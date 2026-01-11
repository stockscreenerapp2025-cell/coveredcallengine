"""
Options Routes - Options chain and expiration endpoints
Designed for scalability with proper async patterns and connection reuse
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

options_router = APIRouter(tags=["Options"])

# Reusable HTTP client settings for better connection pooling
HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def _get_server_data():
    """Lazy import to avoid circular dependencies"""
    from server import MOCK_STOCKS, get_massive_api_key, generate_mock_options
    return MOCK_STOCKS, get_massive_api_key, generate_mock_options


def calculate_dte(expiry_date: str) -> int:
    """Calculate days to expiration - pure function for performance"""
    if not expiry_date:
        return 0
    try:
        exp = datetime.strptime(expiry_date, "%Y-%m-%d")
        today = datetime.now()
        return max(0, (exp - today).days)
    except Exception:
        return 0


@options_router.get("/chain/{symbol}")
async def get_options_chain(
    symbol: str,
    expiry: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    """
    Get options chain for a symbol.
    Scalability: Uses connection pooling, async I/O, efficient data transformation.
    """
    MOCK_STOCKS, get_massive_api_key, generate_mock_options = _get_server_data()
    
    symbol = symbol.upper()
    
    # Try Massive.com/Polygon Options API first
    api_key = await get_massive_api_key()
    if api_key:
        try:
            # Use async context manager for proper connection handling
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                # First get the stock price
                stock_response = await client.get(
                    f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev",
                    params={"apiKey": api_key}
                )
                underlying_price = 0
                if stock_response.status_code == 200:
                    stock_data = stock_response.json()
                    if stock_data.get("results"):
                        underlying_price = stock_data["results"][0].get("c", 0)
                
                # Then get options chain
                params = {
                    "apiKey": api_key,
                    "limit": 250
                }
                
                # Add expiration filter if provided
                if expiry:
                    params["expiration_date"] = expiry
                
                url = f"https://api.polygon.io/v3/snapshot/options/{symbol}"
                logging.info(f"Options chain request: {symbol}, expiry={expiry}")
                
                response = await client.get(url, params=params)
                
                if response.status_code == 200:
                    data = response.json()
                    results = data.get("results", [])
                    
                    logging.info(f"Options chain: {len(results)} results for {symbol}")
                    
                    if results:
                        # Efficient list comprehension for data transformation
                        options = [
                            {
                                "symbol": opt.get("details", {}).get("ticker", ""),
                                "underlying": symbol,
                                "strike": opt.get("details", {}).get("strike_price", 0),
                                "expiry": opt.get("details", {}).get("expiration_date", ""),
                                "dte": calculate_dte(opt.get("details", {}).get("expiration_date", "")),
                                "type": opt.get("details", {}).get("contract_type", "call"),
                                "bid": opt.get("last_quote", {}).get("bid", 0) if opt.get("last_quote") else 0,
                                "ask": opt.get("last_quote", {}).get("ask", 0) if opt.get("last_quote") else 0,
                                "last": (opt.get("day", {}).get("close", 0) if opt.get("day") else 0) or 
                                        (opt.get("last_quote", {}).get("midpoint", 0) if opt.get("last_quote") else 0),
                                "delta": opt.get("greeks", {}).get("delta", 0) if opt.get("greeks") else 0,
                                "gamma": opt.get("greeks", {}).get("gamma", 0) if opt.get("greeks") else 0,
                                "theta": opt.get("greeks", {}).get("theta", 0) if opt.get("greeks") else 0,
                                "vega": opt.get("greeks", {}).get("vega", 0) if opt.get("greeks") else 0,
                                "iv": opt.get("implied_volatility", 0),
                                "volume": opt.get("day", {}).get("volume", 0) if opt.get("day") else 0,
                                "open_interest": opt.get("open_interest", 0),
                                "break_even": opt.get("break_even_price", 0),
                            }
                            for opt in results
                        ]
                        
                        # Filter to calls only for covered call screener
                        call_options = [o for o in options if o["type"] == "call"]
                        
                        return {
                            "symbol": symbol,
                            "stock_price": underlying_price,
                            "options": call_options,
                            "is_live": True
                        }
                elif response.status_code == 403:
                    logging.error("Polygon API 403 - check API plan for options access")
                else:
                    logging.error(f"Polygon API error: {response.status_code}")
        except httpx.TimeoutException:
            logging.error(f"Timeout fetching options for {symbol}")
        except Exception as e:
            logging.error(f"Options API error: {e}")
    
    # Fallback to mock data
    stock_price = MOCK_STOCKS.get(symbol, {}).get("price", 100)
    options = generate_mock_options(symbol, stock_price)
    
    if expiry:
        options = [o for o in options if o["expiry"] == expiry]
    
    return {
        "symbol": symbol,
        "stock_price": stock_price,
        "options": options,
        "is_mock": True
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
