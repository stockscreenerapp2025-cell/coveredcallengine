"""
AI Wallet Data Models

Pydantic models for AI wallet operations.
These define the structure of documents stored in MongoDB collections.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime


# ==================== WALLET MODELS ====================

class AIWallet(BaseModel):
    """User's AI token wallet"""
    user_id: str
    org_id: Optional[str] = None
    free_tokens_remaining: int = 0
    paid_tokens_remaining: int = 0
    monthly_used: int = 0
    last_reset: Optional[str] = None  # ISO datetime string
    next_reset: Optional[str] = None  # ISO datetime string
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AIWalletResponse(BaseModel):
    """Response model for wallet endpoint"""
    user_id: str
    free_tokens_remaining: int
    paid_tokens_remaining: int
    total_tokens: int
    monthly_used: int
    next_reset: Optional[str] = None
    plan: str
    plan_grant: int
    ai_enabled: bool


# ==================== LEDGER MODELS ====================

class AITokenLedgerEntry(BaseModel):
    """Immutable ledger entry for token transactions"""
    user_id: str
    org_id: Optional[str] = None
    action: str  # AI_TRADE_MANAGEMENT, AI_ANALYSIS, etc.
    tokens_total: int
    free_tokens: int = 0
    paid_tokens: int = 0
    source: Literal["usage", "purchase", "reversal", "grant", "expiry"]
    request_id: str
    timestamp: str  # ISO datetime string
    details: Optional[dict] = None


# ==================== PURCHASE MODELS ====================

class AIPurchase(BaseModel):
    """Token pack purchase record"""
    purchase_id: str
    user_id: str
    pack_id: str  # starter, power, pro
    expected_amount_usd: float
    expected_tokens: int
    status: Literal["created", "completed", "failed", "cancelled"]
    created_at: str
    completed_at: Optional[str] = None
    paypal_order_id: Optional[str] = None
    error_message: Optional[str] = None


class PurchaseCreateRequest(BaseModel):
    """Request to create a token purchase"""
    pack_id: str = Field(..., description="Token pack ID: starter, power, or pro")


class PurchaseCreateResponse(BaseModel):
    """Response after creating a purchase"""
    purchase_id: str
    pack_id: str
    amount_usd: float
    tokens: int
    paypal_order_id: str
    approval_url: str


# ==================== PAYPAL EVENT MODELS ====================

class PayPalEvent(BaseModel):
    """PayPal webhook event record for idempotency"""
    event_id: str
    capture_id: str
    processed: bool = False
    processed_at: Optional[str] = None
    event_type: Optional[str] = None
    raw_data: Optional[dict] = None


# ==================== ESTIMATE MODELS ====================

class TokenEstimateRequest(BaseModel):
    """Request to estimate token cost"""
    action: str = Field(..., description="AI action type: ai_analysis, trade_suggestion, etc.")
    params: Optional[dict] = None


class TokenEstimateResponse(BaseModel):
    """Response with estimated token cost"""
    action: str
    estimated_tokens: int
    current_balance: int
    sufficient_tokens: bool


# ==================== GUARD RESPONSE MODELS ====================

class AIGuardResult(BaseModel):
    """Result from AI execution guard"""
    allowed: bool
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    tokens_deducted: int = 0
    free_tokens_used: int = 0
    paid_tokens_used: int = 0
    request_id: Optional[str] = None
    remaining_balance: int = 0


# ==================== ENTITLEMENT MODELS ====================

class AIEntitlement(BaseModel):
    """AI feature entitlement for user/org"""
    user_id: Optional[str] = None
    org_id: Optional[str] = None
    ai_enabled: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
