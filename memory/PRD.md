# Covered Call Engine - Product Requirements Document

## Last Updated
2026-02-10 - AI Wallet & Token System COMPLETE (Deployment On Hold)

---

## AI Wallet & Token System - COMPLETED & APPROVED 2026-02-10

### Status: ✅ APPROVED - DEPLOYMENT ON HOLD (User Decision)

### Objective:
Token-based access control for AI features with PayPal integration for token purchases.

### Pricing (Final Approved):
| Plan | Monthly | Yearly | AI Tokens |
|------|---------|--------|-----------|
| Basic | $29 | $290 | 2,000/mo |
| Standard | $59 | $590 | 6,000/mo |
| Premium | $89 | $890 | 15,000/mo |

### Token Packs:
| Pack | Tokens | Price |
|------|--------|-------|
| Starter | 5,000 | $10 |
| Power | 15,000 | $25 |
| Pro | 50,000 | $75 |

### Key Features Implemented:
1. ✅ Token Wallet - Free + Paid tokens per user
2. ✅ Monthly Reset - Free tokens aligned to billing cycle (expire on reset)
3. ✅ Paid Tokens - Never expire, purchased via PayPal
4. ✅ AI Guard - Atomic deduction with $gte predicates (negative balances impossible)
5. ✅ Rate Limiting - Max 10 calls/minute, 2000 tokens/action
6. ✅ Concurrency Control - One AI call at a time per user
7. ✅ Ledger - Immutable transaction log with free/paid breakdown
8. ✅ PayPal Integration - Webhook-only crediting with signature verification
9. ✅ Retry Limit - Max 1 retry on race condition
10. ✅ Production Safety - Webhook verification hard-fails if PAYPAL_WEBHOOK_ID missing in live mode

### New Collections (Additive-Only):
- `ai_wallet` - User token balances (unique user_id index)
- `ai_token_ledger` - Immutable transaction log
- `ai_purchases` - Token pack purchase records (unique purchase_id index)
- `paypal_events` - Webhook idempotency (unique event_id + capture_id indexes)
- `entitlements` - Feature flags

### New API Endpoints:
- `GET /api/ai-wallet` - Get wallet balance
- `GET /api/ai-wallet/ledger` - Get transaction history
- `GET /api/ai-wallet/packs` - Get token packs
- `POST /api/ai-wallet/estimate` - Estimate token cost
- `POST /api/ai-wallet/purchase/create` - Create PayPal purchase
- `POST /api/ai-wallet/webhook` - PayPal webhook handler

### Frontend Components:
- `AIWallet.js` - Wallet balance page
- `BuyTokensModal.js` - Token purchase modal
- `AIUsageHistoryModal.js` - Transaction history modal
- `AITokenUsageModal.js` - Pre-execution confirmation modal
- Updated `Pricing.js` - $29/$59/$89 with AI tokens, Monthly/Yearly toggle
- Updated `Landing.js` - Updated pricing display

### Hard Constraints Met:
- ✅ Scanner engine untouched
- ✅ Yahoo Finance unchanged
- ✅ No AI without prepaid tokens
- ✅ No negative balances (atomic MongoDB $gte conditional updates)
- ✅ No post-paid billing
- ✅ USD only
- ✅ Additive-only changes (new files + new collections)
- ✅ Webhook signature verification required in production
- ✅ Max 1 retry on deduction race condition

### Deploy Commands (When Ready):
```bash
git pull origin main
cd backend && pip install -r requirements.txt
APP_ENV=production AI_WALLET_INIT_CONFIRM=YES python -m ai_wallet.db_init
sudo supervisorctl restart backend
```

### Required Env Vars for Production:
```
PAYPAL_ENV=live
PAYPAL_CLIENT_ID=<your_id>
PAYPAL_SECRET=<your_secret>
PAYPAL_WEBHOOK_ID=<your_webhook_id>
PUBLIC_APP_URL=https://your-domain.com
```

---

## Phase 3 - COMPLETED 2025-12

### AI-Based Best Option Selection per Symbol
- Implemented deduplication logic showing only the single best option per stock
- Applied to all custom scans and precomputed scans
- Selection based on AI score, quality score, and ROI

---

## Phase 2 - COMPLETED 2025-12

### MongoDB Caching Layer
- Implemented `market_snapshot_cache` collection
- 10-15 minute TTL during market hours
- ~40% performance improvement on custom scans
- `/api/admin/cache/health` endpoint added

---

## Phase 1 - COMPLETED 2025-12

### Data Provider Centralization
- Eliminated Polygon API dependencies
- Centralized data fetching through `data_provider.py`
- Yahoo Finance as primary data source

---

## CCE Volatility & Greeks Correctness - COMPLETED 2026-02-11

### Status: ✅ COMPLETE

### Objective:
Standardize IV and Delta calculations across all endpoints using industry-standard formulas. Remove inaccurate moneyness-based delta fallbacks. Implement true IV Rank and IV Percentile using historical IV proxy data.

### Key Changes:
1. ✅ **Delta via Black-Scholes** - All delta calculations now use Black-Scholes formula
   - Removed moneyness-based delta fallback (accuracy and consistency)
   - Delta source field: `delta_source = "BS"` or `"BS_PROXY_SIGMA"`
   - Delta bounds enforced: calls [0, 1], puts [-1, 0]
   
2. ✅ **IV Normalization** - Consistent across all endpoints
   - `iv` = decimal form (e.g., 0.30)
   - `iv_pct` = percentage form (e.g., 30.0)
   - Invalid IV (< 0.01 or > 5.0) rejected

3. ✅ **Industry-Standard IV Rank** - True historical calculation
   - Formula: `iv_rank = 100 * (iv_current - iv_low) / (iv_high - iv_low)`
   - Requires 20+ historical samples for true calculation
   - Neutral fallback (50) when insufficient history
   
4. ✅ **IV Percentile** - Distribution-based metric
   - Formula: `iv_percentile = 100 * count(iv_hist < iv_current) / N`
   
5. ✅ **IV History Storage** - New collection with TTL
   - Collection: `iv_history`
   - Stores daily ATM proxy IV per symbol
   - TTL: 450 days auto-expiry
   - Indexes: unique (symbol, trading_date)

### API Response Fields (All endpoints):
| Field | Type | Description |
|-------|------|-------------|
| delta | float | Black-Scholes delta |
| delta_source | string | "BS", "BS_PROXY_SIGMA", "EXPIRY", "MISSING" |
| gamma, theta, vega | float | Black-Scholes Greeks |
| iv | float | IV decimal (0.30 = 30%) |
| iv_pct | float | IV percentage (30.0) |
| iv_rank | float | Industry-standard IV Rank (0-100) |
| iv_percentile | float | IV Percentile (0-100) |
| iv_rank_source | string | Source/quality indicator |
| iv_samples | int | Number of historical samples used |

### Files Created:
- `/backend/services/greeks_service.py` - Black-Scholes Greeks calculation
- `/backend/services/iv_rank_service.py` - IV history and rank/percentile
- `/backend/services/option_normalizer.py` - Shared field normalization helper
- `/backend/tests/test_iv_rank_service.py` - 25 unit tests

### Files Modified:
- `/backend/routes/screener_snapshot.py` - Custom scan with IV metrics
- `/backend/routes/options.py` - Options chain endpoint with normalized fields
- `/backend/routes/watchlist.py` - Watchlist with IV metrics integration
- `/backend/routes/simulator.py` - Delegated Greeks to shared service
- `/backend/routes/admin.py` - IV metrics verification endpoints
- `/backend/services/precomputed_scans.py` - Black-Scholes delta
- `/backend/server.py` - IV history index creation at startup

### Endpoints Updated with New Fields:
1. **GET /api/options/chain/{symbol}** - Options chain with per-option and symbol-level IV metrics
2. **GET /api/screener/covered-calls** - Custom scan with Black-Scholes delta and IV rank
3. **GET /api/screener/pmcc** - PMCC scan with Black-Scholes delta
4. **GET /api/watchlist/** - Watchlist items with best_opportunity containing all fields
5. **GET /api/simulator/trades** - Simulator trades using shared Greeks service

### Admin Verification Endpoints:
- `GET /api/admin/iv-metrics/check/{symbol}` - Full IV/Greeks sanity check
- `GET /api/admin/iv-metrics/stats` - IV history collection statistics
- `GET /api/admin/iv-metrics/completeness-test` - Field completeness validation

### ENV Configuration:
- `RISK_FREE_RATE` - Optional, default 0.045 (4.5%), bounds [0.001, 0.20]

---

## Pending Issues (Pre-existing)

| Issue | Priority | Status |
|-------|----------|--------|
| Inbound email replies not appearing in support dashboard | P3 | Recurring |
| LLM rate limiting safeguards | P2 | Addressed by AI Wallet guard |

---

## Future/Backlog

- (P3) Frontend refactor - break down `Simulator.js` (2,200+ lines)
- (P4) Backend refactor - split `simulator.py` (2,800+ lines)
- (P4) Consolidate `precomputed_scans.py` to fully use `data_provider.py`

