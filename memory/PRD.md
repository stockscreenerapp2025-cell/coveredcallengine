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
- [ ] Admin Panel - Support Ticket System (P2)
- [ ] Admin Panel - Content Manager (P2)
- [ ] Admin Panel - Roles & Permissions (P3)
- [ ] Generic CSV Import with field mapping (P3)

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
- **APIs:** Polygon.io, Yahoo Finance, MarketAux, Stripe, Resend
- **Charting:** TradingView (iframe), Recharts

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
│   ├── routes/                    # Fully modular routes (5294 lines total)
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
│   │   ├── screener.py           (705 lines) - NEW
│   │   └── simulator.py          (1629 lines) - NEW
│   ├── services/
│   │   ├── cache.py
│   │   ├── chatbot_service.py
│   │   ├── email_service.py
│   │   ├── email_automation.py
│   │   └── ibkr_parser.py
│   ├── models/
│   │   └── schemas.py (Pydantic models)
│   └── utils/
│       └── auth.py (JWT utilities)
├── frontend/
│   └── src/
│       ├── pages/
│       │   ├── Dashboard.js
│       │   ├── Screener.js
│       │   ├── PMCC.js
│       │   ├── Portfolio.js
│       │   └── Simulator.js (5 tabs: Active, Closed, Rules, Logs, Analytics)
│       ├── components/
│       │   └── StockDetailModal.js
│       └── lib/
│           └── api.js
├── tests/
│   └── test_refactored_routes.py
└── memory/
    └── PRD.md
```

---

## Last Updated
January 11, 2026 - Server Refactoring Phase 3 Complete (Scalability Focus)

## Recent Changes (Jan 11, 2026)
### Server.py Refactoring - Phase 3 Complete ✅
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
