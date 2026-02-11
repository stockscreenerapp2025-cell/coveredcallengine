"""
Greeks Service - Centralized Black-Scholes Greeks Calculation
=============================================================

SINGLE SOURCE OF TRUTH for Delta, Gamma, Theta, Vega calculations.
Replaces all moneyness-based delta fallbacks with proper Black-Scholes.

HARD CONSTRAINTS:
- Delta must be computed using Black-Scholes whenever possible
- If IV is missing, use sigma proxy (0.35) but mark delta_source="BS_PROXY_SIGMA"
- Never use linear moneyness fallback
- All functions handle edge cases gracefully (no NaN, no crashes)

ENV VAR:
- RISK_FREE_RATE: Default 0.045 (4.5%), bounds [0.001, 0.20]
"""

import math
import os
import logging
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

def get_risk_free_rate() -> float:
    """
    Get risk-free rate from environment with validation.
    
    Returns:
        float: Risk-free rate (default 0.045)
    """
    default_rate = 0.045
    
    try:
        rate_str = os.environ.get("RISK_FREE_RATE", "")
        if not rate_str:
            return default_rate
        
        rate = float(rate_str)
        
        # Bounds validation: must be > 0 and <= 0.20
        if rate <= 0 or rate > 0.20:
            logger.warning(f"RISK_FREE_RATE={rate} out of bounds [0.001, 0.20], using default {default_rate}")
            return default_rate
        
        return rate
    except (ValueError, TypeError):
        logger.warning(f"Invalid RISK_FREE_RATE, using default {default_rate}")
        return default_rate


# Default sigma proxy when IV is missing
SIGMA_PROXY_DEFAULT = 0.35
SIGMA_PROXY_MIN = 0.10
SIGMA_PROXY_MAX = 3.00


# =============================================================================
# BLACK-SCHOLES CORE FUNCTIONS
# =============================================================================

def norm_cdf(x: float) -> float:
    """Cumulative distribution function for standard normal."""
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0


def norm_pdf(x: float) -> float:
    """Probability density function for standard normal."""
    return math.exp(-0.5 * x ** 2) / math.sqrt(2 * math.pi)


def calculate_d1_d2(S: float, K: float, T: float, r: float, sigma: float) -> Tuple[Optional[float], Optional[float]]:
    """
    Calculate d1 and d2 for Black-Scholes formula.
    
    Args:
        S: Current stock price
        K: Strike price
        T: Time to expiration (in years)
        r: Risk-free rate
        sigma: Implied volatility (decimal, e.g., 0.30 for 30%)
    
    Returns:
        Tuple of (d1, d2) or (None, None) if invalid inputs
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return None, None
    
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        return d1, d2
    except (ValueError, ZeroDivisionError, OverflowError):
        return None, None


def calculate_call_price_bs(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """
    Calculate Black-Scholes call option price.
    
    Returns intrinsic value if T <= 0 or sigma <= 0.
    """
    if T <= 0 or sigma <= 0:
        return max(0, S - K)
    
    d1, d2 = calculate_d1_d2(S, K, T, r, sigma)
    if d1 is None:
        return max(0, S - K)
    
    return S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)


def calculate_put_price_bs(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """
    Calculate Black-Scholes put option price.
    
    Returns intrinsic value if T <= 0 or sigma <= 0.
    """
    if T <= 0 or sigma <= 0:
        return max(0, K - S)
    
    d1, d2 = calculate_d1_d2(S, K, T, r, sigma)
    if d1 is None:
        return max(0, K - S)
    
    return K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)


# =============================================================================
# GREEKS CALCULATION
# =============================================================================

@dataclass
class GreeksResult:
    """Result container for Greeks calculation."""
    delta: float
    gamma: float
    theta: float
    vega: float
    delta_source: str
    option_value: float
    r_used: float  # Risk-free rate used (for admin endpoint)
    sigma_used: float  # Sigma used (for admin endpoint)


def calculate_greeks(
    S: float,
    K: float,
    T: float,
    sigma: float,
    option_type: str = "call",
    r: float = None
) -> GreeksResult:
    """
    Calculate option Greeks using Black-Scholes.
    
    FALLBACK HIERARCHY:
    1. If sigma is valid (0.01 <= sigma <= 5.0), use it -> delta_source="BS"
    2. If sigma is missing/invalid, use SIGMA_PROXY_DEFAULT -> delta_source="BS_PROXY_SIGMA"
    3. If even proxy fails, return neutral values -> delta_source="MISSING"
    
    Args:
        S: Current stock price
        K: Strike price
        T: Time to expiration (in years, e.g., 30/365 for 30 DTE)
        sigma: Implied volatility (decimal, e.g., 0.30 for 30%)
        option_type: "call" or "put"
        r: Risk-free rate (defaults to env var or 0.045)
    
    Returns:
        GreeksResult with delta, gamma, theta, vega, and source info
    """
    if r is None:
        r = get_risk_free_rate()
    
    # Determine sigma to use and source
    sigma_used = sigma
    delta_source = "BS"
    
    # Validate IV
    if sigma is None or sigma <= 0.01 or sigma > 5.0:
        # Use sigma proxy
        sigma_used = SIGMA_PROXY_DEFAULT
        delta_source = "BS_PROXY_SIGMA"
    
    # Handle edge cases
    if S <= 0 or K <= 0:
        return GreeksResult(
            delta=0.0,
            gamma=0.0,
            theta=0.0,
            vega=0.0,
            delta_source="MISSING",
            option_value=0.0,
            r_used=r,
            sigma_used=0.0
        )
    
    if T <= 0:
        # At expiry - intrinsic value only
        if option_type == "call":
            delta = 1.0 if S > K else 0.0
            option_value = max(0, S - K)
        else:
            delta = -1.0 if S < K else 0.0
            option_value = max(0, K - S)
        
        return GreeksResult(
            delta=delta,
            gamma=0.0,
            theta=0.0,
            vega=0.0,
            delta_source="EXPIRY",
            option_value=option_value,
            r_used=r,
            sigma_used=sigma_used
        )
    
    # Calculate d1, d2
    d1, d2 = calculate_d1_d2(S, K, T, r, sigma_used)
    
    if d1 is None:
        # Calculation failed - return neutral values
        return GreeksResult(
            delta=0.5 if option_type == "call" else -0.5,
            gamma=0.0,
            theta=0.0,
            vega=0.0,
            delta_source="MISSING",
            option_value=0.0,
            r_used=r,
            sigma_used=sigma_used
        )
    
    try:
        # Delta
        if option_type == "call":
            delta = norm_cdf(d1)
        else:
            delta = norm_cdf(d1) - 1.0  # Put delta is negative
        
        # Gamma (same for calls and puts)
        gamma = norm_pdf(d1) / (S * sigma_used * math.sqrt(T))
        
        # Theta (per day)
        if option_type == "call":
            theta = (-(S * norm_pdf(d1) * sigma_used) / (2 * math.sqrt(T)) 
                    - r * K * math.exp(-r * T) * norm_cdf(d2)) / 365
        else:
            theta = (-(S * norm_pdf(d1) * sigma_used) / (2 * math.sqrt(T)) 
                    + r * K * math.exp(-r * T) * norm_cdf(-d2)) / 365
        
        # Vega (per 1% change in IV)
        vega = S * math.sqrt(T) * norm_pdf(d1) / 100
        
        # Option value
        if option_type == "call":
            option_value = calculate_call_price_bs(S, K, T, r, sigma_used)
        else:
            option_value = calculate_put_price_bs(S, K, T, r, sigma_used)
        
        # Validate delta bounds
        if option_type == "call":
            delta = max(0.0, min(1.0, delta))
        else:
            delta = max(-1.0, min(0.0, delta))
        
        # Check for NaN
        if math.isnan(delta) or math.isnan(gamma) or math.isnan(theta) or math.isnan(vega):
            return GreeksResult(
                delta=0.5 if option_type == "call" else -0.5,
                gamma=0.0,
                theta=0.0,
                vega=0.0,
                delta_source="MISSING",
                option_value=0.0,
                r_used=r,
                sigma_used=sigma_used
            )
        
        return GreeksResult(
            delta=round(delta, 4),
            gamma=round(gamma, 6),
            theta=round(theta, 4),
            vega=round(vega, 4),
            delta_source=delta_source,
            option_value=round(option_value, 2),
            r_used=r,
            sigma_used=sigma_used
        )
        
    except (ValueError, ZeroDivisionError, OverflowError) as e:
        logger.warning(f"Greeks calculation error: {e}")
        return GreeksResult(
            delta=0.5 if option_type == "call" else -0.5,
            gamma=0.0,
            theta=0.0,
            vega=0.0,
            delta_source="MISSING",
            option_value=0.0,
            r_used=r,
            sigma_used=sigma_used
        )


def validate_iv(iv: float) -> Tuple[float, bool]:
    """
    Validate and normalize IV value.
    
    Args:
        iv: Implied volatility (may be decimal or percentage)
    
    Returns:
        Tuple of (normalized_iv_decimal, is_valid)
    """
    if iv is None:
        return 0.0, False
    
    # Handle NaN
    if isinstance(iv, float) and math.isnan(iv):
        return 0.0, False
    
    # If IV looks like percentage (> 5), assume it's already in percentage form
    # This shouldn't happen with Yahoo data, but handle it gracefully
    if iv > 5.0:
        iv = iv / 100.0
    
    # Reject unrealistic values
    if iv < 0.01 or iv > 5.0:
        return 0.0, False
    
    return iv, True


def normalize_iv_fields(iv_raw: float) -> Dict[str, Any]:
    """
    Normalize IV to both decimal and percentage forms.
    
    Args:
        iv_raw: Raw IV value from data source
    
    Returns:
        Dict with iv (decimal), iv_pct (percentage), iv_valid
    """
    iv_decimal, is_valid = validate_iv(iv_raw)
    
    return {
        "iv": round(iv_decimal, 4) if is_valid else 0.0,
        "iv_pct": round(iv_decimal * 100, 1) if is_valid else 0.0,
        "iv_valid": is_valid
    }


# =============================================================================
# SANITY CHECK HELPERS
# =============================================================================

def sanity_check_delta(delta: float, option_type: str) -> Tuple[bool, str]:
    """
    Validate delta is within expected bounds.
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if math.isnan(delta):
        return False, "Delta is NaN"
    
    if option_type == "call":
        if delta < 0 or delta > 1:
            return False, f"Call delta {delta} not in [0, 1]"
    else:
        if delta < -1 or delta > 0:
            return False, f"Put delta {delta} not in [-1, 0]"
    
    return True, ""


def sanity_check_iv(iv: float) -> Tuple[bool, str]:
    """
    Validate IV is within expected bounds.
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if iv is None:
        return False, "IV is None"
    
    if isinstance(iv, float) and math.isnan(iv):
        return False, "IV is NaN"
    
    if iv < 0 or iv > 5.0:
        return False, f"IV {iv} not in (0, 5)"
    
    return True, ""
