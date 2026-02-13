--- backend/routes/admin.py
+++ backend/routes/admin.py
@@
 def _mask_api_key(key: str) -> str:
     """Mask API key for security - show first 8 and last 4 chars"""
     if not key or len(key) <= 12:
         return "****"
     return key[:8] + "..." + key[-4:]
+
+
+def _mask_small(key: str) -> str:
+    """Mask string for UI display - show first 4 and last 2 chars."""
+    if not key:
+        return ""
+    if len(key) <= 6:
+        return "****"
+    return key[:4] + "..." + key[-2:]
@@
 @admin_router.get("/integration-settings")
 async def get_integration_settings(admin: dict = Depends(get_admin_user)):
-    """Get all integration settings (Stripe, Resend, etc.)"""
+    """Get all integration settings (Stripe, Resend, PayPal, etc.)"""
     stripe_settings = await db.admin_settings.find_one({"type": "stripe_settings"}, {"_id": 0})
     email_settings = await db.admin_settings.find_one({"type": "email_settings"}, {"_id": 0})
+    paypal_settings = await db.admin_settings.find_one({"type": "paypal_settings"}, {"_id": 0})
     
     env_resend_key = os.environ.get("RESEND_API_KEY")
     env_stripe_webhook = os.environ.get("STRIPE_WEBHOOK_SECRET")
+
+    paypal_enabled = bool(paypal_settings and paypal_settings.get("enabled"))
+    paypal_mode = (paypal_settings.get("mode") if paypal_settings else None) or "sandbox"
+    paypal_configured = bool(
+        paypal_settings
+        and paypal_settings.get("api_username")
+        and paypal_settings.get("api_password")
+        and paypal_settings.get("api_signature")
+        and paypal_enabled
+    )
     
     return {
         "stripe": {
             "webhook_secret_configured": bool(stripe_settings and stripe_settings.get("webhook_secret")) or bool(env_stripe_webhook),
             "secret_key_configured": bool(stripe_settings and stripe_settings.get("stripe_secret_key"))
         },
         "email": {
             "resend_api_key_configured": bool(email_settings and email_settings.get("resend_api_key")) or bool(env_resend_key),
             "sender_email": email_settings.get("sender_email", "") if email_settings else os.environ.get("SENDER_EMAIL", "")
-        }
+        },
+        "paypal": {
+            "configured": paypal_configured,
+            "enabled": paypal_enabled,
+            "mode": paypal_mode,
+            "api_username_masked": _mask_small(paypal_settings.get("api_username", "")) if paypal_settings else "",
+            "has_api_password": bool(paypal_settings and paypal_settings.get("api_password")),
+            "has_api_signature": bool(paypal_settings and paypal_settings.get("api_signature"))
+        }
     }
@@
 @admin_router.post("/integration-settings")
 async def update_integration_settings(
     stripe_webhook_secret: Optional[str] = Query(None),
     stripe_secret_key: Optional[str] = Query(None),
     resend_api_key: Optional[str] = Query(None),
     sender_email: Optional[str] = Query(None),
+    paypal_enabled: Optional[bool] = Query(None),
+    paypal_mode: Optional[str] = Query(None, description="sandbox or live"),
+    paypal_api_username: Optional[str] = Query(None),
+    paypal_api_password: Optional[str] = Query(None),
+    paypal_api_signature: Optional[str] = Query(None),
     admin: dict = Depends(get_admin_user)
 ):
     """Update integration settings"""
     now = datetime.now(timezone.utc).isoformat()
@@
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
+
+    # PayPal settings (NVP API credentials, sandbox/live mode)
+    if (paypal_enabled is not None or paypal_mode is not None or paypal_api_username is not None
+        or paypal_api_password is not None or paypal_api_signature is not None):
+
+        existing = await db.admin_settings.find_one({"type": "paypal_settings"}, {"_id": 0}) or {}
+        paypal_update = {"type": "paypal_settings", "updated_at": now, "updated_by": admin["email"]}
+
+        if paypal_enabled is not None:
+            paypal_update["enabled"] = paypal_enabled
+        else:
+            paypal_update["enabled"] = existing.get("enabled", True)
+
+        if paypal_mode:
+            if paypal_mode not in ["sandbox", "live"]:
+                raise HTTPException(status_code=400, detail="paypal_mode must be sandbox or live")
+            paypal_update["mode"] = paypal_mode
+        else:
+            paypal_update["mode"] = existing.get("mode", "sandbox")
+
+        if paypal_api_username:
+            paypal_update["api_username"] = paypal_api_username
+        else:
+            paypal_update["api_username"] = existing.get("api_username", "")
+
+        # Only overwrite secrets if provided
+        if paypal_api_password:
+            paypal_update["api_password"] = paypal_api_password
+        else:
+            if "api_password" in existing:
+                paypal_update["api_password"] = existing["api_password"]
+
+        if paypal_api_signature:
+            paypal_update["api_signature"] = paypal_api_signature
+        else:
+            if "api_signature" in existing:
+                paypal_update["api_signature"] = existing["api_signature"]
+
+        await db.admin_settings.update_one(
+            {"type": "paypal_settings"},
+            {"$set": paypal_update},
+            upsert=True
+        )
     
     # Log action
     await db.audit_logs.insert_one({
         "action": "update_integration_settings",
         "admin_id": admin["id"],
         "details": {
             "stripe_updated": stripe_webhook_secret is not None or stripe_secret_key is not None,
-            "email_updated": resend_api_key is not None or sender_email is not None
+            "email_updated": resend_api_key is not None or sender_email is not None,
+            "paypal_updated": paypal_enabled is not None or paypal_mode is not None or paypal_api_username is not None or paypal_api_password is not None or paypal_api_signature is not None
         },
         "timestamp": now
     })
     
     return {"message": "Integration settings updated"}
