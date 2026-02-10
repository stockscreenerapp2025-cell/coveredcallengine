"""
AI Wallet API Routes

Endpoints:
- GET /api/ai-wallet - Get wallet balance and info
- GET /api/ai-wallet/ledger - Get transaction history
- POST /api/ai-wallet/estimate - Estimate token cost
- POST /api/ai-wallet/purchase/create - Create token purchase
- POST /api/ai-wallet/webhook - PayPal webhook handler
"""

import os
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, Field

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import db
from utils.auth import get_current_user, get_admin_user
from ai_wallet.wallet_service import WalletService
from ai_wallet.paypal_service import PayPalTokenService
from ai_wallet.config import TOKEN_PACKS, AI_ACTION_COSTS
from ai_wallet.models import (
    AIWalletResponse,
    TokenEstimateRequest,
    TokenEstimateResponse,
    PurchaseCreateRequest,
    PurchaseCreateResponse
)

logger = logging.getLogger(__name__)

ai_wallet_router = APIRouter(prefix="/ai-wallet", tags=["AI Wallet"])


# ==================== WALLET ENDPOINTS ====================

@ai_wallet_router.get("", response_model=AIWalletResponse)
async def get_wallet(user: dict = Depends(get_current_user)):
    """
    Get current user's AI wallet balance and information.
    
    Returns:
        Wallet balance, plan info, next reset date, AI enabled status
    """
    wallet_service = WalletService(db)
    return await wallet_service.get_wallet_response(user["id"])


@ai_wallet_router.get("/ledger")
async def get_ledger(
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(get_current_user)
):
    """
    Get AI token usage history (ledger entries).
    
    Shows all token transactions: usage, purchases, grants, reversals.
    """
    wallet_service = WalletService(db)
    entries = await wallet_service.get_ledger(user["id"], limit)
    
    return {
        "entries": entries,
        "count": len(entries)
    }


@ai_wallet_router.post("/estimate", response_model=TokenEstimateResponse)
async def estimate_tokens(
    request: TokenEstimateRequest,
    user: dict = Depends(get_current_user)
):
    """
    Estimate token cost for an AI action.
    
    Call this before confirming an AI action to show user the cost.
    Does NOT deduct any tokens.
    """
    from ai_wallet.guard import AIGuard
    
    guard = AIGuard(db)
    return await guard.estimate(user["id"], request.action, request.params)


# ==================== TOKEN PACK INFO ====================

@ai_wallet_router.get("/packs")
async def get_token_packs():
    """
    Get available token packs for purchase.
    
    Returns all packs with pricing and token amounts.
    """
    return {
        "packs": [
            {
                "id": pack_id,
                **pack_info
            }
            for pack_id, pack_info in TOKEN_PACKS.items()
        ],
        "currency": "USD"
    }


@ai_wallet_router.get("/actions")
async def get_action_costs():
    """
    Get token costs for different AI actions.
    
    Useful for frontend to show users estimated costs.
    """
    return {
        "actions": AI_ACTION_COSTS
    }


# ==================== PURCHASE ENDPOINTS ====================

class PurchaseCreateBody(BaseModel):
    pack_id: str = Field(..., description="Token pack ID: starter, power, or pro")
    return_url: Optional[str] = None
    cancel_url: Optional[str] = None


@ai_wallet_router.post("/purchase/create")
async def create_purchase(
    body: PurchaseCreateBody,
    user: dict = Depends(get_current_user)
):
    """
    Create a token pack purchase and get PayPal approval URL.
    
    Flow:
    1. Create internal purchase record
    2. Create PayPal order
    3. Return approval URL for redirect
    
    User completes purchase on PayPal, then webhook credits tokens.
    """
    pack_id = body.pack_id
    
    # Validate pack
    if pack_id not in TOKEN_PACKS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid pack_id. Valid options: {list(TOKEN_PACKS.keys())}"
        )
    
    pack = TOKEN_PACKS[pack_id]
    now = datetime.now(timezone.utc)
    purchase_id = str(uuid.uuid4())
    
    # Get base URL for return/cancel
    base_url = os.environ.get("PUBLIC_APP_URL", "")
    if not base_url:
        # Try to construct from request or use default
        base_url = os.environ.get("REACT_APP_BACKEND_URL", "https://localhost:3000")
    
    return_url = body.return_url or f"{base_url}/ai-wallet?purchase=success&id={purchase_id}"
    cancel_url = body.cancel_url or f"{base_url}/ai-wallet?purchase=cancelled"
    
    # Create internal purchase record
    purchase_doc = {
        "purchase_id": purchase_id,
        "user_id": user["id"],
        "pack_id": pack_id,
        "expected_amount_usd": pack["price_usd"],
        "expected_tokens": pack["tokens"],
        "status": "created",
        "created_at": now.isoformat()
    }
    
    await db.ai_purchases.insert_one(purchase_doc)
    
    # Create PayPal order
    paypal_service = PayPalTokenService(db)
    
    try:
        result = await paypal_service.create_order(
            user_id=user["id"],
            pack_id=pack_id,
            purchase_id=purchase_id,
            return_url=return_url,
            cancel_url=cancel_url
        )
        
        # Update purchase with PayPal order ID
        await db.ai_purchases.update_one(
            {"purchase_id": purchase_id},
            {"$set": {"paypal_order_id": result["order_id"]}}
        )
        
        return {
            "purchase_id": purchase_id,
            "pack_id": pack_id,
            "amount_usd": pack["price_usd"],
            "tokens": pack["tokens"],
            "paypal_order_id": result["order_id"],
            "approval_url": result["approval_url"]
        }
        
    except Exception as e:
        # Mark purchase as failed
        await db.ai_purchases.update_one(
            {"purchase_id": purchase_id},
            {"$set": {"status": "failed", "error_message": str(e)}}
        )
        
        logger.error(f"PayPal order creation failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create PayPal order: {str(e)}"
        )


@ai_wallet_router.get("/purchase/{purchase_id}")
async def get_purchase_status(
    purchase_id: str,
    user: dict = Depends(get_current_user)
):
    """Get status of a token purchase."""
    purchase = await db.ai_purchases.find_one(
        {"purchase_id": purchase_id, "user_id": user["id"]},
        {"_id": 0}
    )
    
    if not purchase:
        raise HTTPException(status_code=404, detail="Purchase not found")
    
    return purchase


# ==================== PAYPAL WEBHOOK ====================

@ai_wallet_router.post("/webhook")
async def paypal_webhook(request: Request):
    """
    Handle PayPal webhook notifications.
    
    This endpoint is called by PayPal when payment events occur.
    Tokens are credited only on PAYMENT.CAPTURE.COMPLETED with valid signature.
    """
    body = await request.body()
    headers = dict(request.headers)
    
    paypal_service = PayPalTokenService(db)
    
    # Verify signature (in production)
    if os.environ.get("PAYPAL_WEBHOOK_ID"):
        is_valid = await paypal_service.verify_webhook_signature(headers, body)
        if not is_valid:
            logger.warning("Invalid PayPal webhook signature")
            raise HTTPException(status_code=401, detail="Invalid signature")
    
    # Parse webhook data
    import json
    data = json.loads(body.decode())
    
    event_id = data.get("id")
    event_type = data.get("event_type")
    resource = data.get("resource", {})
    
    logger.info(f"Received PayPal webhook: {event_type} (event_id={event_id})")
    
    # Process the webhook
    success, message = await paypal_service.process_webhook(
        event_id=event_id,
        event_type=event_type,
        resource=resource
    )
    
    if not success:
        logger.error(f"Webhook processing failed: {message}")
        # Still return 200 to acknowledge receipt
    
    return {"status": "received", "message": message}


# ==================== ADMIN ENDPOINTS ====================

@ai_wallet_router.get("/admin/stats")
async def get_wallet_stats(admin: dict = Depends(get_admin_user)):
    """Get aggregate wallet statistics (admin only)."""
    # Total wallets
    total_wallets = await db.ai_wallet.count_documents({})
    
    # Total tokens purchased (from ledger)
    pipeline = [
        {"$match": {"source": "purchase"}},
        {"$group": {"_id": None, "total": {"$sum": "$tokens_total"}}}
    ]
    purchase_result = await db.ai_token_ledger.aggregate(pipeline).to_list(1)
    total_purchased = purchase_result[0]["total"] if purchase_result else 0
    
    # Total tokens used
    usage_pipeline = [
        {"$match": {"source": "usage"}},
        {"$group": {"_id": None, "total": {"$sum": {"$abs": "$tokens_total"}}}}
    ]
    usage_result = await db.ai_token_ledger.aggregate(usage_pipeline).to_list(1)
    total_used = usage_result[0]["total"] if usage_result else 0
    
    # Purchases by status
    purchase_stats = await db.ai_purchases.aggregate([
        {"$group": {"_id": "$status", "count": {"$sum": 1}}}
    ]).to_list(10)
    
    return {
        "total_wallets": total_wallets,
        "total_tokens_purchased": total_purchased,
        "total_tokens_used": total_used,
        "purchases_by_status": {s["_id"]: s["count"] for s in purchase_stats}
    }


@ai_wallet_router.post("/admin/credit")
async def admin_credit_tokens(
    user_id: str = Query(..., description="User ID to credit"),
    tokens: int = Query(..., ge=1, description="Tokens to credit"),
    reason: str = Query("admin_grant", description="Reason for credit"),
    admin: dict = Depends(get_admin_user)
):
    """Manually credit tokens to a user (admin only)."""
    wallet_service = WalletService(db)
    
    await wallet_service.credit_tokens(
        user_id=user_id,
        tokens=tokens,
        source="grant",
        request_id=str(uuid.uuid4()),
        details={"reason": reason, "admin": admin["email"]}
    )
    
    return {
        "success": True,
        "message": f"Credited {tokens} tokens to user {user_id}"
    }


@ai_wallet_router.post("/admin/set-ai-enabled")
async def admin_set_ai_enabled(
    user_id: str = Query(..., description="User ID"),
    enabled: bool = Query(..., description="Enable/disable AI"),
    admin: dict = Depends(get_admin_user)
):
    """Enable or disable AI features for a user (admin only)."""
    wallet_service = WalletService(db)
    await wallet_service.set_ai_enabled(user_id, enabled)
    
    return {
        "success": True,
        "message": f"AI {'enabled' if enabled else 'disabled'} for user {user_id}"
    }
