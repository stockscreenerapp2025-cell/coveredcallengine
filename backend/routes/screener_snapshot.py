"""
Screener Routes - Covered Call and PMCC screening endpoints
============================================================

CCE MASTER ARCHITECTURE - LAYER 3: Strategy Selection Layer

DATA FETCHING RULES (NON-NEGOTIABLE - UPDATED FEB 2026):

1. ALL SCAN DATA COMES FROM MONGODB ONLY
   - Source: scan_results_cc, scan_results_pmcc collections
   - Pre-computed by EOD pipeline at 4:10 PM ET daily
   - ❌ NO LIVE YAHOO CALLS during request/response cycle
   - ❌ NO fetch_options_chain() calls allowed

2. FALLBACK: precomputed_scans collection (legacy)
   - Used only if no EOD run exists

LAYER 3 RESPONSIBILITIES:
    - Apply user filters at MongoDB query level
    - Return pre-computed results with optional filtering
    - Maintain response schema compatibility
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
import uuid
import math
import traceback

# Import pricing utilities for stabilization
from utils.pricing_utils import (
    sanitize_float,
    sanitize_money,
    sanitize_percentage,
    sanitize_dict_with_money,
    enforce_pricing_policy_cc,
    enforce_pricing_policy_pmcc,
    MONETARY_FIELDS
)

# Import data_provider - ONLY for non-scan paths (Watchlist, Simulator)
# SCAN PATHS (Screener, Dashboard, PMCC) MUST NOT use these for live fetching
from services.data_provider import (
    get_market_state
)

# IV Rank Service for industry-standard IV metrics
from services.iv_rank_service import (
    get_iv_metrics_for_symbol,
    IVMetrics
)

# Import enrichment service for IV Rank and Analyst data
# NOTE: Enrichment is DB-only in scan paths (no live Yahoo calls)
# Import quote cache for after-hours support
from services.quote_cache_service import get_quote_cache

# Import SnapshotService for stock metadata (not for options)
from services.snapshot_service import SnapshotService

# Universe Builder for tiered symbol universe and ETF detection
from utils.universe import (
    is_etf,
    get_scan_universe,
    get_tier_counts,
    ETF_WHITELIST
)

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

# ============================================================
# STABILITY: PRICING PRECISION HELPERS (MASTER STABILIZATION PATCH)
# ============================================================
# - sanitize_float: General floats, no rounding
# - sanitize_money: Monetary values, STRICT 2-decimal precision
# - sanitize_dict_with_money: Full dict sanitization
# Imported from utils.pricing_utils

def safe_divide(numerator, denominator, default=None):
    """
    Safe division that returns None instead of NaN/inf on invalid input.
    """
    if denominator is None or denominator == 0:
        return default
    if numerator is None:
        return default
    try:
        result = float(numerator) / float(denominator)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except (TypeError, ValueError, ZeroDivisionError):
        return default

# Alias for backward compatibility
def sanitize_dict_floats(d: dict) -> dict:
    """Alias for sanitize_dict_with_money for backward compatibility."""
    return sanitize_dict_with_money(d)

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

# ETF symbols for special handling - now using centralized universe builder
# is_etf(symbol) function should be used instead of checking this set directly
ETF_SYMBOLS = ETF_WHITELIST  # Re-export for backward compatibility

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

# Symbol universe (now built dynamically from universe builder)
# Phase 2: S&P500 + Nasdaq100 net + ETF whitelist
# Configuration via MAX_SCAN_UNIVERSE env variable (default 700)
# NOTE: This is now a function call to support dynamic updates
def get_scan_symbols() -> list:
    """Get the current scan universe symbols."""
    return get_scan_universe()

# For backward compatibility, expose as constant (evaluated at import time)
# NOTE: Use get_scan_symbols() for dynamic access
SCAN_SYMBOLS = get_scan_universe()

# Fast scan subset - most liquid symbols for live scanning
# Full universe (550) is too slow for live Yahoo calls
# This subset is used by /covered-calls and /pmcc for live scanning
FAST_SCAN_SYMBOLS = [
    # Top 20 Tech
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD", "INTC", "CRM",
    "ORCL", "ADBE", "NFLX", "PYPL", "SHOP", "SQ", "UBER", "SNOW", "PLTR", "COIN",
    # Top 10 Finance
    "JPM", "BAC", "WFC", "GS", "MS", "C", "V", "MA", "AXP", "SCHW",
    # Top 10 Healthcare
    "UNH", "JNJ", "PFE", "MRK", "ABBV", "LLY", "BMY", "GILD", "AMGN", "CVS",
    # Top 10 Consumer
    "WMT", "HD", "NKE", "SBUX", "MCD", "DIS", "COST", "TGT", "LOW", "YUM",
    # Top 10 Energy
    "XOM", "CVX", "COP", "SLB", "EOG", "OXY", "DVN", "HAL", "MPC", "VLO",
    # Top 10 Industrial
    "CAT", "DE", "BA", "HON", "GE", "UPS", "FDX", "RTX", "LMT", "UNP",
    # Top 15 ETFs (most liquid)
    "SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK", "XLV", "GLD", "SLV",
    "TLT", "ARKK", "VXX", "UVXY", "TQQQ"
]


# ============================================================
# PHASE 3: AI-BASED BEST OPTION SELECTION PER SYMBOL
# ============================================================
# IMPORTANT:
# Scan candidates may include multiple options per symbol.
# Final output must return ONE best option per symbol,
# selected by highest AI score.
#
# This is a post-processing step AFTER:
# - Option scoring
# - AI ranking
# - Quality score calculation
#
# ❌ Does NOT affect: Watchlist, Simulator, Portfolio
# ============================================================

def select_best_option_per_symbol(opportunities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    PHASE 3: Select the single best option for each underlying symbol.
    
    This function ensures clean, professional UI output with one actionable
    recommendation per stock, while allowing rich option exploration internally.
    
    Selection Criteria (in order of priority):
    1. Highest AI score (score field) - Primary
    2. Highest quality score (base_score field) - Tie-breaker
    3. Highest ROI (roi_pct field) - Secondary tie-breaker
    4. Lower downside risk (otm_pct closer to target) - Tertiary tie-breaker
    
    Args:
        opportunities: List of opportunity dictionaries, each containing:
            - symbol: Underlying stock symbol
            - score: AI/final score
            - base_score: Quality score
            - roi_pct: Return on investment percentage
            - otm_pct: Out-of-the-money percentage
            
    Returns:
        Deduplicated list with ONE best option per symbol
    """
    if not opportunities:
        return []
    
    # Group opportunities by underlying symbol
    symbol_groups: Dict[str, List[Dict[str, Any]]] = {}
    for opp in opportunities:
        symbol = opp.get("symbol", "UNKNOWN")
        if symbol not in symbol_groups:
            symbol_groups[symbol] = []
        symbol_groups[symbol].append(opp)
    
    # Select best option from each group
    best_options = []
    for symbol, candidates in symbol_groups.items():
        if len(candidates) == 1:
            # Single candidate - no selection needed
            best_options.append(candidates[0])
        else:
            # Multiple candidates - apply AI-based selection
            # Sort by: score (desc), base_score (desc), roi_pct (desc), otm_pct (closer to 5%)
            sorted_candidates = sorted(
                candidates,
                key=lambda x: (
                    x.get("score", 0),                    # Primary: AI score (higher is better)
                    x.get("base_score", 0),               # Tie-breaker 1: Quality score
                    x.get("roi_pct", 0),                  # Tie-breaker 2: ROI
                    -abs(x.get("otm_pct", 5) - 5)         # Tie-breaker 3: OTM% closest to 5%
                ),
                reverse=True
            )
            best_options.append(sorted_candidates[0])
            
            # Log when multiple candidates exist (for debugging)
            if len(candidates) > 2:
                logging.debug(
                    f"PHASE 3: {symbol} had {len(candidates)} candidates, "
                    f"selected strike={sorted_candidates[0].get('strike')} "
                    f"expiry={sorted_candidates[0].get('expiry')} "
                    f"score={sorted_candidates[0].get('score')}"
                )
    
    # Sort final results by score descending
    best_options.sort(key=lambda x: x.get("score", 0), reverse=True)
    
    return best_options


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
    symbol_is_etf = is_etf(symbol)  # Use imported function
    
    # ETFs are exempt from most checks - they follow different rules
    if symbol_is_etf:
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
    iv_metrics: Any = None
) -> Dict:
    """
    Enrich option contract with computed Greeks using Black-Scholes.
    
    CCE VOLATILITY & GREEKS CORRECTNESS - REFACTORED
    
    CHANGES FROM PREVIOUS VERSION:
    - Delta: Now uses Black-Scholes (removed moneyness fallback)
    - IV: Standardized to decimal (iv) and percentage (iv_pct)
    - IV Rank: Uses true industry-standard calculation when history available
    - All *_source fields added for transparency
    
    Computes:
    - Delta via Black-Scholes (greeks_service.py)
    - IV normalized to decimal and percentage
    - IV Rank/Percentile from historical data (or neutral fallback)
    - Gamma, Theta, Vega via Black-Scholes
    - ROI (%) = (Premium / Stock Price) * 100 * (365 / DTE)
    
    Args:
        contract: Option contract data from snapshot
        stock_price: Stock close price (validated previousClose from Layer 1)
        iv_metrics: IVMetrics object with pre-computed IV rank data (optional)
    
    Returns:
        Enriched contract with Greeks, ROI, and source fields
    """
    from services.greeks_service import calculate_greeks, normalize_iv_fields
    
    enriched = contract.copy()
    
    strike = contract.get("strike", 0)
    dte = contract.get("dte", 30)
    iv_raw = contract.get("implied_volatility", 0)
    option_type = contract.get("option_type", contract.get("type", "call"))
    premium = contract.get("bid", 0) or contract.get("premium", 0)
    ask = contract.get("ask", 0)
    
    # ==========================================================================
    # STEP 1: Normalize IV to decimal and percentage
    # ==========================================================================
    iv_data = normalize_iv_fields(iv_raw)
    enriched["iv"] = iv_data["iv"]
    enriched["iv_pct"] = iv_data["iv_pct"]
    
    # ==========================================================================
    # STEP 2: Calculate Greeks via Black-Scholes
    # (Removed moneyness-based delta fallback - accuracy and consistency)
    # ==========================================================================
    T = max(dte, 1) / 365.0  # Time in years
    
    greeks_result = calculate_greeks(
        S=stock_price,
        K=strike,
        T=T,
        sigma=iv_data["iv"] if iv_data["iv"] > 0 else None,
        option_type=option_type
    )
    
    enriched["delta"] = greeks_result.delta
    enriched["delta_source"] = greeks_result.delta_source
    enriched["gamma"] = greeks_result.gamma
    enriched["theta"] = greeks_result.theta
    enriched["vega"] = greeks_result.vega
    
    # Legacy field names for backward compatibility
    enriched["gamma_estimate"] = greeks_result.gamma
    enriched["theta_estimate"] = greeks_result.theta
    enriched["vega_estimate"] = greeks_result.vega
    
    # ==========================================================================
    # STEP 3: IV Rank and Percentile
    # ==========================================================================
    if iv_metrics is not None and isinstance(iv_metrics, IVMetrics):
        enriched["iv_rank"] = iv_metrics.iv_rank
        enriched["iv_percentile"] = iv_metrics.iv_percentile
        enriched["iv_rank_source"] = iv_metrics.iv_rank_source
        enriched["iv_rank_confidence"] = iv_metrics.iv_rank_confidence
        enriched["iv_samples"] = iv_metrics.iv_samples
    else:
        # No metrics provided - use neutral defaults
        enriched["iv_rank"] = 50.0
        enriched["iv_percentile"] = 50.0
        enriched["iv_rank_source"] = "DEFAULT_NEUTRAL_NO_METRICS"
        enriched["iv_rank_confidence"] = "LOW"
        enriched["iv_samples"] = 0
    
    # ==========================================================================
    # STEP 4: ROI Calculation
    # ==========================================================================
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
# ARCHITECTURE UPDATE (Feb 2026): NO LIVE YAHOO CALLS
# All data comes from pre-computed MongoDB collections
# ============================================================

async def _get_latest_eod_run_id() -> Optional[str]:
    """Get the latest completed EOD run_id from scan_runs collection."""
    try:
        latest = await db.scan_runs.find_one(
            {"status": "COMPLETED"},
            sort=[("completed_at", -1)]
        )
        return latest.get("run_id") if latest else None
    except Exception as e:
        logging.error(f"Failed to get latest EOD run: {e}")
        return None


async def _get_cc_from_eod(
    run_id: str,
    filters: Dict[str, Any],
    limit: int
) -> List[Dict]:
    """
    Query scan_results_cc collection with filters.
    
    NO LIVE YAHOO CALLS - reads from pre-computed data only.
    """
    query = {"run_id": run_id}
    
    # Apply DTE filter
    if filters.get("min_dte"):
        query["dte"] = {"$gte": filters["min_dte"]}
    if filters.get("max_dte"):
        if "dte" in query:
            query["dte"]["$lte"] = filters["max_dte"]
        else:
            query["dte"] = {"$lte": filters["max_dte"]}
    
    # Apply DTE mode filter
    if filters.get("dte_mode") == "weekly":
        query["dte"] = {"$gte": 7, "$lte": 14}
    elif filters.get("dte_mode") == "monthly":
        query["dte"] = {"$gte": 21, "$lte": 45}
    
    # Apply premium yield filter
    if filters.get("min_premium_yield"):
        query["premium_yield"] = {"$gte": filters["min_premium_yield"]}
    if filters.get("max_premium_yield"):
        if "premium_yield" in query:
            query["premium_yield"]["$lte"] = filters["max_premium_yield"]
        else:
            query["premium_yield"] = {"$lte": filters["max_premium_yield"]}
    
    # Apply OTM% filter
    if filters.get("min_otm_pct") is not None:
        query["otm_pct"] = {"$gte": filters["min_otm_pct"]}
    if filters.get("max_otm_pct"):
        if "otm_pct" in query:
            query["otm_pct"]["$lte"] = filters["max_otm_pct"]
        else:
            query["otm_pct"] = {"$lte": filters["max_otm_pct"]}
    
    # Apply delta filter based on risk profile
    risk_profile = filters.get("risk_profile", "moderate")
    if risk_profile == "conservative":
        query["delta"] = {"$gte": 0.15, "$lte": 0.30}
    elif risk_profile == "aggressive":
        query["delta"] = {"$gte": 0.30, "$lte": 0.50}
    # moderate: no delta filter (use all)
    
    try:
        cursor = db.scan_results_cc.find(
            query,
            {"_id": 0}
        ).sort("score", -1).limit(limit)
        
        results = await cursor.to_list(length=limit)
        return results
    except Exception as e:
        logging.error(f"Failed to query scan_results_cc: {e}")
        return []


async def _get_cc_from_legacy(filters: Dict[str, Any], limit: int) -> List[Dict]:
    """
    Fallback: Query precomputed_scans collection (legacy).
    
    NO LIVE YAHOO CALLS - reads from pre-computed data only.
    """
    try:
        # Find latest CC scan
        latest = await db.precomputed_scans.find_one(
            {"type": "cc"},
            sort=[("computed_at", -1)]
        )
        
        if not latest:
            return []
        
        results = latest.get("results", [])
        
        # Apply filters in memory (legacy scans don't have indexed fields)
        filtered = []
        for r in results:
            # DTE filter
            dte = r.get("dte", 0)
            if filters.get("min_dte") and dte < filters["min_dte"]:
                continue
            if filters.get("max_dte") and dte > filters["max_dte"]:
                continue
            
            # Premium yield filter
            py = r.get("premium_yield", 0)
            if filters.get("min_premium_yield") and py < filters["min_premium_yield"]:
                continue
            if filters.get("max_premium_yield") and py > filters["max_premium_yield"]:
                continue
            
            filtered.append(r)
        
        # Sort by score and limit
        filtered.sort(key=lambda x: x.get("score", 0), reverse=True)
        return filtered[:limit]
        
    except Exception as e:
        logging.error(f"Failed to query precomputed_scans: {e}")
        return []


# ============================================================
# ANALYST ENRICHMENT MERGE (READ-TIME)
# ============================================================

async def _merge_analyst_enrichment(opportunities: List[Dict], debug_enrichment: bool = False) -> List[Dict]:
    """
    Merge analyst enrichment data from symbol_enrichment collection (DB-only).

    ARCHITECTURE (Feb 2026): NO LIVE YAHOO CALLS
    - Fetches enrichment for all symbols in batch from MongoDB (symbol_enrichment)
    - For missing symbols: leaves analyst fields as-is (typically null) and (optionally) adds debug metadata
    - Merges: analyst_rating_label, analyst_rating_value, analyst_opinions, target_price_mean/high/low
    - Non-fatal: never breaks the response if enrichment is missing or query fails

    PERFORMANCE: Requires index on symbol_enrichment.symbol (unique)
    """
    if not opportunities:
        return opportunities

    try:
        # Extract unique symbols
        symbols = list({opp.get("symbol") for opp in opportunities if opp.get("symbol")})

        if not symbols:
            return opportunities

        # Batch fetch all enrichments from DB (uses index)
        enrichment_cursor = db.symbol_enrichment.find(
            {"symbol": {"$in": symbols}},
            {
                "_id": 0,
                "symbol": 1,
                "analyst_rating_label": 1,
                "analyst_rating_value": 1,
                "analyst_opinions": 1,
                "target_price_mean": 1,
                "target_price_high": 1,
                "target_price_low": 1,
            },
        )
        enrichments = await enrichment_cursor.to_list(length=len(symbols))

        # Build lookup dict
        enrichment_map = {e["symbol"]: e for e in enrichments if e.get("symbol")}

        # Merge into opportunities
        for opp in opportunities:
            symbol = opp.get("symbol")
            if not symbol:
                continue

            enrichment = enrichment_map.get(symbol)

            if enrichment:
                # Use DB enrichment
                opp["analyst_rating_label"] = enrichment.get("analyst_rating_label")
                opp["analyst_rating_value"] = enrichment.get("analyst_rating_value")
                opp["analyst_opinions"] = enrichment.get("analyst_opinions")
                opp["target_price_mean"] = enrichment.get("target_price_mean")
                opp["target_price_high"] = enrichment.get("target_price_high")
                opp["target_price_low"] = enrichment.get("target_price_low")

                # Legacy field used by UI
                opp["analyst_rating"] = enrichment.get("analyst_rating_label")

                if debug_enrichment:
                    opp["enrichment_applied"] = True
                    opp["enrichment_sources"] = {"analyst": "db", "iv_rank": "none"}
            else:
                # No fallback: keep deterministic, DB-only behaviour.
                if debug_enrichment:
                    opp["enrichment_applied"] = False
                    opp["enrichment_sources"] = {"analyst": "none", "iv_rank": "none"}

        if debug_enrichment:
            missing_count = max(len(symbols) - len(enrichment_map), 0)
            logging.debug(
                f"Analyst enrichment: {len(enrichment_map)}/{len(symbols)} symbols enriched from DB, "
                f"{missing_count} missing (no live fallback)."
            )

        return opportunities

    except Exception as e:
        logging.warning(f"Analyst enrichment merge failed (non-fatal): {e}")
        # Return opportunities unchanged - don't break response
        return opportunities


def _transform_cc_result(r: Dict) -> tuple:
    """
    Transform stored CC result to API response format.
    
    STABILITY: Sanitizes all float values to prevent JSON serialization errors.
    
    Returns:
        tuple: (transformed_dict, error_info) where error_info is None on success
               or {"symbol": str, "reason": str} on failure
    """
    symbol = r.get("symbol", "UNKNOWN")
    try:
        # Use sanitize_money for 2-decimal precision on monetary fields
        stock_price = sanitize_money(r.get("stock_price", 0))
        strike = sanitize_money(r.get("strike", 0))
        dte = r.get("dte", 0) or 0
        
        # Get values with proper fallbacks (NO undefined → 0 fallbacks for prices)
        # CRITICAL: Use sanitize_money for 2-decimal precision
        premium_bid = sanitize_money(r.get("premium_bid") or r.get("premium"))
        premium_ask = sanitize_money(r.get("premium_ask"))
        premium_used = sanitize_money(r.get("premium_used") or premium_bid)
        iv_decimal = sanitize_float(r.get("iv", 0))
        iv_percent = sanitize_float(r.get("iv_pct", 0))
        
        # VALIDATION: If no premium_bid, this row is invalid
        if not premium_bid or premium_bid <= 0:
            return None, {"symbol": symbol, "reason": "invalid_premium_bid"}
        
        # PRICING POLICY ENFORCEMENT: SELL at BID
        # premium_used MUST equal premium_bid
        if premium_used != premium_bid:
            premium_used = premium_bid  # Force compliance
        
        result = {
        # === EXPLICIT CC SCHEMA ===
        
        # Underlying (MONETARY: 2-decimal)
        "symbol": symbol,
        "stock_price": stock_price,
        
        # MANDATORY MARKET CONTEXT FIELDS (Feb 2026)
        "stock_price_source": r.get("stock_price_source", "SESSION_CLOSE"),
        "session_close_price": sanitize_money(r.get("session_close_price")),
        "prior_close_price": sanitize_money(r.get("prior_close_price")),
        "market_status": r.get("market_status", "UNKNOWN"),
        "as_of": r.get("as_of"),
        
        # Option contract (MONETARY: strike 2-decimal)
        "contract_symbol": r.get("contract_symbol"),
        "strike": strike,
        "expiry": r.get("expiry"),
        "dte": dte,
        "dte_category": r.get("dte_category", "weekly" if dte <= 14 else "monthly"),
        
        # Pricing (EXPLICIT - ALL MONETARY 2-decimal)
        "premium_bid": premium_bid,
        "premium_ask": premium_ask,
        "premium_mid": sanitize_money(r.get("premium_mid")),
        "premium_last": sanitize_money(r.get("premium_last")),
        "premium_prev_close": sanitize_money(r.get("premium_prev_close")),
        "premium_used": premium_used,
        "pricing_rule": r.get("pricing_rule", "SELL_BID"),
        
        # OPTION PARITY MODEL: Display price (matches Yahoo)
        "premium_display": sanitize_money(r.get("premium_display")),
        "premium_display_source": r.get("premium_display_source", "NONE"),
        
        # Legacy alias
        "premium": premium_bid,
        
        # Economics (MONETARY: 2-decimal)
        "premium_yield": sanitize_percentage(r.get("premium_yield", 0)),
        "otm_pct": sanitize_percentage(r.get("otm_pct", 0)),
        "roi_pct": sanitize_percentage(r.get("roi_pct", 0)),
        "roi_annualized": sanitize_percentage(r.get("roi_annualized", 0), 1),
        "max_profit": sanitize_money(r.get("max_profit", premium_bid * 100 if premium_bid else None)),
        "breakeven": sanitize_money(r.get("breakeven", stock_price - premium_bid if stock_price and premium_bid else None)),
        
        # Greeks
        "delta": r.get("delta", 0),
        "delta_source": r.get("delta_source", "BLACK_SCHOLES_APPROX"),
        "gamma": r.get("gamma", 0),
        "theta": r.get("theta", 0),
        "vega": r.get("vega", 0),
        
        # IV (explicit units)
        "iv": iv_decimal,           # Decimal (0.65)
        "iv_pct": iv_percent,       # Percent (65.0)
        "iv_rank": r.get("iv_rank"),  # null if not available
        
        # Liquidity
        "open_interest": r.get("open_interest", 0),
        "volume": r.get("volume", 0),
        
        # Classification
        "is_etf": r.get("is_etf", False),
        "instrument_type": r.get("instrument_type", "STOCK"),
        "market_cap": r.get("market_cap"),
        "avg_volume": r.get("avg_volume"),
        
        # Quality flags
        "quality_flags": r.get("quality_flags", []),
        
        # Analyst (explicit fields for UI consistency)
        "analyst_rating": r.get("analyst_rating"),  # Legacy field
        "analyst_rating_label": r.get("analyst_rating"),  # Explicit label for UI
        "analyst_rating_value": r.get("analyst_rating_value"),  # Numeric value if available
        "analyst_opinions": r.get("analyst_opinions"),  # Count of opinions if available
        
        # Scoring
        "score": r.get("score", 0),
        
        # Metadata (for mock banner logic)
        "data_source": "eod_precomputed",
        "run_id": r.get("run_id"),
        
        # Nested format for backward compatibility
        "underlying": {
            "symbol": symbol,
            "instrument_type": r.get("instrument_type", "STOCK"),
            "last_price": stock_price,
            "price_source": "EOD_SNAPSHOT",
            "market_cap": r.get("market_cap"),
            "avg_volume": r.get("avg_volume")
        },
        "short_call": {
            "strike": strike,
            "expiry": r.get("expiry"),
            "dte": dte,
            "contract_symbol": r.get("contract_symbol"),
            "premium": premium_bid,
            "bid": premium_bid,
            "ask": premium_ask,
            "delta": r.get("delta", 0),
            "gamma": r.get("gamma", 0),
            "theta": r.get("theta", 0),
            "vega": r.get("vega", 0),
            "iv": iv_decimal,
            "iv_pct": iv_percent,
            "open_interest": r.get("open_interest", 0),
            "volume": r.get("volume", 0)
        },
        "economics": {
            "max_profit": sanitize_float(r.get("max_profit", premium_bid * 100 if premium_bid else None)),
            "breakeven": sanitize_float(r.get("breakeven", stock_price - premium_bid if stock_price and premium_bid else None)),
            "roi_pct": sanitize_float(r.get("roi_pct")),
            "annualized_roi_pct": sanitize_float(r.get("roi_annualized")),
            "premium_yield": sanitize_float(r.get("premium_yield")),
            "otm_pct": sanitize_float(r.get("otm_pct"))
        },
        "metadata": {
            "dte_category": r.get("dte_category", "weekly" if dte <= 14 else "monthly"),
            "is_etf": r.get("is_etf", False),
            "data_source": "eod_precomputed"
        },
        "scoring": {
            "final_score": sanitize_float(r.get("score"))
        }
        }
        
        # Sanitize all floats in the result to prevent JSON serialization errors
        return sanitize_dict_floats(result), None
        
    except Exception as e:
        # Log error but don't crash - return None to filter out this row
        logging.warning(f"TRANSFORM_CC_ERROR | symbol={symbol} | error={str(e)[:100]}")
        return None, {"symbol": symbol, "reason": f"exception:{str(e)[:50]}"}


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
    use_eod_contract: bool = Query(True, description="Deprecated - always uses EOD data"),
    debug_enrichment: bool = Query(False, description="Include enrichment debug info"),
    user: dict = Depends(get_current_user)
):
    """
    Screen for Covered Call opportunities.
    
    ARCHITECTURE (Feb 2026): MONGODB READ-ONLY
    ==========================================
    - ALL data comes from pre-computed scan_results_cc collection
    - NO LIVE YAHOO CALLS during request/response cycle
    - Data is pre-computed by EOD pipeline at 4:10 PM ET daily
    - Fallback: precomputed_scans collection (legacy)
    
    Args:
        dte_mode: "weekly" (7-14), "monthly" (21-45), or "all" (7-45)
        risk_profile: "conservative", "moderate", or "aggressive"
        scan_mode: "system", "custom", or "manual" (filter strictness)
    """
    import time
    trace_id = str(uuid.uuid4())[:8]
    start_time = time.time()
    
    try:
        # Determine DTE range based on mode
        if min_dte is None or max_dte is None:
            auto_min_dte, auto_max_dte = get_dte_range(dte_mode)
            min_dte = min_dte if min_dte is not None else auto_min_dte
            max_dte = max_dte if max_dte is not None else auto_max_dte
        
        # Build filter dict
        filters = {
            "min_dte": min_dte,
            "max_dte": max_dte,
            "dte_mode": dte_mode if dte_mode != "all" else None,
            "min_premium_yield": min_premium_yield,
            "max_premium_yield": max_premium_yield,
            "min_otm_pct": min_otm_pct,
            "max_otm_pct": max_otm_pct,
            "risk_profile": risk_profile
        }
        
        # Try EOD pipeline results first
        run_id = await _get_latest_eod_run_id()
        data_source = "eod_pipeline"
        run_info = None
        
        if run_id:
            results = await _get_cc_from_eod(run_id, filters, limit)
            
            # Get run metadata
            run_doc = await db.scan_runs.find_one({"run_id": run_id}, {"_id": 0})
            if run_doc:
                run_info = {
                    "run_id": run_id,
                    "as_of": run_doc.get("as_of"),
                    "completed_at": run_doc.get("completed_at"),
                    "symbols_processed": run_doc.get("symbols_processed"),
                    "symbols_included": run_doc.get("symbols_included")
                }
        else:
            # Fallback to legacy precomputed_scans
            results = await _get_cc_from_legacy(filters, limit)
            data_source = "precomputed_scans_legacy"
        
        # Transform results to API format, tracking dropped rows
        # Per-row exceptions are caught in _transform_cc_result
        opportunities = []
        dropped_rows = 0
        transform_errors = []
        dropped_symbols = []
        
        for r in results:
            transformed, error_info = _transform_cc_result(r)
            if transformed is not None:
                opportunities.append(transformed)
            else:
                dropped_rows += 1
                if error_info:
                    transform_errors.append(error_info)
                    dropped_symbols.append(error_info.get("symbol", "UNKNOWN"))
        
        # Log dropped symbols with trace_id
        if dropped_symbols:
            logging.warning(f"CC_DROPPED_ROWS | trace_id={trace_id} | count={dropped_rows} | symbols={dropped_symbols[:20]}")
        
        # ANALYST ENRICHMENT MERGE (READ-TIME)
        opportunities = await _merge_analyst_enrichment(opportunities, debug_enrichment=debug_enrichment)
        
        elapsed_ms = (time.time() - start_time) * 1000
        logging.info(f"CC Screener: {len(opportunities)} results, {dropped_rows} dropped in {elapsed_ms:.1f}ms from {data_source} trace_id={trace_id}")
        
        return {
            "total": len(opportunities),
            "results": opportunities,
            "opportunities": opportunities,
            "symbols_scanned": run_info.get("symbols_processed", 0) if run_info else 0,
            "symbols_with_results": len(opportunities),
            "run_info": run_info,
            "data_source": data_source,
            "live_data_used": False,  # CRITICAL: No live Yahoo calls
            "layer": 3,
            "scan_mode": scan_mode,
            "dte_mode": dte_mode,
            "dte_range": {"min": min_dte, "max": max_dte},
            "filters_applied": filters,
            "architecture": "EOD_PIPELINE_READ_MODEL",
            "latency_ms": round(elapsed_ms, 1),
            "meta": {
                "dropped_rows": dropped_rows,
                "transform_errors": len(transform_errors),
                "trace_id": trace_id
            }
        }
        
    except Exception as e:
        # STABILITY: Return JSON 500 instead of letting Cloudflare mask the error
        elapsed_ms = (time.time() - start_time) * 1000
        error_msg = str(e)[:500]
        tb = traceback.format_exc()
        
        logging.error(f"COVERED_CALLS_ERROR | trace_id={trace_id} | error={error_msg}")
        logging.error(f"COVERED_CALLS_TRACEBACK | trace_id={trace_id}\n{tb}")
        
        raise HTTPException(
            status_code=500,
            detail={
                "error": error_msg,
                "endpoint": "/api/screener/covered-calls",
                "trace_id": trace_id,
                "latency_ms": round(elapsed_ms, 1)
            }
        )

# ============================================================
# PMCC SCREENER - COMPLETELY ISOLATED FROM CC LOGIC
# ============================================================
# ARCHITECTURE UPDATE (Feb 2026): NO LIVE YAHOO CALLS
# All data comes from pre-computed scan_results_pmcc collection
# ============================================================

# PMCC-specific constants (ISOLATED from CC)
# PMCC Constants - STRICT INSTITUTIONAL MODEL (Feb 2026)
# Must match eod_pipeline.py values exactly
PMCC_MIN_LEAP_DTE = 365   # 12 months minimum
PMCC_MAX_LEAP_DTE = 730   # 24 months maximum (~2 years)
PMCC_MIN_SHORT_DTE = 21   # Minimum 30 days (institutional)
PMCC_MAX_SHORT_DTE = 45   # Maximum 45 days (institutional)
PMCC_MIN_DELTA = 0.75     # Deep ITM for LEAPS (institutional)

# PMCC Price filters (different from CC)
PMCC_STOCK_MIN_PRICE = 30.0
PMCC_STOCK_MAX_PRICE = 90.0


async def _get_pmcc_from_eod(
    run_id: str,
    filters: Dict[str, Any],
    limit: int
) -> List[Dict]:
    """
    Query scan_results_pmcc collection with filters.
    
    NO LIVE YAHOO CALLS - reads from pre-computed data only.
    """
    query = {"run_id": run_id}
    
    # Apply LEAP DTE filter
    if filters.get("min_leap_dte"):
        query["leap_dte"] = {"$gte": filters["min_leap_dte"]}
    if filters.get("max_leap_dte"):
        if "leap_dte" in query:
            query["leap_dte"]["$lte"] = filters["max_leap_dte"]
        else:
            query["leap_dte"] = {"$lte": filters["max_leap_dte"]}
    
    # Apply short DTE filter
    if filters.get("min_short_dte"):
        query["short_dte"] = {"$gte": filters["min_short_dte"]}
    if filters.get("max_short_dte"):
        if "short_dte" in query:
            query["short_dte"]["$lte"] = filters["max_short_dte"]
        else:
            query["short_dte"] = {"$lte": filters["max_short_dte"]}
    
    # Apply delta filter
    if filters.get("min_delta"):
        query["leap_delta"] = {"$gte": filters["min_delta"]}
    
    try:
        cursor = db.scan_results_pmcc.find(
            query,
            {"_id": 0}
        ).sort("score", -1).limit(limit)
        
        results = await cursor.to_list(length=limit)
        return results
    except Exception as e:
        logging.error(f"Failed to query scan_results_pmcc: {e}")
        return []


async def _get_pmcc_from_legacy(filters: Dict[str, Any], limit: int) -> List[Dict]:
    """
    Fallback: Query precomputed_scans collection (legacy).
    
    NO LIVE YAHOO CALLS - reads from pre-computed data only.
    """
    try:
        latest = await db.precomputed_scans.find_one(
            {"type": "pmcc"},
            sort=[("computed_at", -1)]
        )
        
        if not latest:
            return []
        
        results = latest.get("results", [])
        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return results[:limit]
        
    except Exception as e:
        logging.error(f"Failed to query precomputed_scans for PMCC: {e}")
        return []


def _transform_pmcc_result(r: Dict) -> tuple:
    """
    Transform stored PMCC result to API response format.
    
    STABILITY: Uses sanitize_money for 2-decimal precision on all monetary fields.
    POLICY: Enforces BUY=ASK for LEAP, SELL=BID for short.
    
    Returns:
        tuple: (transformed_dict, error_info) where error_info is None on success
               or {"symbol": str, "reason": str} on failure
    """
    symbol = r.get("symbol", "UNKNOWN")
    try:
        # Get values with proper handling (NO undefined → 0 fallbacks for prices)
        # CRITICAL: Use sanitize_money for 2-decimal precision
        short_bid = sanitize_money(r.get("short_bid") or r.get("short_premium"))
        short_ask = sanitize_money(r.get("short_ask"))
        short_used = sanitize_money(r.get("short_used") or short_bid)
        leap_ask = sanitize_money(r.get("leap_ask") or r.get("leaps_ask"))
        leap_bid = sanitize_money(r.get("leap_bid"))
        leap_used = sanitize_money(r.get("leap_used") or leap_ask)
        iv_decimal = sanitize_float(r.get("iv", 0))
        iv_percent = sanitize_float(r.get("iv_pct", 0))
        
        # VALIDATION: If short_bid <= 0, this row is invalid
        if not short_bid or short_bid <= 0:
            return None, {"symbol": symbol, "reason": "invalid_short_bid"}
        
        # PRICING POLICY ENFORCEMENT:
        # BUY LEAP at ASK: leap_used = leap_ask
        # SELL short at BID: short_used = short_bid
        if leap_used != leap_ask:
            leap_used = leap_ask  # Force compliance
        if short_used != short_bid:
            short_used = short_bid  # Force compliance
        
        # Stock price (MONETARY: 2-decimal)
        stock_price = sanitize_money(r.get("stock_price"))
        
        result = {
        # === EXPLICIT PMCC SCHEMA ===
        
        # Underlying (MONETARY: 2-decimal)
        "symbol": symbol,
        "stock_price": stock_price,
        
        # MANDATORY MARKET CONTEXT FIELDS (Feb 2026)
        "stock_price_source": r.get("stock_price_source", "SESSION_CLOSE"),
        "session_close_price": sanitize_money(r.get("session_close_price")),
        "prior_close_price": sanitize_money(r.get("prior_close_price")),
        "market_status": r.get("market_status", "UNKNOWN"),
        "as_of": r.get("as_of"),
        
        # LEAP (Long leg - BUY at ASK) - ALL MONETARY 2-decimal
        "leap_symbol": r.get("leap_symbol"),
        "leap_strike": sanitize_money(r.get("leap_strike")),
        "leap_expiry": r.get("leap_expiry"),
        "leap_dte": r.get("leap_dte"),
        "leap_bid": leap_bid,
        "leap_ask": leap_ask,
        "leap_mid": sanitize_money(r.get("leap_mid")),
        "leap_last": sanitize_money(r.get("leap_last")),
        "leap_prev_close": sanitize_money(r.get("leap_prev_close")),
        "leap_used": leap_used,  # = leap_ask (BUY rule ENFORCED)
        "leap_display": sanitize_money(r.get("leap_display")),
        "leap_display_source": r.get("leap_display_source", "NONE"),
        "leap_delta": sanitize_float(r.get("leap_delta")),
        
        # Short leg (SELL at BID) - ALL MONETARY 2-decimal
        "short_symbol": r.get("short_symbol"),
        "short_strike": sanitize_money(r.get("short_strike")),
        "short_expiry": r.get("short_expiry"),
        "short_dte": r.get("short_dte"),
        "short_bid": short_bid,
        "short_ask": short_ask,
        "short_mid": sanitize_money(r.get("short_mid")),
        "short_last": sanitize_money(r.get("short_last")),
        "short_prev_close": sanitize_money(r.get("short_prev_close")),
        "short_used": short_used,  # = short_bid (SELL rule ENFORCED)
        "short_display": sanitize_money(r.get("short_display")),
        "short_display_source": r.get("short_display_source", "NONE"),
        
        # Pricing rule
        "pricing_rule": r.get("pricing_rule", "BUY_ASK_SELL_BID"),
        
        # Legacy aliases for backward compatibility (MONETARY: 2-decimal)
        "short_premium": short_bid,      # UI uses this
        "leaps_ask": leap_ask,           # UI uses this
        "leaps_premium": leap_ask,       # UI uses this
        
        # Economics
        "net_debit": r.get("net_debit"),
        "net_debit_total": r.get("net_debit_total"),
        "width": r.get("width"),
        "max_profit": r.get("max_profit"),
        "max_profit_total": r.get("max_profit_total"),
        "breakeven": r.get("breakeven"),
        "roi_cycle": r.get("roi_cycle") or r.get("roi_per_cycle"),
        "roi_per_cycle": r.get("roi_per_cycle") or r.get("roi_cycle"),
        "roi_annualized": r.get("roi_annualized"),
        
        # Greeks
        "delta": r.get("delta") or r.get("leap_delta"),
        "delta_source": r.get("delta_source", "BLACK_SCHOLES_APPROX"),
        
        # IV (explicit units)
        "iv": iv_decimal,           # Decimal (0.65)
        "iv_pct": iv_percent,       # Percent (65.0)
        "iv_rank": r.get("iv_rank"),  # null if not available
        
        # Classification
        "is_etf": r.get("is_etf", False),
        "instrument_type": r.get("instrument_type", "STOCK"),
        
        # Quality flags
        "quality_flags": r.get("quality_flags", []),
        
        # Analyst (explicit fields for UI consistency)
        "analyst_rating": r.get("analyst_rating"),  # Legacy field
        "analyst_rating_label": r.get("analyst_rating"),  # Explicit label for UI
        "analyst_rating_value": r.get("analyst_rating_value"),  # Numeric value if available
        "analyst_opinions": r.get("analyst_opinions"),  # Count of opinions if available
        
        # Scoring
        "score": sanitize_float(r.get("score")),
        
        # Metadata (for mock banner logic)
        "data_source": "eod_precomputed",
        "run_id": r.get("run_id")
        }
        
        # Sanitize all floats in the result to prevent JSON serialization errors
        return sanitize_dict_floats(result), None
        
    except Exception as e:
        # Log error but don't crash - return None to filter out this row
        logging.warning(f"TRANSFORM_PMCC_ERROR | symbol={symbol} | error={str(e)[:100]}")
        return None, {"symbol": symbol, "reason": f"exception:{str(e)[:50]}"}


@screener_router.get("/pmcc")
async def screen_pmcc(
    limit: int = Query(50, ge=1, le=200),
    risk_profile: str = Query("moderate", regex="^(conservative|moderate|aggressive)$"),
    min_leap_dte: int = Query(PMCC_MIN_LEAP_DTE, ge=365),
    max_leap_dte: int = Query(PMCC_MAX_LEAP_DTE, le=1095),
    min_short_dte: int = Query(PMCC_MIN_SHORT_DTE, ge=1),
    max_short_dte: int = Query(PMCC_MAX_SHORT_DTE, le=60),
    min_delta: float = Query(PMCC_MIN_DELTA, ge=0.5, le=0.95),
    debug_enrichment: bool = Query(False, description="Include enrichment debug info"),
    user: dict = Depends(get_current_user)
):
    """
    Screen for Poor Man's Covered Call (PMCC) opportunities.
    
    ARCHITECTURE (Feb 2026): MONGODB READ-ONLY
    ==========================================
    - ALL data comes from pre-computed scan_results_pmcc collection
    - NO LIVE YAHOO CALLS during request/response cycle
    - Data is pre-computed by EOD pipeline at 4:10 PM ET daily
    - Fallback: precomputed_scans collection (legacy)
    
    PMCC STRUCTURE (STRICT INSTITUTIONAL RULES):
    - Long leg (LEAPS): 365-730 DTE, ITM, delta >= 0.80, OI >= 100, spread <= 5%
    - Short leg: 30-45 DTE, delta 0.20-0.30, OI >= 100, spread <= 5%
    - Solvency: width > net_debit
    - Break-even: short_strike > (leap_strike + net_debit)
    - Net debit = LEAP ask - Short bid
    """
    import time
    trace_id = str(uuid.uuid4())[:8]
    start_time = time.time()
    
    # Build filter dict
    filters = {
        "min_leap_dte": min_leap_dte,
        "max_leap_dte": max_leap_dte,
        "min_short_dte": min_short_dte,
        "max_short_dte": max_short_dte,
        "min_delta": min_delta,
        "risk_profile": risk_profile
    }
    
    # Try EOD pipeline results first
    run_id = await _get_latest_eod_run_id()
    data_source = "eod_pipeline"
    run_info = None
    
    if run_id:
        results = await _get_pmcc_from_eod(run_id, filters, limit)
        
        # Get run metadata
        run_doc = await db.scan_runs.find_one({"run_id": run_id}, {"_id": 0})
        if run_doc:
            run_info = {
                "run_id": run_id,
                "as_of": run_doc.get("as_of"),
                "completed_at": run_doc.get("completed_at")
            }
    else:
        # Fallback to legacy precomputed_scans
        results = await _get_pmcc_from_legacy(filters, limit)
        data_source = "precomputed_scans_legacy"
    
    # Transform results to API format, tracking dropped rows
    opportunities = []
    dropped_rows = 0
    transform_errors = []
    dropped_symbols = []
    
    for r in results:
        transformed, error_info = _transform_pmcc_result(r)
        if transformed is not None:
            opportunities.append(transformed)
        else:
            dropped_rows += 1
            if error_info:
                transform_errors.append(error_info)
                dropped_symbols.append(error_info.get("symbol", "UNKNOWN"))
    
    # Log dropped symbols with trace_id
    if dropped_symbols:
        logging.warning(f"PMCC_DROPPED_ROWS | trace_id={trace_id} | count={dropped_rows} | symbols={dropped_symbols[:20]}")
    
    # ANALYST ENRICHMENT MERGE (READ-TIME)
    opportunities = await _merge_analyst_enrichment(opportunities, debug_enrichment=debug_enrichment)
    
    elapsed_ms = (time.time() - start_time) * 1000
    logging.info(f"PMCC Screener: {len(opportunities)} results, {dropped_rows} dropped in {elapsed_ms:.1f}ms from {data_source} trace_id={trace_id}")
    
    return {
        "total": len(opportunities),
        "results": opportunities,
        "opportunities": opportunities,
        "run_info": run_info,
        "data_source": data_source,
        "live_data_used": False,  # CRITICAL: No live Yahoo calls
        "layer": 3,
        "filters_applied": filters,
        "dte_thresholds": {
            "leap": {"min": min_leap_dte, "max": max_leap_dte},
            "short": {"min": min_short_dte, "max": max_short_dte}
        },
        "architecture": "EOD_PIPELINE_READ_MODEL",
        "latency_ms": round(elapsed_ms, 1),
        "meta": {
            "dropped_rows": dropped_rows,
            "transform_errors": len(transform_errors),
            "trace_id": trace_id
        }
    }
@screener_router.get("/dashboard-opportunities")
async def get_dashboard_opportunities(
    debug_enrichment: bool = Query(False, description="Include enrichment debug info"),
    user: dict = Depends(get_current_user)
):
    """
    Get top opportunities for dashboard display.
    
    Returns Top 5 Weekly + Top 5 Monthly covered calls for dashboard display.
    
    ARCHITECTURE (Feb 2026): MONGODB READ-ONLY
    ==========================================
    - Reads directly from scan_results_cc collection
    - NO LIVE YAHOO CALLS during request/response cycle
    - Fallback: precomputed_scans collection (legacy)
    """
    import time
    start_time = time.time()
    
    # Get latest EOD run
    run_id = await _get_latest_eod_run_id()
    
    if run_id:
        # Query directly from scan_results_cc - sorted by score
        cursor = db.scan_results_cc.find(
            {"run_id": run_id},
            {"_id": 0}
        ).sort("score", -1).limit(100)
        
        results = await cursor.to_list(length=100)
        data_source = "eod_pipeline"
        
        # Get run info
        run_doc = await db.scan_runs.find_one({"run_id": run_id}, {"_id": 0})
        run_info = {
            "run_id": run_id,
            "as_of": run_doc.get("as_of") if run_doc else None,
            "completed_at": run_doc.get("completed_at") if run_doc else None
        }
    else:
        # Fallback to legacy
        results = await _get_cc_from_legacy({}, 100)
        data_source = "precomputed_scans_legacy"
        run_info = None
    
    # Transform results
    opportunities = [_transform_cc_result(r) for r in results]
    
    # Separate into weekly (DTE <= 14) and monthly (DTE > 14)
    weekly_opps = [opp for opp in opportunities if opp.get("dte", 0) <= WEEKLY_MAX_DTE]
    monthly_opps = [opp for opp in opportunities if opp.get("dte", 0) > WEEKLY_MAX_DTE]
    
    # Sort each by score descending
    weekly_opps.sort(key=lambda x: x.get("score", 0), reverse=True)
    monthly_opps.sort(key=lambda x: x.get("score", 0), reverse=True)
    
    # Take top 5 from each
    top_weekly = weekly_opps[:5]
    top_monthly = monthly_opps[:5]
    
    # Mark with expiry_type
    for opp in top_weekly:
        opp["expiry_type"] = "Weekly"
    for opp in top_monthly:
        opp["expiry_type"] = "Monthly"
    
    # Combine
    combined = top_weekly + top_monthly
    
    # ANALYST ENRICHMENT MERGE (READ-TIME)
    combined = await _merge_analyst_enrichment(combined, debug_enrichment=debug_enrichment)
    
    elapsed_ms = (time.time() - start_time) * 1000
    
    return {
        "total": len(combined),
        "opportunities": combined,
        "weekly_count": len([o for o in combined if o.get("expiry_type") == "Weekly"]),
        "monthly_count": len([o for o in combined if o.get("expiry_type") == "Monthly"]),
        "weekly_opportunities": [o for o in combined if o.get("expiry_type") == "Weekly"],
        "monthly_opportunities": [o for o in combined if o.get("expiry_type") == "Monthly"],
        "weekly_available": len(weekly_opps),
        "monthly_available": len(monthly_opps),
        "run_info": run_info,
        "data_source": data_source,
        "live_data_used": False,  # CRITICAL: No live Yahoo calls
        "layer": 3,
        "architecture": "EOD_PIPELINE_READ_MODEL",
        "latency_ms": round(elapsed_ms, 1)
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
    
    Returns structured metrics for Data Quality tab including:
    - Universe breakdown with exclusion counts by stage and reason
    - Run ID for drilldown queries
    - Real-time computed values from scan/snapshot data
    
    Exclusion Stages:
    - QUOTE: Failed to fetch stock quote
    - LIQUIDITY_FILTER: Failed liquidity/price band checks
    - OPTIONS_CHAIN: Failed to fetch options chain
    - CHAIN_QUALITY: Chain is empty or stale
    - CONTRACT_QUALITY: Missing required contract fields
    - OTHER: Forced test exclusion or unknown
    
    Exclusion Reasons:
    - MISSING_QUOTE: No stock quote available
    - LOW_LIQUIDITY_RANK: Dollar volume below threshold
    - OUT_OF_PRICE_BAND: Price outside min/max range
    - MISSING_CHAIN: No options chain available
    - CHAIN_EMPTY: Options chain has no contracts
    - BAD_CHAIN_DATA: Stale or invalid chain data
    - MISSING_CONTRACT_FIELDS: Contracts missing bid/ask/delta
    - OTHER: Forced exclusion or unknown error
    """
    import uuid
    from utils.environment import is_production
    
    # ================================================================
    # FAST READ-ONLY MODE: Read from scan_run_summary (denormalized)
    # No aggregation across audit rows - single document lookup
    # ================================================================
    
    now_utc = datetime.now(timezone.utc)
    total_symbols = len(SCAN_SYMBOLS)
    
    # Get tier counts from universe builder (cached)
    tier_counts = get_tier_counts()
    
    # ================================================================
    # QUERY LATEST COMPLETED SCAN RUN (status=COMPLETED only)
    # Fallback to any latest run if no COMPLETED runs exist (for backward compat)
    # ================================================================
    latest_completed = await db.scan_run_summary.find_one(
        {"status": "COMPLETED"},
        sort=[("as_of", -1)]
    )
    
    # Also check for any latest run (regardless of status)
    latest_any = await db.scan_run_summary.find_one(
        {},
        sort=[("as_of", -1)]
    )
    
    # Determine run_in_progress flag
    run_in_progress = False
    if latest_any and latest_completed:
        run_in_progress = (
            latest_any.get("run_id") != latest_completed.get("run_id") and
            latest_any.get("status") not in ("COMPLETED", "FAILED")
        )
    elif latest_any and not latest_completed:
        # No completed runs, check if latest is in progress
        run_in_progress = latest_any.get("status") not in ("COMPLETED", "FAILED", None)
    
    # Use latest COMPLETED run, or fallback to latest any run (backward compat)
    latest_summary = latest_completed or latest_any
    
    if latest_summary:
        # Fast path: read pre-computed values from summary document
        run_id = latest_summary.get("run_id")
        last_audit_at = latest_summary.get("as_of")
        structure_valid = latest_summary.get("included", 0)
        total_excluded = latest_summary.get("excluded", 0)
        valid_chains = latest_summary.get("chain_success_count", structure_valid)
        
        # New metrics for Data Quality scoring
        # Calculate coverage_ratio if not stored (backward compat)
        total_symbols_from_summary = latest_summary.get("total_symbols", total_symbols)
        if latest_summary.get("coverage_ratio") is not None:
            coverage_ratio = latest_summary.get("coverage_ratio", 0)
        else:
            coverage_ratio = valid_chains / total_symbols_from_summary if total_symbols_from_summary > 0 else 0
        
        throttle_ratio = latest_summary.get("throttle_ratio", 0)
        rate_limited_chain_count = latest_summary.get("rate_limited_chain_count", 0)
        missing_quote_fields_count = latest_summary.get("missing_quote_fields_count", 0)
        
        # Status handling (backward compat: treat missing status as COMPLETED if data exists)
        run_status = latest_summary.get("status")
        if run_status is None and structure_valid > 0:
            run_status = "COMPLETED"  # Assume old successful runs are completed
        elif run_status is None:
            run_status = "UNKNOWN"
        
        run_duration = latest_summary.get("duration_seconds", 0)
        
        # Pre-computed exclusion breakdowns
        excluded_counts_by_stage = latest_summary.get("excluded_counts_by_stage", {})
        excluded_counts_by_reason = latest_summary.get("excluded_counts_by_reason", {})
        
        # Use tier_counts from summary if available, else from universe builder
        if latest_summary.get("tier_counts"):
            tier_counts = latest_summary["tier_counts"]
        
        # Legacy format for backward compatibility + new categories
        excluded_counts = {
            "OUT_OF_RULES": 0,
            "OUT_OF_PRICE_BAND": excluded_counts_by_reason.get("OUT_OF_PRICE_BAND", 0),
            "LOW_LIQUIDITY": excluded_counts_by_reason.get("LOW_LIQUIDITY_RANK", 0),
            "MISSING_QUOTE": excluded_counts_by_reason.get("MISSING_QUOTE", 0),
            "MISSING_QUOTE_FIELDS": excluded_counts_by_reason.get("MISSING_QUOTE_FIELDS", 0),
            "MISSING_CHAIN": excluded_counts_by_reason.get("MISSING_CHAIN", 0),
            "RATE_LIMITED_CHAIN": excluded_counts_by_reason.get("RATE_LIMITED_CHAIN", 0),
            "CHAIN_EMPTY": excluded_counts_by_reason.get("CHAIN_EMPTY", 0),
            "BAD_CHAIN_DATA": excluded_counts_by_reason.get("BAD_CHAIN_DATA", 0),
            "MISSING_CONTRACT_FIELDS": excluded_counts_by_reason.get("MISSING_CONTRACT_FIELDS", 0),
            "OTHER": excluded_counts_by_reason.get("OTHER", 0)
        }
        
    else:
        # Fallback: Try reading from audit collection (slower path)
        run_status = "UNKNOWN"
        run_duration = 0
        coverage_ratio = 0
        throttle_ratio = 0
        rate_limited_chain_count = 0
        missing_quote_fields_count = 0
        
        latest_run = await db.scan_universe_audit.find_one(
            {},
            sort=[("as_of", -1)],
            projection={"run_id": 1, "as_of": 1}
        )
        
        if latest_run:
            run_id = latest_run["run_id"]
            last_audit_at = latest_run["as_of"]
            
            # Count included/excluded (uses index)
            structure_valid = await db.scan_universe_audit.count_documents({"run_id": run_id, "included": True})
            total_excluded = await db.scan_universe_audit.count_documents({"run_id": run_id, "included": False})
            valid_chains = structure_valid
            
            # Minimal aggregation for breakdowns (uses indexes)
            stage_pipeline = [
                {"$match": {"run_id": run_id, "included": False, "exclude_stage": {"$ne": None}}},
                {"$group": {"_id": "$exclude_stage", "count": {"$sum": 1}}}
            ]
            stage_results = await db.scan_universe_audit.aggregate(stage_pipeline).to_list(100)
            excluded_counts_by_stage = {}
            for r in stage_results:
                excluded_counts_by_stage[r["_id"]] = r["count"]
            
            reason_pipeline = [
                {"$match": {"run_id": run_id, "included": False, "exclude_reason": {"$ne": None}}},
                {"$group": {"_id": "$exclude_reason", "count": {"$sum": 1}}}
            ]
            reason_results = await db.scan_universe_audit.aggregate(reason_pipeline).to_list(100)
            excluded_counts_by_reason = {}
            for r in reason_results:
                excluded_counts_by_reason[r["_id"]] = r["count"]
            
            excluded_counts = {
                "OUT_OF_RULES": 0,
                "OUT_OF_PRICE_BAND": excluded_counts_by_reason.get("OUT_OF_PRICE_BAND", 0),
                "LOW_LIQUIDITY": excluded_counts_by_reason.get("LOW_LIQUIDITY_RANK", 0),
                "MISSING_QUOTE": excluded_counts_by_reason.get("MISSING_QUOTE", 0),
                "MISSING_CHAIN": excluded_counts_by_reason.get("MISSING_CHAIN", 0),
                "CHAIN_EMPTY": excluded_counts_by_reason.get("CHAIN_EMPTY", 0),
                "BAD_CHAIN_DATA": excluded_counts_by_reason.get("BAD_CHAIN_DATA", 0),
                "MISSING_CONTRACT_FIELDS": excluded_counts_by_reason.get("MISSING_CONTRACT_FIELDS", 0),
                "OTHER": excluded_counts_by_reason.get("OTHER", 0)
            }
        else:
            # No audit data yet - return empty/placeholder stats
            run_id = None
            last_audit_at = None
            structure_valid = 0
            total_excluded = 0
            valid_chains = 0
            excluded_counts_by_stage = {}
            excluded_counts_by_reason = {}
            excluded_counts = {
                "OUT_OF_RULES": 0, "OUT_OF_PRICE_BAND": 0, "LOW_LIQUIDITY": 0,
                "MISSING_QUOTE": 0, "MISSING_QUOTE_FIELDS": 0, "MISSING_CHAIN": 0,
                "RATE_LIMITED_CHAIN": 0, "CHAIN_EMPTY": 0,
                "BAD_CHAIN_DATA": 0, "MISSING_CONTRACT_FIELDS": 0, "OTHER": 0
            }
    
    # ================================================================
    # Calculate derived metrics
    # ================================================================
    chain_valid_pct = round((valid_chains / total_symbols * 100), 1) if total_symbols > 0 else 0
    structure_valid_pct = round((structure_valid / total_symbols * 100), 1) if total_symbols > 0 else 0
    
    # Get last COMPLETED scan run time (not partial/failed runs)
    last_completed_run = await db.scan_runs.find_one(
        {"status": "COMPLETED"},
        sort=[("as_of", -1)],
        projection={"as_of": 1, "completed_at": 1}
    )
    last_full_run_at = last_completed_run.get("completed_at") if last_completed_run else last_audit_at
    
    # ================================================================
    # HEALTH SCORE CALCULATION - STATUS-BASED (no flip-flopping)
    # ================================================================
    # Thresholds:
    # - CRITICAL (0-25): status != COMPLETED OR coverage < 25%
    # - WARNING (26-50): coverage 25-50% OR throttle_ratio > 30%
    # - HEALTHY (51-100): coverage > 50%
    #
    # DO NOT score CRITICAL just because opportunities=0 (strict PMCC may yield 0)
    
    if run_status != "COMPLETED":
        # Status not COMPLETED = CRITICAL
        health_score = 10
        health_status = "CRITICAL"
    elif coverage_ratio < 0.25:
        # Coverage below 25% = CRITICAL
        health_score = 20
        health_status = "CRITICAL"
    elif coverage_ratio < 0.50 or throttle_ratio > 0.30:
        # Coverage 25-50% OR high throttle = WARNING
        health_score = 40 + int(coverage_ratio * 20)
        health_status = "WARNING"
    else:
        # Coverage > 50% = HEALTHY
        health_score = 60 + int(coverage_ratio * 40)
        health_status = "HEALTHY"
    
    # Cap at 100
    health_score = min(100, health_score)
    
    # Score distribution (would need to query precomputed_scans for real data)
    scored_trades = structure_valid  # Approximation
    score_high = 0
    score_medium_high = 0
    score_medium = 0
    score_low = 0
    
    # Get market state
    current_market_state = get_market_state()
    
    # Normalize market state for frontend compatibility
    if current_market_state == "EXTENDED":
        current_market_state = "AFTERHOURS"
    
    # Determine price source based on market state
    # FREEZE AT MARKET CLOSE POLICY: Outside OPEN, always report PREV_CLOSE
    if current_market_state == "OPEN":
        price_source = "LIVE"
    else:
        # CLOSED, AFTERHOURS, PREMARKET all use frozen previous close
        price_source = "PREV_CLOSE"
    
    # Get score distribution from precomputed scans
    try:
        # Aggregate score distribution from all precomputed scans
        all_scans = await db.precomputed_scans.find({"type": {"$in": ["cc", "pmcc"]}}).to_list(length=10)
        scored_trades = 0
        score_high = 0
        score_medium_high = 0
        score_medium = 0
        score_low = 0
        for scan in all_scans:
            opportunities = scan.get("opportunities", [])
            for opp in opportunities:
                score = opp.get("score", 0)
                scored_trades += 1
                if score >= 70:
                    score_high += 1
                elif score >= 50:
                    score_medium_high += 1
                elif score >= 30:
                    score_medium += 1
                else:
                    score_low += 1
    except Exception as e:
        logging.error(f"Error fetching precomputed scan data: {e}")
        scored_trades = structure_valid
        score_high = 0
        score_medium_high = 0
        score_medium = 0
        score_low = 0
    
    # Calculate rejected count
    rejected = total_symbols - structure_valid
    
    # Note: tier_counts already fetched at start of function
    
    return {
        "run_id": run_id,
        "run_type": "EOD",
        "run_status": run_status if latest_summary else "UNKNOWN",  # NEW: status flag
        "run_in_progress": run_in_progress,  # NEW: show if another run is in progress
        "health_score": health_score,
        "health_status": health_status,  # NEW: CRITICAL/WARNING/HEALTHY
        "last_full_run_at": last_full_run_at.isoformat() if last_full_run_at else None,
        "run_duration_seconds": run_duration if latest_summary else None,  # NEW
        "market_state": current_market_state,
        "price_source": price_source,
        "underlying_price_source": price_source,  # Alias for frontend compatibility
        "as_of": now_utc.isoformat(),
        
        # NEW: Coverage and throttle metrics for debugging
        "coverage_ratio": round(coverage_ratio, 4) if latest_summary else None,
        "throttle_ratio": round(throttle_ratio, 4) if latest_summary else None,
        "rate_limited_chain_count": rate_limited_chain_count if latest_summary else None,
        "missing_quote_fields_count": missing_quote_fields_count if latest_summary else None,
        
        "universe": {
            "source": "INDEX_PLUS_LIQUIDITY",
            "notes": "S&P 500 + Nasdaq 100 + ETF whitelist + optional expansion",
            "total_candidates": total_symbols,
            "included": structure_valid,
            "excluded": total_excluded,
            "excluded_counts": excluded_counts,  # Legacy format
            "excluded_counts_by_stage": excluded_counts_by_stage,
            "excluded_counts_by_reason": excluded_counts_by_reason,
            # Phase 2: Tier breakdown
            "tier_counts": tier_counts
        },
        "eligibility": {
            "universe_scanned": total_symbols,
            "chain_valid": valid_chains,
            "chain_valid_pct": chain_valid_pct,
            "structure_valid": structure_valid,
            "structure_valid_pct": structure_valid_pct,
            "scored_trades": scored_trades,
            "rejected": rejected
        },
        "score_distribution": {
            "high": score_high,
            "medium_high": score_medium_high,
            "medium": score_medium,
            "low": score_low
        },
        "total_opportunities": scored_trades,
        "symbols_scanned": total_symbols,
        "average_score": None,  # Would require computation across all opportunities
        "score_drift": None,  # Would require historical comparison
        "outlier_swings": None,  # Would require historical comparison
        "cache_status": "valid" if valid_chains > 0 else "stale",
        "cache_updated_at": last_full_run_at.isoformat() if last_full_run_at else None,
        "api_errors_24h": None,  # Would require error logging system
        "scheduler_running": True  # APScheduler is running if we got here
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
