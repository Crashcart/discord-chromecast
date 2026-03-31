"""AI provider settings — stored in Redis so they persist across restarts.

Supported providers:
  - disabled  — AI features off
  - ollama    — local Ollama instance
  - gemini    — Google Gemini API
"""
from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_KEY = "cast:ai_settings"


_DEFAULTS: dict[str, Any] = {
    "provider": "disabled",           # disabled | ollama | gemini
    "ollama_url": "http://localhost:11434",
    "ollama_model": "mistral",
    "gemini_api_key": "",
    "gemini_model": "gemini-1.5-flash",
    "system_prompt": (
        "You are an AI assistant for a tabletop RPG game master. "
        "Help suggest atmospheric music and narrate scenes concisely."
    ),
}


class AISettingsService:
    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client

    async def get(self) -> dict[str, Any]:
        raw = await self._redis.get(_KEY)
        if not raw:
            return dict(_DEFAULTS)
        stored = json.loads(raw)
        # Merge with defaults so new keys always appear
        return {**_DEFAULTS, **stored}

    async def save(self, updates: dict[str, Any]) -> dict[str, Any]:
        current = await self.get()
        current.update({k: v for k, v in updates.items() if k in _DEFAULTS})
        await self._redis.set(_KEY, json.dumps(current))
        logger.info("AI settings saved (provider=%s)", current.get("provider"))
        return current

    async def get_provider(self) -> str:
        s = await self.get()
        return s.get("provider", "disabled")
