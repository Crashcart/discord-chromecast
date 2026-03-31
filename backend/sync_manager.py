"""WebSocket sync manager.

Maintains the set of connected WebSocket clients and broadcasts
MediaEvent JSON to all of them.  Also persists current playback state
in Redis so late-joining clients can sync immediately.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass

import redis.asyncio as aioredis
from fastapi import WebSocket

logger = logging.getLogger(__name__)

_STATE_KEY = "cast:playback_state"
_STATE_TTL = 86400  # 24 h


@dataclass
class MediaEvent:
    type: str           # play | pause | stop | seek | url | status
    url: str = ""
    title: str = ""
    content_type: str = "audio/mpeg"
    position: float = 0.0
    thumb_url: str = ""


class SyncManager:
    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._clients: set[WebSocket] = set()
        self._redis = redis_client

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)

        # Send current state to the newly connected client
        state = await self._redis.get(_STATE_KEY)
        if state:
            try:
                await ws.send_text(state.decode())
            except Exception:
                pass

        logger.debug("WS client connected (%d total)", len(self._clients))

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)
        logger.debug("WS client disconnected (%d remaining)", len(self._clients))

    # ------------------------------------------------------------------
    # Broadcast
    # ------------------------------------------------------------------

    async def broadcast(self, event: MediaEvent) -> None:
        payload = json.dumps(asdict(event))

        # Persist state in Redis
        await self._redis.setex(_STATE_KEY, _STATE_TTL, payload)

        dead: list[WebSocket] = []
        for ws in list(self._clients):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self._clients.discard(ws)

    async def get_state(self) -> dict | None:
        raw = await self._redis.get(_STATE_KEY)
        if raw:
            return json.loads(raw)
        return None
