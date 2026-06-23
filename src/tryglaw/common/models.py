from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field


MESSAGE_VERSION = "1"


class RelayRequest(BaseModel):
    version: str = MESSAGE_VERSION
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    mokosz_id: str
    target_url: str
    method: str
    headers: dict[str, str] = Field(default_factory=dict)
    body_b64: str | None = None
    tls_verify: bool | None = None


class RelayResponse(BaseModel):
    version: str = MESSAGE_VERSION
    request_id: str
    status_code: int | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    body_b64: str | None = None
    error: str | None = None
    timed_out: bool = False


class MokoszRegistration(BaseModel):
    version: str = MESSAGE_VERSION
    apikey: str
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MokoszInfo(BaseModel):
    id: str
    description: str | None = None
    connected: bool
    metadata: dict[str, Any] = Field(default_factory=dict)
    last_seen: str | None = None


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
    request_id: str | None = None
    mokosz_id: str | None = None
    system: str | None = None
    environment: str | None = None
