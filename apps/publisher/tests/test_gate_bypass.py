"""Human-authored composer posts bypass the publish gate; AI posts stay gated."""
import pytest
from apps.publisher.engine import PublishEngine


class _FakePP:
    def __init__(self, gate_bypassed=False, gate_id=None, content_hash=""):
        self.gate_bypassed = gate_bypassed
        self.gate_id = gate_id
        self.content_hash = content_hash


def test_bypassed_post_clears_gate_without_gate_id():
    engine = PublishEngine()
    pp = _FakePP(gate_bypassed=True, gate_id=None)
    # Returns None == cleared to publish, even though there is no gate_id.
    assert engine._gate_failure_reason(pp) is None


def test_non_bypassed_post_without_gate_id_is_blocked():
    engine = PublishEngine()
    pp = _FakePP(gate_bypassed=False, gate_id=None)
    assert engine._gate_failure_reason(pp) == "missing gate_id"
