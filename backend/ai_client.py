"""Unified AI client — Ollama or Gemini, switchable at runtime.

Two capabilities exposed:
  suggest(scene_description) → list of Plex search terms
  narrate(title, scene_context) → short atmospheric paragraph

The active provider is read from AISettingsService on every call so
settings changes take effect immediately without a restart.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ai_settings_service import AISettingsService

logger = logging.getLogger(__name__)

_SUGGEST_TMPL = """\
A tabletop RPG scene is described below. Suggest 3 concise Plex search \
terms (track titles, album names, or artists) that would make great \
background music for this scene. Return ONLY a JSON array of strings.

Scene: {scene}"""

_NARRATE_TMPL = """\
A track called "{title}" just started playing during this RPG scene: {scene}

Write 1–2 atmospheric sentences a game master could read aloud to set the mood. \
Be evocative but brief. No meta-commentary."""


class AIUnavailableError(Exception):
    """Raised when no AI provider is configured or reachable."""


class AIClient:
    def __init__(self, settings_svc: AISettingsService) -> None:
        self._svc = settings_svc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def suggest(self, scene_description: str) -> list[str]:
        """Return up to 3 Plex search term suggestions for the scene."""
        cfg = await self._svc.get()
        prompt = _SUGGEST_TMPL.format(scene=scene_description)
        raw = await self._complete(cfg, prompt)
        return self._parse_json_list(raw)

    async def narrate(self, title: str, scene_context: str = "") -> str:
        """Return a short atmospheric narration for the now-playing track."""
        cfg = await self._svc.get()
        prompt = _NARRATE_TMPL.format(title=title, scene=scene_context or "a fantasy adventure")
        return (await self._complete(cfg, prompt)).strip()

    async def health_check(self) -> dict[str, Any]:
        """Return connection status for the current provider."""
        cfg = await self._svc.get()
        provider = cfg.get("provider", "disabled")
        if provider == "disabled":
            return {"provider": "disabled", "ok": True}
        try:
            await self._complete(cfg, "Reply with the single word: ok")
            return {"provider": provider, "ok": True}
        except Exception as exc:
            return {"provider": provider, "ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Provider dispatch
    # ------------------------------------------------------------------

    async def _complete(self, cfg: dict[str, Any], prompt: str) -> str:
        provider = cfg.get("provider", "disabled")
        system = cfg.get("system_prompt", "")

        if provider == "ollama":
            return await self._ollama(cfg, system, prompt)
        if provider == "gemini":
            return await self._gemini(cfg, system, prompt)
        raise AIUnavailableError("No AI provider configured — visit /settings to set one up.")

    # ------------------------------------------------------------------
    # Ollama
    # ------------------------------------------------------------------

    async def _ollama(self, cfg: dict[str, Any], system: str, prompt: str) -> str:
        url = cfg.get("ollama_url", "http://localhost:11434").rstrip("/")
        model = cfg.get("ollama_model", "mistral")
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(f"{url}/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.RequestError as exc:
            raise AIUnavailableError(f"Ollama unreachable at {url}: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise AIUnavailableError(f"Ollama error {exc.response.status_code}: {exc.response.text[:200]}") from exc

        return data.get("message", {}).get("content", "")

    # ------------------------------------------------------------------
    # Gemini
    # ------------------------------------------------------------------

    async def _gemini(self, cfg: dict[str, Any], system: str, prompt: str) -> str:
        api_key = cfg.get("gemini_api_key", "")
        model = cfg.get("gemini_model", "gemini-1.5-flash")
        if not api_key:
            raise AIUnavailableError("Gemini API key not set — visit /settings.")

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": prompt}]}],
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.RequestError as exc:
            raise AIUnavailableError(f"Gemini unreachable: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise AIUnavailableError(f"Gemini error {exc.response.status_code}: {exc.response.text[:300]}") from exc

        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise AIUnavailableError(f"Unexpected Gemini response shape: {data}") from exc

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json_list(raw: str) -> list[str]:
        """Extract a JSON array from the model response."""
        raw = raw.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            result = json.loads(raw)
            if isinstance(result, list):
                return [str(s) for s in result[:5]]
        except json.JSONDecodeError:
            pass
        # Fallback: treat each line as a term
        return [line.strip(" -•\"'") for line in raw.splitlines() if line.strip()][:5]
