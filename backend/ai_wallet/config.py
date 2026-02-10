"""
AI Wallet Configuration and Constants

Token packs, plan grants, and rate limits are defined here.
All values are in USD and tokens.
"""

# ==================== TOKEN PACKS (USD) ====================
TOKEN_PACKS = {
    "starter": {
        "name": "Starter Pack",
        "tokens": 5000,
        "price_usd": 10.00,
        "description": "5,000 AI tokens"
    },
    "power": {
        "name": "Power Pack",
        "tokens": 15000,
        "price_usd": 25.00,
        "description": "15,000 AI tokens"
    },
    "pro": {
        "name": "Pro Pack",
        "tokens": 50000,
        "price_usd": 75.00,
        "description": "50,000 AI tokens"
    }
}

# ==================== PLAN FREE TOKEN GRANTS ====================
# Tokens granted at the start of each billing cycle
PLAN_FREE_TOKENS = {
    "basic": 2000,
    "standard": 6000,
    "premium": 15000,
    # Fallbacks
    "trial": 2000,  # Trial users get basic-level tokens
    "free": 0,       # No free tier
    "none": 0,       # No subscription
    "default": 2000  # Default to basic if plan unknown
}

# ==================== AI ACTION TOKEN COSTS ====================
# Estimated token costs per action type
AI_ACTION_COSTS = {
    "ai_analysis": 200,           # /api/ai/analyze
    "trade_suggestion": 300,       # Portfolio AI suggestions
    "sentiment_analysis": 150,     # News sentiment
    "chatbot_message": 50,         # Chatbot interaction
    "portfolio_scan": 500,         # Full portfolio AI scan
    "default": 100                 # Unknown actions
}

# ==================== RATE LIMITS (ABUSE PREVENTION) ====================
RATE_LIMITS = {
    "max_calls_per_minute": 10,
    "max_tokens_per_action": 2000,
    "max_portfolio_scan_per_hour": 1,
    "max_retries_per_action": 1,
    "per_user_concurrency": 1
}

# ==================== ERROR CODES ====================
ERROR_CODES = {
    "INSUFFICIENT_TOKENS": "Not enough tokens. Please purchase more or wait for monthly reset.",
    "RATE_LIMIT": "Rate limit exceeded. Please wait before making another request.",
    "ACTION_TOO_LARGE": "This action exceeds the maximum token limit.",
    "CONCURRENCY_LIMIT": "Another AI request is in progress. Please wait.",
    "AI_DISABLED": "AI features are not enabled for your account.",
    "WALLET_NOT_FOUND": "Wallet not initialized. Please try again."
}

# ==================== PAYPAL CONFIGURATION ====================
PAYPAL_CONFIG = {
    "sandbox": {
        "api_base": "https://api-m.sandbox.paypal.com",
        "web_base": "https://www.sandbox.paypal.com"
    },
    "live": {
        "api_base": "https://api-m.paypal.com",
        "web_base": "https://www.paypal.com"
    }
}

# Webhook event type for capture completion
PAYPAL_CAPTURE_COMPLETED_EVENT = "PAYMENT.CAPTURE.COMPLETED"
