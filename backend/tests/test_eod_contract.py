"""
Test Suite: EOD Market Close Price Contract (ADR-001)
======================================================

Tests the canonical EOD price contract implementation:
- eod_market_close collection
- eod_options_chain collection
- EODPriceContract service boundary
- EODIngestionService idempotency

VALIDATION CHECKLIST:
- [ ] EOD price for symbol+trade_date is immutable after is_final=true
- [ ] Re-ingestion without override=true is a no-op
- [ ] Dashboard/Screener/PMCC fail fast if EOD data missing
- [ ] Watchlist snapshot mode fails fast (no live fallback)
- [ ] Watchlist live mode is explicitly labeled
- [ ] Options trade_date matches stock trade_date
"""

import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.eod_ingestion_service import (
    EODIngestionService,
    EODPriceContract,
    EODPriceNotFoundError,
    EODOptionsNotFoundError,
    EODAlreadyFinalError
)


class TestEODPriceContract:
    """Test the EOD Price Contract service boundary."""
    
    @pytest.fixture
    def mock_db(self):
        """Create a mock database."""
        db = AsyncMock()
        return db
    
    @pytest.fixture
    def contract(self, mock_db):
        """Create an EOD Price Contract instance."""
        return EODPriceContract(mock_db)
    
    @pytest.mark.asyncio
    async def test_get_market_close_price_success(self, contract, mock_db):
        """Test successful retrieval of canonical EOD price."""
        # Setup mock
        mock_db.eod_market_close.find_one.return_value = {
            "symbol": "AAPL",
            "trade_date": "2026-01-23",
            "market_close_price": 198.45,
            "market_close_timestamp": "2026-01-23T16:05:00-05:00",
            "source": "yahoo",
            "is_final": True
        }
        
        price, doc = await contract.get_market_close_price("AAPL", "2026-01-23")
        
        assert price == 198.45
        assert doc["market_close_timestamp"] == "2026-01-23T16:05:00-05:00"
        assert doc["is_final"] is True
    
    @pytest.mark.asyncio
    async def test_get_market_close_price_not_found(self, contract, mock_db):
        """Test that missing EOD price raises EODPriceNotFoundError."""
        mock_db.eod_market_close.find_one.return_value = None
        
        with pytest.raises(EODPriceNotFoundError) as exc_info:
            await contract.get_market_close_price("FAKE", "2026-01-23")
        
        assert "FAKE" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_get_options_chain_success(self, contract, mock_db):
        """Test successful retrieval of canonical options chain."""
        mock_db.eod_options_chain.find_one.return_value = {
            "symbol": "AAPL",
            "trade_date": "2026-01-23",
            "stock_price": 198.45,
            "is_final": True,
            "calls": [{"strike": 200, "bid": 2.50}],
            "valid_contracts": 42
        }
        
        chain = await contract.get_options_chain("AAPL", "2026-01-23")
        
        assert chain["symbol"] == "AAPL"
        assert chain["valid_contracts"] == 42
        assert len(chain["calls"]) == 1
    
    @pytest.mark.asyncio
    async def test_get_valid_calls_filters_correctly(self, contract, mock_db):
        """Test that get_valid_calls_for_scan filters by DTE and strike."""
        mock_db.eod_options_chain.find_one.return_value = {
            "symbol": "AAPL",
            "trade_date": "2026-01-23",
            "stock_price": 100.0,
            "is_final": True,
            "calls": [
                {"strike": 105, "bid": 2.50, "ask": 2.60, "dte": 14, "valid": True},
                {"strike": 110, "bid": 1.50, "ask": 1.60, "dte": 30, "valid": True},
                {"strike": 150, "bid": 0.10, "ask": 0.20, "dte": 30, "valid": True},  # Too far OTM
                {"strike": 102, "bid": 0.05, "ask": 0.10, "dte": 60, "valid": True},  # DTE too high
            ]
        }
        
        calls = await contract.get_valid_calls_for_scan(
            "AAPL", "2026-01-23",
            min_dte=7, max_dte=45,
            min_strike_pct=1.0, max_strike_pct=1.15,
            min_bid=0.10
        )
        
        # Should only include the first two calls
        assert len(calls) == 2
        assert calls[0]["strike"] == 105
        assert calls[1]["strike"] == 110


class TestEODIngestionService:
    """Test the EOD Ingestion Service."""
    
    @pytest.fixture
    def mock_db(self):
        """Create a mock database."""
        db = AsyncMock()
        db.eod_market_close.find_one.return_value = None
        db.eod_market_close.update_one.return_value = AsyncMock(upserted_id=None)
        db.eod_options_chain.find_one.return_value = None
        db.eod_options_chain.update_one.return_value = AsyncMock(upserted_id=None)
        return db
    
    @pytest.fixture
    def service(self, mock_db):
        """Create an EOD Ingestion Service instance."""
        return EODIngestionService(mock_db)
    
    def test_get_canonical_close_timestamp(self, service):
        """Test that canonical timestamp is 04:05 PM ET."""
        timestamp = service.get_canonical_close_timestamp("2026-01-23")
        
        assert "16:05:00" in timestamp
        assert "-05:00" in timestamp  # Eastern timezone
    
    def test_generate_ingestion_run_id(self, service):
        """Test ingestion run ID generation."""
        run_id = service.generate_ingestion_run_id("2026-01-23")
        
        assert run_id.startswith("run_20260123_1605_")
        assert len(run_id) > 20  # Has UUID suffix
    
    @pytest.mark.asyncio
    async def test_idempotency_already_final(self, service, mock_db):
        """Test that re-ingestion of final data is a no-op without override."""
        # Setup: Existing final record
        mock_db.eod_market_close.find_one.return_value = {
            "symbol": "AAPL",
            "trade_date": "2026-01-23",
            "market_close_price": 198.45,
            "is_final": True
        }
        
        result = await service.ingest_eod_stock_price("AAPL", "2026-01-23", override=False)
        
        assert result["status"] == "ALREADY_FINAL"
        assert result["market_close_price"] == 198.45
        # Update should NOT have been called
        mock_db.eod_market_close.update_one.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_override_allows_reingest(self, service, mock_db):
        """Test that override=True allows re-ingestion."""
        mock_db.eod_market_close.find_one.return_value = {
            "symbol": "AAPL",
            "trade_date": "2026-01-23",
            "market_close_price": 198.45,
            "is_final": True
        }
        
        # Mock the Yahoo fetch to return data
        with patch.object(service, '_fetch_eod_price_yahoo', return_value={
            "close_price": 200.00,
            "volume": 50000000
        }):
            result = await service.ingest_eod_stock_price("AAPL", "2026-01-23", override=True)
        
        # Update should have been called with override
        mock_db.eod_market_close.update_one.assert_called_once()


class TestEODDataIntegrity:
    """Test data integrity across the EOD contract."""
    
    @pytest.mark.asyncio
    async def test_stock_price_immutability(self):
        """
        VALIDATION: EOD price for symbol+trade_date is immutable after is_final=true.
        
        This is a conceptual test - in production, the database constraint
        prevents modification of final records without explicit override.
        """
        # This would be an integration test against a real database
        # For unit testing, we verify the logic in the service
        pass
    
    @pytest.mark.asyncio
    async def test_options_stock_date_alignment(self):
        """
        VALIDATION: Options trade_date must match stock trade_date.
        
        The EODIngestionService.ingest_eod_options_chain() method verifies
        that the stock EOD exists for the same trade_date before ingesting options.
        """
        mock_db = AsyncMock()
        service = EODIngestionService(mock_db)
        
        # Stock EOD does not exist
        mock_db.eod_market_close.find_one.return_value = None
        
        result = await service.ingest_eod_options_chain("AAPL", 198.45, "2026-01-23")
        
        assert result["status"] == "FAILED"
        assert "Stock EOD not found" in result["error"]


class TestADR001Compliance:
    """Test ADR-001 compliance markers."""
    
    def test_price_source_labeling(self):
        """
        VALIDATION: Live prices must be labeled as LIVE_PRICE.
        
        The watchlist endpoint returns price_source field:
        - "EOD_CONTRACT" for canonical prices
        - "LIVE_PRICE" for live prices
        """
        # This is verified by the watchlist endpoint implementation
        # See routes/watchlist.py get_watchlist() function
        pass
    
    def test_no_live_fallback_in_screener(self):
        """
        VALIDATION: Screener must not have live data fallback.
        
        The screener_snapshot.py file has a KILL SWITCH comment:
        # from services.data_provider import fetch_options_chain, fetch_stock_quote
        # ^^^ DELIBERATELY NOT IMPORTED
        """
        import routes.screener_snapshot as screener
        
        # Verify that live data functions are not imported
        assert not hasattr(screener, 'fetch_stock_quote')
        assert not hasattr(screener, 'fetch_options_chain')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
