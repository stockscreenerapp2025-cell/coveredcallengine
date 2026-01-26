"""
Migration Script: Legacy Snapshots to EOD Market Close Contract
================================================================

ADR-001 COMPLIANT

This script migrates data from:
- stock_snapshots -> eod_market_close
- option_chain_snapshots -> eod_options_chain

Run this ONCE to initialize the canonical EOD collections.
After migration, new data will be ingested via the scheduled 04:05 PM ET job.

Usage:
    python -m scripts.migrate_to_eod_contract
"""

import asyncio
import logging
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
import os
from pathlib import Path
from dotenv import load_dotenv
import uuid

# Load environment
ROOT_DIR = Path(__file__).parent.parent
load_dotenv(ROOT_DIR / '.env')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def migrate_stock_snapshots(db):
    """Migrate stock_snapshots to eod_market_close."""
    logger.info("Starting stock snapshot migration...")
    
    migrated = 0
    skipped = 0
    errors = 0
    
    cursor = db.stock_snapshots.find({"completeness_flag": True}, {"_id": 0})
    
    async for snapshot in cursor:
        try:
            symbol = snapshot.get("symbol")
            trade_date = snapshot.get("stock_price_trade_date") or snapshot.get("snapshot_trade_date")
            price = snapshot.get("stock_close_price") or snapshot.get("price")
            
            if not symbol or not trade_date or not price:
                skipped += 1
                continue
            
            # Check if already exists in EOD
            existing = await db.eod_market_close.find_one({
                "symbol": symbol,
                "trade_date": trade_date,
                "is_final": True
            })
            
            if existing:
                skipped += 1
                continue
            
            # Build canonical timestamp (04:05 PM ET)
            from pytz import timezone as pytz_tz
            et = pytz_tz('America/New_York')
            dt = datetime.strptime(trade_date, '%Y-%m-%d')
            canonical_dt = et.localize(dt.replace(hour=16, minute=5, second=0, microsecond=0))
            
            # Create EOD document
            eod_doc = {
                "symbol": symbol.upper(),
                "trade_date": trade_date,
                "market_close_price": price,
                "market_close_timestamp": canonical_dt.isoformat(),
                "source": snapshot.get("source", "yahoo"),
                "ingestion_run_id": f"migration_{datetime.now(timezone.utc).strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}",
                "is_final": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "metadata": {
                    "volume": snapshot.get("volume"),
                    "market_cap": snapshot.get("market_cap"),
                    "avg_volume": snapshot.get("avg_volume"),
                    "earnings_date": snapshot.get("earnings_date"),
                    "analyst_rating": snapshot.get("analyst_rating")
                },
                "migrated_from": "stock_snapshots",
                "migration_timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            await db.eod_market_close.update_one(
                {"symbol": symbol.upper(), "trade_date": trade_date},
                {"$set": eod_doc},
                upsert=True
            )
            
            migrated += 1
            
        except Exception as e:
            errors += 1
            logger.error(f"Error migrating {snapshot.get('symbol')}: {e}")
    
    logger.info(f"Stock migration complete: {migrated} migrated, {skipped} skipped, {errors} errors")
    return {"migrated": migrated, "skipped": skipped, "errors": errors}


async def migrate_option_chain_snapshots(db):
    """Migrate option_chain_snapshots to eod_options_chain."""
    logger.info("Starting options chain migration...")
    
    migrated = 0
    skipped = 0
    errors = 0
    
    cursor = db.option_chain_snapshots.find({"completeness_flag": True}, {"_id": 0})
    
    async for snapshot in cursor:
        try:
            symbol = snapshot.get("symbol")
            trade_date = snapshot.get("snapshot_trade_date") or snapshot.get("options_data_trade_day")
            stock_price = snapshot.get("stock_price")
            
            if not symbol or not trade_date or not stock_price:
                skipped += 1
                continue
            
            # Check if already exists in EOD
            existing = await db.eod_options_chain.find_one({
                "symbol": symbol,
                "trade_date": trade_date,
                "is_final": True
            })
            
            if existing:
                skipped += 1
                continue
            
            # Build canonical timestamp
            from pytz import timezone as pytz_tz
            et = pytz_tz('America/New_York')
            dt = datetime.strptime(trade_date, '%Y-%m-%d')
            canonical_dt = et.localize(dt.replace(hour=16, minute=5, second=0, microsecond=0))
            
            # Create EOD document
            eod_doc = {
                "symbol": symbol.upper(),
                "trade_date": trade_date,
                "stock_price": stock_price,
                "market_close_timestamp": canonical_dt.isoformat(),
                "ingestion_run_id": f"migration_{datetime.now(timezone.utc).strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}",
                "is_final": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "calls": snapshot.get("calls", []),
                "puts": snapshot.get("puts", []),
                "expiries": snapshot.get("expiries", []),
                "total_contracts": snapshot.get("total_contracts", 0),
                "valid_contracts": snapshot.get("valid_contracts", 0),
                "source": snapshot.get("source", "yahoo"),
                "migrated_from": "option_chain_snapshots",
                "migration_timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            await db.eod_options_chain.update_one(
                {"symbol": symbol.upper(), "trade_date": trade_date},
                {"$set": eod_doc},
                upsert=True
            )
            
            migrated += 1
            
        except Exception as e:
            errors += 1
            logger.error(f"Error migrating options for {snapshot.get('symbol')}: {e}")
    
    logger.info(f"Options migration complete: {migrated} migrated, {skipped} skipped, {errors} errors")
    return {"migrated": migrated, "skipped": skipped, "errors": errors}


async def create_indexes(db):
    """Create indexes for EOD collections."""
    logger.info("Creating indexes...")
    
    # eod_market_close indexes
    await db.eod_market_close.create_index([("symbol", 1), ("trade_date", 1)], unique=True)
    await db.eod_market_close.create_index([("trade_date", 1), ("is_final", 1)])
    await db.eod_market_close.create_index("ingestion_run_id")
    
    # eod_options_chain indexes
    await db.eod_options_chain.create_index([("symbol", 1), ("trade_date", 1)], unique=True)
    await db.eod_options_chain.create_index([("trade_date", 1), ("is_final", 1)])
    await db.eod_options_chain.create_index("ingestion_run_id")
    
    logger.info("Indexes created")


async def run_migration():
    """Run the full migration."""
    logger.info("=" * 60)
    logger.info("ADR-001: EOD Market Close Contract Migration")
    logger.info("=" * 60)
    
    # Connect to database
    mongo_url = os.environ.get('MONGO_URL')
    db_name = os.environ.get('DB_NAME')
    
    if not mongo_url or not db_name:
        logger.error("MONGO_URL and DB_NAME environment variables required")
        return
    
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    
    try:
        # Create indexes first
        await create_indexes(db)
        
        # Migrate stocks
        stock_result = await migrate_stock_snapshots(db)
        
        # Migrate options
        options_result = await migrate_option_chain_snapshots(db)
        
        # Summary
        logger.info("=" * 60)
        logger.info("Migration Summary")
        logger.info("=" * 60)
        logger.info(f"Stocks:  {stock_result['migrated']} migrated, {stock_result['skipped']} skipped")
        logger.info(f"Options: {options_result['migrated']} migrated, {options_result['skipped']} skipped")
        
        # Verify
        stock_count = await db.eod_market_close.count_documents({"is_final": True})
        options_count = await db.eod_options_chain.count_documents({"is_final": True})
        
        logger.info(f"Total EOD stock records: {stock_count}")
        logger.info(f"Total EOD options records: {options_count}")
        logger.info("=" * 60)
        
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(run_migration())
