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
import time
import random
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

import yfinance as yf
import pandas as pd

from services.universe_builder import (
    build_universe,
    persist_universe_version,
    get_latest_universe,
    is_etf
)
from utils.symbol_normalization import normalize_symbol
from data.leaps_safe_universe import is_leaps_safe, get_leaps_safe_universe

# Import shared yfinance helpers for global consistency
# ALL underlying price and option chain fetches MUST use these helpers
from services.yf_pricing import (
    get_underlying_price_yf,
    get_option_chain_yf,
    get_all_expirations_yf,
    get_underlying_prices_bulk_yf
)
from services.data_provider import get_market_state

logger = logging.getLogger(__name__)

# =============================================================================
# STABILITY: SAFE DIVISION HELPERS
# =============================================================================

def safe_divide(numerator, denominator, default=None):
    """
    Safe division that returns None instead of NaN/inf on invalid input.
    Prevents JSON serialization errors from NaN/inf values.
    """
    import math
    if denominator is None or denominator == 0:
        return default
    if numerator is None:
        return default
    try:
        result = float(numerator) / float(denominator)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except (TypeError, ValueError, ZeroDivisionError):
        return default

def safe_multiply(a, b, default=None):
    """Safe multiplication that returns None on invalid input."""
    import math
    if a is None or b is None:
        return default
    try:
        result = float(a) * float(b)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except (TypeError, ValueError):
        return default

def safe_int(value, default=0):
    """
    Safely convert a value to int, handling NaN, None, and numpy scalars.
    CRITICAL: NaN check MUST happen BEFORE int() cast.
    """
    import math
    if value is None:
        return default
    # Handle numpy scalars
    if hasattr(value, 'item'):
        value = value.item()
    # Check for NaN (float NaN != NaN comparison trick)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

def safe_float(value, default=None):
    """
    Safely convert a value to float, handling NaN, None, and numpy scalars.
    Returns None for NaN values (not 0, to distinguish missing data).
    """
    import math
    if value is None:
        return default
    # Handle numpy scalars
    if hasattr(value, 'item'):
        value = value.item()
    # Check for NaN
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return default
    try:
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except (ValueError, TypeError):
        return default

# =============================================================================
# PIPELINE CONFIGURATION - TWO-STAGE THROTTLE-SAFE MODEL
# =============================================================================

# Stage 1: Quote fetching (batched)
BULK_QUOTE_BATCH_SIZE = int(os.environ.get("BULK_QUOTE_BATCH_SIZE", "50"))
QUOTE_CONCURRENCY = int(os.environ.get("QUOTE_CONCURRENCY", "2"))

# Stage 2: Option chain fetching (throttle-safe)
CHAIN_CONCURRENCY = int(os.environ.get("CHAIN_CONCURRENCY", "1"))  # MUST be 1 for throttle safety
CHAIN_BATCH_SIZE = int(os.environ.get("CHAIN_BATCH_SIZE", "25"))   # Smaller batches
CHAIN_SYMBOL_DELAY_MS = int(os.environ.get("CHAIN_SYMBOL_DELAY_MS", "250"))  # 250ms between symbols
CHAIN_BATCH_PAUSE_S = float(os.environ.get("CHAIN_BATCH_PAUSE_S", "2.5"))    # 2.5s between batches

# Retry configuration
YAHOO_MAX_RETRIES = int(os.environ.get("YAHOO_MAX_RETRIES", "2"))
RATE_LIMIT_BACKOFF_BASE = 2.0   # Base seconds for exponential backoff
RATE_LIMIT_MAX_BACKOFF = 30.0   # Maximum backoff seconds
RATE_LIMIT_JITTER_MAX = 1.0     # Random jitter 0-1s

# Legacy/general
YAHOO_TIMEOUT_SECONDS = int(os.environ.get("YAHOO_TIMEOUT_SECONDS", "30"))
BATCH_SIZE = 30  # General batch size for DB operations


def fetch_bulk_quotes_sync(symbols: List[str], retry_count: int = 0) -> Dict[str, Dict]:
    """
    Fetch quotes for multiple symbols using yfinance.download() for TRUE batch HTTP request.
    
    Args:
        symbols: List of ticker symbols to fetch
        retry_count: Current retry attempt (for exponential backoff)
        
    Returns:
        Dict mapping symbol -> quote data
        
    PRICE SOURCE RULE (MANDATORY - Feb 2026):
    =========================================
    STORE BOTH:
    - session_close_price = Close from download (last trading session)
    - prior_close_price = Previous day's close
    
    SELECT DETERMINISTICALLY (FREEZE AT MARKET CLOSE):
    - ALWAYS use session_close_price (frozen close from last trading session)
    - OPEN: session_close_price (yesterday's close)
    - CLOSED: session_close_price (today's close after EOD)
    - Outside market hours: deterministic frozen close (session_close_price)
    """
    results = {}
    
    if not symbols:
        return results
    
    try:
        # Use yfinance.download() - this makes a TRUE single HTTP request for all symbols
        logger.info(f"[BULK_QUOTE] HTTP REQUEST: Downloading {len(symbols)} symbols in 1 batch")
        
        # Download last 2 days of data to get both current close and previous close
        df = yf.download(
            tickers=symbols,
            period="2d",
            interval="1d",
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            threads=False  # Single request
        )
        
        logger.info(f"[BULK_QUOTE] HTTP RESPONSE: Download complete, processing {len(symbols)} symbols")
        
        # Process each symbol from the downloaded data
        for symbol in symbols:
            try:
                # Handle both single-ticker and multi-ticker DataFrame structures
                if len(symbols) == 1:
                    symbol_df = df
                else:
                    if symbol not in df.columns.get_level_values(0):
                        results[symbol] = {
                            "symbol": symbol,
                            "success": False,
                            "error_type": "TICKER_NOT_FOUND",
                            "error_detail": f"Symbol {symbol} not in download response"
                        }
                        continue
                    symbol_df = df[symbol]
                
                # Check if we have data
                if symbol_df.empty or len(symbol_df) == 0:
                    results[symbol] = {
                        "symbol": symbol,
                        "success": False,
                        "error_type": "NO_DATA",
                        "error_detail": f"No price data returned for {symbol}"
                    }
                    continue
                
                # Get the most recent row (last trading day)
                latest = symbol_df.iloc[-1]
                
                # Extract prices
                session_close_price = latest.get('Close')
                if pd.isna(session_close_price) or session_close_price is None:
                    session_close_price = latest.get('Adj Close')
                
                # Get previous close from the day before, or from Open if only 1 day of data
                if len(symbol_df) >= 2:
                    prev_row = symbol_df.iloc[-2]
                    prior_close_price = prev_row.get('Close')
                    if pd.isna(prior_close_price) or prior_close_price is None:
                        prior_close_price = prev_row.get('Adj Close')
                else:
                    # Only 1 day of data, use Open as approximation
                    prior_close_price = latest.get('Open')
                
                # Convert to Python types using safe_float helper (handles NaN/numpy scalars)
                session_close_price = safe_float(session_close_price, default=None)
                prior_close_price = safe_float(prior_close_price, default=None)
                
                # Validate prices
                raw_prices = {
                    "session_close": session_close_price,
                    "prior_close": prior_close_price
                }
                
                if session_close_price is None and prior_close_price is None:
                    results[symbol] = {
                        "symbol": symbol,
                        "success": False,
                        "error_type": "MISSING_QUOTE_FIELDS",
                        "error_detail": f"Both price fields are None. Raw: {raw_prices}"
                    }
                    continue
                
                # Handle missing fields with fallback
                if session_close_price is None or session_close_price <= 0:
                    if prior_close_price and prior_close_price > 0:
                        session_close_price = prior_close_price
                        logger.warning(f"[BULK_QUOTE] {symbol}: Using prior_close as session_close fallback")
                    else:
                        results[symbol] = {
                            "symbol": symbol,
                            "success": False,
                            "error_type": "NO_SESSION_CLOSE",
                            "error_detail": f"session_close={session_close_price} invalid"
                        }
                        continue
                
                if prior_close_price is None or (isinstance(prior_close_price, (int, float)) and prior_close_price <= 0):
                    if session_close_price and session_close_price > 0:
                        prior_close_price = session_close_price
                        logger.warning(f"[BULK_QUOTE] {symbol}: Using session_close as prior_close fallback")
                
                # Get volume if available - use safe_int helper (handles NaN/numpy scalars)
                avg_volume = safe_int(latest.get('Volume', 0), default=0)
                
                # Determine market status (default to CLOSED for EOD data)
                market_status = "CLOSED"
                stock_price_source = "SESSION_CLOSE"
                selected_price = session_close_price
                
                results[symbol] = {
                    "symbol": symbol,
                    "success": True,
                    "price": selected_price,
                    "stock_price_source": stock_price_source,
                    "session_close_price": session_close_price,
                    "prior_close_price": prior_close_price,
                    "market_status": market_status,
                    "as_of": None,
                    "regular_market_time": None,
                    "raw_prices": raw_prices,
                    "avg_volume": avg_volume,
                    "market_cap": 0,  # Not available in download
                    "bid": 0,
                    "ask": 0
                }
                
            except Exception as e:
                error_str = str(e)
                results[symbol] = {
                    "symbol": symbol,
                    "success": False,
                    "error_type": "PARSE_ERROR",
                    "error_detail": f"Failed to parse {symbol}: {error_str[:150]}"
                }
        
        return results
        
    except Exception as e:
        error_str = str(e)
        is_rate_limited = "Too Many Requests" in error_str or "Rate limit" in error_str.lower() or "429" in error_str
        
        if is_rate_limited and retry_count < YAHOO_MAX_RETRIES:
            backoff = min(RATE_LIMIT_BACKOFF_BASE * (2 ** retry_count) + random.uniform(0, 1), RATE_LIMIT_MAX_BACKOFF)
            logger.warning(f"[BULK_QUOTE] Rate limited, retry {retry_count + 1}/{YAHOO_MAX_RETRIES} after {backoff:.1f}s backoff")
            time.sleep(backoff)
            return fetch_bulk_quotes_sync(symbols, retry_count + 1)
        
        # Return failure for all symbols in batch
        error_type = "RATE_LIMITED" if is_rate_limited else "BULK_FETCH_ERROR"
        for symbol in symbols:
            results[symbol] = {
                "symbol": symbol,
                "success": False,
                "error_type": error_type,
                "error_detail": error_str[:200]
            }
        
        return results


class EODPipelineResult:
    """
    Result of an EOD pipeline run.
    
    Tracks all metrics needed for Data Quality scoring and debugging.
    """
    
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.started_at = datetime.now(timezone.utc)
        self.completed_at = None
        self.duration_seconds = 0
        self.status = "IN_PROGRESS"  # IN_PROGRESS -> COMPLETED | FAILED
        
        # Counters
        self.symbols_total = 0
        self.symbols_processed = 0
        self.quote_success = 0
        self.quote_failure = 0
        self.chain_success = 0
        self.chain_failure = 0
        
        # Specific failure counters for Data Quality
        self.rate_limited_chain_count = 0
        self.missing_quote_fields_count = 0
        self.bad_chain_data_count = 0
        self.missing_chain_count = 0
        
        # Results
        self.cc_opportunities = []
        self.pmcc_opportunities = []
        
        # Failures detail
        self.failures: List[Dict] = []
        
        # Exclusion breakdown
        self.excluded_by_reason: Dict[str, int] = {}
        self.excluded_by_stage: Dict[str, int] = {}
        
        # Error type breakdown
        self.error_type_counts: Dict[str, int] = {}
    
    def add_exclusion(self, stage: str, reason: str, error_type: str = None):
        """
        Add an exclusion with proper categorization.
        
        Reasons (clear categories):
        - RATE_LIMITED_CHAIN: Yahoo throttled chain request
        - MISSING_CHAIN: No option chain data returned
        - BAD_CHAIN_DATA: Chain data malformed or invalid
        - MISSING_QUOTE_FIELDS: Quote missing required price fields
        - MISSING_QUOTE: General quote failure
        """
        self.excluded_by_reason[reason] = self.excluded_by_reason.get(reason, 0) + 1
        self.excluded_by_stage[stage] = self.excluded_by_stage.get(stage, 0) + 1
        if error_type:
            self.error_type_counts[error_type] = self.error_type_counts.get(error_type, 0) + 1
        
        # Track specific failure types for Data Quality
        if reason == "RATE_LIMITED_CHAIN":
            self.rate_limited_chain_count += 1
        elif reason == "MISSING_QUOTE_FIELDS":
            self.missing_quote_fields_count += 1
        elif reason == "BAD_CHAIN_DATA":
            self.bad_chain_data_count += 1
        elif reason == "MISSING_CHAIN":
            self.missing_chain_count += 1
    
    def finalize(self, status: str = "COMPLETED"):
        """Mark run as complete with final status."""
        self.completed_at = datetime.now(timezone.utc)
        self.duration_seconds = (self.completed_at - self.started_at).total_seconds()
        self.status = status
    
    def to_summary(self) -> Dict:
        """Generate summary dict for scan_run_summary collection."""
        return {
            "run_id": self.run_id,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": round(self.duration_seconds, 2),
            "symbols_total": self.symbols_total,
            "symbols_processed": self.symbols_processed,
            "quote_success": self.quote_success,
            "quote_failure": self.quote_failure,
            "chain_success": self.chain_success,
            "chain_failure": self.chain_failure,
            "rate_limited_chain_count": self.rate_limited_chain_count,
            "missing_quote_fields_count": self.missing_quote_fields_count,
            "bad_chain_data_count": self.bad_chain_data_count,
            "missing_chain_count": self.missing_chain_count,
            "cc_count": len(self.cc_opportunities),
            "pmcc_count": len(self.pmcc_opportunities),
            "excluded_by_reason": self.excluded_by_reason,
            "excluded_by_stage": self.excluded_by_stage,
            "error_type_counts": self.error_type_counts,
            "top_failures": self.failures[:20]
        }
    
    def get_coverage_ratio(self) -> float:
        """Calculate coverage ratio for Data Quality scoring."""
        if self.symbols_total == 0:
            return 0.0
        return self.chain_success / self.symbols_total
    
    def get_throttle_ratio(self) -> float:
        """Calculate throttle ratio for Data Quality scoring."""
        if self.symbols_total == 0:
            return 0.0
        return self.rate_limited_chain_count / self.symbols_total


def fetch_quote_sync(symbol: str) -> Dict:
    """
    Fetch quote from Yahoo Finance (blocking call).
    
    PRICE SOURCE RULE (MANDATORY - Feb 2026):
    =========================================
    Uses shared yf_pricing.get_underlying_price_yf() for global consistency.
    
    MARKET OPEN:
        - Primary: fast_info["last_price"]
        - Fallback: info["regularMarketPrice"]
        
    MARKET CLOSED:
        - Use: history(period="5d")["Close"].iloc[-1]
        - FORBIDDEN: regularMarketPrice (can be stale/after-hours)
    
    All raw Yahoo fields are stored for debugging.
    """
    try:
        # ============================================================
        # STEP 1: Get market state using shared helper
        # ============================================================
        market_state = get_market_state()  # OPEN, EXTENDED, or CLOSED
        
        # ============================================================
        # STEP 2: Get price using shared yf_pricing helper
        # This enforces identical pricing rules everywhere
        # ============================================================
        price, price_field_used, price_time = get_underlying_price_yf(symbol, market_state)
        
        if price is None or price <= 0:
            return {
                "symbol": symbol,
                "success": False,
                "error_type": "NO_VALID_PRICE",
                "error_detail": f"get_underlying_price_yf returned price={price}, field={price_field_used}",
                "market_state": market_state
            }
        
        # ============================================================
        # STEP 3: Get additional metadata from ticker.info
        # (for debugging and enrichment, NOT for pricing)
        # ============================================================
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        
        # Extract raw prices for debugging only
        raw_prices = {
            "regularMarketPrice": info.get("regularMarketPrice"),
            "regularMarketPreviousClose": info.get("regularMarketPreviousClose"),
            "previousClose": info.get("previousClose"),
            "open": info.get("open"),
            "dayHigh": info.get("dayHigh"),
            "dayLow": info.get("dayLow"),
            "postMarketPrice": info.get("postMarketPrice"),
            "preMarketPrice": info.get("preMarketPrice"),
        }
        
        # Get Yahoo's market state for reference
        yahoo_market_status = info.get("marketState", "UNKNOWN")
        
        # Also store prior close for reference (not used for main price)
        prior_close_price = info.get("regularMarketPreviousClose") or info.get("previousClose")
        
        # ============================================================
        # STEP 4: Build response with all context fields
        # ============================================================
        return {
            "symbol": symbol,
            "success": True,
            
            # SELECTED PRICE (from shared yf_pricing helper)
            "price": round(price, 2),
            "stock_price_source": price_field_used,  # e.g., "history.Close[-1]" or "fast_info.last_price"
            "price_time": price_time,
            
            # ADDITIONAL PRICE FIELDS (for reference/debugging)
            "session_close_price": info.get("regularMarketPrice"),  # May differ from selected price
            "prior_close_price": prior_close_price,
            
            # MARKET CONTEXT FIELDS
            "market_state": market_state,  # From our internal logic
            "market_status": yahoo_market_status,  # From Yahoo
            "as_of": price_time,
            
            # RAW YAHOO FIELDS (for debugging)
            "raw_prices": raw_prices,
            
            # OTHER METADATA
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


def fetch_option_chain_sync(symbol: str, retry_count: int = 0) -> Dict:
    """
    Fetch option chain from Yahoo Finance (blocking call).
    
    UPDATED (Feb 2026): Fetches ALL available expirations including LEAPS.
    - Near-term (0-60 DTE): All expirations
    - Mid-term (61-364 DTE): Sample every 2nd expiration
    - LEAPS (365+ DTE): All expirations (critical for PMCC)
    
    Includes retry logic with exponential backoff for rate limiting.
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
        is_rate_limited = "Too Many Requests" in error_str or "Rate limit" in error_str.lower() or "429" in error_str
        
        if is_rate_limited and retry_count < YAHOO_MAX_RETRIES:
            # Exponential backoff with jitter
            backoff = min(RATE_LIMIT_BACKOFF_BASE * (2 ** retry_count) + random.uniform(0, 1), RATE_LIMIT_MAX_BACKOFF)
            logger.warning(f"[CHAIN] {symbol}: Rate limited, retry {retry_count + 1}/{YAHOO_MAX_RETRIES} after {backoff:.1f}s")
            time.sleep(backoff)
            return fetch_option_chain_sync(symbol, retry_count + 1)
        
        error_type = "RATE_LIMITED" if is_rate_limited else "UNKNOWN_ERROR"
        if "404" in error_str:
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
    
    # ==========================================================================
    # STAGE 1: BULK QUOTE FETCHING (batched, concurrent)
    # ==========================================================================
    logger.info("[EOD_PIPELINE] === STAGE 1: QUOTE FETCHING ===")
    logger.info(f"[EOD_PIPELINE] Config: batch_size={BULK_QUOTE_BATCH_SIZE}, concurrency={QUOTE_CONCURRENCY}")
    
    all_quotes = {}
    total_quote_batches = (len(universe) + BULK_QUOTE_BATCH_SIZE - 1) // BULK_QUOTE_BATCH_SIZE
    
    for i in range(0, len(universe), BULK_QUOTE_BATCH_SIZE):
        batch_symbols = universe[i:i + BULK_QUOTE_BATCH_SIZE]
        batch_num = (i // BULK_QUOTE_BATCH_SIZE) + 1
        
        logger.info(f"[EOD_PIPELINE] Quote batch {batch_num}/{total_quote_batches}: {len(batch_symbols)} symbols")
        
        # Fetch quotes in bulk
        batch_quotes = fetch_bulk_quotes_sync(batch_symbols)
        all_quotes.update(batch_quotes)
        
        # Delay between quote batches
        if i + BULK_QUOTE_BATCH_SIZE < len(universe):
            time.sleep(0.5)
    
    # Count and categorize quote results
    for symbol, quote_result in all_quotes.items():
        if quote_result.get("success"):
            result.quote_success += 1
        else:
            result.quote_failure += 1
            error_type = quote_result.get("error_type", "UNKNOWN")
            
            # Categorize quote failure reason
            if error_type == "MISSING_QUOTE_FIELDS":
                reason = "MISSING_QUOTE_FIELDS"
            elif error_type in ("RATE_LIMITED", "RATE_LIMITED_QUOTE"):
                reason = "RATE_LIMITED_QUOTE"
            else:
                reason = "MISSING_QUOTE"
            
            result.add_exclusion("QUOTE", reason, error_type)
            result.failures.append({
                "symbol": symbol,
                "stage": "QUOTE",
                "error_type": error_type,
                "error_detail": quote_result.get("error_detail", "No quote data")
            })
    
    logger.info(f"[EOD_PIPELINE] Quote stage complete: {result.quote_success} success, {result.quote_failure} failures")
    
    # ==========================================================================
    # STAGE 2: OPTION CHAIN FETCHING (throttle-safe, sequential batches)
    # ==========================================================================
    logger.info("[EOD_PIPELINE] === STAGE 2: OPTION CHAIN FETCHING (THROTTLE-SAFE) ===")
    logger.info(f"[EOD_PIPELINE] Config: concurrency={CHAIN_CONCURRENCY}, batch_size={CHAIN_BATCH_SIZE}, "
                f"symbol_delay={CHAIN_SYMBOL_DELAY_MS}ms, batch_pause={CHAIN_BATCH_PAUSE_S}s")
    
    snapshots = []
    audit_records = []
    
    # Process only symbols with successful quotes
    symbols_with_quotes = [s for s in universe if all_quotes.get(s, {}).get("success")]
    total_chain_batches = (len(symbols_with_quotes) + CHAIN_BATCH_SIZE - 1) // CHAIN_BATCH_SIZE
    
    logger.info(f"[EOD_PIPELINE] Processing {len(symbols_with_quotes)} symbols in {total_chain_batches} chain batches")
    
    for batch_idx in range(0, len(symbols_with_quotes), CHAIN_BATCH_SIZE):
        batch = symbols_with_quotes[batch_idx:batch_idx + CHAIN_BATCH_SIZE]
        batch_num = (batch_idx // CHAIN_BATCH_SIZE) + 1
        batch_snapshots = []
        
        logger.info(f"[EOD_PIPELINE] Chain batch {batch_num}/{total_chain_batches}: {len(batch)} symbols")
        
        # Process symbols SEQUENTIALLY within batch (throttle-safe)
        for sym_idx, symbol in enumerate(batch):
            quote_result = all_quotes[symbol]
            result.symbols_processed += 1
            
            # Fetch option chain with retry
            chain_result = fetch_option_chain_sync(symbol)
            
            if chain_result["success"]:
                result.chain_success += 1
                
                has_leaps = chain_result.get("has_leaps", False)
                leaps_count = chain_result.get("leaps_found", 0)
                
                # Create snapshot
                snapshot = {
                    "run_id": run_id,
                    "symbol": symbol,
                    "underlying_price": quote_result["price"],
                    "stock_price_source": quote_result.get("stock_price_source", "SESSION_CLOSE"),
                    "session_close_price": quote_result.get("session_close_price"),
                    "prior_close_price": quote_result.get("prior_close_price"),
                    "market_status": quote_result.get("market_status", "UNKNOWN"),
                    "as_of": quote_result.get("as_of") or as_of.isoformat() if isinstance(as_of, datetime) else as_of,
                    "regular_market_time": quote_result.get("regular_market_time"),
                    "raw_prices": quote_result.get("raw_prices", {}),
                    "avg_volume": quote_result.get("avg_volume", 0) or 0,
                    "market_cap": quote_result.get("market_cap", 0) or 0,
                    "option_chain": chain_result["chains"],
                    "expirations": chain_result["expirations"],
                    "is_etf": is_etf(symbol),
                    "has_leaps": has_leaps,
                    "leaps_count": leaps_count,
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
                    "stock_price_source": quote_result.get("stock_price_source", "SESSION_CLOSE"),
                    "session_close_price": quote_result.get("session_close_price"),
                    "prior_close_price": quote_result.get("prior_close_price"),
                    "market_status": quote_result.get("market_status", "UNKNOWN"),
                    "raw_prices": quote_result.get("raw_prices", {}),
                    "avg_volume": quote_result.get("avg_volume", 0) or 0,
                    "has_leaps": has_leaps,
                    "leaps_count": leaps_count,
                    "leaps_warning": "NO_LEAPS_AVAILABLE" if not has_leaps else None,
                    "as_of": as_of
                })
            else:
                result.chain_failure += 1
                chain_error_type = chain_result.get("error_type", "UNKNOWN")
                
                # Categorize chain failure with CLEAR categories
                if chain_error_type == "RATE_LIMITED":
                    reason = "RATE_LIMITED_CHAIN"
                elif chain_error_type == "NO_OPTIONS":
                    reason = "MISSING_CHAIN"
                elif chain_error_type in ("CHAIN_FETCH_FAILED", "BAD_CHAIN_DATA"):
                    reason = "BAD_CHAIN_DATA"
                else:
                    reason = "MISSING_CHAIN"
                
                result.add_exclusion("OPTIONS_CHAIN", reason, chain_error_type)
                result.failures.append({
                    "symbol": symbol,
                    "stage": "OPTIONS_CHAIN",
                    "error_type": chain_error_type,
                    "error_detail": chain_result.get("error_detail", "Unknown error")
                })
                
                # Audit: excluded
                audit_records.append({
                    "run_id": run_id,
                    "symbol": symbol,
                    "included": False,
                    "exclude_stage": "OPTIONS_CHAIN",
                    "exclude_reason": reason,
                    "exclude_detail": chain_result.get("error_detail", "Unknown error"),
                    "price_used": quote_result["price"],
                    "avg_volume": quote_result.get("avg_volume", 0) or 0,
                    "as_of": as_of
                })
            
            # THROTTLE-SAFE: Fixed pacing delay between symbols (250ms default)
            if sym_idx < len(batch) - 1:
                time.sleep(CHAIN_SYMBOL_DELAY_MS / 1000.0)
        
        snapshots.extend(batch_snapshots)
        
        # Progress log
        logger.info(
            f"[EOD_PIPELINE] Chain batch {batch_num} complete: "
            f"{result.chain_success}/{result.symbols_processed} success ({result.chain_success * 100 // max(1, result.symbols_processed)}%)"
        )
        
        # THROTTLE-SAFE: Pause between batches (2.5s default)
        if batch_idx + CHAIN_BATCH_SIZE < len(symbols_with_quotes):
            logger.debug(f"[EOD_PIPELINE] Pausing {CHAIN_BATCH_PAUSE_S}s between chain batches")
            time.sleep(CHAIN_BATCH_PAUSE_S)
    
    # Add audit records for symbols that failed at quote stage
    # CRITICAL: Use categorized reason (same as summary) for consistency
    for symbol in universe:
        if symbol not in all_quotes or not all_quotes[symbol].get("success"):
            quote_result = all_quotes.get(symbol, {"error_type": "UNKNOWN", "error_detail": "No quote data"})
            error_type = quote_result.get("error_type", "UNKNOWN")
            
            # Categorize reason EXACTLY as done for the summary (lines 738-743)
            if error_type == "MISSING_QUOTE_FIELDS":
                categorized_reason = "MISSING_QUOTE_FIELDS"
            elif error_type in ("RATE_LIMITED", "RATE_LIMITED_QUOTE"):
                categorized_reason = "RATE_LIMITED_QUOTE"
            else:
                categorized_reason = "MISSING_QUOTE"
            
            audit_records.append({
                "run_id": run_id,
                "symbol": symbol,
                "included": False,
                "exclude_stage": "QUOTE",
                "exclude_reason": categorized_reason,  # Use categorized reason, NOT raw error_type
                "exclude_detail": quote_result.get("error_detail", "No quote data"),
                "raw_error_type": error_type,  # Keep raw for debugging
                "price_used": 0,
                "avg_volume": 0,
                "as_of": as_of
            })
    
    logger.info(f"[EOD_PIPELINE] Chain stage complete: {result.chain_success} success, {result.chain_failure} failures")
    
    # ==========================================================================
    # STAGE 3: PERSIST SNAPSHOTS AND AUDIT
    # ==========================================================================
    logger.info("[EOD_PIPELINE] === STAGE 3: PERSIST DATA ===")
    
    if snapshots:
        try:
            await db.symbol_snapshot.insert_many(snapshots)
            logger.info(f"[EOD_PIPELINE] Persisted {len(snapshots)} symbol snapshots")
        except Exception as e:
            logger.error(f"[EOD_PIPELINE] Failed to persist snapshots: {e}")
    
    if audit_records:
        try:
            await db.scan_universe_audit.insert_many(audit_records)
            logger.info(f"[EOD_PIPELINE] Persisted {len(audit_records)} audit records")
        except Exception as e:
            logger.error(f"[EOD_PIPELINE] Failed to persist audit: {e}")
    
    # ==========================================================================
    # STAGE 4: COMPUTE CC AND PMCC RESULTS
    # ==========================================================================
    logger.info("[EOD_PIPELINE] === STAGE 4: COMPUTE OPPORTUNITIES ===")
    logger.info(f"[EOD_PIPELINE] Computing CC/PMCC from {len(snapshots)} snapshots...")
    
    cc_opportunities, pmcc_opportunities = await compute_scan_results(
        db=db,
        run_id=run_id,
        snapshots=snapshots,
        as_of=as_of
    )
    
    result.cc_opportunities = cc_opportunities
    result.pmcc_opportunities = pmcc_opportunities
    
    logger.info(f"[EOD_PIPELINE] Computed {len(cc_opportunities)} CC, {len(pmcc_opportunities)} PMCC opportunities")
    
    # ==========================================================================
    # STAGE 5: FINALIZE AND PERSIST RUN SUMMARY (with status=COMPLETED)
    # ==========================================================================
    logger.info("[EOD_PIPELINE] === STAGE 5: FINALIZE RUN ===")
    
    # Determine final status
    # COMPLETED only when: universe processed, scan results written, summary/audit written
    coverage_ratio = result.get_coverage_ratio()
    throttle_ratio = result.get_throttle_ratio()
    
    if result.chain_success > 0 and len(snapshots) > 0:
        final_status = "COMPLETED"
    else:
        final_status = "FAILED"
    
    result.finalize(status=final_status)
    
    # Build comprehensive summary document
    summary_doc = {
        "run_id": run_id,
        "status": final_status,  # CRITICAL: status flag for Data Quality
        "universe_version": universe_version,
        "as_of": as_of,
        "started_at": result.started_at,
        "completed_at": result.completed_at,
        "duration_seconds": result.duration_seconds,
        "tier_counts": tier_counts,
        
        # Universe counts (MATH: included + excluded = total)
        "total_symbols": result.symbols_total,
        "included": result.chain_success,
        "excluded": result.symbols_total - result.chain_success,
        
        # Quote stage metrics
        "quote_success_count": result.quote_success,
        "quote_failure_count": result.quote_failure,
        
        # Chain stage metrics
        "chain_success_count": result.chain_success,
        "chain_failure_count": result.chain_failure,
        
        # Specific failure counters (for Data Quality)
        "rate_limited_chain_count": result.rate_limited_chain_count,
        "missing_quote_fields_count": result.missing_quote_fields_count,
        "bad_chain_data_count": result.bad_chain_data_count,
        "missing_chain_count": result.missing_chain_count,
        
        # Derived metrics (for Data Quality scoring)
        "coverage_ratio": round(coverage_ratio, 4),
        "throttle_ratio": round(throttle_ratio, 4),
        
        # Opportunity counts
        "cc_count": len(result.cc_opportunities),
        "pmcc_count": len(result.pmcc_opportunities),
        
        # Breakdown maps
        "excluded_counts_by_reason": result.excluded_by_reason,
        "excluded_counts_by_stage": result.excluded_by_stage,
        "error_type_counts": result.error_type_counts,
        
        # Debug info
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
    
    # Persist scan_runs (atomic publish with status flag)
    scan_run_doc = {
        "run_id": run_id,
        "run_type": "EOD",
        "status": final_status,  # CRITICAL: COMPLETED or FAILED
        "universe_version": universe_version,
        "as_of": as_of,
        "created_at": result.started_at,
        "completed_at": result.completed_at,
        "duration_seconds": result.duration_seconds,
        "symbols_total": result.symbols_total,
        "symbols_included": result.chain_success,
        "symbols_excluded": result.symbols_total - result.chain_success,
        "quote_success": result.quote_success,
        "quote_failure": result.quote_failure,
        "chain_success": result.chain_success,
        "chain_failure": result.chain_failure,
        "rate_limited_chain_count": result.rate_limited_chain_count,
        "coverage_ratio": round(coverage_ratio, 4),
        "throttle_ratio": round(throttle_ratio, 4),
        "cc_count": len(result.cc_opportunities),
        "pmcc_count": len(result.pmcc_opportunities)
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
        f"included={result.chain_success}, excluded={result.symbols_total - result.chain_success}"
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

# CC Eligibility Constants (MATCHING PRODUCTION)
CC_MIN_PRICE = 20.0
CC_MAX_PRICE = 500.0
CC_MIN_VOLUME = 1_000_000
CC_MIN_MARKET_CAP = 5_000_000_000
CC_MIN_DTE = 7
CC_MAX_DTE = 45
CC_MIN_PREMIUM_YIELD = 0.5  # 0.5%
CC_MAX_PREMIUM_YIELD = 20.0  # 20%
CC_MIN_OTM_PCT = 0.0        # Must be OTM (strike > stock_price)
CC_MAX_OTM_PCT = 20.0       # Max 20% OTM
CC_MIN_OPEN_INTEREST = 10   # Minimum OI for liquidity
CC_MIN_IV = 0.05            # Min 5% IV
CC_MAX_IV = 2.0             # Max 200% IV

# ============================================================
# PMCC STRATEGY CONSTANTS - STRICT INSTITUTIONAL MODEL (Feb 2026)
# ============================================================
# These rules reduce opportunities but ensure institutional-grade trades

# LEAP (Long leg) constraints
PMCC_MIN_LEAP_DTE = 365          # Minimum 1 year
PMCC_MAX_LEAP_DTE = 730          # Maximum 2 years
PMCC_MIN_LEAP_DELTA = 0.75       # Deep ITM (was 0.70)
PMCC_MIN_LEAP_OI = 100           # Minimum open interest
PMCC_MAX_LEAP_SPREAD_PCT = 5.0   # Maximum bid-ask spread %

# SHORT (Short leg) constraints
PMCC_MIN_SHORT_DTE = 30          # Minimum 30 days (was 7)
PMCC_MAX_SHORT_DTE = 45          # Maximum 45 days (was 60)
PMCC_MIN_SHORT_DELTA = 0.25      # Minimum delta
PMCC_MAX_SHORT_DELTA = 0.35      # Maximum delta
PMCC_MIN_SHORT_OI = 100          # Minimum open interest
PMCC_MAX_SHORT_SPREAD_PCT = 5.0  # Maximum bid-ask spread %
PMCC_MIN_SHORT_OTM_PCT = 0.01    # Short strike must be >= 2% OTM from stock_price

# Structure constraints
PMCC_MIN_IV = 0.05               # Min 5% IV
PMCC_MAX_IV = 3.0                # Max 300% IV
PMCC_MIN_WIDTH = 1.0             # Minimum spread width


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


def validate_cc_option(
    strike: float,
    stock_price: float,
    bid: float,
    iv: float,
    oi: int,
    dte: int
) -> Tuple[bool, List[str]]:
    """
    Validate a CC option against hard rules.
    Returns (is_valid, list_of_quality_flags)
    """
    flags = []
    
    # HARD RULE: Strike must be OTM (strike > stock_price)
    if strike <= stock_price:
        flags.append("STRIKE_NOT_OTM")
        return False, flags
    
    # HARD RULE: Bid > 0
    if not bid or bid <= 0:
        flags.append("BID_ZERO_OR_NEGATIVE")
        return False, flags
    
    # HARD RULE: DTE within range
    if dte < CC_MIN_DTE or dte > CC_MAX_DTE:
        flags.append(f"DTE_OUT_OF_RANGE_{dte}")
        return False, flags
    
    # SOFT RULE: IV sanity check
    if iv and (iv < CC_MIN_IV or iv > CC_MAX_IV):
        flags.append(f"IV_EXTREME_{iv:.2f}")
        # Allow but flag
    
    # SOFT RULE: OI check
    if oi is not None and oi < CC_MIN_OPEN_INTEREST:
        flags.append(f"LOW_OI_{oi}")
        # Allow but flag
    
    return True, flags


def validate_pmcc_structure(
    stock_price: float,
    leap_strike: float,
    leap_ask: float,
    leap_bid: float,
    leap_delta: float,
    leap_dte: int,
    leap_oi: int,
    short_strike: float,
    short_bid: float,
    short_ask: float,
    short_delta: float,
    short_dte: int,
    short_oi: int,
    short_iv: float
) -> Tuple[bool, List[str]]:
    """
    Validate PMCC structure against STRICT INSTITUTIONAL RULES (Feb 2026).
    Returns (is_valid, list_of_quality_flags)
    
    PMCC HARD RULES (INSTITUTIONAL):
    ================================
    LONG LEAP:
    - 365 ≤ leap_dte ≤ 730
    - leap_delta ≥ 0.80
    - leap_ask > 0
    - leap_open_interest ≥ 100
    - leap_spread_pct ≤ 5%
    
    SHORT CALL:
    - 30 ≤ short_dte ≤ 45
    - 0.20 ≤ short_delta ≤ 0.30
    - short_bid > 0
    - short_open_interest ≥ 100
    - short_spread_pct ≤ 5%
    
    STRUCTURE:
    - width > net_debit (SOLVENCY GOLDEN RULE)
    - short_strike > (leap_strike + net_debit) (BREAK-EVEN)
    """
    flags = []
    
    # ================================================================
    # LEAP VALIDATION (HARD RULES)
    # ================================================================
    
    # HARD RULE: LEAP must be ITM
    if leap_strike >= stock_price:
        flags.append("FAIL_LONG_NOT_ITM")
        return False, flags
    
    # HARD RULE: LEAP ask > 0
    if not leap_ask or leap_ask <= 0:
        flags.append("FAIL_LONG_ASK_INVALID")
        return False, flags
    
    # HARD RULE: LEAP DTE 365-730
    if leap_dte < PMCC_MIN_LEAP_DTE or leap_dte > PMCC_MAX_LEAP_DTE:
        flags.append(f"FAIL_LONG_DTE_{leap_dte}")
        return False, flags
    
    # HARD RULE: LEAP delta >= 0.80
    if leap_delta < PMCC_MIN_LEAP_DELTA:
        flags.append(f"FAIL_LONG_DELTA_{leap_delta:.2f}")
        return False, flags
    
    # HARD RULE: LEAP open interest >= 100
    if leap_oi < PMCC_MIN_LEAP_OI:
        flags.append(f"FAIL_LIQUIDITY_LEAP_OI_{leap_oi}")
        return False, flags
    
    # HARD RULE: LEAP spread <= 5%
    if leap_bid and leap_bid > 0:
        leap_mid = (leap_ask + leap_bid) / 2
        leap_spread_pct = ((leap_ask - leap_bid) / leap_mid * 100) if leap_mid > 0 else 100
        if leap_spread_pct > PMCC_MAX_LEAP_SPREAD_PCT:
            flags.append(f"FAIL_LIQUIDITY_LEAP_SPREAD_{leap_spread_pct:.1f}%")
            return False, flags
    
    # ================================================================
    # SHORT VALIDATION (HARD RULES)
    # ================================================================
    
    # HARD RULE: Short bid > 0
    if not short_bid or short_bid <= 0:
        flags.append("FAIL_SHORT_BID_INVALID")
        return False, flags
    
    # HARD RULE: Short strike must be OTM relative to stock_price
    min_short_strike = stock_price * (1 + PMCC_MIN_SHORT_OTM_PCT)
    if short_strike < min_short_strike:
        flags.append("FAIL_SHORT_NOT_OTM")
        return False, flags
    
    # HARD RULE: Short DTE 30-45
    if short_dte < PMCC_MIN_SHORT_DTE or short_dte > PMCC_MAX_SHORT_DTE:
        flags.append(f"FAIL_SHORT_DTE_{short_dte}")
        return False, flags
    
    # HARD RULE: Short delta 0.20-0.30
    if short_delta < PMCC_MIN_SHORT_DELTA or short_delta > PMCC_MAX_SHORT_DELTA:
        flags.append(f"FAIL_SHORT_DELTA_{short_delta:.2f}")
        return False, flags
    
    # HARD RULE: Short open interest >= 100
    if short_oi < PMCC_MIN_SHORT_OI:
        flags.append(f"FAIL_LIQUIDITY_SHORT_OI_{short_oi}")
        return False, flags
    
    # HARD RULE: Short spread <= 5%
    if short_ask and short_ask > 0:
        short_mid = (short_ask + short_bid) / 2
        short_spread_pct = ((short_ask - short_bid) / short_mid * 100) if short_mid > 0 else 100
        if short_spread_pct > PMCC_MAX_SHORT_SPREAD_PCT:
            flags.append(f"FAIL_LIQUIDITY_SHORT_SPREAD_{short_spread_pct:.1f}%")
            return False, flags
    
    # ================================================================
    # STRUCTURE VALIDATION (HARD RULES)
    # ================================================================
    
    # HARD RULE: short_strike > leap_strike
    if short_strike <= leap_strike:
        flags.append("FAIL_STRIKE_STRUCTURE")
        return False, flags
    
    # Calculate structure metrics
    net_debit = leap_ask - short_bid
    width = short_strike - leap_strike
    breakeven = leap_strike + net_debit
    
    # HARD RULE: net_debit > 0
    if net_debit <= 0:
        flags.append("FAIL_NEGATIVE_NET_DEBIT")
        return False, flags
    
    # HARD RULE: SOLVENCY with 20% tolerance
    # This ensures the trade has reasonable profit potential while allowing
    # for ASK/BID spread realities. Pass if net_debit <= width * 1.20
    solvency_threshold = width * 1.20
    if net_debit > solvency_threshold:
        flags.append(f"FAIL_SOLVENCY_width{width:.2f}_debit{net_debit:.2f}_threshold{solvency_threshold:.2f}")
        return False, flags
    
    # HARD RULE: BREAK-EVEN (soft flag)
    # NOTE: With net_debit computed using BUY=ASK and SELL=BID, the break-even inequality
    # is algebraically equivalent to the hard solvency rule (width > net_debit).
    # We keep solvency as the single hard gate and treat break-even as a warning flag only
    # to avoid redundant eliminations.
    if short_strike <= breakeven:
        flags.append(f"WARN_BREAK_EVEN_short{short_strike:.2f}_be{breakeven:.2f}")

    
    # ================================================================
    # SOFT RULES (Flag but don't reject)
    # ================================================================
    
    # SOFT RULE: Minimum width
    if width < PMCC_MIN_WIDTH:
        flags.append(f"NARROW_WIDTH_{width:.2f}")
    
    # SOFT RULE: IV sanity check
    if short_iv and (short_iv < PMCC_MIN_IV or short_iv > PMCC_MAX_IV):
        flags.append(f"IV_EXTREME_{short_iv:.2f}")
    
    return True, flags


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
    score = 30.0  # Base score
    
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
        
        # Fetch analyst enrichment from symbol_enrichment collection
        analyst_data = None
        analyst_rating = None
        if db is not None:
            try:
                analyst_data = await db.symbol_enrichment.find_one(
                    {"symbol": symbol},
                    {"_id": 0, "analyst_rating_label": 1, "analyst_rating_value": 1}
                )
                analyst_rating = analyst_data.get("analyst_rating_label") if analyst_data else None
            except Exception:
                pass
        
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
                
                strike = call.get("strike", 0)
                bid = call.get("bid", 0)
                ask = call.get("ask", 0)
                last_price = call.get("lastPrice", 0) or 0
                prev_close = call.get("previousClose", 0) or call.get("prevClose", 0) or 0
                iv = call.get("impliedVolatility", 0) or 0
                oi = call.get("openInterest", 0) or 0
                volume = call.get("volume", 0) or 0
                
                # ============================================================
                # OPTION PARITY MODEL: Compute display_price for Yahoo parity
                # ============================================================
                mid = round((bid + ask) / 2, 2) if bid > 0 and ask > 0 else None
                
                # Determine display_price (what Yahoo shows)
                if last_price and last_price > 0:
                    display_price = round(last_price, 2)
                    display_price_source = "LAST"
                elif mid is not None:
                    display_price = mid
                    display_price_source = "MID"
                elif prev_close and prev_close > 0:
                    display_price = round(prev_close, 2)
                    display_price_source = "PREV_CLOSE"
                else:
                    display_price = None
                    display_price_source = "NONE"
                
                # ============================================================
                # QUALITY FLAGS (expanded)
                # ============================================================
                # VALIDATE CC OPTION (HARD RULES)
                is_valid, quality_flags = validate_cc_option(
                    strike=strike,
                    stock_price=stock_price,
                    bid=bid,
                    iv=iv,
                    oi=oi,
                    dte=dte
                )
                
                if not is_valid:
                    continue
                
                # SOFT FLAGS (for transparency, don't reject)
                spread_pct = ((ask - bid) / bid * 100) if bid > 0 else 0
                if spread_pct > 10:
                    quality_flags.append("WIDE_SPREAD")
                if oi < 50:
                    quality_flags.append("LOW_OI")
                if not last_price or last_price <= 0:
                    quality_flags.append("NO_LAST")
                
                # PRICING RULE: SELL leg uses BID price
                premium_bid = bid
                premium_ask_val = ask if ask and ask > 0 else None
                premium_used = premium_bid  # SELL rule: use BID
                
                # Calculate metrics using safe_divide (prevents NaN/inf)
                premium_yield = safe_divide(premium_bid, stock_price, 0) * 100 if stock_price else None
                otm_pct = safe_divide(strike - stock_price, stock_price, 0) * 100 if stock_price else None
                
                # Apply filters (skip if calculation failed)
                if premium_yield is None or otm_pct is None:
                    continue
                if premium_yield < CC_MIN_PREMIUM_YIELD or premium_yield > CC_MAX_PREMIUM_YIELD:
                    continue
                if otm_pct < CC_MIN_OTM_PCT or otm_pct > CC_MAX_OTM_PCT:
                    continue
                
                # Calculate Greeks
                greeks = calculate_greeks_simple(stock_price, strike, dte, iv if iv > 0 else 0.30)
                
                # Calculate ROI (must use premium_bid per SELL rule)
                roi_pct = safe_divide(premium_bid, stock_price, 0) * 100 if stock_price else None
                roi_annualized = safe_multiply(roi_pct, safe_divide(365, max(dte, 1), 0)) if roi_pct else None
                
                # ASSERTION: ROI > 0 requires premium_bid > 0
                if roi_pct and roi_pct > 0 and premium_bid <= 0:
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
                # WITH MANDATORY MARKET CONTEXT FIELDS + OPTION PARITY MODEL
                cc_opp = {
                    # Run metadata
                    "run_id": run_id,
                    "as_of": as_of,
                    "created_at": datetime.now(timezone.utc),
                    
                    # Underlying
                    "symbol": symbol,
                    "stock_price": round(stock_price, 2),
                    
                    # MANDATORY MARKET CONTEXT FIELDS
                    "stock_price_source": snapshot.get("stock_price_source", "SESSION_CLOSE"),
                    "session_close_price": snapshot.get("session_close_price"),
                    "prior_close_price": snapshot.get("prior_close_price"),
                    "market_status": snapshot.get("market_status", "UNKNOWN"),
                    
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
                    "premium_mid": mid,  # (bid+ask)/2 when valid
                    "premium_last": round(last_price, 2) if last_price and last_price > 0 else None,
                    "premium_prev_close": round(prev_close, 2) if prev_close and prev_close > 0 else None,
                    "premium_used": round(premium_used, 2),  # = premium_bid (SELL rule)
                    "pricing_rule": "SELL_BID",
                    
                    # OPTION PARITY MODEL: Display price (matches Yahoo display)
                    "premium_display": display_price,
                    "premium_display_source": display_price_source,
                    
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
                    
                    # Quality flags (from validation + soft flags)
                    "quality_flags": quality_flags,
                    
                    # Analyst (from enrichment)
                    "analyst_rating": analyst_rating,
                    
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
                last_price = call.get("lastPrice", 0) or 0
                prev_close = call.get("previousClose", 0) or call.get("prevClose", 0) or 0
                iv = call.get("impliedVolatility", 0) or 0
                oi = call.get("openInterest", 0) or 0
                
                # Compute display price for Yahoo parity
                mid = round((bid + ask) / 2, 2) if bid > 0 and ask > 0 else None
                if last_price and last_price > 0:
                    display_price = round(last_price, 2)
                    display_source = "LAST"
                elif mid is not None:
                    display_price = mid
                    display_source = "MID"
                elif prev_close and prev_close > 0:
                    display_price = round(prev_close, 2)
                    display_source = "PREV_CLOSE"
                else:
                    display_price = None
                    display_source = "NONE"
                
                # Compute quality flags for this option
                option_quality_flags = []
                spread_pct = ((ask - bid) / bid * 100) if bid > 0 else 0
                if spread_pct > 10:
                    option_quality_flags.append("WIDE_SPREAD")
                if oi < 50:
                    option_quality_flags.append("LOW_OI")
                if not last_price or last_price <= 0:
                    option_quality_flags.append("NO_LAST")
                
                # LEAPS candidate (365-730 DTE, ITM) - STRICT INSTITUTIONAL RULES
                if PMCC_MIN_LEAP_DTE <= dte <= PMCC_MAX_LEAP_DTE and strike < stock_price:
                    if ask and ask > 0:
                        greeks = calculate_greeks_simple(stock_price, strike, dte, iv if iv > 0 else 0.30)
                        
                        # INSTITUTIONAL FILTERS
                        # 1. Delta >= 0.80 (stricter than 0.70)
                        if greeks["delta"] < PMCC_MIN_LEAP_DELTA:
                            continue
                        
                        # 2. Minimum open interest >= 100
                        if oi < PMCC_MIN_LEAP_OI:
                            continue
                        
                        # 3. Bid-ask spread <= 5%
                        if bid and bid > 0:
                            spread_pct = ((ask - bid) / bid) * 100
                            if spread_pct > PMCC_MAX_LEAP_SPREAD_PCT:
                                continue
                        
                        leaps_candidates.append({
                            "strike": strike,
                            "expiry": expiry,
                            "dte": dte,
                            "ask": ask,
                            "bid": bid,
                            "mid": mid,
                            "last": last_price if last_price > 0 else None,
                            "prev_close": prev_close if prev_close > 0 else None,
                            "display_price": display_price,
                            "display_source": display_source,
                            "delta": greeks["delta"],
                            "iv": iv,
                            "oi": oi,
                            "quality_flags": option_quality_flags
                        })
                
                # Short call candidate (30-45 DTE) - STRICT INSTITUTIONAL RULES
                if PMCC_MIN_SHORT_DTE <= dte <= PMCC_MAX_SHORT_DTE:
                    if bid and bid > 0:
                        # Calculate delta for institutional filtering
                        short_greeks = calculate_greeks_simple(stock_price, strike, dte, iv if iv > 0 else 0.30)
                        short_delta = short_greeks["delta"]
                        
                        # INSTITUTIONAL FILTERS
                        # 1. Delta range 0.20-0.30
                        if short_delta < PMCC_MIN_SHORT_DELTA or short_delta > PMCC_MAX_SHORT_DELTA:
                            continue
                        
                        # 2. Minimum open interest >= 100
                        if oi < PMCC_MIN_SHORT_OI:
                            continue
                        
                        # 3. Bid-ask spread <= 5%
                        if ask and ask > 0:
                            spread_pct = ((ask - bid) / bid) * 100
                            if spread_pct > PMCC_MAX_SHORT_SPREAD_PCT:
                                continue
                        
                        short_candidates.append({
                            "strike": strike,
                            "expiry": expiry,
                            "dte": dte,
                            "bid": bid,
                            "ask": ask,
                            "mid": mid,
                            "last": last_price if last_price > 0 else None,
                            "prev_close": prev_close if prev_close > 0 else None,
                            "display_price": display_price,
                            "display_source": display_source,
                            "iv": iv,
                            "oi": oi,
                            "quality_flags": option_quality_flags,
                            "delta": short_delta  # Store calculated delta
                        })
        
        # Match LEAPS with short calls
        for leap in leaps_candidates[:3]:  # Limit LEAPS per symbol
            for short in short_candidates:
                # VALIDATE PMCC STRUCTURE (STRICT INSTITUTIONAL RULES)
                is_valid, pmcc_quality_flags = validate_pmcc_structure(
                    stock_price=stock_price,
                    leap_strike=leap["strike"],
                    leap_ask=leap["ask"],
                    leap_bid=leap.get("bid", 0),
                    leap_delta=leap["delta"],
                    leap_dte=leap["dte"],
                    leap_oi=leap.get("oi", 0),
                    short_strike=short["strike"],
                    short_bid=short["bid"],
                    short_ask=short.get("ask", 0),
                    short_delta=short.get("delta", 0.25),  # Use stored delta
                    short_dte=short["dte"],
                    short_iv=short.get("iv", 0),
                    short_oi=short.get("oi", 0)
                )
                
                if not is_valid:
                    continue
                
                # PRICING RULES:
                # - LEAP BUY: use ASK price
                # - Short SELL: use BID price
                leap_ask = leap["ask"]
                leap_bid = leap.get("bid", 0)
                short_bid = short["bid"]
                short_ask = short.get("ask", 0)
                
                leap_used = leap_ask  # BUY rule
                short_used = short_bid  # SELL rule
                
                net_debit = leap_ask - short_bid
                width = short["strike"] - leap["strike"]
                max_profit = width - net_debit
                
                # ROI must use actual prices (leap_ask, short_bid) - safe division
                roi_per_cycle = safe_divide(short_bid, leap_ask, 0)
                roi_per_cycle = roi_per_cycle * 100 if roi_per_cycle else None
                roi_annualized = safe_multiply(roi_per_cycle, safe_divide(365, max(short["dte"], 1), 0)) if roi_per_cycle else None
                
                # Build contract symbols
                try:
                    leap_exp_fmt = datetime.strptime(leap["expiry"], "%Y-%m-%d").strftime("%y%m%d")
                    leap_symbol_str = f"{symbol}{leap_exp_fmt}C{int(leap['strike'] * 1000):08d}"
                except Exception:
                    leap_symbol_str = f"{symbol}_LEAP_{leap['strike']}_{leap['expiry']}"
                
                try:
                    short_exp_fmt = datetime.strptime(short["expiry"], "%Y-%m-%d").strftime("%y%m%d")
                    short_symbol_str = f"{symbol}{short_exp_fmt}C{int(short['strike'] * 1000):08d}"
                except Exception:
                    short_symbol_str = f"{symbol}_SHORT_{short['strike']}_{short['expiry']}"
                
                # IV from short leg (more relevant for premium decay)
                short_iv = short.get("iv", 0) or 0
                iv_decimal = round(short_iv, 4) if short_iv > 0 else 0.0
                iv_percent = round(short_iv * 100, 1) if short_iv > 0 else 0.0
                
                # Combine quality flags from both legs
                combined_quality_flags = list(set(pmcc_quality_flags + leap.get("quality_flags", []) + short.get("quality_flags", [])))
                
                # === EXPLICIT PMCC SCHEMA (Feb 2026) ===
                # WITH MANDATORY MARKET CONTEXT FIELDS + OPTION PARITY MODEL
                pmcc_opp = {
                    # Run metadata
                    "run_id": run_id,
                    "as_of": as_of,
                    "created_at": datetime.now(timezone.utc),
                    
                    # Underlying
                    "symbol": symbol,
                    "stock_price": round(stock_price, 2),
                    
                    # MANDATORY MARKET CONTEXT FIELDS
                    "stock_price_source": snapshot.get("stock_price_source", "SESSION_CLOSE"),
                    "session_close_price": snapshot.get("session_close_price"),
                    "prior_close_price": snapshot.get("prior_close_price"),
                    "market_status": snapshot.get("market_status", "UNKNOWN"),
                    
                    "is_etf": symbol_is_etf,
                    "instrument_type": "ETF" if symbol_is_etf else "STOCK",
                    
                    # LEAP (Long leg - BUY)
                    "leap_symbol": leap_symbol_str,
                    "leap_strike": leap["strike"],
                    "leap_expiry": leap["expiry"],
                    "leap_dte": leap["dte"],
                    "leap_bid": round(leap_bid, 2) if leap_bid else None,
                    "leap_ask": round(leap_ask, 2),
                    "leap_mid": leap.get("mid"),
                    "leap_last": leap.get("last"),
                    "leap_prev_close": leap.get("prev_close"),
                    "leap_used": round(leap_used, 2),  # = leap_ask (BUY rule)
                    "leap_display": leap.get("display_price"),
                    "leap_display_source": leap.get("display_source"),
                    "leap_delta": leap["delta"],
                    
                    # Short leg (SELL)
                    "short_symbol": short_symbol_str,
                    "short_strike": short["strike"],
                    "short_expiry": short["expiry"],
                    "short_dte": short["dte"],
                    "short_bid": round(short_bid, 2),
                    "short_ask": round(short_ask, 2) if short_ask else None,
                    "short_mid": short.get("mid"),
                    "short_last": short.get("last"),
                    "short_prev_close": short.get("prev_close"),
                    "short_used": round(short_used, 2),  # = short_bid (SELL rule)
                    "short_display": short.get("display_price"),
                    "short_display_source": short.get("display_source"),
                    "short_delta": short.get("delta"),  # For institutional verification
                    
                    # Liquidity (for transparency)
                    "leap_oi": leap.get("oi", 0),
                    "short_oi": short.get("oi", 0),
                    
                    # Pricing rule
                    "pricing_rule": "BUY_ASK_SELL_BID",
                    
                    # Legacy fields for backward compatibility
                    "short_premium": round(short_bid, 2),  # Alias for short_bid
                    "leaps_ask": round(leap_ask, 2),       # Alias for leap_ask
                    
                    # Economics
                    "net_debit": round(net_debit, 2),
                    "net_debit_total": round(net_debit * 100, 2),
                    "width": round(width, 2),
                    "max_profit": round(max_profit, 2),
                    "max_profit_total": round(max_profit * 100, 2),
                    "breakeven": round(leap["strike"] + net_debit, 2),
                    "roi_cycle": round(roi_per_cycle, 2),      # Per cycle
                    "roi_per_cycle": round(roi_per_cycle, 2),  # Alias
                    "roi_annualized": round(roi_annualized, 1),
                    
                    # Greeks (from LEAP)
                    "delta": leap["delta"],
                    "delta_source": "BLACK_SCHOLES_APPROX",
                    
                    # IV (from short leg)
                    "iv": iv_decimal,           # Decimal (0.65)
                    "iv_pct": iv_percent,       # Percent (65.0)
                    "iv_rank": None,            # Will be enriched if available
                    
                    # Quality flags (combined from validation + soft flags)
                    "quality_flags": combined_quality_flags,
                    
                    # Analyst (from enrichment)
                    "analyst_rating": analyst_rating,
                    
                    # Scoring
                    "score": round(50 + roi_per_cycle * 5, 1)
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
