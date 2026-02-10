"""
Plan Resolver - Resolves user's subscription plan from existing system

This module reads the user's plan from the existing subscription system
without modifying any existing collections or schemas.

Rules:
- Plans control ONLY the monthly free token grant amount
- Plans do NOT control AI access (that's entitlements)
- Default to 'basic' (2,000 tokens) if plan cannot be determined
"""

import logging
from typing import Optional, Tuple
from datetime import datetime, timezone

from .config import PLAN_FREE_TOKENS

logger = logging.getLogger(__name__)


async def resolve_user_plan(db, user_id: str) -> Tuple[str, int]:
    """
    Resolve user's subscription plan and return plan name + free token grant.
    
    Args:
        db: MongoDB database instance
        user_id: User ID to look up
        
    Returns:
        Tuple of (plan_name, free_token_grant)
        
    Note:
        - Does NOT modify any data
        - Returns ('basic', 2000) if plan cannot be determined
    """
    try:
        # Fetch user document
        user = await db.users.find_one({"id": user_id}, {"_id": 0, "subscription": 1})
        
        if not user:
            logger.warning(f"User not found for plan resolution: {user_id}")
            return "default", PLAN_FREE_TOKENS["default"]
        
        subscription = user.get("subscription", {})
        
        if not subscription:
            # No subscription data - might be trial or free
            return "default", PLAN_FREE_TOKENS["default"]
        
        # Check subscription status
        status = subscription.get("status", "").lower()
        
        # If subscription is cancelled, suspended, or lapsed - no free grant
        if status in ["cancelled", "suspended", "past_due", "lapsed"]:
            logger.info(f"User {user_id} has lapsed/cancelled subscription - no free grant")
            return "none", 0
        
        # Get the plan from subscription
        plan = subscription.get("plan", "").lower()
        
        # Normalize plan names (handle variations)
        plan_mapping = {
            "basic": "basic",
            "standard": "standard",
            "premium": "premium",
            "trial": "trial",
            "trialing": "trial",
            "monthly": "standard",  # Legacy mapping
            "yearly": "standard",   # Legacy mapping
            "free": "free"
        }
        
        normalized_plan = plan_mapping.get(plan, "default")
        free_tokens = PLAN_FREE_TOKENS.get(normalized_plan, PLAN_FREE_TOKENS["default"])
        
        logger.debug(f"Resolved plan for user {user_id}: {normalized_plan} ({free_tokens} tokens)")
        
        return normalized_plan, free_tokens
        
    except Exception as e:
        logger.error(f"Error resolving plan for user {user_id}: {e}")
        return "default", PLAN_FREE_TOKENS["default"]


async def get_billing_cycle_dates(db, user_id: str) -> Tuple[Optional[datetime], Optional[datetime]]:
    """
    Get the current billing cycle start and end dates for a user.
    
    Args:
        db: MongoDB database instance
        user_id: User ID
        
    Returns:
        Tuple of (cycle_start, cycle_end) as datetime objects
        Returns (None, None) if no subscription found
    """
    try:
        user = await db.users.find_one(
            {"id": user_id}, 
            {"_id": 0, "subscription": 1}
        )
        
        if not user or not user.get("subscription"):
            return None, None
        
        subscription = user["subscription"]
        
        # Try to get subscription start date
        start_str = subscription.get("subscription_start") or subscription.get("trial_start")
        next_billing_str = subscription.get("next_billing_date")
        
        if not start_str:
            return None, None
        
        # Parse dates
        try:
            # Handle both datetime and string
            if isinstance(start_str, datetime):
                cycle_start = start_str
            else:
                cycle_start = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
        except:
            cycle_start = datetime.now(timezone.utc)
        
        if next_billing_str:
            try:
                if isinstance(next_billing_str, datetime):
                    cycle_end = next_billing_str
                else:
                    cycle_end = datetime.fromisoformat(next_billing_str.replace('Z', '+00:00'))
            except:
                cycle_end = None
        else:
            cycle_end = None
        
        return cycle_start, cycle_end
        
    except Exception as e:
        logger.error(f"Error getting billing cycle for user {user_id}: {e}")
        return None, None


async def is_subscription_active(db, user_id: str) -> bool:
    """
    Check if user has an active subscription.
    
    Args:
        db: MongoDB database instance
        user_id: User ID
        
    Returns:
        True if subscription is active/trialing, False otherwise
    """
    try:
        user = await db.users.find_one(
            {"id": user_id}, 
            {"_id": 0, "subscription.status": 1}
        )
        
        if not user or not user.get("subscription"):
            return False
        
        status = user["subscription"].get("status", "").lower()
        
        # Active statuses
        return status in ["active", "trialing", "trial"]
        
    except Exception as e:
        logger.error(f"Error checking subscription status for user {user_id}: {e}")
        return False
