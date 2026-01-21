# Covered Call Engine - Product Requirements Document

## Last Updated: January 21, 2026

## Overview
Web-based application for screening Covered Call (CC) and Poor Man's Covered Call (PMCC) options strategies with AI-assisted scoring.

## Current Status: PHASE 8 COMPLETE
All major screener rebuild phases (4-8) are now complete.

## Phased Rebuild Summary

| Phase | Name | Status | Date |
|-------|------|--------|------|
| 4 | CC Engine Rebuild | ✅ Complete | Jan 21, 2026 |
| 5 | PMCC Engine Rebuild | ✅ Complete | Jan 21, 2026 |
| 6 | Market Bias Order Fix | ✅ Complete | Jan 21, 2026 |
| 7 | Quality Score Rewrite | ✅ Complete | Jan 21, 2026 |
| 8 | Storage, Logging & Admin | ✅ Complete | Jan 21, 2026 |

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

### ✅ Completed (Jan 21, 2026) - PHASE 4: Covered Call Engine Rebuild
- [x] **System Scan Filters (Custom Scan ONLY)**
  - Price range: $30-$90 (strict for Custom Scan)
  - Average Volume: ≥1M
  - Market Cap: ≥$5B
  - Earnings: No earnings within 7 days
  - DTE: Weekly 7-14, Monthly 21-45
  - OTM: 2-10% above stock price
- [x] **Dashboard & Pre-computed Scan Filters (BROADER)**
  - Price range: $15-$500 (broader for discovery)
  - Same volume/market cap/earnings filters
- [x] **Top 5 Weekly + Top 5 Monthly Rule**
  - Dashboard shows 5 Weekly (7-14 DTE) + 5 Monthly (21-45 DTE)
  - Weekly has priority over Monthly
  - Single-Candidate Rule per timeframe
- [x] **W/M Badge for ALL Results**
  - Weekly (≤14 DTE) shows cyan "W" badge
  - Monthly (>14 DTE) shows purple "M" badge
  - Applied to both Custom Scan and Pre-computed results
- [x] **Screener Defaults to Custom Scan**
  - Page loads Custom Scan results by default
  - Quick Scans (Pre-computed) available via buttons
- [x] **BID-Only Pricing** (Maintained from Phase 3)
  - All SELL legs use BID price only
- [x] **Testing**
  - 17/17 backend tests passed
  - Dashboard: 5 Weekly + 5 Monthly verified
  - Custom Scan: Phase 4 $30-$90 filter verified
- [x] **Files Updated**
  - `/app/backend/routes/screener.py` - Dashboard + Screener endpoints
  - `/app/frontend/src/pages/Screener.js` - Default to Custom Scan, W/M badges
  - `/app/frontend/src/pages/Dashboard.js` - Updated subtitle

### ✅ Completed (Jan 21, 2026) - PHASE 5: PMCC Engine Rebuild
- [x] **System Scan Filters (Custom Scan)**
  - Price range: $30-$90 for stocks (ETFs exempt)
  - Average Volume: ≥1M
  - Market Cap: ≥$5B (ETFs exempt)
  - Earnings: No earnings within 7 days
  - LEAPS DTE: 180-730 days
  - Short Call DTE: 14-60 days
- [x] **Dashboard/Pre-computed Filters (BROADER)**
  - Price range: $15-$500
  - Same volume/market cap/earnings filters
- [x] **Single-Candidate Rule**
  - One best trade per symbol (highest score wins)
- [x] **ASK/BID Pricing Enforced**
  - LEAPS (Buy leg): ASK price
  - Short Call (Sell leg): BID price
- [x] **PMCC Page Defaults to Custom Scan**
  - Page loads Custom Scan results by default
  - Quick Scans (Pre-computed) available via buttons
- [x] **Bug Fix: Deep ITM LEAPS**
  - Yahoo Finance fetch now includes deep ITM options (50-115% of stock price)
  - LEAPS need ITM options for PMCC strategy
- [x] **ETF Exemptions**
  - Added: GLD, SLV, ARKK, ARKG, ARKW, TLT, EEM, VXX, UVXY, SQQQ, TQQQ
- [x] **Testing**
  - Custom Scan: 10 opportunities (INTC, PYPL, GM, DAL, etc.)
  - All prices in $30-$90 range (ETFs exempt)
- [x] **Files Updated**
  - `/app/backend/routes/screener.py` - PMCC endpoint with Phase 5 filters
  - `/app/backend/services/data_provider.py` - Fixed LEAPS options fetching
  - `/app/frontend/src/pages/PMCC.js` - Default to Custom Scan

### ✅ Completed (Jan 21, 2026) - PHASE 6: Market Bias Order Fix
- [x] **Separated Filtering from Scoring**
  - Eligibility filtering happens first (chain valid, structure valid)
  - Market bias applied ONLY to eligible trades
  - Flow: validate → collect → apply bias → calculate final score → sort
- [x] **Market Sentiment Module**
  - New service: `/app/backend/services/market_bias.py`
  - VIX-based sentiment (70% weight)
  - SPY momentum indicator (30% weight)
  - 15-minute cache TTL
- [x] **Bias Weights**
  - Bullish market: CC weight 1.10-1.20, PMCC weight 1.15-1.25
  - Neutral market: weight 1.0
  - Bearish market: CC weight 0.80-0.90, PMCC weight 0.75-0.85
- [x] **Delta-Based Adjustment**
  - Bullish: Bonus for higher delta (more aggressive)
  - Bearish: Bonus for lower delta (more protective)
- [x] **New Endpoints**
  - `GET /api/screener/market-sentiment` - Current bias info
  - `POST /api/screener/market-sentiment/clear-cache` - Clear cache
- [x] **Response Updates**
  - All screener responses include `market_bias`, `bias_weight`
  - Opportunities include `base_score` and `score` (bias-adjusted)
- [x] **Files Updated**
  - `/app/backend/services/market_bias.py` - NEW
  - `/app/backend/routes/screener.py` - All endpoints updated

### ✅ Completed (Jan 21, 2026) - PHASE 7: Quality Score Rewrite
- [x] **Binary Gating**
  - Invalid trades are NOT scored (rejected before scoring)
- [x] **Covered Call 5 Pillars (0-100)**
  - Volatility & Pricing Edge (30%): IV Rank, Premium Yield, IV Efficiency
  - Greeks Efficiency (25%): Delta Sweet Spot, Theta Decay, Risk/Reward
  - Technical Stability (20%): SMA Alignment, RSI, Price Stability
  - Fundamental Safety (15%): Market Cap, Earnings, Analyst Rating
  - Liquidity & Execution (10%): Open Interest, Volume, Bid-Ask Spread
- [x] **PMCC 5 Pillars (0-100)**
  - LEAP Quality (30%): Delta, DTE, Cost Efficiency
  - Short Call Income Efficiency (25%): ROI, Short Delta, Income vs Decay
  - Volatility Structure (20%): Overall IV, IV Skew, IV Rank
  - Technical Alignment (15%): Trend, SMA, RSI
  - Liquidity & Risk Controls (10%): LEAPS OI, Short OI, Risk Structure
- [x] **Score Breakdown in API**
  - Each opportunity includes `score_breakdown` with pillar details
  - Shows: name, max_score, actual_score, percentage, explanation
- [x] **UI Tooltip for Score**
  - Hover over any score badge to see pillar breakdown
  - Visual progress bars for each pillar
  - Available on Screener and PMCC pages
- [x] **Files Created/Updated**
  - `/app/backend/services/quality_score.py` - NEW: Pillar scoring engine
  - `/app/backend/routes/screener.py` - All endpoints use pillar scoring
  - `/app/frontend/src/pages/Screener.js` - Score tooltip with breakdown
  - `/app/frontend/src/pages/PMCC.js` - Score tooltip with breakdown

### ✅ Completed (Jan 21, 2026) - PHASE 8: Storage, Logging & Admin
- [x] **Admin Status Endpoint**
  - New endpoint: `GET /api/screener/admin/status`
  - Returns: phase info, market bias, quality pillars, system filters, engine rules
- [x] **Admin Panel Data Quality Section**
  - Current Engine Phase with history (Phase 6, 7, 8 status badges)
  - Market Bias display (VIX, SPY momentum, CC/PMCC weights)
  - CC Quality Pillars (5 pillars with weights and factors)
  - PMCC Quality Pillars (5 pillars with weights and factors)
  - System Filters (CC Custom, PMCC Custom)
  - Engine Rules (Single-candidate, Binary gating, ETF exemptions)
  - Pre-computed Scan Status
  - Refresh button for real-time updates
- [x] **Files Updated**
  - `/app/backend/routes/screener.py` - Added admin status endpoint
  - `/app/frontend/src/pages/Admin.js` - Added Data Quality section

### 🔄 In Progress
- None currently

### 📋 Upcoming Tasks
- Refactor `Admin.js` (2000+ lines)
- Refactor `Screener.js` and `PMCC.js`
- Support System - AI Learning
- Admin Panel - Content & Announcement Manager

### ✅ Completed (Jan 14, 2026) - Auto-Load Pre-Computed Scans & Data Preservation
- [x] **PMCC Page Fix**
  - Fixed: PMCC page now auto-loads "Leveraged Income" pre-computed scan on page load
  - 19 PMCC opportunities displayed with full data
  - Users never see blank screen - previous market close data always available
- [x] **Screener Page Fix**  
  - Fixed: Screener page now auto-loads "Premium Hunter" pre-computed scan on page load
  - 32 CC opportunities displayed with real IV, IV Rank, OI data
  - IV (57.9%, 63.8%, 44.0%), IV Rank (87%, 96%, 66%), OI (385, 424, 42)
- [x] **Data Preservation Logic**
  - Added safety check: scans returning 0 results now preserve previous data
  - Prevents overwriting good data during rate limits or after-hours
- [x] **Yahoo Finance for LEAPS**
  - PMCC scan now uses Yahoo Finance (primary) for LEAPS options
  - Fallback to Polygon if Yahoo fails
  - Better data availability for PMCC opportunities
- [x] **All Pre-Computed Scans Refreshed**
  - CC Conservative: 8 opportunities
  - CC Balanced: 27 opportunities  
  - CC Aggressive: 32 opportunities
  - PMCC Conservative: 7 opportunities
  - PMCC Balanced: 19 opportunities

### ✅ Completed (Jan 14, 2026) - IV, IV Rank, OI Data Consistency
- [x] **Dashboard Top 10 Table**
  - IV, IV Rank, and OI columns display correctly
  - Real data from Yahoo Finance: IV (66%), IV Rank (98%), OI (14,432)
  - Added open_interest to scan_parameters when adding trades to simulator
- [x] **Screener Custom Scan**
  - IV, IV Rank, OI columns display correctly with real data
  - Sample data: IV (76.6%), IV Rank (77%), OI (1,417)
  - Fixed bug: 'top_opps' undefined error in screener.py
- [x] **Screener Pre-Computed Scans**
  - IV column displays (30% default from older data)
  - IV Rank and OI show '-' until scans are re-run with new code
  - Updated precomputed_scans.py to use Yahoo Finance for IV/OI
- [x] **Watchlist Page**
  - All columns display correctly: IV, IV Rank, OI
  - Real data from Yahoo Finance opportunity object
- [x] **Simulator Page**
  - Fixed: IV Rank now reads from trade.scan_parameters.iv_rank
  - IV displays correctly, IV Rank now shows (46%, 51%, 45%)
  - OI will display for new trades added after fix
- [x] **PMCC Page**
  - No IV/OI columns by design - focuses on LEAPS metrics
  - All PMCC-specific columns display correctly
- [x] **Files Updated**
  - `/app/backend/services/precomputed_scans.py` - Yahoo primary for options, includes IV/OI
  - `/app/backend/routes/screener.py` - Fixed 'top_opps' bug
  - `/app/frontend/src/pages/Simulator.js` - Reads iv_rank from scan_parameters
  - `/app/frontend/src/pages/Dashboard.js` - Passes open_interest to scan_parameters
  - `/app/frontend/src/pages/Screener.js` - Passes open_interest to scan_parameters

### ✅ Completed (Jan 14, 2026) - Unified Data Architecture (Yahoo Primary)
- [x] **Data Provider Rewrite**
  - Yahoo Finance is now PRIMARY source for stocks AND options
  - Polygon is BACKUP only (for when Yahoo fails)
  - Unified logic in `/app/backend/services/data_provider.py`
- [x] **Consistency Across All Pages**
  - Dashboard, Screener, PMCC, Watchlist now use same data source
  - No more separate enrichment calls - Yahoo provides IV/OI built-in
  - Analyst ratings fetched with stock quotes automatically
- [x] **Data Always Available**
  - Yahoo provides previous close data for weekends/holidays
  - When market opens, real-time data available
  - Graceful fallback to Polygon if Yahoo fails
- [x] **Files Updated**
  - `/app/backend/services/data_provider.py` - Complete rewrite with Yahoo primary
  - `/app/backend/routes/screener.py` - Simplified to use unified provider
  - `/app/backend/routes/watchlist.py` - Simplified to use unified provider
- [x] **Benefits**
  - Simpler codebase (no separate enrichment steps)
  - Consistent data across all pages
  - IV and OI available from Yahoo (during market hours)
  - Analyst ratings included automatically

### ✅ Completed (Jan 14, 2026) - Added OI Column to Dashboard & Screener
- [x] **Dashboard Top 10 Table**
  - Added OI (Open Interest) column between IV and AI Score
  - Added Yahoo enrichment for IV and OI data
  - Shows real values during market hours
- [x] **Screener Table**
  - Replaced IV Rank with OI column for better liquidity visibility
  - Shows real OI values: 11,749 (XLE), 2,732 (XLK), 1,647 (AAL), etc.
  - Shows real IV values: 84.6% (INTC), 58.2% (AAL), 50.7% (XLK), etc.
- [x] **Files Updated**
  - `/app/frontend/src/pages/Dashboard.js` - Added OI column to table header and rows
  - `/app/frontend/src/pages/Screener.js` - Replaced IV Rank with OI column
  - `/app/backend/routes/screener.py` - Added Yahoo enrichment to dashboard endpoint
- [x] **Note**: Dashboard shows default IV (30%) and OI (-) when market is closed due to Yahoo Finance data limitations

### ✅ Completed (Jan 14, 2026) - Yahoo Finance Data Enrichment
- [x] **Yahoo Finance Integration for IV & OI**
  - Created `fetch_options_iv_oi_from_yahoo()` in data_provider.py
  - Created `enrich_options_with_yahoo_data()` helper function
  - Fetches real Implied Volatility and Open Interest from Yahoo
  - Used as enrichment layer on top of Polygon options data
- [x] **Applied to All Screeners**
  - Watchlist: Shows real IV (28%, 48%, 39%) and OI (6,770+)
  - Screener: Shows real IV and OI from Yahoo
  - Dashboard: Uses Yahoo enrichment
  - PMCC: Uses Yahoo enrichment
- [x] **Watchlist Fixes**
  - Removed strict OI filter that blocked all results
  - OI filter now only applies when Yahoo data is available
  - All opportunity columns now populated with real data
- [x] **Files Updated**
  - `/app/backend/services/data_provider.py` - Added Yahoo options functions
  - `/app/backend/routes/watchlist.py` - Uses Yahoo enrichment
  - `/app/backend/routes/screener.py` - Uses Yahoo enrichment

### ✅ Completed (Jan 14, 2026) - Data Quality Filters
- [x] **Premium Sanity Check**
  - Max OTM call premium: 10% of underlying price
  - Filters out unrealistic premiums (e.g., $141 on $124 stock)
  - Applied to: Screener, Dashboard, PMCC, Watchlist
- [x] **ROI Sanity Check**
  - Preliminary ROI check: 20% max for OTM calls
  - Filters out bad data with abnormally high ROI
- [x] **Liquidity Scoring**
  - Bonus points for high open interest (when available)
  - Higher OI = higher score ranking
- [x] **Files Updated**
  - `/app/backend/routes/screener.py` - Main screener and dashboard endpoints
  - `/app/backend/routes/watchlist.py` - Watchlist opportunity finder
  - `/app/backend/services/precomputed_scans.py` - Pre-computed scan service
- [x] **Note**: Polygon basic plan doesn't return open interest, so filtering relies on premium sanity checks

### ✅ Completed (Jan 13, 2026) - Enhanced Watchlist
- [x] **Watchlist Table Redesign**
  - Redesigned from card-based to table format matching screener style
  - Columns: Symbol, Price, Strike, Type, DTE, Premium, ROI, Delta, IV, AI Score, Analyst, Action
  - Notes and "Added" date displayed below symbol name
- [x] **Price Tracking**
  - Captures `price_when_added` from Polygon API when adding stocks
  - Shows current price from live Polygon data
  - Movement percentage calculation (current vs added price) with up/down arrows
- [x] **Covered Call Opportunities**
  - Best opportunity shown for each watchlist item
  - Strike column: Shows expiry + strike + type (e.g., "16JAN26 $257.5C")
  - Type column: Weekly (cyan badge) or Monthly (purple badge)
  - Premium, ROI, Delta, IV columns with formatted data
  - AI Score with color-coded badges (green for high scores)
  - "No opportunities" message with icon for ETFs without suitable options
- [x] **CRUD Operations**
  - Add stock with symbol validation
  - Delete individual items
  - Clear All with confirmation dialog
- [x] **Summary Stats**
  - Total Symbols count
  - With Opportunities count
  - Gainers count (stocks up since added)
  - Losers count (stocks down since added)
- [x] **Analyst Ratings**
  - Fetched from yfinance
  - Color-coded badges (Strong Buy, Buy, Hold, Sell)
  - Shows "-" for stocks without analyst coverage
- [x] **Backend Enhancements**
  - `/app/backend/routes/watchlist.py` - Complete rewrite with Polygon API integration
  - `fetch_stock_prices_polygon()` - Batch price fetching with logging
  - `fetch_analyst_ratings_batch()` - Parallel analyst rating fetches
  - `_get_best_opportunity()` - Find best covered call with Type, AI Score, IV defaults

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
- [ ] Watchlist Price Alerts - notify when target price hit or high-ROI opportunity appears (P3)

### ✅ Completed (Jan 13, 2026) - Analyst Rating Columns
- [x] **Screener Page**
  - Added Analyst column showing Strong Buy/Buy/Hold/Sell badges
  - Fixed IV column to be visible for both pre-computed and custom scans
  - IV data now shows properly (percentage format)
- [x] **PMCC Page**
  - Added Analyst column showing analyst ratings
  - Pre-computed PMCC scans now include analyst_rating data
- [x] **Dashboard Top 10 CC**
  - Added Analyst column header (shows "-" for live data, ratings available in modal)
  - Strike format updated to "16JAN26 $46 C"
- [x] **Pre-Computed Scans Backend**
  - Updated fetch_fundamental_data() to include analyst_rating, num_analysts, target_price
  - Both CC and PMCC opportunities now include analyst data
  - Data sourced from Yahoo Finance recommendationKey field

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
   - Test environment invitations now correctly use: `https://callscreener-1.preview.emergentagent.com`
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
