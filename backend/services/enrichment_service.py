"""
Enrichment Service - Unified IV Rank & Analyst Data Enrichment
==============================================================

This service provides a SINGLE enrichment function that adds:
1. IV Rank (using lightweight chain percentile method)
2. Analyst data (rating, opinions, target prices)

MUST be applied at the LAST STEP before returning results from:
- Dashboard Top 10
- Custom CC scan
- Watchlist
- Simulator

RULE: Overwrite-only-if-missing - if row already has values, keep them.
"""

import logging
from typing import Dict, Any, Optional, List
from concurrent.futures import ThreadPoolExecutor
import asyncio

logger = logging.getLogger(__name__)

# Thread pool for blocking Yahoo calls
_enrichment_executor = ThreadPoolExecutor(max_workers=5)


def _fetch_analyst_data_sync(symbol: str) -> Dict[str, Any]:
    """
    Fetch analyst data from Yahoo Finance (blocking call).
    
    Returns:
        Dict with analyst_rating, analyst_opinions, target prices
    """
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        
        # Analyst rating mapping
        recommendation = info.get("recommendationKey", "")
        rating_map = {
            "strong_buy": "Strong Buy",
            "buy": "Buy",
            "hold": "Hold",
            "underperform": "Underperform",
            "sell": "Sell"
        }
        rating = rating_map.get(recommendation)
        if not rating and recommendation:
            rating = recommendation.replace("_", " ").title()
        
        # Target prices
        target_mean = info.get("targetMeanPrice")
        target_high = info.get("targetHighPrice")
        target_low = info.get("targetLowPrice")
        
        # Number of analyst opinions
        num_analysts = info.get("numberOfAnalystOpinions", 0)
        
        return {
            "analyst_rating": rating,
            "analyst_opinions": num_analysts if num_analysts else None,
            "target_price_mean": round(target_mean, 2) if target_mean else None,
            "target_price_high": round(target_high, 2) if target_high else None,
            "target_price_low": round(target_low, 2) if target_low else None,
            "_source": "yahoo"
        }
    except Exception as e:
        logger.debug(f"[ENRICHMENT] Analyst fetch failed for {symbol}: {e}")
        return {
            "analyst_rating": None,
            "analyst_opinions": None,
            "target_price_mean": None,
            "target_price_high": None,
            "target_price_low": None,
            "_source": "none"
        }


def _compute_iv_rank_from_chain(
    symbol: str,
    stock_price: float,
    row_iv: Optional[float],
    expiry: Optional[str]
) -> Dict[str, Any]:
    """
    Compute IV Rank using lightweight chain percentile method.
    
    Method:
    1. Get option chain for the same expiry (or nearest if not specified)
    2. Filter strikes within ±15% of spot
    3. Compute percentile rank of row's IV among chain IVs
    4. Require at least 20 valid IV points
    
    Returns:
        Dict with iv_rank and metadata
    """
    try:
        import yfinance as yf
        import numpy as np
        
        if not stock_price or stock_price <= 0:
            return {"iv_rank": None, "_source": "none", "_reason": "no_stock_price"}
        
        ticker = yf.Ticker(symbol)
        
        # Get available expirations
        try:
            expirations = ticker.options
        except Exception:
            return {"iv_rank": None, "_source": "none", "_reason": "no_expirations"}
        
        if not expirations:
            return {"iv_rank": None, "_source": "none", "_reason": "no_expirations"}
        
        # Select expiration
        target_expiry = expiry if expiry and expiry in expirations else expirations[0]
        
        # Get option chain
        try:
            chain = ticker.option_chain(target_expiry)
        except Exception:
            return {"iv_rank": None, "_source": "none", "_reason": "chain_fetch_failed"}
        
        # Combine calls and puts
        all_options = []
        if chain.calls is not None and len(chain.calls) > 0:
            all_options.extend(chain.calls.to_dict('records'))
        if chain.puts is not None and len(chain.puts) > 0:
            all_options.extend(chain.puts.to_dict('records'))
        
        if not all_options:
            return {"iv_rank": None, "_source": "none", "_reason": "empty_chain"}
        
        # Filter strikes within ±15% of spot
        strike_min = stock_price * 0.85
        strike_max = stock_price * 1.15
        
        chain_ivs = []
        for opt in all_options:
            strike = opt.get("strike", 0)
            iv = opt.get("impliedVolatility", 0)
            
            if strike_min <= strike <= strike_max and iv and iv > 0.01 and iv < 5.0:
                chain_ivs.append(iv)
        
        # Require at least 20 valid IV points
        if len(chain_ivs) < 20:
            return {
                "iv_rank": None, 
                "_source": "none", 
                "_reason": f"insufficient_samples_{len(chain_ivs)}"
            }
        
        # Determine the IV to rank
        if row_iv and row_iv > 0.01:
            target_iv = row_iv
        else:
            # Use ATM IV (median of chain)
            target_iv = np.median(chain_ivs)
        
        # Compute percentile rank
        chain_ivs_arr = np.array(chain_ivs)
        rank = (np.sum(chain_ivs_arr < target_iv) / len(chain_ivs_arr)) * 100
        
        return {
            "iv_rank": round(rank, 1),
            "_source": "chain_percentile",
            "_samples": len(chain_ivs),
            "_target_iv": round(target_iv, 4)
        }
        
    except Exception as e:
        logger.debug(f"[ENRICHMENT] IV rank computation failed for {symbol}: {e}")
        return {"iv_rank": None, "_source": "none", "_reason": str(e)[:50]}


def enrich_row(
    symbol: str,
    row: Dict[str, Any],
    *,
    stock_price: Optional[float] = None,
    expiry: Optional[str] = None,
    strike: Optional[float] = None,
    iv: Optional[float] = None,
    skip_analyst: bool = False,
    skip_iv_rank: bool = False
) -> Dict[str, Any]:
    """
    Enrich a single row with IV Rank and Analyst data.
    
    MUST be called at the LAST STEP before returning results.
    
    Args:
        symbol: Stock symbol
        row: The row dict to enrich
        stock_price: Current stock price (for IV rank computation)
        expiry: Option expiry date (for IV rank computation)
        strike: Option strike price (optional)
        iv: Row's IV value (for IV rank computation)
        skip_analyst: Skip analyst enrichment
        skip_iv_rank: Skip IV rank enrichment
    
    Returns:
        Enriched row dict (modifies in place and returns)
    
    RULE: Overwrite-only-if-missing - existing non-null values are kept.
    """
    enrichment_meta = {
        "enrichment_applied": True,
        "enrichment_sources": {
            "analyst": "none",
            "iv_rank": "none"
        }
    }
    
    # Extract stock_price from row if not provided
    if stock_price is None:
        stock_price = row.get("stock_price") or row.get("current_price") or row.get("price", 0)
    
    # Extract IV from row if not provided
    if iv is None:
        iv = row.get("iv") or row.get("implied_volatility") or row.get("iv_decimal", 0)
        # Handle percentage format
        if iv and iv > 5:
            iv = iv / 100
    
    # Extract expiry from row if not provided
    if expiry is None:
        expiry = row.get("expiry") or row.get("expiration") or row.get("expiration_date")
    
    # -----------------------------------------------------------------
    # ANALYST ENRICHMENT
    # -----------------------------------------------------------------
    if not skip_analyst:
        # Only fetch if any analyst field is missing
        needs_analyst = (
            row.get("analyst_rating") is None or
            row.get("analyst_opinions") is None or
            row.get("target_price_mean") is None
        )
        
        if needs_analyst:
            analyst_data = _fetch_analyst_data_sync(symbol)
            enrichment_meta["enrichment_sources"]["analyst"] = analyst_data.get("_source", "none")
            
            # Overwrite-only-if-missing
            if row.get("analyst_rating") is None:
                row["analyst_rating"] = analyst_data.get("analyst_rating")
            if row.get("analyst_opinions") is None:
                row["analyst_opinions"] = analyst_data.get("analyst_opinions")
            if row.get("target_price_mean") is None:
                row["target_price_mean"] = analyst_data.get("target_price_mean")
            if row.get("target_price_high") is None:
                row["target_price_high"] = analyst_data.get("target_price_high")
            if row.get("target_price_low") is None:
                row["target_price_low"] = analyst_data.get("target_price_low")
        else:
            enrichment_meta["enrichment_sources"]["analyst"] = "existing"
    
    # -----------------------------------------------------------------
    # IV RANK ENRICHMENT
    # -----------------------------------------------------------------
    if not skip_iv_rank:
        # Only compute if iv_rank is missing or 0
        current_iv_rank = row.get("iv_rank")
        needs_iv_rank = current_iv_rank is None or current_iv_rank == 0
        
        if needs_iv_rank:
            iv_data = _compute_iv_rank_from_chain(symbol, stock_price, iv, expiry)
            enrichment_meta["enrichment_sources"]["iv_rank"] = iv_data.get("_source", "none")
            
            if iv_data.get("iv_rank") is not None:
                row["iv_rank"] = iv_data["iv_rank"]
        else:
            enrichment_meta["enrichment_sources"]["iv_rank"] = "existing"
    
    # Add enrichment metadata
    row["_enrichment_meta"] = enrichment_meta
    
    return row


async def enrich_row_async(
    symbol: str,
    row: Dict[str, Any],
    *,
    stock_price: Optional[float] = None,
    expiry: Optional[str] = None,
    strike: Optional[float] = None,
    iv: Optional[float] = None,
    skip_analyst: bool = False,
    skip_iv_rank: bool = False
) -> Dict[str, Any]:
    """
    Async version of enrich_row - runs enrichment in thread pool.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _enrichment_executor,
        lambda: enrich_row(
            symbol, row,
            stock_price=stock_price,
            expiry=expiry,
            strike=strike,
            iv=iv,
            skip_analyst=skip_analyst,
            skip_iv_rank=skip_iv_rank
        )
    )


async def enrich_rows_batch(
    rows: List[Dict[str, Any]],
    *,
    skip_analyst: bool = False,
    skip_iv_rank: bool = False
) -> List[Dict[str, Any]]:
    """
    Enrich multiple rows in parallel.
    
    Each row must have 'symbol' key.
    """
    if not rows:
        return rows
    
    tasks = []
    for row in rows:
        symbol = row.get("symbol", "")
        if not symbol:
            row["_enrichment_meta"] = {
                "enrichment_applied": False,
                "enrichment_sources": {"analyst": "none", "iv_rank": "none"}
            }
            # Skip enrichment for rows without symbol
            continue
        else:
            tasks.append(enrich_row_async(
                symbol, row,
                skip_analyst=skip_analyst,
                skip_iv_rank=skip_iv_rank
            ))
    
    if tasks:
        await asyncio.gather(*tasks)
    
    return rows


def strip_enrichment_debug(row: Dict[str, Any], include_debug: bool = False) -> Dict[str, Any]:
    """
    Remove or keep enrichment debug metadata based on flag.
    
    Args:
        row: The enriched row
        include_debug: If True, convert _enrichment_meta to enrichment_* fields
                      If False, remove _enrichment_meta entirely
    
    Returns:
        Row with debug fields handled
    """
    meta = row.pop("_enrichment_meta", None)
    
    if include_debug and meta:
        row["enrichment_applied"] = meta.get("enrichment_applied", False)
        row["enrichment_sources"] = meta.get("enrichment_sources", {})
    
    return row
