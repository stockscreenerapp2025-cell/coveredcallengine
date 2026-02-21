"""
Option Quote Cache Service
==========================

CCE MASTER ARCHITECTURE - After-Hours Quote Management

PURPOSE:
When market is closed, provide the most recent valid BID/ASK quotes
from the last regular trading session.

RULES:
1. Store "last valid quote" during market hours when BID/ASK are non-zero
2. After-hours, use cached quotes with proper timestamps
3. All prices marked with:
   - quote_source: "LAST_MARKET_SESSION" or "LIVE"
   - quote_timestamp: When the quote was captured
   - quote_age_hours: How old the quote is

NOTE (Feb 2026 hardening):
- Time logic is America/New_York (ET) aware.
- We treat the "session lock" timestamp as 16:05 ET (not 16:00) to avoid
  edge cases where late prints/updates arrive right after 4:00.
- We do NOT block execution outside market hours; we only switch quote selection.
"""

import logging
from datetime import datetime, timezone, timedelta, date
from typing import Dict, Any, Optional, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

NY = ZoneInfo("America/New_York")


def _now_et() -> datetime:
    return datetime.now(NY)


def _is_weekend(d: date) -> bool:
    return d.weekday() >= 5


def _is_market_open(now_et: datetime) -> bool:
    if _is_weekend(now_et.date()):
        return False
    minutes = now_et.hour * 60 + now_et.minute
    open_m = 9 * 60 + 30
    close_m = 16 * 60
    return open_m <= minutes < close_m


def _session_lock_time_et(now_et: datetime) -> datetime:
    """
    Lock time for the 'final synced' session snapshot: 16:05 ET.
    """
    return now_et.replace(hour=16, minute=5, second=0, microsecond=0)


class OptionQuoteCache:
    def __init__(self, db):
        self.db = db

    def is_market_open(self) -> bool:
        return _is_market_open(_now_et())

    def get_market_session_info(self) -> Dict[str, Any]:
        now = _now_et()
        is_open = _is_market_open(now)

        # Compute last lock time (16:05 ET) for the most recent trading day
        last_lock = _session_lock_time_et(now)

        # Weekend -> previous Friday
        if _is_weekend(now.date()):
            # Sat (5) -> back 1 day, Sun (6) -> back 2 days to Friday
            days_back = now.weekday() - 4
            last_lock = last_lock - timedelta(days=days_back)

        # If it's before today's lock time, use previous trading day's lock
        if now < last_lock:
            # Monday morning -> go back to Friday lock
            if now.weekday() == 0:
                last_lock = last_lock - timedelta(days=3)
            else:
                last_lock = last_lock - timedelta(days=1)
                # If we rolled into weekend, roll back to Friday
                if last_lock.weekday() == 6:
                    last_lock = last_lock - timedelta(days=2)
                elif last_lock.weekday() == 5:
                    last_lock = last_lock - timedelta(days=1)

        hours_since_close = 0.0
        if not is_open:
            hours_since_close = max(0.0, (now - last_lock).total_seconds() / 3600.0)

        return {
            "is_open": is_open,
            "current_time_et": now.isoformat(),
            "last_close_time_et": last_lock.isoformat(),
            "hours_since_close": hours_since_close,
        }

    async def cache_valid_quote(
        self,
        contract_symbol: str,
        symbol: str,
        strike: float,
        expiry: str,
        bid: float,
        ask: float,
        dte: int
    ) -> bool:
        if not self.is_market_open():
            return False
        if (bid or 0) <= 0 and (ask or 0) <= 0:
            return False

        now_utc = datetime.now(timezone.utc)
        session_date = _now_et().date().isoformat()

        quote_doc = {
            "contract_symbol": contract_symbol,
            "symbol": symbol.upper(),
            "strike": strike,
            "expiry": expiry,
            "dte": dte,
            "bid": bid if (bid or 0) > 0 else None,
            "ask": ask if (ask or 0) > 0 else None,
            "quote_timestamp": now_utc,
            "session_date": session_date,
            "quote_source": "LIVE",
        }

        await self.db.option_quote_cache.update_one(
            {"contract_symbol": contract_symbol},
            {"$set": quote_doc},
            upsert=True
        )
        return True

    async def get_cached_quote(self, contract_symbol: str) -> Optional[Dict[str, Any]]:
        quote = await self.db.option_quote_cache.find_one({"contract_symbol": contract_symbol}, {"_id": 0})
        if not quote:
            return None

        qt = quote.get("quote_timestamp")
        if qt:
            now = datetime.now(timezone.utc)
            quote["quote_age_hours"] = round((now - qt).total_seconds() / 3600.0, 1)

        if not self.is_market_open():
            quote["quote_source"] = "LAST_MARKET_SESSION"

        return quote

    async def get_valid_quote_for_sell(
        self,
        contract_symbol: str,
        live_bid: float = None,
        live_ask: float = None
    ) -> Tuple[Optional[float], str, Optional[str]]:
        is_open = self.is_market_open()
        if is_open and live_bid and live_bid > 0:
            return live_bid, "LIVE", datetime.now(timezone.utc).isoformat()

        cached = await self.get_cached_quote(contract_symbol)
        if cached and cached.get("bid") and cached["bid"] > 0:
            ts = cached.get("quote_timestamp")
            return cached["bid"], "LAST_MARKET_SESSION", ts.isoformat() if ts else None

        return None, "NO_VALID_BID", None

    async def get_valid_quote_for_buy(
        self,
        contract_symbol: str,
        live_ask: float = None,
        live_bid: float = None
    ) -> Tuple[Optional[float], str, Optional[str]]:
        is_open = self.is_market_open()
        if is_open and live_ask and live_ask > 0:
            return live_ask, "LIVE", datetime.now(timezone.utc).isoformat()

        cached = await self.get_cached_quote(contract_symbol)
        if cached and cached.get("ask") and cached["ask"] > 0:
            ts = cached.get("quote_timestamp")
            return cached["ask"], "LAST_MARKET_SESSION", ts.isoformat() if ts else None

        return None, "NO_VALID_ASK", None

    async def cleanup_old_quotes(self, max_age_hours: int = 72) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        result = await self.db.option_quote_cache.delete_many({"quote_timestamp": {"$lt": cutoff}})
        return result.deleted_count

    async def get_cache_stats(self) -> Dict[str, Any]:
        total = await self.db.option_quote_cache.count_documents({})
        pipeline = [
            {"$group": {"_id": "$session_date", "count": {"$sum": 1}}},
            {"$sort": {"_id": -1}},
            {"$limit": 5},
        ]
        by_date = await self.db.option_quote_cache.aggregate(pipeline).to_list(5)
        return {
            "total_cached_quotes": total,
            "quotes_by_session_date": {d["_id"]: d["count"] for d in by_date},
            "market_status": self.get_market_session_info(),
        }


_quote_cache_instance = None

def get_quote_cache(db) -> OptionQuoteCache:
    global _quote_cache_instance
    if _quote_cache_instance is None:
        _quote_cache_instance = OptionQuoteCache(db)
    return _quote_cache_instance
