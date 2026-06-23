from __future__ import annotations

import hashlib
import hmac
import secrets


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)


def compute_hmac(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def verify_hmac(payload: bytes, secret: str, signature: str) -> bool:
    expected = compute_hmac(payload, secret)
    return hmac.compare_digest(expected, signature)
