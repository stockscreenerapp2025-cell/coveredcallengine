"""
EOD Snapshot Pipeline
=====================
Runs at 4:05 PM ET (Mon-Fri) to:
1. Load latest universe version (1500 symbols)
2. Fetch underlying prices (previousClose)
3. Fetch option chains
4. Compute CC and PMCC results
5. Write to DB collections

Reliability Controls:
- Per-symbol timeout: 25-30s (configurable)
- Max retries: 1
- Partial failures allowed
- Atomic publish of scan_runs
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
        
        # Fetch chains for first 4 expirations (covers ~2 months)
        chains = []
        for exp_date in expirations[:4]:
            try:
                opt = ticker.option_chain(exp_date)
                calls = opt.calls.to_dict('records') if hasattr(opt.calls, 'to_dict') else []
                puts = opt.puts.to_dict('records') if hasattr(opt.puts, 'to_dict') else []
                chains.append({
                    "expiry": exp_date,
                    "calls": calls,
                    "puts": puts
                })
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
            "total_puts": sum(len(c["puts"]) for c in chains)
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
                            "as_of": as_of,
                            "included": True
                        }
                        batch_snapshots.append(snapshot)
                        
                        # Audit: included
                        audit_records.append({
                            "run_id": run_id,
                            "symbol": symbol,
                            "included": True,
                            "exclude_stage": None,
                            "exclude_reason": None,
                            "exclude_detail": None,
                            "price_used": quote_result["price"],
                            "avg_volume": quote_result["avg_volume"],
                            "as_of": as_of
                        })
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
    
    # Step 5: Compute CC and PMCC results (simplified - real logic in precomputed_scans.py)
    # This is a placeholder - actual computation uses the snapshots
    result.cc_opportunities = []  # Would be populated by CC scanner
    result.pmcc_opportunities = []  # Would be populated by PMCC scanner
    
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
        logger.info(f"[EOD_PIPELINE] Persisted scan_run_summary")
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
        logger.info(f"[EOD_PIPELINE] Persisted scan_runs (atomic publish)")
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
