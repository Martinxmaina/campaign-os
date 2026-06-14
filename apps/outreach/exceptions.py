"""Outreach-engine errors raised by the deliverability adapter and the gate.

These are the contract the higher layers (gate orchestration, sequences, views)
catch — never the transport. ``AddressSuppressed`` / ``CapExceeded`` are raised by
``guarded_send`` *before* the transport is touched; ``GateBlocked`` is raised by
the gate-on-send orchestration (Task 4) when a body fails the gate, so a non-pass
body can never reach the sender.
"""
from __future__ import annotations


class OutreachError(Exception):
    """Base class for outreach-engine errors."""


class AddressSuppressed(OutreachError):
    """The recipient is on the suppression list (unsubscribe / bounce / complaint)."""


class CapExceeded(OutreachError):
    """The mailbox has hit its effective daily cap (warm-up ramp or daily_cap)."""


class GateBlocked(OutreachError):
    """The gate returned a non-pass verdict; the body must NOT be sent.

    Carries the gate ``findings`` so the caller can record an approval-needed
    record without re-running the gate.
    """

    def __init__(self, message="blocked by gate", *, findings=None):
        super().__init__(message)
        self.findings = findings or {}
