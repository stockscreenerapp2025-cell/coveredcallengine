"""
Deterministic Universe Builder
==============================
Builds an exact 1500-symbol universe using tiered approach:

Tier 1: S&P 500 (curated static list)
Tier 2: Nasdaq 100 (net additions)
Tier 3: ETF Whitelist
Tier 4: Liquidity Expansion (from us_symbol_master)

The universe is deterministic and versioned.
"""
import os
import logging
from datetime import datetime, timezone
from typing import List, Dict, Tuple, Optional, Set

from data.sp500_symbols import SP500_SYMBOLS
from data.nasdaq100_symbols import NASDAQ100_SYMBOLS
from data.etf_whitelist import ETF_WHITELIST
from utils.symbol_normalization import normalize_symbol, normalize_symbols

logger = logging.getLogger(__name__)

# Target universe size
TARGET_UNIVERSE_SIZE = 1500

# Liquidity expansion filters
LIQUIDITY_MIN_AVG_VOLUME = 750_000
LIQUIDITY_MIN_MARKET_CAP = 2_000_000_000
LIQUIDITY_MIN_PRICE = 20.0
LIQUIDITY_MAX_PRICE = 500.0


def get_tier1_symbols() -> List[str]:
    """Get Tier 1: S&P 500 symbols (normalized)."""
    return normalize_symbols(SP500_SYMBOLS)


def get_tier2_symbols(exclude: Set[str]) -> List[str]:
    """Get Tier 2: Nasdaq 100 net additions (not in Tier 1)."""
    nasdaq = normalize_symbols(NASDAQ100_SYMBOLS)
    return [s for s in nasdaq if s not in exclude]


def get_tier3_symbols(exclude: Set[str]) -> List[str]:
    """Get Tier 3: ETF Whitelist (not already included)."""
    etfs = normalize_symbols(ETF_WHITELIST)
    return [s for s in etfs if s not in exclude]


async def get_tier4_symbols(
    db,
    exclude: Set[str],
    target_count: int
) -> Tuple[List[str], int]:
    """
    Get Tier 4: Liquidity expansion from us_symbol_master.
    
    Args:
        db: MongoDB database instance
        exclude: Set of symbols already included
        target_count: Number of symbols needed to reach 1500
        
    Returns:
        Tuple of (symbols list, actual count found)
    """
    if target_count <= 0:
        return [], 0
    
    # Query us_symbol_master for liquid symbols
    pipeline = [
        {
            "$match": {
                "symbol": {"$nin": list(exclude)},
                "avg_volume_20d": {"$gte": LIQUIDITY_MIN_AVG_VOLUME},
                "market_cap": {"$gte": LIQUIDITY_MIN_MARKET_CAP},
                "last_close": {
                    "$gte": LIQUIDITY_MIN_PRICE,
                    "$lte": LIQUIDITY_MAX_PRICE
                },
                "is_etf": {"$ne": True}  # Exclude ETFs (already in Tier 3)
            }
        },
        {
            "$addFields": {
                "dollar_volume_20d": {
                    "$multiply": ["$last_close", "$avg_volume_20d"]
                }
            }
        },
        {
            "$sort": {"dollar_volume_20d": -1}
        },
        {
            "$limit": target_count
        },
        {
            "$project": {"symbol": 1, "_id": 0}
        }
    ]
    
    try:
        cursor = db.us_symbol_master.aggregate(pipeline)
        results = await cursor.to_list(length=target_count)
        symbols = [normalize_symbol(r["symbol"]) for r in results]
        return symbols, len(symbols)
    except Exception as e:
        logger.error(f"Tier 4 expansion query failed: {e}")
        return [], 0


async def build_universe(db) -> Tuple[List[str], Dict[str, int], str]:
    """
    Build the deterministic 1500-symbol universe.
    
    Args:
        db: MongoDB database instance
        
    Returns:
        Tuple of (symbols, tier_counts, universe_version)
    """
    # Tier 1: S&P 500
    tier1 = get_tier1_symbols()
    included = set(tier1)
    tier1_count = len(tier1)
    
    # Tier 2: Nasdaq 100 (net)
    tier2 = get_tier2_symbols(included)
    included.update(tier2)
    tier2_count = len(tier2)
    
    # Tier 3: ETF Whitelist
    tier3 = get_tier3_symbols(included)
    included.update(tier3)
    tier3_count = len(tier3)
    
    # Current total
    current_total = len(included)
    needed_for_expansion = TARGET_UNIVERSE_SIZE - current_total
    
    # Tier 4: Liquidity expansion
    tier4, tier4_count = await get_tier4_symbols(db, included, needed_for_expansion)
    included.update(tier4)
    
    # Final universe (preserve tier order)
    universe = tier1 + tier2 + tier3 + tier4
    final_count = len(universe)
    
    # Log results
    tier_counts = {
        "sp500": tier1_count,
        "nasdaq100_net": tier2_count,
        "etf_whitelist": tier3_count,
        "liquidity_expansion": tier4_count,
        "total": final_count,
        "target": TARGET_UNIVERSE_SIZE,
        "shortfall": max(0, TARGET_UNIVERSE_SIZE - final_count)
    }
    
    logger.info(
        f"Universe built: {final_count}/{TARGET_UNIVERSE_SIZE} "
        f"(T1:{tier1_count} T2:{tier2_count} T3:{tier3_count} T4:{tier4_count})"
    )
    
    if final_count < TARGET_UNIVERSE_SIZE:
        logger.warning(
            f"Universe shortfall: {TARGET_UNIVERSE_SIZE - final_count} symbols. "
            f"Consider adding more symbols to us_symbol_master."
        )
    
    # Generate version string
    now = datetime.now(timezone.utc)
    universe_version = f"U{now.strftime('%Y-%m-%d')}_{final_count}"
    
    return universe, tier_counts, universe_version


async def persist_universe_version(
    db,
    universe: List[str],
    tier_counts: Dict[str, int],
    universe_version: str
) -> bool:
    """
    Persist universe version to scan_universe_versions collection.
    
    Args:
        db: MongoDB database instance
        universe: List of symbols
        tier_counts: Tier breakdown
        universe_version: Version string (e.g., U2026-02-16_1500)
        
    Returns:
        True if persisted successfully
    """
    try:
        doc = {
            "universe_version": universe_version,
            "universe_symbols": universe,
            "tier_counts": tier_counts,
            "symbol_count": len(universe),
            "created_at": datetime.now(timezone.utc),
            "is_production": os.environ.get("ENVIRONMENT") == "production"
        }
        
        await db.scan_universe_versions.replace_one(
            {"universe_version": universe_version},
            doc,
            upsert=True
        )
        
        logger.info(f"Persisted universe version: {universe_version}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to persist universe version: {e}")
        return False


async def get_latest_universe(db) -> Optional[Dict]:
    """
    Get the latest persisted universe version.
    
    Args:
        db: MongoDB database instance
        
    Returns:
        Universe document or None
    """
    try:
        return await db.scan_universe_versions.find_one(
            {},
            sort=[("created_at", -1)]
        )
    except Exception as e:
        logger.error(f"Failed to get latest universe: {e}")
        return None


# Legacy compatibility: expose for existing code
def is_etf(symbol: str) -> bool:
    """Check if symbol is in ETF whitelist."""
    normalized = normalize_symbol(symbol)
    return normalized in normalize_symbols(ETF_WHITELIST)


def get_scan_universe() -> List[str]:
    """
    Get scan universe (synchronous, for backward compatibility).
    Returns Tier 1-3 only (no async DB access).
    """
    tier1 = get_tier1_symbols()
    included = set(tier1)
    
    tier2 = get_tier2_symbols(included)
    included.update(tier2)
    
    tier3 = get_tier3_symbols(included)
    
    return tier1 + tier2 + tier3


def get_tier_counts() -> Dict[str, int]:
    """
    Get tier counts (synchronous, for backward compatibility).
    Returns Tier 1-3 counts only.
    """
    tier1 = get_tier1_symbols()
    included = set(tier1)
    
    tier2 = get_tier2_symbols(included)
    included.update(tier2)
    
    tier3 = get_tier3_symbols(included)
    
    return {
        "sp500": len(tier1),
        "nasdaq100_net": len(tier2),
        "etf_whitelist": len(tier3),
        "liquidity_expansion": 0,
        "total": len(tier1) + len(tier2) + len(tier3)
    }
