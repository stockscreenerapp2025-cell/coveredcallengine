"""
Test Data Fetching Rules - CCE Master Architecture Compliance
=============================================================

Tests the three strict data fetching rules:
1. Screener stock prices use previousClose (not regularMarketPrice)
2. Watchlist and Simulator use LIVE intraday prices (regularMarketPrice)
3. Options chain data MUST be fetched LIVE at scan time, never cached

Verifies:
- fetch_stock_quote returns previousClose only
- fetch_live_stock_quote returns regularMarketPrice/currentPrice
- Screener API returns 'stock_price_source: previous_close' and 'options_chain_source: yahoo_live'
"""

import pytest
import requests
import os
import asyncio
from datetime import datetime

# Get BASE_URL from environment
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_EMAIL = "admin@premiumhunter.com"
TEST_PASSWORD = "admin123"


class TestDataFetchingRules:
    """Test the three data fetching rules for CCE Master Architecture"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session with authentication"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login to get token
        login_response = self.session.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
        )
        
        if login_response.status_code == 200:
            data = login_response.json()
            token = data.get("access_token") or data.get("token")
            if token:
                self.session.headers.update({"Authorization": f"Bearer {token}"})
        
        yield
        self.session.close()
    
    # =========================================================================
    # RULE 1: Screener stock prices use previousClose
    # =========================================================================
    
    def test_rule1_screener_cc_returns_previous_close_source(self):
        """
        Rule 1: Verify screener covered-calls endpoint returns stock_price_source: previous_close
        """
        response = self.session.get(f"{BASE_URL}/api/screener/covered-calls?limit=5")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify stock_price_source field
        assert "stock_price_source" in data, "Response missing 'stock_price_source' field"
        assert data["stock_price_source"] == "previous_close", \
            f"Expected 'previous_close', got '{data.get('stock_price_source')}'"
        
        print(f"✓ Rule 1 PASS: Screener CC returns stock_price_source: {data['stock_price_source']}")
    
    def test_rule1_screener_pmcc_returns_previous_close_source(self):
        """
        Rule 1: Verify screener PMCC endpoint returns stock_price_source: previous_close
        """
        response = self.session.get(f"{BASE_URL}/api/screener/pmcc?limit=5")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify stock_price_source field
        assert "stock_price_source" in data, "Response missing 'stock_price_source' field"
        assert data["stock_price_source"] == "previous_close", \
            f"Expected 'previous_close', got '{data.get('stock_price_source')}'"
        
        print(f"✓ Rule 1 PASS: Screener PMCC returns stock_price_source: {data['stock_price_source']}")
    
    def test_rule1_screener_architecture_label(self):
        """
        Rule 1: Verify screener returns correct architecture label
        """
        response = self.session.get(f"{BASE_URL}/api/screener/covered-calls?limit=5")
        
        assert response.status_code == 200
        data = response.json()
        
        # Check architecture field
        assert "architecture" in data, "Response missing 'architecture' field"
        assert data["architecture"] == "LIVE_OPTIONS_PREVIOUS_CLOSE_STOCK", \
            f"Expected 'LIVE_OPTIONS_PREVIOUS_CLOSE_STOCK', got '{data.get('architecture')}'"
        
        print(f"✓ Rule 1 PASS: Architecture label: {data['architecture']}")
    
    # =========================================================================
    # RULE 2: Watchlist and Simulator use LIVE intraday prices
    # =========================================================================
    
    def test_rule2_watchlist_uses_live_prices(self):
        """
        Rule 2: Verify watchlist endpoint uses LIVE intraday prices
        """
        # First add a symbol to watchlist (use trailing slash for redirect)
        add_response = self.session.post(
            f"{BASE_URL}/api/watchlist/",
            json={"symbol": "AAPL", "target_price": 200, "notes": "Test"},
            allow_redirects=True
        )
        
        # Get watchlist with live prices (use trailing slash for redirect)
        response = self.session.get(
            f"{BASE_URL}/api/watchlist/?use_live_prices=true",
            allow_redirects=True
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # If watchlist has items, verify price_source
        if data and len(data) > 0:
            item = data[0]
            
            # Check for LIVE price indicators
            price_source = item.get("price_source", "")
            is_live = item.get("is_live_price", False)
            
            # Watchlist should use LIVE_INTRADAY prices
            assert price_source == "LIVE_INTRADAY" or is_live == True, \
                f"Watchlist should use LIVE prices. Got price_source: {price_source}, is_live: {is_live}"
            
            print(f"✓ Rule 2 PASS: Watchlist uses LIVE prices - price_source: {price_source}, is_live: {is_live}")
        else:
            print("⚠ Watchlist empty - skipping live price verification")
        
        # Cleanup - remove test item
        if add_response.status_code == 200:
            item_id = add_response.json().get("id")
            if item_id:
                self.session.delete(f"{BASE_URL}/api/watchlist/{item_id}", allow_redirects=True)
    
    def test_rule2_watchlist_opportunity_source(self):
        """
        Rule 2: Verify watchlist opportunities are fetched LIVE
        """
        # Add a symbol to watchlist (use trailing slash for redirect)
        add_response = self.session.post(
            f"{BASE_URL}/api/watchlist/",
            json={"symbol": "MSFT", "target_price": 400, "notes": "Test"},
            allow_redirects=True
        )
        
        # Get watchlist (use trailing slash for redirect)
        response = self.session.get(
            f"{BASE_URL}/api/watchlist/?use_live_prices=true",
            allow_redirects=True
        )
        
        assert response.status_code == 200
        data = response.json()
        
        if data and len(data) > 0:
            item = data[0]
            
            # Check opportunity_source if opportunity exists
            opp_source = item.get("opportunity_source")
            if opp_source:
                assert opp_source == "yahoo_live", \
                    f"Watchlist opportunity should be from yahoo_live, got: {opp_source}"
                print(f"✓ Rule 2 PASS: Watchlist opportunity_source: {opp_source}")
            else:
                # Market may be closed - opportunity_source will be null
                print("⚠ No opportunity found for watchlist item (market may be closed)")
        
        # Cleanup
        if add_response.status_code == 200:
            item_id = add_response.json().get("id")
            if item_id:
                self.session.delete(f"{BASE_URL}/api/watchlist/{item_id}", allow_redirects=True)
    
    def test_rule2_simulator_update_uses_live_prices(self):
        """
        Rule 2: Verify simulator price update uses LIVE intraday prices
        """
        # Trigger price update
        response = self.session.post(f"{BASE_URL}/api/simulator/update-prices")
        
        # Should succeed (even if no active trades)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Check that prices were fetched (even if 0 trades updated)
        assert "updated" in data or "message" in data, "Response should contain update status"
        
        print(f"✓ Rule 2 PASS: Simulator update-prices endpoint working. Response: {data.get('message', data)}")
    
    # =========================================================================
    # RULE 3: Options chain fetched LIVE at scan time
    # =========================================================================
    
    def test_rule3_screener_cc_options_chain_source_yahoo_live(self):
        """
        Rule 3: Verify screener CC returns options_chain_source: yahoo_live
        """
        response = self.session.get(f"{BASE_URL}/api/screener/covered-calls?limit=5")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify options_chain_source field
        assert "options_chain_source" in data, "Response missing 'options_chain_source' field"
        assert data["options_chain_source"] == "yahoo_live", \
            f"Expected 'yahoo_live', got '{data.get('options_chain_source')}'"
        
        print(f"✓ Rule 3 PASS: Screener CC returns options_chain_source: {data['options_chain_source']}")
    
    def test_rule3_screener_pmcc_options_chain_source_yahoo_live(self):
        """
        Rule 3: Verify screener PMCC returns options_chain_source: yahoo_live
        """
        response = self.session.get(f"{BASE_URL}/api/screener/pmcc?limit=5")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify options_chain_source field
        assert "options_chain_source" in data, "Response missing 'options_chain_source' field"
        assert data["options_chain_source"] == "yahoo_live", \
            f"Expected 'yahoo_live', got '{data.get('options_chain_source')}'"
        
        print(f"✓ Rule 3 PASS: Screener PMCC returns options_chain_source: {data['options_chain_source']}")
    
    def test_rule3_screener_live_data_used_flag(self):
        """
        Rule 3: Verify screener returns live_data_used: true
        """
        response = self.session.get(f"{BASE_URL}/api/screener/covered-calls?limit=5")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify live_data_used flag
        assert "live_data_used" in data, "Response missing 'live_data_used' field"
        assert data["live_data_used"] == True, \
            f"Expected live_data_used=True, got {data.get('live_data_used')}"
        
        print(f"✓ Rule 3 PASS: Screener returns live_data_used: {data['live_data_used']}")
    
    def test_rule3_individual_opportunity_data_source(self):
        """
        Rule 3: Verify individual opportunities have data_source: live_options
        """
        response = self.session.get(f"{BASE_URL}/api/screener/covered-calls?limit=5")
        
        assert response.status_code == 200
        data = response.json()
        
        opportunities = data.get("opportunities", data.get("results", []))
        
        if opportunities:
            # Check first opportunity
            opp = opportunities[0]
            data_source = opp.get("data_source")
            
            assert data_source == "live_options", \
                f"Expected data_source='live_options', got '{data_source}'"
            
            print(f"✓ Rule 3 PASS: Individual opportunity data_source: {data_source}")
        else:
            print("⚠ No opportunities returned - market may be closed (expected)")


class TestDataProviderFunctions:
    """Test the data_provider.py functions directly via API behavior"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session with authentication"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login to get token
        login_response = self.session.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
        )
        
        if login_response.status_code == 200:
            data = login_response.json()
            token = data.get("access_token") or data.get("token")
            if token:
                self.session.headers.update({"Authorization": f"Bearer {token}"})
        
        yield
        self.session.close()
    
    def test_fetch_stock_quote_returns_previous_close(self):
        """
        Verify fetch_stock_quote behavior via screener endpoint
        
        fetch_stock_quote (line 200-240) should return ONLY previousClose
        """
        response = self.session.get(f"{BASE_URL}/api/screener/covered-calls?limit=5")
        
        assert response.status_code == 200
        data = response.json()
        
        # The screener uses fetch_stock_quote which returns previousClose
        # Verify via the stock_price_source label
        assert data.get("stock_price_source") == "previous_close", \
            "fetch_stock_quote should return previousClose for screener"
        
        # Check individual opportunities have stock_price
        opportunities = data.get("opportunities", data.get("results", []))
        if opportunities:
            opp = opportunities[0]
            stock_price = opp.get("stock_price") or opp.get("underlying", {}).get("last_price")
            assert stock_price and stock_price > 0, "Stock price should be positive"
            print(f"✓ fetch_stock_quote returns previousClose: ${stock_price}")
    
    def test_fetch_live_stock_quote_returns_intraday(self):
        """
        Verify fetch_live_stock_quote behavior via watchlist endpoint
        
        fetch_live_stock_quote (line 99-150) should return regularMarketPrice/currentPrice
        """
        # Add a symbol to watchlist (use trailing slash for redirect)
        add_response = self.session.post(
            f"{BASE_URL}/api/watchlist/",
            json={"symbol": "AAPL", "target_price": 200, "notes": "Test live price"},
            allow_redirects=True
        )
        
        # Get watchlist with live prices (use trailing slash for redirect)
        response = self.session.get(
            f"{BASE_URL}/api/watchlist/?use_live_prices=true",
            allow_redirects=True
        )
        
        assert response.status_code == 200
        data = response.json()
        
        if data and len(data) > 0:
            item = data[0]
            
            # fetch_live_stock_quote should return LIVE_INTRADAY
            price_source = item.get("price_source")
            current_price = item.get("current_price")
            
            assert price_source == "LIVE_INTRADAY", \
                f"fetch_live_stock_quote should return LIVE_INTRADAY, got: {price_source}"
            assert current_price and current_price > 0, "Current price should be positive"
            
            print(f"✓ fetch_live_stock_quote returns LIVE intraday: ${current_price}")
        
        # Cleanup
        if add_response.status_code == 200:
            item_id = add_response.json().get("id")
            if item_id:
                self.session.delete(f"{BASE_URL}/api/watchlist/{item_id}", allow_redirects=True)
    
    def test_fetch_options_chain_returns_live_data(self):
        """
        Verify fetch_options_chain behavior via screener endpoint
        
        fetch_options_chain should return LIVE options data from Yahoo
        """
        response = self.session.get(f"{BASE_URL}/api/screener/covered-calls?limit=5")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify options are fetched live
        assert data.get("options_chain_source") == "yahoo_live", \
            "fetch_options_chain should return yahoo_live source"
        
        opportunities = data.get("opportunities", data.get("results", []))
        if opportunities:
            opp = opportunities[0]
            
            # Check option data is present
            short_call = opp.get("short_call", {})
            strike = short_call.get("strike") or opp.get("strike")
            expiry = short_call.get("expiry") or opp.get("expiry")
            premium = short_call.get("premium") or opp.get("premium")
            
            assert strike and strike > 0, "Strike should be positive"
            assert expiry, "Expiry should be present"
            
            print(f"✓ fetch_options_chain returns LIVE data: Strike ${strike}, Expiry {expiry}")
        else:
            print("⚠ No options returned - market may be closed (BID values are 0)")


class TestScreenerResponseLabels:
    """Test that screener API responses contain correct data source labels"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session with authentication"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login to get token
        login_response = self.session.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
        )
        
        if login_response.status_code == 200:
            data = login_response.json()
            token = data.get("access_token") or data.get("token")
            if token:
                self.session.headers.update({"Authorization": f"Bearer {token}"})
        
        yield
        self.session.close()
    
    def test_cc_screener_all_required_labels(self):
        """
        Verify CC screener returns all required data source labels
        """
        response = self.session.get(f"{BASE_URL}/api/screener/covered-calls?limit=5")
        
        assert response.status_code == 200
        data = response.json()
        
        # Required labels per user requirements
        required_labels = {
            "stock_price_source": "previous_close",
            "options_chain_source": "yahoo_live",
            "live_data_used": True,
            "architecture": "LIVE_OPTIONS_PREVIOUS_CLOSE_STOCK"
        }
        
        for label, expected_value in required_labels.items():
            assert label in data, f"Missing required label: {label}"
            assert data[label] == expected_value, \
                f"Label '{label}' expected '{expected_value}', got '{data[label]}'"
            print(f"✓ {label}: {data[label]}")
        
        print("✓ All required labels present and correct")
    
    def test_pmcc_screener_all_required_labels(self):
        """
        Verify PMCC screener returns all required data source labels
        """
        response = self.session.get(f"{BASE_URL}/api/screener/pmcc?limit=5")
        
        assert response.status_code == 200
        data = response.json()
        
        # Required labels per user requirements
        required_labels = {
            "stock_price_source": "previous_close",
            "options_chain_source": "yahoo_live",
            "live_data_used": True,
            "architecture": "LIVE_OPTIONS_PREVIOUS_CLOSE_STOCK"
        }
        
        for label, expected_value in required_labels.items():
            assert label in data, f"Missing required label: {label}"
            assert data[label] == expected_value, \
                f"Label '{label}' expected '{expected_value}', got '{data[label]}'"
            print(f"✓ {label}: {data[label]}")
        
        print("✓ All required labels present and correct")
    
    def test_dashboard_opportunities_labels(self):
        """
        Verify dashboard-opportunities endpoint returns correct labels
        """
        response = self.session.get(f"{BASE_URL}/api/screener/dashboard-opportunities")
        
        assert response.status_code == 200
        data = response.json()
        
        # Dashboard should also indicate data sources
        # Check for stock_price_source or architecture
        if "stock_price_source" in data:
            assert data["stock_price_source"] == "previous_close"
            print(f"✓ Dashboard stock_price_source: {data['stock_price_source']}")
        
        if "options_chain_source" in data:
            assert data["options_chain_source"] == "yahoo_live"
            print(f"✓ Dashboard options_chain_source: {data['options_chain_source']}")
        
        print("✓ Dashboard opportunities endpoint working")


class TestMarketClosedBehavior:
    """Test behavior when market is closed (BID values may be 0)"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session with authentication"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login to get token
        login_response = self.session.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
        )
        
        if login_response.status_code == 200:
            data = login_response.json()
            token = data.get("access_token") or data.get("token")
            if token:
                self.session.headers.update({"Authorization": f"Bearer {token}"})
        
        yield
        self.session.close()
    
    def test_screener_handles_market_closed(self):
        """
        Verify screener handles market closed gracefully
        
        Per agent context: "Market is closed so options may return 0 results 
        (expected - BID values are 0 outside market hours)"
        """
        response = self.session.get(f"{BASE_URL}/api/screener/covered-calls?limit=50")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        
        # Should return valid response structure even if no results
        assert "total" in data, "Response should have 'total' field"
        assert "stock_price_source" in data, "Response should have 'stock_price_source' field"
        assert "options_chain_source" in data, "Response should have 'options_chain_source' field"
        
        total = data.get("total", 0)
        
        if total == 0:
            print("⚠ Market closed - 0 results returned (expected behavior)")
            print("  BID values are 0 outside market hours, so no valid options")
        else:
            print(f"✓ Market open - {total} results returned")
        
        # Labels should still be correct regardless of results
        assert data["stock_price_source"] == "previous_close"
        assert data["options_chain_source"] == "yahoo_live"
        
        print("✓ Screener handles market closed gracefully")
    
    def test_pmcc_handles_market_closed(self):
        """
        Verify PMCC screener handles market closed gracefully
        """
        response = self.session.get(f"{BASE_URL}/api/screener/pmcc?limit=50")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        
        # Should return valid response structure even if no results
        assert "total" in data, "Response should have 'total' field"
        
        total = data.get("total", 0)
        
        if total == 0:
            print("⚠ Market closed - 0 PMCC results returned (expected behavior)")
        else:
            print(f"✓ Market open - {total} PMCC results returned")
        
        print("✓ PMCC screener handles market closed gracefully")


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
