import hashlib
import hmac
import time

import httpx
from django.conf import settings

REQUEST_TIMEOUT = 10.0


class GateError(Exception):
    pass


def verify_gate(gate_id: str) -> dict:
    """Call agent-service GET /gate/verify/{id} with HMAC signing. Returns
    {gate_id, verdict, content_hash} or raises GateError."""
    base = getattr(settings, "AGENT_SERVICE_BASE_URL", "").rstrip("/")
    secret = getattr(settings, "STUDIO_SHARED_SECRET", "")
    deployment = getattr(settings, "STUDIO_DEPLOYMENT_ID", "platform")
    if not base or not secret:
        raise GateError("gate client not configured")
    path = f"/gate/verify/{gate_id}"
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), f"{ts}:{path}".encode(), hashlib.sha256).hexdigest()
    headers = {"X-Studio-Deployment": deployment, "X-Studio-Timestamp": ts,
               "X-Studio-Signature": sig}
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as c:
            resp = c.get(base + path, headers=headers)
    except httpx.HTTPError as exc:
        raise GateError(f"gate verify transport error: {exc}") from exc
    if resp.status_code != 200:
        raise GateError(f"gate verify status {resp.status_code}")
    return resp.json()
