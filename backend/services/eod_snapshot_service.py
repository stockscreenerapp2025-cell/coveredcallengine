"""
EOD Market Snapshot Service
===========================

Implements the 4:05 PM ET deterministic snapshot system.

RESPONSIBILITIES:
1. Generate synchronized EOD snapshot at 4:05 PM ET
2. Store complete snapshot to eod_market_snapshot collection
3. Serve snapshot data when system is EOD_LOCKED
4. Block live Yahoo calls after 4:05 PM ET

COLLECTION: eod_market_snapshot
Schema:
{
    "run_id": str,           # Unique run identifier
    "symbol": str,           # Stock/ETF symbol
    "underlying_price": float,
    "option_chain": [...],   # Full option chain at snapshot time
    "pricing_rule_used": str,
    "as_of": datetime,       # 4:05 PM ET timestamp
    "created_at": datetime,
    "trade_date": str,       # YYYY-MM-DD
    "is_final": bool
}
"""

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, Tuple
from zoneinfo import ZoneInfo
from motor.motor_asyncio import AsyncIOMotorDatabase

from utils.market_state import (
    get_system_mode,
    get_last_trading_day,
    now_et,
    is_trading_day,
    EODSnapshotNotAvailableError,
    log_eod_event,
    EOD_LOCK_HOUR,
    EOD_LOCK_MINUTE,
    ET
)

logger = logging.getLogger(__name__)

# Collection name
EOD_SNAPSHOT_COLLECTION = "eod_market_snapshot"

# Universe audit collection (for exclusion tracking)
EOD_SNAPSHOT_AUDIT_COLLECTION = "eod_snapshot_audit"


class EODMarketSnapshotService:
    """
    Service for creating and serving EOD market snapshots.
    
    At 4:05 PM ET:
    - Fetch underlying prices (PREV_CLOSE)
    - Fetch option chains using existing pricing rules
    - Save complete snapshot
    
    After 4:05 PM ET:
    - Serve ONLY from stored snapshot
    - No live Yahoo calls permitted
    """
    
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.collection = db[EOD_SNAPSHOT_COLLECTION]
        self.audit_collection = db[EOD_SNAPSHOT_AUDIT_COLLECTION]
    
    async def ensure_indexes(self):
        """Create indexes for efficient snapshot queries."""
        await self.collection.create_index([("symbol", 1), ("trade_date", 1)], unique=True)
        await self.collection.create_index([("run_id", 1)])
        await self.collection.create_index([("trade_date", 1), ("is_final", 1)])
        await self.collection.create_index("as_of")
        
        await self.audit_collection.create_index([("run_id", 1), ("symbol", 1)])
        await self.audit_collection.create_index("as_of")
    
    def generate_run_id(self, trade_date: str) -> str:
        """Generate unique run ID for snapshot batch."""
        short_uuid = uuid.uuid4().hex[:8]
        return f"eod_snap_{trade_date.replace('-', '')}_{EOD_LOCK_HOUR:02d}{EOD_LOCK_MINUTE:02d}_{short_uuid}"
    
    def get_canonical_timestamp(self, trade_date: str = None) -> datetime:
        """Get the canonical 4:05 PM ET timestamp for snapshot."""
        if trade_date:
            dt = datetime.strptime(trade_date, '%Y-%m-%d')
        else:
            dt = now_et()
        
        return dt.replace(
            hour=EOD_LOCK_HOUR,
            minute=EOD_LOCK_MINUTE,
            second=0,
            microsecond=0,
            tzinfo=ET
        )
    
    async def create_eod_snapshot(
        self,
        symbols: List[str],
        trade_date: str = None,
        api_key: str = None
    ) -> Dict[str, Any]:
        """
        Create complete EOD snapshot for all symbols.
        
        Called at 4:05 PM ET by scheduler.
        
        Args:
            symbols: List of symbols to snapshot
            trade_date: Trade date (defaults to today)
            api_key: API key for data provider (optional)
        
        Returns:
            Dict with run_id, success count, failures, etc.
        """
        from services.data_provider import fetch_stock_quote, fetch_options_chain
        
        if not trade_date:
            trade_date = now_et().strftime('%Y-%m-%d')
        
        run_id = self.generate_run_id(trade_date)
        canonical_timestamp = self.get_canonical_timestamp(trade_date)
        
        logger.info(f"[EOD-SNAPSHOT-START] run_id={run_id} symbols={len(symbols)} trade_date={trade_date}")
        
        results = {
            "run_id": run_id,
            "trade_date": trade_date,
            "as_of": canonical_timestamp.isoformat(),
            "symbols_requested": len(symbols),
            "symbols_success": 0,
            "symbols_failed": 0,
            "failures": [],
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        for symbol in symbols:
            symbol = symbol.upper()
            try:
                # Fetch underlying price
                stock_data = await fetch_stock_quote(symbol, api_key)
                
                if not stock_data or stock_data.get("price", 0) <= 0:
                    await self._log_exclusion(run_id, symbol, "STOCK_PRICE_UNAVAILABLE", "No valid stock price from data provider")
                    results["failures"].append({"symbol": symbol, "reason": "STOCK_PRICE_UNAVAILABLE"})
                    results["symbols_failed"] += 1
                    continue
                
                underlying_price = float(stock_data.get("price", 0))
                
                # Fetch option chain using existing pricing rules
                # Short calls: 7-45 DTE, OTM (95-115% of price)
                option_chain = await fetch_options_chain(
                    symbol=symbol,
                    api_key=api_key,
                    option_type="call",
                    min_dte=7,
                    max_dte=45,
                    current_price=underlying_price
                )
                
                if not option_chain:
                    await self._log_exclusion(run_id, symbol, "OPTIONS_CHAIN_UNAVAILABLE", "No option contracts from data provider")
                    results["failures"].append({"symbol": symbol, "reason": "OPTIONS_CHAIN_UNAVAILABLE"})
                    results["symbols_failed"] += 1
                    continue
                
                # Validate chain - at least one contract with valid bid
                valid_contracts = [opt for opt in option_chain if opt.get("bid", 0) > 0]
                if not valid_contracts:
                    await self._log_exclusion(run_id, symbol, "NO_VALID_BIDS", f"All {len(option_chain)} contracts have zero bid")
                    results["failures"].append({"symbol": symbol, "reason": "NO_VALID_BIDS"})
                    results["symbols_failed"] += 1
                    continue
                
                # Create snapshot document
                snapshot_doc = {
                    "run_id": run_id,
                    "symbol": symbol,
                    "underlying_price": underlying_price,
                    "option_chain": valid_contracts,
                    "option_chain_raw_count": len(option_chain),
                    "option_chain_valid_count": len(valid_contracts),
                    "pricing_rule_used": "BID_ONLY_SELL_LEG",
                    "as_of": canonical_timestamp,
                    "trade_date": trade_date,
                    "is_final": True,
                    "created_at": datetime.now(timezone.utc),
                    "stock_data": {
                        "price": underlying_price,
                        "previous_close": stock_data.get("previous_close", underlying_price),
                        "source": stock_data.get("source", "yahoo"),
                        "close_date": stock_data.get("close_date"),
                    }
                }
                
                # Upsert snapshot (idempotent per symbol+trade_date)
                await self.collection.update_one(
                    {"symbol": symbol, "trade_date": trade_date},
                    {"$set": snapshot_doc},
                    upsert=True
                )
                
                results["symbols_success"] += 1
                logger.debug(f"[EOD-SNAPSHOT] {symbol}: price=${underlying_price:.2f}, contracts={len(valid_contracts)}")
                
            except Exception as e:
                logger.error(f"[EOD-SNAPSHOT-ERROR] {symbol}: {e}")
                await self._log_exclusion(run_id, symbol, "EXCEPTION", str(e))
                results["failures"].append({"symbol": symbol, "reason": str(e)})
                results["symbols_failed"] += 1
        
        # Log completion
        log_eod_event(
            "SNAPSHOT_CREATED",
            run_id=run_id,
            symbols_count=results["symbols_success"],
            failures_count=results["symbols_failed"]
        )
        
        logger.info(f"[EOD-SNAPSHOT-COMPLETE] run_id={run_id} success={results['symbols_success']} failed={results['symbols_failed']}")
        
        return results
    
    async def _log_exclusion(self, run_id: str, symbol: str, reason: str, detail: str):
        """Log symbol exclusion to audit collection."""
        try:
            await self.audit_collection.insert_one({
                "run_id": run_id,
                "symbol": symbol,
                "included": False,
                "exclude_reason": reason,
                "exclude_detail": detail,
                "as_of": datetime.now(timezone.utc)
            })
            log_eod_event("SNAPSHOT_FAILED", symbol=symbol, reason=reason, detail=detail)
        except Exception as e:
            logger.warning(f"Failed to log exclusion for {symbol}: {e}")
    
    async def get_snapshot(
        self,
        symbol: str,
        trade_date: str = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get EOD snapshot for a symbol.
        
        Args:
            symbol: Stock symbol
            trade_date: Trade date (defaults to last trading day)
        
        Returns:
            Snapshot document or None if not found
        """
        symbol = symbol.upper()
        
        if not trade_date:
            trade_date = get_last_trading_day()
        
        snapshot = await self.collection.find_one(
            {"symbol": symbol, "trade_date": trade_date, "is_final": True},
            {"_id": 0}
        )
        
        return snapshot
    
    async def get_option_chain_from_snapshot(
        self,
        symbol: str,
        trade_date: str = None
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Get option chain from EOD snapshot.
        
        Used when system is EOD_LOCKED to serve chain data.
        
        Args:
            symbol: Stock symbol
            trade_date: Trade date (defaults to last trading day)
        
        Returns:
            Tuple of (option_chain, metadata)
        
        Raises:
            EODSnapshotNotAvailableError if snapshot not found
        """
        snapshot = await self.get_snapshot(symbol, trade_date)
        
        if not snapshot:
            raise EODSnapshotNotAvailableError(
                symbol=symbol,
                trade_date=trade_date,
                reason="No finalized EOD snapshot exists for this symbol and date"
            )
        
        metadata = {
            "symbol": symbol,
            "underlying_price": snapshot.get("underlying_price", 0),
            "trade_date": snapshot.get("trade_date"),
            "as_of": snapshot.get("as_of"),
            "run_id": snapshot.get("run_id"),
            "pricing_rule_used": snapshot.get("pricing_rule_used"),
            "is_snapshot_data": True,
            "snapshot_created_at": snapshot.get("created_at"),
            "contracts_count": len(snapshot.get("option_chain", []))
        }
        
        return snapshot.get("option_chain", []), metadata
    
    async def get_underlying_price_from_snapshot(
        self,
        symbol: str,
        trade_date: str = None
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Get underlying price from EOD snapshot.
        
        Used when system is EOD_LOCKED to serve price data.
        
        Args:
            symbol: Stock symbol
            trade_date: Trade date (defaults to last trading day)
        
        Returns:
            Tuple of (price, metadata)
        
        Raises:
            EODSnapshotNotAvailableError if snapshot not found
        """
        snapshot = await self.get_snapshot(symbol, trade_date)
        
        if not snapshot:
            raise EODSnapshotNotAvailableError(
                symbol=symbol,
                trade_date=trade_date,
                reason="No finalized EOD snapshot exists for this symbol and date"
            )
        
        metadata = {
            "symbol": symbol,
            "trade_date": snapshot.get("trade_date"),
            "as_of": snapshot.get("as_of"),
            "run_id": snapshot.get("run_id"),
            "is_snapshot_data": True,
            "stock_data": snapshot.get("stock_data", {})
        }
        
        return float(snapshot.get("underlying_price", 0)), metadata
    
    async def get_snapshot_status(self, trade_date: str = None) -> Dict[str, Any]:
        """Get status of EOD snapshots for a trade date."""
        if not trade_date:
            trade_date = get_last_trading_day()
        
        # Count snapshots
        total = await self.collection.count_documents(
            {"trade_date": trade_date, "is_final": True}
        )
        
        # Get run info
        sample = await self.collection.find_one(
            {"trade_date": trade_date, "is_final": True},
            {"_id": 0, "run_id": 1, "as_of": 1, "created_at": 1}
        )
        
        # Get failed symbols from audit
        failed_count = await self.audit_collection.count_documents(
            {"as_of": {"$gte": datetime.strptime(trade_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)},
             "included": False}
        )
        
        return {
            "trade_date": trade_date,
            "symbols_with_snapshot": total,
            "symbols_failed": failed_count,
            "run_id": sample.get("run_id") if sample else None,
            "as_of": sample.get("as_of").isoformat() if sample and sample.get("as_of") else None,
            "created_at": sample.get("created_at").isoformat() if sample and sample.get("created_at") else None,
            "system_mode": get_system_mode(),
            "checked_at": datetime.now(timezone.utc).isoformat()
        }
    
    async def list_available_symbols(self, trade_date: str = None) -> List[str]:
        """Get list of symbols with available snapshots."""
        if not trade_date:
            trade_date = get_last_trading_day()
        
        cursor = self.collection.find(
            {"trade_date": trade_date, "is_final": True},
            {"_id": 0, "symbol": 1}
        )
        
        symbols = [doc["symbol"] async for doc in cursor]
        return sorted(symbols)


# Singleton instance
_eod_snapshot_service: Optional[EODMarketSnapshotService] = None


def get_eod_snapshot_service(db: AsyncIOMotorDatabase) -> EODMarketSnapshotService:
    """Get or create EOD snapshot service singleton."""
    global _eod_snapshot_service
    if _eod_snapshot_service is None:
        _eod_snapshot_service = EODMarketSnapshotService(db)
    return _eod_snapshot_service
