# PHASE 5 — PMCC ENGINE (REBUILD) ✅

## Implementation Complete

### System Scan Filters

| Filter | Custom Scan | Dashboard/Pre-computed |
|--------|-------------|------------------------|
| **Price Range** | $30-$90 (ETFs exempt) | $15-$500 |
| **Avg Volume** | ≥1M | ≥1M |
| **Market Cap** | ≥$5B (ETFs exempt) | ≥$5B |
| **Earnings** | No earnings within 7 days | No earnings within 7 days |
| **LEAPS DTE** | 180-730 days | 180-730 days |
| **Short DTE** | 14-60 days | 14-60 days |

### Single-Candidate Rule ✅

**Rule:** ONE best trade per symbol (highest score wins)

```python
# Implementation in screen_pmcc
best_by_symbol = {}
for opp in opportunities:
    sym = opp["symbol"]
    if sym not in best_by_symbol or opp["score"] > best_by_symbol[sym]["score"]:
        best_by_symbol[sym] = opp
```

### ASK/BID Pricing ✅

- **LEAPS (Buy leg):** Uses ASK price
- **Short Call (Sell leg):** Uses BID price

```python
# LEAPS pricing
ask_price = opt.get("ask", 0) or 0
if ask_price > 0:
    premium = ask_price

# Short call pricing
bid_price = opt.get("bid", 0) or 0
if bid_price > 0:
    premium = bid_price
```

### Files Updated

| File | Change |
|------|--------|
| `/app/backend/routes/screener.py` | Added `enforce_phase5` parameter, Phase 5 filters, expanded ETF list |
| `/app/backend/routes/screener.py` | Updated `/dashboard-pmcc` to use $15-$500 price range |
| `/app/backend/services/data_provider.py` | Fixed Yahoo options fetch to include deep ITM options for LEAPS |
| `/app/frontend/src/pages/PMCC.js` | Default to Custom Scan, $30-$90 price filter, bypass_cache on scan |

### Key Bug Fix: Deep ITM Options

The Yahoo Finance options fetcher was filtering out deep ITM options (needed for PMCC LEAPS). Fixed by:

```python
# For LEAPS (min_dte > 90), include deep ITM options
if min_dte > 90:  # LEAPS - include deep ITM
    if strike < current_price * 0.50 or strike > current_price * 1.15:
        continue
else:
    # For shorter-term, standard ATM/OTM range
    if strike < current_price * 0.95 or strike > current_price * 1.15:
        continue
```

### API Changes

**`GET /api/screener/pmcc`**
- New parameter: `enforce_phase5=true` (default)
- Default price range: $30-$90 (was $20-$150)
- Response includes: `phase: 5`, `passed_filters`
- New cache key: `pmcc_screener_v2_phase5_*`

**`GET /api/screener/dashboard-pmcc`**
- Price range: $15-$500 (broader for dashboard)
- `enforce_phase5=false` (uses broader filters)
- New cache key: `dashboard_pmcc_v3_phase5`

### ETF Exemptions

ETFs are exempt from price and market cap filters:
```python
ETF_SYMBOLS = {"SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK", "XLV", "XLI", 
               "XLB", "XLU", "XLP", "XLY", "GLD", "SLV", "ARKK", "ARKG", "ARKW", 
               "TLT", "EEM", "VXX", "UVXY", "SQQQ", "TQQQ"}
```

### Test Evidence

**PMCC API Response (2026-01-21):**
```
Total: 10 opportunities
Phase: 5
Passed filters: 27

SLV: $85.39 | LEAPS $50 (211d) | Short $93 (22d) | ROI: 11.6% | Score: 177
INTC: $48.56 | LEAPS $27 (239d) | Short $53 (29d) | ROI: 10.0% | Score: 146
PYPL: $55.08 | LEAPS $33 (239d) | Short $60 (29d) | ROI: 4.9% | Score: 83
GM: $77.81 | LEAPS $45 (239d) | Short $83 (29d) | ROI: 4.9% | Score: 82
DAL: $67.46 | LEAPS $35 (239d) | Short $73 (29d) | ROI: 4.6% | Score: 80
```

### UI Verification

Screenshot confirmed:
- Price Range filter shows $30-$90 by default
- Custom Scan loads by default (not Pre-computed)
- Results table shows 10 PMCC opportunities
- All stock prices within $30-$90 (ETFs exempt)
- LEAPS expiry 180+ days, Short expiry 14-60 days

---

## Acceptance Criteria Status

| Criteria | Status |
|----------|--------|
| Price filter $30-$90 for Custom Scan (ETFs exempt) | ✅ PASS |
| Price filter $15-$500 for Dashboard/Pre-computed | ✅ PASS |
| Volume filter ≥1M enforced | ✅ PASS |
| Market cap filter ≥$5B enforced (ETFs exempt) | ✅ PASS |
| Earnings within 7 days excluded | ✅ PASS |
| Single-Candidate Rule (one per symbol) | ✅ PASS |
| ASK pricing for LEAPS (buy leg) | ✅ PASS |
| BID pricing for Short Call (sell leg) | ✅ PASS |
| PMCC page defaults to Custom Scan | ✅ PASS |
| Deep ITM LEAPS options available | ✅ PASS |

---

## Ready for PHASE 6?

All PHASE 5 deliverables complete:
- ✅ Custom Scan filters enforced ($30-$90)
- ✅ Dashboard/Pre-computed uses broader filters ($15-$500)
- ✅ Single-Candidate Rule implemented
- ✅ ASK/BID pricing enforced
- ✅ ETF exemptions working
- ✅ Deep ITM LEAPS fetching fixed

**Awaiting approval to proceed to PHASE 6: MARKET BIAS ORDER FIX**
