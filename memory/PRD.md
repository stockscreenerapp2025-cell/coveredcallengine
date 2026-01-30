# Covered Call Engine - Product Requirements Document

## Original Problem Statement
Build a web-based application named "Covered Call Engine" for options traders with AI-assisted Covered Call (CC) and Poor Man's Covered Call (PMCC) screeners.

## CRITICAL: YAHOO FINANCE IS THE SINGLE SOURCE OF TRUTH

### Stock Price Source (ALL PAGES)
- **Source**: Yahoo Finance `ticker.history(period='5d')` - most recent market close
- **NOT**: previousClose (which is prior day's close)
- **NOT**: EOD contract or cached prices
- **Applies to**: Dashboard, Screener, PMCC, Simulator, Watchlist

### Options Chain Source
- **Source**: Yahoo Finance live options chain
- **Pricing Rules**:
  - SELL legs: BID only (reject if BID=0)
  - BUY legs: ASK only (reject if ASK=0)
  - NEVER use: lastPrice, mid, theoretical price

### Market Indices
- **Source**: Yahoo Finance history() via ETF proxies (SPY, QQQ, DIA, IWM)
- **Works**: After hours, weekends

### Analyst Ratings
- **Source**: Yahoo Finance `ticker.info.recommendationKey`
- **Mapping**: strong_buy→Strong Buy, buy→Buy, hold→Hold, etc.

---

## Validation Evidence (2026-01-29)

| Metric | Yahoo Finance | System | Status |
|--------|---------------|--------|--------|
| INTC Price | $48.66 | $48.66 | ✅ MATCH |
| HAL Price | $33.39 | $33.39 | ✅ MATCH |
| SPY Index | $694.04 | $694.04 | ✅ MATCH |
| CC Results | N/A | 12 opportunities | ✅ POPULATED |
| PMCC Results | N/A | 27 opportunities | ✅ POPULATED |
| Weekly+Monthly | N/A | 2+5=7 | ✅ WORKING |
| Analyst Ratings | N/A | 8/10 have ratings | ✅ WORKING |

---

## Architecture

```
YAHOO_SINGLE_SOURCE_OF_TRUTH
├── Stock Prices: ticker.history(period='5d') → most recent close
├── Options Chain: ticker.option_chain(expiry) → live BID/ASK
├── Analyst Rating: ticker.info.recommendationKey
├── Market Cap: ticker.info.marketCap
├── Avg Volume: ticker.info.averageVolume
└── Market Indices: ETF history (SPY, QQQ, DIA, IWM)
```

---

## Key Files

### Data Provider (SINGLE SOURCE OF TRUTH)
- `/app/backend/services/data_provider.py`:
  - `_fetch_stock_quote_yahoo_sync()` - Uses history() for last market close
  - `fetch_options_chain()` - Live options from Yahoo
  - `fetch_live_stock_quote()` - Live intraday price (Watchlist/Simulator)

### Routes Using Single Source
- `/app/backend/routes/screener_snapshot.py` - CC/PMCC screeners
- `/app/backend/routes/stocks.py` - Market indices
- `/app/backend/routes/watchlist.py` - Watchlist
- `/app/backend/routes/simulator.py` - Simulator

---

## Test Credentials
- **Admin Email**: admin@premiumhunter.com
- **Password**: admin123

---

## Last Updated
2026-01-30 - Yahoo Finance Single Source of Truth implementation
