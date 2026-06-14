"""Tests for the Gmail outbound send transport (``integrations.gmail.send_message``).

``send_message`` builds a MIME message from the supplied fields, base64url-encodes
it, and calls ``service.users().messages().send(userId="me", body={"raw": ...})``,
returning the Gmail-assigned message id. The Gmail ``service`` is mocked — no
network. These assert: the message id is returned; ``send`` is called with
``userId="me"`` and a ``raw`` body; the To/Subject/From/Content-Type headers are
present; and ``In-Reply-To`` / ``References`` threading headers are set only when
supplied.
"""
from __future__ import annotations

import base64
from email import message_from_bytes
from unittest.mock import MagicMock


def _make_service(sent_id="m-sent-1"):
    """A Gmail service double whose messages().send().execute() returns an id."""
    service = MagicMock()
    service.users.return_value.messages.return_value.send.return_value.execute.return_value = {
        "id": sent_id
    }
    return service


def _decode_raw(send_call):
    """Pull the base64url ``raw`` out of a recorded send() call and parse it."""
    body = send_call.kwargs.get("body") or send_call.args[1]
    raw = body["raw"]
    return message_from_bytes(base64.urlsafe_b64decode(raw.encode("ascii")))


def test_send_message_returns_sent_id_and_calls_send():
    from integrations.gmail import send_message

    service = _make_service("m-42")
    result = send_message(
        service,
        to="a@b.org",
        subject="Hello there",
        body_html="<p>hi</p>",
    )

    assert result == "m-42"
    send = service.users.return_value.messages.return_value.send
    send.assert_called_once()
    call = send.call_args
    assert call.kwargs["userId"] == "me"
    assert "raw" in call.kwargs["body"]


def test_send_message_builds_mime_with_core_headers():
    from integrations.gmail import send_message

    service = _make_service()
    send_message(
        service,
        to="a@b.org",
        subject="Subject line",
        body_html="<p>body</p>",
        sender="joseph@africacen.org",
    )

    send = service.users.return_value.messages.return_value.send
    mime = _decode_raw(send.call_args)
    assert mime["To"] == "a@b.org"
    assert mime["Subject"] == "Subject line"
    assert mime["From"] == "joseph@africacen.org"
    assert mime.get_content_type() == "text/html"


def test_send_message_sets_threading_headers_when_provided():
    from integrations.gmail import send_message

    service = _make_service()
    send_message(
        service,
        to="a@b.org",
        subject="re: x",
        body_html="<p>reply</p>",
        headers={"In-Reply-To": "<m1>", "References": "<m1>"},
    )

    send = service.users.return_value.messages.return_value.send
    mime = _decode_raw(send.call_args)
    assert mime["In-Reply-To"] == "<m1>"
    assert mime["References"] == "<m1>"


def test_send_message_omits_threading_headers_when_absent():
    from integrations.gmail import send_message

    service = _make_service()
    send_message(service, to="a@b.org", subject="fresh", body_html="<p>x</p>")

    send = service.users.return_value.messages.return_value.send
    mime = _decode_raw(send.call_args)
    assert mime["In-Reply-To"] is None
    assert mime["References"] is None
