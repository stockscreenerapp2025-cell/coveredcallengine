"""
EOD Pipeline API Tests
======================
Tests for the deterministic End-of-Day (EOD) pipeline that pre-computes 
CC/PMCC scan results and stores them in MongoDB for fast read-only access.

Endpoints tested:
- GET /api/eod-pipeline/covered-calls - Pre-computed CC results
- GET /api/eod-pipeline/pmcc - Pre-computed PMCC results
- GET /api/eod-pipeline/latest-run - Latest run metadata
- GET /api/eod-pipeline/universe - Universe statistics (admin only)
- POST /api/eod-pipeline/create-indexes - Create MongoDB indexes (admin only)
"""
import pytest
import requests
import os
from datetime import datetime

# Get BASE_URL from environment
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
if not BASE_URL:
    raise ValueError("REACT_APP_BACKEND_URL environment variable not set")

# Test credentials
ADMIN_EMAIL = "admin@premiumhunter.com"
ADMIN_PASSWORD = "admin123"


class TestAuthSetup:
    """Test authentication setup for EOD pipeline tests"""
    
    @pytest.fixture(scope="class")
    def admin_token(self):
        """Get admin authentication token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
        )
        assert response.status_code == 200, f"Admin login failed: {response.text}"
        data = response.json()
        assert "access_token" in data, "No access_token in login response"
        return data["access_token"]
    
    @pytest.fixture(scope="class")
    def auth_headers(self, admin_token):
        """Get authorization headers"""
        return {"Authorization": f"Bearer {admin_token}"}


class TestEODPipelineAuth(TestAuthSetup):
    """Test that all EOD pipeline endpoints require authentication"""
    
    def test_covered_calls_requires_auth(self):
        """GET /api/eod-pipeline/covered-calls requires authentication"""
        response = requests.get(f"{BASE_URL}/api/eod-pipeline/covered-calls")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
    
    def test_pmcc_requires_auth(self):
        """GET /api/eod-pipeline/pmcc requires authentication"""
        response = requests.get(f"{BASE_URL}/api/eod-pipeline/pmcc")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
    
    def test_latest_run_requires_auth(self):
        """GET /api/eod-pipeline/latest-run requires authentication"""
        response = requests.get(f"{BASE_URL}/api/eod-pipeline/latest-run")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
    
    def test_universe_requires_admin(self, auth_headers):
        """GET /api/eod-pipeline/universe requires admin access"""
        # First verify it works with admin
        response = requests.get(
            f"{BASE_URL}/api/eod-pipeline/universe",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Admin should access universe: {response.text}"
    
    def test_create_indexes_requires_admin(self, auth_headers):
        """POST /api/eod-pipeline/create-indexes requires admin access"""
        # Verify it works with admin
        response = requests.post(
            f"{BASE_URL}/api/eod-pipeline/create-indexes",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Admin should create indexes: {response.text}"


class TestCoveredCallsEndpoint(TestAuthSetup):
    """Test GET /api/eod-pipeline/covered-calls endpoint"""
    
    def test_get_covered_calls_success(self, auth_headers):
        """GET /api/eod-pipeline/covered-calls returns pre-computed CC results"""
        response = requests.get(
            f"{BASE_URL}/api/eod-pipeline/covered-calls",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "total" in data, "Missing 'total' field"
        assert "results" in data, "Missing 'results' field"
        assert "opportunities" in data, "Missing 'opportunities' field (backward compat)"
        assert "run_info" in data, "Missing 'run_info' field"
        assert "data_source" in data, "Missing 'data_source' field"
        assert "live_data_used" in data, "Missing 'live_data_used' field"
        
        # Verify data source is precomputed
        assert data["data_source"] == "precomputed_eod", f"Expected precomputed_eod, got {data['data_source']}"
        assert data["live_data_used"] == False, "live_data_used should be False"
    
    def test_covered_calls_with_limit(self, auth_headers):
        """GET /api/eod-pipeline/covered-calls respects limit parameter"""
        response = requests.get(
            f"{BASE_URL}/api/eod-pipeline/covered-calls?limit=5",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        # Verify limit is respected
        assert len(data["results"]) <= 5, f"Expected max 5 results, got {len(data['results'])}"
    
    def test_covered_calls_result_fields(self, auth_headers):
        """CC results have correct fields: symbol, strike, premium, roi_pct, delta, score"""
        response = requests.get(
            f"{BASE_URL}/api/eod-pipeline/covered-calls?limit=10",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        if data["total"] > 0:
            # Verify first result has required fields
            result = data["results"][0]
            required_fields = ["symbol", "strike", "premium", "roi_pct", "delta", "score"]
            for field in required_fields:
                assert field in result, f"Missing required field: {field}"
            
            # Verify field types
            assert isinstance(result["symbol"], str), "symbol should be string"
            assert isinstance(result["strike"], (int, float)), "strike should be numeric"
            assert isinstance(result["premium"], (int, float)), "premium should be numeric"
            assert isinstance(result["roi_pct"], (int, float)), "roi_pct should be numeric"
            assert isinstance(result["delta"], (int, float)), "delta should be numeric"
            assert isinstance(result["score"], (int, float)), "score should be numeric"
            
            # Verify delta is in valid range [0, 1]
            assert 0 <= result["delta"] <= 1, f"Delta {result['delta']} out of range [0, 1]"
            
            print(f"Sample CC result: {result['symbol']} @ ${result['strike']} - ROI: {result['roi_pct']}%, Delta: {result['delta']}, Score: {result['score']}")
        else:
            print("No CC results found - pipeline may not have run yet")
    
    def test_covered_calls_run_info(self, auth_headers):
        """CC results include run_info with metadata"""
        response = requests.get(
            f"{BASE_URL}/api/eod-pipeline/covered-calls",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        run_info = data.get("run_info")
        if run_info:
            # Verify run_info fields
            assert "run_id" in run_info, "run_info missing run_id"
            assert "completed_at" in run_info, "run_info missing completed_at"
            assert "symbols_processed" in run_info, "run_info missing symbols_processed"
            assert "symbols_included" in run_info, "run_info missing symbols_included"
            
            print(f"Run info: run_id={run_info['run_id']}, processed={run_info['symbols_processed']}, included={run_info['symbols_included']}")
        else:
            print("No run_info - pipeline may not have completed a run yet")


class TestPMCCEndpoint(TestAuthSetup):
    """Test GET /api/eod-pipeline/pmcc endpoint"""
    
    def test_get_pmcc_success(self, auth_headers):
        """GET /api/eod-pipeline/pmcc returns pre-computed PMCC results"""
        response = requests.get(
            f"{BASE_URL}/api/eod-pipeline/pmcc",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "total" in data, "Missing 'total' field"
        assert "results" in data, "Missing 'results' field"
        assert "opportunities" in data, "Missing 'opportunities' field"
        assert "run_info" in data, "Missing 'run_info' field"
        assert "data_source" in data, "Missing 'data_source' field"
        
        # Verify data source is precomputed
        assert data["data_source"] == "precomputed_eod", f"Expected precomputed_eod, got {data['data_source']}"
        assert data["live_data_used"] == False, "live_data_used should be False"
    
    def test_pmcc_with_limit(self, auth_headers):
        """GET /api/eod-pipeline/pmcc respects limit parameter"""
        response = requests.get(
            f"{BASE_URL}/api/eod-pipeline/pmcc?limit=5",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        # Verify limit is respected
        assert len(data["results"]) <= 5, f"Expected max 5 results, got {len(data['results'])}"
    
    def test_pmcc_result_fields(self, auth_headers):
        """PMCC results have correct fields for LEAPS + short call structure"""
        response = requests.get(
            f"{BASE_URL}/api/eod-pipeline/pmcc?limit=10",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        if data["total"] > 0:
            result = data["results"][0]
            
            # PMCC should have LEAPS and short call fields
            pmcc_fields = ["symbol", "stock_price", "leap_strike", "short_strike", "net_debit", "score"]
            for field in pmcc_fields:
                assert field in result, f"Missing PMCC field: {field}"
            
            print(f"Sample PMCC: {result['symbol']} - LEAP: ${result['leap_strike']}, Short: ${result['short_strike']}, Net Debit: ${result['net_debit']}")
        else:
            print("No PMCC results found - may require LEAPS data (365+ DTE)")


class TestLatestRunEndpoint(TestAuthSetup):
    """Test GET /api/eod-pipeline/latest-run endpoint"""
    
    def test_get_latest_run_success(self, auth_headers):
        """GET /api/eod-pipeline/latest-run returns metadata about last completed run"""
        response = requests.get(
            f"{BASE_URL}/api/eod-pipeline/latest-run",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "has_data" in data, "Missing 'has_data' field"
        
        if data["has_data"]:
            assert "run" in data, "Missing 'run' field when has_data=True"
            run = data["run"]
            
            # Verify run fields
            required_run_fields = ["run_id", "completed_at", "symbols_processed", "symbols_included"]
            for field in required_run_fields:
                assert field in run, f"Run missing required field: {field}"
            
            # Verify run_id format
            assert run["run_id"].startswith("eod_"), f"run_id should start with 'eod_': {run['run_id']}"
            
            print(f"Latest run: {run['run_id']}")
            print(f"  Completed: {run['completed_at']}")
            print(f"  Symbols processed: {run['symbols_processed']}")
            print(f"  Symbols included: {run['symbols_included']}")
        else:
            print("No completed runs found - pipeline may not have run yet")
            assert "message" in data, "Should have message when has_data=False"


class TestUniverseEndpoint(TestAuthSetup):
    """Test GET /api/eod-pipeline/universe endpoint (admin only)"""
    
    def test_get_universe_success(self, auth_headers):
        """GET /api/eod-pipeline/universe returns universe statistics"""
        response = requests.get(
            f"{BASE_URL}/api/eod-pipeline/universe",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "static_universe" in data, "Missing 'static_universe' field"
        assert "target_size" in data, "Missing 'target_size' field"
        
        # Verify static universe
        static = data["static_universe"]
        assert "symbol_count" in static, "static_universe missing symbol_count"
        assert "tier_counts" in static, "static_universe missing tier_counts"
        
        # Verify tier counts
        tier_counts = static["tier_counts"]
        assert "sp500" in tier_counts, "tier_counts missing sp500"
        assert "nasdaq100_net" in tier_counts, "tier_counts missing nasdaq100_net"
        assert "etf_whitelist" in tier_counts, "tier_counts missing etf_whitelist"
        
        print(f"Universe statistics:")
        print(f"  Target size: {data['target_size']}")
        print(f"  Static universe: {static['symbol_count']} symbols")
        print(f"  Tier counts: SP500={tier_counts['sp500']}, NASDAQ100_net={tier_counts['nasdaq100_net']}, ETF={tier_counts['etf_whitelist']}")
        
        if data.get("persisted_universe"):
            persisted = data["persisted_universe"]
            print(f"  Persisted universe: {persisted.get('symbol_count', 0)} symbols, version={persisted.get('version')}")


class TestCreateIndexesEndpoint(TestAuthSetup):
    """Test POST /api/eod-pipeline/create-indexes endpoint (admin only)"""
    
    def test_create_indexes_success(self, auth_headers):
        """POST /api/eod-pipeline/create-indexes creates MongoDB indexes successfully"""
        response = requests.post(
            f"{BASE_URL}/api/eod-pipeline/create-indexes",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "status" in data, "Missing 'status' field"
        assert data["status"] == "completed", f"Expected status=completed, got {data['status']}"
        assert "indexes" in data, "Missing 'indexes' field"
        assert "created_at" in data, "Missing 'created_at' field"
        
        # Verify index results
        indexes = data["indexes"]
        expected_collections = [
            "symbol_snapshot",
            "scan_results_cc",
            "scan_results_pmcc",
            "scan_runs",
            "scan_universe_versions"
        ]
        
        for collection in expected_collections:
            assert collection in indexes, f"Missing index result for {collection}"
            assert indexes[collection] == "OK", f"Index creation failed for {collection}: {indexes[collection]}"
        
        print(f"Index creation results: {indexes}")


class TestDataIntegrity(TestAuthSetup):
    """Test data integrity and consistency across endpoints"""
    
    def test_cc_results_sorted_by_score(self, auth_headers):
        """CC results should be sorted by score descending"""
        response = requests.get(
            f"{BASE_URL}/api/eod-pipeline/covered-calls?limit=50",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        if len(data["results"]) > 1:
            scores = [r["score"] for r in data["results"]]
            assert scores == sorted(scores, reverse=True), "Results should be sorted by score descending"
            print(f"Score range: {max(scores):.1f} to {min(scores):.1f}")
    
    def test_run_info_consistency(self, auth_headers):
        """run_info should be consistent between CC and latest-run endpoints"""
        # Get CC results
        cc_response = requests.get(
            f"{BASE_URL}/api/eod-pipeline/covered-calls",
            headers=auth_headers
        )
        assert cc_response.status_code == 200
        cc_data = cc_response.json()
        
        # Get latest run
        run_response = requests.get(
            f"{BASE_URL}/api/eod-pipeline/latest-run",
            headers=auth_headers
        )
        assert run_response.status_code == 200
        run_data = run_response.json()
        
        if cc_data.get("run_info") and run_data.get("has_data"):
            cc_run_id = cc_data["run_info"]["run_id"]
            latest_run_id = run_data["run"]["run_id"]
            assert cc_run_id == latest_run_id, f"run_id mismatch: CC={cc_run_id}, latest={latest_run_id}"
            print(f"Run ID consistency verified: {cc_run_id}")
    
    def test_no_mongodb_id_in_response(self, auth_headers):
        """Responses should not contain MongoDB _id field"""
        # Check CC results
        cc_response = requests.get(
            f"{BASE_URL}/api/eod-pipeline/covered-calls?limit=5",
            headers=auth_headers
        )
        assert cc_response.status_code == 200
        cc_data = cc_response.json()
        
        for result in cc_data.get("results", []):
            assert "_id" not in result, "CC result should not contain _id"
        
        # Check latest run
        run_response = requests.get(
            f"{BASE_URL}/api/eod-pipeline/latest-run",
            headers=auth_headers
        )
        assert run_response.status_code == 200
        run_data = run_response.json()
        
        if run_data.get("run"):
            assert "_id" not in run_data["run"], "Run should not contain _id"
        
        print("No MongoDB _id fields found in responses")


class TestEdgeCases(TestAuthSetup):
    """Test edge cases and error handling"""
    
    def test_invalid_limit_parameter(self, auth_headers):
        """Invalid limit parameter should be handled gracefully"""
        # Limit too high
        response = requests.get(
            f"{BASE_URL}/api/eod-pipeline/covered-calls?limit=500",
            headers=auth_headers
        )
        # Should either cap at max or return validation error
        assert response.status_code in [200, 422], f"Unexpected status: {response.status_code}"
        
        # Limit too low
        response = requests.get(
            f"{BASE_URL}/api/eod-pipeline/covered-calls?limit=0",
            headers=auth_headers
        )
        assert response.status_code in [200, 422], f"Unexpected status: {response.status_code}"
    
    def test_invalid_run_id_parameter(self, auth_headers):
        """Invalid run_id parameter should return empty results"""
        response = requests.get(
            f"{BASE_URL}/api/eod-pipeline/covered-calls?run_id=invalid_run_id_12345",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        # Should return empty results for non-existent run_id
        assert data["total"] == 0, "Should return 0 results for invalid run_id"
        assert len(data["results"]) == 0, "Should return empty results array"


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
