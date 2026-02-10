"""
PayPal Service for AI Token Pack Purchases

Implements PayPal REST API v2 for one-time token pack purchases.

Features:
- Order creation with custom_id tracking
- Webhook signature verification
- Idempotent event processing
- Environment switching (sandbox/live)

Required Environment Variables:
- PAYPAL_CLIENT_ID
- PAYPAL_SECRET
- PAYPAL_WEBHOOK_ID
- PAYPAL_ENV (sandbox|live)
"""

import os
import logging
import httpx
import hashlib
import base64
import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple

from .config import TOKEN_PACKS, PAYPAL_CONFIG, PAYPAL_CAPTURE_COMPLETED_EVENT
from .models import AIPurchase, PayPalEvent

logger = logging.getLogger(__name__)


class PayPalTokenService:
    """PayPal service for token pack purchases."""
    
    def __init__(self, db):
        self.db = db
        self._access_token = None
        self._token_expires = None
    
    @property
    def env(self) -> str:
        """Get current PayPal environment (sandbox/live)."""
        return os.environ.get("PAYPAL_ENV", "sandbox")
    
    @property
    def api_base(self) -> str:
        """Get API base URL for current environment."""
        return PAYPAL_CONFIG[self.env]["api_base"]
    
    @property
    def client_id(self) -> str:
        return os.environ.get("PAYPAL_CLIENT_ID", "")
    
    @property
    def client_secret(self) -> str:
        return os.environ.get("PAYPAL_SECRET", "")
    
    @property
    def webhook_id(self) -> str:
        return os.environ.get("PAYPAL_WEBHOOK_ID", "")
    
    async def get_access_token(self) -> str:
        """Get or refresh OAuth access token."""
        now = datetime.now(timezone.utc)
        
        # Check if we have a valid cached token
        if self._access_token and self._token_expires and now < self._token_expires:
            return self._access_token
        
        # Get new token
        async with httpx.AsyncClient() as client:
            auth = base64.b64encode(
                f"{self.client_id}:{self.client_secret}".encode()
            ).decode()
            
            response = await client.post(
                f"{self.api_base}/v1/oauth2/token",
                headers={
                    "Authorization": f"Basic {auth}",
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                data="grant_type=client_credentials"
            )
            
            if response.status_code != 200:
                logger.error(f"PayPal auth failed: {response.text}")
                raise Exception("Failed to authenticate with PayPal")
            
            data = response.json()
            self._access_token = data["access_token"]
            # Token expires in ~9 hours, we'll refresh at 8
            from datetime import timedelta
            self._token_expires = now + timedelta(hours=8)
            
            return self._access_token
    
    async def create_order(
        self,
        user_id: str,
        pack_id: str,
        purchase_id: str,
        return_url: str,
        cancel_url: str
    ) -> Dict[str, Any]:
        """
        Create a PayPal order for a token pack purchase.
        
        Args:
            user_id: User making the purchase
            pack_id: Token pack ID (starter/power/pro)
            purchase_id: Our internal purchase ID for tracking
            return_url: URL to redirect after approval
            cancel_url: URL to redirect on cancel
            
        Returns:
            Dict with order_id and approval_url
        """
        pack = TOKEN_PACKS.get(pack_id)
        if not pack:
            raise ValueError(f"Invalid pack_id: {pack_id}")
        
        amount = pack["price_usd"]
        description = f"AI Token Pack - {pack['name']} ({pack['tokens']} tokens)"
        
        access_token = await self.get_access_token()
        
        order_data = {
            "intent": "CAPTURE",
            "purchase_units": [{
                "reference_id": purchase_id,
                "custom_id": f"{user_id}|{pack_id}|{purchase_id}",
                "description": description,
                "amount": {
                    "currency_code": "USD",
                    "value": f"{amount:.2f}"
                }
            }],
            "payment_source": {
                "paypal": {
                    "experience_context": {
                        "payment_method_preference": "IMMEDIATE_PAYMENT_REQUIRED",
                        "brand_name": "Covered Call Engine",
                        "locale": "en-US",
                        "landing_page": "LOGIN",
                        "user_action": "PAY_NOW",
                        "return_url": return_url,
                        "cancel_url": cancel_url
                    }
                }
            }
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.api_base}/v2/checkout/orders",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                    "PayPal-Request-Id": purchase_id  # Idempotency key
                },
                json=order_data
            )
            
            if response.status_code not in [200, 201]:
                logger.error(f"PayPal order creation failed: {response.text}")
                raise Exception(f"Failed to create PayPal order: {response.text}")
            
            result = response.json()
            
            # Find approval URL
            approval_url = None
            for link in result.get("links", []):
                if link.get("rel") == "payer-action":
                    approval_url = link.get("href")
                    break
            
            return {
                "order_id": result["id"],
                "status": result["status"],
                "approval_url": approval_url
            }
    
    async def capture_order(self, order_id: str) -> Dict[str, Any]:
        """
        Capture a PayPal order after user approval.
        
        This is called when user returns from PayPal approval flow.
        """
        access_token = await self.get_access_token()
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.api_base}/v2/checkout/orders/{order_id}/capture",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                }
            )
            
            if response.status_code not in [200, 201]:
                logger.error(f"PayPal capture failed: {response.text}")
                raise Exception(f"Failed to capture PayPal order: {response.text}")
            
            return response.json()
    
    async def verify_webhook_signature(
        self,
        headers: Dict[str, str],
        body: bytes
    ) -> bool:
        """
        Verify PayPal webhook signature.
        
        Args:
            headers: Request headers containing PayPal signature info
            body: Raw request body
            
        Returns:
            True if signature is valid
        """
        if not self.webhook_id:
            logger.warning("PAYPAL_WEBHOOK_ID not configured, skipping verification")
            return True  # In development, might skip
        
        access_token = await self.get_access_token()
        
        # Extract signature headers
        transmission_id = headers.get("paypal-transmission-id", "")
        transmission_time = headers.get("paypal-transmission-time", "")
        cert_url = headers.get("paypal-cert-url", "")
        auth_algo = headers.get("paypal-auth-algo", "")
        transmission_sig = headers.get("paypal-transmission-sig", "")
        
        if not all([transmission_id, transmission_time, transmission_sig]):
            logger.warning("Missing PayPal webhook signature headers")
            return False
        
        verification_data = {
            "auth_algo": auth_algo,
            "cert_url": cert_url,
            "transmission_id": transmission_id,
            "transmission_sig": transmission_sig,
            "transmission_time": transmission_time,
            "webhook_id": self.webhook_id,
            "webhook_event": json.loads(body.decode())
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.api_base}/v1/notifications/verify-webhook-signature",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                },
                json=verification_data
            )
            
            if response.status_code != 200:
                logger.error(f"Webhook verification failed: {response.text}")
                return False
            
            result = response.json()
            return result.get("verification_status") == "SUCCESS"
    
    async def process_webhook(
        self,
        event_id: str,
        event_type: str,
        resource: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """
        Process a PayPal webhook event.
        
        Implements idempotency - same event won't be processed twice.
        
        Args:
            event_id: PayPal event ID
            event_type: Event type (e.g., PAYMENT.CAPTURE.COMPLETED)
            resource: Event resource data
            
        Returns:
            Tuple of (processed, message)
        """
        now = datetime.now(timezone.utc)
        
        # Check idempotency - has this event been processed?
        existing = await self.db.paypal_events.find_one({"event_id": event_id})
        if existing and existing.get("processed"):
            logger.info(f"Event {event_id} already processed, skipping")
            return True, "Event already processed"
        
        # Only process capture completed events
        if event_type != PAYPAL_CAPTURE_COMPLETED_EVENT:
            logger.info(f"Ignoring event type: {event_type}")
            return True, f"Event type {event_type} ignored"
        
        # Extract capture details
        capture_id = resource.get("id")
        status = resource.get("status")
        amount = resource.get("amount", {})
        currency = amount.get("currency_code")
        amount_value = float(amount.get("value", 0))
        
        # Validate status
        if status != "COMPLETED":
            logger.warning(f"Capture status is {status}, not COMPLETED")
            return False, f"Capture status {status} not valid"
        
        # Validate currency
        if currency != "USD":
            logger.warning(f"Currency {currency} is not USD")
            return False, "Only USD payments accepted"
        
        # Extract custom_id to get our purchase details
        custom_id = resource.get("custom_id", "")
        if not custom_id:
            # Try to get from supplementary_data
            supplementary = resource.get("supplementary_data", {})
            related_ids = supplementary.get("related_ids", {})
            custom_id = related_ids.get("custom_id", "")
        
        if not custom_id:
            logger.error("No custom_id found in capture resource")
            return False, "Missing custom_id"
        
        # Parse custom_id: user_id|pack_id|purchase_id
        parts = custom_id.split("|")
        if len(parts) != 3:
            logger.error(f"Invalid custom_id format: {custom_id}")
            return False, "Invalid custom_id format"
        
        user_id, pack_id, purchase_id = parts
        
        # Get pack details
        pack = TOKEN_PACKS.get(pack_id)
        if not pack:
            logger.error(f"Unknown pack_id: {pack_id}")
            return False, f"Unknown pack: {pack_id}"
        
        # Validate amount matches expected price
        expected_amount = pack["price_usd"]
        if abs(amount_value - expected_amount) > 0.01:
            logger.error(f"Amount mismatch: got {amount_value}, expected {expected_amount}")
            return False, f"Amount mismatch: {amount_value} != {expected_amount}"
        
        # Find and validate purchase record
        purchase = await self.db.ai_purchases.find_one({"purchase_id": purchase_id})
        if not purchase:
            logger.error(f"Purchase not found: {purchase_id}")
            return False, f"Purchase not found: {purchase_id}"
        
        if purchase.get("status") == "completed":
            logger.info(f"Purchase {purchase_id} already completed")
            return True, "Purchase already completed"
        
        # Store event for idempotency BEFORE crediting
        await self.db.paypal_events.update_one(
            {"event_id": event_id},
            {
                "$set": {
                    "event_id": event_id,
                    "capture_id": capture_id,
                    "event_type": event_type,
                    "processed": False,  # Will set to True after credit
                    "raw_data": resource
                },
                "$setOnInsert": {
                    "created_at": now.isoformat()
                }
            },
            upsert=True
        )
        
        # Credit tokens to user wallet
        from .wallet_service import WalletService
        wallet_service = WalletService(self.db)
        
        tokens_to_credit = pack["tokens"]
        await wallet_service.credit_tokens(
            user_id=user_id,
            tokens=tokens_to_credit,
            source="purchase",
            request_id=purchase_id,
            details={
                "pack_id": pack_id,
                "pack_name": pack["name"],
                "amount_usd": amount_value,
                "paypal_capture_id": capture_id,
                "paypal_event_id": event_id
            }
        )
        
        # Mark purchase as completed
        await self.db.ai_purchases.update_one(
            {"purchase_id": purchase_id},
            {
                "$set": {
                    "status": "completed",
                    "completed_at": now.isoformat(),
                    "paypal_capture_id": capture_id
                }
            }
        )
        
        # Mark event as processed
        await self.db.paypal_events.update_one(
            {"event_id": event_id},
            {"$set": {"processed": True, "processed_at": now.isoformat()}}
        )
        
        logger.info(f"Successfully credited {tokens_to_credit} tokens to user {user_id}")
        return True, f"Credited {tokens_to_credit} tokens"
    
    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Get status of a PayPal order."""
        access_token = await self.get_access_token()
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.api_base}/v2/checkout/orders/{order_id}",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            
            if response.status_code != 200:
                raise Exception(f"Failed to get order: {response.text}")
            
            return response.json()
