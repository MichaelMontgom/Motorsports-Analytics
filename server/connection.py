"""Tracks connected WebSocket clients and broadcasts JSON events to all of them."""

from typing import Set

from fastapi import WebSocket


class ConnectionManager:
    """A set of live WebSocket connections with a fire-and-forget broadcast."""

    def __init__(self):
        self._sockets: Set[WebSocket] = set()

    def add(self, ws: WebSocket) -> None:
        self._sockets.add(ws)

    def remove(self, ws: WebSocket) -> None:
        self._sockets.discard(ws)

    @property
    def count(self) -> int:
        return len(self._sockets)

    async def send(self, ws: WebSocket, event: dict) -> None:
        await ws.send_json(event)

    async def broadcast(self, event: dict) -> None:
        """Send an event to every connected client, dropping any that fail."""
        dead = []
        for ws in list(self._sockets):
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._sockets.discard(ws)
