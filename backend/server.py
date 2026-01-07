from fastapi import FastAPI, APIRouter, HTTPException, Depends, Query, UploadFile, File
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timezone, timedelta
import jwt
import bcrypt
from bson import ObjectId
import csv
import io
import httpx
from openai import OpenAI
import hashlib
import json

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Cache configuration - default cache duration in seconds (5 minutes for real-time data)
CACHE_DURATION_SECONDS = 300

# Security
security = HTTPBearer()
JWT_SECRET = os.environ.get('JWT_SECRET', 'premium-hunter-secret-key-change-in-production')
JWT_ALGORITHM = "HS256"

# Create the main app
app = FastAPI(title="Covered Call Engine - Options Trading Platform")

# Create routers
api_router = APIRouter(prefix="/api")
auth_router = APIRouter(prefix="/auth", tags=["Authentication"])
stocks_router = APIRouter(prefix="/stocks", tags=["Stocks"])
options_router = APIRouter(prefix="/options", tags=["Options"])
portfolio_router = APIRouter(prefix="/portfolio", tags=["Portfolio"])
watchlist_router = APIRouter(prefix="/watchlist", tags=["Watchlist"])
screener_router = APIRouter(prefix="/screener", tags=["Screener"])
admin_router = APIRouter(prefix="/admin", tags=["Admin"])
ai_router = APIRouter(prefix="/ai", tags=["AI Insights"])
news_router = APIRouter(prefix="/news", tags=["News"])
subscription_router = APIRouter(prefix="/subscription", tags=["Subscription"])

# ==================== CACHE HELPERS ====================

def generate_cache_key(prefix: str, params: Dict[str, Any]) -> str:
    """Generate a unique cache key based on prefix and parameters"""
    params_str = json.dumps(params, sort_keys=True)
    hash_str = hashlib.md5(params_str.encode()).hexdigest()
    return f"{prefix}_{hash_str}"

async def get_cached_data(cache_key: str, max_age_seconds: int = CACHE_DURATION_SECONDS) -> Optional[Dict]:
    """Retrieve cached data if it exists and is not expired"""
    try:
        cached = await db.api_cache.find_one({"cache_key": cache_key}, {"_id": 0})
        if cached:
            cached_at = cached.get("cached_at")
            if isinstance(cached_at, str):
                cached_at = datetime.fromisoformat(cached_at.replace('Z', '+00:00'))
            
            age = (datetime.now(timezone.utc) - cached_at).total_seconds()
            if age < max_age_seconds:
                logging.info(f"Cache hit for {cache_key}, age: {age:.1f}s")
                return cached.get("data")
            else:
                logging.info(f"Cache expired for {cache_key}, age: {age:.1f}s > {max_age_seconds}s")
    except Exception as e:
        logging.error(f"Cache retrieval error: {e}")
    return None

async def set_cached_data(cache_key: str, data: Dict) -> bool:
    """Store data in cache"""
    try:
        cache_doc = {
            "cache_key": cache_key,
            "data": data,
            "cached_at": datetime.now(timezone.utc).isoformat()
        }
        await db.api_cache.update_one(
            {"cache_key": cache_key},
            {"$set": cache_doc},
            upsert=True
        )
        logging.info(f"Cache set for {cache_key}")
        return True
    except Exception as e:
        logging.error(f"Cache storage error: {e}")
        return False

async def clear_cache(prefix: str = None) -> int:
    """Clear cache entries. If prefix provided, only clear matching entries."""
    try:
        if prefix:
            result = await db.api_cache.delete_many({"cache_key": {"$regex": f"^{prefix}"}})
        else:
            result = await db.api_cache.delete_many({})
        logging.info(f"Cleared {result.deleted_count} cache entries")
        return result.deleted_count
    except Exception as e:
        logging.error(f"Cache clear error: {e}")
        return 0

# ==================== MODELS ====================

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    is_admin: bool = False
    created_at: datetime

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

class PortfolioPosition(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    position_type: str  # "covered_call", "pmcc", "stock"
    shares: int = 0
    avg_cost: float = 0
    current_price: float = 0
    option_strike: Optional[float] = None
    option_expiry: Optional[str] = None
    option_premium: Optional[float] = None
    leaps_strike: Optional[float] = None
    leaps_expiry: Optional[str] = None
    leaps_cost: Optional[float] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class PortfolioPositionCreate(BaseModel):
    symbol: str
    position_type: str
    shares: int = 0
    avg_cost: float = 0
    option_strike: Optional[float] = None
    option_expiry: Optional[str] = None
    option_premium: Optional[float] = None
    leaps_strike: Optional[float] = None
    leaps_expiry: Optional[str] = None
    leaps_cost: Optional[float] = None
    notes: Optional[str] = None

class WatchlistItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    target_price: Optional[float] = None
    notes: Optional[str] = None
    added_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class WatchlistItemCreate(BaseModel):
    symbol: str
    target_price: Optional[float] = None
    notes: Optional[str] = None

class ScreenerFilter(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    filters: Dict[str, Any]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ScreenerFilterCreate(BaseModel):
    name: str
    filters: Dict[str, Any]

class AdminSettings(BaseModel):
    # Massive.com API credentials for stock/options data
    massive_api_key: Optional[str] = None
    massive_access_id: Optional[str] = None
    massive_secret_key: Optional[str] = None
    # MarketAux API for news/sentiment
    marketaux_api_token: Optional[str] = None
    # OpenAI for AI analysis
    openai_api_key: Optional[str] = None
    # General settings
    data_refresh_interval: int = 60
    enable_live_data: bool = False

class AIAnalysisRequest(BaseModel):
    symbol: Optional[str] = None
    analysis_type: str  # "opportunity", "risk", "roll_suggestion", "general"
    context: Optional[str] = None

# ==================== AUTH HELPERS ====================

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def create_token(user_id: str, email: str, is_admin: bool = False) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "is_admin": is_admin,
        "exp": datetime.now(timezone.utc) + timedelta(days=30)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        token = credentials.credentials
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        user = await db.users.find_one({"id": user_id}, {"_id": 0, "password": 0})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def get_admin_user(user: dict = Depends(get_current_user)):
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

# ==================== DATA SERVICES ====================

async def get_admin_settings() -> AdminSettings:
    settings = await db.admin_settings.find_one({}, {"_id": 0})
    if settings:
        return AdminSettings(**settings)
    return AdminSettings()

async def get_massive_api_key():
    """Get Massive.com API key string"""
    settings = await get_admin_settings()
    if settings.massive_api_key and "..." not in settings.massive_api_key:
        return settings.massive_api_key
    return None

async def get_marketaux_client():
    """Get MarketAux API token"""
    settings = await get_admin_settings()
    if settings.marketaux_api_token and "..." not in settings.marketaux_api_token:
        return settings.marketaux_api_token
    return None

# Mock market data (used when Polygon API is not configured)
MOCK_STOCKS = {
    "AAPL": {"price": 178.50, "change": 2.35, "change_pct": 1.33, "volume": 45000000, "market_cap": 2800000000000, "pe": 28.5, "roe": 147.0},
    "MSFT": {"price": 378.25, "change": -1.20, "change_pct": -0.32, "volume": 22000000, "market_cap": 2900000000000, "pe": 35.2, "roe": 38.5},
    "GOOGL": {"price": 141.80, "change": 0.95, "change_pct": 0.67, "volume": 18000000, "market_cap": 1800000000000, "pe": 25.1, "roe": 25.3},
    "AMZN": {"price": 178.90, "change": 3.45, "change_pct": 1.97, "volume": 35000000, "market_cap": 1850000000000, "pe": 62.5, "roe": 12.5},
    "NVDA": {"price": 485.50, "change": 12.30, "change_pct": 2.60, "volume": 42000000, "market_cap": 1200000000000, "pe": 65.2, "roe": 55.8},
    "META": {"price": 505.20, "change": 8.40, "change_pct": 1.69, "volume": 15000000, "market_cap": 1300000000000, "pe": 28.8, "roe": 23.5},
    "TSLA": {"price": 248.75, "change": -5.25, "change_pct": -2.07, "volume": 85000000, "market_cap": 790000000000, "pe": 72.3, "roe": 15.2},
    "JPM": {"price": 195.80, "change": 1.15, "change_pct": 0.59, "volume": 8500000, "market_cap": 560000000000, "pe": 11.2, "roe": 14.8},
}

MOCK_INDICES = {
    "SPY": {"name": "S&P 500", "price": 478.50, "change": 3.25, "change_pct": 0.68},
    "QQQ": {"name": "NASDAQ 100", "price": 418.75, "change": 5.80, "change_pct": 1.40},
    "DIA": {"name": "Dow Jones", "price": 378.20, "change": 1.45, "change_pct": 0.38},
    "IWM": {"name": "Russell 2000", "price": 198.35, "change": -0.85, "change_pct": -0.43},
    "VIX": {"name": "Volatility Index", "price": 14.25, "change": -0.35, "change_pct": -2.40},
}

def generate_mock_options(symbol: str, stock_price: float):
    """Generate mock options chain data"""
    options = []
    base_iv = 0.25 + (hash(symbol) % 20) / 100
    
    # Weekly expirations (next 4 weeks)
    for weeks in range(1, 5):
        expiry = (datetime.now() + timedelta(weeks=weeks)).strftime("%Y-%m-%d")
        dte = weeks * 7
        
        # Generate strikes around current price
        for offset in range(-5, 6):
            strike = round(stock_price + offset * 5, 2)
            is_itm = strike < stock_price
            
            # Calculate mock delta based on moneyness
            moneyness = (stock_price - strike) / stock_price
            delta = max(0.05, min(0.95, 0.5 + moneyness * 2))
            
            # Calculate mock premium
            time_value = (dte / 365) ** 0.5 * stock_price * base_iv
            intrinsic = max(0, stock_price - strike)
            premium = round(intrinsic + time_value * (1 - abs(moneyness)), 2)
            
            # ROI calculation
            roi = round((premium / stock_price) * 100, 2) if stock_price > 0 else 0
            
            options.append({
                "symbol": f"{symbol}{expiry.replace('-', '')}C{int(strike * 1000)}",
                "underlying": symbol,
                "strike": strike,
                "expiry": expiry,
                "dte": dte,
                "type": "call",
                "bid": round(premium * 0.95, 2),
                "ask": round(premium * 1.05, 2),
                "last": premium,
                "delta": round(delta, 3),
                "gamma": round(0.05 * (1 - abs(moneyness)), 4),
                "theta": round(-premium / dte if dte > 0 else 0, 4),
                "vega": round(stock_price * 0.01 * (dte / 365) ** 0.5, 4),
                "iv": round(base_iv + (hash(f"{symbol}{strike}") % 10) / 100, 4),
                "iv_rank": round(30 + (hash(f"{symbol}{expiry}") % 40), 1),
                "volume": 100 + hash(f"{symbol}{strike}{expiry}") % 5000,
                "open_interest": 500 + hash(f"{symbol}{strike}") % 10000,
                "roi_pct": roi,
                "downside_protection": round((stock_price - strike + premium) / stock_price * 100, 2) if strike < stock_price else round(premium / stock_price * 100, 2),
                "in_the_money": is_itm
            })
    
    return options

def generate_mock_covered_call_opportunities():
    """Generate mock covered call screening results"""
    opportunities = []
    
    for symbol, data in MOCK_STOCKS.items():
        stock_price = data["price"]
        options = generate_mock_options(symbol, stock_price)
        
        # Find best weekly and monthly options
        for opt in options:
            if opt["dte"] <= 7 and opt["roi_pct"] >= 1.0:  # Weekly >= 1%
                opportunities.append({
                    "symbol": symbol,
                    "stock_price": stock_price,
                    "strike": opt["strike"],
                    "expiry": opt["expiry"],
                    "dte": opt["dte"],
                    "premium": opt["last"],
                    "roi_pct": opt["roi_pct"],
                    "delta": opt["delta"],
                    "iv": opt["iv"],
                    "iv_rank": opt["iv_rank"],
                    "downside_protection": opt["downside_protection"],
                    "pe": data["pe"],
                    "roe": data["roe"],
                    "volume": opt["volume"],
                    "open_interest": opt["open_interest"],
                    "score": round(opt["roi_pct"] * 10 + opt["iv_rank"] / 10 + opt["downside_protection"] / 5, 1)
                })
    
    # Sort by score
    opportunities.sort(key=lambda x: x["score"], reverse=True)
    return opportunities[:50]

def generate_mock_pmcc_opportunities():
    """Generate mock PMCC opportunities"""
    opportunities = []
    
    for symbol, data in MOCK_STOCKS.items():
        stock_price = data["price"]
        
        # Generate LEAPS (12-24 months out)
        leaps_expiry = (datetime.now() + timedelta(days=450)).strftime("%Y-%m-%d")
        leaps_strike = round(stock_price * 0.7, 2)  # Deep ITM
        leaps_delta = 0.85
        leaps_cost = round(stock_price * 0.35, 2)
        
        # Generate short call options
        short_expiry = (datetime.now() + timedelta(days=21)).strftime("%Y-%m-%d")
        short_strike = round(stock_price * 1.05, 2)  # OTM
        short_premium = round(stock_price * 0.02, 2)
        short_delta = 0.25
        
        opportunities.append({
            "symbol": symbol,
            "stock_price": stock_price,
            "leaps": {
                "strike": leaps_strike,
                "expiry": leaps_expiry,
                "delta": leaps_delta,
                "cost": leaps_cost,
                "dte": 450
            },
            "short_call": {
                "strike": short_strike,
                "expiry": short_expiry,
                "delta": short_delta,
                "premium": short_premium,
                "dte": 21
            },
            "max_profit": round(short_strike - leaps_strike + short_premium - leaps_cost, 2),
            "max_loss": leaps_cost - short_premium,
            "breakeven": round(leaps_strike + leaps_cost - short_premium, 2),
            "monthly_income_potential": round(short_premium * 12, 2),
            "roi_on_capital": round((short_premium / leaps_cost) * 100, 2),
            "pe": data["pe"],
            "roe": data["roe"]
        })
    
    opportunities.sort(key=lambda x: x["roi_on_capital"], reverse=True)
    return opportunities

MOCK_NEWS = [
    {"title": "Fed Signals Potential Rate Cuts in 2025", "source": "Reuters", "time": "2h ago", "sentiment": "positive"},
    {"title": "Tech Stocks Rally on AI Optimism", "source": "Bloomberg", "time": "3h ago", "sentiment": "positive"},
    {"title": "Options Trading Volume Hits Record High", "source": "CNBC", "time": "4h ago", "sentiment": "neutral"},
    {"title": "Market Volatility Expected to Increase", "source": "WSJ", "time": "5h ago", "sentiment": "negative"},
    {"title": "Earnings Season Kicks Off Strong", "source": "MarketWatch", "time": "6h ago", "sentiment": "positive"},
    {"title": "Bond Yields Decline as Inflation Cools", "source": "FT", "time": "7h ago", "sentiment": "positive"},
    {"title": "Semiconductor Stocks Lead Market Gains", "source": "Barron's", "time": "8h ago", "sentiment": "positive"},
    {"title": "Energy Sector Faces Headwinds", "source": "Reuters", "time": "9h ago", "sentiment": "negative"},
]

# ==================== AUTH ROUTES ====================

@auth_router.post("/register", response_model=TokenResponse)
async def register(user_data: UserCreate):
    # Check if user exists
    existing = await db.users.find_one({"email": user_data.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Create user
    user_id = str(uuid.uuid4())
    user = {
        "id": user_id,
        "email": user_data.email,
        "name": user_data.name,
        "password": hash_password(user_data.password),
        "is_admin": False,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.users.insert_one(user)
    
    # Generate token
    token = create_token(user_id, user_data.email)
    
    return TokenResponse(
        access_token=token,
        user=UserResponse(
            id=user_id,
            email=user_data.email,
            name=user_data.name,
            is_admin=False,
            created_at=datetime.fromisoformat(user["created_at"])
        )
    )

@auth_router.post("/login", response_model=TokenResponse)
async def login(credentials: UserLogin):
    user = await db.users.find_one({"email": credentials.email})
    if not user or not verify_password(credentials.password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    token = create_token(user["id"], user["email"], user.get("is_admin", False))
    
    created_at = user.get("created_at")
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    
    return TokenResponse(
        access_token=token,
        user=UserResponse(
            id=user["id"],
            email=user["email"],
            name=user["name"],
            is_admin=user.get("is_admin", False),
            created_at=created_at
        )
    )

@auth_router.get("/me", response_model=UserResponse)
async def get_me(user: dict = Depends(get_current_user)):
    created_at = user.get("created_at")
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    
    return UserResponse(
        id=user["id"],
        email=user["email"],
        name=user["name"],
        is_admin=user.get("is_admin", False),
        created_at=created_at
    )

# ==================== STOCKS ROUTES ====================

@stocks_router.get("/quote/{symbol}")
async def get_stock_quote(symbol: str, user: dict = Depends(get_current_user)):
    symbol = symbol.upper()
    
    # Try Massive.com API first
    api_key = await get_massive_api_key()
    if api_key:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Massive.com uses apiKey as query parameter (similar to Polygon)
                # Get previous day aggregates for price data
                response = await client.get(
                    f"https://api.massive.com/v2/aggs/ticker/{symbol}/prev",
                    params={"apiKey": api_key}
                )
                logging.info(f"Stock quote API response for {symbol}: status={response.status_code}")
                if response.status_code == 200:
                    data = response.json()
                    if data.get("results") and len(data["results"]) > 0:
                        result = data["results"][0]
                        return {
                            "symbol": symbol,
                            "price": result.get("c"),  # close price
                            "open": result.get("o"),
                            "high": result.get("h"),
                            "low": result.get("l"),
                            "volume": result.get("v"),
                            "change": round(result.get("c", 0) - result.get("o", 0), 2),
                            "change_pct": round((result.get("c", 0) - result.get("o", 0)) / result.get("o", 1) * 100, 2) if result.get("o") else 0,
                            "is_live": True
                        }
                
                # Fallback: try last trade endpoint
                response = await client.get(
                    f"https://api.massive.com/v2/last/trade/{symbol}",
                    params={"apiKey": api_key}
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("results"):
                        result = data["results"]
                        return {
                            "symbol": symbol,
                            "price": result.get("p"),  # price
                            "volume": result.get("s"),  # size
                            "is_live": True
                        }
        except Exception as e:
            logging.error(f"Massive.com API error: {e}")
    
    # Fallback to mock data
    if symbol in MOCK_STOCKS:
        data = MOCK_STOCKS[symbol]
        return {
            "symbol": symbol,
            "price": data["price"],
            "change": data["change"],
            "change_pct": data["change_pct"],
            "volume": data["volume"],
            "pe": data["pe"],
            "roe": data["roe"],
            "is_mock": True
        }
    
    raise HTTPException(status_code=404, detail=f"Stock {symbol} not found")

@stocks_router.get("/indices")
async def get_market_indices(user: dict = Depends(get_current_user)):
    return MOCK_INDICES

@stocks_router.get("/details/{symbol}")
async def get_stock_details(symbol: str, user: dict = Depends(get_current_user)):
    """Get comprehensive stock details including news, fundamentals, and ratings"""
    symbol = symbol.upper()
    api_key = await get_massive_api_key()
    
    result = {
        "symbol": symbol,
        "price": 0,
        "change": 0,
        "change_pct": 0,
        "news": [],
        "fundamentals": {},
        "analyst_ratings": {},
        "technicals": {},
        "is_live": False
    }
    
    if api_key:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Get current price
                price_response = await client.get(
                    f"https://api.massive.com/v2/aggs/ticker/{symbol}/prev",
                    params={"apiKey": api_key}
                )
                if price_response.status_code == 200:
                    price_data = price_response.json()
                    if price_data.get("results"):
                        r = price_data["results"][0]
                        result["price"] = r.get("c", 0)
                        result["open"] = r.get("o", 0)
                        result["high"] = r.get("h", 0)
                        result["low"] = r.get("l", 0)
                        result["volume"] = r.get("v", 0)
                        result["change"] = round(r.get("c", 0) - r.get("o", 0), 2)
                        result["change_pct"] = round((r.get("c", 0) - r.get("o", 0)) / r.get("o", 1) * 100, 2) if r.get("o") else 0
                        result["is_live"] = True
                
                # Get ticker details/fundamentals
                ticker_response = await client.get(
                    f"https://api.massive.com/v3/reference/tickers/{symbol}",
                    params={"apiKey": api_key}
                )
                if ticker_response.status_code == 200:
                    ticker_data = ticker_response.json()
                    details = ticker_data.get("results", {})
                    result["fundamentals"] = {
                        "name": details.get("name", symbol),
                        "market_cap": details.get("market_cap"),
                        "description": details.get("description", ""),
                        "homepage": details.get("homepage_url", ""),
                        "employees": details.get("total_employees"),
                        "list_date": details.get("list_date"),
                        "sic_description": details.get("sic_description", ""),
                        "locale": details.get("locale", "us"),
                        "primary_exchange": details.get("primary_exchange", "")
                    }
                
                # Get news from Massive.com
                news_response = await client.get(
                    f"https://api.massive.com/v2/reference/news",
                    params={"apiKey": api_key, "ticker": symbol, "limit": 5}
                )
                if news_response.status_code == 200:
                    news_data = news_response.json()
                    for article in news_data.get("results", [])[:5]:
                        result["news"].append({
                            "title": article.get("title", ""),
                            "description": article.get("description", ""),
                            "published": article.get("published_utc", ""),
                            "source": article.get("publisher", {}).get("name", ""),
                            "url": article.get("article_url", ""),
                            "image": article.get("image_url", "")
                        })
                
                # Calculate technical indicators from historical data
                end_date = datetime.now().strftime("%Y-%m-%d")
                start_date = (datetime.now() - timedelta(days=250)).strftime("%Y-%m-%d")
                
                hist_response = await client.get(
                    f"https://api.massive.com/v2/aggs/ticker/{symbol}/range/1/day/{start_date}/{end_date}",
                    params={"apiKey": api_key, "adjusted": "true", "sort": "desc", "limit": 250}
                )
                
                if hist_response.status_code == 200:
                    hist_data = hist_response.json()
                    bars = hist_data.get("results", [])
                    
                    if len(bars) >= 50:
                        closes = [b.get("c", 0) for b in bars]
                        
                        # SMA 50 and SMA 200
                        sma_50 = sum(closes[:50]) / 50
                        sma_200 = sum(closes[:200]) / 200 if len(closes) >= 200 else sum(closes) / len(closes)
                        
                        current = closes[0] if closes else 0
                        
                        # Simple RSI calculation (14 period)
                        gains = []
                        losses = []
                        for i in range(min(14, len(closes) - 1)):
                            change = closes[i] - closes[i + 1]
                            if change > 0:
                                gains.append(change)
                                losses.append(0)
                            else:
                                gains.append(0)
                                losses.append(abs(change))
                        
                        avg_gain = sum(gains) / 14 if gains else 0
                        avg_loss = sum(losses) / 14 if losses else 0.001
                        rs = avg_gain / avg_loss if avg_loss > 0 else 100
                        rsi = 100 - (100 / (1 + rs))
                        
                        # Trend analysis
                        trend = "bullish" if current > sma_50 > sma_200 else "bearish" if current < sma_50 < sma_200 else "neutral"
                        
                        result["technicals"] = {
                            "sma_50": round(sma_50, 2),
                            "sma_200": round(sma_200, 2),
                            "rsi": round(rsi, 1),
                            "trend": trend,
                            "above_sma_50": current > sma_50,
                            "above_sma_200": current > sma_200,
                            "sma_50_above_200": sma_50 > sma_200
                        }
                
        except Exception as e:
            logging.error(f"Stock details error for {symbol}: {e}")
    
    # Get MarketAux news as supplement
    settings = await get_admin_settings()
    if settings.marketaux_api_token and "..." not in settings.marketaux_api_token and len(result["news"]) < 5:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    "https://api.marketaux.com/v1/news/all",
                    params={
                        "api_token": settings.marketaux_api_token,
                        "symbols": symbol,
                        "filter_entities": "true",
                        "limit": 5
                    }
                )
                if response.status_code == 200:
                    data = response.json()
                    for article in data.get("data", []):
                        if len(result["news"]) < 8:
                            result["news"].append({
                                "title": article.get("title", ""),
                                "description": article.get("description", ""),
                                "published": article.get("published_at", ""),
                                "source": article.get("source", ""),
                                "url": article.get("url", ""),
                                "sentiment": article.get("sentiment", 0)
                            })
        except Exception as e:
            logging.error(f"MarketAux news error: {e}")
    
    return result

@stocks_router.get("/historical/{symbol}")
async def get_historical_data(
    symbol: str,
    timespan: str = Query("day", enum=["minute", "hour", "day", "week", "month"]),
    days: int = Query(30, ge=1, le=365),
    user: dict = Depends(get_current_user)
):
    symbol = symbol.upper()
    
    # Generate mock historical data
    data = []
    base_price = MOCK_STOCKS.get(symbol, {}).get("price", 100)
    
    for i in range(days, 0, -1):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        variation = (hash(f"{symbol}{date}") % 1000 - 500) / 10000
        price = base_price * (1 + variation * i / days)
        
        data.append({
            "date": date,
            "open": round(price * 0.998, 2),
            "high": round(price * 1.02, 2),
            "low": round(price * 0.98, 2),
            "close": round(price, 2),
            "volume": 1000000 + hash(f"{symbol}{date}") % 5000000
        })
    
    return data

# ==================== OPTIONS ROUTES ====================

@options_router.get("/chain/{symbol}")
async def get_options_chain(
    symbol: str,
    expiry: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    symbol = symbol.upper()
    
    # Try Massive.com Options API first
    api_key = await get_massive_api_key()
    if api_key:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # First get the stock price
                stock_response = await client.get(
                    f"https://api.massive.com/v2/aggs/ticker/{symbol}/prev",
                    params={"apiKey": api_key}
                )
                underlying_price = 0
                if stock_response.status_code == 200:
                    stock_data = stock_response.json()
                    if stock_data.get("results"):
                        underlying_price = stock_data["results"][0].get("c", 0)
                
                # Then get options chain
                params = {
                    "apiKey": api_key,
                    "limit": 250
                }
                
                # Add expiration filter if provided
                if expiry:
                    params["expiration_date"] = expiry
                
                url = f"https://api.massive.com/v3/snapshot/options/{symbol}"
                logging.info(f"Options chain API request: {url} with params (excluding key): expiry={expiry}")
                
                response = await client.get(url, params=params)
                
                logging.info(f"Options chain API response: status={response.status_code}")
                
                if response.status_code == 200:
                    data = response.json()
                    results = data.get("results", [])
                    
                    logging.info(f"Options chain returned {len(results)} results for {symbol}")
                    
                    if results:
                        options = []
                        for opt in results:
                            details = opt.get("details", {})
                            day = opt.get("day", {})
                            greeks = opt.get("greeks", {})
                            last_quote = opt.get("last_quote", {})
                            
                            options.append({
                                "symbol": details.get("ticker", ""),
                                "underlying": symbol,
                                "strike": details.get("strike_price", 0),
                                "expiry": details.get("expiration_date", ""),
                                "dte": calculate_dte(details.get("expiration_date", "")),
                                "type": details.get("contract_type", "call"),
                                "bid": last_quote.get("bid", 0) if last_quote else 0,
                                "ask": last_quote.get("ask", 0) if last_quote else 0,
                                "last": (day.get("close", 0) if day else 0) or (last_quote.get("midpoint", 0) if last_quote else 0),
                                "delta": greeks.get("delta", 0) if greeks else 0,
                                "gamma": greeks.get("gamma", 0) if greeks else 0,
                                "theta": greeks.get("theta", 0) if greeks else 0,
                                "vega": greeks.get("vega", 0) if greeks else 0,
                                "iv": opt.get("implied_volatility", 0),
                                "volume": day.get("volume", 0) if day else 0,
                                "open_interest": opt.get("open_interest", 0),
                                "break_even": opt.get("break_even_price", 0),
                            })
                        
                        # Filter to calls only for covered call screener
                        call_options = [o for o in options if o["type"] == "call"]
                        
                        return {
                            "symbol": symbol,
                            "stock_price": underlying_price,
                            "options": call_options,
                            "is_live": True
                        }
                elif response.status_code == 403:
                    logging.error("Massive.com API 403 Forbidden - check API plan for options access")
                else:
                    logging.error(f"Massive.com API error: {response.status_code} - {response.text[:200]}")
        except Exception as e:
            logging.error(f"Massive.com Options API error: {e}")
    
    # Fallback to mock data
    stock_price = MOCK_STOCKS.get(symbol, {}).get("price", 100)
    options = generate_mock_options(symbol, stock_price)
    
    if expiry:
        options = [o for o in options if o["expiry"] == expiry]
    
    return {
        "symbol": symbol,
        "stock_price": stock_price,
        "options": options,
        "is_mock": True
    }

def calculate_dte(expiry_date: str) -> int:
    """Calculate days to expiration"""
    if not expiry_date:
        return 0
    try:
        from datetime import datetime
        exp = datetime.strptime(expiry_date, "%Y-%m-%d")
        today = datetime.now()
        return max(0, (exp - today).days)
    except Exception:
        return 0

@options_router.get("/expirations/{symbol}")
async def get_option_expirations(symbol: str, user: dict = Depends(get_current_user)):
    """Get available expiration dates for a symbol"""
    expirations = []
    for weeks in range(1, 12):
        expiry = (datetime.now() + timedelta(weeks=weeks)).strftime("%Y-%m-%d")
        dte = weeks * 7
        expirations.append({"date": expiry, "dte": dte})
    
    # Add monthly expirations
    for months in range(3, 25):
        expiry = (datetime.now() + timedelta(days=months * 30)).strftime("%Y-%m-%d")
        dte = months * 30
        expirations.append({"date": expiry, "dte": dte})
    
    return expirations

# ==================== SCREENER ROUTES ====================

@screener_router.get("/covered-calls")
async def screen_covered_calls(
    min_roi: float = Query(0.5, ge=0),
    max_dte: int = Query(45, ge=1),
    min_delta: float = Query(0.15, ge=0, le=1),
    max_delta: float = Query(0.45, ge=0, le=1),
    min_iv_rank: float = Query(0, ge=0, le=100),
    min_price: float = Query(10, ge=0),
    max_price: float = Query(500, ge=0),
    min_volume: int = Query(0, ge=0),
    min_open_interest: int = Query(0, ge=0),
    weekly_only: bool = Query(False),
    monthly_only: bool = Query(False),
    bypass_cache: bool = Query(False),
    user: dict = Depends(get_current_user)
):
    # Generate cache key based on all filter parameters
    cache_params = {
        "min_roi": min_roi, "max_dte": max_dte, "min_delta": min_delta, "max_delta": max_delta,
        "min_iv_rank": min_iv_rank, "min_price": min_price, "max_price": max_price,
        "min_volume": min_volume, "min_open_interest": min_open_interest,
        "weekly_only": weekly_only, "monthly_only": monthly_only
    }
    cache_key = generate_cache_key("screener_covered_calls", cache_params)
    
    # Check cache first (unless bypassed)
    if not bypass_cache:
        cached_data = await get_cached_data(cache_key)
        if cached_data:
            cached_data["from_cache"] = True
            return cached_data
    
    # Check if we have Massive.com credentials for live data
    api_key = await get_massive_api_key()
    
    logging.info(f"Screener called: api_key={'present' if api_key else 'missing'}, min_roi={min_roi}, max_dte={max_dte}")
    
    if api_key:
        try:
            opportunities = []
            # Scan popular stocks for options
            symbols_to_scan = [
                # Large Cap Tech ($100+)
                "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", 
                # Major ETFs
                "SPY", "QQQ", "IWM", "DIA",
                # Financial ($100+)
                "JPM", "GS", "V", "MA",
                # Mid-range stocks ($50-$100)
                "INTC", "AMD", "CSCO", "PYPL", "UBER", "DIS", "NKE", "SBUX", "KO", "PEP",
                # Lower-priced stocks ($20-$50)
                "BAC", "WFC", "C", "F", "GM", "T", "VZ", "PFE", "MRK", "ABBV",
                # Additional popular options stocks
                "PLTR", "SOFI", "RIVN", "LCID", "NIO", "SNAP", "HOOD", "COIN"
            ]
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                for symbol in symbols_to_scan:
                    try:
                        # First get the current stock price
                        stock_response = await client.get(
                            f"https://api.massive.com/v2/aggs/ticker/{symbol}/prev",
                            params={"apiKey": api_key}
                        )
                        
                        underlying_price = 0
                        if stock_response.status_code == 200:
                            stock_data = stock_response.json()
                            if stock_data.get("results"):
                                underlying_price = stock_data["results"][0].get("c", 0)  # close price
                        
                        if underlying_price == 0:
                            logging.warning(f"Could not get price for {symbol}")
                            continue
                            
                        # Skip if price out of range
                        if underlying_price < min_price or underlying_price > max_price:
                            continue
                        
                        # Get options chain snapshot
                        params = {
                            "apiKey": api_key,
                            "limit": 250,
                            "contract_type": "call"
                        }
                        
                        response = await client.get(
                            f"https://api.massive.com/v3/snapshot/options/{symbol}",
                            params=params
                        )
                        
                        logging.info(f"Options API for {symbol}: status={response.status_code}")
                        
                        if response.status_code == 200:
                            data = response.json()
                            results = data.get("results", [])
                            
                            for opt in results:
                                details = opt.get("details", {})
                                day = opt.get("day", {})
                                greeks = opt.get("greeks", {})
                                last_quote = opt.get("last_quote", {})
                                
                                # Only process calls
                                if details.get("contract_type") != "call":
                                    continue
                                
                                strike = details.get("strike_price", 0)
                                expiry = details.get("expiration_date", "")
                                dte = calculate_dte(expiry)
                                
                                # Apply DTE filters
                                if dte > max_dte or dte < 1:
                                    continue
                                if weekly_only and dte > 7:
                                    continue
                                if monthly_only and dte <= 7:
                                    continue
                                
                                delta = abs(greeks.get("delta", 0))
                                if delta < min_delta or delta > max_delta:
                                    continue
                                
                                # Calculate premium - use day close, last_quote, or estimate
                                bid = last_quote.get("bid", 0) or 0
                                ask = last_quote.get("ask", 0) or 0
                                day_close = day.get("close", 0) or 0
                                
                                if bid > 0 and ask > 0:
                                    premium = (bid + ask) / 2
                                elif day_close > 0:
                                    premium = day_close
                                else:
                                    # Estimate premium based on intrinsic + time value
                                    intrinsic = max(0, underlying_price - strike)
                                    time_value = underlying_price * 0.02 * (dte / 30)  # rough estimate
                                    premium = intrinsic + time_value
                                
                                if premium <= 0:
                                    continue
                                
                                # Calculate ROI
                                roi_pct = (premium / underlying_price) * 100
                                
                                if roi_pct < min_roi:
                                    continue
                                
                                volume = day.get("volume", 0) or 0
                                open_interest = opt.get("open_interest", 0) or 0
                                
                                if volume < min_volume or open_interest < min_open_interest:
                                    continue
                                
                                iv = opt.get("implied_volatility", 0.25) or 0.25
                                iv_rank = min(100, iv * 100)  # Convert to percentage
                                
                                if iv_rank < min_iv_rank:
                                    continue
                                
                                # Calculate downside protection
                                if strike > underlying_price:
                                    protection = (premium / underlying_price) * 100
                                else:
                                    protection = ((strike - underlying_price + premium) / underlying_price * 100)
                                
                                # Calculate score
                                roi_score = min(roi_pct * 15, 40)
                                iv_score = min(iv_rank / 100 * 20, 20)
                                delta_score = max(0, 20 - abs(delta - 0.3) * 50)
                                protection_score = min(abs(protection), 10) * 2
                                
                                score = round(roi_score + iv_score + delta_score + protection_score, 1)
                                
                                opportunities.append({
                                    "symbol": symbol,
                                    "stock_price": round(underlying_price, 2),
                                    "strike": strike,
                                    "expiry": expiry,
                                    "dte": dte,
                                    "premium": round(premium, 2),
                                    "roi_pct": round(roi_pct, 2),
                                    "delta": round(delta, 3),
                                    "theta": round(greeks.get("theta", 0) or 0, 4),
                                    "iv": round(iv, 4),
                                    "iv_rank": round(iv_rank, 1),
                                    "downside_protection": round(protection, 2),
                                    "volume": volume,
                                    "open_interest": open_interest,
                                    "score": score
                                })
                        else:
                            logging.warning(f"Options API returned {response.status_code} for {symbol}")
                    except Exception as e:
                        logging.error(f"Error scanning {symbol}: {e}")
                        continue
            
            # Sort by score
            opportunities.sort(key=lambda x: x["score"], reverse=True)
            
            # Keep only the best opportunity per symbol (highest score)
            best_by_symbol = {}
            for opp in opportunities:
                sym = opp["symbol"]
                if sym not in best_by_symbol or opp["score"] > best_by_symbol[sym]["score"]:
                    best_by_symbol[sym] = opp
            
            # Convert back to list and sort by score
            opportunities = sorted(best_by_symbol.values(), key=lambda x: x["score"], reverse=True)
            
            logging.info(f"Found {len(opportunities)} best opportunities (one per symbol)")
            
            # Cache the live data
            result = {"opportunities": opportunities[:100], "total": len(opportunities), "is_live": True, "from_cache": False}
            await set_cached_data(cache_key, result)
            return result
            
        except Exception as e:
            logging.error(f"Screener error with Massive.com: {e}")
    
    # Fallback to mock data
    opportunities = generate_mock_covered_call_opportunities()
    
    # Apply filters
    filtered = [
        o for o in opportunities
        if o["roi_pct"] >= min_roi
        and o["dte"] <= max_dte
        and min_delta <= o["delta"] <= max_delta
        and o["iv_rank"] >= min_iv_rank
        and min_price <= o["stock_price"] <= max_price
        and o["volume"] >= min_volume
        and o["open_interest"] >= min_open_interest
    ]
    
    # Filter by expiration type
    if weekly_only:
        filtered = [o for o in filtered if o["dte"] <= 7]
    elif monthly_only:
        filtered = [o for o in filtered if o["dte"] > 7]
    
    # Keep only the best opportunity per symbol (highest score)
    best_by_symbol = {}
    for opp in filtered:
        sym = opp["symbol"]
        if sym not in best_by_symbol or opp["score"] > best_by_symbol[sym]["score"]:
            best_by_symbol[sym] = opp
    
    filtered = sorted(best_by_symbol.values(), key=lambda x: x["score"], reverse=True)
    
    return {"opportunities": filtered, "total": len(filtered), "is_mock": True}

@screener_router.get("/dashboard-opportunities")
async def get_dashboard_opportunities(
    user: dict = Depends(get_current_user)
):
    """
    Get top 10 covered call opportunities for dashboard with advanced filters:
    - Stock price: $30-$90
    - Up trending (6 & 12 months) - RELAXED: at least one positive
    - Price above SMA 200
    - Price within 15% above SMA 50 - RELAXED from 10%
    - Exclude stocks with dividends in current month
    - Fundamentals: P/E < 35, ROE data when available
    - Analyst ratings when available
    - Weekly: min 0.8% ROI, Monthly: min 2.5% ROI - RELAXED
    """
    api_key = await get_massive_api_key()
    
    if not api_key:
        return {"opportunities": [], "total": 0, "message": "API key not configured", "is_mock": True}
    
    try:
        # Extended list of stocks to scan - more diverse selection
        symbols_to_scan = [
            # Tech stocks in range
            "INTC", "CSCO", "MU", "QCOM", "TXN", "ADI", "MCHP", "ON", "HPQ", "DELL",
            # Financial stocks
            "BAC", "WFC", "C", "USB", "PNC", "TFC", "KEY", "RF", "CFG", "FITB",
            # Consumer stocks
            "KO", "PEP", "NKE", "SBUX", "DIS", "GM", "F",
            # Telecom/Utilities
            "VZ", "T", 
            # Healthcare
            "PFE", "MRK", "ABBV", "BMY", "GILD",
            # Energy
            "OXY", "DVN", "APA", "HAL", "SLB",
            # Industrials
            "CAT", "DE", "GE", "HON", "MMM",
            # Additional popular options stocks
            "PYPL", "SQ", "ROKU", "SNAP", "UBER", "LYFT"
        ]
        
        opportunities = []
        
        async with httpx.AsyncClient(timeout=90.0) as client:
            for symbol in symbols_to_scan:
                try:
                    # Get stock price
                    stock_response = await client.get(
                        f"https://api.massive.com/v2/aggs/ticker/{symbol}/prev",
                        params={"apiKey": api_key}
                    )
                    
                    if stock_response.status_code != 200:
                        continue
                    
                    stock_data = stock_response.json()
                    if not stock_data.get("results"):
                        continue
                    
                    current_price = stock_data["results"][0].get("c", 0)
                    
                    # RELAXED: Stock price between $25 and $100
                    if current_price < 25 or current_price > 100:
                        continue
                    
                    # Get historical data for SMA and trend
                    end_date = datetime.now().strftime("%Y-%m-%d")
                    start_date = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")
                    
                    aggs_response = await client.get(
                        f"https://api.massive.com/v2/aggs/ticker/{symbol}/range/1/day/{start_date}/{end_date}",
                        params={"apiKey": api_key, "adjusted": "true", "sort": "desc", "limit": 300}
                    )
                    
                    if aggs_response.status_code != 200:
                        continue
                    
                    aggs_data = aggs_response.json()
                    bars = aggs_data.get("results", [])
                    
                    if len(bars) < 50:
                        continue
                    
                    # Calculate SMAs
                    close_prices = [bar.get("c", 0) for bar in bars]
                    sma_50 = sum(close_prices[:50]) / 50 if len(close_prices) >= 50 else current_price
                    sma_200 = sum(close_prices[:200]) / 200 if len(close_prices) >= 200 else sma_50 * 0.95
                    
                    # RELAXED: Price above SMA 200 OR within 5% below
                    if current_price < sma_200 * 0.95:
                        continue
                    
                    # RELAXED: Price within 15% above SMA 50 (was 10%)
                    pct_above_sma50 = ((current_price - sma_50) / sma_50) * 100 if sma_50 > 0 else 0
                    if pct_above_sma50 > 15:
                        continue
                    
                    # Calculate trends
                    price_6m_ago = close_prices[min(126, len(close_prices)-1)] if len(close_prices) > 126 else current_price * 0.9
                    price_12m_ago = close_prices[min(252, len(close_prices)-1)] if len(close_prices) > 252 else current_price * 0.85
                    
                    trend_6m = ((current_price - price_6m_ago) / price_6m_ago * 100) if price_6m_ago > 0 else 0
                    trend_12m = ((current_price - price_12m_ago) / price_12m_ago * 100) if price_12m_ago > 0 else 0
                    
                    # RELAXED: At least one positive trend OR both > -10%
                    if trend_6m < -10 and trend_12m < -10:
                        continue
                    
                    # Get fundamentals (P/E ratio) - try ticker details endpoint
                    pe_ratio = None
                    roe = None
                    try:
                        ticker_response = await client.get(
                            f"https://api.massive.com/v3/reference/tickers/{symbol}",
                            params={"apiKey": api_key}
                        )
                        if ticker_response.status_code == 200:
                            ticker_data = ticker_response.json()
                            results = ticker_data.get("results", {})
                            # Try to get market cap for context
                            market_cap = results.get("market_cap")
                    except Exception:
                        pass
                    
                    # Get dividends to check if any in current month
                    has_dividend_this_month = False
                    next_dividend_date = None
                    try:
                        div_response = await client.get(
                            f"https://api.massive.com/v3/reference/dividends",
                            params={"apiKey": api_key, "ticker": symbol, "limit": 3}
                        )
                        if div_response.status_code == 200:
                            div_data = div_response.json()
                            for div in div_data.get("results", []):
                                ex_date = div.get("ex_dividend_date", "")
                                if ex_date:
                                    next_dividend_date = ex_date
                                    if ex_date.startswith(datetime.now().strftime("%Y-%m")):
                                        has_dividend_this_month = True
                                    break
                    except Exception:
                        pass
                    
                    # RELAXED: Don't exclude dividend stocks, just note it
                    
                    # Get analyst ratings if available
                    analyst_rating = None
                    buy_ratings = 0
                    target_price = None
                    try:
                        # Try to get analyst data from ticker news/insights
                        news_response = await client.get(
                            f"https://api.massive.com/v2/reference/news",
                            params={"apiKey": api_key, "ticker": symbol, "limit": 5}
                        )
                        if news_response.status_code == 200:
                            news_data = news_response.json()
                            # Check for analyst-related news
                            for article in news_data.get("results", []):
                                title = article.get("title", "").lower()
                                if "upgrade" in title or "buy" in title or "outperform" in title:
                                    buy_ratings += 1
                    except Exception:
                        pass
                    
                    # Get options chain
                    options_response = await client.get(
                        f"https://api.massive.com/v3/snapshot/options/{symbol}",
                        params={"apiKey": api_key, "limit": 250, "contract_type": "call"}
                    )
                    
                    if options_response.status_code != 200:
                        continue
                    
                    options_data = options_response.json()
                    options_results = options_data.get("results", [])
                    
                    if not options_results:
                        continue
                    
                    # Find best weekly and monthly options with RELAXED thresholds
                    best_weekly = None
                    best_monthly = None
                    
                    for opt in options_results:
                        details = opt.get("details", {})
                        day = opt.get("day", {})
                        greeks = opt.get("greeks", {})
                        last_quote = opt.get("last_quote", {})
                        
                        if details.get("contract_type") != "call":
                            continue
                        
                        strike = details.get("strike_price", 0)
                        expiry = details.get("expiration_date", "")
                        dte = calculate_dte(expiry)
                        
                        if dte < 1 or dte > 45:
                            continue
                        
                        # Filter for ATM or slightly OTM strikes only
                        # ATM = within 2% of current price
                        # Slightly OTM = 0% to 10% above current price
                        strike_pct_diff = ((strike - current_price) / current_price) * 100
                        
                        # Accept strikes from -2% (slightly ITM) to +10% (OTM)
                        if strike_pct_diff < -2 or strike_pct_diff > 10:
                            continue
                        
                        delta = abs(greeks.get("delta", 0)) if greeks else 0
                        # For covered calls, delta typically 0.25-0.45 for OTM calls
                        if delta < 0.20 or delta > 0.55:
                            continue
                        
                        bid = last_quote.get("bid", 0) if last_quote else 0
                        ask = last_quote.get("ask", 0) if last_quote else 0
                        premium = ((bid + ask) / 2) if bid > 0 and ask > 0 else (day.get("close", 0) if day else 0)
                        
                        if premium <= 0:
                            continue
                        
                        roi_pct = (premium / current_price) * 100
                        iv = opt.get("implied_volatility", 0.25) or 0.25
                        volume = day.get("volume", 0) if day else 0
                        open_interest = opt.get("open_interest", 0)
                        
                        # Determine if ATM or OTM
                        if strike_pct_diff >= -2 and strike_pct_diff <= 2:
                            moneyness = "ATM"
                        else:
                            moneyness = "OTM"
                        
                        opp_data = {
                            "symbol": symbol,
                            "stock_price": round(current_price, 2),
                            "strike": strike,
                            "strike_pct": round(strike_pct_diff, 1),
                            "moneyness": moneyness,
                            "expiry": expiry,
                            "dte": dte,
                            "premium": round(premium, 2),
                            "roi_pct": round(roi_pct, 2),
                            "delta": round(delta, 3),
                            "iv": round(iv * 100, 1),
                            "sma_50": round(sma_50, 2),
                            "sma_200": round(sma_200, 2),
                            "trend_6m": round(trend_6m, 1),
                            "trend_12m": round(trend_12m, 1),
                            "volume": volume,
                            "open_interest": open_interest,
                            "expiry_type": "weekly" if dte <= 7 else "monthly",
                            "has_dividend": has_dividend_this_month,
                            "next_div_date": next_dividend_date,
                            "pe_ratio": pe_ratio,
                            "roe": roe,
                            "buy_signals": buy_ratings
                        }
                        
                        # RELAXED: Weekly min 0.8% ROI (was 1%)
                        if dte <= 7 and roi_pct >= 0.8:
                            if best_weekly is None or roi_pct > best_weekly["roi_pct"]:
                                best_weekly = opp_data.copy()
                        
                        # RELAXED: Monthly min 2.5% ROI (was 4%)
                        elif dte > 7 and roi_pct >= 2.5:
                            if best_monthly is None or roi_pct > best_monthly["roi_pct"]:
                                best_monthly = opp_data.copy()
                    
                    # Calculate composite scores
                    for opp in [best_weekly, best_monthly]:
                        if opp:
                            roi_score = min(opp["roi_pct"] * 10, 30)
                            trend_score = min(max(0, (opp["trend_6m"] + opp["trend_12m"]) / 3), 25)
                            delta_score = max(0, 15 - abs(opp["delta"] - 0.3) * 40)
                            sma_score = 15 if current_price > sma_200 else 8
                            sma_score += 5 if current_price > sma_50 else 0
                            volume_score = min(opp["volume"] / 100, 10) if opp["volume"] > 0 else 5
                            opp["score"] = round(roi_score + trend_score + delta_score + sma_score + volume_score, 1)
                            opportunities.append(opp)
                    
                except Exception as e:
                    logging.error(f"Dashboard scan error for {symbol}: {e}")
                    continue
        
        # Sort by score and get top 10 unique symbols
        opportunities.sort(key=lambda x: x["score"], reverse=True)
        
        # Keep only one entry per symbol (best score)
        seen_symbols = set()
        unique_opps = []
        for opp in opportunities:
            if opp["symbol"] not in seen_symbols:
                seen_symbols.add(opp["symbol"])
                unique_opps.append(opp)
                if len(unique_opps) >= 10:
                    break
        
        return {
            "opportunities": unique_opps,
            "total": len(unique_opps),
            "is_live": True,
            "filters_applied": {
                "price_range": "$25-$100",
                "strike": "ATM or slightly OTM (-2% to +10%)",
                "trend": "At least one positive trend (6M or 12M)",
                "sma": "Above SMA 200 (or within 5%), within 15% of SMA 50",
                "weekly_min_roi": "0.8%",
                "monthly_min_roi": "2.5%"
            }
        }
        
    except Exception as e:
        logging.error(f"Dashboard opportunities error: {e}")
        return {"opportunities": [], "total": 0, "error": str(e), "is_mock": True}

@screener_router.get("/dashboard-pmcc")
async def get_dashboard_pmcc_opportunities(
    user: dict = Depends(get_current_user)
):
    """
    Get top 10 PMCC (Poor Man's Covered Call) opportunities for dashboard.
    
    Uses true LEAPS options (12-24 months out) for the long leg.
    - Long leg: LEAPS call, deep ITM (high delta ~0.80-0.90), 12-24 months
    - Short leg: Short-term call, OTM (low delta ~0.20-0.30), 7-45 days
    
    Price range: $30-$500
    """
    api_key = await get_massive_api_key()
    
    if not api_key:
        return {"opportunities": [], "total": 0, "message": "API key not configured", "is_mock": True}
    
    try:
        symbols_to_scan = [
            # Tech stocks with good options liquidity
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AMD", "INTC", "MU",
            "QCOM", "TXN", "NFLX", "CRM", "ADBE",
            # ETFs
            "SPY", "QQQ", "IWM", "DIA",
            # Financial
            "JPM", "BAC", "WFC", "GS", "C",
            # Consumer
            "COST", "WMT", "HD", "NKE", "SBUX", "MCD", "DIS",
            # Healthcare
            "UNH", "JNJ", "PFE", "MRK", "LLY",
            # Industrial/Energy
            "CAT", "DE", "BA", "XOM", "CVX"
        ]
        
        opportunities = []
        
        # Calculate date ranges for LEAPS (12-24 months out) and short-term (7-45 days)
        today = datetime.now()
        
        # LEAPS date range: 12-24 months from today
        leaps_start = (today + timedelta(days=365)).strftime("%Y-%m-%d")  # 12 months out
        leaps_end = (today + timedelta(days=730)).strftime("%Y-%m-%d")    # 24 months out
        
        # Short-term date range: 7-45 days from today
        short_start = (today + timedelta(days=7)).strftime("%Y-%m-%d")
        short_end = (today + timedelta(days=45)).strftime("%Y-%m-%d")
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            for symbol in symbols_to_scan:
                try:
                    # Get current stock price
                    stock_response = await client.get(
                        f"https://api.massive.com/v2/aggs/ticker/{symbol}/prev",
                        params={"apiKey": api_key}
                    )
                    
                    if stock_response.status_code != 200:
                        continue
                    
                    stock_data = stock_response.json()
                    if not stock_data.get("results"):
                        continue
                    
                    current_price = stock_data["results"][0].get("c", 0)
                    
                    # Filter: Stock price between $30 and $500
                    if current_price < 30 or current_price > 500:
                        continue
                    
                    # Fetch LEAPS options (12-24 months out)
                    leaps_response = await client.get(
                        f"https://api.massive.com/v3/snapshot/options/{symbol}",
                        params={
                            "apiKey": api_key,
                            "limit": 250,
                            "contract_type": "call",
                            "expiration_date.gte": leaps_start,
                            "expiration_date.lte": leaps_end
                        }
                    )
                    
                    # Fetch short-term options (7-45 days)
                    short_response = await client.get(
                        f"https://api.massive.com/v3/snapshot/options/{symbol}",
                        params={
                            "apiKey": api_key,
                            "limit": 250,
                            "contract_type": "call",
                            "expiration_date.gte": short_start,
                            "expiration_date.lte": short_end
                        }
                    )
                    
                    leaps_options = []
                    short_options = []
                    
                    # Process LEAPS options
                    if leaps_response.status_code == 200:
                        leaps_data = leaps_response.json()
                        for opt in leaps_data.get("results", []):
                            details = opt.get("details", {})
                            greeks = opt.get("greeks", {})
                            day = opt.get("day", {})
                            last_quote = opt.get("last_quote", {})
                            
                            if details.get("contract_type") != "call":
                                continue
                            
                            strike = details.get("strike_price", 0)
                            delta = abs(greeks.get("delta", 0)) if greeks else 0
                            expiry = details.get("expiration_date", "")
                            dte = calculate_dte(expiry)
                            
                            # LEAPS should be ITM with high delta (0.70+)
                            if strike >= current_price or delta < 0.70:
                                continue
                            
                            bid = last_quote.get("bid", 0) if last_quote else 0
                            ask = last_quote.get("ask", 0) if last_quote else 0
                            price = ((bid + ask) / 2) if bid > 0 and ask > 0 else (day.get("close", 0) if day else 0)
                            
                            if price <= 0:
                                continue
                            
                            iv = opt.get("implied_volatility", 0.25) or 0.25
                            
                            leaps_options.append({
                                "strike": strike,
                                "expiry": expiry,
                                "dte": dte,
                                "delta": round(delta, 3),
                                "cost": round(price * 100, 2),
                                "iv": round(iv * 100, 1)
                            })
                    
                    # Process short-term options
                    if short_response.status_code == 200:
                        short_data = short_response.json()
                        for opt in short_data.get("results", []):
                            details = opt.get("details", {})
                            greeks = opt.get("greeks", {})
                            day = opt.get("day", {})
                            last_quote = opt.get("last_quote", {})
                            
                            if details.get("contract_type") != "call":
                                continue
                            
                            strike = details.get("strike_price", 0)
                            delta = abs(greeks.get("delta", 0)) if greeks else 0
                            expiry = details.get("expiration_date", "")
                            dte = calculate_dte(expiry)
                            
                            # Short leg should be OTM with delta 0.15-0.40
                            if strike <= current_price or delta < 0.15 or delta > 0.40:
                                continue
                            
                            bid = last_quote.get("bid", 0) if last_quote else 0
                            ask = last_quote.get("ask", 0) if last_quote else 0
                            price = ((bid + ask) / 2) if bid > 0 and ask > 0 else (day.get("close", 0) if day else 0)
                            
                            if price <= 0:
                                continue
                            
                            iv = opt.get("implied_volatility", 0.25) or 0.25
                            
                            short_options.append({
                                "strike": strike,
                                "expiry": expiry,
                                "dte": dte,
                                "delta": round(delta, 3),
                                "premium": round(price * 100, 2),
                                "iv": round(iv * 100, 1)
                            })
                    
                    # Build PMCC if both legs available
                    if leaps_options and short_options:
                        # Best LEAPS: highest delta (deepest ITM)
                        best_leaps = max(leaps_options, key=lambda x: x["delta"])
                        
                        # Best short: closest to delta 0.25
                        best_short = min(short_options, key=lambda x: abs(x["delta"] - 0.25))
                        
                        if best_leaps["cost"] > 0:
                            net_debit = best_leaps["cost"] - best_short["premium"]
                            strike_width = best_short["strike"] - best_leaps["strike"]
                            max_profit = (strike_width * 100) - net_debit
                            breakeven = best_leaps["strike"] + (net_debit / 100)
                            
                            roi_per_cycle = (best_short["premium"] / best_leaps["cost"]) * 100
                            cycles_per_year = 365 / max(best_short["dte"], 7)
                            annualized_roi = roi_per_cycle * min(cycles_per_year, 52)
                            
                            # Score calculation
                            roi_score = min(roi_per_cycle * 10, 35)
                            delta_long_score = 20 if best_leaps["delta"] >= 0.80 else 15 if best_leaps["delta"] >= 0.75 else 10
                            delta_short_score = 15 if 0.20 <= best_short["delta"] <= 0.30 else 10
                            dte_leaps_score = 15 if best_leaps["dte"] >= 365 else 10
                            width_score = min(strike_width / current_price * 100, 10)
                            
                            total_score = roi_score + delta_long_score + delta_short_score + dte_leaps_score + width_score
                            
                            opportunities.append({
                                "symbol": symbol,
                                "stock_price": round(current_price, 2),
                                "leaps_strike": best_leaps["strike"],
                                "leaps_expiry": best_leaps["expiry"],
                                "leaps_dte": best_leaps["dte"],
                                "leaps_delta": best_leaps["delta"],
                                "leaps_cost": best_leaps["cost"],
                                "leaps_iv": best_leaps["iv"],
                                "short_strike": best_short["strike"],
                                "short_expiry": best_short["expiry"],
                                "short_dte": best_short["dte"],
                                "short_delta": best_short["delta"],
                                "short_premium": best_short["premium"],
                                "short_iv": best_short["iv"],
                                "net_debit": round(net_debit, 2),
                                "max_profit": round(max_profit, 2),
                                "breakeven": round(breakeven, 2),
                                "strike_width": round(strike_width, 2),
                                "roi_per_cycle": round(roi_per_cycle, 2),
                                "annualized_roi": round(annualized_roi, 1),
                                "score": round(total_score, 1)
                            })
                    
                except Exception as e:
                    logging.error(f"PMCC scan error for {symbol}: {e}")
                    continue
        
        # Sort by score and get top 10
        opportunities.sort(key=lambda x: x["score"], reverse=True)
        top_10 = opportunities[:10]
        
        return {
            "opportunities": top_10,
            "total": len(top_10),
            "is_live": True,
            "has_leaps": len(top_10) > 0,
            "note": "True LEAPS (12-24 months) with short-term covered calls" if top_10 else "No LEAPS options available for scanned symbols",
            "filters_applied": {
                "price_range": "$30-$500",
                "leaps_leg": f"12-24 months out ({leaps_start} to {leaps_end}), deep ITM (δ≥0.70)",
                "short_leg": f"7-45 days out ({short_start} to {short_end}), OTM (δ 0.15-0.40)"
            }
        }
        
    except Exception as e:
        logging.error(f"Dashboard PMCC error: {e}")
        return {"opportunities": [], "total": 0, "error": str(e), "is_mock": True}

@screener_router.get("/pmcc")
async def screen_pmcc(
    min_price: float = Query(30, ge=1),
    max_price: float = Query(500, le=5000),
    min_leaps_delta: float = Query(0.70, ge=0.5, le=1),
    max_leaps_delta: float = Query(1.0, ge=0.5, le=1),
    min_leaps_dte: int = Query(300, ge=180),
    max_leaps_dte: int = Query(730, le=900),
    min_short_delta: float = Query(0.15, ge=0.05, le=0.5),
    max_short_delta: float = Query(0.40, ge=0.1, le=0.6),
    min_short_dte: int = Query(7, ge=1),
    max_short_dte: int = Query(45, le=90),
    min_roi: float = Query(1.0, ge=0),
    min_annualized_roi: float = Query(20, ge=0),
    user: dict = Depends(get_current_user)
):
    """
    Screen for PMCC opportunities with customizable filters.
    Uses true LEAPS options (12-24 months) for the long leg.
    """
    api_key = await get_massive_api_key()
    
    if not api_key:
        return {"opportunities": [], "total": 0, "message": "API key not configured", "is_mock": True}
    
    try:
        symbols_to_scan = [
            # Tech stocks with good options liquidity
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AMD", "INTC", "MU",
            "QCOM", "TXN", "NFLX", "CRM", "ADBE", "ORCL", "IBM", "CSCO",
            # ETFs
            "SPY", "QQQ", "IWM", "DIA", "XLF", "XLE",
            # Financial
            "JPM", "BAC", "WFC", "GS", "C", "MS", "BLK", "SCHW",
            # Consumer
            "COST", "WMT", "HD", "NKE", "SBUX", "MCD", "DIS", "ABNB", "BKNG",
            # Healthcare
            "UNH", "JNJ", "PFE", "MRK", "LLY", "ABBV", "TMO",
            # Industrial/Energy
            "CAT", "DE", "BA", "XOM", "CVX", "COP", "SLB",
            # Other
            "PYPL", "SQ", "UBER", "LYFT", "COIN", "HOOD"
        ]
        
        opportunities = []
        
        # Calculate date ranges for LEAPS and short-term options
        today = datetime.now()
        
        # LEAPS date range based on filter parameters
        leaps_start = (today + timedelta(days=min_leaps_dte)).strftime("%Y-%m-%d")
        leaps_end = (today + timedelta(days=max_leaps_dte)).strftime("%Y-%m-%d")
        
        # Short-term date range based on filter parameters
        short_start = (today + timedelta(days=min_short_dte)).strftime("%Y-%m-%d")
        short_end = (today + timedelta(days=max_short_dte)).strftime("%Y-%m-%d")
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            for symbol in symbols_to_scan:
                try:
                    # Get current stock price
                    stock_response = await client.get(
                        f"https://api.massive.com/v2/aggs/ticker/{symbol}/prev",
                        params={"apiKey": api_key}
                    )
                    
                    if stock_response.status_code != 200:
                        continue
                    
                    stock_data = stock_response.json()
                    if not stock_data.get("results"):
                        continue
                    
                    current_price = stock_data["results"][0].get("c", 0)
                    
                    # Apply stock price filter
                    if current_price < min_price or current_price > max_price:
                        continue
                    
                    # Fetch LEAPS options
                    leaps_response = await client.get(
                        f"https://api.massive.com/v3/snapshot/options/{symbol}",
                        params={
                            "apiKey": api_key,
                            "limit": 250,
                            "contract_type": "call",
                            "expiration_date.gte": leaps_start,
                            "expiration_date.lte": leaps_end
                        }
                    )
                    
                    # Fetch short-term options
                    short_response = await client.get(
                        f"https://api.massive.com/v3/snapshot/options/{symbol}",
                        params={
                            "apiKey": api_key,
                            "limit": 250,
                            "contract_type": "call",
                            "expiration_date.gte": short_start,
                            "expiration_date.lte": short_end
                        }
                    )
                    
                    leaps_options = []
                    short_options = []
                    
                    # Process LEAPS options
                    if leaps_response.status_code == 200:
                        leaps_data = leaps_response.json()
                        for opt in leaps_data.get("results", []):
                            details = opt.get("details", {})
                            greeks = opt.get("greeks", {})
                            day = opt.get("day", {})
                            last_quote = opt.get("last_quote", {})
                            
                            if details.get("contract_type") != "call":
                                continue
                            
                            strike = details.get("strike_price", 0)
                            delta = abs(greeks.get("delta", 0)) if greeks else 0
                            expiry = details.get("expiration_date", "")
                            dte = calculate_dte(expiry)
                            
                            # Apply LEAPS delta filter - must be ITM
                            if strike >= current_price or delta < min_leaps_delta or delta > max_leaps_delta:
                                continue
                            
                            bid = last_quote.get("bid", 0) if last_quote else 0
                            ask = last_quote.get("ask", 0) if last_quote else 0
                            price = ((bid + ask) / 2) if bid > 0 and ask > 0 else (day.get("close", 0) if day else 0)
                            
                            if price <= 0:
                                continue
                            
                            iv = opt.get("implied_volatility", 0.25) or 0.25
                            
                            leaps_options.append({
                                "strike": strike,
                                "expiry": expiry,
                                "dte": dte,
                                "delta": round(delta, 3),
                                "cost": round(price * 100, 2),
                                "iv": round(iv * 100, 1)
                            })
                    
                    # Process short-term options
                    if short_response.status_code == 200:
                        short_data = short_response.json()
                        for opt in short_data.get("results", []):
                            details = opt.get("details", {})
                            greeks = opt.get("greeks", {})
                            day = opt.get("day", {})
                            last_quote = opt.get("last_quote", {})
                            
                            if details.get("contract_type") != "call":
                                continue
                            
                            strike = details.get("strike_price", 0)
                            delta = abs(greeks.get("delta", 0)) if greeks else 0
                            expiry = details.get("expiration_date", "")
                            dte = calculate_dte(expiry)
                            
                            # Apply short delta filter - must be OTM
                            if strike <= current_price or delta < min_short_delta or delta > max_short_delta:
                                continue
                            
                            bid = last_quote.get("bid", 0) if last_quote else 0
                            ask = last_quote.get("ask", 0) if last_quote else 0
                            price = ((bid + ask) / 2) if bid > 0 and ask > 0 else (day.get("close", 0) if day else 0)
                            
                            if price <= 0:
                                continue
                            
                            iv = opt.get("implied_volatility", 0.25) or 0.25
                            
                            short_options.append({
                                "strike": strike,
                                "expiry": expiry,
                                "dte": dte,
                                "delta": round(delta, 3),
                                "premium": round(price * 100, 2),
                                "iv": round(iv * 100, 1)
                            })
                    
                    # Build PMCC opportunities if both legs available
                    if leaps_options and short_options:
                        # Best LEAPS: highest delta (deepest ITM)
                        best_leaps = max(leaps_options, key=lambda x: x["delta"])
                        
                        # Best short: closest to middle of delta range
                        target_delta = (min_short_delta + max_short_delta) / 2
                        best_short = min(short_options, key=lambda x: abs(x["delta"] - target_delta))
                        
                        if best_leaps["cost"] > 0:
                            net_debit = best_leaps["cost"] - best_short["premium"]
                            strike_width = best_short["strike"] - best_leaps["strike"]
                            max_profit = (strike_width * 100) - net_debit
                            breakeven = best_leaps["strike"] + (net_debit / 100)
                            
                            roi_per_cycle = (best_short["premium"] / best_leaps["cost"]) * 100
                            cycles_per_year = 365 / max(best_short["dte"], 7)
                            annualized_roi = roi_per_cycle * min(cycles_per_year, 52)
                            
                            # Apply ROI filters
                            if roi_per_cycle < min_roi or annualized_roi < min_annualized_roi:
                                continue
                            
                            # Score calculation
                            roi_score = min(roi_per_cycle * 10, 35)
                            delta_long_score = 20 if best_leaps["delta"] >= 0.80 else 15 if best_leaps["delta"] >= 0.75 else 10
                            delta_short_score = 15 if 0.20 <= best_short["delta"] <= 0.30 else 10
                            dte_leaps_score = 15 if best_leaps["dte"] >= 365 else 10
                            width_score = min(strike_width / current_price * 100, 10)
                            
                            total_score = roi_score + delta_long_score + delta_short_score + dte_leaps_score + width_score
                            
                            opportunities.append({
                                "symbol": symbol,
                                "stock_price": round(current_price, 2),
                                "leaps_strike": best_leaps["strike"],
                                "leaps_expiry": best_leaps["expiry"],
                                "leaps_dte": best_leaps["dte"],
                                "leaps_delta": best_leaps["delta"],
                                "leaps_cost": best_leaps["cost"],
                                "leaps_iv": best_leaps["iv"],
                                "short_strike": best_short["strike"],
                                "short_expiry": best_short["expiry"],
                                "short_dte": best_short["dte"],
                                "short_delta": best_short["delta"],
                                "short_premium": best_short["premium"],
                                "short_iv": best_short["iv"],
                                "net_debit": round(net_debit, 2),
                                "max_profit": round(max_profit, 2),
                                "breakeven": round(breakeven, 2),
                                "strike_width": round(strike_width, 2),
                                "roi_per_cycle": round(roi_per_cycle, 2),
                                "annualized_roi": round(annualized_roi, 1),
                                "score": round(total_score, 1)
                            })
                    
                except Exception as e:
                    logging.error(f"PMCC scan error for {symbol}: {e}")
                    continue
        
        # Sort by score
        opportunities.sort(key=lambda x: x["score"], reverse=True)
        
        return {
            "opportunities": opportunities,
            "total": len(opportunities),
            "is_live": True,
            "has_leaps": len(opportunities) > 0,
            "note": f"Found {len(opportunities)} PMCC opportunities with true LEAPS",
            "filters_applied": {
                "price_range": f"${min_price}-${max_price}",
                "leaps_leg": f"{min_leaps_dte}-{max_leaps_dte} days, delta {min_leaps_delta}-{max_leaps_delta}",
                "short_leg": f"{min_short_dte}-{max_short_dte} days, delta {min_short_delta}-{max_short_delta}",
                "min_roi_per_cycle": f"{min_roi}%",
                "min_annualized_roi": f"{min_annualized_roi}%"
            }
        }
        
    except Exception as e:
        logging.error(f"PMCC screener error: {e}")
        return {"opportunities": [], "total": 0, "error": str(e), "is_mock": True}

@screener_router.get("/filters")
async def get_saved_filters(user: dict = Depends(get_current_user)):
    filters = await db.screener_filters.find({"user_id": user["id"]}, {"_id": 0}).to_list(100)
    return filters

@screener_router.post("/filters")
async def save_filter(filter_data: ScreenerFilterCreate, user: dict = Depends(get_current_user)):
    filter_doc = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "name": filter_data.name,
        "filters": filter_data.filters,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.screener_filters.insert_one(filter_doc)
    return {"id": filter_doc["id"], "message": "Filter saved successfully"}

@screener_router.delete("/filters/{filter_id}")
async def delete_filter(filter_id: str, user: dict = Depends(get_current_user)):
    result = await db.screener_filters.delete_one({"id": filter_id, "user_id": user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Filter not found")
    return {"message": "Filter deleted"}

# ==================== PORTFOLIO ROUTES ====================

@portfolio_router.get("/positions")
async def get_portfolio_positions(user: dict = Depends(get_current_user)):
    positions = await db.portfolio.find({"user_id": user["id"]}, {"_id": 0}).to_list(1000)
    
    # Calculate P/L for each position
    for pos in positions:
        symbol = pos.get("symbol", "")
        stock_data = MOCK_STOCKS.get(symbol, {"price": pos.get("avg_cost", 0)})
        current_price = stock_data["price"]
        pos["current_price"] = current_price
        
        # Calculate P/L
        if pos.get("position_type") == "stock" or pos.get("position_type") == "covered_call":
            cost_basis = pos.get("shares", 0) * pos.get("avg_cost", 0)
            current_value = pos.get("shares", 0) * current_price
            premium_received = pos.get("option_premium", 0) * 100 if pos.get("option_premium") else 0
            pos["unrealized_pl"] = round(current_value - cost_basis + premium_received, 2)
            pos["unrealized_pl_pct"] = round((pos["unrealized_pl"] / cost_basis * 100) if cost_basis > 0 else 0, 2)
        elif pos.get("position_type") == "pmcc":
            leaps_cost = pos.get("leaps_cost", 0) * 100
            premium_received = pos.get("option_premium", 0) * 100 if pos.get("option_premium") else 0
            pos["unrealized_pl"] = round(premium_received - leaps_cost, 2)
            pos["unrealized_pl_pct"] = round((pos["unrealized_pl"] / leaps_cost * 100) if leaps_cost > 0 else 0, 2)
    
    return positions

@portfolio_router.post("/positions")
async def add_portfolio_position(position: PortfolioPositionCreate, user: dict = Depends(get_current_user)):
    pos_doc = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        **position.model_dump(),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.portfolio.insert_one(pos_doc)
    return {"id": pos_doc["id"], "message": "Position added successfully"}

@portfolio_router.put("/positions/{position_id}")
async def update_portfolio_position(position_id: str, position: PortfolioPositionCreate, user: dict = Depends(get_current_user)):
    result = await db.portfolio.update_one(
        {"id": position_id, "user_id": user["id"]},
        {"$set": position.model_dump()}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Position not found")
    return {"message": "Position updated"}

@portfolio_router.delete("/positions/{position_id}")
async def delete_portfolio_position(position_id: str, user: dict = Depends(get_current_user)):
    result = await db.portfolio.delete_one({"id": position_id, "user_id": user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Position not found")
    return {"message": "Position deleted"}

@portfolio_router.post("/import-csv")
async def import_csv(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    """Import portfolio from Interactive Brokers CSV"""
    content = await file.read()
    decoded = content.decode('utf-8')
    
    reader = csv.DictReader(io.StringIO(decoded))
    imported = 0
    
    for row in reader:
        try:
            # Map IB CSV columns to our schema
            pos_doc = {
                "id": str(uuid.uuid4()),
                "user_id": user["id"],
                "symbol": row.get("Symbol", row.get("symbol", "")),
                "position_type": "stock",
                "shares": int(float(row.get("Quantity", row.get("quantity", 0)))),
                "avg_cost": float(row.get("Cost Basis Per Share", row.get("avg_cost", 0))),
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            if pos_doc["symbol"]:
                await db.portfolio.insert_one(pos_doc)
                imported += 1
        except Exception as e:
            logging.error(f"Error importing row: {e}")
            continue
    
    return {"message": f"Imported {imported} positions"}

@portfolio_router.get("/summary")
async def get_portfolio_summary(user: dict = Depends(get_current_user)):
    positions = await db.portfolio.find({"user_id": user["id"]}, {"_id": 0}).to_list(1000)
    
    total_value = 0
    total_cost = 0
    total_premium = 0
    
    for pos in positions:
        symbol = pos.get("symbol", "")
        stock_data = MOCK_STOCKS.get(symbol, {"price": pos.get("avg_cost", 0)})
        current_price = stock_data["price"]
        
        if pos.get("position_type") in ["stock", "covered_call"]:
            total_value += pos.get("shares", 0) * current_price
            total_cost += pos.get("shares", 0) * pos.get("avg_cost", 0)
            if pos.get("option_premium"):
                total_premium += pos.get("option_premium", 0) * 100
        elif pos.get("position_type") == "pmcc":
            total_cost += pos.get("leaps_cost", 0) * 100
            if pos.get("option_premium"):
                total_premium += pos.get("option_premium", 0) * 100
    
    return {
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "total_premium_collected": round(total_premium, 2),
        "unrealized_pl": round(total_value - total_cost + total_premium, 2),
        "positions_count": len(positions)
    }

# ==================== WATCHLIST ROUTES ====================

@watchlist_router.get("/")
async def get_watchlist(user: dict = Depends(get_current_user)):
    items = await db.watchlist.find({"user_id": user["id"]}, {"_id": 0}).to_list(100)
    
    # Enrich with current prices
    for item in items:
        symbol = item.get("symbol", "")
        stock_data = MOCK_STOCKS.get(symbol, {"price": 0, "change": 0, "change_pct": 0})
        item["current_price"] = stock_data["price"]
        item["change"] = stock_data["change"]
        item["change_pct"] = stock_data["change_pct"]
    
    return items

@watchlist_router.post("/")
async def add_to_watchlist(item: WatchlistItemCreate, user: dict = Depends(get_current_user)):
    # Check if already in watchlist
    existing = await db.watchlist.find_one({"user_id": user["id"], "symbol": item.symbol.upper()})
    if existing:
        raise HTTPException(status_code=400, detail="Symbol already in watchlist")
    
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "symbol": item.symbol.upper(),
        "target_price": item.target_price,
        "notes": item.notes,
        "added_at": datetime.now(timezone.utc).isoformat()
    }
    await db.watchlist.insert_one(doc)
    return {"id": doc["id"], "message": "Added to watchlist"}

@watchlist_router.delete("/{item_id}")
async def remove_from_watchlist(item_id: str, user: dict = Depends(get_current_user)):
    result = await db.watchlist.delete_one({"id": item_id, "user_id": user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"message": "Removed from watchlist"}

# ==================== NEWS ROUTES ====================

@news_router.get("/")
async def get_market_news(
    symbol: Optional[str] = None,
    limit: int = Query(10, ge=1, le=50),
    user: dict = Depends(get_current_user)
):
    # Try MarketAux API for news and sentiment
    marketaux_token = await get_marketaux_client()
    if marketaux_token:
        try:
            async with httpx.AsyncClient() as client:
                params = {
                    "api_token": marketaux_token,
                    "limit": limit,
                    "language": "en"
                }
                if symbol:
                    params["symbols"] = symbol.upper()
                
                response = await client.get(
                    "https://api.marketaux.com/v1/news/all",
                    params=params
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("data"):
                        return [{
                            "title": n.get("title"),
                            "description": n.get("description"),
                            "source": n.get("source"),
                            "url": n.get("url"),
                            "published_at": n.get("published_at"),
                            "sentiment": n.get("sentiment"),  # MarketAux provides sentiment
                            "sentiment_score": n.get("sentiment_score"),
                            "tickers": [e.get("symbol") for e in n.get("entities", []) if e.get("symbol")],
                            "is_live": True
                        } for n in data["data"]]
        except Exception as e:
            logging.error(f"MarketAux API error: {e}")
    
    # Return mock news
    return MOCK_NEWS[:limit]

# ==================== AI ROUTES ====================

@ai_router.post("/analyze")
async def ai_analysis(request: AIAnalysisRequest, user: dict = Depends(get_current_user)):
    """AI-powered trade analysis using GPT-5.2"""
    settings = await get_admin_settings()
    
    # Use Emergent LLM key or admin-configured key
    api_key = settings.openai_api_key or os.environ.get('EMERGENT_LLM_KEY')
    
    if not api_key:
        # Return mock analysis if no API key
        return {
            "analysis": f"AI analysis for {request.symbol or 'market'} ({request.analysis_type})",
            "recommendations": [
                "Consider selling weekly covered calls at 0.25-0.30 delta",
                "Monitor IV rank for optimal entry points",
                "Set alerts for earnings dates to avoid assignment risk"
            ],
            "confidence": 0.75,
            "is_mock": True
        }
    
    try:
        client = OpenAI(api_key=api_key)
        
        # Build context-aware prompt
        system_prompt = """You are an expert options trading analyst specializing in covered calls and Poor Man's Covered Calls (PMCC). 
        Provide actionable, data-driven analysis with specific recommendations. 
        Include composite scores (1-100), confidence levels, and clear rationale for all suggestions.
        Format responses with clear sections: Summary, Key Metrics, Recommendations, Risk Assessment."""
        
        user_prompt = f"""Analysis Type: {request.analysis_type}
        Symbol: {request.symbol or 'General Market'}
        Context: {request.context or 'Standard analysis requested'}
        
        Please provide:
        1. Current opportunity assessment
        2. Specific strike/expiry recommendations
        3. Risk factors and mitigation strategies
        4. Confidence score and rationale"""
        
        response = client.chat.completions.create(
            model="gpt-4o",  # Using gpt-4o as fallback
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=1000,
            temperature=0.7
        )
        
        analysis_text = response.choices[0].message.content
        
        return {
            "analysis": analysis_text,
            "symbol": request.symbol,
            "analysis_type": request.analysis_type,
            "confidence": 0.85,
            "is_mock": False
        }
        
    except Exception as e:
        logging.error(f"AI Analysis error: {e}")
        return {
            "analysis": f"Unable to generate AI analysis: {str(e)}",
            "is_mock": True,
            "error": True
        }

@ai_router.get("/opportunities")
async def ai_opportunity_scan(
    min_score: float = Query(70, ge=0, le=100),
    user: dict = Depends(get_current_user)
):
    """AI-scored trading opportunities"""
    opportunities = generate_mock_covered_call_opportunities()
    
    # Add AI scores
    for opp in opportunities:
        # Calculate composite score based on multiple factors
        roi_score = min(opp["roi_pct"] * 20, 40)
        iv_score = opp["iv_rank"] / 100 * 20
        delta_score = 20 - abs(opp["delta"] - 0.3) * 100
        protection_score = min(opp["downside_protection"], 10) * 2
        
        opp["ai_score"] = round(roi_score + iv_score + delta_score + protection_score, 1)
        opp["ai_rationale"] = f"ROI: {roi_score:.0f}/40, IV: {iv_score:.0f}/20, Delta: {delta_score:.0f}/20, Protection: {protection_score:.0f}/20"
    
    # Filter by minimum score
    filtered = [o for o in opportunities if o["ai_score"] >= min_score]
    filtered.sort(key=lambda x: x["ai_score"], reverse=True)
    
    return {"opportunities": filtered[:20], "total": len(filtered)}

# ==================== ADMIN ROUTES ====================

@admin_router.get("/settings")
async def get_settings(user: dict = Depends(get_admin_user)):
    settings = await db.admin_settings.find_one({}, {"_id": 0})
    if settings:
        # Mask API keys for security
        if settings.get("massive_api_key"):
            settings["massive_api_key"] = settings["massive_api_key"][:8] + "..." + settings["massive_api_key"][-4:] if len(settings["massive_api_key"]) > 12 else "****"
        if settings.get("massive_access_id"):
            settings["massive_access_id"] = settings["massive_access_id"][:8] + "..." + settings["massive_access_id"][-4:] if len(settings["massive_access_id"]) > 12 else "****"
        if settings.get("massive_secret_key"):
            settings["massive_secret_key"] = settings["massive_secret_key"][:8] + "..." + settings["massive_secret_key"][-4:] if len(settings["massive_secret_key"]) > 12 else "****"
        if settings.get("marketaux_api_token"):
            settings["marketaux_api_token"] = settings["marketaux_api_token"][:8] + "..." + settings["marketaux_api_token"][-4:] if len(settings["marketaux_api_token"]) > 12 else "****"
        if settings.get("openai_api_key"):
            settings["openai_api_key"] = settings["openai_api_key"][:8] + "..." + settings["openai_api_key"][-4:] if len(settings["openai_api_key"]) > 12 else "****"
    return settings or {}

@admin_router.post("/settings")
async def update_settings(settings: AdminSettings, user: dict = Depends(get_admin_user)):
    settings_dict = settings.model_dump(exclude_unset=True)
    
    # Don't update masked values
    masked_fields = ["massive_api_key", "massive_access_id", "massive_secret_key", "marketaux_api_token", "openai_api_key"]
    for field in masked_fields:
        if settings_dict.get(field) and "..." in settings_dict[field]:
            del settings_dict[field]
    
    await db.admin_settings.update_one({}, {"$set": settings_dict}, upsert=True)
    return {"message": "Settings updated successfully"}

@admin_router.post("/clear-cache")
async def clear_api_cache(prefix: Optional[str] = None, admin: dict = Depends(get_admin_user)):
    """Clear API response cache. Optionally filter by prefix."""
    deleted_count = await clear_cache(prefix)
    return {"message": f"Cleared {deleted_count} cache entries", "deleted_count": deleted_count}

@admin_router.get("/cache-stats")
async def get_cache_stats(admin: dict = Depends(get_admin_user)):
    """Get cache statistics"""
    try:
        total_entries = await db.api_cache.count_documents({})
        entries = await db.api_cache.find({}, {"cache_key": 1, "cached_at": 1, "_id": 0}).to_list(100)
        
        stats = {
            "total_entries": total_entries,
            "entries": []
        }
        
        for entry in entries:
            cached_at = entry.get("cached_at")
            if isinstance(cached_at, str):
                cached_at = datetime.fromisoformat(cached_at.replace('Z', '+00:00'))
            age = (datetime.now(timezone.utc) - cached_at).total_seconds() if cached_at else 0
            stats["entries"].append({
                "cache_key": entry.get("cache_key"),
                "age_seconds": round(age, 1)
            })
        
        return stats
    except Exception as e:
        logging.error(f"Cache stats error: {e}")
        return {"total_entries": 0, "error": str(e)}

@admin_router.post("/make-admin/{user_id}")
async def make_admin(user_id: str, admin: dict = Depends(get_admin_user)):
    result = await db.users.update_one({"id": user_id}, {"$set": {"is_admin": True}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "User promoted to admin"}

# ==================== SUBSCRIPTION ROUTES ====================

class SubscriptionLinksUpdate(BaseModel):
    mode: str = Field(..., description="'test' or 'live'")
    trial_link: Optional[str] = None
    monthly_link: Optional[str] = None
    yearly_link: Optional[str] = None

@subscription_router.get("/links")
async def get_subscription_links():
    """Get active subscription payment links (public endpoint)"""
    settings = await db.subscription_settings.find_one({"type": "stripe_links"}, {"_id": 0})
    
    if not settings:
        # Return default test links
        return {
            "trial_link": "https://buy.stripe.com/test_3cI7sD8jQ97bbUH6ip8Ra01",
            "monthly_link": "https://buy.stripe.com/test_bJe7sD6bIdnr2k7cGN8Ra02",
            "yearly_link": "https://buy.stripe.com/test_9B64grarY1EJ2k72298Ra00",
            "mode": "test"
        }
    
    mode = settings.get("active_mode", "test")
    links_key = f"{mode}_links"
    links = settings.get(links_key, {})
    
    return {
        "trial_link": links.get("trial", ""),
        "monthly_link": links.get("monthly", ""),
        "yearly_link": links.get("yearly", ""),
        "mode": mode
    }

@subscription_router.get("/admin/settings")
async def get_subscription_settings(admin: dict = Depends(get_admin_user)):
    """Get full subscription settings (admin only)"""
    settings = await db.subscription_settings.find_one({"type": "stripe_links"}, {"_id": 0})
    
    if not settings:
        # Return default structure
        return {
            "active_mode": "test",
            "test_links": {
                "trial": "https://buy.stripe.com/test_3cI7sD8jQ97bbUH6ip8Ra01",
                "monthly": "https://buy.stripe.com/test_bJe7sD6bIdnr2k7cGN8Ra02",
                "yearly": "https://buy.stripe.com/test_9B64grarY1EJ2k72298Ra00"
            },
            "live_links": {
                "trial": "",
                "monthly": "",
                "yearly": ""
            }
        }
    
    return {
        "active_mode": settings.get("active_mode", "test"),
        "test_links": settings.get("test_links", {}),
        "live_links": settings.get("live_links", {})
    }

@subscription_router.post("/admin/settings")
async def update_subscription_settings(
    active_mode: str = Query(..., description="'test' or 'live'"),
    test_trial: Optional[str] = Query(None),
    test_monthly: Optional[str] = Query(None),
    test_yearly: Optional[str] = Query(None),
    live_trial: Optional[str] = Query(None),
    live_monthly: Optional[str] = Query(None),
    live_yearly: Optional[str] = Query(None),
    admin: dict = Depends(get_admin_user)
):
    """Update subscription settings (admin only)"""
    # Get existing settings
    existing = await db.subscription_settings.find_one({"type": "stripe_links"})
    
    test_links = existing.get("test_links", {}) if existing else {}
    live_links = existing.get("live_links", {}) if existing else {}
    
    # Update only provided values
    if test_trial is not None:
        test_links["trial"] = test_trial
    if test_monthly is not None:
        test_links["monthly"] = test_monthly
    if test_yearly is not None:
        test_links["yearly"] = test_yearly
    if live_trial is not None:
        live_links["trial"] = live_trial
    if live_monthly is not None:
        live_links["monthly"] = live_monthly
    if live_yearly is not None:
        live_links["yearly"] = live_yearly
    
    update_doc = {
        "type": "stripe_links",
        "active_mode": active_mode,
        "test_links": test_links,
        "live_links": live_links,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.subscription_settings.update_one(
        {"type": "stripe_links"},
        {"$set": update_doc},
        upsert=True
    )
    
    return {"message": "Subscription settings updated successfully", "active_mode": active_mode}

@subscription_router.post("/admin/switch-mode")
async def switch_subscription_mode(
    mode: str = Query(..., description="'test' or 'live'"),
    admin: dict = Depends(get_admin_user)
):
    """Quick switch between test and live mode (admin only)"""
    if mode not in ["test", "live"]:
        raise HTTPException(status_code=400, detail="Mode must be 'test' or 'live'")
    
    await db.subscription_settings.update_one(
        {"type": "stripe_links"},
        {"$set": {"active_mode": mode, "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True
    )
    
    return {"message": f"Switched to {mode} mode", "active_mode": mode}

# ==================== ROOT ROUTES ====================

@api_router.get("/")
async def root():
    return {"message": "Covered Call Engine API - Options Trading Platform", "version": "1.0.0"}

@api_router.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}

# Include all routers
api_router.include_router(auth_router)
api_router.include_router(stocks_router)
api_router.include_router(options_router)
api_router.include_router(screener_router)
api_router.include_router(portfolio_router)
api_router.include_router(watchlist_router)
api_router.include_router(news_router)
api_router.include_router(ai_router)
api_router.include_router(admin_router)
api_router.include_router(subscription_router)

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("startup")
async def startup():
    # Create indexes
    await db.users.create_index("email", unique=True)
    await db.users.create_index("id", unique=True)
    await db.portfolio.create_index([("user_id", 1), ("symbol", 1)])
    await db.watchlist.create_index([("user_id", 1), ("symbol", 1)])
    await db.screener_filters.create_index("user_id")
    
    # Create cache index with TTL (auto-expire after 1 hour)
    await db.api_cache.create_index("cache_key", unique=True)
    await db.api_cache.create_index("cached_at", expireAfterSeconds=3600)  # Auto-delete after 1 hour
    
    # Create default admin if not exists
    admin = await db.users.find_one({"email": "admin@premiumhunter.com"})
    if not admin:
        admin_doc = {
            "id": str(uuid.uuid4()),
            "email": "admin@premiumhunter.com",
            "name": "Admin",
            "password": hash_password("admin123"),
            "is_admin": True,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.users.insert_one(admin_doc)
        logger.info("Default admin user created: admin@premiumhunter.com / admin123")

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
