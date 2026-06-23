from pathlib import Path
from urllib.parse import urlparse

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
    APP_URL=(str, "http://localhost:8000"),
    STORAGE_BACKEND=(str, "local"),
    EMAIL_BACKEND_TYPE=(str, "smtp"),
    SENTRY_DSN=(str, ""),
    REDIS_URL=(str, ""),
    SITE_NAME=(str, "WAIIS Dispatch"),
    SOURCE_REPO_URL=(str, "https://github.com/africacen/campaign-os"),
    # Stable identity for the principal approver who must sign off on
    # Joseph-personal channel posts.  Set via env var in production so that a
    # rename or email change is a single config update with no code change.
    JOSEPH_APPROVER_EMAIL=(str, ""),
)

environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
APP_URL = env("APP_URL")

# Branding / AGPL source-availability
SITE_NAME = env("SITE_NAME")
SOURCE_REPO_URL = env("SOURCE_REPO_URL")

# Principal approver for Joseph-personal channel posts.
# Overridden via JOSEPH_APPROVER_EMAIL env var in production.
JOSEPH_APPROVER_EMAIL = env("JOSEPH_APPROVER_EMAIL")

# Blotato multi-platform publishing (add-on providers). One workspace API key;
# falls back here when no org-level PlatformCredential(platform="blotato") exists.
BLOTATO_API_KEY = env("BLOTATO_API_KEY", default="")
BLOTATO_API_BASE = env("BLOTATO_API_BASE", default="https://backend.blotato.com/v2")
BLOTATO_PUBLISH_TIMEOUT = env.int("BLOTATO_PUBLISH_TIMEOUT", default=30)  # inline poll budget (s)
BLOTATO_POLL_INTERVAL = env.int("BLOTATO_POLL_INTERVAL", default=2)  # seconds between polls

# Application definition

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django.contrib.humanize",
]

THIRD_PARTY_APPS = [
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "django_htmx",
    "tailwind",
    "csp",
]

LOCAL_APPS = [
    "apps.common",
    "apps.accounts",
    "apps.organizations",
    "apps.workspaces",
    "apps.members",
    "apps.settings_manager",
    "apps.credentials",
    "apps.social_accounts",
    "apps.media_library",
    "apps.composer",
    "apps.calendar",
    "apps.publisher",
    "apps.notifications",
    "apps.inbox",
    "apps.approvals",
    # WAIIS single-tenant fork: client_portal + onboarding apps removed
    # (multi-tenant client-facing surfaces). Intelligence kept installed
    # for migration consistency but its billing/checkout surface is never
    # mounted — INTELLIGENCE_ENABLED stays False (no env vars), so URLs +
    # templates short-circuit and no Stripe / checkout routes exist.
    "apps.intelligence",
    "apps.api_keys",
    "apps.api",
    "apps.mcp",
    "apps.analytics",
    "apps.content_intake",
    "apps.evals",
    "apps.joseph",
    "apps.crm",
    "apps.outreach",
    "apps.decks",
    "theme",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "apps.accounts.middleware.AuthRateLimitMiddleware",
    "apps.accounts.middleware.TosAcceptanceMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "apps.members.middleware.RBACMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "csp.middleware.CSPMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.notifications.context_processors.unread_notification_count",
                "apps.common.context_processors.sidebar_context",
                "apps.common.context_processors.branding",
                "apps.common.context_processors.joseph_access",
                "apps.common.context_processors.crm_access",
                "apps.intelligence.context_processors.intelligence_flag",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Cache (used by rate limiting, session fallback)
REDIS_URL = env("REDIS_URL")
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }

# Database
DATABASES = {
    "default": env.db("DATABASE_URL", default="postgres://postgres:postgres@localhost:5432/campaign_os"),
}

# Custom user model
AUTH_USER_MODEL = "accounts.User"

# Agent API trusted-proxy list — IPs whose ``X-Forwarded-For`` header we
# will honour for client-IP derivation in the rate-limit throttle and
# audit log. Empty by default so the API uses ``REMOTE_ADDR`` directly,
# which is the only safe choice when the app is reached without a
# trusted proxy in front. Set ``BB_TRUSTED_PROXIES`` in the environment
# (comma-separated) when you run the app behind Cloudflare, an ALB,
# nginx, etc.
BB_TRUSTED_PROXIES = tuple(p.strip() for p in env.list("BB_TRUSTED_PROXIES", default=[]) if p.strip())

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
]

# Password hashing - bcrypt with cost factor 12
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Media files
STORAGE_BACKEND = env("STORAGE_BACKEND")
if STORAGE_BACKEND.lower() == "s3":
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
    }
    AWS_S3_ENDPOINT_URL = env("S3_ENDPOINT_URL", default="")
    AWS_ACCESS_KEY_ID = env("S3_ACCESS_KEY_ID", default="")
    AWS_SECRET_ACCESS_KEY = env("S3_SECRET_ACCESS_KEY", default="")
    AWS_STORAGE_BUCKET_NAME = env("S3_BUCKET_NAME", default="")
    AWS_S3_CUSTOM_DOMAIN = env("S3_CUSTOM_DOMAIN", default="")
    AWS_S3_REGION_NAME = env("S3_REGION_NAME", default="auto")
    AWS_S3_FILE_OVERWRITE = False
    AWS_DEFAULT_ACL = "private"
    AWS_QUERYSTRING_AUTH = True
    AWS_QUERYSTRING_EXPIRE = 3600  # 1-hour expiry for presigned URLs
    AWS_S3_OBJECT_PARAMETERS = {
        "CacheControl": "max-age=86400",
    }
else:
    # Local FS fallback so dev + test environments without S3 credentials
    # can still call default_storage / save uploaded files.
    STORAGES["default"] = {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    }
    MEDIA_ROOT = env("MEDIA_ROOT", default=str(BASE_DIR / "media"))
    MEDIA_URL = "/media/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Sites framework
SITE_ID = 1

# django-allauth
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*"]
ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_EMAIL_SUBJECT_PREFIX = ""
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
LOGIN_REDIRECT_URL = "/"
ACCOUNT_LOGOUT_REDIRECT_URL = "/accounts/login/"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

# Google OAuth for user login/signup (separate from PLATFORM_GOOGLE_* used for publishing)
GOOGLE_AUTH_CLIENT_ID = env("GOOGLE_AUTH_CLIENT_ID", default="")
GOOGLE_AUTH_CLIENT_SECRET = env("GOOGLE_AUTH_CLIENT_SECRET", default="")

# Google Sheets content-intake sync
# OAuth2 (preferred — works even when org policy blocks service-account keys)
GOOGLE_SHEETS_CLIENT_ID = env.str("GOOGLE_SHEETS_CLIENT_ID", default="")
GOOGLE_SHEETS_CLIENT_SECRET = env.str("GOOGLE_SHEETS_CLIENT_SECRET", default="")
GOOGLE_SHEETS_REFRESH_TOKEN = env.str("GOOGLE_SHEETS_REFRESH_TOKEN", default="")
# Fallback: service-account JSON (one line). Used only when OAuth2 vars are not set.
GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON = env.str("GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON", default="")
CONTENT_INTAKE_SHEET_ID = env.str("CONTENT_INTAKE_SHEET_ID", default="")
CONTENT_INTAKE_SHEET_RANGE = env.str("CONTENT_INTAKE_SHEET_RANGE", default="Sheet1!A:P")
# CRM tracker mirror (read-WRITE): daily mirror of the live pipeline into a
# DEDICATED tab of the team's Google Sheet. Writing requires the GOOGLE_SHEETS_*
# token to carry the `spreadsheets` (read-write) scope — a re-consent.
CRM_TRACKER_SHEET_ID = env.str("CRM_TRACKER_SHEET_ID", default="")
CRM_TRACKER_TAB = env.str("CRM_TRACKER_TAB", default="Campaign OS — Pipeline")
# DEFERRED: write-back support (updating the sheet's Status column after a
# ContentIntake row is promoted / published) is not yet implemented.
# This flag is declared here and in .env.example so the feature can be
# activated without a settings change when the writeback path is built.
# Until then it must remain False and must not be read anywhere — any
# code that checks this flag should be added only alongside the
# corresponding writeback implementation.
CONTENT_INTAKE_WRITEBACK_ENABLED = env.bool("CONTENT_INTAKE_WRITEBACK_ENABLED", default=False)

SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "APP": {
            "client_id": GOOGLE_AUTH_CLIENT_ID,
            "secret": GOOGLE_AUTH_CLIENT_SECRET,
        },
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
        "VERIFIED_EMAIL": True,
    },
}

SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_LOGIN_ON_GET = False
SOCIALACCOUNT_ADAPTER = "apps.accounts.adapters.SocialAccountAdapter"

# Sessions
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = 14 * 24 * 60 * 60  # 14 days
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_SAVE_EVERY_REQUEST = True  # Sliding window

# Email
EMAIL_BACKEND_TYPE = env("EMAIL_BACKEND_TYPE")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@localhost")

if EMAIL_BACKEND_TYPE == "smtp":
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = env("EMAIL_HOST", default="localhost")
    EMAIL_PORT = env.int("EMAIL_PORT", default=587)
    EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
    EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
    EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Tailwind
TAILWIND_APP_NAME = "theme"

# CSP - Alpine.js standard build requires unsafe-eval for inline expression
# evaluation. Styles use unsafe-inline because Tailwind utility classes are inline.
CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = ("'self'", "'unsafe-eval'", "https://cdn.jsdelivr.net")
CSP_STYLE_SRC = ("'self'", "'unsafe-inline'", "https://cdn.jsdelivr.net")
CSP_IMG_SRC = ("'self'", "data:", "blob:", "https:")
CSP_FONT_SRC = ("'self'",)
CSP_CONNECT_SRC = ("'self'", "https://cdn.jsdelivr.net")
CSP_MEDIA_SRC = ("'self'", "blob:")
CSP_FORM_ACTION = (
    "'self'",
    "https://accounts.google.com",
    "https://checkout.stripe.com",
    "https://billing.stripe.com",
    "https://www.facebook.com",
    "https://api.instagram.com",
    "https://www.instagram.com",
    "https://www.threads.com",
    "https://threads.net",
    "https://www.linkedin.com",
    "https://www.pinterest.com",
    "https://www.tiktok.com",
)
CSP_INCLUDE_NONCE_IN = ["script-src"]

# Allow media/images from the storage domain in CSP
if STORAGE_BACKEND.lower() == "s3":
    _storage_origin = AWS_S3_CUSTOM_DOMAIN or AWS_S3_ENDPOINT_URL
    if _storage_origin:
        if not _storage_origin.startswith("https://"):
            _storage_origin = f"https://{_storage_origin}"
        _parsed = urlparse(_storage_origin)
        _storage_origin = f"{_parsed.scheme}://{_parsed.hostname}"
        CSP_MEDIA_SRC = (*CSP_MEDIA_SRC, _storage_origin)  # type: ignore[assignment]
        CSP_IMG_SRC = (*CSP_IMG_SRC, _storage_origin)  # type: ignore[assignment]

# Media Library
MEDIA_LIBRARY_MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20MB
MEDIA_LIBRARY_MAX_VIDEO_SIZE = 1024 * 1024 * 1024  # 1GB
MEDIA_LIBRARY_MAX_BULK_UPLOAD = 50
MEDIA_LIBRARY_THUMBNAIL_SIZE = (400, 400)
MEDIA_LIBRARY_FFMPEG_TIMEOUT = 300  # 5 minutes
MEDIA_LIBRARY_MAX_CONCURRENT_TRANSCODES = 2

# Storage quota — bounds the total bytes a single Organization can
# accumulate in the media library. Without this, an Agent API key with
# ``upload_media`` permission could fill the bucket unbounded.
#
# Resolution order at runtime (high → low precedence):
#   1. OrgSetting ``media.storage_quota_bytes_override`` (manual support
#      exception or enterprise contract).
#   2. ``STORAGE_QUOTA_TIERS[IntelligenceSubscription.plan_slug]``.
#   3. ``STORAGE_QUOTA_DEFAULT``.
# See ``apps.media_library.quotas.resolve_storage_quota``.
STORAGE_QUOTA_ENABLED = env.bool("STORAGE_QUOTA_ENABLED", default=True)
STORAGE_QUOTA_TIERS = {
    # plan_slug → bytes. Slugs must match values produced by Intelligence.
    "hobby": 5 * 1024**3,  # 5 GB
    "creator": 50 * 1024**3,  # 50 GB
    "agency": 500 * 1024**3,  # 500 GB
}
STORAGE_QUOTA_DEFAULT = 5 * 1024**3  # 5 GB fallback for orgs without an active subscription

# Encryption key derivation salt - MUST be set per-deployment via environment
ENCRYPTION_KEY_SALT = env("ENCRYPTION_KEY_SALT", default="").encode("utf-8") or None

# Sentry
SENTRY_DSN = env("SENTRY_DSN")
if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        traces_sample_rate=0.1,
        profiles_sample_rate=0.1,
    )

# Mock provider — a deterministic, network-free publish path used by the
# test suite and the slice acceptance flow. Off by default so it can never
# reach a real deployment by accident; flipped on in the test settings and
# (optionally) via the ENABLE_MOCK_PROVIDER env var for local acceptance runs.
ENABLE_MOCK_PROVIDER = env.bool("ENABLE_MOCK_PROVIDER", default=False)

# Platform credentials env vars (cloud version)
_META_CREDENTIALS = {
    "app_id": env("PLATFORM_FACEBOOK_APP_ID", default=""),
    "app_secret": env("PLATFORM_FACEBOOK_APP_SECRET", default=""),
}
_GOOGLE_CREDENTIALS = {
    "client_id": env("PLATFORM_GOOGLE_CLIENT_ID", default=""),
    "client_secret": env("PLATFORM_GOOGLE_CLIENT_SECRET", default=""),
}
_INSTAGRAM_LOGIN_CREDENTIALS = {
    "app_id": env("PLATFORM_INSTAGRAM_APP_ID", default=""),
    "app_secret": env("PLATFORM_INSTAGRAM_APP_SECRET", default=""),
}
_LINKEDIN_LEGACY_CLIENT_ID = env("PLATFORM_LINKEDIN_CLIENT_ID", default="")
_LINKEDIN_LEGACY_CLIENT_SECRET = env("PLATFORM_LINKEDIN_CLIENT_SECRET", default="")

# LinkedIn Company always uses Community Management API scopes (the only path that
# works for Company Pages). Falls back to legacy shared creds for backward compat.
_LINKEDIN_COMPANY_CREDENTIALS = {
    "client_id": env("PLATFORM_LINKEDIN_COMPANY_CLIENT_ID", default="") or _LINKEDIN_LEGACY_CLIENT_ID,
    "client_secret": env("PLATFORM_LINKEDIN_COMPANY_CLIENT_SECRET", default="") or _LINKEDIN_LEGACY_CLIENT_SECRET,
}

# LinkedIn Personal credential resolution + auto-derived OAuth mode:
#   1. PLATFORM_LINKEDIN_PERSONAL_* set -> dedicated personal app -> OIDC + Share scopes
#      (the only personal-posting tier obtainable without CM approval)
#   2. Else, reuse the company app -> CM scopes (refresh tokens + inbox supported)
#   3. Else, empty placeholder
# `_oauth_mode` is computed here, never user-set; it lives in the credentials dict
# so the provider can branch on it without importing settings.
_LINKEDIN_PERSONAL_CLIENT_ID = env("PLATFORM_LINKEDIN_PERSONAL_CLIENT_ID", default="")
if _LINKEDIN_PERSONAL_CLIENT_ID:
    _LINKEDIN_PERSONAL_CREDENTIALS = {
        "client_id": _LINKEDIN_PERSONAL_CLIENT_ID,
        "client_secret": env("PLATFORM_LINKEDIN_PERSONAL_CLIENT_SECRET", default=""),
        "_oauth_mode": "oidc",
    }
elif _LINKEDIN_COMPANY_CREDENTIALS["client_id"]:
    _LINKEDIN_PERSONAL_CREDENTIALS = {
        **_LINKEDIN_COMPANY_CREDENTIALS,
        "_oauth_mode": "community_management",
    }
else:
    # No LinkedIn env vars set. Keep `_oauth_mode` out so the dict's values are all
    # falsy and `_get_configured_platforms()` doesn't false-positive (it treats any
    # truthy credential value as "configured"). The provider defaults to OIDC mode
    # via `_is_oidc_mode` if it ever sees an empty credentials dict.
    _LINKEDIN_PERSONAL_CREDENTIALS = {"client_id": "", "client_secret": ""}

_TWITTER_CREDENTIALS = {
    "client_id": env("PLATFORM_TWITTER_CLIENT_ID", default=""),
    "client_secret": env("PLATFORM_TWITTER_CLIENT_SECRET", default=""),
}

PLATFORM_CREDENTIALS_FROM_ENV = {
    # Meta platforms - Facebook, Instagram, and Threads share the same app
    "facebook": _META_CREDENTIALS,
    "instagram": _META_CREDENTIALS,
    "threads": _META_CREDENTIALS,
    # Instagram (Direct) - uses Instagram Login with separate Instagram App credentials.
    # Despite the platform key, this targets Professional (Business/Creator) IG accounts
    # without requiring a linked Facebook Page. See providers/instagram_login.py.
    "instagram_login": _INSTAGRAM_LOGIN_CREDENTIALS,
    # LinkedIn - personal can run on its own OIDC + Share app (Path A) or reuse the
    # company app's Community Management API credentials (Path B). See README.
    "linkedin_personal": _LINKEDIN_PERSONAL_CREDENTIALS,
    "linkedin_company": _LINKEDIN_COMPANY_CREDENTIALS,
    # Google platform - YouTube OAuth client
    "youtube": _GOOGLE_CREDENTIALS,
    # X/Twitter OAuth 2.0 client
    "twitter": _TWITTER_CREDENTIALS,
}

# Ghost (Nexus Brief) — single org-level Admin API key (no per-user OAuth).
# Added conditionally so _get_configured_platforms() doesn't false-positive on
# empty defaults; the credential store can still hold per-org creds either way.
if env("GHOST_ADMIN_API_KEY", default=""):
    PLATFORM_CREDENTIALS_FROM_ENV["ghost"] = {
        "admin_api_key": env("GHOST_ADMIN_API_KEY"),
        "base_url": env("GHOST_BASE_URL", default="https://the-nexus-brief.ghost.io"),
        "newsletter_slug": env("GHOST_NEWSLETTER_SLUG", default=""),
    }

# Webhook verification
FACEBOOK_WEBHOOK_VERIFY_TOKEN = env("FACEBOOK_WEBHOOK_VERIFY_TOKEN", default="")
INSTAGRAM_LOGIN_WEBHOOK_VERIFY_TOKEN = env("INSTAGRAM_LOGIN_WEBHOOK_VERIFY_TOKEN", default="")
YOUTUBE_WEBHOOK_SECRET = env("YOUTUBE_WEBHOOK_SECRET", default="")

# Rate limiting
RATELIMIT_ENABLE = not DEBUG
RATELIMIT_USE_CACHE = "default"


# ---------------------------------------------------------------------------
# Intelligence integration (optional hosted SaaS)
# ---------------------------------------------------------------------------
# All five env vars must be set for the integration to be active. Missing
# any one → INTELLIGENCE_ENABLED is False and the entire surface is hidden:
# no left-nav item, no /orgs/<id>/intelligence/ URLs, no /intelligence/
# routes. Self-hosters who don't set these get vanilla OSS Studio.
INTELLIGENCE_INTERNAL_URL = env("INTELLIGENCE_INTERNAL_URL", default="")
INTELLIGENCE_PUBLIC_URL = env("INTELLIGENCE_PUBLIC_URL", default="")
STUDIO_DEPLOYMENT_ID = env("STUDIO_DEPLOYMENT_ID", default="")
STUDIO_SHARED_SECRET = env("STUDIO_SHARED_SECRET", default="")
STUDIO_BASE_URL = env("STUDIO_BASE_URL", default="")

# agent-service gate client (HMAC-signed publish gate). Base URL of the
# agent-service exposing GET /gate/verify/{id}. Signed with STUDIO_SHARED_SECRET
# and identified by STUDIO_DEPLOYMENT_ID.
AGENT_SERVICE_BASE_URL = env("AGENT_SERVICE_BASE_URL", default="")

# Bearer token (JWT for a dedicated 'platform' agent-service user) used by the
# shared console client (apps/common/agent_client.py) to read/act over HTTP.
AGENT_SERVICE_TOKEN = env("AGENT_SERVICE_TOKEN", default="")

# agent-service ingest webhook (publish/inbox/analytics events → /ingest).
# Authenticated with a per-feed key in the X-Ingest-Key header (Phase 0
# contract), distinct from the HMAC-signed gate-verify path above.
AGENT_SERVICE_INGEST_URL = env("AGENT_SERVICE_INGEST_URL", default="")
AGENT_SERVICE_INGEST_KEY = env("AGENT_SERVICE_INGEST_KEY", default="")

# --- Celery -------------------------------------------------------------
from config.celery import build_broker_url  # noqa: E402

CELERY_BROKER_URL = build_broker_url(REDIS_URL)
CELERY_RESULT_BACKEND = build_broker_url(REDIS_URL)
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_TIME_LIMIT = 600       # hard kill at 10 min
CELERY_TASK_SOFT_TIME_LIMIT = 540  # SoftTimeLimitExceeded at 9 min
CELERY_TASK_DEFAULT_RETRY_DELAY = 30
CELERY_TASK_ALWAYS_EAGER = False
from jobs.schedules import BEAT_SCHEDULE  # noqa: E402

CELERY_BEAT_SCHEDULE = BEAT_SCHEDULE

INTELLIGENCE_ENABLED = all(
    [
        INTELLIGENCE_INTERNAL_URL.strip(),
        INTELLIGENCE_PUBLIC_URL.strip(),
        STUDIO_DEPLOYMENT_ID.strip(),
        STUDIO_SHARED_SECRET.strip(),
        STUDIO_BASE_URL.strip(),
    ]
)

if INTELLIGENCE_ENABLED:
    # Security invariants — raised (not asserted) because ``python -O``
    # strips assertions. Open-redirect defense + Stripe success-URL
    # constraint + bearer-key-transit confidentiality all depend on
    # these being enforced at boot rather than per-request.
    from urllib.parse import urlparse as _urlparse

    from django.core.exceptions import ImproperlyConfigured

    if not STUDIO_BASE_URL.startswith("https://"):
        raise ImproperlyConfigured("STUDIO_BASE_URL must be https:// when Intelligence is enabled.")

    # The Intelligence URLs carry sensitive material in BOTH directions:
    # /activate-commit and /rotate-key return plaintext API keys in the
    # response body, and every /v1/* tool call sends the per-org bearer
    # in the Authorization header. Plain http would leak both to any
    # observer on the wire. Require https:// in production while still
    # allowing http://localhost or http://127.0.0.1 for local dev (the
    # ngrok-fronted Studio talks to a loopback Intelligence over plain
    # HTTP — same machine, same kernel, no wire to observe).
    def _is_secure_intelligence_url(url: str) -> bool:
        if url.startswith("https://"):
            return True
        try:
            host = (_urlparse(url).hostname or "").lower()
        except ValueError:
            return False
        return host in {"localhost", "127.0.0.1", "::1"}

    for _name, _url in (
        ("INTELLIGENCE_INTERNAL_URL", INTELLIGENCE_INTERNAL_URL),
        ("INTELLIGENCE_PUBLIC_URL", INTELLIGENCE_PUBLIC_URL),
    ):
        if not _is_secure_intelligence_url(_url):
            raise ImproperlyConfigured(
                f"{_name} must be https:// (http:// is only accepted for "
                f"localhost / 127.0.0.1 dev tunnels) — current value would "
                f"leak Intelligence API keys in transit."
            )
