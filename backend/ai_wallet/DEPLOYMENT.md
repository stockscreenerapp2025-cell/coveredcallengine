# AI Wallet Deployment Guide

## Overview
This document provides deployment instructions for the AI Wallet & Token System.

## Required Environment Variables

Add these to your production `.env` file:

```bash
# PayPal Configuration (REQUIRED)
PAYPAL_ENV=live              # sandbox for testing, live for production
PAYPAL_CLIENT_ID=<your_client_id>
PAYPAL_SECRET=<your_secret>
PAYPAL_WEBHOOK_ID=<your_webhook_id>

# Application URL (REQUIRED)
PUBLIC_APP_URL=https://your-domain.com

# DB Init (optional - only needed when running db_init in production)
AI_WALLET_DB_INIT_ON_STARTUP=false
AI_WALLET_INIT_CONFIRM=YES   # Required ONLY when running db_init in production
APP_ENV=production           # or development
```

## PayPal Setup Instructions

### 1. Get PayPal Credentials

1. Go to https://developer.paypal.com/
2. Log in with your PayPal Business account
3. Navigate to Dashboard → My Apps & Credentials
4. Create a new REST API app (or use existing)
5. Copy Client ID and Secret for both Sandbox and Live

### 2. Configure Webhook

1. In PayPal Developer Dashboard, go to your app
2. Click "Add Webhook"
3. Enter your webhook URL: `https://your-domain.com/api/ai-wallet/webhook`
4. Select event type: `PAYMENT.CAPTURE.COMPLETED`
5. Copy the Webhook ID

## Deployment Steps

### VPS Production Deployment

```bash
# 1. Pull latest from GitHub
git pull origin main

# 2. Install dependencies
cd backend
pip install -r requirements.txt

# 3. Run DB init script (one-time, creates collections and indexes)
APP_ENV=production AI_WALLET_INIT_CONFIRM=YES python -m ai_wallet.db_init

# 4. Restart application
sudo supervisorctl restart backend
# OR if using PM2:
pm2 restart backend
# OR if using systemd:
sudo systemctl restart your-app.service
```

### Database Init Details

The `db_init.py` script:
- Creates new collections: `ai_wallet`, `ai_token_ledger`, `ai_purchases`, `paypal_events`, `entitlements`
- Creates required indexes with proper uniqueness constraints
- Is **idempotent** - safe to run multiple times
- Does **NOT** modify existing collections or data
- Requires `AI_WALLET_INIT_CONFIRM=YES` in production

To preview without making changes:
```bash
python -m ai_wallet.db_init --dry-run
```

## New Collections Created

| Collection | Purpose |
|------------|---------|
| `ai_wallet` | User token balances |
| `ai_token_ledger` | Immutable transaction log |
| `ai_purchases` | Token pack purchase records |
| `paypal_events` | Webhook idempotency store |
| `entitlements` | Feature flags (ai.enabled) |
| `ai_wallet_meta` | Init version tracking |

## API Endpoints Added

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/ai-wallet` | GET | Get wallet balance |
| `/api/ai-wallet/ledger` | GET | Get transaction history |
| `/api/ai-wallet/packs` | GET | Get available token packs |
| `/api/ai-wallet/estimate` | POST | Estimate token cost |
| `/api/ai-wallet/purchase/create` | POST | Create PayPal purchase |
| `/api/ai-wallet/webhook` | POST | PayPal webhook handler |
| `/api/ai-wallet/admin/stats` | GET | Admin: wallet stats |
| `/api/ai-wallet/admin/credit` | POST | Admin: credit tokens |

## Token Packs

| Pack | Tokens | Price |
|------|--------|-------|
| Starter | 5,000 | $10 |
| Power | 15,000 | $25 |
| Pro | 50,000 | $75 |

## Plan Free Token Grants

| Plan | Monthly Tokens |
|------|---------------|
| Basic | 2,000 |
| Standard | 6,000 |
| Premium | 15,000 |

## Verification Checklist

After deployment:

- [ ] `/api/ai-wallet` returns balance for authenticated users
- [ ] `/api/ai-wallet/packs` returns token pack list
- [ ] DB collections exist: `ai_wallet`, `ai_token_ledger`, etc.
- [ ] PayPal webhook endpoint responds to POST requests
- [ ] AI features deduct tokens correctly
- [ ] Insufficient tokens blocks AI execution (402 response)

## Rollback

If issues occur:

1. The AI Wallet module is additive - disabling it won't affect other features
2. Collections created are separate from existing data
3. To disable, remove the router include from `server.py`:
   ```python
   # Comment out this line:
   # api_router.include_router(ai_wallet_router)
   ```

## Security Notes

- PayPal webhook signature verification is enabled when `PAYPAL_WEBHOOK_ID` is set
- Tokens are deducted atomically to prevent race conditions
- All purchases use idempotency keys to prevent double-charging
- Admin endpoints require admin authentication
