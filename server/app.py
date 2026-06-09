"""FastAPI WebSocket server for the GPS performance timer.

Run:  python -m server.app           (binds to 127.0.0.1:8000)
The Flutter UI connects to ws://127.0.0.1:8000/ws and drives everything with the
JSON command protocol defined in server/protocol.py.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from server import protocol
from server.connection import ConnectionManager
from server.controller import SessionController, available_ports


manager = ConnectionManager()
controller = SessionController(manager)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await controller.shutdown()


app = FastAPI(title="Motorsports-Analytics GPS Timer", lifespan=lifespan)


@app.get("/ports")
async def get_ports() -> dict:
    """List available serial ports (handy for a setup screen before the socket opens)."""
    return {"ports": available_ports()}


async def dispatch(ws: WebSocket, msg: dict) -> None:
    """Route one client command to the controller, isolating any failure."""
    if not isinstance(msg, dict):
        await manager.send(ws, protocol.error("message must be a JSON object"))
        return

    command = msg.get("type")
    try:
        if command == "start_drag":
            await controller.start_drag(hz=msg.get("hz", 10), port=msg.get("port"))
        elif command == "start_autocross":
            await controller.start_autocross(course=msg.get("course"),
                                             hz=msg.get("hz", 10), port=msg.get("port"))
        elif command == "start_mapping":
            await controller.start_mapping(name=msg.get("name"),
                                           width_ft=msg.get("width_ft", 50.0),
                                           hz=msg.get("hz", 10), port=msg.get("port"))
        elif command == "capture_gate":
            await controller.capture_gate(role=msg.get("role"), name=msg.get("name"))
        elif command == "finish_course":
            await controller.finish_course()
        elif command == "cancel_mapping":
            await controller.cancel_mapping()
        elif command == "stop":
            await controller.stop()
        elif command == "list_courses":
            await controller.list_courses()
        elif command == "list_ports":
            await controller.list_ports()
        elif command == "get_state":
            await controller.send_state(ws)
        else:
            await manager.send(ws, protocol.error(f"unknown command '{command}'", command))
    except Exception as exc:  # never let one bad command kill the socket
        await manager.send(ws, protocol.error(f"command failed: {exc}", command))


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    manager.add(ws)
    try:
        await manager.send(ws, controller.state_event())
        while True:
            msg = await ws.receive_json()
            await dispatch(ws, msg)
    except WebSocketDisconnect:
        manager.remove(ws)
    except Exception:
        manager.remove(ws)


def main() -> None:
    import uvicorn
    uvicorn.run("server.app:app", host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()
