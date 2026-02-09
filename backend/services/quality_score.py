"""
Quality Score Module - Phase 7
Pillar-based, explainable scoring for Covered Calls and PMCC.

PHASE 7 RULES:
- Binary gating: Invalid trades are NOT scored
- Each pillar has a max score and clear calculation
- Score breakdown is visible in API response
- Total score is 0-100

COVERED CALL PILLARS (5):
1. Volatility & Pricing Edge – 30%
2. Greeks Efficiency – 25%
3. Technical Stability – 20%
4. Fundamental Safety – 15%
5. Liquidity & Execution – 10%

PMCC PILLARS (5):
1. LEAP Quality – 30%
2. Short Call Income Efficiency – 25%
3. Volatility Structure – 20%
4. Technical Alignment – 15%
5. Liquidity & Risk Controls – 10%
"""
import logging
from typing import Dict, Any, Tuple, Optional
from dataclasses import dataclass


@dataclass
class ScorePillar:
    """Represents a single scoring pillar"""
    name: str
    max_score: float
    actual_score: float
    percentage: float  # How much of max was achieved
    explanation: str


@dataclass
class QualityScore:
    """Complete quality score with pillar breakdown"""
    total_score: float
    pillars: Dict[str, ScorePillar]
    is_valid: bool
    rejection_reason: Optional[str] = None


# ============================================================
# COVERED CALL SCORING
# ============================================================

def calculate_cc_volatility_score(
    iv: float,
    iv_rank: float,
    premium_yield: float,
    dte: int
) -> Tuple[float, str]:
    """
    Pillar 1: Volatility & Pricing Edge (30 points max)
    
    Factors:
    - IV Rank (higher = better premium opportunity) - 12 points
    - Premium Yield relative to risk - 10 points
    - IV vs DTE efficiency - 8 points
    """
    max_score = 30.0
    
    # PHASE 2 FIX: Handle None iv_rank
    if iv_rank is None:
        iv_rank = 50  # Default to neutral IV rank
    
    # IV Rank scoring (0-100 → 0-12 points)
    # Sweet spot: 30-70 IV Rank (not too low, not panic high)
    if 30 <= iv_rank <= 70:
        iv_rank_score = 12.0
    elif iv_rank > 70:
        # High IV = good premium but risky
        iv_rank_score = 12.0 - (iv_rank - 70) * 0.1
    else:
        # Low IV = less premium opportunity
        iv_rank_score = iv_rank * 0.4
    iv_rank_score = max(0, min(12, iv_rank_score))
    
    # Premium yield scoring (0-10 points)
    # Target: 2-5% monthly equivalent yield
    monthly_equiv = (premium_yield / max(dte, 1)) * 30
    if 2.0 <= monthly_equiv <= 5.0:
        yield_score = 10.0
    elif monthly_equiv > 5.0:
        # Very high yield = might be too risky
        yield_score = 10.0 - min(5, (monthly_equiv - 5) * 0.5)
    else:
        yield_score = monthly_equiv * 5.0
    yield_score = max(0, min(10, yield_score))
    
    # IV efficiency (8 points)
    # Higher IV with reasonable DTE = better
    iv_pct = iv * 100 if iv < 1 else iv
    if dte >= 7 and dte <= 45:
        if iv_pct >= 25 and iv_pct <= 60:
            iv_eff_score = 8.0
        elif iv_pct > 60:
            iv_eff_score = 8.0 - (iv_pct - 60) * 0.1
        else:
            iv_eff_score = iv_pct * 0.32
    else:
        iv_eff_score = 4.0  # Suboptimal DTE
    iv_eff_score = max(0, min(8, iv_eff_score))
    
    total = round(iv_rank_score + yield_score + iv_eff_score, 1)
    explanation = f"IV Rank {iv_rank:.0f}% ({iv_rank_score:.1f}/12), Yield {premium_yield:.2f}% ({yield_score:.1f}/10), IV Eff ({iv_eff_score:.1f}/8)"
    
    return total, explanation


def calculate_cc_greeks_score(
    delta: float,
    theta: float,
    premium: float,
    stock_price: float,
    dte: int
) -> Tuple[float, str]:
    """
    Pillar 2: Greeks Efficiency (25 points max)
    
    Factors:
    - Delta sweet spot (0.20-0.35) - 12 points
    - Theta decay efficiency - 8 points
    - Risk/reward ratio - 5 points
    """
    max_score = 25.0
    
    # Delta scoring (ideal: 0.20-0.35 for CC)
    if 0.20 <= delta <= 0.35:
        delta_score = 12.0
    elif 0.15 <= delta < 0.20:
        delta_score = 10.0
    elif 0.35 < delta <= 0.45:
        delta_score = 10.0 - (delta - 0.35) * 20
    elif delta < 0.15:
        delta_score = delta * 66.67  # Linear scale down
    else:
        delta_score = max(0, 12 - (delta - 0.45) * 30)
    delta_score = max(0, min(12, delta_score))
    
    # Theta efficiency (8 points)
    # Estimate theta if not provided
    if theta == 0 and premium > 0 and dte > 0:
        theta = -premium / dte  # Simple estimate
    
    daily_decay_pct = abs(theta) / stock_price * 100 if stock_price > 0 else 0
    if 0.05 <= daily_decay_pct <= 0.20:
        theta_score = 8.0
    elif daily_decay_pct > 0.20:
        theta_score = 8.0 - min(4, (daily_decay_pct - 0.20) * 20)
    else:
        theta_score = daily_decay_pct * 160
    theta_score = max(0, min(8, theta_score))
    
    # Risk/reward (5 points)
    # Premium vs potential assignment risk
    protection_pct = (premium / stock_price) * 100 if stock_price > 0 else 0
    if protection_pct >= 2.0:
        rr_score = 5.0
    elif protection_pct >= 1.0:
        rr_score = 3.0 + (protection_pct - 1.0) * 2
    else:
        rr_score = protection_pct * 3
    rr_score = max(0, min(5, rr_score))
    
    total = round(delta_score + theta_score + rr_score, 1)
    explanation = f"Delta {delta:.2f} ({delta_score:.1f}/12), Theta ({theta_score:.1f}/8), R/R ({rr_score:.1f}/5)"
    
    return total, explanation


def calculate_cc_technical_score(
    above_sma50: bool = None,
    above_sma200: bool = None,
    rsi: float = None,
    price_stability: float = None
) -> Tuple[float, str]:
    """
    Pillar 3: Technical Stability (20 points max)
    
    Factors:
    - SMA alignment - 8 points
    - RSI position - 6 points
    - Price stability/ATR - 6 points
    """
    max_score = 20.0
    
    # SMA alignment (8 points)
    if above_sma50 is not None and above_sma200 is not None:
        if above_sma50 and above_sma200:
            sma_score = 8.0  # Bullish alignment
        elif above_sma50:
            sma_score = 5.0  # Mixed
        elif above_sma200:
            sma_score = 3.0  # Longer term support
        else:
            sma_score = 1.0  # Below both
    else:
        sma_score = 4.0  # Unknown, neutral
    
    # RSI (6 points) - ideal 40-60 for CC
    if rsi is not None:
        if 40 <= rsi <= 60:
            rsi_score = 6.0  # Neutral, ideal for CC
        elif 30 <= rsi < 40:
            rsi_score = 4.0  # Slightly oversold
        elif 60 < rsi <= 70:
            rsi_score = 4.0  # Slightly overbought
        elif rsi < 30:
            rsi_score = 2.0  # Oversold, risky
        else:
            rsi_score = 2.0  # Overbought, assignment risk
    else:
        rsi_score = 3.0  # Unknown, neutral
    
    # Price stability (6 points)
    if price_stability is not None:
        # Lower ATR% = more stable = better for CC
        if price_stability <= 2.0:
            stability_score = 6.0
        elif price_stability <= 3.5:
            stability_score = 4.0
        elif price_stability <= 5.0:
            stability_score = 2.0
        else:
            stability_score = 1.0
    else:
        stability_score = 3.0  # Unknown, neutral
    
    total = round(sma_score + rsi_score + stability_score, 1)
    explanation = f"SMA ({sma_score:.1f}/8), RSI ({rsi_score:.1f}/6), Stability ({stability_score:.1f}/6)"
    
    return total, explanation


def calculate_cc_fundamental_score(
    market_cap: float = None,
    has_earnings_soon: bool = False,
    analyst_rating: str = None,
    sector: str = None
) -> Tuple[float, str]:
    """
    Pillar 4: Fundamental Safety (15 points max)
    
    Factors:
    - Market cap tier - 6 points
    - Earnings safety - 5 points
    - Analyst consensus - 4 points
    """
    max_score = 15.0
    
    # Market cap (6 points)
    if market_cap is not None:
        if market_cap >= 100_000_000_000:  # $100B+
            cap_score = 6.0
        elif market_cap >= 50_000_000_000:  # $50B+
            cap_score = 5.0
        elif market_cap >= 10_000_000_000:  # $10B+
            cap_score = 4.0
        elif market_cap >= 5_000_000_000:   # $5B+
            cap_score = 3.0
        else:
            cap_score = 2.0
    else:
        cap_score = 3.0  # Unknown
    
    # Earnings safety (5 points)
    if has_earnings_soon:
        earnings_score = 0.0  # Major risk
    else:
        earnings_score = 5.0  # Safe
    
    # Analyst rating (4 points)
    if analyst_rating:
        rating_lower = analyst_rating.lower()
        if "strong buy" in rating_lower:
            analyst_score = 4.0
        elif "buy" in rating_lower:
            analyst_score = 3.5
        elif "hold" in rating_lower:
            analyst_score = 2.5
        elif "sell" in rating_lower or "underperform" in rating_lower:
            analyst_score = 1.0
        else:
            analyst_score = 2.0
    else:
        analyst_score = 2.0  # Unknown
    
    total = round(cap_score + earnings_score + analyst_score, 1)
    explanation = f"MktCap ({cap_score:.1f}/6), Earnings ({earnings_score:.1f}/5), Analyst ({analyst_score:.1f}/4)"
    
    return total, explanation


def calculate_cc_liquidity_score(
    open_interest: int,
    volume: int,
    bid_ask_spread: float = None,
    avg_volume: float = None
) -> Tuple[float, str]:
    """
    Pillar 5: Liquidity & Execution (10 points max)
    
    Factors:
    - Open interest - 4 points
    - Volume - 3 points
    - Bid-ask spread - 3 points
    """
    max_score = 10.0
    
    # Open interest (4 points)
    if open_interest >= 5000:
        oi_score = 4.0
    elif open_interest >= 1000:
        oi_score = 3.0
    elif open_interest >= 500:
        oi_score = 2.5
    elif open_interest >= 100:
        oi_score = 2.0
    elif open_interest >= 50:
        oi_score = 1.0
    else:
        oi_score = 0.5
    
    # Volume (3 points)
    if volume >= 1000:
        vol_score = 3.0
    elif volume >= 500:
        vol_score = 2.5
    elif volume >= 100:
        vol_score = 2.0
    elif volume >= 50:
        vol_score = 1.0
    else:
        vol_score = 0.5
    
    # Bid-ask spread (3 points)
    if bid_ask_spread is not None:
        if bid_ask_spread <= 0.05:
            spread_score = 3.0
        elif bid_ask_spread <= 0.10:
            spread_score = 2.5
        elif bid_ask_spread <= 0.20:
            spread_score = 2.0
        elif bid_ask_spread <= 0.50:
            spread_score = 1.0
        else:
            spread_score = 0.5
    else:
        spread_score = 1.5  # Unknown
    
    total = round(oi_score + vol_score + spread_score, 1)
    explanation = f"OI {open_interest:,} ({oi_score:.1f}/4), Vol ({vol_score:.1f}/3), Spread ({spread_score:.1f}/3)"
    
    return total, explanation


def calculate_cc_quality_score(trade_data: Dict[str, Any]) -> QualityScore:
    """
    Calculate complete Covered Call quality score with pillar breakdown.
    
    Args:
        trade_data: Dict with trade details (symbol, delta, premium, etc.)
    
    Returns:
        QualityScore with total and pillar breakdown
    """
    # Binary gating - check if trade is valid first
    if not trade_data.get("is_valid", True):
        return QualityScore(
            total_score=0,
            pillars={},
            is_valid=False,
            rejection_reason=trade_data.get("rejection_reason", "Invalid trade")
        )
    
    pillars = {}
    
    # Pillar 1: Volatility & Pricing Edge (30%)
    vol_score, vol_exp = calculate_cc_volatility_score(
        iv=trade_data.get("iv", 0.30),
        iv_rank=trade_data.get("iv_rank", 50),
        premium_yield=trade_data.get("roi_pct", 0),
        dte=trade_data.get("dte", 30)
    )
    pillars["volatility"] = ScorePillar(
        name="Volatility & Pricing Edge",
        max_score=30.0,
        actual_score=vol_score,
        percentage=round(vol_score / 30 * 100, 1),
        explanation=vol_exp
    )
    
    # Pillar 2: Greeks Efficiency (25%)
    greeks_score, greeks_exp = calculate_cc_greeks_score(
        delta=trade_data.get("delta", 0.30),
        theta=trade_data.get("theta", 0),
        premium=trade_data.get("premium", 0),
        stock_price=trade_data.get("stock_price", 100),
        dte=trade_data.get("dte", 30)
    )
    pillars["greeks"] = ScorePillar(
        name="Greeks Efficiency",
        max_score=25.0,
        actual_score=greeks_score,
        percentage=round(greeks_score / 25 * 100, 1),
        explanation=greeks_exp
    )
    
    # Pillar 3: Technical Stability (20%)
    tech_score, tech_exp = calculate_cc_technical_score(
        above_sma50=trade_data.get("above_sma50"),
        above_sma200=trade_data.get("above_sma200"),
        rsi=trade_data.get("rsi"),
        price_stability=trade_data.get("atr_pct")
    )
    pillars["technical"] = ScorePillar(
        name="Technical Stability",
        max_score=20.0,
        actual_score=tech_score,
        percentage=round(tech_score / 20 * 100, 1),
        explanation=tech_exp
    )
    
    # Pillar 4: Fundamental Safety (15%)
    fund_score, fund_exp = calculate_cc_fundamental_score(
        market_cap=trade_data.get("market_cap"),
        has_earnings_soon=trade_data.get("has_earnings_soon", False),
        analyst_rating=trade_data.get("analyst_rating"),
        sector=trade_data.get("sector")
    )
    pillars["fundamental"] = ScorePillar(
        name="Fundamental Safety",
        max_score=15.0,
        actual_score=fund_score,
        percentage=round(fund_score / 15 * 100, 1),
        explanation=fund_exp
    )
    
    # Pillar 5: Liquidity & Execution (10%)
    liq_score, liq_exp = calculate_cc_liquidity_score(
        open_interest=trade_data.get("open_interest", 0),
        volume=trade_data.get("volume", 0),
        bid_ask_spread=trade_data.get("bid_ask_spread"),
        avg_volume=trade_data.get("avg_volume")
    )
    pillars["liquidity"] = ScorePillar(
        name="Liquidity & Execution",
        max_score=10.0,
        actual_score=liq_score,
        percentage=round(liq_score / 10 * 100, 1),
        explanation=liq_exp
    )
    
    # Calculate total score
    total = sum(p.actual_score for p in pillars.values())
    total = round(min(100, max(0, total)), 1)
    
    return QualityScore(
        total_score=total,
        pillars=pillars,
        is_valid=True
    )


# ============================================================
# PMCC SCORING
# ============================================================

def calculate_pmcc_leap_quality_score(
    leaps_delta: float,
    leaps_dte: int,
    leaps_cost: float,
    stock_price: float,
    leaps_strike: float
) -> Tuple[float, str]:
    """
    Pillar 1: LEAP Quality (30 points max)
    
    Factors:
    - Delta (0.70-0.85 ideal) - 12 points
    - DTE (180-400 sweet spot) - 10 points
    - Cost efficiency - 8 points
    """
    max_score = 30.0
    
    # LEAPS Delta (12 points) - ideal 0.70-0.85
    if 0.70 <= leaps_delta <= 0.85:
        delta_score = 12.0
    elif 0.85 < leaps_delta <= 0.95:
        delta_score = 10.0  # Very deep ITM, less leverage
    elif 0.60 <= leaps_delta < 0.70:
        delta_score = 8.0  # Slightly too low
    elif leaps_delta > 0.95:
        delta_score = 8.0  # Almost stock replacement
    else:
        delta_score = leaps_delta * 16  # Linear for low delta
    delta_score = max(0, min(12, delta_score))
    
    # DTE (10 points) - ideal 180-400 days
    if 180 <= leaps_dte <= 400:
        dte_score = 10.0
    elif 400 < leaps_dte <= 730:
        dte_score = 8.0  # Very long, more capital tied up
    elif 120 <= leaps_dte < 180:
        dte_score = 6.0  # Getting short for LEAPS
    elif leaps_dte > 730:
        dte_score = 6.0  # Too far out
    else:
        dte_score = max(0, leaps_dte / 30)  # Linear for short DTE
    dte_score = max(0, min(10, dte_score))
    
    # Cost efficiency (8 points)
    # LEAPS cost as % of stock position
    cost_pct = (leaps_cost / (stock_price * 100)) * 100 if stock_price > 0 else 100
    if 40 <= cost_pct <= 70:
        cost_score = 8.0  # Good leverage
    elif 30 <= cost_pct < 40:
        cost_score = 6.0  # Cheap but risky
    elif 70 < cost_pct <= 85:
        cost_score = 6.0  # Less leverage
    elif cost_pct > 85:
        cost_score = 4.0  # Expensive
    else:
        cost_score = 4.0  # Very cheap, probably low delta
    cost_score = max(0, min(8, cost_score))
    
    total = round(delta_score + dte_score + cost_score, 1)
    explanation = f"LEAPS δ{leaps_delta:.2f} ({delta_score:.1f}/12), {leaps_dte}d ({dte_score:.1f}/10), Cost ({cost_score:.1f}/8)"
    
    return total, explanation


def calculate_pmcc_income_efficiency_score(
    short_premium: float,
    leaps_cost: float,
    short_delta: float,
    short_dte: int,
    roi_per_cycle: float
) -> Tuple[float, str]:
    """
    Pillar 2: Short Call Income Efficiency (25 points max)
    
    Factors:
    - ROI per cycle - 10 points
    - Short delta sweet spot - 8 points
    - Income vs LEAPS decay - 7 points
    """
    max_score = 25.0
    
    # ROI per cycle (10 points) - ideal 3-8%
    if 3.0 <= roi_per_cycle <= 8.0:
        roi_score = 10.0
    elif 8.0 < roi_per_cycle <= 12.0:
        roi_score = 8.0  # High but potentially aggressive
    elif 2.0 <= roi_per_cycle < 3.0:
        roi_score = 7.0  # Conservative
    elif roi_per_cycle > 12.0:
        roi_score = 6.0  # Too aggressive, assignment risk
    else:
        roi_score = roi_per_cycle * 3.5
    roi_score = max(0, min(10, roi_score))
    
    # Short delta (8 points) - ideal 0.20-0.30
    if 0.20 <= short_delta <= 0.30:
        delta_score = 8.0
    elif 0.15 <= short_delta < 0.20:
        delta_score = 6.0
    elif 0.30 < short_delta <= 0.40:
        delta_score = 5.0  # Higher assignment risk
    elif short_delta > 0.40:
        delta_score = 3.0  # Too aggressive
    else:
        delta_score = short_delta * 40
    delta_score = max(0, min(8, delta_score))
    
    # Income vs decay (7 points)
    # Short premium should cover LEAPS time decay
    cycles_to_cover = leaps_cost / short_premium if short_premium > 0 else 999
    if cycles_to_cover <= 8:
        decay_score = 7.0  # Excellent
    elif cycles_to_cover <= 12:
        decay_score = 5.0  # Good
    elif cycles_to_cover <= 18:
        decay_score = 3.0  # Acceptable
    else:
        decay_score = 1.0  # Poor income potential
    decay_score = max(0, min(7, decay_score))
    
    total = round(roi_score + delta_score + decay_score, 1)
    explanation = f"ROI {roi_per_cycle:.1f}% ({roi_score:.1f}/10), Short δ{short_delta:.2f} ({delta_score:.1f}/8), Decay ({decay_score:.1f}/7)"
    
    return total, explanation


def calculate_pmcc_volatility_structure_score(
    iv: float = None,
    iv_rank: float = None,
    leaps_iv: float = None,
    short_iv: float = None
) -> Tuple[float, str]:
    """
    Pillar 3: Volatility Structure (20 points max)
    
    Factors:
    - Overall IV environment - 10 points
    - IV skew (LEAPS vs short) - 6 points
    - IV rank - 4 points
    """
    max_score = 20.0
    
    # Overall IV (10 points)
    iv_pct = (iv * 100 if iv and iv < 1 else iv) or 30
    if 25 <= iv_pct <= 50:
        iv_score = 10.0
    elif 50 < iv_pct <= 70:
        iv_score = 7.0  # Higher premium but risk
    elif 15 <= iv_pct < 25:
        iv_score = 6.0  # Low premium
    elif iv_pct > 70:
        iv_score = 5.0  # Very high, risky
    else:
        iv_score = 4.0
    iv_score = max(0, min(10, iv_score))
    
    # IV skew (6 points) - ideally sell higher IV than buy
    if leaps_iv and short_iv:
        skew = short_iv - leaps_iv
        if skew > 0.05:
            skew_score = 6.0  # Positive skew, selling rich
        elif skew > 0:
            skew_score = 5.0  # Slight positive
        elif skew > -0.05:
            skew_score = 4.0  # Neutral
        else:
            skew_score = 2.0  # Negative skew
    else:
        skew_score = 3.0  # Unknown
    skew_score = max(0, min(6, skew_score))
    
    # IV Rank (4 points)
    iv_rank_val = iv_rank or 50
    if 30 <= iv_rank_val <= 70:
        rank_score = 4.0
    elif iv_rank_val > 70:
        rank_score = 3.0  # High rank, good premium but risk
    else:
        rank_score = 2.0  # Low rank
    rank_score = max(0, min(4, rank_score))
    
    total = round(iv_score + skew_score + rank_score, 1)
    explanation = f"IV {iv_pct:.0f}% ({iv_score:.1f}/10), Skew ({skew_score:.1f}/6), Rank ({rank_score:.1f}/4)"
    
    return total, explanation


def calculate_pmcc_technical_alignment_score(
    above_sma50: bool = None,
    above_sma200: bool = None,
    trend_direction: str = None,
    rsi: float = None
) -> Tuple[float, str]:
    """
    Pillar 4: Technical Alignment (15 points max)
    
    Factors:
    - Trend alignment (bullish preferred for PMCC) - 7 points
    - SMA position - 5 points
    - RSI - 3 points
    """
    max_score = 15.0
    
    # Trend (7 points) - PMCC benefits from bullish/neutral trend
    if trend_direction:
        if trend_direction.lower() in ["bullish", "up"]:
            trend_score = 7.0
        elif trend_direction.lower() in ["neutral", "sideways"]:
            trend_score = 5.0
        else:
            trend_score = 2.0  # Bearish, risky for PMCC
    else:
        trend_score = 4.0  # Unknown
    
    # SMA position (5 points)
    if above_sma50 is not None and above_sma200 is not None:
        if above_sma50 and above_sma200:
            sma_score = 5.0
        elif above_sma50:
            sma_score = 4.0
        elif above_sma200:
            sma_score = 3.0
        else:
            sma_score = 1.0
    else:
        sma_score = 2.5
    
    # RSI (3 points)
    if rsi is not None:
        if 40 <= rsi <= 65:
            rsi_score = 3.0
        elif 30 <= rsi < 40:
            rsi_score = 2.0
        elif 65 < rsi <= 75:
            rsi_score = 2.0
        else:
            rsi_score = 1.0
    else:
        rsi_score = 1.5
    
    total = round(trend_score + sma_score + rsi_score, 1)
    explanation = f"Trend ({trend_score:.1f}/7), SMA ({sma_score:.1f}/5), RSI ({rsi_score:.1f}/3)"
    
    return total, explanation


def calculate_pmcc_liquidity_risk_score(
    leaps_oi: int = 0,
    short_oi: int = 0,
    net_debit: float = 0,
    max_loss: float = None,
    strike_width: float = 0
) -> Tuple[float, str]:
    """
    Pillar 5: Liquidity & Risk Controls (10 points max)
    
    Factors:
    - LEAPS liquidity - 4 points
    - Short call liquidity - 3 points
    - Risk/reward structure - 3 points
    """
    max_score = 10.0
    
    # LEAPS liquidity (4 points)
    if leaps_oi >= 500:
        leaps_liq = 4.0
    elif leaps_oi >= 100:
        leaps_liq = 3.0
    elif leaps_oi >= 50:
        leaps_liq = 2.0
    elif leaps_oi >= 20:
        leaps_liq = 1.0
    else:
        leaps_liq = 0.5
    
    # Short liquidity (3 points)
    if short_oi >= 1000:
        short_liq = 3.0
    elif short_oi >= 500:
        short_liq = 2.5
    elif short_oi >= 100:
        short_liq = 2.0
    elif short_oi >= 50:
        short_liq = 1.0
    else:
        short_liq = 0.5
    
    # Risk structure (3 points)
    # Strike width relative to net debit
    if strike_width > 0 and net_debit > 0:
        width_ratio = (strike_width * 100) / net_debit  # Max profit potential ratio
        if width_ratio >= 0.5:
            risk_score = 3.0
        elif width_ratio >= 0.3:
            risk_score = 2.0
        else:
            risk_score = 1.0
    else:
        risk_score = 1.5
    
    total = round(leaps_liq + short_liq + risk_score, 1)
    explanation = f"LEAPS OI ({leaps_liq:.1f}/4), Short OI ({short_liq:.1f}/3), Risk ({risk_score:.1f}/3)"
    
    return total, explanation


def calculate_pmcc_quality_score(trade_data: Dict[str, Any]) -> QualityScore:
    """
    Calculate complete PMCC quality score with pillar breakdown.
    
    Args:
        trade_data: Dict with PMCC trade details
    
    Returns:
        QualityScore with total and pillar breakdown
    """
    # Binary gating
    if not trade_data.get("is_valid", True):
        return QualityScore(
            total_score=0,
            pillars={},
            is_valid=False,
            rejection_reason=trade_data.get("rejection_reason", "Invalid trade")
        )
    
    pillars = {}
    
    # Pillar 1: LEAP Quality (30%)
    leap_score, leap_exp = calculate_pmcc_leap_quality_score(
        leaps_delta=trade_data.get("leaps_delta", 0.80),
        leaps_dte=trade_data.get("leaps_dte", 365),
        leaps_cost=trade_data.get("leaps_cost", 5000),
        stock_price=trade_data.get("stock_price", 100),
        leaps_strike=trade_data.get("leaps_strike", 80)
    )
    pillars["leap_quality"] = ScorePillar(
        name="LEAP Quality",
        max_score=30.0,
        actual_score=leap_score,
        percentage=round(leap_score / 30 * 100, 1),
        explanation=leap_exp
    )
    
    # Pillar 2: Short Call Income Efficiency (25%)
    income_score, income_exp = calculate_pmcc_income_efficiency_score(
        short_premium=trade_data.get("short_premium", 0),
        leaps_cost=trade_data.get("leaps_cost", 5000),
        short_delta=trade_data.get("short_delta", 0.25),
        short_dte=trade_data.get("short_dte", 30),
        roi_per_cycle=trade_data.get("roi_per_cycle", 0)
    )
    pillars["income_efficiency"] = ScorePillar(
        name="Short Call Income Efficiency",
        max_score=25.0,
        actual_score=income_score,
        percentage=round(income_score / 25 * 100, 1),
        explanation=income_exp
    )
    
    # Pillar 3: Volatility Structure (20%)
    vol_score, vol_exp = calculate_pmcc_volatility_structure_score(
        iv=trade_data.get("iv"),
        iv_rank=trade_data.get("iv_rank"),
        leaps_iv=trade_data.get("leaps_iv"),
        short_iv=trade_data.get("short_iv")
    )
    pillars["volatility_structure"] = ScorePillar(
        name="Volatility Structure",
        max_score=20.0,
        actual_score=vol_score,
        percentage=round(vol_score / 20 * 100, 1),
        explanation=vol_exp
    )
    
    # Pillar 4: Technical Alignment (15%)
    tech_score, tech_exp = calculate_pmcc_technical_alignment_score(
        above_sma50=trade_data.get("above_sma50"),
        above_sma200=trade_data.get("above_sma200"),
        trend_direction=trade_data.get("trend_direction"),
        rsi=trade_data.get("rsi")
    )
    pillars["technical_alignment"] = ScorePillar(
        name="Technical Alignment",
        max_score=15.0,
        actual_score=tech_score,
        percentage=round(tech_score / 15 * 100, 1),
        explanation=tech_exp
    )
    
    # Pillar 5: Liquidity & Risk Controls (10%)
    liq_score, liq_exp = calculate_pmcc_liquidity_risk_score(
        leaps_oi=trade_data.get("leaps_oi", 0),
        short_oi=trade_data.get("short_oi", 0),
        net_debit=trade_data.get("net_debit", 0),
        max_loss=trade_data.get("max_loss"),
        strike_width=trade_data.get("strike_width", 0)
    )
    pillars["liquidity_risk"] = ScorePillar(
        name="Liquidity & Risk Controls",
        max_score=10.0,
        actual_score=liq_score,
        percentage=round(liq_score / 10 * 100, 1),
        explanation=liq_exp
    )
    
    # Calculate total score
    total = sum(p.actual_score for p in pillars.values())
    total = round(min(100, max(0, total)), 1)
    
    return QualityScore(
        total_score=total,
        pillars=pillars,
        is_valid=True
    )


def score_to_dict(quality_score: QualityScore) -> Dict[str, Any]:
    """Convert QualityScore to JSON-serializable dict"""
    return {
        "total_score": quality_score.total_score,
        "is_valid": quality_score.is_valid,
        "rejection_reason": quality_score.rejection_reason,
        "pillars": {
            key: {
                "name": pillar.name,
                "max_score": pillar.max_score,
                "actual_score": pillar.actual_score,
                "percentage": pillar.percentage,
                "explanation": pillar.explanation
            }
            for key, pillar in quality_score.pillars.items()
        } if quality_score.pillars else {}
    }
