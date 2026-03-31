/**
 * cast.js — Google Cast Sender SDK integration.
 *
 * Handles:
 *  - Cast API initialisation
 *  - Device session management
 *  - Media loading from a Plex direct-play URL
 *  - Play / pause / stop / seek forwarding to the active session
 */

const CAST_APP_ID = chrome.cast.media.DEFAULT_MEDIA_RECEIVER_APP_ID;

let castSession = null;
let castAvailable = false;

// ---------------------------------------------------------------------------
// Initialisation
// ---------------------------------------------------------------------------

window.__onGCastApiAvailable = function (isAvailable) {
  castAvailable = isAvailable;
  if (!isAvailable) return;

  cast.framework.CastContext.getInstance().setOptions({
    receiverApplicationId: CAST_APP_ID,
    autoJoinPolicy: chrome.cast.AutoJoinPolicy.ORIGIN_SCOPED,
  });

  const castBtn = document.getElementById("cast-btn");
  if (castBtn) castBtn.style.display = "inline-block";

  cast.framework.CastContext.getInstance().addEventListener(
    cast.framework.CastContextEventType.SESSION_STATE_CHANGED,
    onSessionStateChanged
  );
};

function onSessionStateChanged(event) {
  const state = event.sessionState;
  const statusEl = document.getElementById("cast-status");

  if (
    state === cast.framework.SessionState.SESSION_STARTED ||
    state === cast.framework.SessionState.SESSION_RESUMED
  ) {
    castSession = cast.framework.CastContext.getInstance().getCurrentSession();
    if (statusEl) statusEl.textContent = `Cast: ${castSession.getCastDevice().friendlyName}`;
  } else if (state === cast.framework.SessionState.SESSION_ENDED) {
    castSession = null;
    if (statusEl) statusEl.textContent = "Cast: not connected";
  }
}

// ---------------------------------------------------------------------------
// Public helpers (called from player.js)
// ---------------------------------------------------------------------------

/**
 * Load a media URL on the active Cast session.
 * Falls back silently if no session is active.
 */
function castLoadMedia(url, contentType, title, thumbUrl) {
  if (!castSession) return false;

  const mediaInfo = new chrome.cast.media.MediaInfo(url, contentType);
  mediaInfo.metadata = new chrome.cast.media.GenericMediaMetadata();
  mediaInfo.metadata.title = title || "RPG Audio";
  if (thumbUrl) mediaInfo.metadata.images = [{ url: thumbUrl }];

  const request = new chrome.cast.media.LoadRequest(mediaInfo);
  castSession.loadMedia(request).then(
    () => console.log("[cast] media loaded"),
    (err) => console.warn("[cast] load error", err)
  );
  return true;
}

function castPlay() {
  castSession?.getMediaSession()?.play(null, () => {}, () => {});
}

function castPause() {
  castSession?.getMediaSession()?.pause(null, () => {}, () => {});
}

function castStop() {
  castSession?.getMediaSession()?.stop(null, () => {}, () => {});
}

function castSeek(position) {
  const req = new chrome.cast.media.SeekRequest();
  req.currentTime = position;
  castSession?.getMediaSession()?.seek(req, () => {}, () => {});
}

// ---------------------------------------------------------------------------
// UI button
// ---------------------------------------------------------------------------

document.getElementById("cast-btn")?.addEventListener("click", () => {
  cast.framework.CastContext.getInstance().requestSession();
});
