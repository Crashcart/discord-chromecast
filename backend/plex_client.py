"""Plex Media Server client.

Authenticates via X-Plex-Token (never exposed to the frontend).
Queries libraries, returns direct-play URLs only — no media bytes flow
through this service.
"""
from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import httpx
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_SEARCH_TTL = 3600  # 1 hour


@dataclass
class PlexMediaItem:
    key: str
    title: str
    direct_url: str
    content_type: str
    duration_ms: int = 0
    thumb_url: str = ""


class PlexClient:
    def __init__(self, base_url: str, token: str, redis_client: aioredis.Redis) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._redis = redis_client
        self._headers = {
            "X-Plex-Token": token,
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search_library(
        self, query: str, media_type: str = "track"
    ) -> list[PlexMediaItem]:
        """Search Plex for *query*.  Results cached in Redis for 1 h."""
        cache_key = f"plex:search:{media_type}:{query.lower()}"
        cached = await self._redis.get(cache_key)
        if cached:
            raw = json.loads(cached)
            return [PlexMediaItem(**item) for item in raw]

        plex_type = {"track": 10, "episode": 4, "movie": 1}.get(media_type, 10)
        url = f"{self._base}/search"
        params = {"query": query, "type": plex_type}

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, headers=self._headers, params=params)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("Plex search failed: %s", exc)
            return []

        items = self._parse_search_results(data, media_type)
        serialised = json.dumps([item.__dict__ for item in items])
        await self._redis.setex(cache_key, _SEARCH_TTL, serialised)
        return items

    async def get_direct_url(self, media_key: str) -> PlexMediaItem | None:
        """Resolve a Plex media key to a direct-play URL."""
        url = f"{self._base}{media_key}"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, headers=self._headers)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("Plex metadata fetch failed for key %s: %s", media_key, exc)
            return None

        return self._extract_item(data)

    async def list_libraries(self) -> list[dict[str, Any]]:
        """Return all Plex library sections."""
        url = f"{self._base}/library/sections"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, headers=self._headers)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("Plex library list failed: %s", exc)
            return []

        sections = (
            data.get("MediaContainer", {}).get("Directory", [])
        )
        return [{"key": s["key"], "title": s["title"], "type": s["type"]} for s in sections]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_search_results(
        self, data: dict[str, Any], media_type: str
    ) -> list[PlexMediaItem]:
        container = data.get("MediaContainer", {})
        results: list[dict[str, Any]] = (
            container.get("Metadata") or container.get("Track") or []
        )
        items: list[PlexMediaItem] = []
        for r in results[:20]:
            item = self._extract_item_from_metadata(r)
            if item:
                items.append(item)
        return items

    def _extract_item(self, data: dict[str, Any]) -> PlexMediaItem | None:
        container = data.get("MediaContainer", {})
        metadata = container.get("Metadata", [{}])
        if not metadata:
            return None
        return self._extract_item_from_metadata(metadata[0])

    def _extract_item_from_metadata(self, meta: dict[str, Any]) -> PlexMediaItem | None:
        key = meta.get("key", "")
        title = meta.get("title", "Unknown")
        thumb = meta.get("thumb", "")
        duration = meta.get("duration", 0)

        # Prefer direct-play part
        media_list = meta.get("Media", [])
        if not media_list:
            return None

        media = media_list[0]
        parts = media.get("Part", [])
        if not parts:
            return None

        part_key = parts[0].get("key", "")
        content_type = parts[0].get("container", "mp3")
        mime_map = {
            "mp3": "audio/mpeg",
            "mp4": "video/mp4",
            "m4a": "audio/mp4",
            "aac": "audio/aac",
            "flac": "audio/flac",
            "webm": "video/webm",
            "mkv": "video/webm",
        }
        content_type = mime_map.get(content_type.lower(), f"audio/{content_type}")

        direct_url = (
            f"{self._base}{part_key}?X-Plex-Token={self._token}"
        )
        thumb_url = f"{self._base}{thumb}?X-Plex-Token={self._token}" if thumb else ""

        return PlexMediaItem(
            key=key,
            title=title,
            direct_url=direct_url,
            content_type=content_type,
            duration_ms=duration,
            thumb_url=thumb_url,
        )
