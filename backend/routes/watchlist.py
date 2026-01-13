"""
Watchlist routes - Enhanced with price tracking and opportunities
"""
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime, timezone
from typing import List, Dict, Any
import uuid
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
import httpx

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import db
from models.schemas import WatchlistItemCreate
from utils.auth import get_current_user
from services.data_provider import fetch_stock_quote, fetch_options_chain

watchlist_router = APIRouter(tags=["Watchlist"])

# Thread pool for blocking yfinance calls
_executor = ThreadPoolExecutor(max_workers=5)


def _get_server_functions():
    """Lazy import to avoid circular dependencies"""
    from server import get_massive_api_key, MOCK_STOCKS
    return get_massive_api_key, MOCK_STOCKS


def _fetch_analyst_rating_sync(symbol: str) -> dict:
    """Fetch analyst rating only (blocking call)"""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        info = ticker.info
        
        # Get analyst rating
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
        logging.debug(f"Failed to fetch analyst rating for {symbol}: {e}")
        return {
            "symbol": symbol,
            "analyst_rating": None,
            "num_analysts": 0
        }


async def fetch_analyst_ratings_batch(symbols: List[str]) -> Dict[str, str]:
    """Fetch analyst ratings for multiple symbols in parallel"""
    if not symbols:
        return {}
    
    loop = asyncio.get_event_loop()
    
    tasks = [
        loop.run_in_executor(_executor, _fetch_analyst_rating_sync, symbol)
        for symbol in set(symbols)
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    ratings = {}
    for result in results:
        if isinstance(result, dict) and result.get("symbol"):
            ratings[result["symbol"]] = result.get("analyst_rating")
    
    return ratings


async def fetch_stock_prices_polygon(symbols: List[str], api_key: str) -> Dict[str, dict]:
    """Fetch stock prices from Polygon API"""
    if not symbols or not api_key:
        return {}
    
    prices = {}
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Use ticker snapshot grouped endpoint for efficiency
        for symbol in symbols:
            try:
                response = await client.get(
                    f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev",
                    params={"apiKey": api_key}
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("results") and len(data["results"]) > 0:
                        result = data["results"][0]
                        close_price = result.get("c", 0)
                        open_price = result.get("o", close_price)
                        change = close_price - open_price if open_price else 0
                        change_pct = (change / open_price * 100) if open_price else 0
                        
                        prices[symbol] = {
                            "current_price": round(close_price, 2),
                            "change": round(change, 2),
                            "change_pct": round(change_pct, 2)
                        }
            except Exception as e:
                logging.debug(f"Error fetching price for {symbol}: {e}")
    
    return prices


async def _get_best_opportunity(symbol: str, api_key: str, underlying_price: float) -> dict:
    """Get the best covered call opportunity for a symbol"""
    try:
        options = await fetch_options_chain(
            symbol, api_key, "call", 45, min_dte=1, current_price=underlying_price
        )
        
        if not options:
            return None
        
        best_opp = None
        best_roi = 0
        
        for opt in options:
            strike = opt.get("strike", 0)
            expiry = opt.get("expiry", "")
            dte = opt.get("dte", 0)
            premium = opt.get("close", 0) or opt.get("vwap", 0)
            
            if premium <= 0 or strike <= 0 or dte < 1:
                continue
            
            # Filter for reasonable strikes (slightly OTM)
            strike_pct = (strike / underlying_price) * 100 if underlying_price > 0 else 0
            if strike_pct < 98 or strike_pct > 110:
                continue
            
            roi_pct = (premium / underlying_price) * 100
            
            if roi_pct > best_roi and roi_pct >= 0.5:  # Min 0.5% ROI
                best_roi = roi_pct
                
                # Estimate delta based on moneyness
                strike_pct_diff = ((strike - underlying_price) / underlying_price) * 100
                if strike_pct_diff <= 0:
                    estimated_delta = 0.55 - (abs(strike_pct_diff) * 0.02)
                else:
                    estimated_delta = 0.50 - (strike_pct_diff * 0.03)
                estimated_delta = max(0.15, min(0.60, estimated_delta))
                
                iv = opt.get("implied_volatility", 0.25)
                
                best_opp = {
                    "strike": strike,
                    "expiry": expiry,
                    "dte": dte,
                    "premium": round(premium, 2),
                    "roi_pct": round(roi_pct, 2),
                    "delta": round(estimated_delta, 3),
                    "iv": round(iv * 100, 1),
                    "volume": opt.get("volume", 0),
                    "open_interest": opt.get("open_interest", 0)
                }
        
        return best_opp
    except Exception as e:
        logging.error(f"Error getting opportunity for {symbol}: {e}")
        return None


@watchlist_router.get("/")
async def get_watchlist(user: dict = Depends(get_current_user)):
    """Get user's watchlist with current prices and opportunities"""
    get_massive_api_key, MOCK_STOCKS = _get_server_functions()
    
    items = await db.watchlist.find({"user_id": user["id"]}, {"_id": 0}).to_list(100)
    
    if not items:
        return []
    
    # Get all symbols
    symbols = [item.get("symbol", "") for item in items if item.get("symbol")]
    
    # Get API key for Polygon
    api_key = await get_massive_api_key()
    
    # Fetch prices from Polygon
    prices = {}
    if api_key:
        prices = await fetch_stock_prices_polygon(symbols, api_key)
    
    # Fetch analyst ratings in parallel
    analyst_ratings = await fetch_analyst_ratings_batch(symbols)
    
    # Enrich items with current prices and opportunities
    enriched_items = []
    for item in items:
        symbol = item.get("symbol", "")
        price_data = prices.get(symbol, {})
        
        current_price = price_data.get("current_price", 0)
        price_when_added = item.get("price_when_added", 0)
        
        # Calculate price movement since added
        if price_when_added and current_price:
            movement = current_price - price_when_added
            movement_pct = (movement / price_when_added) * 100
        else:
            movement = 0
            movement_pct = 0
        
        enriched = {
            **item,
            "current_price": current_price,
            "change": price_data.get("change", 0),
            "change_pct": price_data.get("change_pct", 0),
            "price_when_added": price_when_added,
            "movement": round(movement, 2),
            "movement_pct": round(movement_pct, 2),
            "analyst_rating": analyst_ratings.get(symbol),
            "opportunity": None
        }
        
        # Get best opportunity if API key is available and current price exists
        if api_key and current_price > 0:
            opp = await _get_best_opportunity(symbol, api_key, current_price)
            enriched["opportunity"] = opp
        
        enriched_items.append(enriched)
    
    return enriched_items


@watchlist_router.post("/")
async def add_to_watchlist(item: WatchlistItemCreate, user: dict = Depends(get_current_user)):
    """Add a symbol to user's watchlist with current price"""
    get_massive_api_key, MOCK_STOCKS = _get_server_functions()
    
    symbol = item.symbol.upper()
    
    # Check if already in watchlist
    existing = await db.watchlist.find_one({"user_id": user["id"], "symbol": symbol})
    if existing:
        raise HTTPException(status_code=400, detail="Symbol already in watchlist")
    
    # Get current price from Polygon
    api_key = await get_massive_api_key()
    price_when_added = 0
    
    if api_key:
        prices = await fetch_stock_prices_polygon([symbol], api_key)
        price_when_added = prices.get(symbol, {}).get("current_price", 0)
    
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "symbol": symbol,
        "target_price": item.target_price,
        "price_when_added": price_when_added,
        "notes": item.notes,
        "added_at": datetime.now(timezone.utc).isoformat()
    }
    await db.watchlist.insert_one(doc)
    
    return {
        "id": doc["id"],
        "symbol": symbol,
        "price_when_added": price_when_added,
        "message": "Added to watchlist"
    }


@watchlist_router.delete("/{item_id}")
async def remove_from_watchlist(item_id: str, user: dict = Depends(get_current_user)):
    """Remove an item from user's watchlist"""
    result = await db.watchlist.delete_one({"id": item_id, "user_id": user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"message": "Removed from watchlist"}


@watchlist_router.delete("/")
async def clear_watchlist(user: dict = Depends(get_current_user)):
    """Clear all items from user's watchlist"""
    result = await db.watchlist.delete_many({"user_id": user["id"]})
    return {"message": f"Cleared {result.deleted_count} items from watchlist"}


@watchlist_router.put("/{item_id}/notes")
async def update_watchlist_notes(item_id: str, notes: str = "", user: dict = Depends(get_current_user)):
    """Update notes for a watchlist item"""
    result = await db.watchlist.update_one(
        {"id": item_id, "user_id": user["id"]},
        {"$set": {"notes": notes}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"message": "Notes updated"}
