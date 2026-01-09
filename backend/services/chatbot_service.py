"""
AI Chatbot Service for Covered Call Engine
Provides conversational AI to help visitors understand the platform and encourage sign-ups
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, List
from uuid import uuid4
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# System prompt for the chatbot - trained on Covered Call Engine knowledge
CHATBOT_SYSTEM_PROMPT = """You are a friendly and knowledgeable AI assistant for Covered Call Engine, a premium options trading platform specializing in covered call and PMCC (Poor Man's Covered Call) strategies.

## About Covered Call Engine:
- **What it does**: Helps traders find high-premium covered call opportunities with our powerful AI-driven screener
- **Key Features**:
  - Real-time covered call scanner with advanced filters (IV, Delta, DTE, ROI)
  - PMCC (Poor Man's Covered Call) opportunity finder for lower capital requirements
  - Portfolio tracker with IBKR integration
  - AI-powered trade suggestions
  - Market news and sentiment analysis
  - TradingView charts integration

## Pricing Plans:
1. **FREE Trial** - 7 days full access, no credit card required
2. **Monthly Plan** - $49/month for full platform access
3. **Annual Plan** - $499/year (save $89 - 2 months free!)

## What is a Covered Call?
A covered call is an options strategy where you:
1. Own shares of a stock (100 shares per contract)
2. Sell call options against those shares to collect premium
3. Generate income while potentially being called away at the strike price

## What is PMCC?
Poor Man's Covered Call is a variation where:
1. Instead of buying stock, you buy deep ITM LEAPS (long-term call options)
2. Sell short-term OTM calls against the LEAPS
3. Requires significantly less capital than traditional covered calls

## Your Goals:
1. Answer questions about covered calls, PMCC, and options trading clearly
2. Explain the platform features and benefits
3. Encourage visitors to sign up for the FREE 7-day trial
4. For serious traders, highlight the value of monthly or annual subscriptions
5. Be helpful, professional, and encouraging without being pushy

## Guidelines:
- Keep responses concise but informative (2-4 sentences when possible)
- Use bullet points for lists
- If asked about specific trades or financial advice, remind them you're an educational tool
- Always be positive about the platform's capabilities
- End responses with a gentle nudge towards trying the FREE trial when appropriate

Remember: You're here to help visitors understand how Covered Call Engine can improve their options trading journey!"""


class ChatbotService:
    def __init__(self, db=None):
        self.db = db
        self.api_key = os.environ.get('EMERGENT_LLM_KEY')
    
    async def get_response(self, session_id: str, message: str, history: List[Dict] = None) -> Dict:
        """Get AI response for a chat message"""
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage
            
            # Initialize chat with system prompt
            chat = LlmChat(
                api_key=self.api_key,
                session_id=session_id,
                system_message=CHATBOT_SYSTEM_PROMPT
            ).with_model("openai", "gpt-4o-mini")  # Using gpt-4o-mini for fast responses
            
            # Add conversation history if provided
            if history:
                for msg in history[-10:]:  # Keep last 10 messages for context
                    if msg.get('role') == 'user':
                        chat.add_user_message(msg.get('content', ''))
                    elif msg.get('role') == 'assistant':
                        chat.add_assistant_message(msg.get('content', ''))
            
            # Send the new message
            user_message = UserMessage(text=message)
            response = await chat.send_message(user_message)
            
            # Log the conversation if db is available
            if self.db:
                await self._log_conversation(session_id, message, response)
            
            return {
                "success": True,
                "response": response,
                "session_id": session_id
            }
            
        except Exception as e:
            logger.error(f"Chatbot error: {e}")
            return {
                "success": False,
                "response": "I apologize, but I'm having trouble responding right now. Please try again or contact us directly for assistance!",
                "error": str(e)
            }
    
    async def _log_conversation(self, session_id: str, user_message: str, ai_response: str):
        """Log conversation to database"""
        try:
            await self.db.chatbot_logs.insert_one({
                "id": str(uuid4()),
                "session_id": session_id,
                "user_message": user_message,
                "ai_response": ai_response,
                "created_at": datetime.now(timezone.utc).isoformat()
            })
        except Exception as e:
            logger.error(f"Failed to log conversation: {e}")
    
    async def get_conversation_history(self, session_id: str, limit: int = 20) -> List[Dict]:
        """Get conversation history for a session"""
        if self.db is None:
            return []
        
        try:
            logs = await self.db.chatbot_logs.find(
                {"session_id": session_id},
                {"_id": 0}
            ).sort("created_at", -1).limit(limit).to_list(limit)
            
            # Convert to message format
            messages = []
            for log in reversed(logs):
                messages.append({"role": "user", "content": log["user_message"]})
                messages.append({"role": "assistant", "content": log["ai_response"]})
            
            return messages
        except Exception as e:
            logger.error(f"Failed to get history: {e}")
            return []


# Predefined quick responses for common questions
QUICK_RESPONSES = {
    "pricing": "Our pricing is simple:\n• **FREE Trial**: 7 days full access\n• **Monthly**: $49/month\n• **Annual**: $499/year (save $89!)\n\nStart with the FREE trial - no credit card needed! 🚀",
    
    "features": "Covered Call Engine offers:\n• 📊 Real-time covered call scanner\n• 🎯 PMCC opportunity finder\n• 📈 Portfolio tracker with IBKR integration\n• 🤖 AI-powered trade suggestions\n• 📰 Market news & sentiment\n\nWant to try it? Start your FREE 7-day trial!",
    
    "covered_call": "A **covered call** is when you:\n1. Own 100+ shares of a stock\n2. Sell a call option against those shares\n3. Collect premium income!\n\nIt's a great way to generate income on stocks you already own. Our scanner finds the best opportunities! 💰",
    
    "pmcc": "**PMCC (Poor Man's Covered Call)** is a capital-efficient strategy:\n1. Buy a deep ITM LEAPS call (instead of stock)\n2. Sell short-term OTM calls against it\n3. Requires 60-80% less capital!\n\nOur PMCC screener finds the best setups. Try it FREE! 🎯",
    
    "trial": "Our **FREE 7-day trial** gives you:\n• Full platform access\n• All screener features\n• Portfolio tracking\n• AI suggestions\n• No credit card required!\n\n👉 Click 'Start Free Trial' to begin your options income journey!",
}
