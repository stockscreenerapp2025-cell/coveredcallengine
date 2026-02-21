"""
Market State Enforcement Utility
================================

Implements deterministic EOD snapshot lock at 4:05 PM ET.

SYSTEM MODES:
- LIVE: During market hours (9:30 AM - 4:05 PM ET), use live data fetching
- EOD_LOCKED: After 4:05 PM ET until next market open, serve ONLY from eod_market_snapshot

NON-NEGOTIABLES:
- No mock data in production
- No live rebuilding after 4:05 PM ET
- No mixing live underlying with cached options
- Snapshot is sole source of truth after lock time
"""

import logging
from datetime import datetime, time
from typing import Literal, Dict, Any, Optional
from zoneinfo import ZoneInfo
import pandas_market_calendars as mcal

logger = logging.getLogger(__name__)

# Timezone: Always US/Eastern
ET = ZoneInfo("America/New_York")

# Lock time: 4:05 PM ET
EOD_LOCK_HOUR = 16
EOD_LOCK_MINUTE = 5

# Market hours
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 30
MARKET_CLOSE_HOUR = 16
MARKET_CLOSE_MINUTE = 0

# System modes
SystemMode = Literal["LIVE", "EOD_LOCKED"]

# NYSE Calendar singleton
_nyse_calendar = None

def _get_nyse_calendar():
    """Get or create NYSE calendar singleton."""
    global _nyse_calendar
    if _nyse_calendar is None:
        _nyse_calendar = mcal.get_calendar('NYSE')
    return _nyse_calendar


def now_et() -> datetime:
    """Get current time in ET timezone."""
    return datetime.now(ET)


def is_weekend(dt: datetime = None) -> bool:
    """Check if date is weekend (Saturday=5, Sunday=6)."""
    dt = dt or now_et()
    return dt.weekday() >= 5


def is_nyse_holiday(dt: datetime = None) -> bool:
    """Check if date is an NYSE holiday."""
    dt = dt or now_et()
    try:
        calendar = _get_nyse_calendar()
        schedule = calendar.schedule(
            start_date=dt.strftime('%Y-%m-%d'),
            end_date=dt.strftime('%Y-%m-%d')
        )
        return schedule.empty
    except Exception as e:
        logger.warning(f"NYSE calendar check failed: {e}")
        # Default to not a holiday if calendar fails
        return False


def is_trading_day(dt: datetime = None) -> bool:
    """Check if date is a valid NYSE trading day."""
    dt = dt or now_et()
    return not is_weekend(dt) and not is_nyse_holiday(dt)


def is_before_market_open(dt: datetime = None) -> bool:
    """Check if time is before market open (9:30 AM ET)."""
    dt = dt or now_et()
    market_open = dt.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0)
    return dt < market_open


def is_after_eod_lock(dt: datetime = None) -> bool:
    """Check if time is at or after EOD lock (4:05 PM ET)."""
    dt = dt or now_et()
    lock_time = dt.replace(hour=EOD_LOCK_HOUR, minute=EOD_LOCK_MINUTE, second=0, microsecond=0)
    return dt >= lock_time


def is_market_open(dt: datetime = None) -> bool:
    """
    Check if market is currently open.
    Market is open: weekday, not holiday, 9:30 AM - 4:00 PM ET.
    """
    dt = dt or now_et()
    
    if not is_trading_day(dt):
        return False
    
    market_open = dt.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0)
    market_close = dt.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE, second=0, microsecond=0)
    
    return market_open <= dt < market_close


def get_system_mode(dt: datetime = None) -> SystemMode:
    """
    Determine system mode based on current time.
    
    LIVE: During market hours up to 4:05 PM ET
    EOD_LOCKED: After 4:05 PM ET or outside trading days
    
    Returns:
        SystemMode: "LIVE" or "EOD_LOCKED"
    """
    dt = dt or now_et()
    
    # Non-trading days are always EOD_LOCKED
    if not is_trading_day(dt):
        return "EOD_LOCKED"
    
    # Before market open: EOD_LOCKED (use previous day's snapshot)
    if is_before_market_open(dt):
        return "EOD_LOCKED"
    
    # At or after 4:05 PM ET: EOD_LOCKED
    if is_after_eod_lock(dt):
        return "EOD_LOCKED"
    
    # During market hours (9:30 AM - 4:05 PM ET): LIVE
    return "LIVE"


def get_eod_lock_time(dt: datetime = None) -> datetime:
    """Get the EOD lock time (4:05 PM ET) for a given date."""
    dt = dt or now_et()
    return dt.replace(hour=EOD_LOCK_HOUR, minute=EOD_LOCK_MINUTE, second=0, microsecond=0)


def get_market_state_info(dt: datetime = None) -> Dict[str, Any]:
    """
    Get comprehensive market state information.
    
    Returns:
        Dict with system_mode, is_live, lock_time, etc.
    """
    dt = dt or now_et()
    system_mode = get_system_mode(dt)
    
    return {
        "system_mode": system_mode,
        "is_live": system_mode == "LIVE",
        "is_eod_locked": system_mode == "EOD_LOCKED",
        "is_trading_day": is_trading_day(dt),
        "is_market_open": is_market_open(dt),
        "is_weekend": is_weekend(dt),
        "is_holiday": is_nyse_holiday(dt) if is_trading_day(dt) is False and not is_weekend(dt) else False,
        "is_before_open": is_before_market_open(dt),
        "is_after_lock": is_after_eod_lock(dt),
        "current_time_et": dt.isoformat(),
        "eod_lock_time_et": get_eod_lock_time(dt).isoformat(),
        "market_open_time": f"{MARKET_OPEN_HOUR:02d}:{MARKET_OPEN_MINUTE:02d}",
        "eod_lock_time": f"{EOD_LOCK_HOUR:02d}:{EOD_LOCK_MINUTE:02d}",
    }


def get_last_trading_day(dt: datetime = None) -> str:
    """
    Get the last trading day's date string (YYYY-MM-DD).
    
    - If currently EOD_LOCKED on a trading day, returns today
    - If weekend, returns Friday
    - If before market open, returns previous trading day
    """
    dt = dt or now_et()
    
    # If it's a trading day and after EOD lock, today is the reference
    if is_trading_day(dt) and is_after_eod_lock(dt):
        return dt.strftime('%Y-%m-%d')
    
    # If it's a trading day and market is open or before lock, use previous day
    if is_trading_day(dt) and not is_after_eod_lock(dt):
        # Before lock time, previous trading day's snapshot is current
        pass  # Fall through to calendar lookup
    
    # Use NYSE calendar to find last trading day
    try:
        from datetime import timedelta
        calendar = _get_nyse_calendar()
        end_date = dt.strftime('%Y-%m-%d')
        start_dt = dt - timedelta(days=10)
        schedule = calendar.schedule(
            start_date=start_dt.strftime('%Y-%m-%d'),
            end_date=end_date
        )
        
        if not schedule.empty:
            # Get the last trading day from schedule
            last_day = schedule.index[-1]
            last_day_date = last_day.to_pydatetime().date()
            
            # If today is in schedule and before lock time, use previous day
            today_date = dt.date()
            if last_day_date == today_date and not is_after_eod_lock(dt):
                if len(schedule) > 1:
                    last_day = schedule.index[-2]
                    return last_day.strftime('%Y-%m-%d')
            
            return last_day.strftime('%Y-%m-%d')
    except Exception as e:
        logger.warning(f"Calendar lookup failed: {e}")
    
    # Fallback: simple weekday rollback
    from datetime import timedelta
    current = dt
    if not is_after_eod_lock(dt):
        current = current - timedelta(days=1)
    
    while current.weekday() >= 5:  # Skip weekends
        current = current - timedelta(days=1)
    
    return current.strftime('%Y-%m-%d')


class EODLockViolationError(Exception):
    """
    Raised when attempting live data fetch during EOD_LOCKED mode.
    
    This is a critical error - system must serve from snapshot only.
    """
    def __init__(self, operation: str, reason: str = None):
        self.operation = operation
        self.reason = reason or "Live data fetch blocked during EOD_LOCKED mode"
        super().__init__(f"{operation}: {self.reason}")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_type": "EOD_LOCK_VIOLATION",
            "operation": self.operation,
            "reason": self.reason,
            "system_mode": "EOD_LOCKED",
            "message": "After 4:05 PM ET, all data must come from the stored EOD snapshot. No live fetching permitted."
        }


class EODSnapshotNotAvailableError(Exception):
    """
    Raised when EOD snapshot is not available for a required symbol.
    
    Used when system is in EOD_LOCKED mode but snapshot doesn't exist.
    """
    def __init__(self, symbol: str, trade_date: str = None, reason: str = None):
        self.symbol = symbol
        self.trade_date = trade_date
        self.reason = reason or "EOD snapshot not available"
        super().__init__(f"[{symbol}] {self.reason}")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "data_status": "EOD_SNAPSHOT_NOT_AVAILABLE",
            "symbol": self.symbol,
            "trade_date": self.trade_date,
            "reason": self.reason,
            "message": f"No EOD snapshot available for {self.symbol}. Data cannot be served in EOD_LOCKED mode."
        }


def enforce_live_mode(operation: str):
    """
    Decorator/guard to enforce LIVE mode for data fetching operations.
    
    Raises EODLockViolationError if system is in EOD_LOCKED mode.
    
    Usage:
        enforce_live_mode("fetch_options_chain")  # Raises if locked
    """
    system_mode = get_system_mode()
    if system_mode == "EOD_LOCKED":
        raise EODLockViolationError(
            operation=operation,
            reason=f"Cannot perform {operation} - system is EOD_LOCKED. Use stored snapshot data only."
        )


def log_eod_event(event_type: str, **kwargs):
    """Log EOD-related events in a standard format."""
    dt = now_et()
    system_mode = get_system_mode(dt)
    
    log_data = {
        "event": event_type,
        "system_mode": system_mode,
        "time_et": dt.isoformat(),
        **kwargs
    }
    
    if event_type == "SNAPSHOT_CREATED":
        logger.info(f"[EOD-SNAPSHOT-CREATED] run_id={kwargs.get('run_id')} symbols={kwargs.get('symbols_count')}")
    elif event_type == "SNAPSHOT_FAILED":
        logger.error(f"[EOD-SNAPSHOT-FAILED] symbol={kwargs.get('symbol')} reason={kwargs.get('reason')}")
    elif event_type == "LIVE_BLOCKED":
        logger.warning(f"[EOD-LIVE-BLOCKED] operation={kwargs.get('operation')} reason=EOD_LOCKED")
    else:
        logger.info(f"[EOD-{event_type}] {log_data}")
