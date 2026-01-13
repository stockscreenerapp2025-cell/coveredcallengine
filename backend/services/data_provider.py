"""
Centralized Data Provider Service
=================================
This service manages all external data sourcing with clear separation of concerns:

OPTIONS DATA: Polygon/Massive ONLY (paid subscription)
STOCK DATA: Polygon/Massive primary, Yahoo fallback (until upgrade)

Configuration:
- Set USE_POLYGON_FOR_STOCKS = True when stock subscription is upgraded
- All options data always comes from Polygon/Massive

This is the SINGLE SOURCE OF TRUTH for data sourcing logic.
Do not implement data fetching elsewhere in the codebase.
"""

import os
import logging
import asyncio
import aiohttp
import httpx
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import pytz

# =============================================================================
# CONFIGURATION - Change this when upgrading Polygon stock subscription
# =============================================================================
USE_POLYGON_FOR_STOCKS = False  # Set to True when stock subscription is upgraded

# API Settings
HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
POLYGON_BASE_URL = "https://api.polygon.io"

# =============================================================================
# MARKET STATUS HELPERS
# =============================================================================

def is_market_closed() -> bool:
    """Check if US stock market is currently closed (weekend or outside market hours)"""
    try:
        eastern = pytz.timezone('US/Eastern')
        now_eastern = datetime.now(eastern)
        
        # Weekend (Saturday=5, Sunday=6)
        if now_eastern.weekday() >= 5:
            return True
        
        # Outside market hours (9:30 AM - 4:00 PM ET)
        market_open = now_eastern.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now_eastern.replace(hour=16, minute=0, second=0, microsecond=0)
        
        if now_eastern < market_open or now_eastern > market_close:
            return True
            
        return False
    except Exception as e:
        logging.warning(f"Error checking market hours: {e}")
        return False


def calculate_dte(expiry_date: str) -> int:
    """Calculate days to expiration from expiry date string (YYYY-MM-DD)"""
    if not expiry_date:
        return 0
    try:
        expiry = datetime.strptime(expiry_date, "%Y-%m-%d")
        today = datetime.now()
        return max(0, (expiry - today).days)
    except Exception:
        return 0


# =============================================================================
# OPTIONS DATA - POLYGON/MASSIVE ONLY
# =============================================================================

async def fetch_options_chain(
    symbol: str, 
    api_key: str, 
    contract_type: str = "call", 
    max_dte: int = 45, 
    min_dte: int = 1, 
    current_price: float = 0
) -> List[Dict[str, Any]]:
    """
    Fetch options chain data from Polygon/Massive ONLY.
    
    This is the ONLY function for fetching options data.
    Yahoo Finance is NOT used for options under any circumstances.
    
    Args:
        symbol: Stock ticker symbol
        api_key: Polygon/Massive API key
        contract_type: "call" or "put"
        max_dte: Maximum days to expiration
        min_dte: Minimum days to expiration
        current_price: Current stock price for filtering strikes
        
    Returns:
        List of option contract data with pricing
    """
    if not api_key:
        logging.warning(f"No API key provided for options chain fetch: {symbol}")
        return []
    
    options = []
    today = datetime.now()
    min_expiry = (today + timedelta(days=min_dte)).strftime("%Y-%m-%d")
    max_expiry = (today + timedelta(days=max_dte)).strftime("%Y-%m-%d")
    
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            # Step 1: Get available contracts from Polygon
            contracts_url = f"{POLYGON_BASE_URL}/v3/reference/options/contracts"
            params = {
                "underlying_ticker": symbol.upper(),
                "contract_type": contract_type,
                "expiration_date.gte": min_expiry,
                "expiration_date.lte": max_expiry,
                "limit": 250,
                "apiKey": api_key
            }
            
            response = await client.get(contracts_url, params=params)
            
            if response.status_code != 200:
                logging.warning(f"Polygon contracts API error for {symbol}: {response.status_code}")
                return []
            
            data = response.json()
            contracts = data.get("results", [])
            
            if not contracts:
                logging.info(f"No options contracts found for {symbol} (DTE: {min_dte}-{max_dte})")
                return []
            
            logging.info(f"Found {len(contracts)} {contract_type} contracts for {symbol}")
            
            # Filter contracts by strike range if current_price provided
            if current_price > 0:
                if min_dte >= 150:  # LEAPS - want ITM (40-95% of price)
                    valid_contracts = [c for c in contracts 
                                      if current_price * 0.40 <= c.get("strike_price", 0) <= current_price * 0.95]
                    logging.info(f"{symbol} LEAPS: {len(valid_contracts)} contracts in ITM range")
                else:  # Short-term calls - want OTM (95-150% of price)
                    valid_contracts = [c for c in contracts 
                                      if current_price * 0.95 <= c.get("strike_price", 0) <= current_price * 1.50]
                    logging.info(f"{symbol} Short: {len(valid_contracts)} contracts in OTM range")
                
                if valid_contracts:
                    contracts = valid_contracts
                else:
                    contracts = contracts[:50]
            
            # Limit contracts for price fetching
            contracts_to_fetch = contracts[:40]
            
            # Step 2: Try to get IV from options snapshot (more reliable)
            iv_data = {}
            try:
                snapshot_url = f"{POLYGON_BASE_URL}/v3/snapshot/options/{symbol.upper()}"
                snapshot_response = await client.get(snapshot_url, params={"apiKey": api_key})
                if snapshot_response.status_code == 200:
                    snapshot_data = snapshot_response.json()
                    for result in snapshot_data.get("results", []):
                        details = result.get("details", {})
                        greeks = result.get("greeks", {})
                        contract_ticker = details.get("ticker", "")
                        if contract_ticker and greeks.get("implied_volatility"):
                            iv_data[contract_ticker] = greeks.get("implied_volatility", 0)
                    logging.info(f"Fetched IV data for {len(iv_data)} contracts from snapshot")
            except Exception as e:
                logging.debug(f"Snapshot IV fetch failed for {symbol}: {e}")
            
            # Step 3: Fetch prices in parallel
            semaphore = asyncio.Semaphore(15)
            
            async def fetch_contract_price(contract):
                async with semaphore:
                    contract_ticker = contract.get("ticker", "")
                    if not contract_ticker:
                        return None
                    
                    try:
                        price_response = await client.get(
                            f"{POLYGON_BASE_URL}/v2/aggs/ticker/{contract_ticker}/prev",
                            params={"apiKey": api_key}
                        )
                        
                        if price_response.status_code == 200:
                            price_data = price_response.json()
                            results = price_data.get("results", [])
                            
                            if results:
                                result = results[0]
                                strike = contract.get("strike_price", 0)
                                expiry = contract.get("expiration_date", "")
                                
                                # Get IV from snapshot data or default
                                iv = iv_data.get(contract_ticker, 0)
                                
                                return {
                                    "contract_ticker": contract_ticker,
                                    "underlying": symbol.upper(),
                                    "strike": strike,
                                    "expiry": expiry,
                                    "dte": calculate_dte(expiry),
                                    "type": contract.get("contract_type", "call"),
                                    "close": result.get("c", 0),
                                    "open": result.get("o", 0),
                                    "high": result.get("h", 0),
                                    "low": result.get("l", 0),
                                    "volume": result.get("v", 0),
                                    "vwap": result.get("vw", 0),
                                    "implied_volatility": iv,
                                }
                    except Exception as e:
                        logging.debug(f"Error fetching price for {contract_ticker}: {e}")
                    return None
            
            # Execute all fetches in parallel
            results = await asyncio.gather(
                *[fetch_contract_price(c) for c in contracts_to_fetch],
                return_exceptions=True
            )
            
            # Filter valid results
            for result in results:
                if result and not isinstance(result, Exception):
                    options.append(result)
            
            logging.info(f"Successfully fetched {len(options)} option prices for {symbol}")
            return options
            
    except Exception as e:
        logging.error(f"Error fetching options chain for {symbol}: {e}")
        return []


# =============================================================================
# STOCK DATA - POLYGON PRIMARY, YAHOO FALLBACK
# =============================================================================

async def _fetch_stock_from_polygon(symbol: str, api_key: str) -> Optional[Dict[str, Any]]:
    """Fetch stock data from Polygon/Massive (primary source)"""
    if not api_key:
        return None
        
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{POLYGON_BASE_URL}/v2/aggs/ticker/{symbol.upper()}/prev"
            params = {"apiKey": api_key}
            
            async with session.get(url, params=params, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    results = data.get("results", [])
                    if results:
                        r = results[0]
                        return {
                            "symbol": symbol.upper(),
                            "price": r.get("c", 0),
                            "open": r.get("o", 0),
                            "high": r.get("h", 0),
                            "low": r.get("l", 0),
                            "volume": r.get("v", 0),
                            "source": "polygon"
                        }
    except Exception as e:
        logging.warning(f"Polygon stock fetch error for {symbol}: {e}")
    return None


async def _fetch_stock_from_yahoo(symbol: str) -> Optional[Dict[str, Any]]:
    """Fetch stock data from Yahoo Finance (fallback source)"""
    yahoo_symbol = symbol.replace(' ', '-').replace('.', '-')
    
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}?interval=1d&range=1d"
            headers = {"User-Agent": "Mozilla/5.0"}
            
            async with session.get(url, headers=headers, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    result = data.get("chart", {}).get("result", [])
                    if result:
                        meta = result[0].get("meta", {})
                        price = meta.get("regularMarketPrice", 0)
                        if price:
                            return {
                                "symbol": symbol.upper(),
                                "price": price,
                                "open": meta.get("regularMarketOpen", 0),
                                "high": meta.get("regularMarketDayHigh", 0),
                                "low": meta.get("regularMarketDayLow", 0),
                                "volume": meta.get("regularMarketVolume", 0),
                                "source": "yahoo"
                            }
    except Exception as e:
        logging.warning(f"Yahoo stock fetch error for {symbol}: {e}")
    return None


async def fetch_stock_quote(symbol: str, api_key: str = None) -> Optional[Dict[str, Any]]:
    """
    Fetch current stock quote.
    
    Strategy:
    - If USE_POLYGON_FOR_STOCKS is True: Use Polygon only
    - If USE_POLYGON_FOR_STOCKS is False: Try Polygon first, fallback to Yahoo
    
    This allows easy switching when Polygon stock subscription is upgraded.
    
    Args:
        symbol: Stock ticker symbol
        api_key: Polygon/Massive API key
        
    Returns:
        Stock quote data or None if unavailable
    """
    # Try Polygon first (primary source)
    if api_key:
        polygon_data = await _fetch_stock_from_polygon(symbol, api_key)
        if polygon_data:
            return polygon_data
    
    # If Polygon-only mode is enabled, don't fall back to Yahoo
    if USE_POLYGON_FOR_STOCKS:
        logging.warning(f"Polygon-only mode enabled but no data for {symbol}")
        return None
    
    # Fallback to Yahoo for stock data
    yahoo_data = await _fetch_stock_from_yahoo(symbol)
    if yahoo_data:
        return yahoo_data
    
    logging.warning(f"No stock data available for {symbol} from any source")
    return None


async def fetch_stock_quotes_batch(
    symbols: List[str], 
    api_key: str = None
) -> Dict[str, Dict[str, Any]]:
    """
    Fetch stock quotes for multiple symbols in parallel.
    
    Args:
        symbols: List of stock ticker symbols
        api_key: Polygon/Massive API key
        
    Returns:
        Dictionary mapping symbols to their quote data
    """
    results = {}
    
    async def fetch_single(symbol):
        quote = await fetch_stock_quote(symbol, api_key)
        if quote:
            results[symbol.upper()] = quote
    
    # Fetch all quotes in parallel
    await asyncio.gather(*[fetch_single(s) for s in symbols], return_exceptions=True)
    
    return results


# =============================================================================
# HISTORICAL DATA (for trends, charts, etc.)
# =============================================================================

async def fetch_historical_prices(
    symbol: str, 
    api_key: str = None,
    days: int = 365
) -> List[Dict[str, Any]]:
    """
    Fetch historical daily prices for a symbol.
    
    Uses same sourcing strategy as stock quotes:
    - Polygon primary, Yahoo fallback (until subscription upgrade)
    
    Args:
        symbol: Stock ticker symbol
        api_key: Polygon/Massive API key
        days: Number of days of history to fetch
        
    Returns:
        List of daily price data (oldest to newest)
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    # Try Polygon first
    if api_key:
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{POLYGON_BASE_URL}/v2/aggs/ticker/{symbol.upper()}/range/1/day/{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}"
                params = {"apiKey": api_key, "sort": "asc", "limit": 500}
                
                async with session.get(url, params=params, timeout=15) as response:
                    if response.status == 200:
                        data = await response.json()
                        results = data.get("results", [])
                        if results:
                            return [
                                {
                                    "date": datetime.fromtimestamp(r["t"] / 1000).strftime("%Y-%m-%d"),
                                    "open": r.get("o", 0),
                                    "high": r.get("h", 0),
                                    "low": r.get("l", 0),
                                    "close": r.get("c", 0),
                                    "volume": r.get("v", 0),
                                    "source": "polygon"
                                }
                                for r in results
                            ]
        except Exception as e:
            logging.warning(f"Polygon historical fetch error for {symbol}: {e}")
    
    # If Polygon-only mode, don't fall back
    if USE_POLYGON_FOR_STOCKS:
        return []
    
    # Fallback to Yahoo for historical data
    try:
        import yfinance as yf
        
        def fetch_yahoo_history():
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period=f"{days}d")
            if hist.empty:
                return []
            return [
                {
                    "date": idx.strftime("%Y-%m-%d"),
                    "open": row["Open"],
                    "high": row["High"],
                    "low": row["Low"],
                    "close": row["Close"],
                    "volume": int(row["Volume"]),
                    "source": "yahoo"
                }
                for idx, row in hist.iterrows()
            ]
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fetch_yahoo_history)
        
    except Exception as e:
        logging.warning(f"Yahoo historical fetch error for {symbol}: {e}")
    
    return []


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_data_source_status() -> Dict[str, Any]:
    """
    Get current data source configuration status.
    Useful for admin dashboards and debugging.
    """
    return {
        "options_source": "polygon_only",
        "stock_source": "polygon_primary_yahoo_fallback" if not USE_POLYGON_FOR_STOCKS else "polygon_only",
        "use_polygon_for_stocks": USE_POLYGON_FOR_STOCKS,
        "polygon_base_url": POLYGON_BASE_URL,
        "market_closed": is_market_closed()
    }
