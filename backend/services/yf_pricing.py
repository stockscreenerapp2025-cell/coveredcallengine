"""
YFinance Pricing Helpers - Single Source of Truth
==================================================
GLOBAL CONSISTENCY REQUIREMENT (Feb 2026)

This module provides the SINGLE SOURCE OF TRUTH for all yfinance data retrieval:
1. Underlying stock price
2. Option chain data

ALL modules MUST use these helpers - no direct yfinance calls for pricing.

MODULES THAT MUST USE THESE HELPERS:
- Dashboard
- CC scan endpoints  
- PMCC scan endpoints
- Customised scans
- eod_pipeline.py
- precomputed_scans.py
- Simulator
- Watchlist

PRICING RULES (enforced here, identical everywhere):
- BUY option price = ask
- SELL option price = bid
- No midpoint, averaging, or fallback pricing
"""

import logging
from datetime import datetime, timezone
from typing import Tuple, Optional, Dict, Any, Literal
import yfinance as yf
import pandas as pd

# Import market state from data_provider (single source of truth)
from services.data_provider import get_market_state, is_market_closed

logger = logging.getLogger(__name__)

# Type alias for market state
MarketState = Literal["OPEN", "EXTENDED", "CLOSED"]

# =============================================================================
# UNDERLYING PRICE HELPER - MANDATORY FOR ALL MODULES
# =============================================================================

def get_underlying_price_yf(
    symbol: str,
    market_state: MarketState = None
) -> Tuple[Optional[float], str, Optional[str]]:
    """
    Get underlying stock price using consistent yfinance fields.
    
    THIS IS THE ONLY FUNCTION TO USE FOR UNDERLYING PRICE.
    All modules (Dashboard, CC, PMCC, Customised, Precomputed, Simulator, Watchlist)
    MUST call this function - no direct yfinance calls for price.
    
    PRICING RULES (NON-NEGOTIABLE):
    ===============================
    When market_state == OPEN:
        Use LIVE LAST from:
        1. ticker.fast_info["last_price"] (primary)
        2. ticker.info["regularMarketPrice"] (fallback)
        
        FORBIDDEN: postMarketPrice, preMarketPrice, currentPrice
        
    When market_state == CLOSED or EXTENDED:
        Use EOD CLOSE from:
        ticker.history(period="5d", interval="1d")["Close"].iloc[-1]
        
        FORBIDDEN: regularMarketPrice (can be stale/after-hours)
        FORBIDDEN: regularMarketPreviousClose (that's prior day, not EOD)
    
    Args:
        symbol: Stock ticker symbol
        market_state: Current market state (OPEN/EXTENDED/CLOSED)
                     If None, will be determined automatically
    
    Returns:
        Tuple of:
        - underlying_price: The stock price (or None if failed)
        - underlying_price_field_used: Which yfinance field was used
        - underlying_price_time: Timestamp of the price (ISO format or None)
    """
    if market_state is None:
        market_state = get_market_state()
    
    try:
        ticker = yf.Ticker(symbol)
        
        if market_state == "OPEN":
            # LIVE LAST: Use fast_info.last_price or fallback to info.regularMarketPrice
            return _get_live_price(ticker, symbol)
        else:
            # EOD CLOSE: Use history Close[-1]
            return _get_eod_close_price(ticker, symbol)
            
    except Exception as e:
        logger.error(f"[YF_PRICING] Failed to get price for {symbol}: {e}")
        return None, "ERROR", None


def _get_live_price(ticker: yf.Ticker, symbol: str) -> Tuple[Optional[float], str, Optional[str]]:
    """
    Get LIVE price when market is OPEN.
    
    Priority:
    1. fast_info["last_price"]
    2. info["regularMarketPrice"] (fallback)
    """
    price = None
    field_used = "NONE"
    price_time = None
    
    # Try fast_info first (preferred for live data)
    try:
        fast_info = ticker.fast_info
        if fast_info and "last_price" in fast_info:
            last_price = fast_info.get("last_price")
            if last_price is not None and last_price > 0:
                price = float(last_price)
                field_used = "fast_info.last_price"
                
                # Get timestamp if available
                last_price_time = fast_info.get("last_price_time")
                if last_price_time:
                    try:
                        if isinstance(last_price_time, (int, float)):
                            price_time = datetime.fromtimestamp(last_price_time, tz=timezone.utc).isoformat()
                        else:
                            price_time = str(last_price_time)
                    except Exception:
                        pass
                
                logger.debug(f"[YF_PRICING] {symbol} OPEN: {field_used}={price}")
                return price, field_used, price_time
    except Exception as e:
        logger.debug(f"[YF_PRICING] {symbol}: fast_info failed: {e}")
    
    # Fallback to info.regularMarketPrice
    try:
        info = ticker.info
        if info:
            reg_price = info.get("regularMarketPrice")
            if reg_price is not None and reg_price > 0:
                price = float(reg_price)
                field_used = "info.regularMarketPrice"
                
                # Get timestamp
                reg_time = info.get("regularMarketTime")
                if reg_time:
                    try:
                        price_time = datetime.fromtimestamp(reg_time, tz=timezone.utc).isoformat()
                    except Exception:
                        pass
                
                logger.debug(f"[YF_PRICING] {symbol} OPEN (fallback): {field_used}={price}")
                return price, field_used, price_time
    except Exception as e:
        logger.debug(f"[YF_PRICING] {symbol}: info fallback failed: {e}")
    
    logger.warning(f"[YF_PRICING] {symbol} OPEN: No valid price found")
    return None, "NONE", None


def _get_eod_close_price(ticker: yf.Ticker, symbol: str) -> Tuple[Optional[float], str, Optional[str]]:
    """
    Get EOD CLOSE price when market is CLOSED or EXTENDED.
    
    Uses: history(period="5d", interval="1d")["Close"].iloc[-1]
    
    FORBIDDEN: regularMarketPrice (can be stale/after-hours)
    FORBIDDEN: regularMarketPreviousClose (that's prior day close)
    """
    try:
        hist = ticker.history(period="5d", interval="1d")
        
        if hist.empty or len(hist) == 0:
            logger.warning(f"[YF_PRICING] {symbol} CLOSED: No history data")
            return None, "NONE", None
        
        # Get the last row (most recent trading day)
        last_row = hist.iloc[-1]
        close_price = last_row.get("Close")
        
        if close_price is None or pd.isna(close_price) or close_price <= 0:
            logger.warning(f"[YF_PRICING] {symbol} CLOSED: Invalid Close price")
            return None, "NONE", None
        
        price = float(close_price)
        field_used = "history.Close[-1]"
        
        # Get timestamp from index (last trading day)
        price_time = None
        try:
            last_date = hist.index[-1]
            if hasattr(last_date, 'isoformat'):
                price_time = last_date.isoformat()
            elif hasattr(last_date, 'strftime'):
                price_time = last_date.strftime("%Y-%m-%dT%H:%M:%S")
            else:
                price_time = str(last_date)
        except Exception:
            pass
        
        logger.debug(f"[YF_PRICING] {symbol} CLOSED: {field_used}={price}")
        return price, field_used, price_time
        
    except Exception as e:
        logger.error(f"[YF_PRICING] {symbol} CLOSED: history failed: {e}")
        return None, "NONE", None


# =============================================================================
# OPTION CHAIN HELPER - MANDATORY FOR ALL MODULES
# =============================================================================

def get_option_chain_yf(
    symbol: str,
    expiry: str
) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame], Dict[str, Any]]:
    """
    Get option chain using consistent yfinance fields.
    
    THIS IS THE ONLY FUNCTION TO USE FOR OPTION CHAIN DATA.
    All modules (CC, PMCC, Customised, Precomputed)
    MUST call this function - no direct yfinance option_chain calls.
    
    REQUIRED COLUMNS (used for pricing/filters):
    ============================================
    - bid: BID price (used for SELL)
    - ask: ASK price (used for BUY)
    - openInterest: Open interest
    - volume: Trading volume
    - impliedVolatility: IV
    - lastTradeDate: Last trade timestamp
    - strike: Strike price
    
    PRICING RULES (NON-NEGOTIABLE):
    ===============================
    - BUY option price = ask
    - SELL option price = bid
    
    Args:
        symbol: Stock ticker symbol
        expiry: Expiration date in YYYY-MM-DD format
    
    Returns:
        Tuple of:
        - calls_df: DataFrame with call options (or None if failed)
        - puts_df: DataFrame with put options (or None if failed)
        - chain_meta: Metadata dict with expiry, symbol, fetch_time
    """
    chain_meta = {
        "symbol": symbol,
        "expiry": expiry,
        "fetch_time": datetime.now(timezone.utc).isoformat(),
        "success": False,
        "error": None
    }
    
    try:
        ticker = yf.Ticker(symbol)
        opt_chain = ticker.option_chain(expiry)
        
        calls_df = opt_chain.calls
        puts_df = opt_chain.puts
        
        # Validate required columns exist
        required_columns = ["bid", "ask", "openInterest", "strike"]
        
        for col in required_columns:
            if col not in calls_df.columns:
                logger.warning(f"[YF_CHAIN] {symbol} {expiry}: Missing column {col} in calls")
            if col not in puts_df.columns:
                logger.warning(f"[YF_CHAIN] {symbol} {expiry}: Missing column {col} in puts")
        
        chain_meta["success"] = True
        chain_meta["calls_count"] = len(calls_df)
        chain_meta["puts_count"] = len(puts_df)
        
        logger.debug(f"[YF_CHAIN] {symbol} {expiry}: {len(calls_df)} calls, {len(puts_df)} puts")
        
        return calls_df, puts_df, chain_meta
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"[YF_CHAIN] {symbol} {expiry}: Failed: {error_msg}")
        chain_meta["error"] = error_msg[:200]
        return None, None, chain_meta


def get_all_expirations_yf(symbol: str) -> Tuple[list, Dict[str, Any]]:
    """
    Get all available expiration dates for a symbol.
    
    Args:
        symbol: Stock ticker symbol
    
    Returns:
        Tuple of:
        - expirations: List of expiration dates (YYYY-MM-DD strings)
        - meta: Metadata dict
    """
    meta = {
        "symbol": symbol,
        "fetch_time": datetime.now(timezone.utc).isoformat(),
        "success": False,
        "error": None
    }
    
    try:
        ticker = yf.Ticker(symbol)
        expirations = list(ticker.options)
        
        meta["success"] = True
        meta["count"] = len(expirations)
        
        logger.debug(f"[YF_EXPIRY] {symbol}: {len(expirations)} expirations")
        return expirations, meta
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"[YF_EXPIRY] {symbol}: Failed: {error_msg}")
        meta["error"] = error_msg[:200]
        return [], meta


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def extract_option_price_for_sell(row: pd.Series) -> Tuple[Optional[float], str]:
    """
    Extract SELL price from option chain row.
    SELL = bid (no alternatives)
    
    Args:
        row: A row from calls_df or puts_df
    
    Returns:
        Tuple of (price, pricing_rule)
    """
    bid = row.get("bid", 0)
    if bid is None or pd.isna(bid) or bid <= 0:
        return None, "INVALID_BID"
    return float(bid), "SELL_BID"


def extract_option_price_for_buy(row: pd.Series) -> Tuple[Optional[float], str]:
    """
    Extract BUY price from option chain row.
    BUY = ask (no alternatives)
    
    Args:
        row: A row from calls_df or puts_df
    
    Returns:
        Tuple of (price, pricing_rule)
    """
    ask = row.get("ask", 0)
    if ask is None or pd.isna(ask) or ask <= 0:
        return None, "INVALID_ASK"
    return float(ask), "BUY_ASK"


def extract_chain_row_data(row: pd.Series) -> Dict[str, Any]:
    """
    Extract standardized data from an option chain row.
    
    This ensures all modules use the same field names and extraction logic.
    
    Args:
        row: A row from calls_df or puts_df
    
    Returns:
        Dict with standardized option data
    """
    return {
        "strike": float(row.get("strike", 0)),
        "bid": float(row.get("bid", 0)) if pd.notna(row.get("bid")) else 0,
        "ask": float(row.get("ask", 0)) if pd.notna(row.get("ask")) else 0,
        "last_price": float(row.get("lastPrice", 0)) if pd.notna(row.get("lastPrice")) else 0,
        "open_interest": int(row.get("openInterest", 0)) if pd.notna(row.get("openInterest")) else 0,
        "volume": int(row.get("volume", 0)) if pd.notna(row.get("volume")) else 0,
        "implied_volatility": float(row.get("impliedVolatility", 0)) if pd.notna(row.get("impliedVolatility")) else 0,
        "last_trade_date": str(row.get("lastTradeDate", "")) if pd.notna(row.get("lastTradeDate")) else None,
        "contract_symbol": str(row.get("contractSymbol", "")) if pd.notna(row.get("contractSymbol")) else None,
        "in_the_money": bool(row.get("inTheMoney", False)) if pd.notna(row.get("inTheMoney")) else False
    }


# =============================================================================
# BULK OPERATIONS (for efficiency in scans)
# =============================================================================

def get_underlying_prices_bulk_yf(
    symbols: list,
    market_state: MarketState = None
) -> Dict[str, Dict[str, Any]]:
    """
    Get underlying prices for multiple symbols.
    
    Uses yf.download() for efficiency when fetching many symbols.
    Falls back to individual calls if bulk fails.
    
    Args:
        symbols: List of ticker symbols
        market_state: Current market state
    
    Returns:
        Dict mapping symbol -> {price, field_used, price_time, success}
    """
    if market_state is None:
        market_state = get_market_state()
    
    results = {}
    
    if market_state == "OPEN":
        # For OPEN market, use individual calls (fast_info is symbol-specific)
        for symbol in symbols:
            price, field_used, price_time = get_underlying_price_yf(symbol, market_state)
            results[symbol] = {
                "price": price,
                "field_used": field_used,
                "price_time": price_time,
                "success": price is not None
            }
    else:
        # For CLOSED market, use bulk download for efficiency
        try:
            logger.info(f"[YF_PRICING_BULK] Downloading {len(symbols)} symbols for CLOSED market")
            
            df = yf.download(
                tickers=symbols,
                period="5d",
                interval="1d",
                group_by="ticker",
                auto_adjust=False,
                progress=False,
                threads=False
            )
            
            for symbol in symbols:
                try:
                    if len(symbols) == 1:
                        symbol_df = df
                    else:
                        if symbol not in df.columns.get_level_values(0):
                            results[symbol] = {
                                "price": None,
                                "field_used": "NONE",
                                "price_time": None,
                                "success": False
                            }
                            continue
                        symbol_df = df[symbol]
                    
                    if symbol_df.empty or len(symbol_df) == 0:
                        results[symbol] = {
                            "price": None,
                            "field_used": "NONE", 
                            "price_time": None,
                            "success": False
                        }
                        continue
                    
                    last_row = symbol_df.iloc[-1]
                    close_price = last_row.get("Close")
                    
                    if close_price is None or pd.isna(close_price) or close_price <= 0:
                        results[symbol] = {
                            "price": None,
                            "field_used": "NONE",
                            "price_time": None,
                            "success": False
                        }
                        continue
                    
                    price_time = None
                    try:
                        last_date = symbol_df.index[-1]
                        if hasattr(last_date, 'isoformat'):
                            price_time = last_date.isoformat()
                        else:
                            price_time = str(last_date)
                    except Exception:
                        pass
                    
                    results[symbol] = {
                        "price": float(close_price),
                        "field_used": "history.Close[-1]",
                        "price_time": price_time,
                        "success": True
                    }
                    
                except Exception as e:
                    logger.debug(f"[YF_PRICING_BULK] {symbol}: Parse error: {e}")
                    results[symbol] = {
                        "price": None,
                        "field_used": "NONE",
                        "price_time": None,
                        "success": False
                    }
                    
        except Exception as e:
            logger.warning(f"[YF_PRICING_BULK] Bulk download failed: {e}, falling back to individual")
            # Fallback to individual calls
            for symbol in symbols:
                price, field_used, price_time = get_underlying_price_yf(symbol, market_state)
                results[symbol] = {
                    "price": price,
                    "field_used": field_used,
                    "price_time": price_time,
                    "success": price is not None
                }
    
    return results
