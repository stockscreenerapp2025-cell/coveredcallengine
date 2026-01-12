"""
IMAP Email Service for Covered Call Engine
Polls Hostinger mailbox for customer replies and imports them into support tickets
"""

import os
import re
import email
import imaplib
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple
from email.header import decode_header
from email.utils import parseaddr

logger = logging.getLogger(__name__)


class IMAPService:
    """Service for polling IMAP mailbox and importing support ticket replies"""
    
    def __init__(self, db):
        self.db = db
        self.imap_server = None
        self.imap_port = 993
        self.username = None
        self.password = None
        self.connection = None
        self.last_error = None
    
    async def initialize(self) -> Tuple[bool, Optional[str]]:
        """Load IMAP settings from database and test connection
        
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        try:
            settings = await self.db.admin_settings.find_one(
                {"type": "imap_settings"}, 
                {"_id": 0}
            )
            
            if not settings:
                return False, "IMAP settings not configured"
            
            self.imap_server = settings.get("imap_server")
            self.imap_port = settings.get("imap_port", 993)
            self.username = settings.get("username")
            self.password = settings.get("password")
            
            if not all([self.imap_server, self.username, self.password]):
                return False, "IMAP settings incomplete"
            
            return True, None
            
        except Exception as e:
            error_msg = f"Failed to load IMAP settings: {str(e)}"
            logger.error(error_msg)
            return False, error_msg
    
    def _connect(self) -> Tuple[bool, Optional[str]]:
        """Establish connection to IMAP server
        
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        try:
            self.connection = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            self.connection.login(self.username, self.password)
            self.last_error = None
            return True, None
        except imaplib.IMAP4.error as e:
            error_msg = f"IMAP authentication failed: {str(e)}"
            if "AUTHENTICATIONFAILED" in str(e).upper() or "LOGIN" in str(e).upper():
                error_msg = "IMAP authentication failed. Please check your password in Admin Settings."
            self.last_error = error_msg
            logger.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"IMAP connection failed: {str(e)}"
            self.last_error = error_msg
            logger.error(error_msg)
            return False, error_msg
    
    def _disconnect(self):
        """Close IMAP connection"""
        if self.connection:
            try:
                self.connection.logout()
            except:
                pass
            self.connection = None
    
    def _decode_header_value(self, value: str) -> str:
        """Decode email header value"""
        if not value:
            return ""
        
        decoded_parts = []
        for part, encoding in decode_header(value):
            if isinstance(part, bytes):
                decoded_parts.append(part.decode(encoding or 'utf-8', errors='replace'))
            else:
                decoded_parts.append(part)
        return ''.join(decoded_parts)
    
    def _extract_text_content(self, msg) -> str:
        """Extract plain text content from email message"""
        text_content = ""
        
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))
                
                # Skip attachments
                if "attachment" in content_disposition:
                    continue
                
                if content_type == "text/plain":
                    try:
                        payload = part.get_payload(decode=True)
                        charset = part.get_content_charset() or 'utf-8'
                        text_content = payload.decode(charset, errors='replace')
                        break  # Prefer plain text
                    except:
                        continue
                elif content_type == "text/html" and not text_content:
                    try:
                        payload = part.get_payload(decode=True)
                        charset = part.get_content_charset() or 'utf-8'
                        html_content = payload.decode(charset, errors='replace')
                        # Basic HTML to text conversion
                        text_content = re.sub(r'<[^>]+>', '', html_content)
                        text_content = re.sub(r'\s+', ' ', text_content).strip()
                    except:
                        continue
        else:
            try:
                payload = msg.get_payload(decode=True)
                charset = msg.get_content_charset() or 'utf-8'
                text_content = payload.decode(charset, errors='replace')
            except:
                text_content = str(msg.get_payload())
        
        # Clean up the content - remove quoted replies (lines starting with >)
        lines = text_content.split('\n')
        cleaned_lines = []
        for line in lines:
            # Stop at common reply markers
            if line.strip().startswith('>') or line.strip().startswith('On ') and 'wrote:' in line:
                break
            if '-------- Original Message --------' in line:
                break
            if 'From:' in line and 'Sent:' in line:
                break
            cleaned_lines.append(line)
        
        return '\n'.join(cleaned_lines).strip()
    
    def _extract_ticket_number(self, subject: str) -> Optional[str]:
        """Extract ticket number from email subject"""
        # Match patterns like [CCE-0014], CCE-0014, Re: [CCE-0014]
        match = re.search(r'\[?(CCE-\d+)\]?', subject, re.IGNORECASE)
        if match:
            return match.group(1).upper()
        return None
    
    async def fetch_unread_emails(self) -> Tuple[List[Dict], Optional[str]]:
        """Fetch all unread emails from inbox
        
        Returns:
            Tuple of (emails: List[Dict], error_message: Optional[str])
        """
        emails = []
        
        # Initialize settings
        success, error = await self.initialize()
        if not success:
            return emails, error
        
        # Connect to IMAP
        success, error = self._connect()
        if not success:
            # Log the authentication error
            await self._log_sync_attempt(success=False, error=error, emails_processed=0)
            return emails, error
        
        try:
            # Select inbox
            self.connection.select('INBOX')
            
            # Search for unread emails
            status, messages = self.connection.search(None, 'UNSEEN')
            
            if status != 'OK':
                return emails, "Failed to search mailbox"
            
            email_ids = messages[0].split()
            
            for email_id in email_ids:
                try:
                    # Fetch the email
                    status, msg_data = self.connection.fetch(email_id, '(RFC822)')
                    
                    if status != 'OK':
                        continue
                    
                    # Parse email
                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)
                    
                    # Extract details
                    subject = self._decode_header_value(msg.get('Subject', ''))
                    from_header = self._decode_header_value(msg.get('From', ''))
                    date_str = msg.get('Date', '')
                    message_id = msg.get('Message-ID', '')
                    
                    # Parse sender
                    sender_name, sender_email = parseaddr(from_header)
                    if not sender_name:
                        sender_name = sender_email.split('@')[0] if sender_email else 'Unknown'
                    
                    # Extract text content
                    text_content = self._extract_text_content(msg)
                    
                    # Extract ticket number if present
                    ticket_number = self._extract_ticket_number(subject)
                    
                    emails.append({
                        'email_id': email_id.decode() if isinstance(email_id, bytes) else email_id,
                        'message_id': message_id,
                        'subject': subject,
                        'from_email': sender_email,
                        'from_name': sender_name,
                        'content': text_content,
                        'date': date_str,
                        'ticket_number': ticket_number
                    })
                    
                except Exception as e:
                    logger.warning(f"Failed to parse email {email_id}: {e}")
                    continue
            
            return emails, None
            
        except Exception as e:
            error_msg = f"Error fetching emails: {str(e)}"
            logger.error(error_msg)
            return emails, error_msg
        finally:
            self._disconnect()
    
    async def mark_as_read(self, email_ids: List[str]) -> bool:
        """Mark emails as read after processing"""
        if not email_ids:
            return True
        
        success, error = await self.initialize()
        if not success:
            return False
        
        success, error = self._connect()
        if not success:
            return False
        
        try:
            self.connection.select('INBOX')
            
            for email_id in email_ids:
                try:
                    self.connection.store(email_id.encode() if isinstance(email_id, str) else email_id, 
                                         '+FLAGS', '\\Seen')
                except Exception as e:
                    logger.warning(f"Failed to mark email {email_id} as read: {e}")
            
            return True
        except Exception as e:
            logger.error(f"Error marking emails as read: {e}")
            return False
        finally:
            self._disconnect()
    
    async def process_incoming_emails(self) -> Dict:
        """Main method: Fetch emails and import replies into tickets
        
        Returns:
            Dict with results: {success, processed, errors, details}
        """
        from services.support_service import SupportService
        support_service = SupportService(self.db)
        
        result = {
            "success": False,
            "processed": 0,
            "matched": 0,
            "new_tickets": 0,
            "errors": [],
            "details": []
        }
        
        # Fetch unread emails
        emails, error = await self.fetch_unread_emails()
        
        if error:
            result["errors"].append(error)
            await self._log_sync_attempt(success=False, error=error, emails_processed=0)
            return result
        
        if not emails:
            result["success"] = True
            result["details"].append("No new emails found")
            await self._log_sync_attempt(success=True, error=None, emails_processed=0)
            return result
        
        processed_email_ids = []
        
        for email_data in emails:
            try:
                ticket_number = email_data.get('ticket_number')
                sender_email = email_data.get('from_email', '').lower()
                sender_name = email_data.get('from_name', '')
                content = email_data.get('content', '')
                subject = email_data.get('subject', '')
                
                # Skip if no content
                if not content.strip():
                    result["details"].append(f"Skipped empty email from {sender_email}")
                    processed_email_ids.append(email_data['email_id'])
                    continue
                
                # Skip emails from our own support address
                if 'coveredcallengine.com' in sender_email:
                    result["details"].append(f"Skipped outbound email: {subject[:50]}")
                    processed_email_ids.append(email_data['email_id'])
                    continue
                
                if ticket_number:
                    # Try to find existing ticket
                    ticket = await support_service.get_ticket(ticket_number)
                    
                    if ticket and ticket.get("user_email", "").lower() == sender_email:
                        # Add reply to existing ticket
                        await support_service.add_reply(
                            ticket_id=ticket["id"],
                            message=content,
                            sender_type="user",
                            sender_name=sender_name,
                            sender_email=sender_email,
                            send_email=False
                        )
                        
                        # Trigger AI to generate a new draft response based on the customer's reply
                        try:
                            await support_service.generate_ai_draft(ticket["id"])
                            result["details"].append(f"Added reply to {ticket_number} from {sender_email} + AI draft generated")
                        except Exception as ai_err:
                            logger.warning(f"Failed to generate AI draft for {ticket_number}: {ai_err}")
                            result["details"].append(f"Added reply to {ticket_number} from {sender_email} (AI draft failed)")
                        
                        result["matched"] += 1
                    else:
                        # Ticket not found or email mismatch - create new ticket
                        clean_subject = re.sub(r'^(Re:|Fwd:|FW:)\s*', '', subject, flags=re.IGNORECASE)
                        clean_subject = re.sub(r'\[CCE-\d+\]\s*', '', clean_subject).strip()
                        
                        new_ticket = await support_service.create_ticket(
                            name=sender_name,
                            email=sender_email,
                            subject=clean_subject or "Email Inquiry",
                            message=content
                        )
                        
                        result["new_tickets"] += 1
                        result["details"].append(f"Created {new_ticket['ticket_number']} from {sender_email}")
                else:
                    # No ticket reference - create new ticket
                    clean_subject = re.sub(r'^(Re:|Fwd:|FW:)\s*', '', subject, flags=re.IGNORECASE)
                    
                    new_ticket = await support_service.create_ticket(
                        name=sender_name,
                        email=sender_email,
                        subject=clean_subject or "Email Inquiry",
                        message=content
                    )
                    
                    result["new_tickets"] += 1
                    result["details"].append(f"Created {new_ticket['ticket_number']} from {sender_email}")
                
                result["processed"] += 1
                processed_email_ids.append(email_data['email_id'])
                
            except Exception as e:
                error_msg = f"Error processing email from {email_data.get('from_email')}: {str(e)}"
                result["errors"].append(error_msg)
                logger.error(error_msg)
        
        # Mark processed emails as read
        if processed_email_ids:
            await self.mark_as_read(processed_email_ids)
        
        result["success"] = len(result["errors"]) == 0
        
        # Log the sync attempt
        await self._log_sync_attempt(
            success=result["success"],
            error="; ".join(result["errors"]) if result["errors"] else None,
            emails_processed=result["processed"],
            matched=result["matched"],
            new_tickets=result["new_tickets"]
        )
        
        return result
    
    async def _log_sync_attempt(
        self, 
        success: bool, 
        error: Optional[str], 
        emails_processed: int,
        matched: int = 0,
        new_tickets: int = 0
    ):
        """Log sync attempt for tracking and debugging"""
        await self.db.imap_sync_logs.insert_one({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": success,
            "error": error,
            "emails_processed": emails_processed,
            "matched_to_tickets": matched,
            "new_tickets_created": new_tickets
        })
        
        # Update last sync status in settings
        await self.db.admin_settings.update_one(
            {"type": "imap_settings"},
            {
                "$set": {
                    "last_sync": datetime.now(timezone.utc).isoformat(),
                    "last_sync_success": success,
                    "last_sync_error": error,
                    "last_sync_processed": emails_processed
                }
            }
        )
    
    async def test_connection(self) -> Tuple[bool, str]:
        """Test IMAP connection with current settings
        
        Returns:
            Tuple of (success: bool, message: str)
        """
        success, error = await self.initialize()
        if not success:
            return False, error or "Failed to load settings"
        
        success, error = self._connect()
        if not success:
            return False, error or "Connection failed"
        
        try:
            # Try to select inbox to verify access
            status, _ = self.connection.select('INBOX')
            if status == 'OK':
                return True, "Connection successful! Inbox accessible."
            else:
                return False, "Connected but cannot access inbox"
        except Exception as e:
            return False, f"Connection test failed: {str(e)}"
        finally:
            self._disconnect()
    
    async def get_sync_history(self, limit: int = 20) -> List[Dict]:
        """Get recent sync history"""
        logs = await self.db.imap_sync_logs.find(
            {},
            {"_id": 0}
        ).sort("timestamp", -1).limit(limit).to_list(limit)
        return logs
