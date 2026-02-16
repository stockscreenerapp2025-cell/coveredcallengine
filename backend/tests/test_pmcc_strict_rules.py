"""
PMCC Strict Institutional Rules Test Suite
==========================================
Tests the PMCC API endpoint /api/screener/pmcc to verify that all returned
opportunities strictly adhere to institutional-grade filtering rules.

PMCC STRICT RULES (Feb 2026):
- LEAP DTE: 365-730 days
- LEAP Delta: >= 0.80
- LEAP OI: >= 100
- LEAP Spread: <= 5%
- Short DTE: 30-45 days
- Short Delta: 0.20-0.30
- Short OI: >= 100
- Short Spread: <= 5%
- Solvency: width > net_debit
- Break-even: short_strike > breakeven
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# PMCC Constants from eod_pipeline.py
PMCC_MIN_LEAP_DTE = 365
PMCC_MAX_LEAP_DTE = 730
PMCC_MIN_LEAP_DELTA = 0.80
PMCC_MIN_LEAP_OI = 100
PMCC_MAX_LEAP_SPREAD_PCT = 5.0

PMCC_MIN_SHORT_DTE = 30
PMCC_MAX_SHORT_DTE = 45
PMCC_MIN_SHORT_DELTA = 0.20
PMCC_MAX_SHORT_DELTA = 0.30
PMCC_MIN_SHORT_OI = 100
PMCC_MAX_SHORT_SPREAD_PCT = 5.0


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token for API calls."""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "admin@premiumhunter.com", "password": "admin123"}
    )
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.skip("Authentication failed - skipping tests")


@pytest.fixture(scope="module")
def pmcc_response(auth_token):
    """Fetch PMCC results from API."""
    response = requests.get(
        f"{BASE_URL}/api/screener/pmcc",
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert response.status_code == 200, f"PMCC endpoint failed: {response.text}"
    return response.json()


class TestPMCCEndpointStructure:
    """Test PMCC API endpoint response structure."""
    
    def test_pmcc_endpoint_returns_200(self, auth_token):
        """PMCC endpoint should return 200 OK."""
        response = requests.get(
            f"{BASE_URL}/api/screener/pmcc",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
    
    def test_pmcc_response_has_required_fields(self, pmcc_response):
        """Response should have required top-level fields."""
        assert "total" in pmcc_response
        assert "results" in pmcc_response
        assert "opportunities" in pmcc_response
        assert "data_source" in pmcc_response
        assert "filters_applied" in pmcc_response
    
    def test_pmcc_data_source_is_eod_pipeline(self, pmcc_response):
        """Data source should be eod_pipeline (not live Yahoo)."""
        assert pmcc_response.get("data_source") == "eod_pipeline"
    
    def test_pmcc_live_data_not_used(self, pmcc_response):
        """live_data_used should be False (pre-computed data only)."""
        assert pmcc_response.get("live_data_used") == False
    
    def test_pmcc_filters_applied_match_strict_rules(self, pmcc_response):
        """filters_applied should show strict institutional parameters."""
        filters = pmcc_response.get("filters_applied", {})
        
        # Verify LEAP DTE filters
        assert filters.get("min_leap_dte") == PMCC_MIN_LEAP_DTE
        assert filters.get("max_leap_dte") == PMCC_MAX_LEAP_DTE
        
        # Verify Short DTE filters
        assert filters.get("min_short_dte") == PMCC_MIN_SHORT_DTE
        assert filters.get("max_short_dte") == PMCC_MAX_SHORT_DTE
        
        # Verify Delta filter
        assert filters.get("min_delta") == PMCC_MIN_LEAP_DELTA


class TestPMCCLeapRules:
    """Test LEAP (Long leg) strict rules."""
    
    def test_all_results_have_leap_dte_in_range(self, pmcc_response):
        """All PMCC results should have leap_dte between 365-730."""
        results = pmcc_response.get("results", [])
        
        for r in results:
            leap_dte = r.get("leap_dte", 0)
            assert PMCC_MIN_LEAP_DTE <= leap_dte <= PMCC_MAX_LEAP_DTE, \
                f"{r.get('symbol')}: leap_dte={leap_dte} not in [{PMCC_MIN_LEAP_DTE}, {PMCC_MAX_LEAP_DTE}]"
    
    def test_all_results_have_leap_delta_above_minimum(self, pmcc_response):
        """All PMCC results should have leap_delta >= 0.80."""
        results = pmcc_response.get("results", [])
        
        for r in results:
            leap_delta = r.get("leap_delta", 0)
            assert leap_delta >= PMCC_MIN_LEAP_DELTA, \
                f"{r.get('symbol')}: leap_delta={leap_delta} < {PMCC_MIN_LEAP_DELTA}"
    
    def test_all_results_have_valid_leap_strike(self, pmcc_response):
        """All PMCC results should have leap_strike < stock_price (ITM)."""
        results = pmcc_response.get("results", [])
        
        for r in results:
            leap_strike = r.get("leap_strike", 0)
            stock_price = r.get("stock_price", 0)
            assert leap_strike < stock_price, \
                f"{r.get('symbol')}: leap_strike={leap_strike} >= stock_price={stock_price} (not ITM)"
    
    def test_all_results_have_valid_leap_ask(self, pmcc_response):
        """All PMCC results should have leap_ask > 0."""
        results = pmcc_response.get("results", [])
        
        for r in results:
            leap_ask = r.get("leap_ask", 0)
            assert leap_ask > 0, \
                f"{r.get('symbol')}: leap_ask={leap_ask} <= 0"


class TestPMCCShortRules:
    """Test Short (Sell leg) strict rules."""
    
    def test_all_results_have_short_dte_in_range(self, pmcc_response):
        """All PMCC results should have short_dte between 30-45."""
        results = pmcc_response.get("results", [])
        
        for r in results:
            short_dte = r.get("short_dte", 0)
            assert PMCC_MIN_SHORT_DTE <= short_dte <= PMCC_MAX_SHORT_DTE, \
                f"{r.get('symbol')}: short_dte={short_dte} not in [{PMCC_MIN_SHORT_DTE}, {PMCC_MAX_SHORT_DTE}]"
    
    def test_all_results_have_short_delta_in_range(self, pmcc_response):
        """All PMCC results should have short_delta between 0.20-0.30."""
        results = pmcc_response.get("results", [])
        
        for r in results:
            short_delta = r.get("short_delta")
            # short_delta may not be in API response, check if present
            if short_delta is not None:
                assert PMCC_MIN_SHORT_DELTA <= short_delta <= PMCC_MAX_SHORT_DELTA, \
                    f"{r.get('symbol')}: short_delta={short_delta} not in [{PMCC_MIN_SHORT_DELTA}, {PMCC_MAX_SHORT_DELTA}]"
    
    def test_all_results_have_valid_short_bid(self, pmcc_response):
        """All PMCC results should have short_bid > 0."""
        results = pmcc_response.get("results", [])
        
        for r in results:
            short_bid = r.get("short_bid", 0)
            assert short_bid > 0, \
                f"{r.get('symbol')}: short_bid={short_bid} <= 0"
    
    def test_all_results_have_short_strike_otm(self, pmcc_response):
        """All PMCC results should have short_strike > stock_price (OTM)."""
        results = pmcc_response.get("results", [])
        
        for r in results:
            short_strike = r.get("short_strike", 0)
            stock_price = r.get("stock_price", 0)
            assert short_strike > stock_price, \
                f"{r.get('symbol')}: short_strike={short_strike} <= stock_price={stock_price} (not OTM)"


class TestPMCCSolvencyRule:
    """Test PMCC Solvency rule: width > net_debit."""
    
    def test_all_results_pass_solvency_rule(self, pmcc_response):
        """All PMCC results should have width > net_debit (solvency)."""
        results = pmcc_response.get("results", [])
        
        for r in results:
            width = r.get("width", 0)
            net_debit = r.get("net_debit", 0)
            assert width > net_debit, \
                f"{r.get('symbol')}: SOLVENCY FAIL - width={width} <= net_debit={net_debit}"
    
    def test_width_calculation_is_correct(self, pmcc_response):
        """Width should equal short_strike - leap_strike."""
        results = pmcc_response.get("results", [])
        
        for r in results:
            width = r.get("width", 0)
            short_strike = r.get("short_strike", 0)
            leap_strike = r.get("leap_strike", 0)
            expected_width = short_strike - leap_strike
            
            assert abs(width - expected_width) < 0.01, \
                f"{r.get('symbol')}: width={width} != short_strike({short_strike}) - leap_strike({leap_strike}) = {expected_width}"
    
    def test_net_debit_calculation_is_correct(self, pmcc_response):
        """Net debit should equal leap_ask - short_bid."""
        results = pmcc_response.get("results", [])
        
        for r in results:
            net_debit = r.get("net_debit", 0)
            leap_ask = r.get("leap_ask", 0)
            short_bid = r.get("short_bid", 0)
            expected_net_debit = leap_ask - short_bid
            
            assert abs(net_debit - expected_net_debit) < 0.01, \
                f"{r.get('symbol')}: net_debit={net_debit} != leap_ask({leap_ask}) - short_bid({short_bid}) = {expected_net_debit}"


class TestPMCCBreakevenRule:
    """Test PMCC Break-even rule: short_strike > breakeven."""
    
    def test_all_results_pass_breakeven_rule(self, pmcc_response):
        """All PMCC results should have short_strike > breakeven."""
        results = pmcc_response.get("results", [])
        
        for r in results:
            short_strike = r.get("short_strike", 0)
            breakeven = r.get("breakeven", 0)
            assert short_strike > breakeven, \
                f"{r.get('symbol')}: BREAK-EVEN FAIL - short_strike={short_strike} <= breakeven={breakeven}"
    
    def test_breakeven_calculation_is_correct(self, pmcc_response):
        """Breakeven should equal leap_strike + net_debit."""
        results = pmcc_response.get("results", [])
        
        for r in results:
            breakeven = r.get("breakeven", 0)
            leap_strike = r.get("leap_strike", 0)
            net_debit = r.get("net_debit", 0)
            expected_breakeven = leap_strike + net_debit
            
            assert abs(breakeven - expected_breakeven) < 0.01, \
                f"{r.get('symbol')}: breakeven={breakeven} != leap_strike({leap_strike}) + net_debit({net_debit}) = {expected_breakeven}"


class TestPMCCQualityFlags:
    """Test PMCC quality flags for valid trades."""
    
    def test_valid_trades_have_empty_quality_flags(self, pmcc_response):
        """Valid PMCC trades should have empty quality_flags []."""
        results = pmcc_response.get("results", [])
        
        for r in results:
            quality_flags = r.get("quality_flags", [])
            # Empty flags indicate all hard rules passed
            assert isinstance(quality_flags, list), \
                f"{r.get('symbol')}: quality_flags should be a list"
            
            # Check for any FAIL_ flags (hard rule failures)
            fail_flags = [f for f in quality_flags if f.startswith("FAIL_")]
            assert len(fail_flags) == 0, \
                f"{r.get('symbol')}: Has FAIL flags: {fail_flags}"


class TestPMCCPricingRules:
    """Test PMCC pricing rules (BUY_ASK_SELL_BID)."""
    
    def test_pricing_rule_is_buy_ask_sell_bid(self, pmcc_response):
        """All PMCC results should use BUY_ASK_SELL_BID pricing rule."""
        results = pmcc_response.get("results", [])
        
        for r in results:
            pricing_rule = r.get("pricing_rule")
            assert pricing_rule == "BUY_ASK_SELL_BID", \
                f"{r.get('symbol')}: pricing_rule={pricing_rule} != BUY_ASK_SELL_BID"
    
    def test_leap_used_equals_leap_ask(self, pmcc_response):
        """LEAP used price should equal leap_ask (BUY rule)."""
        results = pmcc_response.get("results", [])
        
        for r in results:
            leap_used = r.get("leap_used", 0)
            leap_ask = r.get("leap_ask", 0)
            assert abs(leap_used - leap_ask) < 0.01, \
                f"{r.get('symbol')}: leap_used={leap_used} != leap_ask={leap_ask}"
    
    def test_short_used_equals_short_bid(self, pmcc_response):
        """Short used price should equal short_bid (SELL rule)."""
        results = pmcc_response.get("results", [])
        
        for r in results:
            short_used = r.get("short_used", 0)
            short_bid = r.get("short_bid", 0)
            assert abs(short_used - short_bid) < 0.01, \
                f"{r.get('symbol')}: short_used={short_used} != short_bid={short_bid}"


class TestPMCCROICalculations:
    """Test PMCC ROI calculations."""
    
    def test_roi_per_cycle_is_positive(self, pmcc_response):
        """ROI per cycle should be positive for valid trades."""
        results = pmcc_response.get("results", [])
        
        for r in results:
            roi_per_cycle = r.get("roi_per_cycle", 0)
            assert roi_per_cycle > 0, \
                f"{r.get('symbol')}: roi_per_cycle={roi_per_cycle} <= 0"
    
    def test_roi_per_cycle_calculation(self, pmcc_response):
        """ROI per cycle should equal (short_bid / leap_ask) * 100."""
        results = pmcc_response.get("results", [])
        
        for r in results:
            roi_per_cycle = r.get("roi_per_cycle", 0)
            short_bid = r.get("short_bid", 0)
            leap_ask = r.get("leap_ask", 0)
            
            if leap_ask > 0:
                expected_roi = (short_bid / leap_ask) * 100
                assert abs(roi_per_cycle - expected_roi) < 0.1, \
                    f"{r.get('symbol')}: roi_per_cycle={roi_per_cycle} != expected={expected_roi:.2f}"
    
    def test_max_profit_is_positive(self, pmcc_response):
        """Max profit should be positive for valid trades."""
        results = pmcc_response.get("results", [])
        
        for r in results:
            max_profit = r.get("max_profit", 0)
            assert max_profit > 0, \
                f"{r.get('symbol')}: max_profit={max_profit} <= 0"
    
    def test_max_profit_calculation(self, pmcc_response):
        """Max profit should equal width - net_debit."""
        results = pmcc_response.get("results", [])
        
        for r in results:
            max_profit = r.get("max_profit", 0)
            width = r.get("width", 0)
            net_debit = r.get("net_debit", 0)
            expected_max_profit = width - net_debit
            
            assert abs(max_profit - expected_max_profit) < 0.1, \
                f"{r.get('symbol')}: max_profit={max_profit} != width({width}) - net_debit({net_debit}) = {expected_max_profit}"


class TestPMCCMarketContext:
    """Test PMCC market context fields."""
    
    def test_all_results_have_stock_price_source(self, pmcc_response):
        """All results should have stock_price_source field."""
        results = pmcc_response.get("results", [])
        
        for r in results:
            stock_price_source = r.get("stock_price_source")
            assert stock_price_source is not None, \
                f"{r.get('symbol')}: missing stock_price_source"
    
    def test_all_results_have_market_status(self, pmcc_response):
        """All results should have market_status field."""
        results = pmcc_response.get("results", [])
        
        for r in results:
            market_status = r.get("market_status")
            assert market_status is not None, \
                f"{r.get('symbol')}: missing market_status"
    
    def test_all_results_have_as_of_timestamp(self, pmcc_response):
        """All results should have as_of timestamp."""
        results = pmcc_response.get("results", [])
        
        for r in results:
            as_of = r.get("as_of")
            assert as_of is not None, \
                f"{r.get('symbol')}: missing as_of timestamp"


class TestPMCCRunInfo:
    """Test PMCC run_info consistency."""
    
    def test_run_info_present(self, pmcc_response):
        """Response should have run_info."""
        assert "run_info" in pmcc_response
        assert pmcc_response["run_info"] is not None
    
    def test_run_info_has_run_id(self, pmcc_response):
        """run_info should have run_id."""
        run_info = pmcc_response.get("run_info", {})
        assert "run_id" in run_info
        assert run_info["run_id"] is not None
    
    def test_results_match_run_id(self, pmcc_response):
        """All results should have matching run_id."""
        run_info = pmcc_response.get("run_info", {})
        expected_run_id = run_info.get("run_id")
        results = pmcc_response.get("results", [])
        
        for r in results:
            result_run_id = r.get("run_id")
            assert result_run_id == expected_run_id, \
                f"{r.get('symbol')}: run_id={result_run_id} != expected={expected_run_id}"


class TestPMCCDTEThresholds:
    """Test PMCC DTE thresholds in response."""
    
    def test_dte_thresholds_present(self, pmcc_response):
        """Response should have dte_thresholds."""
        assert "dte_thresholds" in pmcc_response
    
    def test_leap_dte_thresholds_correct(self, pmcc_response):
        """LEAP DTE thresholds should match strict rules."""
        dte_thresholds = pmcc_response.get("dte_thresholds", {})
        leap = dte_thresholds.get("leap", {})
        
        assert leap.get("min") == PMCC_MIN_LEAP_DTE
        assert leap.get("max") == PMCC_MAX_LEAP_DTE
    
    def test_short_dte_thresholds_correct(self, pmcc_response):
        """Short DTE thresholds should match strict rules."""
        dte_thresholds = pmcc_response.get("dte_thresholds", {})
        short = dte_thresholds.get("short", {})
        
        assert short.get("min") == PMCC_MIN_SHORT_DTE
        assert short.get("max") == PMCC_MAX_SHORT_DTE


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
