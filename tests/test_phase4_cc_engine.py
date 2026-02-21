"""
Phase 4 Covered Call Engine Tests
Tests for System Scan Filters, Single-Candidate Rule, and BID pricing

Features tested:
- Dashboard endpoint `/api/screener/dashboard-opportunities` returns opportunities with price in $30-$90 range
- Dashboard endpoint applies Single-Candidate Rule (one opportunity per symbol)
- Dashboard endpoint response includes `phase: 4` indicator
- Main screener `/api/screener/covered-calls?enforce_phase4=true` applies volume/market cap/earnings filters
- All opportunities use BID pricing (no zero premiums)
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_EMAIL = "admin@premiumhunter.com"
TEST_PASSWORD = "admin123"


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token for API calls"""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
    )
    if response.status_code == 200:
        data = response.json()
        # API returns access_token, not token
        return data.get("access_token")
    pytest.skip("Authentication failed - skipping tests")


@pytest.fixture(scope="module")
def api_client(auth_token):
    """Create authenticated session"""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_token}"
    })
    return session


class TestDashboardOpportunities:
    """Tests for /api/screener/dashboard-opportunities endpoint"""
    
    def test_dashboard_returns_phase4_indicator(self, api_client):
        """Dashboard response should include phase: 4"""
        response = api_client.get(f"{BASE_URL}/api/screener/dashboard-opportunities?bypass_cache=true")
        assert response.status_code == 200
        
        data = response.json()
        assert "phase" in data, "Response should include 'phase' field"
        assert data["phase"] == 4, f"Phase should be 4, got {data['phase']}"
    
    def test_dashboard_price_range_filter(self, api_client):
        """All opportunities should have stock_price in $30-$90 range"""
        response = api_client.get(f"{BASE_URL}/api/screener/dashboard-opportunities?bypass_cache=true")
        assert response.status_code == 200
        
        data = response.json()
        opportunities = data.get("opportunities", [])
        
        # Should have some opportunities
        assert len(opportunities) > 0, "Dashboard should return opportunities"
        
        # All prices should be in $30-$90 range
        for opp in opportunities:
            price = opp.get("stock_price", 0)
            assert 30 <= price <= 90, f"Stock price ${price} for {opp['symbol']} outside $30-$90 range"
    
    def test_dashboard_single_candidate_rule(self, api_client):
        """Each symbol should appear only once (single-candidate rule)"""
        response = api_client.get(f"{BASE_URL}/api/screener/dashboard-opportunities?bypass_cache=true")
        assert response.status_code == 200
        
        data = response.json()
        opportunities = data.get("opportunities", [])
        
        # Extract symbols
        symbols = [opp["symbol"] for opp in opportunities]
        unique_symbols = set(symbols)
        
        # Each symbol should appear exactly once
        assert len(symbols) == len(unique_symbols), \
            f"Duplicate symbols found: {[s for s in symbols if symbols.count(s) > 1]}"
    
    def test_dashboard_bid_pricing(self, api_client):
        """All opportunities should have BID pricing (no zero premiums)"""
        response = api_client.get(f"{BASE_URL}/api/screener/dashboard-opportunities?bypass_cache=true")
        assert response.status_code == 200
        
        data = response.json()
        opportunities = data.get("opportunities", [])
        
        for opp in opportunities:
            # Check bid field exists and is positive
            bid = opp.get("bid", 0)
            assert bid > 0, f"BID price for {opp['symbol']} should be > 0, got {bid}"
            
            # Premium should match bid
            premium = opp.get("premium", 0)
            assert premium > 0, f"Premium for {opp['symbol']} should be > 0, got {premium}"
    
    def test_dashboard_filters_applied_field(self, api_client):
        """Response should include filters_applied with Phase 4 system filters"""
        response = api_client.get(f"{BASE_URL}/api/screener/dashboard-opportunities?bypass_cache=true")
        assert response.status_code == 200
        
        data = response.json()
        
        assert "filters_applied" in data, "Response should include 'filters_applied'"
        filters = data["filters_applied"]
        
        # Verify system filter values
        assert filters.get("min_price") == 30, "min_price should be 30"
        assert filters.get("max_price") == 90, "max_price should be 90"
        assert filters.get("min_avg_volume") == 1_000_000, "min_avg_volume should be 1M"
        assert filters.get("min_market_cap") == 5_000_000_000, "min_market_cap should be $5B"
        assert filters.get("earnings_exclusion_days") == 7, "earnings_exclusion_days should be 7"
    
    def test_dashboard_dte_ranges(self, api_client):
        """Opportunities should be in Weekly (7-14 DTE) or Monthly (21-45 DTE) ranges"""
        response = api_client.get(f"{BASE_URL}/api/screener/dashboard-opportunities?bypass_cache=true")
        assert response.status_code == 200
        
        data = response.json()
        opportunities = data.get("opportunities", [])
        
        for opp in opportunities:
            dte = opp.get("dte", 0)
            expiry_type = opp.get("expiry_type", "")
            
            if expiry_type == "Weekly":
                assert 7 <= dte <= 14, f"Weekly DTE {dte} for {opp['symbol']} outside 7-14 range"
            elif expiry_type == "Monthly":
                assert 21 <= dte <= 45, f"Monthly DTE {dte} for {opp['symbol']} outside 21-45 range"
    
    def test_dashboard_otm_strikes(self, api_client):
        """All strikes should be OTM (2-10% above stock price)"""
        response = api_client.get(f"{BASE_URL}/api/screener/dashboard-opportunities?bypass_cache=true")
        assert response.status_code == 200
        
        data = response.json()
        opportunities = data.get("opportunities", [])
        
        for opp in opportunities:
            strike_pct = opp.get("strike_pct", 0)
            moneyness = opp.get("moneyness", "")
            
            # Should be OTM
            assert moneyness == "OTM", f"{opp['symbol']} should be OTM, got {moneyness}"
            
            # Strike percentage should be 2-10%
            assert 2 <= strike_pct <= 10, \
                f"Strike % {strike_pct} for {opp['symbol']} outside 2-10% OTM range"
    
    def test_dashboard_max_10_opportunities(self, api_client):
        """Dashboard should return max 10 opportunities"""
        response = api_client.get(f"{BASE_URL}/api/screener/dashboard-opportunities?bypass_cache=true")
        assert response.status_code == 200
        
        data = response.json()
        opportunities = data.get("opportunities", [])
        
        assert len(opportunities) <= 10, f"Dashboard should return max 10 opportunities, got {len(opportunities)}"


class TestMainScreenerPhase4:
    """Tests for /api/screener/covered-calls with enforce_phase4=true"""
    
    def test_screener_phase4_enabled(self, api_client):
        """Screener with enforce_phase4=true should return phase: 4"""
        response = api_client.get(
            f"{BASE_URL}/api/screener/covered-calls?enforce_phase4=true&bypass_cache=true"
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("phase") == 4, f"Phase should be 4 when enforce_phase4=true"
    
    def test_screener_phase4_disabled(self, api_client):
        """Screener with enforce_phase4=false should not return phase: 4"""
        response = api_client.get(
            f"{BASE_URL}/api/screener/covered-calls?enforce_phase4=false&bypass_cache=true"
        )
        assert response.status_code == 200
        
        data = response.json()
        # Phase should be None or not 4 when disabled
        assert data.get("phase") != 4 or data.get("phase") is None
    
    def test_screener_single_candidate_rule(self, api_client):
        """Each symbol should appear only once in screener results"""
        response = api_client.get(
            f"{BASE_URL}/api/screener/covered-calls?enforce_phase4=true&bypass_cache=true"
        )
        assert response.status_code == 200
        
        data = response.json()
        opportunities = data.get("opportunities", [])
        
        symbols = [opp["symbol"] for opp in opportunities]
        unique_symbols = set(symbols)
        
        assert len(symbols) == len(unique_symbols), \
            f"Duplicate symbols found in screener: {[s for s in symbols if symbols.count(s) > 1]}"
    
    def test_screener_bid_pricing(self, api_client):
        """All screener opportunities should have positive premiums (BID pricing)"""
        response = api_client.get(
            f"{BASE_URL}/api/screener/covered-calls?enforce_phase4=true&bypass_cache=true"
        )
        assert response.status_code == 200
        
        data = response.json()
        opportunities = data.get("opportunities", [])
        
        for opp in opportunities:
            premium = opp.get("premium", 0)
            assert premium > 0, f"Premium for {opp['symbol']} should be > 0, got {premium}"
    
    def test_screener_stocks_price_filter(self, api_client):
        """Non-ETF stocks should be in $30-$90 range when enforce_phase4=true"""
        response = api_client.get(
            f"{BASE_URL}/api/screener/covered-calls?enforce_phase4=true&bypass_cache=true&min_price=30&max_price=90"
        )
        assert response.status_code == 200
        
        data = response.json()
        opportunities = data.get("opportunities", [])
        
        # ETF symbols that are exempt from price filter
        etf_symbols = {"SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK", "XLV", "XLI", "XLB", "XLU", "XLP", "XLY"}
        
        for opp in opportunities:
            symbol = opp.get("symbol", "")
            price = opp.get("stock_price", 0)
            
            # ETFs are exempt from price filter
            if symbol not in etf_symbols:
                assert 30 <= price <= 90, \
                    f"Stock {symbol} price ${price} outside $30-$90 range"


class TestAuthenticationRequired:
    """Tests to verify authentication is required"""
    
    def test_dashboard_requires_auth(self):
        """Dashboard endpoint should require authentication"""
        response = requests.get(f"{BASE_URL}/api/screener/dashboard-opportunities")
        assert response.status_code == 401 or response.status_code == 403
    
    def test_screener_requires_auth(self):
        """Screener endpoint should require authentication"""
        response = requests.get(f"{BASE_URL}/api/screener/covered-calls")
        assert response.status_code == 401 or response.status_code == 403


class TestDataQuality:
    """Tests for data quality and consistency"""
    
    def test_dashboard_roi_calculation(self, api_client):
        """ROI should be calculated correctly (premium / stock_price * 100)"""
        response = api_client.get(f"{BASE_URL}/api/screener/dashboard-opportunities?bypass_cache=true")
        assert response.status_code == 200
        
        data = response.json()
        opportunities = data.get("opportunities", [])
        
        for opp in opportunities:
            premium = opp.get("premium", 0)
            stock_price = opp.get("stock_price", 0)
            roi_pct = opp.get("roi_pct", 0)
            
            if stock_price > 0:
                expected_roi = (premium / stock_price) * 100
                # Allow small floating point difference
                assert abs(roi_pct - expected_roi) < 0.1, \
                    f"ROI mismatch for {opp['symbol']}: expected {expected_roi:.2f}, got {roi_pct}"
    
    def test_dashboard_has_required_fields(self, api_client):
        """Each opportunity should have all required fields"""
        response = api_client.get(f"{BASE_URL}/api/screener/dashboard-opportunities?bypass_cache=true")
        assert response.status_code == 200
        
        data = response.json()
        opportunities = data.get("opportunities", [])
        
        required_fields = [
            "symbol", "stock_price", "strike", "expiry", "dte",
            "premium", "bid", "roi_pct", "delta", "iv", "open_interest", "score"
        ]
        
        for opp in opportunities:
            for field in required_fields:
                assert field in opp, f"Missing field '{field}' in opportunity for {opp.get('symbol', 'unknown')}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
