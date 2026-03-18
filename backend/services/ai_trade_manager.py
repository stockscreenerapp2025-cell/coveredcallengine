# backend/services/ai_trade_manager.py
"""
AI Trade Manager — rule-aware recommendation engine.

Rules come first. The AI applies user rules to current trade conditions
and recommends the best action within those boundaries.

Called by POST /simulator/manage/{trade_id}
"""

from datetime import datetime, timezone
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ─── Defaults (used when no rule_config provided) ─────────────────────────────
DEFAULT_CLOSE_CAPTURE_PCT   = 80.0   # close when premium capture >= this %
DEFAULT_ROLL_DTE            = 21     # start considering roll at this DTE
DEFAULT_HARD_ROLL_DTE       = 7      # must roll/decide at this DTE
DEFAULT_AVOID_ASSIGNMENT    = True   # default: avoid assignment
DEFAULT_MIN_WEEKLY_RETURN   = 1.0    # minimum 1% weekly for new short call
MIN_DELTA_SHORT_CALL        = 0.15
MAX_DELTA_SHORT_CALL        = 0.35
DCA_DROP_THRESHOLD_PCT      = 10.0


# ─── Main Entry Point ─────────────────────────────────────────────────────────

async def generate_recommendation(
    trade: dict,
    current_price: float,
    options_chain: list,
    goals: dict,
    rule_config: dict = None
) -> dict:
    """
    Analyze a trade using the user's rule set and produce a structured recommendation.

    Returns:
        {
            "action": str,
            "reasoning": [str, ...],
            "metrics": { stock_price, strike, distance_to_strike_pct, breakeven, ... },
            "confidence": int (0-100),
            "confidence_basis": [str, ...],
            "actions": [ { type, label, description, primary, ... }, ... ],
            "rule_applied": str or None,
            "warnings": [str, ...]
        }
    """
    # ── Extract trade fields ──────────────────────────────────────────────────
    dte           = max(trade.get("dte_remaining", 0), 0)
    short_strike  = float(trade.get("short_call_strike", 0))
    entry_price   = float(trade.get("entry_underlying_price", current_price))
    entry_premium = float(trade.get("short_call_premium", 0))
    contracts     = int(trade.get("contracts", 1))
    strategy      = trade.get("strategy_type", "covered_call")
    premium_capture_pct = float(trade.get("premium_capture_pct", 0))
    current_delta = float(trade.get("current_delta") or trade.get("short_call_delta") or 0)
    unrealized_pnl = float(trade.get("unrealized_pnl") or 0)

    # ── Extract user rules ────────────────────────────────────────────────────
    rc       = rule_config or {}
    controls = rc.get("controls", {})
    summary  = rc.get("summary", {})

    # Hard rules
    avoid_assignment   = summary.get("avoid_assignment", DEFAULT_AVOID_ASSIGNMENT)
    close_capture_pct  = float(controls.get("close_at_capture_pct", DEFAULT_CLOSE_CAPTURE_PCT))
    roll_dte_trigger   = int(controls.get("roll_dte_trigger", DEFAULT_ROLL_DTE))
    hard_roll_dte      = int(controls.get("hard_roll_dte", DEFAULT_HARD_ROLL_DTE))
    no_debit_roll      = bool(controls.get("no_debit_roll", True))
    min_weekly         = float(goals.get("min_weekly_return_pct", DEFAULT_MIN_WEEKLY_RETURN))
    dca_enabled        = bool(goals.get("dca_enabled", False))

    warnings      = []
    rule_applied  = None

    # ── Compute key metrics ───────────────────────────────────────────────────
    distance_pct = ((short_strike - current_price) / current_price * 100) if current_price > 0 else 0
    itm = current_price >= short_strike
    premium_total = float(trade.get("premium_received_total") or entry_premium * 100 * contracts or 0)
    # Breakeven: for CC = entry - (premium per share); entry_price is per share
    premium_per_share = (entry_premium if entry_premium < current_price else entry_premium / 100)
    breakeven = round(entry_price - premium_per_share, 2)
    capital_used = entry_price * 100 * contracts  # CC default

    if strategy == "pmcc":
        leaps_cost = float(trade.get("leaps_cost") or trade.get("leaps_premium", 0))
        net_debit  = leaps_cost - entry_premium
        capital_used = net_debit * 100 * contracts if net_debit > 0 else leaps_cost * 100 * contracts
        breakeven  = round(net_debit, 2)

    # Estimated option current value (MTM) for open trades
    option_remaining_value = max(0, entry_premium * (1 - premium_capture_pct / 100))

    metrics = {
        "stock_price":            round(current_price, 2),
        "strike":                 short_strike,
        "distance_to_strike_pct": round(distance_pct, 1),
        "in_the_money":           itm,
        "breakeven":              breakeven,
        "dte":                    dte,
        "premium_collected":      round(premium_total, 2),
        "premium_remaining":      round(option_remaining_value * 100 * contracts, 2),
        "premium_capture_pct":    round(premium_capture_pct, 1),
        "current_delta":          round(current_delta, 2),
        "unrealized_pnl":         round(unrealized_pnl, 2),
        "capital_used":           round(capital_used, 2),
    }

    # ── Find possible roll target ─────────────────────────────────────────────
    roll_target = _find_best_short_call(
        options_chain, current_price, contracts,
        min_weekly_pct=min_weekly,
        target_dte_days=30,
        avoid_itm=avoid_assignment
    )

    # ── Build reasoning + determine action ────────────────────────────────────
    reasoning     = []
    confidence    = 75
    conf_basis    = []
    primary_action = "hold"

    # ── RULE: Hard close at capture threshold ────────────────────────────────
    if premium_capture_pct >= close_capture_pct and not itm:
        primary_action = "close"
        rule_applied   = f"Close at {close_capture_pct:.0f}% premium capture"
        reasoning.append(
            f"Premium capture is {premium_capture_pct:.0f}% — exceeds your {close_capture_pct:.0f}% close rule"
        )
        reasoning.append("Closing now locks in profit and frees capital for new opportunities")
        reasoning.append(f"Limited additional reward in holding {dte} more days with theta nearly exhausted")
        confidence  = 90
        conf_basis  = [
            f"Rule triggered: close at {close_capture_pct:.0f}% capture",
            f"Premium capture: {premium_capture_pct:.0f}%",
            f"DTE: {dte}d remaining"
        ]

    # ── RULE: Expiry today — OTM ─────────────────────────────────────────────
    elif dte == 0 and not itm:
        primary_action = "expire_and_write"
        rule_applied   = "Expiry: OTM — write next call"
        reasoning.append(f"Short call expires worthless today — full premium kept")
        reasoning.append(f"Stock at ${current_price:.2f} is OTM vs ${short_strike} strike — no assignment")
        reasoning.append("Next step: write new short call for next cycle income")
        confidence = 95
        conf_basis = ["Expiry day, OTM confirmed", "No assignment risk"]

    # ── RULE: Expiry today — ITM → Assignment ────────────────────────────────
    elif dte == 0 and itm:
        if avoid_assignment and roll_target:
            primary_action = "roll"
            rule_applied   = "Avoid assignment — roll on expiry day"
            reasoning.append(f"Stock at ${current_price:.2f} is ITM vs ${short_strike} strike at expiry")
            reasoning.append("Your rules require avoiding assignment — rolling to next expiry")
            reasoning.append(f"Roll target: ${roll_target['strike']} for {roll_target['dte']}d at ${roll_target['premium']:.2f} credit")
            confidence = 85
            conf_basis = ["Rule: avoid assignment", f"Roll available: ${roll_target['strike']}"]
        else:
            primary_action = "assign"
            rule_applied   = "Allow assignment" if not avoid_assignment else "No roll available — accept assignment"
            reasoning.append(f"Stock at ${current_price:.2f} is ITM vs ${short_strike} at expiry")
            if not avoid_assignment:
                reasoning.append("Your rules allow assignment — shares called away at strike price")
            else:
                reasoning.append("No suitable roll target found — accepting assignment")
            reasoning.append(f"Final P/L: premium kept + stock gain/loss at ${short_strike} strike")
            confidence = 88
            conf_basis = ["Expiry day, ITM", "Assignment confirmed"]

    # ── RULE: Near expiry ITM — roll if avoiding assignment ──────────────────
    elif dte <= hard_roll_dte and itm and avoid_assignment:
        if roll_target:
            primary_action = "roll"
            rule_applied   = f"Roll at {hard_roll_dte}d DTE — ITM + avoid assignment rule"
            reasoning.append(
                f"Strike ${short_strike} is ITM with only {dte}d left — assignment risk is {'high' if current_delta > 0.5 else 'elevated'}"
            )
            reasoning.append("Your rules require avoiding assignment — rolling out now")
            reasoning.append(
                f"Rolling to ${roll_target['strike']} ({roll_target['dte']}d) collects +${roll_target['premium']:.2f} credit"
            )
            confidence = 85
            conf_basis = [
                f"Rule: avoid assignment, roll at {hard_roll_dte}d DTE",
                f"Delta: {current_delta:.2f} (assignment risk)",
                f"Roll credit available: ${roll_target['premium']:.2f}"
            ]
        else:
            warnings.append("No valid roll target found. Consider accepting assignment or adjusting return target.")
            primary_action = "hold"
            reasoning.append(f"ITM with {dte}d left but no suitable roll found meeting your return criteria")
            reasoning.append("Monitor closely — assignment may occur unless stock reverses")
            confidence = 50
            conf_basis = ["No roll target meeting criteria", "Assignment risk elevated"]

    # ── RULE: Near expiry OTM — roll for income if at trigger DTE ────────────
    elif dte <= roll_dte_trigger and not itm and premium_capture_pct >= 75:
        if roll_target:
            primary_action = "roll"
            rule_applied   = f"Roll at {roll_dte_trigger}d DTE — {premium_capture_pct:.0f}% captured"
            reasoning.append(
                f"Premium {premium_capture_pct:.0f}% captured with {dte}d left — near your {roll_dte_trigger}d roll trigger"
            )
            reasoning.append(f"Stock is OTM (${current_price:.2f} vs ${short_strike} strike) — safe to roll")
            reasoning.append(
                f"Rolling to ${roll_target['strike']} ({roll_target['dte']}d) adds +${roll_target['premium']:.2f}/share credit"
            )
            confidence = 78
            conf_basis = [
                f"DTE {dte} within roll trigger ({roll_dte_trigger}d)",
                f"Premium capture: {premium_capture_pct:.0f}%",
                f"OTM: {distance_pct:.1f}% distance"
            ]
        else:
            primary_action = "hold"
            reasoning.append(f"{premium_capture_pct:.0f}% premium captured, {dte}d remaining")
            reasoning.append("No suitable roll target found — holding until expiry is reasonable")
            confidence = 70
            conf_basis = [f"Premium capture {premium_capture_pct:.0f}%", "No roll target"]

    # ── RULE: DCA trigger ────────────────────────────────────────────────────
    elif dca_enabled:
        drop_pct = ((entry_price - current_price) / entry_price * 100) if entry_price > 0 else 0
        if drop_pct >= DCA_DROP_THRESHOLD_PCT:
            primary_action = "dca"
            rule_applied   = f"DCA: stock down {drop_pct:.1f}% from entry"
            reasoning.append(f"Stock dropped {drop_pct:.1f}% from entry ${entry_price:.2f} → ${current_price:.2f}")
            reasoning.append("DCA opportunity to lower cost basis while collecting premium income")
            reasoning.append(f"Adding {contracts} more contract(s) at current level")
            confidence = 65
            conf_basis = [f"DCA enabled, drop {drop_pct:.1f}% > {DCA_DROP_THRESHOLD_PCT}%"]
            warnings.append(f"DCA increases position size — ensure adequate capital (${capital_used * contracts:.0f} additional)")

    # ── Default: HOLD with specific reasoning ────────────────────────────────
    if primary_action == "hold" and not reasoning:
        otm_label = f"{distance_pct:.1f}% OTM" if not itm else f"{abs(distance_pct):.1f}% ITM"
        reasoning.append(
            f"Stock ${current_price:.2f} is {otm_label} vs ${short_strike} strike — {'low' if not itm else 'elevated'} assignment risk"
        )
        if premium_capture_pct < close_capture_pct:
            reasoning.append(
                f"Premium capture {premium_capture_pct:.0f}% is below your {close_capture_pct:.0f}% close threshold — still collecting time value"
            )
        if dte > roll_dte_trigger:
            reasoning.append(f"{dte}d remaining — above your {roll_dte_trigger}d roll trigger, no action required")
        confidence = 80 if not itm else 60
        conf_basis = [
            f"Delta: {current_delta:.2f} ({'low' if current_delta < 0.3 else 'medium'} assignment risk)",
            f"DTE: {dte}d — within holding range",
            f"Capture: {premium_capture_pct:.0f}% of {close_capture_pct:.0f}% target"
        ]
        rule_applied = f"Hold — rules not triggered (close>{close_capture_pct:.0f}%, roll<{roll_dte_trigger}d)"

    # ── Build multi-action list ───────────────────────────────────────────────
    actions = _build_actions(
        primary_action=primary_action,
        trade=trade,
        current_price=current_price,
        roll_target=roll_target,
        contracts=contracts,
        unrealized_pnl=unrealized_pnl,
        no_debit_roll=no_debit_roll,
        short_strike=short_strike
    )

    return {
        "action":         primary_action,
        "reasoning":      reasoning,
        "metrics":        metrics,
        "confidence":     confidence,
        "confidence_basis": conf_basis,
        "actions":        actions,
        "rule_applied":   rule_applied,
        "warnings":       warnings,
        "generated_at":   datetime.now(timezone.utc).isoformat()
    }


def _build_actions(
    primary_action: str,
    trade: dict,
    current_price: float,
    roll_target: Optional[dict],
    contracts: int,
    unrealized_pnl: float,
    no_debit_roll: bool,
    short_strike: float
) -> list:
    """Build list of available actions (primary + alternatives)."""
    actions = []

    # Primary action always first
    action_labels = {
        "hold":          ("Do Nothing", "Maintain current position — let time decay work"),
        "close":         ("Close Position", f"Buy back short call — lock in ${unrealized_pnl:.0f} profit"),
        "roll":          ("Roll Position", "Close current call and open next cycle"),
        "expire_and_write": ("Write Next Call", "Expired worthless — sell next cycle call"),
        "assign":        ("Accept Assignment", "Let shares be called away at strike price"),
        "dca":           ("Average Down (DCA)", "Add contracts at lower price to reduce cost basis"),
    }

    label, desc = action_labels.get(primary_action, ("Execute", "Execute recommended action"))
    actions.append({
        "type":        primary_action,
        "label":       label,
        "description": desc,
        "primary":     True,
        "impact":      f"Recommended based on current conditions and your rules"
    })

    # Always offer "Do Nothing" as alternative unless it IS the primary
    if primary_action != "hold":
        actions.append({
            "type":        "hold",
            "label":       "Do Nothing",
            "description": "Keep position open — accept current risk",
            "primary":     False,
            "impact":      "No change to position"
        })

    # Offer roll if a target exists and it's not already primary
    if roll_target and primary_action not in ("roll", "expire_and_write"):
        credit = roll_target['premium'] * 100 * contracts
        debit_warning = " (may be a debit roll)" if no_debit_roll and credit < 0 else ""
        actions.append({
            "type":        "roll",
            "label":       f"Roll to ${roll_target['strike']} {roll_target['expiry']}",
            "description": f"+${credit:.0f} credit, {roll_target['dte']}d DTE{debit_warning}",
            "primary":     False,
            "impact":      f"Weekly return: {roll_target['weekly_return_pct']:.1f}%",
            "roll_strike": roll_target['strike'],
            "roll_expiry": roll_target['expiry'],
            "roll_premium": roll_target['premium']
        })

    # Offer close if not primary and trade has P/L
    if primary_action not in ("close", "assign") and unrealized_pnl != 0:
        actions.append({
            "type":        "close",
            "label":       "Close Early",
            "description": f"Lock in ${unrealized_pnl:.0f} — free capital for redeployment",
            "primary":     False,
            "impact":      f"Realized P/L: ${unrealized_pnl:.0f}"
        })

    return actions


# ─── Roll Engine ──────────────────────────────────────────────────────────────

def _find_best_short_call(
    options_chain: list,
    current_price: float,
    contracts: int,
    min_weekly_pct: float,
    target_dte_days: int = 30,
    avoid_itm: bool = True
) -> Optional[dict]:
    """Scan options chain for best short call meeting return and delta criteria."""
    candidates = []
    dte_window = 7  # wider window for better matches

    for option in options_chain:
        try:
            strike      = float(option.get("strike", 0))
            premium     = float(option.get("bid", option.get("ask", option.get("last", 0))))
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

        try:
            expiry_dt = datetime.strptime(expiry_str[:10], "%Y-%m-%d")
            dte = (expiry_dt - datetime.now()).days
        except ValueError:
            continue

        if abs(dte - target_dte_days) > dte_window:
            continue
        if dte <= 0:
            continue
        if not (MIN_DELTA_SHORT_CALL <= delta <= MAX_DELTA_SHORT_CALL):
            continue

        weekly_return_pct = (premium / current_price) * (7 / dte) * 100
        if weekly_return_pct < min_weekly_pct:
            continue

        candidates.append({
            "strike":            strike,
            "premium":           premium,
            "delta":             delta,
            "expiry":            expiry_str[:10],
            "dte":               dte,
            "weekly_return_pct": round(weekly_return_pct, 2),
            "total_credit":      round(premium * 100 * contracts, 2)
        })

    if not candidates:
        return None
    candidates.sort(key=lambda x: (-x["weekly_return_pct"], abs(x["dte"] - target_dte_days)))
    return candidates[0]


# ─── Apply Recommendation ─────────────────────────────────────────────────────

def apply_recommendation_to_trade(trade: dict, recommendation: dict, current_price: float) -> dict:
    """
    Mutate a trade document based on an approved recommendation.
    Returns the dict of fields to $set in MongoDB.
    """
    action   = recommendation["action"]
    # Support both old "details" and new "actions" structure
    details  = recommendation.get("details", {})
    # Find primary action details from actions list if available
    actions_list = recommendation.get("actions", [])
    primary = next((a for a in actions_list if a.get("primary")), None)
    if primary:
        details.update({k: v for k, v in primary.items() if k in ("roll_strike", "roll_expiry", "roll_premium")})

    now     = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d")
    updates = {}

    if action in ("expire_and_write", "roll"):
        strike  = float(details.get("strike") or details.get("roll_strike") or details.get("new_strike", 0))
        premium = float(details.get("premium") or details.get("roll_premium") or details.get("new_premium", 0))
        expiry  = details.get("expiry") or details.get("roll_expiry") or details.get("new_expiry", now_str)
        dte_new = int(details.get("dte") or details.get("new_dte", 30))
        old_premium     = float(trade.get("short_call_premium", 0))
        roll_count      = int(trade.get("roll_count", 0)) + 1
        realized_credit = old_premium * 100 * trade.get("contracts", 1)
        updates = {
            "short_call_strike":      strike,
            "short_call_premium":     premium,
            "expiry_date":            expiry,
            "dte_remaining":          dte_new,
            "roll_count":             roll_count,
            "premium_received_total": float(trade.get("premium_received_total", 0)) + realized_credit,
            "last_managed_at":        now_str,
            "last_action":            action,
            "status":                 "open",
        }

    elif action == "assign":
        updates = {
            "status":          "assigned",
            "close_date":      now_str,
            "last_managed_at": now_str,
            "last_action":     "assign",
            "final_pnl":       _calc_final_pnl_on_assign(trade, current_price)
        }

    elif action == "close":
        updates = {
            "status":          "closed",
            "close_date":      now_str,
            "last_managed_at": now_str,
            "last_action":     "close_early",
            "final_pnl":       float(trade.get("unrealized_pnl") or 0)
        }

    elif action == "dca":
        updates = {
            "last_managed_at": now_str,
            "last_action":     "dca_suggested",
            "dca_triggered":   True
        }

    else:  # hold
        updates = {
            "last_managed_at": now_str,
            "last_action":     "hold"
        }

    return updates


def _calc_final_pnl_on_assign(trade: dict, current_price: float) -> float:
    short_strike  = float(trade.get("short_call_strike", current_price))
    entry_price   = float(trade.get("entry_underlying_price", current_price))
    premium_total = float(trade.get("premium_received_total") or trade.get("short_call_premium", 0))
    contracts     = int(trade.get("contracts", 1))
    stock_pnl     = (short_strike - entry_price) * 100 * contracts
    option_pnl    = premium_total * 100 * contracts
    return round(stock_pnl + option_pnl, 2)
