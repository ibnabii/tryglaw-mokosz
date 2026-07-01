from __future__ import annotations

import asyncio
import json
import socket
import ssl
import struct

import websockets
import websockets.exceptions

from tryglaw.common.logging import log_payload, setup_logger
from tryglaw.common.models import (
    MokoszRegistration,
    RelayRequest,
    RelayResponse,
    TunnelOpenAck,
    TunnelClose,
)
from tryglaw.mokosz.executor import execute_request
from tryglaw.mokosz.settings import MokoszSettings

STREAM_ID_FMT = ">I"
STREAM_ID_SIZE = struct.calcsize(STREAM_ID_FMT)


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
        self._logger.info("Connecting to %s", self._settings.perun_ws_url)

        async with websockets.connect(url, ssl=ssl_context) as ws:
            reg = self._build_registration()
            await ws.send(reg.model_dump_json())
            self._logger.info("Registered as %s", self._settings.description)

            async for message in ws:
                if isinstance(message, bytes):
                    asyncio.create_task(self._handle_tunnel_data(ws, message))
                else:
                    data = json.loads(message)
                    msg_type = data.get("type", "request")
                    if msg_type == "registered":
                        self._mokosz_id = data.get("mokosz_id", "")
                        self._logger.info("Registered at Perun with id: %s", self._mokosz_id)
                    elif msg_type == "tunnel_open":
                        asyncio.create_task(self._handle_tunnel_open(ws, data))
                    elif msg_type == "tunnel_close":
                        self._close_tunnel(data["stream_id"])
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
        stream_id = struct.unpack(STREAM_ID_FMT, raw[:STREAM_ID_SIZE])[0]
        payload = raw[STREAM_ID_SIZE:]
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
                frame = struct.pack(STREAM_ID_FMT, stream_id) + data
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
