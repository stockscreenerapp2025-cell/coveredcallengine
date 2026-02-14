"""
Centralized Data Provider Service
================================
PRIMARY DATA SOURCE: Yahoo Finance (yfinance)
BACKUP DATA SOURCE: Polygon/Massive (free tier)

This module is the SINGLE SOURCE OF TRUTH for market-time and data sourcing logic.

Key principles (Feb 2026 hardening):
- Time logic is ALWAYS America/New_York (ET) aware (never server-local naive datetime.now()).
- Market state is explicit: OPEN | EXTENDED | CLOSED.
- SNAPSHOT (scan/screener) data must be regular-session synced (previous close while market is open).
- LIVE (watchlist/simulator) can use intraday / extended-hours prices.
- Display endpoints may show extended-hours price, but must ALSO provide the synced regular-session price
  so options math can remain consistent after-hours.

PRICING RULES:
- SELL legs: Use BID only, reject if BID is None/0/missing
- BUY legs: Use ASK only, reject if ASK is None/0/missing
- NEVER use: lastPrice, mid, theoretical price

USER PATH vs SCAN PATH (Feb 2026):
- USER PATHS (Dashboard, Watchlist, Simulator, single-symbol): Use full executor capacity, NO scan semaphore
- SCAN PATHS (Screener, PMCC scans): Use bounded concurrency via ResilientYahooFetcher
"""

from __future__ import annotations

import logging
import asyncio
import httpx
import time
import os
from datetime import datetime, timedelta, timezone, date
from typing import Optional, List, Dict, Any, Literal
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo
import math

import pytz  # retained for compatibility in other modules that still import pytz

HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
POLYGON_BASE_URL = "https://api.polygon.io"

# =============================================================================
# YAHOO EXECUTOR CONFIGURATION (Feb 2026 - User Path Speed Fix)
# =============================================================================
# USER PATHS (Dashboard, Watchlist, Simulator) use this executor directly
# SCAN PATHS use ResilientYahooFetcher with bounded concurrency
# =============================================================================
YAHOO_MAX_WORKERS = int(os.environ.get("YAHOO_MAX_WORKERS", "12"))

_yahoo_executor = ThreadPoolExecutor(max_workers=YAHOO_MAX_WORKERS)
# Legacy semaphore kept for backward compatibility but NOT used in user paths
_yahoo_semaphore = asyncio.Semaphore(YAHOO_MAX_WORKERS)

logger = logging.getLogger(__name__)
logger.info(f"Yahoo executor initialized: YAHOO_MAX_WORKERS={YAHOO_MAX_WORKERS}")

NY = ZoneInfo("America/New_York")

MarketState = Literal["OPEN", "EXTENDED", "CLOSED"]

# Cache metrics tracking (Phase 2)
_cache_metrics = {
    "hits": 0,
    "misses": 0,
    "yahoo_calls": 0,
    "last_reset": datetime.now(timezone.utc),
    "fetch_times_ms": []
}

# -----------------------------------------------------------------------------
# Time / Market State Helpers (ET)
# -----------------------------------------------------------------------------

def now_et() -> datetime:
    return datetime.now(NY)

def is_weekend_et(d: date) -> bool:
    return d.weekday() >= 5  # Sat/Sun

def get_market_state(now: Optional[datetime] = None) -> MarketState:
    """
    OPEN:     09:30–16:00 ET
    EXTENDED: 16:00–20:00 ET
    CLOSED:   otherwise + weekends

    Note:
    - This function does NOT model US market holidays.
    - For the platform's stability goals, weekends are handled explicitly,
      and holidays are treated like CLOSED at the UI level via "staleness" flags.
    """
    n = now or now_et()
    if is_weekend_et(n.date()):
        return "CLOSED"

    minutes = n.hour * 60 + n.minute
    open_m = 9 * 60 + 30
    close_m = 16 * 60
    ext_end_m = 20 * 60

    if open_m <= minutes < close_m:
        return "OPEN"
    if close_m <= minutes < ext_end_m:
        return "EXTENDED"
    return "CLOSED"

def is_market_closed() -> bool:
    """Back-compat wrapper used by older modules."""
    return get_market_state() != "OPEN"

def get_last_trading_day_et(now: Optional[datetime] = None) -> str:
    """
    Returns YYYY-MM-DD for the last trading day (ET), based on weekend + pre-open logic.
    Does not model holidays; holidays will look like "last weekday".
    """
    n = now or now_et()

    # Weekend -> roll back to Friday
    if n.weekday() == 5:  # Sat
        n = n - timedelta(days=1)
    elif n.weekday() == 6:  # Sun
        n = n - timedelta(days=2)

    # Before market open on a weekday -> use previous weekday
    minutes = n.hour * 60 + n.minute
    open_m = 9 * 60 + 30
    if n.weekday() == 0 and minutes < open_m:
        n = n - timedelta(days=3)
    elif minutes < open_m:
        n = n - timedelta(days=1)
        # If we rolled into weekend, roll back to Friday
        if n.weekday() == 6:
            n = n - timedelta(days=2)
        elif n.weekday() == 5:
            n = n - timedelta(days=1)

    return n.strftime("%Y-%m-%d")

def calculate_dte(expiry_date: str) -> int:
    """
    Days-to-expiry computed on ET calendar days (date-to-date) to avoid drift.
    """
    try:
        exp = datetime.strptime(expiry_date, "%Y-%m-%d").date()
        today = now_et().date()
        return max(0, (exp - today).days)
    except Exception:
        return 0

def shutdown_executor():
    global _yahoo_executor
    if _yahoo_executor:
        _yahoo_executor.shutdown(wait=True)
        logging.info("Yahoo Finance thread pool executor shut down")

# =============================================================================
# RESILIENT YAHOO FETCHER (Feb 2026 - Scan Path Concurrency Control)
# =============================================================================
# Used ONLY by scan paths (screener, PMCC scans) to prevent overwhelming Yahoo
# User paths bypass this and use _yahoo_executor directly for maximum speed
# =============================================================================

class ResilientYahooFetcher:
    """
    Bounded concurrency wrapper for Yahoo Finance calls in SCAN contexts.
    
    Features:
    - Configurable max concurrent requests (default: 4)
    - Exponential backoff on failures
    - Request rate limiting
    - Automatic retry with jitter
    
    Usage: SCAN PATHS ONLY - user paths should use _yahoo_executor directly
    """
    
    def __init__(self, max_concurrent: int = 4, max_retries: int = 2):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.max_retries = max_retries
        self.last_request_time = 0
        self.min_request_interval = 0.1  # 100ms between requests
        
    async def fetch_with_backoff(self, fetch_func, *args, **kwargs):
        """Execute fetch function with exponential backoff and rate limiting."""
        async with self.semaphore:
            # Rate limiting
            now = time.time()
            time_since_last = now - self.last_request_time
            if time_since_last < self.min_request_interval:
                await asyncio.sleep(self.min_request_interval - time_since_last)
            
            self.last_request_time = time.time()
            
            for attempt in range(self.max_retries + 1):
                try:
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(_yahoo_executor, fetch_func, *args, **kwargs)
                    return result
                except Exception as e:
                    if attempt == self.max_retries:
                        logger.warning(f"Yahoo fetch failed after {self.max_retries + 1} attempts: {e}")
                        return None
                    
                    # Exponential backoff with jitter
                    delay = (2 ** attempt) + (0.1 * attempt)  # 0.1, 2.1, 4.2 seconds
                    jitter = delay * 0.1 * (0.5 - asyncio.get_event_loop().time() % 1)
                    await asyncio.sleep(delay + jitter)
                    
            return None

# Global instance for scan paths
_resilient_fetcher = ResilientYahooFetcher(max_concurrent=4)

# -----------------------------------------------------------------------------
# Yahoo Finance - LIVE intraday prices (Watchlist & Simulator)
# -----------------------------------------------------------------------------

def _fetch_live_stock_quote_yahoo_sync(symbol: str) -> Optional[Dict[str, Any]]:
    """
    LIVE quote from Yahoo (blocking):
    - Can reflect regular session, pre-market, or after-hours depending on timing.
    """
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}

        current_price = info.get("regularMarketPrice") or info.get("currentPrice") or info.get("previousClose") or 0
        previous_close = info.get("previousClose") or current_price or 0

        if not current_price or current_price <= 0:
            return None

        change = (current_price - previous_close) if previous_close else 0
        change_pct = (change / previous_close * 100) if previous_close else 0

        # Best-effort timestamps (ET)
        n_et = now_et()
        ts_et = info.get("regularMarketTime")
        ts_et_iso = n_et.isoformat()
        if ts_et:
            try:
                ts_et_iso = datetime.fromtimestamp(ts_et, NY).isoformat()
            except Exception:
                ts_et_iso = n_et.isoformat()

        return {
            "symbol": symbol.upper(),
            "price": round(float(current_price), 2),
            "previous_close": round(float(previous_close), 2),
            "change": round(float(change), 2),
            "change_pct": round(float(change_pct), 2),
            "source": "yahoo_live",
            "is_live": True,
            "market_state": get_market_state(n_et),
            "timestamp_et": ts_et_iso,
        }
    except Exception as e:
        logging.warning(f"Yahoo live stock quote failed for {symbol}: {e}")
        return None

async def fetch_live_stock_quote(symbol: str, api_key: str = None) -> Optional[Dict[str, Any]]:
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_yahoo_executor, _fetch_live_stock_quote_yahoo_sync, symbol)
    if result and result.get("price", 0) > 0:
        return result
    return await fetch_stock_quote(symbol, api_key)

async def fetch_live_stock_quotes_batch(symbols: List[str], api_key: str = None) -> Dict[str, Dict[str, Any]]:
    if not symbols:
        return {}
    tasks = [fetch_live_stock_quote(sym, api_key) for sym in set(symbols)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    quotes: Dict[str, Dict[str, Any]] = {}
    for r in results:
        if isinstance(r, dict) and r.get("symbol"):
            quotes[r["symbol"]] = r
    return quotes

# -----------------------------------------------------------------------------
# Yahoo Finance - REGULAR SESSION synced quote (SNAPSHOT use)
# -----------------------------------------------------------------------------

def _safe_float(x, default=0.0) -> float:
    try:
        if x is None:
            return default
        if isinstance(x, float) and math.isnan(x):
            return default
        return float(x)
    except Exception:
        return default

def _fetch_stock_quote_yahoo_sync(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Regular-session synced quote (blocking).

    Returns the *most recent completed regular-session close*:
    - If market is OPEN and Yahoo history includes today's row, use second-to-last close.
    - Otherwise use last close.

    Also returns post-market fields (best-effort) so display layers can choose safely.
    """
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}

        hist = ticker.history(period="7d")  # small buffer for weekends
        if hist is None or hist.empty:
            return None

        n_et = now_et()
        today = n_et.date()
        last_date = hist.index[-1].date()

        use_index = -1
        if get_market_state(n_et) == "OPEN" and last_date == today and len(hist) >= 2:
            use_index = -2

        close_price = _safe_float(hist["Close"].iloc[use_index], 0.0)
        close_date = hist.index[use_index].strftime("%Y-%m-%d") if close_price > 0 else None

        if close_price <= 0:
            return None

        # Best-effort extended-hours fields (for display ONLY)
        regular_price = _safe_float(info.get("regularMarketPrice") or info.get("currentPrice") or close_price, close_price)
        post_price = info.get("postMarketPrice")
        post_price = _safe_float(post_price, 0.0) if post_price is not None else None

        # Timestamps (ET)
        regular_time = info.get("regularMarketTime")
        post_time = info.get("postMarketTime")
        ts_regular_et = None
        ts_post_et = None
        try:
            if regular_time:
                ts_regular_et = datetime.fromtimestamp(regular_time, NY).isoformat()
        except Exception:
            ts_regular_et = None
        try:
            if post_time:
                ts_post_et = datetime.fromtimestamp(post_time, NY).isoformat()
        except Exception:
            ts_post_et = None

        # Metadata enrichment (kept compatible with previous implementation)
        recommendation = info.get("recommendationKey", "")
        rating_map = {
            "strong_buy": "Strong Buy",
            "buy": "Buy",
            "hold": "Hold",
            "underperform": "Sell",
            "sell": "Sell",
        }
        analyst_rating = rating_map.get(recommendation, recommendation.replace("_", " ").title() if recommendation else None)

        return {
            "symbol": symbol.upper(),
            # SNAPSHOT price: last completed regular-session close
            "price": round(close_price, 2),
            "previous_close": round(close_price, 2),
            "close_date": close_date,
            # Provide regular/post fields for display layers (optional)
            "regular_price": round(_safe_float(regular_price, close_price), 2),
            "post_price": round(_safe_float(post_price, 0.0), 2) if post_price is not None else None,
            "timestamp_regular_et": ts_regular_et,
            "timestamp_post_et": ts_post_et,
            "market_state": get_market_state(n_et),
            "timestamp_et": (ts_post_et or ts_regular_et or n_et.isoformat()),
            "analyst_rating": analyst_rating,
            "market_cap": info.get("marketCap", 0),
            "avg_volume": info.get("averageVolume", 0) or info.get("averageDailyVolume10Day", 0),
            "earnings_date": None,
            "source": "yahoo",
        }
    except Exception as e:
        logging.warning(f"Yahoo stock quote failed for {symbol}: {e}")
        return None

async def fetch_stock_quote(symbol: str, api_key: str = None) -> Optional[Dict[str, Any]]:
    """
    SNAPSHOT quote (regular-session synced): Yahoo primary, Polygon backup.
    """
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_yahoo_executor, _fetch_stock_quote_yahoo_sync, symbol)
    if result and result.get("price", 0) > 0:
        return result

    # Polygon backup (previous close aggregate)
    if api_key:
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                r = await client.get(
                    f"{POLYGON_BASE_URL}/v2/aggs/ticker/{symbol.upper()}/prev",
                    params={"apiKey": api_key},
                )
                if r.status_code == 200:
                    data = r.json()
                    if data.get("results"):
                        row = data["results"][0]
                        c = _safe_float(row.get("c"), 0.0)
                        if c > 0:
                            return {
                                "symbol": symbol.upper(),
                                "price": c,
                                "previous_close": c,
                                "close_date": get_last_trading_day_et(),
                                "market_state": get_market_state(),
                                "timestamp_et": now_et().isoformat(),
                                "source": "polygon",
                            }
        except Exception as e:
            logging.debug(f"Polygon stock quote backup failed for {symbol}: {e}")

    return None

async def fetch_stock_quotes_batch(symbols: List[str], api_key: str = None) -> Dict[str, Dict[str, Any]]:
    if not symbols:
        return {}
    tasks = [fetch_stock_quote(sym, api_key) for sym in set(symbols)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out: Dict[str, Dict[str, Any]] = {}
    for r in results:
        if isinstance(r, dict) and r.get("symbol"):
            out[r["symbol"]] = r
    return out

# -----------------------------------------------------------------------------
# Yahoo Finance - Options Chain (primary)
# -----------------------------------------------------------------------------

def _fetch_options_chain_yahoo_sync(
    symbol: str,
    max_dte: int = 45,
    min_dte: int = 1,
    option_type: str = "call",
    current_price: float = None,
) -> List[Dict[str, Any]]:
    """
    Fetch options chain from Yahoo Finance (blocking).
    Returns: bid/ask/iv/oi/volume and quote metadata.
    """
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)

        # Determine current_price if not provided (use regular price, not after-hours)
        if not current_price or current_price <= 0:
            info = ticker.info or {}
            current_price = _safe_float(info.get("regularMarketPrice") or info.get("currentPrice") or info.get("previousClose"), 0.0)

        if not current_price or current_price <= 0:
            return []

        expirations = []
        try:
            expirations = ticker.options or []
        except Exception:
            expirations = []

        if not expirations:
            return []

        today_et = now_et().date()
        valid_expiries: List[tuple[str,int]] = []
        for exp_str in expirations:
            try:
                exp_d = datetime.strptime(exp_str, "%Y-%m-%d").date()
                dte = (exp_d - today_et).days
                if min_dte <= dte <= max_dte:
                    valid_expiries.append((exp_str, dte))
            except Exception:
                continue

        if not valid_expiries:
            return []

        options: List[Dict[str, Any]] = []
        max_expiries = 5 if min_dte > 90 else 3

        n_et = now_et()
        m_state = get_market_state(n_et)
        quote_timestamp = datetime.now(timezone.utc).isoformat()

        for expiry, dte in valid_expiries[:max_expiries]:
            try:
                chain = ticker.option_chain(expiry)
                df = chain.calls if option_type == "call" else chain.puts
                for _, row in df.iterrows():
                    strike = _safe_float(row.get("strike"), 0.0)
                    if strike <= 0:
                        continue

                    # Strike filters (keep original intent)
                    if option_type == "call":
                        if min_dte > 90:
                            if strike < current_price * 0.50 or strike > current_price * 1.15:
                                continue
                        else:
                            if strike < current_price * 0.95 or strike > current_price * 1.15:
                                continue
                    else:
                        if strike > current_price * 1.05 or strike < current_price * 0.85:
                            continue

                    bid = _safe_float(row.get("bid"), 0.0)
                    ask = _safe_float(row.get("ask"), 0.0)

                    if bid <= 0 and ask <= 0:
                        continue

                    iv = _safe_float(row.get("impliedVolatility"), 0.0)
                    if iv and (iv < 0.01 or iv > 5.0):
                        iv = 0.0

                    options.append({
                        "contract_ticker": row.get("contractSymbol", "") or "",
                        "underlying": symbol.upper(),
                        "strike": strike,
                        "expiry": expiry,
                        "dte": int(dte),
                        "type": option_type,
                        "bid": bid,
                        "ask": ask,
                        "volume": int(row.get("volume") or 0),
                        "open_interest": int(row.get("openInterest") or 0),
                        "implied_volatility": iv,
                        # Quote provenance
                        "quote_source": "LIVE" if m_state == "OPEN" else "LAST_MARKET_SESSION",
                        "quote_timestamp": quote_timestamp,
                        "source": "yahoo",
                    })
            except Exception as e:
                logging.debug(f"Error fetching {symbol} options for {expiry}: {e}")
                continue

        return options
    except Exception as e:
        logging.warning(f"Yahoo options chain failed for {symbol}: {e}")
        return []

async def fetch_options_chain(
    symbol: str,
    api_key: str = None,
    option_type: str = "call",
    max_dte: int = 45,
    min_dte: int = 1,
    current_price: float = None,
) -> List[Dict[str, Any]]:
    """
    Options chain - Yahoo primary, Polygon backup.
    """
    loop = asyncio.get_event_loop()
    opts = await loop.run_in_executor(
        _yahoo_executor,
        _fetch_options_chain_yahoo_sync,
        symbol, max_dte, min_dte, option_type, current_price,
    )
    if opts:
        return opts

    if api_key:
        opts = await _fetch_options_chain_polygon(symbol, api_key, option_type, max_dte, min_dte, current_price)
        if opts:
            return opts

    return []

async def _fetch_options_chain_polygon(
    symbol: str,
    api_key: str,
    option_type: str = "call",
    max_dte: int = 45,
    min_dte: int = 1,
    current_price: float = None
) -> List[Dict[str, Any]]:
    """Polygon backup (basic plan - no IV/OI)."""
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            today = now_et().date()
            min_expiry = (today + timedelta(days=min_dte)).isoformat()
            max_expiry = (today + timedelta(days=max_dte)).isoformat()

            r = await client.get(
                f"{POLYGON_BASE_URL}/v3/reference/options/contracts",
                params={
                    "underlying_ticker": symbol.upper(),
                    "contract_type": option_type,
                    "expiration_date.gte": min_expiry,
                    "expiration_date.lte": max_expiry,
                    "limit": 50,
                    "apiKey": api_key,
                },
            )
            if r.status_code != 200:
                return []
            data = r.json()
            contracts = data.get("results", []) or []
            if not contracts:
                return []

            out: List[Dict[str, Any]] = []
            for c in contracts[:30]:
                ticker = c.get("ticker", "")
                strike = _safe_float(c.get("strike_price"), 0.0)
                expiry = c.get("expiration_date", "")
                if not ticker or strike <= 0 or not expiry:
                    continue

                try:
                    pr = await client.get(
                        f"{POLYGON_BASE_URL}/v2/aggs/ticker/{ticker}/prev",
                        params={"apiKey": api_key},
                    )
                    if pr.status_code != 200:
                        continue
                    pdata = pr.json()
                    results = pdata.get("results", []) or []
                    if not results:
                        continue
                    row = results[0]
                    out.append({
                        "contract_ticker": ticker,
                        "underlying": symbol.upper(),
                        "strike": strike,
                        "expiry": expiry,
                        "dte": calculate_dte(expiry),
                        "type": option_type,
                        "close": _safe_float(row.get("c"), 0.0),
                        "volume": int(row.get("v") or 0),
                        "open_interest": 0,
                        "implied_volatility": 0.0,
                        "source": "polygon",
                    })
                except Exception:
                    continue

            return out
    except Exception as e:
        logging.warning(f"Polygon options chain failed for {symbol}: {e}")
        return []

# -----------------------------------------------------------------------------
# Quote caching wrapper (unchanged API, but uses ET market_state)
# -----------------------------------------------------------------------------

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
    """
    from services.quote_cache_service import get_quote_cache
    quote_cache = get_quote_cache(db)
    market_info = quote_cache.get_market_session_info()
    is_open = market_info["is_open"]

    live_options = await fetch_options_chain(
        symbol=symbol,
        api_key=None,
        option_type=option_type,
        max_dte=max_dte,
        min_dte=min_dte,
        current_price=current_price,
    )

    enriched: List[Dict[str, Any]] = []
    for opt in live_options:
        contract = opt.get("contract_ticker", "")
        bid = _safe_float(opt.get("bid"), 0.0)
        ask = _safe_float(opt.get("ask"), 0.0)

        if is_open and (bid > 0 or ask > 0):
            await quote_cache.cache_valid_quote(
                contract_symbol=contract,
                symbol=symbol.upper(),
                strike=_safe_float(opt.get("strike"), 0.0),
                expiry=opt.get("expiry", ""),
                bid=bid,
                ask=ask,
                dte=int(opt.get("dte") or 0),
            )

        if is_open:
            opt["quote_source"] = "LIVE"
            opt["quote_timestamp"] = datetime.now(timezone.utc).isoformat()
        else:
            opt["quote_source"] = "LAST_MARKET_SESSION"
            opt["quote_age_hours"] = market_info.get("hours_since_close", 0)

        enriched.append(opt)

    if (not is_open) and (not enriched):
        cached_quotes = await db.option_quote_cache.find(
            {"symbol": symbol.upper(), "dte": {"$gte": min_dte, "$lte": max_dte}},
            {"_id": 0},
        ).to_list(200)

        for cached in cached_quotes:
            if cached.get("bid", 0) in (None, 0) and cached.get("ask", 0) in (None, 0):
                continue
            cached["quote_source"] = "LAST_MARKET_SESSION"
            cached["quote_age_hours"] = market_info.get("hours_since_close", 0)
            if isinstance(cached.get("quote_timestamp"), datetime):
                cached["quote_timestamp"] = cached["quote_timestamp"].isoformat()
            enriched.append(cached)

    return enriched

# -----------------------------------------------------------------------------
# Status helpers
# -----------------------------------------------------------------------------

def get_data_source_status() -> Dict[str, Any]:
    return {
        "primary_source": "yahoo",
        "backup_source": "polygon",
        "market_state": get_market_state(),
        "market_closed": is_market_closed(),
        "last_trading_day_et": get_last_trading_day_et(),
    }

# -----------------------------------------------------------------------------
# Historical data (unchanged)
# -----------------------------------------------------------------------------

async def fetch_historical_data(symbol: str, api_key: str = None, days: int = 30) -> List[Dict[str, Any]]:
    try:
        import yfinance as yf

        def _fetch_history():
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period=f"{days}d")
            data = []
            for dt, row in hist.iterrows():
                data.append({
                    "date": dt.strftime("%Y-%m-%d"),
                    "open": round(float(row["Open"]), 2),
                    "high": round(float(row["High"]), 2),
                    "low": round(float(row["Low"]), 2),
                    "close": round(float(row["Close"]), 2),
                    "volume": int(row["Volume"]),
                })
            return data

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_yahoo_executor, _fetch_history)
    except Exception as e:
        logging.warning(f"Historical data fetch failed for {symbol}: {e}")
        return []

# -----------------------------------------------------------------------------
# Phase 2 snapshot cache (kept, but now uses ET helpers)
# -----------------------------------------------------------------------------

CACHE_TTL_MARKET_OPEN_MIN = 12
CACHE_TTL_MARKET_CLOSED_HOURS = 3
SNAPSHOT_CACHE_COLLECTION = "market_snapshot_cache"

def _get_cache_ttl_seconds() -> int:
    return CACHE_TTL_MARKET_CLOSED_HOURS * 3600 if is_market_closed() else CACHE_TTL_MARKET_OPEN_MIN * 60

async def _get_cached_snapshot(db, symbol: str) -> Optional[Dict[str, Any]]:
    try:
        cached = await db[SNAPSHOT_CACHE_COLLECTION].find_one({"symbol": symbol.upper()}, {"_id": 0})
        if not cached:
            return None
        cached_at = cached.get("cached_at")
        if not cached_at:
            return None
        if isinstance(cached_at, str):
            cached_at = datetime.fromisoformat(cached_at.replace("Z", "+00:00"))
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=timezone.utc)

        ttl = _get_cache_ttl_seconds()
        age = (datetime.now(timezone.utc) - cached_at).total_seconds()
        if age > ttl:
            return None
        return cached
    except Exception as e:
        logging.warning(f"Error reading cache for {symbol}: {e}")
        return None

async def _store_snapshot_cache(db, symbol: str, stock_data: Dict[str, Any], options_metadata: Optional[Dict[str, Any]] = None) -> None:
    try:
        cache_doc = {
            "symbol": symbol.upper(),
            "cached_at": datetime.now(timezone.utc),
            "ttl_seconds": _get_cache_ttl_seconds(),
            "market_status": "closed" if is_market_closed() else "open",
            "price": stock_data.get("price", 0),
            "previous_close": stock_data.get("previous_close", 0),
            "close_date": stock_data.get("close_date"),
            "analyst_rating": stock_data.get("analyst_rating"),
            "market_cap": stock_data.get("market_cap", 0),
            "avg_volume": stock_data.get("avg_volume", 0),
            "earnings_date": stock_data.get("earnings_date"),
            "source": stock_data.get("source", "yahoo"),
            "options_metadata": options_metadata,
        }
        await db[SNAPSHOT_CACHE_COLLECTION].update_one(
            {"symbol": symbol.upper()},
            {"$set": cache_doc},
            upsert=True,
        )
    except Exception as e:
        logging.warning(f"Error caching snapshot for {symbol}: {e}")

async def get_symbol_snapshot(
    db,
    symbol: str,
    api_key: str = None,
    include_options: bool = False,
    max_dte: int = 45,
    min_dte: int = 1,
) -> Dict[str, Any]:
    global _cache_metrics
    symbol = symbol.upper()
    result = {"symbol": symbol, "stock_data": None, "options_data": None, "from_cache": False, "fetch_time_ms": 0}
    start = time.time()

    cached = await _get_cached_snapshot(db, symbol)
    if cached and cached.get("price", 0) > 0:
        _cache_metrics["hits"] += 1
        result["stock_data"] = {
            "symbol": symbol,
            "price": cached.get("price", 0),
            "previous_close": cached.get("previous_close", 0),
            "close_date": cached.get("close_date"),
            "analyst_rating": cached.get("analyst_rating"),
            "market_cap": cached.get("market_cap", 0),
            "avg_volume": cached.get("avg_volume", 0),
            "earnings_date": cached.get("earnings_date"),
            "source": cached.get("source", "yahoo_cached"),
        }
        result["from_cache"] = True
        if not include_options:
            result["fetch_time_ms"] = (time.time() - start) * 1000
            return result
    else:
        _cache_metrics["misses"] += 1

    async with _yahoo_semaphore:
        _cache_metrics["yahoo_calls"] += 1
        if not result["stock_data"]:
            stock_data = await fetch_stock_quote(symbol, api_key)
            if stock_data and stock_data.get("price", 0) > 0:
                result["stock_data"] = stock_data
                await _store_snapshot_cache(db, symbol, stock_data)
            else:
                result["fetch_time_ms"] = (time.time() - start) * 1000
                return result

        if include_options:
            current_price = result["stock_data"].get("price", 0)
            options_data = await fetch_options_chain(symbol, api_key, "call", max_dte, min_dte, current_price)
            if options_data:
                result["options_data"] = options_data
                options_metadata = {
                    "count": len(options_data),
                    "expiries": list(set(o.get("expiry", "") for o in options_data)),
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }
                await _store_snapshot_cache(db, symbol, result["stock_data"], options_metadata)

    ft = (time.time() - start) * 1000
    result["fetch_time_ms"] = ft
    _cache_metrics["fetch_times_ms"].append(ft)
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
    batch_size: int = 10,
) -> Dict[str, Dict[str, Any]]:
    if not symbols:
        return {}
    results: Dict[str, Dict[str, Any]] = {}
    unique = list(set(s.upper() for s in symbols))
    for i in range(0, len(unique), batch_size):
        batch = unique[i:i+batch_size]
        tasks = [get_symbol_snapshot(db, s, api_key, include_options, max_dte, min_dte) for s in batch]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        for j, r in enumerate(batch_results):
            if isinstance(r, dict) and r.get("stock_data"):
                results[batch[j]] = r
            elif isinstance(r, Exception):
                logging.warning(f"Error fetching snapshot for {batch[j]}: {r}")
        if i + batch_size < len(unique):
            await asyncio.sleep(0.5)
    return results

def get_cache_metrics() -> Dict[str, Any]:
    global _cache_metrics
    total = _cache_metrics["hits"] + _cache_metrics["misses"]
    hit_rate = (_cache_metrics["hits"] / total * 100) if total else 0
    elapsed = (datetime.now(timezone.utc) - _cache_metrics["last_reset"]).total_seconds()
    hours = max(elapsed/3600, 0.01)
    yahoo_calls_per_hour = _cache_metrics["yahoo_calls"]/hours
    ft = _cache_metrics["fetch_times_ms"]
    avg_ft = sum(ft)/len(ft) if ft else 0
    return {
        "cache_hits": _cache_metrics["hits"],
        "cache_misses": _cache_metrics["misses"],
        "total_requests": total,
        "hit_rate_pct": round(hit_rate, 1),
        "yahoo_calls": _cache_metrics["yahoo_calls"],
        "yahoo_calls_per_hour": round(yahoo_calls_per_hour, 1),
        "avg_fetch_time_ms": round(avg_ft, 1),
        "market_status": "closed" if is_market_closed() else "open",
        "cache_ttl_seconds": _get_cache_ttl_seconds(),
        "time_since_reset_hours": round(hours, 2),
    }

def reset_cache_metrics() -> Dict[str, Any]:
    global _cache_metrics
    old = get_cache_metrics()
    _cache_metrics = {
        "hits": 0,
        "misses": 0,
        "yahoo_calls": 0,
        "last_reset": datetime.now(timezone.utc),
        "fetch_times_ms": [],
    }
    return {"message": "Cache metrics reset", "previous_metrics": old}
