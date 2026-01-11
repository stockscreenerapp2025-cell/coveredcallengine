"""
Subscription Routes - Stripe subscription management endpoints
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import db
from utils.auth import get_admin_user

subscription_router = APIRouter(tags=["Subscription"])


class SubscriptionLinksUpdate(BaseModel):
    mode: str = Field(..., description="'test' or 'live'")
    trial_link: Optional[str] = None
    monthly_link: Optional[str] = None
    yearly_link: Optional[str] = None


@subscription_router.get("/links")
async def get_subscription_links():
    """Get active subscription payment links (public endpoint)"""
    settings = await db.subscription_settings.find_one({"type": "stripe_links"}, {"_id": 0})
    
    if not settings:
        # Return default test links
        return {
            "trial_link": "https://buy.stripe.com/test_14A00caQj0XUeHG43m3ZK02",
            "monthly_link": "https://buy.stripe.com/test_6oU5kw6A3cGC0QQ0Ra3ZK01",
            "yearly_link": "https://buy.stripe.com/test_9B6cMYbUn362bvueI03ZK00",
            "mode": "test"
        }
    
    mode = settings.get("active_mode", "test")
    links_key = f"{mode}_links"
    links = settings.get(links_key, {})
    
    return {
        "trial_link": links.get("trial", ""),
        "monthly_link": links.get("monthly", ""),
        "yearly_link": links.get("yearly", ""),
        "mode": mode
    }


@subscription_router.get("/admin/settings")
async def get_subscription_settings(admin: dict = Depends(get_admin_user)):
    """Get full subscription settings (admin only)"""
    settings = await db.subscription_settings.find_one({"type": "stripe_links"}, {"_id": 0})
    
    if not settings:
        # Return default structure
        return {
            "active_mode": "test",
            "test_links": {
                "trial": "https://buy.stripe.com/test_14A00caQj0XUeHG43m3ZK02",
                "monthly": "https://buy.stripe.com/test_6oU5kw6A3cGC0QQ0Ra3ZK01",
                "yearly": "https://buy.stripe.com/test_9B6cMYbUn362bvueI03ZK00"
            },
            "live_links": {
                "trial": "",
                "monthly": "",
                "yearly": ""
            }
        }
    
    return {
        "active_mode": settings.get("active_mode", "test"),
        "test_links": settings.get("test_links", {}),
        "live_links": settings.get("live_links", {})
    }


@subscription_router.post("/admin/settings")
async def update_subscription_settings(
    active_mode: str = Query(..., description="'test' or 'live'"),
    test_trial: Optional[str] = Query(None),
    test_monthly: Optional[str] = Query(None),
    test_yearly: Optional[str] = Query(None),
    live_trial: Optional[str] = Query(None),
    live_monthly: Optional[str] = Query(None),
    live_yearly: Optional[str] = Query(None),
    admin: dict = Depends(get_admin_user)
):
    """Update subscription settings (admin only)"""
    # Get existing settings
    existing = await db.subscription_settings.find_one({"type": "stripe_links"})
    
    test_links = existing.get("test_links", {}) if existing else {}
    live_links = existing.get("live_links", {}) if existing else {}
    
    # Update only provided values
    if test_trial is not None:
        test_links["trial"] = test_trial
    if test_monthly is not None:
        test_links["monthly"] = test_monthly
    if test_yearly is not None:
        test_links["yearly"] = test_yearly
    if live_trial is not None:
        live_links["trial"] = live_trial
    if live_monthly is not None:
        live_links["monthly"] = live_monthly
    if live_yearly is not None:
        live_links["yearly"] = live_yearly
    
    update_doc = {
        "type": "stripe_links",
        "active_mode": active_mode,
        "test_links": test_links,
        "live_links": live_links,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.subscription_settings.update_one(
        {"type": "stripe_links"},
        {"$set": update_doc},
        upsert=True
    )
    
    return {"message": "Subscription settings updated successfully", "active_mode": active_mode}


@subscription_router.post("/admin/switch-mode")
async def switch_subscription_mode(
    mode: str = Query(..., description="'test' or 'live'"),
    admin: dict = Depends(get_admin_user)
):
    """Quick switch between test and live mode (admin only)"""
    if mode not in ["test", "live"]:
        raise HTTPException(status_code=400, detail="Mode must be 'test' or 'live'")
    
    await db.subscription_settings.update_one(
        {"type": "stripe_links"},
        {"$set": {"active_mode": mode, "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True
    )
    
    return {"message": f"Switched to {mode} mode", "active_mode": mode}
