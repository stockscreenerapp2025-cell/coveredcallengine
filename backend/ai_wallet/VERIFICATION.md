# AI Wallet Production Verification Document

## A) DB Init + "No New Database" Confirmation

### ✅ NO NEW DATABASE CREATED
The db_init.py script uses the **existing MongoDB connection** from environment variables:
```python
# /app/backend/ai_wallet/db_init.py lines 148-152
mongo_url = os.environ.get('MONGO_URL')
db_name = os.environ.get('DB_NAME')
...
client = AsyncIOMotorClient(mongo_url)
db = client[db_name]  # Uses EXISTING database
```

### Exact Command to Run on VPS:
```bash
# Production deployment (with confirmation)
APP_ENV=production AI_WALLET_INIT_CONFIRM=YES python -m ai_wallet.db_init

# Dry-run first (recommended - shows what will happen without changes)
python -m ai_wallet.db_init --dry-run
```

### Expected Output on Success:
```
2026-02-10 05:15:39 - INFO - Environment: production
2026-02-10 05:15:39 - INFO - Database: premium_hunter
2026-02-10 05:15:39 - INFO - Dry Run: False
2026-02-10 05:15:39 - INFO - MongoDB connection: OK

=== Collections ===
  [CREATE] Created collection 'ai_wallet'
  [CREATE] Created collection 'ai_token_ledger'
  [CREATE] Created collection 'ai_purchases'
  [CREATE] Created collection 'paypal_events'
  [CREATE] Created collection 'entitlements'
  [CREATE] Created collection 'ai_wallet_meta'

=== Indexes ===
  [CREATE] Created index 'idx_user_id_unique' on 'ai_wallet'
  [CREATE] Created index 'idx_org_id' on 'ai_wallet'
  ...

=== Version Stamp ===
  [UPDATE] Version stamp updated to v1.0.0

==================================================
SUCCESS: AI Wallet DB init completed
==================================================
```

### Idempotency Confirmation:
Running twice will show `[SKIP]` messages instead of `[CREATE]`:
```
  [SKIP] Collection 'ai_wallet' already exists
  [SKIP] Index 'idx_user_id_unique' on 'ai_wallet' already exists
```

### Non-Destructive Confirmation:
The script contains **NO** drop, delete, or truncate operations. Only:
- `create_collection()` with existence check
- `create_index()` with existence check
- Single upsert for version stamp

### Indexes Created:

| Collection | Index Name | Fields | Unique |
|------------|------------|--------|--------|
| `ai_wallet` | `idx_user_id_unique` | `user_id` | **YES** |
| `ai_wallet` | `idx_org_id` | `org_id` | No |
| `ai_token_ledger` | `idx_user_timestamp` | `user_id`, `timestamp` | No |
| `ai_token_ledger` | `idx_request_id` | `request_id` | No |
| `ai_purchases` | `idx_purchase_id_unique` | `purchase_id` | **YES** |
| `ai_purchases` | `idx_status_created` | `status`, `created_at` | No |
| `ai_purchases` | `idx_user_id` | `user_id` | No |
| `paypal_events` | `idx_event_id_unique` | `event_id` | **YES** |
| `paypal_events` | `idx_capture_id_unique` | `capture_id` | **YES** (sparse) |
| `entitlements` | `idx_entitlement_user_id` | `user_id` | **YES** (sparse) |
| `entitlements` | `idx_entitlement_org_id` | `org_id` | No |

---

## B) Atomic Deduction Proof (Negative Balances Impossible)

### Exact Conditional Update Query:
**Location:** `/app/backend/ai_wallet/wallet_service.py` lines 246-260

```python
# Calculate split: free first, then paid
free_to_use = min(free_available, tokens_required)
paid_to_use = tokens_required - free_to_use

# Atomic deduction with conditional update
result = await self.db.ai_wallet.update_one(
    {
        "user_id": user_id,
        "free_tokens_remaining": {"$gte": free_to_use},   # MUST have enough free
        "paid_tokens_remaining": {"$gte": paid_to_use}    # MUST have enough paid
    },
    {
        "$inc": {
            "free_tokens_remaining": -free_to_use,
            "paid_tokens_remaining": -paid_to_use,
            "monthly_used": tokens_required
        },
        "$set": {"updated_at": now.isoformat()}
    }
)
```

### Why Negative Balances Are Impossible:
1. The `$gte` predicates in the query ensure the document is **only matched if sufficient balance exists**
2. MongoDB's `update_one` with conditional predicates is **atomic** - if another request modifies the document between read and write, the predicate fails and `modified_count == 0`
3. On `modified_count == 0`, we retry once with fresh balance check
4. If retry also fails, we return `INSUFFICIENT_TOKENS` error

### Token Consumption Order (Free First, Then Paid):
```python
# Lines 238-240
free_to_use = min(free_available, tokens_required)  # Take from free first
paid_to_use = tokens_required - free_to_use         # Remainder from paid
```

### Ledger Records Breakdown:
```python
# Lines 268-277
await self._write_ledger_entry(
    user_id=user_id,
    action=action,
    tokens_total=-tokens_required,
    free_tokens=-free_to_use,      # Breakdown: free tokens used
    paid_tokens=-paid_to_use,      # Breakdown: paid tokens used
    source="usage",
    request_id=request_id,
    ...
)
```

### Concurrency Limit + Atomic Updates:
**Location:** `/app/backend/ai_wallet/guard.py`

1. **Concurrency limit (1 per user):** Enforced via in-memory lock at lines 254-262
2. **Atomic updates still exist:** Even with concurrency=1, the conditional MongoDB update provides defense-in-depth for multi-tab/multi-instance scenarios
3. **Multi-tab safe:** If user opens 2 tabs and clicks simultaneously:
   - First request acquires concurrency lock → succeeds
   - Second request blocked by concurrency lock → returns `CONCURRENCY_LIMIT` error

---

## C) PayPal Webhooks (Security + Idempotency)

### ✅ Webhook Signature Verification IMPLEMENTED:
**Location:** `/app/backend/ai_wallet/paypal_service.py` lines 208-265

```python
async def verify_webhook_signature(self, headers: Dict, body: bytes) -> bool:
    # Extract PayPal signature headers
    transmission_id = headers.get("paypal-transmission-id", "")
    transmission_sig = headers.get("paypal-transmission-sig", "")
    ...
    
    # Call PayPal's verification API
    response = await client.post(
        f"{self.api_base}/v1/notifications/verify-webhook-signature",
        headers={"Authorization": f"Bearer {access_token}"},
        json=verification_data
    )
    
    result = response.json()
    return result.get("verification_status") == "SUCCESS"
```

### Tokens Credited ONLY on PAYMENT.CAPTURE.COMPLETED:
**Location:** `/app/backend/ai_wallet/paypal_service.py` lines 294-297
```python
# Only process capture completed events
if event_type != PAYPAL_CAPTURE_COMPLETED_EVENT:  # "PAYMENT.CAPTURE.COMPLETED"
    logger.info(f"Ignoring event type: {event_type}")
    return True, f"Event type {event_type} ignored"
```

### Credit Requires All Validations:
**Location:** Lines 303-356

| Validation | Code |
|------------|------|
| Currency == USD | `if currency != "USD": return False` |
| Amount matches pack price | `if abs(amount_value - expected_amount) > 0.01: return False` |
| Purchase exists server-side | `purchase = await self.db.ai_purchases.find_one({"purchase_id": purchase_id})` |
| Status not completed | `if purchase.get("status") == "completed": return True, "Already completed"` |

### Idempotency (No Double-Credit):
**Location:** Lines 288-292 + Lines 358-374

1. **Check if already processed:**
```python
existing = await self.db.paypal_events.find_one({"event_id": event_id})
if existing and existing.get("processed"):
    return True, "Event already processed"
```

2. **Store event BEFORE crediting:**
```python
await self.db.paypal_events.update_one(
    {"event_id": event_id},
    {"$set": {"event_id": event_id, "capture_id": capture_id, "processed": False}},
    upsert=True
)
```

3. **Unique indexes block duplicates:**
- `event_id` has unique index
- `capture_id` has unique index (sparse)

### Webhook Endpoint Path:
**Location:** `/app/backend/ai_wallet/routes.py` lines 166-200

```
POST /api/ai-wallet/webhook
```

**Full URL for PayPal configuration:**
```
https://your-domain.com/api/ai-wallet/webhook
```

**Routing wired in:** `/app/backend/server.py`
```python
api_router.include_router(ai_wallet_router)  # AI Wallet: Token purchases & balance
```

---

## D) Plan Detection

### Source of Truth:
**Collection:** `users`
**Field:** `subscription.plan`

**Location:** `/app/backend/ai_wallet/plan_resolver.py` lines 37-79

```python
# Fetch user document
user = await db.users.find_one({"id": user_id}, {"_id": 0, "subscription": 1})
...
# Get the plan from subscription
plan = subscription.get("plan", "").lower()

# Normalize plan names
plan_mapping = {
    "basic": "basic",
    "standard": "standard",
    "premium": "premium",
    "trial": "trial",
    "monthly": "standard",  # Legacy mapping
    "yearly": "standard",
}
```

### Plans Affect ONLY Free Monthly Grant:
```python
PLAN_FREE_TOKENS = {
    "basic": 2000,
    "standard": 6000,
    "premium": 15000,
    "trial": 2000,
    "default": 2000
}
```

### AI Access Controlled Separately via Entitlements:
**Location:** `/app/backend/ai_wallet/wallet_service.py` lines 346-357

```python
async def is_ai_enabled(self, user_id: str) -> bool:
    """Check if AI features are enabled for user."""
    entitlement = await self.db.entitlements.find_one(
        {"user_id": user_id},
        {"_id": 0, "ai_enabled": 1}
    )
    if entitlement:
        return entitlement.get("ai_enabled", True)
    # Default: AI enabled for all users
    return True
```

---

## E) Scope Control (Scanner/Yahoo Finance Untouched)

### Files Changed OUTSIDE `/backend/ai_wallet/`:

| File | Change | Impact |
|------|--------|--------|
| `/app/backend/server.py` | Added 2 lines: import + router include | Routing only |
| `/app/backend/routes/portfolio.py` | Updated AI suggestion endpoint | Uses AIExecutionService |
| `/app/backend/routes/ai.py` | Updated analyze endpoint | Uses AIExecutionService |
| `/app/backend/.env` | Added PayPal env vars | Config only |

### Files Changed in Frontend:

| File | Change |
|------|--------|
| `/app/frontend/src/pages/AIWallet.js` | NEW - Wallet page |
| `/app/frontend/src/components/BuyTokensModal.js` | NEW - Purchase modal |
| `/app/frontend/src/components/AIUsageHistoryModal.js` | NEW - History modal |
| `/app/frontend/src/components/AITokenUsageModal.js` | NEW - Confirmation modal |
| `/app/frontend/src/components/Layout.js` | Added "AI Wallet" nav item |
| `/app/frontend/src/pages/Pricing.js` | Added AI Credits section |
| `/app/frontend/src/pages/Landing.js` | Updated pricing + AI credits |
| `/app/frontend/src/App.js` | Added /ai-wallet route |

### Scanner & Yahoo Finance Files NOT MODIFIED:
- ❌ `/app/backend/routes/screener_snapshot.py` - UNCHANGED
- ❌ `/app/backend/services/data_provider.py` - UNCHANGED
- ❌ `/app/backend/services/precomputed_scans.py` - UNCHANGED
- ❌ `/app/backend/routes/stocks.py` - UNCHANGED
- ❌ `/app/backend/routes/options.py` - UNCHANGED

### Support Dashboard NOT MODIFIED:
- ❌ `/app/backend/routes/admin.py` - UNCHANGED (existing inbound email issue predates this work)

---

## F) Production Deploy Checklist

### Required Environment Variables:

```bash
# PayPal (REQUIRED for token purchases)
PAYPAL_ENV=sandbox          # Change to 'live' for production
PAYPAL_CLIENT_ID=<your_id>
PAYPAL_SECRET=<your_secret>
PAYPAL_WEBHOOK_ID=<your_webhook_id>

# Application
PUBLIC_APP_URL=https://your-domain.com

# DB Init (optional - for init script only)
AI_WALLET_DB_INIT_ON_STARTUP=false
AI_WALLET_INIT_CONFIRM=YES  # Required when running db_init in production
APP_ENV=production
```

### Smoke Test Steps After Deploy:

#### 1. Create Wallet on First Use
```bash
TOKEN=$(curl -s -X POST "https://your-domain.com/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"..."}' | jq -r '.access_token')

curl -s "https://your-domain.com/api/ai-wallet" \
  -H "Authorization: Bearer $TOKEN"
```
**Expected:** Returns wallet with `free_tokens_remaining: 2000` (or per plan)

#### 2. Estimate → Confirm → Deduct → Ledger Entry
```bash
# Estimate
curl -s -X POST "https://your-domain.com/api/ai-wallet/estimate" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action":"ai_analysis"}'
# Expected: {"estimated_tokens": 200, "current_balance": 2000, "sufficient_tokens": true}

# Execute AI (deducts tokens)
curl -s -X POST "https://your-domain.com/api/ai/analyze" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"AAPL","analysis_type":"covered_call"}'
# Expected: {"tokens_used": 200, "remaining_balance": 1800, ...}

# Check ledger
curl -s "https://your-domain.com/api/ai-wallet/ledger?limit=5" \
  -H "Authorization: Bearer $TOKEN"
# Expected: Entry with action="ai_analysis", tokens_total=-200, source="usage"
```

#### 3. Insufficient Tokens Block + Upsell
```bash
# Drain tokens to 0, then try AI
# Expected: HTTP 402 with {"error_code": "INSUFFICIENT_TOKENS", "remaining_balance": 0}
```

#### 4. Webhook Replay Idempotency Test
```bash
# Send same webhook event twice (simulate)
# First call: Tokens credited
# Second call: Returns "Event already processed" (no double credit)
```

---

## Summary

| Item | Status |
|------|--------|
| A) No new database | ✅ Uses existing DB connection |
| A) db_init idempotent | ✅ Safe to run multiple times |
| A) All required indexes | ✅ See index table above |
| B) Atomic deduction | ✅ Conditional MongoDB update |
| B) Free first, then paid | ✅ `min(free_available, required)` |
| B) Concurrency=1 | ✅ In-memory lock + atomic fallback |
| C) Webhook signature verification | ✅ PayPal API verification |
| C) PAYMENT.CAPTURE.COMPLETED only | ✅ Event type filter |
| C) USD + amount + purchase validation | ✅ All checks present |
| C) Idempotency | ✅ Unique indexes + processed flag |
| D) Plan source of truth | ✅ `users.subscription.plan` |
| D) Plans ≠ AI access | ✅ Separate entitlements collection |
| E) Scanner untouched | ✅ No modifications |
| E) Yahoo Finance untouched | ✅ No modifications |
