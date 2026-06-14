"""DEAL-ENGINE weighted scoring, ported from agent-service to Django.

Mirrors ``agent-service/app/services/scoring.py::score_engager`` weights so the
two services stay in parity on shared fixtures.
"""

WEIGHTS = {
    "warmth": 0.25,
    "seniority_org_fit": 0.20,
    "pillar_fit": 0.15,
    "engagement_recency": 0.20,
    "engagement_frequency": 0.10,
    "track_alignment": 0.10,
}


def score_thread_features(features: dict) -> tuple[float, int, str]:
    """Transparent weighted score 0..1 → quintile 1..5 → recommended action."""
    score = round(sum(WEIGHTS[k] * float(features.get(k, 0.0)) for k in WEIGHTS), 4)
    quintile = max(1, min(5, int(score * 5) + 1))
    action = "advance" if quintile >= 4 else "nurture" if quintile >= 2 else "deprioritize"
    return score, quintile, action
