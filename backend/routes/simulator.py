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
from services.data_provider import fetch_live_stock_quote

simulator_router = APIRouter(tags=["Simulator"])

# Valid lifecycle statuses
CC_STATUSES = ["open", "expired", "assigned", "closed"]
PMCC_STATUSES = ["open", "rolled", "assigned", "closed"]
ALL_STATUSES = ["open", "rolled", "expired", "assigned", "closed"]
COMPLETED_STATUSES = ["expired", "assigned", "closed"]  # For analytics - ASSIGNED = CLOSED


# ==================== BLACK-SCHOLES CALCULATIONS ====================

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
    Calculate option Greeks
    S: Current stock price
    K: Strike price
    T: Time to expiration (in years)
    r: Risk-free rate (default 5%)
    sigma: Implied volatility
    
    Returns: dict with delta, gamma, theta, vega
    """
    if T <= 0 or sigma <= 0:
        # At expiry or invalid inputs
        delta = 1.0 if S > K else 0.0
        return {
            "delta": delta,
            "gamma": 0,
            "theta": 0,
            "vega": 0,
            "option_value": max(0, S - K)
        }
    
    d1, d2 = calculate_d1_d2(S, K, T, r, sigma)
    if d1 is None:
        return {"delta": 0, "gamma": 0, "theta": 0, "vega": 0, "option_value": 0}
    
    # Delta
    delta = norm_cdf(d1)
    
    # Gamma
    gamma = norm_pdf(d1) / (S * sigma * math.sqrt(T))
    
    # Theta (per day)
    theta = (-(S * norm_pdf(d1) * sigma) / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * norm_cdf(d2)) / 365
    
    # Vega (per 1% change in IV)
    vega = S * math.sqrt(T) * norm_pdf(d1) / 100
    
    # Option value
    option_value = calculate_call_price(S, K, T, r, sigma)
    
    return {
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta": round(theta, 4),
        "vega": round(vega, 4),
        "option_value": round(option_value, 2)
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
        dte = (expiry_dt - datetime.now()).days
    except:
        dte = 30  # Default
    
    # Create simulator trade document
    trade_doc = {
        "id": trade_id,
        "user_id": user["id"],
        "symbol": trade.symbol.upper(),
        "strategy_type": trade.strategy_type,
        "status": "active",  # active, closed, expired, assigned
        
        # Entry snapshot (immutable)
        "entry_date": entry_date,
        "entry_underlying_price": trade.underlying_price,
        
        # Short call details
        "short_call_strike": trade.short_call_strike,
        "short_call_expiry": trade.short_call_expiry,
        "short_call_premium": trade.short_call_premium,
        "short_call_delta": trade.short_call_delta,
        "short_call_iv": trade.short_call_iv,
        
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
    status: Optional[str] = Query(None, description="Filter by status: active, closed, expired, assigned"),
    symbol: Optional[str] = Query(None),
    strategy_type: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    skip: int = Query(0, ge=0),
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
    
    if trade.get("status") != "active":
        raise HTTPException(status_code=400, detail="Trade is not active")
    
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


@simulator_router.post("/update-prices")
async def update_simulator_prices(user: dict = Depends(get_current_user)):
    """
    Manually trigger LIVE price update for user's active trades.
    
    DATA RULE #2: Simulator uses LIVE intraday prices (regularMarketPrice)
    for accurate P&L tracking during market hours.
    """
    active_trades = await db.simulator_trades.find(
        {"user_id": user["id"], "status": "active"},
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
            dte_remaining = (expiry_dt - datetime.now()).days
            time_to_expiry = max(dte_remaining / 365, 0.001)  # In years
        except:
            dte_remaining = trade.get("dte_remaining", 0)
            time_to_expiry = max(dte_remaining / 365, 0.001)
        
        # Calculate days held
        try:
            entry_dt = datetime.strptime(trade["entry_date"], "%Y-%m-%d")
            days_held = (datetime.now() - entry_dt).days
        except:
            days_held = trade.get("days_held", 0)
        
        # Calculate current Greeks and option value
        iv = trade.get("short_call_iv") or 0.30  # Default 30% IV
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
            leaps_iv = trade.get("leaps_iv") or iv
            leaps_dte = trade.get("leaps_dte_remaining") or 365
            leaps_time_to_expiry = max(leaps_dte / 365, 0.001)
            
            leaps_greeks = calculate_greeks(
                S=current_price,
                K=trade.get("leaps_strike", current_price * 0.8),
                T=leaps_time_to_expiry,
                r=risk_free_rate,
                sigma=leaps_iv
            )
            
            leaps_value_change = (leaps_greeks["option_value"] - (trade.get("leaps_premium", 0))) * 100 * trade["contracts"]
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
            {"user_id": user["id"], "status": "active"},
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
    
    active_trades = [t for t in all_trades if t.get("status") == "active"]
    closed_trades = [t for t in all_trades if t.get("status") in ["closed", "expired", "assigned"]]
    
    # Calculate P&L
    total_realized = sum(t.get("realized_pnl", 0) or t.get("final_pnl", 0) for t in closed_trades)
    total_unrealized = sum(t.get("unrealized_pnl", 0) for t in active_trades)
    
    # Win rate
    winners = [t for t in closed_trades if (t.get("realized_pnl", 0) or t.get("final_pnl", 0)) > 0]
    win_rate = (len(winners) / len(closed_trades) * 100) if closed_trades else 0
    
    # Average ROI
    rois = [t.get("roi_percent", 0) for t in closed_trades if t.get("roi_percent") is not None]
    avg_roi = sum(rois) / len(rois) if rois else 0
    
    # By strategy
    by_strategy = {}
    for strategy in ["covered_call", "pmcc"]:
        strategy_trades = [t for t in all_trades if t.get("strategy_type") == strategy]
        strategy_closed = [t for t in strategy_trades if t.get("status") in ["closed", "expired", "assigned"]]
        strategy_active = [t for t in strategy_trades if t.get("status") == "active"]
        
        by_strategy[strategy] = {
            "total": len(strategy_trades),
            "active": len(strategy_active),
            "closed": len(strategy_closed),
            "realized_pnl": sum(t.get("realized_pnl", 0) or t.get("final_pnl", 0) for t in strategy_closed),
            "unrealized_pnl": sum(t.get("unrealized_pnl", 0) for t in strategy_active)
        }
    
    # By status
    by_status = {}
    for status in ["active", "closed", "expired", "assigned"]:
        status_trades = [t for t in all_trades if t.get("status") == status]
        by_status[status] = len(status_trades)
    
    return {
        "total_trades": len(all_trades),
        "active_trades": len(active_trades),
        "closed_trades": len(closed_trades),
        "total_realized_pnl": round(total_realized, 2),
        "total_unrealized_pnl": round(total_unrealized, 2),
        "total_capital_deployed": sum(t.get("capital_deployed", 0) for t in active_trades),
        "win_rate": round(win_rate, 1),
        "avg_roi": round(avg_roi, 2),
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
    """Get pre-built rule templates"""
    
    templates = [
        {
            "id": "profit_50",
            "name": "50% Profit Target",
            "description": "Close trade when 50% of max premium is captured",
            "rule_type": "profit_target",
            "conditions": [{"field": "premium_capture_pct", "operator": ">=", "value": 50}],
            "action": "close",
            "action_params": {"reason": "profit_target_50pct"},
            "priority": 10
        },
        {
            "id": "profit_75",
            "name": "75% Profit Target",
            "description": "Close trade when 75% of max premium is captured",
            "rule_type": "profit_target",
            "conditions": [{"field": "premium_capture_pct", "operator": ">=", "value": 75}],
            "action": "close",
            "action_params": {"reason": "profit_target_75pct"},
            "priority": 10
        },
        {
            "id": "stop_loss_100",
            "name": "100% Stop Loss",
            "description": "Close trade when loss equals initial premium received",
            "rule_type": "stop_loss",
            "conditions": [{"field": "premium_capture_pct", "operator": "<=", "value": -100}],
            "action": "close",
            "action_params": {"reason": "stop_loss_100pct"},
            "priority": 20
        },
        {
            "id": "stop_loss_200",
            "name": "200% Stop Loss",
            "description": "Close trade when loss is 2x initial premium",
            "rule_type": "stop_loss",
            "conditions": [{"field": "premium_capture_pct", "operator": "<=", "value": -200}],
            "action": "close",
            "action_params": {"reason": "stop_loss_200pct"},
            "priority": 20
        },
        {
            "id": "dte_7_close",
            "name": "Close at 7 DTE",
            "description": "Close trade when 7 days or less remain",
            "rule_type": "time_based",
            "conditions": [{"field": "dte_remaining", "operator": "<=", "value": 7}],
            "action": "close",
            "action_params": {"reason": "dte_close_7days"},
            "priority": 5
        },
        {
            "id": "dte_14_close",
            "name": "Close at 14 DTE",
            "description": "Close trade when 14 days or less remain",
            "rule_type": "time_based",
            "conditions": [{"field": "dte_remaining", "operator": "<=", "value": 14}],
            "action": "close",
            "action_params": {"reason": "dte_close_14days"},
            "priority": 5
        },
        {
            "id": "delta_high_alert",
            "name": "High Delta Alert",
            "description": "Alert when delta exceeds 0.70 (getting ITM)",
            "rule_type": "delta_target",
            "conditions": [{"field": "current_delta", "operator": ">=", "value": 0.70}],
            "action": "alert",
            "action_params": {"message": "Warning: Option delta above 0.70 - consider rolling"},
            "priority": 15
        },
        {
            "id": "combined_profit_dte",
            "name": "Take Profit or Close at DTE",
            "description": "Close at 50% profit OR when DTE reaches 21",
            "rule_type": "custom",
            "conditions": [
                {"field": "premium_capture_pct", "operator": ">=", "value": 50}
            ],
            "action": "close",
            "action_params": {"reason": "combined_exit"},
            "priority": 10
        },
        {
            "id": "theta_decay_target",
            "name": "Theta Decay Target",
            "description": "Alert when daily theta decay exceeds $5",
            "rule_type": "custom",
            "conditions": [{"field": "current_theta", "operator": "<=", "value": -5}],
            "action": "alert",
            "action_params": {"message": "High theta decay - good time to hold for premium capture"},
            "priority": 3
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
    
    rule = TradeRuleCreate(
        name=template["name"],
        description=template["description"],
        rule_type=template["rule_type"],
        conditions=template["conditions"],
        action=template["action"],
        action_params=template.get("action_params"),
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
        {"user_id": user["id"], "status": "active"},
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
    """Get PMCC-specific summary statistics"""
    
    pmcc_trades = await db.simulator_trades.find(
        {"user_id": user["id"], "strategy_type": "pmcc"},
        {"_id": 0}
    ).to_list(10000)
    
    if not pmcc_trades:
        return {
            "total_pmcc_trades": 0,
            "active_trades": 0,
            "completed_trades": 0,
            "total_leaps_cost": 0,
            "total_premium_collected": 0,
            "premium_to_cost_ratio": 0,
            "avg_rolls_per_position": 0,
            "realized_pnl": 0,
            "unrealized_pnl": 0
        }
    
    active = [t for t in pmcc_trades if t.get("status") == "active"]
    completed = [t for t in pmcc_trades if t.get("status") in ["closed", "expired", "assigned"]]
    
    total_leaps_cost = sum((t.get("leaps_premium", 0) * 100 * t.get("contracts", 1)) for t in pmcc_trades)
    total_premium = sum(t.get("premium_received", 0) for t in pmcc_trades)
    
    premium_ratio = (total_premium / total_leaps_cost * 100) if total_leaps_cost > 0 else 0
    
    realized_pnl = sum(t.get("realized_pnl", 0) or t.get("final_pnl", 0) for t in completed)
    unrealized_pnl = sum(t.get("unrealized_pnl", 0) for t in active)
    
    return {
        "total_pmcc_trades": len(pmcc_trades),
        "active_trades": len(active),
        "completed_trades": len(completed),
        "total_leaps_cost": round(total_leaps_cost, 2),
        "total_premium_collected": round(total_premium, 2),
        "premium_to_cost_ratio": round(premium_ratio, 1),
        "avg_rolls_per_position": 0,  # Would need roll tracking
        "realized_pnl": round(realized_pnl, 2),
        "unrealized_pnl": round(unrealized_pnl, 2)
    }


# ==================== ANALYTICS ENDPOINTS ====================

@simulator_router.get("/analytics/performance")
async def get_performance_analytics(
    time_period: str = Query("all", description="all, 30d, 90d, 1y"),
    strategy_type: Optional[str] = Query(None),
    user: dict = Depends(get_current_user)
):
    """Get detailed performance analytics for closed trades"""
    
    query = {"user_id": user["id"], "status": {"$in": ["closed", "expired", "assigned"]}}
    
    if strategy_type:
        query["strategy_type"] = strategy_type
    
    # Time filter
    if time_period != "all":
        days_map = {"30d": 30, "90d": 90, "1y": 365}
        days = days_map.get(time_period, 365)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        query["close_date"] = {"$gte": cutoff[:10]}
    
    trades = await db.simulator_trades.find(query, {"_id": 0}).to_list(10000)
    
    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0,
            "avg_roi": 0,
            "total_pnl": 0,
            "avg_pnl": 0,
            "max_win": 0,
            "max_loss": 0,
            "avg_holding_days": 0,
            "by_close_reason": {},
            "by_symbol": {},
            "monthly_breakdown": [],
            "scan_parameter_analysis": []
        }
    
    # Basic stats
    pnls = [t.get("realized_pnl", 0) or t.get("final_pnl", 0) for t in trades]
    rois = [t.get("roi_percent", 0) for t in trades if t.get("roi_percent") is not None]
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p < 0]
    
    total_pnl = sum(pnls)
    avg_pnl = total_pnl / len(trades) if trades else 0
    win_rate = (len(winners) / len(trades) * 100) if trades else 0
    avg_roi = sum(rois) / len(rois) if rois else 0
    
    # Holding period
    holding_days = []
    for t in trades:
        if t.get("entry_date") and t.get("close_date"):
            try:
                entry = datetime.strptime(t["entry_date"], "%Y-%m-%d")
                close = datetime.strptime(t["close_date"], "%Y-%m-%d")
                holding_days.append((close - entry).days)
            except:
                pass
    avg_holding = sum(holding_days) / len(holding_days) if holding_days else 0
    
    # By close reason
    by_reason = {}
    for t in trades:
        reason = t.get("close_reason", "unknown")
        if reason not in by_reason:
            by_reason[reason] = {"count": 0, "total_pnl": 0, "avg_pnl": 0}
        by_reason[reason]["count"] += 1
        by_reason[reason]["total_pnl"] += t.get("realized_pnl", 0) or t.get("final_pnl", 0)
    
    for reason in by_reason:
        if by_reason[reason]["count"] > 0:
            by_reason[reason]["avg_pnl"] = round(by_reason[reason]["total_pnl"] / by_reason[reason]["count"], 2)
        by_reason[reason]["total_pnl"] = round(by_reason[reason]["total_pnl"], 2)
    
    # By symbol
    by_symbol = {}
    for t in trades:
        symbol = t.get("symbol", "UNKNOWN")
        if symbol not in by_symbol:
            by_symbol[symbol] = {"trades": 0, "wins": 0, "total_pnl": 0}
        by_symbol[symbol]["trades"] += 1
        pnl = t.get("realized_pnl", 0) or t.get("final_pnl", 0)
        by_symbol[symbol]["total_pnl"] += pnl
        if pnl > 0:
            by_symbol[symbol]["wins"] += 1
    
    for symbol in by_symbol:
        by_symbol[symbol]["win_rate"] = round(by_symbol[symbol]["wins"] / by_symbol[symbol]["trades"] * 100, 1)
        by_symbol[symbol]["total_pnl"] = round(by_symbol[symbol]["total_pnl"], 2)
    
    # Monthly breakdown
    monthly = {}
    for t in trades:
        if t.get("close_date"):
            month = t["close_date"][:7]  # YYYY-MM
            if month not in monthly:
                monthly[month] = {"trades": 0, "pnl": 0, "wins": 0}
            monthly[month]["trades"] += 1
            pnl = t.get("realized_pnl", 0) or t.get("final_pnl", 0)
            monthly[month]["pnl"] += pnl
            if pnl > 0:
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
    for t in trades:
        params = t.get("scan_parameters", {})
        if not params:
            continue
        
        # Group by key parameters
        dte_bucket = f"DTE_{(params.get('max_dte', 45) // 15) * 15}"
        delta_bucket = f"Delta_{int(params.get('max_delta', 0.45) * 100)}"
        roi_bucket = f"ROI_{int(params.get('min_roi', 0.5))}"
        
        for bucket_type, bucket in [("dte", dte_bucket), ("delta", delta_bucket), ("roi", roi_bucket)]:
            key = f"{bucket_type}:{bucket}"
            if key not in param_stats:
                param_stats[key] = {"param": bucket, "type": bucket_type, "trades": 0, "total_pnl": 0, "wins": 0}
            param_stats[key]["trades"] += 1
            pnl = t.get("realized_pnl", 0) or t.get("final_pnl", 0)
            param_stats[key]["total_pnl"] += pnl
            if pnl > 0:
                param_stats[key]["wins"] += 1
    
    param_analysis = []
    for key, stats in param_stats.items():
        if stats["trades"] >= 3:  # Minimum sample size
            param_analysis.append({
                "parameter": stats["param"],
                "type": stats["type"],
                "trades": stats["trades"],
                "avg_pnl": round(stats["total_pnl"] / stats["trades"], 2),
                "win_rate": round(stats["wins"] / stats["trades"] * 100, 1)
            })
    
    return {
        "total_trades": len(trades),
        "win_rate": round(win_rate, 1),
        "avg_roi": round(avg_roi, 2),
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(avg_pnl, 2),
        "max_win": round(max(pnls), 2) if pnls else 0,
        "max_loss": round(min(pnls), 2) if pnls else 0,
        "avg_holding_days": round(avg_holding, 1),
        "profit_factor": round(abs(sum(winners)) / abs(sum(losers)), 2) if losers and sum(losers) != 0 else 0,
        "by_close_reason": by_reason,
        "by_symbol": dict(sorted(by_symbol.items(), key=lambda x: x[1]["total_pnl"], reverse=True)[:10]),
        "monthly_breakdown": monthly_list,
        "scan_parameter_analysis": sorted(param_analysis, key=lambda x: x["avg_pnl"], reverse=True)
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
