from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, field_validator

MAX_PASSWORD_BYTES = 72  # bcrypt only uses the first 72 bytes and newer versions reject more


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)

    @field_validator("password")
    @classmethod
    def password_fits_bcrypt(cls, v: str) -> str:
        if len(v.encode("utf-8")) > MAX_PASSWORD_BYTES:
            raise ValueError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes")
        return v


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str


class MonitorIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: HttpUrl
    method: Literal["GET", "HEAD"] = "GET"
    interval_s: int = Field(60, ge=30, le=3600)
    timeout_s: float = Field(10.0, gt=0, le=30)
    expected_status: int = Field(200, ge=100, le=599)


class MonitorPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    interval_s: int | None = Field(None, ge=30, le=3600)
    timeout_s: float | None = Field(None, gt=0, le=30)
    expected_status: int | None = Field(None, ge=100, le=599)
    is_active: bool | None = None


class MonitorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    url: str
    method: str
    interval_s: int
    timeout_s: float
    expected_status: int
    is_active: bool
    status: str
    last_checked_at: datetime | None
    created_at: datetime


class CheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    checked_at: datetime
    ok: bool
    status_code: int | None
    latency_ms: float | None
    error: str | None


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    started_at: datetime
    resolved_at: datetime | None
    cause: str


class Stats(BaseModel):
    hours: int
    checks: int
    uptime_pct: float | None
    avg_latency_ms: float | None
    p95_latency_ms: float | None
    incidents: int
