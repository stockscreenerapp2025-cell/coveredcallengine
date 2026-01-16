"""
Screener Routes - Covered Call and PMCC screening endpoints
Designed for scalability with proper caching, async patterns, and efficient data processing

DATA SOURCING STRATEGY:
- OPTIONS DATA: Yahoo Finance primary, Polygon backup
- STOCK DATA: Yahoo Finance primary, Polygon backup
- All data sourcing is handled by services/data_provider.py

T-1 DATA PRINCIPLE (STRICT):
- CCE must always use T-1 market close data (last completed trading session)
- No intraday or partial data is ever used
- Weekend/Holiday handling: Auto-rollback to most recent trading day
- Data freshness indicators show T-1 date consistently

DATA USAGE RULES:
1. Default & Only Data Source: T-1 market close data
2. No Intraday: Do not pull intraday quotes or mix data
3. Holiday/Weekend: Automatically roll back to most recent completed trading day
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
# Import centralized data provider (T-1 data principle)
from services.data_provider import (
    fetch_options_chain,
    fetch_stock_quote,
    get_data_date,
    get_data_source_status,
    calculate_dte
)
# Import trading calendar for T-1 dates
from services.trading_calendar import (
    get_t_minus_1,
    get_market_data_status,
    get_data_freshness_status,
    is_valid_expiration_date
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
    
    DATA SOURCES:
    - Options: Polygon/Massive ONLY
    - Stock prices: Polygon primary, Yahoo fallback
    
    DATA QUALITY:
    - When market is OPEN: Always fetch live data (cache only used for rate limiting)
    - When market is CLOSED: Use cached data from last trading day
    - All responses include data freshness indicators
    """
    funcs = _get_server_functions()
    market_closed = funcs['is_market_closed']()
    
    # Generate cache key based on all filter parameters
    cache_params = {
        "min_roi": min_roi, "max_dte": max_dte, "min_delta": min_delta, "max_delta": max_delta,
        "min_iv_rank": min_iv_rank, "min_price": min_price, "max_price": max_price,
        "include_stocks": include_stocks, "include_etfs": include_etfs, "include_index": include_index,
        "min_volume": min_volume, "min_open_interest": min_open_interest,
        "weekly_only": weekly_only, "monthly_only": monthly_only
    }
    cache_key = funcs['generate_cache_key']("screener_covered_calls_v3", cache_params)
    
    # DATA QUALITY PRINCIPLE: Only use cache when market is CLOSED
    # When market is open, we want fresh data (use short cache for rate limiting only)
    if market_closed and not bypass_cache:
        # Market closed - prefer cached data
        cached_data = await funcs['get_cached_data'](cache_key)
        if cached_data and cached_data.get("opportunities"):
            cached_data["from_cache"] = True
            cached_data["market_closed"] = True
            cached_data["data_note"] = "Cached data from last market session"
            return cached_data
        
        # Try last trading day data
        ltd_data = await funcs['get_last_trading_day_data'](cache_key)
        if ltd_data and ltd_data.get("opportunities"):
            ltd_data["from_cache"] = True
            ltd_data["market_closed"] = True
            ltd_data["is_last_trading_day"] = True
            ltd_data["data_note"] = "Data from last trading day"
            return ltd_data
        
        # Fallback to precomputed balanced scan
        precomputed = await db.precomputed_scans.find_one(
            {"strategy": "covered_call", "risk_profile": "balanced"},
            {"_id": 0}
        )
        if precomputed and precomputed.get("opportunities"):
            return {
                "opportunities": precomputed["opportunities"],
                "total": len(precomputed["opportunities"]),
                "from_cache": True,
                "market_closed": True,
                "is_precomputed_fallback": True,
                "precomputed_profile": "balanced",
                "computed_at": precomputed.get("computed_at"),
                "data_note": f"Pre-computed scan from {precomputed.get('computed_date', 'unknown')}"
            }
    elif not bypass_cache:
        # Market open - use short cache (5 min) for rate limiting only
        cached_data = await funcs['get_cached_data'](cache_key, max_age_seconds=300)
        if cached_data and cached_data.get("opportunities"):
            cached_data["from_cache"] = True
            cached_data["market_closed"] = False
            cached_data["data_note"] = "Live data (cached < 5 min)"
            return cached_data
    
    # Get API key for Polygon/Massive
    api_key = await funcs['get_massive_api_key']()
    
    logging.info(f"Covered Calls Screener: api_key={'present' if api_key else 'missing'}, min_roi={min_roi}, max_dte={max_dte}")
    
    if not api_key:
        # No API key - return mock data
        opportunities = funcs['generate_mock_covered_call_opportunities']()
        filtered = [o for o in opportunities if o["roi_pct"] >= min_roi and o["dte"] <= max_dte]
        return {"opportunities": filtered[:20], "total": len(filtered), "is_mock": True, "message": "API key required for live data"}
    
    try:
        opportunities = []
        
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
                # Get stock price using centralized data provider (Yahoo primary)
                stock_data = await fetch_stock_quote(symbol, api_key)
                
                if not stock_data or stock_data.get("price", 0) == 0:
                    continue
                
                underlying_price = stock_data["price"]
                analyst_rating = stock_data.get("analyst_rating")
                
                is_etf = symbol.upper() in ETF_SYMBOLS
                if not is_etf and (underlying_price < min_price or underlying_price > max_price):
                    continue
                
                # Get options chain (Yahoo primary with IV/OI, Polygon backup)
                options_results = await fetch_options_chain(
                    symbol, api_key, "call", max_dte, min_dte=1, current_price=underlying_price
                )
                
                if not options_results:
                    logging.debug(f"No options data for {symbol}")
                    continue
                
                for opt in options_results:
                    strike = opt.get("strike", 0)
                    expiry = opt.get("expiry", "")
                    dte = opt.get("dte", 0)
                    
                    strike_pct = (strike / underlying_price) * 100 if underlying_price > 0 else 0
                    if is_etf:
                        if strike_pct < 95 or strike_pct > 108:
                            continue
                    else:
                        if strike_pct < 97 or strike_pct > 115:
                            continue
                    
                    if dte > max_dte or dte < 1:
                        continue
                    if weekly_only and dte > 7:
                        continue
                    if monthly_only and dte <= 7:
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
                    
                    premium = opt.get("close", 0) or opt.get("vwap", 0)
                    
                    if premium <= 0:
                        continue
                    
                    # DATA QUALITY FILTER: Check for unrealistic premiums
                    # For OTM calls, premium should not exceed intrinsic value + reasonable time value
                    # Rule 1: Max reasonable premium for OTM call: ~10% of underlying price for 30-45 DTE
                    max_reasonable_premium = underlying_price * 0.10
                    if strike > underlying_price and premium > max_reasonable_premium:
                        logging.debug(f"Skipping {symbol} ${strike}C: premium ${premium} exceeds reasonable max ${max_reasonable_premium:.2f}")
                        continue
                    
                    # DATA QUALITY FILTER: Open interest check (when available from Yahoo)
                    open_interest = opt.get("open_interest", 0) or 0
                    # If we have OI data from Yahoo, filter out illiquid options
                    if open_interest > 0 and open_interest < 10:
                        logging.debug(f"Skipping {symbol} ${strike}C: open interest {open_interest} < 10")
                        continue
                    
                    roi_pct = (premium / underlying_price) * 100
                    
                    if roi_pct < min_roi:
                        continue
                    
                    volume = opt.get("volume", 0) or 0
                    
                    if volume < min_volume:
                        continue
                    
                    iv = opt.get("implied_volatility", 0.25)
                    iv_rank = min(100, iv * 100)
                    
                    if iv_rank < min_iv_rank:
                        continue
                    
                    # Calculate downside protection
                    if strike > underlying_price:
                        protection = (premium / underlying_price) * 100
                    else:
                        protection = ((strike - underlying_price + premium) / underlying_price * 100)
                    
                    # Calculate score with liquidity bonus/penalty
                    roi_score = min(roi_pct * 15, 40)
                    iv_score = min(iv_rank / 100 * 20, 20)
                    delta_score = max(0, 20 - abs(estimated_delta - 0.3) * 50)
                    protection_score = min(abs(protection), 10) * 2
                    
                    # Liquidity bonus: reward high open interest
                    liquidity_score = 0
                    if open_interest >= 1000:
                        liquidity_score = 10
                    elif open_interest >= 500:
                        liquidity_score = 7
                    elif open_interest >= 100:
                        liquidity_score = 5
                    elif open_interest >= 50:
                        liquidity_score = 2
                    # Low OI already filtered out above
                    
                    score = round(roi_score + iv_score + delta_score + protection_score + liquidity_score, 1)
                    
                    opportunities.append({
                        "symbol": symbol,
                        "stock_price": round(underlying_price, 2),
                        "strike": strike,
                        "expiry": expiry,
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
                        "data_source": opt.get("source", "yahoo"),
                        "data_quality": "fresh"  # Live data is always fresh
                    })
            except Exception as e:
                logging.error(f"Error scanning {symbol}: {e}")
                continue
        
        # Sort and dedupe
        opportunities.sort(key=lambda x: x["score"], reverse=True)
        best_by_symbol = {}
        for opp in opportunities:
            sym = opp["symbol"]
            if sym not in best_by_symbol or opp["score"] > best_by_symbol[sym]["score"]:
                best_by_symbol[sym] = opp
        
        opportunities = sorted(best_by_symbol.values(), key=lambda x: x["score"], reverse=True)
        
        result = {
            "opportunities": opportunities, 
            "total": len(opportunities), 
            "is_live": True, 
            "from_cache": False,
            "market_closed": market_closed,
            "data_source": "polygon",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "data_freshness_score": 100.0,  # Live data = 100% fresh
            "data_note": "Live market data"
        }
        await funcs['set_cached_data'](cache_key, result)
        return result
        
    except Exception as e:
        logging.error(f"Screener error: {e}")
        return {"opportunities": [], "total": 0, "error": str(e), "is_live": False}



@screener_router.get("/dashboard-opportunities")
async def get_dashboard_opportunities(user: dict = Depends(get_current_user)):
    """
    Get top 10 covered call opportunities for dashboard - 5 Weekly + 5 Monthly.
    
    DATA SOURCES:
    - Options: Polygon/Massive ONLY
    - Stock prices: Polygon primary, Yahoo fallback
    """
    funcs = _get_server_functions()
    
    cache_key = "dashboard_opportunities_v4"
    
    cached_data = await funcs['get_cached_data'](cache_key)
    if cached_data:
        cached_data["from_cache"] = True
        cached_data["market_closed"] = funcs['is_market_closed']()
        return cached_data
    
    if funcs['is_market_closed']():
        ltd_data = await funcs['get_last_trading_day_data'](cache_key)
        if ltd_data:
            ltd_data["from_cache"] = True
            ltd_data["market_closed"] = True
            return ltd_data
    
    api_key = await funcs['get_massive_api_key']()
    
    if not api_key:
        return {"opportunities": [], "total": 0, "message": "API key not configured", "is_mock": True}
    
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
        
        for symbol in symbols_to_scan[:35]:  # Limit for performance
            try:
                # Get stock price using centralized data provider (Yahoo primary)
                stock_data = await fetch_stock_quote(symbol, api_key)
                
                if not stock_data or stock_data.get("price", 0) == 0:
                    continue
                
                current_price = stock_data["price"]
                analyst_rating = stock_data.get("analyst_rating")
                
                if current_price < 25 or current_price > 100:
                    continue
                
                # Get options - Yahoo primary with IV/OI
                weekly_options = await fetch_options_chain(
                    symbol, api_key, "call", 7, min_dte=1, current_price=current_price
                )
                
                monthly_options = await fetch_options_chain(
                    symbol, api_key, "call", 45, min_dte=8, current_price=current_price
                )
                
                all_options = []
                if weekly_options:
                    for opt in weekly_options:
                        opt["expiry_type"] = "Weekly"
                    all_options.extend(weekly_options)
                if monthly_options:
                    for opt in monthly_options:
                        opt["expiry_type"] = "Monthly"
                    all_options.extend(monthly_options)
                
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
            "is_live": True,
            "data_source": "yahoo_primary",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "data_freshness_score": 100.0,
            "data_note": "Live market data"
        }
        await funcs['set_cached_data'](cache_key, result)
        return result
        
    except Exception as e:
        logging.error(f"Dashboard opportunities error: {e}")
        return {"opportunities": [], "total": 0, "error": str(e), "is_mock": True}


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
    Generates multiple combinations per symbol for better coverage.
    
    DATA SOURCES:
    - Options: Polygon/Massive ONLY
    - Stock prices: Polygon primary, Yahoo fallback
    
    DATA QUALITY PRINCIPLES:
    - When market is OPEN: Always fetch live data
    - When market is CLOSED: Use cached/precomputed data with freshness indicators
    - All expiry dates are validated against current option chains
    - Include data freshness score in response
    """
    funcs = _get_server_functions()
    market_closed = funcs['is_market_closed']()
    
    cache_params = {
        "min_price": min_price, "max_price": max_price,
        "min_leaps_dte": min_leaps_dte, "max_leaps_dte": max_leaps_dte,
        "min_short_dte": min_short_dte, "max_short_dte": max_short_dte,
        "min_roi": min_roi, "min_annualized_roi": min_annualized_roi
    }
    cache_key = funcs['generate_cache_key']("pmcc_screener_v2", cache_params)
    
    logging.info(f"PMCC scan - market_closed: {market_closed}, bypass_cache: {bypass_cache}")
    
    # DATA QUALITY PRINCIPLE: Only use cache when market is CLOSED
    if market_closed and not bypass_cache:
        # Try cache first
        cached_data = await funcs['get_cached_data'](cache_key)
        if cached_data and cached_data.get("opportunities"):
            cached_data["from_cache"] = True
            cached_data["market_closed"] = True
            cached_data["data_note"] = "Cached data from last market session"
            return cached_data
        
        # Try last trading day data
        ltd_data = await funcs['get_last_trading_day_data'](cache_key)
        if ltd_data and ltd_data.get("opportunities"):
            ltd_data["from_cache"] = True
            ltd_data["market_closed"] = True
            ltd_data["is_last_trading_day"] = True
            ltd_data["data_note"] = "Data from last trading day"
            return ltd_data
        
        # Fallback to precomputed scans
        for profile in ["balanced", "aggressive", "conservative"]:
            precomputed = await db.precomputed_scans.find_one(
                {"strategy": "pmcc", "risk_profile": profile},
                {"_id": 0}
            )
            if precomputed and precomputed.get("opportunities"):
                return {
                    "opportunities": precomputed["opportunities"],
                    "total": len(precomputed["opportunities"]),
                    "from_cache": True,
                    "market_closed": True,
                    "is_precomputed_fallback": True,
                    "precomputed_profile": profile,
                    "computed_at": precomputed.get("computed_at"),
                    "data_note": f"Pre-computed {profile} scan from {precomputed.get('computed_date', 'unknown')}"
                }
    elif not bypass_cache:
        # Market open - use short cache (5 min) for rate limiting only
        cached_data = await funcs['get_cached_data'](cache_key, max_age_seconds=300)
        if cached_data and cached_data.get("opportunities"):
            cached_data["from_cache"] = True
            cached_data["market_closed"] = False
            cached_data["data_note"] = "Live data (cached < 5 min)"
            return cached_data
    
    api_key = await funcs['get_massive_api_key']()
    
    if not api_key:
        return {"opportunities": [], "total": 0, "message": "API key required for PMCC screening", "is_mock": True}
    
    try:
        # Expanded symbol list for more opportunities
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
        
        for symbol in symbols_to_scan:
            try:
                # Get stock price using centralized data provider
                stock_data = await fetch_stock_quote(symbol, api_key)
                
                if not stock_data or stock_data.get("price", 0) == 0:
                    continue
                
                current_price = stock_data["price"]
                
                if current_price < min_price or current_price > max_price:
                    continue
                
                # Get LEAPS options from Polygon ONLY (long leg)
                leaps_options = await fetch_options_chain(
                    symbol, api_key, "call", max_leaps_dte, min_dte=min_leaps_dte, current_price=current_price
                )
                
                # Get short-term options from Polygon ONLY (short leg)
                short_options = await fetch_options_chain(
                    symbol, api_key, "call", max_short_dte, min_dte=min_short_dte, current_price=current_price
                )
                
                if not leaps_options or not short_options:
                    logging.debug(f"No LEAPS or short options from Polygon for {symbol}")
                    continue
                
                # Filter LEAPS for deep ITM (high delta)
                filtered_leaps = []
                for opt in leaps_options:
                    strike = opt.get("strike", 0)
                    open_interest = opt.get("open_interest", 0) or 0
                    premium = opt.get("close", 0) or opt.get("vwap", 0)
                    
                    # DATA QUALITY FILTER: Skip low OI
                    if open_interest < 10:
                        continue
                    
                    # DATA QUALITY FILTER: Premium sanity check for LEAPS
                    # LEAPS premium should be reasonable (not > stock price + 50% for deep ITM)
                    max_leaps_premium = current_price * 1.5
                    if premium > max_leaps_premium:
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
                                    "short_strike": short.get("strike"),
                                    "short_expiry": short.get("expiry"),
                                    "short_dte": short.get("dte"),
                                    "short_delta": round(short["delta"], 2),
                                    "short_premium": round(short["premium"], 2),
                                    "net_debit": round(net_debit, 2),
                                    "roi_per_cycle": round(roi_per_cycle, 2),
                                    "annualized_roi": round(annualized_roi, 1),
                                    "score": round(score, 1),
                                    "data_source": "polygon"
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
        
        # Add analyst ratings and data quality flag to opportunities
        for opp in opportunities:
            opp["analyst_rating"] = analyst_ratings.get(opp["symbol"])
            opp["data_quality"] = "fresh"  # Live data is always fresh
        
        result = {
            "opportunities": opportunities, 
            "total": len(opportunities), 
            "is_live": True, 
            "from_cache": False,
            "market_closed": market_closed,
            "data_source": "polygon",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "data_freshness_score": 100.0,  # Live data = 100% fresh
            "data_note": "Live market data"
        }
        await funcs['set_cached_data'](cache_key, result)
        return result
        
    except Exception as e:
        logging.error(f"PMCC screener error: {e}")
        return {"opportunities": [], "total": 0, "error": str(e), "is_mock": True}


@screener_router.get("/dashboard-pmcc")
async def get_dashboard_pmcc(user: dict = Depends(get_current_user)):
    """Get top PMCC opportunities for dashboard - always shows data (from cache/last trading day when market closed)"""
    funcs = _get_server_functions()
    
    cache_key = "dashboard_pmcc_v2"
    
    # Check cache first
    cached_data = await funcs['get_cached_data'](cache_key)
    if cached_data:
        cached_data["from_cache"] = True
        cached_data["market_closed"] = funcs['is_market_closed']()
        return cached_data
    
    # If market is closed and no cache, try last trading day data
    if funcs['is_market_closed']():
        ltd_data = await funcs['get_last_trading_day_data'](cache_key)
        if ltd_data:
            ltd_data["from_cache"] = True
            ltd_data["market_closed"] = True
            ltd_data["is_last_trading_day"] = True
            return ltd_data
    
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
    Returns freshness indicators and any known issues.
    """
    funcs = _get_server_functions()
    market_closed = funcs['is_market_closed']()
    
    # Check precomputed scan freshness
    precomputed_status = []
    for strategy in ["covered_call", "pmcc"]:
        for profile in ["conservative", "balanced", "aggressive"]:
            scan = await db.precomputed_scans.find_one(
                {"strategy": strategy, "risk_profile": profile},
                {"_id": 0, "opportunities": 0}
            )
            if scan:
                computed_at = scan.get("computed_at", "")
                try:
                    if computed_at:
                        dt = datetime.fromisoformat(computed_at.replace('Z', '+00:00'))
                        age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
                        freshness = "fresh" if age_hours < 24 else "stale" if age_hours < 72 else "very_stale"
                    else:
                        age_hours = None
                        freshness = "unknown"
                except:
                    age_hours = None
                    freshness = "unknown"
                
                precomputed_status.append({
                    "strategy": strategy,
                    "profile": profile,
                    "count": scan.get("count", 0),
                    "computed_at": computed_at,
                    "age_hours": round(age_hours, 1) if age_hours else None,
                    "freshness": freshness
                })
    
    return {
        "market_status": "closed" if market_closed else "open",
        "precomputed_scans": precomputed_status,
        "data_quality_note": (
            "When market is open, screeners fetch live data. "
            "When market is closed, cached data from last trading day is used. "
            "Precomputed scans are updated daily at 4:45 PM ET."
        ),
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
