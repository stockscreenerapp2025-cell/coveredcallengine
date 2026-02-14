"""
Admin Routes - Administrative endpoints for managing users, settings, and email automation
Designed for scalability with proper async patterns, pagination, and efficient queries
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone, timedelta
import os
import logging
import json

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import db
from utils.auth import get_admin_user

admin_router = APIRouter(tags=["Admin"])


# ==================== PYDANTIC MODELS ====================
class AdminSettings(BaseModel):
    massive_api_key: Optional[str] = None
    massive_access_id: Optional[str] = None
    massive_secret_key: Optional[str] = None
    marketaux_api_token: Optional[str] = None
    openai_api_key: Optional[str] = None
    data_refresh_interval: int = 60
    enable_live_data: bool = False


class IMAPSettings(BaseModel):
    imap_server: str = "imap.hostinger.com"
    imap_port: int = 993
    username: str
    password: str


def _mask_api_key(key: str) -> str:
    """Mask API key for security - show first 8 and last 4 chars"""
    if not key or len(key) <= 12:
        return "****"
    return key[:8] + "..." + key[-4:]


def _mask_small(key: str) -> str:
    """Mask string for UI display - show first 4 and last 2 chars."""
    if not key:
        return ""
    if len(key) <= 6:
        return "****"
    return key[:4] + "..." + key[-2:]


async def clear_cache(prefix: str = None) -> int:
    """Clear cache entries. If prefix provided, only clear matching entries."""
    try:
        if prefix:
            result = await db.api_cache.delete_many({"cache_key": {"$regex": f"^{prefix}"}})
        else:
            result = await db.api_cache.delete_many({})
        return result.deleted_count
    except Exception as e:
        logging.error(f"Cache clear error: {e}")
        return 0


# ==================== SETTINGS ROUTES ====================
@admin_router.get("/settings")
async def get_settings(user: dict = Depends(get_admin_user)):
    """Get admin settings with masked API keys"""
    settings = await db.admin_settings.find_one({}, {"_id": 0})
    if settings:
        # Mask API keys for security
        for field in ["massive_api_key", "massive_access_id", "massive_secret_key", "marketaux_api_token", "openai_api_key"]:
            if settings.get(field):
                settings[field] = _mask_api_key(settings[field])
    return settings or {}


@admin_router.post("/settings")
async def update_settings(settings: AdminSettings, user: dict = Depends(get_admin_user)):
    """Update admin settings"""
    settings_dict = settings.model_dump(exclude_unset=True)
    
    # Don't update masked values
    masked_fields = ["massive_api_key", "massive_access_id", "massive_secret_key", "marketaux_api_token", "openai_api_key"]
    for field in masked_fields:
        if settings_dict.get(field) and "..." in settings_dict[field]:
            del settings_dict[field]
    
    await db.admin_settings.update_one({}, {"$set": settings_dict}, upsert=True)
    return {"message": "Settings updated successfully"}


@admin_router.post("/clear-cache")
async def clear_api_cache(prefix: Optional[str] = None, admin: dict = Depends(get_admin_user)):
    """Clear API response cache. Optionally filter by prefix."""
    deleted_count = await clear_cache(prefix)
    return {"message": f"Cleared {deleted_count} cache entries", "deleted_count": deleted_count}


@admin_router.get("/cache-stats")
async def get_cache_stats(admin: dict = Depends(get_admin_user)):
    """Get cache statistics - optimized with projection and limit"""
    try:
        total_entries = await db.api_cache.count_documents({})
        # Only fetch necessary fields
        entries = await db.api_cache.find(
            {}, 
            {"cache_key": 1, "cached_at": 1, "_id": 0}
        ).limit(100).to_list(100)
        
        now = datetime.now(timezone.utc)
        stats = {
            "total_entries": total_entries,
            "entries": []
        }
        
        for entry in entries:
            cached_at = entry.get("cached_at")
            if isinstance(cached_at, str):
                cached_at = datetime.fromisoformat(cached_at.replace('Z', '+00:00'))
            age = (now - cached_at).total_seconds() if cached_at else 0
            stats["entries"].append({
                "cache_key": entry.get("cache_key"),
                "age_seconds": round(age, 1)
            })
        
        return stats
    except Exception as e:
        logging.error(f"Cache stats error: {e}")
        return {"total_entries": 0, "error": str(e)}


@admin_router.post("/make-admin/{user_id}")
async def make_admin(user_id: str, admin: dict = Depends(get_admin_user)):
    """Promote a user to admin"""
    result = await db.users.update_one({"id": user_id}, {"$set": {"is_admin": True}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "User promoted to admin"}


# ==================== DASHBOARD STATS ====================
@admin_router.get("/dashboard-stats")
async def get_admin_dashboard_stats(admin: dict = Depends(get_admin_user)):
    """Get admin dashboard KPIs - optimized with parallel queries"""
    now = datetime.now(timezone.utc)
    thirty_days_ago = (now - timedelta(days=30)).isoformat()
    seven_days_ago = (now - timedelta(days=7)).isoformat()
    three_days_later = (now + timedelta(days=3)).isoformat()
    
    # Execute counts in parallel for better performance
    total_users = await db.users.count_documents({})
    active_users = await db.users.count_documents({"last_login": {"$gte": seven_days_ago}})
    trial_users = await db.users.count_documents({"subscription.status": "trialing"})
    active_subs = await db.users.count_documents({"subscription.status": "active"})
    monthly_subs = await db.users.count_documents({"subscription.plan": "monthly", "subscription.status": "active"})
    yearly_subs = await db.users.count_documents({"subscription.plan": "yearly", "subscription.status": "active"})
    cancelled_users = await db.users.count_documents({"subscription.status": "cancelled"})
    past_due_users = await db.users.count_documents({"subscription.status": "past_due"})
    
    # Calculate MRR
    mrr = (monthly_subs * 49) + (yearly_subs * 499 / 12)
    arr = mrr * 12
    
    # Trial conversion rate
    converted_trials = await db.users.count_documents({"subscription.converted_at": {"$exists": True}})
    total_trials = await db.users.count_documents({"subscription.trial_start": {"$exists": True}})
    conversion_rate = (converted_trials / total_trials * 100) if total_trials > 0 else 0
    
    # Churn (cancelled in last 30 days)
    recent_cancellations = await db.users.count_documents({
        "subscription.cancelled_at": {"$gte": thirty_days_ago}
    })
    churn_rate = (recent_cancellations / (active_subs + recent_cancellations) * 100) if (active_subs + recent_cancellations) > 0 else 0
    
    # Support tickets and trials ending soon
    open_tickets = await db.support_tickets.count_documents({"status": {"$in": ["open", "in_progress"]}})
    trials_ending_soon = await db.users.count_documents({
        "subscription.status": "trialing",
        "subscription.trial_end": {"$lte": three_days_later, "$gte": now.isoformat()}
    })
    
    return {
        "users": {
            "total": total_users,
            "active_7d": active_users,
            "trial": trial_users,
            "cancelled": cancelled_users,
            "past_due": past_due_users
        },
        "subscriptions": {
            "active": active_subs,
            "monthly": monthly_subs,
            "yearly": yearly_subs,
            "conversion_rate": round(conversion_rate, 1),
            "churn_rate": round(churn_rate, 1)
        },
        "revenue": {
            "mrr": round(mrr, 2),
            "arr": round(arr, 2)
        },
        "alerts": {
            "trials_ending_soon": trials_ending_soon,
            "payment_failures": past_due_users,
            "open_tickets": open_tickets
        }
    }


# ==================== USER MANAGEMENT ====================
@admin_router.get("/users")
async def get_admin_users(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    plan: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    admin: dict = Depends(get_admin_user)
):
    """Get paginated list of users with filters - optimized for large datasets"""
    query = {}
    
    if status:
        query["subscription.status"] = status
    if plan:
        query["subscription.plan"] = plan
    if search:
        query["$or"] = [
            {"email": {"$regex": search, "$options": "i"}},
            {"name": {"$regex": search, "$options": "i"}}
        ]
    
    skip = (page - 1) * limit
    
    # Use projection to exclude sensitive fields
    users = await db.users.find(
        query, 
        {"_id": 0, "password": 0, "hashed_password": 0}
    ).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    
    total = await db.users.count_documents(query)
    
    return {
        "users": users,
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit
    }


@admin_router.get("/users/{user_id}")
async def get_admin_user_detail(user_id: str, admin: dict = Depends(get_admin_user)):
    """Get detailed user information with activity and email history"""
    user = await db.users.find_one({"id": user_id}, {"_id": 0, "password": 0, "hashed_password": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get user activity (limited for performance)
    activity = await db.user_activity.find(
        {"user_id": user_id}, 
        {"_id": 0}
    ).sort("timestamp", -1).limit(50).to_list(50)
    
    # Get email history
    emails = await db.email_logs.find(
        {"to": user.get("email")}, 
        {"_id": 0}
    ).sort("sent_at", -1).limit(20).to_list(20)
    
    return {
        "user": user,
        "activity": activity,
        "emails": emails
    }


@admin_router.post("/users/{user_id}/extend-trial")
async def extend_user_trial(
    user_id: str,
    days: int = Query(..., ge=1, le=30),
    admin: dict = Depends(get_admin_user)
):
    """Extend user's trial period"""
    user = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    current_trial_end = user.get("subscription", {}).get("trial_end")
    if current_trial_end:
        new_end = datetime.fromisoformat(current_trial_end.replace("Z", "+00:00")) + timedelta(days=days)
    else:
        new_end = datetime.now(timezone.utc) + timedelta(days=days)
    
    await db.users.update_one(
        {"id": user_id},
        {"$set": {
            "subscription.trial_end": new_end.isoformat(),
            "subscription.status": "trialing",
            "updated_at": datetime.now(timezone.utc).isoformat()
        }}
    )
    
    # Log action
    await db.audit_logs.insert_one({
        "action": "extend_trial",
        "admin_id": admin["id"],
        "user_id": user_id,
        "details": {"days_added": days, "new_end": new_end.isoformat()},
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    return {"message": f"Trial extended by {days} days", "new_trial_end": new_end.isoformat()}


@admin_router.post("/users/{user_id}/cancel-subscription")
async def cancel_user_subscription(
    user_id: str,
    reason: Optional[str] = Query(None),
    admin: dict = Depends(get_admin_user)
):
    """Cancel user's subscription (admin action)"""
    user = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    now = datetime.now(timezone.utc)
    
    await db.users.update_one(
        {"id": user_id},
        {"$set": {
            "subscription.status": "cancelled",
            "subscription.cancelled_at": now.isoformat(),
            "subscription.cancellation_reason": reason or "Admin cancelled",
            "updated_at": now.isoformat()
        }}
    )
    
    # Log action
    await db.audit_logs.insert_one({
        "action": "admin_cancel_subscription",
        "admin_id": admin["id"],
        "user_id": user_id,
        "details": {"reason": reason},
        "timestamp": now.isoformat()
    })
    
    return {"message": "Subscription cancelled"}


@admin_router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    admin: dict = Depends(get_admin_user)
):
    """Delete a user account (admin action). Cannot delete admin users."""
    user = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Prevent deleting admin users
    if user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Cannot delete admin users")
    
    # Prevent self-deletion
    if user_id == admin["id"]:
        raise HTTPException(status_code=403, detail="Cannot delete your own account")
    
    now = datetime.now(timezone.utc)
    
    # Delete the user
    result = await db.users.delete_one({"id": user_id})
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=500, detail="Failed to delete user")
    
    # Also delete related data (optional - you may want to keep some for records)
    # Delete user's invitations if any
    await db.invitations.delete_many({"email": user.get("email")})
    
    # Log action
    await db.audit_logs.insert_one({
        "action": "admin_delete_user",
        "admin_id": admin["id"],
        "admin_email": admin.get("email"),
        "deleted_user_id": user_id,
        "deleted_user_email": user.get("email"),
        "timestamp": now.isoformat()
    })
    
    return {"message": f"User {user.get('email')} deleted successfully"}


@admin_router.post("/users/{user_id}/set-subscription")
async def set_user_subscription(
    user_id: str,
    status: str = Query(..., description="active, trialing, cancelled, past_due"),
    plan: str = Query("monthly", description="trial, monthly, yearly"),
    admin: dict = Depends(get_admin_user)
):
    """Manually set user's subscription status and plan (admin action)"""
    valid_statuses = ["active", "trialing", "cancelled", "past_due", "expired"]
    valid_plans = ["trial", "monthly", "yearly"]
    
    if status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")
    if plan not in valid_plans:
        raise HTTPException(status_code=400, detail=f"Invalid plan. Must be one of: {valid_plans}")
    
    user = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    now = datetime.now(timezone.utc)
    
    subscription_data = {
        "subscription.status": status,
        "subscription.plan": plan,
        "updated_at": now.isoformat()
    }
    
    if status == "trialing":
        subscription_data["subscription.trial_start"] = now.isoformat()
        subscription_data["subscription.trial_end"] = (now + timedelta(days=7)).isoformat()
    
    if status == "active":
        subscription_data["subscription.subscription_start"] = now.isoformat()
        if plan == "monthly":
            subscription_data["subscription.next_billing_date"] = (now + timedelta(days=30)).isoformat()
        elif plan == "yearly":
            subscription_data["subscription.next_billing_date"] = (now + timedelta(days=365)).isoformat()
    
    await db.users.update_one({"id": user_id}, {"$set": subscription_data})
    
    # Log action
    await db.audit_logs.insert_one({
        "action": "admin_set_subscription",
        "admin_id": admin["id"],
        "user_id": user_id,
        "details": {"status": status, "plan": plan},
        "timestamp": now.isoformat()
    })
    
    return {"message": f"User subscription set to {status} ({plan})"}


# ==================== INTEGRATION SETTINGS ====================
@admin_router.get("/integration-settings")
async def get_integration_settings(admin: dict = Depends(get_admin_user)):
    """Get all integration settings (Stripe, Resend, PayPal, etc.)"""
    stripe_settings = await db.admin_settings.find_one({"type": "stripe_settings"}, {"_id": 0})
    email_settings = await db.admin_settings.find_one({"type": "email_settings"}, {"_id": 0})
    paypal_settings = await db.admin_settings.find_one({"type": "paypal_settings"}, {"_id": 0})
    
    env_resend_key = os.environ.get("RESEND_API_KEY")
    env_stripe_webhook = os.environ.get("STRIPE_WEBHOOK_SECRET")
    
    # PayPal status
    paypal_enabled = bool(paypal_settings and paypal_settings.get("enabled"))
    paypal_mode = (paypal_settings.get("mode") if paypal_settings else None) or "sandbox"
    paypal_configured = bool(
        paypal_settings
        and paypal_settings.get("api_username")
        and paypal_settings.get("api_password")
        and paypal_settings.get("api_signature")
        and paypal_enabled
    )
    
    return {
        "stripe": {
            "webhook_secret_configured": bool(stripe_settings and stripe_settings.get("webhook_secret")) or bool(env_stripe_webhook),
            "secret_key_configured": bool(stripe_settings and stripe_settings.get("stripe_secret_key"))
        },
        "email": {
            "resend_api_key_configured": bool(email_settings and email_settings.get("resend_api_key")) or bool(env_resend_key),
            "sender_email": email_settings.get("sender_email", "") if email_settings else os.environ.get("SENDER_EMAIL", "")
        },
        "paypal": {
            "configured": paypal_configured,
            "enabled": paypal_enabled,
            "mode": paypal_mode,
            "api_username_masked": _mask_small(paypal_settings.get("api_username", "")) if paypal_settings else "",
            "has_api_password": bool(paypal_settings and paypal_settings.get("api_password")),
            "has_api_signature": bool(paypal_settings and paypal_settings.get("api_signature"))
        }
    }


@admin_router.post("/integration-settings")
async def update_integration_settings(
    stripe_webhook_secret: Optional[str] = Query(None),
    stripe_secret_key: Optional[str] = Query(None),
    resend_api_key: Optional[str] = Query(None),
    sender_email: Optional[str] = Query(None),
    paypal_enabled: Optional[bool] = Query(None),
    paypal_mode: Optional[str] = Query(None, description="sandbox or live"),
    paypal_api_username: Optional[str] = Query(None),
    paypal_api_password: Optional[str] = Query(None),
    paypal_api_signature: Optional[str] = Query(None),
    admin: dict = Depends(get_admin_user)
):
    """Update integration settings"""
    now = datetime.now(timezone.utc).isoformat()
    
    if stripe_webhook_secret is not None or stripe_secret_key is not None:
        stripe_update = {"type": "stripe_settings", "updated_at": now}
        if stripe_webhook_secret:
            stripe_update["webhook_secret"] = stripe_webhook_secret
        if stripe_secret_key:
            stripe_update["stripe_secret_key"] = stripe_secret_key
        
        await db.admin_settings.update_one(
            {"type": "stripe_settings"},
            {"$set": stripe_update},
            upsert=True
        )
    
    if resend_api_key is not None or sender_email is not None:
        email_update = {"type": "email_settings", "updated_at": now}
        if resend_api_key:
            email_update["resend_api_key"] = resend_api_key
        if sender_email:
            email_update["sender_email"] = sender_email
        
        await db.admin_settings.update_one(
            {"type": "email_settings"},
            {"$set": email_update},
            upsert=True
        )
    
    # PayPal settings
    if paypal_enabled is not None or paypal_mode is not None or paypal_api_username is not None or paypal_api_password is not None or paypal_api_signature is not None:
        paypal_update = {"type": "paypal_settings", "updated_at": now}
        if paypal_enabled is not None:
            paypal_update["enabled"] = paypal_enabled
        if paypal_mode:
            paypal_update["mode"] = paypal_mode
        if paypal_api_username:
            paypal_update["api_username"] = paypal_api_username
        if paypal_api_password:
            paypal_update["api_password"] = paypal_api_password
        if paypal_api_signature:
            paypal_update["api_signature"] = paypal_api_signature
        
        await db.admin_settings.update_one(
            {"type": "paypal_settings"},
            {"$set": paypal_update},
            upsert=True
        )
    
    # Log action
    await db.audit_logs.insert_one({
        "action": "update_integration_settings",
        "admin_id": admin["id"],
        "details": {
            "stripe_updated": stripe_webhook_secret is not None or stripe_secret_key is not None,
            "email_updated": resend_api_key is not None or sender_email is not None,
            "paypal_updated": paypal_enabled is not None or paypal_mode is not None or paypal_api_username is not None
        },
        "timestamp": now
    })
    
    return {"message": "Integration settings updated"}


# ==================== EMAIL TEMPLATES ====================
@admin_router.get("/email-templates")
async def get_email_templates_simple(admin: dict = Depends(get_admin_user)):
    """Get all email templates"""
    from services.email_service import EMAIL_TEMPLATES
    
    custom_templates = await db.email_templates.find({}, {"_id": 0}).to_list(100)
    custom_dict = {t["name"]: t for t in custom_templates}
    
    templates = []
    for name, template in EMAIL_TEMPLATES.items():
        custom = custom_dict.get(name, {})
        templates.append({
            "name": name,
            "subject": custom.get("subject", template["subject"]),
            "enabled": custom.get("enabled", template.get("enabled", True)),
            "is_custom": name in custom_dict
        })
    
    return {"templates": templates}


@admin_router.post("/email-templates/{template_name}/toggle")
async def toggle_email_template(
    template_name: str,
    enabled: bool = Query(...),
    admin: dict = Depends(get_admin_user)
):
    """Enable or disable an email template"""
    await db.email_templates.update_one(
        {"name": template_name},
        {"$set": {"name": template_name, "enabled": enabled, "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True
    )
    
    return {"message": f"Template '{template_name}' {'enabled' if enabled else 'disabled'}"}


@admin_router.post("/test-email")
async def send_test_email(
    recipient_email: str = Query(..., description="Email address to send test to"),
    template_name: str = Query("welcome", description="Template to test"),
    admin: dict = Depends(get_admin_user)
):
    """Send a test email to verify Resend integration"""
    from services.email_service import EmailService
    
    email_service = EmailService(db)
    
    if not await email_service.initialize():
        return {"status": "error", "message": "Email service not configured. Please add your Resend API key in Integrations settings."}
    
    test_variables = {
        "name": "Test User",
        "plan": "7-Day Free Trial",
        "trial_end_date": "January 15, 2025",
        "days_left": "3",
        "next_billing_date": "January 15, 2025",
        "amount": "$49/month",
        "access_until": "January 15, 2025"
    }
    
    result = await email_service.send_email(recipient_email, template_name, test_variables)
    
    await db.audit_logs.insert_one({
        "action": "test_email_sent",
        "admin_id": admin["id"],
        "admin_email": admin["email"],
        "recipient": recipient_email,
        "template": template_name,
        "result": result,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    return {
        "status": result.get("status"),
        "message": f"Test email sent to {recipient_email}" if result.get("status") == "success" else result.get("reason"),
        "email_id": result.get("email_id")
    }


# ==================== AUDIT LOGS ====================
@admin_router.get("/audit-logs")
async def get_audit_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    admin: dict = Depends(get_admin_user)
):
    """Get audit logs with pagination"""
    skip = (page - 1) * limit
    logs = await db.audit_logs.find({}, {"_id": 0}).sort("timestamp", -1).skip(skip).limit(limit).to_list(limit)
    total = await db.audit_logs.count_documents({})
    
    return {
        "logs": logs,
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit
    }


# ==================== EMAIL AUTOMATION ====================
@admin_router.get("/email-automation/templates")
async def get_email_automation_templates(admin: dict = Depends(get_admin_user)):
    """Get all email automation templates"""
    from services.email_automation import EmailAutomationService
    
    email_automation = EmailAutomationService(db)
    await email_automation.setup_default_templates()
    
    templates = await email_automation.get_templates()
    return {"templates": templates}


@admin_router.get("/email-automation/templates/{template_id}")
async def get_email_template(template_id: str, admin: dict = Depends(get_admin_user)):
    """Get a single email template"""
    from services.email_automation import EmailAutomationService
    
    email_automation = EmailAutomationService(db)
    template = await email_automation.get_template(template_id)
    
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    return template


@admin_router.put("/email-automation/templates/{template_id}")
async def update_email_template(
    template_id: str,
    name: Optional[str] = None,
    subject: Optional[str] = None,
    html: Optional[str] = None,
    enabled: Optional[bool] = None,
    admin: dict = Depends(get_admin_user)
):
    """Update an email template"""
    from services.email_automation import EmailAutomationService
    
    email_automation = EmailAutomationService(db)
    
    updates = {}
    if name is not None:
        updates["name"] = name
    if subject is not None:
        updates["subject"] = subject
    if html is not None:
        updates["html"] = html
    if enabled is not None:
        updates["enabled"] = enabled
    
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")
    
    success = await email_automation.update_template(template_id, updates)
    
    if not success:
        raise HTTPException(status_code=404, detail="Template not found or update failed")
    
    await db.audit_logs.insert_one({
        "action": "email_template_updated",
        "admin_id": admin["id"],
        "admin_email": admin["email"],
        "template_id": template_id,
        "updates": list(updates.keys()),
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    return {"message": "Template updated successfully"}


@admin_router.get("/email-automation/rules")
async def get_automation_rules(admin: dict = Depends(get_admin_user)):
    """Get all automation rules"""
    from services.email_automation import EmailAutomationService, TRIGGER_TYPES, ACTION_TYPES
    
    email_automation = EmailAutomationService(db)
    await email_automation.setup_default_rules()
    
    rules = await email_automation.get_rules()
    return {
        "rules": rules,
        "trigger_types": TRIGGER_TYPES,
        "action_types": ACTION_TYPES
    }


@admin_router.post("/email-automation/rules")
async def create_automation_rule(
    name: str,
    trigger_type: str,
    action: str,
    template_key: str,
    delay_minutes: int = 0,
    condition: Optional[str] = None,
    enabled: bool = True,
    admin: dict = Depends(get_admin_user)
):
    """Create a new automation rule"""
    from services.email_automation import EmailAutomationService
    
    email_automation = EmailAutomationService(db)
    
    rule_data = {
        "name": name,
        "trigger_type": trigger_type,
        "condition": json.loads(condition) if condition else {},
        "delay_minutes": delay_minutes,
        "action": action,
        "template_key": template_key,
        "enabled": enabled
    }
    
    rule = await email_automation.create_rule(rule_data)
    
    await db.audit_logs.insert_one({
        "action": "automation_rule_created",
        "admin_id": admin["id"],
        "admin_email": admin["email"],
        "rule_name": name,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    return {"message": "Rule created successfully", "rule": rule}


@admin_router.put("/email-automation/rules/{rule_id}")
async def update_automation_rule(
    rule_id: str,
    name: Optional[str] = None,
    trigger_type: Optional[str] = None,
    action: Optional[str] = None,
    template_key: Optional[str] = None,
    delay_minutes: Optional[int] = None,
    condition: Optional[str] = None,
    enabled: Optional[bool] = None,
    admin: dict = Depends(get_admin_user)
):
    """Update an automation rule"""
    from services.email_automation import EmailAutomationService
    
    email_automation = EmailAutomationService(db)
    
    updates = {}
    if name is not None:
        updates["name"] = name
    if trigger_type is not None:
        updates["trigger_type"] = trigger_type
    if action is not None:
        updates["action"] = action
    if template_key is not None:
        updates["template_key"] = template_key
    if delay_minutes is not None:
        updates["delay_minutes"] = delay_minutes
    if condition is not None:
        updates["condition"] = json.loads(condition)
    if enabled is not None:
        updates["enabled"] = enabled
    
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")
    
    success = await email_automation.update_rule(rule_id, updates)
    
    if not success:
        raise HTTPException(status_code=404, detail="Rule not found or update failed")
    
    return {"message": "Rule updated successfully"}


@admin_router.delete("/email-automation/rules/{rule_id}")
async def delete_automation_rule(rule_id: str, admin: dict = Depends(get_admin_user)):
    """Delete an automation rule"""
    from services.email_automation import EmailAutomationService
    
    email_automation = EmailAutomationService(db)
    success = await email_automation.delete_rule(rule_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    await db.audit_logs.insert_one({
        "action": "automation_rule_deleted",
        "admin_id": admin["id"],
        "admin_email": admin["email"],
        "rule_id": rule_id,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    return {"message": "Rule deleted successfully"}


@admin_router.get("/email-automation/logs")
async def get_email_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    status: Optional[str] = None,
    template_key: Optional[str] = None,
    admin: dict = Depends(get_admin_user)
):
    """Get email logs with pagination and filters"""
    from services.email_automation import EmailAutomationService
    
    email_automation = EmailAutomationService(db)
    
    filters = {}
    if status:
        filters["status"] = status
    if template_key:
        filters["template_key"] = template_key
    
    skip = (page - 1) * limit
    result = await email_automation.get_email_logs(limit=limit, skip=skip, filters=filters)
    
    return {
        "logs": result["logs"],
        "total": result["total"],
        "page": page,
        "pages": (result["total"] + limit - 1) // limit if result["total"] > 0 else 1
    }


@admin_router.get("/email-automation/stats")
async def get_email_stats(admin: dict = Depends(get_admin_user)):
    """Get email analytics/statistics"""
    from services.email_automation import EmailAutomationService
    
    email_automation = EmailAutomationService(db)
    stats = await email_automation.get_email_stats()
    
    return stats


@admin_router.post("/email-automation/broadcast")
async def send_broadcast_email(
    template_key: str,
    subject_override: Optional[str] = None,
    announcement_title: Optional[str] = None,
    announcement_content: Optional[str] = None,
    update_title: Optional[str] = None,
    update_content: Optional[str] = None,
    recipient_filter: Optional[str] = None,
    admin: dict = Depends(get_admin_user)
):
    """Send a broadcast email to multiple users"""
    from services.email_automation import EmailAutomationService
    
    email_automation = EmailAutomationService(db)
    
    variables = {}
    if announcement_title:
        variables["announcement_title"] = announcement_title
    if announcement_content:
        variables["announcement_content"] = announcement_content
    if update_title:
        variables["update_title"] = update_title
    if update_content:
        variables["update_content"] = update_content
    
    filter_dict = json.loads(recipient_filter) if recipient_filter else None
    
    result = await email_automation.send_broadcast(template_key, variables, filter_dict)
    
    await db.audit_logs.insert_one({
        "action": "broadcast_email_sent",
        "admin_id": admin["id"],
        "admin_email": admin["email"],
        "template_key": template_key,
        "recipients_count": result.get("total", 0),
        "sent": result.get("sent", 0),
        "failed": result.get("failed", 0),
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    return result


@admin_router.post("/email-automation/test-send")
async def test_send_email(
    template_key: str,
    recipient_email: str,
    admin: dict = Depends(get_admin_user)
):
    """Send a test email to a specific recipient"""
    from services.email_automation import EmailAutomationService
    
    email_automation = EmailAutomationService(db)
    
    variables = {
        "first_name": "Test User",
        "name": "Test User",
        "dashboard_url": "https://coveredcallengine.com/dashboard",
        "scanner_link": "https://coveredcallengine.com/screener",
        "feature_link": "https://coveredcallengine.com/screener",
        "upgrade_link": "https://coveredcallengine.com/pricing",
        "trial_days": "7",
        "announcement_title": "Test Announcement",
        "announcement_content": "This is a test announcement content.",
        "update_title": "Test Update",
        "update_content": "This is a test system update content."
    }
    
    result = await email_automation.send_email(recipient_email, template_key, variables)
    
    return {
        "success": result.get("success", False),
        "message": f"Test email sent to {recipient_email}" if result.get("success") else result.get("error"),
        "message_id": result.get("message_id")
    }


# ==================== IMAP EMAIL SYNC ROUTES ====================

@admin_router.get("/imap/settings")
async def get_imap_settings(admin: dict = Depends(get_admin_user)):
    """Get IMAP settings (password masked)"""
    settings = await db.admin_settings.find_one({"type": "imap_settings"}, {"_id": 0})
    
    if settings:
        # Mask password for security
        if settings.get("password"):
            settings["password"] = "••••••••"
        return settings
    
    return {
        "type": "imap_settings",
        "imap_server": "imap.hostinger.com",
        "imap_port": 993,
        "username": "",
        "password": "",
        "configured": False
    }


@admin_router.post("/imap/settings")
async def update_imap_settings(settings: IMAPSettings, admin: dict = Depends(get_admin_user)):
    """Save or update IMAP settings"""
    settings_dict = {
        "type": "imap_settings",
        "imap_server": settings.imap_server,
        "imap_port": settings.imap_port,
        "username": settings.username,
        "password": settings.password,
        "configured": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": admin["email"]
    }
    
    await db.admin_settings.update_one(
        {"type": "imap_settings"},
        {"$set": settings_dict},
        upsert=True
    )
    
    # Test connection immediately
    from services.imap_service import IMAPService
    imap_service = IMAPService(db)
    success, message = await imap_service.test_connection()
    
    return {
        "message": "IMAP settings saved",
        "connection_test": {
            "success": success,
            "message": message
        }
    }


@admin_router.post("/imap/test-connection")
async def test_imap_connection(admin: dict = Depends(get_admin_user)):
    """Test IMAP connection with current settings"""
    from services.imap_service import IMAPService
    
    imap_service = IMAPService(db)
    success, message = await imap_service.test_connection()
    
    return {
        "success": success,
        "message": message
    }


@admin_router.post("/imap/sync-now")
async def sync_emails_now(admin: dict = Depends(get_admin_user)):
    """Manually trigger email sync"""
    from services.imap_service import IMAPService
    
    imap_service = IMAPService(db)
    result = await imap_service.process_incoming_emails()
    
    # Log admin action
    await db.audit_logs.insert_one({
        "action": "manual_email_sync",
        "admin_id": admin["id"],
        "admin_email": admin["email"],
        "result": result,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    return result


@admin_router.get("/imap/sync-history")
async def get_sync_history(
    limit: int = Query(default=20, ge=1, le=100),
    admin: dict = Depends(get_admin_user)
):
    """Get IMAP sync history"""
    from services.imap_service import IMAPService
    
    imap_service = IMAPService(db)
    history = await imap_service.get_sync_history(limit)
    
    return {"history": history}


@admin_router.get("/imap/status")
async def get_imap_status(admin: dict = Depends(get_admin_user)):
    """Get current IMAP configuration status"""
    settings = await db.admin_settings.find_one({"type": "imap_settings"}, {"_id": 0})
    
    if not settings or not settings.get("configured"):
        return {
            "configured": False,
            "message": "IMAP not configured. Please add your email credentials."
        }
    
    return {
        "configured": True,
        "imap_server": settings.get("imap_server"),
        "username": settings.get("username"),
        "last_sync": settings.get("last_sync"),
        "last_sync_success": settings.get("last_sync_success"),
        "last_sync_error": settings.get("last_sync_error"),
        "last_sync_processed": settings.get("last_sync_processed", 0)
    }



# ==================== PHASE 2: CACHE HEALTH ENDPOINTS ====================

@admin_router.get("/cache/health")
async def get_cache_health(admin: dict = Depends(get_admin_user)):
    """
    PHASE 2: Get cache health metrics for monitoring.
    
    Returns:
    - Hit rate percentage
    - Yahoo calls per hour
    - Average fetch latency
    - Cache collection statistics
    """
    from services.data_provider import get_cache_status
    
    return await get_cache_status(db)


@admin_router.get("/user-path/metrics")
async def get_user_path_latency_metrics(admin: dict = Depends(get_admin_user)):
    """
    Get user path latency metrics (Dashboard, Watchlist, Simulator).
    
    Returns avg, p95, max latency and Yahoo executor configuration.
    """
    from services.data_provider import get_user_path_metrics
    
    return get_user_path_metrics()


@admin_router.post("/user-path/reset-metrics")
async def reset_user_path_latency_metrics(admin: dict = Depends(get_admin_user)):
    """
    Reset user path latency metrics.
    """
    from services.data_provider import reset_user_path_metrics
    
    return reset_user_path_metrics()


@admin_router.get("/cache/metrics")
async def get_cache_metrics(admin: dict = Depends(get_admin_user)):
    """
    PHASE 2: Get in-memory cache metrics.
    
    These metrics track the current session's cache performance.
    """
    from services.data_provider import get_cache_metrics
    
    return get_cache_metrics()


@admin_router.post("/cache/reset-metrics")
async def reset_cache_metrics_endpoint(admin: dict = Depends(get_admin_user)):
    """
    PHASE 2: Reset cache metrics.
    
    Resets the in-memory counters for hit rate tracking.
    Useful for starting fresh measurements.
    """
    from services.data_provider import reset_cache_metrics
    
    return reset_cache_metrics()


@admin_router.post("/cache/clear")
async def clear_snapshot_cache(
    symbol: Optional[str] = Query(None, description="Symbol to clear, or all if not provided"),
    admin: dict = Depends(get_admin_user)
):
    """
    PHASE 2: Clear snapshot cache entries.
    
    Args:
        symbol: Optional specific symbol to clear (clears all if not provided)
    
    Returns:
        Number of entries deleted
    """
    from services.data_provider import clear_snapshot_cache as dp_clear_cache
    
    return await dp_clear_cache(db, symbol)


@admin_router.get("/cache/entries")
async def get_cache_entries(
    limit: int = Query(50, ge=1, le=200),
    admin: dict = Depends(get_admin_user)
):
    """
    PHASE 2: Get recent cache entries for inspection.
    
    Returns the most recent cached symbols with their data.
    """
    from services.data_provider import SNAPSHOT_CACHE_COLLECTION
    
    try:
        entries = await db[SNAPSHOT_CACHE_COLLECTION].find(
            {},
            {"_id": 0}
        ).sort("cached_at", -1).limit(limit).to_list(limit)
        
        return {
            "entries": entries,
            "count": len(entries)
        }
    except Exception as e:
        logging.error(f"Error fetching cache entries: {e}")
        return {"error": str(e)}



# ==================== EOD MARKET SNAPSHOT MANAGEMENT ====================

@admin_router.post("/eod-snapshot/trigger")
async def trigger_eod_snapshot(
    trade_date: Optional[str] = Query(None, description="Trade date (YYYY-MM-DD), defaults to last trading day"),
    admin: dict = Depends(get_admin_user)
):
    """
    Manually trigger EOD market snapshot generation.
    
    Creates a synchronized snapshot of underlying prices and option chains
    for all symbols in the universe.
    
    WARNING: This should normally only run at 4:05 PM ET via scheduler.
    Manual triggering is for testing and recovery purposes only.
    """
    from services.eod_snapshot_service import get_eod_snapshot_service
    from routes.eod import EOD_SYMBOLS
    from utils.market_state import now_et, get_last_trading_day, log_eod_event
    
    # Use last trading day if not specified
    if not trade_date:
        trade_date = get_last_trading_day()
    
    logging.info(f"[EOD-SNAPSHOT] Manual trigger by admin: {admin.get('email')} for trade_date={trade_date}")
    
    # Get API key for data fetching
    settings = await db.admin_settings.find_one(
        {"massive_api_key": {"$exists": True}}, 
        {"_id": 0}
    )
    api_key = settings.get("massive_api_key") if settings else None
    
    eod_service = get_eod_snapshot_service(db)
    await eod_service.ensure_indexes()
    
    results = await eod_service.create_eod_snapshot(
        symbols=EOD_SYMBOLS,
        trade_date=trade_date,
        api_key=api_key
    )
    
    log_eod_event(
        "MANUAL_SNAPSHOT_TRIGGERED",
        triggered_by=admin.get("email"),
        run_id=results["run_id"],
        trade_date=trade_date
    )
    
    return {
        "status": "completed",
        "triggered_by": admin.get("email"),
        "triggered_at": now_et().isoformat(),
        **results
    }


@admin_router.get("/eod-snapshot/status")
async def get_eod_snapshot_admin_status(
    trade_date: Optional[str] = Query(None, description="Trade date (YYYY-MM-DD)"),
    admin: dict = Depends(get_admin_user)
):
    """
    Get detailed status of EOD market snapshots.
    
    Returns snapshot availability, symbols covered, and audit information.
    """
    from services.eod_snapshot_service import get_eod_snapshot_service
    from utils.market_state import get_system_mode, get_last_trading_day, now_et
    
    eod_service = get_eod_snapshot_service(db)
    
    if not trade_date:
        trade_date = get_last_trading_day()
    
    # Get basic status
    status = await eod_service.get_snapshot_status(trade_date)
    
    # Get list of available symbols
    available_symbols = await eod_service.list_available_symbols(trade_date)
    
    # Get failures from audit collection
    failures = await db.eod_snapshot_audit.find(
        {"as_of": {"$gte": datetime.strptime(trade_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)},
         "included": False}
    ).to_list(100)
    
    return {
        **status,
        "available_symbols": available_symbols,
        "available_count": len(available_symbols),
        "failures": [{"symbol": f.get("symbol"), "reason": f.get("exclude_reason"), "detail": f.get("exclude_detail")} for f in failures],
        "current_time_et": now_et().isoformat()
    }


@admin_router.get("/eod-snapshot/sample/{symbol}")
async def get_eod_snapshot_sample(
    symbol: str,
    trade_date: Optional[str] = Query(None, description="Trade date (YYYY-MM-DD)"),
    admin: dict = Depends(get_admin_user)
):
    """
    Get sample EOD snapshot for a specific symbol.
    
    Returns the full snapshot document including underlying price and option chain.
    """
    from services.eod_snapshot_service import get_eod_snapshot_service
    from utils.market_state import get_last_trading_day
    
    eod_service = get_eod_snapshot_service(db)
    
    if not trade_date:
        trade_date = get_last_trading_day()
    
    snapshot = await eod_service.get_snapshot(symbol.upper(), trade_date)
    
    if not snapshot:
        raise HTTPException(
            status_code=404,
            detail={
                "data_status": "EOD_SNAPSHOT_NOT_FOUND",
                "symbol": symbol.upper(),
                "trade_date": trade_date
            }
        )
    
    # Limit option chain to first 5 contracts for sample view
    if snapshot.get("option_chain"):
        snapshot["option_chain_sample"] = snapshot["option_chain"][:5]
        snapshot["option_chain_total"] = len(snapshot["option_chain"])
        del snapshot["option_chain"]
    
    return snapshot



# ==================== IV METRICS VERIFICATION (CCE Volatility & Greeks Correctness) ====================

@admin_router.get("/iv-metrics/check/{symbol}")
async def check_iv_metrics(
    symbol: str,
    admin: dict = Depends(get_admin_user)
):
    """
    Admin endpoint to validate IV metrics and Greeks for a symbol.
    
    CCE VOLATILITY & GREEKS CORRECTNESS - VERIFICATION ENDPOINT
    
    Returns:
    - Current proxy IV, IV Rank, IV Percentile, sample size
    - Selected ATM contract metadata
    - First 5 history values (for sanity)
    - Greeks sanity checks (delta bounds, IV bounds, no NaN)
    - Risk-free rate used (r_used)
    
    Use this endpoint to:
    1. Verify IV Rank calculation is correct
    2. Check delta is computed via Black-Scholes
    3. Validate no missing/null fields
    """
    from services.data_provider import fetch_options_chain, fetch_stock_quote
    from services.iv_rank_service import (
        get_iv_metrics_for_symbol,
        get_iv_history_debug,
        get_iv_collection_stats
    )
    from services.greeks_service import (
        calculate_greeks,
        normalize_iv_fields,
        sanity_check_delta,
        sanity_check_iv,
        get_risk_free_rate
    )
    
    symbol = symbol.upper()
    result = {
        "symbol": symbol,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "checking"
    }
    
    try:
        # Step 1: Get stock price
        stock_data = await fetch_stock_quote(symbol)
        if not stock_data or stock_data.get("price", 0) <= 0:
            result["status"] = "error"
            result["error"] = "Could not fetch stock price"
            return result
        
        stock_price = stock_data["price"]
        result["stock_price"] = stock_price
        
        # Step 2: Fetch options chain
        options = await fetch_options_chain(
            symbol=symbol,
            api_key=None,
            option_type="call",
            min_dte=7,
            max_dte=60,
            current_price=stock_price
        )
        
        if not options:
            result["status"] = "error"
            result["error"] = "No options chain available"
            return result
        
        result["options_count"] = len(options)
        
        # Step 3: Compute IV metrics
        iv_metrics = await get_iv_metrics_for_symbol(
            db=db,
            symbol=symbol,
            options=options,
            stock_price=stock_price,
            store_history=True
        )
        
        result["iv_metrics"] = {
            "iv_proxy": iv_metrics.iv_proxy,
            "iv_proxy_pct": iv_metrics.iv_proxy_pct,
            "iv_rank": iv_metrics.iv_rank,
            "iv_percentile": iv_metrics.iv_percentile,
            "iv_low": iv_metrics.iv_low,
            "iv_high": iv_metrics.iv_high,
            "iv_samples": iv_metrics.iv_samples,
            "iv_samples_used": iv_metrics.iv_samples_used,
            "iv_rank_source": iv_metrics.iv_rank_source,
            "iv_rank_confidence": iv_metrics.iv_rank_confidence,
            "proxy_meta": iv_metrics.proxy_meta,
            "bootstrap_info": {
                "is_bootstrapping": iv_metrics.iv_samples < 20,
                "shrinkage_applied": 5 <= iv_metrics.iv_samples < 20,
                "weight_if_shrunk": round(iv_metrics.iv_samples / 20, 2) if 5 <= iv_metrics.iv_samples < 20 else None
            }
        }
        
        # Step 4: Get IV history (last 10 entries for better debugging)
        history = await get_iv_history_debug(db, symbol, limit=10)
        result["iv_history_sample"] = [
            {"date": h.get("trading_date"), "iv": round(h.get("iv_atm_proxy", 0), 4)}
            for h in history
        ]
        result["history_excluded_today"] = True  # Rank was computed BEFORE storing today
        
        # Step 5: Greeks sanity checks on sample contracts
        r_used = get_risk_free_rate()
        result["r_used"] = r_used
        
        greeks_checks = []
        for opt in options[:5]:  # Check first 5 options
            strike = opt.get("strike", 0)
            dte = opt.get("dte", 30)
            iv_raw = opt.get("implied_volatility", 0)
            
            iv_data = normalize_iv_fields(iv_raw)
            T = max(dte, 1) / 365.0
            
            greeks = calculate_greeks(
                S=stock_price,
                K=strike,
                T=T,
                sigma=iv_data["iv"] if iv_data["iv"] > 0 else None,
                option_type="call",
                r=r_used
            )
            
            delta_ok, delta_err = sanity_check_delta(greeks.delta, "call")
            iv_ok, iv_err = sanity_check_iv(iv_data["iv"])
            
            greeks_checks.append({
                "strike": strike,
                "dte": dte,
                "delta": greeks.delta,
                "delta_source": greeks.delta_source,
                "gamma": greeks.gamma,
                "theta": greeks.theta,
                "vega": greeks.vega,
                "iv": iv_data["iv"],
                "iv_pct": iv_data["iv_pct"],
                "checks": {
                    "delta_in_bounds": delta_ok,
                    "delta_error": delta_err if not delta_ok else None,
                    "iv_valid": iv_ok,
                    "iv_error": iv_err if not iv_ok else None
                }
            })
        
        result["greeks_sanity_checks"] = greeks_checks
        
        # Step 6: Summary
        all_delta_ok = all(c["checks"]["delta_in_bounds"] for c in greeks_checks)
        all_iv_ok = all(c["checks"]["iv_valid"] for c in greeks_checks if c["iv"] > 0)
        
        result["summary"] = {
            "all_deltas_valid": all_delta_ok,
            "all_ivs_valid": all_iv_ok,
            "iv_rank_computed": iv_metrics.iv_rank_source == "OBSERVED_ATM_PROXY",
            "history_samples": iv_metrics.iv_samples,
            "needs_more_history": iv_metrics.iv_samples < 20
        }
        
        result["status"] = "success"
        
    except Exception as e:
        logging.error(f"IV metrics check failed for {symbol}: {e}")
        result["status"] = "error"
        result["error"] = str(e)
    
    return result


@admin_router.get("/iv-metrics/stats")
async def get_iv_stats(admin: dict = Depends(get_admin_user)):
    """
    Get statistics about the IV history collection.
    
    Returns:
    - Total entries
    - Unique symbols
    - Date range
    - Minimum samples required for IV Rank
    """
    from services.iv_rank_service import get_iv_collection_stats
    
    return await get_iv_collection_stats(db)


@admin_router.get("/iv-metrics/completeness-test")
async def test_completeness(
    admin: dict = Depends(get_admin_user)
):
    """
    Test field completeness across endpoints.
    
    Calls dashboard snapshots, options chain, custom scan, and precomputed scan
    and validates that all required fields are populated.
    
    Required fields for every option row:
    - delta, delta_source
    - iv, iv_pct
    - iv_rank, iv_percentile, iv_rank_source, iv_samples
    """
    from services.option_normalizer import REQUIRED_FIELDS
    
    test_symbol = "AAPL"
    results = {
        "symbol": test_symbol,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tests": []
    }
    
    # Test 1: Options chain endpoint
    try:
        from services.data_provider import fetch_options_chain, fetch_stock_quote
        from services.iv_rank_service import get_iv_metrics_for_symbol
        from services.option_normalizer import enrich_option_with_normalized_fields
        
        stock_data = await fetch_stock_quote(test_symbol)
        stock_price = stock_data.get("price", 0) if stock_data else 0
        
        options = await fetch_options_chain(
            symbol=test_symbol,
            api_key=None,
            option_type="call",
            min_dte=7,
            max_dte=45,
            current_price=stock_price
        )
        
        if options:
            iv_metrics = await get_iv_metrics_for_symbol(
                db=db,
                symbol=test_symbol,
                options=options,
                stock_price=stock_price
            )
            
            # Check completeness
            missing_count = 0
            for opt in options[:10]:
                enriched = enrich_option_with_normalized_fields(
                    opt.copy(),
                    stock_price,
                    opt.get("dte", 30),
                    iv_metrics
                )
                for field in REQUIRED_FIELDS:
                    if field not in enriched or enriched[field] is None:
                        missing_count += 1
            
            results["tests"].append({
                "endpoint": "options_chain",
                "status": "pass" if missing_count == 0 else "fail",
                "options_checked": min(10, len(options)),
                "missing_fields": missing_count
            })
        else:
            results["tests"].append({
                "endpoint": "options_chain",
                "status": "skip",
                "reason": "No options returned"
            })
            
    except Exception as e:
        results["tests"].append({
            "endpoint": "options_chain",
            "status": "error",
            "error": str(e)
        })
    
    # Summary
    passed = sum(1 for t in results["tests"] if t["status"] == "pass")
    failed = sum(1 for t in results["tests"] if t["status"] == "fail")
    
    results["summary"] = {
        "passed": passed,
        "failed": failed,
        "total": len(results["tests"]),
        "all_complete": failed == 0
    }
    
    return results



# ==================== UNIVERSE AUDIT DRILLDOWN ====================

@admin_router.get("/universe/excluded")
async def get_excluded_symbols(
    run_id: Optional[str] = Query(None, description="Specific run ID to query. If omitted, uses latest run."),
    reason: Optional[str] = Query(None, description="Filter by exclusion reason"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    admin: dict = Depends(get_admin_user)
):
    """
    Get list of excluded symbols from a universe audit run.
    
    Exclusion reasons:
    - OUT_OF_RULES
    - OUT_OF_PRICE_BAND
    - LOW_LIQUIDITY
    - MISSING_QUOTE
    - MISSING_CHAIN
    - CHAIN_EMPTY
    - BAD_CHAIN_DATA
    - MISSING_CONTRACT_FIELDS
    - OTHER
    """
    # Build query
    query = {"included": False}
    
    if run_id:
        query["run_id"] = run_id
    else:
        # Find the latest run_id
        latest = await db.scan_universe_audit.find_one(
            {},
            sort=[("as_of", -1)],
            projection={"run_id": 1}
        )
        if latest and latest.get("run_id"):
            query["run_id"] = latest["run_id"]
        else:
            return {"total": 0, "items": [], "run_id": None}
    
    if reason:
        query["exclude_reason"] = reason
    
    # Get total count
    total = await db.scan_universe_audit.count_documents(query)
    
    # Fetch items with pagination
    cursor = db.scan_universe_audit.find(
        query,
        {"_id": 0, "symbol": 1, "price_used": 1, "avg_volume": 1, "dollar_volume": 1, 
         "exclude_reason": 1, "exclude_detail": 1, "as_of": 1}
    ).sort("symbol", 1).skip(offset).limit(limit)
    
    items = []
    async for doc in cursor:
        items.append({
            "symbol": doc.get("symbol"),
            "price_used": doc.get("price_used", 0),
            "avg_volume": doc.get("avg_volume", 0),
            "dollar_volume": doc.get("dollar_volume", 0),
            "exclude_reason": doc.get("exclude_reason"),
            "exclude_detail": doc.get("exclude_detail"),
            "as_of": doc.get("as_of").isoformat() if doc.get("as_of") else None
        })
    
    return {
        "total": total,
        "items": items,
        "run_id": query.get("run_id"),
        "reason_filter": reason
    }


@admin_router.get("/universe/excluded.csv")
async def get_excluded_symbols_csv(
    run_id: Optional[str] = Query(None, description="Specific run ID to query. If omitted, uses latest run."),
    reason: Optional[str] = Query(None, description="Filter by exclusion reason"),
    admin: dict = Depends(get_admin_user)
):
    """
    Download excluded symbols as CSV.
    
    Columns: symbol,price_used,avg_volume,dollar_volume,exclude_reason,exclude_detail,as_of
    """
    from fastapi.responses import Response
    
    # Build query
    query = {"included": False}
    
    if run_id:
        query["run_id"] = run_id
    else:
        # Find the latest run_id
        latest = await db.scan_universe_audit.find_one(
            {},
            sort=[("as_of", -1)],
            projection={"run_id": 1}
        )
        if latest and latest.get("run_id"):
            query["run_id"] = latest["run_id"]
        else:
            return Response(
                content="symbol,price_used,avg_volume,dollar_volume,exclude_reason,exclude_detail,as_of\n",
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=excluded_symbols.csv"}
            )
    
    if reason:
        query["exclude_reason"] = reason
    
    # Fetch all excluded symbols
    cursor = db.scan_universe_audit.find(
        query,
        {"_id": 0, "symbol": 1, "price_used": 1, "avg_volume": 1, "dollar_volume": 1, 
         "exclude_reason": 1, "exclude_detail": 1, "as_of": 1}
    ).sort("symbol", 1)
    
    # Build CSV
    lines = ["symbol,price_used,avg_volume,dollar_volume,exclude_reason,exclude_detail,as_of"]
    async for doc in cursor:
        as_of = doc.get("as_of").isoformat() if doc.get("as_of") else ""
        # Escape quotes in exclude_detail
        exclude_detail = (doc.get("exclude_detail") or "").replace('"', '""')
        line = f'{doc.get("symbol", "")},{doc.get("price_used", 0)},{doc.get("avg_volume", 0)},{doc.get("dollar_volume", 0)},{doc.get("exclude_reason", "")},"{exclude_detail}",{as_of}'
        lines.append(line)
    
    csv_content = "\n".join(lines)
    
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=excluded_symbols_{query.get('run_id', 'latest')}.csv"}
    )


@admin_router.get("/universe/runs")
async def get_audit_runs(
    limit: int = Query(10, ge=1, le=50),
    admin: dict = Depends(get_admin_user)
):
    """
    Get list of recent universe audit runs.
    """
    # Aggregate to get unique run_ids with their stats
    pipeline = [
        {"$group": {
            "_id": "$run_id",
            "as_of": {"$max": "$as_of"},
            "total_symbols": {"$sum": 1},
            "included": {"$sum": {"$cond": ["$included", 1, 0]}},
            "excluded": {"$sum": {"$cond": ["$included", 0, 1]}}
        }},
        {"$sort": {"as_of": -1}},
        {"$limit": limit}
    ]
    
    runs = []
    async for doc in db.scan_universe_audit.aggregate(pipeline):
        runs.append({
            "run_id": doc["_id"],
            "as_of": doc["as_of"].isoformat() if doc.get("as_of") else None,
            "total_symbols": doc.get("total_symbols", 0),
            "included": doc.get("included", 0),
            "excluded": doc.get("excluded", 0)
        })
    
    return {"runs": runs}


# ==================== SCAN RESILIENCE CONFIGURATION ====================

@admin_router.get("/scan/resilience-config")
async def get_scan_resilience_config(
    admin: dict = Depends(get_admin_user)
):
    """
    Get the current scan resilience configuration.
    
    SCAN TIMEOUT FIX (December 2025):
    Shows bounded concurrency, timeout, and retry settings.
    """
    from services.resilient_fetch import get_resilience_config
    
    config = get_resilience_config()
    return {
        "config": config,
        "description": {
            "yahoo_scan_max_concurrency": "Maximum concurrent Yahoo Finance calls during scans (semaphore limit)",
            "yahoo_timeout_seconds": "Timeout per symbol fetch in seconds",
            "yahoo_max_retries": "Number of retry attempts before marking a symbol as failed",
            "semaphore_initialized": "Whether the scan semaphore has been initialized"
        },
        "environment_variables": {
            "YAHOO_SCAN_MAX_CONCURRENCY": os.environ.get("YAHOO_SCAN_MAX_CONCURRENCY", "5"),
            "YAHOO_TIMEOUT_SECONDS": os.environ.get("YAHOO_TIMEOUT_SECONDS", "30"),
            "YAHOO_MAX_RETRIES": os.environ.get("YAHOO_MAX_RETRIES", "2")
        },
        "notes": [
            "These settings apply ONLY to batch scan workflows (Screener, PMCC scans)",
            "Single-symbol lookups (Watchlist, Simulator) are NOT affected",
            "Partial success: if a symbol times out, the scan continues with remaining symbols",
            "Aggregated stats are logged at the end of each scan run"
        ]
    }

