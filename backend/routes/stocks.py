"""
Stocks Routes - Stock data and quote endpoints

PHASE 1 REFACTOR (December 2025):
- All stock quotes now route through services/data_provider.py
- Yahoo Finance is primary source, Polygon is backup (via data_provider)
- MOCK_STOCKS retained for fallback but flagged
- Mock fallback blocked in production (ENVIRONMENT check)
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
from utils.environment import allow_mock_data, check_mock_fallback, DataUnavailableError
from services.data_provider import fetch_stock_quote, fetch_live_stock_quote

# Lazy import yfinance to avoid startup slowdown (retained for analyst ratings)
_yf = None
def get_yfinance():
    global _yf
    if _yf is None:
        import yfinance as yf
        _yf = yf
    return _yf

# Thread pool for yfinance (which is blocking) - retained for analyst ratings
_executor = ThreadPoolExecutor(max_workers=5)

stocks_router = APIRouter(tags=["Stocks"])


# Import shared data and functions from server module
def _get_server_data():
    """Lazy import to avoid circular dependencies"""
    from server import MOCK_STOCKS, MOCK_INDICES, get_massive_api_key, get_admin_settings
    return MOCK_STOCKS, MOCK_INDICES, get_massive_api_key, get_admin_settings


@stocks_router.get("/quote/{symbol}")
async def get_stock_quote(symbol: str, user: dict = Depends(get_current_user)):
    """
    Get stock quote for a symbol.
    
    PHASE 1 REFACTOR: Now routes through data_provider.py
    - Primary: Yahoo Finance (via data_provider.fetch_stock_quote)
    - Backup: Polygon (via data_provider fallback)
    - Last Resort: MOCK_STOCKS (only in dev/test, blocked in production)
    """
    MOCK_STOCKS, _, get_massive_api_key, _ = _get_server_data()
    
    symbol = symbol.upper()
    
    # Get API key for potential Polygon fallback
    api_key = await get_massive_api_key()
    
    # Route through centralized data_provider (Yahoo primary, Polygon backup)
    try:
        result = await fetch_stock_quote(symbol, api_key)
        
        if result and result.get("price", 0) > 0:
            return {
                "symbol": symbol,
                "price": result.get("price"),
                "previous_close": result.get("previous_close"),
                "change": result.get("change", 0),
                "change_pct": result.get("change_pct", 0),
                "close_date": result.get("close_date"),
                "source": result.get("source", "yahoo"),
                "is_live": True
            }
    except Exception as e:
        logging.error(f"data_provider fetch_stock_quote error for {symbol}: {e}")
    
    # Check if mock fallback is allowed (raises in production)
    try:
        if symbol in MOCK_STOCKS and allow_mock_data():
            check_mock_fallback(
                symbol=symbol,
                reason="YAHOO_AND_POLYGON_UNAVAILABLE",
                details="Primary and backup data providers failed"
            )
            data = MOCK_STOCKS[symbol]
            logging.warning(f"Using MOCK_STOCKS fallback for {symbol}")
            return {
                "symbol": symbol,
                "price": data["price"],
                "change": data["change"],
                "change_pct": data["change_pct"],
                "volume": data["volume"],
                "pe": data["pe"],
                "roe": data["roe"],
                "is_mock": True  # FLAG: Mock data in use
            }
    except DataUnavailableError as e:
        # Production: return structured unavailability response
        raise HTTPException(
            status_code=503,
            detail=e.to_dict()
        )
    
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
    """
    Get comprehensive stock details including news, fundamentals, and ratings.
    
    PHASE 1 REFACTOR: Stock price now routes through data_provider.py
    - Primary: Yahoo Finance (via data_provider.fetch_stock_quote)
    - News/Fundamentals: Still uses Polygon (supplementary data, not core price)
    - Analyst ratings: Yahoo Finance direct (already was)
    """
    _, _, get_massive_api_key, get_admin_settings = _get_server_data()
    
    symbol = symbol.upper()
    api_key = await get_massive_api_key()
    
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
    
    # Fetch analyst ratings from yfinance in parallel
    loop = asyncio.get_event_loop()
    analyst_task = loop.run_in_executor(_executor, _fetch_analyst_ratings, symbol)
    
    # PHASE 1: Get stock price from data_provider (Yahoo primary)
    try:
        stock_data = await fetch_stock_quote(symbol, api_key)
        if stock_data and stock_data.get("price", 0) > 0:
            result["price"] = stock_data.get("price", 0)
            result["previous_close"] = stock_data.get("previous_close", 0)
            result["close_date"] = stock_data.get("close_date")
            result["is_live"] = True
            result["price_source"] = stock_data.get("source", "yahoo")
            
            # Calculate change from previous close if available
            prev = stock_data.get("previous_close", 0)
            if prev and prev > 0:
                result["change"] = round(stock_data.get("price", 0) - prev, 2)
                result["change_pct"] = round((result["change"] / prev) * 100, 2)
    except Exception as e:
        logging.error(f"data_provider stock quote error for {symbol}: {e}")
    
    # Supplementary data from Polygon (news, fundamentals, technicals)
    # NOTE: This is NOT core price data - kept as supplementary enrichment
    if api_key:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Get ticker details/fundamentals from Polygon
                ticker_response = await client.get(
                    f"https://api.polygon.io/v3/reference/tickers/{symbol}",
                    params={"apiKey": api_key}
                )
                if ticker_response.status_code == 200:
                    ticker_data = ticker_response.json()
                    details = ticker_data.get("results", {})
                    result["fundamentals"] = {
                        "name": details.get("name", symbol),
                        "market_cap": details.get("market_cap"),
                        "description": details.get("description", ""),
                        "homepage": details.get("homepage_url", ""),
                        "employees": details.get("total_employees"),
                        "list_date": details.get("list_date"),
                        "sic_description": details.get("sic_description", ""),
                        "locale": details.get("locale", "us"),
                        "primary_exchange": details.get("primary_exchange", "")
                    }
                
                # Get news from Polygon
                news_response = await client.get(
                    "https://api.polygon.io/v2/reference/news",
                    params={"apiKey": api_key, "ticker": symbol, "limit": 5}
                )
                if news_response.status_code == 200:
                    news_data = news_response.json()
                    for article in news_data.get("results", [])[:5]:
                        result["news"].append({
                            "title": article.get("title", ""),
                            "description": article.get("description", ""),
                            "published": article.get("published_utc", ""),
                            "source": article.get("publisher", {}).get("name", ""),
                            "url": article.get("article_url", ""),
                            "image": article.get("image_url", "")
                        })
                
                # Calculate technical indicators from historical data
                end_date = datetime.now().strftime("%Y-%m-%d")
                start_date = (datetime.now() - timedelta(days=250)).strftime("%Y-%m-%d")
                
                hist_response = await client.get(
                    f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/day/{start_date}/{end_date}",
                    params={"apiKey": api_key, "adjusted": "true", "sort": "desc", "limit": 250}
                )
                
                if hist_response.status_code == 200:
                    hist_data = hist_response.json()
                    bars = hist_data.get("results", [])
                    
                    if len(bars) >= 50:
                        closes = [b.get("c", 0) for b in bars]
                        
                        # SMA 50 and SMA 200
                        sma_50 = sum(closes[:50]) / 50
                        sma_200 = sum(closes[:200]) / 200 if len(closes) >= 200 else sum(closes) / len(closes)
                        
                        current = closes[0] if closes else 0
                        
                        # Simple RSI calculation (14 period)
                        gains = []
                        losses = []
                        for i in range(min(14, len(closes) - 1)):
                            change = closes[i] - closes[i + 1]
                            if change > 0:
                                gains.append(change)
                                losses.append(0)
                            else:
                                gains.append(0)
                                losses.append(abs(change))
                        
                        avg_gain = sum(gains) / 14 if gains else 0
                        avg_loss = sum(losses) / 14 if losses else 0.001
                        rs = avg_gain / avg_loss if avg_loss > 0 else 100
                        rsi = 100 - (100 / (1 + rs))
                        
                        # Trend analysis
                        trend = "bullish" if current > sma_50 > sma_200 else "bearish" if current < sma_50 < sma_200 else "neutral"
                        
                        result["technicals"] = {
                            "sma_50": round(sma_50, 2),
                            "sma_200": round(sma_200, 2),
                            "rsi": round(rsi, 1),
                            "trend": trend,
                            "above_sma_50": current > sma_50,
                            "above_sma_200": current > sma_200,
                            "sma_50_above_200": sma_50 > sma_200
                        }
                
        except Exception as e:
            logging.error(f"Stock details supplementary data error for {symbol}: {e}")
    
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
