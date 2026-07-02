"""Regression: the live-preview endpoint must accept the caption via POST body.

The composer's live preview originally fired an ``hx-get`` that serialized the
whole compose form — including the full caption — into the URL query string.
A long caption (e.g. a multi-paragraph LinkedIn post) pushed the request line
past the server/proxy limit (~4-8 KB) and the edge returned ``400 Bad Request``
before Django ever saw it, so the preview silently stopped updating.

The fix moves the request to POST (caption rides in the body, no length ceiling)
and the view reads ``request.POST`` (with a GET fallback). These tests pin that
the view reads the caption from POST and that the full caption survives.

The Django test client imposes no request-line limit, so a 200 alone proves
nothing — the load-bearing assertion is that the POSTed caption is reflected.
"""
import pytest
from django.urls import reverse

from apps.members.models import WorkspaceMembership

MARKER = "REGRESSIONMARKER"
# Far longer than any single platform char limit and well past the ~8 KB URL
# ceiling that broke the old GET-based preview.
LONG_CAPTION = MARKER + " " + ("compute and capital and corridors " * 200)


@pytest.fixture
def manager_client(client, workspace, make_user_in_workspace):
    user = make_user_in_workspace(
        workspace, role=WorkspaceMembership.WorkspaceRole.MANAGER
    )
    client.force_login(user)
    return client, user, workspace


@pytest.fixture
def connected_account(db, workspace):
    """A connected LinkedIn SocialAccount in the test workspace."""
    from apps.social_accounts.models import SocialAccount

    return SocialAccount.objects.create(
        workspace=workspace,
        platform="linkedin",
        account_platform_id="acct-linkedin-preview",
        account_name="LinkedIn account",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    )


def test_preview_reads_long_caption_from_post(manager_client, connected_account):
    client, _user, workspace = manager_client
    url = reverse("composer:preview", kwargs={"workspace_id": workspace.id})

    resp = client.post(
        url,
        data={
            "caption": LONG_CAPTION,
            "selected_accounts": str(connected_account.id),
        },
    )

    assert resp.status_code == 200
    body = resp.content.decode("utf-8")
    # The caption was read from the POST body and rendered for the account.
    assert MARKER in body
    # The FULL caption length surfaced (char_count = len(caption)) — proving the
    # whole body arrived, not a transport-truncated query string.
    assert str(len(LONG_CAPTION)) in body


def test_preview_still_accepts_get(manager_client, connected_account):
    """GET fallback stays green for existing tests / direct links."""
    client, _user, workspace = manager_client
    url = reverse("composer:preview", kwargs={"workspace_id": workspace.id})

    resp = client.get(
        url,
        data={"caption": MARKER + " short", "selected_accounts": str(connected_account.id)},
    )

    assert resp.status_code == 200
    assert MARKER in resp.content.decode("utf-8")


# ---------------------------------------------------------------------------
# Platform-accurate cards for Blotato + Ghost (previously fell through to the
# bland generic card because the preview branches didn't recognise the keys).
# ---------------------------------------------------------------------------


@pytest.fixture
def x_account(db, workspace):
    from apps.social_accounts.models import SocialAccount

    return SocialAccount.objects.create(
        workspace=workspace,
        platform="blotato_twitter",
        account_platform_id="acct-x-preview",
        account_name="AI 10Bn",
        account_handle="ai10bn",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    )


@pytest.fixture
def ghost_account(db, workspace):
    from apps.social_accounts.models import SocialAccount

    return SocialAccount.objects.create(
        workspace=workspace,
        platform="ghost",
        account_platform_id="acct-ghost-preview",
        account_name="Nexus Brief",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    )


def test_blotato_twitter_renders_x_card(manager_client, x_account):
    client, _user, workspace = manager_client
    url = reverse("composer:preview", kwargs={"workspace_id": workspace.id})
    resp = client.post(
        url,
        data={"caption": "Africa energy investment", "selected_accounts": str(x_account.id)},
    )
    assert resp.status_code == 200
    body = resp.content.decode("utf-8")
    # X verified-badge path is unique to the X card (proves it's not the generic fallback).
    assert "M22.5 12.5c0-1.58" in body
    assert "@ai10bn" in body
    assert "Africa energy investment" in body
    # X Premium long-form limit (25,000) surfaces for the blotato_twitter card.
    assert "/25000" in body


def test_ghost_renders_article_card(manager_client, ghost_account):
    client, _user, workspace = manager_client
    url = reverse("composer:preview", kwargs={"workspace_id": workspace.id})
    resp = client.post(
        url,
        data={
            "title": "The $25 Billion Question",
            "caption": "<p>Africa has an investment problem.</p><h2>The capital exists</h2>",
            "selected_accounts": str(ghost_account.id),
        },
    )
    assert resp.status_code == 200
    body = resp.content.decode("utf-8")
    # Ghost article card renders the rich HTML body verbatim (|safe) under .ghost-article.
    assert "ghost-article" in body
    assert "The $25 Billion Question" in body
    assert "Nexus Brief" in body
    assert "<h2>The capital exists</h2>" in body
