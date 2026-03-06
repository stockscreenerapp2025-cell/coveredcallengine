# Covered Call Engine (CCE) — Complete Project Document
### Business Logic, Architecture, Data Flow & Feature Explanation

---

## 1. What Is This Product?

**Covered Call Engine (CCE)** is a web-based financial tool for US stock market traders.

It helps traders find the best **Covered Call** and **PMCC (Poor Man's Covered Call)** option trading opportunities across 1,000+ US stocks and ETFs — automatically, every day after market close.

### What is a Covered Call? (Simple Explanation)
- You own 100 shares of a stock (e.g., Apple at $180/share = $18,000 invested)
- You sell someone the right to buy your shares at a higher price (e.g., $185) for a fee (called a "premium")
- If the stock doesn't reach $185 by expiry — you keep the premium as income
- This is a conservative income-generating strategy used by millions of traders

### What is PMCC? (Poor Man's Covered Call)
- Instead of buying 100 real shares, you buy a **LEAPS option** (long-dated call option, 1-2 years out)
- Much cheaper than buying real shares (e.g., $3,000 instead of $18,000)
- Then you sell short-term calls against it — same income, less capital required

---

## 2. Who Is the Target User?

| User Type | What They Need |
|---|---|
| Retail options traders | Find the best covered call setups daily |
| Income investors | Generate consistent monthly premium income |
| PMCC traders | Leverage LEAPS for cheap covered call income |
| Portfolio managers | Screen for best risk-adjusted opportunities |

---

## 3. Technology Stack

### Backend
| Component | Technology |
|---|---|
| Language | Python 3.11+ |
| Web Framework | FastAPI (async) |
| Database | MongoDB (via Motor async driver) |
| Scheduler | APScheduler (runs EOD pipeline daily at 4:10 PM ET) |
| Market Data | Yahoo Finance (yfinance) |
| Options Pricing | Black-Scholes formula (custom implementation) |
| Authentication | JWT (JSON Web Tokens) |
| Email | SMTP + IMAP |
| Payments | PayPal (subscription billing) |

### Frontend
| Component | Technology |
|---|---|
| Framework | React.js |
| Styling | Tailwind CSS |
| Charts | Recharts |
| HTTP Client | Axios |
| Routing | React Router |

### Infrastructure
| Component | Detail |
|---|---|
| Domain | coveredcallengine.com |
| Hosting | VPS / Cloud server |
| Database | MongoDB Atlas or self-hosted |
| Environment | .env file for secrets |

---

## 4. MongoDB Database Collections

The database is named `premium_hunter`. Here are all the key collections:

| Collection | Purpose | Key Fields |
|---|---|---|
| `users` | User accounts | email, password_hash, subscription_tier, created_at |
| `scan_universe` | List of 1,000+ symbols to scan | symbol, market_cap, volume, price, source |
| `eod_snapshots` | Raw option chain data per symbol | symbol, expiry, strike, bid, ask, iv, dte, delta, theta, volume, open_interest |
| `scan_runs` | Results of each daily EOD scan | run_id, timestamp, symbols_scanned, opportunities |
| `cc_opportunities` | Final covered call results | symbol, strike, premium, roi_pct, delta, theta, dte, quality_score |
| `pmcc_opportunities` | PMCC results | symbol, leaps_strike, short_strike, net_debit, roi_per_cycle |
| `symbol_enrichment` | Technical & fundamental data per symbol | symbol, rsi, adx, sma_50, sma_200, trend, pe_ratio, roe, quote_type, analyst_rating |
| `iv_history` | Historical IV data for IV Rank calculation | symbol, date, iv |
| `portfolios` | User's tracked positions | user_id, symbol, strategy, entry_date, premium_collected |
| `watchlists` | User's saved watchlist | user_id, symbols[] |
| `saved_scans` | User's saved filter presets | user_id, name, filters |
| `wallet_transactions` | AI Wallet credits | user_id, amount, type, balance |
| `subscriptions` | PayPal subscription records | user_id, plan, status, paypal_id |
| `scan_progress` | Real-time scan progress (in-memory) | user_id, stage, pct, current_symbol |

---

## 5. How the System Works — End to End

### Step 1: Universe Setup (Admin Only)

The admin uploads a **Nasdaq CSV file** (downloaded from Nasdaq screener website) to build the scan universe.

**Admin Panel → CCE Universe Management:**
1. Admin uploads `nasdaq_screener.csv`
2. System imports ~8,000 symbols
3. System filters down to ~1,000 symbols based on:
   - Market Cap >= $500 Million
   - Volume >= 100,000 daily
   - Price $10–$600 (too cheap = illiquid options, too expensive = capital intensive)
4. Result saved to `scan_universe` collection
5. Separately, a PMCC universe is built for stocks with LEAPS available

---

### Step 2: EOD Pipeline — Runs Daily at 4:10 PM ET

This is the **heart of the system**. Every trading day after market close, the pipeline runs automatically.

**What it does:**

```
4:10 PM ET trigger
      |
      v
Load ~1,000 symbols from scan_universe
      |
      v
For each symbol (in batches, with 25s timeout):
  1. Fetch current stock price from Yahoo Finance
  2. Fetch full option chain (all expiry dates)
  3. Filter to options within DTE range (7-60 days for CC)
  4. For each valid strike/expiry combination:
     - Calculate ROI = (premium / stock_price) × 100
     - Calculate Annualized ROI = ROI × (365 / DTE)
     - Calculate Delta, Theta (Black-Scholes)
     - Check min thresholds (volume, OI, price, delta)
  5. Score each opportunity (0-100 Quality Score)
  6. Save best opportunities to cc_opportunities
      |
      v
For PMCC universe symbols:
  - Fetch LEAPS (365+ DTE options)
  - Find best ITM LEAPS (delta 0.70-0.85)
  - Pair with short-term OTM calls
  - Calculate net debit, max profit, ROI per cycle
  - Score and save to pmcc_opportunities
      |
      v
Run Symbol Enrichment:
  - Fetch Yahoo Finance: pe_ratio, roe, analyst_rating, quoteType
  - Calculate: RSI, SMA-50, SMA-200, ADX, Trend
  - Save to symbol_enrichment collection
      |
      v
Write scan_run record with summary stats
Pipeline complete (~15-30 minutes total)
```

---

### Step 3: User Scans (Real-Time)

When a user clicks **"Scan"** in the Screener:

```
User sets filters (min ROI, delta, DTE, etc.)
      |
      v
Frontend sends request to /screener/covered-calls
      |
      v
Backend checks cache (5-min cache, keyed by filter hash)
      |  (cache miss)
      v
Load latest scan_run snapshot from MongoDB
      |
      v
Apply user filters:
  - Price range, Market Cap
  - Min Volume, Min Open Interest
  - Delta range (min/max)
  - DTE range
  - Moneyness (ATM/ITM/OTM)
  - Min ROI, Min Annualized ROI
  - Max Theta
  - Min Probability OTM
  - Technical: Overall Trend, SMA filter, RSI filter, Trend Strength
  - Fundamental: P/E Ratio, Min ROE
      |
      v
Merge enrichment data (RSI, ADX, SMA, P/E, ROE) from symbol_enrichment
      |
      v
Return filtered, sorted opportunities to frontend
      |
      v
Progress bar updates every 1.5 seconds (5 stages shown)
      |
      v
Results displayed in table with sorting/pagination
```

---

## 6. Quality Scoring System (0–100)

Every opportunity gets an automated quality score. This helps users compare trades objectively.

### Covered Call Score (5 Pillars)

| Pillar | Weight | What It Measures |
|---|---|---|
| Volatility & Pricing Edge | 30% | IV Rank, premium yield, IV efficiency |
| Greeks Efficiency | 25% | Delta sweet spot (0.20–0.35), theta decay rate |
| Technical Stability | 20% | SMA alignment, RSI position, price stability |
| Fundamental Safety | 15% | Market cap tier, earnings date risk, analyst rating |
| Liquidity & Execution | 10% | Open Interest, volume, bid-ask spread |

**Score Interpretation:**
- 80–100: Excellent trade setup
- 60–79: Good opportunity
- 40–59: Average, some risk
- Below 40: Weak setup, proceed with caution

### PMCC Score (5 Pillars)

| Pillar | Weight | What It Measures |
|---|---|---|
| LEAP Quality | 30% | LEAPS delta (0.70–0.85 ideal), DTE, cost efficiency |
| Short Call Income | 25% | ROI per cycle, short delta, cycles to cover LEAPS cost |
| Volatility Structure | 20% | IV environment, IV skew (LEAPS vs short), IV Rank |
| Technical Alignment | 15% | Trend direction, SMA, RSI |
| Liquidity & Risk | 10% | LEAPS OI, short call OI, strike width ratio |

---

## 7. Key Financial Calculations

### ROI (Return on Investment)
```
ROI % = (Option Premium / Stock Price) × 100
Example: Premium $2.50, Stock $100 → ROI = 2.5%
```

### Annualized ROI
```
Ann. ROI % = ROI × (365 / DTE)
Example: 2.5% ROI, 30 DTE → Ann. ROI = 30.4%
```

### Moneyness (ATM/ITM/OTM)
```
% Difference = (Strike - Spot) / Spot × 100

ATM = abs(% diff) <= 2%          (within 2% of current price)
ITM = Strike < Spot AND not ATM  (strike below current price)
OTM = Strike > Spot AND not ATM  (strike above current price)
```

### Black-Scholes Theta (Daily Decay)
```
d1 = [ln(S/K) + 0.5 × σ² × T] / (σ × √T)
N'(d1) = (1/√2π) × e^(-0.5 × d1²)
Theta = -(S × N'(d1) × σ) / (2 × √T) / 365

Where:
  S = Stock price
  K = Strike price
  σ = Implied Volatility (IV)
  T = Time to expiry in years (DTE/365)

Result: Negative number = daily dollar decay per share
Example: Theta = -0.05 means option loses $0.05/day in value
```

### IV Rank
```
IV Rank = (Current IV - 52-week Low IV) / (52-week High IV - 52-week Low IV) × 100

IV Rank 0-30  = Low volatility (cheap premium)
IV Rank 30-70 = Normal (sweet spot)
IV Rank 70+   = High volatility (expensive premium, more risk)
```

### ADX (Average Directional Index — Trend Strength)
```
ADX < 20   = Weak trend (ranging market)
ADX 20–25  = Moderate trend
ADX > 25   = Strong trend (trending market)
```

---

## 8. Screener Filters — Full List

### Stock Filters
| Filter | Description |
|---|---|
| Min Price / Max Price | Stock price range |
| Market Cap | Any / Small (<$2B) / Mid ($2-10B) / Large (>$10B) |
| Sector | Technology, Healthcare, Finance, etc. |
| Exchange | Any / NYSE / NASDAQ |
| Symbol Search | Search specific ticker |

### Options Filters
| Filter | Description |
|---|---|
| Min DTE / Max DTE | Days to expiry range (7–60 typical) |
| Moneyness | ATM / ITM / OTM / All |
| Min Volume | Minimum daily option volume |
| Min Open Interest | Minimum open contracts |

### Greeks Filters
| Filter | Description |
|---|---|
| Min Delta / Max Delta | Target delta range (0.20–0.35 ideal) |
| Maximum Theta | Max daily decay (e.g., -0.05 = keep theta >= -0.05) |
| Min Prob OTM / Max Prob OTM | Probability option expires worthless |

### ROI Filters
| Filter | Description |
|---|---|
| Min ROI % | Minimum return on investment |
| Min Annualized ROI % | Minimum annualized return |

### Technical Filters
| Filter | Description |
|---|---|
| Overall Signal | All / Bullish / Bearish / Neutral |
| SMA Filter | None / Above SMA-50 / Above SMA-200 / Above Both |
| RSI Filter | All / Oversold (<30) / Neutral (30-70) / Overbought (>70) |
| Trend Strength | All / Strong / Moderate / Weak |

### Fundamental Filters
| Filter | Description |
|---|---|
| P/E Ratio | Under 15 / 15-25 / 25-40 / Over 40 |
| Min ROE % | Minimum Return on Equity |

---

## 9. Pages & Features

### Dashboard
- Market overview (market state: open/closed/pre-market)
- Summary stats: total opportunities today, avg ROI, top opportunities
- Quick scan launch

### Screener (Main Feature)
- 15+ filter combinations
- Results table: Symbol, Strategy, Strike, Expiry, Premium, ROI, Delta, Theta, Quality Score
- Stock Detail Modal: price chart, Greeks breakdown, technical indicators (RSI, ADX, SMA, trend)
- Export to CSV
- Save/load filter presets
- Real-time scan progress bar during refresh

### PMCC Screener
- Same concept but for Poor Man's Covered Calls
- Shows: LEAPS details, short call, net debit, max profit, break-even
- Quality score breakdown for PMCC pillars

### Portfolio Tracker
- User adds their open positions
- Tracks: entry date, premium collected, current P&L
- Shows: days remaining, position status (open/closed/expired/assigned)
- Calculates total income generated

### Watchlist
- User saves stocks they're monitoring
- Shows quick option stats for watchlisted symbols

### Simulator
- Paper trading tool
- User simulates entering/exiting covered call trades
- Tracks simulated P&L without real money

### AI Wallet
- Credit-based system
- Users buy AI credits (via PayPal)
- Use credits to ask AI questions about their trades (chatbot)
- Plan resolver maps subscription tier to credit limits

### Admin Panel
- Universe management (upload Nasdaq CSV, build universe)
- User management
- Subscription management
- Pipeline controls (manual trigger, status view)
- System health (DB connection, scheduler status, market state)
- Email automation controls

---

## 10. Symbol Enrichment Pipeline

Every symbol in the scan universe gets enriched with additional data. This runs as part of the EOD pipeline.

**Data fetched from Yahoo Finance:**
| Field | Source | Description |
|---|---|---|
| `quote_type` | yf.info["quoteType"] | "ETF" or "EQUITY" |
| `pe_ratio` | yf.info["trailingPE"] | Price-to-Earnings ratio |
| `roe` | yf.info["returnOnEquity"] | Return on Equity % |
| `analyst_rating` | yf.info["recommendationKey"] | buy/hold/sell |
| `market_cap` | yf.info["marketCap"] | Market capitalization |

**Calculated internally:**
| Field | Calculation |
|---|---|
| `rsi` | 14-period RSI from daily closes |
| `sma_50` | 50-day simple moving average |
| `sma_200` | 200-day simple moving average |
| `adx` | 14-period ADX (trend strength) |
| `trend` | bullish/bearish/neutral based on SMA crossover + price action |
| `trend_strength` | strong/moderate/weak based on ADX value |
| `macd_signal` | MACD line vs signal line |

---

## 11. ETF Handling

ETFs (like SPY, QQQ, IWM) behave differently from stocks:
- They don't have P/E ratios or ROE
- Their premiums are lower than individual stocks
- Covered calls on ETFs are very common (income strategy)

**How the system handles ETFs:**
1. `quote_type = "ETF"` detected from Yahoo Finance
2. ETF gets a relaxed **ROI floor of 0.15%** (instead of user's min ROI)
   - This prevents ETFs from being filtered out even when user sets min ROI = 2%
   - ETF premiums are naturally lower, so lower ROI is still acceptable
3. P/E and ROE filters are skipped for ETFs (no fundamental data)

---

## 12. Caching System

The system uses aggressive caching to avoid hitting Yahoo Finance rate limits and to return results fast.

| Cache Type | Duration | Key |
|---|---|---|
| Screener results | 5 minutes | Hash of all filter parameters |
| Weekend cache | 72 hours | Market doesn't change on weekends |
| EOD snapshot | Until next EOD run | Latest scan_run ID |
| IV Rank | 24 hours | Symbol + date |

**Cache key generation:**
All filter parameters are hashed together into a unique string. If any parameter changes, a new cache entry is created. Cache is stored in MongoDB.

---

## 13. Authentication & Subscription Tiers

### Authentication
- JWT-based (JSON Web Token)
- Token stored in browser localStorage
- 24-hour token expiry
- Password reset via email

### Subscription Tiers
| Tier | Features |
|---|---|
| Free | Limited scans per day, basic filters |
| Pro | Unlimited scans, all filters, export CSV, portfolio tracker |
| Premium | All Pro features + AI Wallet credits, priority support |

### Payment
- PayPal subscription (monthly/annual)
- Webhook for subscription status updates
- Credits system for AI chatbot usage

---

## 14. Market State Detection

The system knows the current state of the US market:

| State | Hours (ET) | Behavior |
|---|---|---|
| Pre-Market | 4:00 AM – 9:30 AM | Show previous day data |
| Market Open | 9:30 AM – 4:00 PM | Real-time prices where possible |
| After Hours | 4:00 PM – 8:00 PM | EOD pipeline runs at 4:10 PM |
| Closed | 8:00 PM – 4:00 AM | Use cached data |
| Weekend | Sat–Sun | 72-hour cache, no pipeline |

**Trading calendar** is used to detect US market holidays (no pipeline runs on holidays).

---

## 15. Data Flow Diagram

```
[Yahoo Finance API]
        |
        v
[EOD Pipeline - 4:10 PM ET daily]
        |
        |----> [eod_snapshots] (raw option chains)
        |----> [cc_opportunities] (filtered CC trades)
        |----> [pmcc_opportunities] (filtered PMCC trades)
        |----> [symbol_enrichment] (RSI, ADX, SMA, PE, ROE)
        |----> [iv_history] (for IV Rank calculation)
        |----> [scan_runs] (summary record)
        |
        v
[MongoDB - premium_hunter DB]
        |
        v
[FastAPI Backend]
        |
        |----> GET /screener/covered-calls (with filters)
        |----> GET /screener/pmcc (PMCC results)
        |----> GET /screener/scan-progress (live progress)
        |----> GET /portfolio (user positions)
        |----> POST /auth/login (authentication)
        |----> POST /paypal/subscribe (payments)
        |----> GET /admin/* (admin controls)
        |
        v
[React Frontend - coveredcallengine.com]
        |
        |----> Screener Page (main feature)
        |----> PMCC Page
        |----> Dashboard
        |----> Portfolio Tracker
        |----> Watchlist
        |----> Simulator
        |----> AI Wallet
        |----> Admin Panel
```

---

## 16. Key Business Rules

1. **Minimum Quality Gate:** Options with volume < 10 or OI < 10 are excluded before scoring
2. **ETF ROI Floor:** ETFs use min(user_roi, 0.15%) so they're not filtered out unfairly
3. **Earnings Safety:** Stocks with earnings within the DTE window score 0 on fundamentals (high IV crush risk)
4. **Negative P/E Excluded:** Companies with negative or zero P/E are excluded from P/E filters (loss-making companies)
5. **Theta Direction:** More negative theta = faster decay. max_theta = -0.05 means "keep options where theta >= -0.05"
6. **ATM Precedence:** If strike is within ±2% of spot, it's always ATM — never ITM or OTM
7. **LEAPS for PMCC:** Only symbols in the LEAPS safe universe (confirmed to have far-dated options) are scanned for PMCC
8. **Cache Bypass:** Admin can bypass cache to force fresh scan results

---

## 17. File Structure

```
coveredcallengine/
├── backend/
│   ├── server.py                     # FastAPI app entry point, all routes registered
│   ├── database.py                   # MongoDB connection, env validation
│   ├── routes/
│   │   ├── screener.py               # Main covered call screener API
│   │   ├── eod_pipeline.py           # Manual EOD trigger endpoint
│   │   ├── admin.py                  # Admin panel APIs
│   │   ├── portfolio.py              # Portfolio tracker
│   │   ├── watchlist.py              # Watchlist management
│   │   ├── auth.py                   # Login, register, JWT
│   │   ├── paypal.py                 # Payment & subscriptions
│   │   ├── ai.py                     # AI chatbot endpoint
│   │   └── options.py                # Option data endpoints
│   ├── services/
│   │   ├── eod_pipeline.py           # Core EOD pipeline logic
│   │   ├── symbol_enrichment.py      # Technical/fundamental data fetch
│   │   ├── quality_score.py          # 0-100 scoring system
│   │   ├── iv_rank_service.py        # IV Rank calculation
│   │   ├── yf_pricing.py             # Yahoo Finance helpers
│   │   ├── universe_builder.py       # Symbol universe management
│   │   ├── scheduler_setup.py        # APScheduler configuration
│   │   ├── scan_progress.py          # Real-time progress tracking
│   │   └── email_service.py          # Email notifications
│   ├── data/
│   │   ├── etf_whitelist.py          # Known ETF tickers (fallback)
│   │   ├── sp500_symbols.py          # S&P 500 symbol list
│   │   └── leaps_safe_universe.py    # Symbols with LEAPS available
│   └── utils/
│       ├── auth.py                   # JWT helpers
│       ├── market_state.py           # Market open/closed detection
│       └── trading_calendar.py       # US holiday calendar
│
└── frontend/
    └── src/
        ├── pages/
        │   ├── Screener.js           # Main screener UI
        │   ├── PMCC.js               # PMCC screener
        │   ├── Dashboard.js          # Overview page
        │   ├── Portfolio.js          # Portfolio tracker
        │   ├── Watchlist.js          # Watchlist page
        │   ├── Simulator.js          # Paper trading
        │   ├── AIWallet.js           # AI credits & chatbot
        │   ├── Admin.js              # Admin panel
        │   ├── Login.js / Register.js
        │   └── Pricing.js            # Plans page
        ├── components/
        │   ├── StockDetailModal.js   # Trade detail popup
        │   ├── ScanProgressBar.js    # Live progress during scan
        │   └── ui/                   # Reusable UI components
        └── lib/
            └── api.js                # All API calls centralized
```

---

## 18. Summary — What Makes This Product Valuable

| Feature | Why It Matters |
|---|---|
| 1,000+ symbols scanned daily | Saves trader hours of manual research |
| Quality Score (0-100) | Objective comparison across trades |
| 15+ filters | Trader finds exactly what fits their strategy |
| Technical indicators (RSI, ADX, SMA) | Avoid trading against the trend |
| Fundamental filters (P/E, ROE) | Avoid fundamentally weak companies |
| PMCC strategy | Access for traders without large capital |
| IV Rank | Know if you're selling premium at the right time |
| Portfolio tracker | Track all positions in one place |
| AI Chatbot | Get explanations and trade guidance |
| Automated daily pipeline | Always fresh data, zero manual work |

---

*Document generated: March 2026*
*Version: CCE v3 Phase 4*
