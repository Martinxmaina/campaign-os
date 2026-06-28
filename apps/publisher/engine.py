"""Publishing Engine - background worker logic (F-2.4).

This module implements the core publish loop:
1. Poll for PlatformPosts where scheduled_at <= now() and status = 'scheduled'.
2. Transition each due PlatformPost to 'publishing'.
3. Dispatch platform posts in parallel.
4. Handle retries with exponential backoff.
5. Post first comment after 2-minute delay.
6. Update per-platform status and log results.

Status is owned entirely by ``PlatformPost`` — the parent ``Post`` exposes an
aggregate ``status`` property derived from its children (see
``apps.composer.status``).
"""

import contextlib
import logging
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.composer.models import PlatformPost
from apps.credentials.models import PlatformCredential
from apps.publisher.gate_client import GateError, verify_gate
from apps.publisher.ingest_webhook import post_to_ingest
from providers import get_provider
from providers.exceptions import BlotatoStillPublishing
from providers.types import AuthType, PostType, PublishContent

from .models import PublishLog, RateLimitState

logger = logging.getLogger(__name__)

# Retry backoff schedule (in seconds)
RETRY_BACKOFF = [60, 300, 1800]  # 1min, 5min, 30min

# HTTP statuses that mean "the access token is no longer valid" — refresh the
# token and retry once rather than replaying the dead token through the normal
# exponential-backoff loop. 401 = unauthenticated, 403 = the token is valid but
# the platform rejected it as expired/revoked (LinkedIn returns 403 for some
# token states).
_AUTH_FAILURE_STATUSES = {401, 403}


def _is_auth_failure(exc: Exception) -> bool:
    """True when ``exc`` indicates the access token must be refreshed.

    Covers the two shapes the providers raise: an ``APIError`` carrying a
    401/403 ``status_code`` (the base ``_request`` helper), and the explicit
    ``TokenExpiredError`` type. Anything else (500s, rate limits, validation
    errors) is NOT an auth failure and must flow through the normal loop.
    """
    from providers.exceptions import APIError, TokenExpiredError

    if isinstance(exc, TokenExpiredError):
        return True
    if isinstance(exc, APIError):
        return exc.status_code in _AUTH_FAILURE_STATUSES
    return False


class GateBlockError(Exception):
    """Raised at the provider dispatch chokepoint when a PlatformPost is not
    cleared by the approval gate. A gate block is a terminal, non-retryable
    condition: re-publishing the identical (unapproved) content would fail
    the gate again forever, so we mark the post FAILED and do NOT schedule a
    retry. Re-approval (new gate_id + matching content_hash) is required to
    publish."""


def _resolve_publish_credentials(account):
    """Resolve the credentials dict for publishing on behalf of `account`.

    Combines org-level `PlatformCredential` (falling back to env) with
    per-account federation metadata (Mastodon `instance_url` +
    `MastodonAppRegistration`, Bluesky `pds_url`). Returns a plain dict
    suitable for `get_provider(platform, credentials)`.
    """
    platform = account.platform

    # Blotato is a single-key, multi-target provider family. Every blotato_*
    # account shares one org-level key (PlatformCredential(platform="blotato"))
    # with an env fallback. There are no per-account OAuth tokens.
    if platform.startswith("blotato_"):
        api_key = ""
        try:
            cred = PlatformCredential.objects.for_org(
                account.workspace.organization_id
            ).get(platform="blotato", is_configured=True)
            api_key = cred.credentials.get("api_key", "")
        except PlatformCredential.DoesNotExist:
            api_key = getattr(settings, "BLOTATO_API_KEY", "")
        return {"api_key": api_key}

    try:
        cred = PlatformCredential.objects.for_org(account.workspace.organization_id).get(
            platform=platform, is_configured=True
        )
        credentials = dict(cred.credentials)
    except PlatformCredential.DoesNotExist:
        env_creds = getattr(settings, "PLATFORM_CREDENTIALS_FROM_ENV", {})
        credentials = dict(env_creds.get(platform, {}))

    if platform == "mastodon" and account.instance_url:
        from apps.common.validators import is_safe_url

        if is_safe_url(account.instance_url):
            credentials["instance_url"] = account.instance_url
            if not credentials.get("client_id"):
                from apps.social_accounts.models import MastodonAppRegistration

                try:
                    reg = MastodonAppRegistration.objects.get(instance_url=account.instance_url)
                    credentials["client_id"] = reg.client_id
                    credentials["client_secret"] = reg.client_secret
                except MastodonAppRegistration.DoesNotExist:
                    pass
        else:
            logger.warning(
                "Mastodon instance URL failed SSRF check for account %s",
                account.id,
            )
    elif platform == "bluesky" and account.instance_url:
        credentials["pds_url"] = account.instance_url

    return credentials


def _looks_like_html(text: str) -> bool:
    """True when the string contains HTML markup (a tag like <p>, <strong>, <img …>).

    Used to decide whether a Ghost channel's per-channel override was authored
    in the composer's rich editor (HTML) versus typed as plain text.
    """
    import re

    return bool(re.search(r"<[a-zA-Z][^>]*>", text or ""))


def _blotato_extra(account, platform: str, extra: dict) -> None:
    """Inject per-account Blotato data into the provider content extras."""
    cfg = account.provider_config or {}
    extra["blotato_account_id"] = cfg.get("blotato_account_id") or account.account_platform_id
    if platform == "blotato_facebook" and "page_id" not in extra:
        page_id = cfg.get("page_id")
        if page_id:
            extra["page_id"] = page_id


MAX_RETRIES = 3
FIRST_COMMENT_DELAY = getattr(settings, "PUBLISHER_FIRST_COMMENT_DELAY", 120)
MAX_CONCURRENT_PUBLISHES = getattr(settings, "PUBLISHER_MAX_CONCURRENT_PUBLISHES", 10)
MAX_CONCURRENT_POSTS = getattr(settings, "PUBLISHER_MAX_CONCURRENT_POSTS", 4)


def _synchronous_publish() -> bool:
    """Run the publish fan-out inline instead of via ThreadPoolExecutor.

    The worker fans out across threads in production. Under the test suite
    those threads would open independent DB connections that cannot see the
    transaction pytest-django wraps each test in, so the gate-hook end-to-end
    test (``poll_and_publish`` → gate → mock provider) needs an inline path.
    Controlled by ``settings.PUBLISHER_SYNCHRONOUS`` (default False).
    """
    return bool(getattr(settings, "PUBLISHER_SYNCHRONOUS", False))


class PublishEngine:
    """Orchestrates the publishing of scheduled posts."""

    def poll_and_publish(self):
        """Main poll loop - find and publish due platform posts.

        Called every ~15 seconds by the background worker. Groups due
        PlatformPosts by parent Post and publishes each group.
        """
        due_pps = self._get_due_platform_posts()

        # Group by parent post_id
        groups: dict = {}
        for pp in due_pps:
            groups.setdefault(pp.post_id, []).append(pp)

        published_count = 0
        if _synchronous_publish():
            for post_id, pps in groups.items():
                try:
                    self._publish_post_group(pps[0].post, pps)
                    published_count += 1
                except Exception:
                    logger.exception("Unexpected error publishing post group %s", post_id)
        else:
            with ThreadPoolExecutor(max_workers=min(len(groups), MAX_CONCURRENT_POSTS) or 1) as executor:
                futures = {
                    executor.submit(self._publish_post_group, pps[0].post, pps): post_id
                    for post_id, pps in groups.items()
                }
                for future in as_completed(futures):
                    post_id = futures[future]
                    try:
                        future.result()
                        published_count += 1
                    except Exception:
                        logger.exception("Unexpected error publishing post group %s", post_id)

        # Always process retries, even when no new posts are due
        self._process_retries()

        return published_count

    def _get_due_platform_posts(self):
        """Find PlatformPosts due for publishing, using Coalesce fallback."""
        now = timezone.now()
        return list(
            PlatformPost.objects.filter(
                status=PlatformPost.Status.SCHEDULED,
            )
            .annotate(effective_at=Coalesce("scheduled_at", "post__scheduled_at"))
            .filter(effective_at__lte=now)
            .select_related("post__workspace", "social_account")
            .order_by("effective_at")[:MAX_CONCURRENT_PUBLISHES]
        )

    def _publish_post_group(self, post, due_pps):
        """Publish a group of due PlatformPosts belonging to the same Post.

        Grouping is purely an operational optimization (shared media download,
        shared credential resolution). Status lives on the children — the
        parent Post is not touched.
        """
        # Lock and transition each due child from SCHEDULED → PUBLISHING.
        with transaction.atomic():
            platform_posts = list(
                PlatformPost.objects.select_for_update()
                .filter(
                    post_id=post.id,
                    id__in=[pp.id for pp in due_pps],
                    status=PlatformPost.Status.SCHEDULED,
                )
                .select_related("social_account", "post__workspace")
            )

            if not platform_posts:
                return

            # Untouchable gate chokepoint: block-and-skip any child lacking a
            # valid pass/approved gate_id whose content_hash matches, BEFORE
            # the SCHEDULED → PUBLISHING transition. Covers native editor- and
            # API-composed posts alike (single chokepoint).
            platform_posts = [pp for pp in platform_posts if self._gate_ok(pp)]

            if not platform_posts:
                return

            PlatformPost.objects.filter(id__in=[pp.id for pp in platform_posts]).update(
                status=PlatformPost.Status.PUBLISHING
            )

        # Publish in parallel
        results = {}
        if _synchronous_publish():
            for pp in platform_posts:
                try:
                    results[pp.id] = self._publish_platform_post(pp)
                except Exception as e:
                    results[pp.id] = {"success": False, "error": str(e)}
        else:
            with ThreadPoolExecutor(max_workers=min(len(platform_posts), 5)) as executor:
                futures = {executor.submit(self._publish_platform_post, pp): pp for pp in platform_posts}
                for future in as_completed(futures):
                    pp = futures[future]
                    try:
                        results[pp.id] = future.result()
                    except Exception as e:
                        results[pp.id] = {"success": False, "error": str(e)}

        # Reflect the aggregate onto Post.published_at so dashboards that
        # display "last published" don't need to query every child.
        self._sync_parent_published_at(post)

        # Schedule first comments for successful publishes (non-blocking)
        for pp in platform_posts:
            pp.refresh_from_db()
            if pp.status != PlatformPost.Status.PUBLISHED:
                continue
            if not pp.social_account.supports_first_comment():
                continue
            comment_text = pp.effective_first_comment
            if comment_text:
                _post_first_comment_task.apply_async(args=[str(pp.id)], countdown=FIRST_COMMENT_DELAY)

    def _gate_failure_reason(self, platform_post) -> str | None:
        """Verify the approval gate for a PlatformPost.

        Returns ``None`` when the post is cleared to publish (valid
        pass/approved gate_id whose content_hash matches), or a human-readable
        reason string when it is blocked. Pure check — does NOT mutate state.
        """
        if platform_post.gate_bypassed:
            # Human-authored composer post — the gate is intentionally skipped
            # (operator chose direct human authorship over agent gating).
            return None
        if not platform_post.gate_id:
            return "missing gate_id"
        try:
            res = verify_gate(str(platform_post.gate_id))
        except GateError as exc:
            return f"gate verify error: {exc}"
        if res.get("verdict") not in ("pass", "approved"):
            return f"gate verdict {res.get('verdict')}"
        if res.get("content_hash") != platform_post.content_hash:
            return "content hash mismatch"
        return None

    def _gate_ok(self, platform_post) -> bool:
        """Fail-fast gate filter used in _publish_post_group BEFORE the
        SCHEDULED → PUBLISHING transition. The AUTHORITATIVE enforcement lives
        at the provider dispatch chokepoint (_dispatch_to_provider) so EVERY
        path — fresh and retry — is gated by construction; this early filter
        just lets us skip the transition for an obviously-blocked post."""
        reason = self._gate_failure_reason(platform_post)
        if reason is not None:
            self._block(platform_post, reason)
            return False
        return True

    def _block(self, platform_post, reason: str):
        platform_post.status = PlatformPost.Status.FAILED
        platform_post.publish_error = f"GATE BLOCK: {reason}"
        platform_post.save(update_fields=["status", "publish_error", "updated_at"])
        PublishLog.objects.create(
            platform_post=platform_post,
            error_message=f"GATE BLOCK: {reason}",
        )
        logger.warning("Gate blocked publish for %s: %s", platform_post.id, reason)

    def _publish_platform_post(self, platform_post):
        """Publish a single PlatformPost to its target platform.

        Returns dict: {"success": bool, "platform_post_id": str, "error": str}
        """
        start_time = time.monotonic()
        account = platform_post.social_account

        # Check rate limits
        rate_state = RateLimitState.objects.filter(
            social_account=account,
            platform=account.platform,
        ).first()

        if rate_state and rate_state.is_rate_limited:
            error_msg = f"Rate limited until {rate_state.window_resets_at}"
            self._schedule_retry(platform_post, error_msg)
            return {"success": False, "error": error_msg}

        try:
            # Get the provider for this platform (gated at the dispatch site)
            result = self._dispatch_to_provider(platform_post)

            duration_ms = int((time.monotonic() - start_time) * 1000)

            if result["success"]:
                platform_post.platform_post_id = result.get("platform_post_id", "")
                platform_post.status = PlatformPost.Status.PUBLISHED
                platform_post.published_at = timezone.now()
                platform_post.save()

                # Log success
                PublishLog.objects.create(
                    platform_post=platform_post,
                    attempt_number=platform_post.retry_count + 1,
                    status_code=result.get("status_code", 200),
                    response_body=str(result.get("response", ""))[:1000],
                    duration_ms=duration_ms,
                )

                # Update rate limit state
                self._update_rate_limit(account, result)

                # Emit publish result to agent-service /ingest (non-fatal).
                self._emit_ingest(platform_post, result)

                return result
            else:
                error_msg = result.get("error", "Unknown publish error")
                duration_ms = int((time.monotonic() - start_time) * 1000)

                PublishLog.objects.create(
                    platform_post=platform_post,
                    attempt_number=platform_post.retry_count + 1,
                    status_code=result.get("status_code"),
                    response_body=str(result.get("response", ""))[:1000],
                    error_message=error_msg,
                    duration_ms=duration_ms,
                )

                self._schedule_retry(platform_post, error_msg)
                return result

        except GateBlockError as e:
            # Terminal: _block() already set status=FAILED + logged the GATE
            # BLOCK. Do NOT schedule a retry — re-publishing identical
            # unapproved content would just fail the gate again forever.
            return {"success": False, "error": f"GATE BLOCK: {e}"}
        except BlotatoStillPublishing as e:
            # Blotato accepted the post but it's still in-progress. Park at
            # publishing + persist the submission id; the reconcile task
            # finalizes it. Never re-submit (would duplicate the post).
            platform_post.platform_post_id = e.submission_id
            platform_post.status = PlatformPost.Status.PUBLISHING
            platform_post.publish_error = ""
            platform_post.save(update_fields=["platform_post_id", "status", "publish_error", "updated_at"])
            PublishLog.objects.create(
                platform_post=platform_post,
                attempt_number=platform_post.retry_count + 1,
                error_message=f"Blotato in-progress ({e.submission_id}); awaiting reconcile",
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )
            return {"success": False, "pending": True, "platform_post_id": e.submission_id}
        except Exception as e:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            error_msg = str(e)

            PublishLog.objects.create(
                platform_post=platform_post,
                attempt_number=platform_post.retry_count + 1,
                error_message=error_msg,
                duration_ms=duration_ms,
            )

            self._schedule_retry(platform_post, error_msg)
            return {"success": False, "error": error_msg}

    def _emit_ingest(self, platform_post, result):
        """POST a successful publish result to agent-service /ingest.

        Best-effort: any misconfiguration or transport error is logged and
        swallowed so the publish path is never blocked by the ingest webhook.
        """
        if not getattr(settings, "AGENT_SERVICE_INGEST_URL", "") or not getattr(
            settings, "AGENT_SERVICE_INGEST_KEY", ""
        ):
            return
        platform_post_id = result.get("platform_post_id") or platform_post.platform_post_id
        try:
            post_to_ingest(
                source_type="webhook",
                source_id="platform_publish",
                payload={
                    "platform_post_id": platform_post_id,
                    "internal_post_id": str(platform_post.id),
                    "platform": platform_post.social_account.platform,
                    "status": platform_post.status,
                },
                dedupe_key=platform_post_id or str(platform_post.id),
            )
        except Exception:  # noqa: BLE001 - ingest is non-fatal
            logger.exception("Failed to emit publish result to /ingest for %s", platform_post.id)

    def _dispatch_to_provider(self, platform_post):
        """Dispatch to the appropriate platform provider.

        Resolves credentials, refreshes tokens if needed, builds a
        PublishContent payload, and calls provider.publish_post().
        Returns: {"success": bool, "platform_post_id": str, ...}
        """
        account = platform_post.social_account
        platform = account.platform

        # Intake sensitivity gate (before agent-service gate)
        from apps.content_intake.models import ContentIntake
        from apps.publisher.intake_gate import check_intake_gate
        try:
            _intake_item = platform_post.post.intake_source
        except ContentIntake.DoesNotExist:
            _intake_item = None
        if _intake_item is not None:
            _blocked, _reason = check_intake_gate(_intake_item)
            if _blocked:
                _full_reason = f"[INTAKE GATE] {_reason}"
                self._block(platform_post, _full_reason)
                raise GateBlockError(_full_reason)

        # Joseph-personal channel requires Joseph's explicit approval.
        # A missing approval is a normal workflow hold, not an error — transition
        # to pending_client so the post is not mis-classified as broken and does
        # not exhaust retry-count budgets or trigger error dashboards.
        if _intake_item:
            from apps.content_intake.channel_routing import requires_joseph_approval as _req_joseph
            if _req_joseph(_intake_item.channel_targets):
                if not _check_joseph_approval(platform_post):
                    platform_post.transition_to("pending_client")
                    platform_post.publish_error = "[JOSEPH GATE] Awaiting Joseph personal-channel approval"
                    platform_post.save(update_fields=["status", "publish_error", "updated_at"])
                    logger.info(
                        "Joseph gate hold for PlatformPost %s — moved to pending_client",
                        platform_post.id,
                    )
                    return

        # AUTHORITATIVE GATE CHOKEPOINT. Every publish path funnels through
        # here — fresh (_publish_post_group → _publish_platform_post) AND
        # retry (_process_retries → _publish_platform_post). Enforcing the
        # gate immediately before the provider call makes it impossible to
        # publish unapproved content by construction, regardless of how the
        # post reached this method. The early _gate_ok filter in
        # _publish_post_group is only a fail-fast; this check is the
        # source of truth. A gate block is terminal (non-retryable).
        reason = self._gate_failure_reason(platform_post)
        if reason is not None:
            self._block(platform_post, reason)
            raise GateBlockError(reason)

        credentials = _resolve_publish_credentials(account)
        provider = get_provider(platform, credentials)

        # Publish-time caption-limit guard. Some adapters (Threads, YouTube)
        # used to silently truncate over-limit text; instead reject loudly so
        # the post is never published mangled. This is the authoritative
        # backstop behind the compose-time service/API checks — it catches
        # content that was edited on the platform side, imported, or otherwise
        # reached here over-limit. A length failure is a content problem, not a
        # transient one, so it surfaces as a PublishError (logged, retried by
        # the normal loop until it exhausts and is marked FAILED).
        effective_caption = platform_post.effective_caption or ""
        if len(effective_caption) > provider.max_caption_length:
            from providers.exceptions import PublishError

            raise PublishError(
                f"Caption is {len(effective_caption)} characters but {platform} allows "
                f"at most {provider.max_caption_length}.",
                platform=platform,
            )

        # Refresh token if expired or expiring soon (OAuth2 providers only)
        access_token = account.oauth_access_token
        if account.token_expires_at and account.is_token_expiring_soon and provider.auth_type == AuthType.OAUTH2:
            try:
                new_tokens = provider.refresh_token(account.oauth_refresh_token)
                account.oauth_access_token = new_tokens.access_token
                if new_tokens.refresh_token:
                    account.oauth_refresh_token = new_tokens.refresh_token
                if new_tokens.expires_in:
                    account.token_expires_at = timezone.now() + timedelta(seconds=new_tokens.expires_in)
                account.connection_status = account.ConnectionStatus.CONNECTED
                account.save(
                    update_fields=[
                        "oauth_access_token",
                        "oauth_refresh_token",
                        "token_expires_at",
                        "connection_status",
                        "updated_at",
                    ]
                )
                access_token = new_tokens.access_token
                logger.info("Refreshed token for %s", account)
            except Exception:
                logger.exception("Token refresh failed for %s", account)

        # Download media from storage (S3/cloud) to temp files for upload
        # and collect public URLs (presigned R2 / absolute) for providers
        # that require fetchable URLs (Instagram, Threads, Google Business, etc.)
        media_files = []
        media_urls = []
        temp_files = []
        attachments = list(platform_post.post.media_attachments.select_related("media_asset").order_by("position"))

        # For video-only platforms (YouTube, TikTok), skip non-video attachments
        video_only = set(provider.supported_post_types) <= {PostType.VIDEO, PostType.SHORT}
        if video_only:
            attachments = [pm for pm in attachments if pm.media_asset.media_type == "video"]

        first_media_type = None
        app_url = getattr(settings, "APP_URL", "").rstrip("/")
        try:
            for pm in attachments:
                asset = pm.media_asset
                if not asset.file:
                    continue
                # Track the first media type for post type detection
                if first_media_type is None:
                    first_media_type = asset.media_type

                # Collect the public/presigned URL for this asset
                url = asset.file.url
                if url.startswith("/"):
                    # Local storage: make absolute using APP_URL
                    url = f"{app_url}{url}"
                media_urls.append(url)

                # Download to a temp file (works with any storage backend)
                suffix = os.path.splitext(asset.filename)[1] or ".tmp"
                tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115
                    suffix=suffix, delete=False
                )
                temp_files.append(tmp.name)
                with asset.file.open("rb") as src:
                    for chunk in iter(lambda: src.read(8192), b""):
                        tmp.write(chunk)
                tmp.close()
                media_files.append(tmp.name)

            # Merge per-platform extras (e.g. YouTube privacy_status, custom
            # tags, thumbnail) on top of the base extra dict.
            extra = {"tags": platform_post.post.tags or []}
            platform_extra = platform_post.platform_extra or {}
            extra.update(platform_extra)

            # Inject page_id for Facebook from the connected account.
            if platform == "facebook" and "page_id" not in extra:
                extra["page_id"] = account.account_platform_id

            # Inject org author URN for LinkedIn Company Page.
            if platform == "linkedin_company" and "author" not in extra:
                extra["author"] = f"urn:li:organization:{account.account_platform_id}"

            # Inject Blotato per-account data for blotato_* platforms.
            if platform.startswith("blotato_"):
                _blotato_extra(account, platform, extra)

            # Ghost (Nexus Brief): the per-channel override is authored in the
            # composer's rich editor and is HTML. Signal the provider to publish
            # it verbatim (no escaping) when the override is set on this channel.
            if (
                platform == "ghost"
                and platform_post.platform_specific_caption
                and _looks_like_html(platform_post.platform_specific_caption)
            ):
                extra["body_format"] = "html"

            # Pop link_url from extra and set on PublishContent directly
            link_url = extra.pop("link_url", None)

            # Resolve thumbnail_asset_id → temp file path for providers that
            # need to upload a custom thumbnail (YouTube).
            thumb_asset_id = extra.pop("thumbnail_asset_id", None)
            if thumb_asset_id:
                from apps.media_library.models import MediaAsset

                try:
                    thumb_asset = MediaAsset.objects.get(id=thumb_asset_id)
                    if thumb_asset.file:
                        suffix = os.path.splitext(thumb_asset.filename)[1] or ".jpg"
                        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)  # noqa: SIM115
                        temp_files.append(tmp.name)
                        with thumb_asset.file.open("rb") as src:
                            for chunk in iter(lambda: src.read(8192), b""):
                                tmp.write(chunk)
                        tmp.close()
                        extra["thumbnail_file"] = tmp.name
                except MediaAsset.DoesNotExist:
                    logger.warning("Thumbnail asset %s not found", thumb_asset_id)

            # Resolve cover_image_asset_id → temp file (Pinterest video pins)
            cover_asset_id = extra.pop("cover_image_asset_id", None)
            if cover_asset_id:
                try:
                    cover_asset = MediaAsset.objects.get(id=cover_asset_id)
                    if cover_asset.file:
                        suffix = os.path.splitext(cover_asset.filename)[1] or ".jpg"
                        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)  # noqa: SIM115
                        temp_files.append(tmp.name)
                        with cover_asset.file.open("rb") as src:
                            for chunk in iter(lambda: src.read(8192), b""):
                                tmp.write(chunk)
                        tmp.close()
                        extra["cover_image_file"] = tmp.name
                except MediaAsset.DoesNotExist:
                    logger.warning("Cover image asset %s not found", cover_asset_id)

            post_type = self._resolve_post_type(
                platform=platform,
                platform_extra=platform_extra,
                media_count=len(media_files),
                first_media_type=first_media_type,
            )

            content = PublishContent(
                text=platform_post.effective_caption or "",
                title=platform_post.effective_title,
                description=platform_post.effective_caption,
                first_comment=platform_post.effective_first_comment,
                media_files=media_files,
                media_urls=media_urls,
                post_type=post_type,
                extra=extra,
                link_url=link_url,
            )

            logger.info(
                "Publishing to %s (account: %s, type: %s, media: %d)",
                platform,
                account.account_name,
                post_type.value,
                len(media_files),
            )
            result = self._publish_with_auth_retry(provider, account, access_token, content)
            return {
                "success": True,
                "platform_post_id": result.platform_post_id,
                "url": result.url,
                "response": result.extra,
            }
        finally:
            # Clean up temp files regardless of success/failure
            for path in temp_files:
                with contextlib.suppress(OSError):
                    os.unlink(path)

    def _publish_with_auth_retry(self, provider, account, access_token, content):
        """Call ``provider.publish_post`` with a single token-refresh retry on 401.

        The pre-publish expiry check above refreshes tokens that are *known* to
        be expiring, but a token can still die between that check and the
        provider call (clock skew, early server-side revocation). When the
        publish itself comes back as an auth failure (401/403) and the account
        is an OAuth2 account with a refresh token, refresh + persist + retry the
        publish exactly ONCE. This is deliberately OUTSIDE the engine's
        exponential-backoff loop: a dead token will never recover by waiting, so
        replaying it with backoff just burns the retry budget. If there is no
        refresh token, or the single retry still fails auth, mark the account
        needs-reconnect (connection_status=ERROR) and re-raise so the caller
        logs the failure exactly as it does today.
        """
        try:
            return provider.publish_post(access_token, content)
        except Exception as exc:
            if not _is_auth_failure(exc):
                raise

            can_refresh = (
                provider.auth_type == AuthType.OAUTH2
                and bool(account.oauth_refresh_token)
            )
            if not can_refresh:
                self._mark_needs_reconnect(account, exc)
                raise

            logger.info("Publish 401 for %s — refreshing token and retrying once", account)
            try:
                new_access_token = self._refresh_account_token(provider, account)
            except Exception:
                logger.exception("Token refresh after 401 failed for %s", account)
                self._mark_needs_reconnect(account, exc)
                raise exc from None

            try:
                return provider.publish_post(new_access_token, content)
            except Exception as retry_exc:
                if _is_auth_failure(retry_exc):
                    self._mark_needs_reconnect(account, retry_exc)
                raise

    @staticmethod
    def _refresh_account_token(provider, account) -> str:
        """Refresh + persist OAuth tokens for ``account``; return the new access token.

        Mirrors the refresh+persist logic in the health-check task
        (``apps.social_accounts.tasks.check_social_account_health``) so a
        refresh triggered by a publish 401 leaves the account in the exact same
        shape a scheduled health check would.
        """
        new_tokens = provider.refresh_token(account.oauth_refresh_token)
        account.oauth_access_token = new_tokens.access_token
        if new_tokens.refresh_token:
            account.oauth_refresh_token = new_tokens.refresh_token
        if new_tokens.expires_in:
            account.token_expires_at = timezone.now() + timedelta(seconds=new_tokens.expires_in)
        account.connection_status = account.ConnectionStatus.CONNECTED
        account.last_error = ""
        account.save(
            update_fields=[
                "oauth_access_token",
                "oauth_refresh_token",
                "token_expires_at",
                "connection_status",
                "last_error",
                "updated_at",
            ]
        )
        logger.info("Refreshed token for %s after publish 401", account)
        return new_tokens.access_token

    @staticmethod
    def _mark_needs_reconnect(account, exc: Exception) -> None:
        """Flag the account ERROR (``needs_reconnect``) on a terminal auth failure."""
        account.connection_status = account.ConnectionStatus.ERROR
        account.last_error = str(exc)[:500]
        account.save(update_fields=["connection_status", "last_error", "updated_at"])
        logger.warning("Marked %s needs-reconnect after publish auth failure: %s", account, exc)

    @staticmethod
    def _resolve_post_type(
        platform: str,
        platform_extra: dict,
        media_count: int,
        first_media_type: str | None,
    ) -> PostType:
        """Derive the correct PostType from context.

        Priority:
        1. Explicit hint in platform_extra (validated against PostType enum)
        2. Platform defaults (Pinterest → PIN)
        3. Multi-media on carousel-capable platforms → CAROUSEL
        4. Fallback: video → VIDEO, image → IMAGE, else → TEXT
        """
        # 1. Explicit post_type hint from platform_extra
        hint = platform_extra.get("post_type")
        if hint:
            valid_values = {pt.value for pt in PostType}
            if hint in valid_values:
                return PostType(hint)
            logger.warning("Invalid post_type hint %r, ignoring", hint)

        # 2. Platform defaults
        if platform == "pinterest":
            return PostType.PIN

        # 3. Multi-media → CAROUSEL for Instagram/Threads
        if media_count > 1 and platform in (
            "instagram",
            "instagram_login",
            "threads",
        ):
            return PostType.CAROUSEL

        # 4. Fallback based on first media type
        if first_media_type == "video":
            return PostType.VIDEO
        if first_media_type == "image":
            return PostType.IMAGE
        return PostType.TEXT

    def _schedule_retry(self, platform_post, error_msg):
        """Schedule a retry with exponential backoff."""
        if platform_post.retry_count >= MAX_RETRIES:
            platform_post.status = PlatformPost.Status.FAILED
            platform_post.publish_error = error_msg
            platform_post.save()
            logger.warning(
                "PlatformPost %s failed after %d retries: %s",
                platform_post.id,
                MAX_RETRIES,
                error_msg,
            )
            return

        backoff_seconds = RETRY_BACKOFF[min(platform_post.retry_count, len(RETRY_BACKOFF) - 1)]
        platform_post.retry_count += 1
        platform_post.next_retry_at = timezone.now() + timedelta(seconds=backoff_seconds)
        # Drop back to SCHEDULED so the next _process_retries tick picks it up
        # once next_retry_at passes.
        platform_post.status = PlatformPost.Status.SCHEDULED
        platform_post.publish_error = error_msg
        platform_post.save()

        logger.info(
            "Scheduled retry %d for PlatformPost %s in %d seconds",
            platform_post.retry_count,
            platform_post.id,
            backoff_seconds,
        )

    def _process_retries(self):
        """Process platform posts that are due for retry.

        Uses an atomic status flip (UPDATE WHERE status=SCHEDULED) before
        calling the network publisher.  If two cycles race, only one UPDATE
        will match; the other gets 0 rows and skips, preventing double-publish.
        """
        now = timezone.now()
        retry_posts = PlatformPost.objects.filter(
            status=PlatformPost.Status.SCHEDULED,
            retry_count__gt=0,
            retry_count__lte=MAX_RETRIES,
            next_retry_at__lte=now,
        ).select_related("social_account", "post")

        for pp in retry_posts:
            try:
                # Atomic claim: only proceed if this cycle wins the race.
                claimed = PlatformPost.objects.filter(
                    status=PlatformPost.Status.SCHEDULED,
                    id=pp.id,
                ).update(status=PlatformPost.Status.PUBLISHING)
                if not claimed:
                    # Another concurrent cycle already claimed this row; skip.
                    logger.debug(
                        "PlatformPost %s already claimed by another cycle; skipping",
                        pp.id,
                    )
                    continue
                # Refresh from DB so pp.status reflects the committed update.
                pp.refresh_from_db(fields=["status"])
                result = self._publish_platform_post(pp)
                if result.get("success"):
                    self._sync_parent_published_at(pp.post)
            except Exception:
                logger.exception("Error retrying PlatformPost %s", pp.id)

    def _update_rate_limit(self, account, result):
        """Update rate limit state from API response headers."""
        remaining = result.get("rate_limit_remaining")
        resets_at = result.get("rate_limit_resets_at")

        if remaining is not None:
            RateLimitState.objects.update_or_create(
                social_account=account,
                platform=account.platform,
                defaults={
                    "requests_remaining": remaining,
                    "window_resets_at": resets_at,
                },
            )

    def _sync_parent_published_at(self, post):
        """Reflect the latest child published_at onto the parent Post.

        Status itself lives entirely on PlatformPost now (Post.status is a
        derived property), but we still maintain ``Post.published_at`` so
        dashboards/lists that show "last published" don't have to aggregate
        children at read time.
        """
        latest = max(
            (pp.published_at for pp in post.platform_posts.all() if pp.published_at),
            default=None,
        )
        if latest and post.published_at != latest:
            post.published_at = latest
            post.save(update_fields=["published_at", "updated_at"])


def _check_joseph_approval(platform_post) -> bool:
    """Return True if the post has an approval action from the principal approver.

    Identity resolution uses two stable checks applied in order:

    1. ``ContentIntake.owner_raw`` — the raw sheet value populated at import
       time (typically 'Joseph').  This avoids a user-table scan entirely and
       is the canonical approach when the intake item is available.

    2. ``settings.JOSEPH_APPROVER_EMAIL`` — a deployment-level setting that
       names the approver by their exact email address.  This is the fallback
       for posts whose intake item carries no ``owner_raw``, and is the only
       place the email address needs to change when the account is renamed.

    Both checks require an ApprovalAction.APPROVED row on the post — the
    approver's identity is verified against that row, not inferred from the
    intake owner alone.
    """
    from django.conf import settings

    from apps.approvals.models import ApprovalAction

    # Prefer matching via the intake owner_raw field (no user-table scan needed).
    try:
        intake_item = platform_post.post.intake_source
        intake_owner_raw = (intake_item.owner_raw or "").strip().lower()
    except Exception:  # noqa: BLE001 — intake_source may not exist
        intake_owner_raw = ""

    joseph_email = (getattr(settings, "JOSEPH_APPROVER_EMAIL", "") or "").strip().lower()

    # Build approval queryset once.
    approvals_qs = ApprovalAction.objects.filter(
        post=platform_post.post,
        action=ApprovalAction.ActionType.APPROVED,
    ).select_related("user")

    for action in approvals_qs:
        approver_email = (action.user.email if action.user else "").strip().lower()

        # Check 1: approver's email matches the configured principal email (exact match).
        if joseph_email and approver_email == joseph_email:
            return True

        # Check 2: approver's email matches the intake owner_raw value (exact match,
        # not a substring).  This covers cases where owner_raw holds the account
        # email or a normalised name that the approver also uses as their login.
        if intake_owner_raw and approver_email == intake_owner_raw:
            return True

    return False


# Public alias — the gate hook + slice tests refer to the engine as ``Publisher``.
Publisher = PublishEngine


@shared_task
def _post_first_comment_task(platform_post_id):
    """Post the first comment as a background task (avoids blocking the publisher thread)."""
    try:
        platform_post = PlatformPost.objects.select_related("social_account__workspace__organization").get(
            pk=platform_post_id
        )
    except PlatformPost.DoesNotExist:
        logger.warning("PlatformPost %s not found for first comment.", platform_post_id)
        return

    comment_text = platform_post.effective_first_comment
    if not comment_text:
        return

    # Re-verify the approval gate for the parent post before publishing the
    # first comment. Editing first_comment clears the gate (FIX C), so a
    # mutated comment's parent will fail this check; we also re-verify here so
    # the comment can never reach the provider without a live pass/approved
    # verdict on a present gate_id.
    if not platform_post.gate_id:
        logger.warning(
            "Skipping first comment for %s: parent has no gate_id", platform_post.id
        )
        return
    try:
        gate_res = verify_gate(str(platform_post.gate_id))
    except GateError as exc:
        logger.warning(
            "Skipping first comment for %s: gate verify error: %s",
            platform_post.id,
            exc,
        )
        return
    if gate_res.get("verdict") not in ("pass", "approved"):
        logger.warning(
            "Skipping first comment for %s: gate verdict %s",
            platform_post.id,
            gate_res.get("verdict"),
        )
        return

    account = platform_post.social_account
    try:
        credentials = _resolve_publish_credentials(account)
        provider = get_provider(account.platform, credentials)
        provider.publish_comment(
            access_token=account.oauth_access_token,
            post_id=platform_post.platform_post_id,
            text=comment_text,
        )
        logger.info("Posted first comment for PlatformPost %s", platform_post.id)
    except NotImplementedError:
        logger.info("First comment not supported for %s", account.platform)
    except Exception:
        logger.exception("Failed to post first comment for PlatformPost %s", platform_post.id)
