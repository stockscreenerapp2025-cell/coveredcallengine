"""
Chatbot routes
"""
from fastapi import APIRouter, Request, HTTPException
from typing import Optional
import uuid

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import db

chatbot_router = APIRouter(tags=["Chatbot"])


async def _get_optional_user(request: Request) -> Optional[dict]:
    """Return the logged-in user if a valid token is present, otherwise None."""
    try:
        from utils.auth import get_current_user
        from fastapi.security import OAuth2PasswordBearer
        token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not token:
            return None
        # Reuse the existing JWT verification logic
        import jwt, os
        secret = os.environ.get("JWT_SECRET_KEY", "")
        if not secret:
            return None
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        user_id = payload.get("sub") or payload.get("user_id")
        if not user_id:
            return None
        user = await db.users.find_one({"_id": user_id}) or await db.users.find_one({"id": user_id})
        return user
    except Exception:
        return None


@chatbot_router.post("/message")
async def send_chatbot_message(
    request: Request,
    message: str,
    session_id: Optional[str] = None,
):
    """
    Send a message to the AI chatbot.
    - Public visitors (no token): free, no token deduction.
    - Logged-in users: 50 tokens deducted and logged in Usage History.
    """
    from services.chatbot_service import ChatbotService

    if not session_id:
        session_id = str(uuid.uuid4())

    user = await _get_optional_user(request)

    # Charge tokens only for authenticated users
    guard_result = None
    if user:
        from ai_wallet.ai_service import AIExecutionService
        ai_service = AIExecutionService(db)
        guard_result = await ai_service.guard.check_and_deduct(
            user_id=user["id"],
            action="chatbot_message",
        )
        if not guard_result.allowed:
            raise HTTPException(status_code=402, detail=guard_result.error_message)

    chatbot = ChatbotService(db)
    history = await chatbot.get_conversation_history(session_id, limit=10)

    try:
        result = await chatbot.get_response(session_id, message, history)
    except Exception as e:
        if user and guard_result:
            from ai_wallet.ai_service import AIExecutionService
            ai_service = AIExecutionService(db)
            await ai_service.guard.reverse_on_failure(
                user_id=user["id"],
                result=guard_result,
                reason=f"Chatbot error: {e}",
            )
            await ai_service.guard.release(user["id"], guard_result.request_id)
        raise HTTPException(status_code=500, detail="Chatbot error. Tokens not charged.")

    if user and guard_result:
        from ai_wallet.ai_service import AIExecutionService
        ai_service = AIExecutionService(db)
        await ai_service.guard.release(user["id"], guard_result.request_id)

    return {
        "response": result.get("response", ""),
        "session_id": session_id,
        "success": result.get("success", False),
        "tokens_used": guard_result.tokens_deducted if guard_result else 0,
        "remaining_balance": guard_result.remaining_balance if guard_result else None,
    }


@chatbot_router.get("/history/{session_id}")
async def get_chatbot_history(session_id: str):
    """Get conversation history for a session"""
    from services.chatbot_service import ChatbotService
    
    chatbot = ChatbotService(db)
    history = await chatbot.get_conversation_history(session_id)
    
    return {"history": history, "session_id": session_id}


@chatbot_router.get("/quick-response/{topic}")
async def get_quick_response(topic: str):
    """Get a quick predefined response for common topics"""
    from services.chatbot_service import QUICK_RESPONSES
    
    response = QUICK_RESPONSES.get(topic.lower())
    if response:
        return {"response": response, "topic": topic}
    
    return {"response": None, "topic": topic, "available_topics": list(QUICK_RESPONSES.keys())}
