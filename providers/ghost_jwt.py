"""Ghost Admin API JWT signing (stdlib only — no external dependency).

Ghost Admin auth: HS256 JWT with the key id in the header ``kid``, a 5-minute
expiry, aud="/admin/", signed with the secret decoded from hex to bytes.
Mirrors docs/ghost.md §3. Generate fresh per request — tokens expire in 5 min.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def ghost_admin_jwt(admin_api_key: str) -> str:
    """Return a signed Ghost Admin API JWT for ``<key_id>:<hex_secret>``."""
    if ":" not in admin_api_key:
        raise ValueError("Ghost Admin API key must be in '<id>:<secret>' form")
    key_id, secret_hex = admin_api_key.split(":", 1)
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT", "kid": key_id}).encode())
    now = int(time.time())
    payload = _b64url(json.dumps({"iat": now, "exp": now + 300, "aud": "/admin/"}).encode())
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = hmac.new(bytes.fromhex(secret_hex), signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64url(signature)}"
