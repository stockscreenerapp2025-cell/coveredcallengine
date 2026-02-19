# CCE Forensic Invariant Audit

## Document Information
- **Audit Type**: Forensic Code Inspection
- **Date**: December 2025
- **Constraint**: NO CODE CHANGES - Documentation Only
- **Purpose**: Identify deviations between intended system invariants and actual implementation

---

## Table of Contents
1. [Invariant Analysis (A-H)](#1-invariant-analysis-a-h)
2. [Four-Path Comparison](#2-four-path-comparison)
3. [Timing Alignment Analysis](#3-timing-alignment-analysis)
4. [Deviation Summary](#4-deviation-summary)

---

## 1. Invariant Analysis (A-H)

### Invariant A: Single Underlying Price Policy Across All Pages

#### Intended Invariant
All pages (Dashboard, Screener, PMCC, Simulator, Watchlist) must use the same underlying price source for consistency.

#### Implementation Locations

| File | Function | Price Source |
|------|----------|--------------|
| `/app/backend/services/yf_pricing.py:46-100` | `get_underlying_price_yf()` | **Declared single source of truth** |
| `/app/backend/services/eod_pipeline.py:159-343` | `fetch_bulk_quotes_sync()` | `yf.download()` → `Close[-1]` (session_close) |
| `/app/backend/services/data_provider.py:368-453` | `_fetch_stock_quote_yahoo_sync()` | Calls `get_underlying_price_yf()` ✅ |
| `/app/backend/services/data_provider.py:287-334` | `_fetch_live_stock_quote_yahoo_sync()` | Calls `get_underlying_price_yf()` ✅ |

#### Endpoints That Bypass or Partially Implement

| Endpoint | File:Line | Bypasses? | Details |
|----------|-----------|-----------|---------|
| Dashboard Top 10 | `screener_snapshot.py:1716-1809` | NO | Reads from `scan_results_cc.stock_price` (MongoDB) |
| CC Screener | `screener_snapshot.py:1217-1355` | NO | Reads from `scan_results_cc.stock_price` (MongoDB) |
| PMCC Screener | `screener_snapshot.py:1605-1715` | NO | Reads from `scan_results_pmcc.stock_price` (MongoDB) |
| Watchlist (default) | `watchlist.py:746-875` | NO | Reads from `symbol_snapshot.session_close_price` (MongoDB) |
| Watchlist (live mode) | `watchlist.py:786-793` | **PARTIAL** | Calls `fetch_live_stock_quotes_batch()` → Yahoo LIVE |
| Simulator | `simulator.py:40` | **YES** | Imports `fetch_live_stock_quote` directly |

#### Fallback/Default Behaviors

| Location | Fallback | Silent? |
|----------|----------|---------|
| `eod_pipeline.py:268-285` | If `session_close_price` is None, use `prior_close_price` | **SILENT** (logged as warning) |
| `yf_pricing.py:139-157` | If `fast_info.last_price` fails, use `info.regularMarketPrice` | **SILENT** (logged as debug) |
| `data_provider.py:464-490` | If Yahoo fails, try Polygon backup | **EXPLICIT** (source field set) |

#### **DEVIATION FINDING A1**
- **Location**: `simulator.py:40`, `watchlist.py:786-793`
- **Issue**: Simulator and Watchlist (live mode) use LIVE intraday prices while scans use EOD session_close
- **Classification**: **Policy Drift** - Intentional by design (Rule #2 in simulator.py docstring), but creates price divergence between pages

#### **DEVIATION FINDING A2**
- **Location**: `eod_pipeline.py:268-285`
- **Issue**: Fallback from session_close to prior_close is silent (only logged as warning)
- **Classification**: **Silent Fallback** - User not informed when prior_close is used

---

### Invariant B: CC Premium Enforcement (SELL = BID Only)

#### Intended Invariant
Covered Call short leg premium MUST use BID price only. No fallbacks to lastPrice, mid, ask, or theoretical.

#### Implementation Locations

| File | Function | Line | Enforcement |
|------|----------|------|-------------|
| `/app/backend/services/pricing_rules.py:30-51` | `get_sell_price()` | 30-51 | **CORRECT**: Returns `(None, "INVALID_BID")` if bid ≤ 0 |
| `/app/backend/services/yf_pricing.py:332-346` | `extract_option_price_for_sell()` | 332-346 | **CORRECT**: Returns `(None, "INVALID_BID")` if bid invalid |
| `/app/backend/services/eod_pipeline.py:1212-1217` | `validate_cc_option()` | 1212-1217 | **CORRECT**: Hard reject if bid ≤ 0 |
| `/app/backend/utils/pricing_utils.py:184-206` | `enforce_pricing_policy_cc()` | 184-206 | **CORRECT**: Raises exception if premium_used ≠ premium_bid |

#### Endpoints That Bypass or Partially Implement

| Endpoint | File:Line | Issue |
|----------|-----------|-------|
| CC Transform | `screener_snapshot.py:1076-1089` | **COMPLIANT**: Validates premium_bid > 0, forces premium_used = premium_bid |
| CC Precomputed Transform | `precomputed_scans.py:169-200` | **COMPLIANT**: Uses `premium_bid` as `premium` |
| Watchlist Live | `watchlist.py:126-136` | **COMPLIANT**: Rejects if bid ≤ 0 |

#### Fallback/Default Behaviors

| Location | Code | Issue |
|----------|------|-------|
| `screener_snapshot.py:447` | `premium = contract.get("bid", 0) or contract.get("premium", 0)` | **POTENTIAL BYPASS**: Falls back to generic "premium" field if bid is 0 |
| `screener_snapshot.py:1076` | `premium_bid = sanitize_money(r.get("premium_bid") or r.get("premium"))` | **POTENTIAL BYPASS**: Falls back to generic "premium" |

#### **DEVIATION FINDING B1**
- **Location**: `screener_snapshot.py:447`, `screener_snapshot.py:1076`
- **Issue**: Fallback to generic `premium` field when `bid` is 0/missing
- **Classification**: **Silent Fallback** - The `or` clause allows non-bid values to slip through
- **Impact**: If `premium_bid` is 0 but `premium` has a value, that value is used without verification it's actually the bid

---

### Invariant C: PMCC Premium Enforcement (BUY = ASK, SELL = BID)

#### Intended Invariant
- LEAP (long leg): BUY at ASK only
- Short call: SELL at BID only
- Net debit = leap_ask - short_bid

#### Implementation Locations

| File | Function | Line | Enforcement |
|------|----------|------|-------------|
| `/app/backend/services/pricing_rules.py:54-75` | `get_buy_price()` | 54-75 | **CORRECT**: Returns `(None, "INVALID_ASK")` if ask ≤ 0 |
| `/app/backend/services/eod_pipeline.py:1287-1322` | `validate_pmcc_structure()` | 1287-1322 | **CORRECT**: Hard reject if leap_ask ≤ 0 or short_bid ≤ 0 |
| `/app/backend/services/eod_pipeline.py:1362-1369` | Net debit calculation | 1362-1369 | **CORRECT**: `net_debit = leap_ask - short_bid` |
| `/app/backend/utils/pricing_utils.py:209-238` | `enforce_pricing_policy_pmcc()` | 209-238 | **CORRECT**: Raises exception if leap_used ≠ leap_ask or short_used ≠ short_bid |

#### Endpoints That Bypass or Partially Implement

| Endpoint | File:Line | Issue |
|----------|-----------|-------|
| PMCC Transform | `screener_snapshot.py:1483-1499` | **COMPLIANT**: Forces leap_used = leap_ask, short_used = short_bid |
| PMCC Enrichment | `screener_snapshot.py:548-554` | **POTENTIAL BYPASS**: See below |

#### Fallback/Default Behaviors

| Location | Code | Issue |
|----------|------|-------|
| `screener_snapshot.py:548` | `leap_ask = leap_contract.get("ask", 0) or leap_contract.get("premium", 0)` | **POTENTIAL BYPASS**: Falls back to generic "premium" |
| `screener_snapshot.py:554` | `short_bid = short_contract.get("bid", 0) or short_contract.get("premium", 0)` | **POTENTIAL BYPASS**: Falls back to generic "premium" |
| `screener_snapshot.py:1483-1485` | `leap_ask = sanitize_money(r.get("leap_ask") or r.get("leaps_ask"))` | Field name inconsistency (leap_ask vs leaps_ask) |

#### **DEVIATION FINDING C1**
- **Location**: `screener_snapshot.py:548`, `screener_snapshot.py:554`
- **Issue**: Fallback to generic `premium` field when `ask`/`bid` is 0/missing in enrichment function
- **Classification**: **Silent Fallback** - Non-bid/ask values can slip through

#### **DEVIATION FINDING C2**
- **Location**: `screener_snapshot.py:1483`
- **Issue**: Field name inconsistency (`leap_ask` vs `leaps_ask`) suggests different code paths may store differently
- **Classification**: **Bypassed Shared Util** - Inconsistent field naming

---

### Invariant D: No Silent Fallbacks for premium_used, bid/ask, Contract Selection

#### Intended Invariant
Any fallback affecting premium_used, bid, ask, or contract selection must be EXPLICIT to the user.

#### Implementation Analysis

| Location | Fallback | Silent? | Impact |
|----------|----------|---------|--------|
| `screener_snapshot.py:447` | `bid` → `premium` | **SILENT** | Premium source unclear |
| `screener_snapshot.py:548` | `ask` → `premium` | **SILENT** | LEAP cost source unclear |
| `screener_snapshot.py:554` | `bid` → `premium` | **SILENT** | Short premium source unclear |
| `screener_snapshot.py:1076` | `premium_bid` → `premium` | **SILENT** | Row may use non-bid value |
| `screener_snapshot.py:1483` | `leap_ask` → `leaps_ask` | **SILENT** | Field name mismatch tolerated |
| `watchlist.py:185-188` | `iv_rank` → 50.0 (neutral) | **SILENT** | Neutral IV rank assumed |

#### **DEVIATION FINDING D1**
- **Location**: Multiple locations above
- **Issue**: All `or` fallbacks for pricing fields are silent
- **Classification**: **Silent Fallback** - User/admin has no visibility into when fallbacks are used
- **Detection Method**: Would require checking `premium_display_source` field (if populated)

---

### Invariant E: Scan Endpoints Must Not Call Live Providers

#### Intended Invariant
All scan endpoints (Dashboard, Screener, PMCC) must read from MongoDB ONLY during request/response cycle.

#### Implementation Locations

| File | Line | Declaration |
|------|------|-------------|
| `/app/backend/routes/screener_snapshot.py:1-22` | Docstring | **DECLARED**: "NO LIVE YAHOO CALLS during request/response cycle" |
| `/app/backend/routes/precomputed_scans.py:1-21` | Docstring | **DECLARED**: "No Yahoo live calls during request/response" |

#### Endpoints Verification

| Endpoint | File:Function | Live Calls? | Evidence |
|----------|---------------|-------------|----------|
| `/api/screener/covered-calls` | `screener_snapshot.py:screen_covered_calls()` | **NO** | Reads from `scan_results_cc` only |
| `/api/screener/pmcc` | `screener_snapshot.py:screen_pmcc()` | **NO** | Reads from `scan_results_pmcc` only |
| `/api/screener/dashboard-opportunities` | `screener_snapshot.py:get_dashboard_opportunities()` | **NO** | Reads from `scan_results_cc` only |
| `/api/scans/covered-call/{profile}` | `precomputed_scans.py` | **NO** | Reads from `scan_results_cc` only |
| `/api/scans/pmcc/{profile}` | `precomputed_scans.py` | **NO** | Reads from `scan_results_pmcc` only |

#### **DEVIATION FINDING E1**
- **Finding**: No deviation detected
- **Status**: **COMPLIANT** - All scan endpoints read from MongoDB only
- **Verification**: Confirmed by code inspection - no `fetch_*` or `yfinance` imports used in request paths

---

### Invariant F: Precomputed and Computed Scans Produce Identical Results When Pinned to Same Snapshot

#### Intended Invariant
Given the same `run_id`, precomputed scans (`/api/scans/*`) and computed scans (`/api/screener/*`) must return identical results.

#### Implementation Analysis

| Path | Data Source | Transform Function | Pricing Rule |
|------|-------------|-------------------|--------------|
| `/api/screener/covered-calls` | `scan_results_cc` | `_transform_cc_result()` | Line 1076: premium_bid |
| `/api/scans/covered-call/{profile}` | `scan_results_cc` | `_transform_cc_for_scans()` | Line 183: premium_bid |
| `/api/screener/pmcc` | `scan_results_pmcc` | `_transform_pmcc_result()` | Line 1480: short_bid |
| `/api/scans/pmcc/{profile}` | `scan_results_pmcc` | `_transform_pmcc_for_scans()` | Line 210: short_bid |

#### Transform Function Comparison (CC)

| Field | `_transform_cc_result()` (screener_snapshot.py:1070-1210) | `_transform_cc_for_scans()` (precomputed_scans.py:169-200) |
|-------|----------------------------------------------------------|-----------------------------------------------------------|
| premium | `premium_bid` (Line 1126) | `premium_bid` (Line 183) |
| stock_price | `stock_price` (Line 1103) | `stock_price` (Line 174) |
| Rounding | `sanitize_money()` | `sanitize_money()` |
| IV handling | `iv_decimal`, `iv_percent` dual fields | `iv`, `iv_pct` |

#### **DEVIATION FINDING F1**
- **Location**: `screener_snapshot.py:1070-1210` vs `precomputed_scans.py:169-250`
- **Issue**: Different transform functions with different field structures
- **Classification**: **Bypassed Shared Util** - Two separate transform implementations instead of one shared function
- **Impact**: Field naming differences (`iv_decimal` vs `iv`), scoring calculations may differ
- **Evidence**: 
  - screener_snapshot.py exports `premium_display`, `premium_display_source`
  - precomputed_scans.py does not export these fields

#### **DEVIATION FINDING F2**
- **Location**: Risk profile filtering
- **Issue**: `/api/screener/covered-calls` applies filters via query params, `/api/scans/covered-call/{profile}` uses hardcoded profile thresholds
- **Classification**: **Policy Drift** - Different filtering logic
- **Evidence**: 
  - `screener_snapshot.py:880-891` - Generic query builder
  - `precomputed_scans.py:96-118` - Hardcoded profile thresholds (conservative: score ≥ 70, delta ≤ 0.35)

---

### Invariant G: Previous Close Must Represent NYSE Trading Day

#### Intended Invariant
`prior_close_price` must be the official close of the most recent NYSE trading day, not an arbitrary historical value.

#### Implementation Locations

| File | Function | Line | Method |
|------|----------|------|--------|
| `/app/backend/services/eod_pipeline.py:239-247` | `fetch_bulk_quotes_sync()` | 239-247 | Uses `df.iloc[-2]["Close"]` from 2-day download |
| `/app/backend/services/data_provider.py:181-200` | `get_last_trading_day_et()` | 181-200 | Calculates last trading day with weekend roll-back |

#### Analysis of `fetch_bulk_quotes_sync()`

```python
# Lines 239-247
if len(symbol_df) >= 2:
    prev_row = symbol_df.iloc[-2]
    prior_close_price = prev_row.get('Close')
else:
    # Only 1 day of data, use Open as approximation
    prior_close_price = latest.get('Open')
```

#### **DEVIATION FINDING G1**
- **Location**: `eod_pipeline.py:247`
- **Issue**: When only 1 day of data is returned, `Open` is used as `prior_close_price` approximation
- **Classification**: **Silent Fallback** - Using Open instead of prior close without explicit flagging
- **Impact**: `prior_close_price` may not represent actual prior NYSE close

#### **DEVIATION FINDING G2**
- **Location**: `data_provider.py:181-200`
- **Issue**: `get_last_trading_day_et()` does not model US market holidays
- **Classification**: **Policy Drift** - Holidays treated as closed but prior_close may be 2+ days stale
- **Evidence**: Comment at line 157-161: "This function does NOT model US market holidays"

---

### Invariant H: Underlying Price and Options Chain Must Be Time-Aligned (Same Snapshot Window)

#### Intended Invariant
The stock price used for calculations must be from the same time window as the options chain data.

#### Implementation Analysis

| Data | Source | Timestamp Field | Storage |
|------|--------|-----------------|---------|
| Stock Price | `yf.download()` | `as_of` | `scan_results_*.stock_price` |
| Options Chain | `ticker.option_chain()` | `chain_fetch_time` | `scan_results_*.chain_fetch_time` (if stored) |

#### EOD Pipeline Flow (eod_pipeline.py)

1. **Stage 1** (Lines 159-343): Bulk quote fetch → `session_close_price` stored
2. **Stage 2** (Lines varies): Option chain fetch → chains fetched per-symbol with delay
3. **Time Gap**: Between Stage 1 and Stage 2, several minutes may elapse

#### **DEVIATION FINDING H1**
- **Location**: `eod_pipeline.py` Stage 1 vs Stage 2
- **Issue**: Stock prices are fetched in bulk first, then option chains are fetched sequentially with 250ms delays
- **Classification**: **Timing Misalignment** - Quote fetch and chain fetch are NOT atomic
- **Evidence**: 
  - Line 139: `BULK_QUOTE_BATCH_SIZE = 50` (quotes fetched in batches)
  - Line 145: `CHAIN_SYMBOL_DELAY_MS = 250` (chains fetched 250ms apart)
  - Total chain fetch time for 1500 symbols ≈ 6+ minutes

#### **DEVIATION FINDING H2**
- **Location**: `scan_results_cc` / `scan_results_pmcc` collections
- **Issue**: No `chain_as_of` timestamp stored in scan results
- **Classification**: **Timing Misalignment** - Cannot verify quote/chain time alignment
- **Evidence**: Searching for `chain_as_of` or `chain_fetch_time` in schema shows no such field

#### **DEVIATION FINDING H3**
- **Location**: `scan_runs` collection
- **Issue**: Only `as_of` (run start time) is stored, not per-symbol timestamps
- **Classification**: **Snapshot Misalignment** - All symbols share same `as_of` even though they were processed sequentially

---

## 2. Four-Path Comparison

### 2.1 Covered Call - Computed (`/api/screener/covered-calls`)

| Aspect | Implementation | File:Line |
|--------|----------------|-----------|
| **Underlying Price Source** | `scan_results_cc.stock_price` (from MongoDB) | `screener_snapshot.py:880` |
| **Options Chain Source** | `scan_results_cc` (pre-computed, from MongoDB) | `screener_snapshot.py:938` |
| **Premium Rule Applied** | SELL = BID (`premium_bid`) | `screener_snapshot.py:1076-1089` |
| **Rounding/Sanitization** | `sanitize_money()` - 2 decimal | `screener_snapshot.py:1103-1126` |
| **run_id / as_of** | `run_id` from latest `scan_runs` where status=completed | `screener_snapshot.py:826-838` |
| **Divergence from Invariants** | F1, F2 - Different transform, different filter logic | See Section 1 |

### 2.2 Covered Call - Precomputed (`/api/scans/covered-call/{profile}`)

| Aspect | Implementation | File:Line |
|--------|----------------|-----------|
| **Underlying Price Source** | `scan_results_cc.stock_price` (from MongoDB) | `precomputed_scans.py:115` |
| **Options Chain Source** | `scan_results_cc` (pre-computed, from MongoDB) | `precomputed_scans.py:115` |
| **Premium Rule Applied** | SELL = BID (`premium_bid`) | `precomputed_scans.py:183` |
| **Rounding/Sanitization** | `sanitize_money()` - 2 decimal | `precomputed_scans.py:174-199` |
| **run_id / as_of** | `run_id` from `_get_latest_eod_run_id()` | `precomputed_scans.py:63-83` |
| **Divergence from Invariants** | F1 - Different transform function, field names differ | See Section 1 |

### 2.3 PMCC - Computed (`/api/screener/pmcc`)

| Aspect | Implementation | File:Line |
|--------|----------------|-----------|
| **Underlying Price Source** | `scan_results_pmcc.stock_price` (from MongoDB) | `screener_snapshot.py:1654` |
| **Options Chain Source** | `scan_results_pmcc` (pre-computed, from MongoDB) | `screener_snapshot.py:1654` |
| **Premium Rule Applied** | BUY LEAP = ASK (`leap_ask`), SELL Short = BID (`short_bid`) | `screener_snapshot.py:1480-1499` |
| **Rounding/Sanitization** | `sanitize_money()` - 2 decimal | `screener_snapshot.py:1556-1564` |
| **run_id / as_of** | `run_id` from `_get_latest_eod_run_id()` | `screener_snapshot.py:1649` |
| **Divergence from Invariants** | C1, C2 - Fallback to generic `premium`, field name inconsistency | See Section 1 |

### 2.4 PMCC - Precomputed (`/api/scans/pmcc/{profile}`)

| Aspect | Implementation | File:Line |
|--------|----------------|-----------|
| **Underlying Price Source** | `scan_results_pmcc.stock_price` (from MongoDB) | `precomputed_scans.py:154` |
| **Options Chain Source** | `scan_results_pmcc` (pre-computed, from MongoDB) | `precomputed_scans.py:154` |
| **Premium Rule Applied** | BUY LEAP = ASK, SELL Short = BID | `precomputed_scans.py:210-230` (assumed) |
| **Rounding/Sanitization** | `sanitize_money()` - 2 decimal | `precomputed_scans.py` |
| **run_id / as_of** | `run_id` from `_get_latest_eod_run_id()` | `precomputed_scans.py:63-83` |
| **Divergence from Invariants** | F1 - Different transform function | See Section 1 |

### 2.5 Comparison Table Summary

| Aspect | CC Computed | CC Precomputed | PMCC Computed | PMCC Precomputed |
|--------|-------------|----------------|---------------|------------------|
| Data Source | `scan_results_cc` | `scan_results_cc` | `scan_results_pmcc` | `scan_results_pmcc` |
| Transform Func | `_transform_cc_result()` | `_transform_cc_for_scans()` | `_transform_pmcc_result()` | (separate) |
| **SAME DATA?** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes |
| **SAME TRANSFORM?** | ❌ No | ❌ No | ❌ No | ❌ No |
| **SAME OUTPUT?** | ⚠️ Similar but not identical | ⚠️ Similar | ⚠️ Similar | ⚠️ Similar |

---

## 3. Timing Alignment Analysis

### 3.1 Previous Close Calculation

| Source | Method | Holiday Handling | File:Line |
|--------|--------|------------------|-----------|
| EOD Pipeline | `yf.download(period="2d")` → `df.iloc[-2]["Close"]` | None (uses yfinance data) | `eod_pipeline.py:239-247` |
| Data Provider | `get_last_trading_day_et()` → weekday calculation | Weekend only (no holidays) | `data_provider.py:181-200` |

**Issue**: If Monday is a holiday, `get_last_trading_day_et()` returns Monday's date, but the actual last trading day was Friday. This can cause mismatches.

### 3.2 Chain As-Of Storage

| Collection | Has `chain_as_of`? | Has `quote_as_of`? | Has `run_id`? |
|------------|-------------------|-------------------|---------------|
| `scan_results_cc` | ❌ NO | ❌ NO | ✅ YES |
| `scan_results_pmcc` | ❌ NO | ❌ NO | ✅ YES |
| `scan_runs` | N/A | ✅ YES (`as_of` = run start) | ✅ YES |
| `symbol_snapshot` | ❌ NO | ✅ YES (`as_of`) | ❌ NO |

**Issue**: Cannot verify that `quote_as_of` and `chain_as_of` match because `chain_as_of` is not stored.

### 3.3 Run ID Pinning Enforcement

| Endpoint | Enforces run_id? | Evidence |
|----------|------------------|----------|
| `/api/screener/covered-calls` | **IMPLICIT** | Uses `_get_latest_eod_run_id()` internally |
| `/api/screener/pmcc` | **IMPLICIT** | Uses `_get_latest_eod_run_id()` internally |
| `/api/scans/covered-call/{profile}` | **IMPLICIT** | Uses `_get_latest_eod_run_id()` internally |
| `/api/scans/pmcc/{profile}` | **IMPLICIT** | Uses `_get_latest_eod_run_id()` internally |

**Issue**: No endpoint allows explicit `run_id` parameter for historical comparison. All endpoints return latest run only.

---

## 4. Deviation Summary

### 4.1 Classified Deviations

| ID | Invariant | Location | Root Cause | Classification |
|----|-----------|----------|------------|----------------|
| A1 | A | `simulator.py:40`, `watchlist.py:786` | Different price sources for user paths vs scan paths | **Policy Drift** |
| A2 | A | `eod_pipeline.py:268-285` | Fallback from session_close to prior_close | **Silent Fallback** |
| B1 | B | `screener_snapshot.py:447,1076` | `or` clause allows generic `premium` | **Silent Fallback** |
| C1 | C | `screener_snapshot.py:548,554` | `or` clause allows generic `premium` | **Silent Fallback** |
| C2 | C | `screener_snapshot.py:1483` | Field name inconsistency (leap_ask vs leaps_ask) | **Bypassed Shared Util** |
| D1 | D | Multiple | All `or` fallbacks for pricing are silent | **Silent Fallback** |
| F1 | F | `screener_snapshot.py` vs `precomputed_scans.py` | Different transform functions | **Bypassed Shared Util** |
| F2 | F | Risk profile filtering | Different filter logic per endpoint | **Policy Drift** |
| G1 | G | `eod_pipeline.py:247` | Open used as prior_close fallback | **Silent Fallback** |
| G2 | G | `data_provider.py:157-161` | No holiday modeling | **Policy Drift** |
| H1 | H | `eod_pipeline.py` Stage 1-2 | Non-atomic quote/chain fetch | **Timing Misalignment** |
| H2 | H | `scan_results_*` schema | No `chain_as_of` stored | **Timing Misalignment** |
| H3 | H | `scan_runs` schema | Single `as_of` for all symbols | **Snapshot Misalignment** |

### 4.2 Classification Summary

| Classification | Count | IDs |
|----------------|-------|-----|
| **Policy Drift** | 4 | A1, F2, G2, (partially A1) |
| **Bypassed Shared Util** | 2 | C2, F1 |
| **Silent Fallback** | 6 | A2, B1, C1, D1, G1 |
| **Snapshot Misalignment** | 1 | H3 |
| **Timing Misalignment** | 2 | H1, H2 |

### 4.3 Impact Severity Assessment

| ID | Severity | Impact Description |
|----|----------|-------------------|
| A1 | **MEDIUM** | Price divergence between Simulator/Watchlist and Screener pages |
| B1 | **HIGH** | CC premium may not be true BID, affecting ROI calculations |
| C1 | **HIGH** | PMCC economics may use wrong prices, affecting solvency checks |
| F1 | **MEDIUM** | API responses from different endpoints have structural differences |
| H1 | **MEDIUM** | Quote and chain may be from different time windows (~6 min gap) |
| H2 | **LOW** | Cannot audit time alignment after the fact |

---

## Appendix A: File Reference Index

| Invariant | Primary Files |
|-----------|---------------|
| A (Price Policy) | `yf_pricing.py`, `data_provider.py`, `eod_pipeline.py` |
| B (CC Premium) | `pricing_rules.py`, `eod_pipeline.py:1212-1217`, `screener_snapshot.py:1076` |
| C (PMCC Premium) | `pricing_rules.py`, `eod_pipeline.py:1236-1401`, `screener_snapshot.py:1480-1499` |
| D (Silent Fallbacks) | `screener_snapshot.py:447,548,554,1076,1483` |
| E (No Live Calls) | `screener_snapshot.py`, `precomputed_scans.py` |
| F (Computed = Precomputed) | `screener_snapshot.py:1070-1210` vs `precomputed_scans.py:169-250` |
| G (Previous Close) | `eod_pipeline.py:239-247`, `data_provider.py:181-200` |
| H (Time Alignment) | `eod_pipeline.py:139,145`, `scan_runs` schema |

---

*Audit completed December 2025 - NO CODE CHANGES MADE*
