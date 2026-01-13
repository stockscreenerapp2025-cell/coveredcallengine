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
    MOCK_STOCKS, _, get_massive_api_key, _ = _get_server_data()
    
    symbol = symbol.upper()
    
    # Try Massive.com API first
    api_key = await get_massive_api_key()
    if api_key:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Massive.com uses apiKey as query parameter (similar to Polygon)
                # Get previous day aggregates for price data
                response = await client.get(
                    f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev",
                    params={"apiKey": api_key}
                )
                logging.info(f"Stock quote API response for {symbol}: status={response.status_code}")
                if response.status_code == 200:
                    data = response.json()
                    if data.get("results") and len(data["results"]) > 0:
                        result = data["results"][0]
                        return {
                            "symbol": symbol,
                            "price": result.get("c"),  # close price
                            "open": result.get("o"),
                            "high": result.get("h"),
                            "low": result.get("l"),
                            "volume": result.get("v"),
                            "change": round(result.get("c", 0) - result.get("o", 0), 2),
                            "change_pct": round((result.get("c", 0) - result.get("o", 0)) / result.get("o", 1) * 100, 2) if result.get("o") else 0,
                            "is_live": True
                        }
                
                # Fallback: try last trade endpoint
                response = await client.get(
                    f"https://api.polygon.io/v2/last/trade/{symbol}",
                    params={"apiKey": api_key}
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("results"):
                        result = data["results"]
                        return {
                            "symbol": symbol,
                            "price": result.get("p"),  # price
                            "volume": result.get("s"),  # size
                            "is_live": True
                        }
        except Exception as e:
            logging.error(f"Massive.com API error: {e}")
    
    # Fallback to mock data
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
    """Get market indices data"""
    _, MOCK_INDICES, _, _ = _get_server_data()
    return MOCK_INDICES


@stocks_router.get("/details/{symbol}")
async def get_stock_details(symbol: str, user: dict = Depends(get_current_user)):
    """Get comprehensive stock details including news, fundamentals, and ratings"""
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
    
    if api_key:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Get current price
                price_response = await client.get(
                    f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev",
                    params={"apiKey": api_key}
                )
                if price_response.status_code == 200:
                    price_data = price_response.json()
                    if price_data.get("results"):
                        r = price_data["results"][0]
                        result["price"] = r.get("c", 0)
                        result["open"] = r.get("o", 0)
                        result["high"] = r.get("h", 0)
                        result["low"] = r.get("l", 0)
                        result["volume"] = r.get("v", 0)
                        result["change"] = round(r.get("c", 0) - r.get("o", 0), 2)
                        result["change_pct"] = round((r.get("c", 0) - r.get("o", 0)) / r.get("o", 1) * 100, 2) if r.get("o") else 0
                        result["is_live"] = True
                
                # Get ticker details/fundamentals
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
                
                # Get news from Massive.com
                news_response = await client.get(
                    f"https://api.polygon.io/v2/reference/news",
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
            logging.error(f"Stock details error for {symbol}: {e}")
    
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
