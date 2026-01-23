"""
Screener Routes - Covered Call and PMCC screening endpoints
============================================================

CCE MASTER ARCHITECTURE - LAYER 3: Strategy Selection Layer

TWO-PHASE ARCHITECTURE (NON-NEGOTIABLE):

PHASE 1 - INGESTION (services/snapshot_service.py):
    - Trading-day aware using NYSE calendar
    - Fetch stock + options data from Yahoo/Polygon
    - Store in MongoDB with full metadata
    - Run ONLY after market close

PHASE 2 - SCAN (this file):
    - READ-ONLY from stored Mongo snapshots
    - MUST ABORT if snapshot missing/stale/incomplete
    - ZERO live API calls during scan
    - NO "market open/closed" logic

LAYER 3 RESPONSIBILITIES:
    - Apply CC eligibility filters (price, volume, market cap)
    - Enforce earnings ±7 days exclusion
    - Separate Weekly (7-14 DTE) and Monthly (21-45 DTE) modes
    - Compute/enrich Greeks (Delta, IV, IV Rank, OI)
    - Prepare enriched data for downstream scoring
    
🚫 ABSOLUTE RULES:
    - NO live API calls during scan
    - NO cache used for trade eligibility
    - NO fallback to Yahoo / live data
    - NO market open/closed logic in scan
    
KILL SWITCH: fetch_stock_quote() and fetch_options_chain() are NOT imported.
Any accidental usage will cause a runtime error.
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

# ============================================================
# KILL SWITCH: DO NOT IMPORT LIVE DATA FUNCTIONS
# ============================================================
# from services.data_provider import fetch_options_chain, fetch_stock_quote
# ^^^ DELIBERATELY NOT IMPORTED - ANY USAGE WILL CAUSE RUNTIME ERROR

# Import SnapshotService for TWO-PHASE ARCHITECTURE
from services.snapshot_service import SnapshotService

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

# Initialize SnapshotService (singleton)
import os
_snapshot_service = None

def get_snapshot_service() -> SnapshotService:
    """Get or create the SnapshotService singleton."""
    global _snapshot_service
    if _snapshot_service is None:
        polygon_key = os.environ.get('POLYGON_API_KEY')
        _snapshot_service = SnapshotService(db, polygon_api_key=polygon_key)
    return _snapshot_service

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
    # ETFs (excluding GLD - incomplete chain)
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
    
    # ETFs are exempt from some checks
    if is_etf:
        # ETFs still need price check
        if scan_mode in ("system", "custom"):
            if stock_price < CC_SYSTEM_MIN_PRICE or stock_price > CC_SYSTEM_MAX_PRICE:
                return False, f"Price ${stock_price:.2f} outside $30-$90 range"
        return True, "ETF - eligible"
    
    # PRICE CHECK
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
# LAYER 3: GREEKS ENRICHMENT
# ============================================================

def enrich_option_greeks(
    contract: Dict,
    stock_price: float,
    risk_free_rate: float = 0.05
) -> Dict:
    """
    Enrich option contract with computed/estimated Greeks.
    
    CCE MASTER ARCHITECTURE - LAYER 3 COMPLIANT
    
    Computes/estimates:
    - Delta (from snapshot or estimated)
    - IV (from snapshot)
    - IV Rank (placeholder - requires historical data)
    - Theta (estimated)
    - Gamma (estimated)
    
    Args:
        contract: Option contract data from snapshot
        stock_price: Stock close price
        risk_free_rate: Risk-free rate for calculations
    
    Returns:
        Enriched contract with Greeks
    """
    enriched = contract.copy()
    
    strike = contract.get("strike", 0)
    dte = contract.get("dte", 30)
    iv = contract.get("implied_volatility", 0)
    option_type = contract.get("option_type", "call")
    
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
        enriched["iv_pct"] = round(iv, 1)
    
    # IV RANK - placeholder (would require 52-week IV history)
    # For now, use a simple estimate based on current IV
    if iv > 0:
        # Rough estimate: assume typical IV range is 20-60%
        iv_pct = iv * 100 if iv < 5 else iv
        enriched["iv_rank"] = min(100, max(0, (iv_pct - 20) / 40 * 100))
    else:
        enriched["iv_rank"] = None
    
    # THETA estimate (simplified)
    if dte > 0 and iv > 0:
        # Rough theta estimate: premium decay accelerates near expiry
        premium = contract.get("bid", 0) or contract.get("premium", 0)
        if premium > 0:
            daily_decay = premium / dte
            # Adjust for time decay acceleration
            if dte < 7:
                daily_decay *= 1.5
            elif dte < 14:
                daily_decay *= 1.2
            enriched["theta_estimate"] = -round(daily_decay, 3)
    
    # GAMMA estimate (simplified)
    if "delta" in enriched and dte > 0:
        # Gamma is highest ATM and near expiry
        atm_factor = 1 - abs((stock_price - strike) / stock_price)
        time_factor = max(0.1, 1 - dte / 60)
        enriched["gamma_estimate"] = round(atm_factor * time_factor * 0.05, 4)
    
    return enriched


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
    user: dict = Depends(get_current_user)
):
    """
    Screen for Covered Call opportunities.
    
    CCE MASTER ARCHITECTURE - LAYER 3: Strategy Selection
    
    ARCHITECTURE: Reads ONLY from stored Mongo snapshots.
    NO live data fetching. NO market open/closed logic.
    
    LAYER 3 FEATURES:
    - CC eligibility filters (price $30-$90, volume ≥1M, market cap ≥$5B)
    - Earnings ±7 days exclusion
    - Weekly (7-14 DTE) / Monthly (21-45 DTE) modes
    - Greeks enrichment (Delta, IV, IV Rank, OI)
    
    Args:
        dte_mode: "weekly" (7-14), "monthly" (21-45), or "all" (7-45)
        scan_mode: "system" (strict filters), "custom", or "manual" (relaxed price)
    
    FAIL CLOSED: Returns HTTP 409 if snapshot validation fails.
    """
    snapshot_service = get_snapshot_service()
    
    # LAYER 3: Determine DTE range based on mode
    if min_dte is None or max_dte is None:
        auto_min_dte, auto_max_dte = get_dte_range(dte_mode)
        min_dte = min_dte if min_dte is not None else auto_min_dte
        max_dte = max_dte if max_dte is not None else auto_max_dte
    
    # Step 1: Validate ALL snapshots (FAIL CLOSED)
    try:
        validation = await validate_all_snapshots(SCAN_SYMBOLS)
    except SnapshotValidationError:
        raise  # Re-raise to return 409
    
    # Step 2: Get market sentiment for scoring (not for eligibility)
    try:
        sentiment = await fetch_market_sentiment()
        market_bias = sentiment.get("bias", "neutral")
        bias_weight = get_market_bias_weight(market_bias)
    except Exception as e:
        logging.warning(f"Market sentiment unavailable, using neutral: {e}")
        market_bias = "neutral"
        bias_weight = 1.0
    
    # Step 3: Scan each symbol using SNAPSHOT DATA ONLY
    opportunities = []
    symbols_scanned = 0
    symbols_with_results = 0
    symbols_filtered = []  # Track filtered symbols for debugging
    
    for sym_data in validation["valid_symbols"]:
        symbol = sym_data["symbol"]
        stock_price = sym_data["stock_price"]
        symbols_scanned += 1
        
        # Get stock snapshot for eligibility check
        stock_snapshot, _ = await snapshot_service.get_stock_snapshot(symbol)
        
        # LAYER 3: Check CC eligibility (price, volume, market cap, earnings)
        is_eligible, eligibility_reason = check_cc_eligibility(
            symbol=symbol,
            stock_price=stock_price,
            market_cap=stock_snapshot.get("market_cap"),
            avg_volume=stock_snapshot.get("avg_volume"),
            earnings_date=stock_snapshot.get("earnings_date"),
            scan_mode=scan_mode,
            scan_date=sym_data.get("snapshot_date")
        )
        
        if not is_eligible:
            symbols_filtered.append({"symbol": symbol, "reason": eligibility_reason})
            continue
        
        # Get valid calls from snapshot (Phase 2: READ-ONLY)
        calls, error = await snapshot_service.get_valid_calls_for_scan(
            symbol=symbol,
            min_dte=min_dte,
            max_dte=max_dte,
            min_strike_pct=1.0 + (min_otm_pct / 100),
            max_strike_pct=1.0 + (max_otm_pct / 100),
            min_bid=0.05
        )
        
        if error or not calls:
            continue
        
        for call in calls:
            strike = call["strike"]
            premium = call["premium"]  # BID price (already validated)
            dte = call["dte"]
            expiry = call["expiry"]
            iv = call.get("implied_volatility", 0)
            oi = call.get("open_interest", 0)
            ask = call.get("ask", 0)
            
            # Calculate metrics
            premium_yield = (premium / stock_price) * 100
            otm_pct = ((strike - stock_price) / stock_price) * 100
            
            # Apply filters
            if premium_yield < min_premium_yield or premium_yield > max_premium_yield:
                continue
            if otm_pct < min_otm_pct or otm_pct > max_otm_pct:
                continue
            
            # Validate trade structure (includes Layer 2 spread check)
            is_valid, rejection = validate_cc_trade(
                symbol=symbol,
                stock_price=stock_price,
                strike=strike,
                expiry=expiry,
                bid=premium,
                dte=dte,
                open_interest=oi,
                ask=ask  # Pass ASK for spread validation
            )
            
            if not is_valid:
                continue
            
            # LAYER 3: Enrich with Greeks
            enriched_call = enrich_option_greeks(call, stock_price)
            
            # Calculate quality score (Phase 7)
            trade_data = {
                "iv": iv,
                "iv_rank": enriched_call.get("iv_rank", iv * 100 if iv < 1 else iv),
                "delta": enriched_call.get("delta", 0.3),
                "roi_pct": premium_yield,
                "premium": premium,
                "stock_price": stock_price,
                "dte": dte,
                "strike": strike,
                "open_interest": oi,
                "is_etf": symbol in ETF_SYMBOLS
            }
            quality_result = calculate_cc_quality_score(trade_data)
            
            # Apply market bias (Phase 6)
            final_score = apply_bias_to_score(quality_result.total_score, bias_weight)
            
            opportunities.append({
                "symbol": symbol,
                "strike": strike,
                "expiry": expiry,
                "dte": dte,
                "dte_category": "weekly" if dte <= WEEKLY_MAX_DTE else "monthly",
                "stock_price": round(stock_price, 2),
                "premium": round(premium, 2),
                "premium_yield": round(premium_yield, 2),
                "otm_pct": round(otm_pct, 2),
                # LAYER 3: Enriched Greeks
                "delta": round(enriched_call.get("delta", 0), 4),
                "implied_volatility": round(enriched_call.get("iv_pct", iv * 100 if iv < 1 else iv), 1),
                "iv_rank": round(enriched_call.get("iv_rank", 0), 1) if enriched_call.get("iv_rank") else None,
                "theta_estimate": enriched_call.get("theta_estimate"),
                "open_interest": oi,
                "volume": call.get("volume", 0),
                # Scores
                "base_score": round(quality_result.total_score, 1),
                "score": round(final_score, 1),
                "score_breakdown": {
                    "total": round(quality_result.total_score, 1),
                    "pillars": {k: {"score": round(v.actual_score, 1), "max": v.max_score} 
                               for k, v in quality_result.pillars.items()} if quality_result.pillars else {}
                },
                # Stock metadata
                "market_cap": stock_snapshot.get("market_cap"),
                "avg_volume": stock_snapshot.get("avg_volume"),
                "analyst_rating": stock_snapshot.get("analyst_rating"),
                "earnings_date": stock_snapshot.get("earnings_date"),
                "snapshot_date": sym_data["snapshot_date"],
                "data_age_hours": sym_data["data_age_hours"]
            })
        
        if calls:
            symbols_with_results += 1
    
    # Sort by score descending
    opportunities.sort(key=lambda x: x["score"], reverse=True)
    
    return {
        "total": len(opportunities),
        "results": opportunities[:limit],
        "opportunities": opportunities[:limit],  # Backward compatibility
        "symbols_scanned": symbols_scanned,
        "symbols_with_results": symbols_with_results,
        "symbols_filtered": len(symbols_filtered),
        "filter_reasons": symbols_filtered[:10],  # First 10 for debugging
        "market_bias": market_bias,
        "bias_weight": bias_weight,
        "snapshot_validation": {
            "total": validation["symbols_total"],
            "valid": validation["symbols_valid"]
        },
        # LAYER 3 metadata
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
        "architecture": "TWO_PHASE_SNAPSHOT_ONLY",
        "live_data_used": False
    }


# ============================================================
# PMCC SCREENER (Phase 2 - READ-ONLY FROM SNAPSHOTS)
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
    user: dict = Depends(get_current_user)
):
    """
    Screen for Poor Man's Covered Call (PMCC) opportunities.
    
    ARCHITECTURE: Phase 2 - Reads ONLY from stored Mongo snapshots.
    NO live data fetching. NO market open/closed logic.
    
    FAIL CLOSED: Returns HTTP 409 if snapshot validation fails.
    """
    snapshot_service = get_snapshot_service()
    
    # Step 1: Validate ALL snapshots (FAIL CLOSED)
    try:
        validation = await validate_all_snapshots(SCAN_SYMBOLS)
    except SnapshotValidationError:
        raise
    
    # Step 2: Get market sentiment for scoring
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
    
    for sym_data in validation["valid_symbols"]:
        symbol = sym_data["symbol"]
        stock_price = sym_data["stock_price"]
        symbols_scanned += 1
        
        # Get LEAPS from snapshot (BUY leg - uses ASK)
        leaps, leap_error = await snapshot_service.get_valid_leaps_for_pmcc(
            symbol=symbol,
            min_dte=min_leap_dte,
            max_dte=max_leap_dte,
            min_delta=min_delta
        )
        
        if leap_error or not leaps:
            continue
        
        # Get short calls from snapshot (SELL leg - uses BID)
        shorts, short_error = await snapshot_service.get_valid_calls_for_scan(
            symbol=symbol,
            min_dte=min_short_dte,
            max_dte=max_short_dte,
            min_strike_pct=1.02,  # 2% OTM minimum
            max_strike_pct=1.15,  # 15% OTM maximum
            min_bid=0.10
        )
        
        if short_error or not shorts:
            continue
        
        # Get stock snapshot for metadata
        stock_snapshot, _ = await snapshot_service.get_stock_snapshot(symbol)
        
        # Build PMCC combinations
        for leap in leaps:
            leap_cost = leap["premium"]  # ASK price
            leap_strike = leap["strike"]
            leap_delta = leap["delta"]
            leap_dte = leap["dte"]
            leap_expiry = leap["expiry"]
            
            for short in shorts:
                short_strike = short["strike"]
                short_premium = short["premium"]  # BID price
                short_dte = short["dte"]
                short_expiry = short["expiry"]
                
                # PMCC structure validation
                if short_strike <= leap_strike:
                    continue  # Short must be above LEAP strike
                
                # Calculate metrics
                max_profit = (short_strike - leap_strike) * 100 + (short_premium * 100)
                net_debit = leap_cost - short_premium
                
                if net_debit <= 0:
                    continue  # Invalid structure
                
                roi_per_cycle = (short_premium / leap_cost) * 100
                cycles_per_year = 365 / short_dte
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
                
                opportunities.append({
                    "symbol": symbol,
                    "stock_price": round(stock_price, 2),
                    # LEAP (BUY leg)
                    "leap_strike": leap_strike,
                    "leap_expiry": leap_expiry,
                    "leap_dte": leap_dte,
                    "leap_cost": round(leap_cost, 2),
                    "leap_delta": round(leap_delta, 3),
                    # Short (SELL leg)
                    "short_strike": short_strike,
                    "short_expiry": short_expiry,
                    "short_dte": short_dte,
                    "short_premium": round(short_premium, 2),
                    # Metrics
                    "net_debit": round(net_debit, 2),
                    "max_profit": round(max_profit, 2),
                    "roi_per_cycle": round(roi_per_cycle, 2),
                    "annualized_roi": round(annualized_roi, 1),
                    "base_score": round(quality_result.total_score, 1),
                    "score": round(final_score, 1),
                    "score_breakdown": {
                        "total": round(quality_result.total_score, 1),
                        "pillars": {k: {"score": round(v.actual_score, 1), "max": v.max_score} 
                                   for k, v in quality_result.pillars.items()} if quality_result.pillars else {}
                    },
                    "snapshot_date": sym_data["snapshot_date"],
                    "data_age_hours": sym_data["data_age_hours"]
                })
    
    # Sort by annualized ROI
    opportunities.sort(key=lambda x: x["annualized_roi"], reverse=True)
    
    return {
        "total": len(opportunities),
        "results": opportunities[:limit],
        "opportunities": opportunities[:limit],
        "symbols_scanned": symbols_scanned,
        "market_bias": market_bias,
        "snapshot_validation": {
            "total": validation["symbols_total"],
            "valid": validation["symbols_valid"]
        },
        "phase": 7,
        "architecture": "TWO_PHASE_SNAPSHOT_ONLY",
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
    
    ARCHITECTURE: Phase 2 - Reads ONLY from stored Mongo snapshots.
    
    FAIL CLOSED: Returns HTTP 409 if snapshot validation fails.
    """
    # Use the covered calls endpoint with default parameters
    return await screen_covered_calls(
        limit=10,
        risk_profile="moderate",
        min_dte=7,
        max_dte=45,
        min_premium_yield=0.5,
        max_premium_yield=20.0,
        min_otm_pct=0.0,
        max_otm_pct=15.0,
        user=user
    )


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
