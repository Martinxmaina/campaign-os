"""HMAC verification for the TWG → Campaign OS webhook.

Contract (Lazarus, 2026-07-06): signature = HMAC-SHA256 over the exact bytes
``f"{timestamp}.".encode() + raw_body`` with a shared secret, sent as
``sha256=<hex>``. Verify against the RAW request bytes (never parse-then-
re-serialize), constant-time compare, reject timestamps outside ±5 min.
"""

from __future__ import annotations

import hashlib
import hmac
import time

REPLAY_WINDOW_SECONDS = 300


def verify(raw_body: bytes, timestamp: str, signature_header: str, secret: str) -> bool:
    """Return True iff the signature is valid and the timestamp is fresh."""
    if not secret:
        # No shared secret configured → cannot trust anything. Fail closed.
        return False
    # 1. replay guard — reject stale/absent timestamps (±5 min)
    try:
        if abs(time.time() - int(timestamp)) > REPLAY_WINDOW_SECONDS:
            return False
    except (TypeError, ValueError):
        return False
    # 2. recompute over the EXACT raw bytes
    signing_input = f"{timestamp}.".encode("utf-8") + raw_body
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).hexdigest()
    # 3. constant-time compare (never ==)
    return hmac.compare_digest(expected, signature_header or "")
