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
    
    # Use centralized data provider
    from services.data_provider import fetch_options_chain, fetch_stock_quote
    
    # 1. Fetch underlying price first
    quote = await fetch_stock_quote(symbol)
    stock_price = quote.get("price", 0) if quote else 0
    
    if stock_price > 0:
        # 2. Fetch options chain (Yahoo primary)
        options = await fetch_options_chain(
            symbol=symbol,
            current_price=stock_price,
            option_type="call" # Screener focuses on calls
        )
        
        if options:
            # Filter by expiry if provided
            if expiry:
                options = [o for o in options if o["expiry"] == expiry]
                
            return {
                "symbol": symbol,
                "stock_price": stock_price,
                "options": options,
                "is_live": True,
                "source": "yahoo"
            }
    
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
