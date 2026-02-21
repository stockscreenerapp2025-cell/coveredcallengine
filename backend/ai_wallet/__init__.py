"""
AI Wallet Module
Token-based access control for AI features in Covered Call Engine

This module provides:
- Token wallet management (free + paid tokens)
- Usage tracking and ledger
- PayPal integration for token pack purchases
- Abuse prevention and rate limiting
- Concurrency-safe atomic deductions

Collections used (additive only - no schema modifications to existing collections):
- ai_wallet: User token balances
- ai_token_ledger: Immutable transaction log
- ai_purchases: Token pack purchase records
- paypal_events: Webhook idempotency store
- entitlements: Feature flags (ai.enabled)
"""

__version__ = "1.0.0"
