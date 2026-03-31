/**
 * player.js — Local HTML5 player + WebSocket event handler.
 *
 * Connects to the backend /ws/sync endpoint and reacts to MediaEvent
 * messages.  If a Cast session is active, routes commands there instead.
 */

const BACKEND_WS = (location.protocol === "https:" ? "wss" : "ws") +
  "://" + (window.BACKEND_HOST || "localhost:8000") + "/ws/sync";

const audioEl = document.getElementById("audio-player");
const videoEl = document.getElementById("video-player");
const titleEl = document.getElementById("track-title");
const thumbEl = document.getElementById("track-thumb");

let ws = null;
let reconnectDelay = 1000;

// ---------------------------------------------------------------------------
// WebSocket
// ---------------------------------------------------------------------------

function connectWs() {
  ws = new WebSocket(BACKEND_WS);

  ws.onopen = () => {
    console.log("[ws] connected");
    reconnectDelay = 1000;
    document.getElementById("ws-status").textContent = "Live";
    document.getElementById("ws-status").className = "status-ok";
  };

  ws.onclose = () => {
    console.log("[ws] disconnected — retrying in", reconnectDelay, "ms");
    document.getElementById("ws-status").textContent = "Disconnected";
    document.getElementById("ws-status").className = "status-err";
    setTimeout(connectWs, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, 30000);
  };

  ws.onmessage = (ev) => {
    try {
      const event = JSON.parse(ev.data);
      handleMediaEvent(event);
    } catch (e) {
      console.warn("[ws] bad message", ev.data);
    }
  };
}

// ---------------------------------------------------------------------------
// Event handling
// ---------------------------------------------------------------------------

function handleMediaEvent(event) {
  switch (event.type) {
    case "url":
      loadMedia(event.url, event.content_type, event.title, event.thumb_url);
      break;
    case "play":
      resumeMedia();
      break;
    case "pause":
      pauseMedia();
      break;
    case "stop":
      stopMedia();
      break;
    case "seek":
      seekMedia(event.position || 0);
      break;
    default:
      console.debug("[player] unknown event type:", event.type);
  }
}

function loadMedia(url, contentType, title, thumbUrl) {
  if (titleEl) titleEl.textContent = title || "";
  if (thumbEl && thumbUrl) { thumbEl.src = thumbUrl; thumbEl.style.display = "block"; }

  // Try Cast first
  if (typeof castLoadMedia === "function" && castLoadMedia(url, contentType, title, thumbUrl)) {
    hideLocalPlayer();
    return;
  }

  // Fall back to HTML5
  const isVideo = contentType && contentType.startsWith("video/");
  if (isVideo) {
    videoEl.src = url;
    videoEl.style.display = "block";
    audioEl.style.display = "none";
    videoEl.play();
  } else {
    audioEl.src = url;
    audioEl.style.display = "block";
    videoEl.style.display = "none";
    audioEl.play();
  }
}

function resumeMedia() {
  if (typeof castPlay === "function" && castSession) { castPlay(); return; }
  activePlayer()?.play();
}

function pauseMedia() {
  if (typeof castPause === "function" && castSession) { castPause(); return; }
  activePlayer()?.pause();
}

function stopMedia() {
  if (typeof castStop === "function" && castSession) { castStop(); return; }
  const p = activePlayer();
  if (p) { p.pause(); p.currentTime = 0; }
}

function seekMedia(position) {
  if (typeof castSeek === "function" && castSession) { castSeek(position); return; }
  const p = activePlayer();
  if (p) p.currentTime = position;
}

function activePlayer() {
  if (audioEl.src) return audioEl;
  if (videoEl.src) return videoEl;
  return null;
}

function hideLocalPlayer() {
  audioEl.style.display = "none";
  videoEl.style.display = "none";
}

// ---------------------------------------------------------------------------
// UI controls
// ---------------------------------------------------------------------------

document.getElementById("btn-play")?.addEventListener("click", resumeMedia);
document.getElementById("btn-pause")?.addEventListener("click", pauseMedia);
document.getElementById("btn-stop")?.addEventListener("click", stopMedia);

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

connectWs();
