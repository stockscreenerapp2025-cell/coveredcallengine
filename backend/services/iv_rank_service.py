"""
IV Rank Service - Industry Standard IV Rank & Percentile
========================================================

Implements true IV Rank and IV Percentile using internal observed history.
Stores daily "representative IV" per symbol based on ATM proxy from option chains.

INDUSTRY STANDARD FORMULAS:
- IV Rank = 100 * (iv_current - iv_low) / (iv_high - iv_low)
- IV Percentile = 100 * count(iv_hist < iv_current) / N

DATABASE:
- Collection: iv_history
- TTL: ~450 days
- Unique index: (symbol, trading_date)

BOOTSTRAP BEHAVIOR (to reduce 50/100 clustering):
- < 5 samples: return neutral 50 with LOW confidence
- 5-19 samples: compute true rank with shrinkage toward 50, MEDIUM confidence
- >= 20 samples: true rank/percentile, HIGH confidence (MEDIUM if < 60 samples)

HARD CONSTRAINTS:
- trading_date uses US/Eastern timezone
- All fields always populated, never None/null
- Compute rank BEFORE storing today's value (prevent self-teaching)
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
import pytz

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

# Staged confidence thresholds
MIN_SAMPLES_TOO_FEW = 5       # Below this: pure neutral
MIN_SAMPLES_BOOTSTRAP = 20    # Below this: shrinkage applied
MIN_SAMPLES_HIGH_CONF = 60    # Above this: HIGH confidence

# Target DTE for ATM proxy selection
TARGET_DTE = 35
MIN_DTE_FOR_PROXY = 25
MAX_DTE_FOR_PROXY = 60

# History retention (days)
HISTORY_RETENTION_DAYS = 400

# Collection name
IV_HISTORY_COLLECTION = "iv_history"


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class IVMetrics:
    """Complete IV metrics for a symbol."""
    iv_proxy: float  # Current ATM proxy IV (decimal)
    iv_proxy_pct: float  # Current ATM proxy IV (percentage)
    iv_rank: float  # Industry standard IV Rank (0-100)
    iv_percentile: float  # Industry standard IV Percentile (0-100)
    iv_low: float  # 52-week low IV (decimal)
    iv_high: float  # 52-week high IV (decimal)
    iv_samples: int  # Number of historical samples
    iv_rank_source: str  # Source/quality indicator
    proxy_meta: Dict[str, Any]  # Metadata about proxy selection
    iv_rank_confidence: str = "LOW"  # "LOW", "MEDIUM", "HIGH"
    iv_samples_used: int = 0  # Samples used in calculation (may differ from iv_samples)


# =============================================================================
# ATM PROXY COMPUTATION
# =============================================================================

def compute_iv_atm_proxy(
    options: List[Dict],
    stock_price: float,
    target_dte: int = TARGET_DTE,
    min_dte: int = MIN_DTE_FOR_PROXY,
    max_dte: int = MAX_DTE_FOR_PROXY
) -> Tuple[Optional[float], Dict[str, Any]]:
    """
    Compute representative IV (ATM proxy) from an options chain.
    
    Selection logic:
    1. Filter options within DTE range [min_dte, max_dte]
    2. Find expiry nearest to target_dte
    3. Select strike closest to stock_price (ATM)
    4. Return that option's impliedVolatility
    
    Args:
        options: List of option contracts from chain
        stock_price: Current underlying price
        target_dte: Target DTE for selection (default 35)
        min_dte: Minimum DTE to consider
        max_dte: Maximum DTE to consider
    
    Returns:
        Tuple of (iv_decimal, metadata_dict) or (None, {}) if cannot compute
    """
    if not options or stock_price <= 0:
        return None, {"error": "No options or invalid stock price"}
    
    # Filter options within DTE range with valid IV
    valid_options = []
    for opt in options:
        dte = opt.get("dte", 0)
        iv = opt.get("implied_volatility", 0) or opt.get("iv", 0)
        strike = opt.get("strike", 0)
        
        if min_dte <= dte <= max_dte and iv > 0.01 and iv < 5.0 and strike > 0:
            valid_options.append({
                "strike": strike,
                "expiry": opt.get("expiry", ""),
                "dte": dte,
                "iv": iv,
                "contract": opt.get("contract_ticker", opt.get("symbol", ""))
            })
    
    if not valid_options:
        return None, {"error": "No valid options in DTE range"}
    
    # Find expiry nearest to target_dte
    valid_options.sort(key=lambda x: abs(x["dte"] - target_dte))
    target_expiry = valid_options[0]["expiry"]
    
    # Filter to only that expiry
    expiry_options = [o for o in valid_options if o["expiry"] == target_expiry]
    
    # Select strike closest to stock price (ATM)
    expiry_options.sort(key=lambda x: abs(x["strike"] - stock_price))
    atm_option = expiry_options[0]
    
    iv_decimal = atm_option["iv"]
    
    meta = {
        "selected_strike": atm_option["strike"],
        "selected_expiry": atm_option["expiry"],
        "selected_dte": atm_option["dte"],
        "selected_contract": atm_option["contract"],
        "stock_price": stock_price,
        "options_considered": len(valid_options),
        "target_dte": target_dte
    }
    
    return iv_decimal, meta


# =============================================================================
# DATABASE OPERATIONS
# =============================================================================

def get_trading_date_eastern() -> str:
    """
    Get current trading date in US/Eastern timezone.
    
    Returns date string in YYYY-MM-DD format.
    """
    eastern = pytz.timezone('US/Eastern')
    now_eastern = datetime.now(eastern)
    return now_eastern.strftime('%Y-%m-%d')


async def upsert_iv_history(
    db,
    symbol: str,
    trading_date: str,
    iv_decimal: float,
    meta: Dict[str, Any]
) -> bool:
    """
    Store or update IV history entry (idempotent per date).
    
    Args:
        db: MongoDB database instance
        symbol: Stock symbol (uppercase)
        trading_date: Date string YYYY-MM-DD (US/Eastern)
        iv_decimal: IV value (decimal form, e.g., 0.30)
        meta: Metadata about the proxy selection
    
    Returns:
        True if successful, False otherwise
    """
    try:
        doc = {
            "symbol": symbol.upper(),
            "trading_date": trading_date,
            "iv_atm_proxy": iv_decimal,
            "captured_at": datetime.now(timezone.utc),
            "meta": meta
        }
        
        await db[IV_HISTORY_COLLECTION].update_one(
            {"symbol": symbol.upper(), "trading_date": trading_date},
            {"$set": doc},
            upsert=True
        )
        
        logger.debug(f"Upserted IV history for {symbol} on {trading_date}: IV={iv_decimal:.4f}")
        return True
        
    except Exception as e:
        logger.warning(f"Failed to upsert IV history for {symbol}: {e}")
        return False


async def get_iv_history_series(
    db,
    symbol: str,
    limit_days: int = HISTORY_RETENTION_DAYS
) -> List[float]:
    """
    Retrieve IV history series for a symbol.
    
    Args:
        db: MongoDB database instance
        symbol: Stock symbol
        limit_days: Max days of history to retrieve
    
    Returns:
        List of IV values (decimals), most recent last
    """
    try:
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=limit_days)).strftime('%Y-%m-%d')
        
        cursor = db[IV_HISTORY_COLLECTION].find(
            {
                "symbol": symbol.upper(),
                "trading_date": {"$gte": cutoff_date}
            },
            {"iv_atm_proxy": 1, "trading_date": 1, "_id": 0}
        ).sort("trading_date", 1)
        
        docs = await cursor.to_list(500)
        
        return [doc["iv_atm_proxy"] for doc in docs if doc.get("iv_atm_proxy")]
        
    except Exception as e:
        logger.warning(f"Failed to get IV history for {symbol}: {e}")
        return []


async def ensure_iv_history_indexes(db) -> None:
    """
    Create required indexes for iv_history collection.
    
    Should be called during app startup.
    """
    try:
        # Unique compound index on (symbol, trading_date)
        await db[IV_HISTORY_COLLECTION].create_index(
            [("symbol", 1), ("trading_date", 1)],
            unique=True,
            name="symbol_date_unique"
        )
        
        # Index for efficient lookups by symbol + date range
        await db[IV_HISTORY_COLLECTION].create_index(
            [("symbol", 1), ("captured_at", -1)],
            name="symbol_captured_desc"
        )
        
        # TTL index to auto-expire old data (~450 days)
        await db[IV_HISTORY_COLLECTION].create_index(
            "captured_at",
            expireAfterSeconds=450 * 24 * 60 * 60,
            name="ttl_expire"
        )
        
        logger.info("IV history indexes ensured")
        
    except Exception as e:
        logger.warning(f"Failed to create IV history indexes: {e}")


# =============================================================================
# IV RANK & PERCENTILE CALCULATION
# =============================================================================

def compute_iv_rank_percentile(
    iv_current: float,
    series: List[float]
) -> Dict[str, Any]:
    """
    Compute IV Rank and IV Percentile from historical series.
    
    Industry Standard Formulas:
    - IV Rank = 100 * (iv_current - iv_low) / (iv_high - iv_low)
    - IV Percentile = 100 * count(iv_hist < iv_current) / N
    
    STAGED BOOTSTRAP BEHAVIOR (to reduce 50/100 clustering):
    - < 5 samples: return neutral 50 with LOW confidence
    - 5-19 samples: compute true rank with shrinkage toward 50, MEDIUM confidence
    - >= 20 samples: true rank/percentile unchanged, HIGH/MEDIUM confidence
    
    Shrinkage formula (5-19 samples):
        w = samples / 20
        iv_rank = 50 + w * (raw_iv_rank - 50)
    
    Args:
        iv_current: Current IV proxy value (decimal)
        series: Historical IV values (decimals)
    
    Returns:
        Dict with iv_rank, iv_percentile, iv_low, iv_high, iv_samples, 
        iv_rank_source, iv_rank_confidence, iv_samples_used
    """
    sample_count = len(series)
    
    # ==========================================================================
    # STAGE 1: Too few samples (< 5) - Pure neutral
    # ==========================================================================
    if sample_count < MIN_SAMPLES_TOO_FEW:
        return {
            "iv_rank": 50.0,
            "iv_percentile": 50.0,
            "iv_low": 0.0,
            "iv_high": 0.0,
            "iv_samples": sample_count,
            "iv_samples_used": sample_count,
            "iv_rank_source": "DEFAULT_NEUTRAL_TOO_FEW_SAMPLES",
            "iv_rank_confidence": "LOW"
        }
    
    # ==========================================================================
    # Calculate raw statistics (used for both bootstrap and full calculation)
    # ==========================================================================
    iv_low = min(series)
    iv_high = max(series)
    
    # Raw IV Rank (industry standard)
    if iv_high == iv_low:
        # Flat series - return neutral
        raw_iv_rank = 50.0
    else:
        raw_iv_rank = 100 * (iv_current - iv_low) / (iv_high - iv_low)
        raw_iv_rank = max(0.0, min(100.0, raw_iv_rank))
    
    # Raw IV Percentile (industry standard)
    count_below = sum(1 for iv in series if iv < iv_current)
    raw_percentile = 100 * count_below / sample_count
    raw_percentile = max(0.0, min(100.0, raw_percentile))
    
    # ==========================================================================
    # STAGE 2: Bootstrap phase (5-19 samples) - Shrinkage toward 50
    # ==========================================================================
    if sample_count < MIN_SAMPLES_BOOTSTRAP:
        # Apply shrinkage: pull extreme values toward 50
        # w = 0.25 at 5 samples, w = 0.95 at 19 samples
        w = sample_count / MIN_SAMPLES_BOOTSTRAP
        
        iv_rank = 50.0 + w * (raw_iv_rank - 50.0)
        iv_percentile = 50.0 + w * (raw_percentile - 50.0)
        
        return {
            "iv_rank": round(iv_rank, 1),
            "iv_percentile": round(iv_percentile, 1),
            "iv_low": round(iv_low, 4),
            "iv_high": round(iv_high, 4),
            "iv_samples": sample_count,
            "iv_samples_used": sample_count,
            "iv_rank_source": "OBSERVED_ATM_PROXY_BOOTSTRAP_SHRUNK",
            "iv_rank_confidence": "MEDIUM"
        }
    
    # ==========================================================================
    # STAGE 3: Full history (>= 20 samples) - True rank/percentile
    # ==========================================================================
    confidence = "HIGH" if sample_count >= MIN_SAMPLES_HIGH_CONF else "MEDIUM"
    
    return {
        "iv_rank": round(raw_iv_rank, 1),
        "iv_percentile": round(raw_percentile, 1),
        "iv_low": round(iv_low, 4),
        "iv_high": round(iv_high, 4),
        "iv_samples": sample_count,
        "iv_samples_used": sample_count,
        "iv_rank_source": "OBSERVED_ATM_PROXY",
        "iv_rank_confidence": confidence
    }


# =============================================================================
# MAIN SERVICE FUNCTION
# =============================================================================

async def get_iv_metrics_for_symbol(
    db,
    symbol: str,
    options: List[Dict],
    stock_price: float,
    store_history: bool = True
) -> IVMetrics:
    """
    Get complete IV metrics for a symbol.
    
    This is the main function to call from endpoints.
    
    CRITICAL ORDER (Part B fix - prevent self-teaching):
    1. Compute ATM proxy IV from current chain
    2. Load historical series (BEFORE storing today)
    3. Compute IV Rank and Percentile from history
    4. Store today's value in history (idempotent)
    5. Return metrics
    
    This ensures custom scans don't artificially teach history and 
    immediately consume it, which would cause rank=100 clustering.
    
    Args:
        db: MongoDB database instance
        symbol: Stock symbol
        options: Current options chain data
        stock_price: Current underlying price
        store_history: Whether to store current IV in history
    
    Returns:
        IVMetrics with all populated fields (never None)
    """
    symbol = symbol.upper()
    
    # Step 1: Compute ATM proxy from current chain
    iv_proxy, proxy_meta = compute_iv_atm_proxy(options, stock_price)
    
    # If we can't compute proxy, return defaults
    if iv_proxy is None:
        return IVMetrics(
            iv_proxy=0.0,
            iv_proxy_pct=0.0,
            iv_rank=50.0,
            iv_percentile=50.0,
            iv_low=0.0,
            iv_high=0.0,
            iv_samples=0,
            iv_rank_source="NO_ATM_PROXY_AVAILABLE",
            proxy_meta=proxy_meta,
            iv_rank_confidence="LOW",
            iv_samples_used=0
        )
    
    # Step 2: Get historical series BEFORE storing today's value
    # This prevents "self-teaching" where we store and immediately rank ourselves
    series = await get_iv_history_series(db, symbol)
    
    # Step 3: Compute IV Rank and Percentile from historical data
    metrics = compute_iv_rank_percentile(iv_proxy, series)
    
    # Step 4: Store in history if requested (AFTER computing rank)
    if store_history:
        trading_date = get_trading_date_eastern()
        await upsert_iv_history(db, symbol, trading_date, iv_proxy, proxy_meta)
    
    # Step 5: Return complete metrics
    return IVMetrics(
        iv_proxy=round(iv_proxy, 4),
        iv_proxy_pct=round(iv_proxy * 100, 1),
        iv_rank=metrics["iv_rank"],
        iv_percentile=metrics["iv_percentile"],
        iv_low=metrics["iv_low"],
        iv_high=metrics["iv_high"],
        iv_samples=metrics["iv_samples"],
        iv_rank_source=metrics["iv_rank_source"],
        proxy_meta=proxy_meta,
        iv_rank_confidence=metrics["iv_rank_confidence"],
        iv_samples_used=metrics["iv_samples_used"]
    )
        iv_percentile=metrics["iv_percentile"],
        iv_low=metrics["iv_low"],
        iv_high=metrics["iv_high"],
        iv_samples=metrics["iv_samples"],
        iv_rank_source=metrics["iv_rank_source"],
        proxy_meta=proxy_meta
    )


async def get_iv_metrics_quick(
    db,
    symbol: str
) -> Dict[str, Any]:
    """
    Get IV metrics from stored history only (no chain computation).
    
    Used when we don't have a fresh chain but need IV metrics.
    Returns neutral values if no history available.
    
    Args:
        db: MongoDB database instance
        symbol: Stock symbol
    
    Returns:
        Dict with iv_rank, iv_percentile, iv_samples, iv_rank_source
    """
    series = await get_iv_history_series(db, symbol.upper())
    
    if not series:
        return {
            "iv_proxy": 0.0,
            "iv_proxy_pct": 0.0,
            "iv_rank": 50.0,
            "iv_percentile": 50.0,
            "iv_low": 0.0,
            "iv_high": 0.0,
            "iv_samples": 0,
            "iv_rank_source": "NO_HISTORY_AVAILABLE"
        }
    
    # Use most recent as current
    iv_current = series[-1]
    metrics = compute_iv_rank_percentile(iv_current, series)
    
    return {
        "iv_proxy": round(iv_current, 4),
        "iv_proxy_pct": round(iv_current * 100, 1),
        **metrics
    }


# =============================================================================
# ADMIN / DEBUG FUNCTIONS
# =============================================================================

async def get_iv_history_debug(
    db,
    symbol: str,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Get recent IV history entries for debugging.
    
    Args:
        db: MongoDB database instance
        symbol: Stock symbol
        limit: Number of entries to return
    
    Returns:
        List of history documents (most recent first)
    """
    try:
        cursor = db[IV_HISTORY_COLLECTION].find(
            {"symbol": symbol.upper()},
            {"_id": 0}
        ).sort("trading_date", -1).limit(limit)
        
        return await cursor.to_list(limit)
        
    except Exception as e:
        logger.warning(f"Failed to get IV history debug for {symbol}: {e}")
        return []


async def get_iv_collection_stats(db) -> Dict[str, Any]:
    """
    Get statistics about the iv_history collection.
    
    Returns:
        Dict with count, unique symbols, date range, etc.
    """
    try:
        total_count = await db[IV_HISTORY_COLLECTION].count_documents({})
        
        # Get unique symbols
        unique_symbols = await db[IV_HISTORY_COLLECTION].distinct("symbol")
        
        # Get date range
        oldest = await db[IV_HISTORY_COLLECTION].find_one(
            {}, {"trading_date": 1, "_id": 0}, sort=[("trading_date", 1)]
        )
        newest = await db[IV_HISTORY_COLLECTION].find_one(
            {}, {"trading_date": 1, "_id": 0}, sort=[("trading_date", -1)]
        )
        
        return {
            "total_entries": total_count,
            "unique_symbols": len(unique_symbols),
            "symbols_sample": unique_symbols[:20] if unique_symbols else [],
            "oldest_date": oldest.get("trading_date") if oldest else None,
            "newest_date": newest.get("trading_date") if newest else None,
            "min_samples_required": MIN_SAMPLES_FOR_IV_RANK
        }
        
    except Exception as e:
        logger.warning(f"Failed to get IV collection stats: {e}")
        return {"error": str(e)}
