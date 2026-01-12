"""
Support Service for Covered Call Engine
Handles ticket creation, AI classification, draft response generation, and email sending
Phase 1: Human-in-the-loop - All AI responses require admin approval before sending
"""
import os
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from uuid import uuid4

from models.support import (
    TicketStatus, TicketCategory, TicketSentiment, TicketPriority, TicketSource,
    AIClassificationResult, AIDraftResponse, TicketResponse, TicketListItem, TicketMessage
)

logger = logging.getLogger(__name__)


# AI System prompts
CLASSIFICATION_SYSTEM_PROMPT = """You are a support ticket classifier for Covered Call Engine, a web application for options trading strategies (Covered Calls and Poor Man's Covered Calls - PMCC).

Your task is to analyze incoming support tickets and provide:
1. Category - The topic/area of the inquiry
2. Sentiment - The emotional tone of the user
3. Priority - How urgent this ticket should be handled
4. Confidence Score - How confident you are in your classification (0-100)
5. Auto-response eligibility - Whether this ticket can be auto-responded (Phase 2 feature)

Categories:
- general: General questions about the platform
- billing: Payment, subscription, pricing questions
- technical: Technical issues, errors, bugs
- bug_report: Specific bug reports with reproduction steps
- feature_request: Feature suggestions
- screener: Questions about the Covered Call screener
- pmcc: Questions about PMCC (Poor Man's Covered Call) strategy
- simulator: Questions about the Trade Simulator
- portfolio: Questions about Portfolio tracking
- account: Account-related issues (login, profile, etc.)
- how_it_works: Educational questions about how features work
- educational: General trading education questions

Priority Guidelines:
- urgent: User cannot access account, payment issues blocking access, data loss
- high: Feature not working, incorrect data shown, billing disputes
- normal: General questions, feature requests, educational queries
- low: Feedback, minor suggestions, questions answered in FAQ

Auto-response eligible (Phase 2):
- ONLY if confidence >= 85%
- ONLY if sentiment is neutral or positive
- ONLY for categories: general, how_it_works, educational
- NEVER for: billing, bug_report, technical (these always need human review)

Respond with valid JSON only."""

DRAFT_RESPONSE_SYSTEM_PROMPT = """You are a support agent for Covered Call Engine (CCE), an options trading web app.

CRITICAL: Keep responses SHORT and DIRECT. Aim for 3-5 sentences max. No fluff.

FORMAT (use blank lines between sections):
```
Hi [Name],

[Direct answer - 1-3 sentences with proper paragraph breaks]

[Next step if needed]

Best Wishes,
The CCE Team
```

BUSINESS RULES (MUST FOLLOW):

1. REFUNDS: We have a strict NO REFUND policy stated in our Terms of Service.
   - First request: Politely decline and link to Terms: https://coveredcallengine.com/terms
   - Repeat requests from same customer: Escalate to human review
   
2. DATA SOURCES: Never reveal specific data providers.
   - Say: "Our data is provided by third-party providers with whom we have performed due diligence."
   
3. FILTER SETUP: You can EXPLAIN how filters work, but you CANNOT configure user accounts.
   - Offer guidance on filter settings, not promises to set them up
   
4. INCLUDE RELEVANT LINKS:
   - Privacy Policy: https://coveredcallengine.com/privacy
   - Terms of Service: https://coveredcallengine.com/terms
   - Contact: https://coveredcallengine.com/contact

EXAMPLES:

Refund request:
"Hi John,

Thank you for reaching out. Our Terms of Service outline a strict no-refund policy, which you can review here: https://coveredcallengine.com/terms

If you have concerns about your subscription, we're happy to help troubleshoot any issues you're experiencing.

Best Wishes,
The CCE Team"

Data source question:
"Hi Sarah,

Our market data is provided by third-party providers with whom we have performed due diligence to ensure accuracy and reliability.

Best Wishes,
The CCE Team"

RULES:
- NO lengthy explanations
- NO repeating their question back
- DO use blank lines between greeting, body, and sign-off
- DO include relevant URLs when applicable
- If customer persists on refund, flag for escalation

MUST NOT: Give financial advice, recommend specific trades, reveal data sources, promise refunds.

Respond with JSON:
- draft_content: The formatted email response (use \\n\\n for paragraph breaks)
- confidence_score: 0-100 based on how confident you are
- needs_human_review: true/false (default true for Phase 1)
- flagged_for_escalation: true if this needs senior review
- escalation_reason: reason for escalation if flagged"""


class SupportService:
    """Service for managing support tickets with AI assistance"""
    
    # Support email configuration - uses subdomain for inbound email routing
    # Replies to this address will be received by Resend and forwarded to our webhook
    SUPPORT_EMAIL = "support@tickets.coveredcallengine.com"
    SUPPORT_NAME = "CCE Support"
    
    def __init__(self, db):
        self.db = db
        self.llm_key = os.environ.get("EMERGENT_LLM_KEY")
        self._ticket_counter = None
    
    def get_support_from_address(self) -> str:
        """Get the formatted support from address"""
        return f"{self.SUPPORT_NAME} <{self.SUPPORT_EMAIL}>"
    
    async def _get_next_ticket_number(self) -> str:
        """Generate sequential ticket number like CCE-0001"""
        counter = await self.db.counters.find_one_and_update(
            {"_id": "support_ticket"},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=True
        )
        seq = counter.get("seq", 1)
        return f"CCE-{seq:04d}"
    
    async def _get_knowledge_base(self, category: Optional[TicketCategory] = None) -> List[Dict]:
        """Get active KB articles, optionally filtered by category"""
        query = {"active": True}
        if category:
            query["category"] = category.value
        
        articles = await self.db.knowledge_base.find(
            query, 
            {"_id": 0, "id": 1, "question": 1, "answer": 1, "category": 1}
        ).limit(20).to_list(20)
        
        return articles
    
    async def _call_llm(self, system_prompt: str, user_message: str) -> Optional[Dict]:
        """Call LLM for classification or draft generation"""
        if not self.llm_key:
            logger.warning("No EMERGENT_LLM_KEY configured - AI features disabled")
            return None
        
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage
            
            chat = LlmChat(
                api_key=self.llm_key,
                session_id=f"support-{uuid4()}",
                system_message=system_prompt
            ).with_model("openai", "gpt-5.2")
            
            response = await chat.send_message(UserMessage(text=user_message))
            
            # Parse JSON from response
            # Handle case where response might have markdown code blocks
            response_text = response.strip()
            if response_text.startswith("```"):
                # Remove markdown code blocks
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
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return None
    
    async def classify_ticket(self, subject: str, message: str) -> AIClassificationResult:
        """Classify a ticket using AI"""
        user_prompt = f"""Classify this support ticket:

Subject: {subject}
Message: {message}

Respond with JSON in this exact format:
{{
    "category": "string (one of: general, billing, technical, bug_report, feature_request, screener, pmcc, simulator, portfolio, account, how_it_works, educational)",
    "sentiment": "string (positive, neutral, or negative)",
    "priority": "string (low, normal, high, or urgent)",
    "confidence_score": number (0-100),
    "rationale": "string explaining your classification",
    "auto_response_eligible": boolean
}}"""
        
        result = await self._call_llm(CLASSIFICATION_SYSTEM_PROMPT, user_prompt)
        
        if not result:
            # Fallback to defaults if AI fails
            return AIClassificationResult(
                category=TicketCategory.GENERAL,
                sentiment=TicketSentiment.NEUTRAL,
                priority=TicketPriority.NORMAL,
                confidence_score=0,
                rationale="AI classification unavailable - using defaults",
                auto_response_eligible=False,
                kb_articles_referenced=[]
            )
        
        try:
            return AIClassificationResult(
                category=TicketCategory(result.get("category", "general")),
                sentiment=TicketSentiment(result.get("sentiment", "neutral")),
                priority=TicketPriority(result.get("priority", "normal")),
                confidence_score=result.get("confidence_score", 50),
                rationale=result.get("rationale", ""),
                auto_response_eligible=result.get("auto_response_eligible", False),
                kb_articles_referenced=result.get("kb_articles_referenced", [])
            )
        except ValueError as e:
            logger.warning(f"Invalid enum value from AI: {e}")
            return AIClassificationResult(
                category=TicketCategory.GENERAL,
                sentiment=TicketSentiment.NEUTRAL,
                priority=TicketPriority.NORMAL,
                confidence_score=30,
                rationale=f"AI returned invalid category: {result}",
                auto_response_eligible=False,
                kb_articles_referenced=[]
            )
    
    async def generate_draft_response(
        self, 
        user_name: str,
        user_email: str,
        subject: str, 
        message: str,
        category: TicketCategory,
        ticket_history: List[Dict] = None
    ) -> AIDraftResponse:
        """Generate an AI draft response for a ticket"""
        
        # Get relevant KB articles
        kb_articles = await self._get_knowledge_base(category)
        kb_context = ""
        if kb_articles:
            kb_context = "\n\nKNOWLEDGE BASE ARTICLES:\n"
            for article in kb_articles[:5]:  # Limit to 5 most relevant
                kb_context += f"\nQ: {article['question']}\nA: {article['answer']}\n---"
        
        # Include conversation history if available
        history_context = ""
        if ticket_history:
            history_context = "\n\nPREVIOUS MESSAGES IN THIS TICKET:\n"
            for msg in ticket_history[-5:]:  # Last 5 messages
                history_context += f"\n[{msg['sender_type'].upper()}] {msg['content']}\n---"
        
        user_prompt = f"""Draft a professional support response for this ticket:

USER NAME: {user_name}
USER EMAIL: {user_email}
CATEGORY: {category.value}
SUBJECT: {subject}
MESSAGE: {message}
{history_context}
{kb_context}

Respond with JSON in this exact format:
{{
    "draft_content": "string (the full email response)",
    "confidence_score": number (0-100),
    "rationale": "string explaining your approach",
    "kb_articles_used": ["list of KB article IDs used"],
    "needs_human_review": true,
    "flagged_for_escalation": boolean,
    "escalation_reason": "string or null"
}}"""
        
        result = await self._call_llm(DRAFT_RESPONSE_SYSTEM_PROMPT, user_prompt)
        
        if not result:
            # Fallback template if AI fails
            default_draft = f"""Hi {user_name},

Thank you for reaching out to Covered Call Engine support.

We have received your inquiry regarding "{subject}" and our team is reviewing it.

We will get back to you as soon as possible with a detailed response.

Best regards,
The Covered Call Engine Team"""
            
            return AIDraftResponse(
                draft_content=default_draft,
                confidence_score=0,
                rationale="AI draft generation unavailable - using template",
                kb_articles_used=[],
                needs_human_review=True,
                flagged_for_escalation=True,
                escalation_reason="AI unavailable - manual response required"
            )
        
        return AIDraftResponse(
            draft_content=result.get("draft_content", ""),
            confidence_score=result.get("confidence_score", 50),
            rationale=result.get("rationale", ""),
            kb_articles_used=result.get("kb_articles_used", []),
            needs_human_review=result.get("needs_human_review", True),
            flagged_for_escalation=result.get("flagged_for_escalation", False),
            escalation_reason=result.get("escalation_reason")
        )
    
    async def create_ticket(
        self,
        name: str,
        email: str,
        subject: str,
        message: str,
        source: TicketSource = TicketSource.CONTACT_FORM
    ) -> Dict:
        """Create a new support ticket with AI classification and draft response"""
        now = datetime.now(timezone.utc).isoformat()
        ticket_number = await self._get_next_ticket_number()
        ticket_id = str(uuid4())
        
        # AI Classification
        classification = await self.classify_ticket(subject, message)
        
        # AI Draft Response
        draft = await self.generate_draft_response(
            user_name=name,
            user_email=email,
            subject=subject,
            message=message,
            category=classification.category
        )
        
        # Determine initial status based on AI results
        if draft.flagged_for_escalation:
            initial_status = TicketStatus.ESCALATED
        elif classification.confidence_score >= 70 and draft.confidence_score >= 70:
            initial_status = TicketStatus.AI_DRAFTED
        else:
            initial_status = TicketStatus.AWAITING_HUMAN_REVIEW
        
        # Create initial message
        initial_message = {
            "id": str(uuid4()),
            "sender_type": "user",
            "sender_name": name,
            "sender_email": email,
            "content": message,
            "is_ai_draft": False,
            "created_at": now,
            "sent_via_email": source == TicketSource.EMAIL
        }
        
        ticket = {
            "id": ticket_id,
            "ticket_number": ticket_number,
            
            # User info
            "user_name": name,
            "user_email": email,
            
            # Content
            "subject": subject or "General Inquiry",
            "original_message": message,
            
            # Classification
            "status": initial_status.value,
            "category": classification.category.value,
            "sentiment": classification.sentiment.value,
            "priority": classification.priority.value,
            "source": source.value,
            
            # AI metadata
            "ai_classification": {
                "category": classification.category.value,
                "sentiment": classification.sentiment.value,
                "priority": classification.priority.value,
                "confidence_score": classification.confidence_score,
                "rationale": classification.rationale,
                "auto_response_eligible": classification.auto_response_eligible
            },
            "ai_draft_response": draft.draft_content,
            "ai_draft_confidence": draft.confidence_score,
            "ai_draft_rationale": draft.rationale,
            "ai_escalation_reason": draft.escalation_reason,
            "auto_response_eligible": classification.auto_response_eligible and draft.confidence_score >= 85,
            
            # Thread
            "messages": [initial_message],
            
            # Admin
            "assigned_to": None,
            "internal_notes": "",
            
            # Timestamps
            "created_at": now,
            "updated_at": now,
            "first_response_at": None,
            "resolved_at": None
        }
        
        await self.db.support_tickets.insert_one(ticket)
        
        # Send auto-acknowledgment email to user
        await self._send_acknowledgment_email(name, email, ticket_number, subject)
        
        return {
            "ticket_id": ticket_id,
            "ticket_number": ticket_number,
            "status": initial_status.value,
            "message": "Your message has been received. We'll get back to you soon."
        }
    
    async def _send_acknowledgment_email(
        self, 
        name: str, 
        email: str, 
        ticket_number: str, 
        subject: str
    ):
        """Send auto-acknowledgment email to user"""
        try:
            from services.email_service import EmailService
            email_service = EmailService(self.db)
            
            if await email_service.initialize():
                html_content = f"""
                <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #09090b; color: #ffffff;">
                    <div style="text-align: center; padding: 20px 0; border-bottom: 1px solid #27272a;">
                        <h1 style="color: #10b981; margin: 0;">Covered Call Engine</h1>
                    </div>
                    <div style="padding: 30px 20px;">
                        <h2 style="color: #ffffff; margin-bottom: 20px;">We've Received Your Message</h2>
                        <p style="color: #a1a1aa; line-height: 1.6;">
                            Hi {name},
                        </p>
                        <p style="color: #a1a1aa; line-height: 1.6;">
                            Thank you for contacting Covered Call Engine support. We've received your inquiry and our team is reviewing it.
                        </p>
                        <div style="background-color: #18181b; border-radius: 8px; padding: 20px; margin: 20px 0;">
                            <p style="color: #71717a; margin: 5px 0; font-size: 14px;">Ticket Reference:</p>
                            <p style="color: #10b981; margin: 5px 0; font-size: 20px; font-weight: bold;">{ticket_number}</p>
                            <p style="color: #71717a; margin: 15px 0 5px 0; font-size: 14px;">Subject:</p>
                            <p style="color: #ffffff; margin: 5px 0;">{subject}</p>
                        </div>
                        <p style="color: #a1a1aa; line-height: 1.6;">
                            We typically respond within 24 hours during business days. For urgent matters, please include "URGENT" in your subject line.
                        </p>
                        <p style="color: #a1a1aa; line-height: 1.6;">
                            Best regards,<br>
                            <strong style="color: #10b981;">The Covered Call Engine Team</strong>
                        </p>
                    </div>
                    <div style="text-align: center; padding: 20px; border-top: 1px solid #27272a; color: #71717a; font-size: 12px;">
                        © 2025 Covered Call Engine. All rights reserved.<br>
                        <a href="https://coveredcallengine.com" style="color: #10b981; text-decoration: none;">coveredcallengine.com</a>
                    </div>
                </div>
                """
                
                await email_service.send_raw_email(
                    to_email=email,
                    subject=f"[{ticket_number}] We've received your message - {subject}",
                    html_content=html_content
                )
        except Exception as e:
            logger.warning(f"Failed to send acknowledgment email: {e}")
    
    async def get_ticket(self, ticket_id: str) -> Optional[Dict]:
        """Get a single ticket by ID"""
        ticket = await self.db.support_tickets.find_one(
            {"$or": [{"id": ticket_id}, {"ticket_number": ticket_id}]},
            {"_id": 0}
        )
        return ticket
    
    async def get_tickets(
        self,
        page: int = 1,
        limit: int = 20,
        status: Optional[str] = None,
        category: Optional[str] = None,
        priority: Optional[str] = None,
        sentiment: Optional[str] = None,
        search: Optional[str] = None,
        assigned_to: Optional[str] = None
    ) -> Dict:
        """Get paginated list of tickets with filters"""
        query = {}
        
        if status and status != "all":
            query["status"] = status
        if category and category != "all":
            query["category"] = category
        if priority and priority != "all":
            query["priority"] = priority
        if sentiment and sentiment != "all":
            query["sentiment"] = sentiment
        if assigned_to:
            query["assigned_to"] = assigned_to
        if search:
            query["$or"] = [
                {"subject": {"$regex": search, "$options": "i"}},
                {"user_email": {"$regex": search, "$options": "i"}},
                {"user_name": {"$regex": search, "$options": "i"}},
                {"ticket_number": {"$regex": search, "$options": "i"}}
            ]
        
        skip = (page - 1) * limit
        
        tickets = await self.db.support_tickets.find(
            query,
            {"_id": 0, "messages": 0, "ai_classification": 0, "ai_draft_rationale": 0}
        ).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
        
        total = await self.db.support_tickets.count_documents(query)
        
        # Transform to list items
        ticket_list = []
        for t in tickets:
            ticket_list.append({
                "id": t.get("id"),
                "ticket_number": t.get("ticket_number"),
                "user_name": t.get("user_name"),
                "user_email": t.get("user_email"),
                "subject": t.get("subject"),
                "status": t.get("status"),
                "category": t.get("category"),
                "sentiment": t.get("sentiment"),
                "priority": t.get("priority"),
                "source": t.get("source"),
                "ai_confidence_score": t.get("ai_draft_confidence"),
                "message_count": len(t.get("messages", [])) if "messages" in t else 1,
                "created_at": t.get("created_at"),
                "updated_at": t.get("updated_at")
            })
        
        return {
            "tickets": ticket_list,
            "total": total,
            "page": page,
            "pages": (total + limit - 1) // limit if total > 0 else 1
        }
    
    async def update_ticket(
        self,
        ticket_id: str,
        updates: Dict,
        admin_id: str = None,
        admin_email: str = None
    ) -> bool:
        """Update ticket fields"""
        now = datetime.now(timezone.utc).isoformat()
        updates["updated_at"] = now
        
        # Track status changes for metrics
        if "status" in updates:
            if updates["status"] == TicketStatus.RESOLVED.value:
                updates["resolved_at"] = now
        
        result = await self.db.support_tickets.update_one(
            {"$or": [{"id": ticket_id}, {"ticket_number": ticket_id}]},
            {"$set": updates}
        )
        
        # Log admin action
        if admin_id:
            await self.db.audit_logs.insert_one({
                "action": "ticket_updated",
                "admin_id": admin_id,
                "admin_email": admin_email,
                "ticket_id": ticket_id,
                "updates": list(updates.keys()),
                "timestamp": now
            })
        
        return result.modified_count > 0
    
    async def add_reply(
        self,
        ticket_id: str,
        message: str,
        sender_type: str,
        sender_name: str,
        sender_email: str = None,
        is_ai_draft: bool = False,
        send_email: bool = True,
        admin_id: str = None
    ) -> Optional[Dict]:
        """Add a reply to a ticket thread"""
        now = datetime.now(timezone.utc).isoformat()
        
        ticket = await self.get_ticket(ticket_id)
        if not ticket:
            return None
        
        new_message = {
            "id": str(uuid4()),
            "sender_type": sender_type,
            "sender_name": sender_name,
            "sender_email": sender_email,
            "content": message,
            "is_ai_draft": is_ai_draft,
            "created_at": now,
            "sent_via_email": False
        }
        
        # Update status based on sender
        new_status = ticket["status"]
        updates = {
            "updated_at": now
        }
        
        if sender_type == "admin":
            if ticket.get("first_response_at") is None:
                updates["first_response_at"] = now
            new_status = TicketStatus.AWAITING_USER.value
            
            # Send email to user if requested
            if send_email:
                await self._send_reply_email(
                    to_email=ticket["user_email"],
                    user_name=ticket["user_name"],
                    ticket_number=ticket["ticket_number"],
                    subject=ticket["subject"],
                    message=message
                )
                new_message["sent_via_email"] = True
        
        elif sender_type == "user":
            # User replied - ticket needs attention again
            if ticket["status"] in [TicketStatus.AWAITING_USER.value, TicketStatus.RESOLVED.value]:
                new_status = TicketStatus.NEW.value
        
        updates["status"] = new_status
        
        result = await self.db.support_tickets.update_one(
            {"$or": [{"id": ticket_id}, {"ticket_number": ticket_id}]},
            {
                "$push": {"messages": new_message},
                "$set": updates
            }
        )
        
        # Log if admin action
        if admin_id and sender_type == "admin":
            await self.db.audit_logs.insert_one({
                "action": "ticket_reply_sent",
                "admin_id": admin_id,
                "ticket_id": ticket_id,
                "sent_email": send_email,
                "timestamp": now
            })
        
        if result.modified_count > 0:
            return new_message
        return None
    
    async def _send_reply_email(
        self,
        to_email: str,
        user_name: str,
        ticket_number: str,
        subject: str,
        message: str
    ):
        """Send reply email to user with proper formatting and logo"""
        try:
            from services.email_service import EmailService
            email_service = EmailService(self.db)
            
            if await email_service.initialize():
                # Convert line breaks to HTML paragraphs for proper spacing
                paragraphs = message.split('\n\n')
                html_paragraphs = []
                for p in paragraphs:
                    if p.strip():
                        # Convert single line breaks within paragraphs
                        p_html = p.replace('\n', '<br>')
                        html_paragraphs.append(f'<p style="margin: 0 0 16px 0; line-height: 1.6;">{p_html}</p>')
                html_message = ''.join(html_paragraphs)
                
                # Logo URL
                logo_url = "https://customer-assets.emergentagent.com/job_optiontrader-9/artifacts/cg2ri3n1_Logo%20CCE.JPG"
                
                html_content = f"""
                <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #09090b; color: #ffffff;">
                    <div style="padding: 30px 20px;">
                        <p style="color: #71717a; font-size: 12px; margin-bottom: 20px;">
                            Reference: {ticket_number}
                        </p>
                        <div style="color: #e4e4e7;">
                            {html_message}
                        </div>
                        <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #27272a;">
                            <img src="{logo_url}" alt="Covered Call Engine" style="height: 40px; margin-bottom: 10px;" />
                            <p style="color: #71717a; font-size: 12px; margin: 0;">
                                <a href="https://coveredcallengine.com" style="color: #10b981; text-decoration: none;">coveredcallengine.com</a>
                            </p>
                        </div>
                    </div>
                </div>
                """
                
                # Send from support subdomain so replies route back to Resend webhook
                result = await email_service.send_raw_email(
                    to_email=to_email,
                    subject=f"Re: [{ticket_number}] {subject}",
                    html_content=html_content,
                    from_email=self.get_support_from_address(),
                    reply_to=self.SUPPORT_EMAIL
                )
                logger.info(f"Reply email sent to {to_email} from {self.SUPPORT_EMAIL}: {result}")
                return result
            else:
                logger.warning("Email service not initialized - email not sent")
                return None
        except Exception as e:
            logger.error(f"Failed to send reply email: {e}")
            raise  # Re-raise to surface the error
    
    async def regenerate_ai_draft(self, ticket_id: str) -> Optional[Dict]:
        """Regenerate AI draft for a ticket"""
        ticket = await self.get_ticket(ticket_id)
        if not ticket:
            return None
        
        # Get conversation history
        messages = ticket.get("messages", [])
        
        draft = await self.generate_draft_response(
            user_name=ticket["user_name"],
            user_email=ticket["user_email"],
            subject=ticket["subject"],
            message=ticket["original_message"],
            category=TicketCategory(ticket["category"]),
            ticket_history=messages
        )
        
        now = datetime.now(timezone.utc).isoformat()
        
        await self.db.support_tickets.update_one(
            {"id": ticket_id},
            {"$set": {
                "ai_draft_response": draft.draft_content,
                "ai_draft_confidence": draft.confidence_score,
                "ai_draft_rationale": draft.rationale,
                "updated_at": now
            }}
        )
        
        return {
            "draft": draft.draft_content,
            "confidence": draft.confidence_score,
            "rationale": draft.rationale
        }
    
    async def get_stats(self) -> Dict:
        """Get support dashboard statistics"""
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        
        total = await self.db.support_tickets.count_documents({})
        
        # Open statuses
        open_statuses = [
            TicketStatus.NEW.value,
            TicketStatus.AI_DRAFTED.value,
            TicketStatus.AWAITING_HUMAN_REVIEW.value,
            TicketStatus.ESCALATED.value
        ]
        open_count = await self.db.support_tickets.count_documents({"status": {"$in": open_statuses}})
        
        awaiting_review = await self.db.support_tickets.count_documents({
            "status": {"$in": [TicketStatus.AI_DRAFTED.value, TicketStatus.AWAITING_HUMAN_REVIEW.value]}
        })
        
        resolved_today = await self.db.support_tickets.count_documents({
            "resolved_at": {"$gte": today_start}
        })
        
        # Status breakdown
        status_pipeline = [
            {"$group": {"_id": "$status", "count": {"$sum": 1}}}
        ]
        status_results = await self.db.support_tickets.aggregate(status_pipeline).to_list(20)
        tickets_by_status = {r["_id"]: r["count"] for r in status_results}
        
        # Category breakdown
        category_pipeline = [
            {"$group": {"_id": "$category", "count": {"$sum": 1}}}
        ]
        category_results = await self.db.support_tickets.aggregate(category_pipeline).to_list(20)
        tickets_by_category = {r["_id"]: r["count"] for r in category_results}
        
        # Sentiment breakdown
        sentiment_pipeline = [
            {"$group": {"_id": "$sentiment", "count": {"$sum": 1}}}
        ]
        sentiment_results = await self.db.support_tickets.aggregate(sentiment_pipeline).to_list(10)
        tickets_by_sentiment = {r["_id"]: r["count"] for r in sentiment_results}
        
        return {
            "total_tickets": total,
            "open_tickets": open_count,
            "awaiting_review": awaiting_review,
            "resolved_today": resolved_today,
            "avg_response_time_hours": 0,  # TODO: Calculate from first_response_at
            "avg_resolution_time_hours": 0,  # TODO: Calculate from resolved_at
            "ai_draft_accuracy": 0,  # TODO: Track approvals vs edits
            "tickets_by_status": tickets_by_status,
            "tickets_by_category": tickets_by_category,
            "tickets_by_sentiment": tickets_by_sentiment
        }
    
    # ==================== KNOWLEDGE BASE ====================
    async def create_kb_article(
        self,
        question: str,
        answer: str,
        category: str,
        active: bool = True
    ) -> Dict:
        """Create a new KB article"""
        now = datetime.now(timezone.utc).isoformat()
        article_id = str(uuid4())
        
        article = {
            "id": article_id,
            "question": question,
            "answer": answer,
            "category": category,
            "active": active,
            "created_at": now,
            "updated_at": now,
            "usage_count": 0
        }
        
        await self.db.knowledge_base.insert_one(article)
        
        # Return without _id
        article.pop("_id", None)
        return article
    
    async def get_kb_articles(
        self,
        page: int = 1,
        limit: int = 20,
        category: Optional[str] = None,
        active_only: bool = False,
        search: Optional[str] = None
    ) -> Dict:
        """Get paginated KB articles"""
        query = {}
        
        if category and category != "all":
            query["category"] = category
        if active_only:
            query["active"] = True
        if search:
            query["$or"] = [
                {"question": {"$regex": search, "$options": "i"}},
                {"answer": {"$regex": search, "$options": "i"}}
            ]
        
        skip = (page - 1) * limit
        
        articles = await self.db.knowledge_base.find(
            query, {"_id": 0}
        ).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
        
        total = await self.db.knowledge_base.count_documents(query)
        
        return {
            "articles": articles,
            "total": total,
            "page": page,
            "pages": (total + limit - 1) // limit if total > 0 else 1
        }
    
    async def update_kb_article(self, article_id: str, updates: Dict) -> bool:
        """Update a KB article"""
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        
        result = await self.db.knowledge_base.update_one(
            {"id": article_id},
            {"$set": updates}
        )
        return result.modified_count > 0
    
    async def delete_kb_article(self, article_id: str) -> bool:
        """Delete a KB article"""
        result = await self.db.knowledge_base.delete_one({"id": article_id})
        return result.deleted_count > 0
    
    # ==================== PHASE 2: AUTO-RESPONSE ====================
    
    async def process_pending_auto_responses(self) -> Dict:
        """
        Process tickets eligible for auto-response.
        Called by scheduler every few minutes.
        Returns count of processed tickets.
        """
        # Get auto-response settings
        settings = await self.db.admin_settings.find_one(
            {"type": "support_auto_response"},
            {"_id": 0}
        )
        
        if not settings or not settings.get("enabled", False):
            return {"processed": 0, "reason": "Auto-response disabled"}
        
        delay_minutes = settings.get("delay_minutes", 60)
        min_confidence = settings.get("min_confidence", 85)
        allowed_categories = settings.get("allowed_categories", ["general", "how_it_works", "educational"])
        allowed_sentiments = settings.get("allowed_sentiments", ["positive", "neutral"])
        
        # Calculate cutoff time (tickets older than delay_minutes)
        from datetime import timedelta
        cutoff_time = (datetime.now(timezone.utc) - timedelta(minutes=delay_minutes)).isoformat()
        
        # Find eligible tickets
        query = {
            "status": {"$in": [TicketStatus.AI_DRAFTED.value, TicketStatus.NEW.value]},
            "auto_response_eligible": True,
            "ai_draft_confidence": {"$gte": min_confidence},
            "category": {"$in": allowed_categories},
            "sentiment": {"$in": allowed_sentiments},
            "created_at": {"$lte": cutoff_time},
            "auto_response_sent": {"$ne": True}  # Not already auto-responded
        }
        
        eligible_tickets = await self.db.support_tickets.find(
            query, {"_id": 0}
        ).limit(10).to_list(10)  # Process max 10 at a time
        
        processed = 0
        errors = []
        
        for ticket in eligible_tickets:
            try:
                # Send the AI draft as response
                message = ticket.get("ai_draft_response")
                if not message:
                    continue
                
                # Add reply and send email
                await self.add_reply(
                    ticket_id=ticket["id"],
                    message=message,
                    sender_type="admin",  # Appears as from support team
                    sender_name="CCE Support",
                    sender_email=None,
                    is_ai_draft=True,
                    send_email=True
                )
                
                # Mark as auto-responded
                await self.db.support_tickets.update_one(
                    {"id": ticket["id"]},
                    {"$set": {
                        "status": TicketStatus.AI_RESPONDED.value,
                        "auto_response_sent": True,
                        "auto_response_at": datetime.now(timezone.utc).isoformat()
                    }}
                )
                
                processed += 1
                logger.info(f"Auto-response sent for ticket {ticket['ticket_number']}")
                
            except Exception as e:
                errors.append({"ticket": ticket.get("ticket_number"), "error": str(e)})
                logger.error(f"Failed to auto-respond to {ticket.get('ticket_number')}: {e}")
        
        return {
            "processed": processed,
            "errors": errors,
            "settings": {
                "delay_minutes": delay_minutes,
                "min_confidence": min_confidence,
                "allowed_categories": allowed_categories
            }
        }
    
    async def check_repeat_refund_request(self, email: str) -> bool:
        """
        Check if this email has made previous refund requests.
        Used to auto-escalate repeat requests.
        """
        count = await self.db.support_tickets.count_documents({
            "user_email": {"$regex": f"^{email}$", "$options": "i"},
            "category": "billing",
            "$or": [
                {"subject": {"$regex": "refund", "$options": "i"}},
                {"original_message": {"$regex": "refund", "$options": "i"}}
            ]
        })
        return count > 1  # More than 1 means repeat request
