"""
Resilient Fetch Service for Scan Workflows
==========================================

SCAN TIMEOUT FIX (December 2025):
- Bounded concurrency via asyncio.Semaphore (YAHOO_SCAN_MAX_CONCURRENCY)
- Timeout handling per symbol fetch (YAHOO_TIMEOUT_SECONDS)
- Retry logic with exponential backoff (YAHOO_MAX_RETRIES)
- Partial success tracking (scan continues if individual symbols fail)
- Aggregated logging per scan run

IMPORTANT: This applies ONLY to SCAN PATHS (batch processing)
- Screener scans (precomputed_scans.py)
- Custom scans (screener.py)
- Does NOT affect single-symbol user lookups (watchlist, simulator)
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, List, Optional, TypeVar
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# Configuration from environment
YAHOO_SCAN_MAX_CONCURRENCY = int(os.environ.get("YAHOO_SCAN_MAX_CONCURRENCY", "5"))
YAHOO_TIMEOUT_SECONDS = int(os.environ.get("YAHOO_TIMEOUT_SECONDS", "30"))
YAHOO_MAX_RETRIES = int(os.environ.get("YAHOO_MAX_RETRIES", "2"))

# Module-level semaphore for scan concurrency control
_scan_semaphore: Optional[asyncio.Semaphore] = None

def get_scan_semaphore() -> asyncio.Semaphore:
    """Get or create the scan semaphore (lazy initialization)."""
    global _scan_semaphore
    if _scan_semaphore is None:
        _scan_semaphore = asyncio.Semaphore(YAHOO_SCAN_MAX_CONCURRENCY)
        logger.info(f"Initialized scan semaphore with max_concurrency={YAHOO_SCAN_MAX_CONCURRENCY}")
    return _scan_semaphore

def reset_scan_semaphore():
    """Reset the semaphore (useful for testing or config reload)."""
    global _scan_semaphore
    _scan_semaphore = None

T = TypeVar("T")


@dataclass
class ScanStats:
    """Aggregated statistics for a scan run."""
    run_id: str
    scan_type: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    
    # Counters
    total_symbols: int = 0
    successful: int = 0
    failed_timeout: int = 0
    failed_error: int = 0
    retries_total: int = 0
    
    # Timing
    total_duration_seconds: float = 0.0
    avg_fetch_time_seconds: float = 0.0
    max_fetch_time_seconds: float = 0.0
    
    # Failed symbols tracking
    failed_symbols: List[Dict[str, str]] = field(default_factory=list)
    
    def complete(self):
        """Mark the scan as complete and calculate final stats."""
        self.completed_at = datetime.now(timezone.utc)
        if self.started_at:
            self.total_duration_seconds = (self.completed_at - self.started_at).total_seconds()
    
    def log_summary(self):
        """Log a summary of the scan run."""
        success_rate = (self.successful / self.total_symbols * 100) if self.total_symbols > 0 else 0
        
        logger.info(
            f"SCAN_STATS | run_id={self.run_id} | type={self.scan_type} | "
            f"total={self.total_symbols} | success={self.successful} ({success_rate:.1f}%) | "
            f"timeout={self.failed_timeout} | error={self.failed_error} | "
            f"retries={self.retries_total} | duration={self.total_duration_seconds:.1f}s"
        )
        
        if self.failed_symbols:
            failed_preview = self.failed_symbols[:5]
            logger.warning(
                f"SCAN_FAILURES | run_id={self.run_id} | "
                f"failed_symbols (first 5): {failed_preview}"
            )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage/logging."""
        return {
            "run_id": self.run_id,
            "scan_type": self.scan_type,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "total_symbols": self.total_symbols,
            "successful": self.successful,
            "failed_timeout": self.failed_timeout,
            "failed_error": self.failed_error,
            "retries_total": self.retries_total,
            "success_rate_pct": round((self.successful / self.total_symbols * 100) if self.total_symbols > 0 else 0, 1),
            "total_duration_seconds": round(self.total_duration_seconds, 2),
            "avg_fetch_time_seconds": round(self.avg_fetch_time_seconds, 2),
            "max_fetch_time_seconds": round(self.max_fetch_time_seconds, 2),
            "failed_symbols": self.failed_symbols[:20],  # Limit for storage
        }


@dataclass
class FetchResult:
    """Result of a single fetch operation."""
    symbol: str
    success: bool
    data: Any = None
    error: Optional[str] = None
    fetch_time_seconds: float = 0.0
    retries_used: int = 0
    timed_out: bool = False


async def fetch_with_resilience(
    symbol: str,
    fetch_func: Callable[..., Coroutine[Any, Any, T]],
    stats: ScanStats,
    timeout_seconds: int = None,
    max_retries: int = None,
    *args,
    **kwargs
) -> FetchResult:
    """
    Execute a fetch function with bounded concurrency, timeout, and retry.
    
    SCAN PATH ONLY - applies to batch scan operations.
    
    Args:
        symbol: Symbol being fetched (for logging)
        fetch_func: Async function to call
        stats: ScanStats object for aggregating results
        timeout_seconds: Override timeout (default: YAHOO_TIMEOUT_SECONDS)
        max_retries: Override retries (default: YAHOO_MAX_RETRIES)
        *args, **kwargs: Arguments to pass to fetch_func
    
    Returns:
        FetchResult with success/failure info and data
    """
    timeout = timeout_seconds or YAHOO_TIMEOUT_SECONDS
    retries = max_retries or YAHOO_MAX_RETRIES
    
    semaphore = get_scan_semaphore()
    result = FetchResult(symbol=symbol, success=False)
    start_time = time.time()
    
    for attempt in range(retries + 1):
        try:
            async with semaphore:
                # Apply timeout to the fetch operation
                data = await asyncio.wait_for(
                    fetch_func(*args, **kwargs),
                    timeout=timeout
                )
                
                # Success
                result.success = True
                result.data = data
                result.fetch_time_seconds = time.time() - start_time
                result.retries_used = attempt
                
                stats.successful += 1
                stats.retries_total += attempt
                
                return result
                
        except asyncio.TimeoutError:
            result.timed_out = True
            result.error = f"Timeout after {timeout}s"
            
            if attempt < retries:
                # Exponential backoff before retry
                wait_time = (2 ** attempt) * 0.5  # 0.5s, 1s, 2s...
                logger.debug(f"Timeout for {symbol}, retry {attempt + 1}/{retries} in {wait_time}s")
                await asyncio.sleep(wait_time)
            else:
                # Final timeout - log and mark failed
                result.fetch_time_seconds = time.time() - start_time
                result.retries_used = retries
                
                stats.failed_timeout += 1
                stats.retries_total += retries
                stats.failed_symbols.append({
                    "symbol": symbol,
                    "reason": "TIMEOUT",
                    "attempts": retries + 1
                })
                
                logger.warning(f"SCAN_TIMEOUT | symbol={symbol} | attempts={retries + 1} | timeout={timeout}s")
                return result
                
        except Exception as e:
            error_msg = str(e)
            result.error = error_msg
            
            if attempt < retries:
                # Retry on error
                wait_time = (2 ** attempt) * 0.5
                logger.debug(f"Error for {symbol}: {error_msg}, retry {attempt + 1}/{retries} in {wait_time}s")
                await asyncio.sleep(wait_time)
            else:
                # Final error - log and mark failed
                result.fetch_time_seconds = time.time() - start_time
                result.retries_used = retries
                
                stats.failed_error += 1
                stats.retries_total += retries
                stats.failed_symbols.append({
                    "symbol": symbol,
                    "reason": f"ERROR: {error_msg[:100]}",
                    "attempts": retries + 1
                })
                
                logger.warning(f"SCAN_ERROR | symbol={symbol} | error={error_msg[:100]}")
                return result
    
    return result


async def fetch_batch_with_resilience(
    symbols: List[str],
    fetch_func: Callable[[str], Coroutine[Any, Any, T]],
    scan_type: str,
    run_id: str,
    batch_size: int = 10,
    inter_batch_delay: float = 1.0,
) -> tuple[Dict[str, T], ScanStats]:
    """
    Fetch multiple symbols with resilience, processing in batches.
    
    This is the main entry point for scan workflows.
    
    Args:
        symbols: List of symbols to fetch
        fetch_func: Async function that takes a symbol and returns data
        scan_type: Type of scan for logging (e.g., "covered_call", "pmcc")
        run_id: Unique identifier for this scan run
        batch_size: Number of symbols to process in parallel
        inter_batch_delay: Delay between batches to avoid rate limiting
    
    Returns:
        Tuple of (results_dict, stats)
        - results_dict: {symbol: data} for successful fetches
        - stats: ScanStats with aggregated metrics
    """
    stats = ScanStats(
        run_id=run_id,
        scan_type=scan_type,
        total_symbols=len(symbols)
    )
    
    results: Dict[str, T] = {}
    fetch_times: List[float] = []
    
    logger.info(f"SCAN_START | run_id={run_id} | type={scan_type} | symbols={len(symbols)} | batch_size={batch_size}")
    
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        
        # Create tasks for the batch
        tasks = [
            fetch_with_resilience(
                symbol=sym,
                fetch_func=fetch_func,
                stats=stats,
                symbol_arg=sym  # Pass symbol to fetch_func
            )
            for sym in batch
        ]
        
        # Execute batch in parallel
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        for result in batch_results:
            if isinstance(result, FetchResult):
                if result.success and result.data is not None:
                    results[result.symbol] = result.data
                if result.fetch_time_seconds > 0:
                    fetch_times.append(result.fetch_time_seconds)
            elif isinstance(result, Exception):
                logger.error(f"Unexpected exception in batch: {result}")
        
        # Inter-batch delay to avoid rate limiting
        if i + batch_size < len(symbols):
            await asyncio.sleep(inter_batch_delay)
    
    # Calculate final stats
    stats.complete()
    if fetch_times:
        stats.avg_fetch_time_seconds = sum(fetch_times) / len(fetch_times)
        stats.max_fetch_time_seconds = max(fetch_times)
    
    stats.log_summary()
    
    return results, stats


async def fetch_with_resilience_simple(
    symbol: str,
    fetch_func: Callable[..., Coroutine[Any, Any, T]],
    stats: ScanStats,
    *args,
    **kwargs
) -> Optional[T]:
    """
    Simplified wrapper that returns just the data (or None on failure).
    
    For use in existing code that expects Optional[T] returns.
    """
    result = await fetch_with_resilience(symbol, fetch_func, stats, *args, **kwargs)
    return result.data if result.success else None


class ResilientYahooFetcher:
    """
    Wrapper class for Yahoo Finance calls in scan contexts.
    
    Usage:
        fetcher = ResilientYahooFetcher(scan_type="covered_call", run_id="cc_2025_01_01")
        
        # Fetch with resilience
        data = await fetcher.fetch(symbol, fetch_func, *args)
        
        # Get stats at end
        stats = fetcher.get_stats()
        stats.log_summary()
    """
    
    def __init__(self, scan_type: str, run_id: str = None):
        self.scan_type = scan_type
        self.run_id = run_id or f"{scan_type}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        self.stats = ScanStats(run_id=self.run_id, scan_type=scan_type)
        self._fetch_times: List[float] = []
    
    def set_total_symbols(self, count: int):
        """Set the total symbol count for stats."""
        self.stats.total_symbols = count
    
    async def fetch(
        self,
        symbol: str,
        fetch_func: Callable[..., Coroutine[Any, Any, T]],
        *args,
        **kwargs
    ) -> Optional[T]:
        """
        Fetch data for a symbol with resilience.
        
        Returns the data on success, None on failure.
        
        Args:
            symbol: Symbol being fetched (for logging)
            fetch_func: Async function to call
            *args: Arguments to pass to fetch_func
            **kwargs: Keyword arguments to pass to fetch_func
        """
        semaphore = get_scan_semaphore()
        timeout = YAHOO_TIMEOUT_SECONDS
        retries = YAHOO_MAX_RETRIES
        
        start_time = time.time()
        
        for attempt in range(retries + 1):
            try:
                async with semaphore:
                    # Apply timeout to the fetch operation
                    data = await asyncio.wait_for(
                        fetch_func(*args, **kwargs),
                        timeout=timeout
                    )
                    
                    # Success
                    fetch_time = time.time() - start_time
                    self._fetch_times.append(fetch_time)
                    self.stats.successful += 1
                    self.stats.retries_total += attempt
                    
                    return data
                    
            except asyncio.TimeoutError:
                if attempt < retries:
                    # Exponential backoff before retry
                    wait_time = (2 ** attempt) * 0.5
                    logger.debug(f"Timeout for {symbol}, retry {attempt + 1}/{retries} in {wait_time}s")
                    await asyncio.sleep(wait_time)
                else:
                    # Final timeout
                    self.stats.failed_timeout += 1
                    self.stats.retries_total += retries
                    self.stats.failed_symbols.append({
                        "symbol": symbol,
                        "reason": "TIMEOUT",
                        "attempts": retries + 1
                    })
                    logger.warning(f"SCAN_TIMEOUT | symbol={symbol} | attempts={retries + 1} | timeout={timeout}s")
                    return None
                    
            except Exception as e:
                error_msg = str(e)
                
                if attempt < retries:
                    wait_time = (2 ** attempt) * 0.5
                    logger.debug(f"Error for {symbol}: {error_msg}, retry {attempt + 1}/{retries} in {wait_time}s")
                    await asyncio.sleep(wait_time)
                else:
                    # Final error
                    self.stats.failed_error += 1
                    self.stats.retries_total += retries
                    self.stats.failed_symbols.append({
                        "symbol": symbol,
                        "reason": f"ERROR: {error_msg[:100]}",
                        "attempts": retries + 1
                    })
                    logger.warning(f"SCAN_ERROR | symbol={symbol} | error={error_msg[:100]}")
                    return None
        
        return None
    
    def get_stats(self) -> ScanStats:
        """Get the current stats (call at end of scan)."""
        self.stats.complete()
        if self._fetch_times:
            self.stats.avg_fetch_time_seconds = sum(self._fetch_times) / len(self._fetch_times)
            self.stats.max_fetch_time_seconds = max(self._fetch_times)
        return self.stats
    
    def log_summary(self):
        """Log the scan summary."""
        stats = self.get_stats()
        stats.log_summary()
        return stats


def get_resilience_config() -> Dict[str, Any]:
    """Get the current resilience configuration."""
    return {
        "yahoo_scan_max_concurrency": YAHOO_SCAN_MAX_CONCURRENCY,
        "yahoo_timeout_seconds": YAHOO_TIMEOUT_SECONDS,
        "yahoo_max_retries": YAHOO_MAX_RETRIES,
        "semaphore_initialized": _scan_semaphore is not None,
    }
