import httpx
from apps.publisher.ingest_webhook import post_to_ingest


def test_post_to_ingest_signs_and_targets(monkeypatch, settings):
    settings.AGENT_SERVICE_INGEST_URL = "https://agent.example/ingest"
    settings.AGENT_SERVICE_INGEST_KEY = "platform_ingest_key"
    captured = {}

    def fake_post(self, url, headers=None, json=None, **kw):
        captured.update(url=url, headers=headers, json=json)
        return httpx.Response(
            200,
            json={"id": "i1", "decision": "stored"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    out = post_to_ingest(
        source_type="webhook",
        source_id="platform_publish",
        payload={"platform_post_id": "p1"},
        dedupe_key="p1",
    )
    assert out["decision"] == "stored"
    assert captured["headers"]["X-Ingest-Key"] == "platform_ingest_key"
    assert captured["json"]["source_type"] == "webhook"
