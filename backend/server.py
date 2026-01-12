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

# Import external routers (refactored)
from routes.auth import auth_router
from routes.watchlist import watchlist_router
from routes.news import news_router
from routes.chatbot import chatbot_router
from routes.ai import ai_router
from routes.subscription import subscription_router
from routes.stocks import stocks_router
from routes.options import options_router
from routes.admin import admin_router
from routes.portfolio import portfolio_router
from routes.screener import screener_router
from routes.simulator import simulator_router
from routes.support import support_router

# Create routers (still in server.py - to be refactored)
api_router = APIRouter(prefix="/api")

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


def calculate_dte(expiry_date: str) -> int:
    """Calculate days to expiration"""
    if not expiry_date:
        return 0
    try:
        exp = datetime.strptime(expiry_date, "%Y-%m-%d")
        today = datetime.now()
        return max(0, (exp - today).days)
    except Exception:
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
                                if min_dte >= 150:  # LEAPS (150+ days is standard threshold for long-dated options)
                                    # For LEAPS: allow deep ITM (40% to 95% of current price)
                                    if strike_pct < 40 or strike_pct > 95:
                                        continue
                                else:  # Short calls
                                    # For short-term: allow near/at/OTM (95% to 150% of current price)
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

# ==================== AUTH ROUTES (Moved to routes/auth.py) ====================

# ==================== STOCKS ROUTES (Moved to routes/stocks.py) ====================

# ==================== OPTIONS ROUTES (Moved to routes/options.py) ====================

# ==================== SCREENER ROUTES (Moved to routes/screener.py) ====================
# ==================== PORTFOLIO ROUTES (Moved to routes/portfolio.py) ====================

# ==================== WATCHLIST ROUTES (Moved to routes/watchlist.py) ====================

# ==================== NEWS ROUTES (Moved to routes/news.py) ====================

# ==================== AI ROUTES (Moved to routes/ai.py) ====================

# ==================== ADMIN ROUTES (Moved to routes/admin.py) ====================

# ==================== SUBSCRIPTION ROUTES (Moved to routes/subscription.py) ====================

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

# ==================== ENHANCED ADMIN & EMAIL AUTOMATION (Moved to routes/admin.py) ====================

# ==================== CHATBOT ENDPOINTS (Moved to routes/chatbot.py) ====================

# ==================== CONTACT FORM ENDPOINT ====================

class ContactForm(BaseModel):
    name: str
    email: EmailStr
    subject: Optional[str] = ""
    message: str

@api_router.post("/contact")
async def submit_contact_form(form: ContactForm):
    """Submit a contact/support form - creates a support ticket with AI classification"""
    from services.support_service import SupportService
    
    service = SupportService(db)
    result = await service.create_ticket(
        name=form.name,
        email=form.email,
        subject=form.subject or "General Inquiry",
        message=form.message
    )
    
    return {"success": True, **result}

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


# ==================== SCHEDULER FOR AUTOMATED UPDATES ====================

# Import simulator functions for scheduled updates
from routes.simulator import calculate_greeks, evaluate_and_execute_rules

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
            
            # Calculate unrealized P&L
            entry_premium = trade.get("short_call_premium", 0)
            current_option_value = greeks["option_value"]
            
            if trade["strategy_type"] == "covered_call":
                stock_pnl = (current_price - trade["entry_underlying_price"]) * 100 * trade["contracts"]
                option_pnl = (entry_premium - current_option_value) * 100 * trade["contracts"]
                unrealized_pnl = stock_pnl + option_pnl
            else:  # PMCC
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
        
        # Evaluate rules for all still-active trades
        logging.info("Evaluating trade management rules...")
        try:
            user_ids = list(set(t["user_id"] for t in active_trades))
            
            rules_triggered = 0
            for user_id in user_ids:
                user_rules = await db.simulator_rules.find(
                    {"user_id": user_id, "is_enabled": True},
                    {"_id": 0}
                ).to_list(100)
                
                if not user_rules:
                    continue
                
                user_active_trades = await db.simulator_trades.find(
                    {"user_id": user_id, "status": "active"},
                    {"_id": 0}
                ).to_list(1000)
                
                for trade in user_active_trades:
                    results = await evaluate_and_execute_rules(trade, user_rules, db)
                    for result in results:
                        if result.get("success"):
                            rules_triggered += 1
                            await db.simulator_rules.update_one(
                                {"id": result["rule_id"]},
                                {"$inc": {"times_triggered": 1}}
                            )
            
            logging.info(f"Rule evaluation complete: {rules_triggered} rules triggered")
            
        except Exception as rule_error:
            logging.error(f"Error evaluating rules: {rule_error}")
        
    except Exception as e:
        logging.error(f"Error in scheduled price update: {e}")


# Include all routers
# External routers (from routes/)
api_router.include_router(auth_router, prefix="/auth")
api_router.include_router(watchlist_router, prefix="/watchlist")
api_router.include_router(news_router, prefix="/news")
api_router.include_router(chatbot_router, prefix="/chatbot")
api_router.include_router(ai_router, prefix="/ai")
api_router.include_router(subscription_router, prefix="/subscription")
api_router.include_router(stocks_router, prefix="/stocks")
api_router.include_router(options_router, prefix="/options")
api_router.include_router(admin_router, prefix="/admin")
api_router.include_router(portfolio_router, prefix="/portfolio")
api_router.include_router(screener_router, prefix="/screener")
api_router.include_router(simulator_router, prefix="/simulator")
api_router.include_router(support_router)

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
    
    # Create simulator rules index
    await db.simulator_rules.create_index([("user_id", 1), ("is_enabled", 1)])
    await db.simulator_rules.create_index("id", unique=True)
    
    # Create cache index with TTL (auto-expire after 1 hour)
    await db.api_cache.create_index("cache_key", unique=True)
    await db.api_cache.create_index("cached_at", expireAfterSeconds=3600)  # Auto-delete after 1 hour
    
    # Create support ticket indexes
    await db.support_tickets.create_index("id", unique=True)
    await db.support_tickets.create_index("ticket_number", unique=True)
    await db.support_tickets.create_index([("status", 1), ("created_at", -1)])
    await db.support_tickets.create_index("user_email")
    await db.knowledge_base.create_index("id", unique=True)
    await db.knowledge_base.create_index([("category", 1), ("active", 1)])
    
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
    
    # Auto-response scheduler - runs every 5 minutes to check for eligible tickets
    async def process_support_auto_responses():
        """Process pending auto-responses for support tickets"""
        try:
            from services.support_service import SupportService
            service = SupportService(db)
            result = await service.process_pending_auto_responses()
            if result.get("processed", 0) > 0:
                logger.info(f"Support auto-response: processed {result['processed']} tickets")
        except Exception as e:
            logger.error(f"Support auto-response error: {e}")
    
    scheduler.add_job(
        process_support_auto_responses,
        'interval',
        minutes=5,
        id='support_auto_response',
        replace_existing=True
    )
    
    scheduler.start()
    logger.info("Schedulers started - Simulator: 4:30 PM ET weekdays, Support auto-response: every 5 min")

@app.on_event("shutdown")
async def shutdown_db_client():
    # Shutdown scheduler
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Simulator scheduler shut down")
    client.close()
