"""Unified content-pipeline progress.

One number for "how many posts, and how far through the pipeline" across **all**
content the team has created and curated:

* **created**  — composer ``Post`` rows authored directly (HERALD drafts +
  hand-written), i.e. Posts with no linked intake item.
* **curated**  — every ``ContentIntake`` row (the planning register). An intake
  item that has already become a draft carries that ``Post`` via the
  ``post`` OneToOne, so it is counted **here, once** — never again as a created
  Post (which is why the created query excludes ``intake_source``).

Both sources are mapped onto a single funnel and summarised into per-stage
counts plus a weighted "% through the pipeline" figure. Read straight from the
canonical Django tables, so it survives an agent-service outage.
"""
from __future__ import annotations

from apps.composer.models import Post
from apps.content_intake.models import ContentIntake

# Funnel stages in flow order. The weight is each stage's fraction of "done",
# used for the progress bar (Curated contributes nothing; Published is complete).
STAGES: list[tuple[str, str]] = [
    ("curated", "Curated"),
    ("drafting", "Drafting"),
    ("review", "In review"),
    ("approved", "Approved"),
    ("scheduled", "Scheduled"),
    ("published", "Published"),
]
_STAGE_WEIGHT = {
    "curated": 0.0,
    "drafting": 0.2,
    "review": 0.4,
    "approved": 0.6,
    "scheduled": 0.8,
    "published": 1.0,
}
# A light-stone → deep-orange ramp: colour intensity = progress toward "done",
# staying inside the BrightBean warm/brand palette.
_STAGE_COLOR = {
    "curated": "#e7e5e4",
    "drafting": "#fed7aa",
    "review": "#fdba74",
    "approved": "#fb923c",
    "scheduled": "#f97316",
    "published": "#c2410c",
}
_STAGE_ORDER = {key: i for i, (key, _) in enumerate(STAGES)}

# ContentIntake.Status → funnel stage. Statuses absent here (skipped, archived)
# are dead/terminal and excluded from the active pipeline total. Blocked/held are
# stuck pre-draft, so they sit in "Curated".
_INTAKE_STAGE = {
    ContentIntake.Status.IDEA: "curated",
    ContentIntake.Status.ACCEPTED: "curated",
    ContentIntake.Status.REVIEW_QUEUE: "curated",
    ContentIntake.Status.BLOCKED: "curated",
    ContentIntake.Status.HELD: "curated",
    ContentIntake.Status.DRAFTING: "drafting",
    ContentIntake.Status.IN_REVIEW: "review",
    ContentIntake.Status.APPROVED: "approved",
    ContentIntake.Status.SCHEDULED: "scheduled",
    ContentIntake.Status.PUBLISHED: "published",
}


def _post_stage(published_at, scheduled_at, review_state) -> str:
    """Map a composer Post onto the funnel from its publish/schedule/review state.

    Uses the DB-stored scalar fields rather than the derived ``Post.status``
    property (which fires a per-row query over ``platform_posts``).
    """
    if published_at:
        return "published"
    if scheduled_at:
        return "scheduled"
    if review_state == Post.ReviewState.APPROVED:
        return "approved"
    if review_state == Post.ReviewState.PENDING:
        return "review"
    # none / changes_requested / draft → still being drafted
    return "drafting"


def content_pipeline_progress(workspace) -> dict:
    """Funnel counts + weighted progress over created + curated content.

    Returns ``{stages: [{key,label,count,pct}], total, created, curated,
    published, percent}``. Safe for ``workspace=None`` (all zero).
    """
    counts = {key: 0 for key, _ in STAGES}
    curated = 0
    created = 0

    if workspace is not None:
        # Curated register — every intake row (each may already carry a linked
        # Post via the ``post`` OneToOne; the join columns are NULL when none).
        intake_rows = ContentIntake.objects.filter(workspace=workspace).values_list(
            "status",
            "post__published_at",
            "post__scheduled_at",
            "post__review_state",
        )
        for status, p_pub, p_sched, p_review in intake_rows:
            stage = _INTAKE_STAGE.get(status)
            if stage is None:
                continue  # skipped / archived — not in the active funnel
            if p_review is not None:  # a linked Post exists
                post_stage = _post_stage(p_pub, p_sched, p_review)
                if _STAGE_ORDER[post_stage] > _STAGE_ORDER[stage]:
                    stage = post_stage  # the draft has moved further than the row
            counts[stage] += 1
            curated += 1

        # Created standalone — Posts with no intake item behind them. Rejected
        # drafts are dropped from the active funnel.
        post_rows = (
            Post.objects.filter(workspace=workspace, intake_source__isnull=True)
            .exclude(review_state=Post.ReviewState.REJECTED)
            .values_list("published_at", "scheduled_at", "review_state")
        )
        for p_pub, p_sched, p_review in post_rows:
            counts[_post_stage(p_pub, p_sched, p_review)] += 1
            created += 1

    total = curated + created
    weighted = sum(counts[key] * _STAGE_WEIGHT[key] for key, _ in STAGES)
    percent = round(weighted / total * 100) if total else 0

    stages = [
        {
            "key": key,
            "label": label,
            "count": counts[key],
            "pct": round(counts[key] / total * 100) if total else 0,
            "color": _STAGE_COLOR[key],
        }
        for key, label in STAGES
    ]
    return {
        "stages": stages,
        "total": total,
        "created": created,
        "curated": curated,
        "published": counts["published"],
        "percent": percent,
    }


def content_pipeline_board(workspace) -> list[dict]:
    """The created + curated content as a stage-bucketed board (the team content
    pipeline). Returns one column per funnel stage, each with its cards. Each card
    links to where it is acted on: a Post → the composer; a curated-only intake
    row → the intake board. De-duped exactly like ``content_pipeline_progress``.
    """
    from django.urls import reverse

    cols = {key: [] for key, _ in STAGES}
    if workspace is not None:
        # Curated rows (may carry a linked Post → take its more-advanced stage).
        intake_rows = ContentIntake.objects.filter(workspace=workspace).values_list(
            "id", "status", "angle", "pillar_theme",
            "post_id", "post__published_at", "post__scheduled_at",
            "post__review_state", "post__title",
        )
        for iid, status, angle, pillar, post_id, p_pub, p_sched, p_review, p_title in intake_rows:
            stage = _INTAKE_STAGE.get(status)
            if stage is None:
                continue
            if p_review is not None:
                post_stage = _post_stage(p_pub, p_sched, p_review)
                if _STAGE_ORDER[post_stage] > _STAGE_ORDER[stage]:
                    stage = post_stage
            if post_id:
                url = reverse("composer:compose_edit",
                              kwargs={"workspace_id": workspace.id, "post_id": post_id})
            else:
                url = reverse("console:intake-board")
            cols[stage].append({
                "title": (p_title or angle or pillar or "Untitled").strip()[:90],
                "subtitle": pillar or "",
                "origin": "curated",
                "url": url,
            })

        # Created standalone Posts (no intake behind them).
        post_rows = (
            Post.objects.filter(workspace=workspace, intake_source__isnull=True)
            .exclude(review_state=Post.ReviewState.REJECTED)
            .values_list("id", "title", "caption", "pillar",
                         "published_at", "scheduled_at", "review_state")
        )
        for pid, title, caption, pillar, p_pub, p_sched, p_review in post_rows:
            stage = _post_stage(p_pub, p_sched, p_review)
            cols[stage].append({
                "title": (title or caption or "Untitled").strip()[:90],
                "subtitle": pillar or "",
                "origin": "created",
                "url": reverse("composer:compose_edit",
                               kwargs={"workspace_id": workspace.id, "post_id": pid}),
            })

    return [
        {"key": key, "label": label, "color": _STAGE_COLOR[key], "cards": cols[key]}
        for key, label in STAGES
    ]
