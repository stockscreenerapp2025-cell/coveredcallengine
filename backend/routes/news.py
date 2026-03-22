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


# Sentiment keywords (Tier 2)
POSITIVE_KEYWORDS = [
    'upgrade', 'beats earnings', 'strong guidance', 'record revenue', 'growth',
    'partnership', 'buyback', 'expansion', 'ai adoption', 'contract win',
    'surge', 'soar', 'jump', 'rally', 'gain', 'outperform', 'profit',
    'revenue beat', 'better than expected', 'breakout', 'price target raised',
    'strong buy', 'record high', 'market share', 'dividend increase',
]
NEGATIVE_KEYWORDS = [
    'downgrade', 'miss earnings', 'lawsuit', 'bankruptcy', 'investigation',
    'recall', 'guidance cut', 'layoffs', 'regulation risk',
    'fall', 'plunge', 'crash', 'loss', 'weak', 'miss', 'below expectations',
    'disappointing', 'debt', 'fraud', 'warning', 'concern', 'underperform',
    'sell rating', 'price target cut', 'market share loss',
]


def _sentiment_label(score: float) -> str:
    if score >= 0.20:
        return 'Positive'
    if score <= -0.20:
        return 'Negative'
    return 'Neutral'


def _score_to_display(score: float) -> int:
    return max(0, min(100, int(50 + score * 50)))


def _marketaux_weighted_score(items) -> float:
    import math as _m
    weighted_sum, total_weight = 0.0, 0.0
    for item in items:
        if item.sentiment_score is None:
            continue
        raw = max(-1.0, min(1.0, float(item.sentiment_score)))
        if raw >= 0.6:
            mapped = 0.8
        elif raw >= 0.2:
            mapped = 0.5
        elif raw >= 0.1:
            mapped = 0.25
        elif raw >= -0.1:
            mapped = 0.0
        elif raw >= -0.2:
            mapped = -0.25
        elif raw >= -0.6:
            mapped = -0.5
        else:
            mapped = -0.8
        weighted_sum += mapped
        total_weight += 1.0
    if total_weight == 0:
        return 0.0
    avg = weighted_sum / total_weight
    volume_factor = _m.log(len(items) + 1) / _m.log(6)
    return max(-1.0, min(1.0, avg * volume_factor + avg * (1 - volume_factor)))


def _keyword_score(title: str, description: str) -> float:
    text = (title + ' ' + (description or '')).lower()
    score = 0.0
    for kw in POSITIVE_KEYWORDS:
        if kw in text:
            score += 0.1
    for kw in NEGATIVE_KEYWORDS:
        if kw in text:
            score -= 0.1
    return max(-0.6, min(0.6, score))


@news_router.post('/analyze-sentiment')
async def analyze_news_sentiment(
    news_items: List[NewsItem],
    user: dict = Depends(get_current_user)
):
    import os, json, re, math

    if not news_items:
        return {'sentiments': [], 'overall_sentiment': 'Neutral',
                'sentiment_score': 0.0, 'overall_score': 50,
                'confidence': 0.0, 'source': 'none'}

    # Tier 1: MarketAux
    ma_items = [it for it in news_items if it.sentiment_score is not None]
    if ma_items:
        score = _marketaux_weighted_score(ma_items)
        label = _sentiment_label(score)
        confidence = round(min(0.95, 0.5 + abs(score) * 0.5), 2)
        per_article = []
        for i, item in enumerate(ma_items[:5], 1):
            art_raw = max(-1.0, min(1.0, float(item.sentiment_score)))
            per_article.append({'index': i, 'sentiment': _sentiment_label(art_raw),
                                 'score': round(art_raw, 2), 'confidence': 'High'})
        return {'sentiments': per_article, 'overall_sentiment': label,
                'sentiment_score': round(score, 2), 'overall_score': _score_to_display(score),
                'confidence': confidence, 'source': 'MarketAux'}

    def _keyword_fallback(items):
        scores, per_article = [], []
        for i, item in enumerate(items[:5], 1):
            s = _keyword_score(item.title, item.description or '')
            scores.append(s)
            per_article.append({'index': i, 'sentiment': _sentiment_label(s),
                                 'score': round(s, 2), 'confidence': 'Medium'})
        avg = (sum(scores) / len(scores)) if scores else 0.0
        avg = max(-0.6, min(0.6, avg))
        return {'sentiments': per_article, 'overall_sentiment': _sentiment_label(avg),
                'sentiment_score': round(avg, 2), 'overall_score': _score_to_display(avg),
                'confidence': round(0.3 + abs(avg) * 0.3, 2), 'source': 'Keyword'}

    gemini_key = os.environ.get('GEMINI_API_KEY')
    if not gemini_key:
        return _keyword_fallback(news_items)

    # Tier 3: Gemini (only when keyword signal is weak)
    kw_scores = [_keyword_score(it.title, it.description or '') for it in news_items[:5]]
    kw_avg = sum(kw_scores) / len(kw_scores) if kw_scores else 0.0
    if abs(kw_avg) >= 0.2:
        return _keyword_fallback(news_items)

    try:
        news_text = ''.join(
            f"{i}. {item.title}\n{(item.description or '')[:200]}\n\n"
            for i, item in enumerate(news_items[:5], 1)
        )
        prompt = (
            'You are a financial sentiment analyst. Analyze these headlines.\n'
            'Respond in JSON ONLY (no markdown):\n'
            '{"articles":[{"index":1,"sentiment":"Positive","confidence_score":0.8}],'
            '"overall_sentiment":"Positive","overall_score":0.62,"summary":"one sentence"}\n\n'
            'sentiment: Positive | Neutral | Negative\n'
            'overall_score: -1.0 to +1.0\n\n'
            + news_text
        )
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}",
                headers={'Content-Type': 'application/json'},
                json={'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
                      'generationConfig': {'temperature': 0.2, 'maxOutputTokens': 400}},
            )
        if resp.status_code == 200:
            text = resp.json()['candidates'][0]['content']['parts'][0]['text']
            m = re.search(r'\{[\s\S]*\}', text)
            if m:
                result = json.loads(m.group())
                raw = float(result.get('overall_score', 0))
                raw = max(-1.0, min(1.0, raw))
                per_article = []
                for art in result.get('articles', []):
                    conf = float(art.get('confidence_score', 0.7))
                    lbl = art.get('sentiment', 'Neutral')
                    gem_s = (0.6 * conf) if lbl == 'Positive' else (-0.6 * conf if lbl == 'Negative' else 0.0)
                    per_article.append({'index': art.get('index'), 'sentiment': lbl,
                                        'score': round(gem_s, 2), 'confidence': round(conf, 2)})
                return {'sentiments': per_article, 'overall_sentiment': _sentiment_label(raw),
                        'sentiment_score': round(raw, 2), 'overall_score': _score_to_display(raw),
                        'confidence': round(min(0.9, 0.5 + abs(raw) * 0.4), 2),
                        'source': 'Gemini', 'summary': result.get('summary', '')}
        logging.warning(f'Gemini sentiment fallback: status={resp.status_code}')
    except Exception as e:
        logging.error(f'Gemini sentiment error: {e}')

    return _keyword_fallback(news_items)
