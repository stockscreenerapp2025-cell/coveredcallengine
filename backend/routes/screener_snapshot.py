"""
Screener Routes - Covered Call and PMCC screening endpoints
============================================================
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

# PHASE 2: Import chain validator
from services.chain_validator import (
    get_validator,
    validate_chain_for_cc,
    validate_cc_trade,
    validate_pmcc_trade
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
    calculate_pmcc_quality_score,
    score_to_dict
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

# Symbol universe (fixed at ~60, validated for snapshot completeness)
# NOTE: GS, BLK, AMGN, MMM, GLD removed due to option chain validation issues
SCAN_SYMBOLS = [
    # Tech Giants
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD", "INTC", "CRM",
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
        
        valid_symbols.append({
            "symbol": symbol,
            "stock_price": stock.get("price"),
            "snapshot_date": stock.get("snapshot_trade_date"),
            "data_age_hours": stock.get("data_age_hours"),
            "valid_contracts": chain.get("valid_contracts", 0)
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
# COVERED CALL SCREENER (Phase 2 - READ-ONLY FROM SNAPSHOTS)
# ============================================================

@screener_router.get("/covered-calls")
async def screen_covered_calls(
    limit: int = Query(50, ge=1, le=200),
    risk_profile: str = Query("moderate", regex="^(conservative|moderate|aggressive)$"),
    min_dte: int = Query(7, ge=1),
    max_dte: int = Query(45, le=180),
    min_premium_yield: float = Query(0.5, ge=0),
    max_premium_yield: float = Query(20.0, le=50),
    min_otm_pct: float = Query(0.0, ge=0),
    max_otm_pct: float = Query(20.0, le=50),
    user: dict = Depends(get_current_user)
):
    """
    Screen for Covered Call opportunities.
    
    ARCHITECTURE: Phase 2 - Reads ONLY from stored Mongo snapshots.
    NO live data fetching. NO market open/closed logic.
    
    FAIL CLOSED: Returns HTTP 409 if snapshot validation fails.
    """
    snapshot_service = get_snapshot_service()
    
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
    
    for sym_data in validation["valid_symbols"]:
        symbol = sym_data["symbol"]
        stock_price = sym_data["stock_price"]
        symbols_scanned += 1
        
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
        
        # Get stock snapshot for additional data
        stock_snapshot, _ = await snapshot_service.get_stock_snapshot(symbol)
        
        for call in calls:
            strike = call["strike"]
            premium = call["premium"]  # BID price (already validated)
            dte = call["dte"]
            expiry = call["expiry"]
            iv = call.get("implied_volatility", 0)
            oi = call.get("open_interest", 0)
            
            # Calculate metrics
            premium_yield = (premium / stock_price) * 100
            otm_pct = ((strike - stock_price) / stock_price) * 100
            
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
                open_interest=oi
            )
            
            if not is_valid:
                continue
            
            # Calculate quality score (Phase 7)
            quality_result = calculate_cc_quality_score(
                iv_rank=iv * 100 if iv < 1 else iv,  # Convert to percentage if needed
                delta=0.3,  # Estimate
                premium_yield=premium_yield,
                dte=dte,
                otm_pct=otm_pct,
                open_interest=oi,
                near_earnings=False,
                is_etf=symbol in ETF_SYMBOLS
            )
            
            # Apply market bias (Phase 6)
            final_score = apply_bias_to_score(quality_result.final_score, bias_weight)
            
            opportunities.append({
                "symbol": symbol,
                "strike": strike,
                "expiry": expiry,
                "dte": dte,
                "stock_price": round(stock_price, 2),
                "premium": round(premium, 2),
                "premium_yield": round(premium_yield, 2),
                "otm_pct": round(otm_pct, 2),
                "implied_volatility": round(iv * 100, 1) if iv < 1 else round(iv, 1),
                "open_interest": oi,
                "volume": call.get("volume", 0),
                "base_score": round(quality_result.final_score, 1),
                "score": round(final_score, 1),
                "score_breakdown": score_to_dict(quality_result),
                "market_cap": stock_snapshot.get("market_cap"),
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
        "market_bias": market_bias,
        "bias_weight": bias_weight,
        "snapshot_validation": {
            "total": validation["symbols_total"],
            "valid": validation["symbols_valid"]
        },
        "phase": 7,
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
                    leap_ask=leap_cost,
                    leap_dte=leap_dte,
                    leap_delta=leap_delta,
                    leap_oi=leap.get("open_interest", 0),
                    short_strike=short_strike,
                    short_bid=short_premium,
                    short_dte=short_dte
                )
                
                if not is_valid:
                    continue
                
                # Calculate quality score
                quality_result = calculate_pmcc_quality_score(
                    leap_delta=leap_delta,
                    leap_dte=leap_dte,
                    leap_spread_pct=((leap["ask"] - leap["bid"]) / leap["ask"] * 100) if leap["ask"] > 0 else 0,
                    short_premium_pct=roi_per_cycle,
                    short_dte=short_dte,
                    short_otm_pct=((short_strike - stock_price) / stock_price) * 100,
                    is_etf=symbol in ETF_SYMBOLS
                )
                
                final_score = apply_bias_to_score(quality_result.final_score, bias_weight)
                
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
                    "base_score": round(quality_result.final_score, 1),
                    "score": round(final_score, 1),
                    "score_breakdown": score_to_dict(quality_result),
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
