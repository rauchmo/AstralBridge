from unittest.mock import AsyncMock, patch


def _entry(**kwargs):
    base = {
        "id": "r1", "ts": "12:00:00", "character": "Gandalf",
        "entity_id": "1", "entity_type": "character", "game_id": "g1",
        "action": "Fireball", "rollType": "damage",
        "total": 18, "text": "18", "dice": [], "constant": 0,
    }
    base.update(kwargs)
    return base


def test_get_rolls_empty(client):
    r = client.get("/api/rolls")
    assert r.status_code == 200
    assert r.json() == []


def test_get_rolls_returns_history(client):
    from services.roll_store import roll_history, roll_index
    entry = _entry()
    roll_history.appendleft(entry)
    roll_index["r1"] = {**entry, "raw": {}}

    r = client.get("/api/rolls")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["character"] == "Gandalf"


def test_get_roll_detail_200(client):
    from services.roll_store import roll_history, roll_index
    entry = _entry(id="xyz", character="Frodo")
    roll_history.appendleft(entry)
    roll_index["xyz"] = {**entry, "raw": {}}

    r = client.get("/api/rolls/xyz")
    assert r.status_code == 200
    assert r.json()["character"] == "Frodo"


def test_get_roll_detail_404(client):
    r = client.get("/api/rolls/nonexistent")
    assert r.status_code == 404


def test_delete_rolls_clears_state(client):
    from services.roll_store import roll_history, roll_index
    entry = _entry()
    roll_history.appendleft(entry)
    roll_index["r1"] = {**entry, "raw": {}}

    r = client.delete("/api/rolls")
    assert r.status_code == 200
    assert len(roll_history) == 0
    assert len(roll_index) == 0


def test_resend_roll_200(client):
    from services.roll_store import roll_index
    roll_index["r1"] = {
        "id": "r1", "character": "Aragorn", "action": "Attack",
        "rollType": "to hit", "total": 20, "text": "20",
        "constant": 0, "dice": [], "raw": {},
    }
    with patch("routes.rolls.broadcast_to_foundry", new_callable=AsyncMock):
        r = client.post("/api/rolls/r1/resend")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_resend_roll_404(client):
    r = client.post("/api/rolls/missing/resend")
    assert r.status_code == 404
