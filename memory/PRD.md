# Covered Call Engine - Options Trading Platform PRD

## Original Problem Statement
Build a web-based application to identify, analyse, and manage Covered Call and Poor Man's Covered Call strategies, with real-time market data, screening, portfolio tracking, and AI-assisted insights.

## User Choices
- **Market Data**: Polygon.io
- **AI Provider**: OpenAI GPT-5.2
- **Authentication**: JWT-based custom auth
- **News Feed**: Polygon.io news API
- **Admin Panel**: For API key configuration
- **Deployment Domain**: coveredcallengine.com

## Architecture
- **Backend**: FastAPI + MongoDB (Motor async driver)
- **Frontend**: React + Tailwind CSS + Shadcn UI
- **Authentication**: JWT tokens with bcrypt password hashing
- **Data**: Polygon.io API with parallel asyncio.gather optimization

## User Personas
1. **Options Trader**: Primary user looking to find covered call opportunities
2. **PMCC Strategist**: User focused on Poor Man's Covered Call setups
3. **Portfolio Manager**: User tracking multiple positions
4. **Admin**: System administrator managing API keys and settings

## Core Requirements (All Implemented ✅)
- [x] Dashboard with market overview
- [x] Comprehensive Covered Call Screener with advanced filters
- [x] PMCC Scanner for LEAPS + short calls
- [x] Portfolio Tracking with P/L calculations
- [x] Watchlist Management
- [x] Admin Panel for API credentials
- [x] AI Analysis Integration (GPT-5.2)
- [x] News Feed
- [x] JWT Authentication
- [x] CSV Import for Portfolio
- [x] Terms & Conditions checkbox on registration

## Recent Updates (January 2026)
### Manual Trade Entry Form (New)
- Added "Add Trade" button to Portfolio header
- Full manual trade entry form with support for:
  - Covered Calls (Stock + Short Call)
  - PMCC (LEAPS + Short Call)
  - Stock-only positions
  - Individual options
- Backend API endpoints: POST/PUT/DELETE `/api/portfolio/manual-trade`
- Close trade endpoint with P/L calculation

### Screener/PMCC Performance Fix
- Implemented parallel API requests using `asyncio.gather` in `fetch_options_chain_polygon`
- Added semaphore-based rate limiting (15 concurrent requests)
- Expanded strike price filtering for short options (95-150% of stock price)
- Added proper ATM/OTM filtering for covered calls (97-115% of stock price)
- Results improved from 2 PMCC opportunities to 40+ opportunities
- Added "Refresh Data" button to bypass cache and fetch fresh market data
- Added `/api/screener/clear-cache` endpoint for cache management

### ETF Options Support (New)
- Integrated Yahoo Finance (`yfinance`) as data source for ETF options
- Added ETF symbols: SPY, QQQ, IWM, DIA, XLF, XLE, XLK and more
- ETFs are now included in Screener results regardless of price filter
- Yahoo Finance provides real-time options data for ETFs
- Security Type filter (Stocks/ETFs/Index) now works correctly

### MarketAux News Rate Limiting & Filtering
- Implemented 100 requests/day rate limit for free tier
- Added `/api/news/rate-limit` endpoint to check usage status
- Filtered news to only show relevant stock/options trading content
- News now includes ticker symbols and excludes irrelevant content (concerts, entertainment, etc.)
- Keywords filter for options-related terms: volatility, earnings, dividend, Fed, etc.

### Dashboard Portfolio Mockup
- Enhanced mockup section with colorful sample charts
- Sample Strategy Distribution pie chart (Covered Calls, PMCC, Stocks)
- Sample Realized P/L bar chart by position
- Clear "Sample Data Preview" banner explaining import process
- Call-to-action button to import IBKR data

### Portfolio Onboarding Page
- Three-option onboarding: IBKR Import, New Account, Manual Entry (coming soon)
- Step-by-step IBKR export instructions
- Clear "bonus feature" messaging to manage expectations
- Affiliate link placeholder for IBKR account opening (admin configurable)

### Screener Filter UI Fix
- All filter fields now show as blank/empty placeholders by default
- Removed pre-populated default values (no more 10-100, 1-45, etc.)
- Filters only apply when user explicitly sets values

### Terms & Conditions
- Added mandatory checkbox on registration page
- Links to Terms & Conditions and Privacy Policy pages
- Validation prevents registration without acceptance

## Screener Filters (All Implemented ✅)

### Days to Expiration
- [x] DTE Range (min/max)
- [x] Weekly Expirations Only
- [x] Monthly Expirations Only

### Stock Filters
- [x] Stock Price Range
- [x] Security Type (Stock/ETF/Index)

### Options Filters
- [x] Option Volume
- [x] Open Interest
- [x] Moneyness (ITM/ATM/OTM)

### Greeks
- [x] Delta Range
- [x] Theta

### Probability
- [x] Probability of Assignment
- [x] Probability of NOT Assignment

### Technicals
- [x] Price Above SMA 50
- [x] Price Above SMA 200
- [x] RSI Range
- [x] MACD Signal (Bullish/Bearish)
- [x] Min ADX (Trend Strength)
- [x] Signal Strength (Bullish/Bearish/Neutral)

### Fundamentals
- [x] Analyst Coverage
- [x] Buy/Strong Buy Ratings
- [x] P/E Ratio Range
- [x] ROE

### ROI
- [x] Min ROI %
- [x] Min Annualized ROI

## What's Been Implemented (December 2024)

### Backend (FastAPI)
- JWT Authentication (register, login, me endpoints)
- Stocks API (quotes, indices, historical data)
- Options API (chains, expirations)
- Enhanced Screener API with all filters
- Portfolio API (CRUD, CSV import, summary)
- Watchlist API (CRUD operations)
- News API (Polygon integration ready)
- AI API (OpenAI GPT analysis)
- Admin API (settings management)
- Default admin user created on startup

### Frontend (React)
- Landing page with emerald green branding
- Login/Register with JWT
- Dashboard with indices, chart, news, opportunities
- **Comprehensive Covered Call Screener** with accordion filters
- PMCC Scanner with AI analysis panel
- Portfolio Management with add/delete/CSV import
- Watchlist with price tracking
- Admin Settings for API keys
- Responsive sidebar navigation

## Branding
- **App Name**: Covered Call Engine
- **Primary Color**: Emerald (#10b981)
- **Theme**: Dark professional trading terminal

## Deployment
- **Target Domain**: coveredcallengine.com
- **Status**: Ready for deployment
- **Cost**: 50 credits/month

## Next Action Items
1. Configure Stripe webhook URL in Stripe dashboard: `https://covercall.preview.emergentagent.com/api/webhooks/stripe`
2. Verify domain in Resend for email delivery
3. Validate portfolio parser with user's second IBKR account CSV
4. Implement Watchlist functionality

## Pending User Actions
- Stripe webhook configuration (required for subscription management)
- Resend domain verification (required for email notifications)

## Future Tasks
- Admin Panel - Support Ticket System
- Admin Panel - Content & Announcement Manager
- Admin Panel - Roles & Permissions and Audit Logs
