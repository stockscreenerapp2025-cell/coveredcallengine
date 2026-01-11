"""
Screener Routes - Covered Call and PMCC screening endpoints
Designed for scalability with proper caching, async patterns, and efficient data processing
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta
import logging
import httpx

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import db
from utils.auth import get_current_user

screener_router = APIRouter(tags=["Screener"])

# HTTP client settings
HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# ETF symbols for special handling
ETF_SYMBOLS = {"SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK", "XLV", "XLI", "XLB", "XLU", "XLP", "XLY"}


class ScreenerFilterCreate(BaseModel):
    name: str
    filters: Dict[str, Any]


def _get_server_functions():
    """Lazy import to avoid circular dependencies"""
    from server import (
        get_massive_api_key, generate_cache_key, get_cached_data, 
        set_cached_data, get_last_trading_day_data, is_market_closed,
        generate_mock_covered_call_opportunities, clear_cache,
        fetch_options_chain_polygon, fetch_options_chain_yahoo
    )
    return {
        'get_massive_api_key': get_massive_api_key,
        'generate_cache_key': generate_cache_key,
        'get_cached_data': get_cached_data,
        'set_cached_data': set_cached_data,
        'get_last_trading_day_data': get_last_trading_day_data,
        'is_market_closed': is_market_closed,
        'generate_mock_covered_call_opportunities': generate_mock_covered_call_opportunities,
        'clear_cache': clear_cache,
        'fetch_options_chain_polygon': fetch_options_chain_polygon,
        'fetch_options_chain_yahoo': fetch_options_chain_yahoo
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
    """Screen for covered call opportunities with advanced filters"""
    funcs = _get_server_functions()
    
    # Generate cache key based on all filter parameters
    cache_params = {
        "min_roi": min_roi, "max_dte": max_dte, "min_delta": min_delta, "max_delta": max_delta,
        "min_iv_rank": min_iv_rank, "min_price": min_price, "max_price": max_price,
        "include_stocks": include_stocks, "include_etfs": include_etfs, "include_index": include_index,
        "min_volume": min_volume, "min_open_interest": min_open_interest,
        "weekly_only": weekly_only, "monthly_only": monthly_only
    }
    cache_key = funcs['generate_cache_key']("screener_covered_calls", cache_params)
    
    # Check cache first (unless bypassed)
    if not bypass_cache:
        cached_data = await funcs['get_cached_data'](cache_key)
        if cached_data:
            cached_data["from_cache"] = True
            cached_data["market_closed"] = funcs['is_market_closed']()
            return cached_data
        
        # If market is closed and no recent cache, try last trading day data
        if funcs['is_market_closed']():
            ltd_data = await funcs['get_last_trading_day_data'](cache_key)
            if ltd_data:
                ltd_data["from_cache"] = True
                ltd_data["market_closed"] = True
                return ltd_data
    
    # Check if we have Massive.com credentials for live data
    api_key = await funcs['get_massive_api_key']()
    
    logging.info(f"Screener called: api_key={'present' if api_key else 'missing'}, min_roi={min_roi}, max_dte={max_dte}")
    
    if api_key:
        try:
            opportunities = []
            
            # Tiered symbol scanning - prioritize stocks under $100
            tier1_symbols = [
                "INTC", "AMD", "BAC", "WFC", "C", "F", "GM", "T", "VZ",
                "PFE", "MRK", "KO", "PEP", "NKE", "DIS",
                "PYPL", "UBER", "SNAP", "PLTR", "SOFI",
                "AAL", "DAL", "CCL",
                "USB", "PNC", "CFG",
                "DVN", "APA", "HAL", "OXY"
            ]
            
            tier2_symbols = [
                "AAPL", "MSFT", "META", "AMD",
                "JPM", "GS", "V", "MA",
                "HD", "COST",
                "XOM", "CVX"
            ]
            
            etf_symbols = ["SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK"]
            
            # Build symbols list based on security type filters
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
            
            logging.info(f"Symbols to scan: {len(symbols_to_scan)} symbols")
            
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                for symbol in symbols_to_scan:
                    try:
                        # Get current stock price
                        stock_response = await client.get(
                            f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev",
                            params={"apiKey": api_key}
                        )
                        
                        underlying_price = 0
                        if stock_response.status_code == 200:
                            stock_data = stock_response.json()
                            if stock_data.get("results"):
                                underlying_price = stock_data["results"][0].get("c", 0)
                        
                        if underlying_price == 0:
                            continue
                            
                        is_etf = symbol.upper() in ETF_SYMBOLS
                        if not is_etf and (underlying_price < min_price or underlying_price > max_price):
                            continue
                        
                        # Get options chain
                        if is_etf:
                            options_results = await funcs['fetch_options_chain_yahoo'](symbol, "call", max_dte, min_dte=1, current_price=underlying_price)
                        else:
                            options_results = await funcs['fetch_options_chain_polygon'](symbol, api_key, "call", max_dte, min_dte=1, current_price=underlying_price)
                        
                        if not options_results and not is_etf:
                            options_results = await funcs['fetch_options_chain_yahoo'](symbol, "call", max_dte, min_dte=1, current_price=underlying_price)
                        
                        if not options_results:
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
                            
                            roi_pct = (premium / underlying_price) * 100
                            
                            if roi_pct < min_roi:
                                continue
                            
                            volume = opt.get("volume", 0) or 0
                            
                            if volume < min_volume:
                                continue
                            
                            iv = 0.25
                            iv_rank = min(100, iv * 100)
                            
                            if iv_rank < min_iv_rank:
                                continue
                            
                            # Calculate downside protection
                            if strike > underlying_price:
                                protection = (premium / underlying_price) * 100
                            else:
                                protection = ((strike - underlying_price + premium) / underlying_price * 100)
                            
                            # Calculate score
                            roi_score = min(roi_pct * 15, 40)
                            iv_score = min(iv_rank / 100 * 20, 20)
                            delta_score = max(0, 20 - abs(estimated_delta - 0.3) * 50)
                            protection_score = min(abs(protection), 10) * 2
                            
                            score = round(roi_score + iv_score + delta_score + protection_score, 1)
                            
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
                                "open_interest": 0,
                                "score": score
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
            
            result = {"opportunities": opportunities[:100], "total": len(opportunities), "is_live": True, "from_cache": False}
            await funcs['set_cached_data'](cache_key, result)
            return result
            
        except Exception as e:
            logging.error(f"Screener error with Polygon.io: {e}")
    
    # Fallback to mock data
    opportunities = funcs['generate_mock_covered_call_opportunities']()
    
    filtered = [
        o for o in opportunities
        if o["roi_pct"] >= min_roi
        and o["dte"] <= max_dte
        and min_delta <= o["delta"] <= max_delta
        and o["iv_rank"] >= min_iv_rank
        and min_price <= o["stock_price"] <= max_price
        and o["volume"] >= min_volume
    ]
    
    if weekly_only:
        filtered = [o for o in filtered if o["dte"] <= 7]
    elif monthly_only:
        filtered = [o for o in filtered if o["dte"] > 7]
    
    best_by_symbol = {}
    for opp in filtered:
        sym = opp["symbol"]
        if sym not in best_by_symbol or opp["score"] > best_by_symbol[sym]["score"]:
            best_by_symbol[sym] = opp
    
    filtered = sorted(best_by_symbol.values(), key=lambda x: x["score"], reverse=True)
    
    return {"opportunities": filtered, "total": len(filtered), "is_mock": True}



@screener_router.get("/dashboard-opportunities")
async def get_dashboard_opportunities(user: dict = Depends(get_current_user)):
    """Get top 10 covered call opportunities for dashboard with advanced filters"""
    funcs = _get_server_functions()
    
    cache_key = "dashboard_opportunities_v2"
    
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
            "PLTR", "SOFI", "HOOD", "RIVN", "LCID", "NIO",
            "AAPL", "AMD", "DELL", "IBM", "ORCL"
        ]
        
        opportunities = []
        
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            for symbol in symbols_to_scan[:30]:  # Limit for performance
                try:
                    # Get stock price
                    stock_response = await client.get(
                        f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev",
                        params={"apiKey": api_key}
                    )
                    
                    if stock_response.status_code != 200:
                        continue
                    
                    stock_data = stock_response.json()
                    if not stock_data.get("results"):
                        continue
                    
                    current_price = stock_data["results"][0].get("c", 0)
                    
                    if current_price < 30 or current_price > 90:
                        continue
                    
                    # Get options
                    options_results = await funcs['fetch_options_chain_yahoo'](symbol, "call", 45, min_dte=7, current_price=current_price)
                    
                    if not options_results:
                        continue
                    
                    for opt in options_results:
                        strike = opt.get("strike", 0)
                        dte = opt.get("dte", 0)
                        premium = opt.get("close", 0) or opt.get("vwap", 0)
                        
                        if not premium or premium <= 0:
                            continue
                        
                        # Filter for OTM calls
                        if strike <= current_price:
                            continue
                        
                        strike_pct = ((strike - current_price) / current_price) * 100
                        if strike_pct > 10:  # Max 10% OTM
                            continue
                        
                        roi_pct = (premium / current_price) * 100
                        
                        # ROI filters
                        if dte <= 7 and roi_pct < 0.8:
                            continue
                        if dte > 7 and roi_pct < 2.5:
                            continue
                        
                        annualized_roi = (roi_pct / max(dte, 1)) * 365
                        
                        opportunities.append({
                            "symbol": symbol,
                            "stock_price": round(current_price, 2),
                            "strike": strike,
                            "expiry": opt.get("expiry", ""),
                            "dte": dte,
                            "premium": round(premium, 2),
                            "roi_pct": round(roi_pct, 2),
                            "annualized_roi": round(annualized_roi, 1),
                            "delta": round(0.3, 2),  # Estimated
                            "score": round(roi_pct * 10 + annualized_roi / 10, 1)
                        })
                        
                except Exception as e:
                    logging.error(f"Dashboard scan error for {symbol}: {e}")
                    continue
        
        # Sort and limit
        opportunities.sort(key=lambda x: x["score"], reverse=True)
        
        # Dedupe by symbol
        best_by_symbol = {}
        for opp in opportunities:
            sym = opp["symbol"]
            if sym not in best_by_symbol or opp["score"] > best_by_symbol[sym]["score"]:
                best_by_symbol[sym] = opp
        
        opportunities = sorted(best_by_symbol.values(), key=lambda x: x["score"], reverse=True)[:10]
        
        result = {"opportunities": opportunities, "total": len(opportunities), "is_live": True}
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
    """Screen for Poor Man's Covered Call (PMCC) opportunities"""
    funcs = _get_server_functions()
    
    cache_params = {
        "min_price": min_price, "max_price": max_price,
        "min_leaps_dte": min_leaps_dte, "max_leaps_dte": max_leaps_dte,
        "min_short_dte": min_short_dte, "max_short_dte": max_short_dte,
        "min_roi": min_roi, "min_annualized_roi": min_annualized_roi
    }
    cache_key = funcs['generate_cache_key']("pmcc_screener", cache_params)
    
    if not bypass_cache:
        cached_data = await funcs['get_cached_data'](cache_key)
        if cached_data:
            cached_data["from_cache"] = True
            return cached_data
    
    api_key = await funcs['get_massive_api_key']()
    
    if not api_key:
        return {"opportunities": [], "total": 0, "message": "API key required for PMCC screening", "is_mock": True}
    
    try:
        symbols_to_scan = [
            "INTC", "AMD", "MU", "QCOM",
            "BAC", "WFC", "C", "USB",
            "KO", "PEP", "NKE",
            "PFE", "MRK",
            "OXY", "DVN",
            "PYPL", "UBER", "SNAP",
            "AAL", "DAL",
            "PLTR", "SOFI"
        ]
        
        opportunities = []
        
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            for symbol in symbols_to_scan:
                try:
                    # Get stock price
                    stock_response = await client.get(
                        f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev",
                        params={"apiKey": api_key}
                    )
                    
                    if stock_response.status_code != 200:
                        continue
                    
                    stock_data = stock_response.json()
                    if not stock_data.get("results"):
                        continue
                    
                    current_price = stock_data["results"][0].get("c", 0)
                    
                    if current_price < min_price or current_price > max_price:
                        continue
                    
                    # Get LEAPS options (long leg)
                    leaps_options = await funcs['fetch_options_chain_yahoo'](
                        symbol, "call", max_leaps_dte, min_dte=min_leaps_dte, current_price=current_price
                    )
                    
                    # Get short-term options (short leg)
                    short_options = await funcs['fetch_options_chain_yahoo'](
                        symbol, "call", max_short_dte, min_dte=min_short_dte, current_price=current_price
                    )
                    
                    if not leaps_options or not short_options:
                        continue
                    
                    # Filter LEAPS for deep ITM (high delta)
                    filtered_leaps = []
                    for opt in leaps_options:
                        strike = opt.get("strike", 0)
                        if strike < current_price * 0.85:  # Deep ITM
                            estimated_delta = min(0.90, 0.70 + (current_price - strike) / current_price * 0.5)
                            if min_leaps_delta <= estimated_delta <= max_leaps_delta:
                                opt["delta"] = estimated_delta
                                opt["cost"] = (opt.get("close", 0) or opt.get("vwap", 0)) * 100
                                if opt["cost"] > 0:
                                    filtered_leaps.append(opt)
                    
                    # Filter short options for OTM
                    filtered_short = []
                    for opt in short_options:
                        strike = opt.get("strike", 0)
                        if strike > current_price:  # OTM
                            strike_pct = ((strike - current_price) / current_price) * 100
                            estimated_delta = max(0.15, 0.50 - strike_pct * 0.03)
                            if min_short_delta <= estimated_delta <= max_short_delta:
                                opt["delta"] = estimated_delta
                                opt["premium"] = (opt.get("close", 0) or opt.get("vwap", 0)) * 100
                                if opt["premium"] > 0:
                                    filtered_short.append(opt)
                    
                    if filtered_leaps and filtered_short:
                        best_leaps = max(filtered_leaps, key=lambda x: x["delta"])
                        best_short = min(filtered_short, key=lambda x: abs(x["delta"] - 0.25))
                        
                        if best_leaps["cost"] > 0:
                            net_debit = best_leaps["cost"] - best_short["premium"]
                            
                            if net_debit <= 0:
                                continue
                            
                            roi_per_cycle = (best_short["premium"] / best_leaps["cost"]) * 100
                            cycles_per_year = 365 / max(best_short.get("dte", 30), 7)
                            annualized_roi = roi_per_cycle * min(cycles_per_year, 52)
                            
                            if roi_per_cycle < min_roi or annualized_roi < min_annualized_roi:
                                continue
                            
                            score = roi_per_cycle * 10 + annualized_roi / 5
                            
                            opportunities.append({
                                "symbol": symbol,
                                "stock_price": round(current_price, 2),
                                "leaps_strike": best_leaps.get("strike"),
                                "leaps_expiry": best_leaps.get("expiry"),
                                "leaps_dte": best_leaps.get("dte"),
                                "leaps_delta": round(best_leaps["delta"], 2),
                                "leaps_cost": round(best_leaps["cost"], 2),
                                "short_strike": best_short.get("strike"),
                                "short_expiry": best_short.get("expiry"),
                                "short_dte": best_short.get("dte"),
                                "short_delta": round(best_short["delta"], 2),
                                "short_premium": round(best_short["premium"], 2),
                                "net_debit": round(net_debit, 2),
                                "roi_per_cycle": round(roi_per_cycle, 2),
                                "annualized_roi": round(annualized_roi, 1),
                                "score": round(score, 1)
                            })
                    
                except Exception as e:
                    logging.error(f"PMCC scan error for {symbol}: {e}")
                    continue
        
        opportunities.sort(key=lambda x: x["score"], reverse=True)
        
        result = {"opportunities": opportunities, "total": len(opportunities), "is_live": True}
        await funcs['set_cached_data'](cache_key, result)
        return result
        
    except Exception as e:
        logging.error(f"PMCC screener error: {e}")
        return {"opportunities": [], "total": 0, "error": str(e), "is_mock": True}


@screener_router.get("/dashboard-pmcc")
async def get_dashboard_pmcc(user: dict = Depends(get_current_user)):
    """Get top PMCC opportunities for dashboard"""
    funcs = _get_server_functions()
    
    cache_key = "dashboard_pmcc_v2"
    
    cached_data = await funcs['get_cached_data'](cache_key)
    if cached_data:
        cached_data["from_cache"] = True
        return cached_data
    
    # Call the main PMCC screener with default params
    result = await screen_pmcc(user=user)
    
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
        return {"message": f"Cache cleared successfully", "entries_cleared": total_cleared}
    except Exception as e:
        logging.error(f"Error clearing cache: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to clear cache: {str(e)}")


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
