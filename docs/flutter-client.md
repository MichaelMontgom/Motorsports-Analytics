# Flutter Client — WebSocket Protocol Reference

This is the contract between the Flutter UI and the Python timing server. The
server reads the GPS, runs all calculations, and streams results; the UI sends
commands to start/stop modes and to map courses. The authoritative source for
this format is [`server/protocol.py`](../server/protocol.py).

- **Endpoint:** `ws://<host>:8000/ws` (default `ws://127.0.0.1:8000/ws`)
- **REST helper:** `GET http://<host>:8000/ports` returns
  `{"ports": [{"device", "description"}]}` — list serial ports for a setup/port-picker
  screen without opening the socket. (Same data as the `list_ports` command below.)
- **Encoding:** every message is a single JSON object with a `"type"` field.
- **On connect:** the server immediately sends one `state_changed` event so the UI
  knows the current mode.
- **Broadcast:** all events go to every connected client. Commands can come from
  any client.

> Dart: use `web_socket_channel`. Send with
> `channel.sink.add(jsonEncode({...}))`; read by decoding each string on
> `channel.stream` and switching on `msg['type']`.

---

## Commands (UI → server)

| `type` | Fields | Valid when | Effect |
|--------|--------|-----------|--------|
| `start_drag` | `hz?` (1/5/10, default 10), `port?` | IDLE | Start 0-60 / ¼-mile timing |
| `start_autocross` | `course` (name), `hz?`, `port?` | IDLE | Load course, start lap timing |
| `start_mapping` | `name`, `width_ft?` (default 50), `hz?`, `port?` | IDLE | Begin button-driven course mapping |
| `capture_gate` | `role` (`start`\|`split`\|`finish`), `name?` | MAPPING | Snapshot current position into a gate |
| `finish_course` | — | MAPPING | Assemble + save the course, return to IDLE |
| `cancel_mapping` | — | MAPPING | Discard mapping, return to IDLE |
| `stop` | — | DRAG/AUTOCROSS/MAPPING | Stop the active mode, return to IDLE |
| `list_courses` | — | any | Reply with a `courses` event |
| `list_ports` | — | any | Reply with a `ports` event |
| `get_state` | — | any | Reply with a `state_changed` event |

`port` is optional everywhere — omit it to let the server auto-detect the GPS
module. Invalid commands (wrong state, missing fields, no GPS fix yet, unknown
type) never close the socket; they reply with an `error` event.

### Examples

```json
{ "type": "start_drag", "hz": 10 }
{ "type": "start_autocross", "course": "Test Course" }
{ "type": "start_mapping", "name": "My Course", "width_ft": 50 }
{ "type": "capture_gate", "role": "split" }
{ "type": "finish_course" }
{ "type": "stop" }
```

---

## Events (server → UI)

### `state_changed`
Current mode. Sent on connect, after every start/stop, and in reply to `get_state`.
```json
{ "type": "state_changed", "state": "DRAG", "mode": "drag",
  "course": null, "run_number": 0, "hz": 10, "port": "/dev/cu.usbserial-1234" }
```
`state` is one of `IDLE`, `DRAG`, `AUTOCROSS`, `MAPPING`. `course` is the course
name in autocross/mapping (else `null`).

### `gps_point`
One raw GPS sample, emitted for every point in every active mode (~10 Hz). Use it
to draw the live position/track.
```json
{ "type": "gps_point", "point": {
    "timestamp": 1733700000.12, "speed_mph": 47.3,
    "latitude": 40.00123, "longitude": -83.00456,
    "gps_time": "18:20:00", "heading_deg": 12.0 } }
```
`heading_deg` may be `null` (e.g. when stopped, the module blanks the course).

### `live_status`
Mid-run snapshot for the live readout (drag & autocross, while no result has fired).
```json
{ "type": "live_status", "in_run": true, "partial": { /* RunResult or LapResult fields */ } }
```
`partial` is `null` in autocross before the start line is crossed. The shape of
`partial` matches `run_result.result` (drag) or `lap_result.result` (autocross).

### `run_result` (drag)
A completed drag run.
```json
{ "type": "run_result", "run_number": 1, "result": {
    "zero_to_sixty_s": 5.8, "quarter_mile_s": 13.9,
    "quarter_mile_trap_mph": 102.4, "peak_speed_mph": 104.0,
    "distance_ft": 1322.0 } }
```
Any field except `peak_speed_mph`/`distance_ft` can be `null` if not captured
(e.g. a run stopped before 60 mph).

### `lap_result` (autocross)
A completed lap. The large raw `track` array is **stripped** from this event (it's
saved to disk); fetch it from the session file if needed.
```json
{ "type": "lap_result", "run_number": 2, "result": {
    "course_name": "Test Course", "total_time_s": 41.27,
    "split_times_s": [12.4, 27.9], "peak_speed_mph": 58.1,
    "distance_ft": 2310.0, "start_timestamp": 1733700000.0 } }
```
`split_times_s` are **cumulative** seconds from the start line at each split gate.

### `run_saved`
Confirms a drag run or lap was written to disk.
```json
{ "type": "run_saved", "path": "/.../sessions/test-course_2026-06-09.json" }
```

### `mapping_status`
Emitted continuously while mapping; drives the mapping screen.
```json
{ "type": "mapping_status", "name": "My Course", "width_ft": 50,
  "captured": [ { "role": "start", "name": "start", "heading_deg": 90.0 } ],
  "has_heading_fix": true, "latest_heading": 91.0 }
```
Only enable the capture buttons when `has_heading_fix` is `true`.

### `gate_captured`
A gate was placed in response to `capture_gate`.
```json
{ "type": "gate_captured", "role": "start", "gate": {
    "name": "start", "lat1": 40.0, "lon1": -83.0,
    "lat2": 40.0, "lon2": -83.0001, "heading_deg": 90.0 } }
```

### `course_saved`
The mapped course was saved (after `finish_course`); the server returns to IDLE.
```json
{ "type": "course_saved", "path": "/.../courses/my-course.json", "course": {
    "name": "My Course", "start": { /* gate */ }, "finish": { /* gate */ },
    "splits": [ /* gates */ ], "width_ft": 50, "created": "2026-06-09" } }
```

### `courses` / `ports`
Replies to `list_courses` / `list_ports`.
```json
{ "type": "courses", "names": ["Test Course", "Autocross A"] }
{ "type": "ports", "ports": [ { "device": "/dev/cu.usbserial-1234", "description": "CP2104 USB to UART" } ] }
```

### `error`
A command was rejected or a GPS error occurred. Non-fatal — the socket stays open.
```json
{ "type": "error", "message": "cannot start drag while AUTOCROSS", "command": "start_drag" }
```

### `gps_stopped`
The GPS reader ended on its own (cable unplugged, fatal error). The server resets
to IDLE and follows this with a `state_changed`.
```json
{ "type": "gps_stopped", "reason": "GPS reader ended unexpectedly" }
```

---

## Typical UI flows

**Drag run**
1. `start_drag` → expect `state_changed` (DRAG).
2. Stream of `gps_point` + `live_status` (show speed, distance, live 0-60).
3. On run completion: `run_result` then `run_saved`. Timer re-arms automatically —
   more runs stream on the same connection.
4. `stop` → `state_changed` (IDLE). (A run in progress emits a partial `run_result`.)

**Autocross lap**
1. `start_autocross` with a `course` name → `state_changed` (AUTOCROSS).
2. `gps_point` + `live_status` (partial is `null` until the start line is crossed).
3. Each lap: `lap_result` + `run_saved`. Cross the start line again for the next lap.
4. `stop` → IDLE.

**Mapping a course** (the "press buttons to place gates" flow)
1. `start_mapping` with a `name` → `state_changed` (MAPPING).
2. Watch `mapping_status`; enable buttons once `has_heading_fix` is `true`.
3. Drive across the start line, press **Capture Start** → `capture_gate {role:"start"}`
   → `gate_captured`. Repeat with `role:"split"` for each split, then `role:"finish"`.
4. **Finish** → `finish_course` → `course_saved`, server returns to IDLE. Or
   **Cancel** → `cancel_mapping`.

---

## Notes for the Flutter side

- The server is **localhost-only** by default. To reach it from a phone/tablet,
  run the server with host `0.0.0.0` and connect to the machine's LAN IP. There is
  no auth yet — trusted networks only.
- All numeric units: **mph**, **feet**, **seconds**, **degrees**; `timestamp` is
  Unix epoch seconds (float).
- Treat any field documented as nullable (`heading_deg`, several result fields,
  `partial`, `course`) as optional in your Dart models.
- Reconnect logic: on reconnect, the first message is always `state_changed`, so the
  UI can rebuild its view from that without sending `get_state`.
