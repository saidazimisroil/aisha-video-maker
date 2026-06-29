"""security.py - Password hashing, opaque bearer tokens, and auth dependencies.

The app uses *server-side* sessions: login mints a random ``secrets.token_urlsafe`` value,
stores only its SHA-256 hash in ``auth_sessions`` (db.py) with a 24h expiry, and hands the raw
token to the client once. Every protected request sends it as ``Authorization: Bearer <token>``.
This is fully revocable (real logout / password reset) and needs no JWT secret to manage.

Passwords are bcrypt-hashed (per-password salt built in) and never stored or returned in clear.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, Header, HTTPException, Query

from app import db
from app.config import settings

# bcrypt only considers the first 72 bytes of a password; schemas cap input accordingly.
_BCRYPT_MAX_BYTES = 72
_UNAUTH_HEADERS = {"WWW-Authenticate": "Bearer"}


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    pw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        pw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
        return bcrypt.checkpw(pw, password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# --------------------------------------------------------------------------- #
# Tokens
# --------------------------------------------------------------------------- #
def token_hash(raw: str) -> str:
    """Stable SHA-256 hex of a raw token (what we actually store / look up)."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_token() -> tuple[str, str]:
    """Return (raw_token, token_hash). The raw token is shown to the client once."""
    raw = secrets.token_urlsafe(32)
    return raw, token_hash(raw)


def token_expiry_iso() -> str:
    """ISO timestamp for when a freshly minted token should expire (now + TTL)."""
    return (datetime.now(timezone.utc)
            + timedelta(hours=settings.auth_token_ttl_hours)).isoformat()


# --------------------------------------------------------------------------- #
# FastAPI dependencies
# --------------------------------------------------------------------------- #
async def get_current_user(authorization: str | None = Header(default=None),
                           token: str | None = Query(default=None)) -> dict:
    """Resolve the bearer token to its (active, non-expired) user, else 401.

    The token normally arrives as ``Authorization: Bearer <token>``. A ``?token=`` query
    fallback exists so media the browser loads via ``<img>/<video>/<audio>`` and download
    links (which can't set headers) stay gated too.

    The returned dict carries the user's columns plus ``_auth_token_hash`` (used by logout);
    response models (UserPublic) ignore the extra key.
    """
    raw = None
    if authorization and authorization.lower().startswith("bearer "):
        raw = authorization.split(" ", 1)[1].strip()
    elif token:
        raw = token.strip()
    if not raw:
        raise HTTPException(401, "Not authenticated.", headers=_UNAUTH_HEADERS)

    th = token_hash(raw)
    user = db.get_auth_session(th)
    if not user or not user.get("is_active"):
        raise HTTPException(
            401, "Your session has expired. Please log in again.", headers=_UNAUTH_HEADERS)
    user["_auth_token_hash"] = th
    return user


def require_roles(*roles: str):
    """Build a dependency that admits only the given roles (on top of get_current_user)."""
    async def _dep(current: dict = Depends(get_current_user)) -> dict:
        if current.get("role") not in roles:
            raise HTTPException(403, "You don't have permission to do that.")
        return current
    return _dep


require_admin = require_roles("admin", "super_admin")
require_super_admin = require_roles("super_admin")
