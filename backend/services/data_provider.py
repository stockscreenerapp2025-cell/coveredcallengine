"""
Centralized Data Provider Service
=================================
PRIMARY DATA SOURCE: Yahoo Finance (yfinance)
BACKUP DATA SOURCE: Polygon/Massive (free tier)

Yahoo Finance provides:
- Stock quotes (current + previous close - always available)
- Options chains with IV, OI, Greeks built-in
- Works during market hours and after (returns last available data)

Polygon provides:
- Backup for stock quotes when Yahoo fails
- Options aggregates (no IV/OI in basic plan)

This is the SINGLE SOURCE OF TRUTH for data sourcing logic.
All screeners and pages should use these functions for consistency.
"""

import os
import logging
import asyncio
import httpx
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor
import pytz

# =============================================================================
# CONFIGURATION
# =============================================================================
HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
POLYGON_BASE_URL = "https://api.polygon.io"

# Thread pool for blocking yfinance calls
_yahoo_executor = ThreadPoolExecutor(max_workers=8)

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


def get_last_trading_day() -> str:
    """Get the last trading day date string (YYYY-MM-DD)"""
    eastern = pytz.timezone('US/Eastern')
    now = datetime.now(eastern)
    
    # If weekend, go back to Friday
    if now.weekday() == 5:  # Saturday
        now = now - timedelta(days=1)
    elif now.weekday() == 6:  # Sunday
        now = now - timedelta(days=2)
    elif now.weekday() == 0 and now.hour < 9:  # Monday before market open
        now = now - timedelta(days=3)
    elif now.hour < 9 or (now.hour == 9 and now.minute < 30):
        # Before market open on weekday
        now = now - timedelta(days=1)
        if now.weekday() == 6:  # Sunday
            now = now - timedelta(days=2)
    
    return now.strftime('%Y-%m-%d')


def calculate_dte(expiry_date: str) -> int:
    """Calculate days to expiration from date string"""
    try:
        exp = datetime.strptime(expiry_date, '%Y-%m-%d')
        today = datetime.now()
        return max(0, (exp - today).days)
    except Exception:
        return 0


# =============================================================================
# YAHOO FINANCE - PRIMARY DATA SOURCE
# =============================================================================

def _fetch_stock_quote_yahoo_sync(symbol: str) -> Dict[str, Any]:
    """
    Fetch stock quote from Yahoo Finance (blocking call).
    
    CCE MASTER ARCHITECTURE - LAYER 1 COMPLIANT:
    Returns ONLY the PREVIOUS NYSE MARKET CLOSE price.
    
    ❌ FORBIDDEN: regularMarketPrice, currentPrice (intraday prices)
    ✅ CORRECT: previousClose ONLY - ensures consistency with snapshot_service.py
    """
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        info = ticker.info
        
        # LAYER 1 COMPLIANT: Use ONLY previousClose - never intraday prices
        previous_close = info.get("previousClose", 0)
        
        if not previous_close or previous_close <= 0:
            logging.warning(f"Yahoo stock quote: No previousClose for {symbol}")
            return None
        
        # Get analyst rating
        recommendation = info.get("recommendationKey", "")
        rating_map = {
            "strong_buy": "Strong Buy",
            "buy": "Buy",
            "hold": "Hold",
            "underperform": "Sell",
            "sell": "Sell"
        }
        analyst_rating = rating_map.get(recommendation, recommendation.replace("_", " ").title() if recommendation else None)
        
        return {
            "symbol": symbol,
            "price": round(previous_close, 2),  # LAYER 1: previousClose ONLY
            "previous_close": round(previous_close, 2),
            "analyst_rating": analyst_rating,
            "source": "yahoo"
        }
    except Exception as e:
        logging.warning(f"Yahoo stock quote failed for {symbol}: {e}")
        return None


def _fetch_options_chain_yahoo_sync(
    symbol: str, 
    max_dte: int = 45, 
    min_dte: int = 1,
    option_type: str = "call",
    current_price: float = None
) -> List[Dict]:
    """
    Fetch options chain from Yahoo Finance (blocking call).
    Returns options with IV, OI, and Greeks built-in.
    """
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        
        # Get current price if not provided
        if not current_price:
            info = ticker.info
            current_price = info.get("regularMarketPrice") or info.get("currentPrice") or info.get("previousClose", 0)
        
        if not current_price:
            return []
        
        # Get available expirations
        try:
            expirations = ticker.options
        except Exception:
            return []
        
        if not expirations:
            return []
        
        # Filter expirations within DTE range
        today = datetime.now()
        valid_expiries = []
        for exp_str in expirations:
            try:
                exp_date = datetime.strptime(exp_str, "%Y-%m-%d")
                dte = (exp_date - today).days
                if min_dte <= dte <= max_dte:
                    valid_expiries.append((exp_str, dte))
            except Exception:
                continue
        
        if not valid_expiries:
            return []
        
        options = []
        
        # For LEAPS (DTE > 90), include more expiries; for shorter-term, limit to 3
        max_expiries = 5 if min_dte > 90 else 3
        
        # Fetch options for each valid expiry
        for expiry, dte in valid_expiries[:max_expiries]:
            try:
                opt_chain = ticker.option_chain(expiry)
                chain_data = opt_chain.calls if option_type == "call" else opt_chain.puts
                
                for _, row in chain_data.iterrows():
                    strike = row.get('strike', 0)
                    if not strike:
                        continue
                    
                    # Filter strikes based on moneyness
                    # PMCC/LEAPS need deep ITM calls, so widen the filter for longer DTE
                    if option_type == "call":
                        if min_dte > 90:  # LEAPS - include deep ITM
                            # For LEAPS, include 50% ITM to 15% OTM
                            if strike < current_price * 0.50 or strike > current_price * 1.15:
                                continue
                        else:
                            # For shorter-term, focus on 5% ITM to 15% OTM
                            if strike < current_price * 0.95 or strike > current_price * 1.15:
                                continue
                    else:
                        # For puts, focus on ATM to OTM
                        if strike > current_price * 1.05 or strike < current_price * 0.85:
                            continue
                    
                    # Get premium - Store BID and ASK separately
                    # The consuming code decides which to use (BID for sell, ASK for buy)
                    last_price = row.get('lastPrice', 0)
                    bid = row.get('bid', 0) if row.get('bid') and not (hasattr(row.get('bid'), '__len__') and len(row.get('bid')) == 0) else 0
                    ask = row.get('ask', 0) if row.get('ask') and not (hasattr(row.get('ask'), '__len__') and len(row.get('ask')) == 0) else 0
                    
                    # Handle NaN values
                    import math
                    if bid and isinstance(bid, float) and math.isnan(bid):
                        bid = 0
                    if ask and isinstance(ask, float) and math.isnan(ask):
                        ask = 0
                    if last_price and isinstance(last_price, float) and math.isnan(last_price):
                        last_price = 0
                    
                    # LAYER 2 PRICING RULES: SELL legs must use BID only, never lastPrice or ASK
                    # Reject contract if no valid BID - lastPrice fallback removed to prevent
                    # overstating premium (lastPrice could be from a BUY transaction at ASK)
                    if bid and bid > 0:
                        premium = bid
                    else:
                        continue  # Reject contract if no valid BID
                    
                    if premium <= 0:
                        continue
                    
                    # Get IV and OI
                    iv = row.get('impliedVolatility', 0)
                    oi = row.get('openInterest', 0)
                    volume = row.get('volume', 0)
                    
                    # Skip if IV is unrealistic (< 1% or > 500%)
                    if iv and (iv < 0.01 or iv > 5.0):
                        iv = 0
                    
                    options.append({
                        "contract_ticker": row.get('contractSymbol', ''),
                        "underlying": symbol,
                        "strike": float(strike),
                        "expiry": expiry,
                        "dte": dte,
                        "type": option_type,
                        "close": round(float(premium), 2),
                        "bid": float(bid) if bid else 0,
                        "ask": float(ask) if ask else 0,
                        "volume": int(volume) if volume else 0,
                        "open_interest": int(oi) if oi else 0,
                        "implied_volatility": float(iv) if iv else 0,
                        "source": "yahoo"
                    })
                    
            except Exception as e:
                logging.debug(f"Error fetching {symbol} options for {expiry}: {e}")
                continue
        
        logging.info(f"Yahoo: fetched {len(options)} {option_type} options for {symbol}")
        return options
        
    except Exception as e:
        logging.warning(f"Yahoo options chain failed for {symbol}: {e}")
        return []


async def fetch_stock_quote(symbol: str, api_key: str = None) -> Dict[str, Any]:
    """
    Fetch stock quote - Yahoo primary, Polygon backup.
    Always returns data (at minimum, previous close).
    """
    loop = asyncio.get_event_loop()
    
    # Try Yahoo first
    result = await loop.run_in_executor(_yahoo_executor, _fetch_stock_quote_yahoo_sync, symbol)
    
    if result and result.get("price", 0) > 0:
        return result
    
    # Fallback to Polygon
    if api_key:
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                response = await client.get(
                    f"{POLYGON_BASE_URL}/v2/aggs/ticker/{symbol}/prev",
                    params={"apiKey": api_key}
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("results") and len(data["results"]) > 0:
                        r = data["results"][0]
                        return {
                            "symbol": symbol,
                            "price": r.get("c", 0),
                            "previous_close": r.get("c", 0),
                            "change": r.get("c", 0) - r.get("o", r.get("c", 0)),
                            "change_pct": 0,
                            "source": "polygon"
                        }
        except Exception as e:
            logging.debug(f"Polygon stock quote backup failed for {symbol}: {e}")
    
    return None


async def fetch_options_chain(
    symbol: str,
    api_key: str = None,
    option_type: str = "call",
    max_dte: int = 45,
    min_dte: int = 1,
    current_price: float = None
) -> List[Dict]:
    """
    Fetch options chain - Yahoo primary, Polygon backup.
    Yahoo includes IV, OI, and Greeks by default.
    """
    loop = asyncio.get_event_loop()
    
    # Try Yahoo first
    options = await loop.run_in_executor(
        _yahoo_executor,
        _fetch_options_chain_yahoo_sync,
        symbol, max_dte, min_dte, option_type, current_price
    )
    
    if options and len(options) > 0:
        return options
    
    # Fallback to Polygon (basic plan - no IV/OI)
    if api_key:
        options = await _fetch_options_chain_polygon(symbol, api_key, option_type, max_dte, min_dte, current_price)
        if options:
            return options
    
    return []


async def _fetch_options_chain_polygon(
    symbol: str,
    api_key: str,
    option_type: str = "call",
    max_dte: int = 45,
    min_dte: int = 1,
    current_price: float = None
) -> List[Dict]:
    """Polygon options chain backup (no IV/OI in basic plan)"""
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            # Get contracts
            today = datetime.now()
            min_expiry = (today + timedelta(days=min_dte)).strftime('%Y-%m-%d')
            max_expiry = (today + timedelta(days=max_dte)).strftime('%Y-%m-%d')
            
            response = await client.get(
                f"{POLYGON_BASE_URL}/v3/reference/options/contracts",
                params={
                    "underlying_ticker": symbol.upper(),
                    "contract_type": option_type,
                    "expiration_date.gte": min_expiry,
                    "expiration_date.lte": max_expiry,
                    "limit": 50,
                    "apiKey": api_key
                }
            )
            
            if response.status_code != 200:
                return []
            
            data = response.json()
            contracts = data.get("results", [])
            
            if not contracts:
                return []
            
            # Get prices for contracts
            options = []
            for contract in contracts[:30]:
                ticker = contract.get("ticker", "")
                strike = contract.get("strike_price", 0)
                expiry = contract.get("expiration_date", "")
                
                try:
                    price_response = await client.get(
                        f"{POLYGON_BASE_URL}/v2/aggs/ticker/{ticker}/prev",
                        params={"apiKey": api_key}
                    )
                    
                    if price_response.status_code == 200:
                        price_data = price_response.json()
                        results = price_data.get("results", [])
                        
                        if results:
                            r = results[0]
                            options.append({
                                "contract_ticker": ticker,
                                "underlying": symbol.upper(),
                                "strike": strike,
                                "expiry": expiry,
                                "dte": calculate_dte(expiry),
                                "type": option_type,
                                "close": r.get("c", 0),
                                "volume": r.get("v", 0),
                                "open_interest": 0,  # Not available in basic plan
                                "implied_volatility": 0,  # Not available in basic plan
                                "source": "polygon"
                            })
                except Exception:
                    continue
            
            return options
            
    except Exception as e:
        logging.warning(f"Polygon options chain failed for {symbol}: {e}")
        return []


async def fetch_stock_quotes_batch(symbols: List[str], api_key: str = None) -> Dict[str, Dict]:
    """Fetch stock quotes for multiple symbols in parallel."""
    if not symbols:
        return {}
    
    tasks = [fetch_stock_quote(symbol, api_key) for symbol in set(symbols)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    quotes = {}
    for result in results:
        if isinstance(result, dict) and result.get("symbol"):
            quotes[result["symbol"]] = result
    
    return quotes


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_data_source_status() -> Dict[str, Any]:
    """Get current data source configuration status."""
    return {
        "primary_source": "yahoo",
        "backup_source": "polygon",
        "market_closed": is_market_closed(),
        "last_trading_day": get_last_trading_day()
    }


# =============================================================================
# HISTORICAL DATA (for charts, etc.)
# =============================================================================

async def fetch_historical_data(
    symbol: str,
    api_key: str = None,
    days: int = 30
) -> List[Dict]:
    """Fetch historical OHLCV data - Yahoo primary."""
    try:
        import yfinance as yf
        
        def _fetch_history():
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period=f"{days}d")
            
            data = []
            for date, row in hist.iterrows():
                data.append({
                    "date": date.strftime('%Y-%m-%d'),
                    "open": round(row['Open'], 2),
                    "high": round(row['High'], 2),
                    "low": round(row['Low'], 2),
                    "close": round(row['Close'], 2),
                    "volume": int(row['Volume'])
                })
            return data
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_yahoo_executor, _fetch_history)
        
    except Exception as e:
        logging.warning(f"Historical data fetch failed for {symbol}: {e}")
        return []
