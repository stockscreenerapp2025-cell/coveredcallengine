"""
Screener Routes - Covered Call and PMCC screening endpoints
Designed for scalability with proper caching, async patterns, and efficient data processing

TWO-SOURCE DATA MODEL (AUTHORITATIVE SPEC):
1. EQUITY PRICE (Hard Rule):
   - Always use T-1 market close
   - Non-negotiable

2. OPTIONS CHAIN DATA (Flexible but Controlled):
   - Use latest fully available option chain snapshot
   - Only use expirations that ACTUALLY exist in Yahoo Finance
   - Reject chains with missing IV or OI
   - Only include Friday expirations (standard weeklies)

3. WEEKLY/MONTHLY MIX:
   - Show 50/50 mix of best weekly and monthly options
   - Fallback: whatever is available

4. MANDATORY METADATA:
   - Equity Price Date: e.g., "Jan 15, 2026 (T-1 close)"
   - Options Chain Snapshot: e.g., "As of: Jan 14, 2026 22:10 ET"

5. STALENESS RULES:
   - 🟢 Fresh: snapshot ≤ 24h old
   - 🟠 Stale: 24-48h old
   - 🔴 Invalid: >48h old → exclude from scans
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
import logging
import httpx
import asyncio

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import db
from utils.auth import get_current_user
# Import centralized data provider (Two-Source Model)
from services.data_provider import (
    fetch_options_chain,
    fetch_stock_quote,
    get_data_date,
    get_data_source_status,
    calculate_dte,
    get_available_expirations
)
# Import trading calendar for T-1 dates
from services.trading_calendar import (
    get_t_minus_1,
    get_market_data_status,
    get_data_freshness_status,
    is_valid_expiration_date,
    is_friday_expiration,
    is_monthly_expiration,
    categorize_expirations,
    get_option_chain_staleness,
    validate_option_chain_data,
    get_data_metadata
)
# Import data quality validation
from services.data_quality import (
    validate_opportunities_batch,
    calculate_data_freshness_score,
    validate_expiry_date
)

screener_router = APIRouter(tags=["Screener"])

# HTTP client settings
HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# Thread pool for blocking yfinance calls
_analyst_executor = ThreadPoolExecutor(max_workers=10)

# ETF symbols for special handling
ETF_SYMBOLS = {"SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK", "XLV", "XLI", "XLB", "XLU", "XLP", "XLY"}


def _fetch_analyst_rating_sync(symbol: str) -> dict:
    """Fetch analyst rating for a single symbol (blocking call)"""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        info = ticker.info
        
        recommendation = info.get("recommendationKey", "")
        rating_map = {
            "strong_buy": "Strong Buy",
            "buy": "Buy",
            "hold": "Hold",
            "underperform": "Sell",
            "sell": "Sell"
        }
        rating = rating_map.get(recommendation, recommendation.replace("_", " ").title() if recommendation else None)
        
        return {
            "symbol": symbol,
            "analyst_rating": rating,
            "num_analysts": info.get("numberOfAnalystOpinions", 0)
        }
    except Exception as e:
        logging.warning(f"Failed to fetch analyst rating for {symbol}: {e}")
        return {"symbol": symbol, "analyst_rating": None, "num_analysts": 0}


async def fetch_analyst_ratings_batch(symbols: List[str]) -> Dict[str, str]:
    """Fetch analyst ratings for multiple symbols in parallel"""
    if not symbols:
        return {}
    
    loop = asyncio.get_event_loop()
    
    # Run all fetches in parallel using thread pool
    tasks = [
        loop.run_in_executor(_analyst_executor, _fetch_analyst_rating_sync, symbol)
        for symbol in set(symbols)  # Dedupe symbols
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Build symbol -> rating map
    ratings = {}
    for result in results:
        if isinstance(result, dict):
            ratings[result["symbol"]] = result.get("analyst_rating")
    
    return ratings


class ScreenerFilterCreate(BaseModel):
    name: str
    filters: Dict[str, Any]


def _get_server_functions():
    """Lazy import for cache and utility functions from server.py"""
    from server import (
        get_massive_api_key, generate_cache_key, get_cached_data, 
        set_cached_data, get_last_trading_day_data, is_market_closed,
        generate_mock_covered_call_opportunities, clear_cache
    )
    return {
        'get_massive_api_key': get_massive_api_key,
        'generate_cache_key': generate_cache_key,
        'get_cached_data': get_cached_data,
        'set_cached_data': set_cached_data,
        'get_last_trading_day_data': get_last_trading_day_data,
        'is_market_closed': is_market_closed,
        'generate_mock_covered_call_opportunities': generate_mock_covered_call_opportunities,
        'clear_cache': clear_cache
    }


def _get_t1_data_info() -> Dict[str, Any]:
    """
    Get comprehensive data metadata for response.
    
    Returns:
        Dict with equity price date, options snapshot info, staleness thresholds
    """
    metadata = get_data_metadata()
    t1_date, t1_datetime = get_t_minus_1()
    market_status = get_market_data_status()
    
    return {
        # Equity price info (T-1 close - hard rule)
        "equity_price_date": t1_date,
        "equity_price_source": "T-1 Market Close",
        # Options snapshot info (may differ from equity date)
        "options_snapshot_time": None,  # Will be populated per-request
        # General info
        "data_age_hours": market_status["data_age_hours"],
        "next_refresh": market_status["next_data_refresh"],
        "current_time_et": market_status["current_time_et"],
        # Staleness thresholds
        "staleness_thresholds": metadata["staleness_thresholds"]
    }


def _mix_weekly_monthly_opportunities(opportunities: List[Dict], target_count: int = 20) -> List[Dict]:
    """
    Mix weekly and monthly opportunities in 50/50 ratio.
    
    Args:
        opportunities: List of opportunity dicts with 'expiry_type' field
        target_count: Target number of opportunities
        
    Returns:
        Mixed list with roughly 50% weekly, 50% monthly
    """
    weekly = [o for o in opportunities if o.get("expiry_type") == "weekly"]
    monthly = [o for o in opportunities if o.get("expiry_type") == "monthly"]
    
    # Sort each by score
    weekly.sort(key=lambda x: x.get("score", 0), reverse=True)
    monthly.sort(key=lambda x: x.get("score", 0), reverse=True)
    
    # Target 50/50 mix
    half = target_count // 2
    
    # Get best from each category
    best_weekly = weekly[:half]
    best_monthly = monthly[:half]
    
    # If one category is short, take more from the other
    remaining_slots = target_count - len(best_weekly) - len(best_monthly)
    
    if len(best_weekly) < half and len(monthly) > half:
        # Need more monthly
        extra_monthly = monthly[half:half + remaining_slots]
        best_monthly.extend(extra_monthly)
    elif len(best_monthly) < half and len(weekly) > half:
        # Need more weekly
        extra_weekly = weekly[half:half + remaining_slots]
        best_weekly.extend(extra_weekly)
    
    # Combine and sort by score
    mixed = best_weekly + best_monthly
    mixed.sort(key=lambda x: x.get("score", 0), reverse=True)
    
    return mixed[:target_count]



@screener_router.get("/covered-calls")
async def screen_covered_calls(
    min_roi: float = Query(0.5, ge=0),
    max_dte: int = Query(45, ge=1),
    min_delta: float = Query(0.15, ge=0, le=1),
    max_delta: float = Query(0.45, ge=0, le=1),
    min_iv_rank: float = Query(0, ge=0, le=100),
    min_price: float = Query(10, ge=0),
    max_price: float = Query(500, ge=0),
    min_volume: int = Query(0, ge=0),
    min_open_interest: int = Query(0, ge=0),
    weekly_only: bool = Query(False),
    monthly_only: bool = Query(False),
    include_stocks: bool = Query(True),
    include_etfs: bool = Query(True),
    include_index: bool = Query(False),
    bypass_cache: bool = Query(False),
    user: dict = Depends(get_current_user)
):
    """
    Screen for covered call opportunities with advanced filters.
    
    TWO-SOURCE DATA MODEL:
    - Equity Price: T-1 market close (hard rule)
    - Options Chain: Latest fully available snapshot from Yahoo Finance
    
    WEEKLY/MONTHLY MIX:
    - Returns 50/50 mix of best weekly and monthly options by default
    - Use weekly_only=True or monthly_only=True to filter
    
    VALIDATION:
    - Only uses expirations that ACTUALLY exist in Yahoo Finance
    - Only Friday expirations (standard weeklies)
    - Rejects options with missing IV or OI
    """
    funcs = _get_server_functions()
    
    # Get T-1 data info for response
    t1_info = _get_t1_data_info()
    equity_date = t1_info["equity_price_date"]
    
    # Generate cache key
    cache_params = {
        "equity_date": equity_date,
        "min_roi": min_roi, "max_dte": max_dte, "min_delta": min_delta, "max_delta": max_delta,
        "min_iv_rank": min_iv_rank, "min_price": min_price, "max_price": max_price,
        "include_stocks": include_stocks, "include_etfs": include_etfs, "include_index": include_index,
        "min_volume": min_volume, "min_open_interest": min_open_interest,
        "weekly_only": weekly_only, "monthly_only": monthly_only
    }
    cache_key = funcs['generate_cache_key']("screener_cc_v2", cache_params)
    
    # Check cache first
    if not bypass_cache:
        cached_data = await funcs['get_cached_data'](cache_key, max_age_seconds=86400)
        if cached_data and cached_data.get("opportunities"):
            cached_data["from_cache"] = True
            cached_data["metadata"] = t1_info
            return cached_data
        
        # Check precomputed scans
        precomputed = await db.precomputed_scans.find_one(
            {"strategy": "covered_call", "risk_profile": "balanced"},
            {"_id": 0}
        )
        if precomputed and precomputed.get("opportunities"):
            computed_date = precomputed.get("computed_date", "unknown")
            freshness = get_data_freshness_status(computed_date) if computed_date != "unknown" else {"status": "amber"}
            
            # Calculate weekly/monthly counts from precomputed data
            opps = precomputed["opportunities"]
            weekly_count = sum(1 for o in opps if o.get("expiry_type") == "weekly" or o.get("timeframe") == "weekly")
            monthly_count = sum(1 for o in opps if o.get("expiry_type") == "monthly" or o.get("timeframe") == "monthly")
            
            return {
                "opportunities": opps,
                "total": len(opps),
                "weekly_count": weekly_count,
                "monthly_count": monthly_count,
                "from_cache": True,
                "is_precomputed": True,
                "precomputed_profile": "balanced",
                "computed_at": precomputed.get("computed_at"),
                "metadata": {
                    **t1_info,
                    "options_snapshot_time": precomputed.get("computed_at", "Pre-computed scan")
                },
                "data_freshness": freshness
            }
    
    # Get API key for backup data source
    api_key = await funcs['get_massive_api_key']()
    
    logging.info(f"CC Screener (Equity: {equity_date}): api_key={'present' if api_key else 'missing'}, min_roi={min_roi}, max_dte={max_dte}")
    
    if not api_key:
        opportunities = funcs['generate_mock_covered_call_opportunities']()
        filtered = [o for o in opportunities if o["roi_pct"] >= min_roi and o["dte"] <= max_dte]
        return {"opportunities": filtered[:20], "total": len(filtered), "is_mock": True, "message": "API key required for live data"}
    
    try:
        opportunities = []
        options_snapshot_time = None
        
        # Symbol lists for scanning
        tier1_symbols = [
            "INTC", "AMD", "BAC", "WFC", "C", "F", "GM", "T", "VZ",
            "PFE", "MRK", "KO", "PEP", "NKE", "DIS",
            "PYPL", "UBER", "SNAP", "PLTR", "SOFI",
            "AAL", "DAL", "CCL",
            "USB", "PNC", "CFG",
            "DVN", "APA", "HAL", "OXY"
        ]
        
        tier2_symbols = [
            "AAPL", "MSFT", "META",
            "JPM", "GS", "V", "MA",
            "HD", "COST",
            "XOM", "CVX"
        ]
        
        etf_symbols = ["SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK"]
        
        # Build symbols list based on filters
        symbols_to_scan = []
        
        if include_stocks:
            if max_price <= 100:
                symbols_to_scan.extend(tier1_symbols)
            elif min_price >= 100:
                symbols_to_scan.extend(tier2_symbols)
            else:
                symbols_to_scan.extend(tier1_symbols + tier2_symbols)
        
        if include_etfs:
            symbols_to_scan.extend(etf_symbols)
        
        logging.info(f"Scanning {len(symbols_to_scan)} symbols for covered calls")
        
        for symbol in symbols_to_scan:
            try:
                # Get stock price using centralized data provider (T-1 close)
                stock_data = await fetch_stock_quote(symbol, api_key)
                
                if not stock_data or stock_data.get("price", 0) == 0:
                    continue
                
                underlying_price = stock_data["price"]
                analyst_rating = stock_data.get("analyst_rating")
                
                is_etf = symbol.upper() in ETF_SYMBOLS
                if not is_etf and (underlying_price < min_price or underlying_price > max_price):
                    continue
                
                # Get options chain with STRICT validation
                # - Only Friday expirations
                # - Requires complete data (IV, OI)
                options_results, opt_metadata = await fetch_options_chain(
                    symbol=symbol,
                    api_key=api_key,
                    option_type="call",
                    max_dte=max_dte,
                    min_dte=1,
                    current_price=underlying_price,
                    friday_only=True,
                    require_complete_data=True
                )
                
                # Track options snapshot time
                if opt_metadata.get("snapshot_time") and not options_snapshot_time:
                    options_snapshot_time = opt_metadata["snapshot_time"]
                
                if not options_results:
                    logging.debug(f"No valid options for {symbol}: {opt_metadata.get('error', 'unknown')}")
                    continue
                
                for opt in options_results:
                    strike = opt.get("strike", 0)
                    expiry = opt.get("expiry", "")
                    dte = opt.get("dte", 0)
                    expiry_type = opt.get("expiry_type", "weekly")
                    
                    # Strike range filter
                    strike_pct = (strike / underlying_price) * 100 if underlying_price > 0 else 0
                    if is_etf:
                        if strike_pct < 95 or strike_pct > 108:
                            continue
                    else:
                        if strike_pct < 97 or strike_pct > 115:
                            continue
                    
                    if dte > max_dte or dte < 1:
                        continue
                    if weekly_only and expiry_type != "weekly":
                        continue
                    if monthly_only and expiry_type != "monthly":
                        continue
                    
                    # Estimate delta based on moneyness
                    strike_pct_diff = ((strike - underlying_price) / underlying_price) * 100
                    if strike_pct_diff <= 0:
                        estimated_delta = 0.55 - (abs(strike_pct_diff) * 0.02)
                    else:
                        estimated_delta = 0.50 - (strike_pct_diff * 0.03)
                    estimated_delta = max(0.15, min(0.60, estimated_delta))
                    
                    if not is_etf and (estimated_delta < min_delta or estimated_delta > max_delta):
                        continue
                    
                    premium = opt.get("close", 0)
                    
                    if premium <= 0:
                        continue
                    
                    # Get IV and OI from validated option data
                    iv = opt.get("implied_volatility", 0)
                    open_interest = opt.get("open_interest", 0)
                    volume = opt.get("volume", 0)
                    
                    # Skip if IV is missing (already filtered by data_provider but double-check)
                    if iv <= 0:
                        continue
                    
                    # Skip if OI is too low
                    if open_interest < min_open_interest:
                        continue
                    
                    roi_pct = (premium / underlying_price) * 100
                    
                    if roi_pct < min_roi:
                        continue
                    
                    if volume < min_volume:
                        continue
                    
                    iv_rank = min(100, iv * 100)
                    
                    if iv_rank < min_iv_rank:
                        continue
                    
                    # Calculate downside protection
                    if strike > underlying_price:
                        protection = (premium / underlying_price) * 100
                    else:
                        protection = ((strike - underlying_price + premium) / underlying_price * 100)
                    
                    # Calculate score with liquidity bonus
                    roi_score = min(roi_pct * 15, 40)
                    iv_score = min(iv_rank / 100 * 20, 20)
                    delta_score = max(0, 20 - abs(estimated_delta - 0.3) * 50)
                    protection_score = min(abs(protection), 10) * 2
                    
                    # Liquidity bonus
                    liquidity_score = 0
                    if open_interest >= 1000:
                        liquidity_score = 10
                    elif open_interest >= 500:
                        liquidity_score = 7
                    elif open_interest >= 100:
                        liquidity_score = 5
                    elif open_interest >= 50:
                        liquidity_score = 2
                    
                    score = round(roi_score + iv_score + delta_score + protection_score + liquidity_score, 1)
                    
                    opportunities.append({
                        "symbol": symbol,
                        "stock_price": round(underlying_price, 2),
                        "strike": strike,
                        "expiry": expiry,
                        "expiry_type": expiry_type,  # "weekly" or "monthly"
                        "dte": dte,
                        "premium": round(premium, 2),
                        "roi_pct": round(roi_pct, 2),
                        "delta": round(estimated_delta, 3),
                        "theta": 0,
                        "iv": round(iv, 4),
                        "iv_rank": round(iv_rank, 1),
                        "downside_protection": round(protection, 2),
                        "volume": volume,
                        "open_interest": open_interest,
                        "score": score,
                        "analyst_rating": analyst_rating,
                        "days_to_earnings": stock_data.get("days_to_earnings"),
                        "earnings_date": stock_data.get("earnings_date"),
                        # Metadata
                        "equity_price_date": equity_date,
                        "options_snapshot_time": opt.get("options_snapshot_time"),
                        "data_source": opt.get("source", "yahoo")
                    })
            except Exception as e:
                logging.error(f"Error scanning {symbol}: {e}")
                continue
        
        # Sort all by score
        opportunities.sort(key=lambda x: x["score"], reverse=True)
        
        # Apply weekly/monthly mix if not filtering specifically
        if not weekly_only and not monthly_only:
            opportunities = _mix_weekly_monthly_opportunities(opportunities, target_count=40)
        else:
            # Just take top 20 if filtering
            best_by_symbol = {}
            for opp in opportunities:
                sym = opp["symbol"]
                if sym not in best_by_symbol or opp["score"] > best_by_symbol[sym]["score"]:
                    best_by_symbol[sym] = opp
            opportunities = sorted(best_by_symbol.values(), key=lambda x: x["score"], reverse=True)[:20]
        # Update metadata with options snapshot time
        t1_info["options_snapshot_time"] = options_snapshot_time
        
        # Count weekly vs monthly in results
        weekly_count = sum(1 for o in opportunities if o.get("expiry_type") == "weekly")
        monthly_count = sum(1 for o in opportunities if o.get("expiry_type") == "monthly")
        
        result = {
            "opportunities": opportunities, 
            "total": len(opportunities),
            "weekly_count": weekly_count,
            "monthly_count": monthly_count,
            "from_cache": False,
            "metadata": {
                "equity_price_date": equity_date,
                "equity_price_source": "T-1 Market Close",
                "options_snapshot_time": options_snapshot_time,
                "data_source": "yahoo",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "staleness_thresholds": t1_info.get("staleness_thresholds", {})
            }
        }
        await funcs['set_cached_data'](cache_key, result)
        return result
        
    except Exception as e:
        logging.error(f"Screener error: {e}")
        return {"opportunities": [], "total": 0, "error": str(e), "metadata": t1_info}



@screener_router.get("/dashboard-opportunities")
async def get_dashboard_opportunities(user: dict = Depends(get_current_user)):
    """
    Get top 10 covered call opportunities for dashboard - 5 Weekly + 5 Monthly.
    
    TWO-SOURCE DATA MODEL:
    - Equity: T-1 market close
    - Options: Latest available snapshot
    - Weekly options FIRST, then Monthly to fill remaining slots
    """
    funcs = _get_server_functions()
    t1_info = _get_t1_data_info()
    equity_date = t1_info["equity_price_date"]
    
    cache_key = f"dashboard_opportunities_v3_{equity_date}"
    
    # Check cache (valid for entire day)
    cached_data = await funcs['get_cached_data'](cache_key, max_age_seconds=86400)
    if cached_data:
        cached_data["from_cache"] = True
        cached_data["metadata"] = t1_info
        return cached_data
    
    api_key = await funcs['get_massive_api_key']()
    
    if not api_key:
        return {"opportunities": [], "total": 0, "message": "API key not configured", "is_mock": True, "metadata": t1_info}
    
    try:
        symbols_to_scan = [
            "INTC", "CSCO", "MU", "QCOM", "TXN", "ADI", "MCHP", "ON", "HPQ",
            "BAC", "WFC", "C", "USB", "PNC", "TFC", "KEY", "RF", "CFG", "FITB",
            "KO", "PEP", "NKE", "SBUX", "DIS", "GM", "F",
            "VZ", "T", "TMUS",
            "PFE", "MRK", "ABBV", "BMY", "GILD",
            "OXY", "DVN", "APA", "HAL", "SLB", "MRO",
            "CAT", "DE", "GE", "HON",
            "PYPL", "SQ", "ROKU", "SNAP", "UBER", "LYFT",
            "AAL", "DAL", "UAL", "CCL", "NCLH",
            "PLTR", "SOFI", "HOOD",
            "AMD", "DELL", "IBM", "ORCL"
        ]
        
        weekly_opportunities = []
        monthly_opportunities = []
        options_snapshot_time = None
        
        for symbol in symbols_to_scan[:35]:
            try:
                # Get stock price (T-1 close)
                stock_data = await fetch_stock_quote(symbol, api_key)
                
                if not stock_data or stock_data.get("price", 0) == 0:
                    continue
                
                current_price = stock_data["price"]
                analyst_rating = stock_data.get("analyst_rating")
                
                if current_price < 25 or current_price > 100:
                    continue
                
                # Get options with proper tuple unpacking
                # Weekly: DTE 1-7
                weekly_result, weekly_meta = await fetch_options_chain(
                    symbol=symbol,
                    api_key=api_key,
                    option_type="call",
                    max_dte=7,
                    min_dte=1,
                    current_price=current_price,
                    friday_only=True,
                    require_complete_data=True
                )
                
                # Monthly: DTE 8-45
                monthly_result, monthly_meta = await fetch_options_chain(
                    symbol=symbol,
                    api_key=api_key,
                    option_type="call",
                    max_dte=45,
                    min_dte=8,
                    current_price=current_price,
                    friday_only=True,
                    require_complete_data=True
                )
                
                # Track snapshot time
                if weekly_meta.get("snapshot_time") and not options_snapshot_time:
                    options_snapshot_time = weekly_meta["snapshot_time"]
                
                all_options = []
                if weekly_result:
                    for opt in weekly_result:
                        opt["expiry_type"] = "weekly"
                    all_options.extend(weekly_result)
                if monthly_result:
                    for opt in monthly_result:
                        opt["expiry_type"] = "monthly"
                    all_options.extend(monthly_result)
                
                if not all_options:
                    continue
                
                for opt in all_options:
                    strike = opt.get("strike", 0)
                    dte = opt.get("dte", 0)
                    premium = opt.get("close", 0) or opt.get("vwap", 0)
                    expiry_type = opt.get("expiry_type", "Monthly")
                    open_interest = opt.get("open_interest", 0) or 0
                    
                    if not premium or premium <= 0:
                        continue
                    
                    # DATA QUALITY FILTER: Premium sanity check (tighter for OTM)
                    # OTM calls premium shouldn't exceed 10% of stock price
                    max_reasonable_premium = current_price * 0.10
                    if premium > max_reasonable_premium:
                        continue
                    
                    # Filter for OTM calls
                    if strike <= current_price:
                        continue
                    
                    strike_pct = ((strike - current_price) / current_price) * 100
                    if strike_pct > 10:  # Max 10% OTM
                        continue
                    
                    roi_pct = (premium / current_price) * 100
                    
                    # ROI filters - Weekly needs at least 0.8%, Monthly needs at least 2.5%
                    if expiry_type == "Weekly" and roi_pct < 0.8:
                        continue
                    if expiry_type == "Monthly" and roi_pct < 2.5:
                        continue
                    
                    annualized_roi = (roi_pct / max(dte, 1)) * 365
                    
                    # Estimate delta based on strike distance
                    estimated_delta = max(0.15, min(0.50, 0.50 - strike_pct * 0.025))
                    
                    # Get implied volatility from the option data
                    iv = opt.get("implied_volatility", 0)
                    if iv and iv > 0:
                        iv = iv * 100  # Convert to percentage
                    else:
                        iv = 30  # Default estimate
                    
                    # Determine moneyness
                    if strike_pct >= -2 and strike_pct <= 2:
                        moneyness = "ATM"
                    else:
                        moneyness = "OTM"
                    
                    # Calculate score with liquidity bonus
                    base_score = roi_pct * 10 + annualized_roi / 10 + (50 - iv) / 10
                    
                    # Liquidity bonus
                    liquidity_bonus = 0
                    if open_interest >= 1000:
                        liquidity_bonus = 10
                    elif open_interest >= 500:
                        liquidity_bonus = 7
                    elif open_interest >= 100:
                        liquidity_bonus = 5
                    elif open_interest >= 50:
                        liquidity_bonus = 2
                    
                    score = round(base_score + liquidity_bonus, 1)
                    
                    opp_data = {
                        "symbol": symbol,
                        "stock_price": round(current_price, 2),
                        "strike": strike,
                        "strike_pct": round(strike_pct, 1),
                        "moneyness": moneyness,
                        "expiry": opt.get("expiry", ""),
                        "expiry_type": expiry_type,
                        "dte": dte,
                        "premium": round(premium, 2),
                        "roi_pct": round(roi_pct, 2),
                        "annualized_roi": round(annualized_roi, 1),
                        "delta": round(estimated_delta, 2),
                        "iv": round(iv, 0),
                        "iv_rank": round(min(100, iv * 1.5), 0),
                        "open_interest": open_interest,
                        "score": score,
                        "analyst_rating": analyst_rating,
                        "days_to_earnings": stock_data.get("days_to_earnings"),
                        "earnings_date": stock_data.get("earnings_date"),
                        "data_source": opt.get("source", "yahoo")
                    }
                    
                    if expiry_type == "Weekly":
                        weekly_opportunities.append(opp_data)
                    else:
                        monthly_opportunities.append(opp_data)
                    
            except Exception as e:
                logging.error(f"Dashboard scan error for {symbol}: {e}")
                continue
        
        # Sort each list and take top 5
        weekly_opportunities.sort(key=lambda x: x["score"], reverse=True)
        monthly_opportunities.sort(key=lambda x: x["score"], reverse=True)
        
        # Dedupe by symbol within each category
        def dedupe_by_symbol(opps, limit):
            best_by_symbol = {}
            for opp in opps:
                sym = opp["symbol"]
                if sym not in best_by_symbol or opp["score"] > best_by_symbol[sym]["score"]:
                    best_by_symbol[sym] = opp
            return sorted(best_by_symbol.values(), key=lambda x: x["score"], reverse=True)[:limit]
        
        top_weekly = dedupe_by_symbol(weekly_opportunities, 5)
        top_monthly = dedupe_by_symbol(monthly_opportunities, 5)
        
        # Combine: Weekly first, then Monthly
        opportunities = top_weekly + top_monthly
        
        result = {
            "opportunities": opportunities, 
            "total": len(opportunities), 
            "weekly_count": len(top_weekly),
            "monthly_count": len(top_monthly),
            "from_cache": False,
            "data_source": "yahoo",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "t1_data": t1_info
        }
        await funcs['set_cached_data'](cache_key, result)
        return result
        
    except Exception as e:
        logging.error(f"Dashboard opportunities error: {e}")
        return {"opportunities": [], "total": 0, "error": str(e), "is_mock": True, "t1_data": t1_info}


@screener_router.get("/pmcc")
async def screen_pmcc(
    min_price: float = Query(20, ge=0),
    max_price: float = Query(150, ge=0),
    min_leaps_dte: int = Query(180, ge=30),
    max_leaps_dte: int = Query(730, ge=30),
    min_short_dte: int = Query(14, ge=1),
    max_short_dte: int = Query(60, ge=1),
    min_leaps_delta: float = Query(0.70, ge=0, le=1),
    max_leaps_delta: float = Query(0.90, ge=0, le=1),
    min_short_delta: float = Query(0.15, ge=0, le=1),
    max_short_delta: float = Query(0.35, ge=0, le=1),
    min_roi: float = Query(2.0, ge=0),
    min_annualized_roi: float = Query(20.0, ge=0),
    bypass_cache: bool = Query(False),
    user: dict = Depends(get_current_user)
):
    """
    Screen for Poor Man's Covered Call (PMCC) opportunities.
    
    TWO-SOURCE DATA MODEL:
    - Equity Price: T-1 market close (hard rule)
    - Options Chain: Latest fully available snapshot with IV/OI
    - Only uses expirations that ACTUALLY exist in Yahoo Finance
    - Only Friday expirations for short leg
    """
    funcs = _get_server_functions()
    t1_info = _get_t1_data_info()
    equity_date = t1_info["equity_price_date"]
    
    cache_params = {
        "equity_date": equity_date,
        "min_price": min_price, "max_price": max_price,
        "min_leaps_dte": min_leaps_dte, "max_leaps_dte": max_leaps_dte,
        "min_short_dte": min_short_dte, "max_short_dte": max_short_dte,
        "min_roi": min_roi, "min_annualized_roi": min_annualized_roi
    }
    cache_key = funcs['generate_cache_key']("pmcc_screener_v2", cache_params)
    
    logging.info(f"PMCC scan (Equity: {equity_date}), bypass_cache: {bypass_cache}")
    
    # Check cache first
    if not bypass_cache:
        cached_data = await funcs['get_cached_data'](cache_key, max_age_seconds=86400)
        if cached_data and cached_data.get("opportunities"):
            cached_data["from_cache"] = True
            cached_data["metadata"] = t1_info
            return cached_data
        
        # Check precomputed scans
        for profile in ["balanced", "aggressive", "conservative"]:
            precomputed = await db.precomputed_scans.find_one(
                {"strategy": "pmcc", "risk_profile": profile},
                {"_id": 0}
            )
            if precomputed and precomputed.get("opportunities"):
                computed_date = precomputed.get("computed_date", "unknown")
                freshness = get_data_freshness_status(computed_date) if computed_date != "unknown" else {"status": "amber"}
                return {
                    "opportunities": precomputed["opportunities"],
                    "total": len(precomputed["opportunities"]),
                    "from_cache": True,
                    "is_precomputed": True,
                    "precomputed_profile": profile,
                    "computed_at": precomputed.get("computed_at"),
                    "metadata": t1_info,
                    "data_freshness": freshness
                }
    
    api_key = await funcs['get_massive_api_key']()
    
    if not api_key:
        return {"opportunities": [], "total": 0, "message": "API key required for PMCC screening", "is_mock": True, "metadata": t1_info}
    
    try:
        # Expanded symbol list for PMCC opportunities
        symbols_to_scan = [
            # Tech
            "INTC", "AMD", "MU", "QCOM", "CSCO", "HPQ", "DELL", "IBM",
            # Financials
            "BAC", "WFC", "C", "USB", "PNC", "KEY", "RF", "CFG",
            # Consumer
            "KO", "PEP", "NKE", "SBUX", "DIS", "GM", "F",
            # Healthcare
            "PFE", "MRK", "ABBV", "BMY", "GILD",
            # Energy
            "OXY", "DVN", "APA", "HAL", "SLB",
            # Growth/Fintech
            "PYPL", "UBER", "SNAP", "SQ", "HOOD",
            # Airlines/Travel
            "AAL", "DAL", "UAL", "CCL", "NCLH",
            # High volatility
            "PLTR", "SOFI"
        ]
        
        opportunities = []
        options_snapshot_time = None
        
        for symbol in symbols_to_scan:
            try:
                # Get stock price using centralized data provider (T-1 close)
                stock_data = await fetch_stock_quote(symbol, api_key)
                
                if not stock_data or stock_data.get("price", 0) == 0:
                    continue
                
                current_price = stock_data["price"]
                
                if current_price < min_price or current_price > max_price:
                    continue
                
                # Get LEAPS options (long leg) - allow all Friday expirations for LEAPS
                leaps_options, leaps_meta = await fetch_options_chain(
                    symbol=symbol,
                    api_key=api_key,
                    option_type="call",
                    max_dte=max_leaps_dte,
                    min_dte=min_leaps_dte,
                    current_price=current_price,
                    friday_only=True,
                    require_complete_data=True
                )
                
                # Get short-term options (short leg) - Friday only
                short_options, short_meta = await fetch_options_chain(
                    symbol=symbol,
                    api_key=api_key,
                    option_type="call",
                    max_dte=max_short_dte,
                    min_dte=min_short_dte,
                    current_price=current_price,
                    friday_only=True,
                    require_complete_data=True
                )
                
                # Track snapshot time
                if leaps_meta.get("snapshot_time") and not options_snapshot_time:
                    options_snapshot_time = leaps_meta["snapshot_time"]
                
                if not leaps_options or not short_options:
                    logging.debug(f"No LEAPS or short options for {symbol}: leaps={leaps_meta.get('error', 'none')}, short={short_meta.get('error', 'none')}")
                    continue
                
                # Filter LEAPS for deep ITM (high delta)
                filtered_leaps = []
                for opt in leaps_options:
                    strike = opt.get("strike", 0)
                    open_interest = opt.get("open_interest", 0) or 0
                    premium = opt.get("close", 0)
                    iv = opt.get("implied_volatility", 0)
                    
                    # Skip if no IV (already filtered by data_provider but double-check)
                    if iv <= 0:
                        continue
                    
                    # Skip low liquidity
                    if open_interest < 10:
                        continue
                    
                    if strike < current_price * 0.85:  # Deep ITM
                        estimated_delta = min(0.90, 0.70 + (current_price - strike) / current_price * 0.5)
                        if min_leaps_delta <= estimated_delta <= max_leaps_delta:
                            opt["delta"] = estimated_delta
                            opt["cost"] = premium * 100
                            opt["open_interest"] = open_interest
                            if opt["cost"] > 0:
                                filtered_leaps.append(opt)
                
                # Filter short options for OTM
                filtered_short = []
                for opt in short_options:
                    strike = opt.get("strike", 0)
                    open_interest = opt.get("open_interest", 0) or 0
                    premium = opt.get("close", 0) or opt.get("vwap", 0)
                    
                    # DATA QUALITY FILTER: Skip low OI
                    if open_interest < 10:
                        continue
                    
                    # DATA QUALITY FILTER: Premium sanity for OTM short calls
                    max_short_premium = current_price * 0.20
                    if premium > max_short_premium:
                        continue
                    
                    if strike > current_price:  # OTM
                        strike_pct = ((strike - current_price) / current_price) * 100
                        estimated_delta = max(0.15, 0.50 - strike_pct * 0.03)
                        if min_short_delta <= estimated_delta <= max_short_delta:
                            opt["delta"] = estimated_delta
                            opt["premium"] = premium * 100
                            opt["open_interest"] = open_interest
                            if opt["premium"] > 0:
                                filtered_short.append(opt)
                
                # Generate multiple combinations per symbol (up to top 3 LEAPS x top 3 shorts)
                if filtered_leaps and filtered_short:
                    # Sort LEAPS by delta (highest first - deepest ITM)
                    filtered_leaps.sort(key=lambda x: x["delta"], reverse=True)
                    # Sort shorts by delta closest to 0.25 (ideal short delta)
                    filtered_short.sort(key=lambda x: abs(x["delta"] - 0.25))
                    
                    # Take top 3 of each for combinations
                    top_leaps = filtered_leaps[:3]
                    top_shorts = filtered_short[:3]
                    
                    for leaps in top_leaps:
                        for short in top_shorts:
                            if leaps["cost"] <= 0:
                                continue
                                
                            net_debit = leaps["cost"] - short["premium"]
                            
                            if net_debit <= 0:
                                continue
                            
                            roi_per_cycle = (short["premium"] / leaps["cost"]) * 100
                            cycles_per_year = 365 / max(short.get("dte", 30), 7)
                            annualized_roi = roi_per_cycle * min(cycles_per_year, 52)
                            
                            if roi_per_cycle < min_roi or annualized_roi < min_annualized_roi:
                                continue
                            
                            # Score based on ROI, delta quality, and capital efficiency
                            roi_score = roi_per_cycle * 10
                            delta_score = (leaps["delta"] - 0.7) * 50  # Bonus for higher LEAPS delta
                            efficiency_score = (1 - net_debit / (current_price * 100)) * 20  # Lower cost = better
                            score = round(roi_score + delta_score + efficiency_score + annualized_roi / 5, 1)
                            
                            opportunities.append({
                                    "symbol": symbol,
                                    "stock_price": round(current_price, 2),
                                    "leaps_strike": leaps.get("strike"),
                                    "leaps_expiry": leaps.get("expiry"),
                                    "leaps_dte": leaps.get("dte"),
                                    "leaps_delta": round(leaps["delta"], 2),
                                    "leaps_cost": round(leaps["cost"], 2),
                                    "leaps_iv": round(leaps.get("implied_volatility", 0), 4),
                                    "leaps_oi": leaps.get("open_interest", 0),
                                    "short_strike": short.get("strike"),
                                    "short_expiry": short.get("expiry"),
                                    "short_dte": short.get("dte"),
                                    "short_delta": round(short["delta"], 2),
                                    "short_premium": round(short["premium"], 2),
                                    "short_iv": round(short.get("implied_volatility", 0), 4),
                                    "short_oi": short.get("open_interest", 0),
                                    "net_debit": round(net_debit, 2),
                                    "roi_per_cycle": round(roi_per_cycle, 2),
                                    "annualized_roi": round(annualized_roi, 1),
                                    "score": round(score, 1),
                                    # Metadata
                                    "equity_price_date": equity_date,
                                    "options_snapshot_time": options_snapshot_time,
                                    "data_source": "yahoo"
                                })
                    
            except Exception as e:
                logging.error(f"PMCC scan error for {symbol}: {e}")
                continue
        
        # Sort by score and limit to top 100
        opportunities.sort(key=lambda x: x["score"], reverse=True)
        opportunities = opportunities[:100]
        
        # Fetch analyst ratings for all symbols
        symbols = [opp["symbol"] for opp in opportunities]
        analyst_ratings = await fetch_analyst_ratings_batch(symbols)
        
        # Add analyst ratings
        for opp in opportunities:
            opp["analyst_rating"] = analyst_ratings.get(opp["symbol"])
        
        result = {
            "opportunities": opportunities, 
            "total": len(opportunities), 
            "from_cache": False,
            "metadata": {
                "equity_price_date": equity_date,
                "equity_price_source": "T-1 Market Close",
                "options_snapshot_time": options_snapshot_time,
                "data_source": "yahoo",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "staleness_thresholds": t1_info.get("staleness_thresholds", {})
            }
        }
        await funcs['set_cached_data'](cache_key, result)
        return result
        
    except Exception as e:
        logging.error(f"PMCC screener error: {e}")
        return {"opportunities": [], "total": 0, "error": str(e), "is_mock": True, "metadata": t1_info}


@screener_router.get("/dashboard-pmcc")
async def get_dashboard_pmcc(user: dict = Depends(get_current_user)):
    """Get top PMCC opportunities for dashboard - uses T-1 data"""
    funcs = _get_server_functions()
    t1_info = _get_t1_data_info()
    t1_date = t1_info["data_date"]
    
    cache_key = f"dashboard_pmcc_t1_{t1_date}"
    
    # Check cache (valid for entire T-1 day)
    cached_data = await funcs['get_cached_data'](cache_key, max_age_seconds=86400)
    if cached_data:
        cached_data["from_cache"] = True
        cached_data["t1_data"] = t1_info
        return cached_data
    
    # Call the main PMCC screener with explicit default values
    result = await screen_pmcc(
        min_price=20,
        max_price=150,
        min_leaps_dte=180,
        max_leaps_dte=730,
        min_short_dte=14,
        max_short_dte=60,
        min_leaps_delta=0.70,
        max_leaps_delta=0.90,
        min_short_delta=0.15,
        max_short_delta=0.35,
        min_roi=2.0,
        min_annualized_roi=20.0,
        bypass_cache=True,  # We're already caching at this level
        user=user
    )
    
    if result.get("opportunities"):
        # Limit to top 10 for dashboard
        result["opportunities"] = result["opportunities"][:10]
        await funcs['set_cached_data'](cache_key, result)
    
    return result


@screener_router.get("/filters")
async def get_saved_filters(user: dict = Depends(get_current_user)):
    """Get user's saved screener filters"""
    filters = await db.screener_filters.find({"user_id": user["id"]}, {"_id": 0}).to_list(100)
    return filters


@screener_router.post("/clear-cache")
async def clear_screener_cache(user: dict = Depends(get_current_user)):
    """Clear all screener-related cache to force fresh data fetch"""
    funcs = _get_server_functions()
    
    try:
        prefixes_to_clear = [
            "screener_covered_calls",
            "pmcc_screener",
            "dashboard_opportunities",
            "dashboard_pmcc"
        ]
        total_cleared = 0
        for prefix in prefixes_to_clear:
            count = await funcs['clear_cache'](prefix)
            total_cleared += count
        
        logging.info(f"Cache cleared by user {user.get('email')}: {total_cleared} entries")
        return {"message": "Cache cleared successfully", "entries_cleared": total_cleared}
    except Exception as e:
        logging.error(f"Error clearing cache: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to clear cache: {str(e)}")


@screener_router.post("/refresh-precomputed")
async def refresh_precomputed_scans(user: dict = Depends(get_current_user)):
    """
    Manually trigger a refresh of all precomputed scans.
    This updates both Covered Call and PMCC scans with fresh market data.
    
    Note: This is rate-limited and should only be called when data seems stale.
    """
    try:
        from services.precomputed_scans import PrecomputedScanService
        
        # Check if user is admin
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Admin access required")
        
        funcs = _get_server_functions()
        api_key = await funcs['get_massive_api_key']()
        
        service = PrecomputedScanService(db, api_key)
        
        logging.info(f"Manual precomputed scan refresh triggered by {user.get('email')}")
        
        # Run the scan computation
        results = await service.run_all_scans()
        
        return {
            "message": "Precomputed scans refreshed successfully",
            "results": results,
            "refreshed_at": datetime.now(timezone.utc).isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error refreshing precomputed scans: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to refresh scans: {str(e)}")


@screener_router.get("/data-quality")
async def get_data_quality_status(user: dict = Depends(get_current_user)):
    """
    Get data quality status for all screener data sources.
    Uses T-1 data principle - shows green/amber/red status for each scan.
    """
    t1_info = _get_t1_data_info()
    t1_date = t1_info["data_date"]
    
    # Check precomputed scan freshness
    precomputed_status = []
    for strategy in ["covered_call", "pmcc"]:
        for profile in ["conservative", "balanced", "aggressive"]:
            scan = await db.precomputed_scans.find_one(
                {"strategy": strategy, "risk_profile": profile},
                {"_id": 0, "opportunities": 0}
            )
            if scan:
                computed_date = scan.get("computed_date", "")
                computed_at = scan.get("computed_at", "")
                
                # Get freshness status using trading calendar
                if computed_date:
                    freshness = get_data_freshness_status(computed_date)
                else:
                    freshness = {"status": "red", "label": "Unknown", "description": "No computed date"}
                
                precomputed_status.append({
                    "strategy": strategy,
                    "profile": profile,
                    "count": scan.get("count", 0),
                    "computed_date": computed_date,
                    "computed_at": computed_at,
                    "status": freshness["status"],
                    "status_label": freshness["label"],
                    "status_description": freshness["description"]
                })
            else:
                precomputed_status.append({
                    "strategy": strategy,
                    "profile": profile,
                    "count": 0,
                    "computed_date": None,
                    "computed_at": None,
                    "status": "red",
                    "status_label": "Missing",
                    "status_description": "No precomputed data available"
                })
    
    return {
        "t1_data": t1_info,
        "precomputed_scans": precomputed_status,
        "data_quality_note": (
            f"CCE uses T-1 (previous trading day) market close data. "
            f"Current T-1 date: {t1_date}. "
            f"Data is refreshed daily after 4:00 PM ET market close."
        ),
        "checked_at": datetime.now(timezone.utc).isoformat()
    }


@screener_router.get("/data-quality-dashboard")
async def get_data_quality_dashboard(user: dict = Depends(get_current_user)):
    """
    Admin Data Quality Dashboard - Shows green/amber/red status for all scans.
    
    Returns comprehensive status with actionable information.
    """
    t1_info = _get_t1_data_info()
    
    # Get market data status
    market_status = get_market_data_status()
    
    # Scan statuses with traffic light indicators
    scan_statuses = []
    
    # 1. Covered Call Scans
    for profile in ["conservative", "balanced", "aggressive"]:
        scan = await db.precomputed_scans.find_one(
            {"strategy": "covered_call", "risk_profile": profile},
            {"_id": 0, "opportunities": 0}
        )
        
        if scan:
            computed_date = scan.get("computed_date", "")
            freshness = get_data_freshness_status(computed_date) if computed_date else {"status": "red", "days_old": None}
            
            scan_statuses.append({
                "scan_type": "Covered Call",
                "profile": profile.title(),
                "status": freshness["status"],
                "status_emoji": "🟢" if freshness["status"] == "green" else "🟡" if freshness["status"] == "amber" else "🔴",
                "count": scan.get("count", 0),
                "computed_date": computed_date,
                "computed_at": scan.get("computed_at", ""),
                "days_old": freshness.get("days_old"),
                "needs_refresh": freshness["status"] != "green"
            })
        else:
            scan_statuses.append({
                "scan_type": "Covered Call",
                "profile": profile.title(),
                "status": "red",
                "status_emoji": "🔴",
                "count": 0,
                "computed_date": None,
                "computed_at": None,
                "days_old": None,
                "needs_refresh": True
            })
    
    # 2. PMCC Scans
    for profile in ["conservative", "balanced", "aggressive"]:
        scan = await db.precomputed_scans.find_one(
            {"strategy": "pmcc", "risk_profile": profile},
            {"_id": 0, "opportunities": 0}
        )
        
        if scan:
            computed_date = scan.get("computed_date", "")
            freshness = get_data_freshness_status(computed_date) if computed_date else {"status": "red", "days_old": None}
            
            scan_statuses.append({
                "scan_type": "PMCC",
                "profile": profile.title(),
                "status": freshness["status"],
                "status_emoji": "🟢" if freshness["status"] == "green" else "🟡" if freshness["status"] == "amber" else "🔴",
                "count": scan.get("count", 0),
                "computed_date": computed_date,
                "computed_at": scan.get("computed_at", ""),
                "days_old": freshness.get("days_old"),
                "needs_refresh": freshness["status"] != "green"
            })
        else:
            scan_statuses.append({
                "scan_type": "PMCC",
                "profile": profile.title(),
                "status": "red",
                "status_emoji": "🔴",
                "count": 0,
                "computed_date": None,
                "computed_at": None,
                "days_old": None,
                "needs_refresh": True
            })
    
    # Count by status
    green_count = sum(1 for s in scan_statuses if s["status"] == "green")
    amber_count = sum(1 for s in scan_statuses if s["status"] == "amber")
    red_count = sum(1 for s in scan_statuses if s["status"] == "red")
    
    # Overall status
    if red_count > 0:
        overall_status = "red"
        overall_message = f"{red_count} scan(s) need refresh"
    elif amber_count > 0:
        overall_status = "amber"
        overall_message = f"{amber_count} scan(s) slightly stale"
    else:
        overall_status = "green"
        overall_message = "All scans up to date"
    
    return {
        "t1_data": t1_info,
        "market_status": market_status,
        "overall_status": overall_status,
        "overall_status_emoji": "🟢" if overall_status == "green" else "🟡" if overall_status == "amber" else "🔴",
        "overall_message": overall_message,
        "summary": {
            "green": green_count,
            "amber": amber_count,
            "red": red_count,
            "total": len(scan_statuses)
        },
        "scans": scan_statuses,
        "actions": {
            "refresh_endpoint": "/api/screener/refresh-precomputed",
            "refresh_available": True,
            "note": "Refresh will update all scans with T-1 market close data"
        },
        "checked_at": datetime.now(timezone.utc).isoformat()
    }


@screener_router.post("/filters")
async def save_filter(filter_data: ScreenerFilterCreate, user: dict = Depends(get_current_user)):
    """Save a screener filter preset"""
    import uuid
    
    filter_doc = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "name": filter_data.name,
        "filters": filter_data.filters,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.screener_filters.insert_one(filter_doc)
    return {"id": filter_doc["id"], "message": "Filter saved successfully"}


@screener_router.delete("/filters/{filter_id}")
async def delete_filter(filter_id: str, user: dict = Depends(get_current_user)):
    """Delete a saved filter"""
    result = await db.screener_filters.delete_one({"id": filter_id, "user_id": user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Filter not found")
    return {"message": "Filter deleted"}
