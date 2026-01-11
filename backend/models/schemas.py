"""
Pydantic models/schemas for the application
"""
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import List, Optional, Dict, Any
from datetime import datetime


# ==================== AUTH MODELS ====================

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    is_admin: bool = False
    created_at: Optional[str] = None

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# ==================== PORTFOLIO MODELS ====================

class PortfolioPosition(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    
    id: Optional[str] = None
    symbol: str
    quantity: float
    avg_cost: float
    current_price: Optional[float] = None
    market_value: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    unrealized_pnl_pct: Optional[float] = None
    strategy: Optional[str] = None
    option_details: Optional[Dict[str, Any]] = None

class PortfolioPositionCreate(BaseModel):
    symbol: str
    quantity: float
    avg_cost: float
    strategy: Optional[str] = None
    option_details: Optional[Dict[str, Any]] = None


# ==================== WATCHLIST MODELS ====================

class WatchlistItem(BaseModel):
    id: Optional[str] = None
    symbol: str
    added_at: Optional[str] = None
    notes: Optional[str] = None

class WatchlistItemCreate(BaseModel):
    symbol: str
    target_price: Optional[float] = None
    notes: Optional[str] = None


# ==================== SCREENER MODELS ====================

class ScreenerFilter(BaseModel):
    id: Optional[str] = None
    name: str
    filters: Dict[str, Any]

class ScreenerFilterCreate(BaseModel):
    name: str
    filters: Dict[str, Any]


# ==================== ADMIN MODELS ====================

class AdminSettings(BaseModel):
    polygon_api_key: Optional[str] = None
    marketaux_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    stripe_secret_key: Optional[str] = None
    stripe_publishable_key: Optional[str] = None
    stripe_price_id: Optional[str] = None
    resend_api_key: Optional[str] = None
    resend_from_email: Optional[str] = None
    free_trial_days: int = 7


# ==================== AI MODELS ====================

class AIAnalysisRequest(BaseModel):
    symbol: str
    analysis_type: str = "covered_call"
    data: Optional[Dict[str, Any]] = None


# ==================== MANUAL TRADE MODELS ====================

class ManualTradeCreate(BaseModel):
    """Model for creating a manual trade entry"""
    symbol: str
    strategy: str  # covered_call, pmcc, stock_only, option_only, collar
    
    # Stock position
    shares: Optional[int] = None
    entry_price: Optional[float] = None
    current_price: Optional[float] = None
    
    # Short call (for covered calls, PMCC, collar)
    short_call_strike: Optional[float] = None
    short_call_expiry: Optional[str] = None
    short_call_premium: Optional[float] = None
    short_call_contracts: Optional[int] = None
    
    # Long call (for PMCC - LEAPS)
    long_call_strike: Optional[float] = None
    long_call_expiry: Optional[str] = None
    long_call_premium: Optional[float] = None
    long_call_contracts: Optional[int] = None
    
    # Long put (for collar)
    long_put_strike: Optional[float] = None
    long_put_expiry: Optional[str] = None
    long_put_premium: Optional[float] = None
    long_put_contracts: Optional[int] = None
    
    # Option only position
    option_type: Optional[str] = None  # call or put
    option_strike: Optional[float] = None
    option_expiry: Optional[str] = None
    option_premium: Optional[float] = None
    option_contracts: Optional[int] = None
    option_position: Optional[str] = None  # long or short
    
    # Trade metadata
    open_date: Optional[str] = None
    status: str = "open"  # open, closed
    notes: Optional[str] = None


# ==================== SIMULATOR MODELS ====================

class SimulatorTradeEntry(BaseModel):
    """Model for adding a trade to the simulator"""
    symbol: str
    strategy_type: str  # "covered_call" or "pmcc"
    
    # Stock/LEAPS Entry
    underlying_price: float
    
    # Short Call Details
    short_call_strike: float
    short_call_expiry: str
    short_call_premium: float
    short_call_delta: Optional[float] = None
    short_call_iv: Optional[float] = None
    
    # For PMCC - LEAPS details
    leaps_strike: Optional[float] = None
    leaps_expiry: Optional[str] = None
    leaps_premium: Optional[float] = None
    leaps_delta: Optional[float] = None
    
    # Position sizing
    contracts: int = 1
    
    # Scan metadata (for feedback loop)
    scan_parameters: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None


# ==================== RULE MODELS ====================

class TradeRuleCondition(BaseModel):
    """Individual condition for a rule"""
    field: str  # premium_capture_pct, current_delta, loss_pct, dte_remaining, etc.
    operator: str  # gte, lte, gt, lt, eq
    value: float

class TradeRuleAction(BaseModel):
    """Action to take when rule conditions are met"""
    action_type: str  # roll, close, alert
    parameters: Optional[Dict[str, Any]] = None  # e.g., new_dte for roll

class TradeRuleCreate(BaseModel):
    """Model for creating a trade rule"""
    name: str
    description: Optional[str] = None
    strategy_type: Optional[str] = None  # covered_call, pmcc, or None for both
    is_enabled: bool = True
    priority: int = 10  # Lower number = higher priority
    conditions: List[TradeRuleCondition]
    action: TradeRuleAction

class TradeRuleUpdate(BaseModel):
    """Model for updating a trade rule"""
    name: Optional[str] = None
    description: Optional[str] = None
    strategy_type: Optional[str] = None
    is_enabled: Optional[bool] = None
    priority: Optional[int] = None
    conditions: Optional[List[TradeRuleCondition]] = None
    action: Optional[TradeRuleAction] = None
