"""
Support Ticket Data Models for Covered Call Engine
Defines ticket schema, statuses, categories, and Pydantic models
"""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Literal
from datetime import datetime
from enum import Enum


# ==================== ENUMS ====================
class TicketStatus(str, Enum):
    NEW = "new"
    AI_DRAFTED = "ai_drafted"
    AWAITING_HUMAN_REVIEW = "awaiting_human_review"
    AI_RESPONDED = "ai_responded"
    AWAITING_USER = "awaiting_user"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TicketCategory(str, Enum):
    GENERAL = "general"
    BILLING = "billing"
    TECHNICAL = "technical"
    BUG_REPORT = "bug_report"
    FEATURE_REQUEST = "feature_request"
    SCREENER = "screener"
    PMCC = "pmcc"
    SIMULATOR = "simulator"
    PORTFOLIO = "portfolio"
    ACCOUNT = "account"
    HOW_IT_WORKS = "how_it_works"
    EDUCATIONAL = "educational"


class TicketSentiment(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class TicketPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class TicketSource(str, Enum):
    CONTACT_FORM = "contact_form"
    EMAIL = "email"
    ADMIN_CREATED = "admin_created"


# ==================== REQUEST MODELS ====================
class CreateTicketRequest(BaseModel):
    """Request model for creating a ticket from contact form"""
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    subject: Optional[str] = Field(default="", max_length=200)
    message: str = Field(..., min_length=10, max_length=5000)


class AdminCreateTicketRequest(BaseModel):
    """Request model for admin to create a ticket on behalf of user"""
    user_email: EmailStr
    user_name: str
    subject: str
    message: str
    category: Optional[TicketCategory] = TicketCategory.GENERAL
    priority: Optional[TicketPriority] = TicketPriority.NORMAL


class TicketReplyRequest(BaseModel):
    """Request model for replying to a ticket"""
    message: str = Field(..., min_length=1, max_length=10000)
    send_email: bool = True


class UpdateTicketRequest(BaseModel):
    """Request model for updating ticket details"""
    status: Optional[TicketStatus] = None
    category: Optional[TicketCategory] = None
    priority: Optional[TicketPriority] = None
    assigned_to: Optional[str] = None
    internal_notes: Optional[str] = None


# ==================== AI RESPONSE MODELS ====================
class AIClassificationResult(BaseModel):
    """Result from AI classification"""
    category: TicketCategory
    sentiment: TicketSentiment
    priority: TicketPriority
    confidence_score: int = Field(..., ge=0, le=100)
    rationale: str
    auto_response_eligible: bool = False
    kb_articles_referenced: List[str] = []


class AIDraftResponse(BaseModel):
    """AI-generated draft response"""
    draft_content: str
    confidence_score: int = Field(..., ge=0, le=100)
    rationale: str
    kb_articles_used: List[str] = []
    needs_human_review: bool = True
    flagged_for_escalation: bool = False
    escalation_reason: Optional[str] = None
    suggest_resolution: bool = False  # True if customer indicated issue is resolved


# ==================== RESPONSE MODELS ====================
class TicketMessage(BaseModel):
    """A single message in a ticket thread"""
    id: str
    sender_type: Literal["user", "admin", "ai", "system"]
    sender_name: str
    sender_email: Optional[str] = None
    content: str
    is_ai_draft: bool = False
    ai_confidence_score: Optional[int] = None
    created_at: str
    sent_via_email: bool = False


class TicketResponse(BaseModel):
    """Full ticket response model"""
    id: str
    ticket_number: str
    
    # User info
    user_name: str
    user_email: str
    
    # Ticket content
    subject: str
    original_message: str
    
    # Status & classification
    status: TicketStatus
    category: TicketCategory
    sentiment: TicketSentiment
    priority: TicketPriority
    source: TicketSource
    
    # AI metadata
    ai_confidence_score: Optional[int] = None
    ai_draft_response: Optional[str] = None
    auto_response_eligible: bool = False
    
    # Assignment
    assigned_to: Optional[str] = None
    
    # Thread
    messages: List[TicketMessage] = []
    
    # Internal
    internal_notes: Optional[str] = None
    
    # Timestamps
    created_at: str
    updated_at: str
    first_response_at: Optional[str] = None
    resolved_at: Optional[str] = None


class TicketListItem(BaseModel):
    """Ticket summary for list views"""
    id: str
    ticket_number: str
    user_name: str
    user_email: str
    subject: str
    status: TicketStatus
    category: TicketCategory
    sentiment: TicketSentiment
    priority: TicketPriority
    source: TicketSource
    ai_confidence_score: Optional[int] = None
    message_count: int = 1
    created_at: str
    updated_at: str


class TicketListResponse(BaseModel):
    """Paginated ticket list response"""
    tickets: List[TicketListItem]
    total: int
    page: int
    pages: int
    stats: dict = {}


# ==================== KNOWLEDGE BASE MODELS ====================
class KBArticle(BaseModel):
    """Knowledge Base article model"""
    id: str
    question: str
    answer: str
    category: TicketCategory
    active: bool = True
    created_at: str
    updated_at: str
    usage_count: int = 0


class CreateKBArticleRequest(BaseModel):
    """Request model for creating KB article"""
    question: str = Field(..., min_length=5, max_length=500)
    answer: str = Field(..., min_length=10, max_length=10000)
    category: TicketCategory = TicketCategory.GENERAL
    active: bool = True


class UpdateKBArticleRequest(BaseModel):
    """Request model for updating KB article"""
    question: Optional[str] = None
    answer: Optional[str] = None
    category: Optional[TicketCategory] = None
    active: Optional[bool] = None


# ==================== STATS MODELS ====================
class SupportStats(BaseModel):
    """Support dashboard statistics"""
    total_tickets: int = 0
    open_tickets: int = 0
    awaiting_review: int = 0
    resolved_today: int = 0
    avg_response_time_hours: float = 0.0
    avg_resolution_time_hours: float = 0.0
    ai_draft_accuracy: float = 0.0  # % of AI drafts approved without edit
    tickets_by_status: dict = {}
    tickets_by_category: dict = {}
    tickets_by_sentiment: dict = {}
