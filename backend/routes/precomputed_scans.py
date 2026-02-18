"""
Pre-Computed Scans Routes
=========================
API endpoints for accessing pre-computed scan results.

ARCHITECTURE (Feb 2026): UNIFIED EOD SNAPSHOT READ MODEL
=========================================================
All /api/scans/* endpoints now read from the same EOD pipeline collections
as /api/screener/* endpoints, ensuring consistent pricing:
- scan_results_cc for Covered Calls
- scan_results_pmcc for PMCC
- stock_price_source: SESSION_CLOSE (frozen at market close)
- No Yahoo live calls during request/response

Endpoints:
- GET /api/scans/available - List all available scans with metadata
- GET /api/scans/covered-call/{risk_profile} - Get CC scan results from EOD
- GET /api/scans/pmcc/{risk_profile} - Get PMCC scan results from EOD
- POST /api/scans/trigger/{strategy}/{risk_profile} - Manually trigger scan (admin)
- POST /api/scans/trigger-all - Trigger all scans (admin)
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from typing import Optional, Dict, List
import logging
import sys
import uuid
import json
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))

from database import db
from utils.auth import get_current_user, get_admin_user

# Import pricing utilities for stabilization (MASTER PATCH)
from utils.pricing_utils import (
    sanitize_float,
    sanitize_money,
    sanitize_percentage,
    sanitize_dict_with_money,
    MONETARY_FIELDS
)

logger = logging.getLogger(__name__)

scans_router = APIRouter(prefix="/scans", tags=["Pre-Computed Scans"])

# ==================== STABILITY HELPERS ====================
# Using centralized pricing_utils for consistency across all endpoints

def sanitize_response(data: Dict) -> Dict:
    """
    Sanitize entire response dict to ensure JSON serializability.
    Uses monetary-aware sanitization.
    """
    return sanitize_dict_with_money(data)

# ==================== EOD READ HELPERS ====================

async def _get_latest_eod_run_id() -> Optional[str]:
    """Get the latest EOD pipeline run_id."""
    # Try scan_runs first
    latest_run = await db.scan_runs.find_one(
        {"status": "completed"},
        {"run_id": 1, "_id": 0},
        sort=[("completed_at", -1)]
    )
    if latest_run and latest_run.get("run_id"):
        return latest_run.get("run_id")
    
    # Fallback: get run_id from most recent scan_results_cc entry
    latest_cc = await db.scan_results_cc.find_one(
        {},
        {"run_id": 1, "_id": 0},
        sort=[("created_at", -1)]
    )
    if latest_cc and latest_cc.get("run_id"):
        return latest_cc.get("run_id")
    
    return None

async def _get_eod_cc_opportunities(
    run_id: str,
    risk_profile: str,
    limit: int,
    min_score: float,
    sector: Optional[str]
) -> tuple:
    """
    Get Covered Call opportunities from EOD scan_results_cc.
    Returns (opportunities, run_info).
    """
    # Build query based on risk profile scoring thresholds
    query = {"run_id": run_id}
    
    # Risk profile determines score thresholds
    if risk_profile == "conservative":
        query["score"] = {"$gte": 70}
        query["delta"] = {"$lte": 0.35}  # Lower delta = more conservative
    elif risk_profile == "balanced":
        query["score"] = {"$gte": 50}
        query["delta"] = {"$gte": 0.25, "$lte": 0.45}
    elif risk_profile == "aggressive":
        query["score"] = {"$gte": 40}
        query["delta"] = {"$gte": 0.35}
    
    if min_score > 0:
        query["score"] = {"$gte": min_score}
    
    # Note: sector filtering would need sector data in the collection
    
    results = await db.scan_results_cc.find(
        query,
        {"_id": 0}
    ).sort("score", -1).limit(limit).to_list(limit)
    
    # Get run metadata
    run_doc = await db.scan_runs.find_one({"run_id": run_id}, {"_id": 0})
    run_info = {
        "run_id": run_id,
        "as_of": run_doc.get("as_of") if run_doc else None,
        "completed_at": run_doc.get("completed_at") if run_doc else None
    }
    
    return results, run_info

async def _get_eod_pmcc_opportunities(
    run_id: str,
    risk_profile: str,
    limit: int,
    min_score: float,
    sector: Optional[str]
) -> tuple:
    """
    Get PMCC opportunities from EOD scan_results_pmcc.
    Returns (opportunities, run_info).
    """
    query = {"run_id": run_id}
    
    # Risk profile determines thresholds
    if risk_profile == "conservative":
        query["score"] = {"$gte": 60}
    elif risk_profile == "balanced":
        query["score"] = {"$gte": 45}
    elif risk_profile == "aggressive":
        query["score"] = {"$gte": 30}
    
    if min_score > 0:
        query["score"] = {"$gte": min_score}
    
    results = await db.scan_results_pmcc.find(
        query,
        {"_id": 0}
    ).sort("score", -1).limit(limit).to_list(limit)
    
    # Get run metadata
    run_doc = await db.scan_runs.find_one({"run_id": run_id}, {"_id": 0})
    run_info = {
        "run_id": run_id,
        "as_of": run_doc.get("as_of") if run_doc else None,
        "completed_at": run_doc.get("completed_at") if run_doc else None
    }
    
    return results, run_info

def _transform_cc_for_scans(row: Dict) -> Dict:
    """Transform EOD CC row to scans API response format with 2-decimal monetary precision."""
    result = {
        "symbol": row.get("symbol"),
        # MONETARY: 2-decimal precision
        "stock_price": sanitize_money(row.get("stock_price")),
        "stock_price_source": row.get("stock_price_source", "SESSION_CLOSE"),
        "session_close_price": sanitize_money(row.get("session_close_price")),
        "prior_close_price": sanitize_money(row.get("prior_close_price")),
        "market_status": row.get("market_status"),
        "strike": sanitize_money(row.get("strike")),
        "expiry": row.get("expiry"),
        "dte": row.get("dte"),
        # PRICING POLICY: SELL at BID (2-decimal)
        "premium": sanitize_money(row.get("premium_bid")),  # SELL rule: use BID
        "premium_bid": sanitize_money(row.get("premium_bid")),
        "premium_ask": sanitize_money(row.get("premium_ask")),
        # Percentages
        "premium_yield": sanitize_percentage(row.get("premium_yield")),
        "roi_pct": sanitize_percentage(row.get("roi_pct")),
        "roi_annualized": sanitize_percentage(row.get("roi_annualized"), 1),
        # Greeks (non-monetary)
        "delta": sanitize_float(row.get("delta")),
        "iv": sanitize_float(row.get("iv")),
        "iv_pct": sanitize_float(row.get("iv_pct")),
        "iv_rank": sanitize_float(row.get("iv_rank")),
        "open_interest": row.get("open_interest"),
        "volume": row.get("volume"),
        "score": sanitize_float(row.get("score")),
        "is_etf": row.get("is_etf", False),
        "instrument_type": row.get("instrument_type", "STOCK"),
        "quality_flags": row.get("quality_flags", []),
        "analyst_rating": row.get("analyst_rating"),
        "contract_symbol": row.get("contract_symbol"),
        "as_of": row.get("as_of"),
        "run_id": row.get("run_id")
    }
    return result

def _transform_pmcc_for_scans(row: Dict) -> Dict:
    """Transform EOD PMCC row to scans API response format with 2-decimal monetary precision."""
    result = {
        "symbol": row.get("symbol"),
        # MONETARY: 2-decimal precision
        "stock_price": sanitize_money(row.get("stock_price")),
        "stock_price_source": row.get("stock_price_source", "SESSION_CLOSE"),
        "session_close_price": sanitize_money(row.get("session_close_price")),
        "prior_close_price": sanitize_money(row.get("prior_close_price")),
        "market_status": row.get("market_status"),
        # LEAP leg (BUY at ASK) - MONETARY: 2-decimal
        "leap_strike": sanitize_money(row.get("leap_strike")),
        "leap_expiry": row.get("leap_expiry"),
        "leap_dte": row.get("leap_dte"),
        "leap_ask": sanitize_money(row.get("leap_ask")),
        "leap_bid": sanitize_money(row.get("leap_bid")),
        "leap_delta": sanitize_float(row.get("leap_delta")),
        # Short leg (SELL at BID) - MONETARY: 2-decimal
        "short_strike": sanitize_money(row.get("short_strike")),
        "short_expiry": row.get("short_expiry"),
        "short_dte": row.get("short_dte"),
        "short_bid": sanitize_money(row.get("short_bid")),
        "short_ask": sanitize_money(row.get("short_ask")),
        "short_delta": sanitize_float(row.get("short_delta")),
        # Economics - MONETARY: 2-decimal
        "net_debit": sanitize_money(row.get("net_debit")),
        "width": sanitize_money(row.get("width")),
        "max_profit": sanitize_money(row.get("max_profit")),
        "breakeven": sanitize_money(row.get("breakeven")),
        "roi_annualized": sanitize_percentage(row.get("roi_annualized"), 1),
        # Greeks & IV (non-monetary)
        "iv": sanitize_float(row.get("iv")),
        "iv_pct": sanitize_float(row.get("iv_pct")),
        "iv_rank": sanitize_float(row.get("iv_rank")),
        # Metadata
        "score": sanitize_float(row.get("score")),
        "is_etf": row.get("is_etf", False),
        "instrument_type": row.get("instrument_type", "STOCK"),
        "quality_flags": row.get("quality_flags", []),
        "analyst_rating": row.get("analyst_rating"),
        "as_of": row.get("as_of"),
        "run_id": row.get("run_id")
    }
    return result


async def get_scan_service():
    """Get scan service instance."""
    from services.precomputed_scans import PrecomputedScanService
    # No API key needed for Yahoo Finance
    return PrecomputedScanService(db)


# ==================== PUBLIC ENDPOINTS ====================

@scans_router.get("/available")
async def get_available_scans(user: dict = Depends(get_current_user)):
    """
    Get list of all available pre-computed scans with metadata.
    Returns scan types, last computed time, and result counts.
    
    CRITICAL FIX (Feb 2026): Counts now computed from EOD pipeline collections
    (scan_results_cc, scan_results_pmcc) using the same filtering logic as
    the detail endpoints, ensuring summary counts match returned results.
    """
    # Get latest EOD run
    run_id = await _get_latest_eod_run_id()
    
    # Get run metadata for computed_at timestamp
    run_info = None
    if run_id:
        run_doc = await db.scan_runs.find_one({"run_id": run_id}, {"_id": 0})
        if run_doc:
            run_info = {
                "run_id": run_id,
                "as_of": run_doc.get("as_of"),
                "completed_at": run_doc.get("completed_at")
            }
    
    # Compute CC counts using SAME filtering logic as detail endpoint
    cc_counts = {}
    if run_id:
        # Conservative: score >= 70, delta <= 0.35
        cc_counts["conservative"] = await db.scan_results_cc.count_documents({
            "run_id": run_id,
            "score": {"$gte": 70},
            "delta": {"$lte": 0.35}
        })
        # Balanced: score >= 50, delta 0.25-0.45
        cc_counts["balanced"] = await db.scan_results_cc.count_documents({
            "run_id": run_id,
            "score": {"$gte": 50},
            "delta": {"$gte": 0.25, "$lte": 0.45}
        })
        # Aggressive: score >= 40, delta >= 0.35
        cc_counts["aggressive"] = await db.scan_results_cc.count_documents({
            "run_id": run_id,
            "score": {"$gte": 40},
            "delta": {"$gte": 0.35}
        })
    
    # Compute PMCC counts using SAME filtering logic as detail endpoint
    pmcc_counts = {}
    if run_id:
        # Conservative: score >= 60
        pmcc_counts["conservative"] = await db.scan_results_pmcc.count_documents({
            "run_id": run_id,
            "score": {"$gte": 60}
        })
        # Balanced: score >= 45
        pmcc_counts["balanced"] = await db.scan_results_pmcc.count_documents({
            "run_id": run_id,
            "score": {"$gte": 45}
        })
        # Aggressive: score >= 30
        pmcc_counts["aggressive"] = await db.scan_results_pmcc.count_documents({
            "run_id": run_id,
            "score": {"$gte": 30}
        })
    
    computed_at = run_info.get("completed_at") if run_info else None
    
    # Build response with accurate counts from EOD collections
    all_scans = {
        "covered_call": [
            {
                "risk_profile": "conservative",
                "label": "Income Guard",
                "description": "Stable stocks with low volatility and high probability of profit",
                "button_text": "Income Guard – Covered Call (Low Risk)",
                "available": run_id is not None,
                "count": cc_counts.get("conservative", 0),
                "computed_at": computed_at
            },
            {
                "risk_profile": "balanced",
                "label": "Steady Income",
                "description": "Slightly bullish stocks with moderate volatility",
                "button_text": "Steady Income – Covered Call (Balanced)",
                "available": run_id is not None,
                "count": cc_counts.get("balanced", 0),
                "computed_at": computed_at
            },
            {
                "risk_profile": "aggressive",
                "label": "Premium Hunter",
                "description": "Strong momentum with premium maximization",
                "button_text": "Premium Hunter – Covered Call (Aggressive)",
                "available": run_id is not None,
                "count": cc_counts.get("aggressive", 0),
                "computed_at": computed_at
            }
        ],
        "pmcc": [
            {
                "risk_profile": "conservative",
                "label": "Capital Efficient Income",
                "description": "PMCC with stable underlying and high delta LEAPS",
                "button_text": "Capital Efficient Income – PMCC (Low Risk)",
                "available": run_id is not None,
                "count": pmcc_counts.get("conservative", 0),
                "computed_at": computed_at
            },
            {
                "risk_profile": "balanced",
                "label": "Leveraged Income",
                "description": "Moderate risk PMCC with balanced LEAPS selection",
                "button_text": "Leveraged Income – PMCC (Balanced)",
                "available": run_id is not None,
                "count": pmcc_counts.get("balanced", 0),
                "computed_at": computed_at
            },
            {
                "risk_profile": "aggressive",
                "label": "Max Yield Diagonal",
                "description": "Aggressive PMCC targeting maximum premium yield",
                "button_text": "Max Yield Diagonal – PMCC (Aggressive)",
                "available": run_id is not None,
                "count": pmcc_counts.get("aggressive", 0),
                "computed_at": computed_at
            }
        ]
    }
    
    return {
        "scans": all_scans,
        "total_scans": 6,  # Always 6 scan types defined
        "run_id": run_id,
        "message": "Use GET /api/scans/{strategy}/{risk_profile} to fetch results"
    }


@scans_router.get("/covered-call/{risk_profile}")
async def get_covered_call_scan(
    risk_profile: str,
    limit: int = Query(50, ge=1, le=100),
    min_score: float = Query(0, ge=0),
    sector: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    """
    Get covered call scan results from EOD SNAPSHOT READ MODEL.
    
    ARCHITECTURE (Feb 2026): UNIFIED EOD READ MODEL
    ===============================================
    - Reads from scan_results_cc collection (same as /api/screener/covered-calls)
    - stock_price_source: SESSION_CLOSE (frozen at market close)
    - NO LIVE YAHOO CALLS during request/response
    - Guarantees identical prices with /api/screener/* endpoints
    
    Risk profiles:
    - conservative: Income Guard (Low Risk) - delta <= 0.35, score >= 70
    - balanced: Steady Income (Moderate) - delta 0.25-0.45, score >= 50
    - aggressive: Premium Hunter (High Premium) - delta >= 0.35, score >= 40
    """
    import time
    trace_id = str(uuid.uuid4())[:8]
    start_time = time.time()
    
    if risk_profile not in ["conservative", "balanced", "aggressive"]:
        raise HTTPException(
            status_code=400, 
            detail="Invalid risk_profile. Use: conservative, balanced, aggressive"
        )
    
    # Get latest EOD run
    run_id = await _get_latest_eod_run_id()
    
    if not run_id:
        raise HTTPException(
            status_code=404,
            detail="No EOD scan results available. Scans run daily at 4:10 PM ET."
        )
    
    # Get opportunities from EOD collection
    results, run_info = await _get_eod_cc_opportunities(
        run_id, risk_profile, limit, min_score, sector
    )
    
    # Transform to API response format
    opportunities = [_transform_cc_for_scans(r) for r in results]
    
    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(f"CC Scans: {len(opportunities)} results for {risk_profile} in {elapsed_ms:.1f}ms trace_id={trace_id}")
    
    # Risk profile labels
    labels = {
        "conservative": {"label": "Income Guard", "description": "Stable stocks with low volatility and high probability of profit"},
        "balanced": {"label": "Steady Income", "description": "Slightly bullish stocks with moderate volatility"},
        "aggressive": {"label": "Premium Hunter", "description": "Strong momentum with premium maximization"}
    }
    
    return sanitize_response({
        "strategy": "covered_call",
        "risk_profile": risk_profile,
        "label": labels[risk_profile]["label"],
        "description": labels[risk_profile]["description"],
        "opportunities": opportunities,
        "total": len(opportunities),
        "computed_at": run_info.get("completed_at"),
        "as_of": run_info.get("as_of"),
        "run_id": run_info.get("run_id"),
        "is_precomputed": True,
        "architecture": "EOD_PIPELINE_READ_MODEL",
        "stock_price_source": "SESSION_CLOSE",
        "live_data_used": False,
        "latency_ms": round(elapsed_ms, 1),
        "trace_id": trace_id
    })


@scans_router.get("/pmcc/{risk_profile}")
async def get_pmcc_scan(
    risk_profile: str,
    limit: int = Query(50, ge=1, le=100),
    min_score: float = Query(0, ge=0),
    sector: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    """
    Get PMCC scan results from EOD SNAPSHOT READ MODEL.
    
    ARCHITECTURE (Feb 2026): UNIFIED EOD READ MODEL
    ===============================================
    - Reads from scan_results_pmcc collection (same as /api/screener/pmcc)
    - stock_price_source: SESSION_CLOSE (frozen at market close)
    - NO LIVE YAHOO CALLS during request/response
    - Guarantees identical prices with /api/screener/* endpoints
    
    Risk profiles:
    - conservative: Capital Efficient Income (Low Risk) - score >= 60
    - balanced: Leveraged Income (Moderate) - score >= 45
    - aggressive: Max Yield Diagonal (High Premium) - score >= 30
    """
    import time
    trace_id = str(uuid.uuid4())[:8]
    start_time = time.time()
    
    if risk_profile not in ["conservative", "balanced", "aggressive"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid risk_profile. Use: conservative, balanced, aggressive"
        )
    
    # Get latest EOD run
    run_id = await _get_latest_eod_run_id()
    
    if not run_id:
        raise HTTPException(
            status_code=404,
            detail="No EOD scan results available. Scans run daily at 4:10 PM ET."
        )
    
    # Get opportunities from EOD collection
    results, run_info = await _get_eod_pmcc_opportunities(
        run_id, risk_profile, limit, min_score, sector
    )
    
    # Transform to API response format
    opportunities = [_transform_pmcc_for_scans(r) for r in results]
    
    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(f"PMCC Scans: {len(opportunities)} results for {risk_profile} in {elapsed_ms:.1f}ms trace_id={trace_id}")
    
    # Risk profile labels
    labels = {
        "conservative": {"label": "Capital Efficient Income", "description": "Low risk PMCC with strong safety margins"},
        "balanced": {"label": "Leveraged Income", "description": "Moderate risk PMCC with balanced yield"},
        "aggressive": {"label": "Max Yield Diagonal", "description": "Aggressive PMCC targeting maximum premium yield"}
    }
    
    return sanitize_response({
        "strategy": "pmcc",
        "risk_profile": risk_profile,
        "label": labels[risk_profile]["label"],
        "description": labels[risk_profile]["description"],
        "opportunities": opportunities,
        "total": len(opportunities),
        "computed_at": run_info.get("completed_at"),
        "as_of": run_info.get("as_of"),
        "run_id": run_info.get("run_id"),
        "is_precomputed": True,
        "architecture": "EOD_PIPELINE_READ_MODEL",
        "stock_price_source": "SESSION_CLOSE",
        "live_data_used": False,
        "latency_ms": round(elapsed_ms, 1),
        "trace_id": trace_id
    })


# ==================== ADMIN ENDPOINTS ====================

@scans_router.post("/trigger/{strategy}/{risk_profile}")
async def trigger_scan(
    strategy: str,
    risk_profile: str,
    admin: dict = Depends(get_admin_user)
):
    """
    Manually trigger a specific scan (admin only).
    This is useful for testing or forcing a refresh.
    """
    if strategy not in ["covered_call", "pmcc"]:
        raise HTTPException(status_code=400, detail="Invalid strategy")
    
    if risk_profile not in ["conservative", "balanced", "aggressive"]:
        raise HTTPException(status_code=400, detail="Invalid risk_profile")
    
    service = await get_scan_service()
    
    logger.info(f"Admin {admin.get('email')} triggered {strategy}/{risk_profile} scan")
    
    if strategy == "covered_call":
        opportunities = await service.run_covered_call_scan(risk_profile)
        await service.store_scan_results("covered_call", risk_profile, opportunities)
    else:  # pmcc
        opportunities = await service.run_pmcc_scan(risk_profile)
        await service.store_scan_results("pmcc", risk_profile, opportunities)
    
    return {
        "message": "Scan complete",
        "strategy": strategy,
        "risk_profile": risk_profile,
        "count": len(opportunities),
        "triggered_by": admin.get("email")
    }


@scans_router.post("/trigger-all")
async def trigger_all_scans(admin: dict = Depends(get_admin_user)):
    """
    Trigger all pre-computed scans (admin only).
    This runs the same logic as the nightly job.
    """
    service = await get_scan_service()
    
    logger.info(f"Admin {admin.get('email')} triggered all scans")
    
    results = await service.run_all_scans()
    
    return {
        "message": "All scans triggered",
        "results": results,
        "triggered_by": admin.get("email")
    }


@scans_router.get("/admin/status")
async def get_scan_status(admin: dict = Depends(get_admin_user)):
    """Get detailed status of all scans (admin only)."""
    service = await get_scan_service()
    scans = await service.get_all_scan_metadata()
    
    return {
        "scans": scans,
        "api_key_configured": False, # No longer applicable
        "total_scans": len(scans)
    }
