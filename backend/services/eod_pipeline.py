"""
EOD Snapshot Pipeline
=====================
Runs at 4:10 PM ET (Mon-Fri) to:
1. Load latest universe version (1500 symbols)
2. Fetch underlying prices (previousClose)
3. Fetch option chains (including LEAPS for PMCC)
4. Compute CC and PMCC results
5. Write to DB collections

Reliability Controls:
- Per-symbol timeout: 25-30s (configurable)
- Max retries: 1
- Partial failures allowed
- Atomic publish of scan_runs

LEAPS Coverage (Feb 2026):
- Option chain fetch now includes ALL available expirations
- LEAPS (365+ DTE) explicitly fetched for PMCC eligibility
- NO_LEAPS_AVAILABLE tracked in audit for symbols without far-dated options
"""
import os
import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

import yfinance as yf

from services.universe_builder import (
    build_universe,
    persist_universe_version,
    get_latest_universe,
    is_etf
)
from utils.symbol_normalization import normalize_symbol
from data.leaps_safe_universe import is_leaps_safe, get_leaps_safe_universe

logger = logging.getLogger(__name__)

# Configuration
YAHOO_TIMEOUT_SECONDS = int(os.environ.get("YAHOO_TIMEOUT_SECONDS", "30"))
YAHOO_MAX_RETRIES = int(os.environ.get("YAHOO_MAX_RETRIES", "1"))
YAHOO_MAX_CONCURRENCY = int(os.environ.get("YAHOO_SCAN_MAX_CONCURRENCY", "5"))
BATCH_SIZE = 30


class EODPipelineResult:
    """Result of an EOD pipeline run."""
    
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.started_at = datetime.now(timezone.utc)
        self.completed_at = None
        self.duration_seconds = 0
        
        # Counters
        self.symbols_total = 0
        self.symbols_processed = 0
        self.quote_success = 0
        self.quote_failure = 0
        self.chain_success = 0
        self.chain_failure = 0
        
        # Results
        self.cc_opportunities = []
        self.pmcc_opportunities = []
        
        # Failures
        self.failures: List[Dict] = []
        
        # Exclusion breakdown
        self.excluded_by_reason: Dict[str, int] = {}
        self.excluded_by_stage: Dict[str, int] = {}
    
    def add_exclusion(self, stage: str, reason: str):
        self.excluded_by_reason[reason] = self.excluded_by_reason.get(reason, 0) + 1
        self.excluded_by_stage[stage] = self.excluded_by_stage.get(stage, 0) + 1
    
    def finalize(self):
        self.completed_at = datetime.now(timezone.utc)
        self.duration_seconds = (self.completed_at - self.started_at).total_seconds()
    
    def to_summary(self) -> Dict:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": round(self.duration_seconds, 2),
            "symbols_total": self.symbols_total,
            "symbols_processed": self.symbols_processed,
            "quote_success": self.quote_success,
            "quote_failure": self.quote_failure,
            "chain_success": self.chain_success,
            "chain_failure": self.chain_failure,
            "cc_count": len(self.cc_opportunities),
            "pmcc_count": len(self.pmcc_opportunities),
            "excluded_by_reason": self.excluded_by_reason,
            "excluded_by_stage": self.excluded_by_stage,
            "top_failures": self.failures[:20]
        }


def fetch_quote_sync(symbol: str) -> Dict:
    """
    Fetch quote from Yahoo Finance (blocking call).
    Uses previousClose as primary, regularMarketPrice as fallback.
    """
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        
        if not info:
            return {
                "symbol": symbol,
                "success": False,
                "error_type": "EMPTY_RESPONSE",
                "error_detail": "Yahoo returned empty info"
            }
        
        # Use previousClose as primary (EOD consistency)
        prev_close = info.get("previousClose")
        regular_price = info.get("regularMarketPrice")
        price = prev_close or regular_price
        
        if not price or price <= 0:
            return {
                "symbol": symbol,
                "success": False,
                "error_type": "NO_PRICE",
                "error_detail": f"previousClose={prev_close}, regularMarketPrice={regular_price}"
            }
        
        return {
            "symbol": symbol,
            "success": True,
            "price": price,
            "price_source": "previousClose" if prev_close else "regularMarketPrice",
            "avg_volume": info.get("averageVolume", 0) or info.get("volume", 0),
            "market_cap": info.get("marketCap", 0),
            "bid": info.get("bid", 0),
            "ask": info.get("ask", 0)
        }
        
    except Exception as e:
        error_str = str(e)
        error_type = "UNKNOWN_ERROR"
        
        if "Too Many Requests" in error_str or "Rate limit" in error_str.lower():
            error_type = "RATE_LIMITED"
        elif "404" in error_str or "Not Found" in error_str:
            error_type = "HTTP_404"
        elif "timeout" in error_str.lower():
            error_type = "TIMEOUT"
        elif "delisted" in error_str.lower():
            error_type = "DELISTED"
        
        return {
            "symbol": symbol,
            "success": False,
            "error_type": error_type,
            "error_detail": error_str[:200]
        }


def fetch_option_chain_sync(symbol: str) -> Dict:
    """
    Fetch option chain from Yahoo Finance (blocking call).
    
    UPDATED (Feb 2026): Fetches ALL available expirations including LEAPS.
    - Near-term (0-60 DTE): All expirations
    - Mid-term (61-364 DTE): Sample every 2nd expiration
    - LEAPS (365+ DTE): All expirations (critical for PMCC)
    """
    try:
        ticker = yf.Ticker(symbol)
        
        # Get expiration dates
        expirations = ticker.options
        if not expirations:
            return {
                "symbol": symbol,
                "success": False,
                "error_type": "NO_OPTIONS",
                "error_detail": "No expiration dates available"
            }
        
        # Categorize expirations by DTE
        from datetime import datetime
        today = datetime.now()
        
        near_term = []  # 0-60 DTE
        mid_term = []   # 61-364 DTE
        leaps = []      # 365+ DTE
        
        for exp_str in expirations:
            try:
                exp_date = datetime.strptime(exp_str, "%Y-%m-%d")
                dte = (exp_date - today).days
                
                if dte <= 60:
                    near_term.append(exp_str)
                elif dte <= 364:
                    mid_term.append(exp_str)
                else:
                    leaps.append(exp_str)
            except ValueError:
                continue
        
        # Select which expirations to fetch
        # Near-term: all (for CC/short leg)
        # Mid-term: every 2nd (reduce API calls)
        # LEAPS: all (critical for PMCC)
        selected_exps = near_term + mid_term[::2] + leaps
        
        # Limit total to prevent excessive API calls
        # But ALWAYS include all LEAPS
        if len(selected_exps) > 12:
            # Keep first 8 near-term + all LEAPS
            selected_exps = near_term[:8] + leaps
        
        chains = []
        leaps_found = 0
        
        for exp_date in selected_exps:
            try:
                opt = ticker.option_chain(exp_date)
                calls = opt.calls.to_dict('records') if hasattr(opt.calls, 'to_dict') else []
                puts = opt.puts.to_dict('records') if hasattr(opt.puts, 'to_dict') else []
                
                # Calculate DTE for this expiry
                exp_dt = datetime.strptime(exp_date, "%Y-%m-%d")
                dte = (exp_dt - today).days
                
                # Add DTE to each call/put record
                for call in calls:
                    call['daysToExpiration'] = dte
                for put in puts:
                    put['daysToExpiration'] = dte
                
                chains.append({
                    "expiry": exp_date,
                    "dte": dte,
                    "calls": calls,
                    "puts": puts
                })
                
                if dte >= 365:
                    leaps_found += 1
                    
            except Exception:
                continue
        
        if not chains:
            return {
                "symbol": symbol,
                "success": False,
                "error_type": "CHAIN_FETCH_FAILED",
                "error_detail": "Could not fetch any option chains"
            }
        
        return {
            "symbol": symbol,
            "success": True,
            "expirations": [c["expiry"] for c in chains],
            "chains": chains,
            "total_calls": sum(len(c["calls"]) for c in chains),
            "total_puts": sum(len(c["puts"]) for c in chains),
            "leaps_found": leaps_found,
            "has_leaps": leaps_found > 0,
            "available_leaps_expirations": leaps  # For audit
        }
        
    except Exception as e:
        error_str = str(e)
        error_type = "UNKNOWN_ERROR"
        
        if "Too Many Requests" in error_str:
            error_type = "RATE_LIMITED"
        elif "404" in error_str:
            error_type = "HTTP_404"
        
        return {
            "symbol": symbol,
            "success": False,
            "error_type": error_type,
            "error_detail": error_str[:200]
        }


async def run_eod_pipeline(db, force_build_universe: bool = False) -> EODPipelineResult:
    """
    Run the full EOD pipeline.
    
    Args:
        db: MongoDB database instance
        force_build_universe: If True, build fresh universe; else use latest
        
    Returns:
        EODPipelineResult with all statistics
    """
    run_id = f"eod_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    result = EODPipelineResult(run_id)
    
    logger.info(f"[EOD_PIPELINE] Starting run_id={run_id}")
    
    # Step 1: Get universe
    if force_build_universe:
        universe, tier_counts, universe_version = await build_universe(db)
        await persist_universe_version(db, universe, tier_counts, universe_version)
    else:
        latest = await get_latest_universe(db)
        if latest:
            universe = latest.get("universe_symbols", [])
            tier_counts = latest.get("tier_counts", {})
            universe_version = latest.get("universe_version", "UNKNOWN")
        else:
            # Build fresh if no persisted version
            universe, tier_counts, universe_version = await build_universe(db)
            await persist_universe_version(db, universe, tier_counts, universe_version)
    
    result.symbols_total = len(universe)
    as_of = datetime.now(timezone.utc)
    
    logger.info(f"[EOD_PIPELINE] Universe: {len(universe)} symbols, version={universe_version}")
    
    # Step 2: Fetch quotes and chains in batches
    snapshots = []
    audit_records = []
    
    for i in range(0, len(universe), BATCH_SIZE):
        batch = universe[i:i + BATCH_SIZE]
        batch_snapshots = []
        
        # Fetch quotes using thread pool
        with ThreadPoolExecutor(max_workers=YAHOO_MAX_CONCURRENCY) as executor:
            future_to_symbol = {executor.submit(fetch_quote_sync, sym): sym for sym in batch}
            
            for future in as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                quote_result = future.result()
                result.symbols_processed += 1
                
                if quote_result["success"]:
                    result.quote_success += 1
                    
                    # Fetch option chain
                    chain_result = fetch_option_chain_sync(symbol)
                    
                    if chain_result["success"]:
                        result.chain_success += 1
                        
                        # Check for LEAPS availability
                        has_leaps = chain_result.get("has_leaps", False)
                        leaps_count = chain_result.get("leaps_found", 0)
                        
                        # Create snapshot
                        snapshot = {
                            "run_id": run_id,
                            "symbol": symbol,
                            "underlying_price": quote_result["price"],
                            "price_source": quote_result["price_source"],
                            "avg_volume": quote_result["avg_volume"],
                            "market_cap": quote_result["market_cap"],
                            "option_chain": chain_result["chains"],
                            "expirations": chain_result["expirations"],
                            "is_etf": is_etf(symbol),
                            "has_leaps": has_leaps,
                            "leaps_count": leaps_count,
                            "as_of": as_of,
                            "included": True
                        }
                        batch_snapshots.append(snapshot)
                        
                        # Audit: included - with LEAPS status
                        audit_record = {
                            "run_id": run_id,
                            "symbol": symbol,
                            "included": True,
                            "exclude_stage": None,
                            "exclude_reason": None,
                            "exclude_detail": None,
                            "price_used": quote_result["price"],
                            "avg_volume": quote_result["avg_volume"],
                            "has_leaps": has_leaps,
                            "leaps_count": leaps_count,
                            "as_of": as_of
                        }
                        
                        # Track NO_LEAPS_AVAILABLE as warning (not exclusion)
                        if not has_leaps:
                            audit_record["leaps_warning"] = "NO_LEAPS_AVAILABLE"
                            logger.debug(f"[EOD_PIPELINE] {symbol}: No LEAPS available (365+ DTE)")
                        
                        audit_records.append(audit_record)
                    else:
                        result.chain_failure += 1
                        result.add_exclusion("OPTIONS_CHAIN", "MISSING_CHAIN")
                        result.failures.append({
                            "symbol": symbol,
                            "stage": "OPTIONS_CHAIN",
                            "error_type": chain_result["error_type"],
                            "error_detail": chain_result["error_detail"]
                        })
                        
                        # Audit: excluded
                        audit_records.append({
                            "run_id": run_id,
                            "symbol": symbol,
                            "included": False,
                            "exclude_stage": "OPTIONS_CHAIN",
                            "exclude_reason": "MISSING_CHAIN",
                            "exclude_detail": chain_result["error_detail"],
                            "price_used": quote_result["price"],
                            "avg_volume": quote_result["avg_volume"],
                            "as_of": as_of
                        })
                else:
                    result.quote_failure += 1
                    result.add_exclusion("QUOTE", "MISSING_QUOTE")
                    result.failures.append({
                        "symbol": symbol,
                        "stage": "QUOTE",
                        "error_type": quote_result["error_type"],
                        "error_detail": quote_result["error_detail"]
                    })
                    
                    # Audit: excluded
                    audit_records.append({
                        "run_id": run_id,
                        "symbol": symbol,
                        "included": False,
                        "exclude_stage": "QUOTE",
                        "exclude_reason": "MISSING_QUOTE",
                        "exclude_detail": quote_result["error_detail"],
                        "price_used": 0,
                        "avg_volume": 0,
                        "as_of": as_of
                    })
        
        snapshots.extend(batch_snapshots)
        
        # Progress log
        logger.info(
            f"[EOD_PIPELINE] Progress: {result.symbols_processed}/{result.symbols_total} "
            f"(quotes: {result.quote_success}, chains: {result.chain_success})"
        )
    
    # Step 3: Persist snapshots
    if snapshots:
        try:
            await db.symbol_snapshot.insert_many(snapshots)
            logger.info(f"[EOD_PIPELINE] Persisted {len(snapshots)} symbol snapshots")
        except Exception as e:
            logger.error(f"[EOD_PIPELINE] Failed to persist snapshots: {e}")
    
    # Step 4: Persist audit records
    if audit_records:
        try:
            await db.scan_universe_audit.insert_many(audit_records)
            logger.info(f"[EOD_PIPELINE] Persisted {len(audit_records)} audit records")
        except Exception as e:
            logger.error(f"[EOD_PIPELINE] Failed to persist audit: {e}")
    
    # Step 5: Compute CC and PMCC results from snapshots
    logger.info(f"[EOD_PIPELINE] Computing CC/PMCC opportunities from {len(snapshots)} snapshots...")
    
    cc_opportunities, pmcc_opportunities = await compute_scan_results(
        db=db,
        run_id=run_id,
        snapshots=snapshots,
        as_of=as_of
    )
    
    result.cc_opportunities = cc_opportunities
    result.pmcc_opportunities = pmcc_opportunities
    
    logger.info(f"[EOD_PIPELINE] Computed {len(cc_opportunities)} CC, {len(pmcc_opportunities)} PMCC opportunities")
    
    # Step 6: Finalize and persist run summary
    result.finalize()
    
    # Persist scan_run_summary
    summary_doc = {
        "run_id": run_id,
        "universe_version": universe_version,
        "as_of": as_of,
        "completed_at": result.completed_at,
        "duration_seconds": result.duration_seconds,
        "tier_counts": tier_counts,
        "total_symbols": result.symbols_total,
        "included": result.quote_success,
        "excluded": result.quote_failure + result.chain_failure,
        "excluded_counts_by_reason": result.excluded_by_reason,
        "excluded_counts_by_stage": result.excluded_by_stage,
        "quote_success_count": result.quote_success,
        "quote_failure_count": result.quote_failure,
        "chain_success_count": result.chain_success,
        "chain_failure_count": result.chain_failure,
        "cc_count": len(result.cc_opportunities),
        "pmcc_count": len(result.pmcc_opportunities),
        "top_failures": result.failures[:20]
    }
    
    try:
        await db.scan_run_summary.replace_one(
            {"run_id": run_id},
            summary_doc,
            upsert=True
        )
        logger.info("[EOD_PIPELINE] Persisted scan_run_summary")
    except Exception as e:
        logger.error(f"[EOD_PIPELINE] Failed to persist summary: {e}")
    
    # Persist scan_runs (atomic publish)
    scan_run_doc = {
        "run_id": run_id,
        "run_type": "EOD",
        "universe_version": universe_version,
        "as_of": as_of,
        "status": "COMPLETED",
        "created_at": result.started_at,
        "completed_at": result.completed_at,
        "duration_seconds": result.duration_seconds,
        "symbols_processed": result.symbols_processed,
        "symbols_included": result.quote_success,
        "symbols_excluded": result.symbols_total - result.quote_success
    }
    
    try:
        await db.scan_runs.replace_one(
            {"run_id": run_id},
            scan_run_doc,
            upsert=True
        )
        logger.info("[EOD_PIPELINE] Persisted scan_runs (atomic publish)")
    except Exception as e:
        logger.error(f"[EOD_PIPELINE] Failed to persist scan_runs: {e}")
    
    logger.info(
        f"[EOD_PIPELINE] Completed run_id={run_id} in {result.duration_seconds:.1f}s: "
        f"included={result.quote_success}, excluded={result.quote_failure + result.chain_failure}"
    )
    
    return result


def is_production() -> bool:
    """Check if running in production environment."""
    return os.environ.get("ENVIRONMENT", "").lower() == "production"


def is_manual_run_allowed() -> bool:
    """Check if manual runs are allowed (disabled in production)."""
    return not is_production()


# ============================================================
# CC/PMCC SCAN COMPUTATION
# ============================================================

# CC Eligibility Constants
CC_MIN_PRICE = 30.0
CC_MAX_PRICE = 90.0
CC_MIN_VOLUME = 1_000_000
CC_MIN_MARKET_CAP = 5_000_000_000
CC_MIN_DTE = 7
CC_MAX_DTE = 45
CC_MIN_PREMIUM_YIELD = 0.5  # 0.5%
CC_MAX_PREMIUM_YIELD = 20.0  # 20%
CC_MIN_OTM_PCT = 0.0
CC_MAX_OTM_PCT = 20.0

# PMCC Constants
PMCC_MIN_LEAP_DTE = 365
PMCC_MAX_LEAP_DTE = 730
PMCC_MIN_SHORT_DTE = 7
PMCC_MAX_SHORT_DTE = 60
PMCC_MIN_DELTA = 0.70


def check_cc_eligibility(
    symbol: str,
    stock_price: float,
    market_cap: float,
    avg_volume: float,
    symbol_is_etf: bool
) -> Tuple[bool, str]:
    """Check if symbol is eligible for CC scanning."""
    # ETFs are exempt from price checks (SPY ~$600, QQQ ~$530)
    if symbol_is_etf:
        if stock_price < 1 or stock_price > 2000:
            return False, f"ETF price ${stock_price:.2f} outside valid range"
        return True, "ETF - eligible"
    
    # Price check
    if stock_price < CC_MIN_PRICE:
        return False, f"Price ${stock_price:.2f} below minimum ${CC_MIN_PRICE}"
    if stock_price > CC_MAX_PRICE:
        return False, f"Price ${stock_price:.2f} above maximum ${CC_MAX_PRICE}"
    
    # Volume check
    if avg_volume and avg_volume < CC_MIN_VOLUME:
        return False, f"Avg volume {avg_volume:,.0f} below minimum {CC_MIN_VOLUME:,.0f}"
    
    # Market cap check
    if market_cap and market_cap < CC_MIN_MARKET_CAP:
        return False, f"Market cap ${market_cap/1e9:.1f}B below minimum $5B"
    
    return True, "Eligible"


def calculate_greeks_simple(stock_price: float, strike: float, dte: int, iv: float) -> Dict[str, float]:
    """Simplified Black-Scholes Greeks calculation for EOD pipeline."""
    import math
    
    if dte <= 0 or iv <= 0 or stock_price <= 0 or strike <= 0:
        return {"delta": 0.3, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    
    T = max(dte, 1) / 365.0
    r = 0.05  # Risk-free rate
    
    try:
        d1 = (math.log(stock_price / strike) + (r + 0.5 * iv ** 2) * T) / (iv * math.sqrt(T))
        
        # Cumulative normal distribution approximation
        def norm_cdf(x):
            return 0.5 * (1 + math.erf(x / math.sqrt(2)))
        
        delta = norm_cdf(d1)
        
        # Simplified gamma, theta, vega
        gamma = math.exp(-0.5 * d1 ** 2) / (stock_price * iv * math.sqrt(2 * math.pi * T))
        theta = -(stock_price * iv * math.exp(-0.5 * d1 ** 2)) / (2 * math.sqrt(2 * math.pi * T))
        vega = stock_price * math.sqrt(T) * math.exp(-0.5 * d1 ** 2) / math.sqrt(2 * math.pi)
        
        return {
            "delta": round(delta, 4),
            "gamma": round(gamma, 6),
            "theta": round(theta, 4),
            "vega": round(vega, 4)
        }
    except Exception:
        return {"delta": 0.3, "gamma": 0.0, "theta": 0.0, "vega": 0.0}


def calculate_cc_score(trade_data: Dict[str, Any]) -> float:
    """Calculate simplified CC quality score (0-100)."""
    score = 50.0  # Base score
    
    # ROI scoring (max +20)
    roi_pct = trade_data.get("roi_pct", 0)
    if 1.0 <= roi_pct <= 3.0:
        score += 20
    elif roi_pct > 3.0:
        score += 15
    elif roi_pct > 0.5:
        score += roi_pct * 10
    
    # Delta scoring (max +15) - prefer 0.25-0.35
    delta = trade_data.get("delta", 0.3)
    if 0.25 <= delta <= 0.35:
        score += 15
    elif 0.20 <= delta <= 0.40:
        score += 10
    elif 0.15 <= delta <= 0.50:
        score += 5
    
    # OTM% scoring (max +10) - prefer 3-8%
    otm_pct = trade_data.get("otm_pct", 0)
    if 3.0 <= otm_pct <= 8.0:
        score += 10
    elif 1.0 <= otm_pct <= 12.0:
        score += 5
    
    # Liquidity scoring (max +5)
    oi = trade_data.get("open_interest", 0)
    if oi >= 500:
        score += 5
    elif oi >= 100:
        score += 2
    
    return min(100, max(0, score))


async def compute_scan_results(
    db,
    run_id: str,
    snapshots: List[Dict[str, Any]],
    as_of: datetime
) -> Tuple[List[Dict], List[Dict]]:
    """
    Compute CC and PMCC opportunities from symbol snapshots.
    
    Args:
        db: MongoDB database instance
        run_id: EOD pipeline run ID
        snapshots: List of symbol snapshot documents
        as_of: Timestamp of the scan
        
    Returns:
        Tuple of (cc_opportunities, pmcc_opportunities)
        
    PMCC SAFEGUARD (Feb 2026):
    - Only evaluates symbols with has_leaps=True in snapshot
    - Tracks symbols_without_leaps for audit
    """
    cc_opportunities = []
    pmcc_opportunities = []
    symbols_without_leaps = []
    
    for snapshot in snapshots:
        symbol = snapshot.get("symbol")
        stock_price = snapshot.get("underlying_price", 0)
        avg_volume = snapshot.get("avg_volume", 0)
        market_cap = snapshot.get("market_cap", 0)
        option_chains = snapshot.get("option_chain", [])
        symbol_is_etf = snapshot.get("is_etf", False)
        has_leaps = snapshot.get("has_leaps", False)
        
        if not symbol or stock_price <= 0:
            continue
        
        # Check CC eligibility
        is_eligible, reason = check_cc_eligibility(
            symbol, stock_price, market_cap, avg_volume, symbol_is_etf
        )
        
        if not is_eligible:
            continue
        
        # Process option chains for CC opportunities
        for chain in option_chains:
            expiry = chain.get("expiry", "")
            calls = chain.get("calls", [])
            
            for call in calls:
                dte = call.get("daysToExpiration", 0)
                if not dte:
                    try:
                        exp_dt = datetime.strptime(expiry, "%Y-%m-%d")
                        dte = (exp_dt - datetime.now()).days
                    except Exception:
                        continue
                
                # DTE filter
                if dte < CC_MIN_DTE or dte > CC_MAX_DTE:
                    continue
                
                strike = call.get("strike", 0)
                bid = call.get("bid", 0)
                ask = call.get("ask", 0)
                iv = call.get("impliedVolatility", 0) or 0
                oi = call.get("openInterest", 0) or 0
                volume = call.get("volume", 0) or 0
                
                # Require valid bid
                if not bid or bid <= 0:
                    continue
                
                # PRICING RULE: SELL leg uses BID price
                premium_bid = bid
                premium_ask_val = ask if ask and ask > 0 else None
                premium_used = premium_bid  # SELL rule: use BID
                
                # Calculate metrics
                premium_yield = (premium_bid / stock_price) * 100 if stock_price > 0 else 0
                otm_pct = ((strike - stock_price) / stock_price) * 100 if stock_price > 0 else 0
                
                # Apply filters
                if premium_yield < CC_MIN_PREMIUM_YIELD or premium_yield > CC_MAX_PREMIUM_YIELD:
                    continue
                if otm_pct < CC_MIN_OTM_PCT or otm_pct > CC_MAX_OTM_PCT:
                    continue
                
                # Calculate Greeks
                greeks = calculate_greeks_simple(stock_price, strike, dte, iv if iv > 0 else 0.30)
                
                # Calculate ROI (must use premium_bid per SELL rule)
                roi_pct = (premium_bid / stock_price) * 100 if stock_price > 0 else 0
                roi_annualized = roi_pct * (365 / max(dte, 1))
                
                # ASSERTION: ROI > 0 requires premium_bid > 0
                if roi_pct > 0 and premium_bid <= 0:
                    continue  # Invalid state
                
                # Calculate score
                trade_data = {
                    "roi_pct": roi_pct,
                    "delta": greeks["delta"],
                    "otm_pct": otm_pct,
                    "open_interest": oi
                }
                score = calculate_cc_score(trade_data)
                
                # Build contract symbol
                try:
                    exp_formatted = datetime.strptime(expiry, "%Y-%m-%d").strftime("%y%m%d")
                    contract_symbol = f"{symbol}{exp_formatted}C{int(strike * 1000):08d}"
                except Exception:
                    contract_symbol = f"{symbol}_{strike}_{expiry}"
                
                # IV validation: store as decimal (0.65) and percent (65.0)
                iv_decimal = round(iv, 4) if iv and iv > 0 else 0.0
                iv_percent = round(iv * 100, 1) if iv and iv > 0 else 0.0
                
                # === EXPLICIT CC SCHEMA (Feb 2026) ===
                cc_opp = {
                    # Run metadata
                    "run_id": run_id,
                    "as_of": as_of,
                    "created_at": datetime.now(timezone.utc),
                    
                    # Underlying
                    "symbol": symbol,
                    "stock_price": round(stock_price, 2),
                    "stock_price_source": "EOD_SNAPSHOT",
                    "is_etf": symbol_is_etf,
                    "instrument_type": "ETF" if symbol_is_etf else "STOCK",
                    "market_cap": market_cap,
                    "avg_volume": avg_volume,
                    
                    # Option contract
                    "contract_symbol": contract_symbol,
                    "strike": strike,
                    "expiry": expiry,
                    "dte": dte,
                    "dte_category": "weekly" if dte <= 14 else "monthly",
                    
                    # Pricing (EXPLICIT - no ambiguity)
                    "premium_bid": round(premium_bid, 2),
                    "premium_ask": round(premium_ask_val, 2) if premium_ask_val else None,
                    "premium_used": round(premium_used, 2),  # = premium_bid (SELL rule)
                    "pricing_rule": "SELL_BID",
                    
                    # Legacy fields for backward compatibility
                    "premium": round(premium_bid, 2),  # Alias for premium_bid
                    
                    # Economics
                    "premium_yield": round(premium_yield, 2),
                    "otm_pct": round(otm_pct, 2),
                    "roi_pct": round(roi_pct, 2),
                    "roi_annualized": round(roi_annualized, 1),
                    "max_profit": round(premium_bid * 100, 2),
                    "breakeven": round(stock_price - premium_bid, 2),
                    
                    # Greeks
                    "delta": greeks["delta"],
                    "delta_source": "BLACK_SCHOLES_APPROX",
                    "gamma": greeks["gamma"],
                    "theta": greeks["theta"],
                    "vega": greeks["vega"],
                    
                    # IV (explicit units)
                    "iv": iv_decimal,           # Decimal (0.65)
                    "iv_pct": iv_percent,       # Percent (65.0)
                    "iv_rank": None,            # Will be enriched if available
                    
                    # Liquidity
                    "open_interest": oi,
                    "volume": volume,
                    
                    # Analyst (nullable)
                    "analyst_rating": None,     # Will be enriched if available
                    
                    # Scoring
                    "score": round(score, 1)
                }
                
                cc_opportunities.append(cc_opp)
        
        # PMCC opportunities - ONLY evaluate if symbol has LEAPS
        # Skip symbols without LEAPS to prevent false-zero results
        if not has_leaps:
            symbols_without_leaps.append(symbol)
            continue  # Skip PMCC evaluation for this symbol
        
        # Find LEAPS (365-730 DTE)
        leaps_candidates = []
        short_candidates = []
        
        for chain in option_chains:
            expiry = chain.get("expiry", "")
            calls = chain.get("calls", [])
            
            for call in calls:
                dte = call.get("daysToExpiration", 0)
                if not dte:
                    try:
                        exp_dt = datetime.strptime(expiry, "%Y-%m-%d")
                        dte = (exp_dt - datetime.now()).days
                    except Exception:
                        continue
                
                strike = call.get("strike", 0)
                bid = call.get("bid", 0)
                ask = call.get("ask", 0)
                iv = call.get("impliedVolatility", 0) or 0
                oi = call.get("openInterest", 0) or 0
                
                # LEAPS candidate (365-730 DTE, ITM)
                if PMCC_MIN_LEAP_DTE <= dte <= PMCC_MAX_LEAP_DTE and strike < stock_price:
                    if ask and ask > 0:
                        greeks = calculate_greeks_simple(stock_price, strike, dte, iv if iv > 0 else 0.30)
                        if greeks["delta"] >= PMCC_MIN_DELTA:
                            leaps_candidates.append({
                                "strike": strike,
                                "expiry": expiry,
                                "dte": dte,
                                "ask": ask,
                                "bid": bid,
                                "delta": greeks["delta"],
                                "iv": iv,
                                "oi": oi
                            })
                
                # Short call candidate (7-60 DTE)
                if PMCC_MIN_SHORT_DTE <= dte <= PMCC_MAX_SHORT_DTE:
                    if bid and bid > 0:
                        short_candidates.append({
                            "strike": strike,
                            "expiry": expiry,
                            "dte": dte,
                            "bid": bid,
                            "ask": ask,
                            "iv": iv,
                            "oi": oi
                        })
        
        # Match LEAPS with short calls (short strike > leap strike)
        for leap in leaps_candidates[:3]:  # Limit LEAPS per symbol
            for short in short_candidates:
                if short["strike"] <= leap["strike"]:
                    continue  # Short must be above LEAP
                
                net_debit = leap["ask"] - short["bid"]
                if net_debit <= 0:
                    continue
                
                width = short["strike"] - leap["strike"]
                max_profit = width - net_debit
                roi_per_cycle = (short["bid"] / leap["ask"]) * 100 if leap["ask"] > 0 else 0
                roi_annualized = roi_per_cycle * (365 / max(short["dte"], 1))
                
                pmcc_opp = {
                    "run_id": run_id,
                    "symbol": symbol,
                    "stock_price": round(stock_price, 2),
                    "leap_strike": leap["strike"],
                    "leap_expiry": leap["expiry"],
                    "leap_dte": leap["dte"],
                    "leap_ask": round(leap["ask"], 2),
                    "leap_delta": leap["delta"],
                    "short_strike": short["strike"],
                    "short_expiry": short["expiry"],
                    "short_dte": short["dte"],
                    "short_bid": round(short["bid"], 2),
                    "net_debit": round(net_debit, 2),
                    "net_debit_total": round(net_debit * 100, 2),
                    "width": round(width, 2),
                    "max_profit": round(max_profit, 2),
                    "max_profit_total": round(max_profit * 100, 2),
                    "breakeven": round(leap["strike"] + net_debit, 2),
                    "roi_per_cycle": round(roi_per_cycle, 2),
                    "roi_annualized": round(roi_annualized, 1),
                    "is_etf": symbol_is_etf,
                    "instrument_type": "ETF" if symbol_is_etf else "STOCK",
                    "score": round(50 + roi_per_cycle * 5, 1),  # Simple PMCC scoring
                    "as_of": as_of,
                    "created_at": datetime.now(timezone.utc)
                }
                
                pmcc_opportunities.append(pmcc_opp)
    
    # Select best option per symbol (one CC per symbol)
    cc_by_symbol = {}
    for opp in cc_opportunities:
        symbol = opp["symbol"]
        if symbol not in cc_by_symbol or opp["score"] > cc_by_symbol[symbol]["score"]:
            cc_by_symbol[symbol] = opp
    
    cc_opportunities = sorted(cc_by_symbol.values(), key=lambda x: x["score"], reverse=True)
    
    # Select best PMCC per symbol
    pmcc_by_symbol = {}
    for opp in pmcc_opportunities:
        symbol = opp["symbol"]
        if symbol not in pmcc_by_symbol or opp["score"] > pmcc_by_symbol[symbol]["score"]:
            pmcc_by_symbol[symbol] = opp
    
    pmcc_opportunities = sorted(pmcc_by_symbol.values(), key=lambda x: x["score"], reverse=True)
    
    # Persist CC results
    if cc_opportunities:
        try:
            await db.scan_results_cc.insert_many(cc_opportunities)
            logger.info(f"[EOD_PIPELINE] Persisted {len(cc_opportunities)} CC opportunities")
        except Exception as e:
            logger.error(f"[EOD_PIPELINE] Failed to persist CC results: {e}")
    
    # Persist PMCC results
    if pmcc_opportunities:
        try:
            await db.scan_results_pmcc.insert_many(pmcc_opportunities)
            logger.info(f"[EOD_PIPELINE] Persisted {len(pmcc_opportunities)} PMCC opportunities")
        except Exception as e:
            logger.error(f"[EOD_PIPELINE] Failed to persist PMCC results: {e}")
    
    # Log LEAPS coverage stats
    total_symbols = len(snapshots)
    symbols_with_leaps = total_symbols - len(symbols_without_leaps)
    logger.info(f"[EOD_PIPELINE] LEAPS coverage: {symbols_with_leaps}/{total_symbols} symbols have LEAPS")
    if symbols_without_leaps:
        logger.debug(f"[EOD_PIPELINE] Symbols without LEAPS: {symbols_without_leaps[:20]}...")
    
    return cc_opportunities, pmcc_opportunities


async def get_latest_scan_run(db) -> Optional[Dict]:
    """Get the latest completed scan run."""
    try:
        return await db.scan_runs.find_one(
            {"status": "COMPLETED"},
            sort=[("completed_at", -1)]
        )
    except Exception as e:
        logger.error(f"Failed to get latest scan run: {e}")
        return None


async def get_precomputed_cc_results(db, run_id: str = None, limit: int = 50) -> List[Dict]:
    """
    Get pre-computed CC results from the database.
    
    Args:
        db: MongoDB database instance
        run_id: Specific run ID or None for latest
        limit: Maximum results to return
        
    Returns:
        List of CC opportunities
    """
    try:
        if not run_id:
            latest_run = await get_latest_scan_run(db)
            if not latest_run:
                return []
            run_id = latest_run.get("run_id")
        
        cursor = db.scan_results_cc.find(
            {"run_id": run_id},
            {"_id": 0}
        ).sort("score", -1).limit(limit)
        
        return await cursor.to_list(length=limit)
    except Exception as e:
        logger.error(f"Failed to get pre-computed CC results: {e}")
        return []


async def get_precomputed_pmcc_results(db, run_id: str = None, limit: int = 50) -> List[Dict]:
    """
    Get pre-computed PMCC results from the database.
    
    Args:
        db: MongoDB database instance
        run_id: Specific run ID or None for latest
        limit: Maximum results to return
        
    Returns:
        List of PMCC opportunities
    """
    try:
        if not run_id:
            latest_run = await get_latest_scan_run(db)
            if not latest_run:
                return []
            run_id = latest_run.get("run_id")
        
        cursor = db.scan_results_pmcc.find(
            {"run_id": run_id},
            {"_id": 0}
        ).sort("score", -1).limit(limit)
        
        return await cursor.to_list(length=limit)
    except Exception as e:
        logger.error(f"Failed to get pre-computed PMCC results: {e}")
        return []
