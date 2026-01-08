"""
Email Service using Resend for Covered Call Engine
Handles all transactional and lifecycle emails
"""

import os
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
import resend

logger = logging.getLogger(__name__)

# Email Templates
EMAIL_TEMPLATES = {
    "welcome": {
        "subject": "Welcome to Covered Call Engine! 🎉",
        "enabled": True,
        "html": """
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #09090b; color: #ffffff;">
            <div style="text-align: center; padding: 20px 0; border-bottom: 1px solid #27272a;">
                <h1 style="color: #10b981; margin: 0;">Covered Call Engine</h1>
            </div>
            <div style="padding: 30px 20px;">
                <h2 style="color: #ffffff; margin-bottom: 20px;">Welcome, {{name}}! 👋</h2>
                <p style="color: #a1a1aa; line-height: 1.6;">
                    Thank you for starting your <strong style="color: #10b981;">{{plan}}</strong> with Covered Call Engine!
                </p>
                <p style="color: #a1a1aa; line-height: 1.6;">
                    You now have access to our powerful options screening tools:
                </p>
                <ul style="color: #a1a1aa; line-height: 1.8;">
                    <li>📊 Covered Call Screener with advanced filters</li>
                    <li>📈 PMCC Strategy Scanner with real LEAPS data</li>
                    <li>📉 TradingView charts with SMA 50/200</li>
                    <li>💼 Portfolio tracking and management</li>
                </ul>
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{{login_url}}" style="display: inline-block; padding: 15px 30px; background-color: #10b981; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: bold;">
                        Start Scanning Now →
                    </a>
                </div>
                <p style="color: #71717a; font-size: 14px;">
                    Your trial ends on <strong style="color: #fbbf24;">{{trial_end_date}}</strong>. 
                    Make the most of it!
                </p>
            </div>
            <div style="text-align: center; padding: 20px; border-top: 1px solid #27272a; color: #71717a; font-size: 12px;">
                © 2025 Covered Call Engine. All rights reserved.
            </div>
        </div>
        """
    },
    "trial_ending": {
        "subject": "⏰ Your trial ends in {{days_left}} days",
        "enabled": True,
        "html": """
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #09090b; color: #ffffff;">
            <div style="text-align: center; padding: 20px 0; border-bottom: 1px solid #27272a;">
                <h1 style="color: #10b981; margin: 0;">Covered Call Engine</h1>
            </div>
            <div style="padding: 30px 20px;">
                <h2 style="color: #fbbf24; margin-bottom: 20px;">⏰ Your trial is ending soon!</h2>
                <p style="color: #a1a1aa; line-height: 1.6;">
                    Hi {{name}},
                </p>
                <p style="color: #a1a1aa; line-height: 1.6;">
                    Your free trial ends on <strong style="color: #fbbf24;">{{trial_end_date}}</strong> 
                    ({{days_left}} days left).
                </p>
                <p style="color: #a1a1aa; line-height: 1.6;">
                    Don't lose access to:
                </p>
                <ul style="color: #a1a1aa; line-height: 1.8;">
                    <li>✅ Real-time options screening</li>
                    <li>✅ PMCC opportunities with LEAPS</li>
                    <li>✅ TradingView chart analysis</li>
                    <li>✅ Your saved watchlist and portfolio</li>
                </ul>
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{{subscribe_url}}" style="display: inline-block; padding: 15px 30px; background-color: #8b5cf6; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: bold;">
                        Subscribe Now & Keep Access →
                    </a>
                </div>
                <p style="color: #71717a; font-size: 14px; text-align: center;">
                    Questions? Just reply to this email.
                </p>
            </div>
            <div style="text-align: center; padding: 20px; border-top: 1px solid #27272a; color: #71717a; font-size: 12px;">
                © 2025 Covered Call Engine. All rights reserved.
            </div>
        </div>
        """
    },
    "trial_converted": {
        "subject": "🎉 Welcome to Premium, {{name}}!",
        "enabled": True,
        "html": """
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #09090b; color: #ffffff;">
            <div style="text-align: center; padding: 20px 0; border-bottom: 1px solid #27272a;">
                <h1 style="color: #10b981; margin: 0;">Covered Call Engine</h1>
            </div>
            <div style="padding: 30px 20px;">
                <h2 style="color: #10b981; margin-bottom: 20px;">🎉 You're now a Premium member!</h2>
                <p style="color: #a1a1aa; line-height: 1.6;">
                    Hi {{name}},
                </p>
                <p style="color: #a1a1aa; line-height: 1.6;">
                    Thank you for subscribing to the <strong style="color: #8b5cf6;">{{plan}}</strong>!
                </p>
                <p style="color: #a1a1aa; line-height: 1.6;">
                    Your subscription details:
                </p>
                <div style="background-color: #18181b; border-radius: 8px; padding: 20px; margin: 20px 0;">
                    <p style="color: #ffffff; margin: 5px 0;"><strong>Plan:</strong> {{plan}}</p>
                    <p style="color: #ffffff; margin: 5px 0;"><strong>Next billing:</strong> {{next_billing_date}}</p>
                    <p style="color: #ffffff; margin: 5px 0;"><strong>Amount:</strong> {{amount}}</p>
                </div>
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{{login_url}}" style="display: inline-block; padding: 15px 30px; background-color: #10b981; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: bold;">
                        Go to Dashboard →
                    </a>
                </div>
            </div>
            <div style="text-align: center; padding: 20px; border-top: 1px solid #27272a; color: #71717a; font-size: 12px;">
                © 2025 Covered Call Engine. All rights reserved.
            </div>
        </div>
        """
    },
    "payment_failed": {
        "subject": "⚠️ Payment failed - Action required",
        "enabled": True,
        "html": """
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #09090b; color: #ffffff;">
            <div style="text-align: center; padding: 20px 0; border-bottom: 1px solid #27272a;">
                <h1 style="color: #10b981; margin: 0;">Covered Call Engine</h1>
            </div>
            <div style="padding: 30px 20px;">
                <h2 style="color: #ef4444; margin-bottom: 20px;">⚠️ Payment Failed</h2>
                <p style="color: #a1a1aa; line-height: 1.6;">
                    Hi {{name}},
                </p>
                <p style="color: #a1a1aa; line-height: 1.6;">
                    We couldn't process your payment for your <strong>{{plan}}</strong> subscription.
                </p>
                <p style="color: #a1a1aa; line-height: 1.6;">
                    Please update your payment method to avoid losing access to your account.
                </p>
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{{billing_url}}" style="display: inline-block; padding: 15px 30px; background-color: #ef4444; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: bold;">
                        Update Payment Method →
                    </a>
                </div>
                <p style="color: #71717a; font-size: 14px; text-align: center;">
                    If you need help, just reply to this email.
                </p>
            </div>
            <div style="text-align: center; padding: 20px; border-top: 1px solid #27272a; color: #71717a; font-size: 12px;">
                © 2025 Covered Call Engine. All rights reserved.
            </div>
        </div>
        """
    },
    "subscription_cancelled": {
        "subject": "We're sorry to see you go 😢",
        "enabled": True,
        "html": """
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #09090b; color: #ffffff;">
            <div style="text-align: center; padding: 20px 0; border-bottom: 1px solid #27272a;">
                <h1 style="color: #10b981; margin: 0;">Covered Call Engine</h1>
            </div>
            <div style="padding: 30px 20px;">
                <h2 style="color: #a1a1aa; margin-bottom: 20px;">Your subscription has been cancelled</h2>
                <p style="color: #a1a1aa; line-height: 1.6;">
                    Hi {{name}},
                </p>
                <p style="color: #a1a1aa; line-height: 1.6;">
                    Your <strong>{{plan}}</strong> subscription has been cancelled.
                </p>
                <p style="color: #a1a1aa; line-height: 1.6;">
                    You'll still have access until <strong style="color: #fbbf24;">{{access_until}}</strong>.
                </p>
                <p style="color: #a1a1aa; line-height: 1.6;">
                    We'd love to know how we can improve. Would you mind sharing your feedback?
                </p>
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{{feedback_url}}" style="display: inline-block; padding: 15px 30px; background-color: #3f3f46; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: bold;">
                        Share Feedback →
                    </a>
                </div>
                <p style="color: #71717a; font-size: 14px; text-align: center;">
                    Changed your mind? You can resubscribe anytime.
                </p>
            </div>
            <div style="text-align: center; padding: 20px; border-top: 1px solid #27272a; color: #71717a; font-size: 12px;">
                © 2025 Covered Call Engine. All rights reserved.
            </div>
        </div>
        """
    },
    "annual_thank_you": {
        "subject": "🙏 Thank you for your annual subscription!",
        "enabled": True,
        "html": """
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #09090b; color: #ffffff;">
            <div style="text-align: center; padding: 20px 0; border-bottom: 1px solid #27272a;">
                <h1 style="color: #10b981; margin: 0;">Covered Call Engine</h1>
            </div>
            <div style="padding: 30px 20px;">
                <h2 style="color: #f59e0b; margin-bottom: 20px;">🙏 Thank you, {{name}}!</h2>
                <p style="color: #a1a1aa; line-height: 1.6;">
                    We're thrilled you've chosen the <strong style="color: #f59e0b;">Annual Plan</strong>!
                </p>
                <p style="color: #a1a1aa; line-height: 1.6;">
                    You're saving <strong style="color: #10b981;">$89/year</strong> compared to monthly billing.
                </p>
                <div style="background-color: #18181b; border-radius: 8px; padding: 20px; margin: 20px 0;">
                    <p style="color: #ffffff; margin: 5px 0;"><strong>Your benefits:</strong></p>
                    <ul style="color: #a1a1aa; line-height: 1.8; margin: 10px 0;">
                        <li>🌟 Priority support</li>
                        <li>🚀 Early access to new features</li>
                        <li>💰 Locked-in pricing</li>
                        <li>📊 Annual strategy review</li>
                    </ul>
                </div>
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{{login_url}}" style="display: inline-block; padding: 15px 30px; background-color: #f59e0b; color: #000000; text-decoration: none; border-radius: 8px; font-weight: bold;">
                        Go to Dashboard →
                    </a>
                </div>
            </div>
            <div style="text-align: center; padding: 20px; border-top: 1px solid #27272a; color: #71717a; font-size: 12px;">
                © 2025 Covered Call Engine. All rights reserved.
            </div>
        </div>
        """
    }
}


class EmailService:
    """Email service using Resend"""
    
    def __init__(self, db):
        self.db = db
        self.api_key = None
        self.sender_email = None
        self.base_url = os.environ.get("APP_BASE_URL", "https://coveredcallengine.com")
    
    async def initialize(self):
        """Load email settings from database"""
        settings = await self.db.admin_settings.find_one({"type": "email_settings"}, {"_id": 0})
        if settings:
            self.api_key = settings.get("resend_api_key")
            self.sender_email = settings.get("sender_email")
        
        # Fallback to env
        if not self.api_key:
            self.api_key = os.environ.get("RESEND_API_KEY")
        
        # Set default sender email if not configured
        if not self.sender_email:
            self.sender_email = os.environ.get("SENDER_EMAIL", "onboarding@resend.dev")
        
        if self.api_key:
            resend.api_key = self.api_key
            return True
        return False
    
    def _replace_variables(self, template: str, variables: dict) -> str:
        """Replace template variables"""
        result = template
        for key, value in variables.items():
            result = result.replace(f"{{{{{key}}}}}", str(value))
        return result
    
    async def send_email(self, to_email: str, template_name: str, variables: dict) -> dict:
        """Send email using a template"""
        if not await self.initialize():
            logger.warning("Email service not configured - skipping email")
            return {"status": "skipped", "reason": "Email service not configured"}
        
        template = EMAIL_TEMPLATES.get(template_name)
        if not template:
            return {"status": "error", "reason": f"Template '{template_name}' not found"}
        
        if not template.get("enabled", True):
            return {"status": "skipped", "reason": "Template disabled"}
        
        # Add default variables
        variables.setdefault("login_url", f"{self.base_url}/login")
        variables.setdefault("subscribe_url", f"{self.base_url}/#pricing")
        variables.setdefault("billing_url", f"{self.base_url}/billing")
        variables.setdefault("feedback_url", f"{self.base_url}/feedback")
        
        subject = self._replace_variables(template["subject"], variables)
        html = self._replace_variables(template["html"], variables)
        
        params = {
            "from": self.sender_email,
            "to": [to_email],
            "subject": subject,
            "html": html
        }
        
        try:
            email_result = await asyncio.to_thread(resend.Emails.send, params)
            
            # Log email send
            await self.db.email_logs.insert_one({
                "to": to_email,
                "template": template_name,
                "subject": subject,
                "status": "sent",
                "email_id": email_result.get("id"),
                "sent_at": datetime.now(timezone.utc).isoformat()
            })
            
            return {"status": "success", "email_id": email_result.get("id")}
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            
            # Log failure
            await self.db.email_logs.insert_one({
                "to": to_email,
                "template": template_name,
                "subject": subject,
                "status": "failed",
                "error": str(e),
                "sent_at": datetime.now(timezone.utc).isoformat()
            })
            
            return {"status": "error", "reason": str(e)}
    
    async def send_welcome_email(self, user: dict):
        """Send welcome email to new user"""
        variables = {
            "name": user.get("name", user.get("email", "").split("@")[0]),
            "plan": user.get("subscription", {}).get("plan", "7-Day Free Trial"),
            "trial_end_date": user.get("subscription", {}).get("trial_end", "N/A")
        }
        return await self.send_email(user["email"], "welcome", variables)
    
    async def send_trial_ending_email(self, user: dict, days_left: int):
        """Send trial ending reminder"""
        variables = {
            "name": user.get("name", user.get("email", "").split("@")[0]),
            "days_left": days_left,
            "trial_end_date": user.get("subscription", {}).get("trial_end", "N/A")
        }
        return await self.send_email(user["email"], "trial_ending", variables)
    
    async def send_conversion_email(self, user: dict):
        """Send email when trial converts to paid"""
        sub = user.get("subscription", {})
        plan_name = "Monthly Plan" if sub.get("plan") == "monthly" else "Annual Plan"
        amount = "$49/month" if sub.get("plan") == "monthly" else "$499/year"
        
        variables = {
            "name": user.get("name", user.get("email", "").split("@")[0]),
            "plan": plan_name,
            "next_billing_date": sub.get("next_billing_date", "N/A"),
            "amount": amount
        }
        
        template = "annual_thank_you" if sub.get("plan") == "yearly" else "trial_converted"
        return await self.send_email(user["email"], template, variables)
    
    async def send_payment_failed_email(self, user: dict):
        """Send payment failed notification"""
        variables = {
            "name": user.get("name", user.get("email", "").split("@")[0]),
            "plan": user.get("subscription", {}).get("plan", "Subscription")
        }
        return await self.send_email(user["email"], "payment_failed", variables)
    
    async def send_cancellation_email(self, user: dict):
        """Send cancellation confirmation"""
        variables = {
            "name": user.get("name", user.get("email", "").split("@")[0]),
            "plan": user.get("subscription", {}).get("plan", "Subscription"),
            "access_until": user.get("subscription", {}).get("cancelled_at", "N/A")
        }
        return await self.send_email(user["email"], "subscription_cancelled", variables)
