"""Intelligence service layer — intake context wiring for HERALD/ATLAS.

Provides ``get_herald_intake_context(workspace)`` which is the single
call HERALD and ATLAS make when building their deliberation payload.
This is a thin adapter: the canonical logic lives in
``apps.content_intake.agent_context``; this module re-exports it so
the intelligence service layer owns the contract without duplicating the
query logic.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_herald_intake_context(workspace) -> dict[str, Any]:
    """Return serialisable intake context dict for HERALD/ATLAS prompts.

    Delegates to ``build_intake_context`` from the content_intake app.
    Returns an empty context dict if content_intake is not installed or
    the workspace has no intake items, so callers never have to guard
    against None.
    """
    try:
        from apps.content_intake.agent_context import build_intake_context
        return build_intake_context(workspace)
    except ImportError:
        logger.warning(
            "content_intake app not installed — returning empty intake context"
        )
        return {"intake_items": [], "total_visible": 0, "workspace": str(getattr(workspace, "pk", ""))}
    except Exception:
        logger.exception(
            "Failed to build intake context for workspace=%s",
            getattr(workspace, "pk", "?"),
        )
        return {"intake_items": [], "total_visible": 0, "workspace": str(getattr(workspace, "pk", ""))}
