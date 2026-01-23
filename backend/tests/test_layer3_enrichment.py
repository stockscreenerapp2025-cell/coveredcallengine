"""
Layer 3 Enrichment Unit Tests

Tests for:
- Greeks enrichment (Delta, IV, IV Rank, Theta, Gamma, Vega)
- ROI calculation
- PMCC metrics
- Weekly/Monthly/All DTE selection
- GOOG vs GOOGL distinction
"""

import pytest
from datetime import datetime, timedelta
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from routes.screener_snapshot import (
    enrich_option_greeks,
    enrich_pmcc_metrics,
    log_price_discrepancy,
    get_dte_range,
    WEEKLY_MIN_DTE,
    WEEKLY_MAX_DTE,
    MONTHLY_MIN_DTE,
    MONTHLY_MAX_DTE,
    SCAN_SYMBOLS
)


class TestGreeksEnrichment:
    """Test suite for Greeks enrichment function"""
    
    def test_basic_greeks_enrichment(self):
        """Test that basic contract enrichment adds all required fields"""
        contract = {
            "strike": 100,
            "dte": 30,
            "implied_volatility": 0.35,
            "option_type": "call",
            "bid": 2.50,
            "ask": 2.70
        }
        stock_price = 98.00
        
        enriched = enrich_option_greeks(contract, stock_price)
        
        # Verify all required fields are present
        assert "delta" in enriched
        assert "iv_pct" in enriched
        assert "iv_rank" in enriched
        assert "theta_estimate" in enriched
        assert "gamma_estimate" in enriched
        assert "vega_estimate" in enriched
        assert "roi_pct" in enriched
        assert "roi_annualized" in enriched
        assert "premium_ask" in enriched
    
    def test_roi_calculation(self):
        """Test ROI calculation: (Premium / Stock Price) * 100 * (365 / DTE)"""
        contract = {
            "strike": 100,
            "dte": 30,
            "implied_volatility": 0.30,
            "option_type": "call",
            "bid": 3.00,
            "ask": 3.20
        }
        stock_price = 100.00
        
        enriched = enrich_option_greeks(contract, stock_price)
        
        # ROI per trade = (3.00 / 100.00) * 100 = 3%
        expected_roi = 3.00
        assert abs(enriched["roi_pct"] - expected_roi) < 0.01
        
        # Annualized ROI = 3% * (365 / 30) = ~36.5%
        expected_annualized = 3.00 * (365 / 30)
        assert abs(enriched["roi_annualized"] - expected_annualized) < 0.5
    
    def test_delta_estimation_otm_call(self):
        """Test delta estimation for OTM call"""
        contract = {
            "strike": 105,  # 5% OTM
            "dte": 30,
            "implied_volatility": 0.30,
            "option_type": "call",
            "bid": 1.50,
            "ask": 1.70
        }
        stock_price = 100.00
        
        enriched = enrich_option_greeks(contract, stock_price)
        
        # OTM call should have delta < 0.5
        assert enriched["delta"] < 0.50
        assert enriched["delta"] > 0.0
    
    def test_delta_estimation_itm_call(self):
        """Test delta estimation for ITM call"""
        contract = {
            "strike": 95,  # ITM
            "dte": 30,
            "implied_volatility": 0.30,
            "option_type": "call",
            "bid": 6.00,
            "ask": 6.20
        }
        stock_price = 100.00
        
        enriched = enrich_option_greeks(contract, stock_price)
        
        # ITM call should have delta > 0.5
        assert enriched["delta"] > 0.50
    
    def test_iv_percentage_conversion(self):
        """Test IV conversion from decimal to percentage"""
        # Test decimal IV (0.35 = 35%)
        contract = {
            "strike": 100,
            "dte": 30,
            "implied_volatility": 0.35,
            "option_type": "call",
            "bid": 2.50
        }
        enriched = enrich_option_greeks(contract, 100.00)
        assert enriched["iv_pct"] == 35.0
        
        # Test already-percentage IV
        contract2 = {
            "strike": 100,
            "dte": 30,
            "implied_volatility": 35.0,
            "option_type": "call",
            "bid": 2.50
        }
        enriched2 = enrich_option_greeks(contract2, 100.00)
        assert enriched2["iv_pct"] == 35.0
    
    def test_iv_rank_calculation(self):
        """Test IV rank estimation"""
        # Low IV (20%) should give low rank
        contract_low = {
            "strike": 100,
            "dte": 30,
            "implied_volatility": 0.20,
            "option_type": "call",
            "bid": 2.00
        }
        enriched_low = enrich_option_greeks(contract_low, 100.00)
        assert enriched_low["iv_rank"] < 30
        
        # High IV (60%) should give high rank
        contract_high = {
            "strike": 100,
            "dte": 30,
            "implied_volatility": 0.60,
            "option_type": "call",
            "bid": 5.00
        }
        enriched_high = enrich_option_greeks(contract_high, 100.00)
        assert enriched_high["iv_rank"] > 50
    
    def test_theta_estimate(self):
        """Test theta estimation"""
        contract = {
            "strike": 100,
            "dte": 30,
            "implied_volatility": 0.30,
            "option_type": "call",
            "bid": 3.00
        }
        
        enriched = enrich_option_greeks(contract, 100.00)
        
        # Theta should be negative (time decay)
        assert enriched["theta_estimate"] < 0
    
    def test_zero_premium_handling(self):
        """Test handling of zero premium"""
        contract = {
            "strike": 100,
            "dte": 30,
            "implied_volatility": 0.30,
            "option_type": "call",
            "bid": 0,
            "ask": 0.05
        }
        
        enriched = enrich_option_greeks(contract, 100.00)
        
        # Should not crash, ROI should be 0
        assert enriched["roi_pct"] == 0
        assert enriched["roi_annualized"] == 0


class TestPMCCMetrics:
    """Test suite for PMCC metrics enrichment"""
    
    def test_pmcc_basic_metrics(self):
        """Test basic PMCC metrics calculation"""
        leap = {
            "strike": 90,
            "ask": 20.00,
            "premium": 20.00,
            "dte": 400,
            "delta": 0.75,
            "open_interest": 1000
        }
        short = {
            "strike": 105,
            "bid": 2.50,
            "premium": 2.50,
            "dte": 30
        }
        stock_price = 100.00
        
        metrics = enrich_pmcc_metrics(leap, short, stock_price)
        
        # Check all required PMCC fields
        assert "leaps_buy_eligible" in metrics
        assert "premium_ask" in metrics
        assert "delta" in metrics
        assert "leap_dte" in metrics
        assert "short_dte" in metrics
        assert "leap_cost" in metrics
        assert "width" in metrics
        assert "net_debit" in metrics
        assert "roi_per_cycle" in metrics
        assert "roi_annualized" in metrics
        assert "breakeven" in metrics
    
    def test_pmcc_leaps_eligibility(self):
        """Test LEAPS buy eligibility criteria"""
        # Eligible LEAP: DTE >= 365, Delta >= 0.70, OI >= 500
        eligible_leap = {
            "strike": 90,
            "ask": 20.00,
            "dte": 400,
            "delta": 0.75,
            "open_interest": 600
        }
        short = {"strike": 105, "bid": 2.50, "dte": 30}
        
        metrics = enrich_pmcc_metrics(eligible_leap, short, 100.00)
        assert metrics["leaps_buy_eligible"] == True
        
        # Ineligible LEAP: DTE < 365
        ineligible_leap = {
            "strike": 90,
            "ask": 20.00,
            "dte": 300,  # Too short
            "delta": 0.75,
            "open_interest": 600
        }
        
        metrics2 = enrich_pmcc_metrics(ineligible_leap, short, 100.00)
        assert metrics2["leaps_buy_eligible"] == False
    
    def test_pmcc_width_calculation(self):
        """Test width (spread) calculation"""
        leap = {"strike": 90, "ask": 20.00, "dte": 400, "delta": 0.75, "open_interest": 600}
        short = {"strike": 105, "bid": 2.50, "dte": 30}
        
        metrics = enrich_pmcc_metrics(leap, short, 100.00)
        
        # Width = short_strike - leap_strike = 105 - 90 = 15
        assert metrics["width"] == 15.00
    
    def test_pmcc_roi_calculation(self):
        """Test PMCC ROI per cycle calculation"""
        leap = {"strike": 90, "ask": 20.00, "premium": 20.00, "dte": 400, "delta": 0.75, "open_interest": 600}
        short = {"strike": 105, "bid": 2.50, "premium": 2.50, "dte": 30}
        
        metrics = enrich_pmcc_metrics(leap, short, 100.00)
        
        # ROI per cycle = (short_bid / leap_ask) * 100 = (2.50 / 20.00) * 100 = 12.5%
        expected_roi = 12.5
        assert abs(metrics["roi_per_cycle"] - expected_roi) < 0.1


class TestDTEModes:
    """Test suite for DTE mode selection"""
    
    def test_weekly_dte_range(self):
        """Test weekly DTE range"""
        min_dte, max_dte = get_dte_range("weekly")
        
        assert min_dte == WEEKLY_MIN_DTE
        assert max_dte == WEEKLY_MAX_DTE
        assert max_dte <= 14  # Weekly should be <= 14 days
    
    def test_monthly_dte_range(self):
        """Test monthly DTE range"""
        min_dte, max_dte = get_dte_range("monthly")
        
        assert min_dte == MONTHLY_MIN_DTE
        assert max_dte == MONTHLY_MAX_DTE
        assert min_dte >= 15  # Monthly should start after weekly
    
    def test_all_dte_range(self):
        """Test 'all' DTE range covers both weekly and monthly"""
        min_dte, max_dte = get_dte_range("all")
        
        # Should cover from weekly min to monthly max
        assert min_dte == WEEKLY_MIN_DTE
        assert max_dte == MONTHLY_MAX_DTE


class TestSymbolHandling:
    """Test suite for symbol handling"""
    
    def test_goog_googl_both_present(self):
        """Test that both GOOG and GOOGL are in scan symbols"""
        assert "GOOG" in SCAN_SYMBOLS
        assert "GOOGL" in SCAN_SYMBOLS
    
    def test_goog_googl_distinct(self):
        """Test that GOOG and GOOGL are treated as separate symbols"""
        goog_count = SCAN_SYMBOLS.count("GOOG")
        googl_count = SCAN_SYMBOLS.count("GOOGL")
        
        # Each should appear exactly once
        assert goog_count == 1
        assert googl_count == 1


class TestPriceDiscrepancy:
    """Test suite for price discrepancy detection"""
    
    def test_no_discrepancy(self):
        """Test when prices are within threshold"""
        result = log_price_discrepancy(
            symbol="AAPL",
            source1_name="Source1",
            source1_price=150.00,
            source2_name="Source2",
            source2_price=150.10,
            threshold_pct=0.1
        )
        
        # 0.067% difference, should not trigger
        assert result == False
    
    def test_discrepancy_detected(self):
        """Test when prices exceed threshold"""
        result = log_price_discrepancy(
            symbol="AAPL",
            source1_name="Source1",
            source1_price=150.00,
            source2_name="Source2",
            source2_price=150.50,
            threshold_pct=0.1
        )
        
        # 0.33% difference, should trigger
        assert result == True
    
    def test_zero_price_handling(self):
        """Test handling of zero prices"""
        result = log_price_discrepancy(
            symbol="AAPL",
            source1_name="Source1",
            source1_price=0,
            source2_name="Source2",
            source2_price=150.00,
            threshold_pct=0.1
        )
        
        # Should not crash with zero prices
        assert result == False


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
