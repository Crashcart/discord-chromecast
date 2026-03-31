"""discord-chromecast backend.

FastAPI service that:
  - Authenticates with Plex (token never reaches the frontend)
  - Queries Plex libraries and extracts direct-play URLs
  - Pushes MediaEvent payloads to all connected clients via WebSocket
  - Orchestrates Chromecast sessions via pychromecast
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from cast_manager import ChromecastManager
from config import settings
from plex_client import PlexClient
from sync_manager import MediaEvent, SyncManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# App state holder
# ---------------------------------------------------------------------------

class AppState:
    redis: aioredis.Redis
    plex: PlexClient
    cast: ChromecastManager
    sync: SyncManager


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.redis = aioredis.from_url(settings.redis_url, decode_responses=False)
    state.plex = PlexClient(settings.plex_url, settings.plex_token, state.redis)
    state.cast = ChromecastManager(state.redis)
    state.sync = SyncManager(state.redis)
    logger.info("discord-chromecast backend ready")
    yield
    await state.redis.aclose()


app = FastAPI(title="discord-chromecast", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class PlayRequest(BaseModel):
    query: str
    media_type: str = "track"   # track | episode | movie
    device_name: str = ""       # if set, also cast to this device


class CastRequest(BaseModel):
    device_name: str
    url: str
    content_type: str = "audio/mpeg"
    title: str = ""


class ControlRequest(BaseModel):
    action: str         # play | pause | stop | seek
    device_name: str = ""
    position: float = 0.0


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/devices")
async def list_devices() -> dict[str, Any]:
    devices = await state.cast.list_devices()
    return {"devices": [d.__dict__ for d in devices]}


@app.get("/api/libraries")
async def list_libraries() -> dict[str, Any]:
    libs = await state.plex.list_libraries()
    return {"libraries": libs}


@app.post("/api/play")
async def play(req: PlayRequest) -> dict[str, Any]:
    """Query Plex, resolve a direct URL, optionally cast it, and broadcast."""
    results = await state.plex.search_library(req.query, req.media_type)
    if not results:
        raise HTTPException(status_code=404, detail=f"No results for '{req.query}'")

    item = results[0]

    event = MediaEvent(
        type="url",
        url=item.direct_url,
        title=item.title,
        content_type=item.content_type,
        thumb_url=item.thumb_url,
    )
    await state.sync.broadcast(event)

    # Optionally cast to a named device
    cast_ok = False
    if req.device_name:
        cast_ok = await state.cast.cast_media(
            req.device_name, item.direct_url, item.content_type, item.title
        )

    return {
        "title": item.title,
        "url": item.direct_url,
        "content_type": item.content_type,
        "thumb_url": item.thumb_url,
        "cast": cast_ok,
    }


@app.post("/api/cast")
async def cast_url(req: CastRequest) -> dict[str, Any]:
    """Cast an arbitrary URL to a named Chromecast device."""
    ok = await state.cast.cast_media(
        req.device_name, req.url, req.content_type, req.title
    )
    if not ok:
        raise HTTPException(status_code=502, detail="Cast failed — device not found or unreachable")
    return {"cast": True}


@app.post("/api/control")
async def control(req: ControlRequest) -> dict[str, Any]:
    """Send play/pause/stop/seek to all WS clients and optionally to a cast device."""
    allowed = {"play", "pause", "stop", "seek"}
    if req.action not in allowed:
        raise HTTPException(status_code=400, detail=f"action must be one of {allowed}")

    event = MediaEvent(type=req.action, position=req.position)
    await state.sync.broadcast(event)

    cast_ok = False
    if req.device_name:
        cast_ok = await state.cast.send_command(req.device_name, req.action, req.position)

    return {"action": req.action, "cast": cast_ok}


@app.get("/api/status")
async def status() -> dict[str, Any]:
    """Return current playback state from Redis."""
    s = await state.sync.get_state()
    return s or {"type": "status", "url": "", "title": "", "position": 0.0}


@app.get("/api/search")
async def search(q: str, media_type: str = "track") -> dict[str, Any]:
    """Search Plex library. Returns top-20 matches."""
    results = await state.plex.search_library(q, media_type)
    return {"results": [r.__dict__ for r in results]}


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/ws/sync")
async def ws_sync(ws: WebSocket) -> None:
    await state.sync.connect(ws)
    try:
        while True:
            # Keep the connection alive; clients may send pings
            await ws.receive_text()
    except WebSocketDisconnect:
        state.sync.disconnect(ws)
