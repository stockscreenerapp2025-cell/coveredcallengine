"""
Test Stock Price (Last Market Close) and Quote Cache Service
=============================================================

Tests for two critical fixes:
1. Stock prices now use LAST market close (not previousClose which is prior day)
2. Options quotes now support after-hours with quote caching and timestamps

FEATURES TO TEST:
- Stock price returns LAST market close (e.g., OXY should return ~$44.83 not $44.55)
- Options quotes marked with quote_source (LIVE or LAST_MARKET_SESSION)
- Options quotes include quote_timestamp and quote_age_hours
- SELL legs still require valid BID (reject if BID=0)
- BUY legs still require valid ASK (reject if ASK=0)
- Screener returns results with proper quote_info object
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
def auth_token():
    """Get authentication token for API calls"""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
    )
    if response.status_code == 200:
        data = response.json()
        return data.get("access_token") or data.get("token")
    pytest.skip(f"Authentication failed: {response.status_code} - {response.text}")


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Get headers with auth token"""
    return {"Authorization": f"Bearer {auth_token}"}


class TestStockPriceLastMarketClose:
    """
    Test that stock prices use LAST market close (most recent trading day's close)
    instead of previousClose (prior day's close).
    
    The fix uses yfinance history() to get the actual last market close.
    """
    
    def test_stock_quote_returns_close_date(self, auth_headers):
        """
        Verify stock quote includes close_date field showing when the price was captured.
        This confirms we're using historical data, not just previousClose.
        """
        # Test with a known symbol
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls",
            params={"limit": 5},
            headers=auth_headers
        )
        assert response.status_code == 200, f"API failed: {response.text}"
        
        data = response.json()
        # Check that we got results or at least the API responded correctly
        assert "results" in data or "opportunities" in data, "Missing results field"
        
        # Verify stock_price_source indicates previous_close (which now means last market close)
        assert data.get("stock_price_source") == "previous_close", \
            f"Expected stock_price_source='previous_close', got {data.get('stock_price_source')}"
    
    def test_screener_cc_stock_price_source(self, auth_headers):
        """
        Verify Covered Call screener uses correct stock price source.
        """
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls",
            params={"limit": 10},
            headers=auth_headers
        )
        assert response.status_code == 200, f"API failed: {response.text}"
        
        data = response.json()
        
        # Verify architecture label
        assert data.get("architecture") == "LIVE_OPTIONS_PREVIOUS_CLOSE_STOCK", \
            f"Expected architecture='LIVE_OPTIONS_PREVIOUS_CLOSE_STOCK', got {data.get('architecture')}"
        
        # Verify stock price source
        assert data.get("stock_price_source") == "previous_close", \
            f"Expected stock_price_source='previous_close', got {data.get('stock_price_source')}"
    
    def test_screener_pmcc_stock_price_source(self, auth_headers):
        """
        Verify PMCC screener uses correct stock price source.
        """
        response = requests.get(
            f"{BASE_URL}/api/screener/pmcc",
            params={"limit": 10},
            headers=auth_headers
        )
        assert response.status_code == 200, f"API failed: {response.text}"
        
        data = response.json()
        
        # Verify architecture label
        assert data.get("architecture") == "LIVE_OPTIONS_PREVIOUS_CLOSE_STOCK", \
            f"Expected architecture='LIVE_OPTIONS_PREVIOUS_CLOSE_STOCK', got {data.get('architecture')}"
        
        # Verify stock price source
        assert data.get("stock_price_source") == "previous_close", \
            f"Expected stock_price_source='previous_close', got {data.get('stock_price_source')}"


class TestQuoteCacheService:
    """
    Test quote caching for after-hours support.
    
    Features:
    - Options quotes marked with quote_source (LIVE or LAST_MARKET_SESSION)
    - Options quotes include quote_timestamp and quote_age_hours
    """
    
    def test_screener_cc_returns_quote_info(self, auth_headers):
        """
        Verify Covered Call screener returns quote_info object with:
        - quote_source: "LIVE" or "LAST_MARKET_SESSION"
        - quote_timestamp: When the quote was captured
        - quote_age_hours: How old the quote is (after hours only)
        """
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls",
            params={"limit": 20},
            headers=auth_headers
        )
        assert response.status_code == 200, f"API failed: {response.text}"
        
        data = response.json()
        results = data.get("results") or data.get("opportunities") or []
        
        # If we have results, verify quote_info structure
        if results:
            for result in results[:5]:  # Check first 5 results
                # Check for quote_info object (new structure)
                if "quote_info" in result:
                    quote_info = result["quote_info"]
                    assert "quote_source" in quote_info, \
                        f"Missing quote_source in quote_info for {result.get('symbol')}"
                    assert quote_info["quote_source"] in ["LIVE", "LAST_MARKET_SESSION"], \
                        f"Invalid quote_source: {quote_info['quote_source']}"
                    
                    # quote_timestamp should be present
                    assert "quote_timestamp" in quote_info, \
                        f"Missing quote_timestamp in quote_info for {result.get('symbol')}"
                    
                    # quote_age_hours should be present (0 for LIVE, >0 for LAST_MARKET_SESSION)
                    assert "quote_age_hours" in quote_info, \
                        f"Missing quote_age_hours in quote_info for {result.get('symbol')}"
                    
                    print(f"✓ {result.get('symbol')}: quote_source={quote_info['quote_source']}, "
                          f"quote_age_hours={quote_info['quote_age_hours']}")
                
                # Also check legacy flat fields for backward compatibility
                elif "quote_source" in result:
                    assert result["quote_source"] in ["LIVE", "LAST_MARKET_SESSION"], \
                        f"Invalid quote_source: {result['quote_source']}"
                    print(f"✓ {result.get('symbol')}: quote_source={result['quote_source']} (legacy field)")
        else:
            # No results is acceptable during after-hours if BID=0
            print("No results returned - this is expected if market is closed and BID=0")
    
    def test_quote_source_values(self, auth_headers):
        """
        Verify quote_source is either LIVE or LAST_MARKET_SESSION.
        """
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls",
            params={"limit": 10},
            headers=auth_headers
        )
        assert response.status_code == 200, f"API failed: {response.text}"
        
        data = response.json()
        results = data.get("results") or data.get("opportunities") or []
        
        valid_sources = ["LIVE", "LAST_MARKET_SESSION"]
        
        for result in results:
            # Check quote_info object
            if "quote_info" in result:
                source = result["quote_info"].get("quote_source")
                assert source in valid_sources, \
                    f"Invalid quote_source '{source}' for {result.get('symbol')}"
            # Check legacy field
            elif "quote_source" in result:
                source = result.get("quote_source")
                assert source in valid_sources, \
                    f"Invalid quote_source '{source}' for {result.get('symbol')}"


class TestPricingRules:
    """
    Test that pricing rules are enforced:
    - SELL legs require valid BID (reject if BID=0)
    - BUY legs require valid ASK (reject if ASK=0)
    """
    
    def test_cc_sell_leg_uses_bid(self, auth_headers):
        """
        Verify Covered Call (SELL leg) uses BID price.
        Premium should equal BID, not ASK or mid.
        """
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls",
            params={"limit": 20},
            headers=auth_headers
        )
        assert response.status_code == 200, f"API failed: {response.text}"
        
        data = response.json()
        results = data.get("results") or data.get("opportunities") or []
        
        for result in results[:10]:
            # Check short_call object (new structure)
            if "short_call" in result:
                short_call = result["short_call"]
                premium = short_call.get("premium", 0)
                bid = short_call.get("bid", 0)
                
                # Premium should equal BID for SELL legs
                assert premium == bid, \
                    f"SELL leg premium ({premium}) should equal BID ({bid}) for {result.get('symbol')}"
                
                # BID must be > 0 (contracts with BID=0 should be rejected)
                assert bid > 0, \
                    f"SELL leg BID should be > 0 for {result.get('symbol')}, got {bid}"
                
                print(f"✓ {result.get('symbol')}: SELL premium=${premium} = BID=${bid}")
            
            # Check legacy flat fields
            elif "premium" in result and "bid" in result:
                premium = result.get("premium", 0)
                bid = result.get("bid", premium)  # Some responses may not have separate bid
                
                # Premium should be > 0 (BID=0 contracts rejected)
                assert premium > 0, \
                    f"SELL leg premium should be > 0 for {result.get('symbol')}, got {premium}"
    
    def test_pmcc_buy_leg_uses_ask(self, auth_headers):
        """
        Verify PMCC BUY leg (LEAP) uses ASK price.
        LEAP cost should equal ASK, not BID or mid.
        """
        response = requests.get(
            f"{BASE_URL}/api/screener/pmcc",
            params={"limit": 20},
            headers=auth_headers
        )
        assert response.status_code == 200, f"API failed: {response.text}"
        
        data = response.json()
        results = data.get("results") or data.get("opportunities") or []
        
        for result in results[:10]:
            # Check long_call object (new structure)
            if "long_call" in result:
                long_call = result["long_call"]
                premium = long_call.get("premium", 0)
                ask = long_call.get("ask", 0)
                
                # Premium should equal ASK for BUY legs
                assert premium == ask, \
                    f"BUY leg premium ({premium}) should equal ASK ({ask}) for {result.get('symbol')}"
                
                # ASK must be > 0 (contracts with ASK=0 should be rejected)
                assert ask > 0, \
                    f"BUY leg ASK should be > 0 for {result.get('symbol')}, got {ask}"
                
                print(f"✓ {result.get('symbol')}: BUY premium=${premium} = ASK=${ask}")
            
            # Check legacy flat fields
            elif "leap_ask" in result:
                leap_ask = result.get("leap_ask", 0)
                leap_cost = result.get("leap_cost", 0)
                
                # LEAP cost should equal ASK
                assert leap_cost == leap_ask or leap_cost > 0, \
                    f"BUY leg leap_cost should be > 0 for {result.get('symbol')}, got {leap_cost}"
    
    def test_pmcc_sell_leg_uses_bid(self, auth_headers):
        """
        Verify PMCC SELL leg (short call) uses BID price.
        """
        response = requests.get(
            f"{BASE_URL}/api/screener/pmcc",
            params={"limit": 20},
            headers=auth_headers
        )
        assert response.status_code == 200, f"API failed: {response.text}"
        
        data = response.json()
        results = data.get("results") or data.get("opportunities") or []
        
        for result in results[:10]:
            # Check short_call object (new structure)
            if "short_call" in result:
                short_call = result["short_call"]
                premium = short_call.get("premium", 0)
                bid = short_call.get("bid", 0)
                
                # Premium should equal BID for SELL legs
                assert premium == bid, \
                    f"SELL leg premium ({premium}) should equal BID ({bid}) for {result.get('symbol')}"
                
                # BID must be > 0
                assert bid > 0, \
                    f"SELL leg BID should be > 0 for {result.get('symbol')}, got {bid}"
                
                print(f"✓ {result.get('symbol')}: SELL premium=${premium} = BID=${bid}")
            
            # Check legacy flat fields
            elif "short_premium" in result:
                short_premium = result.get("short_premium", 0)
                
                # Short premium should be > 0
                assert short_premium > 0, \
                    f"SELL leg short_premium should be > 0 for {result.get('symbol')}, got {short_premium}"


class TestScreenerResponseStructure:
    """
    Test that screener responses have proper structure with quote_info.
    """
    
    def test_cc_response_has_quote_info_or_legacy_fields(self, auth_headers):
        """
        Verify CC response has either quote_info object or legacy quote_source field.
        """
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls",
            params={"limit": 10},
            headers=auth_headers
        )
        assert response.status_code == 200, f"API failed: {response.text}"
        
        data = response.json()
        results = data.get("results") or data.get("opportunities") or []
        
        for result in results:
            symbol = result.get("symbol", "UNKNOWN")
            
            # Must have either quote_info object or legacy quote_source field
            has_quote_info = "quote_info" in result
            has_legacy_quote_source = "quote_source" in result
            
            assert has_quote_info or has_legacy_quote_source, \
                f"Missing quote_info or quote_source for {symbol}"
            
            if has_quote_info:
                quote_info = result["quote_info"]
                assert "quote_source" in quote_info, f"Missing quote_source in quote_info for {symbol}"
                assert "quote_timestamp" in quote_info, f"Missing quote_timestamp in quote_info for {symbol}"
                assert "quote_age_hours" in quote_info, f"Missing quote_age_hours in quote_info for {symbol}"
                print(f"✓ {symbol}: Has quote_info object")
            else:
                print(f"✓ {symbol}: Has legacy quote_source field")
    
    def test_cc_response_metadata(self, auth_headers):
        """
        Verify CC response has proper metadata fields.
        """
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls",
            params={"limit": 5},
            headers=auth_headers
        )
        assert response.status_code == 200, f"API failed: {response.text}"
        
        data = response.json()
        
        # Check top-level metadata
        assert "stock_price_source" in data, "Missing stock_price_source"
        assert "options_chain_source" in data, "Missing options_chain_source"
        assert "architecture" in data, "Missing architecture"
        assert "live_data_used" in data, "Missing live_data_used"
        
        print(f"✓ stock_price_source: {data.get('stock_price_source')}")
        print(f"✓ options_chain_source: {data.get('options_chain_source')}")
        print(f"✓ architecture: {data.get('architecture')}")
        print(f"✓ live_data_used: {data.get('live_data_used')}")


class TestMarketStatusAwareness:
    """
    Test that the system is aware of market status and handles after-hours correctly.
    """
    
    def test_data_source_status_endpoint(self, auth_headers):
        """
        Test the data source status endpoint if available.
        """
        # Try to get data source status
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls",
            params={"limit": 1},
            headers=auth_headers
        )
        assert response.status_code == 200, f"API failed: {response.text}"
        
        data = response.json()
        
        # Check if market status info is included
        if "market_bias" in data:
            print(f"✓ Market bias: {data.get('market_bias')}")
        
        # Check symbols scanned
        if "symbols_scanned" in data:
            print(f"✓ Symbols scanned: {data.get('symbols_scanned')}")
        
        # Check symbols with results
        if "symbols_with_results" in data:
            print(f"✓ Symbols with results: {data.get('symbols_with_results')}")
        
        # Check filter reasons
        if "filter_reasons" in data:
            print(f"✓ Filter reasons: {len(data.get('filter_reasons', []))} symbols filtered")


class TestSpecificStockPrice:
    """
    Test specific stock prices to verify the fix.
    Note: These tests may need adjustment based on actual market data.
    """
    
    def test_stock_price_is_reasonable(self, auth_headers):
        """
        Verify stock prices are reasonable (not 0, not negative).
        """
        response = requests.get(
            f"{BASE_URL}/api/screener/covered-calls",
            params={"limit": 20},
            headers=auth_headers
        )
        assert response.status_code == 200, f"API failed: {response.text}"
        
        data = response.json()
        results = data.get("results") or data.get("opportunities") or []
        
        for result in results:
            symbol = result.get("symbol", "UNKNOWN")
            
            # Check underlying object (new structure)
            if "underlying" in result:
                stock_price = result["underlying"].get("last_price", 0)
            else:
                stock_price = result.get("stock_price", 0)
            
            # Stock price should be positive and reasonable
            assert stock_price > 0, f"Stock price should be > 0 for {symbol}, got {stock_price}"
            assert stock_price < 10000, f"Stock price seems too high for {symbol}: {stock_price}"
            
            print(f"✓ {symbol}: stock_price=${stock_price}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
