"""
Market Bias Module - Phase 6
Calculates market sentiment and applies bias weights to trade scores.

PHASE 6 RULES:
- Market bias is applied AFTER eligibility filtering
- Bias weight adjusts the final score, not the eligibility
- Bullish bias favors higher delta (closer to ATM)
- Bearish bias favors lower delta (more OTM protection)
- Neutral bias applies no adjustment

Flow:
1. Validate option chain and structure → eligible_trades
2. Apply market_bias_weight to each eligible trade
3. Calculate final_score = base_score * bias_multiplier
4. Sort by final_score
"""
import logging
import httpx
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
import os

# Cache for market bias (avoid repeated API calls)
_bias_cache: Dict[str, Tuple[dict, datetime]] = {}
BIAS_CACHE_TTL = timedelta(minutes=15)

# Market bias thresholds
BULLISH_THRESHOLD = 0.6   # VIX < 18 or positive momentum
BEARISH_THRESHOLD = 0.4   # VIX > 25 or negative momentum
NEUTRAL_LOW = 0.4
NEUTRAL_HIGH = 0.6


def get_market_bias_weight(sentiment_score: float, strategy: str = "cc") -> float:
    """
    Calculate the market bias weight based on sentiment score.
    
    Args:
        sentiment_score: 0.0 (bearish) to 1.0 (bullish)
        strategy: "cc" for covered call, "pmcc" for poor man's covered call
    
    Returns:
        Multiplier for score adjustment (0.8 to 1.2)
    """
    if sentiment_score >= BULLISH_THRESHOLD:
        # Bullish: Favor higher premium (higher delta) strategies
        # CC: Slightly boost scores (market going up = premium capture likely)
        # PMCC: Boost scores more (LEAPS will appreciate)
        if strategy == "pmcc":
            return 1.15 + (sentiment_score - BULLISH_THRESHOLD) * 0.25
        return 1.10 + (sentiment_score - BULLISH_THRESHOLD) * 0.20
    
    elif sentiment_score <= BEARISH_THRESHOLD:
        # Bearish: Favor protective strategies (lower delta, more OTM)
        # CC: Reduce scores slightly (stock may drop, premium less valuable)
        # PMCC: Reduce more (LEAPS at risk)
        if strategy == "pmcc":
            return 0.85 - (BEARISH_THRESHOLD - sentiment_score) * 0.25
        return 0.90 - (BEARISH_THRESHOLD - sentiment_score) * 0.20
    
    else:
        # Neutral: No adjustment
        return 1.0


async def fetch_market_sentiment() -> Dict:
    """
    Fetch market sentiment indicators.
    Uses VIX, market breadth, and momentum indicators.
    
    Returns:
        Dict with sentiment_score (0-1) and components
    """
    cache_key = "market_sentiment"
    
    # Check cache
    if cache_key in _bias_cache:
        cached_data, cached_time = _bias_cache[cache_key]
        if datetime.now() - cached_time < BIAS_CACHE_TTL:
            return cached_data
    
    try:
        # Default neutral sentiment if we can't fetch data
        sentiment_data = {
            "sentiment_score": 0.5,
            "vix_level": None,
            "market_trend": "neutral",
            "bias": "neutral",
            "weight_cc": 1.0,
            "weight_pmcc": 1.0,
            "source": "default",
            "timestamp": datetime.now().isoformat()
        }
        
        # Try to fetch VIX data using yfinance
        try:
            import yfinance as yf
            
            vix = yf.Ticker("^VIX")
            vix_hist = vix.history(period="5d")
            
            if not vix_hist.empty:
                current_vix = vix_hist["Close"].iloc[-1]
                vix_5d_avg = vix_hist["Close"].mean()
                
                # VIX-based sentiment:
                # VIX < 15: Very bullish (0.8-1.0)
                # VIX 15-20: Bullish (0.6-0.8)
                # VIX 20-25: Neutral (0.4-0.6)
                # VIX 25-30: Bearish (0.2-0.4)
                # VIX > 30: Very bearish (0.0-0.2)
                if current_vix < 15:
                    vix_sentiment = 0.9
                elif current_vix < 20:
                    vix_sentiment = 0.7
                elif current_vix < 25:
                    vix_sentiment = 0.5
                elif current_vix < 30:
                    vix_sentiment = 0.3
                else:
                    vix_sentiment = 0.15
                
                # Adjust for VIX trend (rising VIX = more bearish)
                if current_vix > vix_5d_avg * 1.1:
                    vix_sentiment -= 0.1  # VIX rising fast
                elif current_vix < vix_5d_avg * 0.9:
                    vix_sentiment += 0.1  # VIX falling fast
                
                vix_sentiment = max(0.0, min(1.0, vix_sentiment))
                
                sentiment_data["vix_level"] = round(current_vix, 2)
                sentiment_data["vix_5d_avg"] = round(vix_5d_avg, 2)
                sentiment_data["sentiment_score"] = round(vix_sentiment, 2)
                sentiment_data["source"] = "vix"
                
        except Exception as vix_error:
            logging.warning(f"Could not fetch VIX data: {vix_error}")
        
        # Try to add SPY momentum as secondary indicator
        try:
            import yfinance as yf
            
            spy = yf.Ticker("SPY")
            spy_hist = spy.history(period="20d")
            
            if len(spy_hist) >= 10:
                current_price = spy_hist["Close"].iloc[-1]
                price_10d_ago = spy_hist["Close"].iloc[-10]
                sma_20 = spy_hist["Close"].mean()
                
                # Calculate momentum
                momentum_pct = ((current_price - price_10d_ago) / price_10d_ago) * 100
                above_sma = current_price > sma_20
                
                # Momentum-based adjustment
                if momentum_pct > 3 and above_sma:
                    momentum_sentiment = 0.8
                elif momentum_pct > 0 and above_sma:
                    momentum_sentiment = 0.65
                elif momentum_pct < -3 and not above_sma:
                    momentum_sentiment = 0.2
                elif momentum_pct < 0 and not above_sma:
                    momentum_sentiment = 0.35
                else:
                    momentum_sentiment = 0.5
                
                # Blend VIX and momentum (70% VIX, 30% momentum)
                blended_sentiment = sentiment_data["sentiment_score"] * 0.7 + momentum_sentiment * 0.3
                sentiment_data["sentiment_score"] = round(blended_sentiment, 2)
                sentiment_data["spy_momentum_pct"] = round(momentum_pct, 2)
                sentiment_data["spy_above_sma20"] = above_sma
                sentiment_data["source"] = "vix+momentum"
                
        except Exception as spy_error:
            logging.warning(f"Could not fetch SPY data: {spy_error}")
        
        # Determine bias label
        score = sentiment_data["sentiment_score"]
        if score >= BULLISH_THRESHOLD:
            sentiment_data["bias"] = "bullish"
            sentiment_data["market_trend"] = "up"
        elif score <= BEARISH_THRESHOLD:
            sentiment_data["bias"] = "bearish"
            sentiment_data["market_trend"] = "down"
        else:
            sentiment_data["bias"] = "neutral"
            sentiment_data["market_trend"] = "sideways"
        
        # Calculate weights for each strategy
        sentiment_data["weight_cc"] = round(get_market_bias_weight(score, "cc"), 3)
        sentiment_data["weight_pmcc"] = round(get_market_bias_weight(score, "pmcc"), 3)
        
        # Cache the result
        _bias_cache[cache_key] = (sentiment_data, datetime.now())
        
        logging.info(f"Market bias: {sentiment_data['bias']} (score={score:.2f}, VIX={sentiment_data.get('vix_level', 'N/A')})")
        return sentiment_data
        
    except Exception as e:
        logging.error(f"Error fetching market sentiment: {e}")
        return {
            "sentiment_score": 0.5,
            "bias": "neutral",
            "weight_cc": 1.0,
            "weight_pmcc": 1.0,
            "source": "error_fallback",
            "error": str(e)
        }


def apply_bias_to_score(base_score: float, bias_weight: float, delta: float = 0.3) -> float:
    """
    Apply market bias weight to a trade's base score.
    
    Args:
        base_score: The original score calculated from ROI, delta, etc.
        bias_weight: The market bias multiplier (0.8-1.2)
        delta: The option's delta (used for additional adjustment)
    
    Returns:
        Bias-adjusted final score
    """
    # Base adjustment from market bias
    adjusted_score = base_score * bias_weight
    
    # Additional delta-based adjustment:
    # In bullish markets, slightly favor higher delta (more aggressive)
    # In bearish markets, slightly favor lower delta (more protective)
    if bias_weight > 1.0:
        # Bullish: bonus for higher delta
        delta_bonus = (delta - 0.25) * 5  # +2.5 for delta 0.5, -1.25 for delta 0.0
        adjusted_score += max(0, delta_bonus)
    elif bias_weight < 1.0:
        # Bearish: bonus for lower delta
        delta_bonus = (0.35 - delta) * 5  # +1.75 for delta 0.0, -0.75 for delta 0.5
        adjusted_score += max(0, delta_bonus)
    
    return round(adjusted_score, 1)


def clear_bias_cache():
    """Clear the market bias cache (for admin/testing)"""
    global _bias_cache
    _bias_cache = {}
    logging.info("Market bias cache cleared")
