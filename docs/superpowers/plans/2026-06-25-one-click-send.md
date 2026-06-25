# One-click "Send" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a single **Send** button to the AI Approvals console so the assigned reviewer can approve a post, email a copy to a configured inbox, and publish it through the existing compliance gate — in one click.

**Architecture:** Approach A (compound action reusing existing services). The Send action is a new `decision == "send"` branch on the existing `apps/approvals/console_views.py::approval_decide` view, backed by a thin `send_for_publish(post, user)` service that (1) approves at the Post level exactly as the console's `approve` branch does, (2) emails a rendered copy to `review.copy_email`, and (3) calls a new shared `schedule_now(post)` helper to schedule publishing. The gate at `apps/publisher/engine._dispatch_to_provider` is untouched and still authoritative.

**Tech Stack:** Django 5.1, pytest (`config.settings.test`), HTMX/Alpine templates, Celery publish engine, `apps/settings_manager` cascade, Django email (locmem in tests).

**Run tests:** `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest <path> -q -p no:warnings`

---

## File Structure

- **Create** `apps/approvals/send_actions.py` — `send_for_publish(post, user)` + `email_post_copy(post, to_email, reviewer)`. The whole new behaviour lives here.
- **Create** `templates/notifications/email/post_copy.txt` and `.html` — the emailed copy.
- **Create** `apps/approvals/tests/test_send_for_publish.py` — all new tests.
- **Modify** `apps/settings_manager/defaults.py` — add `review.copy_email` default.
- **Modify** `apps/composer/views.py` — extract `schedule_now(post)` from `publish_post` and call it (DRY; `publish_post` keeps identical behaviour).
- **Modify** `apps/approvals/console_views.py` — add the `decision == "send"` branch to `approval_decide`.
- **Modify** `templates/console/approvals.html` — add the **Send** form/button.

---

### Task 1: `review.copy_email` default setting

**Files:**
- Modify: `apps/settings_manager/defaults.py`
- Test: `apps/approvals/tests/test_send_for_publish.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/approvals/tests/test_send_for_publish.py
import pytest
from apps.settings_manager.helpers import get_setting


@pytest.mark.django_db
def test_review_copy_email_default(workspace):
    # Falls back to the app default when no workspace/org override exists.
    assert get_setting(workspace.id, "review.copy_email") == "martin.maina@africacen.org"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/approvals/tests/test_send_for_publish.py::test_review_copy_email_default -q -p no:warnings`
Expected: FAIL — `get_setting` returns `None` (key not in `APP_DEFAULTS`).

- [ ] **Step 3: Add the default**

In `apps/settings_manager/defaults.py`, inside `APP_DEFAULTS`, add (next to the other workspace-level keys, e.g. after the `approval.*` block):

```python
    # Review → one-click Send: where the emailed copy goes (override per
    # workspace/org via the settings cascade).
    "review.copy_email": "martin.maina@africacen.org",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/approvals/tests/test_send_for_publish.py::test_review_copy_email_default -q -p no:warnings`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/settings_manager/defaults.py apps/approvals/tests/test_send_for_publish.py
git commit -m "feat(approvals): review.copy_email default for one-click Send"
```

---

### Task 2: Extract `schedule_now(post)` shared publish helper

`publish_post` (composer) already contains the exact schedule-effective-now logic we need. Extract it to a reusable function and have `publish_post` call it, so the Send action and the existing one-tap Publish share one implementation.

**Files:**
- Modify: `apps/composer/views.py:907-927` (the scheduling block inside `publish_post`) and add `schedule_now` near `_transition_post_children` (`apps/composer/views.py:505`)
- Test: `apps/composer/tests/test_schedule_now.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/composer/tests/test_schedule_now.py
import pytest
from apps.composer.models import Post
from apps.composer.views import schedule_now


@pytest.mark.django_db
def test_schedule_now_sets_effective_now(workspace):
    post = Post.objects.create(workspace=workspace, title="P", caption="c",
        review_state="approved")
    assert post.scheduled_at is None
    schedule_now(post)
    post.refresh_from_db()
    assert post.scheduled_at is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/composer/tests/test_schedule_now.py -q -p no:warnings`
Expected: FAIL — `ImportError: cannot import name 'schedule_now'`.

- [ ] **Step 3: Add `schedule_now` and call it from `publish_post`**

In `apps/composer/views.py`, add this function (place it just below `_transition_post_children`, ~line 505):

```python
def schedule_now(post):
    """Schedule *post* to publish effective-now and hand it to the Celery
    publish chain. Sets ``scheduled_at`` on the post and its publishable
    children, transitions those children to ``scheduled``, and propagates the
    time. Idempotent: children already scheduled / publishing / published are
    left untouched. The compliance gate still runs downstream at
    ``apps/publisher/engine._dispatch_to_provider`` — this only schedules.
    """
    now_dt = timezone.now()
    post.scheduled_at = now_dt
    post.save(update_fields=["scheduled_at", "updated_at"])
    publishable = post.platform_posts.exclude(
        status__in=[
            PlatformPost.Status.SCHEDULED,
            PlatformPost.Status.PUBLISHING,
            PlatformPost.Status.PUBLISHED,
        ]
    )
    only_ids = [pp.id for pp in publishable]
    _transition_post_children(post, "scheduled", only=only_ids)
    post.platform_posts.filter(status=PlatformPost.Status.SCHEDULED).update(scheduled_at=now_dt)
```

Then in `publish_post` replace the inline block (`apps/composer/views.py:907-927`, from `now_dt = timezone.now()` through the `.update(scheduled_at=now_dt)` line) with a single call:

```python
    schedule_now(post)
```

- [ ] **Step 4: Run the new test AND the existing publish tests**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/composer/tests/test_schedule_now.py apps/composer/tests/ -k "publish" -q -p no:warnings`
Expected: PASS (new test passes; existing publish_post tests still green — behaviour is identical).

- [ ] **Step 5: Commit**

```bash
git add apps/composer/views.py apps/composer/tests/test_schedule_now.py
git commit -m "refactor(composer): extract schedule_now() shared publish helper"
```

---

### Task 3: Post-copy email

**Files:**
- Create: `templates/notifications/email/post_copy.txt`, `templates/notifications/email/post_copy.html`
- Create: `apps/approvals/send_actions.py`
- Test: `apps/approvals/tests/test_send_for_publish.py`

- [ ] **Step 1: Write the failing test**

```python
# append to apps/approvals/tests/test_send_for_publish.py
from django.core import mail
from apps.composer.models import Post


@pytest.mark.django_db
def test_email_post_copy_sends_one_mail(workspace, reviewer):
    from apps.approvals.send_actions import email_post_copy
    post = Post.objects.create(workspace=workspace, title="Solar story",
        caption="Solar is booming across East Africa.", review_state="pending",
        review_assignee=reviewer)
    sent = email_post_copy(post, "ops@example.com", reviewer)
    assert sent is True
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["ops@example.com"]
    assert "Solar is booming" in mail.outbox[0].body


@pytest.mark.django_db
def test_email_post_copy_no_address_is_noop(workspace, reviewer):
    from apps.approvals.send_actions import email_post_copy
    post = Post.objects.create(workspace=workspace, title="P", caption="c",
        review_state="pending", review_assignee=reviewer)
    assert email_post_copy(post, "", reviewer) is False
    assert len(mail.outbox) == 0
```

This test uses the `reviewer` fixture pattern from `apps/approvals/tests/test_ai_approvals_queue.py` (org_owner + WorkspaceMembership owner + force_login). Copy that `reviewer` fixture to the top of this test file:

```python
@pytest.fixture
def reviewer(client, org_owner, workspace):
    from apps.members.models import WorkspaceMembership
    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    org_owner.last_workspace_id = workspace.id
    org_owner.save(update_fields=["last_workspace_id"])
    client.force_login(org_owner)
    return org_owner
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/approvals/tests/test_send_for_publish.py -k email_post_copy -q -p no:warnings`
Expected: FAIL — `ModuleNotFoundError: apps.approvals.send_actions`.

- [ ] **Step 3: Create the email templates**

`templates/notifications/email/post_copy.txt`:

```
A post was approved and sent to publish.

Title: {{ post.title|default:"(untitled)" }}
Sent by: {{ reviewer.display_name|default:reviewer.email }}
Platforms: {% for p in platforms %}{{ p }}{% if not forloop.last %}, {% endif %}{% empty %}(none){% endfor %}

--- Caption ---
{{ post.caption }}
```

`templates/notifications/email/post_copy.html`:

```html
<div style="font-family:Georgia,serif;color:#1c1917;max-width:640px">
  <p style="color:#78716c;font-size:13px;margin:0 0 12px">A post was approved and sent to publish.</p>
  <h2 style="font-size:18px;margin:0 0 4px">{{ post.title|default:"(untitled)" }}</h2>
  <p style="color:#78716c;font-size:13px;margin:0 0 2px">Sent by {{ reviewer.display_name|default:reviewer.email }}</p>
  <p style="color:#78716c;font-size:13px;margin:0 0 16px">
    Platforms: {% for p in platforms %}{{ p }}{% if not forloop.last %}, {% endif %}{% empty %}(none){% endfor %}
  </p>
  <div style="white-space:pre-wrap;border-top:1px solid #e7e5e4;padding-top:12px;font-size:15px;line-height:1.6">{{ post.caption }}</div>
</div>
```

- [ ] **Step 4: Create `send_actions.py` with `email_post_copy`**

```python
# apps/approvals/send_actions.py
"""One-click Send: approve + email a copy + publish (Approach A)."""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def email_post_copy(post, to_email, reviewer):
    """Email a rendered copy of *post* to *to_email*. Returns False (no-op) when
    no address is configured; returns True after a successful send."""
    if not to_email:
        return False
    platforms = [
        pp.social_account.platform
        for pp in post.platform_posts.select_related("social_account")
    ]
    ctx = {"post": post, "reviewer": reviewer, "platforms": platforms}
    subject = f"[Sent] {post.title or post.caption_snippet}"
    text_body = render_to_string("notifications/email/post_copy.txt", ctx)
    html_body = render_to_string("notifications/email/post_copy.html", ctx)
    msg = EmailMultiAlternatives(subject, text_body, settings.DEFAULT_FROM_EMAIL, [to_email])
    msg.attach_alternative(html_body, "text/html")
    msg.send()
    return True
```

- [ ] **Step 5: Run test to verify it passes**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/approvals/tests/test_send_for_publish.py -k email_post_copy -q -p no:warnings`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/approvals/send_actions.py templates/notifications/email/post_copy.txt templates/notifications/email/post_copy.html apps/approvals/tests/test_send_for_publish.py
git commit -m "feat(approvals): post-copy email for one-click Send"
```

---

### Task 4: `send_for_publish(post, user)` service

**Files:**
- Modify: `apps/approvals/send_actions.py`
- Test: `apps/approvals/tests/test_send_for_publish.py`

- [ ] **Step 1: Write the failing test**

```python
# append to apps/approvals/tests/test_send_for_publish.py
from apps.approvals.models import ApprovalAction


@pytest.mark.django_db
def test_send_for_publish_approves_emails_and_schedules(workspace, reviewer):
    from apps.approvals.send_actions import send_for_publish
    post = Post.objects.create(workspace=workspace, title="P",
        caption="Ship it across the corridor.", review_state="pending",
        review_assignee=reviewer)

    send_for_publish(post, reviewer)

    post.refresh_from_db()
    assert post.review_state == "approved"                      # approved
    assert post.scheduled_at is not None                        # scheduled to publish
    assert ApprovalAction.objects.filter(post=post, action="approved").exists()
    assert len(mail.outbox) == 1                                # one copy email
    assert mail.outbox[0].to == ["martin.maina@africacen.org"]  # to the default address


@pytest.mark.django_db
def test_send_for_publish_email_failure_is_nonfatal(workspace, reviewer, monkeypatch):
    """A broken mail backend must not stop approve + publish."""
    import apps.approvals.send_actions as sa
    post = Post.objects.create(workspace=workspace, title="P", caption="c",
        review_state="pending", review_assignee=reviewer)

    def boom(*a, **k):
        raise RuntimeError("smtp down")
    monkeypatch.setattr(sa, "email_post_copy", boom)

    send_for_publish(post, reviewer)  # must not raise

    post.refresh_from_db()
    assert post.review_state == "approved"
    assert post.scheduled_at is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/approvals/tests/test_send_for_publish.py -k send_for_publish -q -p no:warnings`
Expected: FAIL — `ImportError: cannot import name 'send_for_publish'`.

- [ ] **Step 3: Add `send_for_publish`**

Append to `apps/approvals/send_actions.py` (and add the imports shown at top):

```python
from apps.composer.models import Post
from apps.composer.views import schedule_now
from apps.settings_manager.helpers import get_setting

from .models import ApprovalAction


def send_for_publish(post, user):
    """Approve *post*, email a copy to the configured inbox, then publish.

    Approve mirrors the console ``approve`` branch (Post-level review_state +
    audit row + move pending_review children to approved). The email is
    best-effort (a failure is logged, never fatal). Publishing is scheduled via
    ``schedule_now`` — the gate still runs at publish time and can still block.
    """
    # 1. Approve at the Post level (matches console_views.approval_decide).
    post.review_state = Post.ReviewState.APPROVED
    post.save(update_fields=["review_state", "updated_at"])
    ApprovalAction.objects.create(
        post=post, user=user, action=ApprovalAction.ActionType.APPROVED
    )
    post.platform_posts.filter(status="pending_review").update(status="approved")

    # 2. Email a copy (best-effort; never blocks publish).
    try:
        email_post_copy(post, get_setting(post.workspace_id, "review.copy_email"), user)
    except Exception:  # noqa: BLE001 — copy email is a notification, not a gate
        logger.warning("post-copy email failed for post %s", post.id, exc_info=True)

    # 3. Publish (gate enforced downstream in publisher.engine).
    schedule_now(post)
    return post
```

- [ ] **Step 4: Run test to verify it passes**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/approvals/tests/test_send_for_publish.py -k send_for_publish -q -p no:warnings`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/approvals/send_actions.py apps/approvals/tests/test_send_for_publish.py
git commit -m "feat(approvals): send_for_publish service (approve + email + publish)"
```

---

### Task 5: Wire `decision == "send"` into `approval_decide`

**Files:**
- Modify: `apps/approvals/console_views.py:49-76` (the `approval_decide` view)
- Test: `apps/approvals/tests/test_send_for_publish.py`

- [ ] **Step 1: Write the failing test**

```python
# append to apps/approvals/tests/test_send_for_publish.py
from django.urls import reverse


@pytest.mark.django_db
def test_send_decision_endpoint(client, workspace, reviewer):
    post = Post.objects.create(workspace=workspace, title="P", caption="c",
        review_state="pending", review_assignee=reviewer)
    url = reverse("console:approval-decide", args=[post.id])
    resp = client.post(url, {"decision": "send"})
    assert resp.status_code in (200, 302)
    post.refresh_from_db()
    assert post.review_state == "approved"
    assert post.scheduled_at is not None
    assert len(mail.outbox) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/approvals/tests/test_send_for_publish.py::test_send_decision_endpoint -q -p no:warnings`
Expected: FAIL — `decision == "send"` is unhandled, so `scheduled_at` stays `None` and no mail is sent.

- [ ] **Step 3: Add the `send` branch**

In `apps/approvals/console_views.py`, inside `approval_decide`, add this branch BEFORE the final `post.save(update_fields=["review_state", "updated_at"])` line (insert after the `reject` branch, before `post.save(...)`):

```python
    elif decision == "send":
        from apps.approvals.send_actions import send_for_publish

        send_for_publish(post, request.user)
        return redirect("console:approvals")
```

The early `return` is deliberate — `send_for_publish` already persists `review_state` and `scheduled_at`, so it bypasses the generic trailing save. The existing authorization check at the top of the view (`_is_ws_admin(request) or post.review_assignee_id == request.user.id`) already guards this branch.

- [ ] **Step 4: Run test to verify it passes**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/approvals/tests/test_send_for_publish.py::test_send_decision_endpoint -q -p no:warnings`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/approvals/console_views.py apps/approvals/tests/test_send_for_publish.py
git commit -m "feat(approvals): handle decision=send in approval_decide"
```

---

### Task 6: **Send** button in the AI Approvals console

**Files:**
- Modify: `templates/console/approvals.html` (the decision-form group, ~lines 15-23)
- Test: `apps/approvals/tests/test_send_for_publish.py`

- [ ] **Step 1: Write the failing test**

```python
# append to apps/approvals/tests/test_send_for_publish.py
@pytest.mark.django_db
def test_send_button_renders_in_queue(client, workspace, reviewer):
    Post.objects.create(workspace=workspace, title="Mine", caption="c",
        review_assignee=reviewer, review_state="pending")
    resp = client.get(reverse("console:approvals"))
    assert resp.status_code == 200
    assert b'value="send"' in resp.content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/approvals/tests/test_send_for_publish.py::test_send_button_renders_in_queue -q -p no:warnings`
Expected: FAIL — no `value="send"` in the page.

- [ ] **Step 3: Add the Send form**

In `templates/console/approvals.html`, after the existing Approve form (the `value="approve"` block, ~line 17) add:

```html
          <form method="post" action="{% url 'console:approval-decide' post.id %}">{% csrf_token %}
            <input type="hidden" name="decision" value="send">
            <button class="rounded text-white px-3 py-1 text-xs" style="background-color: var(--primary)"
                    title="Approve, email a copy, and publish">Send</button></form>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/approvals/tests/test_send_for_publish.py::test_send_button_renders_in_queue -q -p no:warnings`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add templates/console/approvals.html apps/approvals/tests/test_send_for_publish.py
git commit -m "feat(approvals): Send button on the AI Approvals queue"
```

---

### Task 7: Guard tests — permission + gate-still-authoritative

**Files:**
- Test: `apps/approvals/tests/test_send_for_publish.py`

- [ ] **Step 1: Write the failing tests**

```python
# append to apps/approvals/tests/test_send_for_publish.py
@pytest.mark.django_db
def test_non_assignee_cannot_send(client, organization, workspace):
    """A non-admin member cannot Send a post assigned to someone else."""
    from django.utils import timezone
    from apps.accounts.models import User
    from apps.members.models import OrgMembership, WorkspaceMembership

    assignee = User.objects.create_user(email="a@example.com", password="x",
        name="Assignee", tos_accepted_at=timezone.now())
    WorkspaceMembership.objects.create(user=assignee, workspace=workspace, workspace_role="member")
    attacker = User.objects.create_user(email="b@example.com", password="x",
        name="Attacker", tos_accepted_at=timezone.now())
    OrgMembership.objects.create(user=attacker, organization=organization,
        org_role=OrgMembership.OrgRole.MEMBER)
    WorkspaceMembership.objects.create(user=attacker, workspace=workspace, workspace_role="member")
    attacker.last_workspace_id = workspace.id
    attacker.save(update_fields=["last_workspace_id"])

    post = Post.objects.create(workspace=workspace, title="NotYours", caption="c",
        review_assignee=assignee, review_state="pending")

    client.force_login(attacker)
    resp = client.post(reverse("console:approval-decide", args=[post.id]), {"decision": "send"})
    assert resp.status_code == 403
    post.refresh_from_db()
    assert post.review_state == "pending"      # untouched
    assert post.scheduled_at is None           # not scheduled
    assert len(mail.outbox) == 0               # no email leaked


@pytest.mark.django_db
def test_gate_still_blocks_after_send(workspace, reviewer, social_account):
    """Send schedules publish but the gate is still authoritative: an
    AI-drafted PlatformPost with no valid gate_id must NOT publish."""
    from apps.composer.models import PlatformPost
    from apps.approvals.send_actions import send_for_publish
    from apps.publisher.engine import PublishEngine, GateBlockError

    post = Post.objects.create(workspace=workspace, title="P", caption="c",
        review_state="pending", review_assignee=reviewer)
    pp = PlatformPost.objects.create(post=post, social_account=social_account,
        status="pending_review")  # AI-drafted: gate_bypassed defaults False, no gate_id

    send_for_publish(post, reviewer)
    pp.refresh_from_db()
    assert pp.status == "scheduled"            # scheduled by Send

    # When the engine dispatches it, the gate blocks it (no valid gate_id).
    engine = PublishEngine()
    with pytest.raises(GateBlockError):
        engine._dispatch_to_provider(pp)
    pp.refresh_from_db()
    assert pp.status != "published"            # gate held the line
```

> Note: `social_account` is the repo-wide fixture used across `apps/api/tests` and `apps/publisher/tests`. If pytest reports it as missing for the approvals app, copy that fixture into `apps/approvals/tests/conftest.py` (it builds a `SocialAccount` for `workspace`). Confirm the exact `GateBlockError` import path against `apps/publisher/engine.py` before running (it is raised at `_dispatch_to_provider`).

- [ ] **Step 2: Run tests to verify they fail (or pass for the permission one)**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/approvals/tests/test_send_for_publish.py -k "non_assignee or gate_still" -q -p no:warnings`
Expected: `test_non_assignee_cannot_send` should already PASS (auth is inherited from Task 5). `test_gate_still_blocks_after_send` confirms the invariant; adjust only the fixture/import notes above if collection errors.

- [ ] **Step 3: Fix only if a guard fails**

If `test_non_assignee_cannot_send` fails, the early-return branch was placed *above* the authorization check — move the `decision == "send"` branch so it runs after the existing `if not (_is_ws_admin(...) or ...): return HttpResponseForbidden(...)` guard (it already is, in Task 5). No new code expected.

- [ ] **Step 4: Run the full new test file + the touched apps**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest apps/approvals/ apps/composer/tests/test_schedule_now.py -q -p no:warnings`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/approvals/tests/test_send_for_publish.py
git commit -m "test(approvals): one-click Send permission + gate-authoritative guards"
```

---

## Self-Review

**Spec coverage:**
- Send = approve + email-copy + publish in one click → Tasks 4–6. ✓
- Email to configurable fixed inbox (`REVIEW_COPY_EMAIL`, default Martin) → Task 1 (`review.copy_email`) + Task 3/4. ✓
- Gate unchanged + authoritative → no gate edits anywhere; Task 7 proves a sent post still blocks. ✓
- Email failure non-fatal → Task 4 `test_send_for_publish_email_failure_is_nonfatal`. ✓
- Send only by assignee/approver → Task 7 `test_non_assignee_cannot_send` (auth inherited from existing `approval_decide` guard). ✓
- Send button on the reviewer surface → Task 6. ✓
- Live link via existing publish-success notification → no work needed; the existing approve/publish notifications already fire. ✓
- Out of scope (no new approval modes, one fixed address, no second "it's live" email) → respected. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. The two external references (the `social_account` fixture and `GateBlockError` import path) are called out explicitly with where to confirm them — not silent gaps.

**Type/name consistency:** `schedule_now(post)` defined in Task 2, used in Task 4. `email_post_copy(post, to_email, reviewer)` defined Task 3, used Task 4. `send_for_publish(post, user)` defined Task 4, used Task 5. `review.copy_email` key consistent across Tasks 1 and 4. `decision == "send"` consistent across Tasks 5 and 6 (`value="send"`). Auth uses the existing `approval_decide` guard. Consistent.

---

## Notes for the implementer
- Settings cascade: an org/workspace can override `review.copy_email` via the existing `set_org_setting`/`WorkspaceSetting` mechanism — no new UI is in scope. A settings_manager form field is a fast follow if wanted.
- Publishing is async (the ~15s poll), so the copy email goes out at Send time without the live URL; the live link rides the existing publish-success notification. This is the agreed Approach A (not C).
