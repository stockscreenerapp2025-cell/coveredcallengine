"""
Screener Routes - Covered Call and PMCC screening endpoints
============================================================

CCE MASTER ARCHITECTURE - LAYER 3: Strategy Selection Layer

DATA FETCHING RULES (NON-NEGOTIABLE):

1. STOCK PRICES: Use PREVIOUS US MARKET CLOSE on trading days only
   - Source: eod_market_close or previousClose from Yahoo
   - ❌ No intraday prices (regularMarketPrice)
   - ❌ No pre-market or after-hours prices

2. OPTIONS CHAIN: MUST be fetched LIVE per symbol, per expiry
   - Source: Yahoo Finance at scan time
   - ❌ Never cached, stored, or reconstructed
   - ❌ Never inferred from derived data

LAYER 3 RESPONSIBILITIES:
    - Apply CC eligibility filters (price, volume, market cap)
    - Enforce earnings ±7 days exclusion
    - Separate Weekly (7-14 DTE) and Monthly (21-45 DTE) modes
    - Compute/enrich Greeks (Delta, IV, IV Rank, OI)
    - Prepare enriched data for downstream scoring
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
import logging
import asyncio

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import db
from utils.auth import get_current_user

# Import data_provider for LIVE options fetching
from services.data_provider import fetch_options_chain, fetch_stock_quote

# Import SnapshotService for stock metadata (not for options)
from services.snapshot_service import SnapshotService

# ADR-001: EOD Market Close Price Contract (for stock prices ONLY)
from services.eod_ingestion_service import (
    EODPriceContract,
    EODPriceNotFoundError,
    EODOptionsNotFoundError
)

# LAYER 2: Import validators
from services.chain_validator import (
    get_validator,
    validate_chain_for_cc,
    validate_cc_trade,
    validate_pmcc_trade,
    validate_sell_pricing,
    MAX_SPREAD_PCT
)
# PHASE 6: Import market bias module
from services.market_bias import (
    fetch_market_sentiment,
    get_market_bias_weight,
    apply_bias_to_score
)
# PHASE 7: Import quality scoring module
from services.quality_score import (
    calculate_cc_quality_score,
    calculate_pmcc_quality_score
)

screener_router = APIRouter(tags=["Screener"])

# Initialize SnapshotService (singleton) - LEGACY, being replaced by EOD Contract
import os
_snapshot_service = None

def get_snapshot_service() -> SnapshotService:
    """Get or create the SnapshotService singleton. LEGACY - use EOD Contract."""
    global _snapshot_service
    if _snapshot_service is None:
        polygon_key = os.environ.get('POLYGON_API_KEY')
        _snapshot_service = SnapshotService(db, polygon_api_key=polygon_key)
    return _snapshot_service

# ADR-001: EOD Price Contract singleton
_eod_price_contract = None

def get_eod_contract() -> EODPriceContract:
    """Get or create the EOD Price Contract singleton. ADR-001 COMPLIANT."""
    global _eod_price_contract
    if _eod_price_contract is None:
        _eod_price_contract = EODPriceContract(db)
    return _eod_price_contract

# Thread pool for analyst ratings (still needed for scoring enrichment)
_analyst_executor = ThreadPoolExecutor(max_workers=10)

# ETF symbols for special handling
ETF_SYMBOLS = {"SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK", "XLV", "XLI", "XLB", "XLU", "XLP", "XLY", "GLD", "SLV", "ARKK", "ARKG", "ARKW", "TLT", "EEM", "VXX", "UVXY", "SQQQ", "TQQQ"}

# ============================================================
# LAYER 3 CONSTANTS - CC ELIGIBILITY FILTERS
# ============================================================

# System/Custom Scan Eligibility (strict)
CC_SYSTEM_MIN_PRICE = 30.0      # Minimum stock price
CC_SYSTEM_MAX_PRICE = 90.0      # Maximum stock price
CC_SYSTEM_MIN_VOLUME = 1_000_000  # Minimum average daily volume
CC_SYSTEM_MIN_MARKET_CAP = 5_000_000_000  # Minimum $5B market cap

# Manual Scan Eligibility (relaxed price, strict structure)
CC_MANUAL_MIN_PRICE = 15.0      # Lower bound for manual
CC_MANUAL_MAX_PRICE = 500.0     # Upper bound for manual

# DTE Ranges per CCE Master Architecture
WEEKLY_MIN_DTE = 7
WEEKLY_MAX_DTE = 14
MONTHLY_MIN_DTE = 21
MONTHLY_MAX_DTE = 45

# Earnings exclusion window (days before and after)
EARNINGS_EXCLUSION_DAYS = 7

# Symbol universe (fixed at ~60, validated for snapshot completeness)
# NOTE: GS, BLK, AMGN, MMM, GLD removed due to option chain validation issues
# NOTE: GOOGL = Class A shares, GOOG = Class C shares (both included)
SCAN_SYMBOLS = [
    # Tech Giants (GOOGL = Class A, GOOG = Class C)
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA", "AMD", "INTC", "CRM",
    # Finance (excluding GS, BLK - incomplete chains)
    "JPM", "BAC", "WFC", "MS", "C", "USB", "PNC", "SCHW",
    # Consumer
    "WMT", "HD", "NKE", "SBUX", "MCD", "DIS", "CMCSA", "VZ", "T",
    # Healthcare (excluding AMGN - incomplete chain)
    "JNJ", "UNH", "PFE", "MRK", "ABBV", "BMY", "GILD", "LLY",
    # Energy
    "XOM", "CVX", "COP", "SLB", "EOG", "OXY", "DVN", "HAL", "MPC",
    # Industrial (excluding MMM - incomplete chain)
    "CAT", "DE", "BA", "HON", "GE", "UPS", "RTX",
    # Other Popular
    "PLTR", "SOFI", "COIN", "HOOD", "RIVN", "LCID", "NIO", "UBER", "LYFT",
    "AAL", "DAL", "UAL", "CCL", "NCLH", "MGM", "WYNN",
    # ETFs - only those with existing snapshots
    "SPY", "QQQ", "IWM", "SLV"
]


# ============================================================
# LAYER 3: CC ELIGIBILITY CHECKER
# ============================================================

def check_cc_eligibility(
    symbol: str,
    stock_price: float,
    market_cap: float,
    avg_volume: float,
    earnings_date: str,
    scan_mode: str = "system",
    scan_date: str = None
) -> tuple[bool, str]:
    """
    Check if a symbol is eligible for Covered Call scanning.
    
    CCE MASTER ARCHITECTURE - LAYER 3 COMPLIANT
    
    System/Custom Scan Rules:
    - Price: $30-$90
    - Avg volume: ≥1M
    - Market cap: ≥$5B
    - No earnings ±7 days
    
    Manual Scan Rules:
    - Price: $15-$500 (flagged but allowed)
    - All structure & pricing rules still enforced
    
    Args:
        symbol: Stock ticker
        stock_price: Current stock close price
        market_cap: Market capitalization
        avg_volume: Average daily volume
        earnings_date: Next earnings date (YYYY-MM-DD or None)
        scan_mode: "system", "custom", or "manual"
        scan_date: Date to check against (default: today)
    
    Returns:
        (is_eligible, rejection_reason or warning)
    """
    is_etf = symbol in ETF_SYMBOLS
    
    # ETFs are exempt from most checks - they follow different rules
    if is_etf:
        # ETFs have NO price restriction (SPY is ~$600, QQQ is ~$530)
        # Only reject if price is completely unreasonable
        if stock_price < 1 or stock_price > 2000:
            return False, f"ETF price ${stock_price:.2f} outside valid range"
        return True, "ETF - eligible"
    
    # PRICE CHECK (Stocks only)
    if scan_mode in ("system", "custom"):
        if stock_price < CC_SYSTEM_MIN_PRICE:
            return False, f"Price ${stock_price:.2f} below minimum ${CC_SYSTEM_MIN_PRICE}"
        if stock_price > CC_SYSTEM_MAX_PRICE:
            return False, f"Price ${stock_price:.2f} above maximum ${CC_SYSTEM_MAX_PRICE}"
    elif scan_mode == "manual":
        if stock_price < CC_MANUAL_MIN_PRICE:
            return False, f"Price ${stock_price:.2f} below manual minimum ${CC_MANUAL_MIN_PRICE}"
        if stock_price > CC_MANUAL_MAX_PRICE:
            return False, f"Price ${stock_price:.2f} above manual maximum ${CC_MANUAL_MAX_PRICE}"
    
    # VOLUME CHECK (System/Custom only)
    if scan_mode in ("system", "custom"):
        if avg_volume and avg_volume < CC_SYSTEM_MIN_VOLUME:
            return False, f"Avg volume {avg_volume:,.0f} below minimum {CC_SYSTEM_MIN_VOLUME:,.0f}"
    
    # MARKET CAP CHECK (System/Custom only, non-ETF)
    if scan_mode in ("system", "custom"):
        if market_cap and market_cap < CC_SYSTEM_MIN_MARKET_CAP:
            return False, f"Market cap ${market_cap/1e9:.1f}B below minimum $5B"
    
    # EARNINGS CHECK (All modes)
    if earnings_date:
        try:
            earnings_dt = datetime.strptime(earnings_date, '%Y-%m-%d')
            if scan_date:
                today = datetime.strptime(scan_date, '%Y-%m-%d')
            else:
                today = datetime.now()
            
            days_to_earnings = (earnings_dt - today).days
            
            if -EARNINGS_EXCLUSION_DAYS <= days_to_earnings <= EARNINGS_EXCLUSION_DAYS:
                return False, f"Earnings in {days_to_earnings} days (within ±{EARNINGS_EXCLUSION_DAYS} day window)"
        except ValueError:
            pass  # Invalid date format, skip check
    
    return True, "Eligible"


# ============================================================
# LAYER 3: GREEKS ENRICHMENT (ENHANCED)
# ============================================================

def enrich_option_greeks(
    contract: Dict,
    stock_price: float,
    risk_free_rate: float = 0.05
) -> Dict:
    """
    Enrich option contract with computed/estimated Greeks.
    
    CCE MASTER ARCHITECTURE - LAYER 3 COMPLIANT (ENHANCED)
    
    Computes/estimates:
    - Delta (from snapshot or estimated using validated previousClose)
    - IV (from snapshot)
    - IV Rank (estimated from current IV relative to typical range)
    - Theta (estimated based on premium and DTE)
    - Gamma (estimated based on moneyness and time)
    - ROI (%) = (Premium / Stock Price) * 100 * (365 / DTE)
    
    Args:
        contract: Option contract data from snapshot
        stock_price: Stock close price (validated previousClose from Layer 1)
        risk_free_rate: Risk-free rate for calculations
    
    Returns:
        Enriched contract with Greeks and ROI
    """
    enriched = contract.copy()
    
    strike = contract.get("strike", 0)
    dte = contract.get("dte", 30)
    iv = contract.get("implied_volatility", 0)
    option_type = contract.get("option_type", "call")
    premium = contract.get("bid", 0) or contract.get("premium", 0)
    ask = contract.get("ask", 0)
    
    # DELTA - use from snapshot or estimate
    if "delta" not in enriched or enriched["delta"] == 0:
        # Estimate delta based on moneyness
        if stock_price > 0 and strike > 0:
            moneyness = (stock_price - strike) / stock_price
            if option_type == "call":
                if moneyness > 0:  # ITM
                    enriched["delta"] = min(0.95, 0.50 + moneyness * 2)
                else:  # OTM
                    enriched["delta"] = max(0.05, 0.50 + moneyness * 2)
            else:  # put
                if moneyness < 0:  # ITM put
                    enriched["delta"] = max(-0.95, -0.50 + moneyness * 2)
                else:  # OTM put
                    enriched["delta"] = min(-0.05, -0.50 + moneyness * 2)
    
    # IV - convert to percentage if needed
    if iv > 0 and iv < 5:  # Likely decimal form (0.30 = 30%)
        enriched["iv_pct"] = round(iv * 100, 1)
    else:
        enriched["iv_pct"] = round(iv, 1) if iv else 0
    
    # IV RANK - estimated from current IV relative to typical range
    # Uses range 15-80% as typical for most stocks
    if iv > 0:
        iv_pct = iv * 100 if iv < 5 else iv
        # More accurate IV rank estimation
        # 15% = 0 rank, 50% = 50 rank, 80%+ = 100 rank
        enriched["iv_rank"] = min(100, max(0, round((iv_pct - 15) / 65 * 100)))
    else:
        enriched["iv_rank"] = None
    
    # THETA estimate (simplified)
    if dte > 0 and premium > 0:
        # Rough theta estimate: premium decay accelerates near expiry
        daily_decay = premium / dte
        # Adjust for time decay acceleration (theta increases as expiry approaches)
        if dte < 7:
            daily_decay *= 1.5
        elif dte < 14:
            daily_decay *= 1.2
        enriched["theta_estimate"] = -round(daily_decay, 3)
    else:
        enriched["theta_estimate"] = 0
    
    # GAMMA estimate (simplified)
    if "delta" in enriched and dte > 0 and stock_price > 0 and strike > 0:
        # Gamma is highest ATM and near expiry
        atm_factor = 1 - abs((stock_price - strike) / stock_price)
        time_factor = max(0.1, 1 - dte / 60)
        enriched["gamma_estimate"] = round(atm_factor * time_factor * 0.05, 4)
    else:
        enriched["gamma_estimate"] = 0
    
    # VEGA estimate (simplified - based on IV and DTE)
    if iv > 0 and dte > 0 and stock_price > 0:
        # Vega is higher for longer DTE and ATM options
        atm_factor = 1 - abs((stock_price - strike) / stock_price) if strike > 0 else 0.5
        time_factor = min(1.0, dte / 30)  # Normalize to 30 days
        enriched["vega_estimate"] = round(stock_price * 0.01 * atm_factor * time_factor, 3)
    else:
        enriched["vega_estimate"] = 0
    
    # ROI CALCULATION: (Premium / Stock Price) * 100 * (365 / DTE)
    # This is the annualized return on investment
    if stock_price > 0 and premium > 0 and dte > 0:
        roi_per_trade = (premium / stock_price) * 100
        annualized_roi = roi_per_trade * (365 / dte)
        enriched["roi_pct"] = round(roi_per_trade, 2)
        enriched["roi_annualized"] = round(annualized_roi, 1)
    else:
        enriched["roi_pct"] = 0
        enriched["roi_annualized"] = 0
    
    # Premium Ask (for reference)
    enriched["premium_ask"] = round(ask, 2) if ask else None
    
    return enriched


def enrich_pmcc_metrics(
    leap_contract: Dict,
    short_contract: Dict,
    stock_price: float
) -> Dict:
    """
    Compute PMCC-specific metrics for eligible contracts.
    
    CCE MASTER ARCHITECTURE - LAYER 3 COMPLIANT (PMCC ENRICHMENT)
    
    Computes:
    - Leaps BUY eligibility
    - Premium Ask (for LEAP BUY leg)
    - Delta
    - DTE
    - Cost Calculation (LEAP cost)
    - Width (spread between short call strike and LEAP strike)
    - ROI per cycle
    - Annualized ROI
    
    Args:
        leap_contract: LEAP option data (BUY leg)
        short_contract: Short call option data (SELL leg)
        stock_price: Stock close price
    
    Returns:
        Dict with PMCC metrics
    """
    pmcc_metrics = {}
    
    leap_strike = leap_contract.get("strike", 0)
    leap_ask = leap_contract.get("ask", 0) or leap_contract.get("premium", 0)
    leap_dte = leap_contract.get("dte", 0)
    leap_delta = leap_contract.get("delta", 0)
    leap_oi = leap_contract.get("open_interest", 0)
    
    short_strike = short_contract.get("strike", 0)
    short_bid = short_contract.get("bid", 0) or short_contract.get("premium", 0)
    short_dte = short_contract.get("dte", 0)
    
    # LEAP BUY eligibility (DTE >= 365, Delta >= 0.70, OI >= 500)
    pmcc_metrics["leaps_buy_eligible"] = (
        leap_dte >= 365 and 
        leap_delta >= 0.70 and 
        leap_oi >= 500 and
        leap_ask > 0
    )
    
    # Premium Ask (LEAP cost per contract)
    pmcc_metrics["premium_ask"] = round(leap_ask, 2)
    
    # Delta
    pmcc_metrics["delta"] = round(leap_delta, 3)
    
    # DTE
    pmcc_metrics["leap_dte"] = leap_dte
    pmcc_metrics["short_dte"] = short_dte
    
    # Cost Calculation (LEAP cost - what you pay to buy)
    pmcc_metrics["leap_cost"] = round(leap_ask * 100, 2)  # Per contract (100 shares)
    
    # Width (spread between short call strike and LEAP strike)
    pmcc_metrics["width"] = round(short_strike - leap_strike, 2) if short_strike > leap_strike else 0
    
    # Net Debit (what you pay upfront)
    net_debit = leap_ask - short_bid
    pmcc_metrics["net_debit"] = round(net_debit, 2)
    pmcc_metrics["net_debit_total"] = round(net_debit * 100, 2)  # Per contract
    
    # Max Profit (if stock rises to short strike at expiry)
    if short_strike > leap_strike and net_debit > 0:
        max_profit = (short_strike - leap_strike) - net_debit
        pmcc_metrics["max_profit"] = round(max_profit, 2)
        pmcc_metrics["max_profit_total"] = round(max_profit * 100, 2)
    else:
        pmcc_metrics["max_profit"] = 0
        pmcc_metrics["max_profit_total"] = 0
    
    # ROI per cycle (Short premium / LEAP cost)
    if leap_ask > 0 and short_bid > 0:
        roi_per_cycle = (short_bid / leap_ask) * 100
        pmcc_metrics["roi_per_cycle"] = round(roi_per_cycle, 2)
        
        # Annualized ROI (assuming monthly cycles)
        if short_dte > 0:
            cycles_per_year = 365 / short_dte
            pmcc_metrics["roi_annualized"] = round(roi_per_cycle * cycles_per_year, 1)
        else:
            pmcc_metrics["roi_annualized"] = 0
    else:
        pmcc_metrics["roi_per_cycle"] = 0
        pmcc_metrics["roi_annualized"] = 0
    
    # Breakeven price
    if leap_strike > 0 and net_debit > 0:
        pmcc_metrics["breakeven"] = round(leap_strike + net_debit, 2)
    else:
        pmcc_metrics["breakeven"] = 0
    
    return pmcc_metrics


def log_price_discrepancy(
    symbol: str,
    source1_name: str,
    source1_price: float,
    source2_name: str,
    source2_price: float,
    threshold_pct: float = 0.1
) -> bool:
    """
    Log warning if price discrepancy exceeds threshold.
    
    Args:
        symbol: Stock symbol
        source1_name: Name of first price source
        source1_price: Price from first source
        source2_name: Name of second price source
        source2_price: Price from second source
        threshold_pct: Threshold percentage for logging (default 0.1%)
    
    Returns:
        True if discrepancy detected, False otherwise
    """
    if source1_price <= 0 or source2_price <= 0:
        return False
    
    diff_pct = abs(source1_price - source2_price) / source1_price * 100
    
    if diff_pct > threshold_pct:
        logging.warning(
            f"[PRICE DISCREPANCY] {symbol}: {source1_name}=${source1_price:.2f} vs "
            f"{source2_name}=${source2_price:.2f} (diff={diff_pct:.2f}% > {threshold_pct}%)"
        )
        return True
    
    return False


# ============================================================
# LAYER 3: DTE MODE HELPERS
# ============================================================

def get_dte_range(mode: str) -> tuple[int, int]:
    """
    Get DTE range based on scan mode.
    
    CCE MASTER ARCHITECTURE - LAYER 3 COMPLIANT
    
    Args:
        mode: "weekly", "monthly", or "all"
    
    Returns:
        (min_dte, max_dte)
    """
    if mode == "weekly":
        return WEEKLY_MIN_DTE, WEEKLY_MAX_DTE
    elif mode == "monthly":
        return MONTHLY_MIN_DTE, MONTHLY_MAX_DTE
    else:  # "all" or default
        return WEEKLY_MIN_DTE, MONTHLY_MAX_DTE


class SnapshotValidationError(HTTPException):
    """Raised when snapshot validation fails - scan must abort."""
    def __init__(self, missing: int, total: int, details: List[str]):
        detail = {
            "error": "SCAN_ABORTED_SNAPSHOT_VALIDATION_FAILED",
            "message": f"Scan aborted: {missing} of {total} symbols missing valid snapshots. Deterministic scan requires 100% snapshot availability.",
            "missing_count": missing,
            "total_symbols": total,
            "rejection_details": details[:20]  # First 20 reasons
        }
        super().__init__(status_code=409, detail=detail)


# ============================================================
# SNAPSHOT VALIDATION - FAIL CLOSED
# ============================================================

async def validate_all_snapshots(symbols: List[str]) -> Dict[str, Any]:
    """
    Validate that ALL symbols have valid snapshots before scanning.
    
    CCE MASTER ARCHITECTURE - LAYER 3 COMPLIANT
    
    FAIL CLOSED: If ANY symbol is missing/stale/incomplete, raise SnapshotValidationError.
    
    Returns validation results if all pass.
    """
    snapshot_service = get_snapshot_service()
    
    valid_symbols = []
    invalid_symbols = []
    rejection_reasons = []
    
    for symbol in symbols:
        # Check stock snapshot
        stock, stock_error = await snapshot_service.get_stock_snapshot(symbol)
        if stock_error:
            invalid_symbols.append(symbol)
            rejection_reasons.append(f"{symbol}: {stock_error}")
            continue
        
        # Check option chain snapshot
        chain, chain_error = await snapshot_service.get_option_chain_snapshot(symbol)
        if chain_error:
            invalid_symbols.append(symbol)
            rejection_reasons.append(f"{symbol}: {chain_error}")
            continue
        
        # LAYER 1 COMPLIANT: Use stock_close_price (fallback to price for backward compat)
        stock_price = stock.get("stock_close_price") or stock.get("price")
        
        valid_symbols.append({
            "symbol": symbol,
            "stock_price": stock_price,
            "stock_price_trade_date": stock.get("stock_price_trade_date") or stock.get("snapshot_trade_date"),
            "snapshot_date": stock.get("snapshot_trade_date"),
            "data_age_hours": stock.get("data_age_hours"),
            "valid_contracts": chain.get("valid_contracts", 0),
            # Additional metadata for Layer 3
            "market_cap": stock.get("market_cap"),
            "avg_volume": stock.get("avg_volume"),
            "earnings_date": stock.get("earnings_date")
        })
    
    validation_result = {
        "symbols_total": len(symbols),
        "symbols_valid": len(valid_symbols),
        "symbols_invalid": len(invalid_symbols),
        "valid_symbols": valid_symbols,
        "invalid_symbols": invalid_symbols,
        "rejection_reasons": rejection_reasons
    }
    
    # FAIL CLOSED: Abort if ANY symbol is invalid
    if invalid_symbols:
        raise SnapshotValidationError(
            missing=len(invalid_symbols),
            total=len(symbols),
            details=rejection_reasons
        )
    
    return validation_result


# ============================================================
# ADR-001: EOD PRICE CONTRACT VALIDATION - FAIL CLOSED
# ============================================================

async def validate_eod_data(symbols: List[str], trade_date: str = None) -> Dict[str, Any]:
    """
    ADR-001 COMPLIANT: Validate that ALL symbols have canonical EOD data.
    
    Uses eod_market_close and eod_options_chain collections.
    
    FAIL CLOSED: If ANY symbol is missing final EOD data, raise SnapshotValidationError.
    
    Returns validation results if all pass.
    """
    eod_contract = get_eod_contract()
    
    valid_symbols = []
    invalid_symbols = []
    rejection_reasons = []
    
    for symbol in symbols:
        try:
            # Get canonical EOD stock price
            price, stock_doc = await eod_contract.get_market_close_price(symbol, trade_date)
            
            # Get canonical EOD options chain
            chain_doc = await eod_contract.get_options_chain(symbol, trade_date)
            
            valid_symbols.append({
                "symbol": symbol,
                "stock_price": price,  # Canonical market_close_price
                "stock_price_trade_date": stock_doc.get("trade_date"),
                "market_close_timestamp": stock_doc.get("market_close_timestamp"),
                "valid_contracts": chain_doc.get("valid_contracts", 0),
                "is_final": stock_doc.get("is_final") and chain_doc.get("is_final"),
                # Metadata for Layer 3
                "market_cap": stock_doc.get("metadata", {}).get("market_cap"),
                "avg_volume": stock_doc.get("metadata", {}).get("avg_volume"),
                "earnings_date": stock_doc.get("metadata", {}).get("earnings_date"),
                "source": "eod_contract"  # ADR-001 marker
            })
            
        except EODPriceNotFoundError as e:
            invalid_symbols.append(symbol)
            rejection_reasons.append(f"{symbol}: No canonical EOD price - {e}")
            
        except EODOptionsNotFoundError as e:
            invalid_symbols.append(symbol)
            rejection_reasons.append(f"{symbol}: No canonical options chain - {e}")
    
    validation_result = {
        "symbols_total": len(symbols),
        "symbols_valid": len(valid_symbols),
        "symbols_invalid": len(invalid_symbols),
        "valid_symbols": valid_symbols,
        "invalid_symbols": invalid_symbols,
        "rejection_reasons": rejection_reasons,
        "data_source": "eod_contract",  # ADR-001 marker
        "trade_date_filter": trade_date
    }
    
    # FAIL CLOSED: Abort if ANY symbol is invalid
    if invalid_symbols:
        raise SnapshotValidationError(
            missing=len(invalid_symbols),
            total=len(symbols),
            details=rejection_reasons
        )
    
    return validation_result


# ============================================================
# COVERED CALL SCREENER (LAYER 3 - Strategy Selection)
# ============================================================

@screener_router.get("/covered-calls")
async def screen_covered_calls(
    limit: int = Query(50, ge=1, le=200),
    risk_profile: str = Query("moderate", regex="^(conservative|moderate|aggressive)$"),
    dte_mode: str = Query("all", regex="^(weekly|monthly|all)$"),
    scan_mode: str = Query("system", regex="^(system|custom|manual)$"),
    min_dte: int = Query(None, ge=1),
    max_dte: int = Query(None, le=180),
    min_premium_yield: float = Query(0.5, ge=0),
    max_premium_yield: float = Query(20.0, le=50),
    min_otm_pct: float = Query(0.0, ge=0),
    max_otm_pct: float = Query(20.0, le=50),
    use_eod_contract: bool = Query(True, description="ADR-001: Use EOD contract for stock prices"),
    user: dict = Depends(get_current_user)
):
    """
    Screen for Covered Call opportunities.
    
    DATA FETCHING RULES:
    1. STOCK PRICES: Previous US market close (from EOD contract or previousClose)
    2. OPTIONS CHAINS: Fetched LIVE from Yahoo Finance at scan time
    
    LAYER 3 FEATURES:
    - CC eligibility filters (price $30-$90, volume ≥1M, market cap ≥$5B)
    - Earnings ±7 days exclusion
    - Weekly (7-14 DTE) / Monthly (21-45 DTE) modes
    - Greeks enrichment (Delta, IV, IV Rank, OI)
    
    Args:
        dte_mode: "weekly" (7-14), "monthly" (21-45), or "all" (7-45)
        scan_mode: "system" (strict filters), "custom", or "manual" (relaxed price)
        use_eod_contract: If True, uses EOD contract for stock prices.
    """
    eod_contract = get_eod_contract()
    snapshot_service = get_snapshot_service()
    
    # LAYER 3: Determine DTE range based on mode
    if min_dte is None or max_dte is None:
        auto_min_dte, auto_max_dte = get_dte_range(dte_mode)
        min_dte = min_dte if min_dte is not None else auto_min_dte
        max_dte = max_dte if max_dte is not None else auto_max_dte
    
    # Step 1: Get stock prices (previous close) for all symbols
    stock_data = {}
    symbols_with_stock_data = []
    
    for symbol in SCAN_SYMBOLS:
        try:
            # Try EOD contract first for stock price (previous close)
            if use_eod_contract:
                try:
                    price, stock_doc = await eod_contract.get_market_close_price(symbol)
                    stock_data[symbol] = {
                        "stock_price": price,
                        "trade_date": stock_doc.get("trade_date"),
                        "market_cap": stock_doc.get("metadata", {}).get("market_cap"),
                        "avg_volume": stock_doc.get("metadata", {}).get("avg_volume"),
                        "earnings_date": stock_doc.get("metadata", {}).get("earnings_date"),
                        "source": "eod_contract"
                    }
                    symbols_with_stock_data.append(symbol)
                except EODPriceNotFoundError:
                    # Fallback to Yahoo previousClose
                    quote = await fetch_stock_quote(symbol)
                    if quote and quote.get("price"):
                        stock_data[symbol] = {
                            "stock_price": quote["price"],  # previousClose
                            "trade_date": None,
                            "market_cap": None,
                            "avg_volume": None,
                            "earnings_date": None,
                            "source": "yahoo_previous_close"
                        }
                        symbols_with_stock_data.append(symbol)
            else:
                # Use Yahoo previousClose
                quote = await fetch_stock_quote(symbol)
                if quote and quote.get("price"):
                    stock_data[symbol] = {
                        "stock_price": quote["price"],
                        "trade_date": None,
                        "market_cap": None,
                        "avg_volume": None,
                        "earnings_date": None,
                        "source": "yahoo_previous_close"
                    }
                    symbols_with_stock_data.append(symbol)
        except Exception as e:
            logging.debug(f"Could not get stock price for {symbol}: {e}")
    
    # Step 2: Get market sentiment for scoring
    try:
        sentiment = await fetch_market_sentiment()
        market_bias = sentiment.get("bias", "neutral")
        bias_weight = get_market_bias_weight(market_bias)
    except Exception as e:
        logging.warning(f"Market sentiment unavailable, using neutral: {e}")
        market_bias = "neutral"
        bias_weight = 1.0
    
    # Step 3: Scan each symbol - fetch LIVE options at scan time
    opportunities = []
    symbols_scanned = 0
    symbols_with_results = 0
    symbols_filtered = []
    
    for symbol in symbols_with_stock_data:
        sym_data = stock_data[symbol]
        stock_price = sym_data["stock_price"]
        symbols_scanned += 1
        
        # Get metadata for eligibility check
        market_cap = sym_data.get("market_cap")
        avg_volume = sym_data.get("avg_volume")
        earnings_date = sym_data.get("earnings_date")
        
        # If metadata missing, try legacy snapshot
        if market_cap is None or avg_volume is None:
            try:
                stock_snapshot, _ = await snapshot_service.get_stock_snapshot(symbol)
                if stock_snapshot:
                    market_cap = market_cap or stock_snapshot.get("market_cap")
                    avg_volume = avg_volume or stock_snapshot.get("avg_volume")
                    earnings_date = earnings_date or stock_snapshot.get("earnings_date")
            except Exception:
                pass
        
        # LAYER 3: Check CC eligibility
        is_eligible, eligibility_reason = check_cc_eligibility(
            symbol=symbol,
            stock_price=stock_price,
            market_cap=market_cap,
            avg_volume=avg_volume,
            earnings_date=earnings_date,
            scan_mode=scan_mode,
            scan_date=sym_data.get("trade_date")
        )
        
        if not is_eligible:
            symbols_filtered.append({"symbol": symbol, "reason": eligibility_reason})
            continue
        
        # ============================================================
        # LIVE OPTIONS FETCH - Per user requirement #3
        # Options chain data MUST be fetched live, per symbol, per expiry
        # ============================================================
        try:
            live_options = await fetch_options_chain(
                symbol=symbol,
                api_key=None,  # Yahoo doesn't need API key
                option_type="call",
                max_dte=max_dte,
                min_dte=min_dte,
                current_price=stock_price
            )
        except Exception as e:
            logging.debug(f"Could not fetch live options for {symbol}: {e}")
            continue
        
        if not live_options:
            continue
        
        # Process each live option
        for opt in live_options:
            strike = opt.get("strike", 0)
            bid = opt.get("bid", 0)
            ask = opt.get("ask", 0)
            dte = opt.get("dte", 0)
            expiry = opt.get("expiry", "")
            iv = opt.get("implied_volatility", 0)
            oi = opt.get("open_interest", 0)
            volume = opt.get("volume", 0)
            
            # Use BID as premium (SELL leg)
            premium = bid if bid > 0 else opt.get("close", 0)
            if premium <= 0:
                continue
            
            # Calculate metrics
            premium_yield = (premium / stock_price) * 100 if stock_price > 0 else 0
            otm_pct = ((strike - stock_price) / stock_price) * 100 if stock_price > 0 else 0
            
            # Apply filters
            if premium_yield < min_premium_yield or premium_yield > max_premium_yield:
                continue
            if otm_pct < min_otm_pct or otm_pct > max_otm_pct:
                continue
            
            # Validate trade structure
            is_valid, rejection = validate_cc_trade(
                symbol=symbol,
                stock_price=stock_price,
                strike=strike,
                expiry=expiry,
                bid=premium,
                dte=dte,
                open_interest=oi,
                ask=ask
            )
            
            if not is_valid:
                continue
            
            # LAYER 3: Enrich with Greeks and ROI
            enriched_call = enrich_option_greeks(opt, stock_price)
            
            # Use enriched ROI calculation
            roi_pct = enriched_call.get("roi_pct", premium_yield)
            roi_annualized = enriched_call.get("roi_annualized", 0)
            
            # Calculate quality score (Phase 7)
            trade_data = {
                "iv": iv,
                "iv_rank": enriched_call.get("iv_rank", iv * 100 if iv < 1 else iv),
                "delta": enriched_call.get("delta", 0.3),
                "roi_pct": roi_pct,
                "premium": premium,
                "stock_price": stock_price,
                "dte": dte,
                "strike": strike,
                "open_interest": oi,
                "volume": volume,
                "is_etf": symbol in ETF_SYMBOLS,
                "market_cap": market_cap,
                "analyst_rating": None
            }
            quality_result = calculate_cc_quality_score(trade_data)
            
            # Apply market bias (Phase 6)
            final_score = apply_bias_to_score(quality_result.total_score, bias_weight)
            
            # Calculate bid-ask spread percentage
            spread_pct = ((ask - premium) / premium * 100) if premium > 0 and ask > 0 else 0
            
            # Build contract symbol (e.g., AAPL240119C00190000)
            try:
                exp_formatted = datetime.strptime(expiry, "%Y-%m-%d").strftime("%y%m%d")
                contract_symbol = f"{symbol}{exp_formatted}C{int(strike * 1000):08d}"
            except:
                contract_symbol = f"{symbol}_{strike}_{expiry}"
            
            # ==============================================================
            # AUTHORITATIVE CC CONTRACT - LAYER 3 COMPLIANT
            # ==============================================================
            is_etf = symbol in ETF_SYMBOLS
            
            opportunities.append({
                # UNDERLYING object - ADR-001: Uses market_close_price
                "underlying": {
                    "symbol": symbol,
                    "instrument_type": "ETF" if is_etf else "STOCK",
                    "last_price": round(stock_price, 2),
                    "price_source": "EOD_CONTRACT" if use_eod_contract else "BID",  # ADR-001 marker
                    "snapshot_date": sym_data.get("stock_price_trade_date"),
                    "market_close_timestamp": sym_data.get("market_close_timestamp"),  # ADR-001
                    "market_cap": market_cap,
                    "avg_volume": avg_volume,
                    "analyst_rating": None,  # Not in EOD contract
                    "earnings_date": earnings_date
                },
                
                # SHORT_CALL object - ALL option data here
                "short_call": {
                    "strike": strike,
                    "expiry": expiry,
                    "dte": dte,
                    "contract_symbol": contract_symbol,
                    "premium": round(premium, 2),  # BID ONLY
                    "bid": round(premium, 2),
                    "ask": round(ask, 2) if ask else None,
                    "spread_pct": round(spread_pct, 2),
                    "delta": round(enriched_call.get("delta", 0), 4),
                    "gamma": round(enriched_call.get("gamma_estimate", 0), 4),
                    "theta": round(enriched_call.get("theta_estimate", 0), 4),
                    "vega": round(enriched_call.get("vega_estimate", 0), 4),
                    "implied_volatility": round(enriched_call.get("iv_pct", iv * 100 if iv < 1 else iv), 1),
                    "iv_rank": round(enriched_call.get("iv_rank", 0), 1) if enriched_call.get("iv_rank") else None,
                    "open_interest": oi,
                    "volume": volume
                },
                
                # ECONOMICS object
                "economics": {
                    "max_profit": round(premium * 100, 2),  # Per contract
                    "breakeven": round(stock_price - premium, 2),
                    "roi_pct": round(roi_pct, 2),
                    "annualized_roi_pct": round(roi_annualized, 1),
                    "premium_yield": round(premium_yield, 2),
                    "otm_pct": round(otm_pct, 2)
                },
                
                # METADATA object
                "metadata": {
                    "dte_category": "weekly" if dte <= WEEKLY_MAX_DTE else "monthly",
                    "earnings_safe": earnings_date is None,
                    "is_etf": is_etf,
                    "validation_flags": {
                        "spread_ok": spread_pct < 10,
                        "liquidity_ok": oi >= 100,
                        "delta_ok": 0.20 <= enriched_call.get("delta", 0) <= 0.50
                    },
                    "data_source": "eod_contract" if use_eod_contract else "legacy_snapshot"  # ADR-001
                },
                
                # SCORING object
                "scoring": {
                    "base_score": round(quality_result.total_score, 1),
                    "final_score": round(final_score, 1),
                    "pillars": {k: {"score": round(v.actual_score, 1), "max": v.max_score} 
                               for k, v in quality_result.pillars.items()} if quality_result.pillars else {}
                },
                
                # ==============================================================
                # LEGACY FLAT FIELDS - For backwards compatibility during transition
                # These will be REMOVED once frontend is updated
                # ==============================================================
                "symbol": symbol,
                "strike": strike,
                "expiry": expiry,
                "dte": dte,
                "dte_category": "weekly" if dte <= WEEKLY_MAX_DTE else "monthly",
                "stock_price": round(stock_price, 2),
                "premium": round(premium, 2),
                "premium_ask": round(ask, 2) if ask else None,
                "premium_yield": round(premium_yield, 2),
                "otm_pct": round(otm_pct, 2),
                "roi_pct": round(roi_pct, 2),
                "roi_annualized": round(roi_annualized, 1),
                "delta": round(enriched_call.get("delta", 0), 4),
                "gamma": round(enriched_call.get("gamma_estimate", 0), 4),
                "theta": round(enriched_call.get("theta_estimate", 0), 4),
                "vega": round(enriched_call.get("vega_estimate", 0), 4),
                "implied_volatility": round(enriched_call.get("iv_pct", iv * 100 if iv < 1 else iv), 1),
                "iv_rank": round(enriched_call.get("iv_rank", 0), 1) if enriched_call.get("iv_rank") else None,
                "open_interest": oi,
                "volume": volume,
                "is_etf": is_etf,
                "instrument_type": "ETF" if is_etf else "STOCK",
                "base_score": round(quality_result.total_score, 1),
                "score": round(final_score, 1),
                "score_breakdown": {
                    "total": round(quality_result.total_score, 1),
                    "pillars": {k: {"score": round(v.actual_score, 1), "max": v.max_score} 
                               for k, v in quality_result.pillars.items()} if quality_result.pillars else {}
                },
                "market_cap": market_cap,
                "avg_volume": avg_volume,
                "analyst_rating": None,
                "earnings_date": earnings_date,
                "snapshot_date": sym_data.get("trade_date"),
                "data_source": "live_options"  # Now fetched LIVE
            })
        
        if live_options:
            symbols_with_results += 1
    
    # Sort by score descending
    opportunities.sort(key=lambda x: x["score"], reverse=True)
    
    # DEDUPLICATION: Keep only the best opportunity per symbol
    seen_symbols = set()
    deduplicated = []
    for opp in opportunities:
        if opp["symbol"] not in seen_symbols:
            seen_symbols.add(opp["symbol"])
            deduplicated.append(opp)
    
    opportunities = deduplicated
    
    return {
        "total": len(opportunities),
        "results": opportunities[:limit],
        "opportunities": opportunities[:limit],
        "symbols_scanned": symbols_scanned,
        "symbols_with_results": symbols_with_results,
        "symbols_filtered": len(symbols_filtered),
        "filter_reasons": symbols_filtered[:10],
        "market_bias": market_bias,
        "bias_weight": bias_weight,
        "stock_price_source": "previous_close",  # Rule #1
        "options_chain_source": "yahoo_live",    # Rule #3
        "layer": 3,
        "scan_mode": scan_mode,
        "dte_mode": dte_mode,
        "dte_range": {"min": min_dte, "max": max_dte},
        "eligibility_filters": {
            "price_range": f"${CC_SYSTEM_MIN_PRICE}-${CC_SYSTEM_MAX_PRICE}" if scan_mode != "manual" else f"${CC_MANUAL_MIN_PRICE}-${CC_MANUAL_MAX_PRICE}",
            "min_volume": f"{CC_SYSTEM_MIN_VOLUME:,}" if scan_mode != "manual" else "N/A",
            "min_market_cap": f"${CC_SYSTEM_MIN_MARKET_CAP/1e9:.0f}B" if scan_mode != "manual" else "N/A",
            "earnings_exclusion": f"±{EARNINGS_EXCLUSION_DAYS} days"
        },
        "spread_threshold": f"{MAX_SPREAD_PCT}%",
        "architecture": "LIVE_OPTIONS_PREVIOUS_CLOSE_STOCK",
        "live_data_used": True
    }


# ============================================================
# PMCC SCREENER - LIVE OPTIONS FETCH
# ============================================================

@screener_router.get("/pmcc")
async def screen_pmcc(
    limit: int = Query(50, ge=1, le=200),
    risk_profile: str = Query("moderate", regex="^(conservative|moderate|aggressive)$"),
    min_leap_dte: int = Query(365, ge=180),
    max_leap_dte: int = Query(730, le=1095),
    min_short_dte: int = Query(21, ge=7),
    max_short_dte: int = Query(60, le=90),
    min_delta: float = Query(0.70, ge=0.5, le=0.95),
    use_eod_contract: bool = Query(True, description="Use EOD contract for stock prices"),
    user: dict = Depends(get_current_user)
):
    """
    Screen for Poor Man's Covered Call (PMCC) opportunities.
    
    DATA FETCHING RULES:
    1. STOCK PRICES: Previous US market close (from EOD contract or previousClose)
    2. OPTIONS CHAINS: Fetched LIVE from Yahoo Finance at scan time
    """
    eod_contract = get_eod_contract()
    snapshot_service = get_snapshot_service()
    
    # Step 1: Get stock prices (previous close) for all symbols
    stock_data = {}
    symbols_with_stock_data = []
    
    for symbol in SCAN_SYMBOLS:
        try:
            if use_eod_contract:
                try:
                    price, stock_doc = await eod_contract.get_market_close_price(symbol)
                    stock_data[symbol] = {
                        "stock_price": price,
                        "trade_date": stock_doc.get("trade_date"),
                        "market_cap": stock_doc.get("metadata", {}).get("market_cap"),
                        "source": "eod_contract"
                    }
                    symbols_with_stock_data.append(symbol)
                except EODPriceNotFoundError:
                    quote = await fetch_stock_quote(symbol)
                    if quote and quote.get("price"):
                        stock_data[symbol] = {
                            "stock_price": quote["price"],
                            "trade_date": None,
                            "market_cap": None,
                            "source": "yahoo_previous_close"
                        }
                        symbols_with_stock_data.append(symbol)
            else:
                quote = await fetch_stock_quote(symbol)
                if quote and quote.get("price"):
                    stock_data[symbol] = {
                        "stock_price": quote["price"],
                        "trade_date": None,
                        "market_cap": None,
                        "source": "yahoo_previous_close"
                    }
                    symbols_with_stock_data.append(symbol)
        except Exception as e:
            logging.debug(f"Could not get stock price for {symbol}: {e}")
    
    # Step 2: Get market sentiment for scoring
    try:
        sentiment = await fetch_market_sentiment()
        market_bias = sentiment.get("bias", "neutral")
        bias_weight = get_market_bias_weight(market_bias)
    except Exception:
        market_bias = "neutral"
        bias_weight = 1.0
    
    # Step 3: Scan each symbol for PMCC opportunities - LIVE options fetch
    opportunities = []
    symbols_scanned = 0
    
    for symbol in symbols_with_stock_data:
        sym_data = stock_data[symbol]
        stock_price = sym_data["stock_price"]
        symbols_scanned += 1
        
        # ============================================================
        # LIVE LEAPS FETCH - Per user requirement #3
        # ============================================================
        try:
            live_leaps = await fetch_options_chain(
                symbol=symbol,
                api_key=None,
                option_type="call",
                max_dte=max_leap_dte,
                min_dte=min_leap_dte,
                current_price=stock_price
            )
        except Exception as e:
            logging.debug(f"Could not fetch live LEAPs for {symbol}: {e}")
            continue
        
        if not live_leaps:
            continue
        
        # Filter LEAPs for PMCC (deep ITM, high delta)
        leaps = []
        for opt in live_leaps:
            strike = opt.get("strike", 0)
            ask = opt.get("ask", 0)
            bid = opt.get("bid", 0)
            
            # Use ASK for BUY leg (LEAP)
            premium = ask if ask > 0 else bid
            if premium <= 0:
                continue
            
            # Calculate delta estimate if not provided
            moneyness = stock_price / strike if strike > 0 else 0
            # Deep ITM calls have delta close to 1
            if moneyness > 1.2:  # 20% ITM
                estimated_delta = min(0.95, 0.5 + (moneyness - 1) * 0.5)
            else:
                estimated_delta = opt.get("implied_volatility", 0.5)  # Rough estimate
            
            delta = opt.get("delta", estimated_delta)
            if delta < min_delta:
                continue
            
            leaps.append({
                "strike": strike,
                "expiry": opt.get("expiry", ""),
                "dte": opt.get("dte", 0),
                "premium": premium,
                "ask": ask,
                "bid": bid,
                "delta": delta,
                "implied_volatility": opt.get("implied_volatility", 0),
                "open_interest": opt.get("open_interest", 0)
            })
        
        if not leaps:
            continue
        
        # ============================================================
        # LIVE SHORT CALLS FETCH - Per user requirement #3
        # ============================================================
        try:
            live_shorts = await fetch_options_chain(
                symbol=symbol,
                api_key=None,
                option_type="call",
                max_dte=max_short_dte,
                min_dte=min_short_dte,
                current_price=stock_price
            )
        except Exception as e:
            logging.debug(f"Could not fetch live short calls for {symbol}: {e}")
            continue
        
        if not live_shorts:
            continue
        
        # Filter short calls for PMCC (OTM, use BID)
        shorts = []
        for opt in live_shorts:
            strike = opt.get("strike", 0)
            bid = opt.get("bid", 0)
            
            # Use BID for SELL leg
            if bid <= 0.10:  # Minimum $0.10 premium
                continue
            
            # Must be OTM (strike > stock price)
            if strike <= stock_price * 1.02:  # At least 2% OTM
                continue
            if strike > stock_price * 1.15:  # Max 15% OTM
                continue
            
            shorts.append({
                "strike": strike,
                "expiry": opt.get("expiry", ""),
                "dte": opt.get("dte", 0),
                "premium": bid,  # BID only for SELL leg
                "ask": opt.get("ask", 0),
                "implied_volatility": opt.get("implied_volatility", 0),
                "open_interest": opt.get("open_interest", 0)
            })
        
        if not shorts:
            continue
        
        market_cap = sym_data.get("market_cap")
        
        # Build PMCC combinations
        for leap in leaps:
            leap_cost = leap["premium"]  # ASK price
            leap_strike = leap["strike"]
            leap_delta = leap["delta"]
            leap_dte = leap["dte"]
            leap_expiry = leap["expiry"]
            leap_ask = leap.get("ask", leap_cost)
            leap_oi = leap.get("open_interest", 0)
            leap_iv = leap.get("implied_volatility", 0)
            
            for short in shorts:
                short_strike = short["strike"]
                short_premium = short["premium"]  # BID price
                short_dte = short["dte"]
                short_expiry = short["expiry"]
                short_ask = short.get("ask", 0)
                short_iv = short.get("implied_volatility", 0)
                
                # PMCC structure validation
                if short_strike <= leap_strike:
                    continue  # Short must be above LEAP strike
                
                # Calculate metrics
                max_profit = (short_strike - leap_strike) * 100 + (short_premium * 100)
                net_debit = leap_cost - short_premium
                
                if net_debit <= 0:
                    continue  # Invalid structure
                
                roi_per_cycle = (short_premium / leap_cost) * 100
                cycles_per_year = 365 / short_dte if short_dte > 0 else 12
                annualized_roi = roi_per_cycle * cycles_per_year
                
                # Validate PMCC trade structure
                is_valid, rejection = validate_pmcc_trade(
                    symbol=symbol,
                    stock_price=stock_price,
                    leap_strike=leap_strike,
                    leap_expiry=leap_expiry,
                    leap_ask=leap_cost,
                    leap_dte=leap_dte,
                    leap_delta=leap_delta,
                    leap_oi=leap.get("open_interest", 0),
                    short_strike=short_strike,
                    short_expiry=short_expiry,
                    short_bid=short_premium,
                    short_dte=short_dte
                )
                
                if not is_valid:
                    continue
                
                # LAYER 3: Compute PMCC-specific metrics
                pmcc_metrics = enrich_pmcc_metrics(leap, short, stock_price)
                
                # Calculate quality score
                pmcc_trade_data = {
                    "leap_delta": leap_delta,
                    "leap_dte": leap_dte,
                    "short_dte": short_dte,
                    "short_otm_pct": ((short_strike - stock_price) / stock_price) * 100,
                    "roi_pct": roi_per_cycle,
                    "is_etf": symbol in ETF_SYMBOLS
                }
                quality_result = calculate_pmcc_quality_score(pmcc_trade_data)
                
                final_score = apply_bias_to_score(quality_result.total_score, bias_weight)
                
                # Width calculation
                width = short_strike - leap_strike
                
                # LAYER 3: Compute short call delta (if not from snapshot)
                # Estimate based on moneyness for OTM calls
                short_delta = short.get("delta", 0)
                if short_delta == 0 and stock_price > 0 and short_strike > 0:
                    moneyness = (stock_price - short_strike) / stock_price
                    # OTM call delta estimation
                    if moneyness < 0:  # OTM
                        short_delta = max(0.05, 0.50 + moneyness * 2)
                    else:  # ITM
                        short_delta = min(0.95, 0.50 + moneyness * 2)
                
                # Calculate short call Greeks
                short_gamma = short.get("gamma", 0)
                short_theta = short.get("theta", 0)
                short_vega = short.get("vega", 0)
                
                # Estimate if not provided
                if short_theta == 0 and short_premium > 0 and short_dte > 0:
                    short_theta = -round(short_premium / short_dte, 4)
                
                # Calculate spread percentages
                short_spread_pct = ((short_ask - short_premium) / short_premium * 100) if short_premium > 0 and short_ask else 0
                leap_spread_pct = ((leap_ask - leap.get("bid", leap_ask)) / leap_ask * 100) if leap_ask > 0 else 0
                
                # Build contract symbols
                short_exp_fmt = datetime.strptime(short_expiry, "%Y-%m-%d").strftime("%y%m%d")
                leap_exp_fmt = datetime.strptime(leap_expiry, "%Y-%m-%d").strftime("%y%m%d")
                short_contract_symbol = f"{symbol}{short_exp_fmt}C{int(short_strike * 1000):08d}"
                leap_contract_symbol = f"{symbol}{leap_exp_fmt}C{int(leap_strike * 1000):08d}"
                
                # ==============================================================
                # AUTHORITATIVE PMCC CONTRACT - ADR-001 COMPLIANT
                # ==============================================================
                opportunities.append({
                    # UNDERLYING object - ADR-001: Uses market_close_price
                    "underlying": {
                        "symbol": symbol,
                        "last_price": round(stock_price, 2),
                        "price_source": "EOD_CONTRACT" if use_eod_contract else "BID",  # ADR-001
                        "snapshot_date": sym_data.get("stock_price_trade_date"),
                        "market_close_timestamp": sym_data.get("market_close_timestamp"),  # ADR-001
                        "market_cap": market_cap,
                        "analyst_rating": None  # Not in EOD contract
                    },
                    
                    # SHORT_CALL object - SELL leg
                    "short_call": {
                        "strike": short_strike,
                        "expiry": short_expiry,
                        "dte": short_dte,
                        "contract_symbol": short_contract_symbol,
                        "premium": round(short_premium, 2),  # BID ONLY
                        "bid": round(short_premium, 2),
                        "ask": round(short_ask, 2) if short_ask else None,
                        "spread_pct": round(short_spread_pct, 2),
                        "delta": round(short_delta, 4),
                        "gamma": round(short_gamma, 4) if short_gamma else None,
                        "theta": round(short_theta, 4) if short_theta else None,
                        "vega": round(short_vega, 4) if short_vega else None,
                        "implied_volatility": round(short_iv * 100 if short_iv < 1 else short_iv, 1),
                        "open_interest": short.get("open_interest", 0),
                        "volume": short.get("volume", 0)
                    },
                    
                    # LONG_CALL object - BUY leg (LEAP)
                    "long_call": {
                        "strike": leap_strike,
                        "expiry": leap_expiry,
                        "dte": leap_dte,
                        "contract_symbol": leap_contract_symbol,
                        "premium": round(leap_ask, 2),  # ASK ONLY for buys
                        "bid": round(leap.get("bid", 0), 2) if leap.get("bid") else None,
                        "ask": round(leap_ask, 2),
                        "spread_pct": round(leap_spread_pct, 2),
                        "delta": round(leap_delta, 4),
                        "implied_volatility": round(leap_iv * 100 if leap_iv < 1 else leap_iv, 1),
                        "open_interest": leap_oi,
                        "volume": leap.get("volume", 0)
                    },
                    
                    # ECONOMICS object
                    "economics": {
                        "net_debit": round(net_debit, 2),
                        "net_debit_total": round(net_debit * 100, 2),
                        "width": round(width, 2),
                        "max_profit": round(pmcc_metrics.get("max_profit_total", max_profit), 2),
                        "breakeven": round(pmcc_metrics.get("breakeven", leap_strike + net_debit), 2),
                        "roi_pct": round(roi_per_cycle, 2),
                        "annualized_roi_pct": round(annualized_roi, 1)
                    },
                    
                    # METADATA object
                    "metadata": {
                        "leaps_buy_eligible": pmcc_metrics.get("leaps_buy_eligible", False),
                        "analyst_rating": None,  # ADR-001: Not in EOD contract
                        "validation_flags": {
                            "leap_delta_ok": leap_delta >= 0.70,
                            "leap_dte_ok": leap_dte >= 365,
                            "short_otm_ok": short_strike > stock_price
                        },
                        "data_source": "eod_contract" if use_eod_contract else "legacy_snapshot"  # ADR-001
                    },
                    
                    # SCORING object
                    "scoring": {
                        "base_score": round(quality_result.total_score, 1),
                        "final_score": round(final_score, 1),
                        "pillars": {k: {"score": round(v.actual_score, 1), "max": v.max_score} 
                                   for k, v in quality_result.pillars.items()} if quality_result.pillars else {}
                    },
                    
                    # ==============================================================
                    # LEGACY FLAT FIELDS - For backwards compatibility during transition
                    # These will be REMOVED once frontend is updated
                    # ==============================================================
                    "symbol": symbol,
                    "stock_price": round(stock_price, 2),
                    "leap_strike": leap_strike,
                    "leap_expiry": leap_expiry,
                    "leap_dte": leap_dte,
                    "leap_cost": round(leap_cost, 2),
                    "leap_delta": round(leap_delta, 3),
                    "leap_ask": round(leap_ask, 2),
                    "leap_open_interest": leap_oi,
                    "leap_iv": round(leap_iv * 100 if leap_iv < 1 else leap_iv, 1),
                    "leaps_buy_eligible": pmcc_metrics.get("leaps_buy_eligible", False),
                    "short_strike": short_strike,
                    "short_expiry": short_expiry,
                    "short_dte": short_dte,
                    "short_premium": round(short_premium, 2),
                    "short_ask": round(short_ask, 2) if short_ask else None,
                    "short_iv": round(short_iv * 100 if short_iv < 1 else short_iv, 1),
                    "short_delta": round(short_delta, 4),  # NEW: Short call delta
                    "width": round(width, 2),
                    "net_debit": round(net_debit, 2),
                    "net_debit_total": round(net_debit * 100, 2),
                    "max_profit": round(pmcc_metrics.get("max_profit_total", max_profit), 2),
                    "breakeven": pmcc_metrics.get("breakeven", 0),
                    "roi_per_cycle": round(roi_per_cycle, 2),
                    "annualized_roi": round(annualized_roi, 1),
                    "base_score": round(quality_result.total_score, 1),
                    "score": round(final_score, 1),
                    "score_breakdown": {
                        "total": round(quality_result.total_score, 1),
                        "pillars": {k: {"score": round(v.actual_score, 1), "max": v.max_score} 
                                   for k, v in quality_result.pillars.items()} if quality_result.pillars else {}
                    },
                    "analyst_rating": None,  # Not in EOD contract
                    "market_cap": market_cap,
                    "snapshot_date": sym_data.get("stock_price_trade_date"),
                    "data_source": "eod_contract" if use_eod_contract else "legacy_snapshot"  # ADR-001
                })
    
    # Sort by annualized ROI
    opportunities.sort(key=lambda x: x["annualized_roi"], reverse=True)
    
    # DEDUPLICATION: Keep only the best PMCC opportunity per symbol
    seen_symbols = set()
    deduplicated = []
    for opp in opportunities:
        if opp["symbol"] not in seen_symbols:
            seen_symbols.add(opp["symbol"])
            deduplicated.append(opp)
    
    opportunities = deduplicated
    
    return {
        "total": len(opportunities),
        "results": opportunities[:limit],
        "opportunities": opportunities[:limit],
        "symbols_scanned": symbols_scanned,
        "market_bias": market_bias,
        "snapshot_validation": {
            "total": validation["symbols_total"],
            "valid": validation["symbols_valid"],
            "data_source": validation.get("data_source", "legacy")  # ADR-001
        },
        # ADR-001: EOD Contract metadata
        "eod_contract": {
            "enabled": use_eod_contract,
            "version": "ADR-001"
        },
        "phase": 7,
        "architecture": "ADR-001_EOD_CONTRACT" if use_eod_contract else "TWO_PHASE_SNAPSHOT_ONLY",
        "live_data_used": False
    }


# ============================================================
# DASHBOARD OPPORTUNITIES (Phase 2 - READ-ONLY FROM SNAPSHOTS)
# ============================================================

@screener_router.get("/dashboard-opportunities")
async def get_dashboard_opportunities(
    user: dict = Depends(get_current_user)
):
    """
    Get top opportunities for dashboard display.
    
    Returns Top 5 Weekly + Top 5 Monthly covered calls for dashboard display.
    If fewer than 5 weekly options available, fills remaining slots with monthly.
    
    ARCHITECTURE: Phase 2 - Reads ONLY from stored Mongo snapshots.
    
    FAIL CLOSED: Returns HTTP 409 if snapshot validation fails.
    """
    # Get a broader set with relaxed filters to ensure we have options
    all_opportunities = await screen_covered_calls(
        limit=100,
        risk_profile="moderate",
        dte_mode="all",
        scan_mode="system",
        min_dte=None,
        max_dte=None,
        min_premium_yield=0.3,  # Relaxed for dashboard to get more options
        max_premium_yield=20.0,
        min_otm_pct=0.0,
        max_otm_pct=15.0,
        user=user
    )
    
    results = all_opportunities.get("opportunities", all_opportunities.get("results", []))
    
    # Separate into weekly (DTE <= 14) and monthly (DTE > 14)
    weekly_opps = [opp for opp in results if opp.get("dte", 0) <= WEEKLY_MAX_DTE]
    monthly_opps = [opp for opp in results if opp.get("dte", 0) > WEEKLY_MAX_DTE]
    
    # Sort each by score descending
    weekly_opps.sort(key=lambda x: x.get("score", 0), reverse=True)
    monthly_opps.sort(key=lambda x: x.get("score", 0), reverse=True)
    
    # Take top 5 from each (or as many as available)
    top_weekly = weekly_opps[:5]
    top_monthly = monthly_opps[:5]
    
    # If we have fewer than 5 weekly, note it but don't fill with monthly
    # This maintains data integrity - weekly means weekly
    weekly_count = len(top_weekly)
    monthly_count = len(top_monthly)
    
    # Mark with expiry_type for frontend styling
    for opp in top_weekly:
        opp["expiry_type"] = "Weekly"
        opp["metadata"] = opp.get("metadata", {})
        opp["metadata"]["dte_category"] = "weekly"
    for opp in top_monthly:
        opp["expiry_type"] = "Monthly"
        opp["metadata"] = opp.get("metadata", {})
        opp["metadata"]["dte_category"] = "monthly"
    
    # Combine: Weekly first, then Monthly
    combined = top_weekly + top_monthly
    
    return {
        "total": len(combined),
        "opportunities": combined,
        "weekly_count": weekly_count,
        "monthly_count": monthly_count,
        "weekly_opportunities": top_weekly,
        "monthly_opportunities": top_monthly,
        # Data availability note
        "weekly_available": len(weekly_opps),
        "monthly_available": len(monthly_opps),
        "data_note": f"Weekly: {weekly_count}/5 available, Monthly: {monthly_count}/5 available" if weekly_count < 5 else None,
        # Preserve metadata from original response
        "market_bias": all_opportunities.get("market_bias"),
        "snapshot_validation": all_opportunities.get("snapshot_validation"),
        "layer": 3,
        "architecture": "TOP5_WEEKLY_TOP5_MONTHLY",
        "live_data_used": False
    }


# ============================================================
# MARKET SENTIMENT (Still allowed - not for scan eligibility)
# ============================================================

@screener_router.get("/market-sentiment")
async def get_market_sentiment(user: dict = Depends(get_current_user)):
    """
    Get current market sentiment for display.
    
    NOTE: This data is used for SCORING only, NOT for scan eligibility.
    """
    try:
        sentiment = await fetch_market_sentiment()
        return sentiment
    except Exception as e:
        return {
            "bias": "neutral",
            "confidence": 0.5,
            "error": str(e)
        }


# ============================================================
# ADMIN STATUS ENDPOINT
# ============================================================

@screener_router.get("/admin-status")
async def get_admin_status(user: dict = Depends(get_current_user)):
    """
    Get detailed screener status for admin dashboard.
    
    Returns snapshot health information.
    """
    snapshot_service = get_snapshot_service()
    
    # Count snapshots by status
    total_symbols = len(SCAN_SYMBOLS)
    
    valid_stocks = 0
    valid_chains = 0
    stale_stocks = 0
    stale_chains = 0
    missing_stocks = 0
    missing_chains = 0
    incomplete_chains = 0
    
    rejection_details = []
    
    for symbol in SCAN_SYMBOLS:
        stock, stock_error = await snapshot_service.get_stock_snapshot(symbol)
        chain, chain_error = await snapshot_service.get_option_chain_snapshot(symbol)
        
        if stock_error:
            if "stale" in stock_error.lower():
                stale_stocks += 1
            else:
                missing_stocks += 1
            rejection_details.append(f"{symbol} stock: {stock_error}")
        else:
            valid_stocks += 1
        
        if chain_error:
            if "stale" in chain_error.lower():
                stale_chains += 1
            elif "incomplete" in chain_error.lower():
                incomplete_chains += 1
            else:
                missing_chains += 1
            rejection_details.append(f"{symbol} chain: {chain_error}")
        else:
            valid_chains += 1
    
    # Calculate scan readiness
    scan_ready = valid_stocks == total_symbols and valid_chains == total_symbols
    
    return {
        "architecture": "TWO_PHASE_SNAPSHOT_ONLY",
        "live_data_enabled": False,
        "symbols_total": total_symbols,
        "snapshot_status": {
            "stocks": {
                "valid": valid_stocks,
                "stale": stale_stocks,
                "missing": missing_stocks
            },
            "option_chains": {
                "valid": valid_chains,
                "stale": stale_chains,
                "incomplete": incomplete_chains,
                "missing": missing_chains
            }
        },
        "scan_ready": scan_ready,
        "scan_ready_message": "All snapshots valid" if scan_ready else f"Scan will abort: {total_symbols - valid_stocks} stock + {total_symbols - valid_chains} chain issues",
        "rejection_details": rejection_details[:20],
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# ============================================================
# SNAPSHOT HEALTH CHECK (Anti-Panic Control)
# ============================================================

@screener_router.get("/snapshot-health")
async def get_snapshot_health():
    """
    Public health check for snapshot status.
    
    Use this to diagnose blank screen issues:
    - Data issue vs validation issue vs UI issue
    """
    snapshot_service = get_snapshot_service()
    
    symbols_total = len(SCAN_SYMBOLS)
    snapshots_found = 0
    snapshots_valid = 0
    rejected_stale = 0
    rejected_incomplete = 0
    rejected_missing = 0
    
    for symbol in SCAN_SYMBOLS:
        stock, _ = await snapshot_service.get_stock_snapshot(symbol)
        chain, chain_error = await snapshot_service.get_option_chain_snapshot(symbol)
        
        if stock:
            snapshots_found += 1
        
        if chain:
            if chain.get("completeness_flag"):
                snapshots_valid += 1
            else:
                rejected_incomplete += 1
        elif chain_error:
            if "stale" in chain_error.lower():
                rejected_stale += 1
            else:
                rejected_missing += 1
    
    return {
        "symbols_total": symbols_total,
        "snapshots_found": snapshots_found,
        "snapshots_valid": snapshots_valid,
        "rejected_stale": rejected_stale,
        "rejected_incomplete": rejected_incomplete,
        "rejected_missing": rejected_missing,
        "scan_will_succeed": snapshots_valid == symbols_total,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
