"""
IBKR CSV Parser Service for Covered Call Engine
Parses Interactive Brokers transaction history and categorizes trading strategies
"""

import csv
import re
import io
import hashlib
import logging
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from uuid import uuid4

logger = logging.getLogger(__name__)

# Strategy type constants
STRATEGY_TYPES = {
    'STOCK': 'Stock',
    'ETF': 'ETF',
    'INDEX': 'Index',
    'COVERED_CALL': 'Covered Call',
    'PMCC': 'PMCC',
    'NAKED_PUT': 'Naked Put',
    'COLLAR': 'Collar',
    'OPTION': 'Option',
    'DIVIDEND': 'Dividend',
    'OTHER': 'Other'
}

# Common ETF symbols - expanded list
ETF_SYMBOLS = {
    # Major Index ETFs
    'SPY', 'QQQ', 'IWM', 'DIA', 'VTI', 'VOO', 'VXX', 'RSP',
    # Sector ETFs
    'XLF', 'XLE', 'XLK', 'XLV', 'XLI', 'XLP', 'XLY', 'XLB', 'XLU', 'XLRE',
    # International
    'EEM', 'EFA', 'VWO', 'VEA', 'IEMG', 'VEU', 'VXUS',
    # Bonds
    'AGG', 'BND', 'LQD', 'HYG', 'TLT', 'IEF', 'SHY', 'TIP',
    # Commodities
    'GLD', 'SLV', 'USO', 'UNG', 'DBA', 'DBC',
    # ARK Innovation
    'ARKK', 'ARKG', 'ARKW', 'ARKF', 'ARKQ', 'ARKX',
    # Leveraged/Inverse
    'SOXL', 'TQQQ', 'SPXL', 'UPRO', 'SQQQ', 'SDOW', 'UVXY', 'VIXY', 'SOXS',
    # Dividend/Value
    'VIG', 'VYM', 'SCHD', 'DVY', 'HDV', 'SDY',
    # Growth
    'VUG', 'IWF', 'MGK', 'VONG', 'VGT', 'IGV',
    # Thematic/Specialty
    'SMH', 'SOXX', 'XBI', 'IBB', 'HACK', 'SKYY', 'CLOU', 'WCLD',
    'BOTZ', 'ROBO', 'RBTZ', 'AIQ', 'IRBO',
    # Crypto/Blockchain
    'HUT', 'BITX', 'BITO', 'GBTC', 'ETHE', 'BLOK', 'DAPP',
    # Cannabis
    'MSOS', 'MJ', 'YOLO',
    # Clean Energy
    'ICLN', 'TAN', 'QCLN', 'PBW', 'LIT',
    # Metals/Mining
    'GDX', 'GDXJ', 'SIL', 'REMX', 'PICK', 'XME',
    # Real Estate
    'VNQ', 'IYR', 'SCHH', 'RWR'
}

# Index symbols
INDEX_SYMBOLS = {'SPX', 'NDX', 'RUT', 'VIX', 'DJX'}


class IBKRParser:
    """Parser for Interactive Brokers CSV transaction files"""
    
    def __init__(self):
        self.transactions = []
        self.accounts = set()
        self.fx_rates = {}
        
    def parse_csv(self, csv_content: str) -> Dict:
        """Parse IBKR CSV content and return structured data"""
        self.transactions = []
        self.accounts = set()
        self.fx_rates = {}
        
        # Parse IBKR CSV format which has sections
        raw_transactions = []
        lines = csv_content.strip().split('\n')
        
        # Find transaction history section
        transaction_header = None
        for i, line in enumerate(lines):
            if 'Transaction History,Header,' in line:
                parts = line.split(',')
                if len(parts) >= 3:
                    header_fields = parts[2:]
                    transaction_header = header_fields
                break
        
        if not transaction_header:
            logger.warning("No transaction history header found in CSV")
            return {
                'accounts': [],
                'trades': [],
                'raw_transactions': [],
                'fx_rates': {},
                'summary': self._calculate_summary([])
            }
        
        # Parse transaction data rows
        for line in lines:
            if 'Transaction History,Data,' in line:
                parts = line.split(',')
                if len(parts) >= len(transaction_header) + 2:
                    data_values = parts[2:]
                    row = {}
                    for i, header in enumerate(transaction_header):
                        if i < len(data_values):
                            row[header.strip()] = data_values[i].strip()
                    
                    parsed = self._parse_row(row)
                    if parsed:
                        raw_transactions.append(parsed)
                        if parsed.get('account'):
                            self.accounts.add(parsed['account'])
        
        # Extract FX rates
        self._extract_fx_rates(raw_transactions)
        
        # Group and categorize transactions
        trades = self._group_transactions(raw_transactions)
        
        return {
            'accounts': list(self.accounts),
            'trades': trades,
            'raw_transactions': raw_transactions,
            'fx_rates': self.fx_rates,
            'summary': self._calculate_summary(trades)
        }
    
    def _parse_row(self, row: Dict) -> Optional[Dict]:
        """Parse a single CSV row into a transaction"""
        try:
            if not row.get('Date') or row.get('Date') == 'Date':
                return None
            
            transaction_type = row.get('Transaction Type', '').strip()
            if not transaction_type or transaction_type in ['Statement', 'Summary']:
                return None
            
            # Skip FX translations and adjustments for trade parsing
            if transaction_type in ['Adjustment', 'Foreign Tax Withholding']:
                return None
            
            date_str = row.get('Date', '').strip()
            try:
                trade_date = datetime.strptime(date_str, '%Y-%m-%d')
            except ValueError:
                try:
                    trade_date = datetime.strptime(date_str, '%m/%d/%Y')
                except ValueError:
                    return None
            
            symbol = row.get('Symbol', '').strip()
            is_option = False
            option_details = None
            underlying_symbol = symbol
            
            # Check if it's an option symbol
            if symbol and len(symbol) > 6:
                option_details = self._parse_option_symbol(symbol)
                if option_details:
                    is_option = True
                    underlying_symbol = option_details['underlying']
            
            quantity = self._parse_number(row.get('Quantity', '0'))
            price = self._parse_number(row.get('Price', '0'))
            gross_amount = self._parse_number(row.get('Gross Amount', '0'))
            commission = self._parse_number(row.get('Commission', '0'))
            net_amount = self._parse_number(row.get('Net Amount', '0'))
            
            description = row.get('Description', '')
            currency = 'USD'
            if 'AUD' in symbol or 'AUD' in description:
                currency = 'AUD'
            
            # Create deterministic unique ID
            unique_key = f"{row.get('Account', '')}-{date_str}-{symbol}-{transaction_type}-{quantity}-{price}-{gross_amount}"
            tx_id = hashlib.md5(unique_key.encode()).hexdigest()[:16]
            
            return {
                'id': tx_id,
                'date': trade_date.strftime('%Y-%m-%d'),
                'datetime': trade_date.isoformat(),
                'account': row.get('Account', '').strip(),
                'description': description,
                'transaction_type': transaction_type,
                'symbol': symbol,
                'underlying_symbol': underlying_symbol,
                'is_option': is_option,
                'option_details': option_details,
                'quantity': quantity,
                'price': price,
                'gross_amount': gross_amount,
                'commission': abs(commission),
                'net_amount': net_amount,
                'currency': currency
            }
            
        except Exception as e:
            logger.warning(f"Error parsing row: {e}")
            return None
    
    def _parse_option_symbol(self, symbol: str) -> Optional[Dict]:
        """Parse option symbol to extract details.
        
        Handles multiple IBKR formats:
        1. Standard: "IONQ 260123P48500" -> YYMMDD[C/P]STRIKE
        2. Human readable: "IONQ 23JAN26 48.5 P" -> DDMMMYY STRIKE [C/P]
        """
        try:
            symbol = symbol.strip()
            parts = symbol.split()
            if len(parts) < 2:
                return None
            
            underlying = parts[0]
            option_code = ''.join(parts[1:])
            
            # Format 1: Standard IBKR format YYMMDD[C/P]STRIKE (e.g., "260123P48500")
            match = re.match(r'^(\d{6})([CP])(\d+)$', option_code)
            if match:
                date_part, option_type, strike_part = match.groups()
                try:
                    expiry = datetime.strptime(date_part, '%y%m%d')
                    strike = float(strike_part) / 1000
                    return {
                        'underlying': underlying,
                        'expiry': expiry.strftime('%Y-%m-%d'),
                        'option_type': 'Call' if option_type == 'C' else 'Put',
                        'strike': strike
                    }
                except Exception:
                    pass
            
            # Format 2: Human readable format (e.g., "IONQ 23JAN26 48.5 P" or "IONQ 30JAN26 49 C")
            # Pattern: UNDERLYING DDMMMYY STRIKE C/P
            if len(parts) >= 4:
                date_str = parts[1]  # e.g., "23JAN26"
                strike_str = parts[2]  # e.g., "48.5" or "49"
                option_char = parts[3].upper()  # e.g., "P" or "C"
                
                # Try to parse the date
                expiry = None
                for fmt in ['%d%b%y', '%d%B%y']:  # 23JAN26 or 23January26
                    try:
                        expiry = datetime.strptime(date_str.upper(), fmt)
                        break
                    except ValueError:
                        continue
                
                if expiry and option_char in ['C', 'P']:
                    try:
                        strike = float(strike_str)
                        return {
                            'underlying': underlying,
                            'expiry': expiry.strftime('%Y-%m-%d'),
                            'option_type': 'Call' if option_char == 'C' else 'Put',
                            'strike': strike
                        }
                    except ValueError:
                        pass
            
        except Exception as e:
            logger.debug(f"Could not parse option symbol {symbol}: {e}")
        return None
    
    def _parse_number(self, value: str) -> float:
        """Parse a number from string"""
        if not value or value == '-':
            return 0.0
        try:
            cleaned = str(value).replace(',', '').strip()
            return float(cleaned)
        except ValueError:
            return 0.0
    
    def _extract_fx_rates(self, transactions: List[Dict]):
        """Extract FX rates from forex transactions"""
        for tx in transactions:
            if tx.get('transaction_type') == 'Forex Trade Component':
                symbol = tx.get('symbol', '')
                if 'AUD.USD' in symbol:
                    price = tx.get('price', 0)
                    if price > 0:
                        self.fx_rates['AUD_USD'] = price
    
    def _group_transactions(self, transactions: List[Dict]) -> List[Dict]:
        """
        Group related transactions into trades with LIFECYCLE AWARENESS.
        
        =====================================================
        POSITION LIFECYCLE RULES (NON-NEGOTIABLE):
        =====================================================
        
        1. A stock lifecycle STARTS when shares are bought (BUY or PUT ASSIGNMENT)
        2. A stock lifecycle ENDS when ALL shares are sold or call-assigned
        3. Assignment of shares CLOSES the lifecycle
        4. Any subsequent purchase of the same ticker starts a NEW lifecycle
        5. Lifecycles must NOT be merged, even for the same ticker
        6. Each lifecycle gets a unique Position Instance ID
        
        ENTRY PRICE RULE:
        - Entry Price = execution price of the BUY/ASSIGNMENT in THIS lifecycle
        - Do NOT average across historical closed positions
        
        PREMIUM TRACKING:
        - Premiums from previous lifecycles belong to closed positions
        - New lifecycle starts fresh with $0 premium
        """
        trade_types = {'Buy', 'Sell', 'Assignment', 'Exercise', 'Dividend'}
        
        # First, group all transactions by account and underlying symbol
        symbol_groups = {}
        for tx in transactions:
            if tx.get('transaction_type') not in trade_types:
                continue
            key = (tx.get('account', ''), tx.get('underlying_symbol', ''))
            if key not in symbol_groups:
                symbol_groups[key] = []
            symbol_groups[key].append(tx)
        
        trades = []
        for (account, symbol), txs in symbol_groups.items():
            if not symbol or symbol == '-':
                continue
            
            # Sort by datetime to process chronologically
            txs.sort(key=lambda x: x.get('datetime', ''))
            
            # Split into lifecycles
            lifecycles = self._split_into_lifecycles(txs)
            
            # Create a trade for each lifecycle
            for lifecycle_idx, lifecycle_txs in enumerate(lifecycles):
                trade = self._create_trade_from_lifecycle(account, symbol, lifecycle_txs, lifecycle_idx)
                if trade:
                    trades.append(trade)
        
        return trades
    
    def _split_into_lifecycles(self, transactions: List[Dict]) -> List[List[Dict]]:
        """
        Split transactions into separate lifecycles based on position changes.
        
        LIFECYCLE RULES:
        1. A lifecycle ends when all shares are sold or call-assigned (position = 0)
        2. A new lifecycle starts when stock is bought AFTER a position was closed
        
        SPECIAL CASE - WHEEL STRATEGY:
        - CSP (naked put) → Put Assignment → CC is ONE lifecycle
        - The put sale and assignment are part of the same lifecycle
        - Only when CALL assignment closes the position does the lifecycle end
        """
        if not transactions:
            return []
        
        lifecycles = []
        current_lifecycle = []
        current_shares = 0
        has_pending_options = False  # Track if we have options without stock yet (CSP)
        
        for tx in transactions:
            is_option = tx.get('is_option', False)
            tx_type = tx.get('transaction_type', '')
            qty = tx.get('quantity', 0)
            
            if is_option:
                # Options: Check if this is a PUT sell (CSP starting)
                opt_details = tx.get('option_details', {})
                is_put_sell = (tx_type == 'Sell' and opt_details.get('option_type') == 'Put')
                
                if is_put_sell and current_shares == 0 and not current_lifecycle:
                    # Starting a new lifecycle with CSP
                    has_pending_options = True
                
                current_lifecycle.append(tx)
                
            else:
                # Stock transaction
                if tx_type == 'Buy':
                    # Check if this is a new lifecycle (buying after position was FULLY closed)
                    # Key: We DON'T start new lifecycle if we have pending CSP options
                    if current_shares == 0 and current_lifecycle and not has_pending_options:
                        # Position was closed AND no pending CSP, this is a new lifecycle
                        lifecycles.append(current_lifecycle)
                        current_lifecycle = []
                    
                    current_lifecycle.append(tx)
                    current_shares += qty
                    has_pending_options = False  # Clear pending flag as we now have stock
                    
                elif tx_type == 'Sell':
                    current_lifecycle.append(tx)
                    current_shares += qty  # qty is negative for sells
                    
                    # Check if position is now closed
                    if current_shares <= 0:
                        # Position closed via sell
                        lifecycles.append(current_lifecycle)
                        current_lifecycle = []
                        current_shares = 0
                        has_pending_options = False
                        
                elif tx_type == 'Assignment':
                    # Assignment qty: positive = put assigned (you buy), negative = call assigned (you sell)
                    if qty > 0:
                        # Put assignment - you're buying stock
                        # This is PART OF the current lifecycle (CSP → Stock)
                        current_lifecycle.append(tx)
                        current_shares += qty
                        has_pending_options = False  # Now we have actual stock
                        
                    else:
                        # Call assignment - shares being sold/assigned away
                        current_lifecycle.append(tx)
                        current_shares += qty  # qty is negative
                        
                        # Check if position is now closed
                        if current_shares <= 0:
                            # Position closed via call assignment
                            lifecycles.append(current_lifecycle)
                            current_lifecycle = []
                            current_shares = 0
                            has_pending_options = False
        
        # Add any remaining transactions as the final lifecycle
        if current_lifecycle:
            lifecycles.append(current_lifecycle)
        
        return lifecycles
    
    def _create_trade_from_lifecycle(self, account: str, symbol: str, transactions: List[Dict], lifecycle_idx: int = 0) -> Optional[Dict]:
        """
        Create a trade record from a single lifecycle's transactions.
        
        Each lifecycle is isolated:
        - Entry price is based ONLY on buys/assignments in THIS lifecycle
        - Premium is based ONLY on options in THIS lifecycle
        - Metrics are calculated for THIS lifecycle only
        """
        if not transactions:
            return None
        
        transactions.sort(key=lambda x: x.get('datetime', ''))
        
        stock_txs = [t for t in transactions if not t.get('is_option')]
        option_txs = [t for t in transactions if t.get('is_option')]
        
        # Determine strategy type
        strategy = self._determine_strategy(stock_txs, option_txs)
        
        # =====================================================
        # ENTRY PRICE CALCULATION (CRITICAL - LOT-AWARE)
        # =====================================================
        # Entry price must reflect the ACTUAL price paid per share:
        # - For BUY transactions: Use the transaction 'price' field directly
        # - For PUT ASSIGNMENT: Use the put strike price (this is the exercise price)
        # The 'net_amount' includes fees and is NOT the same as entry price * quantity
        
        # Track each lot separately for accurate entry price calculation
        lots = []  # List of (shares, price_per_share) tuples
        total_shares = 0
        total_proceeds = 0  # Track proceeds from sells and call assignments
        
        # First, find put strike if there's a put assignment (for CSP/Wheel)
        put_strike_for_assignment = None
        put_sells = [t for t in option_txs 
                    if t.get('transaction_type') == 'Sell' and 
                    t.get('option_details', {}).get('option_type') == 'Put']
        if put_sells:
            # Get the put strike from the most recent put sell
            put_strike_for_assignment = put_sells[-1].get('option_details', {}).get('strike')
        
        for tx in stock_txs:
            qty = tx.get('quantity', 0)
            tx_type = tx.get('transaction_type', '')
            tx_price = tx.get('price', 0)  # Use the actual transaction price
            
            if tx_type == 'Buy':
                total_shares += qty
                # Use the ACTUAL price from the transaction, NOT net_amount/qty
                if tx_price and tx_price > 0:
                    lots.append((qty, tx_price))
                    
            elif tx_type == 'Sell':
                total_shares += qty  # qty is negative for sells
                total_proceeds += abs(tx.get('net_amount', 0))
                
            elif tx_type == 'Assignment':
                # Assignment qty: positive = put assigned (you buy), negative = call assigned (you sell)
                total_shares += qty
                if qty > 0:
                    # PUT ASSIGNMENT - use the PUT STRIKE as entry price (this is the exercise price)
                    # The put strike is the price at which you're obligated to buy the shares
                    if put_strike_for_assignment:
                        lots.append((qty, put_strike_for_assignment))
                    elif tx_price and tx_price > 0:
                        # Fallback to transaction price if put strike not found
                        lots.append((qty, tx_price))
                else:
                    # Call assignment - your stock was called away
                    total_proceeds += abs(tx.get('net_amount', 0))
        
        total_contracts = sum(abs(t.get('quantity', 0)) for t in option_txs)
        
        # Calculate weighted average entry price from lots
        entry_price = None
        total_cost = 0  # Track cost basis for buys and put assignments
        
        if lots:
            total_lot_shares = sum(lot[0] for lot in lots)
            if total_lot_shares > 0:
                # Weighted average: sum(shares * price) / total_shares
                weighted_sum = sum(lot[0] * lot[1] for lot in lots)
                entry_price = weighted_sum / total_lot_shares
                total_cost = weighted_sum
        
        # Premium calculation - net premium (received - paid)
        # For SELL options: premium received (positive)
        # For BUY options: premium paid (negative from our perspective)
        option_premium_received = sum(abs(t.get('net_amount', 0)) for t in option_txs 
                                     if t.get('transaction_type') == 'Sell')
        option_premium_paid = sum(abs(t.get('net_amount', 0)) for t in option_txs 
                                 if t.get('transaction_type') == 'Buy')
        premium_received = option_premium_received - option_premium_paid
        
        # =====================================================
        # IBKR FEES CALCULATION (from commission field)
        # =====================================================
        # Commission is ALWAYS positive in IBKR CSV, represents fees paid
        total_fees = sum(abs(t.get('commission', 0)) for t in transactions)
        
        # Dates
        first_date = transactions[0].get('date')
        last_date = transactions[-1].get('date')
        
        # Find the latest option expiry for DTE calculation
        option_expiry = None
        option_strike = None
        dte = None
        
        for opt in reversed(option_txs):
            opt_details = opt.get('option_details', {})
            if opt_details and opt_details.get('expiry'):
                option_expiry = opt_details.get('expiry')
                option_strike = opt_details.get('strike')
                break
        
        if option_expiry:
            try:
                exp_date = datetime.strptime(option_expiry, '%Y-%m-%d')
                dte = max(0, (exp_date - datetime.now()).days)
            except:
                pass
        
        # Determine status - Only "Open" if you still hold shares
        # Stocks with negative shares are NOT real open positions
        status = 'Open'
        date_closed = None
        close_reason = None
        
        # Check if there was any assignment
        has_call_assignment = any(t.get('transaction_type') == 'Assignment' and t.get('quantity', 0) < 0 for t in stock_txs)
        has_put_assignment = any(t.get('transaction_type') == 'Assignment' and t.get('quantity', 0) > 0 for t in stock_txs)
        
        # Position is closed if no shares remain
        if total_shares == 0:
            status = 'Closed'
            if has_call_assignment:
                close_reason = 'Assigned'
            elif total_proceeds > 0:
                close_reason = 'Sold'
            elif option_expiry:
                try:
                    exp_date = datetime.strptime(option_expiry, '%Y-%m-%d')
                    if exp_date < datetime.now():
                        close_reason = 'Expired'
                except:
                    pass
            date_closed = last_date
        elif total_shares < 0:
            # Negative shares - this indicates an error or short position
            # Mark as closed for now, with a note
            status = 'Closed'
            close_reason = 'Short/Error'
            date_closed = last_date
        # If total_shares > 0, position is Open
        
        # For NAKED_PUT without stock yet, check if expired
        if strategy == 'NAKED_PUT' and total_shares == 0 and not has_put_assignment:
            if option_expiry:
                try:
                    exp_date = datetime.strptime(option_expiry, '%Y-%m-%d')
                    if exp_date < datetime.now():
                        status = 'Closed'
                        close_reason = 'Expired'
                        date_closed = option_expiry
                except:
                    pass
        
        # Calculate days in trade
        days_in_trade = 0
        if first_date:
            try:
                d1 = datetime.strptime(first_date, '%Y-%m-%d')
                d2 = datetime.strptime(date_closed, '%Y-%m-%d') if date_closed else datetime.now()
                days_in_trade = (d2 - d1).days
            except:
                pass
        
        # =====================================================
        # BREAK-EVEN CALCULATION (STRATEGY-AWARE)
        # =====================================================
        # BE depends on strategy type:
        # - CSP: "Effective Entry" = Put Strike - Put Premium
        # - CC: Lot BE = Entry Price - (Call Premiums / shares)
        # - Stock only: Entry Price + Fees per share
        break_even = None
        
        if total_shares > 0 and entry_price and entry_price > 0:
            # Premium per share (premiums collected reduce break-even)
            premium_per_share = premium_received / total_shares if total_shares > 0 else 0
            # Fees per share (fees increase break-even)
            fees_per_share = total_fees / total_shares if total_shares > 0 else 0
            
            # Break-even = Entry Price - Premium received per share + Fees per share
            break_even = entry_price - premium_per_share + fees_per_share
        
        # For CSP (NAKED_PUT), break-even is Strike - Premium
        if strategy == 'NAKED_PUT' and put_strike_for_assignment and premium_received > 0:
            # CSP BE = Put Strike - Put Premium per share
            # Premium is total, so divide by (strike * contracts) to get per-share equivalent
            if total_contracts > 0:
                premium_per_share = premium_received / (total_contracts * 100)
                break_even = put_strike_for_assignment - premium_per_share
        
        # =====================================================
        # ROI CALCULATION
        # =====================================================
        realized_pnl = None
        roi = None
        
        if status == 'Closed' and total_cost > 0:
            # Realized P/L = Proceeds from selling stock + Net option premium - Cost - Fees
            realized_pnl = total_proceeds + premium_received - total_cost - total_fees
            roi = (realized_pnl / total_cost) * 100
        elif status == 'Closed' and total_cost == 0 and premium_received > 0:
            # Pure option play (e.g., naked put that expired worthless)
            realized_pnl = premium_received - total_fees
            # ROI on naked put is based on capital at risk (strike * 100 * contracts)
            if put_strike_for_assignment and total_contracts > 0:
                capital_at_risk = put_strike_for_assignment * total_contracts * 100
                roi = (realized_pnl / capital_at_risk) * 100
        
        # Store put strike for reference (for CSP → CC transitions)
        csp_put_strike = put_strike_for_assignment
        
        # =====================================================
        # POSITION INSTANCE ID (Lifecycle Tracking)
        # =====================================================
        # Each lifecycle gets a unique ID, even for the same ticker
        # Format: {SYMBOL}-{YYYY-MM}-Entry-{NN}
        # Example: IREN-2024-05-Entry-01
        
        # Create Position Instance ID based on the lifecycle's first transaction date
        if first_date:
            date_part = first_date[:7]  # YYYY-MM
        else:
            date_part = datetime.now().strftime('%Y-%m')
        
        position_instance_id = f"{symbol}-{date_part}-Entry-{lifecycle_idx + 1:02d}"
        
        # Create deterministic trade ID that includes lifecycle index
        trade_unique_key = f"{account}-{symbol}-{first_date or 'unknown'}-lifecycle{lifecycle_idx}"
        trade_id = hashlib.md5(trade_unique_key.encode()).hexdigest()[:16]
        
        return {
            'id': trade_id,
            'position_instance_id': position_instance_id,  # New: Unique lifecycle identifier
            'lifecycle_index': lifecycle_idx,  # New: Index of this lifecycle for the symbol
            'trade_id': transactions[0].get('id'),
            'account': account,
            'symbol': symbol,
            'strategy_type': strategy,
            'strategy_label': STRATEGY_TYPES.get(strategy, strategy),
            'date_opened': first_date,
            'date_closed': date_closed,
            'close_reason': close_reason,
            'days_in_trade': days_in_trade,
            'dte': dte,
            'status': status,
            'shares': int(total_shares),
            'contracts': int(total_contracts),
            'entry_price': round(entry_price, 2) if entry_price else None,
            'premium_received': round(premium_received, 2),
            'total_fees': round(total_fees, 2),
            'break_even': round(break_even, 2) if break_even else None,
            'option_strike': option_strike,
            'option_expiry': option_expiry,
            'csp_put_strike': csp_put_strike,
            'total_proceeds': round(total_proceeds, 2),
            'total_cost': round(total_cost, 2),
            'realized_pnl': round(realized_pnl, 2) if realized_pnl is not None else None,
            'roi': round(roi, 2) if roi is not None else None,
            'transactions': transactions,
            'current_price': None,
            'unrealized_pnl': None,
            'created_at': datetime.now(timezone.utc).isoformat()
        }
    
    def _determine_strategy(self, stock_txs: List[Dict], option_txs: List[Dict]) -> str:
        """Determine the trading strategy from transactions"""
        has_stock_buy = any(t.get('transaction_type') == 'Buy' for t in stock_txs)
        has_stock_sell = any(t.get('transaction_type') == 'Sell' for t in stock_txs)
        has_put_assignment = any(t.get('transaction_type') == 'Assignment' and t.get('quantity', 0) > 0 for t in stock_txs)
        has_call_assignment = any(t.get('transaction_type') == 'Assignment' and t.get('quantity', 0) < 0 for t in stock_txs)
        
        # Check if user owns stock (bought or got assigned via put)
        has_stock = has_stock_buy or has_put_assignment
        
        # Categorize options
        call_sells = [t for t in option_txs 
                     if t.get('transaction_type') == 'Sell' and t.get('option_details', {}).get('option_type') == 'Call']
        put_sells = [t for t in option_txs 
                    if t.get('transaction_type') == 'Sell' and t.get('option_details', {}).get('option_type') == 'Put']
        call_buys = [t for t in option_txs 
                    if t.get('transaction_type') == 'Buy' and t.get('option_details', {}).get('option_type') == 'Call']
        put_buys = [t for t in option_txs 
                   if t.get('transaction_type') == 'Buy' and t.get('option_details', {}).get('option_type') == 'Put']
        
        # Determine strategy
        if has_stock:
            if call_sells and put_buys:
                return 'COLLAR'
            elif call_sells:
                return 'COVERED_CALL'
            else:
                # Pure stock - check if ETF or Index
                symbol = stock_txs[0].get('underlying_symbol', '') if stock_txs else ''
                if symbol in ETF_SYMBOLS:
                    return 'ETF'
                elif symbol in INDEX_SYMBOLS:
                    return 'INDEX'
                return 'STOCK'
        elif has_stock_sell and not has_stock_buy:
            # Just sold stock (maybe from assignment or transfer)
            symbol = stock_txs[0].get('underlying_symbol', '') if stock_txs else ''
            if symbol in ETF_SYMBOLS:
                return 'ETF'
            return 'STOCK'
        else:
            # Options only
            if call_buys and call_sells:
                return 'PMCC'
            elif put_sells and not put_buys:
                return 'NAKED_PUT'
            elif call_sells or put_sells or call_buys or put_buys:
                return 'OPTION'
        
        return 'STOCK'  # Default to STOCK instead of OTHER
    
    def _calculate_summary(self, trades: List[Dict]) -> Dict:
        """Calculate portfolio summary statistics"""
        total_invested = 0
        total_premium = 0
        total_fees = 0
        open_trades = 0
        closed_trades = 0
        total_realized_pnl = 0
        
        by_strategy = {}
        by_account = {}
        
        for trade in trades:
            strategy = trade.get('strategy_type', 'OTHER')
            account = trade.get('account', 'Unknown')
            
            if strategy not in by_strategy:
                by_strategy[strategy] = {'count': 0, 'premium': 0, 'invested': 0}
            by_strategy[strategy]['count'] += 1
            by_strategy[strategy]['premium'] += trade.get('premium_received', 0)
            
            if account not in by_account:
                by_account[account] = {'count': 0, 'invested': 0}
            by_account[account]['count'] += 1
            
            total_cost = trade.get('total_cost', 0)
            by_strategy[strategy]['invested'] += total_cost
            
            total_invested += total_cost
            total_premium += trade.get('premium_received', 0)
            total_fees += trade.get('total_fees', 0)
            
            if trade.get('realized_pnl') is not None:
                total_realized_pnl += trade.get('realized_pnl', 0)
            
            if trade.get('status') == 'Open':
                open_trades += 1
            else:
                closed_trades += 1
        
        return {
            'total_trades': len(trades),
            'open_trades': open_trades,
            'closed_trades': closed_trades,
            'total_invested': round(total_invested, 2),
            'total_premium': round(total_premium, 2),
            'total_fees': round(total_fees, 2),
            'net_premium': round(total_premium - total_fees, 2),
            'total_realized_pnl': round(total_realized_pnl, 2),
            'by_strategy': by_strategy,
            'by_account': by_account
        }


def parse_ibkr_csv(csv_content: str) -> Dict:
    """Convenience function to parse IBKR CSV"""
    parser = IBKRParser()
    return parser.parse_csv(csv_content)
