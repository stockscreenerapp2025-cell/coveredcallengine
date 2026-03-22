"""
Subscription Routes - Pricing & Plan Configuration (DB-driven)

This module intentionally does NOT manage hosted payment links.
Plans/pricing are served from:
1) admin_settings.type="pricing_config" (editable from Admin UI)
2) fallback to hardcoded SUBSCRIPTION_PLANS
"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import sys
from pathlib import Path

# Keep project-relative imports consistent with your repo structure
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import db
from utils.auth import get_admin_user

subscription_router = APIRouter(tags=["Subscription"])


# Fallback plan definitions (used only if pricing_config is not present in DB)
SUBSCRIPTION_PLANS: Dict[str, Dict[str, Any]] = {
    "basic": {
        "name": "Basic",
        "monthly_price": 29,
        "yearly_price": 290,
        "yearly_savings": "Save 2 months",
        "features": [
            "Access to Covered Call Dashboard",
            "Covered Call Scans",
            "Real Market Data",
            "TradingView Integration",
            "Charts",
            "Key Technical Indicators",
            "Portfolio Tracker",
            "Cancel any time",
            "Dedicated Support",
        ],
        "trial_days": 7,
    },
    "standard": {
        "name": "Standard",
        "monthly_price": 59,
        "yearly_price": 590,
        "yearly_savings": "Save 2 months",
        "features": [
            "Everything in Basic",
            "PMCC Strategy Scanner",
            "Powerful Watch List with AI Features",
            "Dedicated Support",
        ],
        "trial_days": 7,
    },
    "premium": {
        "name": "Premium",
        "monthly_price": 89,
        "yearly_price": 890,
        "yearly_savings": "Save 2 months",
        "features": [
            "Everything in Standard",
            "Powerful Simulator and Analyser",
            "AI Management of Trades",
            "Dedicated Support",
        ],
        "trial_days": 7,
    },
}


async def _get_pricing_config_from_db() -> Optional[Dict[str, Any]]:
    """
    Internal helper used by both public and admin endpoints.
    Other modules (e.g., PayPal) can import and use this if needed.
    """
    return await db.admin_settings.find_one({"type": "pricing_config"}, {"_id": 0})


@subscription_router.get("/plans")
async def get_subscription_plans():
    """
    Public endpoint for Pricing page.
    Returns DB-driven pricing_config if present; otherwise fallback to SUBSCRIPTION_PLANS.
    """
    cfg = await _get_pricing_config_from_db()
    if cfg and cfg.get("plans"):
        return {
            "plans": cfg.get("plans"),
            "trial_days": int(cfg.get("trial_days", 7)),
            "currency": cfg.get("currency", "USD"),
            "updated_at": cfg.get("updated_at"),
        }

    # Fallback: hardcoded
    return {"plans": SUBSCRIPTION_PLANS, "trial_days": 7, "currency": "USD"}


@subscription_router.get("/admin/pricing-config")
async def get_pricing_config(admin: dict = Depends(get_admin_user)):
    """
    Admin endpoint to read the editable pricing config.
    If not set yet, returns a default config built from SUBSCRIPTION_PLANS.
    """
    cfg = await _get_pricing_config_from_db()
    return cfg or {
        "type": "pricing_config",
        "plans": SUBSCRIPTION_PLANS,
        "trial_days": 7,
        "currency": "USD",
    }


class PricingConfig(BaseModel):
    plans: Dict[str, Any]
    trial_days: int = 7
    currency: str = "USD"


@subscription_router.post("/admin/pricing-config")
async def update_pricing_config(payload: PricingConfig, admin: dict = Depends(get_admin_user)):
    """
    Admin endpoint to update pricing config.
    This is what enables future pricing changes from the frontend/admin panel.
    """
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "type": "pricing_config",
        "plans": payload.plans,
        "trial_days": int(payload.trial_days),
        "currency": payload.currency,
        "updated_at": now,
        "updated_by": admin.get("email"),
    }
    await db.admin_settings.update_one({"type": "pricing_config"}, {"$set": doc}, upsert=True)
    return {"success": True, "updated_at": now}


@subscription_router.get("/admin/settings")
async def get_subscription_settings(admin: dict = Depends(get_admin_user)):
    """Return current active_mode + test/live payment links for Admin Billing tab."""
    doc = await db.admin_settings.find_one({"type": "stripe_settings"}, {"_id": 0})
    if not doc:
        return {
            "active_mode": "test",
            "test_links": {"trial": "", "monthly": "", "yearly": ""},
            "live_links": {"trial": "", "monthly": "", "yearly": ""},
        }
    return {
        "active_mode": doc.get("active_mode", "test"),
        "test_links": doc.get("test_links", {"trial": "", "monthly": "", "yearly": ""}),
        "live_links": doc.get("live_links", {"trial": "", "monthly": "", "yearly": ""}),
    }


@subscription_router.post("/admin/settings")
async def save_subscription_settings(
    active_mode: str = Query("test"),
    test_trial: str = Query(""),
    test_monthly: str = Query(""),
    test_yearly: str = Query(""),
    live_trial: str = Query(""),
    live_monthly: str = Query(""),
    live_yearly: str = Query(""),
    admin: dict = Depends(get_admin_user),
):
    """Save active_mode + test/live payment links from Admin Billing tab."""
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "type": "stripe_settings",
        "active_mode": active_mode,
        "test_links": {"trial": test_trial, "monthly": test_monthly, "yearly": test_yearly},
        "live_links": {"trial": live_trial, "monthly": live_monthly, "yearly": live_yearly},
        "updated_at": now,
        "updated_by": admin.get("email"),
    }
    await db.admin_settings.update_one({"type": "stripe_settings"}, {"$set": doc}, upsert=True)
    return {"success": True, "active_mode": active_mode}


@subscription_router.post("/admin/switch-mode")
async def switch_subscription_mode(
    mode: str = Query(..., description="test or live"),
    admin: dict = Depends(get_admin_user),
):
    """Quickly flip between test and live payment link mode."""
    if mode not in ("test", "live"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="mode must be 'test' or 'live'")
    now = datetime.now(timezone.utc).isoformat()
    await db.admin_settings.update_one(
        {"type": "stripe_settings"},
        {"$set": {"active_mode": mode, "updated_at": now, "updated_by": admin.get("email")}},
        upsert=True,
    )
    return {"success": True, "active_mode": mode}


@subscription_router.get("/links")
async def get_subscription_links():
    """
    Public endpoint for Pricing page to fetch payment links.
    Returns PayPal hosted links from admin_settings.
    Schema must match frontend Pricing.js expectations.
    """
    # Default schema with null values
    default_links = {
        "basic_monthly_link": None,
        "basic_yearly_link": None,
        "standard_monthly_link": None,
        "standard_yearly_link": None,
        "premium_monthly_link": None,
        "premium_yearly_link": None,
    }
    
    settings = await db.admin_settings.find_one({"type": "paypal_links"}, {"_id": 0})
    stripe_settings = await db.admin_settings.find_one({"type": "stripe_settings"}, {"_id": 0})

    # Determine mode from stripe_settings (used by Billing tab) or paypal_settings
    mode = "test"
    if stripe_settings:
        mode = stripe_settings.get("active_mode", "test")
    else:
        paypal_settings = await db.admin_settings.find_one({"type": "paypal_settings"}, {"_id": 0})
        if paypal_settings:
            mode = "live" if paypal_settings.get("mode") == "live" else "test"

    # Get links from paypal_links collection first, fallback to stripe_settings
    configured_links = {}
    if settings:
        configured_links = settings.get("live_links" if mode == "live" else "sandbox_links", {})

    # If no paypal_links, use stripe_settings monthly link for all plans
    if not configured_links and stripe_settings:
        link_set = stripe_settings.get("live_links" if mode == "live" else "test_links", {})
        monthly = link_set.get("monthly") or None
        yearly = link_set.get("yearly") or None
        trial = link_set.get("trial") or None
        configured_links = {
            "basic_monthly_link": monthly,
            "basic_yearly_link": yearly,
            "standard_monthly_link": monthly,
            "standard_yearly_link": yearly,
            "premium_monthly_link": monthly,
            "premium_yearly_link": yearly,
            "trial_link": trial,
        }

    # Merge configured links with defaults (preserving null for unconfigured)
    return {**default_links, **configured_links}
