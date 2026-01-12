"""
Support Routes for Covered Call Engine
API endpoints for support ticket management, knowledge base, and admin operations
Phase 1: Human-in-the-loop - All AI responses require admin approval before sending
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional
from datetime import datetime, timezone
import logging

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import db
from utils.auth import get_current_user, get_admin_user, get_support_user
from services.support_service import SupportService
from models.support import (
    CreateTicketRequest, AdminCreateTicketRequest, TicketReplyRequest, UpdateTicketRequest,
    CreateKBArticleRequest, UpdateKBArticleRequest,
    TicketStatus, TicketCategory, TicketPriority, TicketSource
)

logger = logging.getLogger(__name__)

support_router = APIRouter(prefix="/support", tags=["Support"])


def get_support_service():
    """Dependency to get support service instance"""
    return SupportService(db)


# ==================== PUBLIC ENDPOINTS ====================

@support_router.post("/tickets")
async def create_ticket(
    request: CreateTicketRequest,
    service: SupportService = Depends(get_support_service)
):
    """
    Create a new support ticket from contact form (public endpoint).
    This is the main entry point for user inquiries.
    
    - Creates ticket with AI classification and draft response
    - Sends auto-acknowledgment email to user
    - Status will be 'ai_drafted' or 'awaiting_human_review' based on AI confidence
    """
    try:
        result = await service.create_ticket(
            name=request.name,
            email=request.email,
            subject=request.subject,
            message=request.message
        )
        return result
    except Exception as e:
        logger.error(f"Failed to create ticket: {e}")
        raise HTTPException(status_code=500, detail="Failed to create support ticket")


@support_router.get("/tickets/{ticket_id}/public")
async def get_ticket_public(
    ticket_id: str,
    email: str = Query(..., description="Email for verification"),
    service: SupportService = Depends(get_support_service)
):
    """
    Get ticket details by ID or ticket number (public - requires email verification).
    Users can check their ticket status using ticket number + email.
    """
    ticket = await service.get_ticket(ticket_id)
    
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    # Verify email matches
    if ticket["user_email"].lower() != email.lower():
        raise HTTPException(status_code=403, detail="Email does not match ticket")
    
    # Return limited info for public view
    return {
        "ticket_number": ticket["ticket_number"],
        "subject": ticket["subject"],
        "status": ticket["status"],
        "created_at": ticket["created_at"],
        "updated_at": ticket["updated_at"],
        "message_count": len(ticket.get("messages", []))
    }


@support_router.post("/tickets/{ticket_id}/reply/public")
async def add_user_reply(
    ticket_id: str,
    request: TicketReplyRequest,
    email: str = Query(..., description="Email for verification"),
    service: SupportService = Depends(get_support_service)
):
    """
    Add a user reply to their ticket (public - requires email verification).
    """
    ticket = await service.get_ticket(ticket_id)
    
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    # Verify email matches
    if ticket["user_email"].lower() != email.lower():
        raise HTTPException(status_code=403, detail="Email does not match ticket")
    
    result = await service.add_reply(
        ticket_id=ticket_id,
        message=request.message,
        sender_type="user",
        sender_name=ticket["user_name"],
        sender_email=ticket["user_email"],
        send_email=False  # Don't send email for user's own message
    )
    
    if not result:
        raise HTTPException(status_code=500, detail="Failed to add reply")
    
    return {"success": True, "message_id": result["id"]}


# ==================== ADMIN TICKET ENDPOINTS ====================

@support_router.get("/admin/tickets")
async def get_tickets(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    sentiment: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    assigned_to: Optional[str] = Query(None),
    admin: dict = Depends(get_admin_user),
    service: SupportService = Depends(get_support_service)
):
    """
    Get paginated list of support tickets with filters (admin only).
    """
    return await service.get_tickets(
        page=page,
        limit=limit,
        status=status,
        category=category,
        priority=priority,
        sentiment=sentiment,
        search=search,
        assigned_to=assigned_to
    )


@support_router.get("/admin/tickets/{ticket_id}")
async def get_ticket_detail(
    ticket_id: str,
    admin: dict = Depends(get_admin_user),
    service: SupportService = Depends(get_support_service)
):
    """
    Get full ticket details including messages and AI metadata (admin only).
    """
    ticket = await service.get_ticket(ticket_id)
    
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    return ticket


@support_router.put("/admin/tickets/{ticket_id}")
async def update_ticket(
    ticket_id: str,
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    assigned_to: Optional[str] = Query(None),
    internal_notes: Optional[str] = Query(None),
    admin: dict = Depends(get_admin_user),
    service: SupportService = Depends(get_support_service)
):
    """
    Update ticket properties (status, category, priority, assignment, notes).
    """
    updates = {}
    if status is not None:
        updates["status"] = status
    if category is not None:
        updates["category"] = category
    if priority is not None:
        updates["priority"] = priority
    if assigned_to is not None:
        updates["assigned_to"] = assigned_to
    if internal_notes is not None:
        updates["internal_notes"] = internal_notes
    
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")
    
    success = await service.update_ticket(
        ticket_id=ticket_id,
        updates=updates,
        admin_id=admin["id"],
        admin_email=admin.get("email")
    )
    
    if not success:
        raise HTTPException(status_code=404, detail="Ticket not found or update failed")
    
    return {"success": True, "message": "Ticket updated"}


@support_router.post("/admin/tickets/{ticket_id}/reply")
async def add_admin_reply(
    ticket_id: str,
    message: str = Query(..., description="Reply message"),
    send_email: bool = Query(True, description="Send email to user"),
    admin: dict = Depends(get_admin_user),
    service: SupportService = Depends(get_support_service)
):
    """
    Add an admin reply to a ticket.
    This is the Phase 1 human-in-the-loop action - admin sends response (optionally via email).
    """
    result = await service.add_reply(
        ticket_id=ticket_id,
        message=message,
        sender_type="admin",
        sender_name=admin.get("name", admin.get("email", "Support Team")),
        sender_email=admin.get("email"),
        send_email=send_email,
        admin_id=admin["id"]
    )
    
    if not result:
        raise HTTPException(status_code=404, detail="Ticket not found or reply failed")
    
    return {
        "success": True,
        "message_id": result["id"],
        "sent_via_email": result.get("sent_via_email", False)
    }


@support_router.post("/admin/tickets/{ticket_id}/approve-draft")
async def approve_ai_draft(
    ticket_id: str,
    edit_message: Optional[str] = Query(None, description="Optionally edit the AI draft before sending"),
    send_email: bool = Query(True),
    admin: dict = Depends(get_admin_user),
    service: SupportService = Depends(get_support_service)
):
    """
    Approve (and optionally edit) AI draft response and send to user.
    This is the key Phase 1 action - human reviews and approves AI draft.
    """
    ticket = await service.get_ticket(ticket_id)
    
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    # Use edited message or original AI draft
    message = edit_message if edit_message else ticket.get("ai_draft_response")
    
    if not message:
        raise HTTPException(status_code=400, detail="No draft response available")
    
    # Track if admin edited the draft (for AI accuracy metrics)
    was_edited = edit_message is not None and edit_message != ticket.get("ai_draft_response")
    
    result = await service.add_reply(
        ticket_id=ticket_id,
        message=message,
        sender_type="admin",
        sender_name=admin.get("name", admin.get("email", "Support Team")),
        sender_email=admin.get("email"),
        send_email=send_email,
        admin_id=admin["id"]
    )
    
    if not result:
        raise HTTPException(status_code=500, detail="Failed to send reply")
    
    # Update ticket status
    await service.update_ticket(
        ticket_id=ticket_id,
        updates={"status": TicketStatus.AWAITING_USER.value},
        admin_id=admin["id"]
    )
    
    # Log for AI learning
    await db.audit_logs.insert_one({
        "action": "ai_draft_approved",
        "admin_id": admin["id"],
        "admin_email": admin.get("email"),
        "ticket_id": ticket_id,
        "was_edited": was_edited,
        "ai_confidence": ticket.get("ai_draft_confidence"),
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    return {
        "success": True,
        "message_id": result["id"],
        "was_edited": was_edited,
        "sent_via_email": send_email
    }


@support_router.post("/admin/tickets/{ticket_id}/regenerate-draft")
async def regenerate_draft(
    ticket_id: str,
    admin: dict = Depends(get_admin_user),
    service: SupportService = Depends(get_support_service)
):
    """
    Regenerate AI draft response for a ticket.
    Useful when the initial draft is not satisfactory.
    """
    result = await service.regenerate_ai_draft(ticket_id)
    
    if not result:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    return {
        "success": True,
        "draft": result["draft"],
        "confidence": result["confidence"],
        "rationale": result["rationale"]
    }


@support_router.post("/admin/tickets/{ticket_id}/escalate")
async def escalate_ticket(
    ticket_id: str,
    reason: str = Query(..., description="Reason for escalation"),
    admin: dict = Depends(get_admin_user),
    service: SupportService = Depends(get_support_service)
):
    """
    Escalate a ticket for senior review.
    """
    success = await service.update_ticket(
        ticket_id=ticket_id,
        updates={
            "status": TicketStatus.ESCALATED.value,
            "internal_notes": f"[ESCALATED by {admin.get('email')}] {reason}"
        },
        admin_id=admin["id"],
        admin_email=admin.get("email")
    )
    
    if not success:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    return {"success": True, "message": "Ticket escalated"}


@support_router.post("/admin/tickets/{ticket_id}/resolve")
async def resolve_ticket(
    ticket_id: str,
    resolution_notes: Optional[str] = Query(None),
    admin: dict = Depends(get_admin_user),
    service: SupportService = Depends(get_support_service)
):
    """
    Mark a ticket as resolved.
    """
    updates = {"status": TicketStatus.RESOLVED.value}
    if resolution_notes:
        ticket = await service.get_ticket(ticket_id)
        if ticket:
            existing_notes = ticket.get("internal_notes", "")
            updates["internal_notes"] = f"{existing_notes}\n[RESOLVED] {resolution_notes}".strip()
    
    success = await service.update_ticket(
        ticket_id=ticket_id,
        updates=updates,
        admin_id=admin["id"],
        admin_email=admin.get("email")
    )
    
    if not success:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    return {"success": True, "message": "Ticket resolved"}


@support_router.post("/admin/tickets/{ticket_id}/close")
async def close_ticket(
    ticket_id: str,
    admin: dict = Depends(get_admin_user),
    service: SupportService = Depends(get_support_service)
):
    """
    Close a ticket (typically after resolution and no further response from user).
    """
    success = await service.update_ticket(
        ticket_id=ticket_id,
        updates={"status": TicketStatus.CLOSED.value},
        admin_id=admin["id"],
        admin_email=admin.get("email")
    )
    
    if not success:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    return {"success": True, "message": "Ticket closed"}


@support_router.post("/admin/tickets")
async def admin_create_ticket(
    request: AdminCreateTicketRequest,
    admin: dict = Depends(get_admin_user),
    service: SupportService = Depends(get_support_service)
):
    """
    Admin creates a ticket on behalf of a user (e.g., from phone call).
    """
    from models.support import TicketSource
    
    result = await service.create_ticket(
        name=request.user_name,
        email=request.user_email,
        subject=request.subject,
        message=request.message,
        source=TicketSource.ADMIN_CREATED
    )
    
    # Override category and priority if specified
    if request.category or request.priority:
        updates = {}
        if request.category:
            updates["category"] = request.category.value
        if request.priority:
            updates["priority"] = request.priority.value
        
        await service.update_ticket(
            ticket_id=result["ticket_id"],
            updates=updates,
            admin_id=admin["id"]
        )
    
    return result


# ==================== STATS ENDPOINT ====================

@support_router.get("/admin/stats")
async def get_support_stats(
    admin: dict = Depends(get_admin_user),
    service: SupportService = Depends(get_support_service)
):
    """
    Get support dashboard statistics.
    """
    return await service.get_stats()


# ==================== KNOWLEDGE BASE ENDPOINTS ====================

@support_router.get("/admin/kb")
async def get_kb_articles(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    category: Optional[str] = Query(None),
    active_only: bool = Query(False),
    search: Optional[str] = Query(None),
    admin: dict = Depends(get_admin_user),
    service: SupportService = Depends(get_support_service)
):
    """
    Get paginated knowledge base articles.
    """
    return await service.get_kb_articles(
        page=page,
        limit=limit,
        category=category,
        active_only=active_only,
        search=search
    )


@support_router.post("/admin/kb")
async def create_kb_article(
    request: CreateKBArticleRequest,
    admin: dict = Depends(get_admin_user),
    service: SupportService = Depends(get_support_service)
):
    """
    Create a new knowledge base article.
    """
    article = await service.create_kb_article(
        question=request.question,
        answer=request.answer,
        category=request.category.value,
        active=request.active
    )
    
    # Log action
    await db.audit_logs.insert_one({
        "action": "kb_article_created",
        "admin_id": admin["id"],
        "admin_email": admin.get("email"),
        "article_id": article["id"],
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    return {"success": True, "article": article}


@support_router.put("/admin/kb/{article_id}")
async def update_kb_article(
    article_id: str,
    question: Optional[str] = Query(None),
    answer: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    active: Optional[bool] = Query(None),
    admin: dict = Depends(get_admin_user),
    service: SupportService = Depends(get_support_service)
):
    """
    Update a knowledge base article.
    """
    updates = {}
    if question is not None:
        updates["question"] = question
    if answer is not None:
        updates["answer"] = answer
    if category is not None:
        updates["category"] = category
    if active is not None:
        updates["active"] = active
    
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")
    
    success = await service.update_kb_article(article_id, updates)
    
    if not success:
        raise HTTPException(status_code=404, detail="Article not found")
    
    # Log action
    await db.audit_logs.insert_one({
        "action": "kb_article_updated",
        "admin_id": admin["id"],
        "admin_email": admin.get("email"),
        "article_id": article_id,
        "updates": list(updates.keys()),
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    return {"success": True, "message": "Article updated"}


@support_router.delete("/admin/kb/{article_id}")
async def delete_kb_article(
    article_id: str,
    admin: dict = Depends(get_admin_user),
    service: SupportService = Depends(get_support_service)
):
    """
    Delete a knowledge base article.
    """
    success = await service.delete_kb_article(article_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Article not found")
    
    # Log action
    await db.audit_logs.insert_one({
        "action": "kb_article_deleted",
        "admin_id": admin["id"],
        "admin_email": admin.get("email"),
        "article_id": article_id,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    return {"success": True, "message": "Article deleted"}


# ==================== CATEGORY/STATUS LISTS ====================

@support_router.get("/meta/categories")
async def get_categories():
    """Get list of ticket categories"""
    return {
        "categories": [
            {"value": c.value, "label": c.value.replace("_", " ").title()}
            for c in TicketCategory
        ]
    }


@support_router.get("/meta/statuses")
async def get_statuses():
    """Get list of ticket statuses"""
    return {
        "statuses": [
            {"value": s.value, "label": s.value.replace("_", " ").title()}
            for s in TicketStatus
        ]
    }


@support_router.get("/meta/priorities")
async def get_priorities():
    """Get list of ticket priorities"""
    return {
        "priorities": [
            {"value": p.value, "label": p.value.title()}
            for p in TicketPriority
        ]
    }


# ==================== PHASE 2: INBOUND EMAIL WEBHOOK ====================

@support_router.post("/inbound-email")
async def handle_inbound_email(
    request: dict,
    service: SupportService = Depends(get_support_service)
):
    """
    Webhook endpoint for Resend inbound emails.
    Parses incoming email and adds to existing ticket or creates new one.
    
    Resend sends: { type: "email.received", data: { from, to, subject, text, html, ... } }
    """
    import re
    
    try:
        event_type = request.get("type")
        
        if event_type != "email.received":
            logger.info(f"Ignoring non-inbound event: {event_type}")
            return {"status": "ignored", "reason": f"Event type {event_type} not handled"}
        
        data = request.get("data", {})
        
        # Extract email details
        from_email = data.get("from", "")
        # Handle format: "Name <email@example.com>" or just "email@example.com"
        email_match = re.search(r'[\w\.-]+@[\w\.-]+', from_email)
        sender_email = email_match.group(0) if email_match else from_email
        
        # Try to extract name from "Name <email>" format
        name_match = re.match(r'^([^<]+)<', from_email)
        sender_name = name_match.group(1).strip() if name_match else sender_email.split('@')[0]
        
        subject = data.get("subject", "")
        message_text = data.get("text", "") or data.get("html", "")
        
        # Try to match to existing ticket via ticket number in subject
        # Format: Re: [CCE-0001] Original Subject
        ticket_match = re.search(r'\[?(CCE-\d+)\]?', subject)
        
        if ticket_match:
            ticket_number = ticket_match.group(1)
            ticket = await service.get_ticket(ticket_number)
            
            if ticket and ticket["user_email"].lower() == sender_email.lower():
                # Add reply to existing ticket
                result = await service.add_reply(
                    ticket_id=ticket["id"],
                    message=message_text,
                    sender_type="user",
                    sender_name=sender_name,
                    sender_email=sender_email,
                    send_email=False
                )
                
                logger.info(f"Added user reply to ticket {ticket_number} from {sender_email}")
                return {
                    "status": "reply_added",
                    "ticket_number": ticket_number,
                    "message_id": result["id"] if result else None
                }
        
        # No matching ticket found - create new ticket
        # Clean subject (remove Re:, Fwd:, ticket numbers)
        clean_subject = re.sub(r'^(Re:|Fwd:|FW:)\s*', '', subject, flags=re.IGNORECASE)
        clean_subject = re.sub(r'\[CCE-\d+\]\s*', '', clean_subject).strip()
        
        result = await service.create_ticket(
            name=sender_name,
            email=sender_email,
            subject=clean_subject or "Email Inquiry",
            message=message_text,
            source=TicketSource.EMAIL
        )
        
        logger.info(f"Created new ticket {result['ticket_number']} from inbound email {sender_email}")
        return {
            "status": "ticket_created",
            "ticket_number": result["ticket_number"],
            "ticket_id": result["ticket_id"]
        }
        
    except Exception as e:
        logger.error(f"Error processing inbound email: {e}")
        # Return 200 to prevent Resend from retrying
        return {"status": "error", "reason": str(e)}


# ==================== PHASE 2: AUTO-RESPONSE SETTINGS ====================

@support_router.get("/admin/auto-response-settings")
async def get_auto_response_settings(
    admin: dict = Depends(get_admin_user)
):
    """Get auto-response configuration"""
    settings = await db.admin_settings.find_one(
        {"type": "support_auto_response"},
        {"_id": 0}
    )
    
    if not settings:
        # Return defaults
        return {
            "enabled": False,
            "delay_minutes": 60,
            "min_confidence": 85,
            "allowed_sentiments": ["positive", "neutral"],
            "allowed_categories": ["general", "how_it_works", "educational"],
            "excluded_categories": ["billing", "bug_report", "technical"]
        }
    
    return settings


@support_router.put("/admin/auto-response-settings")
async def update_auto_response_settings(
    enabled: bool = Query(...),
    delay_minutes: int = Query(60, ge=0, le=1440),
    min_confidence: int = Query(85, ge=50, le=100),
    allowed_categories: str = Query("general,how_it_works,educational"),
    admin: dict = Depends(get_admin_user)
):
    """Update auto-response configuration"""
    settings = {
        "type": "support_auto_response",
        "enabled": enabled,
        "delay_minutes": delay_minutes,
        "min_confidence": min_confidence,
        "allowed_categories": allowed_categories.split(","),
        "excluded_categories": ["billing", "bug_report", "technical"],  # Always excluded
        "allowed_sentiments": ["positive", "neutral"],  # Negative always requires human
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": admin.get("email")
    }
    
    await db.admin_settings.update_one(
        {"type": "support_auto_response"},
        {"$set": settings},
        upsert=True
    )
    
    logger.info(f"Auto-response settings updated by {admin.get('email')}: enabled={enabled}, delay={delay_minutes}min")
    
    return {"success": True, "settings": settings}


@support_router.post("/admin/process-auto-responses")
async def trigger_auto_response_processing(
    admin: dict = Depends(get_admin_user),
    service: SupportService = Depends(get_support_service)
):
    """
    Manually trigger auto-response processing (for testing).
    In production, this runs via scheduler.
    """
    result = await service.process_pending_auto_responses()
    return result
