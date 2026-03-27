"""Tests for the Graph client wrapper without live network calls."""

from __future__ import annotations

import urllib.error

from email_intel.graph_client import GraphClient, GraphClientConfig, GraphRequestError


def make_client(**kwargs) -> GraphClient:
    config_data = {
        "tenant_id": "tenant-123",
        "client_id": "client-123",
        "client_secret": "secret-123",
        "mailbox_address": "kmcquire@peak10energy.com",
        "sharepoint_site_id": "site-123",
        "sharepoint_drive_id": "drive-123",
    }
    config_data.update(kwargs)
    config = GraphClientConfig(**config_data)
    return GraphClient(config=config)


def test_unavailable_without_required_credentials():
    client = GraphClient(config=GraphClientConfig())
    assert not client.is_available


def test_sharepoint_availability_is_tracked_separately_from_mailbox():
    client = make_client(mailbox_address="")

    assert client.is_available is False
    assert client.sharepoint_available is True


def test_build_messages_url_contains_mailbox_and_filter():
    client = make_client()
    url = client.build_messages_url(top=10, unread_only=True)

    assert "kmcquire%40peak10energy.com" in url
    assert "$top=10" in url
    assert "isRead+eq+false" in url


def test_build_upload_url_uses_site_and_drive():
    client = make_client()
    url = client.build_upload_url(
        "Invoice_123.pdf",
        folder_path="00_STAGING/Inbox",
    )

    assert "/sites/site-123/drives/drive-123/" in url
    assert "00_STAGING/Inbox/Invoice_123.pdf" in url


def test_list_inbox_messages_returns_value_array(monkeypatch):
    client = make_client()
    monkeypatch.setattr(
        client,
        "_request_json",
        lambda method, url, payload=None, content_type="application/json": {
            "value": [{"id": "msg-1"}]
        },
    )

    messages = client.list_inbox_messages()
    assert messages == [{"id": "msg-1"}]


def test_get_message_uses_selected_fields(monkeypatch):
    client = make_client()
    captured: dict[str, str] = {}

    def fake_request(method, url, payload=None, content_type="application/json"):
        captured["method"] = method
        captured["url"] = url
        return {"id": "msg-1"}

    monkeypatch.setattr(client, "_request_json", fake_request)

    message = client.get_message("msg-1", select_fields=["from", "replyTo"])

    assert message == {"id": "msg-1"}
    assert captured["method"] == "GET"
    assert "$select=from,replyTo" in captured["url"]


def test_send_mail_posts_expected_payload(monkeypatch):
    client = make_client()
    captured: dict[str, object] = {}

    def fake_request(method, url, payload=None, content_type="application/json"):
        captured["method"] = method
        captured["url"] = url
        captured["payload"] = payload
        captured["content_type"] = content_type
        return {}

    monkeypatch.setattr(client, "_request_json", fake_request)

    client.send_mail(
        to_recipients=["sender@example.com"],
        cc_recipients=["assistant@example.com"],
        subject="Re: Test",
        body="Thanks for the note.",
    )

    assert captured["method"] == "POST"
    assert captured["content_type"] == "application/json"
    assert str(captured["url"]).endswith("/users/kmcquire%40peak10energy.com/sendMail")
    assert captured["payload"] == {
        "message": {
            "subject": "Re: Test",
            "body": {
                "contentType": "Text",
                "content": "Thanks for the note.",
            },
            "toRecipients": [
                {"emailAddress": {"address": "sender@example.com"}}
            ],
            "ccRecipients": [
                {"emailAddress": {"address": "assistant@example.com"}}
            ],
        },
        "saveToSentItems": True,
    }


def test_move_message_posts_destination_id(monkeypatch):
    client = make_client()
    captured: dict[str, object] = {}

    def fake_request(method, url, payload=None, content_type="application/json"):
        if method == "GET" and "/mailFolders/archive" in str(url):
            return {"id": "archive", "displayName": "Archive", "wellKnownName": "archive"}
        captured["method"] = method
        captured["url"] = url
        captured["payload"] = payload
        return {"id": "moved-msg"}

    monkeypatch.setattr(client, "_request_json", fake_request)

    moved = client.move_message("msg-1", "archive")

    assert moved == {"id": "moved-msg"}
    assert captured["method"] == "POST"
    assert str(captured["url"]).endswith("/messages/msg-1/move")
    assert captured["payload"] == {"destinationId": "archive"}


def test_move_message_resolves_archive_folder_id_from_folder_listing(monkeypatch):
    client = make_client()
    captured: dict[str, object] = {}

    def fake_request(method, url, payload=None, content_type="application/json"):
        if method == "GET" and "/mailFolders/archive" in str(url):
            raise urllib.error.HTTPError(str(url), 404, "Not Found", hdrs=None, fp=None)
        if method == "GET" and str(url).endswith("/mailFolders?$top=200&$select=id,displayName,wellKnownName&includeHiddenFolders=true"):
            return {
                "value": [
                    {"id": "folder-1", "displayName": "Inbox", "wellKnownName": "inbox"},
                    {"id": "folder-archive", "displayName": "Archive", "wellKnownName": "archive"},
                ]
            }

        captured["method"] = method
        captured["url"] = url
        captured["payload"] = payload
        return {"id": "moved-msg"}

    monkeypatch.setattr(client, "_request_json", fake_request)

    moved = client.move_message("msg-1", "archive")

    assert moved == {"id": "moved-msg"}
    assert captured["method"] == "POST"
    assert str(captured["url"]).endswith("/messages/msg-1/move")
    assert captured["payload"] == {"destinationId": "folder-archive"}


def test_move_message_falls_back_to_raw_destination_on_not_found(monkeypatch):
    client = make_client()
    attempts: list[dict[str, object]] = []

    def fake_request(method, url, payload=None, content_type="application/json"):
        if method == "GET" and "/mailFolders/archive" in str(url):
            return {"id": "folder-archive", "displayName": "Archive", "wellKnownName": "archive"}
        if method == "POST":
            attempts.append({"url": str(url), "payload": payload})
            if payload == {"destinationId": "folder-archive"}:
                raise GraphRequestError(
                    status_code=404,
                    code="ErrorItemNotFound",
                    message="Folder not found",
                    url=str(url),
                )
            return {"id": "moved-msg"}
        return {"value": []}

    monkeypatch.setattr(client, "_request_json", fake_request)

    moved = client.move_message("msg-1", "archive")

    assert moved == {"id": "moved-msg"}
    assert attempts == [
        {
            "url": "https://graph.microsoft.com/v1.0/users/kmcquire%40peak10energy.com/messages/msg-1/move",
            "payload": {"destinationId": "folder-archive"},
        },
        {
            "url": "https://graph.microsoft.com/v1.0/users/kmcquire%40peak10energy.com/messages/msg-1/move",
            "payload": {"destinationId": "archive"},
        },
    ]


def test_build_mail_folders_url_can_include_hidden_folders():
    client = make_client()

    url = client.build_mail_folders_url(select_fields=["id"], include_hidden_folders=True)

    assert "includeHiddenFolders=true" in url
