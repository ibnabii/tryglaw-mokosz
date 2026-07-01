# Tryglaw - Mokosz

Restricted environment agent that connects to Perun and executes API calls to target systems on behalf of Weles. Optionally allows web proxy connections for browsing the web from this machine.

## Table of Contents

- [What it does](#what-it-does)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running](#running)
- [Registered ID](#registered-id)
- [Web proxy support](#web-proxy-support)
- [Access-key pairing](#access-key-pairing)
- [Encrypted connection](#encrypted-connection-wss-vs-ws)
- [Registration metadata](#registration-metadata)
- [Behavior](#behavior)

## What it does

Mokosz runs inside a restricted environment (where target systems are accessible) and maintains a persistent WebSocket connection to Perun. When a request arrives from Weles (via Perun), Mokosz executes the actual HTTP call to the target URL and returns the response. It can also serve as a tunnel endpoint for the Perun web proxy, allowing a browser to browse pages as if from this machine.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install .
```

## Configuration

Copy `.env.template` to `.env` and configure:

| Variable | Description | Default |
|----------|-------------|---------|
| MOKOSZ_PERUN_WS_URL | Perun WebSocket URL | ws://localhost:9000/ws |
| MOKOSZ_API_KEY | API key for authenticating to Perun | (required) |
| MOKOSZ_DESCRIPTION | Human-readable instance description | Mokosz Instance |
| MOKOSZ_TARGET_TIMEOUT | Timeout for target HTTP calls (seconds) | 300 |
| MOKOSZ_ACCESS_KEYS | Comma-separated access keys for Weles pairing (empty = open to all) | (empty) |
| MOKOSZ_ALLOW_PROXY | Allow web proxy connections through this instance | false |
| MOKOSZ_LOG_LEVEL | Logging level | DEBUG |
| MOKOSZ_PAYLOAD_LOG_FILE | File path for payload logging | (optional) |
| MOKOSZ_TLS_VERIFY | Verify TLS certificates for target calls | true |

## Running

```bash
python -m tryglaw.mokosz
```

Mokosz will connect to Perun, register itself, and begin listening for requests. If the connection drops, it reconnects automatically with exponential backoff (1s, 2s, 4s, ... up to 60s).

## Registered ID

On successful registration, Perun assigns this Mokosz instance a UUID and sends it back. Mokosz prints the UUID to stdout:

```
Registered with Perun as mokosz_id=a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

This UUID is needed as the **username** when logging into the Perun web proxy. It is stable across reconnects (tied to the API key, not the connection).

## Web proxy support

When `MOKOSZ_ALLOW_PROXY=true`, this Mokosz instance advertises proxy support to Perun. A browser configured to use Perun's proxy can then browse the web as if from this machine by authenticating with:
- **Username**: this Mokosz's UUID (printed to stdout on start)
- **Password**: one of this Mokosz's `MOKOSZ_ACCESS_KEYS`

If `MOKOSZ_ALLOW_PROXY=true` but no `MOKOSZ_ACCESS_KEYS` are set, Mokosz starts with a warning and accepts any password for proxy connections. This is useful for testing but not recommended for production.

### How proxy tunneling works

When a browser sends a CONNECT or HTTP request through the Perun proxy, Perun opens a tunnel through this Mokosz's WebSocket. Mokosz creates a real TCP connection to the target host from its own network and pipes bytes in both directions. For HTTPS, the browser's TLS is end-to-end to the target (Mokosz/Perun never see the decrypted content).

All tunnel traffic rides the existing Mokosz-Perun WebSocket, so it inherits the same encryption (`wss://` for TLS).

## Access-key pairing

Access keys control which Weles instances can discover and use this Mokosz. They are a shared-secret mechanism, separate from the Perun API keys used for authentication. Access keys also double as the proxy password when web proxy is enabled.

### How it works

- A Mokosz that declares **no keys** (`MOKOSZ_ACCESS_KEYS=` or unset) is **open to every Weles** that can reach Perun, no restrictions.
- A Mokosz that declares one or more keys is **only visible and routable** by Weles instances that share at least one matching key.

Pairing is checked both during discovery (`GET /mokosz`) and routing (`POST /api/v1/requests`). A Weles that tries to route to a Mokosz it is not paired with receives HTTP 403 `mokosz_forbidden`.

Keys are sent to Perun on every (re)connect, so if you change `MOKOSZ_ACCESS_KEYS` and restart Mokosz, the new key list takes effect immediately for all future discovery and routing.

### Example

| Instance | Keys |
|----------|------|
| Mokosz-A | `key-alpha, key-beta` |
| Mokosz-B | (none, open) |
| Weles-1 | `key-beta, key-gamma` |
| Weles-2 | `key-gamma` |

- **Weles-1** sees Mokosz-A (shares `key-beta`) and Mokosz-B (open).
- **Weles-2** sees only Mokosz-B (open). It cannot see or route to Mokosz-A (no shared key).

### Generating keys

```bash
python -m tryglaw.mokosz.admin_cli generate-key
```

The key is printed to stdout. Copy it and add it to:
1. This Mokosz's `.env`: `MOKOSZ_ACCESS_KEYS=<key>` (comma-separated if multiple).
2. The corresponding Weles instance's `.env` or Settings tab: `WELES_ACCESS_KEYS=<key>`.

### Configuration

Set keys as a comma-separated list in `.env`:

```
MOKOSZ_ACCESS_KEYS=key-example-1,key-example-2
```

Whitespace around keys is trimmed. An empty value or missing variable means the instance is open to all.

## Encrypted connection (wss vs ws)

The `MOKOSZ_PERUN_WS_URL` setting controls whether the Mokosz-Perun channel is encrypted:

| URL scheme | Encryption | Use when |
|------------|-----------|----------|
| `ws://host:port/ws` | None (plaintext) | Local development, both on same machine |
| `wss://host:port/ws` | TLS encrypted | Any network deployment |

With `ws://`, all traffic between Mokosz and Perun (request payloads, API keys, response bodies, tunnel data) is visible to network traffic analyzers. With `wss://`, the channel is encrypted end-to-end.

To switch to encrypted mode:
1. Configure TLS on Perun (see Perun README).
2. Change `MOKOSZ_PERUN_WS_URL=wss://perun-host:19000/ws`.

### MOKOSZ_TLS_VERIFY

Controls whether Mokosz verifies Perun's TLS certificate when using `wss://`:

| Value | Behavior |
|-------|----------|
| `true` (default) | Rejects connections if the certificate is not trusted |
| `false` | Accepts any certificate, including self-signed ones |

Set `MOKOSZ_TLS_VERIFY=false` for self-signed certificates. For production with CA-issued certificates, keep the default `true`.

This setting only affects the Mokosz-to-Perun WebSocket connection. Certificate verification for target HTTP calls is controlled separately by `WELES_TARGET_TLS_VERIFY` (passed through the relay request from Weles).

## Registration metadata

On connect, Mokosz sends its description, hostname, and proxy support status to Perun:

```json
{
  "apikey": "...",
  "description": "Production gateway",
  "metadata": { "hostname": "restricted-host-01" },
  "access_keys": ["key-alpha"],
  "supports_proxy": true
}
```

Mokosz is a pure executor. It does not declare system or environment. All routing configuration is managed in Weles via named aliases. See `README_weles.md` for details.

## Behavior

- Handles multiple concurrent requests in parallel.
- Each incoming request spawns an async task that executes the HTTP call.
- If the target system does not respond within `MOKOSZ_TARGET_TIMEOUT`, a timeout marker is sent back (which Perun translates to HTTP 504 for Weles).
- Proxy tunnel connections are handled concurrently alongside relay requests.
- Verbose logging to stdout shows each request/response. Optionally, full payloads are written to a log file.
