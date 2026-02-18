"""
Pricing Utilities - Master Stabilization Patch
===============================================
Deterministic pricing precision and policy enforcement.

NON-NEGOTIABLE:
- BUY = ASK
- SELL = BID
- 2-decimal precision for ALL monetary values
- No integer coercion on prices
- No live pricing outside OPEN market

Created: Feb 2026
"""

import math
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Dict, Any, List
import logging

logger = logging.getLogger(__name__)

# ============================================================
# CORE SANITIZERS
# ============================================================

def sanitize_float(x: Any) -> Optional[float]:
    """
    General float sanitizer - NO rounding.
    Returns None for invalid/NaN/inf values.
    
    Use for: percentages, deltas, ratios, non-monetary values
    """
    if x is None:
        return None
    try:
        f = float(x)
    except (ValueError, TypeError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def sanitize_money(x: Any) -> Optional[float]:
    """
    Money sanitizer - STRICT 2 decimal precision.
    Uses Decimal for accurate rounding (ROUND_HALF_UP).
    
    Use for: ALL monetary fields (prices, premiums, costs, profits)
    
    Examples:
        147.50 → 147.50 (NOT 147.0)
        147.499 → 147.50
        147.501 → 147.50
    """
    f = sanitize_float(x)
    if f is None:
        return None
    try:
        return float(
            Decimal(str(f)).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP
            )
        )
    except Exception:
        return None


def sanitize_percentage(x: Any, decimals: int = 2) -> Optional[float]:
    """
    Percentage sanitizer - configurable decimal places.
    Default 2 decimals for display.
    """
    f = sanitize_float(x)
    if f is None:
        return None
    try:
        precision = Decimal(f"0.{'0' * decimals}")
        return float(Decimal(str(f)).quantize(precision, rounding=ROUND_HALF_UP))
    except Exception:
        return None


# ============================================================
# MONETARY FIELD REGISTRY
# All fields that MUST use sanitize_money()
# ============================================================

MONETARY_FIELDS = {
    # Stock prices
    "stock_price",
    "session_close_price",
    "prior_close_price",
    
    # LEAP/Long leg (BUY at ASK)
    "leap_bid",
    "leap_ask",
    "leap_mid",
    "leap_last",
    "leap_used",
    "leap_prev_close",
    "leaps_ask",
    "leaps_bid",
    "leaps_premium",
    "leap_cost",
    
    # Short leg (SELL at BID)
    "short_bid",
    "short_ask",
    "short_mid",
    "short_last",
    "short_used",
    "short_prev_close",
    "short_premium",
    
    # CC premiums (SELL at BID)
    "premium",
    "premium_bid",
    "premium_ask",
    "premium_mid",
    "premium_last",
    "premium_used",
    "premium_prev_close",
    
    # Strike prices
    "strike",
    "leap_strike",
    "short_strike",
    
    # Economics
    "net_debit",
    "net_debit_total",
    "breakeven",
    "max_profit",
    "max_profit_total",
    "max_loss",
    "width",
}


def sanitize_dict_with_money(d: Dict) -> Dict:
    """
    Recursively sanitize a dictionary.
    - Monetary fields get 2-decimal precision
    - Other floats get NaN/inf protection only
    - Nested dicts/lists handled recursively
    """
    if not isinstance(d, dict):
        return d
    
    result = {}
    for key, value in d.items():
        if isinstance(value, float):
            if key in MONETARY_FIELDS:
                result[key] = sanitize_money(value)
            else:
                result[key] = sanitize_float(value)
        elif isinstance(value, dict):
            result[key] = sanitize_dict_with_money(value)
        elif isinstance(value, list):
            result[key] = [
                sanitize_dict_with_money(item) if isinstance(item, dict)
                else sanitize_money(item) if isinstance(item, float) and key in MONETARY_FIELDS
                else sanitize_float(item) if isinstance(item, float)
                else item
                for item in value
            ]
        else:
            result[key] = value
    return result


# ============================================================
# PRICING POLICY ENFORCEMENT
# ============================================================

class PricingPolicyViolation(Exception):
    """Raised when BUY=ASK / SELL=BID policy is violated."""
    pass


def enforce_pricing_policy_cc(row: Dict) -> None:
    """
    Enforce Covered Call pricing policy: SELL at BID.
    
    For CC, we SELL call options, so:
    - premium_used MUST equal premium_bid
    
    Raises PricingPolicyViolation if mismatch detected.
    """
    premium_used = row.get("premium_used")
    premium_bid = row.get("premium_bid")
    
    if premium_used is None or premium_bid is None:
        return  # Can't verify if values missing
    
    # Use Decimal comparison to avoid float precision issues
    used_d = Decimal(str(premium_used)).quantize(Decimal("0.01"))
    bid_d = Decimal(str(premium_bid)).quantize(Decimal("0.01"))
    
    if used_d != bid_d:
        raise PricingPolicyViolation(
            f"CC pricing violation: premium_used={premium_used} != premium_bid={premium_bid}"
        )


def enforce_pricing_policy_pmcc(row: Dict) -> None:
    """
    Enforce PMCC pricing policy:
    - BUY LEAP at ASK: leap_used MUST equal leap_ask
    - SELL short at BID: short_used MUST equal short_bid
    
    Raises PricingPolicyViolation if mismatch detected.
    """
    leap_used = row.get("leap_used")
    leap_ask = row.get("leap_ask")
    short_used = row.get("short_used")
    short_bid = row.get("short_bid")
    
    # Check LEAP (BUY at ASK)
    if leap_used is not None and leap_ask is not None:
        used_d = Decimal(str(leap_used)).quantize(Decimal("0.01"))
        ask_d = Decimal(str(leap_ask)).quantize(Decimal("0.01"))
        if used_d != ask_d:
            raise PricingPolicyViolation(
                f"PMCC LEAP pricing violation: leap_used={leap_used} != leap_ask={leap_ask}"
            )
    
    # Check Short (SELL at BID)
    if short_used is not None and short_bid is not None:
        used_d = Decimal(str(short_used)).quantize(Decimal("0.01"))
        bid_d = Decimal(str(short_bid)).quantize(Decimal("0.01"))
        if used_d != bid_d:
            raise PricingPolicyViolation(
                f"PMCC short pricing violation: short_used={short_used} != short_bid={short_bid}"
            )


# ============================================================
# LIVE PRICING GUARD
# ============================================================

_live_pricing_blocked = False

def set_live_pricing_blocked(blocked: bool) -> None:
    """Set global live pricing block status."""
    global _live_pricing_blocked
    _live_pricing_blocked = blocked


def is_live_pricing_blocked() -> bool:
    """Check if live pricing is blocked."""
    return _live_pricing_blocked


class LivePricingBlocked(Exception):
    """Raised when live pricing is attempted outside OPEN market."""
    pass


def guard_live_pricing(market_state: str, operation: str = "pricing") -> None:
    """
    Guard against live pricing calls outside OPEN market.
    
    Args:
        market_state: Current market state (OPEN, CLOSED, PREMARKET, AFTERHOURS)
        operation: Description of operation for error message
    
    Raises:
        LivePricingBlocked if market not OPEN and blocking is enabled
    """
    if _live_pricing_blocked and market_state != "OPEN":
        raise LivePricingBlocked(
            f"Live {operation} blocked outside OPEN market (state={market_state})"
        )


# ============================================================
# CROSS-ENDPOINT CONSISTENCY HELPERS
# ============================================================

def normalize_opportunity_prices(opp: Dict) -> Dict:
    """
    Normalize all monetary fields in an opportunity dict
    to ensure cross-endpoint consistency.
    """
    return sanitize_dict_with_money(opp)


def compare_prices(price1: float, price2: float) -> bool:
    """
    Compare two prices for equality (2 decimal precision).
    Returns True if equal, False otherwise.
    """
    if price1 is None or price2 is None:
        return price1 is None and price2 is None
    
    p1 = Decimal(str(price1)).quantize(Decimal("0.01"))
    p2 = Decimal(str(price2)).quantize(Decimal("0.01"))
    return p1 == p2
