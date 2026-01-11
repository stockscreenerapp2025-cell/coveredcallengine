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
        
        # PHASE 3: After price updates, evaluate rules for all still-active trades
        logging.info("Evaluating trade management rules...")
        try:
            # Get unique user IDs from active trades
            user_ids = list(set(t["user_id"] for t in active_trades if t.get("status") == "active" or t["id"] not in [at["id"] for at in active_trades if update_doc.get("status") in ["expired", "assigned"]]))
            
            rules_triggered = 0
            for user_id in user_ids:
                # Get user's enabled rules
                user_rules = await db.simulator_rules.find(
                    {"user_id": user_id, "is_enabled": True},
                    {"_id": 0}
                ).to_list(100)
                
                if not user_rules:
                    continue
                
                # Get user's still-active trades (need to re-fetch after updates)
                user_active_trades = await db.simulator_trades.find(
                    {"user_id": user_id, "status": "active"},
                    {"_id": 0}
                ).to_list(1000)
                
                for trade in user_active_trades:
                    results = await evaluate_and_execute_rules(trade, user_rules, db)
                    for result in results:
                        if result.get("success"):
                            rules_triggered += 1
                            # Update rule trigger count
                            await db.simulator_rules.update_one(
                                {"id": result["rule_id"]},
                                {"$inc": {"times_triggered": 1}}
                            )
            
            logging.info(f"Rule evaluation complete: {rules_triggered} rules triggered")
            
        except Exception as rule_error:
            logging.error(f"Error evaluating rules: {rule_error}")
        
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


# ==================== PHASE 4: ANALYTICS FEEDBACK LOOP ====================

@simulator_router.get("/analytics/performance")
async def get_performance_analytics(
    user: dict = Depends(get_current_user),
    strategy: Optional[str] = Query(None, description="Filter by strategy: covered_call, pmcc"),
    timeframe: str = Query("all", description="Timeframe: 7d, 30d, 90d, ytd, all")
):
    """
    Analyze simulator trade performance to identify winning patterns.
    Returns metrics by delta range, DTE, premium captured, symbol performance, etc.
    """
    
    # Build query
    query = {"user_id": user["id"], "status": {"$in": ["closed", "expired", "assigned"]}}
    if strategy:
        query["strategy_type"] = strategy
    
    # Apply timeframe filter
    if timeframe != "all":
        now = datetime.now(timezone.utc)
        if timeframe == "7d":
            cutoff = now - timedelta(days=7)
        elif timeframe == "30d":
            cutoff = now - timedelta(days=30)
        elif timeframe == "90d":
            cutoff = now - timedelta(days=90)
        elif timeframe == "ytd":
            cutoff = datetime(now.year, 1, 1, tzinfo=timezone.utc)
        else:
            cutoff = None
        
        if cutoff:
            query["created_at"] = {"$gte": cutoff.isoformat()}
    
    trades = await db.simulator_trades.find(query, {"_id": 0}).to_list(10000)
    
    if not trades:
        return {
            "message": "No closed trades found for analysis",
            "analytics": None,
            "recommendations": []
        }
    
    # Calculate overall metrics
    total_trades = len(trades)
    winning_trades = [t for t in trades if (t.get("final_pnl", 0) or 0) > 0]
    losing_trades = [t for t in trades if (t.get("final_pnl", 0) or 0) < 0]
    
    total_pnl = sum(t.get("final_pnl", 0) or 0 for t in trades)
    total_capital = sum(t.get("capital_deployed", 0) for t in trades)
    win_rate = (len(winning_trades) / total_trades * 100) if total_trades > 0 else 0
    avg_win = sum(t.get("final_pnl", 0) or 0 for t in winning_trades) / len(winning_trades) if winning_trades else 0
    avg_loss = sum(t.get("final_pnl", 0) or 0 for t in losing_trades) / len(losing_trades) if losing_trades else 0
    
    # Performance by Delta Range
    delta_ranges = {
        "0.10-0.20": {"min": 0.10, "max": 0.20, "trades": [], "wins": 0, "total_pnl": 0},
        "0.20-0.30": {"min": 0.20, "max": 0.30, "trades": [], "wins": 0, "total_pnl": 0},
        "0.30-0.40": {"min": 0.30, "max": 0.40, "trades": [], "wins": 0, "total_pnl": 0},
        "0.40-0.50": {"min": 0.40, "max": 0.50, "trades": [], "wins": 0, "total_pnl": 0},
        "0.50+": {"min": 0.50, "max": 1.0, "trades": [], "wins": 0, "total_pnl": 0}
    }
    
    for trade in trades:
        delta = trade.get("short_call_delta") or 0.30
        pnl = trade.get("final_pnl", 0) or 0
        
        for range_name, range_data in delta_ranges.items():
            if range_data["min"] <= delta < range_data["max"]:
                range_data["trades"].append(trade)
                range_data["total_pnl"] += pnl
                if pnl > 0:
                    range_data["wins"] += 1
                break
    
    delta_analysis = []
    for range_name, data in delta_ranges.items():
        count = len(data["trades"])
        if count > 0:
            delta_analysis.append({
                "range": range_name,
                "trade_count": count,
                "win_rate": round(data["wins"] / count * 100, 1),
                "total_pnl": round(data["total_pnl"], 2),
                "avg_pnl": round(data["total_pnl"] / count, 2)
            })
    
    # Performance by DTE Range
    dte_ranges = {
        "7d or less": {"min": 0, "max": 7, "trades": [], "wins": 0, "total_pnl": 0},
        "8-14d": {"min": 8, "max": 14, "trades": [], "wins": 0, "total_pnl": 0},
        "15-30d": {"min": 15, "max": 30, "trades": [], "wins": 0, "total_pnl": 0},
        "31-45d": {"min": 31, "max": 45, "trades": [], "wins": 0, "total_pnl": 0},
        "45d+": {"min": 46, "max": 365, "trades": [], "wins": 0, "total_pnl": 0}
    }
    
    for trade in trades:
        dte = trade.get("initial_dte", 30)
        pnl = trade.get("final_pnl", 0) or 0
        
        for range_name, range_data in dte_ranges.items():
            if range_data["min"] <= dte <= range_data["max"]:
                range_data["trades"].append(trade)
                range_data["total_pnl"] += pnl
                if pnl > 0:
                    range_data["wins"] += 1
                break
    
    dte_analysis = []
    for range_name, data in dte_ranges.items():
        count = len(data["trades"])
        if count > 0:
            dte_analysis.append({
                "range": range_name,
                "trade_count": count,
                "win_rate": round(data["wins"] / count * 100, 1),
                "total_pnl": round(data["total_pnl"], 2),
                "avg_pnl": round(data["total_pnl"] / count, 2)
            })
    
    # Performance by Symbol
    symbol_performance = {}
    for trade in trades:
        symbol = trade["symbol"]
        if symbol not in symbol_performance:
            symbol_performance[symbol] = {"trades": 0, "wins": 0, "total_pnl": 0, "capital": 0}
        
        symbol_performance[symbol]["trades"] += 1
        symbol_performance[symbol]["total_pnl"] += trade.get("final_pnl", 0) or 0
        symbol_performance[symbol]["capital"] += trade.get("capital_deployed", 0)
        if (trade.get("final_pnl", 0) or 0) > 0:
            symbol_performance[symbol]["wins"] += 1
    
    symbol_analysis = sorted([
        {
            "symbol": sym,
            "trade_count": data["trades"],
            "win_rate": round(data["wins"] / data["trades"] * 100, 1) if data["trades"] > 0 else 0,
            "total_pnl": round(data["total_pnl"], 2),
            "avg_pnl": round(data["total_pnl"] / data["trades"], 2) if data["trades"] > 0 else 0,
            "roi": round(data["total_pnl"] / data["capital"] * 100, 2) if data["capital"] > 0 else 0
        }
        for sym, data in symbol_performance.items()
    ], key=lambda x: x["total_pnl"], reverse=True)
    
    # Performance by Outcome Type
    outcome_analysis = {
        "expired_otm": {"count": 0, "total_pnl": 0},
        "assigned": {"count": 0, "total_pnl": 0},
        "early_close": {"count": 0, "total_pnl": 0},
        "rolled": {"count": 0, "total_pnl": 0},
        "rule_closed": {"count": 0, "total_pnl": 0},
        "other": {"count": 0, "total_pnl": 0}
    }
    
    for trade in trades:
        reason = trade.get("close_reason", "other") or "other"
        pnl = trade.get("final_pnl", 0) or 0
        
        if reason in outcome_analysis:
            outcome_analysis[reason]["count"] += 1
            outcome_analysis[reason]["total_pnl"] += pnl
        else:
            outcome_analysis["other"]["count"] += 1
            outcome_analysis["other"]["total_pnl"] += pnl
    
    outcomes = [
        {"outcome": k, "count": v["count"], "total_pnl": round(v["total_pnl"], 2), 
         "avg_pnl": round(v["total_pnl"] / v["count"], 2) if v["count"] > 0 else 0}
        for k, v in outcome_analysis.items() if v["count"] > 0
    ]
    
    # Generate recommendations
    recommendations = []
    
    # Find best performing delta range
    if delta_analysis:
        best_delta = max(delta_analysis, key=lambda x: x["win_rate"] if x["trade_count"] >= 3 else 0)
        if best_delta["trade_count"] >= 3 and best_delta["win_rate"] > win_rate:
            recommendations.append({
                "type": "delta_optimization",
                "priority": "high",
                "message": f"Delta range {best_delta['range']} has {best_delta['win_rate']}% win rate vs {win_rate:.1f}% overall",
                "suggestion": f"Consider focusing on delta {best_delta['range']} for better results",
                "data": best_delta
            })
    
    # Find best performing DTE range
    if dte_analysis:
        best_dte = max(dte_analysis, key=lambda x: x["win_rate"] if x["trade_count"] >= 3 else 0)
        if best_dte["trade_count"] >= 3 and best_dte["win_rate"] > win_rate:
            recommendations.append({
                "type": "dte_optimization",
                "priority": "high",
                "message": f"DTE range {best_dte['range']} has {best_dte['win_rate']}% win rate",
                "suggestion": f"Consider targeting {best_dte['range']} expiration cycles",
                "data": best_dte
            })
    
    # Identify underperforming symbols
    poor_symbols = [s for s in symbol_analysis if s["trade_count"] >= 2 and s["win_rate"] < 40]
    if poor_symbols:
        recommendations.append({
            "type": "symbol_warning",
            "priority": "medium",
            "message": f"{len(poor_symbols)} symbol(s) have win rate below 40%",
            "suggestion": f"Consider avoiding: {', '.join([s['symbol'] for s in poor_symbols[:5]])}",
            "data": poor_symbols[:5]
        })
    
    # Identify top performing symbols
    top_symbols = [s for s in symbol_analysis if s["trade_count"] >= 2 and s["win_rate"] >= 70]
    if top_symbols:
        recommendations.append({
            "type": "symbol_recommendation",
            "priority": "high",
            "message": f"{len(top_symbols)} symbol(s) have 70%+ win rate",
            "suggestion": f"Top performers: {', '.join([s['symbol'] for s in top_symbols[:5]])}",
            "data": top_symbols[:5]
        })
    
    # Assignment rate warning
    assigned = outcome_analysis["assigned"]["count"]
    if total_trades > 0 and assigned / total_trades > 0.30:
        recommendations.append({
            "type": "assignment_warning",
            "priority": "high",
            "message": f"High assignment rate: {assigned / total_trades * 100:.1f}%",
            "suggestion": "Consider selecting lower delta strikes or rolling earlier",
            "data": {"assigned_count": assigned, "rate": round(assigned / total_trades * 100, 1)}
        })
    
    return {
        "timeframe": timeframe,
        "strategy": strategy or "all",
        "analytics": {
            "overall": {
                "total_trades": total_trades,
                "win_rate": round(win_rate, 1),
                "total_pnl": round(total_pnl, 2),
                "total_capital": round(total_capital, 2),
                "roi": round(total_pnl / total_capital * 100, 2) if total_capital > 0 else 0,
                "avg_win": round(avg_win, 2),
                "avg_loss": round(avg_loss, 2),
                "profit_factor": round(abs(avg_win / avg_loss), 2) if avg_loss != 0 else 0
            },
            "by_delta": delta_analysis,
            "by_dte": dte_analysis,
            "by_symbol": symbol_analysis[:15],  # Top 15
            "by_outcome": outcomes
        },
        "recommendations": recommendations
    }


@simulator_router.get("/analytics/scanner-comparison")
async def compare_scanner_parameters(
    user: dict = Depends(get_current_user)
):
    """
    Compare performance of trades that came from different scanner parameter sets.
    Helps identify which scanner configurations produce the best results.
    """
    
    # Get all closed trades with scan parameters
    trades = await db.simulator_trades.find(
        {
            "user_id": user["id"],
            "status": {"$in": ["closed", "expired", "assigned"]},
            "scan_parameters": {"$exists": True, "$ne": None}
        },
        {"_id": 0}
    ).to_list(10000)
    
    if not trades:
        return {
            "message": "No trades with scan parameters found. Add trades from screener to track parameter performance.",
            "comparisons": []
        }
    
    # Group by scan parameter configurations
    param_groups = {}
    
    for trade in trades:
        params = trade.get("scan_parameters", {})
        if not params:
            continue
        
        # Create a key from key parameters
        key_params = {
            "min_roi": params.get("min_roi"),
            "min_delta": params.get("min_delta"),
            "max_delta": params.get("max_delta"),
            "max_dte": params.get("max_dte")
        }
        
        # Skip if no meaningful params
        if all(v is None for v in key_params.values()):
            continue
        
        param_key = json.dumps(key_params, sort_keys=True)
        
        if param_key not in param_groups:
            param_groups[param_key] = {
                "params": key_params,
                "trades": [],
                "wins": 0,
                "total_pnl": 0,
                "capital": 0
            }
        
        pnl = trade.get("final_pnl", 0) or 0
        param_groups[param_key]["trades"].append(trade)
        param_groups[param_key]["total_pnl"] += pnl
        param_groups[param_key]["capital"] += trade.get("capital_deployed", 0)
        if pnl > 0:
            param_groups[param_key]["wins"] += 1
    
    # Convert to sorted list
    comparisons = []
    for key, data in param_groups.items():
        count = len(data["trades"])
        if count >= 2:  # Only show configs with at least 2 trades
            comparisons.append({
                "parameters": data["params"],
                "trade_count": count,
                "win_rate": round(data["wins"] / count * 100, 1),
                "total_pnl": round(data["total_pnl"], 2),
                "avg_pnl": round(data["total_pnl"] / count, 2),
                "roi": round(data["total_pnl"] / data["capital"] * 100, 2) if data["capital"] > 0 else 0
            })
    
    # Sort by ROI
    comparisons.sort(key=lambda x: x["roi"], reverse=True)
    
    # Generate optimal parameters recommendation
    optimal_params = None
    if comparisons:
        best = comparisons[0]
        if best["win_rate"] >= 50 and best["roi"] > 0:
            optimal_params = {
                "recommendation": "Based on your trading history, these parameters perform best:",
                "parameters": best["parameters"],
                "expected_win_rate": best["win_rate"],
                "expected_roi": best["roi"],
                "sample_size": best["trade_count"]
            }
    
    return {
        "total_configurations": len(comparisons),
        "comparisons": comparisons[:10],  # Top 10
        "optimal_parameters": optimal_params
    }


@simulator_router.get("/analytics/optimal-settings")
async def get_optimal_scanner_settings(
    user: dict = Depends(get_current_user),
    strategy: str = Query("covered_call", description="Strategy: covered_call or pmcc"),
    confidence_threshold: int = Query(5, ge=3, description="Minimum trades needed for recommendation")
):
    """
    Analyze closed trades and recommend optimal scanner settings.
    Returns suggested min_delta, max_delta, max_dte, and symbols based on historical performance.
    """
    
    # Get closed trades
    trades = await db.simulator_trades.find(
        {
            "user_id": user["id"],
            "strategy_type": strategy,
            "status": {"$in": ["closed", "expired", "assigned"]}
        },
        {"_id": 0}
    ).to_list(10000)
    
    if len(trades) < confidence_threshold:
        return {
            "message": f"Need at least {confidence_threshold} closed trades for reliable recommendations. Currently have {len(trades)}.",
            "optimal_settings": None,
            "confidence": "low"
        }
    
    # Analyze winning trades specifically
    winning_trades = [t for t in trades if (t.get("final_pnl", 0) or 0) > 0]
    
    if len(winning_trades) < 3:
        return {
            "message": "Not enough winning trades to determine optimal settings",
            "optimal_settings": None,
            "confidence": "low"
        }
    
    # Calculate optimal delta range from winners
    winning_deltas = [t.get("short_call_delta", 0.30) for t in winning_trades if t.get("short_call_delta")]
    if winning_deltas:
        avg_winning_delta = sum(winning_deltas) / len(winning_deltas)
        delta_std = (sum((d - avg_winning_delta) ** 2 for d in winning_deltas) / len(winning_deltas)) ** 0.5
        optimal_min_delta = max(0.10, round(avg_winning_delta - delta_std, 2))
        optimal_max_delta = min(0.50, round(avg_winning_delta + delta_std, 2))
    else:
        optimal_min_delta = 0.20
        optimal_max_delta = 0.40
    
    # Calculate optimal DTE from winners
    winning_dtes = [t.get("initial_dte", 30) for t in winning_trades]
    avg_winning_dte = sum(winning_dtes) / len(winning_dtes) if winning_dtes else 30
    optimal_max_dte = min(60, max(14, round(avg_winning_dte * 1.2)))  # Add 20% buffer
    
    # Find best performing symbols
    symbol_stats = {}
    for trade in trades:
        symbol = trade["symbol"]
        pnl = trade.get("final_pnl", 0) or 0
        
        if symbol not in symbol_stats:
            symbol_stats[symbol] = {"wins": 0, "total": 0, "pnl": 0}
        
        symbol_stats[symbol]["total"] += 1
        symbol_stats[symbol]["pnl"] += pnl
        if pnl > 0:
            symbol_stats[symbol]["wins"] += 1
    
    # Sort symbols by win rate (minimum 2 trades)
    recommended_symbols = sorted([
        {"symbol": s, "win_rate": d["wins"] / d["total"] * 100, "trades": d["total"], "total_pnl": d["pnl"]}
        for s, d in symbol_stats.items() if d["total"] >= 2
    ], key=lambda x: (x["win_rate"], x["total_pnl"]), reverse=True)
    
    # Symbols to avoid
    avoid_symbols = [s for s in recommended_symbols if s["win_rate"] < 40 and s["trades"] >= 2]
    top_symbols = [s for s in recommended_symbols if s["win_rate"] >= 60][:10]
    
    # Determine confidence level
    total_trades = len(trades)
    if total_trades >= 50:
        confidence = "high"
    elif total_trades >= 20:
        confidence = "medium"
    else:
        confidence = "low"
    
    # Calculate expected performance with optimal settings
    trades_matching_optimal = [
        t for t in winning_trades
        if optimal_min_delta <= (t.get("short_call_delta") or 0.30) <= optimal_max_delta
        and (t.get("initial_dte") or 30) <= optimal_max_dte
    ]
    
    expected_win_rate = len(winning_trades) / len(trades) * 100 if trades else 0
    
    return {
        "strategy": strategy,
        "sample_size": total_trades,
        "winning_trades": len(winning_trades),
        "confidence": confidence,
        "optimal_settings": {
            "min_delta": optimal_min_delta,
            "max_delta": optimal_max_delta,
            "max_dte": optimal_max_dte,
            "expected_win_rate": round(expected_win_rate, 1),
            "reasoning": {
                "delta": f"Winners averaged {avg_winning_delta:.2f} delta",
                "dte": f"Winners averaged {avg_winning_dte:.0f} DTE"
            }
        },
        "symbol_recommendations": {
            "top_performers": top_symbols[:5],
            "avoid": [s["symbol"] for s in avoid_symbols[:5]]
        },
        "apply_url": f"/screener/covered-calls?min_delta={optimal_min_delta}&max_delta={optimal_max_delta}&max_dte={optimal_max_dte}"
    }


@simulator_router.post("/analytics/save-profile")
async def save_scanner_profile(
    profile_name: str = Query(..., description="Name for this scanner profile"),
    user: dict = Depends(get_current_user)
):
    """
    Save current optimal settings as a named scanner profile for future use.
    """
    
    # Get optimal settings
    optimal = await get_optimal_scanner_settings(user, strategy="covered_call")
    
    if not optimal.get("optimal_settings"):
        raise HTTPException(status_code=400, detail="Not enough data to create profile")
    
    profile_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    
    profile_doc = {
        "id": profile_id,
        "user_id": user["id"],
        "name": profile_name,
        "settings": optimal["optimal_settings"],
        "sample_size": optimal["sample_size"],
        "confidence": optimal["confidence"],
        "created_at": now.isoformat(),
        "performance_at_creation": {
            "expected_win_rate": optimal["optimal_settings"]["expected_win_rate"],
            "winning_trades": optimal["winning_trades"]
        }
    }
    
    await db.scanner_profiles.insert_one(profile_doc)
    
    if "_id" in profile_doc:
        del profile_doc["_id"]
    
    return {"message": "Profile saved", "profile": profile_doc}


@simulator_router.get("/analytics/profiles")
async def get_scanner_profiles(user: dict = Depends(get_current_user)):
    """Get all saved scanner profiles for the user"""
    
    profiles = await db.scanner_profiles.find(
        {"user_id": user["id"]},
        {"_id": 0}
    ).sort("created_at", -1).to_list(50)
    
    return {"profiles": profiles}


@simulator_router.delete("/analytics/profiles/{profile_id}")
async def delete_scanner_profile(profile_id: str, user: dict = Depends(get_current_user)):
    """Delete a scanner profile"""
    
    result = await db.scanner_profiles.delete_one({"id": profile_id, "user_id": user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Profile not found")
    
    return {"message": "Profile deleted"}


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

# Internal routers (still in server.py - to be refactored)
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
    
    # Create simulator rules index
    await db.simulator_rules.create_index([("user_id", 1), ("is_enabled", 1)])
    await db.simulator_rules.create_index("id", unique=True)
    
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
