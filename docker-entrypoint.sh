#!/bin/sh
# One image, three roles. Railway sets PROCESS_TYPE per service (web|worker|beat).
set -e

PROCESS_TYPE="${PROCESS_TYPE:-web}"
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.production}"
echo "[entrypoint] PROCESS_TYPE=${PROCESS_TYPE} settings=${DJANGO_SETTINGS_MODULE}"

case "$PROCESS_TYPE" in
  web)
    python manage.py migrate --noinput
    # Auto-connect Ghost from GHOST_ADMIN_API_KEY (idempotent; no-op if unset).
    # || true so a Ghost hiccup never blocks the web boot.
    python manage.py ensure_ghost_connected || true
    exec gunicorn config.wsgi:application --bind 0.0.0.0:"${PORT:-8000}" --workers 2 --threads 2
    ;;
  worker)
    # Single-worker Railway deploy: run beat embedded (-B) so periodic
    # schedules fire without a separate dyno. If you scale to multiple
    # workers, drop -B here and run a dedicated PROCESS_TYPE=beat service
    # (the `beat)` case below) so only ONE scheduler is active.
    exec celery -A config worker -B -l info --concurrency 2
    ;;
  beat)
    exec celery -A config beat -l info
    ;;
  *)
    echo "[entrypoint] unknown PROCESS_TYPE: ${PROCESS_TYPE}" >&2
    exit 1
    ;;
esac
