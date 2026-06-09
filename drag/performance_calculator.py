from dataclasses import dataclass
from typing import Optional, List
from util.gps_reader import GPSPoint
from util.geo import haversine_feet


QUARTER_MILE_FEET = 1320.0

# Speed thresholds
LAUNCH_SPEED_MPH  = 2.0    # Must exceed this to start a run
ZERO_SPEED_MPH    = 1.0    # Below this is considered stopped
TARGET_60_MPH     = 60.0
TARGET_1320_FT    = QUARTER_MILE_FEET


@dataclass
class RunResult:
    zero_to_sixty_s: Optional[float] = None      # seconds
    quarter_mile_s: Optional[float] = None        # seconds
    quarter_mile_trap_mph: Optional[float] = None # mph at 1320 ft
    peak_speed_mph: float = 0.0
    distance_ft: float = 0.0


@dataclass
class _RunState:
    start_time: float
    start_lat: float
    start_lon: float
    prev_point: GPSPoint
    sixty_time: Optional[float] = None
    quarter_time: Optional[float] = None
    quarter_trap_speed: Optional[float] = None
    peak_speed: float = 0.0
    distance_ft: float = 0.0
    complete: bool = False


class PerformanceCalculator:
    """
    State machine that ingests GPSPoints and detects:
      - 0-60 mph time
      - Quarter mile (1/4 mile) elapsed time and trap speed

    Usage:
        calc = PerformanceCalculator()
        for point in gps_reader.read_points():
            result = calc.feed(point)
            if result:
                print(result)   # run finished
    """

    def __init__(self):
        self._run: Optional[_RunState] = None
        self._waiting_for_stop = True   # True until vehicle is stopped and ready

    @property
    def in_run(self) -> bool:
        return self._run is not None

    @property
    def current_distance_ft(self) -> float:
        return self._run.distance_ft if self._run else 0.0

    def reset(self) -> None:
        self._run = None
        self._waiting_for_stop = True

    def feed(self, point: GPSPoint) -> Optional[RunResult]:
        """
        Feed the next GPS point.  Returns a RunResult when the run is complete
        (both 0-60 and quarter mile captured, or user aborts), otherwise None.
        """
        speed = point.speed_mph

        # --- Idle: wait for the car to be stopped before arming ---
        if self._waiting_for_stop:
            if speed < ZERO_SPEED_MPH:
                self._waiting_for_stop = False
            return None

        # --- Armed and not yet in a run: wait for launch ---
        if self._run is None:
            if speed >= LAUNCH_SPEED_MPH:
                self._run = _RunState(
                    start_time=point.timestamp,
                    start_lat=point.latitude,
                    start_lon=point.longitude,
                    prev_point=point,
                    peak_speed=speed,
                )
            return None

        # --- Active run ---
        run = self._run
        elapsed = point.timestamp - run.start_time

        # Accumulate distance via haversine between consecutive points
        run.distance_ft += haversine_feet(
            run.prev_point.latitude, run.prev_point.longitude,
            point.latitude, point.longitude,
        )
        run.prev_point = point
        run.peak_speed = max(run.peak_speed, speed)

        # 0-60 capture
        if run.sixty_time is None and speed >= TARGET_60_MPH:
            run.sixty_time = elapsed

        # Quarter mile capture (interpolate to exact 1320 ft crossing)
        if run.quarter_time is None and run.distance_ft >= TARGET_1320_FT:
            run.quarter_time = elapsed
            run.quarter_trap_speed = speed
            run.complete = True

        if run.complete:
            result = RunResult(
                zero_to_sixty_s=run.sixty_time,
                quarter_mile_s=run.quarter_time,
                quarter_mile_trap_mph=run.quarter_trap_speed,
                peak_speed_mph=run.peak_speed,
                distance_ft=run.distance_ft,
            )
            self._run = None
            self._waiting_for_stop = True
            return result

        return None

    def partial_result(self) -> RunResult:
        """Return whatever data has been captured so far (mid-run snapshot)."""
        if not self._run:
            return RunResult()
        run = self._run
        return RunResult(
            zero_to_sixty_s=run.sixty_time,
            quarter_mile_s=run.quarter_time,
            quarter_mile_trap_mph=run.quarter_trap_speed,
            peak_speed_mph=run.peak_speed,
            distance_ft=run.distance_ft,
        )
