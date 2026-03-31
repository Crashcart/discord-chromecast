"""Chromecast device manager.

Uses pychromecast for mDNS discovery and media loading.
Device list is cached in Redis (TTL 30 s) to avoid blocking the event loop
on every /api/devices call.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass
from typing import Any

import pychromecast
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_DEVICE_CACHE_TTL = 30  # seconds


@dataclass
class CastDevice:
    name: str
    host: str
    port: int
    uuid: str
    model_name: str = ""


class ChromecastManager:
    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def list_devices(self) -> list[CastDevice]:
        """Return discovered Chromecast devices.  Cached for 30 s."""
        cached = await self._redis.get("cast:devices")
        if cached:
            raw: list[dict[str, Any]] = json.loads(cached)
            return [CastDevice(**d) for d in raw]

        devices = await asyncio.to_thread(self._discover)
        serialised = json.dumps([asdict(d) for d in devices])
        await self._redis.setex("cast:devices", _DEVICE_CACHE_TTL, serialised)
        return devices

    async def cast_media(
        self,
        device_name: str,
        media_url: str,
        content_type: str,
        title: str = "",
    ) -> bool:
        """Load *media_url* on the named Chromecast.  Returns True on success."""
        try:
            return await asyncio.to_thread(
                self._load_on_device, device_name, media_url, content_type, title
            )
        except Exception as exc:
            logger.warning("Cast to '%s' failed: %s", device_name, exc)
            return False

    async def send_command(self, device_name: str, command: str, position: float = 0.0) -> bool:
        """Send play/pause/stop/seek to a named device."""
        try:
            return await asyncio.to_thread(
                self._send_command_sync, device_name, command, position
            )
        except Exception as exc:
            logger.warning("Cast command '%s' to '%s' failed: %s", command, device_name, exc)
            return False

    # ------------------------------------------------------------------
    # Sync helpers (run in thread pool via asyncio.to_thread)
    # ------------------------------------------------------------------

    def _discover(self) -> list[CastDevice]:
        chromecasts, browser = pychromecast.get_chromecasts(timeout=5)
        devices: list[CastDevice] = []
        for cc in chromecasts:
            info = cc.cast_info
            devices.append(
                CastDevice(
                    name=info.friendly_name,
                    host=info.host,
                    port=info.port,
                    uuid=str(info.uuid),
                    model_name=info.model_name,
                )
            )
        browser.stop_discovery()
        return devices

    def _get_device(self, device_name: str) -> pychromecast.Chromecast | None:
        chromecasts, browser = pychromecast.get_chromecasts(timeout=5)
        match = next(
            (cc for cc in chromecasts if cc.cast_info.friendly_name == device_name),
            None,
        )
        browser.stop_discovery()
        return match

    def _load_on_device(
        self,
        device_name: str,
        media_url: str,
        content_type: str,
        title: str,
    ) -> bool:
        cc = self._get_device(device_name)
        if not cc:
            logger.warning("Chromecast '%s' not found", device_name)
            return False

        cc.wait()
        mc = cc.media_controller
        mc.play_media(media_url, content_type, title=title)
        mc.block_until_active(timeout=10)
        return True

    def _send_command_sync(
        self, device_name: str, command: str, position: float
    ) -> bool:
        cc = self._get_device(device_name)
        if not cc:
            return False

        cc.wait()
        mc = cc.media_controller

        if command == "play":
            mc.play()
        elif command == "pause":
            mc.pause()
        elif command == "stop":
            mc.stop()
        elif command == "seek":
            mc.seek(position)
        else:
            logger.warning("Unknown cast command: %s", command)
            return False

        return True
