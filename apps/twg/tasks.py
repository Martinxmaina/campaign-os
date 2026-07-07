"""Process an inbound TWG meeting via HERALD.

Runs off the webhook (the row is already persisted, so a failure here never
loses the meeting — it can be re-queued). Flow: HERALD curates the public-safe
payload into a content plan (understand → curate → decide) → create a Post with
the curated per-channel drafts (incl. the Ghost Nexus Brief) → route on HERALD's
decision:

  publish → schedule_now() → the publish engine gates + dispatches, Ghost-first,
            so [NEXUS BRIEF LINK] resolves for the social posts.
  hold    → one bundled review email to Joseph (human decides).
  none    → nothing worth posting; record and stop.

The authoritative compliance gate still runs at publish (engine._dispatch_to_provider).
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


def _build_brief(payload: dict) -> str:
    """Compose the public-safe master text (kept as the Post's base caption)."""

    def _lines(items):
        return "\n".join(f"- {x}" for x in (items or []) if str(x).strip())

    parts = [
        payload.get("meeting_title", "TWG meeting"),
        f"Pillar: {payload.get('twg_pillar', '')} | Date: {payload.get('date', '')}".strip(),
    ]
    if payload.get("public_highlights"):
        parts.append("Highlights:\n" + _lines(payload["public_highlights"]))
    if payload.get("public_decisions_milestones"):
        parts.append("Decisions & milestones:\n" + _lines(payload["public_decisions_milestones"]))
    if payload.get("institutions_public"):
        parts.append("Institutions: " + ", ".join(payload["institutions_public"]))
    if payload.get("next_milestone"):
        parts.append(f"Next milestone: {payload['next_milestone']}")
    if payload.get("minutes_url"):
        parts.append(f"Minutes: {payload['minutes_url']}")
    return "\n\n".join(p for p in parts if p and p.strip())


def _resolve_workspace():
    from apps.workspaces.models import Workspace

    ws_id = (getattr(settings, "TWG_INGEST_WORKSPACE_ID", "") or "").strip()
    if not ws_id:
        return None
    return Workspace.objects.filter(id=ws_id).first()


def _append_hashtags(caption: str, hashtags) -> str:
    tags = [str(t).lstrip("#") for t in (hashtags or []) if str(t).strip()]
    if not tags:
        return caption
    return caption.rstrip() + "\n\n" + " ".join("#" + t for t in tags)


@shared_task
def process_twg_meeting(event_id: str) -> str:
    from apps.approvals.assignment_service import assign_for_review
    from apps.composer.models import PlatformPost, Post
    from apps.composer.views import schedule_now
    from apps.social_accounts.models import SocialAccount

    from .herald import curate, herald_platform
    from .models import TwgMeetingEvent

    event = TwgMeetingEvent.objects.filter(id=event_id).first()
    if event is None:
        logger.warning("process_twg_meeting: event %s not found", event_id)
        return "missing"
    if event.status != TwgMeetingEvent.Status.RECEIVED:
        return f"noop:{event.status}"

    event.status = TwgMeetingEvent.Status.PROCESSING
    event.save(update_fields=["status"])

    try:
        payload = event.payload or {}
        workspace = _resolve_workspace()
        if workspace is None:
            raise RuntimeError("TWG_INGEST_WORKSPACE_ID unset or workspace not found")

        # Connected channels grouped by HERALD platform (first per platform).
        accounts = {}
        for a in SocialAccount.objects.filter(
            workspace=workspace, connection_status=SocialAccount.ConnectionStatus.CONNECTED
        ):
            hp = herald_platform(a.platform)
            if hp and hp not in accounts:
                accounts[hp] = a

        plan = curate(payload, sorted(accounts))
        decision = plan.get("decision")

        if decision == "none":
            event.status = TwgMeetingEvent.Status.SKIPPED
            event.error = (plan.get("reason") or "nothing post-worthy")[:2000]
            event.processed_at = timezone.now()
            event.save(update_fields=["status", "error", "processed_at"])
            return "none"

        post = Post.objects.create(
            workspace=workspace,
            title=(payload.get("meeting_title", "") or "TWG meeting")[:255],
            caption=_build_brief(payload),
            ai_brief={
                "source": "twg",
                "meeting_id": event.meeting_id,
                "minutes_url": payload.get("minutes_url", ""),
                "herald_decision": decision,
                "herald_reason": plan.get("reason", ""),
            },
            tags=["twg", event.meeting_id],
        )

        created = 0
        for p in plan.get("posts", []):
            acct = accounts.get((p.get("platform") or "").lower())
            if not acct:
                continue
            caption = p.get("caption") or ""
            # Ghost is long-form; the others get their hashtags appended.
            if herald_platform(acct.platform) != "ghost":
                caption = _append_hashtags(caption, p.get("hashtags"))
            PlatformPost.objects.create(
                post=post,
                social_account=acct,
                status=PlatformPost.Status.DRAFT,
                platform_specific_caption=caption,
            )
            created += 1

        if created == 0:
            raise RuntimeError("HERALD returned no posts matching a connected channel")

        event.post = post

        if decision == "publish":
            # Hand to the publish engine: it gates every child and dispatches
            # Ghost-first, so [NEXUS BRIEF LINK] resolves for the social posts.
            schedule_now(post)
        else:  # hold → one bundled review email to Joseph
            joseph = (getattr(settings, "JOSEPH_APPROVER_EMAIL", "") or "").strip()
            if joseph:
                assign_for_review(
                    post=post, assigned_by=None,
                    reviewer_email=joseph, reviewer_name="Joseph Nganga",
                )

        event.status = TwgMeetingEvent.Status.DRAFTED
        event.processed_at = timezone.now()
        event.save(update_fields=["post", "status", "processed_at"])
        return f"{decision}:{post.id}"

    except Exception as exc:  # noqa: BLE001 — persist the failure, never lose the event
        logger.exception("process_twg_meeting failed for %s", event_id)
        event.status = TwgMeetingEvent.Status.FAILED
        event.error = str(exc)[:2000]
        event.save(update_fields=["status", "error"])
        return f"failed:{exc}"
