# TB.1 — Joseph's Voice Profile — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A versioned voice profile HERALD applies when drafting Joseph's content — stored in agent-service, editable in Django, validated by a rubric, refined by a weekly loop on his edits.

**Architecture:** Voice profile = a `PlaybookVersion(agent_name="voice:joseph")` in agent-service. HERALD injects it into `system_extra` when `voice_user` is set. Django `/joseph/voice/` edits it via new `/voice/*` agent-service endpoints. Edit-deltas captured on Joseph's HERALD-post edits feed a weekly `voice_reflect` task that proposes profile diffs Joseph approves.

**Tech Stack:** agent-service (FastAPI, SQLAlchemy, Alembic, `uv run pytest`) + Django 5.1 (HTMX, `apps/evals`). Two repos:
- agent-service: `/Users/macbook/Downloads/WAIIS/agent-service` — tests `cd agent-service && uv run pytest <path> -q`; migrations `uv run alembic revision --autogenerate` + `upgrade head`.
- Django: `/Users/macbook/Downloads/WAIIS/waiis-dispatch-platform` — tests `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest <path> -p no:warnings -q`.

**Spec:** `docs/superpowers/specs/2026-06-12-tb1-joseph-voice-profile-design.md`

---

## File Map

**agent-service (new):** `app/agents/voice.py`, `app/api/voice.py`, `app/jobs/voice.py`, `app/db/models/voice.py` (+ migration), seed for `voice:joseph`, tests under `tests/`.
**agent-service (modified):** `app/services/herald.py`, `app/api/agents.py`, `app/db/models/__init__.py`, `app/main.py`, `app/jobs/app.py` (beat registration).
**Django (new):** `apps/joseph/` (app, urls, views), `templates/joseph/voice_editor.html`, `apps/content_intake/voice_rubric.py`, tests.
**Django (modified):** `apps/common/agent_client.py` (+`agent_put`), `config/urls.py`, composer save path (edit-delta capture), `apps/content_intake/herald_bridge.py` (pass `voice_user`).

---

## Task 1: Voice profile storage + loader + seed (agent-service)

**Files:**
- Create: `agent-service/app/agents/voice.py`
- Modify: `agent-service/app/db/seed.py` (or a dedicated seed)
- Test: `agent-service/tests/test_voice_store.py`

- [ ] **Step 1: Write the failing test**

```python
# agent-service/tests/test_voice_store.py
import pytest
from app.agents.voice import load_voice, save_voice, JOSEPH_V1


@pytest.mark.asyncio
async def test_save_then_load_increments_version(db_session):
    v1 = await save_voice(db_session, "joseph", JOSEPH_V1)
    assert v1 == 1
    body = await load_voice(db_session, "joseph")
    assert "banned_phrases" in body and "leverage" in " ".join(body["banned_phrases"]).lower()
    v2 = await save_voice(db_session, "joseph", {**JOSEPH_V1, "tone": "tweaked"})
    assert v2 == 2
    assert (await load_voice(db_session, "joseph"))["tone"] == "tweaked"


@pytest.mark.asyncio
async def test_load_missing_user_returns_empty(db_session):
    assert await load_voice(db_session, "nobody") == {}
```

(Use the repo's existing async db fixture — check `tests/conftest.py` for its name; if it differs from `db_session`, match it.)

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/macbook/Downloads/WAIIS/agent-service && uv run pytest tests/test_voice_store.py -q`
Expected: FAIL — `app.agents.voice` missing.

- [ ] **Step 3: Implement `voice.py`**

```python
# agent-service/app/agents/voice.py
"""Joseph's (and any principal's) voice profile, stored as a versioned playbook
(agent_name="voice:<user>") reusing PlaybookVersion. v1 seeded from docs/joseph.md."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PlaybookVersion

# v1 content, verbatim from docs/joseph.md TB.1.
JOSEPH_V1 = {
    "tone": "Direct, data-led, authoritative but not academic. African perspective as a "
            "strength, not a qualifier. No hedging language.",
    "openers": "Never start with 'I'. Never open a LinkedIn post with a question. Often open "
               "with a bold assertion or a number.",
    "hooks_by_audience": {
        "dfis": "blended finance architecture, catalytic capital, de-risking",
        "philanthropies": "catalytic capital, systems change, precedent",
        "governments": "digital public infrastructure, sovereignty, jobs",
        "tech_ecosystem": "energy-compute nexus, build vs. concept note",
    },
    "banned_phrases": ["synergies", "ecosystem play", "leverage", "unlock"],
    "signature_moves": [
        "the SE4ALL precedent argument",
        "the 'concept note vs. operational engine' framing",
        "the catalytic capital logic",
    ],
    "length_by_channel": {
        "linkedin": "250-400 words, tight",
        "email": "3 paragraphs max for cold; longer for warm follow-up",
        "x": "punchy, no threads unless it earns it",
        "voice": "conversational, first person, stories",
    },
}


def _agent_key(user: str) -> str:
    return f"voice:{user}"


async def load_voice(session: AsyncSession, user: str) -> dict:
    row = (await session.execute(
        select(PlaybookVersion)
        .where(PlaybookVersion.agent_name == _agent_key(user))
        .order_by(PlaybookVersion.version.desc()).limit(1)
    )).scalar_one_or_none()
    return row.body if row else {}


async def save_voice(session: AsyncSession, user: str, body: dict) -> int:
    """Insert a new version (prev max + 1). Returns the new version number."""
    prev = (await session.execute(
        select(PlaybookVersion.version)
        .where(PlaybookVersion.agent_name == _agent_key(user))
        .order_by(PlaybookVersion.version.desc()).limit(1)
    )).scalar_one_or_none()
    version = (prev or 0) + 1
    session.add(PlaybookVersion(agent_name=_agent_key(user), version=version, body=body))
    await session.commit()
    return version


async def seed_joseph_voice(session: AsyncSession) -> None:
    """Idempotent v1 seed."""
    if not await load_voice(session, "joseph"):
        await save_voice(session, "joseph", JOSEPH_V1)
```

Wire the seed into the existing startup seed: in `app/db/seed.py`, import and call `await seed_joseph_voice(session)` alongside the other seeds.

- [ ] **Step 4: Run to verify it passes**

Run: `cd /Users/macbook/Downloads/WAIIS/agent-service && uv run pytest tests/test_voice_store.py -q`
Expected: PASS (2 cases)

- [ ] **Step 5: Commit**

```bash
cd /Users/macbook/Downloads/WAIIS/agent-service
git add app/agents/voice.py app/db/seed.py tests/test_voice_store.py
git commit -m "feat(voice): voice profile storage (agent_name=voice:<user>) + load/save + joseph v1 seed"
```

---

## Task 2: `/voice` endpoints + delta/proposal models (agent-service)

**Files:**
- Create: `agent-service/app/db/models/voice.py`, `agent-service/app/api/voice.py`
- Modify: `agent-service/app/db/models/__init__.py`, `agent-service/app/main.py`
- Migration: autogenerated
- Test: `agent-service/tests/test_voice_api.py`

- [ ] **Step 1: Write the failing test**

```python
# agent-service/tests/test_voice_api.py
import pytest


@pytest.mark.asyncio
async def test_get_put_voice(client, lead_token):
    h = {"Authorization": f"Bearer {lead_token}"}
    # seed v1 first via PUT
    r = await client.put("/voice/joseph", json={"body": {"tone": "x", "banned_phrases": ["leverage"]}}, headers=h)
    assert r.status_code == 200 and r.json()["version"] >= 1
    g = await client.get("/voice/joseph", headers=h)
    assert g.status_code == 200 and g.json()["body"]["tone"] == "x"


@pytest.mark.asyncio
async def test_edit_delta_stored(client, lead_token):
    h = {"Authorization": f"Bearer {lead_token}"}
    r = await client.post("/voice/joseph/edit-delta",
                          json={"original": "a", "edited": "b", "channel": "linkedin"}, headers=h)
    assert r.status_code in (200, 201)
```

(Match the repo's existing async test client + token fixtures — see `tests/conftest.py` / `tests/test_gate_api.py` for names.)

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/macbook/Downloads/WAIIS/agent-service && uv run pytest tests/test_voice_api.py -q`
Expected: FAIL — no `/voice` routes.

- [ ] **Step 3: Models**

```python
# agent-service/app/db/models/voice.py
from __future__ import annotations
import uuid
from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.models.base import Base, UUIDPKMixin, TimestampMixin  # match the base import other models use


class VoiceEditDelta(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "voice_edit_deltas"
    user_key: Mapped[str] = mapped_column(String(64), index=True)
    original: Mapped[str] = mapped_column(Text, default="")
    edited: Mapped[str] = mapped_column(Text, default="")
    channel: Mapped[str] = mapped_column(String(32), default="")
    processed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class VoiceProposal(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "voice_proposals"
    user_key: Mapped[str] = mapped_column(String(64), index=True)
    proposed_body: Mapped[dict] = mapped_column(JSONB, default=dict)
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending|applied|dismissed
```

(Open an existing model file to confirm the exact `Base`/mixin import path; mirror it.)

Add to `app/db/models/__init__.py`:
```python
from app.db.models.voice import VoiceEditDelta, VoiceProposal  # noqa: F401
```

- [ ] **Step 4: Router**

```python
# agent-service/app/api/voice.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.voice import load_voice, save_voice
from app.db.models import PlaybookVersion, VoiceEditDelta
from app.db.session import get_session
from app.services.auth import require_role  # match how other routers import the role guard

router = APIRouter(prefix="/voice", tags=["voice"])


class VoiceBody(BaseModel):
    body: dict


class EditDelta(BaseModel):
    original: str = ""
    edited: str = ""
    channel: str = ""


@router.get("/{user}")
async def get_voice(user: str, _u: dict = Depends(require_role("lead")),
                    session: AsyncSession = Depends(get_session)) -> dict:
    body = await load_voice(session, user)
    return {"user": user, "body": body}


@router.put("/{user}")
async def put_voice(user: str, payload: VoiceBody, _u: dict = Depends(require_role("lead")),
                    session: AsyncSession = Depends(get_session)) -> dict:
    version = await save_voice(session, user, payload.body)
    return {"user": user, "version": version}


@router.get("/{user}/versions")
async def voice_versions(user: str, _u: dict = Depends(require_role("lead")),
                         session: AsyncSession = Depends(get_session)) -> dict:
    rows = (await session.execute(
        select(PlaybookVersion).where(PlaybookVersion.agent_name == f"voice:{user}")
        .order_by(PlaybookVersion.version.desc())
    )).scalars().all()
    return {"versions": [{"version": r.version, "created_at": r.created_at.isoformat(), "body": r.body} for r in rows]}


@router.post("/{user}/edit-delta")
async def edit_delta(user: str, payload: EditDelta, _u: dict = Depends(require_role("lead")),
                     session: AsyncSession = Depends(get_session)) -> dict:
    session.add(VoiceEditDelta(user_key=user, original=payload.original,
                               edited=payload.edited, channel=payload.channel))
    await session.commit()
    return {"ok": True}
```

Register in `app/main.py` (next to the other `include_router` calls):
```python
    from app.api import voice as voice_api
    app.include_router(voice_api.router)
```

- [ ] **Step 5: Migration**

Run:
```bash
cd /Users/macbook/Downloads/WAIIS/agent-service
uv run alembic revision --autogenerate -m "voice edit deltas + proposals"
uv run alembic upgrade head
```

- [ ] **Step 6: Run tests**

Run: `cd /Users/macbook/Downloads/WAIIS/agent-service && uv run pytest tests/test_voice_api.py tests/test_voice_store.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/macbook/Downloads/WAIIS/agent-service
git add app/api/voice.py app/db/models/voice.py app/db/models/__init__.py app/main.py app/db/migrations/ tests/test_voice_api.py
git commit -m "feat(voice): /voice GET/PUT/versions + edit-delta endpoint + delta/proposal models"
```

---

## Task 3: HERALD applies the voice (agent-service)

**Files:**
- Modify: `agent-service/app/services/herald.py`, `agent-service/app/api/agents.py`
- Test: `agent-service/tests/test_voice_herald.py`

- [ ] **Step 1: Write the failing test**

```python
# agent-service/tests/test_voice_herald.py
import pytest
from app.services.herald import _voice_block


@pytest.mark.asyncio
async def test_voice_block_includes_banned_and_length(db_session):
    from app.agents.voice import save_voice, JOSEPH_V1
    await save_voice(db_session, "joseph", JOSEPH_V1)
    block = await _voice_block(db_session, "joseph", channel="linkedin")
    assert "leverage" in block.lower()       # banned phrase listed
    assert "250-400" in block                # linkedin length rule present


@pytest.mark.asyncio
async def test_voice_block_empty_when_no_profile(db_session):
    assert await _voice_block(db_session, "nobody", channel="linkedin") == ""
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/macbook/Downloads/WAIIS/agent-service && uv run pytest tests/test_voice_herald.py -q`
Expected: FAIL — `_voice_block` missing.

- [ ] **Step 3: Add `_voice_block` + inject into `draft`**

In `app/services/herald.py`, add:

```python
from app.agents.voice import load_voice


async def _voice_block(session, voice_user: str | None, channel: str = "linkedin") -> str:
    if not voice_user:
        return ""
    v = await load_voice(session, voice_user)
    if not v:
        return ""
    length = (v.get("length_by_channel") or {}).get(channel, "")
    banned = ", ".join(v.get("banned_phrases", []))
    sigs = "; ".join(v.get("signature_moves", []))
    return (
        "\n\nVOICE PROFILE (write in this person's voice; obey strictly):\n"
        f"- Tone: {v.get('tone','')}\n"
        f"- Openers: {v.get('openers','')}\n"
        f"- NEVER use these phrases: {banned}\n"
        f"- Length for this channel: {length}\n"
        f"- Use these signature framings where they fit: {sigs}\n"
    )
```

In `draft(...)`, add a `voice_user: str | None = None` parameter, and append the block to
`system_extra` (after the existing PLAYBOOK assembly):

```python
    system_extra += await _voice_block(session, voice_user, channel="linkedin")
```

- [ ] **Step 4: Add `voice_user` to the request + route**

In `app/api/agents.py`, add `voice_user: str | None = None` to `HeraldDraftRequest` and pass it
through: `herald_draft(session, sector=body.sector, brief=body.brief, track=body.track,
count=min(body.count, 5), voice_user=body.voice_user, runtime=DeepSeekRuntime())`.

- [ ] **Step 5: Run tests**

Run: `cd /Users/macbook/Downloads/WAIIS/agent-service && uv run pytest tests/test_voice_herald.py -q`
Expected: PASS (2 cases)

- [ ] **Step 6: Commit**

```bash
cd /Users/macbook/Downloads/WAIIS/agent-service
git add app/services/herald.py app/api/agents.py tests/test_voice_herald.py
git commit -m "feat(voice): HERALD injects the VOICE block when voice_user is set"
```

---

## Task 4: Weekly voice-reflect proposal (agent-service)

**Files:**
- Create: `agent-service/app/jobs/voice.py`
- Modify: `agent-service/app/jobs/app.py` (register task)
- Test: `agent-service/tests/test_voice_reflect.py`

- [ ] **Step 1: Write the failing test**

```python
# agent-service/tests/test_voice_reflect.py
import pytest
from app.jobs.voice import voice_reflect_user
from app.db.models import VoiceEditDelta, VoiceProposal
from app.agents.voice import save_voice, JOSEPH_V1


@pytest.mark.asyncio
async def test_reflect_creates_pending_proposal(db_session):
    await save_voice(db_session, "joseph", JOSEPH_V1)
    for i in range(3):
        db_session.add(VoiceEditDelta(user_key="joseph",
            original="We will leverage synergies.", edited="We build the operational engine.",
            channel="linkedin"))
    await db_session.commit()
    await voice_reflect_user(db_session, "joseph")
    from sqlalchemy import select
    props = (await db_session.execute(select(VoiceProposal).where(VoiceProposal.user_key=="joseph"))).scalars().all()
    assert len(props) == 1 and props[0].status == "pending"
    # deltas marked processed
    deltas = (await db_session.execute(select(VoiceEditDelta).where(VoiceEditDelta.processed==True))).scalars().all()
    assert len(deltas) == 3
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/macbook/Downloads/WAIIS/agent-service && uv run pytest tests/test_voice_reflect.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `voice.py` job**

```python
# agent-service/app/jobs/voice.py
"""Weekly voice reflection: aggregate a principal's edit-deltas, ask the model for a
minimal voice-profile diff, store a pending VoiceProposal (never auto-applied)."""
from __future__ import annotations
import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.runtime.deepseek import DeepSeekRuntime
from app.agents.voice import load_voice
from app.db.models import VoiceEditDelta, VoiceProposal

logger = logging.getLogger(__name__)


async def voice_reflect_user(session: AsyncSession, user: str) -> None:
    deltas = (await session.execute(
        select(VoiceEditDelta).where(VoiceEditDelta.user_key == user, VoiceEditDelta.processed == False)  # noqa: E712
    )).scalars().all()
    if not deltas:
        return
    current = await load_voice(session, user)
    evidence = [{"original": d.original, "edited": d.edited, "channel": d.channel} for d in deltas]
    prompt = (
        "You refine a writer's VOICE PROFILE from how they edit AI drafts of their content.\n"
        f"CURRENT PROFILE (JSON):\n{json.dumps(current)}\n\n"
        f"EDIT DELTAS (original → edited):\n{json.dumps(evidence)}\n\n"
        "Propose a MINIMAL updated profile JSON (same keys) reflecting consistent patterns in the "
        "edits (e.g. new banned phrases, opener tendencies, length preferences). Output JSON only."
    )
    try:
        out = await DeepSeekRuntime().complete(prompt)  # match the runtime's actual call signature
        proposed = json.loads(_extract_json(out))
    except Exception:
        logger.exception("voice_reflect failed for %s", user)
        return
    session.add(VoiceProposal(user_key=user, proposed_body=proposed, evidence={"deltas": evidence}, status="pending"))
    for d in deltas:
        d.processed = True
    await session.commit()


def _extract_json(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start >= 0 and end > start else "{}"
```

(Confirm `DeepSeekRuntime`'s real completion method name in `app/agents/runtime/deepseek.py`;
the existing HERALD path uses `run_agent` — if there's no simple `.complete`, reuse `run_agent`
with a minimal agent or the runtime's direct call. Match what exists.)

Register a weekly beat entry in `app/jobs/app.py` (mirror the existing `herald_daily_draft`
registration) calling a `voice_reflect()` wrapper that iterates principals (currently just
"joseph").

- [ ] **Step 4: Run tests**

Run: `cd /Users/macbook/Downloads/WAIIS/agent-service && uv run pytest tests/test_voice_reflect.py -q`
Expected: PASS (mock the runtime in the test if it makes a network call — patch `DeepSeekRuntime.complete`
to return a JSON string with an added banned phrase).

- [ ] **Step 5: Commit**

```bash
cd /Users/macbook/Downloads/WAIIS/agent-service
git add app/jobs/voice.py app/jobs/app.py tests/test_voice_reflect.py
git commit -m "feat(voice): weekly voice_reflect proposes a profile diff from edit-deltas (pending, never auto-applied)"
```

---

## Task 5: Django voice editor (`/joseph/voice/`)

**Files:**
- Create: `apps/joseph/__init__.py`, `apps/joseph/apps.py`, `apps/joseph/views.py`, `apps/joseph/urls.py`, `templates/joseph/voice_editor.html`, `apps/joseph/tests/test_voice_editor.py`
- Modify: `apps/common/agent_client.py` (+`agent_put`), `config/urls.py`, `config/settings/base.py` (INSTALLED_APPS)
- Test: as above

- [ ] **Step 1: Write the failing test**

```python
# apps/joseph/tests/test_voice_editor.py
from unittest.mock import patch
import pytest
from django.urls import reverse


@pytest.fixture
def joseph(client, org_owner, workspace):
    from apps.members.models import WorkspaceMembership
    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    client.force_login(org_owner)
    return org_owner


@pytest.mark.django_db
def test_voice_editor_renders_sections(joseph, client):
    fake = {"user": "joseph", "body": {"tone": "Direct and data-led", "banned_phrases": ["leverage"],
            "openers": "x", "signature_moves": [], "hooks_by_audience": {}, "length_by_channel": {}}}
    with patch("apps.joseph.views.agent_get", return_value=fake):
        resp = client.get(reverse("joseph:voice"))
    assert resp.status_code == 200
    assert b"Direct and data-led" in resp.content
    assert b"leverage" in resp.content


@pytest.mark.django_db
def test_voice_save_puts_new_version(joseph, client):
    with patch("apps.joseph.views.agent_put", return_value={"version": 2}) as m:
        resp = client.post(reverse("joseph:voice-save"), {
            "tone": "t", "openers": "o", "banned_phrases": "leverage, synergies",
            "signature_moves": "SE4ALL precedent", "length_by_channel_linkedin": "250-400",
        })
    assert resp.status_code in (200, 302)
    m.assert_called_once()
    # banned_phrases sent as a list
    sent = m.call_args[0][1]
    assert "leverage" in sent["body"]["banned_phrases"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/joseph/tests/test_voice_editor.py -p no:warnings -q`
Expected: FAIL — app/route missing.

- [ ] **Step 3: Add `agent_put` to the client**

In `apps/common/agent_client.py`, mirror `agent_post` but with `c.put(...)`:

```python
def agent_put(path: str, json: dict | None = None) -> dict:
    url, headers = _url_and_headers(path)   # reuse whatever agent_post uses to build these
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as c:
            resp = c.put(url, json=json, headers=headers)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as exc:
        raise AgentClientError(str(exc)) from exc
```

(Match the exact URL/header/error construction `agent_post` already uses in this file.)

- [ ] **Step 4: Scaffold `apps/joseph`**

```bash
mkdir -p apps/joseph/tests && touch apps/joseph/__init__.py apps/joseph/tests/__init__.py
```

`apps/joseph/apps.py`:
```python
from django.apps import AppConfig
class JosephConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.joseph"
    verbose_name = "Joseph"
```

`apps/joseph/views.py`:
```python
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.common.agent_client import agent_get, agent_put

_CHANNELS = ["linkedin", "email", "x", "voice"]


@login_required
def voice_editor(request):
    data = agent_get("/voice/joseph")
    body = (data or {}).get("body", {})
    return render(request, "joseph/voice_editor.html", {"body": body, "channels": _CHANNELS})


@login_required
@require_POST
def voice_save(request):
    body = {
        "tone": request.POST.get("tone", "").strip(),
        "openers": request.POST.get("openers", "").strip(),
        "banned_phrases": [p.strip() for p in request.POST.get("banned_phrases", "").split(",") if p.strip()],
        "signature_moves": [s.strip() for s in request.POST.get("signature_moves", "").split("\n") if s.strip()],
        "length_by_channel": {c: request.POST.get(f"length_by_channel_{c}", "").strip() for c in _CHANNELS},
        "hooks_by_audience": {},  # edited in a later iteration; preserve existing on round-trip
    }
    # preserve hooks_by_audience from current profile
    current = (agent_get("/voice/joseph") or {}).get("body", {})
    body["hooks_by_audience"] = current.get("hooks_by_audience", {})
    agent_put("/voice/joseph", {"body": body})
    return redirect("joseph:voice")
```

`apps/joseph/urls.py`:
```python
from django.urls import path
from . import views
app_name = "joseph"
urlpatterns = [
    path("voice/", views.voice_editor, name="voice"),
    path("voice/save/", views.voice_save, name="voice-save"),
]
```

`templates/joseph/voice_editor.html` (extends the console base; sectioned form):
```html
{% extends "console/base.html" %}
{% block content %}
<div class="p-6 max-w-3xl">
  <h1 class="text-2xl font-bold mb-4">Joseph — Voice Profile</h1>
  <form method="post" action="{% url 'joseph:voice-save' %}" class="space-y-4">
    {% csrf_token %}
    <label class="block text-sm font-medium">Tone</label>
    <textarea name="tone" rows="2" class="w-full rounded border px-3 py-2 text-sm">{{ body.tone }}</textarea>
    <label class="block text-sm font-medium">Openers</label>
    <textarea name="openers" rows="2" class="w-full rounded border px-3 py-2 text-sm">{{ body.openers }}</textarea>
    <label class="block text-sm font-medium">Banned phrases (comma-separated)</label>
    <input name="banned_phrases" value="{{ body.banned_phrases|join:', ' }}" class="w-full rounded border px-3 py-2 text-sm">
    <label class="block text-sm font-medium">Signature moves (one per line)</label>
    <textarea name="signature_moves" rows="3" class="w-full rounded border px-3 py-2 text-sm">{{ body.signature_moves|join:'
' }}</textarea>
    <label class="block text-sm font-medium">Length by channel</label>
    {% for c in channels %}
    <div class="flex items-center gap-2"><span class="w-20 text-xs text-stone-500">{{ c }}</span>
      <input name="length_by_channel_{{ c }}" value="{{ body.length_by_channel|default_if_none:''|dictsort:0 }}" class="flex-1 rounded border px-2 py-1 text-sm"></div>
    {% endfor %}
    <button class="rounded bg-blue-600 text-white px-4 py-2 text-sm">Save new version</button>
  </form>
</div>
{% endblock %}
```
(If the `length_by_channel` per-channel prefill expression is awkward in the template, pass a
pre-zipped `channel_lengths` list of `(channel, value)` from the view instead.)

Add `"apps.joseph"` to `LOCAL_APPS` in `config/settings/base.py`, and mount in `config/urls.py`:
```python
    path("joseph/", include("apps.joseph.urls")),
```

- [ ] **Step 5: Run tests**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/joseph/tests/test_voice_editor.py -p no:warnings -q`
Expected: PASS (2 cases)

- [ ] **Step 6: Surface + apply reflection proposals (Component 5 approve)**

Add agent-service endpoints in `app/api/voice.py`: `GET /voice/{user}/proposals` (pending list)
and `POST /voice/{user}/proposals/{id}/apply` (save `proposed_body` as a new version via
`save_voice`, mark proposal `applied`) and `.../dismiss` (mark `dismissed`). Then in
`apps/joseph/views.py::voice_editor`, also `agent_get("/voice/joseph/proposals")` and render any
pending proposal as a diff with **Apply** / **Dismiss** buttons (POST to new Django views
`voice_apply_proposal` / `voice_dismiss_proposal` that call the agent-service endpoints). Add a
test: a pending proposal renders in the editor and Apply calls the agent-service apply endpoint
(mock `agent_post`).

- [ ] **Step 7: Run tests**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/joseph/tests/ -p no:warnings -q`
Expected: PASS (editor render + save + proposal apply).

- [ ] **Step 8: Commit**

```bash
cd /Users/macbook/Downloads/WAIIS/waiis-dispatch-platform
git add apps/joseph/ templates/joseph/ apps/common/agent_client.py config/urls.py config/settings/base.py
git commit -m "feat(joseph): /joseph/voice editor (read+save+approve proposals) + agent_put"
cd /Users/macbook/Downloads/WAIIS/agent-service
git add app/api/voice.py && git commit -m "feat(voice): proposal list/apply/dismiss endpoints"
```

---

## Task 6: Voice rubric eval (Django)

**Files:**
- Create: `apps/content_intake/voice_rubric.py`, `apps/content_intake/tests/test_voice_rubric.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/content_intake/tests/test_voice_rubric.py
from apps.content_intake.voice_rubric import score_voice

PROFILE = {
    "banned_phrases": ["synergies", "leverage", "unlock", "ecosystem play"],
    "length_by_channel": {"linkedin": (250, 400), "email": (40, 400)},
    "signature_moves": ["SE4ALL", "operational engine", "catalytic capital"],
}


def test_joseph_linkedin_passes():
    text = ("300 reasons the catalytic capital logic beats a concept note. " * 30)  # ~300+ words, no banned, no 'I' opener
    res = score_voice(text, "linkedin", PROFILE)
    assert res["passed"], res["failures"]


def test_non_joseph_fails_on_banned_and_opener():
    text = "I think we should leverage synergies to unlock our ecosystem play."
    res = score_voice(text, "linkedin", PROFILE)
    assert not res["passed"]
    assert any("banned" in f for f in res["failures"])


def test_email_length_out_of_range_fails():
    res = score_voice("Too short.", "email", PROFILE)
    assert not res["passed"]
    assert any("length" in f for f in res["failures"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/content_intake/tests/test_voice_rubric.py -p no:warnings -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `voice_rubric.py`**

```python
# apps/content_intake/voice_rubric.py
"""Score text against a voice profile (TB.1 validation rubric)."""
from __future__ import annotations
import re


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text or ""))


def score_voice(text: str, channel: str, profile: dict) -> dict:
    failures: list[str] = []
    low = (text or "").lower()

    for phrase in profile.get("banned_phrases", []):
        if phrase.lower() in low:
            failures.append(f"banned phrase present: {phrase!r}")

    stripped = (text or "").lstrip()
    if stripped[:2].lower() == "i " or stripped[:2] == "I'":
        failures.append("opener starts with 'I'")
    if channel == "linkedin" and stripped[:80].strip().endswith("?"):
        failures.append("LinkedIn opener is a question")

    rng = (profile.get("length_by_channel") or {}).get(channel)
    if isinstance(rng, (list, tuple)) and len(rng) == 2:
        wc = _word_count(text)
        if wc < rng[0] or wc > rng[1]:
            failures.append(f"length {wc} out of range {rng[0]}-{rng[1]} for {channel}")

    return {"passed": not failures, "failures": failures}
```

- [ ] **Step 4: Run tests**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/content_intake/tests/test_voice_rubric.py -p no:warnings -q`
Expected: PASS (3 cases)

- [ ] **Step 5: Commit**

```bash
cd /Users/macbook/Downloads/WAIIS/waiis-dispatch-platform
git add apps/content_intake/voice_rubric.py apps/content_intake/tests/test_voice_rubric.py
git commit -m "feat(voice): voice rubric eval (banned phrases, opener, channel length)"
```

---

## Task 7: Edit-delta capture + bridge passes voice_user (Django)

**Files:**
- Modify: `apps/content_intake/herald_bridge.py` (pass `voice_user` for Joseph-owned items)
- Modify: composer save path (`apps/composer/views.py::save_post`) — capture Joseph's HERALD-origin edit-deltas
- Test: `apps/content_intake/tests/test_voice_capture.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/content_intake/tests/test_voice_capture.py
from unittest.mock import patch
import pytest
from apps.content_intake.herald_bridge import request_herald_draft
from apps.content_intake.models import ContentIntake


@pytest.mark.django_db
def test_bridge_passes_voice_user_for_joseph(workspace):
    item = ContentIntake.objects.create(workspace=workspace, external_id="V-1", angle="x",
        owner_raw="Joseph", channel_targets=[{"platform": "linkedin", "account": "joseph"}],
        sensitivity="public_safe", status="accepted")
    with patch("apps.content_intake.herald_bridge.agent_post", return_value={"proposals": [{"content_id": "c1"}]}) as m:
        request_herald_draft(item)
    payload = m.call_args[0][1]
    assert payload.get("voice_user") == "joseph"


@pytest.mark.django_db
def test_bridge_no_voice_user_for_org_item(workspace):
    item = ContentIntake.objects.create(workspace=workspace, external_id="V-2", angle="x",
        owner_raw="Carren", channel_targets=[{"platform": "linkedin", "account": "waiis"}],
        sensitivity="public_safe", status="accepted")
    with patch("apps.content_intake.herald_bridge.agent_post", return_value={"proposals": [{"content_id": "c2"}]}) as m:
        request_herald_draft(item)
    payload = m.call_args[0][1]
    assert "voice_user" not in payload or payload.get("voice_user") is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/content_intake/tests/test_voice_capture.py -p no:warnings -q`
Expected: FAIL — bridge doesn't send `voice_user`.

- [ ] **Step 3: Pass `voice_user` in the bridge**

In `apps/content_intake/herald_bridge.py`, in `request_herald_draft`, when building the
`agent_post("/agents/herald/draft", {...})` payload, add Joseph detection:

```python
    is_joseph = (intake.owner_raw or "").strip().lower().startswith("joseph") or any(
        (t.get("account") or "").lower() == "joseph" for t in (intake.channel_targets or [])
    )
    payload = {"sector": sector, "brief": brief, "count": 1}
    if is_joseph:
        payload["voice_user"] = "joseph"
    result = agent_post("/agents/herald/draft", payload)
```

(Adapt to the exact current payload construction in the function.)

- [ ] **Step 4: Capture edit-deltas on Joseph's HERALD-post edits**

In `apps/composer/views.py::save_post`, after a successful save of an existing post, if the post
originates from a HERALD draft for Joseph, send the delta. Add near the end of `save_post` (after
`post.save()` / version snapshot), guarded so it never blocks the save:

```python
    try:
        _capture_voice_delta(request, post)
    except Exception:
        logger.exception("voice delta capture failed for post %s", post.id)
```

and a helper in the same module:

```python
def _capture_voice_delta(request, post):
    """If this post came from a HERALD draft for Joseph and a human edited the caption,
    record the (original → edited) delta in agent-service for voice reflection."""
    from apps.common.agent_client import agent_post as _ap
    intake = getattr(post, "intake_source", None)
    intake = intake.first() if intake is not None else None
    if intake is None or not intake.herald_content_id:
        return
    if not (intake.owner_raw or "").strip().lower().startswith("joseph"):
        return
    original = request.POST.get("_herald_original_caption", "")
    edited = post.caption or ""
    if original and edited and original.strip() != edited.strip():
        _ap("/voice/joseph/edit-delta", {"original": original, "edited": edited, "channel": "linkedin"})
```

The composer edit form must carry the original AI caption in a hidden field
`_herald_original_caption` (set when the composer loads a HERALD-origin post). Add that hidden
input to the composer template's edit form for HERALD-origin posts.

- [ ] **Step 5: Run tests**

Run: `DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest apps/content_intake/tests/test_voice_capture.py -p no:warnings -q`
Expected: PASS (2 cases).

- [ ] **Step 6: Commit**

```bash
cd /Users/macbook/Downloads/WAIIS/waiis-dispatch-platform
git add apps/content_intake/herald_bridge.py apps/composer/views.py templates/composer/ apps/content_intake/tests/test_voice_capture.py
git commit -m "feat(voice): bridge sends voice_user=joseph + composer captures Joseph's HERALD edit-deltas"
```

---

## Task 8: Full suites (both repos) + deploy both services

**Files:** none (verification).

- [ ] **Step 1: agent-service suite**

Run: `cd /Users/macbook/Downloads/WAIIS/agent-service && uv run pytest -q 2>&1 | tail -12`
Expected: all pass.

- [ ] **Step 2: Django suite**

Run: `cd /Users/macbook/Downloads/WAIIS/waiis-dispatch-platform && DJANGO_SETTINGS_MODULE=config.settings.test /Users/macbook/.local/bin/uv run pytest -p no:warnings -q 2>&1 | tail -12`
Expected: all pass.

- [ ] **Step 3: Commit + push both repos**

```bash
cd /Users/macbook/Downloads/WAIIS/agent-service && git push origin HEAD
cd /Users/macbook/Downloads/WAIIS/waiis-dispatch-platform && git push origin main
```

- [ ] **Step 4: Deploy both services**

```bash
# agent-service (project waiis-agent-service)
cd /Users/macbook/Downloads/WAIIS/agent-service
railway link --project eeec90fd-f7f4-42f3-967a-c3d82b2c0f09
railway up --service web
# dispatch platform
cd /Users/macbook/Downloads/WAIIS/waiis-dispatch-platform
railway link --project 2ee08478-c28d-4e6e-a1d0-bf8d5c871051
railway up --service web
railway up --service worker
```

- [ ] **Step 5: Verify live**

```bash
TOKEN="<AGENT_SERVICE_TOKEN>"  # the 1-year platform JWT
curl -s https://web-production-e7cf9.up.railway.app/voice/joseph -H "Authorization: Bearer $TOKEN" | head -c 300
curl -s -o /dev/null -w "joseph voice page: %{http_code}\n" https://web-production-2f84d.up.railway.app/joseph/voice/
```
Expected: voice GET returns the seeded profile JSON; `/joseph/voice/` → 302 (login).

- [ ] **Step 6: Verification commit**

```bash
cd /Users/macbook/Downloads/WAIIS/waiis-dispatch-platform
git commit --allow-empty -m "chore: TB.1 voice profile deployed + verified (both services)"
git push origin main
```

---

## Notes for the Operator

- `/joseph/voice/` (Joseph/owner role) shows the 6-section voice profile, seeded from `joseph.md`; saving creates a new version.
- When HERALD drafts Joseph's content (owner=Joseph or channel=joseph), it now writes in his voice.
- When Joseph edits a HERALD draft of his content, the change is recorded; the weekly `voice_reflect` task proposes profile updates from those edits for him to approve.
- The voice rubric (`score_voice`) validates drafts against the profile.
