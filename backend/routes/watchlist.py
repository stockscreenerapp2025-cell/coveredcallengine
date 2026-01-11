"""
Watchlist routes
"""
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime, timezone
import uuid

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import db
from models.schemas import WatchlistItemCreate
from utils.auth import get_current_user

watchlist_router = APIRouter(tags=["Watchlist"])


@watchlist_router.get("/")
async def get_watchlist(user: dict = Depends(get_current_user)):
    """Get user's watchlist with current prices"""
    # Import here to avoid circular dependency
    from server import MOCK_STOCKS
    
    items = await db.watchlist.find({"user_id": user["id"]}, {"_id": 0}).to_list(100)
    
    # Enrich with current prices
    for item in items:
        symbol = item.get("symbol", "")
        stock_data = MOCK_STOCKS.get(symbol, {"price": 0, "change": 0, "change_pct": 0})
        item["current_price"] = stock_data["price"]
        item["change"] = stock_data["change"]
        item["change_pct"] = stock_data["change_pct"]
    
    return items


@watchlist_router.post("/")
async def add_to_watchlist(item: WatchlistItemCreate, user: dict = Depends(get_current_user)):
    """Add a symbol to user's watchlist"""
    # Check if already in watchlist
    existing = await db.watchlist.find_one({"user_id": user["id"], "symbol": item.symbol.upper()})
    if existing:
        raise HTTPException(status_code=400, detail="Symbol already in watchlist")
    
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "symbol": item.symbol.upper(),
        "target_price": item.target_price,
        "notes": item.notes,
        "added_at": datetime.now(timezone.utc).isoformat()
    }
    await db.watchlist.insert_one(doc)
    return {"id": doc["id"], "message": "Added to watchlist"}


@watchlist_router.delete("/{item_id}")
async def remove_from_watchlist(item_id: str, user: dict = Depends(get_current_user)):
    """Remove an item from user's watchlist"""
    result = await db.watchlist.delete_one({"id": item_id, "user_id": user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"message": "Removed from watchlist"}
