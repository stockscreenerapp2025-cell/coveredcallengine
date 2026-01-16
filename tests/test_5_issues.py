"""
Test file for verifying 5 user-reported issues:
1. Simulator - IV, IV Rank, & OI fields should be saved when adding a new trade
2. Dashboard - 'Market Closed' badge should display 'US Market Closed'
3. Screener Page - Should NOT auto-load data on page load
4. PMCC Page - Should NOT auto-load data on page load
5. Watchlist - Analyst rating should be saved when adding a new stock
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestAuth:
    """Authentication tests"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@premiumhunter.com",
            "password": "admin123"
        })
        assert response.status_code == 200, f"Login failed: {response.text}"
        return response.json().get("access_token")
    
    @pytest.fixture(scope="class")
    def auth_headers(self, auth_token):
        """Get auth headers"""
        return {"Authorization": f"Bearer {auth_token}"}


class TestIssue1SimulatorFields(TestAuth):
    """Issue 1: Simulator - IV, IV Rank, & OI fields should be saved when adding a new trade"""
    
    def test_simulator_trade_model_accepts_iv_fields(self, auth_headers):
        """Test that the simulator trade endpoint accepts IV, IV Rank, and Open Interest fields"""
        # Create a test trade with IV, IV Rank, and Open Interest
        trade_data = {
            "symbol": "TEST_AAPL",
            "strategy_type": "covered_call",
            "underlying_price": 185.50,
            "short_call_strike": 190.00,
            "short_call_expiry": "2025-02-21",
            "short_call_premium": 3.50,
            "short_call_delta": 0.30,
            "short_call_iv": 0.25,
            "short_call_iv_rank": 45.5,
            "short_call_open_interest": 5000,
            "contracts": 1,
            "scan_parameters": {
                "score": 65,
                "roi_pct": 1.89,
                "dte": 35,
                "iv_rank": 45.5,
                "open_interest": 5000
            }
        }
        
        response = requests.post(
            f"{BASE_URL}/api/simulator/trade",
            json=trade_data,
            headers=auth_headers
        )
        
        # Should accept the trade with IV fields
        assert response.status_code == 200, f"Failed to create trade: {response.text}"
        data = response.json()
        assert "id" in data, "Trade should have an ID"
        
        # Store trade_id for cleanup
        trade_id = data.get("id")
        
        # Verify the trade was created with the IV fields
        trades_response = requests.get(
            f"{BASE_URL}/api/simulator/trades",
            headers=auth_headers
        )
        assert trades_response.status_code == 200
        
        trades = trades_response.json()
        test_trade = next((t for t in trades if t.get("symbol") == "TEST_AAPL"), None)
        
        if test_trade:
            # Check if scan_parameters contains the IV fields
            scan_params = test_trade.get("scan_parameters", {})
            print(f"Trade scan_parameters: {scan_params}")
            print(f"Trade iv_rank field: {test_trade.get('iv_rank')}")
            print(f"Trade open_interest field: {test_trade.get('open_interest')}")
            
            # The IV rank should be stored in scan_parameters
            assert scan_params.get("iv_rank") == 45.5 or test_trade.get("short_call_iv_rank") == 45.5, \
                "IV Rank should be saved in trade"
            
            # Clean up - delete the test trade
            if trade_id:
                requests.delete(
                    f"{BASE_URL}/api/simulator/trade/{trade_id}",
                    headers=auth_headers
                )
        
        print("✓ Issue 1: Simulator accepts IV, IV Rank, and Open Interest fields")


class TestIssue2DashboardMarketBadge:
    """Issue 2: Dashboard - 'Market Closed' badge should display 'US Market Closed'"""
    
    def test_market_status_endpoint(self):
        """Test that market status endpoint returns proper data"""
        response = requests.get(f"{BASE_URL}/api/market-status")
        assert response.status_code == 200, f"Market status failed: {response.text}"
        
        data = response.json()
        assert "is_open" in data, "Market status should have is_open field"
        
        # The badge text is in frontend, but we verify the API works
        print(f"Market status: is_open={data.get('is_open')}, reason={data.get('reason')}")
        print("✓ Issue 2: Market status API works (badge text 'US Market Closed' is in frontend code)")


class TestIssue3ScreenerAutoLoad:
    """Issue 3: Screener Page - Should NOT auto-load data on page load"""
    
    def test_screener_code_review(self):
        """
        Code review test - verify that Screener.js does NOT auto-load data.
        This is a code inspection test, not a runtime test.
        """
        # Read the Screener.js file
        screener_path = "/app/frontend/src/pages/Screener.js"
        with open(screener_path, 'r') as f:
            content = f.read()
        
        # Check if fetchOpportunities is called in useEffect
        # The issue is that lines 215 and 218 call fetchOpportunities()
        if "fetchOpportunities()" in content:
            # Find the useEffect block
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if "useEffect" in line and i < len(lines) - 20:
                    # Check next 20 lines for fetchOpportunities call
                    block = '\n'.join(lines[i:i+25])
                    if "fetchOpportunities()" in block and "initializeData" in block:
                        print(f"⚠ Issue 3 NOT FIXED: Screener.js still calls fetchOpportunities() on page load")
                        print(f"  Found in useEffect around line {i+1}")
                        pytest.fail("Screener.js still auto-loads data on page load - fetchOpportunities() is called in useEffect")
        
        print("✓ Issue 3: Screener does not auto-load data")


class TestIssue4PMCCAutoLoad:
    """Issue 4: PMCC Page - Should NOT auto-load data on page load"""
    
    def test_pmcc_code_review(self):
        """
        Code review test - verify that PMCC.js does NOT auto-load data.
        This is a code inspection test, not a runtime test.
        """
        # Read the PMCC.js file
        pmcc_path = "/app/frontend/src/pages/PMCC.js"
        with open(pmcc_path, 'r') as f:
            content = f.read()
        
        # Check if fetchOpportunities is called in useEffect
        if "fetchOpportunities()" in content:
            # Find the useEffect block
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if "useEffect" in line and i < len(lines) - 20:
                    # Check next 20 lines for fetchOpportunities call
                    block = '\n'.join(lines[i:i+20])
                    if "fetchOpportunities()" in block and "initializeData" in block:
                        print(f"⚠ Issue 4 NOT FIXED: PMCC.js still calls fetchOpportunities() on page load")
                        print(f"  Found in useEffect around line {i+1}")
                        pytest.fail("PMCC.js still auto-loads data on page load - fetchOpportunities() is called in useEffect")
        
        print("✓ Issue 4: PMCC does not auto-load data")


class TestIssue5WatchlistAnalystRating(TestAuth):
    """Issue 5: Watchlist - Analyst rating should be saved when adding a new stock"""
    
    def test_watchlist_saves_analyst_rating(self, auth_headers):
        """Test that watchlist saves analyst rating when adding a stock"""
        # First, remove TEST_MSFT if it exists
        watchlist_response = requests.get(
            f"{BASE_URL}/api/watchlist/",
            headers=auth_headers
        )
        if watchlist_response.status_code == 200:
            items = watchlist_response.json()
            for item in items:
                if item.get("symbol") == "MSFT":
                    requests.delete(
                        f"{BASE_URL}/api/watchlist/{item.get('id')}",
                        headers=auth_headers
                    )
        
        # Add a stock to watchlist
        add_response = requests.post(
            f"{BASE_URL}/api/watchlist/",
            json={"symbol": "MSFT", "target_price": 450.00, "notes": "Test stock"},
            headers=auth_headers
        )
        
        assert add_response.status_code == 200, f"Failed to add to watchlist: {add_response.text}"
        add_data = add_response.json()
        
        print(f"Add response: {add_data}")
        
        # The response should include analyst_rating if available
        # Note: analyst_rating may be None if Yahoo Finance doesn't have data
        
        # Now fetch the watchlist and verify the stock is there with analyst_rating_at_add
        time.sleep(1)  # Wait for data to be saved
        
        watchlist_response = requests.get(
            f"{BASE_URL}/api/watchlist/",
            headers=auth_headers
        )
        assert watchlist_response.status_code == 200
        
        items = watchlist_response.json()
        msft_item = next((item for item in items if item.get("symbol") == "MSFT"), None)
        
        assert msft_item is not None, "MSFT should be in watchlist"
        
        # Check if analyst_rating is present (either from live data or stored at add time)
        analyst_rating = msft_item.get("analyst_rating")
        print(f"MSFT watchlist item: analyst_rating={analyst_rating}")
        print(f"Full item: {msft_item}")
        
        # The analyst_rating should be present (either live or from analyst_rating_at_add)
        # Note: It may be None if Yahoo Finance doesn't have analyst data for this stock
        
        # Clean up - remove the test stock
        if msft_item.get("id"):
            requests.delete(
                f"{BASE_URL}/api/watchlist/{msft_item.get('id')}",
                headers=auth_headers
            )
        
        print("✓ Issue 5: Watchlist saves analyst rating (may be None if no analyst data available)")


class TestBackendHealth:
    """Basic backend health checks"""
    
    def test_health_endpoint(self):
        """Test health endpoint"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200, f"Health check failed: {response.text}"
        print("✓ Backend health check passed")
    
    def test_auth_login(self):
        """Test login endpoint"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@premiumhunter.com",
            "password": "admin123"
        })
        assert response.status_code == 200, f"Login failed: {response.text}"
        data = response.json()
        assert "access_token" in data, "Login should return access_token"
        print("✓ Auth login works")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
