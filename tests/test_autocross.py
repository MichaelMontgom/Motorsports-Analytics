#!/usr/bin/env python3
"""Offline tests for autocross geometry, timing, and course persistence.

Run with:  python tests/test_autocross.py   (asserts only, no GPS hardware)
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from util.gps_reader import GPSPoint
from util.geo import build_gate_from_crossing, gate_crossing
from autocross import course as course_mod
from autocross.course import Gate, Course, save_course, load_course
from autocross.calculator import AutocrossCalculator


def _point(t, lat, lon, speed=30.0, heading=0.0):
    return GPSPoint(timestamp=t, speed_mph=speed, latitude=lat, longitude=lon,
                    gps_time="", heading_deg=heading)


def _gate_facing_north(lat, lon, width_ft=50.0):
    """A gate centered at (lat, lon) that a northbound (heading 0°) car crosses."""
    latA, lonA, latB, lonB = build_gate_from_crossing(lat, lon, 0.0, width_ft)
    return Gate(name="g", lat1=latA, lon1=lonA, lat2=latB, lon2=lonB, heading_deg=0.0)


def test_gate_crossing_forward_and_interpolation():
    gate = _gate_facing_north(40.0000, -83.0000)
    # Northbound drive: prev just south of the line, cur just north of it.
    prev = _point(100.0, 39.99995, -83.0000)
    cur = _point(101.0, 40.00005, -83.0000)
    t = gate_crossing(prev, cur, gate)
    assert t is not None, "northbound pass should cross the gate"
    assert 0.0 <= t <= 1.0, f"fraction out of range: {t}"
    crossing_time = prev.timestamp + t * (cur.timestamp - prev.timestamp)
    assert prev.timestamp <= crossing_time <= cur.timestamp
    # The line is centered between prev and cur, so t ~ 0.5.
    assert abs(t - 0.5) < 0.1, f"expected ~0.5, got {t}"
    print("ok  gate_crossing forward + interpolation")


def test_gate_crossing_wrong_direction():
    gate = _gate_facing_north(40.0000, -83.0000)
    # Southbound drive across the same line — opposite the gate heading.
    prev = _point(100.0, 40.00005, -83.0000)
    cur = _point(101.0, 39.99995, -83.0000)
    assert gate_crossing(prev, cur, gate) is None, "wrong-direction pass must not trigger"
    print("ok  gate_crossing rejects wrong direction")


def test_autocross_calculator_full_lap():
    # Build start, one split, and finish gates along a northbound straight line.
    start = _gate_facing_north(40.0000, -83.0000)
    split = _gate_facing_north(40.0010, -83.0000)
    finish = _gate_facing_north(40.0020, -83.0000)
    course = Course(name="Line", start=start, finish=finish, splits=[split])
    calc = AutocrossCalculator(course)

    # Scripted northbound track at 1 Hz; latitudes straddle each gate.
    lats = [39.9998, 40.00005, 40.0005, 40.00105, 40.0015, 40.00205, 40.0023]
    result = None
    for i, lat in enumerate(lats):
        result = calc.feed(_point(float(i), lat, -83.0000)) or result

    assert result is not None, "lap should complete after crossing finish"
    assert len(result.split_times_s) == 1, "exactly one split expected"
    # Start crossed ~t=1.0, split ~t=3.0, finish ~t=5.0 → split ~2s, total ~4s.
    assert abs(result.split_times_s[0] - 2.0) < 0.3, result.split_times_s
    assert abs(result.total_time_s - 4.0) < 0.3, result.total_time_s
    assert result.distance_ft > 0
    print("ok  AutocrossCalculator full lap (split + total)")


def test_autocross_calculator_backward_ignored():
    start = _gate_facing_north(40.0000, -83.0000)
    finish = _gate_facing_north(40.0020, -83.0000)
    course = Course(name="Line", start=start, finish=finish, splits=[])
    calc = AutocrossCalculator(course)
    # Southbound track should never arm.
    for i, lat in enumerate([40.0005, 40.00005, 39.9998]):
        assert calc.feed(_point(float(i), lat, -83.0000)) is None
    assert not calc.in_run, "backward pass must not start a run"
    print("ok  AutocrossCalculator ignores backward start")


def test_course_roundtrip(tmp_dir):
    course_mod.COURSES_DIR = tmp_dir
    start = _gate_facing_north(40.0, -83.0)
    finish = _gate_facing_north(40.002, -83.0)
    split = _gate_facing_north(40.001, -83.0)
    original = Course(name="Round Trip", start=start, finish=finish,
                      splits=[split], width_ft=42.0)
    save_course(original)
    loaded = load_course("Round Trip")
    assert loaded == original, "round-tripped course must equal the original"
    print("ok  course save/load round-trip")


def main():
    test_gate_crossing_forward_and_interpolation()
    test_gate_crossing_wrong_direction()
    test_autocross_calculator_full_lap()
    test_autocross_calculator_backward_ignored()
    with tempfile.TemporaryDirectory() as tmp:
        test_course_roundtrip(tmp)
    print("\nAll autocross tests passed.")


if __name__ == "__main__":
    main()
