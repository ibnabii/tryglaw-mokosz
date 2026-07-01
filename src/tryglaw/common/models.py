from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field


MESSAGE_VERSION = "1"


class RelayRequest(BaseModel):
    type: str = "request"
    version: str = MESSAGE_VERSION
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    mokosz_id: str
    target_url: str
    method: str
    headers: dict[str, str] = Field(default_factory=dict)
    body_b64: str | None = None
    tls_verify: bool | None = None


class RelayResponse(BaseModel):
    type: str = "response"
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
    access_keys: list[str] = Field(default_factory=list)
    supports_proxy: bool = False


class MokoszInfo(BaseModel):
    id: str
    description: str | None = None
    connected: bool
    metadata: dict[str, Any] = Field(default_factory=dict)
    last_seen: str | None = None
    supports_proxy: bool = False


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
    request_id: str | None = None
    mokosz_id: str | None = None
    system: str | None = None
    environment: str | None = None


class RegisteredAck(BaseModel):
    type: str = "registered"
    mokosz_id: str


class TunnelOpen(BaseModel):
    type: str = "tunnel_open"
    stream_id: int
    host: str
    port: int


class TunnelOpenAck(BaseModel):
    type: str = "tunnel_open_ack"
    stream_id: int
    ok: bool
    error: str | None = None


class TunnelClose(BaseModel):
    type: str = "tunnel_close"
    stream_id: int
