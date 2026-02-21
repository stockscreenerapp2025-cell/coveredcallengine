# ADR-001: End-of-Day Market Close Price Contract

## Status
**ACCEPTED** - January 2026

## Context

The Covered Call Engine (CCE) platform requires deterministic, reproducible scanning results across all snapshot-based modules (Dashboard, Screener CC, PMCC). The current implementation has several architectural gaps:

1. **No explicit timing enforcement** - Snapshots can be triggered at any time
2. **No idempotency** - Re-ingestion overwrites existing data without safeguards
3. **Mixed data sources** - Watchlist falls back to live data, breaking consistency
4. **No canonical timestamp** - Market close is implied, not enforced

These gaps violate the principle of a **Single Source of Truth** and cause data divergence between modules.

## Decision

We establish a **permanent, non-negotiable EOD Price Contract** that defines:

### 1. Market Close Definition

For every Stock and ETF symbol, the **Market Close Price** is:

- A snapshot taken at **04:05:00 PM ET** (after the NYSE close candle finalizes)
- Representing the **official NYSE end-of-day close price**
- **Immutable** for that trading day
- Applied regardless of user timezone

### 2. Canonical Schema

A new MongoDB collection `eod_market_close` stores the authoritative EOD data:

```javascript
{
  "symbol": "AAPL",
  "trade_date": "2026-01-23",                    // NYSE trading day (YYYY-MM-DD)
  "market_close_price": 198.45,                  // THE canonical price
  "market_close_timestamp": "2026-01-23T16:05:00-05:00",  // Fixed ET
  "source": "yahoo",                             // Data provider
  "ingestion_run_id": "run_20260123_1605_abc123", // Unique run identifier
  "is_final": true,                              // Immutability flag
  "created_at": "2026-01-23T21:06:00Z",          // UTC timestamp
  "metadata": {
    "volume": 45000000,
    "market_cap": 2800000000000,
    "avg_volume": 50000000,
    "earnings_date": "2026-02-15",
    "analyst_rating": "buy"
  }
}
```

A new MongoDB collection `eod_options_chain` stores the authoritative options data:

```javascript
{
  "symbol": "AAPL",
  "trade_date": "2026-01-23",
  "stock_price": 198.45,                         // Must match eod_market_close
  "market_close_timestamp": "2026-01-23T16:05:00-05:00",
  "ingestion_run_id": "run_20260123_1605_abc123",
  "is_final": true,
  "calls": [...],                                // Option contracts
  "puts": [...],
  "expiries": [...],
  "valid_contracts": 245,
  "source": "yahoo"
}
```

### 3. Module Usage Rules

| Module | Data Source | Fallback Allowed? |
|--------|-------------|-------------------|
| Dashboard | `eod_market_close` | ❌ FAIL FAST |
| Screener CC | `eod_market_close` | ❌ FAIL FAST |
| PMCC | `eod_market_close` | ❌ FAIL FAST |
| Watchlist (Snapshot Mode) | `eod_market_close` | ❌ FAIL FAST |
| Watchlist (Live Mode) | Live API | N/A (explicit live) |
| Simulator | Live API | N/A (explicit live) |

**Forbidden in snapshot modules:**
- `fetch_stock_quote()` 
- `regularMarketPrice`
- `currentPrice`
- `previousClose` (from yfinance.info)
- Any live API fallback

### 4. Ingestion Rules

1. **Timing**: Ingestion runs **once per trading day after 04:05 PM ET**
2. **Idempotency**: If `is_final: true` exists for symbol+trade_date, ingestion is a **no-op**
3. **Override**: Re-ingestion requires explicit `override=true` flag and admin privileges
4. **Cross-Validation**: Options `trade_date` must match stock `trade_date` or ingestion fails

### 5. Service Boundary

A new `EODPriceContract` class enforces the contract at the service boundary:

```python
class EODPriceContract:
    @staticmethod
    async def get_market_close_price(symbol: str, trade_date: str) -> float:
        """Returns canonical EOD price or raises EODPriceNotFoundError."""
        
    @staticmethod
    async def get_options_chain(symbol: str, trade_date: str) -> dict:
        """Returns canonical options chain or raises EODOptionsNotFoundError."""
```

All snapshot-based modules **MUST** use this interface. Direct database access is prohibited.

## Consequences

### Positive
- Deterministic scan results across all modules
- Clear separation between EOD (snapshot) and live data streams
- Audit trail via `ingestion_run_id`
- Protection against accidental data corruption

### Negative
- Requires migration of existing snapshot data
- Watchlist module must be split (snapshot vs live)
- Slightly more complex ingestion logic

### Neutral
- Scheduler timing becomes critical (must run after 04:05 PM ET)
- Manual re-ingestion requires admin override

## Migration Plan

1. **Phase 1**: Create new collections (`eod_market_close`, `eod_options_chain`)
2. **Phase 2**: Create `EODIngestionService` with idempotency and timing
3. **Phase 3**: Create `EODPriceContract` service boundary
4. **Phase 4**: Migrate snapshot-based modules to use contract
5. **Phase 5**: Split Watchlist into snapshot/live modes
6. **Phase 6**: Configure APScheduler for 04:05 PM ET
7. **Phase 7**: Deprecate old `stock_snapshots` / `option_chain_snapshots` collections

## Validation Checklist

- [ ] EOD price for symbol+trade_date is immutable after `is_final: true`
- [ ] Re-ingestion without `override=true` is a no-op
- [ ] Dashboard/Screener/PMCC fail fast if EOD data missing
- [ ] Watchlist snapshot mode fails fast (no live fallback)
- [ ] Watchlist live mode is explicitly labeled
- [ ] APScheduler runs at 04:05 PM ET on trading days
- [ ] Options trade_date matches stock trade_date

## Governance

Once implemented:
- EOD price and EOD options chain semantics are **frozen**
- Any deviation (fallback to live, schema reuse, semantic change) requires a **new ADR**
- This is an **architectural change**, not a bug fix

## Authors
- CCE Architecture Team
- Date: January 2026
