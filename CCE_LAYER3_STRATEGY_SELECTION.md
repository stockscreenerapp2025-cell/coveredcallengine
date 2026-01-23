# CCE Layer 3 - Strategy Selection & Enrichment

**Version:** 1.0  
**Status:** LAYER 3 COMPLIANT  
**Date:** January 2026

---

## Overview

Layer 3 acts as the **DECISION ENGINE** between validated data (Layer 2) and scoring (Layer 4).
It applies eligibility filters, computes Greeks, and prepares enriched data for downstream consumers.

---

## 1. CC Eligibility Filters

### System/Custom Scan (Strict)
| Filter | Value | Rationale |
|--------|-------|-----------|
| Price | $30 - $90 | Avoid penny stocks and expensive premiums |
| Avg Volume | ≥ 1,000,000 | Ensure liquidity |
| Market Cap | ≥ $5B | Large-cap stability |
| Earnings | ±7 days exclusion | Avoid earnings volatility |

### Manual Scan (Relaxed)
| Filter | Value | Note |
|--------|-------|------|
| Price | $15 - $500 | Flagged but allowed |
| Volume | N/A | Not enforced |
| Market Cap | N/A | Not enforced |
| Earnings | ±7 days exclusion | Still enforced |

**Important:** Manual scan relaxes symbol eligibility ONLY. Pricing rules (BID/ASK, spread ≤10%) are NEVER relaxed.

---

## 2. DTE Modes

Per CCE Master Architecture:

| Mode | Min DTE | Max DTE | Use Case |
|------|---------|---------|----------|
| Weekly | 7 | 14 | Short-term income |
| Monthly | 21 | 45 | Standard income strategy |
| All | 7 | 45 | Full range scan |

```python
# API Usage
GET /api/screener/covered-calls?dte_mode=weekly   # 7-14 DTE
GET /api/screener/covered-calls?dte_mode=monthly  # 21-45 DTE
GET /api/screener/covered-calls?dte_mode=all      # 7-45 DTE
```

---

## 3. Greeks Enrichment

Layer 3 computes/estimates the following for each option contract:

### Delta
- Source: Snapshot (if available) or estimated from moneyness
- Estimation formula:
  ```python
  moneyness = (stock_price - strike) / stock_price
  delta = 0.50 + moneyness * 2  # Capped at 0.05-0.95
  ```

### Implied Volatility (IV)
- Source: Snapshot `implied_volatility` field
- Converted to percentage if in decimal form

### IV Rank (Estimated)
- Rough estimate based on current IV
- Formula: `(IV% - 20) / 40 * 100` (assumes typical range 20-60%)
- **Note:** Accurate IV Rank requires 52-week historical IV data

### Theta (Estimated)
- Daily time decay estimate
- Accelerates near expiry (1.5x for <7 DTE, 1.2x for <14 DTE)

### Gamma (Estimated)
- Highest ATM and near expiry
- Based on moneyness and time factors

---

## 4. API Response Structure

```json
{
  "total": 43,
  "symbols_scanned": 72,
  "symbols_with_results": 5,
  "symbols_filtered": 57,
  "filter_reasons": [
    {"symbol": "AAPL", "reason": "Price $247.65 above maximum $90.0"}
  ],
  "layer": 3,
  "scan_mode": "system",
  "dte_mode": "weekly",
  "dte_range": {"min": 7, "max": 14},
  "eligibility_filters": {
    "price_range": "$30.0-$90.0",
    "min_volume": "1,000,000",
    "min_market_cap": "$5B",
    "earnings_exclusion": "±7 days"
  },
  "spread_threshold": "10.0%",
  "results": [
    {
      "symbol": "NKE",
      "strike": 66.0,
      "expiry": "2026-01-30",
      "dte": 7,
      "dte_category": "weekly",
      "stock_price": 65.46,
      "premium": 0.95,
      "premium_yield": 1.45,
      "otm_pct": 0.82,
      // LAYER 3 ENRICHED GREEKS
      "delta": 0.4835,
      "implied_volatility": 31.2,
      "iv_rank": 27.9,
      "theta_estimate": -0.163,
      "open_interest": 1552,
      "volume": 2338,
      // SCORES (from Layer 4)
      "score": 76.3,
      "score_breakdown": {...}
    }
  ]
}
```

---

## 5. Test Results

### System Mode (Strict Filters)
```
Total: 43 opportunities
Symbols Scanned: 72
Symbols with Results: 5
Symbols Filtered: 57
DTE Mode: weekly (7-14)
Price Range: $30-$90
```

### Manual Mode (Relaxed Price)
```
Total: 214 opportunities  
Symbols Scanned: 72
Symbols with Results: 46
Symbols Filtered: 6
DTE Mode: monthly (21-45)
Price Range: $15-$500
```

---

## 6. Layer 3 Compliance Checklist

| Requirement | Status | Evidence |
|-------------|--------|----------|
| Price filter $30-$90 (system) | ✅ | `CC_SYSTEM_MIN_PRICE`, `CC_SYSTEM_MAX_PRICE` |
| Volume filter ≥1M | ✅ | `CC_SYSTEM_MIN_VOLUME` |
| Market cap filter ≥$5B | ✅ | `CC_SYSTEM_MIN_MARKET_CAP` |
| Earnings ±7 days check | ✅ | `EARNINGS_EXCLUSION_DAYS = 7` |
| Weekly DTE 7-14 | ✅ | `WEEKLY_MIN_DTE`, `WEEKLY_MAX_DTE` |
| Monthly DTE 21-45 | ✅ | `MONTHLY_MIN_DTE`, `MONTHLY_MAX_DTE` |
| Manual scan relaxed price only | ✅ | $15-$500 for manual |
| Pricing rules never relaxed | ✅ | Layer 2 validators always called |
| Greeks enrichment | ✅ | `enrich_option_greeks()` |
| Delta computed | ✅ | From snapshot or estimated |
| IV/IV Rank included | ✅ | `iv_pct`, `iv_rank` |
| OI included | ✅ | `open_interest` field |
| DTE included | ✅ | `dte`, `dte_category` fields |

---

## 7. Files Modified

**Layer 3 file:**
- `/app/backend/routes/screener_snapshot.py`

**Functions Added:**
- `check_cc_eligibility()` - Symbol eligibility checker
- `enrich_option_greeks()` - Greeks computation
- `get_dte_range()` - DTE mode helper

**Constants Added:**
- `CC_SYSTEM_MIN_PRICE = 30.0`
- `CC_SYSTEM_MAX_PRICE = 90.0`
- `CC_SYSTEM_MIN_VOLUME = 1,000,000`
- `CC_SYSTEM_MIN_MARKET_CAP = 5,000,000,000`
- `WEEKLY_MIN_DTE = 7`, `WEEKLY_MAX_DTE = 14`
- `MONTHLY_MIN_DTE = 21`, `MONTHLY_MAX_DTE = 45`
- `EARNINGS_EXCLUSION_DAYS = 7`

---

**Layer 3 Implementation Complete.**  
**Awaiting written approval to proceed with Layer 4 (Scoring & Ranking) or Layer 5 (Consumers).**
