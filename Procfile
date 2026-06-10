release: python manage.py migrate
web: gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --threads 2
worker: celery -A config worker -l info --concurrency 2
beat: celery -A config beat -l info
