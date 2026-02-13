"""
PayPal Routes - PayPal payment management endpoints

Supports:
- Hosted PayPal "link" checkout (admin-configured links per plan/cycle)
- PayPal Express Checkout + Recurring Profiles (for automatic renewals)
- Server-side subscription lifecycle + access control updates
- Trial-period marketing email automation triggers
"""
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta
import logging

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import db
from utils.auth import get_current_user, get_admin_user
from services.paypal_service import PayPalService
from services.email_automation import EmailAutomationService
from routes.subscription import SUBSCRIPTION_PLANS

logger = logging.getLogger(__name__)

paypal_router = APIRouter(tags=["PayPal"])

# Initialize PayPal service
paypal_service = PayPalService(db)


class PayPalSettingsUpdate(BaseModel):
    enabled: bool = True
    api_username: str
    api_password: str
    api_signature: str
    mode: str = "sandbox"  # sandbox or live


class PayPalLinksUpdate(BaseModel):
    active_mode: str = Field("sandbox", description="sandbox or live")
    sandbox_links: Dict[str, str] = Field(default_factory=dict)
    live_links: Dict[str, str] = Field(default_factory=dict)


class CreateCheckoutRequest(BaseModel):
    plan_id: str = Field(..., description="basic, standard, or premium")
    billing_cycle: str = Field(..., description="monthly or yearly")
    start_with_trial: bool = Field(True, description="If true, start with 7-day trial before billing")
    return_url: str
    cancel_url: str


# ==================== PUBLIC ENDPOINTS ====================

@paypal_router.get("/config")
async def get_paypal_config():
    """Get PayPal configuration status (public - for pricing page)"""
    settings = await db.admin_settings.find_one({"type": "paypal_settings"}, {"_id": 0})
    if not settings or not settings.get("enabled", False):
        return {"enabled": False, "mode": None}
    return {"enabled": True, "mode": settings.get("mode", "sandbox")}


@paypal_router.get("/links")
async def get_paypal_links():
    """DEPRECATED: Hosted PayPal links removed.

    Use /paypal/create-checkout (Express Checkout) instead.
    Kept temporarily so older frontends don't hard-fail.
    """
    settings = await db.admin_settings.find_one({"type": "paypal_settings"}, {"_id": 0})
    enabled = settings.get("enabled", False) if settings else False
    mode = settings.get("mode", "sandbox") if settings else "sandbox"
    return {
        "enabled": enabled,
        "mode": mode,
        "deprecated": True,
        "message": "Hosted PayPal links have been removed. Use Express Checkout (/paypal/create-checkout).",
        "basic_monthly_link": "", "basic_yearly_link": "",
        "standard_monthly_link": "", "standard_yearly_link": "",
        "premium_monthly_link": "", "premium_yearly_link": "",
    }

@paypal_router.post("/create-checkout")
async def create_checkout(payload: CreateCheckoutRequest, user: dict = Depends(get_current_user)):
    """
    Create a PayPal Express Checkout session.

    This is used when you want PayPal to handle renewals (recurring profile),
    while our system still controls feature access by updating the user's subscription state.
    
    Pricing is DB-driven (admin_settings.type="pricing_config") with fallback to hardcoded.
    """
    plan_id = payload.plan_id.lower().strip()
    billing_cycle = payload.billing_cycle.lower().strip()

    # Load pricing from DB first, fallback to hardcoded SUBSCRIPTION_PLANS
    pricing_config = await db.admin_settings.find_one({"type": "pricing_config"}, {"_id": 0})
    if pricing_config and pricing_config.get("plans"):
        plans = pricing_config["plans"]
    else:
        plans = SUBSCRIPTION_PLANS

    if plan_id not in plans:
        raise HTTPException(status_code=400, detail="Invalid plan_id")
    if billing_cycle not in ["monthly", "yearly"]:
        raise HTTPException(status_code=400, detail="Invalid billing_cycle")

    plan = plans[plan_id]
    
    # Amount we will charge as part of the initial checkout.
    # If starting with trial, we use a minimal verification amount.
    if payload.start_with_trial:
        checkout_amount = 0.01
    else:
        checkout_amount = float(plan.get(f"{billing_cycle}_price", 0))

    await paypal_service.initialize()

    result = await paypal_service.set_express_checkout(
        amount=checkout_amount,
        plan_id=plan_id,
        billing_cycle=billing_cycle,
        is_trial=bool(payload.start_with_trial),
        return_url=payload.return_url,
        cancel_url=payload.cancel_url,
        customer_email=user.get("email")
    )

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Checkout creation failed"))

    logger.info(f"[PayPal] Checkout created for user={user.get('email')}, plan={plan_id}, cycle={billing_cycle}, trial={payload.start_with_trial}")
    return result


@paypal_router.get("/checkout-return")
async def checkout_return(token: str = Query(...), PayerID: str = Query(...)):
    """
    Handle return from PayPal after user approves checkout.

    Creates a recurring profile for monthly/yearly billing (with optional 7-day trial)
    and updates the user's subscription state in our DB.
    
    - Sets access_active = True
    - Stores paypal_profile_id
    - Triggers email automation for subscription_created
    """
    await paypal_service.initialize()

    details = await paypal_service.get_express_checkout_details(token)
    if not details.get("success"):
        raise HTTPException(status_code=400, detail=details.get("error", "Failed to get checkout details"))

    email = details.get("email")
    metadata = details.get("metadata", {}) or {}

    plan_id = (metadata.get("plan_id") or "standard").lower()
    billing_cycle = (metadata.get("billing_cycle") or "monthly").lower()
    is_trial = metadata.get("is_trial") in ["1", "true", "True"]

    # Load pricing from DB first, fallback to hardcoded SUBSCRIPTION_PLANS
    pricing_config = await db.admin_settings.find_one({"type": "pricing_config"}, {"_id": 0})
    if pricing_config and pricing_config.get("plans"):
        plans = pricing_config["plans"]
    else:
        plans = SUBSCRIPTION_PLANS

    if plan_id not in plans:
        plan_id = "standard"
    if billing_cycle not in ["monthly", "yearly"]:
        billing_cycle = "monthly"

    plan = plans[plan_id]

    # Complete the initial payment (0.01 for trial verification OR full amount if no-trial)
    amount = float(details.get("amount", 0) or 0)
    payment_result = await paypal_service.do_express_checkout_payment(
        token=token,
        payer_id=PayerID,
        amount=amount
    )
    if not payment_result.get("success"):
        raise HTTPException(status_code=400, detail=payment_result.get("error", "Payment failed"))

    # Create recurring profile (PayPal handles ongoing billing)
    full_amount = float(plan.get(f"{billing_cycle}_price", 0))
    description = f"Covered Call Engine - {plan.get('name', plan_id.title())} ({billing_cycle})"

    profile_id = None
    trial_days = int(plan.get("trial_days", 7)) if is_trial else 0
    
    profile_result = await paypal_service.create_recurring_profile(
        token=token,
        payer_id=PayerID,
        amount=full_amount,
        billing_cycle=billing_cycle,
        description=description,
        trial_days=trial_days,
        trial_amount=0.00,
    )
    if profile_result.get("success"):
        profile_id = profile_result.get("profile_id")
    else:
        logger.warning(f"[PayPal] Failed to create recurring profile: {profile_result.get('error')}")

    now = datetime.now(timezone.utc)

    # Build subscription object
    if is_trial and trial_days > 0:
        trial_end = now + timedelta(days=trial_days)
        next_billing = trial_end
        status = "trialing"
    else:
        next_billing = now + timedelta(days=30 if billing_cycle == "monthly" else 365)
        status = "active"

    subscription_data = {
        "plan_id": plan_id,
        "plan_name": plan.get("name", plan_id.title()),
        "billing_cycle": billing_cycle,
        "status": status,
        "subscription_start": now.isoformat(),
        "next_billing_date": next_billing.isoformat(),
        "payment_status": "succeeded",
        "payment_provider": "paypal",
        "trial_days": int(SUBSCRIPTION_PLANS[plan_id].get("trial_days", 7)),
    }
    if is_trial:
        subscription_data.update({
            "trial_start": now.isoformat(),
            "trial_end": (now + timedelta(days=int(SUBSCRIPTION_PLANS[plan_id].get("trial_days", 7)))).isoformat(),
        })

    user_doc = await db.users.find_one({"email": email})
    if user_doc:
        update_doc: Dict[str, Any] = {
            "subscription": subscription_data,
            "paypal_payer_id": PayerID,
            "updated_at": now.isoformat(),
            "access_active": True,
        }
        if profile_id:
            update_doc["paypal_profile_id"] = profile_id

        await db.users.update_one({"email": email}, {"$set": update_doc})

        # Trigger marketing emails during trial (welcome, followups)
        if subscription_data.get("status") == "trialing":
            try:
                automation = EmailAutomationService(db)
                await automation.initialize()
                await automation.trigger_event(
                    trigger_type="subscription_created",
                    user=user_doc,
                    subscription=subscription_data
                )
            except Exception as e:
                logger.error(f"Failed to trigger trial marketing emails: {e}")

    # Log transaction
    await db.paypal_transactions.insert_one({
        "email": email,
        "transaction_id": payment_result.get("transaction_id"),
        "profile_id": profile_id,
        "plan_id": plan_id,
        "billing_cycle": billing_cycle,
        "amount": full_amount,
        "initial_amount": amount,
        "status": "completed",
        "created_at": now.isoformat(),
        "provider": "paypal"
    })

    return {
        "success": True,
        "email": email,
        "plan_id": plan_id,
        "billing_cycle": billing_cycle,
        "status": subscription_data.get("status"),
        "profile_id": profile_id
    }


# ==================== PAYPAL IPN (LIFECYCLE) ====================

@paypal_router.post("/ipn")
async def paypal_ipn(request: Request):
    """
    PayPal IPN listener.

    Configure this URL in your PayPal profile so we can:
    - Activate access on payment
    - Deactivate on cancellation
    - Mark past_due on failures
    - Trigger configured marketing emails (trial + lifecycle)

    We keep it permissive (always 200) to reduce PayPal retries,
    but we only apply updates if verification succeeds.
    """
    try:
        form = await request.form()
        data = dict(form)
    except Exception:
        data = {}

    await paypal_service.initialize()

    verified = await paypal_service.verify_ipn(data)
    if not verified:
        logger.warning("Unverified PayPal IPN received")
        return {"ok": True}

    txn_type = (data.get("txn_type") or "").strip()
    profile_id = data.get("recurring_payment_id") or data.get("rp_invoice_id") or data.get("subscr_id") or ""
    if not profile_id:
        return {"ok": True}

    now = datetime.now(timezone.utc)
    user_doc = await db.users.find_one({"paypal_profile_id": profile_id})
    if not user_doc:
        return {"ok": True}

    subscription = user_doc.get("subscription", {}) or {}

    # Common txn_type values: recurring_payment, recurring_payment_failed, recurring_payment_profile_cancel, subscr_cancel
    if txn_type in ["recurring_payment", "subscr_payment"]:
        subscription["status"] = "active"
        subscription["payment_status"] = "succeeded"
        subscription["last_payment_at"] = now.isoformat()
        subscription["access_active"] = True

        cycle = subscription.get("billing_cycle", subscription.get("plan", "monthly"))
        subscription["billing_cycle"] = cycle
        subscription["next_billing_date"] = (now + timedelta(days=30 if cycle == "monthly" else 365)).isoformat()

        await db.users.update_one(
            {"_id": user_doc["_id"]},
            {"$set": {"subscription": subscription, "access_active": True, "updated_at": now.isoformat()}}
        )

        # Trigger automation emails (payment succeeded / renewed)
        try:
            automation = EmailAutomationService(db)
            await automation.initialize()
            await automation.trigger_event("subscription_payment_succeeded", user_doc, subscription=subscription)
        except Exception as e:
            logger.error(f"Email automation trigger (payment_succeeded) failed: {e}")

    elif txn_type in ["recurring_payment_failed", "subscr_failed"]:
        subscription["status"] = "past_due"
        subscription["payment_status"] = "failed"
        subscription["last_failure_at"] = now.isoformat()

        await db.users.update_one(
            {"_id": user_doc["_id"]},
            {"$set": {"subscription": subscription, "access_active": False, "updated_at": now.isoformat()}}
        )

        # Trigger automation emails (payment failed)
        try:
            automation = EmailAutomationService(db)
            await automation.initialize()
            await automation.trigger_event("subscription_payment_failed", user_doc, subscription=subscription)
        except Exception as e:
            logger.error(f"Email automation trigger (payment_failed) failed: {e}")

    elif txn_type in ["recurring_payment_profile_cancel", "subscr_cancel"]:
        subscription["status"] = "cancelled"
        subscription["payment_status"] = "cancelled"
        subscription["cancelled_at"] = now.isoformat()

        await db.users.update_one(
            {"_id": user_doc["_id"]},
            {"$set": {"subscription": subscription, "access_active": False, "updated_at": now.isoformat()}}
        )

        # Trigger automation emails (subscription cancelled)
        try:
            automation = EmailAutomationService(db)
            await automation.initialize()
            await automation.trigger_event("subscription_cancelled", user_doc, subscription=subscription)
        except Exception as e:
            logger.error(f"Email automation trigger (cancelled) failed: {e}")

    # Log IPN event
    await db.paypal_ipn_logs.insert_one({
        "profile_id": profile_id,
        "txn_type": txn_type,
        "data": data,
        "received_at": now.isoformat()
    })

    return {"ok": True}

# ==================== ADMIN ENDPOINTS ====================

@paypal_router.get("/admin/settings")
async def get_paypal_settings(admin: dict = Depends(get_admin_user)):
    """Get PayPal settings (admin)"""
    settings = await db.admin_settings.find_one({"type": "paypal_settings"}, {"_id": 0})
    if not settings:
        return {"enabled": False, "mode": "sandbox"}
    # Never return secrets in full; just indicate presence
    return {
        "enabled": bool(settings.get("enabled", False)),
        "mode": settings.get("mode", "sandbox"),
        "api_username_set": bool(settings.get("api_username")),
        "api_password_set": bool(settings.get("api_password")),
        "api_signature_set": bool(settings.get("api_signature")),
    }


@paypal_router.post("/admin/settings")
async def update_paypal_settings(payload: PayPalSettingsUpdate, admin: dict = Depends(get_admin_user)):
    """Update PayPal settings (admin)"""
    doc = payload.model_dump()
    doc["type"] = "paypal_settings"
    doc["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.admin_settings.update_one({"type": "paypal_settings"}, {"$set": doc}, upsert=True)
    return {"success": True}


@paypal_router.get("/admin/links")
async def get_paypal_links_admin(admin: dict = Depends(get_admin_user)):
    """Get PayPal hosted payment links config (admin)"""
    settings = await db.admin_settings.find_one({"type": "paypal_links"}, {"_id": 0})
    if not settings:
        return {
            "active_mode": "sandbox",
            "sandbox_links": {
                "basic_monthly": "", "basic_yearly": "",
                "standard_monthly": "", "standard_yearly": "",
                "premium_monthly": "", "premium_yearly": ""
            },
            "live_links": {
                "basic_monthly": "", "basic_yearly": "",
                "standard_monthly": "", "standard_yearly": "",
                "premium_monthly": "", "premium_yearly": ""
            }
        }
    return {
        "active_mode": settings.get("active_mode", "sandbox"),
        "sandbox_links": settings.get("sandbox_links", {}),
        "live_links": settings.get("live_links", {}),
    }


@paypal_router.post("/admin/links")
async def update_paypal_links_admin(payload: PayPalLinksUpdate, admin: dict = Depends(get_admin_user)):
    """Update PayPal hosted payment links config (admin)"""
    if payload.active_mode not in ["sandbox", "live"]:
        raise HTTPException(status_code=400, detail="active_mode must be 'sandbox' or 'live'")
    doc = payload.model_dump()
    doc["type"] = "paypal_links"
    doc["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.admin_settings.update_one({"type": "paypal_links"}, {"$set": doc}, upsert=True)
    return {"success": True}