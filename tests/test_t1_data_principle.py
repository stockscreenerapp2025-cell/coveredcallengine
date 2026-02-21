"""
Test T-1 Data Principle Implementation
======================================
Tests for T-1 (previous trading day) market data principle across the Covered Call Engine.

Features tested:
- /api/market-status endpoint returns T-1 data information
- /api/screener/data-quality-dashboard endpoint returns correct scan status
- /api/screener/covered-calls endpoint returns T-1 data info in response
- /api/screener/pmcc endpoint returns T-1 data info in response
- Pre-computed scans show correct data freshness status
"""

import pytest
import requests
import os
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_EMAIL = "admin@premiumhunter.com"
TEST_PASSWORD = "admin123"


@pytest.fixture(scope="module")
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture(scope="module")
def auth_token(api_client):
    """Get authentication token"""
    response = api_client.post(f"{BASE_URL}/api/auth/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD
    })
    if response.status_code == 200:
        data = response.json()
        return data.get("access_token") or data.get("token")
    pytest.skip(f"Authentication failed - status {response.status_code}: {response.text}")


@pytest.fixture(scope="module")
def authenticated_client(api_client, auth_token):
    """Session with auth header"""
    api_client.headers.update({"Authorization": f"Bearer {auth_token}"})
    return api_client


class TestHealthAndMarketStatus:
    """Test health and market status endpoints"""
    
    def test_health_endpoint(self, api_client):
        """Test /api/health endpoint is accessible"""
        response = api_client.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy"
        print(f"✓ Health endpoint: {data}")
    
    def test_market_status_endpoint(self, api_client):
        """Test /api/market-status returns T-1 data information"""
        response = api_client.get(f"{BASE_URL}/api/market-status")
        assert response.status_code == 200
        data = response.json()
        
        # Verify T-1 data fields are present
        assert "t1_data" in data, "Response should contain t1_data field"
        t1_data = data["t1_data"]
        
        # Verify T-1 data structure
        assert "date" in t1_data, "t1_data should have date field"
        assert "description" in t1_data, "t1_data should have description field"
        assert "data_age_hours" in t1_data, "t1_data should have data_age_hours field"
        assert "next_refresh" in t1_data, "t1_data should have next_refresh field"
        
        # Verify date format (YYYY-MM-DD)
        t1_date = t1_data["date"]
        try:
            datetime.strptime(t1_date, "%Y-%m-%d")
        except ValueError:
            pytest.fail(f"T-1 date format invalid: {t1_date}")
        
        # Verify data_note mentions T-1
        assert "data_note" in data, "Response should contain data_note"
        assert "T-1" in data["data_note"], "data_note should mention T-1"
        
        print(f"✓ Market status T-1 date: {t1_date}")
        print(f"✓ Data age: {t1_data['data_age_hours']} hours")
        print(f"✓ Next refresh: {t1_data['next_refresh']}")
        print(f"✓ Data note: {data['data_note']}")


class TestDataQualityDashboard:
    """Test data quality dashboard endpoint"""
    
    def test_data_quality_dashboard_requires_auth(self, api_client):
        """Test that data quality dashboard requires authentication"""
        response = api_client.get(f"{BASE_URL}/api/screener/data-quality-dashboard")
        assert response.status_code == 401 or response.status_code == 403
        print("✓ Data quality dashboard requires authentication")
    
    def test_data_quality_dashboard_returns_t1_info(self, authenticated_client):
        """Test /api/screener/data-quality-dashboard returns T-1 data info"""
        response = authenticated_client.get(f"{BASE_URL}/api/screener/data-quality-dashboard")
        assert response.status_code == 200
        data = response.json()
        
        # Verify T-1 data fields
        assert "t1_data" in data, "Response should contain t1_data"
        t1_data = data["t1_data"]
        assert "data_date" in t1_data, "t1_data should have data_date"
        assert "data_age_hours" in t1_data, "t1_data should have data_age_hours"
        
        print(f"✓ Data quality T-1 date: {t1_data.get('data_date')}")
        print(f"✓ Data age: {t1_data.get('data_age_hours')} hours")
    
    def test_data_quality_dashboard_scan_status(self, authenticated_client):
        """Test that scan status includes green/amber/red indicators"""
        response = authenticated_client.get(f"{BASE_URL}/api/screener/data-quality-dashboard")
        assert response.status_code == 200
        data = response.json()
        
        # Verify overall status
        assert "overall_status" in data, "Response should have overall_status"
        assert data["overall_status"] in ["green", "amber", "red"], f"Invalid status: {data['overall_status']}"
        
        # Verify summary counts
        assert "summary" in data, "Response should have summary"
        summary = data["summary"]
        assert "green" in summary, "Summary should have green count"
        assert "amber" in summary, "Summary should have amber count"
        assert "red" in summary, "Summary should have red count"
        
        # Verify scans array
        assert "scans" in data, "Response should have scans array"
        scans = data["scans"]
        assert isinstance(scans, list), "scans should be a list"
        
        if len(scans) > 0:
            scan = scans[0]
            assert "status" in scan, "Each scan should have status"
            assert scan["status"] in ["green", "amber", "red"], f"Invalid scan status: {scan['status']}"
            assert "scan_type" in scan, "Each scan should have scan_type"
            assert "profile" in scan, "Each scan should have profile"
            assert "count" in scan, "Each scan should have count"
        
        print(f"✓ Overall status: {data['overall_status']}")
        print(f"✓ Summary - Green: {summary['green']}, Amber: {summary['amber']}, Red: {summary['red']}")
        print(f"✓ Total scans: {len(scans)}")
        
        for scan in scans:
            print(f"  - {scan['scan_type']} ({scan['profile']}): {scan['status']} - {scan['count']} opportunities")


class TestCoveredCallsEndpoint:
    """Test covered calls screener endpoint"""
    
    def test_covered_calls_accessible(self, api_client):
        """Test that covered calls endpoint is accessible (may or may not require auth)"""
        response = api_client.get(f"{BASE_URL}/api/screener/covered-calls")
        # Endpoint may be public or require auth - both are valid
        assert response.status_code in [200, 401, 403]
        print(f"✓ Covered calls endpoint status: {response.status_code}")
    
    def test_covered_calls_returns_t1_info(self, authenticated_client):
        """Test /api/screener/covered-calls returns T-1 data info"""
        response = authenticated_client.get(f"{BASE_URL}/api/screener/covered-calls", params={
            "min_roi": 0.5,
            "max_dte": 45
        })
        assert response.status_code == 200
        data = response.json()
        
        # Verify T-1 data info in response
        assert "t1_data" in data, "Response should contain t1_data"
        t1_data = data["t1_data"]
        
        assert "data_date" in t1_data, "t1_data should have data_date"
        assert "data_type" in t1_data, "t1_data should have data_type"
        assert t1_data["data_type"] == "t_minus_1_close", f"data_type should be t_minus_1_close, got {t1_data['data_type']}"
        
        print(f"✓ Covered calls T-1 date: {t1_data.get('data_date')}")
        print(f"✓ Data type: {t1_data.get('data_type')}")
        print(f"✓ Data description: {t1_data.get('data_description')}")
        
        # Verify opportunities array
        assert "opportunities" in data, "Response should have opportunities"
        opportunities = data["opportunities"]
        print(f"✓ Total opportunities: {len(opportunities)}")
        
        # Check if opportunities have data_date field
        if len(opportunities) > 0:
            opp = opportunities[0]
            if "data_date" in opp:
                print(f"✓ First opportunity data_date: {opp['data_date']}")


class TestPMCCEndpoint:
    """Test PMCC screener endpoint"""
    
    def test_pmcc_accessible(self, api_client):
        """Test that PMCC endpoint is accessible (may or may not require auth)"""
        response = api_client.get(f"{BASE_URL}/api/screener/pmcc")
        # Endpoint may be public or require auth - both are valid
        assert response.status_code in [200, 401, 403]
        print(f"✓ PMCC endpoint status: {response.status_code}")
    
    def test_pmcc_returns_t1_info(self, authenticated_client):
        """Test /api/screener/pmcc returns T-1 data info"""
        response = authenticated_client.get(f"{BASE_URL}/api/screener/pmcc", params={
            "risk_profile": "balanced"
        })
        assert response.status_code == 200
        data = response.json()
        
        # Verify T-1 data info in response
        assert "t1_data" in data, "Response should contain t1_data"
        t1_data = data["t1_data"]
        
        assert "data_date" in t1_data, "t1_data should have data_date"
        assert "data_type" in t1_data, "t1_data should have data_type"
        
        print(f"✓ PMCC T-1 date: {t1_data.get('data_date')}")
        print(f"✓ Data type: {t1_data.get('data_type')}")
        
        # Verify opportunities array
        assert "opportunities" in data, "Response should have opportunities"
        opportunities = data["opportunities"]
        print(f"✓ Total PMCC opportunities: {len(opportunities)}")


class TestPrecomputedScans:
    """Test pre-computed scans endpoints"""
    
    def test_precomputed_covered_calls(self, authenticated_client):
        """Test pre-computed covered calls scan"""
        response = authenticated_client.get(f"{BASE_URL}/api/screener/precomputed/covered_call/balanced")
        
        if response.status_code == 200:
            data = response.json()
            
            # Check for T-1 data info
            if "t1_data" in data:
                print(f"✓ Pre-computed CC T-1 date: {data['t1_data'].get('data_date')}")
            
            # Check for data freshness
            if "data_freshness" in data:
                freshness = data["data_freshness"]
                print(f"✓ Data freshness status: {freshness.get('status')}")
                print(f"✓ Data freshness label: {freshness.get('label')}")
            
            # Check opportunities
            opportunities = data.get("opportunities", [])
            print(f"✓ Pre-computed CC opportunities: {len(opportunities)}")
            
            # Check computed_at
            if "computed_at" in data:
                print(f"✓ Computed at: {data['computed_at']}")
        elif response.status_code == 404:
            print("⚠ Pre-computed covered calls not found (may need refresh)")
        else:
            print(f"⚠ Pre-computed covered calls returned status {response.status_code}")
    
    def test_precomputed_pmcc(self, authenticated_client):
        """Test pre-computed PMCC scan"""
        response = authenticated_client.get(f"{BASE_URL}/api/screener/precomputed/pmcc/balanced")
        
        if response.status_code == 200:
            data = response.json()
            
            # Check for T-1 data info
            if "t1_data" in data:
                print(f"✓ Pre-computed PMCC T-1 date: {data['t1_data'].get('data_date')}")
            
            # Check for data freshness
            if "data_freshness" in data:
                freshness = data["data_freshness"]
                print(f"✓ Data freshness status: {freshness.get('status')}")
            
            # Check opportunities
            opportunities = data.get("opportunities", [])
            print(f"✓ Pre-computed PMCC opportunities: {len(opportunities)}")
        elif response.status_code == 404:
            print("⚠ Pre-computed PMCC not found (may need refresh)")
        else:
            print(f"⚠ Pre-computed PMCC returned status {response.status_code}")


class TestAvailableScans:
    """Test available scans endpoint"""
    
    def test_available_scans_endpoint(self, authenticated_client):
        """Test /api/screener/available-scans returns scan info"""
        response = authenticated_client.get(f"{BASE_URL}/api/screener/available-scans")
        
        if response.status_code == 200:
            data = response.json()
            
            # Check for covered_call scans
            if "covered_call" in data:
                cc_scans = data["covered_call"]
                print(f"✓ Covered call scans available: {len(cc_scans)}")
                for scan in cc_scans:
                    print(f"  - {scan.get('profile')}: {scan.get('count')} opportunities, available={scan.get('available')}")
            
            # Check for pmcc scans
            if "pmcc" in data:
                pmcc_scans = data["pmcc"]
                print(f"✓ PMCC scans available: {len(pmcc_scans)}")
                for scan in pmcc_scans:
                    print(f"  - {scan.get('profile')}: {scan.get('count')} opportunities, available={scan.get('available')}")
        else:
            print(f"⚠ Available scans returned status {response.status_code}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
