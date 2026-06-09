"""Interactive drive-through course mapping.

Drive across each line and press Enter; the app snapshots the current GPS point
+ heading and builds a perpendicular gate of the given width.
"""

import threading
import time
from typing import Optional

from util.gps_reader import GPSReader, GPSPoint
from util.geo import build_gate_from_crossing
from autocross.course import Gate, Course, save_course


class _GPSStream(threading.Thread):
    """Background reader that keeps the latest GPS point that carries a heading."""

    def __init__(self, port: str, hz: int, interrupted: list):
        super().__init__(daemon=True)
        self.port = port
        self.hz = hz
        self.interrupted = interrupted
        self._latest: Optional[GPSPoint] = None
        self._lock = threading.Lock()
        self.error: Optional[Exception] = None

    def run(self) -> None:
        try:
            with GPSReader(self.port, update_hz=self.hz) as gps:
                for pt in gps.read_points():
                    if self.interrupted[0]:
                        break
                    # Keep the last point with a real heading so a momentary stop
                    # (which blanks the NMEA course) doesn't lose the bearing.
                    if pt.heading_deg is not None:
                        with self._lock:
                            self._latest = pt
        except Exception as exc:  # surfaced to the main thread
            self.error = exc

    def latest(self) -> Optional[GPSPoint]:
        with self._lock:
            return self._latest


def _capture_gate(label: str, gate_name: str, stream: _GPSStream, width_ft: float) -> Gate:
    input(f"  → Drive across the {label} line, then press Enter...")
    pt = stream.latest()
    latA, lonA, latB, lonB = build_gate_from_crossing(
        pt.latitude, pt.longitude, pt.heading_deg, width_ft
    )
    gate = Gate(name=gate_name, lat1=latA, lon1=lonA, lat2=latB, lon2=lonB,
                heading_deg=pt.heading_deg)
    print(f"    {label} captured @ heading {pt.heading_deg:.0f}°  "
          f"A=({latA:.6f}, {lonA:.6f})  B=({latB:.6f}, {lonB:.6f})")
    return gate


def map_course(port: str, hz: int, name: str, width_ft: float, interrupted: list) -> Optional[Course]:
    """Run the interactive mapping flow and save the resulting course."""
    stream = _GPSStream(port, hz, interrupted)
    stream.start()

    print(f"\nMapping course '{name}'  (gate width {width_ft:.0f} ft)")
    print("Waiting for a GPS fix with heading — drive forward a little...")
    while stream.latest() is None:
        if interrupted[0]:
            return None
        if stream.error is not None:
            raise stream.error
        time.sleep(0.2)
    print("Got it.\n")

    start_gate = _capture_gate("START", "start", stream, width_ft)

    splits = []
    i = 1
    while True:
        ans = input(f"  Add split #{i}? [Enter = yes, type 'done' to finish]: ").strip().lower()
        if interrupted[0]:
            return None
        if ans == "done":
            break
        splits.append(_capture_gate(f"SPLIT {i}", f"split{i}", stream, width_ft))
        i += 1

    finish_gate = _capture_gate("FINISH", "finish", stream, width_ft)

    course = Course(name=name, start=start_gate, finish=finish_gate,
                    splits=splits, width_ft=width_ft)
    path = save_course(course)
    print(f"\nSaved course to {path}")
    return course
