"""
Test Data Consistency Bugs - Iteration 16
==========================================
Tests for the 4 reported data inconsistency issues:
1. Dashboard Top CC shows only monthlies instead of 50/50 weekly/monthly mix
2. CC Screener shows only monthlies
3. PMCC shows invalid Saturday expirations
4. Simulator and Watchlist are missing Greek data (IV, OI, Delta)

All tests verify:
- expiry_type field distribution (weekly vs monthly)
- Friday-only valid trading days
- IV, OI, Delta data presence
- Metadata: equity_price_date, options_snapshot_time
"""

import pytest
import requests
import os
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://covermax.preview.emergentagent.com')


class TestDataConsistencyBugs:
    """Test suite for data consistency bugs"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup: Login and get auth token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "admin@premiumhunter.com", "password": "admin123"}
        )
        assert response.status_code == 200, f"Login failed: {response.text}"
        self.token = response.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def _is_friday(self, date_str: str) -> bool:
        """Check if a date string is a Friday"""
        try:
            dt = datetime.strptime(date_str, '%Y-%m-%d')
            return dt.weekday() == 4  # Friday = 4
        except:
            return False
    
    # =========================================================================
    # TEST 1: Dashboard Opportunities - 50/50 Weekly/Monthly Mix
    # =========================================================================
    
    def test_dashboard_opportunities_returns_data(self):
        """Dashboard opportunities endpoint returns data"""
        response = requests.get(
            f"{BASE_URL}/api/screener/dashboard-opportunities",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "opportunities" in data
        assert data["total"] > 0
    
    def test_dashboard_opportunities_weekly_monthly_mix(self):
        """Dashboard opportunities should have ~5 weekly + ~5 monthly (50/50 mix)"""
        response = requests.get(
            f"{BASE_URL}/api/screener/dashboard-opportunities",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # Check weekly_count and monthly_count fields
        weekly_count = data.get("weekly_count", 0)
        monthly_count = data.get("monthly_count", 0)
        
        # Should have both weekly and monthly
        assert weekly_count > 0, "Dashboard should have weekly opportunities"
        assert monthly_count > 0, "Dashboard should have monthly opportunities"
        
        # Target is 5 weekly + 5 monthly
        assert weekly_count >= 3, f"Expected at least 3 weekly, got {weekly_count}"
        assert monthly_count >= 3, f"Expected at least 3 monthly, got {monthly_count}"
    
    def test_dashboard_opportunities_expiry_type_field(self):
        """Dashboard opportunities should have expiry_type field"""
        response = requests.get(
            f"{BASE_URL}/api/screener/dashboard-opportunities",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        for opp in data["opportunities"]:
            assert "expiry_type" in opp, f"Missing expiry_type for {opp.get('symbol')}"
            assert opp["expiry_type"] in ["weekly", "monthly"], f"Invalid expiry_type: {opp['expiry_type']}"
    
    def test_dashboard_opportunities_friday_expirations(self):
        """Dashboard opportunities should only have Friday expirations"""
        response = requests.get(
            f"{BASE_URL}/api/screener/dashboard-opportunities",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        for opp in data["opportunities"]:
            expiry = opp.get("expiry", "")
            assert self._is_friday(expiry), f"Expiry {expiry} is not a Friday for {opp.get('symbol')}"
    
    def test_dashboard_opportunities_metadata(self):
        """Dashboard opportunities should include metadata"""
        response = requests.get(
            f"{BASE_URL}/api/screener/dashboard-opportunities",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "metadata" in data
        metadata = data["metadata"]
        assert "equity_price_date" in metadata
        assert metadata["equity_price_date"] is not None
    
    # =========================================================================
    # TEST 2: CC Screener - Weekly/Monthly Mix with bypass_cache
    # =========================================================================
    
    def test_cc_screener_returns_data(self):
        """CC Screener endpoint returns data"""
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls?bypass_cache=true",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "opportunities" in data
        assert data["total"] > 0
    
    def test_cc_screener_weekly_monthly_mix(self):
        """CC Screener with bypass_cache should have mix of weekly AND monthly"""
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls?bypass_cache=true",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        weekly_count = data.get("weekly_count", 0)
        monthly_count = data.get("monthly_count", 0)
        
        # Should have both weekly and monthly
        assert weekly_count > 0, "CC Screener should have weekly opportunities"
        assert monthly_count > 0, "CC Screener should have monthly opportunities"
    
    def test_cc_screener_expiry_type_distribution(self):
        """CC Screener should have expiry_type field with proper distribution"""
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls?bypass_cache=true",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        weekly = [o for o in data["opportunities"] if o.get("expiry_type") == "weekly"]
        monthly = [o for o in data["opportunities"] if o.get("expiry_type") == "monthly"]
        
        assert len(weekly) > 0, "Should have weekly opportunities"
        assert len(monthly) > 0, "Should have monthly opportunities"
    
    def test_cc_screener_friday_expirations(self):
        """CC Screener should only have Friday expirations"""
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls?bypass_cache=true",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        for opp in data["opportunities"]:
            expiry = opp.get("expiry", "")
            assert self._is_friday(expiry), f"Expiry {expiry} is not a Friday for {opp.get('symbol')}"
    
    def test_cc_screener_iv_oi_data(self):
        """CC Screener should have IV and OI data"""
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls?bypass_cache=true",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        for opp in data["opportunities"][:10]:  # Check first 10
            assert "iv" in opp, f"Missing IV for {opp.get('symbol')}"
            assert opp["iv"] is not None and opp["iv"] > 0, f"IV should be > 0 for {opp.get('symbol')}"
            assert "open_interest" in opp, f"Missing open_interest for {opp.get('symbol')}"
    
    def test_cc_screener_metadata(self):
        """CC Screener should include metadata with equity_price_date and options_snapshot_time"""
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls?bypass_cache=true",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "metadata" in data
        metadata = data["metadata"]
        assert "equity_price_date" in metadata
        assert metadata["equity_price_date"] is not None
        # options_snapshot_time should be present when fetching live data
        assert "options_snapshot_time" in metadata
    
    # =========================================================================
    # TEST 3: PMCC - Valid Friday Expirations Only (No Saturdays)
    # =========================================================================
    
    def test_pmcc_returns_data(self):
        """PMCC endpoint returns data"""
        response = requests.get(
            f"{BASE_URL}/api/screener/pmcc?bypass_cache=true",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "opportunities" in data
        assert data["total"] > 0
    
    def test_pmcc_short_expiry_friday_only(self):
        """PMCC short_expiry should be valid Fridays only (no Saturdays)"""
        response = requests.get(
            f"{BASE_URL}/api/screener/pmcc?bypass_cache=true",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        for opp in data["opportunities"]:
            short_expiry = opp.get("short_expiry", "")
            assert self._is_friday(short_expiry), f"short_expiry {short_expiry} is not a Friday for {opp.get('symbol')}"
    
    def test_pmcc_leaps_expiry_friday_only(self):
        """PMCC leaps_expiry should be valid Fridays only (no Saturdays)"""
        response = requests.get(
            f"{BASE_URL}/api/screener/pmcc?bypass_cache=true",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        for opp in data["opportunities"]:
            leaps_expiry = opp.get("leaps_expiry", "")
            assert self._is_friday(leaps_expiry), f"leaps_expiry {leaps_expiry} is not a Friday for {opp.get('symbol')}"
    
    def test_pmcc_iv_oi_data(self):
        """PMCC should have IV and OI data for both LEAPS and short legs"""
        response = requests.get(
            f"{BASE_URL}/api/screener/pmcc?bypass_cache=true",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        for opp in data["opportunities"][:10]:  # Check first 10
            # LEAPS IV and OI
            assert "leaps_iv" in opp, f"Missing leaps_iv for {opp.get('symbol')}"
            assert opp["leaps_iv"] is not None and opp["leaps_iv"] > 0, f"leaps_iv should be > 0"
            assert "leaps_oi" in opp, f"Missing leaps_oi for {opp.get('symbol')}"
            
            # Short IV and OI
            assert "short_iv" in opp, f"Missing short_iv for {opp.get('symbol')}"
            assert opp["short_iv"] is not None and opp["short_iv"] > 0, f"short_iv should be > 0"
            assert "short_oi" in opp, f"Missing short_oi for {opp.get('symbol')}"
    
    def test_pmcc_metadata(self):
        """PMCC should include metadata"""
        response = requests.get(
            f"{BASE_URL}/api/screener/pmcc?bypass_cache=true",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "metadata" in data
        metadata = data["metadata"]
        assert "equity_price_date" in metadata
        assert metadata["equity_price_date"] is not None
    
    # =========================================================================
    # TEST 4: Watchlist - IV, OI, Delta in Opportunity Data
    # =========================================================================
    
    def test_watchlist_returns_data(self):
        """Watchlist endpoint returns data"""
        response = requests.get(
            f"{BASE_URL}/api/watchlist/",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_watchlist_opportunity_iv_oi_delta(self):
        """Watchlist opportunity should have IV, open_interest, delta"""
        response = requests.get(
            f"{BASE_URL}/api/watchlist/",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # Find items with opportunities
        items_with_opps = [item for item in data if item.get("opportunity")]
        
        if len(items_with_opps) == 0:
            pytest.skip("No watchlist items with opportunities to test")
        
        for item in items_with_opps[:5]:  # Check first 5
            opp = item["opportunity"]
            symbol = item.get("symbol", "unknown")
            
            # IV
            assert "iv" in opp, f"Missing IV for {symbol}"
            assert opp["iv"] is not None and opp["iv"] > 0, f"IV should be > 0 for {symbol}"
            
            # Open Interest
            assert "open_interest" in opp, f"Missing open_interest for {symbol}"
            
            # Delta
            assert "delta" in opp, f"Missing delta for {symbol}"
            assert opp["delta"] is not None, f"Delta should not be None for {symbol}"
    
    def test_watchlist_opportunity_iv_rank(self):
        """Watchlist opportunity should have IV Rank"""
        response = requests.get(
            f"{BASE_URL}/api/watchlist/",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        
        items_with_opps = [item for item in data if item.get("opportunity")]
        
        if len(items_with_opps) == 0:
            pytest.skip("No watchlist items with opportunities to test")
        
        for item in items_with_opps[:5]:
            opp = item["opportunity"]
            symbol = item.get("symbol", "unknown")
            
            assert "iv_rank" in opp, f"Missing iv_rank for {symbol}"


class TestMetadataConsistency:
    """Test metadata consistency across all endpoints"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup: Login and get auth token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "admin@premiumhunter.com", "password": "admin123"}
        )
        assert response.status_code == 200
        self.token = response.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_all_endpoints_have_equity_price_date(self):
        """All screener endpoints should include equity_price_date in metadata"""
        endpoints = [
            "/api/screener/dashboard-opportunities",
            "/api/screener/covered-calls?bypass_cache=true",
            "/api/screener/pmcc?bypass_cache=true"
        ]
        
        for endpoint in endpoints:
            response = requests.get(f"{BASE_URL}{endpoint}", headers=self.headers)
            assert response.status_code == 200, f"Failed for {endpoint}"
            data = response.json()
            
            assert "metadata" in data, f"Missing metadata for {endpoint}"
            assert "equity_price_date" in data["metadata"], f"Missing equity_price_date for {endpoint}"
            assert data["metadata"]["equity_price_date"] is not None, f"equity_price_date is None for {endpoint}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
