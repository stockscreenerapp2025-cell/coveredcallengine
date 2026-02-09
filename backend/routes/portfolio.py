"""
Portfolio Routes - Portfolio management, IBKR integration, and manual trade entry
Designed for scalability with proper async patterns and efficient queries

PHASE 1 REFACTOR (December 2025):
- fetch_stock_quote now imports from data_provider.py instead of server.py
- This ensures portfolio uses the same data source as other pages
"""
from fastapi import APIRouter, Depends, Query, HTTPException, File, UploadFile
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone
import uuid
import csv
import io
import os
import logging

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import db
from utils.auth import get_current_user
from services.data_provider import fetch_stock_quote

portfolio_router = APIRouter(tags=["Portfolio"])


# ==================== PYDANTIC MODELS ====================
class PortfolioPositionCreate(BaseModel):
    symbol: str
    position_type: str  # "stock", "covered_call", "pmcc"
    shares: Optional[int] = None
    avg_cost: Optional[float] = None
    option_strike: Optional[float] = None
    option_expiry: Optional[str] = None
    option_premium: Optional[float] = None
    leaps_strike: Optional[float] = None
    leaps_expiry: Optional[str] = None
    leaps_cost: Optional[float] = None
    notes: Optional[str] = None


class ManualTradeEntry(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=10)
    trade_type: str = Field(..., description="covered_call, collar, pmcc, stock_only, option_only")
    
    # Stock leg
    stock_quantity: Optional[int] = None
    stock_price: Optional[float] = None
    stock_date: Optional[str] = None
    
    # Option leg (for covered calls / collar / PMCC)
    option_type: Optional[str] = None  # call, put
    option_action: Optional[str] = None  # sell, buy
    strike_price: Optional[float] = None
    expiry_date: Optional[str] = None
    option_premium: Optional[float] = None
    option_quantity: Optional[int] = None
    option_date: Optional[str] = None
    
    # For PMCC - LEAPS leg
    leaps_strike: Optional[float] = None
    leaps_expiry: Optional[str] = None
    leaps_cost: Optional[float] = None
    leaps_quantity: Optional[int] = None
    leaps_date: Optional[str] = None
    
    # For Collar - Protective Put leg
    put_strike: Optional[float] = None
    put_expiry: Optional[str] = None
    put_premium: Optional[float] = None
    put_quantity: Optional[int] = None
    put_date: Optional[str] = None
    
    notes: Optional[str] = None


def _get_server_data():
    """
    Lazy import to avoid circular dependencies.
    
    PHASE 1 REFACTOR: fetch_stock_quote now comes from data_provider.py
    MOCK_STOCKS still comes from server.py for fallback
    """
    from server import MOCK_STOCKS, get_massive_api_key
    return MOCK_STOCKS, get_massive_api_key


# ==================== BASIC PORTFOLIO CRUD ====================
@portfolio_router.get("/positions")
async def get_portfolio_positions(user: dict = Depends(get_current_user)):
    """Get all portfolio positions with P/L calculations"""
    MOCK_STOCKS, _ = _get_server_data()
    
    positions = await db.portfolio.find({"user_id": user["id"]}, {"_id": 0}).to_list(1000)
    
    # Calculate P/L for each position
    for pos in positions:
        symbol = pos.get("symbol", "")
        stock_data = MOCK_STOCKS.get(symbol, {"price": pos.get("avg_cost", 0)})
        current_price = stock_data["price"]
        pos["current_price"] = current_price
        
        if pos.get("position_type") == "stock" or pos.get("position_type") == "covered_call":
            cost_basis = pos.get("shares", 0) * pos.get("avg_cost", 0)
            current_value = pos.get("shares", 0) * current_price
            premium_received = pos.get("option_premium", 0) * 100 if pos.get("option_premium") else 0
            pos["unrealized_pl"] = round(current_value - cost_basis + premium_received, 2)
            pos["unrealized_pl_pct"] = round((pos["unrealized_pl"] / cost_basis * 100) if cost_basis > 0 else 0, 2)
        elif pos.get("position_type") == "pmcc":
            leaps_cost = pos.get("leaps_cost", 0) * 100
            premium_received = pos.get("option_premium", 0) * 100 if pos.get("option_premium") else 0
            pos["unrealized_pl"] = round(premium_received - leaps_cost, 2)
            pos["unrealized_pl_pct"] = round((pos["unrealized_pl"] / leaps_cost * 100) if leaps_cost > 0 else 0, 2)
    
    return positions


@portfolio_router.post("/positions")
async def add_portfolio_position(position: PortfolioPositionCreate, user: dict = Depends(get_current_user)):
    """Add a new portfolio position"""
    pos_doc = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        **position.model_dump(),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.portfolio.insert_one(pos_doc)
    return {"id": pos_doc["id"], "message": "Position added successfully"}


@portfolio_router.put("/positions/{position_id}")
async def update_portfolio_position(position_id: str, position: PortfolioPositionCreate, user: dict = Depends(get_current_user)):
    """Update an existing portfolio position"""
    result = await db.portfolio.update_one(
        {"id": position_id, "user_id": user["id"]},
        {"$set": position.model_dump()}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Position not found")
    return {"message": "Position updated"}


@portfolio_router.delete("/positions/{position_id}")
async def delete_portfolio_position(position_id: str, user: dict = Depends(get_current_user)):
    """Delete a portfolio position"""
    result = await db.portfolio.delete_one({"id": position_id, "user_id": user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Position not found")
    return {"message": "Position deleted"}


@portfolio_router.get("/summary")
async def get_portfolio_summary(user: dict = Depends(get_current_user)):
    """Get portfolio summary with totals"""
    MOCK_STOCKS, _ = _get_server_data()
    
    positions = await db.portfolio.find({"user_id": user["id"]}, {"_id": 0}).to_list(1000)
    
    total_value = 0
    total_cost = 0
    total_premium = 0
    
    for pos in positions:
        symbol = pos.get("symbol", "")
        stock_data = MOCK_STOCKS.get(symbol, {"price": pos.get("avg_cost", 0)})
        current_price = stock_data["price"]
        
        if pos.get("position_type") in ["stock", "covered_call"]:
            total_value += pos.get("shares", 0) * current_price
            total_cost += pos.get("shares", 0) * pos.get("avg_cost", 0)
            if pos.get("option_premium"):
                total_premium += pos.get("option_premium", 0) * 100
        elif pos.get("position_type") == "pmcc":
            total_cost += pos.get("leaps_cost", 0) * 100
            if pos.get("option_premium"):
                total_premium += pos.get("option_premium", 0) * 100
    
    return {
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "total_premium_collected": round(total_premium, 2),
        "unrealized_pl": round(total_value - total_cost + total_premium, 2),
        "positions_count": len(positions)
    }


# ==================== CSV IMPORT ====================
@portfolio_router.post("/import-csv")
async def import_csv(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    """Import portfolio from simple CSV format"""
    content = await file.read()
    decoded = content.decode('utf-8')
    
    reader = csv.DictReader(io.StringIO(decoded))
    imported = 0
    
    for row in reader:
        try:
            pos_doc = {
                "id": str(uuid.uuid4()),
                "user_id": user["id"],
                "symbol": row.get("Symbol", row.get("symbol", "")),
                "position_type": "stock",
                "shares": int(float(row.get("Quantity", row.get("quantity", 0)))),
                "avg_cost": float(row.get("Cost Basis Per Share", row.get("avg_cost", 0))),
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            if pos_doc["symbol"]:
                await db.portfolio.insert_one(pos_doc)
                imported += 1
        except Exception as e:
            logging.error(f"Error importing row: {e}")
            continue
    
    return {"message": f"Imported {imported} positions"}


# ==================== IBKR IMPORT ====================
@portfolio_router.post("/import-ibkr")
async def import_ibkr_csv(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    """Import and parse IBKR transaction history CSV - overwrites existing data for same accounts"""
    from services.ibkr_parser import parse_ibkr_csv
    
    content = await file.read()
    decoded = content.decode('utf-8')
    
    result = parse_ibkr_csv(decoded)
    imported_accounts = result.get('accounts', [])
    
    # Clear existing data for these accounts (overwrite behavior)
    if imported_accounts:
        await db.ibkr_transactions.delete_many({
            "user_id": user['id'],
            "account": {"$in": imported_accounts}
        })
        await db.ibkr_trades.delete_many({
            "user_id": user['id'],
            "account": {"$in": imported_accounts}
        })
    
    # Store raw transactions
    for tx in result.get('raw_transactions', []):
        tx['user_id'] = user['id']
        await db.ibkr_transactions.insert_one(tx)
    
    # Store parsed trades
    for trade in result.get('trades', []):
        trade['user_id'] = user['id']
        trade_doc = {k: v for k, v in trade.items() if k != 'transactions'}
        trade_doc['transaction_ids'] = [t['id'] for t in trade.get('transactions', [])]
        await db.ibkr_trades.insert_one(trade_doc)
    
    return {
        "message": f"Imported {len(result.get('trades', []))} trades from {len(imported_accounts)} accounts",
        "accounts": imported_accounts,
        "summary": result.get('summary', {}),
        "trades_count": len(result.get('trades', []))
    }


@portfolio_router.get("/ibkr/accounts")
async def get_ibkr_accounts(user: dict = Depends(get_current_user)):
    """Get list of broker accounts from imported data"""
    pipeline = [
        {"$match": {"user_id": user["id"]}},
        {"$group": {"_id": "$account"}},
        {"$project": {"account": "$_id", "_id": 0}}
    ]
    accounts = await db.ibkr_trades.aggregate(pipeline).to_list(100)
    return {"accounts": [a.get('account') for a in accounts if a.get('account')]}


@portfolio_router.get("/ibkr/trades")
async def get_ibkr_trades(
    user: dict = Depends(get_current_user),
    account: Optional[str] = Query(None),
    strategy: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100)
):
    """Get parsed IBKR trades with filters and pagination"""
    # PHASE 1: fetch_stock_quote now imported from data_provider.py at module level
    
    query = {"user_id": user["id"]}
    
    if account:
        query["account"] = account
    if strategy:
        query["strategy_type"] = strategy
    if status:
        query["status"] = status
    if symbol:
        query["symbol"] = {"$regex": symbol.upper(), "$options": "i"}
    
    skip = (page - 1) * limit
    
    trades = await db.ibkr_trades.find(query, {"_id": 0}).sort("date_opened", -1).skip(skip).limit(limit).to_list(limit)
    total = await db.ibkr_trades.count_documents(query)
    
    # Fetch current prices for open trades
    symbols_to_fetch = list(set(t.get('symbol') for t in trades if t.get('status') == 'Open' and t.get('symbol')))
    
    price_cache = {}
    if symbols_to_fetch:
        for sym in symbols_to_fetch:
            try:
                quote = await fetch_stock_quote(sym)
                if quote and quote.get('price'):
                    price_cache[sym] = quote.get('price')
            except Exception as e:
                logging.warning(f"Error fetching price for {sym}: {e}")
    
    # Normalize fields and calculate P/L
    for trade in trades:
        _normalize_trade_fields(trade)
        
        if trade.get('status') == 'Open' and trade.get('symbol') in price_cache:
            trade['current_price'] = price_cache[trade['symbol']]
            _calculate_unrealized_pnl(trade)
    
    return {
        "trades": trades,
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit
    }


@portfolio_router.get("/ibkr/trades/{trade_id}")
async def get_ibkr_trade_detail(trade_id: str, user: dict = Depends(get_current_user)):
    """Get detailed trade information including transaction history"""
    _, fetch_stock_quote = _get_server_data()
    
    trade = await db.ibkr_trades.find_one({"user_id": user["id"], "id": trade_id}, {"_id": 0})
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    
    _normalize_trade_fields(trade)
    
    # Fetch related transactions
    tx_ids = trade.get('transaction_ids', [])
    transactions = await db.ibkr_transactions.find(
        {"user_id": user["id"], "id": {"$in": tx_ids}},
        {"_id": 0}
    ).sort("datetime", 1).to_list(100)
    
    trade['transactions'] = transactions
    
    # Fetch current price for open trades
    if trade.get('symbol') and trade.get('status') == 'Open':
        try:
            quote = await fetch_stock_quote(trade['symbol'])
            if quote and quote.get('price'):
                trade['current_price'] = quote.get('price', 0)
                _calculate_unrealized_pnl(trade)
        except Exception as e:
            logging.warning(f"Error fetching quote for {trade['symbol']}: {e}")
    
    return trade


@portfolio_router.get("/ibkr/summary")
async def get_ibkr_summary(
    user: dict = Depends(get_current_user),
    account: Optional[str] = Query(None)
):
    """Get portfolio summary statistics"""
    query = {"user_id": user["id"]}
    if account:
        query["account"] = account
    
    trades = await db.ibkr_trades.find(query, {"_id": 0}).to_list(1000)
    
    total_invested = 0
    total_premium = 0
    total_fees = 0
    open_trades = 0
    closed_trades = 0
    by_strategy = {}
    
    for trade in trades:
        strategy = trade.get('strategy_type', 'OTHER')
        
        if strategy not in by_strategy:
            by_strategy[strategy] = {'count': 0, 'premium': 0, 'invested': 0}
        by_strategy[strategy]['count'] += 1
        by_strategy[strategy]['premium'] += trade.get('premium_received', 0) or 0
        
        shares = trade.get('shares', 0) or 0
        entry = trade.get('entry_price', 0) or 0
        by_strategy[strategy]['invested'] += shares * entry
        
        total_invested += shares * entry
        total_premium += trade.get('premium_received', 0) or 0
        total_fees += trade.get('total_fees', 0) or 0
        
        if trade.get('status') == 'Open':
            open_trades += 1
        else:
            closed_trades += 1
    
    return {
        'total_trades': len(trades),
        'open_trades': open_trades,
        'closed_trades': closed_trades,
        'total_invested': round(total_invested, 2),
        'total_premium': round(total_premium, 2),
        'total_fees': round(total_fees, 2),
        'net_premium': round(total_premium - total_fees, 2),
        'by_strategy': by_strategy
    }


@portfolio_router.delete("/ibkr/clear")
async def clear_ibkr_data(user: dict = Depends(get_current_user)):
    """Clear all imported IBKR data for the user"""
    await db.ibkr_trades.delete_many({"user_id": user["id"]})
    await db.ibkr_transactions.delete_many({"user_id": user["id"]})
    return {"message": "All IBKR data cleared"}


# ==================== AI SUGGESTIONS ====================
@portfolio_router.post("/ibkr/trades/{trade_id}/ai-suggestion")
async def get_trade_ai_suggestion(trade_id: str, user: dict = Depends(get_current_user)):
    """Get AI-powered suggestion for a trade"""
    trade = await db.ibkr_trades.find_one({"user_id": user["id"], "id": trade_id}, {"_id": 0})
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    
    suggestion = await _generate_ai_suggestion_for_trade(trade)
    
    await db.ibkr_trades.update_one(
        {"user_id": user["id"], "id": trade_id},
        {"$set": {
            "ai_suggestion": suggestion.get("full_suggestion"),
            "ai_action": suggestion.get("action"),
            "suggestion_updated": datetime.now(timezone.utc).isoformat()
        }}
    )
    
    return {"suggestion": suggestion.get("full_suggestion"), "action": suggestion.get("action"), "trade_id": trade_id}


@portfolio_router.post("/ibkr/generate-suggestions")
async def generate_all_suggestions(user: dict = Depends(get_current_user)):
    """Generate AI suggestions for all open trades"""
    logging.info(f"Generating suggestions for user {user['id']}")
    
    open_trades = await db.ibkr_trades.find(
        {"user_id": user["id"], "status": "Open"},
        {"_id": 0}
    ).to_list(100)
    
    logging.info(f"Found {len(open_trades)} open trades")
    
    if not open_trades:
        return {"message": "No open trades found", "updated": 0}
    
    updated = 0
    for trade in open_trades:
        try:
            suggestion = await _generate_ai_suggestion_for_trade(trade)
            
            await db.ibkr_trades.update_one(
                {"user_id": user["id"], "id": trade["id"]},
                {"$set": {
                    "ai_suggestion": suggestion.get("full_suggestion"),
                    "ai_action": suggestion.get("action"),
                    "suggestion_updated": datetime.now(timezone.utc).isoformat()
                }}
            )
            updated += 1
        except Exception as e:
            logging.error(f"Error generating suggestion for {trade.get('symbol')}: {e}")
            continue
    
    return {"message": f"Generated suggestions for {updated} open trades", "updated": updated}


# ==================== MANUAL TRADE ENTRY ====================
@portfolio_router.post("/manual-trade")
async def add_manual_trade(trade: ManualTradeEntry, user: dict = Depends(get_current_user)):
    """Add a manually entered trade"""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    # Validate required fields based on trade type
    _validate_manual_trade(trade, today)
    
    trade_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    
    # Calculate values
    cost_basis, premium_collected, put_cost = _calculate_trade_values(trade)
    dte = _calculate_dte(trade.expiry_date or trade.leaps_expiry or trade.put_expiry)
    days_in_trade = _calculate_days_in_trade(trade.stock_date or trade.option_date or trade.leaps_date or trade.put_date)
    break_even = _calculate_break_even(trade, cost_basis)
    strategy_type, strategy_label = _get_strategy_labels(trade)
    
    trade_doc = {
        "id": trade_id,
        "user_id": user["id"],
        "symbol": trade.symbol.upper(),
        "strategy": trade.trade_type.replace("_", " ").title(),
        "strategy_type": strategy_type,
        "strategy_label": strategy_label,
        "status": "Open",
        "source": "manual",
        "stock_quantity": trade.stock_quantity,
        "stock_price": trade.stock_price,
        "stock_date": trade.stock_date,
        "option_type": trade.option_type,
        "option_action": trade.option_action,
        "option_strike": trade.strike_price,
        "option_expiry": trade.expiry_date,
        "premium": trade.option_premium,
        "option_quantity": trade.option_quantity,
        "option_date": trade.option_date,
        "contracts": trade.option_quantity,
        "leaps_strike": trade.leaps_strike,
        "leaps_expiry": trade.leaps_expiry,
        "leaps_cost": trade.leaps_cost,
        "leaps_quantity": trade.leaps_quantity,
        "leaps_date": trade.leaps_date,
        "protective_put_strike": trade.put_strike,
        "protective_put_expiry": trade.put_expiry,
        "protective_put_premium": trade.put_premium,
        "put_quantity": trade.put_quantity,
        "put_date": trade.put_date,
        "shares": trade.stock_quantity if trade.stock_quantity else (trade.option_quantity * 100 if trade.option_quantity else None),
        "entry_price": trade.stock_price or trade.leaps_cost,
        "premium_received": trade.option_premium,
        "put_cost": put_cost,
        "break_even": break_even,
        "dte": dte,
        "days_in_trade": days_in_trade,
        "total_fees": 0,
        "cost_basis": cost_basis + put_cost if trade.trade_type == "collar" else cost_basis,
        "premium_collected": premium_collected,
        "realized_pnl": 0,
        "unrealized_pnl": 0,
        "roi": ((premium_collected - put_cost) / cost_basis * 100) if cost_basis > 0 and trade.trade_type == "collar" else ((premium_collected / cost_basis * 100) if cost_basis > 0 else 0),
        "notes": trade.notes,
        "account": "Manual",
        "date_opened": trade.stock_date or trade.option_date or trade.leaps_date or trade.put_date or now.isoformat(),
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    
    await db.ibkr_trades.insert_one(trade_doc)
    
    if "_id" in trade_doc:
        del trade_doc["_id"]
    return {"message": "Trade added successfully", "trade": trade_doc}


@portfolio_router.put("/manual-trade/{trade_id}")
async def update_manual_trade(trade_id: str, trade: ManualTradeEntry, user: dict = Depends(get_current_user)):
    """Update a manually entered trade"""
    existing = await db.ibkr_trades.find_one({"id": trade_id, "user_id": user["id"], "source": "manual"})
    if not existing:
        raise HTTPException(status_code=404, detail="Trade not found or not a manual entry")
    
    cost_basis, premium_collected, put_cost = _calculate_trade_values(trade)
    dte = _calculate_dte(trade.expiry_date or trade.leaps_expiry or trade.put_expiry)
    days_in_trade = _calculate_days_in_trade(trade.stock_date or trade.option_date or trade.leaps_date or trade.put_date)
    break_even = _calculate_break_even(trade, cost_basis)
    strategy_type, strategy_label = _get_strategy_labels(trade)
    
    update_doc = {
        "symbol": trade.symbol.upper(),
        "strategy": trade.trade_type.replace("_", " ").title(),
        "strategy_type": strategy_type,
        "strategy_label": strategy_label,
        "stock_quantity": trade.stock_quantity,
        "stock_price": trade.stock_price,
        "stock_date": trade.stock_date,
        "option_type": trade.option_type,
        "option_action": trade.option_action,
        "option_strike": trade.strike_price,
        "option_expiry": trade.expiry_date,
        "premium": trade.option_premium,
        "option_quantity": trade.option_quantity,
        "contracts": trade.option_quantity,
        "option_date": trade.option_date,
        "leaps_strike": trade.leaps_strike,
        "leaps_expiry": trade.leaps_expiry,
        "leaps_cost": trade.leaps_cost,
        "leaps_quantity": trade.leaps_quantity,
        "leaps_date": trade.leaps_date,
        "protective_put_strike": trade.put_strike,
        "protective_put_expiry": trade.put_expiry,
        "protective_put_premium": trade.put_premium,
        "put_quantity": trade.put_quantity,
        "put_date": trade.put_date,
        "shares": trade.stock_quantity if trade.stock_quantity else (trade.option_quantity * 100 if trade.option_quantity else None),
        "entry_price": trade.stock_price or trade.leaps_cost,
        "premium_received": trade.option_premium,
        "break_even": break_even,
        "dte": dte,
        "days_in_trade": days_in_trade,
        "total_fees": 0,
        "cost_basis": cost_basis + put_cost if trade.trade_type == "collar" else cost_basis,
        "premium_collected": premium_collected,
        "put_cost": put_cost,
        "roi": ((premium_collected - put_cost) / cost_basis * 100) if cost_basis > 0 and trade.trade_type == "collar" else ((premium_collected / cost_basis * 100) if cost_basis > 0 else 0),
        "notes": trade.notes,
        "date_opened": trade.stock_date or trade.option_date or trade.leaps_date or trade.put_date or existing.get("date_opened"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    
    await db.ibkr_trades.update_one({"id": trade_id}, {"$set": update_doc})
    return {"message": "Trade updated successfully"}


@portfolio_router.delete("/manual-trade/{trade_id}")
async def delete_manual_trade(trade_id: str, user: dict = Depends(get_current_user)):
    """Delete a manually entered trade"""
    result = await db.ibkr_trades.delete_one({"id": trade_id, "user_id": user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Trade not found")
    return {"message": "Trade deleted successfully"}


@portfolio_router.put("/trade/{trade_id}/close")
async def close_trade(trade_id: str, close_price: float = Query(...), user: dict = Depends(get_current_user)):
    """Mark a trade as closed with final P/L"""
    trade = await db.ibkr_trades.find_one({"id": trade_id, "user_id": user["id"]})
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    
    cost_basis = trade.get("cost_basis", 0)
    premium_collected = trade.get("premium_collected", 0)
    
    realized_pnl = premium_collected
    if trade.get("stock_quantity") and trade.get("stock_price"):
        stock_pnl = (close_price - trade["stock_price"]) * trade["stock_quantity"] * 100
        realized_pnl += stock_pnl
    
    await db.ibkr_trades.update_one(
        {"id": trade_id},
        {"$set": {
            "status": "Closed",
            "close_price": close_price,
            "realized_pnl": realized_pnl,
            "date_closed": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }}
    )
    
    return {"message": "Trade closed", "realized_pnl": realized_pnl}


# ==================== HELPER FUNCTIONS ====================
def _normalize_trade_fields(trade: dict):
    """Normalize field names for frontend compatibility"""
    if trade.get('strike') and not trade.get('option_strike'):
        trade['option_strike'] = trade.get('strike')
    if trade.get('expiry') and not trade.get('option_expiry'):
        trade['option_expiry'] = trade.get('expiry')
    if trade.get('option_quantity') and not trade.get('contracts'):
        trade['contracts'] = trade.get('option_quantity')
    if not trade.get('days_in_trade') and trade.get('date_opened'):
        try:
            open_dt = datetime.fromisoformat(trade['date_opened'].replace('Z', '+00:00')) if 'T' in trade['date_opened'] else datetime.strptime(trade['date_opened'], "%Y-%m-%d")
            trade['days_in_trade'] = (datetime.now(timezone.utc).replace(tzinfo=None) - open_dt.replace(tzinfo=None)).days
        except:
            pass
    if trade.get('total_fees') is None:
        trade['total_fees'] = 0
    if not trade.get('account'):
        trade['account'] = 'Manual' if trade.get('source') == 'manual' else 'IBKR'


def _calculate_unrealized_pnl(trade: dict):
    """Calculate unrealized P/L for a trade"""
    shares = trade.get('shares', 0) or 0
    entry_price = trade.get('entry_price', 0) or 0
    break_even = trade.get('break_even') or 0
    current_price = trade.get('current_price', 0)
    
    if shares > 0 and current_price:
        if break_even and break_even > 0:
            trade['unrealized_pnl'] = round((current_price - break_even) * shares, 2)
        elif entry_price and entry_price > 0:
            trade['unrealized_pnl'] = round((current_price - entry_price) * shares, 2)
        
        if entry_price > 0:
            trade['roi'] = round(((current_price - (break_even or entry_price)) / entry_price) * 100, 2)


def _validate_manual_trade(trade: ManualTradeEntry, today: str):
    """Validate manual trade entry"""
    if not trade.symbol or trade.symbol.strip() == "":
        raise HTTPException(status_code=400, detail="Symbol is required")
    
    # Date validations
    if trade.stock_date and trade.stock_date > today:
        raise HTTPException(status_code=400, detail="Purchase date cannot be in the future")
    if trade.option_date and trade.option_date > today:
        raise HTTPException(status_code=400, detail="Option purchase date cannot be in the future")
    if trade.leaps_date and trade.leaps_date > today:
        raise HTTPException(status_code=400, detail="LEAPS purchase date cannot be in the future")
    if trade.put_date and trade.put_date > today:
        raise HTTPException(status_code=400, detail="Put purchase date cannot be in the future")
    if trade.expiry_date and trade.expiry_date < today:
        raise HTTPException(status_code=400, detail="Expiry date cannot be in the past")
    if trade.leaps_expiry and trade.leaps_expiry < today:
        raise HTTPException(status_code=400, detail="LEAPS expiry date cannot be in the past")
    if trade.put_expiry and trade.put_expiry < today:
        raise HTTPException(status_code=400, detail="Put expiry date cannot be in the past")
    
    # Trade type validations
    if trade.trade_type == "covered_call":
        if not trade.stock_quantity or not trade.stock_price:
            raise HTTPException(status_code=400, detail="Stock quantity and price are required for covered calls")
        if not trade.strike_price or not trade.option_premium:
            raise HTTPException(status_code=400, detail="Strike price and premium are required for covered calls")
        if not trade.expiry_date:
            raise HTTPException(status_code=400, detail="Expiry date is required for covered calls")
    elif trade.trade_type == "pmcc":
        if not trade.leaps_cost or not trade.leaps_strike:
            raise HTTPException(status_code=400, detail="LEAPS cost and strike are required for PMCC")
        if not trade.leaps_expiry:
            raise HTTPException(status_code=400, detail="LEAPS expiry date is required for PMCC")
        if not trade.strike_price or not trade.option_premium:
            raise HTTPException(status_code=400, detail="Short call strike and premium are required for PMCC")
        if not trade.expiry_date:
            raise HTTPException(status_code=400, detail="Short call expiry date is required for PMCC")
    elif trade.trade_type == "stock_only":
        if not trade.stock_quantity or not trade.stock_price:
            raise HTTPException(status_code=400, detail="Stock quantity and price are required")
    elif trade.trade_type == "option_only":
        if not trade.strike_price or not trade.option_premium or not trade.expiry_date:
            raise HTTPException(status_code=400, detail="Strike, premium, and expiry are required")


def _calculate_trade_values(trade: ManualTradeEntry):
    """Calculate cost basis, premium, and put cost for a trade"""
    cost_basis = 0
    premium_collected = 0
    put_cost = 0
    
    if trade.trade_type == "covered_call":
        if trade.stock_quantity and trade.stock_price:
            cost_basis = trade.stock_quantity * trade.stock_price
        if trade.option_premium and trade.option_quantity:
            premium_collected = trade.option_premium * trade.option_quantity * 100
    elif trade.trade_type == "collar":
        if trade.stock_quantity and trade.stock_price:
            cost_basis = trade.stock_quantity * trade.stock_price
        if trade.option_premium and trade.option_quantity:
            premium_collected = trade.option_premium * trade.option_quantity * 100
        if trade.put_premium and trade.put_quantity:
            put_cost = trade.put_premium * trade.put_quantity * 100
    elif trade.trade_type == "pmcc":
        if trade.leaps_cost and trade.leaps_quantity:
            cost_basis = trade.leaps_cost * trade.leaps_quantity * 100
        if trade.option_premium and trade.option_quantity:
            premium_collected = trade.option_premium * trade.option_quantity * 100
    elif trade.trade_type == "stock_only":
        if trade.stock_quantity and trade.stock_price:
            cost_basis = trade.stock_quantity * trade.stock_price
    elif trade.trade_type == "option_only":
        if trade.option_premium and trade.option_quantity:
            if trade.option_action == "buy":
                cost_basis = trade.option_premium * trade.option_quantity * 100
            else:
                premium_collected = trade.option_premium * trade.option_quantity * 100
    
    return cost_basis, premium_collected, put_cost


def _calculate_dte(expiry_date_str: Optional[str]) -> Optional[int]:
    """Calculate days to expiration"""
    if not expiry_date_str:
        return None
    try:
        expiry_dt = datetime.strptime(expiry_date_str, "%Y-%m-%d")
        dte = (expiry_dt - datetime.now()).days
        return max(0, dte)
    except:
        return None


def _calculate_days_in_trade(open_date: Optional[str]) -> Optional[int]:
    """Calculate days in trade"""
    if not open_date:
        return None
    try:
        open_dt = datetime.strptime(open_date, "%Y-%m-%d")
        days = (datetime.now() - open_dt).days
        return max(0, days)
    except:
        return None


def _calculate_break_even(trade: ManualTradeEntry, cost_basis: float) -> Optional[float]:
    """Calculate break-even price"""
    if trade.trade_type == "covered_call" and trade.stock_price and trade.option_premium:
        return trade.stock_price - trade.option_premium
    elif trade.trade_type == "collar" and trade.stock_price and trade.option_premium and trade.put_premium:
        return trade.stock_price - trade.option_premium + trade.put_premium
    elif trade.trade_type == "pmcc" and trade.leaps_cost and trade.leaps_strike and trade.option_premium:
        return trade.leaps_strike + trade.leaps_cost - trade.option_premium
    return None


def _get_strategy_labels(trade: ManualTradeEntry) -> tuple:
    """Get strategy type and label"""
    strategy_map = {
        "covered_call": ("COVERED_CALL", "Covered Call"),
        "collar": ("COLLAR", "Collar"),
        "pmcc": ("PMCC", "PMCC"),
        "stock_only": ("STOCK", "Stock Only"),
    }
    
    if trade.trade_type == "option_only":
        option_type = (trade.option_type or "call").lower()
        option_action = (trade.option_action or "buy").lower()
        if option_action == "sell":
            return ("NAKED_CALL", "Naked Call") if option_type == "call" else ("NAKED_PUT", "Naked Put")
        else:
            return ("LONG_CALL", "Long Call") if option_type == "call" else ("LONG_PUT", "Long Put")
    
    return strategy_map.get(trade.trade_type, ("OTHER", "Other"))


async def _generate_ai_suggestion_for_trade(trade: dict) -> dict:
    """Generate AI suggestion for a single trade"""
    _, fetch_stock_quote = _get_server_data()
    
    symbol = trade.get('symbol', '')
    current_price = None
    
    # Fetch current market data
    if symbol:
        try:
            quote = await fetch_stock_quote(symbol)
            if quote:
                current_price = quote.get('price', 0)
        except:
            pass
    
    # Calculate metrics
    dte = trade.get('dte', 0) or 0
    option_strike = trade.get('option_strike')
    entry_price = trade.get('entry_price', 0) or 0
    break_even = trade.get('break_even')
    premium = trade.get('premium_received', 0) or 0
    strategy = trade.get('strategy_type', '')
    
    # Determine profit status
    profit_status = "N/A"
    if current_price and entry_price:
        profit_status = "Profitable" if current_price > (break_even or entry_price) else "At Loss"
    
    # ITM/OTM status
    itm_status = "N/A"
    if option_strike and current_price:
        if 'CALL' in strategy.upper() or strategy in ['COVERED_CALL', 'PMCC']:
            itm_status = "ITM" if current_price > option_strike else "OTM"
        elif 'PUT' in strategy.upper() or strategy == 'NAKED_PUT':
            itm_status = "ITM" if current_price < option_strike else "OTM"
    
    # Format values for the prompt
    current_price_str = f"${current_price:.2f}" if current_price else "N/A"
    strike_str = f"${option_strike:.2f}" if option_strike else "N/A"
    
    context = f"""
    Analyze this options trade:
    Symbol: {symbol}, Strategy: {trade.get('strategy_label', strategy)}
    Entry: ${entry_price:.2f}, Current: {current_price_str}
    Strike: {strike_str}, DTE: {dte}, Status: {itm_status}
    Premium: ${premium:.2f}, Profit: {profit_status}
    
    Recommend: HOLD, LET_EXPIRE, ROLL_UP, ROLL_DOWN, ROLL_OUT, or CLOSE
    """
    
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        
        llm = LlmChat(
            api_key=os.environ.get("EMERGENT_LLM_KEY"),
            session_id=str(uuid.uuid4()),
            system_message="You are a professional options trading advisor. Start with ONE action word, then explain briefly."
        )
        response = await llm.send_message(UserMessage(text=context))
        full_suggestion = response if isinstance(response, str) else str(response)
        
        action = "HOLD"
        first_line = full_suggestion.strip().split('\n')[0].strip().upper()
        for possible_action in ["LET_EXPIRE", "HOLD", "CLOSE", "ROLL_UP", "ROLL_DOWN", "ROLL_OUT"]:
            if possible_action in first_line:
                action = possible_action
                break
        
        return {"action": action, "full_suggestion": full_suggestion}
    except Exception as e:
        logging.error(f"AI suggestion error: {e}")
        return {"action": "N/A", "full_suggestion": f"Unable to generate AI suggestion: {str(e)}"}
