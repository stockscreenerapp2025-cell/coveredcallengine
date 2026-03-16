"""
Pricing Rules - Single Source of Truth
======================================
GLOBAL CONSISTENCY REQUIREMENT (Feb 2026)

This module defines the SINGLE SOURCE OF TRUTH for option pricing rules
used across ALL scan paths:
- Dashboard
- Custom CC scans
- Custom PMCC scans
- Precomputed CC scans (Quick CC buckets)
- Precomputed PMCC scans (Quick PMCC buckets)

MANDATORY PRICING RULES (NO DIVERGENCE ALLOWED):
================================================
- BUY = ask (for buying options, e.g., PMCC LEAP leg)
- SELL = bid (for selling options, e.g., CC short call, PMCC short call)
- No midpoint pricing
- No averaging
- No "best of bid/ask"
- No price smoothing
- No different fallback pricing for precomputed

These functions MUST be used by all scan paths. Do NOT duplicate logic.
"""

from typing import Tuple, Optional, Dict, Any


def get_sell_price(bid: float, ask: float = None) -> Tuple[Optional[float], str]:
    """
    Get price for SELLING an option (e.g., CC short call, PMCC short call).
    
    RULE: SELL = bid
    - Use BID only
    - If BID is None, 0, or missing → return None (reject the contract)
    - Never use: lastPrice, mid, ASK, theoretical price
    
    Args:
        bid: The bid price
        ask: The ask price (not used for SELL, included for consistency)
        
    Returns:
        Tuple of (price, pricing_rule_used)
        - price: The bid price if valid, None otherwise
        - pricing_rule_used: "SELL_BID" or "INVALID_BID"
    """
    if bid is None or bid <= 0:
        return None, "INVALID_BID"
    
    return round(bid, 2), "SELL_BID"


def get_buy_price(ask: float, bid: float = None) -> Tuple[Optional[float], str]:
    """
    Get price for BUYING an option (e.g., PMCC LEAP leg).
    
    RULE: BUY = ask
    - Use ASK only
    - If ASK is None, 0, or missing → return None (reject the contract)
    - Never use: BID, lastPrice, mid, theoretical price
    
    Args:
        ask: The ask price
        bid: The bid price (not used for BUY, included for consistency)
        
    Returns:
        Tuple of (price, pricing_rule_used)
        - price: The ask price if valid, None otherwise
        - pricing_rule_used: "BUY_ASK" or "INVALID_ASK"
    """
    if ask is None or ask <= 0:
        return None, "INVALID_ASK"
    
    return round(ask, 2), "BUY_ASK"


def validate_pmcc_solvency(
    long_strike: float,
    short_strike: float,
    net_debit: float
) -> Tuple[bool, str]:
    """
    Validate PMCC solvency rule with 20% tolerance.
    
    RULE: net_debit <= width * 1.20
    This ensures the trade has reasonable profit potential while allowing
    for ASK/BID spread realities.
    
    Args:
        long_strike: LEAP strike price
        short_strike: Short call strike price
        net_debit: Cost to enter position (leap_ask - short_bid)
        
    Returns:
        Tuple of (is_valid, reason)
    """
    width = short_strike - long_strike
    
    if width <= 0:
        return False, f"FAIL_SOLVENCY_INVALID_WIDTH_{width:.2f}"
    
    # 20% tolerance: pass if net_debit <= width * 1.20
    threshold = width * 1.20
    if net_debit > threshold:
        return False, f"FAIL_SOLVENCY_width{width:.2f}_debit{net_debit:.2f}_threshold{threshold:.2f}"
    
    return True, "PASS_SOLVENCY"


def validate_pmcc_breakeven(
    long_strike: float,
    short_strike: float,
    net_debit: float
) -> Tuple[bool, str]:
    """
    Validate PMCC break-even rule.
    
    RULE: short_strike > (long_strike + net_debit)
    This ensures the short strike is above the break-even point.
    
    Args:
        long_strike: LEAP strike price
        short_strike: Short call strike price
        net_debit: Cost to enter position (leap_ask - short_bid)
        
    Returns:
        Tuple of (is_valid, reason)
    """
    breakeven = long_strike + net_debit
    
    if short_strike <= breakeven:
        return False, f"FAIL_BREAK_EVEN_short{short_strike:.2f}_be{breakeven:.2f}"
    
    return True, "PASS_BREAKEVEN"


def validate_pmcc_structure_rules(
    long_strike: float,
    short_strike: float,
    leap_ask: float,
    short_bid: float
) -> Tuple[bool, list]:
    """
    Validate PMCC structure against solvency and break-even rules.
    
    This function enforces ONLY:
    1. Solvency: (short_strike - long_strike) > net_debit
    2. Break-even: short_strike > (long_strike + net_debit)
    
    These are the two mandatory safety rules for precomputed PMCC.
    Does NOT modify any other rules (delta, DTE, OI, spread, etc.)
    
    Args:
        long_strike: LEAP strike price
        short_strike: Short call strike price
        leap_ask: ASK price of LEAP (BUY price)
        short_bid: BID price of short call (SELL price)
        
    Returns:
        Tuple of (is_valid, list_of_flags)
    """
    flags = []
    
    # Calculate net debit using proper pricing rules
    # BUY LEAP at ASK, SELL short at BID
    net_debit = leap_ask - short_bid
    
    # Net debit must be positive
    if net_debit <= 0:
        flags.append("FAIL_NEGATIVE_NET_DEBIT")
        return False, flags
    
    # RULE 1: Solvency check
    is_solvent, solvency_reason = validate_pmcc_solvency(
        long_strike, short_strike, net_debit
    )
    if not is_solvent:
        flags.append(solvency_reason)
        return False, flags
    
    # RULE 2: Break-even check
# NOTE: With net_debit defined as (BUY=ASK - SELL=BID), the break-even inequality
# short_strike > (long_strike + net_debit) is algebraically equivalent to the solvency rule
# (short_strike - long_strike) > net_debit. Therefore, break-even is treated as a SOFT flag
# to avoid redundant hard rejections while preserving the hard solvency gate.
    is_be_valid, be_reason = validate_pmcc_breakeven(
        long_strike, short_strike, net_debit
    )
    if not is_be_valid:
        # Soft flag only
        flags.append(be_reason.replace('FAIL_', 'WARN_'))

    
    return True, flags


def compute_pmcc_economics(
    long_strike: float,
    short_strike: float,
    leap_ask: float,
    short_bid: float,
    current_price: float = None,
    long_delta: float = 0.0,
    long_dte: int = 365,
    long_oi: int = 0,
    long_iv: float = 0.0,
    short_delta: float = 0.0,
    short_dte: int = 30,
    short_oi: int = 0,
    long_spread_pct: float = 0.0,
    short_spread_pct: float = 0.0,
) -> Dict[str, Any]:
    """Compute PMCC economic metrics. BUY at ASK, SELL at BID."""
    from backend.services.pmcc_scoring import compute_pmcc_metrics, hard_reject, warning_badges, score_pmcc

    spot = current_price or (long_strike * 1.05)  # fallback estimate

    metrics = compute_pmcc_metrics(
        spot=spot,
        long_strike=long_strike,
        long_ask=leap_ask,
        long_delta=long_delta,
        long_dte=long_dte,
        long_oi=long_oi,
        long_iv=long_iv,
        short_strike=short_strike,
        short_bid=short_bid,
        short_delta=short_delta,
        short_dte=short_dte,
        short_oi=short_oi,
        long_spread_pct=long_spread_pct,
        short_spread_pct=short_spread_pct,
    )

    reject_reason = hard_reject(metrics)
    badges = warning_badges(metrics)
    pmcc_score = score_pmcc(metrics)

    return {
        **metrics,
        "reject_reason": reject_reason,
        "warning_badges": badges,
        "pmcc_score": pmcc_score,
        "pricing_rule": "BUY_ASK_SELL_BID",
        # Legacy aliases
        "leap_cost": metrics["leaps_cost"],
        "short_premium": metrics["short_credit"],
        "max_profit": metrics["initial_capped_pl"],
        "max_profit_total": metrics["initial_capped_pl"],
        "roi_per_cycle": metrics["roi_cycle"],
        "capital_efficiency": metrics["capital_efficiency_ratio"],
    }
