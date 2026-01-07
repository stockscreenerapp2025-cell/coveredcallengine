"""
Stripe Webhook Handler for Covered Call Engine
Handles subscription lifecycle events
"""

import os
import logging
import stripe
from datetime import datetime, timezone, timedelta
from fastapi import Request, HTTPException

logger = logging.getLogger(__name__)


class StripeWebhookHandler:
    """Handle Stripe webhook events"""
    
    def __init__(self, db, email_service):
        self.db = db
        self.email_service = email_service
        self.webhook_secret = None
    
    async def initialize(self):
        """Load Stripe settings from database"""
        settings = await self.db.admin_settings.find_one({"type": "stripe_settings"}, {"_id": 0})
        if settings:
            self.webhook_secret = settings.get("webhook_secret")
            stripe_key = settings.get("stripe_secret_key")
            if stripe_key:
                stripe.api_key = stripe_key
        
        # Fallback to env
        if not self.webhook_secret:
            self.webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
        
        return bool(self.webhook_secret)
    
    async def verify_webhook(self, request: Request) -> dict:
        """Verify and parse webhook payload"""
        if not await self.initialize():
            raise HTTPException(status_code=500, detail="Stripe webhook not configured")
        
        payload = await request.body()
        sig_header = request.headers.get("stripe-signature")
        
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, self.webhook_secret
            )
            return event
        except ValueError as e:
            logger.error(f"Invalid payload: {e}")
            raise HTTPException(status_code=400, detail="Invalid payload")
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Invalid signature: {e}")
            raise HTTPException(status_code=400, detail="Invalid signature")
    
    async def handle_event(self, event: dict) -> dict:
        """Route event to appropriate handler"""
        event_type = event.get("type")
        data = event.get("data", {}).get("object", {})
        
        handlers = {
            "checkout.session.completed": self._handle_checkout_completed,
            "customer.subscription.created": self._handle_subscription_created,
            "customer.subscription.updated": self._handle_subscription_updated,
            "customer.subscription.deleted": self._handle_subscription_deleted,
            "invoice.payment_succeeded": self._handle_payment_succeeded,
            "invoice.payment_failed": self._handle_payment_failed,
            "customer.subscription.trial_will_end": self._handle_trial_ending,
        }
        
        handler = handlers.get(event_type)
        if handler:
            result = await handler(data)
            
            # Log webhook event
            await self._log_event(event_type, data, result)
            
            return result
        
        logger.info(f"Unhandled event type: {event_type}")
        return {"status": "ignored", "event_type": event_type}
    
    async def _log_event(self, event_type: str, data: dict, result: dict):
        """Log webhook event for audit"""
        await self.db.webhook_logs.insert_one({
            "event_type": event_type,
            "stripe_customer_id": data.get("customer"),
            "stripe_subscription_id": data.get("id") or data.get("subscription"),
            "result": result,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    
    async def _get_user_by_stripe_customer(self, customer_id: str) -> dict:
        """Find user by Stripe customer ID"""
        return await self.db.users.find_one(
            {"stripe_customer_id": customer_id},
            {"_id": 0}
        )
    
    async def _get_user_by_email(self, email: str) -> dict:
        """Find user by email"""
        return await self.db.users.find_one({"email": email}, {"_id": 0})
    
    async def _handle_checkout_completed(self, data: dict) -> dict:
        """Handle successful checkout - create/update user subscription"""
        customer_email = data.get("customer_details", {}).get("email")
        customer_id = data.get("customer")
        subscription_id = data.get("subscription")
        
        if not customer_email:
            return {"status": "error", "reason": "No customer email"}
        
        # Determine plan from metadata or amount
        mode = data.get("mode")
        plan = "trial"
        
        if mode == "subscription":
            amount = data.get("amount_total", 0)
            if amount >= 49900:  # $499
                plan = "yearly"
            elif amount >= 4900:  # $49
                plan = "monthly"
        
        # Find or create user
        user = await self._get_user_by_email(customer_email)
        
        now = datetime.now(timezone.utc)
        trial_end = (now + timedelta(days=7)).isoformat() if plan == "trial" else None
        
        subscription_data = {
            "stripe_customer_id": customer_id,
            "stripe_subscription_id": subscription_id,
            "subscription": {
                "plan": plan,
                "status": "trialing" if plan == "trial" else "active",
                "trial_start": now.isoformat() if plan == "trial" else None,
                "trial_end": trial_end,
                "subscription_start": now.isoformat(),
                "next_billing_date": trial_end or (now + timedelta(days=30 if plan == "monthly" else 365)).isoformat(),
                "payment_status": "succeeded"
            },
            "updated_at": now.isoformat()
        }
        
        if user:
            # Update existing user
            await self.db.users.update_one(
                {"email": customer_email},
                {"$set": subscription_data}
            )
            user = await self._get_user_by_email(customer_email)
        else:
            # Create new user with temporary password
            from uuid import uuid4
            import hashlib
            
            temp_password = str(uuid4())[:8]
            hashed_password = hashlib.sha256(temp_password.encode()).hexdigest()
            
            new_user = {
                "id": str(uuid4()),
                "email": customer_email,
                "name": data.get("customer_details", {}).get("name", ""),
                "hashed_password": hashed_password,
                "temp_password": temp_password,  # Store temporarily for welcome email
                "is_admin": False,
                "created_at": now.isoformat(),
                **subscription_data
            }
            
            await self.db.users.insert_one(new_user)
            user = new_user
        
        # Send welcome email
        if self.email_service:
            await self.email_service.send_welcome_email(user)
        
        return {"status": "success", "action": "subscription_created", "plan": plan}
    
    async def _handle_subscription_created(self, data: dict) -> dict:
        """Handle subscription created event"""
        customer_id = data.get("customer")
        user = await self._get_user_by_stripe_customer(customer_id)
        
        if not user:
            return {"status": "skipped", "reason": "User not found"}
        
        status = data.get("status")
        plan = self._get_plan_from_subscription(data)
        
        await self.db.users.update_one(
            {"stripe_customer_id": customer_id},
            {"$set": {
                "stripe_subscription_id": data.get("id"),
                "subscription.status": status,
                "subscription.plan": plan,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }}
        )
        
        return {"status": "success", "action": "subscription_updated"}
    
    async def _handle_subscription_updated(self, data: dict) -> dict:
        """Handle subscription update (plan change, status change)"""
        customer_id = data.get("customer")
        user = await self._get_user_by_stripe_customer(customer_id)
        
        if not user:
            return {"status": "skipped", "reason": "User not found"}
        
        status = data.get("status")
        plan = self._get_plan_from_subscription(data)
        cancel_at = data.get("cancel_at")
        
        update_data = {
            "subscription.status": status,
            "subscription.plan": plan,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        if cancel_at:
            update_data["subscription.cancelled_at"] = datetime.fromtimestamp(cancel_at, timezone.utc).isoformat()
        
        # Check for trial to paid conversion
        previous_status = user.get("subscription", {}).get("status")
        if previous_status == "trialing" and status == "active":
            update_data["subscription.converted_at"] = datetime.now(timezone.utc).isoformat()
            
            # Send conversion email
            if self.email_service:
                updated_user = {**user, "subscription": {**user.get("subscription", {}), "plan": plan}}
                await self.email_service.send_conversion_email(updated_user)
        
        await self.db.users.update_one(
            {"stripe_customer_id": customer_id},
            {"$set": update_data}
        )
        
        return {"status": "success", "action": "subscription_updated", "new_status": status}
    
    async def _handle_subscription_deleted(self, data: dict) -> dict:
        """Handle subscription cancellation"""
        customer_id = data.get("customer")
        user = await self._get_user_by_stripe_customer(customer_id)
        
        if not user:
            return {"status": "skipped", "reason": "User not found"}
        
        now = datetime.now(timezone.utc)
        
        await self.db.users.update_one(
            {"stripe_customer_id": customer_id},
            {"$set": {
                "subscription.status": "cancelled",
                "subscription.cancelled_at": now.isoformat(),
                "updated_at": now.isoformat()
            }}
        )
        
        # Send cancellation email
        if self.email_service:
            await self.email_service.send_cancellation_email(user)
        
        return {"status": "success", "action": "subscription_cancelled"}
    
    async def _handle_payment_succeeded(self, data: dict) -> dict:
        """Handle successful payment"""
        customer_id = data.get("customer")
        
        await self.db.users.update_one(
            {"stripe_customer_id": customer_id},
            {"$set": {
                "subscription.payment_status": "succeeded",
                "subscription.last_payment_date": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }}
        )
        
        return {"status": "success", "action": "payment_recorded"}
    
    async def _handle_payment_failed(self, data: dict) -> dict:
        """Handle failed payment"""
        customer_id = data.get("customer")
        user = await self._get_user_by_stripe_customer(customer_id)
        
        if not user:
            return {"status": "skipped", "reason": "User not found"}
        
        await self.db.users.update_one(
            {"stripe_customer_id": customer_id},
            {"$set": {
                "subscription.status": "past_due",
                "subscription.payment_status": "failed",
                "updated_at": datetime.now(timezone.utc).isoformat()
            }}
        )
        
        # Send payment failed email
        if self.email_service:
            await self.email_service.send_payment_failed_email(user)
        
        return {"status": "success", "action": "payment_failed_recorded"}
    
    async def _handle_trial_ending(self, data: dict) -> dict:
        """Handle trial ending soon notification"""
        customer_id = data.get("customer")
        user = await self._get_user_by_stripe_customer(customer_id)
        
        if not user:
            return {"status": "skipped", "reason": "User not found"}
        
        trial_end = data.get("trial_end")
        days_left = 3  # Stripe sends this 3 days before trial ends
        
        if trial_end:
            end_date = datetime.fromtimestamp(trial_end, timezone.utc)
            days_left = (end_date - datetime.now(timezone.utc)).days
        
        # Send trial ending email
        if self.email_service:
            await self.email_service.send_trial_ending_email(user, days_left)
        
        return {"status": "success", "action": "trial_ending_notification_sent"}
    
    def _get_plan_from_subscription(self, subscription: dict) -> str:
        """Determine plan type from subscription data"""
        items = subscription.get("items", {}).get("data", [])
        if not items:
            return "monthly"
        
        price = items[0].get("price", {})
        interval = price.get("recurring", {}).get("interval", "month")
        
        if interval == "year":
            return "yearly"
        return "monthly"
