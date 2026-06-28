"""UTM tagging util (apps.publisher.utm.apply_utm)."""
from apps.publisher.utm import apply_utm


def test_adds_utm_params():
    out = apply_utm("Read more at https://africacen.org/news", "linkedin", "EGM 2026")
    assert "utm_source=linkedin" in out
    assert "utm_medium=social" in out
    assert "utm_campaign=egm-2026" in out


def test_strips_blotato_prefix_for_source():
    out = apply_utm("https://x.com/a", "blotato_linkedin", "c")
    assert "utm_source=linkedin" in out


def test_idempotent_when_already_tagged():
    url = "https://africacen.org/?utm_source=manual"
    text = f"see {url}"
    assert apply_utm(text, "linkedin", "c") == text  # left untouched


def test_preserves_existing_query():
    out = apply_utm("https://africacen.org/p?ref=abc", "twitter", "launch")
    assert "ref=abc" in out
    assert "utm_source=twitter" in out


def test_trailing_period_kept_outside_url():
    out = apply_utm("End at https://africacen.org/news.", "linkedin", "c")
    assert out.endswith(".")
    assert "news.?" not in out  # the period is not part of the tagged URL


def test_empty_campaign_defaults_organic():
    assert "utm_campaign=organic" in apply_utm("https://a.org", "linkedin", "")


def test_no_url_unchanged():
    assert apply_utm("no links here", "linkedin", "c") == "no links here"
    assert apply_utm("", "linkedin", "c") == ""
