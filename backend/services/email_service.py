"""
Email Service using SMTP (Hostinger) for Covered Call Engine
Handles all transactional and lifecycle emails
"""

import os
import asyncio
import logging
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# SMTP Configuration
def _get_smtp_config():
    return {
        "host": os.environ.get("SMTP_HOST", "smtp.hostinger.com"),
        "port": int(os.environ.get("SMTP_PORT", 465)),
        "username": os.environ.get("SMTP_USERNAME", "contact@coveredcallengine.com"),
        "password": os.environ.get("SMTP_PASSWORD", ""),
    }

async def _smtp_send(to_email: str, subject: str, html: str, from_email: str = None, reply_to: str = None) -> dict:
    """Core SMTP send function"""
    cfg = _get_smtp_config()
    sender = from_email or cfg["username"]

    def _send():
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"Covered Call Engine <{sender}>"
        msg["To"] = to_email
        if reply_to:
            msg["Reply-To"] = reply_to
        msg.attach(MIMEText(html, "html"))
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"], context=context) as s:
            s.login(cfg["username"], cfg["password"])
            s.sendmail(sender, to_email, msg.as_string())

    try:
        await asyncio.to_thread(_send)
        logger.info(f"Email sent to {to_email}: {subject}")
        return {"status": "success"}
    except Exception as e:
        logger.error(f"SMTP error sending to {to_email}: {e}")
        return {"status": "error", "reason": str(e)}


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
                <ul style="color: #a1a1aa; line-height: 1.8;">
                    <li>📊 Access to Covered Call Dashboard</li>
                    <li>📈 Near real-time options data</li>
                    <li>📉 TradingView chart integration</li>
                    <li>💹 Key Technical indicators</li>
                </ul>
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{{login_url}}" style="display: inline-block; padding: 15px 30px; background-color: #10b981; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: bold;">
                        Start Scanning Now →
                    </a>
                </div>
                <p style="color: #71717a; font-size: 14px;">
                    Your trial ends on <strong style="color: #fbbf24;">{{trial_end_date}}</strong>.
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
                <p style="color: #a1a1aa; line-height: 1.6;">Hi {{name}},</p>
                <p style="color: #a1a1aa; line-height: 1.6;">
                    Your free trial ends on <strong style="color: #fbbf24;">{{trial_end_date}}</strong> ({{days_left}} days left).
                </p>
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{{subscribe_url}}" style="display: inline-block; padding: 15px 30px; background-color: #8b5cf6; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: bold;">
                        Subscribe Now & Keep Access →
                    </a>
                </div>
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
                <p style="color: #a1a1aa;">Hi {{name}},</p>
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
                <p style="color: #a1a1aa;">Hi {{name}},</p>
                <p style="color: #a1a1aa;">We couldn't process your payment for your <strong>{{plan}}</strong> subscription.</p>
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{{billing_url}}" style="display: inline-block; padding: 15px 30px; background-color: #ef4444; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: bold;">
                        Update Payment Method →
                    </a>
                </div>
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
                <p style="color: #a1a1aa;">Hi {{name}},</p>
                <p style="color: #a1a1aa;">You'll still have access until <strong style="color: #fbbf24;">{{access_until}}</strong>.</p>
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{{feedback_url}}" style="display: inline-block; padding: 15px 30px; background-color: #3f3f46; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: bold;">
                        Share Feedback →
                    </a>
                </div>
            </div>
            <div style="text-align: center; padding: 20px; border-top: 1px solid #27272a; color: #71717a; font-size: 12px;">
                © 2025 Covered Call Engine. All rights reserved.
            </div>
        </div>
        """
    },
    "annual_thank_you": {
        "subject": "🙏 Thank you for your Annual subscription!",
        "enabled": True,
        "html": """
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #09090b; color: #ffffff;">
            <div style="text-align: center; padding: 20px 0; border-bottom: 1px solid #27272a;">
                <h1 style="color: #10b981; margin: 0;">Covered Call Engine</h1>
            </div>
            <div style="padding: 30px 20px;">
                <h2 style="color: #f59e0b; margin-bottom: 20px;">🙏 Thank you, {{name}}!</h2>
                <p style="color: #a1a1aa;">We're thrilled you've chosen the Annual Plan!</p>
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
    """Email service using SMTP (Hostinger) - drop-in replacement for Resend-based service"""

    def __init__(self, db):
        self.db = db
        self.base_url = os.environ.get("APP_BASE_URL", "https://coveredcallengine.com")

    def _replace_variables(self, template: str, variables: dict) -> str:
        result = template
        for key, value in variables.items():
            result = result.replace(f"{{{{{key}}}}}", str(value))
        return result

    async def send_email(self, to_email: str, template_name: str, variables: dict) -> dict:
        """Send email using a template"""
        template = EMAIL_TEMPLATES.get(template_name)
        if not template:
            return {"status": "error", "reason": f"Template '{template_name}' not found"}
        if not template.get("enabled", True):
            return {"status": "skipped", "reason": "Template disabled"}

        variables.setdefault("login_url", f"{self.base_url}/login")
        variables.setdefault("subscribe_url", f"{self.base_url}/#pricing")
        variables.setdefault("billing_url", f"{self.base_url}/billing")
        variables.setdefault("feedback_url", f"{self.base_url}/feedback")

        subject = self._replace_variables(template["subject"], variables)
        html = self._replace_variables(template["html"], variables)

        result = await _smtp_send(to_email, subject, html)

        # Log to DB
        try:
            await self.db.email_logs.insert_one({
                "to": to_email,
                "template": template_name,
                "subject": subject,
                "status": result["status"],
                "sent_at": datetime.now(timezone.utc).isoformat()
            })
        except Exception:
            pass

        return result

    async def send_raw_email(self, to_email: str, subject: str, html_content: str,
                              from_email: str = None, reply_to: str = None) -> dict:
        """Send a raw email without using templates"""
        result = await _smtp_send(to_email, subject, html_content,
                                   from_email=from_email, reply_to=reply_to)

        # Log to DB
        try:
            await self.db.email_logs.insert_one({
                "to": to_email,
                "from": from_email,
                "template": "raw_email",
                "subject": subject,
                "status": result["status"],
                "sent_at": datetime.now(timezone.utc).isoformat()
            })
        except Exception:
            pass

        return result

    async def send_welcome_email(self, user: dict):
        variables = {
            "name": user.get("name", user.get("email", "").split("@")[0]),
            "plan": user.get("subscription", {}).get("plan", "7-Day Free Trial"),
            "trial_end_date": user.get("subscription", {}).get("trial_end", "N/A")
        }
        return await self.send_email(user["email"], "welcome", variables)

    async def send_trial_ending_email(self, user: dict, days_left: int):
        variables = {
            "name": user.get("name", user.get("email", "").split("@")[0]),
            "days_left": days_left,
            "trial_end_date": user.get("subscription", {}).get("trial_end", "N/A")
        }
        return await self.send_email(user["email"], "trial_ending", variables)

    async def send_conversion_email(self, user: dict):
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
        variables = {
            "name": user.get("name", user.get("email", "").split("@")[0]),
            "plan": user.get("subscription", {}).get("plan", "Subscription")
        }
        return await self.send_email(user["email"], "payment_failed", variables)

    async def send_cancellation_email(self, user: dict):
        variables = {
            "name": user.get("name", user.get("email", "").split("@")[0]),
            "plan": user.get("subscription", {}).get("plan", "Subscription"),
            "access_until": user.get("subscription", {}).get("cancelled_at", "N/A")
        }
        return await self.send_email(user["email"], "subscription_cancelled", variables)
