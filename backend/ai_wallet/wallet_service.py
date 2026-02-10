"""
AI Wallet Service

Core wallet operations including:
- Lazy wallet creation
- Balance queries
- Token deductions (atomic, concurrency-safe)
- Monthly reset logic
- Ledger entries

CRITICAL: All token deductions use MongoDB conditional updates
to make negative balances impossible under any concurrency scenario.
"""

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, Dict, Any

from .config import PLAN_FREE_TOKENS, AI_ACTION_COSTS, ERROR_CODES
from .models import AIWallet, AIWalletResponse, AITokenLedgerEntry, AIGuardResult
from .plan_resolver import resolve_user_plan, get_billing_cycle_dates

logger = logging.getLogger(__name__)


class WalletService:
    """Service for managing AI token wallets."""
    
    def __init__(self, db):
        self.db = db
    
    async def get_or_create_wallet(self, user_id: str) -> Dict[str, Any]:
        """
        Get existing wallet or create one lazily.
        
        Implements lazy wallet creation - wallet is created on first access.
        """
        # Try to get existing wallet
        wallet = await self.db.ai_wallet.find_one(
            {"user_id": user_id},
            {"_id": 0}
        )
        
        if wallet:
            # Check if reset is needed
            wallet = await self._check_and_apply_reset(user_id, wallet)
            return wallet
        
        # Create new wallet
        return await self._create_wallet(user_id)
    
    async def _create_wallet(self, user_id: str) -> Dict[str, Any]:
        """Create a new wallet for user with initial free tokens."""
        now = datetime.now(timezone.utc)
        
        # Resolve plan and get free token grant
        plan_name, free_tokens = await resolve_user_plan(self.db, user_id)
        
        # Get billing cycle for reset dates
        cycle_start, cycle_end = await get_billing_cycle_dates(self.db, user_id)
        
        # If no billing cycle, use monthly from now
        if not cycle_end:
            cycle_end = now + timedelta(days=30)
        
        wallet_doc = {
            "user_id": user_id,
            "org_id": None,
            "free_tokens_remaining": free_tokens,
            "paid_tokens_remaining": 0,
            "monthly_used": 0,
            "last_reset": now.isoformat(),
            "next_reset": cycle_end.isoformat() if cycle_end else (now + timedelta(days=30)).isoformat(),
            "created_at": now.isoformat(),
            "updated_at": now.isoformat()
        }
        
        # Use upsert to handle race conditions
        await self.db.ai_wallet.update_one(
            {"user_id": user_id},
            {"$setOnInsert": wallet_doc},
            upsert=True
        )
        
        # Log the initial grant
        if free_tokens > 0:
            await self._write_ledger_entry(
                user_id=user_id,
                action="MONTHLY_GRANT",
                tokens_total=free_tokens,
                free_tokens=free_tokens,
                paid_tokens=0,
                source="grant",
                request_id=str(uuid.uuid4()),
                details={"plan": plan_name, "type": "initial_creation"}
            )
        
        # Return the created wallet
        return await self.db.ai_wallet.find_one({"user_id": user_id}, {"_id": 0})
    
    async def _check_and_apply_reset(self, user_id: str, wallet: Dict) -> Dict[str, Any]:
        """
        Check if monthly reset is needed and apply it.
        
        Reset logic:
        - Free tokens expire at reset (set to new grant amount)
        - Paid tokens never expire
        - Monthly usage counter resets
        """
        next_reset_str = wallet.get("next_reset")
        if not next_reset_str:
            return wallet
        
        try:
            next_reset = datetime.fromisoformat(next_reset_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return wallet
        
        now = datetime.now(timezone.utc)
        
        if now < next_reset:
            # No reset needed
            return wallet
        
        # Reset is due - apply it
        logger.info(f"Applying monthly reset for user {user_id}")
        
        # Get new plan grant
        plan_name, free_tokens = await resolve_user_plan(self.db, user_id)
        
        # Calculate next reset date (billing cycle aligned)
        _, new_cycle_end = await get_billing_cycle_dates(self.db, user_id)
        if not new_cycle_end or new_cycle_end <= now:
            # Fallback: 30 days from now
            new_cycle_end = now + timedelta(days=30)
        
        # Record expiry of old free tokens if any
        old_free_tokens = wallet.get("free_tokens_remaining", 0)
        if old_free_tokens > 0:
            await self._write_ledger_entry(
                user_id=user_id,
                action="FREE_TOKEN_EXPIRY",
                tokens_total=-old_free_tokens,
                free_tokens=-old_free_tokens,
                paid_tokens=0,
                source="expiry",
                request_id=str(uuid.uuid4()),
                details={"expired_tokens": old_free_tokens}
            )
        
        # Apply reset atomically
        result = await self.db.ai_wallet.update_one(
            {"user_id": user_id, "next_reset": next_reset_str},  # Ensure we have the same state
            {
                "$set": {
                    "free_tokens_remaining": free_tokens,
                    "monthly_used": 0,
                    "last_reset": now.isoformat(),
                    "next_reset": new_cycle_end.isoformat(),
                    "updated_at": now.isoformat()
                }
            }
        )
        
        if result.modified_count > 0 and free_tokens > 0:
            # Log the new grant
            await self._write_ledger_entry(
                user_id=user_id,
                action="MONTHLY_GRANT",
                tokens_total=free_tokens,
                free_tokens=free_tokens,
                paid_tokens=0,
                source="grant",
                request_id=str(uuid.uuid4()),
                details={"plan": plan_name, "type": "monthly_reset"}
            )
        
        # Return updated wallet
        return await self.db.ai_wallet.find_one({"user_id": user_id}, {"_id": 0})
    
    async def get_wallet_response(self, user_id: str) -> AIWalletResponse:
        """Get wallet data formatted for API response."""
        wallet = await self.get_or_create_wallet(user_id)
        
        plan_name, plan_grant = await resolve_user_plan(self.db, user_id)
        ai_enabled = await self.is_ai_enabled(user_id)
        
        free_tokens = wallet.get("free_tokens_remaining", 0)
        paid_tokens = wallet.get("paid_tokens_remaining", 0)
        
        return AIWalletResponse(
            user_id=user_id,
            free_tokens_remaining=free_tokens,
            paid_tokens_remaining=paid_tokens,
            total_tokens=free_tokens + paid_tokens,
            monthly_used=wallet.get("monthly_used", 0),
            next_reset=wallet.get("next_reset"),
            plan=plan_name,
            plan_grant=plan_grant,
            ai_enabled=ai_enabled
        )
    
    async def deduct_tokens(
        self,
        user_id: str,
        tokens_required: int,
        action: str,
        request_id: str
    ) -> AIGuardResult:
        """
        Atomically deduct tokens from wallet.
        
        CRITICAL: This uses MongoDB conditional updates to ensure:
        1. Free tokens are consumed first
        2. Paid tokens are used only after free are exhausted
        3. Negative balances are IMPOSSIBLE
        4. Concurrent requests cannot over-deduct
        
        Returns:
            AIGuardResult with success/failure and details
        """
        # Get current wallet state
        wallet = await self.get_or_create_wallet(user_id)
        
        free_available = wallet.get("free_tokens_remaining", 0)
        paid_available = wallet.get("paid_tokens_remaining", 0)
        total_available = free_available + paid_available
        
        if total_available < tokens_required:
            return AIGuardResult(
                allowed=False,
                error_code="INSUFFICIENT_TOKENS",
                error_message=ERROR_CODES["INSUFFICIENT_TOKENS"],
                remaining_balance=total_available
            )
        
        # Calculate split: free first, then paid
        free_to_use = min(free_available, tokens_required)
        paid_to_use = tokens_required - free_to_use
        
        # Atomic deduction with conditional update
        # This ensures we only deduct if balances haven't changed
        now = datetime.now(timezone.utc)
        
        result = await self.db.ai_wallet.update_one(
            {
                "user_id": user_id,
                "free_tokens_remaining": {"$gte": free_to_use},
                "paid_tokens_remaining": {"$gte": paid_to_use}
            },
            {
                "$inc": {
                    "free_tokens_remaining": -free_to_use,
                    "paid_tokens_remaining": -paid_to_use,
                    "monthly_used": tokens_required
                },
                "$set": {"updated_at": now.isoformat()}
            }
        )
        
        if result.modified_count == 0:
            # Race condition - balances changed between read and write
            # Retry once
            return await self._retry_deduction(user_id, tokens_required, action, request_id)
        
        # Write ledger entry
        await self._write_ledger_entry(
            user_id=user_id,
            action=action,
            tokens_total=-tokens_required,
            free_tokens=-free_to_use,
            paid_tokens=-paid_to_use,
            source="usage",
            request_id=request_id,
            details={"action_type": action}
        )
        
        # Get updated balance
        updated_wallet = await self.db.ai_wallet.find_one({"user_id": user_id}, {"_id": 0})
        new_balance = (
            updated_wallet.get("free_tokens_remaining", 0) + 
            updated_wallet.get("paid_tokens_remaining", 0)
        )
        
        return AIGuardResult(
            allowed=True,
            tokens_deducted=tokens_required,
            free_tokens_used=free_to_use,
            paid_tokens_used=paid_to_use,
            request_id=request_id,
            remaining_balance=new_balance
        )
    
    async def _retry_deduction(
        self,
        user_id: str,
        tokens_required: int,
        action: str,
        request_id: str
    ) -> AIGuardResult:
        """Retry deduction after race condition (max 1 retry per spec)."""
        logger.warning(f"Race condition in token deduction for user {user_id}, retrying...")
        
        # Refresh wallet state
        wallet = await self.get_or_create_wallet(user_id)
        
        free_available = wallet.get("free_tokens_remaining", 0)
        paid_available = wallet.get("paid_tokens_remaining", 0)
        total_available = free_available + paid_available
        
        if total_available < tokens_required:
            return AIGuardResult(
                allowed=False,
                error_code="INSUFFICIENT_TOKENS",
                error_message=ERROR_CODES["INSUFFICIENT_TOKENS"],
                remaining_balance=total_available
            )
        
        # Recalculate split
        free_to_use = min(free_available, tokens_required)
        paid_to_use = tokens_required - free_to_use
        
        now = datetime.now(timezone.utc)
        
        result = await self.db.ai_wallet.update_one(
            {
                "user_id": user_id,
                "free_tokens_remaining": {"$gte": free_to_use},
                "paid_tokens_remaining": {"$gte": paid_to_use}
            },
            {
                "$inc": {
                    "free_tokens_remaining": -free_to_use,
                    "paid_tokens_remaining": -paid_to_use,
                    "monthly_used": tokens_required
                },
                "$set": {"updated_at": now.isoformat()}
            }
        )
        
        if result.modified_count == 0:
            # Still failed - report insufficient tokens
            return AIGuardResult(
                allowed=False,
                error_code="INSUFFICIENT_TOKENS",
                error_message="Token deduction failed after retry. Please try again.",
                remaining_balance=total_available
            )
        
        # Write ledger entry
        await self._write_ledger_entry(
            user_id=user_id,
            action=action,
            tokens_total=-tokens_required,
            free_tokens=-free_to_use,
            paid_tokens=-paid_to_use,
            source="usage",
            request_id=request_id,
            details={"action_type": action, "retry": True}
        )
        
        # Get updated balance
        updated_wallet = await self.db.ai_wallet.find_one({"user_id": user_id}, {"_id": 0})
        new_balance = (
            updated_wallet.get("free_tokens_remaining", 0) + 
            updated_wallet.get("paid_tokens_remaining", 0)
        )
        
        return AIGuardResult(
            allowed=True,
            tokens_deducted=tokens_required,
            free_tokens_used=free_to_use,
            paid_tokens_used=paid_to_use,
            request_id=request_id,
            remaining_balance=new_balance
        )
    
    async def credit_tokens(
        self,
        user_id: str,
        tokens: int,
        source: str,
        request_id: str,
        details: Optional[Dict] = None
    ) -> bool:
        """
        Credit tokens to wallet (for purchases or reversals).
        
        Args:
            user_id: User to credit
            tokens: Number of tokens to add
            source: 'purchase' or 'reversal'
            request_id: Unique request ID for idempotency
            details: Additional details for ledger
            
        Returns:
            True if successful
        """
        now = datetime.now(timezone.utc)
        
        # Ensure wallet exists
        await self.get_or_create_wallet(user_id)
        
        # Credit goes to paid tokens (purchases never expire)
        await self.db.ai_wallet.update_one(
            {"user_id": user_id},
            {
                "$inc": {"paid_tokens_remaining": tokens},
                "$set": {"updated_at": now.isoformat()}
            }
        )
        
        # Write ledger entry
        await self._write_ledger_entry(
            user_id=user_id,
            action="TOKEN_CREDIT",
            tokens_total=tokens,
            free_tokens=0,
            paid_tokens=tokens,
            source=source,
            request_id=request_id,
            details=details or {}
        )
        
        logger.info(f"Credited {tokens} tokens to user {user_id} (source={source})")
        return True
    
    async def reverse_tokens(
        self,
        user_id: str,
        original_request_id: str,
        tokens: int,
        free_tokens_used: int,
        paid_tokens_used: int,
        reason: str
    ) -> bool:
        """
        Reverse a token deduction (for system failures only).
        
        Reverses the exact token split that was originally deducted.
        """
        now = datetime.now(timezone.utc)
        
        # Reverse the exact split
        await self.db.ai_wallet.update_one(
            {"user_id": user_id},
            {
                "$inc": {
                    "free_tokens_remaining": free_tokens_used,
                    "paid_tokens_remaining": paid_tokens_used,
                    "monthly_used": -tokens
                },
                "$set": {"updated_at": now.isoformat()}
            }
        )
        
        # Write reversal ledger entry
        await self._write_ledger_entry(
            user_id=user_id,
            action="TOKEN_REVERSAL",
            tokens_total=tokens,
            free_tokens=free_tokens_used,
            paid_tokens=paid_tokens_used,
            source="reversal",
            request_id=str(uuid.uuid4()),
            details={
                "original_request_id": original_request_id,
                "reason": reason
            }
        )
        
        logger.info(f"Reversed {tokens} tokens for user {user_id} (reason={reason})")
        return True
    
    async def _write_ledger_entry(
        self,
        user_id: str,
        action: str,
        tokens_total: int,
        free_tokens: int,
        paid_tokens: int,
        source: str,
        request_id: str,
        details: Optional[Dict] = None
    ):
        """Write an immutable ledger entry."""
        now = datetime.now(timezone.utc)
        
        entry = {
            "user_id": user_id,
            "org_id": None,
            "action": action,
            "tokens_total": tokens_total,
            "free_tokens": free_tokens,
            "paid_tokens": paid_tokens,
            "source": source,
            "request_id": request_id,
            "timestamp": now.isoformat(),
            "details": details or {}
        }
        
        await self.db.ai_token_ledger.insert_one(entry)
    
    async def get_ledger(self, user_id: str, limit: int = 50) -> list:
        """Get recent ledger entries for user."""
        cursor = self.db.ai_token_ledger.find(
            {"user_id": user_id},
            {"_id": 0}
        ).sort("timestamp", -1).limit(limit)
        
        return await cursor.to_list(length=limit)
    
    async def is_ai_enabled(self, user_id: str) -> bool:
        """Check if AI features are enabled for user."""
        # Check entitlements collection
        entitlement = await self.db.entitlements.find_one(
            {"user_id": user_id},
            {"_id": 0, "ai_enabled": 1}
        )
        
        if entitlement:
            return entitlement.get("ai_enabled", True)
        
        # Default: AI enabled for all users
        return True
    
    async def set_ai_enabled(self, user_id: str, enabled: bool) -> bool:
        """Set AI enabled status for user."""
        now = datetime.now(timezone.utc)
        
        await self.db.entitlements.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "ai_enabled": enabled,
                    "updated_at": now.isoformat()
                },
                "$setOnInsert": {
                    "created_at": now.isoformat()
                }
            },
            upsert=True
        )
        
        return True
    
    def estimate_tokens(self, action: str) -> int:
        """Estimate token cost for an action."""
        return AI_ACTION_COSTS.get(action, AI_ACTION_COSTS["default"])
