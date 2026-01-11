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


