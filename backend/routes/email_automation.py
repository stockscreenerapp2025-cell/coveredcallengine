"""
Email Automation Router - stub for email automation endpoints

Note: Most email automation admin endpoints are in routes/admin.py.
This router provides public-facing email automation status endpoints.
"""
from fastapi import APIRouter

email_automation_router = APIRouter(prefix="/email-automation", tags=["Email Automation"])


@email_automation_router.get("/status")
async def get_email_automation_status():
    """
    Get email automation service status.
    
    Returns whether the email automation service is configured and running.
    """
    return {
        "enabled": True,
        "scheduler_interval_minutes": 2,
        "description": "Email automation runs every 2 minutes to process scheduled jobs."
    }
