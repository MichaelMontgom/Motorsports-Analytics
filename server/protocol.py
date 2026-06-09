"""WebSocket message schema: client commands and server event builders.

Every message is a JSON object with a ``type`` field. Result payloads are built
by ``dataclasses.asdict`` on the existing GPSPoint / RunResult / LapResult /
Course / Gate dataclasses — there is no parallel schema to keep in sync.

This module is the single source of truth for the wire format the Flutter UI
consumes.
"""

from dataclasses import asdict
from typing import Optional

from util.gps_reader import GPSPoint
from drag.performance_calculator import RunResult
from autocross.calculator import LapResult
from autocross.course import Course, Gate


# ---- Command vocabulary (client -> server) --------------------------------
# Documented here for reference; dispatch lives in server.controller.
COMMANDS = (
    "start_drag",      # {hz?, port?}
    "start_autocross", # {course, hz?, port?}
    "start_mapping",   # {name, width_ft?, hz?, port?}
    "capture_gate",    # {role: start|split|finish, name?}
    "finish_course",   # {}
    "cancel_mapping",  # {}
    "stop",            # {}
    "list_courses",    # {}
    "list_ports",      # {}
    "get_state",       # {}
)


# ---- Event builders (server -> client) ------------------------------------

def state_changed(state: str, *, mode: Optional[str] = None,
                  course: Optional[str] = None, run_number: int = 0,
                  hz: Optional[int] = None, port: Optional[str] = None) -> dict:
    return {
        "type": "state_changed",
        "state": state,
        "mode": mode,
        "course": course,
        "run_number": run_number,
        "hz": hz,
        "port": port,
    }


def gps_point(point: GPSPoint) -> dict:
    return {"type": "gps_point", "point": asdict(point)}


def live_status(partial, *, in_run: bool) -> dict:
    return {
        "type": "live_status",
        "in_run": in_run,
        "partial": asdict(partial) if partial is not None else None,
    }


def run_result(run_number: int, result: RunResult) -> dict:
    return {"type": "run_result", "run_number": run_number, "result": asdict(result)}


def lap_result(run_number: int, result: LapResult) -> dict:
    """Autocross lap result with the large raw track stripped (it's persisted to disk)."""
    payload = asdict(result)
    payload.pop("track", None)
    return {"type": "lap_result", "run_number": run_number, "result": payload}


def run_saved(path: str) -> dict:
    return {"type": "run_saved", "path": path}


def mapping_status(session) -> dict:
    return {
        "type": "mapping_status",
        "name": session.name,
        "width_ft": session.width_ft,
        "captured": session.captured_summary(),
        "has_heading_fix": session.has_heading_fix,
        "latest_heading": session.latest.heading_deg if session.latest else None,
    }


def gate_captured(role: str, gate: Gate) -> dict:
    return {"type": "gate_captured", "role": role, "gate": asdict(gate)}


def course_saved(course: Course, path: str) -> dict:
    return {"type": "course_saved", "course": asdict(course), "path": path}


def courses(names: list) -> dict:
    return {"type": "courses", "names": names}


def ports(port_list: list) -> dict:
    return {"type": "ports", "ports": port_list}


def error(message: str, command: Optional[str] = None) -> dict:
    return {"type": "error", "message": message, "command": command}


def gps_stopped(reason: Optional[str] = None) -> dict:
    return {"type": "gps_stopped", "reason": reason}
