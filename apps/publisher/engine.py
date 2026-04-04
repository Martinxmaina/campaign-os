"""Publishing Engine — background worker logic (F-2.4).

This module implements the core publish loop:
1. Poll for posts where scheduled_at <= now() and status = 'scheduled'.
2. Transition to 'publishing'.
3. Dispatch platform posts in parallel.
4. Handle retries with exponential backoff.
5. Post first comment after 5-second delay.
6. Update statuses and log results.
"""

import logging
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta

from background_task import background
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.composer.models import PlatformPost, Post
from apps.credentials.models import PlatformCredential
from providers import get_provider
from providers.types import PostType, PublishContent

from .models import PublishLog, RateLimitState

logger = logging.getLogger(__name__)

# Retry backoff schedule (in seconds)
RETRY_BACKOFF = [60, 300, 1800]  # 1min, 5min, 30min
MAX_RETRIES = 3
FIRST_COMMENT_DELAY = getattr(settings, "PUBLISHER_FIRST_COMMENT_DELAY", 5)
MAX_CONCURRENT_PUBLISHES = getattr(settings, "PUBLISHER_MAX_CONCURRENT_PUBLISHES", 10)
MAX_CONCURRENT_POSTS = getattr(settings, "PUBLISHER_MAX_CONCURRENT_POSTS", 4)


class PublishEngine:
    """Orchestrates the publishing of scheduled posts."""

    def poll_and_publish(self):
        """Main poll loop — find and publish due posts.

        Called every ~15 seconds by the background worker.
        """
        due_posts = self._get_due_posts()

        published_count = 0
        with ThreadPoolExecutor(max_workers=min(len(due_posts), MAX_CONCURRENT_POSTS) or 1) as executor:
            futures = {executor.submit(self._publish_post, post): post for post in due_posts}
            for future in as_completed(futures):
                post = futures[future]
                try:
                    future.result()
                    published_count += 1
                except Exception:
                    logger.exception("Unexpected error publishing post %s", post.id)

        # Always process retries, even when no new posts are due
        self._process_retries()

        return published_count

    def _get_due_posts(self):
        """Find posts due for publishing."""
        now = timezone.now()
        return list(
            Post.objects.filter(
                status=Post.Status.SCHEDULED,
                scheduled_at__lte=now,
            )
            .select_related("workspace")
            .prefetch_related("platform_posts__social_account")[:MAX_CONCURRENT_PUBLISHES]
        )

    def _publish_post(self, post):
        """Publish a single post across all its target platforms."""
        # Transition post and platform posts atomically to prevent duplicate publishing
        with transaction.atomic():
            post = Post.objects.select_for_update().get(id=post.id)
            if post.status != Post.Status.SCHEDULED:
                return  # Already picked up by another worker
            post.transition_to(Post.Status.PUBLISHING)
            post.save()

            platform_posts = list(
                post.platform_posts.select_for_update()
                .filter(publish_status=PlatformPost.PublishStatus.PENDING)
                .select_related("social_account")
            )

            if not platform_posts:
                post.transition_to(Post.Status.FAILED)
                post.save()
                return

            PlatformPost.objects.filter(
                id__in=[pp.id for pp in platform_posts]
            ).update(publish_status=PlatformPost.PublishStatus.PUBLISHING)

        # Publish in parallel
        results = {}
        with ThreadPoolExecutor(max_workers=min(len(platform_posts), 5)) as executor:
            futures = {executor.submit(self._publish_platform_post, pp): pp for pp in platform_posts}
            for future in as_completed(futures):
                pp = futures[future]
                try:
                    results[pp.id] = future.result()
                except Exception as e:
                    results[pp.id] = {"success": False, "error": str(e)}

        # Determine overall post status
        successes = sum(1 for r in results.values() if r.get("success"))
        failures = sum(1 for r in results.values() if not r.get("success"))

        if failures == 0:
            post.transition_to(Post.Status.PUBLISHED)
            post.published_at = timezone.now()
        elif successes > 0:
            post.status = Post.Status.PARTIALLY_PUBLISHED
            post.published_at = timezone.now()
        else:
            post.status = Post.Status.FAILED

        post.save()

        # Schedule first comments for successful publishes (non-blocking)
        for pp in platform_posts:
            pp.refresh_from_db()
            if pp.publish_status == PlatformPost.PublishStatus.PUBLISHED:
                comment_text = pp.effective_first_comment
                if comment_text:
                    _post_first_comment_task(str(pp.id), schedule=FIRST_COMMENT_DELAY)

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
            # Get the provider for this platform
            result = self._dispatch_to_provider(platform_post)

            duration_ms = int((time.monotonic() - start_time) * 1000)

            if result["success"]:
                platform_post.platform_post_id = result.get("platform_post_id", "")
                platform_post.publish_status = PlatformPost.PublishStatus.PUBLISHED
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

    def _dispatch_to_provider(self, platform_post):
        """Dispatch to the appropriate platform provider.

        Resolves credentials, refreshes tokens if needed, builds a
        PublishContent payload, and calls provider.publish_post().
        Returns: {"success": bool, "platform_post_id": str, ...}
        """
        account = platform_post.social_account
        platform = account.platform

        # Resolve app credentials (org-specific first, then env fallback)
        try:
            cred = PlatformCredential.objects.for_org(
                account.workspace.organization_id
            ).get(platform=platform, is_configured=True)
            credentials = cred.credentials
        except PlatformCredential.DoesNotExist:
            env_creds = getattr(settings, "PLATFORM_CREDENTIALS_FROM_ENV", {})
            credentials = env_creds.get(platform, {})

        provider = get_provider(platform, credentials)

        # Refresh token if expired or expiring soon
        access_token = account.oauth_access_token
        if account.token_expires_at and account.is_token_expiring_soon:
            try:
                new_tokens = provider.refresh_token(account.oauth_refresh_token)
                account.oauth_access_token = new_tokens.access_token
                if new_tokens.refresh_token:
                    account.oauth_refresh_token = new_tokens.refresh_token
                if new_tokens.expires_in:
                    account.token_expires_at = timezone.now() + timedelta(
                        seconds=new_tokens.expires_in
                    )
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
        media_files = []
        temp_files = []
        attachments = list(
            platform_post.post.media_attachments.select_related("media_asset")
            .order_by("position")
        )

        post_type = PostType.TEXT
        try:
            for pm in attachments:
                asset = pm.media_asset
                if not asset.file:
                    continue
                # Determine post type from first media asset
                if not media_files:
                    if asset.media_type == "video":
                        post_type = PostType.VIDEO
                    elif asset.media_type == "image":
                        post_type = PostType.IMAGE

                # Download to a temp file (works with any storage backend)
                suffix = os.path.splitext(asset.filename)[1] or ".tmp"
                tmp = tempfile.NamedTemporaryFile(
                    suffix=suffix, delete=False
                )
                temp_files.append(tmp.name)
                with asset.file.open("rb") as src:
                    for chunk in iter(lambda: src.read(8192), b""):
                        tmp.write(chunk)
                tmp.close()
                media_files.append(tmp.name)

            content = PublishContent(
                text=platform_post.effective_caption or "",
                title=platform_post.effective_title,
                description=platform_post.effective_caption,
                first_comment=platform_post.effective_first_comment,
                media_files=media_files,
                post_type=post_type,
                extra={"tags": platform_post.post.tags or []},
            )

            logger.info(
                "Publishing to %s (account: %s)",
                platform,
                account.account_name,
            )
            result = provider.publish_post(access_token, content)
            return {
                "success": True,
                "platform_post_id": result.platform_post_id,
                "url": result.url,
                "response": result.extra,
            }
        finally:
            # Clean up temp files regardless of success/failure
            for path in temp_files:
                try:
                    os.unlink(path)
                except OSError:
                    pass

    def _schedule_retry(self, platform_post, error_msg):
        """Schedule a retry with exponential backoff."""
        if platform_post.retry_count >= MAX_RETRIES:
            platform_post.publish_status = PlatformPost.PublishStatus.FAILED
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
        platform_post.publish_status = PlatformPost.PublishStatus.PENDING
        platform_post.publish_error = error_msg
        platform_post.save()

        logger.info(
            "Scheduled retry %d for PlatformPost %s in %d seconds",
            platform_post.retry_count,
            platform_post.id,
            backoff_seconds,
        )

    def _process_retries(self):
        """Process platform posts that are due for retry."""
        now = timezone.now()
        retry_posts = PlatformPost.objects.filter(
            publish_status=PlatformPost.PublishStatus.PENDING,
            retry_count__gt=0,
            retry_count__lte=MAX_RETRIES,
            next_retry_at__lte=now,
        ).select_related("social_account", "post")

        for pp in retry_posts:
            try:
                result = self._publish_platform_post(pp)
                if result.get("success"):
                    # Check if all platform posts for the parent are now done
                    self._update_parent_post_status(pp.post)
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

    def _update_parent_post_status(self, post):
        """Update parent Post status based on all PlatformPost statuses."""
        platform_posts = post.platform_posts.all()
        statuses = set(platform_posts.values_list("publish_status", flat=True))

        if statuses == {"published"}:
            post.status = Post.Status.PUBLISHED
            post.published_at = timezone.now()
        elif "published" in statuses and ("failed" in statuses or "pending" in statuses):
            post.status = Post.Status.PARTIALLY_PUBLISHED
        elif statuses == {"failed"}:
            post.status = Post.Status.FAILED
        # If still pending/publishing, leave as-is

        post.save()


@background(schedule=0)
def _post_first_comment_task(platform_post_id):
    """Post the first comment as a background task (avoids blocking the publisher thread)."""
    try:
        platform_post = PlatformPost.objects.select_related(
            "social_account__workspace__organization"
        ).get(pk=platform_post_id)
    except PlatformPost.DoesNotExist:
        logger.warning("PlatformPost %s not found for first comment.", platform_post_id)
        return

    comment_text = platform_post.effective_first_comment
    if not comment_text:
        return

    account = platform_post.social_account
    try:
        try:
            cred = PlatformCredential.objects.for_org(
                account.workspace.organization_id
            ).get(platform=account.platform, is_configured=True)
            credentials = cred.credentials
        except PlatformCredential.DoesNotExist:
            env_creds = getattr(settings, "PLATFORM_CREDENTIALS_FROM_ENV", {})
            credentials = env_creds.get(account.platform, {})

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
