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
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
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


async def execute_rule_action(trade: dict, rule: dict, db_instance) -> dict:
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
        
        if trade["strategy_type"] == "covered_call":
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
        
        await db_instance.simulator_trades.update_one(
            {"id": trade["id"]},
            {"$set": update_doc}
        )
        
        # Log the action
        await db_instance.simulator_trades.update_one(
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
        # Just log an alert (would send notification in production)
        alert_message = action_params.get("message", f"Rule '{rule.get('name')}' triggered")
        
        await db_instance.simulator_trades.update_one(
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
    await db_instance.simulator_action_logs.insert_one(log_entry)
    
    return result


async def evaluate_and_execute_rules(trade: dict, rules: list, db_instance) -> list:
    """
    Evaluate all rules against a trade and execute matching ones
    Rules are sorted by priority (higher = more important)
    """
    results = []
    
    # Sort rules by priority (descending)
    sorted_rules = sorted(rules, key=lambda r: r.get("priority", 0), reverse=True)
    
    for rule in sorted_rules:
        if not rule.get("is_enabled", True):
            continue
            
        if evaluate_rule(trade, rule):
            result = await execute_rule_action(trade, rule, db_instance)
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
    if trade.strategy_type == "covered_call":
        # Covered Call: Long 100 shares + Short call
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
        raise HTTPException(status_code=400, detail="Invalid strategy type. Must be 'covered_call' or 'pmcc'")
    
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

    # ========== ENRICHMENT: IV Rank + Analyst Data (LAST STEP) ==========
    for trade in trades:
        sym = trade.get("symbol", "")
        if sym:
            enrich_row(
                sym, trade,
                stock_price=trade.get("current_underlying_price") or trade.get("entry_underlying_price"),
                expiry=trade.get("short_call_expiry"),
                iv=trade.get("short_call_iv")
            )
            strip_enrichment_debug(trade, include_debug=debug_enrichment)

    return {
        "trades": trades,
        "total": total,
        "limit": limit,
        "skip": skip
    }


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
    
    if trade["strategy_type"] == "covered_call":
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
            # Use LIVE stock quote (regularMarketPrice)
            quote = await fetch_live_stock_quote(symbol)
            if quote and quote.get("price"):
                price_cache[symbol] = quote["price"]
        except Exception as e:
            logging.warning(f"Could not fetch live price for {symbol}: {e}")
    
    now = datetime.now(timezone.utc)
    risk_free_rate = 0.05  # 5% risk-free rate
    
    updated_count = 0
    
    for trade in active_trades:
        symbol = trade["symbol"]
        if symbol not in price_cache:
            continue
        
        current_price = price_cache[symbol]
        
        # Calculate DTE remaining
        try:
            expiry_dt = datetime.strptime(trade["short_call_expiry"], "%Y-%m-%d")
            dte_remaining = max((expiry_dt - datetime.now()).days, 0)
            time_to_expiry = max(dte_remaining / 365, 0.001)  # In years
        except:
            dte_remaining = max(trade.get("dte_remaining", 0), 0)
            time_to_expiry = max(dte_remaining / 365, 0.001)
        
        # Calculate days held
        try:
            entry_dt = datetime.strptime(trade["entry_date"], "%Y-%m-%d")
            days_held = (datetime.now() - entry_dt).days
        except:
            days_held = trade.get("days_held", 0)
        
        # Calculate current Greeks and option value
        iv_raw = trade.get("short_call_iv")
        try:
            iv = normalize_iv_fields(iv_raw)["iv"] if iv_raw else 0.30
        except Exception:
            iv = 0.30
        if not iv or iv <= 0:
            iv = 0.30  # Default 30% IV
        greeks = calculate_greeks(
            S=current_price,
            K=trade["short_call_strike"],
            T=time_to_expiry,
            r=risk_free_rate,
            sigma=iv
        )
        
        # Calculate unrealized P&L
        entry_premium = trade.get("short_call_premium", 0)
        current_option_value = greeks["option_value"]
        
        if trade["strategy_type"] == "covered_call":
            stock_pnl = (current_price - trade["entry_underlying_price"]) * 100 * trade["contracts"]
            option_pnl = (entry_premium - current_option_value) * 100 * trade["contracts"]
            unrealized_pnl = stock_pnl + option_pnl
        else:  # PMCC
            leaps_strike_val = trade.get("leaps_strike")
            leaps_premium_stored = trade.get("leaps_premium")

            # Guard: validate LEAPS fields before pricing to prevent insane Unrealized P&L
            if leaps_strike_val and leaps_strike_val > 0 and leaps_premium_stored and leaps_premium_stored > 0:
                leaps_iv = trade.get("leaps_iv") or iv
                leaps_dte = max(trade.get("leaps_dte_remaining") or 365, 0)
                leaps_time_to_expiry = max(leaps_dte / 365, 0.001)

                leaps_greeks = calculate_greeks(
                    S=current_price,
                    K=leaps_strike_val,
                    T=leaps_time_to_expiry,
                    r=risk_free_rate,
                    sigma=leaps_iv
                )

                leaps_value_change = (leaps_greeks["option_value"] - leaps_premium_stored) * 100 * trade["contracts"]
            else:
                leaps_value_change = 0

            short_call_pnl = (entry_premium - current_option_value) * 100 * trade["contracts"]
            unrealized_pnl = leaps_value_change + short_call_pnl
        
        # Calculate premium capture percentage
        if entry_premium > 0 and current_option_value >= 0:
            premium_capture_pct = ((entry_premium - current_option_value) / entry_premium) * 100
        else:
            premium_capture_pct = 0
        
        update_doc = {
            "current_underlying_price": current_price,
            "current_option_value": current_option_value,
            "unrealized_pnl": round(unrealized_pnl, 2),
            "days_held": days_held,
            "dte_remaining": dte_remaining,
            "premium_capture_pct": round(premium_capture_pct, 1),
            "last_updated": now.isoformat(),
            "updated_at": now.isoformat(),
            "current_delta": greeks["delta"],
            "current_gamma": greeks["gamma"],
            "current_theta": greeks["theta"],
            "current_vega": greeks["vega"],
        }
        
        # Auto-expire or assign when DTE reaches 0
        if dte_remaining == 0 and trade.get("status") in ["open", "rolled"]:
            is_itm = current_price >= trade["short_call_strike"]
            update_doc["status"] = "assigned" if is_itm else "expired"
            update_doc["final_pnl"] = round(unrealized_pnl, 2)
            update_doc["realized_pnl"] = round(unrealized_pnl, 2)
            update_doc["close_date"] = now.strftime("%Y-%m-%d")

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
    
    # Win rate
    winners = [t for t in closed_trades if (t.get("realized_pnl", 0) or t.get("final_pnl", 0)) > 0]
    win_rate = (len(winners) / len(closed_trades) * 100) if closed_trades else 0
    
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
        "total_capital_deployed": round(total_capital_deployed, 2),
        "win_rate": round(win_rate, 1),
        "avg_roi": round(avg_roi, 2),
        "avg_return_pct": round(avg_return_pct, 2),
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


# ==================== RULES ENDPOINTS ====================

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
    
    query = {"user_id": user["id"]}
    if trade_id:
        query["trade_id"] = trade_id
    if rule_id:
        query["rule_id"] = rule_id
    
    logs = await db.simulator_action_logs.find(
        query,
        {"_id": 0}
    ).sort("timestamp", -1).limit(limit).to_list(limit)
    
    return {"logs": logs, "count": len(logs)}


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
        if status == "assigned" and t.get("strategy_type") == "covered_call":
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


# ==================== ANALYZER ENDPOINT (3-Row Structure) ====================

@simulator_router.get("/analyzer")
async def get_analyzer_metrics(
    strategy: Optional[str] = Query(None, description="Filter by strategy: covered_call, pmcc"),
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    time_period: str = Query("all", description="all, 30d, 90d, 1y"),
    user: dict = Depends(get_current_user)
):
    """
    Analyzer Page - Fixed 3-Row Structure with Scope-Aware Metrics
    
    CORE DESIGN PRINCIPLE:
    The Analyzer always renders three rows in the same order:
    - Row 1: Outcome (What did I make?)
    - Row 2: Risk & Capital (How much pain did I take?)
    - Row 3: Strategy Health (Is the logic working?)
    
    SCOPE MODEL:
    - Portfolio Scope: All symbols + all strategies (default)
    - Strategy Scope: All symbols + single strategy (CC or PMCC)
    - Symbol Scope: Single symbol + single strategy
    """
    
    # Build query based on scope
    query = {"user_id": user["id"]}
    
    if strategy:
        query["strategy_type"] = strategy
    if symbol:
        query["symbol"] = symbol.upper()
    
    all_trades = await db.simulator_trades.find(query, {"_id": 0}).to_list(10000)
    
    if not all_trades:
        return {
            "scope": {
                "type": "portfolio" if not strategy and not symbol else "strategy" if not symbol else "symbol",
                "strategy": strategy,
                "symbol": symbol
            },
            "row1_outcome": {
                "total_pnl": 0,
                "win_rate": 0,
                "roi": 0,
                "avg_win": 0,
                "avg_loss": 0,
                "expectancy": 0,
                "max_drawdown": 0,
                "time_weighted_return": 0
            },
            "row2_risk_capital": {
                "peak_capital_at_risk": 0,
                "avg_capital_per_trade": 0,
                "worst_case_loss": 0,
                "assignment_exposure_cc": 0,
                "assignment_exposure_pmcc": 0
            },
            "row3_strategy_health": {
                "strategies": [],
                "strategy_distribution": [],
                "pnl_by_strategy": []
            }
        }
    
    # Apply time filter
    if time_period != "all":
        days_map = {"30d": 30, "90d": 90, "1y": 365}
        days = days_map.get(time_period, 365)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        all_trades = [t for t in all_trades if t.get("entry_date", "") >= cutoff]
    
    if not all_trades:
        return {"scope": {"type": "portfolio"}, "row1_outcome": {}, "row2_risk_capital": {}, "row3_strategy_health": {}}
    
    # Separate open vs completed trades
    open_trades = [t for t in all_trades if t.get("status") in ["open", "rolled", "active"]]
    completed_trades = [t for t in all_trades if t.get("status") in ["closed", "expired", "assigned"]]
    
    # ==================== ROW 1: OUTCOME ====================
    # Question: What did I make?
    
    completed_pnls = [(t.get("realized_pnl") or t.get("final_pnl") or 0) for t in completed_trades]
    total_pnl = sum(completed_pnls)
    
    # Win rate calculation
    winners = []
    losers = []
    for t in completed_trades:
        pnl = (t.get("realized_pnl") or t.get("final_pnl") or 0)
        if pnl > 0 or t.get("status") in ["assigned", "expired"]:
            winners.append(pnl)
        elif pnl < 0:
            losers.append(pnl)
    
    win_rate = (len(winners) / len(completed_trades) * 100) if completed_trades else 0
    avg_win = (sum(w for w in winners if w > 0) / len([w for w in winners if w > 0])) if [w for w in winners if w > 0] else 0
    avg_loss = (sum(losers) / len(losers)) if losers else 0
    
    # ROI calculation
    total_capital = sum(t.get("capital_deployed", 0) for t in completed_trades)
    roi = (total_pnl / total_capital * 100) if total_capital > 0 else 0
    
    # NEW: Expectancy = (Win% × Avg Win) – (Loss% × Avg Loss)
    win_pct = len(winners) / len(completed_trades) if completed_trades else 0
    loss_pct = len(losers) / len(completed_trades) if completed_trades else 0
    expectancy = (win_pct * abs(avg_win)) - (loss_pct * abs(avg_loss)) if completed_trades else 0
    
    # NEW: Maximum Drawdown (peak-to-trough)
    cumulative_pnl = []
    running_total = 0
    for t in sorted(completed_trades, key=lambda x: x.get("close_date", "")):
        running_total += (t.get("realized_pnl") or t.get("final_pnl") or 0)
        cumulative_pnl.append(running_total)
    
    max_drawdown = 0
    peak = 0
    for pnl in cumulative_pnl:
        if pnl > peak:
            peak = pnl
        drawdown = peak - pnl
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    
    # NEW: Time-Weighted Return (simple approximation)
    total_holding_days = 0
    weighted_returns = 0
    for t in completed_trades:
        if t.get("entry_date") and t.get("close_date"):
            try:
                entry = datetime.strptime(t["entry_date"], "%Y-%m-%d")
                close = datetime.strptime(t["close_date"], "%Y-%m-%d")
                days = max((close - entry).days, 1)
                pnl = (t.get("realized_pnl") or t.get("final_pnl") or 0)
                capital = t.get("capital_deployed", 1)
                if capital > 0:
                    weighted_returns += (pnl / capital) * days
                    total_holding_days += days
            except:
                pass
    
    twr = (weighted_returns / total_holding_days * 365 * 100) if total_holding_days > 0 else 0  # Annualized
    
    row1_outcome = {
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(win_rate, 1),
        "roi": round(roi, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "expectancy": round(expectancy, 2),
        "expectancy_tooltip": "Expected profit per trade if conditions repeat",
        "max_drawdown": round(max_drawdown, 2),
        "time_weighted_return": round(twr, 2),
        "twr_tooltip": "Annualized return adjusted for time in market",
        "total_trades": len(all_trades),
        "open_trades": len(open_trades),
        "completed_trades": len(completed_trades)
    }
    
    # ==================== ROW 2: RISK & CAPITAL ====================
    # Question: How much pain did I take to earn it?
    
    # Peak Capital at Risk (maximum simultaneous capital deployed)
    # For simplicity, we'll use max capital from any single trade or sum of open positions
    max_single_capital = max((t.get("capital_deployed", 0) for t in all_trades), default=0)
    total_open_capital = sum(t.get("capital_deployed", 0) for t in open_trades)
    peak_capital = max(max_single_capital, total_open_capital)
    
    # Average Capital per Trade
    avg_capital = sum(t.get("capital_deployed", 0) for t in all_trades) / len(all_trades) if all_trades else 0
    
    # Worst-Case Loss (Theoretical) - Strategy specific
    worst_case_cc = 0
    worst_case_pmcc = 0
    
    for t in open_trades:
        if t.get("strategy_type") == "covered_call":
            # CC worst case: Stock to zero minus premium received
            stock_value = t.get("entry_underlying_price", 0) * t.get("shares", 100)
            premium = t.get("premium_received", 0)
            worst_case_cc += stock_value - premium
        elif t.get("strategy_type") == "pmcc":
            # PMCC worst case: Long LEAPS premium minus short call premium
            leaps_cost = t.get("leaps_premium", 0) * 100 * t.get("contracts", 1)
            short_premium = t.get("premium_received", 0)
            worst_case_pmcc += leaps_cost - short_premium
    
    # Use the appropriate worst case based on scope
    if strategy == "covered_call":
        worst_case_loss = worst_case_cc
    elif strategy == "pmcc":
        worst_case_loss = worst_case_pmcc
    else:
        worst_case_loss = worst_case_cc + worst_case_pmcc
    
    # Assignment Exposure % (separate for CC and PMCC)
    cc_trades = [t for t in open_trades if t.get("strategy_type") == "covered_call"]
    pmcc_trades = [t for t in open_trades if t.get("strategy_type") == "pmcc"]
    
    # Calculate assignment risk based on delta
    cc_at_risk = len([t for t in cc_trades if t.get("current_delta", 0) >= 0.50])
    pmcc_at_risk = len([t for t in pmcc_trades if t.get("current_delta", 0) >= 0.50])
    
    assignment_exposure_cc = (cc_at_risk / len(cc_trades) * 100) if cc_trades else 0
    assignment_exposure_pmcc = (pmcc_at_risk / len(pmcc_trades) * 100) if pmcc_trades else 0
    
    row2_risk_capital = {
        "peak_capital_at_risk": round(peak_capital, 2),
        "avg_capital_per_trade": round(avg_capital, 2),
        "worst_case_loss": round(worst_case_loss, 2),
        "worst_case_loss_tooltip": "Theoretical max loss if stock goes to zero (CC) or LEAPS expires worthless (PMCC)",
        "assignment_exposure_cc": round(assignment_exposure_cc, 1),
        "assignment_exposure_pmcc": round(assignment_exposure_pmcc, 1),
        "cc_positions_at_risk": cc_at_risk,
        "pmcc_positions_at_risk": pmcc_at_risk,
        "total_open_positions": len(open_trades)
    }
    
    # ==================== ROW 3: STRATEGY HEALTH ====================
    # Question: Is the logic actually working?
    
    strategies_health = []
    for strat in ["covered_call", "pmcc"]:
        strat_trades = [t for t in all_trades if t.get("strategy_type") == strat]
        strat_completed = [t for t in strat_trades if t.get("status") in ["closed", "expired", "assigned"]]
        strat_open = [t for t in strat_trades if t.get("status") in ["open", "rolled", "active"]]
        
        if not strat_trades:
            continue
        
        # Win Rate by Strategy
        strat_winners = [t for t in strat_completed if (t.get("realized_pnl") or t.get("final_pnl") or 0) > 0 or t.get("status") in ["assigned", "expired"]]
        strat_win_rate = (len(strat_winners) / len(strat_completed) * 100) if strat_completed else 0
        
        # Average Hold Time
        hold_times = []
        for t in strat_completed:
            if t.get("entry_date") and t.get("close_date"):
                try:
                    entry = datetime.strptime(t["entry_date"], "%Y-%m-%d")
                    close = datetime.strptime(t["close_date"], "%Y-%m-%d")
                    hold_times.append((close - entry).days)
                except:
                    pass
        avg_hold = sum(hold_times) / len(hold_times) if hold_times else 0
        
        # Profit Factor = Gross Winning P/L / Gross Losing P/L
        gross_wins = sum((t.get("realized_pnl") or t.get("final_pnl") or 0) for t in strat_completed if (t.get("realized_pnl") or t.get("final_pnl") or 0) > 0)
        gross_losses = abs(sum((t.get("realized_pnl") or t.get("final_pnl") or 0) for t in strat_completed if (t.get("realized_pnl") or t.get("final_pnl") or 0) < 0))
        profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else (99.99 if gross_wins > 0 else 0)
        
        # Total P/L for strategy
        strat_pnl = sum((t.get("realized_pnl") or t.get("final_pnl") or 0) for t in strat_completed)
        strat_unrealized = sum((t.get("unrealized_pnl") or 0) for t in strat_open)
        
        strategies_health.append({
            "strategy": strat,
            "strategy_label": "Covered Call" if strat == "covered_call" else "PMCC",
            "total_trades": len(strat_trades),
            "open_trades": len(strat_open),
            "completed_trades": len(strat_completed),
            "win_rate": round(strat_win_rate, 1),
            "avg_hold_days": round(avg_hold, 1),
            "profit_factor": round(profit_factor, 2),
            "profit_factor_status": "good" if profit_factor >= 1.5 else "neutral" if profit_factor >= 1 else "caution",
            "realized_pnl": round(strat_pnl, 2),
            "unrealized_pnl": round(strat_unrealized, 2)
        })
    
    # Strategy Distribution for charts
    strategy_distribution = [
        {"name": s["strategy_label"], "value": s["total_trades"]}
        for s in strategies_health
    ]
    
    pnl_by_strategy = [
        {"name": s["strategy_label"], "realized": s["realized_pnl"], "unrealized": s["unrealized_pnl"]}
        for s in strategies_health
    ]
    
    row3_strategy_health = {
        "strategies": strategies_health,
        "strategy_distribution": strategy_distribution,
        "pnl_by_strategy": pnl_by_strategy
    }
    
    # Determine scope type
    scope_type = "portfolio"
    if symbol:
        scope_type = "symbol"
    elif strategy:
        scope_type = "strategy"
    
    return {
        "scope": {
            "type": scope_type,
            "strategy": strategy,
            "symbol": symbol,
            "time_period": time_period
        },
        "row1_outcome": row1_outcome,
        "row2_risk_capital": row2_risk_capital,
        "row3_strategy_health": row3_strategy_health
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
    from services.wallet_service import get_balance
    balance = await get_balance(db, user["id"])
    return {"balance_credits": balance}


# ─── POST /simulator/manage/{trade_id} ───────────────────────────────────────
@simulator_router.post("/manage/{trade_id}")
async def manage_trade(
    trade_id: str,
    body: dict,
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
    from services.wallet_service import debit_wallet, get_balance, MANAGE_COST_CREDITS
    from services.ai_trade_manager import generate_recommendation

    user_id = user["id"]
    mode    = body.get("mode", "recommend_only")
    goals   = body.get("goals", {})

    # ── 1. Load trade ────────────────────────────────────────────────────────
    try:
        from bson import ObjectId
        trade = await db_instance.simulator_trades.find_one({
            "_id": ObjectId(trade_id),
            "user_id": user_id
        })
    except Exception:
        trade = None

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
    debit_result = await debit_wallet(
        db, user_id,
        amount=MANAGE_COST_CREDITS,
        reason=f"AI manage: {symbol} trade",
        ref_id=trade_id
    )
    if not debit_result["success"]:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "insufficient_credits",
                "message": f"You need {MANAGE_COST_CREDITS} credits to run AI management. "
                           f"Current balance: {debit_result['balance']}.",
                "balance": debit_result["balance"]
            }
        )

    balance_after = debit_result["balance_after"]

    # ── 5. Generate recommendation ───────────────────────────────────────────
    try:
        recommendation = await generate_recommendation(
            trade=trade,
            current_price=current_price,
            options_chain=chain,
            goals=goals
        )
    except Exception as e:
        # Refund on failure
        from services.wallet_service import credit_wallet
        await credit_wallet(db, user_id, MANAGE_COST_CREDITS, reason="Refund: manage failed", ref_id=trade_id)
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
    await db_instance.simulator_action_logs.insert_one(action_log_entry)

    # Also write to recommendations collection for history
    await db_instance.simulator_ai_recommendations.insert_one({
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
    body: dict,
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
    from services.wallet_service import debit_wallet, APPLY_COST_CREDITS
    from services.ai_trade_manager import apply_recommendation_to_trade

    user_id        = user["id"]
    recommendation = body.get("recommendation", {})
    current_price  = float(body.get("current_price", 0))

    if not recommendation:
        raise HTTPException(status_code=400, detail="recommendation is required")

    # ── Load trade ────────────────────────────────────────────────────────────
    try:
        from bson import ObjectId
        trade = await db_instance.simulator_trades.find_one({
            "_id": ObjectId(trade_id),
            "user_id": user_id
        })
    except Exception:
        trade = None

    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    # ── Debit wallet ──────────────────────────────────────────────────────────
    debit_result = await debit_wallet(
        db, user_id,
        amount=APPLY_COST_CREDITS,
        reason=f"AI apply: {trade.get('symbol')} {recommendation.get('action')}",
        ref_id=trade_id
    )
    if not debit_result["success"]:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "insufficient_credits",
                "message": f"Need {APPLY_COST_CREDITS} credits to apply. Balance: {debit_result['balance']}",
                "balance": debit_result["balance"]
            }
        )

    # ── Build and apply updates ────────────────────────────────────────────────
    field_updates = apply_recommendation_to_trade(trade, recommendation, current_price)

    await db_instance.simulator_trades.update_one(
        {"_id": trade["_id"]},
        {"$set": field_updates}
    )

    # Log the apply action
    symbol = trade.get("symbol", "")
    await db_instance.simulator_action_logs.insert_one({
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
    await db_instance.simulator_ai_recommendations.update_many(
        {"trade_id": trade_id, "status": "pending_approval"},
        {"$set": {"status": "applied", "applied_at": datetime.utcnow()}}
    )

    # Return the updated trade
    updated = await db_instance.simulator_trades.find_one({"_id": trade["_id"]})
    updated["id"] = str(updated.pop("_id"))

    return {
        "trade":        updated,
        "balance_after": debit_result["balance_after"],
        "action_applied": recommendation["action"]
    }

