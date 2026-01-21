"""
PayPal Routes - PayPal payment management endpoints
"""
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone, timedelta

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import db
from utils.auth import get_current_user, get_admin_user
from services.paypal_service import PayPalService

paypal_router = APIRouter(tags=["PayPal"])

# Initialize PayPal service
paypal_service = PayPalService(db)


class PayPalSettingsUpdate(BaseModel):
    api_username: str
    api_password: str
    api_signature: str
    mode: str = "sandbox"  # sandbox or live


class CheckoutRequest(BaseModel):
    plan_type: str = Field(..., description="trial, monthly, or yearly")
    return_url: str
    cancel_url: str


# ==================== PUBLIC ENDPOINTS ====================

@paypal_router.get("/config")
async def get_paypal_config():
    """Get PayPal configuration status (public - for pricing page)"""
    settings = await db.admin_settings.find_one({"type": "paypal_settings"}, {"_id": 0})
    
    if not settings or not settings.get("enabled", False):
        return {
            "enabled": False,
            "mode": None
        }
    
    return {
        "enabled": True,
        "mode": settings.get("mode", "sandbox")
    }


@paypal_router.get("/links")
async def get_paypal_links():
    """Get PayPal payment links (public endpoint for pricing page)"""
    settings = await db.admin_settings.find_one({"type": "paypal_links"}, {"_id": 0})
    
    if not settings:
        return {
            "enabled": False,
            "trial_link": "",
            "monthly_link": "",
            "yearly_link": "",
            "mode": "sandbox"
        }
    
    # Check if PayPal is enabled
    paypal_settings = await db.admin_settings.find_one({"type": "paypal_settings"}, {"_id": 0})
    enabled = paypal_settings.get("enabled", False) if paypal_settings else False
    
    mode = settings.get("active_mode", "sandbox")
    links_key = f"{mode}_links"
    links = settings.get(links_key, {})
    
    return {
        "enabled": enabled,
        "trial_link": links.get("trial", ""),
        "monthly_link": links.get("monthly", ""),
        "yearly_link": links.get("yearly", ""),
        "mode": mode
    }


@paypal_router.post("/create-checkout")
async def create_checkout(
    request: CheckoutRequest,
    user: dict = Depends(get_current_user)
):
    """Create a PayPal Express Checkout session"""
    # Get pricing for plan
    prices = {
        "trial": 0.00,
        "monthly": 49.00,
        "yearly": 499.00
    }
    
    amount = prices.get(request.plan_type)
    if amount is None:
        raise HTTPException(status_code=400, detail="Invalid plan type")
    
    # For trial, we don't charge but still create a session for card verification
    if request.plan_type == "trial":
        amount = 0.01  # Minimal amount for verification
    
    await paypal_service.initialize()
    
    result = await paypal_service.set_express_checkout(
        amount=amount,
        plan_type=request.plan_type,
        return_url=request.return_url,
        cancel_url=request.cancel_url,
        customer_email=user.get("email")
    )
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Checkout creation failed"))
    
    return result


@paypal_router.get("/checkout-return")
async def checkout_return(
    token: str = Query(...),
    PayerID: str = Query(...)
):
    """Handle return from PayPal after user approves payment"""
    await paypal_service.initialize()
    
    # Get checkout details
    details = await paypal_service.get_express_checkout_details(token)
    
    if not details.get("success"):
        raise HTTPException(status_code=400, detail=details.get("error", "Failed to get checkout details"))
    
    amount = float(details.get("amount", 0))
    plan_type = details.get("plan_type", "monthly")
    email = details.get("email")
    
    # Complete the payment
    payment_result = await paypal_service.do_express_checkout_payment(
        token=token,
        payer_id=PayerID,
        amount=amount
    )
    
    if not payment_result.get("success"):
        raise HTTPException(status_code=400, detail=payment_result.get("error", "Payment failed"))
    
    # For subscriptions (monthly/yearly), create recurring profile
    profile_id = None
    if plan_type in ["monthly", "yearly"]:
        profile_result = await paypal_service.create_recurring_profile(
            token=token,
            payer_id=PayerID,
            amount=amount,
            plan_type=plan_type,
            description=f"Covered Call Engine - {plan_type.title()} Subscription"
        )
        
        if profile_result.get("success"):
            profile_id = profile_result.get("profile_id")
    
    # Update user subscription in database
    now = datetime.now(timezone.utc)
    
    if plan_type == "trial":
        trial_end = now + timedelta(days=7)
        subscription_data = {
            "plan": "trial",
            "status": "trialing",
            "trial_start": now.isoformat(),
            "trial_end": trial_end.isoformat(),
            "subscription_start": now.isoformat(),
            "next_billing_date": trial_end.isoformat(),
            "payment_status": "succeeded",
            "payment_provider": "paypal"
        }
    else:
        next_billing = now + timedelta(days=30 if plan_type == "monthly" else 365)
        subscription_data = {
            "plan": plan_type,
            "status": "active",
            "subscription_start": now.isoformat(),
            "next_billing_date": next_billing.isoformat(),
            "payment_status": "succeeded",
            "payment_provider": "paypal"
        }
    
    # Find and update user
    user = await db.users.find_one({"email": email})
    
    if user:
        update_doc = {
            "subscription": subscription_data,
            "paypal_payer_id": PayerID,
            "updated_at": now.isoformat()
        }
        if profile_id:
            update_doc["paypal_profile_id"] = profile_id
        
        await db.users.update_one(
            {"email": email},
            {"$set": update_doc}
        )
    
    # Log the transaction
    await db.paypal_transactions.insert_one({
        "email": email,
        "transaction_id": payment_result.get("transaction_id"),
        "profile_id": profile_id,
        "amount": amount,
        "plan_type": plan_type,
        "status": payment_result.get("payment_status"),
        "timestamp": now.isoformat()
    })
    
    return {
        "success": True,
        "plan": plan_type,
        "transaction_id": payment_result.get("transaction_id"),
        "message": f"Successfully subscribed to {plan_type} plan"
    }


@paypal_router.post("/ipn")
async def handle_ipn(request: Request):
    """Handle PayPal IPN (Instant Payment Notification) webhook"""
    raw_body = await request.body()
    
    await paypal_service.initialize()
    
    # Verify and parse IPN
    ipn_result = await paypal_service.process_ipn(raw_body)
    
    if not ipn_result.get("success"):
        # Still return 200 to acknowledge receipt
        return {"status": "invalid"}
    
    # Handle subscription events
    await paypal_service.handle_subscription_event(ipn_result.get("data", {}))
    
    return {"status": "processed"}


@paypal_router.post("/cancel-subscription")
async def cancel_subscription(user: dict = Depends(get_current_user)):
    """Cancel user's PayPal subscription"""
    profile_id = user.get("paypal_profile_id")
    
    if not profile_id:
        raise HTTPException(status_code=400, detail="No active PayPal subscription found")
    
    await paypal_service.initialize()
    
    result = await paypal_service.cancel_recurring_profile(profile_id)
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to cancel subscription"))
    
    # Update user record
    now = datetime.now(timezone.utc)
    await db.users.update_one(
        {"id": user.get("id")},
        {"$set": {
            "subscription.status": "cancelled",
            "subscription.cancelled_at": now.isoformat(),
            "updated_at": now.isoformat()
        }}
    )
    
    return {"success": True, "message": "Subscription cancelled successfully"}


# ==================== ADMIN ENDPOINTS ====================

@paypal_router.get("/admin/settings")
async def get_paypal_settings(admin: dict = Depends(get_admin_user)):
    """Get PayPal settings (admin only)"""
    settings = await db.admin_settings.find_one({"type": "paypal_settings"}, {"_id": 0})
    
    if not settings:
        return {
            "enabled": False,
            "api_username": "",
            "api_password": "",
            "api_signature": "",
            "mode": "sandbox",
            "configured": False
        }
    
    # Mask sensitive data
    return {
        "enabled": settings.get("enabled", False),
        "api_username": settings.get("api_username", ""),
        "api_password": "••••••••" if settings.get("api_password") else "",
        "api_signature": "••••••••" if settings.get("api_signature") else "",
        "mode": settings.get("mode", "sandbox"),
        "configured": bool(settings.get("api_username") and settings.get("api_password") and settings.get("api_signature")),
        "updated_at": settings.get("updated_at")
    }


@paypal_router.post("/admin/settings")
async def update_paypal_settings(
    api_username: str = Query(None),
    api_password: str = Query(None),
    api_signature: str = Query(None),
    mode: str = Query("sandbox"),
    enabled: bool = Query(True),
    admin: dict = Depends(get_admin_user)
):
    """Update PayPal settings (admin only)"""
    # Get existing settings to preserve unchanged fields
    existing = await db.admin_settings.find_one({"type": "paypal_settings"})
    
    update_doc = {
        "type": "paypal_settings",
        "enabled": enabled,
        "mode": mode,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    
    # Only update credentials if provided (not masked values)
    if api_username:
        update_doc["api_username"] = api_username
    elif existing:
        update_doc["api_username"] = existing.get("api_username", "")
    
    if api_password and api_password != "••••••••":
        update_doc["api_password"] = api_password
    elif existing:
        update_doc["api_password"] = existing.get("api_password", "")
    
    if api_signature and api_signature != "••••••••":
        update_doc["api_signature"] = api_signature
    elif existing:
        update_doc["api_signature"] = existing.get("api_signature", "")
    
    await db.admin_settings.update_one(
        {"type": "paypal_settings"},
        {"$set": update_doc},
        upsert=True
    )
    
    # Reinitialize the service
    await paypal_service.initialize()
    
    return {"message": "PayPal settings updated successfully", "enabled": enabled, "mode": mode}


@paypal_router.post("/admin/test-connection")
async def test_paypal_connection(admin: dict = Depends(get_admin_user)):
    """Test PayPal API connection (admin only)"""
    await paypal_service.initialize()
    result = await paypal_service.test_connection()
    return result


@paypal_router.get("/admin/transactions")
async def get_transactions(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    admin: dict = Depends(get_admin_user)
):
    """Get PayPal transaction history (admin only)"""
    skip = (page - 1) * limit
    
    total = await db.paypal_transactions.count_documents({})
    
    cursor = db.paypal_transactions.find(
        {},
        {"_id": 0}
    ).sort("timestamp", -1).skip(skip).limit(limit)
    
    transactions = await cursor.to_list(length=limit)
    
    return {
        "transactions": transactions,
        "page": page,
        "pages": (total + limit - 1) // limit,
        "total": total
    }


@paypal_router.get("/admin/webhook-logs")
async def get_webhook_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    admin: dict = Depends(get_admin_user)
):
    """Get PayPal webhook/IPN logs (admin only)"""
    skip = (page - 1) * limit
    
    total = await db.paypal_webhook_logs.count_documents({})
    
    cursor = db.paypal_webhook_logs.find(
        {},
        {"_id": 0, "raw_data": 0}  # Exclude raw data for brevity
    ).sort("timestamp", -1).skip(skip).limit(limit)
    
    logs = await cursor.to_list(length=limit)
    
    return {
        "logs": logs,
        "page": page,
        "pages": (total + limit - 1) // limit,
        "total": total
    }


@paypal_router.post("/admin/switch-mode")
async def switch_paypal_mode(
    mode: str = Query(..., description="'sandbox' or 'live'"),
    admin: dict = Depends(get_admin_user)
):
    """Switch between PayPal sandbox and live mode (admin only)"""
    if mode not in ["sandbox", "live"]:
        raise HTTPException(status_code=400, detail="Mode must be 'sandbox' or 'live'")
    
    await db.admin_settings.update_one(
        {"type": "paypal_settings"},
        {"$set": {"mode": mode, "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True
    )
    
    # Also update paypal_links active_mode
    await db.admin_settings.update_one(
        {"type": "paypal_links"},
        {"$set": {"active_mode": mode, "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True
    )
    
    # Reinitialize service
    await paypal_service.initialize()
    
    return {"message": f"Switched to {mode} mode", "mode": mode}


@paypal_router.get("/admin/links")
async def get_paypal_links_admin(admin: dict = Depends(get_admin_user)):
    """Get PayPal payment links settings (admin only)"""
    settings = await db.admin_settings.find_one({"type": "paypal_links"}, {"_id": 0})
    
    if not settings:
        return {
            "active_mode": "sandbox",
            "sandbox_links": {
                "trial": "",
                "monthly": "",
                "yearly": ""
            },
            "live_links": {
                "trial": "",
                "monthly": "",
                "yearly": ""
            }
        }
    
    return {
        "active_mode": settings.get("active_mode", "sandbox"),
        "sandbox_links": settings.get("sandbox_links", {}),
        "live_links": settings.get("live_links", {})
    }


@paypal_router.post("/admin/links")
async def update_paypal_links(
    active_mode: str = Query(..., description="'sandbox' or 'live'"),
    sandbox_trial: Optional[str] = Query(None),
    sandbox_monthly: Optional[str] = Query(None),
    sandbox_yearly: Optional[str] = Query(None),
    live_trial: Optional[str] = Query(None),
    live_monthly: Optional[str] = Query(None),
    live_yearly: Optional[str] = Query(None),
    admin: dict = Depends(get_admin_user)
):
    """Update PayPal payment links (admin only)"""
    # Get existing settings
    existing = await db.admin_settings.find_one({"type": "paypal_links"})
    
    sandbox_links = existing.get("sandbox_links", {}) if existing else {}
    live_links = existing.get("live_links", {}) if existing else {}
    
    # Update only provided values
    if sandbox_trial is not None:
        sandbox_links["trial"] = sandbox_trial
    if sandbox_monthly is not None:
        sandbox_links["monthly"] = sandbox_monthly
    if sandbox_yearly is not None:
        sandbox_links["yearly"] = sandbox_yearly
    if live_trial is not None:
        live_links["trial"] = live_trial
    if live_monthly is not None:
        live_links["monthly"] = live_monthly
    if live_yearly is not None:
        live_links["yearly"] = live_yearly
    
    update_doc = {
        "type": "paypal_links",
        "active_mode": active_mode,
        "sandbox_links": sandbox_links,
        "live_links": live_links,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.admin_settings.update_one(
        {"type": "paypal_links"},
        {"$set": update_doc},
        upsert=True
    )
    
    return {"message": "PayPal links updated successfully", "active_mode": active_mode}

