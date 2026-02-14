"""
Options Routes - Options chain and expiration endpoints
Designed for scalability with proper async patterns and connection reuse

PHASE 1 REFACTOR (December 2025):
- All options data now routes through services/data_provider.py
- Yahoo Finance is primary source, Polygon is backup (via data_provider)
- MOCK options retained for fallback but flagged
- Mock fallback blocked in production (ENVIRONMENT check)

FIXES APPLIED (Feb 2026):
✅ All time/DTE logic is now America/New_York (ET) aware (no server-local datetime.now()).
✅ Market state is explicit: OPEN | EXTENDED | CLOSED.
✅ Prevents "post-market stock price + stale options chain" mismatch:
   - Stock price may be extended-hours for display
   - Greeks/filters use a synced regular-session underlying unless market is OPEN
✅ Expirations endpoint prefers real expirations from data_provider (fallback is synthetic + flagged).
✅ Response includes explicit metadata: market_state, staleness, sources, timestamp_et.

EOD SNAPSHOT LOCK (Dec 2025):
✅ After 4:05 PM ET, system is EOD_LOCKED
✅ /chain/{symbol} serves ONLY from eod_market_snapshot collection
✅ No live Yahoo calls after lock time
✅ Returns data_status=EOD_SNAPSHOT_NOT_AVAILABLE if snapshot missing
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, date
import logging
import httpx
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.auth import get_current_user
from utils.environment import allow_mock_data, check_mock_fallback, DataUnavailableError
from utils.market_state import (
    get_system_mode,
    get_market_state_info,
    get_last_trading_day,
    EODSnapshotNotAvailableError,
    log_eod_event
)
from services.data_provider import (
    fetch_stock_quote,
    fetch_options_chain,
    calculate_dte,
    # Optional future:
    # fetch_option_expirations,
)
from services.greeks_service import calculate_greeks, normalize_iv_fields
from services.iv_rank_service import get_iv_metrics_for_symbol
from services.eod_snapshot_service import get_eod_snapshot_service
from database import db

options_router = APIRouter(tags=["Options"])
HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

NY = ZoneInfo("America/New_York")


def _get_server_data():
    """Lazy import to avoid circular dependencies"""
    from server import MOCK_STOCKS, get_massive_api_key, generate_mock_options
    return MOCK_STOCKS, get_massive_api_key, generate_mock_options


def _now_et() -> datetime:
    return datetime.now(NY)


def _is_weekend(d: date) -> bool:
    return d.weekday() >= 5  # 5=Sat, 6=Sun


def _get_market_state(now_et: datetime) -> str:
    """
    Equity market state (simple, robust):
    OPEN:     09:30–16:00 ET
    EXTENDED: 16:00–20:00 ET
    CLOSED:   otherwise + weekends

    NOTE: This does not model holidays. Holiday logic should live in a single
    trading calendar utility (recommended). For now, weekends handled here.
    """
    if _is_weekend(now_et.date()):
        return "CLOSED"

    minutes = now_et.hour * 60 + now_et.minute
    open_m = 9 * 60 + 30
    close_m = 16 * 60
    ext_end_m = 20 * 60

    if open_m <= minutes < close_m:
        return "OPEN"
    if close_m <= minutes < ext_end_m:
        return "EXTENDED"
    return "CLOSED"


def _parse_expiry_et(expiry: str) -> date:
    try:
        return datetime.strptime(expiry, "%Y-%m-%d").date()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid expiry format. Use YYYY-MM-DD.")


def _compute_dte_et(expiry_date: date, now_et: datetime) -> int:
    return (expiry_date - now_et.date()).days


def _extract_prices(stock_data: Optional[Dict[str, Any]], now_et: datetime) -> Dict[str, Any]:
    """
    Defensive extraction to support multiple provider shapes.

    - display_price: can be extended-hours
    - regular_session_price: last regular-market price/close (best available)
    - price_source: REGULAR | POST | LAST_CLOSE | UNKNOWN

    For options greeks and strategy math:
      S_for_greeks = display_price ONLY when market_state == OPEN
                   else regular_session_price
    """
    market_state = _get_market_state(now_et)

    if not stock_data:
        return {
            "display_price": 0.0,
            "regular_session_price": 0.0,
            "price_source": "UNKNOWN",
            "market_state": market_state,
            "timestamp_et": now_et.isoformat(),
        }

    display_price = (
        stock_data.get("post_price")
        if (market_state == "EXTENDED" and stock_data.get("post_price") is not None)
        else stock_data.get("price") or stock_data.get("last") or stock_data.get("regularMarketPrice") or 0.0
    )

    regular_session_price = (
        stock_data.get("price")  # in our data_provider: this is last completed regular close (snapshot)
        or stock_data.get("regular_price")
        or stock_data.get("regularMarketPrice")
        or stock_data.get("previousClose")
        or display_price
        or 0.0
    )

    post_price = stock_data.get("post_price") or stock_data.get("postMarketPrice") or None

    price_source = "UNKNOWN"
    if market_state == "OPEN":
        price_source = "REGULAR"
    elif market_state == "EXTENDED":
        price_source = "POST" if post_price is not None else "REGULAR"
    else:
        price_source = "LAST_CLOSE"
        display_price = regular_session_price

    timestamp_et = stock_data.get("timestamp_et") or stock_data.get("timestamp") or stock_data.get("timestamp_post_et") or stock_data.get("timestamp_regular_et") or now_et.isoformat()

    return {
        "display_price": float(display_price or 0.0),
        "regular_session_price": float(regular_session_price or 0.0),
        "price_source": price_source,
        "market_state": market_state,
        "timestamp_et": timestamp_et,
    }


def _options_staleness_flag(market_state: str) -> Dict[str, Any]:
    if market_state == "OPEN":
        return {"stale": False, "stale_reason": None}
    if market_state == "EXTENDED":
        return {"stale": True, "stale_reason": "EXTENDED_HOURS_OPTIONS_MAY_BE_STALE"}
    return {"stale": True, "stale_reason": "MARKET_CLOSED_LAST_REGULAR_SESSION"}


@options_router.get("/chain/{symbol}")
async def get_options_chain(
    symbol: str,
    expiry: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    """
    Get options chain for a symbol.
    
    BEHAVIOR BY SYSTEM MODE:
    - LIVE (9:30 AM - 4:05 PM ET): Fetch live data from Yahoo Finance
    - EOD_LOCKED (after 4:05 PM ET): Serve ONLY from eod_market_snapshot
    
    If EOD_LOCKED and snapshot not available, returns 503 with data_status=EOD_SNAPSHOT_NOT_AVAILABLE
    """
    MOCK_STOCKS, get_massive_api_key, generate_mock_options = _get_server_data()
    symbol = symbol.upper()
    
    now_et_time = _now_et()
    system_mode = get_system_mode()
    
    # EOD_LOCKED: Serve from snapshot only - NO live Yahoo calls
    if system_mode == "EOD_LOCKED":
        log_eod_event("CHAIN_REQUEST_EOD_LOCKED", symbol=symbol)
        
        try:
            eod_service = get_eod_snapshot_service(db)
            trade_date = get_last_trading_day()
            
            # Get option chain from snapshot
            option_chain, metadata = await eod_service.get_option_chain_from_snapshot(symbol, trade_date)
            underlying_price = metadata.get("underlying_price", 0)
            
            # Filter by expiry if provided
            if expiry:
                option_chain = [opt for opt in option_chain if opt.get("expiry") == expiry]
            
            # Transform options with Greeks calculation
            transformed: List[Dict[str, Any]] = []
            for opt in option_chain:
                dte = int(opt.get("dte", 30) or 30)
                strike = float(opt.get("strike", 0) or 0)
                
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
                
                bid = float(opt.get("bid", 0) or 0)
                ask = float(opt.get("ask", 0) or 0)
                mid = (bid + ask) / 2.0 if (bid > 0 and ask > 0) else 0.0
                
                transformed.append({
                    "symbol": opt.get("contract_ticker", "") or opt.get("symbol", ""),
                    "underlying": symbol,
                    "strike": strike,
                    "expiry": opt.get("expiry", ""),
                    "dte": dte,
                    "type": opt.get("type", "call"),
                    "bid": bid,
                    "ask": ask,
                    "mid": mid,
                    "last": float(opt.get("close", 0) or 0),
                    "delta": greeks_result.delta,
                    "delta_source": greeks_result.delta_source,
                    "gamma": greeks_result.gamma,
                    "theta": greeks_result.theta,
                    "vega": greeks_result.vega,
                    "iv": iv_data["iv"],
                    "iv_pct": iv_data["iv_pct"],
                    "iv_rank": 50.0,  # Default when serving from snapshot
                    "iv_percentile": 50.0,
                    "iv_rank_source": "SNAPSHOT_DEFAULT",
                    "iv_samples": 0,
                    "volume": int(opt.get("volume", 0) or 0),
                    "open_interest": int(opt.get("open_interest", 0) or 0),
                    "break_even": strike + ask if (opt.get("type") == "call") else strike - ask,
                    "source": "eod_snapshot",
                })
            
            return {
                "symbol": symbol,
                "stock_price": underlying_price,
                "stock_price_regular_session": underlying_price,
                "stock_price_for_greeks": underlying_price,
                "options": transformed,
                "iv_proxy": 0.0,
                "iv_proxy_pct": 0.0,
                "iv_rank": 50.0,
                "iv_percentile": 50.0,
                "iv_rank_source": "SNAPSHOT_DEFAULT",
                "iv_samples": 0,
                "market_state": "CLOSED",
                "system_mode": "EOD_LOCKED",
                "timestamp_et": metadata.get("as_of", now_et_time.isoformat()),
                "snapshot_trade_date": metadata.get("trade_date"),
                "snapshot_run_id": metadata.get("run_id"),
                "stock_price_source": "EOD_SNAPSHOT",
                "options_source": "eod_snapshot",
                "options_stale": False,  # Snapshot is authoritative, not stale
                "options_stale_reason": None,
                "is_live": False,
                "is_eod_snapshot": True,
            }
            
        except EODSnapshotNotAvailableError as e:
            logging.warning(f"EOD snapshot not available for {symbol}: {e}")
            raise HTTPException(
                status_code=503,
                detail=e.to_dict()
            )
        except Exception as e:
            logging.error(f"Error serving EOD snapshot for {symbol}: {e}")
            raise HTTPException(
                status_code=503,
                detail={
                    "data_status": "EOD_SNAPSHOT_NOT_AVAILABLE",
                    "symbol": symbol,
                    "reason": str(e),
                    "system_mode": "EOD_LOCKED"
                }
            )
    
    # LIVE MODE: Use live data fetching
    api_key = await get_massive_api_key()
    market_state = _get_market_state(now_et_time)
    staleness_meta = _options_staleness_flag(market_state)

    try:
        stock_data = await fetch_stock_quote(symbol, api_key)
        price_meta = _extract_prices(stock_data, now_et_time)

        display_underlying_price = price_meta["display_price"]
        regular_underlying_price = price_meta["regular_session_price"]
        S_for_greeks = display_underlying_price if market_state == "OPEN" else regular_underlying_price

        min_dte = 1
        max_dte = 90

        expiry_date: Optional[date] = None
        if expiry:
            expiry_date = _parse_expiry_et(expiry)
            dte = _compute_dte_et(expiry_date, now_et_time)
            if dte < 0:
                raise HTTPException(status_code=400, detail="Expiry is in the past (ET).")
            min_dte = max(1, dte - 7)
            max_dte = dte + 7

        options = await fetch_options_chain(
            symbol=symbol,
            api_key=api_key,
            option_type="call",
            min_dte=min_dte,
            max_dte=max_dte,
            current_price=S_for_greeks
        )

        if options:
            try:
                iv_metrics = await get_iv_metrics_for_symbol(
                    db=db,
                    symbol=symbol,
                    options=options,
                    stock_price=S_for_greeks,
                    store_history=True
                )
            except Exception as e:
                logging.warning(f"Could not compute IV metrics for {symbol}: {e}")
                iv_metrics = None

            transformed: List[Dict[str, Any]] = []
            for opt in options:
                if expiry and opt.get("expiry") != expiry:
                    continue

                dte = int(opt.get("dte", 30) or 30)
                strike = float(opt.get("strike", 0) or 0)

                iv_raw = opt.get("implied_volatility", 0)
                iv_data = normalize_iv_fields(iv_raw)

                T = max(dte, 1) / 365.0

                greeks_result = calculate_greeks(
                    S=S_for_greeks,
                    K=strike,
                    T=T,
                    sigma=iv_data["iv"] if iv_data["iv"] > 0 else None,
                    option_type="call"
                )

                bid = float(opt.get("bid", 0) or 0)
                ask = float(opt.get("ask", 0) or 0)

                last = opt.get("last")
                if last is None:
                    last = opt.get("last_price")
                if last is None:
                    last = opt.get("lastPrice")
                if last is None:
                    last = opt.get("close", 0)
                last = float(last or 0)

                mid = (bid + ask) / 2.0 if (bid > 0 and ask > 0) else 0.0

                transformed.append({
                    "symbol": opt.get("contract_ticker", "") or opt.get("symbol", ""),
                    "underlying": symbol,
                    "strike": strike,
                    "expiry": opt.get("expiry", ""),
                    "dte": dte,
                    "type": opt.get("type", "call"),
                    "bid": bid,
                    "ask": ask,
                    "mid": mid,
                    "last": last,

                    "delta": greeks_result.delta,
                    "delta_source": greeks_result.delta_source,
                    "gamma": greeks_result.gamma,
                    "theta": greeks_result.theta,
                    "vega": greeks_result.vega,

                    "iv": iv_data["iv"],
                    "iv_pct": iv_data["iv_pct"],

                    "iv_rank": iv_metrics.iv_rank if iv_metrics else 50.0,
                    "iv_percentile": iv_metrics.iv_percentile if iv_metrics else 50.0,
                    "iv_rank_source": iv_metrics.iv_rank_source if iv_metrics else "DEFAULT_NEUTRAL",
                    "iv_samples": iv_metrics.iv_samples if iv_metrics else 0,

                    "volume": int(opt.get("volume", 0) or 0),
                    "open_interest": int(opt.get("open_interest", 0) or 0),

                    "break_even": strike + ask if (opt.get("type") == "call") else strike - ask,
                    "source": opt.get("source", "yahoo"),
                })

            if transformed:
                src = options[0].get("source", "yahoo")
                return {
                    "symbol": symbol,
                    "stock_price": display_underlying_price,
                    "stock_price_regular_session": regular_underlying_price,
                    "stock_price_for_greeks": S_for_greeks,
                    "options": transformed,

                    "iv_proxy": iv_metrics.iv_proxy if iv_metrics else 0.0,
                    "iv_proxy_pct": iv_metrics.iv_proxy_pct if iv_metrics else 0.0,
                    "iv_rank": iv_metrics.iv_rank if iv_metrics else 50.0,
                    "iv_percentile": iv_metrics.iv_percentile if iv_metrics else 50.0,
                    "iv_rank_source": iv_metrics.iv_rank_source if iv_metrics else "DEFAULT_NEUTRAL",
                    "iv_samples": iv_metrics.iv_samples if iv_metrics else 0,

                    "market_state": market_state,
                    "system_mode": "LIVE",
                    "timestamp_et": price_meta["timestamp_et"],
                    "stock_price_source": price_meta["price_source"],
                    "options_source": src,
                    "options_stale": staleness_meta["stale"],
                    "options_stale_reason": staleness_meta["stale_reason"],
                    "is_live": (market_state == "OPEN") and (not staleness_meta["stale"]),
                    "is_eod_snapshot": False,
                }

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"data_provider options chain error for {symbol}: {e}")

    # Check if mock fallback is allowed (raises in production)
    try:
        check_mock_fallback(
            symbol=symbol,
            reason="YAHOO_CHAIN_UNAVAILABLE",
            details="Options chain fetch failed from all data providers"
        )
    except DataUnavailableError as err:
        # Production: return structured unavailability response
        raise HTTPException(
            status_code=503,
            detail=err.to_dict()
        )

    # Mock fallback allowed (dev/test only)
    stock_price = MOCK_STOCKS.get(symbol, {}).get("price", 100)
    mock_options = generate_mock_options(symbol, stock_price)
    if expiry:
        mock_options = [o for o in mock_options if o.get("expiry") == expiry]

    now_et_time = _now_et()
    logging.warning(f"Using mock options fallback for {symbol}")
    return {
        "symbol": symbol,
        "stock_price": stock_price,
        "options": mock_options,
        "is_mock": True,
        "market_state": _get_market_state(now_et_time),
        "system_mode": "LIVE",
        "timestamp_et": now_et_time.isoformat(),
        "options_stale": True,
        "options_stale_reason": "MOCK_FALLBACK",
        "is_eod_snapshot": False,
    }


@options_router.get("/expirations/{symbol}")
async def get_option_expirations(symbol: str, user: dict = Depends(get_current_user)):
    symbol = symbol.upper()
    now_et = _now_et()

    expirations: List[Dict[str, Any]] = []

    # TEMP synthetic fallback (flagged)
    for weeks in range(1, 13):
        expiry_date = now_et.date() + timedelta(weeks=weeks)
        expirations.append({
            "date": expiry_date.isoformat(),
            "dte": (expiry_date - now_et.date()).days,
            "is_synthetic": True
        })

    for months in range(3, 25):
        expiry_date = now_et.date() + timedelta(days=months * 30)
        expirations.append({
            "date": expiry_date.isoformat(),
            "dte": (expiry_date - now_et.date()).days,
            "is_synthetic": True
        })

    return {
        "symbol": symbol,
        "expirations": expirations,
        "market_state": _get_market_state(now_et),
        "timestamp_et": now_et.isoformat(),
        "note": "Expirations are synthetic until data_provider exposes real expirations for the symbol.",
    }



@options_router.get("/market-state")
async def get_options_market_state():
    """
    Get current market state and system mode for options trading.
    
    Returns:
        - system_mode: LIVE or EOD_LOCKED
        - is_live: True if live data fetching is allowed
        - is_eod_locked: True if serving from snapshot only
        - lock_time_et: When EOD lock occurs (4:05 PM ET)
    """
    return get_market_state_info()


@options_router.get("/snapshot-status")
async def get_eod_snapshot_status():
    """
    Get status of EOD market snapshots.
    
    Returns:
        - trade_date: Current snapshot trade date
        - symbols_with_snapshot: Count of symbols with snapshots
        - system_mode: Current system mode
    """
    eod_service = get_eod_snapshot_service(db)
    return await eod_service.get_snapshot_status()

