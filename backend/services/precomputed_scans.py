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

SCAN TIMEOUT FIX (December 2025):
- Bounded concurrency via semaphore (YAHOO_SCAN_MAX_CONCURRENCY)
- Timeout handling per symbol (YAHOO_TIMEOUT_SECONDS)
- Retry logic with exponential backoff (YAHOO_MAX_RETRIES)
- Partial success: failed symbols are logged, scan continues
- Aggregated stats logging per scan run
"""

import json
from collections import defaultdict
import asyncio
import logging
import aiohttp
import httpx
import pytz
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, Tuple
import yfinance as yf
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor

# Import centralized market status helper
from .data_provider import is_market_closed

# Import resilient fetch service for scan timeout handling
from .resilient_fetch import (
    ResilientYahooFetcher,
    fetch_with_resilience,
    get_scan_semaphore,
    ScanStats,
    get_resilience_config,
    YAHOO_SCAN_MAX_CONCURRENCY,
    YAHOO_TIMEOUT_SECONDS,
    YAHOO_MAX_RETRIES
)

# Import universe builder for ETF detection
from utils.universe import is_etf, get_scan_universe, get_tier_counts

# Import shared pricing rules for global consistency
from .pricing_rules import (
    get_sell_price,
    get_buy_price,
    validate_pmcc_structure_rules,
    compute_pmcc_economics
)

# Import shared yfinance helpers for global consistency
# ALL underlying price and option chain fetches MUST use these helpers
from .yf_pricing import (
    get_underlying_price_yf,
    get_option_chain_yf,
    get_all_expirations_yf
)

# Configure logging
logger = logging.getLogger(__name__)

# ==================== PMCC DEBUG INSTRUMENTATION ====================
# Lightweight rejection counters to diagnose "0 results" scenarios.
# Enables quick visibility into which rule is eliminating candidates.


class RejectStats:
    def __init__(self, sample_limit: int = 10):
        self.total = 0
        self.kept = 0
        self.reasons = defaultdict(int)
        self.samples = defaultdict(list)
        self.sample_limit = sample_limit

    def reject(self, reason: str, sample: Optional[Dict[str, Any]] = None):
        self.reasons[reason] += 1
        if sample is not None and len(self.samples[reason]) < self.sample_limit:
            self.samples[reason].append(sample)

    def keep(self):
        self.kept += 1

    def summary(self) -> Dict[str, Any]:
        sorted_reasons = sorted(self.reasons.items(),
                                key=lambda x: x[1], reverse=True)
        return {
            "total_candidates": self.total,
            "kept": self.kept,
            "rejections_total": max(0, self.total - self.kept),
            "rejection_reasons": [{"reason": r, "count": c} for r, c in sorted_reasons],
            "samples": {k: v for k, v in self.samples.items()},
        }

    def log(self, logger_obj=None, prefix: str = "PMCC_DEBUG"):
        payload = self.summary()
        txt = json.dumps(payload, default=str, indent=2)
        if logger_obj:
            logger_obj.info(f"{prefix} summary:\n{txt}")
        else:
            print(f"{prefix} summary:\n{txt}")


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
        "rsi_min": 35,
        "rsi_max": 65,
        "atr_pct_max": 0.04,  # ATR <= 4%
        "no_recent_gap": False,  # Relaxed for more results
        "gap_threshold": 0.03,
        # Fundamental filters
        "market_cap_min": 5_000_000_000,  # $5B (relaxed from $10B)
        "eps_positive": True,
        "revenue_growth_min": 0,  # Relaxed - any positive revenue is fine
        "debt_to_equity_max": 1.0,  # Relaxed from 0.6
        "roe_min": 0.08,  # 8% (relaxed from 12%)
        # Options filters
        "iv_percentile_min": 15,
        "iv_percentile_max": 50,
        "delta_min": 0.20,
        "delta_max": 0.35,
        "dte_min": 20,
        "dte_max": 50,
        "premium_yield_min": 0.005,  # 0.5% (relaxed)
        # Earnings filter
        "earnings_days_away_min": 14,
    },
    "balanced": {
        "label": "Steady Income",
        "description": "Slightly bullish stocks with moderate volatility",
        # Technical filters
        "trend_sma50_above_sma200": False,  # Just price > SMA50
        "price_above_sma50": True,
        "rsi_min": 40,
        "rsi_max": 70,
        "atr_pct_max": 0.06,  # ATR <= 6%
        "no_recent_gap": False,
        "volume_above_avg": False,  # Relaxed
        # Fundamental filters
        "market_cap_min": 2_000_000_000,  # $2B
        "eps_positive": False,  # Allow negative EPS
        "revenue_growth_min": 0,  # Any revenue growth
        "debt_to_equity_max": 2.0,  # More lenient
        "roe_min": 0,
        # Options filters
        "iv_percentile_min": 20,
        "iv_percentile_max": 60,
        "delta_min": 0.25,
        "delta_max": 0.45,
        "dte_min": 15,
        "dte_max": 45,
        "premium_yield_min": 0.008,  # 0.8%
        # Earnings filter
        "earnings_days_away_min": 14,
    },
    "aggressive": {
        "label": "Premium Hunter",
        "description": "Strong momentum with premium maximization",
        # Technical filters
        "trend_sma50_above_sma200": True,  # MANDATORY: Slightly bullish bias for ALL scans
        "price_above_sma20": True,  # Fast trend confirmation
        "price_above_sma50": False,  # Relaxed - using SMA20 for short-term momentum
        "rsi_min": 45,
        "rsi_max": 80,
        "atr_pct_min": 0.025,  # ATR >= 2.5% (more momentum stocks)
        "volume_expansion": False,  # Relaxed
        # Fundamental filters
        "market_cap_min": 1_000_000_000,  # $1B
        "eps_positive": False,
        "revenue_growth_min": 0,  # Any growth
        "debt_to_equity_max": None,  # No limit
        "roe_min": 0,
        # Options filters
        "iv_percentile_min": 35,
        "iv_percentile_max": 90,
        "delta_min": 0.35,
        "delta_max": 0.55,
        "dte_min": 7,
        "dte_max": 35,
        "premium_yield_min": 0.012,  # 1.2%
        # Earnings filter
        "earnings_days_away_min": 3,
    }
}

# PMCC-specific configurations
PMCC_PROFILES = {
    "conservative": {
        "label": "Capital Efficient Income",
        "description": "High delta LEAPS with conservative short calls for stable income",
        "long_dte_min": 365,  # Minimum 12 months for true LEAPS
        "long_dte_max": 730,
        "long_delta_min": 0.70,
        "long_delta_max": 0.80,
        "long_itm_pct": 0.05,  # ITM >= 10%
        "short_delta_min": 0.20,
        "short_delta_max": 0.30,
        "short_dte_min": 25,
        "short_dte_max": 45,
    },
    "balanced": {
        "label": "Leveraged Income",
        "description": "Moderate delta LEAPS with balanced risk/reward diagonal spread",
        "long_dte_min": 365,  # Minimum 12 months for true LEAPS
        "long_dte_max": 730,
        "long_delta_min": 0.65,
        "long_delta_max": 0.75,
        "long_itm_pct": 0.05,
        "short_delta_min": 0.30,
        "short_delta_max": 0.40,
        "short_dte_min": 20,
        "short_dte_max": 40,
    },
    "aggressive": {
        "label": "Max Yield Diagonal",
        "description": "Lower delta LEAPS with aggressive short calls for maximum yield",
        "long_dte_min": 365,  # Minimum 12 months for true LEAPS
        "long_dte_max": 730,
        "long_delta_min": 0.55,
        "long_delta_max": 0.70,
        "long_itm_pct": 0.05,
        "short_delta_min": 0.35,
        "short_delta_max": 0.55,
        "short_dte_min": 7,
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
                wait_time = STOCK_API_RATE_WINDOW - \
                    (now - oldest).total_seconds()
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

        GLOBAL CONSISTENCY: Uses get_underlying_price_yf() for close price.
        """
        try:
            def _fetch_yahoo():
                # Import shared helper inside thread to avoid circular imports
                from .yf_pricing import get_underlying_price_yf
                from .data_provider import get_market_state

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
                tr = pd.concat(
                    [high_low, high_close, low_close], axis=1).max(axis=1)
                hist['ATR14'] = tr.rolling(window=14).mean()

                # Calculate daily change % for gap detection
                hist['daily_change_pct'] = hist['Close'].pct_change().abs()

                # ============================================================
                # GLOBAL CONSISTENCY: Use shared yf_pricing helper for close
                # This ensures precomputed uses IDENTICAL price as Dashboard
                # ============================================================
                market_state = get_market_state()
                close, field_used, price_time = get_underlying_price_yf(
                    symbol, market_state)

                if close is None or close <= 0:
                    # Fallback to history if helper fails
                    close = float(hist['Close'].iloc[-1])
                    field_used = "history_fallback"

                # Log for verification (NVDA only for debugging)
                if symbol == "NVDA":
                    logger.info(f"[PRECOMPUTED_PRICE_CHECK] symbol={symbol} market_state={market_state} "
                                f"helper_price={close} field_used={field_used} price_time={price_time}")

                # Get technical indicators from last row (for SMA/RSI/ATR)
                latest = hist.iloc[-1]

                # Calculate 20-day average volume
                avg_volume_20d = hist['Volume'].tail(20).mean()

                # Check for gaps in last 10 days
                max_gap_10d = hist['daily_change_pct'].tail(10).max()

                # NOTE: 'close' comes from shared helper, NOT reassigned here
                return {
                    "symbol": symbol,
                    "close": float(close),  # From get_underlying_price_yf()
                    "close_field_used": field_used,  # Track which field was used
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
                        earnings_dt = datetime.strptime(
                            earnings_date, "%Y-%m-%d")
                        days_to_earnings = (earnings_dt - datetime.now()).days
                    except Exception:
                        pass

                # Analyst Rating
                recommendation = info.get("recommendationKey", "")
                num_analysts = info.get("numberOfAnalystOpinions", 0)
                target_price = info.get("targetMeanPrice")

                # Map Yahoo's recommendation keys to display values
                rating_map = {
                    "strong_buy": "Strong Buy",
                    "buy": "Buy",
                    "hold": "Hold",
                    "underperform": "Sell",
                    "sell": "Sell"
                }
                analyst_rating = rating_map.get(recommendation, recommendation.replace(
                    "_", " ").title() if recommendation else None)

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
                    "analyst_rating": analyst_rating,
                    "num_analysts": num_analysts,
                    "target_price": target_price,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }

            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(self._executor, _fetch_fundamentals)

        except Exception as e:
            logger.warning(
                f"Failed to fetch fundamental data for {symbol}: {e}")
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
        Fetch and filter options contracts using Yahoo Finance (primary) for IV/OI data.
        Falls back to Polygon if Yahoo fails.
        """
        try:
            # Try Yahoo Finance first (has IV, OI data)
            options = await self._fetch_options_yahoo(symbol, current_price, dte_min, dte_max, delta_min, delta_max)
            if options:
                return options

            # Fallback to Polygon (no IV/OI in basic plan)
            if self.api_key:
                return await self._fetch_options_polygon(symbol, current_price, dte_min, dte_max, delta_min, delta_max)

            return []
        except Exception as e:
            logger.error(f"Error fetching options for {symbol}: {e}")
            return []

    async def _fetch_options_yahoo(
        self,
        symbol: str,
        current_price: float,
        dte_min: int,
        dte_max: int,
        delta_min: float,
        delta_max: float
    ) -> List[Dict[str, Any]]:
        """Fetch options from Yahoo Finance with real IV and OI data."""
        try:
            def _fetch_yahoo_sync():
                ticker = yf.Ticker(symbol)
                try:
                    expirations = ticker.options
                except Exception:
                    return []

                if not expirations:
                    return []

                today = datetime.now()
                options = []

                for exp_str in expirations:
                    try:
                        exp_date = datetime.strptime(exp_str, "%Y-%m-%d")
                        dte = (exp_date - today).days

                        if dte < dte_min or dte > dte_max:
                            continue

                        opt_chain = ticker.option_chain(exp_str)
                        calls = opt_chain.calls

                        for _, row in calls.iterrows():
                            strike = row.get('strike', 0)
                            if not strike:
                                continue

                            # Get IV for Black-Scholes delta calculation
                            iv_raw = row.get('impliedVolatility', 0)

                            # Skip if IV is unrealistic
                            if iv_raw and (iv_raw < 0.01 or iv_raw > 5.0):
                                iv_raw = 0

                            # Calculate delta using Black-Scholes
                            # (Removed moneyness-based delta fallback for accuracy)
                            from .greeks_service import calculate_greeks, normalize_iv_fields

                            iv_data = normalize_iv_fields(iv_raw)
                            T = max(dte, 1) / 365.0

                            greeks_result = calculate_greeks(
                                S=current_price,
                                K=float(strike),
                                T=T,
                                sigma=iv_data["iv"] if iv_data["iv"] > 0 else None,
                                option_type="call"
                            )

                            est_delta = greeks_result.delta
                            delta_source = greeks_result.delta_source

                            # Filter by delta
                            if est_delta < delta_min or est_delta > delta_max:
                                continue

                            # PRICING RULES - SELL leg (covered call):
                            # - Use BID only
                            # - If BID is None, 0, or missing → reject the contract
                            # - Never use: lastPrice, mid, ASK, theoretical price
                            bid = row.get('bid', 0)
                            ask = row.get('ask', 0)

                            if not bid or bid <= 0:
                                continue  # Reject - no valid BID for SELL leg

                            premium = bid  # BID only for SELL leg

                            # DATA QUALITY FILTER: Premium sanity check
                            max_reasonable_premium = current_price * 0.20
                            if premium > max_reasonable_premium:
                                continue

                            premium_yield = premium / current_price

                            # DATA QUALITY FILTER: ROI sanity check
                            if premium_yield > 0.50:
                                continue

                            # Get OI and volume from Yahoo
                            oi = row.get('openInterest', 0)
                            volume = row.get('volume', 0)

                            # Filter low liquidity options
                            if oi and oi > 0 and oi < 10:
                                continue

                            options.append({
                                "contract_ticker": row.get('contractSymbol', ''),
                                "symbol": symbol,
                                "strike": float(strike),
                                "expiry": exp_str,
                                "dte": dte,
                                "premium": round(float(premium), 2),
                                "premium_yield": round(premium_yield, 4),
                                # Greeks (Black-Scholes)
                                "delta": round(est_delta, 4),
                                "delta_source": delta_source,
                                "gamma": greeks_result.gamma,
                                "theta": greeks_result.theta,
                                "vega": greeks_result.vega,
                                # IV fields (standardized)
                                "iv": iv_data["iv"],
                                "iv_pct": iv_data["iv_pct"],
                                # Liquidity
                                "volume": int(volume) if volume else 0,
                                "open_interest": int(oi) if oi else 0,
                                "bid": float(bid) if bid else 0,
                                "ask": float(ask) if ask else 0
                            })

                    except Exception as e:
                        logger.debug(
                            f"Error processing expiry {exp_str} for {symbol}: {e}")
                        continue

                return options

            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(self._executor, _fetch_yahoo_sync)

        except Exception as e:
            logger.warning(f"Yahoo options fetch failed for {symbol}: {e}")
            return []

    async def _fetch_options_polygon(
        self,
        symbol: str,
        current_price: float,
        dte_min: int,
        dte_max: int,
        delta_min: float,
        delta_max: float
    ) -> List[Dict[str, Any]]:
        """Fallback: Fetch options from Polygon (no IV/OI in basic plan)."""
        if not self.api_key:
            return []

        try:
            today = datetime.now()
            min_expiry = (today + timedelta(days=dte_min)).strftime("%Y-%m-%d")
            max_expiry = (today + timedelta(days=dte_max)).strftime("%Y-%m-%d")

            # Calculate strike range based on delta targets
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
                    logger.warning(
                        f"Polygon contracts API error for {symbol}: {response.status_code}")
                    return []

                data = response.json()
                contracts = data.get("results", [])

                if not contracts:
                    return []

                semaphore = asyncio.Semaphore(20)

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
                                    expiry = contract.get(
                                        "expiration_date", "")

                                    dte = 0
                                    if expiry:
                                        try:
                                            exp_dt = datetime.strptime(
                                                expiry, "%Y-%m-%d")
                                            dte = (
                                                exp_dt - datetime.now()).days
                                        except Exception:
                                            pass

                                    # Calculate delta using Black-Scholes
                                    # Note: Polygon doesn't provide IV, so we use proxy sigma
                                    from .greeks_service import calculate_greeks

                                    T = max(dte, 1) / 365.0
                                    greeks_result = calculate_greeks(
                                        S=current_price,
                                        K=strike,
                                        T=T,
                                        sigma=None,  # Will use proxy sigma
                                        option_type="call"
                                    )

                                    est_delta = greeks_result.delta
                                    delta_source = greeks_result.delta_source

                                    if est_delta < delta_min or est_delta > delta_max:
                                        return None

                                    close_price = r.get("c", 0)
                                    if close_price <= 0:
                                        return None

                                    # WARNING: Polygon aggregates API returns OHLCV close price, not BID/ASK
                                    # This is a BACKUP ONLY - Yahoo with BID/ASK is preferred
                                    # Mark as low confidence since we can't verify BID/ASK

                                    max_reasonable_premium = current_price * 0.20
                                    if close_price > max_reasonable_premium:
                                        return None

                                    premium_yield = close_price / current_price

                                    if premium_yield > 0.50:
                                        return None

                                    return {
                                        "contract_ticker": ticker,
                                        "symbol": symbol,
                                        "strike": strike,
                                        "expiry": expiry,
                                        "dte": dte,
                                        "premium": close_price,
                                        "premium_yield": premium_yield,
                                        # Greeks (Black-Scholes with proxy sigma)
                                        "delta": round(est_delta, 4),
                                        "delta_source": delta_source,
                                        "gamma": greeks_result.gamma,
                                        "theta": greeks_result.theta,
                                        "vega": greeks_result.vega,
                                        # IV (not available from Polygon basic)
                                        "iv": 0.0,
                                        "iv_pct": 0.0,
                                        # Liquidity
                                        "volume": r.get("v", 0),
                                        "open_interest": 0,
                                        "vwap": r.get("vw", 0)
                                    }
                        except Exception as e:
                            logger.debug(
                                f"Error fetching price for {ticker}: {e}")
                        return None

                tasks = [fetch_price(c) for c in contracts[:50]]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                options = [
                    r for r in results if r and not isinstance(r, Exception)]

                return options

        except Exception as e:
            logger.error(f"Polygon options fetch failed for {symbol}: {e}")
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

        market_cap = fund_data.get("market_cap") or 0
        eps = fund_data.get("eps_ttm") or 0
        roe = fund_data.get("roe") or 0
        de_ratio = fund_data.get("debt_to_equity") or 0
        rev_growth = fund_data.get("revenue_growth") or 0
        days_to_earnings = fund_data.get("days_to_earnings")

        # Market cap filter - must have valid market cap
        min_cap = profile.get("market_cap_min", 0)
        if market_cap < min_cap:
            return False, f"Market cap ${market_cap/1e9:.1f}B below ${min_cap/1e9}B"

        # EPS filter - only apply if strictly required
        if profile.get("eps_positive") and eps is not None and eps <= 0:
            return False, f"EPS ${eps:.2f} not positive"

        # ROE filter - skip if data not available
        min_roe = profile.get("roe_min", 0)
        if min_roe > 0 and roe is not None and roe > 0 and roe < min_roe:
            return False, f"ROE {roe*100:.1f}% below {min_roe*100}%"

        # Debt to Equity filter - skip if no data
        max_de = profile.get("debt_to_equity_max")
        if max_de is not None and de_ratio is not None and de_ratio > 0 and de_ratio > max_de:
            return False, f"D/E {de_ratio:.2f} above {max_de}"

        # Revenue growth filter - skip if no data
        min_rev = profile.get("revenue_growth_min", 0)
        if min_rev > 0 and rev_growth is not None and rev_growth < min_rev:
            return False, f"Revenue growth {rev_growth*100:.1f}% below {min_rev*100}%"

        # Earnings date filter - skip if no data
        min_days = profile.get("earnings_days_away_min", 0)
        if min_days > 0 and days_to_earnings is not None and days_to_earnings >= 0 and days_to_earnings < min_days:
            return False, f"Earnings in {days_to_earnings} days (min {min_days})"

        return True, "Passed"

    # ==================== MAIN SCAN LOGIC ====================

    async def run_covered_call_scan(
        self,
        risk_profile: str = "conservative",
        snapshots: Optional[Dict[str, Dict]] = None
    ) -> List[Dict[str, Any]]:
        """
        Run a covered call scan for the given risk profile.
        Returns ranked list of opportunities.

        CACHE-ONLY (February 2026):
        - Reads from MongoDB daily_snapshots — zero Yahoo Finance calls.
        - snapshots dict passed in from run_all_scans (loaded once).
        - Falls back to loading from DB if called standalone.

        SCAN TIMEOUT FIX (December 2025):
        - Uses bounded concurrency via semaphore
        - Applies timeout/retry to each symbol fetch
        - Continues on partial failure (logs failed symbols)
        - Aggregates success/timeout/error counts
        """
        profile = RISK_PROFILES.get(
            risk_profile, RISK_PROFILES["conservative"])
        run_id = f"cc_{risk_profile}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

        logger.info(
            f"Starting {risk_profile} covered call scan (run_id={run_id})...")
        logger.info(
            f"Resilience config: concurrency={YAHOO_SCAN_MAX_CONCURRENCY}, timeout={YAHOO_TIMEOUT_SECONDS}s, retries={YAHOO_MAX_RETRIES}")

        # ── Load snapshots from MongoDB if not passed in ──────────────
        if snapshots is None:
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            raw_snaps = await self.db.daily_snapshots.find(
                {"snapshot_date": today_str}
            ).to_list(length=5000)
            snapshots = {s["symbol"]: s for s in raw_snaps}

        if not snapshots:
            logger.error(f"CC scan ({risk_profile}): no snapshots available")
            return []

        # Get symbol universe — limited to symbols present in snapshots
        all_symbols = await self.get_liquid_symbols()
        symbols = [s for s in all_symbols if s in snapshots]
        logger.info(
            f"Scanning {len(symbols)} symbols for {risk_profile} profile ({len(snapshots)} snapshots available)")

        # Initialize resilient fetcher for this scan
        fetcher = ResilientYahooFetcher(
            scan_type=f"covered_call_{risk_profile}", run_id=run_id)
        fetcher.set_total_symbols(len(symbols))

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

        # Process symbols in batches with bounded concurrency
        # The semaphore in resilient_fetch limits concurrent Yahoo calls
        batch_size = 10
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]

            # Fetch technical and fundamental data with resilience
            # Each call goes through the semaphore and has timeout/retry
            tech_results = []
            fund_results = []

            for symbol in batch:
                # Technical data fetch with resilience
                tech_data = await fetcher.fetch(
                    symbol,  # For logging
                    self.fetch_technical_data,
                    symbol  # Pass symbol as argument to fetch_technical_data
                )
                tech_results.append(tech_data)

                # ================================================================
                # ETF HANDLING: Skip fundamental fetch for ETFs
                # ETFs don't have traditional fundamentals (market cap, P/E, EPS)
                # Fetching would result in 404s or empty data
                # ================================================================
                if is_etf(symbol):
                    # ETF: Use placeholder data, skip fundamental fetch
                    fund_results.append(
                        {"symbol": symbol, "is_etf": True, "fundamentals_skipped": True})
                    logger.debug(f"ETF_FUNDAMENTALS_SKIPPED | symbol={symbol}")
                else:
                    # Stock: Fetch fundamental data with resilience
                    fund_data = await fetcher.fetch(
                        symbol,  # For logging
                        self.fetch_fundamental_data,
                        symbol  # Pass symbol as argument to fetch_fundamental_data
                    )
                    fund_results.append(fund_data)

            for j, symbol in enumerate(batch):
                tech_data = tech_results[j]
                fund_data = fund_results[j]
                symbol_is_etf = is_etf(symbol)

                # Handle fetch failures gracefully (partial success)
                if tech_data is None:
                    stats["failed_technical"].append(
                        (symbol, "Fetch failed/timeout"))
                    continue

                # Apply technical filters
                tech_pass, tech_reason = self.passes_technical_filters(
                    tech_data, profile)
                if not tech_pass:
                    stats["failed_technical"].append((symbol, tech_reason))
                    continue
                stats["passed_technical"] += 1

                # ================================================================
                # ETF HANDLING: Skip fundamental filters for ETFs
                # ETFs pass fundamental stage automatically
                # ================================================================
                if symbol_is_etf:
                    # ETF: Auto-pass fundamentals
                    stats["passed_fundamental"] += 1
                    logger.debug(
                        f"ETF_FUNDAMENTALS_BYPASSED | symbol={symbol}")
                else:
                    # Stock: Apply fundamental filters
                    # Handle fundamental fetch failure
                    if fund_data is None:
                        stats["failed_fundamental"].append(
                            (symbol, "Fetch failed/timeout"))
                        continue

                    # Apply fundamental filters
                    fund_pass, fund_reason = self.passes_fundamental_filters(
                        fund_data, profile)
                    if not fund_pass:
                        stats["failed_fundamental"].append(
                            (symbol, fund_reason))
                        continue
                    stats["passed_fundamental"] += 1

                # ── Read options from snapshot (NO Yahoo call) ────────
                current_price = tech_data.get("close", 0)
                snap = snapshots.get(symbol, {})
                raw_short_calls = snap.get("short_calls", [])

                if not raw_short_calls:
                    stats["failed_options"].append(
                        (symbol, "No short_calls in snapshot"))
                    continue

                # Convert snapshot short_calls to the same shape fetch_options_for_scan returns
                options = []
                for opt in raw_short_calls:
                    bid = opt.get("bid", 0) or 0
                    if bid <= 0:
                        continue
                    oi = opt.get("open_interest", 0) or 0
                    dte = opt.get("dte", 0)
                    strike = opt.get("strike", 0)
                    premium_yield = bid / current_price if current_price > 0 else 0
                    options.append({
                        "strike": strike,
                        "expiry": opt.get("expiry", ""),
                        "dte": dte,
                        "premium": round(bid, 2),
                        "premium_yield": round(premium_yield, 4),
                        "delta": opt.get("delta", 0),
                        "volume": opt.get("volume", 0),
                        "open_interest": oi,
                        "bid": bid,
                        "ask": opt.get("ask", 0),
                        "iv": opt.get("iv", 0),
                        "iv_pct": opt.get("iv_pct", 0),
                    })

                # Apply delta filter from profile
                options = [
                    o for o in options
                    if profile["delta_min"] <= o.get("delta", 0) <= profile["delta_max"]
                ] if any(o.get("delta", 0) > 0 for o in options) else options

                if not options:
                    stats["failed_options"].append(
                        (symbol, "No matching options in snapshot"))
                    continue

                stats["passed_options"] += 1

                # Filter by premium yield
                min_yield = profile.get("premium_yield_min", 0)
                qualified_options = [o for o in options if o.get(
                    "premium_yield", 0) >= min_yield]

                if not qualified_options:
                    continue

                # Score and rank options
                for opt in qualified_options:
                    # Calculate composite score
                    roi_score = min(opt["premium_yield"] * 100 * 15, 40)
                    delta_score = 20 - abs(opt["delta"] - 0.30) * 50
                    dte_score = 10 - abs(opt["dte"] - 30) * 0.3

                    # Fundamental bonus (ETFs get neutral score since fundamentals skipped)
                    fund_score = 0
                    if not symbol_is_etf:
                        if fund_data.get("roe", 0) > 0.15:
                            fund_score += 5
                        if fund_data.get("revenue_growth", 0) > 0.10:
                            fund_score += 5

                    total_score = max(
                        0, roi_score + delta_score + dte_score + fund_score)

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
                        # Timeframe classification
                        "timeframe": "weekly" if opt["dte"] <= 14 else "monthly",
                        # ETF flag
                        "is_etf": symbol_is_etf,
                        # Include technical indicators
                        "sma50": tech_data.get("sma50"),
                        "sma200": tech_data.get("sma200"),
                        "rsi14": tech_data.get("rsi14"),
                        "atr_pct": round(tech_data.get("atr_pct", 0) * 100, 2) if tech_data.get("atr_pct") else None,
                        # Include fundamental data (None for ETFs)
                        "market_cap": fund_data.get("market_cap", 0) if not symbol_is_etf else None,
                        "eps_ttm": fund_data.get("eps_ttm", 0) if not symbol_is_etf else None,
                        "roe": round(fund_data.get("roe", 0) * 100, 1) if fund_data.get("roe") and not symbol_is_etf else None,
                        "debt_to_equity": fund_data.get("debt_to_equity") if not symbol_is_etf else None,
                        "days_to_earnings": fund_data.get("days_to_earnings") if not symbol_is_etf else None,
                        "sector": fund_data.get("sector", "") if not symbol_is_etf else "ETF",
                        # Include analyst rating (None for ETFs)
                        "analyst_rating": fund_data.get("analyst_rating") if not symbol_is_etf else None,
                        "num_analysts": fund_data.get("num_analysts", 0) if not symbol_is_etf else None,
                        "target_price": fund_data.get("target_price") if not symbol_is_etf else None,
                        # Include IV data
                        "iv": opt.get("iv"),
                        "iv_pct": round(opt.get("iv", 0) * 100, 1) if opt.get("iv") else None,
                        # Include OI and IV Rank data
                        "open_interest": opt.get("open_interest", 0),
                        "iv_rank": round(min(100, opt.get("iv", 0) * 100 * 1.5), 0) if opt.get("iv") else None,
                    })

            # Inter-batch delay to avoid rate limiting
            # Reduced since semaphore now controls concurrency
            await asyncio.sleep(1.0)

        # Log resilient fetch stats
        scan_stats = fetcher.get_stats()
        scan_stats.log_summary()

        # Deduplicate: Keep best Weekly + Monthly per symbol
        opportunities = self._dedupe_by_symbol_timeframe(opportunities)

        # Sort by score and limit
        opportunities.sort(key=lambda x: x["score"], reverse=True)
        opportunities = opportunities[:50]  # Top 50

        logger.info(f"Scan complete: {len(opportunities)} opportunities found")
        logger.info(f"Stats: {stats['passed_technical']} passed tech, "
                    f"{stats['passed_fundamental']} passed fund, "
                    f"{stats['passed_options']} had options")

        return opportunities

    def _dedupe_by_symbol_timeframe(self, opportunities: List[Dict]) -> List[Dict]:
        """
        PHASE 3: AI-Based Best Option Selection per Symbol

        ============================================================
        IMPORTANT:
        Scan candidates may include multiple options per symbol.
        Final output must return ONE best option per symbol,
        selected by highest AI score.
        ============================================================

        Selection Criteria (in order of priority):
        1. Highest AI score (score field) - Primary
        2. Highest quality score (quality_score field) - Tie-breaker
        3. Highest ROI (roi_pct field) - Secondary tie-breaker
        """
        if not opportunities:
            return []

        # Group by symbol only (not by timeframe)
        symbol_best = {}

        for opp in opportunities:
            symbol = opp["symbol"]

            if symbol not in symbol_best:
                symbol_best[symbol] = opp
            else:
                # Compare: score → quality_score → roi_pct
                current_best = symbol_best[symbol]

                # Primary: AI score
                if opp.get("score", 0) > current_best.get("score", 0):
                    symbol_best[symbol] = opp
                elif opp.get("score", 0) == current_best.get("score", 0):
                    # Tie-breaker 1: quality_score
                    if opp.get("quality_score", 0) > current_best.get("quality_score", 0):
                        symbol_best[symbol] = opp
                    elif opp.get("quality_score", 0) == current_best.get("quality_score", 0):
                        # Tie-breaker 2: roi_pct
                        if opp.get("roi_pct", 0) > current_best.get("roi_pct", 0):
                            symbol_best[symbol] = opp

        result = list(symbol_best.values())
        logger.debug(
            f"PHASE 3: Deduplicated {len(opportunities)} candidates to {len(result)} unique symbols")
        return result

    # ==================== STORAGE ====================

    async def store_scan_results(
        self,
        strategy: str,
        risk_profile: str,
        opportunities: List[Dict]
    ) -> bool:
        """Store pre-computed scan results in MongoDB.

        IMPORTANT: If new scan returns 0 results, preserve the previous data
        to ensure users always see something (previous market close data).
        """
        try:
            now = datetime.now(timezone.utc)

            # SAFETY: Don't overwrite good data with empty results
            if not opportunities or len(opportunities) == 0:
                existing = await self.db.precomputed_scans.find_one(
                    {"strategy": strategy, "risk_profile": risk_profile}
                )
                if existing and existing.get("count", 0) > 0:
                    logger.warning(f"Scan returned 0 results for {strategy}/{risk_profile}. "
                                   f"Preserving previous data ({existing.get('count')} opportunities)")
                    return True

            # Use appropriate profile config based on strategy
            if strategy == "pmcc":
                profile_config = PMCC_PROFILES.get(risk_profile, {})
            else:
                profile_config = RISK_PROFILES.get(risk_profile, {})

            scan_doc = {
                "strategy": strategy,  # "covered_call" or "pmcc"
                "risk_profile": risk_profile,
                "opportunities": opportunities,
                "count": len(opportunities),
                "computed_at": now.isoformat(),
                "computed_date": now.strftime("%Y-%m-%d"),
                "label": profile_config.get("label", risk_profile.title()),
                "description": profile_config.get("description", ""),
            }

            # Upsert - replace existing scan for same strategy+profile
            await self.db.precomputed_scans.update_one(
                {"strategy": strategy, "risk_profile": risk_profile},
                {"$set": scan_doc},
                upsert=True
            )

            logger.info(
                f"Stored {len(opportunities)} {risk_profile} {strategy} results")
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
        Reads ONLY from MongoDB daily_snapshots — zero Yahoo Finance calls.
        Snapshots loaded ONCE and passed to both CC and PMCC scan methods.
        """
        logger.info("=" * 50)
        logger.info("STARTING NIGHTLY PRE-COMPUTED SCANS (cache-only)")
        logger.info("=" * 50)

        start_time = datetime.now()
        results = {}

        # ── Load snapshots ONCE ──────────────────────────────────────
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        raw_snaps = await self.db.daily_snapshots.find(
            {"snapshot_date": today_str}
        ).to_list(length=5000)

        if not raw_snaps:
            logger.error("No daily_snapshots found for today — aborting scans")
            return {"error": "no_snapshots"}

        # Index by symbol for O(1) lookup
        snapshots: Dict[str, Dict] = {s["symbol"]: s for s in raw_snaps}
        logger.info(f"Loaded {len(snapshots)} snapshots for {today_str}")

        # ── CC scans ─────────────────────────────────────────────────
        all_opportunities: Dict[str, List[Dict]] = {}
        for profile in ["conservative", "balanced", "aggressive"]:
            try:
                logger.info(
                    f"\n--- Running {profile.upper()} Covered Call scan ---")
                opportunities = await self.run_covered_call_scan(profile, snapshots)
                all_opportunities[profile] = opportunities
                logger.info(
                    f"  Found {len(opportunities)} raw opportunities for {profile}")
            except Exception as e:
                logger.error(f"Error in {profile} CC scan: {e}")
                all_opportunities[profile] = []
                results[f"cc_{profile}"] = f"Error: {str(e)}"

        deduped_opportunities = self._dedupe_across_profiles(all_opportunities)
        for profile, opportunities in deduped_opportunities.items():
            await self.store_scan_results("covered_call", profile, opportunities)
            results[f"cc_{profile}"] = len(opportunities)
            logger.info(
                f"  Stored {len(opportunities)} deduplicated opportunities for {profile}")

        # ── PMCC scans ───────────────────────────────────────────────
        logger.info("\n" + "=" * 50)
        logger.info("STARTING PMCC SCANS")
        logger.info("=" * 50)

        pmcc_opportunities: Dict[str, List[Dict]] = {}
        for profile in ["conservative", "balanced", "aggressive"]:
            try:
                logger.info(f"\n--- Running {profile.upper()} PMCC scan ---")
                opportunities = await self.run_pmcc_scan(profile, snapshots)
                pmcc_opportunities[profile] = opportunities
                logger.info(
                    f"  Found {len(opportunities)} raw PMCC opportunities for {profile}")
            except Exception as e:
                logger.error(f"Error in {profile} PMCC scan: {e}")
                pmcc_opportunities[profile] = []
                results[f"pmcc_{profile}"] = f"Error: {str(e)}"

        deduped_pmcc = self._dedupe_across_profiles(pmcc_opportunities)
        for profile, opportunities in deduped_pmcc.items():
            await self.store_scan_results("pmcc", profile, opportunities)
            results[f"pmcc_{profile}"] = len(opportunities)
            logger.info(
                f"  Stored {len(opportunities)} deduplicated PMCC opportunities for {profile}")

        duration = (datetime.now() - start_time).total_seconds()
        logger.info("=" * 50)
        logger.info(f"NIGHTLY SCANS COMPLETE in {duration:.1f}s")
        logger.info(f"Results: {results}")
        logger.info("=" * 50)

        return results

    def _dedupe_across_profiles(self, all_opportunities: Dict[str, List[Dict]]) -> Dict[str, List[Dict]]:
        """
        Deduplicate symbols across profiles.
        Each symbol should appear in only ONE profile - the one it's most suitable for.

        Logic:
        1. For each symbol, determine which profile it fits best based on its characteristics
        2. Conservative: Low ATR, high market cap, positive EPS, SMA alignment
        3. Balanced: Moderate ATR, decent fundamentals
        4. Aggressive: High ATR, momentum characteristics
        """
        # Track which symbols are assigned to which profile
        symbol_assignments = {}  # symbol -> (profile, best_opportunity)

        # Priority order: conservative first, then balanced, then aggressive
        # But we'll assign based on BEST FIT, not just first-come
        profiles_order = ["conservative", "balanced", "aggressive"]

        for profile in profiles_order:
            for opp in all_opportunities.get(profile, []):
                symbol = opp["symbol"]

                if symbol not in symbol_assignments:
                    # First time seeing this symbol, assign it
                    symbol_assignments[symbol] = (profile, opp)
                else:
                    # Symbol already assigned, check if this profile is a better fit
                    existing_profile, existing_opp = symbol_assignments[symbol]

                    # Calculate "fit score" for each profile based on characteristics
                    existing_fit = self._calculate_profile_fit(
                        existing_opp, existing_profile)
                    new_fit = self._calculate_profile_fit(opp, profile)

                    # If new profile is a better fit, reassign
                    if new_fit > existing_fit:
                        symbol_assignments[symbol] = (profile, opp)

        # Build deduplicated lists for each profile
        deduped = {profile: [] for profile in profiles_order}
        for symbol, (profile, opp) in symbol_assignments.items():
            deduped[profile].append(opp)

        # Sort each profile's list by score
        for profile in deduped:
            deduped[profile].sort(key=lambda x: x["score"], reverse=True)
            deduped[profile] = deduped[profile][:50]  # Limit to 50

        return deduped

    def _calculate_profile_fit(self, opp: Dict, profile: str) -> float:
        """
        Calculate how well an opportunity fits a specific profile.
        Higher score = better fit.
        """
        fit_score = 0

        atr_pct = opp.get("atr_pct", 3) or 3  # Default 3%
        market_cap = opp.get("market_cap", 0) or 0
        eps = opp.get("eps_ttm", 0) or 0
        roe = opp.get("roe", 0) or 0
        delta = opp.get("delta", 0.35) or 0.35
        dte = opp.get("dte", 30) or 30

        if profile == "conservative":
            # Conservative prefers: low ATR, high market cap, positive EPS, low delta, longer DTE
            if atr_pct <= 3:
                fit_score += 20
            elif atr_pct <= 4:
                fit_score += 10

            if market_cap >= 50_000_000_000:  # $50B+
                fit_score += 20
            elif market_cap >= 10_000_000_000:  # $10B+
                fit_score += 10

            if eps > 0:
                fit_score += 15

            if delta <= 0.30:
                fit_score += 15

            if dte >= 30:
                fit_score += 10

        elif profile == "balanced":
            # Balanced prefers: moderate ATR, decent market cap, moderate delta
            if 3 <= atr_pct <= 5:
                fit_score += 20
            elif atr_pct < 3:
                fit_score += 10

            if 5_000_000_000 <= market_cap <= 50_000_000_000:
                fit_score += 15

            if 0.30 <= delta <= 0.40:
                fit_score += 15

            if 20 <= dte <= 40:
                fit_score += 10

        elif profile == "aggressive":
            # Aggressive prefers: high ATR, any market cap, higher delta, shorter DTE
            if atr_pct >= 4:
                fit_score += 25
            elif atr_pct >= 3:
                fit_score += 15

            if delta >= 0.40:
                fit_score += 20

            if dte <= 21:
                fit_score += 15

            # Higher premium yield is bonus for aggressive
            premium_yield = opp.get("premium_yield", 0) or 0
            if premium_yield >= 1.5:
                fit_score += 15
            elif premium_yield >= 1.0:
                fit_score += 10

        return fit_score

    # ==================== PMCC SCAN LOGIC ====================

    async def fetch_leaps_options(
        self,
        symbol: str,
        current_price: float,
        dte_min: int,
        dte_max: int = None,
        delta_min: float = 0.55,
        delta_max: float = 0.80,
        itm_pct: float = 0.10
    ) -> List[Dict[str, Any]]:
        """
        Fetch LEAPS (Long-term Equity AnticiPation Securities) for PMCC long leg.
        LEAPS are deep ITM calls with high delta and long DTE.

        Uses Yahoo Finance (primary) with Polygon as fallback.
        """
        # Try Yahoo Finance first
        leaps = await self._fetch_leaps_yahoo(symbol, current_price, dte_min, dte_max, delta_min, delta_max, itm_pct)
        if leaps:
            return leaps

        # Fallback to Polygon
        return await self._fetch_leaps_polygon(symbol, current_price, dte_min, dte_max, delta_min, delta_max, itm_pct)

    async def _fetch_leaps_yahoo(
        self,
        symbol: str,
        current_price: float,
        dte_min: int,
        dte_max: int,
        delta_min: float,
        delta_max: float,
        itm_pct: float
    ) -> List[Dict[str, Any]]:
        """Fetch LEAPS from Yahoo Finance."""
        try:
            def _fetch_yahoo_sync():
                ticker = yf.Ticker(symbol)
                try:
                    expirations = ticker.options
                except Exception:
                    return []

                if not expirations:
                    return []

                today = datetime.now()
                leaps = []

                for exp_str in expirations:
                    try:
                        exp_date = datetime.strptime(exp_str, "%Y-%m-%d")
                        dte = (exp_date - today).days

                        # Filter for LEAPS (long-term)
                        if dte < dte_min or dte > (dte_max or 730):
                            continue

                        opt_chain = ticker.option_chain(exp_str)
                        calls = opt_chain.calls

                        for _, row in calls.iterrows():
                            strike = row.get('strike', 0)
                            if not strike:
                                continue

                            # LEAPS should be ITM - strike below current price
                            if strike >= current_price * (1 - itm_pct):
                                continue  # Not deep enough ITM

                            if strike < current_price * 0.5:
                                continue  # Too deep ITM

                            # Calculate delta using Black-Scholes
                            from .greeks_service import calculate_greeks, normalize_iv_fields

                            iv_raw = row.get('impliedVolatility', 0)
                            iv_data = normalize_iv_fields(iv_raw)
                            T = max(dte, 1) / 365.0

                            greeks_result = calculate_greeks(
                                S=current_price,
                                K=float(strike),
                                T=T,
                                sigma=iv_data["iv"] if iv_data["iv"] > 0 else None,
                                option_type="call"
                            )

                            est_delta = greeks_result.delta
                            delta_source = greeks_result.delta_source

                            if est_delta < delta_min or est_delta > delta_max:
                                continue

                            # PRICING RULES - BUY leg (PMCC LEAP):
                            # - Use ASK only
                            # - If ASK is None, 0, or missing → reject the contract
                            # - Never use: BID, lastPrice, mid
                            bid = row.get('bid', 0)
                            ask = row.get('ask', 0)

                            if not ask or ask <= 0:
                                continue  # Reject - no valid ASK for BUY leg

                            premium = ask  # ASK only for BUY leg

                            # Calculate intrinsic and extrinsic value
                            intrinsic = max(0, current_price - strike)
                            extrinsic = premium - intrinsic

                            oi = row.get('openInterest', 0)

                            # Calculate ITM percentage for display
                            itm_moneyness = (
                                current_price - float(strike)) / current_price

                            leaps.append({
                                "contract_ticker": row.get('contractSymbol', ''),
                                "symbol": symbol,
                                "strike": float(strike),
                                "expiry": exp_str,
                                "dte": dte,
                                "premium": round(float(premium), 2),
                                # Greeks (Black-Scholes)
                                "delta": round(est_delta, 4),
                                "delta_source": delta_source,
                                "gamma": greeks_result.gamma,
                                "theta": greeks_result.theta,
                                "vega": greeks_result.vega,
                                # IV fields (standardized)
                                "iv": iv_data["iv"],
                                "iv_pct": iv_data["iv_pct"],
                                # Other metrics
                                "intrinsic": round(intrinsic, 2),
                                "extrinsic": round(extrinsic, 2),
                                "itm_pct": round(itm_moneyness * 100, 1),
                                "volume": int(row.get('volume', 0) or 0),
                                "open_interest": int(oi) if oi else 0
                            })

                    except Exception as e:
                        logger.debug(
                            f"Error processing LEAPS expiry {exp_str} for {symbol}: {e}")
                        continue

                # Sort by DTE (prefer longer) and delta (prefer higher)
                leaps.sort(key=lambda x: (x["dte"], x["delta"]), reverse=True)
                return leaps

            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(self._executor, _fetch_yahoo_sync)

        except Exception as e:
            logger.debug(f"Yahoo LEAPS fetch failed for {symbol}: {e}")
            return []

    async def _fetch_leaps_polygon(
        self,
        symbol: str,
        current_price: float,
        dte_min: int,
        dte_max: int,
        delta_min: float,
        delta_max: float,
        itm_pct: float
    ) -> List[Dict[str, Any]]:
        """Fallback: Fetch LEAPS from Polygon."""
        if not self.api_key:
            return []

        try:
            today = datetime.now()
            min_expiry = (today + timedelta(days=dte_min)).strftime("%Y-%m-%d")
            max_expiry = (today + timedelta(days=dte_max or 730)
                          ).strftime("%Y-%m-%d")

            # LEAPS should be ITM - strike below current price
            strike_max = current_price * \
                (1 - itm_pct)  # At least ITM by itm_pct
            strike_min = current_price * 0.5  # Don't go too deep

            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                contracts_url = f"{POLYGON_BASE_URL}/v3/reference/options/contracts"
                params = {
                    "underlying_ticker": symbol.upper(),
                    "contract_type": "call",
                    "expiration_date.gte": min_expiry,
                    "expiration_date.lte": max_expiry,
                    "strike_price.gte": strike_min,
                    "strike_price.lte": strike_max,
                    "limit": 50,
                    "apiKey": self.api_key
                }

                response = await client.get(contracts_url, params=params)
                if response.status_code != 200:
                    return []

                data = response.json()
                contracts = data.get("results", [])

                if not contracts:
                    return []

                # Fetch prices for LEAPS
                semaphore = asyncio.Semaphore(20)

                async def fetch_leap_price(contract):
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
                                    expiry = contract.get(
                                        "expiration_date", "")

                                    # Calculate DTE
                                    dte = 0
                                    if expiry:
                                        try:
                                            exp_dt = datetime.strptime(
                                                expiry, "%Y-%m-%d")
                                            dte = (
                                                exp_dt - datetime.now()).days
                                        except Exception:
                                            pass

                                    # Calculate delta using Black-Scholes
                                    from .greeks_service import calculate_greeks

                                    T = max(dte, 1) / 365.0
                                    greeks_result = calculate_greeks(
                                        S=current_price,
                                        K=float(strike),
                                        T=T,
                                        sigma=None,  # Polygon doesn't provide IV
                                        option_type="call"
                                    )

                                    est_delta = greeks_result.delta
                                    delta_source = greeks_result.delta_source

                                    # Filter by delta
                                    if est_delta < delta_min or est_delta > delta_max:
                                        return None

                                    close_price = r.get("c", 0)
                                    if close_price <= 0:
                                        return None

                                    # Calculate intrinsic and extrinsic value
                                    intrinsic = max(0, current_price - strike)
                                    extrinsic = close_price - intrinsic
                                    itm_moneyness = (
                                        current_price - float(strike)) / current_price

                                    return {
                                        "contract_ticker": ticker,
                                        "symbol": symbol,
                                        "strike": float(strike),
                                        "expiry": expiry,
                                        "dte": dte,
                                        "premium": round(close_price, 2),
                                        # Greeks (Black-Scholes with proxy sigma)
                                        "delta": round(est_delta, 4),
                                        "delta_source": delta_source,
                                        "gamma": greeks_result.gamma,
                                        "theta": greeks_result.theta,
                                        "vega": greeks_result.vega,
                                        # IV (not available from Polygon basic)
                                        "iv": 0.0,
                                        "iv_pct": 0.0,
                                        # Other metrics
                                        "intrinsic": round(intrinsic, 2),
                                        "extrinsic": round(extrinsic, 2),
                                        "itm_pct": round(itm_moneyness * 100, 1),
                                        "volume": r.get("v", 0),
                                        "open_interest": 0
                                    }
                        except Exception as e:
                            logger.debug(
                                f"Error fetching LEAP price for {ticker}: {e}")
                        return None

                tasks = [fetch_leap_price(c) for c in contracts[:30]]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                leaps = [
                    r for r in results if r and not isinstance(r, Exception)]

                # Sort by DTE (prefer longer) and delta (prefer higher)
                leaps.sort(key=lambda x: (x["dte"], x["delta"]), reverse=True)

                return leaps

        except Exception as e:
            logger.error(f"Error fetching LEAPS for {symbol}: {e}")
            return []

    async def run_pmcc_scan(
        self,
        risk_profile: str = "conservative",
        snapshots: Optional[Dict[str, Dict]] = None
    ) -> List[Dict[str, Any]]:
        """
        Run a PMCC (Poor Man's Covered Call) scan for the given risk profile.

        CACHE-ONLY (February 2026):
        - Reads leaps_calls and short_calls from MongoDB daily_snapshots.
        - snapshots dict passed in from run_all_scans (loaded once).
        - Falls back to loading from DB if called standalone.

        PMCC structure:
        - Long Call (LEAPS): Deep ITM, high delta, long DTE
        - Short Call: OTM, lower delta, shorter DTE

        SCAN TIMEOUT FIX (December 2025):
        - Uses bounded concurrency via semaphore
        - Applies timeout/retry to each symbol fetch
        - Continues on partial failure (logs failed symbols)
        - Aggregates success/timeout/error counts

        Returns ranked list of PMCC opportunities.
        """
        cc_profile = RISK_PROFILES.get(
            risk_profile, RISK_PROFILES["conservative"])
        pmcc_profile = PMCC_PROFILES.get(
            risk_profile, PMCC_PROFILES["conservative"])
        run_id = f"pmcc_{risk_profile}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

        logger.info(f"Starting {risk_profile} PMCC scan (run_id={run_id})...")
        logger.info(
            f"Resilience config: concurrency={YAHOO_SCAN_MAX_CONCURRENCY}, timeout={YAHOO_TIMEOUT_SECONDS}s, retries={YAHOO_MAX_RETRIES}")

        # ── Load snapshots from MongoDB if not passed in ──────────────
        if snapshots is None:
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            raw_snaps = await self.db.daily_snapshots.find(
                {"snapshot_date": today_str}
            ).to_list(length=5000)
            snapshots = {s["symbol"]: s for s in raw_snaps}

        if not snapshots:
            logger.error(f"PMCC scan ({risk_profile}): no snapshots available")
            return []

        # Get symbol universe — limited to symbols present in snapshots
        all_symbols = await self.get_liquid_symbols()
        symbols = [s for s in all_symbols if s in snapshots]
        logger.info(f"Scanning {len(symbols)} symbols for {risk_profile} PMCC ({len(snapshots)} snapshots available)")

        # Initialize resilient fetcher for this scan
        fetcher = ResilientYahooFetcher(
            scan_type=f"pmcc_{risk_profile}", run_id=run_id)
        fetcher.set_total_symbols(len(symbols))

        opportunities = []
        pmcc_debug = RejectStats(sample_limit=5)
        stats = {
            "total_symbols": len(symbols),
            "passed_technical": 0,
            "passed_fundamental": 0,
            "has_leaps": 0,
            "has_short_call": 0,
        }

        # Process symbols in batches with bounded concurrency
        batch_size = 10
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]

            # Fetch technical and fundamental data with resilience
            tech_results = []
            fund_results = []

            for symbol in batch:
                # Technical data fetch with resilience
                tech_data = await fetcher.fetch(
                    symbol,  # For logging
                    self.fetch_technical_data,
                    symbol
                )
                tech_results.append(tech_data)

                # ================================================================
                # ETF HANDLING: Skip fundamental fetch for ETFs (same as CC scan)
                # ================================================================
                if is_etf(symbol):
                    fund_results.append(
                        {"symbol": symbol, "is_etf": True, "fundamentals_skipped": True})
                    logger.debug(
                        f"PMCC_ETF_FUNDAMENTALS_SKIPPED | symbol={symbol}")
                else:
                    # Fundamental data fetch with resilience
                    fund_data = await fetcher.fetch(
                        symbol,  # For logging
                        self.fetch_fundamental_data,
                        symbol
                    )
                    fund_results.append(fund_data)

            for j, symbol in enumerate(batch):
                pmcc_debug.total += 1
                tech_data = tech_results[j]
                fund_data = fund_results[j]
                symbol_is_etf = is_etf(symbol)

                # Handle fetch failures gracefully
                if tech_data is None:
                    pmcc_debug.reject("fetch_failed_technical", {
                                      "symbol": symbol})
                    continue

                # Apply technical filters (same as covered call)
                tech_pass, _ = self.passes_technical_filters(
                    tech_data, cc_profile)
                if not tech_pass:
                    pmcc_debug.reject("fails_technical_filters", {
                                      "symbol": symbol, "close": tech_data.get("close")})
                    continue
                stats["passed_technical"] += 1

                # ================================================================
                # ETF HANDLING: Skip fundamental filters for ETFs
                # ================================================================
                if symbol_is_etf:
                    # ETF: Auto-pass fundamentals
                    stats["passed_fundamental"] += 1
                    logger.debug(
                        f"PMCC_ETF_FUNDAMENTALS_BYPASSED | symbol={symbol}")
                else:
                    # Stock: Apply fundamental filters
                    # Handle fundamental fetch failure
                    if fund_data is None:
                        pmcc_debug.reject("fetch_failed_fundamental", {
                                          "symbol": symbol})
                        continue

                    # Apply fundamental filters
                    fund_pass, _ = self.passes_fundamental_filters(
                        fund_data, cc_profile)
                    if not fund_pass:
                        pmcc_debug.reject("fails_fundamental_filters", {
                                          "symbol": symbol})
                        continue
                    stats["passed_fundamental"] += 1

                current_price = tech_data.get("close", 0)
                if current_price <= 0:
                    pmcc_debug.reject("missing_underlying_price", {
                                      "symbol": symbol, "close": current_price})
                    continue

                # ── Read LEAPS and short calls from snapshot (NO Yahoo call) ──
                snap = snapshots.get(symbol, {})

                # Build leaps list from snapshot leaps_calls
                raw_leaps = snap.get("leaps_calls", [])
                leaps = []
                for l in raw_leaps:
                    ask = l.get("ask", 0) or 0
                    if ask <= 0:
                        continue
                    oi = l.get("open_interest", 0) or 0
                    dte = l.get("dte", 0)
                    if not (pmcc_profile.get("long_dte_min", 365) <= dte <= pmcc_profile.get("long_dte_max", 730)):
                        continue
                    leaps.append({
                        "strike": l.get("strike", 0),
                        "expiry": l.get("expiry", ""),
                        "dte": dte,
                        "premium": round(ask, 2),  # ASK for BUY leg
                        "delta": l.get("delta", 0),
                        "open_interest": oi,
                        "itm_pct": l.get("itm_pct", 0),
                        "iv": l.get("iv", 0),
                        "iv_pct": l.get("iv_pct", 0),
                    })

                if not leaps:
                    pmcc_debug.reject(
                        "no_leaps", {"symbol": symbol, "price": current_price})
                    continue
                stats["has_leaps"] += 1

                # Build short_calls list from snapshot short_calls
                raw_shorts = snap.get("short_calls", [])
                short_calls = []
                for s in raw_shorts:
                    bid = s.get("bid", 0) or 0
                    if bid <= 0:
                        continue
                    oi = s.get("open_interest", 0) or 0
                    dte = s.get("dte", 0)
                    if not (pmcc_profile.get("short_dte_min", 20) <= dte <= pmcc_profile.get("short_dte_max", 45)):
                        continue
                    short_calls.append({
                        "strike": s.get("strike", 0),
                        "expiry": s.get("expiry", ""),
                        "dte": dte,
                        "premium": round(bid, 2),  # BID for SELL leg
                        "delta": s.get("delta", 0),
                        "open_interest": oi,
                        "iv": s.get("iv", 0),
                        "iv_pct": s.get("iv_pct", 0),
                    })

                if not short_calls:
                    pmcc_debug.reject("no_short_calls", {
                                      "symbol": symbol, "price": current_price})
                    continue
                stats["has_short_call"] += 1

                # Find best LEAP and short call combination
                best_leap = leaps[0]  # Already sorted by quality in snapshot
                best_short = max(
                    short_calls, key=lambda x: x.get("premium", 0))

                # ============================================================
                # GLOBAL CONSISTENCY: Use shared pricing rules
                # BUY LEAP at ASK, SELL short at BID
                # ============================================================
                leap_ask = best_leap["premium"]   # LEAPS use ASK for BUY
                short_bid = best_short["premium"]  # Short calls use BID for SELL

                # ============================================================
                # MANDATORY SAFETY RULES: Solvency + Break-even
                # These are enforced in precomputed PMCC to match custom PMCC
                # ============================================================
                is_valid, structure_flags = validate_pmcc_structure_rules(
                    long_strike=best_leap["strike"],
                    short_strike=best_short["strike"],
                    leap_ask=leap_ask,
                    short_bid=short_bid
                )

                if not is_valid:
                    # Skip this combination - fails solvency or break-even
                    # Record which rule(s) rejected so "0 results" can be diagnosed quickly.
                    pmcc_debug.reject("pmcc_structure_rejected", {
                                      "symbol": symbol, "flags": structure_flags})
                    try:
                        if isinstance(structure_flags, dict):
                            for k, v in structure_flags.items():
                                if v:
                                    pmcc_debug.reject(f"pmcc_rule_{k}", {
                                                      "symbol": symbol})
                        elif isinstance(structure_flags, (list, tuple, set)):
                            for k in structure_flags:
                                pmcc_debug.reject(f"pmcc_rule_{k}", {
                                                  "symbol": symbol})
                        elif isinstance(structure_flags, str) and structure_flags:
                            pmcc_debug.reject(f"pmcc_rule_{structure_flags}", {
                                              "symbol": symbol})
                    except Exception:
                        pass
                    logger.debug(
                        f"PMCC_STRUCTURE_REJECTED | symbol={symbol} | flags={structure_flags}")
                    continue

                # Use shared economics computation for consistency
                economics = compute_pmcc_economics(
                    long_strike=best_leap["strike"],
                    short_strike=best_short["strike"],
                    leap_ask=leap_ask,
                    short_bid=short_bid,
                    current_price=current_price
                )

                # Extract computed values
                net_debit = economics["net_debit"]
                net_debit_total = economics["net_debit_total"]
                max_profit = economics["max_profit"]
                max_profit_total = economics["max_profit_total"]
                breakeven = economics["breakeven"]
                capital_efficiency = economics["capital_efficiency"] or 0

                # ROI on capital deployed (LEAP cost)
                roi_pct = economics["roi_per_cycle"]

                # Calculate score
                score = 0
                score += min(roi_pct * 5, 30)  # ROI contribution
                score += min(capital_efficiency * 2, 20)  # Capital efficiency
                # High delta LEAP
                score += 10 if best_leap["delta"] >= 0.70 else 5
                # Low delta short
                score += 10 if best_short["delta"] <= 0.30 else 5

                # Fundamental bonus
                if fund_data.get("eps_ttm", 0) > 0:
                    score += 10
                if fund_data.get("roe", 0) > 0.15:
                    score += 5

                opportunities.append({
                    "symbol": symbol,
                    "stock_price": round(current_price, 2),
                    "risk_profile": risk_profile,
                    "strategy": "pmcc",
                    # Long leg (LEAP) - BUY at ASK
                    "long_strike": best_leap["strike"],
                    "long_expiry": best_leap["expiry"],
                    "long_dte": best_leap["dte"],
                    # ASK price used for BUY
                    "long_premium": round(leap_ask, 2),
                    "long_delta": best_leap["delta"],
                    "long_itm_pct": best_leap.get("itm_pct", 0),
                    # Short leg - SELL at BID
                    "short_strike": best_short["strike"],
                    "short_expiry": best_short["expiry"],
                    "short_dte": best_short["dte"],
                    # BID price used for SELL
                    "short_premium": round(short_bid, 2),
                    "short_delta": best_short["delta"],
                    # Combined metrics (from shared computation)
                    "net_debit": round(net_debit, 2),
                    "net_debit_total": round(net_debit_total, 2),
                    "width": economics["width"],
                    "max_profit": round(max_profit, 2),
                    "max_profit_total": round(max_profit_total, 2),
                    "breakeven": breakeven,
                    "roi_pct": round(roi_pct, 2),
                    "capital_efficiency": round(capital_efficiency, 1),
                    "pricing_rule": economics["pricing_rule"],
                    "score": round(score, 1),
                    # Technical indicators
                    "sma50": tech_data.get("sma50"),
                    "sma200": tech_data.get("sma200"),
                    "rsi14": tech_data.get("rsi14"),
                    "atr_pct": round(tech_data.get("atr_pct", 0) * 100, 2) if tech_data.get("atr_pct") else None,
                    # Fundamental data
                    "market_cap": fund_data.get("market_cap", 0),
                    "eps_ttm": fund_data.get("eps_ttm", 0),
                    "roe": round(fund_data.get("roe", 0) * 100, 1) if fund_data.get("roe") else None,
                    "debt_to_equity": fund_data.get("debt_to_equity"),
                    "days_to_earnings": fund_data.get("days_to_earnings"),
                    "sector": fund_data.get("sector", ""),
                    # Include analyst rating
                    "analyst_rating": fund_data.get("analyst_rating"),
                    "num_analysts": fund_data.get("num_analysts", 0),
                    "target_price": fund_data.get("target_price"),
                })
                pmcc_debug.keep()

            # Inter-batch delay
            await asyncio.sleep(1.0)

        # Log resilient fetch stats
        scan_stats = fetcher.get_stats()
        scan_stats.log_summary()

        # ============================================================
        # PHASE 3: AI-BASED BEST OPTION SELECTION PER SYMBOL (PMCC)
        # ============================================================
        symbol_best = {}
        for opp in opportunities:
            symbol = opp["symbol"]
            if symbol not in symbol_best or opp["score"] > symbol_best[symbol]["score"]:
                symbol_best[symbol] = opp

        opportunities = list(symbol_best.values())
        opportunities.sort(key=lambda x: x["score"], reverse=True)
        opportunities = opportunities[:50]

        logger.info(
            f"PMCC scan complete: {len(opportunities)} opportunities found")
        logger.info(f"Stats: {stats['passed_technical']} passed tech, "
                    f"{stats['passed_fundamental']} passed fund, "
                    f"{stats['has_leaps']} had LEAPS, "
                    f"{stats['has_short_call']} had short calls")
        pmcc_debug.log(logger_obj=logger, prefix=f"PMCC_DEBUG_{risk_profile}")

        return opportunities