# apps/content_intake/tests/test_voice_rubric.py
from apps.content_intake.voice_rubric import score_voice

PROFILE = {
    "banned_phrases": ["synergies", "leverage", "unlock", "ecosystem play"],
    "length_by_channel": {"linkedin": (250, 400), "email": (40, 400)},
    "signature_moves": ["SE4ALL", "operational engine", "catalytic capital"],
}


def test_joseph_linkedin_passes():
    text = ("300 reasons the catalytic capital logic beats a concept note. " * 30)  # ~300+ words, no banned, no 'I' opener
    res = score_voice(text, "linkedin", PROFILE)
    assert res["passed"], res["failures"]


def test_non_joseph_fails_on_banned_and_opener():
    text = "I think we should leverage synergies to unlock our ecosystem play."
    res = score_voice(text, "linkedin", PROFILE)
    assert not res["passed"]
    assert any("banned" in f for f in res["failures"])


def test_email_length_out_of_range_fails():
    res = score_voice("Too short.", "email", PROFILE)
    assert not res["passed"]
    assert any("length" in f for f in res["failures"])
