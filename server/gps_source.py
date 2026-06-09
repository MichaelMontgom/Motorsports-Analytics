"""Bridge the blocking pyserial GPS generator onto the asyncio event loop.

`GPSReader.read_points()` is a blocking generator, so we run it in a background
thread and hand each `GPSPoint` back to the event loop with
`loop.call_soon_threadsafe`. This keeps every callback (and therefore all
calculator state) on the loop thread, so the controller needs no locks.

The thread is stopped with a `threading.Event`: `GPSReader` reads the serial
port with a 1 s timeout, so the loop notices the flag within ~1 s, then
`GPSReader.__exit__` restores 1 Hz and closes the port. This replaces the
`interrupted = [False]` SIGINT flag used by the CLI runners.
"""

import asyncio
import threading
from typing import Callable, Optional

from util.gps_reader import GPSReader, GPSPoint


OnPoint = Callable[[GPSPoint], None]
OnError = Callable[[Exception], None]
OnStopped = Callable[[], None]


class SerialGPSSource:
    """Reads a real GPS module on a background thread and delivers points to the loop."""

    def __init__(self, port: str, update_hz: int = 10):
        self.port = port
        self.update_hz = update_hz
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, on_point: OnPoint, on_error: OnError, on_stopped: OnStopped) -> None:
        """Begin reading. Callbacks are invoked on the calling thread's event loop."""
        self._loop = asyncio.get_running_loop()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(on_point, on_error, on_stopped),
            daemon=True,
        )
        self._thread.start()

    def _run(self, on_point: OnPoint, on_error: OnError, on_stopped: OnStopped) -> None:
        try:
            with GPSReader(self.port, update_hz=self.update_hz) as gps:
                for pt in gps.read_points():
                    if self._stop.is_set():
                        break
                    self._dispatch(on_point, pt)
        except Exception as exc:  # surfaced to the loop thread
            self._dispatch(on_error, exc)
        finally:
            self._dispatch(on_stopped)

    def _dispatch(self, fn, *args) -> None:
        """Schedule a callback on the loop thread if the loop is still alive."""
        if self._loop is None or self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(fn, *args)

    def stop(self, join_timeout: float = 2.0) -> None:
        """Signal the reader to stop and wait briefly for the thread to exit."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=join_timeout)
        self._thread = None
