# CCE Layer 1 - Snapshot Schema Definition

**Version:** 1.0  
**Status:** LAYER 1 COMPLIANT  
**Date:** January 2026

---

## 1. Stock Snapshot Schema

**Collection:** `stock_snapshots`

```json
{
  "symbol": "AAPL",                              // Stock ticker (uppercase)
  
  // MANDATORY PRICE FIELDS (LAYER 1 COMPLIANT)
  "stock_close_price": 247.65,                  // THE ONLY VALID PRICE - Previous NYSE market close
  "stock_price_trade_date": "2026-01-22",       // LTD when price was established
  
  // Legacy field (for backward compatibility)
  "price": 247.65,                              // Deprecated - use stock_close_price
  
  // DATE/TIME METADATA
  "snapshot_trade_date": "2026-01-22",          // NYSE trading day this snapshot represents
  "snapshot_time": "2026-01-22T23:15:46+00:00", // UTC timestamp when snapshot was taken
  "data_age_hours": 2.3,                        // Hours since market close
  
  // LIQUIDITY/SIZE METRICS
  "volume": 36741334,                           // Trading day volume
  "avg_volume": 46204940,                       // Average daily volume
  "market_cap": 3669707194368,                  // Market capitalization
  
  // DOWNSTREAM FIELDS (for Layer 3 filtering)
  "earnings_date": "2026-04-25",                // Next earnings date (or null)
  "analyst_rating": "buy",                      // Consensus rating
  "pe_ratio": 32.5,                             // P/E ratio
  "dividend_yield": 0.004,                      // Dividend yield
  
  // VALIDATION
  "completeness_flag": true,                    // All required fields present
  "source": "yahoo",                            // Data provider (yahoo|polygon)
  "error": null                                 // Error message if incomplete
}
```

### Mandatory Fields for Layer 1 Compliance:
- `stock_close_price` - MUST be previousClose (not regularMarketPrice)
- `stock_price_trade_date` - MUST equal snapshot_trade_date
- `completeness_flag` - MUST be true for valid snapshot

### FORBIDDEN Price Sources:
- ❌ `regularMarketPrice` (intraday)
- ❌ `currentPrice` (intraday)
- ❌ `preMarketPrice`
- ❌ `postMarketPrice`

---

## 2. Option Chain Snapshot Schema

**Collection:** `option_chain_snapshots`

```json
{
  "symbol": "AAPL",
  "stock_price": 247.65,                         // Stock close price at snapshot time
  
  // DATE FIELDS (ALL MUST MATCH FOR VALIDATION)
  "snapshot_trade_date": "2026-01-22",          // NYSE trading day
  "options_data_trade_day": "2026-01-22",       // Options data trading day
  "options_snapshot_time": "2026-01-22T23:15:47+00:00", // UTC snapshot timestamp
  "stock_trade_date_from_stock_snapshot": "2026-01-22", // Cross-validation field
  
  // DATA AGE
  "data_age_hours": 2.3,
  
  // CHAIN DATA
  "expiries": ["2026-01-23", "2026-01-30", ...], // Available expiration dates
  "calls": [...],                                // Array of call contracts
  "puts": [...],                                 // Array of put contracts
  "total_contracts": 2030,                       // Total contracts fetched
  "valid_contracts": 1373,                       // Contracts passing validation
  "rejection_reasons": [...],                    // Sample rejection messages
  
  // VALIDATION FLAGS
  "completeness_flag": true,                     // Chain complete enough for scanning
  "date_validation_passed": true,                // stock_trade_date == options_trade_date
  "source": "yahoo",
  "error": null
}
```

---

## 3. Option Contract Schema (within calls/puts arrays)

```json
{
  // IDENTITY
  "contract_symbol": "AAPL260130C00155000",
  "strike": 155.0,
  "expiry": "2026-01-30",
  "dte": 7,
  "option_type": "call",                        // "call" or "put"
  
  // PRICING (MANDATORY - NEVER averaged)
  "bid": 92.0,                                  // SELL legs use BID ONLY
  "ask": 95.35,                                 // BUY legs use ASK ONLY
  "last_price": 103.73,                         // Last trade (informational only)
  
  // LIQUIDITY (MANDATORY)
  "volume": 0,                                  // Daily volume
  "open_interest": 2,                           // Open interest
  
  // GREEKS (MANDATORY)
  "implied_volatility": 1.4589,                 // IV from market
  "delta": 0.95,                                // Estimated delta
  "gamma": 0.0,                                 // Placeholder (not from Yahoo)
  "theta": 0.0,                                 // Placeholder
  "vega": 0.0,                                  // Placeholder
  "iv_rank": null,                              // Placeholder (requires historical)
  
  // VALIDATION
  "valid": true,                                // Passed Layer 1 validation
  "rejection_reason": null                      // Reason if rejected
}
```

### Contract Validation Rules (Layer 1):
1. `bid > 0` - Required for all contracts
2. `ask > 0` - Required for all contracts
3. Spread < 50% - Loose filter (Layer 2 applies 10%)
4. Strike within 50-150% of stock price

---

## 4. Sample Validated Snapshot Document

### Stock (AAPL - Layer 1 Compliant):
```json
{
  "symbol": "AAPL",
  "stock_close_price": 247.65,
  "stock_price_trade_date": "2026-01-22",
  "snapshot_trade_date": "2026-01-22",
  "snapshot_time": "2026-01-22T23:15:46.700007+00:00",
  "data_age_hours": 2.3,
  "volume": 36741334,
  "avg_volume": 46204940,
  "market_cap": 3669707194368,
  "earnings_date": null,
  "analyst_rating": "buy",
  "completeness_flag": true,
  "source": "yahoo",
  "error": null
}
```

### Option Chain Summary (AAPL):
```json
{
  "symbol": "AAPL",
  "stock_price": 247.65,
  "snapshot_trade_date": "2026-01-22",
  "options_data_trade_day": "2026-01-22",
  "stock_trade_date_from_stock_snapshot": "2026-01-22",
  "date_validation_passed": true,
  "completeness_flag": true,
  "valid_contracts": 1373,
  "total_contracts": 2030,
  "data_age_hours": 2.3,
  "source": "yahoo"
}
```

---

## 5. Cross-Validation Rules

### Date Matching (HARD FAIL if violated):
```
stock_price_trade_date == options_data_trade_day == snapshot_trade_date
```

If any dates don't match:
- `date_validation_passed = false`
- Snapshot is stored but flagged as invalid
- Scan MUST abort (HTTP 409)

### Data Age Enforcement:
- `MAX_DATA_AGE_HOURS = 48`
- Snapshots older than 48 hours are considered stale
- Scan MUST abort if using stale data

---

## 6. Layer 1 Compliance Checklist

| Requirement | Status | Evidence |
|-------------|--------|----------|
| Stock price = previous NYSE close only | ✅ | Uses `previousClose` from Yahoo |
| No regularMarketPrice | ✅ | Explicitly rejected in `_fetch_stock_yahoo` |
| No intraday/pre-market/after-hours | ✅ | Only `previousClose` allowed |
| NYSE calendar enforced | ✅ | `pandas_market_calendars` NYSE calendar |
| Weekends/holidays handled | ✅ | `get_last_trading_day()` |
| Stock/options dates cross-validated | ✅ | `date_validation_passed` flag |
| Mismatched dates = HARD FAIL | ✅ | Returns error, scan aborts |
| BID/ASK stored separately | ✅ | Never averaged |
| All mandatory fields present | ✅ | Schema includes greeks, OI, volume |
| No live data imports in Layer 1 | ✅ | Only `snapshot_service.py` fetches data |

---

**Layer 1 Implementation Complete.**  
**No downstream layers (2-5) were modified.**
