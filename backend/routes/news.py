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
                                # Compute sentiment from entity scores — MarketAux stores
                                # sentiment_score per entity (-1 to 1), not at article level
                                entities = n.get("entities", [])
                                scores = [
                                    e.get("sentiment_score")
                                    for e in entities
                                    if e.get("sentiment_score") is not None
                                ]
                                if scores:
                                    avg = sum(scores) / len(scores)
                                    if avg >= 0.15:
                                        sentiment_label = "positive"
                                    elif avg <= -0.15:
                                        sentiment_label = "negative"
                                    else:
                                        sentiment_label = "neutral"
                                    sentiment_score = round(avg, 4)
                                else:
                                    sentiment_label = None
                                    sentiment_score = None

                                filtered_news.append({
                                    "title": n.get("title"),
                                    "description": n.get("description"),
                                    "source": n.get("source"),
                                    "url": n.get("url"),
                                    "published_at": n.get("published_at"),
                                    "sentiment": sentiment_label,
                                    "sentiment_score": sentiment_score,
                                    "tickers": [e.get("symbol") for e in entities if e.get("symbol")],
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


from pydantic import BaseModel
from typing import List, Optional


class NewsItem(BaseModel):
    title: str
    description: Optional[str] = None


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
        return "Bullish", min(score, 85)
    elif ratio <= 0.4:
        score = int(45 - (1 - ratio) * 30)
        return "Bearish", max(score, 15)
    return "Neutral", 50


@news_router.post("/analyze-sentiment")
async def analyze_news_sentiment(
    news_items: List[NewsItem],
    user: dict = Depends(get_current_user)
):
    """Analyze sentiment of news articles.
    Uses OpenAI when configured, falls back to keyword-based analysis.
    """
    import os
    import json
    import re

    if not news_items:
        return {
            "sentiments": [],
            "overall_sentiment": "Neutral",
            "overall_score": 50
        }

    api_key = os.environ.get("OPENAI_API_KEY")

    # --- Keyword-based fallback (no API key needed) ---
    if not api_key:
        sentiments = []
        scores = []
        for i, item in enumerate(news_items[:5], 1):
            label, score = _keyword_sentiment(item.title, item.description or "")
            sentiments.append({"index": i, "sentiment": label, "confidence": "Medium"})
            scores.append(score)
        avg_score = int(sum(scores) / len(scores)) if scores else 50
        if avg_score >= 56:
            overall = "Bullish"
        elif avg_score <= 44:
            overall = "Bearish"
        else:
            overall = "Neutral"
        return {
            "sentiments": sentiments,
            "overall_sentiment": overall,
            "overall_score": avg_score
        }

    try:
        # Prepare news text for analysis
        news_text = ""
        for i, item in enumerate(news_items[:5], 1):  # Limit to 5 articles
            title = item.title
            desc = item.description or ""
            news_text += f"{i}. {title}\n{desc[:200] if desc else ''}\n\n"

        system_message = """You are a financial sentiment analyst. Analyze the sentiment of stock-related news articles.
For each article, provide:
1. Sentiment: Positive, Neutral, or Negative
2. Confidence: High, Medium, or Low

Then provide an overall sentiment score from 0-100 where:
- 0-30 = Very Bearish
- 31-45 = Bearish
- 46-55 = Neutral
- 56-70 = Bullish
- 71-100 = Very Bullish

Respond in JSON format ONLY:
{
  "articles": [
    {"index": 1, "sentiment": "Positive", "confidence": "High"},
    ...
  ],
  "overall_sentiment": "Bullish",
  "overall_score": 65,
  "summary": "Brief 1-sentence summary of overall sentiment"
}"""

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": system_message},
                        {"role": "user", "content": f"Analyze the sentiment of these news articles:\n\n{news_text}"}
                    ],
                    "temperature": 0.3,
                    "max_tokens": 500
                }
            )

        if response.status_code != 200:
            logging.error(f"OpenAI API error: {response.text}")
            return {"sentiments": [], "overall_sentiment": "Neutral", "overall_score": 50, "error": "AI call failed"}

        content = response.json()["choices"][0]["message"]["content"]

        # Extract JSON from response
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            result = json.loads(json_match.group())
            return {
                "sentiments": result.get("articles", []),
                "overall_sentiment": result.get("overall_sentiment", "Neutral"),
                "overall_score": result.get("overall_score", 50),
                "summary": result.get("summary", "")
            }

        return {
            "sentiments": [],
            "overall_sentiment": "Neutral",
            "overall_score": 50,
            "error": "Could not parse AI response"
        }

    except Exception as e:
        logging.error(f"Sentiment analysis error: {e}")
        return {
            "sentiments": [],
            "overall_sentiment": "Neutral",
            "overall_score": 50,
            "error": str(e)
        }
