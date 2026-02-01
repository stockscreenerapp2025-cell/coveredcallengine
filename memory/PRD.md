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

---

## Portfolio Tracker - Position Lifecycle System - COMPLETED 2026-02-01

### Position Lifecycle Rules (Non-Negotiable)
Each stock position is tracked as a separate **lifecycle**, even for the same ticker:

1. **Lifecycle STARTS**: When shares are bought (BUY or PUT ASSIGNMENT)
2. **Lifecycle ENDS**: When ALL shares are sold or call-assigned
3. **Assignment closes the lifecycle**: Position marked CLOSED, P/L locked
4. **Re-buying same ticker starts NEW lifecycle**: Entry price = new buy price

### Entry Price Rule
- Entry Price = **execution price of BUY/ASSIGNMENT in THIS lifecycle**
- Do NOT average across historical closed positions
- Each lifecycle's metrics are completely isolated

### Position Instance ID
Each lifecycle gets a unique identifier:
```
{SYMBOL}-{YYYY-MM}-Entry-{NN}
Examples:
- IREN-2024-05-Entry-01 (closed via assignment)
- IREN-2024-11-Entry-02 (current active position)
```

### Special Case: Wheel Strategy (CSP → Assignment → CC)
- CSP (naked put) → Put Assignment → Covered Call = **ONE lifecycle**
- The put sale, assignment, and subsequent CC are all part of the same lifecycle
- Only when CALL assignment closes the position does the lifecycle end

### Premium Tracking
- Premiums from previous lifecycles belong to closed positions
- New lifecycle starts with $0 premium
- Portfolio-level premium aggregation is separate from lifecycle metrics

### Validation Evidence (2026-02-01)
| Scenario | Expected | Actual | Status |
|----------|----------|--------|--------|
| IREN Buy→CC→Assign→Buy | 2 lifecycles | 2 lifecycles | ✅ PASS |
| IREN LC1 Entry | $75.18 | $75.18 | ✅ PASS |
| IREN LC2 Entry | $55.78 (new buy) | $55.78 | ✅ PASS |
| IONQ CSP→Assign→CC | 1 lifecycle (Wheel) | 1 lifecycle | ✅ PASS |
| IONQ Entry | $48.50 (put strike) | $48.50 | ✅ PASS |
| Premium Isolation | Per-lifecycle | Per-lifecycle | ✅ PASS |

### IMPORTANT: Users must RE-UPLOAD their CSV
Since existing data was parsed with old logic, users must **re-upload their IBKR CSV file** to see lifecycle-aware calculations.

---

## Portfolio Tracker - IBKR Parser Fix - COMPLETED 2026-01-31

### Entry Price Calculation (Critical Fix)
Fixed the entry price calculation to use **actual transaction prices** instead of `net_amount / quantity`:

**For BUY Transactions:**
- Entry price = The `price` field from the transaction (actual buy price)
- NOT `net_amount / quantity` (which includes fees)

**For PUT ASSIGNMENT (CSP → Wheel):**
- Entry price = The PUT STRIKE price (the price you're obligated to buy at)
- NOT `net_amount / quantity` (which includes fees and adjustments)

**Example Fixes:**
| Symbol | Old Entry | New Entry | Why |
|--------|-----------|-----------|-----|
| IONQ | $70.33 | $48.50 | Uses PUT strike for assignment |
| APLD | $35.45 | $35.42 | Uses actual transaction price |

### Break-Even Calculation
- BE = Entry Price - (Premium Received / Shares) + (Fees / Shares)
- For CSP: BE = Put Strike - Put Premium per share

### Option Symbol Parsing (Enhanced)
Now handles both IBKR formats:
1. **Standard**: `IONQ 260123P48500` → YYMMDD[C/P]STRIKE
2. **Human readable**: `IONQ 23JAN26 48.5 P` → DDMMMYY STRIKE [C/P]

### IMPORTANT: Users must RE-UPLOAD their CSV
Since the data is parsed and stored in the database, existing users must **re-upload their IBKR CSV file** to see the corrected calculations.

---

## Key Files

### Data Provider (SINGLE SOURCE OF TRUTH)
- `/app/backend/services/data_provider.py`:
  - `_fetch_stock_quote_yahoo_sync()` - Uses history() for last market close
  - `fetch_options_chain()` - Live options from Yahoo
  - `fetch_live_stock_quote()` - Live intraday price (Watchlist/Simulator)

### IBKR Parser (FIXED 2026-01-31)
- `/app/backend/services/ibkr_parser.py`:
  - `_parse_option_symbol()` - Now handles both human-readable and standard formats
  - `_create_trade_from_transactions()` - Lot-aware entry price calculation

### Routes
- `/app/backend/routes/screener_snapshot.py` - CC/PMCC screeners
- `/app/backend/routes/portfolio.py` - Portfolio Tracker API
- `/app/backend/routes/stocks.py` - Market indices

---

## Completed Tasks

### 2026-01-31
- [x] Fixed Portfolio Tracker Entry Price calculation
- [x] Fixed IBKR parser to use transaction price (not net_amount/qty)
- [x] Fixed PUT assignment entry price to use PUT strike
- [x] Enhanced option symbol parsing for both IBKR formats
- [x] Fixed Break-Even calculation with proper lot-awareness
- [x] Fixed IBKR Fees calculation to use commission field

### 2026-01-30
- [x] Fixed PMCC Screener - Completely isolated from CC logic
- [x] Updated LEAPS DTE from 180 days to 365-730 days (12-24 months)
- [x] Fixed undefined `breakeven` variable in PMCC response
- [x] Single Source of Truth for Stock Price (Yahoo Finance history)
- [x] Analyst Ratings Restored
- [x] Live Dashboard Index Data
- [x] After-Hours Options Pricing with quote caching
- [x] Strict BID/ASK Pricing Rules

---

## Pending Tasks

### P1 - High Priority
- [ ] Fix PMCC Custom Scan Price Rules - Stocks $30-$90, ETFs no limit
- [ ] Restore PMCC Pre-computed Aggressive Scan - Use cached EOD chains

### P2 - Medium Priority
- [ ] Decouple Manual Filters - Pull from universal US stocks/ETFs list
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
2026-01-31 - Portfolio Tracker Entry Price Fix (IBKR Parser)
