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
- [x] **Refactor server.py - Phase 1 (Jan 11, 2026)** - Extracted 7 routers

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
│   ├── server.py (main API - needs refactoring)
│   ├── requirements.txt
│   └── .env
├── frontend/
│   └── src/
│       ├── pages/
│       │   ├── Dashboard.js
│       │   ├── Screener.js
│       │   ├── PMCC.js
│       │   └── Portfolio.js
│       ├── components/
│       │   └── StockDetailModal.js
│       └── lib/
│           └── api.js
└── memory/
    └── PRD.md
```

---

## Last Updated
January 11, 2026 - Server Refactoring Phase 1 Complete

## Recent Changes (Jan 11, 2026)
### Server.py Refactoring - Phase 1 Complete
- **Line count reduced:** 7333 → 6518 lines (11% reduction, ~815 lines extracted)
- **7 routers extracted to /app/backend/routes/:**
  - `auth.py` - Login, register, /me endpoints
  - `watchlist.py` - Watchlist CRUD operations
  - `news.py` - MarketAux news with rate limiting
  - `chatbot.py` - AI chatbot endpoints
  - `ai.py` - AI analysis and opportunities
  - `subscription.py` - Stripe subscription management
  - `stocks.py` - Stock quotes, indices, details, historical
- **All 32 backend tests passed (100% success rate)**
- **Remaining routers to extract (Phase 2):**
  - `options_router` (~120 lines)
  - `portfolio_router` (~1000 lines)
  - `admin_router` (~800 lines)
  - `screener_router` (~1150 lines)
  - `simulator_router` (~2000+ lines)

### Trade Simulator Phase 4 - Analytics Feedback Loop (PENDING VERIFICATION)
- Performance analytics by delta range, DTE, symbol, and outcome type
- AI-powered recommendations for scanner parameter optimization
- Optimal settings calculator based on winning trade patterns
