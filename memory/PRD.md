# Covered Call Engine - Product Requirements Document

## Last Updated
2026-02-18 - Critical Scan & Watchlist Regression Fix COMPLETE

---

## Critical Scan & Watchlist Regression Fix - COMPLETED 2026-02-18

### Status: ✅ COMPLETE

### Issues Fixed:

1. **Watchlist Runtime Error** (`TypeError: items.map is not a function`)
   - **Root Cause:** Backend returned `{ items: [...] }` but frontend expected array directly
   - **Fix:** Updated `Watchlist.js` to extract `items` from response object

2. **Dashboard-Opportunities Cloudflare 520 Error**
   - **Root Cause:** `_transform_cc_result()` returns tuple `(result, error_info)` but was incorrectly used in list comprehension without unpacking
   - **Fix:** Changed line 1762 in `screener_snapshot.py` to properly unpack the tuple

3. **Pre-computed Scan Count Mismatch** (28 shown on card, 2 returned)
   - **Root Cause:** `/api/scans/available` read counts from legacy `precomputed_scans` collection while detail endpoints read from EOD `scan_results_cc` collection
   - **Fix:** Rewrote `get_available_scans()` to compute counts from EOD collections using same filtering logic as detail endpoints

### Files Modified:

| File | Changes |
|------|---------|
| `/frontend/src/pages/Watchlist.js` | Line 65: Extract `items` array from response object |
| `/backend/routes/screener_snapshot.py` | Lines 1761-1766: Fixed tuple unpacking in dashboard-opportunities |
| `/backend/routes/precomputed_scans.py` | Lines 263-398: Rewrote `get_available_scans()` to use EOD collections |

### Verification:

| Endpoint | Response |
|----------|----------|
| Dashboard Top 10 | `total: 3, weekly: 2, monthly: 1` ✅ |
| CC Aggressive Scan | `total: 2, opportunities: 2` ✅ |
| PMCC Conservative | `total: 0, opportunities: 0` ✅ |
| Watchlist | No runtime error, items displayed ✅ |

### Confirmations:
- ✅ Filter → Sort → Limit order verified (limit applied after filtering)
- ✅ Total count matches returned results count
- ✅ Summary counts match detail results for pre-computed scans
- ✅ Response schema consistent (`{ total, results/opportunities }`)

---

## NaN Conversion Crash Fix in EOD Pipeline - VERIFIED 2026-02-18

### Status: ✅ VERIFIED

### Problem:
The EOD pipeline was crashing with `ValueError: cannot convert float NaN to integer` when parsing the 'Volume' field from `yfinance`, which sometimes returns `NaN`. This caused 370 symbols to be incorrectly excluded with `MISSING_QUOTE` reason.

### Solution:
Added `safe_int()` and `safe_float()` helper functions in `/app/backend/services/eod_pipeline.py` that:
1. Check for `NaN` values BEFORE attempting type casting
2. Handle numpy scalars correctly
3. Return safe defaults instead of crashing

### Files Modified:

| File | Changes |
|------|---------|
| `/backend/services/eod_pipeline.py` | Lines 91-132: Added `safe_int()` and `safe_float()` helpers |

### Verification Results (EOD Run 2026-02-18):

| Metric | Before Fix | After Fix |
|--------|------------|-----------|
| MISSING_QUOTE exclusions | 370 | 0 |
| Total exclusions | 412 | 33 |
| NaN-related errors | Multiple crashes | 0 |
| Symbols included | ~200 | 589 |

### Current Exclusion Breakdown:
- `MISSING_QUOTE_FIELDS`: 30 (legitimate - both price fields were None)
- `MISSING_CHAIN`: 3 (legitimate - no option expirations available)

### API Verification:
```
GET /api/screener/covered-calls - Returns 3 results ✅
GET /api/admin/eod-snapshot/status - Returns correct EOD status ✅
```

---

## Freeze at Market Close Policy Fix - COMPLETED 2026-02-17

### Status: ✅ COMPLETE

### Problem:
Price/state mismatches were causing mass rejections due to:
1. Admin Data Quality reporting "DELAYED" price source during AFTERHOURS/PREMARKET
2. EOD bulk quote selecting wrong price field during OPEN hours

### Solution:

**A) Admin Data Quality price_source mapping** (`/app/backend/routes/screener_snapshot.py`):
- Changed: Outside market OPEN (CLOSED, AFTERHOURS, PREMARKET) now reports `price_source = "PREV_CLOSE"`
- Previously: AFTERHOURS/PREMARKET incorrectly reported "DELAYED"

**B) EOD bulk quote selected price** (`/app/backend/services/eod_pipeline.py`):
- ALWAYS use `session_close_price` (frozen close from last trading session)
- OPEN: session_close_price (yesterday's close)
- CLOSED: session_close_price (today's close after EOD)
- Both `session_close_price` and `prior_close_price` are still stored for debugging

### Verification:
```
Market State: AFTERHOURS
Price Source: PREV_CLOSE  (was "DELAYED" before fix)

EOD Pipeline (AAPL):
  price = session_close_price: True
  stock_price_source: SESSION_CLOSE
```

---


## PMCC 20% Solvency Tolerance Fix - COMPLETED 2026-02-17

### Status: ✅ COMPLETE

### Problem:
Precomputed PMCC scans were returning **zero opportunities** because the strict solvency rule (`width > net_debit`) was mathematically impossible to satisfy with pure ASK/BID pricing. When buying LEAPs at ASK and selling short calls at BID, the net_debit almost always exceeds the width due to bid-ask spreads.

### Solution:
Relaxed the solvency rule to allow a **20% tolerance**: `net_debit <= width * 1.20`

### Files Modified:

| File | Changes |
|------|---------|
| `/backend/services/pricing_rules.py` | Line 78-108: `validate_pmcc_solvency()` now uses 20% tolerance |
| `/backend/services/eod_pipeline.py` | Line 1286-1292: `validate_pmcc_structure()` updated to match |

### Verification Results:

| Profile | Before Fix | After Fix |
|---------|------------|-----------|
| Conservative | 0 | 8 opportunities |
| Balanced | 0 | 1 opportunity |
| Aggressive | 0 | 0 (stricter criteria) |

### Sample PMCC Opportunities Now Passing:
```
PFE:  width=4.00, net_debit=4.52, threshold=4.80 ✓
XOM:  width=30.00, net_debit=32.11, threshold=36.00 ✓
TFC:  width=10.00, net_debit=11.85, threshold=12.00 ✓
ABBV: width=55.00, net_debit=56.02, threshold=66.00 ✓
SLB:  width=15.00, net_debit=15.36, threshold=18.00 ✓
```

### Test Coverage:
- 23 unit tests created in `/app/backend/tests/test_pmcc_solvency_tolerance.py`
- 100% pass rate

---


## IV Rank & Analyst Enrichment - COMPLETED 2026-02-17

### Status: ✅ COMPLETE

### Objective:
Ensure ALL strategy rows returned by live endpoints include consistent, non-null (when available) values for:
- `iv_rank` (0-100 or null)
- `analyst_rating` (string or null)
- `analyst_opinions` (int or null)
- `target_price_mean/high/low` (numbers or null)

### Implementation:

| File | Purpose |
|------|---------|
| `/backend/services/enrichment_service.py` | **NEW** - Single enrichment function for IV Rank + Analyst data |
| `/backend/routes/screener_snapshot.py` | Updated `_merge_analyst_enrichment()` to fall back to live Yahoo |
| `/backend/routes/watchlist.py` | Added enrichment at response time |
| `/backend/routes/simulator.py` | Added enrichment at response time |

### Enrichment Function:
```python
enrich_row(symbol, row, *, stock_price, expiry, strike, iv, skip_analyst, skip_iv_rank)
```

### Analyst Enrichment:
- Source: Yahoo Finance `ticker.info`
- Fields: `analyst_rating`, `analyst_opinions`, `target_price_mean/high/low`
- Rule: If missing → return nulls. Do not fake.

### IV Rank Enrichment:
- Method: Lightweight chain percentile
- Uses option chain IVs within ±15% of spot
- Requires ≥20 valid IV points
- Rule: Never return 0 unless rank truly computes to 0

### Debug Flag:
`?debug_enrichment=1` adds to each row:
- `enrichment_applied`: true/false
- `enrichment_sources`: { analyst: "yahoo"|"db"|"none", iv_rank: "chain_percentile"|"none" }

### Verified Endpoints:
```
CCL Results (debug_enrichment=1):
  Dashboard Top 10: enrichment_applied=true, analyst="yahoo"
  Custom CC Scan: enrichment_applied=true, analyst="yahoo"
  Watchlist: enrichment_applied=true, analyst="yahoo"
  Simulator: enrichment_applied=true, analyst="yahoo"
```

---

## Global yfinance Pricing Consistency - COMPLETED 2026-02-17

### Status: ✅ COMPLETE

### Objective:
Enforce identical yfinance pricing fields across ALL modules (Dashboard, CC, PMCC, Customised Scans, Precomputed Scans, Simulator, Watchlist).

### Single Source of Truth Helpers:

| Helper | File | Purpose |
|--------|------|---------|
| `get_underlying_price_yf()` | `/backend/services/yf_pricing.py` | Get stock price using correct field based on market state |
| `get_option_chain_yf()` | `/backend/services/yf_pricing.py` | Get option chain with consistent column names |

### Pricing Rules (Enforced Globally):

| Market State | Field Used | Forbidden Fields |
|--------------|------------|------------------|
| **OPEN** | `fast_info.last_price` (primary), `info.regularMarketPrice` (fallback) | postMarketPrice, preMarketPrice, currentPrice |
| **CLOSED** | `history(period="5d")["Close"].iloc[-1]` | regularMarketPrice, regularMarketPreviousClose |

### Option Chain Columns (Consistent Everywhere):
- `bid` (used for SELL)
- `ask` (used for BUY)
- `openInterest`
- `volume`
- `impliedVolatility`
- `strike`
- `lastTradeDate`

### Files Modified:

| File | Changes |
|------|---------|
| `/backend/services/yf_pricing.py` | **NEW** - Shared yfinance helpers for price and chain |
| `/backend/services/pricing_rules.py` | Added solvency/breakeven validation for precomputed PMCC |
| `/backend/services/eod_pipeline.py` | Updated `fetch_quote_sync` to use `get_underlying_price_yf()` |
| `/backend/services/data_provider.py` | Updated `_fetch_stock_quote_yahoo_sync` and `_fetch_live_stock_quote_yahoo_sync` to use shared helper |
| `/backend/services/precomputed_scans.py` | Added imports for shared helpers |

### Verification:
```
NVDA Price Consistency Test (Market CLOSED):
  Dashboard: $182.81 (history.Close[-1])
  Precomputed (EOD): $182.81 (history.Close[-1])
  All prices identical: ✅ YES
```

---

## Strict PMCC Institutional Rules - COMPLETED 2026-02-16

### Status: ✅ COMPLETE

### Objective:
Implement institutional-grade filtering rules for PMCC (Poor Man's Covered Call) strategy to ensure only high-quality, executable trades are presented to users.

### PMCC Strict Rules:
| Category | Rule | Value | Purpose |
|----------|------|-------|---------|
| **LEAP (Long)** | DTE Range | 365-730 days | Adequate time for multiple short cycles |
| | Delta Minimum | ≥ 0.80 | Deep ITM for stock-like behavior |
| | Open Interest Min | ≥ 100 | Sufficient liquidity |
| | Bid-Ask Spread Max | ≤ 5% | Reasonable execution costs |
| | Strike Requirement | ITM (strike < stock) | Acts as stock substitute |
| **Short** | DTE Range | 30-45 days | Optimal theta decay window |
| | Delta Range | 0.20-0.30 | ~75% probability of profit |
| | Open Interest Min | ≥ 100 | Sufficient liquidity |
| | Bid-Ask Spread Max | ≤ 5% | Reasonable execution costs |
| | Strike Requirement | OTM ≥2% above stock | Safe profit zone |
| **Structure** | Solvency | net_debit ≤ width * 1.20 | 20% tolerance for ASK/BID spreads |
| | Break-even | short_strike > BE (soft flag) | Warning only, not rejection |

### Quality Flags:
| Flag | Trigger | Impact |
|------|---------|--------|
| `FAIL_LONG_DTE_xxx` | leap_dte outside 365-730 | Rejected |
| `FAIL_LONG_DELTA_x.xx` | leap_delta < 0.80 | Rejected |
| `FAIL_LIQUIDITY_LEAP_OI_xxx` | leap_oi < 100 | Rejected |
| `FAIL_LIQUIDITY_LEAP_SPREAD_x%` | leap_spread > 5% | Rejected |
| `FAIL_SHORT_DTE_xxx` | short_dte outside 30-45 | Rejected |
| `FAIL_SHORT_DELTA_x.xx` | short_delta outside 0.20-0.30 | Rejected |
| `FAIL_SOLVENCY_xxx` | net_debit > width * 1.20 | Rejected (20% tolerance) |
| `WARN_BREAK_EVEN_xxx` | short_strike ≤ breakeven | Warning (soft flag) |
| `WIDE_SPREAD` | spread > 10% | Flagged (soft) |
| `LOW_OI` | OI < 50 | Flagged (soft) |
| `NO_LAST` | No last traded price | Flagged (soft) |

### Files Modified:
| File | Changes |
|------|---------|
| `/backend/services/eod_pipeline.py` | Updated PMCC constants (lines 692-716), Enhanced `validate_pmcc_structure` function |
| `/backend/routes/screener_snapshot.py` | Updated API default parameters to match strict rules |

### Test Results:
- **35/35 tests passed (100%)**
- Test file: `/app/backend/tests/test_pmcc_strict_rules.py`
- Validated: DTE ranges, delta ranges, solvency, break-even, quality flags, pricing rules

### Impact:
- Fewer PMCC opportunities (1 vs 5 in previous run) - expected
- All remaining opportunities meet institutional standards
- Improved trade quality and user confidence

---

## Deterministic EOD Pipeline - COMPLETED 2026-02-16

### Status: ✅ COMPLETE

### Objective:
Build a deterministic, scalable End-of-Day (EOD) pipeline that:
1. Builds a versioned 1500-symbol universe from static data files
2. Pre-computes all CC/PMCC scan results after market close
3. Stores everything in MongoDB for read-only access
4. Decouples frontend UI from live API calls

### Architecture:
```
┌───────────────────────────────────────────────────────────────┐
│                    EOD Pipeline Flow                           │
├───────────────────────────────────────────────────────────────┤
│  1. Universe Builder (Tier 1-4)                                │
│     ├── Tier 1: S&P 500 symbols (~517)                        │
│     ├── Tier 2: Nasdaq 100 net of S&P overlap (~16)           │
│     ├── Tier 3: ETF Whitelist (~89)                           │
│     └── Tier 4: Liquidity expansion (from us_symbol_master)   │
│                                                                │
│  2. EOD Pipeline (scheduled 4:10 PM ET weekdays)              │
│     ├── Fetch quotes (price, volume, market cap)              │
│     ├── Fetch option chains                                    │
│     ├── Compute CC opportunities                               │
│     ├── Compute PMCC opportunities                             │
│     └── Persist to MongoDB collections                         │
│                                                                │
│  3. Read-Only API Endpoints                                    │
│     ├── /api/eod-pipeline/covered-calls                       │
│     └── /api/eod-pipeline/pmcc                                │
└───────────────────────────────────────────────────────────────┘
```

### New Collections:
| Collection | Purpose |
|------------|---------|
| `scan_universe_versions` | Versioned universe snapshots |
| `symbol_snapshot` | Underlying prices + option chains per run |
| `scan_results_cc` | Pre-computed Covered Call opportunities |
| `scan_results_pmcc` | Pre-computed PMCC opportunities |
| `scan_runs` | Log of completed EOD pipeline runs |
| `scan_run_summary` | Pre-aggregated summary for fast dashboard |

### New Files:
| File | Purpose |
|------|---------|
| `/backend/data/sp500_symbols.py` | Static S&P 500 symbol list |
| `/backend/data/nasdaq100_symbols.py` | Static Nasdaq 100 symbol list |
| `/backend/data/etf_whitelist.py` | Static ETF whitelist |
| `/backend/services/universe_builder.py` | Builds deterministic universe |
| `/backend/services/eod_pipeline.py` | Main EOD processing logic |
| `/backend/services/db_indexes.py` | MongoDB index creation |
| `/backend/routes/eod_pipeline.py` | API endpoints for EOD pipeline |
| `/backend/utils/symbol_normalization.py` | Ticker format normalization |

### API Endpoints:
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/eod-pipeline/covered-calls` | GET | Pre-computed CC results (read-only) |
| `/api/eod-pipeline/pmcc` | GET | Pre-computed PMCC results (read-only) |
| `/api/eod-pipeline/latest-run` | GET | Latest pipeline run metadata |
| `/api/eod-pipeline/run` | POST | Manual pipeline trigger (admin, dev only) |
| `/api/eod-pipeline/create-indexes` | POST | Create MongoDB indexes (admin) |
| `/api/eod-pipeline/runs` | GET | List pipeline runs (admin) |
| `/api/eod-pipeline/universe` | GET | Current universe stats (admin) |

### Scheduler:
- **Job ID:** `eod_pipeline_scan`
- **Schedule:** 4:10 PM ET, Mon-Fri
- **Timezone:** America/New_York

### Performance Results (First Run):
- **Run Duration:** ~2.5 minutes for 622 symbols
- **Symbols Processed:** 622 (Tier 1-3)
- **Symbols Included:** 399 (successful quotes + chains)
- **CC Opportunities:** 75
- **PMCC Opportunities:** 0 (expected - requires LEAPS availability)

### Benefits:
1. ✅ **Fast UI** - Screener pages serve from pre-computed DB, no live calls
2. ✅ **Scalable** - Can expand to 1500+ symbols without timeout issues
3. ✅ **Deterministic** - Same run produces same results
4. ✅ **Reliable** - No rate limiting or API failures during user sessions
5. ✅ **Auditable** - Full run history with success/failure breakdowns

---

## Universe Expansion - COMPLETED 2026-02-14

### Status: ✅ COMPLETE (Phase 1 & Phase 2)

### Objective:
Expand scan universe from fixed ~60 symbols to S&P500 + Nasdaq100 + ETF whitelist (~340+ symbols), with proper ETF handling that skips fundamental data fetch.

### Phase 1: ETF Handling (Complete)
**Goal:** Make ETFs first-class citizens in scans by skipping fundamentals cleanly

**Implementation:**
1. **`is_etf(symbol)` function** - Centralized ETF detection using whitelist
   - Located in `/backend/utils/universe.py`
   - Returns True for 37 whitelisted ETFs (SPY, QQQ, IWM, sector ETFs, etc.)
   
2. **Scan Pipeline Changes:**
   - Covered Call scan (`precomputed_scans.py`): Skips `fetch_fundamental_data()` for ETFs
   - PMCC scan (`precomputed_scans.py`): Skips `passes_fundamental_filters()` for ETFs
   - No 404 errors logged for ETF fundamentals
   - ETFs get neutral fundamental score (0 points, not penalized)

3. **Audit Ledger:**
   - ETF symbols show `fundamentals_skipped: true`
   - ETFs auto-pass fundamental stage in stats

### Phase 2: Universe Expansion v1 (Complete)
**Goal:** Expand universe to S&P500 + Nasdaq100 + ETF whitelist

**Implementation:**
1. **Universe Builder** (`/backend/utils/universe.py`):
   - `SP500_SYMBOLS`: ~263 liquid S&P 500 stocks
   - `NASDAQ100_NET`: ~41 Nasdaq 100 symbols (net of S&P overlap)
   - `ETF_WHITELIST`: 37 liquid options ETFs
   - `build_scan_universe()`: Combines tiers, respects MAX_SCAN_UNIVERSE limit

2. **Configuration:**
   | Variable | Default | Description |
   |----------|---------|-------------|
   | MAX_SCAN_UNIVERSE | 700 | Maximum symbols in scan universe |
   | UNIVERSE_INCLUDE_ETF | true | Include ETF whitelist |
   | UNIVERSE_INCLUDE_NASDAQ | true | Include Nasdaq 100 net |

3. **Admin Status Updates:**
   - `GET /api/screener/admin-status` now returns `tier_counts`:
     ```json
     "tier_counts": {
       "sp500": 263,
       "nasdaq100_net": 41,
       "etf_whitelist": 37,
       "liquidity_expansion": 0,
       "total": 341
     }
     ```
   - Exclusion tracking works with expanded universe

### New Files:
- `/backend/utils/universe.py` - Universe builder and ETF detection

### Modified Files:
- `/backend/services/precomputed_scans.py` - ETF fundamental skip logic
- `/backend/routes/screener_snapshot.py` - Uses universe builder, returns tier_counts
- `/backend/routes/screener.py` - Uses centralized ETF detection
- `/backend/.env` - Added MAX_SCAN_UNIVERSE, UNIVERSE_INCLUDE_* vars

### API Changes:
| Endpoint | Change |
|----------|--------|
| `/api/screener/admin-status` | Added `universe.tier_counts` field |

### ETF Whitelist (37 symbols):
- Major Index: SPY, QQQ, IWM, DIA
- Sectors: XLF, XLE, XLK, XLV, XLI, XLB, XLU, XLP, XLY, XLRE, XLC
- Commodities: GLD, SLV, USO
- Bonds: TLT, HYG, LQD
- International: EEM, EFA, FXI
- Volatility: VXX, UVXY, SQQQ, TQQQ, SPXU, SPXL
- Thematic: ARKK, ARKG, ARKW, ARKF
- Small/Mid: IJR, IJH, MDY

---

## Scan Timeout Fix - COMPLETED 2026-02-14

### Status: ✅ COMPLETE

### Objective:
Fix scan workflow timeouts by implementing bounded concurrency, timeout handling, and retry logic. This applies ONLY to scan paths (Screener, PMCC scans) without affecting single-symbol lookups.

### Problem Statement:
Scan workflows (Screener, PMCC, etc.) create bursty traffic to Yahoo Finance, causing timeouts. The fix must:
1. Apply bounded concurrency ONLY to scan paths
2. Implement timeout and retry policies
3. Enable partial success (failed symbols don't fail entire scan)
4. Log aggregated stats per scan run

### Configuration (Environment Variables):
| Variable | Default | Description |
|----------|---------|-------------|
| YAHOO_SCAN_MAX_CONCURRENCY | 5 | Max concurrent Yahoo calls during scans (semaphore limit) |
| YAHOO_TIMEOUT_SECONDS | 30 | Timeout per symbol fetch in seconds |
| YAHOO_MAX_RETRIES | 2 | Number of retry attempts before marking symbol as failed |

### Key Features:
1. **Bounded Concurrency** - `asyncio.Semaphore` limits concurrent Yahoo calls
2. **Timeout Handling** - `asyncio.wait_for()` wraps each fetch
3. **Retry Logic** - Exponential backoff (0.5s, 1s, 2s...) before retries
4. **Partial Success** - Failed symbols logged, scan continues
5. **Aggregated Stats** - Success rate, timeout count, error count per scan run

### New Components:
- `/backend/services/resilient_fetch.py` - Resilient fetch service
  - `ResilientYahooFetcher` class for scan contexts
  - `ScanStats` dataclass for aggregated metrics
  - `get_scan_semaphore()` for lazy semaphore initialization

### Modified Files:
- `/backend/services/precomputed_scans.py` - Uses ResilientYahooFetcher
- `/backend/routes/admin.py` - Added `/api/admin/scan/resilience-config` endpoint
- `/backend/.env` - Added new environment variables

### New API Endpoint:
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/admin/scan/resilience-config` | GET | Returns resilience configuration |

### Logging:
- `SCAN_START | run_id=... | type=... | symbols=... | batch_size=...`
- `SCAN_TIMEOUT | symbol=... | attempts=... | timeout=...`
- `SCAN_ERROR | symbol=... | error=...`
- `SCAN_STATS | run_id=... | total=... | success=... | timeout=... | error=...`

### Scope:
- ✅ Applies to: `run_covered_call_scan()`, `run_pmcc_scan()` in precomputed_scans.py
- ❌ Does NOT affect: Single-symbol lookups (Watchlist, Simulator, Options Chain)

### Test Coverage:
- 25 tests in `/backend/tests/test_scan_resilience.py`
- All tests passing

---

## Deterministic EOD Snapshot Lock - COMPLETED 2026-02-14

### Status: ✅ COMPLETE

### Objective:
Implement a strict EOD snapshot model guaranteeing synchronized underlying price and option chain data after market close. After 4:05 PM ET, all data comes from a stored deterministic snapshot with no live rebuilding.

### System Modes:
| Mode | Time Range | Behavior |
|------|------------|----------|
| LIVE | 9:30 AM - 4:05 PM ET | Live Yahoo Finance fetching |
| EOD_LOCKED | After 4:05 PM ET | Serve ONLY from `eod_market_snapshot` |

### Non-Negotiables Enforced:
- ✅ No mock data in production
- ✅ No dynamic option chain rebuilding after 4:05 PM ET
- ✅ No mixing live underlying with cached options
- ✅ Snapshot is sole source of truth after lock time
- ✅ No scoring/pricing rule changes

### Key Features:
1. **Market State Enforcement** (`/backend/utils/market_state.py`)
   - `get_system_mode()` returns LIVE or EOD_LOCKED
   - Uses US/Eastern timezone explicitly
   - Handles weekends and holidays via NYSE calendar

2. **4:05 PM ET Snapshot Job** (Scheduler in `server.py`)
   - Triggered at 4:05 PM ET on weekdays
   - Fetches underlying prices
   - Fetches option chains using BID_ONLY pricing rule
   - Saves to `eod_market_snapshot` collection

3. **After 4:05 PM ET Behavior**
   - `/api/options/chain/{symbol}` serves from snapshot
   - Returns `data_status: EOD_SNAPSHOT_NOT_AVAILABLE` if missing
   - No live Yahoo calls permitted

4. **Logging**
   - `[EOD-SNAPSHOT-CREATED] run_id=... symbols=...` on success
   - `[EOD-SNAPSHOT-FAILED] symbol=... reason=...` on failure
   - Exclusions logged to `eod_snapshot_audit` collection

### New Collection: `eod_market_snapshot`
```json
{
  "run_id": "eod_snap_20260213_1605_abc12345",
  "symbol": "AAPL",
  "underlying_price": 255.78,
  "option_chain": [...],
  "pricing_rule_used": "BID_ONLY_SELL_LEG",
  "as_of": "2026-02-13T16:05:00-05:00",
  "trade_date": "2026-02-13",
  "is_final": true,
  "created_at": "2026-02-13T21:05:00.000Z"
}
```

### New/Modified API Endpoints:
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/options/chain/{symbol}` | GET | Now serves from snapshot in EOD_LOCKED mode |
| `/api/options/market-state` | GET | Returns system mode and lock info |
| `/api/options/snapshot-status` | GET | Returns snapshot availability |
| `/api/market-status` | GET | Enhanced with system_mode field |
| `/api/admin/eod-snapshot/trigger` | POST | Manual snapshot creation |
| `/api/admin/eod-snapshot/status` | GET | Detailed snapshot status |
| `/api/admin/eod-snapshot/sample/{symbol}` | GET | View snapshot for symbol |

### Files Created:
- `/backend/utils/market_state.py` - System mode enforcement
- `/backend/services/eod_snapshot_service.py` - Snapshot creation/retrieval

### Files Modified:
- `/backend/routes/options.py` - EOD lock enforcement on /chain
- `/backend/routes/admin.py` - Admin snapshot endpoints
- `/backend/server.py` - Scheduler job, indexes, market-status enhancement

### Expected Behavior:
| Time | System Mode | Data Source |
|------|-------------|-------------|
| 4:04 PM ET | LIVE | Yahoo Finance |
| 4:05 PM ET | EOD_LOCKED | Snapshot created |
| 4:06 PM ET | EOD_LOCKED | Snapshot only |
| 9:00 PM ET | EOD_LOCKED | Snapshot only |
| Next 9:30 AM ET | LIVE | Yahoo Finance |

### Guarantees:
- ✅ Underlying price = option chain reference (synchronized)
- ✅ No after-hours drift
- ✅ No stale mismatches
- ✅ No fake quotes
- ✅ No mock fallback
- ✅ Deterministic behavior

---

## AI Wallet & Token System - COMPLETED & APPROVED 2026-02-10

### Status: ✅ APPROVED - DEPLOYMENT ON HOLD (User Decision)

### Objective:
Token-based access control for AI features with PayPal integration for token purchases.

### Pricing (Final Approved):
| Plan | Monthly | Yearly | AI Tokens |
|------|---------|--------|-----------|
| Basic | $29 | $290 | 2,000/mo |
| Standard | $59 | $590 | 6,000/mo |
| Premium | $89 | $890 | 15,000/mo |

### Token Packs:
| Pack | Tokens | Price |
|------|--------|-------|
| Starter | 5,000 | $10 |
| Power | 15,000 | $25 |
| Pro | 50,000 | $75 |

### Key Features Implemented:
1. ✅ Token Wallet - Free + Paid tokens per user
2. ✅ Monthly Reset - Free tokens aligned to billing cycle (expire on reset)
3. ✅ Paid Tokens - Never expire, purchased via PayPal
4. ✅ AI Guard - Atomic deduction with $gte predicates (negative balances impossible)
5. ✅ Rate Limiting - Max 10 calls/minute, 2000 tokens/action
6. ✅ Concurrency Control - One AI call at a time per user
7. ✅ Ledger - Immutable transaction log with free/paid breakdown
8. ✅ PayPal Integration - Webhook-only crediting with signature verification
9. ✅ Retry Limit - Max 1 retry on race condition
10. ✅ Production Safety - Webhook verification hard-fails if PAYPAL_WEBHOOK_ID missing in live mode

### New Collections (Additive-Only):
- `ai_wallet` - User token balances (unique user_id index)
- `ai_token_ledger` - Immutable transaction log
- `ai_purchases` - Token pack purchase records (unique purchase_id index)
- `paypal_events` - Webhook idempotency (unique event_id + capture_id indexes)
- `entitlements` - Feature flags

### New API Endpoints:
- `GET /api/ai-wallet` - Get wallet balance
- `GET /api/ai-wallet/ledger` - Get transaction history
- `GET /api/ai-wallet/packs` - Get token packs
- `POST /api/ai-wallet/estimate` - Estimate token cost
- `POST /api/ai-wallet/purchase/create` - Create PayPal purchase
- `POST /api/ai-wallet/webhook` - PayPal webhook handler

### Frontend Components:
- `AIWallet.js` - Wallet balance page
- `BuyTokensModal.js` - Token purchase modal
- `AIUsageHistoryModal.js` - Transaction history modal
- `AITokenUsageModal.js` - Pre-execution confirmation modal
- Updated `Pricing.js` - $29/$59/$89 with AI tokens, Monthly/Yearly toggle
- Updated `Landing.js` - Updated pricing display

### Hard Constraints Met:
- ✅ Scanner engine untouched
- ✅ Yahoo Finance unchanged
- ✅ No AI without prepaid tokens
- ✅ No negative balances (atomic MongoDB $gte conditional updates)
- ✅ No post-paid billing
- ✅ USD only
- ✅ Additive-only changes (new files + new collections)
- ✅ Webhook signature verification required in production
- ✅ Max 1 retry on deduction race condition

### Deploy Commands (When Ready):
```bash
git pull origin main
cd backend && pip install -r requirements.txt
APP_ENV=production AI_WALLET_INIT_CONFIRM=YES python -m ai_wallet.db_init
sudo supervisorctl restart backend
```

### Required Env Vars for Production:
```
PAYPAL_ENV=live
PAYPAL_CLIENT_ID=<your_id>
PAYPAL_SECRET=<your_secret>
PAYPAL_WEBHOOK_ID=<your_webhook_id>
PUBLIC_APP_URL=https://your-domain.com
```

---

## Phase 3 - COMPLETED 2025-12

### AI-Based Best Option Selection per Symbol
- Implemented deduplication logic showing only the single best option per stock
- Applied to all custom scans and precomputed scans
- Selection based on AI score, quality score, and ROI

---

## Phase 2 - COMPLETED 2025-12

### MongoDB Caching Layer
- Implemented `market_snapshot_cache` collection
- 10-15 minute TTL during market hours
- ~40% performance improvement on custom scans
- `/api/admin/cache/health` endpoint added

---

## Phase 1 - COMPLETED 2025-12

### Data Provider Centralization
- Eliminated Polygon API dependencies
- Centralized data fetching through `data_provider.py`
- Yahoo Finance as primary data source

---

## CCE Volatility & Greeks Correctness - COMPLETED 2026-02-11

### Status: ✅ COMPLETE (with Bootstrap Fix 2026-02-11)

### Objective:
Standardize IV and Delta calculations across all endpoints using industry-standard formulas. Remove inaccurate moneyness-based delta fallbacks. Implement true IV Rank and IV Percentile using historical IV proxy data.

### Key Changes:
1. ✅ **Delta via Black-Scholes** - All delta calculations now use Black-Scholes formula
   - Removed moneyness-based delta fallback (accuracy and consistency)
   - Delta source field: `delta_source = "BS"` or `"BS_PROXY_SIGMA"`
   - Delta bounds enforced: calls [0, 1], puts [-1, 0]
   
2. ✅ **IV Normalization** - Consistent across all endpoints
   - `iv` = decimal form (e.g., 0.30)
   - `iv_pct` = percentage form (e.g., 30.0)
   - Invalid IV (< 0.01 or > 5.0) rejected

3. ✅ **Industry-Standard IV Rank** - True historical calculation with bootstrap
   - Formula: `iv_rank = 100 * (iv_current - iv_low) / (iv_high - iv_low)`
   - **Bootstrap behavior to reduce 50/100 clustering:**
     - < 5 samples: neutral 50, LOW confidence
     - 5-19 samples: shrinkage toward 50 (`rank = 50 + w*(raw-50)` where w=samples/20), MEDIUM confidence
     - >= 20 samples: true rank, MEDIUM/HIGH confidence
   
4. ✅ **IV Percentile** - Distribution-based metric with same bootstrap
   - Formula: `iv_percentile = 100 * count(iv_hist < iv_current) / N`
   
5. ✅ **IV History Storage** - New collection with TTL
   - Collection: `iv_history`
   - Stores daily ATM proxy IV per symbol
   - TTL: 450 days auto-expiry
   - Indexes: unique (symbol, trading_date)

6. ✅ **Computation Order Fix** - Prevent self-teaching
   - Rank is computed BEFORE storing today's value
   - Prevents artificial rank=100 when first encountering a symbol

### API Response Fields (All endpoints):
| Field | Type | Description |
|-------|------|-------------|
| delta | float | Black-Scholes delta |
| delta_source | string | "BS", "BS_PROXY_SIGMA", "EXPIRY", "MISSING" |
| gamma, theta, vega | float | Black-Scholes Greeks |
| iv | float | IV decimal (0.30 = 30%) |
| iv_pct | float | IV percentage (30.0) |
| iv_rank | float | Industry-standard IV Rank (0-100) |
| iv_percentile | float | IV Percentile (0-100) |
| iv_rank_source | string | Source/quality indicator |
| iv_rank_confidence | string | "LOW", "MEDIUM", "HIGH" |
| iv_samples | int | Number of historical samples used |

### Files Created:
- `/backend/services/greeks_service.py` - Black-Scholes Greeks calculation
- `/backend/services/iv_rank_service.py` - IV history and rank/percentile with bootstrap
- `/backend/services/option_normalizer.py` - Shared field normalization helper
- `/backend/tests/test_iv_rank_service.py` - 28 unit tests

### Files Modified:
- `/backend/routes/screener_snapshot.py` - Custom scan with IV metrics
- `/backend/routes/options.py` - Options chain endpoint with normalized fields
- `/backend/routes/watchlist.py` - Watchlist with IV metrics integration
- `/backend/routes/simulator.py` - Delegated Greeks to shared service
- `/backend/routes/admin.py` - IV metrics verification endpoints with bootstrap info
- `/backend/services/precomputed_scans.py` - Black-Scholes delta
- `/backend/services/snapshot_service.py` - Ingestion + retrieval with B-S Greeks
- `/backend/server.py` - IV history index creation at startup

### Endpoints Updated with New Fields:
1. **GET /api/options/chain/{symbol}** - Options chain with per-option and symbol-level IV metrics
2. **GET /api/screener/covered-calls** - Custom scan with Black-Scholes delta and IV rank
3. **GET /api/screener/pmcc** - PMCC scan with Black-Scholes delta
4. **GET /api/watchlist/** - Watchlist items with best_opportunity containing all fields
5. **GET /api/simulator/trades** - Simulator trades using shared Greeks service
6. **GET /api/snapshots/calls/{symbol}** - Dashboard snapshots with B-S Greeks (on-the-fly for legacy data)
7. **GET /api/snapshots/leaps/{symbol}** - LEAPS snapshots with B-S Greeks

### Admin Verification Endpoints:
- `GET /api/admin/iv-metrics/check/{symbol}` - Full IV/Greeks sanity check with bootstrap info
- `GET /api/admin/iv-metrics/stats` - IV history collection statistics
- `GET /api/admin/iv-metrics/completeness-test` - Field completeness validation

### ENV Configuration:
- `RISK_FREE_RATE` - Optional, default 0.045 (4.5%), bounds [0.001, 0.20]

---

## Pending Issues (Pre-existing)

| Issue | Priority | Status |
|-------|----------|--------|
| Inbound email replies not appearing in support dashboard | P3 | Recurring |
| LLM rate limiting safeguards | P2 | Addressed by AI Wallet guard |

---

## Future/Backlog

- (P3) Frontend refactor - break down `Simulator.js` (2,200+ lines)
- (P4) Backend refactor - split `simulator.py` (2,800+ lines)
- (P4) Consolidate `precomputed_scans.py` to fully use `data_provider.py`

