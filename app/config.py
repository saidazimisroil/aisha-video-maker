"""config.py - Environment-driven settings for the web service.

All tunables live here so deployment is pure configuration: set env vars (or a
local ``.env``) and nothing in the code changes between dev and prod. Importing
this module instantiates :data:`settings`; if ``AISHA_API_KEY`` is missing it
raises immediately, so the server fails fast at startup instead of at the first
TTS call. The CLI does **not** import this module, so it is unaffected.
"""

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Secrets / integration ------------------------------------------- #
    # Required: the server's own AIsha X-Api-Key. Every video spends its balance.
    aisha_api_key: str = Field(..., alias="AISHA_API_KEY")

    # --- Storage --------------------------------------------------------- #
    data_dir: Path = Field(Path("./data"), alias="DATA_DIR")

    # --- TTS / render defaults (overridable per request within limits) --- #
    default_language: str = Field("uz", alias="DEFAULT_LANGUAGE")
    default_mood: str = Field("Neutral", alias="DEFAULT_MOOD")
    default_width: int = Field(1280, alias="DEFAULT_WIDTH")
    default_height: int = Field(720, alias="DEFAULT_HEIGHT")
    default_fps: int = Field(24, alias="DEFAULT_FPS")
    default_dpi: int = Field(150, alias="DEFAULT_DPI")
    # TTS speech rate (uz only). 0 = API default; custom range 0.5–2.0.
    default_speed: float = Field(0.75, alias="DEFAULT_SPEED")

    # TTS polling (async 202 responses).
    tts_poll_interval: int = Field(3, alias="TTS_POLL_INTERVAL")
    tts_poll_max: int = Field(40, alias="TTS_POLL_MAX")

    # --- Audio library (Aisha TTS history proxy) ------------------------- #
    # Default page size when the dashboard browses the account's TTS history.
    audio_page_size: int = Field(12, alias="AUDIO_PAGE_SIZE")
    # Optional override for the account-balance endpoint path (relative to the
    # Aisha base). Empty = run a best-effort probe and hide the widget if none
    # of the candidates answer. Set this once you know the real path.
    aisha_balance_path: str = Field("", alias="AISHA_BALANCE_PATH")

    # How long a "build from existing audios" session may sit in AWAITING_PAIRS
    # (slides rendered, waiting for the user to pick audios) before cleanup reaps
    # it. Longer than a normal job so the user has time to pair.
    reuse_prepare_ttl_hours: int = Field(6, alias="REUSE_PREPARE_TTL_HOURS")

    # --- Limits / safety ------------------------------------------------- #
    max_upload_mb: int = Field(25, alias="MAX_UPLOAD_MB")
    max_slides: int = Field(40, alias="MAX_SLIDES")
    max_queue: int = Field(3, alias="MAX_QUEUE")

    # --- Session retention (ephemeral-disk hygiene) ---------------------- #
    session_max_age_hours: int = Field(24, alias="SESSION_MAX_AGE_HOURS")
    session_max_count: int = Field(50, alias="SESSION_MAX_COUNT")

    # --- CORS (split frontend) ------------------------------------------ #
    # Comma-separated list of allowed browser origins. "*" allows any (dev only).
    allowed_origins: str = Field("*", alias="AISHA_ALLOWED_ORIGINS")

    # --- Logging --------------------------------------------------------- #
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    @property
    def origins_list(self) -> List[str]:
        raw = (self.allowed_origins or "").strip()
        if raw in ("", "*"):
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def sessions_root(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def db_file(self) -> Path:
        """SQLite history DB, a sibling of the sessions/ folder under DATA_DIR."""
        return self.data_dir / "aisha.db"


@lru_cache
def get_settings() -> Settings:
    """Cached singleton. Raises at first call if AISHA_API_KEY is unset."""
    return Settings()


# Instantiated at import time so a misconfigured server fails fast on startup.
settings = get_settings()
