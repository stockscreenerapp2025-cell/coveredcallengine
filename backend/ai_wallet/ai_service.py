"""
AI Execution Service - Centralized AI execution with token guard

This service provides a single entry point for all AI operations.
All AI calls MUST go through this service to enforce token requirements.

Usage:
    from ai_wallet.ai_service import AIExecutionService
    
    ai_service = AIExecutionService(db)
    
    # Execute with token check
    result = await ai_service.execute(
        user_id=user["id"],
        action="trade_suggestion",
        prompt="Analyze this trade...",
        system_message="You are a trading advisor."
    )
    
    if result["success"]:
        print(result["response"])
    else:
        print(result["error"])  # Insufficient tokens, rate limit, etc.
"""

import os
import logging
import uuid
from typing import Optional, Dict, Any

from .guard import AIGuard
from .config import AI_ACTION_COSTS

logger = logging.getLogger(__name__)


class AIExecutionService:
    """
    Centralized AI execution service with token management.
    
    All AI calls in the application should use this service to:
    1. Check token balance
    2. Deduct tokens atomically
    3. Execute the AI call
    4. Handle failures and reversals
    """
    
    def __init__(self, db):
        self.db = db
        self.guard = AIGuard(db)
        self.api_key = os.environ.get('EMERGENT_LLM_KEY')
    
    async def execute(
        self,
        user_id: str,
        action: str,
        prompt: str,
        system_message: str = "You are a helpful AI assistant.",
        model: str = "gpt-4o-mini",
        provider: str = "openai",
        max_tokens: int = 1000,
        temperature: float = 0.7,
        tokens_override: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Execute an AI call with token guard.
        
        Args:
            user_id: User making the request
            action: AI action type (for token calculation)
            prompt: User prompt to send to AI
            system_message: System message for AI context
            model: AI model to use
            provider: AI provider (openai, etc.)
            max_tokens: Maximum response tokens
            temperature: Response randomness
            tokens_override: Override calculated token cost
            
        Returns:
            Dict with success, response/error, and token info
        """
        # Check and deduct tokens
        guard_result = await self.guard.check_and_deduct(
            user_id=user_id,
            action=action,
            tokens_override=tokens_override
        )
        
        if not guard_result.allowed:
            return {
                "success": False,
                "error": guard_result.error_message,
                "error_code": guard_result.error_code,
                "remaining_balance": guard_result.remaining_balance
            }
        
        try:
            # Execute AI call using emergentintegrations
            from emergentintegrations.llm.chat import LlmChat, UserMessage
            
            chat = LlmChat(
                api_key=self.api_key,
                session_id=str(uuid.uuid4()),
                system_message=system_message
            ).with_model(provider, model)
            
            response = await chat.send_message(UserMessage(text=prompt))
            response_text = response if isinstance(response, str) else str(response)
            
            # Release guard (successful execution)
            await self.guard.release(user_id, guard_result.request_id)
            
            return {
                "success": True,
                "response": response_text,
                "tokens_used": guard_result.tokens_deducted,
                "free_tokens_used": guard_result.free_tokens_used,
                "paid_tokens_used": guard_result.paid_tokens_used,
                "remaining_balance": guard_result.remaining_balance,
                "request_id": guard_result.request_id
            }
            
        except Exception as e:
            # System error - reverse tokens
            logger.error(f"AI execution failed for user {user_id}: {e}")
            
            await self.guard.reverse_on_failure(
                user_id=user_id,
                result=guard_result,
                reason=f"AI execution error: {str(e)}"
            )
            
            # Release guard
            await self.guard.release(user_id, guard_result.request_id)
            
            return {
                "success": False,
                "error": f"AI execution failed: {str(e)}",
                "error_code": "AI_EXECUTION_ERROR",
                "tokens_reversed": True
            }
    
    async def estimate(self, user_id: str, action: str) -> Dict[str, Any]:
        """
        Estimate token cost for an action.
        
        Returns:
            Dict with estimated_tokens, current_balance, sufficient_tokens
        """
        result = await self.guard.estimate(user_id, action)
        return {
            "action": result.action,
            "estimated_tokens": result.estimated_tokens,
            "current_balance": result.current_balance,
            "sufficient_tokens": result.sufficient_tokens
        }
    
    async def execute_trade_suggestion(
        self,
        user_id: str,
        trade_context: str
    ) -> Dict[str, Any]:
        """
        Execute AI trade suggestion with appropriate token cost.
        
        Convenience method for trade suggestions.
        """
        system_message = """You are a professional options trading advisor. 
        Analyze the trade data and provide actionable recommendations.
        Start with ONE action word (HOLD, CLOSE, ROLL_UP, ROLL_DOWN, ROLL_OUT, or LET_EXPIRE), 
        then explain your reasoning briefly in 2-3 sentences."""
        
        return await self.execute(
            user_id=user_id,
            action="trade_suggestion",
            prompt=trade_context,
            system_message=system_message,
            model="gpt-4o-mini",
            temperature=0.5
        )
    
    async def execute_sentiment_analysis(
        self,
        user_id: str,
        news_text: str
    ) -> Dict[str, Any]:
        """
        Execute AI sentiment analysis with appropriate token cost.
        
        Convenience method for sentiment analysis.
        """
        system_message = """You are a financial sentiment analyst. 
        Analyze the sentiment of stock-related news articles.
        Respond in JSON format with sentiment scores and summary."""
        
        return await self.execute(
            user_id=user_id,
            action="sentiment_analysis",
            prompt=news_text,
            system_message=system_message,
            model="gpt-4o-mini",
            temperature=0.3
        )
    
    async def execute_general_analysis(
        self,
        user_id: str,
        analysis_request: str,
        context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute general AI analysis with appropriate token cost.
        
        Convenience method for general analysis requests.
        """
        system_message = """You are an expert options trading analyst 
        specializing in covered calls and PMCC strategies.
        Provide actionable, data-driven analysis with specific recommendations.
        Include confidence levels and clear rationale."""
        
        prompt = analysis_request
        if context:
            prompt = f"{context}\n\n{analysis_request}"
        
        return await self.execute(
            user_id=user_id,
            action="ai_analysis",
            prompt=prompt,
            system_message=system_message,
            model="gpt-4o",
            temperature=0.7
        )


# Singleton-like access for easy import
_ai_service_instance = None

def get_ai_service(db):
    """Get or create the AI execution service instance."""
    global _ai_service_instance
    if _ai_service_instance is None:
        _ai_service_instance = AIExecutionService(db)
    return _ai_service_instance
