"""
Snapshot Service - PHASE 1: Data Ingestion Layer
=================================================

CCE MASTER ARCHITECTURE COMPLIANCE - LAYER 1

This service implements the two-phase architecture:
- PHASE 1 (Ingestion): Fetch and store snapshots with full metadata
- PHASE 2 (Scan): Read-only access to stored snapshots

GLOBAL RULES ENFORCED (NON-NEGOTIABLE):
- Stock price = PREVIOUS NYSE MARKET CLOSE ONLY
  ❌ No intraday prices (regularMarketPrice)
  ❌ No pre-market prices
  ❌ No after-hours prices
- NYSE trading calendar enforced for all date logic
- BID only for SELL legs
- ASK only for BUY legs (PMCC LEAP)
- Stock and options snapshot dates MUST match
- Full chain validation before storage

MANDATORY SNAPSHOT SCHEMA FIELDS:
Stock Snapshots:
  - stock_close_price (previous NYSE close - THE ONLY VALID PRICE)
  - stock_price_trade_date (LTD - must equal snapshot_trade_date)
  - volume, avg_volume, market_cap
  - earnings_date, analyst_rating

Option Snapshots:
  - bid, ask (separate - NEVER averaged)
  - open_interest, implied_volatility
  - delta (estimated for ITM), iv_rank
  - options_data_trade_day (must equal stock trade date)
"""

import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
from concurrent.futures import ThreadPoolExecutor
import pandas_market_calendars as mcal
import yfinance as yf
import httpx
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

# ==================== LAYER 1 CONSTANTS ====================
HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
POLYGON_BASE_URL = "https://api.polygon.io"
MAX_DATA_AGE_HOURS = 48  # Reject snapshots older than this

# CRITICAL: These are the ONLY valid price sources
# ✅ previousClose - Last NYSE market close
# ❌ regularMarketPrice - FORBIDDEN (intraday)
# ❌ currentPrice - FORBIDDEN (intraday)
# ❌ preMarketPrice - FORBIDDEN
# ❌ postMarketPrice - FORBIDDEN


class SnapshotService:
    """
    Manages data snapshots for deterministic scanning.
    
    Two-phase architecture:
    1. Ingestion: Fetch from Yahoo/Polygon, validate, store with metadata
    2. Scan: Read-only from stored snapshots, abort if missing/stale
    """
    
    def __init__(self, db: AsyncIOMotorDatabase, polygon_api_key: str = None):
        self.db = db
        self.polygon_api_key = polygon_api_key
        self._executor = ThreadPoolExecutor(max_workers=10)
        self._nyse_calendar = mcal.get_calendar('NYSE')
    
    # ==================== NYSE CALENDAR HELPERS ====================
    
    def get_last_trading_day(self, reference_date: datetime = None) -> datetime:
        """Get the most recent NYSE trading day."""
        if reference_date is None:
            reference_date = datetime.now(timezone.utc)
        
        # Get schedule for last 10 days to find most recent trading day
        start = reference_date - timedelta(days=10)
        end = reference_date
        
        schedule = self._nyse_calendar.schedule(
            start_date=start.strftime('%Y-%m-%d'),
            end_date=end.strftime('%Y-%m-%d')
        )
        
        if schedule.empty:
            # Fallback: subtract days until we hit a weekday
            current = reference_date
            while current.weekday() >= 5:  # Saturday = 5, Sunday = 6
                current -= timedelta(days=1)
            return current.replace(hour=16, minute=0, second=0, microsecond=0)
        
        # Get the last trading day from schedule
        last_day = schedule.index[-1]
        return last_day.to_pydatetime().replace(tzinfo=timezone.utc)
    
    def is_trading_day(self, date: datetime = None) -> bool:
        """Check if a given date is an NYSE trading day."""
        if date is None:
            date = datetime.now(timezone.utc)
        
        schedule = self._nyse_calendar.schedule(
            start_date=date.strftime('%Y-%m-%d'),
            end_date=date.strftime('%Y-%m-%d')
        )
        return not schedule.empty
    
    def get_market_close_time(self, date: datetime = None) -> Optional[datetime]:
        """Get market close time for a given date."""
        if date is None:
            date = datetime.now(timezone.utc)
        
        schedule = self._nyse_calendar.schedule(
            start_date=date.strftime('%Y-%m-%d'),
            end_date=date.strftime('%Y-%m-%d')
        )
        
        if schedule.empty:
            return None
        
        return schedule.iloc[0]['market_close'].to_pydatetime()
    
    # ==================== PHASE 1: DATA INGESTION ====================
    
    async def ingest_stock_snapshot(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch and store stock snapshot with full metadata.
        
        CCE MASTER ARCHITECTURE - LAYER 1 COMPLIANT
        
        MANDATORY: Uses PREVIOUS NYSE CLOSE ONLY
        ❌ FORBIDDEN: regularMarketPrice, currentPrice, preMarket, afterHours
        
        Returns snapshot document with:
        - stock_close_price: THE ONLY VALID PRICE (previous NYSE close)
        - stock_price_trade_date: LTD when price was established
        - snapshot_trade_date: The trading day this data represents
        - snapshot_time: When the snapshot was taken
        - data_age_hours: Hours since market close
        - completeness_flag: Whether all required fields are present
        - source: Data provider used
        - volume, avg_volume, market_cap: Liquidity/size metrics
        - earnings_date: For ±7 day exclusion in Layer 3
        """
        now = datetime.now(timezone.utc)
        ltd = self.get_last_trading_day(now)
        ltd_str = ltd.strftime('%Y-%m-%d')
        
        # LAYER 1 COMPLIANT SCHEMA
        snapshot = {
            "symbol": symbol.upper(),
            # DATE FIELDS (must be consistent)
            "snapshot_trade_date": ltd_str,
            "stock_price_trade_date": ltd_str,  # MANDATORY: LTD for price
            "snapshot_time": now.isoformat(),
            "data_age_hours": 0,
            # PRICE FIELD - PREVIOUS CLOSE ONLY
            "stock_close_price": None,  # THE ONLY VALID PRICE
            # Legacy field for backward compatibility (will be deprecated)
            "price": None,
            # LIQUIDITY/SIZE METRICS
            "volume": None,
            "avg_volume": None,
            "market_cap": None,
            # DOWNSTREAM FIELDS
            "earnings_date": None,
            "analyst_rating": None,
            # METADATA
            "completeness_flag": False,
            "source": None,
            "error": None
        }
        
        try:
            # Try Yahoo Finance first
            data = await self._fetch_stock_yahoo(symbol)
            
            if data and data.get("previous_close"):
                # CRITICAL: Use ONLY previousClose, not regularMarketPrice
                previous_close = data["previous_close"]
                
                snapshot.update({
                    "source": "yahoo",
                    "stock_close_price": previous_close,  # MANDATORY FIELD
                    "price": previous_close,  # Legacy compatibility
                    "volume": data.get("volume"),
                    "market_cap": data.get("market_cap"),
                    "avg_volume": data.get("avg_volume"),
                    "earnings_date": data.get("earnings_date"),
                    "analyst_rating": data.get("analyst_rating"),
                    "completeness_flag": True
                })
                
                logger.info(f"[LAYER1] {symbol}: Using previousClose=${previous_close} (LTD={ltd_str})")
                
            elif self.polygon_api_key:
                # Fallback to Polygon (already uses close price from previous day)
                data = await self._fetch_stock_polygon(symbol)
                if data and data.get("price"):
                    snapshot.update({
                        "source": "polygon",
                        "stock_close_price": data["price"],  # Polygon /prev returns previous close
                        "price": data["price"],  # Legacy compatibility
                        "volume": data.get("volume"),
                        "completeness_flag": True
                    })
                    
                    logger.info(f"[LAYER1] {symbol}: Polygon fallback, close=${data['price']} (LTD={ltd_str})")
            
            # Calculate data age from market close
            market_close = self.get_market_close_time(ltd)
            if market_close:
                age_delta = now - market_close
                snapshot["data_age_hours"] = round(age_delta.total_seconds() / 3600, 1)
            
            # Store in database
            await self.db.stock_snapshots.update_one(
                {"symbol": symbol.upper()},
                {"$set": snapshot},
                upsert=True
            )
            
            logger.info(f"Ingested stock snapshot for {symbol}: stock_close_price=${snapshot.get('stock_close_price')}, source={snapshot.get('source')}")
            
        except Exception as e:
            snapshot["error"] = str(e)
            logger.error(f"Error ingesting stock snapshot for {symbol}: {e}")
        
        return snapshot
    
    async def ingest_option_chain_snapshot(self, symbol: str, stock_price: float) -> Dict[str, Any]:
        """
        Fetch and store complete option chain snapshot with full metadata.
        
        CRITICAL: Stores BID and ASK separately for proper pricing enforcement.
        
        Returns snapshot document with:
        - All expiries and strikes available
        - BID/ASK for each contract (not midpoint!)
        - Completeness validation
        """
        now = datetime.now(timezone.utc)
        ltd = self.get_last_trading_day(now)
        
        snapshot = {
            "symbol": symbol.upper(),
            "stock_price": stock_price,
            "snapshot_trade_date": ltd.strftime('%Y-%m-%d'),
            "options_snapshot_time": now.isoformat(),
            "options_data_trade_day": ltd.strftime('%Y-%m-%d'),
            "data_age_hours": 0,
            "completeness_flag": False,
            "source": None,
            "expiries": [],
            "calls": [],
            "puts": [],
            "total_contracts": 0,
            "valid_contracts": 0,
            "rejection_reasons": [],
            "error": None
        }
        
        try:
            # Fetch from Yahoo (has BID/ASK data)
            chain_data = await self._fetch_option_chain_yahoo(symbol, stock_price)
            
            if chain_data:
                snapshot.update({
                    "source": "yahoo",
                    "expiries": chain_data.get("expiries", []),
                    "calls": chain_data.get("calls", []),
                    "puts": chain_data.get("puts", []),
                    "total_contracts": chain_data.get("total_contracts", 0),
                    "valid_contracts": chain_data.get("valid_contracts", 0),
                    "rejection_reasons": chain_data.get("rejection_reasons", [])
                })
                
                # Validate completeness
                snapshot["completeness_flag"] = self._validate_chain_completeness(
                    snapshot, stock_price
                )
            
            # Calculate data age
            market_close = self.get_market_close_time(ltd)
            if market_close:
                age_delta = now - market_close
                snapshot["data_age_hours"] = round(age_delta.total_seconds() / 3600, 1)
            
            # Store in database
            await self.db.option_chain_snapshots.update_one(
                {"symbol": symbol.upper()},
                {"$set": snapshot},
                upsert=True
            )
            
            logger.info(f"Ingested option chain for {symbol}: {snapshot['valid_contracts']} valid contracts, complete={snapshot['completeness_flag']}")
            
        except Exception as e:
            snapshot["error"] = str(e)
            logger.error(f"Error ingesting option chain for {symbol}: {e}")
        
        return snapshot
    
    async def _fetch_stock_yahoo(self, symbol: str) -> Optional[Dict]:
        """
        Fetch stock data from Yahoo Finance.
        
        CCE MASTER ARCHITECTURE - LAYER 1 COMPLIANT
        
        CRITICAL: Returns ONLY previousClose as the price source.
        
        ❌ FORBIDDEN FIELDS (NEVER USE):
           - regularMarketPrice (intraday)
           - currentPrice (intraday)
           - preMarketPrice (pre-market)
           - postMarketPrice (after-hours)
        
        ✅ ALLOWED FIELD:
           - previousClose (last NYSE market close)
        """
        def _fetch_sync():
            try:
                ticker = yf.Ticker(symbol)
                info = ticker.info
                
                if not info:
                    return None
                
                # CRITICAL: Get previousClose ONLY
                previous_close = info.get("previousClose")
                
                if not previous_close:
                    # previousClose is MANDATORY - cannot proceed without it
                    logger.warning(f"[LAYER1 VIOLATION] {symbol}: No previousClose available, rejecting")
                    return None
                
                # VALIDATION: Ensure we're not accidentally using intraday prices
                # Log if regularMarketPrice differs significantly from previousClose
                # This is for debugging only - we NEVER use regularMarketPrice
                regular_price = info.get("regularMarketPrice")
                if regular_price and previous_close:
                    diff_pct = abs(regular_price - previous_close) / previous_close * 100
                    if diff_pct > 5:
                        logger.debug(f"[LAYER1] {symbol}: regularMarketPrice=${regular_price} differs {diff_pct:.1f}% from previousClose=${previous_close} - USING previousClose")
                
                # Get earnings date
                earnings_date = None
                try:
                    calendar = ticker.calendar
                    if calendar is not None and not calendar.empty:
                        if 'Earnings Date' in calendar.index:
                            earnings_dates = calendar.loc['Earnings Date']
                            if len(earnings_dates) > 0:
                                earnings_date = str(earnings_dates.iloc[0])[:10]
                except:
                    pass
                
                # Return ONLY previousClose as the price
                return {
                    "previous_close": previous_close,  # THE ONLY VALID PRICE
                    "volume": info.get("regularMarketVolume"),
                    "market_cap": info.get("marketCap"),
                    "avg_volume": info.get("averageVolume"),
                    "earnings_date": earnings_date,
                    "analyst_rating": info.get("recommendationKey")
                }
            except Exception as e:
                logger.debug(f"Yahoo stock fetch error for {symbol}: {e}")
                return None
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, _fetch_sync)
    
    async def _fetch_stock_polygon(self, symbol: str) -> Optional[Dict]:
        """Fetch stock data from Polygon as fallback."""
        if not self.polygon_api_key:
            return None
        
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                url = f"{POLYGON_BASE_URL}/v2/aggs/ticker/{symbol}/prev"
                response = await client.get(url, params={"apiKey": self.polygon_api_key})
                
                if response.status_code == 200:
                    data = response.json()
                    results = data.get("results", [])
                    if results:
                        r = results[0]
                        return {
                            "price": r.get("c"),  # Close price
                            "previous_close": r.get("c"),
                            "volume": r.get("v")
                        }
        except Exception as e:
            logger.debug(f"Polygon stock fetch error for {symbol}: {e}")
        
        return None
    
    async def _fetch_option_chain_yahoo(self, symbol: str, stock_price: float) -> Optional[Dict]:
        """
        Fetch complete option chain from Yahoo with BID/ASK data.
        
        CRITICAL: Stores bid and ask separately - never averages them!
        """
        def _fetch_sync():
            try:
                ticker = yf.Ticker(symbol)
                expiries = ticker.options
                
                if not expiries:
                    return None
                
                calls = []
                puts = []
                total_contracts = 0
                valid_contracts = 0
                rejection_reasons = []
                today = datetime.now()
                
                for exp_str in expiries:
                    try:
                        exp_date = datetime.strptime(exp_str, "%Y-%m-%d")
                        dte = (exp_date - today).days
                        
                        if dte < 1 or dte > 730:  # Skip expired or too far out
                            continue
                        
                        chain = ticker.option_chain(exp_str)
                        
                        # Process calls
                        for _, row in chain.calls.iterrows():
                            total_contracts += 1
                            contract = self._process_option_row(row, exp_str, dte, stock_price, "call")
                            
                            if contract.get("valid"):
                                calls.append(contract)
                                valid_contracts += 1
                            elif contract.get("rejection_reason"):
                                rejection_reasons.append(f"{symbol} {exp_str} ${row.get('strike')}C: {contract['rejection_reason']}")
                        
                        # Process puts
                        for _, row in chain.puts.iterrows():
                            total_contracts += 1
                            contract = self._process_option_row(row, exp_str, dte, stock_price, "put")
                            
                            if contract.get("valid"):
                                puts.append(contract)
                                valid_contracts += 1
                    
                    except Exception as e:
                        logger.debug(f"Error processing expiry {exp_str} for {symbol}: {e}")
                        continue
                
                return {
                    "expiries": list(expiries),
                    "calls": calls,
                    "puts": puts,
                    "total_contracts": total_contracts,
                    "valid_contracts": valid_contracts,
                    "rejection_reasons": rejection_reasons[:50]  # Limit stored reasons
                }
                
            except Exception as e:
                logger.error(f"Yahoo option chain error for {symbol}: {e}")
                return None
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, _fetch_sync)
    
    def _process_option_row(self, row, expiry: str, dte: int, stock_price: float, option_type: str) -> Dict:
        """
        Process a single option contract row.
        
        CRITICAL: Stores BID and ASK separately for enforcement in scan phase.
        Rejects contracts with missing/invalid BID.
        """
        strike = row.get('strike', 0)
        bid = row.get('bid', 0) if not (hasattr(row.get('bid'), '__iter__') and len(row.get('bid', [])) == 0) else 0
        ask = row.get('ask', 0) if not (hasattr(row.get('ask'), '__iter__') and len(row.get('ask', [])) == 0) else 0
        
        # Handle NaN values
        import math
        if bid and (isinstance(bid, float) and math.isnan(bid)):
            bid = 0
        if ask and (isinstance(ask, float) and math.isnan(ask)):
            ask = 0
        
        contract = {
            "contract_symbol": row.get('contractSymbol', ''),
            "strike": float(strike) if strike else 0,
            "expiry": expiry,
            "dte": dte,
            "option_type": option_type,
            "bid": float(bid) if bid else 0,
            "ask": float(ask) if ask else 0,
            "last_price": float(row.get('lastPrice', 0)) if row.get('lastPrice') else 0,
            "volume": int(row.get('volume', 0)) if row.get('volume') else 0,
            "open_interest": int(row.get('openInterest', 0)) if row.get('openInterest') else 0,
            "implied_volatility": float(row.get('impliedVolatility', 0)) if row.get('impliedVolatility') else 0,
            "valid": False,
            "rejection_reason": None
        }
        
        # VALIDATION: BID must exist and be > 0 for valid contract
        if contract["bid"] <= 0:
            contract["rejection_reason"] = "BID is zero or missing"
            return contract
        
        # VALIDATION: ASK must exist for BUY legs
        if contract["ask"] <= 0:
            contract["rejection_reason"] = "ASK is zero or missing"
            return contract
        
        # VALIDATION: Bid-Ask spread sanity check (reject if spread > 50%)
        if contract["ask"] > 0 and contract["bid"] > 0:
            spread_pct = (contract["ask"] - contract["bid"]) / contract["ask"] * 100
            if spread_pct > 50:
                contract["rejection_reason"] = f"Bid-Ask spread too wide: {spread_pct:.1f}%"
                return contract
        
        # VALIDATION: Strike must be reasonable (within 50% of stock price)
        if stock_price > 0:
            strike_pct = contract["strike"] / stock_price
            if strike_pct < 0.5 or strike_pct > 1.5:
                contract["rejection_reason"] = f"Strike {contract['strike']} outside valid range for ${stock_price:.2f} stock"
                return contract
        
        contract["valid"] = True
        return contract
    
    def _validate_chain_completeness(self, snapshot: Dict, stock_price: float) -> bool:
        """
        Validate that option chain is complete enough for scanning.
        
        Requirements:
        - At least one expiry exists
        - Calls exist
        - Strikes exist within ±20% of spot
        """
        if not snapshot.get("expiries"):
            return False
        
        calls = snapshot.get("calls", [])
        if not calls:
            return False
        
        # Check for strikes within ±20% of spot
        min_strike = stock_price * 0.8
        max_strike = stock_price * 1.2
        
        valid_strikes = [c for c in calls if min_strike <= c.get("strike", 0) <= max_strike]
        if len(valid_strikes) < 3:  # Need at least 3 strikes in range
            return False
        
        return True
    
    # ==================== PHASE 2: SNAPSHOT RETRIEVAL (READ-ONLY) ====================
    
    async def get_stock_snapshot(self, symbol: str) -> Tuple[Optional[Dict], Optional[str]]:
        """
        Get stored stock snapshot for scanning.
        
        Returns: (snapshot, error_message)
        - Returns snapshot if valid
        - Returns None with error if missing, incomplete, or stale
        
        SCAN MUST ABORT if this returns None!
        """
        snapshot = await self.db.stock_snapshots.find_one(
            {"symbol": symbol.upper()},
            {"_id": 0}
        )
        
        if not snapshot:
            return None, f"No snapshot exists for {symbol}"
        
        if not snapshot.get("completeness_flag"):
            return None, f"Snapshot incomplete for {symbol}"
        
        if snapshot.get("data_age_hours", 999) > MAX_DATA_AGE_HOURS:
            return None, f"Snapshot stale for {symbol}: {snapshot.get('data_age_hours')}h old (max {MAX_DATA_AGE_HOURS}h)"
        
        return snapshot, None
    
    async def get_option_chain_snapshot(self, symbol: str) -> Tuple[Optional[Dict], Optional[str]]:
        """
        Get stored option chain snapshot for scanning.
        
        Returns: (snapshot, error_message)
        - Returns snapshot if valid
        - Returns None with error if missing, incomplete, or stale
        
        SCAN MUST ABORT if this returns None!
        """
        snapshot = await self.db.option_chain_snapshots.find_one(
            {"symbol": symbol.upper()},
            {"_id": 0}
        )
        
        if not snapshot:
            return None, f"No option chain snapshot exists for {symbol}"
        
        if not snapshot.get("completeness_flag"):
            return None, f"Option chain incomplete for {symbol}: {snapshot.get('rejection_reasons', [])[:3]}"
        
        if snapshot.get("data_age_hours", 999) > MAX_DATA_AGE_HOURS:
            return None, f"Option chain stale for {symbol}: {snapshot.get('data_age_hours')}h old (max {MAX_DATA_AGE_HOURS}h)"
        
        return snapshot, None
    
    async def get_valid_calls_for_scan(
        self,
        symbol: str,
        min_dte: int = 7,
        max_dte: int = 45,
        min_strike_pct: float = 1.0,  # ATM
        max_strike_pct: float = 1.15,  # 15% OTM
        min_bid: float = 0.01
    ) -> Tuple[List[Dict], Optional[str]]:
        """
        Get valid call options for CC scanning from stored snapshot.
        
        CRITICAL: Returns BID price for SELL legs (Covered Call).
        
        Returns: (contracts, error_message)
        """
        snapshot, error = await self.get_option_chain_snapshot(symbol)
        if error:
            return [], error
        
        stock_price = snapshot.get("stock_price", 0)
        if stock_price <= 0:
            return [], f"Invalid stock price in snapshot for {symbol}"
        
        calls = snapshot.get("calls", [])
        valid_calls = []
        
        for call in calls:
            if not call.get("valid"):
                continue
            
            dte = call.get("dte", 0)
            if dte < min_dte or dte > max_dte:
                continue
            
            strike = call.get("strike", 0)
            strike_pct = strike / stock_price
            if strike_pct < min_strike_pct or strike_pct > max_strike_pct:
                continue
            
            bid = call.get("bid", 0)
            if bid < min_bid:
                continue
            
            # Return contract with BID as the premium (SELL leg)
            valid_calls.append({
                "contract_symbol": call.get("contract_symbol"),
                "strike": strike,
                "expiry": call.get("expiry"),
                "dte": dte,
                "premium": bid,  # BID ONLY for SELL
                "bid": bid,
                "ask": call.get("ask", 0),
                "volume": call.get("volume", 0),
                "open_interest": call.get("open_interest", 0),
                "implied_volatility": call.get("implied_volatility", 0),
                "stock_price": stock_price
            })
        
        return valid_calls, None
    
    async def get_valid_leaps_for_pmcc(
        self,
        symbol: str,
        min_dte: int = 365,
        max_dte: int = 730,
        min_delta: float = 0.70,
        max_spread_pct: float = 10.0,
        min_oi: int = 500
    ) -> Tuple[List[Dict], Optional[str]]:
        """
        Get valid LEAP options for PMCC scanning from stored snapshot.
        
        CRITICAL: Returns ASK price for BUY legs (PMCC LEAP).
        
        Returns: (contracts, error_message)
        """
        snapshot, error = await self.get_option_chain_snapshot(symbol)
        if error:
            return [], error
        
        stock_price = snapshot.get("stock_price", 0)
        if stock_price <= 0:
            return [], f"Invalid stock price in snapshot for {symbol}"
        
        calls = snapshot.get("calls", [])
        valid_leaps = []
        
        for call in calls:
            if not call.get("valid"):
                continue
            
            dte = call.get("dte", 0)
            if dte < min_dte or dte > max_dte:
                continue
            
            strike = call.get("strike", 0)
            bid = call.get("bid", 0)
            ask = call.get("ask", 0)
            oi = call.get("open_interest", 0)
            
            # LEAP must be ITM (strike < stock price)
            if strike >= stock_price:
                continue
            
            # Check OI requirement
            if oi < min_oi:
                continue
            
            # Check bid-ask spread
            if ask > 0 and bid > 0:
                spread_pct = (ask - bid) / ask * 100
                if spread_pct > max_spread_pct:
                    continue
            
            # Estimate delta for ITM call
            moneyness = (stock_price - strike) / stock_price
            est_delta = 0.50 + moneyness * 2
            est_delta = min(0.95, max(0.50, est_delta))
            
            if est_delta < min_delta:
                continue
            
            # Return contract with ASK as the premium (BUY leg)
            valid_leaps.append({
                "contract_symbol": call.get("contract_symbol"),
                "strike": strike,
                "expiry": call.get("expiry"),
                "dte": dte,
                "premium": ask,  # ASK ONLY for BUY
                "bid": bid,
                "ask": ask,
                "delta": round(est_delta, 3),
                "volume": call.get("volume", 0),
                "open_interest": oi,
                "implied_volatility": call.get("implied_volatility", 0),
                "stock_price": stock_price
            })
        
        return valid_leaps, None
    
    # ==================== BATCH INGESTION ====================
    
    async def ingest_symbols(self, symbols: List[str]) -> Dict[str, Any]:
        """
        Batch ingest stock and option chain snapshots for multiple symbols.
        
        This should be called:
        - After market close (4:45 PM ET)
        - Before running any scans
        """
        results = {
            "success": [],
            "failed": [],
            "total": len(symbols),
            "started_at": datetime.now(timezone.utc).isoformat()
        }
        
        for symbol in symbols:
            try:
                # Ingest stock first
                stock_snapshot = await self.ingest_stock_snapshot(symbol)
                
                if not stock_snapshot.get("completeness_flag"):
                    results["failed"].append({
                        "symbol": symbol,
                        "reason": stock_snapshot.get("error") or "Stock data incomplete"
                    })
                    continue
                
                # Ingest option chain
                chain_snapshot = await self.ingest_option_chain_snapshot(
                    symbol, 
                    stock_snapshot.get("price", 0)
                )
                
                if chain_snapshot.get("completeness_flag"):
                    results["success"].append({
                        "symbol": symbol,
                        "price": stock_snapshot.get("price"),
                        "valid_contracts": chain_snapshot.get("valid_contracts", 0)
                    })
                else:
                    results["failed"].append({
                        "symbol": symbol,
                        "reason": chain_snapshot.get("error") or "Option chain incomplete"
                    })
                
                # Rate limiting
                await asyncio.sleep(0.5)
                
            except Exception as e:
                results["failed"].append({
                    "symbol": symbol,
                    "reason": str(e)
                })
        
        results["completed_at"] = datetime.now(timezone.utc).isoformat()
        results["success_count"] = len(results["success"])
        results["failed_count"] = len(results["failed"])
        
        logger.info(f"Batch ingestion complete: {results['success_count']} success, {results['failed_count']} failed")
        
        return results
    
    # ==================== ADMIN UTILITIES ====================
    
    async def get_snapshot_status(self) -> Dict[str, Any]:
        """Get status of all snapshots for admin dashboard."""
        stock_count = await self.db.stock_snapshots.count_documents({})
        chain_count = await self.db.option_chain_snapshots.count_documents({})
        
        # Get stale snapshots
        stale_stocks = await self.db.stock_snapshots.count_documents({
            "data_age_hours": {"$gt": MAX_DATA_AGE_HOURS}
        })
        stale_chains = await self.db.option_chain_snapshots.count_documents({
            "data_age_hours": {"$gt": MAX_DATA_AGE_HOURS}
        })
        
        # Get incomplete snapshots
        incomplete_stocks = await self.db.stock_snapshots.count_documents({
            "completeness_flag": False
        })
        incomplete_chains = await self.db.option_chain_snapshots.count_documents({
            "completeness_flag": False
        })
        
        return {
            "stock_snapshots": {
                "total": stock_count,
                "stale": stale_stocks,
                "incomplete": incomplete_stocks,
                "valid": stock_count - stale_stocks - incomplete_stocks
            },
            "option_chain_snapshots": {
                "total": chain_count,
                "stale": stale_chains,
                "incomplete": incomplete_chains,
                "valid": chain_count - stale_chains - incomplete_chains
            },
            "max_data_age_hours": MAX_DATA_AGE_HOURS,
            "checked_at": datetime.now(timezone.utc).isoformat()
        }
    
    async def cleanup_old_snapshots(self, days: int = 30) -> Dict[str, int]:
        """Remove snapshots older than specified days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_str = cutoff.isoformat()
        
        stock_result = await self.db.stock_snapshots.delete_many({
            "snapshot_time": {"$lt": cutoff_str}
        })
        
        chain_result = await self.db.option_chain_snapshots.delete_many({
            "options_snapshot_time": {"$lt": cutoff_str}
        })
        
        return {
            "stock_snapshots_deleted": stock_result.deleted_count,
            "option_chain_snapshots_deleted": chain_result.deleted_count
        }
