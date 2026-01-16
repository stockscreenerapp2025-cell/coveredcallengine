"""
Watchlist routes - Enhanced with price tracking and opportunities
Uses unified data provider (Yahoo primary, Polygon backup)
"""
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime, timezone
from typing import List, Dict, Any
import uuid
import logging
import asyncio

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import db
from models.schemas import WatchlistItemCreate
from utils.auth import get_current_user
from services.data_provider import fetch_stock_quote, fetch_options_chain, fetch_stock_quotes_batch

watchlist_router = APIRouter(tags=["Watchlist"])


def _get_server_functions():
    """Lazy import to avoid circular dependencies"""
    from server import get_massive_api_key, MOCK_STOCKS
    return get_massive_api_key, MOCK_STOCKS


async def _get_best_opportunity(symbol: str, api_key: str, underlying_price: float) -> dict:
    """Get the best covered call opportunity for a symbol using unified data provider"""
    try:
        # Fetch options chain (Yahoo primary with IV/OI, Polygon backup)
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
            premium = opt.get("close", 0)
            open_interest = opt.get("open_interest", 0) or 0
            iv = opt.get("implied_volatility", 0) or 0
            
            if premium <= 0 or strike <= 0 or dte < 1:
                continue
            
            # Filter for reasonable strikes (slightly OTM)
            strike_pct = (strike / underlying_price) * 100 if underlying_price > 0 else 0
            if strike_pct < 98 or strike_pct > 110:
                continue
            
            # DATA QUALITY FILTER: Premium sanity check (10% max for OTM)
            if strike > underlying_price:
                max_reasonable_premium = underlying_price * 0.10
                if premium > max_reasonable_premium:
                    continue
            
            roi_pct = (premium / underlying_price) * 100
            
            # DATA QUALITY FILTER: ROI sanity check (20% max for OTM)
            if strike > underlying_price and roi_pct > 20:
                continue
            
            # If we have OI data, prefer liquid options
            if open_interest > 0 and open_interest < 10:
                continue
            
            if roi_pct > best_roi and roi_pct >= 0.5:
                best_roi = roi_pct
                
                # Estimate delta based on moneyness
                strike_pct_diff = ((strike - underlying_price) / underlying_price) * 100
                if strike_pct_diff <= 0:
                    estimated_delta = 0.55 - (abs(strike_pct_diff) * 0.02)
                else:
                    estimated_delta = 0.50 - (strike_pct_diff * 0.03)
                estimated_delta = max(0.15, min(0.60, estimated_delta))
                
                # Use IV from Yahoo if available, else estimate
                if iv == 0:
                    iv = 0.30  # 30% default
                
                # Determine type: Weekly (<=7 DTE) or Monthly
                option_type = "Weekly" if dte <= 7 else "Monthly"
                
                # Calculate AI Score with liquidity bonus
                roi_score = min(roi_pct * 15, 40)
                iv_score = min(iv * 20, 20)
                delta_score = max(0, 20 - abs(estimated_delta - 0.3) * 50)
                protection = (premium / underlying_price) * 100 if strike > underlying_price else ((strike - underlying_price + premium) / underlying_price * 100)
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
                
                ai_score = round(roi_score + iv_score + delta_score + protection_score + liquidity_score, 1)
                
                # Calculate IV Rank (simplified: IV as percentage of typical range 20-80%)
                iv_rank = min(100, max(0, (iv - 0.20) / 0.60 * 100)) if iv > 0 else 0
                
                best_opp = {
                    "strike": strike,
                    "expiry": expiry,
                    "dte": dte,
                    "premium": round(premium, 2),
                    "roi_pct": round(roi_pct, 2),
                    "delta": round(estimated_delta, 3),
                    "iv": round(iv * 100, 1),
                    "iv_rank": round(iv_rank, 0),
                    "volume": opt.get("volume", 0),
                    "open_interest": open_interest,
                    "type": option_type,
                    "ai_score": ai_score,
                    "days_to_earnings": opt.get("days_to_earnings"),
                    "source": opt.get("source", "yahoo")
                }
        
        return best_opp
    except Exception as e:
        logging.error(f"Error getting opportunity for {symbol}: {e}")
        return None


@watchlist_router.get("/")
async def get_watchlist(user: dict = Depends(get_current_user)):
    """Get user's watchlist with current prices and opportunities"""
    get_massive_api_key, _ = _get_server_functions()
    
    items = await db.watchlist.find({"user_id": user["id"]}, {"_id": 0}).to_list(100)
    
    if not items:
        return []
    
    # Get all symbols
    symbols = [item.get("symbol", "") for item in items if item.get("symbol")]
    
    # Get API key
    api_key = await get_massive_api_key()
    
    # Fetch stock quotes in batch (Yahoo primary)
    stock_data = await fetch_stock_quotes_batch(symbols, api_key)
    
    # Enrich items with current prices and opportunities
    enriched_items = []
    for item in items:
        symbol = item.get("symbol", "")
        data = stock_data.get(symbol, {})
        
        current_price = data.get("price", 0)
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
            "change": data.get("change", 0),
            "change_pct": data.get("change_pct", 0),
            "price_when_added": price_when_added,
            "movement": round(movement, 2),
            "movement_pct": round(movement_pct, 2),
            # Use live analyst_rating if available, otherwise use stored value at add time
            "analyst_rating": data.get("analyst_rating") or item.get("analyst_rating_at_add"),
            "days_to_earnings": data.get("days_to_earnings") if data.get("days_to_earnings") is not None else item.get("days_to_earnings_at_add"),
            "earnings_date": data.get("earnings_date") or item.get("earnings_date_at_add"),
            "opportunity": None
        }
        
        # Get best opportunity if current price exists
        if current_price > 0:
            opp = await _get_best_opportunity(symbol, api_key, current_price)
            enriched["opportunity"] = opp
        
        enriched_items.append(enriched)
    
    return enriched_items


@watchlist_router.post("/")
async def add_to_watchlist(item: WatchlistItemCreate, user: dict = Depends(get_current_user)):
    """Add a symbol to user's watchlist with current price and analyst data"""
    get_massive_api_key, _ = _get_server_functions()
    
    symbol = item.symbol.upper()
    
    # Check if already in watchlist
    existing = await db.watchlist.find_one({"user_id": user["id"], "symbol": symbol})
    if existing:
        raise HTTPException(status_code=400, detail="Symbol already in watchlist")
    
    # Get current price and analyst data (Yahoo primary)
    api_key = await get_massive_api_key()
    stock_data = await fetch_stock_quote(symbol, api_key)
    
    price_when_added = stock_data.get("price", 0) if stock_data else 0
    analyst_rating = stock_data.get("analyst_rating") if stock_data else None
    days_to_earnings = stock_data.get("days_to_earnings") if stock_data else None
    earnings_date = stock_data.get("earnings_date") if stock_data else None
    
    # If analyst data is missing, try a direct yfinance call
    if not analyst_rating or days_to_earnings is None:
        try:
            import yfinance as yf
            from datetime import datetime as dt
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            # Get analyst rating if missing
            if not analyst_rating:
                recommendation = info.get("recommendationKey", "")
                rating_map = {
                    "strong_buy": "Strong Buy",
                    "buy": "Buy", 
                    "hold": "Hold",
                    "underperform": "Sell",
                    "sell": "Sell"
                }
                analyst_rating = rating_map.get(recommendation, recommendation.replace("_", " ").title() if recommendation else None)
            
            # Get earnings date if missing
            if days_to_earnings is None:
                try:
                    calendar = ticker.calendar
                    if calendar is not None and 'Earnings Date' in calendar:
                        earnings_dates = calendar['Earnings Date']
                        if len(earnings_dates) > 0:
                            next_earnings = earnings_dates[0]
                            if hasattr(next_earnings, 'date'):
                                earnings_date = next_earnings.date().isoformat()
                            else:
                                earnings_date = str(next_earnings)[:10]
                            if earnings_date:
                                earnings_dt = dt.strptime(earnings_date, "%Y-%m-%d")
                                days_to_earnings = (earnings_dt - dt.now()).days
                except Exception:
                    pass
        except Exception as e:
            logging.warning(f"Secondary data fetch failed for {symbol}: {e}")
    
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "symbol": symbol,
        "target_price": item.target_price,
        "price_when_added": price_when_added,
        "analyst_rating_at_add": analyst_rating,
        "days_to_earnings_at_add": days_to_earnings,
        "earnings_date_at_add": earnings_date,
        "notes": item.notes,
        "added_at": datetime.now(timezone.utc).isoformat()
    }
    await db.watchlist.insert_one(doc)
    
    return {
        "id": doc["id"],
        "symbol": symbol,
        "price_when_added": price_when_added,
        "analyst_rating": analyst_rating,
        "days_to_earnings": days_to_earnings,
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
