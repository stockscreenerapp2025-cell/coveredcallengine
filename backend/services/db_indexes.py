"""
MongoDB Index Definitions
=========================
Creates all required indexes for the EOD pipeline collections.
Run this once during application startup or via admin endpoint.
"""
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


async def create_all_indexes(db) -> Dict[str, Any]:
    """
    Create all required indexes for EOD pipeline.
    
    Collections and indexes:
    - symbol_snapshot: (run_id, symbol)
    - scan_results_cc: (run_id, score desc), (run_id, symbol)
    - scan_results_pmcc: (run_id, score desc), (run_id, symbol)
    - scan_runs: (as_of desc), (run_id unique)
    - scan_universe_versions: (universe_version unique), (created_at desc)
    - scan_universe_audit: (run_id, included), (run_id, exclude_reason), etc.
    - scan_run_summary: (as_of desc), (run_id unique)
    
    Returns:
        Summary of indexes created
    """
    results = {}
    
    # symbol_snapshot
    try:
        await db.symbol_snapshot.create_index([("run_id", 1), ("symbol", 1)])
        await db.symbol_snapshot.create_index([("as_of", -1)])
        results["symbol_snapshot"] = "OK"
    except Exception as e:
        results["symbol_snapshot"] = f"ERROR: {e}"
        logger.error(f"Index creation failed for symbol_snapshot: {e}")
    
    # scan_results_cc
    try:
        await db.scan_results_cc.create_index([("run_id", 1), ("score", -1)])
        await db.scan_results_cc.create_index([("run_id", 1), ("symbol", 1)])
        results["scan_results_cc"] = "OK"
    except Exception as e:
        results["scan_results_cc"] = f"ERROR: {e}"
        logger.error(f"Index creation failed for scan_results_cc: {e}")
    
    # scan_results_pmcc
    try:
        await db.scan_results_pmcc.create_index([("run_id", 1), ("score", -1)])
        await db.scan_results_pmcc.create_index([("run_id", 1), ("symbol", 1)])
        results["scan_results_pmcc"] = "OK"
    except Exception as e:
        results["scan_results_pmcc"] = f"ERROR: {e}"
        logger.error(f"Index creation failed for scan_results_pmcc: {e}")
    
    # scan_runs
    try:
        await db.scan_runs.create_index([("as_of", -1)])
        await db.scan_runs.create_index([("run_id", 1)], unique=True)
        results["scan_runs"] = "OK"
    except Exception as e:
        results["scan_runs"] = f"ERROR: {e}"
        logger.error(f"Index creation failed for scan_runs: {e}")
    
    # scan_universe_versions
    try:
        await db.scan_universe_versions.create_index([("universe_version", 1)], unique=True)
        await db.scan_universe_versions.create_index([("created_at", -1)])
        results["scan_universe_versions"] = "OK"
    except Exception as e:
        results["scan_universe_versions"] = f"ERROR: {e}"
        logger.error(f"Index creation failed for scan_universe_versions: {e}")
    
    # scan_universe_audit
    try:
        await db.scan_universe_audit.create_index([("run_id", 1), ("included", 1)])
        await db.scan_universe_audit.create_index([("run_id", 1), ("exclude_reason", 1)])
        await db.scan_universe_audit.create_index([("run_id", 1), ("exclude_stage", 1)])
        await db.scan_universe_audit.create_index([("as_of", -1)])
        results["scan_universe_audit"] = "OK"
    except Exception as e:
        results["scan_universe_audit"] = f"ERROR: {e}"
        logger.error(f"Index creation failed for scan_universe_audit: {e}")
    
    # scan_run_summary
    try:
        await db.scan_run_summary.create_index([("as_of", -1)])
        await db.scan_run_summary.create_index([("run_id", 1)], unique=True)
        results["scan_run_summary"] = "OK"
    except Exception as e:
        results["scan_run_summary"] = f"ERROR: {e}"
        logger.error(f"Index creation failed for scan_run_summary: {e}")
    
    # us_symbol_master (for liquidity expansion queries)
    try:
        await db.us_symbol_master.create_index([
            ("avg_volume_20d", -1),
            ("market_cap", -1),
            ("last_close", 1)
        ])
        await db.us_symbol_master.create_index([("symbol", 1)], unique=True)
        results["us_symbol_master"] = "OK"
    except Exception as e:
        results["us_symbol_master"] = f"ERROR: {e}"
        logger.error(f"Index creation failed for us_symbol_master: {e}")
    
    logger.info(f"Index creation complete: {results}")
    return results
