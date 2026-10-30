from __future__ import annotations

import base64
import hashlib
import hmac
import time


def create_asset_token(job_id: str, secret: str, expires_at: int) -> str:
    payload = f"{job_id}:{expires_at}".encode()
    signature = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    encoded = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{expires_at}.{encoded}"


def verify_asset_token(job_id: str, token: str, secret: str) -> bool:
    try:
        expiry_text, supplied = token.split(".", 1)
        expires_at = int(expiry_text)
    except (ValueError, TypeError):
        return False
    if expires_at < int(time.time()):
        return False
    expected = create_asset_token(job_id, secret, expires_at).split(".", 1)[1]
    return hmac.compare_digest(supplied, expected)

