"""
Universe Builder - Symbol Universe Management
==============================================

Manages the scan universe with tiered symbol lists:
- Tier 1: S&P 500 constituents
- Tier 2: Nasdaq 100 (net of S&P 500 overlap)
- Tier 3: ETF whitelist (liquid options ETFs)
- Tier 4: Liquidity expansion (to reach 1500 total)

Configuration:
- TARGET_UNIVERSE_SIZE: 1500 symbols

ETF Handling:
- is_etf(symbol): Returns True if symbol is an ETF
- ETFs skip fundamental data fetch (no 404 errors)

Symbol Normalization:
- BRK-B -> BRK.B (Yahoo format)
- All symbols normalized before use
"""
import os
import logging
from typing import List, Dict, Set, Tuple

# Import from new modular structure
from services.universe_builder import (
    get_tier1_symbols,
    get_tier2_symbols,
    get_tier3_symbols,
    get_scan_universe,
    get_tier_counts,
    is_etf,
    build_universe,
    persist_universe_version,
    get_latest_universe,
    TARGET_UNIVERSE_SIZE
)
from utils.symbol_normalization import normalize_symbol, normalize_symbols
from data.etf_whitelist import ETF_WHITELIST as _ETF_LIST

logger = logging.getLogger(__name__)

# Re-export ETF_WHITELIST for backward compatibility
ETF_WHITELIST = set(normalize_symbols(_ETF_LIST))


def refresh_universe() -> Tuple[List[str], Dict[str, int]]:
    """Force rebuild of the scan universe (synchronous version)."""
    universe = get_scan_universe()
    tier_counts = get_tier_counts()
    return universe, tier_counts


def get_symbol_tier(symbol: str) -> str:
    """
    Get the tier classification for a symbol.
    
    Args:
        symbol: Stock/ETF ticker symbol
        
    Returns:
        Tier name: "sp500", "nasdaq100", "etf", or "unknown"
    """
    normalized = normalize_symbol(symbol)
    
    if normalized in ETF_WHITELIST:
        return "etf"
    
    tier1 = set(get_tier1_symbols())
    if normalized in tier1:
        return "sp500"
    
    tier2 = set(get_tier2_symbols(tier1))
    if normalized in tier2:
        return "nasdaq100"
    
    return "unknown"
