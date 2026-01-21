"""
Screener Routes - Covered Call and PMCC screening endpoints
Designed for scalability with proper caching, async patterns, and efficient data processing

DATA SOURCING STRATEGY (DO NOT CHANGE):
- OPTIONS DATA: Polygon/Massive ONLY (paid subscription)
- STOCK DATA: Polygon/Massive primary, Yahoo fallback (until upgrade)
- All data sourcing is handled by services/data_provider.py

PHASE 2: Chain Validation
- All chains are validated BEFORE strategy logic
- Invalid chains are REJECTED (not scored, not displayed)
- BID-only pricing for SELL legs
- ASK-only pricing for BUY legs (PMCC LEAP)

PHASE 6: Market Bias Order Fix
- Filtering and scoring are SEPARATED
- Market bias is applied AFTER eligibility filtering
- Flow: validate → collect eligible → apply bias → calculate final score → sort
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
# Import centralized data provider
from services.data_provider import (
    fetch_options_chain,
    fetch_stock_quote,
    is_market_closed as data_provider_market_closed
)
# PHASE 2: Import chain validator
from services.chain_validator import (
    get_validator,
    validate_chain_for_cc,
    validate_cc_trade,
    validate_pmcc_trade
)
# PHASE 6: Import market bias module
from services.market_bias import (
    fetch_market_sentiment,
    get_market_bias_weight,
    apply_bias_to_score
)

screener_router = APIRouter(tags=["Screener"])

# HTTP client settings
HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# Thread pool for blocking yfinance calls
_analyst_executor = ThreadPoolExecutor(max_workers=10)

# ETF symbols for special handling
ETF_SYMBOLS = {"SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK", "XLV", "XLI", "XLB", "XLU", "XLP", "XLY", "GLD", "SLV", "ARKK", "ARKG", "ARKW", "TLT", "EEM", "VXX", "UVXY", "SQQQ", "TQQQ"}


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
    enforce_phase4: bool = Query(True),  # PHASE 4: Enable system filters
    user: dict = Depends(get_current_user)
):
    """
    Screen for covered call opportunities with advanced filters.
    
    PHASE 4 RULES (when enforce_phase4=True):
    - System Scan Filters: $30-$90 price, ≥1M avg volume, ≥$5B market cap
    - No earnings within 7 days
    - Single-Candidate Rule: ONE best trade per symbol
    - BID pricing only for SELL legs
    
    DATA SOURCES:
    - Options: Polygon/Massive ONLY
    - Stock prices: Polygon primary, Yahoo fallback
    """
    funcs = _get_server_functions()
    
    # Generate cache key based on all filter parameters
    cache_params = {
        "min_roi": min_roi, "max_dte": max_dte, "min_delta": min_delta, "max_delta": max_delta,
        "min_iv_rank": min_iv_rank, "min_price": min_price, "max_price": max_price,
        "include_stocks": include_stocks, "include_etfs": include_etfs, "include_index": include_index,
        "min_volume": min_volume, "min_open_interest": min_open_interest,
        "weekly_only": weekly_only, "monthly_only": monthly_only,
        "enforce_phase4": enforce_phase4  # PHASE 4
    }
    cache_key = funcs['generate_cache_key']("screener_covered_calls_v3_phase4", cache_params)
    
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
                avg_volume = stock_data.get("avg_volume", 0) or 0
                market_cap = stock_data.get("market_cap", 0) or 0
                earnings_date = stock_data.get("earnings_date")
                
                is_etf = symbol.upper() in ETF_SYMBOLS
                if not is_etf and (underlying_price < min_price or underlying_price > max_price):
                    continue
                
                # PHASE 4: System Scan Filters (when enabled)
                if enforce_phase4 and not is_etf:
                    # Filter: Average volume ≥ 1M
                    if avg_volume > 0 and avg_volume < 1_000_000:
                        logging.debug(f"PHASE4: {symbol} rejected - avg volume {avg_volume:,} < 1M")
                        continue
                    
                    # Filter: Market cap ≥ $5B
                    if market_cap > 0 and market_cap < 5_000_000_000:
                        logging.debug(f"PHASE4: {symbol} rejected - market cap ${market_cap/1e9:.1f}B < $5B")
                        continue
                    
                    # Filter: No earnings within 7 days
                    if earnings_date:
                        try:
                            earnings_dt = datetime.strptime(earnings_date[:10], "%Y-%m-%d")
                            days_to_earnings = (earnings_dt - datetime.now()).days
                            if 0 <= days_to_earnings <= 7:
                                logging.debug(f"PHASE4: {symbol} rejected - earnings in {days_to_earnings} days")
                                continue
                        except:
                            pass
                
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
                    
                    # PHASE 1 FIX: Use BID price for SELL legs (Covered Call)
                    # Fallback chain: bid -> close -> vwap (bid preferred)
                    bid_price = opt.get("bid", 0) or 0
                    close_price = opt.get("close", 0) or opt.get("vwap", 0) or 0
                    
                    # Use BID if available and reasonable, otherwise fallback to close
                    if bid_price > 0:
                        premium = bid_price
                        premium_source = "bid"
                    elif close_price > 0:
                        premium = close_price
                        premium_source = "close"
                    else:
                        continue
                    
                    if premium <= 0:
                        continue
                    
                    # PHASE 2: Validate trade structure BEFORE scoring
                    expiry = opt.get("expiry", "")
                    open_interest = opt.get("open_interest", 0) or 0
                    
                    is_valid, rejection_reason = validate_cc_trade(
                        symbol=symbol,
                        stock_price=underlying_price,
                        strike=strike,
                        expiry=expiry,
                        bid=bid_price,
                        dte=dte,
                        open_interest=open_interest
                    )
                    
                    if not is_valid:
                        logging.debug(f"CC trade rejected: {symbol} ${strike} - {rejection_reason}")
                        continue
                    
                    # DATA QUALITY FILTER: Check for unrealistic premiums
                    # For OTM calls, premium should not exceed intrinsic value + reasonable time value
                    # Rule 1: Max reasonable premium for OTM call: ~10% of underlying price for 30-45 DTE
                    max_reasonable_premium = underlying_price * 0.10
                    if strike > underlying_price and premium > max_reasonable_premium:
                        logging.debug(f"Skipping {symbol} ${strike}C: premium ${premium} exceeds reasonable max ${max_reasonable_premium:.2f}")
                        continue
                    
                    # DATA QUALITY FILTER: Open interest check (when available from Yahoo)
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
                    
                    # ========== PHASE 6: CALCULATE BASE SCORE (before bias) ==========
                    # Calculate base score components
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
                    
                    # Base score (before market bias adjustment)
                    base_score = round(roi_score + iv_score + delta_score + protection_score + liquidity_score, 1)
                    
                    # Add to eligible trades (score will be adjusted after loop)
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
                        "base_score": base_score,  # PHASE 6: Store base score
                        "score": base_score,  # Will be adjusted below
                        "analyst_rating": analyst_rating,
                        "data_source": opt.get("source", "yahoo")
                    })
            except Exception as e:
                logging.error(f"Error scanning {symbol}: {e}")
                continue
        
        # ========== PHASE 6: APPLY MARKET BIAS AFTER FILTERING ==========
        # Fetch market sentiment
        market_sentiment = await fetch_market_sentiment()
        bias_weight = market_sentiment.get("weight_cc", 1.0)
        
        # Apply bias to each eligible trade's score
        for opp in opportunities:
            opp["score"] = apply_bias_to_score(
                opp["base_score"], 
                bias_weight, 
                opp["delta"]
            )
        
        # Sort by final (bias-adjusted) score and dedupe
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
            "phase": 6,  # PHASE 6: Updated phase number
            "market_bias": market_sentiment.get("bias", "neutral"),
            "bias_weight": bias_weight,
            "data_source": "polygon"
        }
        await funcs['set_cached_data'](cache_key, result)
        return result
        
    except Exception as e:
        logging.error(f"Screener error: {e}")
        return {"opportunities": [], "total": 0, "error": str(e), "is_live": False}



@screener_router.get("/dashboard-opportunities")
async def get_dashboard_opportunities(
    bypass_cache: bool = Query(False),
    user: dict = Depends(get_current_user)
):
    """
    Get top 10 covered call opportunities for dashboard.
    
    DASHBOARD RULES:
    - Price filter: $15-$500 (broader range for dashboard)
    - Volume ≥1M, Market Cap ≥$5B, No earnings within 7 days
    - Top 5 Weekly (7-14 DTE) + Top 5 Monthly (21-45 DTE)
    - Weekly gets preference over Monthly
    - Single-Candidate Rule: ONE best trade per symbol per timeframe
    - BID pricing only for SELL legs
    """
    funcs = _get_server_functions()
    
    cache_key = "dashboard_opportunities_v7_weekly_monthly"  # Updated cache key
    
    if not bypass_cache:
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
    
    # DASHBOARD FILTERS (broader than Custom Scan Phase 4 filters)
    DASHBOARD_FILTERS = {
        "min_price": 15,      # $15 min (broader than Custom Scan $30)
        "max_price": 500,     # $500 max (broader than Custom Scan $90)
        "min_avg_volume": 1_000_000,  # 1M
        "min_market_cap": 5_000_000_000,  # $5B
        "earnings_exclusion_days": 7,
        "weekly_dte_min": 7,
        "weekly_dte_max": 14,
        "monthly_dte_min": 21,
        "monthly_dte_max": 45,
        "min_otm_pct": 2,  # Minimum 2% OTM
        "max_otm_pct": 10,  # Maximum 10% OTM
    }
    
    try:
        # Extended symbol list for Dashboard (broader price range $15-$500)
        symbols_to_scan = [
            # Tech - various price ranges
            "INTC", "CSCO", "MU", "QCOM", "TXN", "ADI", "MCHP", "ON", "HPQ", "AMD",
            "AAPL", "MSFT", "NVDA", "META",  # Large tech
            # Financials
            "BAC", "WFC", "C", "USB", "PNC", "TFC", "KEY", "RF", "CFG", "FITB",
            "JPM", "GS",  # Large financials
            # Consumer
            "KO", "PEP", "NKE", "SBUX", "DIS", "GM", "F",
            # Telecom
            "VZ", "T", "TMUS",
            # Healthcare
            "PFE", "MRK", "ABBV", "BMY", "GILD", "JNJ",
            # Energy
            "OXY", "DVN", "APA", "HAL", "SLB", "MRO", "XOM", "CVX",
            # Industrials
            "CAT", "DE", "GE", "HON",
            # Growth/Fintech
            "PYPL", "SQ", "ROKU", "SNAP", "UBER", "LYFT",
            # Travel
            "AAL", "DAL", "UAL", "CCL", "NCLH",
            # High Vol
            "PLTR", "SOFI", "HOOD",
            # Large Tech
            "DELL", "IBM", "ORCL"
        ]
        
        # Track Weekly and Monthly opportunities separately
        weekly_opportunities = []
        monthly_opportunities = []
        rejected_symbols = []
        passed_filter_count = 0
        
        for symbol in symbols_to_scan[:60]:  # Scan up to 60 symbols
            try:
                # Get stock data with fundamentals
                stock_data = await fetch_stock_quote(symbol, api_key)
                
                if not stock_data or stock_data.get("price", 0) == 0:
                    rejected_symbols.append({"symbol": symbol, "reason": "No price data"})
                    continue
                
                current_price = stock_data["price"]
                analyst_rating = stock_data.get("analyst_rating")
                avg_volume = stock_data.get("avg_volume", 0) or 0
                market_cap = stock_data.get("market_cap", 0) or 0
                earnings_date = stock_data.get("earnings_date")
                
                # ========== DASHBOARD FILTERS (BROADER THAN CUSTOM SCAN) ==========
                
                # Filter 1: Price range $15-$500
                if current_price < DASHBOARD_FILTERS["min_price"] or current_price > DASHBOARD_FILTERS["max_price"]:
                    rejected_symbols.append({"symbol": symbol, "reason": f"Price ${current_price:.2f} outside $15-$500"})
                    continue
                
                # Filter 2: Average volume ≥ 1M
                if avg_volume > 0 and avg_volume < DASHBOARD_FILTERS["min_avg_volume"]:
                    rejected_symbols.append({"symbol": symbol, "reason": f"Avg volume {avg_volume:,} < 1M"})
                    continue
                
                # Filter 3: Market cap ≥ $5B
                if market_cap > 0 and market_cap < DASHBOARD_FILTERS["min_market_cap"]:
                    rejected_symbols.append({"symbol": symbol, "reason": f"Market cap ${market_cap/1e9:.1f}B < $5B"})
                    continue
                
                # Filter 4: No earnings within 7 days
                if earnings_date:
                    try:
                        earnings_dt = datetime.strptime(earnings_date[:10], "%Y-%m-%d")
                        days_to_earnings = (earnings_dt - datetime.now()).days
                        if 0 <= days_to_earnings <= DASHBOARD_FILTERS["earnings_exclusion_days"]:
                            rejected_symbols.append({"symbol": symbol, "reason": f"Earnings in {days_to_earnings} days"})
                            continue
                    except:
                        pass
                
                passed_filter_count += 1
                
                # ========== FETCH OPTIONS ==========
                
                # Get Weekly options (7-14 DTE)
                weekly_opts = await fetch_options_chain(
                    symbol, api_key, "call", 
                    DASHBOARD_FILTERS["weekly_dte_max"], 
                    min_dte=DASHBOARD_FILTERS["weekly_dte_min"], 
                    current_price=current_price
                )
                
                # Get Monthly options (21-45 DTE)
                monthly_opts = await fetch_options_chain(
                    symbol, api_key, "call", 
                    DASHBOARD_FILTERS["monthly_dte_max"], 
                    min_dte=DASHBOARD_FILTERS["monthly_dte_min"], 
                    current_price=current_price
                )
                
                # ========== PROCESS OPTIONS ==========
                
                for options_list, timeframe in [(weekly_opts, "Weekly"), (monthly_opts, "Monthly")]:
                    if not options_list:
                        continue
                    
                    for opt in options_list:
                        strike = opt.get("strike", 0)
                        dte = opt.get("dte", 0)
                        expiry = opt.get("expiry", "")
                        open_interest = opt.get("open_interest", 0) or 0
                        
                        # BID-ONLY pricing (Phase 3 rule)
                        bid_price = opt.get("bid", 0) or 0
                        
                        if bid_price <= 0:
                            continue  # REJECT: No bid price
                        
                        premium = bid_price
                        
                        # Validate trade structure (Phase 2)
                        is_valid, rejection_reason = validate_cc_trade(
                            symbol=symbol,
                            stock_price=current_price,
                            strike=strike,
                            expiry=expiry,
                            bid=bid_price,
                            dte=dte,
                            open_interest=open_interest
                        )
                        
                        if not is_valid:
                            continue
                        
                        # OTM filter: Must be 2-10% out of the money
                        if strike <= current_price:
                            continue  # ITM - skip
                        
                        strike_pct = ((strike - current_price) / current_price) * 100
                        
                        if strike_pct < DASHBOARD_FILTERS["min_otm_pct"] or strike_pct > DASHBOARD_FILTERS["max_otm_pct"]:
                            continue
                        
                        # Premium sanity check
                        max_reasonable_premium = current_price * 0.10
                        if premium > max_reasonable_premium:
                            continue
                        
                        # Calculate ROI
                        roi_pct = (premium / current_price) * 100
                        
                        # ROI minimums
                        if timeframe == "Weekly" and roi_pct < 0.8:
                            continue
                        if timeframe == "Monthly" and roi_pct < 2.5:
                            continue
                        
                        annualized_roi = (roi_pct / max(dte, 1)) * 365
                        
                        # Estimate delta
                        estimated_delta = max(0.15, min(0.50, 0.50 - strike_pct * 0.025))
                        
                        # IV from option data
                        iv = opt.get("implied_volatility", 0)
                        if iv and iv > 0:
                            iv = iv * 100
                        else:
                            iv = 30
                        
                        # PHASE 6: Calculate base score with liquidity bonus
                        base_score = roi_pct * 10 + annualized_roi / 10 + (50 - iv) / 10
                        
                        liquidity_bonus = 0
                        if open_interest >= 1000:
                            liquidity_bonus = 10
                        elif open_interest >= 500:
                            liquidity_bonus = 7
                        elif open_interest >= 100:
                            liquidity_bonus = 5
                        elif open_interest >= 50:
                            liquidity_bonus = 2
                        
                        base_score = round(base_score + liquidity_bonus, 1)
                        
                        opp_data = {
                            "symbol": symbol,
                            "stock_price": round(current_price, 2),
                            "strike": strike,
                            "strike_pct": round(strike_pct, 1),
                            "moneyness": "OTM",
                            "expiry": expiry,
                            "expiry_type": timeframe,
                            "dte": dte,
                            "premium": round(premium, 2),
                            "bid": bid_price,
                            "ask": opt.get("ask", 0),
                            "roi_pct": round(roi_pct, 2),
                            "annualized_roi": round(annualized_roi, 1),
                            "delta": round(estimated_delta, 2),
                            "iv": round(iv, 0),
                            "iv_rank": round(min(100, iv * 1.5), 0),
                            "open_interest": open_interest,
                            "base_score": base_score,  # PHASE 6: Store base score
                            "score": base_score,  # Will be adjusted below
                            "analyst_rating": analyst_rating,
                            "market_cap": market_cap,
                            "avg_volume": avg_volume,
                            "data_source": opt.get("source", "yahoo")
                        }
                        
                        # Add to appropriate list
                        if timeframe == "Weekly":
                            weekly_opportunities.append(opp_data)
                        else:
                            monthly_opportunities.append(opp_data)
                
            except Exception as e:
                logging.error(f"Dashboard scan error for {symbol}: {e}")
                rejected_symbols.append({"symbol": symbol, "reason": str(e)})
                continue
        
        # ========== PHASE 6: APPLY MARKET BIAS AFTER FILTERING ==========
        market_sentiment = await fetch_market_sentiment()
        bias_weight = market_sentiment.get("weight_cc", 1.0)
        
        # Apply bias to all opportunities
        for opp in weekly_opportunities:
            opp["score"] = apply_bias_to_score(opp["base_score"], bias_weight, opp["delta"])
        for opp in monthly_opportunities:
            opp["score"] = apply_bias_to_score(opp["base_score"], bias_weight, opp["delta"])
        
        # ========== TOP 5 WEEKLY + TOP 5 MONTHLY (Weekly Preference) ==========
        
        # Dedupe Weekly: One best per symbol
        weekly_best_by_symbol = {}
        for opp in weekly_opportunities:
            sym = opp["symbol"]
            if sym not in weekly_best_by_symbol or opp["score"] > weekly_best_by_symbol[sym]["score"]:
                weekly_best_by_symbol[sym] = opp
        top_weekly = sorted(weekly_best_by_symbol.values(), key=lambda x: x["score"], reverse=True)[:5]
        
        # Dedupe Monthly: One best per symbol (excluding symbols already in Weekly)
        weekly_symbols = {opp["symbol"] for opp in top_weekly}
        monthly_best_by_symbol = {}
        for opp in monthly_opportunities:
            sym = opp["symbol"]
            if sym in weekly_symbols:
                continue  # Skip if symbol already in Weekly list
            if sym not in monthly_best_by_symbol or opp["score"] > monthly_best_by_symbol[sym]["score"]:
                monthly_best_by_symbol[sym] = opp
        top_monthly = sorted(monthly_best_by_symbol.values(), key=lambda x: x["score"], reverse=True)[:5]
        
        # Combine: Weekly first (priority), then Monthly
        final_opportunities = top_weekly + top_monthly
        
        weekly_count = len(top_weekly)
        monthly_count = len(top_monthly)
        
        result = {
            "opportunities": final_opportunities, 
            "total": len(final_opportunities),
            "weekly_count": weekly_count,
            "monthly_count": monthly_count,
            "symbols_scanned": len(symbols_to_scan[:60]),
            "passed_filters": passed_filter_count,
            "is_live": True,
            "phase": 6,  # PHASE 6
            "market_bias": market_sentiment.get("bias", "neutral"),
            "bias_weight": bias_weight,
            "filters_applied": DASHBOARD_FILTERS,
            "data_source": "yahoo_primary"
        }
        await funcs['set_cached_data'](cache_key, result)
        return result
        
    except Exception as e:
        logging.error(f"Dashboard opportunities error: {e}")
        return {"opportunities": [], "total": 0, "error": str(e), "is_mock": True}


@screener_router.get("/pmcc")
async def screen_pmcc(
    min_price: float = Query(30, ge=0),  # Phase 5: Default $30
    max_price: float = Query(90, ge=0),  # Phase 5: Default $90
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
    enforce_phase5: bool = Query(True),  # Phase 5: Enable system filters
    user: dict = Depends(get_current_user)
):
    """
    Screen for Poor Man's Covered Call (PMCC) opportunities.
    
    PHASE 5 RULES (when enforce_phase5=True - Custom Scan):
    - Price filter: $30-$90 for stocks (ETFs exempt)
    - Volume ≥1M, Market Cap ≥$5B, No earnings within 7 days
    - Single-Candidate Rule: ONE best trade per symbol
    - ASK pricing for BUY legs (LEAPS), BID pricing for SELL legs (short calls)
    
    DATA SOURCES:
    - Options: Polygon/Massive ONLY
    - Stock prices: Polygon primary, Yahoo fallback
    """
    funcs = _get_server_functions()
    
    # PHASE 5: System Scan Filters
    PHASE5_FILTERS = {
        "min_price": 30,
        "max_price": 90,
        "min_avg_volume": 1_000_000,  # 1M
        "min_market_cap": 5_000_000_000,  # $5B
        "earnings_exclusion_days": 7,
    }
    
    cache_params = {
        "min_price": min_price, "max_price": max_price,
        "min_leaps_dte": min_leaps_dte, "max_leaps_dte": max_leaps_dte,
        "min_short_dte": min_short_dte, "max_short_dte": max_short_dte,
        "min_roi": min_roi, "min_annualized_roi": min_annualized_roi,
        "enforce_phase5": enforce_phase5  # Phase 5
    }
    cache_key = funcs['generate_cache_key']("pmcc_screener_v2_phase5", cache_params)
    
    if not bypass_cache:
        cached_data = await funcs['get_cached_data'](cache_key)
        if cached_data:
            cached_data["from_cache"] = True
            return cached_data
    
    api_key = await funcs['get_massive_api_key']()
    
    if not api_key:
        return {"opportunities": [], "total": 0, "message": "API key required for PMCC screening", "is_mock": True}
    
    try:
        # Extended symbol list including ETFs for Phase 5
        symbols_to_scan = [
            # Tech - various price ranges
            "INTC", "AMD", "MU", "QCOM", "CSCO", "HPQ", "DELL", "IBM",
            "AAPL", "MSFT", "NVDA", "META",  # Large tech
            # Financials
            "BAC", "WFC", "C", "USB", "PNC", "KEY", "RF", "CFG",
            "JPM", "GS",  # Large financials
            # Consumer
            "KO", "PEP", "NKE", "SBUX", "DIS", "GM", "F",
            # Healthcare
            "PFE", "MRK", "ABBV", "BMY", "GILD", "JNJ",
            # Energy
            "OXY", "DVN", "APA", "HAL", "SLB", "XOM", "CVX",
            # Growth/Fintech
            "PYPL", "UBER", "SNAP", "SQ", "HOOD", "ROKU",
            # Airlines/Travel
            "AAL", "DAL", "UAL", "CCL", "NCLH",
            # High volatility
            "PLTR", "SOFI", "LYFT",
            # ETFs (exempt from price filter)
            "SPY", "QQQ", "IWM", "XLF", "XLE", "XLK", "XLV", "ARKK", "GLD", "SLV"
        ]
        
        opportunities = []
        rejected_symbols = []
        passed_filter_count = 0
        
        for symbol in symbols_to_scan:
            try:
                # Check if ETF (exempt from price filter in Phase 5)
                is_etf = symbol.upper() in ETF_SYMBOLS
                
                # Get stock data with fundamentals
                stock_data = await fetch_stock_quote(symbol, api_key)
                
                if not stock_data or stock_data.get("price", 0) == 0:
                    rejected_symbols.append({"symbol": symbol, "reason": "No price data"})
                    continue
                
                current_price = stock_data["price"]
                avg_volume = stock_data.get("avg_volume", 0) or 0
                market_cap = stock_data.get("market_cap", 0) or 0
                earnings_date = stock_data.get("earnings_date")
                
                # ========== PHASE 5: SYSTEM SCAN FILTERS ==========
                if enforce_phase5:
                    # Filter 1: Price range $30-$90 (ETFs exempt)
                    if not is_etf:
                        if current_price < PHASE5_FILTERS["min_price"] or current_price > PHASE5_FILTERS["max_price"]:
                            rejected_symbols.append({"symbol": symbol, "reason": f"Price ${current_price:.2f} outside $30-$90"})
                            continue
                    
                    # Filter 2: Average volume ≥ 1M
                    if avg_volume > 0 and avg_volume < PHASE5_FILTERS["min_avg_volume"]:
                        rejected_symbols.append({"symbol": symbol, "reason": f"Avg volume {avg_volume:,} < 1M"})
                        continue
                    
                    # Filter 3: Market cap ≥ $5B (skip for ETFs)
                    if not is_etf and market_cap > 0 and market_cap < PHASE5_FILTERS["min_market_cap"]:
                        rejected_symbols.append({"symbol": symbol, "reason": f"Market cap ${market_cap/1e9:.1f}B < $5B"})
                        continue
                    
                    # Filter 4: No earnings within 7 days (skip for ETFs)
                    if not is_etf and earnings_date:
                        try:
                            earnings_dt = datetime.strptime(earnings_date[:10], "%Y-%m-%d")
                            days_to_earnings = (earnings_dt - datetime.now()).days
                            if 0 <= days_to_earnings <= PHASE5_FILTERS["earnings_exclusion_days"]:
                                rejected_symbols.append({"symbol": symbol, "reason": f"Earnings in {days_to_earnings} days"})
                                continue
                        except:
                            pass
                else:
                    # Non-Phase 5 (Dashboard/Pre-computed): Use user-provided price filters
                    if current_price < min_price or current_price > max_price:
                        continue
                
                passed_filter_count += 1
                
                # Get LEAPS options from Polygon ONLY (long leg)
                leaps_options = await fetch_options_chain(
                    symbol, api_key, "call", max_leaps_dte, min_dte=min_leaps_dte, current_price=current_price
                )
                
                # Get short-term options from Polygon ONLY (short leg)
                short_options = await fetch_options_chain(
                    symbol, api_key, "call", max_short_dte, min_dte=min_short_dte, current_price=current_price
                )
                
                if not leaps_options or not short_options:
                    logging.debug(f"No LEAPS or short options for {symbol}")
                    continue
                
                # Filter LEAPS for deep ITM (high delta)
                filtered_leaps = []
                for opt in leaps_options:
                    strike = opt.get("strike", 0)
                    open_interest = opt.get("open_interest", 0) or 0
                    
                    # PHASE 3: Use ASK price for BUY legs (PMCC LEAP)
                    ask_price = opt.get("ask", 0) or 0
                    close_price = opt.get("close", 0) or opt.get("vwap", 0) or 0
                    
                    if ask_price > 0:
                        premium = ask_price
                    elif close_price > 0:
                        premium = close_price
                    else:
                        continue
                    
                    # DATA QUALITY FILTER: Skip very low OI (relaxed for LEAPS)
                    if open_interest < 5:  # Relaxed from 10 to 5 for LEAPS
                        continue
                    
                    # DATA QUALITY FILTER: Premium sanity check for LEAPS
                    # LEAPS premium should be reasonable (not > stock price + 50% for deep ITM)
                    max_leaps_premium = current_price * 1.5
                    if premium > max_leaps_premium:
                        continue
                    
                    # Deep ITM check: strike at least 10% below current price
                    if strike < current_price * 0.90:  # Relaxed from 0.85 to 0.90
                        # Estimate delta based on moneyness (no actual delta from Yahoo)
                        # For deep ITM calls, delta approaches 1.0 as strike goes deeper
                        moneyness = (current_price - strike) / current_price  # % ITM (0.1 = 10% ITM)
                        # Delta estimation: starts at 0.70 for 10% ITM, approaches 0.95 for 50%+ ITM
                        opt_delta = min(0.95, 0.70 + moneyness * 0.5)  # 10% ITM → 0.75, 50% ITM → 0.95
                        opt_delta = round(opt_delta, 2)
                        
                        if min_leaps_delta <= opt_delta <= max_leaps_delta:
                            opt["delta"] = opt_delta
                            opt["cost"] = premium * 100
                            opt["open_interest"] = open_interest
                            if opt["cost"] > 0:
                                filtered_leaps.append(opt)
                
                # Filter short options for OTM
                filtered_short = []
                for opt in short_options:
                    strike = opt.get("strike", 0)
                    open_interest = opt.get("open_interest", 0) or 0
                    
                    # PHASE 3: Use BID price for SELL legs (PMCC short call)
                    bid_price = opt.get("bid", 0) or 0
                    close_price = opt.get("close", 0) or opt.get("vwap", 0) or 0
                    
                    if bid_price > 0:
                        premium = bid_price
                    elif close_price > 0:
                        premium = close_price
                    else:
                        continue
                    
                    # DATA QUALITY FILTER: Skip very low OI
                    if open_interest < 5:  # Relaxed from 10 to 5
                        continue
                    
                    # DATA QUALITY FILTER: Premium sanity for OTM short calls
                    max_short_premium = current_price * 0.20
                    if premium > max_short_premium:
                        continue
                    
                    if strike > current_price:  # OTM
                        strike_pct = ((strike - current_price) / current_price) * 100
                        
                        # Estimate delta based on moneyness (no actual delta from Yahoo)
                        # OTM calls have delta between 0 and 0.5
                        # At strike_pct = 0% (ATM): delta ≈ 0.50
                        # At strike_pct = 5%: delta ≈ 0.35
                        # At strike_pct = 10%: delta ≈ 0.20
                        opt_delta = max(0.10, 0.50 - strike_pct * 0.03)
                        opt_delta = round(opt_delta, 2)
                        
                        if min_short_delta <= opt_delta <= max_short_delta:
                            opt["delta"] = opt_delta
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
                rejected_symbols.append({"symbol": symbol, "reason": str(e)})
                continue
        
        # ========== SINGLE-CANDIDATE RULE ==========
        # One best trade per symbol (highest score wins)
        best_by_symbol = {}
        for opp in opportunities:
            sym = opp["symbol"]
            if sym not in best_by_symbol or opp["score"] > best_by_symbol[sym]["score"]:
                best_by_symbol[sym] = opp
        
        # Convert back to list and sort by score
        opportunities = sorted(best_by_symbol.values(), key=lambda x: x["score"], reverse=True)[:100]
        
        # Fetch analyst ratings for all symbols
        symbols = [opp["symbol"] for opp in opportunities]
        analyst_ratings = await fetch_analyst_ratings_batch(symbols)
        
        # Add analyst ratings to opportunities
        for opp in opportunities:
            opp["analyst_rating"] = analyst_ratings.get(opp["symbol"])
        
        result = {
            "opportunities": opportunities, 
            "total": len(opportunities), 
            "is_live": True, 
            "phase": 5 if enforce_phase5 else None,
            "passed_filters": passed_filter_count,
            "data_source": "polygon"
        }
        await funcs['set_cached_data'](cache_key, result)
        return result
        
    except Exception as e:
        logging.error(f"PMCC screener error: {e}")
        return {"opportunities": [], "total": 0, "error": str(e), "is_mock": True}


@screener_router.get("/dashboard-pmcc")
async def get_dashboard_pmcc(
    bypass_cache: bool = Query(False),
    user: dict = Depends(get_current_user)
):
    """
    Get top PMCC opportunities for dashboard.
    
    DASHBOARD RULES:
    - Price filter: $15-$500 (broader range for dashboard)
    - Volume ≥1M, Market Cap ≥$5B, No earnings within 7 days
    - Single-Candidate Rule: ONE best trade per symbol
    """
    funcs = _get_server_functions()
    
    cache_key = "dashboard_pmcc_v3_phase5"
    
    if not bypass_cache:
        cached_data = await funcs['get_cached_data'](cache_key)
        if cached_data:
            cached_data["from_cache"] = True
            return cached_data
    
    # Call the main PMCC screener with DASHBOARD filters ($15-$500)
    result = await screen_pmcc(
        min_price=15,      # Dashboard: broader price range
        max_price=500,     # Dashboard: broader price range
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
        bypass_cache=True,
        enforce_phase5=False,  # Dashboard uses broader filters
        user=user
    )
    
    if result.get("opportunities"):
        # Limit to top 10 for dashboard
        result["opportunities"] = result["opportunities"][:10]
        result["total"] = len(result["opportunities"])
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


@screener_router.get("/validation-status")
async def get_validation_status(user: dict = Depends(get_current_user)):
    """
    PHASE 2: Get chain validation status and rejection log.
    
    Shows:
    - Total rejections
    - Rejections grouped by reason
    - Helps diagnose why symbols are excluded
    """
    validator = get_validator()
    
    return {
        "summary": validator.get_rejection_summary(),
        "recent_rejections": validator.get_rejection_log()[-50:],  # Last 50
        "validation_rules": {
            "cc_rules": [
                "Strike must exist exactly",
                "Expiry must exist exactly",
                "BID must be > 0 (SELL leg)",
                "DTE must be 1-60 days",
                "Strike must be ≥ 95% of stock price (not deep ITM)"
            ],
            "pmcc_rules": [
                "LEAP: DTE ≥ 365 days",
                "LEAP: Delta ≥ 0.70",
                "LEAP: OI ≥ 500",
                "LEAP: ASK must exist (BUY leg)",
                "Short: DTE 14-45 days",
                "Short: BID must exist (SELL leg)",
                "Short strike > LEAP breakeven"
            ]
        }
    }


@screener_router.post("/validation-clear")
async def clear_validation_log(user: dict = Depends(get_current_user)):
    """Clear the validation rejection log."""
    validator = get_validator()
    validator.clear_rejection_log()
    return {"message": "Validation log cleared"}


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
