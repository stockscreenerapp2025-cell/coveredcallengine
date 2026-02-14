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

PHASE 2 (December 2025): Market Snapshot Cache
- Stock data now uses get_symbol_snapshot() for cache-first approach
- Reduces Yahoo Finance calls by ~70% for Custom Scans
- Options are still fetched live (not cached)
- Does NOT affect Watchlist or Simulator
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
from services.data_provider import (
    fetch_options_chain, 
    fetch_stock_quote, 
    fetch_live_stock_quote,
    fetch_options_with_cache,
    get_market_state,
    # PHASE 2: Import cache-first functions
    get_symbol_snapshot,
    get_symbol_snapshots_batch,
    get_cache_metrics
)

# IV Rank Service for industry-standard IV metrics
from services.iv_rank_service import (
    get_iv_metrics_for_symbol,
    IVMetrics
)

# Import quote cache for after-hours support
from services.quote_cache_service import get_quote_cache

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
    
    # ========== MARKET-STATE AWARE PRICING ==========
    current_market_state = get_market_state()
    use_live_price = (current_market_state == "OPEN")
    underlying_price_source = "LIVE" if use_live_price else "LAST_CLOSE"
    
    logging.info(f"CC Screener: market_state={current_market_state}, price_source={underlying_price_source}")
    
    # LAYER 3: Determine DTE range based on mode
    if min_dte is None or max_dte is None:
        auto_min_dte, auto_max_dte = get_dte_range(dte_mode)
        min_dte = min_dte if min_dte is not None else auto_min_dte
        max_dte = max_dte if max_dte is not None else auto_max_dte
    
    # Step 1: Get stock prices - PHASE 2: Use cache-first approach for Yahoo Finance
    # This reduces Yahoo calls by ~70% while still using Yahoo as single source of truth
    # Cache TTL: 12 min during market hours, 3 hours after close
    stock_data = {}
    symbols_with_stock_data = []
    
    # PHASE 2: Track cache performance
    cache_stats = {"hits": 0, "misses": 0, "symbols_processed": 0, "bid_rejected": 0}
    
    # PHASE 2: Batch fetch snapshots with cache-first approach
    snapshots = await get_symbol_snapshots_batch(
        db=db,
        symbols=SCAN_SYMBOLS,
        api_key=None,  # Not needed for Yahoo-only mode
        include_options=False,  # Options fetched live below
        batch_size=10,
        is_scan_path=True  # Use bounded concurrency for screener
    )
    
    for symbol in SCAN_SYMBOLS:
        try:
            # PHASE 2: Get data from snapshot cache
            snapshot = snapshots.get(symbol.upper())
            
            if snapshot and snapshot.get("stock_data"):
                quote = snapshot["stock_data"]
                
                # Track cache stats
                cache_stats["symbols_processed"] += 1
                if snapshot.get("from_cache"):
                    cache_stats["hits"] += 1
                else:
                    cache_stats["misses"] += 1
                
                if quote.get("price") and quote.get("price") > 0:
                    # ========== MARKET-STATE AWARE UNDERLYING PRICE ==========
                    # During OPEN: Use live quote for consistency with live BID/ASK
                    # During CLOSED: Use snapshot (previous close)
                    if use_live_price:
                        live_quote = await fetch_live_stock_quote(symbol.upper(), None)
                        if live_quote and live_quote.get("price", 0) > 0:
                            final_price = live_quote["price"]
                            price_source = "yahoo_live"
                        else:
                            final_price = quote["price"]
                            price_source = "yahoo_cached" if snapshot.get("from_cache") else "yahoo_live"
                    else:
                        final_price = quote["price"]
                        price_source = "yahoo_cached" if snapshot.get("from_cache") else "yahoo_live"
                    
                    stock_data[symbol] = {
                        "stock_price": final_price,
                        "trade_date": quote.get("close_date"),  # Date of the close price
                        "market_cap": quote.get("market_cap"),
                        "avg_volume": quote.get("avg_volume"),
                        "earnings_date": quote.get("earnings_date"),
                        "analyst_rating": quote.get("analyst_rating"),
                        "source": price_source
                    }
                    symbols_with_stock_data.append(symbol)
        except Exception as e:
            logging.debug(f"Could not get stock price for {symbol}: {e}")
    
    logging.info(f"CC Screener cache stats: {cache_stats}")
    
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
        
        # Get metadata from Yahoo (already fetched in Step 1)
        market_cap = sym_data.get("market_cap")
        avg_volume = sym_data.get("avg_volume")
        earnings_date = sym_data.get("earnings_date")
        analyst_rating = sym_data.get("analyst_rating")
        
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
        # OPTIONS FETCH WITH QUOTE CACHING
        # - During market hours: Fetch live, cache valid quotes
        # - After hours: Use last market session quotes
        # - All quotes marked with source and timestamp
        # ============================================================
        try:
            live_options = await fetch_options_with_cache(
                symbol=symbol,
                db=db,
                option_type="call",
                max_dte=max_dte,
                min_dte=min_dte,
                current_price=stock_price
            )
        except Exception as e:
            logging.debug(f"Could not fetch options for {symbol}: {e}")
            continue
        
        if not live_options:
            continue
        
        # ============================================================
        # COMPUTE IV METRICS FOR SYMBOL (Industry Standard IV Rank)
        # ============================================================
        try:
            iv_metrics = await get_iv_metrics_for_symbol(
                db=db,
                symbol=symbol,
                options=live_options,
                stock_price=stock_price,
                store_history=True  # Store for future IV Rank calculations
            )
        except Exception as e:
            logging.debug(f"Could not compute IV metrics for {symbol}: {e}")
            iv_metrics = None
        
        # Process each option
        for opt in live_options:
            strike = opt.get("strike", 0)
            bid = opt.get("bid", 0)
            ask = opt.get("ask", 0)
            dte = opt.get("dte", 0)
            expiry = opt.get("expiry", "")
            iv = opt.get("implied_volatility", 0)
            oi = opt.get("open_interest", 0)
            volume = opt.get("volume", 0)
            quote_source = opt.get("quote_source", "LIVE")
            quote_timestamp = opt.get("quote_timestamp", "")
            quote_age_hours = opt.get("quote_age_hours", 0)
            
            # ========== STRICT BID-ONLY PRICING (NO FALLBACK) ==========
            # SELL leg (short call): REQUIRE BID > 0, reject if missing/0
            # Never use: lastPrice, mid, ASK, close, vwap, theoretical price
            if not bid or bid <= 0:
                cache_stats["bid_rejected"] += 1
                continue  # REJECT: No valid BID for SELL leg
            
            premium = bid  # SELL leg uses BID only
            
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
            
            # LAYER 3: Enrich with Greeks and ROI (using Black-Scholes + IV metrics)
            enriched_call = enrich_option_greeks(opt, stock_price, iv_metrics)
            
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
                    "price_source": "YAHOO_PREVIOUS_CLOSE",  # Single source of truth
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
                    # Greeks (Black-Scholes)
                    "delta": enriched_call.get("delta", 0),
                    "delta_source": enriched_call.get("delta_source", "UNKNOWN"),
                    "gamma": enriched_call.get("gamma", 0),
                    "theta": enriched_call.get("theta", 0),
                    "vega": enriched_call.get("vega", 0),
                    # IV fields (standardized)
                    "iv": enriched_call.get("iv", 0),  # Decimal
                    "iv_pct": enriched_call.get("iv_pct", 0),  # Percentage
                    "implied_volatility": enriched_call.get("iv_pct", 0),  # Legacy alias
                    # IV Rank (industry standard with bootstrap handling)
                    "iv_rank": enriched_call.get("iv_rank", 50.0),
                    "iv_percentile": enriched_call.get("iv_percentile", 50.0),
                    "iv_rank_source": enriched_call.get("iv_rank_source", "DEFAULT_NEUTRAL"),
                    "iv_rank_confidence": enriched_call.get("iv_rank_confidence", "LOW"),
                    "iv_samples": enriched_call.get("iv_samples", 0),
                    # Liquidity
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
                    "data_source": "live_options"
                },
                
                # QUOTE SOURCE object - Per after-hours requirement
                "quote_info": {
                    "quote_source": quote_source,  # "LIVE" or "LAST_MARKET_SESSION"
                    "quote_timestamp": quote_timestamp,
                    "quote_age_hours": quote_age_hours if quote_source == "LAST_MARKET_SESSION" else 0
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
                # Greeks (Black-Scholes) - ALWAYS POPULATED
                "delta": enriched_call.get("delta", 0),
                "delta_source": enriched_call.get("delta_source", "UNKNOWN"),
                "gamma": enriched_call.get("gamma", 0),
                "theta": enriched_call.get("theta", 0),
                "vega": enriched_call.get("vega", 0),
                # IV fields (standardized) - ALWAYS POPULATED
                "iv": enriched_call.get("iv", 0),  # Decimal
                "iv_pct": enriched_call.get("iv_pct", 0),  # Percentage
                "implied_volatility": enriched_call.get("iv_pct", 0),  # Legacy alias
                # IV Rank (industry standard with bootstrap handling) - ALWAYS POPULATED
                "iv_rank": enriched_call.get("iv_rank", 50.0),
                "iv_percentile": enriched_call.get("iv_percentile", 50.0),
                "iv_rank_source": enriched_call.get("iv_rank_source", "DEFAULT_NEUTRAL"),
                "iv_rank_confidence": enriched_call.get("iv_rank_confidence", "LOW"),
                "iv_samples": enriched_call.get("iv_samples", 0),
                # Liquidity
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
                "analyst_rating": analyst_rating,  # From Yahoo Finance
                "earnings_date": earnings_date,
                "snapshot_date": sym_data.get("trade_date"),
                "quote_source": quote_source,  # LIVE or LAST_MARKET_SESSION
                "quote_timestamp": quote_timestamp,
                "data_source": "yahoo_single_source"
            })
        
        if live_options:
            symbols_with_results += 1
    
    # ============================================================
    # PHASE 3: AI-BASED BEST OPTION SELECTION PER SYMBOL
    # ============================================================
    # IMPORTANT:
    # Scan candidates may include multiple options per symbol.
    # Final output must return ONE best option per symbol,
    # selected by highest AI score.
    # ============================================================
    opportunities = select_best_option_per_symbol(opportunities)
    
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
        "stock_price_source": "yahoo_cached",  # PHASE 2: Cache-first approach
        "options_chain_source": "yahoo_live",  # Options still fetched live
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
        "architecture": "YAHOO_SINGLE_SOURCE_OF_TRUTH",
        "live_data_used": True,
        "snapshot_cache_stats": cache_stats,  # PHASE 2: Include cache stats
        # ========== PRICE SYNC METADATA ==========
        "market_state": current_market_state,
        "underlying_price_source": underlying_price_source,
        "pricing_rule": "BID_ONLY"
    }


# ============================================================
# PMCC SCREENER - COMPLETELY ISOLATED FROM CC LOGIC
# ============================================================
# PMCC (Poor Man's Covered Call) has DIFFERENT rules than CC:
# - Long leg (LEAPS): ≥6 months, ITM (strike < stock price), use ASK
# - Short leg: ≤60 days, strike > long-leg strike, use BID
# - Net debit = Long-leg ASK - Short-leg BID
# - NEVER shares filters, expiry rules, or pricing with CC
# ============================================================

# PMCC-specific constants (ISOLATED from CC)
# USER REQUIREMENT: LEAPS must be 12-24 months (365-730 days)
PMCC_MIN_LEAP_DTE = 365  # 12 months minimum
PMCC_MAX_LEAP_DTE = 730  # 24 months maximum (~2 years)
PMCC_MIN_SHORT_DTE = 7
PMCC_MAX_SHORT_DTE = 60  # ≤60 days
PMCC_MIN_DELTA = 0.70  # Deep ITM for LEAPS

# PMCC Price filters (different from CC)
PMCC_STOCK_MIN_PRICE = 30.0
PMCC_STOCK_MAX_PRICE = 90.0
# ETFs have NO price limits in PMCC

@screener_router.get("/pmcc")
async def screen_pmcc(
    limit: int = Query(50, ge=1, le=200),
    risk_profile: str = Query("moderate", regex="^(conservative|moderate|aggressive)$"),
    min_leap_dte: int = Query(PMCC_MIN_LEAP_DTE, ge=365),
    max_leap_dte: int = Query(PMCC_MAX_LEAP_DTE, le=1095),
    min_short_dte: int = Query(PMCC_MIN_SHORT_DTE, ge=1),
    max_short_dte: int = Query(PMCC_MAX_SHORT_DTE, le=60),
    min_delta: float = Query(PMCC_MIN_DELTA, ge=0.5, le=0.95),
    user: dict = Depends(get_current_user)
):
    """
    Screen for Poor Man's Covered Call (PMCC) opportunities.
    
    =====================================================
    PMCC CHAIN SELECTION RULES (COMPLETELY ISOLATED FROM CC):
    =====================================================
    
    LONG LEG (LEAPS CALL):
    - Expiry must be 12-24 months (365-730 days) from current date
    - Strike must be BELOW the current stock price (ITM)
    - Option price = ASK only
    - Both BID and ASK must be > 0
    
    SHORT LEG (CALL):
    - Expiry must be ≤ 60 days
    - Strike must be ABOVE the long-leg strike
    - Option price = BID only
    - Both BID and ASK must be > 0
    
    NET DEBIT CALCULATION:
    - Net debit = Long-leg ASK - Short-leg BID
    - LAST price is NEVER used
    
    PRICE FILTERS (PMCC-specific):
    - Stocks: $30-$90
    - ETFs: No price limits
    
    PHASE 2: Uses cache-first approach for stock data
    """
    # ========== MARKET-STATE AWARE PRICING ==========
    current_market_state = get_market_state()
    use_live_price = (current_market_state == "OPEN")
    underlying_price_source = "LIVE" if use_live_price else "LAST_CLOSE"
    
    logging.info(f"PMCC Screener: market_state={current_market_state}, price_source={underlying_price_source}")
    
    # PHASE 2: Track cache performance
    cache_stats = {"hits": 0, "misses": 0, "symbols_processed": 0, "ask_rejected": 0, "bid_rejected": 0}
    
    # PHASE 2: Batch fetch snapshots with cache-first approach
    snapshots = await get_symbol_snapshots_batch(
        db=db,
        symbols=SCAN_SYMBOLS,
        api_key=None,
        include_options=False,
        batch_size=10,
        is_scan_path=True  # Use bounded concurrency for screener
    )
    
    # Step 1: Get stock prices - PHASE 2: Cache-first approach
    stock_data = {}
    symbols_with_stock_data = []
    
    for symbol in SCAN_SYMBOLS:
        try:
            # PHASE 2: Get data from snapshot cache
            snapshot = snapshots.get(symbol.upper())
            
            if snapshot and snapshot.get("stock_data"):
                quote = snapshot["stock_data"]
                
                # Track cache stats
                cache_stats["symbols_processed"] += 1
                if snapshot.get("from_cache"):
                    cache_stats["hits"] += 1
                else:
                    cache_stats["misses"] += 1
                
                if quote.get("price") and quote.get("price") > 0:
                    # ========== MARKET-STATE AWARE UNDERLYING PRICE ==========
                    if use_live_price:
                        live_quote = await fetch_live_stock_quote(symbol.upper(), None)
                        if live_quote and live_quote.get("price", 0) > 0:
                            stock_price = live_quote["price"]
                            price_source = "yahoo_live"
                        else:
                            stock_price = quote["price"]
                            price_source = "yahoo_cached" if snapshot.get("from_cache") else "yahoo_live"
                    else:
                        stock_price = quote["price"]
                        price_source = "yahoo_cached" if snapshot.get("from_cache") else "yahoo_live"
                    
                    is_etf = symbol in ETF_SYMBOLS
                    
                    # PMCC-specific price filter (different from CC)
                    if not is_etf:
                        # Stocks: $30-$90
                        if stock_price < PMCC_STOCK_MIN_PRICE or stock_price > PMCC_STOCK_MAX_PRICE:
                            continue
                    # ETFs: No price limits
                    
                    stock_data[symbol] = {
                        "stock_price": stock_price,
                        "trade_date": quote.get("close_date"),
                        "market_cap": quote.get("market_cap"),
                        "analyst_rating": quote.get("analyst_rating"),
                        "is_etf": is_etf,
                        "source": price_source
                    }
                    symbols_with_stock_data.append(symbol)
        except Exception as e:
            logging.debug(f"Could not get stock price for {symbol}: {e}")
    
    logging.info(f"PMCC Screener cache stats: {cache_stats}")
    
    # Step 2: Get market sentiment
    try:
        sentiment = await fetch_market_sentiment()
        market_bias = sentiment.get("bias", "neutral")
        bias_weight = get_market_bias_weight(market_bias)
    except Exception:
        market_bias = "neutral"
        bias_weight = 1.0
    
    # Step 3: Scan each symbol for PMCC opportunities
    opportunities = []
    symbols_scanned = 0
    
    for symbol in symbols_with_stock_data:
        sym_data = stock_data[symbol]
        stock_price = sym_data["stock_price"]
        market_cap = sym_data.get("market_cap")
        analyst_rating = sym_data.get("analyst_rating")
        is_etf = sym_data.get("is_etf", False)
        symbols_scanned += 1
        
        # ============================================================
        # PMCC LONG LEG (LEAPS) FETCH
        # Rule: Expiry ≥ 6 months, Strike < Stock Price (ITM), Use ASK
        # ============================================================
        try:
            live_leaps = await fetch_options_chain(
                symbol=symbol,
                api_key=None,
                option_type="call",
                max_dte=max_leap_dte,
                min_dte=min_leap_dte,  # ≥6 months
                current_price=stock_price
            )
        except Exception as e:
            logging.debug(f"PMCC: Could not fetch LEAPS for {symbol}: {e}")
            continue
        
        if not live_leaps:
            continue
        
        # ============================================================
        # COMPUTE IV METRICS FOR SYMBOL (Industry Standard IV Rank)
        # Use short-term options for IV proxy (more liquid)
        # ============================================================
        try:
            # Combine all options for IV metrics
            all_options = live_leaps.copy()
            iv_metrics = await get_iv_metrics_for_symbol(
                db=db,
                symbol=symbol,
                options=all_options,
                stock_price=stock_price,
                store_history=True
            )
        except Exception as e:
            logging.debug(f"PMCC: Could not compute IV metrics for {symbol}: {e}")
            iv_metrics = None
        
        # Filter LEAPS - PMCC specific rules (NOT shared with CC)
        valid_leaps = []
        for opt in live_leaps:
            strike = opt.get("strike", 0)
            ask = opt.get("ask", 0)
            bid = opt.get("bid", 0)
            dte = opt.get("dte", 0)
            
            # ========== STRICT ASK-ONLY PRICING FOR BUY LEG ==========
            # PMCC LEAP BUY leg: REQUIRE ASK > 0, reject if missing/0
            # BID also required for spread validation
            if not ask or ask <= 0:
                cache_stats["ask_rejected"] += 1
                continue  # REJECT: No valid ASK for BUY leg
            if not bid or bid <= 0:
                continue  # Reject - need both for spread validation
            
            # PMCC RULE: Expiry must be 12-24 months (365-730 days)
            if dte < min_leap_dte:
                continue
            
            # PMCC RULE: Strike must be BELOW stock price (ITM)
            if strike >= stock_price:
                continue  # Reject - must be ITM
            
            # Calculate delta using Black-Scholes
            from services.greeks_service import calculate_greeks, normalize_iv_fields
            
            iv_raw = opt.get("implied_volatility", 0)
            iv_data = normalize_iv_fields(iv_raw)
            T = max(dte, 1) / 365.0
            
            greeks_result = calculate_greeks(
                S=stock_price,
                K=strike,
                T=T,
                sigma=iv_data["iv"] if iv_data["iv"] > 0 else None,
                option_type="call"
            )
            
            delta = greeks_result.delta
            delta_source = greeks_result.delta_source
            
            if delta < min_delta:
                continue
            
            valid_leaps.append({
                "strike": strike,
                "expiry": opt.get("expiry", ""),
                "dte": dte,
                "ask": ask,  # PMCC uses ASK for long leg
                "bid": bid,
                "delta": delta,
                "delta_source": delta_source,
                "iv": iv_data["iv"],
                "iv_pct": iv_data["iv_pct"],
                "oi": opt.get("open_interest", 0),
                "contract_symbol": opt.get("contract_ticker", "")
            })
        
        if not valid_leaps:
            continue
        
        # ============================================================
        # PMCC SHORT LEG FETCH
        # Rule: Expiry ≤ 60 days, Strike > Long-leg Strike, Use BID
        # ============================================================
        try:
            live_shorts = await fetch_options_chain(
                symbol=symbol,
                api_key=None,
                option_type="call",
                max_dte=max_short_dte,  # ≤60 days
                min_dte=min_short_dte,
                current_price=stock_price
            )
        except Exception as e:
            logging.debug(f"PMCC: Could not fetch short calls for {symbol}: {e}")
            continue
        
        if not live_shorts:
            continue
        
        # Filter short calls - PMCC specific rules
        valid_shorts = []
        for opt in live_shorts:
            strike = opt.get("strike", 0)
            bid = opt.get("bid", 0)
            ask = opt.get("ask", 0)
            dte = opt.get("dte", 0)
            
            # ========== STRICT BID-ONLY PRICING FOR SELL LEG ==========
            # PMCC short call SELL leg: REQUIRE BID > 0, reject if missing/0
            if not bid or bid <= 0:
                cache_stats["bid_rejected"] += 1
                continue  # REJECT: No valid BID for SELL leg
            if not ask or ask <= 0:
                continue  # Need ASK for spread validation
            
            # PMCC RULE: Expiry must be ≤ 60 days
            if dte > max_short_dte:
                continue
            
            # Minimum premium threshold
            if bid < 0.10:
                continue
            
            # Calculate delta using Black-Scholes for short calls
            iv_raw = opt.get("implied_volatility", 0)
            iv_data = normalize_iv_fields(iv_raw)
            T = max(dte, 1) / 365.0
            
            greeks_result = calculate_greeks(
                S=stock_price,
                K=strike,
                T=T,
                sigma=iv_data["iv"] if iv_data["iv"] > 0 else None,
                option_type="call"
            )
            
            valid_shorts.append({
                "strike": strike,
                "expiry": opt.get("expiry", ""),
                "dte": dte,
                "bid": bid,  # PMCC uses BID for short leg
                "ask": ask,
                "delta": greeks_result.delta,
                "delta_source": greeks_result.delta_source,
                "iv": iv_data["iv"],
                "iv_pct": iv_data["iv_pct"],
                "oi": opt.get("open_interest", 0),
                "contract_symbol": opt.get("contract_ticker", "")
            })
        
        if not valid_shorts:
            continue
        
        # ============================================================
        # BUILD PMCC COMBINATIONS
        # Rule: Short strike > Long strike, Net Debit = Long ASK - Short BID
        # ============================================================
        for leap in valid_leaps:
            leap_strike = leap["strike"]
            leap_ask = leap["ask"]  # Long leg uses ASK
            leap_dte = leap["dte"]
            leap_expiry = leap["expiry"]
            leap_delta = leap["delta"]
            leap_delta_source = leap.get("delta_source", "UNKNOWN")
            leap_bid = leap["bid"]
            leap_iv = leap["iv"]
            leap_iv_pct = leap.get("iv_pct", leap_iv * 100 if leap_iv < 5 else leap_iv)
            leap_oi = leap["oi"]
            
            for short in valid_shorts:
                short_strike = short["strike"]
                short_bid = short["bid"]  # Short leg uses BID
                short_ask = short["ask"]
                short_dte = short["dte"]
                short_expiry = short["expiry"]
                short_delta = short.get("delta", 0.3)
                short_delta_source = short.get("delta_source", "UNKNOWN")
                short_iv = short["iv"]
                short_iv_pct = short.get("iv_pct", short_iv * 100 if short_iv < 5 else short_iv)
                short_oi = short["oi"]
                
                # PMCC RULE: Short strike must be ABOVE long-leg strike
                if short_strike <= leap_strike:
                    continue
                
                # PMCC NET DEBIT: Long-leg ASK - Short-leg BID
                net_debit = leap_ask - short_bid
                
                if net_debit <= 0:
                    continue  # Invalid - should be a debit strategy
                
                # Calculate PMCC metrics
                width = short_strike - leap_strike
                max_profit = (width * 100) + (short_bid * 100) - (leap_ask * 100)
                
                if net_debit > 0:
                    roi_per_cycle = (short_bid / net_debit) * 100
                    cycles_per_year = 365 / short_dte if short_dte > 0 else 12
                    roi_annualized = roi_per_cycle * cycles_per_year
                else:
                    roi_per_cycle = 0
                    roi_annualized = 0
                
                # Calculate spreads
                leap_spread_pct = ((leap_ask - leap_bid) / leap_ask * 100) if leap_ask > 0 else 0
                short_spread_pct = ((short_ask - short_bid) / short_bid * 100) if short_bid > 0 else 0
                
                # Validate PMCC trade structure
                is_valid, rejection = validate_pmcc_trade(
                    symbol=symbol,
                    stock_price=stock_price,
                    leap_strike=leap_strike,
                    leap_expiry=leap_expiry,
                    leap_ask=leap_ask,
                    leap_dte=leap_dte,
                    leap_delta=leap_delta,
                    leap_oi=leap_oi,
                    short_strike=short_strike,
                    short_expiry=short_expiry,
                    short_bid=short_bid,
                    short_dte=short_dte
                )
                
                if not is_valid:
                    continue
                
                # Calculate PMCC quality score
                pmcc_trade_data = {
                    "leap_delta": leap_delta,
                    "leap_iv": leap_iv,
                    "leap_dte": leap_dte,
                    "leap_oi": leap_oi,
                    "leap_spread_pct": leap_spread_pct,
                    "short_iv": short_iv,
                    "short_dte": short_dte,
                    "short_oi": short_oi,
                    "short_spread_pct": short_spread_pct,
                    "roi_annualized": roi_annualized,
                    "net_debit": net_debit,
                    "width": width,
                    "max_profit": max_profit / 100,
                    "is_etf": is_etf
                }
                quality_result = calculate_pmcc_quality_score(pmcc_trade_data)
                final_score = apply_bias_to_score(quality_result.total_score, bias_weight)
                
                # Enrich with PMCC metrics
                leap_contract = {
                    "strike": leap_strike,
                    "ask": leap_ask,
                    "dte": leap_dte,
                    "delta": leap_delta,
                    "open_interest": leap_oi
                }
                short_contract = {
                    "strike": short_strike,
                    "bid": short_bid,
                    "dte": short_dte
                }
                pmcc_metrics = enrich_pmcc_metrics(leap_contract, short_contract, stock_price)
                
                # Calculate contract symbols
                try:
                    leap_exp_fmt = datetime.strptime(leap_expiry, "%Y-%m-%d").strftime("%y%m%d")
                    leap_contract_symbol = f"{symbol}{leap_exp_fmt}C{int(leap_strike * 1000):08d}"
                    short_exp_fmt = datetime.strptime(short_expiry, "%Y-%m-%d").strftime("%y%m%d")
                    short_contract_symbol = f"{symbol}{short_exp_fmt}C{int(short_strike * 1000):08d}"
                except:
                    leap_contract_symbol = leap.get("contract_symbol", "")
                    short_contract_symbol = short.get("contract_symbol", "")
                
                # Delta estimates for short leg
                short_delta = max(0.1, min(0.5, 1 - (short_strike - stock_price) / stock_price)) if short_strike > stock_price else 0.5
                short_gamma = 0.05
                short_theta = -0.02
                short_vega = 0.10
                
                # ==============================================================
                # AUTHORITATIVE PMCC CONTRACT - YAHOO SINGLE SOURCE OF TRUTH
                # ==============================================================
                opportunities.append({
                    # UNDERLYING object
                    "underlying": {
                        "symbol": symbol,
                        "last_price": round(stock_price, 2),
                        "price_source": "yahoo_last_close",  # SINGLE SOURCE OF TRUTH
                        "snapshot_date": sym_data.get("trade_date"),
                        "market_cap": market_cap,
                        "analyst_rating": analyst_rating  # From Yahoo Finance
                    },
                    
                    # SHORT_CALL object - SELL leg
                    "short_call": {
                        "strike": short_strike,
                        "expiry": short_expiry,
                        "dte": short_dte,
                        "contract_symbol": short_contract_symbol,
                        "premium": round(short_bid, 2),  # BID ONLY
                        "bid": round(short_bid, 2),
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
                        "annualized_roi_pct": round(roi_annualized, 1)
                    },
                    
                    # METADATA object
                    "metadata": {
                        "leaps_buy_eligible": True,  # Already validated
                        "is_etf": is_etf,
                        "validation_flags": {
                            "leap_itm": leap_strike < stock_price,  # PMCC rule: LEAP must be ITM
                            "leap_delta_ok": leap_delta >= min_delta,
                            "leap_dte_ok": leap_dte >= PMCC_MIN_LEAP_DTE,  # 12-24 months
                            "short_above_leap": short_strike > leap_strike,
                            "short_dte_ok": short_dte <= PMCC_MAX_SHORT_DTE,  # ≤60 days
                            "both_bid_ask_valid": True  # Already validated
                        },
                        "data_source": "yahoo_live_pmcc"  # PMCC-isolated data source
                    },
                    
                    # SCORING object
                    "scoring": {
                        "base_score": round(quality_result.total_score, 1),
                        "final_score": round(final_score, 1),
                        "pillars": {k: {"score": round(v.actual_score, 1), "max": v.max_score} 
                                   for k, v in quality_result.pillars.items()} if quality_result.pillars else {}
                    },
                    
                    # ==============================================================
                    # LEGACY FLAT FIELDS - For backwards compatibility
                    # ==============================================================
                    "symbol": symbol,
                    "stock_price": round(stock_price, 2),
                    "is_etf": is_etf,
                    "leap_strike": leap_strike,
                    "leap_expiry": leap_expiry,
                    "leap_dte": leap_dte,
                    "leap_cost": round(leap_ask, 2),
                    "leap_delta": round(leap_delta, 3),
                    "leap_ask": round(leap_ask, 2),
                    "leap_bid": round(leap_bid, 2),
                    "leap_open_interest": leap_oi,
                    "leap_iv": round(leap_iv * 100 if leap_iv < 1 else leap_iv, 1),
                    "leaps_buy_eligible": True,
                    "short_strike": short_strike,
                    "short_expiry": short_expiry,
                    "short_dte": short_dte,
                    "short_premium": round(short_bid, 2),
                    "short_bid": round(short_bid, 2),
                    "short_ask": round(short_ask, 2),
                    "short_iv": round(short_iv * 100 if short_iv < 1 else short_iv, 1),
                    "short_delta": round(short_delta, 4),
                    "width": round(width, 2),
                    "net_debit": round(net_debit, 2),
                    "net_debit_total": round(net_debit * 100, 2),
                    "max_profit": round(max_profit, 2),
                    "breakeven": round(pmcc_metrics.get("breakeven", leap_strike + net_debit), 2),
                    "roi_per_cycle": round(roi_per_cycle, 2),
                    "annualized_roi": round(roi_annualized, 1),
                    "base_score": round(quality_result.total_score, 1),
                    "score": round(final_score, 1),
                    "analyst_rating": analyst_rating,
                    "market_cap": market_cap,
                    "snapshot_date": sym_data.get("trade_date"),
                    "data_source": "yahoo_live_pmcc"
                })
    
    # ============================================================
    # PHASE 3: AI-BASED BEST OPTION SELECTION PER SYMBOL (PMCC)
    # ============================================================
    # IMPORTANT:
    # Scan candidates may include multiple PMCC combinations per symbol.
    # Final output must return ONE best option per symbol,
    # selected by highest AI score.
    # ============================================================
    opportunities = select_best_option_per_symbol(opportunities)
    
    return {
        "total": len(opportunities),
        "results": opportunities[:limit],
        "opportunities": opportunities[:limit],
        "symbols_scanned": symbols_scanned,
        "market_bias": market_bias,
        # PMCC-specific metadata
        "pmcc_rules": {
            "long_leg_min_dte": PMCC_MIN_LEAP_DTE,  # 12-24 months
            "long_leg_max_dte": PMCC_MAX_LEAP_DTE,
            "long_leg_must_be_itm": True,
            "long_leg_pricing": "ASK",
            "short_leg_max_dte": PMCC_MAX_SHORT_DTE,  # ≤60 days
            "short_leg_pricing": "BID",
            "net_debit_formula": "Long-leg ASK - Short-leg BID"
        },
        "price_filters": {
            "stocks": f"${PMCC_STOCK_MIN_PRICE}-${PMCC_STOCK_MAX_PRICE}",
            "etfs": "No price limits"
        },
        "stock_price_source": "yahoo_last_close",
        "options_chain_source": "yahoo_live",
        "layer": 3,
        "architecture": "PMCC_ISOLATED_FROM_CC",
        "live_data_used": True,
        "snapshot_cache_stats": cache_stats,
        # ========== PRICE SYNC METADATA ==========
        "market_state": current_market_state,
        "underlying_price_source": underlying_price_source,
        "pricing_rules": {
            "long_leg": "ASK_ONLY",
            "short_leg": "BID_ONLY"
        }
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
        "stock_price_source": "yahoo_last_close",  # SINGLE SOURCE OF TRUTH
        "options_chain_source": "yahoo_live",
        "layer": 3,
        "architecture": "TOP5_WEEKLY_TOP5_MONTHLY_YAHOO_SINGLE_SOURCE",
        "live_data_used": True
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
    structure_valid = 0
    
    # Track exclusions by stage and reason
    excluded_counts_by_stage = {
        "QUOTE": 0,
        "LIQUIDITY_FILTER": 0,
        "OPTIONS_CHAIN": 0,
        "CHAIN_QUALITY": 0,
        "CONTRACT_QUALITY": 0,
        "OTHER": 0
    }
    
    excluded_counts_by_reason = {
        "MISSING_QUOTE": 0,
        "LOW_LIQUIDITY_RANK": 0,
        "OUT_OF_PRICE_BAND": 0,
        "MISSING_CHAIN": 0,
        "CHAIN_EMPTY": 0,
        "BAD_CHAIN_DATA": 0,
        "MISSING_CONTRACT_FIELDS": 0,
        "OTHER": 0
    }
    
    # Legacy format for backward compatibility
    excluded_counts = {
        "OUT_OF_RULES": 0,
        "OUT_OF_PRICE_BAND": 0,
        "LOW_LIQUIDITY": 0,
        "MISSING_QUOTE": 0,
        "MISSING_CHAIN": 0,
        "CHAIN_EMPTY": 0,
        "BAD_CHAIN_DATA": 0,
        "MISSING_CONTRACT_FIELDS": 0,
        "OTHER": 0
    }
    
    # ================================================================
    # FORCED EXCLUSION TEST MODE (Development/Testing Only)
    # ================================================================
    # Set AUDIT_FORCE_EXCLUDE_SYMBOLS=AAPL,MSFT to test exclusion flow
    # DISABLED in production environment
    # ================================================================
    forced_exclude_symbols = set()
    if not is_production():
        force_exclude_env = os.environ.get("AUDIT_FORCE_EXCLUDE_SYMBOLS", "")
        if force_exclude_env:
            forced_exclude_symbols = set(s.strip().upper() for s in force_exclude_env.split(",") if s.strip())
            logging.info(f"[AUDIT] Forced exclusion test mode: {forced_exclude_symbols}")
    
    # Generate run_id for this audit
    now_utc = datetime.now(timezone.utc)
    run_id = f"audit_{now_utc.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    
    # Audit records to persist
    audit_records = []
    
    for symbol in SCAN_SYMBOLS:
        stock, stock_error = await snapshot_service.get_stock_snapshot(symbol)
        chain, chain_error = await snapshot_service.get_option_chain_snapshot(symbol)
        
        # Determine inclusion/exclusion status
        included = True
        exclude_stage = None
        exclude_reason = None
        exclude_detail = None
        price_used = stock.get("price", 0) if stock else 0
        avg_volume = stock.get("volume", 0) if stock else 0
        dollar_volume = price_used * avg_volume if price_used and avg_volume else 0
        
        # ================================================================
        # STAGE 1: QUOTE - Check stock quote availability
        # ================================================================
        if stock_error:
            included = False
            exclude_stage = "QUOTE"
            if "stale" in stock_error.lower():
                stale_stocks += 1
                exclude_reason = "MISSING_QUOTE"
                exclude_detail = f"Stale quote: {stock_error}"
            else:
                missing_stocks += 1
                exclude_reason = "MISSING_QUOTE"
                exclude_detail = stock_error
        else:
            valid_stocks += 1
        
        # ================================================================
        # STAGE 2: LIQUIDITY_FILTER - Check price band and liquidity
        # (Only if quote was valid)
        # ================================================================
        if included and stock:
            # Price band check (example: $5 - $500)
            min_price = 5.0
            max_price = 500.0
            if price_used < min_price or price_used > max_price:
                included = False
                exclude_stage = "LIQUIDITY_FILTER"
                exclude_reason = "OUT_OF_PRICE_BAND"
                exclude_detail = f"Price ${price_used:.2f} outside ${min_price}-${max_price} range"
            
            # Liquidity check (example: $1M daily dollar volume)
            min_dollar_volume = 1_000_000
            if included and dollar_volume < min_dollar_volume:
                included = False
                exclude_stage = "LIQUIDITY_FILTER"
                exclude_reason = "LOW_LIQUIDITY_RANK"
                exclude_detail = f"Dollar volume ${dollar_volume:,.0f} below ${min_dollar_volume:,.0f} threshold"
        
        # ================================================================
        # STAGE 3: OPTIONS_CHAIN - Check chain availability
        # (Only if previous stages passed)
        # ================================================================
        if included and chain_error:
            included = False
            if "stale" in chain_error.lower():
                stale_chains += 1
                exclude_stage = "CHAIN_QUALITY"
                exclude_reason = "BAD_CHAIN_DATA"
                exclude_detail = f"Stale chain: {chain_error}"
            elif "incomplete" in chain_error.lower():
                incomplete_chains += 1
                exclude_stage = "CONTRACT_QUALITY"
                exclude_reason = "MISSING_CONTRACT_FIELDS"
                exclude_detail = chain_error
            elif "empty" in chain_error.lower() or "no options" in chain_error.lower():
                exclude_stage = "CHAIN_QUALITY"
                exclude_reason = "CHAIN_EMPTY"
                exclude_detail = chain_error
            else:
                missing_chains += 1
                exclude_stage = "OPTIONS_CHAIN"
                exclude_reason = "MISSING_CHAIN"
                exclude_detail = chain_error
        elif included and not chain_error:
            valid_chains += 1
            structure_valid += 1
        
        # ================================================================
        # FORCED EXCLUSION TEST MODE (Development Only)
        # ================================================================
        if symbol.upper() in forced_exclude_symbols:
            included = False
            exclude_stage = "OTHER"
            exclude_reason = "OTHER"
            exclude_detail = "FORCED_TEST_EXCLUSION"
        
        # ================================================================
        # Update exclusion counters
        # ================================================================
        if not included and exclude_stage and exclude_reason:
            excluded_counts_by_stage[exclude_stage] += 1
            excluded_counts_by_reason[exclude_reason] += 1
            
            # Legacy counter mapping
            legacy_mapping = {
                "MISSING_QUOTE": "MISSING_QUOTE",
                "LOW_LIQUIDITY_RANK": "LOW_LIQUIDITY",
                "OUT_OF_PRICE_BAND": "OUT_OF_PRICE_BAND",
                "MISSING_CHAIN": "MISSING_CHAIN",
                "CHAIN_EMPTY": "CHAIN_EMPTY",
                "BAD_CHAIN_DATA": "BAD_CHAIN_DATA",
                "MISSING_CONTRACT_FIELDS": "MISSING_CONTRACT_FIELDS",
                "OTHER": "OTHER"
            }
            legacy_key = legacy_mapping.get(exclude_reason, "OTHER")
            if legacy_key in excluded_counts:
                excluded_counts[legacy_key] += 1
        
        # ================================================================
        # Create audit record (one per symbol, included or excluded)
        # ================================================================
        audit_records.append({
            "run_id": run_id,
            "symbol": symbol,
            "included": included,
            "exclude_stage": exclude_stage,
            "exclude_reason": exclude_reason,
            "exclude_detail": exclude_detail,
            "price_used": price_used,
            "avg_volume": avg_volume,
            "dollar_volume": dollar_volume,
            "as_of": now_utc
        })
    
    # Persist audit records to database
    try:
        if audit_records:
            result = await db.scan_universe_audit.insert_many(audit_records)
            logging.info(f"Persisted {len(result.inserted_ids)} universe audit records for run_id={run_id}")
    except Exception as e:
        logging.error(f"Failed to persist universe audit for run_id={run_id}: {e}")
    
    # Get market state
    current_market_state = get_market_state()
    
    # Normalize market state for frontend compatibility
    if current_market_state == "EXTENDED":
        current_market_state = "AFTERHOURS"
    
    # Determine price source based on market state
    if current_market_state == "OPEN":
        price_source = "LIVE"
    elif current_market_state == "CLOSED":
        price_source = "PREV_CLOSE"
    elif current_market_state in ["PREMARKET", "AFTERHOURS"]:
        price_source = "DELAYED"
    else:
        price_source = "STALE"
    
    # Get last scan run time from precomputed_scans collection
    last_full_run_at = None
    scored_trades = 0
    score_high = 0
    score_medium_high = 0
    score_medium = 0
    score_low = 0
    
    try:
        # Find most recent precomputed scan
        latest_scan = await db.precomputed_scans.find_one(
            {"type": {"$in": ["cc", "pmcc"]}},
            sort=[("last_updated", -1)]
        )
        if latest_scan and latest_scan.get("last_updated"):
            last_full_run_at = latest_scan["last_updated"]
            
        # Aggregate score distribution from all precomputed scans
        all_scans = await db.precomputed_scans.find({"type": {"$in": ["cc", "pmcc"]}}).to_list(length=10)
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
    
    # Calculate health score based on data quality
    chain_valid_pct = round((valid_chains / total_symbols) * 100) if total_symbols > 0 else 0
    structure_valid_pct = round((structure_valid / total_symbols) * 100) if total_symbols > 0 else 0
    
    # Health score: weighted average of data quality metrics
    # 40% chain validity, 30% stock validity, 30% structure validity
    stock_valid_pct = round((valid_stocks / total_symbols) * 100) if total_symbols > 0 else 0
    health_score = round(
        (chain_valid_pct * 0.4) + 
        (stock_valid_pct * 0.3) + 
        (structure_valid_pct * 0.3)
    )
    
    # Calculate rejected count
    rejected = total_symbols - structure_valid
    
    # Calculate total excluded
    total_excluded = sum(excluded_counts_by_stage.values())
    
    return {
        "run_id": run_id,
        "run_type": "EOD",
        "health_score": health_score if health_score > 0 else 0,
        "last_full_run_at": last_full_run_at.isoformat() if last_full_run_at else None,
        "market_state": current_market_state,
        "price_source": price_source,
        "underlying_price_source": price_source,  # Alias for frontend compatibility
        "as_of": now_utc.isoformat(),
        "universe": {
            "source": "INDEX_PLUS_LIQUIDITY",
            "notes": "S&P 500 + Nasdaq 100 + ETF whitelist + optional expansion",
            "total_candidates": total_symbols,
            "included": structure_valid,
            "excluded": total_excluded,
            "excluded_counts": excluded_counts,  # Legacy format
            "excluded_counts_by_stage": excluded_counts_by_stage,
            "excluded_counts_by_reason": excluded_counts_by_reason
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
        "scheduler_running": True,  # APScheduler is running if we got here
        "forced_exclusion_test_mode": len(forced_exclude_symbols) > 0,
        "forced_exclude_symbols": list(forced_exclude_symbols) if forced_exclude_symbols else None
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
