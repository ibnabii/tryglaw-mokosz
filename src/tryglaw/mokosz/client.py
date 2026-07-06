from __future__ import annotations

import asyncio
import json
import socket
import ssl
import struct

import websockets
import websockets.exceptions

from tryglaw.common.logging import log_payload, setup_logger, startup_log
from tryglaw.common.models import (
    FileDataEnd,
    FileOpRequest,
    FileOpResponse,
    MokoszRegistration,
    RelayRequest,
    RelayResponse,
    TunnelOpenAck,
    TunnelClose,
)
from tryglaw.mokosz.executor import execute_request
from tryglaw.mokosz.settings import MokoszSettings

FRAME_FMT = ">BI"  # kind(1) + stream_id(4)
FRAME_SIZE = struct.calcsize(FRAME_FMT)
KIND_TUNNEL = 0x01
KIND_FILE = 0x02


class MokoszClient:
    def __init__(self, settings: MokoszSettings):
        self._settings = settings
        self._logger, self._payload_logger = setup_logger(
            "mokosz",
            level=settings.log_level,
            payload_log_file=settings.payload_log_file or None,
        )
        self._tunnels: dict[int, _TunnelEntry] = {}
        self._mokosz_id: str | None = None
        self._fileshare_config = None
        self._upload_queues: dict[int, asyncio.Queue[bytes | None]] = {}
        self._init_fileshare()

    def _init_fileshare(self) -> None:
        if not self._settings.fileshare_enabled:
            return
        if not self._settings.access_keys_list:
            self._logger.error(
                "MOKOSZ_FILESHARE_ENABLED=true but no MOKOSZ_ACCESS_KEYS set. "
                "File sharing disabled for security."
            )
            return
        if not self._settings.fileshare_config:
            self._logger.error("MOKOSZ_FILESHARE_ENABLED=true but no MOKOSZ_FILESHARE_CONFIG set.")
            return
        try:
            from tryglaw.mokosz.fileshare import FileshareConfig
            self._fileshare_config = FileshareConfig.load(self._settings.fileshare_config)
            startup_log(
                self._logger, "File sharing enabled with %d root(s)", len(self._fileshare_config.roots)
            )
        except Exception as e:
            self._logger.error("Failed to load fileshare config: %s", e)

    def _build_ws_url(self) -> str:
        sep = "&" if "?" in self._settings.perun_ws_url else "?"
        return f"{self._settings.perun_ws_url}{sep}apikey={self._settings.api_key}"

    def _build_registration(self) -> MokoszRegistration:
        return MokoszRegistration(
            apikey=self._settings.api_key,
            description=self._settings.description,
            metadata={"hostname": socket.gethostname()},
            access_keys=self._settings.access_keys_list,
            supports_proxy=self._settings.allow_proxy,
            supports_fileshare=self._fileshare_config is not None,
        )

    async def run(self) -> None:
        if self._settings.allow_proxy and not self._settings.access_keys_list:
            self._logger.warning(
                "MOKOSZ_ALLOW_PROXY=true but no MOKOSZ_ACCESS_KEYS set. "
                "Proxy will accept any password for this instance."
            )

        backoff = 1.0
        max_backoff = 60.0

        while True:
            try:
                await self._connect_and_listen()
                backoff = 1.0
            except (
                websockets.exceptions.ConnectionClosedError,
                websockets.exceptions.InvalidStatusCode,
                OSError,
            ) as e:
                self._logger.warning("Connection lost: %s. Reconnecting in %.1fs", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
            except asyncio.CancelledError:
                self._logger.info("Shutting down")
                break

    async def _connect_and_listen(self) -> None:
        ssl_context: ssl.SSLContext | None = None
        if self._settings.perun_ws_url.startswith("wss://"):
            ssl_context = ssl.create_default_context()
            if not self._settings.tls_verify:
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE

        url = self._build_ws_url()
        startup_log(self._logger, "Connecting to %s", self._settings.perun_ws_url)

        async with websockets.connect(url, ssl=ssl_context) as ws:
            reg = self._build_registration()
            await ws.send(reg.model_dump_json())
            startup_log(self._logger, "Registered as %s", self._settings.description)

            async for message in ws:
                if isinstance(message, bytes):
                    kind = message[0]
                    if kind == KIND_TUNNEL:
                        asyncio.create_task(self._handle_tunnel_data(ws, message))
                    elif kind == KIND_FILE:
                        self._handle_file_data(message)
                else:
                    data = json.loads(message)
                    msg_type = data.get("type", "request")
                    if msg_type == "registered":
                        self._mokosz_id = data.get("mokosz_id", "")
                        startup_log(self._logger, "Registered at Perun with id: %s", self._mokosz_id)
                    elif msg_type == "tunnel_open":
                        asyncio.create_task(self._handle_tunnel_open(ws, data))
                    elif msg_type == "tunnel_close":
                        self._close_tunnel(data["stream_id"])
                    elif msg_type == "file_op":
                        asyncio.create_task(self._handle_file_op(ws, data))
                    elif msg_type == "file_data_end":
                        self._end_file_upload(data["stream_id"])
                    else:
                        asyncio.create_task(self._handle_request(ws, message))

    async def _handle_request(self, ws, raw: str) -> None:
        try:
            request = RelayRequest(**json.loads(raw))
            self._logger.info(
                "Received request %s -> %s %s",
                request.request_id[:8],
                request.method,
                request.target_url,
            )
            log_payload(self._payload_logger, "REQUEST", request.model_dump())

            response = await execute_request(
                request,
                timeout=self._settings.target_timeout,
                tls_verify=self._settings.tls_verify,
            )

            if response.error:
                self._logger.error(
                    "Request %s FAILED | %s %s | error: %s",
                    response.request_id[:8],
                    request.method,
                    request.target_url,
                    response.error,
                )
            elif response.timed_out:
                self._logger.warning(
                    "Request %s TIMED OUT | %s %s",
                    response.request_id[:8],
                    request.method,
                    request.target_url,
                )
            else:
                self._logger.info(
                    "Response %s | status=%s | %s %s",
                    response.request_id[:8],
                    response.status_code,
                    request.method,
                    request.target_url,
                )
            log_payload(self._payload_logger, "RESPONSE", response.model_dump())

            await ws.send(response.model_dump_json())
        except Exception as e:
            self._logger.error("Error handling request: %s", e)
            error_resp = RelayResponse(
                request_id=json.loads(raw).get("request_id", "unknown"),
                error=f"execution_error: {e}",
            )
            await ws.send(error_resp.model_dump_json())

    async def _handle_tunnel_open(self, ws, data: dict) -> None:
        stream_id = data["stream_id"]
        host = data["host"]
        port = data["port"]
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=15.0,
            )
        except Exception as e:
            self._logger.warning("Tunnel open failed %s:%d: %s", host, port, e)
            ack = TunnelOpenAck(stream_id=stream_id, ok=False, error=str(e))
            await ws.send(ack.model_dump_json())
            return

        self._logger.info("Tunnel opened stream=%d -> %s:%d", stream_id, host, port)
        ack = TunnelOpenAck(stream_id=stream_id, ok=True)
        await ws.send(ack.model_dump_json())

        pump_task = asyncio.create_task(self._pump_target_to_ws(ws, stream_id, reader))
        self._tunnels[stream_id] = _TunnelEntry(reader, writer, pump_task)

    async def _handle_tunnel_data(self, ws, raw: bytes) -> None:
        _, stream_id = struct.unpack(FRAME_FMT, raw[:FRAME_SIZE])
        payload = raw[FRAME_SIZE:]
        entry = self._tunnels.get(stream_id)
        if entry and not entry.writer.is_closing():
            entry.writer.write(payload)
            await entry.writer.drain()

    async def _pump_target_to_ws(self, ws, stream_id: int, reader: asyncio.StreamReader) -> None:
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                frame = struct.pack(FRAME_FMT, KIND_TUNNEL, stream_id) + data
                await ws.send(frame)
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            close_msg = TunnelClose(stream_id=stream_id)
            try:
                await ws.send(close_msg.model_dump_json())
            except Exception:
                pass
            self._tunnels.pop(stream_id, None)

    def _handle_file_data(self, raw: bytes) -> None:
        _, stream_id = struct.unpack(FRAME_FMT, raw[:FRAME_SIZE])
        payload = raw[FRAME_SIZE:]
        q = self._upload_queues.get(stream_id)
        if q:
            q.put_nowait(payload)

    def _end_file_upload(self, stream_id: int) -> None:
        q = self._upload_queues.get(stream_id)
        if q:
            q.put_nowait(None)

    async def _handle_file_op(self, ws, data: dict) -> None:
        from tryglaw.mokosz.fileshare import (
            list_dir, stat_path, mkdir, delete_path, stream_download,
        )
        req = FileOpRequest(**data)
        try:
            if not self._fileshare_config:
                raise PermissionError("fileshare_not_enabled")

            root = self._fileshare_config.get_root(req.root)
            if not root:
                raise FileNotFoundError(f"unknown_root: {req.root}")

            if req.op == "list" and not req.root:
                entries = [
                    {"name": r.name, "is_dir": True, "size": 0, "mtime": 0, "writable": r.writable}
                    for r in self._fileshare_config.roots
                ]
                resp = FileOpResponse(request_id=req.request_id, ok=True, entries=entries)
                await ws.send(resp.model_dump_json())
                return

            if req.op == "list":
                entries = list_dir(root, req.path)
                resp = FileOpResponse(request_id=req.request_id, ok=True, entries=entries)
                await ws.send(resp.model_dump_json())

            elif req.op == "stat":
                if req.path in ("", "."):
                    info = {"name": root.name, "is_dir": True, "size": 0, "mtime": 0, "writable": root.writable}
                    resp = FileOpResponse(request_id=req.request_id, ok=True, stat=info)
                    await ws.send(resp.model_dump_json())
                    return
                info = stat_path(root, req.path)
                resp = FileOpResponse(request_id=req.request_id, ok=True, stat=info)
                await ws.send(resp.model_dump_json())

            elif req.op == "mkdir":
                mkdir(root, req.path)
                resp = FileOpResponse(request_id=req.request_id, ok=True)
                await ws.send(resp.model_dump_json())

            elif req.op == "delete":
                delete_path(root, req.path)
                resp = FileOpResponse(request_id=req.request_id, ok=True)
                await ws.send(resp.model_dump_json())

            elif req.op == "download":
                import os as _os
                from tryglaw.mokosz.fileshare import safe_resolve
                target = safe_resolve(root, req.path)
                file_size = _os.path.getsize(target)
                resp = FileOpResponse(
                    request_id=req.request_id, ok=True,
                    stream_id=req.stream_id, size=file_size,
                )
                await ws.send(resp.model_dump_json())
                await stream_download(ws, root, req.path, req.stream_id)

            elif req.op == "upload":
                q: asyncio.Queue[bytes | None] = asyncio.Queue()
                self._upload_queues[req.stream_id] = q
                resp = FileOpResponse(request_id=req.request_id, ok=True)
                await ws.send(resp.model_dump_json())

                max_bytes = self._fileshare_config.max_file_size_mb * 1024 * 1024
                from tryglaw.mokosz.fileshare import safe_resolve
                if not root.writable:
                    raise PermissionError("root_not_writable")
                target = safe_resolve(root, req.path)
                target.parent.mkdir(parents=True, exist_ok=True)

                total = 0
                with open(target, "wb") as f:
                    while True:
                        chunk = await asyncio.wait_for(q.get(), timeout=120.0)
                        if chunk is None:
                            break
                        total += len(chunk)
                        if total > max_bytes:
                            raise PermissionError("file_too_large")
                        f.write(chunk)

                self._upload_queues.pop(req.stream_id, None)
                done_resp = FileOpResponse(request_id=req.request_id, ok=True)
                await ws.send(done_resp.model_dump_json())
            else:
                raise ValueError(f"unknown_op: {req.op}")

        except Exception as e:
            self._logger.error("File op error: %s", e)
            resp = FileOpResponse(request_id=req.request_id, ok=False, error=str(e))
            await ws.send(resp.model_dump_json())

    def _close_tunnel(self, stream_id: int) -> None:
        entry = self._tunnels.pop(stream_id, None)
        if entry:
            if not entry.writer.is_closing():
                entry.writer.close()
            entry.pump_task.cancel()


class _TunnelEntry:
    __slots__ = ("reader", "writer", "pump_task")

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        pump_task: asyncio.Task,
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.pump_task = pump_task
