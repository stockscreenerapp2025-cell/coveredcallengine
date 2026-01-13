# Covered Call Engine - Product Requirements Document

## Original Problem Statement
Build a web-based application named "Covered Call Engine" to identify, analyze, and manage Covered Call and Poor Man's Covered Call (PMCC) strategies.

## Core Features

### 1. Dashboard
- Display new opportunities, market indices, stock data
- Live news feed (MarketAux API with rate limiting)
- Portfolio performance graph (mocked for new users, live for users with data)

### 2. Covered Call Screener
- Powerful screening engine with extensive filters
- Supports stocks and ETFs
- Uses Polygon.io for stock data, Yahoo Finance fallback for ETFs
- **Pre-Computed Scans** (Updated - Jan 13, 2026)
  - Income Guard (Conservative): Stable large-caps, SMA trending, high probability
  - Steady Income (Balanced): Growth stocks, moderate IV, solid fundamentals
  - Premium Hunter (Aggressive): High momentum, high IV, maximum premium yield
  - Results pre-computed nightly at 4:45 PM ET after market close
  - Instant loading from MongoDB (no API delay on click)
  - **Deduplication Logic**:
    - Each symbol appears in only ONE profile (most suitable based on characteristics)
    - Best Weekly + Monthly option per symbol (no duplicate strikes)
    - Profile fit scoring based on ATR%, market cap, EPS, delta, DTE
  - Technical filters: SMA50/200 alignment, RSI, ATR%, price stability
  - Fundamental filters: Market cap, EPS, ROE, D/E, revenue growth
  - Options filters: Delta range, DTE range, premium yield minimum

### 3. PMCC Screener
- Dedicated page for Poor Man's Covered Call strategies
- Identifies suitable LEAPS and short calls
- Refresh Data button to bypass cache

### 4. Stock Detail Modal
- TradingView chart with SMA 50/200
- News and fundamental data
- Technical indicators

### 5. Portfolio Tracker
- IBKR CSV import functionality
- **Manual Trade Entry** (Completed - Jan 11, 2026)
  - Add Covered Calls, PMCC, Stock Only, Option Only, Collar trades
  - Full data display: Symbol, Strategy, Status, DTE, Days in Trade, Shares, Contracts, Entry, Premium, B/E, Current Price, P/L, ROI
  - Trade detail popup with all fields properly populated
  - Delete individual trades
  - Clear all imported data
- AI-powered suggestions
- Dashboard Integration: Strategy Distribution pie chart and P/L bar charts (open/closed positions)

### 6. Authentication & Subscription
- JWT-based authentication
- Stripe integration for subscription management
- 7-day free trial support

### 7. Admin Panel
- User management
- API key configuration (Polygon.io, MarketAux, OpenAI)
- Cache management
- **Pre-Computed Scans Management** (NEW - Jan 13, 2026)
  - Trigger manual scans for any risk profile
  - View scan status and results count
  - Automatic nightly scheduler at 4:45 PM ET

### 8. Legal & Contact
- Terms & Conditions page
- Privacy Policy page
- Contact Us form

---

## Implementation Status

### ✅ Completed
- [x] Dashboard with opportunities display
- [x] Covered Call Screener with filters
- [x] PMCC Screener with LEAPS selection
- [x] Stock Detail Modal with TradingView
- [x] Portfolio Tracker - IBKR CSV Import
- [x] Portfolio Tracker - Manual Trade Entry (Jan 2026)
- [x] Authentication (JWT)
- [x] Stripe Integration
- [x] Admin Panel - Basic
- [x] News API Integration with rate limiting
- [x] ETF data via Yahoo Finance fallback
- [x] AI Chatbot on homepage
- [x] Trade Simulator Phase 1 - Core MVP (Jan 2026)
- [x] Trade Simulator Phase 2 - Automation & Greeks (Jan 2026)
- [x] Trade Simulator Phase 3 - Rule-based Trade Management (Jan 11, 2026)
  - Rule engine with conditions (premium_capture_pct, delta, loss_pct, dte_remaining, etc.)
  - 7 pre-built rule templates (Roll at 80% Premium, Delta Threshold, Stop Loss, etc.)
  - Rule actions: roll (with new_dte/strike_adjustment), close, alert
  - Action logs with timestamps for all rule-driven actions
  - PMCC Income Tracker (cumulative income vs LEAPS decay)
  - Automated rule evaluation in daily scheduler
- [x] Trade Simulator Phase 4 - Analytics Feedback Loop (Jan 11, 2026)
  - Performance analytics by delta range, DTE, symbol, and outcome type
  - AI-powered recommendations for scanner parameter optimization
  - Optimal settings calculator based on winning trade patterns
  - Scanner profile save/load functionality
  - Scanner comparison to identify best parameter combinations

### 🔄 In Progress
- [ ] Watchlist Functionality (P1)

### 🔴 Blocked
- [ ] Stripe Webhook Configuration - Requires user action
- [ ] Resend Domain Verification - Requires user action
- [ ] IBKR CSV Parser Validation - Waiting for user's second account CSV

### 📋 Backlog
- [ ] Support System - AI Learning from admin edits (P1)
- [ ] Refactor Admin.js (2000+ lines) into sub-components (P2)
- [ ] Refactor Screener.js and PMCC.js into smaller components (P2)
- [ ] Support Ticket System - Phase 3: Advanced AI Resolution (P2)
- [ ] Admin Panel - Content Manager (P2)
- [ ] Admin Panel - Roles & Permissions (P3)
- [ ] Generic CSV Import with field mapping (P3)

### ✅ Completed (Jan 13, 2026) - New Features
- [x] **PMCC LEAPS Minimum 12 Months DTE**
  - Updated PMCC_PROFILES to require `long_dte_min: 365` for all risk profiles (conservative, balanced, aggressive)
  - All pre-computed PMCC scans now only show LEAPS with 12+ months expiration
  - True LEAPS options for better capital efficiency and leverage
- [x] **Dashboard Top 10 CC Strike Format**
  - Strike column now shows date + strike + type format: "16JAN26 $46 C"
  - Added `formatOptionContract()` function to Dashboard.js
  - Better visibility of contract details at a glance
- [x] **Portfolio IBKR Button Cleanup**
  - Removed "Opens in new window" helper text from IBKR account button
  - Cleaner UI in the Portfolio page
- [x] **AI Sentiment Analysis for News**
  - Added "Analyze News" button in Stock Detail Modal News tab
  - Uses GPT-5.2 via Emergent integrations for sentiment analysis
  - Returns: Overall Sentiment (Bullish/Bearish/Neutral), Sentiment Score (0-100), Summary
  - Per-article sentiment badges: Positive/Neutral/Negative with confidence levels
  - New endpoint: `POST /api/news/analyze-sentiment`
- [x] **Analyst Ratings in Fundamentals Tab**
  - Added Analyst Ratings card in Stock Detail Modal Fundamentals tab
  - Shows: Rating badge (Strong Buy/Buy/Hold/Sell), Analyst count, Target Price
  - Price Range (low - high), Upside percentage calculation
  - Data from Yahoo Finance via yfinance library
  - Added `_fetch_analyst_ratings()` function in stocks.py
  - Added "Analyst" column to Dashboard Top 10 CC table

### ✅ Completed (Jan 13, 2026) - PMCC Bug Fixes
- [x] **PMCC Pre-Computed Scans Data Mapping Fix**
  - Added `normalizeOpp()` helper function to map backend `long_*` fields to frontend `leaps_*` fields
  - Backend sends: long_dte, long_strike, long_premium, long_delta
  - Frontend displays: LEAPS (Buy) column with formatted contract info
  - Simulate modal now uses normalized data for both custom and pre-computed scans
- [x] **PMCC Default Screener Deduplication**
  - Added client-side deduplication in `fetchOpportunities()` function
  - Keeps highest score per symbol, removes duplicates
- [x] **PMCC Page Layout Reorganization**
  - New order: Header → Compact Strategy Explanation → Quick Scans → Filters + Results
  - Removed standalone Strategy Tips cards at bottom
  - Integrated key strategy info into compact 2-column card at top
- [x] **Code Quality Improvements**
  - Moved `SortHeader` component outside main `PMCC` component (React lint fix)
  - Updated all SortHeader usages to pass required props

### ✅ Completed (Jan 13, 2026) - Pre-Computed Scans
- [x] **Pre-Computed Scans for Covered Calls**
  - Income Guard (Conservative): 32 opportunities
  - Steady Income (Balanced): 50 opportunities
  - Premium Hunter (Aggressive): 50 opportunities
  - Backend service: `/app/backend/services/precomputed_scans.py`
  - API routes: `/app/backend/routes/precomputed_scans.py`
  - Nightly scheduler at 4:45 PM ET (weekdays)
  - Technical filters: SMA alignment, RSI, ATR%, price stability
  - Fundamental filters: Market cap, EPS, ROE, D/E, revenue growth
  - Options filters: Delta range, DTE range, premium yield
  - MongoDB collection: `precomputed_scans`
  - Frontend: Quick Scans section with 3 scan buttons

### ✅ Completed (Jan 12, 2026)
- [x] **Full RBAC Implementation**
  - Admin, Tester, Support Staff roles
  - Role-based navigation and access control
  - Invitation system fixed
- [x] **IMAP Email Polling System**
  - Automated email import from Hostinger mailbox
  - AI auto-draft for customer replies
- [x] **Support Ticket System - Phase 1: Human-in-the-Loop**
  - Unified ticket intake via contact form (email ingestion planned for Phase 2)
  - AI ticket classification using GPT-5.2 (category, sentiment, priority, confidence score)
  - AI-generated draft responses with professional tone
  - Admin dashboard in Admin Panel → Support tab
  - Ticket management: view, filter, search, status updates
  - Human-in-the-loop workflow: Admin reviews/edits AI draft before sending
  - Auto-acknowledgment emails via Resend
  - Knowledge Base management: Add/Edit/Delete FAQ articles for AI reference
  - Sequential ticket numbering (CCE-0001, CCE-0002, etc.)
  - Full audit logging for admin actions

### ✅ Completed Refactoring (Jan 11, 2026)
- [x] **server.py Refactoring - Phase 4 Complete**
  - Extracted ALL 12 routers from monolithic server.py
  - server.py reduced from 4504 lines to 1326 lines (71% reduction)
  - Route modules total: 5294 lines across 12 well-organized files
  - All endpoints verified working after extraction

---

## Tech Stack
- **Frontend:** React, Tailwind CSS, Shadcn/UI
- **Backend:** FastAPI (Python)
- **Database:** MongoDB
- **APIs:** Polygon.io, Yahoo Finance (technical + fundamentals), MarketAux, Stripe, Resend
- **Charting:** TradingView (iframe), Recharts
- **Scheduler:** APScheduler (nightly pre-computed scans)

---

## Key API Endpoints

### Portfolio
- `GET /api/portfolio/ibkr/trades` - Get all trades
- `POST /api/portfolio/manual-trade` - Add manual trade
- `DELETE /api/portfolio/manual-trade/{id}` - Delete manual trade
- `DELETE /api/portfolio/ibkr/clear` - Clear all imported data

### Screeners
- `GET /api/screener/covered-calls` - Screener data
- `GET /api/screener/pmcc` - PMCC data

### Support (New - Jan 12, 2026)
- `POST /api/support/tickets` - Create ticket from contact form (public)
- `GET /api/support/admin/tickets` - Get tickets list with filters (admin)
- `GET /api/support/admin/tickets/{id}` - Get ticket detail with AI draft (admin)
- `PUT /api/support/admin/tickets/{id}` - Update ticket status/priority (admin)
- `POST /api/support/admin/tickets/{id}/reply` - Send admin reply (admin)
- `POST /api/support/admin/tickets/{id}/approve-draft` - Approve AI draft and send (admin)
- `POST /api/support/admin/tickets/{id}/regenerate-draft` - Regenerate AI draft (admin)
- `POST /api/support/admin/tickets/{id}/escalate` - Escalate ticket (admin)
- `POST /api/support/admin/tickets/{id}/resolve` - Mark resolved (admin)
- `GET /api/support/admin/stats` - Get support statistics (admin)
- `GET /api/support/admin/kb` - Get knowledge base articles (admin)
- `POST /api/support/admin/kb` - Create KB article (admin)
- `PUT /api/support/admin/kb/{id}` - Update KB article (admin)
- `DELETE /api/support/admin/kb/{id}` - Delete KB article (admin)

### Admin
- `POST /api/admin/clear-cache` - Clear server cache

---

## File Structure
```
/app/
├── backend/
│   ├── server.py (main API - 1326 lines, scheduler + core infrastructure)
│   ├── database.py (MongoDB connection with pooling)
│   ├── requirements.txt
│   ├── .env
│   ├── routes/                    # Fully modular routes (6000+ lines total)
│   │   ├── __init__.py
│   │   ├── auth.py               (101 lines)
│   │   ├── watchlist.py          (64 lines)
│   │   ├── news.py               (221 lines)
│   │   ├── chatbot.py            (64 lines)
│   │   ├── ai.py                 (134 lines)
│   │   ├── subscription.py       (144 lines)
│   │   ├── stocks.py             (297 lines)
│   │   ├── options.py            (171 lines)
│   │   ├── admin.py              (874 lines)
│   │   ├── portfolio.py          (887 lines)
│   │   ├── screener.py           (705 lines)
│   │   ├── simulator.py          (1629 lines)
│   │   └── support.py            (616 lines) - NEW Jan 12, 2026
│   ├── services/
│   │   ├── cache.py
│   │   ├── chatbot_service.py
│   │   ├── data_provider.py      (centralized market data service)
│   │   ├── email_service.py
│   │   ├── email_automation.py
│   │   ├── ibkr_parser.py
│   │   ├── stripe_webhook.py
│   │   └── support_service.py    (877 lines) - NEW Jan 12, 2026
│   ├── models/
│   │   ├── schemas.py (Pydantic models)
│   │   └── support.py (237 lines) - NEW Jan 12, 2026
│   └── utils/
│       └── auth.py (JWT utilities)
├── frontend/
│   └── src/
│       ├── pages/
│       │   ├── Dashboard.js
│       │   ├── Screener.js
│       │   ├── PMCC.js
│       │   ├── Portfolio.js
│       │   ├── Simulator.js (5 tabs: Active, Closed, Rules, Logs, Analytics)
│       │   └── Admin.js (7 tabs: Dashboard, Users, Support, Email, Billing, Integrations, API Keys)
│       ├── components/
│       │   ├── StockDetailModal.js
│       │   └── AdminSupport.jsx (986 lines) - NEW Jan 12, 2026
│       └── lib/
│           └── api.js
├── tests/
│   └── test_refactored_routes.py
└── memory/
    └── PRD.md
```

---

## Last Updated
January 12, 2026 - Centralized Data Sourcing Implementation

## Recent Changes

### Centralized Data Sourcing Architecture (Jan 12, 2026) ✅
**Implemented a clean, consistent data sourcing strategy:**

**Data Sourcing Rules (PERMANENT - DO NOT CHANGE):**
- **OPTIONS DATA**: Polygon/Massive ONLY (paid subscription)
- **STOCK DATA**: Polygon/Massive primary, Yahoo fallback (until subscription upgrade)
- **Future-proof**: Set `USE_POLYGON_FOR_STOCKS = True` in `data_provider.py` when upgrading

**New File Created:**
- `/app/backend/services/data_provider.py` - Centralized data sourcing service
  - `fetch_options_chain()` - Polygon only for options
  - `fetch_stock_quote()` - Polygon primary, Yahoo fallback
  - `fetch_historical_prices()` - Polygon primary, Yahoo fallback
  - `is_market_closed()` - Market hours detection
  - `get_data_source_status()` - Admin diagnostic tool

**Updated Screeners:**
- `/app/backend/routes/screener.py` - All three screeners now use centralized data provider
  - Covered Calls screener: Polygon for options, hybrid for stocks
  - PMCC screener: Polygon for options, hybrid for stocks
  - Dashboard opportunities: Polygon for options, hybrid for stocks
  - All responses now include `data_source: "polygon"` field

**Result:** Consistent data sourcing across all screeners. Options always from Polygon, stock prices with graceful fallback.

### Dashboard Top 10 Covered Calls Enhancement (Jan 12, 2026) ✅
**Issues Fixed:**
1. Strike column was showing full option contract format instead of just strike price
2. IV, 6M, 12M columns were showing "%" with no values
3. Only Monthly opportunities were displayed

**Changes Made:**
- **Backend (`screener.py`):**
  - Updated `/dashboard-opportunities` to return Top 5 Weekly + Top 5 Monthly (was only Monthly before)
  - Added `min_dte=1` query for Weekly options (1-7 DTE) and `min_dte=8` for Monthly (8-45 DTE)
  - Added proper IV data extraction from Yahoo Finance options data
  - Added `expiry_type`, `moneyness`, `strike_pct` fields to response
  - Changed cache key to `dashboard_opportunities_v3`
  
- **Frontend (`Dashboard.js`):**
  - Updated subtitle to "Top 5 Weekly + Top 5 Monthly"
  - Strike column now shows just "$XX" with ATM/OTM badge (not full option contract)
  - Removed 6M/12M trend columns (requires separate historical data API)
  - Fixed IV display to show actual percentage values

**Result:** Dashboard now displays 5 Weekly + 5 Monthly opportunities with proper IV values (40-70%) and clean Strike prices.

### PMCC Screener Enhancement (Jan 12, 2026) ✅
**Issue 1:** PMCC screener was returning 0 results due to LEAPS detection bug.
**Fix 1:** Changed LEAPS detection threshold from `min_dte >= 300` to `min_dte >= 150` in `server.py` line 633.

**Issue 2:** After fix, PMCC screener only returned 3-4 results (one per symbol).
**Root Cause:** The screener only generated 1 PMCC opportunity per symbol by selecting the single "best" LEAPS and "best" short call.

**Fix 2 (screener.py):**
- Expanded symbol list from 22 to 47 stocks across Tech, Financials, Consumer, Healthcare, Energy, Fintech, Airlines, and High-Volatility sectors
- Changed logic to generate **multiple combinations per symbol** (up to 3 LEAPS × 3 short calls = 9 combos per symbol)
- Improved scoring algorithm to account for capital efficiency
- Capped results at top 100 opportunities

**Result:** PMCC screener now returns **100 opportunities** with ROIs ranging from 7% to 14% per cycle and 100%+ annualized returns.

### Server.py Refactoring - Phase 4 Complete (Jan 11, 2026) ✅
**Goal:** Build scalable architecture for 1000+ concurrent users

**Results:**
- **Line count reduced:** 7333 → 4504 lines (38.6% reduction, 2829 lines extracted)
- **11 routers extracted to /app/backend/routes/:**
  1. `auth.py` (101 lines) - Login, register, /me endpoints
  2. `watchlist.py` (64 lines) - Watchlist CRUD operations
  3. `news.py` (221 lines) - MarketAux news with rate limiting
  4. `chatbot.py` (64 lines) - AI chatbot endpoints
  5. `ai.py` (134 lines) - AI analysis and opportunities
  6. `subscription.py` (144 lines) - Stripe subscription management
  7. `stocks.py` (297 lines) - Stock quotes, indices, details, historical
  8. `options.py` (171 lines) - Options chain, expirations
  9. `admin.py` (874 lines) - Full admin panel with user management, email automation
  10. `portfolio.py` (887 lines) - Portfolio management, IBKR import, manual trades

**Scalability Improvements:**
- Proper async/await patterns throughout
- Efficient database queries with projections (exclude _id, sensitive fields)
- Pagination on all list endpoints (admin/users, audit-logs, trades, etc.)
- Connection pooling for HTTP requests (httpx.Timeout config)
- Lazy imports to avoid circular dependencies
- Stateless API design
- Normalized field handling for frontend compatibility

**Remaining in server.py (Phase 4):**
- `screener_router` (~1200 lines) - Complex business logic with caching
- `simulator_router` (~1900 lines) - Rule engine, analytics, scheduler
- Core infrastructure: Cache helpers, models, auth utilities

**Testing:** All 10 API groups verified working (Auth, Stocks, Options, Screener, Portfolio, Admin, Simulator, News, Watchlist, Subscription)

### Invitation System & Security Fixes (Jan 12, 2026) ✅
**Three critical bugs fixed:**

1. **Security Vulnerability - Demo Credentials Removed**
   - Removed hardcoded demo credentials from Login.js that were visible on the production login page
   - File: `/app/frontend/src/pages/Login.js` - Removed lines 127-132

2. **Invitation URL Environment Logic**
   - Test environment invitations now correctly use: `https://premiumcall.preview.emergentagent.com`
   - Production environment invitations use: `https://coveredcallengine.com`
   - File: `/app/backend/routes/invitations.py` - Lines 36-39

3. **AcceptInvitation Page Working**
   - Page renders correctly with invitation details, role badge, and password form
   - Complete account creation flow verified working
   - File: `/app/frontend/src/pages/AcceptInvitation.js`

### Role-Based Access Control (RBAC) Implementation (Jan 12, 2026) ✅
**Complete role-based security system:**

**Backend Changes:**
- Updated `/app/backend/models/schemas.py` - UserResponse now includes role, is_support_staff, is_tester, permissions
- Updated `/app/backend/routes/auth.py` - Login and /me endpoints return full role information
- JWT tokens now include role information for backend authorization

**Frontend Changes:**
- Updated `/app/frontend/src/contexts/AuthContext.js` - Added role helpers: isAdmin, isSupportStaff, isTester, hasSupportAccess, hasPermission()
- Updated `/app/frontend/src/App.js` - Added SupportRoute wrapper, imported SupportPanel
- Updated `/app/frontend/src/components/Layout.js` - Dynamic navigation based on user role
- Updated `/app/frontend/src/pages/Login.js` - Role-based redirect after login
- Updated `/app/frontend/src/pages/Dashboard.js` - Redirect support-only staff to /support
- Created `/app/frontend/src/pages/SupportPanel.js` - Dedicated support panel for support staff

**Role Access Matrix:**
| Role | Navigation | Access | Redirect |
|------|-----------|--------|----------|
| Admin | Full + Admin | Everything | /dashboard |
| Tester | Full (no Admin) | App features | /dashboard |
| Support Staff | Support only | Support Panel | /support |

### IMAP Email Sync Implementation (Jan 12, 2026) ✅
**Automated email reply import from Hostinger mailbox:**

**Features:**
- Connects to Hostinger IMAP (`imap.hostinger.com:993`)
- Scans for unread emails and matches to tickets by ticket number in subject (e.g., `[CCE-0014]`)
- Automatically adds replies to existing tickets
- Creates new tickets for emails without ticket references
- Marks processed emails as read
- Runs automatically every 6 hours (4 times daily)
- Manual "Sync Now" button in Admin panel

**Files Created/Modified:**
- `/app/backend/services/imap_service.py` - IMAP connection and email processing
- `/app/backend/routes/admin.py` - Added IMAP settings endpoints
- `/app/backend/server.py` - Added scheduler job for IMAP sync
- `/app/frontend/src/pages/Admin.js` - Added "Email Sync" tab with settings, history, and sync controls

**Key Endpoints:**
- `GET /api/admin/imap/settings` - Get IMAP settings (password masked)
- `POST /api/admin/imap/settings` - Save IMAP settings
- `POST /api/admin/imap/test-connection` - Test IMAP connection
- `POST /api/admin/imap/sync-now` - Trigger manual sync
- `GET /api/admin/imap/sync-history` - Get sync history
- `GET /api/admin/imap/status` - Get IMAP status

### Invitation System Architecture (Jan 12, 2026) ✅
**Key Files:**
- `/app/backend/routes/invitations.py` - Invitation CRUD, email sending, token verification
- `/app/frontend/src/pages/AcceptInvitation.js` - Public invitation acceptance page
- `/app/frontend/src/pages/Admin.js` - Admin UI for invitations

**Key Endpoints:**
- `POST /api/invitations/send` - Send invitation (admin only)
- `GET /api/invitations/list` - List all invitations (admin only)
- `DELETE /api/invitations/{id}` - Delete/revoke invitation (admin only)
- `POST /api/invitations/{id}/resend` - Resend invitation email (admin only)
- `GET /api/invitations/verify/{token}` - Verify invitation token (public)
- `POST /api/invitations/accept/{token}` - Accept invitation and create account (public)

**Roles Supported:**
- `support_staff` - Access to Support Ticket System only
- `tester` - Access to main application features (Beta Tester)
