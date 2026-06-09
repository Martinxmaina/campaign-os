from apps.composer.curated_feeds import (
    FEED_CATEGORIES,
    get_feed_categories,
    get_feeds_for_category,
)


def test_afcen_category_registered():
    slugs = {c["slug"] for c in FEED_CATEGORIES}
    assert "afcen-africa" in slugs
    labels = {c["slug"]: c["label"] for c in get_feed_categories()}
    assert labels["afcen-africa"] == "AfCEN / Africa"


def test_afcen_category_resolves_with_required_fields():
    feeds = get_feeds_for_category("afcen-africa")
    assert feeds, "afcen-africa category should resolve to a non-empty feed list"
    for feed in feeds:
        assert feed.get("name"), f"missing name: {feed}"
        assert feed.get("website"), f"missing website: {feed}"
        assert feed.get("rss"), f"missing rss: {feed}"
