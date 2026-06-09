"""Append completed autocross runs (results + full raw track) to a session file."""

import json
import os
from dataclasses import asdict
from datetime import date

from autocross.course import Course, slug
from autocross.calculator import LapResult


# sessions/ lives at the repo root (gitignored — these are personal run logs).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESSIONS_DIR = os.path.join(_REPO_ROOT, "sessions")


def session_path(course: Course, on: str = None) -> str:
    on = on or date.today().isoformat()
    return os.path.join(SESSIONS_DIR, f"{slug(course.name)}_{on}.json")


def append_run(course: Course, result: LapResult) -> str:
    """Append a lap result to today's session file for this course; return the path."""
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    path = session_path(course)

    runs = []
    if os.path.exists(path):
        try:
            with open(path) as f:
                runs = json.load(f)
        except (json.JSONDecodeError, OSError):
            runs = []

    runs.append(asdict(result))
    with open(path, "w") as f:
        json.dump(runs, f, indent=2)
    return path
