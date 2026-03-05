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


def _calc_rsi(closes: list, period: int = 14):
    """Calculate RSI from a list of closing prices (oldest first)."""
    if len(closes) < period + 1:
        return None
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    recent = changes[-period:]
    gains = [c for c in recent if c > 0]
    losses = [abs(c) for c in recent if c < 0]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period or 0.001
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def _calc_ema(prices: list, period: int) -> float:
    """Calculate EMA from a list of prices (oldest first)."""
    k = 2 / (period + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = p * k + ema * (1 - k)
    return ema


def _calc_macd_signal(closes: list):
    """
    Calculate MACD signal direction (bullish/bearish) from closing prices (oldest first).
    Uses 12/26 EMA for MACD line, 9-period EMA for signal line.
    """
    if len(closes) < 35:
        return None
    # Build MACD line values for last 9 bars to compute signal EMA
    macd_values = []
    start = max(26, len(closes) - 9)
    for i in range(start, len(closes)):
        subset = closes[:i + 1]
        if len(subset) >= 26:
            macd_values.append(_calc_ema(subset, 12) - _calc_ema(subset, 26))
    if len(macd_values) < 2:
        return None
    signal_ema = macd_values[0]
    k = 2 / 10  # 9-period EMA
    for m in macd_values[1:]:
        signal_ema = m * k + signal_ema * (1 - k)
    return "bullish" if macd_values[-1] > signal_ema else "bearish"


def _calc_adx(highs: list, lows: list, closes: list, period: int = 14):
    """
    Calculate ADX using Wilder's smoothing method.
    Returns (adx_value, trend_strength_label).
    """
    if len(closes) < period * 2 + 1:
        return None, None
    tr_values, plus_dm, minus_dm = [], [], []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        tr_values.append(tr)
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(up if up > down and up > 0 else 0)
        minus_dm.append(down if down > up and down > 0 else 0)
    if len(tr_values) < period:
        return None, None
    atr = sum(tr_values[:period])
    spdm = sum(plus_dm[:period])
    smdm = sum(minus_dm[:period])
    dx_values = []
    for i in range(period, len(tr_values)):
        atr = atr - atr / period + tr_values[i]
        spdm = spdm - spdm / period + plus_dm[i]
        smdm = smdm - smdm / period + minus_dm[i]
        pdi = 100 * spdm / atr if atr > 0 else 0
        mdi = 100 * smdm / atr if atr > 0 else 0
        di_sum = pdi + mdi
        dx_values.append(100 * abs(pdi - mdi) / di_sum if di_sum > 0 else 0)
    if not dx_values:
        return None, None
    adx = sum(dx_values[:period]) / period if len(dx_values) >= period else sum(dx_values) / len(dx_values)
    for i in range(period, len(dx_values)):
        adx = (adx * (period - 1) + dx_values[i]) / period
    adx = round(adx, 1)
    label = "strong" if adx > 25 else "moderate" if adx >= 15 else "weak"
    return adx, label


def fetch_analyst_data_sync(symbol: str) -> Dict:
    """
    Fetch analyst + technical indicator data from Yahoo Finance (blocking call).

    Returns analyst rating, SMA, RSI, MACD signal, ADX, and overall trend.
    """
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info

        # Yahoo provides recommendationMean (1=Strong Buy, 5=Strong Sell)
        rec_mean = info.get("recommendationMean")
        rec_key = info.get("recommendationKey")  # e.g., "buy", "hold", "sell"
        num_analysts = info.get("numberOfAnalystOpinions", 0)

        # Fundamental metrics
        raw_pe = info.get("trailingPE")
        raw_roe = info.get("returnOnEquity")
        pe_ratio = round(raw_pe, 2) if raw_pe and raw_pe > 0 else None
        roe = round(raw_roe * 100, 2) if raw_roe is not None else None
        target_high = info.get("targetHighPrice")
        target_low = info.get("targetLowPrice")
        target_mean = info.get("targetMeanPrice")

        # Map recommendationKey to label (Yahoo returns camelCase or snake_case)
        label_map = {
            "strongBuy": "Strong Buy",
            "strong_buy": "Strong Buy",
            "buy": "Buy",
            "hold": "Hold",
            "sell": "Sell",
            "strongSell": "Strong Sell",
            "strong_sell": "Strong Sell",
            "underperform": "Sell",
            "underweight": "Sell",
        }

        rec_label = label_map.get(rec_key, rec_key.replace("_", " ").title() if rec_key else None)

        # SMA data — available directly from yfinance info (no extra API call)
        fifty_day_avg = info.get("fiftyDayAverage")
        two_hundred_day_avg = info.get("twoHundredDayAverage")
        current_price = info.get("currentPrice") or info.get("regularMarketPrice")

        # --- Technical indicators from price history ---
        rsi = None
        macd_signal = None
        adx = None
        trend_strength = None
        trend = None
        try:
            hist = ticker.history(period="2mo")
            if not hist.empty and len(hist) >= 15:
                closes = hist["Close"].tolist()
                rsi = _calc_rsi(closes)
                macd_signal = _calc_macd_signal(closes)
                if len(hist) >= 29:
                    adx, trend_strength = _calc_adx(
                        hist["High"].tolist(), hist["Low"].tolist(), closes
                    )
                # Overall trend from SMA crossover
                cp = current_price or (closes[-1] if closes else None)
                if cp and fifty_day_avg and two_hundred_day_avg:
                    if cp > fifty_day_avg and fifty_day_avg > two_hundred_day_avg:
                        trend = "bullish"
                    elif cp < fifty_day_avg and fifty_day_avg < two_hundred_day_avg:
                        trend = "bearish"
                    else:
                        trend = "neutral"
        except Exception:
            pass  # Technical data is non-critical; skip on error

        return {
            "symbol": symbol,
            "success": True,
            "analyst_rating_value": rec_mean,
            "analyst_rating_label": rec_label,
            "analyst_opinions": num_analysts,
            "target_price_high": target_high,
            "target_price_low": target_low,
            "target_price_mean": target_mean,
            "fifty_day_avg": fifty_day_avg,
            "two_hundred_day_avg": two_hundred_day_avg,
            "current_price": current_price,
            "rsi": rsi,
            "macd_signal": macd_signal,
            "adx": adx,
            "trend_strength": trend_strength,
            "trend": trend,
            "pe_ratio": pe_ratio,
            "roe": roe,
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
                        "fifty_day_avg": result.get("fifty_day_avg"),
                        "two_hundred_day_avg": result.get("two_hundred_day_avg"),
                        "rsi": result.get("rsi"),
                        "macd_signal": result.get("macd_signal"),
                        "adx": result.get("adx"),
                        "trend_strength": result.get("trend_strength"),
                        "trend": result.get("trend"),
                        "pe_ratio": result.get("pe_ratio"),
                        "roe": result.get("roe"),
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
    from services.universe_builder import get_pmcc_universe_symbols, get_scan_universe

    # Get current universe symbols from pmcc_universe (Nasdaq CSV-based)
    symbols = await get_pmcc_universe_symbols(db)
    if not symbols:
        symbols = get_scan_universe()  # fallback to static tier list
    
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
