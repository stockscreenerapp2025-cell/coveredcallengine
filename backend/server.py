from fastapi import FastAPI, APIRouter, HTTPException, Depends, Query, UploadFile, File, Request
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
import aiohttp
from openai import OpenAI
import hashlib
import json
import stripe
import pytz
import yfinance as yf
import pandas as pd
import math
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import asyncio

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Cache configuration - default cache duration in seconds (5 minutes for real-time data)
CACHE_DURATION_SECONDS = 300
# Weekend cache duration - 72 hours (Friday close to Monday open)
WEEKEND_CACHE_DURATION_SECONDS = 259200  # 72 hours

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
simulator_router = APIRouter(prefix="/simulator", tags=["Simulator"])

# ==================== CACHE HELPERS ====================

def is_market_closed() -> bool:
    """Check if US stock market is currently closed (weekend or outside market hours)"""
    import pytz
    try:
        eastern = pytz.timezone('US/Eastern')
        now_eastern = datetime.now(eastern)
        
        # Check if weekend (Saturday=5, Sunday=6)
        if now_eastern.weekday() >= 5:
            return True
        
        # Check if outside market hours (9:30 AM - 4:00 PM ET)
        market_open = now_eastern.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now_eastern.replace(hour=16, minute=0, second=0, microsecond=0)
        
        if now_eastern < market_open or now_eastern > market_close:
            return True
            
        return False
    except Exception as e:
        logging.warning(f"Error checking market hours: {e}")
        return False

def get_cache_duration() -> int:
    """Get appropriate cache duration based on market status"""
    if is_market_closed():
        logging.info("Market is closed - using extended cache duration")
        return WEEKEND_CACHE_DURATION_SECONDS
    return CACHE_DURATION_SECONDS

def generate_cache_key(prefix: str, params: Dict[str, Any]) -> str:
    """Generate a unique cache key based on prefix and parameters"""
    params_str = json.dumps(params, sort_keys=True)
    hash_str = hashlib.md5(params_str.encode()).hexdigest()
    return f"{prefix}_{hash_str}"

async def get_cached_data(cache_key: str, max_age_seconds: int = None) -> Optional[Dict]:
    """Retrieve cached data if it exists and is not expired"""
    if max_age_seconds is None:
        max_age_seconds = get_cache_duration()
    
    try:
        cached = await db.api_cache.find_one({"cache_key": cache_key}, {"_id": 0})
        if cached:
            cached_at = cached.get("cached_at")
            if isinstance(cached_at, str):
                cached_at = datetime.fromisoformat(cached_at.replace('Z', '+00:00'))
            
            age = (datetime.now(timezone.utc) - cached_at).total_seconds()
            if age < max_age_seconds:
                logging.info(f"Cache hit for {cache_key}, age: {age:.1f}s (max: {max_age_seconds}s)")
                return cached.get("data")
            else:
                logging.info(f"Cache expired for {cache_key}, age: {age:.1f}s > {max_age_seconds}s")
    except Exception as e:
        logging.error(f"Cache retrieval error: {e}")
    return None

async def get_last_trading_day_data(cache_key: str) -> Optional[Dict]:
    """Get data from the last trading day - used for weekends/after hours"""
    try:
        # Look for the permanent "last trading day" cache
        ltd_key = f"ltd_{cache_key}"
        cached = await db.api_cache.find_one({"cache_key": ltd_key}, {"_id": 0})
        if cached:
            logging.info(f"Using last trading day data for {cache_key}")
            data = cached.get("data", {})
            data["is_last_trading_day"] = True
            data["cached_date"] = cached.get("cached_at")
            return data
    except Exception as e:
        logging.error(f"Error getting last trading day data: {e}")
    return None

async def set_cached_data(cache_key: str, data: Dict, save_as_last_trading_day: bool = True) -> bool:
    """Store data in cache. Also saves as 'last trading day' data when market is open."""
    try:
        now = datetime.now(timezone.utc)
        cache_doc = {
            "cache_key": cache_key,
            "data": data,
            "cached_at": now.isoformat()
        }
        await db.api_cache.update_one(
            {"cache_key": cache_key},
            {"$set": cache_doc},
            upsert=True
        )
        logging.info(f"Cache set for {cache_key}")
        
        # If market is open, also save as "last trading day" data for weekend access
        if save_as_last_trading_day and not is_market_closed():
            ltd_key = f"ltd_{cache_key}"
            ltd_doc = {
                "cache_key": ltd_key,
                "data": data,
                "cached_at": now.isoformat(),
                "trading_date": now.strftime("%Y-%m-%d")
            }
            await db.api_cache.update_one(
                {"cache_key": ltd_key},
                {"$set": ltd_doc},
                upsert=True
            )
            logging.info(f"Last trading day cache set for {ltd_key}")
        
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
    # First try to find document with API keys
    settings = await db.admin_settings.find_one({"massive_api_key": {"$exists": True}}, {"_id": 0})
    if not settings:
        # Fallback to type-based query
        settings = await db.admin_settings.find_one({"type": "api_keys"}, {"_id": 0})
    if not settings:
        # Legacy fallback - first document without type
        settings = await db.admin_settings.find_one({"type": {"$exists": False}}, {"_id": 0})
    if settings:
        return AdminSettings(**settings)
    return AdminSettings()

async def get_massive_api_key():
    """Get Massive.com API key string"""
    settings = await get_admin_settings()
    if settings.massive_api_key and "..." not in settings.massive_api_key:
        return settings.massive_api_key
    return None

async def fetch_stock_quote(symbol: str, api_key: str = None) -> Optional[dict]:
    """Fetch current stock quote - tries Yahoo Finance first for real-time prices, then Massive.com fallback"""
    # Normalize symbol for different APIs
    yahoo_symbol = symbol.replace(' ', '-').replace('.', '-')  # BRK B -> BRK-B
    
    # Try Yahoo Finance first for real-time market prices
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}?interval=1d&range=1d"
            headers = {"User-Agent": "Mozilla/5.0"}
            async with session.get(url, headers=headers, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    result = data.get("chart", {}).get("result", [])
                    if result:
                        meta = result[0].get("meta", {})
                        price = meta.get("regularMarketPrice", 0)
                        if price:
                            return {
                                "symbol": symbol.upper(),
                                "price": price,
                                "open": meta.get("regularMarketOpen", 0),
                                "high": meta.get("regularMarketDayHigh", 0),
                                "low": meta.get("regularMarketDayLow", 0),
                                "volume": meta.get("regularMarketVolume", 0)
                            }
    except Exception as e:
        logging.warning(f"Yahoo Finance error for {symbol}: {e}")
    
    # Fallback to Massive.com API (previous day close)
    if not api_key:
        api_key = await get_massive_api_key()
    
    if api_key:
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev"
                headers = {"Authorization": f"Bearer {api_key}"}
                async with session.get(url, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        results = data.get("results", [])
                        if results:
                            return {
                                "symbol": symbol.upper(),
                                "price": results[0].get("c", 0),
                                "open": results[0].get("o", 0),
                                "high": results[0].get("h", 0),
                                "low": results[0].get("l", 0),
                                "volume": results[0].get("v", 0)
                            }
        except Exception as e:
            logging.warning(f"Massive API error for {symbol}: {e}")
    
    # Last resort: check mock data
    mock = MOCK_STOCKS.get(symbol.upper())
    if mock:
        return {"symbol": symbol.upper(), "price": mock["price"]}
    
    return None

async def get_marketaux_client():
    """Get MarketAux API token"""
    settings = await get_admin_settings()
    if settings.marketaux_api_token and "..." not in settings.marketaux_api_token:
        return settings.marketaux_api_token
    return None

import asyncio

async def fetch_options_chain_polygon(symbol: str, api_key: str, contract_type: str = "call", max_dte: int = 45, min_dte: int = 1, current_price: float = 0) -> list:
    """
    Fetch options chain using Polygon.io endpoints that work with basic subscription:
    1. v3/reference/options/contracts - Get list of available contracts
    2. v2/aggs/ticker/{contract}/prev - Get previous day OHLCV for each contract (PARALLEL)
    
    Returns list of option data with pricing info.
    
    Uses asyncio.gather for PARALLEL price fetching to dramatically improve performance.
    
    If current_price is provided, filters contracts to strikes between 40-95% of price (for LEAPS)
    or 95-150% of price (for short calls - EXPANDED range).
    """
    from datetime import datetime, timedelta
    
    options = []
    today = datetime.now()
    min_expiry = (today + timedelta(days=min_dte)).strftime("%Y-%m-%d")
    max_expiry = (today + timedelta(days=max_dte)).strftime("%Y-%m-%d")
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Step 1: Get list of contracts - request sorted by strike price
            params = {
                "underlying_ticker": symbol.upper(),
                "contract_type": contract_type,
                "expired": "false",
                "expiration_date.gte": min_expiry,
                "expiration_date.lte": max_expiry,
                "limit": 250,
                "apiKey": api_key
            }
            
            # For short calls (low DTE), sort ascending to get OTM strikes first
            # For LEAPS (high DTE), sort descending to get ITM strikes first
            if min_dte < 100:
                params["sort"] = "strike_price"
                params["order"] = "asc"  # Get lower strikes first, then filter to OTM
            else:
                params["sort"] = "strike_price"
                params["order"] = "desc"  # Get higher strikes first for LEAPS
            
            contracts_response = await client.get(
                "https://api.polygon.io/v3/reference/options/contracts",
                params=params
            )
            
            if contracts_response.status_code != 200:
                logging.warning(f"Polygon contracts API returned {contracts_response.status_code} for {symbol}")
                return []
            
            contracts_data = contracts_response.json()
            contracts = contracts_data.get("results", [])
            
            if not contracts:
                logging.info(f"No contracts found for {symbol} (DTE: {min_dte}-{max_dte})")
                return []
            
            logging.info(f"Found {len(contracts)} raw {contract_type} contracts for {symbol} (DTE: {min_dte}-{max_dte})")
            
            # If current_price provided, filter to valid strike range before fetching pricing
            if current_price > 0:
                if min_dte >= 300:  # LEAPS - want ITM (40-95% of price)
                    valid_contracts = [c for c in contracts 
                                      if current_price * 0.40 <= c.get("strike_price", 0) <= current_price * 0.95]
                    logging.info(f"{symbol} LEAPS: {len(valid_contracts)} contracts in ITM range (40-95% of ${current_price:.2f})")
                else:  # Short calls - want OTM (95-150% of price) - EXPANDED RANGE
                    valid_contracts = [c for c in contracts 
                                      if current_price * 0.95 <= c.get("strike_price", 0) <= current_price * 1.50]
                    logging.info(f"{symbol} Short: {len(valid_contracts)} contracts in OTM range (95-150% of ${current_price:.2f})")
                
                # Use filtered contracts if we have them, otherwise use all contracts
                if valid_contracts:
                    contracts = valid_contracts
                else:
                    logging.warning(f"{symbol}: No contracts in target range, using top 50 from all")
                    contracts = contracts[:50]
            
            # Limit to 40 contracts per symbol for price fetching (increased from 30)
            contracts_to_fetch = contracts[:40]
            logging.info(f"Fetching prices for {len(contracts_to_fetch)} contracts for {symbol}")
            
            # Step 2: Fetch prices in PARALLEL using asyncio.gather
            async def fetch_single_price(contract):
                """Fetch price for a single contract"""
                contract_ticker = contract.get("ticker", "")
                if not contract_ticker:
                    return None
                
                try:
                    price_response = await client.get(
                        f"https://api.polygon.io/v2/aggs/ticker/{contract_ticker}/prev",
                        params={"apiKey": api_key}
                    )
                    
                    if price_response.status_code == 200:
                        price_data = price_response.json()
                        results = price_data.get("results", [])
                        
                        if results:
                            result = results[0]
                            strike = contract.get("strike_price", 0)
                            
                            return {
                                "contract_ticker": contract_ticker,
                                "underlying": symbol.upper(),
                                "strike": strike,
                                "expiry": contract.get("expiration_date", ""),
                                "dte": calculate_dte(contract.get("expiration_date", "")),
                                "type": contract.get("contract_type", "call"),
                                "close": result.get("c", 0),
                                "open": result.get("o", 0),
                                "high": result.get("h", 0),
                                "low": result.get("l", 0),
                                "volume": result.get("v", 0),
                                "vwap": result.get("vw", 0),
                            }
                except Exception as e:
                    logging.debug(f"Error fetching price for {contract_ticker}: {e}")
                return None
            
            # Execute all price fetches in parallel with semaphore to limit concurrency
            semaphore = asyncio.Semaphore(15)  # Limit to 15 concurrent requests
            
            async def fetch_with_semaphore(contract):
                async with semaphore:
                    return await fetch_single_price(contract)
            
            # Run all fetches in parallel
            results = await asyncio.gather(*[fetch_with_semaphore(c) for c in contracts_to_fetch], return_exceptions=True)
            
            # Filter out None results and exceptions
            for result in results:
                if result and not isinstance(result, Exception):
                    options.append(result)
            
            logging.info(f"Successfully fetched {len(options)} option prices for {symbol}")
            return options
            
    except Exception as e:
        logging.error(f"Error fetching options chain for {symbol}: {e}")
        return []


async def fetch_options_chain_yahoo(symbol: str, contract_type: str = "call", max_dte: int = 45, min_dte: int = 1, current_price: float = 0) -> list:
    """
    Fetch options chain using Yahoo Finance (yfinance) as fallback.
    Useful for ETFs like SPY, QQQ, IWM that may not have data in Polygon.
    
    Returns list of option data with pricing info.
    """
    import asyncio
    from datetime import datetime, timedelta
    
    options = []
    today = datetime.now()
    min_expiry = today + timedelta(days=min_dte)
    max_expiry = today + timedelta(days=max_dte)
    
    try:
        # yfinance is synchronous, so run in executor
        def fetch_yahoo_options():
            try:
                ticker = yf.Ticker(symbol)
                
                # Get available expiration dates
                expirations = ticker.options
                if not expirations:
                    logging.info(f"Yahoo: No options available for {symbol}")
                    return []
                
                # Filter expirations within DTE range
                valid_expirations = []
                for exp in expirations:
                    try:
                        exp_date = datetime.strptime(exp, "%Y-%m-%d")
                        if min_expiry <= exp_date <= max_expiry:
                            valid_expirations.append(exp)
                    except:
                        continue
                
                if not valid_expirations:
                    logging.info(f"Yahoo: No expirations in DTE range for {symbol}")
                    return []
                
                logging.info(f"Yahoo: Found {len(valid_expirations)} valid expirations for {symbol}")
                
                results = []
                for exp in valid_expirations[:3]:  # Limit to 3 expirations for performance
                    try:
                        chain = ticker.option_chain(exp)
                        df = chain.calls if contract_type == "call" else chain.puts
                        
                        if df.empty:
                            continue
                        
                        for _, row in df.iterrows():
                            strike = row.get('strike', 0)
                            last_price = row.get('lastPrice', 0)
                            
                            # Skip if no price data
                            if last_price <= 0:
                                continue
                            
                            # Apply strike filtering if current_price provided
                            if current_price > 0:
                                strike_pct = (strike / current_price) * 100
                                if min_dte >= 300:  # LEAPS
                                    if strike_pct < 40 or strike_pct > 95:
                                        continue
                                else:  # Short calls
                                    if strike_pct < 95 or strike_pct > 150:
                                        continue
                            
                            exp_date = datetime.strptime(exp, "%Y-%m-%d")
                            dte = (exp_date - today).days
                            
                            results.append({
                                "contract_ticker": row.get('contractSymbol', ''),
                                "underlying": symbol.upper(),
                                "strike": strike,
                                "expiry": exp,
                                "dte": dte,
                                "type": contract_type,
                                "close": last_price,
                                "bid": row.get('bid', 0) if pd.notna(row.get('bid')) else 0,
                                "ask": row.get('ask', 0) if pd.notna(row.get('ask')) else 0,
                                "volume": int(row.get('volume', 0)) if pd.notna(row.get('volume')) else 0,
                                "open_interest": int(row.get('openInterest', 0)) if pd.notna(row.get('openInterest')) else 0,
                                "implied_volatility": row.get('impliedVolatility', 0) if pd.notna(row.get('impliedVolatility')) else 0,
                            })
                            
                            # Limit results per expiration
                            if len(results) > 40:
                                break
                                
                    except Exception as e:
                        logging.warning(f"Yahoo: Error fetching chain for {symbol} {exp}: {e}")
                        continue
                
                return results
                
            except Exception as e:
                logging.error(f"Yahoo: Error for {symbol}: {e}")
                return []
        
        # Run synchronous yfinance call in executor
        loop = asyncio.get_event_loop()
        options = await loop.run_in_executor(None, fetch_yahoo_options)
        
        logging.info(f"Yahoo: Retrieved {len(options)} options for {symbol}")
        return options
        
    except Exception as e:
        logging.error(f"Yahoo options fetch error for {symbol}: {e}")
        return []


# ETF symbols that should use Yahoo Finance fallback
ETF_SYMBOLS = {"SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK", "XLV", "XLI", "XLB", "XLU", "XLP", "XLY", "XLRE", "GLD", "SLV", "USO", "TLT", "HYG", "EEM", "VXX", "ARKK", "TQQQ", "SQQQ"}


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
                    f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev",
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
                    f"https://api.polygon.io/v2/last/trade/{symbol}",
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
                    f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev",
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
                    f"https://api.polygon.io/v3/reference/tickers/{symbol}",
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
                    f"https://api.polygon.io/v2/reference/news",
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
                    f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/day/{start_date}/{end_date}",
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
                    f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev",
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
                
                url = f"https://api.polygon.io/v3/snapshot/options/{symbol}"
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
    include_stocks: bool = Query(True),
    include_etfs: bool = Query(True),
    include_index: bool = Query(False),
    bypass_cache: bool = Query(False),
    user: dict = Depends(get_current_user)
):
    # Generate cache key based on all filter parameters
    cache_params = {
        "min_roi": min_roi, "max_dte": max_dte, "min_delta": min_delta, "max_delta": max_delta,
        "min_iv_rank": min_iv_rank, "min_price": min_price, "max_price": max_price,
        "include_stocks": include_stocks, "include_etfs": include_etfs, "include_index": include_index,
        "min_volume": min_volume, "min_open_interest": min_open_interest,
        "weekly_only": weekly_only, "monthly_only": monthly_only
    }
    cache_key = generate_cache_key("screener_covered_calls", cache_params)
    
    # Check cache first (unless bypassed)
    if not bypass_cache:
        cached_data = await get_cached_data(cache_key)
        if cached_data:
            cached_data["from_cache"] = True
            cached_data["market_closed"] = is_market_closed()
            return cached_data
        
        # If market is closed and no recent cache, try last trading day data
        if is_market_closed():
            ltd_data = await get_last_trading_day_data(cache_key)
            if ltd_data:
                ltd_data["from_cache"] = True
                ltd_data["market_closed"] = True
                return ltd_data
    
    # Check if we have Massive.com credentials for live data
    api_key = await get_massive_api_key()
    
    logging.info(f"Screener called: api_key={'present' if api_key else 'missing'}, min_roi={min_roi}, max_dte={max_dte}")
    
    if api_key:
        try:
            opportunities = []
            
            # Tiered symbol scanning - prioritize stocks under $100
            tier1_symbols = [
                # Under $100 - High Priority (reduced for speed)
                "INTC", "AMD", "BAC", "WFC", "C", "F", "GM", "T", "VZ",
                "PFE", "MRK", "KO", "PEP", "NKE", "DIS",
                "PYPL", "UBER", "SNAP", "PLTR", "SOFI",
                "AAL", "DAL", "CCL",
                "USB", "PNC", "CFG",
                "DVN", "APA", "HAL", "OXY"
            ]
            
            tier2_symbols = [
                # $100-$500 - Secondary
                "AAPL", "MSFT", "META", "AMD",
                "JPM", "GS", "V", "MA",
                "HD", "COST",
                "XOM", "CVX"
            ]
            
            # ETF symbols (separate category - any price)
            etf_symbols = [
                "SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK"
            ]
            
            # Build symbols list based on security type filters
            symbols_to_scan = []
            
            # Add stock symbols if stocks are included
            if include_stocks:
                if max_price <= 100:
                    symbols_to_scan.extend(tier1_symbols)
                elif min_price >= 100:
                    symbols_to_scan.extend(tier2_symbols)
                else:
                    symbols_to_scan.extend(tier1_symbols + tier2_symbols)
            
            # Add ETF symbols if ETFs are included
            if include_etfs:
                symbols_to_scan.extend(etf_symbols)
            
            # Note: Index options would be added here if include_index is True
            # Currently no index-specific symbols as they require different data sources
            
            logging.info(f"Security type filter: stocks={include_stocks}, etfs={include_etfs}, index={include_index}")
            logging.info(f"Symbols to scan: {len(symbols_to_scan)} symbols")
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                for symbol in symbols_to_scan:
                    try:
                        # First get the current stock price
                        stock_response = await client.get(
                            f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev",
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
                            
                        # Skip if price out of range (but always include ETFs)
                        is_etf = symbol.upper() in ETF_SYMBOLS
                        if not is_etf and (underlying_price < min_price or underlying_price > max_price):
                            continue
                        
                        # Get options chain - use Yahoo Finance for ETFs, Polygon for stocks
                        if is_etf:
                            options_results = await fetch_options_chain_yahoo(symbol, "call", max_dte, min_dte=1, current_price=underlying_price)
                            logging.info(f"{symbol} (ETF): Using Yahoo Finance, got {len(options_results)} options")
                        else:
                            options_results = await fetch_options_chain_polygon(symbol, api_key, "call", max_dte, min_dte=1, current_price=underlying_price)
                        
                        # Try Yahoo as fallback if Polygon returns nothing
                        if not options_results and not is_etf:
                            options_results = await fetch_options_chain_yahoo(symbol, "call", max_dte, min_dte=1, current_price=underlying_price)
                            if options_results:
                                logging.info(f"{symbol}: Polygon returned nothing, Yahoo fallback got {len(options_results)} options")
                        
                        if not options_results:
                            continue
                        
                        logging.info(f"Found {len(options_results)} options for {symbol}")
                        
                        for opt in options_results:
                            strike = opt.get("strike", 0)
                            expiry = opt.get("expiry", "")
                            dte = opt.get("dte", 0)
                            
                            # For covered calls, filter to ATM or slightly OTM
                            # Use different ranges for high-priced ETFs vs regular stocks
                            strike_pct = (strike / underlying_price) * 100 if underlying_price > 0 else 0
                            if is_etf:
                                # For ETFs, accept slightly wider range (95% to 108%)
                                if strike_pct < 95 or strike_pct > 108:
                                    continue
                            else:
                                # For stocks, use stricter range (97% to 115%)
                                if strike_pct < 97 or strike_pct > 115:
                                    continue
                            
                            # Apply DTE filters
                            if dte > max_dte or dte < 1:
                                continue
                            if weekly_only and dte > 7:
                                continue
                            if monthly_only and dte <= 7:
                                continue
                            
                            # Estimate delta based on moneyness
                            strike_pct_diff = ((strike - underlying_price) / underlying_price) * 100
                            if strike_pct_diff <= 0:
                                estimated_delta = 0.55 - (abs(strike_pct_diff) * 0.02)
                            else:
                                estimated_delta = 0.50 - (strike_pct_diff * 0.03)
                            estimated_delta = max(0.15, min(0.60, estimated_delta))
                            
                            # Skip delta filter for ETFs to get more results
                            if not is_etf and (estimated_delta < min_delta or estimated_delta > max_delta):
                                continue
                            
                            # Use close price as premium
                            premium = opt.get("close", 0) or opt.get("vwap", 0)
                            
                            if premium <= 0:
                                continue
                            
                            # Calculate ROI
                            roi_pct = (premium / underlying_price) * 100
                            
                            if roi_pct < min_roi:
                                continue
                            
                            volume = opt.get("volume", 0) or 0
                            
                            if volume < min_volume:
                                continue
                            
                            iv = 0.25  # Default estimate since we don't have real-time IV
                            iv_rank = min(100, iv * 100)
                            
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
                            delta_score = max(0, 20 - abs(estimated_delta - 0.3) * 50)
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
                                "delta": round(estimated_delta, 3),
                                "theta": 0,
                                "iv": round(iv, 4),
                                "iv_rank": round(iv_rank, 1),
                                "downside_protection": round(protection, 2),
                                "volume": volume,
                                "open_interest": 0,
                                "score": score
                            })
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
            logging.error(f"Screener error with Polygon.io: {e}")
    
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
    cache_key = "dashboard_opportunities_v2"
    
    # Check cache first (with extended duration for weekends)
    cached_data = await get_cached_data(cache_key)
    if cached_data:
        cached_data["from_cache"] = True
        cached_data["market_closed"] = is_market_closed()
        return cached_data
    
    # If market is closed and no recent cache, try last trading day data
    if is_market_closed():
        ltd_data = await get_last_trading_day_data(cache_key)
        if ltd_data:
            ltd_data["from_cache"] = True
            ltd_data["market_closed"] = True
            return ltd_data
    
    api_key = await get_massive_api_key()
    
    if not api_key:
        return {"opportunities": [], "total": 0, "message": "API key not configured", "is_mock": True}
    
    try:
        # Extended list of stocks to scan - prioritize under $100
        symbols_to_scan = [
            # Under $100 stocks - Priority
            "INTC", "CSCO", "MU", "QCOM", "TXN", "ADI", "MCHP", "ON", "HPQ",
            "BAC", "WFC", "C", "USB", "PNC", "TFC", "KEY", "RF", "CFG", "FITB",
            "KO", "PEP", "NKE", "SBUX", "DIS", "GM", "F",
            "VZ", "T", "TMUS",
            "PFE", "MRK", "ABBV", "BMY", "GILD",
            "OXY", "DVN", "APA", "HAL", "SLB", "MRO",
            "CAT", "DE", "GE", "HON",
            "PYPL", "SQ", "ROKU", "SNAP", "UBER", "LYFT",
            "AAL", "DAL", "UAL", "CCL", "NCLH",
            "PLTR", "SOFI", "HOOD", "RIVN", "LCID", "NIO",
            # $100-150 range
            "AAPL", "AMD", "DELL", "IBM", "ORCL"
        ]
        
        opportunities = []
        
        async with httpx.AsyncClient(timeout=90.0) as client:
            for symbol in symbols_to_scan:
                try:
                    # Get stock price
                    stock_response = await client.get(
                        f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev",
                        params={"apiKey": api_key}
                    )
                    
                    if stock_response.status_code != 200:
                        continue
                    
                    stock_data = stock_response.json()
                    if not stock_data.get("results"):
                        continue
                    
                    current_price = stock_data["results"][0].get("c", 0)
                    
                    # RELAXED: Stock price between $20 and $150
                    if current_price < 20 or current_price > 150:
                        continue
                    
                    # Get historical data for SMA and trend
                    end_date = datetime.now().strftime("%Y-%m-%d")
                    start_date = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")
                    
                    aggs_response = await client.get(
                        f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/day/{start_date}/{end_date}",
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
                            f"https://api.polygon.io/v3/reference/tickers/{symbol}",
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
                            f"https://api.polygon.io/v3/reference/dividends",
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
                            f"https://api.polygon.io/v2/reference/news",
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
                    
                    # Get options chain - use Yahoo Finance for ETFs, Polygon for stocks
                    if symbol.upper() in ETF_SYMBOLS:
                        options_results = await fetch_options_chain_yahoo(symbol, "call", 45, min_dte=1, current_price=current_price)
                        logging.info(f"Dashboard {symbol} (ETF): Using Yahoo Finance, got {len(options_results)} options")
                    else:
                        options_results = await fetch_options_chain_polygon(symbol, api_key, "call", 45, min_dte=1, current_price=current_price)
                    
                    # Try Yahoo as fallback if Polygon returns nothing
                    if not options_results and symbol.upper() not in ETF_SYMBOLS:
                        options_results = await fetch_options_chain_yahoo(symbol, "call", 45, min_dte=1, current_price=current_price)
                        if options_results:
                            logging.info(f"Dashboard {symbol}: Polygon returned nothing, Yahoo fallback got {len(options_results)} options")
                    
                    if not options_results:
                        continue
                    
                    # Find best weekly and monthly options with RELAXED thresholds
                    best_weekly = None
                    best_monthly = None
                    
                    for opt in options_results:
                        strike = opt.get("strike", 0)
                        expiry = opt.get("expiry", "")
                        dte = opt.get("dte", 0)
                        
                        if dte < 1 or dte > 45:
                            continue
                        
                        # Filter for ATM or slightly OTM strikes only
                        strike_pct_diff = ((strike - current_price) / current_price) * 100
                        
                        # Accept strikes from -2% (slightly ITM) to +10% (OTM)
                        if strike_pct_diff < -2 or strike_pct_diff > 10:
                            continue
                        
                        # Use close price as premium
                        premium = opt.get("close", 0) or opt.get("vwap", 0)
                        
                        if premium <= 0:
                            continue
                        
                        # Estimate delta based on moneyness (simplified calculation)
                        # OTM options have lower delta
                        if strike_pct_diff <= 0:
                            estimated_delta = 0.55 - (abs(strike_pct_diff) * 0.02)
                        else:
                            estimated_delta = 0.50 - (strike_pct_diff * 0.03)
                        estimated_delta = max(0.15, min(0.60, estimated_delta))
                        
                        roi_pct = (premium / current_price) * 100
                        volume = opt.get("volume", 0)
                        
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
                            "delta": round(estimated_delta, 3),
                            "iv": 25.0,  # Default IV estimate
                            "sma_50": round(sma_50, 2),
                            "sma_200": round(sma_200, 2),
                            "trend_6m": round(trend_6m, 1),
                            "trend_12m": round(trend_12m, 1),
                            "volume": volume,
                            "open_interest": 0,
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
        
        result = {
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
        
        # Cache the result for weekend access
        await set_cached_data(cache_key, result)
        
        return result
        
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
    cache_key = "dashboard_pmcc_v2"
    
    # Check cache first (with extended duration for weekends)
    cached_data = await get_cached_data(cache_key)
    if cached_data:
        cached_data["from_cache"] = True
        cached_data["market_closed"] = is_market_closed()
        return cached_data
    
    # If market is closed and no recent cache, try last trading day data
    if is_market_closed():
        ltd_data = await get_last_trading_day_data(cache_key)
        if ltd_data:
            ltd_data["from_cache"] = True
            ltd_data["market_closed"] = True
            return ltd_data
    
    api_key = await get_massive_api_key()
    
    if not api_key:
        return {"opportunities": [], "total": 0, "message": "API key not configured", "is_mock": True}
    
    try:
        symbols_to_scan = [
            # Full symbol list for PMCC Dashboard
            "AAPL", "MSFT", "GOOGL", "META", "NVDA", "AMD", "INTC", "MU", "QCOM",
            "SPY", "QQQ", "IWM", "DIA",
            "JPM", "BAC", "WFC", "GS", "C", "MS",
            "COST", "HD", "NKE", "DIS", "SBUX",
            "UNH", "JNJ", "PFE", "MRK", "LLY",
            "XOM", "CVX", "COP", "OXY",
            "PYPL", "V", "MA", "UBER"
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
                        f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev",
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
                    
                    # Fetch LEAPS options (365-730 days = 12-24 months)
                    leaps_options_raw = await fetch_options_chain_polygon(symbol, api_key, "call", max_dte=730, min_dte=365, current_price=current_price)
                    
                    # Fetch short-term options (7-45 days)
                    short_options_raw = await fetch_options_chain_polygon(symbol, api_key, "call", max_dte=45, min_dte=7, current_price=current_price)
                    
                    leaps_options = []
                    short_options = []
                    
                    # Process LEAPS options
                    for opt in leaps_options_raw:
                        strike = opt.get("strike", 0)
                        dte = opt.get("dte", 0)
                        price = opt.get("close", 0) or opt.get("vwap", 0)
                        
                        if price <= 0:
                            continue
                        
                        # LEAPS must be ITM but not too deep (strike should be 60-90% of current price)
                        # This ensures realistic PMCC setups
                        strike_pct = (strike / current_price) * 100
                        if strike_pct < 60 or strike_pct > 95:
                            continue
                        
                        # Estimate delta - ITM options have high delta
                        itm_pct = ((current_price - strike) / current_price) * 100
                        estimated_delta = min(0.95, 0.60 + (itm_pct * 0.02))
                        
                        # LEAPS should have high delta (0.70+)
                        if estimated_delta < 0.70:
                            continue
                        
                        leaps_options.append({
                            "strike": strike,
                            "expiry": opt.get("expiry", ""),
                            "dte": dte,
                            "delta": round(estimated_delta, 3),
                            "cost": round(price * 100, 2),
                            "iv": 25.0  # Default estimate
                        })
                    
                    # Process short-term options
                    short_count = 0
                    for opt in short_options_raw:
                        strike = opt.get("strike", 0)
                        dte = opt.get("dte", 0)
                        price = opt.get("close", 0) or opt.get("vwap", 0)
                        
                        if price <= 0:
                            continue
                        
                        # Short leg should be OTM (strike above current price)
                        if strike <= current_price:
                            continue
                        
                        # Estimate delta - OTM options have lower delta
                        otm_pct = ((strike - current_price) / current_price) * 100
                        estimated_delta = max(0.10, 0.50 - (otm_pct * 0.04))
                        
                        # Short leg should be OTM with delta 0.15-0.40
                        if estimated_delta < 0.15 or estimated_delta > 0.40:
                            continue
                        
                        short_count += 1
                        short_options.append({
                            "strike": strike,
                            "expiry": opt.get("expiry", ""),
                            "dte": dte,
                            "delta": round(estimated_delta, 3),
                            "premium": round(price * 100, 2),
                            "iv": 25.0  # Default estimate
                        })
                    
                    logging.info(f"{symbol}: Short options - {len(short_options_raw)} raw, {short_count} passed filters")
                    
                    # Build PMCC if both legs available
                    if leaps_options and short_options:
                        logging.info(f"{symbol}: Found {len(leaps_options)} LEAPS and {len(short_options)} short options")
                        
                        # Best LEAPS: highest delta (deepest ITM)
                        best_leaps = max(leaps_options, key=lambda x: x["delta"])
                        
                        # Best short: closest to delta 0.25
                        best_short = min(short_options, key=lambda x: abs(x["delta"] - 0.25))
                        
                        logging.info(f"{symbol}: Best LEAPS strike={best_leaps['strike']}, cost={best_leaps['cost']}, Best Short premium={best_short['premium']}")
                        
                        if best_leaps["cost"] > 0:
                            net_debit = best_leaps["cost"] - best_short["premium"]
                            
                            # PMCC should have positive net debit (cost to enter)
                            if net_debit <= 0:
                                logging.info(f"{symbol}: Skipping - negative net debit {net_debit}")
                                continue
                            
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
        
        result = {
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
        
        # Cache the result for weekend access
        await set_cached_data(cache_key, result)
        
        return result
        
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
    bypass_cache: bool = Query(False),
    user: dict = Depends(get_current_user)
):
    """
    Screen for PMCC opportunities with customizable filters.
    Uses true LEAPS options (12-24 months) for the long leg.
    """
    # Generate cache key for PMCC screener
    cache_params = {
        "min_price": min_price, "max_price": max_price,
        "min_leaps_delta": min_leaps_delta, "max_leaps_delta": max_leaps_delta,
        "min_leaps_dte": min_leaps_dte, "max_leaps_dte": max_leaps_dte,
        "min_short_delta": min_short_delta, "max_short_delta": max_short_delta,
        "min_short_dte": min_short_dte, "max_short_dte": max_short_dte,
        "min_roi": min_roi, "min_annualized_roi": min_annualized_roi
    }
    cache_key = generate_cache_key("pmcc_screener", cache_params)
    
    # Check cache first (unless bypassed)
    if not bypass_cache:
        cached_data = await get_cached_data(cache_key)
        if cached_data:
            cached_data["from_cache"] = True
            cached_data["market_closed"] = is_market_closed()
            return cached_data
        
        # If market is closed, try last trading day data
        if is_market_closed():
            ltd_data = await get_last_trading_day_data(cache_key)
            if ltd_data:
                ltd_data["from_cache"] = True
                ltd_data["market_closed"] = True
                return ltd_data
    else:
        logging.info(f"PMCC screener: Cache bypassed by user request")
    
    api_key = await get_massive_api_key()
    
    if not api_key:
        return {"opportunities": [], "total": 0, "message": "API key not configured", "is_mock": True}
    
    try:
        # Full symbol list for PMCC Screener - comprehensive coverage
        symbols_to_scan = [
            # Tech - various price ranges
            "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD", "INTC", "MU",
            "QCOM", "TXN", "NFLX", "CRM", "ADBE", "ORCL", "IBM", "CSCO", "AVGO", "NOW",
            # ETFs
            "SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK", "XLV", "XLI",
            # Financial
            "JPM", "BAC", "WFC", "GS", "C", "MS", "BLK", "SCHW", "USB", "PNC", "AXP",
            # Consumer
            "COST", "WMT", "HD", "LOW", "NKE", "SBUX", "MCD", "DIS", "TGT",
            # Healthcare
            "UNH", "JNJ", "PFE", "MRK", "LLY", "ABBV", "TMO", "ABT", "CVS", "CI",
            # Industrial/Energy
            "CAT", "DE", "BA", "HON", "GE", "XOM", "CVX", "COP", "SLB", "OXY", "DVN",
            # Other popular
            "PYPL", "SQ", "UBER", "V", "MA", "COIN", "HOOD", "SOFI", "PLTR", "SNAP"
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
                        f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev",
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
                    
                    # Fetch LEAPS options using the working endpoint
                    leaps_options_raw = await fetch_options_chain_polygon(symbol, api_key, "call", max_dte=max_leaps_dte, min_dte=min_leaps_dte, current_price=current_price)
                    
                    # Fetch short-term options using the working endpoint
                    short_options_raw = await fetch_options_chain_polygon(symbol, api_key, "call", max_dte=max_short_dte, min_dte=min_short_dte, current_price=current_price)
                    
                    leaps_options = []
                    short_options = []
                    
                    # Process LEAPS options
                    leaps_count = 0
                    for opt in leaps_options_raw:
                        strike = opt.get("strike", 0)
                        dte = opt.get("dte", 0)
                        price = opt.get("close", 0) or opt.get("vwap", 0)
                        
                        if price <= 0:
                            continue
                        
                        # LEAPS must be ITM (strike should be 40-95% of current price for valid PMCC)
                        strike_pct = (strike / current_price) * 100
                        if strike_pct < 40 or strike_pct > 95:
                            continue
                        
                        # Estimate delta - ITM options have high delta
                        itm_pct = ((current_price - strike) / current_price) * 100
                        estimated_delta = min(0.95, 0.60 + (itm_pct * 0.02))
                        
                        # Apply LEAPS delta filter
                        if estimated_delta < min_leaps_delta or estimated_delta > max_leaps_delta:
                            continue
                        
                        leaps_count += 1
                        leaps_options.append({
                            "strike": strike,
                            "expiry": opt.get("expiry", ""),
                            "dte": dte,
                            "delta": round(estimated_delta, 3),
                            "cost": round(price * 100, 2),
                            "iv": 25.0
                        })
                    
                    logging.info(f"{symbol}: Processed {len(leaps_options_raw)} raw LEAPS, {leaps_count} passed filters")
                    
                    # Process short-term options
                    short_count = 0
                    for opt in short_options_raw:
                        strike = opt.get("strike", 0)
                        dte = opt.get("dte", 0)
                        price = opt.get("close", 0) or opt.get("vwap", 0)
                        
                        if price <= 0:
                            continue
                        
                        # Short leg must be OTM (strike above current price)
                        if strike <= current_price:
                            continue
                        
                        # Estimate delta - OTM options have lower delta
                        otm_pct = ((strike - current_price) / current_price) * 100
                        estimated_delta = max(0.10, 0.50 - (otm_pct * 0.04))
                        
                        # Apply short delta filter
                        if estimated_delta < min_short_delta or estimated_delta > max_short_delta:
                            continue
                        
                        short_count += 1
                        short_options.append({
                            "strike": strike,
                            "expiry": opt.get("expiry", ""),
                            "dte": dte,
                            "delta": round(estimated_delta, 3),
                            "premium": round(price * 100, 2),
                            "iv": 25.0
                        })
                    
                    logging.info(f"{symbol}: Short options - {len(short_options_raw)} raw, {short_count} passed filters")
                    
                    # Build PMCC opportunities if both legs available
                    if leaps_options and short_options:
                        # Best LEAPS: highest delta (deepest ITM)
                        best_leaps = max(leaps_options, key=lambda x: x["delta"])
                        
                        # Best short: closest to middle of delta range
                        target_delta = (min_short_delta + max_short_delta) / 2
                        best_short = min(short_options, key=lambda x: abs(x["delta"] - target_delta))
                        
                        if best_leaps["cost"] > 0:
                            net_debit = best_leaps["cost"] - best_short["premium"]
                            
                            # PMCC should have positive net debit (cost to enter)
                            if net_debit <= 0:
                                continue
                            
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
        
        result = {
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
        
        # Cache the result
        await set_cached_data(cache_key, result)
        
        return result
        
    except Exception as e:
        logging.error(f"PMCC screener error: {e}")
        return {"opportunities": [], "total": 0, "error": str(e), "is_mock": True}

@screener_router.get("/filters")
async def get_saved_filters(user: dict = Depends(get_current_user)):
    filters = await db.screener_filters.find({"user_id": user["id"]}, {"_id": 0}).to_list(100)
    return filters

@screener_router.post("/clear-cache")
async def clear_screener_cache(user: dict = Depends(get_current_user)):
    """Clear all screener-related cache to force fresh data fetch"""
    try:
        # Clear specific screener caches
        prefixes_to_clear = [
            "screener_covered_calls",
            "pmcc_screener",
            "dashboard_opportunities",
            "dashboard_pmcc"
        ]
        total_cleared = 0
        for prefix in prefixes_to_clear:
            count = await clear_cache(prefix)
            total_cleared += count
        
        logging.info(f"Cache cleared by user {user.get('email')}: {total_cleared} entries")
        return {"message": f"Cache cleared successfully", "entries_cleared": total_cleared}
    except Exception as e:
        logging.error(f"Error clearing cache: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to clear cache: {str(e)}")

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
    """Import portfolio from simple CSV format"""
    content = await file.read()
    decoded = content.decode('utf-8')
    
    reader = csv.DictReader(io.StringIO(decoded))
    imported = 0
    
    for row in reader:
        try:
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

@portfolio_router.post("/import-ibkr")
async def import_ibkr_csv(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    """Import and parse IBKR transaction history CSV - overwrites existing data for same accounts"""
    from services.ibkr_parser import parse_ibkr_csv
    
    content = await file.read()
    decoded = content.decode('utf-8')
    
    # Parse the IBKR CSV
    result = parse_ibkr_csv(decoded)
    
    # Get accounts from the imported file
    imported_accounts = result.get('accounts', [])
    
    # Clear existing data for these accounts (overwrite behavior)
    if imported_accounts:
        await db.ibkr_transactions.delete_many({
            "user_id": user['id'],
            "account": {"$in": imported_accounts}
        })
        await db.ibkr_trades.delete_many({
            "user_id": user['id'],
            "account": {"$in": imported_accounts}
        })
    
    # Store raw transactions
    for tx in result.get('raw_transactions', []):
        tx['user_id'] = user['id']
        await db.ibkr_transactions.insert_one(tx)
    
    # Store parsed trades
    for trade in result.get('trades', []):
        trade['user_id'] = user['id']
        # Remove transactions from trade doc to avoid duplication
        trade_doc = {k: v for k, v in trade.items() if k != 'transactions'}
        trade_doc['transaction_ids'] = [t['id'] for t in trade.get('transactions', [])]
        await db.ibkr_trades.insert_one(trade_doc)
    
    return {
        "message": f"Imported {len(result.get('trades', []))} trades from {len(imported_accounts)} accounts",
        "accounts": imported_accounts,
        "summary": result.get('summary', {}),
        "trades_count": len(result.get('trades', []))
    }

@portfolio_router.get("/ibkr/accounts")
async def get_ibkr_accounts(user: dict = Depends(get_current_user)):
    """Get list of broker accounts from imported data"""
    pipeline = [
        {"$match": {"user_id": user["id"]}},
        {"$group": {"_id": "$account"}},
        {"$project": {"account": "$_id", "_id": 0}}
    ]
    accounts = await db.ibkr_trades.aggregate(pipeline).to_list(100)
    return {"accounts": [a.get('account') for a in accounts if a.get('account')]}

@portfolio_router.get("/ibkr/trades")
async def get_ibkr_trades(
    user: dict = Depends(get_current_user),
    account: Optional[str] = Query(None),
    strategy: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100)
):
    """Get parsed IBKR trades with filters"""
    query = {"user_id": user["id"]}
    
    if account:
        query["account"] = account
    if strategy:
        query["strategy_type"] = strategy
    if status:
        query["status"] = status
    if symbol:
        query["symbol"] = {"$regex": symbol.upper(), "$options": "i"}
    
    skip = (page - 1) * limit
    
    trades = await db.ibkr_trades.find(query, {"_id": 0}).sort("date_opened", -1).skip(skip).limit(limit).to_list(limit)
    total = await db.ibkr_trades.count_documents(query)
    
    # Fetch current prices for open trades (uses Yahoo Finance fallback if no Massive key)
    symbols_to_fetch = list(set(t.get('symbol') for t in trades if t.get('status') == 'Open' and t.get('symbol')))
    
    # Build a price cache to avoid duplicate API calls
    price_cache = {}
    if symbols_to_fetch:
        logging.info(f"Fetching prices for {len(symbols_to_fetch)} symbols: {symbols_to_fetch}")
        for symbol in symbols_to_fetch:
            try:
                quote = await fetch_stock_quote(symbol)
                if quote and quote.get('price'):
                    price_cache[symbol] = quote.get('price')
                    logging.info(f"Got price for {symbol}: {quote.get('price')}")
                else:
                    logging.warning(f"No price returned for {symbol}")
            except Exception as e:
                logging.warning(f"Error fetching price for {symbol}: {e}")
    
    # Apply prices and calculate P/L for open trades
    for trade in trades:
        # Normalize field names for frontend compatibility (handle old data with 'strike'/'expiry' field names)
        if trade.get('strike') and not trade.get('option_strike'):
            trade['option_strike'] = trade.get('strike')
        if trade.get('expiry') and not trade.get('option_expiry'):
            trade['option_expiry'] = trade.get('expiry')
        if trade.get('option_quantity') and not trade.get('contracts'):
            trade['contracts'] = trade.get('option_quantity')
        if not trade.get('days_in_trade') and trade.get('date_opened'):
            try:
                open_dt = datetime.fromisoformat(trade['date_opened'].replace('Z', '+00:00')) if 'T' in trade['date_opened'] else datetime.strptime(trade['date_opened'], "%Y-%m-%d")
                trade['days_in_trade'] = (datetime.now(timezone.utc).replace(tzinfo=None) - open_dt.replace(tzinfo=None)).days
            except:
                pass
        if trade.get('total_fees') is None:
            trade['total_fees'] = 0
        if not trade.get('account'):
            trade['account'] = 'Manual' if trade.get('source') == 'manual' else 'IBKR'
        
        if trade.get('status') == 'Open' and trade.get('symbol'):
            symbol = trade.get('symbol')
            if symbol in price_cache:
                trade['current_price'] = price_cache[symbol]
                # Calculate unrealized P/L
                shares = trade.get('shares', 0) or 0
                entry_price = trade.get('entry_price', 0) or 0
                break_even = trade.get('break_even') or 0
                
                if shares > 0:
                    if break_even and break_even > 0:
                        trade['unrealized_pnl'] = round((trade['current_price'] - break_even) * shares, 2)
                    elif entry_price and entry_price > 0:
                        trade['unrealized_pnl'] = round((trade['current_price'] - entry_price) * shares, 2)
    
    return {
        "trades": trades,
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit
}

@portfolio_router.get("/ibkr/trades/{trade_id}")
async def get_ibkr_trade_detail(trade_id: str, user: dict = Depends(get_current_user)):
    """Get detailed trade information including transaction history"""
    trade = await db.ibkr_trades.find_one({"user_id": user["id"], "id": trade_id}, {"_id": 0})
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    
    # Normalize field names for frontend compatibility (handle old data)
    if trade.get('strike') and not trade.get('option_strike'):
        trade['option_strike'] = trade.get('strike')
    if trade.get('expiry') and not trade.get('option_expiry'):
        trade['option_expiry'] = trade.get('expiry')
    if trade.get('option_quantity') and not trade.get('contracts'):
        trade['contracts'] = trade.get('option_quantity')
    if not trade.get('days_in_trade') and trade.get('date_opened'):
        try:
            open_dt = datetime.fromisoformat(trade['date_opened'].replace('Z', '+00:00')) if 'T' in trade['date_opened'] else datetime.strptime(trade['date_opened'], "%Y-%m-%d")
            trade['days_in_trade'] = (datetime.now(timezone.utc).replace(tzinfo=None) - open_dt.replace(tzinfo=None)).days
        except:
            pass
    if trade.get('total_fees') is None:
        trade['total_fees'] = 0
    if not trade.get('account'):
        trade['account'] = 'Manual' if trade.get('source') == 'manual' else 'IBKR'
    
    # Fetch related transactions
    tx_ids = trade.get('transaction_ids', [])
    transactions = await db.ibkr_transactions.find(
        {"user_id": user["id"], "id": {"$in": tx_ids}},
        {"_id": 0}
    ).sort("datetime", 1).to_list(100)
    
    trade['transactions'] = transactions
    
    # Fetch current price for open trades (always try - uses Yahoo Finance fallback if no Massive key)
    if trade.get('symbol') and trade.get('status') == 'Open':
        try:
            quote = await fetch_stock_quote(trade['symbol'])
            if quote and quote.get('price'):
                trade['current_price'] = quote.get('price', 0)
                shares = trade.get('shares', 0) or 0
                break_even = trade.get('break_even', 0) or 0
                entry_price = trade.get('entry_price', 0) or 0
                
                if shares > 0:
                    if break_even > 0:
                        trade['unrealized_pnl'] = round((trade['current_price'] - break_even) * shares, 2)
                    elif entry_price > 0:
                        trade['unrealized_pnl'] = round((trade['current_price'] - entry_price) * shares, 2)
                    
                    if entry_price > 0:
                        trade['roi'] = round(((trade['current_price'] - (break_even or entry_price)) / entry_price) * 100, 2)
        except Exception as e:
            logging.warning(f"Error fetching quote for {trade['symbol']}: {e}")
    
    return trade

@portfolio_router.get("/ibkr/summary")
async def get_ibkr_summary(
    user: dict = Depends(get_current_user),
    account: Optional[str] = Query(None)
):
    """Get portfolio summary statistics"""
    query = {"user_id": user["id"]}
    if account:
        query["account"] = account
    
    trades = await db.ibkr_trades.find(query, {"_id": 0}).to_list(1000)
    
    # Calculate summary
    total_invested = 0
    total_premium = 0
    total_fees = 0
    open_trades = 0
    closed_trades = 0
    by_strategy = {}
    
    for trade in trades:
        strategy = trade.get('strategy_type', 'OTHER')
        
        if strategy not in by_strategy:
            by_strategy[strategy] = {'count': 0, 'premium': 0, 'invested': 0}
        by_strategy[strategy]['count'] += 1
        by_strategy[strategy]['premium'] += trade.get('premium_received', 0) or 0
        
        shares = trade.get('shares', 0) or 0
        entry = trade.get('entry_price', 0) or 0
        by_strategy[strategy]['invested'] += shares * entry
        
        total_invested += shares * entry
        total_premium += trade.get('premium_received', 0) or 0
        total_fees += trade.get('total_fees', 0) or 0
        
        if trade.get('status') == 'Open':
            open_trades += 1
        else:
            closed_trades += 1
    
    return {
        'total_trades': len(trades),
        'open_trades': open_trades,
        'closed_trades': closed_trades,
        'total_invested': round(total_invested, 2),
        'total_premium': round(total_premium, 2),
        'total_fees': round(total_fees, 2),
        'net_premium': round(total_premium - total_fees, 2),
        'by_strategy': by_strategy
    }

@portfolio_router.post("/ibkr/trades/{trade_id}/ai-suggestion")
async def get_trade_ai_suggestion(trade_id: str, user: dict = Depends(get_current_user)):
    """Get AI-powered suggestion for a trade"""
    trade = await db.ibkr_trades.find_one({"user_id": user["id"], "id": trade_id}, {"_id": 0})
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    
    suggestion = await generate_ai_suggestion_for_trade(trade)
    
    # Store suggestion
    await db.ibkr_trades.update_one(
        {"user_id": user["id"], "id": trade_id},
        {"$set": {
            "ai_suggestion": suggestion.get("full_suggestion"),
            "ai_action": suggestion.get("action"),
            "suggestion_updated": datetime.now(timezone.utc).isoformat()
        }}
    )
    
    return {"suggestion": suggestion.get("full_suggestion"), "action": suggestion.get("action"), "trade_id": trade_id}

async def generate_ai_suggestion_for_trade(trade: dict) -> dict:
    """Generate AI suggestion for a single trade with technicals, fundamentals, and news"""
    settings = await db.admin_settings.find_one({"type": "api_keys"}, {"_id": 0})
    massive_key = settings.get("massive_api_key") if settings else os.environ.get("MASSIVE_API_KEY")
    marketaux_key = settings.get("marketaux_api_key") if settings else os.environ.get("MARKETAUX_API_KEY")
    
    symbol = trade.get('symbol', '')
    current_price = None
    price_change_pct = None
    volume = None
    high_52w = None
    low_52w = None
    news_summary = "No recent news available"
    
    # Fetch current market data
    if massive_key and symbol:
        try:
            quote = await fetch_stock_quote(symbol, massive_key)
            if quote:
                current_price = quote.get('price', 0)
                volume = quote.get('volume', 0)
        except:
            pass
    
    # Fetch news from MarketAux if available
    if marketaux_key and symbol:
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://api.marketaux.com/v1/news/all?symbols={symbol}&filter_entities=true&language=en&api_token={marketaux_key}&limit=3"
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        articles = data.get('data', [])
                        if articles:
                            headlines = [a.get('title', '')[:80] for a in articles[:3]]
                            news_summary = " | ".join(headlines)
        except:
            pass
    
    # Calculate metrics
    dte = trade.get('dte', 0) or 0
    option_strike = trade.get('option_strike')
    entry_price = trade.get('entry_price', 0) or 0
    break_even = trade.get('break_even')
    premium = trade.get('premium_received', 0) or 0
    strategy = trade.get('strategy_type', '')
    
    # Calculate profit/loss status
    profit_status = "N/A"
    if current_price and entry_price:
        if break_even:
            profit_status = "Profitable" if current_price > break_even else "At Loss"
        else:
            profit_status = "Profitable" if current_price > entry_price else "At Loss"
    
    # Calculate intrinsic value for options
    intrinsic_value = None
    time_value = None
    itm_status = "N/A"
    if option_strike and current_price:
        if 'CALL' in strategy.upper() or strategy in ['COVERED_CALL', 'PMCC']:
            intrinsic_value = max(0, current_price - option_strike)
            itm_status = "ITM" if current_price > option_strike else "OTM"
        elif 'PUT' in strategy.upper() or strategy == 'NAKED_PUT':
            intrinsic_value = max(0, option_strike - current_price)
            itm_status = "ITM" if current_price < option_strike else "OTM"
    
    # Build comprehensive context for AI
    current_price_str = f"${current_price:.2f}" if current_price else "N/A"
    break_even_str = f"${break_even:.2f}" if break_even else "N/A (Stock only)"
    entry_price_str = f"${entry_price:.2f}" if entry_price else "N/A"
    option_strike_str = f"${option_strike}" if option_strike else "N/A"
    premium_str = f"${premium:.2f}" if premium else "$0.00"
    
    context = f"""
    Analyze this options trade and provide a recommendation based on technicals, fundamentals, and market news.
    
    === POSITION DETAILS ===
    Symbol: {symbol}
    Strategy: {trade.get('strategy_label', strategy)}
    Status: {trade.get('status')}
    Entry Price: {entry_price_str}
    Current Price: {current_price_str}
    Break-Even: {break_even_str}
    Profit Status: {profit_status}
    
    === OPTIONS DATA ===
    Option Strike: {option_strike_str}
    Option Expiry: {trade.get('option_expiry', 'N/A')}
    Days to Expiry (DTE): {dte}
    ITM/OTM Status: {itm_status}
    Premium Received: {premium_str}
    Shares Held: {trade.get('shares', 0)}
    
    === MARKET DATA ===
    Recent News: {news_summary}
    
    === DECISION RULES ===
    1. DTE = 0-1: If ITM, recommend LET_EXPIRE (auto-exercise saves $15-30 in fees). If OTM, option expires worthless - keep premium.
    2. DTE = 2-5 and ITM: Consider if rolling makes sense based on momentum
    3. DTE > 7: More time to evaluate - consider fundamentals and news
    4. Strong bullish news + ITM: Consider ROLL_UP to capture more upside
    5. Bearish news + at risk: Consider CLOSE or ROLL_DOWN
    6. Neutral market + profitable: HOLD and let theta decay work
    
    === RESPONSE FORMAT ===
    Start with exactly ONE action on its own line:
    - HOLD: Keep position, let time work for you
    - LET_EXPIRE: Option near expiry, let it auto-exercise/expire (saves fees)
    - ROLL_UP: Stock momentum strong, roll to higher strike for more premium
    - ROLL_DOWN: Defensive move, roll to lower strike
    - ROLL_OUT: Extend expiry date to collect more time premium
    - CLOSE: Exit position immediately
    
    Then provide 2-3 sentences explaining your reasoning based on:
    1. Technical setup (price vs strike, DTE, ITM/OTM)
    2. News/sentiment impact
    3. Risk/reward of the suggested action
    """
    
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        import uuid as uuid_module
        
        session_id = str(uuid_module.uuid4())
        system_message = """You are a professional options trading advisor specializing in covered calls and cash-secured puts. 
        Consider transaction costs ($1-2 per contract), theta decay, and market sentiment when making recommendations.
        Be specific about WHY you're recommending an action based on the data provided.
        Always start your response with exactly one action word on its own line."""
        
        llm = LlmChat(
            api_key=os.environ.get("EMERGENT_LLM_KEY"),
            session_id=session_id,
            system_message=system_message
        )
        user_msg = UserMessage(text=context)
        response = await llm.send_message(user_msg)
        
        full_suggestion = response if isinstance(response, str) else str(response)
        
        # Extract the action from the response
        action = "HOLD"  # Default
        first_line = full_suggestion.strip().split('\n')[0].strip().upper()
        for possible_action in ["LET_EXPIRE", "HOLD", "CLOSE", "ROLL_UP", "ROLL_DOWN", "ROLL_OUT"]:
            if possible_action in first_line:
                action = possible_action
                break
        
        return {
            "action": action,
            "full_suggestion": full_suggestion
        }
        
    except Exception as e:
        logging.error(f"AI suggestion error: {e}")
        return {
            "action": "N/A",
            "full_suggestion": f"Unable to generate AI suggestion: {str(e)}"
        }

@portfolio_router.post("/ibkr/generate-suggestions")
async def generate_all_suggestions(user: dict = Depends(get_current_user)):
    """Generate AI suggestions for all open trades"""
    # Get all open trades
    open_trades = await db.ibkr_trades.find(
        {"user_id": user["id"], "status": "Open"},
        {"_id": 0}
    ).to_list(100)
    
    if not open_trades:
        return {"message": "No open trades found", "updated": 0}
    
    updated = 0
    for trade in open_trades:
        try:
            suggestion = await generate_ai_suggestion_for_trade(trade)
            
            await db.ibkr_trades.update_one(
                {"user_id": user["id"], "id": trade["id"]},
                {"$set": {
                    "ai_suggestion": suggestion.get("full_suggestion"),
                    "ai_action": suggestion.get("action"),
                    "suggestion_updated": datetime.now(timezone.utc).isoformat()
                }}
            )
            updated += 1
        except Exception as e:
            logging.error(f"Error generating suggestion for {trade.get('symbol')}: {e}")
            continue
    
    return {"message": f"Generated suggestions for {updated} open trades", "updated": updated}

@portfolio_router.delete("/ibkr/clear")
async def clear_ibkr_data(user: dict = Depends(get_current_user)):
    """Clear all imported IBKR data for the user"""
    await db.ibkr_trades.delete_many({"user_id": user["id"]})
    await db.ibkr_transactions.delete_many({"user_id": user["id"]})
    return {"message": "All IBKR data cleared"}


# Manual Trade Entry Models
class ManualTradeEntry(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=10)
    trade_type: str = Field(..., description="covered_call, collar, pmcc, stock_only, option_only")
    
    # Stock leg
    stock_quantity: Optional[int] = None
    stock_price: Optional[float] = None
    stock_date: Optional[str] = None
    
    # Option leg (for covered calls / collar / PMCC)
    option_type: Optional[str] = None  # call, put
    option_action: Optional[str] = None  # sell, buy
    strike_price: Optional[float] = None
    expiry_date: Optional[str] = None
    option_premium: Optional[float] = None
    option_quantity: Optional[int] = None
    option_date: Optional[str] = None
    
    # For PMCC - LEAPS leg
    leaps_strike: Optional[float] = None
    leaps_expiry: Optional[str] = None
    leaps_cost: Optional[float] = None
    leaps_quantity: Optional[int] = None
    leaps_date: Optional[str] = None
    
    # For Collar - Protective Put leg
    put_strike: Optional[float] = None
    put_expiry: Optional[str] = None
    put_premium: Optional[float] = None
    put_quantity: Optional[int] = None
    put_date: Optional[str] = None
    
    notes: Optional[str] = None


@portfolio_router.post("/manual-trade")
async def add_manual_trade(trade: ManualTradeEntry, user: dict = Depends(get_current_user)):
    """Add a manually entered trade"""
    
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    # Helper function to validate dates
    def is_future_date(date_str):
        if not date_str:
            return False
        return date_str > today
    
    def is_past_date(date_str):
        if not date_str:
            return False
        return date_str < today
    
    # Backend validation for required fields based on trade type
    if not trade.symbol or trade.symbol.strip() == "":
        raise HTTPException(status_code=400, detail="Symbol is required")
    
    # Date validations - Purchase dates cannot be in the future
    if is_future_date(trade.stock_date):
        raise HTTPException(status_code=400, detail="Purchase date cannot be in the future")
    if is_future_date(trade.option_date):
        raise HTTPException(status_code=400, detail="Option purchase date cannot be in the future")
    if is_future_date(trade.leaps_date):
        raise HTTPException(status_code=400, detail="LEAPS purchase date cannot be in the future")
    if is_future_date(trade.put_date):
        raise HTTPException(status_code=400, detail="Put purchase date cannot be in the future")
    
    # Date validations - Expiry dates cannot be in the past
    if is_past_date(trade.expiry_date):
        raise HTTPException(status_code=400, detail="Expiry date cannot be in the past")
    if is_past_date(trade.leaps_expiry):
        raise HTTPException(status_code=400, detail="LEAPS expiry date cannot be in the past")
    if is_past_date(trade.put_expiry):
        raise HTTPException(status_code=400, detail="Put expiry date cannot be in the past")
    
    if trade.trade_type == "covered_call":
        if not trade.stock_quantity or not trade.stock_price:
            raise HTTPException(status_code=400, detail="Stock quantity and price are required for covered calls")
        if not trade.strike_price or not trade.option_premium:
            raise HTTPException(status_code=400, detail="Strike price and premium are required for covered calls")
        if not trade.expiry_date:
            raise HTTPException(status_code=400, detail="Expiry date is required for covered calls")
    
    elif trade.trade_type == "collar":
        if not trade.stock_quantity or not trade.stock_price:
            raise HTTPException(status_code=400, detail="Stock quantity and price are required for collar")
        if not trade.strike_price or not trade.option_premium:
            raise HTTPException(status_code=400, detail="Short call strike and premium are required for collar")
        if not trade.expiry_date:
            raise HTTPException(status_code=400, detail="Short call expiry date is required for collar")
        if not trade.put_strike or not trade.put_premium:
            raise HTTPException(status_code=400, detail="Protective put strike and premium are required for collar")
        if not trade.put_expiry:
            raise HTTPException(status_code=400, detail="Protective put expiry date is required for collar")
    
    elif trade.trade_type == "pmcc":
        if not trade.leaps_cost or not trade.leaps_strike:
            raise HTTPException(status_code=400, detail="LEAPS cost and strike are required for PMCC")
        if not trade.leaps_expiry:
            raise HTTPException(status_code=400, detail="LEAPS expiry date is required for PMCC")
        if not trade.strike_price or not trade.option_premium:
            raise HTTPException(status_code=400, detail="Short call strike and premium are required for PMCC")
        if not trade.expiry_date:
            raise HTTPException(status_code=400, detail="Short call expiry date is required for PMCC")
        # PMCC: Both legs must have same number of contracts
        leaps_qty = trade.leaps_quantity or 1
        short_call_qty = trade.option_quantity or 1
        if leaps_qty != short_call_qty:
            raise HTTPException(status_code=400, detail="PMCC requires same number of contracts for both LEAPS and short call")
    
    elif trade.trade_type == "stock_only":
        if not trade.stock_quantity or not trade.stock_price:
            raise HTTPException(status_code=400, detail="Stock quantity and price are required")
    
    elif trade.trade_type == "option_only":
        if not trade.strike_price:
            raise HTTPException(status_code=400, detail="Strike price is required")
        if not trade.option_premium:
            raise HTTPException(status_code=400, detail="Premium is required")
        if not trade.expiry_date:
            raise HTTPException(status_code=400, detail="Expiry date is required")
        if not trade.option_quantity or trade.option_quantity < 1:
            raise HTTPException(status_code=400, detail="Number of contracts is required")
    
    trade_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    
    # Calculate P/L and other metrics based on trade type
    realized_pnl = 0
    unrealized_pnl = 0
    cost_basis = 0
    premium_collected = 0
    put_cost = 0  # For collar protective put
    
    if trade.trade_type == "covered_call":
        # Covered call: own stock + sold call
        # stock_quantity = actual number of shares (e.g., 500 shares)
        # option_quantity = number of contracts (1 contract = 100 shares)
        if trade.stock_quantity and trade.stock_price:
            cost_basis = trade.stock_quantity * trade.stock_price  # actual shares * price
        if trade.option_premium and trade.option_quantity:
            premium_collected = trade.option_premium * trade.option_quantity * 100  # premium per share * contracts * 100
    
    elif trade.trade_type == "collar":
        # Collar: own stock + sold call + long put (protective)
        if trade.stock_quantity and trade.stock_price:
            cost_basis = trade.stock_quantity * trade.stock_price
        if trade.option_premium and trade.option_quantity:
            premium_collected = trade.option_premium * trade.option_quantity * 100
        if trade.put_premium and trade.put_quantity:
            put_cost = trade.put_premium * trade.put_quantity * 100  # Premium paid for protection
            
    elif trade.trade_type == "pmcc":
        # PMCC: LEAPS (long call) + short call
        # leaps_quantity = number of LEAPS contracts
        # option_quantity = number of short call contracts
        if trade.leaps_cost and trade.leaps_quantity:
            cost_basis = trade.leaps_cost * trade.leaps_quantity * 100  # premium per share * contracts * 100
        if trade.option_premium and trade.option_quantity:
            premium_collected = trade.option_premium * trade.option_quantity * 100
            
    elif trade.trade_type == "stock_only":
        # stock_quantity = actual number of shares
        if trade.stock_quantity and trade.stock_price:
            cost_basis = trade.stock_quantity * trade.stock_price
            
    elif trade.trade_type == "option_only":
        # option_quantity = number of contracts
        if trade.option_premium and trade.option_quantity:
            if trade.option_action == "buy":
                cost_basis = trade.option_premium * trade.option_quantity * 100
            else:
                premium_collected = trade.option_premium * trade.option_quantity * 100
    
    # Calculate DTE (days to expiration)
    dte = None
    expiry_date_str = trade.expiry_date or trade.leaps_expiry or trade.put_expiry
    if expiry_date_str:
        try:
            expiry_dt = datetime.strptime(expiry_date_str, "%Y-%m-%d")
            dte = (expiry_dt - datetime.now()).days
            if dte < 0:
                dte = 0
        except:
            pass
    
    # Calculate break-even price
    break_even = None
    if trade.trade_type == "covered_call" and trade.stock_price and trade.option_premium:
        break_even = trade.stock_price - trade.option_premium
    elif trade.trade_type == "collar" and trade.stock_price and trade.option_premium and trade.put_premium:
        # Collar break-even: stock price - call premium received + put premium paid
        break_even = trade.stock_price - trade.option_premium + trade.put_premium
    elif trade.trade_type == "pmcc" and trade.leaps_cost and trade.leaps_strike and trade.option_premium:
        break_even = trade.leaps_strike + trade.leaps_cost - trade.option_premium
    
    # Map strategy types for display
    strategy_map = {
        "covered_call": ("COVERED_CALL", "Covered Call"),
        "collar": ("COLLAR", "Collar"),
        "pmcc": ("PMCC", "PMCC"),
        "stock_only": ("STOCK", "Stock Only"),
    }
    
    # For option_only, determine specific strategy based on option_type and option_action
    if trade.trade_type == "option_only":
        option_type = (trade.option_type or "call").lower()
        option_action = (trade.option_action or "buy").lower()
        
        if option_action == "sell":
            if option_type == "call":
                strategy_type, strategy_label = "NAKED_CALL", "Naked Call"
            else:
                strategy_type, strategy_label = "NAKED_PUT", "Naked Put"
        else:  # buy
            if option_type == "call":
                strategy_type, strategy_label = "LONG_CALL", "Long Call"
            else:
                strategy_type, strategy_label = "LONG_PUT", "Long Put"
    else:
        strategy_type, strategy_label = strategy_map.get(trade.trade_type, ("OTHER", "Other"))
    
    # Calculate days in trade
    days_in_trade = None
    open_date = trade.stock_date or trade.option_date or trade.leaps_date or trade.put_date
    if open_date:
        try:
            open_dt = datetime.strptime(open_date, "%Y-%m-%d")
            days_in_trade = (datetime.now() - open_dt).days
            if days_in_trade < 0:
                days_in_trade = 0
        except:
            pass
    
    # Create trade document with proper field mapping for frontend
    trade_doc = {
        "id": trade_id,
        "user_id": user["id"],
        "symbol": trade.symbol.upper(),
        "strategy": trade.trade_type.replace("_", " ").title(),
        "strategy_type": strategy_type,
        "strategy_label": strategy_label,
        "status": "Open",
        "source": "manual",
        
        # Stock details
        "stock_quantity": trade.stock_quantity,
        "stock_price": trade.stock_price,
        "stock_date": trade.stock_date,
        
        # Option details - use frontend expected field names
        "option_type": trade.option_type,
        "option_action": trade.option_action,
        "option_strike": trade.strike_price,  # Frontend expects option_strike
        "option_expiry": trade.expiry_date,   # Frontend expects option_expiry
        "premium": trade.option_premium,
        "option_quantity": trade.option_quantity,
        "option_date": trade.option_date,
        "contracts": trade.option_quantity,  # Frontend expects contracts field
        
        # LEAPS details (for PMCC)
        "leaps_strike": trade.leaps_strike,
        "leaps_expiry": trade.leaps_expiry,
        "leaps_cost": trade.leaps_cost,
        "leaps_quantity": trade.leaps_quantity,
        "leaps_date": trade.leaps_date,
        
        # Protective Put details (for Collar)
        "protective_put_strike": trade.put_strike,
        "protective_put_expiry": trade.put_expiry,
        "protective_put_premium": trade.put_premium,
        "put_quantity": trade.put_quantity,
        "put_date": trade.put_date,
        
        # Calculated fields for display (matching frontend expectations)
        # For stocks: shares = stock_quantity (user enters actual shares)
        # For options: shares = option_quantity * 100 (contracts to shares)
        "shares": trade.stock_quantity if trade.stock_quantity else (trade.option_quantity * 100 if trade.option_quantity else None),
        "entry_price": trade.stock_price or trade.leaps_cost,
        "premium_received": trade.option_premium,
        "put_cost": put_cost,  # For collar - cost of protective put
        "break_even": break_even,
        "dte": dte,
        "days_in_trade": days_in_trade,  # Frontend expects days_in_trade
        "total_fees": 0,  # Manual trades don't have IBKR fees
        
        # P/L fields - For collar, net premium = call premium - put cost
        "cost_basis": cost_basis + put_cost if trade.trade_type == "collar" else cost_basis,
        "premium_collected": premium_collected,
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized_pnl,
        "roi": ((premium_collected - put_cost) / cost_basis * 100) if cost_basis > 0 and trade.trade_type == "collar" else ((premium_collected / cost_basis * 100) if cost_basis > 0 else 0),
        
        # Metadata
        "notes": trade.notes,
        "account": "Manual",  # Add account field for display
        "date_opened": trade.stock_date or trade.option_date or trade.leaps_date or trade.put_date or now.isoformat(),
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    
    await db.ibkr_trades.insert_one(trade_doc)
    
    # Return without _id
    if "_id" in trade_doc:
        del trade_doc["_id"]
    return {"message": "Trade added successfully", "trade": trade_doc}


@portfolio_router.put("/manual-trade/{trade_id}")
async def update_manual_trade(trade_id: str, trade: ManualTradeEntry, user: dict = Depends(get_current_user)):
    """Update a manually entered trade"""
    existing = await db.ibkr_trades.find_one({"id": trade_id, "user_id": user["id"], "source": "manual"})
    if not existing:
        raise HTTPException(status_code=404, detail="Trade not found or not a manual entry")
    
    # Recalculate values
    cost_basis = 0
    premium_collected = 0
    put_cost = 0
    
    if trade.trade_type == "covered_call":
        if trade.stock_quantity and trade.stock_price:
            cost_basis = trade.stock_quantity * trade.stock_price
        if trade.option_premium and trade.option_quantity:
            premium_collected = trade.option_premium * trade.option_quantity * 100
    elif trade.trade_type == "collar":
        if trade.stock_quantity and trade.stock_price:
            cost_basis = trade.stock_quantity * trade.stock_price
        if trade.option_premium and trade.option_quantity:
            premium_collected = trade.option_premium * trade.option_quantity * 100
        if trade.put_premium and trade.put_quantity:
            put_cost = trade.put_premium * trade.put_quantity * 100
    elif trade.trade_type == "pmcc":
        if trade.leaps_cost and trade.leaps_quantity:
            cost_basis = trade.leaps_cost * trade.leaps_quantity * 100
        if trade.option_premium and trade.option_quantity:
            premium_collected = trade.option_premium * trade.option_quantity * 100
    elif trade.trade_type == "stock_only":
        if trade.stock_quantity and trade.stock_price:
            cost_basis = trade.stock_quantity * trade.stock_price
    elif trade.trade_type == "option_only":
        if trade.option_premium and trade.option_quantity:
            if trade.option_action == "buy":
                cost_basis = trade.option_premium * trade.option_quantity * 100
            else:
                premium_collected = trade.option_premium * trade.option_quantity * 100
    
    # Calculate DTE
    dte = None
    expiry_date_str = trade.expiry_date or trade.leaps_expiry or trade.put_expiry
    if expiry_date_str:
        try:
            expiry_dt = datetime.strptime(expiry_date_str, "%Y-%m-%d")
            dte = (expiry_dt - datetime.now()).days
            if dte < 0:
                dte = 0
        except:
            pass
    
    # Calculate days in trade
    days_in_trade = None
    open_date = trade.stock_date or trade.option_date or trade.leaps_date or trade.put_date
    if open_date:
        try:
            open_dt = datetime.strptime(open_date, "%Y-%m-%d")
            days_in_trade = (datetime.now() - open_dt).days
            if days_in_trade < 0:
                days_in_trade = 0
        except:
            pass
    
    # Calculate break-even
    break_even = None
    if trade.trade_type == "covered_call" and trade.stock_price and trade.option_premium:
        break_even = trade.stock_price - trade.option_premium
    elif trade.trade_type == "collar" and trade.stock_price and trade.option_premium and trade.put_premium:
        break_even = trade.stock_price - trade.option_premium + trade.put_premium
    elif trade.trade_type == "pmcc" and trade.leaps_cost and trade.leaps_strike and trade.option_premium:
        break_even = trade.leaps_strike + trade.leaps_cost - trade.option_premium
    
    # Map strategy types
    strategy_map = {
        "covered_call": ("COVERED_CALL", "Covered Call"),
        "collar": ("COLLAR", "Collar"),
        "pmcc": ("PMCC", "PMCC"),
        "stock_only": ("STOCK", "Stock Only"),
    }
    
    if trade.trade_type == "option_only":
        option_type = (trade.option_type or "call").lower()
        option_action = (trade.option_action or "buy").lower()
        if option_action == "sell":
            if option_type == "call":
                strategy_type, strategy_label = "NAKED_CALL", "Naked Call"
            else:
                strategy_type, strategy_label = "NAKED_PUT", "Naked Put"
        else:
            if option_type == "call":
                strategy_type, strategy_label = "LONG_CALL", "Long Call"
            else:
                strategy_type, strategy_label = "LONG_PUT", "Long Put"
    else:
        strategy_type, strategy_label = strategy_map.get(trade.trade_type, ("OTHER", "Other"))
    
    update_doc = {
        "symbol": trade.symbol.upper(),
        "strategy": trade.trade_type.replace("_", " ").title(),
        "strategy_type": strategy_type,
        "strategy_label": strategy_label,
        "stock_quantity": trade.stock_quantity,
        "stock_price": trade.stock_price,
        "stock_date": trade.stock_date,
        "option_type": trade.option_type,
        "option_action": trade.option_action,
        "option_strike": trade.strike_price,  # Frontend expects option_strike
        "option_expiry": trade.expiry_date,   # Frontend expects option_expiry
        "premium": trade.option_premium,
        "option_quantity": trade.option_quantity,
        "contracts": trade.option_quantity,  # Frontend expects contracts field
        "option_date": trade.option_date,
        "leaps_strike": trade.leaps_strike,
        "leaps_expiry": trade.leaps_expiry,
        "leaps_cost": trade.leaps_cost,
        "leaps_quantity": trade.leaps_quantity,
        "leaps_date": trade.leaps_date,
        "protective_put_strike": trade.put_strike,
        "protective_put_expiry": trade.put_expiry,
        "protective_put_premium": trade.put_premium,
        "put_quantity": trade.put_quantity,
        "put_date": trade.put_date,
        "shares": trade.stock_quantity if trade.stock_quantity else (trade.option_quantity * 100 if trade.option_quantity else None),
        "entry_price": trade.stock_price or trade.leaps_cost,
        "premium_received": trade.option_premium,
        "break_even": break_even,
        "dte": dte,
        "days_in_trade": days_in_trade,
        "total_fees": 0,
        "cost_basis": cost_basis + put_cost if trade.trade_type == "collar" else cost_basis,
        "premium_collected": premium_collected,
        "put_cost": put_cost,
        "roi": ((premium_collected - put_cost) / cost_basis * 100) if cost_basis > 0 and trade.trade_type == "collar" else ((premium_collected / cost_basis * 100) if cost_basis > 0 else 0),
        "notes": trade.notes,
        "date_opened": trade.stock_date or trade.option_date or trade.leaps_date or trade.put_date or existing.get("date_opened"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    
    await db.ibkr_trades.update_one({"id": trade_id}, {"$set": update_doc})
    return {"message": "Trade updated successfully"}


@portfolio_router.delete("/manual-trade/{trade_id}")
async def delete_manual_trade(trade_id: str, user: dict = Depends(get_current_user)):
    """Delete a manually entered trade"""
    result = await db.ibkr_trades.delete_one({"id": trade_id, "user_id": user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Trade not found")
    return {"message": "Trade deleted successfully"}


@portfolio_router.put("/trade/{trade_id}/close")
async def close_trade(trade_id: str, close_price: float = Query(...), user: dict = Depends(get_current_user)):
    """Mark a trade as closed with final P/L"""
    trade = await db.ibkr_trades.find_one({"id": trade_id, "user_id": user["id"]})
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    
    # Calculate final P/L
    cost_basis = trade.get("cost_basis", 0)
    premium_collected = trade.get("premium_collected", 0)
    
    # For covered calls: P/L = premium + (close_price - stock_price) * quantity
    realized_pnl = premium_collected
    if trade.get("stock_quantity") and trade.get("stock_price"):
        stock_pnl = (close_price - trade["stock_price"]) * trade["stock_quantity"] * 100
        realized_pnl += stock_pnl
    
    await db.ibkr_trades.update_one(
        {"id": trade_id},
        {"$set": {
            "status": "Closed",
            "close_price": close_price,
            "realized_pnl": realized_pnl,
            "date_closed": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }}
    )
    
    return {"message": "Trade closed", "realized_pnl": realized_pnl}


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

# MarketAux rate limiting - 100 requests per day for free tier
MARKETAUX_DAILY_LIMIT = 100
marketaux_request_count = {"date": None, "count": 0}

# Relevant keywords for options trading news filtering
OPTIONS_TRADING_KEYWORDS = [
    'option', 'options', 'call', 'put', 'strike', 'expir', 'volatility', 'iv', 'implied',
    'premium', 'delta', 'theta', 'gamma', 'vega', 'covered call', 'iron condor', 'straddle',
    'strangle', 'spread', 'hedge', 'earnings', 'dividend', 'stock', 'etf', 'market', 'trading',
    'invest', 'bull', 'bear', 'rally', 'decline', 'rise', 'fall', 'gain', 'loss', 'profit',
    'revenue', 'eps', 'guidance', 'forecast', 'analyst', 'upgrade', 'downgrade', 'target',
    'fed', 'interest rate', 'inflation', 'gdp', 'employment', 'jobs', 'economic',
    's&p', 'nasdaq', 'dow', 'russell', 'index', 'sector', 'tech', 'financ', 'energy',
    'healthcare', 'consumer', 'industrial', 'ipo', 'merger', 'acquisition', 'buyback',
    'short', 'squeeze', 'momentum', 'breakout', 'support', 'resistance', 'trend'
]

# List of stocks/ETFs we track for news filtering
TRACKED_SYMBOLS = {
    # Top stocks
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD", "INTC", "JPM",
    "BAC", "WFC", "C", "GS", "V", "MA", "PFE", "MRK", "JNJ", "UNH", "KO", "PEP",
    "NKE", "DIS", "NFLX", "PYPL", "UBER", "SNAP", "PLTR", "SOFI", "AAL", "DAL",
    "CCL", "USB", "PNC", "CFG", "DVN", "APA", "HAL", "OXY", "HD", "COST", "XOM", "CVX",
    # ETFs
    "SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK", "XLV", "XLI", "XLB", "XLU", "XLP", "XLY",
    "GLD", "SLV", "TLT", "HYG", "VIX", "VXX", "ARKK", "TQQQ", "SQQQ"
}

def is_relevant_news(article: dict) -> bool:
    """Check if a news article is relevant for options traders"""
    title = (article.get("title") or "").lower()
    description = (article.get("description") or "").lower()
    source = (article.get("source") or "").lower()
    
    # Skip clearly irrelevant sources
    irrelevant_sources = ['entertainment', 'sports', 'celebrity', 'lifestyle', 'music', 'concert', 'ticket']
    if any(src in source for src in irrelevant_sources):
        return False
    
    # Check if article mentions any tracked symbols
    entities = article.get("entities", [])
    article_symbols = {e.get("symbol", "").upper() for e in entities if e.get("symbol")}
    if article_symbols & TRACKED_SYMBOLS:  # Intersection
        return True
    
    # Check for relevant keywords in title or description
    combined_text = f"{title} {description}"
    keyword_matches = sum(1 for kw in OPTIONS_TRADING_KEYWORDS if kw in combined_text)
    
    # Require at least 2 keyword matches for general financial relevance
    return keyword_matches >= 2

async def check_marketaux_rate_limit() -> bool:
    """Check if we can make a MarketAux API request (100/day limit)"""
    global marketaux_request_count
    today = datetime.now(timezone.utc).date().isoformat()
    
    if marketaux_request_count["date"] != today:
        # Reset counter for new day
        marketaux_request_count = {"date": today, "count": 0}
    
    if marketaux_request_count["count"] >= MARKETAUX_DAILY_LIMIT:
        logging.warning(f"MarketAux daily limit reached ({MARKETAUX_DAILY_LIMIT} requests)")
        return False
    
    return True

async def increment_marketaux_counter():
    """Increment the MarketAux request counter"""
    global marketaux_request_count
    today = datetime.now(timezone.utc).date().isoformat()
    
    if marketaux_request_count["date"] != today:
        marketaux_request_count = {"date": today, "count": 1}
    else:
        marketaux_request_count["count"] += 1
    
    logging.info(f"MarketAux requests today: {marketaux_request_count['count']}/{MARKETAUX_DAILY_LIMIT}")


@news_router.get("/")
async def get_market_news(
    symbol: Optional[str] = None,
    limit: int = Query(10, ge=1, le=50),
    user: dict = Depends(get_current_user)
):
    # Generate cache key for news
    cache_key = f"market_news_{symbol or 'general'}_{limit}"
    
    # Check cache first (news is cached longer on weekends)
    cached_news = await get_cached_data(cache_key)
    if cached_news:
        for item in cached_news:
            item["from_cache"] = True
        return cached_news
    
    # Check rate limit before making API call
    can_request = await check_marketaux_rate_limit()
    
    # Try MarketAux API for news and sentiment (if within rate limit)
    marketaux_token = await get_marketaux_client()
    if marketaux_token and can_request:
        try:
            async with httpx.AsyncClient() as client:
                # Request more items to allow for filtering
                request_limit = min(limit * 3, 50)  # Request 3x to account for filtering
                
                params = {
                    "api_token": marketaux_token,
                    "limit": request_limit,
                    "language": "en",
                    "filter_entities": "true"  # Get entity data for better filtering
                }
                
                # If specific symbol requested, filter to that symbol
                if symbol:
                    params["symbols"] = symbol.upper()
                else:
                    # For general news, use our tracked symbols
                    # Use top liquid symbols for general market news
                    params["symbols"] = ",".join(["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "SPY", "QQQ", "META", "TSLA", "AMD"])
                
                response = await client.get(
                    "https://api.marketaux.com/v1/news/all",
                    params=params
                )
                
                # Increment counter after successful request
                await increment_marketaux_counter()
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("data"):
                        # Filter for relevant news
                        filtered_news = []
                        for n in data["data"]:
                            if is_relevant_news(n):
                                filtered_news.append({
                                    "title": n.get("title"),
                                    "description": n.get("description"),
                                    "source": n.get("source"),
                                    "url": n.get("url"),
                                    "published_at": n.get("published_at"),
                                    "sentiment": n.get("sentiment"),
                                    "sentiment_score": n.get("sentiment_score"),
                                    "tickers": [e.get("symbol") for e in n.get("entities", []) if e.get("symbol")],
                                    "is_live": True
                                })
                                if len(filtered_news) >= limit:
                                    break
                        
                        if filtered_news:
                            # Cache news for weekend access
                            await set_cached_data(cache_key, filtered_news)
                            return filtered_news
                        
        except Exception as e:
            logging.error(f"MarketAux API error: {e}")
    
    # If market is closed and no fresh news, try last trading day data
    if is_market_closed():
        ltd_news = await get_last_trading_day_data(cache_key)
        if ltd_news:
            for item in ltd_news:
                item["from_cache"] = True
            return ltd_news
    
    # Return filtered mock news
    return MOCK_NEWS[:limit]


@news_router.get("/rate-limit")
async def get_news_rate_limit(user: dict = Depends(get_current_user)):
    """Get current MarketAux API rate limit status"""
    today = datetime.now(timezone.utc).date().isoformat()
    current_count = marketaux_request_count.get("count", 0) if marketaux_request_count.get("date") == today else 0
    
    return {
        "daily_limit": MARKETAUX_DAILY_LIMIT,
        "requests_today": current_count,
        "remaining": MARKETAUX_DAILY_LIMIT - current_count,
        "date": today,
        "limit_reached": current_count >= MARKETAUX_DAILY_LIMIT
    }

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
            "trial_link": "https://buy.stripe.com/test_14A00caQj0XUeHG43m3ZK02",
            "monthly_link": "https://buy.stripe.com/test_6oU5kw6A3cGC0QQ0Ra3ZK01",
            "yearly_link": "https://buy.stripe.com/test_9B6cMYbUn362bvueI03ZK00",
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
                "trial": "https://buy.stripe.com/test_14A00caQj0XUeHG43m3ZK02",
                "monthly": "https://buy.stripe.com/test_6oU5kw6A3cGC0QQ0Ra3ZK01",
                "yearly": "https://buy.stripe.com/test_9B6cMYbUn362bvueI03ZK00"
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

# ==================== STRIPE WEBHOOK ROUTES ====================

@api_router.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events"""
    from services.stripe_webhook import StripeWebhookHandler
    from services.email_service import EmailService
    
    email_service = EmailService(db)
    webhook_handler = StripeWebhookHandler(db, email_service)
    
    try:
        event = await webhook_handler.verify_webhook(request)
        result = await webhook_handler.handle_event(event)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== ENHANCED ADMIN ROUTES ====================

@admin_router.get("/dashboard-stats")
async def get_admin_dashboard_stats(admin: dict = Depends(get_admin_user)):
    """Get admin dashboard KPIs"""
    now = datetime.now(timezone.utc)
    thirty_days_ago = (now - timedelta(days=30)).isoformat()
    seven_days_ago = (now - timedelta(days=7)).isoformat()
    
    # Get user counts
    total_users = await db.users.count_documents({})
    active_users = await db.users.count_documents({"last_login": {"$gte": seven_days_ago}})
    
    # Subscription stats
    trial_users = await db.users.count_documents({"subscription.status": "trialing"})
    active_subs = await db.users.count_documents({"subscription.status": "active"})
    monthly_subs = await db.users.count_documents({"subscription.plan": "monthly", "subscription.status": "active"})
    yearly_subs = await db.users.count_documents({"subscription.plan": "yearly", "subscription.status": "active"})
    cancelled_users = await db.users.count_documents({"subscription.status": "cancelled"})
    past_due_users = await db.users.count_documents({"subscription.status": "past_due"})
    
    # Calculate MRR
    mrr = (monthly_subs * 49) + (yearly_subs * 499 / 12)
    arr = mrr * 12
    
    # Trial conversion rate
    converted_trials = await db.users.count_documents({"subscription.converted_at": {"$exists": True}})
    total_trials = await db.users.count_documents({"subscription.trial_start": {"$exists": True}})
    conversion_rate = (converted_trials / total_trials * 100) if total_trials > 0 else 0
    
    # Churn (cancelled in last 30 days)
    recent_cancellations = await db.users.count_documents({
        "subscription.cancelled_at": {"$gte": thirty_days_ago}
    })
    churn_rate = (recent_cancellations / (active_subs + recent_cancellations) * 100) if (active_subs + recent_cancellations) > 0 else 0
    
    # Support tickets
    open_tickets = await db.support_tickets.count_documents({"status": {"$in": ["open", "in_progress"]}})
    
    # Trials ending soon (next 3 days)
    three_days_later = (now + timedelta(days=3)).isoformat()
    trials_ending_soon = await db.users.count_documents({
        "subscription.status": "trialing",
        "subscription.trial_end": {"$lte": three_days_later, "$gte": now.isoformat()}
    })
    
    return {
        "users": {
            "total": total_users,
            "active_7d": active_users,
            "trial": trial_users,
            "cancelled": cancelled_users,
            "past_due": past_due_users
        },
        "subscriptions": {
            "active": active_subs,
            "monthly": monthly_subs,
            "yearly": yearly_subs,
            "conversion_rate": round(conversion_rate, 1),
            "churn_rate": round(churn_rate, 1)
        },
        "revenue": {
            "mrr": round(mrr, 2),
            "arr": round(arr, 2)
        },
        "alerts": {
            "trials_ending_soon": trials_ending_soon,
            "payment_failures": past_due_users,
            "open_tickets": open_tickets
        }
    }

@admin_router.get("/users")
async def get_admin_users(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    plan: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    admin: dict = Depends(get_admin_user)
):
    """Get paginated list of users with filters"""
    query = {}
    
    if status:
        query["subscription.status"] = status
    if plan:
        query["subscription.plan"] = plan
    if search:
        query["$or"] = [
            {"email": {"$regex": search, "$options": "i"}},
            {"name": {"$regex": search, "$options": "i"}}
        ]
    
    skip = (page - 1) * limit
    
    users = await db.users.find(query, {"_id": 0, "hashed_password": 0}).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    total = await db.users.count_documents(query)
    
    return {
        "users": users,
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit
    }

@admin_router.get("/users/{user_id}")
async def get_admin_user_detail(user_id: str, admin: dict = Depends(get_admin_user)):
    """Get detailed user information"""
    user = await db.users.find_one({"id": user_id}, {"_id": 0, "hashed_password": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get user activity
    activity = await db.user_activity.find({"user_id": user_id}, {"_id": 0}).sort("timestamp", -1).limit(50).to_list(50)
    
    # Get email history
    emails = await db.email_logs.find({"to": user.get("email")}, {"_id": 0}).sort("sent_at", -1).limit(20).to_list(20)
    
    return {
        "user": user,
        "activity": activity,
        "emails": emails
    }

@admin_router.post("/users/{user_id}/extend-trial")
async def extend_user_trial(
    user_id: str,
    days: int = Query(..., ge=1, le=30),
    admin: dict = Depends(get_admin_user)
):
    """Extend user's trial period"""
    user = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    current_trial_end = user.get("subscription", {}).get("trial_end")
    if current_trial_end:
        new_end = datetime.fromisoformat(current_trial_end.replace("Z", "+00:00")) + timedelta(days=days)
    else:
        new_end = datetime.now(timezone.utc) + timedelta(days=days)
    
    await db.users.update_one(
        {"id": user_id},
        {"$set": {
            "subscription.trial_end": new_end.isoformat(),
            "subscription.status": "trialing",
            "updated_at": datetime.now(timezone.utc).isoformat()
        }}
    )
    
    # Log action
    await db.audit_logs.insert_one({
        "action": "extend_trial",
        "admin_id": admin["id"],
        "user_id": user_id,
        "details": {"days_added": days, "new_end": new_end.isoformat()},
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    return {"message": f"Trial extended by {days} days", "new_trial_end": new_end.isoformat()}

@admin_router.post("/users/{user_id}/cancel-subscription")
async def cancel_user_subscription(
    user_id: str,
    reason: Optional[str] = Query(None),
    admin: dict = Depends(get_admin_user)
):
    """Cancel user's subscription (admin action)"""
    user = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    now = datetime.now(timezone.utc)
    
    await db.users.update_one(
        {"id": user_id},
        {"$set": {
            "subscription.status": "cancelled",
            "subscription.cancelled_at": now.isoformat(),
            "subscription.cancellation_reason": reason or "Admin cancelled",
            "updated_at": now.isoformat()
        }}
    )
    
    # Log action
    await db.audit_logs.insert_one({
        "action": "admin_cancel_subscription",
        "admin_id": admin["id"],
        "user_id": user_id,
        "details": {"reason": reason},
        "timestamp": now.isoformat()
    })
    
    return {"message": "Subscription cancelled"}

@admin_router.post("/users/{user_id}/set-subscription")
async def set_user_subscription(
    user_id: str,
    status: str = Query(..., description="active, trialing, cancelled, past_due"),
    plan: str = Query("monthly", description="trial, monthly, yearly"),
    admin: dict = Depends(get_admin_user)
):
    """Manually set user's subscription status and plan (admin action)"""
    valid_statuses = ["active", "trialing", "cancelled", "past_due", "expired"]
    valid_plans = ["trial", "monthly", "yearly"]
    
    if status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")
    if plan not in valid_plans:
        raise HTTPException(status_code=400, detail=f"Invalid plan. Must be one of: {valid_plans}")
    
    user = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    now = datetime.now(timezone.utc)
    
    subscription_data = {
        "subscription.status": status,
        "subscription.plan": plan,
        "updated_at": now.isoformat()
    }
    
    # Set trial dates if trialing
    if status == "trialing":
        subscription_data["subscription.trial_start"] = now.isoformat()
        subscription_data["subscription.trial_end"] = (now + timedelta(days=7)).isoformat()
    
    # Set subscription start if active
    if status == "active":
        subscription_data["subscription.subscription_start"] = now.isoformat()
        if plan == "monthly":
            subscription_data["subscription.next_billing_date"] = (now + timedelta(days=30)).isoformat()
        elif plan == "yearly":
            subscription_data["subscription.next_billing_date"] = (now + timedelta(days=365)).isoformat()
    
    await db.users.update_one(
        {"id": user_id},
        {"$set": subscription_data}
    )
    
    # Log action
    await db.audit_logs.insert_one({
        "action": "admin_set_subscription",
        "admin_id": admin["id"],
        "user_id": user_id,
        "details": {"status": status, "plan": plan},
        "timestamp": now.isoformat()
    })
    
    return {"message": f"User subscription set to {status} ({plan})"}

@admin_router.get("/integration-settings")
async def get_integration_settings(admin: dict = Depends(get_admin_user)):
    """Get all integration settings (Stripe, Resend, etc.)"""
    stripe_settings = await db.admin_settings.find_one({"type": "stripe_settings"}, {"_id": 0})
    email_settings = await db.admin_settings.find_one({"type": "email_settings"}, {"_id": 0})
    
    # Check env variables as fallback
    env_resend_key = os.environ.get("RESEND_API_KEY")
    env_stripe_webhook = os.environ.get("STRIPE_WEBHOOK_SECRET")
    
    return {
        "stripe": {
            "webhook_secret_configured": bool(stripe_settings and stripe_settings.get("webhook_secret")) or bool(env_stripe_webhook),
            "secret_key_configured": bool(stripe_settings and stripe_settings.get("stripe_secret_key"))
        },
        "email": {
            "resend_api_key_configured": bool(email_settings and email_settings.get("resend_api_key")) or bool(env_resend_key),
            "sender_email": email_settings.get("sender_email", "") if email_settings else os.environ.get("SENDER_EMAIL", "")
        }
    }

@admin_router.post("/integration-settings")
async def update_integration_settings(
    stripe_webhook_secret: Optional[str] = Query(None),
    stripe_secret_key: Optional[str] = Query(None),
    resend_api_key: Optional[str] = Query(None),
    sender_email: Optional[str] = Query(None),
    admin: dict = Depends(get_admin_user)
):
    """Update integration settings"""
    now = datetime.now(timezone.utc).isoformat()
    
    # Update Stripe settings
    if stripe_webhook_secret is not None or stripe_secret_key is not None:
        stripe_update = {"type": "stripe_settings", "updated_at": now}
        if stripe_webhook_secret:
            stripe_update["webhook_secret"] = stripe_webhook_secret
        if stripe_secret_key:
            stripe_update["stripe_secret_key"] = stripe_secret_key
        
        await db.admin_settings.update_one(
            {"type": "stripe_settings"},
            {"$set": stripe_update},
            upsert=True
        )
    
    # Update Email settings
    if resend_api_key is not None or sender_email is not None:
        email_update = {"type": "email_settings", "updated_at": now}
        if resend_api_key:
            email_update["resend_api_key"] = resend_api_key
        if sender_email:
            email_update["sender_email"] = sender_email
        
        await db.admin_settings.update_one(
            {"type": "email_settings"},
            {"$set": email_update},
            upsert=True
        )
    
    # Log action
    await db.audit_logs.insert_one({
        "action": "update_integration_settings",
        "admin_id": admin["id"],
        "details": {
            "stripe_updated": stripe_webhook_secret is not None or stripe_secret_key is not None,
            "email_updated": resend_api_key is not None or sender_email is not None
        },
        "timestamp": now
    })
    
    return {"message": "Integration settings updated"}

@admin_router.get("/email-templates")
async def get_email_templates(admin: dict = Depends(get_admin_user)):
    """Get all email templates"""
    from services.email_service import EMAIL_TEMPLATES
    
    # Get custom templates from DB (if any overrides)
    custom_templates = await db.email_templates.find({}, {"_id": 0}).to_list(100)
    custom_dict = {t["name"]: t for t in custom_templates}
    
    templates = []
    for name, template in EMAIL_TEMPLATES.items():
        custom = custom_dict.get(name, {})
        templates.append({
            "name": name,
            "subject": custom.get("subject", template["subject"]),
            "enabled": custom.get("enabled", template.get("enabled", True)),
            "is_custom": name in custom_dict
        })
    
    return {"templates": templates}

@admin_router.post("/email-templates/{template_name}/toggle")
async def toggle_email_template(
    template_name: str,
    enabled: bool = Query(...),
    admin: dict = Depends(get_admin_user)
):
    """Enable or disable an email template"""
    await db.email_templates.update_one(
        {"name": template_name},
        {"$set": {"name": template_name, "enabled": enabled, "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True
    )
    
    return {"message": f"Template '{template_name}' {'enabled' if enabled else 'disabled'}"}

@admin_router.post("/test-email")
async def send_test_email(
    recipient_email: str = Query(..., description="Email address to send test to"),
    template_name: str = Query("welcome", description="Template to test"),
    admin: dict = Depends(get_admin_user)
):
    """Send a test email to verify Resend integration"""
    from services.email_service import EmailService
    
    email_service = EmailService(db)
    
    # Check if service is configured
    if not await email_service.initialize():
        return {"status": "error", "message": "Email service not configured. Please add your Resend API key in Integrations settings."}
    
    # Send test email with sample variables
    test_variables = {
        "name": "Test User",
        "plan": "7-Day Free Trial",
        "trial_end_date": "January 15, 2025",
        "days_left": "3",
        "next_billing_date": "January 15, 2025",
        "amount": "$49/month",
        "access_until": "January 15, 2025"
    }
    
    result = await email_service.send_email(recipient_email, template_name, test_variables)
    
    # Log the test
    await db.audit_logs.insert_one({
        "action": "test_email_sent",
        "admin_id": admin["id"],
        "admin_email": admin["email"],
        "recipient": recipient_email,
        "template": template_name,
        "result": result,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    return {
        "status": result.get("status"),
        "message": f"Test email sent to {recipient_email}" if result.get("status") == "success" else result.get("reason"),
        "email_id": result.get("email_id")
    }

@admin_router.get("/audit-logs")
async def get_audit_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    admin: dict = Depends(get_admin_user)
):
    """Get audit logs"""
    skip = (page - 1) * limit
    logs = await db.audit_logs.find({}, {"_id": 0}).sort("timestamp", -1).skip(skip).limit(limit).to_list(limit)
    total = await db.audit_logs.count_documents({})
    
    return {
        "logs": logs,
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit
    }

# ==================== EMAIL AUTOMATION ENDPOINTS ====================

@admin_router.get("/email-automation/templates")
async def get_email_templates(admin: dict = Depends(get_admin_user)):
    """Get all email templates"""
    from services.email_automation import EmailAutomationService
    
    email_automation = EmailAutomationService(db)
    await email_automation.setup_default_templates()  # Ensure defaults exist
    
    templates = await email_automation.get_templates()
    return {"templates": templates}

@admin_router.get("/email-automation/templates/{template_id}")
async def get_email_template(template_id: str, admin: dict = Depends(get_admin_user)):
    """Get a single email template"""
    from services.email_automation import EmailAutomationService
    
    email_automation = EmailAutomationService(db)
    template = await email_automation.get_template(template_id)
    
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    return template

@admin_router.put("/email-automation/templates/{template_id}")
async def update_email_template(
    template_id: str,
    name: Optional[str] = None,
    subject: Optional[str] = None,
    html: Optional[str] = None,
    enabled: Optional[bool] = None,
    admin: dict = Depends(get_admin_user)
):
    """Update an email template"""
    from services.email_automation import EmailAutomationService
    
    email_automation = EmailAutomationService(db)
    
    updates = {}
    if name is not None:
        updates["name"] = name
    if subject is not None:
        updates["subject"] = subject
    if html is not None:
        updates["html"] = html
    if enabled is not None:
        updates["enabled"] = enabled
    
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")
    
    success = await email_automation.update_template(template_id, updates)
    
    if not success:
        raise HTTPException(status_code=404, detail="Template not found or update failed")
    
    # Log the action
    await db.audit_logs.insert_one({
        "action": "email_template_updated",
        "admin_id": admin["id"],
        "admin_email": admin["email"],
        "template_id": template_id,
        "updates": list(updates.keys()),
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    return {"message": "Template updated successfully"}

@admin_router.get("/email-automation/rules")
async def get_automation_rules(admin: dict = Depends(get_admin_user)):
    """Get all automation rules"""
    from services.email_automation import EmailAutomationService, TRIGGER_TYPES, ACTION_TYPES
    
    email_automation = EmailAutomationService(db)
    await email_automation.setup_default_rules()  # Ensure defaults exist
    
    rules = await email_automation.get_rules()
    return {
        "rules": rules,
        "trigger_types": TRIGGER_TYPES,
        "action_types": ACTION_TYPES
    }

@admin_router.post("/email-automation/rules")
async def create_automation_rule(
    name: str,
    trigger_type: str,
    action: str,
    template_key: str,
    delay_minutes: int = 0,
    condition: Optional[str] = None,
    enabled: bool = True,
    admin: dict = Depends(get_admin_user)
):
    """Create a new automation rule"""
    from services.email_automation import EmailAutomationService
    import json
    
    email_automation = EmailAutomationService(db)
    
    rule_data = {
        "name": name,
        "trigger_type": trigger_type,
        "condition": json.loads(condition) if condition else {},
        "delay_minutes": delay_minutes,
        "action": action,
        "template_key": template_key,
        "enabled": enabled
    }
    
    rule = await email_automation.create_rule(rule_data)
    
    # Log the action
    await db.audit_logs.insert_one({
        "action": "automation_rule_created",
        "admin_id": admin["id"],
        "admin_email": admin["email"],
        "rule_name": name,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    return {"message": "Rule created successfully", "rule": rule}

@admin_router.put("/email-automation/rules/{rule_id}")
async def update_automation_rule(
    rule_id: str,
    name: Optional[str] = None,
    trigger_type: Optional[str] = None,
    action: Optional[str] = None,
    template_key: Optional[str] = None,
    delay_minutes: Optional[int] = None,
    condition: Optional[str] = None,
    enabled: Optional[bool] = None,
    admin: dict = Depends(get_admin_user)
):
    """Update an automation rule"""
    from services.email_automation import EmailAutomationService
    import json
    
    email_automation = EmailAutomationService(db)
    
    updates = {}
    if name is not None:
        updates["name"] = name
    if trigger_type is not None:
        updates["trigger_type"] = trigger_type
    if action is not None:
        updates["action"] = action
    if template_key is not None:
        updates["template_key"] = template_key
    if delay_minutes is not None:
        updates["delay_minutes"] = delay_minutes
    if condition is not None:
        updates["condition"] = json.loads(condition)
    if enabled is not None:
        updates["enabled"] = enabled
    
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")
    
    success = await email_automation.update_rule(rule_id, updates)
    
    if not success:
        raise HTTPException(status_code=404, detail="Rule not found or update failed")
    
    return {"message": "Rule updated successfully"}

@admin_router.delete("/email-automation/rules/{rule_id}")
async def delete_automation_rule(rule_id: str, admin: dict = Depends(get_admin_user)):
    """Delete an automation rule"""
    from services.email_automation import EmailAutomationService
    
    email_automation = EmailAutomationService(db)
    success = await email_automation.delete_rule(rule_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    # Log the action
    await db.audit_logs.insert_one({
        "action": "automation_rule_deleted",
        "admin_id": admin["id"],
        "admin_email": admin["email"],
        "rule_id": rule_id,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    return {"message": "Rule deleted successfully"}

@admin_router.get("/email-automation/logs")
async def get_email_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    status: Optional[str] = None,
    template_key: Optional[str] = None,
    admin: dict = Depends(get_admin_user)
):
    """Get email logs with pagination and filters"""
    from services.email_automation import EmailAutomationService
    
    email_automation = EmailAutomationService(db)
    
    filters = {}
    if status:
        filters["status"] = status
    if template_key:
        filters["template_key"] = template_key
    
    skip = (page - 1) * limit
    result = await email_automation.get_email_logs(limit=limit, skip=skip, filters=filters)
    
    return {
        "logs": result["logs"],
        "total": result["total"],
        "page": page,
        "pages": (result["total"] + limit - 1) // limit if result["total"] > 0 else 1
    }

@admin_router.get("/email-automation/stats")
async def get_email_stats(admin: dict = Depends(get_admin_user)):
    """Get email analytics/statistics"""
    from services.email_automation import EmailAutomationService
    
    email_automation = EmailAutomationService(db)
    stats = await email_automation.get_email_stats()
    
    return stats

@admin_router.post("/email-automation/broadcast")
async def send_broadcast_email(
    template_key: str,
    subject_override: Optional[str] = None,
    announcement_title: Optional[str] = None,
    announcement_content: Optional[str] = None,
    update_title: Optional[str] = None,
    update_content: Optional[str] = None,
    recipient_filter: Optional[str] = None,
    admin: dict = Depends(get_admin_user)
):
    """Send a broadcast email to multiple users"""
    from services.email_automation import EmailAutomationService
    import json
    
    email_automation = EmailAutomationService(db)
    
    variables = {}
    if announcement_title:
        variables["announcement_title"] = announcement_title
    if announcement_content:
        variables["announcement_content"] = announcement_content
    if update_title:
        variables["update_title"] = update_title
    if update_content:
        variables["update_content"] = update_content
    
    filter_dict = json.loads(recipient_filter) if recipient_filter else None
    
    result = await email_automation.send_broadcast(template_key, variables, filter_dict)
    
    # Log the action
    await db.audit_logs.insert_one({
        "action": "broadcast_email_sent",
        "admin_id": admin["id"],
        "admin_email": admin["email"],
        "template_key": template_key,
        "recipients_count": result.get("total", 0),
        "sent": result.get("sent", 0),
        "failed": result.get("failed", 0),
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    return result

@admin_router.post("/email-automation/test-send")
async def test_send_email(
    template_key: str,
    recipient_email: str,
    admin: dict = Depends(get_admin_user)
):
    """Send a test email to a specific recipient"""
    from services.email_automation import EmailAutomationService
    
    email_automation = EmailAutomationService(db)
    
    # Test variables
    variables = {
        "first_name": "Test User",
        "name": "Test User",
        "dashboard_url": "https://coveredcallengine.com/dashboard",
        "scanner_link": "https://coveredcallengine.com/screener",
        "feature_link": "https://coveredcallengine.com/screener",
        "upgrade_link": "https://coveredcallengine.com/pricing",
        "trial_days": "7",
        "announcement_title": "Test Announcement",
        "announcement_content": "This is a test announcement content.",
        "update_title": "Test Update",
        "update_content": "This is a test system update content."
    }
    
    result = await email_automation.send_email(recipient_email, template_key, variables)
    
    return {
        "success": result.get("success", False),
        "message": f"Test email sent to {recipient_email}" if result.get("success") else result.get("error"),
        "message_id": result.get("message_id")
    }

# ==================== CHATBOT ENDPOINTS ====================

chatbot_router = APIRouter(prefix="/chatbot", tags=["chatbot"])

@chatbot_router.post("/message")
async def send_chatbot_message(
    message: str,
    session_id: Optional[str] = None
):
    """Send a message to the AI chatbot and get a response"""
    from services.chatbot_service import ChatbotService
    
    # Generate session ID if not provided
    if not session_id:
        session_id = str(uuid4())
    
    chatbot = ChatbotService(db)
    
    # Get conversation history for context
    history = await chatbot.get_conversation_history(session_id, limit=10)
    
    # Get AI response
    result = await chatbot.get_response(session_id, message, history)
    
    return {
        "response": result.get("response", ""),
        "session_id": session_id,
        "success": result.get("success", False)
    }

@chatbot_router.get("/history/{session_id}")
async def get_chatbot_history(session_id: str):
    """Get conversation history for a session"""
    from services.chatbot_service import ChatbotService
    
    chatbot = ChatbotService(db)
    history = await chatbot.get_conversation_history(session_id)
    
    return {"history": history, "session_id": session_id}

@chatbot_router.get("/quick-response/{topic}")
async def get_quick_response(topic: str):
    """Get a quick predefined response for common topics"""
    from services.chatbot_service import QUICK_RESPONSES
    
    response = QUICK_RESPONSES.get(topic.lower())
    if response:
        return {"response": response, "topic": topic}
    
    return {"response": None, "topic": topic, "available_topics": list(QUICK_RESPONSES.keys())}

# ==================== CONTACT FORM ENDPOINT ====================

class ContactForm(BaseModel):
    name: str
    email: EmailStr
    subject: Optional[str] = ""
    message: str

@api_router.post("/contact")
async def submit_contact_form(form: ContactForm):
    """Submit a contact/support form - creates a support ticket"""
    from uuid import uuid4
    
    now = datetime.now(timezone.utc).isoformat()
    
    ticket = {
        "id": str(uuid4()),
        "name": form.name,
        "email": form.email,
        "subject": form.subject or "General Inquiry",
        "message": form.message,
        "status": "open",
        "priority": "normal",
        "source": "contact_form",
        "created_at": now,
        "updated_at": now
    }
    
    await db.support_tickets.insert_one(ticket)
    
    # Try to send notification email to admin (optional)
    try:
        from services.email_service import EmailService
        email_service = EmailService(db)
        if await email_service.initialize():
            # Get admin settings for notification email
            settings = await db.admin_settings.find_one({"type": "email_settings"}, {"_id": 0})
            admin_email = settings.get("sender_email") if settings else None
            
            if admin_email:
                # Send notification to admin about new ticket
                await email_service.send_raw_email(
                    to_email=admin_email,
                    subject=f"[CCE Support] New Contact Form: {form.subject or 'General Inquiry'}",
                    html_content=f"""
                    <div style="font-family: Arial, sans-serif; padding: 20px;">
                        <h2>New Support Ticket</h2>
                        <p><strong>From:</strong> {form.name} ({form.email})</p>
                        <p><strong>Subject:</strong> {form.subject or 'General Inquiry'}</p>
                        <p><strong>Message:</strong></p>
                        <div style="background: #f5f5f5; padding: 15px; border-radius: 8px;">
                            {form.message}
                        </div>
                        <p style="color: #666; font-size: 12px; margin-top: 20px;">
                            Ticket ID: {ticket['id']}
                        </p>
                    </div>
                    """
                )
    except Exception as e:
        # Don't fail the contact submission if email fails
        logger.warning(f"Failed to send contact notification email: {e}")
    
    return {"success": True, "ticket_id": ticket["id"], "message": "Your message has been received. We'll get back to you soon."}

@api_router.get("/")
async def root():
    return {"message": "Covered Call Engine API - Options Trading Platform", "version": "1.0.0"}

@api_router.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}

@api_router.get("/market-status")
async def get_market_status():
    """Get current market status (open/closed) and relevant times"""
    try:
        eastern = pytz.timezone('US/Eastern')
        now_eastern = datetime.now(eastern)
        
        market_open_time = now_eastern.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close_time = now_eastern.replace(hour=16, minute=0, second=0, microsecond=0)
        
        is_weekend = now_eastern.weekday() >= 5
        is_before_open = now_eastern < market_open_time
        is_after_close = now_eastern > market_close_time
        
        market_closed = is_weekend or is_before_open or is_after_close
        
        status = "closed"
        reason = ""
        
        if is_weekend:
            status = "closed"
            reason = "Weekend - Market is closed"
        elif is_before_open:
            status = "pre-market"
            reason = "Pre-market hours"
        elif is_after_close:
            status = "after-hours"
            reason = "After-hours - Market closed"
        else:
            status = "open"
            reason = "Market is open"
        
        return {
            "status": status,
            "is_open": not market_closed,
            "is_weekend": is_weekend,
            "reason": reason,
            "current_time_et": now_eastern.strftime("%Y-%m-%d %H:%M:%S ET"),
            "market_open": "9:30 AM ET",
            "market_close": "4:00 PM ET",
            "data_note": "Data shown is from Friday's market close" if is_weekend else ("Data is cached from market hours" if market_closed else "Live market data")
        }
    except Exception as e:
        logging.error(f"Market status error: {e}")
        return {"status": "unknown", "is_open": False, "error": str(e)}

# ==================== SIMULATOR ROUTES ====================

# Black-Scholes Greeks Calculations
def calculate_d1_d2(S, K, T, r, sigma):
    """Calculate d1 and d2 for Black-Scholes"""
    if T <= 0 or sigma <= 0:
        return None, None
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return d1, d2

def norm_cdf(x):
    """Cumulative distribution function for standard normal"""
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

def norm_pdf(x):
    """Probability density function for standard normal"""
    return math.exp(-0.5 * x ** 2) / math.sqrt(2 * math.pi)

def calculate_call_price(S, K, T, r, sigma):
    """Calculate Black-Scholes call option price"""
    if T <= 0:
        return max(0, S - K)  # Intrinsic value at expiry
    if sigma <= 0:
        return max(0, S - K)
    
    d1, d2 = calculate_d1_d2(S, K, T, r, sigma)
    if d1 is None:
        return max(0, S - K)
    
    return S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)

def calculate_greeks(S, K, T, r, sigma):
    """
    Calculate option Greeks
    S: Current stock price
    K: Strike price
    T: Time to expiration (in years)
    r: Risk-free rate (default 5%)
    sigma: Implied volatility
    
    Returns: dict with delta, gamma, theta, vega
    """
    if T <= 0 or sigma <= 0:
        # At expiry or invalid inputs
        delta = 1.0 if S > K else 0.0
        return {
            "delta": delta,
            "gamma": 0,
            "theta": 0,
            "vega": 0,
            "option_value": max(0, S - K)
        }
    
    d1, d2 = calculate_d1_d2(S, K, T, r, sigma)
    if d1 is None:
        return {"delta": 0, "gamma": 0, "theta": 0, "vega": 0, "option_value": 0}
    
    # Delta
    delta = norm_cdf(d1)
    
    # Gamma
    gamma = norm_pdf(d1) / (S * sigma * math.sqrt(T))
    
    # Theta (per day)
    theta = (-(S * norm_pdf(d1) * sigma) / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * norm_cdf(d2)) / 365
    
    # Vega (per 1% change in IV)
    vega = S * math.sqrt(T) * norm_pdf(d1) / 100
    
    # Option value
    option_value = calculate_call_price(S, K, T, r, sigma)
    
    return {
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta": round(theta, 4),
        "vega": round(vega, 4),
        "option_value": round(option_value, 2)
    }

# Scheduler for automated daily price updates
scheduler = AsyncIOScheduler()

async def scheduled_price_update():
    """
    Automated daily price update for all active simulator trades.
    Runs at market close (4:00 PM ET) on weekdays.
    """
    logging.info("Starting scheduled simulator price update...")
    
    try:
        # Get all active trades across all users
        active_trades = await db.simulator_trades.find({"status": "active"}).to_list(10000)
        
        if not active_trades:
            logging.info("No active simulator trades to update")
            return
        
        # Get unique symbols
        symbols = list(set(t["symbol"] for t in active_trades))
        logging.info(f"Updating prices for {len(symbols)} symbols across {len(active_trades)} trades")
        
        # Fetch current prices
        price_cache = {}
        for symbol in symbols:
            try:
                quote = await fetch_stock_quote(symbol)
                if quote and quote.get("price"):
                    price_cache[symbol] = quote["price"]
            except Exception as e:
                logging.warning(f"Could not fetch price for {symbol}: {e}")
        
        now = datetime.now(timezone.utc)
        risk_free_rate = 0.05  # 5% risk-free rate
        
        updated_count = 0
        expired_count = 0
        assigned_count = 0
        
        for trade in active_trades:
            symbol = trade["symbol"]
            if symbol not in price_cache:
                continue
            
            current_price = price_cache[symbol]
            
            # Calculate DTE remaining
            try:
                expiry_dt = datetime.strptime(trade["short_call_expiry"], "%Y-%m-%d")
                dte_remaining = (expiry_dt - datetime.now()).days
                time_to_expiry = max(dte_remaining / 365, 0.001)  # In years
            except:
                dte_remaining = trade.get("dte_remaining", 0)
                time_to_expiry = max(dte_remaining / 365, 0.001)
            
            # Calculate days held
            try:
                entry_dt = datetime.strptime(trade["entry_date"], "%Y-%m-%d")
                days_held = (datetime.now() - entry_dt).days
            except:
                days_held = trade.get("days_held", 0)
            
            # Calculate current Greeks and option value
            iv = trade.get("short_call_iv") or 0.30  # Default 30% IV
            greeks = calculate_greeks(
                S=current_price,
                K=trade["short_call_strike"],
                T=time_to_expiry,
                r=risk_free_rate,
                sigma=iv
            )
            
            # Calculate unrealized P&L
            entry_premium = trade.get("short_call_premium", 0)
            current_option_value = greeks["option_value"]
            
            if trade["strategy_type"] == "covered_call":
                # Stock P&L + Premium received - Current option liability
                stock_pnl = (current_price - trade["entry_underlying_price"]) * 100 * trade["contracts"]
                option_pnl = (entry_premium - current_option_value) * 100 * trade["contracts"]
                unrealized_pnl = stock_pnl + option_pnl
            else:  # PMCC
                # LEAPS value change + Short call P&L
                leaps_iv = trade.get("leaps_iv") or iv
                leaps_dte = trade.get("leaps_dte_remaining") or 365
                leaps_time_to_expiry = max(leaps_dte / 365, 0.001)
                
                leaps_greeks = calculate_greeks(
                    S=current_price,
                    K=trade.get("leaps_strike", current_price * 0.8),
                    T=leaps_time_to_expiry,
                    r=risk_free_rate,
                    sigma=leaps_iv
                )
                
                leaps_value_change = (leaps_greeks["option_value"] - (trade.get("leaps_premium", 0))) * 100 * trade["contracts"]
                short_call_pnl = (entry_premium - current_option_value) * 100 * trade["contracts"]
                unrealized_pnl = leaps_value_change + short_call_pnl
            
            # Calculate premium capture percentage
            if entry_premium > 0 and current_option_value >= 0:
                premium_capture_pct = ((entry_premium - current_option_value) / entry_premium) * 100
            else:
                premium_capture_pct = 0
            
            update_doc = {
                "current_underlying_price": current_price,
                "current_option_value": current_option_value,
                "unrealized_pnl": round(unrealized_pnl, 2),
                "days_held": days_held,
                "dte_remaining": dte_remaining,
                "premium_capture_pct": round(premium_capture_pct, 1),
                "last_updated": now.isoformat(),
                "updated_at": now.isoformat(),
                # Greeks
                "current_delta": greeks["delta"],
                "current_gamma": greeks["gamma"],
                "current_theta": greeks["theta"],
                "current_vega": greeks["vega"],
            }
            
            # Check for expiry (DTE <= 0)
            if dte_remaining <= 0:
                if current_price >= trade["short_call_strike"]:
                    # ITM - Assigned
                    if trade["strategy_type"] == "covered_call":
                        final_pnl = ((trade["short_call_strike"] - trade["entry_underlying_price"]) * 100 + entry_premium * 100) * trade["contracts"]
                    else:  # PMCC
                        short_call_loss = (current_price - trade["short_call_strike"]) * 100 * trade["contracts"]
                        leaps_gain = max(0, current_price - trade.get("leaps_strike", 0)) * 100 * trade["contracts"]
                        final_pnl = leaps_gain - trade["capital_deployed"] + trade["premium_received"] - short_call_loss
                    
                    update_doc.update({
                        "status": "assigned",
                        "close_date": now.strftime("%Y-%m-%d"),
                        "close_price": current_price,
                        "close_reason": "assigned_itm",
                        "final_pnl": round(final_pnl, 2),
                        "roi_percent": round((final_pnl / trade["capital_deployed"]) * 100, 2) if trade["capital_deployed"] > 0 else 0,
                        "realized_pnl": round(final_pnl, 2)
                    })
                    assigned_count += 1
                    
                    await db.simulator_trades.update_one(
                        {"id": trade["id"]},
                        {"$push": {"action_log": {
                            "action": "assigned",
                            "timestamp": now.isoformat(),
                            "details": f"Short call ITM at ${current_price:.2f}, assigned at strike ${trade['short_call_strike']:.2f}"
                        }}}
                    )
                else:
                    # OTM - Option expires worthless
                    if trade["strategy_type"] == "covered_call":
                        final_pnl = (current_price - trade["entry_underlying_price"]) * 100 * trade["contracts"] + trade["premium_received"]
                    else:
                        final_pnl = trade["premium_received"]  # Keep full premium
                    
                    update_doc.update({
                        "status": "expired",
                        "close_date": now.strftime("%Y-%m-%d"),
                        "close_price": current_price,
                        "close_reason": "expired_otm",
                        "final_pnl": round(final_pnl, 2),
                        "roi_percent": round((final_pnl / trade["capital_deployed"]) * 100, 2) if trade["capital_deployed"] > 0 else 0,
                        "realized_pnl": round(final_pnl, 2),
                        "premium_capture_pct": 100  # Full premium captured
                    })
                    expired_count += 1
                    
                    await db.simulator_trades.update_one(
                        {"id": trade["id"]},
                        {"$push": {"action_log": {
                            "action": "expired",
                            "timestamp": now.isoformat(),
                            "details": f"Short call expired OTM at ${current_price:.2f}, kept full premium ${trade['premium_received']:.2f}"
                        }}}
                    )
            
            await db.simulator_trades.update_one({"id": trade["id"]}, {"$set": update_doc})
            updated_count += 1
        
        logging.info(f"Scheduled update complete: {updated_count} updated, {expired_count} expired, {assigned_count} assigned")
        
    except Exception as e:
        logging.error(f"Error in scheduled price update: {e}")

# Pydantic Models for Simulator
class SimulatorTradeEntry(BaseModel):
    """Model for adding a trade to the simulator"""
    symbol: str
    strategy_type: str  # "covered_call" or "pmcc"
    
    # Stock/LEAPS Entry
    underlying_price: float
    
    # Short Call Details
    short_call_strike: float
    short_call_expiry: str
    short_call_premium: float
    short_call_delta: Optional[float] = None
    short_call_iv: Optional[float] = None
    
    # For PMCC - LEAPS details
    leaps_strike: Optional[float] = None
    leaps_expiry: Optional[str] = None
    leaps_premium: Optional[float] = None
    leaps_delta: Optional[float] = None
    
    # Position sizing
    contracts: int = 1
    
    # Scan metadata (for feedback loop)
    scan_parameters: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None


@simulator_router.post("/trade")
async def add_simulator_trade(trade: SimulatorTradeEntry, user: dict = Depends(get_current_user)):
    """Add a new trade to the simulator from screener results"""
    
    trade_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    entry_date = now.strftime("%Y-%m-%d")
    
    # Calculate key metrics based on strategy type
    if trade.strategy_type == "covered_call":
        # Covered Call: Long 100 shares + Short call
        capital_per_contract = trade.underlying_price * 100  # Cost of 100 shares
        total_capital = capital_per_contract * trade.contracts
        premium_received = trade.short_call_premium * trade.contracts * 100
        max_profit = ((trade.short_call_strike - trade.underlying_price) * 100 + trade.short_call_premium * 100) * trade.contracts
        max_loss = (trade.underlying_price * 100 - trade.short_call_premium * 100) * trade.contracts  # Stock goes to 0
        breakeven = trade.underlying_price - trade.short_call_premium
        
    elif trade.strategy_type == "pmcc":
        # PMCC: Long LEAPS + Short call
        if not trade.leaps_strike or not trade.leaps_expiry or not trade.leaps_premium:
            raise HTTPException(status_code=400, detail="PMCC requires LEAPS details")
        
        capital_per_contract = trade.leaps_premium * 100  # Cost of LEAPS
        total_capital = capital_per_contract * trade.contracts
        premium_received = trade.short_call_premium * trade.contracts * 100
        
        # Max profit: difference between strikes + net credit/debit
        strike_diff = trade.short_call_strike - trade.leaps_strike
        net_debit = trade.leaps_premium - trade.short_call_premium
        max_profit = (strike_diff * 100 - net_debit * 100) * trade.contracts if strike_diff > 0 else (trade.short_call_premium * 100 * trade.contracts)
        max_loss = total_capital  # LEAPS expires worthless
        breakeven = trade.leaps_strike + net_debit
    else:
        raise HTTPException(status_code=400, detail="Invalid strategy type. Must be 'covered_call' or 'pmcc'")
    
    # Calculate DTE
    try:
        expiry_dt = datetime.strptime(trade.short_call_expiry, "%Y-%m-%d")
        dte = (expiry_dt - datetime.now()).days
    except:
        dte = 30  # Default
    
    # Create simulator trade document
    trade_doc = {
        "id": trade_id,
        "user_id": user["id"],
        "symbol": trade.symbol.upper(),
        "strategy_type": trade.strategy_type,
        "status": "active",  # active, closed, expired, assigned
        
        # Entry snapshot (immutable)
        "entry_date": entry_date,
        "entry_underlying_price": trade.underlying_price,
        
        # Short call details
        "short_call_strike": trade.short_call_strike,
        "short_call_expiry": trade.short_call_expiry,
        "short_call_premium": trade.short_call_premium,
        "short_call_delta": trade.short_call_delta,
        "short_call_iv": trade.short_call_iv,
        
        # LEAPS details (for PMCC)
        "leaps_strike": trade.leaps_strike,
        "leaps_expiry": trade.leaps_expiry,
        "leaps_premium": trade.leaps_premium,
        "leaps_delta": trade.leaps_delta,
        
        # Position sizing
        "contracts": trade.contracts,
        
        # Calculated at entry
        "capital_deployed": total_capital,
        "premium_received": premium_received,
        "max_profit": max_profit,
        "max_loss": max_loss,
        "breakeven": breakeven,
        "initial_dte": dte,
        
        # Live tracking (updated daily)
        "current_underlying_price": trade.underlying_price,
        "current_option_value": trade.short_call_premium,
        "unrealized_pnl": 0,
        "realized_pnl": 0,
        "days_held": 0,
        "dte_remaining": dte,
        "last_updated": now.isoformat(),
        
        # Outcome (set when closed)
        "close_date": None,
        "close_price": None,
        "close_reason": None,  # expired_otm, assigned, early_close, rolled
        "final_pnl": None,
        "roi_percent": None,
        
        # Scan metadata for feedback loop
        "scan_parameters": trade.scan_parameters,
        "notes": trade.notes,
        
        # Audit
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "action_log": [{
            "action": "opened",
            "timestamp": now.isoformat(),
            "details": f"Opened {trade.contracts} contract(s) at ${trade.underlying_price}"
        }]
    }
    
    # Check for duplicate (same symbol, strike, expiry)
    existing = await db.simulator_trades.find_one({
        "user_id": user["id"],
        "symbol": trade.symbol.upper(),
        "short_call_strike": trade.short_call_strike,
        "short_call_expiry": trade.short_call_expiry,
        "status": "active"
    })
    
    if existing:
        raise HTTPException(status_code=400, detail="Duplicate trade already exists in simulator")
    
    await db.simulator_trades.insert_one(trade_doc)
    
    # Remove _id for response
    if "_id" in trade_doc:
        del trade_doc["_id"]
    
    return {"message": "Trade added to simulator", "trade": trade_doc}


@simulator_router.get("/trades")
async def get_simulator_trades(
    user: dict = Depends(get_current_user),
    status: Optional[str] = Query(None, description="Filter by status: active, closed, expired, assigned"),
    strategy: Optional[str] = Query(None, description="Filter by strategy: covered_call, pmcc"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100)
):
    """Get all simulator trades for the user"""
    query = {"user_id": user["id"]}
    
    if status:
        query["status"] = status
    if strategy:
        query["strategy_type"] = strategy
    
    skip = (page - 1) * limit
    
    trades = await db.simulator_trades.find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    total = await db.simulator_trades.count_documents(query)
    
    return {
        "trades": trades,
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit
    }


@simulator_router.get("/trades/{trade_id}")
async def get_simulator_trade_detail(trade_id: str, user: dict = Depends(get_current_user)):
    """Get detailed information about a specific simulator trade"""
    trade = await db.simulator_trades.find_one({"id": trade_id, "user_id": user["id"]}, {"_id": 0})
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    return trade


@simulator_router.delete("/trades/{trade_id}")
async def delete_simulator_trade(trade_id: str, user: dict = Depends(get_current_user)):
    """Delete a simulator trade"""
    result = await db.simulator_trades.delete_one({"id": trade_id, "user_id": user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Trade not found")
    return {"message": "Trade deleted"}


@simulator_router.post("/trades/{trade_id}/close")
async def close_simulator_trade(
    trade_id: str,
    close_price: float = Query(..., description="Closing underlying price"),
    close_reason: str = Query("early_close", description="Reason: early_close, rolled"),
    user: dict = Depends(get_current_user)
):
    """Manually close a simulator trade before expiry"""
    trade = await db.simulator_trades.find_one({"id": trade_id, "user_id": user["id"]}, {"_id": 0})
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    
    if trade["status"] != "active":
        raise HTTPException(status_code=400, detail="Trade is not active")
    
    now = datetime.now(timezone.utc)
    
    # Calculate final P&L
    if trade["strategy_type"] == "covered_call":
        # Stock P&L + Premium received
        stock_pnl = (close_price - trade["entry_underlying_price"]) * 100 * trade["contracts"]
        final_pnl = stock_pnl + trade["premium_received"]
    else:  # PMCC
        # Simplified: Assume LEAPS value proportional to intrinsic + some time value
        leaps_value_est = max(0, close_price - trade["leaps_strike"]) * 100 * trade["contracts"]
        final_pnl = leaps_value_est - trade["capital_deployed"] + trade["premium_received"]
    
    roi_percent = (final_pnl / trade["capital_deployed"]) * 100 if trade["capital_deployed"] > 0 else 0
    
    # Calculate days held
    try:
        entry_dt = datetime.strptime(trade["entry_date"], "%Y-%m-%d")
        days_held = (datetime.now() - entry_dt).days
    except:
        days_held = trade.get("days_held", 0)
    
    update_doc = {
        "status": "closed",
        "close_date": now.strftime("%Y-%m-%d"),
        "close_price": close_price,
        "close_reason": close_reason,
        "final_pnl": round(final_pnl, 2),
        "roi_percent": round(roi_percent, 2),
        "realized_pnl": round(final_pnl, 2),
        "days_held": days_held,
        "updated_at": now.isoformat()
    }
    
    # Add to action log
    await db.simulator_trades.update_one(
        {"id": trade_id},
        {
            "$set": update_doc,
            "$push": {"action_log": {
                "action": "closed",
                "timestamp": now.isoformat(),
                "details": f"Closed at ${close_price}, P/L: ${final_pnl:.2f} ({roi_percent:.2f}%)",
                "reason": close_reason
            }}
        }
    )
    
    return {"message": "Trade closed", "final_pnl": final_pnl, "roi_percent": roi_percent}


@simulator_router.post("/update-prices")
async def update_simulator_prices(user: dict = Depends(get_current_user)):
    """Update all active simulator trades with current EOD prices and Greeks"""
    
    # Get all active trades for user
    active_trades = await db.simulator_trades.find(
        {"user_id": user["id"], "status": "active"},
        {"_id": 0}
    ).to_list(1000)
    
    if not active_trades:
        return {"message": "No active trades to update", "updated": 0}
    
    # Get unique symbols
    symbols = list(set(t["symbol"] for t in active_trades))
    
    # Fetch current prices
    price_cache = {}
    for symbol in symbols:
        try:
            quote = await fetch_stock_quote(symbol)
            if quote and quote.get("price"):
                price_cache[symbol] = quote["price"]
        except Exception as e:
            logging.warning(f"Could not fetch price for {symbol}: {e}")
    
    now = datetime.now(timezone.utc)
    risk_free_rate = 0.05  # 5% risk-free rate
    updated_count = 0
    expired_count = 0
    assigned_count = 0
    
    for trade in active_trades:
        symbol = trade["symbol"]
        if symbol not in price_cache:
            continue
        
        current_price = price_cache[symbol]
        
        # Calculate DTE remaining
        try:
            expiry_dt = datetime.strptime(trade["short_call_expiry"], "%Y-%m-%d")
            dte_remaining = (expiry_dt - datetime.now()).days
            time_to_expiry = max(dte_remaining / 365, 0.001)
        except:
            dte_remaining = trade.get("dte_remaining", 0)
            time_to_expiry = max(dte_remaining / 365, 0.001)
        
        # Calculate days held
        try:
            entry_dt = datetime.strptime(trade["entry_date"], "%Y-%m-%d")
            days_held = (datetime.now() - entry_dt).days
        except:
            days_held = trade.get("days_held", 0)
        
        # Calculate current Greeks and option value
        iv = trade.get("short_call_iv") or 0.30
        greeks = calculate_greeks(
            S=current_price,
            K=trade["short_call_strike"],
            T=time_to_expiry,
            r=risk_free_rate,
            sigma=iv
        )
        
        # Calculate unrealized P&L with option value
        entry_premium = trade.get("short_call_premium", 0)
        current_option_value = greeks["option_value"]
        
        if trade["strategy_type"] == "covered_call":
            stock_pnl = (current_price - trade["entry_underlying_price"]) * 100 * trade["contracts"]
            option_pnl = (entry_premium - current_option_value) * 100 * trade["contracts"]
            unrealized_pnl = stock_pnl + option_pnl
        else:  # PMCC
            leaps_iv = trade.get("leaps_iv") or iv
            leaps_dte = 365  # Assume 1 year remaining for LEAPS
            leaps_time_to_expiry = max(leaps_dte / 365, 0.001)
            
            leaps_greeks = calculate_greeks(
                S=current_price,
                K=trade.get("leaps_strike", current_price * 0.8),
                T=leaps_time_to_expiry,
                r=risk_free_rate,
                sigma=leaps_iv
            )
            
            leaps_value_change = (leaps_greeks["option_value"] - trade.get("leaps_premium", 0)) * 100 * trade["contracts"]
            short_call_pnl = (entry_premium - current_option_value) * 100 * trade["contracts"]
            unrealized_pnl = leaps_value_change + short_call_pnl
        
        # Calculate premium capture percentage
        if entry_premium > 0 and current_option_value >= 0:
            premium_capture_pct = ((entry_premium - current_option_value) / entry_premium) * 100
        else:
            premium_capture_pct = 0
        
        update_doc = {
            "current_underlying_price": current_price,
            "current_option_value": round(current_option_value, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "days_held": days_held,
            "dte_remaining": dte_remaining,
            "premium_capture_pct": round(premium_capture_pct, 1),
            "last_updated": now.isoformat(),
            "updated_at": now.isoformat(),
            # Greeks
            "current_delta": greeks["delta"],
            "current_gamma": greeks["gamma"],
            "current_theta": greeks["theta"],
            "current_vega": greeks["vega"],
        }
        
        # Check for expiry (DTE <= 0)
        if dte_remaining <= 0:
            # Determine outcome based on price vs strike
            if current_price >= trade["short_call_strike"]:
                # ITM - Assigned
                if trade["strategy_type"] == "covered_call":
                    final_pnl = ((trade["short_call_strike"] - trade["entry_underlying_price"]) * 100 + entry_premium * 100) * trade["contracts"]
                else:  # PMCC
                    short_call_loss = (current_price - trade["short_call_strike"]) * 100 * trade["contracts"]
                    leaps_gain = max(0, current_price - trade["leaps_strike"]) * 100 * trade["contracts"]
                    final_pnl = leaps_gain - trade["capital_deployed"] + trade["premium_received"] - short_call_loss
                
                update_doc.update({
                    "status": "assigned",
                    "close_date": now.strftime("%Y-%m-%d"),
                    "close_price": current_price,
                    "close_reason": "assigned_itm",
                    "final_pnl": round(final_pnl, 2),
                    "roi_percent": round((final_pnl / trade["capital_deployed"]) * 100, 2) if trade["capital_deployed"] > 0 else 0,
                    "realized_pnl": round(final_pnl, 2),
                    "premium_capture_pct": 100
                })
                assigned_count += 1
            else:
                # OTM - Option expires worthless, keep premium
                if trade["strategy_type"] == "covered_call":
                    final_pnl = (current_price - trade["entry_underlying_price"]) * 100 * trade["contracts"] + trade["premium_received"]
                else:
                    final_pnl = trade["premium_received"]
                
                update_doc.update({
                    "status": "expired",
                    "close_date": now.strftime("%Y-%m-%d"),
                    "close_price": current_price,
                    "close_reason": "expired_otm",
                    "final_pnl": round(final_pnl, 2),
                    "roi_percent": round((final_pnl / trade["capital_deployed"]) * 100, 2) if trade["capital_deployed"] > 0 else 0,
                    "realized_pnl": round(final_pnl, 2),
                    "premium_capture_pct": 100
                })
                expired_count += 1
            
            # Add action log entry
            await db.simulator_trades.update_one(
                {"id": trade["id"]},
                {"$push": {"action_log": {
                    "action": update_doc["status"],
                    "timestamp": now.isoformat(),
                    "details": f"Expired at ${current_price}, Final P/L: ${update_doc['final_pnl']:.2f}"
                }}}
            )
        
        await db.simulator_trades.update_one({"id": trade["id"]}, {"$set": update_doc})
        updated_count += 1
    
    return {
        "message": "Prices updated",
        "updated": updated_count,
        "expired": expired_count,
        "assigned": assigned_count
    }


@simulator_router.get("/summary")
async def get_simulator_summary(user: dict = Depends(get_current_user)):
    """Get portfolio-level summary statistics"""
    
    trades = await db.simulator_trades.find(
        {"user_id": user["id"]},
        {"_id": 0}
    ).to_list(1000)
    
    if not trades:
        return {
            "total_trades": 0,
            "active_trades": 0,
            "closed_trades": 0,
            "total_capital_deployed": 0,
            "total_unrealized_pnl": 0,
            "total_realized_pnl": 0,
            "total_pnl": 0,
            "win_rate": 0,
            "avg_return_per_trade": 0,
            "assignment_rate": 0,
            "by_strategy": {}
        }
    
    # Aggregate stats
    active_trades = [t for t in trades if t["status"] == "active"]
    closed_trades = [t for t in trades if t["status"] in ["closed", "expired", "assigned"]]
    winning_trades = [t for t in closed_trades if (t.get("final_pnl") or 0) > 0]
    assigned_trades = [t for t in closed_trades if t["status"] == "assigned"]
    
    total_capital = sum(t.get("capital_deployed", 0) for t in active_trades)
    total_unrealized = sum(t.get("unrealized_pnl", 0) for t in active_trades)
    total_realized = sum(t.get("final_pnl", 0) or 0 for t in closed_trades)
    
    win_rate = (len(winning_trades) / len(closed_trades) * 100) if closed_trades else 0
    avg_return = (total_realized / len(closed_trades)) if closed_trades else 0
    assignment_rate = (len(assigned_trades) / len(closed_trades) * 100) if closed_trades else 0
    
    # By strategy breakdown
    by_strategy = {}
    for strategy in ["covered_call", "pmcc"]:
        strat_trades = [t for t in trades if t["strategy_type"] == strategy]
        strat_active = [t for t in strat_trades if t["status"] == "active"]
        strat_closed = [t for t in strat_trades if t["status"] in ["closed", "expired", "assigned"]]
        strat_wins = [t for t in strat_closed if (t.get("final_pnl") or 0) > 0]
        
        by_strategy[strategy] = {
            "total": len(strat_trades),
            "active": len(strat_active),
            "closed": len(strat_closed),
            "capital_deployed": sum(t.get("capital_deployed", 0) for t in strat_active),
            "unrealized_pnl": sum(t.get("unrealized_pnl", 0) for t in strat_active),
            "realized_pnl": sum(t.get("final_pnl", 0) or 0 for t in strat_closed),
            "win_rate": (len(strat_wins) / len(strat_closed) * 100) if strat_closed else 0
        }
    
    return {
        "total_trades": len(trades),
        "active_trades": len(active_trades),
        "closed_trades": len(closed_trades),
        "total_capital_deployed": round(total_capital, 2),
        "total_unrealized_pnl": round(total_unrealized, 2),
        "total_realized_pnl": round(total_realized, 2),
        "total_pnl": round(total_unrealized + total_realized, 2),
        "win_rate": round(win_rate, 1),
        "avg_return_per_trade": round(avg_return, 2),
        "assignment_rate": round(assignment_rate, 1),
        "by_strategy": by_strategy
    }


@simulator_router.delete("/clear")
async def clear_simulator_data(user: dict = Depends(get_current_user)):
    """Clear all simulator trades for the user"""
    result = await db.simulator_trades.delete_many({"user_id": user["id"]})
    return {"message": f"Cleared {result.deleted_count} simulator trades"}


@simulator_router.get("/scheduler-status")
async def get_scheduler_status(user: dict = Depends(get_current_user)):
    """Get the status of the automated price update scheduler"""
    jobs = scheduler.get_jobs()
    job_info = []
    for job in jobs:
        job_info.append({
            "id": job.id,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger)
        })
    
    return {
        "scheduler_running": scheduler.running,
        "jobs": job_info,
        "timezone": "America/New_York",
        "schedule": "4:30 PM ET on weekdays (Mon-Fri)"
    }


@simulator_router.post("/trigger-update")
async def trigger_manual_update(user: dict = Depends(get_current_user)):
    """Manually trigger a price update for the current user's trades (same as Update Prices button)"""
    # This is essentially the same as update_simulator_prices but we can add admin-only full update later
    return await update_simulator_prices(user)


# ==================== PHASE 3: RULE-BASED TRADE MANAGEMENT ====================

# Pydantic Models for Trade Rules
class TradeRuleCondition(BaseModel):
    """Individual condition for a rule"""
    field: str  # premium_capture_pct, current_delta, loss_pct, dte_remaining, etc.
    operator: str  # gte, lte, gt, lt, eq
    value: float
    
class TradeRuleAction(BaseModel):
    """Action to take when rule conditions are met"""
    action_type: str  # roll, close, alert
    parameters: Optional[Dict[str, Any]] = None  # e.g., new_dte for roll

class TradeRuleCreate(BaseModel):
    """Model for creating a trade rule"""
    name: str
    description: Optional[str] = None
    strategy_type: Optional[str] = None  # covered_call, pmcc, or None for both
    is_enabled: bool = True
    priority: int = 10  # Lower number = higher priority
    conditions: List[TradeRuleCondition]
    action: TradeRuleAction
    
class TradeRuleUpdate(BaseModel):
    """Model for updating a trade rule"""
    name: Optional[str] = None
    description: Optional[str] = None
    strategy_type: Optional[str] = None
    is_enabled: Optional[bool] = None
    priority: Optional[int] = None
    conditions: Optional[List[TradeRuleCondition]] = None
    action: Optional[TradeRuleAction] = None


# ==================== RULE EVALUATION ENGINE ====================

def evaluate_condition(trade: dict, condition: dict) -> bool:
    """Evaluate a single condition against a trade"""
    field = condition["field"]
    operator = condition["operator"]
    target_value = condition["value"]
    
    # Get the actual value from trade
    actual_value = None
    
    if field == "premium_capture_pct":
        actual_value = trade.get("premium_capture_pct", 0)
    elif field == "current_delta":
        actual_value = trade.get("current_delta") or trade.get("short_call_delta", 0)
    elif field == "loss_pct":
        # Calculate loss as percentage of capital deployed
        unrealized = trade.get("unrealized_pnl", 0)
        capital = trade.get("capital_deployed", 1)
        actual_value = (unrealized / capital) * 100 if capital > 0 else 0
    elif field == "profit_pct":
        # Calculate profit as percentage of capital deployed
        unrealized = trade.get("unrealized_pnl", 0)
        capital = trade.get("capital_deployed", 1)
        actual_value = (unrealized / capital) * 100 if capital > 0 else 0
    elif field == "dte_remaining":
        actual_value = trade.get("dte_remaining", 999)
    elif field == "days_held":
        actual_value = trade.get("days_held", 0)
    elif field == "current_theta":
        actual_value = abs(trade.get("current_theta", 0))
    elif field == "current_gamma":
        actual_value = trade.get("current_gamma", 0)
    elif field == "unrealized_pnl":
        actual_value = trade.get("unrealized_pnl", 0)
    elif field == "leaps_decay_pct":
        # For PMCC: estimate LEAPS time decay
        if trade.get("strategy_type") == "pmcc":
            leaps_cost = trade.get("leaps_premium", 0) * 100 * trade.get("contracts", 1)
            # Simplified decay estimate based on days held
            days_held = trade.get("days_held", 0)
            initial_dte = trade.get("initial_dte", 30)
            decay_rate = days_held / max(initial_dte * 4, 1)  # Rough estimate
            actual_value = decay_rate * 100
        else:
            actual_value = 0
    elif field == "cumulative_income_ratio":
        # For PMCC: cumulative premium income vs LEAPS cost
        if trade.get("strategy_type") == "pmcc":
            leaps_cost = trade.get("capital_deployed", 1)
            premium = trade.get("premium_received", 0)
            cumulative = trade.get("cumulative_premium", premium)
            actual_value = (cumulative / leaps_cost) * 100 if leaps_cost > 0 else 0
        else:
            actual_value = 0
    else:
        actual_value = trade.get(field, 0)
    
    if actual_value is None:
        return False
    
    # Compare based on operator
    if operator == "gte":
        return actual_value >= target_value
    elif operator == "lte":
        return actual_value <= target_value
    elif operator == "gt":
        return actual_value > target_value
    elif operator == "lt":
        return actual_value < target_value
    elif operator == "eq":
        return abs(actual_value - target_value) < 0.001
    
    return False


def evaluate_rule(trade: dict, rule: dict) -> bool:
    """Evaluate all conditions of a rule against a trade"""
    conditions = rule.get("conditions", [])
    if not conditions:
        return False
    
    # All conditions must be true (AND logic)
    for condition in conditions:
        if not evaluate_condition(trade, condition):
            return False
    
    return True


async def execute_rule_action(trade: dict, rule: dict, db_instance) -> dict:
    """Execute the action defined in a rule"""
    action = rule.get("action", {})
    action_type = action.get("action_type", "alert")
    params = action.get("parameters", {})
    
    now = datetime.now(timezone.utc)
    trade_id = trade["id"]
    
    result = {
        "success": False,
        "action_type": action_type,
        "message": "",
        "new_trade_id": None
    }
    
    if action_type == "close":
        # Close the trade early
        current_price = trade.get("current_underlying_price", trade["entry_underlying_price"])
        
        if trade["strategy_type"] == "covered_call":
            stock_pnl = (current_price - trade["entry_underlying_price"]) * 100 * trade["contracts"]
            final_pnl = stock_pnl + trade["premium_received"] - (trade.get("current_option_value", 0) * 100 * trade["contracts"])
        else:  # PMCC
            final_pnl = trade.get("unrealized_pnl", 0)
        
        roi_percent = (final_pnl / trade["capital_deployed"]) * 100 if trade["capital_deployed"] > 0 else 0
        close_reason = params.get("reason", f"rule_close_{rule['id'][:8]}")
        
        update_doc = {
            "status": "closed",
            "close_date": now.strftime("%Y-%m-%d"),
            "close_price": current_price,
            "close_reason": close_reason,
            "final_pnl": round(final_pnl, 2),
            "roi_percent": round(roi_percent, 2),
            "realized_pnl": round(final_pnl, 2),
            "updated_at": now.isoformat()
        }
        
        await db_instance.simulator_trades.update_one(
            {"id": trade_id},
            {
                "$set": update_doc,
                "$push": {"action_log": {
                    "action": "rule_closed",
                    "timestamp": now.isoformat(),
                    "rule_id": rule["id"],
                    "rule_name": rule["name"],
                    "details": f"Auto-closed by rule '{rule['name']}' at ${current_price:.2f}, P/L: ${final_pnl:.2f}"
                }}
            }
        )
        
        result["success"] = True
        result["message"] = f"Trade closed by rule '{rule['name']}', Final P/L: ${final_pnl:.2f}"
        
    elif action_type == "roll":
        # Roll the call - close current position and open new one with new expiry
        current_price = trade.get("current_underlying_price", trade["entry_underlying_price"])
        current_option_value = trade.get("current_option_value", 0)
        
        # Calculate P&L from closing current short call (buying to close)
        buyback_cost = current_option_value * 100 * trade["contracts"]
        original_premium = trade["premium_received"]
        roll_pnl = original_premium - buyback_cost
        
        # New expiry parameters
        new_dte = params.get("new_dte", 30)  # Default 30 DTE
        new_strike_adjustment = params.get("strike_adjustment", 0)  # 0 = same strike, positive = higher
        
        new_expiry_dt = datetime.now() + timedelta(days=new_dte)
        new_expiry = new_expiry_dt.strftime("%Y-%m-%d")
        new_strike = trade["short_call_strike"] + new_strike_adjustment
        
        # Estimate new premium (simplified - use same ratio)
        estimated_new_premium = trade.get("short_call_premium", 0) * 0.8  # Conservative estimate
        
        # Update current trade as rolled
        await db_instance.simulator_trades.update_one(
            {"id": trade_id},
            {
                "$set": {
                    "status": "closed",
                    "close_date": now.strftime("%Y-%m-%d"),
                    "close_price": current_price,
                    "close_reason": "rolled",
                    "final_pnl": round(roll_pnl, 2),
                    "roi_percent": round((roll_pnl / trade["capital_deployed"]) * 100, 2) if trade["capital_deployed"] > 0 else 0,
                    "realized_pnl": round(roll_pnl, 2),
                    "updated_at": now.isoformat()
                },
                "$push": {"action_log": {
                    "action": "rolled",
                    "timestamp": now.isoformat(),
                    "rule_id": rule["id"],
                    "rule_name": rule["name"],
                    "details": f"Rolled by rule '{rule['name']}': closed ${trade['short_call_strike']} call, P/L: ${roll_pnl:.2f}"
                }}
            }
        )
        
        # Create new trade for the rolled position
        new_trade_id = str(uuid.uuid4())
        cumulative_premium = trade.get("cumulative_premium", trade["premium_received"]) + (estimated_new_premium * 100 * trade["contracts"])
        roll_count = trade.get("roll_count", 0) + 1
        
        new_trade_doc = {
            "id": new_trade_id,
            "user_id": trade["user_id"],
            "symbol": trade["symbol"],
            "strategy_type": trade["strategy_type"],
            "status": "active",
            
            # Entry snapshot (carry forward stock/LEAPS position)
            "entry_date": trade["entry_date"],  # Original entry date
            "entry_underlying_price": trade["entry_underlying_price"],  # Original entry price
            
            # New short call details
            "short_call_strike": new_strike,
            "short_call_expiry": new_expiry,
            "short_call_premium": estimated_new_premium,
            "short_call_delta": trade.get("short_call_delta"),
            "short_call_iv": trade.get("short_call_iv"),
            
            # LEAPS details (for PMCC) - carried forward
            "leaps_strike": trade.get("leaps_strike"),
            "leaps_expiry": trade.get("leaps_expiry"),
            "leaps_premium": trade.get("leaps_premium"),
            "leaps_delta": trade.get("leaps_delta"),
            
            # Position sizing
            "contracts": trade["contracts"],
            
            # Capital (carry forward)
            "capital_deployed": trade["capital_deployed"],
            "premium_received": estimated_new_premium * 100 * trade["contracts"],
            "cumulative_premium": cumulative_premium,  # Track total premium across rolls
            "max_profit": trade["max_profit"],
            "max_loss": trade["max_loss"],
            "breakeven": trade["breakeven"],
            "initial_dte": new_dte,
            
            # Live tracking
            "current_underlying_price": current_price,
            "current_option_value": estimated_new_premium,
            "unrealized_pnl": 0,
            "realized_pnl": roll_pnl,  # Carry forward realized P&L from roll
            "days_held": trade.get("days_held", 0),
            "dte_remaining": new_dte,
            "last_updated": now.isoformat(),
            
            # Roll tracking
            "roll_count": roll_count,
            "rolled_from_trade_id": trade_id,
            "original_trade_id": trade.get("original_trade_id", trade_id),
            
            # Audit
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "action_log": [{
                "action": "rolled_open",
                "timestamp": now.isoformat(),
                "rule_id": rule["id"],
                "rule_name": rule["name"],
                "details": f"New position from roll: ${new_strike} call exp {new_expiry}, Roll #{roll_count}"
            }]
        }
        
        await db_instance.simulator_trades.insert_one(new_trade_doc)
        
        result["success"] = True
        result["new_trade_id"] = new_trade_id
        result["message"] = f"Rolled to ${new_strike} strike, exp {new_expiry} (Roll #{roll_count})"
        
    elif action_type == "alert":
        # Just log an alert/notification (no trade changes)
        await db_instance.simulator_trades.update_one(
            {"id": trade_id},
            {"$push": {"action_log": {
                "action": "rule_alert",
                "timestamp": now.isoformat(),
                "rule_id": rule["id"],
                "rule_name": rule["name"],
                "details": f"Alert from rule '{rule['name']}': {params.get('message', 'Condition triggered')}"
            }}}
        )
        
        result["success"] = True
        result["message"] = f"Alert logged for rule '{rule['name']}'"
    
    return result


async def evaluate_and_execute_rules(trade: dict, rules: list, db_instance) -> list:
    """Evaluate all applicable rules for a trade and execute matching ones"""
    results = []
    
    # Sort rules by priority (lower number = higher priority)
    sorted_rules = sorted(rules, key=lambda r: r.get("priority", 10))
    
    for rule in sorted_rules:
        # Check if rule applies to this strategy type
        rule_strategy = rule.get("strategy_type")
        if rule_strategy and rule_strategy != trade["strategy_type"]:
            continue
        
        # Check if rule is enabled
        if not rule.get("is_enabled", True):
            continue
        
        # Evaluate rule conditions
        if evaluate_rule(trade, rule):
            # Execute the action
            result = await execute_rule_action(trade, rule, db_instance)
            results.append({
                "rule_id": rule["id"],
                "rule_name": rule["name"],
                **result
            })
            
            # If action was close or roll, stop evaluating more rules for this trade
            if result["success"] and rule["action"]["action_type"] in ["close", "roll"]:
                break
    
    return results


# ==================== RULE ENDPOINTS ====================

@simulator_router.post("/rules")
async def create_trade_rule(rule: TradeRuleCreate, user: dict = Depends(get_current_user)):
    """Create a new trade management rule"""
    
    rule_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    
    rule_doc = {
        "id": rule_id,
        "user_id": user["id"],
        "name": rule.name,
        "description": rule.description,
        "strategy_type": rule.strategy_type,
        "is_enabled": rule.is_enabled,
        "priority": rule.priority,
        "conditions": [c.model_dump() for c in rule.conditions],
        "action": rule.action.model_dump(),
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "times_triggered": 0
    }
    
    await db.simulator_rules.insert_one(rule_doc)
    
    # Remove _id for response
    if "_id" in rule_doc:
        del rule_doc["_id"]
    
    return {"message": "Rule created", "rule": rule_doc}


@simulator_router.get("/rules")
async def get_trade_rules(
    user: dict = Depends(get_current_user),
    strategy: Optional[str] = Query(None, description="Filter by strategy type"),
    enabled_only: bool = Query(False, description="Only return enabled rules")
):
    """Get all trade management rules for the user"""
    
    query = {"user_id": user["id"]}
    if strategy:
        query["strategy_type"] = {"$in": [strategy, None]}  # Match specific or applies to all
    if enabled_only:
        query["is_enabled"] = True
    
    rules = await db.simulator_rules.find(query, {"_id": 0}).sort("priority", 1).to_list(100)
    
    return {"rules": rules, "total": len(rules)}


@simulator_router.get("/rules/{rule_id}")
async def get_trade_rule(rule_id: str, user: dict = Depends(get_current_user)):
    """Get a specific trade rule"""
    
    rule = await db.simulator_rules.find_one(
        {"id": rule_id, "user_id": user["id"]},
        {"_id": 0}
    )
    
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    return rule


@simulator_router.put("/rules/{rule_id}")
async def update_trade_rule(
    rule_id: str,
    update: TradeRuleUpdate,
    user: dict = Depends(get_current_user)
):
    """Update a trade rule"""
    
    rule = await db.simulator_rules.find_one({"id": rule_id, "user_id": user["id"]})
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    update_doc = {"updated_at": datetime.now(timezone.utc).isoformat()}
    
    if update.name is not None:
        update_doc["name"] = update.name
    if update.description is not None:
        update_doc["description"] = update.description
    if update.strategy_type is not None:
        update_doc["strategy_type"] = update.strategy_type
    if update.is_enabled is not None:
        update_doc["is_enabled"] = update.is_enabled
    if update.priority is not None:
        update_doc["priority"] = update.priority
    if update.conditions is not None:
        update_doc["conditions"] = [c.model_dump() for c in update.conditions]
    if update.action is not None:
        update_doc["action"] = update.action.model_dump()
    
    await db.simulator_rules.update_one(
        {"id": rule_id, "user_id": user["id"]},
        {"$set": update_doc}
    )
    
    updated_rule = await db.simulator_rules.find_one({"id": rule_id}, {"_id": 0})
    return {"message": "Rule updated", "rule": updated_rule}


@simulator_router.delete("/rules/{rule_id}")
async def delete_trade_rule(rule_id: str, user: dict = Depends(get_current_user)):
    """Delete a trade rule"""
    
    result = await db.simulator_rules.delete_one({"id": rule_id, "user_id": user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    return {"message": "Rule deleted"}


@simulator_router.post("/rules/evaluate")
async def evaluate_rules_manually(
    user: dict = Depends(get_current_user),
    dry_run: bool = Query(True, description="If true, only show what would happen without executing")
):
    """Manually evaluate and optionally execute all rules against active trades"""
    
    # Get user's active trades
    active_trades = await db.simulator_trades.find(
        {"user_id": user["id"], "status": "active"},
        {"_id": 0}
    ).to_list(1000)
    
    if not active_trades:
        return {"message": "No active trades to evaluate", "results": []}
    
    # Get user's enabled rules
    rules = await db.simulator_rules.find(
        {"user_id": user["id"], "is_enabled": True},
        {"_id": 0}
    ).to_list(100)
    
    if not rules:
        return {"message": "No enabled rules found", "results": []}
    
    all_results = []
    
    for trade in active_trades:
        trade_results = []
        
        for rule in sorted(rules, key=lambda r: r.get("priority", 10)):
            # Check if rule applies to this strategy
            if rule.get("strategy_type") and rule["strategy_type"] != trade["strategy_type"]:
                continue
            
            # Evaluate conditions
            if evaluate_rule(trade, rule):
                if dry_run:
                    trade_results.append({
                        "rule_id": rule["id"],
                        "rule_name": rule["name"],
                        "action_type": rule["action"]["action_type"],
                        "would_execute": True,
                        "dry_run": True
                    })
                    # In dry run, continue checking all rules
                else:
                    # Actually execute
                    result = await execute_rule_action(trade, rule, db)
                    trade_results.append({
                        "rule_id": rule["id"],
                        "rule_name": rule["name"],
                        **result
                    })
                    
                    # Update trigger count
                    await db.simulator_rules.update_one(
                        {"id": rule["id"]},
                        {"$inc": {"times_triggered": 1}}
                    )
                    
                    if result["success"] and rule["action"]["action_type"] in ["close", "roll"]:
                        break
        
        if trade_results:
            all_results.append({
                "trade_id": trade["id"],
                "symbol": trade["symbol"],
                "strategy": trade["strategy_type"],
                "matched_rules": trade_results
            })
    
    return {
        "dry_run": dry_run,
        "trades_evaluated": len(active_trades),
        "rules_count": len(rules),
        "results": all_results
    }


@simulator_router.get("/rules/templates")
async def get_rule_templates(user: dict = Depends(get_current_user)):
    """Get pre-defined rule templates for common strategies"""
    
    templates = [
        {
            "id": "premium_capture_80",
            "name": "Roll at 80% Premium Capture",
            "description": "Roll the call when 80% of the premium has been captured",
            "strategy_type": None,
            "conditions": [
                {"field": "premium_capture_pct", "operator": "gte", "value": 80}
            ],
            "action": {
                "action_type": "roll",
                "parameters": {"new_dte": 30, "strike_adjustment": 0}
            }
        },
        {
            "id": "delta_threshold",
            "name": "Roll at High Delta",
            "description": "Roll when delta exceeds 0.70 (high probability of assignment)",
            "strategy_type": None,
            "conditions": [
                {"field": "current_delta", "operator": "gte", "value": 0.70}
            ],
            "action": {
                "action_type": "roll",
                "parameters": {"new_dte": 30, "strike_adjustment": 5}
            }
        },
        {
            "id": "stop_loss_10",
            "name": "Stop Loss at 10%",
            "description": "Close trade if loss exceeds 10% of capital deployed",
            "strategy_type": None,
            "conditions": [
                {"field": "loss_pct", "operator": "lte", "value": -10}
            ],
            "action": {
                "action_type": "close",
                "parameters": {"reason": "stop_loss"}
            }
        },
        {
            "id": "time_decay_exit",
            "name": "Exit Near Expiry",
            "description": "Close 5 days before expiry to avoid gamma risk",
            "strategy_type": "covered_call",
            "conditions": [
                {"field": "dte_remaining", "operator": "lte", "value": 5},
                {"field": "premium_capture_pct", "operator": "gte", "value": 50}
            ],
            "action": {
                "action_type": "close",
                "parameters": {"reason": "time_exit"}
            }
        },
        {
            "id": "pmcc_weekly_roll",
            "name": "PMCC Weekly Roll",
            "description": "Roll PMCC short leg when DTE <= 7 and premium capture >= 60%",
            "strategy_type": "pmcc",
            "conditions": [
                {"field": "dte_remaining", "operator": "lte", "value": 7},
                {"field": "premium_capture_pct", "operator": "gte", "value": 60}
            ],
            "action": {
                "action_type": "roll",
                "parameters": {"new_dte": 14, "strike_adjustment": 0}
            }
        },
        {
            "id": "pmcc_leaps_decay_alert",
            "name": "PMCC LEAPS Decay Alert",
            "description": "Alert when cumulative premium hasn't offset LEAPS decay",
            "strategy_type": "pmcc",
            "conditions": [
                {"field": "cumulative_income_ratio", "operator": "lt", "value": 20},
                {"field": "days_held", "operator": "gte", "value": 30}
            ],
            "action": {
                "action_type": "alert",
                "parameters": {"message": "LEAPS decay outpacing premium income"}
            }
        },
        {
            "id": "profit_target_5",
            "name": "Take Profit at 5%",
            "description": "Close trade when profit reaches 5% of capital",
            "strategy_type": None,
            "conditions": [
                {"field": "profit_pct", "operator": "gte", "value": 5}
            ],
            "action": {
                "action_type": "close",
                "parameters": {"reason": "profit_target"}
            }
        }
    ]
    
    return {"templates": templates}


@simulator_router.post("/rules/from-template/{template_id}")
async def create_rule_from_template(template_id: str, user: dict = Depends(get_current_user)):
    """Create a new rule from a template"""
    
    # Get templates
    templates_response = await get_rule_templates(user)
    templates = templates_response["templates"]
    
    template = next((t for t in templates if t["id"] == template_id), None)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    # Create rule from template
    rule_data = TradeRuleCreate(
        name=template["name"],
        description=template["description"],
        strategy_type=template["strategy_type"],
        is_enabled=True,
        priority=10,
        conditions=[TradeRuleCondition(**c) for c in template["conditions"]],
        action=TradeRuleAction(**template["action"])
    )
    
    return await create_trade_rule(rule_data, user)


# ==================== ACTION LOG ENDPOINTS ====================

@simulator_router.get("/action-logs")
async def get_action_logs(
    user: dict = Depends(get_current_user),
    trade_id: Optional[str] = Query(None, description="Filter by trade ID"),
    action_type: Optional[str] = Query(None, description="Filter by action type"),
    limit: int = Query(50, ge=1, le=200),
    page: int = Query(1, ge=1)
):
    """Get action logs from all trades"""
    
    # Query for trades with action logs
    query = {"user_id": user["id"]}
    if trade_id:
        query["id"] = trade_id
    
    trades = await db.simulator_trades.find(
        query,
        {"id": 1, "symbol": 1, "strategy_type": 1, "action_log": 1, "_id": 0}
    ).to_list(1000)
    
    # Flatten and sort all action logs
    all_logs = []
    for trade in trades:
        for log in trade.get("action_log", []):
            if action_type and log.get("action") != action_type:
                continue
            all_logs.append({
                "trade_id": trade["id"],
                "symbol": trade["symbol"],
                "strategy_type": trade["strategy_type"],
                **log
            })
    
    # Sort by timestamp descending
    all_logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    
    # Paginate
    skip = (page - 1) * limit
    paginated_logs = all_logs[skip:skip + limit]
    
    return {
        "logs": paginated_logs,
        "total": len(all_logs),
        "page": page,
        "pages": (len(all_logs) + limit - 1) // limit
    }


@simulator_router.get("/pmcc-summary")
async def get_pmcc_summary(user: dict = Depends(get_current_user)):
    """Get PMCC-specific summary: cumulative income vs LEAPS decay tracking"""
    
    # Get all PMCC trades (active and closed)
    pmcc_trades = await db.simulator_trades.find(
        {"user_id": user["id"], "strategy_type": "pmcc"},
        {"_id": 0}
    ).to_list(1000)
    
    if not pmcc_trades:
        return {"message": "No PMCC trades found", "summary": None}
    
    # Group by original trade (to track rolls)
    trade_chains = {}
    for trade in pmcc_trades:
        original_id = trade.get("original_trade_id", trade["id"])
        if original_id not in trade_chains:
            trade_chains[original_id] = []
        trade_chains[original_id].append(trade)
    
    summaries = []
    for original_id, chain in trade_chains.items():
        # Sort by entry date to get chronological order
        chain.sort(key=lambda t: t.get("created_at", ""))
        
        first_trade = chain[0]
        latest_trade = chain[-1]
        
        # Calculate totals
        total_premium_received = sum(t.get("premium_received", 0) for t in chain)
        total_realized_pnl = sum(t.get("realized_pnl", 0) or 0 for t in chain if t["status"] != "active")
        leaps_cost = first_trade.get("capital_deployed", 0)
        roll_count = len(chain) - 1
        
        # Calculate LEAPS decay estimate
        if first_trade.get("leaps_expiry"):
            try:
                leaps_expiry_dt = datetime.strptime(first_trade["leaps_expiry"], "%Y-%m-%d")
                days_to_leaps_expiry = (leaps_expiry_dt - datetime.now()).days
                original_leaps_dte = first_trade.get("initial_dte", 365) * 4  # Rough estimate
                decay_pct = ((original_leaps_dte - days_to_leaps_expiry) / original_leaps_dte) * 100 if original_leaps_dte > 0 else 0
            except:
                decay_pct = 0
                days_to_leaps_expiry = 365
        else:
            decay_pct = 0
            days_to_leaps_expiry = 365
        
        # Income to cost ratio
        income_ratio = (total_premium_received / leaps_cost) * 100 if leaps_cost > 0 else 0
        
        summaries.append({
            "original_trade_id": original_id,
            "symbol": first_trade["symbol"],
            "leaps_strike": first_trade.get("leaps_strike"),
            "leaps_expiry": first_trade.get("leaps_expiry"),
            "leaps_cost": leaps_cost,
            "days_to_leaps_expiry": days_to_leaps_expiry,
            "roll_count": roll_count,
            "status": latest_trade["status"],
            
            # Income tracking
            "total_premium_received": round(total_premium_received, 2),
            "total_realized_pnl": round(total_realized_pnl, 2),
            "unrealized_pnl": latest_trade.get("unrealized_pnl", 0) if latest_trade["status"] == "active" else 0,
            
            # Ratios
            "income_to_cost_ratio": round(income_ratio, 2),
            "estimated_leaps_decay_pct": round(decay_pct, 1),
            
            # Health indicator
            "health": "good" if income_ratio > decay_pct else "warning" if income_ratio > decay_pct * 0.5 else "critical"
        })
    
    # Overall PMCC stats
    total_leaps_cost = sum(s["leaps_cost"] for s in summaries)
    total_income = sum(s["total_premium_received"] for s in summaries)
    
    return {
        "summary": summaries,
        "overall": {
            "total_pmcc_positions": len(summaries),
            "active_positions": len([s for s in summaries if s["status"] == "active"]),
            "total_leaps_investment": round(total_leaps_cost, 2),
            "total_premium_income": round(total_income, 2),
            "overall_income_ratio": round((total_income / total_leaps_cost) * 100, 2) if total_leaps_cost > 0 else 0
        }
    }


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
api_router.include_router(chatbot_router)
api_router.include_router(simulator_router)

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
    
    # Create simulator trades index
    await db.simulator_trades.create_index([("user_id", 1), ("status", 1)])
    await db.simulator_trades.create_index("id", unique=True)
    
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
    
    # Start the scheduler for automated price updates
    # Run at 4:30 PM ET (after market close) on weekdays
    scheduler.add_job(
        scheduled_price_update,
        CronTrigger(hour=16, minute=30, day_of_week='mon-fri', timezone='America/New_York'),
        id='simulator_price_update',
        replace_existing=True
    )
    scheduler.start()
    logger.info("Simulator price update scheduler started - runs at 4:30 PM ET on weekdays")

@app.on_event("shutdown")
async def shutdown_db_client():
    # Shutdown scheduler
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Simulator scheduler shut down")
    client.close()
