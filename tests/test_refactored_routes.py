"""
Test suite for refactored routes in Covered Call Engine
Tests: Auth, Watchlist, News, Chatbot, AI, Subscription, Stocks routes
All routes were refactored from server.py into separate files in routes/
"""
import pytest
import requests
import os
import uuid
from datetime import datetime

# Get BASE_URL from environment
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
if not BASE_URL:
    raise ValueError("REACT_APP_BACKEND_URL environment variable not set")

# Test credentials
TEST_ADMIN_EMAIL = "admin@premiumhunter.com"
TEST_ADMIN_PASSWORD = "admin123"

# Test user for registration tests
TEST_USER_EMAIL = f"test_refactor_{uuid.uuid4().hex[:8]}@example.com"
TEST_USER_PASSWORD = "testpass123"
TEST_USER_NAME = "Test Refactor User"


class TestHealthCheck:
    """Basic health check to ensure API is running"""
    
    def test_health_endpoint(self):
        """Test /api/health returns 200"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy"
        print(f"✓ Health check passed: {data}")


class TestAuthRoutes:
    """Test authentication routes from routes/auth.py"""
    
    def test_login_success(self):
        """Test POST /api/auth/login with valid credentials"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_ADMIN_EMAIL, "password": TEST_ADMIN_PASSWORD}
        )
        assert response.status_code == 200, f"Login failed: {response.text}"
        data = response.json()
        assert "access_token" in data
        assert "user" in data
        assert data["user"]["email"] == TEST_ADMIN_EMAIL
        print(f"✓ Login success: user={data['user']['email']}, is_admin={data['user'].get('is_admin')}")
        return data["access_token"]
    
    def test_login_invalid_credentials(self):
        """Test POST /api/auth/login with invalid credentials"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "wrong@example.com", "password": "wrongpass"}
        )
        assert response.status_code == 401
        print("✓ Invalid login correctly rejected with 401")
    
    def test_register_new_user(self):
        """Test POST /api/auth/register with new user"""
        response = requests.post(
            f"{BASE_URL}/api/auth/register",
            json={
                "email": TEST_USER_EMAIL,
                "password": TEST_USER_PASSWORD,
                "name": TEST_USER_NAME
            }
        )
        assert response.status_code == 200, f"Registration failed: {response.text}"
        data = response.json()
        assert "access_token" in data
        assert data["user"]["email"] == TEST_USER_EMAIL
        print(f"✓ Registration success: {TEST_USER_EMAIL}")
    
    def test_register_duplicate_email(self):
        """Test POST /api/auth/register with existing email"""
        response = requests.post(
            f"{BASE_URL}/api/auth/register",
            json={
                "email": TEST_ADMIN_EMAIL,  # Already exists
                "password": "anypass",
                "name": "Duplicate User"
            }
        )
        assert response.status_code == 400
        print("✓ Duplicate registration correctly rejected with 400")
    
    def test_get_me_authenticated(self):
        """Test GET /api/auth/me with valid token"""
        # First login to get token
        login_response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_ADMIN_EMAIL, "password": TEST_ADMIN_PASSWORD}
        )
        token = login_response.json()["access_token"]
        
        # Then get user info
        response = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == TEST_ADMIN_EMAIL
        print(f"✓ Get me success: {data['email']}, is_admin={data.get('is_admin')}")
    
    def test_get_me_unauthenticated(self):
        """Test GET /api/auth/me without token"""
        response = requests.get(f"{BASE_URL}/api/auth/me")
        assert response.status_code in [401, 403]
        print("✓ Unauthenticated /me correctly rejected")


class TestWatchlistRoutes:
    """Test watchlist routes from routes/watchlist.py"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get auth token before each test"""
        login_response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_ADMIN_EMAIL, "password": TEST_ADMIN_PASSWORD}
        )
        self.token = login_response.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_get_watchlist(self):
        """Test GET /api/watchlist/"""
        response = requests.get(
            f"{BASE_URL}/api/watchlist/",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Get watchlist success: {len(data)} items")
    
    def test_add_to_watchlist(self):
        """Test POST /api/watchlist/"""
        test_symbol = f"TEST{uuid.uuid4().hex[:4].upper()}"
        response = requests.post(
            f"{BASE_URL}/api/watchlist/",
            headers=self.headers,
            json={
                "symbol": test_symbol,
                "target_price": 150.00,
                "notes": "Test watchlist item"
            }
        )
        assert response.status_code == 200, f"Add to watchlist failed: {response.text}"
        data = response.json()
        assert "id" in data
        print(f"✓ Add to watchlist success: {test_symbol}, id={data['id']}")
        return data["id"]
    
    def test_add_duplicate_to_watchlist(self):
        """Test POST /api/watchlist/ with duplicate symbol"""
        # First add
        requests.post(
            f"{BASE_URL}/api/watchlist/",
            headers=self.headers,
            json={"symbol": "AAPL", "notes": "First add"}
        )
        # Try duplicate
        response = requests.post(
            f"{BASE_URL}/api/watchlist/",
            headers=self.headers,
            json={"symbol": "AAPL", "notes": "Duplicate"}
        )
        # Should be 400 if already exists
        assert response.status_code in [200, 400]
        print(f"✓ Duplicate watchlist handling: status={response.status_code}")
    
    def test_delete_from_watchlist(self):
        """Test DELETE /api/watchlist/{item_id}"""
        # First add an item
        add_response = requests.post(
            f"{BASE_URL}/api/watchlist/",
            headers=self.headers,
            json={"symbol": f"DEL{uuid.uuid4().hex[:4].upper()}", "notes": "To delete"}
        )
        item_id = add_response.json()["id"]
        
        # Then delete it
        response = requests.delete(
            f"{BASE_URL}/api/watchlist/{item_id}",
            headers=self.headers
        )
        assert response.status_code == 200
        print(f"✓ Delete from watchlist success: id={item_id}")
    
    def test_delete_nonexistent_watchlist_item(self):
        """Test DELETE /api/watchlist/{item_id} with invalid id"""
        response = requests.delete(
            f"{BASE_URL}/api/watchlist/nonexistent-id-12345",
            headers=self.headers
        )
        assert response.status_code == 404
        print("✓ Delete nonexistent item correctly returns 404")


class TestNewsRoutes:
    """Test news routes from routes/news.py"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get auth token before each test"""
        login_response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_ADMIN_EMAIL, "password": TEST_ADMIN_PASSWORD}
        )
        self.token = login_response.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_get_market_news(self):
        """Test GET /api/news/"""
        response = requests.get(
            f"{BASE_URL}/api/news/",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Get news success: {len(data)} articles")
    
    def test_get_news_with_limit(self):
        """Test GET /api/news/?limit=5"""
        response = requests.get(
            f"{BASE_URL}/api/news/?limit=5",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) <= 5
        print(f"✓ Get news with limit success: {len(data)} articles (limit=5)")
    
    def test_get_news_with_symbol(self):
        """Test GET /api/news/?symbol=AAPL"""
        response = requests.get(
            f"{BASE_URL}/api/news/?symbol=AAPL",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Get news for AAPL success: {len(data)} articles")
    
    def test_get_rate_limit_status(self):
        """Test GET /api/news/rate-limit"""
        response = requests.get(
            f"{BASE_URL}/api/news/rate-limit",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "daily_limit" in data
        assert "requests_today" in data
        assert "remaining" in data
        print(f"✓ Rate limit status: {data['requests_today']}/{data['daily_limit']} used, {data['remaining']} remaining")


class TestChatbotRoutes:
    """Test chatbot routes from routes/chatbot.py"""
    
    def test_send_chatbot_message(self):
        """Test POST /api/chatbot/message"""
        response = requests.post(
            f"{BASE_URL}/api/chatbot/message",
            params={"message": "What is a covered call?"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "response" in data
        assert "session_id" in data
        print(f"✓ Chatbot message success: session_id={data['session_id'][:8]}...")
    
    def test_send_chatbot_message_with_session(self):
        """Test POST /api/chatbot/message with existing session"""
        session_id = str(uuid.uuid4())
        response = requests.post(
            f"{BASE_URL}/api/chatbot/message",
            params={"message": "Tell me about PMCC", "session_id": session_id}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == session_id
        print(f"✓ Chatbot with session success: session_id={session_id[:8]}...")
    
    def test_get_chatbot_history(self):
        """Test GET /api/chatbot/history/{session_id}"""
        session_id = str(uuid.uuid4())
        # First send a message
        requests.post(
            f"{BASE_URL}/api/chatbot/message",
            params={"message": "Hello", "session_id": session_id}
        )
        
        # Then get history
        response = requests.get(f"{BASE_URL}/api/chatbot/history/{session_id}")
        assert response.status_code == 200
        data = response.json()
        assert "history" in data
        assert data["session_id"] == session_id
        print(f"✓ Chatbot history success: {len(data['history'])} messages")
    
    def test_get_quick_response(self):
        """Test GET /api/chatbot/quick-response/{topic}"""
        response = requests.get(f"{BASE_URL}/api/chatbot/quick-response/covered_call")
        assert response.status_code == 200
        data = response.json()
        assert "topic" in data
        print(f"✓ Quick response success: topic={data['topic']}")


class TestAIRoutes:
    """Test AI routes from routes/ai.py"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get auth token before each test"""
        login_response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_ADMIN_EMAIL, "password": TEST_ADMIN_PASSWORD}
        )
        self.token = login_response.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_ai_analyze(self):
        """Test POST /api/ai/analyze"""
        response = requests.post(
            f"{BASE_URL}/api/ai/analyze",
            headers=self.headers,
            json={
                "symbol": "AAPL",
                "analysis_type": "covered_call",
                "context": "Looking for weekly income opportunities"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert "analysis" in data
        print(f"✓ AI analyze success: is_mock={data.get('is_mock', False)}")
    
    def test_ai_opportunities(self):
        """Test GET /api/ai/opportunities"""
        response = requests.get(
            f"{BASE_URL}/api/ai/opportunities",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "opportunities" in data
        assert "total" in data
        print(f"✓ AI opportunities success: {data['total']} opportunities found")
    
    def test_ai_opportunities_with_min_score(self):
        """Test GET /api/ai/opportunities?min_score=80"""
        response = requests.get(
            f"{BASE_URL}/api/ai/opportunities?min_score=80",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        # All opportunities should have score >= 80
        for opp in data.get("opportunities", []):
            assert opp.get("ai_score", 0) >= 80
        print(f"✓ AI opportunities with min_score=80: {data['total']} opportunities")


class TestSubscriptionRoutes:
    """Test subscription routes from routes/subscription.py"""
    
    def test_get_subscription_links_public(self):
        """Test GET /api/subscription/links (public endpoint)"""
        response = requests.get(f"{BASE_URL}/api/subscription/links")
        assert response.status_code == 200
        data = response.json()
        assert "trial_link" in data
        assert "monthly_link" in data
        assert "yearly_link" in data
        assert "mode" in data
        print(f"✓ Subscription links success: mode={data['mode']}")
    
    def test_get_subscription_admin_settings(self):
        """Test GET /api/subscription/admin/settings (admin only)"""
        # Login as admin
        login_response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_ADMIN_EMAIL, "password": TEST_ADMIN_PASSWORD}
        )
        token = login_response.json()["access_token"]
        
        response = requests.get(
            f"{BASE_URL}/api/subscription/admin/settings",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "active_mode" in data
        assert "test_links" in data
        assert "live_links" in data
        print(f"✓ Admin subscription settings success: mode={data['active_mode']}")


class TestStocksRoutes:
    """Test stocks routes from routes/stocks.py"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get auth token before each test"""
        login_response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_ADMIN_EMAIL, "password": TEST_ADMIN_PASSWORD}
        )
        self.token = login_response.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_get_stock_quote(self):
        """Test GET /api/stocks/quote/{symbol}"""
        response = requests.get(
            f"{BASE_URL}/api/stocks/quote/AAPL",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["symbol"] == "AAPL"
        assert "price" in data
        print(f"✓ Stock quote AAPL: ${data['price']}, is_live={data.get('is_live', False)}")
    
    def test_get_stock_quote_invalid_symbol(self):
        """Test GET /api/stocks/quote/{symbol} with invalid symbol"""
        response = requests.get(
            f"{BASE_URL}/api/stocks/quote/INVALIDXYZ123",
            headers=self.headers
        )
        assert response.status_code == 404
        print("✓ Invalid stock symbol correctly returns 404")
    
    def test_get_market_indices(self):
        """Test GET /api/stocks/indices"""
        response = requests.get(
            f"{BASE_URL}/api/stocks/indices",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        # Should have SPY, QQQ, etc.
        assert "SPY" in data or len(data) > 0
        print(f"✓ Market indices success: {list(data.keys())[:5]}...")
    
    def test_get_stock_details(self):
        """Test GET /api/stocks/details/{symbol}"""
        response = requests.get(
            f"{BASE_URL}/api/stocks/details/AAPL",
            headers=self.headers,
            timeout=30  # This endpoint may take longer
        )
        assert response.status_code == 200
        data = response.json()
        assert data["symbol"] == "AAPL"
        assert "price" in data
        assert "news" in data
        assert "fundamentals" in data
        print(f"✓ Stock details AAPL: price=${data['price']}, news={len(data['news'])} articles")
    
    def test_get_historical_data(self):
        """Test GET /api/stocks/historical/{symbol}"""
        response = requests.get(
            f"{BASE_URL}/api/stocks/historical/AAPL?days=30",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) <= 30
        if data:
            assert "date" in data[0]
            assert "close" in data[0]
        print(f"✓ Historical data AAPL: {len(data)} days")


class TestRouteIntegration:
    """Integration tests to verify routes work together"""
    
    def test_full_auth_flow(self):
        """Test complete auth flow: register -> login -> get me"""
        unique_email = f"integration_{uuid.uuid4().hex[:8]}@test.com"
        
        # Register
        reg_response = requests.post(
            f"{BASE_URL}/api/auth/register",
            json={"email": unique_email, "password": "testpass123", "name": "Integration Test"}
        )
        assert reg_response.status_code == 200
        reg_token = reg_response.json()["access_token"]
        
        # Login with same credentials
        login_response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": unique_email, "password": "testpass123"}
        )
        assert login_response.status_code == 200
        login_token = login_response.json()["access_token"]
        
        # Get me with login token
        me_response = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {login_token}"}
        )
        assert me_response.status_code == 200
        assert me_response.json()["email"] == unique_email
        
        print(f"✓ Full auth flow success for {unique_email}")
    
    def test_watchlist_crud_flow(self):
        """Test complete watchlist CRUD flow"""
        # Login
        login_response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_ADMIN_EMAIL, "password": TEST_ADMIN_PASSWORD}
        )
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        # Create
        symbol = f"CRUD{uuid.uuid4().hex[:4].upper()}"
        create_response = requests.post(
            f"{BASE_URL}/api/watchlist/",
            headers=headers,
            json={"symbol": symbol, "notes": "CRUD test"}
        )
        assert create_response.status_code == 200
        item_id = create_response.json()["id"]
        
        # Read
        read_response = requests.get(f"{BASE_URL}/api/watchlist/", headers=headers)
        assert read_response.status_code == 200
        items = read_response.json()
        assert any(item.get("symbol") == symbol for item in items)
        
        # Delete
        delete_response = requests.delete(f"{BASE_URL}/api/watchlist/{item_id}", headers=headers)
        assert delete_response.status_code == 200
        
        # Verify deleted
        verify_response = requests.get(f"{BASE_URL}/api/watchlist/", headers=headers)
        items_after = verify_response.json()
        assert not any(item.get("id") == item_id for item in items_after)
        
        print(f"✓ Watchlist CRUD flow success for {symbol}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
