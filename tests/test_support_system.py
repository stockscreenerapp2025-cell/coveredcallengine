"""
Test Support Ticket System - Backend API Tests
Tests for: ticket creation, admin dashboard, KB CRUD, stats API
"""
import pytest
import requests
import os
import uuid
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestSupportTicketSystem:
    """Support Ticket System API Tests"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.admin_token = None
        self.test_ticket_id = None
        self.test_kb_article_id = None
        
    def get_admin_token(self):
        """Get admin authentication token"""
        if self.admin_token:
            return self.admin_token
            
        response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@premiumhunter.com",
            "password": "admin123"
        })
        assert response.status_code == 200, f"Admin login failed: {response.text}"
        self.admin_token = response.json().get("access_token")
        return self.admin_token
    
    def get_admin_headers(self):
        """Get headers with admin auth"""
        token = self.get_admin_token()
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    # ==================== PUBLIC TICKET ENDPOINTS ====================
    
    def test_create_ticket_public(self):
        """Test creating a support ticket from contact form (public endpoint)"""
        unique_id = str(uuid.uuid4())[:8]
        payload = {
            "name": f"Test User {unique_id}",
            "email": f"testuser_{unique_id}@example.com",
            "subject": f"Test Support Ticket {unique_id}",
            "message": "This is a test support ticket message for testing the AI classification and draft response generation. I need help with the covered call screener feature."
        }
        
        response = self.session.post(f"{BASE_URL}/api/support/tickets", json=payload)
        print(f"Create ticket response: {response.status_code} - {response.text[:500]}")
        
        assert response.status_code == 200, f"Failed to create ticket: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "ticket_id" in data, "Response missing ticket_id"
        assert "ticket_number" in data, "Response missing ticket_number"
        assert "status" in data, "Response missing status"
        assert data["ticket_number"].startswith("CCE-"), f"Invalid ticket number format: {data['ticket_number']}"
        
        # Store for later tests
        self.__class__.test_ticket_id = data["ticket_id"]
        self.__class__.test_ticket_number = data["ticket_number"]
        print(f"Created ticket: {data['ticket_number']} with ID: {data['ticket_id']}")
        print(f"Ticket status: {data['status']}")
        
    def test_get_ticket_public(self):
        """Test getting ticket details via public endpoint (requires email verification)"""
        if not hasattr(self.__class__, 'test_ticket_id'):
            pytest.skip("No test ticket created")
            
        # Get the ticket using ticket number and email
        unique_id = self.__class__.test_ticket_number.split("-")[1] if hasattr(self.__class__, 'test_ticket_number') else None
        if not unique_id:
            pytest.skip("No ticket number available")
            
        # We need to use the email from the created ticket
        # Since we don't have it stored, let's test with admin endpoint instead
        pytest.skip("Public endpoint requires original email - testing via admin endpoint")
    
    # ==================== ADMIN TICKET ENDPOINTS ====================
    
    def test_admin_get_tickets_list(self):
        """Test admin endpoint to get paginated tickets list"""
        headers = self.get_admin_headers()
        
        response = self.session.get(f"{BASE_URL}/api/support/admin/tickets", headers=headers)
        print(f"Admin tickets list response: {response.status_code}")
        
        assert response.status_code == 200, f"Failed to get tickets: {response.text}"
        data = response.json()
        
        # Verify pagination structure
        assert "tickets" in data, "Response missing tickets array"
        assert "total" in data, "Response missing total count"
        assert "page" in data, "Response missing page number"
        assert "pages" in data, "Response missing pages count"
        
        print(f"Total tickets: {data['total']}, Page: {data['page']}/{data['pages']}")
        
        # Verify ticket structure if any exist
        if data["tickets"]:
            ticket = data["tickets"][0]
            assert "id" in ticket, "Ticket missing id"
            assert "ticket_number" in ticket, "Ticket missing ticket_number"
            assert "status" in ticket, "Ticket missing status"
            assert "category" in ticket, "Ticket missing category"
            assert "priority" in ticket, "Ticket missing priority"
            print(f"First ticket: {ticket['ticket_number']} - {ticket['status']} - {ticket['category']}")
    
    def test_admin_get_tickets_with_filters(self):
        """Test admin tickets list with filters"""
        headers = self.get_admin_headers()
        
        # Test status filter
        response = self.session.get(f"{BASE_URL}/api/support/admin/tickets?status=ai_drafted", headers=headers)
        assert response.status_code == 200, f"Status filter failed: {response.text}"
        
        # Test priority filter
        response = self.session.get(f"{BASE_URL}/api/support/admin/tickets?priority=normal", headers=headers)
        assert response.status_code == 200, f"Priority filter failed: {response.text}"
        
        # Test search filter
        response = self.session.get(f"{BASE_URL}/api/support/admin/tickets?search=test", headers=headers)
        assert response.status_code == 200, f"Search filter failed: {response.text}"
        
        print("All filter tests passed")
    
    def test_admin_get_ticket_detail(self):
        """Test getting full ticket details including AI draft"""
        if not hasattr(self.__class__, 'test_ticket_id'):
            pytest.skip("No test ticket created")
            
        headers = self.get_admin_headers()
        ticket_id = self.__class__.test_ticket_id
        
        response = self.session.get(f"{BASE_URL}/api/support/admin/tickets/{ticket_id}", headers=headers)
        print(f"Ticket detail response: {response.status_code}")
        
        assert response.status_code == 200, f"Failed to get ticket detail: {response.text}"
        data = response.json()
        
        # Verify full ticket structure
        assert "id" in data, "Missing id"
        assert "ticket_number" in data, "Missing ticket_number"
        assert "user_name" in data, "Missing user_name"
        assert "user_email" in data, "Missing user_email"
        assert "subject" in data, "Missing subject"
        assert "original_message" in data, "Missing original_message"
        assert "status" in data, "Missing status"
        assert "category" in data, "Missing category"
        assert "sentiment" in data, "Missing sentiment"
        assert "priority" in data, "Missing priority"
        assert "messages" in data, "Missing messages array"
        
        # Verify AI classification was done
        assert "ai_classification" in data, "Missing AI classification"
        assert "ai_draft_response" in data, "Missing AI draft response"
        
        print(f"Ticket: {data['ticket_number']}")
        print(f"Category: {data['category']}, Sentiment: {data['sentiment']}, Priority: {data['priority']}")
        print(f"AI Draft Confidence: {data.get('ai_draft_confidence', 'N/A')}")
        print(f"AI Draft Response (first 200 chars): {data.get('ai_draft_response', 'N/A')[:200]}...")
    
    def test_admin_update_ticket_status(self):
        """Test updating ticket status"""
        if not hasattr(self.__class__, 'test_ticket_id'):
            pytest.skip("No test ticket created")
            
        headers = self.get_admin_headers()
        ticket_id = self.__class__.test_ticket_id
        
        response = self.session.put(
            f"{BASE_URL}/api/support/admin/tickets/{ticket_id}?status=awaiting_user",
            headers=headers
        )
        print(f"Update status response: {response.status_code}")
        
        assert response.status_code == 200, f"Failed to update status: {response.text}"
        data = response.json()
        assert data.get("success") == True, "Update not successful"
        print("Status updated successfully")
    
    # ==================== SUPPORT STATS ENDPOINT ====================
    
    def test_admin_get_support_stats(self):
        """Test support dashboard statistics endpoint"""
        headers = self.get_admin_headers()
        
        response = self.session.get(f"{BASE_URL}/api/support/admin/stats", headers=headers)
        print(f"Support stats response: {response.status_code}")
        
        assert response.status_code == 200, f"Failed to get stats: {response.text}"
        data = response.json()
        
        # Verify stats structure
        assert "total_tickets" in data, "Missing total_tickets"
        assert "open_tickets" in data, "Missing open_tickets"
        assert "awaiting_review" in data, "Missing awaiting_review"
        assert "resolved_today" in data, "Missing resolved_today"
        assert "tickets_by_status" in data, "Missing tickets_by_status"
        assert "tickets_by_category" in data, "Missing tickets_by_category"
        assert "tickets_by_sentiment" in data, "Missing tickets_by_sentiment"
        
        print(f"Total tickets: {data['total_tickets']}")
        print(f"Open tickets: {data['open_tickets']}")
        print(f"Awaiting review: {data['awaiting_review']}")
        print(f"Resolved today: {data['resolved_today']}")
        print(f"By status: {data['tickets_by_status']}")
        print(f"By category: {data['tickets_by_category']}")
    
    # ==================== KNOWLEDGE BASE ENDPOINTS ====================
    
    def test_kb_create_article(self):
        """Test creating a knowledge base article"""
        headers = self.get_admin_headers()
        unique_id = str(uuid.uuid4())[:8]
        
        payload = {
            "question": f"How do I use the covered call screener? (Test {unique_id})",
            "answer": "The covered call screener helps you find optimal covered call opportunities. Navigate to the Screener tab, set your filters for premium yield, delta, and days to expiration, then click Search to find matching options.",
            "category": "screener",
            "active": True
        }
        
        response = self.session.post(f"{BASE_URL}/api/support/admin/kb", json=payload, headers=headers)
        print(f"Create KB article response: {response.status_code}")
        
        assert response.status_code == 200, f"Failed to create KB article: {response.text}"
        data = response.json()
        
        assert data.get("success") == True, "Create not successful"
        assert "article" in data, "Missing article in response"
        assert "id" in data["article"], "Article missing id"
        
        self.__class__.test_kb_article_id = data["article"]["id"]
        print(f"Created KB article: {data['article']['id']}")
    
    def test_kb_get_articles(self):
        """Test getting knowledge base articles list"""
        headers = self.get_admin_headers()
        
        response = self.session.get(f"{BASE_URL}/api/support/admin/kb", headers=headers)
        print(f"Get KB articles response: {response.status_code}")
        
        assert response.status_code == 200, f"Failed to get KB articles: {response.text}"
        data = response.json()
        
        assert "articles" in data, "Missing articles array"
        assert "total" in data, "Missing total count"
        assert "page" in data, "Missing page"
        assert "pages" in data, "Missing pages"
        
        print(f"Total KB articles: {data['total']}")
        
        if data["articles"]:
            article = data["articles"][0]
            assert "id" in article, "Article missing id"
            assert "question" in article, "Article missing question"
            assert "answer" in article, "Article missing answer"
            assert "category" in article, "Article missing category"
            print(f"First article: {article['question'][:50]}...")
    
    def test_kb_update_article(self):
        """Test updating a knowledge base article"""
        if not hasattr(self.__class__, 'test_kb_article_id'):
            pytest.skip("No test KB article created")
            
        headers = self.get_admin_headers()
        article_id = self.__class__.test_kb_article_id
        
        response = self.session.put(
            f"{BASE_URL}/api/support/admin/kb/{article_id}?active=false",
            headers=headers
        )
        print(f"Update KB article response: {response.status_code}")
        
        assert response.status_code == 200, f"Failed to update KB article: {response.text}"
        data = response.json()
        assert data.get("success") == True, "Update not successful"
        print("KB article updated successfully")
    
    def test_kb_delete_article(self):
        """Test deleting a knowledge base article"""
        if not hasattr(self.__class__, 'test_kb_article_id'):
            pytest.skip("No test KB article created")
            
        headers = self.get_admin_headers()
        article_id = self.__class__.test_kb_article_id
        
        response = self.session.delete(f"{BASE_URL}/api/support/admin/kb/{article_id}", headers=headers)
        print(f"Delete KB article response: {response.status_code}")
        
        assert response.status_code == 200, f"Failed to delete KB article: {response.text}"
        data = response.json()
        assert data.get("success") == True, "Delete not successful"
        print("KB article deleted successfully")
    
    # ==================== META ENDPOINTS ====================
    
    def test_get_categories(self):
        """Test getting ticket categories list"""
        response = self.session.get(f"{BASE_URL}/api/support/meta/categories")
        print(f"Categories response: {response.status_code}")
        
        assert response.status_code == 200, f"Failed to get categories: {response.text}"
        data = response.json()
        
        assert "categories" in data, "Missing categories"
        assert len(data["categories"]) > 0, "No categories returned"
        print(f"Categories: {[c['value'] for c in data['categories']]}")
    
    def test_get_statuses(self):
        """Test getting ticket statuses list"""
        response = self.session.get(f"{BASE_URL}/api/support/meta/statuses")
        print(f"Statuses response: {response.status_code}")
        
        assert response.status_code == 200, f"Failed to get statuses: {response.text}"
        data = response.json()
        
        assert "statuses" in data, "Missing statuses"
        assert len(data["statuses"]) > 0, "No statuses returned"
        print(f"Statuses: {[s['value'] for s in data['statuses']]}")
    
    def test_get_priorities(self):
        """Test getting ticket priorities list"""
        response = self.session.get(f"{BASE_URL}/api/support/meta/priorities")
        print(f"Priorities response: {response.status_code}")
        
        assert response.status_code == 200, f"Failed to get priorities: {response.text}"
        data = response.json()
        
        assert "priorities" in data, "Missing priorities"
        assert len(data["priorities"]) > 0, "No priorities returned"
        print(f"Priorities: {[p['value'] for p in data['priorities']]}")
    
    # ==================== CLEANUP ====================
    
    def test_zz_cleanup_test_ticket(self):
        """Cleanup: Close the test ticket"""
        if not hasattr(self.__class__, 'test_ticket_id'):
            pytest.skip("No test ticket to cleanup")
            
        headers = self.get_admin_headers()
        ticket_id = self.__class__.test_ticket_id
        
        # Close the ticket
        response = self.session.post(f"{BASE_URL}/api/support/admin/tickets/{ticket_id}/close", headers=headers)
        print(f"Close ticket response: {response.status_code}")
        
        if response.status_code == 200:
            print(f"Test ticket {ticket_id} closed successfully")
        else:
            print(f"Warning: Could not close test ticket: {response.text}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
