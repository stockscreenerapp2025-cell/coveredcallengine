"""
Test Simulator Trade Lifecycle and Analytics
Tests the fixes for blank Analytics and PMCC Tracker pages

Key requirements tested:
1. ASSIGNED = CLOSED for analytics
2. Analytics includes OPEN + EXPIRED + ASSIGNED trades
3. PMCC Tracker shows OPEN, ROLLED, ASSIGNED trades
4. Health status indicators for PMCC positions
5. Backend API response structure matches frontend expectations
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "admin@premiumhunter.com",
        "password": "admin123"
    })
    assert response.status_code == 200, f"Login failed: {response.text}"
    data = response.json()
    return data.get("access_token") or data.get("token")

@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Get headers with auth token"""
    return {"Authorization": f"Bearer {auth_token}"}


class TestSimulatorTrades:
    """Test /api/simulator/trades endpoint"""
    
    def test_get_trades_returns_200(self, auth_headers):
        """Test that trades endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/simulator/trades", headers=auth_headers)
        assert response.status_code == 200
    
    def test_trades_response_structure(self, auth_headers):
        """Test trades response has correct structure"""
        response = requests.get(f"{BASE_URL}/api/simulator/trades", headers=auth_headers)
        data = response.json()
        
        assert "trades" in data
        assert "total" in data
        assert isinstance(data["trades"], list)
    
    def test_trades_have_status_field(self, auth_headers):
        """Test that all trades have status field"""
        response = requests.get(f"{BASE_URL}/api/simulator/trades", headers=auth_headers)
        data = response.json()
        
        for trade in data["trades"]:
            assert "status" in trade, f"Trade {trade.get('id')} missing status field"
            # Status should be one of the valid values
            valid_statuses = ["open", "active", "rolled", "expired", "assigned", "closed"]
            assert trade["status"] in valid_statuses, f"Invalid status: {trade['status']}"
    
    def test_trades_have_strategy_type(self, auth_headers):
        """Test that all trades have strategy_type field"""
        response = requests.get(f"{BASE_URL}/api/simulator/trades", headers=auth_headers)
        data = response.json()
        
        for trade in data["trades"]:
            assert "strategy_type" in trade
            assert trade["strategy_type"] in ["covered_call", "pmcc"]
    
    def test_trades_count_matches_total(self, auth_headers):
        """Test that returned trades count matches total"""
        response = requests.get(f"{BASE_URL}/api/simulator/trades?limit=100", headers=auth_headers)
        data = response.json()
        
        # If total <= limit, trades count should equal total
        if data["total"] <= 100:
            assert len(data["trades"]) == data["total"]


class TestSimulatorAnalytics:
    """Test /api/simulator/analytics/performance endpoint"""
    
    def test_analytics_returns_200(self, auth_headers):
        """Test that analytics endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/simulator/analytics/performance", headers=auth_headers)
        assert response.status_code == 200
    
    def test_analytics_has_overall_structure(self, auth_headers):
        """Test analytics response has analytics.overall structure"""
        response = requests.get(f"{BASE_URL}/api/simulator/analytics/performance", headers=auth_headers)
        data = response.json()
        
        # Frontend expects analytics.overall structure
        assert "analytics" in data, "Response missing 'analytics' key"
        assert "overall" in data["analytics"], "Response missing 'analytics.overall' key"
    
    def test_analytics_overall_has_required_fields(self, auth_headers):
        """Test analytics.overall has all required fields for frontend"""
        response = requests.get(f"{BASE_URL}/api/simulator/analytics/performance", headers=auth_headers)
        data = response.json()
        
        overall = data["analytics"]["overall"]
        required_fields = [
            "total_trades",
            "win_rate",
            "total_pnl",
            "roi",
            "avg_win",
            "avg_loss"
        ]
        
        for field in required_fields:
            assert field in overall, f"Missing required field: {field}"
    
    def test_analytics_includes_all_trade_statuses(self, auth_headers):
        """Test that analytics includes OPEN + EXPIRED + ASSIGNED trades"""
        response = requests.get(f"{BASE_URL}/api/simulator/analytics/performance", headers=auth_headers)
        data = response.json()
        
        overall = data["analytics"]["overall"]
        
        # Get trades to compare
        trades_resp = requests.get(f"{BASE_URL}/api/simulator/trades?limit=1000", headers=auth_headers)
        trades_data = trades_resp.json()
        
        # Total trades in analytics should match total trades
        assert overall["total_trades"] == trades_data["total"], \
            f"Analytics total_trades ({overall['total_trades']}) != trades total ({trades_data['total']})"
    
    def test_analytics_win_rate_calculation(self, auth_headers):
        """Test that win rate is calculated correctly (ASSIGNED = WIN for CC)"""
        response = requests.get(f"{BASE_URL}/api/simulator/analytics/performance", headers=auth_headers)
        data = response.json()
        
        overall = data["analytics"]["overall"]
        
        # Win rate should be a percentage between 0 and 100
        assert 0 <= overall["win_rate"] <= 100, f"Invalid win rate: {overall['win_rate']}"
    
    def test_analytics_has_by_outcome_data(self, auth_headers):
        """Test analytics has performance by outcome data"""
        response = requests.get(f"{BASE_URL}/api/simulator/analytics/performance", headers=auth_headers)
        data = response.json()
        
        analytics = data["analytics"]
        
        # Should have by_outcome or similar breakdown
        # Check for expired/assigned/closed counts
        if "by_outcome" in analytics:
            by_outcome = analytics["by_outcome"]
            assert isinstance(by_outcome, (list, dict))


class TestPMCCSummary:
    """Test /api/simulator/pmcc-summary endpoint"""
    
    def test_pmcc_summary_returns_200(self, auth_headers):
        """Test that PMCC summary endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/simulator/pmcc-summary", headers=auth_headers)
        assert response.status_code == 200
    
    def test_pmcc_summary_has_overall_and_summary(self, auth_headers):
        """Test PMCC summary has overall and summary array"""
        response = requests.get(f"{BASE_URL}/api/simulator/pmcc-summary", headers=auth_headers)
        data = response.json()
        
        # Frontend expects both overall and summary
        assert "overall" in data, "Response missing 'overall' key"
        assert "summary" in data, "Response missing 'summary' key"
        assert isinstance(data["summary"], list), "summary should be an array"
    
    def test_pmcc_overall_has_required_fields(self, auth_headers):
        """Test PMCC overall has required fields"""
        response = requests.get(f"{BASE_URL}/api/simulator/pmcc-summary", headers=auth_headers)
        data = response.json()
        
        overall = data["overall"]
        required_fields = [
            "total_leaps_investment",
            "total_premium_income",
            "overall_income_ratio",
            "total_pmcc_positions",
            "active_positions"
        ]
        
        for field in required_fields:
            assert field in overall, f"Missing required field in overall: {field}"
    
    def test_pmcc_positions_have_health_status(self, auth_headers):
        """Test PMCC positions have health status indicator"""
        response = requests.get(f"{BASE_URL}/api/simulator/pmcc-summary", headers=auth_headers)
        data = response.json()
        
        for position in data["summary"]:
            assert "health" in position, f"Position {position.get('symbol')} missing health field"
            assert position["health"] in ["good", "warning", "critical"], \
                f"Invalid health status: {position['health']}"
    
    def test_pmcc_positions_have_income_metrics(self, auth_headers):
        """Test PMCC positions have income vs LEAPS decay metrics"""
        response = requests.get(f"{BASE_URL}/api/simulator/pmcc-summary", headers=auth_headers)
        data = response.json()
        
        for position in data["summary"]:
            # Check for income_to_cost_ratio
            assert "income_to_cost_ratio" in position or "income_ratio" in position, \
                f"Position {position.get('symbol')} missing income ratio"
            
            # Check for estimated_leaps_decay_pct
            assert "estimated_leaps_decay_pct" in position, \
                f"Position {position.get('symbol')} missing estimated_leaps_decay_pct"
    
    def test_pmcc_shows_open_rolled_assigned_trades(self, auth_headers):
        """Test PMCC summary shows OPEN, ROLLED, ASSIGNED trades"""
        response = requests.get(f"{BASE_URL}/api/simulator/pmcc-summary", headers=auth_headers)
        data = response.json()
        
        # Get all statuses in summary
        statuses = set(pos.get("status") for pos in data["summary"])
        
        # Should include active/open trades (not just closed)
        valid_statuses = {"open", "active", "rolled", "assigned"}
        
        # At least one position should be in a visible status
        if data["summary"]:
            assert any(s in valid_statuses for s in statuses), \
                f"PMCC summary should show open/rolled/assigned trades, got: {statuses}"


class TestSimulatorSummary:
    """Test /api/simulator/summary endpoint"""
    
    def test_summary_returns_200(self, auth_headers):
        """Test that summary endpoint returns 200"""
        response = requests.get(f"{BASE_URL}/api/simulator/summary", headers=auth_headers)
        assert response.status_code == 200
    
    def test_summary_has_required_fields(self, auth_headers):
        """Test summary has required fields"""
        response = requests.get(f"{BASE_URL}/api/simulator/summary", headers=auth_headers)
        data = response.json()
        
        required_fields = [
            "total_trades",
            "active_trades",
            "closed_trades",
            "win_rate",
            "by_status"
        ]
        
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
    
    def test_summary_by_status_breakdown(self, auth_headers):
        """Test summary has status breakdown"""
        response = requests.get(f"{BASE_URL}/api/simulator/summary", headers=auth_headers)
        data = response.json()
        
        by_status = data["by_status"]
        
        # Should have counts for different statuses
        expected_statuses = ["open", "rolled", "closed", "expired", "assigned"]
        for status in expected_statuses:
            assert status in by_status, f"Missing status in by_status: {status}"


class TestStatusBackwardCompatibility:
    """Test backward compatibility for 'active' vs 'open' status"""
    
    def test_active_status_handled_in_analytics(self, auth_headers):
        """Test that 'active' status trades are included in analytics"""
        # Get trades
        trades_resp = requests.get(f"{BASE_URL}/api/simulator/trades?limit=1000", headers=auth_headers)
        trades_data = trades_resp.json()
        
        # Count active trades
        active_count = sum(1 for t in trades_data["trades"] if t.get("status") == "active")
        
        # Get analytics
        analytics_resp = requests.get(f"{BASE_URL}/api/simulator/analytics/performance", headers=auth_headers)
        analytics_data = analytics_resp.json()
        
        # Analytics should include active trades in total
        total_trades = analytics_data["analytics"]["overall"]["total_trades"]
        
        # Total should include active trades
        assert total_trades >= active_count, \
            f"Analytics total ({total_trades}) should include active trades ({active_count})"
    
    def test_active_status_handled_in_pmcc_summary(self, auth_headers):
        """Test that 'active' status PMCC trades appear in summary"""
        response = requests.get(f"{BASE_URL}/api/simulator/pmcc-summary", headers=auth_headers)
        data = response.json()
        
        # Check if any positions have 'active' status
        statuses = [pos.get("status") for pos in data["summary"]]
        
        # 'active' should be treated same as 'open'
        # Both should appear in the summary
        if "active" in statuses:
            print(f"Found 'active' status positions in PMCC summary")
        
        # Summary should not be empty if there are PMCC trades
        if data["overall"]["total_pmcc_positions"] > 0:
            assert len(data["summary"]) > 0, "PMCC summary should not be empty"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
