"""
Scan Progress Tracker
=====================
In-memory progress store for live scan status.
Keyed by user_id — each user sees only their own scan progress.
Auto-cleared 60 seconds after scan finishes.
"""
from datetime import datetime, timezone
from typing import Dict, Optional

_progress: Dict[str, dict] = {}


def start(user_id: str, total_symbols: int):
    _progress[user_id] = {
        "active": True,
        "stage": "Loading market snapshot",
        "stage_index": 0,
        "total_stages": 5,
        "pct": 0,
        "current_symbol": None,
        "symbols_done": 0,
        "total_symbols": total_symbols,
        "opportunities_found": 0,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "elapsed_seconds": 0,
        "error": None,
    }


def set_stage(user_id: str, stage_index: int, stage_name: str, pct: int):
    if user_id not in _progress:
        return
    started = _progress[user_id].get("started_at")
    elapsed = 0
    if started:
        try:
            elapsed = int((datetime.now(timezone.utc) - datetime.fromisoformat(started)).total_seconds())
        except Exception:
            pass
    _progress[user_id].update({
        "stage_index": stage_index,
        "stage": stage_name,
        "pct": pct,
        "current_symbol": None,
        "elapsed_seconds": elapsed,
    })


def tick_symbol(user_id: str, symbol: str, symbols_done: int, total_symbols: int, found: int):
    if user_id not in _progress:
        return
    pct = 20 + int((symbols_done / max(total_symbols, 1)) * 50)
    started = _progress[user_id].get("started_at")
    elapsed = 0
    if started:
        try:
            elapsed = int((datetime.now(timezone.utc) - datetime.fromisoformat(started)).total_seconds())
        except Exception:
            pass
    _progress[user_id].update({
        "stage": "Scanning symbols",
        "stage_index": 1,
        "pct": pct,
        "current_symbol": symbol,
        "symbols_done": symbols_done,
        "total_symbols": total_symbols,
        "opportunities_found": found,
        "elapsed_seconds": elapsed,
    })


def finish(user_id: str, found: int, error: str = None):
    if user_id not in _progress:
        return
    started = _progress[user_id].get("started_at")
    elapsed = 0
    if started:
        try:
            elapsed = int((datetime.now(timezone.utc) - datetime.fromisoformat(started)).total_seconds())
        except Exception:
            pass
    _progress[user_id].update({
        "active": False,
        "stage": "Error" if error else "Done",
        "stage_index": 5,
        "pct": _progress[user_id].get("pct", 0) if error else 100,
        "current_symbol": None,
        "opportunities_found": found,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": elapsed,
        "error": error,
    })


def get(user_id: str) -> Optional[dict]:
    return _progress.get(user_id)


def clear(user_id: str):
    _progress.pop(user_id, None)
