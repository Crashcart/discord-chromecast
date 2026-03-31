"""Plex TV authentication.

Exchanges a Plex username + password for an auth token by calling the
official Plex TV sign-in API.  The token is stored in Redis so it
persists across restarts and is reused for all PlexClient calls.

The Plex token NEVER leaves the backend — only a session cookie is
returned to the browser.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import uuid

import httpx
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# Plex TV sign-in endpoint
_PLEX_SIGNIN_URL = "https://plex.tv/api/v2/users/signin"

# Unique identifier for this app (stable per install)
_CLIENT_ID = "discord-chromecast-rpg-bot"

_PLEX_HEADERS = {
    "X-Plex-Client-Identifier": _CLIENT_ID,
    "X-Plex-Product": "discord-chromecast",
    "X-Plex-Version": "1.0.0",
    "Accept": "application/json",
}

# Redis keys
_TOKEN_KEY = "cast:plex_token"
_SESSION_PREFIX = "cast:session:"
_SESSION_TTL = 86400 * 7  # 7 days


class PlexAuthError(Exception):
    """Raised when Plex credentials are invalid."""


class PlexAuthService:
    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client

    # ------------------------------------------------------------------
    # Login / logout
    # ------------------------------------------------------------------

    async def login(self, username: str, password: str) -> str:
        """Authenticate with Plex TV.  Returns a session token (not the Plex token)."""
        plex_token = await self._fetch_plex_token(username, password)

        # Store Plex token in Redis (only the backend reads this)
        await self._redis.set(_TOKEN_KEY, plex_token)

        # Create an opaque session token for the browser
        session_token = secrets.token_urlsafe(32)
        await self._redis.setex(
            f"{_SESSION_PREFIX}{session_token}",
            _SESSION_TTL,
            "1",
        )
        logger.info("Plex login successful for %s", username)
        return session_token

    async def logout(self, session_token: str) -> None:
        await self._redis.delete(f"{_SESSION_PREFIX}{session_token}")

    async def is_authenticated(self, session_token: str) -> bool:
        if not session_token:
            return False
        val = await self._redis.get(f"{_SESSION_PREFIX}{session_token}")
        return val is not None

    # ------------------------------------------------------------------
    # Token retrieval (used by PlexClient)
    # ------------------------------------------------------------------

    async def get_plex_token(self) -> str:
        """Return the stored Plex token (from Redis or empty string)."""
        raw = await self._redis.get(_TOKEN_KEY)
        if raw:
            return raw.decode() if isinstance(raw, bytes) else raw
        return ""

    async def has_plex_token(self) -> bool:
        return bool(await self._redis.exists(_TOKEN_KEY))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _fetch_plex_token(self, username: str, password: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    _PLEX_SIGNIN_URL,
                    headers=_PLEX_HEADERS,
                    data={"login": username, "password": password, "rememberMe": True},
                )
        except httpx.RequestError as exc:
            raise PlexAuthError(f"Network error contacting Plex TV: {exc}") from exc

        if resp.status_code == 401:
            raise PlexAuthError("Invalid Plex username or password.")
        if not resp.is_success:
            raise PlexAuthError(f"Plex TV returned {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        token = data.get("authToken") or data.get("auth_token", "")
        if not token:
            raise PlexAuthError("Plex TV response did not include an auth token.")
        return token
