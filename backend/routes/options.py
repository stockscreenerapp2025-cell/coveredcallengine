"""
Options Routes - Options chain and expiration endpoints
Designed for scalability with proper async patterns and connection reuse

PHASE 1 REFACTOR (December 2025):
- All options data now routes through services/data_provider.py
- Yahoo Finance is primary source, Polygon is backup (via data_provider)
- MOCK options retained for fallback but flagged
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional
from datetime import datetime, timedelta
import logging
import httpx

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.auth import get_current_user
from services.data_provider import fetch_stock_quote, fetch_options_chain, calculate_dte
from services.greeks_service import calculate_greeks, normalize_iv_fields
from services.iv_rank_service import get_iv_metrics_for_symbol
from database import db

options_router = APIRouter(tags=["Options"])

# Reusable HTTP client settings for better connection pooling
HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def _get_server_data():
    """Lazy import to avoid circular dependencies"""
    from server import MOCK_STOCKS, get_massive_api_key, generate_mock_options
    return MOCK_STOCKS, get_massive_api_key, generate_mock_options


@options_router.get("/chain/{symbol}")
async def get_options_chain(
    symbol: str,
    expiry: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    """
    Get options chain for a symbol.
    
    PHASE 1 REFACTOR: Now routes through data_provider.py
    - Primary: Yahoo Finance (via data_provider.fetch_options_chain)
    - Backup: Polygon (via data_provider fallback)
    - Last Resort: Mock options (flagged with is_mock=True)
    """
    MOCK_STOCKS, get_massive_api_key, generate_mock_options = _get_server_data()
    
    symbol = symbol.upper()
    
    # Get API key for potential Polygon fallback
    api_key = await get_massive_api_key()
    
    try:
        # Get stock price from data_provider
        stock_data = await fetch_stock_quote(symbol, api_key)
        underlying_price = stock_data.get("price", 0) if stock_data else 0
        
        # Calculate DTE range based on expiry filter
        min_dte = 1
        max_dte = 90  # Default: fetch up to 90 days
        
        if expiry:
            # If specific expiry requested, narrow the DTE range
            try:
                exp_date = datetime.strptime(expiry, "%Y-%m-%d")
                dte = (exp_date - datetime.now()).days
                min_dte = max(1, dte - 7)
                max_dte = dte + 7
            except Exception:
                pass
        
        # Fetch options from data_provider (Yahoo primary, Polygon backup)
        options = await fetch_options_chain(
            symbol=symbol,
            api_key=api_key,
            option_type="call",
            min_dte=min_dte,
            max_dte=max_dte,
            current_price=underlying_price
        )
        
        if options and len(options) > 0:
            # Compute IV metrics for the symbol (industry-standard IV Rank)
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
            
            # Transform to expected format with proper Greeks
            transformed_options = []
            for opt in options:
                # Filter by specific expiry if provided
                if expiry and opt.get("expiry") != expiry:
                    continue
                
                # Calculate Greeks using Black-Scholes
                dte = opt.get("dte", 30)
                strike = opt.get("strike", 0)
                iv_raw = opt.get("implied_volatility", 0)
                iv_data = normalize_iv_fields(iv_raw)
                T = max(dte, 1) / 365.0
                
                greeks_result = calculate_greeks(
                    S=underlying_price,
                    K=strike,
                    T=T,
                    sigma=iv_data["iv"] if iv_data["iv"] > 0 else None,
                    option_type="call"
                )
                
                transformed_options.append({
                    "symbol": opt.get("contract_ticker", ""),
                    "underlying": symbol,
                    "strike": strike,
                    "expiry": opt.get("expiry", ""),
                    "dte": dte,
                    "type": opt.get("type", "call"),
                    "bid": opt.get("bid", 0),
                    "ask": opt.get("ask", 0),
                    "last": opt.get("close", 0),
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
                    "volume": opt.get("volume", 0),
                    "open_interest": opt.get("open_interest", 0),
                    "break_even": strike + opt.get("ask", 0) if opt.get("type") == "call" else strike - opt.get("ask", 0),
                })
            
            if transformed_options:
                logging.info(f"Options chain: {len(transformed_options)} results for {symbol} via data_provider")
                return {
                    "symbol": symbol,
                    "stock_price": underlying_price,
                    "options": transformed_options,
                    # Symbol-level IV metrics
                    "iv_proxy": iv_metrics.iv_proxy if iv_metrics else 0.0,
                    "iv_proxy_pct": iv_metrics.iv_proxy_pct if iv_metrics else 0.0,
                    "iv_rank": iv_metrics.iv_rank if iv_metrics else 50.0,
                    "iv_percentile": iv_metrics.iv_percentile if iv_metrics else 50.0,
                    "iv_rank_source": iv_metrics.iv_rank_source if iv_metrics else "DEFAULT_NEUTRAL",
                    "iv_samples": iv_metrics.iv_samples if iv_metrics else 0,
                    "source": options[0].get("source", "yahoo") if options else "yahoo",
                    "is_live": True
                }
    
    except Exception as e:
        logging.error(f"data_provider options chain error for {symbol}: {e}")
    
    # Fallback to mock data (flagged)
    stock_price = MOCK_STOCKS.get(symbol, {}).get("price", 100)
    mock_options = generate_mock_options(symbol, stock_price)
    
    if expiry:
        mock_options = [o for o in mock_options if o["expiry"] == expiry]
    
    logging.warning(f"Using mock options fallback for {symbol}")
    return {
        "symbol": symbol,
        "stock_price": stock_price,
        "options": mock_options,
        "is_mock": True  # FLAG: Mock data in use
    }


@options_router.get("/expirations/{symbol}")
async def get_option_expirations(symbol: str, user: dict = Depends(get_current_user)):
    """
    Get available expiration dates for a symbol.
    Returns weekly and monthly expirations.
    """
    expirations = []
    now = datetime.now()
    
    # Weekly expirations (next 12 weeks) - efficient loop
    for weeks in range(1, 12):
        expiry = (now + timedelta(weeks=weeks)).strftime("%Y-%m-%d")
        expirations.append({"date": expiry, "dte": weeks * 7})
    
    # Monthly expirations (3-24 months out)
    for months in range(3, 25):
        expiry = (now + timedelta(days=months * 30)).strftime("%Y-%m-%d")
        expirations.append({"date": expiry, "dte": months * 30})
    
    return expirations
