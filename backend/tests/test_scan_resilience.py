"""
Test Suite for Scan Timeout Fix - Resilient Fetch Service
==========================================================

Tests for:
1. Admin endpoint GET /api/admin/scan/resilience-config
2. Environment variables loading (YAHOO_SCAN_MAX_CONCURRENCY, YAHOO_TIMEOUT_SECONDS, YAHOO_MAX_RETRIES)
3. ResilientYahooFetcher class instantiation and stats tracking
4. PrecomputedScanService imports resilient fetch module
5. Backend health check
"""

import pytest
import requests
import os
import sys

# Add backend to path for direct imports
sys.path.insert(0, '/app/backend')

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# ==================== FIXTURES ====================

@pytest.fixture(scope="module")
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture(scope="module")
def admin_token(api_client):
    """Get admin authentication token"""
    response = api_client.post(f"{BASE_URL}/api/auth/login", json={
        "email": "admin@premiumhunter.com",
        "password": "admin123"
    })
    if response.status_code == 200:
        data = response.json()
        return data.get("access_token") or data.get("token")
    pytest.skip("Admin authentication failed - skipping admin tests")


@pytest.fixture(scope="module")
def authenticated_client(api_client, admin_token):
    """Session with admin auth header"""
    api_client.headers.update({"Authorization": f"Bearer {admin_token}"})
    return api_client


# ==================== BACKEND HEALTH CHECK ====================

class TestBackendHealth:
    """Verify backend is running and healthy"""
    
    def test_health_endpoint(self, api_client):
        """Test backend health check passes"""
        response = api_client.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200, f"Health check failed: {response.text}"
        print(f"✓ Backend health check passed: {response.status_code}")


# ==================== ENVIRONMENT VARIABLES ====================

class TestEnvironmentVariables:
    """Test that environment variables are loaded correctly"""
    
    def test_yahoo_scan_max_concurrency_env(self):
        """Test YAHOO_SCAN_MAX_CONCURRENCY is set in environment"""
        value = os.environ.get("YAHOO_SCAN_MAX_CONCURRENCY")
        assert value is not None, "YAHOO_SCAN_MAX_CONCURRENCY not set in environment"
        assert value.isdigit(), f"YAHOO_SCAN_MAX_CONCURRENCY should be numeric, got: {value}"
        assert int(value) > 0, f"YAHOO_SCAN_MAX_CONCURRENCY should be positive, got: {value}"
        print(f"✓ YAHOO_SCAN_MAX_CONCURRENCY = {value}")
    
    def test_yahoo_timeout_seconds_env(self):
        """Test YAHOO_TIMEOUT_SECONDS is set in environment"""
        value = os.environ.get("YAHOO_TIMEOUT_SECONDS")
        assert value is not None, "YAHOO_TIMEOUT_SECONDS not set in environment"
        assert value.isdigit(), f"YAHOO_TIMEOUT_SECONDS should be numeric, got: {value}"
        assert int(value) > 0, f"YAHOO_TIMEOUT_SECONDS should be positive, got: {value}"
        print(f"✓ YAHOO_TIMEOUT_SECONDS = {value}")
    
    def test_yahoo_max_retries_env(self):
        """Test YAHOO_MAX_RETRIES is set in environment"""
        value = os.environ.get("YAHOO_MAX_RETRIES")
        assert value is not None, "YAHOO_MAX_RETRIES not set in environment"
        assert value.isdigit(), f"YAHOO_MAX_RETRIES should be numeric, got: {value}"
        assert int(value) >= 0, f"YAHOO_MAX_RETRIES should be non-negative, got: {value}"
        print(f"✓ YAHOO_MAX_RETRIES = {value}")


# ==================== RESILIENT FETCH MODULE ====================

class TestResilientFetchModule:
    """Test resilient_fetch.py module imports and classes"""
    
    def test_module_imports(self):
        """Test that resilient_fetch module can be imported"""
        try:
            from services.resilient_fetch import (
                ResilientYahooFetcher,
                fetch_with_resilience,
                get_scan_semaphore,
                ScanStats,
                get_resilience_config,
                YAHOO_SCAN_MAX_CONCURRENCY,
                YAHOO_TIMEOUT_SECONDS,
                YAHOO_MAX_RETRIES
            )
            print("✓ All resilient_fetch imports successful")
        except ImportError as e:
            pytest.fail(f"Failed to import from resilient_fetch: {e}")
    
    def test_config_values_loaded(self):
        """Test that config values are loaded from environment"""
        from services.resilient_fetch import (
            YAHOO_SCAN_MAX_CONCURRENCY,
            YAHOO_TIMEOUT_SECONDS,
            YAHOO_MAX_RETRIES
        )
        
        assert YAHOO_SCAN_MAX_CONCURRENCY == 5, f"Expected 5, got {YAHOO_SCAN_MAX_CONCURRENCY}"
        assert YAHOO_TIMEOUT_SECONDS == 30, f"Expected 30, got {YAHOO_TIMEOUT_SECONDS}"
        assert YAHOO_MAX_RETRIES == 2, f"Expected 2, got {YAHOO_MAX_RETRIES}"
        print(f"✓ Config values: concurrency={YAHOO_SCAN_MAX_CONCURRENCY}, timeout={YAHOO_TIMEOUT_SECONDS}s, retries={YAHOO_MAX_RETRIES}")
    
    def test_get_resilience_config(self):
        """Test get_resilience_config returns correct structure"""
        from services.resilient_fetch import get_resilience_config
        
        config = get_resilience_config()
        
        assert isinstance(config, dict), "Config should be a dictionary"
        assert "yahoo_scan_max_concurrency" in config, "Missing yahoo_scan_max_concurrency"
        assert "yahoo_timeout_seconds" in config, "Missing yahoo_timeout_seconds"
        assert "yahoo_max_retries" in config, "Missing yahoo_max_retries"
        assert "semaphore_initialized" in config, "Missing semaphore_initialized"
        
        assert config["yahoo_scan_max_concurrency"] == 5
        assert config["yahoo_timeout_seconds"] == 30
        assert config["yahoo_max_retries"] == 2
        
        print(f"✓ get_resilience_config() returns: {config}")


# ==================== RESILIENT YAHOO FETCHER CLASS ====================

class TestResilientYahooFetcher:
    """Test ResilientYahooFetcher class instantiation and methods"""
    
    def test_instantiation(self):
        """Test ResilientYahooFetcher can be instantiated"""
        from services.resilient_fetch import ResilientYahooFetcher
        
        fetcher = ResilientYahooFetcher(scan_type="test_scan")
        
        assert fetcher is not None, "Fetcher should not be None"
        assert fetcher.scan_type == "test_scan", f"Expected scan_type='test_scan', got {fetcher.scan_type}"
        assert fetcher.run_id is not None, "run_id should be auto-generated"
        assert "test_scan" in fetcher.run_id, "run_id should contain scan_type"
        
        print(f"✓ ResilientYahooFetcher instantiated: run_id={fetcher.run_id}")
    
    def test_instantiation_with_custom_run_id(self):
        """Test ResilientYahooFetcher with custom run_id"""
        from services.resilient_fetch import ResilientYahooFetcher
        
        fetcher = ResilientYahooFetcher(scan_type="covered_call", run_id="custom_run_123")
        
        assert fetcher.run_id == "custom_run_123", f"Expected run_id='custom_run_123', got {fetcher.run_id}"
        print(f"✓ Custom run_id accepted: {fetcher.run_id}")
    
    def test_set_total_symbols(self):
        """Test set_total_symbols method"""
        from services.resilient_fetch import ResilientYahooFetcher
        
        fetcher = ResilientYahooFetcher(scan_type="test")
        fetcher.set_total_symbols(100)
        
        assert fetcher.stats.total_symbols == 100, f"Expected 100, got {fetcher.stats.total_symbols}"
        print(f"✓ set_total_symbols(100) works: {fetcher.stats.total_symbols}")
    
    def test_stats_initialization(self):
        """Test that stats are properly initialized"""
        from services.resilient_fetch import ResilientYahooFetcher
        
        fetcher = ResilientYahooFetcher(scan_type="pmcc_test", run_id="test_run_001")
        
        stats = fetcher.stats
        assert stats.run_id == "test_run_001", f"Expected run_id='test_run_001', got {stats.run_id}"
        assert stats.scan_type == "pmcc_test", f"Expected scan_type='pmcc_test', got {stats.scan_type}"
        assert stats.successful == 0, "Initial successful count should be 0"
        assert stats.failed_timeout == 0, "Initial failed_timeout count should be 0"
        assert stats.failed_error == 0, "Initial failed_error count should be 0"
        assert stats.retries_total == 0, "Initial retries_total should be 0"
        assert stats.total_symbols == 0, "Initial total_symbols should be 0"
        assert stats.failed_symbols == [], "Initial failed_symbols should be empty list"
        
        print(f"✓ Stats initialized correctly: {stats.to_dict()}")
    
    def test_get_stats(self):
        """Test get_stats method returns ScanStats"""
        from services.resilient_fetch import ResilientYahooFetcher, ScanStats
        
        fetcher = ResilientYahooFetcher(scan_type="test")
        stats = fetcher.get_stats()
        
        assert isinstance(stats, ScanStats), f"Expected ScanStats, got {type(stats)}"
        assert stats.completed_at is not None, "completed_at should be set after get_stats()"
        print(f"✓ get_stats() returns ScanStats with completed_at={stats.completed_at}")


# ==================== SCAN STATS CLASS ====================

class TestScanStats:
    """Test ScanStats dataclass"""
    
    def test_scan_stats_creation(self):
        """Test ScanStats can be created"""
        from services.resilient_fetch import ScanStats
        
        stats = ScanStats(run_id="test_123", scan_type="covered_call")
        
        assert stats.run_id == "test_123"
        assert stats.scan_type == "covered_call"
        assert stats.started_at is not None
        assert stats.completed_at is None
        print(f"✓ ScanStats created: run_id={stats.run_id}, scan_type={stats.scan_type}")
    
    def test_scan_stats_complete(self):
        """Test ScanStats.complete() method"""
        from services.resilient_fetch import ScanStats
        import time
        
        stats = ScanStats(run_id="test_456", scan_type="pmcc")
        time.sleep(0.1)  # Small delay to ensure duration > 0
        stats.complete()
        
        assert stats.completed_at is not None, "completed_at should be set"
        assert stats.total_duration_seconds >= 0, "Duration should be non-negative"
        print(f"✓ ScanStats.complete() works: duration={stats.total_duration_seconds:.3f}s")
    
    def test_scan_stats_to_dict(self):
        """Test ScanStats.to_dict() method"""
        from services.resilient_fetch import ScanStats
        
        stats = ScanStats(run_id="test_789", scan_type="test")
        stats.total_symbols = 50
        stats.successful = 45
        stats.failed_timeout = 3
        stats.failed_error = 2
        stats.retries_total = 10
        stats.complete()
        
        result = stats.to_dict()
        
        assert isinstance(result, dict), "to_dict() should return dict"
        assert result["run_id"] == "test_789"
        assert result["scan_type"] == "test"
        assert result["total_symbols"] == 50
        assert result["successful"] == 45
        assert result["failed_timeout"] == 3
        assert result["failed_error"] == 2
        assert result["retries_total"] == 10
        assert result["success_rate_pct"] == 90.0  # 45/50 * 100
        
        print(f"✓ ScanStats.to_dict() returns: {result}")


# ==================== PRECOMPUTED SCANS SERVICE IMPORTS ====================

class TestPrecomputedScansImports:
    """Test that PrecomputedScanService imports resilient fetch module"""
    
    def test_precomputed_scans_imports_resilient_fetch(self):
        """Test PrecomputedScanService imports from resilient_fetch"""
        try:
            from services.precomputed_scans import (
                ResilientYahooFetcher,
                fetch_with_resilience,
                get_scan_semaphore,
                ScanStats,
                get_resilience_config,
                YAHOO_SCAN_MAX_CONCURRENCY,
                YAHOO_TIMEOUT_SECONDS,
                YAHOO_MAX_RETRIES
            )
            print("✓ PrecomputedScanService imports resilient_fetch components")
        except ImportError as e:
            pytest.fail(f"PrecomputedScanService failed to import resilient_fetch: {e}")
    
    def test_precomputed_scan_service_class(self):
        """Test PrecomputedScanService class can be imported"""
        try:
            from services.precomputed_scans import PrecomputedScanService
            assert PrecomputedScanService is not None
            print("✓ PrecomputedScanService class imported successfully")
        except ImportError as e:
            pytest.fail(f"Failed to import PrecomputedScanService: {e}")


# ==================== ADMIN API ENDPOINT ====================

class TestAdminResilienceConfigEndpoint:
    """Test GET /api/admin/scan/resilience-config endpoint"""
    
    def test_resilience_config_endpoint_requires_auth(self, api_client):
        """Test endpoint requires authentication"""
        response = api_client.get(f"{BASE_URL}/api/admin/scan/resilience-config")
        assert response.status_code in [401, 403], f"Expected 401/403 without auth, got {response.status_code}"
        print(f"✓ Endpoint requires authentication: {response.status_code}")
    
    def test_resilience_config_endpoint_returns_config(self, authenticated_client):
        """Test endpoint returns correct configuration"""
        response = authenticated_client.get(f"{BASE_URL}/api/admin/scan/resilience-config")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Check top-level structure
        assert "config" in data, "Response should contain 'config'"
        assert "description" in data, "Response should contain 'description'"
        assert "environment_variables" in data, "Response should contain 'environment_variables'"
        assert "notes" in data, "Response should contain 'notes'"
        
        # Check config values
        config = data["config"]
        assert config["yahoo_scan_max_concurrency"] == 5, f"Expected 5, got {config['yahoo_scan_max_concurrency']}"
        assert config["yahoo_timeout_seconds"] == 30, f"Expected 30, got {config['yahoo_timeout_seconds']}"
        assert config["yahoo_max_retries"] == 2, f"Expected 2, got {config['yahoo_max_retries']}"
        assert "semaphore_initialized" in config, "Missing semaphore_initialized"
        
        # Check environment_variables
        env_vars = data["environment_variables"]
        assert env_vars["YAHOO_SCAN_MAX_CONCURRENCY"] == "5"
        assert env_vars["YAHOO_TIMEOUT_SECONDS"] == "30"
        assert env_vars["YAHOO_MAX_RETRIES"] == "2"
        
        # Check descriptions exist
        desc = data["description"]
        assert "yahoo_scan_max_concurrency" in desc
        assert "yahoo_timeout_seconds" in desc
        assert "yahoo_max_retries" in desc
        
        # Check notes
        assert len(data["notes"]) > 0, "Notes should not be empty"
        
        print(f"✓ Resilience config endpoint returns correct data:")
        print(f"  - config: {config}")
        print(f"  - env_vars: {env_vars}")
    
    def test_resilience_config_endpoint_response_structure(self, authenticated_client):
        """Test endpoint response has all required fields"""
        response = authenticated_client.get(f"{BASE_URL}/api/admin/scan/resilience-config")
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify all expected keys
        expected_config_keys = ["yahoo_scan_max_concurrency", "yahoo_timeout_seconds", "yahoo_max_retries", "semaphore_initialized"]
        for key in expected_config_keys:
            assert key in data["config"], f"Missing config key: {key}"
        
        expected_env_keys = ["YAHOO_SCAN_MAX_CONCURRENCY", "YAHOO_TIMEOUT_SECONDS", "YAHOO_MAX_RETRIES"]
        for key in expected_env_keys:
            assert key in data["environment_variables"], f"Missing env var key: {key}"
        
        print(f"✓ Response structure validated with all required fields")


# ==================== SEMAPHORE FUNCTIONALITY ====================

class TestSemaphoreFunctionality:
    """Test semaphore initialization and functionality"""
    
    def test_get_scan_semaphore(self):
        """Test get_scan_semaphore returns a semaphore"""
        from services.resilient_fetch import get_scan_semaphore, reset_scan_semaphore
        import asyncio
        
        # Reset first to ensure clean state
        reset_scan_semaphore()
        
        semaphore = get_scan_semaphore()
        
        assert semaphore is not None, "Semaphore should not be None"
        assert isinstance(semaphore, asyncio.Semaphore), f"Expected asyncio.Semaphore, got {type(semaphore)}"
        print(f"✓ get_scan_semaphore() returns asyncio.Semaphore")
    
    def test_semaphore_lazy_initialization(self):
        """Test semaphore is lazily initialized"""
        from services.resilient_fetch import get_scan_semaphore, reset_scan_semaphore, get_resilience_config
        
        # Reset to clear any existing semaphore
        reset_scan_semaphore()
        
        # Check semaphore is not initialized
        config_before = get_resilience_config()
        assert config_before["semaphore_initialized"] == False, "Semaphore should not be initialized after reset"
        
        # Get semaphore (triggers initialization)
        semaphore = get_scan_semaphore()
        
        # Check semaphore is now initialized
        config_after = get_resilience_config()
        assert config_after["semaphore_initialized"] == True, "Semaphore should be initialized after get_scan_semaphore()"
        
        print(f"✓ Semaphore lazy initialization works correctly")
    
    def test_reset_scan_semaphore(self):
        """Test reset_scan_semaphore clears the semaphore"""
        from services.resilient_fetch import get_scan_semaphore, reset_scan_semaphore, get_resilience_config
        
        # Initialize semaphore
        get_scan_semaphore()
        config_before = get_resilience_config()
        assert config_before["semaphore_initialized"] == True
        
        # Reset
        reset_scan_semaphore()
        
        # Check it's cleared
        config_after = get_resilience_config()
        assert config_after["semaphore_initialized"] == False, "Semaphore should be cleared after reset"
        
        print(f"✓ reset_scan_semaphore() clears the semaphore")


# ==================== FETCH RESULT CLASS ====================

class TestFetchResult:
    """Test FetchResult dataclass"""
    
    def test_fetch_result_creation(self):
        """Test FetchResult can be created"""
        from services.resilient_fetch import FetchResult
        
        result = FetchResult(symbol="AAPL", success=True, data={"price": 150.0})
        
        assert result.symbol == "AAPL"
        assert result.success == True
        assert result.data == {"price": 150.0}
        assert result.error is None
        assert result.fetch_time_seconds == 0.0
        assert result.retries_used == 0
        assert result.timed_out == False
        
        print(f"✓ FetchResult created: {result}")
    
    def test_fetch_result_failure(self):
        """Test FetchResult for failure case"""
        from services.resilient_fetch import FetchResult
        
        result = FetchResult(
            symbol="INVALID",
            success=False,
            error="Timeout after 30s",
            timed_out=True,
            retries_used=2,
            fetch_time_seconds=32.5
        )
        
        assert result.symbol == "INVALID"
        assert result.success == False
        assert result.data is None
        assert result.error == "Timeout after 30s"
        assert result.timed_out == True
        assert result.retries_used == 2
        assert result.fetch_time_seconds == 32.5
        
        print(f"✓ FetchResult failure case: {result}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
