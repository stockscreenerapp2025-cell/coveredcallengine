#!/usr/bin/env python3
"""
Focused test for Covered Call Engine Live Data Integration
Tests the specific requirements from the review request
"""

import requests
import json
from datetime import datetime

class LiveDataTester:
    def __init__(self):
        self.base_url = "https://option-strategy-hub-1.preview.emergentagent.com"
        self.token = None
        self.session = requests.Session()
        
    def login(self):
        """Login with admin credentials"""
        login_data = {
            "email": "admin@premiumhunter.com",
            "password": "admin123"
        }
        
        response = self.session.post(
            f"{self.base_url}/api/auth/login",
            json=login_data,
            headers={'Content-Type': 'application/json'}
        )
        
        if response.status_code == 200:
            data = response.json()
            self.token = data.get("access_token")
            print(f"✅ Authentication successful")
            return True
        else:
            print(f"❌ Authentication failed: {response.status_code}")
            return False
    
    def test_screener_covered_calls(self):
        """Test the main screener endpoint with specific parameters"""
        print("\n🔍 Testing Screener Covered Calls API")
        print("=" * 50)
        
        headers = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json'
        }
        
        # Test with exact parameters from review request
        response = self.session.get(
            f"{self.base_url}/api/screener/covered-calls?min_roi=0.5&max_dte=45",
            headers=headers
        )
        
        if response.status_code == 200:
            data = response.json()
            
            # Check basic response structure
            print(f"✅ API Response: {response.status_code}")
            print(f"✅ Opportunities found: {len(data.get('opportunities', []))}")
            
            # Critical test: Check for live data vs mock data
            is_live = data.get("is_live", False)
            is_mock = data.get("is_mock", False)
            
            print(f"\n🎯 CRITICAL VERIFICATION:")
            print(f"   is_live: {is_live}")
            print(f"   is_mock: {is_mock}")
            
            if is_live and not is_mock:
                print(f"✅ SUCCESS: Screener is returning LIVE data from Massive.com API")
            elif is_mock:
                print(f"❌ ISSUE: Screener is still returning MOCK data")
                return False
            else:
                print(f"⚠️  WARNING: Data source unclear")
            
            # Verify data structure
            opportunities = data.get("opportunities", [])
            if opportunities:
                sample = opportunities[0]
                required_fields = ["symbol", "stock_price", "strike", "expiry", "dte", "premium", "roi_pct", "delta", "iv", "volume", "open_interest", "score"]
                
                print(f"\n📊 Data Structure Verification:")
                for field in required_fields:
                    has_field = field in sample
                    print(f"   {field}: {'✅' if has_field else '❌'}")
                
                # Show sample opportunity
                print(f"\n📈 Sample Opportunity:")
                print(f"   Symbol: {sample.get('symbol', 'N/A')}")
                print(f"   Stock Price: ${sample.get('stock_price', 'N/A')}")
                print(f"   Strike: ${sample.get('strike', 'N/A')}")
                print(f"   Premium: ${sample.get('premium', 'N/A')}")
                print(f"   ROI: {sample.get('roi_pct', 'N/A')}%")
                print(f"   DTE: {sample.get('dte', 'N/A')} days")
                
            return is_live and not is_mock
        else:
            print(f"❌ API Error: {response.status_code}")
            return False
    
    def test_stock_quote(self):
        """Test stock quote API for AAPL"""
        print("\n📈 Testing Stock Quote API")
        print("=" * 50)
        
        headers = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json'
        }
        
        response = self.session.get(
            f"{self.base_url}/api/stocks/quote/AAPL",
            headers=headers
        )
        
        if response.status_code == 200:
            data = response.json()
            
            print(f"✅ API Response: {response.status_code}")
            print(f"✅ Symbol: {data.get('symbol', 'N/A')}")
            print(f"✅ Price: ${data.get('price', 'N/A')}")
            
            is_live = data.get("is_live", False)
            is_mock = data.get("is_mock", False)
            
            print(f"\n🎯 Data Source:")
            print(f"   is_live: {is_live}")
            print(f"   is_mock: {is_mock}")
            
            if is_live and not is_mock:
                print(f"✅ SUCCESS: Stock quote is LIVE data")
                return True
            else:
                print(f"❌ ISSUE: Stock quote is not live data")
                return False
        else:
            print(f"❌ API Error: {response.status_code}")
            return False
    
    def test_options_chain(self):
        """Test options chain API for AAPL"""
        print("\n⚡ Testing Options Chain API")
        print("=" * 50)
        
        headers = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json'
        }
        
        response = self.session.get(
            f"{self.base_url}/api/options/chain/AAPL",
            headers=headers
        )
        
        if response.status_code == 200:
            data = response.json()
            
            print(f"✅ API Response: {response.status_code}")
            print(f"✅ Symbol: {data.get('symbol', 'N/A')}")
            print(f"✅ Options count: {len(data.get('options', []))}")
            
            is_live = data.get("is_live", False)
            is_mock = data.get("is_mock", False)
            
            print(f"\n🎯 Data Source:")
            print(f"   is_live: {is_live}")
            print(f"   is_mock: {is_mock}")
            
            if is_live and not is_mock:
                print(f"✅ SUCCESS: Options chain is LIVE data")
                return True
            else:
                print(f"❌ ISSUE: Options chain is not live data")
                return False
        else:
            print(f"❌ API Error: {response.status_code}")
            return False
    
    def test_pmcc_screener(self):
        """Test PMCC screener API"""
        print("\n🔄 Testing PMCC Screener API")
        print("=" * 50)
        
        headers = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json'
        }
        
        response = self.session.get(
            f"{self.base_url}/api/screener/pmcc",
            headers=headers
        )
        
        if response.status_code == 200:
            data = response.json()
            
            print(f"✅ API Response: {response.status_code}")
            print(f"✅ PMCC Opportunities: {len(data.get('opportunities', []))}")
            
            is_live = data.get("is_live", False)
            is_mock = data.get("is_mock", False)
            
            print(f"\n🎯 Data Source:")
            print(f"   is_live: {is_live}")
            print(f"   is_mock: {is_mock}")
            
            # PMCC can be live or mock based on API availability
            print(f"✅ PMCC screener working (can be live or mock based on API availability)")
            return True
        else:
            print(f"❌ API Error: {response.status_code}")
            return False
    
    def run_tests(self):
        """Run all live data integration tests"""
        print("🚀 Covered Call Engine - Live Data Integration Test")
        print("=" * 60)
        print(f"Testing against: {self.base_url}")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        if not self.login():
            return False
        
        results = []
        results.append(self.test_screener_covered_calls())
        results.append(self.test_stock_quote())
        results.append(self.test_options_chain())
        results.append(self.test_pmcc_screener())
        
        print("\n" + "=" * 60)
        print("📊 FINAL RESULTS")
        print("=" * 60)
        
        passed = sum(results)
        total = len(results)
        
        test_names = [
            "Screener Covered Calls (CRITICAL)",
            "Stock Quote API",
            "Options Chain API", 
            "PMCC Screener API"
        ]
        
        for i, (test_name, result) in enumerate(zip(test_names, results)):
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"{status} {test_name}")
        
        print(f"\n🎯 Overall Result: {passed}/{total} tests passed")
        
        if results[0]:  # Most critical test
            print("✅ CRITICAL SUCCESS: Screener is returning LIVE data from Massive.com API")
        else:
            print("❌ CRITICAL FAILURE: Screener is NOT returning live data")
        
        return all(results)

if __name__ == "__main__":
    tester = LiveDataTester()
    success = tester.run_tests()
    exit(0 if success else 1)