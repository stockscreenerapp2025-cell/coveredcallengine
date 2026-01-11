"""
Phase 4 Refactoring Tests - Screener and Simulator Routes
Tests all endpoints from the newly refactored screener.py and simulator.py modules
Also verifies existing routes continue to work after refactoring
"""
import pytest
import requests
import os
import uuid
from datetime import datetime, timedelta

# Get BASE_URL from environment
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
if not BASE_URL:
    raise ValueError("REACT_APP_BACKEND_URL environment variable not set")

# Test credentials
TEST_EMAIL = "admin@premiumhunter.com"
TEST_PASSWORD = "admin123"


class TestHealthAndBasics:
    """Basic health check and API availability tests"""
    
    def test_health_endpoint(self):
        """Test /api/health returns healthy status"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy"
        print("✓ Health endpoint working")
    
    def test_root_endpoint(self):
        """Test /api/ returns API info"""
        response = requests.get(f"{BASE_URL}/api/")
        assert response.status_code == 200
        data = response.json()
        assert "Covered Call Engine" in data.get("message", "")
        print("✓ Root endpoint working")
    
    def test_market_status(self):
        """Test /api/market-status returns market info"""
        response = requests.get(f"{BASE_URL}/api/market-status")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "is_open" in data
        print(f"✓ Market status: {data.get('status')}")


class TestAuthRoutes:
    """Authentication endpoint tests"""
    
    def test_login_success(self):
        """Test /api/auth/login with valid credentials"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "user" in data
        assert data["user"]["email"] == TEST_EMAIL
        assert data["user"]["is_admin"] == True
        print("✓ Login successful - admin user verified")
        return data["access_token"]
    
    def test_login_invalid_credentials(self):
        """Test /api/auth/login with invalid credentials"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "wrong@example.com",
            "password": "wrongpassword"
        })
        assert response.status_code == 401
        print("✓ Invalid login correctly rejected")
    
    def test_auth_me_authenticated(self):
        """Test /api/auth/me with valid token"""
        token = self.test_login_success()
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(f"{BASE_URL}/api/auth/me", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == TEST_EMAIL
        print("✓ Auth me endpoint working")
    
    def test_auth_me_unauthenticated(self):
        """Test /api/auth/me without token"""
        response = requests.get(f"{BASE_URL}/api/auth/me")
        assert response.status_code in [401, 403]
        print("✓ Unauthenticated request correctly rejected")


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token for tests"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD
    })
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.skip("Authentication failed - skipping authenticated tests")


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Get headers with auth token"""
    return {"Authorization": f"Bearer {auth_token}"}


class TestWatchlistRoutes:
    """Watchlist endpoint tests"""
    
    def test_get_watchlist(self, auth_headers):
        """Test GET /api/watchlist/"""
        response = requests.get(f"{BASE_URL}/api/watchlist/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Watchlist returned {len(data)} items")
    
    def test_add_to_watchlist(self, auth_headers):
        """Test POST /api/watchlist/"""
        test_symbol = f"TEST{uuid.uuid4().hex[:4].upper()}"
        response = requests.post(f"{BASE_URL}/api/watchlist/", 
            headers=auth_headers,
            json={"symbol": test_symbol, "notes": "Test item"}
        )
        # May return 400 if already exists, 200 if added
        assert response.status_code in [200, 400]
        print(f"✓ Add to watchlist endpoint working")


class TestStocksRoutes:
    """Stock data endpoint tests"""
    
    def test_get_stock_quote(self, auth_headers):
        """Test GET /api/stocks/quote/AAPL"""
        response = requests.get(f"{BASE_URL}/api/stocks/quote/AAPL", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data.get("symbol") == "AAPL"
        assert "price" in data
        print(f"✓ Stock quote: AAPL @ ${data.get('price')}")
    
    def test_get_market_indices(self, auth_headers):
        """Test GET /api/stocks/indices"""
        response = requests.get(f"{BASE_URL}/api/stocks/indices", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "SPY" in data or len(data) > 0
        print(f"✓ Market indices returned")


class TestOptionsRoutes:
    """Options chain endpoint tests"""
    
    def test_get_options_chain(self, auth_headers):
        """Test GET /api/options/chain/AAPL"""
        response = requests.get(f"{BASE_URL}/api/options/chain/AAPL", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data.get("symbol") == "AAPL"
        assert "options" in data
        print(f"✓ Options chain: {len(data.get('options', []))} options for AAPL")
    
    def test_get_option_expirations(self, auth_headers):
        """Test GET /api/options/expirations/AAPL"""
        response = requests.get(f"{BASE_URL}/api/options/expirations/AAPL", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        print(f"✓ Option expirations: {len(data)} dates available")


class TestPortfolioRoutes:
    """Portfolio management endpoint tests"""
    
    def test_get_portfolio_positions(self, auth_headers):
        """Test GET /api/portfolio/positions"""
        response = requests.get(f"{BASE_URL}/api/portfolio/positions", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Portfolio positions: {len(data)} positions")
    
    def test_get_portfolio_summary(self, auth_headers):
        """Test GET /api/portfolio/summary"""
        response = requests.get(f"{BASE_URL}/api/portfolio/summary", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "total_value" in data or "positions_count" in data
        print(f"✓ Portfolio summary returned")


class TestScreenerRoutes:
    """Screener endpoint tests - NEWLY REFACTORED in Phase 4"""
    
    def test_dashboard_opportunities(self, auth_headers):
        """Test GET /api/screener/dashboard-opportunities"""
        response = requests.get(f"{BASE_URL}/api/screener/dashboard-opportunities", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "opportunities" in data
        assert "total" in data
        print(f"✓ Dashboard opportunities: {data.get('total', 0)} found")
    
    def test_dashboard_pmcc(self, auth_headers):
        """Test GET /api/screener/dashboard-pmcc"""
        response = requests.get(f"{BASE_URL}/api/screener/dashboard-pmcc", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "opportunities" in data
        print(f"✓ Dashboard PMCC: {len(data.get('opportunities', []))} opportunities")
    
    def test_get_saved_filters(self, auth_headers):
        """Test GET /api/screener/filters"""
        response = requests.get(f"{BASE_URL}/api/screener/filters", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Saved filters: {len(data)} filters")
    
    def test_covered_calls_screener(self, auth_headers):
        """Test GET /api/screener/covered-calls with default params"""
        response = requests.get(f"{BASE_URL}/api/screener/covered-calls", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "opportunities" in data
        print(f"✓ Covered calls screener: {len(data.get('opportunities', []))} results")
    
    def test_pmcc_screener(self, auth_headers):
        """Test GET /api/screener/pmcc with default params"""
        response = requests.get(f"{BASE_URL}/api/screener/pmcc", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "opportunities" in data
        print(f"✓ PMCC screener: {len(data.get('opportunities', []))} results")


class TestSimulatorRoutes:
    """Simulator endpoint tests - NEWLY REFACTORED in Phase 4"""
    
    def test_get_simulator_summary(self, auth_headers):
        """Test GET /api/simulator/summary"""
        response = requests.get(f"{BASE_URL}/api/simulator/summary", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "total_trades" in data
        assert "active_trades" in data
        assert "by_strategy" in data
        print(f"✓ Simulator summary: {data.get('total_trades', 0)} total trades")
    
    def test_get_simulator_trades(self, auth_headers):
        """Test GET /api/simulator/trades"""
        response = requests.get(f"{BASE_URL}/api/simulator/trades", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "trades" in data
        assert "total" in data
        print(f"✓ Simulator trades: {data.get('total', 0)} trades")
    
    def test_get_simulator_rules(self, auth_headers):
        """Test GET /api/simulator/rules"""
        response = requests.get(f"{BASE_URL}/api/simulator/rules", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "rules" in data
        print(f"✓ Simulator rules: {len(data.get('rules', []))} rules")
    
    def test_get_rule_templates(self, auth_headers):
        """Test GET /api/simulator/rules/templates"""
        response = requests.get(f"{BASE_URL}/api/simulator/rules/templates", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "templates" in data
        assert len(data.get("templates", [])) > 0
        print(f"✓ Rule templates: {len(data.get('templates', []))} templates available")
    
    def test_get_scheduler_status(self, auth_headers):
        """Test GET /api/simulator/scheduler-status"""
        response = requests.get(f"{BASE_URL}/api/simulator/scheduler-status", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "scheduler_running" in data
        assert "jobs" in data
        print(f"✓ Scheduler status: running={data.get('scheduler_running')}, jobs={len(data.get('jobs', []))}")
    
    def test_get_pmcc_summary(self, auth_headers):
        """Test GET /api/simulator/pmcc-summary"""
        response = requests.get(f"{BASE_URL}/api/simulator/pmcc-summary", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "total_pmcc_trades" in data
        print(f"✓ PMCC summary: {data.get('total_pmcc_trades', 0)} PMCC trades")
    
    def test_get_action_logs(self, auth_headers):
        """Test GET /api/simulator/action-logs"""
        response = requests.get(f"{BASE_URL}/api/simulator/action-logs", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "logs" in data
        print(f"✓ Action logs: {len(data.get('logs', []))} logs")
    
    def test_analytics_performance(self, auth_headers):
        """Test GET /api/simulator/analytics/performance"""
        response = requests.get(f"{BASE_URL}/api/simulator/analytics/performance", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "total_trades" in data
        assert "win_rate" in data
        print(f"✓ Analytics performance: win_rate={data.get('win_rate', 0)}%")


class TestAdminRoutes:
    """Admin endpoint tests (admin user only)"""
    
    def test_get_admin_settings(self, auth_headers):
        """Test GET /api/admin/settings"""
        response = requests.get(f"{BASE_URL}/api/admin/settings", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        # Settings may be empty or have masked keys
        assert isinstance(data, dict)
        print(f"✓ Admin settings retrieved")
    
    def test_get_dashboard_stats(self, auth_headers):
        """Test GET /api/admin/dashboard-stats"""
        response = requests.get(f"{BASE_URL}/api/admin/dashboard-stats", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "users" in data
        assert "subscriptions" in data
        print(f"✓ Admin dashboard stats: {data.get('users', {}).get('total', 0)} total users")


class TestSubscriptionRoutes:
    """Subscription endpoint tests"""
    
    def test_get_subscription_links(self):
        """Test GET /api/subscription/links (public endpoint)"""
        response = requests.get(f"{BASE_URL}/api/subscription/links")
        assert response.status_code == 200
        data = response.json()
        assert "mode" in data
        print(f"✓ Subscription links: mode={data.get('mode')}")
    
    def test_get_admin_subscription_settings(self, auth_headers):
        """Test GET /api/subscription/admin/settings"""
        response = requests.get(f"{BASE_URL}/api/subscription/admin/settings", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "active_mode" in data
        print(f"✓ Admin subscription settings: mode={data.get('active_mode')}")


class TestSimulatorTradeOperations:
    """Test simulator trade CRUD operations"""
    
    def test_create_and_get_trade(self, auth_headers):
        """Test POST /api/simulator/trade and GET /api/simulator/trades/{id}"""
        # Create a test trade
        trade_data = {
            "symbol": "AAPL",
            "strategy_type": "covered_call",
            "underlying_price": 175.50,
            "short_call_strike": 180.0,
            "short_call_expiry": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
            "short_call_premium": 3.50,
            "short_call_delta": 0.30,
            "contracts": 1,
            "notes": "TEST_trade_for_testing"
        }
        
        response = requests.post(f"{BASE_URL}/api/simulator/trade", 
            headers=auth_headers, json=trade_data)
        assert response.status_code == 200
        data = response.json()
        assert "trade" in data
        trade_id = data["trade"]["id"]
        print(f"✓ Created simulator trade: {trade_id}")
        
        # Get the trade
        response = requests.get(f"{BASE_URL}/api/simulator/trades/{trade_id}", headers=auth_headers)
        assert response.status_code == 200
        trade = response.json()
        assert trade["symbol"] == "AAPL"
        assert trade["strategy_type"] == "covered_call"
        print(f"✓ Retrieved trade details")
        
        # Delete the trade (cleanup)
        response = requests.delete(f"{BASE_URL}/api/simulator/trades/{trade_id}", headers=auth_headers)
        assert response.status_code == 200
        print(f"✓ Deleted test trade")


class TestSimulatorRuleOperations:
    """Test simulator rule CRUD operations"""
    
    def test_create_rule_from_template(self, auth_headers):
        """Test POST /api/simulator/rules/from-template/{template_id}"""
        # Create rule from template
        response = requests.post(f"{BASE_URL}/api/simulator/rules/from-template/profit_50", 
            headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "rule" in data
        rule_id = data["rule"]["id"]
        print(f"✓ Created rule from template: {rule_id}")
        
        # Delete the rule (cleanup)
        response = requests.delete(f"{BASE_URL}/api/simulator/rules/{rule_id}", headers=auth_headers)
        assert response.status_code == 200
        print(f"✓ Deleted test rule")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
