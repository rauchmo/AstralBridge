import os
from unittest.mock import patch, AsyncMock


def test_get_config_returns_env_vars(client, monkeypatch):
    monkeypatch.setenv("DDB_COBALT_TOKEN", "mytoken")
    monkeypatch.setenv("DDB_GAME_ID", "mygame")
    monkeypatch.setenv("DDB_USER_ID", "myuser")

    r = client.get("/api/config")
    assert r.status_code == 200
    data = r.json()
    assert data["DDB_COBALT_TOKEN"] == "mytoken"
    assert data["DDB_GAME_ID"] == "mygame"
    assert data["DDB_USER_ID"] == "myuser"


def test_post_config_updates_env(client, tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("")
    with patch("routes.config.ENV_PATH", env_file):
        r = client.post("/api/config", json={
            "DDB_COBALT_TOKEN": "newtoken",
            "DDB_GAME_ID": "newgame",
            "DDB_USER_ID": "newuser",
        })
    assert r.status_code == 200
    assert os.getenv("DDB_COBALT_TOKEN") == "newtoken"


def test_restart_returns_200(client):
    with patch("services.ddb_client.start_ddb_client"):
        r = client.post("/api/restart")
    assert r.status_code == 200
    assert r.json()["status"] == "restarting"


def test_get_status(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert "ddb_connected" in data
    assert "foundry_clients" in data
