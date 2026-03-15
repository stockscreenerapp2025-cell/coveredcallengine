"""
Lot-based trade lifecycle engine for Covered Calls (CC / Wheel / CSP) and PMCC strategies.

Core Rules:
  1. Every new stock acquisition creates a new ShareLot.
  2. Every new lot starts as a separate TradeCycle.
  3. Short calls are matched FIFO to uncovered open lots (oldest first).
  4. If calls cover shares across multiple cycles, those cycles are marked jointly_managed.
  5. Only merge cycles visually when ALL lots are intentionally covered together.
  6. Put assignment creates a new ShareLot with effective_entry = strike - put_premium_per_share.
  7. Call expiry keeps cycle OPEN; shares become uncovered again.
  8. Call assignment closes only the linked share quantity (not all shares of that symbol).
  9. A symbol can have multiple simultaneous open cycles.
"""

from __future__ import annotations

import uuid
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class ShareLot:
    lot_id: str
    symbol: str
    open_date: str                  # YYYY-MM-DD
    shares_open: int                # total shares acquired
    shares_remaining: int           # currently uncovered / available
    entry_price: float
    effective_entry: float          # after put premium deducted
    entry_type: str                 # 'BUY' or 'PUT_ASSIGNMENT'
    source_trade_ids: list = field(default_factory=list)
    linked_cycle_id: str = ""


@dataclass
class OptionPosition:
    option_id: str
    symbol: str
    opt_type: str                   # 'CALL' or 'PUT'
    side: str                       # 'SELL' (we only track sold options here)
    strike: float
    expiry: str
    contracts: int
    open_premium: float             # per share
    open_date: str
    close_date: Optional[str] = None
    close_premium: Optional[float] = None
    status: str = "OPEN"            # 'OPEN','EXPIRED','BOUGHT_BACK','ASSIGNED'
    linked_cycle_ids: list = field(default_factory=list)
    source_trade_ids: list = field(default_factory=list)


@dataclass
class TradeCycle:
    cycle_id: str
    symbol: str
    strategy: str                   # 'CC', 'WHEEL', 'CSP'
    status: str                     # see spec
    entry_mode: str                 # 'STOCK_ENTRY' or 'PUT_ENTRY'
    opened_date: str
    closed_date: Optional[str] = None
    jointly_managed_with: list = field(default_factory=list)

    total_shares_entered: int = 0
    shares_current: int = 0
    shares_covered_by_calls: int = 0
    uncovered_shares: int = 0

    lots: list = field(default_factory=list)        # lot_ids
    short_calls: list = field(default_factory=list)  # option_ids
    short_puts: list = field(default_factory=list)   # option_ids

    total_stock_cost: float = 0.0
    total_premium_received: float = 0.0
    total_premium_paid: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0

    avg_cost: float = 0.0
    effective_avg_cost: float = 0.0
    number_of_rolls: int = 0
    number_of_assignments: int = 0


@dataclass
class LongCallLot:
    lot_id: str
    symbol: str
    strike: float
    expiry: str
    contracts_open: int
    contracts_remaining: int
    premium_paid: float             # per share
    total_cost: float               # contracts × 100 × premium_paid
    open_date: str
    close_date: Optional[str] = None
    delta_at_open: Optional[float] = None
    status: str = "OPEN"            # 'OPEN','CLOSED','EXPIRED','ROLLED'
    linked_cycle_id: str = ""
    source_trade_ids: list = field(default_factory=list)


@dataclass
class PMCCCycle:
    cycle_id: str
    symbol: str
    strategy: str = "PMCC"
    status: str = "Open - LEAPS Only"
    opened_date: str = ""
    closed_date: Optional[str] = None

    long_call_lots: list = field(default_factory=list)   # LongCallLot IDs
    short_calls: list = field(default_factory=list)       # option_ids
    active_long_lot_id: Optional[str] = None
    active_short_call_id: Optional[str] = None

    total_debit_paid: float = 0.0
    total_short_premium_received: float = 0.0
    total_short_close_cost: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    net_capital_in_use: float = 0.0
    number_of_rolls: int = 0


# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------
EV_BUY_STOCK = "BUY_STOCK"
EV_SELL_STOCK = "SELL_STOCK"
EV_SELL_CALL_OPEN = "SELL_CALL_OPEN"
EV_BUY_CALL_CLOSE = "BUY_CALL_CLOSE"
EV_CALL_EXPIRE = "CALL_EXPIRE"
EV_CALL_ASSIGNMENT = "CALL_ASSIGNMENT"
EV_SELL_PUT_OPEN = "SELL_PUT_OPEN"
EV_BUY_PUT_CLOSE = "BUY_PUT_CLOSE"
EV_PUT_EXPIRE = "PUT_EXPIRE"
EV_PUT_ASSIGNMENT = "PUT_ASSIGNMENT"
EV_BUY_LONG_CALL = "BUY_LONG_CALL"
EV_SELL_LONG_CALL = "SELL_LONG_CALL"
EV_LONG_CALL_EXPIRE = "LONG_CALL_EXPIRE"

LEAPS_MIN_DTE = 180


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _parse_date(date_str: str) -> date:
    """Parse YYYY-MM-DD or YYYY-MM-DD HH:MM:SS to a date object."""
    try:
        return datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    except Exception:
        return date.min


def _dte(open_date_str: str, expiry_str: str) -> int:
    """Days-to-expiry from open_date to expiry."""
    try:
        return (_parse_date(expiry_str) - _parse_date(open_date_str)).days
    except Exception:
        return 0


def _uid() -> str:
    return str(uuid.uuid4())[:8]


def _dataclass_to_dict(obj) -> dict:
    """Recursively convert a dataclass (or list/dict thereof) to plain dict."""
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    if isinstance(obj, list):
        return [_dataclass_to_dict(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _dataclass_to_dict(v) for k, v in obj.items()}
    return obj


# ---------------------------------------------------------------------------
# Main Engine
# ---------------------------------------------------------------------------

class LifecycleEngine:
    """
    Process a list of raw transactions for a single symbol and produce
    a structured lifecycle result containing CC and PMCC cycles.
    """

    def __init__(self):
        self.lots: dict[str, ShareLot] = {}
        self.options: dict[str, OptionPosition] = {}
        self.cycles: dict[str, TradeCycle] = {}
        self.pmcc_cycles: dict[str, PMCCCycle] = {}
        self.long_call_lots: dict[str, LongCallLot] = {}
        self._cycle_counter: dict[str, int] = {}

        # Pending open puts (option_id -> OptionPosition) waiting for assignment
        self._open_puts: dict[str, OptionPosition] = {}

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def process_transactions(self, transactions: list[dict], symbol: str) -> dict:
        """
        Main entry point.

        Parameters
        ----------
        transactions : list of raw transaction dicts (from ibkr_parser.py)
        symbol       : the ticker symbol being processed

        Returns
        -------
        dict with keys: cc_cycles, pmcc_cycles, summary
        """
        if not transactions:
            return self._build_output(symbol)

        events = self._normalize(transactions, symbol)
        for event in events:
            try:
                self._process_event(event)
            except Exception as exc:
                logger.warning(
                    "Error processing event %s for %s: %s",
                    event.get("event_type"),
                    symbol,
                    exc,
                    exc_info=True,
                )

        self._infer_expired_options()
        self._recalculate_all_cycles()
        return self._build_output(symbol)

    # ------------------------------------------------------------------
    # Normalisation
    # ------------------------------------------------------------------

    def _normalize(self, transactions: list[dict], symbol: str) -> list[dict]:
        """
        Sort transactions by datetime and classify each into an event_type.
        Returns a list of enriched event dicts.
        """
        sorted_txns = sorted(
            transactions,
            key=lambda t: t.get("datetime", t.get("date", "1970-01-01")),
        )

        events = []
        for txn in sorted_txns:
            event = self._classify(txn, symbol)
            if event:
                events.append(event)
        return events

    def _classify(self, txn: dict, symbol: str) -> Optional[dict]:
        """Classify a single transaction into an event dict."""
        txn_type = txn.get("transaction_type", "")
        is_option = txn.get("is_option", False)
        quantity = txn.get("quantity", 0)
        opt = txn.get("option_details") or {}
        opt_type = opt.get("option_type", "")
        date_str = txn.get("date", txn.get("datetime", "")[:10])

        event_type = None

        if not is_option:
            # Stock transaction
            if txn_type in ("Buy",) and quantity > 0:
                event_type = EV_BUY_STOCK
            elif txn_type in ("Sell",) and quantity < 0:
                event_type = EV_SELL_STOCK
            elif txn_type == "Assignment":
                # Stock leg of a put assignment
                event_type = EV_PUT_ASSIGNMENT
            else:
                logger.debug("Unclassified stock transaction: %s", txn)
                return None
        else:
            # Option transaction
            if opt_type == "Call":
                if txn_type == "Buy" and quantity > 0:
                    # Could be LEAPS buy or close of a short call
                    dte = opt.get("dte_at_open") or _dte(date_str, opt.get("expiry", ""))
                    delta = opt.get("delta")
                    if self._qualifies_as_leaps(dte, delta, opt.get("strike"), txn.get("price")):
                        event_type = EV_BUY_LONG_CALL
                    else:
                        event_type = EV_BUY_CALL_CLOSE
                elif txn_type == "Sell" and quantity < 0:
                    event_type = EV_SELL_CALL_OPEN
                elif txn_type in ("Expiry", "Expire"):
                    # Determine if it was a short or long call
                    event_type = self._resolve_expiry_event(opt, "Call", txn)
                elif txn_type == "Assignment":
                    event_type = EV_CALL_ASSIGNMENT
                else:
                    logger.debug("Unclassified call transaction: %s", txn)
                    return None

            elif opt_type == "Put":
                if txn_type == "Sell" and quantity < 0:
                    event_type = EV_SELL_PUT_OPEN
                elif txn_type == "Buy" and quantity > 0:
                    event_type = EV_BUY_PUT_CLOSE
                elif txn_type in ("Expiry", "Expire"):
                    event_type = EV_PUT_EXPIRE
                elif txn_type == "Assignment":
                    event_type = EV_PUT_ASSIGNMENT
                else:
                    logger.debug("Unclassified put transaction: %s", txn)
                    return None
            else:
                logger.debug("Unknown option_type: %s", opt_type)
                return None

        if event_type is None:
            return None

        return {
            "event_type": event_type,
            "id": txn.get("id", _uid()),
            "date": date_str,
            "datetime": txn.get("datetime", date_str),
            "symbol": txn.get("underlying_symbol") or txn.get("symbol", symbol),
            "quantity": quantity,
            "price": txn.get("price", 0.0),
            "net_amount": txn.get("net_amount", 0.0),
            "option_details": opt,
            "raw": txn,
        }

    def _resolve_expiry_event(self, opt: dict, opt_type: str, txn: dict) -> str:
        """Determine whether an expiry belongs to a long call or short call."""
        # Check if we have an open long_call_lot matching this option
        expiry = opt.get("expiry", "")
        strike = opt.get("strike")
        symbol = txn.get("symbol", "")
        for ll in self.long_call_lots.values():
            if (
                ll.symbol == symbol
                and ll.strike == strike
                and ll.expiry == expiry
                and ll.status == "OPEN"
            ):
                return EV_LONG_CALL_EXPIRE
        return EV_CALL_EXPIRE

    @staticmethod
    def _qualifies_as_leaps(dte: Optional[int], delta: Optional[float], strike, price) -> bool:
        """
        Determine if a long call qualifies as LEAPS for PMCC purposes.
        Criteria:
          - DTE at purchase >= 180 days
          - delta >= 0.50 OR strike significantly below current price (>= 10% ITM)
        """
        if dte is None or dte < LEAPS_MIN_DTE:
            return False
        if delta is not None and delta >= 0.50:
            return True
        # Fallback: strike is at least 10% below the purchase price
        if strike is not None and price is not None and price > 0:
            if strike <= price * 0.90:
                return True
        return False

    # ------------------------------------------------------------------
    # Event dispatcher
    # ------------------------------------------------------------------

    def _process_event(self, event: dict):
        et = event["event_type"]
        dispatch = {
            EV_BUY_STOCK:       self._handle_buy_stock,
            EV_SELL_STOCK:      self._handle_sell_stock,
            EV_SELL_CALL_OPEN:  self._handle_sell_call,
            EV_BUY_CALL_CLOSE:  self._handle_buy_call_close,
            EV_CALL_EXPIRE:     self._handle_call_expire,
            EV_CALL_ASSIGNMENT: self._handle_call_assignment,
            EV_SELL_PUT_OPEN:   self._handle_sell_put,
            EV_BUY_PUT_CLOSE:   self._handle_buy_put_close,
            EV_PUT_EXPIRE:      self._handle_put_expire,
            EV_PUT_ASSIGNMENT:  self._handle_put_assignment,
            EV_BUY_LONG_CALL:   self._handle_buy_long_call,
            EV_SELL_LONG_CALL:  self._handle_sell_long_call,
            EV_LONG_CALL_EXPIRE: self._handle_long_call_expire,
        }
        handler = dispatch.get(et)
        if handler:
            handler(event)
        else:
            logger.debug("No handler for event type: %s", et)

    # ------------------------------------------------------------------
    # CC / Wheel Handlers
    # ------------------------------------------------------------------

    def _handle_buy_stock(self, event: dict):
        """Rule 1 & 2: New stock acquisition creates a new ShareLot and TradeCycle."""
        symbol = event["symbol"]
        shares = abs(event["quantity"])
        price = event["price"]
        date_str = event["date"]
        trade_id = event["id"]

        lot_id = f"LOT_{symbol}_{_uid()}"
        lot = ShareLot(
            lot_id=lot_id,
            symbol=symbol,
            open_date=date_str,
            shares_open=shares,
            shares_remaining=shares,
            entry_price=price,
            effective_entry=price,
            entry_type="BUY",
            source_trade_ids=[trade_id],
        )

        cycle_id = self._new_cycle_id(symbol, "CC")
        cycle = TradeCycle(
            cycle_id=cycle_id,
            symbol=symbol,
            strategy="CC",
            status="Open - Uncovered",
            entry_mode="STOCK_ENTRY",
            opened_date=date_str,
            lots=[lot_id],
            total_shares_entered=shares,
            shares_current=shares,
            uncovered_shares=shares,
            total_stock_cost=shares * price,
            avg_cost=price,
            effective_avg_cost=price,
        )

        lot.linked_cycle_id = cycle_id
        self.lots[lot_id] = lot
        self.cycles[cycle_id] = cycle

    def _handle_sell_stock(self, event: dict):
        """Close shares from oldest lot first; update cycle status."""
        symbol = event["symbol"]
        shares_to_sell = abs(event["quantity"])
        price = event["price"]
        date_str = event["date"]

        open_lots = self._get_open_lots(symbol)
        if not open_lots:
            logger.warning("SELL_STOCK: no open lots for %s", symbol)
            return

        remaining = shares_to_sell
        for lot in open_lots:
            if remaining <= 0:
                break
            allocated = min(lot.shares_remaining, remaining)
            realized = allocated * (price - lot.effective_entry)
            lot.shares_remaining -= allocated
            remaining -= allocated

            cycle = self.cycles.get(lot.linked_cycle_id)
            if cycle:
                cycle.realized_pnl += realized
                cycle.shares_current = max(0, cycle.shares_current - allocated)
                if cycle.shares_current == 0:
                    cycle.status = "Closed by Share Sale"
                    cycle.closed_date = date_str

    def _handle_sell_call(self, event: dict):
        """
        Rule 3: Match short call FIFO to uncovered open lots.
        Rule 4: If call spans multiple cycles, mark jointly_managed.
        """
        symbol = event["symbol"]
        opt = event["option_details"]
        contracts = abs(opt.get("contracts", abs(event["quantity"]) // 100 or 1))
        premium = opt.get("premium_per_share", event["price"])
        strike = opt.get("strike", 0.0)
        expiry = opt.get("expiry", "")
        date_str = event["date"]
        trade_id = event["id"]

        # Check if this is a PMCC short call (there is an active LEAPS)
        active_pmcc = self._find_active_pmcc(symbol)
        if active_pmcc:
            option_id = self._create_option_position(
                symbol, "CALL", "SELL", strike, expiry,
                contracts, premium, date_str, trade_id,
                linked_cycle_ids=[active_pmcc.cycle_id],
            )
            self._handle_sell_short_call_pmcc(event, active_pmcc, option_id)
            return

        # CC short call — FIFO allocate
        shares_needed = contracts * 100
        allocated_lots = self._fifo_allocate(symbol, shares_needed)
        if not allocated_lots:
            logger.warning("SELL_CALL_OPEN: no uncovered lots for %s (contracts=%d)", symbol, contracts)
            return

        touched_cycle_ids = []
        for lot, shares_alloc in allocated_lots:
            lot.shares_remaining -= shares_alloc
            if lot.linked_cycle_id not in touched_cycle_ids:
                touched_cycle_ids.append(lot.linked_cycle_id)

        option_id = self._create_option_position(
            symbol, "CALL", "SELL", strike, expiry,
            contracts, premium, date_str, trade_id,
            linked_cycle_ids=touched_cycle_ids,
        )

        for cycle_id in touched_cycle_ids:
            cycle = self.cycles.get(cycle_id)
            if cycle:
                cycle.short_calls.append(option_id)
                cycle.total_premium_received += premium * contracts * 100

        # Rule 4 & 5: Mark jointly_managed if call spans multiple cycles
        if len(touched_cycle_ids) > 1:
            self._maybe_merge_cycles(touched_cycle_ids, self.options[option_id])

        self._update_cycle_coverage_status(touched_cycle_ids)

    def _handle_buy_call_close(self, event: dict):
        """Buy back a short call (close position)."""
        symbol = event["symbol"]
        opt = event["option_details"]
        strike = opt.get("strike", 0.0)
        expiry = opt.get("expiry", "")
        contracts = abs(opt.get("contracts", abs(event["quantity"]) // 100 or 1))
        close_premium = opt.get("premium_per_share", event["price"])
        date_str = event["date"]

        matched = self._find_open_short_call(symbol, strike, expiry, contracts)
        if not matched:
            logger.warning("BUY_CALL_CLOSE: no matching short call for %s %s %s", symbol, strike, expiry)
            return

        matched.status = "BOUGHT_BACK"
        matched.close_date = date_str
        matched.close_premium = close_premium

        for cycle_id in matched.linked_cycle_ids:
            cycle = self.cycles.get(cycle_id)
            if cycle:
                cycle.total_premium_paid += close_premium * matched.contracts * 100
                # Release covered shares back to lots
                self._release_shares_for_option(matched)
        self._update_cycle_coverage_status(matched.linked_cycle_ids)

    def _handle_call_expire(self, event: dict):
        """
        Rule 7: Call expiry keeps cycle OPEN; shares become uncovered again.
        """
        symbol = event["symbol"]
        opt = event["option_details"]
        strike = opt.get("strike", 0.0)
        expiry = opt.get("expiry", "")
        contracts = abs(opt.get("contracts", 1))
        date_str = event["date"]

        matched = self._find_open_short_call(symbol, strike, expiry, contracts)
        if not matched:
            logger.warning("CALL_EXPIRE: no matching short call for %s %s %s", symbol, strike, expiry)
            return

        matched.status = "EXPIRED"
        matched.close_date = date_str
        matched.close_premium = 0.0

        for cycle_id in matched.linked_cycle_ids:
            cycle = self.cycles.get(cycle_id)
            if cycle:
                cycle.total_premium_received += 0  # already booked at open
        # Release shares (they are uncovered again)
        self._release_shares_for_option(matched)
        self._update_cycle_coverage_status(matched.linked_cycle_ids)

    def _handle_call_assignment(self, event: dict):
        """
        Rule 8: Call assignment removes assigned shares from FIFO lots.
        Partial or full close of linked cycle(s).
        """
        symbol = event["symbol"]
        opt = event["option_details"]
        strike = opt.get("strike", 0.0)
        expiry = opt.get("expiry", "")
        contracts = abs(opt.get("contracts", abs(event["quantity"]) // 100 or 1))
        date_str = event["date"]

        matched = self._find_open_short_call(symbol, strike, expiry, contracts)
        if not matched:
            logger.warning("CALL_ASSIGNMENT: no matching short call for %s %s %s", symbol, strike, expiry)
            return

        matched.status = "ASSIGNED"
        matched.close_date = date_str
        matched.close_premium = 0.0

        shares_to_assign = contracts * 100
        # These shares were already "covered" by the option so shares_remaining
        # was already decremented. We now fully close those share slots.
        # Walk lots linked to the cycles of this option to remove shares.
        remaining = shares_to_assign
        for cycle_id in matched.linked_cycle_ids:
            cycle = self.cycles.get(cycle_id)
            if not cycle:
                continue
            for lot_id in cycle.lots:
                if remaining <= 0:
                    break
                lot = self.lots.get(lot_id)
                if not lot or lot.shares_open == 0:
                    continue
                # Covered shares were already taken from shares_remaining,
                # so shares_open - shares_remaining = currently covered shares.
                covered_in_lot = lot.shares_open - lot.shares_remaining
                if covered_in_lot <= 0:
                    continue
                assigned = min(covered_in_lot, remaining)
                realized = assigned * (strike - lot.effective_entry) + matched.open_premium * assigned
                lot.shares_open -= assigned
                # shares_remaining doesn't change (these were covered shares)
                cycle.realized_pnl += realized
                cycle.shares_current = max(0, cycle.shares_current - assigned)
                cycle.number_of_assignments += 1
                remaining -= assigned

            if cycle.shares_current == 0:
                cycle.status = "Closed by Assignment"
                cycle.closed_date = date_str
            elif cycle.shares_current < cycle.total_shares_entered:
                cycle.status = "Partially Assigned"

        self._update_cycle_coverage_status(matched.linked_cycle_ids)

    def _handle_sell_put(self, event: dict):
        """Create a short put position (cash-secured put / wheel entry)."""
        symbol = event["symbol"]
        opt = event["option_details"]
        contracts = abs(opt.get("contracts", abs(event["quantity"]) // 100 or 1))
        premium = opt.get("premium_per_share", event["price"])
        strike = opt.get("strike", 0.0)
        expiry = opt.get("expiry", "")
        date_str = event["date"]
        trade_id = event["id"]

        # Determine which cycle this put belongs to (or create CSP cycle)
        open_uncovered = [
            c for c in self.cycles.values()
            if c.symbol == symbol and c.status in ("Open - Uncovered", "Open - Put Entry Active")
        ]

        if open_uncovered:
            cycle_id = open_uncovered[-1].cycle_id
        else:
            cycle_id = self._new_cycle_id(symbol, "CSP")
            cycle = TradeCycle(
                cycle_id=cycle_id,
                symbol=symbol,
                strategy="CSP",
                status="Open - Put Entry Active",
                entry_mode="PUT_ENTRY",
                opened_date=date_str,
            )
            self.cycles[cycle_id] = cycle

        option_id = self._create_option_position(
            symbol, "PUT", "SELL", strike, expiry,
            contracts, premium, date_str, trade_id,
            linked_cycle_ids=[cycle_id],
        )
        self._open_puts[option_id] = self.options[option_id]

        cycle = self.cycles[cycle_id]
        cycle.short_puts.append(option_id)
        cycle.total_premium_received += premium * contracts * 100
        cycle.status = "Open - Put Entry Active"

    def _handle_buy_put_close(self, event: dict):
        """Buy back a short put."""
        symbol = event["symbol"]
        opt = event["option_details"]
        strike = opt.get("strike", 0.0)
        expiry = opt.get("expiry", "")
        contracts = abs(opt.get("contracts", abs(event["quantity"]) // 100 or 1))
        close_premium = opt.get("premium_per_share", event["price"])
        date_str = event["date"]

        matched = self._find_open_short_put(symbol, strike, expiry)
        if not matched:
            logger.warning("BUY_PUT_CLOSE: no matching short put for %s %s %s", symbol, strike, expiry)
            return

        matched.status = "BOUGHT_BACK"
        matched.close_date = date_str
        matched.close_premium = close_premium

        for cycle_id in matched.linked_cycle_ids:
            cycle = self.cycles.get(cycle_id)
            if cycle:
                cycle.total_premium_paid += close_premium * matched.contracts * 100

        self._open_puts.pop(matched.option_id, None)

    def _handle_put_expire(self, event: dict):
        """Short put expires worthless — keep cycle open (premium already received)."""
        symbol = event["symbol"]
        opt = event["option_details"]
        strike = opt.get("strike", 0.0)
        expiry = opt.get("expiry", "")
        date_str = event["date"]

        matched = self._find_open_short_put(symbol, strike, expiry)
        if not matched:
            logger.warning("PUT_EXPIRE: no matching short put for %s %s %s", symbol, strike, expiry)
            return

        matched.status = "EXPIRED"
        matched.close_date = date_str
        matched.close_premium = 0.0
        self._open_puts.pop(matched.option_id, None)

        for cycle_id in matched.linked_cycle_ids:
            cycle = self.cycles.get(cycle_id)
            if cycle:
                # If no stock was acquired the cycle closes; put premium is the realized P&L.
                if not cycle.lots:
                    cycle.status = "Closed by Share Sale"  # treat as closed
                    cycle.closed_date = date_str
                    cycle.realized_pnl += cycle.total_premium_received - cycle.total_premium_paid
                else:
                    cycle.status = "Open - Uncovered"

    def _handle_put_assignment(self, event: dict):
        """
        Rule 6: Put assignment creates a new ShareLot with
        effective_entry = strike - put_premium_per_share.
        """
        symbol = event["symbol"]
        opt = event.get("option_details") or {}
        date_str = event["date"]
        trade_id = event["id"]

        strike = opt.get("strike") or event.get("price", 0.0)
        contracts = abs(opt.get("contracts", 1))
        shares = contracts * 100

        # Find the matching open short put to retrieve premium
        matched_put = None
        expiry = opt.get("expiry", "")
        if expiry:
            matched_put = self._find_open_short_put(symbol, strike, expiry)
        if matched_put is None:
            # Fallback: find any open put at this strike
            for op in list(self._open_puts.values()):
                if op.symbol == symbol and op.strike == strike:
                    matched_put = op
                    break

        put_premium = 0.0
        linked_put_cycle_ids = []
        if matched_put:
            put_premium = matched_put.open_premium
            matched_put.status = "ASSIGNED"
            matched_put.close_date = date_str
            linked_put_cycle_ids = matched_put.linked_cycle_ids
            self._open_puts.pop(matched_put.option_id, None)

        effective_entry = strike - put_premium

        lot_id = f"LOT_{symbol}_{_uid()}"
        lot = ShareLot(
            lot_id=lot_id,
            symbol=symbol,
            open_date=date_str,
            shares_open=shares,
            shares_remaining=shares,
            entry_price=strike,
            effective_entry=effective_entry,
            entry_type="PUT_ASSIGNMENT",
            source_trade_ids=[trade_id],
        )

        # Reuse the existing CSP cycle if there is one, otherwise create CC cycle
        if linked_put_cycle_ids:
            cycle_id = linked_put_cycle_ids[0]
            cycle = self.cycles.get(cycle_id)
            if cycle:
                cycle.lots.append(lot_id)
                cycle.total_shares_entered += shares
                cycle.shares_current += shares
                cycle.uncovered_shares += shares
                cycle.total_stock_cost += shares * strike
                cycle.strategy = "WHEEL"
                cycle.status = "Open - Uncovered"
                cycle.number_of_assignments += 1
                self._recalculate_cycle_costs(cycle)
        else:
            cycle_id = self._new_cycle_id(symbol, "WHEEL")
            cycle = TradeCycle(
                cycle_id=cycle_id,
                symbol=symbol,
                strategy="WHEEL",
                status="Open - Uncovered",
                entry_mode="PUT_ENTRY",
                opened_date=date_str,
                lots=[lot_id],
                total_shares_entered=shares,
                shares_current=shares,
                uncovered_shares=shares,
                total_stock_cost=shares * strike,
                avg_cost=strike,
                effective_avg_cost=effective_entry,
                number_of_assignments=1,
            )
            self.cycles[cycle_id] = cycle

        lot.linked_cycle_id = cycle_id
        self.lots[lot_id] = lot

    # ------------------------------------------------------------------
    # PMCC Handlers
    # ------------------------------------------------------------------

    def _handle_buy_long_call(self, event: dict):
        """Create a LongCallLot and a new PMCCCycle."""
        symbol = event["symbol"]
        opt = event["option_details"]
        strike = opt.get("strike", 0.0)
        expiry = opt.get("expiry", "")
        contracts = abs(opt.get("contracts", abs(event["quantity"]) // 100 or 1))
        premium = opt.get("premium_per_share", event["price"])
        date_str = event["date"]
        trade_id = event["id"]
        delta = opt.get("delta")

        lot_id = f"LEAPS_{symbol}_{_uid()}"
        total_cost = contracts * 100 * premium
        ll = LongCallLot(
            lot_id=lot_id,
            symbol=symbol,
            strike=strike,
            expiry=expiry,
            contracts_open=contracts,
            contracts_remaining=contracts,
            premium_paid=premium,
            total_cost=total_cost,
            open_date=date_str,
            delta_at_open=delta,
            source_trade_ids=[trade_id],
        )

        # Attach to existing open PMCC cycle for this symbol, or create new one
        existing = self._find_open_pmcc_without_leaps(symbol)
        if existing:
            cycle_id = existing.cycle_id
            pmcc = existing
            pmcc.long_call_lots.append(lot_id)
            pmcc.active_long_lot_id = lot_id
            pmcc.total_debit_paid += total_cost
            pmcc.net_capital_in_use += total_cost
        else:
            cycle_id = self._new_cycle_id(symbol, "PMCC")
            pmcc = PMCCCycle(
                cycle_id=cycle_id,
                symbol=symbol,
                opened_date=date_str,
                long_call_lots=[lot_id],
                active_long_lot_id=lot_id,
                total_debit_paid=total_cost,
                net_capital_in_use=total_cost,
                status="Open - LEAPS Only",
            )
            self.pmcc_cycles[cycle_id] = pmcc

        ll.linked_cycle_id = cycle_id
        self.long_call_lots[lot_id] = ll

    def _handle_sell_short_call_pmcc(self, event: dict, pmcc: PMCCCycle, option_id: str):
        """Link a short call to a PMCC cycle."""
        opt = event["option_details"]
        contracts = abs(opt.get("contracts", 1))
        premium = opt.get("premium_per_share", event["price"])

        pmcc.short_calls.append(option_id)
        pmcc.active_short_call_id = option_id
        pmcc.total_short_premium_received += premium * contracts * 100
        pmcc.net_capital_in_use = max(0, pmcc.total_debit_paid - pmcc.total_short_premium_received + pmcc.total_short_close_cost)
        pmcc.status = "Open - Short Call Active"

    def _handle_short_call_expire_pmcc(self, pmcc: PMCCCycle, option_pos: OptionPosition, date_str: str):
        """PMCC short call expired — wait to resell."""
        option_pos.status = "EXPIRED"
        option_pos.close_date = date_str
        option_pos.close_premium = 0.0
        if pmcc.active_short_call_id == option_pos.option_id:
            pmcc.active_short_call_id = None
        pmcc.status = "Open - Waiting to Resell"
        pmcc.net_capital_in_use = max(
            0,
            pmcc.total_debit_paid - pmcc.total_short_premium_received + pmcc.total_short_close_cost,
        )

    def _handle_sell_long_call(self, event: dict):
        """Close the LEAPS leg; if no replacement, close the PMCC cycle."""
        symbol = event["symbol"]
        opt = event["option_details"]
        strike = opt.get("strike", 0.0)
        expiry = opt.get("expiry", "")
        close_premium = opt.get("premium_per_share", event["price"])
        contracts = abs(opt.get("contracts", abs(event["quantity"]) // 100 or 1))
        date_str = event["date"]

        matched_ll = None
        for ll in self.long_call_lots.values():
            if (
                ll.symbol == symbol
                and ll.strike == strike
                and ll.expiry == expiry
                and ll.status == "OPEN"
            ):
                matched_ll = ll
                break

        if not matched_ll:
            logger.warning("SELL_LONG_CALL: no matching long call lot for %s %s %s", symbol, strike, expiry)
            return

        close_value = contracts * 100 * close_premium
        matched_ll.status = "CLOSED"
        matched_ll.close_date = date_str
        matched_ll.contracts_remaining = max(0, matched_ll.contracts_remaining - contracts)

        pmcc = self.pmcc_cycles.get(matched_ll.linked_cycle_id)
        if pmcc:
            realized = close_value - (matched_ll.premium_paid * contracts * 100)
            pmcc.realized_pnl += realized
            if pmcc.active_long_lot_id == matched_ll.lot_id:
                pmcc.active_long_lot_id = None
            # Check if any long lot is still open
            any_open = any(
                self.long_call_lots[lid].status == "OPEN"
                for lid in pmcc.long_call_lots
                if lid in self.long_call_lots
            )
            if not any_open:
                pmcc.status = "Closed"
                pmcc.closed_date = date_str
                pmcc.net_capital_in_use = 0.0
            pmcc.net_capital_in_use = max(
                0,
                pmcc.total_debit_paid - pmcc.total_short_premium_received + pmcc.total_short_close_cost - close_value,
            )

    def _handle_long_call_expire(self, event: dict):
        """LEAPS expired worthless — close PMCC cycle at a loss."""
        symbol = event["symbol"]
        opt = event["option_details"]
        strike = opt.get("strike", 0.0)
        expiry = opt.get("expiry", "")
        date_str = event["date"]

        for ll in self.long_call_lots.values():
            if (
                ll.symbol == symbol
                and ll.strike == strike
                and ll.expiry == expiry
                and ll.status == "OPEN"
            ):
                ll.status = "EXPIRED"
                ll.close_date = date_str
                pmcc = self.pmcc_cycles.get(ll.linked_cycle_id)
                if pmcc:
                    pmcc.realized_pnl -= ll.premium_paid * ll.contracts_open * 100  # full cost lost
                    pmcc.realized_pnl += pmcc.total_short_premium_received - pmcc.total_short_close_cost
                    pmcc.status = "Closed"
                    pmcc.closed_date = date_str
                    pmcc.net_capital_in_use = 0.0
                break

    # ------------------------------------------------------------------
    # FIFO helpers
    # ------------------------------------------------------------------

    def _get_open_lots(self, symbol: str) -> list[ShareLot]:
        """Return all open lots for symbol sorted oldest first."""
        return sorted(
            [
                lot for lot in self.lots.values()
                if lot.symbol == symbol and lot.shares_remaining > 0
            ],
            key=lambda l: l.open_date,
        )

    def _fifo_allocate(self, symbol: str, shares_needed: int) -> list[tuple]:
        """
        FIFO-allocate shares_needed uncovered shares across open lots.
        Returns [(ShareLot, shares_allocated), ...] oldest-first.
        Does NOT mutate the lots — caller is responsible for decrementing.
        """
        open_lots = self._get_open_lots(symbol)
        allocations = []
        remaining = shares_needed
        for lot in open_lots:
            if remaining <= 0:
                break
            if lot.shares_remaining <= 0:
                continue
            allocated = min(lot.shares_remaining, remaining)
            allocations.append((lot, allocated))
            remaining -= allocated
        if remaining > 0:
            logger.debug(
                "_fifo_allocate: could only allocate %d of %d shares for %s",
                shares_needed - remaining, shares_needed, symbol,
            )
        return allocations

    def _release_shares_for_option(self, option_pos: OptionPosition):
        """
        After a call expires or is bought back, restore shares_remaining
        for the lots that were covered by it.
        """
        shares_to_release = option_pos.contracts * 100
        for cycle_id in option_pos.linked_cycle_ids:
            cycle = self.cycles.get(cycle_id)
            if not cycle:
                continue
            for lot_id in cycle.lots:
                if shares_to_release <= 0:
                    break
                lot = self.lots.get(lot_id)
                if not lot:
                    continue
                covered = lot.shares_open - lot.shares_remaining
                release = min(covered, shares_to_release)
                if release > 0:
                    lot.shares_remaining += release
                    shares_to_release -= release

    # ------------------------------------------------------------------
    # Cycle management helpers
    # ------------------------------------------------------------------

    def _maybe_merge_cycles(self, cycle_ids: list[str], short_call: OptionPosition):
        """
        Rule 4 & 5: Mark cycles as jointly_managed only if ALL shares across
        those cycles are collectively covered by the same call.
        """
        total_covered = short_call.contracts * 100
        total_in_cycles = sum(
            self.cycles[cid].shares_current
            for cid in cycle_ids
            if cid in self.cycles
        )
        if total_covered >= total_in_cycles:
            # Full joint coverage — mark visually merged
            for cid in cycle_ids:
                cycle = self.cycles.get(cid)
                if cycle:
                    others = [x for x in cycle_ids if x != cid]
                    for other in others:
                        if other not in cycle.jointly_managed_with:
                            cycle.jointly_managed_with.append(other)

    def _update_cycle_coverage_status(self, cycle_ids: list[str]):
        """Recompute shares_covered and status for each cycle in the list."""
        for cid in cycle_ids:
            cycle = self.cycles.get(cid)
            if not cycle:
                continue
            # Count shares covered by active (OPEN) short calls
            covered = 0
            for opt_id in cycle.short_calls:
                op = self.options.get(opt_id)
                if op and op.status == "OPEN":
                    covered += op.contracts * 100
            cycle.shares_covered_by_calls = min(covered, cycle.shares_current)
            cycle.uncovered_shares = max(0, cycle.shares_current - cycle.shares_covered_by_calls)

            if cycle.status in ("Closed by Assignment", "Closed by Share Sale"):
                continue
            if cycle.shares_current <= 0:
                continue

            if cycle.shares_covered_by_calls == 0:
                if any(self.options.get(p) and self.options[p].status == "OPEN"
                       for p in cycle.short_puts):
                    cycle.status = "Open - Put Entry Active"
                else:
                    cycle.status = "Open - Uncovered"
            elif cycle.shares_covered_by_calls < cycle.shares_current:
                cycle.status = "Open - Partial Coverage"
            else:
                cycle.status = "Open - Covered Call Active"

    def _infer_expired_options(self):
        """
        IBKR Activity Statements don't export zero-value expiry rows.
        Any short option still marked OPEN whose expiry date is in the past
        is assumed to have expired worthless — apply expiry logic now.
        """
        from datetime import date as _date
        today = _date.today()

        # Infer expired short calls (CC cycles) — self.options holds all positions
        for opt in list(self.options.values()):
            if opt.opt_type != "CALL" or opt.side != "SELL" or opt.status != "OPEN":
                continue
            if not opt.expiry:
                continue
            try:
                exp_date = datetime.strptime(opt.expiry, "%Y-%m-%d").date()
            except ValueError:
                continue
            if exp_date < today:
                opt.status = "EXPIRED"
                opt.close_date = opt.expiry
                opt.close_premium = 0.0
                # Release covered shares back to uncovered
                self._release_shares_for_option(opt)
                self._update_cycle_coverage_status(opt.linked_cycle_ids)
                # Update PMCC cycle if this was a PMCC short call
                for pmcc in self.pmcc_cycles.values():
                    if pmcc.active_short_call_id == opt.option_id:
                        pmcc.active_short_call_id = None
                        pmcc.status = "Open - Waiting to Resell"

        # Infer expired short puts
        for opt in list(self._open_puts.values()):
            if not opt.expiry:
                continue
            try:
                exp_date = datetime.strptime(opt.expiry, "%Y-%m-%d").date()
            except ValueError:
                continue
            if exp_date < today:
                opt.status = "EXPIRED"
                opt.close_date = opt.expiry
                opt.close_premium = 0.0
                self._open_puts.pop(opt.option_id, None)
                for cycle_id in opt.linked_cycle_ids:
                    cycle = self.cycles.get(cycle_id)
                    if cycle and not cycle.lots:
                        cycle.status = "Closed by Share Sale"
                        cycle.closed_date = opt.expiry
                        cycle.realized_pnl += cycle.total_premium_received - cycle.total_premium_paid

    def _recalculate_cycle_costs(self, cycle: TradeCycle):
        """Recompute avg_cost and effective_avg_cost from lots."""
        if cycle.shares_current <= 0:
            return
        total_cost = sum(
            self.lots[lid].entry_price * self.lots[lid].shares_open
            for lid in cycle.lots
            if lid in self.lots
        )
        total_eff_cost = sum(
            self.lots[lid].effective_entry * self.lots[lid].shares_open
            for lid in cycle.lots
            if lid in self.lots
        )
        total_shares = sum(
            self.lots[lid].shares_open
            for lid in cycle.lots
            if lid in self.lots
        )
        if total_shares > 0:
            cycle.avg_cost = total_cost / total_shares
            cycle.effective_avg_cost = total_eff_cost / total_shares

    def _recalculate_all_cycles(self):
        """Final pass to recompute derived fields for all cycles."""
        for cycle in self.cycles.values():
            self._recalculate_cycle_costs(cycle)
            self._update_cycle_coverage_status([cycle.cycle_id])

    # ------------------------------------------------------------------
    # PMCC lookup helpers
    # ------------------------------------------------------------------

    def _find_active_pmcc(self, symbol: str) -> Optional[PMCCCycle]:
        """Find an open PMCC cycle for the symbol that has an active LEAPS."""
        for pmcc in self.pmcc_cycles.values():
            if pmcc.symbol != symbol:
                continue
            if pmcc.status in ("Closed",):
                continue
            if pmcc.active_long_lot_id and self.long_call_lots.get(pmcc.active_long_lot_id):
                ll = self.long_call_lots[pmcc.active_long_lot_id]
                if ll.status == "OPEN":
                    return pmcc
        return None

    def _find_open_pmcc_without_leaps(self, symbol: str) -> Optional[PMCCCycle]:
        """Find an open PMCC cycle that has no active long lot (rolling scenario)."""
        for pmcc in self.pmcc_cycles.values():
            if pmcc.symbol == symbol and pmcc.status != "Closed" and not pmcc.active_long_lot_id:
                return pmcc
        return None

    # ------------------------------------------------------------------
    # Option lookup helpers
    # ------------------------------------------------------------------

    def _create_option_position(
        self,
        symbol: str,
        opt_type: str,
        side: str,
        strike: float,
        expiry: str,
        contracts: int,
        premium: float,
        date_str: str,
        trade_id: str,
        linked_cycle_ids: list[str] = None,
    ) -> str:
        option_id = f"OPT_{symbol}_{opt_type}_{_uid()}"
        op = OptionPosition(
            option_id=option_id,
            symbol=symbol,
            opt_type=opt_type,
            side=side,
            strike=strike,
            expiry=expiry,
            contracts=contracts,
            open_premium=premium,
            open_date=date_str,
            linked_cycle_ids=linked_cycle_ids or [],
            source_trade_ids=[trade_id],
        )
        self.options[option_id] = op
        return option_id

    def _find_open_short_call(
        self, symbol: str, strike: float, expiry: str, contracts: int = None
    ) -> Optional[OptionPosition]:
        """Find the best matching open short call."""
        candidates = [
            op for op in self.options.values()
            if (
                op.symbol == symbol
                and op.opt_type == "CALL"
                and op.side == "SELL"
                and op.strike == strike
                and op.expiry == expiry
                and op.status == "OPEN"
            )
        ]
        if not candidates:
            return None
        if contracts is not None:
            exact = [c for c in candidates if c.contracts == contracts]
            if exact:
                return exact[0]
        return candidates[0]

    def _find_open_short_put(
        self, symbol: str, strike: float, expiry: str
    ) -> Optional[OptionPosition]:
        for op in self._open_puts.values():
            if op.symbol == symbol and op.strike == strike and (not expiry or op.expiry == expiry):
                return op
        # Fallback: search all options
        for op in self.options.values():
            if (
                op.symbol == symbol
                and op.opt_type == "PUT"
                and op.side == "SELL"
                and op.strike == strike
                and op.status == "OPEN"
                and (not expiry or op.expiry == expiry)
            ):
                return op
        return None

    # ------------------------------------------------------------------
    # Cycle ID generator
    # ------------------------------------------------------------------

    def _new_cycle_id(self, symbol: str, strategy: str) -> str:
        key = f"{symbol}_{strategy}"
        self._cycle_counter[key] = self._cycle_counter.get(key, 0) + 1
        return f"{symbol}_{strategy}_{self._cycle_counter[key]:03d}"

    # ------------------------------------------------------------------
    # Output builder
    # ------------------------------------------------------------------

    def _build_output(self, symbol: str) -> dict:
        """Return a serializable dict of all cycles for this symbol."""
        cc_cycles = [
            asdict(c)
            for c in sorted(self.cycles.values(), key=lambda x: x.opened_date)
            if c.symbol == symbol
        ]
        pmcc_cycles = [
            self._pmcc_cycle_to_dict(p)
            for p in sorted(self.pmcc_cycles.values(), key=lambda x: x.opened_date)
            if p.symbol == symbol
        ]

        total_premium = sum(c.get("total_premium_received", 0) for c in cc_cycles) + sum(
            p.get("total_short_premium_received", 0) for p in pmcc_cycles
        )
        realized_pnl = sum(c.get("realized_pnl", 0) for c in cc_cycles) + sum(
            p.get("realized_pnl", 0) for p in pmcc_cycles
        )
        unrealized_pnl = sum(c.get("unrealized_pnl", 0) for c in cc_cycles) + sum(
            p.get("unrealized_pnl", 0) for p in pmcc_cycles
        )

        open_statuses = {
            "Open - Uncovered",
            "Open - Covered Call Active",
            "Open - Put Entry Active",
            "Open - Partial Coverage",
            "Partially Assigned",
            "Open - LEAPS Only",
            "Open - Short Call Active",
            "Open - Waiting to Resell",
            "Roll in Progress",
        }
        closed_statuses = {
            "Closed by Assignment",
            "Closed by Share Sale",
            "Closed",
        }

        open_cycles = sum(1 for c in cc_cycles if c["status"] in open_statuses) + sum(
            1 for p in pmcc_cycles if p["status"] in open_statuses
        )
        closed_cycles = sum(1 for c in cc_cycles if c["status"] in closed_statuses) + sum(
            1 for p in pmcc_cycles if p["status"] in closed_statuses
        )

        # Expose option positions and long call lots as lookup maps for frontend
        options_map = {
            opt_id: asdict(opt)
            for opt_id, opt in self.options.items()
            if opt.symbol == symbol
        }
        long_call_lots_map = {
            lot_id: asdict(lot)
            for lot_id, lot in self.long_call_lots.items()
            if lot.symbol == symbol
        }

        return {
            "cc_cycles": cc_cycles,
            "pmcc_cycles": pmcc_cycles,
            "options": options_map,
            "long_call_lots": long_call_lots_map,
            "summary": {
                "total_premium_received": round(total_premium, 2),
                "realized_pnl": round(realized_pnl, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "open_cycles": open_cycles,
                "closed_cycles": closed_cycles,
            },
        }

    def _pmcc_cycle_to_dict(self, pmcc: PMCCCycle) -> dict:
        """Serialize a PMCCCycle including embedded LongCallLot details."""
        d = asdict(pmcc)
        # Enrich long_call_lots with actual lot data
        d["long_call_lot_details"] = [
            asdict(self.long_call_lots[lid])
            for lid in pmcc.long_call_lots
            if lid in self.long_call_lots
        ]
        return d
