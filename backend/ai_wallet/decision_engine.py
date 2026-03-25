"""
AI Trade Management Decision Engine
====================================
Deterministic rule-based engine for covered call trade management.
AI provides narrative ONLY — all decisions are made here.

Priority order (from spec):
  1. Avoid wrong realised loss
  2. Preserve income opportunity
  3. Preserve recovery opportunity
  4. Consider averaging only when sensible
  5. Never force a trade
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from math import log1p


# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

DRAWDOWN_MILD_THRESHOLD     = -0.05   # stock < BE by 5-15%
DRAWDOWN_MODERATE_THRESHOLD = -0.15   # stock < BE by 15-30%
DRAWDOWN_SEVERE_THRESHOLD   = -0.30   # stock < BE by >30%

MIN_WEEKLY_ROI  = 0.010   # 1.0% of current price
MIN_MONTHLY_ROI = 0.020   # 2.0% of current price

WEEKLY_MAX_DTE  = 21
MONTHLY_MIN_DTE = 21
MONTHLY_MAX_DTE = 60

MIN_OI          = 50
MIN_BID         = 0.10
MAX_SPREAD_PCT  = 0.40    # (ask-bid)/mid

# Weighted scoring per strategy mode
_MODE_WEIGHTS: Dict[str, Dict[str, float]] = {
    "INCOME_MAXIMIZER": {
        "roi": 0.40, "strike_quality": 0.15,
        "be_protection": 0.10, "liquidity": 0.20, "recovery": 0.15,
    },
    "BALANCED": {
        "roi": 0.25, "strike_quality": 0.20,
        "be_protection": 0.25, "liquidity": 0.15, "recovery": 0.15,
    },
    "CAPITAL_PROTECTION": {
        "roi": 0.10, "strike_quality": 0.10,
        "be_protection": 0.40, "liquidity": 0.15, "recovery": 0.25,
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# Data Classes
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class PositionState:
    symbol: str
    current_price: float
    entry_price: float
    break_even: float
    shares: int
    dte: int                    # may be negative (already expired)
    unrealized_pnl: float
    premium_received: float
    last_strike: float          # strike of the most recent short call
    strategy_mode: str          # INCOME_MAXIMIZER | BALANCED | CAPITAL_PROTECTION
    drawdown_flag: str          # none | mild | moderate | severe
    pct_from_be: float          # (current - be) / be  (negative = below BE)
    strategy: str = "CC"


@dataclass
class OptionCandidate:
    strike: float
    expiry: str
    dte: int
    bid: float
    ask: float
    oi: int
    volume: int
    iv: float
    roi_pct: float              # bid / current_price * 100
    is_weekly: bool = False
    score: float = 0.0


# ──────────────────────────────────────────────────────────────────────────────
# Position State Evaluation
# ──────────────────────────────────────────────────────────────────────────────

def evaluate_position_state(trade: Dict, current_price: float) -> PositionState:
    """
    Build PositionState from a trade document and live current_price.
    Strategy mode is auto-determined from drawdown severity.
    """
    entry  = float(trade.get("entry_price") or 0)
    be     = float(trade.get("break_even") or entry)
    shares = int(trade.get("shares") or trade.get("quantity") or 0)
    dte    = int(trade.get("_dte_computed") if "_dte_computed" in trade else (trade.get("dte") or 0))
    prem   = float(trade.get("premium_received") or trade.get("total_premium") or 0)
    strike = float(trade.get("option_strike") or trade.get("short_call_strike") or 0)
    upnl   = float(trade.get("unrealized_pnl") or 0)

    # How far is current price from break-even?
    pct_from_be = ((current_price - be) / be) if be > 0 else 0.0

    if pct_from_be >= DRAWDOWN_MILD_THRESHOLD:
        drawdown_flag = "none"
    elif pct_from_be >= DRAWDOWN_MODERATE_THRESHOLD:
        drawdown_flag = "mild"
    elif pct_from_be >= DRAWDOWN_SEVERE_THRESHOLD:
        drawdown_flag = "moderate"
    else:
        drawdown_flag = "severe"

    # Auto-determine mode from drawdown
    if drawdown_flag == "severe":
        mode = "CAPITAL_PROTECTION"
    elif drawdown_flag == "moderate":
        mode = "BALANCED"
    else:
        mode = "BALANCED"

    return PositionState(
        symbol=trade.get("symbol", ""),
        current_price=current_price,
        entry_price=entry,
        break_even=be,
        shares=shares,
        dte=dte,
        unrealized_pnl=upnl,
        premium_received=prem,
        last_strike=strike,
        strategy_mode=mode,
        drawdown_flag=drawdown_flag,
        pct_from_be=pct_from_be,
        strategy=trade.get("strategy_type", "CC"),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Candidate Building & Filtering
# ──────────────────────────────────────────────────────────────────────────────

def _is_liquid(bid: float, ask: float, oi: int) -> bool:
    if bid < MIN_BID:
        return False
    if oi < MIN_OI:
        return False
    mid = (bid + ask) / 2 if ask > 0 else bid
    if mid > 0 and (ask - bid) / mid > MAX_SPREAD_PCT:
        return False
    return True


def build_valid_call_candidates(
    calls: List[Dict],
    state: PositionState,
) -> List[OptionCandidate]:
    """
    Filter raw option chain into valid covered-call candidates.
    Rules enforced:
    - OTM only (strike > current_price)
    - Liquidity gates (bid, OI, spread)
    - ROI minimums (weekly ≥1%, monthly ≥2%)
    - Break-even protection per strategy mode
    """
    cp   = state.current_price
    be   = state.break_even
    mode = state.strategy_mode
    candidates = []

    for c in calls:
        strike = float(c.get("strike") or 0)
        bid    = float(c.get("bid") or 0)
        ask    = float(c.get("ask") or 0)
        dte_c  = int(c.get("dte") or 0)
        oi     = int(c.get("open_interest") or c.get("oi") or 0)
        vol    = int(c.get("volume") or 0)
        iv     = float(c.get("implied_volatility") or c.get("iv") or 0)

        # Must be OTM
        if strike <= cp:
            continue

        # Liquidity gate
        if not _is_liquid(bid, ask, oi):
            continue

        is_weekly = dte_c <= WEEKLY_MAX_DTE
        min_roi   = MIN_WEEKLY_ROI if is_weekly else MIN_MONTHLY_ROI
        roi       = (bid / cp) if cp > 0 else 0.0

        if roi < min_roi:
            continue

        # Break-even protection filters
        if mode == "CAPITAL_PROTECTION" and strike < be:
            continue  # Hard rule: no strikes below BE in protection mode
        if mode == "BALANCED" and state.drawdown_flag in ("moderate", "severe"):
            if strike < (be * 0.90):
                continue  # Skip strikes materially below BE when underwater

        candidates.append(OptionCandidate(
            strike=strike, expiry=c.get("expiry") or "",
            dte=dte_c, bid=bid, ask=ask, oi=oi, volume=vol, iv=iv,
            roi_pct=roi * 100, is_weekly=is_weekly,
        ))

    return candidates


# ──────────────────────────────────────────────────────────────────────────────
# Candidate Ranking
# ──────────────────────────────────────────────────────────────────────────────

def _score_candidate(c: OptionCandidate, state: PositionState) -> float:
    cp   = state.current_price
    be   = state.break_even
    mode = state.strategy_mode
    w    = _MODE_WEIGHTS[mode]

    # 1. ROI score (0-1) — normalised against 5% reference
    roi_score = min(c.roi_pct / 5.0, 1.0)

    # 2. Strike quality — higher OTM = better (0-1)
    denom = cp * 0.10 + 1e-9
    strike_score = max(0.0, min((c.strike - cp) / denom, 1.0))

    # 3. Break-even protection — strike above/below BE (0-1)
    if be > 0:
        if c.strike >= be:
            be_score = min((c.strike - be) / (be * 0.05 + 1e-9), 1.0)
            be_score = max(0.0, be_score)
        else:
            # Penalise proportionally to how far below BE
            be_score = max(0.0, 1.0 + (c.strike - be) / be)
    else:
        be_score = 0.5

    # 4. Liquidity score (0-1)
    liq_score = min(log1p(c.oi) / log1p(1000), 1.0)

    # 5. Recovery preservation — would assignment be profitable vs BE?
    if cp > 0 and be > 0:
        recovery_score = max(0.0, min((c.strike - be) / be + 0.5, 1.0))
    else:
        recovery_score = 0.5

    total = (
        w["roi"]            * roi_score
        + w["strike_quality"] * strike_score
        + w["be_protection"]  * be_score
        + w["liquidity"]      * liq_score
        + w["recovery"]       * recovery_score
    )
    return round(total, 4)


def rank_candidates(
    candidates: List[OptionCandidate],
    state: PositionState,
) -> List[OptionCandidate]:
    """
    Rank all valid candidates by weighted score.
    Tie-break: prefer higher strike (spec: choose highest strike that meets threshold).
    """
    for c in candidates:
        c.score = _score_candidate(c, state)
    return sorted(candidates, key=lambda c: (c.score, c.strike), reverse=True)


# ──────────────────────────────────────────────────────────────────────────────
# DCA Averaging Check
# ──────────────────────────────────────────────────────────────────────────────

def should_consider_dca(state: PositionState, sentiment_score: float = 0.0) -> bool:
    """
    DCA / CSP averaging is optional and conditional — never automatic.
    Only suggest when:
    - Drawdown is moderate or severe
    - Sentiment is not sharply negative (fundamentals not broken)
    """
    if state.drawdown_flag not in ("moderate", "severe"):
        return False
    if sentiment_score < -0.5:
        return False  # Avoid averaging into deteriorating fundamentals
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Sub-decision Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _assignment_risk_note(c: OptionCandidate, state: PositionState) -> str:
    be = state.break_even
    if c.strike >= be:
        return (
            f"Assignment at ${c.strike:.2f} would be at or above break-even "
            f"(${be:.2f}) — acceptable outcome."
        )
    loss_pct = (be - c.strike) / be * 100
    return (
        f"Assignment at ${c.strike:.2f} would realise a loss of {loss_pct:.1f}% "
        f"relative to break-even (${be:.2f}). Only accept in INCOME_MAXIMIZER mode."
    )


def _recovery_insight(state: PositionState) -> str:
    flag = state.drawdown_flag
    if flag == "none":
        return "Position is near or above break-even. Income-focused strategy is appropriate."
    if flag == "mild":
        return "Mild drawdown. Selling a slightly OTM call balances income and recovery upside."
    if flag == "moderate":
        return (
            "Moderate drawdown. Avoid strikes too far below break-even. "
            "Recovery potential matters more than premium alone."
        )
    return (
        "Severe drawdown. Prioritize recovery over income. "
        "Only sell calls at strike levels that do not lock in unacceptable losses."
    )


def _standard_management(state: PositionState) -> Dict:
    """DTE > 1: HOLD, MONITOR_CLOSELY, or ROLL."""
    cp     = state.current_price
    strike = state.last_strike
    dte    = state.dte
    itm    = (strike > 0 and cp > strike)

    if itm and dte <= 7:
        return _decision(
            action="MONITOR_CLOSELY",
            reason=(
                f"Stock (${cp:.2f}) is above the current call strike (${strike:.2f}) "
                f"with {dte} DTE. Assignment probability is elevated."
            ),
            risk_note="Consider rolling to avoid assignment if retaining shares is preferred.",
            insight="If assignment is acceptable, let the position run. Otherwise act now.",
            state=state,
        )
    if itm and dte > 7:
        return _decision(
            action="ROLL",
            reason=(
                f"Stock (${cp:.2f}) is above strike (${strike:.2f}) with {dte} DTE. "
                "Rolling up and out is worth evaluating."
            ),
            risk_note="Rolling captures additional premium while deferring or avoiding assignment.",
            insight="Roll to a higher strike on a later expiry if you want to retain the shares.",
            state=state,
        )
    return _decision(
        action="HOLD",
        reason=f"Option is OTM with {dte} DTE. Time decay is working. No action required.",
        risk_note="Monitor as expiry approaches. Reassess if price rallies toward the strike.",
        insight="Let theta work. Re-evaluate closer to expiry.",
        state=state,
    )


def _near_expiry_management(state: PositionState) -> Dict:
    """DTE = 1: LET_EXPIRE, EXPECT_ASSIGNMENT, or MONITOR_CLOSELY."""
    cp     = state.current_price
    strike = state.last_strike
    itm    = (strike > 0 and cp > strike)

    if itm:
        return _decision(
            action="EXPECT_ASSIGNMENT",
            reason=(
                f"Option expires tomorrow and is ITM (stock ${cp:.2f} > strike ${strike:.2f}). "
                "Assignment is very likely."
            ),
            risk_note="Shares will be called away at the strike price. Last chance to roll if preferred.",
            insight="If you want to keep shares, rolling now is the final opportunity before expiry.",
            state=state,
        )
    return _decision(
        action="LET_EXPIRE",
        reason=(
            f"Option expires tomorrow OTM (stock ${cp:.2f} < strike ${strike:.2f}). "
            "Will likely expire worthless."
        ),
        risk_note="Shares are retained. Prepare to evaluate a new covered call after expiry.",
        insight="Full premium captured. Assess new call candidates for the next cycle.",
        state=state,
    )


def _decision(
    action: str, reason: str, risk_note: str, insight: str,
    state: PositionState, suggested_trade: Optional[Dict] = None,
    alternatives: Optional[List[Dict]] = None,
) -> Dict:
    return {
        "action":           action,
        "reason":           reason,
        "suggested_trade":  suggested_trade,
        "alternatives":     alternatives or [],
        "risk_note":        risk_note,
        "strategy_insight": insight,
        "drawdown_flag":    state.drawdown_flag,
        "strategy_mode":    state.strategy_mode,
        "pct_from_be":      round(state.pct_from_be * 100, 1),
        "current_price":    state.current_price,
        "break_even":       state.break_even,
        "entry_price":      state.entry_price,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Main Entry Point
# ──────────────────────────────────────────────────────────────────────────────

def generate_cc_decision(
    state: PositionState,
    all_calls: List[Dict],
    sentiment_score: float = 0.0,
) -> Dict[str, Any]:
    """
    Deterministic CC decision engine.

    Returns a structured decision dict that the AI narrative layer uses
    to generate the final user-facing explanation.

    Args:
        state:           Evaluated position state
        all_calls:       Raw option chain (calls only, any DTE)
        sentiment_score: Overall news/sentiment score (-1 to 1)
    """
    cp   = state.current_price
    be   = state.break_even
    dte  = state.dte
    mode = state.strategy_mode

    # ── No shares remaining ───────────────────────────────────────────────────
    if state.shares <= 0:
        return _decision(
            action="EXPECT_ASSIGNMENT",
            reason="Shares have been called away. No covered call position remains.",
            risk_note="No covered call can be sold until shares are reacquired.",
            insight=(
                "Consider re-entry via a cash-secured put if you still have conviction "
                "in the underlying stock."
            ),
            state=state,
        )

    # ── DTE > 1: standard management ─────────────────────────────────────────
    if dte > 1:
        return _standard_management(state)

    # ── DTE = 1: near expiry ──────────────────────────────────────────────────
    if dte == 1:
        return _near_expiry_management(state)

    # ── DTE ≤ 0: option has expired — determine next action ──────────────────
    # Non-negotiable: do not end here. Must choose a forward-looking action.

    candidates = build_valid_call_candidates(all_calls, state)
    ranked     = rank_candidates(candidates, state)

    if ranked:
        best = ranked[0]
        return _decision(
            action="SELL_ANOTHER_CALL",
            reason=(
                f"Option has expired {'worthless' if cp < (state.last_strike or cp + 1) else 'ITM'}. "
                f"Stock is {'above' if cp >= be else 'below'} break-even (${be:.2f}). "
                f"A valid covered call candidate was identified from {len(ranked)} screened option(s)."
            ),
            risk_note=_assignment_risk_note(best, state),
            insight=_recovery_insight(state),
            state=state,
            suggested_trade={
                "strike":              best.strike,
                "expiry":              best.expiry,
                "dte":                 best.dte,
                "bid":                 best.bid,
                "ask":                 best.ask,
                "roi_pct":             round(best.roi_pct, 2),
                "type":                "weekly" if best.is_weekly else "monthly",
                "score":               best.score,
                "total_candidates":    len(ranked),
                "strike_vs_be":        round(best.strike - be, 2),
            },
            alternatives=[
                {
                    "strike":   c.strike,
                    "expiry":   c.expiry,
                    "dte":      c.dte,
                    "roi_pct":  round(c.roi_pct, 2),
                    "score":    c.score,
                }
                for c in ranked[1:3]
            ],
        )

    # No valid candidates found
    if should_consider_dca(state, sentiment_score):
        return _decision(
            action="CONSIDER_CSP_AVERAGING",
            reason=(
                f"No covered call candidate meets strike, ROI, and recovery requirements. "
                f"Stock is {abs(state.pct_from_be) * 100:.1f}% below break-even (${be:.2f}). "
                "Averaging may improve future covered call flexibility."
            ),
            risk_note=(
                "Averaging increases capital exposure. "
                "Only appropriate if conviction remains strong and additional capital is available."
            ),
            insight=(
                "Selling a CSP or buying shares at the lower price can reduce your break-even "
                "and open up better strike options on the next covered call cycle."
            ),
            state=state,
        )

    return _decision(
        action="DO_NOTHING",
        reason=(
            f"No suitable covered call currently meets strike, ROI, and recovery requirements. "
            f"Stock is {abs(state.pct_from_be) * 100:.1f}% from break-even (${be:.2f}). "
            "Forcing a trade would risk locking in an unacceptable loss."
        ),
        risk_note=(
            "Waiting is better than forcing a trade that may realise a large loss. "
            "Reassess after price recovery or when better premiums become available."
        ),
        insight=(
            "If sentiment deteriorates further, consider reviewing position conviction. "
            "Do not sell a call purely because premium exists — recovery must be preserved."
        ),
        state=state,
    )
