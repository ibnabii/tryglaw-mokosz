from __future__ import annotations

import hashlib
import hmac
import json
import secrets


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)


def compute_hmac(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def verify_hmac(payload: bytes, secret: str, signature: str) -> bool:
    expected = compute_hmac(payload, secret)
    return hmac.compare_digest(expected, signature)


def parse_key_list(value: str | list | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if not isinstance(value, str):
        return []
    value = value.strip()
    if not value:
        return []
    if value.startswith("["):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(v).strip() for v in parsed if str(v).strip()]
        except (json.JSONDecodeError, ValueError):
            pass
    return [v.strip() for v in value.split(",") if v.strip()]


def keys_paired(mokosz_keys: list[str], weles_keys: list[str]) -> bool:
    if not mokosz_keys:
        return True
    return bool(set(mokosz_keys) & set(weles_keys))
