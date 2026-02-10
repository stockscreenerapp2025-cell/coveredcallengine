"""
AI Wallet Database Initialization Script

MANDATORY RULES (from spec):
1. Environment Guard - requires APP_ENV and AI_WALLET_INIT_CONFIRM=YES for production
2. Idempotent - running multiple times must not duplicate anything
3. No destructive operations - no dropping, deleting, truncation
4. Lazy wallet creation - wallets created on first use, not here
5. Safe index creation - handles "index already exists" gracefully
6. Logging - prints environment, DB name, collections, indexes
7. Dry-run mode - --dry-run prints what it would do
8. Version stamp - tracks init version

Usage:
    CLI one-off: python -m ai_wallet.db_init
    With dry-run: python -m ai_wallet.db_init --dry-run
    In production: APP_ENV=production AI_WALLET_INIT_CONFIRM=YES python -m ai_wallet.db_init
"""

import os
import sys
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import CollectionInvalid, OperationFailure

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Version tracking
INIT_VERSION = "v1.0.0"

# Collections to create (if not exist)
REQUIRED_COLLECTIONS = [
    "ai_wallet",
    "ai_token_ledger",
    "ai_purchases",
    "paypal_events",
    "entitlements",
    "ai_wallet_meta"  # For version tracking
]

# Index definitions: (collection, index_spec, options)
REQUIRED_INDEXES = [
    # ai_wallet indexes
    ("ai_wallet", [("user_id", 1)], {"unique": True, "name": "idx_user_id_unique"}),
    ("ai_wallet", [("org_id", 1)], {"name": "idx_org_id"}),
    
    # ai_token_ledger indexes
    ("ai_token_ledger", [("user_id", 1), ("timestamp", -1)], {"name": "idx_user_timestamp"}),
    ("ai_token_ledger", [("request_id", 1)], {"name": "idx_request_id"}),
    
    # ai_purchases indexes
    ("ai_purchases", [("purchase_id", 1)], {"unique": True, "name": "idx_purchase_id_unique"}),
    ("ai_purchases", [("status", 1), ("created_at", -1)], {"name": "idx_status_created"}),
    ("ai_purchases", [("user_id", 1)], {"name": "idx_user_id"}),
    
    # paypal_events indexes
    ("paypal_events", [("event_id", 1)], {"unique": True, "name": "idx_event_id_unique"}),
    ("paypal_events", [("capture_id", 1)], {"unique": True, "sparse": True, "name": "idx_capture_id_unique"}),
    
    # entitlements indexes
    ("entitlements", [("user_id", 1)], {"unique": True, "sparse": True, "name": "idx_entitlement_user_id"}),
    ("entitlements", [("org_id", 1)], {"sparse": True, "name": "idx_entitlement_org_id"}),
]


def check_environment() -> Tuple[bool, str]:
    """
    Check environment and confirm if production execution is allowed.
    
    Returns:
        Tuple of (allowed, message)
    """
    app_env = os.environ.get("APP_ENV", os.environ.get("NODE_ENV", "development"))
    
    if app_env.lower() == "production":
        confirm = os.environ.get("AI_WALLET_INIT_CONFIRM", "")
        if confirm != "YES":
            return False, (
                "PRODUCTION ENVIRONMENT DETECTED!\n"
                "To run init in production, set: AI_WALLET_INIT_CONFIRM=YES\n"
                "Current value: AI_WALLET_INIT_CONFIRM='%s'" % confirm
            )
    
    return True, f"Environment: {app_env}"


async def create_collection_if_not_exists(db, collection_name: str, dry_run: bool = False) -> str:
    """Create a collection if it doesn't exist."""
    existing = await db.list_collection_names()
    
    if collection_name in existing:
        return f"  [SKIP] Collection '{collection_name}' already exists"
    
    if dry_run:
        return f"  [DRY-RUN] Would create collection '{collection_name}'"
    
    try:
        await db.create_collection(collection_name)
        return f"  [CREATE] Created collection '{collection_name}'"
    except CollectionInvalid:
        return f"  [SKIP] Collection '{collection_name}' already exists (race)"


async def create_index_if_not_exists(
    db, 
    collection_name: str, 
    index_spec: List[Tuple], 
    options: dict,
    dry_run: bool = False
) -> str:
    """Create an index if it doesn't exist."""
    collection = db[collection_name]
    index_name = options.get("name", str(index_spec))
    
    # Check existing indexes
    existing_indexes = await collection.index_information()
    
    if index_name in existing_indexes:
        return f"  [SKIP] Index '{index_name}' on '{collection_name}' already exists"
    
    if dry_run:
        return f"  [DRY-RUN] Would create index '{index_name}' on '{collection_name}'"
    
    try:
        await collection.create_index(index_spec, **options)
        return f"  [CREATE] Created index '{index_name}' on '{collection_name}'"
    except OperationFailure as e:
        if "already exists" in str(e).lower():
            return f"  [SKIP] Index '{index_name}' on '{collection_name}' already exists (race)"
        raise


async def update_version_stamp(db, dry_run: bool = False) -> str:
    """Update or create version stamp document."""
    if dry_run:
        return f"  [DRY-RUN] Would update version stamp to {INIT_VERSION}"
    
    await db.ai_wallet_meta.update_one(
        {"_id": "ai_wallet_init"},
        {
            "$set": {
                "version": INIT_VERSION,
                "applied_at": datetime.now(timezone.utc).isoformat()
            }
        },
        upsert=True
    )
    return f"  [UPDATE] Version stamp updated to {INIT_VERSION}"


async def run_init(dry_run: bool = False):
    """Run the database initialization."""
    from dotenv import load_dotenv
    
    # Load environment
    env_path = Path(__file__).parent.parent / '.env'
    load_dotenv(env_path)
    
    # Environment check
    allowed, env_message = check_environment()
    logger.info(env_message)
    
    if not allowed:
        logger.error("Init blocked due to environment guard")
        sys.exit(1)
    
    # Get DB connection
    mongo_url = os.environ.get('MONGO_URL')
    db_name = os.environ.get('DB_NAME')
    
    if not mongo_url or not db_name:
        logger.error("Missing MONGO_URL or DB_NAME environment variables")
        sys.exit(1)
    
    logger.info(f"Database: {db_name}")
    logger.info(f"Dry Run: {dry_run}")
    logger.info("-" * 50)
    
    # Connect to MongoDB
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    
    # Test connection
    try:
        await client.admin.command('ping')
        logger.info("MongoDB connection: OK")
    except Exception as e:
        logger.error(f"MongoDB connection failed: {e}")
        sys.exit(1)
    
    # Create collections
    logger.info("\n=== Collections ===")
    for collection_name in REQUIRED_COLLECTIONS:
        result = await create_collection_if_not_exists(db, collection_name, dry_run)
        logger.info(result)
    
    # Create indexes
    logger.info("\n=== Indexes ===")
    for collection_name, index_spec, options in REQUIRED_INDEXES:
        result = await create_index_if_not_exists(db, collection_name, index_spec, options, dry_run)
        logger.info(result)
    
    # Update version stamp
    logger.info("\n=== Version Stamp ===")
    result = await update_version_stamp(db, dry_run)
    logger.info(result)
    
    # Close connection
    client.close()
    
    logger.info("\n" + "=" * 50)
    logger.info("SUCCESS: AI Wallet DB init completed")
    logger.info("=" * 50)


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="AI Wallet Database Initialization",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Development (default)
    python -m ai_wallet.db_init
    
    # Dry run (no changes)
    python -m ai_wallet.db_init --dry-run
    
    # Production
    APP_ENV=production AI_WALLET_INIT_CONFIRM=YES python -m ai_wallet.db_init
        """
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Print what would be done without making changes'
    )
    
    args = parser.parse_args()
    
    asyncio.run(run_init(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
