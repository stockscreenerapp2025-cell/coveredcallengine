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
        """Parse option symbol to extract details"""
        try:
            symbol = symbol.strip()
            parts = symbol.split()
            if len(parts) >= 2:
                underlying = parts[0]
                option_code = ''.join(parts[1:])
                
                # Match pattern: YYMMDD[C/P]STRIKE
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
                    except:
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
        """Group related transactions into trades"""
        trade_types = {'Buy', 'Sell', 'Assignment', 'Exercise', 'Dividend'}
        
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
            trade = self._create_trade_from_transactions(account, symbol, txs)
            if trade:
                trades.append(trade)
        
        return trades
    
    def _create_trade_from_transactions(self, account: str, symbol: str, transactions: List[Dict]) -> Optional[Dict]:
        """Create a trade record from related transactions"""
        if not transactions:
            return None
        
        transactions.sort(key=lambda x: x.get('datetime', ''))
        
        stock_txs = [t for t in transactions if not t.get('is_option')]
        option_txs = [t for t in transactions if t.get('is_option')]
        
        # Determine strategy type
        strategy = self._determine_strategy(stock_txs, option_txs)
        
        # Calculate stock positions correctly
        # Positive quantity = adding to position (buy, put assignment)
        # Negative quantity = reducing position (sell, call assignment)
        total_shares = 0
        total_cost = 0  # Track cost basis for buys and put assignments
        total_proceeds = 0  # Track proceeds from sells and call assignments
        
        for tx in stock_txs:
            qty = tx.get('quantity', 0)
            net_amount = tx.get('net_amount', 0)
            tx_type = tx.get('transaction_type', '')
            
            if tx_type == 'Buy':
                total_shares += qty
                total_cost += abs(net_amount)
            elif tx_type == 'Sell':
                total_shares += qty  # qty is negative for sells
                total_proceeds += abs(net_amount)
            elif tx_type == 'Assignment':
                # Assignment qty: positive = put assigned (you buy), negative = call assigned (you sell)
                total_shares += qty
                if qty > 0:
                    # Put assignment - you bought stock
                    total_cost += abs(net_amount)
                else:
                    # Call assignment - your stock was called away
                    total_proceeds += abs(net_amount)
        
        total_contracts = sum(abs(t.get('quantity', 0)) for t in option_txs)
        
        # Calculate entry price (average cost basis per share)
        entry_price = None
        if total_shares > 0 and total_cost > 0:
            # Count shares that contributed to cost (buys + put assignments)
            cost_shares = sum(t.get('quantity', 0) for t in stock_txs 
                            if t.get('transaction_type') == 'Buy' or 
                            (t.get('transaction_type') == 'Assignment' and t.get('quantity', 0) > 0))
            if cost_shares > 0:
                entry_price = total_cost / cost_shares
        
        # Premium calculation - net premium (received - paid)
        option_premium_received = sum(abs(t.get('net_amount', 0)) for t in option_txs 
                                     if t.get('transaction_type') == 'Sell')
        option_premium_paid = sum(abs(t.get('net_amount', 0)) for t in option_txs 
                                 if t.get('transaction_type') == 'Buy')
        premium_received = option_premium_received - option_premium_paid
        
        # Total fees
        total_fees = sum(t.get('commission', 0) for t in transactions)
        
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
        
        # Calculate break-even (for positions with stock)
        break_even = None
        if total_shares > 0 and entry_price and entry_price > 0:
            premium_per_share = premium_received / total_shares if total_shares > 0 else 0
            fees_per_share = total_fees / total_shares if total_shares > 0 else 0
            break_even = entry_price - premium_per_share + fees_per_share
        
        # Calculate realized P/L for closed positions
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
            # For simplicity, just show P/L without ROI
        
        # Create deterministic trade ID
        trade_unique_key = f"{account}-{symbol}"
        trade_id = hashlib.md5(trade_unique_key.encode()).hexdigest()[:16]
        
        return {
            'id': trade_id,
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
            'entry_price': round(entry_price, 4) if entry_price else None,
            'premium_received': round(premium_received, 2),
            'total_fees': round(total_fees, 2),
            'break_even': round(break_even, 4) if break_even else None,
            'option_strike': option_strike,
            'option_expiry': option_expiry,
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
