# Covered Call Engine - Product Requirements Document

## Original Problem Statement
Build a web-based application named "Covered Call Engine" for options traders. The platform provides AI-assisted Covered Call (CC) and Poor Man's Covered Call (PMCC) screeners, a multi-phased AI Support Ticket System, a role-based Invitation System, Portfolio Tracking, and payment subscriptions.

## Core Architecture
The application follows a strict layered architecture (CCE Master Architecture Spec):
- **Layer 1**: Data Ingestion - EOD Price Contract (ADR-001), stock_close_price = previous NYSE close ONLY
- **Layer 2**: Validation & Structure - Chain validation, BID/ASK enforcement, 10% max spread
- **Layer 3**: Filter & Select - Screener filtering with manual filters
- **Layer 4**: Scoring & Ranking (pending)
- **Layer 5**: Presentation (pending)

## Tech Stack
- **Frontend**: React with Shadcn/UI components
- **Backend**: FastAPI (Python)
- **Database**: MongoDB
- **Data Sources**: Yahoo Finance (primary), Polygon.io (backup)
- **Scheduler**: APScheduler for automated jobs

---

## Implementation Status

### Completed ✅

#### Security & Environment (2026-01-28)
- **P0-1**: Created `.env.example` files for both backend and frontend with security warnings
- **P0-2**: Fixed intraday price contamination - `data_provider.py` now uses `previousClose` ONLY
- **P0-3**: Added environment variable validation on startup in `database.py` with fail-fast behavior
- **P1-2**: Fixed lastPrice fallback bug - SELL legs now use BID only, no lastPrice fallback
- **P1-3**: Added database connection health check with connection pool configuration
- **P1-4**: Added NYSE holiday checks to all cron jobs (EOD ingestion, price update, precomputed scans)
- **P2-1**: Unified bid-ask spread threshold to 10% across Layer 1 and Layer 2
- **P2-2**: Fixed ThreadPoolExecutor cleanup - proper shutdown on app restart
- **P2-3**: Improved stale data detection with market-calendar-aware logic (dynamic max age)
- **P2-4**: Fixed CORS wildcard security - now uses explicit allowed origins

#### EOD Price Contract (ADR-001) - Completed
- New MongoDB collections: `eod_market_close`, `eod_options_chain`
- Immutable schema with `is_final` flag
- Idempotent ingestion service
- Automated daily ingestion at 4:05 PM ET
- Screener routes refactored to use EOD data exclusively

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

### P4 - Backlog
- [ ] **Deprecate Legacy Snapshots**: Remove old `stock_snapshots` and `option_chain_snapshots` collections

---

## Key Files Reference

### Backend Services
- `/app/backend/services/eod_ingestion_service.py` - EOD data ingestion
- `/app/backend/services/snapshot_service.py` - Legacy snapshot service (to be deprecated)
- `/app/backend/services/data_provider.py` - Yahoo Finance / Polygon integration
- `/app/backend/services/chain_validator.py` - Layer 2 validation

### Backend Routes
- `/app/backend/routes/eod.py` - EOD API endpoints
- `/app/backend/routes/screener_snapshot.py` - CC/PMCC screener
- `/app/backend/routes/watchlist.py` - Watchlist management

### Configuration
- `/app/backend/.env.example` - Backend env template
- `/app/frontend/.env.example` - Frontend env template
- `/app/backend/docs/ADR-001-EOD-PRICE-CONTRACT.md` - Architecture decision record

---

## Test Credentials
- **Admin Email**: admin@premiumhunter.com
- **Password**: admin123

---

## Last Updated
2026-01-28 - Security & Data Integrity improvements completed
