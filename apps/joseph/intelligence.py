"""JosephIntelligence — the single seam between Joseph's surface and the
intelligence plane.

Today ``brief`` and ``proposals`` compose agent-service reads (via
``apps.joseph.readers``) plus local Django state; ``ask`` is a not-yet-connected
stub. The future external "knows-Joseph-end-to-end" endpoint swaps the impl
behind THIS class only — views and templates never change.

Everything degrades gracefully when the agent-service is down (readers already
return safe defaults), so the surface shows empty states rather than 500s.
"""
from django.utils.text import slugify

from apps.joseph import readers


class JosephIntelligence:
    """Composes readers + local models into the data Joseph's surface renders."""

    # ------------------------------------------------------------------
    # brief(thread_id, tier) — L0 editorial card / L1 / L2 bodies
    # ------------------------------------------------------------------

    def brief(self, thread_id: str, tier: str = "l0") -> dict:
        thread = readers.get_thread(thread_id) or {}
        dossier_id = thread.get("dossier_id")
        dossier = readers.get_dossier(dossier_id) if dossier_id else {}

        tier = (tier or "l0").lower()
        if tier == "l0":
            return self._l0(thread, dossier)
        if tier == "l1":
            return {
                "tier": "l1",
                "has_dossier": bool(dossier),
                "body_md": dossier.get("body_md", ""),
            }
        # l2 → linked wiki page (slug match on entity), tier l2; else body_md.
        entity = dossier.get("entity") or thread.get("org") or ""
        page = readers.get_page(slugify(entity), tier="l2") if entity else {}
        body = (page or {}).get("content") or dossier.get("body_md", "")
        return {
            "tier": "l2",
            "has_dossier": bool(dossier),
            "body_md": body,
            "page": page or {},
        }

    @staticmethod
    def _l0(thread: dict, dossier: dict) -> dict:
        """Map thread + dossier onto the L0 editorial card (no agent-service change).

        WHO       = org + contact (name/role) from thread.state
        WHY NOW   = dossier.summary
        HOOK      = dossier.hooks[thread.track] or the first hook
        RED FLAGS = dossier.red_flags[:3]
        WARM PATH = dossier.meta.warm_path or "cold approach"
        FRESHNESS = {updated_at, sources: len(dossier.sources)}
        """
        state = thread.get("state") or {}
        org = thread.get("org") or dossier.get("entity") or ""
        contact = state.get("contact_name") or ""
        role = state.get("contact_role") or ""
        who = org
        if contact:
            who = f"{org} — {contact}" + (f", {role}" if role else "")

        hooks = dossier.get("hooks") or {}
        track = thread.get("track")
        hook = hooks.get(track) if track else None
        if not hook and hooks:
            hook = next(iter(hooks.values()), "")

        meta = dossier.get("meta") or {}
        sources = dossier.get("sources") or []

        return {
            "thread_id": thread.get("id"),
            "tier": "l0",
            "has_dossier": bool(dossier),
            "who": who,
            "why_now": dossier.get("summary", ""),
            "hook": hook or "",
            "red_flags": (dossier.get("red_flags") or [])[:3],
            "warm_path": meta.get("warm_path") or "cold approach",
            "freshness": {
                "updated_at": dossier.get("updated_at", ""),
                "sources": len(sources),
            },
        }

    # ------------------------------------------------------------------
    # proposals() — merge of three sources into ActionCard dicts
    # ------------------------------------------------------------------

    def proposals(self, *, workspace=None, user=None) -> list:
        """Merge unread agent-service notifications + Joseph's PENDING posts +
        unlinked calendar events into normalized ActionCard dicts, urgent first.
        """
        cards: list[dict] = []

        # 1) agent-service notifications (urgent ones float to the top)
        for n in readers.list_notifications(unread=True):
            cards.append({
                "kind": "notification",
                "title": n.get("kind", "Notification").replace("_", " ").title(),
                "subtitle": n.get("body", ""),
                "urgent": bool(n.get("urgent")),
                "actions": [{"label": "Open", "href": (n.get("action") or {}).get("href", "")}],
                "href": (n.get("action") or {}).get("href", ""),
            })

        # 2) Joseph's PENDING content reviews (local Django Posts)
        for post in self._pending_posts(workspace, user):
            cards.append({
                "kind": "content_review",
                "title": post.title or "Untitled draft",
                "subtitle": "Pending your review",
                "urgent": False,
                "actions": [{"label": "Review", "href": f"/joseph/content/#{post.id}"}],
                "href": f"/joseph/content/#{post.id}",
            })

        # 3) unlinked calendar events surfaced as linkage suggestions
        for ev in self._unlinked_calendar_events(workspace):
            title = ev.get("title", "Calendar event")
            cards.append({
                "kind": "calendar_link",
                "title": title,
                "subtitle": "Link this meeting to a thread?",
                "urgent": False,
                "actions": [{"label": "Link", "href": f"/joseph/?link_event={ev.get('id', '')}"}],
                "href": f"/joseph/?link_event={ev.get('id', '')}",
            })

        # stable sort: urgent first, original order otherwise
        cards.sort(key=lambda c: 0 if c.get("urgent") else 1)
        return cards

    @staticmethod
    def _pending_posts(workspace, user):
        """Posts in PENDING review assigned to (or authored by) Joseph."""
        from django.db.models import Q

        from apps.composer.models import Post

        qs = Post.objects.filter(review_state=Post.ReviewState.PENDING)
        if workspace is not None:
            qs = qs.filter(workspace=workspace)
        if user is not None:
            qs = qs.filter(Q(review_assignee=user) | Q(author=user))
        return list(qs)

    @staticmethod
    def _unlinked_calendar_events(workspace):
        """Unlinked upcoming CalendarEvents (linkage suggestions).

        The CalendarEvent model lands in Task 2; until then (or if the table is
        absent) this degrades to an empty list so the surface never 500s. Tests
        patch this method directly to exercise the merge logic.
        """
        try:
            from apps.joseph.models import CalendarEvent
        except (ImportError, LookupError):
            return []
        try:
            qs = CalendarEvent.objects.filter(linked_thread_id="")
            if workspace is not None:
                qs = qs.filter(workspace=workspace)
            return [
                {"id": str(e.google_event_id), "title": e.title, "start": e.start}
                for e in qs
            ]
        except Exception:
            # table not migrated yet / DB error → safe empty state
            return []

    # ------------------------------------------------------------------
    # ask(question) — not-yet-connected stub (501-style)
    # ------------------------------------------------------------------

    def ask(self, question: str) -> dict:
        return {
            "connected": False,
            "message": (
                "Joseph's end-to-end assistant isn't connected yet. "
                "Brief and pipeline data are live; ask() lights up when the "
                "external intelligence endpoint is wired."
            ),
            "question": question,
        }
