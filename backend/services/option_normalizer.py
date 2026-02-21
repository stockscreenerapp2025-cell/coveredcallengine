"""
Option Fields Normalizer - Shared Helper for Cross-Page Consistency
===================================================================

SINGLE SOURCE OF TRUTH for normalizing option fields.
Guarantees all endpoints return consistent delta, iv, iv_rank fields.

HARD CONSTRAINTS:
- Never return None/null for delta, iv, iv_pct, iv_rank, iv_percentile
- Always include *_source fields explaining the value origin
- Use Black-Scholes for delta (greeks_service.py)
- Use true IV Rank when history available (iv_rank_service.py)

Call this from:
- screener_snapshot.py
- precomputed_scans.py
- options.py
- snapshots.py
"""

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

from services.greeks_service import (
    calculate_greeks,
    normalize_iv_fields,
    validate_iv,
    GreeksResult
)
from services.iv_rank_service import IVMetrics

logger = logging.getLogger(__name__)


@dataclass
class NormalizedOptionFields:
    """Container for all normalized option fields."""
    # Delta fields
    delta: float
    delta_source: str
    
    # IV fields
    iv: float  # Decimal (e.g., 0.30)
    iv_pct: float  # Percentage (e.g., 30.0)
    
    # IV Rank fields
    iv_rank: float
    iv_percentile: float
    iv_rank_source: str
    iv_samples: int
    
    # Additional Greeks
    gamma: float
    theta: float
    vega: float


def normalize_option_fields(
    option_row: Dict[str, Any],
    stock_price: float,
    dte: int,
    iv_metrics: Optional[IVMetrics] = None,
    option_type: str = "call"
) -> NormalizedOptionFields:
    """
    Normalize all option fields for consistent API response.
    
    This function ensures:
    1. Delta is always computed via Black-Scholes (not moneyness fallback)
    2. IV is always in both decimal and percentage form
    3. IV Rank is always populated (true or neutral fallback)
    4. All *_source fields explain the value origin
    
    Args:
        option_row: Raw option data from chain/snapshot
        stock_price: Current underlying price
        dte: Days to expiration
        iv_metrics: Pre-computed IV metrics (optional, for efficiency)
        option_type: "call" or "put"
    
    Returns:
        NormalizedOptionFields with all fields populated
    """
    # Extract raw values
    strike = option_row.get("strike", 0)
    raw_iv = option_row.get("implied_volatility", 0) or option_row.get("iv", 0)
    
    # ==========================================================================
    # STEP 1: Normalize IV to decimal and percentage
    # ==========================================================================
    iv_data = normalize_iv_fields(raw_iv)
    iv_decimal = iv_data["iv"]
    iv_pct = iv_data["iv_pct"]
    
    # ==========================================================================
    # STEP 2: Calculate Greeks via Black-Scholes
    # ==========================================================================
    T = max(dte, 1) / 365.0  # Time in years
    
    greeks_result = calculate_greeks(
        S=stock_price,
        K=strike,
        T=T,
        sigma=iv_decimal if iv_decimal > 0 else None,
        option_type=option_type
    )
    
    # ==========================================================================
    # STEP 3: Handle IV Rank (from metrics or defaults)
    # ==========================================================================
    if iv_metrics is not None:
        iv_rank = iv_metrics.iv_rank
        iv_percentile = iv_metrics.iv_percentile
        iv_rank_source = iv_metrics.iv_rank_source
        iv_samples = iv_metrics.iv_samples
    else:
        # No metrics provided - use defaults
        iv_rank = 50.0
        iv_percentile = 50.0
        iv_rank_source = "DEFAULT_NEUTRAL_NO_METRICS"
        iv_samples = 0
    
    return NormalizedOptionFields(
        delta=greeks_result.delta,
        delta_source=greeks_result.delta_source,
        iv=iv_decimal,
        iv_pct=iv_pct,
        iv_rank=iv_rank,
        iv_percentile=iv_percentile,
        iv_rank_source=iv_rank_source,
        iv_samples=iv_samples,
        gamma=greeks_result.gamma,
        theta=greeks_result.theta,
        vega=greeks_result.vega
    )


def enrich_option_with_normalized_fields(
    option: Dict[str, Any],
    stock_price: float,
    dte: int,
    iv_metrics: Optional[IVMetrics] = None,
    option_type: str = "call"
) -> Dict[str, Any]:
    """
    Enrich an option dict with normalized fields in-place.
    
    Convenience wrapper that updates the dict directly.
    
    Args:
        option: Option dict to enrich (modified in place)
        stock_price: Current underlying price
        dte: Days to expiration
        iv_metrics: Pre-computed IV metrics (optional)
        option_type: "call" or "put"
    
    Returns:
        The enriched option dict
    """
    normalized = normalize_option_fields(
        option_row=option,
        stock_price=stock_price,
        dte=dte,
        iv_metrics=iv_metrics,
        option_type=option_type
    )
    
    # Update option dict with normalized fields
    option["delta"] = normalized.delta
    option["delta_source"] = normalized.delta_source
    option["iv"] = normalized.iv
    option["iv_pct"] = normalized.iv_pct
    option["iv_rank"] = normalized.iv_rank
    option["iv_percentile"] = normalized.iv_percentile
    option["iv_rank_source"] = normalized.iv_rank_source
    option["iv_samples"] = normalized.iv_samples
    option["gamma"] = normalized.gamma
    option["theta"] = normalized.theta
    option["vega"] = normalized.vega
    
    return option


def build_option_response_fields(
    normalized: NormalizedOptionFields
) -> Dict[str, Any]:
    """
    Convert NormalizedOptionFields to a dict for JSON response.
    
    Args:
        normalized: NormalizedOptionFields instance
    
    Returns:
        Dict suitable for JSON serialization
    """
    return {
        "delta": normalized.delta,
        "delta_source": normalized.delta_source,
        "gamma": normalized.gamma,
        "theta": normalized.theta,
        "vega": normalized.vega,
        "iv": normalized.iv,
        "iv_pct": normalized.iv_pct,
        "iv_rank": normalized.iv_rank,
        "iv_percentile": normalized.iv_percentile,
        "iv_rank_source": normalized.iv_rank_source,
        "iv_samples": normalized.iv_samples
    }


# =============================================================================
# COMPLETENESS VALIDATION
# =============================================================================

REQUIRED_FIELDS = [
    "delta", "delta_source",
    "iv", "iv_pct",
    "iv_rank", "iv_percentile", "iv_rank_source", "iv_samples"
]


def validate_option_completeness(option: Dict[str, Any]) -> tuple[bool, list[str]]:
    """
    Validate that an option dict has all required fields populated.
    
    Args:
        option: Option dict to validate
    
    Returns:
        Tuple of (is_complete, missing_fields)
    """
    missing = []
    
    for field in REQUIRED_FIELDS:
        if field not in option or option[field] is None:
            missing.append(field)
    
    return len(missing) == 0, missing


def validate_batch_completeness(options: list[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Validate completeness for a batch of options.
    
    Args:
        options: List of option dicts
    
    Returns:
        Dict with validation results
    """
    total = len(options)
    complete = 0
    incomplete = 0
    missing_by_field = {field: 0 for field in REQUIRED_FIELDS}
    
    for opt in options:
        is_complete, missing = validate_option_completeness(opt)
        if is_complete:
            complete += 1
        else:
            incomplete += 1
            for field in missing:
                missing_by_field[field] += 1
    
    return {
        "total": total,
        "complete": complete,
        "incomplete": incomplete,
        "completeness_pct": round(complete / total * 100, 1) if total > 0 else 100.0,
        "missing_by_field": missing_by_field
    }
