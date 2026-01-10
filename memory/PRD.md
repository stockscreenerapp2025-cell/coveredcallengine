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
### Screener/PMCC Performance Fix
- Implemented parallel API requests using `asyncio.gather` in `fetch_options_chain_polygon`
- Added semaphore-based rate limiting (15 concurrent requests)
- Expanded strike price filtering for short options (95-150% of stock price)
- Added proper ATM/OTM filtering for covered calls (97-115% of stock price)
- Results improved from 2 PMCC opportunities to 40+ opportunities
- Added "Refresh Data" button to bypass cache and fetch fresh market data
- Added `/api/screener/clear-cache` endpoint for cache management

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
1. Deploy to Emergent (click Deploy button)
2. Link custom domain: coveredcallengine.com
3. Configure DNS at domain registrar
4. Add Polygon.io API key in Admin settings for live data
5. Optional: Add OpenAI API key for enhanced AI (Emergent key works as fallback)
