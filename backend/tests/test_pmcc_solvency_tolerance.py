"""
PMCC Solvency Rule with 20% Tolerance Tests
============================================
Tests for the PMCC solvency rule fix that adds 20% tolerance.

The fix: pass if net_debit <= width * 1.20 instead of strict width > net_debit

This test file verifies:
1. Unit tests for validate_pmcc_solvency() in pricing_rules.py
2. Unit tests for validate_pmcc_structure() in eod_pipeline.py
3. API endpoint tests for /api/scans/pmcc/{risk_profile}
"""

import pytest
import requests
import os
import sys

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.pricing_rules import validate_pmcc_solvency, validate_pmcc_structure_rules
from services.eod_pipeline import validate_pmcc_structure

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://covered-call-docs.preview.emergentagent.com').rstrip('/')


# ============================================================
# UNIT TESTS: pricing_rules.py - validate_pmcc_solvency()
# ============================================================

class TestPricingRulesSolvency:
    """Unit tests for validate_pmcc_solvency() in pricing_rules.py"""
    
    def test_solvency_passes_when_net_debit_equals_width(self):
        """Test: net_debit == width should PASS (within 20% tolerance)"""
        # width = 10, net_debit = 10, threshold = 12
        is_valid, reason = validate_pmcc_solvency(
            long_strike=50.0,
            short_strike=60.0,  # width = 10
            net_debit=10.0
        )
        assert is_valid is True, f"Expected PASS but got: {reason}"
        assert reason == "PASS_SOLVENCY"
    
    def test_solvency_passes_when_net_debit_less_than_width(self):
        """Test: net_debit < width should PASS"""
        # width = 10, net_debit = 8, threshold = 12
        is_valid, reason = validate_pmcc_solvency(
            long_strike=50.0,
            short_strike=60.0,  # width = 10
            net_debit=8.0
        )
        assert is_valid is True, f"Expected PASS but got: {reason}"
        assert reason == "PASS_SOLVENCY"
    
    def test_solvency_passes_at_20_percent_tolerance(self):
        """Test: net_debit = width * 1.20 should PASS (exactly at threshold)"""
        # width = 10, net_debit = 12, threshold = 12
        is_valid, reason = validate_pmcc_solvency(
            long_strike=50.0,
            short_strike=60.0,  # width = 10
            net_debit=12.0
        )
        assert is_valid is True, f"Expected PASS but got: {reason}"
        assert reason == "PASS_SOLVENCY"
    
    def test_solvency_passes_within_20_percent_tolerance(self):
        """Test: net_debit between width and width*1.20 should PASS"""
        # width = 10, net_debit = 11, threshold = 12
        is_valid, reason = validate_pmcc_solvency(
            long_strike=50.0,
            short_strike=60.0,  # width = 10
            net_debit=11.0
        )
        assert is_valid is True, f"Expected PASS but got: {reason}"
        assert reason == "PASS_SOLVENCY"
    
    def test_solvency_fails_when_exceeds_20_percent_tolerance(self):
        """Test: net_debit > width * 1.20 should FAIL"""
        # width = 10, net_debit = 13, threshold = 12
        is_valid, reason = validate_pmcc_solvency(
            long_strike=50.0,
            short_strike=60.0,  # width = 10
            net_debit=13.0
        )
        assert is_valid is False, f"Expected FAIL but got: {reason}"
        assert "FAIL_SOLVENCY" in reason
    
    def test_solvency_fails_with_invalid_width(self):
        """Test: width <= 0 should FAIL"""
        # short_strike <= long_strike means width <= 0
        is_valid, reason = validate_pmcc_solvency(
            long_strike=60.0,
            short_strike=50.0,  # width = -10
            net_debit=5.0
        )
        assert is_valid is False
        assert "INVALID_WIDTH" in reason
    
    def test_solvency_real_world_example_pfe(self):
        """Test: Real-world PFE example from API (width=4, net_debit=4.52)"""
        # From API: PFE width=4.0, net_debit=4.52, threshold=4.80
        is_valid, reason = validate_pmcc_solvency(
            long_strike=22.0,
            short_strike=26.0,  # width = 4
            net_debit=4.52
        )
        assert is_valid is True, f"PFE should PASS with 20% tolerance: {reason}"
    
    def test_solvency_real_world_example_xom(self):
        """Test: Real-world XOM example from API (width=30, net_debit=32.11)"""
        # From API: XOM width=30.0, net_debit=32.11, threshold=36.00
        is_valid, reason = validate_pmcc_solvency(
            long_strike=80.0,
            short_strike=110.0,  # width = 30
            net_debit=32.11
        )
        assert is_valid is True, f"XOM should PASS with 20% tolerance: {reason}"


# ============================================================
# UNIT TESTS: eod_pipeline.py - validate_pmcc_structure()
# ============================================================

class TestEODPipelineSolvency:
    """Unit tests for validate_pmcc_structure() in eod_pipeline.py"""
    
    def test_structure_passes_with_20_percent_tolerance(self):
        """Test: PMCC structure passes when net_debit within 20% of width"""
        # width = 10, leap_ask = 15, short_bid = 3, net_debit = 12 (within 20%)
        # Using tight spreads to pass liquidity checks (spread < 5%)
        is_valid, flags = validate_pmcc_structure(
            stock_price=55.0,
            leap_strike=50.0,  # ITM
            leap_ask=15.0,
            leap_bid=14.5,  # Tight spread: (15-14.5)/14.75 = 3.4%
            leap_delta=0.85,
            leap_dte=400,
            leap_oi=200,
            short_strike=60.0,  # OTM, width = 10
            short_bid=3.0,
            short_ask=3.1,  # Tight spread: (3.1-3.0)/3.05 = 3.3%
            short_delta=0.25,
            short_dte=35,
            short_oi=200,
            short_iv=0.30
        )
        # net_debit = 15 - 3 = 12, width = 10, threshold = 12
        # 12 <= 12 should PASS
        assert is_valid is True, f"Expected PASS but got flags: {flags}"
    
    def test_structure_fails_when_exceeds_20_percent_tolerance(self):
        """Test: PMCC structure fails when net_debit > width * 1.20"""
        # width = 10, leap_ask = 16, short_bid = 3, net_debit = 13 (exceeds 20%)
        is_valid, flags = validate_pmcc_structure(
            stock_price=55.0,
            leap_strike=50.0,  # ITM
            leap_ask=16.0,
            leap_bid=15.5,  # Tight spread
            leap_delta=0.85,
            leap_dte=400,
            leap_oi=200,
            short_strike=60.0,  # OTM, width = 10
            short_bid=3.0,
            short_ask=3.1,  # Tight spread
            short_delta=0.25,
            short_dte=35,
            short_oi=200,
            short_iv=0.30
        )
        # net_debit = 16 - 3 = 13, width = 10, threshold = 12
        # 13 > 12 should FAIL
        assert is_valid is False, f"Expected FAIL but got valid with flags: {flags}"
        assert any("FAIL_SOLVENCY" in f for f in flags), f"Expected FAIL_SOLVENCY flag: {flags}"
    
    def test_structure_passes_strict_solvency(self):
        """Test: PMCC structure passes when width > net_debit (strict rule)"""
        # width = 10, leap_ask = 12, short_bid = 3, net_debit = 9
        is_valid, flags = validate_pmcc_structure(
            stock_price=55.0,
            leap_strike=50.0,
            leap_ask=12.0,
            leap_bid=11.6,  # Tight spread: (12-11.6)/11.8 = 3.4%
            leap_delta=0.85,
            leap_dte=400,
            leap_oi=200,
            short_strike=60.0,  # width = 10
            short_bid=3.0,
            short_ask=3.1,  # Tight spread
            short_delta=0.25,
            short_dte=35,
            short_oi=200,
            short_iv=0.30
        )
        # net_debit = 12 - 3 = 9, width = 10
        # 9 < 10 should PASS
        assert is_valid is True, f"Expected PASS but got flags: {flags}"


# ============================================================
# UNIT TESTS: pricing_rules.py - validate_pmcc_structure_rules()
# ============================================================

class TestPricingRulesStructure:
    """Unit tests for validate_pmcc_structure_rules() in pricing_rules.py"""
    
    def test_structure_rules_pass_with_tolerance(self):
        """Test: Structure rules pass when net_debit within 20% tolerance"""
        # width = 10, leap_ask = 15, short_bid = 3, net_debit = 12
        is_valid, flags = validate_pmcc_structure_rules(
            long_strike=50.0,
            short_strike=60.0,  # width = 10
            leap_ask=15.0,
            short_bid=3.0
        )
        # net_debit = 15 - 3 = 12, threshold = 12
        assert is_valid is True, f"Expected PASS but got flags: {flags}"
    
    def test_structure_rules_fail_exceeds_tolerance(self):
        """Test: Structure rules fail when net_debit > width * 1.20"""
        # width = 10, leap_ask = 16, short_bid = 3, net_debit = 13
        is_valid, flags = validate_pmcc_structure_rules(
            long_strike=50.0,
            short_strike=60.0,  # width = 10
            leap_ask=16.0,
            short_bid=3.0
        )
        # net_debit = 16 - 3 = 13, threshold = 12
        assert is_valid is False, f"Expected FAIL but got valid with flags: {flags}"


# ============================================================
# API TESTS: /api/scans/pmcc/{risk_profile}
# ============================================================

class TestPMCCAPIEndpoints:
    """API tests for PMCC scan endpoints"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get authentication token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "admin@premiumhunter.com", "password": "admin123"}
        )
        if response.status_code == 200:
            return response.json().get("access_token")
        pytest.skip("Authentication failed")
    
    @pytest.fixture(scope="class")
    def auth_headers(self, auth_token):
        """Get headers with auth token"""
        return {"Authorization": f"Bearer {auth_token}"}
    
    def test_pmcc_conservative_returns_opportunities(self, auth_headers):
        """Test: PMCC conservative endpoint returns opportunities (not zero)"""
        response = requests.get(
            f"{BASE_URL}/api/scans/pmcc/conservative",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("strategy") == "pmcc"
        assert data.get("risk_profile") == "conservative"
        assert data.get("total", 0) > 0, "PMCC conservative should return opportunities with 20% tolerance"
        assert data.get("is_precomputed") is True
    
    def test_pmcc_balanced_endpoint_works(self, auth_headers):
        """Test: PMCC balanced endpoint returns valid response"""
        response = requests.get(
            f"{BASE_URL}/api/scans/pmcc/balanced",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("strategy") == "pmcc"
        assert data.get("risk_profile") == "balanced"
        # May have 0 or more opportunities
        assert "total" in data
        assert "opportunities" in data
    
    def test_pmcc_aggressive_endpoint_works(self, auth_headers):
        """Test: PMCC aggressive endpoint returns valid response"""
        response = requests.get(
            f"{BASE_URL}/api/scans/pmcc/aggressive",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("strategy") == "pmcc"
        assert data.get("risk_profile") == "aggressive"
        assert "total" in data
        assert "opportunities" in data
    
    def test_pmcc_opportunities_have_solvency_data(self, auth_headers):
        """Test: PMCC opportunities include width and net_debit for solvency verification"""
        response = requests.get(
            f"{BASE_URL}/api/scans/pmcc/conservative",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        opportunities = data.get("opportunities", [])
        
        if len(opportunities) > 0:
            opp = opportunities[0]
            assert "width" in opp, "Opportunity should have width field"
            assert "net_debit" in opp, "Opportunity should have net_debit field"
            assert opp["width"] > 0, "Width should be positive"
            assert opp["net_debit"] > 0, "Net debit should be positive"
    
    def test_pmcc_opportunities_pass_20_percent_tolerance(self, auth_headers):
        """Test: All PMCC opportunities pass the 20% solvency tolerance rule"""
        response = requests.get(
            f"{BASE_URL}/api/scans/pmcc/conservative",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        opportunities = data.get("opportunities", [])
        
        for opp in opportunities:
            width = opp.get("width", 0)
            net_debit = opp.get("net_debit", 0)
            threshold = width * 1.20
            
            assert net_debit <= threshold, (
                f"{opp.get('symbol')}: net_debit ({net_debit}) > threshold ({threshold}). "
                f"Should pass 20% tolerance rule."
            )
    
    def test_pmcc_requires_authentication(self):
        """Test: PMCC endpoints require authentication"""
        response = requests.get(f"{BASE_URL}/api/scans/pmcc/conservative")
        assert response.status_code in [401, 403], "Should require authentication"
    
    def test_pmcc_invalid_risk_profile(self, auth_headers):
        """Test: Invalid risk profile returns 400"""
        response = requests.get(
            f"{BASE_URL}/api/scans/pmcc/invalid_profile",
            headers=auth_headers
        )
        assert response.status_code == 400


# ============================================================
# EDGE CASE TESTS
# ============================================================

class TestSolvencyEdgeCases:
    """Edge case tests for solvency rule"""
    
    def test_solvency_with_zero_width(self):
        """Test: Zero width should fail"""
        is_valid, reason = validate_pmcc_solvency(
            long_strike=50.0,
            short_strike=50.0,  # width = 0
            net_debit=5.0
        )
        assert is_valid is False
        assert "INVALID_WIDTH" in reason
    
    def test_solvency_with_very_small_tolerance_margin(self):
        """Test: net_debit just under threshold should pass"""
        # width = 100, threshold = 120, net_debit = 119.99
        is_valid, reason = validate_pmcc_solvency(
            long_strike=100.0,
            short_strike=200.0,  # width = 100
            net_debit=119.99
        )
        assert is_valid is True, f"Should pass when just under threshold: {reason}"
    
    def test_solvency_with_very_small_tolerance_exceed(self):
        """Test: net_debit just over threshold should fail"""
        # width = 100, threshold = 120, net_debit = 120.01
        is_valid, reason = validate_pmcc_solvency(
            long_strike=100.0,
            short_strike=200.0,  # width = 100
            net_debit=120.01
        )
        assert is_valid is False, f"Should fail when just over threshold: {reason}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
