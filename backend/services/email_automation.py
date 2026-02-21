"""
Email Automation Service for Covered Call Engine
Handles email templates, automation rules, campaigns, and logging
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List
from uuid import uuid4
import resend

logger = logging.getLogger(__name__)

# Default Email Templates - Auto-generated for FREE trial
DEFAULT_TEMPLATES = {
    "welcome_free_trial": {
        "name": "Welcome – Free Trial",
        "purpose": "Onboarding",
        "trigger": "immediate",
        "delay_days": 0,
        "subject": "🚀 Welcome to Your FREE Covered Call Trial",
        "enabled": True,
        "html": """
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #09090b; color: #ffffff;">
    <div style="text-align: center; padding: 20px 0; border-bottom: 1px solid #27272a;">
        <h1 style="color: #10b981; margin: 0;">Covered Call Engine</h1>
    </div>
    <div style="padding: 30px 20px;">
        <h2 style="color: #ffffff; margin-bottom: 20px;">Hi {{first_name}},</h2>
        <p style="color: #a1a1aa; line-height: 1.6;">Welcome aboard! 👋</p>
        <p style="color: #a1a1aa; line-height: 1.6;">
            You now have full FREE access to our Covered Call Engine – built to help you:
        </p>
        <ul style="color: #a1a1aa; line-height: 1.8;">
            <li>✔ Find high-premium covered call opportunities</li>
            <li>✔ Reduce downside risk</li>
            <li>✔ Improve consistency in options income</li>
        </ul>
        <p style="color: #a1a1aa; line-height: 1.6; margin-top: 20px;">
            <strong style="color: #ffffff;">🔹 What you can do right now:</strong>
        </p>
        <ol style="color: #a1a1aa; line-height: 1.8;">
            <li>Open the Covered Call Scanner</li>
            <li>Filter by IV, DTE & Delta</li>
            <li>Save your favourite setups</li>
        </ol>
        <div style="text-align: center; margin: 30px 0;">
            <a href="{{dashboard_url}}" style="display: inline-block; padding: 15px 30px; background-color: #10b981; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: bold;">
                👉 Get Started Now
            </a>
        </div>
        <p style="color: #71717a; font-size: 14px;">
            Your FREE trial is active for <strong style="color: #fbbf24;">{{trial_days}} days</strong>.
        </p>
        <p style="color: #a1a1aa; line-height: 1.6; margin-top: 20px;">
            Happy trading,<br>
            <strong style="color: #10b981;">Covered Call Engine Team</strong>
        </p>
    </div>
    <div style="text-align: center; padding: 20px; border-top: 1px solid #27272a; color: #71717a; font-size: 12px;">
        © 2025 Covered Call Engine. All rights reserved.
    </div>
</div>
        """
    },
    "getting_started": {
        "name": "Getting Started",
        "purpose": "Activation",
        "trigger": "+1 day",
        "delay_days": 1,
        "subject": "How to find your first high-premium covered call",
        "enabled": True,
        "html": """
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #09090b; color: #ffffff;">
    <div style="text-align: center; padding: 20px 0; border-bottom: 1px solid #27272a;">
        <h1 style="color: #10b981; margin: 0;">Covered Call Engine</h1>
    </div>
    <div style="padding: 30px 20px;">
        <h2 style="color: #ffffff; margin-bottom: 20px;">Hi {{first_name}},</h2>
        <p style="color: #a1a1aa; line-height: 1.6;">
            Most users find their first trade within 5 minutes.
        </p>
        <p style="color: #a1a1aa; line-height: 1.6; margin-top: 20px;">
            <strong style="color: #ffffff;">Here's a simple 3-step process:</strong>
        </p>
        <ol style="color: #a1a1aa; line-height: 1.8;">
            <li>Open Scanner</li>
            <li>Select IV > 30%</li>
            <li>Choose DTE 20–45 days</li>
        </ol>
        <p style="color: #fbbf24; line-height: 1.6; margin-top: 20px;">
            📌 <strong>Pro Tip:</strong> Focus on liquid stocks with tight spreads.
        </p>
        <div style="text-align: center; margin: 30px 0;">
            <a href="{{scanner_link}}" style="display: inline-block; padding: 15px 30px; background-color: #10b981; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: bold;">
                Try it now →
            </a>
        </div>
        <p style="color: #a1a1aa; line-height: 1.6;">
            – Team Covered Call Engine
        </p>
    </div>
    <div style="text-align: center; padding: 20px; border-top: 1px solid #27272a; color: #71717a; font-size: 12px;">
        © 2025 Covered Call Engine. All rights reserved.
    </div>
</div>
        """
    },
    "feature_highlight": {
        "name": "Feature Highlight – Scanner",
        "purpose": "Education",
        "trigger": "+3 days",
        "delay_days": 3,
        "subject": "💡 Don't miss this hidden scanner feature",
        "enabled": True,
        "html": """
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #09090b; color: #ffffff;">
    <div style="text-align: center; padding: 20px 0; border-bottom: 1px solid #27272a;">
        <h1 style="color: #10b981; margin: 0;">Covered Call Engine</h1>
    </div>
    <div style="padding: 30px 20px;">
        <h2 style="color: #ffffff; margin-bottom: 20px;">Hi {{first_name}},</h2>
        <p style="color: #a1a1aa; line-height: 1.6;">
            Did you know you can:
        </p>
        <ul style="color: #a1a1aa; line-height: 1.8;">
            <li>✔ Sort by premium yield</li>
            <li>✔ Compare ITM vs OTM returns</li>
            <li>✔ Save setups for later review</li>
        </ul>
        <p style="color: #a1a1aa; line-height: 1.6; margin-top: 20px;">
            This is where most profitable users start.
        </p>
        <div style="text-align: center; margin: 30px 0;">
            <a href="{{feature_link}}" style="display: inline-block; padding: 15px 30px; background-color: #8b5cf6; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: bold;">
                Explore now →
            </a>
        </div>
    </div>
    <div style="text-align: center; padding: 20px; border-top: 1px solid #27272a; color: #71717a; font-size: 12px;">
        © 2025 Covered Call Engine. All rights reserved.
    </div>
</div>
        """
    },
    "trial_checkin": {
        "name": "Trial Check-in",
        "purpose": "Engagement",
        "trigger": "+7 days",
        "delay_days": 7,
        "subject": "Are you finding value in your trial?",
        "enabled": True,
        "html": """
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #09090b; color: #ffffff;">
    <div style="text-align: center; padding: 20px 0; border-bottom: 1px solid #27272a;">
        <h1 style="color: #10b981; margin: 0;">Covered Call Engine</h1>
    </div>
    <div style="padding: 30px 20px;">
        <h2 style="color: #ffffff; margin-bottom: 20px;">Hi {{first_name}},</h2>
        <p style="color: #a1a1aa; line-height: 1.6;">
            Quick check-in 👋
        </p>
        <p style="color: #a1a1aa; line-height: 1.6; margin-top: 20px;">
            Have you:
        </p>
        <ul style="color: #a1a1aa; line-height: 1.8;">
            <li>✔ Found at least 1 trade?</li>
            <li>✔ Used filters?</li>
            <li>✔ Saved a setup?</li>
        </ul>
        <p style="color: #a1a1aa; line-height: 1.6; margin-top: 20px;">
            If not, <strong style="color: #10b981;">reply to this email</strong> and we'll help you personally.
        </p>
        <p style="color: #fbbf24; line-height: 1.6; margin-top: 20px;">
            Your success = our success.
        </p>
    </div>
    <div style="text-align: center; padding: 20px; border-top: 1px solid #27272a; color: #71717a; font-size: 12px;">
        © 2025 Covered Call Engine. All rights reserved.
    </div>
</div>
        """
    },
    "trial_expiry_reminder": {
        "name": "Trial Expiry Reminder",
        "purpose": "Conversion",
        "trigger": "2 days before expiry",
        "delay_days": -2,
        "subject": "⏳ Your FREE trial ends in 48 hours",
        "enabled": True,
        "html": """
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #09090b; color: #ffffff;">
    <div style="text-align: center; padding: 20px 0; border-bottom: 1px solid #27272a;">
        <h1 style="color: #10b981; margin: 0;">Covered Call Engine</h1>
    </div>
    <div style="padding: 30px 20px;">
        <h2 style="color: #fbbf24; margin-bottom: 20px;">⏳ Time is running out!</h2>
        <p style="color: #a1a1aa; line-height: 1.6;">
            Hi {{first_name}},
        </p>
        <p style="color: #a1a1aa; line-height: 1.6;">
            Your FREE trial ends in <strong style="color: #fbbf24;">2 days</strong>.
        </p>
        <p style="color: #a1a1aa; line-height: 1.6; margin-top: 20px;">
            To keep access to:
        </p>
        <ul style="color: #a1a1aa; line-height: 1.8;">
            <li>✔ Live scanner</li>
            <li>✔ Daily updates</li>
            <li>✔ New features</li>
        </ul>
        <div style="text-align: center; margin: 30px 0;">
            <a href="{{upgrade_link}}" style="display: inline-block; padding: 15px 30px; background-color: #10b981; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: bold;">
                Upgrade Now →
            </a>
        </div>
        <p style="color: #71717a; font-size: 14px;">
            No interruption, no data loss.
        </p>
    </div>
    <div style="text-align: center; padding: 20px; border-top: 1px solid #27272a; color: #71717a; font-size: 12px;">
        © 2025 Covered Call Engine. All rights reserved.
    </div>
</div>
        """
    },
    "trial_expired": {
        "name": "Trial Expired",
        "purpose": "Upgrade push",
        "trigger": "After expiry",
        "delay_days": 0,
        "subject": "Your trial has ended – continue where you left off",
        "enabled": True,
        "html": """
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #09090b; color: #ffffff;">
    <div style="text-align: center; padding: 20px 0; border-bottom: 1px solid #27272a;">
        <h1 style="color: #10b981; margin: 0;">Covered Call Engine</h1>
    </div>
    <div style="padding: 30px 20px;">
        <h2 style="color: #ffffff; margin-bottom: 20px;">Hi {{first_name}},</h2>
        <p style="color: #a1a1aa; line-height: 1.6;">
            Your FREE trial has ended, but your saved setups are still waiting.
        </p>
        <p style="color: #a1a1aa; line-height: 1.6; margin-top: 20px;">
            Reactivate anytime:
        </p>
        <div style="text-align: center; margin: 30px 0;">
            <a href="{{upgrade_link}}" style="display: inline-block; padding: 15px 30px; background-color: #10b981; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: bold;">
                👉 Reactivate Now
            </a>
        </div>
        <p style="color: #a1a1aa; line-height: 1.6;">
            We'd love to have you back.
        </p>
        <p style="color: #a1a1aa; line-height: 1.6; margin-top: 20px;">
            <strong style="color: #10b981;">Covered Call Engine Team</strong>
        </p>
    </div>
    <div style="text-align: center; padding: 20px; border-top: 1px solid #27272a; color: #71717a; font-size: 12px;">
        © 2025 Covered Call Engine. All rights reserved.
    </div>
</div>
        """
    },
    "announcement": {
        "name": "Announcement",
        "purpose": "Broadcast",
        "trigger": "Manual",
        "delay_days": 0,
        "subject": "📢 {{announcement_title}}",
        "enabled": True,
        "html": """
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #09090b; color: #ffffff;">
    <div style="text-align: center; padding: 20px 0; border-bottom: 1px solid #27272a;">
        <h1 style="color: #10b981; margin: 0;">Covered Call Engine</h1>
    </div>
    <div style="padding: 30px 20px;">
        <h2 style="color: #ffffff; margin-bottom: 20px;">📢 {{announcement_title}}</h2>
        <div style="color: #a1a1aa; line-height: 1.6;">
            {{announcement_content}}
        </div>
        <p style="color: #a1a1aa; line-height: 1.6; margin-top: 30px;">
            <strong style="color: #10b981;">Covered Call Engine Team</strong>
        </p>
    </div>
    <div style="text-align: center; padding: 20px; border-top: 1px solid #27272a; color: #71717a; font-size: 12px;">
        © 2025 Covered Call Engine. All rights reserved.
    </div>
</div>
        """
    },
    "system_update": {
        "name": "System Update",
        "purpose": "Informational",
        "trigger": "Manual / Scheduled",
        "delay_days": 0,
        "subject": "🔧 System Update: {{update_title}}",
        "enabled": True,
        "html": """
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #09090b; color: #ffffff;">
    <div style="text-align: center; padding: 20px 0; border-bottom: 1px solid #27272a;">
        <h1 style="color: #10b981; margin: 0;">Covered Call Engine</h1>
    </div>
    <div style="padding: 30px 20px;">
        <h2 style="color: #06b6d4; margin-bottom: 20px;">🔧 System Update</h2>
        <h3 style="color: #ffffff;">{{update_title}}</h3>
        <div style="color: #a1a1aa; line-height: 1.6;">
            {{update_content}}
        </div>
        <p style="color: #a1a1aa; line-height: 1.6; margin-top: 30px;">
            <strong style="color: #10b981;">Covered Call Engine Team</strong>
        </p>
    </div>
    <div style="text-align: center; padding: 20px; border-top: 1px solid #27272a; color: #71717a; font-size: 12px;">
        © 2025 Covered Call Engine. All rights reserved.
    </div>
</div>
        """
    }
}

# Default Automation Rules
DEFAULT_RULES = [
    {
        "name": "Welcome Email",
        "trigger_type": "subscription_created",
        "condition": {"status": "trialing"},
        "delay_minutes": 0,
        "action": "send_email",
        "template_key": "welcome_free_trial",
        "enabled": True
    },
    {
        "name": "Getting Started",
        "trigger_type": "subscription_created",
        "condition": {"status": "trialing"},
        "delay_minutes": 1440,  # 1 day
        "action": "send_email",
        "template_key": "getting_started",
        "enabled": True
    },
    {
        "name": "Feature Highlight",
        "trigger_type": "subscription_created",
        "condition": {"status": "trialing"},
        "delay_minutes": 4320,  # 3 days
        "action": "send_email",
        "template_key": "feature_highlight",
        "enabled": True
    },
    {
        "name": "Trial Check-in",
        "trigger_type": "subscription_created",
        "condition": {"status": "trialing"},
        "delay_minutes": 10080,  # 7 days
        "action": "send_email",
        "template_key": "trial_checkin",
        "enabled": True
    },
    {
        "name": "Trial Expiry Reminder",
        "trigger_type": "subscription_expiring",
        "condition": {"days_before": 2},
        "delay_minutes": 0,
        "action": "send_email",
        "template_key": "trial_expiry_reminder",
        "enabled": True
    },
    {
        "name": "Trial Expired",
        "trigger_type": "subscription_expired",
        "condition": {},
        "delay_minutes": 0,
        "action": "send_email",
        "template_key": "trial_expired",
        "enabled": True
    }
]

TRIGGER_TYPES = [
    {"value": "subscription_created", "label": "Subscription Created"},
    {"value": "subscription_renewed", "label": "Subscription Renewed"},
    {"value": "subscription_expiring", "label": "Subscription Expiring"},
    {"value": "subscription_expired", "label": "Subscription Expired"},
    {"value": "user_inactive", "label": "User Inactive (X days)"},
    {"value": "feature_not_used", "label": "Feature Not Used"},
    {"value": "manual_broadcast", "label": "Manual Broadcast"},
    {"value": "subscription_payment_succeeded", "label": "Payment Succeeded / Renewed"},
    {"value": "subscription_payment_failed", "label": "Payment Failed"},
    {"value": "subscription_cancelled", "label": "Subscription Cancelled"},
]

ACTION_TYPES = [
    {"value": "send_email", "label": "Send Email"},
    {"value": "add_tag", "label": "Add Tag"},
    {"value": "add_score", "label": "Add Score"},
    {"value": "trigger_followup", "label": "Trigger Follow-up"},
    {"value": "notify_admin", "label": "Notify Admin"}
]


class EmailAutomationService:
    def __init__(self, db):
        self.db = db
        self.resend_key = None
        self.sender_email = None
    
    async def initialize(self) -> bool:
        """Initialize the email automation service"""
        try:
            # Get email settings
            settings = await self.db.admin_settings.find_one({"type": "email_settings"}, {"_id": 0})
            self.resend_key = settings.get("resend_api_key") if settings else os.environ.get("RESEND_API_KEY")
            self.sender_email = settings.get("sender_email") if settings else "noreply@coveredcallengine.com"
            
            if self.resend_key:
                resend.api_key = self.resend_key
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to initialize email automation: {e}")
            return False
    
    async def setup_default_templates(self):
        """Create default email templates in database if they don't exist"""
        try:
            for key, template in DEFAULT_TEMPLATES.items():
                existing = await self.db.email_templates.find_one({"key": key})
                if not existing:
                    await self.db.email_templates.insert_one({
                        "id": str(uuid4()),
                        "key": key,
                        **template,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    })
            logger.info("Default email templates created")
            return True
        except Exception as e:
            logger.error(f"Failed to setup default templates: {e}")
            return False
    
    async def setup_default_rules(self):
        """Create default automation rules in database if they don't exist"""
        try:
            for rule in DEFAULT_RULES:
                existing = await self.db.automation_rules.find_one({"name": rule["name"]})
                if not existing:
                    await self.db.automation_rules.insert_one({
                        "id": str(uuid4()),
                        **rule,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    })
            logger.info("Default automation rules created")
            return True
        except Exception as e:
            logger.error(f"Failed to setup default rules: {e}")
            return False
    
    
    async def trigger_event(self, trigger_type: str, user: Dict, subscription: Dict):
        """Trigger automation rules for an event by scheduling email jobs."""
        await self.setup_default_templates()
        await self.setup_default_rules()

        rules = await self.db.automation_rules.find(
            {"trigger_type": trigger_type, "enabled": True},
            {"_id": 0}
        ).to_list(1000)

        if not rules:
            return {"scheduled": 0}

        scheduled = 0
        now = datetime.now(timezone.utc)

        # Normalize subscription context for rule matching
        ctx = {
            "plan": subscription.get("plan") or subscription.get("plan_name") or subscription.get("plan_id"),
            "plan_id": subscription.get("plan_id"),
            "status": subscription.get("status"),
            "billing_cycle": subscription.get("billing_cycle"),
            "payment_provider": subscription.get("payment_provider"),
        }

        for rule in rules:
            condition = rule.get("condition") or {}
            if not self._matches_condition(condition, ctx):
                continue

            delay_minutes = int(rule.get("delay_minutes", 0) or 0)
            run_at = now + timedelta(minutes=delay_minutes)

            job = {
                "id": str(uuid4()),
                "status": "scheduled",
                "trigger_type": trigger_type,
                "template_key": rule.get("template_key"),
                "to_email": user.get("email"),
                "payload": {
                    "first_name": user.get("first_name") or user.get("name") or "",
                    "email": user.get("email"),
                    "dashboard_url": os.environ.get("APP_URL", ""),
                    "trial_days": subscription.get("trial_days", 7),
                    "plan_name": subscription.get("plan_name") or subscription.get("plan_id") or "",
                },
                "run_at": run_at.isoformat(),
                "attempts": 0,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }

            await self.db.email_jobs.insert_one(job)
            scheduled += 1

        return {"scheduled": scheduled}

    def _matches_condition(self, condition: Dict, ctx: Dict) -> bool:
        """Simple condition matcher supporting keys in ctx."""
        for k, expected in (condition or {}).items():
            actual = ctx.get(k)
            if expected is None:
                continue
            if isinstance(expected, (list, tuple, set)):
                if actual not in expected:
                    return False
            else:
                if str(actual) != str(expected):
                    return False
        return True

    async def process_due_jobs(self, limit: int = 50) -> Dict[str, int]:
        """Send any scheduled emails that are due."""
        await self.initialize()
        now = datetime.now(timezone.utc)

        jobs = await self.db.email_jobs.find(
            {"status": "scheduled", "run_at": {"$lte": now.isoformat()}},
            {"_id": 0}
        ).to_list(limit)

        sent = 0
        failed = 0

        for job in jobs:
            job_id = job.get("id")
            template_key = job.get("template_key")
            to_email = job.get("to_email")
            payload = job.get("payload") or {}

            try:
                # Load template by key
                template = await self.db.email_templates.find_one({"key": template_key}, {"_id": 0})
                if not template:
                    # fallback to default templates dict
                    template = DEFAULT_TEMPLATES.get(template_key)

                if not template or not template.get("enabled", True):
                    await self.db.email_jobs.update_one({"id": job_id}, {"$set": {"status": "skipped", "updated_at": now.isoformat()}})
                    continue

                subject = template.get("subject", "")
                html = template.get("html", "")

                # Very lightweight variable substitution
                for k, v in payload.items():
                    html = html.replace(f"{{{{{k}}}}}", str(v))
                    subject = subject.replace(f"{{{{{k}}}}}", str(v))

                await self.send_email(to_email=to_email, subject=subject, html=html)

                await self.db.email_jobs.update_one({"id": job_id}, {"$set": {"status": "sent", "sent_at": now.isoformat(), "updated_at": now.isoformat()}})
                sent += 1
            except Exception as e:
                failed += 1
                await self.db.email_jobs.update_one(
                    {"id": job_id},
                    {"$set": {"status": "failed", "last_error": str(e), "updated_at": now.isoformat()}, "$inc": {"attempts": 1}}
                )

        return {"sent": sent, "failed": failed}


    async def get_templates(self) -> List[Dict]:
        """Get all email templates"""
        templates = await self.db.email_templates.find({}, {"_id": 0}).to_list(100)
        return templates
    
    async def get_template(self, template_id: str) -> Optional[Dict]:
        """Get a single email template"""
        return await self.db.email_templates.find_one(
            {"$or": [{"id": template_id}, {"key": template_id}]}, 
            {"_id": 0}
        )
    
    async def update_template(self, template_id: str, updates: Dict) -> bool:
        """Update an email template"""
        try:
            updates["updated_at"] = datetime.now(timezone.utc).isoformat()
            result = await self.db.email_templates.update_one(
                {"$or": [{"id": template_id}, {"key": template_id}]},
                {"$set": updates}
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Failed to update template: {e}")
            return False
    
    async def get_rules(self) -> List[Dict]:
        """Get all automation rules"""
        rules = await self.db.automation_rules.find({}, {"_id": 0}).to_list(100)
        return rules
    
    async def get_rule(self, rule_id: str) -> Optional[Dict]:
        """Get a single automation rule"""
        return await self.db.automation_rules.find_one({"id": rule_id}, {"_id": 0})
    
    async def create_rule(self, rule_data: Dict) -> Dict:
        """Create a new automation rule"""
        rule = {
            "id": str(uuid4()),
            **rule_data,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        await self.db.automation_rules.insert_one(rule)
        return rule
    
    async def update_rule(self, rule_id: str, updates: Dict) -> bool:
        """Update an automation rule"""
        try:
            updates["updated_at"] = datetime.now(timezone.utc).isoformat()
            result = await self.db.automation_rules.update_one(
                {"id": rule_id},
                {"$set": updates}
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Failed to update rule: {e}")
            return False
    
    async def delete_rule(self, rule_id: str) -> bool:
        """Delete an automation rule"""
        try:
            result = await self.db.automation_rules.delete_one({"id": rule_id})
            return result.deleted_count > 0
        except Exception as e:
            logger.error(f"Failed to delete rule: {e}")
            return False
    
    async def log_email(self, log_data: Dict):
        """Log an email send attempt"""
        log = {
            "id": str(uuid4()),
            **log_data,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await self.db.email_logs.insert_one(log)
        return log
    
    async def get_email_logs(self, limit: int = 100, skip: int = 0, filters: Dict = None) -> Dict:
        """Get email logs with pagination"""
        query = filters or {}
        total = await self.db.email_logs.count_documents(query)
        logs = await self.db.email_logs.find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
        return {"logs": logs, "total": total}
    
    async def get_email_stats(self) -> Dict:
        """Get email analytics/statistics"""
        try:
            total_sent = await self.db.email_logs.count_documents({"status": "sent"})
            total_failed = await self.db.email_logs.count_documents({"status": "failed"})
            total_pending = await self.db.email_logs.count_documents({"status": "pending"})
            
            # Get stats by template
            pipeline = [
                {"$group": {"_id": "$template_key", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}}
            ]
            by_template = await self.db.email_logs.aggregate(pipeline).to_list(20)
            
            # Recent activity (last 7 days)
            week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
            recent_sent = await self.db.email_logs.count_documents({
                "status": "sent",
                "created_at": {"$gte": week_ago}
            })
            
            return {
                "total_sent": total_sent,
                "total_failed": total_failed,
                "total_pending": total_pending,
                "recent_sent_7d": recent_sent,
                "by_template": by_template
            }
        except Exception as e:
            logger.error(f"Failed to get email stats: {e}")
            return {}
    
    async def send_email(self, to_email: str, template_key: str, variables: Dict) -> Dict:
        """Send an email using a template"""
        if not await self.initialize():
            return {"success": False, "error": "Email service not configured"}
        
        template = await self.get_template(template_key)
        if not template:
            return {"success": False, "error": f"Template '{template_key}' not found"}
        
        if not template.get("enabled", True):
            return {"success": False, "error": "Template is disabled"}
        
        # Replace variables in subject and body
        subject = template["subject"]
        html = template["html"]
        
        for key, value in variables.items():
            subject = subject.replace(f"{{{{{key}}}}}", str(value))
            html = html.replace(f"{{{{{key}}}}}", str(value))
        
        try:
            result = resend.Emails.send({
                "from": self.sender_email,
                "to": to_email,
                "subject": subject,
                "html": html
            })
            
            # Log the email
            await self.log_email({
                "template_key": template_key,
                "recipient": to_email,
                "subject": subject,
                "status": "sent",
                "resend_id": result.get("id") if isinstance(result, dict) else str(result)
            })
            
            return {"success": True, "message_id": result.get("id") if isinstance(result, dict) else str(result)}
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            
            # Log the failure
            await self.log_email({
                "template_key": template_key,
                "recipient": to_email,
                "subject": subject,
                "status": "failed",
                "error": str(e)
            })
            
            return {"success": False, "error": str(e)}
    
    async def send_broadcast(self, template_key: str, variables: Dict, recipient_filter: Dict = None) -> Dict:
        """Send a broadcast email to multiple users"""
        if not await self.initialize():
            return {"success": False, "error": "Email service not configured"}
        
        # Get users based on filter
        query = recipient_filter or {}
        users = await self.db.users.find(query, {"email": 1, "name": 1, "_id": 0}).to_list(10000)
        
        sent_count = 0
        failed_count = 0
        
        for user in users:
            user_vars = {**variables, "first_name": user.get("name", "").split()[0] if user.get("name") else "there"}
            result = await self.send_email(user["email"], template_key, user_vars)
            if result.get("success"):
                sent_count += 1
            else:
                failed_count += 1
        
        return {
            "success": True,
            "sent": sent_count,
            "failed": failed_count,
            "total": len(users)
        }