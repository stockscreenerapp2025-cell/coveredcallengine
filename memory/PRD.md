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
- [ ] Refactor server.py into modular structure (P3)

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
January 11, 2026 - Trade Simulator Phase 1 MVP Complete

## Recent Changes (Jan 11, 2026)
### Trade Simulator (NEW Feature)
- Added "Simulator" page to sidebar navigation (under Portfolio)
- Added "SIMULATE" button on Screener page results table
- Added "SIMULATE" button on PMCC page results table
- Created Simulator dashboard with:
  - Summary cards: Total P/L, Win Rate, Active Trades, Capital Deployed, Avg Return, Assignment Rate
  - Strategy Distribution pie chart
  - P/L by Strategy bar chart
  - Trades table with status/strategy filters
  - Trade detail dialog
- Backend endpoints:
  - POST /api/simulator/trade - Add trade from screener
  - GET /api/simulator/trades - List trades with pagination/filters
  - GET /api/simulator/summary - Portfolio-level metrics
  - POST /api/simulator/update-prices - EOD price updates
  - DELETE /api/simulator/trades/{id} - Delete trade
  - POST /api/simulator/trades/{id}/close - Close trade manually
- Features:
  - Immutable entry snapshot (no repainting)
  - Position sizing (editable contracts)
  - Expiry handling (ITM=assigned, OTM=expired)
  - Daily price updates via Yahoo Finance
  - Capital tracking per trade and portfolio-level
- Testing: 12/12 backend+frontend tests passing (100% success rate)
