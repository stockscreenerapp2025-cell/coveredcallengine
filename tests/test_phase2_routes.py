"""
Test suite for Phase 2 refactored routes in Covered Call Engine
Tests: Options, Admin routes (newly refactored) + Screener, Portfolio, Simulator (still in server.py)
Phase 2 refactoring: 10 routers extracted from server.py (7333 lines → 5582 lines, 24% reduction)
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
TEST_ADMIN_EMAIL = "admin@premiumhunter.com"
TEST_ADMIN_PASSWORD = "admin123"


def get_auth_token(email=TEST_ADMIN_EMAIL, password=TEST_ADMIN_PASSWORD):
    """Helper to get auth token"""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password}
    )
    if response.status_code == 200:
        return response.json()["access_token"]
    return None


class TestOptionsRoutes:
    """Test options routes from routes/options.py (newly refactored)"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get auth token before each test"""
        self.token = get_auth_token()
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_get_options_chain(self):
        """Test GET /api/options/chain/{symbol}"""
        response = requests.get(
            f"{BASE_URL}/api/options/chain/AAPL",
            headers=self.headers,
            timeout=60
        )
        assert response.status_code == 200, f"Options chain failed: {response.text}"
        data = response.json()
        assert "symbol" in data
        assert data["symbol"] == "AAPL"
        assert "stock_price" in data
        assert "options" in data
        print(f"✓ Options chain AAPL: {len(data['options'])} options, stock_price=${data['stock_price']}, is_live={data.get('is_live', False)}")
    
    def test_get_options_chain_with_expiry(self):
        """Test GET /api/options/chain/{symbol}?expiry=YYYY-MM-DD"""
        # Get a future expiry date (next Friday)
        today = datetime.now()
        days_until_friday = (4 - today.weekday()) % 7
        if days_until_friday == 0:
            days_until_friday = 7
        next_friday = (today + timedelta(days=days_until_friday)).strftime("%Y-%m-%d")
        
        response = requests.get(
            f"{BASE_URL}/api/options/chain/AAPL?expiry={next_friday}",
            headers=self.headers,
            timeout=60
        )
        assert response.status_code == 200
        data = response.json()
        assert "options" in data
        print(f"✓ Options chain AAPL with expiry={next_friday}: {len(data['options'])} options")
    
    def test_get_option_expirations(self):
        """Test GET /api/options/expirations/{symbol}"""
        response = requests.get(
            f"{BASE_URL}/api/options/expirations/AAPL",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        # Check structure
        if data:
            assert "date" in data[0]
            assert "dte" in data[0]
        print(f"✓ Option expirations AAPL: {len(data)} expirations available")
    
    def test_get_options_chain_msft(self):
        """Test GET /api/options/chain/{symbol} for MSFT"""
        response = requests.get(
            f"{BASE_URL}/api/options/chain/MSFT",
            headers=self.headers,
            timeout=60
        )
        assert response.status_code == 200
        data = response.json()
        assert data["symbol"] == "MSFT"
        print(f"✓ Options chain MSFT: {len(data['options'])} options")


class TestAdminRoutes:
    """Test admin routes from routes/admin.py (newly refactored)"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get admin auth token before each test"""
        self.token = get_auth_token()
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_get_admin_settings(self):
        """Test GET /api/admin/settings"""
        response = requests.get(
            f"{BASE_URL}/api/admin/settings",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        # Settings should be a dict (may be empty or have masked keys)
        assert isinstance(data, dict)
        print(f"✓ Admin settings: {list(data.keys())[:5]}...")
    
    def test_get_dashboard_stats(self):
        """Test GET /api/admin/dashboard-stats"""
        response = requests.get(
            f"{BASE_URL}/api/admin/dashboard-stats",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "users" in data
        assert "subscriptions" in data
        assert "revenue" in data
        assert "alerts" in data
        print(f"✓ Dashboard stats: users={data['users']['total']}, active_subs={data['subscriptions']['active']}, MRR=${data['revenue']['mrr']}")
    
    def test_get_admin_users_paginated(self):
        """Test GET /api/admin/users with pagination"""
        response = requests.get(
            f"{BASE_URL}/api/admin/users?page=1&limit=10",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "users" in data
        assert "total" in data
        assert "page" in data
        assert "pages" in data
        assert isinstance(data["users"], list)
        print(f"✓ Admin users: {len(data['users'])} users on page 1, total={data['total']}, pages={data['pages']}")
    
    def test_get_admin_users_with_search(self):
        """Test GET /api/admin/users with search filter"""
        response = requests.get(
            f"{BASE_URL}/api/admin/users?search=admin",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "users" in data
        print(f"✓ Admin users search 'admin': {len(data['users'])} results")
    
    def test_get_cache_stats(self):
        """Test GET /api/admin/cache-stats"""
        response = requests.get(
            f"{BASE_URL}/api/admin/cache-stats",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "total_entries" in data
        print(f"✓ Cache stats: {data['total_entries']} entries")
    
    def test_get_audit_logs(self):
        """Test GET /api/admin/audit-logs"""
        response = requests.get(
            f"{BASE_URL}/api/admin/audit-logs?page=1&limit=10",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "logs" in data
        assert "total" in data
        assert "page" in data
        print(f"✓ Audit logs: {len(data['logs'])} logs on page 1, total={data['total']}")
    
    def test_get_integration_settings(self):
        """Test GET /api/admin/integration-settings"""
        response = requests.get(
            f"{BASE_URL}/api/admin/integration-settings",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "stripe" in data
        assert "email" in data
        print(f"✓ Integration settings: stripe_configured={data['stripe']['webhook_secret_configured']}, email_configured={data['email']['resend_api_key_configured']}")
    
    def test_get_email_templates(self):
        """Test GET /api/admin/email-templates"""
        response = requests.get(
            f"{BASE_URL}/api/admin/email-templates",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "templates" in data
        print(f"✓ Email templates: {len(data['templates'])} templates")
    
    def test_get_email_automation_templates(self):
        """Test GET /api/admin/email-automation/templates"""
        response = requests.get(
            f"{BASE_URL}/api/admin/email-automation/templates",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "templates" in data
        print(f"✓ Email automation templates: {len(data['templates'])} templates")
    
    def test_get_email_automation_rules(self):
        """Test GET /api/admin/email-automation/rules"""
        response = requests.get(
            f"{BASE_URL}/api/admin/email-automation/rules",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "rules" in data
        assert "trigger_types" in data
        assert "action_types" in data
        print(f"✓ Email automation rules: {len(data['rules'])} rules")
    
    def test_get_email_automation_logs(self):
        """Test GET /api/admin/email-automation/logs"""
        response = requests.get(
            f"{BASE_URL}/api/admin/email-automation/logs?page=1&limit=10",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "logs" in data
        assert "total" in data
        print(f"✓ Email automation logs: {len(data['logs'])} logs")
    
    def test_get_email_automation_stats(self):
        """Test GET /api/admin/email-automation/stats"""
        response = requests.get(
            f"{BASE_URL}/api/admin/email-automation/stats",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        # Stats should be a dict with email statistics
        assert isinstance(data, dict)
        print(f"✓ Email automation stats: {list(data.keys())[:5]}...")
    
    def test_admin_requires_auth(self):
        """Test that admin routes require authentication"""
        response = requests.get(f"{BASE_URL}/api/admin/settings")
        assert response.status_code in [401, 403]
        print("✓ Admin routes correctly require authentication")


class TestScreenerRoutes:
    """Test screener routes (still in server.py)"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get auth token before each test"""
        self.token = get_auth_token()
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_screen_covered_calls(self):
        """Test GET /api/screener/covered-calls"""
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls?min_roi=0.5&max_dte=45",
            headers=self.headers,
            timeout=120  # Screener can take time
        )
        assert response.status_code == 200, f"Screener failed: {response.text}"
        data = response.json()
        assert "opportunities" in data
        assert "total" in data
        print(f"✓ Covered calls screener: {data['total']} opportunities, is_live={data.get('is_live', False)}, is_mock={data.get('is_mock', False)}")
    
    def test_screen_covered_calls_with_filters(self):
        """Test GET /api/screener/covered-calls with various filters"""
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls?min_roi=1.0&max_dte=30&min_delta=0.2&max_delta=0.4&min_price=20&max_price=100",
            headers=self.headers,
            timeout=120
        )
        assert response.status_code == 200
        data = response.json()
        assert "opportunities" in data
        # Verify filters are applied
        for opp in data.get("opportunities", [])[:5]:
            assert opp.get("roi_pct", 0) >= 1.0
            assert opp.get("dte", 0) <= 30
        print(f"✓ Covered calls with filters: {data['total']} opportunities")
    
    def test_screen_covered_calls_weekly_only(self):
        """Test GET /api/screener/covered-calls?weekly_only=true"""
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls?weekly_only=true",
            headers=self.headers,
            timeout=120
        )
        assert response.status_code == 200
        data = response.json()
        # All opportunities should have DTE <= 7
        for opp in data.get("opportunities", [])[:5]:
            assert opp.get("dte", 0) <= 7
        print(f"✓ Weekly covered calls: {data['total']} opportunities")
    
    def test_dashboard_opportunities(self):
        """Test GET /api/screener/dashboard-opportunities"""
        response = requests.get(
            f"{BASE_URL}/api/screener/dashboard-opportunities",
            headers=self.headers,
            timeout=120
        )
        assert response.status_code == 200
        data = response.json()
        # Should have opportunities or message
        assert "opportunities" in data or "message" in data
        print(f"✓ Dashboard opportunities: {len(data.get('opportunities', []))} opportunities")
    
    def test_dashboard_pmcc(self):
        """Test GET /api/screener/dashboard-pmcc"""
        response = requests.get(
            f"{BASE_URL}/api/screener/dashboard-pmcc",
            headers=self.headers,
            timeout=120
        )
        assert response.status_code == 200
        data = response.json()
        assert "opportunities" in data or "message" in data
        print(f"✓ Dashboard PMCC: {len(data.get('opportunities', []))} opportunities")
    
    def test_screen_pmcc(self):
        """Test GET /api/screener/pmcc"""
        response = requests.get(
            f"{BASE_URL}/api/screener/pmcc?min_roi=1.0",
            headers=self.headers,
            timeout=120
        )
        assert response.status_code == 200
        data = response.json()
        assert "opportunities" in data
        print(f"✓ PMCC screener: {data.get('total', len(data.get('opportunities', [])))} opportunities")
    
    def test_get_saved_filters(self):
        """Test GET /api/screener/filters"""
        response = requests.get(
            f"{BASE_URL}/api/screener/filters",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Saved filters: {len(data)} filters")
    
    def test_save_and_delete_filter(self):
        """Test POST and DELETE /api/screener/filters"""
        # Save a filter
        filter_name = f"TEST_filter_{uuid.uuid4().hex[:8]}"
        save_response = requests.post(
            f"{BASE_URL}/api/screener/filters",
            headers=self.headers,
            json={
                "name": filter_name,
                "filters": {"min_roi": 1.0, "max_dte": 30}
            }
        )
        assert save_response.status_code == 200
        filter_id = save_response.json().get("id")
        print(f"✓ Saved filter: {filter_name}, id={filter_id}")
        
        # Delete the filter
        if filter_id:
            delete_response = requests.delete(
                f"{BASE_URL}/api/screener/filters/{filter_id}",
                headers=self.headers
            )
            assert delete_response.status_code == 200
            print(f"✓ Deleted filter: {filter_id}")


class TestPortfolioRoutes:
    """Test portfolio routes (still in server.py)"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get auth token before each test"""
        self.token = get_auth_token()
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_get_portfolio_positions(self):
        """Test GET /api/portfolio/positions"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/positions",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Portfolio positions: {len(data)} positions")
    
    def test_add_portfolio_position(self):
        """Test POST /api/portfolio/positions"""
        position_data = {
            "symbol": f"TEST{uuid.uuid4().hex[:4].upper()}",
            "position_type": "covered_call",
            "shares": 100,
            "avg_cost": 150.00,
            "option_strike": 155.00,
            "option_expiry": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
            "option_premium": 3.50,
            "notes": "Test position"
        }
        response = requests.post(
            f"{BASE_URL}/api/portfolio/positions",
            headers=self.headers,
            json=position_data
        )
        assert response.status_code == 200, f"Add position failed: {response.text}"
        data = response.json()
        assert "id" in data
        print(f"✓ Added portfolio position: {position_data['symbol']}, id={data['id']}")
        return data["id"]
    
    def test_get_portfolio_summary(self):
        """Test GET /api/portfolio/summary"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/summary",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        # Summary should have portfolio metrics
        assert isinstance(data, dict)
        print(f"✓ Portfolio summary: {list(data.keys())[:5]}...")
    
    def test_get_ibkr_trades(self):
        """Test GET /api/portfolio/ibkr/trades"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/ibkr/trades?page=1&limit=10",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "trades" in data
        assert "total" in data
        print(f"✓ IBKR trades: {len(data['trades'])} trades, total={data['total']}")
    
    def test_get_ibkr_summary(self):
        """Test GET /api/portfolio/ibkr/summary"""
        response = requests.get(
            f"{BASE_URL}/api/portfolio/ibkr/summary",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        print(f"✓ IBKR summary: {list(data.keys())[:5]}...")
    
    def test_add_manual_trade(self):
        """Test POST /api/portfolio/manual-trade"""
        trade_data = {
            "symbol": f"TEST{uuid.uuid4().hex[:4].upper()}",
            "trade_type": "covered_call",
            "underlying_price": 150.00,
            "shares": 100,
            "strike_price": 155.00,
            "expiration_date": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
            "premium_received": 3.50,
            "contracts": 1,
            "notes": "Test manual trade"
        }
        response = requests.post(
            f"{BASE_URL}/api/portfolio/manual-trade",
            headers=self.headers,
            json=trade_data
        )
        assert response.status_code == 200, f"Add manual trade failed: {response.text}"
        data = response.json()
        assert "id" in data or "trade_id" in data
        trade_id = data.get("id") or data.get("trade_id")
        print(f"✓ Added manual trade: {trade_data['symbol']}, id={trade_id}")
        return trade_id


class TestSimulatorRoutes:
    """Test simulator routes (still in server.py)"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get auth token before each test"""
        self.token = get_auth_token()
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_get_simulator_trades(self):
        """Test GET /api/simulator/trades"""
        response = requests.get(
            f"{BASE_URL}/api/simulator/trades?page=1&limit=10",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "trades" in data
        assert "total" in data
        print(f"✓ Simulator trades: {len(data['trades'])} trades, total={data['total']}")
    
    def test_add_simulator_trade(self):
        """Test POST /api/simulator/trade"""
        trade_data = {
            "symbol": f"SIM{uuid.uuid4().hex[:4].upper()}",
            "trade_type": "covered_call",
            "underlying_price": 100.00,
            "shares": 100,
            "strike_price": 105.00,
            "expiration_date": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
            "premium_received": 2.50,
            "contracts": 1,
            "notes": "Test simulator trade"
        }
        response = requests.post(
            f"{BASE_URL}/api/simulator/trade",
            headers=self.headers,
            json=trade_data
        )
        assert response.status_code == 200, f"Add simulator trade failed: {response.text}"
        data = response.json()
        assert "id" in data or "trade_id" in data
        trade_id = data.get("id") or data.get("trade_id")
        print(f"✓ Added simulator trade: {trade_data['symbol']}, id={trade_id}")
        return trade_id
    
    def test_get_simulator_trade_detail(self):
        """Test GET /api/simulator/trades/{trade_id}"""
        # First add a trade
        trade_data = {
            "symbol": f"DET{uuid.uuid4().hex[:4].upper()}",
            "trade_type": "covered_call",
            "underlying_price": 100.00,
            "shares": 100,
            "strike_price": 105.00,
            "expiration_date": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
            "premium_received": 2.50,
            "contracts": 1
        }
        add_response = requests.post(
            f"{BASE_URL}/api/simulator/trade",
            headers=self.headers,
            json=trade_data
        )
        trade_id = add_response.json().get("id") or add_response.json().get("trade_id")
        
        if trade_id:
            # Get trade detail
            response = requests.get(
                f"{BASE_URL}/api/simulator/trades/{trade_id}",
                headers=self.headers
            )
            assert response.status_code == 200
            data = response.json()
            assert data.get("symbol") == trade_data["symbol"]
            print(f"✓ Simulator trade detail: {data.get('symbol')}")
    
    def test_delete_simulator_trade(self):
        """Test DELETE /api/simulator/trades/{trade_id}"""
        # First add a trade
        trade_data = {
            "symbol": f"DEL{uuid.uuid4().hex[:4].upper()}",
            "trade_type": "covered_call",
            "underlying_price": 100.00,
            "shares": 100,
            "strike_price": 105.00,
            "expiration_date": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
            "premium_received": 2.50,
            "contracts": 1
        }
        add_response = requests.post(
            f"{BASE_URL}/api/simulator/trade",
            headers=self.headers,
            json=trade_data
        )
        trade_id = add_response.json().get("id") or add_response.json().get("trade_id")
        
        if trade_id:
            # Delete the trade
            response = requests.delete(
                f"{BASE_URL}/api/simulator/trades/{trade_id}",
                headers=self.headers
            )
            assert response.status_code == 200
            print(f"✓ Deleted simulator trade: {trade_id}")


class TestRouteIntegration:
    """Integration tests for Phase 2 routes"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get auth token before each test"""
        self.token = get_auth_token()
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_options_to_screener_flow(self):
        """Test flow: Get options chain -> Use in screener"""
        # Get options for AAPL
        options_response = requests.get(
            f"{BASE_URL}/api/options/chain/AAPL",
            headers=self.headers,
            timeout=60
        )
        assert options_response.status_code == 200
        options_data = options_response.json()
        
        # Run screener
        screener_response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls?min_roi=0.5",
            headers=self.headers,
            timeout=120
        )
        assert screener_response.status_code == 200
        
        print(f"✓ Options to screener flow: {len(options_data['options'])} options, screener found {screener_response.json()['total']} opportunities")
    
    def test_admin_dashboard_flow(self):
        """Test admin dashboard data flow"""
        # Get dashboard stats
        stats_response = requests.get(
            f"{BASE_URL}/api/admin/dashboard-stats",
            headers=self.headers
        )
        assert stats_response.status_code == 200
        
        # Get users
        users_response = requests.get(
            f"{BASE_URL}/api/admin/users?page=1&limit=5",
            headers=self.headers
        )
        assert users_response.status_code == 200
        
        # Get audit logs
        logs_response = requests.get(
            f"{BASE_URL}/api/admin/audit-logs?page=1&limit=5",
            headers=self.headers
        )
        assert logs_response.status_code == 200
        
        stats = stats_response.json()
        users = users_response.json()
        logs = logs_response.json()
        
        print(f"✓ Admin dashboard flow: {stats['users']['total']} users, {users['total']} in list, {logs['total']} audit logs")
    
    def test_portfolio_simulator_flow(self):
        """Test portfolio and simulator integration"""
        # Get portfolio positions
        portfolio_response = requests.get(
            f"{BASE_URL}/api/portfolio/positions",
            headers=self.headers
        )
        assert portfolio_response.status_code == 200
        
        # Get simulator trades
        simulator_response = requests.get(
            f"{BASE_URL}/api/simulator/trades",
            headers=self.headers
        )
        assert simulator_response.status_code == 200
        
        portfolio = portfolio_response.json()
        simulator = simulator_response.json()
        
        print(f"✓ Portfolio/Simulator flow: {len(portfolio)} positions, {simulator['total']} simulator trades")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
