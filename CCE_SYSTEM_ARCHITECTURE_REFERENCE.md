# CCE (Covered Call Engine) - Admin & System Architecture Reference

## Document Information
- **Version**: 1.0
- **Last Updated**: December 2025
- **Purpose**: Comprehensive technical documentation for the CCE system
- **Audience**: System administrators, developers, and maintainers

---

## Table of Contents
1. [System Overview](#1-system-overview)
2. [Architecture Layers](#2-architecture-layers)
3. [User-Facing Pages](#3-user-facing-pages)
4. [Admin Panel Deep Dive](#4-admin-panel-deep-dive)
5. [Core Modules](#5-core-modules)
6. [Function Impact Matrix](#6-function-impact-matrix)
7. [Silent Fallback Inventory](#7-silent-fallback-inventory)
8. [Charts/Fundamentals/Technicals Sourcing Map](#8-chartsfundamentalstechnicals-sourcing-map)
9. [Database Schema Reference](#9-database-schema-reference)
10. [Scheduled Jobs](#10-scheduled-jobs)
11. [Third-Party Integrations](#11-third-party-integrations)
12. [Completeness Checklist](#12-completeness-checklist)

---

## 1. System Overview

### 1.1 Technology Stack
| Layer | Technology | Purpose |
|-------|------------|---------|
| Frontend | React 18 | Single-page application |
| Backend | FastAPI (Python) | REST API server |
| Database | MongoDB | Primary data store |
| Data Provider | Yahoo Finance (yfinance) | Market data source |
| Scheduler | APScheduler | Automated jobs |
| Payments | PayPal NVP API | Subscription billing |
| AI | OpenAI GPT | AI analysis features |

**File Reference**: `/app/backend/server.py` (Lines 1-82)

### 1.2 Core Business Logic
CCE is an options trading screener focused on two primary strategies:
1. **Covered Calls (CC)**: Sell call options against owned stock
2. **Poor Man's Covered Calls (PMCC)**: Buy LEAPS, sell short-dated calls

### 1.3 Data Flow Architecture
```
┌────────────────────────────────────────────────────────────────────┐
│                      DATA FLOW OVERVIEW                             │
├────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Yahoo Finance API                                                  │
│       │                                                             │
│       ▼                                                             │
│  ┌─────────────────┐    ┌─────────────────┐                        │
│  │ EOD Pipeline    │───▶│ MongoDB         │                        │
│  │ (4:10 PM ET)    │    │ Collections     │                        │
│  └─────────────────┘    └────────┬────────┘                        │
│                                  │                                  │
│       ┌──────────────────────────┼──────────────────────────┐      │
│       ▼                          ▼                          ▼      │
│  ┌──────────┐            ┌──────────────┐           ┌──────────┐  │
│  │Dashboard │            │  Screener    │           │ Watchlist │  │
│  │ Top 10   │            │  (CC/PMCC)   │           │           │  │
│  └──────────┘            └──────────────┘           └──────────┘  │
│                                                                     │
└────────────────────────────────────────────────────────────────────┘
```

---

## 2. Architecture Layers

### 2.1 Layer 1: Data Ingestion (EOD Pipeline)
**File**: `/app/backend/services/eod_pipeline.py`

**Purpose**: Runs at 4:10 PM ET on weekdays to pre-compute all scan results.

**Key Functions**:
| Function | Line | Purpose |
|----------|------|---------|
| `run_eod_pipeline()` | ~900 | Main entry point |
| `fetch_bulk_quotes_sync()` | 159-343 | Batch stock price fetch |
| `compute_scan_results()` | 1477-1680 | Generate CC/PMCC opportunities |
| `validate_cc_option()` | 1194-1233 | Validate CC eligibility |
| `validate_pmcc_structure()` | 1236-1401 | Validate PMCC eligibility |

**Output Collections**:
- `scan_results_cc` - Pre-computed covered call opportunities
- `scan_results_pmcc` - Pre-computed PMCC opportunities
- `scan_universe_audit` - Audit trail of inclusions/exclusions
- `scan_runs` - Pipeline execution history

### 2.2 Layer 2: Data Validation (Chain Validator)
**File**: `/app/backend/services/chain_validator.py`

**Purpose**: Validates option chain data quality before use in scans.

**Key Rules**:
- Bid-ask spread must be < 10% for liquid options
- Open interest minimum: 10 for CC, 100 for PMCC
- Volume minimum: 1 for active trading
- IV must be within 1%-500% range

### 2.3 Layer 3: Strategy Selection (Screener Routes)
**File**: `/app/backend/routes/screener_snapshot.py`

**Purpose**: Query pre-computed results and apply user filters.

**Key Principle**: 
> **NO LIVE YAHOO CALLS during request/response cycle**
> All scan data comes from MongoDB only (Lines 1-22)

**Key Functions**:
| Function | Line | Purpose |
|----------|------|---------|
| `screen_covered_calls()` | 525-750 | CC scan endpoint |
| `screen_pmcc()` | 1605-1730 | PMCC scan endpoint |
| `get_dashboard_opportunities()` | 1750-1850 | Dashboard Top 10 |
| `select_best_option_per_symbol()` | 242-310 | Deduplicate to 1 per stock |

---

## 3. User-Facing Pages

### 3.1 Dashboard
**Frontend**: `/app/frontend/src/pages/Dashboard.js`
**Backend**: `/app/backend/routes/screener_snapshot.py` (endpoint: `/api/screener/dashboard-opportunities`)

#### Data Retrieval Logic
1. **Primary Source**: `scan_results_cc` collection (pre-computed)
2. **Fallback**: Custom scan if no EOD run exists
3. **Limit**: Top 10 opportunities by AI score

#### Source of Truth Rules
| Data Field | Source | Fallback |
|------------|--------|----------|
| Stock Price | `symbol_snapshot.session_close_price` | None (reject row) |
| Option Premium | `scan_results_cc.premium_bid` | None (reject row) |
| Delta | Black-Scholes calculation | None (reject row) |
| IV Rank | `symbol_enrichment.iv_rank` | 50 (neutral default) |

**File Reference**: `/app/backend/routes/screener_snapshot.py` (Lines 1750-1850)

### 3.2 Screener (Covered Calls)
**Frontend**: `/app/frontend/src/pages/Screener.js`
**Backend**: `/app/backend/routes/screener_snapshot.py` (endpoint: `/api/screener/covered-calls`)

#### Data Retrieval Logic
1. Check for latest completed EOD run in `scan_runs`
2. Query `scan_results_cc` with user filters
3. Apply `select_best_option_per_symbol()` for deduplication
4. Transform results via `_transform_cc_result()`

#### Filter Parameters
| Parameter | Default | Range | DB Query |
|-----------|---------|-------|----------|
| min_price | 30 | 1-10000 | `stock_price: {$gte: value}` |
| max_price | 90 | 1-10000 | `stock_price: {$lte: value}` |
| min_dte | 7 | 1-365 | `dte: {$gte: value}` |
| max_dte | 45 | 1-365 | `dte: {$lte: value}` |
| min_delta | 0.15 | 0-1 | `delta: {$gte: value}` |
| max_delta | 0.50 | 0-1 | `delta: {$lte: value}` |

**File Reference**: `/app/backend/routes/screener_snapshot.py` (Lines 525-750)

### 3.3 PMCC Screener
**Frontend**: `/app/frontend/src/pages/PMCC.js`
**Backend**: `/app/backend/routes/screener_snapshot.py` (endpoint: `/api/screener/pmcc`)

#### PMCC Strict Institutional Rules (Feb 2026)
| Category | Rule | Value | Enforcement |
|----------|------|-------|-------------|
| LEAP DTE | Range | 365-730 days | HARD (reject if outside) |
| LEAP Delta | Minimum | ≥ 0.80 | HARD |
| LEAP OI | Minimum | ≥ 100 | HARD |
| LEAP Spread | Maximum | ≤ 5% | HARD |
| Short DTE | Range | 30-45 days | HARD |
| Short Delta | Range | 0.20-0.30 | HARD |
| Solvency | Check | net_debit ≤ width * 1.20 | HARD |
| Break-even | Check | short_strike > breakeven | SOFT (warning only) |

**File Reference**: `/app/backend/services/eod_pipeline.py` (Lines 1138-1160, 1236-1401)

### 3.4 Simulator
**Frontend**: `/app/frontend/src/pages/Simulator.js`
**Backend**: `/app/backend/routes/simulator.py`

#### Data Retrieval Logic
- **Stock Prices**: LIVE from Yahoo Finance (not EOD)
- **Trade Tracking**: `simulator_trades` collection
- **Rules Engine**: `simulator_rules` collection

#### Key Endpoints
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/simulator/trades` | GET | List user's simulated trades |
| `/api/simulator/trades` | POST | Add new trade |
| `/api/simulator/trades/{id}` | DELETE | Close trade |
| `/api/simulator/rules` | GET/POST | Trade management rules |

**File Reference**: `/app/backend/routes/simulator.py` (Lines 1-60)

### 3.5 Watchlist
**Frontend**: `/app/frontend/src/pages/Watchlist.js`
**Backend**: `/app/backend/routes/watchlist.py`

#### Data Retrieval Logic (Feb 2026 - EOD-Aligned)
**Default Mode** (`use_live_prices=false`):
- Stock prices from `symbol_snapshot.session_close_price`
- Opportunities from `scan_results_cc` (pre-computed)
- NO LIVE YAHOO CALLS

**Live Mode** (`use_live_prices=true`):
- Stock prices LIVE from Yahoo
- Opportunities computed LIVE from option chain

**File Reference**: `/app/backend/routes/watchlist.py` (Lines 746-875)

---

## 4. Admin Panel Deep Dive

### 4.1 Admin Dashboard
**Frontend**: `/app/frontend/src/pages/Admin.js`
**Backend**: `/app/backend/routes/admin.py`

#### 4.1.1 Dashboard Stats Endpoint
**Endpoint**: `GET /api/admin/dashboard-stats`
**File Reference**: `/app/backend/routes/admin.py` (Lines 148-212)

**Data Flow**:
```
Request → get_admin_dashboard_stats() → MongoDB queries (parallel) → Response
                                              │
                    ┌─────────────────────────┼─────────────────────────┐
                    ▼                         ▼                         ▼
              users collection         support_tickets          admin_settings
```

**Response Schema**:
```json
{
  "users": { "total": int, "active_7d": int, "trial": int },
  "subscriptions": { "active": int, "monthly": int, "yearly": int },
  "revenue": { "mrr": float, "arr": float },
  "alerts": { "trials_ending_soon": int, "open_tickets": int }
}
```

### 4.2 User Management
**Endpoint**: `GET /api/admin/users`
**File Reference**: `/app/backend/routes/admin.py` (Lines 216-254)

**Query Parameters**:
| Parameter | Type | Purpose |
|-----------|------|---------|
| page | int | Pagination |
| limit | int | Results per page (max 100) |
| status | str | Filter by subscription status |
| plan | str | Filter by plan type |
| search | str | Email/name search |

**Actions Available**:
| Endpoint | Action |
|----------|--------|
| `POST /api/admin/make-admin/{user_id}` | Promote to admin |
| `POST /api/admin/users/{user_id}/extend-trial` | Extend trial |
| `POST /api/admin/users/{user_id}/set-subscription` | Modify subscription |

### 4.3 EOD Pipeline Status
**Endpoint**: `GET /api/admin/eod-snapshot/status`
**File Reference**: `/app/backend/routes/admin.py` (Lines 868-1030)

**Data Flow**:
```
Request → get_eod_snapshot_status() → scan_runs collection
                                    → scan_run_summary collection
                                    → symbol_snapshot collection
                                    → Response
```

**Response Fields**:
| Field | Source | Purpose |
|-------|--------|---------|
| `last_run` | `scan_runs` | Most recent pipeline execution |
| `symbols_included` | `scan_run_summary` | Count of successful symbols |
| `symbols_excluded` | `scan_run_summary` | Count of excluded symbols |
| `cc_count` | `scan_run_summary` | Covered call opportunities |
| `pmcc_count` | `scan_run_summary` | PMCC opportunities |
| `exclusion_breakdown` | `scan_run_summary.excluded_by_reason` | Why symbols failed |

### 4.4 Universe Audit Drilldown
**Endpoint**: `GET /api/admin/universe/excluded`
**File Reference**: `/app/backend/routes/admin.py` (Lines 1649-1745)

**Exclusion Stages**:
| Stage | Description |
|-------|-------------|
| QUOTE | Failed to fetch stock quote |
| LIQUIDITY_FILTER | Failed liquidity/price band checks |
| OPTIONS_CHAIN | Failed to fetch options chain |
| CHAIN_QUALITY | Chain is empty or stale |
| CONTRACT_QUALITY | Missing required contract fields |

**Exclusion Reasons**:
| Reason | Description |
|--------|-------------|
| MISSING_QUOTE | No stock quote available |
| RATE_LIMITED_CHAIN | Yahoo throttled request |
| MISSING_CHAIN | No options chain available |
| BAD_CHAIN_DATA | Stale or invalid chain data |
| MISSING_QUOTE_FIELDS | Both price fields are None |

### 4.5 Support Ticket Management
**Endpoint**: `GET /api/admin/support/tickets`
**File Reference**: `/app/backend/routes/admin.py` (Lines 540-680)

**Ticket Lifecycle**:
```
open → in_progress → resolved/closed
                  ↘ escalated
```

**Email Integration**:
- **Outbound**: Via SMTP (Hostinger)
- **Inbound**: Via IMAP sync (scheduled job)
- **Sync Job**: `support_email_sync` (every 5 minutes)

### 4.6 Email Automation
**File Reference**: `/app/backend/routes/admin.py` (Lines 320-450)

**Trigger Events**:
| Event | When Triggered |
|-------|---------------|
| `subscription_created` | New subscription activated |
| `subscription_renewed` | Recurring payment succeeded |
| `subscription_payment_failed` | Payment failed |
| `subscription_cancelled` | User cancelled |
| `trial_ending` | Trial ends within 3 days |
| `trial_ended` | Trial expired |

### 4.7 IV Metrics Verification
**Endpoint**: `GET /api/admin/iv-metrics/check/{symbol}`
**File Reference**: `/app/backend/routes/admin.py` (Lines 1480-1548)

**Validates**:
- IV Rank calculation (0-100)
- IV Percentile calculation
- Bootstrap behavior (sample count)
- Delta source (Black-Scholes vs fallback)

---

## 5. Core Modules

### 5.1 Payment System (AI Wallet + PayPal)

#### 5.1.1 AI Wallet Architecture
**Files**:
- `/app/backend/ai_wallet/routes.py` - API endpoints
- `/app/backend/ai_wallet/guard.py` - Pre-execution guard
- `/app/backend/ai_wallet/wallet_service.py` - Token management
- `/app/backend/ai_wallet/paypal_service.py` - PayPal integration

**Token Flow**:
```
User Request → AI Guard Check → Token Deduction → AI Execution
                    │                  │              │
                    ▼                  ▼              ▼
              Rate Limit        Wallet Balance    OpenAI API
              Concurrency       Free + Paid       
```

**Guard Enforcement** (`/app/backend/ai_wallet/guard.py` Lines 91-178):
| Check | Order | Failure Response |
|-------|-------|------------------|
| AI Enabled | 1 | 402 AI_DISABLED |
| Token Limit | 2 | 402 ACTION_TOO_LARGE |
| Rate Limit | 3 | 429 RATE_LIMIT |
| Concurrency | 4 | 429 CONCURRENCY_LIMIT |
| Balance | 5 | 402 INSUFFICIENT_TOKENS |

**Token Deduction** (Atomic MongoDB Operation):
```python
# From /app/backend/ai_wallet/wallet_service.py
result = await db.ai_wallet.update_one(
    {"user_id": user_id, "total_balance": {"$gte": tokens_required}},
    {"$inc": {"total_balance": -tokens_required, ...}}
)
```

#### 5.1.2 PayPal Integration
**File**: `/app/backend/routes/paypal.py`

**Endpoints**:
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/paypal/create-checkout` | POST | Create Express Checkout |
| `/api/paypal/checkout-return` | GET | Handle return from PayPal |
| `/api/paypal/ipn-webhook` | POST | Process IPN notifications |

**Subscription Flow**:
```
User → Create Checkout → PayPal Redirect → Approval → Return Handler
                                                          │
                                            Create Recurring Profile
                                                          │
                                            Update user.subscription
                                                          │
                                            Trigger Email Automation
```

**File Reference**: `/app/backend/routes/paypal.py` (Lines 87-260)

### 5.2 Scheduled Jobs

#### 5.2.1 Job Registry
**File**: `/app/backend/server.py` (Lines 1416-1460)

| Job ID | Schedule | Function | Purpose |
|--------|----------|----------|---------|
| `eod_pipeline_scan` | 4:10 PM ET Mon-Fri | `run_eod_pipeline()` | Pre-compute scans |
| `simulator_price_update` | 4:05 PM ET Mon-Fri | `scheduled_price_update()` | Update trade prices |
| `support_auto_response` | Every 5 min | `process_support_auto_responses()` | Auto-reply tickets |
| `support_email_sync` | Every 5 min | `support_email_sync_job()` | IMAP email sync |

#### 5.2.2 EOD Pipeline Job Detail
**File**: `/app/backend/services/eod_pipeline.py`

**Execution Stages**:
1. Load universe (1500 symbols from static files)
2. Batch fetch quotes via `yf.download()`
3. Fetch option chains per symbol
4. Compute CC opportunities
5. Compute PMCC opportunities
6. Persist to MongoDB

**Configuration**:
| Variable | Default | Purpose |
|----------|---------|---------|
| `BULK_QUOTE_BATCH_SIZE` | 50 | Symbols per download batch |
| `CHAIN_CONCURRENCY` | 1 | Parallel chain fetches |
| `CHAIN_SYMBOL_DELAY_MS` | 250 | Delay between symbols |
| `YAHOO_MAX_RETRIES` | 2 | Retry count on failure |

**File Reference**: `/app/backend/services/eod_pipeline.py` (Lines 134-157)

### 5.3 LLM/API Key Usage

#### 5.3.1 OpenAI Integration
**Files**:
- `/app/backend/routes/chatbot.py` - Chatbot endpoint
- `/app/backend/routes/ai.py` - AI analysis endpoint
- `/app/backend/services/chatbot_service.py` - Service layer

**Key Source**: `admin_settings.openai_api_key` in MongoDB

**Usage Pattern**:
```python
# From /app/backend/routes/ai.py
openai_key = await db.admin_settings.find_one({})
client = OpenAI(api_key=openai_key.get("openai_api_key"))
```

**Token Gating**: All AI calls go through `AIGuard` (`/app/backend/ai_wallet/guard.py`)

#### 5.3.2 Key Storage
| Key | Storage Location | Masked in API |
|-----|------------------|---------------|
| OpenAI API Key | `admin_settings.openai_api_key` | Yes (Lines 41-54 admin.py) |
| PayPal Credentials | `admin_settings.type=paypal_settings` | Yes |
| IMAP Password | `admin_settings.type=imap_settings` | Yes |

---

## 6. Function Impact Matrix

### 6.1 Critical Data Pipeline Functions

| Function | File:Line | Callers | Dependencies | Output | Failure Behavior |
|----------|-----------|---------|--------------|--------|------------------|
| `run_eod_pipeline()` | eod_pipeline.py:900 | Scheduler, Manual trigger | yfinance, MongoDB | CC/PMCC results | Logs error, marks run as FAILED |
| `fetch_bulk_quotes_sync()` | eod_pipeline.py:159 | `run_eod_pipeline` | yfinance.download() | Dict of quotes | Returns failure dict per symbol |
| `get_underlying_price_yf()` | yf_pricing.py:46 | All price endpoints | yfinance, market_state | (price, source, time) | Returns (None, "ERROR", None) |
| `validate_pmcc_structure()` | eod_pipeline.py:1236 | PMCC scan | pricing_rules | (bool, flags) | Returns (False, [flags]) |

### 6.2 API Route Functions

| Function | File:Line | Callers | Dependencies | Output | Failure Behavior |
|----------|-----------|---------|--------------|--------|------------------|
| `screen_covered_calls()` | screener_snapshot.py:525 | Frontend Screener | scan_results_cc | JSON response | HTTPException 500 |
| `get_watchlist()` | watchlist.py:746 | Frontend Watchlist | symbol_snapshot, scan_results_cc | JSON items | Returns empty list |
| `get_admin_dashboard_stats()` | admin.py:148 | Admin Dashboard | users, support_tickets | JSON stats | HTTPException 500 |
| `check_and_deduct()` | guard.py:91 | AI endpoints | ai_wallet collection | AIGuardResult | Returns allowed=False |

### 6.3 Service Functions

| Function | File:Line | Callers | Dependencies | Output | Failure Behavior |
|----------|-----------|---------|--------------|--------|------------------|
| `enrich_row()` | enrichment_service.py:187 | All scan endpoints | yfinance, symbol_enrichment | Enriched dict | Adds partial data |
| `get_iv_metrics_for_symbol()` | iv_rank_service.py | Scans, Watchlist | iv_history, yfinance | IVMetrics | Returns neutral 50 |
| `calculate_greeks()` | greeks_service.py | All option displays | Black-Scholes math | GreeksResult | Returns delta=0.3 default |

### 6.4 Database Operations

| Function | File:Line | Callers | Collection | Operation | Failure Behavior |
|----------|-----------|---------|------------|-----------|------------------|
| `deduct_tokens()` | wallet_service.py | AIGuard | ai_wallet | atomic update | Raises exception |
| `persist_universe_version()` | universe_builder.py | EOD pipeline | scan_universe_versions | upsert | Logs error, continues |
| `_store_snapshot_cache()` | data_provider.py:865 | Symbol lookups | market_snapshot_cache | upsert | Logs warning, continues |

---

## 7. Silent Fallback Inventory

### 7.1 Silent Fallbacks (User NOT Notified)

| Location | File:Line | Trigger | Fallback Value | Impact | Detection Method |
|----------|-----------|---------|----------------|--------|------------------|
| IV Rank Bootstrap | iv_rank_service.py | < 5 samples | 50 (neutral) | Moderate | Check `iv_rank_confidence=LOW` |
| Delta Calculation | greeks_service.py | Missing IV | 0.30 (default) | Low | Check `delta_source=DEFAULT` |
| Analyst Rating | enrichment_service.py | Yahoo fails | null | Low | Check field is null |
| Cache Hit | data_provider.py:843 | Cache valid | Cached data | Low | Check `from_cache=true` |

### 7.2 Explicit Fallbacks (User Notified via UI)

| Location | File:Line | Trigger | Fallback Value | UI Indicator |
|----------|-----------|---------|----------------|--------------|
| EOD Data Missing | screener_snapshot.py | No EOD run | Empty results | "No EOD run available" banner |
| Market Closed | Dashboard.js | is_open=false | Last session data | "Market Closed" badge |
| Live Data Unavailable | watchlist.py | Yahoo timeout | EOD snapshot | `quote_source=LAST_MARKET_SESSION` |

### 7.3 Rejection Behaviors (No Fallback)

| Location | File:Line | Trigger | Behavior | Detection |
|----------|-----------|---------|----------|-----------|
| Invalid BID | pricing_rules.py:48 | bid <= 0 | Row rejected | Row not in results |
| Solvency Fail | eod_pipeline.py:1376 | net_debit > width*1.2 | Row rejected | Quality flag in audit |
| Quote Missing | eod_pipeline.py:260 | Both prices None | Symbol excluded | `exclude_reason=MISSING_QUOTE_FIELDS` |

### 7.4 Fallback Classification Summary

| Type | Count | Risk Level | Monitoring |
|------|-------|------------|------------|
| Silent | 4 | Medium | Requires debug flags |
| Explicit | 3 | Low | Visible in UI |
| Rejection | 3 | None | Audit trail in DB |

---

## 8. Charts/Fundamentals/Technicals Sourcing Map

### 8.1 Price Data Sources

| Data Point | Primary Source | Fallback | File Reference |
|------------|----------------|----------|----------------|
| Stock Price (Market Open) | `fast_info.last_price` | `info.regularMarketPrice` | yf_pricing.py:102-163 |
| Stock Price (Market Closed) | `history(5d).Close[-1]` | None (reject) | yf_pricing.py:165-210 |
| Option Bid/Ask | `option_chain().calls.bid/ask` | None (reject) | yf_pricing.py:217-290 |
| Previous Close | `info.regularMarketPreviousClose` | `info.previousClose` | data_provider.py:310 |

### 8.2 Fundamental Data Sources

| Data Point | Source | API | Collection | File Reference |
|------------|--------|-----|------------|----------------|
| Analyst Rating | Yahoo Finance | `ticker.info.recommendationKey` | symbol_enrichment | enrichment_service.py:29-79 |
| Target Price | Yahoo Finance | `ticker.info.targetMeanPrice` | symbol_enrichment | enrichment_service.py:55-67 |
| Analyst Count | Yahoo Finance | `ticker.info.numberOfAnalystOpinions` | symbol_enrichment | enrichment_service.py:60 |
| Market Cap | Yahoo Finance | `ticker.info.marketCap` | symbol_snapshot | eod_pipeline.py:502-520 |

### 8.3 Technical Indicators Sources

| Indicator | Calculation Method | Source Data | File Reference |
|-----------|-------------------|-------------|----------------|
| Delta | Black-Scholes | IV, Stock Price, Strike, DTE | greeks_service.py |
| Gamma | Black-Scholes | Same as Delta | greeks_service.py |
| Theta | Black-Scholes | Same as Delta | greeks_service.py |
| Vega | Black-Scholes | Same as Delta | greeks_service.py |
| IV Rank | Percentile of current vs historical | iv_history collection | iv_rank_service.py |
| IV Percentile | Distribution position | iv_history collection | iv_rank_service.py |

### 8.4 IV Rank Calculation Pipeline

```
┌─────────────────────────────────────────────────────────────────────┐
│                     IV RANK CALCULATION                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  1. Get current ATM IV from option chain                            │
│  2. Query iv_history for symbol (past 252 trading days)             │
│  3. Apply Bootstrap Rules:                                          │
│     - < 5 samples → iv_rank = 50, confidence = LOW                  │
│     - 5-19 samples → shrinkage toward 50, confidence = MEDIUM       │
│     - ≥ 20 samples → true percentile rank, confidence = HIGH        │
│  4. Store today's IV (computed BEFORE rank calculation)             │
│                                                                      │
│  Formula: iv_rank = 100 * (iv_current - iv_low) / (iv_high - iv_low)│
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

**File Reference**: `/app/backend/services/iv_rank_service.py`

### 8.5 Frontend Data Rendering

| Component | Data Fields | Source Endpoint | Rendering |
|-----------|-------------|-----------------|-----------|
| Price Display | stock_price, change_pct | Multiple | `${price.toFixed(2)}` |
| Delta Badge | delta | scan_results_cc | `{delta.toFixed(2)}` |
| IV Rank | iv_rank | enrichment | `{iv_rank.toFixed(0)}%` or "N/A" |
| Analyst Badge | analyst_rating_label | enrichment | Color-coded badge |

**File Reference**: `/app/frontend/src/pages/Dashboard.js` (Lines 810-900)

---

## 9. Database Schema Reference

### 9.1 Core Collections

#### scan_results_cc
```javascript
{
  run_id: String,           // EOD run identifier
  symbol: String,           // Stock ticker
  stock_price: Number,      // Underlying price
  strike: Number,           // Option strike
  expiry: String,           // YYYY-MM-DD
  dte: Number,              // Days to expiration
  premium_bid: Number,      // SELL price (BID)
  premium_ask: Number,      // BUY price (ASK)
  delta: Number,            // Black-Scholes delta
  iv: Number,               // Implied volatility (decimal)
  iv_pct: Number,           // IV as percentage
  iv_rank: Number,          // 0-100 rank
  open_interest: Number,    // Contract OI
  score: Number,            // AI quality score
  quality_flags: [String],  // Warning flags
  created_at: ISODate       // Timestamp
}
```

#### scan_results_pmcc
```javascript
{
  run_id: String,
  symbol: String,
  stock_price: Number,
  // LEAP (Long leg)
  leap_strike: Number,
  leap_expiry: String,
  leap_dte: Number,
  leap_ask: Number,         // BUY price
  leap_delta: Number,
  // Short leg
  short_strike: Number,
  short_expiry: String,
  short_dte: Number,
  short_bid: Number,        // SELL price
  short_delta: Number,
  // Economics
  net_debit: Number,
  width: Number,
  max_profit: Number,
  breakeven: Number,
  roi_cycle: Number,
  // Quality
  score: Number,
  quality_flags: [String]
}
```

#### ai_wallet
```javascript
{
  user_id: String,          // Unique user ID
  free_tokens_remaining: Number,
  paid_tokens_remaining: Number,
  total_balance: Number,    // free + paid
  ai_enabled: Boolean,
  plan: String,             // basic/standard/premium
  reset_date: ISODate,      // Next free token reset
  created_at: ISODate
}
```

#### simulator_trades
```javascript
{
  id: String,               // UUID
  user_id: String,
  symbol: String,
  strategy_type: String,    // covered_call / pmcc
  status: String,           // open/rolled/expired/assigned/closed
  entry_underlying_price: Number,
  short_call_strike: Number,
  short_call_expiry: String,
  short_call_premium: Number,
  premium_received: Number,
  capital_deployed: Number,
  unrealized_pnl: Number,
  realized_pnl: Number,
  action_log: [Object],     // History of actions
  created_at: ISODate
}
```

### 9.2 Index Definitions
**File Reference**: `/app/backend/server.py` (Lines 1346-1396)

| Collection | Index | Type | Purpose |
|------------|-------|------|---------|
| users | email | unique | Auth lookup |
| scan_results_cc | (run_id, symbol) | compound | Query optimization |
| scan_runs | run_id | unique | Latest run lookup |
| ai_wallet | user_id | unique | Balance lookup |
| iv_history | (symbol, trading_date) | unique | History dedup |
| support_tickets | ticket_number | unique | Ticket lookup |

---

## 10. Scheduled Jobs

### 10.1 Job Configuration
**File Reference**: `/app/backend/server.py` (Lines 1416-1460)

| Job | Cron | Timezone | Function |
|-----|------|----------|----------|
| EOD Pipeline | `16:10 Mon-Fri` | America/New_York | `scheduled_eod_pipeline()` |
| Simulator Update | `16:05 Mon-Fri` | America/New_York | `scheduled_price_update()` |
| Auto Response | `*/5 * * * *` | UTC | `process_support_auto_responses()` |
| Email Sync | `*/5 * * * *` | UTC | `support_email_sync_job()` |

### 10.2 EOD Pipeline Execution Flow
```
16:10 PM ET
    │
    ▼
Load Universe (~1500 symbols)
    │
    ▼
Stage 1: Bulk Quote Fetch (batches of 50)
    │
    ▼
Stage 2: Option Chain Fetch (1 at a time, 250ms delay)
    │
    ▼
Stage 3: Compute CC Opportunities
    │
    ▼
Stage 4: Compute PMCC Opportunities
    │
    ▼
Stage 5: Persist to MongoDB
    │
    ▼
Mark scan_runs as COMPLETED
```

### 10.3 Monitoring
**Admin Endpoint**: `GET /api/admin/eod-snapshot/status`

**Health Indicators**:
| Metric | Healthy Range | Alert Threshold |
|--------|---------------|-----------------|
| Coverage Ratio | > 85% | < 70% |
| Throttle Ratio | < 5% | > 15% |
| Duration | < 10 min | > 20 min |
| CC Count | > 50 | < 10 |

---

## 11. Third-Party Integrations

### 11.1 Yahoo Finance (yfinance)
**Purpose**: Primary market data provider
**Usage**: Stock quotes, option chains, historical data

**Rate Limiting**:
- No official rate limit
- Throttle observed at ~100 req/min
- Mitigation: 250ms delay between calls, exponential backoff

**Key Files**:
- `/app/backend/services/yf_pricing.py`
- `/app/backend/services/data_provider.py`
- `/app/backend/services/eod_pipeline.py`

### 11.2 PayPal NVP API
**Purpose**: Subscription billing
**Mode**: Express Checkout + Recurring Profiles

**Endpoints Used**:
| Operation | NVP Method |
|-----------|------------|
| Create Checkout | SetExpressCheckout |
| Get Details | GetExpressCheckoutDetails |
| Create Profile | CreateRecurringPaymentsProfile |
| Get Profile | GetRecurringPaymentsProfileDetails |

**File Reference**: `/app/backend/services/paypal_service.py`

### 11.3 OpenAI
**Purpose**: AI-powered analysis features
**Model**: GPT-4 (configurable)

**Gating**: All calls through `AIGuard`
**Token Cost**: Configured in `/app/backend/ai_wallet/config.py`

### 11.4 APScheduler
**Purpose**: Job scheduling
**Mode**: AsyncIOScheduler

**File Reference**: `/app/backend/server.py` (Lines 28, 1416-1460)

---

## 12. Completeness Checklist

### 12.1 Mandatory Sections

| Section | Status | Notes |
|---------|--------|-------|
| System Architecture & Logic | ✅ Complete | Sections 1-3 |
| Admin Panel Deep Dive | ✅ Complete | Section 4 |
| Core Modules (Payments) | ✅ Complete | Section 5.1 |
| Core Modules (Scheduled Jobs) | ✅ Complete | Section 5.2, 10 |
| Core Modules (LLM/API Keys) | ✅ Complete | Section 5.3 |
| Core Modules (Charting/Fundamentals) | ✅ Complete | Section 8 |
| Function Impact Matrix | ✅ Complete | Section 6 |
| Silent Fallback Inventory | ✅ Complete | Section 7 |
| Charts/Fundamentals/Technicals Sourcing Map | ✅ Complete | Section 8 |

### 12.2 File References Provided

| Category | Files Referenced |
|----------|------------------|
| Backend Routes | admin.py, screener_snapshot.py, simulator.py, watchlist.py, paypal.py |
| Backend Services | eod_pipeline.py, data_provider.py, yf_pricing.py, pricing_rules.py, enrichment_service.py, greeks_service.py, iv_rank_service.py |
| AI Wallet | routes.py, guard.py, wallet_service.py, config.py |
| Frontend Pages | Dashboard.js, Screener.js, PMCC.js, Simulator.js, Watchlist.js, Admin.js |
| Server Core | server.py |

### 12.3 Documentation Accuracy Verification

| Claim | Verification Method |
|-------|---------------------|
| EOD Pipeline runs at 4:10 PM ET | `/app/backend/server.py` Line 1438 |
| Solvency uses 20% tolerance | `/app/backend/services/pricing_rules.py` Line 104 |
| Delta uses Black-Scholes | `/app/backend/services/greeks_service.py` |
| IV Rank bootstrap at 5 samples | `/app/backend/services/iv_rank_service.py` |
| AI Guard enforces rate limit | `/app/backend/ai_wallet/guard.py` Lines 230-252 |

---

## Appendix A: Quick Reference

### API Endpoint Summary

| Category | Prefix | Key Endpoints |
|----------|--------|---------------|
| Auth | `/api/auth` | login, register, me |
| Screener | `/api/screener` | covered-calls, pmcc, dashboard-opportunities |
| Simulator | `/api/simulator` | trades, rules, analytics |
| Watchlist | `/api/watchlist` | GET, POST, DELETE |
| Admin | `/api/admin` | users, settings, eod-snapshot, support |
| AI Wallet | `/api/ai-wallet` | GET balance, packs, purchase, webhook |
| PayPal | `/api/paypal` | create-checkout, checkout-return, ipn-webhook |

### Environment Variables

| Variable | Purpose | File |
|----------|---------|------|
| MONGO_URL | Database connection | backend/.env |
| DB_NAME | Database name | backend/.env |
| JWT_SECRET | Auth token signing | backend/.env |
| REACT_APP_BACKEND_URL | Frontend API base | frontend/.env |

### Admin Credentials (Default)
- **Email**: admin@premiumhunter.com
- **Password**: admin123
- **Note**: Change immediately in production

---

*Document generated for CCE System v1.0 - December 2025*
