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
2. **Basic** - $29/month (Covered Call Dashboard, Scans, Real Market Data, TradingView Charts, 2,000 AI tokens/month)
3. **Standard** - $59/month (Everything in Basic + PMCC Scanner, Watchlist with AI, Portfolio Tracker, 6,000 AI tokens/month)
4. **Premium** - $89/month (Everything in Standard + Simulator & Analyser, AI Management of Trades, 15,000 AI tokens/month)

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
        self.gemini_key = os.environ.get('GEMINI_API_KEY', '')
        self.openai_key = os.environ.get('OPENAI_API_KEY', os.environ.get('EMERGENT_LLM_KEY', ''))

    async def _call_ai(self, messages: List[Dict]) -> str:
        """Call AI provider — Gemini first, OpenAI fallback."""
        import httpx
        if self.gemini_key:
            # Build Gemini contents from message history
            contents = []
            for m in messages:
                role = "user" if m["role"] == "user" else "model"
                contents.append({"role": role, "parts": [{"text": m["content"]}]})
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.gemini_key}"
            payload = {
                "system_instruction": {"parts": [{"text": CHATBOT_SYSTEM_PROMPT}]},
                "contents": contents,
                "generationConfig": {"maxOutputTokens": 500, "temperature": 0.7}
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
                if resp.status_code == 200:
                    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                raise RuntimeError(f"Gemini error {resp.status_code}: {resp.text[:200]}")
        elif self.openai_key:
            openai_messages = [{"role": "system", "content": CHATBOT_SYSTEM_PROMPT}] + messages
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    json={"model": "gpt-4o-mini", "messages": openai_messages, "max_tokens": 500},
                    headers={"Authorization": f"Bearer {self.openai_key}", "Content-Type": "application/json"}
                )
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"]
                raise RuntimeError(f"OpenAI error {resp.status_code}: {resp.text[:200]}")
        else:
            raise RuntimeError("No AI provider configured. Set GEMINI_API_KEY or OPENAI_API_KEY.")

    async def get_response(self, session_id: str, message: str, history: List[Dict] = None) -> Dict:
        """Get AI response for a chat message"""
        try:
            # Build message list (last 10 history + current)
            messages = []
            if history:
                for msg in history[-10:]:
                    if msg.get('role') in ('user', 'assistant'):
                        messages.append({"role": msg['role'], "content": msg.get('content', '')})
            messages.append({"role": "user", "content": message})

            response = await self._call_ai(messages)

            if self.db is not None:
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
    "pricing": "Our pricing is simple:\n• **FREE Trial**: 7 days full access — no credit card needed\n• **Basic**: $29/month — Covered Call tools + 2,000 AI tokens\n• **Standard**: $59/month — Everything in Basic + PMCC Scanner, Watchlist AI + 6,000 AI tokens\n• **Premium**: $89/month — Full suite including Simulator, AI Trade Management + 15,000 AI tokens\n\nStart with the FREE trial today! 🚀",
    
    "features": "Covered Call Engine offers:\n• 📊 Real-time covered call scanner\n• 🎯 PMCC opportunity finder\n• 📈 Portfolio tracker with IBKR integration\n• 🤖 AI-powered trade suggestions\n• 📰 Market news & sentiment\n\nWant to try it? Start your FREE 7-day trial!",
    
    "covered_call": "A **covered call** is when you:\n1. Own 100+ shares of a stock\n2. Sell a call option against those shares\n3. Collect premium income!\n\nIt's a great way to generate income on stocks you already own. Our scanner finds the best opportunities! 💰",
    
    "pmcc": "**PMCC (Poor Man's Covered Call)** is a capital-efficient strategy:\n1. Buy a deep ITM LEAPS call (instead of stock)\n2. Sell short-term OTM calls against it\n3. Requires 60-80% less capital!\n\nOur PMCC screener finds the best setups. Try it FREE! 🎯",
    
    "trial": "Our **FREE 7-day trial** gives you:\n• Full platform access\n• All screener features\n• Portfolio tracking\n• AI suggestions\n• No credit card required!\n\n👉 Click 'Start Free Trial' to begin your options income journey!",
}
