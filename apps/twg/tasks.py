"""Process an inbound TWG meeting into per-channel drafts + one review email.

Runs off the webhook (the row is already persisted, so a failure here never
loses the meeting — it can be re-queued). Flow: build a public-safe brief →
create a DRAFT Post with a PlatformPost per connected LinkedIn/X/Instagram
channel → draft each channel's caption in Joseph's voice → best-effort
compliance check → assign the whole bundle to Joseph via the review-email flow.
Nothing auto-publishes.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# The contract sends LinkedIn recap + X thread + IG caption. Draft for connected
# accounts in those families (native or Blotato-backed); skip others (e.g. Ghost).
_CHANNEL_FAMILIES = ("linkedin", "twitter", "instagram")


def _build_brief(payload: dict) -> str:
    """Compose the public-safe master text the drafter rewrites per channel."""

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


@shared_task
def process_twg_meeting(event_id: str) -> str:
    from apps.approvals.assignment_service import assign_for_review
    from apps.composer.generation import draft_caption
    from apps.composer.models import PlatformPost, Post
    from apps.publisher.gate_client import GateError, check_gate
    from apps.social_accounts.models import SocialAccount

    from .models import TwgMeetingEvent

    event = TwgMeetingEvent.objects.filter(id=event_id).first()
    if event is None:
        logger.warning("process_twg_meeting: event %s not found", event_id)
        return "missing"
    # Idempotent: only the RECEIVED state proceeds; a re-fire is a no-op.
    if event.status != TwgMeetingEvent.Status.RECEIVED:
        return f"noop:{event.status}"

    event.status = TwgMeetingEvent.Status.PROCESSING
    event.save(update_fields=["status"])

    try:
        payload = event.payload or {}
        workspace = _resolve_workspace()
        if workspace is None:
            raise RuntimeError("TWG_INGEST_WORKSPACE_ID unset or workspace not found")

        joseph_email = (getattr(settings, "JOSEPH_APPROVER_EMAIL", "") or "").strip()
        if not joseph_email:
            raise RuntimeError("JOSEPH_APPROVER_EMAIL unset — cannot route review email")

        master_text = _build_brief(payload)
        brief = {
            "source": "twg",
            "meeting_id": event.meeting_id,
            "minutes_url": payload.get("minutes_url", ""),
            "guardrails": [
                "Public-safe TWG summary only — never source from raw minutes or transcripts.",
                "Do not imply decisions beyond those explicitly listed.",
                "Name only the institutions provided.",
                "WAIIS Secretariat voice; status-accurate language.",
            ],
        }

        post = Post.objects.create(
            workspace=workspace,
            title=(payload.get("meeting_title", "") or "TWG meeting")[:255],
            caption=master_text,
            ai_brief=brief,
            tags=["twg", event.meeting_id],
        )

        accounts = [
            a
            for a in SocialAccount.objects.filter(
                workspace=workspace,
                connection_status=SocialAccount.ConnectionStatus.CONNECTED,
            )
            if any(fam in a.platform for fam in _CHANNEL_FAMILIES)
        ]

        gate_notes = []
        for account in accounts:
            pp = PlatformPost.objects.create(
                post=post, social_account=account, status=PlatformPost.Status.DRAFT
            )
            caption, _src = draft_caption(
                workspace=workspace,
                title=post.title,
                master_text=master_text,
                platform=account.platform,
                platform_label=account.get_platform_display(),
                char_limit=account.char_limit,
                brief=brief,
                voice="joseph",
            )
            pp.platform_specific_caption = caption
            pp.save(update_fields=["platform_specific_caption"])

            # Advisory pre-review compliance check. The authoritative gate runs
            # at publish; here we only annotate so Joseph sees flags. Fail-safe:
            # if agent-service is down we still route the drafts to review.
            try:
                verdict = check_gate(caption, track="waiis", content_type="social")
                if verdict.get("verdict") not in ("pass", "approved"):
                    gate_notes.append(
                        f"{account.get_platform_display()}: {verdict.get('verdict')} "
                        f"— {verdict.get('findings')}"
                    )
            except GateError as exc:
                logger.warning("TWG gate check unavailable for %s: %s", account, exc)

        if gate_notes:
            post.internal_notes = "Compliance flags:\n" + "\n".join(gate_notes)
            post.save(update_fields=["internal_notes", "updated_at"])

        # One bundled review email to Joseph (no-login token flow).
        assign_for_review(
            post=post,
            assigned_by=None,
            reviewer_email=joseph_email,
            reviewer_name="Joseph Nganga",
        )

        event.post = post
        event.status = TwgMeetingEvent.Status.DRAFTED
        event.processed_at = timezone.now()
        event.save(update_fields=["post", "status", "processed_at"])
        return f"drafted:{post.id}"

    except Exception as exc:  # noqa: BLE001 — persist the failure, never lose the event
        logger.exception("process_twg_meeting failed for %s", event_id)
        event.status = TwgMeetingEvent.Status.FAILED
        event.error = str(exc)[:2000]
        event.save(update_fields=["status", "error"])
        return f"failed:{exc}"
