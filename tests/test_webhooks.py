import json
from unittest.mock import patch


def test_get_webhooks_empty(client, tmp_path):
    wf = tmp_path / "webhooks.json"
    with patch("services.webhook_service.WEBHOOKS_FILE", wf):
        r = client.get("/api/webhooks")
    assert r.status_code == 200
    assert r.json() == []


def test_add_webhook(client, tmp_path):
    wf = tmp_path / "webhooks.json"
    with patch("services.webhook_service.WEBHOOKS_FILE", wf):
        r = client.post("/api/webhooks", json={"url": "http://example.com/hook"})
    assert r.status_code == 200
    assert "http://example.com/hook" in r.json()


def test_add_webhook_missing_url(client):
    r = client.post("/api/webhooks", json={"url": ""})
    assert r.status_code == 400


def test_delete_webhook_by_index(client, tmp_path):
    wf = tmp_path / "webhooks.json"
    wf.write_text(json.dumps(["http://example.com/hook"]))
    with patch("services.webhook_service.WEBHOOKS_FILE", wf):
        r = client.delete("/api/webhooks/0")
    assert r.status_code == 200
    assert r.json() == []


def test_delete_webhook_out_of_range(client, tmp_path):
    wf = tmp_path / "webhooks.json"
    with patch("services.webhook_service.WEBHOOKS_FILE", wf):
        r = client.delete("/api/webhooks/99")
    assert r.status_code == 404
