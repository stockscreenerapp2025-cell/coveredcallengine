# CCE Layer 3 Enrichment Enhancement Specification

## Overview
This document describes the Layer 3 enrichment enhancements implemented to ensure all snapshots, API responses, and dashboard displays include complete metrics.

## Date: January 2025

---

## 1. Enhanced Greeks Enrichment

### Function: `enrich_option_greeks(contract, stock_price, risk_free_rate)`

All option contracts are enriched with the following computed/estimated fields:

| Field | Description | Calculation |
|-------|-------------|-------------|
| `delta` | Option delta (from snapshot or estimated) | Estimated based on moneyness |
| `gamma` | Gamma estimate | Based on ATM proximity and time to expiry |
| `theta` | Theta estimate (daily time decay) | Premium / DTE with time acceleration factor |
| `vega` | Vega estimate | Based on IV, DTE, and ATM proximity |
| `iv_pct` | Implied Volatility as percentage | Converted from decimal if needed |
| `iv_rank` | IV Rank (0-100) | Estimated using 15-80% typical IV range |
| `roi_pct` | Return on Investment per trade | (Premium / Stock Price) * 100 |
| `roi_annualized` | Annualized ROI | ROI * (365 / DTE) |
| `premium_ask` | Ask price for reference | Direct from contract |

### ROI Formula
```
ROI (%) = (Premium / Stock Price) * 100 * (365 / DTE)
```

---

## 2. Enhanced PMCC Metrics

### Function: `enrich_pmcc_metrics(leap_contract, short_contract, stock_price)`

PMCC opportunities include these additional fields:

| Field | Description |
|-------|-------------|
| `leaps_buy_eligible` | Boolean: DTE >= 365, Delta >= 0.70, OI >= 500 |
| `premium_ask` | LEAP ask price (cost to buy) |
| `delta` | LEAP delta |
| `leap_dte` | Days to expiration for LEAP |
| `short_dte` | Days to expiration for short call |
| `leap_cost` | LEAP cost per contract ($) |
| `width` | Strike spread (short_strike - leap_strike) |
| `net_debit` | Net cost (leap_ask - short_bid) |
| `net_debit_total` | Per-contract net cost |
| `max_profit` | Maximum profit potential |
| `breakeven` | Breakeven price |
| `roi_per_cycle` | ROI per cycle (%) |
| `roi_annualized` | Annualized ROI (%) |
| `analyst_rating` | Stock analyst rating |

---

## 3. DTE Mode Support

### Endpoint: `/api/screener/covered-calls`

| Mode | DTE Range | Description |
|------|-----------|-------------|
| `weekly` | 7-14 days | Weekly options only |
| `monthly` | 21-45 days | Monthly options only |
| `all` | 7-45 days | Both weekly and monthly |

### Usage
```
GET /api/screener/covered-calls?dte_mode=weekly
GET /api/screener/covered-calls?dte_mode=monthly
GET /api/screener/covered-calls?dte_mode=all
```

---

## 4. Dashboard Opportunities

### Endpoint: `/api/screener/dashboard-opportunities`

Returns **Top 5 Weekly + Top 5 Monthly** covered calls:

```json
{
  "total": 10,
  "weekly_count": 5,
  "monthly_count": 5,
  "opportunities": [...],
  "weekly_opportunities": [...],
  "monthly_opportunities": [...],
  "architecture": "TOP5_WEEKLY_TOP5_MONTHLY"
}
```

### Visual Distinction
- Weekly: Cyan color coding (`bg-cyan-500`)
- Monthly: Violet color coding (`bg-violet-500`)
- Row border indicates type (left border)

---

## 5. Symbol Handling

### GOOG vs GOOGL
Both symbols are included and treated separately:
- `GOOGL` - Class A shares (voting rights)
- `GOOG` - Class C shares (no voting rights)

### Verification
```python
assert "GOOG" in SCAN_SYMBOLS
assert "GOOGL" in SCAN_SYMBOLS
```

---

## 6. Data Accuracy & Validation

### Price Discrepancy Detection

Function: `log_price_discrepancy(symbol, source1_name, source1_price, source2_name, source2_price, threshold_pct=0.1)`

- Logs WARNING if price discrepancy > 0.1%
- Returns `True` if discrepancy detected
- Handles zero prices gracefully

### Layer 1 Authority
- `stock_close_price` from Layer 1 snapshot is authoritative
- Used for all calculations (Greeks, ROI, etc.)
- Layer 2 validated contracts preserved

---

## 7. API Response Fields

### Covered Call Response
```json
{
  "symbol": "AAPL",
  "strike": 240.0,
  "expiry": "2025-01-31",
  "dte": 7,
  "dte_category": "weekly",
  "stock_price": 237.50,
  "premium": 2.15,
  "premium_ask": 2.25,
  "premium_yield": 0.91,
  "otm_pct": 1.05,
  "roi_pct": 0.91,
  "roi_annualized": 47.3,
  "delta": 0.4234,
  "gamma": 0.0312,
  "theta": -0.102,
  "vega": 0.523,
  "implied_volatility": 28.5,
  "iv_rank": 32,
  "open_interest": 15234,
  "volume": 2341,
  "score": 78.5,
  "score_breakdown": {...},
  "analyst_rating": "Buy",
  "market_cap": 3500000000000,
  "earnings_date": "2025-02-15"
}
```

---

## 8. Unit Tests

Location: `/app/backend/tests/test_layer3_enrichment.py`

### Test Coverage
- ✅ Greeks enrichment (Delta, IV, IV Rank, Theta, Gamma, Vega)
- ✅ ROI calculation
- ✅ PMCC metrics (LEAPS eligibility, Width, ROI)
- ✅ Weekly/Monthly/All DTE selection
- ✅ GOOG vs GOOGL distinction
- ✅ Price discrepancy detection

### Run Tests
```bash
cd /app/backend && python -m pytest tests/test_layer3_enrichment.py -v
```

---

## 9. Frontend Dashboard Updates

### Top 10 Covered Calls Display
- Header shows badges: "Top 5 Weekly" + "Top 5 Monthly"
- Table includes ROI Annualized column
- Row border color indicates Weekly (cyan) vs Monthly (violet)
- Type badge styled with distinct colors
- Option contract formatted with expiry type color

### Column Order
Symbol | Price | Strike | Type | DTE | Premium | ROI | ROI Ann. | Delta | IV | IV Rank | OI | AI Score | Analyst | Action

---

## 10. Logging

### Failed Enrichments
Enrichment failures are logged to prevent silent data loss:
```
WARNING: [PRICE DISCREPANCY] AAPL: Source1=$150.00 vs Source2=$150.50 (diff=0.33% > 0.1%)
```

---

## Architecture Compliance

This implementation maintains strict compliance with the CCE Master Architecture Spec:

1. **Layer 1 Authority**: All calculations use validated `stock_close_price`
2. **Layer 2 Preservation**: Validated contracts not overwritten
3. **Layer 3 Enrichment**: All metrics computed post-validation
4. **Fail-Closed**: Missing data fails gracefully with logging
5. **Snapshot-Only**: No live data fetching during enrichment
