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
