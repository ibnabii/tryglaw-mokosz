from __future__ import annotations

import base64

import httpx

from tryglaw.common.models import RelayRequest, RelayResponse

_STRIP_REQUEST_HEADERS = frozenset(("accept-encoding",))
_STRIP_RESPONSE_HEADERS = frozenset((
    "content-encoding", "transfer-encoding", "content-length",
))


async def execute_request(
    request: RelayRequest,
    timeout: float,
    tls_verify: bool = True,
) -> RelayResponse:
    verify = request.tls_verify if request.tls_verify is not None else tls_verify

    body_bytes: bytes | None = None
    if request.body_b64:
        body_bytes = base64.b64decode(request.body_b64)

    fwd_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _STRIP_REQUEST_HEADERS
    }

    try:
        async with httpx.AsyncClient(verify=verify, timeout=timeout) as client:
            resp = await client.request(
                method=request.method,
                url=request.target_url,
                headers=fwd_headers,
                content=body_bytes,
            )
        resp_body_b64: str | None = None
        if resp.content:
            resp_body_b64 = base64.b64encode(resp.content).decode()

        resp_headers = {
            k: v for k, v in resp.headers.items()
            if k.lower() not in _STRIP_RESPONSE_HEADERS
        }

        return RelayResponse(
            request_id=request.request_id,
            status_code=resp.status_code,
            headers=resp_headers,
            body_b64=resp_body_b64,
        )
    except httpx.TimeoutException:
        return RelayResponse(
            request_id=request.request_id,
            timed_out=True,
            error="target_timeout",
        )
    except Exception as e:
        return RelayResponse(
            request_id=request.request_id,
            error=f"execution_error: {e}",
        )
