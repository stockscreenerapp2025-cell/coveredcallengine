"""
Watchlist routes - Enhanced with price tracking and opportunities

DATA FETCHING RULES:
1. STOCK PRICES: Watchlist and Simulator use LIVE intraday prices (regularMarketPrice)
2. OPPORTUNITIES: Fetched LIVE from Yahoo Finance, never cached

This is different from Screener which uses previous close for stock prices.
"""
from fastapi import APIRouter, HTTPException, Depends, Query
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

# Import LIVE price functions for Watchlist (Rule #2)
from services.data_provider import (
    fetch_live_stock_quote,  # LIVE intraday prices for Watchlist
    fetch_live_stock_quotes_batch,  # Batch LIVE prices
    fetch_options_chain,  # LIVE options fetch
    fetch_stock_quote,  # Previous close (for fallback)
    fetch_stock_quotes_batch  # Batch previous close
)

# CCE Volatility & Greeks Correctness - Use shared services
from services.greeks_service import calculate_greeks, normalize_iv_fields
from services.iv_rank_service import get_iv_metrics_for_symbol

# ADR-001: Import EOD Price Contract (for backward compat only)
from services.eod_ingestion_service import (
    EODPriceContract,
    EODPriceNotFoundError,
    EODOptionsNotFoundError
)

watchlist_router = APIRouter(tags=["Watchlist"])


def _get_server_functions():
    """Lazy import to avoid circular dependencies"""
    from server import get_massive_api_key, MOCK_STOCKS
    return get_massive_api_key, MOCK_STOCKS


# ADR-001: EOD Price Contract singleton
_eod_price_contract = None

def _get_eod_contract() -> EODPriceContract:
    """Get or create the EOD Price Contract singleton."""
    global _eod_price_contract
    if _eod_price_contract is None:
        _eod_price_contract = EODPriceContract(db)
    return _eod_price_contract


async def _get_best_opportunity_live(symbol: str, stock_price: float = None) -> dict:
    """
    Get best covered call opportunity using LIVE options data.
    
    DATA RULES COMPLIANT:
    - Options chain fetched LIVE from Yahoo
    - Stock price can be provided or fetched LIVE
    
    CCE VOLATILITY & GREEKS CORRECTNESS:
    - Delta computed via Black-Scholes (not moneyness fallback)
    - IV Rank computed from historical ATM proxy
    """
    try:
        # Get LIVE stock price if not provided
        if not stock_price:
            quote = await fetch_live_stock_quote(symbol)
            if not quote or quote.get("price", 0) <= 0:
                return None
            stock_price = quote["price"]
        
        # Fetch LIVE options chain
        calls = await fetch_options_chain(
            symbol=symbol,
            api_key=None,
            option_type="call",
            max_dte=45,
            min_dte=1,
            current_price=stock_price
        )
        
        if not calls:
            return None
        
        # Compute IV metrics for the symbol (industry-standard IV Rank)
        try:
            iv_metrics = await get_iv_metrics_for_symbol(
                db=db,
                symbol=symbol,
                options=calls,
                stock_price=stock_price,
                store_history=True
            )
        except Exception as e:
            logging.warning(f"Could not compute IV metrics for {symbol}: {e}")
            iv_metrics = None
        
        best_opp = None
        best_score = 0
        
        for call in calls:
            strike = call.get("strike", 0)
            expiry = call.get("expiry", "")
            dte = call.get("dte", 0)
            bid = call.get("bid", 0)
            ask = call.get("ask", 0)
            open_interest = call.get("open_interest", 0)
            iv_raw = call.get("implied_volatility", 0)
            
            # PRICING RULES - SELL leg (covered call):
            # - Use BID only
            # - If BID is None, 0, or missing → reject the contract
            # - Never use: lastPrice, mid, ASK, theoretical price
            if not bid or bid <= 0:
                continue  # Reject - no valid BID for SELL leg
            
            if strike <= 0 or dte < 1:
                continue
            
            premium = bid  # SELL leg uses BID only
            
            # Filter for reasonable strikes
            if strike <= stock_price * 0.98 or strike > stock_price * 1.15:
                continue
            
            # Normalize IV
            iv_data = normalize_iv_fields(iv_raw)
            
            # Calculate delta using Black-Scholes (not moneyness fallback)
            T = max(dte, 1) / 365.0
            greeks_result = calculate_greeks(
                S=stock_price,
                K=strike,
                T=T,
                sigma=iv_data["iv"] if iv_data["iv"] > 0 else None,
                option_type="call"
            )
            
            # Calculate ROI
            roi_pct = (premium / stock_price) * 100 if stock_price > 0 else 0
            roi_annualized = (roi_pct * 365 / dte) if dte > 0 else 0
            
            # Simple scoring: ROI + IV consideration
            score = roi_pct * 2 + (iv_data["iv_pct"] * 0.1 if iv_data["iv_pct"] else 0)
            
            if score > best_score:
                best_score = score
                best_opp = {
                    "symbol": symbol,
                    "strike": strike,
                    "expiry": expiry,
                    "dte": dte,
                    "premium": round(premium, 2),
                    "bid": round(bid, 2),
                    "ask": round(ask, 2) if ask else None,
                    "stock_price": round(stock_price, 2),
                    "roi_pct": round(roi_pct, 2),
                    "roi_annualized": round(roi_annualized, 1),
                    # Greeks (Black-Scholes) - ALWAYS POPULATED
                    "delta": greeks_result.delta,
                    "delta_source": greeks_result.delta_source,
                    "gamma": greeks_result.gamma,
                    "theta": greeks_result.theta,
                    "vega": greeks_result.vega,
                    # IV fields (standardized) - ALWAYS POPULATED
                    "iv": iv_data["iv"],
                    "iv_pct": iv_data["iv_pct"],
                    # IV Rank (industry standard) - ALWAYS POPULATED
                    "iv_rank": iv_metrics.iv_rank if iv_metrics else 50.0,
                    "iv_percentile": iv_metrics.iv_percentile if iv_metrics else 50.0,
                    "iv_rank_source": iv_metrics.iv_rank_source if iv_metrics else "DEFAULT_NEUTRAL",
                    "iv_samples": iv_metrics.iv_samples if iv_metrics else 0,
                    # Liquidity
                    "open_interest": open_interest,
                    "data_source": "yahoo_live"
                }
        
        return best_opp
        
    except Exception as e:
        logging.warning(f"Error getting live opportunity for {symbol}: {e}")
        return None


async def _get_best_opportunity_eod(symbol: str, trade_date: str = None) -> dict:
    """
    LEGACY: Get best covered call opportunity from EOD contract.
    
    NOTE: This is deprecated in favor of _get_best_opportunity_live
    Kept for backward compatibility only.
    
    CCE VOLATILITY & GREEKS CORRECTNESS:
    - Delta computed via Black-Scholes (not moneyness fallback)
    - IV Rank computed using industry-standard formula
    """
    eod_contract = _get_eod_contract()
    
    try:
        # Get canonical EOD stock price
        stock_price, stock_doc = await eod_contract.get_market_close_price(symbol, trade_date)
        
        # Get valid calls from EOD contract
        calls = await eod_contract.get_valid_calls_for_scan(
            symbol=symbol,
            trade_date=trade_date,
            min_dte=1,
            max_dte=45,
            min_strike_pct=0.98,
            max_strike_pct=1.10,
            min_bid=0.05
        )
        
        if not calls:
            return None
        
        # Compute IV metrics for the symbol
        try:
            iv_metrics = await get_iv_metrics_for_symbol(
                db=db,
                symbol=symbol,
                options=calls,
                stock_price=stock_price,
                store_history=True
            )
        except Exception as e:
            logging.warning(f"Could not compute IV metrics for {symbol}: {e}")
            iv_metrics = None
        
        best_opp = None
        best_score = 0
        
        for call in calls:
            strike = call.get("strike", 0)
            expiry = call.get("expiry", "")
            dte = call.get("dte", 0)
            premium = call.get("bid", 0) or call.get("premium", 0)
            ask = call.get("ask", 0)
            open_interest = call.get("open_interest", 0)
            iv_raw = call.get("implied_volatility", 0)
            
            if premium <= 0 or strike <= 0 or dte < 1:
                continue
            
            # Normalize IV
            iv_data = normalize_iv_fields(iv_raw)
            
            # Calculate delta using Black-Scholes (not moneyness fallback)
            T = max(dte, 1) / 365.0
            greeks_result = calculate_greeks(
                S=stock_price,
                K=strike,
                T=T,
                sigma=iv_data["iv"] if iv_data["iv"] > 0 else None,
                option_type="call"
            )
            
            # Calculate ROI
            roi_pct = (premium / stock_price) * 100 if stock_price > 0 else 0
            annualized_roi = roi_pct * (365 / dte) if dte > 0 else 0
            
            if roi_pct < 0.3:
                continue
            
            option_type = "Weekly" if dte <= 14 else "Monthly"
            
            # Calculate AI Score
            roi_score = min(roi_pct * 15, 40)
            iv_score = min(iv_data["iv_pct"] / 5, 20) if iv_data["iv_pct"] > 0 else 10
            delta_score = max(0, 20 - abs(greeks_result.delta - 0.35) * 50)
            liquidity_score = 10 if open_interest >= 500 else 5 if open_interest >= 100 else 2
            
            ai_score = round(roi_score + iv_score + delta_score + liquidity_score, 1)
            
            if ai_score > best_score:
                best_score = ai_score
                
                # Calculate spread percentage
                spread_pct = ((ask - premium) / premium * 100) if premium > 0 and ask else 0
                
                best_opp = {
                    "strike": strike,
                    "expiry": expiry,
                    "dte": dte,
                    "premium": round(premium, 2),
                    "bid": round(premium, 2),
                    "ask": round(ask, 2) if ask else None,
                    "spread_pct": round(spread_pct, 2),
                    # Greeks (Black-Scholes) - ALWAYS POPULATED
                    "delta": greeks_result.delta,
                    "delta_source": greeks_result.delta_source,
                    "gamma": greeks_result.gamma,
                    "theta": greeks_result.theta,
                    "vega": greeks_result.vega,
                    # IV fields (standardized) - ALWAYS POPULATED
                    "iv": iv_data["iv"],
                    "iv_pct": iv_data["iv_pct"],
                    "implied_volatility": iv_data["iv_pct"],  # Legacy alias
                    # IV Rank (industry standard) - ALWAYS POPULATED
                    "iv_rank": iv_metrics.iv_rank if iv_metrics else 50.0,
                    "iv_percentile": iv_metrics.iv_percentile if iv_metrics else 50.0,
                    "iv_rank_source": iv_metrics.iv_rank_source if iv_metrics else "DEFAULT_NEUTRAL",
                    "iv_samples": iv_metrics.iv_samples if iv_metrics else 0,
                    # Liquidity
                    "volume": call.get("volume", 0),
                    "open_interest": open_interest,
                    # ECONOMICS fields
                    "roi_pct": round(roi_pct, 2),
                    "annualized_roi_pct": round(annualized_roi, 1),
                    # METADATA fields
                    "type": option_type,
                    "ai_score": ai_score,
                    "source": "eod_contract",
                    "data_source": "eod_contract",
                    "market_close_timestamp": stock_doc.get("market_close_timestamp")
                }
        
        return best_opp
        
    except (EODPriceNotFoundError, EODOptionsNotFoundError) as e:
        logging.warning(f"[ADR-001] No EOD data for {symbol}: {e}")
        return None
    except Exception as e:
        logging.error(f"[ADR-001] Error getting EOD opportunity for {symbol}: {e}")
        return None


async def _get_best_opportunity(symbol: str, api_key: str, underlying_price: float) -> dict:
    """
    Get the best covered call opportunity for a symbol.
    
    LAYER 3 COMPLIANT: Uses snapshot data from the screener, NOT live data.
    This ensures data consistency across all pages.
    
    CCE VOLATILITY & GREEKS CORRECTNESS:
    - Delta computed via Black-Scholes (not moneyness fallback)
    - IV Rank computed using industry-standard formula
    """
    try:
        # Import snapshot service to use Layer 1/2/3 data
        from services.snapshot_service import SnapshotService
        
        snapshot_service = SnapshotService()
        
        # Get validated snapshot data (Layer 1 + 2)
        stock_snapshot, stock_error = await snapshot_service.get_stock_snapshot(symbol)
        if stock_error or not stock_snapshot:
            # Fallback: fetch fresh data but mark as non-snapshot
            return await _get_best_opportunity_live(symbol, underlying_price)
        
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
            return await _get_best_opportunity_live(symbol, underlying_price)
        
        # Compute IV metrics for the symbol
        try:
            iv_metrics = await get_iv_metrics_for_symbol(
                db=db,
                symbol=symbol,
                options=calls,
                stock_price=stock_price,
                store_history=True
            )
        except Exception as e:
            logging.warning(f"Could not compute IV metrics for {symbol}: {e}")
            iv_metrics = None
        
        best_opp = None
        best_score = 0
        
        for call in calls:
            strike = call.get("strike", 0)
            expiry = call.get("expiry", "")
            dte = call.get("dte", 0)
            premium = call.get("bid", 0) or call.get("premium", 0)  # BID only
            ask = call.get("ask", 0)
            open_interest = call.get("open_interest", 0)
            iv_raw = call.get("implied_volatility", 0)
            
            if premium <= 0 or strike <= 0 or dte < 1:
                continue
            
            # Normalize IV
            iv_data = normalize_iv_fields(iv_raw)
            
            # Calculate delta using Black-Scholes (not moneyness fallback)
            T = max(dte, 1) / 365.0
            greeks_result = calculate_greeks(
                S=stock_price,
                K=strike,
                T=T,
                sigma=iv_data["iv"] if iv_data["iv"] > 0 else None,
                option_type="call"
            )
            
            # Calculate ROI
            roi_pct = (premium / stock_price) * 100 if stock_price > 0 else 0
            annualized_roi = roi_pct * (365 / dte) if dte > 0 else 0
            
            if roi_pct < 0.3:  # Minimum 0.3% yield
                continue
            
            # Determine type: Weekly (<=14 DTE) or Monthly
            option_type = "Weekly" if dte <= 14 else "Monthly"
            
            # Calculate AI Score
            roi_score = min(roi_pct * 15, 40)
            iv_score = min(iv_data["iv_pct"] / 5, 20) if iv_data["iv_pct"] > 0 else 10
            delta_score = max(0, 20 - abs(greeks_result.delta - 0.35) * 50)
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
                    # Greeks (Black-Scholes) - ALWAYS POPULATED
                    "delta": greeks_result.delta,
                    "delta_source": greeks_result.delta_source,
                    "gamma": greeks_result.gamma,
                    "theta": greeks_result.theta,
                    "vega": greeks_result.vega,
                    # IV fields (standardized) - ALWAYS POPULATED
                    "iv": iv_data["iv"],
                    "iv_pct": iv_data["iv_pct"],
                    "implied_volatility": iv_data["iv_pct"],  # Legacy alias
                    # IV Rank (industry standard) - ALWAYS POPULATED
                    "iv_rank": iv_metrics.iv_rank if iv_metrics else 50.0,
                    "iv_percentile": iv_metrics.iv_percentile if iv_metrics else 50.0,
                    "iv_rank_source": iv_metrics.iv_rank_source if iv_metrics else "DEFAULT_NEUTRAL",
                    "iv_samples": iv_metrics.iv_samples if iv_metrics else 0,
                    # Liquidity
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
        return await _get_best_opportunity_live(symbol, underlying_price)


async def _get_best_opportunity_live_fallback(symbol: str, api_key: str, underlying_price: float) -> dict:
    """
    FALLBACK: Get opportunity from live data when snapshot unavailable.
    Used only when Layer 3 snapshot data is not available.
    
    CCE VOLATILITY & GREEKS CORRECTNESS:
    - Delta computed via Black-Scholes (not moneyness fallback)
    - IV Rank computed using industry-standard formula
    """
    try:
        # Fetch options chain (Yahoo primary with IV/OI, Polygon backup)
        options = await fetch_options_chain(
            symbol, api_key, "call", 45, min_dte=1, current_price=underlying_price
        )
        
        if not options:
            return None
        
        # Compute IV metrics for the symbol
        try:
            iv_metrics = await get_iv_metrics_for_symbol(
                db=db,
                symbol=symbol,
                options=options,
                stock_price=underlying_price,
                store_history=True
            )
        except Exception as e:
            logging.warning(f"Could not compute IV metrics for {symbol}: {e}")
            iv_metrics = None
        
        best_opp = None
        best_roi = 0
        
        for opt in options:
            strike = opt.get("strike", 0)
            expiry = opt.get("expiry", "")
            dte = opt.get("dte", 0)
            premium = opt.get("close", 0) or opt.get("bid", 0)
            open_interest = opt.get("open_interest", 0) or 0
            iv_raw = opt.get("implied_volatility", 0) or 0
            
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
                
                # Normalize IV
                iv_data = normalize_iv_fields(iv_raw)
                
                # Calculate delta using Black-Scholes (not moneyness fallback)
                T = max(dte, 1) / 365.0
                greeks_result = calculate_greeks(
                    S=underlying_price,
                    K=strike,
                    T=T,
                    sigma=iv_data["iv"] if iv_data["iv"] > 0 else None,
                    option_type="call"
                )
                
                option_type = "Weekly" if dte <= 14 else "Monthly"
                annualized_roi = roi_pct * (365 / dte) if dte > 0 else 0
                
                # Calculate AI Score
                roi_score = min(roi_pct * 15, 40)
                iv_score = min(iv_data["iv_pct"] / 5, 20) if iv_data["iv_pct"] > 0 else 10
                delta_score = max(0, 20 - abs(greeks_result.delta - 0.35) * 50)
                liquidity_score = 10 if open_interest >= 500 else 5 if open_interest >= 100 else 2
                ai_score = round(roi_score + iv_score + delta_score + liquidity_score, 1)
                
                best_opp = {
                    "strike": strike,
                    "expiry": expiry,
                    "dte": dte,
                    "premium": round(premium, 2),
                    "bid": round(premium, 2),
                    # Greeks (Black-Scholes) - ALWAYS POPULATED
                    "delta": greeks_result.delta,
                    "delta_source": greeks_result.delta_source,
                    "gamma": greeks_result.gamma,
                    "theta": greeks_result.theta,
                    "vega": greeks_result.vega,
                    # IV fields (standardized) - ALWAYS POPULATED
                    "iv": iv_data["iv"],
                    "iv_pct": iv_data["iv_pct"],
                    "implied_volatility": iv_data["iv_pct"],  # Legacy alias
                    # IV Rank (industry standard) - ALWAYS POPULATED
                    "iv_rank": iv_metrics.iv_rank if iv_metrics else 50.0,
                    "iv_percentile": iv_metrics.iv_percentile if iv_metrics else 50.0,
                    "iv_rank_source": iv_metrics.iv_rank_source if iv_metrics else "DEFAULT_NEUTRAL",
                    "iv_samples": iv_metrics.iv_samples if iv_metrics else 0,
                    # Economics
                    "roi_pct": round(roi_pct, 2),
                    "annualized_roi_pct": round(annualized_roi, 1),
                    # Liquidity
                    "volume": opt.get("volume", 0),
                    "open_interest": open_interest,
                    # Metadata
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
async def get_watchlist(
    use_live_prices: bool = Query(True, description="Use LIVE intraday prices (Rule #2)"),
    user: dict = Depends(get_current_user)
):
    """
    Get user's watchlist with current prices and opportunities.
    
    DATA FETCHING RULES:
    - Stock prices: LIVE intraday prices (regularMarketPrice) - Rule #2
    - Options: LIVE from Yahoo Finance - Rule #3
    
    This is different from Screener which uses previous close for stock prices.
    """
    get_massive_api_key, _ = _get_server_functions()
    
    items = await db.watchlist.find({"user_id": user["id"]}, {"_id": 0}).to_list(100)
    
    if not items:
        return []
    
    # Get all symbols
    symbols = [item.get("symbol", "") for item in items if item.get("symbol")]
    
    # Get API key
    api_key = await get_massive_api_key()
    
    # Fetch LIVE stock prices (Rule #2: Watchlist uses live prices)
    if use_live_prices:
        stock_data = await fetch_live_stock_quotes_batch(symbols, api_key)
    else:
        stock_data = await fetch_stock_quotes_batch(symbols, api_key)
    
    # Enrich items with LIVE prices and LIVE opportunities
    enriched_items = []
    for item in items:
        symbol = item.get("symbol", "")
        live_data = stock_data.get(symbol, {})
        
        # Rule #2: Watchlist uses LIVE intraday prices
        if live_data.get("price"):
            current_price = live_data.get("price", 0)
            price_source = "LIVE_INTRADAY"
            is_live = live_data.get("is_live", True)
        else:
            current_price = 0
            price_source = "UNAVAILABLE"
            is_live = False
        
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
            "price_source": price_source,  # LIVE_INTRADAY for watchlist
            "is_live_price": is_live,
            "change": live_data.get("change", 0),
            "change_pct": live_data.get("change_pct", 0),
            "price_when_added": price_when_added,
            "movement": round(movement, 2),
            "movement_pct": round(movement_pct, 2),
            "analyst_rating": live_data.get("analyst_rating"),
            "opportunity": None
        }
        
        # Rule #3: Fetch LIVE opportunities (options chain fetched at request time)
        if current_price > 0:
            opp = await _get_best_opportunity_live(symbol, current_price)
            enriched["opportunity"] = opp
            enriched["opportunity_source"] = "yahoo_live" if opp else None
        
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
