# apps/content_intake/tests/test_voice_capture.py
from unittest.mock import patch
import pytest
from apps.content_intake.herald_bridge import request_herald_draft
from apps.content_intake.models import ContentIntake


@pytest.mark.django_db
def test_bridge_passes_voice_user_for_joseph(workspace):
    item = ContentIntake.objects.create(workspace=workspace, external_id="V-1", angle="x",
        owner_raw="Joseph", channel_targets=[{"platform": "linkedin", "account": "joseph"}],
        sensitivity="public_safe", status="accepted")
    with patch("apps.content_intake.herald_bridge.agent_post", return_value={"proposals": [{"content_id": "c1"}]}) as m:
        request_herald_draft(item)
    payload = m.call_args[0][1]
    assert payload.get("voice_user") == "joseph"


@pytest.mark.django_db
def test_bridge_no_voice_user_for_org_item(workspace):
    item = ContentIntake.objects.create(workspace=workspace, external_id="V-2", angle="x",
        owner_raw="Carren", channel_targets=[{"platform": "linkedin", "account": "waiis"}],
        sensitivity="public_safe", status="accepted")
    with patch("apps.content_intake.herald_bridge.agent_post", return_value={"proposals": [{"content_id": "c2"}]}) as m:
        request_herald_draft(item)
    payload = m.call_args[0][1]
    assert "voice_user" not in payload or payload.get("voice_user") is None
