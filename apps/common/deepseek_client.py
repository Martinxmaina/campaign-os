"""Direct DeepSeek / Azure AI Foundry client (OpenAI-compatible).

Content generation (AI Studio + campaign drafting) calls DeepSeek DIRECTLY
here instead of hopping through the HERALD agent-service. Mirrors the
agent-service's runtime config (DEEPSEEK_API_KEY / BASE_URL / API_VERSION /
MODEL) but uses the *synchronous* OpenAI client since Django views are sync.

Design notes:
- ``openai`` is imported LAZILY inside the call so a missing install (or an
  environment where the key isn't set) never crashes boot or import.
- Azure AI Foundry needs ``?api-version=...``; public DeepSeek leaves it empty.
- Azure's Responsible-AI content filter can return a 400 with
  ``finish_reason='content_filter'`` — we degrade to "" rather than raising,
  so callers fall back to their deterministic path (never a 500).
- ``deepseek_available()`` lets callers pick DeepSeek vs the agent-service
  fallback without importing openai.
"""
from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger(__name__)

# Generous but bounded — content drafts are short; keep a single request well
# under the worker's task budget.
_DEFAULT_TIMEOUT = 40.0
_DEFAULT_MAX_TOKENS = 1200


def deepseek_available() -> bool:
    """True when a DeepSeek API key is configured (no openai import needed)."""
    return bool(getattr(settings, "DEEPSEEK_API_KEY", ""))


def chat(
    system: str,
    user: str,
    *,
    temperature: float = 0.7,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
    timeout: float = _DEFAULT_TIMEOUT,
) -> str:
    """One system+user chat completion → assistant text ("" on any failure).

    NEVER raises: a missing key, missing install, transport error, or Azure
    RAI content-filter all resolve to "" so callers can fall back gracefully.
    """
    api_key = getattr(settings, "DEEPSEEK_API_KEY", "")
    if not api_key:
        return ""

    try:
        from openai import OpenAI  # lazy: never breaks boot if uninstalled
    except Exception:  # pragma: no cover - defensive
        logger.warning("deepseek_client: openai SDK not installed")
        return ""

    kwargs: dict = {
        "api_key": api_key,
        "base_url": getattr(settings, "DEEPSEEK_BASE_URL", "") or "https://api.deepseek.com",
        "timeout": timeout,
    }
    api_version = getattr(settings, "DEEPSEEK_API_VERSION", "")
    if api_version:  # Azure AI Foundry only
        kwargs["default_query"] = {"api-version": api_version}

    try:
        client = OpenAI(**kwargs)
        resp = client.chat.completions.create(
            model=getattr(settings, "DEEPSEEK_MODEL", "") or "deepseek-chat",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        choice = resp.choices[0]
        # Azure RAI can flag the completion — treat as empty, not an error.
        if getattr(choice, "finish_reason", "") == "content_filter":
            logger.info("deepseek_client: response filtered by content policy")
            return ""
        return (choice.message.content or "").strip()
    except Exception as exc:  # transport / 400 RAI / rate-limit — all soft
        logger.warning("deepseek_client: chat failed: %s", exc)
        return ""
