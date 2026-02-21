"""
EOD Pipeline Routes
===================
Admin endpoints for running and monitoring the EOD pipeline.
Also provides read-only endpoints for pre-computed scan results.
"""
from fastapi import APIRouter, Depends, Query, HTTPException, BackgroundTasks
from typing import Optional
from datetime import datetime, timezone
import logging

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import db
from utils.auth import get_current_user, get_admin_user
from services.eod_pipeline import (
    run_eod_pipeline,
    is_manual_run_allowed,
    get_latest_scan_run,
    get_precomputed_cc_results,
    get_precomputed_pmcc_results,
    EODPipelineResult
)
from services.db_indexes import create_all_indexes

logger = logging.getLogger(__name__)

eod_pipeline_router = APIRouter(prefix="/eod-pipeline", tags=["EOD Pipeline"])


# ============================================================
# PRE-COMPUTED RESULTS (READ-ONLY)
# ============================================================

@eod_pipeline_router.get("/covered-calls")
async def get_cc_opportunities(
    limit: int = Query(50, ge=1, le=200),
    run_id: Optional[str] = Query(None, description="Specific run ID or latest"),
    user: dict = Depends(get_current_user)
):
    """
    Get pre-computed Covered Call opportunities.
    
    This endpoint serves data pre-computed by the EOD pipeline.
    It does NOT make any live API calls.
    
    Returns the latest scan results by default, or results from a specific run_id.
    """
    results = await get_precomputed_cc_results(db, run_id=run_id, limit=limit)
    
    # Get run metadata
    latest_run = await get_latest_scan_run(db)
    run_info = None
    if latest_run:
        run_info = {
            "run_id": latest_run.get("run_id"),
            "completed_at": latest_run.get("completed_at"),
            "universe_version": latest_run.get("universe_version"),
            "symbols_processed": latest_run.get("symbols_processed"),
            "symbols_included": latest_run.get("symbols_included")
        }
    
    return {
        "total": len(results),
        "results": results,
        "opportunities": results,  # Alias for backward compatibility
        "run_info": run_info,
        "data_source": "precomputed_eod",
        "live_data_used": False,
        "architecture": "EOD_PIPELINE_READ_MODEL"
    }


@eod_pipeline_router.get("/pmcc")
async def get_pmcc_opportunities(
    limit: int = Query(50, ge=1, le=200),
    run_id: Optional[str] = Query(None, description="Specific run ID or latest"),
    user: dict = Depends(get_current_user)
):
    """
    Get pre-computed PMCC opportunities.
    
    This endpoint serves data pre-computed by the EOD pipeline.
    It does NOT make any live API calls.
    """
    results = await get_precomputed_pmcc_results(db, run_id=run_id, limit=limit)
    
    # Get run metadata
    latest_run = await get_latest_scan_run(db)
    run_info = None
    if latest_run:
        run_info = {
            "run_id": latest_run.get("run_id"),
            "completed_at": latest_run.get("completed_at"),
            "universe_version": latest_run.get("universe_version")
        }
    
    return {
        "total": len(results),
        "results": results,
        "opportunities": results,
        "run_info": run_info,
        "data_source": "precomputed_eod",
        "live_data_used": False,
        "architecture": "EOD_PIPELINE_READ_MODEL"
    }


@eod_pipeline_router.get("/latest-run")
async def get_latest_run_info(
    user: dict = Depends(get_current_user)
):
    """Get information about the latest completed EOD pipeline run."""
    latest_run = await get_latest_scan_run(db)
    
    if not latest_run:
        return {
            "has_data": False,
            "message": "No completed EOD pipeline runs found"
        }
    
    # Get summary
    run_id = latest_run.get("run_id")
    summary = await db.scan_run_summary.find_one({"run_id": run_id}, {"_id": 0})
    
    # Exclude MongoDB _id
    if latest_run.get("_id"):
        del latest_run["_id"]
    
    return {
        "has_data": True,
        "run": latest_run,
        "summary": summary
    }


# ============================================================
# ADMIN ENDPOINTS (Pipeline Management)
# ============================================================

@eod_pipeline_router.post("/run")
async def trigger_eod_pipeline(
    background_tasks: BackgroundTasks,
    force_build_universe: bool = Query(False, description="Build fresh universe or use latest"),
    admin: dict = Depends(get_admin_user)
):
    """
    Manually trigger the EOD pipeline.
    
    This is an admin-only endpoint.
    In production, manual runs are disabled - use scheduled jobs only.
    
    The pipeline runs in the background and returns immediately.
    """
    if not is_manual_run_allowed():
        raise HTTPException(
            status_code=403,
            detail="Manual EOD pipeline runs are disabled in production. Use scheduled jobs."
        )
    
    # Run in background
    async def run_pipeline():
        try:
            result = await run_eod_pipeline(db, force_build_universe=force_build_universe)
            logger.info(f"EOD Pipeline completed: {result.run_id}")
        except Exception as e:
            logger.error(f"EOD Pipeline failed: {e}")
    
    background_tasks.add_task(run_pipeline)
    
    return {
        "status": "started",
        "message": "EOD pipeline started in background",
        "force_build_universe": force_build_universe,
        "triggered_by": admin.get("email"),
        "triggered_at": datetime.now(timezone.utc).isoformat()
    }


@eod_pipeline_router.post("/create-indexes")
async def create_db_indexes(
    admin: dict = Depends(get_admin_user)
):
    """
    Create all required MongoDB indexes for the EOD pipeline.
    
    This is safe to run multiple times - indexes are created idempotently.
    """
    results = await create_all_indexes(db)
    
    return {
        "status": "completed",
        "indexes": results,
        "created_at": datetime.now(timezone.utc).isoformat()
    }


@eod_pipeline_router.get("/runs")
async def list_pipeline_runs(
    limit: int = Query(10, ge=1, le=50),
    admin: dict = Depends(get_admin_user)
):
    """List recent EOD pipeline runs."""
    try:
        cursor = db.scan_runs.find(
            {},
            {"_id": 0}
        ).sort("completed_at", -1).limit(limit)
        
        runs = await cursor.to_list(length=limit)
        
        return {
            "total": len(runs),
            "runs": runs
        }
    except Exception as e:
        logger.error(f"Failed to list pipeline runs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@eod_pipeline_router.get("/universe")
async def get_current_universe(
    admin: dict = Depends(get_admin_user)
):
    """Get the current universe configuration and statistics."""
    from services.universe_builder import (
        get_latest_universe,
        get_tier_counts,
        get_scan_universe
    )
    
    # Get persisted universe
    latest = await get_latest_universe(db)
    
    # Get tier counts from static data
    tier_counts = get_tier_counts()
    
    # Get synchronous scan universe (Tier 1-3 only)
    sync_universe = get_scan_universe()
    
    return {
        "persisted_universe": {
            "version": latest.get("universe_version") if latest else None,
            "symbol_count": latest.get("symbol_count") if latest else 0,
            "tier_counts": latest.get("tier_counts") if latest else {},
            "created_at": latest.get("created_at") if latest else None
        } if latest else None,
        "static_universe": {
            "symbol_count": len(sync_universe),
            "tier_counts": tier_counts,
            "symbols_sample": sync_universe[:20]
        },
        "target_size": 1500
    }
