"""
Database connection and configuration

CCE MASTER ARCHITECTURE - Environment Validation
Fails fast with clear error messages if required variables are missing.
"""
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')


def validate_required_env_vars():
    """
    Validate all critical environment variables exist before the app starts.
    Raises ValueError with clear error message if required variables are missing.
    """
    required_vars = {
        "MONGO_URL": "MongoDB connection string (e.g., mongodb://localhost:27017)",
        "DB_NAME": "Database name (e.g., premium_hunter)"
    }
    
    missing = []
    for var, description in required_vars.items():
        if not os.environ.get(var):
            missing.append(f"  - {var}: {description}")
    
    if missing:
        error_msg = (
            "\n" + "=" * 60 + "\n"
            "CRITICAL: Missing required environment variables!\n"
            "=" * 60 + "\n"
            "The following environment variables must be set:\n\n"
            + "\n".join(missing) + "\n\n"
            "Please check your .env file or environment configuration.\n"
            "See .env.example for reference.\n"
            + "=" * 60
        )
        raise ValueError(error_msg)


# Validate environment variables on module load
validate_required_env_vars()

# MongoDB connection with connection pool configuration
mongo_url = os.environ['MONGO_URL']

try:
    client = AsyncIOMotorClient(
        mongo_url,
        maxPoolSize=50,
        minPoolSize=10,
        connectTimeoutMS=5000,
        serverSelectionTimeoutMS=5000,
        retryWrites=True
    )
except Exception as e:
    raise ValueError(f"Failed to create MongoDB client: {e}")

db = client[os.environ['DB_NAME']]


async def check_db_connection():
    """
    Test database connection health.
    
    Returns:
        Tuple[bool, Optional[str]]: (success, error_message)
    """
    try:
        # Ping the database
        await client.admin.command('ping')
        
        # Test if we can read from a collection
        db_name = os.environ['DB_NAME']
        await db.list_collection_names()
        
        logger.info(f"Database connected successfully: {db_name}")
        return True, None
        
    except Exception as e:
        error_msg = f"Database connection failed: {e}"
        logger.error(error_msg)
        return False, error_msg

# Cache configuration
CACHE_DURATION_SECONDS = 300  # 5 minutes for real-time data
WEEKEND_CACHE_DURATION_SECONDS = 259200  # 72 hours (Friday close to Monday open)
