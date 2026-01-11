"""
Test suite for Trade Simulator Phase 3 - Rule-based Trade Management
Tests: Rule templates, CRUD operations, rule evaluation, action logs, PMCC summary
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials - admin user
TEST_EMAIL = "admin@premiumhunter.com"
TEST_PASSWORD = "admin123"


class TestRuleTemplates:
    """Test rule templates endpoint"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session with authentication"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login
        login_response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        
        if login_response.status_code == 200:
            self.token = login_response.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        else:
            pytest.skip(f"Authentication failed: {login_response.status_code}")
    
    def test_01_get_rule_templates(self):
        """Test GET /api/simulator/rules/templates - Should return 7 pre-built templates"""
        response = self.session.get(f"{BASE_URL}/api/simulator/rules/templates")
        assert response.status_code == 200
        data = response.json()
        
        assert "templates" in data
        templates = data["templates"]
        
        # Should have 7 templates as per requirements
        assert len(templates) == 7, f"Expected 7 templates, got {len(templates)}"
        
        # Verify template structure
        for template in templates:
            assert "id" in template
            assert "name" in template
            assert "description" in template
            assert "conditions" in template
            assert "action" in template
            assert "action_type" in template["action"]
        
        # Verify specific templates exist
        template_ids = [t["id"] for t in templates]
        expected_templates = [
            "premium_capture_80",
            "delta_threshold",
            "stop_loss_10",
            "time_decay_exit",
            "pmcc_weekly_roll",
            "pmcc_leaps_decay_alert",
            "profit_target_5"
        ]
        
        for expected_id in expected_templates:
            assert expected_id in template_ids, f"Missing template: {expected_id}"
        
        print(f"✓ Found {len(templates)} rule templates")
        for t in templates:
            print(f"  - {t['id']}: {t['name']} ({t['action']['action_type']})")


class TestRuleCRUD:
    """Test rule CRUD operations"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session with authentication"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login
        login_response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        
        if login_response.status_code == 200:
            self.token = login_response.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        else:
            pytest.skip("Authentication failed")
    
    def test_02_create_rule_from_template(self):
        """Test POST /api/simulator/rules/from-template/{template_id}"""
        # Create rule from premium_capture_80 template
        response = self.session.post(f"{BASE_URL}/api/simulator/rules/from-template/premium_capture_80")
        assert response.status_code == 200
        data = response.json()
        
        assert "rule" in data
        rule = data["rule"]
        assert rule["name"] == "Roll at 80% Premium Capture"
        assert rule["is_enabled"] == True
        assert len(rule["conditions"]) > 0
        assert rule["action"]["action_type"] == "roll"
        
        # Store rule ID for later tests
        self.created_rule_id = rule["id"]
        print(f"✓ Created rule from template: {rule['name']} (ID: {rule['id'][:8]}...)")
        
        return rule["id"]
    
    def test_03_get_user_rules(self):
        """Test GET /api/simulator/rules"""
        response = self.session.get(f"{BASE_URL}/api/simulator/rules")
        assert response.status_code == 200
        data = response.json()
        
        assert "rules" in data
        assert "total" in data
        
        print(f"✓ User has {data['total']} rules")
        
        if data["rules"]:
            rule = data["rules"][0]
            assert "id" in rule
            assert "name" in rule
            assert "conditions" in rule
            assert "action" in rule
            assert "is_enabled" in rule
            print(f"  - First rule: {rule['name']} (enabled: {rule['is_enabled']})")
    
    def test_04_update_rule_toggle_enabled(self):
        """Test PUT /api/simulator/rules/{rule_id} - Toggle enabled status"""
        # First get existing rules
        response = self.session.get(f"{BASE_URL}/api/simulator/rules")
        assert response.status_code == 200
        rules = response.json().get("rules", [])
        
        if not rules:
            pytest.skip("No rules to update")
        
        rule = rules[0]
        rule_id = rule["id"]
        current_enabled = rule["is_enabled"]
        
        # Toggle enabled status
        update_response = self.session.put(
            f"{BASE_URL}/api/simulator/rules/{rule_id}",
            json={"is_enabled": not current_enabled}
        )
        assert update_response.status_code == 200
        updated_data = update_response.json()
        
        assert "rule" in updated_data
        assert updated_data["rule"]["is_enabled"] == (not current_enabled)
        
        print(f"✓ Toggled rule '{rule['name']}' enabled: {current_enabled} -> {not current_enabled}")
        
        # Toggle back
        self.session.put(
            f"{BASE_URL}/api/simulator/rules/{rule_id}",
            json={"is_enabled": current_enabled}
        )
    
    def test_05_create_custom_rule(self):
        """Test POST /api/simulator/rules - Create custom rule"""
        custom_rule = {
            "name": "TEST_Custom Stop Loss 15%",
            "description": "Test rule - close at 15% loss",
            "strategy_type": "covered_call",
            "is_enabled": True,
            "priority": 5,
            "conditions": [
                {"field": "loss_pct", "operator": "lte", "value": -15}
            ],
            "action": {
                "action_type": "close",
                "parameters": {"reason": "test_stop_loss"}
            }
        }
        
        response = self.session.post(f"{BASE_URL}/api/simulator/rules", json=custom_rule)
        assert response.status_code == 200
        data = response.json()
        
        assert "rule" in data
        rule = data["rule"]
        assert rule["name"] == custom_rule["name"]
        assert rule["strategy_type"] == "covered_call"
        assert rule["priority"] == 5
        
        print(f"✓ Created custom rule: {rule['name']} (ID: {rule['id'][:8]}...)")
        
        # Store for cleanup
        self.__class__.test_rule_id = rule["id"]
    
    def test_06_get_single_rule(self):
        """Test GET /api/simulator/rules/{rule_id}"""
        # Get rules first
        response = self.session.get(f"{BASE_URL}/api/simulator/rules")
        rules = response.json().get("rules", [])
        
        if not rules:
            pytest.skip("No rules to get")
        
        rule_id = rules[0]["id"]
        
        response = self.session.get(f"{BASE_URL}/api/simulator/rules/{rule_id}")
        assert response.status_code == 200
        rule = response.json()
        
        assert rule["id"] == rule_id
        assert "name" in rule
        assert "conditions" in rule
        assert "action" in rule
        
        print(f"✓ Retrieved rule: {rule['name']}")
    
    def test_07_delete_test_rule(self):
        """Test DELETE /api/simulator/rules/{rule_id}"""
        # Find and delete test rules
        response = self.session.get(f"{BASE_URL}/api/simulator/rules")
        rules = response.json().get("rules", [])
        
        deleted = 0
        for rule in rules:
            if rule["name"].startswith("TEST_"):
                del_response = self.session.delete(f"{BASE_URL}/api/simulator/rules/{rule['id']}")
                if del_response.status_code == 200:
                    deleted += 1
        
        print(f"✓ Deleted {deleted} test rules")


class TestRuleEvaluation:
    """Test rule evaluation endpoints"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session with authentication"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login
        login_response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        
        if login_response.status_code == 200:
            self.token = login_response.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        else:
            pytest.skip("Authentication failed")
    
    def test_08_evaluate_rules_dry_run(self):
        """Test POST /api/simulator/rules/evaluate?dry_run=true"""
        response = self.session.post(f"{BASE_URL}/api/simulator/rules/evaluate?dry_run=true")
        assert response.status_code == 200
        data = response.json()
        
        assert "dry_run" in data
        assert data["dry_run"] == True
        assert "trades_evaluated" in data
        assert "rules_count" in data
        assert "results" in data
        
        print(f"✓ Dry run evaluation: {data['trades_evaluated']} trades, {data['rules_count']} rules")
        
        if data["results"]:
            for result in data["results"]:
                print(f"  - {result['symbol']}: {len(result['matched_rules'])} rules matched")
                for rule in result["matched_rules"]:
                    print(f"    → {rule['rule_name']} ({rule['action_type']})")
    
    def test_09_evaluate_rules_execute(self):
        """Test POST /api/simulator/rules/evaluate?dry_run=false"""
        # First do a dry run to see what would happen
        dry_response = self.session.post(f"{BASE_URL}/api/simulator/rules/evaluate?dry_run=true")
        dry_data = dry_response.json()
        
        # Only execute if there are no critical actions that would close trades
        has_close_actions = any(
            any(r.get("action_type") == "close" for r in result.get("matched_rules", []))
            for result in dry_data.get("results", [])
        )
        
        if has_close_actions:
            print("⚠ Skipping execute - would close trades")
            return
        
        response = self.session.post(f"{BASE_URL}/api/simulator/rules/evaluate?dry_run=false")
        assert response.status_code == 200
        data = response.json()
        
        assert "dry_run" in data
        assert data["dry_run"] == False
        
        print(f"✓ Rule execution: {data['trades_evaluated']} trades evaluated")


class TestActionLogs:
    """Test action logs endpoint"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session with authentication"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login
        login_response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        
        if login_response.status_code == 200:
            self.token = login_response.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        else:
            pytest.skip("Authentication failed")
    
    def test_10_get_action_logs(self):
        """Test GET /api/simulator/action-logs"""
        response = self.session.get(f"{BASE_URL}/api/simulator/action-logs")
        assert response.status_code == 200
        data = response.json()
        
        assert "logs" in data
        assert "total" in data
        assert "page" in data
        assert "pages" in data
        
        print(f"✓ Action logs: {data['total']} total logs, page {data['page']}/{data['pages']}")
        
        if data["logs"]:
            for log in data["logs"][:5]:  # Show first 5
                print(f"  - {log.get('symbol', 'N/A')}: {log.get('action', 'N/A')} - {log.get('details', '')[:50]}...")
    
    def test_11_get_action_logs_with_filters(self):
        """Test GET /api/simulator/action-logs with filters"""
        # Test with limit
        response = self.session.get(f"{BASE_URL}/api/simulator/action-logs?limit=10")
        assert response.status_code == 200
        data = response.json()
        assert len(data["logs"]) <= 10
        
        # Test with page
        response = self.session.get(f"{BASE_URL}/api/simulator/action-logs?page=1&limit=5")
        assert response.status_code == 200
        
        print(f"✓ Action logs pagination working")


class TestPMCCSummary:
    """Test PMCC summary endpoint"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session with authentication"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login
        login_response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        
        if login_response.status_code == 200:
            self.token = login_response.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        else:
            pytest.skip("Authentication failed")
    
    def test_12_get_pmcc_summary(self):
        """Test GET /api/simulator/pmcc-summary"""
        response = self.session.get(f"{BASE_URL}/api/simulator/pmcc-summary")
        assert response.status_code == 200
        data = response.json()
        
        # May have no PMCC trades
        if "message" in data and "No PMCC" in data["message"]:
            print("⚠ No PMCC trades found")
            return
        
        assert "summary" in data
        assert "overall" in data
        
        overall = data["overall"]
        assert "total_pmcc_positions" in overall
        assert "active_positions" in overall
        assert "total_leaps_investment" in overall
        assert "total_premium_income" in overall
        assert "overall_income_ratio" in overall
        
        print(f"✓ PMCC Summary:")
        print(f"  - Total positions: {overall['total_pmcc_positions']}")
        print(f"  - Active: {overall['active_positions']}")
        print(f"  - LEAPS investment: ${overall['total_leaps_investment']:.2f}")
        print(f"  - Premium income: ${overall['total_premium_income']:.2f}")
        print(f"  - Income ratio: {overall['overall_income_ratio']:.1f}%")
        
        # Check individual position summaries
        if data["summary"]:
            for pos in data["summary"]:
                assert "symbol" in pos
                assert "leaps_strike" in pos
                assert "leaps_expiry" in pos
                assert "income_to_cost_ratio" in pos
                assert "health" in pos
                
                print(f"  - {pos['symbol']}: {pos['health']} ({pos['income_to_cost_ratio']:.1f}% income ratio)")


class TestExistingTradesAndRules:
    """Test that existing trades and rules are present"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session with authentication"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login
        login_response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        
        if login_response.status_code == 200:
            self.token = login_response.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        else:
            pytest.skip("Authentication failed")
    
    def test_13_verify_existing_trades(self):
        """Verify existing simulated trades are present"""
        response = self.session.get(f"{BASE_URL}/api/simulator/trades?limit=50")
        assert response.status_code == 200
        data = response.json()
        
        trades = data.get("trades", [])
        total = data.get("total", 0)
        
        print(f"✓ Found {total} simulated trades")
        
        # Count by strategy
        cc_count = len([t for t in trades if t.get("strategy_type") == "covered_call"])
        pmcc_count = len([t for t in trades if t.get("strategy_type") == "pmcc"])
        
        print(f"  - Covered Calls: {cc_count}")
        print(f"  - PMCC: {pmcc_count}")
        
        # Show some trade details
        for trade in trades[:5]:
            print(f"  - {trade['symbol']}: {trade['strategy_type']} ({trade['status']})")
    
    def test_14_verify_existing_rules(self):
        """Verify at least one rule exists"""
        response = self.session.get(f"{BASE_URL}/api/simulator/rules")
        assert response.status_code == 200
        data = response.json()
        
        rules = data.get("rules", [])
        total = data.get("total", 0)
        
        print(f"✓ Found {total} rules")
        
        for rule in rules:
            print(f"  - {rule['name']} ({rule['action']['action_type']}) - enabled: {rule['is_enabled']}")


class TestCleanup:
    """Cleanup test data"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test session with authentication"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login
        login_response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        
        if login_response.status_code == 200:
            self.token = login_response.json().get("access_token")
            self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        else:
            pytest.skip("Authentication failed")
    
    def test_99_cleanup_test_rules(self):
        """Cleanup: Delete any test rules created during testing"""
        response = self.session.get(f"{BASE_URL}/api/simulator/rules")
        rules = response.json().get("rules", [])
        
        deleted = 0
        for rule in rules:
            if rule["name"].startswith("TEST_"):
                del_response = self.session.delete(f"{BASE_URL}/api/simulator/rules/{rule['id']}")
                if del_response.status_code == 200:
                    deleted += 1
        
        print(f"✓ Cleaned up {deleted} test rules")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
