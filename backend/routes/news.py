"""
News routes
"""
from fastapi import APIRouter, Depends, Query
from typing import Optional
from datetime import datetime, timezone
import logging
import httpx

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import db
from utils.auth import get_current_user
from services.cache import (
    get_cached_data, set_cached_data, get_last_trading_day_data, is_market_closed
)

news_router = APIRouter(tags=["News"])

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
    
    # Require at least 1 keyword match for general financial relevance
    return keyword_matches >= 1


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


async def get_marketaux_client():
    """Get MarketAux API token from admin settings"""
    settings = await db.admin_settings.find_one({"_id": "settings"}, {"_id": 0})
    if settings:
        return settings.get("marketaux_api_token")
    return None


@news_router.get("/")
async def get_market_news(
    symbol: Optional[str] = None,
    limit: int = Query(10, ge=1, le=50),
    user: dict = Depends(get_current_user)
):
    """Get market news, optionally filtered by symbol"""
    # Import mock data here to avoid circular dependency
    from server import MOCK_NEWS
    
    # Generate cache key for news
    cache_key = f"market_news_v4_{symbol or 'general'}_{limit}"
    
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
                request_limit = min(limit * 5, 50)  # Request 5x to account for filtering
                
                params = {
                    "api_token": marketaux_token,
                    "limit": request_limit,
                    "language": "en",
                    "filter_entities": "true"  # Get entity data for better filtering
                }
                
                # If specific symbol requested, filter to that symbol
                if symbol:
                    params["symbols"] = symbol.upper()
                # For general news, do NOT restrict to specific symbols —
                # MarketAux only returns articles that exist for those symbols,
                # which can be fewer than `limit`. Instead, fetch general
                # financial news and let is_relevant_news() filter locally.
                
                response = await client.get(
                    "https://api.marketaux.com/v1/news/all",
                    params=params
                )
                
                # Increment counter after successful request
                await increment_marketaux_counter()
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("data"):
                        def _parse_article(n):
                            entities = n.get("entities", [])
                            scores = [e.get("sentiment_score") for e in entities if e.get("sentiment_score") is not None]
                            if scores:
                                avg = sum(scores) / len(scores)
                                sentiment_label = "positive" if avg >= 0.15 else ("negative" if avg <= -0.15 else "neutral")
                                sentiment_score = round(avg, 4)
                            else:
                                sentiment_label = "neutral"
                                sentiment_score = None
                            return {
                                "title": n.get("title"),
                                "description": n.get("description"),
                                "source": n.get("source"),
                                "url": n.get("url"),
                                "published_at": n.get("published_at"),
                                "sentiment": sentiment_label,
                                "sentiment_score": sentiment_score,
                                "tickers": [e.get("symbol") for e in entities if e.get("symbol")],
                                "is_live": True
                            }

                        # Pass 1: strict filter (tracked symbols + keywords)
                        filtered_news = []
                        fallback_pool = []
                        for n in data["data"]:
                            if is_relevant_news(n):
                                filtered_news.append(_parse_article(n))
                                if len(filtered_news) >= limit:
                                    break
                            elif not any(src in (n.get("source") or "").lower() for src in ['entertainment', 'sports', 'celebrity', 'lifestyle']):
                                fallback_pool.append(_parse_article(n))

                        # Pass 2: fill up to limit with any non-irrelevant article
                        if len(filtered_news) < limit:
                            needed = limit - len(filtered_news)
                            filtered_news.extend(fallback_pool[:needed])

                        # Pass 3: still not enough? pad with mock news so we always hit limit
                        if len(filtered_news) < limit:
                            existing_titles = {a["title"] for a in filtered_news}
                            for mock in MOCK_NEWS:
                                if len(filtered_news) >= limit:
                                    break
                                if mock["title"] not in existing_titles:
                                    filtered_news.append(mock)

                        if filtered_news:
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


from pydantic import BaseModel
from typing import List, Optional


class NewsItem(BaseModel):
    title: str
    description: Optional[str] = None
    sentiment: Optional[str] = None        # "positive" / "negative" / "neutral" from MarketAux
    sentiment_score: Optional[float] = None  # raw MarketAux score (-1 to 1)


POSITIVE_WORDS = [
    'surge', 'soar', 'jump', 'rally', 'gain', 'rise', 'up', 'high', 'record', 'beat',
    'exceed', 'strong', 'growth', 'profit', 'revenue', 'upgrade', 'buy', 'outperform',
    'bullish', 'positive', 'boost', 'opportunity', 'success', 'increase', 'expand',
    'target raised', 'price target', 'earnings beat', 'better than expected', 'breakout'
]

NEGATIVE_WORDS = [
    'fall', 'drop', 'decline', 'plunge', 'crash', 'lose', 'loss', 'down', 'low',
    'miss', 'weak', 'concern', 'risk', 'warning', 'cut', 'downgrade', 'sell',
    'underperform', 'bearish', 'negative', 'lawsuit', 'investigation', 'fraud',
    'layoff', 'miss', 'below', 'disappointing', 'worse than expected', 'debt'
]


def _keyword_sentiment(title: str, description: str) -> tuple:
    """Simple keyword-based sentiment scoring. Returns (label, score 0-100)."""
    text = (title + " " + (description or "")).lower()
    pos = sum(1 for w in POSITIVE_WORDS if w in text)
    neg = sum(1 for w in NEGATIVE_WORDS if w in text)
    total = pos + neg
    if total == 0:
        return "Neutral", 50
    ratio = pos / total
    if ratio >= 0.6:
        score = int(55 + ratio * 30)
        return "Positive", min(score, 85)
    elif ratio <= 0.4:
        score = int(45 - (1 - ratio) * 30)
        return "Negative", max(score, 15)
    return "Neutral", 50


def _score_label(avg: float) -> str:
    if avg >= 54:
        return "Positive"
    if avg <= 46:
        return "Negative"
    return "Neutral"


def _marketaux_to_score(raw: float) -> int:
    """Convert MarketAux sentiment_score (-1..1) to 0-100 scale."""
    return max(0, min(100, int(50 + raw * 50)))


@news_router.post("/analyze-sentiment")
async def analyze_news_sentiment(
    news_items: List[NewsItem],
    user: dict = Depends(get_current_user)
):
    """Analyze sentiment. Priority: MarketAux scores → keyword analysis → Gemini AI."""
    import os, json, re

    if not news_items:
        return {"sentiments": [], "overall_sentiment": "Neutral", "overall_score": 50}

    # ── Tier 1: use MarketAux sentiment scores already embedded in the news items ──
    marketaux_items = [it for it in news_items[:5] if it.sentiment_score is not None]
    if marketaux_items:
        sentiments = []
        scores = []
        for i, item in enumerate(marketaux_items, 1):
            score = _marketaux_to_score(item.sentiment_score)
            label = _score_label(score)
            sentiments.append({"index": i, "sentiment": label, "confidence": "High"})
            scores.append(score)
        avg_score = int(sum(scores) / len(scores))
        return {
            "sentiments": sentiments,
            "overall_sentiment": _score_label(avg_score),
            "overall_score": avg_score,
        }

    # ── Tier 2: keyword analysis (no API key needed, always works) ──
    def _keyword_fallback(items):
        sentiments, scores = [], []
        for i, item in enumerate(items[:5], 1):
            label, score = _keyword_sentiment(item.title, item.description or "")
            sentiments.append({"index": i, "sentiment": label, "confidence": "Medium"})
            scores.append(score)
        if not scores:
            return {"sentiments": [], "overall_sentiment": "Neutral", "overall_score": 50}
        most_bullish, most_bearish = max(scores), min(scores)
        extreme = most_bullish if abs(most_bullish - 50) >= abs(most_bearish - 50) else most_bearish
        avg = int(sum(scores + [extreme, extreme]) / (len(scores) + 2))
        return {"sentiments": sentiments, "overall_sentiment": _score_label(avg), "overall_score": avg}

    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        return _keyword_fallback(news_items)

    # ── Tier 3: Gemini AI (best quality, optional) ──
    try:
        news_text = "".join(
            f"{i}. {item.title}\n{(item.description or '')[:200]}\n\n"
            for i, item in enumerate(news_items[:5], 1)
        )
        prompt = (
            "You are a financial sentiment analyst. Analyze these news articles and respond in JSON ONLY:\n"
            '{"articles":[{"index":1,"sentiment":"Positive","confidence":"High"}],'
            '"overall_sentiment":"Positive","overall_score":65,'
            '"summary":"one sentence"}\n\n'
            "Use only these sentiment labels: Positive, Neutral, Negative\n"
            "Score scale: 0-30=Very Negative, 31-45=Negative, 46-55=Neutral, 56-70=Positive, 71-100=Very Positive\n\n"
            + news_text
        )
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}",
                headers={"Content-Type": "application/json"},
                json={"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                      "generationConfig": {"temperature": 0.3, "maxOutputTokens": 400}},
            )
        if resp.status_code == 200:
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            m = re.search(r'\{[\s\S]*\}', text)
            if m:
                result = json.loads(m.group())
                return {
                    "sentiments": result.get("articles", []),
                    "overall_sentiment": result.get("overall_sentiment", "Neutral"),
                    "overall_score": result.get("overall_score", 50),
                    "summary": result.get("summary", ""),
                }
        logging.warning(f"Gemini fallback triggered: status={resp.status_code}")
    except Exception as e:
        logging.error(f"Gemini sentiment error: {e}")

    return _keyword_fallback(news_items)
