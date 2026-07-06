"""TWG → Campaign OS ingest endpoint.

``POST /api/ingest/twg-meeting`` — HMAC-verified, idempotent, ACK-fast.

We verify the signature against the raw bytes, persist the event BEFORE any
processing (so a worker/deploy hiccup can't silently drop a meeting), then
enqueue drafting and return 200. Re-delivery of the same meeting is a no-op.
No shared secret configured → fail closed (403), which doubles as the off
switch until go-live.
"""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.http import HttpResponseForbidden, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from .models import TwgMeetingEvent
from .signing import verify

logger = logging.getLogger(__name__)

EXPECTED_EVENT = "minutes.published"


@csrf_exempt
@ratelimit(key="ip", rate="60/m", block=True)
@require_POST
def twg_meeting(request):
    raw = request.body
    secret = getattr(settings, "TWG_WEBHOOK_SECRET", "")

    timestamp = request.headers.get("X-WAIIS-Timestamp", "")
    signature = request.headers.get("X-WAIIS-Signature", "")
    if not verify(raw, timestamp, signature, secret):
        logger.warning("TWG ingest: invalid signature / stale timestamp")
        return HttpResponseForbidden("invalid signature")

    event = request.headers.get("X-WAIIS-Event", "")
    if event != EXPECTED_EVENT:
        return JsonResponse({"error": "unsupported_event", "event": event}, status=400)

    meeting_id = request.headers.get("X-WAIIS-Meeting-Id", "").strip()
    if not meeting_id:
        return JsonResponse({"error": "missing_meeting_id"}, status=400)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid_json"}, status=400)

    # Persist before processing; dedupe on the sender's stable meeting id.
    obj, created = TwgMeetingEvent.objects.get_or_create(
        meeting_id=meeting_id,
        defaults={"event": event, "payload": payload},
    )
    if not created:
        return JsonResponse({"status": "duplicate", "meeting_id": meeting_id}, status=200)

    from .tasks import process_twg_meeting

    process_twg_meeting.delay(str(obj.id))
    return JsonResponse({"status": "accepted", "meeting_id": meeting_id}, status=200)
