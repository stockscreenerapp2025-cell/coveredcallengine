"""
Snapshot Routes - PHASE 1: Data Ingestion API

These endpoints manage the two-phase architecture:
- Trigger ingestion of stock and option chain snapshots
- View snapshot status and health
- Admin controls for data management
"""

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from typing import List, Optional
import logging
import os
from datetime import datetime, timezone

from services.snapshot_service import SnapshotService

logger = logging.getLogger(__name__)

snapshot_router = APIRouter(prefix="/api/snapshots", tags=["snapshots"])

# Default symbols for CC screening
CC_SYMBOLS = [
    # Tech
    "AAPL", "MSFT", "GOOGL", "META", "NVDA", "AMD", "INTC", "CSCO", "ORCL", "IBM",
    "MU", "QCOM", "TXN", "ADI", "MCHP", "ON", "HPQ", "DELL",
    # Financials
    "JPM", "BAC", "WFC", "C", "GS", "MS", "USB", "PNC", "TFC", "KEY", "RF", "CFG",
    # Consumer
    "KO", "PEP", "PG", "JNJ", "MRK", "PFE", "ABBV", "BMY", "GILD",
    "NKE", "SBUX", "MCD", "DIS", "HD", "LOW", "TGT", "WMT", "COST",
    # Energy
    "XOM", "CVX", "COP", "OXY", "DVN", "APA", "HAL", "SLB",
    # Industrials
    "CAT", "DE", "GE", "HON", "UNP", "UPS", "FDX",
    # Growth/Fintech
    "PYPL", "SQ", "UBER", "LYFT", "ABNB",
    # Airlines/Travel
    "AAL", "DAL", "UAL", "LUV", "CCL", "NCLH", "RCL",
    # High Volatility
    "PLTR", "SOFI", "HOOD", "COIN", "ROKU", "SNAP",
    # Mining/Materials
    "NEM", "FCX", "GOLD", "CLF"
]

# Singleton service instance
_snapshot_service: Optional[SnapshotService] = None


def get_snapshot_service() -> SnapshotService:
    """Get or create snapshot service singleton."""
    global _snapshot_service
    if _snapshot_service is None:
        from server import db
        polygon_key = os.environ.get('POLYGON_API_KEY') or os.environ.get('MASSIVE_POLYGON_API_KEY')
        _snapshot_service = SnapshotService(db, polygon_key)
    return _snapshot_service


# Auth dependency (reuse from existing)
from routes.auth import get_current_user


# ==================== INGESTION ENDPOINTS ====================

@snapshot_router.post("/ingest/stock/{symbol}")
async def ingest_stock_snapshot(
    symbol: str,
    user: dict = Depends(get_current_user())
):
    """
    Ingest a single stock snapshot.
    
    Fetches current stock data and stores with full metadata.
    """
    service = get_snapshot_service()
    result = await service.ingest_stock_snapshot(symbol)
    
    return {
        "symbol": symbol,
        "success": result.get("completeness_flag", False),
        "snapshot": result
    }


@snapshot_router.post("/ingest/chain/{symbol}")
async def ingest_option_chain_snapshot(
    symbol: str,
    stock_price: float = Query(..., description="Current stock price"),
    user: dict = Depends(get_current_user())
):
    """
    Ingest option chain snapshot for a symbol.
    
    Requires stock_price to validate chain completeness.
    """
    service = get_snapshot_service()
    result = await service.ingest_option_chain_snapshot(symbol, stock_price)
    
    return {
        "symbol": symbol,
        "success": result.get("completeness_flag", False),
        "valid_contracts": result.get("valid_contracts", 0),
        "total_contracts": result.get("total_contracts", 0),
        "snapshot_time": result.get("options_snapshot_time")
    }


@snapshot_router.post("/ingest/full/{symbol}")
async def ingest_full_snapshot(
    symbol: str,
    user: dict = Depends(get_current_user())
):
    """
    Ingest both stock and option chain snapshot for a symbol.
    
    This is the recommended way to ingest data for scanning.
    """
    service = get_snapshot_service()
    
    # Stock first
    stock_result = await service.ingest_stock_snapshot(symbol)
    
    if not stock_result.get("completeness_flag"):
        return {
            "symbol": symbol,
            "success": False,
            "error": f"Stock data incomplete: {stock_result.get('error')}"
        }
    
    # Then option chain
    chain_result = await service.ingest_option_chain_snapshot(
        symbol, 
        stock_result.get("price", 0)
    )
    
    return {
        "symbol": symbol,
        "success": chain_result.get("completeness_flag", False),
        "stock": {
            "price": stock_result.get("price"),
            "source": stock_result.get("source"),
            "data_age_hours": stock_result.get("data_age_hours")
        },
        "options": {
            "valid_contracts": chain_result.get("valid_contracts", 0),
            "total_contracts": chain_result.get("total_contracts", 0),
            "expiries": len(chain_result.get("expiries", [])),
            "completeness_flag": chain_result.get("completeness_flag")
        }
    }


@snapshot_router.post("/ingest/batch")
async def ingest_batch_snapshots(
    symbols: List[str] = None,
    use_defaults: bool = Query(False, description="Use default CC symbol list"),
    background_tasks: BackgroundTasks = None,
    user: dict = Depends(get_current_user())
):
    """
    Batch ingest snapshots for multiple symbols.
    
    If use_defaults=True, uses the standard CC screening symbol list.
    """
    # Check admin role
    if user.get("role") not in ["admin", "support"]:
        raise HTTPException(status_code=403, detail="Admin access required for batch ingestion")
    
    target_symbols = symbols if symbols else (CC_SYMBOLS if use_defaults else [])
    
    if not target_symbols:
        raise HTTPException(status_code=400, detail="No symbols provided")
    
    service = get_snapshot_service()
    
    # Run in background for large batches
    if len(target_symbols) > 10 and background_tasks:
        background_tasks.add_task(service.ingest_symbols, target_symbols)
        return {
            "status": "started",
            "message": f"Ingesting {len(target_symbols)} symbols in background",
            "symbols": target_symbols[:10],
            "total": len(target_symbols)
        }
    
    # Run synchronously for small batches
    result = await service.ingest_symbols(target_symbols)
    return result


@snapshot_router.post("/ingest/all")
async def ingest_all_default_symbols(
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user())
):
    """
    Trigger full ingestion of all default CC symbols.
    
    This should be called after market close (4:45 PM ET).
    Runs in background.
    """
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    service = get_snapshot_service()
    background_tasks.add_task(service.ingest_symbols, CC_SYMBOLS)
    
    return {
        "status": "started",
        "message": f"Full ingestion started for {len(CC_SYMBOLS)} symbols",
        "symbols_count": len(CC_SYMBOLS),
        "triggered_at": datetime.now(timezone.utc).isoformat(),
        "triggered_by": user.get("email")
    }


# ==================== RETRIEVAL ENDPOINTS ====================

@snapshot_router.get("/stock/{symbol}")
async def get_stock_snapshot(
    symbol: str,
    user: dict = Depends(get_current_user())
):
    """
    Get stored stock snapshot.
    
    Returns error if snapshot is missing, incomplete, or stale.
    """
    service = get_snapshot_service()
    snapshot, error = await service.get_stock_snapshot(symbol)
    
    if error:
        raise HTTPException(status_code=404, detail=error)
    
    return snapshot


@snapshot_router.get("/chain/{symbol}")
async def get_option_chain_snapshot(
    symbol: str,
    user: dict = Depends(get_current_user())
):
    """
    Get stored option chain snapshot.
    
    Returns error if snapshot is missing, incomplete, or stale.
    """
    service = get_snapshot_service()
    snapshot, error = await service.get_option_chain_snapshot(symbol)
    
    if error:
        raise HTTPException(status_code=404, detail=error)
    
    # Don't return full chain data - too large
    return {
        "symbol": snapshot.get("symbol"),
        "stock_price": snapshot.get("stock_price"),
        "snapshot_trade_date": snapshot.get("snapshot_trade_date"),
        "options_snapshot_time": snapshot.get("options_snapshot_time"),
        "data_age_hours": snapshot.get("data_age_hours"),
        "completeness_flag": snapshot.get("completeness_flag"),
        "source": snapshot.get("source"),
        "expiries_count": len(snapshot.get("expiries", [])),
        "calls_count": len(snapshot.get("calls", [])),
        "puts_count": len(snapshot.get("puts", [])),
        "valid_contracts": snapshot.get("valid_contracts", 0),
        "total_contracts": snapshot.get("total_contracts", 0)
    }


@snapshot_router.get("/calls/{symbol}")
async def get_valid_calls(
    symbol: str,
    min_dte: int = Query(7, ge=1),
    max_dte: int = Query(45, le=365),
    min_strike_pct: float = Query(1.0, ge=0.8),
    max_strike_pct: float = Query(1.15, le=1.5),
    user: dict = Depends(get_current_user())
):
    """
    Get valid call options for CC scanning.
    
    Returns contracts with BID price as premium (SELL leg).
    """
    service = get_snapshot_service()
    calls, error = await service.get_valid_calls_for_scan(
        symbol,
        min_dte=min_dte,
        max_dte=max_dte,
        min_strike_pct=min_strike_pct,
        max_strike_pct=max_strike_pct
    )
    
    if error:
        raise HTTPException(status_code=404, detail=error)
    
    return {
        "symbol": symbol,
        "count": len(calls),
        "contracts": calls,
        "pricing_rule": "BID only (SELL leg)"
    }


@snapshot_router.get("/leaps/{symbol}")
async def get_valid_leaps(
    symbol: str,
    min_dte: int = Query(365, ge=180),
    max_dte: int = Query(730, le=1095),
    min_delta: float = Query(0.70, ge=0.50),
    max_spread_pct: float = Query(10.0, le=50.0),
    min_oi: int = Query(500, ge=0),
    user: dict = Depends(get_current_user())
):
    """
    Get valid LEAP options for PMCC scanning.
    
    Returns contracts with ASK price as premium (BUY leg).
    """
    service = get_snapshot_service()
    leaps, error = await service.get_valid_leaps_for_pmcc(
        symbol,
        min_dte=min_dte,
        max_dte=max_dte,
        min_delta=min_delta,
        max_spread_pct=max_spread_pct,
        min_oi=min_oi
    )
    
    if error:
        raise HTTPException(status_code=404, detail=error)
    
    return {
        "symbol": symbol,
        "count": len(leaps),
        "contracts": leaps,
        "pricing_rule": "ASK only (BUY leg)"
    }


# ==================== STATUS & ADMIN ENDPOINTS ====================

@snapshot_router.get("/status")
async def get_snapshot_status(
    user: dict = Depends(get_current_user())
):
    """
    Get overall snapshot health status.
    
    Shows counts of valid, stale, and incomplete snapshots.
    """
    service = get_snapshot_service()
    status = await service.get_snapshot_status()
    return status


@snapshot_router.get("/symbols")
async def get_available_symbols(
    user: dict = Depends(get_current_user())
):
    """
    Get list of symbols with valid snapshots ready for scanning.
    """
    service = get_snapshot_service()
    
    # Find symbols with complete snapshots
    pipeline = [
        {"$match": {"completeness_flag": True, "data_age_hours": {"$lte": 48}}},
        {"$project": {"symbol": 1, "price": 1, "data_age_hours": 1, "_id": 0}}
    ]
    
    stocks = await service.db.stock_snapshots.aggregate(pipeline).to_list(500)
    
    return {
        "count": len(stocks),
        "symbols": stocks,
        "default_symbols": CC_SYMBOLS
    }


@snapshot_router.delete("/cleanup")
async def cleanup_old_snapshots(
    days: int = Query(30, ge=1, le=365),
    user: dict = Depends(get_current_user())
):
    """
    Remove snapshots older than specified days.
    
    Admin only.
    """
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    service = get_snapshot_service()
    result = await service.cleanup_old_snapshots(days)
    
    return {
        "message": f"Cleaned up snapshots older than {days} days",
        **result
    }


@snapshot_router.get("/calendar/trading-day")
async def get_trading_day_info(
    user: dict = Depends(get_current_user())
):
    """
    Get NYSE trading day information.
    
    Shows last trading day, whether today is a trading day, etc.
    """
    service = get_snapshot_service()
    
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    ltd = service.get_last_trading_day(now)
    is_trading = service.is_trading_day(now)
    market_close = service.get_market_close_time(ltd)
    
    return {
        "current_time_utc": now.isoformat(),
        "last_trading_day": ltd.strftime('%Y-%m-%d'),
        "is_today_trading_day": is_trading,
        "market_close_time": market_close.isoformat() if market_close else None,
        "hours_since_close": round((now - market_close).total_seconds() / 3600, 1) if market_close else None
    }
