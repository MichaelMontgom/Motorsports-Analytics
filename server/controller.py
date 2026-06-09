"""SessionController: owns the single active timing mode and processes GPS points.

Exactly one mode runs at a time (IDLE / DRAG / AUTOCROSS / MAPPING). The GPS
source delivers points to `on_point` on the event-loop thread, so the
calculators and all state here are touched from a single thread — no locks.

The existing calculators (PerformanceCalculator, AutocrossCalculator) and
loggers (append_run, append_drag_run) are reused verbatim; this class just wires
them to the websocket event stream.
"""

import asyncio
from typing import Optional, Set

import serial.tools.list_ports

from util.gps_reader import GPSPoint, find_gps_port
from drag.performance_calculator import PerformanceCalculator
from drag.session_logger import append_drag_run
from autocross.calculator import AutocrossCalculator
from autocross.course import load_course, list_courses
from autocross.session_logger import append_run

from server import protocol
from server.connection import ConnectionManager
from server.gps_source import SerialGPSSource
from server.mapping_session import MappingSession, MappingError


IDLE = "IDLE"
DRAG = "DRAG"
AUTOCROSS = "AUTOCROSS"
MAPPING = "MAPPING"

_GPS_SOURCE_FACTORY = SerialGPSSource  # swappable for tests


def available_ports() -> list:
    """List serial ports as {device, description} dicts (shared by WS + REST)."""
    return [{"device": p.device, "description": p.description}
            for p in serial.tools.list_ports.comports()]


class SessionController:
    def __init__(self, manager: ConnectionManager):
        self.manager = manager
        self.state = IDLE
        self.source: Optional[SerialGPSSource] = None
        self.drag_calc: Optional[PerformanceCalculator] = None
        self.auto_calc: Optional[AutocrossCalculator] = None
        self.mapping: Optional[MappingSession] = None
        self.course = None
        self.course_name: Optional[str] = None
        self.run_number = 0
        self.hz: Optional[int] = None
        self.port: Optional[str] = None
        self._expect_stop = False
        self._tasks: Set[asyncio.Task] = set()  # keep strong refs to fire-and-forget tasks

    # ---- event emission --------------------------------------------------

    def _emit(self, event: dict) -> None:
        """Schedule a broadcast from any code running on the loop thread."""
        task = asyncio.create_task(self.manager.broadcast(event))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def state_event(self) -> dict:
        return protocol.state_changed(
            self.state,
            mode=None if self.state == IDLE else self.state.lower(),
            course=self.course_name,
            run_number=self.run_number,
            hz=self.hz,
            port=self.port,
        )

    # ---- lifecycle helpers ----------------------------------------------

    def _resolve_port(self, port: Optional[str]) -> str:
        resolved = port or find_gps_port()
        if not resolved:
            raise MappingError(  # reused as a generic user-facing error
                "could not auto-detect a GPS port; pass an explicit 'port'")
        return resolved

    def _start_source(self, port: str, hz: int) -> None:
        self._expect_stop = False
        self.port = port
        self.hz = hz
        self.source = _GPS_SOURCE_FACTORY(port, update_hz=hz)
        self.source.start(self.on_point, self.on_error, self.on_stopped)

    def _reset_to_idle(self) -> None:
        self.state = IDLE
        self.source = None
        self.drag_calc = None
        self.auto_calc = None
        self.mapping = None
        self.course = None
        self.course_name = None
        self.hz = None
        self.port = None

    # ---- start commands --------------------------------------------------

    async def start_drag(self, hz: int = 10, port: Optional[str] = None) -> None:
        if self.state != IDLE:
            self._emit(protocol.error(f"cannot start drag while {self.state}", "start_drag"))
            return
        try:
            resolved = self._resolve_port(port)
        except MappingError as exc:
            self._emit(protocol.error(str(exc), "start_drag"))
            return
        self.drag_calc = PerformanceCalculator()
        self.run_number = 0
        self.state = DRAG
        self._start_source(resolved, hz)
        self._emit(self.state_event())

    async def start_autocross(self, course: str, hz: int = 10, port: Optional[str] = None) -> None:
        if self.state != IDLE:
            self._emit(protocol.error(f"cannot start autocross while {self.state}", "start_autocross"))
            return
        if not course:
            self._emit(protocol.error("start_autocross requires 'course'", "start_autocross"))
            return
        try:
            loaded = load_course(course)
        except (FileNotFoundError, OSError, KeyError) as exc:
            self._emit(protocol.error(f"course '{course}' not found: {exc}", "start_autocross"))
            return
        try:
            resolved = self._resolve_port(port)
        except MappingError as exc:
            self._emit(protocol.error(str(exc), "start_autocross"))
            return
        self.course = loaded
        self.course_name = loaded.name
        self.auto_calc = AutocrossCalculator(loaded)
        self.run_number = 0
        self.state = AUTOCROSS
        self._start_source(resolved, hz)
        self._emit(self.state_event())

    async def start_mapping(self, name: str, width_ft: float = 50.0,
                            hz: int = 10, port: Optional[str] = None) -> None:
        if self.state != IDLE:
            self._emit(protocol.error(f"cannot start mapping while {self.state}", "start_mapping"))
            return
        if not name:
            self._emit(protocol.error("start_mapping requires 'name'", "start_mapping"))
            return
        try:
            resolved = self._resolve_port(port)
        except MappingError as exc:
            self._emit(protocol.error(str(exc), "start_mapping"))
            return
        self.mapping = MappingSession(name=name, width_ft=width_ft)
        self.course_name = name
        self.state = MAPPING
        self._start_source(resolved, hz)
        self._emit(self.state_event())

    # ---- mapping commands ------------------------------------------------

    async def capture_gate(self, role: str, name: Optional[str] = None) -> None:
        if self.state != MAPPING:
            self._emit(protocol.error("not currently mapping", "capture_gate"))
            return
        try:
            gate = self.mapping.capture(role, name)
        except MappingError as exc:
            self._emit(protocol.error(str(exc), "capture_gate"))
            return
        self._emit(protocol.gate_captured(role, gate))
        self._emit(protocol.mapping_status(self.mapping))

    async def finish_course(self) -> None:
        if self.state != MAPPING:
            self._emit(protocol.error("not currently mapping", "finish_course"))
            return
        try:
            course, path = self.mapping.save()
        except MappingError as exc:
            self._emit(protocol.error(str(exc), "finish_course"))
            return
        self._emit(protocol.course_saved(course, path))
        await self._stop_source_and_idle()

    async def cancel_mapping(self) -> None:
        if self.state != MAPPING:
            self._emit(protocol.error("not currently mapping", "cancel_mapping"))
            return
        await self._stop_source_and_idle()

    # ---- stop ------------------------------------------------------------

    async def stop(self) -> None:
        if self.state == IDLE:
            self._emit(protocol.error("nothing is running", "stop"))
            return
        # Mirror the CLI runners: surface a partial result if a run was in progress.
        if self.state == DRAG and self.drag_calc and self.drag_calc.in_run:
            partial = self.drag_calc.partial_result()
            if partial.distance_ft > 0:
                self.run_number += 1
                self._emit(protocol.run_result(self.run_number, partial))
        elif self.state == AUTOCROSS and self.auto_calc:
            partial = self.auto_calc.partial_result()
            if partial is not None:
                self._emit(protocol.live_status(partial, in_run=True))
        await self._stop_source_and_idle()

    async def _stop_source_and_idle(self) -> None:
        self._expect_stop = True
        if self.source is not None:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self.source.stop)
        self._reset_to_idle()
        self._emit(self.state_event())

    async def shutdown(self) -> None:
        """Called on server shutdown to join any running GPS thread."""
        if self.source is not None:
            self._expect_stop = True
            await asyncio.get_running_loop().run_in_executor(None, self.source.stop)

    # ---- query commands --------------------------------------------------

    async def send_state(self, ws) -> None:
        await self.manager.send(ws, self.state_event())

    async def list_courses(self) -> None:
        self._emit(protocol.courses(list_courses()))

    async def list_ports(self) -> None:
        self._emit(protocol.ports(available_ports()))

    # ---- GPS callbacks (loop thread) ------------------------------------

    def on_point(self, pt: GPSPoint) -> None:
        if self.state == DRAG:
            self._emit(protocol.gps_point(pt))
            result = self.drag_calc.feed(pt)
            if result is not None:
                self.run_number += 1
                self._emit(protocol.run_result(self.run_number, result))
                path = append_drag_run(result)
                self._emit(protocol.run_saved(path))
            else:
                self._emit(protocol.live_status(self.drag_calc.partial_result(),
                                                in_run=self.drag_calc.in_run))
        elif self.state == AUTOCROSS:
            self._emit(protocol.gps_point(pt))
            result = self.auto_calc.feed(pt)
            if result is not None:
                self.run_number += 1
                self._emit(protocol.lap_result(self.run_number, result))
                path = append_run(self.course, result)
                self._emit(protocol.run_saved(path))
            else:
                self._emit(protocol.live_status(self.auto_calc.partial_result(),
                                                in_run=self.auto_calc.in_run))
        elif self.state == MAPPING:
            self.mapping.update_latest(pt)
            self._emit(protocol.gps_point(pt))
            self._emit(protocol.mapping_status(self.mapping))

    def on_error(self, exc: Exception) -> None:
        self._emit(protocol.error(f"GPS error: {exc}"))

    def on_stopped(self) -> None:
        if self._expect_stop:
            return  # a deliberate stop() already handled the state transition
        # The reader ended on its own (cable unplugged, fatal error).
        self._emit(protocol.gps_stopped("GPS reader ended unexpectedly"))
        self._reset_to_idle()
        self._emit(self.state_event())
