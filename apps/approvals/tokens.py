import secrets
from datetime import timedelta
from django.utils import timezone
from .models import ActionToken


def mint_token(assignment, purpose, ttl_days=7):
    return ActionToken.objects.create(
        assignment=assignment, purpose=purpose, token=secrets.token_urlsafe(32),
        expires_at=timezone.now() + timedelta(days=ttl_days))


def resolve_token(raw, purpose):
    t = ActionToken.objects.filter(token=raw, purpose=purpose, used_at__isnull=True).select_related(
        "assignment", "assignment__post").first()
    if t is None or t.expires_at <= timezone.now():
        return None
    return t


def consume(token):
    token.used_at = timezone.now()
    token.save(update_fields=["used_at"])
