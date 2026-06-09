"""Command-driven autocross course mapping.

Replaces the blocking `input()` flow in autocross/mapper.py: instead of the user
pressing Enter at a terminal, the UI sends a `capture_gate` command (a button
press). Each capture snapshots the most recent GPS point that carried a heading
and builds a perpendicular gate, exactly as `autocross/mapper._capture_gate`
did. Reuses build_gate_from_crossing and the Gate/Course model + save_course.
"""

from typing import List, Optional

from util.gps_reader import GPSPoint
from util.geo import build_gate_from_crossing
from autocross.course import Gate, Course, save_course


VALID_ROLES = ("start", "split", "finish")


class MappingError(Exception):
    """Raised for invalid mapping operations (no fix, bad role, missing gate)."""


class MappingSession:
    """Accumulates start/split/finish gates from button-driven captures."""

    def __init__(self, name: str, width_ft: float = 50.0):
        self.name = name
        self.width_ft = width_ft
        # Only updated with points that carry a heading, so a momentary stop
        # (which blanks the NMEA course) doesn't lose the bearing.
        self.latest: Optional[GPSPoint] = None
        self.start_gate: Optional[Gate] = None
        self.splits: List[Gate] = []
        self.finish_gate: Optional[Gate] = None
        self._split_counter = 0

    def update_latest(self, point: GPSPoint) -> None:
        if point.heading_deg is not None:
            self.latest = point

    @property
    def has_heading_fix(self) -> bool:
        return self.latest is not None

    def capture(self, role: str, name: Optional[str] = None) -> Gate:
        """Snapshot the current point into a gate for the given role."""
        if role not in VALID_ROLES:
            raise MappingError(f"unknown gate role '{role}' (expected one of {VALID_ROLES})")
        if self.latest is None:
            raise MappingError("no GPS fix with heading yet — drive forward a little first")

        pt = self.latest
        if role == "split":
            self._split_counter += 1
            gate_name = name or f"split{self._split_counter}"
        else:
            gate_name = name or role

        latA, lonA, latB, lonB = build_gate_from_crossing(
            pt.latitude, pt.longitude, pt.heading_deg, self.width_ft
        )
        gate = Gate(name=gate_name, lat1=latA, lon1=lonA, lat2=latB, lon2=lonB,
                    heading_deg=pt.heading_deg)

        if role == "start":
            self.start_gate = gate
        elif role == "finish":
            self.finish_gate = gate
        else:
            self.splits.append(gate)
        return gate

    def captured_summary(self) -> List[dict]:
        """Lightweight list of captured gates for status events."""
        out = []
        if self.start_gate:
            out.append({"role": "start", "name": self.start_gate.name,
                        "heading_deg": self.start_gate.heading_deg})
        for g in self.splits:
            out.append({"role": "split", "name": g.name, "heading_deg": g.heading_deg})
        if self.finish_gate:
            out.append({"role": "finish", "name": self.finish_gate.name,
                        "heading_deg": self.finish_gate.heading_deg})
        return out

    def build_course(self) -> Course:
        """Assemble the captured gates into a Course (requires start + finish)."""
        if self.start_gate is None:
            raise MappingError("cannot finish: START gate not captured")
        if self.finish_gate is None:
            raise MappingError("cannot finish: FINISH gate not captured")
        return Course(name=self.name, start=self.start_gate, finish=self.finish_gate,
                      splits=list(self.splits), width_ft=self.width_ft)

    def save(self) -> tuple[Course, str]:
        course = self.build_course()
        path = save_course(course)
        return course, path
