# PHASE 0 — BASELINE LOCK AUDIT

## 🎯 Objective
Document all violations of the institutional-grade CCE requirements before making any code changes.

---

## 📐 CURRENT ARCHITECTURE MAP

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          SCAN REQUEST                                    │
│                   (Dashboard / Screener / PMCC)                         │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         CACHE CHECK                                      │
│                  (api_cache collection - TTL based)                      │
│              Market Open: 5 min | Market Closed: 1 hour                  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │ CACHE HIT                      │ CACHE MISS
                    ▼                                ▼
            Return cached data         ┌─────────────────────────────────┐
                                       │     LIVE DATA FETCH             │
                                       │  (VIOLATION: Live during scan)  │
                                       └─────────────────────────────────┘
                                                     │
                    ┌────────────────────────────────┼────────────────────┐
                    ▼                                ▼                    ▼
        ┌───────────────────┐          ┌───────────────────┐    ┌─────────────────┐
        │   Yahoo Finance   │          │    Polygon API    │    │   Mock Data     │
        │     (Primary)     │          │    (Fallback)     │    │  (No API Key)   │
        └───────────────────┘          └───────────────────┘    └─────────────────┘
                    │                                │
                    └────────────────┬───────────────┘
                                     ▼
                    ┌─────────────────────────────────┐
                    │    PRICING EXTRACTION           │
                    │  (VIOLATION: Mixed pricing)     │
                    │  Uses: close, vwap, lastPrice,  │
                    │  midpoint, bid/ask average      │
                    └─────────────────────────────────┘
                                     │
                                     ▼
                    ┌─────────────────────────────────┐
                    │   MINIMAL VALIDATION            │
                    │  (VIOLATION: No chain check)    │
                    │  - Premium > 0                  │
                    │  - OI > 10 (optional)           │
                    │  - Premium sanity check         │
                    └─────────────────────────────────┘
                                     │
                                     ▼
                    ┌─────────────────────────────────┐
                    │     SCORE CALCULATION           │
                    │   (Can score invalid trades)    │
                    └─────────────────────────────────┘
                                     │
                                     ▼
                    ┌─────────────────────────────────┐
                    │       RETURN RESULTS            │
                    │  (Multiple per symbol allowed)  │
                    └─────────────────────────────────┘
```

---

## 🚨 VIOLATIONS BY CATEGORY

### 1. LIVE DATA DURING SCANS (❌ CRITICAL)

| File | Line | Function | Violation |
|------|------|----------|-----------|
| `routes/screener.py` | 226 | `screen_covered_calls()` | `await fetch_stock_quote(symbol, api_key)` - Live call per symbol |
| `routes/screener.py` | 239 | `screen_covered_calls()` | `await fetch_options_chain()` - Live options fetch |
| `routes/screener.py` | 445 | `get_dashboard_opportunities()` | `await fetch_stock_quote(symbol, api_key)` - Live call |
| `routes/screener.py` | 457-461 | `get_dashboard_opportunities()` | `await fetch_options_chain()` - Live weekly + monthly |
| `routes/screener.py` | 681 | `screen_pmcc()` | `await fetch_stock_quote(symbol, api_key)` - Live call |
| `routes/screener.py` | 688-695 | `screen_pmcc()` | `await fetch_options_chain()` - Live LEAPS + short |
| `services/precomputed_scans.py` | 467 | `_fetch_options_yahoo()` | `ticker = yf.Ticker(symbol)` - Live Yahoo call |
| `services/precomputed_scans.py` | 1298 | `_fetch_leaps_yahoo()` | `ticker = yf.Ticker(symbol)` - Live Yahoo call |
| `server.py` | 396 | `fetch_stock_quote()` | `https://api.polygon.io/...` - Live Polygon call |
| `server.py` | 592 | `fetch_options_chain_yahoo()` | `yf.Ticker(symbol)` - Live Yahoo call |

**Impact**: Scan results vary based on when scan runs. Not deterministic.

---

### 2. PRICING VIOLATIONS (❌ CRITICAL)

| File | Line | Current Logic | Required |
|------|------|---------------|----------|
| `routes/screener.py` | 278 | `premium = opt.get("close", 0) or opt.get("vwap", 0)` | SELL = BID only |
| `routes/screener.py` | 481 | `premium = opt.get("close", 0) or opt.get("vwap", 0)` | SELL = BID only |
| `routes/screener.py` | 710 | `premium = opt.get("close", 0) or opt.get("vwap", 0)` | PMCC LEAP BUY = ASK only |
| `routes/screener.py` | 736 | `premium = opt.get("close", 0) or opt.get("vwap", 0)` | PMCC Short = BID only |
| `services/precomputed_scans.py` | 513 | `premium = last_price if last_price > 0 else ((bid + ask) / 2 ...)` | SELL = BID only (midpoint used!) |
| `services/precomputed_scans.py` | 1346 | `premium = last_price if last_price > 0 else ((bid + ask) / 2 ...)` | PMCC LEAP = ASK only |
| `server.py` | 627-630 | `last_price = row.get('lastPrice', 0)` | BID for sell, ASK for buy |

**Current Pricing Priority**:
1. `close` (previous day close price)
2. `vwap` (volume-weighted average)
3. `lastPrice` (last traded price)
4. `(bid + ask) / 2` (midpoint)

**Required Pricing**:
- SELL legs (CC, PMCC short): **BID ONLY**
- BUY legs (PMCC LEAP): **ASK ONLY**
- Reject if BID = 0 or ASK = 0

---

### 3. NO OPTION CHAIN VALIDATION (❌ CRITICAL)

| Validation | Currently Performed? | Required |
|------------|---------------------|----------|
| Expiry exists exactly | ❌ No | ✅ Yes - reject if missing |
| Strike exists exactly | ❌ No | ✅ Yes - reject if missing |
| Both calls and puts exist | ❌ No | ✅ Yes - reject if missing |
| Strikes within ±20% of spot | ❌ No | ✅ Yes - reject partial chains |
| Bid is not null/zero | ⚠️ Partial (`premium > 0`) | ✅ Yes - explicit BID check |
| Timestamp consistency | ❌ No | ✅ Yes - reject stale |
| Chain completeness flag | ❌ No | ✅ Yes - explicit flag |

**Current Validation in `routes/screener.py`**:
```python
# Line 280-281: Only checks premium > 0
if premium <= 0:
    continue

# Line 292-295: Optional OI check
if open_interest > 0 and open_interest < 10:
    continue
```

**Missing**: No validation that the option chain is complete or that the specific strike/expiry combination actually exists in the chain.

---

### 4. DUPLICATE SYMBOLS ALLOWED (❌ VIOLATION)

| File | Function | Issue |
|------|----------|-------|
| `routes/screener.py` | `screen_covered_calls()` | Returns multiple opportunities per symbol |
| `routes/screener.py` | `get_dashboard_opportunities()` | Can show same symbol with weekly AND monthly |
| `services/precomputed_scans.py` | `scan_covered_calls()` | Deduplication exists but only after scoring |

**Current Behavior**: A single symbol can appear multiple times with different strikes/expiries.

**Required**: ONE best trade per symbol.

---

### 5. NO SNAPSHOT METADATA (❌ CRITICAL)

**Required Metadata (Not Currently Stored)**:
- `snapshot_trade_date`
- `options_snapshot_time`
- `options_data_trade_day`
- `data_age_hours`
- `completeness_flag`
- `source`

**Current Storage**: Only stores `computed_at` timestamp in `precomputed_scans` collection.

---

### 6. NO DATA STALENESS CHECK (❌ CRITICAL)

| Check | Exists? | Required Action |
|-------|---------|-----------------|
| Abort if snapshot missing | ❌ No | Scan must fail |
| Abort if completeness_flag = FALSE | ❌ No | Scan must fail |
| Abort if data_age_hours > 48 | ❌ No | Scan must fail |

**Current**: Scans proceed even with partial or missing data.

---

### 7. SCORING INVALID TRADES (❌ VIOLATION)

**Current Flow**:
```
Option found → Filter (basic) → Score → Return
```

**Required Flow**:
```
Option found → Validate chain → Validate structure → PASS? → Score → Return
                                                    → FAIL? → Reject (no score)
```

**Current Scoring** (`routes/screener.py` lines 321-338):
```python
roi_score = min(roi_pct * 15, 40)
iv_score = min(iv_rank / 100 * 20, 20)
delta_score = max(0, 20 - abs(estimated_delta - 0.3) * 50)
protection_score = min(abs(protection), 10) * 2
liquidity_score = 0-10 based on OI

score = roi_score + iv_score + delta_score + protection_score + liquidity_score
```

**Issue**: Score is calculated even if trade structure is invalid.

---

### 8. PMCC STRUCTURAL ISSUES (❌ CRITICAL)

| Requirement | Currently Enforced? |
|-------------|---------------------|
| LEAP DTE ≥ 365 | ⚠️ Partial (180 min in some places) |
| LEAP Delta ≥ 0.70 | ❌ Not enforced |
| LEAP Bid-Ask spread ≤ 10% | ❌ Not checked |
| LEAP OI ≥ 500 | ❌ Not enforced |
| Short DTE 14-45 | ⚠️ Partial |
| Short Delta 0.20-0.30 | ⚠️ Partial |
| Short Strike > LEAP breakeven | ❌ Not validated |
| Width > 0 | ❌ Not validated |

**Current PMCC Logic** (`services/precomputed_scans.py` line 1570+):
- Uses `min_leaps_dte: 180` (should be 365)
- No delta enforcement on LEAP
- No bid-ask spread validation

---

## 📁 FILES REQUIRING CHANGES

| File | Priority | Violations |
|------|----------|------------|
| `/app/backend/routes/screener.py` | 🔴 P0 | Live data, pricing, no validation, duplicates |
| `/app/backend/services/precomputed_scans.py` | 🔴 P0 | Live data, pricing, PMCC structure |
| `/app/backend/server.py` | 🔴 P0 | Data fetch functions need refactor |
| `/app/backend/services/data_provider.py` | 🟡 P1 | Needs snapshot storage layer |
| `/app/backend/routes/watchlist.py` | 🟡 P1 | Uses same flawed pricing |
| `/app/backend/routes/options.py` | 🟡 P1 | Direct API calls |

---

## ✅ PHASE 0 ACCEPTANCE CRITERIA STATUS

| Criteria | Status |
|----------|--------|
| Written architecture map | ✅ Complete |
| List of files/functions that violate rules | ✅ Complete |
| No code changes yet | ✅ Confirmed |

---

## 📋 SUMMARY OF VIOLATIONS

| Category | Count | Severity |
|----------|-------|----------|
| Live data during scans | 10+ locations | 🔴 Critical |
| Incorrect pricing (not BID/ASK) | 7 locations | 🔴 Critical |
| No chain validation | System-wide | 🔴 Critical |
| No snapshot metadata | System-wide | 🔴 Critical |
| Duplicate symbols allowed | 3 locations | 🟡 High |
| Scoring invalid trades | System-wide | 🟡 High |
| PMCC structural gaps | 8 requirements | 🔴 Critical |

---

## READY FOR PHASE 1?

All PHASE 0 deliverables complete:
- ✅ Architecture map documented
- ✅ All violations identified with file/line references
- ✅ No code changes made

**Awaiting approval to proceed to PHASE 1: Architecture Hard Gate**
