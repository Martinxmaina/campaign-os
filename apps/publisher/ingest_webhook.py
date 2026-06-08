"""Outbound webhook → agent-service ``/ingest``.

The fork emits platform events (publish results, social engagement, analytics
snapshots) to the agent-service ingest endpoint. ``/ingest`` authenticates with
a per-feed ``X-Ingest-Key`` header (Phase 0 contract) — distinct from the
HMAC-signed gate-verify path. Failures are the caller's responsibility to log;
this module raises on misconfiguration or HTTP error.
"""

from datetime import datetime, timezone

import httpx
from django.conf import settings

REQUEST_TIMEOUT = 10.0


def post_to_ingest(*, source_type: str, source_id: str, payload: dict, dedupe_key: str) -> dict:
    url = getattr(settings, "AGENT_SERVICE_INGEST_URL", "")
    key = getattr(settings, "AGENT_SERVICE_INGEST_KEY", "")
    if not url or not key:
        raise RuntimeError("ingest webhook not configured")
    body = {
        "source_type": source_type,
        "source_id": source_id,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
        "dedupe_key": dedupe_key,
    }
    with httpx.Client(timeout=REQUEST_TIMEOUT) as c:
        resp = c.post(url, headers={"X-Ingest-Key": key}, json=body)
    resp.raise_for_status()
    return resp.json()
