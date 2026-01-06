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
                        # Get underlying price from first result
                        underlying_price = results[0].get("underlying_asset", {}).get("price", 0) if results else 0
                        
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
                                "bid": last_quote.get("bid", 0),
                                "ask": last_quote.get("ask", 0),
                                "last": day.get("close", 0) or last_quote.get("midpoint", 0),
                                "delta": greeks.get("delta", 0),
                                "gamma": greeks.get("gamma", 0),
                                "theta": greeks.get("theta", 0),
                                "vega": greeks.get("vega", 0),
                                "iv": opt.get("implied_volatility", 0),
                                "volume": day.get("volume", 0),
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
                    logging.error(f"Massive.com API 403 Forbidden - check API plan for options access")
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
    except:
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
            symbols_to_scan = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM", "SPY", "QQQ"]
            
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
            
            logging.info(f"Found {len(opportunities)} live opportunities")
            
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
    
    return {"opportunities": filtered, "total": len(filtered), "is_mock": True}

@screener_router.get("/pmcc")
async def screen_pmcc(
    min_leaps_delta: float = Query(0.8, ge=0.5, le=1),
    max_short_delta: float = Query(0.3, ge=0.1, le=0.5),
    user: dict = Depends(get_current_user)
):
    # Check if we have Massive.com credentials for live data
    api_key = await get_massive_api_key()
    
    if api_key:
        try:
            opportunities = []
            symbols_to_scan = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "SPY", "QQQ"]
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                for symbol in symbols_to_scan:
                    try:
                        # Get options chain
                        params = {
                            "apiKey": api_key,
                            "limit": 250,
                            "contract_type": "call"
                        }
                        
                        response = await client.get(
                            f"https://api.massive.com/v3/snapshot/options/{symbol}",
                            params=params
                        )
                        
                        if response.status_code == 200:
                            data = response.json()
                            results = data.get("results", [])
                            
                            if not results:
                                continue
                            
                            underlying_price = results[0].get("underlying_asset", {}).get("price", 0)
                            
                            # Separate LEAPS (>300 DTE) and short-term options (<45 DTE)
                            leaps_options = []
                            short_options = []
                            
                            for opt in results:
                                details = opt.get("details", {})
                                greeks = opt.get("greeks", {})
                                
                                if details.get("contract_type") != "call":
                                    continue
                                
                                dte = calculate_dte(details.get("expiration_date", ""))
                                delta = abs(greeks.get("delta", 0))
                                
                                if dte >= 300 and delta >= min_leaps_delta:
                                    leaps_options.append({
                                        "strike": details.get("strike_price", 0),
                                        "expiry": details.get("expiration_date", ""),
                                        "dte": dte,
                                        "delta": delta,
                                        "cost": opt.get("last_quote", {}).get("midpoint", 0) or opt.get("day", {}).get("close", 0)
                                    })
                                elif 7 <= dte <= 45 and delta <= max_short_delta and delta >= 0.1:
                                    short_options.append({
                                        "strike": details.get("strike_price", 0),
                                        "expiry": details.get("expiration_date", ""),
                                        "dte": dte,
                                        "delta": delta,
                                        "premium": opt.get("last_quote", {}).get("midpoint", 0) or opt.get("day", {}).get("close", 0)
                                    })
                            
                            # Match LEAPS with short calls
                            if leaps_options and short_options:
                                best_leap = max(leaps_options, key=lambda x: x["delta"])
                                best_short = min(short_options, key=lambda x: abs(x["delta"] - 0.25))
                                
                                if best_leap["cost"] > 0:
                                    max_profit = best_short["strike"] - best_leap["strike"] + best_short["premium"] - best_leap["cost"]
                                    max_loss = best_leap["cost"] - best_short["premium"]
                                    breakeven = best_leap["strike"] + best_leap["cost"] - best_short["premium"]
                                    roi_on_capital = (best_short["premium"] / best_leap["cost"]) * 100 if best_leap["cost"] > 0 else 0
                                    
                                    opportunities.append({
                                        "symbol": symbol,
                                        "stock_price": round(underlying_price, 2),
                                        "leaps": {
                                            "strike": best_leap["strike"],
                                            "expiry": best_leap["expiry"],
                                            "delta": round(best_leap["delta"], 2),
                                            "cost": round(best_leap["cost"], 2),
                                            "dte": best_leap["dte"]
                                        },
                                        "short_call": {
                                            "strike": best_short["strike"],
                                            "expiry": best_short["expiry"],
                                            "delta": round(best_short["delta"], 2),
                                            "premium": round(best_short["premium"], 2),
                                            "dte": best_short["dte"]
                                        },
                                        "max_profit": round(max_profit, 2),
                                        "max_loss": round(max_loss, 2),
                                        "breakeven": round(breakeven, 2),
                                        "monthly_income_potential": round(best_short["premium"] * 12, 2),
                                        "roi_on_capital": round(roi_on_capital, 2)
                                    })
                    except Exception as e:
                        logging.error(f"PMCC scan error for {symbol}: {e}")
                        continue
            
            opportunities.sort(key=lambda x: x["roi_on_capital"], reverse=True)
            return {"opportunities": opportunities, "total": len(opportunities), "is_live": True}
            
        except Exception as e:
            logging.error(f"PMCC screener error: {e}")
    
    # Fallback to mock data
    opportunities = generate_mock_pmcc_opportunities()
    
    filtered = [
        o for o in opportunities
        if o["leaps"]["delta"] >= min_leaps_delta
        and o["short_call"]["delta"] <= max_short_delta
    ]
    
    return {"opportunities": filtered, "total": len(filtered), "is_mock": True}

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
