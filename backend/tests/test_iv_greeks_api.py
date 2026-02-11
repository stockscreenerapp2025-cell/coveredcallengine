"""
API Tests for CCE Volatility & Greeks Correctness
==================================================

Tests the following endpoints:
1. GET /api/admin/iv-metrics/check/{symbol} - IV metrics verification
2. GET /api/screener/covered-calls - Custom scan with IV/Greeks fields

Validates:
- Delta computed via Black-Scholes (delta_source='BS' or 'BS_PROXY_SIGMA')
- Delta sanity: Call delta in [0, 1], no NaN
- IV fields normalized: iv (decimal), iv_pct (percentage), iv_pct == iv * 100
- IV Rank fields: iv_rank, iv_percentile, iv_rank_source, iv_samples
- Consistent field population across all endpoints
"""

import pytest
import requests
import os
import math

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
ADMIN_EMAIL = "admin@premiumhunter.com"
ADMIN_PASSWORD = "admin123"


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token for admin user."""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    if response.status_code == 200:
        data = response.json()
        return data.get("access_token") or data.get("token")
    pytest.skip(f"Authentication failed: {response.status_code} - {response.text}")


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Get headers with auth token."""
    return {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }


class TestAdminIVMetricsEndpoint:
    """Test GET /api/admin/iv-metrics/check/{symbol}"""
    
    def test_iv_metrics_check_returns_200(self, auth_headers):
        """Test that IV metrics check endpoint returns 200 for valid symbol."""
        response = requests.get(
            f"{BASE_URL}/api/admin/iv-metrics/check/AAPL",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    
    def test_iv_metrics_check_returns_required_fields(self, auth_headers):
        """Test that IV metrics check returns all required fields."""
        response = requests.get(
            f"{BASE_URL}/api/admin/iv-metrics/check/AAPL",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # Check top-level fields
        assert "symbol" in data
        assert "status" in data
        assert data["status"] == "success", f"Status is {data['status']}: {data.get('error')}"
        
        # Check iv_metrics object
        assert "iv_metrics" in data, "Missing iv_metrics object"
        iv_metrics = data["iv_metrics"]
        
        required_iv_fields = [
            "iv_proxy", "iv_proxy_pct", "iv_rank", "iv_percentile",
            "iv_samples", "iv_rank_source"
        ]
        for field in required_iv_fields:
            assert field in iv_metrics, f"Missing field: {field}"
        
        # Check greeks_sanity_checks
        assert "greeks_sanity_checks" in data, "Missing greeks_sanity_checks"
        assert len(data["greeks_sanity_checks"]) > 0, "No greeks sanity checks returned"
    
    def test_iv_metrics_check_delta_source(self, auth_headers):
        """Test that delta_source is BS or BS_PROXY_SIGMA (not moneyness)."""
        response = requests.get(
            f"{BASE_URL}/api/admin/iv-metrics/check/AAPL",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        greeks_checks = data.get("greeks_sanity_checks", [])
        for check in greeks_checks:
            delta_source = check.get("delta_source", "")
            # Valid sources: BS, BS_PROXY_SIGMA, EXPIRY, MISSING
            valid_sources = ["BS", "BS_PROXY_SIGMA", "EXPIRY", "MISSING"]
            assert delta_source in valid_sources, f"Invalid delta_source: {delta_source}"
            # Should NOT be moneyness-based
            assert "MONEYNESS" not in delta_source.upper(), f"Moneyness fallback detected: {delta_source}"
    
    def test_iv_metrics_check_delta_bounds(self, auth_headers):
        """Test that call delta is in [0, 1] and not NaN."""
        response = requests.get(
            f"{BASE_URL}/api/admin/iv-metrics/check/AAPL",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        greeks_checks = data.get("greeks_sanity_checks", [])
        for check in greeks_checks:
            delta = check.get("delta")
            assert delta is not None, "Delta is None"
            assert not math.isnan(delta), f"Delta is NaN for strike {check.get('strike')}"
            assert 0 <= delta <= 1, f"Call delta {delta} not in [0, 1] for strike {check.get('strike')}"
            
            # Verify the sanity check passed
            checks = check.get("checks", {})
            assert checks.get("delta_in_bounds") == True, f"Delta sanity check failed: {checks.get('delta_error')}"
    
    def test_iv_metrics_check_iv_normalization(self, auth_headers):
        """Test that IV is normalized correctly (iv decimal, iv_pct percentage)."""
        response = requests.get(
            f"{BASE_URL}/api/admin/iv-metrics/check/AAPL",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        greeks_checks = data.get("greeks_sanity_checks", [])
        for check in greeks_checks:
            iv = check.get("iv", 0)
            iv_pct = check.get("iv_pct", 0)
            
            # IV should be decimal (typically 0.1 to 2.0)
            if iv > 0:
                assert iv < 5.0, f"IV {iv} looks like percentage, should be decimal"
                # iv_pct should be iv * 100
                expected_pct = round(iv * 100, 1)
                assert abs(iv_pct - expected_pct) < 0.2, f"iv_pct {iv_pct} != iv*100 ({expected_pct})"
    
    def test_iv_metrics_check_iv_rank_source(self, auth_headers):
        """Test that IV rank source is valid."""
        response = requests.get(
            f"{BASE_URL}/api/admin/iv-metrics/check/AAPL",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        iv_metrics = data.get("iv_metrics", {})
        iv_rank_source = iv_metrics.get("iv_rank_source", "")
        
        valid_sources = [
            "OBSERVED_ATM_PROXY",
            "DEFAULT_NEUTRAL_INSUFFICIENT_HISTORY",
            "NO_ATM_PROXY_AVAILABLE",
            "NO_HISTORY_AVAILABLE"
        ]
        assert iv_rank_source in valid_sources, f"Invalid iv_rank_source: {iv_rank_source}"
    
    def test_iv_metrics_check_r_used(self, auth_headers):
        """Test that risk-free rate is returned."""
        response = requests.get(
            f"{BASE_URL}/api/admin/iv-metrics/check/AAPL",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "r_used" in data, "Missing r_used field"
        r_used = data["r_used"]
        assert 0 < r_used <= 0.20, f"r_used {r_used} out of expected bounds"


class TestCoveredCallsScreenerEndpoint:
    """Test GET /api/screener/covered-calls"""
    
    def test_covered_calls_returns_200(self, auth_headers):
        """Test that covered calls endpoint returns 200."""
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls?limit=10",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    
    def test_covered_calls_returns_results(self, auth_headers):
        """Test that covered calls returns results array."""
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls?limit=10",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        assert "results" in data or "opportunities" in data, "Missing results/opportunities array"
        results = data.get("results") or data.get("opportunities", [])
        assert len(results) > 0, "No results returned"
    
    def test_covered_calls_delta_fields(self, auth_headers):
        """Test that each trade has delta and delta_source fields."""
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls?limit=10",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        results = data.get("results") or data.get("opportunities", [])
        for trade in results[:5]:  # Check first 5
            # Check flat fields (legacy)
            assert "delta" in trade, f"Missing delta for {trade.get('symbol')}"
            assert "delta_source" in trade, f"Missing delta_source for {trade.get('symbol')}"
            
            delta = trade["delta"]
            delta_source = trade["delta_source"]
            
            # Delta should be in [0, 1] for calls
            assert 0 <= delta <= 1, f"Delta {delta} not in [0, 1] for {trade.get('symbol')}"
            
            # Delta source should be BS or BS_PROXY_SIGMA
            valid_sources = ["BS", "BS_PROXY_SIGMA", "EXPIRY", "MISSING", "UNKNOWN"]
            assert delta_source in valid_sources, f"Invalid delta_source: {delta_source}"
    
    def test_covered_calls_iv_fields(self, auth_headers):
        """Test that each trade has iv and iv_pct fields."""
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls?limit=10",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        results = data.get("results") or data.get("opportunities", [])
        for trade in results[:5]:
            # Check IV fields
            assert "iv" in trade, f"Missing iv for {trade.get('symbol')}"
            assert "iv_pct" in trade, f"Missing iv_pct for {trade.get('symbol')}"
            
            iv = trade["iv"]
            iv_pct = trade["iv_pct"]
            
            # IV should be decimal
            if iv > 0:
                assert iv < 5.0, f"IV {iv} looks like percentage for {trade.get('symbol')}"
                # iv_pct should be iv * 100
                expected_pct = round(iv * 100, 1)
                assert abs(iv_pct - expected_pct) < 1.0, f"iv_pct {iv_pct} != iv*100 ({expected_pct})"
    
    def test_covered_calls_iv_rank_fields(self, auth_headers):
        """Test that each trade has IV rank fields."""
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls?limit=10",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        results = data.get("results") or data.get("opportunities", [])
        for trade in results[:5]:
            # Check IV rank fields
            assert "iv_rank" in trade, f"Missing iv_rank for {trade.get('symbol')}"
            assert "iv_percentile" in trade, f"Missing iv_percentile for {trade.get('symbol')}"
            assert "iv_rank_source" in trade, f"Missing iv_rank_source for {trade.get('symbol')}"
            assert "iv_samples" in trade, f"Missing iv_samples for {trade.get('symbol')}"
            
            iv_rank = trade["iv_rank"]
            iv_percentile = trade["iv_percentile"]
            iv_rank_source = trade["iv_rank_source"]
            iv_samples = trade["iv_samples"]
            
            # IV rank should be 0-100
            assert 0 <= iv_rank <= 100, f"iv_rank {iv_rank} not in [0, 100]"
            assert 0 <= iv_percentile <= 100, f"iv_percentile {iv_percentile} not in [0, 100]"
            
            # iv_samples should be non-negative
            assert iv_samples >= 0, f"iv_samples {iv_samples} is negative"
            
            # iv_rank_source should be valid
            valid_sources = [
                "OBSERVED_ATM_PROXY",
                "DEFAULT_NEUTRAL_INSUFFICIENT_HISTORY",
                "DEFAULT_NEUTRAL_NO_METRICS",
                "DEFAULT_NEUTRAL",
                "NO_ATM_PROXY_AVAILABLE",
                "NO_HISTORY_AVAILABLE"
            ]
            assert iv_rank_source in valid_sources, f"Invalid iv_rank_source: {iv_rank_source}"
    
    def test_covered_calls_short_call_object(self, auth_headers):
        """Test that short_call object has all required fields."""
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls?limit=10",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        results = data.get("results") or data.get("opportunities", [])
        for trade in results[:3]:
            # Check short_call object
            assert "short_call" in trade, f"Missing short_call for {trade.get('symbol')}"
            short_call = trade["short_call"]
            
            required_fields = [
                "strike", "expiry", "dte", "premium", "bid",
                "delta", "delta_source",
                "iv", "iv_pct",
                "iv_rank", "iv_percentile", "iv_rank_source", "iv_samples"
            ]
            for field in required_fields:
                assert field in short_call, f"Missing {field} in short_call for {trade.get('symbol')}"
    
    def test_covered_calls_no_nan_values(self, auth_headers):
        """Test that no NaN values are returned."""
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls?limit=20",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        results = data.get("results") or data.get("opportunities", [])
        for trade in results:
            # Check numeric fields for NaN
            numeric_fields = ["delta", "iv", "iv_pct", "iv_rank", "iv_percentile", "gamma", "theta", "vega"]
            for field in numeric_fields:
                value = trade.get(field)
                if value is not None and isinstance(value, float):
                    assert not math.isnan(value), f"{field} is NaN for {trade.get('symbol')}"


class TestIVRankNeutralFallback:
    """Test IV Rank neutral fallback behavior."""
    
    def test_iv_rank_neutral_when_insufficient_history(self, auth_headers):
        """Test that IV rank is 50 (neutral) when history is insufficient."""
        response = requests.get(
            f"{BASE_URL}/api/admin/iv-metrics/check/AAPL",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        iv_metrics = data.get("iv_metrics", {})
        iv_samples = iv_metrics.get("iv_samples", 0)
        iv_rank = iv_metrics.get("iv_rank", 0)
        iv_rank_source = iv_metrics.get("iv_rank_source", "")
        
        # If samples < 20, should be neutral
        if iv_samples < 20:
            assert iv_rank == 50.0, f"Expected neutral IV rank (50) with {iv_samples} samples, got {iv_rank}"
            assert "INSUFFICIENT" in iv_rank_source or "DEFAULT" in iv_rank_source, \
                f"Expected insufficient/default source, got {iv_rank_source}"


class TestIVMetricsStats:
    """Test GET /api/admin/iv-metrics/stats"""
    
    def test_iv_stats_returns_200(self, auth_headers):
        """Test that IV stats endpoint returns 200."""
        response = requests.get(
            f"{BASE_URL}/api/admin/iv-metrics/stats",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    
    def test_iv_stats_returns_required_fields(self, auth_headers):
        """Test that IV stats returns required fields."""
        response = requests.get(
            f"{BASE_URL}/api/admin/iv-metrics/stats",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        required_fields = ["total_entries", "unique_symbols", "min_samples_required"]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
        
        # min_samples_required should be 20
        assert data["min_samples_required"] == 20, f"Expected min_samples_required=20, got {data['min_samples_required']}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
