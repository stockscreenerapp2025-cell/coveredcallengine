"""
Unit Tests for IV Rank Service
==============================

CCE VOLATILITY & GREEKS CORRECTNESS - Test Suite

Tests:
1. IV Rank calculation with synthetic series
2. IV Percentile correctness
3. Edge cases: flat series, small series, missing IV
4. ATM proxy selection
5. Black-Scholes delta validation
"""

import pytest
from unittest.mock import MagicMock, AsyncMock
import math

# Add backend to path
import sys
sys.path.insert(0, '/app/backend')

from services.iv_rank_service import (
    compute_iv_atm_proxy,
    compute_iv_rank_percentile,
    MIN_SAMPLES_FOR_IV_RANK
)
from services.greeks_service import (
    calculate_greeks,
    normalize_iv_fields,
    validate_iv,
    get_risk_free_rate,
    sanity_check_delta,
    sanity_check_iv
)


class TestIVRankCalculation:
    """Test IV Rank and Percentile calculations."""
    
    def test_iv_rank_basic(self):
        """Test basic IV Rank calculation."""
        # Series: [0.20, 0.25, 0.30, 0.35]
        # Current: 0.30
        # iv_rank = 100 * (0.30 - 0.20) / (0.35 - 0.20) = 66.67
        series = [0.20, 0.25, 0.30, 0.35] * 10  # Duplicate to meet min samples
        iv_current = 0.30
        
        result = compute_iv_rank_percentile(iv_current, series)
        
        assert result["iv_samples"] == 40
        assert result["iv_low"] == 0.20
        assert result["iv_high"] == 0.35
        # Expected: 100 * (0.30 - 0.20) / (0.35 - 0.20) = 66.67
        assert abs(result["iv_rank"] - 66.7) < 0.1
        assert result["iv_rank_source"] == "OBSERVED_ATM_PROXY"
    
    def test_iv_percentile_basic(self):
        """Test IV Percentile calculation."""
        # Series: [0.20, 0.25, 0.30, 0.35] x 10
        # Current: 0.30
        # 20 values below 0.30 (0.20 and 0.25), so percentile = 50%
        series = [0.20, 0.25, 0.30, 0.35] * 10
        iv_current = 0.30
        
        result = compute_iv_rank_percentile(iv_current, series)
        
        # 20 values (0.20, 0.25) are below 0.30 out of 40 total
        assert result["iv_percentile"] == 50.0
    
    def test_iv_rank_at_low(self):
        """Test IV Rank when current is at the low."""
        series = [0.20, 0.25, 0.30, 0.35, 0.40] * 10
        iv_current = 0.20
        
        result = compute_iv_rank_percentile(iv_current, series)
        
        assert result["iv_rank"] == 0.0
    
    def test_iv_rank_at_high(self):
        """Test IV Rank when current is at the high."""
        series = [0.20, 0.25, 0.30, 0.35, 0.40] * 10
        iv_current = 0.40
        
        result = compute_iv_rank_percentile(iv_current, series)
        
        assert result["iv_rank"] == 100.0
    
    def test_iv_rank_insufficient_history(self):
        """Test IV Rank with insufficient history (<20 samples)."""
        series = [0.20, 0.25, 0.30]  # Only 3 samples
        iv_current = 0.25
        
        result = compute_iv_rank_percentile(iv_current, series)
        
        assert result["iv_rank"] == 50.0  # Default neutral
        assert result["iv_percentile"] == 50.0
        assert result["iv_rank_source"] == "DEFAULT_NEUTRAL_INSUFFICIENT_HISTORY"
        assert result["iv_samples"] == 3
    
    def test_iv_rank_flat_series(self):
        """Test IV Rank with flat series (all same values)."""
        series = [0.30] * 50  # All same value
        iv_current = 0.30
        
        result = compute_iv_rank_percentile(iv_current, series)
        
        # Flat series means iv_high == iv_low, should return 50 (neutral)
        assert result["iv_rank"] == 50.0
    
    def test_iv_rank_clamping(self):
        """Test IV Rank clamping at 0-100 bounds."""
        series = [0.20, 0.30, 0.40] * 10
        
        # Current above max
        result_high = compute_iv_rank_percentile(0.50, series)
        assert result_high["iv_rank"] == 100.0
        
        # Current below min
        result_low = compute_iv_rank_percentile(0.10, series)
        assert result_low["iv_rank"] == 0.0


class TestATMProxySelection:
    """Test ATM proxy selection from options chain."""
    
    def test_atm_proxy_basic(self):
        """Test basic ATM proxy selection."""
        options = [
            {"strike": 95, "dte": 30, "implied_volatility": 0.25, "expiry": "2024-01-15"},
            {"strike": 100, "dte": 30, "implied_volatility": 0.28, "expiry": "2024-01-15"},
            {"strike": 105, "dte": 30, "implied_volatility": 0.30, "expiry": "2024-01-15"},
        ]
        stock_price = 100
        
        iv_proxy, meta = compute_iv_atm_proxy(options, stock_price)
        
        assert iv_proxy == 0.28  # ATM strike is 100
        assert meta["selected_strike"] == 100
    
    def test_atm_proxy_dte_preference(self):
        """Test that proxy prefers target DTE."""
        options = [
            {"strike": 100, "dte": 10, "implied_volatility": 0.20, "expiry": "2024-01-10"},
            {"strike": 100, "dte": 35, "implied_volatility": 0.30, "expiry": "2024-01-30"},
            {"strike": 100, "dte": 60, "implied_volatility": 0.40, "expiry": "2024-02-15"},
        ]
        stock_price = 100
        
        iv_proxy, meta = compute_iv_atm_proxy(options, stock_price, target_dte=35)
        
        assert iv_proxy == 0.30  # Should select 35 DTE
        assert meta["selected_dte"] == 35
    
    def test_atm_proxy_no_valid_options(self):
        """Test ATM proxy when no valid options exist."""
        options = [
            {"strike": 100, "dte": 5, "implied_volatility": 0.30, "expiry": "2024-01-05"},  # Below min DTE
            {"strike": 100, "dte": 100, "implied_volatility": 0.30, "expiry": "2024-04-05"},  # Above max DTE
        ]
        stock_price = 100
        
        iv_proxy, meta = compute_iv_atm_proxy(options, stock_price)
        
        assert iv_proxy is None
        assert "error" in meta
    
    def test_atm_proxy_invalid_iv_filtered(self):
        """Test that invalid IV values are filtered."""
        options = [
            {"strike": 100, "dte": 30, "implied_volatility": 0.005, "expiry": "2024-01-15"},  # Too low
            {"strike": 105, "dte": 30, "implied_volatility": 0.30, "expiry": "2024-01-15"},
        ]
        stock_price = 100
        
        iv_proxy, meta = compute_iv_atm_proxy(options, stock_price)
        
        # Should select 105 strike since 100 has invalid IV
        assert meta["selected_strike"] == 105


class TestGreeksService:
    """Test Black-Scholes Greeks calculations."""
    
    def test_call_delta_bounds(self):
        """Test call delta is within [0, 1]."""
        # ATM call
        result = calculate_greeks(S=100, K=100, T=30/365, sigma=0.30, option_type="call")
        assert 0 <= result.delta <= 1
        assert result.delta_source == "BS"
        
        # Deep ITM call
        result_itm = calculate_greeks(S=100, K=80, T=30/365, sigma=0.30, option_type="call")
        assert result_itm.delta > 0.8
        
        # Deep OTM call
        result_otm = calculate_greeks(S=100, K=120, T=30/365, sigma=0.30, option_type="call")
        assert result_otm.delta < 0.2
    
    def test_put_delta_bounds(self):
        """Test put delta is within [-1, 0]."""
        result = calculate_greeks(S=100, K=100, T=30/365, sigma=0.30, option_type="put")
        assert -1 <= result.delta <= 0
        
        # Deep ITM put
        result_itm = calculate_greeks(S=100, K=120, T=30/365, sigma=0.30, option_type="put")
        assert result_itm.delta < -0.8
        
        # Deep OTM put
        result_otm = calculate_greeks(S=100, K=80, T=30/365, sigma=0.30, option_type="put")
        assert result_otm.delta > -0.2
    
    def test_delta_with_proxy_sigma(self):
        """Test delta calculation with proxy sigma when IV is missing."""
        result = calculate_greeks(S=100, K=100, T=30/365, sigma=None, option_type="call")
        
        assert 0 <= result.delta <= 1
        assert result.delta_source == "BS_PROXY_SIGMA"
        assert result.sigma_used == 0.35  # Default proxy
    
    def test_delta_at_expiry(self):
        """Test delta at expiry (T=0)."""
        # ITM call at expiry
        result = calculate_greeks(S=100, K=95, T=0, sigma=0.30, option_type="call")
        assert result.delta == 1.0
        
        # OTM call at expiry
        result_otm = calculate_greeks(S=100, K=105, T=0, sigma=0.30, option_type="call")
        assert result_otm.delta == 0.0
    
    def test_greeks_no_nan(self):
        """Test that Greeks never return NaN."""
        test_cases = [
            {"S": 100, "K": 100, "T": 30/365, "sigma": 0.30},
            {"S": 100, "K": 100, "T": 1/365, "sigma": 0.30},  # Very short term
            {"S": 100, "K": 100, "T": 365/365, "sigma": 0.80},  # High IV
            {"S": 100, "K": 100, "T": 30/365, "sigma": None},  # Missing IV
        ]
        
        for tc in test_cases:
            result = calculate_greeks(**tc, option_type="call")
            assert not math.isnan(result.delta), f"Delta is NaN for {tc}"
            assert not math.isnan(result.gamma), f"Gamma is NaN for {tc}"
            assert not math.isnan(result.theta), f"Theta is NaN for {tc}"
            assert not math.isnan(result.vega), f"Vega is NaN for {tc}"


class TestIVNormalization:
    """Test IV normalization functions."""
    
    def test_normalize_decimal_iv(self):
        """Test normalizing decimal IV."""
        result = normalize_iv_fields(0.30)
        
        assert result["iv"] == 0.30
        assert result["iv_pct"] == 30.0
        assert result["iv_valid"] == True
    
    def test_normalize_invalid_iv(self):
        """Test normalizing invalid IV."""
        # Too low
        result_low = normalize_iv_fields(0.005)
        assert result_low["iv"] == 0.0
        assert result_low["iv_valid"] == False
        
        # Too high
        result_high = normalize_iv_fields(6.0)
        assert result_high["iv"] == 0.0
        assert result_high["iv_valid"] == False
        
        # None
        result_none = normalize_iv_fields(None)
        assert result_none["iv"] == 0.0
        assert result_none["iv_valid"] == False
    
    def test_validate_iv_bounds(self):
        """Test IV validation bounds."""
        # Valid range
        assert validate_iv(0.30) == (0.30, True)
        assert validate_iv(0.01) == (0.01, True)  # Just at lower bound
        
        # Invalid
        assert validate_iv(0.005)[1] == False
        assert validate_iv(5.5)[1] == False


class TestSanityChecks:
    """Test sanity check functions."""
    
    def test_delta_sanity_call(self):
        """Test delta sanity check for calls."""
        assert sanity_check_delta(0.5, "call") == (True, "")
        assert sanity_check_delta(0.0, "call") == (True, "")
        assert sanity_check_delta(1.0, "call") == (True, "")
        
        # Invalid
        is_valid, error = sanity_check_delta(-0.1, "call")
        assert is_valid == False
        assert "not in [0, 1]" in error
    
    def test_delta_sanity_put(self):
        """Test delta sanity check for puts."""
        assert sanity_check_delta(-0.5, "put") == (True, "")
        assert sanity_check_delta(0.0, "put") == (True, "")
        assert sanity_check_delta(-1.0, "put") == (True, "")
        
        # Invalid
        is_valid, error = sanity_check_delta(0.1, "put")
        assert is_valid == False
        assert "not in [-1, 0]" in error
    
    def test_iv_sanity(self):
        """Test IV sanity check."""
        assert sanity_check_iv(0.30) == (True, "")
        assert sanity_check_iv(4.5) == (True, "")
        
        # Invalid
        assert sanity_check_iv(None) == (False, "IV is None")
        is_valid, error = sanity_check_iv(5.5)
        assert is_valid == False


class TestRiskFreeRate:
    """Test risk-free rate configuration."""
    
    def test_default_rate(self):
        """Test default risk-free rate."""
        import os
        # Clear env var if set
        if "RISK_FREE_RATE" in os.environ:
            del os.environ["RISK_FREE_RATE"]
        
        rate = get_risk_free_rate()
        assert rate == 0.045
    
    def test_custom_rate_from_env(self):
        """Test custom rate from environment."""
        import os
        os.environ["RISK_FREE_RATE"] = "0.05"
        
        rate = get_risk_free_rate()
        assert rate == 0.05
        
        # Cleanup
        del os.environ["RISK_FREE_RATE"]
    
    def test_invalid_rate_bounds(self):
        """Test rate validation bounds."""
        import os
        
        # Rate too high
        os.environ["RISK_FREE_RATE"] = "0.25"
        rate = get_risk_free_rate()
        assert rate == 0.045  # Should revert to default
        
        # Rate too low
        os.environ["RISK_FREE_RATE"] = "-0.01"
        rate = get_risk_free_rate()
        assert rate == 0.045  # Should revert to default
        
        # Cleanup
        if "RISK_FREE_RATE" in os.environ:
            del os.environ["RISK_FREE_RATE"]


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
