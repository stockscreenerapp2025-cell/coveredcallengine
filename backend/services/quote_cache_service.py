"""
Option Quote Cache Service
==========================

CCE MASTER ARCHITECTURE - After-Hours Quote Management

PURPOSE:
When market is closed, provide the most recent valid BID/ASK quotes
from the last regular trading session.

RULES:
1. Store "last valid quote" during market hours when BID/ASK are non-zero
2. After hours, use cached quotes with proper timestamps
3. All prices marked with:
   - quote_source: "LAST_MARKET_SESSION" or "LIVE"
   - quote_timestamp: When the quote was captured
   - quote_age_hours: How old the quote is

FORBIDDEN:
- lastPrice fallbacks
- mid calculation
- synthetic prices
- previousClose for options
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Tuple
import pytz

logger = logging.getLogger(__name__)


class OptionQuoteCache:
    """
    Manages option quote caching for after-hours screening.
    
    Stores valid BID/ASK quotes during market hours and
    provides them with proper timestamps during after-hours.
    """
    
    def __init__(self, db):
        self.db = db
        self._eastern = pytz.timezone('US/Eastern')
    
    def is_market_open(self) -> bool:
        """Check if NYSE is currently open (9:30 AM - 4:00 PM ET, Mon-Fri)"""
        now = datetime.now(self._eastern)
        
        # Check weekday (0=Monday, 4=Friday)
        if now.weekday() > 4:
            return False
        
        # Check time (9:30 AM - 4:00 PM ET)
        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
        
        return market_open <= now <= market_close
    
    def get_market_session_info(self) -> Dict[str, Any]:
        """Get current market session information"""
        now = datetime.now(self._eastern)
        is_open = self.is_market_open()
        
        # Find last trading day's close time
        last_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
        
        if now.weekday() > 4:  # Weekend
            # Go back to Friday 4 PM
            days_back = now.weekday() - 4
            last_close = last_close - timedelta(days=days_back)
        elif now.hour < 16 or (not is_open and now.hour >= 16):
            # Before today's close or after hours
            if now.weekday() == 0 and now.hour < 9:  # Monday early morning
                last_close = last_close - timedelta(days=3)  # Friday
            elif now.hour < 9 or (now.hour == 9 and now.minute < 30):
                # Before today's open
                last_close = last_close - timedelta(days=1)
                if last_close.weekday() > 4:
                    last_close = last_close - timedelta(days=last_close.weekday() - 4)
        
        return {
            "is_open": is_open,
            "current_time_et": now.strftime("%Y-%m-%d %H:%M:%S ET"),
            "last_close_time": last_close.strftime("%Y-%m-%d %H:%M:%S ET"),
            "hours_since_close": (now - last_close).total_seconds() / 3600 if not is_open else 0
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
        """
        Cache a valid quote during market hours.
        
        Only caches if:
        - Market is open
        - BID > 0 (for SELL eligibility)
        - ASK > 0 (for BUY eligibility)
        
        Returns True if quote was cached.
        """
        if not self.is_market_open():
            return False
        
        if bid <= 0 and ask <= 0:
            return False
        
        now = datetime.now(timezone.utc)
        session_date = datetime.now(self._eastern).strftime("%Y-%m-%d")
        
        quote_doc = {
            "contract_symbol": contract_symbol,
            "symbol": symbol,
            "strike": strike,
            "expiry": expiry,
            "dte": dte,
            "bid": bid if bid > 0 else None,
            "ask": ask if ask > 0 else None,
            "quote_timestamp": now,
            "session_date": session_date,
            "quote_source": "LIVE"
        }
        
        # Upsert by contract symbol
        await self.db.option_quote_cache.update_one(
            {"contract_symbol": contract_symbol},
            {"$set": quote_doc},
            upsert=True
        )
        
        return True
    
    async def get_cached_quote(
        self,
        contract_symbol: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached quote for a contract.
        
        Returns quote with:
        - quote_source: "LAST_MARKET_SESSION"
        - quote_timestamp: When captured
        - quote_age_hours: How old
        """
        quote = await self.db.option_quote_cache.find_one(
            {"contract_symbol": contract_symbol},
            {"_id": 0}
        )
        
        if not quote:
            return None
        
        # Calculate quote age
        quote_time = quote.get("quote_timestamp")
        if quote_time:
            now = datetime.now(timezone.utc)
            age_hours = (now - quote_time).total_seconds() / 3600
            quote["quote_age_hours"] = round(age_hours, 1)
        
        # Mark as last market session if market is closed
        if not self.is_market_open():
            quote["quote_source"] = "LAST_MARKET_SESSION"
        
        return quote
    
    async def get_valid_quote_for_sell(
        self,
        contract_symbol: str,
        live_bid: float = None,
        live_ask: float = None
    ) -> Tuple[Optional[float], str, Optional[str]]:
        """
        Get valid BID for SELL leg.
        
        Returns: (bid_price, quote_source, quote_timestamp)
        
        Priority:
        1. Live BID if > 0 and market open
        2. Cached BID from last market session
        """
        is_open = self.is_market_open()
        
        # If market open and live BID available, use it
        if is_open and live_bid and live_bid > 0:
            return live_bid, "LIVE", datetime.now(timezone.utc).isoformat()
        
        # Try cached quote
        cached = await self.get_cached_quote(contract_symbol)
        if cached and cached.get("bid") and cached["bid"] > 0:
            return (
                cached["bid"],
                "LAST_MARKET_SESSION",
                cached.get("quote_timestamp", "").isoformat() if cached.get("quote_timestamp") else None
            )
        
        # No valid BID available
        return None, "NO_VALID_BID", None
    
    async def get_valid_quote_for_buy(
        self,
        contract_symbol: str,
        live_ask: float = None,
        live_bid: float = None
    ) -> Tuple[Optional[float], str, Optional[str]]:
        """
        Get valid ASK for BUY leg.
        
        Returns: (ask_price, quote_source, quote_timestamp)
        
        Priority:
        1. Live ASK if > 0 and market open
        2. Cached ASK from last market session
        """
        is_open = self.is_market_open()
        
        # If market open and live ASK available, use it
        if is_open and live_ask and live_ask > 0:
            return live_ask, "LIVE", datetime.now(timezone.utc).isoformat()
        
        # Try cached quote
        cached = await self.get_cached_quote(contract_symbol)
        if cached and cached.get("ask") and cached["ask"] > 0:
            return (
                cached["ask"],
                "LAST_MARKET_SESSION",
                cached.get("quote_timestamp", "").isoformat() if cached.get("quote_timestamp") else None
            )
        
        # No valid ASK available
        return None, "NO_VALID_ASK", None
    
    async def cleanup_old_quotes(self, max_age_hours: int = 72) -> int:
        """
        Remove quotes older than max_age_hours.
        
        Default 72 hours allows weekend data to persist until Monday.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        
        result = await self.db.option_quote_cache.delete_many({
            "quote_timestamp": {"$lt": cutoff}
        })
        
        return result.deleted_count
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """Get statistics about the quote cache"""
        total = await self.db.option_quote_cache.count_documents({})
        
        # Count by session date
        pipeline = [
            {"$group": {"_id": "$session_date", "count": {"$sum": 1}}},
            {"$sort": {"_id": -1}},
            {"$limit": 5}
        ]
        
        by_date = await self.db.option_quote_cache.aggregate(pipeline).to_list(5)
        
        market_info = self.get_market_session_info()
        
        return {
            "total_cached_quotes": total,
            "quotes_by_session_date": {d["_id"]: d["count"] for d in by_date},
            "market_status": market_info
        }


# Singleton instance
_quote_cache_instance = None


def get_quote_cache(db) -> OptionQuoteCache:
    """Get or create the quote cache singleton"""
    global _quote_cache_instance
    if _quote_cache_instance is None:
        _quote_cache_instance = OptionQuoteCache(db)
    return _quote_cache_instance
