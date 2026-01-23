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
    """
    Get the best covered call opportunity for a symbol.
    
    LAYER 3 COMPLIANT: Uses snapshot data from the screener, NOT live data.
    This ensures data consistency across all pages.
    """
    try:
        # Import snapshot service to use Layer 1/2/3 data
        from services.snapshot_service import SnapshotService
        
        snapshot_service = SnapshotService()
        
        # Get validated snapshot data (Layer 1 + 2)
        stock_snapshot, stock_error = await snapshot_service.get_stock_snapshot(symbol)
        if stock_error or not stock_snapshot:
            # Fallback: fetch fresh data but mark as non-snapshot
            return await _get_best_opportunity_live(symbol, api_key, underlying_price)
        
        # Use snapshot price as authoritative
        stock_price = stock_snapshot.get("stock_close_price") or underlying_price
        
        # Get calls from snapshot (Layer 3 validated)
        calls, call_error = await snapshot_service.get_valid_calls_for_scan(
            symbol=symbol,
            min_dte=1,
            max_dte=45,
            min_strike_pct=0.98,  # 2% ITM to 10% OTM
            max_strike_pct=1.10,
            min_bid=0.05
        )
        
        if call_error or not calls:
            return await _get_best_opportunity_live(symbol, api_key, underlying_price)
        
        best_opp = None
        best_score = 0
        
        for call in calls:
            strike = call.get("strike", 0)
            expiry = call.get("expiry", "")
            dte = call.get("dte", 0)
            premium = call.get("bid", 0) or call.get("premium", 0)  # BID only
            ask = call.get("ask", 0)
            open_interest = call.get("open_interest", 0)
            iv = call.get("implied_volatility", 0)
            delta = call.get("delta", 0)
            
            if premium <= 0 or strike <= 0 or dte < 1:
                continue
            
            # Calculate ROI
            roi_pct = (premium / stock_price) * 100 if stock_price > 0 else 0
            annualized_roi = roi_pct * (365 / dte) if dte > 0 else 0
            
            if roi_pct < 0.3:  # Minimum 0.3% yield
                continue
            
            # Estimate delta if not provided
            if delta == 0 and stock_price > 0 and strike > 0:
                moneyness = (stock_price - strike) / stock_price
                if moneyness < 0:  # OTM
                    delta = max(0.05, 0.50 + moneyness * 2)
                else:  # ITM
                    delta = min(0.95, 0.50 + moneyness * 2)
            
            # Determine type: Weekly (<=14 DTE) or Monthly
            option_type = "Weekly" if dte <= 14 else "Monthly"
            
            # IV in percentage form (Layer 3 standard)
            iv_pct = iv * 100 if iv > 0 and iv < 5 else iv
            
            # IV Rank calculation (Layer 3 standard: 15-80% range)
            iv_rank = min(100, max(0, (iv_pct - 15) / 65 * 100)) if iv_pct > 0 else 0
            
            # Calculate AI Score
            roi_score = min(roi_pct * 15, 40)
            iv_score = min(iv_pct / 5, 20) if iv_pct > 0 else 10
            delta_score = max(0, 20 - abs(delta - 0.35) * 50)
            liquidity_score = 10 if open_interest >= 500 else 5 if open_interest >= 100 else 2
            
            ai_score = round(roi_score + iv_score + delta_score + liquidity_score, 1)
            
            if ai_score > best_score:
                best_score = ai_score
                
                # Calculate spread percentage
                spread_pct = ((ask - premium) / premium * 100) if premium > 0 and ask else 0
                
                # Build contract in Layer 3 authoritative format
                best_opp = {
                    # SHORT_CALL fields (Layer 3 contract)
                    "strike": strike,
                    "expiry": expiry,
                    "dte": dte,
                    "premium": round(premium, 2),  # BID ONLY
                    "bid": round(premium, 2),
                    "ask": round(ask, 2) if ask else None,
                    "spread_pct": round(spread_pct, 2),
                    "delta": round(delta, 4),
                    "implied_volatility": round(iv_pct, 1),  # Percentage form
                    "iv": round(iv_pct, 1),  # Legacy field for backwards compat
                    "iv_rank": round(iv_rank, 0),
                    "volume": call.get("volume", 0),
                    "open_interest": open_interest,
                    # ECONOMICS fields (Layer 3 contract)
                    "roi_pct": round(roi_pct, 2),
                    "annualized_roi_pct": round(annualized_roi, 1),
                    # METADATA fields
                    "type": option_type,
                    "ai_score": ai_score,
                    "source": "snapshot",
                    "data_source": "layer3"
                }
        
        return best_opp
    except Exception as e:
        logging.error(f"Error getting opportunity for {symbol} from snapshot: {e}")
        return await _get_best_opportunity_live(symbol, api_key, underlying_price)


async def _get_best_opportunity_live(symbol: str, api_key: str, underlying_price: float) -> dict:
    """
    FALLBACK: Get opportunity from live data when snapshot unavailable.
    Used only when Layer 3 snapshot data is not available.
    """
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
            premium = opt.get("close", 0) or opt.get("bid", 0)
            open_interest = opt.get("open_interest", 0) or 0
            iv = opt.get("implied_volatility", 0) or 0
            
            if premium <= 0 or strike <= 0 or dte < 1:
                continue
            
            # Filter for reasonable strikes (slightly OTM)
            strike_pct = (strike / underlying_price) * 100 if underlying_price > 0 else 0
            if strike_pct < 98 or strike_pct > 110:
                continue
            
            roi_pct = (premium / underlying_price) * 100
            
            if roi_pct > 20:  # Sanity check
                continue
            
            if open_interest > 0 and open_interest < 10:
                continue
            
            if roi_pct > best_roi and roi_pct >= 0.3:
                best_roi = roi_pct
                
                # Estimate delta based on moneyness
                strike_pct_diff = ((strike - underlying_price) / underlying_price) * 100
                if strike_pct_diff <= 0:
                    estimated_delta = 0.55 - (abs(strike_pct_diff) * 0.02)
                else:
                    estimated_delta = 0.50 - (strike_pct_diff * 0.03)
                estimated_delta = max(0.15, min(0.60, estimated_delta))
                
                if iv == 0:
                    iv = 0.30
                
                option_type = "Weekly" if dte <= 14 else "Monthly"
                
                # Convert IV to percentage
                iv_pct = iv * 100 if iv < 5 else iv
                
                # IV Rank (Layer 3 standard)
                iv_rank = min(100, max(0, (iv_pct - 15) / 65 * 100)) if iv_pct > 0 else 0
                
                # Calculate AI Score
                roi_score = min(roi_pct * 15, 40)
                iv_score = min(iv_pct / 5, 20)
                delta_score = max(0, 20 - abs(estimated_delta - 0.35) * 50)
                liquidity_score = 10 if open_interest >= 500 else 5 if open_interest >= 100 else 2
                ai_score = round(roi_score + iv_score + delta_score + liquidity_score, 1)
                
                annualized_roi = roi_pct * (365 / dte) if dte > 0 else 0
                
                best_opp = {
                    "strike": strike,
                    "expiry": expiry,
                    "dte": dte,
                    "premium": round(premium, 2),
                    "bid": round(premium, 2),
                    "delta": round(estimated_delta, 4),
                    "implied_volatility": round(iv_pct, 1),
                    "iv": round(iv_pct, 1),
                    "iv_rank": round(iv_rank, 0),
                    "roi_pct": round(roi_pct, 2),
                    "annualized_roi_pct": round(annualized_roi, 1),
                    "volume": opt.get("volume", 0),
                    "open_interest": open_interest,
                    "type": option_type,
                    "ai_score": ai_score,
                    "source": "live",
                    "data_source": "live_fallback"
                }
        
        return best_opp
    except Exception as e:
        logging.error(f"Error getting live opportunity for {symbol}: {e}")
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
            "analyst_rating": data.get("analyst_rating"),
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
    """Add a symbol to user's watchlist with current price"""
    get_massive_api_key, _ = _get_server_functions()
    
    symbol = item.symbol.upper()
    
    # Check if already in watchlist
    existing = await db.watchlist.find_one({"user_id": user["id"], "symbol": symbol})
    if existing:
        raise HTTPException(status_code=400, detail="Symbol already in watchlist")
    
    # Get current price (Yahoo primary)
    api_key = await get_massive_api_key()
    stock_data = await fetch_stock_quote(symbol, api_key)
    price_when_added = stock_data.get("price", 0) if stock_data else 0
    
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
