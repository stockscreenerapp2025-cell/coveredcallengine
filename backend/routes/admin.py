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


def _mask_api_key(key: str) -> str:
    """Mask API key for security - show first 8 and last 4 chars"""
    if not key or len(key) <= 12:
        return "****"
    return key[:8] + "..." + key[-4:]


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
    """Get all integration settings (Stripe, Resend, etc.)"""
    stripe_settings = await db.admin_settings.find_one({"type": "stripe_settings"}, {"_id": 0})
    email_settings = await db.admin_settings.find_one({"type": "email_settings"}, {"_id": 0})
    
    env_resend_key = os.environ.get("RESEND_API_KEY")
    env_stripe_webhook = os.environ.get("STRIPE_WEBHOOK_SECRET")
    
    return {
        "stripe": {
            "webhook_secret_configured": bool(stripe_settings and stripe_settings.get("webhook_secret")) or bool(env_stripe_webhook),
            "secret_key_configured": bool(stripe_settings and stripe_settings.get("stripe_secret_key"))
        },
        "email": {
            "resend_api_key_configured": bool(email_settings and email_settings.get("resend_api_key")) or bool(env_resend_key),
            "sender_email": email_settings.get("sender_email", "") if email_settings else os.environ.get("SENDER_EMAIL", "")
        }
    }


@admin_router.post("/integration-settings")
async def update_integration_settings(
    stripe_webhook_secret: Optional[str] = Query(None),
    stripe_secret_key: Optional[str] = Query(None),
    resend_api_key: Optional[str] = Query(None),
    sender_email: Optional[str] = Query(None),
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
    
    # Log action
    await db.audit_logs.insert_one({
        "action": "update_integration_settings",
        "admin_id": admin["id"],
        "details": {
            "stripe_updated": stripe_webhook_secret is not None or stripe_secret_key is not None,
            "email_updated": resend_api_key is not None or sender_email is not None
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
