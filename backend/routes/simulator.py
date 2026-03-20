"""
Simulator Routes - Trade simulation and management endpoints
Designed for forward-running simulation of covered call and PMCC strategies

DATA FETCHING RULES:
- Rule #2: Simulator and Watchlist use LIVE intraday prices (regularMarketPrice)
- This ensures accurate P&L tracking during market hours

TRADE LIFECYCLE MODEL:
Covered Call (CC):
  - OPEN: Call sold, position active
  - EXPIRED: Call expires OTM (win)
  - ASSIGNED: Shares called away (win for CC, loss risk for PMCC)
  - CLOSED: Manually closed or finalized

PMCC:
  - OPEN: Long LEAPS + short call active
  - ROLLED: Short call closed and replaced with new short call
  - ASSIGNED: Short call assigned (BAD - avoid this!)
  - CLOSED: PMCC fully exited

CRITICAL RULE: ASSIGNED = CLOSED for analytics/reporting purposes
"""
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta
import logging
import math
import uuid

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import db
from utils.auth import get_current_user

# Import LIVE price function for simulator (Rule #2)
from services.data_provider import fetch_live_stock_quote, fetch_options_chain

# CCE Volatility & Greeks Correctness - Use shared Greeks service
from services.greeks_service import (
    calculate_greeks as calculate_greeks_bs,
    normalize_iv_fields,
    get_risk_free_rate
)
# Import enrichment service for IV Rank and Analyst data
from services.enrichment_service import enrich_row, strip_enrichment_debug
# AI Trade Manager imports
try:
    from services.wallet_service import debit_wallet, get_balance, MANAGE_COST_CREDITS, APPLY_COST_CREDITS, credit_wallet
    from services.ai_trade_manager import generate_recommendation, apply_recommendation_to_trade
    _MANAGE_AVAILABLE = True
except ImportError:
    _MANAGE_AVAILABLE = False

simulator_router = APIRouter(tags=["Simulator"])

# Valid lifecycle statuses
CC_STATUSES = ["open", "expired", "assigned", "closed"]
PMCC_STATUSES = ["open", "rolled", "assigned", "closed"]
ALL_STATUSES = ["open", "rolled", "expired", "assigned", "closed"]
COMPLETED_STATUSES = ["expired", "assigned", "closed"]  # For analytics - ASSIGNED = CLOSED


# ==================== BLACK-SCHOLES CALCULATIONS ====================
# NOTE: These local functions are kept for backward compatibility.
# New code should use services/greeks_service.py

def calculate_d1_d2(S, K, T, r, sigma):
    """Calculate d1 and d2 for Black-Scholes"""
    if T <= 0 or sigma <= 0:
        return None, None
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return d1, d2

def norm_cdf(x):
    """Cumulative distribution function for standard normal"""
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

def norm_pdf(x):
    """Probability density function for standard normal"""
    return math.exp(-0.5 * x ** 2) / math.sqrt(2 * math.pi)

def calculate_call_price(S, K, T, r, sigma):
    """Calculate Black-Scholes call option price"""
    if T <= 0:
        return max(0, S - K)  # Intrinsic value at expiry
    if sigma <= 0:
        return max(0, S - K)
    
    d1, d2 = calculate_d1_d2(S, K, T, r, sigma)
    if d1 is None:
        return max(0, S - K)
    
    return S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)

def calculate_greeks(S, K, T, r, sigma):
    """
    Calculate option Greeks using shared greeks_service.
    
    CCE VOLATILITY & GREEKS CORRECTNESS:
    This function now delegates to the shared greeks_service for consistency.
    
    S: Current stock price
    K: Strike price
    T: Time to expiration (in years)
    r: Risk-free rate (default from env or 4.5%)
    sigma: Implied volatility (decimal form)
    
    Returns: dict with delta, gamma, theta, vega, option_value
    """
    # Delegate to shared Greeks service
    greeks_result = calculate_greeks_bs(
        S=S, K=K, T=T, sigma=sigma, option_type="call", r=r
    )
    
    # Return in legacy format for backward compatibility
    return {
        "delta": greeks_result.delta,
        "gamma": greeks_result.gamma,
        "theta": greeks_result.theta,
        "vega": greeks_result.vega,
        "option_value": greeks_result.option_value,
        "delta_source": greeks_result.delta_source  # New field
    }


# ==================== PYDANTIC MODELS ====================

class SimulatorTradeEntry(BaseModel):
    """Model for adding a trade to the simulator"""
    symbol: str
    strategy_type: str  # "covered_call" or "pmcc"
    
    # Stock/LEAPS Entry
    underlying_price: float
    
    # Short Call Details
    short_call_strike: float
    short_call_expiry: str
    short_call_premium: float
    short_call_delta: Optional[float] = None
    short_call_iv: Optional[float] = None
    
    # For PMCC - LEAPS details
    leaps_strike: Optional[float] = None
    leaps_expiry: Optional[str] = None
    leaps_premium: Optional[float] = None
    leaps_delta: Optional[float] = None
    
    # Position sizing
    contracts: int = 1
    
    # Scan metadata (for feedback loop)
    scan_parameters: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None


class TradeRuleCreate(BaseModel):
    """Model for creating trade management rules"""
    name: str
    description: Optional[str] = None
    rule_type: str  # "profit_target", "stop_loss", "time_based", "delta_target", "roll", "custom"
    
    # Conditions (all must be met)
    conditions: List[Dict[str, Any]]  # [{"field": "premium_capture_pct", "operator": ">=", "value": 50}]
    
    # Action to take
    action: str  # "close", "roll_out", "roll_up", "alert", "custom"
    action_params: Optional[Dict[str, Any]] = None
    
    # Priority and settings
    priority: int = 0
    is_enabled: bool = True


class StrategyControls(BaseModel):
    model_config = ConfigDict(extra='ignore')
    avoid_early_close: bool = True
    brokerage_aware_hold: bool = True
    roll_itm_near_expiry: bool = False
    roll_delta_based: bool = False
    market_aware_roll_suggestion: bool = False
    target_delta_min: float = 0.25
    target_delta_max: float = 0.35
    manage_short_call_only: bool = False
    roll_before_assignment: bool = False


class StrategyAlerts(BaseModel):
    model_config = ConfigDict(extra='ignore')
    assignment_risk_alert: bool = True
    assignment_imminent_alert: bool = True


class StrategyRuleConfigUpdate(BaseModel):
    model_config = ConfigDict(extra='ignore')
    controls: StrategyControls = StrategyControls()
    alerts: StrategyAlerts = StrategyAlerts()


class RulesPreviewRequest(BaseModel):
    trade_id: Optional[str] = None


class ManageTradeRequest(BaseModel):
    mode: str = "recommend_only"
    goals: Dict[str, Any] = {}


class ApplyRecommendationRequest(BaseModel):
    recommendation: Dict[str, Any]
    current_price: float


# ==================== HELPER FUNCTIONS ====================

def _get_server_functions():
    """Lazy import to avoid circular dependencies"""
    from server import fetch_stock_quote
    return {'fetch_stock_quote': fetch_stock_quote}


def evaluate_condition(trade: dict, condition: dict) -> bool:
    """
    Evaluate a single condition against a trade
    condition format: {"field": "premium_capture_pct", "operator": ">=", "value": 50}
    """
    field = condition.get("field")
    operator = condition.get("operator")
    target_value = condition.get("value")
    
    if not field or not operator or target_value is None:
        return False
    
    # Get the current value from trade
    current_value = trade.get(field)
    
    # Handle nested fields like "greeks.delta"
    if "." in field and current_value is None:
        parts = field.split(".")
        current_value = trade
        for part in parts:
            if isinstance(current_value, dict):
                current_value = current_value.get(part)
            else:
                current_value = None
                break
    
    if current_value is None:
        return False
    
    try:
        current_value = float(current_value)
        target_value = float(target_value)
    except (ValueError, TypeError):
        return False
    
    if operator == ">=":
        return current_value >= target_value
    elif operator == "<=":
        return current_value <= target_value
    elif operator == ">":
        return current_value > target_value
    elif operator == "<":
        return current_value < target_value
    elif operator == "==":
        return current_value == target_value
    elif operator == "!=":
        return current_value != target_value
    elif operator == "between":
        if isinstance(target_value, list) and len(target_value) == 2:
            return target_value[0] <= current_value <= target_value[1]
        return False
    
    return False


def evaluate_rule(trade: dict, rule: dict) -> bool:
    """
    Evaluate if a rule should trigger for a trade
    All conditions must be met (AND logic)
    """
    conditions = rule.get("conditions", [])
    
    if not conditions:
        return False
    
    for condition in conditions:
        if not evaluate_condition(trade, condition):
            return False
    
    return True


async def execute_rule_action(trade: dict, rule: dict, db) -> dict:
    """
    Execute the action defined by a rule
    Returns result of the action
    """
    action = rule.get("action")
    action_params = rule.get("action_params", {})
    now = datetime.now(timezone.utc)
    
    result = {
        "rule_id": rule.get("id"),
        "rule_name": rule.get("name"),
        "action": action,
        "trade_id": trade.get("id"),
        "success": False,
        "message": "",
        "timestamp": now.isoformat()
    }
    
    if action == "close":
        # Close the trade at current price
        close_reason = action_params.get("reason", "rule_triggered")
        
        # Calculate final P&L
        current_price = trade.get("current_underlying_price", trade.get("entry_underlying_price"))
        entry_premium = trade.get("short_call_premium", 0)
        current_option_value = trade.get("current_option_value", 0)
        
        if trade["strategy_type"] in ("covered_call", "wheel", "defensive"):
            stock_pnl = (current_price - trade["entry_underlying_price"]) * 100 * trade["contracts"]
            option_pnl = (entry_premium - current_option_value) * 100 * trade["contracts"]
            final_pnl = stock_pnl + option_pnl
        else:  # PMCC
            final_pnl = trade.get("unrealized_pnl", 0)

        update_doc = {
            "status": "closed",
            "close_date": now.strftime("%Y-%m-%d"),
            "close_price": current_price,
            "close_reason": close_reason,
            "final_pnl": round(final_pnl, 2),
            "realized_pnl": round(final_pnl, 2),
            "roi_percent": round((final_pnl / trade["capital_deployed"]) * 100, 2) if trade.get("capital_deployed", 0) > 0 else 0,
            "closed_by_rule": rule.get("id")
        }
        
        await db.simulator_trades.update_one(
            {"id": trade["id"]},
            {"$set": update_doc}
        )
        
        # Log the action
        await db.simulator_trades.update_one(
            {"id": trade["id"]},
            {"$push": {"action_log": {
                "action": "closed_by_rule",
                "rule_id": rule.get("id"),
                "rule_name": rule.get("name"),
                "timestamp": now.isoformat(),
                "details": f"Closed by rule: {rule.get('name')}. Final P&L: ${final_pnl:.2f}"
            }}}
        )
        
        result["success"] = True
        result["message"] = f"Trade closed. Final P&L: ${final_pnl:.2f}"
        result["final_pnl"] = final_pnl
        
    elif action == "alert":
        alert_message = action_params.get("message", f"Rule '{rule.get('name')}' triggered")

        # Deduplicate: skip if same alert already fired for this trade within last 24 hours
        from datetime import timedelta
        cutoff = (now - timedelta(hours=24)).isoformat()
        recent = await db.simulator_action_logs.find_one({
            "trade_id": trade.get("id"),
            "rule_id": rule.get("id"),
            "action": "alert",
            "timestamp": {"$gte": cutoff}
        })
        if recent:
            result["success"] = False
            result["message"] = "Alert suppressed — already fired within last 24 hours"
            return result

        await db.simulator_trades.update_one(
            {"id": trade["id"]},
            {"$push": {"action_log": {
                "action": "alert",
                "rule_id": rule.get("id"),
                "rule_name": rule.get("name"),
                "timestamp": now.isoformat(),
                "details": alert_message
            }}}
        )

        result["success"] = True
        result["message"] = alert_message
        
    elif action == "roll_out":
        # Placeholder for roll functionality
        result["message"] = "Roll out action not yet implemented"
        
    elif action == "roll_up":
        # Placeholder for roll functionality
        result["message"] = "Roll up action not yet implemented"
        
    else:
        result["message"] = f"Unknown action: {action}"
    
    # Log to action_logs collection
    log_entry = {
        "id": str(uuid.uuid4()),
        "user_id": trade.get("user_id"),
        "trade_id": trade.get("id"),
        "rule_id": rule.get("id"),
        "rule_name": rule.get("name"),
        "action": action,
        "success": result["success"],
        "message": result["message"],
        "timestamp": now.isoformat(),
        "trade_snapshot": {
            "symbol": trade.get("symbol"),
            "strategy_type": trade.get("strategy_type"),
            "premium_capture_pct": trade.get("premium_capture_pct"),
            "unrealized_pnl": trade.get("unrealized_pnl"),
            "dte_remaining": trade.get("dte_remaining"),
            "current_delta": trade.get("current_delta")
        }
    }
    # Ensure top-level fields for Logs tab rendering
    log_entry["symbol"] = log_entry.get("symbol") or trade.get("symbol", "UNKNOWN")
    log_entry["strategy_type"] = log_entry.get("strategy_type") or trade.get("strategy_type", "unknown")
    log_entry["read"] = False  # Unread until user dismisses login popup
    await db.simulator_action_logs.insert_one(log_entry)
    
    return result


async def evaluate_and_execute_rules(trade: dict, rules: list, db) -> list:
    """
    Evaluate all rules against a trade and execute matching ones
    Rules are sorted by priority (higher = more important)
    """
    results = []
    
    # Sort rules by priority (descending)
    sorted_rules = sorted(rules, key=lambda r: r.get("priority", 0), reverse=True)
    
    trade_strategy = (trade.get("strategy_type") or "covered_call").lower()
    # Normalize aliases
    if trade_strategy == "cc":
        trade_strategy = "covered_call"

    for rule in sorted_rules:
        if not rule.get("is_enabled", True):
            continue

        # If the rule is scoped to a specific strategy type, skip trades that don't match
        rule_strategy = rule.get("strategy_type")
        if rule_strategy:
            rule_strategy = rule_strategy.lower()
            if rule_strategy == "cc":
                rule_strategy = "covered_call"
            if rule_strategy != trade_strategy:
                continue

        if evaluate_rule(trade, rule):
            result = await execute_rule_action(trade, rule, db)
            results.append(result)
            
            # If action was "close" and successful, stop processing more rules
            if rule.get("action") == "close" and result.get("success"):
                break
    
    return results


# ==================== TRADE ENDPOINTS ====================

@simulator_router.post("/trade")
async def add_simulator_trade(trade: SimulatorTradeEntry, user: dict = Depends(get_current_user)):
    """Add a new trade to the simulator from screener results"""
    
    trade_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    entry_date = now.strftime("%Y-%m-%d")
    
    # Calculate key metrics based on strategy type
    if trade.strategy_type in ("covered_call", "wheel", "defensive"):
        # Covered Call / Wheel / Defensive: Long 100 shares + Short call
        capital_per_contract = trade.underlying_price * 100  # Cost of 100 shares
        total_capital = capital_per_contract * trade.contracts
        premium_received = trade.short_call_premium * trade.contracts * 100
        max_profit = ((trade.short_call_strike - trade.underlying_price) * 100 + trade.short_call_premium * 100) * trade.contracts
        max_loss = (trade.underlying_price * 100 - trade.short_call_premium * 100) * trade.contracts  # Stock goes to 0
        breakeven = trade.underlying_price - trade.short_call_premium
        
    elif trade.strategy_type == "pmcc":
        # PMCC: Long LEAPS + Short call
        if not trade.leaps_strike or not trade.leaps_expiry or not trade.leaps_premium:
            raise HTTPException(status_code=400, detail="PMCC requires LEAPS details")
        
        capital_per_contract = trade.leaps_premium * 100  # Cost of LEAPS
        total_capital = capital_per_contract * trade.contracts
        premium_received = trade.short_call_premium * trade.contracts * 100
        
        # Max profit: difference between strikes + net credit/debit
        strike_diff = trade.short_call_strike - trade.leaps_strike
        net_debit = trade.leaps_premium - trade.short_call_premium
        max_profit = (strike_diff * 100 - net_debit * 100) * trade.contracts if strike_diff > 0 else (trade.short_call_premium * 100 * trade.contracts)
        max_loss = total_capital  # LEAPS expires worthless
        breakeven = trade.leaps_strike + net_debit
    else:
        if trade.strategy_type not in {"covered_call", "pmcc", "wheel", "defensive"}:
            raise HTTPException(status_code=400, detail="Invalid strategy type. Must be 'covered_call', 'pmcc', 'wheel', or 'defensive'")
        # wheel and defensive: same capital structure as covered_call
        capital_per_contract = trade.underlying_price * 100
        total_capital = capital_per_contract * trade.contracts
        premium_received = trade.short_call_premium * trade.contracts * 100
        max_profit = ((trade.short_call_strike - trade.underlying_price) * 100 + trade.short_call_premium * 100) * trade.contracts
        max_loss = (trade.underlying_price * 100 - trade.short_call_premium * 100) * trade.contracts
        breakeven = trade.underlying_price - trade.short_call_premium
    
    # Calculate DTE
    try:
        expiry_dt = datetime.strptime(trade.short_call_expiry, "%Y-%m-%d")
        dte = max((expiry_dt - datetime.now()).days, 0)
    except:
        dte = 30  # Default
    
    
    # -------------------------------------------------------------------
    # Simulator IV normalization + fill (minimal, simulator-only)
    # - Normalizes IV units (e.g., 30 -> 0.30) to prevent 3000% bugs
    # - If IV missing, attempts a one-time fill from options chain by expiry+nearest strike
    # -------------------------------------------------------------------
    normalized_short_iv = None
    short_iv_source = "PAYLOAD"

    try:
        if getattr(trade, "short_call_iv", None) is not None:
            normalized_short_iv = normalize_iv_fields(trade.short_call_iv)["iv"]
    except Exception:
        normalized_short_iv = None

    if not normalized_short_iv or normalized_short_iv <= 0:
        try:
            chain = await fetch_options_chain(
                symbol=trade.symbol.upper(),
                api_key=None,
                option_type="call",
                min_dte=max(1, dte - 7),
                max_dte=dte + 7,
                current_price=trade.underlying_price
            )
            candidates = [o for o in chain if o.get("expiry") == trade.short_call_expiry]
            if candidates:
                closest = min(
                    candidates,
                    key=lambda o: abs(float(o.get("strike") or 0) - float(trade.short_call_strike))
                )
                iv_raw = closest.get("implied_volatility") or 0
                if iv_raw:
                    normalized_short_iv = normalize_iv_fields(iv_raw)["iv"]
                    if normalized_short_iv and normalized_short_iv > 0:
                        short_iv_source = f"CHAIN:{closest.get('source', 'yahoo')}"
        except Exception:
            pass

    if not normalized_short_iv or normalized_short_iv <= 0:
        normalized_short_iv = 0.30
        short_iv_source = "DEFAULT_0.30"

    # Create simulator trade document
    trade_doc = {
        "id": trade_id,
        "user_id": user["id"],
        "symbol": trade.symbol.upper(),
        "strategy_type": trade.strategy_type,
        "status": "open",  # Lifecycle: open, rolled (PMCC), expired, assigned, closed
        
        # Entry snapshot (immutable)
        "entry_date": entry_date,
        "entry_underlying_price": trade.underlying_price,
        # Canonical entry marks used for P/L calc
        "entry_spot": trade.underlying_price,
        "entry_short_bid": trade.short_call_premium,
        "entry_long_ask": trade.leaps_premium if trade.strategy_type == "pmcc" else None,

        # Short call details
        "short_call_strike": trade.short_call_strike,
        "short_call_expiry": trade.short_call_expiry,
        "short_call_premium": trade.short_call_premium,
        "short_call_delta": trade.short_call_delta,
        "short_call_iv": normalized_short_iv,
        "short_call_iv_source": short_iv_source,
        
        # PMCC LEAPS details (if applicable)
        "leaps_strike": trade.leaps_strike,
        "leaps_expiry": trade.leaps_expiry,
        "leaps_premium": trade.leaps_premium,
        "leaps_delta": trade.leaps_delta,
        
        # Position size
        "contracts": trade.contracts,
        
        # Calculated at entry
        "capital_deployed": total_capital,
        "premium_received": premium_received,
        "max_profit": max_profit,
        "max_loss": max_loss,
        "breakeven": breakeven,
        "initial_dte": dte,
        
        # Current values (updated daily)
        "current_underlying_price": trade.underlying_price,
        "current_option_value": trade.short_call_premium,
        "unrealized_pnl": 0,
        "days_held": 0,
        "dte_remaining": dte,
        "premium_capture_pct": 0,
        
        # Greeks (updated daily)
        "current_delta": trade.short_call_delta or 0.30,
        "current_gamma": 0,
        "current_theta": 0,
        "current_vega": 0,
        
        # Scan parameters for feedback loop
        "scan_parameters": trade.scan_parameters,
        "notes": trade.notes,
        
        # Action log for trade management
        "action_log": [{
            "action": "opened",
            "timestamp": now.isoformat(),
            "details": f"Trade opened: {trade.contracts} contract(s) at ${trade.underlying_price:.2f}"
        }],
        
        # Timestamps
        "created_at": now.isoformat(),
        "updated_at": now.isoformat()
    }
    
    await db.simulator_trades.insert_one(trade_doc)
    
    # Remove MongoDB _id before returning
    trade_doc.pop("_id", None)
    
    return {
        "message": "Trade added to simulator",
        "trade": trade_doc
    }


@simulator_router.get("/trades")
async def get_simulator_trades(
    status: Optional[str] = Query(None, description="Filter by status: open, rolled, expired, assigned, closed"),
    symbol: Optional[str] = Query(None),
    strategy_type: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    skip: int = Query(0, ge=0),
    debug_enrichment: bool = Query(False, description="Include enrichment debug info"),
    user: dict = Depends(get_current_user)
):
    """Get all simulator trades for the user with optional filters"""
    
    query = {"user_id": user["id"]}
    if status:
        query["status"] = status
    if symbol:
        query["symbol"] = symbol.upper()
    if strategy_type:
        query["strategy_type"] = strategy_type
    
    trades = await db.simulator_trades.find(
        query,
        {"_id": 0}
    ).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    
    total = await db.simulator_trades.count_documents(query)
    
    # ========== UI FIELD ALIASES (normalize simulator doc shape for frontend) ==========
    for trade in trades:
        trade["entry"] = trade.get("entry_underlying_price")
        trade["current"] = trade.get("current_underlying_price")
        trade["expiry"] = trade.get("short_call_expiry")
        trade["strike"] = trade.get("short_call_strike")
        trade["premium"] = trade.get("short_call_premium")
        trade["dte"] = trade.get("dte_remaining")
        trade["delta"] = trade.get("current_delta") or trade.get("short_call_delta")
        trade["iv"] = trade.get("short_call_iv")
        status = trade.get("status", "open")
        if status in ["open", "rolled"]:
            trade["p_l"] = trade.get("unrealized_pnl", 0)
        else:
            trade["p_l"] = trade.get("realized_pnl") or trade.get("final_pnl", 0)

    # ========== ENRICHMENT: Only enrich OPEN trades, batch by unique symbol ==========
    # Closed/assigned/expired trades don't need live enrichment (no current option data)
    open_trades = [t for t in trades if t.get("status") in ("open", "rolled", "active")]
    if open_trades:
        seen_symbols = set()
        for trade in open_trades:
            sym = trade.get("symbol", "")
            if sym and sym not in seen_symbols:
                seen_symbols.add(sym)
                enrich_row(
                    sym, trade,
                    stock_price=trade.get("current_underlying_price") or trade.get("entry_underlying_price"),
                    expiry=trade.get("short_call_expiry"),
                    iv=trade.get("short_call_iv"),
                    skip_iv_rank=True,   # IV rank not critical for simulator list view
                    skip_analyst=True    # Simulator table doesn't show analyst data — skip live fetch
                )
                strip_enrichment_debug(trade, include_debug=debug_enrichment)

    return {
        "trades": trades,
        "total": total,
        "limit": limit,
        "skip": skip
    }


@simulator_router.get("/trades/health")
async def get_trades_health(user: dict = Depends(get_current_user)):
    """
    Trade Health endpoint — returns computed P/L, capture%, yield%, ROI, DTE, delta
    for all active (open/rolled) trades. Powers the Analyzer Trade Health table.
    """
    trades = await db.simulator_trades.find(
        {"user_id": user["id"], "status": {"$in": ["open", "rolled"]}},
        {"_id": 0}
    ).to_list(1000)

    rows = []
    for t in trades:
        entry_spot      = t.get("entry_spot") or t.get("entry_underlying_price") or 0
        entry_short_bid = t.get("entry_short_bid") or t.get("short_call_premium") or 0
        entry_long_ask  = t.get("entry_long_ask") or t.get("leaps_premium") or 0
        strategy        = t.get("strategy_type", "covered_call")
        contracts       = t.get("contracts", 1)

        # yield_pct — entry premium / entry spot
        yield_pct = round(entry_short_bid / entry_spot * 100, 2) if entry_spot > 0 else 0

        # Prefer real-mark values stored by update-prices; fall back to BS-derived
        capture_pct = t.get("capture_pct") or t.get("premium_capture_pct") or 0
        total_pl    = t.get("total_pl")          # None if marks were missing
        roi_pct     = t.get("roi_pct")           # None if marks were missing
        data_quality = t.get("data_quality")

        # If total_pl never computed (trade added before new code), fall back to unrealized_pnl
        if total_pl is None and data_quality != "missing_option_mark":
            total_pl = t.get("unrealized_pnl")
            if total_pl is not None:
                if strategy in ("covered_call", "wheel", "defensive"):
                    capital = entry_spot * 100 * contracts
                    roi_pct = round(total_pl / capital * 100, 2) if capital > 0 else None
                else:
                    net_debit = (entry_long_ask - entry_short_bid) * 100 * contracts
                    roi_pct = round(total_pl / net_debit * 100, 2) if net_debit > 0 else None
                data_quality = "bs_estimate"

        rows.append({
            "trade_id":     t.get("id"),
            "symbol":       t.get("symbol"),
            "strategy":     strategy,
            "status":       t.get("status"),
            "contracts":    contracts,
            "dte":          t.get("dte_remaining"),
            "delta":        t.get("current_delta"),
            "iv_pct":       round((t.get("short_call_iv") or 0) * 100, 1),
            "entry_spot":   entry_spot,
            "entry_short_bid": entry_short_bid,
            "short_mark":   t.get("short_mark"),
            "long_mark":    t.get("long_mark"),
            "yield_pct":    yield_pct,
            "capture_pct":  round(capture_pct, 1),
            "total_pl":     total_pl,
            "roi_pct":      roi_pct,
            "data_quality": data_quality,
            "last_updated": t.get("last_updated"),
        })

    # Sort: by total_pl ascending (worst performers first)
    rows.sort(key=lambda r: (r["total_pl"] is None, r["total_pl"] or 0))

    return {"trades": rows, "total": len(rows)}


@simulator_router.get("/trades/{trade_id}")
async def get_simulator_trade_detail(trade_id: str, user: dict = Depends(get_current_user)):
    """Get detailed view of a single simulator trade"""
    trade = await db.simulator_trades.find_one({"id": trade_id, "user_id": user["id"]}, {"_id": 0})
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    return trade


@simulator_router.delete("/trades/{trade_id}")
async def delete_simulator_trade(trade_id: str, user: dict = Depends(get_current_user)):
    """Delete a simulator trade"""
    result = await db.simulator_trades.delete_one({"id": trade_id, "user_id": user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Trade not found")
    return {"message": "Trade deleted"}


@simulator_router.post("/trades/{trade_id}/close")
async def close_simulator_trade(
    trade_id: str,
    close_reason: str = Query("manual", description="Reason for closing: manual, profit_target, stop_loss"),
    close_price: Optional[float] = Query(None),
    user: dict = Depends(get_current_user)
):
    """Manually close a simulator trade"""
    
    trade = await db.simulator_trades.find_one({"id": trade_id, "user_id": user["id"]})
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    
    if trade.get("status") not in ["open", "rolled"]:
        raise HTTPException(status_code=400, detail="Trade is not open or rolled")
    
    now = datetime.now(timezone.utc)
    
    # Use provided close price or current price
    final_price = close_price or trade.get("current_underlying_price", trade.get("entry_underlying_price"))
    
    # Calculate final P&L
    entry_premium = trade.get("short_call_premium", 0)
    current_option_value = trade.get("current_option_value", 0)
    
    if trade["strategy_type"] in ("covered_call", "wheel", "defensive"):
        stock_pnl = (final_price - trade["entry_underlying_price"]) * 100 * trade["contracts"]
        option_pnl = (entry_premium - current_option_value) * 100 * trade["contracts"]
        final_pnl = stock_pnl + option_pnl
    else:  # PMCC
        final_pnl = trade.get("unrealized_pnl", 0)
    
    update_doc = {
        "status": "closed",
        "close_date": now.strftime("%Y-%m-%d"),
        "close_price": final_price,
        "close_reason": close_reason,
        "final_pnl": round(final_pnl, 2),
        "realized_pnl": round(final_pnl, 2),
        "roi_percent": round((final_pnl / trade["capital_deployed"]) * 100, 2) if trade.get("capital_deployed", 0) > 0 else 0,
        "updated_at": now.isoformat()
    }
    
    await db.simulator_trades.update_one(
        {"id": trade_id},
        {
            "$set": update_doc,
            "$push": {"action_log": {
                "action": "closed",
                "timestamp": now.isoformat(),
                "details": f"Trade closed manually. Reason: {close_reason}. Final P&L: ${final_pnl:.2f}"
            }}
        }
    )
    
    return {
        "message": "Trade closed",
        "final_pnl": round(final_pnl, 2),
        "roi_percent": round((final_pnl / trade["capital_deployed"]) * 100, 2) if trade.get("capital_deployed", 0) > 0 else 0
    }


class PMCCRollRequest(BaseModel):
    """Request model for rolling a PMCC short call"""
    new_strike: float
    new_expiry: str  # YYYY-MM-DD
    new_premium: float
    new_delta: Optional[float] = None
    new_iv: Optional[float] = None


@simulator_router.post("/trades/{trade_id}/roll")
async def roll_pmcc_short_call(
    trade_id: str,
    roll_request: PMCCRollRequest,
    user: dict = Depends(get_current_user)
):
    """
    Roll a PMCC short call to a new expiration/strike.
    
    PMCC ROLL RULES (per spec):
    - Short call is closed (premium captured)
    - New short call is opened with new strike/expiry
    - Trade status changes to "rolled"
    - This prevents assignment by moving the short call up/out
    
    CRITICAL: In PMCC, you do NOT want the short call to be assigned.
    Roll before that happens!
    """
    
    trade = await db.simulator_trades.find_one({"id": trade_id, "user_id": user["id"]})
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    
    if trade.get("strategy_type") != "pmcc":
        raise HTTPException(status_code=400, detail="Roll is only available for PMCC trades")
    
    if trade.get("status") not in ["open", "rolled"]:
        raise HTTPException(status_code=400, detail="Trade must be open or previously rolled to roll again")
    
    now = datetime.now(timezone.utc)
    
    # Calculate premium captured from old short call
    old_premium = trade.get("short_call_premium", 0)
    old_option_value = trade.get("current_option_value", 0)
    premium_captured = (old_premium - old_option_value) * 100 * trade["contracts"]
    
    # Get roll count
    roll_count = trade.get("roll_count", 0) + 1
    
    # Calculate new DTE
    try:
        new_expiry_dt = datetime.strptime(roll_request.new_expiry, "%Y-%m-%d")
        new_dte = max((new_expiry_dt - datetime.now()).days, 0)
    except:
        new_dte = 30
    
    # Update trade document
    update_doc = {
        "status": "rolled",  # Mark as rolled
        "short_call_strike": roll_request.new_strike,
        "short_call_expiry": roll_request.new_expiry,
        "short_call_premium": roll_request.new_premium,
        "short_call_delta": roll_request.new_delta or 0.30,
        "short_call_iv": roll_request.new_iv or trade.get("short_call_iv", 0.30),
        "dte_remaining": new_dte,
        "roll_count": roll_count,
        "last_roll_date": now.strftime("%Y-%m-%d"),
        "premium_received": trade.get("premium_received", 0) + (roll_request.new_premium * 100 * trade["contracts"]),
        "total_premium_captured": trade.get("total_premium_captured", 0) + premium_captured,
        "updated_at": now.isoformat()
    }
    
    # Update breakeven
    leaps_premium = trade.get("leaps_premium", 0)
    total_short_premium = (trade.get("total_premium_captured", 0) + premium_captured + roll_request.new_premium * 100 * trade["contracts"]) / (100 * trade["contracts"])
    update_doc["breakeven"] = trade.get("leaps_strike", 0) + (leaps_premium - total_short_premium)
    
    await db.simulator_trades.update_one(
        {"id": trade_id},
        {
            "$set": update_doc,
            "$push": {"action_log": {
                "action": "rolled",
                "timestamp": now.isoformat(),
                "details": f"Rolled short call #{roll_count}: Old ${trade['short_call_strike']} → New ${roll_request.new_strike} exp {roll_request.new_expiry}. Premium captured: ${premium_captured:.2f}. New premium: ${roll_request.new_premium * 100:.2f}"
            }}
        }
    )
    
    return {
        "message": f"PMCC short call rolled successfully (roll #{roll_count})",
        "premium_captured": round(premium_captured, 2),
        "new_strike": roll_request.new_strike,
        "new_expiry": roll_request.new_expiry,
        "new_premium": roll_request.new_premium,
        "total_premium_received": round(update_doc["premium_received"], 2),
        "roll_count": roll_count
    }


@simulator_router.get("/trades/{trade_id}/roll-suggestions")
async def get_roll_suggestions(
    trade_id: str,
    user: dict = Depends(get_current_user)
):
    """
    Get suggestions for rolling a PMCC short call.
    
    PMCC DOWNSIDE PROTECTION RULE:
    - Short call strike must be above LEAPS breakeven
    - Premium should offset LEAPS theta decay
    - Never increase downside risk
    """
    
    trade = await db.simulator_trades.find_one({"id": trade_id, "user_id": user["id"]}, {"_id": 0})
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    
    if trade.get("strategy_type") != "pmcc":
        raise HTTPException(status_code=400, detail="Roll suggestions only available for PMCC trades")
    
    current_price = trade.get("current_underlying_price", trade.get("entry_underlying_price"))
    leaps_strike = trade.get("leaps_strike", 0)
    current_short_strike = trade.get("short_call_strike", 0)
    current_dte = trade.get("dte_remaining", 0)
    
    # Calculate risk metrics
    short_to_stock_ratio = (current_short_strike / current_price * 100) if current_price > 0 else 0
    
    # Determine if roll is urgent
    roll_urgency = "low"
    roll_reason = []
    
    if current_dte <= 7:
        roll_urgency = "high"
        roll_reason.append(f"Only {current_dte} DTE remaining - roll soon to avoid assignment risk")
    elif current_dte <= 14:
        roll_urgency = "medium"
        roll_reason.append(f"{current_dte} DTE - consider rolling to capture remaining theta")
    
    if current_price >= current_short_strike * 0.95:
        roll_urgency = "high"
        roll_reason.append(f"Stock price ${current_price:.2f} is within 5% of strike ${current_short_strike} - HIGH ASSIGNMENT RISK")
    elif current_price >= current_short_strike * 0.90:
        roll_urgency = "medium"
        roll_reason.append("Stock price approaching strike - monitor closely")
    
    # Suggest new strikes (roll up and out)
    suggestions = []
    
    # Roll out same strike (extend DTE)
    suggestions.append({
        "type": "roll_out",
        "description": "Roll out (extend expiration, same strike)",
        "suggested_strike": current_short_strike,
        "suggested_dte": 30,
        "rationale": "Capture more theta decay without changing strike"
    })
    
    # Roll up and out (higher strike, extend DTE)
    roll_up_strike = round(current_price * 1.05, 2)  # 5% above current price
    suggestions.append({
        "type": "roll_up_and_out",
        "description": "Roll up and out (higher strike, extend expiration)",
        "suggested_strike": roll_up_strike,
        "suggested_dte": 45,
        "rationale": "Move strike above current price to reduce assignment risk"
    })
    
    # Aggressive roll (higher strike, same DTE)
    if current_dte > 14:
        suggestions.append({
            "type": "roll_up",
            "description": "Roll up (higher strike, similar expiration)",
            "suggested_strike": round(current_price * 1.03, 2),
            "suggested_dte": current_dte,
            "rationale": "Quick adjustment to reduce delta exposure"
        })
    
    return {
        "trade_id": trade_id,
        "symbol": trade.get("symbol"),
        "current_price": current_price,
        "current_short_strike": current_short_strike,
        "current_dte": current_dte,
        "leaps_strike": leaps_strike,
        "roll_urgency": roll_urgency,
        "roll_reasons": roll_reason,
        "suggestions": suggestions,
        "warning": "In PMCC, short call assignment should be AVOIDED. Roll before the short call goes ITM!"
    }

@simulator_router.post("/update-prices")
async def update_simulator_prices(user: dict = Depends(get_current_user)):
    """
    Manually trigger LIVE price update for user's active trades.
    
    DATA RULE #2: Simulator uses LIVE intraday prices (regularMarketPrice)
    for accurate P&L tracking during market hours.
    """
    active_trades = await db.simulator_trades.find(
        {"user_id": user["id"], "status": {"$in": ["open", "rolled"]}},
        {"_id": 0}
    ).to_list(1000)
    
    if not active_trades:
        return {"message": "No active trades to update", "updated": 0}
    
    # Get unique symbols
    symbols = list(set(t["symbol"] for t in active_trades))
    
    # Fetch LIVE intraday prices (Rule #2)
    price_cache = {}
    for symbol in symbols:
        try:
            quote = await fetch_live_stock_quote(symbol)
            if quote and quote.get("price"):
                price_cache[symbol] = quote["price"]
        except Exception as e:
            logging.warning(f"Could not fetch live price for {symbol}: {e}")

    # Fetch option chain marks per symbol — one broad call covers all expiries
    # option_marks[symbol][(expiry, strike)] = {"ask": float, "bid": float}
    option_marks: dict = {}
    for symbol in symbols:
        option_marks[symbol] = {}
        try:
            chain = await fetch_options_chain(
                symbol=symbol,
                api_key=None,
                option_type="call",
                min_dte=0,
                max_dte=730,
                current_price=price_cache.get(symbol, 0)
            )
            for opt in chain:
                key = (opt.get("expiry"), float(opt.get("strike", 0)))
                option_marks[symbol][key] = {
                    "ask": opt.get("ask") or 0,
                    "bid": opt.get("bid") or 0,
                }
        except Exception as e:
            logging.warning(f"Option chain fetch failed for {symbol}: {e}")

    now = datetime.now(timezone.utc)
    risk_free_rate = 0.05

    updated_count = 0

    for trade in active_trades:
        symbol = trade["symbol"]
        if symbol not in price_cache:
            continue

        spot_mark = price_cache[symbol]
        contracts = trade.get("contracts", 1)
        strategy = trade.get("strategy_type", "covered_call")

        # DTE / days held
        try:
            expiry_dt = datetime.strptime(trade["short_call_expiry"], "%Y-%m-%d")
            dte_remaining = max((expiry_dt - datetime.now()).days, 0)
            time_to_expiry = max(dte_remaining / 365, 0.001)
        except Exception:
            dte_remaining = max(trade.get("dte_remaining", 0), 0)
            time_to_expiry = max(dte_remaining / 365, 0.001)

        try:
            entry_dt = datetime.strptime(trade["entry_date"], "%Y-%m-%d")
            days_held = (datetime.now() - entry_dt).days
        except Exception:
            days_held = trade.get("days_held", 0)

        # Greeks (Black-Scholes) — kept for rule evaluation and display
        iv_raw = trade.get("short_call_iv")
        try:
            iv = normalize_iv_fields(iv_raw)["iv"] if iv_raw else 0.30
        except Exception:
            iv = 0.30
        if not iv or iv <= 0:
            iv = 0.30
        greeks = calculate_greeks(
            S=spot_mark,
            K=trade["short_call_strike"],
            T=time_to_expiry,
            r=risk_free_rate,
            sigma=iv
        )
        current_option_value = greeks["option_value"]

        # Real option marks from chain
        short_key = (trade.get("short_call_expiry"), float(trade.get("short_call_strike", 0)))
        short_opt = option_marks.get(symbol, {}).get(short_key)
        short_mark = short_opt["ask"] if short_opt and short_opt.get("ask", 0) > 0 else None

        long_mark = None
        if strategy == "pmcc":
            long_key = (trade.get("leaps_expiry"), float(trade.get("leaps_strike", 0)))
            long_opt = option_marks.get(symbol, {}).get(long_key)
            long_mark = long_opt["bid"] if long_opt and long_opt.get("bid", 0) > 0 else None

        # Entry anchors (fall back to legacy field names for old trades)
        entry_spot      = trade.get("entry_spot") or trade.get("entry_underlying_price") or spot_mark
        entry_short_bid = trade.get("entry_short_bid") or trade.get("short_call_premium") or 0
        entry_long_ask  = trade.get("entry_long_ask") or trade.get("leaps_premium") or 0

        # yield_pct — always computable from entry data
        yield_pct = round(entry_short_bid / entry_spot * 100, 2) if entry_spot > 0 else 0

        # P/L, capture_pct, ROI using real marks when available
        marks_ok = short_mark is not None and (strategy == "covered_call" or long_mark is not None)
        if marks_ok:
            raw_capture = ((entry_short_bid - short_mark) / entry_short_bid * 100) if entry_short_bid > 0 else 0
            capture_pct = round(max(0.0, min(100.0, raw_capture)), 1)
            if strategy == "covered_call":
                total_pl = round(
                    ((spot_mark - entry_spot) * 100 + (entry_short_bid - short_mark) * 100) * contracts, 2
                )
                capital = entry_spot * 100 * contracts
                roi_pct = round(total_pl / capital * 100, 2) if capital > 0 else None
            else:
                total_pl = round(
                    ((long_mark - entry_long_ask) * 100 + (entry_short_bid - short_mark) * 100) * contracts, 2
                )
                net_debit = (entry_long_ask - entry_short_bid) * 100 * contracts
                roi_pct = round(total_pl / net_debit * 100, 2) if net_debit > 0 else None
            data_quality = None
        else:
            raw_bs_capture = ((entry_short_bid - current_option_value) / entry_short_bid * 100) if entry_short_bid > 0 else 0
            capture_pct = round(max(0.0, min(100.0, raw_bs_capture)), 1)
            total_pl = None
            roi_pct = None
            data_quality = "missing_option_mark"

        # Legacy unrealized_pnl (BS-based, preserved for backward compat)
        if strategy == "covered_call":
            stock_pnl = (spot_mark - entry_spot) * 100 * contracts
            option_pnl = (entry_short_bid - current_option_value) * 100 * contracts
            unrealized_pnl = round(stock_pnl + option_pnl, 2)
        else:
            leaps_strike_val = trade.get("leaps_strike")
            if leaps_strike_val and leaps_strike_val > 0 and entry_long_ask > 0:
                leaps_dte = max(trade.get("leaps_dte_remaining") or 365, 0)
                leaps_greeks = calculate_greeks(
                    S=spot_mark, K=leaps_strike_val,
                    T=max(leaps_dte / 365, 0.001), r=risk_free_rate, sigma=iv
                )
                leaps_value_change = (leaps_greeks["option_value"] - entry_long_ask) * 100 * contracts
            else:
                leaps_value_change = 0
            short_call_pnl = (entry_short_bid - current_option_value) * 100 * contracts
            unrealized_pnl = round(leaps_value_change + short_call_pnl, 2)

        update_doc = {
            "current_underlying_price": spot_mark,
            "current_option_value": current_option_value,
            "unrealized_pnl": unrealized_pnl,
            # Canonical P/L fields per spec
            "total_pl": total_pl,
            "roi_pct": roi_pct,
            "yield_pct": yield_pct,
            "capture_pct": capture_pct,
            "short_mark": short_mark,
            "long_mark": long_mark,
            "data_quality": data_quality,
            # Legacy aliases
            "premium_capture_pct": capture_pct,
            "days_held": days_held,
            "dte_remaining": dte_remaining,
            "last_updated": now.isoformat(),
            "updated_at": now.isoformat(),
            "current_delta": greeks["delta"],
            "current_gamma": greeks["gamma"],
            "current_theta": greeks["theta"],
            "current_vega": greeks["vega"],
        }

        # Auto-expire or assign when DTE reaches 0
        if dte_remaining == 0 and trade.get("status") in ["open", "rolled"]:
            is_itm = spot_mark >= trade["short_call_strike"]
            final = total_pl if total_pl is not None else unrealized_pnl
            update_doc["status"] = "assigned" if is_itm else "expired"
            update_doc["final_pnl"] = round(final, 2)
            update_doc["realized_pnl"] = round(final, 2)
            update_doc["close_date"] = now.strftime("%Y-%m-%d")
            cap = trade.get("capital_deployed", 0)
            update_doc["roi_percent"] = round((final / cap) * 100, 2) if cap and cap > 0 else 0

        await db.simulator_trades.update_one({"id": trade["id"]}, {"$set": update_doc})
        updated_count += 1
    
    # After price update, evaluate rules
    user_rules = await db.simulator_rules.find(
        {"user_id": user["id"], "is_enabled": True},
        {"_id": 0}
    ).to_list(100)
    
    rules_triggered = 0
    if user_rules:
        # Re-fetch active trades with updated prices
        updated_trades = await db.simulator_trades.find(
            {"user_id": user["id"], "status": {"$in": ["open", "rolled"]}},
            {"_id": 0}
        ).to_list(1000)
        
        for trade in updated_trades:
            results = await evaluate_and_execute_rules(trade, user_rules, db)
            for result in results:
                if result.get("success"):
                    rules_triggered += 1
                    await db.simulator_rules.update_one(
                        {"id": result["rule_id"]},
                        {"$inc": {"times_triggered": 1}}
                    )
    
    return {
        "message": f"Updated {updated_count} trades",
        "updated": updated_count,
        "rules_triggered": rules_triggered,
        "prices": price_cache
    }


@simulator_router.get("/summary")
async def get_simulator_summary(user: dict = Depends(get_current_user)):
    """Get summary statistics for user's simulator trades"""
    
    # Get all trades
    all_trades = await db.simulator_trades.find(
        {"user_id": user["id"]},
        {"_id": 0}
    ).to_list(10000)
    
    if not all_trades:
        return {
            "total_trades": 0,
            "active_trades": 0,
            "closed_trades": 0,
            "total_realized_pnl": 0,
            "total_unrealized_pnl": 0,
            "win_rate": 0,
            "avg_roi": 0,
            "by_strategy": {},
            "by_status": {}
        }
    
    active_trades = [t for t in all_trades if t.get("status") in ["open", "rolled"]]
    closed_trades = [t for t in all_trades if t.get("status") in ["closed", "expired", "assigned"]]
    
    # Calculate P&L
    total_realized = sum((t.get("realized_pnl") or t.get("final_pnl") or 0) for t in closed_trades)
    total_unrealized = sum((t.get("unrealized_pnl") or 0) for t in active_trades)
    
    # Win rate — include open trades with positive unrealized P&L so it's not always 0
    # when all trades are still open
    closed_winners = [t for t in closed_trades if (t.get("realized_pnl", 0) or t.get("final_pnl", 0)) > 0]
    open_winners = [t for t in active_trades if (t.get("unrealized_pnl") or 0) > 0]
    all_evaluated = closed_trades + active_trades
    all_winners = closed_winners + open_winners
    win_rate = (len(all_winners) / len(all_evaluated) * 100) if all_evaluated else 0
    
    # Average ROI (closed trades only)
    rois = [t.get("roi_percent", 0) for t in closed_trades if t.get("roi_percent") is not None]
    avg_roi = sum(rois) / len(rois) if rois else 0

    # Avg return % across ALL trades (realized + unrealized vs capital deployed)
    total_capital_deployed = sum((t.get("capital_deployed", 0) or 0) for t in active_trades)
    total_pnl = total_realized + total_unrealized
    avg_return_pct = (total_pnl / total_capital_deployed * 100) if total_capital_deployed > 0 else 0

    # Assignment rate
    assigned_count = sum(1 for t in all_trades if t.get("status") == "assigned")
    completed_count = len(closed_trades)  # already includes expired + assigned + closed
    assignment_rate = round(assigned_count / completed_count * 100, 1) if completed_count > 0 else 0

    # By strategy
    by_strategy = {}
    for strategy in ["covered_call", "pmcc"]:
        strategy_trades = [t for t in all_trades if t.get("strategy_type") == strategy]
        strategy_closed = [t for t in strategy_trades if t.get("status") in ["closed", "expired", "assigned"]]
        strategy_active = [t for t in strategy_trades if t.get("status") in ["open", "rolled"]]

        by_strategy[strategy] = {
            "total": len(strategy_trades),
            "active": len(strategy_active),
            "closed": len(strategy_closed),
            "realized_pnl": sum((t.get("realized_pnl", 0) or t.get("final_pnl", 0) or 0) for t in strategy_closed),
            "unrealized_pnl": sum((t.get("unrealized_pnl", 0) or 0) for t in strategy_active)
        }

    # By status
    by_status = {}
    for status in ["open", "rolled", "closed", "expired", "assigned"]:
        status_trades = [t for t in all_trades if t.get("status") == status]
        by_status[status] = len(status_trades)

    return {
        "total_trades": len(all_trades),
        "active_trades": len(active_trades),
        "closed_trades": len(closed_trades),
        "total_realized_pnl": round(total_realized, 2),
        "total_unrealized_pnl": round(total_unrealized, 2),
        "total_pnl": round(total_pnl, 2),
        "total_capital_deployed": round(total_capital_deployed, 2),
        "win_rate": round(win_rate, 1),
        "avg_roi": round(avg_roi, 2),
        "avg_return_pct": round(avg_return_pct, 2),
        "avg_return_per_trade": round(avg_return_pct, 2),
        "assignment_rate": assignment_rate,
        "by_strategy": by_strategy,
        "by_status": by_status
    }


@simulator_router.delete("/clear")
async def clear_simulator_data(user: dict = Depends(get_current_user)):
    """Clear all simulator trades for user"""
    result = await db.simulator_trades.delete_many({"user_id": user["id"]})
    return {"message": f"Deleted {result.deleted_count} trades"}


@simulator_router.get("/scheduler-status")
async def get_scheduler_status(user: dict = Depends(get_current_user)):
    """Get the status of the automated price update scheduler"""
    from server import scheduler
    jobs = scheduler.get_jobs()
    
    job_info = []
    for job in jobs:
        job_info.append({
            "id": job.id,
            "name": job.name,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger)
        })
    
    return {
        "scheduler_running": scheduler.running,
        "jobs": job_info
    }


@simulator_router.post("/trigger-update")
async def trigger_manual_update(user: dict = Depends(get_current_user)):
    """Admin endpoint to manually trigger the scheduled update for all users"""
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    from server import scheduled_price_update
    
    try:
        await scheduled_price_update()
        return {"message": "Scheduled update triggered successfully"}
    except Exception as e:
        logging.error(f"Error triggering manual update: {e}")
        raise HTTPException(status_code=500, detail=str(e))


STRATEGY_MODE_DEFAULTS = {
    "income": {
        "summary": {"hold_to_expiry": True, "allow_assignment": True, "rolling_enabled": False, "manage_short_call_only": False},
        "controls": {"avoid_early_close": True, "brokerage_aware_hold": True, "roll_itm_near_expiry": False, "roll_delta_based": False, "market_aware_roll_suggestion": False, "target_delta_min": 0.25, "target_delta_max": 0.35, "manage_short_call_only": False, "roll_before_assignment": False},
    },
    "wheel": {
        "summary": {"hold_to_expiry": True, "allow_assignment": True, "rolling_enabled": False, "manage_short_call_only": False},
        "controls": {"avoid_early_close": True, "brokerage_aware_hold": True, "roll_itm_near_expiry": False, "roll_delta_based": False, "market_aware_roll_suggestion": False, "target_delta_min": 0.25, "target_delta_max": 0.35, "manage_short_call_only": False, "roll_before_assignment": False},
    },
    "defensive": {
        "summary": {"hold_to_expiry": False, "allow_assignment": False, "rolling_enabled": True, "manage_short_call_only": False},
        "controls": {"avoid_early_close": True, "brokerage_aware_hold": True, "roll_itm_near_expiry": True, "roll_delta_based": True, "market_aware_roll_suggestion": True, "target_delta_min": 0.25, "target_delta_max": 0.35, "manage_short_call_only": False, "roll_before_assignment": False},
    },
    "pmcc": {
        "summary": {"hold_to_expiry": False, "allow_assignment": False, "rolling_enabled": True, "manage_short_call_only": True},
        "controls": {"avoid_early_close": True, "brokerage_aware_hold": True, "roll_itm_near_expiry": True, "roll_delta_based": True, "market_aware_roll_suggestion": True, "target_delta_min": 0.25, "target_delta_max": 0.35, "manage_short_call_only": True, "roll_before_assignment": True},
    },
}


STRATEGY_TYPE_TO_MODE = {
    "covered_call": "income",
    "cc": "income",
    "wheel": "wheel",
    "defensive": "defensive",
    "pmcc": "pmcc",
}


def _normalize_strategy_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    strategy_mode = (payload.get("strategy_mode") or "income").lower()
    if strategy_mode not in STRATEGY_MODE_DEFAULTS:
        raise HTTPException(status_code=400, detail=f"Invalid strategy_mode: {strategy_mode}")
    import copy
    defaults = copy.deepcopy(STRATEGY_MODE_DEFAULTS[strategy_mode])
    controls = defaults["controls"]
    alerts = {"assignment_risk_alert": True, "assignment_imminent_alert": True}
    controls.update(payload.get("controls") or {})
    alerts.update(payload.get("alerts") or {})
    # Rules are now applied per-trade based on strategy_type — no global contradictions enforced
    summary = {
        "hold_to_expiry": strategy_mode in {"income", "wheel"},
        "allow_assignment": strategy_mode in {"income", "wheel"},
        "rolling_enabled": strategy_mode in {"defensive", "pmcc"},
        "manage_short_call_only": strategy_mode == "pmcc",
    }
    return {"strategy_mode": strategy_mode, "controls": controls, "alerts": alerts, "summary": summary}


def _materialize_strategy_rules(user_id: str, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()
    controls = config["controls"]
    alerts = config["alerts"]
    rules = []

    def add_rule(name, description, action_type, conditions, priority, action_params=None, strategy_type=None):
        rule = {"id": str(uuid.uuid4()), "user_id": user_id, "name": name, "description": description,
                "conditions": conditions, "action": action_type, "action_params": action_params or {},
                "priority": priority, "is_enabled": True, "times_triggered": 0,
                "created_at": now, "updated_at": now, "source": "strategy_config"}
        if strategy_type:
            rule["strategy_type"] = strategy_type
        rules.append(rule)

    # OTM expiry — all strategies
    add_rule("OTM Expiry", "Allow option to expire worthless when OTM at expiry.",
             "alert", [{"field": "dte_remaining", "operator": "==", "value": 0}], 100,
             {"action_type": "expire", "message": "Allow option to expire worthless"})

    # CC and Wheel: accept assignment at expiry
    for st in ("covered_call", "wheel"):
        label = "CC" if st == "covered_call" else "Wheel"
        add_rule(f"{label} — Accept Assignment", f"Assignment is acceptable for {label} strategy.",
                 "alert", [{"field": "dte_remaining", "operator": "<=", "value": 0}], 95,
                 {"action_type": "assignment", "message": "Allow assignment"}, strategy_type=st)

    # PMCC and Defensive: rolling controls
    if controls.get("roll_itm_near_expiry"):
        for st in ("pmcc", "defensive"):
            label = "PMCC" if st == "pmcc" else "Defensive"
            add_rule(f"{label} — Roll ITM Near Expiry", "Roll the short call to avoid assignment.",
                     "roll_out", [{"field": "dte_remaining", "operator": "<=", "value": 7},
                                  {"field": "current_delta", "operator": ">=", "value": 0.65}], 90,
                     {"action_type": "roll", "message": "Roll short call to avoid assignment"}, strategy_type=st)

    if controls.get("roll_delta_based"):
        for st in ("pmcc", "defensive"):
            label = "PMCC" if st == "pmcc" else "Defensive"
            add_rule(f"{label} — Delta-Based Roll", "Roll when delta indicates rising assignment risk.",
                     "roll_out", [{"field": "current_delta", "operator": ">=", "value": 0.75}], 85,
                     {"action_type": "roll", "message": "Roll based on delta threshold",
                      "target_delta_min": controls.get("target_delta_min", 0.25),
                      "target_delta_max": controls.get("target_delta_max", 0.35)}, strategy_type=st)

    if controls.get("roll_before_assignment"):
        add_rule("PMCC — Roll Before Assignment", "Roll short call before assignment occurs.",
                 "roll_out", [{"field": "current_delta", "operator": ">=", "value": 0.80},
                              {"field": "dte_remaining", "operator": "<=", "value": 5}], 88,
                 {"action_type": "roll", "message": "Roll short call before assignment"}, strategy_type="pmcc")

    if controls.get("manage_short_call_only"):
        add_rule("PMCC — Manage Short Call Only", "Keep LEAPS intact and manage only the short call.",
                 "alert", [], 80, {"action_type": "manage_short", "message": "Manage short call only"},
                 strategy_type="pmcc")

    # Alerts — all strategies
    if alerts.get("assignment_risk_alert"):
        add_rule("Assignment Risk Alert", "Alert when assignment risk is elevated.", "alert",
                 [{"field": "current_delta", "operator": ">=", "value": 0.70},
                  {"field": "dte_remaining", "operator": "<=", "value": 7}], 70,
                 {"action_type": "alert", "message": "High assignment risk detected"})
    if alerts.get("assignment_imminent_alert"):
        add_rule("Assignment Imminent Alert", "Critical alert when assignment is very likely.", "alert",
                 [{"field": "current_delta", "operator": ">=", "value": 0.85},
                  {"field": "dte_remaining", "operator": "<=", "value": 3}], 75,
                 {"action_type": "alert", "message": "Assignment is imminent"})

    return rules


def _preview_trade_action(trade: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    trade_strategy = trade.get("strategy_type", "covered_call")
    mode = STRATEGY_TYPE_TO_MODE.get(trade_strategy, "income")
    delta = float(trade.get("current_delta") or 0)
    dte = int(trade.get("dte_remaining") or 0)
    triggers = []
    decision = "hold"
    reason = "No action required under current thresholds"

    if dte <= 0:
        if mode in {"income", "wheel"}:
            decision = "allow_assignment"
            reason = f"{mode.title()} mode accepts assignment at expiry"
        else:
            decision = "roll_short_call"
            reason = f"{'PMCC' if mode == 'pmcc' else 'Defensive'} mode avoids assignment and prefers rolling"
        triggers.append("expiry")
    elif mode in {"defensive", "pmcc"} and dte <= 7 and delta >= 0.65:
        decision = "roll_short_call"
        reason = f"{mode.title()} mode avoids assignment — ITM/near expiry"
        triggers.append("roll_itm_near_expiry")
    elif mode in {"defensive", "pmcc"} and delta >= 0.75:
        decision = "roll_short_call"
        reason = f"{mode.title()} mode roll trigger — delta exceeded threshold"
        triggers.append("roll_delta_based")
    elif mode == "pmcc":
        decision = "manage_short_call_only"
        reason = "PMCC mode manages only the short leg and avoids assignment"
        triggers.append("manage_short_call_only")
    else:
        decision = "hold_to_expiry"
        reason = f"{mode.title()} mode prefers holding to expiry"
        triggers.append("hold_to_expiry")

    if delta >= 0.85 and dte <= 3:
        triggers.append("assignment_imminent_alert")
    elif delta >= 0.70 and dte <= 7:
        triggers.append("assignment_risk_alert")

    return {"trade_id": trade.get("id"), "symbol": trade.get("symbol", "SAMPLE"),
            "strategy": trade.get("strategy_type", "covered_call"), "status": trade.get("status", "open"),
            "dte": dte, "delta": delta, "decision": decision, "reason": reason, "matched_rules": triggers}


# ==================== RULES ENDPOINTS ====================

@simulator_router.get("/rules/config")
async def get_rules_config(user: dict = Depends(get_current_user)):
    existing = await db.simulator_rule_configs.find_one({"user_id": user["id"]}, {"_id": 0})
    if not existing:
        existing = _normalize_strategy_config({"strategy_mode": "income"})
        existing["user_id"] = user["id"]
        existing["updated_at"] = datetime.now(timezone.utc).isoformat()
    materialized = _materialize_strategy_rules(user["id"], existing)
    return {
        "controls": existing.get("controls", {}),
        "alerts": existing.get("alerts", {}),
        "materialized_rules": materialized,
        "updated_at": existing.get("updated_at"),
    }


@simulator_router.put("/rules/config")
async def update_rules_config(config: StrategyRuleConfigUpdate, user: dict = Depends(get_current_user)):
    payload = config.dict()
    now = datetime.now(timezone.utc).isoformat()
    # Preserve existing strategy_mode from DB so _normalize_strategy_config is happy
    existing_doc = await db.simulator_rule_configs.find_one({"user_id": user["id"]}, {"_id": 0})
    payload["strategy_mode"] = (existing_doc or {}).get("strategy_mode", "income")
    normalized = _normalize_strategy_config(payload)
    doc = {**normalized, "user_id": user["id"], "updated_at": now}
    await db.simulator_rule_configs.update_one({"user_id": user["id"]}, {"$set": doc}, upsert=True)
    await db.simulator_rules.delete_many({"user_id": user["id"], "source": "strategy_config"})
    materialized_rules = _materialize_strategy_rules(user["id"], normalized)
    if materialized_rules:
        await db.simulator_rules.insert_many(materialized_rules)
    # pymongo adds _id (ObjectId) to each dict in-place during insert_many — strip before returning
    cleaned_rules = [{k: v for k, v in r.items() if k != "_id"} for r in materialized_rules]
    return {
        "message": "Rules config saved",
        "config": {
            "controls": normalized.get("controls", {}),
            "alerts": normalized.get("alerts", {}),
            "materialized_rules": cleaned_rules,
            "updated_at": now,
        },
    }


@simulator_router.post("/rules/preview")
async def preview_rules_config(payload: RulesPreviewRequest, user: dict = Depends(get_current_user)):
    existing = await db.simulator_rule_configs.find_one({"user_id": user["id"]}, {"_id": 0})
    if not existing:
        existing = _normalize_strategy_config({"strategy_mode": "income"})
    trades = []
    if payload.trade_id:
        trade = await db.simulator_trades.find_one({"id": payload.trade_id, "user_id": user["id"]}, {"_id": 0})
        if not trade:
            raise HTTPException(status_code=404, detail="Trade not found")
        trades = [trade]
    else:
        live_trades = await db.simulator_trades.find(
            {"user_id": user["id"], "status": {"$in": ["open", "rolled", "active"]}}, {"_id": 0}
        ).to_list(50)
        if live_trades:
            trades = live_trades
        else:
            # Sample trades covering both CC and PMCC to demonstrate per-trade rules
            trades = [
                {"id": "sample-cc-otm", "symbol": "AAPL (CC)", "strategy_type": "covered_call", "status": "open", "dte_remaining": 2, "current_delta": 0.22},
                {"id": "sample-cc-itm", "symbol": "TSLA (CC)", "strategy_type": "covered_call", "status": "open", "dte_remaining": 3, "current_delta": 0.78},
                {"id": "sample-pmcc-itm", "symbol": "NVDA (PMCC)", "strategy_type": "pmcc", "status": "open", "dte_remaining": 5, "current_delta": 0.70},
                {"id": "sample-pmcc-delta", "symbol": "AMZN (PMCC)", "strategy_type": "pmcc", "status": "open", "dte_remaining": 12, "current_delta": 0.81},
            ]
    previews = [_preview_trade_action(trade, existing) for trade in trades]
    return {
        "dry_run": True, "strategy_mode": existing["strategy_mode"], "summary": existing["summary"],
        "controls": existing["controls"], "alerts": existing["alerts"],
        "trades_evaluated": len(previews), "rules_count": len(_materialize_strategy_rules(user["id"], existing)),
        "results": previews,
    }


@simulator_router.post("/rules")
async def create_trade_rule(rule: TradeRuleCreate, user: dict = Depends(get_current_user)):
    """Create a new trade management rule"""
    
    rule_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    
    rule_doc = {
        "id": rule_id,
        "user_id": user["id"],
        "name": rule.name,
        "description": rule.description,
        "rule_type": rule.rule_type,
        "conditions": rule.conditions,
        "action": rule.action,
        "action_params": rule.action_params,
        "priority": rule.priority,
        "is_enabled": rule.is_enabled,
        "times_triggered": 0,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat()
    }
    
    await db.simulator_rules.insert_one(rule_doc)
    rule_doc.pop("_id", None)
    
    return {"message": "Rule created", "rule": rule_doc}


@simulator_router.get("/rules")
async def get_trade_rules(
    rule_type: Optional[str] = Query(None),
    is_enabled: Optional[bool] = Query(None),
    user: dict = Depends(get_current_user)
):
    """Get all trade rules for the user"""
    
    query = {"user_id": user["id"]}
    if rule_type:
        query["rule_type"] = rule_type
    if is_enabled is not None:
        query["is_enabled"] = is_enabled
    
    rules = await db.simulator_rules.find(query, {"_id": 0}).sort("priority", -1).to_list(100)
    return {"rules": rules}


@simulator_router.get("/rules/templates")
async def get_rule_templates(user: dict = Depends(get_current_user)):
    """
    Get pre-built rule templates for Income Strategy Trade Management.
    
    CORE PRINCIPLE:
    For CC and PMCC, loss is NOT managed via stop-loss.
    Loss is managed via time, premium decay, rolling, and assignment logic.
    
    Categories:
    - Premium Harvesting: Hold to expiry for max premium capture
    - Expiry Management: OTM/ITM expiry handling
    - Assignment Awareness: Alerts only (no forced actions)
    - Rolling Rules: Core income logic (roll instead of close)
    - PMCC-Specific: Short leg management
    """
    
    templates = [
        # ============ PREMIUM HARVESTING (No Early Close) ============
        {
            "id": "hold_to_expiry",
            "name": "Hold to Expiry – Premium Capture",
            "description": "Hold option until expiry to maximise premium capture and avoid brokerage costs",
            "category": "premium_harvesting",
            "rule_type": "income_strategy",
            "conditions": [
                {"field": "option_moneyness", "operator": "==", "value": "OTM"},
                {"field": "dte_remaining", "operator": ">", "value": 0}
            ],
            "action": {"action_type": "hold", "reason": "premium_capture"},
            "action_params": {"message": "Income strategy prefers expiry over early exit"},
            "priority": 1,
            "is_default": True,
            "ui_hint": "Brokerage-aware strategy"
        },
        
        # ============ EXPIRY-BASED DECISIONS (Primary Controls) ============
        {
            "id": "expiry_otm",
            "name": "Expiry Management – OTM",
            "description": "Allow option to expire worthless when out-of-the-money. Full premium realised.",
            "category": "expiry_management",
            "rule_type": "expiry",
            "conditions": [
                {"field": "dte_remaining", "operator": "==", "value": 0},
                {"field": "option_moneyness", "operator": "==", "value": "OTM"}
            ],
            "action": {"action_type": "expire", "reason": "otm_expiry"},
            "action_params": {"outcome": "expired", "message": "Option expired worthless - Full premium captured"},
            "priority": 100,
            "is_default": True
        },
        {
            "id": "expiry_itm_assignment",
            "name": "Expiry Management – ITM (Assignment Expected)",
            "description": "Prepare for assignment when option finishes in-the-money. Assignment is a valid income outcome.",
            "category": "expiry_management",
            "rule_type": "expiry",
            "conditions": [
                {"field": "dte_remaining", "operator": "==", "value": 0},
                {"field": "option_moneyness", "operator": "==", "value": "ITM"}
            ],
            "action": {"action_type": "assignment", "reason": "itm_assignment"},
            "action_params": {"outcome": "assigned", "message": "Option assigned - executing assignment logic"},
            "priority": 100,
            "is_default": True,
            "ui_hint": "Assignment is a valid income outcome"
        },
        
        # ============ ASSIGNMENT AWARENESS (Alerts Only) ============
        {
            "id": "assignment_risk_alert",
            "name": "Assignment Risk Alert",
            "description": "Alert when short call is likely to be assigned. Consider rolling to avoid assignment.",
            "category": "assignment_awareness",
            "rule_type": "alert",
            "conditions": [
                {"field": "current_delta", "operator": ">=", "value": 0.70},
                {"field": "dte_remaining", "operator": "<=", "value": 7}
            ],
            "action": {"action_type": "alert", "reason": "high_assignment_risk"},
            "action_params": {"message": "High assignment probability detected. Consider rolling to avoid assignment.", "severity": "warning"},
            "priority": 90,
            "is_default": True,
            "ui_hint": "Alert only - no forced action"
        },
        {
            "id": "assignment_imminent_alert",
            "name": "Assignment Imminent Alert",
            "description": "Critical alert when assignment is very likely (deep ITM near expiry).",
            "category": "assignment_awareness",
            "rule_type": "alert",
            "conditions": [
                {"field": "current_delta", "operator": ">=", "value": 0.85},
                {"field": "dte_remaining", "operator": "<=", "value": 3}
            ],
            "action": {"action_type": "alert", "reason": "assignment_imminent"},
            "action_params": {"message": "CRITICAL: Assignment highly likely. Roll immediately or accept assignment.", "severity": "critical"},
            "priority": 95,
            "is_default": True
        },
        
        # ============ ROLLING RULES (Core Income Logic) ============
        {
            "id": "roll_itm_near_expiry",
            "name": "Roll Short Call – ITM Near Expiry",
            "description": "Roll the short call forward to avoid assignment and continue income generation. Prefer same or higher strike with net credit.",
            "category": "rolling",
            "rule_type": "roll",
            "conditions": [
                {"field": "option_moneyness", "operator": "==", "value": "ITM"},
                {"field": "dte_remaining", "operator": "<=", "value": 7}
            ],
            "action": {"action_type": "roll", "reason": "itm_near_expiry"},
            "action_params": {
                "roll_strategy": "roll_out",
                "target_dte": 30,
                "strike_preference": "same_or_higher",
                "credit_required": True,
                "message": "Roll short call out in time. Prefer same strike or higher with net credit ≥ $0"
            },
            "priority": 80,
            "is_default": True
        },
        {
            "id": "roll_delta_based",
            "name": "Roll Short Call – Delta Based",
            "description": "Roll when delta suggests rising assignment risk. Target lower delta (0.25-0.35) with later expiry.",
            "category": "rolling",
            "rule_type": "roll",
            "conditions": [
                {"field": "current_delta", "operator": ">=", "value": 0.75},
                {"field": "dte_remaining", "operator": ">", "value": 7}
            ],
            "action": {"action_type": "roll", "reason": "high_delta"},
            "action_params": {
                "roll_strategy": "roll_up_and_out",
                "target_delta_min": 0.25,
                "target_delta_max": 0.35,
                "credit_preferred": True,
                "message": "Roll to lower delta (0.25-0.35) with later expiry. Net credit preferred."
            },
            "priority": 75,
            "is_default": True
        },
        {
            "id": "roll_suggestion_market_aware",
            "name": "Suggested Roll – Market-Aware",
            "description": "System provides recommended strike prices when rolling, based on current market conditions.",
            "category": "rolling",
            "rule_type": "suggestion",
            "conditions": [
                {"field": "roll_triggered", "operator": "==", "value": True}
            ],
            "action": {"action_type": "suggest", "reason": "market_aware_roll"},
            "action_params": {
                "new_expiry_range_days": [14, 30],
                "strike_selection": "above_current_price",
                "target_delta": [0.25, 0.35],
                "prefer": ["net_credit", "iv_rank_improvement"],
                "message": "Suggestion only — user confirms execution"
            },
            "priority": 70,
            "is_default": False,
            "ui_hint": "System-guided suggestion"
        },
        
        # ============ PMCC-SPECIFIC RULES (Short Leg Focused) ============
        {
            "id": "pmcc_manage_short_only",
            "name": "PMCC – Manage Short Call Only",
            "description": "Long LEAPS are not closed unless exercised or explicitly exited. All rolling applies only to short call.",
            "category": "pmcc_specific",
            "rule_type": "pmcc",
            "strategy_type": "pmcc",
            "conditions": [
                {"field": "strategy_type", "operator": "==", "value": "pmcc"}
            ],
            "action": {"action_type": "manage_short", "reason": "pmcc_structure"},
            "action_params": {
                "manage": "short_call_only",
                "long_leaps": "hold",
                "message": "Long LEAPS remain open across cycles. Rolling applies to short call only."
            },
            "priority": 85,
            "is_default": True,
            "strategy_type": "pmcc"
        },
        {
            "id": "pmcc_assignment_handling",
            "name": "PMCC Assignment Handling",
            "description": "Handle short call assignment using the long LEAPS efficiently. Choose to exercise or close LEAPS.",
            "category": "pmcc_specific",
            "rule_type": "pmcc",
            "strategy_type": "pmcc",
            "conditions": [
                {"field": "strategy_type", "operator": "==", "value": "pmcc"},
                {"field": "status", "operator": "==", "value": "assigned"}
            ],
            "action": {"action_type": "prompt", "reason": "pmcc_assignment"},
            "action_params": {
                "options": [
                    {"id": "exercise_leaps", "label": "Exercise LEAPS (if ITM and profitable)"},
                    {"id": "close_leaps", "label": "Close LEAPS at market"}
                ],
                "message": "Short call assigned. Long LEAPS available to cover. Select preferred action."
            },
            "priority": 95,
            "is_default": True,
            "strategy_type": "pmcc"
        },
        {
            "id": "pmcc_roll_before_assignment",
            "name": "PMCC – Roll Before Assignment",
            "description": "For PMCC, always prefer rolling the short call over accepting assignment. Assignment should be avoided.",
            "category": "pmcc_specific",
            "rule_type": "pmcc",
            "strategy_type": "pmcc",
            "conditions": [
                {"field": "strategy_type", "operator": "==", "value": "pmcc"},
                {"field": "current_delta", "operator": ">=", "value": 0.65},
                {"field": "dte_remaining", "operator": "<=", "value": 14}
            ],
            "action": {"action_type": "roll", "reason": "pmcc_avoid_assignment"},
            "action_params": {
                "roll_strategy": "roll_up_and_out",
                "urgency": "high",
                "message": "PMCC: Roll short call to avoid assignment and preserve LEAPS structure"
            },
            "priority": 88,
            "is_default": True,
            "strategy_type": "pmcc"
        },
        
        # ============ BROKERAGE-AWARE CONTROLS ============
        {
            "id": "avoid_early_close",
            "name": "Avoid Early Close",
            "description": "Avoid closing positions early to reduce brokerage impact. Income strategy prefers holding to expiry.",
            "category": "brokerage_aware",
            "rule_type": "guidance",
            "conditions": [],
            "action": {"action_type": "guidance", "reason": "brokerage_awareness"},
            "action_params": {"message": "Brokerage-aware strategy - early close not recommended"},
            "priority": 1,
            "is_default": True,
            "ui_hint": "Brokerage-aware strategy"
        },
        
        # ============ INFORMATIONAL (Non-Action) ============
        {
            "id": "income_strategy_reminder",
            "name": "Income Strategy Reminder",
            "description": "This strategy prioritises time decay, assignment management, and capital efficiency. Unrealised losses do not imply trade failure.",
            "category": "informational",
            "rule_type": "info",
            "conditions": [],
            "action": {"action_type": "info", "reason": "strategy_philosophy"},
            "action_params": {"message": "Unrealised losses do not imply trade failure. Manage via time and rolling."},
            "priority": 0,
            "is_default": False,
            "ui_hint": "Non-action guidance"
        },
        
        # ============ OPTIONAL/ADVANCED (De-emphasized) ============
        {
            "id": "profit_75_optional",
            "name": "[Optional] 75% Profit Target",
            "description": "Close trade when 75% of max premium is captured. Use sparingly - increases brokerage costs.",
            "category": "optional_advanced",
            "rule_type": "profit_target",
            "conditions": [{"field": "premium_capture_pct", "operator": ">=", "value": 75}],
            "action": {"action_type": "close", "reason": "profit_target_75pct"},
            "action_params": {"message": "Optional: Early profit taking (increases brokerage)"},
            "priority": 10,
            "is_default": False,
            "is_advanced": True,
            "ui_hint": "Advanced - increases brokerage"
        },
        {
            "id": "stop_loss_200_optional",
            "name": "[Advanced] 200% Stop Loss",
            "description": "Close trade when loss is 2x initial premium. NOT recommended for income strategies.",
            "category": "optional_advanced",
            "rule_type": "stop_loss",
            "conditions": [{"field": "premium_capture_pct", "operator": "<=", "value": -200}],
            "action": {"action_type": "close", "reason": "stop_loss_200pct"},
            "action_params": {"message": "Advanced: Stop-loss exit (not typical for income strategy)"},
            "priority": 20,
            "is_default": False,
            "is_advanced": True,
            "ui_hint": "Advanced - not recommended"
        }
    ]
    
    return {"templates": templates}


@simulator_router.post("/rules/from-template/{template_id}")
async def create_rule_from_template(template_id: str, user: dict = Depends(get_current_user)):
    """Create a new rule from a template"""
    
    templates_response = await get_rule_templates(user)
    templates = templates_response["templates"]
    
    template = next((t for t in templates if t["id"] == template_id), None)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    # Templates store action as {"action_type": "...", "reason": "..."}
    # but TradeRuleCreate.action expects a plain str — extract and map it
    ACTION_MAP = {
        "hold": "alert",
        "expire": "alert",
        "assignment": "alert",
        "suggest": "alert",
        "manage_short": "alert",
        "roll": "roll_out",
        "prompt": "alert",
        "guidance": "alert",
        "info": "alert",
    }
    raw_action = template["action"]
    if isinstance(raw_action, dict):
        action_type = raw_action.get("action_type")
        if not action_type:
            raise HTTPException(status_code=400, detail="Template action missing action_type")
        action_str = ACTION_MAP.get(action_type, action_type)
        # Merge template reason into action_params
        existing_params = dict(template.get("action_params") or {})
        reason = raw_action.get("reason")
        if reason:
            existing_params.setdefault("reason", reason)
        action_params = existing_params or None
    else:
        action_str = raw_action
        action_params = template.get("action_params")

    rule = TradeRuleCreate(
        name=template["name"],
        description=template["description"],
        rule_type=template["rule_type"],
        conditions=template["conditions"],
        action=action_str,
        action_params=action_params,
        priority=template.get("priority", 0),
        is_enabled=True
    )

    return await create_trade_rule(rule, user)


@simulator_router.post("/rules/evaluate")
async def evaluate_rules_now(user: dict = Depends(get_current_user)):
    """Manually evaluate all rules against active trades"""
    
    user_rules = await db.simulator_rules.find(
        {"user_id": user["id"], "is_enabled": True},
        {"_id": 0}
    ).to_list(100)
    
    if not user_rules:
        return {"message": "No active rules", "results": []}
    
    active_trades = await db.simulator_trades.find(
        {"user_id": user["id"], "status": {"$in": ["open", "rolled"]}},
        {"_id": 0}
    ).to_list(1000)
    
    if not active_trades:
        return {"message": "No active trades", "results": []}
    
    all_results = []
    for trade in active_trades:
        results = await evaluate_and_execute_rules(trade, user_rules, db)
        all_results.extend(results)
        
        for result in results:
            if result.get("success") and result.get("rule_id"):
                await db.simulator_rules.update_one(
                    {"id": result["rule_id"]},
                    {"$inc": {"times_triggered": 1}}
                )
    
    return {
        "message": f"Evaluated {len(user_rules)} rules against {len(active_trades)} trades",
        "results": all_results,
        "trades_evaluated": len(active_trades),
        "rules_triggered": len([r for r in all_results if r.get("success")])
    }


@simulator_router.get("/rules/{rule_id}")
async def get_rule_detail(rule_id: str, user: dict = Depends(get_current_user)):
    """Get details of a specific rule"""
    rule = await db.simulator_rules.find_one(
        {"id": rule_id, "user_id": user["id"]},
        {"_id": 0}
    )
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@simulator_router.put("/rules/{rule_id}")
async def update_trade_rule(
    rule_id: str,
    updates: Dict[str, Any],
    user: dict = Depends(get_current_user)
):
    """Update a trade rule"""
    
    rule = await db.simulator_rules.find_one({"id": rule_id, "user_id": user["id"]})
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    allowed_fields = ["name", "description", "conditions", "action", "action_params", "priority", "is_enabled"]
    update_doc = {k: v for k, v in updates.items() if k in allowed_fields}
    update_doc["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    await db.simulator_rules.update_one(
        {"id": rule_id},
        {"$set": update_doc}
    )
    
    updated_rule = await db.simulator_rules.find_one({"id": rule_id}, {"_id": 0})
    return {"message": "Rule updated", "rule": updated_rule}


@simulator_router.delete("/rules/{rule_id}")
async def delete_trade_rule(rule_id: str, user: dict = Depends(get_current_user)):
    """Delete a trade rule"""
    result = await db.simulator_rules.delete_one({"id": rule_id, "user_id": user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"message": "Rule deleted"}


@simulator_router.get("/action-logs")
async def get_action_logs(
    trade_id: Optional[str] = Query(None),
    rule_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    user: dict = Depends(get_current_user)
):
    """Get action logs for rule executions"""
    try:
        query = {"user_id": user["id"]}
        if trade_id:
            query["trade_id"] = trade_id
        if rule_id:
            query["rule_id"] = rule_id

        total = await db.simulator_action_logs.count_documents(query)
        logs = await db.simulator_action_logs.find(
            query,
            {"_id": 0}
        ).sort("timestamp", -1).limit(limit).to_list(limit)

        return {
            "logs": logs,
            "count": len(logs),
            "total": total,
            "pages": max(1, (total + limit - 1) // limit)
        }
    except Exception as e:
        logging.error(f"Failed to fetch action logs: {e}")
        return {"logs": [], "count": 0, "total": 0, "pages": 1}


@simulator_router.get("/unread-alerts")
async def get_unread_alerts(user: dict = Depends(get_current_user)):
    """Get unread alert logs for login-time popup notification"""
    try:
        alerts = await db.simulator_action_logs.find(
            {"user_id": user["id"], "action": "alert", "read": {"$ne": True}},
            {"_id": 0}
        ).sort("timestamp", -1).to_list(50)
        return {"alerts": alerts, "count": len(alerts)}
    except Exception as e:
        logging.error(f"Failed to fetch unread alerts: {e}")
        return {"alerts": [], "count": 0}


@simulator_router.post("/mark-alerts-read")
async def mark_alerts_read(user: dict = Depends(get_current_user)):
    """Mark all alert logs as read (called when user dismisses login popup)"""
    try:
        await db.simulator_action_logs.update_many(
            {"user_id": user["id"], "action": "alert", "read": {"$ne": True}},
            {"$set": {"read": True}}
        )
        return {"message": "Alerts marked as read"}
    except Exception as e:
        logging.error(f"Failed to mark alerts read: {e}")
        raise HTTPException(status_code=500, detail="Failed to mark alerts read")


# ==================== PMCC SUMMARY ====================

@simulator_router.get("/pmcc-summary")
async def get_pmcc_summary(user: dict = Depends(get_current_user)):
    """
    Get PMCC-specific summary statistics.
    
    PMCC Tracker Purpose (per spec):
    - Track cumulative premium income vs LEAPS decay
    - Show PMCC trades in OPEN, ROLLED, ASSIGNED status
    - Monitor downside protection status
    
    Response format matches frontend expectations.
    """
    
    pmcc_trades = await db.simulator_trades.find(
        {"user_id": user["id"], "strategy_type": "pmcc"},
        {"_id": 0}
    ).to_list(10000)
    
    if not pmcc_trades:
        return {
            "overall": {
                "total_leaps_investment": 0,
                "total_premium_income": 0,
                "overall_income_ratio": 0,
                "total_unrealized_pnl": 0,
                "total_pmcc_positions": 0,
                "active_positions": 0
            },
            "summary": []
        }
    
    # Active includes OPEN, ROLLED, and legacy ACTIVE status (per spec visibility rules)
    active = [t for t in pmcc_trades if t.get("status") in ["open", "rolled", "active"]]
    completed = [t for t in pmcc_trades if t.get("status") in ["closed", "expired", "assigned"]]
    
    # Overall stats
    total_leaps_cost = sum((t.get("leaps_premium", 0) * 100 * t.get("contracts", 1)) for t in pmcc_trades)
    total_premium = sum((t.get("premium_received") or 0) for t in pmcc_trades)
    
    premium_ratio = (total_premium / total_leaps_cost * 100) if total_leaps_cost > 0 else 0
    
    realized_pnl = sum((t.get("realized_pnl") or t.get("final_pnl") or 0) for t in completed)
    unrealized_pnl = sum((t.get("unrealized_pnl") or 0) for t in active)
    
    # Build per-position summary array for the frontend
    # This should show OPEN, ROLLED, and ASSIGNED trades (per spec)
    summary = []
    now = datetime.now()
    
    for trade in pmcc_trades:
        if trade.get("status") in ["open", "rolled", "active", "assigned"]:  # Show all except closed/expired
            leaps_cost = (trade.get("leaps_premium", 0) * 100 * trade.get("contracts", 1))
            premium_collected = trade.get("premium_received", 0) or 0
            income_ratio = (premium_collected / leaps_cost * 100) if leaps_cost > 0 else 0
            
            # Calculate days to LEAPS expiry
            days_to_leaps_expiry = 0
            try:
                leaps_expiry_dt = datetime.strptime(trade.get("leaps_expiry", ""), "%Y-%m-%d")
                days_to_leaps_expiry = max((leaps_expiry_dt - now).days, 0)
            except:
                days_to_leaps_expiry = 365
            
            # Determine health status
            current_delta = trade.get("current_delta", 0.3)
            dte_remaining = trade.get("dte_remaining", 30)
            
            health = "good"
            if trade.get("status") == "assigned":
                health = "critical"
            elif current_delta >= 0.70 or dte_remaining <= 3:
                health = "critical"
            elif current_delta >= 0.50 or dte_remaining <= 7:
                health = "warning"
            
            # Estimate LEAPS decay - rough approximation based on time decay
            # Typically options lose ~1/3 of their time value in the last 30 days
            if days_to_leaps_expiry > 0:
                days_elapsed = (now - datetime.strptime(trade.get("entry_date", now.strftime("%Y-%m-%d")), "%Y-%m-%d")).days
                total_days = days_elapsed + days_to_leaps_expiry
                # Rough estimate: decay accelerates toward expiry
                decay_factor = days_elapsed / total_days if total_days > 0 else 0
                estimated_leaps_decay_pct = decay_factor * 100 * 0.5  # Assume 50% max time decay over life
            else:
                estimated_leaps_decay_pct = 50  # Expired
            
            summary.append({
                "original_trade_id": trade.get("id"),
                "symbol": trade.get("symbol"),
                "status": trade.get("status"),
                "leaps_strike": trade.get("leaps_strike", 0),
                "leaps_expiry": trade.get("leaps_expiry", ""),
                "leaps_cost": round(leaps_cost, 2),
                "leaps_current_value": trade.get("current_leaps_value", leaps_cost),
                "short_call_strike": trade.get("short_call_strike", 0),
                "short_call_expiry": trade.get("short_call_expiry", ""),
                "contracts": trade.get("contracts", 1),
                "total_premium_received": round(premium_collected, 2),
                "income_ratio": round(income_ratio, 1),
                "income_to_cost_ratio": round(income_ratio, 1),  # Alias for frontend
                "estimated_leaps_decay_pct": round(estimated_leaps_decay_pct, 1),
                "roll_count": trade.get("roll_count", 0),
                "total_realized_pnl": round(trade.get("realized_pnl") or trade.get("final_pnl") or 0, 2),
                "unrealized_pnl": round(trade.get("unrealized_pnl") or 0, 2),
                "dte_remaining": dte_remaining,
                "days_to_leaps_expiry": days_to_leaps_expiry,
                "entry_date": trade.get("entry_date", ""),
                "health": health,
                # Assignment warning per spec
                "assignment_risk": "HIGH" if trade.get("status") == "assigned" or current_delta >= 0.70 else "NORMAL"
            })
    
    return {
        "overall": {
            "total_leaps_investment": round(total_leaps_cost, 2),
            "total_premium_income": round(total_premium, 2),
            "overall_income_ratio": round(premium_ratio, 1),
            "total_unrealized_pnl": round(unrealized_pnl, 2),
            "total_realized_pnl": round(realized_pnl, 2),
            "total_pmcc_positions": len(pmcc_trades),
            "active_positions": len(active),
            "completed_positions": len(completed)
        },
        "summary": summary
    }


# ==================== ANALYTICS ENDPOINTS ====================

@simulator_router.get("/analytics/performance")
async def get_performance_analytics(
    time_period: str = Query("all", description="all, 30d, 90d, 1y"),
    strategy_type: Optional[str] = Query(None),
    include_open: bool = Query(True, description="Include open trades in metrics"),
    user: dict = Depends(get_current_user)
):
    """
    Get comprehensive performance analytics.
    
    CRITICAL: Analytics must NOT depend only on CLOSED trades.
    It must include: OPEN, EXPIRED, ASSIGNED trades.
    
    Win Definition:
    - Assignment = WIN (for CC)
    - Worthless expiry = WIN
    - Profitable close = WIN
    
    ASSIGNED = CLOSED for analytics purposes.
    """
    
    # Get ALL trades - not just closed ones (per specification)
    base_query = {"user_id": user["id"]}
    
    if strategy_type:
        base_query["strategy_type"] = strategy_type
    
    all_trades = await db.simulator_trades.find(base_query, {"_id": 0}).to_list(10000)
    
    if not all_trades:
        return {
            "total_trades": 0,
            "open_trades": 0,
            "completed_trades": 0,
            "win_rate": 0,
            "assignment_rate": 0,
            "avg_roi": 0,
            "total_pnl": 0,
            "avg_pnl": 0,
            "max_win": 0,
            "max_loss": 0,
            "avg_holding_days": 0,
            "capital_efficiency": 0,
            "by_close_reason": {},
            "by_symbol": {},
            "by_strategy": {},
            "monthly_breakdown": [],
            "scan_parameter_analysis": []
        }
    
    # Separate open vs completed trades
    # Include "active" for backward compatibility with existing data
    open_trades = [t for t in all_trades if t.get("status") in ["open", "rolled", "active"]]
    # CRITICAL: "assigned" counts as CLOSED for analytics (per spec)
    completed_trades = [t for t in all_trades if t.get("status") in ["closed", "expired", "assigned"]]
    
    # Apply time filter only to completed trades
    if time_period != "all":
        days_map = {"30d": 30, "90d": 90, "1y": 365}
        days = days_map.get(time_period, 365)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        completed_trades = [t for t in completed_trades if t.get("close_date", "") >= cutoff]
    
    # Calculate P&L for completed trades
    completed_pnls = [(t.get("realized_pnl") or t.get("final_pnl") or 0) for t in completed_trades]
    # Calculate unrealized P&L for open trades
    open_pnls = [(t.get("unrealized_pnl") or 0) for t in open_trades]
    
    # WIN RATE CALCULATION (per spec):
    # - Assignment = WIN (shares called away at strike = profit)
    # - Worthless expiry = WIN (kept full premium)
    # - Profitable close = WIN
    winners = []
    losers = []
    
    for t in completed_trades:
        pnl = (t.get("realized_pnl") or t.get("final_pnl") or 0)
        status = t.get("status", "")
        close_reason = t.get("close_reason", "")
        
        # Assignment is a WIN for covered calls (you got paid strike price)
        # Expired OTM is a WIN (kept premium)
        if status == "assigned" and t.get("strategy_type") in ("covered_call", "wheel", "defensive"):
            winners.append(pnl)
        elif status == "expired":
            winners.append(pnl)
        elif pnl > 0:
            winners.append(pnl)
        else:
            losers.append(pnl)
    
    # Calculate assignment rate
    assigned_trades = [t for t in completed_trades if t.get("status") == "assigned"]
    assignment_rate = (len(assigned_trades) / len(completed_trades) * 100) if completed_trades else 0
    
    # ROI calculation
    rois = [t.get("roi_percent", 0) for t in completed_trades if t.get("roi_percent") is not None]
    
    total_realized_pnl = sum(completed_pnls)
    total_unrealized_pnl = sum(open_pnls)
    total_pnl = total_realized_pnl + total_unrealized_pnl if include_open else total_realized_pnl
    
    avg_pnl = total_realized_pnl / len(completed_trades) if completed_trades else 0
    win_rate = (len(winners) / len(completed_trades) * 100) if completed_trades else 0
    avg_roi = sum(rois) / len(rois) if rois else 0
    
    # Holding period for completed trades
    holding_days = []
    for t in completed_trades:
        if t.get("entry_date") and t.get("close_date"):
            try:
                entry = datetime.strptime(t["entry_date"], "%Y-%m-%d")
                close = datetime.strptime(t["close_date"], "%Y-%m-%d")
                holding_days.append((close - entry).days)
            except:
                pass
    avg_holding = sum(holding_days) / len(holding_days) if holding_days else 0
    
    # Capital efficiency (realized P&L / capital deployed)
    total_capital = sum(t.get("capital_deployed", 0) for t in completed_trades)
    capital_efficiency = (total_realized_pnl / total_capital * 100) if total_capital > 0 else 0
    
    # By close reason
    by_reason = {}
    for t in completed_trades:
        reason = t.get("close_reason", "unknown")
        if reason not in by_reason:
            by_reason[reason] = {"count": 0, "total_pnl": 0, "avg_pnl": 0}
        by_reason[reason]["count"] += 1
        by_reason[reason]["total_pnl"] += (t.get("realized_pnl") or t.get("final_pnl") or 0)
    
    for reason in by_reason:
        if by_reason[reason]["count"] > 0:
            by_reason[reason]["avg_pnl"] = round(by_reason[reason]["total_pnl"] / by_reason[reason]["count"], 2)
        by_reason[reason]["total_pnl"] = round(by_reason[reason]["total_pnl"], 2)
    
    # By symbol (include both open and completed)
    by_symbol = {}
    for t in all_trades:
        symbol = t.get("symbol", "UNKNOWN")
        if symbol not in by_symbol:
            by_symbol[symbol] = {"trades": 0, "wins": 0, "total_pnl": 0, "open": 0}
        by_symbol[symbol]["trades"] += 1
        
        if t.get("status") in ["open", "rolled", "active"]:
            by_symbol[symbol]["open"] += 1
            by_symbol[symbol]["total_pnl"] += (t.get("unrealized_pnl") or 0)
        else:
            pnl = (t.get("realized_pnl") or t.get("final_pnl") or 0)
            by_symbol[symbol]["total_pnl"] += pnl
            if pnl > 0 or t.get("status") in ["assigned", "expired"]:
                by_symbol[symbol]["wins"] += 1
    
    for symbol in by_symbol:
        completed_for_symbol = by_symbol[symbol]["trades"] - by_symbol[symbol]["open"]
        by_symbol[symbol]["win_rate"] = round(by_symbol[symbol]["wins"] / completed_for_symbol * 100, 1) if completed_for_symbol > 0 else 0
        by_symbol[symbol]["total_pnl"] = round(by_symbol[symbol]["total_pnl"], 2)
    
    # By strategy (CC vs PMCC)
    by_strategy = {}
    for strategy in ["covered_call", "pmcc"]:
        strategy_trades = [t for t in all_trades if t.get("strategy_type") == strategy]
        strategy_completed = [t for t in strategy_trades if t.get("status") in ["closed", "expired", "assigned"]]
        strategy_open = [t for t in strategy_trades if t.get("status") in ["open", "rolled", "active"]]
        
        if strategy_trades:
            strategy_pnl = sum((t.get("realized_pnl") or t.get("final_pnl") or 0) for t in strategy_completed)
            strategy_unrealized = sum((t.get("unrealized_pnl") or 0) for t in strategy_open)
            strategy_wins = len([t for t in strategy_completed if (t.get("realized_pnl") or t.get("final_pnl") or 0) > 0 or t.get("status") in ["assigned", "expired"]])
            
            by_strategy[strategy] = {
                "total": len(strategy_trades),
                "open": len(strategy_open),
                "completed": len(strategy_completed),
                "realized_pnl": round(strategy_pnl, 2),
                "unrealized_pnl": round(strategy_unrealized, 2),
                "win_rate": round(strategy_wins / len(strategy_completed) * 100, 1) if strategy_completed else 0
            }
    
    # Monthly breakdown (completed trades only)
    monthly = {}
    for t in completed_trades:
        if t.get("close_date"):
            month = t["close_date"][:7]  # YYYY-MM
            if month not in monthly:
                monthly[month] = {"trades": 0, "pnl": 0, "wins": 0}
            monthly[month]["trades"] += 1
            pnl = (t.get("realized_pnl") or t.get("final_pnl") or 0)
            monthly[month]["pnl"] += pnl
            if pnl > 0 or t.get("status") in ["assigned", "expired"]:
                monthly[month]["wins"] += 1
    
    monthly_list = [
        {
            "month": m,
            "trades": monthly[m]["trades"],
            "pnl": round(monthly[m]["pnl"], 2),
            "win_rate": round(monthly[m]["wins"] / monthly[m]["trades"] * 100, 1) if monthly[m]["trades"] > 0 else 0
        }
        for m in sorted(monthly.keys())
    ]
    
    # Scan parameter analysis
    param_stats = {}
    for t in completed_trades:
        params = t.get("scan_parameters", {})
        if not params:
            continue
        
        dte_bucket = f"DTE_{(params.get('max_dte', 45) // 15) * 15}"
        delta_bucket = f"Delta_{int(params.get('max_delta', 0.45) * 100)}"
        roi_bucket = f"ROI_{int(params.get('min_roi', 0.5))}"
        
        for bucket_type, bucket in [("dte", dte_bucket), ("delta", delta_bucket), ("roi", roi_bucket)]:
            key = f"{bucket_type}:{bucket}"
            if key not in param_stats:
                param_stats[key] = {"param": bucket, "type": bucket_type, "trades": 0, "total_pnl": 0, "wins": 0}
            param_stats[key]["trades"] += 1
            pnl = (t.get("realized_pnl") or t.get("final_pnl") or 0)
            param_stats[key]["total_pnl"] += pnl
            if pnl > 0 or t.get("status") in ["assigned", "expired"]:
                param_stats[key]["wins"] += 1
    
    param_analysis = []
    for key, stats in param_stats.items():
        if stats["trades"] >= 3:
            param_analysis.append({
                "parameter": stats["param"],
                "type": stats["type"],
                "trades": stats["trades"],
                "avg_pnl": round(stats["total_pnl"] / stats["trades"], 2),
                "win_rate": round(stats["wins"] / stats["trades"] * 100, 1)
            })
    
    # Convert by_symbol dict to list format for frontend charts
    by_symbol_list = []
    for symbol, data in sorted(by_symbol.items(), key=lambda x: x[1]["total_pnl"], reverse=True)[:10]:
        completed_count = data["trades"] - data["open"]
        avg_pnl = data["total_pnl"] / completed_count if completed_count > 0 else 0
        by_symbol_list.append({
            "symbol": symbol,
            "trade_count": data["trades"],
            "trades": data["trades"],
            "wins": data["wins"],
            "total_pnl": round(data["total_pnl"], 2),
            "avg_pnl": round(avg_pnl, 2),
            "open": data["open"],
            "win_rate": data["win_rate"],
            "roi": data["win_rate"]  # Using win_rate as proxy for ROI display
        })
    
    # Return in format expected by frontend
    return {
        "analytics": {
            "overall": {
                "total_trades": len(all_trades),
                "open_trades": len(open_trades),
                "completed_trades": len(completed_trades),
                "win_rate": round(win_rate, 1),
                "assignment_rate": round(assignment_rate, 1),
                "roi": round(avg_roi, 2),
                "total_pnl": round(total_pnl, 2),
                "realized_pnl": round(total_realized_pnl, 2),
                "unrealized_pnl": round(total_unrealized_pnl, 2),
                "avg_pnl": round(avg_pnl, 2),
                "avg_win": round(max(completed_pnls), 2) if completed_pnls else 0,
                "avg_loss": round(min(completed_pnls), 2) if completed_pnls else 0,
                "avg_holding_days": round(avg_holding, 1),
                "capital_efficiency": round(capital_efficiency, 2),
                "profit_factor": round(abs(sum(winners)) / abs(sum(losers)), 2) if losers and sum(losers) != 0 else 0,
            },
            "by_close_reason": by_reason,
            "by_symbol": by_symbol_list,
            "by_strategy": by_strategy,
            "by_delta": [],  # Placeholder for future delta bucketing
            "by_dte": [],    # Placeholder for future DTE bucketing  
            "by_outcome": [
                {"outcome": "expired", "count": len([t for t in completed_trades if t.get("status") == "expired"]), "total_pnl": sum((t.get("realized_pnl") or t.get("final_pnl") or 0) for t in completed_trades if t.get("status") == "expired")},
                {"outcome": "assigned", "count": len([t for t in completed_trades if t.get("status") == "assigned"]), "total_pnl": sum((t.get("realized_pnl") or t.get("final_pnl") or 0) for t in completed_trades if t.get("status") == "assigned")},
                {"outcome": "early_close", "count": len([t for t in completed_trades if t.get("status") == "closed"]), "total_pnl": sum((t.get("realized_pnl") or t.get("final_pnl") or 0) for t in completed_trades if t.get("status") == "closed")},
            ],
            "monthly_breakdown": monthly_list,
            "scan_parameter_analysis": sorted(param_analysis, key=lambda x: x["avg_pnl"], reverse=True)
        },
        "recommendations": []  # Placeholder for AI recommendations
    }


# ==================== ANALYZER ENDPOINT (5-Section Dashboard) ====================

@simulator_router.get("/analyzer")
async def get_analyzer_metrics(
    strategy: Optional[str] = Query(None, description="Filter by strategy: covered_call, pmcc"),
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    time_period: str = Query("all", description="all, 30d, 90d, 1y"),
    user: dict = Depends(get_current_user)
):
    """
    Analyzer Dashboard — 5-Section trade-management knowledge base.
    Sections: A Performance Summary, B Open Risk, C Action Queue,
              D Strategy Quality, E Advanced Metrics (sample-gated).
    """
    query = {"user_id": user["id"]}
    if strategy:
        query["strategy_type"] = strategy
    if symbol:
        query["symbol"] = symbol.upper()

    all_trades = await db.simulator_trades.find(query, {"_id": 0}).to_list(10000)

    # Determine scope label
    scope_type = "symbol" if symbol else ("strategy" if strategy else "portfolio")

    empty_response = {
        "scope": {"type": scope_type, "strategy": strategy, "symbol": symbol, "time_period": time_period},
        "section_a_performance": None,
        "section_b_risk": None,
        "section_c_action_queue": [],
        "section_d_strategy_quality": [],
        "section_e_advanced": None,
        "sample_quality": {"closed_trade_count": 0, "days_of_history": 0, "warnings": []}
    }

    if not all_trades:
        return empty_response

    # Apply time filter
    if time_period != "all":
        days_map = {"30d": 30, "90d": 90, "1y": 365}
        days_back = days_map.get(time_period, 365)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
        all_trades = [t for t in all_trades if t.get("entry_date", "") >= cutoff]

    if not all_trades:
        return empty_response

    open_trades = [t for t in all_trades if t.get("status") in ["open", "rolled", "active"]]
    completed_trades = [t for t in all_trades if t.get("status") in ["closed", "expired", "assigned"]]

    # ── Sample quality ──────────────────────────────────────────────────────────
    all_entry_dates = [t.get("entry_date", "") for t in all_trades if t.get("entry_date")]
    days_of_history = 0
    if all_entry_dates:
        try:
            earliest = datetime.strptime(min(all_entry_dates), "%Y-%m-%d")
            days_of_history = (datetime.now() - earliest).days
        except Exception:
            pass

    n_closed = len(completed_trades)
    sample_warnings = []
    if n_closed < 5:
        sample_warnings.append("fewer_than_5_closed")
    if n_closed < 10:
        sample_warnings.append("fewer_than_10_closed")
    if days_of_history < 90:
        sample_warnings.append("less_than_90_days")

    # ── Section A: Performance Summary ─────────────────────────────────────────
    def _pnl(t):
        return t.get("realized_pnl") or t.get("final_pnl") or 0

    realized_pnl = sum(_pnl(t) for t in completed_trades)
    unrealized_pnl = sum(t.get("unrealized_pnl") or 0 for t in open_trades)
    total_pnl = realized_pnl + unrealized_pnl

    net_premium_collected = sum(t.get("premium_received") or 0 for t in all_trades)
    # Net premium kept = realized premium minus buyback costs (approximated as realized P/L from expired/profit-closed)
    net_premium_kept = sum(_pnl(t) for t in completed_trades if _pnl(t) > 0)

    # ROI on peak capital
    all_capitals = [t.get("capital_deployed") or 0 for t in all_trades]
    peak_capital_hist = sum(t.get("capital_deployed") or 0 for t in open_trades)
    for t in completed_trades:
        peak_capital_hist = max(peak_capital_hist, t.get("capital_deployed") or 0)
    roi_on_peak = (realized_pnl / peak_capital_hist * 100) if peak_capital_hist > 0 else 0

    # Avg closed trade return %
    closed_returns = []
    for t in completed_trades:
        cap = t.get("capital_deployed") or 0
        if cap > 0:
            closed_returns.append(_pnl(t) / cap * 100)
    avg_closed_trade_return_pct = sum(closed_returns) / len(closed_returns) if closed_returns else 0

    # Avg hold days
    hold_days_list = []
    for t in completed_trades:
        if t.get("entry_date") and t.get("close_date"):
            try:
                d = (datetime.strptime(t["close_date"], "%Y-%m-%d") - datetime.strptime(t["entry_date"], "%Y-%m-%d")).days
                hold_days_list.append(max(d, 0))
            except Exception:
                pass
    avg_hold_days = sum(hold_days_list) / len(hold_days_list) if hold_days_list else 0

    section_a = {
        "total_pnl": round(total_pnl, 2),
        "realized_pnl": round(realized_pnl, 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "net_premium_collected": round(net_premium_collected, 2),
        "net_premium_kept": round(net_premium_kept, 2),
        "roi_on_peak_capital": round(roi_on_peak, 2),
        "avg_closed_trade_return_pct": round(avg_closed_trade_return_pct, 2),
        "avg_hold_days": round(avg_hold_days, 1),
        "total_trades": len(all_trades),
        "open_count": len(open_trades),
        "closed_count": n_closed,
    }

    # ── Section B: Open Risk ────────────────────────────────────────────────────
    current_capital_at_risk = sum(t.get("capital_deployed") or 0 for t in open_trades)

    assignment_at_risk = [t for t in open_trades if (t.get("current_delta") or 0) >= 0.50]
    assignment_exposure = len(assignment_at_risk)
    assignment_exposure_pct = (len(assignment_at_risk) / len(open_trades) * 100) if open_trades else 0

    largest_pos_cap = max((t.get("capital_deployed") or 0 for t in open_trades), default=0)
    largest_position_weight = (largest_pos_cap / current_capital_at_risk * 100) if current_capital_at_risk > 0 else 0

    def _get_dte(t):
        return t.get("dte_remaining") or t.get("dte") or t.get("days_to_expiry") or 99

    def _get_strike(t):
        return t.get("short_call_strike") or t.get("strike") or t.get("short_strike")

    def _get_capture(t):
        return t.get("capture_pct") or t.get("premium_capture_pct")

    def _needs_action(t):
        dte = _get_dte(t)
        delta = t.get("current_delta") or 0
        return dte <= 14 or delta >= 0.50

    trades_needing_action = len([t for t in open_trades if _needs_action(t)])

    section_b = {
        "current_capital_at_risk": round(current_capital_at_risk, 2),
        "peak_capital_at_risk": round(peak_capital_hist, 2),
        "assignment_exposure": assignment_exposure,
        "assignment_exposure_pct": round(assignment_exposure_pct, 1),
        "largest_position_weight": round(largest_position_weight, 1),
        "trades_needing_action": trades_needing_action,
        "total_open": len(open_trades),
    }

    # ── Section C: Action Queue ─────────────────────────────────────────────────
    def _suggest_action(t):
        dte = _get_dte(t)
        delta = t.get("current_delta") or 0
        pnl = t.get("unrealized_pnl") or 0
        capture = _get_capture(t) or 0
        if dte <= 7:
            return "Close", "danger"
        if delta >= 0.50:
            return "Roll up or close", "danger"
        if dte <= 14 and delta >= 0.35:
            return "Roll out", "warning"
        if delta >= 0.40:
            return "Watch — consider roll", "warning"
        if capture >= 75 and dte > 14:
            return "Close early (75%+ captured)", "info"
        if dte <= 14:
            return "Hold or close", "info"
        return "Hold", "ok"

    action_queue = []
    for t in open_trades:
        action_label, action_level = _suggest_action(t)
        action_queue.append({
            "trade_id": t.get("id"),
            "symbol": t.get("symbol"),
            "strategy": t.get("strategy_type"),
            "entry_date": t.get("entry_date"),
            "expiry": t.get("expiry_date") or t.get("short_expiry") or t.get("short_call_expiry"),
            "dte": _get_dte(t) if _get_dte(t) != 99 else None,
            "strike": _get_strike(t),
            "delta": t.get("current_delta"),
            "capture_pct": _get_capture(t),
            "unrealized_pnl": t.get("unrealized_pnl"),
            "capital_deployed": t.get("capital_deployed"),
            "suggested_action": action_label,
            "action_level": action_level,  # ok / info / warning / danger
        })
    # Sort by urgency: danger first, then warning, then others
    _level_order = {"danger": 0, "warning": 1, "info": 2, "ok": 3}
    action_queue.sort(key=lambda x: _level_order.get(x["action_level"], 3))

    # ── Section D: Strategy Quality ─────────────────────────────────────────────
    section_d = []
    for strat in ["covered_call", "pmcc"]:
        strat_all = [t for t in all_trades if t.get("strategy_type") == strat]
        strat_closed = [t for t in strat_all if t.get("status") in ["closed", "expired", "assigned"]]
        strat_open = [t for t in strat_all if t.get("status") in ["open", "rolled", "active"]]
        if not strat_all:
            continue

        # Roll success rate: trades marked as rolled that eventually closed profitably
        rolled = [t for t in strat_all if t.get("roll_count", 0) > 0 or t.get("status") == "rolled"]
        rolled_profit = [t for t in rolled if _pnl(t) > 0]
        roll_success_rate = (len(rolled_profit) / len(rolled) * 100) if rolled else None

        # Assignment rate
        assigned_count = len([t for t in strat_closed if t.get("status") == "assigned"])
        assignment_rate = (assigned_count / len(strat_closed) * 100) if strat_closed else 0

        # Hold days
        s_hold = []
        for t in strat_closed:
            if t.get("entry_date") and t.get("close_date"):
                try:
                    s_hold.append(max((datetime.strptime(t["close_date"], "%Y-%m-%d") - datetime.strptime(t["entry_date"], "%Y-%m-%d")).days, 0))
                except Exception:
                    pass
        avg_hold = sum(s_hold) / len(s_hold) if s_hold else 0

        # Realized P/L
        strat_realized = sum(_pnl(t) for t in strat_closed)
        strat_unrealized = sum(t.get("unrealized_pnl") or 0 for t in strat_open)

        # Profit factor
        gw = sum(_pnl(t) for t in strat_closed if _pnl(t) > 0)
        gl = abs(sum(_pnl(t) for t in strat_closed if _pnl(t) < 0))
        profit_factor = round(gw / gl, 2) if gl > 0 else (None if gw == 0 else 99.0)

        # Win rate (sample-gated)
        winners_s = [t for t in strat_closed if _pnl(t) > 0 or t.get("status") in ["assigned", "expired"]]
        win_rate_s = (len(winners_s) / len(strat_closed) * 100) if strat_closed else 0

        # Strategy score (0–100): blend of win rate, profit factor, avg return
        avg_return_pct = sum(_pnl(t) / (t.get("capital_deployed") or 1) * 100 for t in strat_closed) / len(strat_closed) if strat_closed else 0
        pf_score = min(profit_factor or 0, 3.0) / 3.0 * 30 if profit_factor is not None else 0
        wr_score = min(win_rate_s / 100, 1.0) * 40
        ret_score = max(0, min(avg_return_pct / 10, 1.0)) * 30
        strategy_score = round(pf_score + wr_score + ret_score, 1)

        section_d.append({
            "strategy": strat,
            "strategy_label": "Covered Call" if strat == "covered_call" else "PMCC",
            "total_trades": len(strat_all),
            "open_trades": len(strat_open),
            "closed_trades": len(strat_closed),
            "win_rate": round(win_rate_s, 1),
            "avg_hold_days": round(avg_hold, 1),
            "profit_factor": profit_factor,
            "roll_success_rate": round(roll_success_rate, 1) if roll_success_rate is not None else None,
            "assignment_rate": round(assignment_rate, 1),
            "realized_pnl": round(strat_realized, 2),
            "unrealized_pnl": round(strat_unrealized, 2),
            "strategy_score": strategy_score,
            "sample_ok": len(strat_closed) >= 5,
        })

    # ── Section E: Advanced Metrics (sample-gated) ──────────────────────────────
    # Win rate
    winners_all = [t for t in completed_trades if _pnl(t) > 0 or t.get("status") in ["assigned", "expired"]]
    losers_all = [t for t in completed_trades if _pnl(t) < 0]
    win_rate_all = (len(winners_all) / n_closed * 100) if n_closed >= 5 else None

    # Profit factor
    gw_all = sum(_pnl(t) for t in completed_trades if _pnl(t) > 0)
    gl_all = abs(sum(_pnl(t) for t in completed_trades if _pnl(t) < 0))
    profit_factor_all = round(gw_all / gl_all, 2) if (gl_all > 0 and n_closed >= 5) else None

    # Max drawdown
    max_drawdown = None
    if n_closed >= 5:
        running = 0
        peak_v = 0
        max_dd = 0
        for t in sorted(completed_trades, key=lambda x: x.get("close_date", "")):
            running += _pnl(t)
            if running > peak_v:
                peak_v = running
            dd = peak_v - running
            if dd > max_dd:
                max_dd = dd
        max_drawdown = round(max_dd, 2)

    # TWR (only if 10+ closed and 90+ days)
    twr = None
    if n_closed >= 10 and days_of_history >= 90:
        wt_ret = 0
        wt_days = 0
        for t in completed_trades:
            if t.get("entry_date") and t.get("close_date"):
                try:
                    d = max((datetime.strptime(t["close_date"], "%Y-%m-%d") - datetime.strptime(t["entry_date"], "%Y-%m-%d")).days, 1)
                    cap = t.get("capital_deployed") or 1
                    wt_ret += (_pnl(t) / cap) * d
                    wt_days += d
                except Exception:
                    pass
        twr = round(wt_ret / wt_days * 365 * 100, 2) if wt_days > 0 else None

    section_e = {
        "win_rate": round(win_rate_all, 1) if win_rate_all is not None else None,
        "win_rate_gated": n_closed < 5,
        "profit_factor": profit_factor_all,
        "profit_factor_gated": n_closed < 5,
        "max_drawdown": max_drawdown,
        "max_drawdown_gated": n_closed < 5,
        "time_weighted_return": twr,
        "twr_gated": n_closed < 10 or days_of_history < 90,
        "avg_win": round(sum(_pnl(t) for t in winners_all) / len(winners_all), 2) if winners_all else 0,
        "avg_loss": round(sum(_pnl(t) for t in losers_all) / len(losers_all), 2) if losers_all else 0,
    }

    return {
        "scope": {"type": scope_type, "strategy": strategy, "symbol": symbol, "time_period": time_period},
        "section_a_performance": section_a,
        "section_b_risk": section_b,
        "section_c_action_queue": action_queue,
        "section_d_strategy_quality": section_d,
        "section_e_advanced": section_e,
        "sample_quality": {
            "closed_trade_count": n_closed,
            "days_of_history": days_of_history,
            "warnings": sample_warnings,
        }
    }


@simulator_router.get("/analytics/scanner-comparison")
async def get_scanner_comparison(user: dict = Depends(get_current_user)):
    """Compare performance across different scanner parameter sets"""
    
    trades = await db.simulator_trades.find(
        {"user_id": user["id"], "status": {"$in": ["closed", "expired", "assigned"]}},
        {"_id": 0}
    ).to_list(10000)
    
    if not trades:
        return {"profiles": [], "message": "No closed trades for analysis"}
    
    # Group trades by scan parameter profiles
    profiles = {}
    
    for t in trades:
        params = t.get("scan_parameters", {})
        if not params:
            continue
        
        # Create a profile key from key parameters
        profile_key = f"dte{params.get('max_dte', 'na')}_delta{params.get('max_delta', 'na')}_roi{params.get('min_roi', 'na')}"
        
        if profile_key not in profiles:
            profiles[profile_key] = {
                "parameters": params,
                "trades": [],
                "total_trades": 0,
                "wins": 0,
                "total_pnl": 0,
                "total_roi": 0,
                "avg_holding_days": 0
            }
        
        pnl = t.get("realized_pnl", 0) or t.get("final_pnl", 0)
        roi = t.get("roi_percent", 0)
        
        profiles[profile_key]["trades"].append(t)
        profiles[profile_key]["total_trades"] += 1
        profiles[profile_key]["total_pnl"] += pnl
        profiles[profile_key]["total_roi"] += roi
        if pnl > 0:
            profiles[profile_key]["wins"] += 1
    
    # Calculate final stats for each profile
    result_profiles = []
    for key, profile in profiles.items():
        if profile["total_trades"] < 3:  # Minimum trades for meaningful comparison
            continue
        
        # Calculate holding days
        holding_days = []
        for t in profile["trades"]:
            if t.get("entry_date") and t.get("close_date"):
                try:
                    entry = datetime.strptime(t["entry_date"], "%Y-%m-%d")
                    close = datetime.strptime(t["close_date"], "%Y-%m-%d")
                    holding_days.append((close - entry).days)
                except:
                    pass
        
        avg_holding = sum(holding_days) / len(holding_days) if holding_days else 0
        
        result_profiles.append({
            "profile_key": key,
            "parameters": {
                "max_dte": profile["parameters"].get("max_dte"),
                "max_delta": profile["parameters"].get("max_delta"),
                "min_roi": profile["parameters"].get("min_roi"),
                "min_price": profile["parameters"].get("min_price"),
                "max_price": profile["parameters"].get("max_price")
            },
            "total_trades": profile["total_trades"],
            "win_rate": round(profile["wins"] / profile["total_trades"] * 100, 1),
            "avg_pnl": round(profile["total_pnl"] / profile["total_trades"], 2),
            "total_pnl": round(profile["total_pnl"], 2),
            "avg_roi": round(profile["total_roi"] / profile["total_trades"], 2),
            "avg_holding_days": round(avg_holding, 1)
        })
    
    # Sort by avg_pnl descending
    result_profiles.sort(key=lambda x: x["avg_pnl"], reverse=True)
    
    return {
        "profiles": result_profiles,
        "total_profiles_analyzed": len(result_profiles),
        "recommendation": result_profiles[0] if result_profiles else None
    }


@simulator_router.get("/analytics/optimal-settings")
async def get_optimal_settings(user: dict = Depends(get_current_user)):
    """Analyze trade outcomes to suggest optimal screener settings"""
    
    trades = await db.simulator_trades.find(
        {"user_id": user["id"], "status": {"$in": ["closed", "expired", "assigned"]}},
        {"_id": 0}
    ).to_list(10000)
    
    if len(trades) < 10:
        return {
            "message": "Need at least 10 closed trades for optimal settings analysis",
            "current_trades": len(trades)
        }
    
    winners = [t for t in trades if (t.get("realized_pnl", 0) or t.get("final_pnl", 0)) > 0]
    losers = [t for t in trades if (t.get("realized_pnl", 0) or t.get("final_pnl", 0)) <= 0]
    
    # Analyze parameter distributions for winners vs losers
    def analyze_param(trades_list, param_path):
        values = []
        for t in trades_list:
            params = t.get("scan_parameters", {})
            if params:
                val = params.get(param_path)
                if val is not None:
                    values.append(val)
        return values
    
    def get_stats(values):
        if not values:
            return {"min": None, "max": None, "avg": None, "median": None}
        sorted_vals = sorted(values)
        return {
            "min": min(values),
            "max": max(values),
            "avg": sum(values) / len(values),
            "median": sorted_vals[len(sorted_vals) // 2]
        }
    
    params_to_analyze = ["max_dte", "max_delta", "min_delta", "min_roi", "min_price", "max_price"]
    
    analysis = {}
    recommendations = {}
    
    for param in params_to_analyze:
        winner_vals = analyze_param(winners, param)
        loser_vals = analyze_param(losers, param)
        
        winner_stats = get_stats(winner_vals)
        loser_stats = get_stats(loser_vals)
        
        analysis[param] = {
            "winners": winner_stats,
            "losers": loser_stats
        }
        
        # Generate recommendations
        if winner_stats["avg"] and loser_stats["avg"]:
            if param == "max_dte":
                # Prefer shorter DTE if winners have lower DTE
                if winner_stats["avg"] < loser_stats["avg"]:
                    recommendations[param] = {
                        "suggestion": round(winner_stats["median"], 0),
                        "reason": f"Winning trades averaged {winner_stats['avg']:.0f} DTE vs {loser_stats['avg']:.0f} for losers"
                    }
            elif param == "max_delta":
                if winner_stats["avg"] < loser_stats["avg"]:
                    recommendations[param] = {
                        "suggestion": round(winner_stats["median"], 2),
                        "reason": f"Lower delta ({winner_stats['avg']:.2f}) associated with winning trades"
                    }
            elif param == "min_roi":
                if winner_stats["avg"] > loser_stats["avg"]:
                    recommendations[param] = {
                        "suggestion": round(winner_stats["median"], 2),
                        "reason": f"Higher minimum ROI ({winner_stats['avg']:.2f}%) associated with winners"
                    }
    
    # Overall win rate
    win_rate = len(winners) / len(trades) * 100 if trades else 0
    
    # Best performing symbols
    symbol_stats = {}
    for t in trades:
        symbol = t.get("symbol", "UNKNOWN")
        if symbol not in symbol_stats:
            symbol_stats[symbol] = {"trades": 0, "wins": 0, "total_pnl": 0}
        symbol_stats[symbol]["trades"] += 1
        pnl = t.get("realized_pnl", 0) or t.get("final_pnl", 0)
        symbol_stats[symbol]["total_pnl"] += pnl
        if pnl > 0:
            symbol_stats[symbol]["wins"] += 1
    
    top_symbols = []
    for symbol, stats in symbol_stats.items():
        if stats["trades"] >= 3:
            top_symbols.append({
                "symbol": symbol,
                "trades": stats["trades"],
                "win_rate": round(stats["wins"] / stats["trades"] * 100, 1),
                "avg_pnl": round(stats["total_pnl"] / stats["trades"], 2)
            })
    
    top_symbols.sort(key=lambda x: x["avg_pnl"], reverse=True)
    
    return {
        "total_trades_analyzed": len(trades),
        "overall_win_rate": round(win_rate, 1),
        "parameter_analysis": analysis,
        "recommendations": recommendations,
        "top_symbols": top_symbols[:10],
        "bottom_symbols": sorted(top_symbols, key=lambda x: x["avg_pnl"])[:5] if top_symbols else []
    }


@simulator_router.post("/analytics/save-profile")
async def save_scanner_profile(
    name: str,
    description: Optional[str] = None,
    parameters: Dict[str, Any] = None,
    user: dict = Depends(get_current_user)
):
    """Save a scanner parameter profile based on analysis"""
    
    profile_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    
    profile_doc = {
        "id": profile_id,
        "user_id": user["id"],
        "name": name,
        "description": description,
        "parameters": parameters or {},
        "created_at": now.isoformat()
    }
    
    await db.scanner_profiles.insert_one(profile_doc)
    profile_doc.pop("_id", None)
    
    return {"message": "Profile saved", "profile": profile_doc}


@simulator_router.get("/analytics/profiles")
async def get_scanner_profiles(user: dict = Depends(get_current_user)):
    """Get saved scanner profiles"""
    
    profiles = await db.scanner_profiles.find(
        {"user_id": user["id"]},
        {"_id": 0}
    ).sort("created_at", -1).to_list(50)
    
    return {"profiles": profiles}


@simulator_router.delete("/analytics/profiles/{profile_id}")
async def delete_scanner_profile(profile_id: str, user: dict = Depends(get_current_user)):
    """Delete a scanner profile"""
    
    result = await db.scanner_profiles.delete_one({"id": profile_id, "user_id": user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Profile not found")
    
    return {"message": "Profile deleted"}


# ─── AI Manage Routes (auto-appended) ───
@simulator_router.get("/wallet")
async def get_wallet_balance(user: dict = Depends(get_current_user)):
    """
    Return the user's current AI credit balance.
    Frontend calls this to show "You have X credits" in the Manage modal.
    """
    from ai_wallet.wallet_service import WalletService as AIWalletService
    wallet_svc = AIWalletService(db)
    wallet = await wallet_svc.get_or_create_wallet(user["id"])
    balance = wallet.get("free_tokens_remaining", 0) + wallet.get("paid_tokens_remaining", 0)
    return {"balance_credits": balance}


# ─── POST /simulator/manage/{trade_id} ───────────────────────────────────────
@simulator_router.post("/manage/{trade_id}")
async def manage_trade(
    trade_id: str,
    request: Request,
    user: dict = Depends(get_current_user)
):
    """
    AI trade management endpoint.

    Body:
        {
            "mode": "recommend_only" | "apply_after_approval",
            "goals": {
                "min_weekly_return_pct": 1.0,
                "dca_enabled": false
            }
        }

    Flow:
        1. Load trade, verify ownership
        2. Fetch live price + options chain
        3. Debit wallet (charge MANAGE_COST_CREDITS)
        4. Generate recommendation (deterministic rule engine)
        5. Log to simulator_action_logs + simulator_ai_recommendations
        6. Return recommendation for user to review

    Returns:
        { "recommendation": {...}, "balance_after": int }
    """
    from ai_wallet.wallet_service import WalletService as AIWalletService
    from services.ai_trade_manager import generate_recommendation
    MANAGE_COST_CREDITS = 5

    body_data = await request.json()
    user_id = user["id"]
    mode    = body_data.get("mode", "recommend_only")
    goals   = body_data.get("goals", {})

    # ── 1. Load trade ────────────────────────────────────────────────────────
    trade = await db.simulator_trades.find_one(
        {"id": trade_id, "user_id": user_id},
        {"_id": 0}
    )

    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    if trade.get("status") not in ("open", "rolled", "active"):
        raise HTTPException(status_code=400, detail="Trade is not active — cannot manage closed/assigned trades")

    symbol = trade.get("symbol", "UNKNOWN")

    # ── 2. Fetch live price ──────────────────────────────────────────────────
    try:
        quote = await fetch_live_stock_quote(symbol)
        current_price = float(quote.get("price") or quote.get("last", 0))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Could not fetch live price for {symbol}: {e}")

    if current_price <= 0:
        raise HTTPException(status_code=503, detail=f"Invalid price returned for {symbol}")

    # ── 3. Fetch options chain ───────────────────────────────────────────────
    try:
        expiry = trade.get("expiry_date", "")
        chain  = await fetch_options_chain(symbol, expiry) if expiry else []
    except Exception:
        chain = []

    # ── 4. Debit wallet ──────────────────────────────────────────────────────
    import uuid
    wallet_svc = AIWalletService(db)
    debit_result = await wallet_svc.deduct_tokens(
        user_id=user_id,
        tokens_required=MANAGE_COST_CREDITS,
        action="trade_management",
        request_id=str(uuid.uuid4())
    )
    if not debit_result.allowed:
        wallet = await wallet_svc.get_or_create_wallet(user_id)
        current_bal = wallet.get("free_tokens_remaining", 0) + wallet.get("paid_tokens_remaining", 0)
        raise HTTPException(
            status_code=402,
            detail={
                "error": "insufficient_credits",
                "message": f"You need {MANAGE_COST_CREDITS} tokens to run AI management. "
                           f"Current balance: {current_bal}.",
                "balance": current_bal
            }
        )

    balance_after = debit_result.remaining_balance

    # ── 5. Load user rule config and generate recommendation ─────────────────
    rule_config = await db.simulator_rule_configs.find_one({"user_id": user_id}, {"_id": 0}) or {}
    try:
        recommendation = await generate_recommendation(
            trade=trade,
            current_price=current_price,
            options_chain=chain,
            goals=goals,
            rule_config=rule_config
        )
    except Exception as e:
        # Refund on failure
        await wallet_svc.credit_tokens(user_id=user_id, tokens=MANAGE_COST_CREDITS, source="refund", request_id=trade_id)
        raise HTTPException(status_code=500, detail=f"Recommendation engine error: {e}")

    # ── 6. Log to simulator_action_logs ──────────────────────────────────────
    now = datetime.utcnow()
    action_log_entry = {
        "user_id":        user_id,
        "trade_id":       trade_id,
        "symbol":         symbol,                          # ← top-level so Logs tab shows it
        "strategy_type":  trade.get("strategy_type"),      # ← top-level
        "action_type":    f"ai_manage:{recommendation['action']}",
        "trigger":        "manual_manage",
        "result":         "recommendation_generated",
        "recommendation": recommendation,
        "current_price":  current_price,
        "credits_charged": MANAGE_COST_CREDITS,
        "mode":           mode,
        "timestamp":      now,
        "trade_snapshot": {
            "dte_remaining":   trade.get("dte_remaining"),
            "short_strike":    trade.get("short_call_strike"),
            "unrealized_pnl":  trade.get("unrealized_pnl"),
        }
    }
    await db.simulator_action_logs.insert_one(action_log_entry)

    # Also write to recommendations collection for history
    await db.simulator_ai_recommendations.insert_one({
        **action_log_entry,
        "status": "pending_approval"
    })

    return {
        "recommendation": recommendation,
        "balance_after":  balance_after,
        "current_price":  current_price,
        "trade_id":       trade_id,
        "symbol":         symbol
    }


# ─── POST /simulator/manage/{trade_id}/apply ─────────────────────────────────
@simulator_router.post("/manage/{trade_id}/apply")
async def apply_trade_recommendation(
    trade_id: str,
    request: Request,
    user: dict = Depends(get_current_user)
):
    """
    Apply a previously generated recommendation to the actual trade.

    Body:
        {
            "recommendation": { ...the recommendation object returned by /manage... },
            "current_price": 185.50
        }

    Flow:
        1. Load trade, verify ownership
        2. Debit APPLY_COST_CREDITS
        3. Compute trade field updates
        4. Apply to MongoDB
        5. Log action
        6. Return updated trade

    Returns:
        { "trade": {...updated trade...}, "balance_after": int }
    """
    from ai_wallet.wallet_service import WalletService as AIWalletService
    from services.ai_trade_manager import apply_recommendation_to_trade
    APPLY_COST_CREDITS = 2

    body_data      = await request.json()
    user_id        = user["id"]
    recommendation = body_data.get("recommendation", {})
    current_price  = float(body_data.get("current_price", 0))

    if not recommendation:
        raise HTTPException(status_code=400, detail="recommendation is required")

    # ── Load trade ────────────────────────────────────────────────────────────
    trade = await db.simulator_trades.find_one({"id": trade_id, "user_id": user_id}, {"_id": 0})

    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    # ── Debit wallet (same service as manage endpoint) ────────────────────────
    import uuid as _uuid
    wallet_svc = AIWalletService(db)
    debit_result = await wallet_svc.deduct_tokens(
        user_id=user_id,
        tokens_required=APPLY_COST_CREDITS,
        action="trade_apply",
        request_id=str(_uuid.uuid4())
    )
    if not debit_result.allowed:
        wallet = await wallet_svc.get_or_create_wallet(user_id)
        current_bal = wallet.get("free_tokens_remaining", 0) + wallet.get("paid_tokens_remaining", 0)
        raise HTTPException(
            status_code=402,
            detail={
                "error": "insufficient_credits",
                "message": f"Need {APPLY_COST_CREDITS} credits to apply. Balance: {current_bal}",
                "balance": current_bal
            }
        )

    balance_after = debit_result.remaining_balance

    # ── Build and apply updates ────────────────────────────────────────────────
    field_updates = apply_recommendation_to_trade(trade, recommendation, current_price)

    await db.simulator_trades.update_one(
        {"id": trade_id},
        {"$set": field_updates}
    )

    # Log the apply action
    symbol = trade.get("symbol", "")
    await db.simulator_action_logs.insert_one({
        "user_id":        user_id,
        "trade_id":       trade_id,
        "symbol":         symbol,
        "strategy_type":  trade.get("strategy_type"),
        "action_type":    f"ai_apply:{recommendation['action']}",
        "trigger":        "user_approved",
        "result":         "trade_updated",
        "field_updates":  field_updates,
        "recommendation": recommendation,
        "credits_charged": APPLY_COST_CREDITS,
        "timestamp":      datetime.utcnow()
    })

    # Mark recommendation as applied
    await db.simulator_ai_recommendations.update_many(
        {"trade_id": trade_id, "status": "pending_approval"},
        {"$set": {"status": "applied", "applied_at": datetime.utcnow()}}
    )

    # Return the updated trade
    updated = await db.simulator_trades.find_one({"id": trade_id}, {"_id": 0})

    return {
        "trade":         updated,
        "balance_after": balance_after,
        "action_applied": recommendation["action"]
    }

