# Covered Call Engine - Product Requirements Document

## Original Problem Statement
Build a web-based application named "Covered Call Engine" for options traders. The platform provides AI-assisted Covered Call (CC) and Poor Man's Covered Call (PMCC) screeners, a multi-phased AI Support Ticket System, a role-based Invitation System, Portfolio Tracking, and payment subscriptions.

## Core Data Fetching Rules (NON-NEGOTIABLE)

### Rule 1: Screener Stock Prices
- **Source**: Previous US market close (`previousClose`)
- **Pages**: CC Screener, PMCC Screener, Dashboard Opportunities
- **Implementation**: `fetch_stock_quote()` returns `previousClose` only
- **Verification**: API returns `stock_price_source: "previous_close"`

### Rule 2: Watchlist/Simulator Stock Prices
- **Source**: LIVE intraday prices (`regularMarketPrice`)
- **Pages**: Watchlist, Simulator
- **Implementation**: `fetch_live_stock_quote()` returns current market price
- **Verification**: API returns `price_source: "LIVE_INTRADAY"`, `is_live_price: true`

### Rule 3: Options Chain Data
- **Source**: Fetched LIVE from Yahoo Finance at scan time
- **NEVER**: Cached, stored, reconstructed, or inferred from derived data
- **Implementation**: `fetch_options_chain()` called on every scan request
- **Verification**: API returns `options_chain_source: "yahoo_live"`, `live_data_used: true`

## Tech Stack
- **Frontend**: React with Shadcn/UI components
- **Backend**: FastAPI (Python)
- **Database**: MongoDB
- **Data Sources**: Yahoo Finance (primary), Polygon.io (backup)
- **Scheduler**: APScheduler for automated jobs

---

## Implementation Status

### Completed ✅

#### Data Fetching Rules Implementation (2026-01-28)
- **Rule 1**: Screener uses `previousClose` via `fetch_stock_quote()`
- **Rule 2**: Watchlist/Simulator use `regularMarketPrice` via `fetch_live_stock_quote()`
- **Rule 3**: Options chains fetched LIVE at scan time via `fetch_options_chain()`
- All API responses include source labels for verification

#### Security & Environment (2026-01-28)
- Created `.env.example` files with security warnings
- Added environment variable validation on startup
- Fixed CORS wildcard security issue
- Added database connection health check with connection pool config
- Added NYSE holiday checks to all cron jobs
- Fixed ThreadPoolExecutor memory leak on shutdown

#### Data Integrity Fixes (2026-01-28)
- Fixed intraday price contamination in `data_provider.py`
- Fixed lastPrice fallback bug (SELL legs use BID only)
- Unified bid-ask spread threshold to 10% across all layers
- Improved stale data detection with market-calendar-aware logic

---

## Prioritized Backlog

### P0 - Critical
- [ ] **Fix Manual Filters**: Screener filters (`min_delta`, `min_iv_rank`) not narrowing results correctly
- [ ] **Implement Layer 4 - Scoring**: Pillar-based scoring in `quality_score.py`

### P1 - Important  
- [ ] **Implement Layer 5 - Presentation**: Audit UI-facing endpoints
- [ ] **PayPal Re-integration**: Re-integrate PayPal as payment provider

### P2 - Medium
- [ ] **Fix Inbound Email**: Replies not appearing in support dashboard (recurring - 3+ attempts)
- [ ] **Expand Symbol Universe**: Ingest more ETFs and symbols

### P3 - Low
- [ ] **Frontend Refactor**: Break down large components (`Admin.js`, `Screener.js`, `PMCC.js`)

---

## Key Files Reference

### Data Provider (Data Fetching Rules)
- `/app/backend/services/data_provider.py`:
  - `fetch_stock_quote()` - Returns `previousClose` (Rule 1)
  - `fetch_live_stock_quote()` - Returns `regularMarketPrice` (Rule 2)
  - `fetch_options_chain()` - LIVE options fetch (Rule 3)

### Backend Routes
- `/app/backend/routes/screener_snapshot.py` - CC/PMCC screener (Rules 1 & 3)
- `/app/backend/routes/watchlist.py` - Watchlist (Rule 2)
- `/app/backend/routes/simulator.py` - Simulator (Rule 2)

### Configuration
- `/app/backend/.env.example` - Backend env template
- `/app/frontend/.env.example` - Frontend env template

---

## Test Credentials
- **Admin Email**: admin@premiumhunter.com
- **Password**: admin123

---

## API Response Verification

### Screener (CC/PMCC)
```json
{
  "stock_price_source": "previous_close",
  "options_chain_source": "yahoo_live",
  "live_data_used": true,
  "architecture": "LIVE_OPTIONS_PREVIOUS_CLOSE_STOCK"
}
```

### Watchlist
```json
{
  "price_source": "LIVE_INTRADAY",
  "is_live_price": true,
  "opportunity_source": "yahoo_live"
}
```

---

## Last Updated
2026-01-28 - Data Fetching Rules implementation completed and verified
