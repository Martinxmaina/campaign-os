"""Deck review surface URLs (TB.5 Task 3).

Mounted under ``/joseph/decks/`` (see config/urls.py). The literal ``stale/``
and ``index`` routes precede the ``<uuid:deck_id>/`` detail route — a UUID
converter would not match ``stale`` regardless, but the explicit order keeps the
intent clear. Every view is gated by ``apps.joseph.views._can_access_joseph``.
"""
from django.urls import path

from . import views

app_name = "decks"

urlpatterns = [
    # Decks index — Joseph's deck action queue (drafts first).
    path("", views.index, name="index"),
    # Stale-figure report — sent decks pinning a now-superseded block.
    path("stale/", views.stale, name="stale"),
    # Per-deck review screen. deck_id is a DeckRegistry UUID.
    path("<uuid:deck_id>/", views.review, name="review"),
    # Restore a prior version (writes a NEW version row, never in-place).
    path("<uuid:deck_id>/revert/<uuid:version_id>/", views.revert, name="revert"),
]
