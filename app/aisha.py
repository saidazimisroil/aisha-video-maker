"""aisha.py - Thin client for the Aisha account-wide APIs we proxy for the dashboard.

The browser must never see the server's ``X-Api-Key``, so every outbound call is made here
(or in ``pipeline.py``) and the frontend talks only to our own API. Two surfaces:

* **Audio library** — ``GET /api/v1/tts/get/`` lists the account's whole TTS history. Its
  exact JSON schema is undocumented, so :func:`normalize_record` maps the field names we
  expect while preserving everything else, and the response wrapper handles both DRF-style
  ``{count, results}`` and a bare list.
* **Audio bytes** — downloading a clip needs the key, so :func:`fetch_audio_bytes` streams it
  server-side for the preview player. :func:`resolve_audio_url` is an SSRF guard: only Aisha
  hosts (or relative ``/media/...`` paths) are ever fetched.

:func:`get_balance` is best-effort — the balance endpoint is unknown, so it probes a few
candidates (or an operator-supplied ``AISHA_BALANCE_PATH``) and quietly returns ``None`` if
nothing answers, letting the UI hide the widget.
"""

import logging
from urllib.parse import urlparse

import requests

from app.config import settings
from app.pipeline import BASE, media_url

log = logging.getLogger("aisha.client")

TTS_LIST_URL = BASE + "/api/v1/tts/get/"
_ALLOWED_HOST_SUFFIX = "aisha.group"

# Endpoints we *guess* might expose the account balance. Tried in order; an operator who
# knows the real path can set AISHA_BALANCE_PATH and it is tried first (and trusted).
_BALANCE_CANDIDATES = (
    "/api/v1/account/", "/api/v1/balance/", "/api/v1/account/balance/",
    "/api/v1/user/", "/api/v1/users/me/", "/api/v1/me/",
)
_BALANCE_KEYS = ("balance", "amount", "credit", "credits", "sum", "available_balance")


def _headers() -> dict:
    return {"X-Api-Key": settings.aisha_api_key}


# --------------------------------------------------------------------------- #
# Audio library
# --------------------------------------------------------------------------- #
def normalize_record(r) -> dict:
    """Map an upstream TTS record to a stable shape, preserving all original keys."""
    if not isinstance(r, dict):
        return {"raw": r}
    audio = (r.get("audio_path") or r.get("audio") or r.get("audio_url")
             or r.get("file") or r.get("url"))
    out = dict(r)  # keep everything upstream sent (AudioRecord allows extras)
    out["id"] = str(r.get("id")) if r.get("id") is not None else None
    out["audio_url"] = media_url(audio) if audio else None
    out["transcript"] = r.get("transcript") or r.get("text")
    out["language"] = r.get("language") or r.get("lang")
    out["status"] = r.get("status")
    out["created_at"] = r.get("created_at") or r.get("created") or r.get("date")
    return out


def list_tts(page: int = 1, limit: int = 12, search: str = None,
             language: str = None) -> dict:
    """Fetch a page of the account's TTS history and normalize it.

    Raises ``requests.RequestException`` on a transport/HTTP error so the route can map it
    to a friendly 502.
    """
    params = {"page": page, "limit": limit}
    # Pass filters through best-effort; the upstream may ignore unknown params.
    if search:
        params["search"] = search
    if language:
        params["language"] = language
    resp = requests.get(TTS_LIST_URL, headers=_headers(), params=params, timeout=30)
    resp.raise_for_status()
    body = resp.json()

    if isinstance(body, list):
        items, count = body, None
    elif isinstance(body, dict):
        items = (body.get("results") or body.get("data") or body.get("items") or [])
        count = body.get("count", body.get("total"))
    else:
        items, count = [], None

    return {
        "count": count,
        "page": page,
        "limit": limit,
        "results": [normalize_record(r) for r in items],
    }


# --------------------------------------------------------------------------- #
# Audio bytes (preview proxy) — SSRF-guarded
# --------------------------------------------------------------------------- #
def resolve_audio_url(url_or_path: str) -> str:
    """Resolve a record's audio reference to a full URL we are allowed to fetch.

    Relative paths (``/media/...``) are prefixed with the Aisha base. Absolute URLs are
    only accepted when the host is on ``*.aisha.group``. Anything else raises ``ValueError``
    so the preview proxy can't be turned into an open relay (SSRF).
    """
    if not url_or_path:
        raise ValueError("Empty audio url.")
    full = media_url(url_or_path)  # prefixes BASE for relative paths
    host = (urlparse(full).hostname or "").lower()
    if host != _ALLOWED_HOST_SUFFIX and not host.endswith("." + _ALLOWED_HOST_SUFFIX):
        raise ValueError("Audio url host is not allowed.")
    return full


def fetch_audio_bytes(url_or_path: str):
    """Download an audio clip server-side. Returns ``(content_bytes, content_type)``."""
    full = resolve_audio_url(url_or_path)
    resp = requests.get(full, headers=_headers(), timeout=120)
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")


# --------------------------------------------------------------------------- #
# Account balance (best-effort)
# --------------------------------------------------------------------------- #
def _extract_balance(body):
    if isinstance(body, dict):
        for key in _BALANCE_KEYS:
            if key in body and isinstance(body[key], (int, float)):
                return float(body[key])
        # one level of nesting (e.g. {"account": {"balance": ...}})
        for v in body.values():
            if isinstance(v, dict):
                nested = _extract_balance(v)
                if nested is not None:
                    return nested
    return None


def get_balance():
    """Return ``{"available": True, "balance": ..., "raw": {...}}`` or ``None``.

    Tries the operator-supplied path (trusted) first, then a few guesses (accepted only if a
    numeric balance is actually found). Never raises.
    """
    candidates = []
    if settings.aisha_balance_path:
        candidates.append((settings.aisha_balance_path, True))
    candidates += [(p, False) for p in _BALANCE_CANDIDATES]

    for path, explicit in candidates:
        try:
            resp = requests.get(BASE + path, headers=_headers(), timeout=10)
        except requests.RequestException:
            continue
        if resp.status_code != 200:
            continue
        try:
            body = resp.json()
        except ValueError:
            continue
        balance = _extract_balance(body)
        if balance is not None or explicit:
            raw = body if isinstance(body, dict) else {"value": body}
            return {"available": True, "balance": balance, "raw": raw}
    return None
