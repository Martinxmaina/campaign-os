from apps.publisher.gate_hash import canonical_content_hash


def test_hash_matches_agent_service_algorithm():
    # Mirror of agent-service app/services/content_hash.py
    import hashlib
    text = "Funding has been secured."
    expected = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
    assert canonical_content_hash(text, []) == expected
