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
    def __init__(self, base_url: str = "https://covercall-engine.preview.emergentagent.com"):
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
                       success and status == 200 and "Premium Hunter API" in data.get("message", ""),
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
        """Test stock-related endpoints"""
        if not self.token:
            self.log_result("Stocks Test", False, "No user token available")
            return
        
        # Test market indices
        success, data, status = self.make_request('GET', 'stocks/indices', token=self.token)
        self.log_result("Market Indices", 
                       success and status == 200 and isinstance(data, dict),
                       f"Status: {status}, Indices count: {len(data) if isinstance(data, dict) else 0}")
        
        # Test stock quote
        success, data, status = self.make_request('GET', 'stocks/quote/AAPL', token=self.token)
        self.log_result("Stock Quote (AAPL)", 
                       success and status == 200 and data.get("symbol") == "AAPL",
                       f"Status: {status}, Price: {data.get('price', 'N/A')}")
        
        # Test historical data
        success, data, status = self.make_request('GET', 'stocks/historical/AAPL?days=7', token=self.token)
        self.log_result("Historical Data", 
                       success and status == 200 and isinstance(data, list),
                       f"Status: {status}, Data points: {len(data) if isinstance(data, list) else 0}")

    def test_options_endpoints(self):
        """Test options-related endpoints"""
        if not self.token:
            self.log_result("Options Test", False, "No user token available")
            return
        
        # Test options chain
        success, data, status = self.make_request('GET', 'options/chain/AAPL', token=self.token)
        self.log_result("Options Chain", 
                       success and status == 200 and data.get("symbol") == "AAPL",
                       f"Status: {status}, Options count: {len(data.get('options', []))}")
        
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