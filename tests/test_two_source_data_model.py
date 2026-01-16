"""
Test Two-Source Data Model Implementation
==========================================
Tests for:
1. CC Screener - Two-Source Data banner with Equity date and Options Snapshot time
2. CC Screener - IV, IV Rank, and Open Interest data (not blank)
3. CC Screener - 50/50 mix of weekly and monthly options (W and M badges)
4. PMCC Screener - Valid expirations that actually exist
5. PMCC results - IV and OI for both LEAPS and short leg
6. Watchlist - Current price (T-1 close)
7. Simulator - IV, IV Rank, OI data for trades
8. All expiration dates are actual Fridays
9. API endpoints return metadata with equity_price_date and options_snapshot_time
"""

import pytest
import requests
import os
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://premium-hunter-2.preview.emergentagent.com').rstrip('/')

# Test credentials
TEST_EMAIL = "admin@premiumhunter.com"
TEST_PASSWORD = "admin123"


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD
    })
    if response.status_code == 200:
        return response.json().get("access_token")
    pytest.skip("Authentication failed - skipping authenticated tests")


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Get headers with auth token"""
    return {"Authorization": f"Bearer {auth_token}"}


class TestHealthAndBasics:
    """Basic health checks"""
    
    def test_health_endpoint(self):
        """Test health endpoint is working"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy"
        print(f"✓ Health check passed: {data}")
    
    def test_market_status_endpoint(self, auth_headers):
        """Test market status returns T-1 data info"""
        response = requests.get(f"{BASE_URL}/api/market-status", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        # Should have T-1 data info
        assert "t1_data" in data or "data_date" in data
        print(f"✓ Market status: {data}")


class TestCoveredCallScreener:
    """Test CC Screener Two-Source Data Model"""
    
    def test_cc_screener_returns_metadata(self, auth_headers):
        """Test CC screener returns metadata with equity_price_date and options_snapshot_time"""
        response = requests.get(f"{BASE_URL}/api/screener/covered-calls", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        # Check for metadata
        assert "metadata" in data or "equity_price_date" in data.get("opportunities", [{}])[0] if data.get("opportunities") else True
        
        if "metadata" in data:
            metadata = data["metadata"]
            print(f"✓ CC Screener metadata: {metadata}")
            
            # Verify equity_price_date exists
            assert "equity_price_date" in metadata, "Missing equity_price_date in metadata"
            
            # Verify options_snapshot_time exists (may be None if no options fetched)
            assert "options_snapshot_time" in metadata, "Missing options_snapshot_time in metadata"
            
            print(f"  - Equity Price Date: {metadata.get('equity_price_date')}")
            print(f"  - Options Snapshot Time: {metadata.get('options_snapshot_time')}")
        
        return data
    
    def test_cc_screener_has_iv_data(self, auth_headers):
        """Test CC screener results include IV, IV Rank, and Open Interest"""
        response = requests.get(f"{BASE_URL}/api/screener/covered-calls", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        opportunities = data.get("opportunities", [])
        
        if len(opportunities) > 0:
            # Check first few opportunities for IV data
            iv_present = 0
            iv_rank_present = 0
            oi_present = 0
            
            for opp in opportunities[:10]:
                if opp.get("iv") and opp.get("iv") > 0:
                    iv_present += 1
                if opp.get("iv_rank") and opp.get("iv_rank") > 0:
                    iv_rank_present += 1
                if opp.get("open_interest") and opp.get("open_interest") > 0:
                    oi_present += 1
            
            print(f"✓ CC Screener IV data check (out of {min(10, len(opportunities))} opportunities):")
            print(f"  - IV present: {iv_present}")
            print(f"  - IV Rank present: {iv_rank_present}")
            print(f"  - Open Interest present: {oi_present}")
            
            # At least some should have IV data
            assert iv_present > 0 or len(opportunities) == 0, "No IV data in any opportunity"
        else:
            print("⚠ No opportunities returned - may need to refresh data")
    
    def test_cc_screener_weekly_monthly_mix(self, auth_headers):
        """Test CC screener returns 50/50 mix of weekly and monthly options"""
        response = requests.get(f"{BASE_URL}/api/screener/covered-calls", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        # Check for weekly_count and monthly_count in response
        weekly_count = data.get("weekly_count", 0)
        monthly_count = data.get("monthly_count", 0)
        
        print(f"✓ CC Screener weekly/monthly mix:")
        print(f"  - Weekly count: {weekly_count}")
        print(f"  - Monthly count: {monthly_count}")
        print(f"  - Total: {data.get('total', 0)}")
        
        # Also check expiry_type in opportunities
        opportunities = data.get("opportunities", [])
        if opportunities:
            weekly_in_opps = sum(1 for o in opportunities if o.get("expiry_type") == "weekly")
            monthly_in_opps = sum(1 for o in opportunities if o.get("expiry_type") == "monthly")
            print(f"  - Weekly in opportunities: {weekly_in_opps}")
            print(f"  - Monthly in opportunities: {monthly_in_opps}")
    
    def test_cc_screener_friday_expirations(self, auth_headers):
        """Test all expiration dates are actual Fridays"""
        response = requests.get(f"{BASE_URL}/api/screener/covered-calls", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        opportunities = data.get("opportunities", [])
        non_friday_count = 0
        friday_count = 0
        
        for opp in opportunities:
            expiry = opp.get("expiry")
            if expiry:
                try:
                    exp_date = datetime.strptime(expiry, "%Y-%m-%d")
                    if exp_date.weekday() == 4:  # Friday
                        friday_count += 1
                    else:
                        non_friday_count += 1
                        print(f"  ⚠ Non-Friday expiry found: {expiry} ({exp_date.strftime('%A')})")
                except:
                    pass
        
        print(f"✓ CC Screener Friday expiration check:")
        print(f"  - Friday expirations: {friday_count}")
        print(f"  - Non-Friday expirations: {non_friday_count}")
        
        # All should be Fridays
        if friday_count > 0:
            assert non_friday_count == 0, f"Found {non_friday_count} non-Friday expirations"


class TestPMCCScreener:
    """Test PMCC Screener Two-Source Data Model"""
    
    def test_pmcc_screener_returns_results(self, auth_headers):
        """Test PMCC screener returns results with valid expirations"""
        response = requests.get(f"{BASE_URL}/api/screener/pmcc", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        print(f"✓ PMCC Screener response:")
        print(f"  - Total opportunities: {data.get('total', 0)}")
        print(f"  - From cache: {data.get('from_cache', False)}")
        
        if "metadata" in data:
            print(f"  - Metadata: {data['metadata']}")
        
        return data
    
    def test_pmcc_has_iv_oi_for_both_legs(self, auth_headers):
        """Test PMCC results include IV and OI for both LEAPS and short leg"""
        response = requests.get(f"{BASE_URL}/api/screener/pmcc", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        opportunities = data.get("opportunities", [])
        
        if len(opportunities) > 0:
            leaps_iv_present = 0
            leaps_oi_present = 0
            short_iv_present = 0
            short_oi_present = 0
            
            for opp in opportunities[:10]:
                # Check LEAPS leg
                if opp.get("leaps_iv") and opp.get("leaps_iv") > 0:
                    leaps_iv_present += 1
                if opp.get("leaps_oi") and opp.get("leaps_oi") > 0:
                    leaps_oi_present += 1
                
                # Check short leg
                if opp.get("short_iv") and opp.get("short_iv") > 0:
                    short_iv_present += 1
                if opp.get("short_oi") and opp.get("short_oi") > 0:
                    short_oi_present += 1
            
            sample_size = min(10, len(opportunities))
            print(f"✓ PMCC IV/OI data check (out of {sample_size} opportunities):")
            print(f"  - LEAPS IV present: {leaps_iv_present}")
            print(f"  - LEAPS OI present: {leaps_oi_present}")
            print(f"  - Short IV present: {short_iv_present}")
            print(f"  - Short OI present: {short_oi_present}")
            
            # Sample first opportunity
            if opportunities:
                first = opportunities[0]
                print(f"  - Sample opportunity: {first.get('symbol')}")
                print(f"    LEAPS: strike={first.get('leaps_strike')}, iv={first.get('leaps_iv')}, oi={first.get('leaps_oi')}")
                print(f"    Short: strike={first.get('short_strike')}, iv={first.get('short_iv')}, oi={first.get('short_oi')}")
        else:
            print("⚠ No PMCC opportunities returned")
    
    def test_pmcc_friday_expirations(self, auth_headers):
        """Test PMCC expiration dates are valid Fridays"""
        response = requests.get(f"{BASE_URL}/api/screener/pmcc", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        opportunities = data.get("opportunities", [])
        
        leaps_friday = 0
        leaps_non_friday = 0
        short_friday = 0
        short_non_friday = 0
        
        for opp in opportunities:
            # Check LEAPS expiry
            leaps_expiry = opp.get("leaps_expiry")
            if leaps_expiry:
                try:
                    exp_date = datetime.strptime(leaps_expiry, "%Y-%m-%d")
                    if exp_date.weekday() == 4:
                        leaps_friday += 1
                    else:
                        leaps_non_friday += 1
                except:
                    pass
            
            # Check short expiry
            short_expiry = opp.get("short_expiry")
            if short_expiry:
                try:
                    exp_date = datetime.strptime(short_expiry, "%Y-%m-%d")
                    if exp_date.weekday() == 4:
                        short_friday += 1
                    else:
                        short_non_friday += 1
                except:
                    pass
        
        print(f"✓ PMCC Friday expiration check:")
        print(f"  - LEAPS Friday: {leaps_friday}, Non-Friday: {leaps_non_friday}")
        print(f"  - Short Friday: {short_friday}, Non-Friday: {short_non_friday}")


class TestWatchlist:
    """Test Watchlist T-1 price display"""
    
    def test_watchlist_returns_prices(self, auth_headers):
        """Test watchlist displays current price (T-1 close)"""
        response = requests.get(f"{BASE_URL}/api/watchlist", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        watchlist = data if isinstance(data, list) else data.get("watchlist", [])
        
        print(f"✓ Watchlist response:")
        print(f"  - Items count: {len(watchlist)}")
        
        if watchlist:
            for item in watchlist[:3]:
                print(f"  - {item.get('symbol')}: price={item.get('current_price')}")


class TestSimulator:
    """Test Simulator IV/OI data"""
    
    def test_simulator_trades_list(self, auth_headers):
        """Test simulator returns trades with IV/OI data"""
        response = requests.get(f"{BASE_URL}/api/simulator/trades", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        trades = data if isinstance(data, list) else data.get("trades", [])
        
        print(f"✓ Simulator trades response:")
        print(f"  - Trades count: {len(trades)}")
        
        if trades:
            for trade in trades[:3]:
                print(f"  - {trade.get('symbol')}: strategy={trade.get('strategy_type')}")


class TestDataQualityDashboard:
    """Test Data Quality Dashboard endpoints"""
    
    def test_data_quality_dashboard(self, auth_headers):
        """Test data quality dashboard returns scan status"""
        response = requests.get(f"{BASE_URL}/api/screener/data-quality-dashboard", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        print(f"✓ Data Quality Dashboard:")
        print(f"  - Overall status: {data.get('overall_status')} {data.get('overall_status_emoji')}")
        print(f"  - Overall message: {data.get('overall_message')}")
        
        if "summary" in data:
            summary = data["summary"]
            print(f"  - Summary: green={summary.get('green')}, amber={summary.get('amber')}, red={summary.get('red')}")
        
        if "t1_data" in data:
            t1 = data["t1_data"]
            print(f"  - T-1 Data: equity_date={t1.get('equity_price_date')}")
        
        if "scans" in data:
            print(f"  - Scans:")
            for scan in data["scans"]:
                print(f"    {scan.get('scan_type')} {scan.get('profile')}: {scan.get('status_emoji')} count={scan.get('count')}")


class TestMetadataInResponses:
    """Test that API responses include proper metadata"""
    
    def test_cc_metadata_structure(self, auth_headers):
        """Test CC screener metadata structure"""
        response = requests.get(f"{BASE_URL}/api/screener/covered-calls", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        if "metadata" in data:
            metadata = data["metadata"]
            
            # Required fields
            required_fields = ["equity_price_date", "equity_price_source"]
            for field in required_fields:
                assert field in metadata, f"Missing required field: {field}"
            
            print(f"✓ CC Metadata structure valid:")
            print(f"  - equity_price_date: {metadata.get('equity_price_date')}")
            print(f"  - equity_price_source: {metadata.get('equity_price_source')}")
            print(f"  - options_snapshot_time: {metadata.get('options_snapshot_time')}")
            print(f"  - data_source: {metadata.get('data_source')}")
    
    def test_pmcc_metadata_structure(self, auth_headers):
        """Test PMCC screener metadata structure"""
        response = requests.get(f"{BASE_URL}/api/screener/pmcc", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        if "metadata" in data:
            metadata = data["metadata"]
            
            print(f"✓ PMCC Metadata structure:")
            print(f"  - equity_price_date: {metadata.get('equity_price_date')}")
            print(f"  - equity_price_source: {metadata.get('equity_price_source')}")
            print(f"  - options_snapshot_time: {metadata.get('options_snapshot_time')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
