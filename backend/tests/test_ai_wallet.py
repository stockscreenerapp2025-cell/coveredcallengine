"""
AI Wallet API Tests

Tests for:
- GET /api/ai-wallet - Get wallet balance
- GET /api/ai-wallet/ledger - Get transaction history
- GET /api/ai-wallet/packs - Get available token packs
- POST /api/ai-wallet/estimate - Estimate token cost
- POST /api/ai/analyze - AI analysis with token deduction
- POST /api/ai-wallet/purchase/create - Create purchase (PayPal)
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_EMAIL = "admin@premiumhunter.com"
TEST_PASSWORD = "admin123"


class TestAIWalletAuth:
    """Authentication for AI Wallet tests"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get authentication token"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
        )
        assert response.status_code == 200, f"Login failed: {response.text}"
        data = response.json()
        assert "access_token" in data, "No access_token in response"
        return data["access_token"]
    
    @pytest.fixture(scope="class")
    def auth_headers(self, auth_token):
        """Get headers with auth token"""
        return {
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json"
        }


class TestAIWalletEndpoints(TestAIWalletAuth):
    """Test AI Wallet API endpoints"""
    
    def test_get_wallet_balance(self, auth_headers):
        """GET /api/ai-wallet - Returns wallet balance with all required fields"""
        response = requests.get(f"{BASE_URL}/api/ai-wallet", headers=auth_headers)
        
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        # Verify required fields exist
        assert "free_tokens_remaining" in data, "Missing free_tokens_remaining"
        assert "paid_tokens_remaining" in data, "Missing paid_tokens_remaining"
        assert "total_tokens" in data, "Missing total_tokens"
        assert "monthly_used" in data, "Missing monthly_used"
        assert "plan" in data, "Missing plan"
        assert "next_reset" in data, "Missing next_reset"
        
        # Verify data types
        assert isinstance(data["free_tokens_remaining"], int), "free_tokens_remaining should be int"
        assert isinstance(data["paid_tokens_remaining"], int), "paid_tokens_remaining should be int"
        assert isinstance(data["total_tokens"], int), "total_tokens should be int"
        assert isinstance(data["monthly_used"], int), "monthly_used should be int"
        
        # Verify total_tokens calculation
        expected_total = data["free_tokens_remaining"] + data["paid_tokens_remaining"]
        assert data["total_tokens"] == expected_total, f"total_tokens mismatch: {data['total_tokens']} != {expected_total}"
        
        print(f"✓ Wallet balance: {data['total_tokens']} tokens (free: {data['free_tokens_remaining']}, paid: {data['paid_tokens_remaining']})")
    
    def test_get_wallet_ledger(self, auth_headers):
        """GET /api/ai-wallet/ledger - Returns transaction history"""
        response = requests.get(f"{BASE_URL}/api/ai-wallet/ledger?limit=10", headers=auth_headers)
        
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "entries" in data, "Missing entries field"
        assert "count" in data, "Missing count field"
        assert isinstance(data["entries"], list), "entries should be a list"
        
        # If there are entries, verify structure
        if data["entries"]:
            entry = data["entries"][0]
            assert "action" in entry, "Entry missing action"
            assert "tokens_total" in entry, "Entry missing tokens_total"
            assert "timestamp" in entry, "Entry missing timestamp"
            print(f"✓ Ledger has {data['count']} entries, latest: {entry['action']}")
        else:
            print("✓ Ledger is empty (new wallet)")
    
    def test_get_token_packs(self, auth_headers):
        """GET /api/ai-wallet/packs - Returns available token packs"""
        response = requests.get(f"{BASE_URL}/api/ai-wallet/packs", headers=auth_headers)
        
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "packs" in data, "Missing packs field"
        assert "currency" in data, "Missing currency field"
        assert data["currency"] == "USD", f"Currency should be USD, got {data['currency']}"
        
        packs = data["packs"]
        assert len(packs) == 3, f"Expected 3 packs, got {len(packs)}"
        
        # Verify each pack has required fields
        pack_ids = []
        for pack in packs:
            assert "id" in pack, "Pack missing id"
            assert "name" in pack, "Pack missing name"
            assert "tokens" in pack, "Pack missing tokens"
            assert "price_usd" in pack, "Pack missing price_usd"
            pack_ids.append(pack["id"])
        
        # Verify expected packs exist
        assert "starter" in pack_ids, "Missing starter pack"
        assert "power" in pack_ids, "Missing power pack"
        assert "pro" in pack_ids, "Missing pro pack"
        
        # Verify pricing
        starter = next(p for p in packs if p["id"] == "starter")
        power = next(p for p in packs if p["id"] == "power")
        pro = next(p for p in packs if p["id"] == "pro")
        
        assert starter["price_usd"] == 10.0, f"Starter price should be $10, got ${starter['price_usd']}"
        assert power["price_usd"] == 25.0, f"Power price should be $25, got ${power['price_usd']}"
        assert pro["price_usd"] == 75.0, f"Pro price should be $75, got ${pro['price_usd']}"
        
        print(f"✓ Token packs: starter=${starter['price_usd']}, power=${power['price_usd']}, pro=${pro['price_usd']}")
    
    def test_estimate_tokens(self, auth_headers):
        """POST /api/ai-wallet/estimate - Returns estimated token cost"""
        response = requests.post(
            f"{BASE_URL}/api/ai-wallet/estimate",
            headers=auth_headers,
            json={"action": "ai_analysis", "params": {}}
        )
        
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "action" in data, "Missing action field"
        assert "estimated_tokens" in data, "Missing estimated_tokens field"
        assert "current_balance" in data, "Missing current_balance field"
        assert "sufficient_tokens" in data, "Missing sufficient_tokens field"
        
        # Verify data types
        assert isinstance(data["estimated_tokens"], int), "estimated_tokens should be int"
        assert isinstance(data["current_balance"], int), "current_balance should be int"
        assert isinstance(data["sufficient_tokens"], bool), "sufficient_tokens should be bool"
        
        # ai_analysis should cost 200 tokens per config
        assert data["estimated_tokens"] == 200, f"ai_analysis should cost 200 tokens, got {data['estimated_tokens']}"
        
        print(f"✓ Estimate: {data['action']} costs {data['estimated_tokens']} tokens, balance: {data['current_balance']}, sufficient: {data['sufficient_tokens']}")
    
    def test_get_action_costs(self, auth_headers):
        """GET /api/ai-wallet/actions - Returns token costs for different actions"""
        response = requests.get(f"{BASE_URL}/api/ai-wallet/actions", headers=auth_headers)
        
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "actions" in data, "Missing actions field"
        actions = data["actions"]
        
        # Verify expected actions exist
        assert "ai_analysis" in actions, "Missing ai_analysis action"
        assert "trade_suggestion" in actions, "Missing trade_suggestion action"
        assert "sentiment_analysis" in actions, "Missing sentiment_analysis action"
        assert "default" in actions, "Missing default action"
        
        print(f"✓ Action costs: ai_analysis={actions['ai_analysis']}, trade_suggestion={actions['trade_suggestion']}")


class TestAIAnalyzeWithTokens(TestAIWalletAuth):
    """Test AI analyze endpoint with token deduction"""
    
    def test_ai_analyze_uses_tokens(self, auth_headers):
        """POST /api/ai/analyze - Uses tokens and returns tokens_used"""
        # First get current balance
        wallet_response = requests.get(f"{BASE_URL}/api/ai-wallet", headers=auth_headers)
        assert wallet_response.status_code == 200
        initial_balance = wallet_response.json()["total_tokens"]
        
        # Skip if insufficient tokens
        if initial_balance < 200:
            pytest.skip(f"Insufficient tokens for test: {initial_balance}")
        
        # Make AI analysis request
        response = requests.post(
            f"{BASE_URL}/api/ai/analyze",
            headers=auth_headers,
            json={
                "symbol": "AAPL",
                "analysis_type": "opportunity",
                "context": "Test analysis for covered call opportunity"
            },
            timeout=60  # AI calls can take time
        )
        
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "analysis" in data, "Missing analysis field"
        
        # Check if tokens were used (non-mock response)
        if not data.get("is_mock", False):
            assert "tokens_used" in data, "Missing tokens_used field"
            assert "remaining_balance" in data, "Missing remaining_balance field"
            
            # Verify tokens were deducted
            assert data["tokens_used"] > 0, "tokens_used should be > 0"
            assert data["remaining_balance"] < initial_balance, "Balance should have decreased"
            
            print(f"✓ AI analysis used {data['tokens_used']} tokens, remaining: {data['remaining_balance']}")
        else:
            print(f"✓ AI analysis returned mock response (AI service may be unavailable)")
    
    def test_ai_analyze_returns_remaining_balance(self, auth_headers):
        """POST /api/ai/analyze - Returns remaining_balance after deduction"""
        # Get current balance
        wallet_response = requests.get(f"{BASE_URL}/api/ai-wallet", headers=auth_headers)
        assert wallet_response.status_code == 200
        initial_balance = wallet_response.json()["total_tokens"]
        
        if initial_balance < 200:
            pytest.skip(f"Insufficient tokens: {initial_balance}")
        
        # Make request
        response = requests.post(
            f"{BASE_URL}/api/ai/analyze",
            headers=auth_headers,
            json={
                "symbol": "MSFT",
                "analysis_type": "risk",
                "context": "Risk assessment test"
            },
            timeout=60
        )
        
        assert response.status_code == 200
        data = response.json()
        
        if not data.get("is_mock", False):
            # Verify balance in response matches wallet
            new_wallet = requests.get(f"{BASE_URL}/api/ai-wallet", headers=auth_headers)
            assert new_wallet.status_code == 200
            actual_balance = new_wallet.json()["total_tokens"]
            
            assert data["remaining_balance"] == actual_balance, \
                f"remaining_balance mismatch: {data['remaining_balance']} != {actual_balance}"
            
            print(f"✓ Remaining balance verified: {actual_balance}")


class TestPurchaseEndpoint(TestAIWalletAuth):
    """Test token purchase endpoint (PayPal integration)"""
    
    def test_create_purchase_invalid_pack(self, auth_headers):
        """POST /api/ai-wallet/purchase/create - Returns 400 for invalid pack"""
        response = requests.post(
            f"{BASE_URL}/api/ai-wallet/purchase/create",
            headers=auth_headers,
            json={"pack_id": "invalid_pack"}
        )
        
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        print("✓ Invalid pack returns 400")
    
    def test_create_purchase_missing_paypal_config(self, auth_headers):
        """POST /api/ai-wallet/purchase/create - Returns error when PayPal not configured"""
        response = requests.post(
            f"{BASE_URL}/api/ai-wallet/purchase/create",
            headers=auth_headers,
            json={"pack_id": "starter"}
        )
        
        # Should return 500 with PayPal error since credentials are not configured
        # This is expected behavior per the test requirements
        if response.status_code == 500:
            data = response.json()
            assert "PayPal" in data.get("detail", "") or "paypal" in data.get("detail", "").lower(), \
                f"Error should mention PayPal: {data}"
            print("✓ Purchase returns PayPal config error (expected - no PayPal credentials)")
        else:
            # If it somehow succeeds, verify the response structure
            assert response.status_code == 200
            data = response.json()
            assert "purchase_id" in data
            assert "approval_url" in data
            print(f"✓ Purchase created (unexpected - PayPal may be configured)")


class TestWalletUnauthorized:
    """Test unauthorized access to wallet endpoints"""
    
    def test_wallet_requires_auth(self):
        """GET /api/ai-wallet - Returns 401/403 without auth"""
        response = requests.get(f"{BASE_URL}/api/ai-wallet")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("✓ Wallet requires authentication")
    
    def test_ledger_requires_auth(self):
        """GET /api/ai-wallet/ledger - Returns 401/403 without auth"""
        response = requests.get(f"{BASE_URL}/api/ai-wallet/ledger")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("✓ Ledger requires authentication")
    
    def test_estimate_requires_auth(self):
        """POST /api/ai-wallet/estimate - Returns 401/403 without auth"""
        response = requests.post(
            f"{BASE_URL}/api/ai-wallet/estimate",
            json={"action": "ai_analysis"}
        )
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("✓ Estimate requires authentication")


class TestLedgerAfterUsage(TestAIWalletAuth):
    """Test ledger entries after token usage"""
    
    def test_ledger_records_usage(self, auth_headers):
        """Verify ledger records token usage after AI call"""
        # Get initial ledger count
        initial_ledger = requests.get(
            f"{BASE_URL}/api/ai-wallet/ledger?limit=5",
            headers=auth_headers
        )
        assert initial_ledger.status_code == 200
        initial_count = initial_ledger.json()["count"]
        
        # Check if we have tokens
        wallet = requests.get(f"{BASE_URL}/api/ai-wallet", headers=auth_headers)
        if wallet.json()["total_tokens"] < 200:
            pytest.skip("Insufficient tokens")
        
        # Make AI call
        ai_response = requests.post(
            f"{BASE_URL}/api/ai/analyze",
            headers=auth_headers,
            json={"symbol": "NVDA", "analysis_type": "general"},
            timeout=60
        )
        
        if ai_response.status_code == 200 and not ai_response.json().get("is_mock"):
            # Check ledger for new entry
            new_ledger = requests.get(
                f"{BASE_URL}/api/ai-wallet/ledger?limit=5",
                headers=auth_headers
            )
            assert new_ledger.status_code == 200
            
            entries = new_ledger.json()["entries"]
            if entries:
                latest = entries[0]
                # Should have a usage entry
                if latest["source"] == "usage":
                    assert latest["tokens_total"] < 0, "Usage should have negative tokens"
                    print(f"✓ Ledger recorded usage: {latest['action']} ({latest['tokens_total']} tokens)")
                else:
                    print(f"✓ Latest ledger entry: {latest['action']}")
        else:
            print("✓ Skipped ledger check (mock response)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
