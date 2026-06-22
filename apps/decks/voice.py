"""Joseph-voice application SEAM (TB.5 Task 2).

# SEAM: real agent-service voice:joseph pass later.

Block content is pre-approved and is *never* voiced — only the **generated**
personalization layer (opening framing, audience vocabulary, the ask line) is
run through Joseph's voice profile before it is gated. ``apply_voice(text)`` is
that seam.

Today it is the identity function: it returns ``text`` unchanged so assembly is
deterministic and testable without the agent-service. When wired, the body calls
the ``voice:joseph`` profile via agent-service (see project_tb1_voice_profile)
and **degrades to identity** on any ``AgentClientError`` — a voice-service outage
must never block (or corrupt) an otherwise-clean deck. The signature is stable,
so the live swap leaves these tests green.
"""
from __future__ import annotations


def apply_voice(text: str) -> str:
    """Apply Joseph's voice to GENERATED ``text``; identity when the service is down.

    Pre-approved block content must NOT be passed here — only generated framing/
    vocabulary/ask lines. Returns the (possibly-voiced) text; on any failure it
    returns ``text`` unchanged so the deck still assembles.
    """
    if not text:
        return text
    # SEAM: real agent-service voice:joseph pass later. Until then, identity.
    return text
