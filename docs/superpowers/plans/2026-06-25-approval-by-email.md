# Approval-by-email Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or executing-plans. TDD per task. Each task = failing test → implement → green → commit. Use `git -C <worktree>` for ALL git ops; never rely on `cd`.

**Goal:** Assign a reviewer → email them a platform-styled preview → they approve/decline with a recorded reason via secure no-login links → publisher gets a "Publish now" email → publish through the unchanged gate. Keep the existing one-click Send.

**Architecture:** New units in `apps/approvals`: models (`ReviewAssignment`, `ActionToken`), `tokens.py`, `platform_cards.py`, `emailer.py`, `assignment_service.py`, `review_views.py` (+ public URLs + templates). Reuses `apps/composer/views.schedule_now` for the gated publish and `integrations/gmail` for sending. Gate (`apps/publisher/engine._dispatch_to_provider`) is untouched.

**Tech Stack:** Django 5.1, pytest (`config.settings.test`), `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest <path> -q -p no:warnings`. Migrations via `uv run python manage.py makemigrations approvals`.

**Reference:** full design in `docs/superpowers/specs/2026-06-25-approval-by-email-design.md`. Read it before Task 1.

---

### Task 1: Models + token utilities

**Files:** `apps/approvals/models.py` (append), new `apps/approvals/tokens.py`, migration, test `apps/approvals/tests/test_review_tokens.py`.

- [ ] **Step 1 — failing test** (`test_review_tokens.py`):
```python
import pytest
from django.utils import timezone
from datetime import timedelta
from apps.composer.models import Post
from apps.approvals.models import ReviewAssignment, ActionToken
from apps.approvals import tokens


@pytest.mark.django_db
def test_mint_and_resolve_review_token(workspace, django_user_model):
    u = django_user_model.objects.create_user(email="m@x.co", password="x", name="M")
    post = Post.objects.create(workspace=workspace, title="P", caption="c")
    a = ReviewAssignment.objects.create(post=post, assigned_by=u,
        reviewer_email="rev@x.co", reviewer_name="Rev")
    t = tokens.mint_token(a, ActionToken.Purpose.REVIEW, ttl_days=7)
    assert t.token and t.expires_at > timezone.now()
    assert tokens.resolve_token(t.token, ActionToken.Purpose.REVIEW) == t


@pytest.mark.django_db
def test_used_and_expired_tokens_rejected(workspace, django_user_model):
    u = django_user_model.objects.create_user(email="m2@x.co", password="x", name="M")
    post = Post.objects.create(workspace=workspace, title="P", caption="c")
    a = ReviewAssignment.objects.create(post=post, assigned_by=u, reviewer_email="r@x.co")
    t = tokens.mint_token(a, ActionToken.Purpose.REVIEW, ttl_days=7)
    tokens.consume(t)
    assert tokens.resolve_token(t.token, ActionToken.Purpose.REVIEW) is None
    t2 = tokens.mint_token(a, ActionToken.Purpose.PUBLISH, ttl_days=7)
    t2.expires_at = timezone.now() - timedelta(seconds=1); t2.save(update_fields=["expires_at"])
    assert tokens.resolve_token(t2.token, ActionToken.Purpose.PUBLISH) is None
```
- [ ] **Step 2 — run, expect ImportError/❌.**
- [ ] **Step 3 — models** (append to `apps/approvals/models.py`):
```python
class ReviewAssignment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"; APPROVED = "approved"; DECLINED = "declined"; EXPIRED = "expired"
    post = models.ForeignKey("composer.Post", on_delete=models.CASCADE, related_name="review_assignments")
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    reviewer_email = models.EmailField()
    reviewer_name = models.CharField(max_length=200, blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    reason = models.TextField(blank=True, default="")
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ActionToken(models.Model):
    class Purpose(models.TextChoices):
        REVIEW = "review"; PUBLISH = "publish"
    assignment = models.ForeignKey(ReviewAssignment, on_delete=models.CASCADE, related_name="tokens")
    purpose = models.CharField(max_length=10, choices=Purpose.choices)
    token = models.CharField(max_length=64, unique=True, db_index=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
```
Ensure `from django.conf import settings` is imported at top of the file.
- [ ] **Step 4 — `apps/approvals/tokens.py`:**
```python
import secrets
from datetime import timedelta
from django.utils import timezone
from .models import ActionToken


def mint_token(assignment, purpose, ttl_days=7):
    return ActionToken.objects.create(
        assignment=assignment, purpose=purpose, token=secrets.token_urlsafe(32),
        expires_at=timezone.now() + timedelta(days=ttl_days))


def resolve_token(raw, purpose):
    t = ActionToken.objects.filter(token=raw, purpose=purpose, used_at__isnull=True).select_related(
        "assignment", "assignment__post").first()
    if t is None or t.expires_at <= timezone.now():
        return None
    return t


def consume(token):
    token.used_at = timezone.now()
    token.save(update_fields=["used_at"])
```
- [ ] **Step 5 — `uv run python manage.py makemigrations approvals`**, then run the test → green.
- [ ] **Step 6 — commit** `feat(approvals): ReviewAssignment + ActionToken + token utils`.

---

### Task 2: Platform-styled cards

**Files:** new `apps/approvals/platform_cards.py`, test `apps/approvals/tests/test_platform_cards.py`.

- [ ] **Step 1 — failing test:** create a Post with two PlatformPosts (linkedin, twitter) via the `social_account` fixture pattern from `apps/publisher/tests`; assert `render_cards(post)` returns HTML containing one card per platform, each with a platform label (e.g. "LinkedIn", "X") and the caption text. (If `social_account` fixture isn't visible, copy it into `apps/approvals/tests/conftest.py`.)
- [ ] **Step 2 — run, expect ❌.**
- [ ] **Step 3 — implement** `render_cards(post) -> str`: iterate `post.platform_posts.select_related("social_account")`; for each, pick a per-platform style block (linkedin/x/instagram/facebook/threads/default → label + accent color) and emit an email-safe inline-styled `<div>` card with: platform badge, account handle (`pp.social_account` identity), caption (`post.caption`), and first media thumbnail if present. Concatenate. Keep all CSS inline (email clients strip `<style>`). Pure function, no DB writes.
- [ ] **Step 4 — green. Step 5 — commit** `feat(approvals): platform-styled email cards`.

---

### Task 3: Email transport seam + templates

**Files:** new `apps/approvals/emailer.py`, templates `templates/approvals/email/review.html` + `publish.html` + `declined.html`, test `apps/approvals/tests/test_emailer.py`.

- [ ] **Step 1 — failing test:** (a) with no Gmail integration, `send_email("to@x.co","S","<b>h</b>")` returns True and lands one message in `django.core.mail.outbox` (SMTP/locmem path). (b) monkeypatch the Gmail builder to a stub recording the send; with an integration present, `send_email` uses Gmail and returns True. (c) when both transports raise, `send_email` returns False (never raises).
- [ ] **Step 2 — run, expect ❌.**
- [ ] **Step 3 — implement `emailer.py`:**
```python
import logging
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
logger = logging.getLogger(__name__)


def _gmail_integration():
    """Return an admin GoogleIntegration with gmail.send scope, or None."""
    try:
        from apps.joseph.models import GoogleIntegration
        return GoogleIntegration.objects.filter(
            scopes__contains="gmail.send").first()
    except Exception:
        return None


def send_email(to, subject, html):
    """Send HTML email; prefer Gmail-OAuth, fall back to SMTP/console. Never raises."""
    integration = _gmail_integration()
    if integration is not None:
        try:
            from integrations.gmail import build_gmail_service, send_message
            service = build_gmail_service(integration)
            send_message(service, to=to, subject=subject, body_html=html,
                         sender=settings.DEFAULT_FROM_EMAIL or None)
            return True
        except Exception:
            logger.warning("Gmail send failed; falling back to SMTP", exc_info=True)
    try:
        msg = EmailMultiAlternatives(subject, html, settings.DEFAULT_FROM_EMAIL, [to])
        msg.attach_alternative(html, "text/html")
        msg.send()
        return True
    except Exception:
        logger.warning("SMTP send failed for %s", to, exc_info=True)
        return False
```
(Confirm `GoogleIntegration.scopes` shape against `apps/joseph/models.py`; if scopes is a JSON list, use the correct lookup — adjust `_gmail_integration` to match, e.g. iterate in Python if `__contains` isn't valid for the field type.)
- [ ] **Step 4 — templates:** `review.html` (intro + `{{ cards|safe }}` + Approve button → `review_url` + Decline note), `publish.html` (cards + "Publish now" button → `publish_url`), `declined.html` (reason + which post). Email-safe inline styles.
- [ ] **Step 5 — green. Step 6 — commit** `feat(approvals): email transport seam + review/publish/declined templates`.

---

### Task 4: assign_for_review service

**Files:** new `apps/approvals/assignment_service.py`, test `apps/approvals/tests/test_assignment_service.py`.

- [ ] **Step 1 — failing test:** `assign_for_review(post, assigned_by, "rev@x.co", "Rev")` → creates a `ReviewAssignment` (status PENDING), mints a REVIEW `ActionToken`, sets `post.review_state="pending"`, and sends exactly one email (assert `len(mail.outbox)==1`, recipient `rev@x.co`). Patch `emailer.send_email` to capture args and assert the review URL with the token is in the HTML.
- [ ] **Step 2 — run ❌. Step 3 — implement:**
```python
from django.urls import reverse
from apps.composer.models import Post
from apps.settings_manager.helpers import get_setting
from . import tokens, emailer
from .platform_cards import render_cards
from .models import ReviewAssignment, ActionToken
from django.template.loader import render_to_string


def assign_for_review(post, assigned_by, reviewer_email, reviewer_name=""):
    a = ReviewAssignment.objects.create(post=post, assigned_by=assigned_by,
        reviewer_email=reviewer_email, reviewer_name=reviewer_name or "")
    post.review_state = Post.ReviewState.PENDING
    if assigned_by is not None:
        post.review_assignee = assigned_by  # keep existing FK in sync where applicable
    post.save(update_fields=["review_state", "review_assignee", "updated_at"])
    ttl = get_setting(post.workspace_id, "review.token_ttl_days") or 7
    tok = tokens.mint_token(a, ActionToken.Purpose.REVIEW, ttl_days=int(ttl))
    review_url = _abs(reverse("approvals:review", args=[tok.token]))
    html = render_to_string("approvals/email/review.html",
        {"post": post, "cards": render_cards(post), "review_url": review_url,
         "reviewer_name": reviewer_name})
    emailer.send_email(reviewer_email, f"Review requested: {post.title or post.caption_snippet}", html)
    return a
```
Add an `_abs(path)` helper that builds an absolute URL from `settings` (use `settings.PUBLIC_BASE_URL` if present else a sensible default; confirm the project's existing absolute-URL convention and reuse it). If `post.review_assignee` requires a User and `assigned_by` may be None, guard the `update_fields` accordingly.
- [ ] **Step 4 — green. Step 5 — commit** `feat(approvals): assign_for_review service`.

---

### Task 5: Public review page (approve/decline)

**Files:** new `apps/approvals/review_views.py`, `apps/approvals/urls.py` (add routes under names `approvals:review`), templates `templates/approvals/public/review.html` + `invalid.html`, test `apps/approvals/tests/test_review_page.py`.

- [ ] **Step 1 — failing tests:** (a) `GET /review/<token>/` returns 200 and shows the cards + Approve/Decline; invalid token → 200 "link no longer valid" page (not 500). (b) `POST` approve → `ApprovalAction(action=APPROVED)` exists, assignment.status=APPROVED, `post.review_state="approved"`, a PUBLISH token is minted, publisher emailed (outbox+1), token consumed (replay does nothing). (c) `POST` decline with empty reason → re-renders with error, no state change; with reason → assignment.status=DECLINED + reason saved, `post.review_state="changes_requested"`, publisher emailed.
- [ ] **Step 2 — run ❌. Step 3 — implement** `review_views.py`:
  - `review(request, token)`: `resolve_token(token, REVIEW)`; None → render `public/invalid.html`. GET → render `public/review.html` with cards. POST: read `decision` + `reason`. `approve` → set assignment APPROVED + `ApprovalAction(post=, user=assignment.assigned_by, action=APPROVED, comment=reason)`, `post.review_state=APPROVED`, `consume(token)`, mint PUBLISH token, email publisher (`assignment.assigned_by.email` or `get_setting(...,"review.copy_email")`) via `publish.html` (cards + publish_url). `decline` with empty reason → re-render with error (no consume); with reason → assignment DECLINED + reason, `ApprovalAction(CHANGES_REQUESTED, comment=reason)`, `post.review_state=CHANGES_REQUESTED`, consume, email publisher `declined.html`. Wrap in `transaction.atomic`.
  - Routes: `path("review/<str:token>/", review_views.review, name="review")` and the publish route from Task 6. These are PUBLIC (no `login_required`); add `@csrf_protect` and ensure they're reachable without auth (check project URL/middleware; the form posts with CSRF token rendered in the page).
- [ ] **Step 4 — green. Step 5 — commit** `feat(approvals): public review page approve/decline with reason`.

---

### Task 6: Publish-by-token (gated)

**Files:** `apps/approvals/review_views.py` (add `publish` view), `urls.py` (route `approvals:review_publish`), template `templates/approvals/public/publish.html`, test `apps/approvals/tests/test_review_publish.py`.

- [ ] **Step 1 — failing tests:** (a) `GET /review/publish/<token>/` (valid PUBLISH token) → 200 confirm page with cards + Publish button; invalid → "link no longer valid". (b) `POST` → consumes token, calls `schedule_now(post)` (assert `post.scheduled_at` set), shows success. (c) **gate-authoritative:** create a PlatformPost(status="pending_review", no gate_id, gate_bypassed False) on the post; after publish-token POST, `pp.status=="scheduled"`; then `PublishEngine.__new__(PublishEngine)._dispatch_to_provider(pp)` raises `GateBlockError` and `pp.status != "published"` (mirror `apps/publisher/tests/test_joseph_gate.py`). (d) replay: a second POST with the consumed token → "link no longer valid", no double-schedule.
- [ ] **Step 2 — run ❌. Step 3 — implement** `publish(request, token)`: `resolve_token(token, PUBLISH)`; None → invalid page. GET → confirm page (cards). POST → `consume(token)`, `from apps.composer.views import schedule_now; schedule_now(assignment.post)`, render success. Wrap in `transaction.atomic`.
- [ ] **Step 4 — green (incl. the gate-authoritative assertion actually executing). Step 5 — commit** `feat(approvals): tokenized publish-by-email (gated)`.

---

### Task 7: Entry UI + setting

**Files:** `apps/settings_manager/defaults.py` (add `review.token_ttl_days`), an "Assign for review" control + handler view (in `apps/approvals/views.py` or composer studio — follow the existing assign/approve UI pattern), URL, test `apps/approvals/tests/test_assign_entry.py`.

- [ ] **Step 1 — failing test:** POST to the assign endpoint with `{reviewer_email, reviewer_name}` for a post (as the publisher) → 302/200, a `ReviewAssignment` created (PENDING) + one email sent; permission: only a workspace member with `approve_posts` (or post author) can assign. Add `review.token_ttl_days=7` default test (get_setting returns 7).
- [ ] **Step 2 — run ❌. Step 3 — implement:** add `"review.token_ttl_days": 7` to `APP_DEFAULTS`; add an `assign_for_review` view (login_required, permission-checked) that calls `assignment_service.assign_for_review`; add a small "Assign for review" form (email + name) to the post review surface (e.g. `templates/console/approvals.html` next to the Send button, or the studio card) posting to it.
- [ ] **Step 4 — green. Step 5 — commit** `feat(approvals): assign-for-review entry + token_ttl setting`.

---

### Task 8: End-to-end + regression guard

**Files:** test `apps/approvals/tests/test_approval_flow_e2e.py`.

- [ ] **Step 1 — write e2e test:** assign → GET review page → POST approve → assert publisher got publish email + PUBLISH token → GET publish page → POST publish → `schedule_now` ran + gate still authoritative. Plus assert the existing one-click Send test file still passes (run it).
- [ ] **Step 2 — run the full `apps/approvals` + `apps/composer/tests/test_schedule_now.py` suite → all green. Step 3 — commit** `test(approvals): approval-by-email end-to-end + regression`.

---

## Self-review
- Spec coverage: assign(T4/T7) → email w/ platform preview (T2/T3) → approve/decline w/ recorded reason (T5) → publish email (T5) → gated publish (T6); tokens/security (T1); one-click Send kept (T8 regression). ✓
- No placeholders in code blocks; the few "confirm against existing code" notes (absolute-URL helper, `GoogleIntegration.scopes` lookup, `social_account` fixture) are explicit verification points, not silent gaps.
- Type consistency: `ReviewAssignment`/`ActionToken`/`Purpose`/`Status`, `mint_token/resolve_token/consume`, `render_cards`, `send_email`, `assign_for_review`, `schedule_now` consistent across tasks.
- Gate never modified; publish always via `schedule_now`→`_dispatch_to_provider`.

## Notes
- Real email in prod needs a `gmail.send` token (go-live input); until then `send_email` falls back (non-fatal) — the flow + state changes still work and are testable.
- Absolute URLs for tokenized links must use the prod base URL; confirm/define the project's base-URL setting in Task 4.
