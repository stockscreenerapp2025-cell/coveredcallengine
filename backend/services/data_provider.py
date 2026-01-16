"""
Centralized Data Provider Service
=================================
PRIMARY DATA SOURCE: Yahoo Finance (yfinance)
BACKUP DATA SOURCE: Polygon/Massive (free tier)

TWO-SOURCE DATA MODEL (AUTHORITATIVE SPEC):
1. EQUITY PRICE (Hard Rule):
   - Always use T-1 market close
   - Non-negotiable

2. OPTIONS CHAIN DATA (Flexible but Controlled):
   - Use latest fully available option chain snapshot
   - Snapshot must be complete (no missing strikes for expiry)
   - Snapshot must be consistent (IV + Greeks present)
   - Snapshot timestamp must be ≤ T market open
   - Never use partial intraday chains

3. STALENESS RULES:
   - 🟢 Fresh: snapshot ≤ 24h old
   - 🟠 Stale: 24-48h old
   - 🔴 Invalid: >48h old → exclude from scans

4. MANDATORY METADATA:
   - Equity Price Date: e.g., "Jan 15, 2026 (T-1 close)"
   - Options Chain Snapshot: e.g., "As of: Jan 14, 2026 22:10 ET"
   - These may not always match, and that is acceptable

5. ROI & GREEKS CALCULATION:
   - Use equity price = T-1 close
   - Use options premium = snapshot value
   - Use Greeks = snapshot Greeks (vendor-supplied, point-in-time)
   - Do NOT recompute Greeks using T-1 price
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
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
    get_data_freshness_status,
    is_friday_expiration,
    is_monthly_expiration,
    categorize_expirations,
    get_option_chain_staleness,
    validate_option_chain_data,
    get_data_metadata
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
    Get the date for which EQUITY data should be fetched (T-1).
    This is the single source of truth for equity price date.
    """
    t1_date, _ = get_t_minus_1()
    return t1_date


def is_market_closed() -> bool:
    """Always return True - we always use T-1 equity data."""
    return True


def get_last_trading_day() -> str:
    """Alias for get_data_date() for backward compatibility."""
    return get_data_date()


# =============================================================================
# AVAILABLE OPTIONS CHAIN EXPIRATIONS (CRITICAL)
# =============================================================================

def _get_available_expirations_yahoo_sync(symbol: str) -> Tuple[List[str], datetime]:
    """
    Get ACTUAL available option expirations from Yahoo Finance.
    
    This is CRITICAL - we can only use expirations that actually exist.
    
    Returns:
        Tuple of (list of available expiration dates, snapshot timestamp)
    """
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        
        # Get available expirations directly from Yahoo
        expirations = ticker.options
        
        if not expirations:
            logger.warning(f"No options available for {symbol}")
            return [], datetime.now(EASTERN_TZ)
        
        # Filter to only Friday expirations and valid trading days
        valid_expirations = filter_valid_expirations(list(expirations), friday_only=True)
        
        # Snapshot timestamp is now (when we fetched)
        snapshot_time = datetime.now(EASTERN_TZ)
        
        logger.info(f"Available expirations for {symbol}: {len(valid_expirations)} (Friday-only)")
        return valid_expirations, snapshot_time
        
    except Exception as e:
        logger.error(f"Failed to get expirations for {symbol}: {e}")
        return [], datetime.now(EASTERN_TZ)


async def get_available_expirations(symbol: str) -> Dict[str, Any]:
    """
    Get available option expirations with categorization.
    
    Returns:
        Dict with weekly, monthly expirations and metadata
    """
    loop = asyncio.get_event_loop()
    expirations, snapshot_time = await loop.run_in_executor(
        _yahoo_executor, _get_available_expirations_yahoo_sync, symbol
    )
    
    # Categorize into weekly vs monthly
    categorized = categorize_expirations(expirations)
    
    # Calculate DTE for each
    t1_date_str = get_data_date()
    t1_date = datetime.strptime(t1_date_str, '%Y-%m-%d')
    
    weekly_with_dte = []
    for exp in categorized["weekly"]:
        exp_date = datetime.strptime(exp, '%Y-%m-%d')
        dte = (exp_date - t1_date).days
        weekly_with_dte.append({"expiry": exp, "dte": dte, "type": "weekly"})
    
    monthly_with_dte = []
    for exp in categorized["monthly"]:
        exp_date = datetime.strptime(exp, '%Y-%m-%d')
        dte = (exp_date - t1_date).days
        monthly_with_dte.append({"expiry": exp, "dte": dte, "type": "monthly"})
    
    return {
        "symbol": symbol,
        "weekly": weekly_with_dte,
        "monthly": monthly_with_dte,
        "all_expirations": expirations,
        "snapshot_time": snapshot_time.strftime('%Y-%m-%d %H:%M:%S ET'),
        "t1_date": t1_date_str
    }


# =============================================================================
# YAHOO FINANCE - PRIMARY DATA SOURCE
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
            "equity_price_date": t1_date,
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
    current_price: float = None,
    friday_only: bool = True,
    require_complete_data: bool = True,
    is_leaps: bool = False
) -> Tuple[List[Dict], Dict[str, Any]]:
    """
    Fetch options chain from Yahoo Finance with STRICT validation.
    
    CRITICAL RULES:
    1. Only use expirations that ACTUALLY exist in Yahoo
    2. Only include Friday expirations (standard weeklies)
    3. Reject options with missing IV, OI, or premium
    4. Track snapshot timestamp for metadata
    
    Args:
        symbol: Stock symbol
        max_dte: Maximum days to expiration
        min_dte: Minimum days to expiration
        option_type: "call" or "put"
        current_price: Current stock price (T-1 close)
        friday_only: Only include Friday expirations
        require_complete_data: Reject options missing IV/OI
        is_leaps: If True, use wider strike range for deep ITM LEAPS
    
    Returns:
        Tuple of (list of options, metadata dict)
    """
    snapshot_time = datetime.now(EASTERN_TZ)
    metadata = {
        "snapshot_time": snapshot_time.strftime('%Y-%m-%d %H:%M:%S ET'),
        "source": "yahoo",
        "options_fetched": 0,
        "options_rejected": 0,
        "rejection_reasons": {}
    }
    
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        
        # Get current price if not provided (T-1 close)
        if not current_price:
            info = ticker.info
            current_price = info.get("previousClose") or info.get("regularMarketPrice") or info.get("currentPrice", 0)
        
        if not current_price:
            metadata["error"] = "No price data available"
            return [], metadata
        
        # Get ACTUAL available expirations from Yahoo
        try:
            available_expirations = ticker.options
        except Exception:
            metadata["error"] = "Failed to get expirations"
            return [], metadata
        
        if not available_expirations:
            metadata["error"] = "No options available"
            return [], metadata
        
        # Filter to valid trading days and optionally Friday-only
        valid_expirations = filter_valid_expirations(list(available_expirations), friday_only=friday_only)
        
        if not valid_expirations:
            metadata["error"] = "No valid expirations after filtering"
            return [], metadata
        
        # Get T-1 date for DTE calculation
        t1_date_str = get_data_date()
        t1_date = datetime.strptime(t1_date_str, '%Y-%m-%d')
        
        # Filter expirations within DTE range
        valid_expiries = []
        for exp_str in valid_expirations:
            try:
                exp_date = datetime.strptime(exp_str, "%Y-%m-%d")
                dte = (exp_date - t1_date).days
                if min_dte <= dte <= max_dte:
                    is_monthly = is_monthly_expiration(exp_str)
                    valid_expiries.append({
                        "expiry": exp_str,
                        "dte": dte,
                        "type": "monthly" if is_monthly else "weekly"
                    })
            except Exception:
                continue
        
        if not valid_expiries:
            metadata["error"] = f"No expirations in DTE range {min_dte}-{max_dte}"
            return [], metadata
        
        metadata["available_expirations"] = [e["expiry"] for e in valid_expiries]
        
        options = []
        rejection_reasons = {"missing_iv": 0, "missing_oi": 0, "missing_premium": 0, "out_of_range": 0}
        
        # Fetch options for each valid expiry
        for exp_info in valid_expiries:
            expiry = exp_info["expiry"]
            dte = exp_info["dte"]
            exp_type = exp_info["type"]
            
            try:
                opt_chain = ticker.option_chain(expiry)
                chain_data = opt_chain.calls if option_type == "call" else opt_chain.puts
                
                for _, row in chain_data.iterrows():
                    strike = row.get('strike', 0)
                    if not strike:
                        continue
                    
                    # Filter strikes based on moneyness
                    # For LEAPS, use much wider range to include deep ITM strikes
                    if is_leaps:
                        # LEAPS: allow strikes from 40% to 110% of current price
                        if option_type == "call":
                            if strike < current_price * 0.40 or strike > current_price * 1.10:
                                rejection_reasons["out_of_range"] += 1
                                continue
                        else:
                            if strike > current_price * 1.60 or strike < current_price * 0.90:
                                rejection_reasons["out_of_range"] += 1
                                continue
                    else:
                        # Regular options: tighter range around current price
                        if option_type == "call":
                            if strike < current_price * 0.95 or strike > current_price * 1.15:
                                rejection_reasons["out_of_range"] += 1
                                continue
                        else:
                            if strike > current_price * 1.05 or strike < current_price * 0.85:
                                rejection_reasons["out_of_range"] += 1
                                continue
                    
                    # Get premium - use last price or mid of bid/ask
                    last_price = row.get('lastPrice', 0)
                    bid = row.get('bid', 0)
                    ask = row.get('ask', 0)
                    premium = last_price if last_price > 0 else ((bid + ask) / 2 if bid > 0 and ask > 0 else 0)
                    
                    if premium <= 0:
                        rejection_reasons["missing_premium"] += 1
                        if require_complete_data:
                            continue
                    
                    # Get IV and OI - CRITICAL for data quality
                    iv = row.get('impliedVolatility', 0)
                    oi = row.get('openInterest', 0)
                    volume = row.get('volume', 0)
                    
                    # Skip if IV is missing or unrealistic
                    if require_complete_data:
                        if not iv or iv <= 0:
                            rejection_reasons["missing_iv"] += 1
                            continue
                        if iv < 0.01 or iv > 5.0:  # < 1% or > 500%
                            rejection_reasons["missing_iv"] += 1
                            continue
                    
                    # Skip if OI is 0 (no liquidity)
                    if require_complete_data and (not oi or oi <= 0):
                        rejection_reasons["missing_oi"] += 1
                        continue
                    
                    options.append({
                        "contract_ticker": row.get('contractSymbol', ''),
                        "underlying": symbol,
                        "strike": float(strike),
                        "expiry": expiry,
                        "dte": dte,
                        "expiry_type": exp_type,  # "weekly" or "monthly"
                        "type": option_type,
                        "close": round(float(premium), 2),
                        "bid": float(bid) if bid else 0,
                        "ask": float(ask) if ask else 0,
                        "volume": int(volume) if volume else 0,
                        "open_interest": int(oi) if oi else 0,
                        "implied_volatility": round(float(iv), 4) if iv else 0,
                        # Metadata
                        "source": "yahoo",
                        "options_snapshot_time": metadata["snapshot_time"],
                        "equity_price_date": t1_date_str
                    })
                    
            except Exception as e:
                logger.debug(f"Error fetching {symbol} options for {expiry}: {e}")
                continue
        
        metadata["options_fetched"] = len(options)
        metadata["options_rejected"] = sum(rejection_reasons.values())
        metadata["rejection_reasons"] = rejection_reasons
        
        logger.info(f"Yahoo: fetched {len(options)} valid {option_type} options for {symbol}")
        return options, metadata
        
    except Exception as e:
        logger.warning(f"Yahoo options chain failed for {symbol}: {e}")
        metadata["error"] = str(e)
        return [], metadata


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
                            "equity_price_date": t1_date,
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
    current_price: float = None,
    friday_only: bool = True,
    require_complete_data: bool = True,
    is_leaps: bool = False
) -> Tuple[List[Dict], Dict[str, Any]]:
    """
    Fetch options chain with STRICT validation.
    
    Args:
        is_leaps: If True, use wider strike range for deep ITM LEAPS (min_dte >= 180)
    
    Returns:
        Tuple of (options list, metadata dict including snapshot time)
    """
    loop = asyncio.get_event_loop()
    
    # Auto-detect LEAPS mode based on DTE
    if min_dte >= 180:
        is_leaps = True
    
    # Fetch from Yahoo with strict validation
    options, metadata = await loop.run_in_executor(
        _yahoo_executor,
        lambda: _fetch_options_chain_yahoo_sync(
            symbol, max_dte, min_dte, option_type, current_price, friday_only, require_complete_data, is_leaps
        )
    )
    
    if options and len(options) > 0:
        return options, metadata
    
    # Polygon fallback (limited - no IV/OI in basic plan)
    if api_key and not require_complete_data:
        polygon_options = await _fetch_options_chain_polygon(
            symbol, api_key, option_type, max_dte, min_dte, current_price
        )
        if polygon_options:
            return polygon_options, {"source": "polygon", "snapshot_time": datetime.now(EASTERN_TZ).strftime('%Y-%m-%d %H:%M:%S ET')}
    
    return [], metadata


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
            
            # Filter to Friday expirations only
            valid_contracts = []
            for contract in contracts:
                expiry = contract.get("expiration_date", "")
                if is_friday_expiration(expiry):
                    is_valid, _ = is_valid_expiration_date(expiry)
                    if is_valid:
                        valid_contracts.append(contract)
            
            options = []
            snapshot_time = datetime.now(EASTERN_TZ).strftime('%Y-%m-%d %H:%M:%S ET')
            
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
                                "expiry_type": "monthly" if is_monthly_expiration(expiry) else "weekly",
                                "type": option_type,
                                "close": r.get("c", 0),
                                "volume": r.get("v", 0),
                                "open_interest": 0,
                                "implied_volatility": 0,
                                "source": "polygon",
                                "options_snapshot_time": snapshot_time,
                                "equity_price_date": t1_date_str,
                                "note": "Polygon basic plan - IV/OI not available"
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
# DATA QUALITY FUNCTIONS
# =============================================================================

def get_data_source_status() -> Dict[str, Any]:
    """Get current data source configuration and status."""
    metadata = get_data_metadata()
    
    return {
        "primary_source": "yahoo",
        "backup_source": "polygon",
        "data_principle": "Two-Source Model (T-1 Equity + Latest Options Snapshot)",
        "equity_price_date": metadata["equity_price_date"],
        "equity_price_source": metadata["equity_price_source"],
        "next_refresh": metadata["next_refresh"],
        "current_time_et": metadata["current_time_et"],
        "staleness_thresholds": metadata["staleness_thresholds"],
        "validation_rules": {
            "friday_only_expirations": True,
            "require_iv": True,
            "require_oi": True,
            "reject_stale_data": True
        }
    }


def calculate_dte(expiry_date: str) -> int:
    """Calculate days to expiration from T-1 date."""
    return calculate_dte_from_t1(expiry_date)


# =============================================================================
# HISTORICAL DATA
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
