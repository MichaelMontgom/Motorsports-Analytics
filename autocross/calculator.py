"""Gate-based autocross lap timing engine."""

from dataclasses import dataclass, field
from typing import List, Optional

from util.gps_reader import GPSPoint
from util.geo import haversine_feet, gate_crossing
from autocross.course import Course


ARMED = "ARMED"
RUNNING = "RUNNING"


@dataclass
class LapResult:
    course_name: str
    total_time_s: float
    split_times_s: List[float]          # cumulative seconds at each intermediate gate
    peak_speed_mph: float
    distance_ft: float
    start_timestamp: float
    track: List[GPSPoint] = field(default_factory=list)


def _interp_time(prev: GPSPoint, cur: GPSPoint, t: float) -> float:
    """Interpolate the crossing timestamp a fraction t along prev→cur."""
    return prev.timestamp + t * (cur.timestamp - prev.timestamp)


class AutocrossCalculator:
    """State machine that times a lap across a course's start/split/finish gates.

    Usage:
        calc = AutocrossCalculator(course)
        for point in gps.read_points():
            result = calc.feed(point)
            if result:
                print(result)   # lap finished
    """

    def __init__(self, course: Course):
        self.course = course
        self.reset()

    @property
    def in_run(self) -> bool:
        return self._state == RUNNING

    def reset(self) -> None:
        self._state = ARMED
        self._prev: Optional[GPSPoint] = None
        self._next_split_index = 0
        self._t0: Optional[float] = None
        self._track: List[GPSPoint] = []
        self._split_times: List[float] = []
        self._peak = 0.0
        self._dist = 0.0

    def feed(self, point: GPSPoint) -> Optional[LapResult]:
        """Feed the next GPS point. Returns a LapResult when the lap finishes, else None."""
        prev = self._prev
        self._prev = point
        if prev is None:
            return None

        if self._state == ARMED:
            t = gate_crossing(prev, point, self.course.start)
            if t is not None:
                self._t0 = _interp_time(prev, point, t)
                self._state = RUNNING
                self._track = [point]
                self._peak = point.speed_mph
                self._dist = 0.0
            return None

        # RUNNING
        self._track.append(point)
        self._dist += haversine_feet(
            prev.latitude, prev.longitude, point.latitude, point.longitude
        )
        self._peak = max(self._peak, point.speed_mph)

        # Next intermediate split, taken strictly in order.
        if self._next_split_index < len(self.course.splits):
            gate = self.course.splits[self._next_split_index]
            t = gate_crossing(prev, point, gate)
            if t is not None:
                self._split_times.append(_interp_time(prev, point, t) - self._t0)
                self._next_split_index += 1

        # Finish line.
        t = gate_crossing(prev, point, self.course.finish)
        if t is not None:
            total = _interp_time(prev, point, t) - self._t0
            result = LapResult(
                course_name=self.course.name,
                total_time_s=total,
                split_times_s=list(self._split_times),
                peak_speed_mph=self._peak,
                distance_ft=self._dist,
                start_timestamp=self._t0,
                track=list(self._track),
            )
            self.reset()
            return result

        return None

    def partial_result(self) -> Optional[LapResult]:
        """Mid-lap snapshot for live display, or None if not currently running."""
        if self._state != RUNNING or self._t0 is None:
            return None
        elapsed = (self._prev.timestamp - self._t0) if self._prev else 0.0
        return LapResult(
            course_name=self.course.name,
            total_time_s=elapsed,
            split_times_s=list(self._split_times),
            peak_speed_mph=self._peak,
            distance_ft=self._dist,
            start_timestamp=self._t0,
            track=list(self._track),
        )
