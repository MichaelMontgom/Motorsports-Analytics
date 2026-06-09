# Server — GPS Timing WebSocket Backend

The `server/` package wraps the existing GPS timing engine in a **FastAPI
WebSocket** service. Python keeps doing all the work — reading the GPS module,
running the drag / autocross calculations, and logging results — and streams the
pertinent data to a UI (the Flutter app) over a single WebSocket. The UI starts
and stops the timing processes and drives course mapping.

The original CLI (`python main.py --mode ...`) is **unchanged** and still works;
the server is an additive, parallel entry point that reuses the same calculators.

For the message format the UI consumes, see **[`docs/flutter-client.md`](../docs/flutter-client.md)**.

---

## Running the server

```bash
# from the repo root, with the virtualenv active
pip install -r requirements.txt          # fastapi + uvicorn[standard] (first time)
python -m server.app
```

This starts uvicorn on **`http://127.0.0.1:8000`**. Endpoints:

- **`ws://127.0.0.1:8000/ws`** — the WebSocket the UI drives everything through.
- **`GET http://127.0.0.1:8000/ports`** — REST helper that returns the available
  serial ports as `{"ports": [{"device", "description"}]}`. Useful for a setup /
  port-picker screen before the socket is open (the same data is also available via
  the `list_ports` WebSocket command).

- Bound to **localhost only** (`127.0.0.1`). The Flutter app must run on the same
  machine, or you must add port-forwarding / change the bind (see below).
- No authentication. Only run this on a trusted machine/network.
- The GPS port is **auto-detected** (`find_gps_port`) when a mode starts; a client
  can override it per-start with a `port` field.

### Exposing it to a phone/tablet on the same network

`server/app.py`'s `main()` calls `uvicorn.run(..., host="127.0.0.1", ...)`. To let
another device on the LAN connect, change the host to `0.0.0.0` and point the
Flutter app at the machine's LAN IP (e.g. `ws://192.168.1.50:8000/ws`). Do this
only on a trusted network — there is no auth layer yet.

---

## How it works

```
GPS module (serial)
   │  GPSReader.read_points()  ── blocking generator, ~10 Hz
   ▼
SerialGPSSource (background thread)
   │  loop.call_soon_threadsafe(controller.on_point, point)
   ▼
SessionController   ── single active mode: IDLE | DRAG | AUTOCROSS | MAPPING
   │  feeds the point to the reused calculator, builds events
   ▼
ConnectionManager.broadcast(event)  ──►  every connected WebSocket  ──►  Flutter UI
                                   ◄──  client commands (start/stop/capture…)
```

### The thread ↔ asyncio bridge (`server/gps_source.py`)

`GPSReader.read_points()` is a **blocking** pyserial generator, so it can't run
directly inside FastAPI's event loop. `SerialGPSSource` runs it on a background
daemon thread and hands each `GPSPoint` back to the loop with
`loop.call_soon_threadsafe`. Because every callback then executes on the loop
thread, the controller and calculators are only ever touched from one thread — no
locks are needed.

Stopping is done with a `threading.Event`. The serial read has a 1-second
timeout, so the worker notices the stop flag within ~1 s, then `GPSReader.__exit__`
restores the module to 1 Hz and closes the port. (This replaces the
`interrupted = [False]` flag the CLI runners use.)

### The session controller (`server/controller.py`)

`SessionController` owns exactly one active mode at a time and guards illegal
transitions (e.g. you can't `start_drag` while already running, or `capture_gate`
while idle — both reply with an `error` event). On each GPS point, `on_point`
dispatches by state:

- **DRAG** → feeds `PerformanceCalculator`; on a completed run emits `run_result`,
  writes it to disk via `append_drag_run`, and emits `run_saved`.
- **AUTOCROSS** → feeds `AutocrossCalculator`; on a completed lap emits `lap_result`
  (with the large raw `track` array stripped — it's already persisted), writes it
  via `append_run`, and emits `run_saved`.
- **MAPPING** → updates the `MappingSession`'s latest heading-bearing point and
  emits `mapping_status`.

The timing logic itself is **not reimplemented** — it reuses
`drag/performance_calculator.py` and `autocross/calculator.py` exactly as the CLI
does.

### Command-driven mapping (`server/mapping_session.py`)

The CLI mapper blocked on keyboard `input()` between gates. The server version is
command-driven: each UI button press sends a `capture_gate` command, which
snapshots the most recent GPS point that carried a heading and builds a
perpendicular gate (reusing `build_gate_from_crossing` and `save_course`). A
`finish_course` command assembles and saves the `Course`.

### Files

| File | Responsibility |
|------|----------------|
| `server/app.py` | FastAPI app, `/ws` route, command dispatch, uvicorn entry |
| `server/controller.py` | `SessionController` state machine + per-point dispatch |
| `server/gps_source.py` | `SerialGPSSource` — blocking GPS thread → asyncio bridge |
| `server/mapping_session.py` | Button-driven gate capture → `Course` |
| `server/connection.py` | `ConnectionManager` — tracks sockets, broadcasts events |
| `server/protocol.py` | Event builders + command vocabulary (the wire contract) |
| `drag/session_logger.py` | `append_drag_run` — persists drag runs (new) |

Persistence (unchanged locations): courses in `courses/<slug>.json`, autocross laps
in `sessions/<course>_<date>.json`, drag runs in `sessions/drag_<date>.json`.

---

## Testing

```bash
python tests/test_autocross.py   # existing calculator/geometry tests (regression)
python tests/test_server.py      # protocol, state machine, logging, /ws wiring
```

`tests/test_server.py` needs **no GPS hardware**: a `FakeGPSSource` feeds scripted
points and a `RecordingManager` captures the events the controller would broadcast.
A couple of checks use FastAPI's `TestClient` to exercise the real `/ws` route.

### Manual smoke test (no hardware needed)

```bash
python -m server.app          # in one terminal
```

```python
# in another terminal: python - <<'PY'
import asyncio, json, websockets
async def main():
    async with websockets.connect("ws://127.0.0.1:8000/ws") as ws:
        print(json.loads(await ws.recv()))            # state_changed (IDLE)
        await ws.send(json.dumps({"type": "list_ports"}))
        print(json.loads(await ws.recv()))            # ports
asyncio.run(main())
PY
```

With the GPS module plugged in, send `{"type": "start_drag"}` and watch
`gps_point` / `live_status` stream, followed by a `run_result` after a run.
