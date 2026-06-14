import hashlib
import hmac
import time

import httpx
from django.conf import settings

REQUEST_TIMEOUT = 10.0


class GateError(Exception):
    pass


def check_gate(content: str, *, track: str | None = None, author: str | None = None,
               content_type: str = "email") -> dict:
    """Submit ``content`` to agent-service ``POST /gate/check`` and return its
    verdict dict ``{verdict, findings, gate_id, content_hash}``.

    This is the *issuing* side of the gate (verify_gate is the read-back side).
    It reuses the bearer-token agent-service client so the single gate path in
    the service stays authoritative; ``track``/``author`` are forwarded as the
    spec contract metadata. Raises ``GateError`` on any transport/config error
    so the caller fails closed."""
    from apps.common.agent_client import AgentClientError, agent_post

    payload = {"content": content, "content_type": content_type}
    if track:
        payload["track"] = track
    if author:
        payload["author"] = author
    try:
        return agent_post("/gate/check", payload)
    except AgentClientError as exc:
        raise GateError(f"gate check error: {exc}") from exc


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
