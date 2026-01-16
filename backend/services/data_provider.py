"""
Centralized Data Provider Service
=================================
PRIMARY DATA SOURCE: Yahoo Finance (yfinance)
BACKUP DATA SOURCE: Polygon/Massive (free tier)

T-1 DATA PRINCIPLE (STRICT):
- All data fetches return T-1 (previous trading day) market close data
- No intraday or partial data is ever used
- This ensures consistency across all scans and calculations

Yahoo Finance provides:
- Stock quotes (previous close - T-1)
- Options chains with IV, OI, Greeks built-in

Polygon provides:
- Backup for stock quotes when Yahoo fails
- Options aggregates (no IV/OI in basic plan)

This is the SINGLE SOURCE OF TRUTH for data sourcing logic.
All screeners and pages should use these functions for consistency.
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor
import asyncio
import httpx
import pytz

# Import trading calendar for T-1 date management
from services.trading_calendar import (
    get_t_minus_1,
    get_market_data_status,
    is_valid_expiration_date,
    filter_valid_expirations,
    calculate_dte_from_t1,
    get_data_freshness_status
)

# =============================================================================
# CONFIGURATION
# =============================================================================
HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
POLYGON_BASE_URL = "https://api.polygon.io"
EASTERN_TZ = pytz.timezone('US/Eastern')

# Thread pool for blocking yfinance calls
_yahoo_executor = ThreadPoolExecutor(max_workers=8)

logger = logging.getLogger(__name__)


# =============================================================================
# T-1 DATA ACCESS (PRIMARY INTERFACE)
# =============================================================================

def get_data_date() -> str:
    """
    Get the date for which all data should be fetched (T-1).
    
    This is the single source of truth for data date across all components.
    """
    t1_date, _ = get_t_minus_1()
    return t1_date


def is_market_closed() -> bool:
    """
    Check if US stock market is currently closed.
    
    Note: For T-1 data principle, market is always considered "closed" 
    since we only use previous trading day data.
    """
    status = get_market_data_status()
    return True  # Always return True - we always use T-1 data


def get_last_trading_day() -> str:
    """
    Get the last trading day date string (YYYY-MM-DD).
    This is an alias for get_data_date() for backward compatibility.
    """
    return get_data_date()


# =============================================================================
# YAHOO FINANCE - PRIMARY DATA SOURCE (T-1 DATA)
# =============================================================================

def _fetch_stock_quote_yahoo_sync(symbol: str) -> Dict[str, Any]:
    """
    Fetch T-1 stock quote from Yahoo Finance (blocking call).
    Always returns previous trading day close data.
    """
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        info = ticker.info
        
        # T-1 Data: Use previous close as the primary price
        # This ensures consistency with the T-1 data principle
        previous_close = info.get("previousClose", 0)
        regular_price = info.get("regularMarketPrice") or info.get("currentPrice", 0)
        
        # For T-1, we want the previous close
        price = previous_close if previous_close > 0 else regular_price
        
        if price == 0:
            return None
        
        # Calculate change from day before T-1
        open_price = info.get("open", price)
        change = price - open_price if open_price else 0
        change_pct = (change / open_price * 100) if open_price else 0
        
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
        
        # Get next earnings date
        earnings_date = None
        days_to_earnings = None
        try:
            calendar = ticker.calendar
            if calendar is not None and 'Earnings Date' in calendar:
                earnings_dates = calendar['Earnings Date']
                if len(earnings_dates) > 0:
                    next_earnings = earnings_dates[0]
                    if hasattr(next_earnings, 'date'):
                        earnings_date = next_earnings.date().isoformat()
                    else:
                        earnings_date = str(next_earnings)[:10]
                    
                    # Calculate days to earnings from T-1
                    if earnings_date:
                        t1_date_str = get_data_date()
                        t1_date = datetime.strptime(t1_date_str, "%Y-%m-%d")
                        earnings_dt = datetime.strptime(earnings_date, "%Y-%m-%d")
                        days_to_earnings = (earnings_dt - t1_date).days
        except Exception:
            pass
        
        t1_date = get_data_date()
        
        return {
            "symbol": symbol,
            "price": round(price, 2),
            "previous_close": round(previous_close, 2) if previous_close else round(price, 2),
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
            "analyst_rating": analyst_rating,
            "earnings_date": earnings_date,
            "days_to_earnings": days_to_earnings,
            "source": "yahoo",
            "data_date": t1_date,
            "data_type": "t_minus_1_close"
        }
    except Exception as e:
        logger.warning(f"Yahoo stock quote failed for {symbol}: {e}")
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
    Returns T-1 options data with IV, OI, and Greeks built-in.
    
    Filters out invalid expiration dates (weekends, holidays).
    """
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        
        # Get current price if not provided (T-1 close)
        if not current_price:
            info = ticker.info
            current_price = info.get("previousClose") or info.get("regularMarketPrice") or info.get("currentPrice", 0)
        
        if not current_price:
            return []
        
        # Get available expirations
        try:
            expirations = ticker.options
        except Exception:
            return []
        
        if not expirations:
            return []
        
        # Filter out invalid expirations (weekends, holidays)
        valid_expirations = filter_valid_expirations(list(expirations))
        
        if not valid_expirations:
            logger.warning(f"No valid expirations found for {symbol} after filtering")
            return []
        
        # Get T-1 date for DTE calculation
        t1_date_str = get_data_date()
        t1_date = datetime.strptime(t1_date_str, '%Y-%m-%d')
        
        # Filter expirations within DTE range (calculated from T-1)
        valid_expiries = []
        for exp_str in valid_expirations:
            try:
                exp_date = datetime.strptime(exp_str, "%Y-%m-%d")
                dte = (exp_date - t1_date).days
                if min_dte <= dte <= max_dte:
                    valid_expiries.append((exp_str, dte))
            except Exception:
                continue
        
        if not valid_expiries:
            return []
        
        options = []
        
        # Fetch options for each valid expiry (limit to 3 for performance)
        for expiry, dte in valid_expiries[:3]:
            try:
                opt_chain = ticker.option_chain(expiry)
                chain_data = opt_chain.calls if option_type == "call" else opt_chain.puts
                
                for _, row in chain_data.iterrows():
                    strike = row.get('strike', 0)
                    if not strike:
                        continue
                    
                    # Filter strikes based on moneyness
                    if option_type == "call":
                        # For calls, focus on ATM to OTM
                        if strike < current_price * 0.95 or strike > current_price * 1.15:
                            continue
                    else:
                        # For puts, focus on ATM to OTM
                        if strike > current_price * 1.05 or strike < current_price * 0.85:
                            continue
                    
                    # Get premium - use last price or mid of bid/ask
                    last_price = row.get('lastPrice', 0)
                    bid = row.get('bid', 0)
                    ask = row.get('ask', 0)
                    premium = last_price if last_price > 0 else ((bid + ask) / 2 if bid > 0 and ask > 0 else 0)
                    
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
                        "source": "yahoo",
                        "data_date": t1_date_str,
                        "data_type": "t_minus_1_close"
                    })
                    
            except Exception as e:
                logger.debug(f"Error fetching {symbol} options for {expiry}: {e}")
                continue
        
        logger.info(f"Yahoo: fetched {len(options)} {option_type} options for {symbol} (T-1: {t1_date_str})")
        return options
        
    except Exception as e:
        logger.warning(f"Yahoo options chain failed for {symbol}: {e}")
        return []


async def fetch_stock_quote(symbol: str, api_key: str = None) -> Dict[str, Any]:
    """
    Fetch T-1 stock quote - Yahoo primary, Polygon backup.
    Always returns previous trading day close data.
    """
    loop = asyncio.get_event_loop()
    
    # Try Yahoo first
    result = await loop.run_in_executor(_yahoo_executor, _fetch_stock_quote_yahoo_sync, symbol)
    
    if result and result.get("price", 0) > 0:
        return result
    
    # Fallback to Polygon
    if api_key:
        try:
            t1_date = get_data_date()
            
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                # Use previous day aggregates for T-1 data
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
                            "source": "polygon",
                            "data_date": t1_date,
                            "data_type": "t_minus_1_close"
                        }
        except Exception as e:
            logger.debug(f"Polygon stock quote backup failed for {symbol}: {e}")
    
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
    Fetch T-1 options chain - Yahoo primary, Polygon backup.
    Yahoo includes IV, OI, and Greeks by default.
    
    All expiration dates are validated to exclude weekends and holidays.
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
        t1_date_str = get_data_date()
        t1_date = datetime.strptime(t1_date_str, '%Y-%m-%d')
        
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            # Get contracts - calculate from T-1
            min_expiry = (t1_date + timedelta(days=min_dte)).strftime('%Y-%m-%d')
            max_expiry = (t1_date + timedelta(days=max_dte)).strftime('%Y-%m-%d')
            
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
            
            # Filter out invalid expiration dates
            valid_contracts = []
            for contract in contracts:
                expiry = contract.get("expiration_date", "")
                is_valid, _ = is_valid_expiration_date(expiry)
                if is_valid:
                    valid_contracts.append(contract)
            
            # Get prices for contracts
            options = []
            for contract in valid_contracts[:30]:
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
                            dte = calculate_dte_from_t1(expiry)
                            options.append({
                                "contract_ticker": ticker,
                                "underlying": symbol.upper(),
                                "strike": strike,
                                "expiry": expiry,
                                "dte": dte,
                                "type": option_type,
                                "close": r.get("c", 0),
                                "volume": r.get("v", 0),
                                "open_interest": 0,  # Not available in basic plan
                                "implied_volatility": 0,  # Not available in basic plan
                                "source": "polygon",
                                "data_date": t1_date_str,
                                "data_type": "t_minus_1_close"
                            })
                except Exception:
                    continue
            
            return options
            
    except Exception as e:
        logger.warning(f"Polygon options chain failed for {symbol}: {e}")
        return []


async def fetch_stock_quotes_batch(symbols: List[str], api_key: str = None) -> Dict[str, Dict]:
    """Fetch T-1 stock quotes for multiple symbols in parallel."""
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
    """Get current data source configuration and T-1 status."""
    status = get_market_data_status()
    
    return {
        "primary_source": "yahoo",
        "backup_source": "polygon",
        "data_principle": "T-1 (Previous Trading Day Close)",
        "t_minus_1_date": status["t_minus_1_date"],
        "data_age_hours": status["data_age_hours"],
        "next_data_refresh": status["next_data_refresh"],
        "current_time_et": status["current_time_et"]
    }


def calculate_dte(expiry_date: str) -> int:
    """
    Calculate days to expiration from T-1 date.
    Use this for consistent DTE calculations.
    """
    return calculate_dte_from_t1(expiry_date)


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
            for date_idx, row in hist.iterrows():
                data.append({
                    "date": date_idx.strftime('%Y-%m-%d'),
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
        logger.warning(f"Historical data fetch failed for {symbol}: {e}")
        return []
