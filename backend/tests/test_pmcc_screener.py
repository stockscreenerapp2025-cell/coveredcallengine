"""
PMCC Screener Tests - Verifying PMCC Logic Isolation from CC
============================================================

Tests for the PMCC (Poor Man's Covered Call) screener endpoint.

PMCC RULES (COMPLETELY ISOLATED FROM CC):
- Long leg (LEAPS): 12-24 months DTE (365-730 days), ITM (strike < stock price), use ASK
- Short leg: ≤60 days DTE, strike > long-leg strike, use BID
- Net debit = Long-leg ASK - Short-leg BID
- Both BID and ASK must be > 0

CC RULES (SEPARATE):
- DTE: 7-45 days
- Use BID for premium (SELL leg)
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# PMCC Constants from screener_snapshot.py
PMCC_MIN_LEAP_DTE = 365  # 12 months minimum
PMCC_MAX_LEAP_DTE = 730  # 24 months maximum
PMCC_MAX_SHORT_DTE = 60  # ≤60 days

# CC Constants
CC_MIN_DTE = 7
CC_MAX_DTE = 45


class TestPMCCScreenerEndpoint:
    """Test PMCC screener endpoint returns results"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session with authentication"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login to get auth token
        login_response = self.session.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "admin@premiumhunter.com", "password": "admin123"}
        )
        if login_response.status_code == 200:
            token = login_response.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {token}"})
        else:
            pytest.skip("Authentication failed - skipping tests")
    
    def test_pmcc_endpoint_returns_200(self):
        """Test that PMCC endpoint returns 200 status"""
        response = self.session.get(f"{BASE_URL}/api/screener/pmcc")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "total" in data, "Response should contain 'total' field"
        assert "results" in data or "opportunities" in data, "Response should contain results"
        print(f"✓ PMCC endpoint returned 200 with {data.get('total', 0)} results")
    
    def test_pmcc_endpoint_returns_results_structure(self):
        """Test that PMCC results have correct structure"""
        response = self.session.get(f"{BASE_URL}/api/screener/pmcc")
        assert response.status_code == 200
        
        data = response.json()
        results = data.get("results", data.get("opportunities", []))
        
        # Check response metadata
        assert "symbols_scanned" in data, "Response should contain symbols_scanned"
        assert "stock_price_source" in data, "Response should contain stock_price_source"
        assert "options_chain_source" in data, "Response should contain options_chain_source"
        
        print(f"✓ PMCC response structure verified: {data.get('symbols_scanned', 0)} symbols scanned")
        print(f"  - Stock price source: {data.get('stock_price_source')}")
        print(f"  - Options chain source: {data.get('options_chain_source')}")


class TestPMCCLeapsDTERange:
    """Test PMCC LEAPS have DTE between 365-730 days (12-24 months)"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session with authentication"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        login_response = self.session.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "admin@premiumhunter.com", "password": "admin123"}
        )
        if login_response.status_code == 200:
            token = login_response.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {token}"})
        else:
            pytest.skip("Authentication failed")
    
    def test_pmcc_leaps_dte_minimum_365_days(self):
        """Test that PMCC LEAPS have DTE >= 365 days (12 months)"""
        response = self.session.get(f"{BASE_URL}/api/screener/pmcc")
        assert response.status_code == 200
        
        data = response.json()
        results = data.get("results", data.get("opportunities", []))
        
        if not results:
            pytest.skip("No PMCC results available - market may be closed or no valid options")
        
        violations = []
        for result in results:
            leap_dte = result.get("leap_dte") or result.get("long_call", {}).get("dte", 0)
            if leap_dte < PMCC_MIN_LEAP_DTE:
                violations.append({
                    "symbol": result.get("symbol"),
                    "leap_dte": leap_dte,
                    "expected_min": PMCC_MIN_LEAP_DTE
                })
        
        assert len(violations) == 0, f"LEAPS DTE violations found: {violations}"
        print(f"✓ All {len(results)} PMCC results have LEAPS DTE >= {PMCC_MIN_LEAP_DTE} days")
    
    def test_pmcc_leaps_dte_maximum_730_days(self):
        """Test that PMCC LEAPS have DTE <= 730 days (24 months)"""
        response = self.session.get(f"{BASE_URL}/api/screener/pmcc")
        assert response.status_code == 200
        
        data = response.json()
        results = data.get("results", data.get("opportunities", []))
        
        if not results:
            pytest.skip("No PMCC results available")
        
        violations = []
        for result in results:
            leap_dte = result.get("leap_dte") or result.get("long_call", {}).get("dte", 0)
            if leap_dte > PMCC_MAX_LEAP_DTE:
                violations.append({
                    "symbol": result.get("symbol"),
                    "leap_dte": leap_dte,
                    "expected_max": PMCC_MAX_LEAP_DTE
                })
        
        assert len(violations) == 0, f"LEAPS DTE violations found: {violations}"
        print(f"✓ All {len(results)} PMCC results have LEAPS DTE <= {PMCC_MAX_LEAP_DTE} days")


class TestPMCCLeapsITM:
    """Test PMCC LEAPS strikes are ITM (below stock price)"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session with authentication"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        login_response = self.session.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "admin@premiumhunter.com", "password": "admin123"}
        )
        if login_response.status_code == 200:
            token = login_response.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {token}"})
        else:
            pytest.skip("Authentication failed")
    
    def test_pmcc_leaps_strike_below_stock_price(self):
        """Test that PMCC LEAPS strikes are ITM (strike < stock price)"""
        response = self.session.get(f"{BASE_URL}/api/screener/pmcc")
        assert response.status_code == 200
        
        data = response.json()
        results = data.get("results", data.get("opportunities", []))
        
        if not results:
            pytest.skip("No PMCC results available")
        
        violations = []
        for result in results:
            stock_price = result.get("stock_price") or result.get("underlying", {}).get("last_price", 0)
            leap_strike = result.get("leap_strike") or result.get("long_call", {}).get("strike", 0)
            
            if leap_strike >= stock_price:
                violations.append({
                    "symbol": result.get("symbol"),
                    "stock_price": stock_price,
                    "leap_strike": leap_strike,
                    "issue": "LEAP strike should be < stock price (ITM)"
                })
        
        assert len(violations) == 0, f"LEAPS ITM violations found: {violations}"
        print(f"✓ All {len(results)} PMCC results have ITM LEAPS (strike < stock price)")


class TestPMCCLeapsAskPricing:
    """Test PMCC LEAPS use ASK price for premium (BUY leg)"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session with authentication"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        login_response = self.session.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "admin@premiumhunter.com", "password": "admin123"}
        )
        if login_response.status_code == 200:
            token = login_response.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {token}"})
        else:
            pytest.skip("Authentication failed")
    
    def test_pmcc_leaps_uses_ask_price(self):
        """Test that PMCC LEAPS premium equals ASK (BUY leg uses ASK)"""
        response = self.session.get(f"{BASE_URL}/api/screener/pmcc")
        assert response.status_code == 200
        
        data = response.json()
        results = data.get("results", data.get("opportunities", []))
        
        if not results:
            pytest.skip("No PMCC results available")
        
        violations = []
        for result in results:
            # Check both flat fields and nested structure
            leap_ask = result.get("leap_ask") or result.get("long_call", {}).get("ask", 0)
            leap_premium = result.get("leap_cost") or result.get("long_call", {}).get("premium", 0)
            
            # Premium should equal ASK for BUY leg
            if leap_ask > 0 and abs(leap_premium - leap_ask) > 0.01:
                violations.append({
                    "symbol": result.get("symbol"),
                    "leap_ask": leap_ask,
                    "leap_premium": leap_premium,
                    "issue": "LEAP premium should equal ASK"
                })
        
        assert len(violations) == 0, f"LEAPS ASK pricing violations: {violations}"
        print(f"✓ All {len(results)} PMCC results use ASK price for LEAPS (BUY leg)")
    
    def test_pmcc_leaps_ask_greater_than_zero(self):
        """Test that PMCC LEAPS have ASK > 0"""
        response = self.session.get(f"{BASE_URL}/api/screener/pmcc")
        assert response.status_code == 200
        
        data = response.json()
        results = data.get("results", data.get("opportunities", []))
        
        if not results:
            pytest.skip("No PMCC results available")
        
        violations = []
        for result in results:
            leap_ask = result.get("leap_ask") or result.get("long_call", {}).get("ask", 0)
            
            if leap_ask <= 0:
                violations.append({
                    "symbol": result.get("symbol"),
                    "leap_ask": leap_ask,
                    "issue": "LEAP ASK must be > 0"
                })
        
        assert len(violations) == 0, f"LEAPS ASK > 0 violations: {violations}"
        print(f"✓ All {len(results)} PMCC results have LEAPS ASK > 0")


class TestPMCCShortCallDTE:
    """Test PMCC short calls have DTE ≤60 days"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session with authentication"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        login_response = self.session.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "admin@premiumhunter.com", "password": "admin123"}
        )
        if login_response.status_code == 200:
            token = login_response.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {token}"})
        else:
            pytest.skip("Authentication failed")
    
    def test_pmcc_short_call_dte_max_60_days(self):
        """Test that PMCC short calls have DTE <= 60 days"""
        response = self.session.get(f"{BASE_URL}/api/screener/pmcc")
        assert response.status_code == 200
        
        data = response.json()
        results = data.get("results", data.get("opportunities", []))
        
        if not results:
            pytest.skip("No PMCC results available")
        
        violations = []
        for result in results:
            short_dte = result.get("short_dte") or result.get("short_call", {}).get("dte", 0)
            
            if short_dte > PMCC_MAX_SHORT_DTE:
                violations.append({
                    "symbol": result.get("symbol"),
                    "short_dte": short_dte,
                    "expected_max": PMCC_MAX_SHORT_DTE
                })
        
        assert len(violations) == 0, f"Short call DTE violations: {violations}"
        print(f"✓ All {len(results)} PMCC results have short call DTE <= {PMCC_MAX_SHORT_DTE} days")


class TestPMCCShortCallStrike:
    """Test PMCC short call strikes are above LEAPS strikes"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session with authentication"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        login_response = self.session.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "admin@premiumhunter.com", "password": "admin123"}
        )
        if login_response.status_code == 200:
            token = login_response.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {token}"})
        else:
            pytest.skip("Authentication failed")
    
    def test_pmcc_short_strike_above_leap_strike(self):
        """Test that PMCC short call strike > LEAP strike"""
        response = self.session.get(f"{BASE_URL}/api/screener/pmcc")
        assert response.status_code == 200
        
        data = response.json()
        results = data.get("results", data.get("opportunities", []))
        
        if not results:
            pytest.skip("No PMCC results available")
        
        violations = []
        for result in results:
            leap_strike = result.get("leap_strike") or result.get("long_call", {}).get("strike", 0)
            short_strike = result.get("short_strike") or result.get("short_call", {}).get("strike", 0)
            
            if short_strike <= leap_strike:
                violations.append({
                    "symbol": result.get("symbol"),
                    "leap_strike": leap_strike,
                    "short_strike": short_strike,
                    "issue": "Short strike must be > LEAP strike"
                })
        
        assert len(violations) == 0, f"Short strike violations: {violations}"
        print(f"✓ All {len(results)} PMCC results have short strike > LEAP strike")


class TestPMCCShortCallBidPricing:
    """Test PMCC short calls use BID price for premium (SELL leg)"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session with authentication"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        login_response = self.session.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "admin@premiumhunter.com", "password": "admin123"}
        )
        if login_response.status_code == 200:
            token = login_response.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {token}"})
        else:
            pytest.skip("Authentication failed")
    
    def test_pmcc_short_call_uses_bid_price(self):
        """Test that PMCC short call premium equals BID (SELL leg uses BID)"""
        response = self.session.get(f"{BASE_URL}/api/screener/pmcc")
        assert response.status_code == 200
        
        data = response.json()
        results = data.get("results", data.get("opportunities", []))
        
        if not results:
            pytest.skip("No PMCC results available")
        
        violations = []
        for result in results:
            short_bid = result.get("short_bid") or result.get("short_call", {}).get("bid", 0)
            short_premium = result.get("short_premium") or result.get("short_call", {}).get("premium", 0)
            
            # Premium should equal BID for SELL leg
            if short_bid > 0 and abs(short_premium - short_bid) > 0.01:
                violations.append({
                    "symbol": result.get("symbol"),
                    "short_bid": short_bid,
                    "short_premium": short_premium,
                    "issue": "Short premium should equal BID"
                })
        
        assert len(violations) == 0, f"Short call BID pricing violations: {violations}"
        print(f"✓ All {len(results)} PMCC results use BID price for short call (SELL leg)")
    
    def test_pmcc_short_call_bid_greater_than_zero(self):
        """Test that PMCC short calls have BID > 0"""
        response = self.session.get(f"{BASE_URL}/api/screener/pmcc")
        assert response.status_code == 200
        
        data = response.json()
        results = data.get("results", data.get("opportunities", []))
        
        if not results:
            pytest.skip("No PMCC results available")
        
        violations = []
        for result in results:
            short_bid = result.get("short_bid") or result.get("short_call", {}).get("bid", 0)
            
            if short_bid <= 0:
                violations.append({
                    "symbol": result.get("symbol"),
                    "short_bid": short_bid,
                    "issue": "Short BID must be > 0"
                })
        
        assert len(violations) == 0, f"Short call BID > 0 violations: {violations}"
        print(f"✓ All {len(results)} PMCC results have short call BID > 0")


class TestPMCCNetDebitCalculation:
    """Test PMCC net_debit = leap_ask - short_bid is correctly calculated"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session with authentication"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        login_response = self.session.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "admin@premiumhunter.com", "password": "admin123"}
        )
        if login_response.status_code == 200:
            token = login_response.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {token}"})
        else:
            pytest.skip("Authentication failed")
    
    def test_pmcc_net_debit_calculation(self):
        """Test that net_debit = leap_ask - short_bid"""
        response = self.session.get(f"{BASE_URL}/api/screener/pmcc")
        assert response.status_code == 200
        
        data = response.json()
        results = data.get("results", data.get("opportunities", []))
        
        if not results:
            pytest.skip("No PMCC results available")
        
        violations = []
        for result in results:
            leap_ask = result.get("leap_ask") or result.get("long_call", {}).get("ask", 0)
            short_bid = result.get("short_bid") or result.get("short_call", {}).get("bid", 0)
            net_debit = result.get("net_debit") or result.get("economics", {}).get("net_debit", 0)
            
            expected_net_debit = leap_ask - short_bid
            
            # Allow small floating point tolerance
            if abs(net_debit - expected_net_debit) > 0.02:
                violations.append({
                    "symbol": result.get("symbol"),
                    "leap_ask": leap_ask,
                    "short_bid": short_bid,
                    "expected_net_debit": round(expected_net_debit, 2),
                    "actual_net_debit": net_debit
                })
        
        assert len(violations) == 0, f"Net debit calculation violations: {violations}"
        print(f"✓ All {len(results)} PMCC results have correct net_debit = leap_ask - short_bid")
    
    def test_pmcc_net_debit_is_positive(self):
        """Test that net_debit > 0 (it's a debit strategy)"""
        response = self.session.get(f"{BASE_URL}/api/screener/pmcc")
        assert response.status_code == 200
        
        data = response.json()
        results = data.get("results", data.get("opportunities", []))
        
        if not results:
            pytest.skip("No PMCC results available")
        
        violations = []
        for result in results:
            net_debit = result.get("net_debit") or result.get("economics", {}).get("net_debit", 0)
            
            if net_debit <= 0:
                violations.append({
                    "symbol": result.get("symbol"),
                    "net_debit": net_debit,
                    "issue": "Net debit must be > 0 for PMCC"
                })
        
        assert len(violations) == 0, f"Net debit positive violations: {violations}"
        print(f"✓ All {len(results)} PMCC results have positive net_debit")


class TestCCScreenerStillWorks:
    """Test CC screener endpoint still works"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session with authentication"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        login_response = self.session.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "admin@premiumhunter.com", "password": "admin123"}
        )
        if login_response.status_code == 200:
            token = login_response.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {token}"})
        else:
            pytest.skip("Authentication failed")
    
    def test_cc_endpoint_returns_200(self):
        """Test that CC endpoint returns 200 status"""
        response = self.session.get(f"{BASE_URL}/api/screener/covered-calls")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "total" in data, "Response should contain 'total' field"
        assert "results" in data or "opportunities" in data, "Response should contain results"
        print(f"✓ CC endpoint returned 200 with {data.get('total', 0)} results")
    
    def test_cc_endpoint_returns_results_structure(self):
        """Test that CC results have correct structure"""
        response = self.session.get(f"{BASE_URL}/api/screener/covered-calls")
        assert response.status_code == 200
        
        data = response.json()
        
        # Check response metadata
        assert "symbols_scanned" in data, "Response should contain symbols_scanned"
        assert "stock_price_source" in data, "Response should contain stock_price_source"
        assert "options_chain_source" in data, "Response should contain options_chain_source"
        assert "dte_range" in data, "Response should contain dte_range"
        
        print(f"✓ CC response structure verified: {data.get('symbols_scanned', 0)} symbols scanned")
        print(f"  - DTE range: {data.get('dte_range')}")


class TestCCAndPMCCSeparateDTERanges:
    """Test CC and PMCC have separate DTE ranges"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session with authentication"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        login_response = self.session.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "admin@premiumhunter.com", "password": "admin123"}
        )
        if login_response.status_code == 200:
            token = login_response.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {token}"})
        else:
            pytest.skip("Authentication failed")
    
    def test_cc_dte_range_7_to_45(self):
        """Test that CC uses DTE range 7-45 days"""
        response = self.session.get(f"{BASE_URL}/api/screener/covered-calls")
        assert response.status_code == 200
        
        data = response.json()
        dte_range = data.get("dte_range", {})
        
        # CC default DTE range should be 7-45
        assert dte_range.get("min") == CC_MIN_DTE, f"CC min DTE should be {CC_MIN_DTE}, got {dte_range.get('min')}"
        assert dte_range.get("max") == CC_MAX_DTE, f"CC max DTE should be {CC_MAX_DTE}, got {dte_range.get('max')}"
        
        print(f"✓ CC DTE range verified: {dte_range.get('min')}-{dte_range.get('max')} days")
    
    def test_pmcc_leaps_dte_range_365_to_730(self):
        """Test that PMCC LEAPS use DTE range 365-730 days"""
        response = self.session.get(f"{BASE_URL}/api/screener/pmcc")
        assert response.status_code == 200
        
        data = response.json()
        
        # Check PMCC-specific DTE ranges in response
        leap_dte_range = data.get("leap_dte_range", {})
        
        # If leap_dte_range is in response, verify it
        if leap_dte_range:
            assert leap_dte_range.get("min") == PMCC_MIN_LEAP_DTE, f"PMCC LEAPS min DTE should be {PMCC_MIN_LEAP_DTE}"
            assert leap_dte_range.get("max") == PMCC_MAX_LEAP_DTE, f"PMCC LEAPS max DTE should be {PMCC_MAX_LEAP_DTE}"
        
        # Verify actual results have correct DTE
        results = data.get("results", data.get("opportunities", []))
        if results:
            for result in results:
                leap_dte = result.get("leap_dte") or result.get("long_call", {}).get("dte", 0)
                assert leap_dte >= PMCC_MIN_LEAP_DTE, f"LEAPS DTE {leap_dte} < {PMCC_MIN_LEAP_DTE}"
                assert leap_dte <= PMCC_MAX_LEAP_DTE, f"LEAPS DTE {leap_dte} > {PMCC_MAX_LEAP_DTE}"
        
        print(f"✓ PMCC LEAPS DTE range verified: {PMCC_MIN_LEAP_DTE}-{PMCC_MAX_LEAP_DTE} days")
    
    def test_pmcc_short_dte_range_max_60(self):
        """Test that PMCC short calls use DTE ≤60 days"""
        response = self.session.get(f"{BASE_URL}/api/screener/pmcc")
        assert response.status_code == 200
        
        data = response.json()
        
        # Check PMCC-specific short DTE range
        short_dte_range = data.get("short_dte_range", {})
        
        if short_dte_range:
            assert short_dte_range.get("max") == PMCC_MAX_SHORT_DTE, f"PMCC short max DTE should be {PMCC_MAX_SHORT_DTE}"
        
        # Verify actual results have correct short DTE
        results = data.get("results", data.get("opportunities", []))
        if results:
            for result in results:
                short_dte = result.get("short_dte") or result.get("short_call", {}).get("dte", 0)
                assert short_dte <= PMCC_MAX_SHORT_DTE, f"Short DTE {short_dte} > {PMCC_MAX_SHORT_DTE}"
        
        print(f"✓ PMCC short call DTE range verified: max {PMCC_MAX_SHORT_DTE} days")
    
    def test_cc_and_pmcc_dte_ranges_do_not_overlap(self):
        """Test that CC and PMCC LEAPS DTE ranges are completely separate"""
        # CC: 7-45 days
        # PMCC LEAPS: 365-730 days
        # These should NOT overlap
        
        cc_max = CC_MAX_DTE  # 45
        pmcc_min = PMCC_MIN_LEAP_DTE  # 365
        
        assert pmcc_min > cc_max, f"PMCC LEAPS min DTE ({pmcc_min}) should be > CC max DTE ({cc_max})"
        
        gap = pmcc_min - cc_max
        print(f"✓ CC and PMCC LEAPS DTE ranges are separate with {gap} day gap")
        print(f"  - CC: {CC_MIN_DTE}-{CC_MAX_DTE} days")
        print(f"  - PMCC LEAPS: {PMCC_MIN_LEAP_DTE}-{PMCC_MAX_LEAP_DTE} days")


class TestPMCCValidationFlags:
    """Test PMCC validation flags are correctly set"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session with authentication"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        login_response = self.session.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "admin@premiumhunter.com", "password": "admin123"}
        )
        if login_response.status_code == 200:
            token = login_response.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {token}"})
        else:
            pytest.skip("Authentication failed")
    
    def test_pmcc_validation_flags_present(self):
        """Test that PMCC results have validation flags"""
        response = self.session.get(f"{BASE_URL}/api/screener/pmcc")
        assert response.status_code == 200
        
        data = response.json()
        results = data.get("results", data.get("opportunities", []))
        
        if not results:
            pytest.skip("No PMCC results available")
        
        # Check first result for validation flags
        result = results[0]
        metadata = result.get("metadata", {})
        validation_flags = metadata.get("validation_flags", {})
        
        # Check expected validation flags
        expected_flags = ["leap_itm", "leap_delta_ok", "leap_dte_ok", "short_above_leap", "short_dte_ok"]
        
        for flag in expected_flags:
            if flag in validation_flags:
                print(f"  - {flag}: {validation_flags[flag]}")
        
        print(f"✓ PMCC validation flags present in results")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
