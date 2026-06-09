import httpx
import pytest
from django.test import override_settings
from apps.common import agent_client


@override_settings(AGENT_SERVICE_BASE_URL="https://agent.example", AGENT_SERVICE_TOKEN="svc-tok")
def test_agent_get_attaches_bearer(monkeypatch):
    captured = {}
    def fake_get(self, url, headers=None, **kw):
        captured["url"] = url; captured["headers"] = headers
        return httpx.Response(200, json={"items": [1]})
    monkeypatch.setattr(httpx.Client, "get", fake_get)
    out = agent_client.agent_get("/ideas?week=2026-W24")
    assert out == {"items": [1]}
    assert captured["url"] == "https://agent.example/ideas?week=2026-W24"
    assert captured["headers"]["Authorization"] == "Bearer svc-tok"


@override_settings(AGENT_SERVICE_BASE_URL="https://agent.example", AGENT_SERVICE_TOKEN="svc-tok")
def test_agent_get_raises_on_non2xx(monkeypatch):
    monkeypatch.setattr(httpx.Client, "get",
                        lambda self, url, headers=None, **kw: httpx.Response(503, text="down"))
    with pytest.raises(agent_client.AgentClientError):
        agent_client.agent_get("/ideas")


@override_settings(AGENT_SERVICE_BASE_URL="", AGENT_SERVICE_TOKEN="")
def test_unconfigured_raises():
    with pytest.raises(agent_client.AgentClientError):
        agent_client.agent_get("/ideas")
