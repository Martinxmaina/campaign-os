# apps/approvals/tests/test_send_for_publish.py
import pytest
from apps.settings_manager.helpers import get_setting


@pytest.mark.django_db
def test_review_copy_email_default(workspace):
    # Falls back to the app default when no workspace/org override exists.
    assert get_setting(workspace.id, "review.copy_email") == "martin.maina@africacen.org"
