"""
PayPal Payment Service for Covered Call Engine
Handles PayPal NVP API integration for subscriptions
"""

import os
import logging
import httpx
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from urllib.parse import urlencode, parse_qs

logger = logging.getLogger(__name__)


class PayPalService:
    """Handle PayPal NVP API operations"""
    
    # PayPal NVP API endpoints
    SANDBOX_ENDPOINT = "https://api-3t.sandbox.paypal.com/nvp"
    LIVE_ENDPOINT = "https://api-3t.paypal.com/nvp"
    
    # PayPal redirect URLs
    SANDBOX_REDIRECT = "https://www.sandbox.paypal.com/cgi-bin/webscr"
    LIVE_REDIRECT = "https://www.paypal.com/cgi-bin/webscr"
    
    NVP_VERSION = "204.0"
    
    def __init__(self, db):
        self.db = db
        self.api_username = None
        self.api_password = None
        self.api_signature = None
        self.mode = "sandbox"  # sandbox or live
        self._initialized = False
    
    async def initialize(self) -> bool:
        """Load PayPal settings from database"""
        try:
            settings = await self.db.admin_settings.find_one(
                {"type": "paypal_settings"}, 
                {"_id": 0}
            )
            
            if settings:
                self.api_username = settings.get("api_username")
                self.api_password = settings.get("api_password")
                self.api_signature = settings.get("api_signature")
                self.mode = settings.get("mode", "sandbox")
                self._initialized = bool(self.api_username and self.api_password and self.api_signature)
            
            return self._initialized
        except Exception as e:
            logger.error(f"Failed to initialize PayPal: {e}")
            return False
    
    @property
    def endpoint(self) -> str:
        return self.LIVE_ENDPOINT if self.mode == "live" else self.SANDBOX_ENDPOINT
    
    @property
    def redirect_url(self) -> str:
        return self.LIVE_REDIRECT if self.mode == "live" else self.SANDBOX_REDIRECT
    
    def _get_base_params(self) -> Dict[str, str]:
        """Get base NVP parameters"""
        return {
            "USER": self.api_username,
            "PWD": self.api_password,
            "SIGNATURE": self.api_signature,
            "VERSION": self.NVP_VERSION
        }
    
    async def _make_request(self, params: Dict[str, str]) -> Dict[str, Any]:
        """Make NVP API request to PayPal"""
        if not self._initialized:
            await self.initialize()
            if not self._initialized:
                return {"ACK": "Failure", "L_LONGMESSAGE0": "PayPal not configured"}
        
        all_params = {**self._get_base_params(), **params}
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.endpoint,
                    data=all_params,
                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                )
                
                # Parse NVP response
                result = {}
                for item in response.text.split("&"):
                    if "=" in item:
                        key, value = item.split("=", 1)
                        result[key] = httpx.URL(f"http://x?v={value}").params.get("v", value)
                
                return result
        except Exception as e:
            logger.error(f"PayPal API error: {e}")
            return {"ACK": "Failure", "L_LONGMESSAGE0": str(e)}
    
    async def set_express_checkout(
        self,
        amount: float,
        currency: str = "USD",
        plan_type: str = "monthly",
        return_url: str = "",
        cancel_url: str = "",
        customer_email: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create an Express Checkout session
        Returns token for redirecting user to PayPal
        """
        params = {
            "METHOD": "SetExpressCheckout",
            "PAYMENTREQUEST_0_PAYMENTACTION": "Sale",
            "PAYMENTREQUEST_0_AMT": f"{amount:.2f}",
            "PAYMENTREQUEST_0_CURRENCYCODE": currency,
            "PAYMENTREQUEST_0_DESC": f"Covered Call Engine - {plan_type.title()} Subscription",
            "RETURNURL": return_url,
            "CANCELURL": cancel_url,
            "NOSHIPPING": "1",
            "ALLOWNOTE": "0",
            "BRANDNAME": "Covered Call Engine",
            "CUSTOM": plan_type,  # Store plan type for later
        }
        
        if customer_email:
            params["EMAIL"] = customer_email
        
        result = await self._make_request(params)
        
        if result.get("ACK") == "Success":
            token = result.get("TOKEN")
            redirect = f"{self.redirect_url}?cmd=_express-checkout&token={token}"
            return {
                "success": True,
                "token": token,
                "redirect_url": redirect
            }
        
        return {
            "success": False,
            "error": result.get("L_LONGMESSAGE0", "Unknown error")
        }
    
    async def get_express_checkout_details(self, token: str) -> Dict[str, Any]:
        """Get checkout details after user returns from PayPal"""
        params = {
            "METHOD": "GetExpressCheckoutDetails",
            "TOKEN": token
        }
        
        result = await self._make_request(params)
        
        if result.get("ACK") == "Success":
            return {
                "success": True,
                "payer_id": result.get("PAYERID"),
                "email": result.get("EMAIL"),
                "first_name": result.get("FIRSTNAME"),
                "last_name": result.get("LASTNAME"),
                "amount": result.get("PAYMENTREQUEST_0_AMT"),
                "plan_type": result.get("CUSTOM", "monthly")
            }
        
        return {
            "success": False,
            "error": result.get("L_LONGMESSAGE0", "Unknown error")
        }
    
    async def do_express_checkout_payment(
        self,
        token: str,
        payer_id: str,
        amount: float,
        currency: str = "USD"
    ) -> Dict[str, Any]:
        """Complete the payment after user approval"""
        params = {
            "METHOD": "DoExpressCheckoutPayment",
            "TOKEN": token,
            "PAYERID": payer_id,
            "PAYMENTREQUEST_0_PAYMENTACTION": "Sale",
            "PAYMENTREQUEST_0_AMT": f"{amount:.2f}",
            "PAYMENTREQUEST_0_CURRENCYCODE": currency
        }
        
        result = await self._make_request(params)
        
        if result.get("ACK") == "Success":
            return {
                "success": True,
                "transaction_id": result.get("PAYMENTINFO_0_TRANSACTIONID"),
                "payment_status": result.get("PAYMENTINFO_0_PAYMENTSTATUS"),
                "amount": result.get("PAYMENTINFO_0_AMT")
            }
        
        return {
            "success": False,
            "error": result.get("L_LONGMESSAGE0", "Unknown error")
        }
    
    async def create_recurring_profile(
        self,
        token: str,
        payer_id: str,
        amount: float,
        plan_type: str,
        description: str,
        currency: str = "USD"
    ) -> Dict[str, Any]:
        """Create a recurring payments profile for subscriptions"""
        
        # Determine billing period
        if plan_type == "yearly":
            billing_period = "Year"
            billing_frequency = "1"
        else:
            billing_period = "Month"
            billing_frequency = "1"
        
        # Start date should be now
        start_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        
        params = {
            "METHOD": "CreateRecurringPaymentsProfile",
            "TOKEN": token,
            "PAYERID": payer_id,
            "PROFILESTARTDATE": start_date,
            "DESC": description,
            "BILLINGPERIOD": billing_period,
            "BILLINGFREQUENCY": billing_frequency,
            "AMT": f"{amount:.2f}",
            "CURRENCYCODE": currency,
            "AUTOBILLOUTAMT": "AddToNextBilling"
        }
        
        result = await self._make_request(params)
        
        if result.get("ACK") == "Success":
            return {
                "success": True,
                "profile_id": result.get("PROFILEID"),
                "profile_status": result.get("PROFILESTATUS")
            }
        
        return {
            "success": False,
            "error": result.get("L_LONGMESSAGE0", "Unknown error")
        }
    
    async def get_recurring_profile_details(self, profile_id: str) -> Dict[str, Any]:
        """Get details of a recurring profile"""
        params = {
            "METHOD": "GetRecurringPaymentsProfileDetails",
            "PROFILEID": profile_id
        }
        
        result = await self._make_request(params)
        
        if result.get("ACK") == "Success":
            return {
                "success": True,
                "status": result.get("STATUS"),
                "description": result.get("DESC"),
                "next_billing_date": result.get("NEXTBILLINGDATE"),
                "amount": result.get("AMT")
            }
        
        return {
            "success": False,
            "error": result.get("L_LONGMESSAGE0", "Unknown error")
        }
    
    async def cancel_recurring_profile(self, profile_id: str, note: str = "") -> Dict[str, Any]:
        """Cancel a recurring payments profile"""
        params = {
            "METHOD": "ManageRecurringPaymentsProfileStatus",
            "PROFILEID": profile_id,
            "ACTION": "Cancel",
            "NOTE": note or "Subscription cancelled by user"
        }
        
        result = await self._make_request(params)
        
        if result.get("ACK") == "Success":
            return {
                "success": True,
                "profile_id": result.get("PROFILEID")
            }
        
        return {
            "success": False,
            "error": result.get("L_LONGMESSAGE0", "Unknown error")
        }
    
    async def process_ipn(self, raw_post_data: bytes) -> Dict[str, Any]:
        """
        Process PayPal IPN (Instant Payment Notification)
        Returns parsed and verified IPN data
        """
        # First verify with PayPal
        verify_data = raw_post_data.decode("utf-8") + "&cmd=_notify-validate"
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.redirect_url,
                    content=verify_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                )
                
                if response.text != "VERIFIED":
                    return {"success": False, "error": "IPN verification failed"}
        except Exception as e:
            logger.error(f"IPN verification error: {e}")
            return {"success": False, "error": str(e)}
        
        # Parse IPN data
        ipn_data = parse_qs(raw_post_data.decode("utf-8"))
        ipn_dict = {k: v[0] if len(v) == 1 else v for k, v in ipn_data.items()}
        
        return {
            "success": True,
            "data": ipn_dict
        }
    
    async def handle_subscription_event(self, ipn_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle subscription-related IPN events"""
        txn_type = ipn_data.get("txn_type", "")
        payer_email = ipn_data.get("payer_email")
        recurring_profile_id = ipn_data.get("recurring_payment_id")
        payment_status = ipn_data.get("payment_status")
        
        result = {"action": "none", "event_type": txn_type}
        
        if txn_type == "recurring_payment":
            # Successful recurring payment
            if payment_status == "Completed":
                # Update user subscription
                now = datetime.now(timezone.utc)
                await self.db.users.update_one(
                    {"email": payer_email},
                    {"$set": {
                        "subscription.payment_status": "succeeded",
                        "subscription.last_payment_date": now.isoformat(),
                        "subscription.payment_provider": "paypal",
                        "updated_at": now.isoformat()
                    }}
                )
                result["action"] = "payment_recorded"
        
        elif txn_type == "recurring_payment_failed":
            # Failed recurring payment
            await self.db.users.update_one(
                {"email": payer_email},
                {"$set": {
                    "subscription.status": "past_due",
                    "subscription.payment_status": "failed",
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }}
            )
            result["action"] = "payment_failed"
        
        elif txn_type == "recurring_payment_profile_cancel":
            # Profile cancelled
            await self.db.users.update_one(
                {"paypal_profile_id": recurring_profile_id},
                {"$set": {
                    "subscription.status": "cancelled",
                    "subscription.cancelled_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }}
            )
            result["action"] = "subscription_cancelled"
        
        elif txn_type == "recurring_payment_suspended":
            # Profile suspended
            await self.db.users.update_one(
                {"paypal_profile_id": recurring_profile_id},
                {"$set": {
                    "subscription.status": "suspended",
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }}
            )
            result["action"] = "subscription_suspended"
        
        # Log the event
        await self.db.paypal_webhook_logs.insert_one({
            "txn_type": txn_type,
            "payer_email": payer_email,
            "profile_id": recurring_profile_id,
            "payment_status": payment_status,
            "result": result,
            "raw_data": ipn_data,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        return result
    
    async def test_connection(self) -> Dict[str, Any]:
        """Test PayPal API connection"""
        if not self._initialized:
            await self.initialize()
            if not self._initialized:
                return {
                    "success": False,
                    "message": "PayPal credentials not configured"
                }
        
        # Use GetBalance as a simple API test
        params = {"METHOD": "GetBalance"}
        result = await self._make_request(params)
        
        if result.get("ACK") == "Success":
            return {
                "success": True,
                "message": f"Connected to PayPal ({self.mode} mode)",
                "balance": result.get("L_AMT0", "N/A")
            }
        
        return {
            "success": False,
            "message": result.get("L_LONGMESSAGE0", "Connection failed")
        }
