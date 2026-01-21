"""
Test suite for new features:
1. PMCC LEAPS minimum 12 months DTE
2. Dashboard Top 10 CC Strike format
3. Portfolio IBKR button (no 'Opens in new window' text)
4. AI sentiment analysis for news
5. Analyst ratings in Fundamentals tab
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://callscreener-1.preview.emergentagent.com')

class TestAuth:
    """Authentication tests"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@premiumhunter.com",
            "password": "admin123"
        })
        assert response.status_code == 200, f"Login failed: {response.text}"
        return response.json().get("access_token")
    
    def test_login_success(self):
        """Test login with valid credentials"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@premiumhunter.com",
            "password": "admin123"
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["user"]["email"] == "admin@premiumhunter.com"


class TestPMCCLeapsMinDTE:
    """Test PMCC LEAPS minimum 12 months (365 days) DTE"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@premiumhunter.com",
            "password": "admin123"
        })
        return response.json().get("access_token")
    
    def test_pmcc_conservative_leaps_dte(self, auth_token):
        """Test conservative PMCC scan has LEAPS with 365+ DTE"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/api/scans/pmcc/conservative", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        opportunities = data.get("opportunities", [])
        
        # Check that all LEAPS have at least 365 days DTE
        for opp in opportunities:
            long_dte = opp.get("long_dte", 0)
            assert long_dte >= 365, f"LEAPS DTE {long_dte} is less than 365 for {opp.get('symbol')}"
    
    def test_pmcc_balanced_leaps_dte(self, auth_token):
        """Test balanced PMCC scan has LEAPS with 365+ DTE"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/api/scans/pmcc/balanced", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        opportunities = data.get("opportunities", [])
        
        for opp in opportunities:
            long_dte = opp.get("long_dte", 0)
            assert long_dte >= 365, f"LEAPS DTE {long_dte} is less than 365 for {opp.get('symbol')}"
    
    def test_pmcc_aggressive_leaps_dte(self, auth_token):
        """Test aggressive PMCC scan has LEAPS with 365+ DTE"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/api/scans/pmcc/aggressive", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        opportunities = data.get("opportunities", [])
        
        for opp in opportunities:
            long_dte = opp.get("long_dte", 0)
            assert long_dte >= 365, f"LEAPS DTE {long_dte} is less than 365 for {opp.get('symbol')}"


class TestDashboardOpportunities:
    """Test Dashboard Top 10 CC opportunities"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@premiumhunter.com",
            "password": "admin123"
        })
        return response.json().get("access_token")
    
    def test_dashboard_opportunities_endpoint(self, auth_token):
        """Test dashboard opportunities endpoint returns data"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/api/screener/dashboard-opportunities", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        assert "opportunities" in data
        opportunities = data.get("opportunities", [])
        assert len(opportunities) > 0, "No opportunities returned"
    
    def test_opportunities_have_required_fields(self, auth_token):
        """Test opportunities have fields needed for Strike format"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/api/screener/dashboard-opportunities", headers=headers)
        
        data = response.json()
        opportunities = data.get("opportunities", [])
        
        for opp in opportunities[:5]:
            # Check required fields for Strike format (e.g., "16JAN26 $46 C")
            assert "strike" in opp, f"Missing 'strike' field for {opp.get('symbol')}"
            assert "dte" in opp or "expiry" in opp, f"Missing 'dte' or 'expiry' field for {opp.get('symbol')}"
            assert opp.get("strike") is not None, f"Strike is None for {opp.get('symbol')}"


class TestStockDetails:
    """Test Stock Details endpoint with Analyst Ratings"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@premiumhunter.com",
            "password": "admin123"
        })
        return response.json().get("access_token")
    
    def test_stock_details_endpoint(self, auth_token):
        """Test stock details endpoint returns data"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/api/stocks/details/INTC", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("symbol") == "INTC"
    
    def test_stock_details_has_analyst_ratings(self, auth_token):
        """Test stock details includes analyst ratings"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/api/stocks/details/AAPL", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        
        # Check analyst_ratings field exists
        assert "analyst_ratings" in data, "Missing 'analyst_ratings' field"
        analyst_ratings = data.get("analyst_ratings", {})
        
        # Check analyst ratings has expected fields
        if analyst_ratings:  # May be empty for some stocks
            # At least one of these fields should be present
            expected_fields = ["rating", "num_analysts", "target_price", "target_high", "target_low"]
            has_any_field = any(field in analyst_ratings for field in expected_fields)
            assert has_any_field, f"Analyst ratings missing expected fields: {analyst_ratings}"
    
    def test_stock_details_has_news(self, auth_token):
        """Test stock details includes news"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/api/stocks/details/INTC", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        
        # Check news field exists
        assert "news" in data, "Missing 'news' field"


class TestAISentimentAnalysis:
    """Test AI Sentiment Analysis endpoint"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@premiumhunter.com",
            "password": "admin123"
        })
        return response.json().get("access_token")
    
    def test_sentiment_analysis_endpoint_exists(self, auth_token):
        """Test sentiment analysis endpoint exists"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        
        # Send sample news items for analysis
        news_items = [
            {"title": "Intel Stock Surges on Strong Earnings", "description": "Intel reported better than expected Q4 results"},
            {"title": "Tech Sector Faces Headwinds", "description": "Rising interest rates impact growth stocks"}
        ]
        
        response = requests.post(
            f"{BASE_URL}/api/news/analyze-sentiment",
            headers=headers,
            json=news_items
        )
        
        assert response.status_code == 200, f"Sentiment analysis failed: {response.text}"
    
    def test_sentiment_analysis_returns_expected_fields(self, auth_token):
        """Test sentiment analysis returns expected fields"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        
        news_items = [
            {"title": "Apple Announces Record iPhone Sales", "description": "Strong demand in China drives growth"},
            {"title": "Market Rally Continues", "description": "S&P 500 hits new all-time high"}
        ]
        
        response = requests.post(
            f"{BASE_URL}/api/news/analyze-sentiment",
            headers=headers,
            json=news_items
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Check expected fields
        assert "overall_sentiment" in data, "Missing 'overall_sentiment' field"
        assert "overall_score" in data, "Missing 'overall_score' field"
        
        # Overall sentiment should be one of: Bullish, Bearish, Neutral, or similar
        overall_sentiment = data.get("overall_sentiment", "")
        valid_sentiments = ["Bullish", "Bearish", "Neutral", "Very Bullish", "Very Bearish"]
        assert overall_sentiment in valid_sentiments or overall_sentiment, f"Invalid sentiment: {overall_sentiment}"
        
        # Score should be 0-100
        score = data.get("overall_score", 0)
        assert 0 <= score <= 100, f"Score {score} out of range 0-100"


class TestPortfolioEndpoints:
    """Test Portfolio endpoints"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@premiumhunter.com",
            "password": "admin123"
        })
        return response.json().get("access_token")
    
    def test_portfolio_summary(self, auth_token):
        """Test portfolio summary endpoint"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/api/portfolio/summary", headers=headers)
        
        assert response.status_code == 200
    
    def test_ibkr_summary(self, auth_token):
        """Test IBKR summary endpoint"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/api/portfolio/ibkr/summary", headers=headers)
        
        assert response.status_code == 200
    
    def test_ibkr_trades(self, auth_token):
        """Test IBKR trades endpoint"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/api/portfolio/ibkr/trades", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        assert "trades" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
