"""discord-chromecast Discord bot.

Slash commands that talk to the backend API to control Plex/Chromecast
playback from within a Discord server.
"""
from __future__ import annotations

import os
import logging

import discord
import httpx
from discord import app_commands

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
DISCORD_APP_ID = int(os.getenv("DISCORD_APP_ID", "0"))


# ---------------------------------------------------------------------------
# Bot setup
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


def _http() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=BACKEND_URL, timeout=20)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _media_embed(title: str, url: str, thumb_url: str = "", cast: bool = False) -> discord.Embed:
    embed = discord.Embed(title=f"▶ {title}", color=0xe94560)
    embed.set_footer(text="📺 Casting" if cast else "🔊 Streaming")
    if thumb_url:
        embed.set_thumbnail(url=thumb_url)
    return embed


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

@tree.command(name="play", description="Search Plex and stream a track")
@app_commands.describe(query="Track name, artist, or album", media_type="Type of media")
@app_commands.choices(media_type=[
    app_commands.Choice(name="Track", value="track"),
    app_commands.Choice(name="Episode", value="episode"),
    app_commands.Choice(name="Movie", value="movie"),
])
async def cmd_play(
    interaction: discord.Interaction,
    query: str,
    media_type: app_commands.Choice[str] | None = None,
) -> None:
    await interaction.response.defer()
    mtype = media_type.value if media_type else "track"
    async with _http() as http:
        resp = await http.post("/api/play", json={"query": query, "media_type": mtype})

    if resp.status_code == 404:
        await interaction.followup.send(f"No results found for **{query}**.")
        return
    resp.raise_for_status()
    data = resp.json()
    embed = _media_embed(data["title"], data["url"], data.get("thumb_url", ""))
    await interaction.followup.send(embed=embed)


@tree.command(name="cast", description="Search Plex and cast to a Chromecast device")
@app_commands.describe(query="Track/movie name", device="Chromecast device friendly name")
async def cmd_cast(
    interaction: discord.Interaction,
    query: str,
    device: str,
) -> None:
    await interaction.response.defer()
    async with _http() as http:
        resp = await http.post("/api/play", json={
            "query": query,
            "media_type": "track",
            "device_name": device,
        })

    if resp.status_code == 404:
        await interaction.followup.send(f"No results found for **{query}**.")
        return
    resp.raise_for_status()
    data = resp.json()
    embed = _media_embed(data["title"], data["url"], data.get("thumb_url", ""), cast=data.get("cast", False))
    await interaction.followup.send(embed=embed)


@tree.command(name="pause", description="Pause playback")
async def cmd_pause(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    async with _http() as http:
        await http.post("/api/control", json={"action": "pause"})
    await interaction.followup.send("⏸ Paused.")


@tree.command(name="resume", description="Resume playback")
async def cmd_resume(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    async with _http() as http:
        await http.post("/api/control", json={"action": "play"})
    await interaction.followup.send("▶ Resumed.")


@tree.command(name="stop", description="Stop playback")
async def cmd_stop(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    async with _http() as http:
        await http.post("/api/control", json={"action": "stop"})
    await interaction.followup.send("⏹ Stopped.")


@tree.command(name="devices", description="List available Chromecast devices")
async def cmd_devices(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    async with _http() as http:
        resp = await http.get("/api/devices")
    resp.raise_for_status()
    devices = resp.json().get("devices", [])

    if not devices:
        await interaction.followup.send("No Chromecast devices found on the network.")
        return

    embed = discord.Embed(title="📺 Chromecast Devices", color=0xe94560)
    for dev in devices:
        embed.add_field(
            name=dev["name"],
            value=f"`{dev['host']}:{dev['port']}`  —  {dev.get('model_name', 'Chromecast')}",
            inline=False,
        )
    await interaction.followup.send(embed=embed)


@tree.command(name="status", description="Show current playback status")
async def cmd_status(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    async with _http() as http:
        resp = await http.get("/api/status")
    resp.raise_for_status()
    data = resp.json()

    if not data.get("url"):
        await interaction.followup.send("Nothing is currently playing.")
        return

    embed = _media_embed(data.get("title", "Unknown"), data["url"], data.get("thumb_url", ""))
    embed.add_field(name="State", value=data.get("type", "—"))
    await interaction.followup.send(embed=embed)


@tree.command(name="search", description="Search Plex library without playing")
@app_commands.describe(query="Search terms", media_type="Type of media")
@app_commands.choices(media_type=[
    app_commands.Choice(name="Track", value="track"),
    app_commands.Choice(name="Episode", value="episode"),
    app_commands.Choice(name="Movie", value="movie"),
])
async def cmd_search(
    interaction: discord.Interaction,
    query: str,
    media_type: app_commands.Choice[str] | None = None,
) -> None:
    await interaction.response.defer()
    mtype = media_type.value if media_type else "track"
    async with _http() as http:
        resp = await http.get("/api/search", params={"q": query, "media_type": mtype})
    resp.raise_for_status()
    results = resp.json().get("results", [])

    if not results:
        await interaction.followup.send(f"No results for **{query}**.")
        return

    embed = discord.Embed(title=f"Search: {query}", color=0x0f3460)
    for item in results[:10]:
        embed.add_field(name=item["title"], value=item.get("content_type", ""), inline=False)
    await interaction.followup.send(embed=embed)


# ---------------------------------------------------------------------------
# Ready
# ---------------------------------------------------------------------------

@client.event
async def on_ready() -> None:
    await tree.sync()
    logger.info("discord-chromecast bot ready as %s", client.user)


client.run(DISCORD_TOKEN)
