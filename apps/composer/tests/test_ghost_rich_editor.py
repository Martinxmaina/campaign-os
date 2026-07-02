"""Roadmap #2 — rich HTML editor for the Ghost (Nexus Brief) channel override.

Two layers are covered:

1. Provider — when ``content.extra['body_format'] == 'html'`` the Ghost provider
   must publish the supplied HTML *verbatim* (no escaping), and re-host inline
   ``<img>`` on Ghost so the rendered article survives our presigned-URL expiry.
2. Composer render — editing a post that has a GHOST channel selected with a
   saved HTML override must render the rich-editor toolbar AND ship the saved
   HTML to the page so the contenteditable can re-hydrate.
"""
import httpx
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.composer.models import PlatformPost, Post
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace
from providers.ghost import GhostProvider
from providers.types import PublishContent

CREDS = {"admin_api_key": "id123:" + "ab" * 32, "base_url": "https://demo.ghost.io"}


def _provider():
    return GhostProvider(credentials=dict(CREDS))


# ── Provider: HTML body is published verbatim ────────────────────────────────


def test_html_body_format_publishes_html_unescaped(monkeypatch):
    """body_format=html → the supplied HTML reaches the POST body intact,
    NOT run through escaping (no &lt;p&gt; etc.)."""
    captured = {}

    def fake_post(url, headers=None, json=None, **kw):
        captured["url"] = url
        captured["json"] = json
        return httpx.Response(201, json={"posts": [{"id": "p1", "url": "https://demo.ghost.io/p1/"}]})

    monkeypatch.setattr("providers.ghost.httpx.post", fake_post)

    rich = "<h2>The Brief</h2><p>Bold <strong>energy</strong> news &amp; more.</p><ul><li>One</li></ul>"
    res = _provider().publish_post(
        "unused",
        PublishContent(text=rich, extra={"body_format": "html", "ghost_publish_as": "post"}),
    )

    assert res.platform_post_id == "p1"
    sent_html = captured["json"]["posts"][0]["html"]
    # The real HTML tags survive — they were NOT escaped into entities.
    assert "<h2>The Brief</h2>" in sent_html
    assert "<strong>energy</strong>" in sent_html
    assert "<ul><li>One</li></ul>" in sent_html
    assert "&lt;p&gt;" not in sent_html
    # Title/excerpt are derived from the stripped text content, sensibly.
    assert captured["json"]["posts"][0]["title"]
    # custom_excerpt is only set when a subtitle is supplied (none here); when
    # present it must never contain raw HTML.
    assert "<" not in captured["json"]["posts"][0].get("custom_excerpt", "")


def test_plain_text_path_still_escapes(monkeypatch):
    """Without body_format=html the legacy plain-text path is unchanged:
    angle brackets in the text are escaped, wrapped in <p>."""
    captured = {}

    def fake_post(url, headers=None, json=None, **kw):
        captured["json"] = json
        return httpx.Response(201, json={"posts": [{"id": "p2", "url": "https://demo.ghost.io/p2/"}]})

    monkeypatch.setattr("providers.ghost.httpx.post", fake_post)

    _provider().publish_post(
        "unused",
        PublishContent(text="Plain <not a tag> line", extra={"ghost_publish_as": "post"}),
    )
    sent_html = captured["json"]["posts"][0]["html"]
    assert "&lt;not a tag&gt;" in sent_html


def test_inline_images_rehosted_on_ghost(monkeypatch):
    """An <img> pointing at our (presigned) media is uploaded to Ghost's
    /images/upload/ and its src is rewritten to the stable Ghost URL."""
    posts = []

    def fake_get(url, **kw):
        # The provider fetches the image bytes from our media URL.
        return httpx.Response(200, content=b"\xff\xd8\xff-fakejpeg", headers={"content-type": "image/jpeg"})

    def fake_post(url, headers=None, json=None, files=None, data=None, **kw):
        if url.endswith("/images/upload/"):
            return httpx.Response(
                201, json={"images": [{"url": "https://demo.ghost.io/content/images/2026/06/hero.jpg"}]}
            )
        posts.append({"url": url, "json": json})
        return httpx.Response(201, json={"posts": [{"id": "p3", "url": "https://demo.ghost.io/p3/"}]})

    monkeypatch.setattr("providers.ghost.httpx.get", fake_get)
    monkeypatch.setattr("providers.ghost.httpx.post", fake_post)

    presigned = "https://s3.example.com/media/hero.jpg?X-Amz-Expires=3600&sig=abc"
    rich = f'<p>See:</p><img src="{presigned}" alt="hero">'
    _provider().publish_post(
        "unused",
        PublishContent(text=rich, extra={"body_format": "html", "ghost_publish_as": "post"}),
    )

    sent_html = posts[0]["json"]["posts"][0]["html"]
    assert "https://demo.ghost.io/content/images/2026/06/hero.jpg" in sent_html
    assert presigned not in sent_html


def test_rehost_failure_keeps_original_src(monkeypatch):
    """If the Ghost image upload fails, the original src is left intact
    (best-effort — we still publish the article)."""
    posts = []

    def fake_get(url, **kw):
        return httpx.Response(200, content=b"bytes", headers={"content-type": "image/png"})

    def fake_post(url, headers=None, json=None, files=None, data=None, **kw):
        if url.endswith("/images/upload/"):
            return httpx.Response(500, text="boom")
        posts.append({"json": json})
        return httpx.Response(201, json={"posts": [{"id": "p4", "url": "https://demo.ghost.io/p4/"}]})

    monkeypatch.setattr("providers.ghost.httpx.get", fake_get)
    monkeypatch.setattr("providers.ghost.httpx.post", fake_post)

    src = "https://s3.example.com/media/x.png?sig=1"
    _provider().publish_post(
        "unused",
        PublishContent(text=f'<img src="{src}">', extra={"body_format": "html"}),
    )
    assert src in posts[0]["json"]["posts"][0]["html"]


# ── Composer render: Ghost rich editor + saved HTML prefill ─────────────────


class GhostRichEditorRenderTests(TestCase):
    def setUp(self):
        # Non-singleton names so they don't collide with the auto-provisioned
        # "AfCEN"/"WAIIS" org+workspace the user post_save signal creates.
        self.org = Organization.objects.create(name="AfCEN RichEd")
        self.workspace = Workspace.objects.create(organization=self.org, name="WAIIS RichEd")
        self.user = User.objects.create_user(
            email="ed@example.com", password="pw", tos_accepted_at=timezone.now()
        )
        OrgMembership.objects.create(
            user=self.user, organization=self.org, org_role=OrgMembership.OrgRole.OWNER
        )
        WorkspaceMembership.objects.create(
            user=self.user, workspace=self.workspace,
            workspace_role=WorkspaceMembership.WorkspaceRole.OWNER,
        )
        self.ghost = SocialAccount.objects.create(
            workspace=self.workspace,
            platform="ghost",
            account_platform_id="ghost-1",
            account_name="Nexus Brief",
            connection_status="connected",
        )

    def _compose_edit_url(self, post):
        return reverse(
            "composer:compose_edit",
            kwargs={"workspace_id": self.workspace.id, "post_id": post.id},
        )

    def test_edit_renders_toolbar_and_saved_html(self):
        post = Post.objects.create(
            workspace=self.workspace, author=self.user, title="Brief", caption="plain shared"
        )
        saved_html = "<h2>Headline</h2><p>The <strong>article</strong> body.</p>"
        PlatformPost.objects.create(
            post=post,
            social_account=self.ghost,
            status=PlatformPost.Status.DRAFT,
            platform_specific_caption=saved_html,
        )

        self.client.force_login(self.user)
        resp = self.client.get(self._compose_edit_url(post))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()

        # The rich-editor toolbar marker is present (CSP-safe contenteditable editor).
        self.assertIn("ghost-rich-toolbar", body)
        self.assertIn('data-ghost-rich-editor="1"', body)
        self.assertIn("ghost-rich-editor", body)
        # The saved HTML is shipped to the page via the platform_overrides json_script
        # so the contenteditable can re-hydrate it on init.
        self.assertIn("composer-platform-overrides", body)
        self.assertIn("Headline", body)
        self.assertIn("article", body)

    def test_edit_renders_for_post_with_ghost_channel_selected(self):
        """Even without a saved override, selecting the Ghost channel renders
        the rich editor branch (toolbar present, plain textarea kept for others)."""
        post = Post.objects.create(
            workspace=self.workspace, author=self.user, title="Brief2", caption="shared"
        )
        PlatformPost.objects.create(
            post=post, social_account=self.ghost, status=PlatformPost.Status.DRAFT
        )
        self.client.force_login(self.user)
        resp = self.client.get(self._compose_edit_url(post))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("ghost-rich-toolbar", body)
        # The Ghost account id is among the selected accounts.
        self.assertIn(str(self.ghost.id), body)
