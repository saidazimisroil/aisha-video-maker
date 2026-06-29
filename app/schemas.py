"""schemas.py - Enums and Pydantic models for the API.

Request options for the create flows arrive as multipart form fields (they accompany the
pptx upload), so they are validated inline in ``main.py`` with FastAPI ``Form(...)``
constraints plus the enums below. JSON request bodies (rename, reuse pairs) and every JSON
response are shaped by the models here.
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class Language(str, Enum):
    uz = "uz"
    en = "en"
    ru = "ru"


class Mood(str, Enum):
    Neutral = "Neutral"
    Cheerful = "Cheerful"
    Happy = "Happy"
    Sad = "Sad"


# Allowed output heights (16:9 widths are derived). Keeps 1080p opt-in.
ALLOWED_HEIGHTS = [480, 720, 1080]
HEIGHT_TO_WIDTH = {480: 854, 720: 1280, 1080: 1920}
FPS_MIN, FPS_MAX = 12, 30
# Aisha TTS speed (uz only): 0 = API default, or a custom value in 0.5–2.0.
SPEED_MIN, SPEED_MAX = 0.5, 2.0


class Progress(BaseModel):
    phase: str
    current: int
    total: int
    message: str = ""


class CreateSessionResponse(BaseModel):
    session_id: str
    status: str
    kind: str = "tts"


class StatusResponse(BaseModel):
    session_id: str
    status: str
    title: Optional[str] = None
    kind: str = "tts"
    slide_count: Optional[int] = None
    progress: Optional[Progress] = None
    has_output: bool = False
    error: Optional[str] = None
    output: Optional[dict] = None


class SessionSummary(BaseModel):
    session_id: str
    title: Optional[str] = None
    kind: str = "tts"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    status: Optional[str] = None
    slide_count: Optional[int] = None
    duration: Optional[float] = None
    has_output: bool = False
    error: Optional[str] = None


class SessionList(BaseModel):
    count: int            # total matching (across all pages)
    page: int = 1
    limit: int = 20
    results: List[SessionSummary]


class RenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)


# --------------------------------------------------------------------------- #
# Audio library (proxied Aisha TTS history)
# --------------------------------------------------------------------------- #
class AudioRecord(BaseModel):
    # The upstream /tts/get/ schema is undocumented, so stay lenient: every field is
    # optional and unknown upstream keys are preserved (extra="allow").
    model_config = ConfigDict(extra="allow")

    id: Optional[str] = None
    audio_url: Optional[str] = None
    transcript: Optional[str] = None
    language: Optional[str] = None
    status: Optional[str] = None
    created_at: Optional[str] = None


class AudioList(BaseModel):
    count: Optional[int] = None
    page: int = 1
    limit: int = 12
    results: List[AudioRecord]


# --------------------------------------------------------------------------- #
# Text-to-speech (single clip)
# --------------------------------------------------------------------------- #
class TTSCreateRequest(BaseModel):
    # The 1000-character cap (the Aisha CHAR_LIMIT) and speed range are enforced in the
    # route with friendly messages, mirroring the create-video flow's inline validation.
    transcript: str
    language: Language = Language.uz
    mood: Mood = Mood.Neutral
    model: str = "Gulnoza"
    speed: float = 0.75


class TTSCreateResponse(BaseModel):
    id: Optional[str] = None
    audio_url: Optional[str] = None
    transcript: str
    language: str
    status: str = "SUCCESS"
    created_at: Optional[str] = None


# --------------------------------------------------------------------------- #
# Build from existing audios
# --------------------------------------------------------------------------- #
class ReusePair(BaseModel):
    slide_index: int = Field(..., ge=1)
    audio_id: Optional[str] = None
    audio_url: str = Field(..., min_length=1)


class ReuseBuildRequest(BaseModel):
    pairs: List[ReusePair] = Field(..., min_length=1)


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
class StatsResponse(BaseModel):
    total: int
    by_status: dict
    by_kind: dict
    total_duration: float
    total_slides: int
    queue_depth: int


class AccountResponse(BaseModel):
    available: bool
    balance: Optional[float] = None
    raw: Optional[dict] = None


class HealthResponse(BaseModel):
    ok: bool
    soffice: bool
    ffmpeg: bool
    ffprobe: bool
    queue_depth: int


# --------------------------------------------------------------------------- #
# Auth / user management
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    user = "user"
    admin = "admin"
    super_admin = "super_admin"


# Usernames: 3–50 chars, letters/digits/._- (case-insensitive uniqueness in db).
# Passwords: 8–72 chars (bcrypt only hashes the first 72 bytes).
_USERNAME = Field(..., min_length=3, max_length=50, pattern=r"^[A-Za-z0-9._-]+$")
_PASSWORD = Field(..., min_length=8, max_length=72)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=72)


class UserPublic(BaseModel):
    """A user as exposed to API callers — never includes the password hash."""
    id: str
    username: str
    role: UserRole = UserRole.user
    is_active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    last_login_at: Optional[str] = None


class LoginResponse(BaseModel):
    token: str
    expires_at: str
    user: UserPublic


class UserCreate(BaseModel):
    username: str = _USERNAME
    password: str = _PASSWORD
    # Requested role; an 'admin' caller is downgraded to 'user' in the route.
    role: UserRole = UserRole.user


class UserUpdate(BaseModel):
    username: Optional[str] = Field(None, min_length=3, max_length=50,
                                    pattern=r"^[A-Za-z0-9._-]+$")
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class PasswordResetRequest(BaseModel):
    new_password: str = _PASSWORD


class UserList(BaseModel):
    count: int            # total matching (across all pages)
    page: int = 1
    limit: int = 20
    results: List[UserPublic]
