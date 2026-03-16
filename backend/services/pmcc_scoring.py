"""
PMCC Scoring Service — shared scoring for both quick scans and custom scans.
100-point model: Capital Efficiency (30) + LEAPS Quality (25) +
                 Short Income (20) + Management Safety (15) + Liquidity (10)
"""
from math import log1p
from typing import Dict, Any, Optional


PROFILES = {
    "capital_efficient": {
        "leaps_delta_min": 0.75, "leaps_delta_max": 0.90,
        "short_delta_min": 0.15, "short_delta_max": 0.25,
        "leaps_extrinsic_max": 0.15, "min_cap_efficiency": 1.20,
    },
    "leveraged_income": {
        "leaps_delta_min": 0.65, "leaps_delta_max": 0.75,
        "short_delta_min": 0.20, "short_delta_max": 0.30,
        "leaps_extrinsic_max": 0.20, "min_cap_efficiency": 1.15,
    },
    "max_yield_diagonal": {
        "leaps_delta_min": 0.55, "leaps_delta_max": 0.65,
        "short_delta_min": 0.25, "short_delta_max": 0.40,
        "leaps_extrinsic_max": 0.25, "min_cap_efficiency": 1.08,
    },
}


def compute_pmcc_metrics(
    spot: float,
    long_strike: float,
    long_ask: float,
    long_delta: float,
    long_dte: int,
    long_oi: int,
    long_iv: float,
    short_strike: float,
    short_bid: float,
    short_delta: float,
    short_dte: int,
    short_oi: int,
    long_spread_pct: float = 0.0,
    short_spread_pct: float = 0.0,
) -> Dict[str, Any]:
    """Compute all PMCC metrics for a trade."""
    leaps_cost = long_ask * 100
    short_credit = short_bid * 100
    net_debit_per_share = long_ask - short_bid
    net_debit = net_debit_per_share * 100
    width = short_strike - long_strike
    width_total = width * 100

    # Stock equivalent cost
    stock_equivalent_cost = spot * 100

    # Synthetic stock cost
    synthetic_stock_cost = long_strike + long_ask

    # Capital efficiency
    capital_efficiency_ratio = (stock_equivalent_cost / net_debit) if net_debit > 0 else 0
    capital_saved_dollar = stock_equivalent_cost - net_debit
    capital_saved_percent = (capital_saved_dollar / stock_equivalent_cost * 100) if stock_equivalent_cost > 0 else 0

    # LEAPS extrinsic
    long_intrinsic = max(0.0, spot - long_strike)
    leaps_extrinsic = max(0.0, long_ask - long_intrinsic)
    leaps_extrinsic_percent = (leaps_extrinsic / long_ask * 100) if long_ask > 0 else 100.0

    # ROI
    roi_cycle = (short_bid / net_debit_per_share * 100) if net_debit_per_share > 0 else 0
    annualized_income_yield = min(roi_cycle * (365 / max(short_dte, 1)), 300.0)

    # Payback
    payback_cycles = (net_debit_per_share / short_bid) if short_bid > 0 else 999
    payback_months = payback_cycles * (short_dte / 30)

    # Max spread / initial capped P/L
    max_spread_value = width_total
    initial_capped_pl = max_spread_value - net_debit

    # Breakeven
    breakeven = long_strike + net_debit_per_share

    # Assignment risk label
    if short_delta <= 0.20:
        assignment_risk = "Low"
    elif short_delta <= 0.30:
        assignment_risk = "Medium"
    else:
        assignment_risk = "High"

    return {
        "stock_equivalent_cost": round(stock_equivalent_cost, 2),
        "leaps_cost": round(leaps_cost, 2),
        "short_credit": round(short_credit, 2),
        "net_debit": round(net_debit_per_share, 2),
        "net_debit_total": round(net_debit, 2),
        "width": round(width, 2),
        "width_total": round(width_total, 2),
        "synthetic_stock_cost": round(synthetic_stock_cost, 2),
        "capital_efficiency_ratio": round(capital_efficiency_ratio, 3),
        "capital_saved_dollar": round(capital_saved_dollar, 2),
        "capital_saved_percent": round(capital_saved_percent, 2),
        "leaps_extrinsic": round(leaps_extrinsic, 2),
        "leaps_extrinsic_percent": round(leaps_extrinsic_percent, 2),
        "roi_cycle": round(roi_cycle, 2),
        "annualized_income_yield": round(annualized_income_yield, 2),
        "payback_cycles": round(payback_cycles, 1),
        "payback_months": round(payback_months, 1),
        "max_spread_value": round(max_spread_value, 2),
        "initial_capped_pl": round(initial_capped_pl, 2),
        "breakeven": round(breakeven, 2),
        "assignment_risk": assignment_risk,
        "long_spread_pct": round(long_spread_pct, 2),
        "short_spread_pct": round(short_spread_pct, 2),
    }


def hard_reject(metrics: Dict[str, Any], profile: str = "leveraged_income") -> Optional[str]:
    """Return rejection reason string if trade should be rejected, else None."""
    if metrics["capital_efficiency_ratio"] < 1.08:
        return f"REJECT_LOW_CAP_EFF_{metrics['capital_efficiency_ratio']:.2f}x"
    if metrics["capital_saved_percent"] < 5.0:
        return f"REJECT_LOW_CAPITAL_SAVED_{metrics['capital_saved_percent']:.1f}pct"
    if metrics["leaps_extrinsic_percent"] > 30.0:
        return f"REJECT_EXPENSIVE_LEAPS_{metrics['leaps_extrinsic_percent']:.1f}pct"
    if metrics["width"] < 1.0:
        return "REJECT_NARROW_WIDTH"
    if metrics["net_debit_total"] <= 0:
        return "REJECT_ZERO_NET_DEBIT"
    return None


def warning_badges(metrics: Dict[str, Any]) -> list:
    """Return list of warning badge strings for UI display."""
    badges = []
    if metrics["capital_efficiency_ratio"] < 1.20:
        badges.append("Low Capital Benefit")
    if metrics["leaps_extrinsic_percent"] > 20.0:
        badges.append("Expensive LEAPS")
    if metrics["payback_months"] > 18:
        badges.append("Slow Payback")
    if metrics["assignment_risk"] == "High":
        badges.append("High Assignment Risk")
    return badges


def score_pmcc(metrics: Dict[str, Any], profile: str = "leveraged_income") -> float:
    """
    100-point PMCC score:
    - Capital Efficiency: 30 pts
    - LEAPS Quality: 25 pts
    - Short Income: 20 pts
    - Management Safety: 15 pts
    - Liquidity: 10 pts
    """
    # 1. Capital Efficiency (30 pts)
    cer = metrics["capital_efficiency_ratio"]
    if cer >= 1.50:
        cap_eff_score = 30
    elif cer >= 1.35:
        cap_eff_score = 24
    elif cer >= 1.20:
        cap_eff_score = 18
    elif cer >= 1.08:
        cap_eff_score = 10
    else:
        cap_eff_score = 0

    # Bonus for capital saved %
    cap_saved_bonus = min(5, metrics["capital_saved_percent"] / 5)
    cap_eff_score = min(30, cap_eff_score + cap_saved_bonus)

    # 2. LEAPS Quality (25 pts)
    prof = PROFILES.get(profile, PROFILES["leveraged_income"])
    # Use extrinsic and payback as proxy for quality
    extrinsic_pct = metrics["leaps_extrinsic_percent"]
    if extrinsic_pct <= 10:
        leaps_quality_score = 25
    elif extrinsic_pct <= 15:
        leaps_quality_score = 20
    elif extrinsic_pct <= 20:
        leaps_quality_score = 15
    elif extrinsic_pct <= 25:
        leaps_quality_score = 8
    else:
        leaps_quality_score = 2

    # 3. Short Income Quality (20 pts)
    roi = metrics["roi_cycle"]
    if roi >= 10:
        income_score = 20
    elif roi >= 7:
        income_score = 16
    elif roi >= 4:
        income_score = 11
    elif roi >= 2:
        income_score = 6
    else:
        income_score = 1

    # 4. Management Safety (15 pts)
    payback = metrics["payback_months"]
    if payback <= 9:
        safety_score = 15
    elif payback <= 12:
        safety_score = 12
    elif payback <= 18:
        safety_score = 7
    else:
        safety_score = 2

    # Assignment risk penalty
    if metrics["assignment_risk"] == "High":
        safety_score = max(0, safety_score - 5)

    # 5. Liquidity (10 pts) — based on spread_pct
    avg_spread = (metrics["long_spread_pct"] + metrics["short_spread_pct"]) / 2
    if avg_spread <= 5:
        liq_score = 10
    elif avg_spread <= 10:
        liq_score = 7
    elif avg_spread <= 20:
        liq_score = 4
    else:
        liq_score = 1

    total = cap_eff_score + leaps_quality_score + income_score + safety_score + liq_score
    return round(min(100.0, max(0.0, total)), 1)
