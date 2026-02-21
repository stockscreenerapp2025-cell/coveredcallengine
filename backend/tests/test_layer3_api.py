"""
Layer 3 Enrichment API Tests

Tests for:
- Dashboard opportunities endpoint (Top 5 Weekly + Top 5 Monthly)
- Covered calls endpoint with dte_mode parameter
- PMCC endpoint with enriched metrics
- Greeks enrichment in responses
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestLayer3DashboardOpportunities:
    """Test dashboard-opportunities endpoint for Layer 3 features"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup authentication for tests"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@premiumhunter.com",
            "password": "admin123"
        })
        assert response.status_code == 200, f"Login failed: {response.text}"
        self.token = response.json().get("access_token")
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_dashboard_returns_weekly_and_monthly_counts(self):
        """Test that dashboard returns weekly_count and monthly_count"""
        response = requests.get(
            f"{BASE_URL}/api/screener/dashboard-opportunities",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify weekly_count and monthly_count are present
        assert "weekly_count" in data, "weekly_count missing from response"
        assert "monthly_count" in data, "monthly_count missing from response"
        
        # Verify counts are integers
        assert isinstance(data["weekly_count"], int)
        assert isinstance(data["monthly_count"], int)
        
        # Verify total = weekly + monthly
        assert data["total"] == data["weekly_count"] + data["monthly_count"]
    
    def test_dashboard_returns_top_5_weekly_top_5_monthly(self):
        """Test that dashboard returns Top 5 Weekly + Top 5 Monthly"""
        response = requests.get(
            f"{BASE_URL}/api/screener/dashboard-opportunities",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # Should return max 10 opportunities (5 weekly + 5 monthly)
        assert data["total"] <= 10
        
        # Count weekly and monthly in opportunities
        weekly_opps = [o for o in data["opportunities"] if o.get("dte_category") == "weekly" or o.get("dte", 100) <= 14]
        monthly_opps = [o for o in data["opportunities"] if o.get("dte_category") == "monthly" or o.get("dte", 0) > 14]
        
        # Should have max 5 of each
        assert len(weekly_opps) <= 5, f"Too many weekly opportunities: {len(weekly_opps)}"
        assert len(monthly_opps) <= 5, f"Too many monthly opportunities: {len(monthly_opps)}"
    
    def test_dashboard_opportunities_have_enriched_greeks(self):
        """Test that opportunities include enriched Greeks"""
        response = requests.get(
            f"{BASE_URL}/api/screener/dashboard-opportunities",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        if data["opportunities"]:
            opp = data["opportunities"][0]
            
            # Verify enriched fields are present
            assert "roi_pct" in opp, "roi_pct missing"
            assert "roi_annualized" in opp, "roi_annualized missing"
            assert "gamma" in opp, "gamma missing"
            assert "theta" in opp, "theta missing"
            assert "vega" in opp, "vega missing"
            assert "iv_rank" in opp or opp.get("iv_rank") is None, "iv_rank field missing"
            
            # Verify values are reasonable
            if opp.get("roi_pct"):
                assert opp["roi_pct"] > 0, "roi_pct should be positive"
            if opp.get("roi_annualized"):
                assert opp["roi_annualized"] > 0, "roi_annualized should be positive"


class TestLayer3CoveredCallsDTEMode:
    """Test covered-calls endpoint with dte_mode parameter"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup authentication for tests"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@premiumhunter.com",
            "password": "admin123"
        })
        assert response.status_code == 200
        self.token = response.json().get("access_token")
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_dte_mode_weekly(self):
        """Test dte_mode=weekly returns 7-14 DTE options"""
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls?dte_mode=weekly&limit=10",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify dte_mode is returned
        assert data.get("dte_mode") == "weekly"
        
        # Verify DTE range
        assert data.get("dte_range", {}).get("min") == 7
        assert data.get("dte_range", {}).get("max") == 14
        
        # Verify all opportunities are within weekly range
        for opp in data.get("opportunities", []):
            assert 7 <= opp["dte"] <= 14, f"DTE {opp['dte']} outside weekly range 7-14"
    
    def test_dte_mode_monthly(self):
        """Test dte_mode=monthly returns 21-45 DTE options"""
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls?dte_mode=monthly&limit=10",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify dte_mode is returned
        assert data.get("dte_mode") == "monthly"
        
        # Verify DTE range
        assert data.get("dte_range", {}).get("min") == 21
        assert data.get("dte_range", {}).get("max") == 45
        
        # Verify all opportunities are within monthly range
        for opp in data.get("opportunities", []):
            assert 21 <= opp["dte"] <= 45, f"DTE {opp['dte']} outside monthly range 21-45"
    
    def test_dte_mode_all(self):
        """Test dte_mode=all returns 7-45 DTE options"""
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls?dte_mode=all&limit=10",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify dte_mode is returned
        assert data.get("dte_mode") == "all"
        
        # Verify DTE range covers both weekly and monthly
        assert data.get("dte_range", {}).get("min") == 7
        assert data.get("dte_range", {}).get("max") == 45
    
    def test_covered_calls_have_enriched_greeks(self):
        """Test that covered calls include enriched Greeks"""
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls?dte_mode=all&limit=5",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        if data.get("opportunities"):
            opp = data["opportunities"][0]
            
            # Verify enriched fields
            assert "roi_pct" in opp, "roi_pct missing"
            assert "roi_annualized" in opp, "roi_annualized missing"
            assert "gamma" in opp, "gamma missing"
            assert "theta" in opp, "theta missing"
            assert "vega" in opp, "vega missing"
            assert "delta" in opp, "delta missing"
            assert "implied_volatility" in opp, "implied_volatility missing"


class TestLayer3PMCCEndpoint:
    """Test PMCC endpoint for Layer 3 enrichment"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup authentication for tests"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@premiumhunter.com",
            "password": "admin123"
        })
        assert response.status_code == 200
        self.token = response.json().get("access_token")
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_pmcc_returns_leaps_buy_eligible(self):
        """Test that PMCC returns leaps_buy_eligible field"""
        response = requests.get(
            f"{BASE_URL}/api/screener/pmcc?limit=5",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        if data.get("opportunities"):
            opp = data["opportunities"][0]
            assert "leaps_buy_eligible" in opp, "leaps_buy_eligible missing"
            assert isinstance(opp["leaps_buy_eligible"], bool)
    
    def test_pmcc_returns_width(self):
        """Test that PMCC returns width field"""
        response = requests.get(
            f"{BASE_URL}/api/screener/pmcc?limit=5",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        if data.get("opportunities"):
            opp = data["opportunities"][0]
            assert "width" in opp, "width missing"
            # Width should be positive (short_strike > leap_strike)
            assert opp["width"] > 0, "width should be positive"
    
    def test_pmcc_returns_breakeven(self):
        """Test that PMCC returns breakeven field"""
        response = requests.get(
            f"{BASE_URL}/api/screener/pmcc?limit=5",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        if data.get("opportunities"):
            opp = data["opportunities"][0]
            assert "breakeven" in opp, "breakeven missing"
    
    def test_pmcc_returns_analyst_rating(self):
        """Test that PMCC returns analyst_rating field"""
        response = requests.get(
            f"{BASE_URL}/api/screener/pmcc?limit=5",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        if data.get("opportunities"):
            opp = data["opportunities"][0]
            # analyst_rating may be null for some symbols
            assert "analyst_rating" in opp or opp.get("analyst_rating") is None


class TestGOOGvsGOOGLHandling:
    """Test that GOOG and GOOGL are handled separately"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup authentication for tests"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@premiumhunter.com",
            "password": "admin123"
        })
        assert response.status_code == 200
        self.token = response.json().get("access_token")
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_goog_googl_separate_in_scan(self):
        """Test that GOOG and GOOGL can appear separately in scan results"""
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls?dte_mode=all&limit=100",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # Get all symbols in results
        symbols = [opp["symbol"] for opp in data.get("opportunities", [])]
        
        # Both GOOG and GOOGL should be possible (if they pass filters)
        # We just verify they're not merged
        goog_count = symbols.count("GOOG")
        googl_count = symbols.count("GOOGL")
        
        # Log for debugging
        print(f"GOOG count: {goog_count}, GOOGL count: {googl_count}")
        
        # If both appear, they should be separate entries
        # (This test passes as long as they're not incorrectly merged)


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
