"""
IBKR CSV Parser Service for Covered Call Engine
Parses Interactive Brokers transaction history and categorizes trading strategies
"""

import csv
import re
import io
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

# Common ETF symbols
ETF_SYMBOLS = {
    'SPY', 'QQQ', 'IWM', 'DIA', 'VTI', 'VOO', 'VXX', 'GLD', 'SLV', 'USO',
    'XLF', 'XLE', 'XLK', 'XLV', 'XLI', 'XLP', 'XLY', 'XLB', 'XLU', 'XLRE',
    'EEM', 'EFA', 'VWO', 'VEA', 'IEMG', 'AGG', 'BND', 'LQD', 'HYG', 'TLT',
    'IEF', 'SHY', 'ARKK', 'ARKG', 'ARKW', 'ARKF', 'ARKQ', 'SOXL', 'TQQQ',
    'SPXL', 'UPRO', 'SQQQ', 'SDOW', 'UVXY', 'VIXY', 'VIG', 'VYM', 'SCHD'
}

# Index symbols
INDEX_SYMBOLS = {'SPX', 'NDX', 'RUT', 'VIX', 'DJX'}


class IBKRParser:
    """Parser for Interactive Brokers CSV transaction files"""
    
    def __init__(self):
        self.transactions = []
        self.accounts = set()
        self.fx_rates = {}  # Store FX rates for conversion
        
    def parse_csv(self, csv_content: str) -> Dict:
        """
        Parse IBKR CSV content and return structured data
        
        Args:
            csv_content: Raw CSV content as string
            
        Returns:
            Dictionary with parsed transactions, accounts, and summary
        """
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
                # Extract header fields
                parts = line.split(',')
                if len(parts) >= 3:
                    header_fields = parts[2:]  # Skip "Transaction History,Header,"
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
                if len(parts) >= len(transaction_header) + 2:  # +2 for "Transaction History,Data,"
                    data_values = parts[2:]  # Skip "Transaction History,Data,"
                    
                    # Create row dict
                    row = {}
                    for i, header in enumerate(transaction_header):
                        if i < len(data_values):
                            row[header.strip()] = data_values[i].strip()
                    
                    parsed = self._parse_row(row)
                    if parsed:
                        raw_transactions.append(parsed)
                        if parsed.get('account'):
                            self.accounts.add(parsed['account'])
        
        # Extract FX rates from forex transactions
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
            # Skip empty rows or header rows
            if not row.get('Date') or row.get('Date') == 'Date':
                return None
            
            # Skip summary/statement rows
            transaction_type = row.get('Transaction Type', '').strip()
            if not transaction_type or transaction_type in ['Statement', 'Summary']:
                return None
            
            # Parse date
            date_str = row.get('Date', '').strip()
            try:
                trade_date = datetime.strptime(date_str, '%Y-%m-%d')
            except ValueError:
                try:
                    trade_date = datetime.strptime(date_str, '%m/%d/%Y')
                except ValueError:
                    return None
            
            # Parse symbol and detect if it's an option
            symbol = row.get('Symbol', '').strip()
            is_option = False
            option_details = None
            underlying_symbol = symbol
            
            if symbol and len(symbol) > 10 and ('C' in symbol or 'P' in symbol):
                # This looks like an option symbol (e.g., "APLD  260109C00031000")
                option_details = self._parse_option_symbol(symbol)
                if option_details:
                    is_option = True
                    underlying_symbol = option_details['underlying']
            
            # Parse quantities and amounts
            quantity = self._parse_number(row.get('Quantity', '0'))
            price = self._parse_number(row.get('Price', '0'))
            gross_amount = self._parse_number(row.get('Gross Amount', '0'))
            commission = self._parse_number(row.get('Commission', '0'))
            net_amount = self._parse_number(row.get('Net Amount', '0'))
            
            # Determine currency from description or symbol
            description = row.get('Description', '')
            currency = 'USD'
            if 'AUD' in symbol or 'AUD' in description:
                currency = 'AUD'
            
            return {
                'id': str(uuid4()),
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
                'commission': abs(commission),  # Store as positive
                'net_amount': net_amount,
                'currency': currency
            }
            
        except Exception as e:
            logger.warning(f"Error parsing row: {e}")
            return None
    
    def _parse_option_symbol(self, symbol: str) -> Optional[Dict]:
        """
        Parse option symbol to extract details
        Format: UNDERLYING YYMMDDCP00STRIKE000
        Example: APLD  260109C00031000 -> APLD, 2026-01-09, Call, $31
        """
        try:
            # Clean up symbol
            symbol = symbol.strip()
            
            # Try to match option pattern
            # Pattern: SYMBOL YYMMDD[C/P]STRIKE
            match = re.match(r'^(\w+)\s+(\d{6})([CP])(\d+)$', symbol.replace(' ', ''))
            if not match:
                # Try alternative pattern with spaces
                parts = symbol.split()
                if len(parts) >= 2:
                    underlying = parts[0]
                    option_code = parts[-1] if len(parts[-1]) > 6 else ''.join(parts[1:])
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
            else:
                underlying, date_part, option_type, strike_part = match.groups()
                expiry = datetime.strptime(date_part, '%y%m%d')
                strike = float(strike_part) / 1000
                return {
                    'underlying': underlying,
                    'expiry': expiry.strftime('%Y-%m-%d'),
                    'option_type': 'Call' if option_type == 'C' else 'Put',
                    'strike': strike
                }
        except Exception as e:
            logger.debug(f"Could not parse option symbol {symbol}: {e}")
        
        return None
    
    def _parse_number(self, value: str) -> float:
        """Parse a number from string, handling various formats"""
        if not value or value == '-':
            return 0.0
        try:
            # Remove commas and convert
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
        Group related transactions into trades and categorize strategies
        """
        # Filter out non-trade transactions
        trade_types = {'Buy', 'Sell', 'Assignment', 'Exercise'}
        
        # Group by underlying symbol and account
        symbol_groups = {}
        
        for tx in transactions:
            if tx.get('transaction_type') not in trade_types:
                continue
                
            key = (tx.get('account', ''), tx.get('underlying_symbol', ''))
            if key not in symbol_groups:
                symbol_groups[key] = []
            symbol_groups[key].append(tx)
        
        # Create trades from groups
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
        
        # Sort by date
        transactions.sort(key=lambda x: x.get('datetime', ''))
        
        # Separate stock and option transactions
        stock_txs = [t for t in transactions if not t.get('is_option')]
        option_txs = [t for t in transactions if t.get('is_option')]
        
        # Determine strategy type
        strategy = self._determine_strategy(stock_txs, option_txs)
        
        # Calculate aggregates
        total_shares = sum(t.get('quantity', 0) for t in stock_txs if t.get('transaction_type') == 'Buy')
        total_shares -= sum(abs(t.get('quantity', 0)) for t in stock_txs if t.get('transaction_type') == 'Sell')
        
        total_contracts = sum(abs(t.get('quantity', 0)) for t in option_txs)
        
        # Entry price (average)
        buy_txs = [t for t in stock_txs if t.get('transaction_type') == 'Buy']
        entry_price = 0
        if buy_txs:
            total_cost = sum(abs(t.get('gross_amount', 0)) for t in buy_txs)
            total_qty = sum(t.get('quantity', 0) for t in buy_txs)
            if total_qty > 0:
                entry_price = total_cost / total_qty
        
        # Premium received (from selling options)
        sell_options = [t for t in option_txs if t.get('transaction_type') == 'Sell']
        premium_received = sum(t.get('gross_amount', 0) for t in sell_options)
        
        # Total fees
        total_fees = sum(t.get('commission', 0) for t in transactions)
        
        # Dates
        first_date = transactions[0].get('date')
        last_date = transactions[-1].get('date')
        
        # Determine status - improved logic
        status = 'Open'
        
        # Check for assignment first
        if any(t.get('transaction_type') == 'Assignment' for t in transactions):
            status = 'Assigned'
        else:
            # Calculate net position from all stock transactions
            total_bought = sum(t.get('quantity', 0) for t in stock_txs if t.get('transaction_type') == 'Buy')
            total_sold = sum(abs(t.get('quantity', 0)) for t in stock_txs if t.get('transaction_type') == 'Sell')
            
            # For stocks: closed if sold all shares
            if total_bought > 0 and total_sold >= total_bought:
                status = 'Closed'
            # For pure options trades without stock
            elif not stock_txs and option_txs:
                # Check if all options have been bought back or expired
                calls_sold = sum(abs(t.get('quantity', 0)) for t in option_txs 
                               if t.get('transaction_type') == 'Sell' and t.get('option_details', {}).get('option_type') == 'Call')
                calls_bought = sum(t.get('quantity', 0) for t in option_txs 
                                 if t.get('transaction_type') == 'Buy' and t.get('option_details', {}).get('option_type') == 'Call')
                puts_sold = sum(abs(t.get('quantity', 0)) for t in option_txs 
                              if t.get('transaction_type') == 'Sell' and t.get('option_details', {}).get('option_type') == 'Put')
                puts_bought = sum(t.get('quantity', 0) for t in option_txs 
                                if t.get('transaction_type') == 'Buy' and t.get('option_details', {}).get('option_type') == 'Put')
                
                net_calls = calls_sold - calls_bought
                net_puts = puts_sold - puts_bought
                
                if net_calls == 0 and net_puts == 0:
                    status = 'Closed'
            # For covered calls/PMCC: check if shares are gone
            elif total_shares <= 0 and total_bought > 0:
                status = 'Closed'
        
        # Calculate days in trade
        days_in_trade = 0
        if first_date and last_date:
            try:
                d1 = datetime.strptime(first_date, '%Y-%m-%d')
                d2 = datetime.strptime(last_date, '%Y-%m-%d')
                days_in_trade = (d2 - d1).days
            except:
                pass
        
        # Get option details for DTE calculation
        dte = None
        option_strike = None
        option_expiry = None
        if option_txs:
            latest_option = option_txs[-1]
            opt_details = latest_option.get('option_details', {})
            if opt_details:
                option_strike = opt_details.get('strike')
                option_expiry = opt_details.get('expiry')
                if option_expiry:
                    try:
                        exp_date = datetime.strptime(option_expiry, '%Y-%m-%d')
                        dte = (exp_date - datetime.now()).days
                        if dte < 0:
                            dte = 0
                    except:
                        pass
        
        # Calculate break-even
        break_even = entry_price - (premium_received / max(total_shares, 100)) + (total_fees / max(total_shares, 100)) if total_shares > 0 else entry_price
        
        return {
            'id': str(uuid4()),
            'trade_id': transactions[0].get('id'),  # Use first transaction ID as trade reference
            'account': account,
            'symbol': symbol,
            'strategy_type': strategy,
            'strategy_label': STRATEGY_TYPES.get(strategy, strategy),
            'date_opened': first_date,
            'date_closed': last_date if status == 'Closed' else None,
            'days_in_trade': days_in_trade,
            'dte': dte,
            'status': status,
            'shares': int(total_shares),
            'contracts': int(total_contracts),
            'entry_price': round(entry_price, 4),
            'premium_received': round(premium_received, 2),
            'total_fees': round(total_fees, 2),
            'break_even': round(break_even, 4),
            'option_strike': option_strike,
            'option_expiry': option_expiry,
            'transactions': transactions,
            'current_price': None,  # To be filled by market data
            'unrealized_pnl': None,
            'roi': None,
            'created_at': datetime.now(timezone.utc).isoformat()
        }
    
    def _determine_strategy(self, stock_txs: List[Dict], option_txs: List[Dict]) -> str:
        """Determine the trading strategy from transactions"""
        has_stock = any(t.get('transaction_type') == 'Buy' for t in stock_txs)
        
        # Categorize options
        call_buys = []
        call_sells = []
        put_buys = []
        put_sells = []
        
        for opt in option_txs:
            opt_details = opt.get('option_details', {})
            opt_type = opt_details.get('option_type', '')
            tx_type = opt.get('transaction_type', '')
            
            if opt_type == 'Call':
                if tx_type == 'Buy':
                    call_buys.append(opt)
                elif tx_type == 'Sell':
                    call_sells.append(opt)
            elif opt_type == 'Put':
                if tx_type == 'Buy':
                    put_buys.append(opt)
                elif tx_type == 'Sell':
                    put_sells.append(opt)
        
        # Determine strategy
        if has_stock:
            if call_sells and put_buys:
                return 'COLLAR'
            elif call_sells:
                return 'COVERED_CALL'
            else:
                # Check if it's an ETF or Index
                symbol = stock_txs[0].get('underlying_symbol', '') if stock_txs else ''
                if symbol in ETF_SYMBOLS:
                    return 'ETF'
                elif symbol in INDEX_SYMBOLS:
                    return 'INDEX'
                return 'STOCK'
        else:
            if call_buys and call_sells:
                # Check if it's a PMCC (long-dated buy, short-dated sell)
                return 'PMCC'
            elif put_sells and not put_buys:
                return 'NAKED_PUT'
            elif option_txs:
                return 'OPTION'
        
        return 'OTHER'
    
    def _calculate_summary(self, trades: List[Dict]) -> Dict:
        """Calculate portfolio summary statistics"""
        total_invested = 0
        total_premium = 0
        total_fees = 0
        open_trades = 0
        closed_trades = 0
        
        by_strategy = {}
        by_account = {}
        
        for trade in trades:
            strategy = trade.get('strategy_type', 'OTHER')
            account = trade.get('account', 'Unknown')
            
            # Aggregate by strategy
            if strategy not in by_strategy:
                by_strategy[strategy] = {'count': 0, 'premium': 0}
            by_strategy[strategy]['count'] += 1
            by_strategy[strategy]['premium'] += trade.get('premium_received', 0)
            
            # Aggregate by account
            if account not in by_account:
                by_account[account] = {'count': 0, 'invested': 0}
            by_account[account]['count'] += 1
            
            # Totals
            shares = trade.get('shares', 0)
            entry = trade.get('entry_price', 0)
            total_invested += shares * entry
            total_premium += trade.get('premium_received', 0)
            total_fees += trade.get('total_fees', 0)
            
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
            'by_strategy': by_strategy,
            'by_account': by_account
        }


def parse_ibkr_csv(csv_content: str) -> Dict:
    """Convenience function to parse IBKR CSV"""
    parser = IBKRParser()
    return parser.parse_csv(csv_content)
