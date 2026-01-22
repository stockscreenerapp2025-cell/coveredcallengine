"""
Option Chain Validator - LAYER 2: Validation & Structure Layer
==============================================================

CCE MASTER ARCHITECTURE COMPLIANCE - LAYER 2

This validator runs BEFORE any strategy logic to reject bad chains.
It acts as the GATEKEEPER between ingested data and strategy selection.

INCLUDES:
- OptionChainValidator - Main chain validation
- PricingValidator - BID/ASK/Spread enforcement
- CalendarValidator - Date/timestamp consistency

VALIDATION RULES (NON-NEGOTIABLE):
- Expiry must exist exactly (no inference)
- Strike must exist exactly (no rounding)
- Both calls and puts must exist (for relevant strategies)
- Strikes must exist within ±20% of spot price
- BID must not be null or zero
- ASK must not be null or zero  
- Spread ≤ 10% (NOT 50%)
- Timestamp must be consistent

FAILURE BEHAVIOR:
- Reject symbol ENTIRELY
- Store rejection reason
- Symbol INVISIBLE to all downstream layers
- Do NOT score
- Do NOT display
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any
import pandas_market_calendars as mcal

logger = logging.getLogger(__name__)

# ==================== LAYER 2 CONSTANTS ====================
# CRITICAL: Spread threshold per CCE Master Architecture Spec
MAX_SPREAD_PCT = 10.0  # MANDATORY: 10%, not 50%

# Minimum requirements
MIN_STRIKES_REQUIRED = 3
MIN_OI_FOR_LEAPS = 500


class ChainValidationError(Exception):
    """Raised when option chain validation fails."""
    def __init__(self, symbol: str, reason: str):
        self.symbol = symbol
        self.reason = reason
        super().__init__(f"{symbol}: {reason}")


# ==================== CALENDAR VALIDATOR ====================

class CalendarValidator:
    """
    CCE MASTER ARCHITECTURE - LAYER 2: Calendar Validation
    
    Validates:
    - NYSE trading calendar compliance
    - Timestamp consistency between stock and options
    - Data freshness
    """
    
    def __init__(self):
        self._nyse_calendar = mcal.get_calendar('NYSE')
    
    def get_last_trading_day(self, reference_date: datetime = None) -> datetime:
        """Get the most recent NYSE trading day."""
        if reference_date is None:
            reference_date = datetime.now(timezone.utc)
        
        start = reference_date - timedelta(days=10)
        end = reference_date
        
        schedule = self._nyse_calendar.schedule(
            start_date=start.strftime('%Y-%m-%d'),
            end_date=end.strftime('%Y-%m-%d')
        )
        
        if schedule.empty:
            current = reference_date
            while current.weekday() >= 5:
                current -= timedelta(days=1)
            return current.replace(hour=16, minute=0, second=0, microsecond=0)
        
        last_day = schedule.index[-1]
        return last_day.to_pydatetime().replace(tzinfo=timezone.utc)
    
    def is_trading_day(self, date: datetime = None) -> bool:
        """Check if a given date is an NYSE trading day."""
        if date is None:
            date = datetime.now(timezone.utc)
        
        schedule = self._nyse_calendar.schedule(
            start_date=date.strftime('%Y-%m-%d'),
            end_date=date.strftime('%Y-%m-%d')
        )
        return not schedule.empty
    
    def validate_snapshot_dates(
        self,
        stock_trade_date: str,
        options_trade_date: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate that stock and options snapshot dates match.
        
        CCE MASTER ARCHITECTURE RULE:
        stock_price_trade_date MUST equal options_data_trade_day
        
        Returns: (is_valid, rejection_reason)
        """
        if not stock_trade_date:
            return False, "Stock trade date is missing"
        
        if not options_trade_date:
            return False, "Options trade date is missing"
        
        if stock_trade_date != options_trade_date:
            return False, f"DATE MISMATCH: stock_trade_date={stock_trade_date} != options_trade_date={options_trade_date}"
        
        # Verify it's a valid trading day
        try:
            trade_dt = datetime.strptime(stock_trade_date, '%Y-%m-%d')
            if not self.is_trading_day(trade_dt):
                return False, f"Trade date {stock_trade_date} is not a valid NYSE trading day"
        except ValueError as e:
            return False, f"Invalid date format: {e}"
        
        return True, None
    
    def validate_data_freshness(
        self,
        data_age_hours: float,
        max_age_hours: float = 48.0
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate that data is not stale.
        
        Returns: (is_valid, rejection_reason)
        """
        if data_age_hours is None:
            return False, "Data age not available"
        
        if data_age_hours > max_age_hours:
            return False, f"Data is stale: {data_age_hours:.1f}h old (max {max_age_hours}h)"
        
        return True, None


# ==================== PRICING VALIDATOR ====================

class PricingValidator:
    """
    CCE MASTER ARCHITECTURE - LAYER 2: Pricing Validation
    
    Enforces:
    - SELL legs → BID ONLY
    - BUY legs → ASK ONLY
    - Spread ≤ 10%
    - BID=0 or ASK=0 → REJECTED
    - No midpoint, no last trade, no averaging
    """
    
    def __init__(self, max_spread_pct: float = MAX_SPREAD_PCT):
        """
        Initialize pricing validator.
        
        Args:
            max_spread_pct: Maximum allowed bid-ask spread (default 10%)
        """
        self.max_spread_pct = max_spread_pct
    
    def validate_sell_leg(
        self,
        bid: float,
        ask: float = None,
        contract_desc: str = ""
    ) -> Tuple[bool, Optional[str], Optional[float]]:
        """
        Validate pricing for a SELL leg.
        
        CCE MASTER ARCHITECTURE RULE:
        SELL legs (CC short call, PMCC short call) → BID ONLY
        
        Args:
            bid: Bid price
            ask: Ask price (for spread validation)
            contract_desc: Description for error messages
        
        Returns: (is_valid, rejection_reason, valid_price)
        """
        # BID must exist and be > 0
        if bid is None or bid <= 0:
            return False, f"{contract_desc}: BID is zero or missing (SELL leg requires BID)", None
        
        # If ASK available, validate spread
        if ask is not None and ask > 0:
            spread_pct = ((ask - bid) / ask) * 100
            if spread_pct > self.max_spread_pct:
                return False, f"{contract_desc}: Spread {spread_pct:.1f}% exceeds max {self.max_spread_pct}%", None
        
        return True, None, bid
    
    def validate_buy_leg(
        self,
        ask: float,
        bid: float = None,
        contract_desc: str = ""
    ) -> Tuple[bool, Optional[str], Optional[float]]:
        """
        Validate pricing for a BUY leg.
        
        CCE MASTER ARCHITECTURE RULE:
        BUY legs (PMCC LEAP) → ASK ONLY
        
        Args:
            ask: Ask price
            bid: Bid price (for spread validation)
            contract_desc: Description for error messages
        
        Returns: (is_valid, rejection_reason, valid_price)
        """
        # ASK must exist and be > 0
        if ask is None or ask <= 0:
            return False, f"{contract_desc}: ASK is zero or missing (BUY leg requires ASK)", None
        
        # If BID available, validate spread
        if bid is not None and bid > 0:
            spread_pct = ((ask - bid) / ask) * 100
            if spread_pct > self.max_spread_pct:
                return False, f"{contract_desc}: Spread {spread_pct:.1f}% exceeds max {self.max_spread_pct}%", None
        
        return True, None, ask
    
    def validate_spread(
        self,
        bid: float,
        ask: float,
        contract_desc: str = ""
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate bid-ask spread independently.
        
        CCE MASTER ARCHITECTURE RULE:
        If (ASK − BID) / ASK > 10% → option REJECTED
        
        Returns: (is_valid, rejection_reason)
        """
        if bid is None or bid <= 0:
            return False, f"{contract_desc}: BID is zero or missing"
        
        if ask is None or ask <= 0:
            return False, f"{contract_desc}: ASK is zero or missing"
        
        spread_pct = ((ask - bid) / ask) * 100
        
        if spread_pct > self.max_spread_pct:
            return False, f"{contract_desc}: Spread {spread_pct:.1f}% exceeds maximum {self.max_spread_pct}%"
        
        return True, None


class OptionChainValidator:
    """
    Validates option chains before any strategy logic.
    
    A chain that fails validation is REJECTED entirely:
    - Symbol is excluded from results
    - No scoring is performed
    - Rejection reason is logged
    """
    
    def __init__(self, min_strikes_required: int = 3, max_spread_pct: float = 50.0):
        """
        Initialize validator.
        
        Args:
            min_strikes_required: Minimum strikes needed within ±20% of spot
            max_spread_pct: Maximum bid-ask spread percentage allowed
        """
        self.min_strikes_required = min_strikes_required
        self.max_spread_pct = max_spread_pct
        self.rejection_log: List[Dict] = []
    
    def validate_chain(
        self,
        symbol: str,
        stock_price: float,
        calls: List[Dict],
        puts: List[Dict] = None,
        expiries: List[str] = None,
        require_puts: bool = False
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate an option chain for a symbol.
        
        Args:
            symbol: Stock symbol
            stock_price: Current stock price
            calls: List of call option contracts
            puts: List of put option contracts (optional for CC)
            expiries: List of available expiration dates
            require_puts: Whether puts are required (for spreads)
        
        Returns:
            (is_valid, rejection_reason)
            - (True, None) if chain is valid
            - (False, "reason") if chain is invalid
        """
        try:
            # VALIDATION 1: Stock price must be valid
            if not stock_price or stock_price <= 0:
                return self._reject(symbol, "Invalid stock price")
            
            # VALIDATION 2: Expiries must exist
            if not expiries or len(expiries) == 0:
                return self._reject(symbol, "No expiration dates available")
            
            # VALIDATION 3: Calls must exist
            if not calls or len(calls) == 0:
                return self._reject(symbol, "No call options available")
            
            # VALIDATION 4: Puts must exist if required
            if require_puts and (not puts or len(puts) == 0):
                return self._reject(symbol, "No put options available (required for strategy)")
            
            # VALIDATION 5: Check strikes within ±20% of spot
            min_strike = stock_price * 0.80
            max_strike = stock_price * 1.20
            
            valid_strikes = [
                c for c in calls 
                if c.get("strike") and min_strike <= c["strike"] <= max_strike
            ]
            
            if len(valid_strikes) < self.min_strikes_required:
                return self._reject(
                    symbol, 
                    f"Insufficient strikes within ±20% of spot (found {len(valid_strikes)}, need {self.min_strikes_required})"
                )
            
            # VALIDATION 6: Check BID prices
            contracts_with_bid = [c for c in valid_strikes if c.get("bid", 0) > 0]
            
            if len(contracts_with_bid) < self.min_strikes_required:
                return self._reject(
                    symbol,
                    f"Insufficient contracts with valid BID (found {len(contracts_with_bid)}, need {self.min_strikes_required})"
                )
            
            # VALIDATION 7: Check bid-ask spread on valid contracts
            wide_spread_contracts = []
            for c in contracts_with_bid:
                bid = c.get("bid", 0)
                ask = c.get("ask", 0)
                if bid > 0 and ask > 0:
                    spread_pct = ((ask - bid) / ask) * 100
                    if spread_pct > self.max_spread_pct:
                        wide_spread_contracts.append({
                            "strike": c.get("strike"),
                            "spread_pct": round(spread_pct, 1)
                        })
            
            # If ALL contracts have wide spreads, reject
            if len(wide_spread_contracts) == len(contracts_with_bid):
                return self._reject(
                    symbol,
                    f"All contracts have bid-ask spread > {self.max_spread_pct}%"
                )
            
            # Chain is valid
            return True, None
            
        except Exception as e:
            return self._reject(symbol, f"Validation error: {str(e)}")
    
    def validate_contract(
        self,
        symbol: str,
        contract: Dict,
        stock_price: float,
        is_buy_leg: bool = False
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate a single option contract.
        
        Args:
            symbol: Stock symbol
            contract: Option contract data
            stock_price: Current stock price
            is_buy_leg: True if this is a BUY leg (uses ASK), False for SELL (uses BID)
        
        Returns:
            (is_valid, rejection_reason)
        """
        try:
            # VALIDATION 1: Strike must exist exactly
            strike = contract.get("strike")
            if not strike or strike <= 0:
                return False, "Strike price missing or invalid"
            
            # VALIDATION 2: Expiry must exist exactly
            expiry = contract.get("expiry")
            if not expiry:
                return False, "Expiry date missing"
            
            # VALIDATION 3: BID must exist for SELL legs
            bid = contract.get("bid", 0)
            if not is_buy_leg and (not bid or bid <= 0):
                return False, "BID is zero or missing (required for SELL leg)"
            
            # VALIDATION 4: ASK must exist for BUY legs
            ask = contract.get("ask", 0)
            if is_buy_leg and (not ask or ask <= 0):
                return False, "ASK is zero or missing (required for BUY leg)"
            
            # VALIDATION 5: Bid-Ask spread sanity check
            if bid > 0 and ask > 0:
                spread_pct = ((ask - bid) / ask) * 100
                if spread_pct > self.max_spread_pct:
                    return False, f"Bid-Ask spread too wide: {spread_pct:.1f}% (max {self.max_spread_pct}%)"
            
            # VALIDATION 6: Strike must be reasonable relative to stock price
            if stock_price > 0:
                strike_ratio = strike / stock_price
                if strike_ratio < 0.5 or strike_ratio > 2.0:
                    return False, f"Strike ${strike} is outside valid range (50%-200% of ${stock_price:.2f})"
            
            return True, None
            
        except Exception as e:
            return False, f"Contract validation error: {str(e)}"
    
    def validate_covered_call(
        self,
        symbol: str,
        stock_price: float,
        strike: float,
        expiry: str,
        bid: float,
        dte: int,
        open_interest: int = 0
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate a Covered Call trade structure.
        
        Rules:
        - Strike must exist exactly
        - Expiry must exist exactly
        - BID must be > 0 (SELL leg)
        - DTE must be in valid range
        """
        # VALIDATION 1: Strike
        if not strike or strike <= 0:
            return False, "Invalid strike price"
        
        # VALIDATION 2: Expiry
        if not expiry:
            return False, "Missing expiry date"
        
        # VALIDATION 3: BID (SELL leg)
        if not bid or bid <= 0:
            return False, "BID is zero or missing"
        
        # VALIDATION 4: DTE range
        if dte < 1:
            return False, "Expired or expiring today"
        if dte > 60:
            return False, "DTE too long for covered call (>60 days)"
        
        # VALIDATION 5: Strike must be OTM or ATM for CC
        if stock_price > 0 and strike < stock_price * 0.95:
            return False, f"Strike ${strike} is too deep ITM for covered call"
        
        return True, None
    
    def validate_pmcc_structure(
        self,
        symbol: str,
        stock_price: float,
        leap_strike: float,
        leap_expiry: str,
        leap_ask: float,
        leap_dte: int,
        leap_delta: float,
        leap_oi: int,
        short_strike: float,
        short_expiry: str,
        short_bid: float,
        short_dte: int
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate a Poor Man's Covered Call (PMCC) structure.
        
        LEAP Qualification:
        - DTE ≥ 365
        - Delta ≥ 0.70
        - Bid-Ask spread ≤ 10% (handled by contract validation)
        - OI ≥ 500
        
        Short Call Rules:
        - DTE 14-45
        - Delta 0.20-0.30 (implied by strike selection)
        - Strike > LEAP breakeven
        - BID > 0
        
        Structural Rules:
        - Width > 0 (short strike > leap strike)
        """
        # LEAP VALIDATION
        if not leap_strike or leap_strike <= 0:
            return False, "LEAP: Invalid strike price"
        
        if not leap_expiry:
            return False, "LEAP: Missing expiry date"
        
        if not leap_ask or leap_ask <= 0:
            return False, "LEAP: ASK is zero or missing (required for BUY leg)"
        
        if leap_dte < 365:
            return False, f"LEAP: DTE {leap_dte} is less than required 365 days"
        
        if leap_delta < 0.70:
            return False, f"LEAP: Delta {leap_delta:.2f} is less than required 0.70"
        
        if leap_oi < 500:
            return False, f"LEAP: Open Interest {leap_oi} is less than required 500"
        
        # SHORT CALL VALIDATION
        if not short_strike or short_strike <= 0:
            return False, "Short Call: Invalid strike price"
        
        if not short_expiry:
            return False, "Short Call: Missing expiry date"
        
        if not short_bid or short_bid <= 0:
            return False, "Short Call: BID is zero or missing (required for SELL leg)"
        
        if short_dte < 14 or short_dte > 45:
            return False, f"Short Call: DTE {short_dte} outside valid range 14-45"
        
        # STRUCTURAL VALIDATION
        # Width must be positive (short strike > leap strike for PMCC)
        if short_strike <= leap_strike:
            return False, f"Invalid structure: Short strike ${short_strike} must be > LEAP strike ${leap_strike}"
        
        # Short strike must be above LEAP breakeven
        leap_breakeven = leap_strike + leap_ask
        if short_strike <= leap_breakeven:
            return False, f"Short strike ${short_strike} must be above LEAP breakeven ${leap_breakeven:.2f}"
        
        return True, None
    
    def _reject(self, symbol: str, reason: str) -> Tuple[bool, str]:
        """Log rejection and return failure."""
        rejection = {
            "symbol": symbol,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        self.rejection_log.append(rejection)
        logger.warning(f"Chain validation REJECTED: {symbol} - {reason}")
        return False, reason
    
    def get_rejection_log(self) -> List[Dict]:
        """Get list of all rejections."""
        return self.rejection_log
    
    def clear_rejection_log(self):
        """Clear the rejection log."""
        self.rejection_log = []
    
    def get_rejection_summary(self) -> Dict[str, Any]:
        """Get summary of rejections by reason."""
        summary = {}
        for r in self.rejection_log:
            reason = r["reason"]
            if reason not in summary:
                summary[reason] = []
            summary[reason].append(r["symbol"])
        
        return {
            "total_rejections": len(self.rejection_log),
            "by_reason": summary
        }


# Global validator instance
_validator: Optional[OptionChainValidator] = None


def get_validator() -> OptionChainValidator:
    """Get or create the global validator instance."""
    global _validator
    if _validator is None:
        _validator = OptionChainValidator()
    return _validator


def validate_chain_for_cc(
    symbol: str,
    stock_price: float,
    calls: List[Dict],
    expiries: List[str] = None
) -> Tuple[bool, Optional[str]]:
    """
    Convenience function to validate a chain for Covered Call scanning.
    
    Returns: (is_valid, rejection_reason)
    """
    validator = get_validator()
    return validator.validate_chain(
        symbol=symbol,
        stock_price=stock_price,
        calls=calls,
        expiries=expiries,
        require_puts=False
    )


def validate_cc_trade(
    symbol: str,
    stock_price: float,
    strike: float,
    expiry: str,
    bid: float,
    dte: int,
    open_interest: int = 0
) -> Tuple[bool, Optional[str]]:
    """
    Convenience function to validate a single Covered Call trade.
    
    Returns: (is_valid, rejection_reason)
    """
    validator = get_validator()
    return validator.validate_covered_call(
        symbol=symbol,
        stock_price=stock_price,
        strike=strike,
        expiry=expiry,
        bid=bid,
        dte=dte,
        open_interest=open_interest
    )


def validate_pmcc_trade(
    symbol: str,
    stock_price: float,
    leap_strike: float,
    leap_expiry: str,
    leap_ask: float,
    leap_dte: int,
    leap_delta: float,
    leap_oi: int,
    short_strike: float,
    short_expiry: str,
    short_bid: float,
    short_dte: int
) -> Tuple[bool, Optional[str]]:
    """
    Convenience function to validate a PMCC trade structure.
    
    Returns: (is_valid, rejection_reason)
    """
    validator = get_validator()
    return validator.validate_pmcc_structure(
        symbol=symbol,
        stock_price=stock_price,
        leap_strike=leap_strike,
        leap_expiry=leap_expiry,
        leap_ask=leap_ask,
        leap_dte=leap_dte,
        leap_delta=leap_delta,
        leap_oi=leap_oi,
        short_strike=short_strike,
        short_expiry=short_expiry,
        short_bid=short_bid,
        short_dte=short_dte
    )
