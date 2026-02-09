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

PRICING RULES:
- SELL legs: Use BID only, reject if BID is None/0/missing
- BUY legs: Use ASK only, reject if ASK is None/0/missing
- NEVER use: lastPrice, mid, theoretical price
- After hours: Use last market session quotes with timestamp

PHASE 2 (December 2025): Market Snapshot Cache
- Per-symbol cache for Custom Scans (reduces Yahoo calls by ~70%)
- TTL: 10-15 min market open, 2-4 hrs market closed
- Yahoo-safe concurrency: max 4 concurrent calls
- Does NOT affect Watchlist or Simulator (they use live data)
"""

import os
import logging
import asyncio
import httpx
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor
import pytz
import time

# =============================================================================
# CONFIGURATION
# =============================================================================
HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
POLYGON_BASE_URL = "https://api.polygon.io"

# Thread pool for blocking yfinance calls - PHASE 2: Reduced to 4 for rate safety
_yahoo_executor = ThreadPoolExecutor(max_workers=4)

# PHASE 2: Semaphore for Yahoo rate limiting (max 4 concurrent calls)
_yahoo_semaphore = asyncio.Semaphore(4)

# PHASE 2: Cache metrics tracking
_cache_metrics = {
    "hits": 0,
    "misses": 0,
    "yahoo_calls": 0,
    "last_reset": datetime.now(timezone.utc),
    "fetch_times_ms": []  # Rolling window of last 100 fetch times
}


def shutdown_executor():
    """
    Shutdown the Yahoo Finance thread pool executor.
    
    Called during application shutdown to ensure clean thread cleanup
    and prevent memory leaks on application restart.
    """
    global _yahoo_executor
    if _yahoo_executor:
        _yahoo_executor.shutdown(wait=True)
        logging.info("Yahoo Finance thread pool executor shut down")


# =============================================================================
# YAHOO FINANCE - LIVE INTRADAY PRICES (For Simulator & Watchlist ONLY)
# =============================================================================

def _fetch_live_stock_quote_yahoo_sync(symbol: str) -> Dict[str, Any]:
    """
    Fetch LIVE intraday stock quote from Yahoo Finance (blocking call).
    
    ⚠️ USE ONLY FOR: Simulator and Watchlist pages
    ❌ NEVER USE FOR: Screener (which requires previousClose only)
    
    This function returns the CURRENT market price (regularMarketPrice),
    which may be intraday, pre-market, or after-hours depending on timing.
    """
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        info = ticker.info
        
        # Get LIVE intraday price - regularMarketPrice or currentPrice
        current_price = info.get("regularMarketPrice") or info.get("currentPrice") or info.get("previousClose", 0)
        previous_close = info.get("previousClose", current_price)
        
        if not current_price or current_price <= 0:
            logging.warning(f"Yahoo live quote: No current price for {symbol}")
            return None
        
        change = current_price - previous_close if previous_close else 0
        change_pct = (change / previous_close * 100) if previous_close else 0
        
        return {
            "symbol": symbol,
            "price": round(current_price, 2),  # LIVE intraday price
            "previous_close": round(previous_close, 2),
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
            "source": "yahoo_live",
            "is_live": True
        }
    except Exception as e:
        logging.warning(f"Yahoo live stock quote failed for {symbol}: {e}")
        return None


async def fetch_live_stock_quote(symbol: str, api_key: str = None) -> Dict[str, Any]:
    """
    Fetch LIVE intraday stock quote - Yahoo primary, Polygon backup.
    
    ⚠️ USE ONLY FOR: Simulator and Watchlist pages
    ❌ NEVER USE FOR: Screener (which requires previousClose only)
    
    This is explicitly for pages that need real-time price updates.
    """
    loop = asyncio.get_event_loop()
    
    # Try Yahoo first for live price
    result = await loop.run_in_executor(_yahoo_executor, _fetch_live_stock_quote_yahoo_sync, symbol)
    
    if result and result.get("price", 0) > 0:
        return result
    
    # Fallback to previousClose-based quote
    return await fetch_stock_quote(symbol, api_key)


async def fetch_live_stock_quotes_batch(symbols: List[str], api_key: str = None) -> Dict[str, Dict]:
    """
    Fetch LIVE stock quotes for multiple symbols in parallel.
    
    ⚠️ USE ONLY FOR: Simulator and Watchlist pages
    """
    if not symbols:
        return {}
    
    tasks = [fetch_live_stock_quote(symbol, api_key) for symbol in set(symbols)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    quotes = {}
    for result in results:
        if isinstance(result, dict) and result.get("symbol"):
            quotes[result["symbol"]] = result
    
    return quotes

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
    
    THIS IS THE SINGLE SOURCE OF TRUTH FOR STOCK PRICES.
    
    Returns the PREVIOUS MARKET CLOSE price (the last COMPLETED trading day),
    even when the market is currently open. This ensures price consistency
    across all pages: Dashboard, Screener, PMCC, Pre-Computed Scans, 
    Customised Scans, Simulator, Watchlist and Admin.
    
    IMPORTANT: Yahoo's history() may include today's intraday data during
    market hours. We must select the second-to-last row when market is open
    and the last row in history matches today's date.
    
    ❌ FORBIDDEN: regularMarketPrice, currentPrice (intraday prices)
    ✅ CORRECT: Previous market close from history() with market-aware selection
    """
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        
        # Get last 5 days of history to find most recent close
        hist = ticker.history(period='5d')
        
        if hist.empty:
            logging.warning(f"Yahoo stock quote: No history for {symbol}")
            return None
        
        # Determine the correct index based on market state
        # We want the PREVIOUS market close, not today's intraday data
        eastern = pytz.timezone('US/Eastern')
        today = datetime.now(eastern).date()
        last_date = hist.index[-1].date()
        
        # Default to the last available row
        use_index = -1
        
        # If market is OPEN and the last row is from today, use second-to-last row
        # This gives us the previous market close instead of today's intraday close
        if not is_market_closed() and last_date == today:
            use_index = -2
        
        # Safety check: ensure we have enough data for the selected index
        if len(hist) >= abs(use_index):
            last_close = hist['Close'].iloc[use_index]
            last_close_date = hist.index[use_index].strftime('%Y-%m-%d')
        else:
            # Fallback to the last available row if not enough data
            last_close = hist['Close'].iloc[-1]
            last_close_date = hist.index[-1].strftime('%Y-%m-%d')
        
        if not last_close or last_close <= 0:
            logging.warning(f"Yahoo stock quote: No valid close price for {symbol}")
            return None
        
        # Get additional metadata from info
        info = ticker.info
        
        # Analyst rating
        recommendation = info.get("recommendationKey", "")
        rating_map = {
            "strong_buy": "Strong Buy",
            "buy": "Buy",
            "hold": "Hold",
            "underperform": "Sell",
            "sell": "Sell"
        }
        analyst_rating = rating_map.get(recommendation, recommendation.replace("_", " ").title() if recommendation else None)
        
        # Market cap
        market_cap = info.get("marketCap", 0)
        
        # Average volume
        avg_volume = info.get("averageVolume", 0) or info.get("averageDailyVolume10Day", 0)
        
        # Earnings date
        earnings_timestamp = info.get("earningsTimestamp") or info.get("earningsTimestampStart")
        earnings_date = None
        if earnings_timestamp:
            try:
                earnings_date = datetime.fromtimestamp(earnings_timestamp).strftime('%Y-%m-%d')
            except:
                pass
        
        return {
            "symbol": symbol,
            "price": round(float(last_close), 2),  # Most recent market close
            "previous_close": round(float(last_close), 2),
            "close_date": last_close_date,  # Date of the close price
            "analyst_rating": analyst_rating,
            "market_cap": market_cap,
            "avg_volume": avg_volume,
            "earnings_date": earnings_date,
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
                    # PRICING RULES:
                    # - SELL legs → BID only (reject if BID is None/0/missing)
                    # - BUY legs → ASK only (reject if ASK is None/0/missing)
                    # NEVER use: lastPrice, mid, theoretical price
                    bid = row.get('bid', 0) if row.get('bid') and not (hasattr(row.get('bid'), '__len__') and len(row.get('bid')) == 0) else 0
                    ask = row.get('ask', 0) if row.get('ask') and not (hasattr(row.get('ask'), '__len__') and len(row.get('ask')) == 0) else 0
                    
                    # Handle NaN values
                    import math
                    if bid and isinstance(bid, float) and math.isnan(bid):
                        bid = 0
                    if ask and isinstance(ask, float) and math.isnan(ask):
                        ask = 0
                    
                    # Build contract symbol for caching
                    contract_symbol = row.get('contractSymbol', '')
                    
                    # Determine quote source and validity
                    # During market hours: require live BID/ASK
                    # After hours: accept any non-zero BID/ASK (will be marked as last session)
                    quote_source = "LIVE"
                    quote_timestamp = datetime.now(timezone.utc).isoformat()
                    
                    # Check if we have valid quotes
                    has_valid_bid = bid and bid > 0
                    has_valid_ask = ask and ask > 0
                    
                    # Skip if no pricing at all
                    if not has_valid_bid and not has_valid_ask:
                        continue
                    
                    # Get IV and OI
                    iv = row.get('impliedVolatility', 0)
                    oi = row.get('openInterest', 0)
                    volume = row.get('volume', 0)
                    
                    # Skip if IV is unrealistic (< 1% or > 500%)
                    if iv and (iv < 0.01 or iv > 5.0):
                        iv = 0
                    
                    options.append({
                        "contract_ticker": contract_symbol,
                        "underlying": symbol,
                        "strike": float(strike),
                        "expiry": expiry,
                        "dte": dte,
                        "type": option_type,
                        "bid": float(bid) if bid else 0,
                        "ask": float(ask) if ask else 0,
                        "volume": int(volume) if volume else 0,
                        "open_interest": int(oi) if oi else 0,
                        "implied_volatility": float(iv) if iv else 0,
                        "quote_source": quote_source,
                        "quote_timestamp": quote_timestamp,
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


async def fetch_options_with_cache(
    symbol: str,
    db,
    option_type: str = "call",
    max_dte: int = 45,
    min_dte: int = 1,
    current_price: float = None
) -> List[Dict[str, Any]]:
    """
    Fetch options chain with quote caching for after-hours support.
    
    AFTER-HOURS LOGIC:
    1. During market hours: Cache valid BID/ASK quotes
    2. After hours: Use cached quotes from last market session
    3. All quotes marked with source and timestamp
    
    Returns options with:
    - quote_source: "LIVE" or "LAST_MARKET_SESSION"
    - quote_timestamp: When the quote was captured
    - quote_age_hours: How old the quote is (after hours only)
    """
    from services.quote_cache_service import get_quote_cache
    
    quote_cache = get_quote_cache(db)
    market_info = quote_cache.get_market_session_info()
    is_market_open = market_info["is_open"]
    
    # Fetch live options
    live_options = await fetch_options_chain(
        symbol=symbol,
        api_key=None,
        option_type=option_type,
        max_dte=max_dte,
        min_dte=min_dte,
        current_price=current_price
    )
    
    enriched_options = []
    
    for opt in live_options:
        contract = opt.get("contract_ticker", "")
        bid = opt.get("bid", 0)
        ask = opt.get("ask", 0)
        
        # Cache valid quotes during market hours
        if is_market_open and (bid > 0 or ask > 0):
            await quote_cache.cache_valid_quote(
                contract_symbol=contract,
                symbol=symbol,
                strike=opt.get("strike", 0),
                expiry=opt.get("expiry", ""),
                bid=bid,
                ask=ask,
                dte=opt.get("dte", 0)
            )
        
        # Determine final quote source
        if is_market_open:
            # During market hours, use live data
            opt["quote_source"] = "LIVE"
            opt["quote_timestamp"] = datetime.now(timezone.utc).isoformat()
        else:
            # After hours, mark as last market session
            opt["quote_source"] = "LAST_MARKET_SESSION"
            opt["quote_age_hours"] = market_info.get("hours_since_close", 0)
        
        enriched_options.append(opt)
    
    # If after hours and no live options, try cache
    if not is_market_open and not enriched_options:
        # Attempt to get cached quotes
        cached_quotes = await db.option_quote_cache.find({
            "symbol": symbol,
            "dte": {"$gte": min_dte, "$lte": max_dte}
        }, {"_id": 0}).to_list(200)
        
        for cached in cached_quotes:
            if option_type == "call":
                # For calls, we need at least one valid quote
                if cached.get("bid", 0) <= 0 and cached.get("ask", 0) <= 0:
                    continue
            
            cached["quote_source"] = "LAST_MARKET_SESSION"
            cached["quote_age_hours"] = market_info.get("hours_since_close", 0)
            if cached.get("quote_timestamp"):
                cached["quote_timestamp"] = cached["quote_timestamp"].isoformat()
            
            enriched_options.append(cached)
    
    logging.info(f"Options with cache: {len(enriched_options)} {option_type} options for {symbol} (market_open={is_market_open})")
    return enriched_options


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


# =============================================================================
# PHASE 2: MARKET SNAPSHOT CACHE FOR CUSTOM SCANS
# =============================================================================
# This cache reduces Yahoo Finance calls by ~70% for Custom Scans
# Does NOT affect Watchlist or Simulator (they bypass cache for live data)

# Cache TTL configuration
CACHE_TTL_MARKET_OPEN_MIN = 12  # 12 minutes during market hours
CACHE_TTL_MARKET_CLOSED_HOURS = 3  # 3 hours after market close

# MongoDB collection name
SNAPSHOT_CACHE_COLLECTION = "market_snapshot_cache"


def _get_cache_ttl_seconds() -> int:
    """Get appropriate cache TTL based on market status."""
    if is_market_closed():
        return CACHE_TTL_MARKET_CLOSED_HOURS * 3600  # Convert hours to seconds
    else:
        return CACHE_TTL_MARKET_OPEN_MIN * 60  # Convert minutes to seconds


async def _get_cached_snapshot(db, symbol: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve cached snapshot for a symbol if not stale.
    
    Returns None if:
    - No cache entry exists
    - Cache entry is stale (past TTL)
    """
    try:
        cached = await db[SNAPSHOT_CACHE_COLLECTION].find_one(
            {"symbol": symbol.upper()},
            {"_id": 0}
        )
        
        if not cached:
            return None
        
        # Check if cache is stale
        cached_at = cached.get("cached_at")
        if not cached_at:
            return None
        
        # Handle both datetime and string formats
        if isinstance(cached_at, str):
            cached_at = datetime.fromisoformat(cached_at.replace('Z', '+00:00'))
        
        # Ensure cached_at is timezone-aware
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=timezone.utc)
        
        ttl_seconds = _get_cache_ttl_seconds()
        age_seconds = (datetime.now(timezone.utc) - cached_at).total_seconds()
        
        if age_seconds > ttl_seconds:
            logging.debug(f"Cache stale for {symbol}: age={age_seconds:.0f}s, ttl={ttl_seconds}s")
            return None
        
        logging.debug(f"Cache hit for {symbol}: age={age_seconds:.0f}s")
        return cached
        
    except Exception as e:
        logging.warning(f"Error reading cache for {symbol}: {e}")
        return None


async def _store_snapshot_cache(
    db, 
    symbol: str, 
    stock_data: Dict[str, Any],
    options_metadata: Optional[Dict[str, Any]] = None
) -> None:
    """
    Store symbol snapshot in cache.
    
    Stores:
    - Stock price, fundamentals
    - Options metadata (expiry dates, basic chain info)
    """
    try:
        cache_doc = {
            "symbol": symbol.upper(),
            "cached_at": datetime.now(timezone.utc),
            "ttl_seconds": _get_cache_ttl_seconds(),
            "market_status": "closed" if is_market_closed() else "open",
            
            # Stock data
            "price": stock_data.get("price", 0),
            "previous_close": stock_data.get("previous_close", 0),
            "close_date": stock_data.get("close_date"),
            "analyst_rating": stock_data.get("analyst_rating"),
            "market_cap": stock_data.get("market_cap", 0),
            "avg_volume": stock_data.get("avg_volume", 0),
            "earnings_date": stock_data.get("earnings_date"),
            "source": stock_data.get("source", "yahoo"),
            
            # Options metadata (if provided)
            "options_metadata": options_metadata
        }
        
        await db[SNAPSHOT_CACHE_COLLECTION].update_one(
            {"symbol": symbol.upper()},
            {"$set": cache_doc},
            upsert=True
        )
        
        logging.debug(f"Cached snapshot for {symbol}")
        
    except Exception as e:
        logging.warning(f"Error caching snapshot for {symbol}: {e}")


async def get_symbol_snapshot(
    db,
    symbol: str,
    api_key: str = None,
    include_options: bool = False,
    max_dte: int = 45,
    min_dte: int = 1
) -> Dict[str, Any]:
    """
    PHASE 2: Cache-first symbol snapshot for Custom Scans.
    
    This function:
    1. Checks cache first
    2. Only fetches from Yahoo if cache is stale/missing
    3. Respects Yahoo rate limits via semaphore
    4. Tracks metrics for monitoring
    
    ⚠️ USE FOR: Custom Scans (screener.py)
    ❌ DO NOT USE FOR: Watchlist, Simulator (they need live data)
    
    Args:
        db: MongoDB database instance
        symbol: Stock symbol
        api_key: Optional Polygon API key for backup
        include_options: Whether to fetch options chain
        max_dte: Maximum DTE for options (if include_options=True)
        min_dte: Minimum DTE for options (if include_options=True)
    
    Returns:
        Dict with stock_data and optionally options_data
    """
    global _cache_metrics
    
    symbol = symbol.upper()
    result = {
        "symbol": symbol,
        "stock_data": None,
        "options_data": None,
        "from_cache": False,
        "fetch_time_ms": 0
    }
    
    start_time = time.time()
    
    # Step 1: Check cache
    cached = await _get_cached_snapshot(db, symbol)
    
    if cached and cached.get("price", 0) > 0:
        _cache_metrics["hits"] += 1
        
        # Reconstruct stock_data from cache
        result["stock_data"] = {
            "symbol": symbol,
            "price": cached.get("price", 0),
            "previous_close": cached.get("previous_close", 0),
            "close_date": cached.get("close_date"),
            "analyst_rating": cached.get("analyst_rating"),
            "market_cap": cached.get("market_cap", 0),
            "avg_volume": cached.get("avg_volume", 0),
            "earnings_date": cached.get("earnings_date"),
            "source": cached.get("source", "yahoo_cached")
        }
        result["from_cache"] = True
        
        # If options not needed or available in cache, return early
        if not include_options or (cached.get("options_metadata") and not include_options):
            result["fetch_time_ms"] = (time.time() - start_time) * 1000
            return result
    
    # Step 2: Cache miss - fetch from Yahoo with rate limiting
    _cache_metrics["misses"] += 1
    
    async with _yahoo_semaphore:  # Rate limit Yahoo calls
        _cache_metrics["yahoo_calls"] += 1
        
        # Fetch stock data
        if not result["stock_data"]:
            stock_data = await fetch_stock_quote(symbol, api_key)
            
            if stock_data and stock_data.get("price", 0) > 0:
                result["stock_data"] = stock_data
                
                # Store in cache
                await _store_snapshot_cache(db, symbol, stock_data)
            else:
                result["fetch_time_ms"] = (time.time() - start_time) * 1000
                return result
        
        # Fetch options if requested
        if include_options:
            current_price = result["stock_data"].get("price", 0)
            options_data = await fetch_options_chain(
                symbol, api_key, "call", max_dte, min_dte, current_price
            )
            
            if options_data:
                result["options_data"] = options_data
                
                # Update cache with options metadata
                options_metadata = {
                    "count": len(options_data),
                    "expiries": list(set(opt.get("expiry", "") for opt in options_data)),
                    "fetched_at": datetime.now(timezone.utc).isoformat()
                }
                await _store_snapshot_cache(
                    db, symbol, result["stock_data"], options_metadata
                )
    
    # Track fetch time
    fetch_time_ms = (time.time() - start_time) * 1000
    result["fetch_time_ms"] = fetch_time_ms
    
    # Update rolling metrics (keep last 100)
    _cache_metrics["fetch_times_ms"].append(fetch_time_ms)
    if len(_cache_metrics["fetch_times_ms"]) > 100:
        _cache_metrics["fetch_times_ms"] = _cache_metrics["fetch_times_ms"][-100:]
    
    return result


async def get_symbol_snapshots_batch(
    db,
    symbols: List[str],
    api_key: str = None,
    include_options: bool = False,
    max_dte: int = 45,
    min_dte: int = 1,
    batch_size: int = 10
) -> Dict[str, Dict]:
    """
    PHASE 2: Batch fetch symbol snapshots with cache-first approach.
    
    Processes symbols in batches to avoid overwhelming Yahoo Finance.
    Uses semaphore to limit concurrent Yahoo calls to 4.
    
    Args:
        db: MongoDB database instance
        symbols: List of stock symbols
        api_key: Optional Polygon API key
        include_options: Whether to fetch options chains
        max_dte: Maximum DTE for options
        min_dte: Minimum DTE for options
        batch_size: Number of symbols to process per batch
    
    Returns:
        Dict mapping symbol -> snapshot data
    """
    if not symbols:
        return {}
    
    results = {}
    unique_symbols = list(set(s.upper() for s in symbols))
    
    # Process in batches
    for i in range(0, len(unique_symbols), batch_size):
        batch = unique_symbols[i:i + batch_size]
        
        # Fetch batch concurrently (semaphore limits Yahoo calls)
        tasks = [
            get_symbol_snapshot(db, symbol, api_key, include_options, max_dte, min_dte)
            for symbol in batch
        ]
        
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for j, result in enumerate(batch_results):
            if isinstance(result, dict) and result.get("stock_data"):
                symbol = batch[j]
                results[symbol] = result
            elif isinstance(result, Exception):
                logging.warning(f"Error fetching snapshot for {batch[j]}: {result}")
        
        # Small delay between batches for rate safety
        if i + batch_size < len(unique_symbols):
            await asyncio.sleep(0.5)
    
    return results


def get_cache_metrics() -> Dict[str, Any]:
    """
    Get cache performance metrics for Admin dashboard.
    
    Returns:
        Dict with hit_rate, yahoo_calls_per_hour, avg_fetch_time_ms
    """
    global _cache_metrics
    
    total_requests = _cache_metrics["hits"] + _cache_metrics["misses"]
    hit_rate = (_cache_metrics["hits"] / total_requests * 100) if total_requests > 0 else 0
    
    # Calculate Yahoo calls per hour
    time_since_reset = (datetime.now(timezone.utc) - _cache_metrics["last_reset"]).total_seconds()
    hours_elapsed = max(time_since_reset / 3600, 0.01)  # Avoid division by zero
    yahoo_calls_per_hour = _cache_metrics["yahoo_calls"] / hours_elapsed
    
    # Calculate average fetch time
    fetch_times = _cache_metrics["fetch_times_ms"]
    avg_fetch_time = sum(fetch_times) / len(fetch_times) if fetch_times else 0
    
    return {
        "cache_hits": _cache_metrics["hits"],
        "cache_misses": _cache_metrics["misses"],
        "total_requests": total_requests,
        "hit_rate_pct": round(hit_rate, 1),
        "yahoo_calls": _cache_metrics["yahoo_calls"],
        "yahoo_calls_per_hour": round(yahoo_calls_per_hour, 1),
        "avg_fetch_time_ms": round(avg_fetch_time, 1),
        "market_status": "closed" if is_market_closed() else "open",
        "cache_ttl_seconds": _get_cache_ttl_seconds(),
        "time_since_reset_hours": round(hours_elapsed, 2)
    }


def reset_cache_metrics() -> Dict[str, Any]:
    """Reset cache metrics (for Admin use)."""
    global _cache_metrics
    
    old_metrics = get_cache_metrics()
    
    _cache_metrics = {
        "hits": 0,
        "misses": 0,
        "yahoo_calls": 0,
        "last_reset": datetime.now(timezone.utc),
        "fetch_times_ms": []
    }
    
    return {
        "message": "Cache metrics reset",
        "previous_metrics": old_metrics
    }


async def clear_snapshot_cache(db, symbol: str = None) -> Dict[str, Any]:
    """
    Clear snapshot cache entries.
    
    Args:
        db: MongoDB database instance
        symbol: Optional specific symbol to clear (clears all if None)
    
    Returns:
        Dict with deleted count
    """
    try:
        if symbol:
            result = await db[SNAPSHOT_CACHE_COLLECTION].delete_one({"symbol": symbol.upper()})
            return {"deleted": result.deleted_count, "symbol": symbol.upper()}
        else:
            result = await db[SNAPSHOT_CACHE_COLLECTION].delete_many({})
            return {"deleted": result.deleted_count, "scope": "all"}
    except Exception as e:
        logging.error(f"Error clearing cache: {e}")
        return {"error": str(e)}


async def get_cache_status(db) -> Dict[str, Any]:
    """
    Get detailed cache status for Admin dashboard.
    
    Returns cache metrics + collection statistics.
    """
    try:
        # Get collection stats
        cache_count = await db[SNAPSHOT_CACHE_COLLECTION].count_documents({})
        
        # Get sample of recent entries
        recent_entries = await db[SNAPSHOT_CACHE_COLLECTION].find(
            {},
            {"symbol": 1, "cached_at": 1, "price": 1, "_id": 0}
        ).sort("cached_at", -1).limit(10).to_list(10)
        
        # Calculate cache age distribution
        now = datetime.now(timezone.utc)
        stale_count = 0
        fresh_count = 0
        ttl_seconds = _get_cache_ttl_seconds()
        
        async for doc in db[SNAPSHOT_CACHE_COLLECTION].find({}, {"cached_at": 1}):
            cached_at = doc.get("cached_at")
            if cached_at:
                if isinstance(cached_at, str):
                    cached_at = datetime.fromisoformat(cached_at.replace('Z', '+00:00'))
                # Ensure timezone-aware
                if cached_at.tzinfo is None:
                    cached_at = cached_at.replace(tzinfo=timezone.utc)
                age = (now - cached_at).total_seconds()
                if age > ttl_seconds:
                    stale_count += 1
                else:
                    fresh_count += 1
        
        return {
            **get_cache_metrics(),
            "collection_stats": {
                "total_entries": cache_count,
                "fresh_entries": fresh_count,
                "stale_entries": stale_count
            },
            "recent_entries": recent_entries
        }
        
    except Exception as e:
        logging.error(f"Error getting cache status: {e}")
        return {
            **get_cache_metrics(),
            "error": str(e)
        }

