# backend/services/wallet_service.py
"""
Wallet service for billing AI management actions.
Uses the existing 'ai_wallet' collection in MongoDB.

Usage:
    from services.wallet_service import debit_wallet, get_balance, MANAGE_COST_CREDITS

Wallet document structure (ai_wallet collection):
    { user_id, balance_credits, updated_at }

Transaction document structure (ai_token_ledger collection):
    { user_id, amount, reason, ref_id, created_at, balance_after }
"""

from datetime import datetime, timezone
from bson import ObjectId


# ── Cost constants ──────────────────────────────────────────────────
MANAGE_COST_CREDITS = 5        # credits charged per "manage" call
APPLY_COST_CREDITS  = 2        # extra credits charged when user applies a recommendation
FREE_BALANCE_ON_SIGNUP = 50    # credits given to new users (handled elsewhere)


# ── Public API ──────────────────────────────────────────────────────

async def get_balance(db, user_id: str) -> int:
    """Return current credit balance for user. Returns 0 if wallet not found."""
    doc = await db.ai_wallet.find_one({"user_id": user_id})
    return int(doc.get("balance_credits", 0)) if doc else 0


async def debit_wallet(db, user_id: str, amount: int, reason: str, ref_id: str = None) -> dict:
    """
    Debit 'amount' credits from user's wallet atomically.

    Returns:
        { "success": True, "balance_after": int }
      or
        { "success": False, "error": "insufficient_credits", "balance": int }
    """
    # Atomic find-and-update: only deduct if balance >= amount
    result = await db.ai_wallet.find_one_and_update(
        {"user_id": user_id, "balance_credits": {"$gte": amount}},
        {
            "$inc": {"balance_credits": -amount},
            "$set": {"updated_at": datetime.now(timezone.utc)}
        },
        return_document=True  # return updated doc
    )

    if not result:
        # Either wallet doesn't exist or insufficient funds
        current = await get_balance(db, user_id)
        return {"success": False, "error": "insufficient_credits", "balance": current}

    balance_after = int(result["balance_credits"])

    # Write audit entry to ledger
    await db.ai_token_ledger.insert_one({
        "user_id": user_id,
        "amount": -amount,
        "reason": reason,
        "ref_id": ref_id,
        "created_at": datetime.now(timezone.utc),
        "balance_after": balance_after
    })

    return {"success": True, "balance_after": balance_after}


async def credit_wallet(db, user_id: str, amount: int, reason: str, ref_id: str = None) -> dict:
    """
    Credit 'amount' to user's wallet. Creates wallet if not exists.
    Used for refunds or welcome bonuses.
    """
    result = await db.ai_wallet.find_one_and_update(
        {"user_id": user_id},
        {
            "$inc": {"balance_credits": amount},
            "$set": {"updated_at": datetime.now(timezone.utc)},
            "$setOnInsert": {"created_at": datetime.now(timezone.utc)}
        },
        upsert=True,
        return_document=True
    )

    balance_after = int(result["balance_credits"])

    await db.ai_token_ledger.insert_one({
        "user_id": user_id,
        "amount": amount,
        "reason": reason,
        "ref_id": ref_id,
        "created_at": datetime.now(timezone.utc),
        "balance_after": balance_after
    })

    return {"success": True, "balance_after": balance_after}


async def ensure_wallet_exists(db, user_id: str, starter_credits: int = 0):
    """Create wallet for new user if it doesn't exist yet."""
    await db.ai_wallet.update_one(
        {"user_id": user_id},
        {
            "$setOnInsert": {
                "user_id": user_id,
                "balance_credits": starter_credits,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc)
            }
        },
        upsert=True
    )
