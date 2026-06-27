import pytest
from django.urls import reverse

from apps.members.models import WorkspaceMembership

pytestmark = pytest.mark.django_db


def test_inbox_feed_renders_200(client, workspace, make_user_in_workspace):
    user = make_user_in_workspace(workspace, role=WorkspaceMembership.WorkspaceRole.MANAGER)
    client.force_login(user)
    resp = client.get(reverse("inbox:feed", kwargs={"workspace_id": workspace.id}))
    assert resp.status_code == 200
    # The thread/conversation focus and the side-rail tools survive the refactor.
    assert b"Inbox" in resp.content
    assert b"inbox-message-list" in resp.content


def test_inbox_message_detail_renders_200(client, workspace, make_user_in_workspace):
    from django.utils import timezone

    from apps.inbox.models import InboxMessage
    from apps.social_accounts.models import SocialAccount

    user = make_user_in_workspace(workspace, role=WorkspaceMembership.WorkspaceRole.MANAGER)
    client.force_login(user)
    account = SocialAccount.objects.create(
        workspace=workspace,
        platform="mock",
        account_platform_id="acct-mock",
        account_name="Mock acct",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    )
    message = InboxMessage.objects.create(
        workspace=workspace,
        social_account=account,
        platform_message_id="ext-1",
        sender_name="Jane Public",
        body="Hello there, question about your post.",
        status=InboxMessage.Status.UNREAD,
        received_at=timezone.now(),
    )
    resp = client.get(
        reverse(
            "inbox:message_detail",
            kwargs={"workspace_id": workspace.id, "message_id": message.id},
        )
    )
    assert resp.status_code == 200
    assert b"Jane Public" in resp.content
    # Reply tools (HTMX form) must remain present after the density refactor.
    assert b"Send Reply" in resp.content
