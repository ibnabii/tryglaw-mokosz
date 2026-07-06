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
    supports_fileshare: bool = False


class MokoszInfo(BaseModel):
    id: str
    description: str | None = None
    connected: bool
    metadata: dict[str, Any] = Field(default_factory=dict)
    last_seen: str | None = None
    supports_proxy: bool = False
    supports_fileshare: bool = False


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


class FileOpRequest(BaseModel):
    type: str = "file_op"
    version: str = MESSAGE_VERSION
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    mokosz_id: str = ""
    op: str  # list, stat, mkdir, delete, download, upload
    root: str = ""
    path: str = ""
    stream_id: int | None = None
    size: int | None = None


class FileOpResponse(BaseModel):
    type: str = "file_op_response"
    version: str = MESSAGE_VERSION
    request_id: str = ""
    ok: bool = True
    error: str | None = None
    entries: list[dict[str, Any]] | None = None
    stat: dict[str, Any] | None = None
    stream_id: int | None = None
    size: int | None = None


class FileDataEnd(BaseModel):
    type: str = "file_data_end"
    stream_id: int
