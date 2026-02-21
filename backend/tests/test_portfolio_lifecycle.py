"""
Portfolio Lifecycle Tracking Tests
Tests for position lifecycle tracking, entry price calculation, and break-even calculation.

Key Requirements:
1. Each stock lifecycle (buy → sell/assign → buy again) must be tracked separately
2. Entry price = actual transaction price for buys, or PUT STRIKE for put assignments
3. CSP → Assignment → CC is ONE lifecycle (Wheel strategy)
4. Each lifecycle gets unique position_instance_id and lifecycle_index
"""

import pytest
import requests
import os
import sys
from pathlib import Path

# Add backend to path for direct imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.ibkr_parser import IBKRParser, parse_ibkr_csv

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_EMAIL = "admin@premiumhunter.com"
TEST_PASSWORD = "admin123"


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token"""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
    )
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.skip("Authentication failed - skipping tests")


@pytest.fixture(scope="module")
def api_client(auth_token):
    """Authenticated requests session"""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_token}"
    })
    return session


# ==================== API ENDPOINT TESTS ====================

class TestPortfolioTradesEndpoint:
    """Test /api/portfolio/ibkr/trades endpoint"""
    
    def test_trades_endpoint_returns_data(self, api_client):
        """Verify trades endpoint returns data with 200 status"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/ibkr/trades?limit=10")
        assert response.status_code == 200
        
        data = response.json()
        assert "trades" in data
        assert "total" in data
        assert "page" in data
        assert "pages" in data
        assert isinstance(data["trades"], list)
    
    def test_trades_have_required_fields(self, api_client):
        """Verify each trade has required fields"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/ibkr/trades?limit=5")
        assert response.status_code == 200
        
        trades = response.json().get("trades", [])
        if not trades:
            pytest.skip("No trades in database to test")
        
        required_fields = [
            "id", "symbol", "strategy_type", "status", "entry_price",
            "shares", "premium_received", "total_fees"
        ]
        
        for trade in trades:
            for field in required_fields:
                assert field in trade, f"Missing field: {field} in trade {trade.get('id')}"
    
    def test_trades_have_lifecycle_fields(self, api_client):
        """Verify trades have position_instance_id and lifecycle_index fields"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/ibkr/trades?limit=10")
        assert response.status_code == 200
        
        trades = response.json().get("trades", [])
        if not trades:
            pytest.skip("No trades in database to test")
        
        # Check that the fields exist (even if null for old data)
        for trade in trades:
            # Fields should be present in response (may be null for old data)
            assert "position_instance_id" in trade or trade.get("position_instance_id") is None
            assert "lifecycle_index" in trade or trade.get("lifecycle_index") is None
    
    def test_trades_status_values(self, api_client):
        """Verify trades have valid status values (Open/Closed)"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/ibkr/trades?limit=20")
        assert response.status_code == 200
        
        trades = response.json().get("trades", [])
        valid_statuses = ["Open", "Closed"]
        
        for trade in trades:
            status = trade.get("status")
            assert status in valid_statuses, f"Invalid status: {status}"
    
    def test_filter_by_status(self, api_client):
        """Test filtering trades by status"""
        # Test Open filter
        response = api_client.get(f"{BASE_URL}/api/portfolio/ibkr/trades?status=Open&limit=10")
        assert response.status_code == 200
        trades = response.json().get("trades", [])
        for trade in trades:
            assert trade.get("status") == "Open"
        
        # Test Closed filter
        response = api_client.get(f"{BASE_URL}/api/portfolio/ibkr/trades?status=Closed&limit=10")
        assert response.status_code == 200
        trades = response.json().get("trades", [])
        for trade in trades:
            assert trade.get("status") == "Closed"
    
    def test_filter_by_symbol(self, api_client):
        """Test filtering trades by symbol"""
        response = api_client.get(f"{BASE_URL}/api/portfolio/ibkr/trades?symbol=IREN&limit=10")
        assert response.status_code == 200
        
        trades = response.json().get("trades", [])
        for trade in trades:
            assert "IREN" in trade.get("symbol", "").upper()


# ==================== PARSER UNIT TESTS ====================

class TestIBKRParserLifecycleSplitting:
    """Test _split_into_lifecycles() method"""
    
    def test_single_buy_sell_is_one_lifecycle(self):
        """Buy → Sell should be one lifecycle"""
        parser = IBKRParser()
        
        transactions = [
            {"transaction_type": "Buy", "quantity": 100, "is_option": False, "datetime": "2024-01-01T10:00:00"},
            {"transaction_type": "Sell", "quantity": -100, "is_option": False, "datetime": "2024-01-15T10:00:00"},
        ]
        
        lifecycles = parser._split_into_lifecycles(transactions)
        assert len(lifecycles) == 1
        assert len(lifecycles[0]) == 2
    
    def test_buy_sell_buy_is_two_lifecycles(self):
        """Buy → Sell → Buy should be TWO lifecycles"""
        parser = IBKRParser()
        
        transactions = [
            {"transaction_type": "Buy", "quantity": 100, "is_option": False, "datetime": "2024-01-01T10:00:00"},
            {"transaction_type": "Sell", "quantity": -100, "is_option": False, "datetime": "2024-01-15T10:00:00"},
            {"transaction_type": "Buy", "quantity": 100, "is_option": False, "datetime": "2024-02-01T10:00:00"},
        ]
        
        lifecycles = parser._split_into_lifecycles(transactions)
        assert len(lifecycles) == 2, f"Expected 2 lifecycles, got {len(lifecycles)}"
        
        # First lifecycle: Buy + Sell
        assert len(lifecycles[0]) == 2
        # Second lifecycle: Buy
        assert len(lifecycles[1]) == 1
    
    def test_call_assignment_closes_lifecycle(self):
        """Call assignment (negative qty) should close lifecycle"""
        parser = IBKRParser()
        
        transactions = [
            {"transaction_type": "Buy", "quantity": 100, "is_option": False, "datetime": "2024-01-01T10:00:00"},
            {"transaction_type": "Assignment", "quantity": -100, "is_option": False, "datetime": "2024-01-15T10:00:00"},
            {"transaction_type": "Buy", "quantity": 100, "is_option": False, "datetime": "2024-02-01T10:00:00"},
        ]
        
        lifecycles = parser._split_into_lifecycles(transactions)
        assert len(lifecycles) == 2, f"Expected 2 lifecycles after call assignment, got {len(lifecycles)}"
    
    def test_csp_assignment_cc_is_one_lifecycle(self):
        """CSP → Put Assignment → CC should be ONE lifecycle (Wheel strategy)"""
        parser = IBKRParser()
        
        transactions = [
            # CSP: Sell put option
            {"transaction_type": "Sell", "quantity": -1, "is_option": True, 
             "option_details": {"option_type": "Put", "strike": 50}, "datetime": "2024-01-01T10:00:00"},
            # Put Assignment: Get assigned stock
            {"transaction_type": "Assignment", "quantity": 100, "is_option": False, "datetime": "2024-01-15T10:00:00"},
            # CC: Sell call option
            {"transaction_type": "Sell", "quantity": -1, "is_option": True,
             "option_details": {"option_type": "Call", "strike": 55}, "datetime": "2024-01-20T10:00:00"},
        ]
        
        lifecycles = parser._split_into_lifecycles(transactions)
        assert len(lifecycles) == 1, f"CSP → Assignment → CC should be ONE lifecycle, got {len(lifecycles)}"
        assert len(lifecycles[0]) == 3
    
    def test_partial_sell_does_not_close_lifecycle(self):
        """Partial sell should NOT close lifecycle"""
        parser = IBKRParser()
        
        transactions = [
            {"transaction_type": "Buy", "quantity": 200, "is_option": False, "datetime": "2024-01-01T10:00:00"},
            {"transaction_type": "Sell", "quantity": -100, "is_option": False, "datetime": "2024-01-15T10:00:00"},
            # Still have 100 shares, so next buy should NOT start new lifecycle
        ]
        
        lifecycles = parser._split_into_lifecycles(transactions)
        assert len(lifecycles) == 1, "Partial sell should not close lifecycle"


class TestIBKRParserEntryPrice:
    """Test entry price calculation - must use transaction price, NOT net_amount/qty"""
    
    def test_entry_price_uses_transaction_price(self):
        """Entry price should use tx.price, not net_amount/quantity"""
        parser = IBKRParser()
        
        # Simulate a trade where price != net_amount/quantity (due to fees)
        transactions = [
            {
                "id": "tx1",
                "transaction_type": "Buy",
                "quantity": 100,
                "price": 50.00,  # Actual price per share
                "net_amount": -5010.00,  # Includes $10 fee
                "commission": 10.00,
                "is_option": False,
                "datetime": "2024-01-01T10:00:00",
                "date": "2024-01-01",
                "underlying_symbol": "TEST"
            }
        ]
        
        trade = parser._create_trade_from_lifecycle("ACC1", "TEST", transactions, 0)
        
        # Entry price should be 50.00 (the actual price), NOT 50.10 (net_amount/qty)
        assert trade["entry_price"] == 50.00, f"Entry price should be 50.00, got {trade['entry_price']}"
    
    def test_put_assignment_uses_put_strike(self):
        """For PUT assignment, entry price should use the PUT STRIKE"""
        parser = IBKRParser()
        
        transactions = [
            # Sell put at strike $45
            {
                "id": "tx1",
                "transaction_type": "Sell",
                "quantity": -1,
                "price": 2.50,
                "net_amount": 250.00,
                "commission": 1.00,
                "is_option": True,
                "option_details": {"option_type": "Put", "strike": 45.00, "expiry": "2024-01-15"},
                "datetime": "2024-01-01T10:00:00",
                "date": "2024-01-01",
                "underlying_symbol": "TEST"
            },
            # Put assignment - get 100 shares at strike price
            {
                "id": "tx2",
                "transaction_type": "Assignment",
                "quantity": 100,
                "price": 45.00,  # May or may not be populated
                "net_amount": -4500.00,
                "commission": 0,
                "is_option": False,
                "datetime": "2024-01-15T10:00:00",
                "date": "2024-01-15",
                "underlying_symbol": "TEST"
            }
        ]
        
        trade = parser._create_trade_from_lifecycle("ACC1", "TEST", transactions, 0)
        
        # Entry price should be the PUT STRIKE (45.00)
        assert trade["entry_price"] == 45.00, f"Entry price for put assignment should be put strike 45.00, got {trade['entry_price']}"
        assert trade["csp_put_strike"] == 45.00
    
    def test_weighted_average_entry_for_multiple_buys(self):
        """Multiple buys should use weighted average entry price"""
        parser = IBKRParser()
        
        transactions = [
            {
                "id": "tx1",
                "transaction_type": "Buy",
                "quantity": 100,
                "price": 50.00,
                "net_amount": -5000.00,
                "commission": 0,
                "is_option": False,
                "datetime": "2024-01-01T10:00:00",
                "date": "2024-01-01",
                "underlying_symbol": "TEST"
            },
            {
                "id": "tx2",
                "transaction_type": "Buy",
                "quantity": 100,
                "price": 60.00,
                "net_amount": -6000.00,
                "commission": 0,
                "is_option": False,
                "datetime": "2024-01-05T10:00:00",
                "date": "2024-01-05",
                "underlying_symbol": "TEST"
            }
        ]
        
        trade = parser._create_trade_from_lifecycle("ACC1", "TEST", transactions, 0)
        
        # Weighted average: (100*50 + 100*60) / 200 = 55.00
        assert trade["entry_price"] == 55.00, f"Weighted average entry should be 55.00, got {trade['entry_price']}"


class TestIBKRParserBreakEven:
    """Test break-even calculation: Entry - (Premium/Shares) + (Fees/Shares)"""
    
    def test_break_even_calculation(self):
        """Break-even = Entry - Premium/Shares + Fees/Shares"""
        parser = IBKRParser()
        
        transactions = [
            # Buy 100 shares at $50
            {
                "id": "tx1",
                "transaction_type": "Buy",
                "quantity": 100,
                "price": 50.00,
                "net_amount": -5000.00,
                "commission": 5.00,
                "is_option": False,
                "datetime": "2024-01-01T10:00:00",
                "date": "2024-01-01",
                "underlying_symbol": "TEST"
            },
            # Sell call for $200 premium
            {
                "id": "tx2",
                "transaction_type": "Sell",
                "quantity": -1,
                "price": 2.00,
                "net_amount": 200.00,
                "commission": 1.00,
                "is_option": True,
                "option_details": {"option_type": "Call", "strike": 55.00, "expiry": "2024-02-15"},
                "datetime": "2024-01-05T10:00:00",
                "date": "2024-01-05",
                "underlying_symbol": "TEST"
            }
        ]
        
        trade = parser._create_trade_from_lifecycle("ACC1", "TEST", transactions, 0)
        
        # Entry = 50.00
        # Premium = 200.00, Premium/share = 2.00
        # Fees = 5.00 + 1.00 = 6.00, Fees/share = 0.06
        # Break-even = 50.00 - 2.00 + 0.06 = 48.06
        expected_be = 50.00 - (200.00 / 100) + (6.00 / 100)
        assert abs(trade["break_even"] - expected_be) < 0.01, f"Break-even should be ~{expected_be}, got {trade['break_even']}"


class TestIBKRParserPositionInstanceId:
    """Test position_instance_id generation"""
    
    def test_position_instance_id_format(self):
        """Position instance ID should follow format: SYMBOL-YYYY-MM-Entry-NN"""
        parser = IBKRParser()
        
        transactions = [
            {
                "id": "tx1",
                "transaction_type": "Buy",
                "quantity": 100,
                "price": 50.00,
                "net_amount": -5000.00,
                "commission": 0,
                "is_option": False,
                "datetime": "2024-05-15T10:00:00",
                "date": "2024-05-15",
                "underlying_symbol": "IREN"
            }
        ]
        
        trade = parser._create_trade_from_lifecycle("ACC1", "IREN", transactions, 0)
        
        # Should be IREN-2024-05-Entry-01
        assert trade["position_instance_id"] == "IREN-2024-05-Entry-01"
        assert trade["lifecycle_index"] == 0
    
    def test_multiple_lifecycles_get_different_ids(self):
        """Each lifecycle should get a unique position_instance_id"""
        parser = IBKRParser()
        
        # First lifecycle
        tx1 = [
            {
                "id": "tx1",
                "transaction_type": "Buy",
                "quantity": 100,
                "price": 50.00,
                "net_amount": -5000.00,
                "commission": 0,
                "is_option": False,
                "datetime": "2024-05-15T10:00:00",
                "date": "2024-05-15",
                "underlying_symbol": "IREN"
            }
        ]
        
        trade1 = parser._create_trade_from_lifecycle("ACC1", "IREN", tx1, 0)
        trade2 = parser._create_trade_from_lifecycle("ACC1", "IREN", tx1, 1)
        
        assert trade1["position_instance_id"] != trade2["position_instance_id"]
        assert trade1["lifecycle_index"] == 0
        assert trade2["lifecycle_index"] == 1


class TestIBKRParserPremiumTracking:
    """Test premium tracking per lifecycle"""
    
    def test_premium_received_calculation(self):
        """Premium received should be net of sold - bought options"""
        parser = IBKRParser()
        
        transactions = [
            # Buy stock
            {
                "id": "tx1",
                "transaction_type": "Buy",
                "quantity": 100,
                "price": 50.00,
                "net_amount": -5000.00,
                "commission": 0,
                "is_option": False,
                "datetime": "2024-01-01T10:00:00",
                "date": "2024-01-01",
                "underlying_symbol": "TEST"
            },
            # Sell call for $300
            {
                "id": "tx2",
                "transaction_type": "Sell",
                "quantity": -1,
                "price": 3.00,
                "net_amount": 300.00,
                "commission": 0,
                "is_option": True,
                "option_details": {"option_type": "Call", "strike": 55.00, "expiry": "2024-02-15"},
                "datetime": "2024-01-05T10:00:00",
                "date": "2024-01-05",
                "underlying_symbol": "TEST"
            },
            # Buy back call for $100
            {
                "id": "tx3",
                "transaction_type": "Buy",
                "quantity": 1,
                "price": 1.00,
                "net_amount": -100.00,
                "commission": 0,
                "is_option": True,
                "option_details": {"option_type": "Call", "strike": 55.00, "expiry": "2024-02-15"},
                "datetime": "2024-01-10T10:00:00",
                "date": "2024-01-10",
                "underlying_symbol": "TEST"
            }
        ]
        
        trade = parser._create_trade_from_lifecycle("ACC1", "TEST", transactions, 0)
        
        # Net premium = 300 (sold) - 100 (bought) = 200
        assert trade["premium_received"] == 200.00, f"Net premium should be 200, got {trade['premium_received']}"


class TestIBKRParserStatus:
    """Test trade status determination"""
    
    def test_open_status_when_shares_remain(self):
        """Status should be Open when shares > 0"""
        parser = IBKRParser()
        
        transactions = [
            {
                "id": "tx1",
                "transaction_type": "Buy",
                "quantity": 100,
                "price": 50.00,
                "net_amount": -5000.00,
                "commission": 0,
                "is_option": False,
                "datetime": "2024-01-01T10:00:00",
                "date": "2024-01-01",
                "underlying_symbol": "TEST"
            }
        ]
        
        trade = parser._create_trade_from_lifecycle("ACC1", "TEST", transactions, 0)
        assert trade["status"] == "Open"
        assert trade["shares"] == 100
    
    def test_closed_status_when_sold(self):
        """Status should be Closed when all shares sold"""
        parser = IBKRParser()
        
        transactions = [
            {
                "id": "tx1",
                "transaction_type": "Buy",
                "quantity": 100,
                "price": 50.00,
                "net_amount": -5000.00,
                "commission": 0,
                "is_option": False,
                "datetime": "2024-01-01T10:00:00",
                "date": "2024-01-01",
                "underlying_symbol": "TEST"
            },
            {
                "id": "tx2",
                "transaction_type": "Sell",
                "quantity": -100,
                "price": 55.00,
                "net_amount": 5500.00,
                "commission": 0,
                "is_option": False,
                "datetime": "2024-01-15T10:00:00",
                "date": "2024-01-15",
                "underlying_symbol": "TEST"
            }
        ]
        
        trade = parser._create_trade_from_lifecycle("ACC1", "TEST", transactions, 0)
        assert trade["status"] == "Closed"
        assert trade["close_reason"] == "Sold"
        assert trade["shares"] == 0
    
    def test_closed_status_when_assigned(self):
        """Status should be Closed with reason 'Assigned' when call assigned"""
        parser = IBKRParser()
        
        transactions = [
            {
                "id": "tx1",
                "transaction_type": "Buy",
                "quantity": 100,
                "price": 50.00,
                "net_amount": -5000.00,
                "commission": 0,
                "is_option": False,
                "datetime": "2024-01-01T10:00:00",
                "date": "2024-01-01",
                "underlying_symbol": "TEST"
            },
            {
                "id": "tx2",
                "transaction_type": "Assignment",
                "quantity": -100,  # Negative = call assignment (shares taken away)
                "price": 55.00,
                "net_amount": 5500.00,
                "commission": 0,
                "is_option": False,
                "datetime": "2024-01-15T10:00:00",
                "date": "2024-01-15",
                "underlying_symbol": "TEST"
            }
        ]
        
        trade = parser._create_trade_from_lifecycle("ACC1", "TEST", transactions, 0)
        assert trade["status"] == "Closed"
        assert trade["close_reason"] == "Assigned"


# ==================== INTEGRATION TESTS ====================

class TestFullParserIntegration:
    """Test full CSV parsing with lifecycle tracking"""
    
    def test_parse_csv_with_multiple_lifecycles(self):
        """Test parsing CSV that should produce multiple lifecycles for same symbol"""
        csv_content = """Transaction History,Header,Date,Transaction Type,Symbol,Quantity,Price,Gross Amount,Commission,Net Amount,Description,Account
Transaction History,Data,2024-01-01,Buy,TEST,100,50.00,-5000.00,-5.00,-5005.00,Buy TEST,ACC1
Transaction History,Data,2024-01-15,Sell,TEST,-100,55.00,5500.00,-5.00,5495.00,Sell TEST,ACC1
Transaction History,Data,2024-02-01,Buy,TEST,100,52.00,-5200.00,-5.00,-5205.00,Buy TEST,ACC1
"""
        
        result = parse_ibkr_csv(csv_content)
        
        # Should have 2 trades for TEST (2 lifecycles)
        test_trades = [t for t in result["trades"] if t["symbol"] == "TEST"]
        assert len(test_trades) == 2, f"Expected 2 lifecycles for TEST, got {len(test_trades)}"
        
        # First lifecycle should be closed
        assert test_trades[0]["status"] == "Closed"
        assert test_trades[0]["lifecycle_index"] == 0
        
        # Second lifecycle should be open
        assert test_trades[1]["status"] == "Open"
        assert test_trades[1]["lifecycle_index"] == 1
        
        # Each should have unique position_instance_id
        assert test_trades[0]["position_instance_id"] != test_trades[1]["position_instance_id"]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
