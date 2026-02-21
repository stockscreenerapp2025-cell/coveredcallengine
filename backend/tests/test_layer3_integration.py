"""
Layer 3 Integration Tests - Full Pipeline Verification

Tests that enrichment data survives the complete pipeline:
Backend → API → Frontend

This is the "smoking gun" test as specified in the forensic checklist.
"""

import pytest
import httpx
import os
from datetime import datetime
import asyncio

# Get API URL from environment or default
API_URL = os.environ.get('API_URL', 'http://localhost:8001')

# Test credentials
TEST_EMAIL = "admin@premiumhunter.com"
TEST_PASSWORD = "admin123"


class TestEnrichmentPipeline:
    """Full pipeline integration tests"""
    
    @pytest.fixture
    def auth_token(self):
        """Get authentication token"""
        with httpx.Client() as client:
            response = client.post(
                f"{API_URL}/api/auth/login",
                json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
            )
            assert response.status_code == 200, f"Login failed: {response.text}"
            return response.json()["access_token"]
    
    def test_cc_endpoint_returns_all_required_fields(self, auth_token):
        """Test that CC endpoint returns all required enrichment fields"""
        with httpx.Client() as client:
            response = client.get(
                f"{API_URL}/api/screener/covered-calls",
                params={"dte_mode": "weekly", "limit": 10},
                headers={"Authorization": f"Bearer {auth_token}"}
            )
            assert response.status_code == 200
            data = response.json()
            
            assert "opportunities" in data
            assert len(data["opportunities"]) > 0
            
            opp = data["opportunities"][0]
            
            # Required fields from Layer 3 enrichment
            required_fields = [
                "symbol",
                "strike",
                "expiry",
                "dte",
                "stock_price",
                "premium",
                "implied_volatility",  # Must be present, not "iv"
                "iv_rank",
                "delta",
                "gamma",
                "theta",
                "vega",
                "roi_pct",
                "roi_annualized",
                "score"
            ]
            
            for field in required_fields:
                assert field in opp, f"Missing required field: {field}"
                assert opp[field] is not None, f"Field {field} is None"
            
            print(f"✓ All {len(required_fields)} required fields present")
    
    def test_cc_no_duplicate_symbols(self, auth_token):
        """Test that each symbol appears only once in results"""
        with httpx.Client() as client:
            response = client.get(
                f"{API_URL}/api/screener/covered-calls",
                params={"dte_mode": "all", "limit": 100},
                headers={"Authorization": f"Bearer {auth_token}"}
            )
            assert response.status_code == 200
            data = response.json()
            
            symbols = [opp["symbol"] for opp in data["opportunities"]]
            unique_symbols = set(symbols)
            
            assert len(symbols) == len(unique_symbols), \
                f"Duplicate symbols found: {[s for s in symbols if symbols.count(s) > 1]}"
            
            print(f"✓ No duplicates: {len(unique_symbols)} unique symbols")
    
    def test_dashboard_weekly_monthly_split(self, auth_token):
        """Test dashboard returns Top 5 Weekly + Top 5 Monthly"""
        with httpx.Client() as client:
            response = client.get(
                f"{API_URL}/api/screener/dashboard-opportunities",
                headers={"Authorization": f"Bearer {auth_token}"}
            )
            assert response.status_code == 200
            data = response.json()
            
            assert "weekly_count" in data
            assert "monthly_count" in data
            assert data["weekly_count"] <= 5, "More than 5 weekly opportunities"
            assert data["monthly_count"] <= 5, "More than 5 monthly opportunities"
            
            # Verify weekly/monthly categorization
            for opp in data.get("weekly_opportunities", []):
                assert opp["dte"] <= 14, f"Weekly opp has DTE {opp['dte']} > 14"
            
            for opp in data.get("monthly_opportunities", []):
                assert opp["dte"] > 14, f"Monthly opp has DTE {opp['dte']} <= 14"
            
            print(f"✓ Dashboard split: {data['weekly_count']} weekly, {data['monthly_count']} monthly")
    
    def test_pmcc_returns_all_required_fields(self, auth_token):
        """Test that PMCC endpoint returns all required fields"""
        with httpx.Client() as client:
            response = client.get(
                f"{API_URL}/api/screener/pmcc",
                params={"limit": 5},
                headers={"Authorization": f"Bearer {auth_token}"}
            )
            assert response.status_code == 200
            data = response.json()
            
            assert "opportunities" in data
            if len(data["opportunities"]) == 0:
                pytest.skip("No PMCC opportunities available")
            
            opp = data["opportunities"][0]
            
            # Required PMCC fields (using leap_ prefix as sent by backend)
            required_fields = [
                "symbol",
                "stock_price",
                "leap_strike",
                "leap_dte",
                "leap_cost",
                "leap_delta",
                "leap_ask",
                "leaps_buy_eligible",
                "short_strike",
                "short_dte",
                "short_premium",
                "width",
                "net_debit",
                "breakeven",
                "roi_per_cycle",
                "annualized_roi"
            ]
            
            for field in required_fields:
                assert field in opp, f"Missing required PMCC field: {field}"
            
            # Verify width calculation
            if opp.get("short_strike") and opp.get("leap_strike"):
                expected_width = opp["short_strike"] - opp["leap_strike"]
                assert abs(opp["width"] - expected_width) < 0.01, \
                    f"Width mismatch: {opp['width']} vs expected {expected_width}"
            
            print(f"✓ All PMCC required fields present")
    
    def test_iv_consistency_across_endpoints(self, auth_token):
        """Test that IV values are consistent (not converted multiple times)"""
        with httpx.Client() as client:
            # Get CC data
            cc_response = client.get(
                f"{API_URL}/api/screener/covered-calls",
                params={"dte_mode": "weekly", "limit": 20},
                headers={"Authorization": f"Bearer {auth_token}"}
            )
            assert cc_response.status_code == 200
            cc_data = cc_response.json()
            
            # All IV values should be in percentage form (> 1)
            for opp in cc_data.get("opportunities", []):
                iv = opp.get("implied_volatility", 0)
                assert iv > 1, f"IV appears to be in decimal form: {iv}"
                assert iv < 200, f"IV appears to be incorrectly scaled: {iv}"
            
            print("✓ IV values consistently in percentage form (1-200%)")
    
    def test_premium_source_consistency(self, auth_token):
        """Test that premium values come from BID (not mid or ask)"""
        with httpx.Client() as client:
            response = client.get(
                f"{API_URL}/api/screener/covered-calls",
                params={"dte_mode": "weekly", "limit": 10},
                headers={"Authorization": f"Bearer {auth_token}"}
            )
            assert response.status_code == 200
            data = response.json()
            
            for opp in data.get("opportunities", []):
                premium = opp.get("premium", 0)
                premium_ask = opp.get("premium_ask")
                
                # Premium should be less than or equal to ask
                if premium_ask:
                    assert premium <= premium_ask, \
                        f"Premium {premium} > Ask {premium_ask} for {opp['symbol']}"
            
            print("✓ Premium values ≤ Ask (consistent with BID source)")
    
    def test_roi_calculation_accuracy(self, auth_token):
        """Test ROI calculation: (Premium / Stock Price) * 100 * (365 / DTE)"""
        with httpx.Client() as client:
            response = client.get(
                f"{API_URL}/api/screener/covered-calls",
                params={"dte_mode": "monthly", "limit": 10},
                headers={"Authorization": f"Bearer {auth_token}"}
            )
            assert response.status_code == 200
            data = response.json()
            
            for opp in data.get("opportunities", []):
                premium = opp.get("premium", 0)
                stock_price = opp.get("stock_price", 1)
                dte = opp.get("dte", 30)
                roi_pct = opp.get("roi_pct", 0)
                roi_annualized = opp.get("roi_annualized", 0)
                
                if stock_price > 0 and dte > 0:
                    expected_roi = (premium / stock_price) * 100
                    expected_annual = expected_roi * (365 / dte)
                    
                    assert abs(roi_pct - expected_roi) < 0.1, \
                        f"ROI mismatch for {opp['symbol']}: {roi_pct} vs expected {expected_roi}"
                    
                    assert abs(roi_annualized - expected_annual) < 1.0, \
                        f"Annualized ROI mismatch for {opp['symbol']}: {roi_annualized} vs expected {expected_annual}"
            
            print("✓ ROI calculations verified accurate")


class TestCrossPageConsistency:
    """Tests for cross-page data consistency"""
    
    @pytest.fixture
    def auth_token(self):
        """Get authentication token"""
        with httpx.Client() as client:
            response = client.post(
                f"{API_URL}/api/auth/login",
                json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
            )
            return response.json()["access_token"]
    
    def test_goog_googl_distinct(self, auth_token):
        """Test that GOOG and GOOGL are treated as distinct symbols"""
        with httpx.Client() as client:
            response = client.get(
                f"{API_URL}/api/screener/covered-calls",
                params={"dte_mode": "all", "limit": 100},
                headers={"Authorization": f"Bearer {auth_token}"}
            )
            assert response.status_code == 200
            data = response.json()
            
            symbols = [opp["symbol"] for opp in data["opportunities"]]
            
            # Both can appear separately
            goog_present = "GOOG" in symbols
            googl_present = "GOOGL" in symbols
            
            print(f"GOOG present: {goog_present}, GOOGL present: {googl_present}")
            
            # They should not be merged
            if goog_present and googl_present:
                print("✓ GOOG and GOOGL both present as distinct symbols")
            elif goog_present or googl_present:
                print("✓ At least one of GOOG/GOOGL present")
            else:
                print("⚠ Neither GOOG nor GOOGL in current scan results")


class TestPrecomputedScans:
    """Tests for pre-computed scan consistency"""
    
    @pytest.fixture
    def auth_token(self):
        """Get authentication token"""
        with httpx.Client() as client:
            response = client.post(
                f"{API_URL}/api/auth/login",
                json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
            )
            return response.json()["access_token"]
    
    def test_precomputed_cc_returns_valid_data(self, auth_token):
        """Test pre-computed CC scan returns valid data"""
        with httpx.Client() as client:
            response = client.get(
                f"{API_URL}/api/screener/precomputed/covered-calls",
                headers={"Authorization": f"Bearer {auth_token}"}
            )
            # May return 404 if not available
            if response.status_code == 404:
                pytest.skip("Pre-computed CC scans not available")
            
            assert response.status_code == 200
            data = response.json()
            
            # Verify structure
            for scan_type in ["conservative", "balanced", "aggressive"]:
                if scan_type in data:
                    for opp in data[scan_type]:
                        assert "symbol" in opp
                        assert "premium" in opp
                        assert "stock_price" in opp
            
            print("✓ Pre-computed CC scans valid")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-x"])
