import httpx
from apps.publisher.gate_client import verify_gate, GateError


def test_verify_gate_signs_and_parses(monkeypatch, settings):
    settings.AGENT_SERVICE_BASE_URL = "https://agent.example"
    settings.STUDIO_SHARED_SECRET = "plat-secret"
    settings.STUDIO_DEPLOYMENT_ID = "platform"
    captured = {}

    def fake_get(self, url, headers=None, **kw):
        captured["url"] = url
        captured["headers"] = headers
        return httpx.Response(200, json={"gate_id": "g1", "verdict": "pass",
                                         "content_hash": "abc"})

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    res = verify_gate("g1")
    assert res["verdict"] == "pass" and res["content_hash"] == "abc"
    assert "X-Studio-Signature" in captured["headers"]
    assert captured["headers"]["X-Studio-Deployment"] == "platform"
