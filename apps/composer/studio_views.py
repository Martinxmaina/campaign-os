"""Content Studio — the unified content board (backend query layer, Task 3).

The Content Studio collapses the four fragmented draft surfaces (`/console/intake`
plan rows, `/console/drafts` agent-service items, `/composer/drafts` Django Posts,
`/console/approvals` review queue) into ONE segmented board. This module owns the
*query/context* behind it; the markup is Task 4.

`content_studio` lists, for the active workspace, every relevant Post unified
across states — draft, pending_review, approved (not yet published), scheduled,
and recently published — as one list, each card stamped with a ``studio_state``
label (its derived post-level status). It supports the filter set
``?track=&pillar=&house=&campaign=&state=&q=`` (each independently and combined)
and returns per-segment counts (by track and by pillar) for the chips.

Invariants honoured here:
- **Cross-house wall:** posts are read ONLY through ``Post.objects.for_workspace``
  for the active workspace. The ``house`` chip is informational within a single
  workspace; it can never widen the query past the active house.
- Pure read. No gate, no publishing, no state mutation.
- An empty/absent workspace, or an unrecognised filter value, renders an empty
  board — never a 500.
"""
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone

from apps.composer.models import Post
from apps.composer.status import derive_post_status

# Published posts older than this fall off the board (it is a working surface,
# not an archive). Recently-published stays visible so the team sees what just
# shipped.
_PUBLISHED_WINDOW = timedelta(days=14)


@login_required
def content_studio(request):
    """Unified Content Studio board for the active workspace.

    Returns a single ``posts`` list spanning draft → published(recent), each post
    annotated with ``studio_state`` (its derived status). Filters narrow the set;
    ``counts_by_track`` / ``counts_by_pillar`` reflect the *filtered* set so the
    chip counts always match what is on screen.
    """
    ws = getattr(request, "workspace", None)

    track = (request.GET.get("track") or "").strip()
    pillar = (request.GET.get("pillar") or "").strip()
    campaign = (request.GET.get("campaign") or "").strip()
    state = (request.GET.get("state") or "").strip()
    house = (request.GET.get("house") or "").strip()
    q = (request.GET.get("q") or "").strip()

    posts: list[Post] = []
    if ws is not None:
        # Cross-house wall: only ever the active workspace's posts. The ``house``
        # chip is informational here — it can never widen past ``ws``.
        qs = Post.objects.for_workspace(ws.id)

        # DB-level segmentation filters (each independent; combine with AND).
        if track:
            qs = qs.filter(track=track)
        if pillar:
            qs = qs.filter(pillar=pillar)
        if campaign:
            qs = qs.filter(campaign__iexact=campaign)
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(caption__icontains=q))

        qs = qs.prefetch_related("platform_posts").order_by("-updated_at")

        cutoff = timezone.now() - _PUBLISHED_WINDOW
        for post in qs:
            derived = derive_post_status([pp.status for pp in post.platform_posts.all()])
            # The board is a working surface: keep everything except stale
            # published items (anything published before the recency window).
            if derived == "published":
                pub_at = post.published_at
                if pub_at is not None and pub_at < cutoff:
                    continue
            # State filter operates on the derived post-level status.
            if state and derived != state:
                continue
            post.studio_state = derived
            posts.append(post)

    # Per-segment counts over the *visible* (filtered) set so chip counts match.
    counts_by_track: dict[str, int] = {}
    counts_by_pillar: dict[str, int] = {}
    for post in posts:
        if post.track:
            counts_by_track[post.track] = counts_by_track.get(post.track, 0) + 1
        if post.pillar:
            counts_by_pillar[post.pillar] = counts_by_pillar.get(post.pillar, 0) + 1

    context = {
        "posts": posts,
        "counts_by_track": counts_by_track,
        "counts_by_pillar": counts_by_pillar,
        "total": len(posts),
        # Echo the active filters so the template can mark active chips.
        "active": {
            "track": track,
            "pillar": pillar,
            "campaign": campaign,
            "state": state,
            "house": house,
            "q": q,
        },
        "down": False,
    }
    return render(request, "console/content_studio.html", context)
