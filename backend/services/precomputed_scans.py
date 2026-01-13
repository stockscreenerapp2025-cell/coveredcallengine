"""
Pre-Computed Scans Service
==========================
Handles nightly computation of covered call and PMCC scan results.

SCAN TYPES:
- Conservative (Low Risk): Stable stocks, low IV, high probability
- Balanced (Moderate Risk): Growth stocks, moderate IV, good income
- Aggressive (High Premium): Momentum stocks, high IV, maximum yield

DATA SOURCES:
- Technical (SMA, RSI, ATR): Polygon Historical API (rate-limited: 5/min for stocks)
- Fundamental (EPS, ROE, D/E): Yahoo Finance (free)
- Options: Polygon API (unlimited)
- Earnings Dates: Yahoo Finance (free)

ARCHITECTURE:
- Nightly job runs at 4:45 PM ET (after market close)
- Results stored in MongoDB `precomputed_scans` collection
- User clicks → instant fetch from DB
"""

import asyncio
import logging
import aiohttp
import httpx
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, Tuple
import yfinance as yf
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor

# Configure logging
logger = logging.getLogger(__name__)

# Constants
POLYGON_BASE_URL = "https://api.polygon.io"
HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# Rate limiting for stock API (5 calls/min)
STOCK_API_RATE_LIMIT = 5
STOCK_API_RATE_WINDOW = 60  # seconds

# Risk profile configurations
RISK_PROFILES = {
    "conservative": {
        "label": "Income Guard",
        "description": "Stable stocks with low volatility and high probability of profit",
        # Technical filters
        "trend_sma50_above_sma200": True,
        "price_above_sma50": True,
        "rsi_min": 40,
        "rsi_max": 60,
        "atr_pct_max": 0.03,  # ATR <= 3%
        "no_recent_gap": True,
        "gap_threshold": 0.03,  # No 3%+ gaps in 10 days
        # Fundamental filters
        "market_cap_min": 10_000_000_000,  # $10B
        "eps_positive": True,
        "revenue_growth_min": 0.05,  # 5% YoY
        "debt_to_equity_max": 0.6,
        "roe_min": 0.12,  # 12%
        # Options filters
        "iv_percentile_min": 20,
        "iv_percentile_max": 40,
        "delta_min": 0.20,
        "delta_max": 0.30,
        "dte_min": 25,
        "dte_max": 45,
        "premium_yield_min": 0.007,  # 0.7%
        # Earnings filter
        "earnings_days_away_min": 21,
    },
    "balanced": {
        "label": "Steady Income",
        "description": "Slightly bullish stocks with moderate volatility",
        # Technical filters
        "trend_sma50_above_sma200": False,  # Just price > SMA50
        "price_above_sma50": True,
        "rsi_min": 45,
        "rsi_max": 65,
        "atr_pct_max": 0.05,  # ATR <= 5%
        "no_recent_gap": False,
        "volume_above_avg": True,
        # Fundamental filters
        "market_cap_min": 3_000_000_000,  # $3B
        "eps_positive": False,  # Positive OR improving
        "revenue_growth_min": 0.08,  # 8% YoY
        "debt_to_equity_max": 1.0,
        "roe_min": 0,
        # Options filters
        "iv_percentile_min": 30,
        "iv_percentile_max": 55,
        "delta_min": 0.30,
        "delta_max": 0.40,
        "dte_min": 20,
        "dte_max": 40,
        "premium_yield_min": 0.01,  # 1%
        # Earnings filter
        "earnings_days_away_min": 14,
    },
    "aggressive": {
        "label": "Premium Hunter",
        "description": "Strong momentum with premium maximization",
        # Technical filters
        "trend_sma50_above_sma200": False,
        "price_above_sma20": True,  # Faster trend
        "rsi_min": 50,
        "rsi_max": 75,
        "atr_pct_min": 0.04,  # ATR >= 4%
        "volume_expansion": True,
        # Fundamental filters
        "market_cap_min": 1_000_000_000,  # $1B
        "eps_positive": False,
        "revenue_growth_min": 0.10,  # 10% YoY
        "debt_to_equity_max": None,  # No limit
        "roe_min": 0,
        # Options filters
        "iv_percentile_min": 55,
        "iv_percentile_max": 85,
        "delta_min": 0.40,
        "delta_max": 0.55,
        "dte_min": 14,
        "dte_max": 30,
        "premium_yield_min": 0.015,  # 1.5%
        # Earnings filter
        "earnings_days_away_min": 5,
    }
}

# PMCC-specific configurations
PMCC_PROFILES = {
    "conservative": {
        "label": "Capital Efficient Income",
        "long_dte_min": 180,
        "long_delta_min": 0.70,
        "long_delta_max": 0.80,
        "long_itm_pct": 0.10,  # ITM >= 10%
        "short_delta_min": 0.20,
        "short_delta_max": 0.30,
        "short_dte_min": 25,
        "short_dte_max": 45,
    },
    "balanced": {
        "label": "Leveraged Income",
        "long_dte_min": 120,
        "long_dte_max": 240,
        "long_delta_min": 0.65,
        "long_delta_max": 0.75,
        "short_delta_min": 0.30,
        "short_delta_max": 0.40,
        "short_dte_min": 20,
        "short_dte_max": 40,
    },
    "aggressive": {
        "label": "Max Yield Diagonal",
        "long_dte_min": 365,  # 12-24 months
        "long_dte_max": 730,
        "long_delta_min": 0.55,
        "long_delta_max": 0.65,
        "short_delta_min": 0.40,
        "short_delta_max": 0.55,
        "short_dte_min": 14,
        "short_dte_max": 30,
    }
}


class PrecomputedScanService:
    """Service for computing and storing pre-computed scan results."""
    
    def __init__(self, db, api_key: str = None):
        self.db = db
        self.api_key = api_key
        self._rate_limit_semaphore = asyncio.Semaphore(STOCK_API_RATE_LIMIT)
        self._last_stock_calls = []
        self._executor = ThreadPoolExecutor(max_workers=10)
    
    async def _rate_limited_stock_call(self, coro):
        """Execute a stock API call with rate limiting (5/min)."""
        async with self._rate_limit_semaphore:
            now = datetime.now()
            # Clean old timestamps
            self._last_stock_calls = [t for t in self._last_stock_calls 
                                       if (now - t).total_seconds() < STOCK_API_RATE_WINDOW]
            
            # Wait if we've hit the limit
            if len(self._last_stock_calls) >= STOCK_API_RATE_LIMIT:
                oldest = min(self._last_stock_calls)
                wait_time = STOCK_API_RATE_WINDOW - (now - oldest).total_seconds()
                if wait_time > 0:
                    logger.debug(f"Rate limiting: waiting {wait_time:.1f}s")
                    await asyncio.sleep(wait_time + 0.1)
            
            self._last_stock_calls.append(datetime.now())
            return await coro
    
    # ==================== SYMBOL UNIVERSE ====================
    
    async def get_liquid_symbols(self) -> List[str]:
        """
        Get liquidity-filtered symbol universe.
        Applies filters: 2M+ avg volume, $10-500 price range.
        Returns ~150-250 most liquid symbols.
        """
        # Start with a broad universe of liquid stocks
        # This list is curated for options liquidity
        base_universe = [
            # Mega-cap Tech
            "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA",
            # Large-cap Tech
            "AMD", "INTC", "MU", "QCOM", "AVGO", "TXN", "ADI", "MCHP", "AMAT", "LRCX",
            "CRM", "ORCL", "ADBE", "NOW", "SNOW", "NET", "PLTR", "DDOG", "ZS", "CRWD",
            "IBM", "HPQ", "DELL", "CSCO", "PANW", "FTNT",
            # Financials
            "JPM", "BAC", "WFC", "C", "GS", "MS", "USB", "PNC", "TFC", "COF",
            "AXP", "V", "MA", "PYPL", "SQ", "SOFI", "HOOD",
            # Consumer
            "WMT", "COST", "HD", "LOW", "TGT", "AMZN", "DIS", "NFLX", "CMCSA",
            "NKE", "SBUX", "MCD", "KO", "PEP", "PG", "KHC",
            # Healthcare
            "UNH", "JNJ", "PFE", "MRK", "ABBV", "LLY", "BMY", "GILD", "AMGN",
            "CVS", "CI", "HUM", "MRNA", "BNTX",
            # Energy
            "XOM", "CVX", "OXY", "DVN", "APA", "HAL", "SLB", "MRO", "COP", "EOG",
            # Industrials
            "CAT", "DE", "GE", "HON", "BA", "RTX", "LMT", "NOC",
            "UPS", "FDX", "UAL", "DAL", "AAL", "LUV",
            # Materials & Utilities
            "FCX", "NEM", "X",
            # Travel & Leisure
            "CCL", "RCL", "NCLH", "MAR", "HLT", "ABNB",
            # Telecom
            "T", "VZ", "TMUS",
            # High Volatility / Meme
            "GME", "AMC", "RIVN", "LCID", "NIO", "XPEV",
            # ETFs (most liquid)
            "SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK", "XLV", "XLI",
            "GLD", "SLV", "USO", "TLT", "HYG",
            # REITs
            "O", "AMT", "PLD", "EQIX",
        ]
        
        # Remove duplicates and sort
        return sorted(list(set(base_universe)))
    
    # ==================== TECHNICAL DATA ====================
    
    async def fetch_technical_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Fetch technical indicators for a symbol using Yahoo Finance.
        Returns SMA50, SMA200, RSI14, ATR14, volume data.
        """
        try:
            def _fetch_yahoo():
                ticker = yf.Ticker(symbol)
                # Get 200 days of history for SMA200
                hist = ticker.history(period="1y")
                if hist.empty or len(hist) < 50:
                    return None
                
                # Calculate SMAs
                hist['SMA20'] = hist['Close'].rolling(window=20).mean()
                hist['SMA50'] = hist['Close'].rolling(window=50).mean()
                hist['SMA200'] = hist['Close'].rolling(window=200).mean()
                
                # Calculate RSI (14-period)
                delta = hist['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                hist['RSI14'] = 100 - (100 / (1 + rs))
                
                # Calculate ATR (14-period)
                high_low = hist['High'] - hist['Low']
                high_close = (hist['High'] - hist['Close'].shift()).abs()
                low_close = (hist['Low'] - hist['Close'].shift()).abs()
                tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
                hist['ATR14'] = tr.rolling(window=14).mean()
                
                # Calculate daily change % for gap detection
                hist['daily_change_pct'] = hist['Close'].pct_change().abs()
                
                # Get latest values
                latest = hist.iloc[-1]
                close = latest['Close']
                
                # Calculate 20-day average volume
                avg_volume_20d = hist['Volume'].tail(20).mean()
                
                # Check for gaps in last 10 days
                max_gap_10d = hist['daily_change_pct'].tail(10).max()
                
                return {
                    "symbol": symbol,
                    "close": float(close),
                    "sma20": float(latest['SMA20']) if pd.notna(latest['SMA20']) else None,
                    "sma50": float(latest['SMA50']) if pd.notna(latest['SMA50']) else None,
                    "sma200": float(latest['SMA200']) if pd.notna(latest['SMA200']) else None,
                    "rsi14": float(latest['RSI14']) if pd.notna(latest['RSI14']) else None,
                    "atr14": float(latest['ATR14']) if pd.notna(latest['ATR14']) else None,
                    "atr_pct": float(latest['ATR14'] / close) if pd.notna(latest['ATR14']) and close > 0 else None,
                    "volume": int(latest['Volume']),
                    "avg_volume_20d": float(avg_volume_20d),
                    "max_gap_10d": float(max_gap_10d) if pd.notna(max_gap_10d) else 0,
                    "volume_above_avg": latest['Volume'] > avg_volume_20d,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(self._executor, _fetch_yahoo)
            
        except Exception as e:
            logger.warning(f"Failed to fetch technical data for {symbol}: {e}")
            return None
    
    # ==================== FUNDAMENTAL DATA ====================
    
    async def fetch_fundamental_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Fetch fundamental data from Yahoo Finance.
        Returns market cap, EPS, P/E, ROE, D/E, revenue growth.
        """
        try:
            def _fetch_fundamentals():
                ticker = yf.Ticker(symbol)
                info = ticker.info
                
                if not info:
                    return None
                
                # Extract fundamental metrics
                market_cap = info.get('marketCap', 0) or 0
                eps_ttm = info.get('trailingEps', 0) or 0
                pe_ratio = info.get('trailingPE', 0) or 0
                forward_pe = info.get('forwardPE', 0) or 0
                
                # ROE - try multiple fields
                roe = info.get('returnOnEquity', 0) or 0
                
                # Debt to Equity
                debt_to_equity = info.get('debtToEquity', 0) or 0
                if debt_to_equity:
                    debt_to_equity = debt_to_equity / 100  # Convert from percentage
                
                # Revenue Growth
                revenue_growth = info.get('revenueGrowth', 0) or 0
                
                # Earnings Growth
                earnings_growth = info.get('earningsGrowth', 0) or 0
                
                # Next earnings date
                earnings_date = None
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
                except Exception:
                    pass
                
                # Calculate days to earnings
                days_to_earnings = None
                if earnings_date:
                    try:
                        earnings_dt = datetime.strptime(earnings_date, "%Y-%m-%d")
                        days_to_earnings = (earnings_dt - datetime.now()).days
                    except Exception:
                        pass
                
                return {
                    "symbol": symbol,
                    "market_cap": market_cap,
                    "eps_ttm": eps_ttm,
                    "pe_ratio": pe_ratio,
                    "forward_pe": forward_pe,
                    "roe": roe,
                    "debt_to_equity": debt_to_equity,
                    "revenue_growth": revenue_growth,
                    "earnings_growth": earnings_growth,
                    "earnings_date": earnings_date,
                    "days_to_earnings": days_to_earnings,
                    "sector": info.get('sector', ''),
                    "industry": info.get('industry', ''),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(self._executor, _fetch_fundamentals)
            
        except Exception as e:
            logger.warning(f"Failed to fetch fundamental data for {symbol}: {e}")
            return None
    
    # ==================== OPTIONS DATA ====================
    
    async def fetch_options_for_scan(
        self, 
        symbol: str, 
        current_price: float,
        dte_min: int,
        dte_max: int,
        delta_min: float,
        delta_max: float
    ) -> List[Dict[str, Any]]:
        """
        Fetch and filter options contracts from Polygon.
        No rate limiting needed - unlimited API calls.
        """
        if not self.api_key:
            return []
        
        try:
            today = datetime.now()
            min_expiry = (today + timedelta(days=dte_min)).strftime("%Y-%m-%d")
            max_expiry = (today + timedelta(days=dte_max)).strftime("%Y-%m-%d")
            
            # Calculate strike range based on delta targets
            # Lower delta = further OTM = higher strike
            # Delta 0.20-0.30 (conservative) ≈ 3-8% OTM
            # Delta 0.30-0.40 (balanced) ≈ 0-5% OTM
            # Delta 0.40-0.55 (aggressive) ≈ ATM to 3% OTM
            
            if delta_max <= 0.30:  # Conservative - OTM
                strike_min = current_price * 1.02
                strike_max = current_price * 1.15
            elif delta_max <= 0.40:  # Balanced - slightly OTM
                strike_min = current_price * 0.98
                strike_max = current_price * 1.08
            else:  # Aggressive - ATM
                strike_min = current_price * 0.95
                strike_max = current_price * 1.05
            
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                # Fetch contracts
                contracts_url = f"{POLYGON_BASE_URL}/v3/reference/options/contracts"
                params = {
                    "underlying_ticker": symbol.upper(),
                    "contract_type": "call",
                    "expiration_date.gte": min_expiry,
                    "expiration_date.lte": max_expiry,
                    "strike_price.gte": strike_min,
                    "strike_price.lte": strike_max,
                    "limit": 100,
                    "apiKey": self.api_key
                }
                
                response = await client.get(contracts_url, params=params)
                if response.status_code != 200:
                    logger.warning(f"Polygon contracts API error for {symbol}: {response.status_code}")
                    return []
                
                data = response.json()
                contracts = data.get("results", [])
                
                if not contracts:
                    return []
                
                # Fetch prices for each contract in parallel
                semaphore = asyncio.Semaphore(20)  # Unlimited, but control concurrency
                
                async def fetch_price(contract):
                    async with semaphore:
                        ticker = contract.get("ticker", "")
                        if not ticker:
                            return None
                        
                        try:
                            price_resp = await client.get(
                                f"{POLYGON_BASE_URL}/v2/aggs/ticker/{ticker}/prev",
                                params={"apiKey": self.api_key}
                            )
                            
                            if price_resp.status_code == 200:
                                price_data = price_resp.json()
                                results = price_data.get("results", [])
                                
                                if results:
                                    r = results[0]
                                    strike = contract.get("strike_price", 0)
                                    expiry = contract.get("expiration_date", "")
                                    
                                    # Calculate DTE
                                    dte = 0
                                    if expiry:
                                        try:
                                            exp_dt = datetime.strptime(expiry, "%Y-%m-%d")
                                            dte = (exp_dt - datetime.now()).days
                                        except Exception:
                                            pass
                                    
                                    # Estimate delta based on moneyness
                                    moneyness = (strike - current_price) / current_price
                                    if moneyness <= 0:  # ITM
                                        est_delta = 0.55 + abs(moneyness) * 0.5
                                    else:  # OTM
                                        est_delta = 0.50 - moneyness * 3
                                    est_delta = max(0.10, min(0.90, est_delta))
                                    
                                    # Filter by delta
                                    if est_delta < delta_min or est_delta > delta_max:
                                        return None
                                    
                                    close_price = r.get("c", 0)
                                    if close_price <= 0:
                                        return None
                                    
                                    premium_yield = close_price / current_price
                                    
                                    return {
                                        "contract_ticker": ticker,
                                        "symbol": symbol,
                                        "strike": strike,
                                        "expiry": expiry,
                                        "dte": dte,
                                        "premium": close_price,
                                        "premium_yield": premium_yield,
                                        "delta": round(est_delta, 3),
                                        "volume": r.get("v", 0),
                                        "open_interest": 0,  # Would need separate call
                                        "iv": 0.30,  # Would need Greeks API
                                        "vwap": r.get("vw", 0)
                                    }
                        except Exception as e:
                            logger.debug(f"Error fetching price for {ticker}: {e}")
                        return None
                
                # Fetch all prices in parallel
                tasks = [fetch_price(c) for c in contracts[:50]]  # Limit to 50 contracts
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Filter out None results
                options = [r for r in results if r and not isinstance(r, Exception)]
                
                return options
                
        except Exception as e:
            logger.error(f"Error fetching options for {symbol}: {e}")
            return []
    
    # ==================== FILTER LOGIC ====================
    
    def passes_technical_filters(self, tech_data: Dict, profile: Dict) -> Tuple[bool, str]:
        """Check if symbol passes technical filters for given risk profile."""
        if not tech_data:
            return False, "No technical data"
        
        close = tech_data.get("close", 0)
        sma20 = tech_data.get("sma20")
        sma50 = tech_data.get("sma50")
        sma200 = tech_data.get("sma200")
        rsi = tech_data.get("rsi14")
        atr_pct = tech_data.get("atr_pct")
        max_gap = tech_data.get("max_gap_10d", 0)
        
        # Price must be in tradeable range
        if close < 10 or close > 500:
            return False, f"Price ${close:.2f} outside $10-$500 range"
        
        # SMA alignment check
        if profile.get("trend_sma50_above_sma200"):
            if sma50 and sma200 and sma50 <= sma200:
                return False, "SMA50 not above SMA200"
        
        if profile.get("price_above_sma50"):
            if sma50 and close <= sma50:
                return False, f"Price ${close:.2f} below SMA50 ${sma50:.2f}"
        
        if profile.get("price_above_sma20"):
            if sma20 and close <= sma20:
                return False, f"Price ${close:.2f} below SMA20 ${sma20:.2f}"
        
        # RSI filter
        rsi_min = profile.get("rsi_min", 0)
        rsi_max = profile.get("rsi_max", 100)
        if rsi and (rsi < rsi_min or rsi > rsi_max):
            return False, f"RSI {rsi:.1f} outside {rsi_min}-{rsi_max}"
        
        # ATR filter
        atr_max = profile.get("atr_pct_max")
        atr_min = profile.get("atr_pct_min")
        if atr_max and atr_pct and atr_pct > atr_max:
            return False, f"ATR% {atr_pct*100:.1f}% above {atr_max*100}%"
        if atr_min and atr_pct and atr_pct < atr_min:
            return False, f"ATR% {atr_pct*100:.1f}% below {atr_min*100}%"
        
        # Gap filter
        if profile.get("no_recent_gap"):
            gap_threshold = profile.get("gap_threshold", 0.03)
            if max_gap > gap_threshold:
                return False, f"Recent gap {max_gap*100:.1f}% exceeds {gap_threshold*100}%"
        
        return True, "Passed"
    
    def passes_fundamental_filters(self, fund_data: Dict, profile: Dict) -> Tuple[bool, str]:
        """Check if symbol passes fundamental filters."""
        if not fund_data:
            return False, "No fundamental data"
        
        market_cap = fund_data.get("market_cap", 0)
        eps = fund_data.get("eps_ttm", 0)
        roe = fund_data.get("roe", 0)
        de_ratio = fund_data.get("debt_to_equity", 0)
        rev_growth = fund_data.get("revenue_growth", 0)
        days_to_earnings = fund_data.get("days_to_earnings")
        
        # Market cap filter
        min_cap = profile.get("market_cap_min", 0)
        if market_cap < min_cap:
            return False, f"Market cap ${market_cap/1e9:.1f}B below ${min_cap/1e9}B"
        
        # EPS filter
        if profile.get("eps_positive") and eps <= 0:
            return False, f"EPS ${eps:.2f} not positive"
        
        # ROE filter
        min_roe = profile.get("roe_min", 0)
        if roe < min_roe:
            return False, f"ROE {roe*100:.1f}% below {min_roe*100}%"
        
        # Debt to Equity filter
        max_de = profile.get("debt_to_equity_max")
        if max_de is not None and de_ratio > max_de:
            return False, f"D/E {de_ratio:.2f} above {max_de}"
        
        # Revenue growth filter
        min_rev = profile.get("revenue_growth_min", 0)
        if rev_growth < min_rev:
            return False, f"Revenue growth {rev_growth*100:.1f}% below {min_rev*100}%"
        
        # Earnings date filter
        min_days = profile.get("earnings_days_away_min", 0)
        if days_to_earnings is not None and days_to_earnings < min_days:
            return False, f"Earnings in {days_to_earnings} days (min {min_days})"
        
        return True, "Passed"
    
    # ==================== MAIN SCAN LOGIC ====================
    
    async def run_covered_call_scan(
        self, 
        risk_profile: str = "conservative"
    ) -> List[Dict[str, Any]]:
        """
        Run a covered call scan for the given risk profile.
        Returns ranked list of opportunities.
        """
        profile = RISK_PROFILES.get(risk_profile, RISK_PROFILES["conservative"])
        logger.info(f"Starting {risk_profile} covered call scan...")
        
        # Get symbol universe
        symbols = await self.get_liquid_symbols()
        logger.info(f"Scanning {len(symbols)} symbols for {risk_profile} profile")
        
        opportunities = []
        stats = {
            "total_symbols": len(symbols),
            "passed_technical": 0,
            "passed_fundamental": 0,
            "passed_options": 0,
            "failed_technical": [],
            "failed_fundamental": [],
            "failed_options": []
        }
        
        # Process symbols in batches to manage memory
        batch_size = 20
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            
            # Fetch technical and fundamental data in parallel
            tech_tasks = [self.fetch_technical_data(s) for s in batch]
            fund_tasks = [self.fetch_fundamental_data(s) for s in batch]
            
            tech_results = await asyncio.gather(*tech_tasks, return_exceptions=True)
            fund_results = await asyncio.gather(*fund_tasks, return_exceptions=True)
            
            for j, symbol in enumerate(batch):
                tech_data = tech_results[j] if not isinstance(tech_results[j], Exception) else None
                fund_data = fund_results[j] if not isinstance(fund_results[j], Exception) else None
                
                # Apply technical filters
                tech_pass, tech_reason = self.passes_technical_filters(tech_data, profile)
                if not tech_pass:
                    stats["failed_technical"].append((symbol, tech_reason))
                    continue
                stats["passed_technical"] += 1
                
                # Apply fundamental filters
                fund_pass, fund_reason = self.passes_fundamental_filters(fund_data, profile)
                if not fund_pass:
                    stats["failed_fundamental"].append((symbol, fund_reason))
                    continue
                stats["passed_fundamental"] += 1
                
                # Fetch options for survivors only
                current_price = tech_data.get("close", 0)
                options = await self.fetch_options_for_scan(
                    symbol,
                    current_price,
                    profile["dte_min"],
                    profile["dte_max"],
                    profile["delta_min"],
                    profile["delta_max"]
                )
                
                if not options:
                    stats["failed_options"].append((symbol, "No matching options"))
                    continue
                
                stats["passed_options"] += 1
                
                # Filter by premium yield
                min_yield = profile.get("premium_yield_min", 0)
                qualified_options = [o for o in options if o.get("premium_yield", 0) >= min_yield]
                
                if not qualified_options:
                    continue
                
                # Score and rank options
                for opt in qualified_options:
                    # Calculate composite score
                    roi_score = min(opt["premium_yield"] * 100 * 15, 40)
                    delta_score = 20 - abs(opt["delta"] - 0.30) * 50
                    dte_score = 10 - abs(opt["dte"] - 30) * 0.3
                    
                    # Fundamental bonus
                    fund_score = 0
                    if fund_data.get("roe", 0) > 0.15:
                        fund_score += 5
                    if fund_data.get("revenue_growth", 0) > 0.10:
                        fund_score += 5
                    
                    total_score = max(0, roi_score + delta_score + dte_score + fund_score)
                    
                    opportunities.append({
                        "symbol": symbol,
                        "stock_price": round(current_price, 2),
                        "strike": opt["strike"],
                        "expiry": opt["expiry"],
                        "dte": opt["dte"],
                        "premium": round(opt["premium"], 2),
                        "premium_yield": round(opt["premium_yield"] * 100, 2),
                        "roi_pct": round(opt["premium_yield"] * 100, 2),
                        "delta": opt["delta"],
                        "volume": opt.get("volume", 0),
                        "score": round(total_score, 1),
                        "risk_profile": risk_profile,
                        "strategy": "covered_call",
                        # Include technical indicators
                        "sma50": tech_data.get("sma50"),
                        "sma200": tech_data.get("sma200"),
                        "rsi14": tech_data.get("rsi14"),
                        "atr_pct": round(tech_data.get("atr_pct", 0) * 100, 2) if tech_data.get("atr_pct") else None,
                        # Include fundamental data
                        "market_cap": fund_data.get("market_cap", 0),
                        "eps_ttm": fund_data.get("eps_ttm", 0),
                        "roe": round(fund_data.get("roe", 0) * 100, 1) if fund_data.get("roe") else None,
                        "debt_to_equity": fund_data.get("debt_to_equity"),
                        "days_to_earnings": fund_data.get("days_to_earnings"),
                        "sector": fund_data.get("sector", ""),
                    })
            
            # Small delay between batches
            await asyncio.sleep(0.5)
        
        # Sort by score and limit
        opportunities.sort(key=lambda x: x["score"], reverse=True)
        opportunities = opportunities[:50]  # Top 50
        
        logger.info(f"Scan complete: {len(opportunities)} opportunities found")
        logger.info(f"Stats: {stats['passed_technical']} passed tech, "
                   f"{stats['passed_fundamental']} passed fund, "
                   f"{stats['passed_options']} had options")
        
        return opportunities
    
    # ==================== STORAGE ====================
    
    async def store_scan_results(
        self, 
        strategy: str,
        risk_profile: str, 
        opportunities: List[Dict]
    ) -> bool:
        """Store pre-computed scan results in MongoDB."""
        try:
            now = datetime.now(timezone.utc)
            scan_doc = {
                "strategy": strategy,  # "covered_call" or "pmcc"
                "risk_profile": risk_profile,
                "opportunities": opportunities,
                "count": len(opportunities),
                "computed_at": now.isoformat(),
                "computed_date": now.strftime("%Y-%m-%d"),
                "label": RISK_PROFILES.get(risk_profile, {}).get("label", risk_profile.title()),
                "description": RISK_PROFILES.get(risk_profile, {}).get("description", ""),
            }
            
            # Upsert - replace existing scan for same strategy+profile
            await self.db.precomputed_scans.update_one(
                {"strategy": strategy, "risk_profile": risk_profile},
                {"$set": scan_doc},
                upsert=True
            )
            
            logger.info(f"Stored {len(opportunities)} {risk_profile} {strategy} results")
            return True
            
        except Exception as e:
            logger.error(f"Error storing scan results: {e}")
            return False
    
    async def get_scan_results(
        self, 
        strategy: str, 
        risk_profile: str
    ) -> Optional[Dict]:
        """Retrieve pre-computed scan results."""
        try:
            result = await self.db.precomputed_scans.find_one(
                {"strategy": strategy, "risk_profile": risk_profile},
                {"_id": 0}
            )
            return result
        except Exception as e:
            logger.error(f"Error fetching scan results: {e}")
            return None
    
    async def get_all_scan_metadata(self) -> List[Dict]:
        """Get metadata for all available scans."""
        try:
            scans = await self.db.precomputed_scans.find(
                {},
                {"_id": 0, "strategy": 1, "risk_profile": 1, "count": 1, 
                 "computed_at": 1, "label": 1, "description": 1}
            ).to_list(100)
            return scans
        except Exception as e:
            logger.error(f"Error fetching scan metadata: {e}")
            return []
    
    # ==================== NIGHTLY JOB ====================
    
    async def run_all_scans(self):
        """
        Run all pre-computed scans.
        Called by scheduler after market close.
        """
        logger.info("="*50)
        logger.info("STARTING NIGHTLY PRE-COMPUTED SCANS")
        logger.info("="*50)
        
        start_time = datetime.now()
        results = {}
        
        # Run each covered call profile
        for profile in ["conservative", "balanced", "aggressive"]:
            try:
                logger.info(f"\n--- Running {profile.upper()} Covered Call scan ---")
                opportunities = await self.run_covered_call_scan(profile)
                await self.store_scan_results("covered_call", profile, opportunities)
                results[f"cc_{profile}"] = len(opportunities)
            except Exception as e:
                logger.error(f"Error in {profile} CC scan: {e}")
                results[f"cc_{profile}"] = f"Error: {str(e)}"
        
        # TODO: Add PMCC scans in Phase 3
        
        duration = (datetime.now() - start_time).total_seconds()
        logger.info("="*50)
        logger.info(f"NIGHTLY SCANS COMPLETE in {duration:.1f}s")
        logger.info(f"Results: {results}")
        logger.info("="*50)
        
        return results
