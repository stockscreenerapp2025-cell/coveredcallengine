"""
EOD Ingestion Service - Market Close Price Contract Implementation
===================================================================

ADR-001 COMPLIANT

This service implements the canonical EOD Price Contract:
- Market close price captured at 04:05 PM ET
- Immutable per symbol+trade_date once `is_final: true`
- Idempotent ingestion (no-op if already final)
- Cross-validated stock/options dates

COLLECTIONS:
- eod_market_close: Canonical stock prices
- eod_options_chain: Canonical options data

FORBIDDEN IN THIS MODULE:
- regularMarketPrice
- currentPrice  
- Any live API fallback in snapshot context
"""

import logging
import asyncio
import uuid
from datetime import datetime, timezone, timedelta, time
from typing import Dict, List, Optional, Any, Tuple
from concurrent.futures import ThreadPoolExecutor
import pandas_market_calendars as mcal
import yfinance as yf
import pytz
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

# ==================== CONTRACT CONSTANTS ====================

# Canonical market close time (ET)
MARKET_CLOSE_HOUR = 16
MARKET_CLOSE_MINUTE = 5  # 04:05 PM ET - after close candle finalizes

# Maximum data age before rejection (hours)
MAX_DATA_AGE_HOURS = 48

# Timezone
ET_TIMEZONE = pytz.timezone('America/New_York')


class EODPriceNotFoundError(Exception):
    """Raised when canonical EOD price does not exist."""
    pass


class EODOptionsNotFoundError(Exception):
    """Raised when canonical EOD options chain does not exist."""
    pass


class EODDateMismatchError(Exception):
    """Raised when stock and options trade dates don't match."""
    pass


class EODAlreadyFinalError(Exception):
    """Raised when attempting to overwrite final EOD data without override flag."""
    pass


class EODIngestionService:
    """
    Service for ingesting and managing canonical EOD market close data.
    
    ADR-001 COMPLIANT:
    - Captures market close price at 04:05 PM ET
    - Immutable per symbol+trade_date once final
    - Idempotent ingestion
    - Cross-validates stock/options dates
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
        
        # Get schedule for last 10 days
        start = reference_date - timedelta(days=10)
        end = reference_date
        
        schedule = self._nyse_calendar.schedule(
            start_date=start.strftime('%Y-%m-%d'),
            end_date=end.strftime('%Y-%m-%d')
        )
        
        if schedule.empty:
            current = reference_date
            while current.weekday() >= 5:
                current -= timedelta(days=1)
            return current.replace(hour=16, minute=5, second=0, microsecond=0, tzinfo=ET_TIMEZONE)
        
        last_day = schedule.index[-1]
        return last_day.to_pydatetime().replace(
            hour=MARKET_CLOSE_HOUR, 
            minute=MARKET_CLOSE_MINUTE, 
            second=0, 
            microsecond=0,
            tzinfo=ET_TIMEZONE
        )
    
    def is_trading_day(self, date: datetime = None) -> bool:
        """Check if a given date is an NYSE trading day."""
        if date is None:
            date = datetime.now(timezone.utc)
        
        schedule = self._nyse_calendar.schedule(
            start_date=date.strftime('%Y-%m-%d'),
            end_date=date.strftime('%Y-%m-%d')
        )
        return not schedule.empty
    
    def get_canonical_close_timestamp(self, trade_date: str) -> str:
        """Get the canonical 04:05 PM ET timestamp for a trade date."""
        dt = datetime.strptime(trade_date, '%Y-%m-%d')
        et_dt = ET_TIMEZONE.localize(dt.replace(
            hour=MARKET_CLOSE_HOUR,
            minute=MARKET_CLOSE_MINUTE,
            second=0,
            microsecond=0
        ))
        return et_dt.isoformat()
    
    def generate_ingestion_run_id(self, trade_date: str) -> str:
        """Generate unique run ID for ingestion batch."""
        short_uuid = uuid.uuid4().hex[:8]
        return f"run_{trade_date.replace('-', '')}_{MARKET_CLOSE_HOUR:02d}{MARKET_CLOSE_MINUTE:02d}_{short_uuid}"
    
    # ==================== EOD STOCK PRICE INGESTION ====================
    
    async def ingest_eod_stock_price(
        self, 
        symbol: str, 
        trade_date: str = None,
        override: bool = False,
        run_id: str = None
    ) -> Dict[str, Any]:
        """
        Ingest canonical EOD stock price.
        
        ADR-001 COMPLIANT:
        - Uses yfinance.history() to get actual NYSE close for trade_date
        - Immutable once is_final: true
        - Idempotent (no-op if already final and override=false)
        
        Args:
            symbol: Stock ticker
            trade_date: Trading day (YYYY-MM-DD), defaults to LTD
            override: If True, allows overwriting final data (admin only)
            run_id: Ingestion run identifier
        
        Returns:
            Dict with ingestion result
        """
        now = datetime.now(timezone.utc)
        
        # Determine trade date
        if trade_date is None:
            ltd = self.get_last_trading_day(now)
            trade_date = ltd.strftime('%Y-%m-%d')
        
        # Generate run ID if not provided
        if run_id is None:
            run_id = self.generate_ingestion_run_id(trade_date)
        
        # Check if already final
        existing = await self.db.eod_market_close.find_one(
            {"symbol": symbol.upper(), "trade_date": trade_date},
            {"_id": 0}
        )
        
        if existing and existing.get("is_final"):
            if not override:
                logger.info(f"[EOD] {symbol} {trade_date}: Already final, skipping (no override)")
                return {
                    "symbol": symbol.upper(),
                    "trade_date": trade_date,
                    "status": "ALREADY_FINAL",
                    "market_close_price": existing.get("market_close_price"),
                    "message": "EOD data already finalized. Use override=true to re-ingest."
                }
            else:
                logger.warning(f"[EOD] {symbol} {trade_date}: Override requested, re-ingesting")
        
        # Build document
        doc = {
            "symbol": symbol.upper(),
            "trade_date": trade_date,
            "market_close_price": None,
            "market_close_timestamp": self.get_canonical_close_timestamp(trade_date),
            "source": None,
            "ingestion_run_id": run_id,
            "is_final": False,
            "created_at": now.isoformat(),
            "metadata": {
                "volume": None,
                "market_cap": None,
                "avg_volume": None,
                "earnings_date": None,
                "analyst_rating": None
            },
            "error": None
        }
        
        try:
            # Fetch EOD price using yfinance history
            data = await self._fetch_eod_price_yahoo(symbol, trade_date)
            
            if data and data.get("close_price"):
                doc.update({
                    "market_close_price": data["close_price"],
                    "source": "yahoo",
                    "is_final": True,
                    "metadata": {
                        "volume": data.get("volume"),
                        "market_cap": data.get("market_cap"),
                        "avg_volume": data.get("avg_volume"),
                        "earnings_date": data.get("earnings_date"),
                        "analyst_rating": data.get("analyst_rating")
                    }
                })
                
                logger.info(f"[EOD] {symbol} {trade_date}: Captured market_close_price=${data['close_price']:.2f}")
            else:
                doc["error"] = "Failed to fetch EOD price from Yahoo"
                logger.error(f"[EOD] {symbol} {trade_date}: Failed to fetch price")
        
        except Exception as e:
            doc["error"] = str(e)
            logger.error(f"[EOD] {symbol} {trade_date}: Error - {e}")
        
        # Upsert to database
        await self.db.eod_market_close.update_one(
            {"symbol": symbol.upper(), "trade_date": trade_date},
            {"$set": doc},
            upsert=True
        )
        
        return {
            "symbol": doc["symbol"],
            "trade_date": doc["trade_date"],
            "status": "INGESTED" if doc["is_final"] else "FAILED",
            "market_close_price": doc["market_close_price"],
            "market_close_timestamp": doc["market_close_timestamp"],
            "source": doc["source"],
            "is_final": doc["is_final"],
            "ingestion_run_id": run_id,
            "error": doc.get("error")
        }
    
    async def _fetch_eod_price_yahoo(self, symbol: str, trade_date: str) -> Optional[Dict]:
        """
        Fetch EOD price from Yahoo Finance history.
        
        ADR-001 COMPLIANT:
        ✅ Uses history() to get actual close for specific trade_date
        ❌ NEVER uses regularMarketPrice, currentPrice, previousClose from info
        """
        def _fetch_sync():
            try:
                ticker = yf.Ticker(symbol)
                
                # Fetch history around the trade date
                trade_dt = datetime.strptime(trade_date, '%Y-%m-%d')
                start_date = trade_dt - timedelta(days=5)
                end_date = trade_dt + timedelta(days=1)
                
                hist = ticker.history(
                    start=start_date.strftime('%Y-%m-%d'),
                    end=end_date.strftime('%Y-%m-%d')
                )
                
                if hist.empty:
                    logger.warning(f"[EOD] {symbol}: No history data for {trade_date}")
                    return None
                
                # Find the close price for the specific trade date
                close_price = None
                for idx in hist.index:
                    idx_date = idx.strftime('%Y-%m-%d')
                    if idx_date == trade_date:
                        close_price = float(hist.loc[idx, 'Close'])
                        break
                
                if close_price is None:
                    # Fallback: use the last available close before or on trade_date
                    hist_filtered = hist[hist.index.strftime('%Y-%m-%d') <= trade_date]
                    if not hist_filtered.empty:
                        close_price = float(hist_filtered['Close'].iloc[-1])
                        logger.info(f"[EOD] {symbol}: Using closest available close for {trade_date}")
                
                if close_price is None:
                    return None
                
                # Get metadata from info (but NOT the price)
                info = ticker.info or {}
                
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
                
                return {
                    "close_price": close_price,
                    "volume": info.get("regularMarketVolume"),
                    "market_cap": info.get("marketCap"),
                    "avg_volume": info.get("averageVolume"),
                    "earnings_date": earnings_date,
                    "analyst_rating": info.get("recommendationKey")
                }
                
            except Exception as e:
                logger.error(f"[EOD] Yahoo fetch error for {symbol}: {e}")
                return None
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, _fetch_sync)
    
    # ==================== EOD OPTIONS CHAIN INGESTION ====================
    
    async def ingest_eod_options_chain(
        self,
        symbol: str,
        stock_price: float,
        trade_date: str = None,
        override: bool = False,
        run_id: str = None
    ) -> Dict[str, Any]:
        """
        Ingest canonical EOD options chain.
        
        ADR-001 COMPLIANT:
        - Cross-validates trade_date with stock
        - Immutable once is_final: true
        - Stores BID and ASK separately (never averaged)
        
        Args:
            symbol: Stock ticker
            stock_price: Must be market_close_price from eod_market_close
            trade_date: Trading day (YYYY-MM-DD)
            override: If True, allows overwriting final data
            run_id: Ingestion run identifier
        """
        now = datetime.now(timezone.utc)
        
        if trade_date is None:
            ltd = self.get_last_trading_day(now)
            trade_date = ltd.strftime('%Y-%m-%d')
        
        if run_id is None:
            run_id = self.generate_ingestion_run_id(trade_date)
        
        # Check if already final
        existing = await self.db.eod_options_chain.find_one(
            {"symbol": symbol.upper(), "trade_date": trade_date},
            {"_id": 0, "calls": 0, "puts": 0}  # Exclude large arrays
        )
        
        if existing and existing.get("is_final"):
            if not override:
                logger.info(f"[EOD OPTIONS] {symbol} {trade_date}: Already final, skipping")
                return {
                    "symbol": symbol.upper(),
                    "trade_date": trade_date,
                    "status": "ALREADY_FINAL",
                    "valid_contracts": existing.get("valid_contracts", 0),
                    "message": "Options data already finalized."
                }
        
        # Verify stock EOD exists and matches
        stock_eod = await self.db.eod_market_close.find_one(
            {"symbol": symbol.upper(), "trade_date": trade_date, "is_final": True},
            {"_id": 0}
        )
        
        if not stock_eod:
            return {
                "symbol": symbol.upper(),
                "trade_date": trade_date,
                "status": "FAILED",
                "error": f"Stock EOD not found or not final for {trade_date}"
            }
        
        # Verify price matches
        if abs(stock_eod["market_close_price"] - stock_price) > 0.01:
            logger.warning(f"[EOD OPTIONS] {symbol}: Price mismatch - provided ${stock_price:.2f} vs EOD ${stock_eod['market_close_price']:.2f}")
        
        doc = {
            "symbol": symbol.upper(),
            "trade_date": trade_date,
            "stock_price": stock_eod["market_close_price"],  # Use canonical price
            "market_close_timestamp": self.get_canonical_close_timestamp(trade_date),
            "ingestion_run_id": run_id,
            "is_final": False,
            "created_at": now.isoformat(),
            "calls": [],
            "puts": [],
            "expiries": [],
            "total_contracts": 0,
            "valid_contracts": 0,
            "source": None,
            "error": None
        }
        
        try:
            chain_data = await self._fetch_options_chain_yahoo(symbol, stock_eod["market_close_price"])
            
            if chain_data:
                doc.update({
                    "source": "yahoo",
                    "expiries": chain_data.get("expiries", []),
                    "calls": chain_data.get("calls", []),
                    "puts": chain_data.get("puts", []),
                    "total_contracts": chain_data.get("total_contracts", 0),
                    "valid_contracts": chain_data.get("valid_contracts", 0),
                    "is_final": chain_data.get("valid_contracts", 0) >= 10  # Require min contracts
                })
                
                logger.info(f"[EOD OPTIONS] {symbol} {trade_date}: {doc['valid_contracts']} valid contracts")
            else:
                doc["error"] = "Failed to fetch options chain"
                
        except Exception as e:
            doc["error"] = str(e)
            logger.error(f"[EOD OPTIONS] {symbol} {trade_date}: Error - {e}")
        
        # Upsert
        await self.db.eod_options_chain.update_one(
            {"symbol": symbol.upper(), "trade_date": trade_date},
            {"$set": doc},
            upsert=True
        )
        
        return {
            "symbol": doc["symbol"],
            "trade_date": doc["trade_date"],
            "status": "INGESTED" if doc["is_final"] else "FAILED",
            "stock_price": doc["stock_price"],
            "valid_contracts": doc["valid_contracts"],
            "total_contracts": doc["total_contracts"],
            "expiries_count": len(doc["expiries"]),
            "is_final": doc["is_final"],
            "ingestion_run_id": run_id,
            "error": doc.get("error")
        }
    
    async def _fetch_options_chain_yahoo(self, symbol: str, stock_price: float) -> Optional[Dict]:
        """Fetch options chain from Yahoo Finance."""
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
                today = datetime.now()
                
                for exp_str in expiries:
                    try:
                        exp_date = datetime.strptime(exp_str, "%Y-%m-%d")
                        dte = (exp_date - today).days
                        
                        if dte < 1 or dte > 730:
                            continue
                        
                        chain = ticker.option_chain(exp_str)
                        
                        # Process calls
                        for _, row in chain.calls.iterrows():
                            total_contracts += 1
                            contract = self._process_option_row(row, exp_str, dte, stock_price, "call")
                            if contract.get("valid"):
                                calls.append(contract)
                                valid_contracts += 1
                        
                        # Process puts
                        for _, row in chain.puts.iterrows():
                            total_contracts += 1
                            contract = self._process_option_row(row, exp_str, dte, stock_price, "put")
                            if contract.get("valid"):
                                puts.append(contract)
                                valid_contracts += 1
                                
                    except Exception as e:
                        logger.debug(f"Error processing {exp_str} for {symbol}: {e}")
                        continue
                
                return {
                    "expiries": list(expiries),
                    "calls": calls,
                    "puts": puts,
                    "total_contracts": total_contracts,
                    "valid_contracts": valid_contracts
                }
                
            except Exception as e:
                logger.error(f"Yahoo options error for {symbol}: {e}")
                return None
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, _fetch_sync)
    
    def _process_option_row(self, row, expiry: str, dte: int, stock_price: float, option_type: str) -> Dict:
        """Process a single option row."""
        import math
        
        strike = row.get('strike', 0)
        bid = row.get('bid', 0) if row.get('bid') is not None else 0
        ask = row.get('ask', 0) if row.get('ask') is not None else 0
        
        # Handle NaN
        if isinstance(bid, float) and math.isnan(bid):
            bid = 0
        if isinstance(ask, float) and math.isnan(ask):
            ask = 0
        
        volume = row.get('volume', 0) if row.get('volume') else 0
        open_interest = row.get('openInterest', 0) if row.get('openInterest') else 0
        implied_volatility = row.get('impliedVolatility', 0) if row.get('impliedVolatility') else 0
        
        if isinstance(volume, float) and math.isnan(volume):
            volume = 0
        if isinstance(open_interest, float) and math.isnan(open_interest):
            open_interest = 0
        if isinstance(implied_volatility, float) and math.isnan(implied_volatility):
            implied_volatility = 0
        
        contract = {
            "contract_symbol": row.get('contractSymbol', ''),
            "strike": float(strike) if strike else 0,
            "expiry": expiry,
            "dte": dte,
            "option_type": option_type,
            "bid": float(bid) if bid else 0,
            "ask": float(ask) if ask else 0,
            "volume": int(volume),
            "open_interest": int(open_interest),
            "implied_volatility": float(implied_volatility),
            "delta": 0.0,
            "valid": False
        }
        
        # Estimate delta
        if stock_price > 0 and strike > 0:
            if option_type == "call":
                moneyness = (stock_price - strike) / stock_price
                if moneyness > 0:
                    contract["delta"] = min(0.95, 0.50 + moneyness * 2)
                else:
                    contract["delta"] = max(0.05, 0.50 + moneyness * 2)
            else:
                moneyness = (strike - stock_price) / stock_price
                if moneyness > 0:
                    contract["delta"] = max(-0.95, -0.50 - moneyness * 2)
                else:
                    contract["delta"] = min(-0.05, -0.50 - moneyness * 2)
            contract["delta"] = round(contract["delta"], 4)
        
        # Validation
        if contract["bid"] <= 0:
            return contract
        if contract["ask"] <= 0:
            return contract
        
        # Spread check
        if contract["ask"] > 0 and contract["bid"] > 0:
            spread_pct = (contract["ask"] - contract["bid"]) / contract["ask"] * 100
            if spread_pct > 50:
                return contract
        
        # Strike range check
        if stock_price > 0:
            strike_pct = contract["strike"] / stock_price
            if strike_pct < 0.5 or strike_pct > 1.5:
                return contract
        
        contract["valid"] = True
        return contract
    
    # ==================== BATCH INGESTION ====================
    
    async def ingest_all_eod(
        self, 
        symbols: List[str], 
        trade_date: str = None,
        override: bool = False
    ) -> Dict[str, Any]:
        """
        Batch ingest EOD data for multiple symbols.
        
        ADR-001 COMPLIANT:
        - Single ingestion_run_id for the batch
        - Stock ingested before options
        - Cross-validates all dates
        """
        now = datetime.now(timezone.utc)
        
        if trade_date is None:
            ltd = self.get_last_trading_day(now)
            trade_date = ltd.strftime('%Y-%m-%d')
        
        run_id = self.generate_ingestion_run_id(trade_date)
        
        results = {
            "trade_date": trade_date,
            "ingestion_run_id": run_id,
            "started_at": now.isoformat(),
            "total_symbols": len(symbols),
            "stock_success": [],
            "stock_failed": [],
            "stock_skipped": [],
            "options_success": [],
            "options_failed": [],
            "options_skipped": []
        }
        
        for symbol in symbols:
            # Ingest stock first
            stock_result = await self.ingest_eod_stock_price(
                symbol, trade_date, override, run_id
            )
            
            if stock_result["status"] == "ALREADY_FINAL":
                results["stock_skipped"].append(symbol)
            elif stock_result["status"] == "INGESTED":
                results["stock_success"].append(symbol)
            else:
                results["stock_failed"].append({
                    "symbol": symbol,
                    "error": stock_result.get("error")
                })
                continue  # Skip options if stock failed
            
            # Ingest options
            stock_price = stock_result.get("market_close_price", 0)
            if stock_price > 0:
                options_result = await self.ingest_eod_options_chain(
                    symbol, stock_price, trade_date, override, run_id
                )
                
                if options_result["status"] == "ALREADY_FINAL":
                    results["options_skipped"].append(symbol)
                elif options_result["status"] == "INGESTED":
                    results["options_success"].append(symbol)
                else:
                    results["options_failed"].append({
                        "symbol": symbol,
                        "error": options_result.get("error")
                    })
            
            # Rate limiting
            await asyncio.sleep(0.3)
        
        results["completed_at"] = datetime.now(timezone.utc).isoformat()
        results["summary"] = {
            "stock_ingested": len(results["stock_success"]),
            "stock_skipped": len(results["stock_skipped"]),
            "stock_failed": len(results["stock_failed"]),
            "options_ingested": len(results["options_success"]),
            "options_skipped": len(results["options_skipped"]),
            "options_failed": len(results["options_failed"])
        }
        
        logger.info(f"[EOD BATCH] {trade_date}: {results['summary']}")
        
        return results


class EODPriceContract:
    """
    Service boundary that enforces the EOD Price Contract.
    
    ADR-001 COMPLIANT:
    All snapshot-based modules MUST use this interface.
    Direct database access is PROHIBITED.
    """
    
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
    
    async def get_market_close_price(
        self, 
        symbol: str, 
        trade_date: str = None
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Get canonical market close price.
        
        Args:
            symbol: Stock ticker
            trade_date: Trading day (YYYY-MM-DD), defaults to most recent
        
        Returns:
            Tuple of (price, full_document)
        
        Raises:
            EODPriceNotFoundError: If no canonical price exists
        """
        if trade_date is None:
            # Get most recent final EOD
            doc = await self.db.eod_market_close.find_one(
                {"symbol": symbol.upper(), "is_final": True},
                {"_id": 0},
                sort=[("trade_date", -1)]
            )
        else:
            doc = await self.db.eod_market_close.find_one(
                {"symbol": symbol.upper(), "trade_date": trade_date, "is_final": True},
                {"_id": 0}
            )
        
        if not doc:
            raise EODPriceNotFoundError(
                f"No canonical EOD price for {symbol}" + 
                (f" on {trade_date}" if trade_date else "")
            )
        
        return doc["market_close_price"], doc
    
    async def get_options_chain(
        self, 
        symbol: str, 
        trade_date: str = None
    ) -> Dict[str, Any]:
        """
        Get canonical options chain.
        
        Args:
            symbol: Stock ticker
            trade_date: Trading day (YYYY-MM-DD)
        
        Returns:
            Full options chain document
        
        Raises:
            EODOptionsNotFoundError: If no canonical chain exists
        """
        if trade_date is None:
            doc = await self.db.eod_options_chain.find_one(
                {"symbol": symbol.upper(), "is_final": True},
                {"_id": 0},
                sort=[("trade_date", -1)]
            )
        else:
            doc = await self.db.eod_options_chain.find_one(
                {"symbol": symbol.upper(), "trade_date": trade_date, "is_final": True},
                {"_id": 0}
            )
        
        if not doc:
            raise EODOptionsNotFoundError(
                f"No canonical options chain for {symbol}" +
                (f" on {trade_date}" if trade_date else "")
            )
        
        return doc
    
    async def get_valid_calls_for_scan(
        self,
        symbol: str,
        trade_date: str = None,
        min_dte: int = 7,
        max_dte: int = 45,
        min_strike_pct: float = 1.0,
        max_strike_pct: float = 1.15,
        min_bid: float = 0.01
    ) -> List[Dict]:
        """
        Get valid call options for CC scanning.
        
        Returns BID price as premium (SELL leg).
        """
        chain = await self.get_options_chain(symbol, trade_date)
        stock_price = chain["stock_price"]
        calls = chain.get("calls", [])
        
        valid_calls = []
        for call in calls:
            if not call.get("valid"):
                continue
            
            dte = call.get("dte", 0)
            if dte < min_dte or dte > max_dte:
                continue
            
            strike = call.get("strike", 0)
            strike_pct = strike / stock_price if stock_price > 0 else 0
            if strike_pct < min_strike_pct or strike_pct > max_strike_pct:
                continue
            
            bid = call.get("bid", 0)
            if bid < min_bid:
                continue
            
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
                "delta": call.get("delta", 0),
                "stock_price": stock_price
            })
        
        return valid_calls
    
    async def get_valid_leaps_for_pmcc(
        self,
        symbol: str,
        trade_date: str = None,
        min_dte: int = 365,
        max_dte: int = 730,
        min_delta: float = 0.70,
        min_oi: int = 500
    ) -> List[Dict]:
        """
        Get valid LEAP options for PMCC scanning.
        
        Returns ASK price as premium (BUY leg).
        """
        chain = await self.get_options_chain(symbol, trade_date)
        stock_price = chain["stock_price"]
        calls = chain.get("calls", [])
        
        valid_leaps = []
        for call in calls:
            if not call.get("valid"):
                continue
            
            dte = call.get("dte", 0)
            if dte < min_dte or dte > max_dte:
                continue
            
            strike = call.get("strike", 0)
            if strike >= stock_price:  # LEAP must be ITM
                continue
            
            oi = call.get("open_interest", 0)
            if oi < min_oi:
                continue
            
            delta = call.get("delta", 0)
            if delta < min_delta:
                continue
            
            ask = call.get("ask", 0)
            if ask <= 0:
                continue
            
            valid_leaps.append({
                "contract_symbol": call.get("contract_symbol"),
                "strike": strike,
                "expiry": call.get("expiry"),
                "dte": dte,
                "premium": ask,  # ASK ONLY for BUY
                "bid": call.get("bid", 0),
                "ask": ask,
                "delta": delta,
                "volume": call.get("volume", 0),
                "open_interest": oi,
                "implied_volatility": call.get("implied_volatility", 0),
                "stock_price": stock_price
            })
        
        return valid_leaps
    
    async def get_eod_status(self, trade_date: str = None) -> Dict[str, Any]:
        """Get status of EOD data for admin dashboard."""
        query = {"is_final": True}
        if trade_date:
            query["trade_date"] = trade_date
        
        stock_count = await self.db.eod_market_close.count_documents(query)
        options_count = await self.db.eod_options_chain.count_documents(query)
        
        # Get latest trade date
        latest = await self.db.eod_market_close.find_one(
            {"is_final": True},
            {"_id": 0, "trade_date": 1},
            sort=[("trade_date", -1)]
        )
        
        return {
            "stock_records": stock_count,
            "options_records": options_count,
            "latest_trade_date": latest.get("trade_date") if latest else None,
            "query_trade_date": trade_date
        }
