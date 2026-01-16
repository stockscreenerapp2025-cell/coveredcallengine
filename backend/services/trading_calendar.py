"""
Trading Calendar Service
========================
Provides T-1 (previous trading day) market data date management.

PRIMARY PRINCIPLE: 
CCE must always use T-1 market close data (last completed trading session) for all scans,
calculations, and trade suggestions. No intraday or partial data.

DEFINITIONS:
- T (Today): Current calendar date
- T-1: Most recent completed US trading day
- Market Close: 4:00 PM ET on a valid trading day
- Business Day: US market trading day (excludes weekends and US market holidays)

DATA USAGE RULES:
1. Default & Only Data Source: Use T-1 market close data
2. No Intraday or Partial Data: Do not pull intraday quotes or mix data
3. Holiday & Weekend Handling: Automatically roll back to most recent completed trading day
"""

import logging
from datetime import datetime, timedelta, date
from typing import Optional, Tuple, Dict, List
from functools import lru_cache
import pytz

logger = logging.getLogger(__name__)

# US Eastern timezone for market operations
EASTERN_TZ = pytz.timezone('US/Eastern')

# Market hours
MARKET_CLOSE_HOUR = 16  # 4:00 PM ET
MARKET_CLOSE_MINUTE = 0

# Fallback US market holidays for 2024-2026 (used if pandas_market_calendars fails)
FALLBACK_US_HOLIDAYS = {
    # 2024
    "2024-01-01",  # New Year's Day
    "2024-01-15",  # MLK Day
    "2024-02-19",  # Presidents Day
    "2024-03-29",  # Good Friday
    "2024-05-27",  # Memorial Day
    "2024-06-19",  # Juneteenth
    "2024-07-04",  # Independence Day
    "2024-09-02",  # Labor Day
    "2024-11-28",  # Thanksgiving
    "2024-12-25",  # Christmas
    # 2025
    "2025-01-01",  # New Year's Day
    "2025-01-20",  # MLK Day
    "2025-02-17",  # Presidents Day
    "2025-04-18",  # Good Friday
    "2025-05-26",  # Memorial Day
    "2025-06-19",  # Juneteenth
    "2025-07-04",  # Independence Day
    "2025-09-01",  # Labor Day
    "2025-11-27",  # Thanksgiving
    "2025-12-25",  # Christmas
    # 2026
    "2026-01-01",  # New Year's Day
    "2026-01-19",  # MLK Day
    "2026-02-16",  # Presidents Day
    "2026-04-03",  # Good Friday
    "2026-05-25",  # Memorial Day
    "2026-06-19",  # Juneteenth
    "2026-07-03",  # Independence Day (observed)
    "2026-09-07",  # Labor Day
    "2026-11-26",  # Thanksgiving
    "2026-12-25",  # Christmas
}

# Cache for NYSE calendar
_nyse_calendar = None
_calendar_valid_trading_days = None


def _get_nyse_calendar():
    """Get NYSE trading calendar (lazy load)"""
    global _nyse_calendar, _calendar_valid_trading_days
    
    if _nyse_calendar is None:
        try:
            import pandas_market_calendars as mcal
            _nyse_calendar = mcal.get_calendar('NYSE')
            
            # Pre-compute valid trading days for 2024-2027
            start_date = '2024-01-01'
            end_date = '2027-12-31'
            schedule = _nyse_calendar.schedule(start_date=start_date, end_date=end_date)
            _calendar_valid_trading_days = set(schedule.index.strftime('%Y-%m-%d').tolist())
            
            logger.info(f"NYSE calendar initialized with {len(_calendar_valid_trading_days)} trading days")
        except Exception as e:
            logger.warning(f"Failed to initialize NYSE calendar: {e}. Using fallback holidays.")
            _nyse_calendar = "fallback"
            _calendar_valid_trading_days = None
    
    return _nyse_calendar, _calendar_valid_trading_days


def is_trading_day(check_date: date) -> bool:
    """
    Check if a given date is a valid US trading day.
    
    Args:
        check_date: The date to check
        
    Returns:
        True if it's a trading day, False otherwise
    """
    date_str = check_date.strftime('%Y-%m-%d')
    
    # Weekend check first (fastest)
    if check_date.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    
    # Try pandas_market_calendars
    calendar, valid_days = _get_nyse_calendar()
    
    if valid_days is not None:
        return date_str in valid_days
    
    # Fallback to hardcoded holidays
    return date_str not in FALLBACK_US_HOLIDAYS


def get_t_minus_1() -> Tuple[str, datetime]:
    """
    Get the T-1 (previous completed trading day) date.
    
    This is the PRIMARY function for data sourcing. All scans, calculations,
    and trade suggestions should use this date.
    
    Returns:
        Tuple of (date_string 'YYYY-MM-DD', datetime object at market close)
        
    Rules:
        - If today is a trading day and market has closed (after 4 PM ET): T-1 = today
        - If today is a trading day and market is open: T-1 = previous trading day
        - If today is a weekend/holiday: Roll back to most recent trading day
    """
    now_eastern = datetime.now(EASTERN_TZ)
    current_date = now_eastern.date()
    
    # Market close time for today
    market_close_today = now_eastern.replace(
        hour=MARKET_CLOSE_HOUR, 
        minute=MARKET_CLOSE_MINUTE, 
        second=0, 
        microsecond=0
    )
    
    # Determine if we should use today or go back
    if is_trading_day(current_date) and now_eastern >= market_close_today:
        # Today is a trading day and market has closed - T-1 is today
        t_minus_1_date = current_date
    else:
        # Need to find the previous trading day
        t_minus_1_date = current_date - timedelta(days=1)
        
        # Roll back until we find a valid trading day (max 10 days for safety)
        attempts = 0
        while not is_trading_day(t_minus_1_date) and attempts < 10:
            t_minus_1_date -= timedelta(days=1)
            attempts += 1
    
    # Create datetime at market close
    t_minus_1_datetime = EASTERN_TZ.localize(
        datetime.combine(t_minus_1_date, datetime.min.time().replace(
            hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE
        ))
    )
    
    logger.debug(f"T-1 calculated: {t_minus_1_date} (market close: {t_minus_1_datetime})")
    
    return t_minus_1_date.strftime('%Y-%m-%d'), t_minus_1_datetime


def get_trading_days_range(start_date: str, end_date: str) -> List[str]:
    """
    Get list of trading days between two dates.
    
    Args:
        start_date: Start date 'YYYY-MM-DD'
        end_date: End date 'YYYY-MM-DD'
        
    Returns:
        List of trading day date strings
    """
    calendar, valid_days = _get_nyse_calendar()
    
    if valid_days is not None:
        # Use calendar
        return sorted([d for d in valid_days if start_date <= d <= end_date])
    
    # Fallback: enumerate dates and filter
    result = []
    current = datetime.strptime(start_date, '%Y-%m-%d').date()
    end = datetime.strptime(end_date, '%Y-%m-%d').date()
    
    while current <= end:
        if is_trading_day(current):
            result.append(current.strftime('%Y-%m-%d'))
        current += timedelta(days=1)
    
    return result


def is_valid_expiration_date(expiry_date: str) -> Tuple[bool, Optional[str]]:
    """
    Validate if an option expiration date is valid.
    Options expire on trading days only (typically Fridays, but not always).
    
    Args:
        expiry_date: Expiration date 'YYYY-MM-DD'
        
    Returns:
        Tuple of (is_valid, reason if invalid)
    """
    try:
        exp_date = datetime.strptime(expiry_date, '%Y-%m-%d').date()
    except ValueError:
        return False, f"Invalid date format: {expiry_date}"
    
    # Check if it's a weekend (options don't expire on weekends)
    if exp_date.weekday() >= 5:
        weekday_name = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][exp_date.weekday()]
        return False, f"Options cannot expire on {weekday_name}"
    
    # Check if it's a holiday
    if not is_trading_day(exp_date):
        return False, f"{expiry_date} is a market holiday"
    
    return True, None


def is_friday_expiration(expiry_date: str) -> bool:
    """
    Check if an expiration date is a Friday (standard weekly expiration).
    
    Args:
        expiry_date: Expiration date 'YYYY-MM-DD'
        
    Returns:
        True if the date is a Friday
    """
    try:
        exp_date = datetime.strptime(expiry_date, '%Y-%m-%d').date()
        return exp_date.weekday() == 4  # Friday = 4
    except ValueError:
        return False


def is_monthly_expiration(expiry_date: str) -> bool:
    """
    Check if an expiration is a standard monthly (3rd Friday of the month).
    
    Args:
        expiry_date: Expiration date 'YYYY-MM-DD'
        
    Returns:
        True if the date is a monthly expiration (3rd Friday)
    """
    try:
        exp_date = datetime.strptime(expiry_date, '%Y-%m-%d').date()
        
        # Must be a Friday
        if exp_date.weekday() != 4:
            return False
        
        # Check if it's the 3rd Friday (day 15-21)
        if 15 <= exp_date.day <= 21:
            return True
        
        return False
    except ValueError:
        return False


def filter_valid_expirations(expirations: List[str], friday_only: bool = True) -> List[str]:
    """
    Filter a list of expiration dates to only include valid trading days.
    
    Args:
        expirations: List of expiration date strings
        friday_only: If True, only include Friday expirations (default True)
        
    Returns:
        Filtered list of valid expiration dates
    """
    valid = []
    for exp in expirations:
        is_valid, _ = is_valid_expiration_date(exp)
        if is_valid:
            # If friday_only, check if it's a Friday
            if friday_only and not is_friday_expiration(exp):
                continue
            valid.append(exp)
    return valid


def categorize_expirations(expirations: List[str]) -> Dict[str, List[str]]:
    """
    Categorize expirations into weekly and monthly buckets.
    
    Args:
        expirations: List of valid expiration date strings
        
    Returns:
        Dict with 'weekly' and 'monthly' lists
    """
    weekly = []
    monthly = []
    
    for exp in expirations:
        if is_monthly_expiration(exp):
            monthly.append(exp)
        elif is_friday_expiration(exp):
            weekly.append(exp)
    
    return {"weekly": weekly, "monthly": monthly}


def get_market_data_status() -> Dict:
    """
    Get current market data status for display/debugging.
    
    Returns:
        Dict with market status information
    """
    now_eastern = datetime.now(EASTERN_TZ)
    t1_date, t1_datetime = get_t_minus_1()
    
    # Calculate data age
    data_age_hours = (now_eastern - t1_datetime).total_seconds() / 3600
    
    # Determine next trading day
    next_trading = now_eastern.date()
    if not is_trading_day(next_trading) or now_eastern.hour >= MARKET_CLOSE_HOUR:
        next_trading += timedelta(days=1)
        attempts = 0
        while not is_trading_day(next_trading) and attempts < 10:
            next_trading += timedelta(days=1)
            attempts += 1
    
    # Next data refresh time (4:00 PM ET on next trading day)
    next_refresh = EASTERN_TZ.localize(
        datetime.combine(next_trading, datetime.min.time().replace(
            hour=MARKET_CLOSE_HOUR, minute=0
        ))
    )
    
    return {
        "current_time_et": now_eastern.strftime('%Y-%m-%d %H:%M:%S ET'),
        "t_minus_1_date": t1_date,
        "t_minus_1_market_close": t1_datetime.strftime('%Y-%m-%d %H:%M:%S ET'),
        "data_age_hours": round(data_age_hours, 1),
        "is_current_day_trading_day": is_trading_day(now_eastern.date()),
        "next_trading_day": next_trading.strftime('%Y-%m-%d'),
        "next_data_refresh": next_refresh.strftime('%Y-%m-%d %H:%M:%S ET'),
        "market_status": "closed" if data_age_hours > 0 else "open"
    }


def calculate_dte_from_t1(expiry_date: str) -> int:
    """
    Calculate Days to Expiration (DTE) from T-1 date.
    
    This ensures consistent DTE calculations across all components.
    
    Args:
        expiry_date: Expiration date 'YYYY-MM-DD'
        
    Returns:
        Number of calendar days from T-1 to expiration
    """
    try:
        t1_date_str, _ = get_t_minus_1()
        t1_date = datetime.strptime(t1_date_str, '%Y-%m-%d').date()
        exp_date = datetime.strptime(expiry_date, '%Y-%m-%d').date()
        return max(0, (exp_date - t1_date).days)
    except Exception as e:
        logger.warning(f"Error calculating DTE for {expiry_date}: {e}")
        return 0


def get_data_freshness_status(data_date: str) -> Dict:
    """
    Get freshness status for data with a specific date.
    
    Args:
        data_date: Date of the data 'YYYY-MM-DD'
        
    Returns:
        Dict with freshness status (green/amber/red) and description
    """
    t1_date_str, _ = get_t_minus_1()
    
    try:
        data_dt = datetime.strptime(data_date, '%Y-%m-%d').date()
        t1_dt = datetime.strptime(t1_date_str, '%Y-%m-%d').date()
        
        days_diff = (t1_dt - data_dt).days
        
        if days_diff == 0:
            return {
                "status": "green",
                "label": "Fresh",
                "description": f"Data from T-1 ({data_date})",
                "days_old": 0
            }
        elif days_diff <= 2:
            return {
                "status": "amber",
                "label": "Slightly Stale",
                "description": f"Data is {days_diff} day(s) old",
                "days_old": days_diff
            }
        else:
            return {
                "status": "red",
                "label": "Stale",
                "description": f"Data is {days_diff} days old - refresh recommended",
                "days_old": days_diff
            }
    except Exception as e:
        return {
            "status": "red",
            "label": "Unknown",
            "description": f"Could not determine data freshness: {e}",
            "days_old": None
        }


# Initialize calendar on module load
_get_nyse_calendar()
