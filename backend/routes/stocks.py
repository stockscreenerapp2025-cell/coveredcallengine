"""
Stocks Routes - Stock data and quote endpoints
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from datetime import datetime, timedelta
import logging
import httpx
import asyncio
import os
from concurrent.futures import ThreadPoolExecutor

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.auth import get_current_user

# Lazy import yfinance to avoid startup slowdown
_yf = None
def get_yfinance():
    global _yf
    if _yf is None:
        import yfinance as yf
        _yf = yf
    return _yf

# Thread pool for yfinance (which is blocking)
_executor = ThreadPoolExecutor(max_workers=5)

stocks_router = APIRouter(tags=["Stocks"])


# Import shared data and functions from server module
def _get_server_data():
    """Lazy import to avoid circular dependencies"""
    from server import MOCK_STOCKS, MOCK_INDICES, get_massive_api_key, get_admin_settings
    return MOCK_STOCKS, MOCK_INDICES, get_massive_api_key, get_admin_settings


@stocks_router.get("/quote/{symbol}")
async def get_stock_quote(symbol: str, user: dict = Depends(get_current_user)):
    """Get stock quote for a symbol"""
    # Use centralized data provider
    from services.data_provider import fetch_stock_quote as fetch_quote_provider
    
    symbol = symbol.upper()
    
    # Fetch from centralized provider (Yahoo primary)
    quote_data = await fetch_quote_provider(symbol)
    
    if quote_data:
        return {
            "symbol": symbol,
            "price": quote_data.get("price", 0),
            "open": quote_data.get("price", 0), # Fallback as we primarily get close
            "high": quote_data.get("price", 0), # Fallback
            "low": quote_data.get("price", 0),  # Fallback
            "volume": quote_data.get("avg_volume", 0),
            "change": 0, # Calculated in frontend or via history
            "change_pct": 0,
            "is_live": True,
            "source": quote_data.get("source", "yahoo")
        }
    
    # Fallback to mock data if provider fails
    MOCK_STOCKS, _, _, _ = _get_server_data()
    if symbol in MOCK_STOCKS:
        data = MOCK_STOCKS[symbol]
        return {
            "symbol": symbol,
            "price": data["price"],
            "change": data["change"],
            "change_pct": data["change_pct"],
            "volume": data["volume"],
            "pe": data["pe"],
            "roe": data["roe"],
            "is_mock": True
        }
    
    raise HTTPException(status_code=404, detail=f"Stock {symbol} not found")


def _fetch_analyst_ratings(symbol: str) -> dict:
    """Fetch analyst ratings from Yahoo Finance (blocking call)"""
    try:
        yf = get_yfinance()
        ticker = yf.Ticker(symbol)
        info = ticker.info
        
        recommendation = info.get("recommendationKey", "")
        num_analysts = info.get("numberOfAnalystOpinions", 0)
        target_mean = info.get("targetMeanPrice")
        target_high = info.get("targetHighPrice")
        target_low = info.get("targetLowPrice")
        current_price = info.get("currentPrice") or info.get("regularMarketPrice")
        
        # Map Yahoo's recommendation keys to display values
        rating_map = {
            "strong_buy": "Strong Buy",
            "buy": "Buy",
            "hold": "Hold",
            "underperform": "Sell",
            "sell": "Sell"
        }
        
        display_rating = rating_map.get(recommendation, recommendation.replace("_", " ").title() if recommendation else "")
        
        # Calculate upside potential
        upside_pct = None
        if target_mean and current_price and current_price > 0:
            upside_pct = round((target_mean - current_price) / current_price * 100, 1)
        
        return {
            "rating": display_rating,
            "num_analysts": num_analysts,
            "target_price": round(target_mean, 2) if target_mean else None,
            "target_high": round(target_high, 2) if target_high else None,
            "target_low": round(target_low, 2) if target_low else None,
            "upside_pct": upside_pct,
            "has_sufficient_coverage": num_analysts >= 5
        }
    except Exception as e:
        logging.error(f"yfinance analyst ratings error for {symbol}: {e}")
        return {}


@stocks_router.get("/indices")
async def get_market_indices(user: dict = Depends(get_current_user)):
    """
    Get LIVE market indices data from Yahoo Finance.
    
    Returns latest available data, even after hours or on weekends.
    Uses Yahoo Finance history() to get the most recent close prices.
    """
    yf = get_yfinance()
    
    # Index ETFs to track (these trade and have historical data)
    index_symbols = {
        "^GSPC": {"name": "S&P 500", "etf": "SPY"},
        "^IXIC": {"name": "NASDAQ Composite", "etf": "QQQ"},
        "^DJI": {"name": "Dow Jones", "etf": "DIA"},
        "^RUT": {"name": "Russell 2000", "etf": "IWM"},
        "^VIX": {"name": "Volatility Index", "etf": None}
    }
    
    results = {}
    
    for symbol, info in index_symbols.items():
        try:
            # Use ETF if available (more reliable data), otherwise use index directly
            ticker_symbol = info.get("etf") or symbol
            ticker = yf.Ticker(ticker_symbol)
            
            # Get last 5 days of history
            hist = ticker.history(period='5d')
            
            if hist.empty:
                continue
            
            # Get latest close and previous close
            latest_close = hist['Close'].iloc[-1]
            previous_close = hist['Close'].iloc[-2] if len(hist) > 1 else latest_close
            close_date = hist.index[-1].strftime('%Y-%m-%d')
            
            change = latest_close - previous_close
            change_pct = (change / previous_close * 100) if previous_close else 0
            
            display_symbol = info.get("etf") or symbol.replace("^", "")
            
            results[display_symbol] = {
                "name": info["name"],
                "symbol": display_symbol,
                "price": round(float(latest_close), 2),
                "change": round(float(change), 2),
                "change_pct": round(float(change_pct), 2),
                "close_date": close_date,
                "source": "yahoo_finance"
            }
        except Exception as e:
            logging.warning(f"Could not fetch index data for {symbol}: {e}")
    
    # Fallback to mock data if no live data available
    if not results:
        _, MOCK_INDICES, _, _ = _get_server_data()
        return MOCK_INDICES
    
    return results


@stocks_router.get("/details/{symbol}")
async def get_stock_details(symbol: str, user: dict = Depends(get_current_user)):
    """Get comprehensive stock details including news, fundamentals, and ratings"""
    _, _, _, get_admin_settings = _get_server_data()
    
    # Import centralized data providers
    from services.data_provider import (
        fetch_stock_quote, 
        fetch_fundamental_data,
        fetch_technical_data
    )
    
    symbol = symbol.upper()
    
    # Initialize result structure
    result = {
        "symbol": symbol,
        "price": 0,
        "change": 0,
        "change_pct": 0,
        "news": [],
        "fundamentals": {},
        "analyst_ratings": {},
        "technicals": {},
        "is_live": False
    }
    
    try:
        # 1. Fetch Price Data (Yahoo)
        quote_data = await fetch_stock_quote(symbol)
        if quote_data:
            result["price"] = quote_data.get("price", 0)
            result["is_live"] = True
            
            # Use data from quote if available
            if quote_data.get("analyst_rating"):
                result["analyst_ratings"]["rating"] = quote_data["analyst_rating"]
        
        # 2. Fetch Fundamental Data (Yahoo)
        fund_data = await fetch_fundamental_data(symbol)
        if fund_data:
            result["fundamentals"] = fund_data
        
        # 3. Fetch Technical Data (Yahoo)
        tech_data = await fetch_technical_data(symbol)
        if tech_data:
            # Determine trend based on SMAs
            sma50 = tech_data.get("sma50")
            sma200 = tech_data.get("sma200")
            current = tech_data.get("close", 0)
            
            trend = "neutral"
            if sma50 and sma200:
                if current > sma50 > sma200:
                    trend = "bullish"
                elif current < sma50 < sma200:
                    trend = "bearish"
            
            result["technicals"] = {
                "sma_50": round(sma50, 2) if sma50 else None,
                "sma_200": round(sma200, 2) if sma200 else None,
                "rsi": round(tech_data.get("rsi14"), 1) if tech_data.get("rsi14") else None,
                "trend": trend,
                "above_sma_50": current > sma50 if sma50 else False,
                "above_sma_200": current > sma200 if sma200 else False,
                "sma_50_above_200": sma50 > sma200 if sma50 and sma200 else False
            }

    except Exception as e:
        logging.error(f"Stock details fetch error for {symbol}: {e}")
    
    # Get MarketAux news as supplement
    settings = await get_admin_settings()
    if settings.marketaux_api_token and "..." not in settings.marketaux_api_token and len(result["news"]) < 5:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    "https://api.marketaux.com/v1/news/all",
                    params={
                        "api_token": settings.marketaux_api_token,
                        "symbols": symbol,
                        "filter_entities": "true",
                        "limit": 5
                    }
                )
                if response.status_code == 200:
                    data = response.json()
                    for article in data.get("data", []):
                        if len(result["news"]) < 8:
                            result["news"].append({
                                "title": article.get("title", ""),
                                "description": article.get("description", ""),
                                "published": article.get("published_at", ""),
                                "source": article.get("source", ""),
                                "url": article.get("url", ""),
                                "sentiment": article.get("sentiment", 0)
                            })
        except Exception as e:
            logging.error(f"MarketAux news error: {e}")
    
    # Wait for analyst ratings from yfinance
    try:
        analyst_data = await analyst_task
        result["analyst_ratings"] = analyst_data
    except Exception as e:
        logging.error(f"Analyst ratings error: {e}")
    
    return result


@stocks_router.get("/historical/{symbol}")
async def get_historical_data(
    symbol: str,
    timespan: str = Query("day", enum=["minute", "hour", "day", "week", "month"]),
    days: int = Query(30, ge=1, le=365),
    user: dict = Depends(get_current_user)
):
    """Get historical stock data"""
    MOCK_STOCKS, _, _, _ = _get_server_data()
    
    symbol = symbol.upper()
    
    # Generate mock historical data
    data = []
    base_price = MOCK_STOCKS.get(symbol, {}).get("price", 100)
    
    for i in range(days, 0, -1):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        variation = (hash(f"{symbol}{date}") % 1000 - 500) / 10000
        price = base_price * (1 + variation * i / days)
        
        data.append({
            "date": date,
            "open": round(price * 0.998, 2),
            "high": round(price * 1.02, 2),
            "low": round(price * 0.98, 2),
            "close": round(price, 2),
            "volume": 1000000 + hash(f"{symbol}{date}") % 5000000
        })
    
    return data
