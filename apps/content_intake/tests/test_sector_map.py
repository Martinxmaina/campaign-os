# apps/content_intake/tests/test_sector_map.py
import pytest
from apps.content_intake.sector_map import map_pillar_to_sector

@pytest.mark.parametrize("raw,expected", [
    ("energy", "energy"),
    ("Energy", "energy"),
    ("Power & Energy", "energy"),
    ("agribusiness", "agribusiness"),
    ("Agriculture", "agribusiness"),
    ("Food systems", "agribusiness"),
    ("ai", "ai"),
    ("AI", "ai"),
    ("AI 10Bn", "ai"),
    ("Artificial Intelligence", "ai"),
    ("something random", "general"),
    ("", "general"),
])
def test_map_pillar_to_sector(raw, expected):
    assert map_pillar_to_sector(raw) == expected


@pytest.mark.parametrize("raw", ["energy", "agribusiness", "ai", "general"])
def test_canonical_sectors_round_trip(raw):
    """Feeding a canonical sector back in must return itself (idempotent).

    Guards the console_views.news_draft path where an already-canonical
    request-supplied sector is re-normalised before hitting the agent-service.
    """
    assert map_pillar_to_sector(raw) == raw


# --- Documented precedence: an explicit AI signal beats cross-cutting domain
# words. See sector_map module docstring. ---
@pytest.mark.parametrize("raw,expected", [
    ("AI for Agriculture", "ai"),       # would match 'agri' but 'ai' wins
    ("Solar AI platform", "ai"),        # would match 'solar' but 'ai' wins
    ("AI-powered energy grid", "ai"),   # would match energy but 'ai' wins
    ("Machine learning for farms", "ai"),
])
def test_ai_precedence_over_overlapping_domains(raw, expected):
    assert map_pillar_to_sector(raw) == expected


# --- Word-boundary safety: broad tokens must not fire on unrelated words. ---
@pytest.mark.parametrize("raw,expected", [
    ("Women empowerment", "general"),    # 'power' must NOT match 'empowerment'
    ("Manpower planning", "general"),     # 'power' must NOT match 'manpower'
    ("Seafood exports", "general"),       # 'food' must NOT match 'seafood'
    ("Food security policy", "agribusiness"),  # standalone 'food' DOES match
    ("Powering communities", "general"),  # 'power' substring must NOT match
])
def test_word_boundaries_avoid_false_positives(raw, expected):
    assert map_pillar_to_sector(raw) == expected
