"""
Data Quality Service
====================
Validates option data quality and freshness.
Ensures expiry dates exist in actual option chains.

DATA QUALITY PRINCIPLES:
1. Option expiry dates must exist in current market data
2. Premium values must be within reasonable bounds
3. Strike prices must be valid for the underlying
4. Data staleness should be clearly indicated
"""

import logging
import yfinance as yf
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Set
from functools import lru_cache
import asyncio
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# Thread pool for yfinance calls
_executor = ThreadPoolExecutor(max_workers=5)

# Cache for available expiration dates (TTL: 1 hour)
_expiry_cache: Dict[str, Tuple[Set[str], datetime]] = {}
EXPIRY_CACHE_TTL = 3600  # 1 hour


def get_available_expiries(symbol: str) -> Set[str]:
    """
    Get available option expiration dates for a symbol from yfinance.
    Results are cached for 1 hour.
    """
    global _expiry_cache
    
    # Check cache
    if symbol in _expiry_cache:
        expiries, cached_at = _expiry_cache[symbol]
        if (datetime.now() - cached_at).total_seconds() < EXPIRY_CACHE_TTL:
            return expiries
    
    try:
        ticker = yf.Ticker(symbol)
        available = set(ticker.options) if ticker.options else set()
        _expiry_cache[symbol] = (available, datetime.now())
        return available
    except Exception as e:
        logger.warning(f"Failed to get expiries for {symbol}: {e}")
        return set()


def validate_expiry_date(symbol: str, expiry_date: str) -> Tuple[bool, Optional[str]]:
    """
    Validate if an expiry date exists in the current option chain.
    
    Returns:
        (is_valid, closest_valid_expiry)
        - is_valid: True if the expiry exists
        - closest_valid_expiry: If invalid, suggests the closest valid date
    """
    available = get_available_expiries(symbol)
    
    if not available:
        return False, None
    
    # Normalize expiry format
    try:
        exp_dt = datetime.strptime(expiry_date[:10], "%Y-%m-%d")
        expiry_str = exp_dt.strftime("%Y-%m-%d")
    except:
        return False, None
    
    if expiry_str in available:
        return True, expiry_str
    
    # Find closest valid expiry
    today = datetime.now()
    closest = None
    min_diff = float('inf')
    
    for avail_exp in available:
        try:
            avail_dt = datetime.strptime(avail_exp, "%Y-%m-%d")
            diff = abs((avail_dt - exp_dt).days)
            if diff < min_diff:
                min_diff = diff
                closest = avail_exp
        except:
            continue
    
    return False, closest


def validate_premium(symbol: str, strike: float, expiry: str, 
                    premium: float, stock_price: float, 
                    option_type: str = "call") -> Tuple[bool, str]:
    """
    Validate if a premium value is reasonable.
    
    Returns:
        (is_valid, reason)
    """
    if premium <= 0:
        return False, "Premium must be positive"
    
    # For calls: premium shouldn't exceed stock price
    if option_type == "call" and premium > stock_price:
        return False, f"Call premium ${premium:.2f} exceeds stock price ${stock_price:.2f}"
    
    # For deep ITM calls, premium should be at least intrinsic value
    if option_type == "call" and strike < stock_price:
        intrinsic = stock_price - strike
        if premium < intrinsic * 0.8:  # Allow 20% margin for stale data
            return False, f"Premium ${premium:.2f} below intrinsic value ${intrinsic:.2f}"
    
    # For OTM calls, premium should be less than 50% of stock price
    if option_type == "call" and strike > stock_price:
        if premium > stock_price * 0.5:
            return False, f"OTM call premium ${premium:.2f} seems too high"
    
    return True, "Valid"


async def validate_opportunity(opp: Dict, strategy: str = "covered_call") -> Dict:
    """
    Validate a single opportunity and add quality indicators.
    
    Returns the opportunity with added fields:
        - data_quality: "fresh" | "stale" | "invalid"
        - quality_issues: List of issues found
        - validated_at: Timestamp
    """
    issues = []
    quality = "fresh"
    
    symbol = opp.get("symbol", "")
    stock_price = opp.get("stock_price", 0)
    
    if strategy == "covered_call":
        expiry = opp.get("expiry", "")
        strike = opp.get("strike", 0)
        premium = opp.get("premium", 0)
        
        # Validate expiry
        is_valid, closest = validate_expiry_date(symbol, expiry)
        if not is_valid:
            quality = "stale"
            if closest:
                issues.append(f"Expiry {expiry} not available, closest: {closest}")
            else:
                issues.append(f"Expiry {expiry} not available")
        
        # Validate premium (per-share)
        prem_valid, prem_reason = validate_premium(
            symbol, strike, expiry, premium, stock_price, "call"
        )
        if not prem_valid:
            quality = "stale" if quality == "fresh" else quality
            issues.append(prem_reason)
            
    elif strategy == "pmcc":
        # PMCC has two legs
        long_expiry = opp.get("leaps_expiry") or opp.get("long_expiry", "")
        short_expiry = opp.get("short_expiry", "")
        long_strike = opp.get("leaps_strike") or opp.get("long_strike", 0)
        short_strike = opp.get("short_strike", 0)
        long_premium = opp.get("leaps_premium") or opp.get("long_premium", 0)
        short_premium = opp.get("short_premium", 0)
        
        # Validate LEAPS expiry
        is_valid, closest = validate_expiry_date(symbol, long_expiry)
        if not is_valid:
            quality = "stale"
            if closest:
                issues.append(f"LEAPS expiry {long_expiry} not available, closest: {closest}")
            else:
                issues.append(f"LEAPS expiry {long_expiry} not available")
        
        # Validate short expiry
        is_valid, closest = validate_expiry_date(symbol, short_expiry)
        if not is_valid:
            quality = "stale"
            if closest:
                issues.append(f"Short expiry {short_expiry} not available, closest: {closest}")
            else:
                issues.append(f"Short expiry {short_expiry} not available")
        
        # Validate LEAPS premium (deep ITM)
        if long_premium > 0:
            prem_valid, prem_reason = validate_premium(
                symbol, long_strike, long_expiry, long_premium, stock_price, "call"
            )
            if not prem_valid:
                quality = "stale" if quality == "fresh" else quality
                issues.append(f"LEAPS: {prem_reason}")
    
    # Add quality metadata
    opp["data_quality"] = quality
    opp["quality_issues"] = issues
    opp["validated_at"] = datetime.now().isoformat()
    
    return opp


async def validate_opportunities_batch(
    opportunities: List[Dict], 
    strategy: str = "covered_call",
    max_concurrent: int = 10
) -> Tuple[List[Dict], Dict]:
    """
    Validate a batch of opportunities and return quality statistics.
    
    Returns:
        (validated_opportunities, stats)
        - stats includes: total, fresh, stale, invalid counts
    """
    if not opportunities:
        return [], {"total": 0, "fresh": 0, "stale": 0, "invalid": 0}
    
    # Get unique symbols first to batch expiry lookups
    symbols = set(opp.get("symbol", "") for opp in opportunities)
    
    # Pre-fetch all expiries in parallel
    loop = asyncio.get_event_loop()
    for symbol in symbols:
        await loop.run_in_executor(_executor, get_available_expiries, symbol)
    
    # Validate all opportunities
    validated = []
    for opp in opportunities:
        validated_opp = await validate_opportunity(opp, strategy)
        validated.append(validated_opp)
    
    # Calculate stats
    stats = {
        "total": len(validated),
        "fresh": sum(1 for o in validated if o.get("data_quality") == "fresh"),
        "stale": sum(1 for o in validated if o.get("data_quality") == "stale"),
        "invalid": sum(1 for o in validated if o.get("data_quality") == "invalid"),
    }
    
    return validated, stats


def calculate_data_freshness_score(opportunities: List[Dict]) -> float:
    """
    Calculate an overall data freshness score (0-100).
    """
    if not opportunities:
        return 0
    
    fresh_count = sum(1 for o in opportunities if o.get("data_quality") == "fresh")
    return round((fresh_count / len(opportunities)) * 100, 1)


async def get_live_option_price(
    symbol: str, 
    strike: float, 
    expiry: str, 
    option_type: str = "call"
) -> Optional[Dict]:
    """
    Fetch live option price from yfinance.
    
    Returns:
        Dict with keys: last_price, bid, ask, volume, open_interest, iv
        or None if not found
    """
    def _fetch_sync():
        try:
            ticker = yf.Ticker(symbol)
            
            # Check if expiry is available
            if expiry not in ticker.options:
                return None
            
            chain = ticker.option_chain(expiry)
            options = chain.calls if option_type == "call" else chain.puts
            
            # Find the specific strike
            match = options[options['strike'] == strike]
            if match.empty:
                # Try closest strike
                closest_idx = (options['strike'] - strike).abs().idxmin()
                match = options.loc[[closest_idx]]
            
            if not match.empty:
                row = match.iloc[0]
                return {
                    "strike": float(row['strike']),
                    "expiry": expiry,
                    "last_price": float(row['lastPrice']),
                    "bid": float(row['bid']),
                    "ask": float(row['ask']),
                    "volume": int(row['volume']) if pd.notna(row['volume']) else 0,
                    "open_interest": int(row['openInterest']) if pd.notna(row['openInterest']) else 0,
                    "implied_volatility": float(row['impliedVolatility']) if pd.notna(row['impliedVolatility']) else 0,
                }
            return None
        except Exception as e:
            logger.warning(f"Failed to get live price for {symbol} {strike} {expiry}: {e}")
            return None
    
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _fetch_sync)


# Import pandas for the live option price function
import pandas as pd
