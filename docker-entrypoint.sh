#!/bin/sh
# One image, three roles. Railway sets PROCESS_TYPE per service (web|worker|beat).
set -e

PROCESS_TYPE="${PROCESS_TYPE:-web}"
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.production}"
echo "[entrypoint] PROCESS_TYPE=${PROCESS_TYPE} settings=${DJANGO_SETTINGS_MODULE}"

case "$PROCESS_TYPE" in
  web)
    python manage.py migrate --noinput
    exec gunicorn config.wsgi:application --bind 0.0.0.0:"${PORT:-8000}" --workers 2 --threads 2
    ;;
  worker)
    exec celery -A config worker -l info --concurrency 2
    ;;
  beat)
    exec celery -A config beat -l info
    ;;
  *)
    echo "[entrypoint] unknown PROCESS_TYPE: ${PROCESS_TYPE}" >&2
    exit 1
    ;;
esac
