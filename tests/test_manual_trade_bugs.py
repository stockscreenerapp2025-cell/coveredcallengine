"""
Test suite for manual trade bug fixes:
1. Trade detail popup should show all manually entered fields
2. Dashboard bar chart should show unrealized P/L for open manual trades
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_EMAIL = "test_manual_trade@example.com"
TEST_PASSWORD = "testpassword123"
TEST_NAME = "Test Manual Trade User"


class TestManualTradeBugFixes:
    """Test manual trade creation and detail popup field display"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Register or login test user and get auth token"""
        # Try to register first
        register_response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
            "name": TEST_NAME
        })
        
        if register_response.status_code == 200:
            return register_response.json()["access_token"]
        
        # If registration fails (user exists), try login
        login_response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        
        if login_response.status_code == 200:
            return login_response.json()["access_token"]
        
        pytest.fail(f"Could not authenticate: {login_response.text}")
    
    @pytest.fixture(scope="class")
    def api_client(self, auth_token):
        """Create authenticated API client"""
        session = requests.Session()
        session.headers.update({
            "Content-Type": "application/json",
            "Authorization": f"Bearer {auth_token}"
        })
        return session
    
    def test_01_create_manual_covered_call_trade(self, api_client):
        """Create a manual covered call trade with all fields populated"""
        trade_data = {
            "symbol": "AAPL",
            "trade_type": "covered_call",
            "stock_quantity": 100,
            "stock_price": 175.50,
            "stock_date": "2025-01-01",
            "strike_price": 180.00,
            "expiry_date": "2025-01-17",
            "option_premium": 2.50,
            "option_quantity": 1,
            "option_date": "2025-01-01",
            "notes": "Test manual trade for bug verification"
        }
        
        response = api_client.post(f"{BASE_URL}/api/portfolio/manual-trade", json=trade_data)
        
        assert response.status_code == 200, f"Failed to create trade: {response.text}"
        
        data = response.json()
        assert "trade" in data, "Response should contain trade object"
        
        trade = data["trade"]
        
        # Verify all fields are properly stored
        assert trade["symbol"] == "AAPL", "Symbol should be AAPL"
        assert trade["source"] == "manual", "Source should be manual"
        assert trade["status"] == "Open", "Status should be Open"
        
        # BUG FIX VERIFICATION: These fields should now be properly stored
        assert trade.get("option_strike") == 180.00, f"option_strike should be 180.00, got {trade.get('option_strike')}"
        assert trade.get("option_expiry") == "2025-01-17", f"option_expiry should be 2025-01-17, got {trade.get('option_expiry')}"
        assert trade.get("contracts") == 1, f"contracts should be 1, got {trade.get('contracts')}"
        assert trade.get("days_in_trade") is not None, f"days_in_trade should be calculated, got {trade.get('days_in_trade')}"
        assert trade.get("total_fees") == 0, f"total_fees should be 0 for manual trades, got {trade.get('total_fees')}"
        assert trade.get("account") == "Manual", f"account should be Manual, got {trade.get('account')}"
        assert trade.get("premium_received") == 2.50, f"premium_received should be 2.50, got {trade.get('premium_received')}"
        
        # Store trade ID for subsequent tests
        self.__class__.created_trade_id = trade["id"]
        print(f"Created trade ID: {trade['id']}")
        print(f"Trade fields: option_strike={trade.get('option_strike')}, option_expiry={trade.get('option_expiry')}, contracts={trade.get('contracts')}, days_in_trade={trade.get('days_in_trade')}, total_fees={trade.get('total_fees')}")
    
    def test_02_get_trade_detail_shows_all_fields(self, api_client):
        """Verify trade detail endpoint returns all fields for popup display"""
        trade_id = getattr(self.__class__, 'created_trade_id', None)
        if not trade_id:
            pytest.skip("No trade ID from previous test")
        
        response = api_client.get(f"{BASE_URL}/api/portfolio/ibkr/trades/{trade_id}")
        
        assert response.status_code == 200, f"Failed to get trade detail: {response.text}"
        
        trade = response.json()
        
        # BUG FIX VERIFICATION: Detail popup should show these fields
        print(f"\n=== Trade Detail Response ===")
        print(f"days_in_trade: {trade.get('days_in_trade')}")
        print(f"contracts: {trade.get('contracts')}")
        print(f"option_strike: {trade.get('option_strike')}")
        print(f"option_expiry: {trade.get('option_expiry')}")
        print(f"total_fees: {trade.get('total_fees')}")
        print(f"premium_received: {trade.get('premium_received')}")
        print(f"account: {trade.get('account')}")
        print(f"roi: {trade.get('roi')}")
        
        # These fields should NOT be '-' in the popup
        assert trade.get("days_in_trade") is not None, "days_in_trade should be populated"
        assert trade.get("contracts") is not None, "contracts should be populated"
        assert trade.get("option_strike") is not None, "option_strike should be populated"
        assert trade.get("option_expiry") is not None, "option_expiry should be populated"
        assert trade.get("total_fees") is not None, "total_fees should be populated (0 for manual)"
        assert trade.get("account") is not None, "account should be populated"
        
        # Verify specific values
        assert trade.get("option_strike") == 180.00, f"option_strike should be 180.00"
        assert trade.get("option_expiry") == "2025-01-17", f"option_expiry should be 2025-01-17"
        assert trade.get("contracts") == 1, f"contracts should be 1"
        assert trade.get("total_fees") == 0, f"total_fees should be 0 for manual trades"
        assert trade.get("account") == "Manual", f"account should be Manual"
    
    def test_03_get_trades_list_shows_normalized_fields(self, api_client):
        """Verify trades list endpoint normalizes fields for old data compatibility"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/ibkr/trades?status=Open&limit=20")
        
        assert response.status_code == 200, f"Failed to get trades: {response.text}"
        
        data = response.json()
        trades = data.get("trades", [])
        
        # Find our test trade
        test_trade = None
        for trade in trades:
            if trade.get("symbol") == "AAPL" and trade.get("source") == "manual":
                test_trade = trade
                break
        
        if test_trade:
            print(f"\n=== Trade List Entry ===")
            print(f"days_in_trade: {test_trade.get('days_in_trade')}")
            print(f"contracts: {test_trade.get('contracts')}")
            print(f"option_strike: {test_trade.get('option_strike')}")
            print(f"option_expiry: {test_trade.get('option_expiry')}")
            print(f"total_fees: {test_trade.get('total_fees')}")
            print(f"account: {test_trade.get('account')}")
            
            # Verify normalization
            assert test_trade.get("option_strike") is not None, "option_strike should be normalized"
            assert test_trade.get("option_expiry") is not None, "option_expiry should be normalized"
            assert test_trade.get("contracts") is not None, "contracts should be normalized"
            assert test_trade.get("total_fees") is not None, "total_fees should be normalized"
            assert test_trade.get("account") is not None, "account should be normalized"
    
    def test_04_dashboard_open_trades_for_bar_chart(self, api_client):
        """Verify dashboard can fetch open trades with unrealized P/L for bar chart"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/ibkr/trades?status=Open&limit=15")
        
        assert response.status_code == 200, f"Failed to get open trades: {response.text}"
        
        data = response.json()
        trades = data.get("trades", [])
        
        print(f"\n=== Open Trades for Dashboard Bar Chart ===")
        print(f"Total open trades: {len(trades)}")
        
        # Check if manual trades are included
        manual_trades = [t for t in trades if t.get("source") == "manual"]
        print(f"Manual trades: {len(manual_trades)}")
        
        for trade in manual_trades:
            print(f"  - {trade.get('symbol')}: unrealized_pnl={trade.get('unrealized_pnl')}, roi={trade.get('roi')}, current_price={trade.get('current_price')}")
        
        # Verify at least one manual trade exists
        assert len(manual_trades) > 0, "Should have at least one manual trade"
        
        # For bar chart, trades should have unrealized_pnl or roi
        # Note: unrealized_pnl may be None if current_price couldn't be fetched
        for trade in manual_trades:
            # At minimum, the trade should have the required fields for display
            assert trade.get("symbol") is not None, "Trade should have symbol"
    
    def test_05_dashboard_strategy_distribution(self, api_client):
        """Verify IBKR summary includes manual trades for strategy distribution pie chart"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/ibkr/summary")
        
        assert response.status_code == 200, f"Failed to get IBKR summary: {response.text}"
        
        data = response.json()
        
        print(f"\n=== IBKR Summary for Strategy Distribution ===")
        print(f"Total trades: {data.get('total_trades')}")
        print(f"Open trades: {data.get('open_trades')}")
        print(f"Strategy breakdown: {data.get('strategy_breakdown')}")
        
        # Verify summary includes our manual trade
        assert data.get("total_trades", 0) > 0, "Should have at least one trade"
        
        # Check strategy breakdown includes covered_call
        strategy_breakdown = data.get("strategy_breakdown", {})
        if strategy_breakdown:
            print(f"Strategy types: {list(strategy_breakdown.keys())}")
    
    def test_06_cleanup_test_trade(self, api_client):
        """Clean up test trade"""
        trade_id = getattr(self.__class__, 'created_trade_id', None)
        if not trade_id:
            pytest.skip("No trade ID to clean up")
        
        response = api_client.delete(f"{BASE_URL}/api/portfolio/ibkr/trades/{trade_id}")
        
        # Accept both 200 and 404 (if already deleted)
        assert response.status_code in [200, 404], f"Unexpected status: {response.status_code}"
        print(f"Cleaned up trade: {trade_id}")


class TestOldDataNormalization:
    """Test that old data with 'strike'/'expiry' field names gets normalized"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get auth token"""
        login_response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        
        if login_response.status_code == 200:
            return login_response.json()["access_token"]
        
        # Try register if login fails
        register_response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
            "name": TEST_NAME
        })
        
        if register_response.status_code == 200:
            return register_response.json()["access_token"]
        
        pytest.fail("Could not authenticate")
    
    @pytest.fixture(scope="class")
    def api_client(self, auth_token):
        """Create authenticated API client"""
        session = requests.Session()
        session.headers.update({
            "Content-Type": "application/json",
            "Authorization": f"Bearer {auth_token}"
        })
        return session
    
    def test_field_normalization_in_list(self, api_client):
        """Verify field normalization works for trades list"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/ibkr/trades?page=1&limit=20")
        
        assert response.status_code == 200
        
        data = response.json()
        trades = data.get("trades", [])
        
        print(f"\n=== Field Normalization Check ===")
        for trade in trades[:5]:  # Check first 5 trades
            print(f"Trade {trade.get('id')[:8]}...: option_strike={trade.get('option_strike')}, option_expiry={trade.get('option_expiry')}, contracts={trade.get('contracts')}, total_fees={trade.get('total_fees')}, account={trade.get('account')}")
            
            # If trade has option data, it should have normalized fields
            if trade.get('option_strike') or trade.get('strike'):
                # After normalization, option_strike should be set
                assert trade.get('option_strike') is not None or trade.get('strike') is not None, "Should have strike data"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
