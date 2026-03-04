#!/usr/bin/env python3
"""
EOD Pipeline Job — runs as a subprocess, isolated from the API process.
Launched by routes/eod_pipeline.py via subprocess.Popen.

Usage:
    python -m scripts.run_eod_pipeline_job <run_id> [--force-build-universe]

This script creates its own Motor client and event loop so it never
shares resources with the uvicorn API process.
"""
import asyncio
import os
import sys
import argparse
import logging
from datetime import datetime, timezone

# Ensure backend/ is on PYTHONPATH (Docker sets PYTHONPATH=/app/backend)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor.motor_asyncio import AsyncIOMotorClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("eod_job")


async def main(run_id: str, force_build_universe: bool) -> None:
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]

    client = AsyncIOMotorClient(
        mongo_url,
        maxPoolSize=10,
        minPoolSize=1,
        connectTimeoutMS=10000,
        serverSelectionTimeoutMS=10000,
    )
    db = client[db_name]

    try:
        # Mark as RUNNING
        await db.eod_runs.update_one(
            {"run_id": run_id},
            {"$set": {"status": "RUNNING", "started_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        logger.info(f"[EOD_JOB] Starting run_id={run_id} force_build={force_build_universe}")

        from services.eod_pipeline import run_eod_pipeline
        result = await run_eod_pipeline(db, force_build_universe=force_build_universe, run_id=run_id)

        # Update eod_runs with final state
        await db.eod_runs.update_one(
            {"run_id": run_id},
            {"$set": {
                "status": result.status,
                "completed_at": datetime.now(timezone.utc),
                "symbols_processed": result.symbols_processed,
                "symbols_total": result.symbols_total,
                "cc_count": len(result.cc_opportunities) if result.cc_opportunities else 0,
                "pmcc_count": len(result.pmcc_opportunities) if result.pmcc_opportunities else 0,
                "chain_success": result.chain_success,
                "chain_failure": result.chain_failure,
            }},
        )
        logger.info(f"[EOD_JOB] Completed run_id={run_id} status={result.status}")

    except Exception as exc:
        logger.error(f"[EOD_JOB] Failed run_id={run_id}: {exc}", exc_info=True)
        try:
            await db.eod_runs.update_one(
                {"run_id": run_id},
                {"$set": {
                    "status": "FAILED",
                    "completed_at": datetime.now(timezone.utc),
                    "error": str(exc),
                }},
            )
        except Exception:
            pass
        sys.exit(1)
    finally:
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EOD Pipeline subprocess job")
    parser.add_argument("run_id", help="Unique run ID created by the API before spawning this process")
    parser.add_argument("--force-build-universe", action="store_true", help="Rebuild pmcc_universe from scratch")
    args = parser.parse_args()

    asyncio.run(main(args.run_id, args.force_build_universe))
