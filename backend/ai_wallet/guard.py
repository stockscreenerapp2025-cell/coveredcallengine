"""
AI Guard Service - Pre-execution token guard

Enforces:
- Token balance check before AI execution
- Rate limiting (max calls per minute)
- Action size limits (max tokens per action)
- Concurrency limits (one AI call at a time per user)
- Automatic reversal on system failures (5xx)

IMPORTANT: This guard is the ONLY place where AI execution is gated.
All AI call sites must use this guard at the execution boundary.
"""

import logging
import time
import uuid
import asyncio
from datetime import datetime, timezone
from typing import Optional, Tuple, Callable, Any
from functools import wraps

from .config import RATE_LIMITS, AI_ACTION_COSTS, ERROR_CODES
from .models import AIGuardResult, TokenEstimateResponse
from .wallet_service import WalletService

logger = logging.getLogger(__name__)


class AIGuard:
    """
    AI execution guard that enforces token requirements and abuse prevention.
    
    Usage:
        guard = AIGuard(db)
        result = await guard.check_and_deduct(user_id, "ai_analysis", 200)
        if not result.allowed:
            raise HTTPException(status_code=402, detail=result.error_message)
        
        try:
            # Execute AI call
            response = await ai_service.execute(...)
        except Exception as e:
            if is_system_error(e):
                await guard.reverse(user_id, result)
            raise
    """
    
    def __init__(self, db):
        self.db = db
        self.wallet_service = WalletService(db)
        
        # In-memory rate limiting (per user)
        # Format: {user_id: [(timestamp, request_id), ...]}
        self._rate_limit_cache = {}
        
        # In-memory concurrency tracking
        # Format: {user_id: request_id}
        self._active_requests = {}
        
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()
    
    async def estimate(self, user_id: str, action: str, params: Optional[dict] = None) -> TokenEstimateResponse:
        """
        Estimate token cost for an action without deducting.
        
        Args:
            user_id: User requesting estimate
            action: AI action type
            params: Optional action parameters
            
        Returns:
            TokenEstimateResponse with cost and balance info
        """
        estimated_tokens = self._calculate_tokens(action, params)
        
        wallet = await self.wallet_service.get_or_create_wallet(user_id)
        current_balance = (
            wallet.get("free_tokens_remaining", 0) + 
            wallet.get("paid_tokens_remaining", 0)
        )
        
        return TokenEstimateResponse(
            action=action,
            estimated_tokens=estimated_tokens,
            current_balance=current_balance,
            sufficient_tokens=current_balance >= estimated_tokens
        )
    
    async def check_and_deduct(
        self,
        user_id: str,
        action: str,
        tokens_override: Optional[int] = None
    ) -> AIGuardResult:
        """
        Full guard check: entitlement, rate limit, concurrency, balance, deduction.
        
        This is the main entry point for the guard. It performs all checks
        and atomically deducts tokens if allowed.
        
        Args:
            user_id: User ID
            action: AI action type
            tokens_override: Optional override for token cost
            
        Returns:
            AIGuardResult indicating success/failure
        """
        request_id = str(uuid.uuid4())
        
        # 1. Check AI entitlement
        if not await self.wallet_service.is_ai_enabled(user_id):
            return AIGuardResult(
                allowed=False,
                error_code="AI_DISABLED",
                error_message=ERROR_CODES["AI_DISABLED"],
                request_id=request_id
            )
        
        # 2. Calculate tokens required
        tokens_required = tokens_override or self._calculate_tokens(action, None)
        
        # 3. Check action size limit
        if tokens_required > RATE_LIMITS["max_tokens_per_action"]:
            return AIGuardResult(
                allowed=False,
                error_code="ACTION_TOO_LARGE",
                error_message=ERROR_CODES["ACTION_TOO_LARGE"],
                request_id=request_id
            )
        
        # 4. Check rate limit
        rate_check = await self._check_rate_limit(user_id)
        if not rate_check[0]:
            return AIGuardResult(
                allowed=False,
                error_code="RATE_LIMIT",
                error_message=rate_check[1],
                request_id=request_id
            )
        
        # 5. Check concurrency limit
        concurrency_check = await self._check_concurrency(user_id, request_id)
        if not concurrency_check[0]:
            return AIGuardResult(
                allowed=False,
                error_code="CONCURRENCY_LIMIT",
                error_message=concurrency_check[1],
                request_id=request_id
            )
        
        try:
            # 6. Deduct tokens atomically
            result = await self.wallet_service.deduct_tokens(
                user_id=user_id,
                tokens_required=tokens_required,
                action=action,
                request_id=request_id
            )
            
            if not result.allowed:
                # Release concurrency lock on failure
                await self._release_concurrency(user_id, request_id)
            
            return result
            
        except Exception as e:
            # Release concurrency lock on error
            await self._release_concurrency(user_id, request_id)
            logger.error(f"Token deduction error for user {user_id}: {e}")
            return AIGuardResult(
                allowed=False,
                error_code="WALLET_NOT_FOUND",
                error_message=str(e),
                request_id=request_id
            )
    
    async def release(self, user_id: str, request_id: str):
        """
        Release concurrency lock after AI execution completes.
        
        MUST be called after AI execution, whether successful or not.
        """
        await self._release_concurrency(user_id, request_id)
        
        # Record rate limit hit
        await self._record_rate_limit(user_id, request_id)
    
    async def reverse_on_failure(
        self,
        user_id: str,
        result: AIGuardResult,
        reason: str = "System error"
    ):
        """
        Reverse token deduction on system failure (5xx).
        
        Only call this for server-side errors. User errors should NOT be reversed.
        
        Args:
            user_id: User ID
            result: The original guard result with deduction details
            reason: Reason for reversal
        """
        if not result.allowed or result.tokens_deducted == 0:
            return
        
        await self.wallet_service.reverse_tokens(
            user_id=user_id,
            original_request_id=result.request_id,
            tokens=result.tokens_deducted,
            free_tokens_used=result.free_tokens_used,
            paid_tokens_used=result.paid_tokens_used,
            reason=reason
        )
        
        logger.info(f"Reversed {result.tokens_deducted} tokens for user {user_id}: {reason}")
    
    def _calculate_tokens(self, action: str, params: Optional[dict]) -> int:
        """Calculate token cost for an action."""
        base_cost = AI_ACTION_COSTS.get(action, AI_ACTION_COSTS["default"])
        
        # Could add multipliers based on params here
        # e.g., longer analysis = more tokens
        
        return base_cost
    
    async def _check_rate_limit(self, user_id: str) -> Tuple[bool, str]:
        """Check if user is within rate limits."""
        async with self._lock:
            now = time.time()
            window = 60  # 1 minute window
            max_calls = RATE_LIMITS["max_calls_per_minute"]
            
            # Clean old entries
            if user_id in self._rate_limit_cache:
                self._rate_limit_cache[user_id] = [
                    (ts, rid) for ts, rid in self._rate_limit_cache[user_id]
                    if now - ts < window
                ]
            else:
                self._rate_limit_cache[user_id] = []
            
            # Check limit
            recent_calls = len(self._rate_limit_cache[user_id])
            if recent_calls >= max_calls:
                wait_time = int(window - (now - self._rate_limit_cache[user_id][0][0]))
                return False, f"Rate limit exceeded. Please wait {wait_time} seconds."
            
            return True, ""
    
    async def _record_rate_limit(self, user_id: str, request_id: str):
        """Record a request for rate limiting."""
        async with self._lock:
            now = time.time()
            if user_id not in self._rate_limit_cache:
                self._rate_limit_cache[user_id] = []
            self._rate_limit_cache[user_id].append((now, request_id))
    
    async def _check_concurrency(self, user_id: str, request_id: str) -> Tuple[bool, str]:
        """Check and acquire concurrency lock."""
        async with self._lock:
            max_concurrent = RATE_LIMITS["per_user_concurrency"]
            
            if user_id in self._active_requests:
                return False, ERROR_CODES["CONCURRENCY_LIMIT"]
            
            # Acquire lock
            self._active_requests[user_id] = request_id
            return True, ""
    
    async def _release_concurrency(self, user_id: str, request_id: str):
        """Release concurrency lock."""
        async with self._lock:
            if user_id in self._active_requests:
                if self._active_requests[user_id] == request_id:
                    del self._active_requests[user_id]


def ai_guarded(action: str, tokens_override: Optional[int] = None):
    """
    Decorator for AI-enabled route handlers.
    
    Automatically handles:
    - Token check and deduction
    - Error responses for insufficient tokens
    - Concurrency release after execution
    - Automatic reversal on 5xx errors
    
    Usage:
        @router.post("/ai/analyze")
        @ai_guarded("ai_analysis")
        async def analyze(request: AnalysisRequest, user: dict = Depends(get_current_user)):
            # AI execution here - tokens already deducted
            return {"result": "..."}
    
    Note: The decorated function must have 'user' in its parameters.
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Get db and user from kwargs or args
            from database import db
            
            user = kwargs.get('user')
            if not user:
                # Try to find user in args
                for arg in args:
                    if isinstance(arg, dict) and 'id' in arg:
                        user = arg
                        break
            
            if not user or 'id' not in user:
                from fastapi import HTTPException
                raise HTTPException(status_code=401, detail="User not authenticated")
            
            user_id = user['id']
            guard = AIGuard(db)
            
            # Check and deduct
            result = await guard.check_and_deduct(user_id, action, tokens_override)
            
            if not result.allowed:
                from fastapi import HTTPException
                raise HTTPException(
                    status_code=402,
                    detail={
                        "error_code": result.error_code,
                        "message": result.error_message,
                        "remaining_balance": result.remaining_balance
                    }
                )
            
            try:
                # Execute the AI function
                response = await func(*args, **kwargs)
                return response
            except Exception as e:
                # Check if this is a system error (5xx)
                status_code = getattr(e, 'status_code', 500)
                if status_code >= 500:
                    await guard.reverse_on_failure(user_id, result, str(e))
                raise
            finally:
                # Always release concurrency lock
                await guard.release(user_id, result.request_id)
        
        return wrapper
    return decorator
