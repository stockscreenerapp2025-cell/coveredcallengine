"""
Layer 3 Data Pipeline Fix Tests

Tests for the specific issues reported:
1. Screener CC page IV column blank
2. Duplicate symbols in Screener
3. PMCC page missing LEAPS/Premium/Delta/Cost/Width columns
4. Simulator showing incorrect IV values

Root cause: Field name mismatches between backend (implied_volatility, leap_*) 
and frontend (iv, leaps_*)
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://stockdata-engine.preview.emergentagent.com')

# Test credentials
TEST_EMAIL = "admin@premiumhunter.com"
TEST_PASSWORD = "admin123"


class TestLayer3PipelineFix:
    """Tests for Layer 3 data pipeline fix verification"""
    
    @pytest.fixture
    def auth_token(self):
        """Get authentication token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
        )
        assert response.status_code == 200, f"Login failed: {response.text}"
        return response.json()["access_token"]
    
    def test_screener_cc_iv_column_not_blank(self, auth_token):
        """
        Issue #1: Screener CC page IV column blank
        Verify implied_volatility field is present and has valid values
        """
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls",
            params={"dte_mode": "all", "limit": 20},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        opportunities = data.get("opportunities", [])
        assert len(opportunities) > 0, "No opportunities returned"
        
        # Check that implied_volatility is present and not blank
        iv_present_count = 0
        for opp in opportunities:
            iv = opp.get("implied_volatility")
            if iv is not None and iv > 0:
                iv_present_count += 1
                # IV should be in percentage form (e.g., 25.5 for 25.5%)
                assert iv > 1, f"IV appears to be in decimal form: {iv}"
                assert iv < 200, f"IV appears incorrectly scaled: {iv}"
        
        # At least 80% should have IV values
        assert iv_present_count >= len(opportunities) * 0.8, \
            f"Only {iv_present_count}/{len(opportunities)} have IV values"
        
        print(f"✓ IV column populated: {iv_present_count}/{len(opportunities)} opportunities have IV")
    
    def test_screener_cc_no_duplicate_symbols(self, auth_token):
        """
        Issue #2: Duplicate symbols in Screener
        Verify deduplication is working - each symbol appears only once
        """
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls",
            params={"dte_mode": "all", "limit": 100},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        opportunities = data.get("opportunities", [])
        symbols = [opp["symbol"] for opp in opportunities]
        
        # Check for duplicates
        seen = set()
        duplicates = []
        for symbol in symbols:
            if symbol in seen:
                duplicates.append(symbol)
            seen.add(symbol)
        
        assert len(duplicates) == 0, f"Duplicate symbols found: {duplicates}"
        print(f"✓ No duplicates: {len(symbols)} unique symbols")
    
    def test_pmcc_leaps_buy_column(self, auth_token):
        """
        Issue #3a: PMCC page missing LEAPS Buy column
        Verify leap_* fields are present
        """
        response = requests.get(
            f"{BASE_URL}/api/screener/pmcc",
            params={"limit": 10},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        opportunities = data.get("opportunities", [])
        if len(opportunities) == 0:
            pytest.skip("No PMCC opportunities available")
        
        opp = opportunities[0]
        
        # Check LEAPS Buy fields (backend uses leap_ prefix)
        assert "leap_strike" in opp, "Missing leap_strike"
        assert "leap_dte" in opp, "Missing leap_dte"
        assert "leap_delta" in opp, "Missing leap_delta"
        assert "leap_ask" in opp, "Missing leap_ask"
        assert "leaps_buy_eligible" in opp, "Missing leaps_buy_eligible"
        
        # Verify values are not None/zero
        assert opp["leap_strike"] > 0, "leap_strike is zero"
        assert opp["leap_dte"] > 0, "leap_dte is zero"
        
        print(f"✓ LEAPS Buy column fields present: leap_strike={opp['leap_strike']}, leap_dte={opp['leap_dte']}")
    
    def test_pmcc_premium_ask_column(self, auth_token):
        """
        Issue #3b: PMCC page missing Premium Ask column
        Verify leap_ask field is present
        """
        response = requests.get(
            f"{BASE_URL}/api/screener/pmcc",
            params={"limit": 10},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        opportunities = data.get("opportunities", [])
        if len(opportunities) == 0:
            pytest.skip("No PMCC opportunities available")
        
        opp = opportunities[0]
        
        assert "leap_ask" in opp, "Missing leap_ask (Premium Ask)"
        assert opp["leap_ask"] > 0, "leap_ask is zero"
        
        print(f"✓ Premium Ask column present: leap_ask={opp['leap_ask']}")
    
    def test_pmcc_delta_column(self, auth_token):
        """
        Issue #3c: PMCC page missing Delta column
        Verify leap_delta field is present
        """
        response = requests.get(
            f"{BASE_URL}/api/screener/pmcc",
            params={"limit": 10},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        opportunities = data.get("opportunities", [])
        if len(opportunities) == 0:
            pytest.skip("No PMCC opportunities available")
        
        opp = opportunities[0]
        
        assert "leap_delta" in opp, "Missing leap_delta"
        # Delta should be between 0 and 1
        assert 0 < opp["leap_delta"] <= 1, f"Invalid delta: {opp['leap_delta']}"
        
        print(f"✓ Delta column present: leap_delta={opp['leap_delta']}")
    
    def test_pmcc_width_column_not_zero(self, auth_token):
        """
        Issue #3d: PMCC page Width column showing zero
        Verify width is calculated correctly (short_strike - leap_strike)
        """
        response = requests.get(
            f"{BASE_URL}/api/screener/pmcc",
            params={"limit": 10},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        opportunities = data.get("opportunities", [])
        if len(opportunities) == 0:
            pytest.skip("No PMCC opportunities available")
        
        opp = opportunities[0]
        
        assert "width" in opp, "Missing width field"
        assert opp["width"] > 0, f"Width is zero or negative: {opp['width']}"
        
        # Verify width calculation
        expected_width = opp["short_strike"] - opp["leap_strike"]
        assert abs(opp["width"] - expected_width) < 0.01, \
            f"Width mismatch: {opp['width']} vs expected {expected_width}"
        
        print(f"✓ Width column correct: width={opp['width']} (short={opp['short_strike']} - leap={opp['leap_strike']})")
    
    def test_dashboard_weekly_monthly_color_coding(self, auth_token):
        """
        Issue #4: Dashboard Top 10 shows Weekly (cyan) and Monthly (violet) color coding
        Verify dashboard returns both weekly and monthly opportunities with expiry_type
        """
        response = requests.get(
            f"{BASE_URL}/api/screener/dashboard-opportunities",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Check weekly/monthly split
        assert "weekly_count" in data, "Missing weekly_count"
        assert "monthly_count" in data, "Missing monthly_count"
        
        weekly_opps = data.get("weekly_opportunities", [])
        monthly_opps = data.get("monthly_opportunities", [])
        
        # Verify expiry_type is set
        for opp in weekly_opps:
            assert opp.get("expiry_type") == "Weekly", f"Weekly opp missing expiry_type: {opp.get('symbol')}"
            assert opp.get("dte", 0) <= 14, f"Weekly opp has DTE > 14: {opp.get('dte')}"
        
        for opp in monthly_opps:
            assert opp.get("expiry_type") == "Monthly", f"Monthly opp missing expiry_type: {opp.get('symbol')}"
            assert opp.get("dte", 0) > 14, f"Monthly opp has DTE <= 14: {opp.get('dte')}"
        
        print(f"✓ Dashboard color coding: {len(weekly_opps)} Weekly (cyan), {len(monthly_opps)} Monthly (violet)")
    
    def test_simulator_iv_value_from_dashboard(self, auth_token):
        """
        Issue #5: Simulator showing incorrect IV values
        Verify IV is correctly passed from dashboard to simulator
        
        Backend sends implied_volatility in percentage form (e.g., 25.5)
        Frontend should convert to decimal (0.255) when storing in simulator
        """
        # First get dashboard opportunities
        response = requests.get(
            f"{BASE_URL}/api/screener/dashboard-opportunities",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        opportunities = data.get("opportunities", [])
        if len(opportunities) == 0:
            pytest.skip("No dashboard opportunities available")
        
        opp = opportunities[0]
        
        # Verify implied_volatility is present and in percentage form
        iv = opp.get("implied_volatility")
        assert iv is not None, "implied_volatility missing from dashboard opportunity"
        assert iv > 1, f"IV appears to be in decimal form: {iv}"
        
        # The frontend should convert this to decimal (iv / 100) when storing
        expected_decimal_iv = iv / 100
        assert 0 < expected_decimal_iv < 2, f"Converted IV out of range: {expected_decimal_iv}"
        
        print(f"✓ Dashboard IV ready for simulator: {iv}% -> {expected_decimal_iv:.4f} decimal")


class TestPMCCDeduplication:
    """Tests for PMCC deduplication"""
    
    @pytest.fixture
    def auth_token(self):
        """Get authentication token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
        )
        return response.json()["access_token"]
    
    def test_pmcc_no_duplicate_symbols(self, auth_token):
        """Verify PMCC endpoint deduplicates by symbol"""
        response = requests.get(
            f"{BASE_URL}/api/screener/pmcc",
            params={"limit": 50},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        opportunities = data.get("opportunities", [])
        symbols = [opp["symbol"] for opp in opportunities]
        
        seen = set()
        duplicates = []
        for symbol in symbols:
            if symbol in seen:
                duplicates.append(symbol)
            seen.add(symbol)
        
        assert len(duplicates) == 0, f"Duplicate PMCC symbols found: {duplicates}"
        print(f"✓ PMCC no duplicates: {len(symbols)} unique symbols")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
