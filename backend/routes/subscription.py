"""
Subscription Routes - Payment link management endpoints
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


# Plan definitions with pricing
SUBSCRIPTION_PLANS = {
    "basic": {
        "name": "Basic",
        "monthly_price": 39,
        "yearly_price": 390,
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
            "Dedicated Support"
        ],
        "trial_days": 7
    },
    "standard": {
        "name": "Standard",
        "monthly_price": 69,
        "yearly_price": 690,
        "yearly_savings": "Save 2 months",
        "features": [
            "Everything in Basic",
            "PMCC Strategy Scanner",
            "Powerful Watch List with AI Features",
            "Dedicated Support"
        ],
        "trial_days": 7
    },
    "premium": {
        "name": "Premium",
        "monthly_price": 99,
        "yearly_price": 990,
        "yearly_savings": "Save 2 months",
        "features": [
            "Everything in Standard",
            "Powerful Simulator and Analyser",
            "AI Management of Trades",
            "Selected Dedicated Support"
        ],
        "trial_days": 7
    }
}


@subscription_router.get("/plans")
async def get_subscription_plans():
    """Get all subscription plans with pricing (public endpoint)"""
    return {
        "plans": SUBSCRIPTION_PLANS,
        "trial_days": 7
    }


@subscription_router.get("/links")
async def get_subscription_links():
    """Get active subscription payment links (public endpoint)"""
    # Get PayPal links
    paypal_links = await db.admin_settings.find_one({"type": "paypal_links"}, {"_id": 0})
    paypal_settings = await db.admin_settings.find_one({"type": "paypal_settings"}, {"_id": 0})
    
    paypal_enabled = paypal_settings.get("enabled", False) if paypal_settings else False
    
    if paypal_links and paypal_enabled:
        mode = paypal_links.get("active_mode", "sandbox")
        links_key = f"{mode}_links"
        links = paypal_links.get(links_key, {})
        
        return {
            "provider": "paypal",
            "mode": mode,
            "basic_monthly_link": links.get("basic_monthly", ""),
            "basic_yearly_link": links.get("basic_yearly", ""),
            "standard_monthly_link": links.get("standard_monthly", ""),
            "standard_yearly_link": links.get("standard_yearly", ""),
            "premium_monthly_link": links.get("premium_monthly", ""),
            "premium_yearly_link": links.get("premium_yearly", ""),
            # Legacy support
            "trial_link": links.get("trial", links.get("basic_monthly", "")),
            "monthly_link": links.get("monthly", links.get("standard_monthly", "")),
            "yearly_link": links.get("yearly", links.get("standard_yearly", ""))
        }
    
    # Fallback to Stripe links
    stripe_settings = await db.subscription_settings.find_one({"type": "stripe_links"}, {"_id": 0})
    
    if stripe_settings:
        mode = stripe_settings.get("active_mode", "test")
        links_key = f"{mode}_links"
        links = stripe_settings.get(links_key, {})
        
        return {
            "provider": "stripe",
            "mode": mode,
            "basic_monthly_link": links.get("basic_monthly", links.get("trial", "")),
            "basic_yearly_link": links.get("basic_yearly", ""),
            "standard_monthly_link": links.get("standard_monthly", links.get("monthly", "")),
            "standard_yearly_link": links.get("standard_yearly", ""),
            "premium_monthly_link": links.get("premium_monthly", links.get("yearly", "")),
            "premium_yearly_link": links.get("premium_yearly", ""),
            # Legacy support
            "trial_link": links.get("trial", ""),
            "monthly_link": links.get("monthly", ""),
            "yearly_link": links.get("yearly", "")
        }
    
    return {
        "provider": "none",
        "mode": "test",
        "basic_monthly_link": "",
        "basic_yearly_link": "",
        "standard_monthly_link": "",
        "standard_yearly_link": "",
        "premium_monthly_link": "",
        "premium_yearly_link": ""
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
                "basic_monthly": "",
                "basic_yearly": "",
                "standard_monthly": "",
                "standard_yearly": "",
                "premium_monthly": "",
                "premium_yearly": ""
            },
            "live_links": {
                "basic_monthly": "",
                "basic_yearly": "",
                "standard_monthly": "",
                "standard_yearly": "",
                "premium_monthly": "",
                "premium_yearly": ""
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
