"""Append completed drag runs to a daily session file.

Mirrors autocross/session_logger.py. Drag runs have no course, so they all go
to a single per-day file: sessions/drag_<YYYY-MM-DD>.json.
"""

import json
import os
import time
from dataclasses import asdict
from datetime import date

from drag.performance_calculator import RunResult


# sessions/ lives at the repo root (gitignored — these are personal run logs).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESSIONS_DIR = os.path.join(_REPO_ROOT, "sessions")


def drag_session_path(on: str = None) -> str:
    on = on or date.today().isoformat()
    return os.path.join(SESSIONS_DIR, f"drag_{on}.json")


def append_drag_run(result: RunResult, on: str = None) -> str:
    """Append a drag run to today's drag session file; return the path."""
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    path = drag_session_path(on)

    runs = []
    if os.path.exists(path):
        try:
            with open(path) as f:
                runs = json.load(f)
        except (json.JSONDecodeError, OSError):
            runs = []

    record = asdict(result)
    record["completed_at"] = time.time()
    runs.append(record)
    with open(path, "w") as f:
        json.dump(runs, f, indent=2)
    return path
