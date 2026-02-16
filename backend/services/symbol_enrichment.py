"""
Symbol Enrichment Service
=========================
Fetches analyst ratings and other enrichment data for universe symbols.

ARCHITECTURE:
- Runs as a SEPARATE scheduled job (not part of scan pipeline)
- Stores results in symbol_enrichment collection
- Scan endpoints JOIN enrichment data at response time
- NO live Yahoo calls during request/response

Schedule: Daily at 5:00 AM ET (before market open)
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor

import yfinance as yf

logger = logging.getLogger(__name__)


def fetch_analyst_data_sync(symbol: str) -> Dict:
    """
    Fetch analyst recommendation data from Yahoo Finance (blocking call).
    
    Returns analyst rating value (1-5 scale), label, and count.
    """
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        
        # Yahoo provides recommendationMean (1=Strong Buy, 5=Strong Sell)
        rec_mean = info.get("recommendationMean")
        rec_key = info.get("recommendationKey")  # e.g., "buy", "hold", "sell"
        num_analysts = info.get("numberOfAnalystOpinions", 0)
        target_high = info.get("targetHighPrice")
        target_low = info.get("targetLowPrice")
        target_mean = info.get("targetMeanPrice")
        
        # Map recommendationKey to label
        label_map = {
            "strongBuy": "Strong Buy",
            "buy": "Buy",
            "hold": "Hold",
            "sell": "Sell",
            "strongSell": "Strong Sell"
        }
        
        rec_label = label_map.get(rec_key, rec_key.title() if rec_key else None)
        
        return {
            "symbol": symbol,
            "success": True,
            "analyst_rating_value": rec_mean,
            "analyst_rating_label": rec_label,
            "analyst_opinions": num_analysts,
            "target_price_high": target_high,
            "target_price_low": target_low,
            "target_price_mean": target_mean,
            "source": "yahoo"
        }
        
    except Exception as e:
        return {
            "symbol": symbol,
            "success": False,
            "error": str(e)
        }


async def enrich_symbols(
    db,
    symbols: List[str],
    max_workers: int = 5
) -> Dict:
    """
    Enrich a list of symbols with analyst data.
    
    Uses ThreadPoolExecutor for concurrent Yahoo calls.
    Updates symbol_enrichment collection.
    """
    logger.info(f"[ENRICHMENT] Starting enrichment for {len(symbols)} symbols...")
    
    enriched = 0
    failed = 0
    
    loop = asyncio.get_event_loop()
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Batch symbols to avoid rate limiting
        batch_size = 20
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            
            # Fetch analyst data concurrently
            futures = [
                loop.run_in_executor(executor, fetch_analyst_data_sync, symbol)
                for symbol in batch
            ]
            
            results = await asyncio.gather(*futures)
            
            # Upsert results to MongoDB
            for result in results:
                symbol = result["symbol"]
                
                if result.get("success"):
                    doc = {
                        "symbol": symbol,
                        "analyst_rating_value": result.get("analyst_rating_value"),
                        "analyst_rating_label": result.get("analyst_rating_label"),
                        "analyst_opinions": result.get("analyst_opinions"),
                        "target_price_high": result.get("target_price_high"),
                        "target_price_low": result.get("target_price_low"),
                        "target_price_mean": result.get("target_price_mean"),
                        "source": "yahoo",
                        "as_of": datetime.now(timezone.utc),
                        "updated_at": datetime.now(timezone.utc)
                    }
                    
                    await db.symbol_enrichment.update_one(
                        {"symbol": symbol},
                        {"$set": doc},
                        upsert=True
                    )
                    enriched += 1
                else:
                    failed += 1
                    logger.debug(f"[ENRICHMENT] Failed for {symbol}: {result.get('error')}")
            
            # Rate limit between batches
            await asyncio.sleep(1)
    
    logger.info(f"[ENRICHMENT] Completed: {enriched} enriched, {failed} failed")
    
    return {
        "total": len(symbols),
        "enriched": enriched,
        "failed": failed,
        "completed_at": datetime.now(timezone.utc)
    }


async def run_enrichment_job(db) -> Dict:
    """
    Run the full enrichment job for all universe symbols.
    
    Called by APScheduler daily at 5:00 AM ET.
    """
    from services.universe_builder import get_scan_universe
    
    # Get current universe symbols
    symbols = get_scan_universe()
    
    logger.info(f"[ENRICHMENT] Running enrichment job for {len(symbols)} symbols...")
    
    result = await enrich_symbols(db, symbols)
    
    # Create indexes for fast lookup
    await db.symbol_enrichment.create_index("symbol", unique=True)
    await db.symbol_enrichment.create_index("updated_at")
    
    return result


async def get_enrichment(db, symbol: str) -> Optional[Dict]:
    """
    Get enrichment data for a symbol.
    
    Used by scan endpoints to join analyst ratings.
    """
    return await db.symbol_enrichment.find_one(
        {"symbol": symbol},
        {"_id": 0}
    )


async def get_enrichments_batch(db, symbols: List[str]) -> Dict[str, Dict]:
    """
    Get enrichment data for multiple symbols.
    
    Returns dict mapping symbol -> enrichment data.
    """
    cursor = db.symbol_enrichment.find(
        {"symbol": {"$in": symbols}},
        {"_id": 0}
    )
    
    enrichments = await cursor.to_list(length=len(symbols))
    
    return {e["symbol"]: e for e in enrichments}
