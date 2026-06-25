# apps/approvals/tests/test_send_for_publish.py
import pytest
from apps.settings_manager.helpers import get_setting


@pytest.fixture
def reviewer(client, org_owner, workspace):
    from apps.members.models import WorkspaceMembership
    WorkspaceMembership.objects.create(user=org_owner, workspace=workspace, workspace_role="owner")
    org_owner.last_workspace_id = workspace.id
    org_owner.save(update_fields=["last_workspace_id"])
    client.force_login(org_owner)
    return org_owner


@pytest.mark.django_db
def test_review_copy_email_default(workspace):
    # Falls back to the app default when no workspace/org override exists.
    assert get_setting(workspace.id, "review.copy_email") == "martin.maina@africacen.org"


from django.core import mail
from apps.composer.models import Post


@pytest.mark.django_db
def test_email_post_copy_sends_one_mail(workspace, reviewer):
    from apps.approvals.send_actions import email_post_copy
    post = Post.objects.create(workspace=workspace, title="Solar story",
        caption="Solar is booming across East Africa.", review_state="pending",
        review_assignee=reviewer)
    sent = email_post_copy(post, "ops@example.com", reviewer)
    assert sent is True
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["ops@example.com"]
    assert "Solar is booming" in mail.outbox[0].body


@pytest.mark.django_db
def test_email_post_copy_no_address_is_noop(workspace, reviewer):
    from apps.approvals.send_actions import email_post_copy
    post = Post.objects.create(workspace=workspace, title="P", caption="c",
        review_state="pending", review_assignee=reviewer)
    assert email_post_copy(post, "", reviewer) is False
    assert len(mail.outbox) == 0
