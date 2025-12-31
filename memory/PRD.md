# Premium Hunter - Options Trading Platform PRD

## Original Problem Statement
Build a web-based application to identify, analyse, and manage Covered Call and Poor Man's Covered Call strategies, with real-time market data, screening, portfolio tracking, and AI-assisted insights.

## User Choices
- **Market Data**: Polygon.io
- **AI Provider**: OpenAI GPT-5.2
- **Authentication**: JWT-based custom auth
- **News Feed**: Polygon.io news API
- **Admin Panel**: For API key configuration

## Architecture
- **Backend**: FastAPI + MongoDB (Motor async driver)
- **Frontend**: React + Tailwind CSS + Shadcn UI
- **Authentication**: JWT tokens with bcrypt password hashing
- **Data**: Mock data with Polygon.io integration ready

## User Personas
1. **Options Trader**: Primary user looking to find covered call opportunities
2. **PMCC Strategist**: User focused on Poor Man's Covered Call setups
3. **Portfolio Manager**: User tracking multiple positions
4. **Admin**: System administrator managing API keys and settings

## Core Requirements
- [x] Dashboard with market overview
- [x] Covered Call Screener with filters
- [x] PMCC Scanner for LEAPS + short calls
- [x] Portfolio Tracking with P/L calculations
- [x] Watchlist Management
- [x] Admin Panel for API credentials
- [x] AI Analysis Integration (GPT-5.2)
- [x] News Feed
- [x] JWT Authentication
- [x] CSV Import for Portfolio

## What's Been Implemented (December 2024)

### Backend (FastAPI)
- JWT Authentication (register, login, me endpoints)
- Stocks API (quotes, indices, historical data)
- Options API (chains, expirations)
- Screener API (covered calls, PMCC filters)
- Portfolio API (CRUD, CSV import, summary)
- Watchlist API (CRUD operations)
- News API (Polygon integration ready)
- AI API (OpenAI GPT analysis)
- Admin API (settings management)
- Default admin user created on startup

### Frontend (React)
- Landing page with hero, features, CTA
- Login/Register with JWT
- Dashboard with indices, chart, news, opportunities
- Covered Call Screener with filters and export
- PMCC Scanner with AI analysis panel
- Portfolio Management with add/delete/CSV import
- Watchlist with price tracking
- Admin Settings for API keys
- Responsive sidebar navigation

## Prioritized Backlog

### P0 - Critical (Done)
- [x] Core authentication flow
- [x] Dashboard with market data
- [x] Covered call screening
- [x] PMCC scanning
- [x] Portfolio tracking

### P1 - Important
- [ ] Live Polygon.io integration (ready, needs API key)
- [ ] Real-time price updates via WebSocket
- [ ] Options chain visualization
- [ ] Roll management suggestions

### P2 - Nice to Have
- [ ] Email notifications for price alerts
- [ ] Mobile responsive improvements
- [ ] Dark/Light theme toggle
- [ ] Export to Excel format
- [ ] Historical trade analysis

## Technical Details
- MongoDB collections: users, portfolio, watchlist, screener_filters, admin_settings
- Indexes created for performance on startup
- CORS configured for production
- Environment variables properly externalized

## Next Action Items
1. Configure Polygon.io API key in Admin panel for live data
2. Configure OpenAI API key for enhanced AI insights (fallback uses Emergent key)
3. Deploy to production (50 credits/month)
4. Add more stocks to mock data for better testing
5. Implement real-time WebSocket updates
