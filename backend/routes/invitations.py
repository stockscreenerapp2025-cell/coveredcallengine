"""
Invitation Routes for Covered Call Engine
Handles user invitations for support staff and testers
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime, timezone, timedelta
from uuid import uuid4
import secrets
import logging

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import db
from utils.auth import get_admin_user

logger = logging.getLogger(__name__)

invitation_router = APIRouter(prefix="/invitations", tags=["Invitations"])


# ==================== MODELS ====================

class InvitationRequest(BaseModel):
    email: EmailStr
    name: str
    role: str  # 'support_staff' or 'tester'
    environment: str = "production"  # 'test' or 'production'
    message: Optional[str] = None


# Environment URLs
ENVIRONMENT_URLS = {
    "test": "https://cc-screener-1.preview.emergentagent.com",
    "production": "https://coveredcallengine.com"
}


class InvitationResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    status: str
    created_at: str
    expires_at: str


# ==================== ROLE DEFINITIONS ====================

ROLES = {
    "admin": {
        "label": "Administrator",
        "description": "Full access to all features",
        "permissions": ["*"]
    },
    "support_staff": {
        "label": "Support Staff",
        "description": "Access to Support System only",
        "permissions": [
            "support.view_tickets",
            "support.manage_tickets",
            "support.view_kb",
            "support.manage_kb",
            "support.view_stats"
        ]
    },
    "tester": {
        "label": "Beta Tester",
        "description": "Access to test the platform features",
        "permissions": [
            "dashboard.view",
            "screener.view",
            "pmcc.view",
            "simulator.view",
            "portfolio.view"
        ]
    }
}


# ==================== INVITATION ENDPOINTS ====================

@invitation_router.post("/send")
async def send_invitation(
    request: InvitationRequest,
    admin: dict = Depends(get_admin_user)
):
    """
    Send an invitation email to a new user.
    Admin only endpoint.
    """
    # Validate role
    if request.role not in ["support_staff", "tester"]:
        raise HTTPException(status_code=400, detail="Invalid role. Must be 'support_staff' or 'tester'")
    
    # Validate environment
    if request.environment not in ["test", "production"]:
        raise HTTPException(status_code=400, detail="Invalid environment. Must be 'test' or 'production'")
    
    # Check if email already has a pending invitation for this environment
    existing = await db.invitations.find_one({
        "email": request.email.lower(),
        "environment": request.environment,
        "status": "pending"
    })
    if existing:
        raise HTTPException(status_code=400, detail=f"An invitation is already pending for this email in {request.environment}")
    
    # Check if user already exists
    existing_user = await db.users.find_one({"email": request.email.lower()})
    if existing_user:
        raise HTTPException(status_code=400, detail="A user with this email already exists")
    
    # Generate secure invitation token
    token = secrets.token_urlsafe(32)
    invitation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=7)  # 7 days to accept
    
    invitation = {
        "id": invitation_id,
        "email": request.email.lower(),
        "name": request.name,
        "role": request.role,
        "environment": request.environment,
        "token": token,
        "status": "pending",
        "message": request.message,
        "invited_by": admin.get("email"),
        "invited_by_id": admin.get("id"),
        "created_at": now.isoformat(),
        "expires_at": expires_at.isoformat()
    }
    
    await db.invitations.insert_one(invitation)
    
    # Send invitation email
    email_sent = await send_invitation_email(
        to_email=request.email,
        name=request.name,
        role=request.role,
        environment=request.environment,
        token=token,
        message=request.message,
        invited_by=admin.get("name", admin.get("email"))
    )
    
    if email_sent:
        logger.info(f"Invitation sent to {request.email} as {request.role} ({request.environment}) by {admin.get('email')}")
    else:
        logger.warning(f"Failed to send invitation email to {request.email}")
    
    return {
        "success": True,
        "invitation_id": invitation_id,
        "environment": request.environment,
        "email_sent": email_sent,
        "message": f"Invitation sent to {request.email} for {request.environment}"
    }


@invitation_router.get("/list")
async def list_invitations(
    status: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    admin: dict = Depends(get_admin_user)
):
    """
    List all invitations (admin only).
    """
    query = {}
    if status:
        query["status"] = status
    if role:
        query["role"] = role
    
    invitations = await db.invitations.find(
        query,
        {"_id": 0, "token": 0}  # Don't expose token
    ).sort("created_at", -1).to_list(100)
    
    return {"invitations": invitations}


@invitation_router.delete("/{invitation_id}")
async def delete_invitation(
    invitation_id: str,
    admin: dict = Depends(get_admin_user)
):
    """
    Delete an invitation. Pending invitations are revoked, others are fully deleted.
    """
    invitation = await db.invitations.find_one({"id": invitation_id})
    
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    
    if invitation["status"] == "pending":
        # Revoke pending invitations
        await db.invitations.update_one(
            {"id": invitation_id},
            {"$set": {"status": "revoked", "revoked_at": datetime.now(timezone.utc).isoformat()}}
        )
        return {"success": True, "message": "Invitation revoked"}
    else:
        # Delete non-pending invitations
        await db.invitations.delete_one({"id": invitation_id})
        return {"success": True, "message": "Invitation deleted"}


@invitation_router.post("/{invitation_id}/resend")
async def resend_invitation(
    invitation_id: str,
    admin: dict = Depends(get_admin_user)
):
    """
    Resend an invitation email.
    """
    invitation = await db.invitations.find_one({"id": invitation_id}, {"_id": 0})
    
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    
    if invitation["status"] != "pending":
        raise HTTPException(status_code=400, detail="Can only resend pending invitations")
    
    # Extend expiry
    new_expires = datetime.now(timezone.utc) + timedelta(days=7)
    await db.invitations.update_one(
        {"id": invitation_id},
        {"$set": {"expires_at": new_expires.isoformat()}}
    )
    
    # Resend email
    email_sent = await send_invitation_email(
        to_email=invitation["email"],
        name=invitation["name"],
        role=invitation["role"],
        environment=invitation.get("environment", "production"),
        token=invitation["token"],
        message=invitation.get("message"),
        invited_by=admin.get("name", admin.get("email"))
    )
    
    return {"success": True, "email_sent": email_sent}


# ==================== PUBLIC ACCEPT ENDPOINT ====================

@invitation_router.get("/verify/{token}")
async def verify_invitation(token: str):
    """
    Verify an invitation token (public endpoint).
    Used when user clicks the invitation link.
    """
    invitation = await db.invitations.find_one(
        {"token": token},
        {"_id": 0, "token": 0}
    )
    
    if not invitation:
        raise HTTPException(status_code=404, detail="Invalid invitation link")
    
    if invitation["status"] != "pending":
        raise HTTPException(status_code=400, detail="This invitation has already been used or revoked")
    
    # Check expiry
    expires_at = datetime.fromisoformat(invitation["expires_at"].replace("Z", "+00:00"))
    if datetime.now(timezone.utc) > expires_at:
        raise HTTPException(status_code=400, detail="This invitation has expired")
    
    return {
        "valid": True,
        "email": invitation["email"],
        "name": invitation["name"],
        "role": invitation["role"],
        "role_label": ROLES.get(invitation["role"], {}).get("label", invitation["role"])
    }


@invitation_router.post("/accept/{token}")
async def accept_invitation(
    token: str,
    password: str = Query(..., min_length=8, description="Password for the new account")
):
    """
    Accept an invitation and create user account (public endpoint).
    """
    from passlib.hash import bcrypt
    
    invitation = await db.invitations.find_one({"token": token}, {"_id": 0})
    
    if not invitation:
        raise HTTPException(status_code=404, detail="Invalid invitation link")
    
    if invitation["status"] != "pending":
        raise HTTPException(status_code=400, detail="This invitation has already been used or revoked")
    
    # Check expiry
    expires_at = datetime.fromisoformat(invitation["expires_at"].replace("Z", "+00:00"))
    if datetime.now(timezone.utc) > expires_at:
        raise HTTPException(status_code=400, detail="This invitation has expired")
    
    # Create user account
    now = datetime.now(timezone.utc).isoformat()
    user_id = str(uuid4())
    
    user = {
        "id": user_id,
        "email": invitation["email"],
        "name": invitation["name"],
        "password": bcrypt.hash(password),
        "role": invitation["role"],
        "is_admin": False,
        "is_support_staff": invitation["role"] == "support_staff",
        "is_tester": invitation["role"] == "tester",
        "permissions": ROLES.get(invitation["role"], {}).get("permissions", []),
        "invited_by": invitation.get("invited_by"),
        "created_at": now,
        "updated_at": now,
        "subscription_status": "active" if invitation["role"] == "tester" else None,
        "subscription_plan": "tester" if invitation["role"] == "tester" else None
    }
    
    await db.users.insert_one(user)
    
    # Update invitation status
    await db.invitations.update_one(
        {"token": token},
        {"$set": {
            "status": "accepted",
            "accepted_at": now,
            "user_id": user_id
        }}
    )
    
    logger.info(f"Invitation accepted: {invitation['email']} as {invitation['role']}")
    
    # Send welcome email with environment-specific login URL
    await send_welcome_email(
        invitation["email"], 
        invitation["name"], 
        invitation["role"],
        invitation.get("environment", "production")
    )
    
    return {
        "success": True,
        "message": "Account created successfully. You can now log in.",
        "email": invitation["email"]
    }


# ==================== ROLES ENDPOINT ====================

@invitation_router.get("/roles")
async def get_available_roles(admin: dict = Depends(get_admin_user)):
    """
    Get available roles for invitations.
    """
    return {
        "roles": [
            {"value": "support_staff", **ROLES["support_staff"]},
            {"value": "tester", **ROLES["tester"]}
        ]
    }


# ==================== EMAIL HELPERS ====================

async def send_invitation_email(
    to_email: str,
    name: str,
    role: str,
    environment: str,
    token: str,
    message: Optional[str],
    invited_by: str
) -> bool:
    """Send invitation email via Resend"""
    try:
        from services.email_service import EmailService
        email_service = EmailService(db)
        
        if not await email_service.initialize():
            logger.warning("Email service not initialized")
            return False
        
        role_info = ROLES.get(role, {})
        role_label = role_info.get("label", role)
        role_description = role_info.get("description", "")
        
        # Build accept URL based on environment
        base_url = ENVIRONMENT_URLS.get(environment, ENVIRONMENT_URLS["production"])
        accept_url = f"{base_url}/accept-invitation?token={token}"
        
        # Environment label for email
        env_label = "Test Environment" if environment == "test" else "Production"
        env_badge_color = "#f59e0b" if environment == "test" else "#10b981"
        
        # Logo URL
        logo_url = "https://customer-assets.emergentagent.com/job_optiontrader-9/artifacts/cg2ri3n1_Logo%20CCE.JPG"
        
        # Custom message section
        custom_message_html = ""
        if message:
            custom_message_html = f"""
            <div style="background-color: #18181b; border-left: 3px solid #10b981; padding: 15px; margin: 20px 0; border-radius: 0 8px 8px 0;">
                <p style="color: #a1a1aa; margin: 0; font-style: italic;">"{message}"</p>
                <p style="color: #71717a; margin: 10px 0 0 0; font-size: 12px;">— {invited_by}</p>
            </div>
            """
        
        html_content = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #09090b; color: #ffffff;">
            <div style="text-align: center; padding: 30px 0;">
                <img src="{logo_url}" alt="Covered Call Engine" style="height: 50px; margin-bottom: 20px;" />
                <h1 style="color: #10b981; margin: 0; font-size: 24px;">You're Invited!</h1>
                <span style="display: inline-block; margin-top: 10px; padding: 4px 12px; background-color: {env_badge_color}20; color: {env_badge_color}; border-radius: 4px; font-size: 12px; font-weight: bold;">
                    {env_label}
                </span>
            </div>
            
            <div style="padding: 30px 20px;">
                <p style="color: #e4e4e7; font-size: 16px; line-height: 1.6;">
                    Hi {name},
                </p>
                
                <p style="color: #a1a1aa; line-height: 1.6;">
                    You've been invited to join <strong style="color: #10b981;">Covered Call Engine</strong> ({env_label}) as a <strong style="color: #ffffff;">{role_label}</strong>.
                </p>
                
                {custom_message_html}
                
                <div style="background-color: #18181b; border-radius: 8px; padding: 20px; margin: 25px 0;">
                    <p style="color: #71717a; margin: 0 0 5px 0; font-size: 12px; text-transform: uppercase;">Your Role</p>
                    <p style="color: #10b981; margin: 0; font-size: 18px; font-weight: bold;">{role_label}</p>
                    <p style="color: #a1a1aa; margin: 10px 0 0 0; font-size: 14px;">{role_description}</p>
                </div>
                
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{accept_url}" style="display: inline-block; background-color: #10b981; color: #ffffff; padding: 14px 32px; text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 16px;">
                        Accept Invitation
                    </a>
                </div>
                
                <p style="color: #71717a; font-size: 12px; text-align: center;">
                    This invitation expires in 7 days.
                </p>
                
                <p style="color: #71717a; font-size: 12px; margin-top: 30px;">
                    If the button doesn't work, copy and paste this link into your browser:<br>
                    <a href="{accept_url}" style="color: #10b981; word-break: break-all;">{accept_url}</a>
                </p>
            </div>
            
            <div style="text-align: center; padding: 20px; border-top: 1px solid #27272a; color: #71717a; font-size: 12px;">
                © 2025 Covered Call Engine. All rights reserved.<br>
                <a href="https://coveredcallengine.com" style="color: #10b981; text-decoration: none;">coveredcallengine.com</a>
            </div>
        </div>
        """
        
        result = await email_service.send_raw_email(
            to_email=to_email,
            subject=f"You're invited to join Covered Call Engine ({env_label}) as {role_label}",
            html_content=html_content
        )
        
        return result.get("status") == "success"
        
    except Exception as e:
        logger.error(f"Failed to send invitation email: {e}")
        return False


async def send_welcome_email(email: str, name: str, role: str, environment: str = "production") -> bool:
    """Send welcome email after invitation is accepted"""
    try:
        from services.email_service import EmailService
        email_service = EmailService(db)
        
        if not await email_service.initialize():
            return False
        
        role_label = ROLES.get(role, {}).get("label", role)
        logo_url = "https://customer-assets.emergentagent.com/job_optiontrader-9/artifacts/cg2ri3n1_Logo%20CCE.JPG"
        
        # Get environment-specific login URL
        login_url = ENVIRONMENT_URLS.get(environment, ENVIRONMENT_URLS["production"]) + "/login"
        
        # Role-specific content
        if role == "support_staff":
            access_info = """
            <p style="color: #a1a1aa; line-height: 1.6;">
                As a Support Staff member, you have access to:
            </p>
            <ul style="color: #a1a1aa; line-height: 1.8;">
                <li>Support ticket management</li>
                <li>AI-assisted response drafting</li>
                <li>Knowledge base management</li>
                <li>Support statistics dashboard</li>
            </ul>
            <p style="color: #a1a1aa; line-height: 1.6;">
                Access the Support Dashboard from the Admin menu after logging in.
            </p>
            """
        else:  # tester
            access_info = """
            <p style="color: #a1a1aa; line-height: 1.6;">
                As a Beta Tester, you have access to:
            </p>
            <ul style="color: #a1a1aa; line-height: 1.8;">
                <li>Dashboard with market opportunities</li>
                <li>Covered Call Screener</li>
                <li>PMCC Screener</li>
                <li>Trade Simulator</li>
                <li>Portfolio Tracker</li>
            </ul>
            <p style="color: #a1a1aa; line-height: 1.6;">
                We'd love your feedback! Please report any issues or suggestions.
            </p>
            """
        
        html_content = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #09090b; color: #ffffff;">
            <div style="text-align: center; padding: 30px 0;">
                <img src="{logo_url}" alt="Covered Call Engine" style="height: 50px; margin-bottom: 20px;" />
                <h1 style="color: #10b981; margin: 0; font-size: 24px;">Welcome to Covered Call Engine!</h1>
            </div>
            
            <div style="padding: 30px 20px;">
                <p style="color: #e4e4e7; font-size: 16px; line-height: 1.6;">
                    Hi {name},
                </p>
                
                <p style="color: #a1a1aa; line-height: 1.6;">
                    Your account has been created successfully. You're now a <strong style="color: #10b981;">{role_label}</strong>.
                </p>
                
                {access_info}
                
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{login_url}" style="display: inline-block; background-color: #10b981; color: #ffffff; padding: 14px 32px; text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 16px;">
                        Log In Now
                    </a>
                </div>
                
                <p style="color: #71717a; font-size: 12px; text-align: center; margin-top: 20px;">
                    💡 Tip: If someone else is logged in, please log out first or use a private/incognito window.
                </p>
            </div>
            
            <div style="text-align: center; padding: 20px; border-top: 1px solid #27272a; color: #71717a; font-size: 12px;">
                © 2025 Covered Call Engine. All rights reserved.<br>
                <a href="https://coveredcallengine.com" style="color: #10b981; text-decoration: none;">coveredcallengine.com</a>
            </div>
        </div>
        """
        
        result = await email_service.send_raw_email(
            to_email=email,
            subject=f"Welcome to Covered Call Engine, {name}!",
            html_content=html_content
        )
        
        return result.get("status") == "success"
        
    except Exception as e:
        logger.error(f"Failed to send welcome email: {e}")
        return False
