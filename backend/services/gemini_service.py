"""
Gemini LLM Service for Covered Call Engine
Provides unified interface for Google Gemini AI interactions
Replaces emergentintegrations library
"""

import os
import logging
from typing import Optional, List, Dict
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class GeminiChat:
    """
    Gemini Chat wrapper that mimics the emergentintegrations LlmChat interface
    for easy migration from Emergent to Gemini
    """
    
    def __init__(
        self, 
        api_key: Optional[str] = None,
        session_id: Optional[str] = None,
        system_message: str = ""
    ):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.session_id = session_id
        self.system_message = system_message
        self.history: List[Dict] = []
        self.model_name = "gemini-2.0-flash"  # Default model
        self._model = None
        
    def with_model(self, provider: str = "google", model: str = "gemini-2.0-flash") -> "GeminiChat":
        """Set the model to use (for API compatibility with old code)"""
        # Map old model names to Gemini equivalents
        model_mapping = {
            "gpt-4o": "gemini-2.0-flash",
            "gpt-4o-mini": "gemini-2.0-flash", 
            "gpt-5.2": "gemini-2.0-flash",
            "gpt-4": "gemini-2.0-flash",
        }
        self.model_name = model_mapping.get(model, model)
        return self
    
    def add_user_message(self, content: str) -> "GeminiChat":
        """Add a user message to history"""
        self.history.append({"role": "user", "parts": [content]})
        return self
    
    def add_assistant_message(self, content: str) -> "GeminiChat":
        """Add an assistant message to history"""
        self.history.append({"role": "model", "parts": [content]})
        return self
    
    def _get_model(self):
        """Initialize and return the Gemini model"""
        if self._model is None:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self._model = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=self.system_message if self.system_message else None
            )
        return self._model
    
    async def send_message(self, message) -> str:
        """
        Send a message and get a response from Gemini
        
        Args:
            message: Can be a string or an object with a 'text' attribute (UserMessage compatibility)
        
        Returns:
            str: The model's response text
        """
        try:
            import google.generativeai as genai
            
            # Handle both string and UserMessage-like objects
            if hasattr(message, 'text'):
                user_text = message.text
            else:
                user_text = str(message)
            
            model = self._get_model()
            
            # Build conversation with history
            chat = model.start_chat(history=self.history)
            
            # Send message and get response
            response = chat.send_message(user_text)
            
            # Update history
            self.history.append({"role": "user", "parts": [user_text]})
            self.history.append({"role": "model", "parts": [response.text]})
            
            return response.text
            
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            raise


class UserMessage:
    """Compatible UserMessage class for migration from emergentintegrations"""
    def __init__(self, text: str):
        self.text = text


# Convenience function for simple one-off requests
async def generate_response(
    prompt: str,
    system_message: str = "",
    model: str = "gemini-2.0-flash"
) -> str:
    """
    Simple function to generate a response without managing chat history
    
    Args:
        prompt: The user's prompt
        system_message: Optional system instruction
        model: Model name to use
    
    Returns:
        str: The model's response
    """
    chat = GeminiChat(system_message=system_message).with_model("google", model)
    return await chat.send_message(prompt)


# For JSON responses (common in this codebase)
async def generate_json_response(
    prompt: str,
    system_message: str = "",
    model: str = "gemini-2.0-flash"
) -> Optional[Dict]:
    """
    Generate a response and parse it as JSON
    Handles markdown code blocks that Gemini sometimes wraps JSON in
    
    Args:
        prompt: The user's prompt
        system_message: Optional system instruction
        model: Model name to use
    
    Returns:
        dict: Parsed JSON response or None if parsing fails
    """
    import json
    
    try:
        response = await generate_response(prompt, system_message, model)
        
        # Clean response - remove markdown code blocks if present
        response_text = response.strip()
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.startswith("```"):
                    in_block = not in_block
                    continue
                if in_block or not line.startswith("```"):
                    json_lines.append(line)
            response_text = "\n".join(json_lines)
        
        return json.loads(response_text)
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Gemini response as JSON: {e}")
        return None
    except Exception as e:
        logger.error(f"Gemini JSON generation error: {e}")
        return None
