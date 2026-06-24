from __future__ import annotations

import asyncio
import json
import socket
import ssl

import websockets
import websockets.exceptions

from tryglaw.common.logging import log_payload, setup_logger
from tryglaw.common.models import MokoszRegistration, RelayRequest, RelayResponse
from tryglaw.mokosz.executor import execute_request
from tryglaw.mokosz.settings import MokoszSettings


class MokoszClient:
    def __init__(self, settings: MokoszSettings):
        self._settings = settings
        self._logger, self._payload_logger = setup_logger(
            "mokosz",
            level=settings.log_level,
            payload_log_file=settings.payload_log_file or None,
        )

    def _build_ws_url(self) -> str:
        sep = "&" if "?" in self._settings.perun_ws_url else "?"
        return f"{self._settings.perun_ws_url}{sep}apikey={self._settings.api_key}"

    def _build_registration(self) -> MokoszRegistration:
        return MokoszRegistration(
            apikey=self._settings.api_key,
            description=self._settings.description,
            metadata={"hostname": socket.gethostname()},
        )

    async def run(self) -> None:
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
