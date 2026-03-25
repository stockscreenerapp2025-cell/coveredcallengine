"""
Chatbot routes
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
import uuid

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import db
from utils.auth import get_current_user

chatbot_router = APIRouter(tags=["Chatbot"])


@chatbot_router.post("/message")
async def send_chatbot_message(
    message: str,
    session_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    """Send a message to the AI chatbot and get a response (uses AI tokens)"""
    from services.chatbot_service import ChatbotService
    from ai_wallet.ai_service import AIExecutionService

    # Generate session ID if not provided
    if not session_id:
        session_id = str(uuid.uuid4())

    # Check and deduct tokens before calling AI
    ai_service = AIExecutionService(db)
    guard_result = await ai_service.guard.check_and_deduct(
        user_id=user["id"],
        action="chatbot_message",
    )
    if not guard_result.allowed:
        raise HTTPException(status_code=402, detail=guard_result.error_message)

    chatbot = ChatbotService(db)

    # Get conversation history for context
    history = await chatbot.get_conversation_history(session_id, limit=10)

    # Get AI response
    try:
        result = await chatbot.get_response(session_id, message, history)
    except Exception as e:
        await ai_service.guard.reverse_on_failure(
            user_id=user["id"],
            result=guard_result,
            reason=f"Chatbot error: {e}",
        )
        await ai_service.guard.release(user["id"], guard_result.request_id)
        raise HTTPException(status_code=500, detail="Chatbot error. Tokens not charged.")

    await ai_service.guard.release(user["id"], guard_result.request_id)

    return {
        "response": result.get("response", ""),
        "session_id": session_id,
        "success": result.get("success", False),
        "tokens_used": guard_result.tokens_deducted,
        "remaining_balance": guard_result.remaining_balance,
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
