# backend/services/ai_trade_manager.py
"""
AI Trade Manager — deterministic + LLM-assisted recommendation engine.

Handles:
  - Expiry analysis (expire / assign / roll)
  - Roll target selection (next strike/expiry meeting >= 1% weekly)
  - DCA suggestions
  - Structured recommendation output

This is called by POST /simulator/manage/{trade_id}
"""

from datetime import datetime, timezone, timedelta
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ─── Constants ────────────────────────────────────────────────────────────────
MIN_WEEKLY_RETURN_PCT  = 1.0      # minimum 1% weekly for any new short call
ROLL_DTE_THRESHOLD     = 7        # days before expiry to consider rolling
DCA_DROP_THRESHOLD_PCT = 10.0     # % drop in underlying to trigger DCA suggestion
MIN_DELTA_SHORT_CALL   = 0.15     # min delta for short call (avoid too far OTM)
MAX_DELTA_SHORT_CALL   = 0.35     # max delta for short call (avoid too far ITM)


# ─── Main Entry Point ─────────────────────────────────────────────────────────

async def generate_recommendation(trade: dict, current_price: float, options_chain: list, goals: dict) -> dict:
    """
    Analyze a trade and produce a structured recommendation.

    Args:
        trade:          Full trade document from MongoDB
        current_price:  Current underlying price
        options_chain:  List of option contracts from fetch_options_chain()
        goals:          User preferences { min_weekly_return_pct, dca_enabled }

    Returns:
        {
            "action": "hold" | "roll" | "close_and_write" | "expire_and_write" | "assign" | "dca",
            "reason": str,
            "details": { ... action-specific fields ... },
            "confidence": "high" | "medium" | "low",
            "warnings": [str, ...]
        }
    """
    dte           = max(trade.get("dte_remaining", 0), 0)
    short_strike  = float(trade.get("short_call_strike", 0))
    entry_premium = float(trade.get("short_call_premium", 0))
    contracts     = int(trade.get("contracts", 1))
    strategy      = trade.get("strategy_type", "covered_call")
    min_weekly    = float(goals.get("min_weekly_return_pct", MIN_WEEKLY_RETURN_PCT))
    dca_enabled   = bool(goals.get("dca_enabled", False))
    warnings      = []

    # ── Scenario 1: DTE = 0 (expiry today) ──────────────────────────────────
    if dte == 0:
        if current_price >= short_strike:
            # ITM at expiry → assignment
            return _recommendation(
                action="assign",
                reason=f"Short call (${short_strike}) is ITM at expiry with underlying at ${current_price:.2f}. "
                       f"Shares will be called away (covered call) or position assigned (PMCC).",
                details={"short_strike": short_strike, "current_price": current_price},
                confidence="high",
                warnings=warnings
            )
        else:
            # OTM at expiry → expire and write next call
            next_call = _find_best_short_call(
                options_chain, current_price, contracts,
                min_weekly_pct=min_weekly, target_dte_days=7
            )
            if next_call:
                return _recommendation(
                    action="expire_and_write",
                    reason=f"Short call expired worthless (OTM). "
                           f"Writing next call at ${next_call['strike']} for ${next_call['premium']:.2f} credit "
                           f"({next_call['expiry']}, {next_call['dte']}d DTE). "
                           f"Weekly return: {next_call['weekly_return_pct']:.2f}%.",
                    details=next_call,
                    confidence="high",
                    warnings=warnings
                )
            else:
                warnings.append("No suitable strike found meeting the minimum weekly return target. Consider lowering your minimum % or waiting for higher IV.")
                return _recommendation(
                    action="hold",
                    reason="Short call expired worthless but no suitable next strike found meeting your return target.",
                    details={},
                    confidence="low",
                    warnings=warnings
                )

    # ── Scenario 2: Approaching expiry (DTE <= threshold) ───────────────────
    elif dte <= ROLL_DTE_THRESHOLD:
        itm = current_price >= short_strike
        if itm:
            # Approaching expiry ITM → roll out (and possibly up/down)
            next_call = _find_best_short_call(
                options_chain, current_price, contracts,
                min_weekly_pct=min_weekly,
                target_dte_days=21,          # roll further out when ITM
                avoid_itm=True               # try to find OTM strike
            )
            if next_call:
                return _recommendation(
                    action="roll",
                    reason=f"Short call (${short_strike}) is ITM with {dte}d remaining. "
                           f"Rolling to ${next_call['strike']} for {next_call['dte']}d to avoid assignment.",
                    details=next_call,
                    confidence="medium",
                    warnings=warnings
                )
            else:
                warnings.append("Could not find a roll target — consider accepting assignment.")
                return _recommendation(
                    action="assign",
                    reason=f"Short call ITM with {dte}d to expiry. No suitable roll found.",
                    details={"short_strike": short_strike, "current_price": current_price},
                    confidence="medium",
                    warnings=warnings
                )
        else:
            # Approaching expiry OTM → consider early roll to capture remaining premium
            premium_capture_pct = trade.get("premium_capture_pct", 0)
            if premium_capture_pct >= 75:
                next_call = _find_best_short_call(
                    options_chain, current_price, contracts,
                    min_weekly_pct=min_weekly, target_dte_days=14
                )
                if next_call:
                    return _recommendation(
                        action="roll",
                        reason=f"Short call has captured {premium_capture_pct:.0f}% of premium with {dte}d left. "
                               f"Rolling early to capture more income.",
                        details=next_call,
                        confidence="medium",
                        warnings=warnings
                    )

    # ── Scenario 3: DCA check ────────────────────────────────────────────────
    if dca_enabled:
        entry_price = float(trade.get("entry_underlying_price", current_price))
        drop_pct    = ((entry_price - current_price) / entry_price) * 100
        if drop_pct >= DCA_DROP_THRESHOLD_PCT:
            warnings.append(
                f"Underlying has dropped {drop_pct:.1f}% since entry (${entry_price:.2f} → ${current_price:.2f}). "
                f"DCA opportunity: adding shares/LEAPS at lower cost basis."
            )
            return _recommendation(
                action="dca",
                reason=f"Underlying dropped {drop_pct:.1f}% from entry. DCA may lower cost basis.",
                details={
                    "entry_price": entry_price,
                    "current_price": current_price,
                    "drop_pct": round(drop_pct, 2),
                    "suggested_add_contracts": contracts
                },
                confidence="medium",
                warnings=warnings
            )

    # ── Default: Hold ────────────────────────────────────────────────────────
    return _recommendation(
        action="hold",
        reason=f"Trade is healthy. {dte}d remaining, short call at ${short_strike} is {'OTM' if current_price < short_strike else 'ITM'}. No action needed.",
        details={"dte_remaining": dte, "short_strike": short_strike, "current_price": current_price},
        confidence="high",
        warnings=warnings
    )


# ─── Roll Engine ──────────────────────────────────────────────────────────────

def _find_best_short_call(
    options_chain: list,
    current_price: float,
    contracts: int,
    min_weekly_pct: float,
    target_dte_days: int = 7,
    avoid_itm: bool = False
) -> Optional[dict]:
    """
    Scan options chain and find the best short call meeting:
      1. Target DTE window (+/- 3 days of target_dte_days)
      2. Delta between MIN_DELTA and MAX_DELTA
      3. Weekly return >= min_weekly_pct
      4. OTM preferred (if avoid_itm=True, strictly OTM only)

    Returns best candidate or None.
    """
    candidates = []
    dte_window = 3  # days tolerance around target_dte_days

    for option in options_chain:
        # ── Basic filters ──
        try:
            strike      = float(option.get("strike", 0))
            premium     = float(option.get("ask", option.get("last", 0)))
            delta       = abs(float(option.get("delta", 0)))
            expiry_str  = option.get("expiration_date") or option.get("expiry", "")
            option_type = option.get("option_type", option.get("type", "")).lower()
        except (TypeError, ValueError):
            continue

        if option_type not in ("call", "c"):
            continue
        if strike <= 0 or premium <= 0:
            continue
        if avoid_itm and strike <= current_price:
            continue

        # ── DTE check ──
        try:
            expiry_dt = datetime.strptime(expiry_str[:10], "%Y-%m-%d")
            dte = (expiry_dt - datetime.now()).days
        except ValueError:
            continue

        if abs(dte - target_dte_days) > dte_window:
            continue

        # ── Delta check ──
        if not (MIN_DELTA_SHORT_CALL <= delta <= MAX_DELTA_SHORT_CALL):
            continue

        # ── Weekly return check ──
        # Annualize: weekly_return = (premium * 100 * contracts) / (current_price * 100 * contracts) * (7 / dte) * 100
        if dte <= 0:
            continue
        weekly_return_pct = (premium / current_price) * (7 / dte) * 100

        if weekly_return_pct < min_weekly_pct:
            continue

        candidates.append({
            "strike":             strike,
            "premium":            premium,
            "delta":              delta,
            "expiry":             expiry_str[:10],
            "dte":                dte,
            "weekly_return_pct":  round(weekly_return_pct, 2),
            "total_credit":       round(premium * 100 * contracts, 2)
        })

    if not candidates:
        return None

    # Sort: highest weekly return, prefer closer to target DTE
    candidates.sort(key=lambda x: (-x["weekly_return_pct"], abs(x["dte"] - target_dte_days)))
    return candidates[0]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _recommendation(action: str, reason: str, details: dict, confidence: str, warnings: list) -> dict:
    return {
        "action":     action,
        "reason":     reason,
        "details":    details,
        "confidence": confidence,
        "warnings":   warnings,
        "generated_at": datetime.now(timezone.utc).isoformat()
    }


def apply_recommendation_to_trade(trade: dict, recommendation: dict, current_price: float) -> dict:
    """
    Mutate a trade document based on an approved recommendation.
    Returns the dict of fields to $set in MongoDB.

    Called from the /apply endpoint after user approves.
    """
    action   = recommendation["action"]
    details  = recommendation.get("details", {})
    now      = datetime.now(timezone.utc)
    now_str  = now.strftime("%Y-%m-%d")
    updates  = {}

    if action in ("expire_and_write", "roll"):
        # Close old short call, open new one
        old_premium     = float(trade.get("short_call_premium", 0))
        new_strike      = float(details["strike"])
        new_premium     = float(details["premium"])
        new_expiry      = details["expiry"]
        new_dte         = int(details["dte"])
        roll_count      = int(trade.get("roll_count", 0)) + 1

        realized_from_roll = old_premium * 100 * trade.get("contracts", 1)

        updates = {
            "short_call_strike":    new_strike,
            "short_call_premium":   new_premium,
            "expiry_date":          new_expiry,
            "dte_remaining":        new_dte,
            "roll_count":           roll_count,
            "premium_received_total": float(trade.get("premium_received_total", 0)) + realized_from_roll,
            "last_managed_at":      now_str,
            "last_action":          action,
            "status":               "open",
        }

    elif action == "assign":
        updates = {
            "status":          "assigned",
            "close_date":      now_str,
            "last_managed_at": now_str,
            "last_action":     "assign",
            "final_pnl":       _calc_final_pnl_on_assign(trade, current_price)
        }

    elif action == "dca":
        # DCA: just log it — don't auto-change trade fields, let user decide qty
        updates = {
            "last_managed_at": now_str,
            "last_action":     "dca_suggested",
            "dca_triggered":   True
        }

    else:
        # hold or unrecognised
        updates = {
            "last_managed_at": now_str,
            "last_action":     "hold"
        }

    return updates


def _calc_final_pnl_on_assign(trade: dict, current_price: float) -> float:
    """Simplified final P/L when assigned."""
    short_strike    = float(trade.get("short_call_strike", current_price))
    entry_price     = float(trade.get("entry_underlying_price", current_price))
    short_premium   = float(trade.get("short_call_premium", 0))
    premium_total   = float(trade.get("premium_received_total", short_premium))
    contracts       = int(trade.get("contracts", 1))

    stock_pnl   = (short_strike - entry_price) * 100 * contracts
    option_pnl  = premium_total * 100 * contracts  # premium kept
    return round(stock_pnl + option_pnl, 2)
