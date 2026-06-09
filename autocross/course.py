"""Autocross course model and JSON persistence."""

import json
import os
import re
from dataclasses import dataclass, field, asdict
from datetime import date
from typing import List


# courses/ lives at the repo root, regardless of the working directory.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COURSES_DIR = os.path.join(_REPO_ROOT, "courses")


@dataclass
class Gate:
    name: str
    lat1: float
    lon1: float
    lat2: float
    lon2: float
    heading_deg: float


@dataclass
class Course:
    name: str
    start: Gate
    finish: Gate
    splits: List[Gate] = field(default_factory=list)
    width_ft: float = 50.0
    created: str = field(default_factory=lambda: date.today().isoformat())


def slug(name: str) -> str:
    """Filesystem-safe slug for a course name (e.g. 'Test Course' -> 'test-course')."""
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower())
    return s.strip("-") or "course"


def course_path(name: str) -> str:
    return os.path.join(COURSES_DIR, f"{slug(name)}.json")


def save_course(course: Course) -> str:
    """Write the course to courses/<slug>.json and return the path."""
    os.makedirs(COURSES_DIR, exist_ok=True)
    path = course_path(course.name)
    with open(path, "w") as f:
        json.dump(asdict(course), f, indent=2)
    return path


def load_course(name: str) -> Course:
    """Load a course by name (looked up by slug)."""
    path = course_path(name)
    with open(path) as f:
        data = json.load(f)
    return _course_from_dict(data)


def list_courses() -> List[str]:
    """Return the names of all saved courses, sorted."""
    if not os.path.isdir(COURSES_DIR):
        return []
    names = []
    for fname in os.listdir(COURSES_DIR):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(COURSES_DIR, fname)) as f:
                names.append(json.load(f)["name"])
        except (json.JSONDecodeError, KeyError, OSError):
            continue
    return sorted(names)


def _course_from_dict(data: dict) -> Course:
    return Course(
        name=data["name"],
        start=Gate(**data["start"]),
        finish=Gate(**data["finish"]),
        splits=[Gate(**g) for g in data.get("splits", [])],
        width_ft=data.get("width_ft", 50.0),
        created=data.get("created", date.today().isoformat()),
    )
