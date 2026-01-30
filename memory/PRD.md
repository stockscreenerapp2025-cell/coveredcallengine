# Covered Call Engine - Product Requirements Document

## Original Problem Statement
Build a web-based application named "Covered Call Engine" for options traders with AI-assisted Covered Call (CC) and Poor Man's Covered Call (PMCC) screeners.

## CRITICAL: YAHOO FINANCE IS THE SINGLE SOURCE OF TRUTH

### Stock Price Source (ALL PAGES)
- **Source**: Yahoo Finance `ticker.history(period='5d')` - most recent market close
- **NOT**: previousClose (which is prior day's close)
- **NOT**: EOD contract or cached prices
- **Applies to**: Dashboard, Screener, PMCC, Simulator, Watchlist

### Options Chain Source
- **Source**: Yahoo Finance live options chain
- **Pricing Rules**:
  - SELL legs: BID only (reject if BID=0)
  - BUY legs: ASK only (reject if ASK=0)
  - NEVER use: lastPrice, mid, theoretical price

### Market Indices
- **Source**: Yahoo Finance history() via ETF proxies (SPY, QQQ, DIA, IWM)
- **Works**: After hours, weekends

### Analyst Ratings
- **Source**: Yahoo Finance `ticker.info.recommendationKey`
- **Mapping**: strong_buy→Strong Buy, buy→Buy, hold→Hold, etc.

---

## PMCC Screener (ISOLATED FROM CC) - COMPLETED 2026-01-30

### PMCC Chain Selection Rules
The PMCC screener is **completely isolated** from CC logic with its own constants and chain selection rules:

**LONG LEG (LEAPS CALL):**
- Expiry: **12-24 months** (365-730 days) from current date
- Strike: **BELOW** the current stock price (ITM)
- Option price: **ASK only**
- Both BID and ASK must be > 0 (reject otherwise)

**SHORT LEG (CALL):**
- Expiry: **≤60 days**
- Strike: **ABOVE** the long-leg strike
- Option price: **BID only**
- Both BID and ASK must be > 0 (reject otherwise)

**NET DEBIT CALCULATION:**
- Net debit = Long-leg ASK - Short-leg BID
- LAST price is NEVER used

**PRICE FILTERS (PMCC-specific):**
- Stocks: $30-$90
- ETFs: No price limits

### Validation Evidence (2026-01-30)
| Rule | Expected | Actual | Status |
|------|----------|--------|--------|
| LEAPS DTE | 365-730 days | 412-720 days | ✅ PASS |
| LEAPS ITM | Strike < Stock Price | All results ITM | ✅ PASS |
| LEAPS Pricing | ASK only | Uses ASK | ✅ PASS |
| Short DTE | ≤60 days | 20-27 days | ✅ PASS |
| Short Strike | > LEAP Strike | All valid | ✅ PASS |
| Short Pricing | BID only | Uses BID | ✅ PASS |
| Net Debit | ASK - BID | Calculated correctly | ✅ PASS |
| BID/ASK Valid | Both > 0 | All validated | ✅ PASS |

---

## CC Screener (Separate from PMCC)

### CC Chain Selection Rules
- DTE: 7-45 days (weekly 7-14, monthly 21-45)
- Strike: OTM (above stock price)
- Pricing: BID only for SELL legs
- Price filters: $30-$90 for stocks, no limit for ETFs

---

## Architecture

```
YAHOO_SINGLE_SOURCE_OF_TRUTH
├── Stock Prices: ticker.history(period='5d') → most recent close
├── Options Chain: ticker.option_chain(expiry) → live BID/ASK
├── Analyst Rating: ticker.info.recommendationKey
├── Market Cap: ticker.info.marketCap
├── Avg Volume: ticker.info.averageVolume
└── Market Indices: ETF history (SPY, QQQ, DIA, IWM)

CC_PMCC_ISOLATION
├── CC Screener: /api/screener/covered-calls
│   ├── DTE: 7-45 days
│   ├── Strike: OTM
│   └── Uses: BID for premium
└── PMCC Screener: /api/screener/pmcc
    ├── LEAPS DTE: 365-730 days (12-24 months)
    ├── LEAPS Strike: ITM
    ├── Short DTE: ≤60 days
    └── Uses: ASK for LEAPS, BID for short
```

---

## Key Files

### Data Provider (SINGLE SOURCE OF TRUTH)
- `/app/backend/services/data_provider.py`:
  - `_fetch_stock_quote_yahoo_sync()` - Uses history() for last market close
  - `fetch_options_chain()` - Live options from Yahoo
  - `fetch_live_stock_quote()` - Live intraday price (Watchlist/Simulator)

### Routes Using Single Source
- `/app/backend/routes/screener_snapshot.py` - CC/PMCC screeners (PMCC fixed 2026-01-30)
- `/app/backend/routes/stocks.py` - Market indices
- `/app/backend/routes/watchlist.py` - Watchlist
- `/app/backend/routes/simulator.py` - Simulator

### PMCC Constants (lines 1079-1090 in screener_snapshot.py)
```python
PMCC_MIN_LEAP_DTE = 365  # 12 months minimum
PMCC_MAX_LEAP_DTE = 730  # 24 months maximum
PMCC_MIN_SHORT_DTE = 7
PMCC_MAX_SHORT_DTE = 60
PMCC_MIN_DELTA = 0.70
PMCC_STOCK_MIN_PRICE = 30.0
PMCC_STOCK_MAX_PRICE = 90.0
```

---

## Completed Tasks (2026-01-30)

### P0 - Critical
- [x] Fixed PMCC Screener - Completely isolated from CC logic
- [x] Updated LEAPS DTE from 180 days to 365-730 days (12-24 months)
- [x] Fixed undefined `breakeven` variable in PMCC response
- [x] All PMCC rules verified via testing agent (14/14 tests passed)

### Previous Session Completions
- [x] Single Source of Truth for Stock Price (Yahoo Finance history)
- [x] Analyst Ratings Restored
- [x] Live Dashboard Index Data
- [x] After-Hours Options Pricing with quote caching
- [x] Strict BID/ASK Pricing Rules

---

## Pending Tasks

### P1 - High Priority
- [ ] Fix PMCC Custom Scan Price Rules - Stocks $30-$90, ETFs no limit (separate from CC)
- [ ] Restore PMCC Pre-computed Aggressive Scan - Use end-of-day cached chains for after-hours

### P2 - Medium Priority
- [ ] Decouple Manual Filters - Pull from universal US stocks/ETFs list, blank defaults
- [ ] Validation Checklist - Provide logs/screenshots for all fixes

### Future/Backlog
- [ ] Fix inbound email support dashboard issue
- [ ] Expand symbol universe (more ETFs)
- [ ] Frontend refactor (break down large components)
- [ ] Deprecate legacy EOD snapshots

---

## Test Credentials
- **Admin Email**: admin@premiumhunter.com
- **Password**: admin123

---

## Last Updated
2026-01-30 - PMCC Screener Logic Fixed and Isolated from CC
