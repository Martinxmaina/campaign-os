from apps.crm.scoring import score_thread_features


def test_score_thread_features_matches_deal_engine_weights():
    features = {
        "warmth": 1.0,
        "seniority_org_fit": 0.8,
        "pillar_fit": 0.5,
        "engagement_recency": 0.6,
        "engagement_frequency": 0.2,
        "track_alignment": 1.0,
    }
    score, quintile, action = score_thread_features(features)
    # 0.25 + 0.16 + 0.075 + 0.12 + 0.02 + 0.10 = 0.725
    assert score == 0.725
    assert quintile == int(0.725 * 5) + 1  # == 4
    assert quintile == 4
    assert action == "advance"


def test_empty_features_scores_zero_quintile_one():
    score, quintile, action = score_thread_features({})
    assert score == 0.0
    assert quintile == 1
    assert action == "deprioritize"
