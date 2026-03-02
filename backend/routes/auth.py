"""
Authentication routes
"""
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime, timezone
import uuid
import secrets
from datetime import timedelta
from fastapi.responses import RedirectResponse

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import db
from models.schemas import UserCreate, UserResponse, TokenResponse
from utils.auth import hash_password, verify_password, create_token, get_current_user

# Use correct pydantic model for login
from pydantic import BaseModel, EmailStr

import smtplib, ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

async def _send_smtp_email(to_email: str, subject: str, html_content: str):
    """Send email directly via SMTP"""
    import os
    smtp_host = os.environ.get("SMTP_HOST", "smtp.hostinger.com")
    smtp_port = int(os.environ.get("SMTP_PORT", 465))
    smtp_user = os.environ.get("SMTP_USERNAME", "contact@coveredcallengine.com")
    smtp_pass = os.environ.get("SMTP_PASSWORD", "")
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"Covered Call Engine <{smtp_user}>"
        msg["To"] = to_email
        msg.attach(MIMEText(html_content, "html"))
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context) as s:
            s.login(smtp_user, smtp_pass)
            s.sendmail(smtp_user, to_email, msg.as_string())
        import logging; logging.info(f"Email sent to {to_email}: {subject}")
        return True
    except Exception as e:
        import logging; logging.error(f"SMTP error: {e}")
        return False



class UserLogin(BaseModel):
    email: EmailStr
    password: str

auth_router = APIRouter(tags=["Authentication"])


@auth_router.post("/register", response_model=TokenResponse)
async def register(user_data: UserCreate):
    """Register a new user"""
    # Check if user exists
    existing = await db.users.find_one({"email": user_data.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Create user
    user_id = str(uuid.uuid4())
    user = {
        "id": user_id,
        "email": user_data.email,
        "name": user_data.name,
        "password": hash_password(user_data.password),
        "is_admin": False,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.users.insert_one(user)
    
    # Generate token
    token = create_token(user_id, user_data.email)
    
    # Send activation email async (non-blocking)
    try:
        import asyncio
        asyncio.create_task(_send_activation_email(user))
    except Exception:
        pass

    return TokenResponse(
        access_token=token,
        user=UserResponse(
            id=user_id,
            email=user_data.email,
            name=user_data.name,
            is_admin=False,
            created_at=user["created_at"]  # Already a string (isoformat)
        )
    )


@auth_router.post("/login", response_model=TokenResponse)
async def login(credentials: UserLogin):
    """Login user and return token"""
    user = await db.users.find_one({"email": credentials.email})
    if not user or not verify_password(credentials.password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    # Include role in token for backend authorization
    token = create_token(
        user["id"], 
        user["email"], 
        user.get("is_admin", False),
        user.get("role")
    )
    
    created_at = user.get("created_at")
    # Ensure created_at is a string
    if isinstance(created_at, datetime):
        created_at = created_at.isoformat()
    
    return TokenResponse(
        access_token=token,
        user=UserResponse(
            id=user["id"],
            email=user["email"],
            name=user["name"],
            is_admin=user.get("is_admin", False),
            role=user.get("role"),
            is_support_staff=user.get("is_support_staff", False),
            is_tester=user.get("is_tester", False),
            permissions=user.get("permissions", []),
            created_at=created_at
        )
    )


@auth_router.get("/me", response_model=UserResponse)
async def get_me(user: dict = Depends(get_current_user)):
    """Get current user info"""
    created_at = user.get("created_at")
    # Ensure created_at is a string
    if isinstance(created_at, datetime):
        created_at = created_at.isoformat()
    
    return UserResponse(
        id=user["id"],
        email=user["email"],
        name=user["name"],
        is_admin=user.get("is_admin", False),
        role=user.get("role"),
        is_support_staff=user.get("is_support_staff", False),
        is_tester=user.get("is_tester", False),
        permissions=user.get("permissions", []),
        created_at=created_at
    )


class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


async def _send_activation_email(user: dict):
    import secrets, os
    from datetime import timedelta
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    from database import db as _db
    await _db.activation_tokens.insert_one({
        "token": token, "user_id": user["id"], "email": user["email"],
        "expires_at": expires, "used": False,
        "created_at": datetime.now(timezone.utc).isoformat()
    })
    base_url = os.environ.get("FRONTEND_URL", "https://coveredcallengine.com")
    activate_url = f"{base_url}/api/auth/activate?token={token}"
    try:
        await _send_smtp_email(
            to_email=user["email"],
            subject="Activate Your Account - Covered Call Engine",
            html=f"""<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;background:#1a1a2e;color:#fff;padding:40px;border-radius:12px;">
                <h1 style="color:#00d4aa;">Covered Call Engine</h1>
                <h2>Activate Your Account</h2>
                <p style="color:#ccc;">Hi {user.get('name','there')}, welcome! Please activate your account:</p>
                <div style="text-align:center;margin:32px 0;">
                    <a href="{activate_url}" style="background:#00d4aa;color:#000;padding:14px 32px;border-radius:8px;text-decoration:none;font-weight:bold;font-size:16px;">Activate My Account</a>
                </div>
                <p style="color:#999;font-size:14px;">This link expires in 24 hours.</p>
                <p style="color:#999;font-size:12px;border-top:1px solid #333;padding-top:16px;">Or copy: <a href="{activate_url}" style="color:#00d4aa;">{activate_url}</a></p>
            </div>"""
        )
    except Exception as e:
        import logging; logging.error(f"Activation email error: {e}")


@auth_router.post("/forgot-password")
async def forgot_password(request: ForgotPasswordRequest):
    import secrets, os
    from datetime import timedelta
    from database import db as _db
    user = await _db.users.find_one({"email": request.email})
    if not user:
        return {"message": "If that email exists, a reset link has been sent."}
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    await _db.password_reset_tokens.insert_one({
        "token": token, "user_id": user["id"], "email": user["email"],
        "expires_at": expires, "used": False,
        "created_at": datetime.now(timezone.utc).isoformat()
    })
    base_url = os.environ.get("FRONTEND_URL", "https://coveredcallengine.com")
    reset_url = f"{base_url}/reset-password?token={token}"
    try:
        await _send_smtp_email(
            to_email=user["email"],
            subject="Reset Your Password - Covered Call Engine",
            html=f"""<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;background:#1a1a2e;color:#fff;padding:40px;border-radius:12px;">
                <h1 style="color:#00d4aa;">Covered Call Engine</h1>
                <h2>Password Reset Request</h2>
                <p style="color:#ccc;">Hi {user.get('name','there')}, click below to reset your password:</p>
                <div style="text-align:center;margin:32px 0;">
                    <a href="{reset_url}" style="background:#00d4aa;color:#000;padding:14px 32px;border-radius:8px;text-decoration:none;font-weight:bold;font-size:16px;">Reset My Password</a>
                </div>
                <p style="color:#999;font-size:14px;">This link expires in 1 hour. If you didn't request this, ignore this email.</p>
                <p style="color:#999;font-size:12px;border-top:1px solid #333;padding-top:16px;">Or copy: <a href="{reset_url}" style="color:#00d4aa;">{reset_url}</a></p>
            </div>"""
        )
        return {"message": "If that email exists, a reset link has been sent."}
    except Exception as e:
        import logging; logging.error(f"Reset email error: {e}")
        raise HTTPException(status_code=500, detail="Failed to send reset email. Please try again later.")


@auth_router.post("/reset-password")
async def reset_password(request: ResetPasswordRequest):
    from database import db as _db
    token_doc = await _db.password_reset_tokens.find_one({"token": request.token, "used": False})
    if not token_doc:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link.")
    if datetime.now(timezone.utc) > datetime.fromisoformat(token_doc["expires_at"]):
        raise HTTPException(status_code=400, detail="Reset link has expired. Please request a new one.")
    await _db.users.update_one(
        {"id": token_doc["user_id"]},
        {"$set": {"password": hash_password(request.new_password)}}
    )
    await _db.password_reset_tokens.update_one({"token": request.token}, {"$set": {"used": True}})
    return {"message": "Password reset successfully. You can now log in."}


@auth_router.post("/resend-activation")
async def resend_activation(request: ForgotPasswordRequest):
    from database import db as _db
    user = await _db.users.find_one({"email": request.email})
    if not user:
        return {"message": "If that email exists, an activation link has been sent."}
    if user.get("email_verified"):
        return {"message": "Account already activated."}
    await _send_activation_email(user)
    return {"message": "Activation email sent. Please check your inbox."}


@auth_router.get("/activate")
async def activate_account(token: str):
    import os
    from fastapi.responses import RedirectResponse
    from database import db as _db
    base_url = os.environ.get("FRONTEND_URL", "https://coveredcallengine.com")
    token_doc = await _db.activation_tokens.find_one({"token": token, "used": False})
    if not token_doc:
        return RedirectResponse(url=f"{base_url}/login?error=invalid_token")
    if datetime.now(timezone.utc) > datetime.fromisoformat(token_doc["expires_at"]):
        return RedirectResponse(url=f"{base_url}/login?error=token_expired")
    await _db.users.update_one(
        {"id": token_doc["user_id"]},
        {"$set": {"email_verified": True, "activated_at": datetime.now(timezone.utc).isoformat()}}
    )
    await _db.activation_tokens.update_one({"token": token}, {"$set": {"used": True}})
    return RedirectResponse(url=f"{base_url}/login?activated=true")
