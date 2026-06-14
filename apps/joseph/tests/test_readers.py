"""Tests for apps.joseph.readers — thin, graceful wrappers over agent-service.

Each reader calls ``agent_get``/``agent_post`` with the path from the spec
Grounding and returns a safe default ([]/{}) when the service is down
(AgentClientError) so callers never see a 500.
"""
from unittest.mock import patch

import pytest

from apps.common.agent_client import AgentClientError
from apps.joseph import readers


@pytest.mark.django_db
def test_list_threads_passes_filters_and_returns_items():
    fake = {"items": [{"id": "t1", "org": "Rockefeller", "stage": "qualify"}]}
    with patch("apps.joseph.readers.agent_get", return_value=fake) as g:
        out = readers.list_threads(traffic_light="red", owner="joseph")
    assert out == fake["items"]
    called = g.call_args[0][0]
    assert called.startswith("/threads")
    assert "traffic_light=red" in called
    assert "owner=joseph" in called


@pytest.mark.django_db
def test_list_threads_agent_down_returns_empty_list():
    with patch("apps.joseph.readers.agent_get", side_effect=AgentClientError("down")):
        assert readers.list_threads() == []


@pytest.mark.django_db
def test_get_thread_calls_path_and_degrades():
    with patch("apps.joseph.readers.agent_get", return_value={"id": "t1"}) as g:
        assert readers.get_thread("t1") == {"id": "t1"}
    assert g.call_args[0][0] == "/threads/t1"
    with patch("apps.joseph.readers.agent_get", side_effect=AgentClientError("down")):
        assert readers.get_thread("t1") == {}


@pytest.mark.django_db
def test_get_dossier_calls_path_and_degrades():
    with patch("apps.joseph.readers.agent_get", return_value={"id": "d1"}) as g:
        assert readers.get_dossier("d1") == {"id": "d1"}
    assert g.call_args[0][0] == "/dossiers/d1"
    with patch("apps.joseph.readers.agent_get", side_effect=AgentClientError("down")):
        assert readers.get_dossier("d1") == {}


@pytest.mark.django_db
def test_list_notifications_unread_default_and_degrades():
    fake = {"items": [{"id": "n1", "kind": "intro", "urgent": True}]}
    with patch("apps.joseph.readers.agent_get", return_value=fake) as g:
        assert readers.list_notifications() == fake["items"]
    assert "unread" in g.call_args[0][0]
    with patch("apps.joseph.readers.agent_get", side_effect=AgentClientError("down")):
        assert readers.list_notifications() == []


@pytest.mark.django_db
def test_search_pages_passes_query_and_degrades():
    fake = {"pages": [{"slug": "rockefeller", "title": "Rockefeller"}]}
    with patch("apps.joseph.readers.agent_get", return_value=fake) as g:
        assert readers.search_pages("rock", entity_type="funder") == fake["pages"]
    called = g.call_args[0][0]
    assert called.startswith("/knowledge/pages")
    assert "q=rock" in called
    assert "entity_type=funder" in called
    with patch("apps.joseph.readers.agent_get", side_effect=AgentClientError("down")):
        assert readers.search_pages("rock") == []


@pytest.mark.django_db
def test_get_page_tier_and_degrades():
    fake = {"slug": "rockefeller", "tier": "l2", "content": "body"}
    with patch("apps.joseph.readers.agent_get", return_value=fake) as g:
        assert readers.get_page("rockefeller", tier="l2") == fake
    called = g.call_args[0][0]
    assert called.startswith("/knowledge/pages/rockefeller")
    assert "tier=l2" in called
    with patch("apps.joseph.readers.agent_get", side_effect=AgentClientError("down")):
        assert readers.get_page("rockefeller") == {}


@pytest.mark.django_db
def test_page_revisions_and_degrades():
    fake = {"revisions": [{"diff": "+x", "created_at": "now"}]}
    with patch("apps.joseph.readers.agent_get", return_value=fake) as g:
        assert readers.page_revisions("rockefeller") == fake["revisions"]
    assert g.call_args[0][0] == "/knowledge/pages/rockefeller/revisions"
    with patch("apps.joseph.readers.agent_get", side_effect=AgentClientError("down")):
        assert readers.page_revisions("rockefeller") == []


@pytest.mark.django_db
def test_list_content_passes_status_and_degrades():
    fake = {"items": [{"id": "c1", "title": "Draft", "status": "draft"}]}
    with patch("apps.joseph.readers.agent_get", return_value=fake) as g:
        assert readers.list_content(status="draft") == fake["items"]
    called = g.call_args[0][0]
    assert called.startswith("/content/items")
    assert "status=draft" in called
    with patch("apps.joseph.readers.agent_get", side_effect=AgentClientError("down")):
        assert readers.list_content() == []


@pytest.mark.django_db
def test_news_about_filters_by_org_and_degrades():
    fake = {"items": [
        {"title": "Rockefeller Foundation pledges $1B", "summary": "x"},
        {"title": "Unrelated climate headline", "summary": "y"},
    ]}
    with patch("apps.joseph.readers.agent_get", return_value=fake):
        out = readers.news_about("Rockefeller Foundation")
    assert any("Rockefeller" in i["title"] for i in out)
    assert all("Rockefeller" in (i.get("title", "") + i.get("summary", "")) for i in out)
    with patch("apps.joseph.readers.agent_get", side_effect=AgentClientError("down")):
        assert readers.news_about("Rockefeller") == []


@pytest.mark.django_db
def test_mark_read_posts_and_degrades():
    with patch("apps.joseph.readers.agent_post", return_value={}) as p:
        assert readers.mark_read("n1") is True
    assert p.call_args[0][0] == "/notifications/n1/read"
    with patch("apps.joseph.readers.agent_post", side_effect=AgentClientError("down")):
        assert readers.mark_read("n1") is False


@pytest.mark.django_db
def test_compile_dossier_posts_and_degrades():
    with patch("apps.joseph.readers.agent_post", return_value={"dossier_id": "d1"}) as p:
        assert readers.compile_dossier("t1") == {"dossier_id": "d1"}
    assert p.call_args[0][0] == "/threads/t1/dossier"
    with patch("apps.joseph.readers.agent_post", side_effect=AgentClientError("down")):
        assert readers.compile_dossier("t1") == {}
