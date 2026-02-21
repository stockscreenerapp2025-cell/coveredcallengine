"""
EOD Routes - Market Close Price Contract API
=============================================

ADR-001 COMPLIANT

Endpoints for managing canonical EOD market close data:
- Ingestion triggers (admin only)
- Data retrieval (authenticated)
- Status and health checks

These endpoints replace the legacy /api/snapshots/* endpoints
for snapshot-based modules.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Body
from typing import List, Optional
import logging
import os
from datetime import datetime, timezone

from services.eod_ingestion_service import (
    EODIngestionService,
    EODPriceContract,
    EODPriceNotFoundError,
    EODOptionsNotFoundError
)
from utils.auth import get_current_user
from database import db

logger = logging.getLogger(__name__)

eod_router = APIRouter(prefix="/api/eod", tags=["EOD Market Close"])

# Default symbols for CC screening
EOD_SYMBOLS = [
    # Tech
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA", "AMD", "INTC", "CRM",
    # Finance
    "JPM", "BAC", "WFC", "MS", "C", "USB", "PNC", "SCHW",
    # Consumer
    "WMT", "HD", "NKE", "SBUX", "MCD", "DIS", "CMCSA", "VZ", "T",
    # Healthcare
    "JNJ", "UNH", "PFE", "MRK", "ABBV", "BMY", "GILD", "LLY",
    # Energy
    "XOM", "CVX", "COP", "SLB", "EOG", "OXY", "DVN", "HAL", "MPC",
    # Industrial
    "CAT", "DE", "BA", "HON", "GE", "UPS", "RTX",
    # Other
    "PLTR", "SOFI", "COIN", "HOOD", "RIVN", "LCID", "NIO", "UBER", "LYFT",
    "AAL", "DAL", "UAL", "CCL", "NCLH", "MGM", "WYNN",
    # ETFs
    "SPY", "QQQ", "IWM", "SLV"
]

# Singleton services
_eod_ingestion_service: Optional[EODIngestionService] = None
_eod_price_contract: Optional[EODPriceContract] = None


def get_eod_ingestion_service() -> EODIngestionService:
    """Get or create EOD ingestion service singleton."""
    global _eod_ingestion_service
    if _eod_ingestion_service is None:
        polygon_key = os.environ.get('POLYGON_API_KEY') or os.environ.get('MASSIVE_POLYGON_API_KEY')
        _eod_ingestion_service = EODIngestionService(db, polygon_key)
    return _eod_ingestion_service


def get_eod_price_contract() -> EODPriceContract:
    """Get or create EOD price contract singleton."""
    global _eod_price_contract
    if _eod_price_contract is None:
        _eod_price_contract = EODPriceContract(db)
    return _eod_price_contract


# ==================== INGESTION ENDPOINTS (ADMIN ONLY) ====================

@eod_router.post("/ingest/stock/{symbol}")
async def ingest_eod_stock(
    symbol: str,
    trade_date: str = Query(None, description="Trading day (YYYY-MM-DD), defaults to LTD"),
    override: bool = Query(False, description="Override existing final data"),
    user: dict = Depends(get_current_user)
):
    """
    Ingest canonical EOD stock price for a single symbol.
    
    ADR-001 COMPLIANT:
    - Captures market close at 04:05 PM ET
    - Idempotent (no-op if already final without override)
    - Uses yfinance history() for actual NYSE close
    """
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    service = get_eod_ingestion_service()
    result = await service.ingest_eod_stock_price(symbol, trade_date, override)
    
    return result


@eod_router.post("/ingest/options/{symbol}")
async def ingest_eod_options(
    symbol: str,
    trade_date: str = Query(None, description="Trading day (YYYY-MM-DD)"),
    override: bool = Query(False, description="Override existing final data"),
    user: dict = Depends(get_current_user)
):
    """
    Ingest canonical EOD options chain for a symbol.
    
    ADR-001 COMPLIANT:
    - Requires stock EOD to exist first
    - Uses stock's market_close_price for cross-validation
    - Idempotent
    """
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    service = get_eod_ingestion_service()
    contract = get_eod_price_contract()
    
    # Get stock price from EOD contract
    try:
        stock_price, _ = await contract.get_market_close_price(symbol, trade_date)
    except EODPriceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    
    result = await service.ingest_eod_options_chain(symbol, stock_price, trade_date, override)
    
    return result


@eod_router.post("/ingest/full/{symbol}")
async def ingest_eod_full(
    symbol: str,
    trade_date: str = Query(None, description="Trading day (YYYY-MM-DD)"),
    override: bool = Query(False, description="Override existing final data"),
    user: dict = Depends(get_current_user)
):
    """
    Ingest both stock and options EOD data for a symbol.
    
    This is the recommended way to ingest complete EOD data.
    """
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    service = get_eod_ingestion_service()
    
    # Stock first
    stock_result = await service.ingest_eod_stock_price(symbol, trade_date, override)
    
    if stock_result["status"] not in ["INGESTED", "ALREADY_FINAL"]:
        return {
            "symbol": symbol,
            "stock": stock_result,
            "options": None,
            "error": "Stock ingestion failed, options skipped"
        }
    
    # Options
    stock_price = stock_result.get("market_close_price", 0)
    if stock_price > 0:
        options_result = await service.ingest_eod_options_chain(
            symbol, stock_price, trade_date, override
        )
    else:
        options_result = {"status": "SKIPPED", "error": "No stock price available"}
    
    return {
        "symbol": symbol,
        "trade_date": stock_result.get("trade_date"),
        "stock": stock_result,
        "options": options_result
    }


@eod_router.post("/ingest/batch")
async def ingest_eod_batch(
    symbols: List[str] = Body(None, embed=True),
    use_defaults: bool = Query(False, description="Use default symbol list"),
    trade_date: str = Query(None, description="Trading day (YYYY-MM-DD)"),
    override: bool = Query(False, description="Override existing final data"),
    background_tasks: BackgroundTasks = None,
    user: dict = Depends(get_current_user)
):
    """
    Batch ingest EOD data for multiple symbols.
    
    For large batches (>10 symbols), runs in background.
    """
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    target_symbols = symbols if symbols else (EOD_SYMBOLS if use_defaults else [])
    
    if not target_symbols:
        raise HTTPException(status_code=400, detail="No symbols provided")
    
    service = get_eod_ingestion_service()
    
    # Large batches run in background
    if len(target_symbols) > 10 and background_tasks:
        background_tasks.add_task(service.ingest_all_eod, target_symbols, trade_date, override)
        return {
            "status": "STARTED",
            "message": f"Ingesting {len(target_symbols)} symbols in background",
            "symbols_count": len(target_symbols),
            "trade_date": trade_date or "LTD",
            "triggered_at": datetime.now(timezone.utc).isoformat(),
            "triggered_by": user.get("email")
        }
    
    # Small batches run synchronously
    result = await service.ingest_all_eod(target_symbols, trade_date, override)
    return result


@eod_router.post("/ingest/scheduled")
async def trigger_scheduled_ingestion(
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user)
):
    """
    Manually trigger the scheduled EOD ingestion.
    
    This mimics what the 04:05 PM ET scheduler does.
    """
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    service = get_eod_ingestion_service()
    
    # Run in background
    background_tasks.add_task(service.ingest_all_eod, EOD_SYMBOLS)
    
    return {
        "status": "STARTED",
        "message": f"Scheduled ingestion triggered for {len(EOD_SYMBOLS)} symbols",
        "triggered_at": datetime.now(timezone.utc).isoformat(),
        "triggered_by": user.get("email")
    }


# ==================== DATA RETRIEVAL ENDPOINTS ====================

@eod_router.get("/price/{symbol}")
async def get_eod_price(
    symbol: str,
    trade_date: str = Query(None, description="Trading day (YYYY-MM-DD)"),
    user: dict = Depends(get_current_user)
):
    """
    Get canonical EOD market close price.
    
    ADR-001 COMPLIANT:
    - Returns market_close_price only (never live data)
    - Fails fast if data not available
    """
    contract = get_eod_price_contract()
    
    try:
        price, doc = await contract.get_market_close_price(symbol, trade_date)
        return {
            "symbol": doc["symbol"],
            "trade_date": doc["trade_date"],
            "market_close_price": price,
            "market_close_timestamp": doc["market_close_timestamp"],
            "source": doc["source"],
            "is_final": doc["is_final"],
            "metadata": doc.get("metadata", {})
        }
    except EODPriceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@eod_router.get("/options/{symbol}")
async def get_eod_options_summary(
    symbol: str,
    trade_date: str = Query(None, description="Trading day (YYYY-MM-DD)"),
    user: dict = Depends(get_current_user)
):
    """
    Get EOD options chain summary (without full contract arrays).
    
    For full chain data, use /calls or /leaps endpoints.
    """
    contract = get_eod_price_contract()
    
    try:
        chain = await contract.get_options_chain(symbol, trade_date)
        return {
            "symbol": chain["symbol"],
            "trade_date": chain["trade_date"],
            "stock_price": chain["stock_price"],
            "market_close_timestamp": chain["market_close_timestamp"],
            "is_final": chain["is_final"],
            "expiries_count": len(chain.get("expiries", [])),
            "calls_count": len(chain.get("calls", [])),
            "puts_count": len(chain.get("puts", [])),
            "valid_contracts": chain.get("valid_contracts", 0),
            "total_contracts": chain.get("total_contracts", 0),
            "source": chain.get("source")
        }
    except EODOptionsNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@eod_router.get("/calls/{symbol}")
async def get_eod_valid_calls(
    symbol: str,
    trade_date: str = Query(None, description="Trading day (YYYY-MM-DD)"),
    min_dte: int = Query(7, ge=1),
    max_dte: int = Query(45, le=365),
    min_strike_pct: float = Query(1.0, ge=0.8),
    max_strike_pct: float = Query(1.15, le=1.5),
    user: dict = Depends(get_current_user)
):
    """
    Get valid call options for CC scanning from EOD data.
    
    ADR-001 COMPLIANT:
    - Returns BID price as premium (SELL leg)
    - Uses canonical EOD data only
    """
    contract = get_eod_price_contract()
    
    try:
        calls = await contract.get_valid_calls_for_scan(
            symbol,
            trade_date,
            min_dte=min_dte,
            max_dte=max_dte,
            min_strike_pct=min_strike_pct,
            max_strike_pct=max_strike_pct
        )
        return {
            "symbol": symbol,
            "trade_date": trade_date,
            "count": len(calls),
            "contracts": calls,
            "pricing_rule": "BID only (SELL leg)"
        }
    except EODOptionsNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@eod_router.get("/leaps/{symbol}")
async def get_eod_valid_leaps(
    symbol: str,
    trade_date: str = Query(None, description="Trading day (YYYY-MM-DD)"),
    min_dte: int = Query(365, ge=180),
    max_dte: int = Query(730, le=1095),
    min_delta: float = Query(0.70, ge=0.50),
    min_oi: int = Query(500, ge=0),
    user: dict = Depends(get_current_user)
):
    """
    Get valid LEAP options for PMCC scanning from EOD data.
    
    ADR-001 COMPLIANT:
    - Returns ASK price as premium (BUY leg)
    - Uses canonical EOD data only
    """
    contract = get_eod_price_contract()
    
    try:
        leaps = await contract.get_valid_leaps_for_pmcc(
            symbol,
            trade_date,
            min_dte=min_dte,
            max_dte=max_dte,
            min_delta=min_delta,
            min_oi=min_oi
        )
        return {
            "symbol": symbol,
            "trade_date": trade_date,
            "count": len(leaps),
            "contracts": leaps,
            "pricing_rule": "ASK only (BUY leg)"
        }
    except EODOptionsNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ==================== STATUS & ADMIN ENDPOINTS ====================

@eod_router.get("/status")
async def get_eod_status(
    trade_date: str = Query(None, description="Filter by trading day"),
    user: dict = Depends(get_current_user)
):
    """
    Get EOD data status for admin dashboard.
    """
    contract = get_eod_price_contract()
    status = await contract.get_eod_status(trade_date)
    
    return {
        **status,
        "contract_version": "ADR-001",
        "checked_at": datetime.now(timezone.utc).isoformat()
    }


@eod_router.get("/symbols")
async def get_eod_available_symbols(
    trade_date: str = Query(None, description="Filter by trading day"),
    user: dict = Depends(get_current_user)
):
    """
    Get list of symbols with final EOD data available.
    """
    query = {"is_final": True}
    if trade_date:
        query["trade_date"] = trade_date
    
    cursor = db.eod_market_close.find(
        query,
        {"_id": 0, "symbol": 1, "trade_date": 1, "market_close_price": 1}
    ).sort("symbol", 1)
    
    symbols = await cursor.to_list(500)
    
    return {
        "count": len(symbols),
        "symbols": symbols,
        "default_symbols": EOD_SYMBOLS,
        "trade_date_filter": trade_date
    }


@eod_router.get("/calendar/trading-day")
async def get_trading_day_info(
    user: dict = Depends(get_current_user)
):
    """
    Get NYSE trading day information.
    """
    service = get_eod_ingestion_service()
    
    now = datetime.now(timezone.utc)
    ltd = service.get_last_trading_day(now)
    is_trading = service.is_trading_day(now)
    canonical_timestamp = service.get_canonical_close_timestamp(ltd.strftime('%Y-%m-%d'))
    
    return {
        "current_time_utc": now.isoformat(),
        "last_trading_day": ltd.strftime('%Y-%m-%d'),
        "is_today_trading_day": is_trading,
        "canonical_close_timestamp": canonical_timestamp,
        "contract_timing": "04:05 PM ET"
    }


@eod_router.get("/health")
async def eod_health_check():
    """
    Health check for EOD data system.
    
    No auth required - used by monitoring.
    """
    try:
        # Check collections exist and have data
        stock_count = await db.eod_market_close.count_documents({"is_final": True})
        options_count = await db.eod_options_chain.count_documents({"is_final": True})
        
        # Get latest trade date
        latest = await db.eod_market_close.find_one(
            {"is_final": True},
            {"_id": 0, "trade_date": 1},
            sort=[("trade_date", -1)]
        )
        
        return {
            "status": "healthy" if stock_count > 0 else "empty",
            "stock_records": stock_count,
            "options_records": options_count,
            "latest_trade_date": latest.get("trade_date") if latest else None,
            "contract_version": "ADR-001",
            "checked_at": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "checked_at": datetime.now(timezone.utc).isoformat()
        }
