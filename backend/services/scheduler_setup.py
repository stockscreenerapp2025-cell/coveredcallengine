"""
scheduler_setup.py
------------------
APScheduler wiring for the CCE snapshot-first architecture.

FILE: backend/services/scheduler_setup.py

REPLACES any previous scheduler config that had a 4:05 PM or 4:10 PM Yahoo job.

SCHEDULE (all times US/Eastern, Mon-Fri only):
  4:30 PM   → probe: checks if today is a NYSE trading day, then schedules
               snapshot at the correct time (close + 45 min)
  Dynamic   → snapshot job: runs at market close + 45 min
               Normal day:     ~5:00 PM  (4:15 PM close + 45 min)
               Early-close day: e.g. 1:45 PM (1:00 PM close + 45 min)
  5:20 PM   → CC scan   — reads daily_snapshots only, ZERO Yahoo calls
  5:25 PM   → PMCC scan — reads daily_snapshots only, ZERO Yahoo calls

STARTUP USAGE:
    from services.scheduler_setup import setup_scheduler
    scheduler = AsyncIOScheduler()
    setup_scheduler(scheduler, db, universe)
    scheduler.start()

CHANGE LOG vs previous version:
  FIXED:   scheduler ref is passed directly into setup_scheduler() and stored
           in the closure — no fragile module-level _scheduler_ref pattern.
  FIXED:   _make_cc_job now calls ONLY run_all_scans() once, which runs all
           6 profiles internally — removed duplicate run_cc_scan() call.
  FIXED:   _make_pmcc_job is now a no-op guard (run_all_scans already covers
           PMCC) to avoid double execution while keeping the time slot reserved.
  ADDED:   Snapshot existence check before CC and PMCC scans run — if no
           snapshot exists for today the scan is skipped with a clear log.
  ADDED:   set_scheduler_ref() removed — no longer needed.
"""

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from services.trading_calendar import TradingCalendar
from services.eod_pipeline import run_snapshot_job
from services.precomputed_scans import PrecomputedScanService

logger = logging.getLogger(__name__)
ET     = ZoneInfo("America/New_York")

_calendar = TradingCalendar()


# ---------------------------------------------------------------------------
# Public entry point — call once at app startup
# ---------------------------------------------------------------------------

def setup_scheduler(scheduler, db, universe: list) -> None:
    """
    Register all CCE jobs with the provided APScheduler instance.

    Parameters
    ----------
    scheduler : AsyncIOScheduler
        The APScheduler instance created at app startup.
    db        : motor AsyncIOMotorDatabase
        MongoDB database handle.
    universe  : list[str]
        Full symbol universe (~1500 symbols) passed to the snapshot job.

    Call this BEFORE scheduler.start().
    """

    # ── 4:30 PM probe ───────────────────────────────────────────────────────
    # Checks if today is a NYSE trading day.
    # If yes, schedules the snapshot job at the correct time for that day.
    # If no  (holiday / weekend), logs and exits — no snapshot, no scan.
    scheduler.add_job(
        _make_snapshot_probe(scheduler, db, universe),
        CronTrigger(hour=16, minute=30, timezone=ET, day_of_week="mon-fri"),
        id="snapshot_probe",
        replace_existing=True,
        misfire_grace_time=300,   # 5 min grace — safe for probe
    )

    # ── 5:20 PM CC scan ─────────────────────────────────────────────────────
    # Runs all 6 profiles (3 CC + 3 PMCC) via run_all_scans().
    # Reads daily_snapshots only — ZERO Yahoo calls.
    scheduler.add_job(
        _make_scan_job(db),
        CronTrigger(hour=17, minute=20, timezone=ET, day_of_week="mon-fri"),
        id="cc_scan",
        replace_existing=True,
        misfire_grace_time=600,   # 10 min grace — scan can start slightly late
    )

    # ── 5:25 PM PMCC slot ────────────────────────────────────────────────────
    # run_all_scans() at 5:20 already covers PMCC.
    # This slot is reserved as a safety fallback — fires run_all_scans()
    # only if the 5:20 job did not complete (e.g. server restart between slots).
    scheduler.add_job(
        _make_pmcc_guard_job(db),
        CronTrigger(hour=17, minute=25, timezone=ET, day_of_week="mon-fri"),
        id="pmcc_scan",
        replace_existing=True,
        misfire_grace_time=600,
    )

    logger.info(
        "CCE scheduler registered: "
        "probe@4:30 PM ET | snapshot@dynamic | CC+PMCC@5:20 PM ET | guard@5:25 PM ET"
    )


# ---------------------------------------------------------------------------
# Job factories
# ---------------------------------------------------------------------------

def _make_snapshot_probe(scheduler, db, universe: list):
    """
    Returns the 4:30 PM probe coroutine.

    Checks NYSE calendar for today.  If it is a trading day, adds a one-shot
    DateTrigger job for the snapshot at market_close + 45 min.

    The scheduler reference is captured directly in the closure — no global
    module-level reference needed.
    """
    async def snapshot_probe():
        today = date.today()

        if not _calendar.is_trading_day(today):
            logger.info("[PROBE] %s is not a NYSE trading day — snapshot skipped.", today)
            return

        try:
            run_at = _calendar.get_snapshot_time(today)
        except Exception as e:
            logger.error("[PROBE] Could not compute snapshot time for %s: %s", today, e)
            return

        logger.info(
            "[PROBE] %s is a trading day. Snapshot scheduled for %s ET (%s close).",
            today,
            run_at.strftime("%H:%M"),
            "early" if _calendar.is_early_close(today) else "normal",
        )

        scheduler.add_job(
            _make_snapshot_job(db, universe),
            DateTrigger(run_date=run_at, timezone=ET),
            id="snapshot_dynamic",
            replace_existing=True,
            misfire_grace_time=1800,   # 30 min grace — snapshot can start late
        )

    return snapshot_probe


def _make_snapshot_job(db, universe: list):
    """
    Returns the dynamic snapshot coroutine.

    Calls run_snapshot_job() from eod_pipeline.py which is the ONLY place
    Yahoo Finance is called.  Stores results in daily_snapshots collection.
    """
    async def snapshot_job():
        today = date.today()
        logger.info("=== SNAPSHOT JOB STARTING for %s ===", today)
        try:
            result = await run_snapshot_job(db, universe, today)
            logger.info("=== SNAPSHOT JOB COMPLETE: %s ===", result)
        except Exception as e:
            logger.error("=== SNAPSHOT JOB FAILED: %s ===", e, exc_info=True)

    return snapshot_job


def _make_scan_job(db):
    """
    Returns the 5:20 PM scan coroutine.

    Calls PrecomputedScanService.run_all_scans() which runs all 6 profiles
    (3 CC + 3 PMCC) reading ONLY from daily_snapshots.

    Before running, verifies that a snapshot exists for today.
    If not, logs a clear error and aborts — never uses stale data silently.
    """
    async def scan_job():
        logger.info("=== SCAN JOB STARTING (CC + PMCC, cache-only) ===")

        today_str = datetime.now(ET).strftime("%Y-%m-%d")

        # Guard: confirm snapshot exists before running scans
        snapshot_count = await db.daily_snapshots.count_documents(
            {"snapshot_date": today_str}
        )
        if snapshot_count == 0:
            logger.error(
                "=== SCAN ABORTED: No daily_snapshots found for %s. "
                "Did the snapshot job run? ===", today_str
            )
            return

        logger.info(
            "Snapshot guard passed: %d snapshots found for %s",
            snapshot_count, today_str,
        )

        try:
            svc     = PrecomputedScanService(db)
            results = await svc.run_all_scans()
            logger.info("=== SCAN JOB COMPLETE: %s ===", results)
        except Exception as e:
            logger.error("=== SCAN JOB FAILED: %s ===", e, exc_info=True)

    return scan_job


def _make_pmcc_guard_job(db):
    """
    Returns the 5:25 PM guard coroutine.

    run_all_scans() at 5:20 PM already covers PMCC.
    This job only re-runs scans if precomputed_scans has no entry for today,
    which would indicate the 5:20 PM job failed silently.
    """
    async def pmcc_guard():
        today_str = datetime.now(ET).strftime("%Y-%m-%d")

        # Check if scans already completed at 5:20 PM
        completed_count = await db.precomputed_scans.count_documents(
            {"computed_date": today_str}
        )

        if completed_count >= 6:
            # All 6 profiles stored — nothing to do
            logger.info(
                "[PMCC_GUARD] All %d scan profiles already stored for %s — skipping.",
                completed_count, today_str,
            )
            return

        logger.warning(
            "[PMCC_GUARD] Only %d scan profiles stored for %s. "
            "5:20 PM job may have failed. Re-running run_all_scans().",
            completed_count, today_str,
        )

        snapshot_count = await db.daily_snapshots.count_documents(
            {"snapshot_date": today_str}
        )
        if snapshot_count == 0:
            logger.error("[PMCC_GUARD] No snapshots for %s — cannot re-run.", today_str)
            return

        try:
            svc     = PrecomputedScanService(db)
            results = await svc.run_all_scans()
            logger.info("[PMCC_GUARD] Re-run complete: %s", results)
        except Exception as e:
            logger.error("[PMCC_GUARD] Re-run failed: %s", e, exc_info=True)

    return pmcc_guard