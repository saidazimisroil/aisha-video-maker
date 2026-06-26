"""schemas.py - Enums and Pydantic response models for the API.

Request options arrive as multipart form fields (they accompany the pptx upload),
so they are validated inline in ``main.py`` with FastAPI ``Form(...)`` constraints
plus the enums below. These models shape the JSON responses the frontend reads.
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel


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


class StatusResponse(BaseModel):
    session_id: str
    status: str
    slide_count: Optional[int] = None
    progress: Optional[Progress] = None
    has_output: bool = False
    error: Optional[str] = None
    output: Optional[dict] = None


class SessionSummary(BaseModel):
    session_id: str
    created_at: Optional[str] = None
    status: Optional[str] = None
    slide_count: Optional[int] = None
    has_output: bool = False
    error: Optional[str] = None


class SessionList(BaseModel):
    count: int
    results: List[SessionSummary]


class HealthResponse(BaseModel):
    ok: bool
    soffice: bool
    ffmpeg: bool
    ffprobe: bool
    queue_depth: int
