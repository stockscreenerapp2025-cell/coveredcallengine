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


async def _call_gemini(prompt: str, system_message: str, api_key: str,
                       model: str = "gemini-2.0-flash", max_tokens: int = 1000,
                       temperature: float = 0.7) -> str:
    """Call Google Gemini API directly (free tier: 15 RPM, 1500 RPD)."""
    import httpx, json as _json
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "system_instruction": {"parts": [{"text": system_message}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": temperature
        }
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload,
                                 headers={"Content-Type": "application/json"})
        if resp.status_code != 200:
            raise RuntimeError(f"Gemini API error {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]


async def _call_openai(prompt: str, system_message: str, api_key: str,
                       model: str = "gpt-4o-mini", max_tokens: int = 1000,
                       temperature: float = 0.7) -> str:
    """Call OpenAI API directly."""
    import httpx
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user",   "content": prompt}
        ],
        "max_tokens": max_tokens,
        "temperature": temperature
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post("https://api.openai.com/v1/chat/completions",
                                 json=payload, headers=headers)
        if resp.status_code != 200:
            raise RuntimeError(f"OpenAI API error {resp.status_code}: {resp.text[:300]}")
        return resp.json()["choices"][0]["message"]["content"]


class AIExecutionService:
    """
    Centralized AI execution service with token management.
    Uses Google Gemini (free) when GEMINI_API_KEY is set,
    falls back to OpenAI when OPENAI_API_KEY is set.
    """

    def __init__(self, db):
        self.db = db
        self.guard = AIGuard(db)
        self.gemini_key = os.environ.get('GEMINI_API_KEY', '')
        self.openai_key = os.environ.get('OPENAI_API_KEY', os.environ.get('EMERGENT_LLM_KEY', ''))
        # Legacy field kept for compatibility
        self.api_key = self.openai_key
    
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
            # Use Gemini (free) if key configured, else fall back to OpenAI
            if self.gemini_key:
                gemini_model = "gemini-2.0-flash"
                response_text = await _call_gemini(
                    prompt=prompt,
                    system_message=system_message,
                    api_key=self.gemini_key,
                    model=gemini_model,
                    max_tokens=max_tokens,
                    temperature=temperature
                )
                logger.info(f"[AI] Used Gemini ({gemini_model}) for action={action}")
            elif self.openai_key:
                response_text = await _call_openai(
                    prompt=prompt,
                    system_message=system_message,
                    api_key=self.openai_key,
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature
                )
                logger.info(f"[AI] Used OpenAI ({model}) for action={action}")
            else:
                raise RuntimeError("No AI provider configured. Set GEMINI_API_KEY (free) or OPENAI_API_KEY in .env")
            
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
