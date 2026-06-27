from django.urls import path

from . import views

app_name = "social_accounts"

urlpatterns = [
    # Workspace-scoped views
    path(
        "<uuid:workspace_id>/",
        views.account_list,
        name="list",
    ),
    path(
        "<uuid:workspace_id>/connect/",
        views.connect_platform,
        name="connect",
    ),
    path(
        "<uuid:workspace_id>/connect/bluesky/",
        views.connect_bluesky,
        name="connect_bluesky",
    ),
    path(
        "<uuid:workspace_id>/connect/mastodon/",
        views.connect_mastodon,
        name="connect_mastodon",
    ),
    # OAuth callback (not workspace-scoped - platform redirects here)
    path(
        "callback/<str:platform>/",
        views.oauth_callback,
        name="oauth_callback",
    ),
    # Account selection (Facebook multi-page)
    path(
        "select-account/",
        views.select_account,
        name="select_account",
    ),
    # Blotato import (multi-platform publishing add-on)
    path(
        "<uuid:workspace_id>/blotato/import/",
        views.blotato_import,
        name="blotato_import",
    ),
    # Per-account actions
    path(
        "<uuid:workspace_id>/<uuid:account_id>/reconnect/",
        views.reconnect,
        name="reconnect",
    ),
    path(
        "<uuid:workspace_id>/<uuid:account_id>/disconnect/",
        views.disconnect,
        name="disconnect",
    ),
    path(
        "<uuid:workspace_id>/<uuid:account_id>/logo/",
        views.set_account_logo,
        name="set_logo",
    ),
]
