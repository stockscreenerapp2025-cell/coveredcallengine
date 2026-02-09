# Covered Call Engine - Product Requirements Document

## Original Problem Statement
Build a web-based application named "Covered Call Engine" for options traders with AI-assisted Covered Call (CC) and Poor Man's Covered Call (PMCC) screeners.

## CRITICAL: YAHOO FINANCE IS THE SINGLE SOURCE OF TRUTH

### Stock Price Source (ALL PAGES) - UPDATED 2026-02-01
- **Source**: Yahoo Finance `ticker.history(period='5d')` - **PREVIOUS MARKET CLOSE**
- **Market-Aware Selection**: 
  - If market is OPEN and last history date == today: Use index `-2` (previous close)
  - If market is CLOSED or last history date < today: Use index `-1` (last available)
- **NOT**: regularMarketPrice, currentPrice (intraday prices)
- **NOT**: EOD contract or cached prices
- **Applies to**: Dashboard, Screener, PMCC, Pre-Computed Scans, Customised Scans, Simulator, Watchlist, Admin
- **Centralized Functions**:
  - `data_provider._fetch_stock_quote_yahoo_sync()` - Primary source for all pages
  - `precomputed_scans.fetch_technical_data()` - Uses same logic for scan computations
- **Scheduled Jobs (4:05 PM ET daily on trading days)**:
  - EOD Ingestion: Market close price capture
  - Pre-computed Scans: CC and PMCC scan computation
  - Simulator Price Update: Update simulator positions
- **Manual Refresh**: Admin panel → Data Quality → "Trigger All Scans" button
- **Rate Limiting**: Batch size reduced to 10 symbols, 2-second delay between batches to avoid Yahoo Finance rate limits

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

## Portfolio Tracker - CSP Lifecycle Isolation & PMCC Rules - COMPLETED 2026-02-01

### Bug Fix: CSP Assignment Lifecycle Leakage

**Problem:** CSP assignments were being merged into a single lifecycle under the Wheel rule, even when they originated from different CSP contracts with different strikes.

**Fix:** Each CSP assignment now creates a distinct stock lifecycle:
- Entry price = PUT strike
- Quantity = assigned shares
- Start date = assignment date

**CSP Isolation Rules:**
- CSP assignments are NOT merged unless: Same ticker, Same assignment date, Same strike, Same option expiry
- CCs sold after assignment attach ONLY to the lifecycle they logically relate to
- The Wheel strategy rule applies within a SINGLE CSP → assignment → CC chain, not across multiple CSP contracts

### Bug Fix: PMCC Lifecycle Rules

**Problem:** PMCC lifecycles were not properly anchored to the long LEAPS call.

**Fix:** PMCC lifecycles are now anchored to the LONG LEAPS:
- Each long LEAPS creates a new PMCC lifecycle
- Short calls attach only if: Short strike > long strike, Short expiry < long expiry
- Short-call assignment does NOT close the PMCC lifecycle
- PMCC lifecycle closes only when the long LEAPS is sold or expires
- Premiums and P&L remain isolated within each PMCC lifecycle

### Position Instance ID Format
- **Stock/CC/Wheel:** `{SYMBOL}-{YYYY-MM}-Entry-{NN}` (e.g., `IREN-2026-01-Entry-01`)
- **PMCC:** `{SYMBOL}-PMCC-{YYYY-MM}-{LEAPS_STRIKE}-Entry-{NN}` (e.g., `AAPL-PMCC-2026-01-50.0-Entry-01`)

### Validation Evidence (2026-02-01)
| Scenario | Expected | Actual | Status |
|----------|----------|--------|--------|
| Multiple CSPs different strikes | Separate lifecycles | 2 lifecycles | ✅ PASS |
| CSP $55 entry | $55.00 | $55.00 | ✅ PASS |
| CSP $50 entry | $50.00 | $50.00 | ✅ PASS |
| CSP→CC Wheel | 1 lifecycle | 1 lifecycle | ✅ PASS |
| Multiple PMCC LEAPS | Separate lifecycles | 2 lifecycles | ✅ PASS |
| PMCC anchored to LEAPS | Per-LEAPS | Per-LEAPS | ✅ PASS |
| PMCC no stock shares | 0 shares | 0 shares | ✅ PASS |
| PMCC status until LEAPS expires | Open | Open | ✅ PASS |

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

## Simulator Page - Trade Lifecycle Model - COMPLETED 2026-02-02

### Trade Lifecycle States (Foundational Fix)

**Problem:** Analytics and PMCC Tracker pages were blank because:
1. Analytics only queried CLOSED trades, ignoring OPEN/ASSIGNED/EXPIRED
2. PMCC Tracker incorrectly depended on "closed only" trades
3. Status values were inconsistent

**Fix:** Explicit lifecycle states now drive visibility, analytics, and strategy logic.

**Covered Call (CC) Lifecycle:**
| Status | Description |
|--------|-------------|
| `open` | Call sold, position active |
| `expired` | Call expires OTM (WIN) |
| `assigned` | Shares called away (WIN for CC) |
| `closed` | Manually closed |

**PMCC Lifecycle:**
| Status | Description |
|--------|-------------|
| `open` | Long LEAPS + short call active |
| `rolled` | Short call closed and replaced |
| `assigned` | Short call assigned (BAD - avoid!) |
| `closed` | PMCC fully exited |

**Critical Rule: ASSIGNED = CLOSED for analytics**

### Analytics Engine Fix
- Analytics now includes: OPEN + EXPIRED + ASSIGNED trades (not just closed)
- Win Rate calculation: Assignment = WIN, Expired OTM = WIN, Profitable close = WIN
- New metrics: assignment_rate, capital_efficiency, profit_factor
- Performance by Outcome section shows Expired/Assigned/Closed counts

### PMCC Tracker Fix
- Now displays: OPEN, ROLLED, ASSIGNED trades (not just closed)
- Health status indicators: good/warning/critical
- Income vs LEAPS Decay tracking with progress bars
- Fields: income_to_cost_ratio, estimated_leaps_decay_pct

### PMCC Roll Functionality (NEW)
- `/api/simulator/trades/{trade_id}/roll` - Roll short call to new strike/expiry
- `/api/simulator/trades/{trade_id}/roll-suggestions` - Get roll recommendations
- Tracks roll_count, last_roll_date, total_premium_captured
- Warning: "In PMCC, short call assignment should be AVOIDED"

### Backward Compatibility
- Existing trades with `active` status are handled alongside `open`
- All filters include both: `["open", "rolled", "active"]`

### Validation Evidence (2026-02-02)
| Feature | Expected | Actual | Status |
|---------|----------|--------|--------|
| Trades Tab | 24 trades | 24 trades | ✅ PASS |
| Analytics Tab | NOT blank | Shows data | ✅ PASS |
| Total P/L | Shows value | $116,205 | ✅ PASS |
| Win Rate | Includes assigned | 100% | ✅ PASS |
| PMCC Tracker | NOT blank | 4/6 positions | ✅ PASS |
| Health Status | Shows indicators | good/critical | ✅ PASS |
| Test DAL | Expired | Expired | ✅ PASS |
| Test INTC | Assigned | Assigned | ✅ PASS |
| Test COP | Active | Active | ✅ PASS |

---

## Simulator Trade Management Rules - Income Strategy Redesign - COMPLETED 2026-02-02

### Core Principle
For CC and PMCC, **loss is NOT managed via stop-loss**. Loss is managed via:
- Time
- Premium decay
- Rolling
- Assignment logic

**Key Changes:**
- ❌ Stop-loss rules removed as defaults (moved to Optional/Advanced)
- ✅ Rolling becomes the primary management mechanic
- ✅ Assignment treated as valid income outcome for CC
- ✅ PMCC assignment should be avoided (roll first)
- ✅ Brokerage-aware controls added

### Rule Categories (Income Strategy)

| Category | Description | Default Rules |
|----------|-------------|---------------|
| **Premium Harvesting** | No Early Close | Hold to Expiry |
| **Expiry Decisions** | Primary Controls | OTM Expiry, ITM Assignment |
| **Assignment Awareness** | Alerts Only | Risk Alert, Imminent Alert |
| **Rolling Rules** | Core Income Logic | ITM Roll, Delta-Based Roll, Market-Aware Suggestions |
| **PMCC-Specific** | Short Leg Focused | Manage Short Only, Assignment Handling, Roll Before Assignment |
| **Brokerage-Aware** | Cost Controls | Avoid Early Close |
| **Informational** | Non-Action | Income Strategy Reminder |
| **Optional/Advanced** | NOT Recommended | 75% Profit Target, 200% Stop Loss |

### PMCC Assignment Philosophy
**In PMCC, short call assignment should be AVOIDED:**
- Assignment destroys the PMCC structure
- Roll the short call before it goes ITM
- If assigned, prompt user to exercise or close LEAPS

### Rolling Rules
**Roll ITM Near Expiry:**
- Trigger: ITM + DTE ≤ 7
- Action: Roll out in time
- Preference: Same or higher strike, net credit ≥ $0

**Roll Delta-Based:**
- Trigger: Delta ≥ 0.75 + DTE > 7
- Action: Roll up and out
- Target: Delta 0.25-0.35, net credit preferred

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
- `/app/backend/routes/simulator.py` - Simulator with lifecycle management (FIXED 2026-02-02)

---

## Completed Tasks

### 2026-02-02
- [x] Fixed Simulator Analytics - Now includes OPEN + EXPIRED + ASSIGNED trades
- [x] Fixed PMCC Tracker - Now displays OPEN, ROLLED, ASSIGNED positions
- [x] Added PMCC Roll functionality with roll suggestions
- [x] Added health status indicators for PMCC positions
- [x] Implemented Trade Lifecycle Model (ASSIGNED = CLOSED for analytics)
- [x] Added income_to_cost_ratio and estimated_leaps_decay_pct for PMCC
- [x] Backward compatibility for legacy 'active' status
- [x] **Redesigned Trade Management Rules for Income Strategy**
  - Removed stop-loss rules as defaults
  - Added Premium Harvesting, Expiry Management, Rolling Rules categories
  - Added PMCC-specific rules (manage short only, roll before assignment)
  - Added Brokerage-Aware controls
  - De-emphasized early close and stop-loss (moved to Optional/Advanced)
- [x] **Analyzer Page Enhancement - 3-Row Fixed Structure**
  - Row 1: Outcome (Total P/L, Win Rate, ROI, Avg Win/Loss, Expectancy, Max Drawdown, TWR)
  - Row 2: Risk & Capital (Peak Capital, Avg Capital, Worst Case Loss, Assignment Exposure CC/PMCC)
  - Row 3: Strategy Health (Win Rate, Avg Hold, Profit Factor by Strategy + Charts)
  - Scope-aware filtering: Portfolio/Strategy/Symbol
  - All metrics recompute when scope changes

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
2025-12 - Market Data Sourcing Audit Complete

---

## Market Data Sourcing Audit - COMPLETED 2025-12

### Audit Output
Full audit report saved to: `/app/memory/DATA_SOURCING_AUDIT.md`

### Key Findings

**Data Provider Schism Identified:**
The codebase has multiple parallel data fetching implementations rather than using `data_provider.py` exclusively:
1. `data_provider.py` - Intended centralized source (Yahoo primary)
2. `server.py` - Contains duplicate fetch_stock_quote(), fetch_options_chain_polygon(), fetch_options_chain_yahoo()
3. `routes/stocks.py` - Direct Polygon API calls (BYPASSES data_provider.py)
4. `routes/options.py` - Direct Polygon API calls (BYPASSES data_provider.py)
5. `services/precomputed_scans.py` - Own Yahoo Finance fetching (duplicates data_provider.py)

**Files Using data_provider.py Correctly:**
- `/routes/screener.py` ✅
- `/routes/watchlist.py` ✅
- `/routes/simulator.py` (partial) ✅

**Files Bypassing data_provider.py:**
- `/routes/stocks.py` ❌ - Direct Polygon calls
- `/routes/options.py` ❌ - Direct Polygon calls
- `/routes/portfolio.py` ⚠️ - Uses server.py's fetch_stock_quote
- `/services/precomputed_scans.py` ⚠️ - Own implementation (working)

### Recommended Refactoring Priority
1. **HIGH:** Refactor `/routes/stocks.py` to use data_provider.py
2. **HIGH:** Refactor `/routes/options.py` to use data_provider.py
3. **MEDIUM:** Change portfolio.py import from server.py to data_provider.py
4. **MEDIUM:** Remove duplicate functions from server.py
5. **LOW:** Consolidate precomputed_scans.py to use data_provider.py
