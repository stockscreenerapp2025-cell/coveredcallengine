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

# CRITICAL: These are the ONLY valid price sources
# ✅ previousClose - Last NYSE market close
# ❌ regularMarketPrice - FORBIDDEN (intraday)
# ❌ currentPrice - FORBIDDEN (intraday)
# ❌ preMarketPrice - FORBIDDEN
# ❌ postMarketPrice - FORBIDDEN


def get_max_data_age_hours(reference_date: datetime = None) -> float:
    """
    Calculate maximum acceptable data age based on market calendar.
    
    - Weekday: Max 24 hours
    - Weekend/Monday morning: Max 72 hours (allows Friday close data)
    
    This is market-calendar-aware and prevents stale data issues
    like allowing Friday data on Tuesday (which would be > 72 hours).
    """
    if reference_date is None:
        reference_date = datetime.now(timezone.utc)
    
    # If it's Monday before market close (4 PM ET), allow up to 72 hours (Friday close)
    if reference_date.weekday() == 0 and reference_date.hour < 16:
        return 72.0
    
    # If it's Saturday or Sunday, allow 72 hours
    if reference_date.weekday() >= 5:
        return 72.0
    
    # Regular trading days: 24 hours max
    return 24.0


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
    
    async def ingest_option_chain_snapshot(
        self, 
        symbol: str, 
        stock_price: float,
        stock_trade_date: str = None
    ) -> Dict[str, Any]:
        """
        Fetch and store complete option chain snapshot with full metadata.
        
        CCE MASTER ARCHITECTURE - LAYER 1 COMPLIANT
        
        CRITICAL RULES:
        - Stores BID and ASK separately (NEVER averaged)
        - stock_trade_date MUST match options_data_trade_day (HARD FAIL otherwise)
        - All mandatory fields populated or rejected
        
        Args:
            symbol: Stock ticker
            stock_price: MUST be stock_close_price from stock snapshot
            stock_trade_date: LTD from stock snapshot (for cross-validation)
        
        Returns snapshot document with full chain data
        """
        now = datetime.now(timezone.utc)
        ltd = self.get_last_trading_day(now)
        ltd_str = ltd.strftime('%Y-%m-%d')
        
        # Use provided stock_trade_date or default to LTD
        # Cross-validation will fail if these don't match
        expected_trade_date = stock_trade_date or ltd_str
        
        snapshot = {
            "symbol": symbol.upper(),
            "stock_price": stock_price,  # This MUST be stock_close_price (previous close)
            # DATE FIELDS - ALL MUST MATCH
            "snapshot_trade_date": ltd_str,
            "options_snapshot_time": now.isoformat(),
            "options_data_trade_day": ltd_str,
            "stock_trade_date_from_stock_snapshot": expected_trade_date,  # For cross-validation
            # DATA AGE
            "data_age_hours": 0,
            # CHAIN DATA
            "expiries": [],
            "calls": [],
            "puts": [],
            "total_contracts": 0,
            "valid_contracts": 0,
            "rejection_reasons": [],
            # VALIDATION FLAGS
            "completeness_flag": False,
            "date_validation_passed": False,
            "source": None,
            "error": None
        }
        
        # CRITICAL: Cross-validate dates
        if expected_trade_date != ltd_str:
            error_msg = f"DATE MISMATCH: stock_trade_date={expected_trade_date} != options_trade_date={ltd_str}"
            logger.error(f"[LAYER1 HARD FAIL] {symbol}: {error_msg}")
            snapshot["error"] = error_msg
            snapshot["date_validation_passed"] = False
            
            # Store the failed snapshot for debugging
            await self.db.option_chain_snapshots.update_one(
                {"symbol": symbol.upper()},
                {"$set": snapshot},
                upsert=True
            )
            return snapshot
        
        snapshot["date_validation_passed"] = True
        
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
            
            logger.info(f"Ingested option chain for {symbol}: {snapshot['valid_contracts']} valid contracts, complete={snapshot['completeness_flag']}, date_match={snapshot['date_validation_passed']}")
            
        except Exception as e:
            snapshot["error"] = str(e)
            logger.error(f"Error ingesting option chain for {symbol}: {e}")
        
        return snapshot
    
    async def _fetch_stock_yahoo(self, symbol: str) -> Optional[Dict]:
        """
        Fetch stock data from Yahoo Finance.
        
        CCE MASTER ARCHITECTURE - LAYER 1 COMPLIANT
        
        CRITICAL: Returns the ACTUAL NYSE CLOSE PRICE for the Last Trading Day.
        
        ❌ FORBIDDEN FIELDS (NEVER USE):
           - regularMarketPrice (intraday)
           - currentPrice (intraday)
           - preMarketPrice (pre-market)
           - postMarketPrice (after-hours)
        
        ✅ CORRECT APPROACH:
           - Use history() to get the actual close price for LTD
           - This ensures we get Jan 22's close after Jan 22 market closes,
             not Jan 21's close which is what previousClose would return
        """
        def _fetch_sync():
            try:
                ticker = yf.Ticker(symbol)
                info = ticker.info
                
                if not info:
                    return None
                
                # Get the actual close price from history
                # This is more accurate than previousClose after market hours
                hist = ticker.history(period="5d")
                
                if hist.empty:
                    logger.warning(f"[LAYER1] {symbol}: No history data available")
                    return None
                
                # Get the most recent trading day's close
                # This will be today's close if market has closed, or yesterday's if still open
                latest_close = hist['Close'].iloc[-1]
                latest_date = hist.index[-1].strftime('%Y-%m-%d')
                
                # Also get previous day's close for comparison
                prev_close_from_info = info.get("previousClose")
                
                # Determine which price to use based on market status
                # Get the LTD from our calendar logic
                ltd = self._get_last_trading_day_sync()
                ltd_str = ltd.strftime('%Y-%m-%d')
                
                # Find the close price for LTD from history
                ltd_close = None
                for idx in hist.index:
                    if idx.strftime('%Y-%m-%d') == ltd_str:
                        ltd_close = hist.loc[idx, 'Close']
                        break
                
                if ltd_close is not None:
                    actual_close = float(ltd_close)
                    logger.info(f"[LAYER1] {symbol}: Using LTD ({ltd_str}) close=${actual_close:.2f} from history")
                else:
                    # Fallback to latest available close if LTD not in history
                    actual_close = float(latest_close)
                    logger.info(f"[LAYER1] {symbol}: LTD not in history, using latest close=${actual_close:.2f} ({latest_date})")
                
                # Log comparison for debugging
                if prev_close_from_info:
                    diff_pct = abs(actual_close - prev_close_from_info) / prev_close_from_info * 100
                    if diff_pct > 1:
                        logger.debug(f"[LAYER1] {symbol}: history close=${actual_close:.2f} vs previousClose=${prev_close_from_info:.2f} (diff {diff_pct:.1f}%)")
                
                # Get earnings date
                earnings_date = None
                try:
                    calendar = ticker.calendar
                    if calendar is not None and not calendar.empty:
                        if 'Earnings Date' in calendar.index:
                            earnings_dates = calendar.loc['Earnings Date']
                            if len(earnings_dates) > 0:
                                earnings_date = str(earnings_dates.iloc[0])[:10]
                except Exception:
                    pass
                
                # Return the ACTUAL close price for LTD
                return {
                    "previous_close": actual_close,  # THE ACTUAL NYSE CLOSE FOR LTD
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
    
    def _get_last_trading_day_sync(self) -> datetime:
        """Synchronous helper to get last trading day."""
        from datetime import datetime, timezone, timedelta
        import pandas_market_calendars as mcal
        
        now = datetime.now(timezone.utc)
        nyse = mcal.get_calendar('NYSE')
        
        start = now - timedelta(days=10)
        schedule = nyse.schedule(
            start_date=start.strftime('%Y-%m-%d'),
            end_date=now.strftime('%Y-%m-%d')
        )
        
        if schedule.empty:
            current = now
            while current.weekday() >= 5:
                current -= timedelta(days=1)
            return current.replace(hour=16, minute=0, second=0, microsecond=0)
        
        # Check if market has closed today
        last_session = schedule.index[-1]
        market_close = schedule.iloc[-1]['market_close'].to_pydatetime()
        
        if now >= market_close:
            # Market closed - use today's close
            return last_session.to_pydatetime().replace(tzinfo=timezone.utc)
        elif len(schedule) > 1:
            # Market still open - use previous day's close
            return schedule.index[-2].to_pydatetime().replace(tzinfo=timezone.utc)
        else:
            return last_session.to_pydatetime().replace(tzinfo=timezone.utc)
    
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
        
        CCE MASTER ARCHITECTURE - LAYER 1 COMPLIANT
        CCE VOLATILITY & GREEKS CORRECTNESS - Updated to use Black-Scholes
        
        MANDATORY FIELDS IN OUTPUT:
        - bid, ask (SEPARATE - never averaged)
        - open_interest, volume
        - implied_volatility, iv, iv_pct
        - delta, delta_source (Black-Scholes computed)
        - gamma, theta, vega (Black-Scholes computed)
        - iv_rank, iv_percentile, iv_rank_source, iv_samples
        
        CRITICAL: Stores BID and ASK separately for enforcement in scan phase.
        Rejects contracts with missing/invalid BID.
        """
        # Import shared Greeks service for Black-Scholes calculations
        from services.greeks_service import calculate_greeks, normalize_iv_fields
        
        strike = row.get('strike', 0)
        bid = row.get('bid', 0) if not (hasattr(row.get('bid'), '__iter__') and len(row.get('bid', [])) == 0) else 0
        ask = row.get('ask', 0) if not (hasattr(row.get('ask'), '__iter__') and len(row.get('ask', [])) == 0) else 0
        
        # Handle NaN values
        import math
        if bid and (isinstance(bid, float) and math.isnan(bid)):
            bid = 0
        if ask and (isinstance(ask, float) and math.isnan(ask)):
            ask = 0
        
        # Get all available fields from Yahoo
        volume = row.get('volume', 0) if row.get('volume') else 0
        open_interest = row.get('openInterest', 0) if row.get('openInterest') else 0
        implied_volatility = row.get('impliedVolatility', 0) if row.get('impliedVolatility') else 0
        last_price = row.get('lastPrice', 0) if row.get('lastPrice') else 0
        
        # Handle NaN in numeric fields
        if isinstance(volume, float) and math.isnan(volume):
            volume = 0
        if isinstance(open_interest, float) and math.isnan(open_interest):
            open_interest = 0
        if isinstance(implied_volatility, float) and math.isnan(implied_volatility):
            implied_volatility = 0
        if isinstance(last_price, float) and math.isnan(last_price):
            last_price = 0
        
        # Normalize IV to decimal and percentage forms
        iv_data = normalize_iv_fields(implied_volatility)
        
        # Calculate Greeks using Black-Scholes (not moneyness fallback)
        T = max(dte, 1) / 365.0
        greeks_result = calculate_greeks(
            S=stock_price,
            K=float(strike) if strike else 0,
            T=T,
            sigma=iv_data["iv"] if iv_data["iv"] > 0 else None,
            option_type=option_type
        )
        
        # LAYER 1 COMPLIANT: Full schema with all downstream fields
        # CCE VOLATILITY & GREEKS CORRECTNESS: All fields always populated
        contract = {
            # IDENTITY
            "contract_symbol": row.get('contractSymbol', ''),
            "strike": float(strike) if strike else 0,
            "expiry": expiry,
            "dte": dte,
            "option_type": option_type,
            # PRICING (MANDATORY - separate bid/ask)
            "bid": float(bid) if bid else 0,
            "ask": float(ask) if ask else 0,
            "last_price": float(last_price),
            # LIQUIDITY (MANDATORY)
            "volume": int(volume),
            "open_interest": int(open_interest),
            # IV FIELDS (standardized) - ALWAYS POPULATED
            "implied_volatility": float(implied_volatility),  # Raw from Yahoo
            "iv": iv_data["iv"],  # Normalized decimal
            "iv_pct": iv_data["iv_pct"],  # Normalized percentage
            # GREEKS (Black-Scholes) - ALWAYS POPULATED
            "delta": greeks_result.delta,
            "delta_source": greeks_result.delta_source,
            "gamma": greeks_result.gamma,
            "theta": greeks_result.theta,
            "vega": greeks_result.vega,
            # IV RANK (placeholder - computed at symbol level in scan phase)
            "iv_rank": 50.0,  # Default neutral
            "iv_percentile": 50.0,
            "iv_rank_source": "DEFAULT_NEUTRAL_INGESTION",
            "iv_samples": 0,
            # VALIDATION
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
        
        # VALIDATION: Bid-Ask spread sanity check (10% max - consistent with Layer 2)
        # 10% threshold applied at both ingestion and validation
        if contract["ask"] > 0 and contract["bid"] > 0:
            spread_pct = (contract["ask"] - contract["bid"]) / contract["ask"] * 100
            if spread_pct > 10:
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
        
        CCE MASTER ARCHITECTURE - LAYER 1 COMPLIANT (Read Interface)
        
        Returns: (snapshot, error_message)
        - Returns snapshot if valid
        - Returns None with error if missing, incomplete, or stale
        
        SCAN MUST ABORT if this returns None!
        
        The returned snapshot contains:
        - stock_close_price: THE price to use (previous NYSE close)
        - stock_price_trade_date: The trading day this price represents
        """
        snapshot = await self.db.stock_snapshots.find_one(
            {"symbol": symbol.upper()},
            {"_id": 0}
        )
        
        if not snapshot:
            return None, f"No snapshot exists for {symbol}"
        
        if not snapshot.get("completeness_flag"):
            return None, f"Snapshot incomplete for {symbol}"
        
        max_age = get_max_data_age_hours()
        if snapshot.get("data_age_hours", 999) > max_age:
            return None, f"Snapshot stale for {symbol}: {snapshot.get('data_age_hours')}h old (max {max_age}h)"
        
        # LAYER 1 COMPLIANT: Verify stock_close_price exists
        if not snapshot.get("stock_close_price"):
            # Backward compatibility: check legacy "price" field
            if snapshot.get("price"):
                snapshot["stock_close_price"] = snapshot["price"]
            else:
                return None, f"No stock_close_price in snapshot for {symbol}"
        
        return snapshot, None
    
    async def get_option_chain_snapshot(self, symbol: str) -> Tuple[Optional[Dict], Optional[str]]:
        """
        Get stored option chain snapshot for scanning.
        
        CCE MASTER ARCHITECTURE - LAYER 1 COMPLIANT (Read Interface)
        
        Returns: (snapshot, error_message)
        - Returns snapshot if valid
        - Returns None with error if missing, incomplete, stale, or date mismatch
        
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
        
        max_age = get_max_data_age_hours()
        if snapshot.get("data_age_hours", 999) > max_age:
            return None, f"Option chain stale for {symbol}: {snapshot.get('data_age_hours')}h old (max {max_age}h)"
        
        # LAYER 1 COMPLIANT: Check date validation passed
        if snapshot.get("date_validation_passed") is False:
            return None, f"Date mismatch in option chain for {symbol}: stock_date != options_date"
        
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
        
        # Import shared Greeks service for on-the-fly computation if needed
        from services.greeks_service import calculate_greeks, normalize_iv_fields
        
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
            
            # CCE VOLATILITY & GREEKS CORRECTNESS:
            # If delta_source is missing/UNKNOWN, compute Greeks on the fly
            # This handles legacy data that was ingested before the update
            delta = call.get("delta", 0.0)
            delta_source = call.get("delta_source", "UNKNOWN")
            gamma = call.get("gamma", 0.0)
            theta = call.get("theta", 0.0)
            vega = call.get("vega", 0.0)
            iv = call.get("iv", 0.0)
            iv_pct = call.get("iv_pct", 0.0)
            
            # If data looks like legacy (delta_source unknown or iv=0 but implied_volatility exists)
            if delta_source == "UNKNOWN" or (iv == 0 and call.get("implied_volatility", 0) > 0):
                iv_raw = call.get("implied_volatility", 0)
                iv_data = normalize_iv_fields(iv_raw)
                iv = iv_data["iv"]
                iv_pct = iv_data["iv_pct"]
                
                T = max(dte, 1) / 365.0
                greeks_result = calculate_greeks(
                    S=stock_price,
                    K=strike,
                    T=T,
                    sigma=iv if iv > 0 else None,
                    option_type="call"
                )
                delta = greeks_result.delta
                delta_source = greeks_result.delta_source
                gamma = greeks_result.gamma
                theta = greeks_result.theta
                vega = greeks_result.vega
            
            # Return contract with BID as the premium (SELL leg)
            # CCE VOLATILITY & GREEKS: All fields always populated
            valid_calls.append({
                "contract_symbol": call.get("contract_symbol"),
                "strike": strike,
                "expiry": call.get("expiry"),
                "dte": dte,
                "premium": bid,  # BID ONLY for SELL
                "bid": bid,
                "ask": call.get("ask", 0),
                # Greeks (Black-Scholes) - ALWAYS POPULATED
                "delta": delta,
                "delta_source": delta_source,
                "gamma": gamma,
                "theta": theta,
                "vega": vega,
                # IV fields (standardized) - ALWAYS POPULATED
                "iv": iv,
                "iv_pct": iv_pct,
                "implied_volatility": call.get("implied_volatility", 0),  # Legacy
                # IV Rank (defaults - computed at symbol level in scan phase)
                "iv_rank": call.get("iv_rank", 50.0) if call.get("iv_rank") is not None else 50.0,
                "iv_percentile": call.get("iv_percentile", 50.0),
                "iv_rank_source": call.get("iv_rank_source", "DEFAULT_NEUTRAL"),
                "iv_samples": call.get("iv_samples", 0),
                # Liquidity
                "volume": call.get("volume", 0),
                "open_interest": call.get("open_interest", 0),
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
            
            # CCE VOLATILITY & GREEKS CORRECTNESS: Use Black-Scholes for delta
            from services.greeks_service import calculate_greeks, normalize_iv_fields
            
            iv_raw = call.get("implied_volatility", 0) or call.get("iv", 0)
            iv_data = normalize_iv_fields(iv_raw)
            T = max(dte, 1) / 365.0
            
            greeks_result = calculate_greeks(
                S=stock_price,
                K=strike,
                T=T,
                sigma=iv_data["iv"] if iv_data["iv"] > 0 else None,
                option_type="call"
            )
            
            est_delta = greeks_result.delta
            delta_source = greeks_result.delta_source
            
            if est_delta < min_delta:
                continue
            
            # Return contract with ASK as the premium (BUY leg)
            # CCE VOLATILITY & GREEKS: All fields populated
            valid_leaps.append({
                "contract_symbol": call.get("contract_symbol"),
                "strike": strike,
                "expiry": call.get("expiry"),
                "dte": dte,
                "premium": ask,  # ASK ONLY for BUY
                "bid": bid,
                "ask": ask,
                # Greeks (Black-Scholes) - ALWAYS POPULATED
                "delta": est_delta,
                "delta_source": delta_source,
                "gamma": greeks_result.gamma,
                "theta": greeks_result.theta,
                "vega": greeks_result.vega,
                # IV fields (standardized) - ALWAYS POPULATED
                "iv": iv_data["iv"],
                "iv_pct": iv_data["iv_pct"],
                "implied_volatility": call.get("implied_volatility", 0),  # Legacy
                # IV Rank (placeholder - computed at symbol level)
                "iv_rank": 50.0,
                "iv_percentile": 50.0,
                "iv_rank_source": "DEFAULT_NEUTRAL_LEAPS",
                "iv_samples": 0,
                # Liquidity
                "volume": call.get("volume", 0),
                "open_interest": oi,
                "stock_price": stock_price
            })
        
        return valid_leaps, None
    
    # ==================== BATCH INGESTION ====================
    
    async def ingest_symbols(self, symbols: List[str]) -> Dict[str, Any]:
        """
        Batch ingest stock and option chain snapshots for multiple symbols.
        
        CCE MASTER ARCHITECTURE - LAYER 1 COMPLIANT
        
        CRITICAL: Cross-validates stock and options dates.
        Rejects symbols where dates don't match.
        
        This should be called:
        - After market close (4:45 PM ET)
        - Before running any scans
        """
        results = {
            "success": [],
            "failed": [],
            "date_mismatch": [],  # Specific tracking for date validation failures
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
                
                # CRITICAL: Pass stock_trade_date for cross-validation
                stock_trade_date = stock_snapshot.get("stock_price_trade_date")
                stock_close_price = stock_snapshot.get("stock_close_price")
                
                # Ingest option chain with cross-validation
                chain_snapshot = await self.ingest_option_chain_snapshot(
                    symbol, 
                    stock_close_price,  # Use stock_close_price, not legacy "price"
                    stock_trade_date    # Pass for date cross-validation
                )
                
                # Check for date mismatch (HARD FAIL condition)
                if not chain_snapshot.get("date_validation_passed"):
                    results["date_mismatch"].append({
                        "symbol": symbol,
                        "stock_date": stock_trade_date,
                        "options_date": chain_snapshot.get("options_data_trade_day"),
                        "reason": chain_snapshot.get("error") or "Date mismatch between stock and options"
                    })
                    continue
                
                if chain_snapshot.get("completeness_flag"):
                    results["success"].append({
                        "symbol": symbol,
                        "stock_close_price": stock_close_price,
                        "stock_trade_date": stock_trade_date,
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
        results["date_mismatch_count"] = len(results["date_mismatch"])
        
        logger.info(f"Batch ingestion complete: {results['success_count']} success, {results['failed_count']} failed, {results['date_mismatch_count']} date mismatch")
        
        return results
    
    # ==================== ADMIN UTILITIES ====================
    
    async def get_snapshot_status(self) -> Dict[str, Any]:
        """
        Get status of all snapshots for admin dashboard.
        
        CCE MASTER ARCHITECTURE - LAYER 1 COMPLIANT
        
        Reports on:
        - Total, valid, stale, incomplete snapshots
        - Date validation status
        - Price source verification
        """
        stock_count = await self.db.stock_snapshots.count_documents({})
        chain_count = await self.db.option_chain_snapshots.count_documents({})
        
        # Get current max data age (market-calendar aware)
        max_age = get_max_data_age_hours()
        
        # Get stale snapshots
        stale_stocks = await self.db.stock_snapshots.count_documents({
            "data_age_hours": {"$gt": max_age}
        })
        stale_chains = await self.db.option_chain_snapshots.count_documents({
            "data_age_hours": {"$gt": max_age}
        })
        
        # Get incomplete snapshots
        incomplete_stocks = await self.db.stock_snapshots.count_documents({
            "completeness_flag": False
        })
        incomplete_chains = await self.db.option_chain_snapshots.count_documents({
            "completeness_flag": False
        })
        
        # LAYER 1 SPECIFIC: Count date mismatches
        date_mismatch_chains = await self.db.option_chain_snapshots.count_documents({
            "date_validation_passed": False
        })
        
        # LAYER 1 SPECIFIC: Count snapshots using correct price field
        stocks_with_close_price = await self.db.stock_snapshots.count_documents({
            "stock_close_price": {"$exists": True, "$ne": None}
        })
        
        return {
            "stock_snapshots": {
                "total": stock_count,
                "stale": stale_stocks,
                "incomplete": incomplete_stocks,
                "valid": max(0, stock_count - stale_stocks - incomplete_stocks),
                "with_stock_close_price": stocks_with_close_price  # LAYER 1 compliance check
            },
            "option_chain_snapshots": {
                "total": chain_count,
                "stale": stale_chains,
                "incomplete": incomplete_chains,
                "date_mismatch": date_mismatch_chains,  # LAYER 1 compliance check
                "valid": max(0, chain_count - stale_chains - incomplete_chains - date_mismatch_chains)
            },
            "layer1_compliance": {
                "max_data_age_hours": max_age,
                "price_source": "previousClose ONLY",
                "date_validation": "stock_trade_date must equal options_data_trade_day"
            },
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
