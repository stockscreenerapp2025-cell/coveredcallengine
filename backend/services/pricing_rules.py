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
    Validate PMCC solvency rule.
    
    RULE: width > net_debit
    This ensures the trade can be profitable.
    
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
    
    if width <= net_debit:
        return False, f"FAIL_SOLVENCY_width{width:.2f}_debit{net_debit:.2f}"
    
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
    is_be_valid, be_reason = validate_pmcc_breakeven(
        long_strike, short_strike, net_debit
    )
    if not is_be_valid:
        flags.append(be_reason)
        return False, flags
    
    return True, flags


def compute_pmcc_economics(
    long_strike: float,
    short_strike: float,
    leap_ask: float,
    short_bid: float,
    current_price: float = None
) -> Dict[str, Any]:
    """
    Compute PMCC economic metrics using proper pricing rules.
    
    Uses:
    - BUY = ask (for LEAP)
    - SELL = bid (for short call)
    
    Args:
        long_strike: LEAP strike price
        short_strike: Short call strike price
        leap_ask: ASK price of LEAP
        short_bid: BID price of short call
        current_price: Current stock price (optional, for capital efficiency)
        
    Returns:
        Dict with computed economics
    """
    # Proper pricing: BUY at ASK, SELL at BID
    leap_cost = leap_ask * 100  # Per contract
    short_premium = short_bid * 100  # Per contract
    
    net_debit = leap_ask - short_bid
    net_debit_total = net_debit * 100
    
    width = short_strike - long_strike
    max_profit = width - net_debit if width > net_debit else 0
    max_profit_total = max_profit * 100
    
    breakeven = long_strike + net_debit
    
    # ROI per cycle
    roi_per_cycle = (short_bid / leap_ask) * 100 if leap_ask > 0 else 0
    
    # Capital efficiency (vs buying stock)
    capital_efficiency = None
    if current_price and current_price > 0 and net_debit > 0:
        capital_efficiency = (current_price * 100) / net_debit_total
    
    return {
        "leap_cost": round(leap_cost, 2),
        "short_premium": round(short_premium, 2),
        "net_debit": round(net_debit, 2),
        "net_debit_total": round(net_debit_total, 2),
        "width": round(width, 2),
        "max_profit": round(max_profit, 2),
        "max_profit_total": round(max_profit_total, 2),
        "breakeven": round(breakeven, 2),
        "roi_per_cycle": round(roi_per_cycle, 2),
        "capital_efficiency": round(capital_efficiency, 1) if capital_efficiency else None,
        "pricing_rule": "BUY_ASK_SELL_BID"
    }
