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
        },
        "safetySettings": [
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HARASSMENT",         "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH",        "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",  "threshold": "BLOCK_NONE"},
        ]
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload,
                                 headers={"Content-Type": "application/json"})
        if resp.status_code != 200:
            raise RuntimeError(f"Gemini API error {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        candidate = data["candidates"][0]
        finish_reason = candidate.get("finishReason", "UNKNOWN")
        if finish_reason not in ("STOP", "MAX_TOKENS"):
            logger.warning(f"[Gemini] Unexpected finishReason={finish_reason} model={model}")
        if finish_reason == "MAX_TOKENS":
            logger.warning(f"[Gemini] Response hit MAX_TOKENS limit ({max_tokens}) — consider increasing")
        # Gemini may split response into multiple parts — join them all
        parts = candidate.get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts)


async def _call_groq(prompt: str, system_message: str, api_key: str,
                     model: str = "llama-3.3-70b-versatile", max_tokens: int = 1000,
                     temperature: float = 0.7) -> str:
    """Call Groq API (free tier: 30 RPM, 14,400 RPD). OpenAI-compatible."""
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
        resp = await client.post("https://api.groq.com/openai/v1/chat/completions",
                                 json=payload, headers=headers)
        if resp.status_code != 200:
            raise RuntimeError(f"Groq API error {resp.status_code}: {resp.text[:300]}")
        return resp.json()["choices"][0]["message"]["content"]


class AIExecutionService:
    """
    Centralized AI execution service with token management.
    Provider chain (all free): Gemini → Groq → friendly quota message.
    Set GEMINI_API_KEY and GROQ_API_KEY in .env for full coverage.
    """

    def __init__(self, db):
        self.db = db
        self.guard = AIGuard(db)
        self.gemini_key = os.environ.get('GEMINI_API_KEY', '')
        self.groq_key = os.environ.get('GROQ_API_KEY', '')
        self.openai_key = os.environ.get('OPENAI_API_KEY', '')
    
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
            # Provider chain — all use same GEMINI_API_KEY, no new accounts needed:
            # gemini-2.0-flash → gemini-1.5-flash → gemini-1.5-flash-8b → friendly message
            import asyncio
            GEMINI_MODELS = [
                "gemini-2.5-flash",
                "gemini-2.0-flash-lite",
            ]
            response_text = None
            if self.gemini_key:
                for attempt_model in GEMINI_MODELS:
                    try:
                        response_text = await _call_gemini(
                            prompt=prompt, system_message=system_message,
                            api_key=self.gemini_key, model=attempt_model,
                            max_tokens=max_tokens, temperature=temperature
                        )
                        logger.info(f"[AI] Used Gemini model={attempt_model} for action={action}")
                        break
                    except RuntimeError as gemini_err:
                        err_str = str(gemini_err)
                        logger.warning(f"[AI] {attempt_model} failed: {err_str[:200]}, trying next model")
                        if "429" in err_str:
                            await asyncio.sleep(1)
                        # Fall through to next model for any error (404, 400, 403, etc.)

            if response_text is None and self.groq_key:
                try:
                    response_text = await _call_groq(
                        prompt=prompt, system_message=system_message,
                        api_key=self.groq_key, model="llama-3.3-70b-versatile",
                        max_tokens=max_tokens, temperature=temperature
                    )
                    logger.info(f"[AI] Used Groq fallback for action={action}")
                except RuntimeError as groq_err:
                    logger.warning(f"[AI] Groq failed: {str(groq_err)[:200]}")

            if response_text is None and self.openai_key:
                try:
                    import httpx as _httpx
                    headers = {"Authorization": f"Bearer {self.openai_key}", "Content-Type": "application/json"}
                    payload = {
                        "model": "gpt-4o-mini",
                        "messages": [
                            {"role": "system", "content": system_message},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": max_tokens,
                        "temperature": temperature
                    }
                    async with _httpx.AsyncClient(timeout=30.0) as client:
                        resp = await client.post("https://api.openai.com/v1/chat/completions",
                                                 json=payload, headers=headers)
                        if resp.status_code == 200:
                            response_text = resp.json()["choices"][0]["message"]["content"]
                            logger.info(f"[AI] Used OpenAI fallback for action={action}")
                        else:
                            logger.warning(f"[AI] OpenAI failed: {resp.status_code}: {resp.text[:200]}")
                except Exception as openai_err:
                    logger.warning(f"[AI] OpenAI exception: {str(openai_err)[:200]}")

            if response_text is None:
                # All providers at quota — reverse tokens so user is not charged
                await self.guard.reverse_on_failure(
                    user_id=user_id,
                    result=guard_result,
                    reason="AI providers at quota — no charge"
                )
                await self.guard.release(user_id, guard_result.request_id)
                return {
                    "success": False,
                    "error": "AI is temporarily busy. Please try again in a few minutes. Your tokens have not been charged.",
                    "error_code": "QUOTA_EXCEEDED",
                    "tokens_used": 0,
                    "free_tokens_used": 0,
                    "paid_tokens_used": 0,
                    "remaining_balance": guard_result.remaining_balance,
                    "quota_exceeded": True,
                }

            if not self.gemini_key:
                raise RuntimeError("No AI provider configured. Set GEMINI_API_KEY in .env")
            
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
        """
        system_message = (
            "You are a covered call and PMCC trading educator. "
            "Always write complete sentences. Never leave a sentence unfinished. "
            "Follow the decision rules exactly. End every response with: "
            "'This is an AI suggestion only and not a guarantee. Final trade decisions remain with the user.'"
        )

        prompt = f"""{trade_context}

---
=== COVERED CALL (CC) DECISION RULES ===

DTE < 0 (already expired):
- Stock Price > Strike → ALREADY_ASSIGNED (shares called away at strike price)
- Stock Price ≤ Strike → OPTION_EXPIRED_WORTHLESS (keep premium + shares, recommend new call)

DTE = 1:
- Evaluate moneyness and assignment likelihood
- Select one of: LET_EXPIRE, ROLL, MONITOR_CLOSELY

DTE = 0 (expiry day) — mandatory action set:
- Stock Price > Strike → EXPECT_ASSIGNMENT
- Stock Price ≤ Strike + weekly ROI ≥ 1% or monthly ROI ≥ 2% → SELL_ANOTHER_CALL
- Stock Price ≤ Strike + premiums too low or position below break-even → DO_NOTHING
- Stock down >40% + weak fundamentals → DO_NOTHING
- Stock down >40% + trader has conviction → CONSIDER_CSP_AVERAGING

DTE > 1:
- Standard management: HOLD, ROLL_UP, ROLL_DOWN, ROLL_OUT, or CLOSE

=== PMCC DECISION RULES ===

DTE = 1 (short call):
- Select one of: LET_EXPIRE, ROLL, MONITOR_CLOSELY

DTE = 0 (short call expiry) — mandatory action set:
- Stock Price > Strike → EXPECT_ASSIGNMENT (assignment risk disrupts PMCC structure, LEAPS may be forced closed)
- Stock Price ≤ Strike + weekly ROI ≥ 1% or monthly ROI ≥ 2% → SELL_ANOTHER_CALL (LEAPS remains intact)
- Stock Price ≤ Strike + premiums too low → DO_NOTHING
- Stock down >30-40% + weak fundamentals → DO_NOTHING
- Stock down >30-40% + reasonable conviction → CONSIDER_PMCC_ADJUSTMENT

DTE > 1:
- Standard management: HOLD, ROLL, MONITOR_CLOSELY

=== NEXT CALL RECOMMENDATION (when shares/LEAPS remain) ===
Strike selection:
- Prefer OTM strikes
- Prefer liquid options
- Prefer highest strike meeting ROI threshold
- Avoid illiquid / low-quality contracts
- For PMCC: prefer delta ~0.20–0.35

If recommending a new call, output must include:
Strike | Expiry date | Estimated premium | Expected ROI | Brief explanation

=== OUTPUT FORMAT (follow exactly, all lines mandatory) ===

Action: [action word only]
Suggested Trade: [specific trade details, or None]
Why: [two full sentences — what is happening and what to expect]
Risk Note: [one full sentence — the key risk]

This is an AI suggestion only and not a guarantee. Final trade decisions remain with the user."""

        return await self.execute(
            user_id=user_id,
            action="trade_suggestion",
            prompt=prompt,
            system_message=system_message,
            model="gpt-4o-mini",
            max_tokens=2000,
            temperature=0.7
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
