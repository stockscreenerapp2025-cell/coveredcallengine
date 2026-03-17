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
    # Try COMPLETED (uppercase) first — EOD pipeline stores this casing
    latest_run = await db.scan_runs.find_one(
        {"status": "COMPLETED"},
        {"run_id": 1, "_id": 0},
        sort=[("completed_at", -1)]
    )
    if latest_run and latest_run.get("run_id"):
        return latest_run.get("run_id")
    # Fallback: lowercase
    latest_run = await db.scan_runs.find_one(
        {"status": "completed"},
        {"run_id": 1, "_id": 0},
        sort=[("completed_at", -1)]
    )
    if latest_run and latest_run.get("run_id"):
        return latest_run.get("run_id")
    # Last resort: get run_id from most recent scan_results_pmcc or scan_results_cc entry
    latest_pmcc = await db.scan_results_pmcc.find_one(
        {}, {"run_id": 1, "_id": 0}, sort=[("created_at", -1)]
    )
    if latest_pmcc and latest_pmcc.get("run_id"):
        return latest_pmcc.get("run_id")
    latest_cc = await db.scan_results_cc.find_one(
        {}, {"run_id": 1, "_id": 0}, sort=[("created_at", -1)]
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
    If the latest run has few results, expands to recent runs (PMCCs don't expire quickly).
    Returns (opportunities, run_info).
    """
    score_floor = min_score if min_score > 0 else (
        60 if risk_profile == "conservative" else
        45 if risk_profile == "balanced" else 30
    )

    # Profile-specific strategy filters — each profile targets a distinct
    # region of the LEAP/short parameter space so results differ meaningfully.
    # IV Rank >= 20 ensures premium is worth selling (applied where available).
    # Each field uses $or with $exists:false so legacy docs without the field still pass.
    def _field_or(field, condition):
        return [
            {field: condition},
            {field: {"$exists": False}},
            {field: None},
        ]

    if risk_profile == "conservative":
        # Capital Efficient: deep ITM LEAP (0.65-0.90δ), 180+ DTE, conservative short
        profile_and = [
            {"$or": _field_or("leap_delta",  {"$gte": 0.65, "$lte": 0.90})},
            {"$or": _field_or("leap_dte",    {"$gte": 180})},
            {"$or": _field_or("short_delta", {"$gte": 0.10, "$lte": 0.35})},
            {"$or": _field_or("short_dte",   {"$gte": 21, "$lte": 60})},
            {"$or": _field_or("roi_cycle",   {"$gte": 0.03})},
        ]
    elif risk_profile == "balanced":
        # Leveraged Income: moderate ITM LEAP (0.55-0.80δ), 150+ DTE, balanced short
        profile_and = [
            {"$or": _field_or("leap_delta",  {"$gte": 0.55, "$lte": 0.80})},
            {"$or": _field_or("leap_dte",    {"$gte": 150})},
            {"$or": _field_or("short_delta", {"$gte": 0.15, "$lte": 0.40})},
            {"$or": _field_or("short_dte",   {"$gte": 14, "$lte": 60})},
            {"$or": _field_or("roi_cycle",   {"$gte": 0.04})},
        ]
    else:
        # Max Yield Diagonal: lower delta LEAP (0.45-0.75δ), 120+ DTE, aggressive short
        profile_and = [
            {"$or": _field_or("leap_delta",  {"$gte": 0.45, "$lte": 0.75})},
            {"$or": _field_or("leap_dte",    {"$gte": 120})},
            {"$or": _field_or("short_delta", {"$gte": 0.15, "$lte": 0.45})},
            {"$or": _field_or("short_dte",   {"$gte": 14, "$lte": 60})},
            {"$or": _field_or("roi_cycle",   {"$gte": 0.05})},
        ]
    profile_filter = {"$and": profile_and}

    async def _fetch_for_runs(run_ids):
        if not run_ids:
            return []
        query = {
            "run_id": {"$in": run_ids},
            "score": {"$gte": score_floor},
            # IV Rank filter: skip if iv_rank field is absent (allow nulls)
            "$or": [{"iv_rank": {"$gte": 20}}, {"iv_rank": None}, {"iv_rank": {"$exists": False}}],
            **profile_filter,
        }
        return await db.scan_results_pmcc.find(
            query, {"_id": 0}
        ).sort("score", -1).limit(limit * 3).to_list(limit * 3)

    # Try latest run first
    results = await _fetch_for_runs([run_id])

    # If too few results, expand to the 5 most recent runs and deduplicate by symbol
    if len(results) < 20:
        # Get run_ids from scan_results_pmcc directly (more reliable than scan_runs)
        recent_pmcc_docs = await db.scan_results_pmcc.find(
            {}, {"run_id": 1, "_id": 0}
        ).sort("created_at", -1).limit(500).to_list(500)
        all_run_ids = list(dict.fromkeys(
            r["run_id"] for r in recent_pmcc_docs if r.get("run_id")
        ))[:5]  # keep only 5 most recent unique run_ids
        if not all_run_ids:
            # fallback to scan_runs if scan_results_pmcc has no run_ids
            recent_runs_cursor = db.scan_runs.find(
                {"status": {"$in": ["COMPLETED", "completed"]}},
                {"run_id": 1, "_id": 0}
            ).sort("completed_at", -1).limit(5)
            recent_runs = await recent_runs_cursor.to_list(5)
            all_run_ids = list({r["run_id"] for r in recent_runs if r.get("run_id")})
        if len(all_run_ids) > 1:
            all_results = await _fetch_for_runs(all_run_ids)
            # Deduplicate by (symbol, expiry, strike) — prefer newest run per key
            run_order = {rid: i for i, rid in enumerate(all_run_ids)}  # lower index = newer
            by_key = {}
            for r in all_results:
                key = (r.get("symbol"), r.get("short_expiry"), r.get("short_strike"))
                if not key[0]:
                    continue
                if key not in by_key:
                    by_key[key] = r
                else:
                    # Prefer newer run (lower index in run_order)
                    existing_order = run_order.get(by_key[key].get("run_id"), 999)
                    new_order = run_order.get(r.get("run_id"), 999)
                    if new_order < existing_order:
                        by_key[key] = r
            results = sorted(by_key.values(), key=lambda x: x.get("score") or 0, reverse=True)

    results = results[:limit]

    # Get run metadata — build a lookup so we can stamp as_of per row
    run_docs = {}
    all_result_run_ids = list({r.get("run_id") for r in results if r.get("run_id")})
    if all_result_run_ids:
        cursor = db.scan_runs.find({"run_id": {"$in": all_result_run_ids}}, {"run_id": 1, "as_of": 1, "completed_at": 1, "_id": 0})
        for doc in await cursor.to_list(len(all_result_run_ids)):
            run_docs[doc["run_id"]] = doc

    # Stamp as_of on each row so users can see data freshness
    for r in results:
        row_run = run_docs.get(r.get("run_id"), {})
        r["as_of"] = row_run.get("as_of") or row_run.get("completed_at")

    run_doc = run_docs.get(run_id) or {}
    run_info = {
        "run_id": run_id,
        "as_of": run_doc.get("as_of"),
        "completed_at": run_doc.get("completed_at")
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
        # short_premium = alias of short_bid (frontend reads this field name)
        "short_premium": sanitize_money(row.get("short_bid")),
        # Economics - MONETARY: 2-decimal
        "net_debit": sanitize_money(row.get("net_debit")),
        "net_debit_total": sanitize_money(row.get("net_debit_total")),
        "width": sanitize_money(row.get("width")),
        "max_profit": sanitize_money(row.get("max_profit")),
        "breakeven": sanitize_money(row.get("breakeven")),
        "roi_annualized": sanitize_percentage(row.get("roi_annualized"), 1),
        # roi_cycle / roi_per_cycle — frontend reads these field names
        "roi_cycle": sanitize_float(row.get("roi_cycle") or row.get("roi_per_cycle")),
        "roi_per_cycle": sanitize_float(row.get("roi_per_cycle") or row.get("roi_cycle")),
        # annualized_roi — alias of roi_annualized (frontend reads this field name)
        "annualized_roi": sanitize_percentage(row.get("roi_annualized"), 1),
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
        "run_id": row.get("run_id"),
        # Extended pmcc_scoring fields
        "stock_equivalent_cost": sanitize_money(row.get("stock_equivalent_cost")),
        "synthetic_stock_cost": sanitize_money(row.get("synthetic_stock_cost")),
        "capital_efficiency_ratio": sanitize_float(row.get("capital_efficiency_ratio")),
        "capital_saved_dollar": sanitize_money(row.get("capital_saved_dollar")),
        "capital_saved_percent": sanitize_float(row.get("capital_saved_percent")),
        "leaps_extrinsic": sanitize_money(row.get("leaps_extrinsic")),
        "leaps_extrinsic_percent": sanitize_float(row.get("leaps_extrinsic_percent")),
        "payback_months": sanitize_float(row.get("payback_months")),
        "payback_cycles": sanitize_float(row.get("payback_cycles")),
        "initial_capped_pl": sanitize_money(row.get("initial_capped_pl")),
        "assignment_risk": row.get("assignment_risk", "Medium"),
        "warning_badges": row.get("warning_badges", []),
        "pmcc_score": sanitize_float(row.get("pmcc_score")),
        "annualized_income_yield": sanitize_float(row.get("annualized_income_yield")),
    }
    return result


async def get_scan_service():
    """Get scan service instance."""
    from services.precomputed_scans import PrecomputedScanService
    # No API key needed for Yahoo Finance
    return PrecomputedScanService(db)


async def _overlay_cached_prices(opportunities: List[Dict]) -> List[Dict]:
    """
    Overlay stock_price from market_snapshot_cache for any symbol that has a
    fresh cache entry.  This keeps precomputed results in sync with the CC
    screener, which writes to the same cache on every custom scan.

    TTL mirrors data_provider.py:
      - market closed : 3 hours
      - market open   : 12 minutes
    """
    if not opportunities:
        return opportunities

    symbols = [o["symbol"] for o in opportunities if o.get("symbol")]
    if not symbols:
        return opportunities

    from services.data_provider import is_market_closed
    ttl_seconds = 3 * 3600 if is_market_closed() else 12 * 60
    now = datetime.now(timezone.utc)

    cached_prices: Dict[str, float] = {}
    async for snap in db.market_snapshot_cache.find(
        {"symbol": {"$in": symbols}},
        {"symbol": 1, "price": 1, "cached_at": 1, "_id": 0}
    ):
        sym = snap.get("symbol")
        price = snap.get("price", 0)
        cached_at = snap.get("cached_at")
        if not (sym and price and cached_at):
            continue
        if isinstance(cached_at, str):
            cached_at = datetime.fromisoformat(cached_at.replace("Z", "+00:00"))
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=timezone.utc)
        if (now - cached_at).total_seconds() <= ttl_seconds:
            cached_prices[sym] = price

    for opp in opportunities:
        sym = opp.get("symbol")
        if sym in cached_prices:
            opp["stock_price"] = round(cached_prices[sym], 2)
            opp["stock_price_source"] = "CACHED_SNAPSHOT"

    return opportunities


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
    
    # Compute PMCC counts using IDENTICAL filtering logic as _get_eod_pmcc_opportunities.
    # Uses _field_or pattern (missing field = pass) and same ranges/score floors.
    # Counts across the 5 most recent completed runs (same multi-run expansion as scan).
    def _fo(field, condition):
        return {"$or": [{field: condition}, {field: {"$exists": False}}, {field: None}]}

    _iv_filter = {"$or": [{"iv_rank": {"$gte": 20}}, {"iv_rank": None}, {"iv_rank": {"$exists": False}}]}

    # Gather multi-run IDs (same expansion as the scan endpoint)
    pmcc_run_ids = []
    if run_id:
        recent_cursor = db.scan_runs.find(
            {"status": {"$in": ["COMPLETED", "completed"]}}, {"run_id": 1, "_id": 0}
        ).sort("completed_at", -1).limit(5)
        recent_docs = await recent_cursor.to_list(5)
        pmcc_run_ids = list({r["run_id"] for r in recent_docs if r.get("run_id")})
        if not pmcc_run_ids:
            pmcc_run_ids = [run_id]

    pmcc_counts = {}
    if pmcc_run_ids:
        run_filter = {"run_id": {"$in": pmcc_run_ids}}

        conservative_q = {**run_filter, "score": {"$gte": 60}, **_iv_filter, "$and": [
            _fo("leap_delta",  {"$gte": 0.65, "$lte": 0.90}),
            _fo("leap_dte",    {"$gte": 180}),
            _fo("short_delta", {"$gte": 0.10, "$lte": 0.35}),
            _fo("short_dte",   {"$gte": 21, "$lte": 60}),
            _fo("roi_cycle",   {"$gte": 0.03}),
        ]}
        balanced_q = {**run_filter, "score": {"$gte": 45}, **_iv_filter, "$and": [
            _fo("leap_delta",  {"$gte": 0.55, "$lte": 0.80}),
            _fo("leap_dte",    {"$gte": 150}),
            _fo("short_delta", {"$gte": 0.15, "$lte": 0.40}),
            _fo("short_dte",   {"$gte": 14, "$lte": 60}),
            _fo("roi_cycle",   {"$gte": 0.04}),
        ]}
        aggressive_q = {**run_filter, "score": {"$gte": 30}, **_iv_filter, "$and": [
            _fo("leap_delta",  {"$gte": 0.45, "$lte": 0.75}),
            _fo("leap_dte",    {"$gte": 120}),
            _fo("short_delta", {"$gte": 0.15, "$lte": 0.45}),
            _fo("short_dte",   {"$gte": 14, "$lte": 60}),
            _fo("roi_cycle",   {"$gte": 0.05}),
        ]}

        # Distinct-symbol counts (mirrors dedup done in the scan endpoint)
        raw_c = await db.scan_results_pmcc.distinct("symbol", conservative_q)
        raw_b = await db.scan_results_pmcc.distinct("symbol", balanced_q)
        raw_a = await db.scan_results_pmcc.distinct("symbol", aggressive_q)
        pmcc_counts["conservative"] = len(raw_c)
        pmcc_counts["balanced"]     = len(raw_b)
        pmcc_counts["aggressive"]   = len(raw_a)
    
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
    limit: int = Query(200, ge=1, le=500),
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

    # Overlay fresh prices from cache so CC scans match the CC screener
    opportunities = await _overlay_cached_prices(opportunities)

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
    limit: int = Query(200, ge=1, le=500),
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

    # Overlay fresh prices from cache so PMCC page matches the CC screener
    opportunities = await _overlay_cached_prices(opportunities)

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
