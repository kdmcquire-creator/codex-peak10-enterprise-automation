"""Tests for the Graph client wrapper without live network calls."""

from __future__ import annotations

from email_intel.graph_client import GraphClient, GraphClientConfig


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
