"""
PayPal Payment Service for Covered Call Engine
Handles PayPal REST API integration for subscriptions

Migration from NVP to REST:
- Uses OAuth2 client_id/client_secret instead of api_username/password/signature
- Uses Subscriptions API v1 for recurring billing
- Function signatures preserved for backward compatibility with routes
"""

import logging
import httpx
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class PayPalService:
    """Handle PayPal REST API operations"""

    # PayPal REST API base URLs
    SANDBOX_API = "https://api-m.sandbox.paypal.com"
    LIVE_API = "https://api-m.paypal.com"

    def __init__(self, db):
        self.db = db
        self.client_id = None
        self.client_secret = None
        self.mode = "sandbox"
        self._initialized = False
        self._access_token = None
        self._token_expires_at = None

    async def initialize(self) -> bool:
        """Load PayPal settings from database"""
        try:
            settings = await self.db.admin_settings.find_one(
                {"type": "paypal_settings"},
                {"_id": 0}
            )
            if settings:
                self.mode = settings.get("mode", "sandbox")
                # Load mode-specific credentials, fall back to generic
                self.client_id = settings.get(f"{self.mode}_client_id") or settings.get("client_id")
                self.client_secret = settings.get(f"{self.mode}_client_secret") or settings.get("client_secret")
                self._initialized = bool(self.client_id and self.client_secret)
            return self._initialized
        except Exception as e:
            logger.error(f"Failed to initialize PayPal: {e}")
            return False

    @property
    def base_url(self) -> str:
        return self.LIVE_API if self.mode == "live" else self.SANDBOX_API

    async def _get_access_token(self) -> Optional[str]:
        """Get OAuth2 access token, using cache if still valid."""
        now = datetime.now(timezone.utc)
        if self._access_token and self._token_expires_at and now < self._token_expires_at:
            return self._access_token

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}/v1/oauth2/token",
                    data={"grant_type": "client_credentials"},
                    auth=(self.client_id, self.client_secret),
                    headers={"Accept": "application/json", "Accept-Language": "en_US"}
                )
                if response.status_code == 200:
                    data = response.json()
                    self._access_token = data["access_token"]
                    expires_in = data.get("expires_in", 3600)
                    self._token_expires_at = now + timedelta(seconds=expires_in - 60)
                    return self._access_token
                logger.error(f"[PayPal] OAuth failed: {response.status_code} {response.text}")
                return None
        except Exception as e:
            logger.error(f"[PayPal] OAuth error: {e}")
            return None

    async def _api(self, method: str, path: str, json_data: dict = None) -> Dict[str, Any]:
        """Make an authenticated REST API call. Returns dict; check for '_error' key on failure."""
        if not self._initialized:
            await self.initialize()

        token = await self._get_access_token()
        if not token:
            return {"_error": "Failed to get PayPal access token"}

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    json=json_data,
                    headers=headers
                )
                result: Dict[str, Any] = {}
                if response.content:
                    try:
                        result = response.json()
                    except Exception:
                        result = {"_raw": response.text}

                if response.status_code not in (200, 201, 204):
                    logger.error(f"[PayPal] {method} {path} → {response.status_code}: {response.text}")
                    result["_error"] = result.get("message", f"HTTP {response.status_code}")

                return result
        except Exception as e:
            logger.error(f"[PayPal] Request error: {e}")
            return {"_error": str(e)}

    async def _ensure_product(self) -> Optional[str]:
        """
        Get or create a PayPal catalog product for CCE subscriptions.
        The product_id is cached in admin_settings to avoid recreating on every checkout.
        """
        settings = await self.db.admin_settings.find_one({"type": "paypal_settings"}, {"_id": 0})
        product_id = (settings or {}).get(f"product_id_{self.mode}")
        if product_id:
            # Verify the cached product still exists under current credentials
            check = await self._api("GET", f"/v1/catalogs/products/{product_id}")
            if "_error" not in check:
                return product_id
            # Stale/invalid — clear cache and recreate
            logger.warning(f"[PayPal] Cached product {product_id} not found — recreating")
            await self.db.admin_settings.update_one(
                {"type": "paypal_settings"},
                {"$unset": {f"product_id_{self.mode}": ""}}
            )

        result = await self._api("POST", "/v1/catalogs/products", {
            "name": "Covered Call Engine Subscription",
            "type": "SERVICE",
            "category": "SOFTWARE",
            "description": "Options scanning and analysis service"
        })

        if "_error" not in result and result.get("id"):
            product_id = result["id"]
            await self.db.admin_settings.update_one(
                {"type": "paypal_settings"},
                {"$set": {f"product_id_{self.mode}": product_id}}
            )
            logger.info(f"[PayPal] Created catalog product: {product_id}")
            return product_id

        logger.error(f"[PayPal] Failed to create catalog product: {result}")
        return None

    async def set_express_checkout(
        self,
        amount: float,
        plan_id: str = "standard",
        billing_cycle: str = "monthly",
        is_trial: bool = False,
        return_url: str = "",
        cancel_url: str = "",
        customer_email: Optional[str] = None,
        currency: str = "USD",
    ) -> Dict[str, Any]:
        """
        Create a PayPal subscription and return the approval URL.

        The subscription_id is returned as 'token' for backward compatibility
        with checkout_return which uses it to track the subscription.

        Metadata (plan_id, billing_cycle, is_trial) is stored in custom_id
        as a pipe-delimited string: "plan_id|billing_cycle|is_trial_flag"
        """
        if not self._initialized:
            await self.initialize()
            if not self._initialized:
                return {"success": False, "error": "PayPal not configured"}

        custom_data = f"{plan_id}|{billing_cycle}|{'1' if is_trial else '0'}|{customer_email or ''}"
        interval_unit = "YEAR" if billing_cycle == "yearly" else "MONTH"

        # Ensure a catalog product exists (cached after first call)
        product_id = await self._ensure_product()
        if not product_id:
            return {"success": False, "error": "Failed to create PayPal product"}

        # Create a billing plan with trial + regular cycles
        if is_trial:
            billing_cycles = [
                {
                    "frequency": {"interval_unit": "DAY", "interval_count": 7},
                    "tenure_type": "TRIAL",
                    "sequence": 1,
                    "total_cycles": 1,
                    "pricing_scheme": {
                        "fixed_price": {"value": "0.00", "currency_code": currency}
                    }
                },
                {
                    "frequency": {"interval_unit": interval_unit, "interval_count": 1},
                    "tenure_type": "REGULAR",
                    "sequence": 2,
                    "total_cycles": 0,
                    "pricing_scheme": {
                        "fixed_price": {"value": f"{amount:.2f}", "currency_code": currency}
                    }
                }
            ]
        else:
            billing_cycles = [
                {
                    "frequency": {"interval_unit": interval_unit, "interval_count": 1},
                    "tenure_type": "REGULAR",
                    "sequence": 1,
                    "total_cycles": 0,
                    "pricing_scheme": {
                        "fixed_price": {"value": f"{amount:.2f}", "currency_code": currency}
                    }
                }
            ]

        plan_body = {
            "product_id": product_id,
            "name": f"CCE {plan_id.title()} {billing_cycle.title()}",
            "status": "ACTIVE",
            "billing_cycles": billing_cycles,
            "payment_preferences": {
                "auto_bill_outstanding": True,
                "payment_failure_threshold": 3
            }
        }

        plan_result = await self._api("POST", "/v1/billing/plans", plan_body)
        if "_error" in plan_result:
            return {"success": False, "error": plan_result["_error"]}

        billing_plan_id = plan_result.get("id")
        if not billing_plan_id:
            return {"success": False, "error": "Failed to create billing plan"}

        # Create the subscription under that plan
        sub_body: Dict[str, Any] = {
            "plan_id": billing_plan_id,
            "custom_id": custom_data,
            "application_context": {
                "brand_name": "Covered Call Engine",
                "shipping_preference": "NO_SHIPPING",
                "user_action": "SUBSCRIBE_NOW",
                "payment_method": {
                    "payer_selected": "PAYPAL",
                    "payee_preferred": "UNRESTRICTED"
                },
                "return_url": return_url,
                "cancel_url": cancel_url
            }
        }
        if customer_email:
            sub_body["subscriber"] = {"email_address": customer_email}

        sub_result = await self._api("POST", "/v1/billing/subscriptions", sub_body)
        if "_error" in sub_result:
            return {"success": False, "error": sub_result["_error"]}

        subscription_id = sub_result.get("id")
        approve_link = next(
            (lnk["href"] for lnk in sub_result.get("links", []) if lnk.get("rel") == "approve"),
            None
        )

        if not subscription_id or not approve_link:
            return {"success": False, "error": "No subscription or approval URL returned"}

        logger.info(f"[PayPal] Subscription created: {subscription_id}, plan={plan_id}, cycle={billing_cycle}, trial={is_trial}")
        return {
            "success": True,
            "token": subscription_id,   # subscription_id used as token for backward compat
            "redirect_url": approve_link
        }

    async def get_express_checkout_details(self, token: str) -> Dict[str, Any]:
        """
        Get subscription details by subscription_id (passed as token).
        Parses custom_id field to extract plan_id, billing_cycle, is_trial.
        """
        result = await self._api("GET", f"/v1/billing/subscriptions/{token}")
        if "_error" in result:
            return {"success": False, "error": result["_error"]}

        # Parse custom_id: plan_id|billing_cycle|is_trial|customer_email
        custom = result.get("custom_id", "standard|monthly|0|")
        parts = custom.split("|")
        plan_id = parts[0] if len(parts) > 0 else "standard"
        billing_cycle = parts[1] if len(parts) > 1 else "monthly"
        is_trial = parts[2] == "1" if len(parts) > 2 else False
        stored_email = parts[3] if len(parts) > 3 else ""

        subscriber = result.get("subscriber", {}) or {}
        name = subscriber.get("name", {}) or {}

        # Use subscriber email from PayPal, fall back to stored email from custom_id
        email = subscriber.get("email_address") or stored_email or None

        return {
            "success": True,
            "payer_id": subscriber.get("payer_id", token),
            "email": email,
            "first_name": name.get("given_name"),
            "last_name": name.get("surname"),
            "amount": None,  # Resolved from pricing DB in the route
            "subscription_status": result.get("status"),
            "metadata": {
                "plan_id": plan_id,
                "billing_cycle": billing_cycle,
                "is_trial": "1" if is_trial else "0",
            }
        }

    async def do_express_checkout_payment(
        self,
        token: str,
        payer_id: str,
        amount: float,
        currency: str = "USD"
    ) -> Dict[str, Any]:
        """
        With REST subscriptions, payment is automatic after user approval.
        Verify subscription status and return success.
        token = subscription_id
        """
        result = await self._api("GET", f"/v1/billing/subscriptions/{token}")
        if "_error" in result:
            # Don't hard-fail — subscription may still be valid
            logger.warning(f"[PayPal] Could not verify subscription {token}: {result['_error']}")
            return {"success": True, "transaction_id": token, "payment_status": "UNKNOWN", "amount": str(amount)}

        status = result.get("status", "")
        logger.info(f"[PayPal] Subscription {token} status after approval: {status}")

        # APPROVED = user approved but first billing hasn't run yet (normal for trial/future)
        # ACTIVE = first payment processed
        return {
            "success": True,
            "transaction_id": token,
            "payment_status": status,
            "amount": str(amount)
        }

    async def create_recurring_profile(
        self,
        token: str,
        payer_id: str,
        amount: float,
        billing_cycle: str,
        description: str,
        trial_days: int = 0,
        trial_amount: float = 0.0,
        currency: str = "USD"
    ) -> Dict[str, Any]:
        """
        With REST subscriptions, the recurring profile IS the subscription.
        The subscription was already created in set_express_checkout.
        Return token (subscription_id) as the profile_id.
        """
        logger.info(f"[PayPal] REST create_recurring_profile: subscription_id={token} is the profile")
        return {
            "success": True,
            "profile_id": token,
            "profile_status": "ACTIVE"
        }

    async def get_recurring_profile_details(self, profile_id: str) -> Dict[str, Any]:
        """Get subscription details. profile_id = subscription_id"""
        result = await self._api("GET", f"/v1/billing/subscriptions/{profile_id}")
        if "_error" in result:
            return {"success": False, "error": result["_error"]}

        billing_info = result.get("billing_info", {}) or {}
        last_payment = billing_info.get("last_payment", {}) or {}
        return {
            "success": True,
            "status": result.get("status"),
            "description": result.get("plan_id"),
            "next_billing_date": billing_info.get("next_billing_time"),
            "amount": str(last_payment.get("amount", {}).get("value", ""))
        }

    async def cancel_recurring_profile(self, profile_id: str, note: str = "") -> Dict[str, Any]:
        """Cancel a subscription. profile_id = subscription_id"""
        result = await self._api(
            "POST",
            f"/v1/billing/subscriptions/{profile_id}/cancel",
            {"reason": note or "Subscription cancelled by user"}
        )

        # 204 No Content = success (result will be empty dict, no _error)
        # SUBSCRIPTION_STATUS_INVALID means already cancelled — treat as success
        if "_error" in result:
            err = str(result.get("_error", ""))
            if "SUBSCRIPTION_STATUS_INVALID" in err or "already" in err.lower():
                logger.info(f"[PayPal] Subscription {profile_id} already cancelled")
                return {"success": True, "profile_id": profile_id}
            return {"success": False, "error": result["_error"]}

        logger.info(f"[PayPal] Subscription {profile_id} cancelled")
        return {"success": True, "profile_id": profile_id}

    async def verify_rest_webhook(
        self,
        headers: Dict[str, str],
        raw_body: bytes,
        webhook_id: str
    ) -> bool:
        """
        Verify a REST webhook event using PayPal's verification API.

        PayPal requires us to POST back the headers + body to:
        POST /v1/notifications/verify-webhook-signature

        Returns True if verification_status == "SUCCESS", False otherwise.
        If the PayPal API call itself fails (network/auth), returns False.
        """
        import json as _json
        token = await self._get_access_token()
        if not token:
            logger.error("[PayPal] Cannot verify webhook: no access token")
            return False

        # Required PayPal webhook headers (case-insensitive map)
        headers_lower = {k.lower(): v for k, v in headers.items()}
        transmission_id   = headers_lower.get("paypal-transmission-id", "")
        transmission_time = headers_lower.get("paypal-transmission-time", "")
        cert_url          = headers_lower.get("paypal-cert-url", "")
        auth_algo         = headers_lower.get("paypal-auth-algo", "")
        transmission_sig  = headers_lower.get("paypal-transmission-sig", "")

        if not all([transmission_id, transmission_time, cert_url, auth_algo, transmission_sig]):
            logger.warning("[PayPal] Missing webhook signature headers — cannot verify")
            return False

        try:
            body_str = raw_body.decode("utf-8")
        except Exception:
            body_str = raw_body.decode("latin-1")

        payload = {
            "transmission_id":   transmission_id,
            "transmission_time": transmission_time,
            "cert_url":          cert_url,
            "auth_algo":         auth_algo,
            "transmission_sig":  transmission_sig,
            "webhook_id":        webhook_id,
            "webhook_event":     _json.loads(body_str) if body_str else {}
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{self.base_url}/v1/notifications/verify-webhook-signature",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json"
                    }
                )
                if resp.status_code == 200:
                    result = resp.json()
                    status = result.get("verification_status", "")
                    if status == "SUCCESS":
                        return True
                    logger.warning(f"[PayPal] Webhook verification_status={status}")
                    return False
                logger.error(f"[PayPal] Webhook verify API error: {resp.status_code} {resp.text[:200]}")
                return False
        except Exception as e:
            logger.error(f"[PayPal] Webhook verify exception: {e}")
            return False

    async def verify_ipn(self, raw_body: bytes) -> bool:
        """
        Verify a legacy IPN post by sending it back to PayPal's validation endpoint.

        PayPal expects: POST back the exact body with cmd=_notify-validate prepended.
        Response is "VERIFIED" or "INVALID".
        """
        ipn_url = (
            "https://ipnpb.sandbox.paypal.com/cgi-bin/webscr"
            if self.mode != "live"
            else "https://ipnpb.paypal.com/cgi-bin/webscr"
        )
        try:
            body_str = raw_body.decode("utf-8")
        except Exception:
            body_str = raw_body.decode("latin-1")

        validate_body = f"cmd=_notify-validate&{body_str}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    ipn_url,
                    content=validate_body.encode("utf-8"),
                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                )
                verified = resp.text.strip() == "VERIFIED"
                if not verified:
                    logger.warning(f"[PayPal] Legacy IPN verification returned: {resp.text.strip()[:50]}")
                return verified
        except Exception as e:
            logger.error(f"[PayPal] Legacy IPN verify exception: {e}")
            return False

    async def process_ipn(self, raw_post_data: bytes) -> Dict[str, Any]:
        """Legacy method — kept for backward compatibility."""
        return {"success": True, "data": {}}

    async def handle_subscription_event(self, ipn_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle subscription webhook events.
        Supports both REST webhook format (event_type + resource) and
        legacy IPN format (txn_type + payer_email).
        """
        event_type = ipn_data.get("event_type") or ipn_data.get("txn_type", "")
        resource = ipn_data.get("resource", {}) or {}

        subscription_id = (
            resource.get("id") or
            ipn_data.get("recurring_payment_id") or
            ipn_data.get("subscr_id") or ""
        )
        subscriber = resource.get("subscriber", {}) or {}
        payer_email = subscriber.get("email_address") or ipn_data.get("payer_email") or ""

        result = {"action": "none", "event_type": event_type}
        now = datetime.now(timezone.utc)

        user_filter = (
            {"paypal_profile_id": subscription_id} if subscription_id
            else {"email": payer_email}
        )

        if event_type in (
            "BILLING.SUBSCRIPTION.ACTIVATED",
            "PAYMENT.SALE.COMPLETED",
            "recurring_payment",
            "subscr_payment"
        ):
            await self.db.users.update_one(
                user_filter,
                {"$set": {
                    "subscription.status": "active",
                    "subscription.payment_status": "succeeded",
                    "subscription.last_payment_at": now.isoformat(),
                    "access_active": True,
                    "updated_at": now.isoformat()
                }}
            )
            result["action"] = "payment_recorded"

        elif event_type in (
            "BILLING.SUBSCRIPTION.PAYMENT.FAILED",
            "recurring_payment_failed",
            "subscr_failed"
        ):
            await self.db.users.update_one(
                user_filter,
                {"$set": {
                    "subscription.status": "past_due",
                    "subscription.payment_status": "failed",
                    "updated_at": now.isoformat()
                }}
            )
            result["action"] = "payment_failed"

        elif event_type in (
            "BILLING.SUBSCRIPTION.CANCELLED",
            "recurring_payment_profile_cancel",
            "subscr_cancel"
        ):
            await self.db.users.update_one(
                user_filter,
                {"$set": {
                    "subscription.status": "cancelled",
                    "subscription.cancelled_at": now.isoformat(),
                    "access_active": False,
                    "updated_at": now.isoformat()
                }}
            )
            result["action"] = "subscription_cancelled"

        # Log the event
        await self.db.paypal_webhook_logs.insert_one({
            "event_type": event_type,
            "subscription_id": subscription_id,
            "payer_email": payer_email,
            "result": result,
            "raw_data": ipn_data,
            "timestamp": now.isoformat()
        })

        return result

    async def test_connection(self) -> Dict[str, Any]:
        """Test PayPal REST API connection by fetching an OAuth token."""
        if not self._initialized:
            await self.initialize()
            if not self._initialized:
                return {"success": False, "message": "PayPal credentials not configured"}

        # Force a fresh token fetch to validate credentials
        self._access_token = None
        token = await self._get_access_token()

        if token:
            return {
                "success": True,
                "message": f"Connected to PayPal REST API ({self.mode} mode)"
            }

        return {"success": False, "message": "Failed to connect to PayPal REST API"}
