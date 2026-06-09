#!/usr/bin/env python3
"""Offline tests for the websocket server: protocol, state machine, and logging.

No GPS hardware is used — a FakeGPSSource feeds scripted GPSPoints, and a
RecordingManager captures the events the controller would broadcast. A couple of
checks use FastAPI's TestClient to exercise the real /ws wiring.

Run with:  python tests/test_server.py
"""

import asyncio
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from util.gps_reader import GPSPoint
from util.geo import build_gate_from_crossing
from autocross import course as course_mod
from autocross import session_logger as auto_logger
from autocross.course import Gate, Course, save_course, load_course
from drag import session_logger as drag_logger
from drag.session_logger import append_drag_run, drag_session_path
from drag.performance_calculator import RunResult

from server import controller as controller_mod
from server.controller import SessionController, IDLE, DRAG, AUTOCROSS, MAPPING
from server.mapping_session import MappingSession, MappingError


# ---- test doubles ---------------------------------------------------------

class RecordingManager:
    """Stands in for ConnectionManager; records every emitted event."""

    def __init__(self):
        self.events = []

    def add(self, ws): pass
    def remove(self, ws): pass

    async def send(self, ws, event):
        self.events.append(event)

    async def broadcast(self, event):
        self.events.append(event)

    def types(self):
        return [e["type"] for e in self.events]

    def first(self, type_):
        return next((e for e in self.events if e["type"] == type_), None)


class FakeGPSSource:
    """Stands in for SerialGPSSource; feeds points on demand instead of from serial."""

    def __init__(self, port, update_hz=10):
        self.port = port
        self.update_hz = update_hz
        self._on_point = None
        self._running = False

    def start(self, on_point, on_error, on_stopped):
        self._on_point = on_point
        self._running = True

    def stop(self, join_timeout=2.0):
        self._running = False

    @property
    def running(self):
        return self._running

    def feed(self, points):
        for p in points:
            if not self._running:
                break
            self._on_point(p)


def _point(t, lat, lon=-83.0, speed=30.0, heading=0.0):
    return GPSPoint(timestamp=t, speed_mph=speed, latitude=lat, longitude=lon,
                    gps_time="", heading_deg=heading)


def _gate_facing_north(lat, lon, width_ft=50.0):
    latA, lonA, latB, lonB = build_gate_from_crossing(lat, lon, 0.0, width_ft)
    return Gate(name="g", lat1=latA, lon1=lonA, lat2=latB, lon2=lonB, heading_deg=0.0)


async def _flush(ctrl):
    """Await all pending broadcast tasks the controller scheduled."""
    while ctrl._tasks:
        await asyncio.gather(*list(ctrl._tasks))


def _new_controller():
    mgr = RecordingManager()
    return SessionController(mgr), mgr


# ---- pure unit tests ------------------------------------------------------

def test_mapping_session_capture_and_build():
    sess = MappingSession("My Course", width_ft=42.0)
    # No fix yet -> capture fails.
    try:
        sess.capture("start")
        assert False, "capture without a fix should raise"
    except MappingError:
        pass

    sess.update_latest(_point(0, 40.0, heading=90.0))
    sess.capture("start")
    sess.update_latest(_point(1, 40.001, heading=90.0))
    sess.capture("split")
    sess.update_latest(_point(2, 40.002, heading=90.0))
    sess.capture("split")
    sess.update_latest(_point(3, 40.003, heading=90.0))
    sess.capture("finish")

    assert sess.start_gate is not None and sess.finish_gate is not None
    assert [g.name for g in sess.splits] == ["split1", "split2"]
    course = sess.build_course()
    assert course.name == "My Course" and course.width_ft == 42.0
    assert len(course.splits) == 2
    print("ok  MappingSession capture + build_course")


def test_mapping_session_heading_safeguard():
    sess = MappingSession("C")
    sess.update_latest(_point(0, 40.0, heading=45.0))
    # A point with no heading (momentary stop) must not overwrite the bearing.
    sess.update_latest(_point(1, 40.5, heading=None))
    assert sess.latest.heading_deg == 45.0
    assert sess.latest.latitude == 40.0
    print("ok  MappingSession keeps last point with heading")


def test_mapping_build_requires_start_and_finish():
    sess = MappingSession("C")
    sess.update_latest(_point(0, 40.0, heading=0.0))
    sess.capture("start")
    try:
        sess.build_course()
        assert False, "build_course without finish should raise"
    except MappingError:
        pass
    print("ok  build_course requires start + finish")


def test_append_drag_run_roundtrip(tmp_dir):
    drag_logger.SESSIONS_DIR = tmp_dir
    result = RunResult(zero_to_sixty_s=4.2, quarter_mile_s=12.9,
                       quarter_mile_trap_mph=108.0, peak_speed_mph=110.0,
                       distance_ft=1325.0)
    path = append_drag_run(result)
    assert os.path.exists(path)
    with open(path) as f:
        runs = json.load(f)
    assert len(runs) == 1
    assert runs[0]["zero_to_sixty_s"] == 4.2
    assert "completed_at" in runs[0]
    # A second run appends rather than overwrites.
    append_drag_run(result)
    with open(path) as f:
        assert len(json.load(f)) == 2
    print("ok  append_drag_run round-trip + append")


# ---- controller (state machine) tests -------------------------------------

async def _run_drag_flow(tmp_dir):
    drag_logger.SESSIONS_DIR = tmp_dir
    controller_mod._GPS_SOURCE_FACTORY = FakeGPSSource
    ctrl, mgr = _new_controller()

    await ctrl.start_drag(hz=10, port="FAKE")
    assert ctrl.state == DRAG
    source = ctrl.source

    # Stop -> launch -> accelerate past 60 mph and 1/4 mile (≈1320 ft).
    pts = [
        _point(0.0, 40.0000, speed=0.5),   # arms (stopped)
        _point(1.0, 40.0000, speed=5.0),   # launch -> run starts here
        _point(2.0, 40.0008, speed=30.0),  # ~291 ft
        _point(3.0, 40.0016, speed=62.0),  # 0-60 captured, ~582 ft
        _point(4.0, 40.0024, speed=72.0),  # ~873 ft
        _point(5.0, 40.0032, speed=82.0),  # ~1164 ft
        _point(6.0, 40.0040, speed=92.0),  # ~1455 ft -> quarter complete
    ]
    source.feed(pts)
    await _flush(ctrl)

    run = mgr.first("run_result")
    assert run is not None, mgr.types()
    assert run["result"]["zero_to_sixty_s"] is not None
    assert run["result"]["quarter_mile_s"] is not None
    assert mgr.first("run_saved") is not None
    assert os.path.exists(drag_session_path())

    await ctrl.stop()
    await _flush(ctrl)
    assert ctrl.state == IDLE
    assert not source.running
    print("ok  controller drag flow -> run_result + run_saved + clean stop")


async def _run_autocross_flow(tmp_dir):
    course_mod.COURSES_DIR = tmp_dir
    auto_logger.SESSIONS_DIR = tmp_dir
    controller_mod._GPS_SOURCE_FACTORY = FakeGPSSource

    start = _gate_facing_north(40.0000, -83.0000)
    split = _gate_facing_north(40.0010, -83.0000)
    finish = _gate_facing_north(40.0020, -83.0000)
    save_course(Course(name="Line", start=start, finish=finish, splits=[split]))

    ctrl, mgr = _new_controller()
    await ctrl.start_autocross(course="Line", hz=10, port="FAKE")
    assert ctrl.state == AUTOCROSS
    source = ctrl.source

    lats = [39.9998, 40.00005, 40.0005, 40.00105, 40.0015, 40.00205, 40.0023]
    source.feed([_point(float(i), lat, -83.0000) for i, lat in enumerate(lats)])
    await _flush(ctrl)

    lap = mgr.first("lap_result")
    assert lap is not None, mgr.types()
    assert "track" not in lap["result"], "track must be stripped from streamed lap_result"
    assert len(lap["result"]["split_times_s"]) == 1
    assert mgr.first("run_saved") is not None
    print("ok  controller autocross flow -> lap_result (track stripped) + run_saved")


async def _run_mapping_flow(tmp_dir):
    course_mod.COURSES_DIR = tmp_dir
    controller_mod._GPS_SOURCE_FACTORY = FakeGPSSource

    ctrl, mgr = _new_controller()
    await ctrl.start_mapping(name="Mapped Course", width_ft=50.0, port="FAKE")
    assert ctrl.state == MAPPING
    source = ctrl.source

    # Drive forward; capture each gate at the latest heading-bearing point.
    source.feed([_point(0.0, 40.0000, heading=0.0)])
    await ctrl.capture_gate("start")
    source.feed([_point(1.0, 40.0010, heading=0.0)])
    await ctrl.capture_gate("split")
    source.feed([_point(2.0, 40.0020, heading=0.0)])
    await ctrl.capture_gate("finish")
    await ctrl.finish_course()
    await _flush(ctrl)

    assert mgr.first("course_saved") is not None, mgr.types()
    assert ctrl.state == IDLE
    loaded = load_course("Mapped Course")
    assert loaded.name == "Mapped Course"
    assert len(loaded.splits) == 1
    print("ok  controller mapping flow -> course_saved + load round-trip")


async def _run_guard_checks():
    controller_mod._GPS_SOURCE_FACTORY = FakeGPSSource
    ctrl, mgr = _new_controller()

    # capture_gate while idle -> error.
    await ctrl.capture_gate("start")
    await _flush(ctrl)
    assert mgr.first("error") is not None and ctrl.state == IDLE

    # Starting drag twice -> second is rejected.
    mgr.events.clear()
    await ctrl.start_drag(port="FAKE")
    await ctrl.start_drag(port="FAKE")
    await _flush(ctrl)
    errs = [e for e in mgr.events if e["type"] == "error"]
    assert errs and "while DRAG" in errs[0]["message"]

    # stop while idle -> error.
    await ctrl.stop()
    mgr.events.clear()
    await ctrl.stop()
    await _flush(ctrl)
    assert mgr.first("error") is not None
    print("ok  controller guards (capture-when-idle, double-start, stop-when-idle)")


# ---- websocket wiring (TestClient) ----------------------------------------

def test_websocket_wiring(tmp_dir):
    course_mod.COURSES_DIR = tmp_dir  # empty -> no courses
    from fastapi.testclient import TestClient
    from server.app import app

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            hello = ws.receive_json()
            assert hello["type"] == "state_changed" and hello["state"] == "IDLE"

            ws.send_json({"type": "get_state"})
            assert ws.receive_json()["type"] == "state_changed"

            ws.send_json({"type": "bogus"})
            assert ws.receive_json()["type"] == "error"

            ws.send_json({"type": "list_courses"})
            reply = ws.receive_json()
            assert reply["type"] == "courses" and reply["names"] == []

        # REST endpoint for listing serial ports.
        resp = client.get("/ports")
        assert resp.status_code == 200
        body = resp.json()
        assert "ports" in body and isinstance(body["ports"], list)
    print("ok  websocket /ws wiring + GET /ports")


def main():
    test_mapping_session_capture_and_build()
    test_mapping_session_heading_safeguard()
    test_mapping_build_requires_start_and_finish()

    with tempfile.TemporaryDirectory() as tmp:
        test_append_drag_run_roundtrip(tmp)
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(_run_drag_flow(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(_run_autocross_flow(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(_run_mapping_flow(tmp))
    asyncio.run(_run_guard_checks())
    with tempfile.TemporaryDirectory() as tmp:
        test_websocket_wiring(tmp)

    print("\nAll server tests passed.")


if __name__ == "__main__":
    main()
