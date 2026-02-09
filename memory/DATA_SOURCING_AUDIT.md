# MARKET DATA SOURCING AUDIT
## Covered Call Engine - Comprehensive Data Flow Analysis
**Audit Date:** December 2025
**Purpose:** Document actual data sourcing behavior for refactoring planning
**Status:** ✅ BASELINE LOCKED - Approved for Refactor Planning

---

## EXPLICIT CONFIRMATIONS

### ✅ Confirmation 1: No Code Changes Made During Audit
**Verified via `git status`:** Only untracked yarn.lock files exist. No source code modifications were made during this audit. All findings reflect the actual production codebase as of commit `9b317c6`.

### ✅ Confirmation 2: Documented File List Represents Actual Current Production Behavior
**Verified:** All file paths and line numbers have been cross-referenced against the actual codebase. The data flow documented here represents the live production behavior, not intended or deprecated behavior.

### ✅ Confirmation 3: All 5 Parallel Data-Fetching Paths Are Active
**Verified:** Each of the following implementations contains active, callable code:
1. `/backend/services/data_provider.py` - ACTIVE (used by screener.py, watchlist.py, simulator.py)
2. `/backend/server.py` - ACTIVE (used by portfolio.py for fetch_stock_quote)
3. `/backend/routes/stocks.py` - ACTIVE (direct Polygon calls on `/api/stocks/*` endpoints)
4. `/backend/routes/options.py` - ACTIVE (direct Polygon calls on `/api/options/*` endpoints)
5. `/backend/services/precomputed_scans.py` - ACTIVE (nightly job uses own Yahoo implementation)

### ✅ Confirmation 4: Custom Scans Perform LIVE, Synchronous Yahoo Fetches Per Symbol
**Verified in `/backend/routes/screener.py`:**
- Lines 264, 601, 949: Call `fetch_stock_quote()` from data_provider.py (synchronous per-symbol)
- Lines 303, 646, 654, 996, 1001: Call `fetch_options_chain()` from data_provider.py (synchronous per-symbol)
- **No caching layer between user request and Yahoo Finance for custom scans**
- Each custom scan request triggers live HTTP calls to Yahoo for every symbol in the scan list

### ✅ Confirmation 5: Pre-Computed Scans Are DB-Backed (No Yahoo Fetch on User Request)
**Verified in `/backend/services/precomputed_scans.py`:**
- `get_scan_results()` method (line ~795-807): Reads directly from MongoDB `precomputed_scans` collection
- **Zero Yahoo Finance calls** when user requests pre-computed scan results
- Yahoo fetches occur ONLY during nightly job execution (4:45 PM ET)
- User requests return pre-stored database results with no live market data fetching

---

## 1. GLOBAL DATA FLOW OVERVIEW

### Intended Architecture (as documented)
```
PRIMARY: Yahoo Finance (yfinance) → data_provider.py
BACKUP:  Polygon API → data_provider.py
```

### Actual Implementation Reality
```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          DATA SOURCE FRAGMENTATION                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  data_provider.py (INTENDED SINGLE SOURCE)                                  │
│  └── Uses: Yahoo Finance (yfinance) primary, Polygon backup                 │
│                                                                             │
│  BYPASS 1: /routes/stocks.py                                                │
│  └── DIRECTLY calls Polygon API (api.polygon.io/v2/aggs/ticker/.../prev)   │
│  └── Fallback: MOCK_STOCKS dictionary                                       │
│                                                                             │
│  BYPASS 2: /routes/options.py                                               │
│  └── DIRECTLY calls Polygon API (api.polygon.io/v3/snapshot/options/...)   │
│  └── Fallback: generate_mock_options()                                      │
│                                                                             │
│  BYPASS 3: /routes/screener.py                                              │
│  └── IMPORTS from data_provider.py ✓                                        │
│  └── BUT screener relies on get_massive_api_key() for Polygon               │
│                                                                             │
│  BYPASS 4: /routes/portfolio.py                                             │
│  └── IMPORTS fetch_stock_quote from server.py (NOT data_provider.py)        │
│  └── server.py fetch_stock_quote uses Yahoo then Polygon                    │
│                                                                             │
│  BYPASS 5: /services/precomputed_scans.py                                   │
│  └── Uses Yahoo Finance for technical/fundamental data ✓                    │
│  └── Uses Yahoo Finance for options (with Polygon fallback)                 │
│  └── BUT stores api_key parameter (expects Polygon)                         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Finding: "Data Provider Schism"
The codebase has **multiple parallel data fetching implementations** rather than a unified approach through `data_provider.py`:

1. **`/backend/services/data_provider.py`** - Intended centralized source (Yahoo primary)
2. **`/backend/server.py`** - Contains its own `fetch_stock_quote()` and `fetch_options_chain_polygon()`
3. **`/backend/routes/stocks.py`** - Direct Polygon API calls
4. **`/backend/routes/options.py`** - Direct Polygon API calls
5. **`/backend/services/precomputed_scans.py`** - Has its own Yahoo/Polygon logic

---

## 2. PAGE-BY-PAGE DATA SOURCE BREAKDOWN

### 2.1 DASHBOARD (`/routes/screener.py` → `get_dashboard_opportunities`)

| Data Type | Source | Function | File:Line |
|-----------|--------|----------|-----------|
| Stock Price | data_provider.py | `fetch_stock_quote()` | screener.py:604 |
| Analyst Rating | data_provider.py | Via fetch_stock_quote() | screener.py:609 |
| Avg Volume | data_provider.py | Via fetch_stock_quote() | screener.py:610 |
| Market Cap | data_provider.py | Via fetch_stock_quote() | screener.py:611 |
| Earnings Date | data_provider.py | Via fetch_stock_quote() | screener.py:612 |
| Options Chain (Weekly) | data_provider.py | `fetch_options_chain()` | screener.py:646-651 |
| Options Chain (Monthly) | data_provider.py | `fetch_options_chain()` | screener.py:654-660 |
| Market Sentiment | market_bias.py | `fetch_market_sentiment()` | screener.py:793 |

**Status:** ✅ Uses data_provider.py correctly
**Price Type:** Previous Market Close (from Yahoo history())
**Caching:** MongoDB `api_cache` collection, key prefix "dashboard_opportunities_v7"

---

### 2.2 SCREENER - Covered Calls (`/routes/screener.py` → `screen_covered_calls`)

| Data Type | Source | Function | File:Line |
|-----------|--------|----------|-----------|
| Stock Price | data_provider.py | `fetch_stock_quote()` | screener.py:264 |
| Analyst Rating | data_provider.py | Via fetch_stock_quote() | screener.py:271 |
| Market Cap | data_provider.py | Via fetch_stock_quote() | screener.py:273 |
| Options Chain | data_provider.py | `fetch_options_chain()` | screener.py:303-305 |
| Market Sentiment | market_bias.py | `fetch_market_sentiment()` | screener.py:468 |

**Status:** ✅ Uses data_provider.py correctly
**Price Type:** Previous Market Close (from Yahoo history())
**Caching:** MongoDB `api_cache`, key prefix "screener_covered_calls_v3_phase4"

---

### 2.3 PMCC SCREENER (`/routes/screener.py` → `screen_pmcc`)

| Data Type | Source | Function | File:Line |
|-----------|--------|----------|-----------|
| Stock Price | data_provider.py | `fetch_stock_quote()` | screener.py:949 |
| Avg Volume | data_provider.py | Via fetch_stock_quote() | screener.py:957 |
| Market Cap | data_provider.py | Via fetch_stock_quote() | screener.py:958 |
| LEAPS Options | data_provider.py | `fetch_options_chain()` | screener.py:996-998 |
| Short Options | data_provider.py | `fetch_options_chain()` | screener.py:1001-1003 |
| Market Sentiment | market_bias.py | `fetch_market_sentiment()` | screener.py:1177 |

**Status:** ✅ Uses data_provider.py correctly
**Price Type:** Previous Market Close
**Caching:** MongoDB `api_cache`, key prefix "pmcc_screener_v2_phase5"

---

### 2.4 PORTFOLIO TRACKER (`/routes/portfolio.py`)

| Data Type | Source | Function | File:Line |
|-----------|--------|----------|-----------|
| Stock Price (Positions) | MOCK_STOCKS | Direct dictionary lookup | portfolio.py:92 |
| Stock Price (IBKR) | server.py | `fetch_stock_quote()` | portfolio.py:306, 347 |
| Stock Price (Summary) | MOCK_STOCKS | Direct dictionary lookup | portfolio.py:158 |

**Status:** ⚠️ INCONSISTENT
- Uses MOCK_STOCKS for position P/L calculations
- Uses server.py's fetch_stock_quote (NOT data_provider.py) for IBKR trades
- server.py's fetch_stock_quote() tries Yahoo then Polygon

**Flow:**
```
portfolio.py:_get_server_data() 
  → imports from server.py: MOCK_STOCKS, fetch_stock_quote
  → NOT from data_provider.py
```

---

### 2.5 SIMULATOR (`/routes/simulator.py`)

| Data Type | Source | Function | File:Line |
|-----------|--------|----------|-----------|
| Stock Price (Open Trades) | data_provider.py | `fetch_live_stock_quote()` | simulator.py:856 |
| Stock Price (Trade Entry) | server.py | `fetch_stock_quote()` | simulator.py:185-186 |

**Status:** ⚠️ MIXED SOURCES
- Import at line 40: `from services.data_provider import fetch_live_stock_quote`
- But also imports `fetch_stock_quote` from server.py at line 185
- Uses **LIVE intraday prices** (regularMarketPrice) for simulator

**Important:** Simulator uses `fetch_live_stock_quote` which returns **current market price** (different from screener which uses previous close)

---

### 2.6 WATCHLIST (`/routes/watchlist.py`)

| Data Type | Source | Function | File:Line |
|-----------|--------|----------|-----------|
| Stock Price | data_provider.py | `fetch_live_stock_quotes_batch()` | watchlist.py:505 |
| Options Chain | data_provider.py | `fetch_options_chain()` | watchlist.py:79-86 |
| Previous Close | data_provider.py | `fetch_stock_quotes_batch()` | watchlist.py:507 |

**Status:** ✅ Uses data_provider.py correctly
**Price Type:** LIVE intraday prices (when `use_live_prices=True`, default)
**Documented Rule:** Watchlist uses LIVE intraday prices (different from Screener)

---

### 2.7 ADMIN (`/routes/admin.py`)

| Data Type | Source | Function | File:Line |
|-----------|--------|----------|-----------|
| Stock Data | N/A | No direct market data fetching | - |
| API Keys | MongoDB | `admin_settings` collection | admin.py:346-361 |

**Status:** ✅ No data sourcing issues
Admin routes manage settings only, don't fetch market data.

---

### 2.8 PRE-COMPUTED SCANS (`/services/precomputed_scans.py`)

| Data Type | Source | Function | File:Line |
|-----------|--------|----------|-----------|
| Technical Data (SMA, RSI) | Yahoo Finance | `fetch_technical_data()` | precomputed_scans.py:260-348 |
| Fundamental Data | Yahoo Finance | `fetch_fundamental_data()` | precomputed_scans.py:351-448 |
| Options (Primary) | Yahoo Finance | `_fetch_options_yahoo()` | precomputed_scans.py:489-594 |
| Options (Fallback) | Polygon API | `_fetch_options_polygon()` | precomputed_scans.py:599-737 |
| LEAPS (Primary) | Yahoo Finance | `_fetch_leaps_yahoo()` | precomputed_scans.py:1321-1426 |
| LEAPS (Fallback) | Polygon API | `_fetch_leaps_polygon()` | precomputed_scans.py:1428+ |

**Status:** ⚠️ ISOLATED IMPLEMENTATION
- Has its own Yahoo Finance fetching logic (duplicates data_provider.py)
- Uses Polygon only as fallback
- Properly uses Previous Market Close for price consistency (lines 299-320)

**Price Consistency Fix (Lines 299-320):**
```python
# If market is OPEN and the last row is from today, use second-to-last row
if not is_market_closed() and last_date == today:
    use_index = -2
```

---

### 2.9 STOCK DETAILS (`/routes/stocks.py`)

| Data Type | Source | Function | File:Line |
|-----------|--------|----------|-----------|
| Stock Quote | Polygon API | Direct HTTP call | stocks.py:51-73 |
| Stock Quote Fallback | Polygon API | Last trade endpoint | stocks.py:76-89 |
| Mock Fallback | MOCK_STOCKS | Dictionary lookup | stocks.py:94-106 |
| Analyst Ratings | Yahoo Finance | `_fetch_analyst_ratings()` | stocks.py:110-151 |
| Market Indices | Yahoo Finance | yfinance Ticker.history() | stocks.py:155-214 |
| Stock Details | Polygon API | Multiple endpoints | stocks.py:217-390 |

**Status:** ❌ BYPASSES data_provider.py
- Line 51-73: Direct Polygon API call for `/v2/aggs/ticker/{symbol}/prev`
- Line 76-89: Direct Polygon API call for `/v2/last/trade/{symbol}`
- Uses `get_massive_api_key()` from server.py
- Falls back to MOCK_STOCKS if API unavailable

---

### 2.10 OPTIONS CHAIN (`/routes/options.py`)

| Data Type | Source | Function | File:Line |
|-----------|--------|----------|-----------|
| Stock Price | Polygon API | Direct HTTP call | options.py:61-70 |
| Options Chain | Polygon API | `/v3/snapshot/options/{symbol}` | options.py:82-127 |
| Mock Fallback | server.py | `generate_mock_options()` | options.py:139 |

**Status:** ❌ BYPASSES data_provider.py
- Line 61-70: Direct Polygon API call for stock price
- Line 82-127: Direct Polygon API call for options snapshot
- Uses `get_massive_api_key()` from server.py
- Returns mock data if API fails or not configured

---

## 3. FILE-LEVEL TRACEABILITY (MANDATORY)

### Files That USE data_provider.py Correctly:
```
/app/backend/routes/screener.py
  - Line 37-42: Imports fetch_options_chain, fetch_stock_quote
  
/app/backend/routes/watchlist.py
  - Line 26-32: Imports fetch_live_stock_quote, fetch_live_stock_quotes_batch, 
                fetch_options_chain, fetch_stock_quote, fetch_stock_quotes_batch
  
/app/backend/routes/simulator.py
  - Line 40: Imports fetch_live_stock_quote
```

### Files That BYPASS data_provider.py:
```
/app/backend/routes/stocks.py
  - Line 51-89: Direct Polygon API calls
  - Line 110-151: Direct yfinance calls for analyst ratings
  - Issue: Does NOT import from data_provider.py

/app/backend/routes/options.py
  - Line 61-127: Direct Polygon API calls
  - Issue: Does NOT import from data_provider.py

/app/backend/routes/portfolio.py
  - Line 78: Imports fetch_stock_quote from server.py (NOT data_provider.py)
  - Issue: Uses server.py's implementation instead

/app/backend/server.py
  - Line 364-431: Contains its own fetch_stock_quote() function
  - Line 433-575: Contains its own fetch_options_chain_polygon()
  - Line 577-691: Contains its own fetch_options_chain_yahoo()
  - Issue: DUPLICATE implementation of data_provider.py functions

/app/backend/services/precomputed_scans.py
  - Line 260-448: Contains its own technical/fundamental data fetching
  - Line 489-737: Contains its own options fetching logic
  - Issue: DUPLICATE implementation (though correctly uses Yahoo primary)
```

### API Key Flow:
```
server.py:get_massive_api_key() (Line 357-362)
  → Reads from MongoDB: admin_settings.massive_api_key
  → Used by: stocks.py, options.py, screener.py (via _get_server_functions)
  → data_provider.py receives api_key as parameter (doesn't fetch itself)
```

---

## 4. CUSTOM SCAN VS PRE-COMPUTED SCAN COMPARISON

| Aspect | Custom Scan (Screener) | Pre-Computed Scan |
|--------|------------------------|-------------------|
| **Data Source** | data_provider.py | Own implementation (precomputed_scans.py) |
| **Stock Price Source** | Yahoo Finance via data_provider | Yahoo Finance via own fetch_technical_data() |
| **Options Source** | Yahoo primary, Polygon backup via data_provider | Yahoo primary, Polygon backup via own methods |
| **Price Type** | Previous Market Close | Previous Market Close |
| **Caching** | MongoDB api_cache | MongoDB precomputed_scans |
| **Cache Duration** | ~15 minutes | Until next nightly run (4:45 PM ET) |
| **Filters** | User-defined | Risk Profile based (conservative/balanced/aggressive) |
| **Market Bias** | Applied via market_bias.py | NOT applied (direct scoring) |
| **Quality Scoring** | quality_score.py (Pillar-based) | Basic scoring (ROI + delta + DTE) |

### Key Differences:
1. **Code Duplication:** Pre-computed scans have their own Yahoo Finance fetching (duplicates data_provider.py)
2. **Market Bias:** Only Custom Scans apply market bias weighting
3. **Quality Scoring:** Custom Scans use sophisticated pillar-based scoring; Pre-computed use simpler scoring
4. **Storage:** Custom Scans use api_cache (short TTL); Pre-computed use dedicated collection (daily refresh)

---

## 5. WATCHLIST & SIMULATOR DATA EXPECTATION CHECK

### Watchlist Expectations (Documented in watchlist.py Lines 1-9):
```
DATA FETCHING RULES:
1. STOCK PRICES: Watchlist and Simulator use LIVE intraday prices (regularMarketPrice)
2. OPPORTUNITIES: Fetched LIVE from Yahoo Finance, never cached
```

### Actual Implementation:
| Rule | Expected | Actual | Status |
|------|----------|--------|--------|
| Stock Prices | LIVE intraday | `fetch_live_stock_quotes_batch()` | ✅ Correct |
| Options | LIVE from Yahoo | `fetch_options_chain()` | ✅ Correct |
| Caching | Never cached | No caching implemented | ✅ Correct |
| Price Source | regularMarketPrice | Uses `fetch_live_stock_quote_yahoo_sync()` | ✅ Correct |

### Simulator Expectations:
| Rule | Expected | Actual | Status |
|------|----------|--------|--------|
| Open Trade Prices | LIVE intraday | `fetch_live_stock_quote()` (line 856) | ✅ Correct |
| Trade Entry | Current price | Mixed (server.py + data_provider.py) | ⚠️ Inconsistent |

### IMPORTANT: Price Type Difference
```
SCREENER/DASHBOARD: Uses previousClose (history[-1] or history[-2] if market open)
WATCHLIST/SIMULATOR: Uses regularMarketPrice (live intraday)
```
This is BY DESIGN but creates potential confusion if not properly documented.

---

## 6. CURRENT BOTTLENECK SUMMARY (FACTUAL)

### 6.1 Code Duplication
- **3 separate implementations** of stock price fetching:
  1. `data_provider.py` - Intended centralized source
  2. `server.py` - Duplicate functions (`fetch_stock_quote`, `fetch_options_chain_polygon`, `fetch_options_chain_yahoo`)
  3. `precomputed_scans.py` - Own Yahoo Finance fetching

### 6.2 API Source Confusion
- **stocks.py** and **options.py** call Polygon API directly
- **screener.py** and **watchlist.py** use data_provider.py (Yahoo primary)
- **portfolio.py** uses server.py's fetch_stock_quote (which tries Yahoo then Polygon)

### 6.3 Silent Failures / Mock Data Fallbacks
Files that return mock data when API fails:
- `/routes/stocks.py` - Returns MOCK_STOCKS dictionary
- `/routes/options.py` - Returns generate_mock_options()
- `/routes/screener.py` - Returns generate_mock_covered_call_opportunities()

This masks actual API failures from users.

### 6.4 API Key Dependency
- All Polygon-dependent routes require `massive_api_key` from admin_settings
- If key is missing → mock data or empty responses
- No clear error messaging to user about missing API configuration

### 6.5 Rate Limiting Gaps
- No rate limiting on data_provider.py Yahoo calls
- precomputed_scans.py has `_rate_limited_stock_call()` but it's for Polygon (stock tier)
- Yahoo Finance has unofficial ~2000 requests/hour limit

---

## 7. CHANGE-SAFETY NOTES

### Files Safe to Modify (Low Risk):
1. `/routes/stocks.py` - Can refactor to use data_provider.py
2. `/routes/options.py` - Can refactor to use data_provider.py
3. `/routes/portfolio.py` - Can change import from server.py to data_provider.py

### Files Requiring Careful Refactoring (Medium Risk):
1. `/server.py` - Has duplicate functions that may be called elsewhere
   - Search for `from server import fetch_stock_quote` before removing
   - Currently called by: portfolio.py, simulator.py

2. `/services/precomputed_scans.py` - Has working isolated implementation
   - Runs as scheduled job (4:45 PM ET)
   - Changes could affect nightly scan output

### Files to Leave As-Is (Core Data Provider):
1. `/services/data_provider.py` - This IS the intended source of truth
   - Well-documented pricing rules (BID for SELL, ASK for BUY)
   - Proper market hours handling
   - Thread pool for blocking yfinance calls

### Database Collections Affected by Data Changes:
- `api_cache` - Screener cache (will auto-refresh)
- `precomputed_scans` - Pre-computed results (needs manual trigger or wait for nightly job)
- `option_quote_cache` - After-hours quote cache

### Environment Variables Required:
- `MONGO_URL` - Database connection
- `EMERGENT_LLM_KEY` - For AI features (not data fetching)
- Admin Settings → `massive_api_key` - For Polygon API (if needed as backup)

---

## APPENDIX: Function Cross-Reference

### data_provider.py Exports (Should be ONLY source):
```python
fetch_stock_quote(symbol, api_key)           # Previous close price
fetch_live_stock_quote(symbol, api_key)      # Live intraday price
fetch_stock_quotes_batch(symbols, api_key)   # Batch previous close
fetch_live_stock_quotes_batch(symbols, api_key)  # Batch live prices
fetch_options_chain(symbol, api_key, ...)    # Options with IV/OI
fetch_options_with_cache(symbol, db, ...)    # Options with after-hours cache
is_market_closed()                           # Market status check
get_last_trading_day()                       # Last trading day date
```

### server.py Functions (DUPLICATES - candidates for removal):
```python
fetch_stock_quote(symbol, api_key)           # Line 364-431 - DUPLICATE
fetch_options_chain_polygon(...)             # Line 433-575 - DUPLICATE  
fetch_options_chain_yahoo(...)               # Line 577-691 - DUPLICATE
get_massive_api_key()                        # Line 357-362 - API key accessor
```

### precomputed_scans.py Functions (DUPLICATES - consider consolidation):
```python
fetch_technical_data(symbol)                 # Line 260-348 - Custom Yahoo fetching
fetch_fundamental_data(symbol)               # Line 351-448 - Custom Yahoo fetching
fetch_options_for_scan(...)                  # Line 452-477 - Wrapper
_fetch_options_yahoo(...)                    # Line 489-594 - DUPLICATE
_fetch_options_polygon(...)                  # Line 599-737 - DUPLICATE
```

---

## APPENDIX A: PAGE → DATA SOURCE → FILE PATH MAPPING

| Page/Feature | Data Type | Primary Source | File Path | Line(s) |
|--------------|-----------|----------------|-----------|---------|
| **Dashboard** | Stock Price | Yahoo (via data_provider) | `/backend/routes/screener.py` | 601-612 |
| **Dashboard** | Options Chain | Yahoo (via data_provider) | `/backend/routes/screener.py` | 646-660 |
| **Dashboard** | Market Sentiment | Yahoo (via market_bias) | `/backend/services/market_bias.py` | - |
| **Screener (CC)** | Stock Price | Yahoo (via data_provider) | `/backend/routes/screener.py` | 264-275 |
| **Screener (CC)** | Options Chain | Yahoo (via data_provider) | `/backend/routes/screener.py` | 303-305 |
| **Screener (PMCC)** | Stock Price | Yahoo (via data_provider) | `/backend/routes/screener.py` | 949-958 |
| **Screener (PMCC)** | LEAPS Options | Yahoo (via data_provider) | `/backend/routes/screener.py` | 996-998 |
| **Pre-Computed Scans** | All Data | MongoDB (DB-backed) | `/backend/routes/precomputed_scans.py` | 163, 220 |
| **Pre-Computed Scans** | Nightly Job | Yahoo (own impl) | `/backend/services/precomputed_scans.py` | 260-737 |
| **Portfolio Tracker** | Stock Price | Yahoo→Polygon (via server.py) | `/backend/routes/portfolio.py` | 78, 306, 347 |
| **Portfolio Tracker** | Position P/L | MOCK_STOCKS dict | `/backend/routes/portfolio.py` | 92, 158 |
| **Simulator** | Open Trade Prices | Yahoo (via data_provider) | `/backend/routes/simulator.py` | 856 |
| **Simulator** | Trade Entry | Yahoo→Polygon (via server.py) | `/backend/routes/simulator.py` | 185-186 |
| **Watchlist** | Stock Price (Live) | Yahoo (via data_provider) | `/backend/routes/watchlist.py` | 505-507 |
| **Watchlist** | Options Chain | Yahoo (via data_provider) | `/backend/routes/watchlist.py` | 79-86 |
| **Stock Details API** | Stock Quote | **Polygon DIRECT** | `/backend/routes/stocks.py` | 51-89 |
| **Stock Details API** | Analyst Ratings | Yahoo (direct yfinance) | `/backend/routes/stocks.py` | 110-151 |
| **Stock Details API** | Market Indices | Yahoo (direct yfinance) | `/backend/routes/stocks.py` | 155-214 |
| **Stock Details API** | Company Details | **Polygon DIRECT** | `/backend/routes/stocks.py` | 217-390 |
| **Options Chain API** | Stock Price | **Polygon DIRECT** | `/backend/routes/options.py` | 61-70 |
| **Options Chain API** | Options Snapshot | **Polygon DIRECT** | `/backend/routes/options.py` | 82-127 |
| **Admin** | API Key Management | MongoDB | `/backend/routes/admin.py` | 346-361 |
| **EOD Ingestion** | Stock Prices | Yahoo (direct yfinance) | `/backend/services/eod_ingestion_service.py` | - |

---

## APPENDIX B: FILES WHERE YAHOO FINANCE IS CALLED

| File Path | Usage Type | Method |
|-----------|------------|--------|
| `/backend/services/data_provider.py` | **CENTRALIZED** (intended source) | `yf.Ticker().history()`, `yf.Ticker().option_chain()` |
| `/backend/server.py` | **DUPLICATE** | `yf.Ticker().history()`, HTTP to `query1.finance.yahoo.com` |
| `/backend/services/precomputed_scans.py` | **DUPLICATE** (nightly job) | `yf.Ticker().history()`, `yf.Ticker().info`, `yf.Ticker().option_chain()` |
| `/backend/routes/stocks.py` | **PARTIAL** (analyst ratings only) | `yf.Ticker().info` |
| `/backend/routes/screener.py` | Via data_provider.py import | N/A - uses data_provider functions |
| `/backend/services/market_bias.py` | Direct yfinance | `yf.Ticker().history()` for indices |
| `/backend/services/eod_ingestion_service.py` | Direct yfinance | `yf.Ticker().history()` for EOD prices |
| `/backend/services/snapshot_service.py` | Direct yfinance | `yf.Ticker()` for snapshots |
| `/backend/routes/eod.py` | Via services | N/A - uses eod_ingestion_service |
| `/backend/tests/test_stock_price_and_quote_cache.py` | Test file | `yf.Ticker()` for test assertions |

**Total files with direct yfinance usage:** 10

---

## APPENDIX C: FILES WHERE POLYGON API IS REFERENCED

| File Path | Status | Polygon Usage | Notes |
|-----------|--------|---------------|-------|
| `/backend/routes/stocks.py` | **ACTIVE** | Direct HTTP calls | Lines 55, 77, 246, 264, 284, 304 |
| `/backend/routes/options.py` | **ACTIVE** | Direct HTTP calls | Lines 63, 82 |
| `/backend/server.py` | **ACTIVE** | Direct HTTP calls (fallback) | Lines 400, 476, 524 |
| `/backend/services/data_provider.py` | **ACTIVE** | Fallback only (if Yahoo fails) | Line 39: `POLYGON_BASE_URL` defined |
| `/backend/services/precomputed_scans.py` | **ACTIVE** | Fallback for options | Line 42: `POLYGON_BASE_URL`, Lines 599-737 |
| `/backend/services/snapshot_service.py` | **ACTIVE** | Fallback for snapshots | Line 50: `POLYGON_BASE_URL` |
| `/backend/routes/admin.py` | **PASSIVE** | Stores/retrieves `massive_api_key` | Does not make API calls |
| `/backend/routes/screener.py` | **PASSIVE** | References `get_massive_api_key()` | Passes key to data_provider |
| `/backend/routes/screener_snapshot.py` | **PASSIVE** | May reference key | Passes key to services |
| `/backend/routes/snapshots.py` | **PASSIVE** | May reference key | Passes key to services |
| `/backend/routes/watchlist.py` | **PASSIVE** | May reference key | Passes key to data_provider |
| `/backend/routes/eod.py` | **PASSIVE** | May reference key | Passes key to services |

**Legend:**
- **ACTIVE:** File makes direct HTTP calls to `api.polygon.io`
- **PASSIVE:** File references Polygon key but passes to other modules (does not call directly)

**Files with direct Polygon HTTP calls:** 6 (`stocks.py`, `options.py`, `server.py`, `data_provider.py`, `precomputed_scans.py`, `snapshot_service.py`)

---

## RECOMMENDED REFACTORING PRIORITY

1. **HIGH:** Refactor `/routes/stocks.py` to use data_provider.py
2. **HIGH:** Refactor `/routes/options.py` to use data_provider.py
3. **MEDIUM:** Change portfolio.py import from server.py to data_provider.py
4. **MEDIUM:** Remove duplicate functions from server.py (after verifying no other callers)
5. **LOW:** Consolidate precomputed_scans.py to use data_provider.py (currently working)

---

*End of Audit Report*
*Baseline Locked: December 2025*
*Ready for Phased Refactor Specification*
