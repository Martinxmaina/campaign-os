"""Infra-level Celery tasks (heartbeat)."""
from celery import shared_task
from django.core.cache import cache
from django.utils import timezone


@shared_task
def beat_heartbeat():
    """Write a fresh timestamp the health view reads to prove beat is alive."""
    cache.set("beat:heartbeat", timezone.now().isoformat(), timeout=300)
