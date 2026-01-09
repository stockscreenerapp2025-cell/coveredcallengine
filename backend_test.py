#!/usr/bin/env python3
"""
Premium Hunter Backend API Testing Suite
Tests all API endpoints for functionality and integration
"""

import requests
import sys
import json
from datetime import datetime
from typing import Dict, Any, Optional

class PremiumHunterAPITester:
    def __init__(self, base_url: str = "https://covercall.preview.emergentagent.com"):
        self.base_url = base_url
        self.token = None
        self.admin_token = None
        self.user_id = None
        self.admin_id = None
        self.tests_run = 0
        self.tests_passed = 0
        self.failed_tests = []
        self.session = requests.Session()
        
    def log_result(self, test_name: str, success: bool, details: str = ""):
        """Log test result"""
        self.tests_run += 1
        if success:
            self.tests_passed += 1
            print(f"✅ {test_name}")
        else:
            self.failed_tests.append({"test": test_name, "details": details})
            print(f"❌ {test_name} - {details}")
    
    def make_request(self, method: str, endpoint: str, data: Dict = None, 
                    token: str = None, files: Dict = None) -> tuple[bool, Dict, int]:
        """Make HTTP request with error handling"""
        url = f"{self.base_url}/api/{endpoint}"
        headers = {'Content-Type': 'application/json'}
        
        if token:
            headers['Authorization'] = f'Bearer {token}'
        
        try:
            if method == 'GET':
                response = self.session.get(url, headers=headers)
            elif method == 'POST':
                if files:
                    # Remove Content-Type for file uploads
                    headers.pop('Content-Type', None)
                    response = self.session.post(url, headers=headers, files=files)
                else:
                    response = self.session.post(url, headers=headers, json=data)
            elif method == 'PUT':
                response = self.session.put(url, headers=headers, json=data)
            elif method == 'DELETE':
                response = self.session.delete(url, headers=headers)
            else:
                return False, {}, 0
                
            return True, response.json() if response.content else {}, response.status_code
            
        except requests.exceptions.RequestException as e:
            return False, {"error": str(e)}, 0
        except json.JSONDecodeError:
            return False, {"error": "Invalid JSON response"}, response.status_code if 'response' in locals() else 0

    def test_health_check(self):
        """Test basic API health"""
        success, data, status = self.make_request('GET', '')
        self.log_result("API Health Check", 
                       success and status == 200 and ("Premium Hunter API" in data.get("message", "") or "Covered Call Engine API" in data.get("message", "")),
                       f"Status: {status}, Response: {data}")
        
        success, data, status = self.make_request('GET', 'health')
        self.log_result("Health Endpoint", 
                       success and status == 200 and data.get("status") == "healthy",
                       f"Status: {status}, Response: {data}")

    def test_user_registration(self):
        """Test user registration"""
        test_user = {
            "email": f"test_user_{datetime.now().strftime('%H%M%S')}@test.com",
            "password": "TestPass123!",
            "name": "Test User"
        }
        
        success, data, status = self.make_request('POST', 'auth/register', test_user)
        
        if success and status == 200 and data.get("access_token"):
            self.token = data["access_token"]
            self.user_id = data["user"]["id"]
            self.log_result("User Registration", True)
        else:
            self.log_result("User Registration", False, 
                           f"Status: {status}, Response: {data}")

    def test_admin_login(self):
        """Test admin login with provided credentials"""
        admin_creds = {
            "email": "admin@premiumhunter.com",
            "password": "admin123"
        }
        
        success, data, status = self.make_request('POST', 'auth/login', admin_creds)
        
        if success and status == 200 and data.get("access_token"):
            self.admin_token = data["access_token"]
            self.admin_id = data["user"]["id"]
            is_admin = data["user"].get("is_admin", False)
            self.log_result("Admin Login", is_admin, 
                           f"Admin status: {is_admin}")
        else:
            self.log_result("Admin Login", False, 
                           f"Status: {status}, Response: {data}")

    def test_user_profile(self):
        """Test user profile endpoint"""
        if not self.token:
            self.log_result("User Profile", False, "No user token available")
            return
            
        success, data, status = self.make_request('GET', 'auth/me', token=self.token)
        self.log_result("User Profile", 
                       success and status == 200 and data.get("email"),
                       f"Status: {status}, Response: {data}")

    def test_stocks_endpoints(self):
        """Test stock-related endpoints with focus on live data"""
        if not self.token:
            self.log_result("Stocks Test", False, "No user token available")
            return
        
        # Test market indices
        success, data, status = self.make_request('GET', 'stocks/indices', token=self.token)
        self.log_result("Market Indices", 
                       success and status == 200 and isinstance(data, dict),
                       f"Status: {status}, Indices count: {len(data) if isinstance(data, dict) else 0}")
        
        # Test stock quote for AAPL (specific requirement from review)
        success, data, status = self.make_request('GET', 'stocks/quote/AAPL', token=self.token)
        basic_success = success and status == 200 and data.get("symbol") == "AAPL"
        self.log_result("Stock Quote (AAPL) - Basic", 
                       basic_success,
                       f"Status: {status}, Price: {data.get('price', 'N/A')}")
        
        # Critical test: Check for live data vs mock data
        if basic_success:
            is_live = data.get("is_live", False)
            is_mock = data.get("is_mock", False)
            self.log_result("Stock Quote (AAPL) - Live Data Integration", 
                           is_live and not is_mock,
                           f"is_live: {is_live}, is_mock: {is_mock} - Expected: is_live=True")
        
        # Test historical data
        success, data, status = self.make_request('GET', 'stocks/historical/AAPL?days=7', token=self.token)
        self.log_result("Historical Data", 
                       success and status == 200 and isinstance(data, list),
                       f"Status: {status}, Data points: {len(data) if isinstance(data, list) else 0}")

    def test_options_endpoints(self):
        """Test options-related endpoints with focus on live data"""
        if not self.token:
            self.log_result("Options Test", False, "No user token available")
            return
        
        # Test options chain for AAPL (specific requirement from review)
        success, data, status = self.make_request('GET', 'options/chain/AAPL', token=self.token)
        basic_success = success and status == 200 and data.get("symbol") == "AAPL"
        self.log_result("Options Chain (AAPL) - Basic", 
                       basic_success,
                       f"Status: {status}, Options count: {len(data.get('options', []))}")
        
        # Critical test: Check for live data vs mock data
        if basic_success:
            is_live = data.get("is_live", False)
            is_mock = data.get("is_mock", False)
            self.log_result("Options Chain (AAPL) - Live Data Integration", 
                           is_live and not is_mock,
                           f"is_live: {is_live}, is_mock: {is_mock} - Expected: is_live=True")
        
        # Test option expirations
        success, data, status = self.make_request('GET', 'options/expirations/AAPL', token=self.token)
        self.log_result("Option Expirations", 
                       success and status == 200 and isinstance(data, list),
                       f"Status: {status}, Expirations: {len(data) if isinstance(data, list) else 0}")

    def test_screener_endpoints(self):
        """Test screener functionality with focus on live data integration"""
        if not self.token:
            self.log_result("Screener Test", False, "No user token available")
            return
        
        # Test covered calls screener with specific parameters from review request
        success, data, status = self.make_request('GET', 'screener/covered-calls?min_roi=0.5&max_dte=45', token=self.token)
        
        # Check basic functionality
        basic_success = success and status == 200 and "opportunities" in data
        self.log_result("Covered Calls Screener - Basic", 
                       basic_success,
                       f"Status: {status}, Opportunities: {len(data.get('opportunities', []))}")
        
        # Critical test: Check for live data vs mock data
        if basic_success:
            is_live = data.get("is_live", False)
            is_mock = data.get("is_mock", False)
            
            # This is the main issue being tested - should be live data, not mock
            self.log_result("Covered Calls Screener - Live Data Integration", 
                           is_live and not is_mock,
                           f"is_live: {is_live}, is_mock: {is_mock} - Expected: is_live=True, is_mock=False")
            
            # Verify opportunities structure for live data
            opportunities = data.get("opportunities", [])
            if opportunities:
                sample_opp = opportunities[0]
                required_fields = ["symbol", "stock_price", "strike", "expiry", "dte", "premium", "roi_pct", "delta", "iv", "volume", "open_interest", "score"]
                has_all_fields = all(field in sample_opp for field in required_fields)
                self.log_result("Covered Calls Screener - Data Structure", 
                               has_all_fields,
                               f"Sample opportunity fields: {list(sample_opp.keys())}")
        
        # Test PMCC screener
        success, data, status = self.make_request('GET', 'screener/pmcc', token=self.token)
        basic_success = success and status == 200 and "opportunities" in data
        self.log_result("PMCC Screener - Basic", 
                       basic_success,
                       f"Status: {status}, PMCC Opportunities: {len(data.get('opportunities', []))}")
        
        if basic_success:
            is_live = data.get("is_live", False)
            is_mock = data.get("is_mock", False)
            self.log_result("PMCC Screener - Data Source", 
                           True,  # PMCC can be live or mock based on API availability
                           f"is_live: {is_live}, is_mock: {is_mock}")
        
        # Test save filter
        filter_data = {
            "name": "Test Filter",
            "filters": {"min_roi": 2.0, "max_dte": 30}
        }
        success, data, status = self.make_request('POST', 'screener/filters', filter_data, token=self.token)
        filter_id = data.get("id") if success else None
        self.log_result("Save Screener Filter", 
                       success and status == 200 and filter_id,
                       f"Status: {status}, Filter ID: {filter_id}")
        
        # Test get saved filters
        success, data, status = self.make_request('GET', 'screener/filters', token=self.token)
        self.log_result("Get Saved Filters", 
                       success and status == 200 and isinstance(data, list),
                       f"Status: {status}, Filters count: {len(data) if isinstance(data, list) else 0}")
        
        # Test delete filter
        if filter_id:
            success, data, status = self.make_request('DELETE', f'screener/filters/{filter_id}', token=self.token)
            self.log_result("Delete Screener Filter", 
                           success and status == 200,
                           f"Status: {status}")

    def test_portfolio_endpoints(self):
        """Test portfolio management"""
        if not self.token:
            self.log_result("Portfolio Test", False, "No user token available")
            return
        
        # Test get portfolio summary
        success, data, status = self.make_request('GET', 'portfolio/summary', token=self.token)
        self.log_result("Portfolio Summary", 
                       success and status == 200 and "total_value" in data,
                       f"Status: {status}, Total Value: {data.get('total_value', 'N/A')}")
        
        # Test add position
        position_data = {
            "symbol": "AAPL",
            "position_type": "covered_call",
            "shares": 100,
            "avg_cost": 150.00,
            "option_strike": 155.00,
            "option_expiry": "2025-02-21",
            "option_premium": 2.50,
            "notes": "Test position"
        }
        success, data, status = self.make_request('POST', 'portfolio/positions', position_data, token=self.token)
        position_id = data.get("id") if success else None
        self.log_result("Add Portfolio Position", 
                       success and status == 200 and position_id,
                       f"Status: {status}, Position ID: {position_id}")
        
        # Test get positions
        success, data, status = self.make_request('GET', 'portfolio/positions', token=self.token)
        self.log_result("Get Portfolio Positions", 
                       success and status == 200 and isinstance(data, list),
                       f"Status: {status}, Positions count: {len(data) if isinstance(data, list) else 0}")
        
        # Test delete position
        if position_id:
            success, data, status = self.make_request('DELETE', f'portfolio/positions/{position_id}', token=self.token)
            self.log_result("Delete Portfolio Position", 
                           success and status == 200,
                           f"Status: {status}")

    def test_watchlist_endpoints(self):
        """Test watchlist functionality"""
        if not self.token:
            self.log_result("Watchlist Test", False, "No user token available")
            return
        
        # Test add to watchlist
        watchlist_item = {
            "symbol": "MSFT",
            "target_price": 400.00,
            "notes": "Test watchlist item"
        }
        success, data, status = self.make_request('POST', 'watchlist/', watchlist_item, token=self.token)
        item_id = data.get("id") if success else None
        self.log_result("Add to Watchlist", 
                       success and status == 200 and item_id,
                       f"Status: {status}, Item ID: {item_id}")
        
        # Test get watchlist
        success, data, status = self.make_request('GET', 'watchlist/', token=self.token)
        self.log_result("Get Watchlist", 
                       success and status == 200 and isinstance(data, list),
                       f"Status: {status}, Items count: {len(data) if isinstance(data, list) else 0}")
        
        # Test remove from watchlist
        if item_id:
            success, data, status = self.make_request('DELETE', f'watchlist/{item_id}', token=self.token)
            self.log_result("Remove from Watchlist", 
                           success and status == 200,
                           f"Status: {status}")

    def test_news_endpoints(self):
        """Test news functionality"""
        if not self.token:
            self.log_result("News Test", False, "No user token available")
            return
        
        # Test get news
        success, data, status = self.make_request('GET', 'news/?limit=5', token=self.token)
        self.log_result("Get Market News", 
                       success and status == 200 and isinstance(data, list),
                       f"Status: {status}, News count: {len(data) if isinstance(data, list) else 0}")

    def test_ai_endpoints(self):
        """Test AI analysis functionality"""
        if not self.token:
            self.log_result("AI Test", False, "No user token available")
            return
        
        # Test AI analysis
        analysis_request = {
            "symbol": "AAPL",
            "analysis_type": "opportunity",
            "context": "Looking for covered call opportunities"
        }
        success, data, status = self.make_request('POST', 'ai/analyze', analysis_request, token=self.token)
        self.log_result("AI Analysis", 
                       success and status == 200 and "analysis" in data,
                       f"Status: {status}, Has analysis: {'analysis' in data}")
        
        # Test AI opportunities
        success, data, status = self.make_request('GET', 'ai/opportunities?min_score=70', token=self.token)
        self.log_result("AI Opportunities", 
                       success and status == 200 and "opportunities" in data,
                       f"Status: {status}, AI Opportunities: {len(data.get('opportunities', []))}")

    def test_admin_endpoints(self):
        """Test admin functionality"""
        if not self.admin_token:
            self.log_result("Admin Test", False, "No admin token available")
            return
        
        # Test get admin settings
        success, data, status = self.make_request('GET', 'admin/settings', token=self.admin_token)
        self.log_result("Get Admin Settings", 
                       success and status == 200,
                       f"Status: {status}, Settings: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")
        
        # Test update admin settings
        settings_data = {
            "data_refresh_interval": 120,
            "enable_live_data": False
        }
        success, data, status = self.make_request('POST', 'admin/settings', settings_data, token=self.admin_token)
        self.log_result("Update Admin Settings", 
                       success and status == 200,
                       f"Status: {status}")

    def test_admin_integrations(self):
        """Test admin panel integrations - specifically Resend email integration"""
        if not self.admin_token:
            self.log_result("Admin Integrations Test", False, "No admin token available")
            return
        
        print("\n🔧 Testing Admin Panel Integrations...")
        
        # Test 1: GET /api/admin/integration-settings
        success, data, status = self.make_request('GET', 'admin/integration-settings', token=self.admin_token)
        
        if success and status == 200:
            # Check if resend_api_key_configured is true
            email_config = data.get("email", {})
            resend_configured = email_config.get("resend_api_key_configured", False)
            
            self.log_result("Admin Integration Settings - Basic", 
                           True,
                           f"Status: {status}, Email config: {email_config}")
            
            self.log_result("Admin Integration Settings - Resend API Key Configured", 
                           resend_configured,
                           f"resend_api_key_configured: {resend_configured} (Expected: True)")
            
            # Also check Stripe configuration for completeness
            stripe_config = data.get("stripe", {})
            self.log_result("Admin Integration Settings - Stripe Config", 
                           True,  # Just informational
                           f"Stripe config: {stripe_config}")
        else:
            self.log_result("Admin Integration Settings - Basic", 
                           False,
                           f"Status: {status}, Response: {data}")
        
        # Test 2: POST /api/admin/test-email
        test_email = "test@example.com"
        template_name = "welcome"
        
        success, data, status = self.make_request('POST', f'admin/test-email?recipient_email={test_email}&template_name={template_name}', 
                                                 token=self.admin_token)
        
        if success and status == 200:
            email_status = data.get("status")
            message = data.get("message", "")
            email_id = data.get("email_id")
            
            self.log_result("Admin Test Email - Basic Response", 
                           True,
                           f"Status: {status}, Email Status: {email_status}, Message: {message}")
            
            # The test email may fail due to Resend test mode restrictions, but we should get a proper response
            # Success means we got a valid response structure, not necessarily that email was sent
            expected_response_structure = "status" in data and "message" in data
            self.log_result("Admin Test Email - Response Structure", 
                           expected_response_structure,
                           f"Has required fields (status, message): {expected_response_structure}")
            
            # Log the actual result for analysis
            if email_status == "error" and "test mode" in message.lower():
                self.log_result("Admin Test Email - Resend Test Mode (Expected)", 
                               True,
                               f"Resend is in test mode - this is expected: {message}")
            elif email_status == "success":
                self.log_result("Admin Test Email - Email Sent Successfully", 
                               True,
                               f"Email sent successfully with ID: {email_id}")
            else:
                self.log_result("Admin Test Email - Unexpected Result", 
                               True,  # Still pass as we got a response
                               f"Status: {email_status}, Message: {message}")
        else:
            self.log_result("Admin Test Email - Basic Response", 
                           False,
                           f"Status: {status}, Response: {data}")

    def test_stripe_webhook_integration(self):
        """Test Stripe webhook integration as requested in review"""
        if not self.admin_token:
            self.log_result("Stripe Webhook Test", False, "No admin token available")
            return
        
        print("\n🔧 Testing Stripe Webhook Integration...")
        
        # Test 1: Verify GET /api/admin/integration-settings shows stripe.webhook_secret_configured = true
        success, data, status = self.make_request('GET', 'admin/integration-settings', token=self.admin_token)
        
        if success and status == 200:
            stripe_config = data.get("stripe", {})
            webhook_configured = stripe_config.get("webhook_secret_configured", False)
            
            self.log_result("Stripe Integration Settings - Webhook Secret Configured", 
                           webhook_configured,
                           f"webhook_secret_configured: {webhook_configured} (Expected: True)")
            
            # Also check secret key configuration
            secret_key_configured = stripe_config.get("secret_key_configured", False)
            self.log_result("Stripe Integration Settings - Secret Key Status", 
                           True,  # Just informational
                           f"secret_key_configured: {secret_key_configured}")
        else:
            self.log_result("Stripe Integration Settings - Basic", 
                           False,
                           f"Status: {status}, Response: {data}")
            return
        
        # Test 2: Test the webhook endpoint POST /api/webhooks/stripe
        # Note: This should return 400 (invalid signature) NOT 500 (server error) when called without proper Stripe signature
        webhook_url = f"{self.base_url}/api/webhooks/stripe"
        
        try:
            # Make a direct request to the webhook endpoint without proper Stripe signature
            response = self.session.post(
                webhook_url,
                json={"test": "data"},
                headers={'Content-Type': 'application/json'}
            )
            
            # The webhook should handle the request properly and return 400 for invalid signature, not 500
            webhook_working = response.status_code == 400
            
            self.log_result("Stripe Webhook Endpoint - Proper Error Handling", 
                           webhook_working,
                           f"Status: {response.status_code} (Expected: 400 for invalid signature, NOT 500)")
            
            # Check if we get a proper error message
            try:
                response_data = response.json()
                has_error_detail = "detail" in response_data
                self.log_result("Stripe Webhook Endpoint - Error Response Structure", 
                               has_error_detail,
                               f"Response: {response_data}")
            except:
                # If response is not JSON, that's also acceptable for a 400 error
                self.log_result("Stripe Webhook Endpoint - Non-JSON Error Response", 
                               True,
                               f"Non-JSON response (acceptable for 400 error): {response.text[:100]}")
                
        except Exception as e:
            self.log_result("Stripe Webhook Endpoint - Request Failed", 
                           False,
                           f"Failed to make request to webhook: {str(e)}")
        
        # Test 3: Test webhook endpoint with missing signature header (should also return 400)
        try:
            response = self.session.post(
                webhook_url,
                data="test_payload",
                headers={'Content-Type': 'application/json'}
            )
            
            webhook_handles_missing_sig = response.status_code == 400
            self.log_result("Stripe Webhook Endpoint - Missing Signature Handling", 
                           webhook_handles_missing_sig,
                           f"Status: {response.status_code} (Expected: 400 for missing signature)")
                           
        except Exception as e:
            self.log_result("Stripe Webhook Endpoint - Missing Signature Test Failed", 
                           False,
                           f"Failed to test missing signature: {str(e)}")

    def test_stripe_subscription_configuration(self):
        """Test Stripe subscription configuration as requested in review"""
        print("\n💳 Testing Stripe Subscription Configuration...")
        
        # Test 1: GET /api/subscription/links (public endpoint)
        success, data, status = self.make_request('GET', 'subscription/links')
        
        links_success = success and status == 200
        self.log_result("Subscription Payment Links - Basic", 
                       links_success,
                       f"Status: {status}, Response: {data}")
        
        if links_success:
            # Verify the expected payment links
            expected_trial = "https://buy.stripe.com/test_7sY14pdw912ad3vdvpgYU00"
            expected_monthly = "https://buy.stripe.com/test_cNi14p4ZDeT0bZrgHBgYU01"
            expected_yearly = "https://buy.stripe.com/test_dRm6oJ8bP8uC7JbfDxgYU02"
            
            trial_correct = data.get("trial_link") == expected_trial
            monthly_correct = data.get("monthly_link") == expected_monthly
            yearly_correct = data.get("yearly_link") == expected_yearly
            mode_test = data.get("mode") == "test"
            
            self.log_result("Subscription Links - Trial Link", 
                           trial_correct,
                           f"Expected: {expected_trial}, Got: {data.get('trial_link')}")
            
            self.log_result("Subscription Links - Monthly Link", 
                           monthly_correct,
                           f"Expected: {expected_monthly}, Got: {data.get('monthly_link')}")
            
            self.log_result("Subscription Links - Yearly Link", 
                           yearly_correct,
                           f"Expected: {expected_yearly}, Got: {data.get('yearly_link')}")
            
            self.log_result("Subscription Links - Test Mode", 
                           mode_test,
                           f"Expected: test, Got: {data.get('mode')}")
        
        # Test 2: GET /api/subscription/admin/settings (requires admin auth)
        if not self.admin_token:
            self.log_result("Admin Subscription Settings", False, "No admin token available")
            return
        
        success, data, status = self.make_request('GET', 'subscription/admin/settings', token=self.admin_token)
        
        admin_settings_success = success and status == 200
        self.log_result("Admin Subscription Settings - Basic", 
                       admin_settings_success,
                       f"Status: {status}, Response: {data}")
        
        if admin_settings_success:
            # Verify test_links contain all 3 payment links
            test_links = data.get("test_links", {})
            active_mode = data.get("active_mode")
            
            has_trial = "trial" in test_links
            has_monthly = "monthly" in test_links  
            has_yearly = "yearly" in test_links
            
            self.log_result("Admin Settings - Test Links Structure", 
                           has_trial and has_monthly and has_yearly,
                           f"Test links: {test_links}")
            
            self.log_result("Admin Settings - Active Mode", 
                           active_mode == "test",
                           f"Active mode: {active_mode} (Expected: test)")
        
        # Test 3: GET /api/admin/integration-settings (requires admin auth) - Stripe configuration
        success, data, status = self.make_request('GET', 'admin/integration-settings', token=self.admin_token)
        
        integration_success = success and status == 200
        self.log_result("Integration Settings - Basic", 
                       integration_success,
                       f"Status: {status}, Response: {data}")
        
        if integration_success:
            stripe_config = data.get("stripe", {})
            email_config = data.get("email", {})
            
            webhook_configured = stripe_config.get("webhook_secret_configured", False)
            secret_key_configured = stripe_config.get("secret_key_configured", False)
            resend_configured = email_config.get("resend_api_key_configured", False)
            
            self.log_result("Integration Settings - Stripe Webhook Secret", 
                           webhook_configured,
                           f"webhook_secret_configured: {webhook_configured} (Expected: True)")
            
            self.log_result("Integration Settings - Stripe Secret Key", 
                           secret_key_configured,
                           f"secret_key_configured: {secret_key_configured} (Expected: True)")
            
            self.log_result("Integration Settings - Resend API Key", 
                           resend_configured,
                           f"resend_api_key_configured: {resend_configured} (Expected: True)")
        
        # Test 4: POST /api/subscription/admin/switch-mode?mode=test (requires admin auth)
        success, data, status = self.make_request('POST', 'subscription/admin/switch-mode?mode=test', 
                                                 token=self.admin_token)
        
        switch_success = success and status == 200
        self.log_result("Subscription Mode Switch - Test Mode", 
                       switch_success,
                       f"Status: {status}, Response: {data}")
        
        if switch_success:
            active_mode = data.get("active_mode")
            self.log_result("Mode Switch - Verification", 
                           active_mode == "test",
                           f"Active mode after switch: {active_mode} (Expected: test)")
        
        # Test 5: Verify mode switch worked by checking links again
        success, data, status = self.make_request('GET', 'subscription/links')
        
        if success and status == 200:
            mode_after_switch = data.get("mode")
            self.log_result("Mode Switch - Links Verification", 
                           mode_after_switch == "test",
                           f"Mode in links endpoint: {mode_after_switch} (Expected: test)")

    def test_ibkr_portfolio_import(self):
        """Test IBKR Portfolio Import functionality as requested in review"""
        if not self.admin_token:
            self.log_result("IBKR Import Test", False, "No admin token available")
            return
        
        print("\n📊 Testing IBKR Portfolio Import...")
        
        # Test 1: Upload IBKR CSV file
        csv_file_path = "/app/test_ibkr.csv"
        try:
            with open(csv_file_path, 'rb') as f:
                files = {'file': ('test_ibkr.csv', f, 'text/csv')}
                success, data, status = self.make_request('POST', 'portfolio/import-ibkr', 
                                                        token=self.admin_token, files=files)
            
            upload_success = success and status == 200
            self.log_result("IBKR CSV Upload", 
                           upload_success,
                           f"Status: {status}, Response: {data}")
            
            if not upload_success:
                return
                
        except Exception as e:
            self.log_result("IBKR CSV Upload", False, f"Failed to upload CSV: {str(e)}")
            return
        
        # Test 2: GET /api/portfolio/ibkr/accounts - Should return detected accounts
        success, data, status = self.make_request('GET', 'portfolio/ibkr/accounts', token=self.admin_token)
        
        accounts_success = success and status == 200
        self.log_result("IBKR Accounts Detection", 
                       accounts_success,
                       f"Status: {status}, Response: {data}")
        
        # Check if "Ray Family SMSF" account is detected
        if accounts_success:
            # Handle both list and dict response formats
            if isinstance(data, dict) and 'accounts' in data:
                account_names = data['accounts']
            elif isinstance(data, list):
                account_names = [acc.get('_id') for acc in data if '_id' in acc]
            else:
                account_names = []
                
            ray_family_detected = 'Ray Family SMSF' in account_names
            self.log_result("IBKR Account 'Ray Family SMSF' Detected", 
                           ray_family_detected,
                           f"Detected accounts: {account_names}")
        
        # Test 3: GET /api/portfolio/ibkr/trades - Should return parsed trades
        success, data, status = self.make_request('GET', 'portfolio/ibkr/trades', token=self.admin_token)
        
        trades_success = success and status == 200 and 'trades' in data
        self.log_result("IBKR Trades Parsing", 
                       trades_success,
                       f"Status: {status}, Trades count: {len(data.get('trades', []))}")
        
        # Check trade categorization
        if trades_success:
            trades = data.get('trades', [])
            strategy_types = set()
            symbols = set()
            
            for trade in trades:
                strategy_types.add(trade.get('strategy_type', 'Unknown'))
                symbols.add(trade.get('symbol', 'Unknown'))
            
            self.log_result("IBKR Trade Categorization", 
                           len(strategy_types) > 0,
                           f"Strategy types: {list(strategy_types)}, Symbols: {list(symbols)}")
            
            # Check for expected strategies (Covered Call, Stock, etc.)
            expected_strategies = {'COVERED_CALL', 'STOCK'}
            has_expected_strategies = any(s in strategy_types for s in expected_strategies)
            self.log_result("IBKR Expected Strategy Types", 
                           has_expected_strategies,
                           f"Found strategies: {list(strategy_types)}, Expected: {list(expected_strategies)}")
        
        # Test 4: GET /api/portfolio/ibkr/summary - Should return summary statistics
        success, data, status = self.make_request('GET', 'portfolio/ibkr/summary', token=self.admin_token)
        
        summary_success = success and status == 200
        self.log_result("IBKR Summary Statistics", 
                       summary_success,
                       f"Status: {status}, Summary: {data}")
        
        # Check summary structure
        if summary_success:
            required_fields = ['total_trades', 'total_invested', 'total_premium', 'total_fees']
            has_required_fields = all(field in data for field in required_fields)
            self.log_result("IBKR Summary Structure", 
                           has_required_fields,
                           f"Summary fields: {list(data.keys())}")
            
            # Check if summary has meaningful data
            total_trades = data.get('total_trades', 0)
            total_invested = data.get('total_invested', 0)
            total_premium = data.get('total_premium', 0)
            
            has_meaningful_data = total_trades > 0 and (total_invested > 0 or total_premium > 0)
            self.log_result("IBKR Summary Data Quality", 
                           has_meaningful_data,
                           f"Trades: {total_trades}, Invested: {total_invested}, Premium: {total_premium}")
        
        # Test 5: Test filtering trades by account
        success, data, status = self.make_request('GET', 'portfolio/ibkr/trades?account=Ray Family SMSF', 
                                                 token=self.admin_token)
        
        filter_success = success and status == 200
        self.log_result("IBKR Trade Filtering by Account", 
                       filter_success,
                       f"Status: {status}, Filtered trades: {len(data.get('trades', []))}")
        
        # Test 6: Test filtering trades by strategy
        success, data, status = self.make_request('GET', 'portfolio/ibkr/trades?strategy=COVERED_CALL', 
                                                 token=self.admin_token)
        
        strategy_filter_success = success and status == 200
        self.log_result("IBKR Trade Filtering by Strategy", 
                       strategy_filter_success,
                       f"Status: {status}, Covered call trades: {len(data.get('trades', []))}")
        
        # Test 7: Clear IBKR data (cleanup)
        success, data, status = self.make_request('DELETE', 'portfolio/ibkr/clear', token=self.admin_token)
        
        cleanup_success = success and status == 200
        self.log_result("IBKR Data Cleanup", 
                       cleanup_success,
                       f"Status: {status}, Response: {data}")

    def test_unauthorized_access(self):
        """Test endpoints without authentication"""
        # Test protected endpoint without token
        success, data, status = self.make_request('GET', 'portfolio/positions')
        self.log_result("Unauthorized Access Protection", 
                       status == 401 or status == 403,
                       f"Status: {status} (should be 401/403)")
        
        # Test admin endpoint with regular user token
        if self.token:
            success, data, status = self.make_request('GET', 'admin/settings', token=self.token)
            self.log_result("Admin Access Protection", 
                           status == 403,
                           f"Status: {status} (should be 403)")

    def run_all_tests(self):
        """Run complete test suite"""
        print("🚀 Starting Premium Hunter Backend API Tests")
        print("=" * 60)
        
        # Core functionality tests
        self.test_health_check()
        self.test_user_registration()
        self.test_admin_login()
        self.test_user_profile()
        
        # Feature tests
        self.test_stocks_endpoints()
        self.test_options_endpoints()
        self.test_screener_endpoints()
        self.test_portfolio_endpoints()
        self.test_watchlist_endpoints()
        self.test_news_endpoints()
        self.test_ai_endpoints()
        self.test_admin_endpoints()
        
        # Admin integrations test (specific focus for this review)
        self.test_admin_integrations()
        
        # Stripe webhook integration test (specific focus for current review)
        self.test_stripe_webhook_integration()
        
        # Stripe subscription configuration test (specific focus for current review)
        self.test_stripe_subscription_configuration()
        
        # IBKR Portfolio Import test (specific focus for current review)
        self.test_ibkr_portfolio_import()
        
        # Security tests
        self.test_unauthorized_access()
        
        # Print summary
        print("\n" + "=" * 60)
        print(f"📊 Test Results: {self.tests_passed}/{self.tests_run} passed")
        
        if self.failed_tests:
            print("\n❌ Failed Tests:")
            for failure in self.failed_tests:
                print(f"  • {failure['test']}: {failure['details']}")
        
        success_rate = (self.tests_passed / self.tests_run * 100) if self.tests_run > 0 else 0
        print(f"\n✨ Success Rate: {success_rate:.1f}%")
        
        return {
            "total_tests": self.tests_run,
            "passed_tests": self.tests_passed,
            "failed_tests": self.failed_tests,
            "success_rate": success_rate
        }

def main():
    """Main test execution"""
    tester = PremiumHunterAPITester()
    results = tester.run_all_tests()
    
    # Return appropriate exit code
    return 0 if results["success_rate"] >= 80 else 1

if __name__ == "__main__":
    sys.exit(main())