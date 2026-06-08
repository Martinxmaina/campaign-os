# ADR-002: WAIIS Dispatch fork of BrightBean Studio

**Status:** Accepted (2026-06-08)

## Decision
WAIIS Dispatch is forked from BrightBean Studio (AGPLv3),
https://github.com/brightbeanxyz/brightbean-studio, pinned at commit `3d56b44`
(tagged `upstream-3d56b44`, remote `upstream`). The fork imports nothing from
`agent-service`; integration is HTTP-only and signed.

## Baseline
`uv run pytest` green at fork time: 643 passed. Deselected (needs external
services, re-enabled later): none.

## Toolchain
Python 3.13, Django 5.1.x, Django-Ninja, Postgres (job queue via
django-background-tasks). Deps via uv (`uv venv --python 3.13` +
`uv pip install -r requirements.txt`) per `requirements.txt`.

## Task 3: slimmed social providers (kept 7, removed 5)
Removed providers `tiktok`, `pinterest`, `google_business`, `mastodon`,
`bluesky` from `PROVIDER_REGISTRY` and deleted their `providers/*.py` modules
plus their dedicated tests (`tests/providers/test_tiktok.py`,
`tests/providers/test_bluesky.py`). In `tests/providers/test_base.py` the
registry-completeness set was trimmed to the kept 7; the bluesky/mastodon
metadata tests and the session-auth `get_auth_url` test were removed (they
exercised deleted providers); `test_get_provider_default_credentials` now
clears `PLATFORM_CREDENTIALS_FROM_ENV` via the `settings` fixture and uses a
kept provider. Dead env entries for the 5 removed platforms were dropped from
`PLATFORM_CREDENTIALS_FROM_ENV` in `config/settings/base.py`. Migration history
and the `PlatformCredential.Platform` DB choices are intentionally left intact
(no new migration; `makemigrations --check` reports no changes). Kept-7 set:
facebook, instagram, instagram_login, linkedin_personal, linkedin_company,
youtube, threads.

## Task 5: mock provider (test + slice acceptance)
Added `providers/mock.py` (`MockProvider`, platform_name "Mock",
max_caption_length 10000, post types TEXT/IMAGE/VIDEO) returning a synthetic
`mock_<hex16>` id. Registered into `PROVIDER_REGISTRY` only via
`providers._register_mock()`, which syncs the `"mock"` entry to the truthiness
of `settings.ENABLE_MOCK_PROVIDER` (idempotent both directions); called at
import time and on every `get_provider()` call so a runtime flag flip is
honoured. `ENABLE_MOCK_PROVIDER` added to base settings (env-driven, default
False) and set True in `config/settings/test.py`. The registry-completeness
assertion in `tests/providers/test_base.py::test_registry_contains_all_platforms`
was updated to compare `keys() - {"mock"}` against the real-platform set, since
the mock entry is an optional, flag-gated extra rather than a real platform. No
tests deselected; full suite green at 604 passed.

## Task 10: gate_id required to schedule via REST API
`CreatePostRequest` gained `gate_id: uuid.UUID | None`. The `POST /api/v1/posts/`
`create` route now 422s (`"gate_id is required to schedule/publish."`) when
`action="schedule"` and no `gate_id` is supplied; on success it stamps
`gate_id` + `content_hash=canonical_content_hash(effective_caption, media_refs)`
onto each child `PlatformPost` (defence-in-depth atop the publish-engine gate
hook from Task 9). Drafts may omit `gate_id`. Six existing schedule-path tests
that POST'd without a gate (`apps/api/tests/test_routers.py::TestCreatePost::
test_create_scheduled`, both `TestPlatformQuota` cases; `test_e2e.py`'s
publisher-pickup, quota-429, and audit-label schedule tests) were updated to
include a `gate_id` in the body — the contract change is intentional, no tests
were deselected. Added `tests/api_helpers.py` (`make_api_key`, `api_post`) for
top-level API tests. Full suite green at 612 passed.

## Local environment notes
- Dev DB: `createdb -h localhost -U macbook waiis_dispatch`
  (Postgres 17, role `macbook`, no password);
  `DATABASE_URL="postgres://macbook@localhost:5432/waiis_dispatch"`.
- Test settings (`config.settings.test`) create DB `brightbean_test`; run with
  `DB_USER=macbook DB_PASSWORD="" DB_HOST=localhost DB_PORT=5432`.
- Required env for manage.py / pytest: `SECRET_KEY`, `ENCRYPTION_KEY_SALT`,
  `DEBUG`, `ALLOWED_HOSTS`, `ENABLE_MOCK_PROVIDER`.
