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

## Local environment notes
- Dev DB: `createdb -h localhost -U macbook waiis_dispatch`
  (Postgres 17, role `macbook`, no password);
  `DATABASE_URL="postgres://macbook@localhost:5432/waiis_dispatch"`.
- Test settings (`config.settings.test`) create DB `brightbean_test`; run with
  `DB_USER=macbook DB_PASSWORD="" DB_HOST=localhost DB_PORT=5432`.
- Required env for manage.py / pytest: `SECRET_KEY`, `ENCRYPTION_KEY_SALT`,
  `DEBUG`, `ALLOWED_HOSTS`, `ENABLE_MOCK_PROVIDER`.
