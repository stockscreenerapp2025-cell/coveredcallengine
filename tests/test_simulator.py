"""
Test suite for Trade Simulator feature
Tests: POST /api/simulator/trade, GET /api/simulator/trades, GET /api/simulator/summary, POST /api/simulator/update-prices
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_EMAIL = "test_manual_trade@example.com"
TEST_PASSWORD = "testpassword123"


class TestSimulatorAPI:
    """Test suite for Simulator API endpoints"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session with authentication"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.token = None
        
        # Login to get token
        login_response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        
        if login_response.status_code == 200:
            self.token = login_response.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        else:
            pytest.skip(f"Authentication failed: {login_response.status_code} - {login_response.text}")
    
    def test_01_auth_works(self):
        """Test that authentication is working"""
        response = self.session.get(f"{BASE_URL}/api/auth/me")
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == TEST_EMAIL
        print(f"✓ Authenticated as {data['email']}")
    
    def test_02_get_simulator_summary(self):
        """Test GET /api/simulator/summary endpoint"""
        response = self.session.get(f"{BASE_URL}/api/simulator/summary")
        assert response.status_code == 200
        data = response.json()
        
        # Verify summary structure
        assert "total_trades" in data
        assert "active_trades" in data
        assert "total_pnl" in data
        assert "win_rate" in data
        assert "total_capital_deployed" in data
        print(f"✓ Summary: {data['total_trades']} total trades, {data['active_trades']} active")
    
    def test_03_get_simulator_trades(self):
        """Test GET /api/simulator/trades endpoint"""
        response = self.session.get(f"{BASE_URL}/api/simulator/trades")
        assert response.status_code == 200
        data = response.json()
        
        # Verify response structure
        assert "trades" in data
        assert "total" in data
        assert "page" in data
        assert "pages" in data
        print(f"✓ Trades list: {data['total']} trades found")
        
        # If trades exist, verify trade structure
        if data["trades"]:
            trade = data["trades"][0]
            assert "id" in trade
            assert "symbol" in trade
            assert "strategy_type" in trade
            assert "status" in trade
            print(f"✓ First trade: {trade['symbol']} - {trade['strategy_type']} - {trade['status']}")
    
    def test_04_get_trades_with_filters(self):
        """Test GET /api/simulator/trades with status and strategy filters"""
        # Test status filter
        response = self.session.get(f"{BASE_URL}/api/simulator/trades?status=active")
        assert response.status_code == 200
        data = response.json()
        print(f"✓ Active trades filter: {data['total']} trades")
        
        # Test strategy filter
        response = self.session.get(f"{BASE_URL}/api/simulator/trades?strategy=covered_call")
        assert response.status_code == 200
        data = response.json()
        print(f"✓ Covered call filter: {data['total']} trades")
    
    def test_05_add_simulator_trade_covered_call(self):
        """Test POST /api/simulator/trade - Add covered call trade"""
        trade_data = {
            "symbol": "TEST_SIM_CC",
            "strategy_type": "covered_call",
            "underlying_price": 50.00,
            "short_call_strike": 55.00,
            "short_call_expiry": "2025-01-31",
            "short_call_premium": 1.50,
            "short_call_delta": 0.30,
            "short_call_iv": 0.35,
            "contracts": 1,
            "scan_parameters": {
                "score": 75,
                "roi_pct": 3.0,
                "dte": 30
            }
        }
        
        response = self.session.post(f"{BASE_URL}/api/simulator/trade", json=trade_data)
        
        # May get 400 if duplicate exists - that's expected
        if response.status_code == 400 and "Duplicate" in response.text:
            print("✓ Duplicate trade check working (trade already exists)")
            return
        
        assert response.status_code == 200
        data = response.json()
        assert "trade" in data
        trade = data["trade"]
        assert trade["symbol"] == "TEST_SIM_CC"
        assert trade["strategy_type"] == "covered_call"
        assert trade["status"] == "active"
        print(f"✓ Added covered call trade: {trade['symbol']}")
    
    def test_06_add_simulator_trade_pmcc(self):
        """Test POST /api/simulator/trade - Add PMCC trade"""
        trade_data = {
            "symbol": "TEST_SIM_PMCC",
            "strategy_type": "pmcc",
            "underlying_price": 100.00,
            "short_call_strike": 110.00,
            "short_call_expiry": "2025-01-31",
            "short_call_premium": 2.00,
            "short_call_delta": 0.25,
            "short_call_iv": 0.30,
            "leaps_strike": 80.00,
            "leaps_expiry": "2026-01-16",
            "leaps_premium": 25.00,
            "leaps_delta": 0.85,
            "contracts": 1,
            "scan_parameters": {
                "score": 70,
                "net_debit": 2300,
                "max_profit": 3000
            }
        }
        
        response = self.session.post(f"{BASE_URL}/api/simulator/trade", json=trade_data)
        
        # May get 400 if duplicate exists
        if response.status_code == 400 and "Duplicate" in response.text:
            print("✓ Duplicate trade check working (PMCC trade already exists)")
            return
        
        assert response.status_code == 200
        data = response.json()
        assert "trade" in data
        trade = data["trade"]
        assert trade["symbol"] == "TEST_SIM_PMCC"
        assert trade["strategy_type"] == "pmcc"
        print(f"✓ Added PMCC trade: {trade['symbol']}")
    
    def test_07_update_prices(self):
        """Test POST /api/simulator/update-prices endpoint"""
        response = self.session.post(f"{BASE_URL}/api/simulator/update-prices")
        assert response.status_code == 200
        data = response.json()
        
        assert "updated" in data
        assert "expired" in data
        assert "assigned" in data
        print(f"✓ Update prices: {data['updated']} updated, {data['expired']} expired, {data['assigned']} assigned")
    
    def test_08_get_trade_detail(self):
        """Test GET /api/simulator/trades/{trade_id} endpoint"""
        # First get list of trades
        response = self.session.get(f"{BASE_URL}/api/simulator/trades")
        assert response.status_code == 200
        trades = response.json().get("trades", [])
        
        if not trades:
            pytest.skip("No trades to get detail for")
        
        trade_id = trades[0]["id"]
        response = self.session.get(f"{BASE_URL}/api/simulator/trades/{trade_id}")
        assert response.status_code == 200
        trade = response.json()
        
        assert trade["id"] == trade_id
        assert "symbol" in trade
        assert "strategy_type" in trade
        assert "status" in trade
        print(f"✓ Trade detail: {trade['symbol']} - {trade['status']}")
    
    def test_09_summary_after_trades(self):
        """Test summary reflects trades correctly"""
        response = self.session.get(f"{BASE_URL}/api/simulator/summary")
        assert response.status_code == 200
        data = response.json()
        
        # Verify summary has data
        assert isinstance(data["total_trades"], int)
        assert isinstance(data["active_trades"], int)
        assert isinstance(data["total_pnl"], (int, float))
        assert isinstance(data["win_rate"], (int, float))
        
        # Check by_strategy breakdown
        if "by_strategy" in data:
            print(f"✓ Summary by strategy: {data['by_strategy']}")
        
        print(f"✓ Summary: Total P/L=${data['total_pnl']:.2f}, Win Rate={data['win_rate']:.1f}%")
    
    def test_10_cleanup_test_trades(self):
        """Cleanup: Delete test trades created during testing"""
        # Get all trades
        response = self.session.get(f"{BASE_URL}/api/simulator/trades?limit=100")
        assert response.status_code == 200
        trades = response.json().get("trades", [])
        
        deleted = 0
        for trade in trades:
            if trade["symbol"].startswith("TEST_SIM_"):
                del_response = self.session.delete(f"{BASE_URL}/api/simulator/trades/{trade['id']}")
                if del_response.status_code == 200:
                    deleted += 1
        
        print(f"✓ Cleaned up {deleted} test trades")


class TestScreenerSimulateButton:
    """Test that Screener returns data that can be used for simulation"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session with authentication"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login
        login_response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        
        if login_response.status_code == 200:
            self.token = login_response.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        else:
            pytest.skip("Authentication failed")
    
    def test_screener_returns_data_for_simulation(self):
        """Test that screener returns data with fields needed for simulation"""
        response = self.session.get(f"{BASE_URL}/api/screener/covered-calls")
        assert response.status_code == 200
        data = response.json()
        
        opportunities = data.get("opportunities", [])
        if not opportunities:
            print("⚠ No screener opportunities returned (may be market closed)")
            return
        
        # Check first opportunity has required fields for simulation
        opp = opportunities[0]
        required_fields = ["symbol", "stock_price", "strike", "expiry", "premium", "delta", "iv"]
        
        for field in required_fields:
            assert field in opp, f"Missing field: {field}"
        
        print(f"✓ Screener data has all fields for simulation: {opp['symbol']}")
    
    def test_pmcc_returns_data_for_simulation(self):
        """Test that PMCC screener returns data with fields needed for simulation"""
        response = self.session.get(f"{BASE_URL}/api/screener/pmcc")
        assert response.status_code == 200
        data = response.json()
        
        opportunities = data.get("opportunities", [])
        if not opportunities:
            print("⚠ No PMCC opportunities returned (may be market closed)")
            return
        
        # Check first opportunity has required fields for PMCC simulation
        opp = opportunities[0]
        required_fields = ["symbol", "stock_price", "short_strike", "short_expiry", "short_premium", 
                          "leaps_strike", "leaps_expiry", "leaps_cost"]
        
        for field in required_fields:
            assert field in opp, f"Missing field: {field}"
        
        print(f"✓ PMCC data has all fields for simulation: {opp['symbol']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
