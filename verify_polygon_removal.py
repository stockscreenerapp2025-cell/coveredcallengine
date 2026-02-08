import sys
import os
import asyncio
import logging

# Setup path to import backend modules
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.join(current_dir, 'backend')
sys.path.insert(0, backend_dir)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def verify_greeks():
    logger.info("Verifying Black-Scholes Greeks calculation...")
    try:
        from backend.utils.greeks import calculate_greeks
        
        # Test case: ATM Call
        # S=100, K=100, T=1yr, r=5%, sigma=20%
        result = calculate_greeks(100, 100, 1, 0.05, 0.20, "call")
        
        logger.info(f"Greeks Result: {result}")
        
        assert "delta" in result
        # Delta for ATM call should be roughly 0.6 (due to drift)
        if 0.5 < result["delta"] < 0.7:
             logger.info("✅ Delta calculation looks reasonable")
        else:
             logger.warning(f"⚠️ Delta calculation might be off: {result['delta']}")
             
    except ImportError as e:
        logger.error(f"❌ Failed to import calculate_greeks: {e}")
    except Exception as e:
        logger.error(f"❌ Error verifying Greeks: {e}")

async def verify_imports():
    logger.info("Verifying module imports...")
    try:
        import backend.routes.screener
        import backend.routes.precomputed_scans
        import backend.routes.stocks
        import backend.routes.options
        import backend.services.data_provider
        
        logger.info("✅ All modified modules imported successfully")
        
    except ImportError as e:
        logger.error(f"❌ Import error: {e}")
    except Exception as e:
        logger.error(f"❌ Unexpected error during import verification: {e}")

async def main():
    logger.info("Starting verification...")
    await verify_greeks()
    await verify_imports()
    logger.info("Verification complete.")

if __name__ == "__main__":
    asyncio.run(main())
