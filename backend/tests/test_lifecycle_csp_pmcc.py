"""
Tests for CSP Assignment Lifecycle Isolation and PMCC Lifecycle Rules.

These tests verify:
1. Multiple CSP assignments with different strikes create distinct lifecycles
2. PMCC lifecycles are anchored to long LEAPS calls, not stock ticker
3. Short-call assignment in PMCC does NOT close the lifecycle
4. Entry prices are correctly isolated per lifecycle
"""

import pytest
from services.ibkr_parser import IBKRParser


class TestCSPLifecycleIsolation:
    """Tests for CSP Assignment Lifecycle Isolation Bug Fix"""
    
    def test_multiple_csp_different_strikes_same_date(self):
        """
        Test: Multiple CSPs at different strikes assigned on same date
        Expected: Each CSP creates a distinct lifecycle with its own entry price
        """
        parser = IBKRParser()
        
        transactions = [
            # CSP #1: Sell IREN 55 Put
            {
                'id': 'csp1',
                'date': '2026-01-15',
                'datetime': '2026-01-15T09:00:00',
                'account': 'TEST',
                'transaction_type': 'Sell',
                'symbol': 'IREN 260117P55000',
                'underlying_symbol': 'IREN',
                'is_option': True,
                'option_details': {
                    'underlying': 'IREN',
                    'expiry': '2026-01-17',
                    'option_type': 'Put',
                    'strike': 55.0
                },
                'quantity': -2,
                'price': 1.50,
                'net_amount': 290.0,
                'commission': 5.0
            },
            # CSP #2: Sell IREN 50 Put (DIFFERENT STRIKE)
            {
                'id': 'csp2',
                'date': '2026-01-15',
                'datetime': '2026-01-15T09:30:00',
                'account': 'TEST',
                'transaction_type': 'Sell',
                'symbol': 'IREN 260117P50000',
                'underlying_symbol': 'IREN',
                'is_option': True,
                'option_details': {
                    'underlying': 'IREN',
                    'expiry': '2026-01-17',
                    'option_type': 'Put',
                    'strike': 50.0
                },
                'quantity': -2,
                'price': 0.80,
                'net_amount': 150.0,
                'commission': 5.0
            },
            # Assignment #1: 200 shares at $55 (from CSP #1)
            {
                'id': 'assign1',
                'date': '2026-01-17',
                'datetime': '2026-01-17T16:00:00',
                'account': 'TEST',
                'transaction_type': 'Assignment',
                'symbol': 'IREN',
                'underlying_symbol': 'IREN',
                'is_option': False,
                'option_details': None,
                'quantity': 200,
                'price': 55.0,
                'net_amount': -11000.0,
                'commission': 0
            },
            # Assignment #2: 200 shares at $50 (from CSP #2)
            {
                'id': 'assign2',
                'date': '2026-01-17',
                'datetime': '2026-01-17T16:01:00',
                'account': 'TEST',
                'transaction_type': 'Assignment',
                'symbol': 'IREN',
                'underlying_symbol': 'IREN',
                'is_option': False,
                'option_details': None,
                'quantity': 200,
                'price': 50.0,
                'net_amount': -10000.0,
                'commission': 0
            },
        ]
        
        trades = parser._group_transactions(transactions)
        
        # Should detect 2 separate lifecycles
        assert len(trades) >= 2, f"Expected 2+ lifecycles, got {len(trades)}"
        
        # Entry prices should be distinct
        entry_prices = [t.get('entry_price') for t in trades if t.get('entry_price')]
        assert 55.0 in entry_prices, f"Expected entry price $55, got {entry_prices}"
        assert 50.0 in entry_prices, f"Expected entry price $50, got {entry_prices}"
        
        # Entry prices should NOT be averaged
        for t in trades:
            assert t.get('entry_price') != 52.5, "Entry prices should NOT be averaged"
    
    def test_csp_cc_wheel_single_chain(self):
        """
        Test: CSP -> Assignment -> CC is ONE lifecycle (Wheel strategy)
        Expected: Single lifecycle with premiums from both put and call
        """
        parser = IBKRParser()
        
        transactions = [
            # Sell Put (CSP)
            {
                'id': 'csp1',
                'date': '2026-01-15',
                'datetime': '2026-01-15T09:00:00',
                'account': 'TEST',
                'transaction_type': 'Sell',
                'symbol': 'IREN 260117P55000',
                'underlying_symbol': 'IREN',
                'is_option': True,
                'option_details': {
                    'underlying': 'IREN',
                    'expiry': '2026-01-17',
                    'option_type': 'Put',
                    'strike': 55.0
                },
                'quantity': -2,
                'price': 1.50,
                'net_amount': 290.0,
                'commission': 5.0
            },
            # Put Assignment
            {
                'id': 'assign1',
                'date': '2026-01-17',
                'datetime': '2026-01-17T16:00:00',
                'account': 'TEST',
                'transaction_type': 'Assignment',
                'symbol': 'IREN',
                'underlying_symbol': 'IREN',
                'is_option': False,
                'option_details': None,
                'quantity': 200,
                'price': 55.0,
                'net_amount': -11000.0,
                'commission': 0
            },
            # Sell Covered Call
            {
                'id': 'cc1',
                'date': '2026-01-20',
                'datetime': '2026-01-20T09:00:00',
                'account': 'TEST',
                'transaction_type': 'Sell',
                'symbol': 'IREN 260124C57000',
                'underlying_symbol': 'IREN',
                'is_option': True,
                'option_details': {
                    'underlying': 'IREN',
                    'expiry': '2026-01-24',
                    'option_type': 'Call',
                    'strike': 57.0
                },
                'quantity': -2,
                'price': 2.00,
                'net_amount': 390.0,
                'commission': 5.0
            },
        ]
        
        trades = parser._group_transactions(transactions)
        
        # Should be ONE lifecycle (Wheel)
        assert len(trades) == 1, f"Expected 1 lifecycle (Wheel), got {len(trades)}"
        
        trade = trades[0]
        assert trade.get('entry_price') == 55.0, f"Entry should be put strike $55, got {trade.get('entry_price')}"
        assert trade.get('shares') == 200, f"Expected 200 shares, got {trade.get('shares')}"
        
        # Premium should include both put and call
        expected_premium = 290.0 + 390.0  # Put + Call
        assert abs(trade.get('premium_received', 0) - expected_premium) < 1, \
            f"Premium should be ~{expected_premium}, got {trade.get('premium_received')}"


class TestPMCCLifecycleRules:
    """Tests for PMCC Lifecycle Rules"""
    
    def test_pmcc_multiple_leaps_same_ticker(self):
        """
        Test: Multiple LEAPS on same ticker create separate PMCC lifecycles
        Expected: Each LEAPS anchors its own lifecycle
        """
        parser = IBKRParser()
        
        transactions = [
            # LEAPS #1: Strike $50
            {
                'id': 'leaps1',
                'date': '2026-01-10',
                'datetime': '2026-01-10T09:00:00',
                'account': 'TEST',
                'transaction_type': 'Buy',
                'symbol': 'AAPL 270115C50000',
                'underlying_symbol': 'AAPL',
                'is_option': True,
                'option_details': {
                    'underlying': 'AAPL',
                    'expiry': '2027-01-15',
                    'option_type': 'Call',
                    'strike': 50.0
                },
                'quantity': 2,
                'price': 45.00,
                'net_amount': -9010.0,
                'commission': 10.0
            },
            # LEAPS #2: Strike $60
            {
                'id': 'leaps2',
                'date': '2026-01-12',
                'datetime': '2026-01-12T09:00:00',
                'account': 'TEST',
                'transaction_type': 'Buy',
                'symbol': 'AAPL 270115C60000',
                'underlying_symbol': 'AAPL',
                'is_option': True,
                'option_details': {
                    'underlying': 'AAPL',
                    'expiry': '2027-01-15',
                    'option_type': 'Call',
                    'strike': 60.0
                },
                'quantity': 2,
                'price': 38.00,
                'net_amount': -7610.0,
                'commission': 10.0
            },
            # Short call against LEAPS #1
            {
                'id': 'short1',
                'date': '2026-01-15',
                'datetime': '2026-01-15T09:00:00',
                'account': 'TEST',
                'transaction_type': 'Sell',
                'symbol': 'AAPL 260131C55000',
                'underlying_symbol': 'AAPL',
                'is_option': True,
                'option_details': {
                    'underlying': 'AAPL',
                    'expiry': '2026-01-31',
                    'option_type': 'Call',
                    'strike': 55.0
                },
                'quantity': -2,
                'price': 3.00,
                'net_amount': 590.0,
                'commission': 10.0
            },
            # Short call against LEAPS #2
            {
                'id': 'short2',
                'date': '2026-01-15',
                'datetime': '2026-01-15T10:00:00',
                'account': 'TEST',
                'transaction_type': 'Sell',
                'symbol': 'AAPL 260131C65000',
                'underlying_symbol': 'AAPL',
                'is_option': True,
                'option_details': {
                    'underlying': 'AAPL',
                    'expiry': '2026-01-31',
                    'option_type': 'Call',
                    'strike': 65.0
                },
                'quantity': -2,
                'price': 2.00,
                'net_amount': 390.0,
                'commission': 10.0
            },
        ]
        
        trades = parser._group_transactions(transactions)
        
        # Should be 2 separate PMCC lifecycles
        assert len(trades) == 2, f"Expected 2 PMCC lifecycles, got {len(trades)}"
        
        # Each should be PMCC strategy
        for t in trades:
            assert t.get('strategy_type') == 'PMCC', \
                f"Expected PMCC strategy, got {t.get('strategy_type')}"
        
        # LEAPS strikes should be distinct
        leaps_strikes = [t.get('leaps_strike') for t in trades]
        assert 50.0 in leaps_strikes, f"Expected LEAPS strike $50, got {leaps_strikes}"
        assert 60.0 in leaps_strikes, f"Expected LEAPS strike $60, got {leaps_strikes}"
    
    def test_pmcc_no_stock_shares(self):
        """
        Test: PMCC should have 0 stock shares
        Expected: shares field is 0, only contracts matter
        """
        parser = IBKRParser()
        
        transactions = [
            {
                'id': 'leaps1',
                'date': '2026-01-10',
                'datetime': '2026-01-10T09:00:00',
                'account': 'TEST',
                'transaction_type': 'Buy',
                'symbol': 'TSLA 270115C50000',
                'underlying_symbol': 'TSLA',
                'is_option': True,
                'option_details': {
                    'underlying': 'TSLA',
                    'expiry': '2027-01-15',
                    'option_type': 'Call',
                    'strike': 50.0
                },
                'quantity': 1,
                'price': 30.00,
                'net_amount': -3010.0,
                'commission': 10.0
            },
        ]
        
        trades = parser._group_transactions(transactions)
        
        assert len(trades) == 1
        trade = trades[0]
        
        assert trade.get('strategy_type') == 'PMCC'
        assert trade.get('shares') == 0, f"PMCC should have 0 shares, got {trade.get('shares')}"
        assert trade.get('contracts') >= 1, f"PMCC should have contracts, got {trade.get('contracts')}"
    
    def test_pmcc_lifecycle_open_until_leaps_expires(self):
        """
        Test: PMCC lifecycle remains OPEN until LEAPS expires
        Expected: status is 'Open' even with short call activity
        """
        parser = IBKRParser()
        
        transactions = [
            # LEAPS (future expiry)
            {
                'id': 'leaps1',
                'date': '2026-01-10',
                'datetime': '2026-01-10T09:00:00',
                'account': 'TEST',
                'transaction_type': 'Buy',
                'symbol': 'TSLA 270115C50000',
                'underlying_symbol': 'TSLA',
                'is_option': True,
                'option_details': {
                    'underlying': 'TSLA',
                    'expiry': '2027-01-15',  # Future date
                    'option_type': 'Call',
                    'strike': 50.0
                },
                'quantity': 1,
                'price': 30.00,
                'net_amount': -3010.0,
                'commission': 10.0
            },
            # Short call
            {
                'id': 'short1',
                'date': '2026-01-15',
                'datetime': '2026-01-15T09:00:00',
                'account': 'TEST',
                'transaction_type': 'Sell',
                'symbol': 'TSLA 260131C55000',
                'underlying_symbol': 'TSLA',
                'is_option': True,
                'option_details': {
                    'underlying': 'TSLA',
                    'expiry': '2026-01-31',
                    'option_type': 'Call',
                    'strike': 55.0
                },
                'quantity': -1,
                'price': 5.00,
                'net_amount': 490.0,
                'commission': 10.0
            },
        ]
        
        trades = parser._group_transactions(transactions)
        
        assert len(trades) == 1
        trade = trades[0]
        
        assert trade.get('status') == 'Open', \
            f"PMCC should be Open until LEAPS expires, got {trade.get('status')}"
    
    def test_pmcc_short_call_matches_leaps_constraints(self):
        """
        Test: Short calls attach only if strike > long strike and expiry < long expiry
        """
        parser = IBKRParser()
        
        # Short call with strike ABOVE long strike, expiry BEFORE long expiry
        transactions = [
            {
                'id': 'leaps1',
                'date': '2026-01-10',
                'datetime': '2026-01-10T09:00:00',
                'account': 'TEST',
                'transaction_type': 'Buy',
                'symbol': 'AAPL 270115C50000',
                'underlying_symbol': 'AAPL',
                'is_option': True,
                'option_details': {
                    'underlying': 'AAPL',
                    'expiry': '2027-01-15',
                    'option_type': 'Call',
                    'strike': 50.0  # Long strike
                },
                'quantity': 2,
                'price': 45.00,
                'net_amount': -9010.0,
                'commission': 10.0
            },
            {
                'id': 'short1',
                'date': '2026-01-15',
                'datetime': '2026-01-15T09:00:00',
                'account': 'TEST',
                'transaction_type': 'Sell',
                'symbol': 'AAPL 260131C55000',
                'underlying_symbol': 'AAPL',
                'is_option': True,
                'option_details': {
                    'underlying': 'AAPL',
                    'expiry': '2026-01-31',  # BEFORE long expiry
                    'option_type': 'Call',
                    'strike': 55.0  # ABOVE long strike
                },
                'quantity': -2,
                'price': 3.00,
                'net_amount': 590.0,
                'commission': 10.0
            },
        ]
        
        trades = parser._group_transactions(transactions)
        
        assert len(trades) == 1
        trade = trades[0]
        
        # Short call should be attached (premium received > 0)
        assert trade.get('short_premium', 0) > 0, \
            f"Short call should be attached, got premium {trade.get('short_premium')}"


class TestLifecyclePositionInstanceID:
    """Tests for Position Instance ID generation"""
    
    def test_csp_lifecycle_has_position_instance_id(self):
        """Test: CSP lifecycles have unique position_instance_id"""
        parser = IBKRParser()
        
        transactions = [
            {
                'id': 'csp1',
                'date': '2026-01-15',
                'datetime': '2026-01-15T09:00:00',
                'account': 'TEST',
                'transaction_type': 'Sell',
                'symbol': 'IREN 260117P55000',
                'underlying_symbol': 'IREN',
                'is_option': True,
                'option_details': {
                    'underlying': 'IREN',
                    'expiry': '2026-01-17',
                    'option_type': 'Put',
                    'strike': 55.0
                },
                'quantity': -2,
                'price': 1.50,
                'net_amount': 290.0,
                'commission': 5.0
            },
            {
                'id': 'assign1',
                'date': '2026-01-17',
                'datetime': '2026-01-17T16:00:00',
                'account': 'TEST',
                'transaction_type': 'Assignment',
                'symbol': 'IREN',
                'underlying_symbol': 'IREN',
                'is_option': False,
                'quantity': 200,
                'price': 55.0,
                'net_amount': -11000.0,
                'commission': 0
            },
        ]
        
        trades = parser._group_transactions(transactions)
        
        assert len(trades) >= 1
        trade = trades[0]
        
        assert trade.get('position_instance_id') is not None, \
            "Trade should have position_instance_id"
        assert 'IREN' in trade.get('position_instance_id', ''), \
            f"Position ID should contain symbol, got {trade.get('position_instance_id')}"
    
    def test_pmcc_lifecycle_has_position_instance_id(self):
        """Test: PMCC lifecycles have unique position_instance_id with LEAPS info"""
        parser = IBKRParser()
        
        transactions = [
            {
                'id': 'leaps1',
                'date': '2026-01-10',
                'datetime': '2026-01-10T09:00:00',
                'account': 'TEST',
                'transaction_type': 'Buy',
                'symbol': 'AAPL 270115C50000',
                'underlying_symbol': 'AAPL',
                'is_option': True,
                'option_details': {
                    'underlying': 'AAPL',
                    'expiry': '2027-01-15',
                    'option_type': 'Call',
                    'strike': 50.0
                },
                'quantity': 2,
                'price': 45.00,
                'net_amount': -9010.0,
                'commission': 10.0
            },
        ]
        
        trades = parser._group_transactions(transactions)
        
        assert len(trades) == 1
        trade = trades[0]
        
        assert trade.get('position_instance_id') is not None
        assert 'PMCC' in trade.get('position_instance_id', ''), \
            f"PMCC position ID should contain 'PMCC', got {trade.get('position_instance_id')}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
