"""
Chatbot routes
"""
from fastapi import APIRouter
from typing import Optional
import uuid

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import db

chatbot_router = APIRouter(tags=["Chatbot"])


@chatbot_router.post("/message")
async def send_chatbot_message(
    message: str,
    session_id: Optional[str] = None
):
    """Send a message to the AI chatbot and get a response"""
    from services.chatbot_service import ChatbotService
    
    # Generate session ID if not provided
    if not session_id:
        session_id = str(uuid.uuid4())
    
    chatbot = ChatbotService(db)
    
    # Get conversation history for context
    history = await chatbot.get_conversation_history(session_id, limit=10)
    
    # Get AI response
    result = await chatbot.get_response(session_id, message, history)
    
    return {
        "response": result.get("response", ""),
        "session_id": session_id,
        "success": result.get("success", False)
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
