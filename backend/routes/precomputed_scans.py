"""
Pre-Computed Scans Routes
=========================
API endpoints for accessing pre-computed scan results.

Endpoints:
- GET /api/scans/available - List all available scans with metadata
- GET /api/scans/covered-call/{risk_profile} - Get CC scan results
- GET /api/scans/pmcc/{risk_profile} - Get PMCC scan results
- POST /api/scans/trigger/{strategy}/{risk_profile} - Manually trigger scan (admin)
- POST /api/scans/trigger-all - Trigger all scans (admin)
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from database import db
from utils.auth import get_current_user, get_admin_user

logger = logging.getLogger(__name__)

scans_router = APIRouter(prefix="/scans", tags=["Pre-Computed Scans"])


async def get_scan_service():
    """Get scan service instance with API key."""
    from services.precomputed_scans import PrecomputedScanService
    
    # Get Polygon API key from admin settings
    settings = await db.admin_settings.find_one(
        {"massive_api_key": {"$exists": True}}, 
        {"_id": 0}
    )
    api_key = settings.get("massive_api_key") if settings else None
    
    return PrecomputedScanService(db, api_key)


# ==================== PUBLIC ENDPOINTS ====================

@scans_router.get("/available")
async def get_available_scans(user: dict = Depends(get_current_user)):
    """
    Get list of all available pre-computed scans with metadata.
    Returns scan types, last computed time, and result counts.
    """
    service = await get_scan_service()
    scans = await service.get_all_scan_metadata()
    
    # Group by strategy
    covered_calls = [s for s in scans if s.get("strategy") == "covered_call"]
    pmcc = [s for s in scans if s.get("strategy") == "pmcc"]
    
    # Define all scan buttons (even if not computed yet)
    all_scans = {
        "covered_call": [
            {
                "risk_profile": "conservative",
                "label": "Income Guard",
                "description": "Stable stocks with low volatility and high probability of profit",
                "button_text": "Income Guard – Covered Call (Low Risk)",
                "available": False,
                "count": 0,
                "computed_at": None
            },
            {
                "risk_profile": "balanced",
                "label": "Steady Income",
                "description": "Slightly bullish stocks with moderate volatility",
                "button_text": "Steady Income – Covered Call (Balanced)",
                "available": False,
                "count": 0,
                "computed_at": None
            },
            {
                "risk_profile": "aggressive",
                "label": "Premium Hunter",
                "description": "Strong momentum with premium maximization",
                "button_text": "Premium Hunter – Covered Call (Aggressive)",
                "available": False,
                "count": 0,
                "computed_at": None
            }
        ],
        "pmcc": [
            {
                "risk_profile": "conservative",
                "label": "Capital Efficient Income",
                "description": "PMCC with stable underlying and high delta LEAPS",
                "button_text": "Capital Efficient Income – PMCC (Low Risk)",
                "available": False,
                "count": 0,
                "computed_at": None
            },
            {
                "risk_profile": "balanced",
                "label": "Leveraged Income",
                "description": "Moderate risk PMCC with balanced LEAPS selection",
                "button_text": "Leveraged Income – PMCC (Balanced)",
                "available": False,
                "count": 0,
                "computed_at": None
            },
            {
                "risk_profile": "aggressive",
                "label": "Max Yield Diagonal",
                "description": "Aggressive PMCC targeting maximum premium yield",
                "button_text": "Max Yield Diagonal – PMCC (Aggressive)",
                "available": False,
                "count": 0,
                "computed_at": None
            }
        ]
    }
    
    # Merge with actual data
    for scan in covered_calls:
        profile = scan.get("risk_profile")
        for s in all_scans["covered_call"]:
            if s["risk_profile"] == profile:
                s["available"] = True
                s["count"] = scan.get("count", 0)
                s["computed_at"] = scan.get("computed_at")
                s["label"] = scan.get("label", s["label"])
                s["description"] = scan.get("description", s["description"])
    
    for scan in pmcc:
        profile = scan.get("risk_profile")
        for s in all_scans["pmcc"]:
            if s["risk_profile"] == profile:
                s["available"] = True
                s["count"] = scan.get("count", 0)
                s["computed_at"] = scan.get("computed_at")
    
    return {
        "scans": all_scans,
        "total_scans": len(scans),
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
    Get pre-computed covered call scan results.
    
    Risk profiles:
    - conservative: Income Guard (Low Risk)
    - balanced: Steady Income (Moderate)
    - aggressive: Premium Hunter (High Premium)
    """
    if risk_profile not in ["conservative", "balanced", "aggressive"]:
        raise HTTPException(
            status_code=400, 
            detail="Invalid risk_profile. Use: conservative, balanced, aggressive"
        )
    
    service = await get_scan_service()
    result = await service.get_scan_results("covered_call", risk_profile)
    
    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"No pre-computed results for {risk_profile} covered call scan. "
                   f"Scans run daily at 4:45 PM ET. An admin can trigger a manual scan."
        )
    
    opportunities = result.get("opportunities", [])
    
    # Apply filters
    if min_score > 0:
        opportunities = [o for o in opportunities if o.get("score", 0) >= min_score]
    
    if sector:
        opportunities = [o for o in opportunities if o.get("sector", "").lower() == sector.lower()]
    
    # Apply limit
    opportunities = opportunities[:limit]
    
    return {
        "strategy": "covered_call",
        "risk_profile": risk_profile,
        "label": result.get("label", ""),
        "description": result.get("description", ""),
        "opportunities": opportunities,
        "total": len(opportunities),
        "computed_at": result.get("computed_at"),
        "computed_date": result.get("computed_date"),
        "is_precomputed": True
    }


@scans_router.get("/pmcc/{risk_profile}")
async def get_pmcc_scan(
    risk_profile: str,
    limit: int = Query(50, ge=1, le=100),
    min_score: float = Query(0, ge=0),
    sector: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    """
    Get pre-computed PMCC scan results.
    
    Risk profiles:
    - conservative: Capital Efficient Income (Low Risk)
    - balanced: Leveraged Income (Moderate)
    - aggressive: Max Yield Diagonal (High Premium)
    """
    if risk_profile not in ["conservative", "balanced", "aggressive"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid risk_profile. Use: conservative, balanced, aggressive"
        )
    
    service = await get_scan_service()
    result = await service.get_scan_results("pmcc", risk_profile)
    
    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"No pre-computed results for {risk_profile} PMCC scan. "
                   f"Scans run daily at 4:45 PM ET. An admin can trigger a manual scan."
        )
    
    opportunities = result.get("opportunities", [])
    
    # Apply filters
    if min_score > 0:
        opportunities = [o for o in opportunities if o.get("score", 0) >= min_score]
    
    if sector:
        opportunities = [o for o in opportunities if o.get("sector", "").lower() == sector.lower()]
    
    opportunities = opportunities[:limit]
    
    return {
        "strategy": "pmcc",
        "risk_profile": risk_profile,
        "label": result.get("label", ""),
        "description": result.get("description", ""),
        "opportunities": opportunities,
        "total": len(opportunities),
        "computed_at": result.get("computed_at"),
        "is_precomputed": True
    }


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
    
    if not service.api_key:
        raise HTTPException(
            status_code=400, 
            detail="Polygon API key not configured in admin settings"
        )
    
    logger.info(f"Admin {admin.get('email')} triggered {strategy}/{risk_profile} scan")
    
    if strategy == "covered_call":
        opportunities = await service.run_covered_call_scan(risk_profile)
        await service.store_scan_results("covered_call", risk_profile, opportunities)
        
        return {
            "message": "Scan complete",
            "strategy": strategy,
            "risk_profile": risk_profile,
            "count": len(opportunities),
            "triggered_by": admin.get("email")
        }
    else:
        return {
            "message": "PMCC scans are planned for Phase 3",
            "strategy": strategy,
            "risk_profile": risk_profile,
            "count": 0
        }


@scans_router.post("/trigger-all")
async def trigger_all_scans(admin: dict = Depends(get_admin_user)):
    """
    Trigger all pre-computed scans (admin only).
    This runs the same logic as the nightly job.
    """
    service = await get_scan_service()
    
    if not service.api_key:
        raise HTTPException(
            status_code=400,
            detail="Polygon API key not configured in admin settings"
        )
    
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
        "api_key_configured": bool(service.api_key),
        "total_scans": len(scans)
    }
