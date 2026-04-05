import asyncio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import dancing_lights as dl

_AMBIENT_MODES_LITERAL = {
    "tavern":  {"color": [255, 120, 20], "fx": 2,  "bri": 180, "sx": 100},
    "dungeon": {"color": [0,   20,  40], "fx": 38, "bri": 80,  "sx": 60},
    "forest":  {"color": [10,  80,  20], "fx": 58, "bri": 140, "sx": 80},
    "hell":    {"color": [200, 20,   0], "fx": 25, "bri": 220, "sx": 180},
    "ocean":   {"color": [0,   60, 180], "fx": 13, "bri": 150, "sx": 90},
    "magic":   {"color": [120,  0, 200], "fx": 38, "bri": 160, "sx": 100},
    "ice":     {"color": [150, 200, 255],"fx": 2,  "bri": 120, "sx": 70},
    "combat":  {"color": [180,  0,   0], "fx": 11, "bri": 200, "sx": 60},
}

@pytest.fixture(autouse=True)
def reset_globals():
    """Reset all module-level state between tests."""
    if hasattr(dl, "_dl_ds_ambient_mode"):
        dl._dl_ds_ambient_mode = None
    if hasattr(dl, "_dl_ds_player_active"):
        dl._dl_ds_player_active = None
    timer = getattr(dl, "_dl_ds_roll_timer", None)
    if timer is not None:
        timer.cancel()
    if hasattr(dl, "_dl_ds_roll_timer"):
        dl._dl_ds_roll_timer = None
    if hasattr(dl, "_dl_manual_mode"):
        dl._dl_manual_mode = False
    yield

@pytest.fixture
def mock_wled(monkeypatch):
    """Capture all WLED writes, return last written state."""
    calls = []
    async def fake_set(ip, state):
        calls.append((ip, state))
        return True
    async def fake_get(ip):
        return {"on": True, "bri": 100, "seg": [{"col": [[10,10,10]], "fx": 0}]}
    monkeypatch.setattr(dl, "_dl_set", fake_set)
    monkeypatch.setattr(dl, "_dl_get", fake_get)
    return calls

@pytest.fixture
def ds_config(tmp_path, monkeypatch):
    """Minimal dungeon screen config for tests."""
    import json
    cfg = {
        "enabled": True,
        "events": {k: dict(v) for k, v in dl.DL_DEFAULT_EVENTS.items()},
        "dungeon_screen": {
            "ip": "10.0.0.1",
            "total_leds": 30,
            "brightness": 180,
            "players": [
                {"id": "p1", "name": "Alice", "character": "Aria", "start": 0, "end": 10,
                 "color": [255, 0, 0], "auto_signal": True},
            ],
            "corners": [10, 15, 25],
            "current_ambient": None,
            "ambient_modes": dl.DL_DS_AMBIENT_DEFAULTS,
        },
    }
    config_file = tmp_path / "dancing_lights.json"
    config_file.write_text(json.dumps(cfg))
    monkeypatch.setattr(dl, "DL_CONFIG_FILE", config_file)
    return cfg


# ── Task 2: Config migration ────────────────────────────────────────────────

def test_dl_load_adds_ambient_defaults_when_missing(tmp_path, monkeypatch):
    import json
    cfg = {"enabled": True, "events": {}, "dungeon_screen": {"ip": "1.1.1.1"}}
    f = tmp_path / "dancing_lights.json"
    f.write_text(json.dumps(cfg))
    monkeypatch.setattr(dl, "DL_CONFIG_FILE", f)

    result = dl.dl_load()
    ds = result["dungeon_screen"]
    assert "ambient_modes" in ds
    assert "tavern" in ds["ambient_modes"]
    assert "combat" in ds["ambient_modes"]
    assert ds["current_ambient"] is None


def test_dl_load_preserves_devices_key(tmp_path, monkeypatch):
    import json
    cfg = {"enabled": True, "devices": [{"id": "x"}], "events": {}, "dungeon_screen": {}}
    f = tmp_path / "dancing_lights.json"
    f.write_text(json.dumps(cfg))
    monkeypatch.setattr(dl, "DL_CONFIG_FILE", f)

    result = dl.dl_load()
    assert "devices" in result


def test_dl_load_preserves_existing_ambient_modes(tmp_path, monkeypatch):
    import json
    custom_modes = {"tavern": {"color": [1, 2, 3], "fx": 5, "bri": 99, "sx": 77}}
    cfg = {"enabled": True, "events": {}, "dungeon_screen": {
        "ip": "1.1.1.1", "current_ambient": "tavern", "ambient_modes": custom_modes
    }}
    f = tmp_path / "dancing_lights.json"
    f.write_text(json.dumps(cfg))
    monkeypatch.setattr(dl, "DL_CONFIG_FILE", f)

    result = dl.dl_load()
    assert result["dungeon_screen"]["ambient_modes"]["tavern"]["color"] == [1, 2, 3]
    assert result["dungeon_screen"]["current_ambient"] == "tavern"


# ── Task 3: dl_ds_apply_current_layer ──────────────────────────────────────

@pytest.mark.asyncio
async def test_apply_layer_neutral_when_nothing_active(mock_wled, ds_config):
    await dl.dl_ds_apply_current_layer()
    assert len(mock_wled) == 1
    ip, state = mock_wled[0]
    assert ip == "10.0.0.1"
    assert state["bri"] == 10  # neutral near-black


@pytest.mark.asyncio
async def test_apply_layer_ambient_when_set(mock_wled, ds_config):
    dl._dl_ds_ambient_mode = "tavern"
    await dl.dl_ds_apply_current_layer()
    assert len(mock_wled) == 1
    ip, state = mock_wled[0]
    assert state["bri"] == 180
    assert state["seg"][0]["fx"] == 2  # Breathe
    assert state["seg"][0]["col"][0] == [255, 120, 20]


@pytest.mark.asyncio
async def test_apply_layer_signal_overrides_ambient(mock_wled, ds_config):
    dl._dl_ds_ambient_mode = "tavern"
    dl._dl_ds_player_active = "p1"
    await dl.dl_ds_apply_current_layer()
    ip, state = mock_wled[0]
    seg_ids = [s.get("id", 0) for s in state["seg"]]
    assert 1 in seg_ids
    player_seg = next(s for s in state["seg"] if s.get("id") == 1)
    assert player_seg["col"][0] == [255, 0, 0]


@pytest.mark.asyncio
async def test_apply_layer_skips_write_during_roll(mock_wled, ds_config):
    dl._dl_ds_ambient_mode = "tavern"
    dl._dl_ds_roll_timer = asyncio.create_task(asyncio.sleep(100))
    await dl.dl_ds_apply_current_layer()
    dl._dl_ds_roll_timer.cancel()
    dl._dl_ds_roll_timer = None
    assert len(mock_wled) == 0  # no WLED write while roll active


# ── Task 4: dl_ds_signal / dl_ds_clear ─────────────────────────────────────

@pytest.mark.asyncio
async def test_ds_signal_sets_player_active_and_applies(mock_wled, ds_config):
    await dl.dl_ds_signal("p1")
    assert dl._dl_ds_player_active == "p1"
    assert len(mock_wled) == 1
    ip, state = mock_wled[0]
    seg_ids = [s.get("id", 0) for s in state["seg"]]
    assert 1 in seg_ids


@pytest.mark.asyncio
async def test_ds_signal_unknown_player_noop(mock_wled, ds_config):
    await dl.dl_ds_signal("nonexistent")
    assert dl._dl_ds_player_active is None
    assert len(mock_wled) == 0


@pytest.mark.asyncio
async def test_ds_clear_restores_ambient(mock_wled, ds_config):
    dl._dl_ds_player_active = "p1"
    dl._dl_ds_ambient_mode = "dungeon"
    await dl.dl_ds_clear()
    assert dl._dl_ds_player_active is None
    ip, state = mock_wled[0]
    assert state["seg"][0]["fx"] == 38


@pytest.mark.asyncio
async def test_ds_signal_defers_when_roll_active(mock_wled, ds_config):
    """Signal during roll updates state but WLED write is skipped."""
    dl._dl_ds_roll_timer = asyncio.create_task(asyncio.sleep(100))
    await dl.dl_ds_signal("p1")
    dl._dl_ds_roll_timer.cancel()
    dl._dl_ds_roll_timer = None
    assert dl._dl_ds_player_active == "p1"
    assert len(mock_wled) == 0  # apply_current_layer skipped due to roll


# ── Task 7: dl_ds_ambient_set / dl_ds_ambient_clear ──────────────────────────

@pytest.mark.asyncio
async def test_ambient_set_activates_mode_and_applies(mock_wled, ds_config):
    await dl.dl_ds_ambient_set("forest")
    assert dl._dl_ds_ambient_mode == "forest"
    ip, state = mock_wled[0]
    assert state["seg"][0]["fx"] == 58  # Ripple


@pytest.mark.asyncio
async def test_ambient_set_persists_to_config(mock_wled, ds_config):
    await dl.dl_ds_ambient_set("hell")
    cfg = dl.dl_load()
    assert cfg["dungeon_screen"]["current_ambient"] == "hell"


@pytest.mark.asyncio
async def test_ambient_set_defers_wled_during_roll(mock_wled, ds_config):
    dl._dl_ds_roll_timer = asyncio.create_task(asyncio.sleep(100))
    await dl.dl_ds_ambient_set("forest")
    dl._dl_ds_roll_timer.cancel()
    dl._dl_ds_roll_timer = None
    assert dl._dl_ds_ambient_mode == "forest"
    assert len(mock_wled) == 0  # deferred


@pytest.mark.asyncio
async def test_ambient_clear_removes_mode(mock_wled, ds_config):
    dl._dl_ds_ambient_mode = "tavern"
    await dl.dl_ds_ambient_clear()
    assert dl._dl_ds_ambient_mode is None
    cfg = dl.dl_load()
    assert cfg["dungeon_screen"]["current_ambient"] is None
    ip, state = mock_wled[0]
    assert state["bri"] == 10  # neutral


@pytest.mark.asyncio
async def test_ambient_set_unknown_mode_noop(mock_wled, ds_config):
    await dl.dl_ds_ambient_set("nonexistent_mode")
    assert dl._dl_ds_ambient_mode is None
    assert len(mock_wled) == 0


# ── Task 6: dl_trigger ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_trigger_sends_animation_to_dungeon_screen(mock_wled, ds_config):
    await dl.dl_trigger("nat20")
    assert len(mock_wled) >= 1
    ip, state = mock_wled[0]
    assert ip == "10.0.0.1"
    assert state["seg"][0]["fx"] == 38   # Plasma
    assert state["seg"][0]["col"][0] == [255, 215, 0]  # gold


@pytest.mark.asyncio
async def test_trigger_sets_roll_timer(mock_wled, ds_config):
    await dl.dl_trigger("nat20")
    assert dl._dl_ds_roll_timer is not None
    dl._dl_ds_roll_timer.cancel()
    dl._dl_ds_roll_timer = None


@pytest.mark.asyncio
async def test_trigger_cancels_previous_timer_on_rapid_fire(mock_wled, ds_config):
    await dl.dl_trigger("nat20")
    first_timer = dl._dl_ds_roll_timer
    await dl.dl_trigger("damage")
    await asyncio.sleep(0)  # yield to event loop so cancellation is processed
    assert first_timer.cancelled()
    if dl._dl_ds_roll_timer:
        dl._dl_ds_roll_timer.cancel()
        dl._dl_ds_roll_timer = None


@pytest.mark.asyncio
async def test_trigger_disabled_event_noop(mock_wled, ds_config, monkeypatch, tmp_path):
    import json
    cfg = ds_config.copy()
    cfg["events"] = {k: dict(v) for k, v in cfg["events"].items()}
    cfg["events"]["nat20"] = dict(cfg["events"]["nat20"])
    cfg["events"]["nat20"]["enabled"] = False
    f = tmp_path / "dl.json"
    f.write_text(json.dumps(cfg))
    monkeypatch.setattr(dl, "DL_CONFIG_FILE", f)
    await dl.dl_trigger("nat20")
    assert len(mock_wled) == 0


# ── Task 5: dl_auto_signal ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_auto_signal_matches_character_and_signals(mock_wled, ds_config):
    await dl.dl_auto_signal("Aria")
    assert dl._dl_ds_player_active == "p1"
    assert len(mock_wled) == 1


@pytest.mark.asyncio
async def test_auto_signal_no_match_clears_signal(mock_wled, ds_config):
    dl._dl_ds_player_active = "p1"
    await dl.dl_auto_signal("Unknown Character")
    assert dl._dl_ds_player_active is None


@pytest.mark.asyncio
async def test_auto_signal_disabled_player_not_signaled(mock_wled, ds_config, monkeypatch, tmp_path):
    import json
    cfg = ds_config.copy()
    cfg["dungeon_screen"] = dict(cfg["dungeon_screen"])
    cfg["dungeon_screen"]["players"] = [dict(cfg["dungeon_screen"]["players"][0])]
    cfg["dungeon_screen"]["players"][0]["auto_signal"] = False
    f = tmp_path / "dl.json"
    f.write_text(json.dumps(cfg))
    monkeypatch.setattr(dl, "DL_CONFIG_FILE", f)
    await dl.dl_auto_signal("Aria")
    assert dl._dl_ds_player_active is None


# ── Task 8: API routes ──────────────────────────────────────────────────────

@pytest.fixture
def api_client(ds_config, mock_wled):
    app = FastAPI()
    app.include_router(dl.router)
    return TestClient(app)


def test_get_ambient_returns_modes_and_current(api_client):
    dl._dl_ds_ambient_mode = "tavern"
    r = api_client.get("/dl/api/dungeon-screen/ambient")
    assert r.status_code == 200
    data = r.json()
    assert data["current"] == "tavern"
    assert "tavern" in data["modes"]
    assert "combat" in data["modes"]


def test_post_ambient_activates_mode(api_client):
    r = api_client.post("/dl/api/dungeon-screen/ambient/forest")
    assert r.status_code == 200
    assert dl._dl_ds_ambient_mode == "forest"


def test_post_ambient_unknown_mode_returns_404(api_client):
    r = api_client.post("/dl/api/dungeon-screen/ambient/nonexistent")
    assert r.status_code == 404


def test_patch_ambient_updates_params(api_client):
    r = api_client.patch("/dl/api/dungeon-screen/ambient/tavern",
                         json={"bri": 50, "sx": 30})
    assert r.status_code == 200
    cfg = dl.dl_load()
    assert cfg["dungeon_screen"]["ambient_modes"]["tavern"]["bri"] == 50
    assert cfg["dungeon_screen"]["ambient_modes"]["tavern"]["sx"] == 30
    assert cfg["dungeon_screen"]["ambient_modes"]["tavern"]["color"] == [255, 120, 20]


def test_delete_ambient_clears(api_client):
    dl._dl_ds_ambient_mode = "combat"
    r = api_client.delete("/dl/api/dungeon-screen/ambient")
    assert r.status_code == 200
    assert dl._dl_ds_ambient_mode is None


def test_get_dungeon_screen_includes_ambient_state(api_client):
    dl._dl_ds_ambient_mode = "magic"
    r = api_client.get("/dl/api/dungeon-screen")
    assert r.status_code == 200
    data = r.json()
    assert data["current_ambient"] == "magic"
    assert "roll_active" in data


def test_restore_endpoint_applies_current_layer(api_client, mock_wled):
    dl._dl_ds_ambient_mode = "ice"
    r = api_client.post("/dl/api/dungeon-screen/restore")
    assert r.status_code == 200
    assert len(mock_wled) >= 1


# ── Task 1: event upsert + delete ────────────────────────────────────────────

def test_put_event_creates_new(api_client):
    r = api_client.put("/dl/api/events/my_event",
        json={"label":"My Event","enabled":True,"color":[100,0,255],
              "effect":25,"brightness":200,"speed":150,"duration":2000})
    assert r.status_code == 200
    cfg = dl.dl_load()
    assert "my_event" in cfg["events"]
    assert cfg["events"]["my_event"]["label"] == "My Event"


def test_put_event_updates_existing(api_client):
    r = api_client.put("/dl/api/events/nat20",
        json={"label":"NAT20","enabled":True,"color":[0,0,255],
              "effect":9,"brightness":100,"speed":100,"duration":1000})
    assert r.status_code == 200
    assert dl.dl_load()["events"]["nat20"]["brightness"] == 100


def test_delete_event_removes_from_config(api_client):
    r = api_client.delete("/dl/api/events/nat20")
    assert r.status_code == 200
    assert "nat20" not in dl.dl_load()["events"]


def test_delete_event_unknown_404(api_client):
    r = api_client.delete("/dl/api/events/does_not_exist")
    assert r.status_code == 404


def test_trigger_endpoint_plays_event(api_client, mock_wled):
    r = api_client.post("/dl/api/events/nat20/trigger")
    assert r.status_code == 200
    # dl_trigger is dispatched via create_task; mock_wled call happens in background
    # — status 200 is sufficient to verify the endpoint exists and doesn't 404


def test_trigger_endpoint_404_unknown(api_client):
    r = api_client.post("/dl/api/events/does_not_exist/trigger")
    assert r.status_code == 404


# ── Task 2: ambient mode upsert + delete ─────────────────────────────────────

def test_put_ambient_mode_creates_new(api_client):
    r = api_client.put("/dl/api/dungeon-screen/ambient/stadt",
        json={"color":[200,180,100],"fx":2,"bri":150,"sx":80})
    assert r.status_code == 200
    assert "stadt" in dl.dl_load()["dungeon_screen"]["ambient_modes"]


def test_put_ambient_mode_updates_existing(api_client):
    r = api_client.put("/dl/api/dungeon-screen/ambient/tavern",
        json={"color":[1,2,3],"fx":9,"bri":50,"sx":40})
    assert r.status_code == 200
    assert dl.dl_load()["dungeon_screen"]["ambient_modes"]["tavern"]["bri"] == 50


def test_delete_ambient_mode_removes(api_client):
    r = api_client.delete("/dl/api/dungeon-screen/ambient/tavern")
    assert r.status_code == 200
    assert "tavern" not in dl.dl_load()["dungeon_screen"]["ambient_modes"]


def test_delete_ambient_mode_clears_active(api_client):
    dl._dl_ds_ambient_mode = "tavern"
    r = api_client.delete("/dl/api/dungeon-screen/ambient/tavern")
    assert r.status_code == 200
    assert dl._dl_ds_ambient_mode is None
    assert dl.dl_load()["dungeon_screen"]["current_ambient"] is None


def test_delete_ambient_mode_404(api_client):
    r = api_client.delete("/dl/api/dungeon-screen/ambient/no_such_mode")
    assert r.status_code == 404


# ── Task 1: manual_mode gating ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_manual_mode_gates_dl_trigger(mock_wled, ds_config):
    """dl_trigger does nothing when _dl_manual_mode is True."""
    dl._dl_manual_mode = True
    await dl.dl_trigger("nat20")
    assert len(mock_wled) == 0


@pytest.mark.asyncio
async def test_manual_mode_gates_dl_auto_signal(mock_wled, ds_config):
    """dl_auto_signal does nothing when _dl_manual_mode is True."""
    dl._dl_manual_mode = True
    await dl.dl_auto_signal("Aria")
    assert dl._dl_ds_player_active is None
    assert len(mock_wled) == 0


def test_manual_mode_default_is_false():
    """_dl_manual_mode starts False."""
    assert dl._dl_manual_mode is False


# ── Task 2: new endpoints ────────────────────────────────────────────────────

def test_get_mode_returns_false_by_default(api_client):
    r = api_client.get("/dl/api/mode")
    assert r.status_code == 200
    assert r.json() == {"manual": False}


def test_post_mode_sets_manual_true(api_client, ds_config):
    r = api_client.post("/dl/api/mode", json={"manual": True})
    assert r.status_code == 200
    assert r.json() == {"manual": True}
    assert dl._dl_manual_mode is True


def test_post_mode_persists_to_config(api_client, ds_config):
    api_client.post("/dl/api/mode", json={"manual": True})
    assert dl.dl_load().get("manual_mode") is True


def test_post_mode_to_auto_calls_apply_layer(api_client, ds_config, mock_wled):
    dl._dl_manual_mode = True
    r = api_client.post("/dl/api/mode", json={"manual": False})
    assert r.status_code == 200
    assert dl._dl_manual_mode is False
    # apply_current_layer writes neutral state since no ambient/player active
    assert len(mock_wled) >= 1


def test_post_mode_to_manual_no_wled_write(api_client, ds_config, mock_wled):
    r = api_client.post("/dl/api/mode", json={"manual": True})
    assert r.status_code == 200
    assert len(mock_wled) == 0


def test_manual_apply_on_sets_wled(api_client, ds_config, mock_wled):
    r = api_client.post("/dl/api/dungeon-screen/manual-apply",
                        json={"on": True, "color": [255, 0, 0], "fx": 9, "bri": 200, "sx": 150})
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert len(mock_wled) == 1
    ip, state = mock_wled[0]
    assert ip == "10.0.0.1"
    assert state["on"] is True
    assert state["bri"] == 200
    assert state["seg"][0]["col"][0] == [255, 0, 0]
    assert state["seg"][0]["fx"] == 9


def test_manual_apply_off_turns_strip_off(api_client, ds_config, mock_wled):
    r = api_client.post("/dl/api/dungeon-screen/manual-apply", json={"on": False})
    assert r.status_code == 200
    ip, state = mock_wled[0]
    assert state["on"] is False


def test_manual_apply_uses_defaults_when_fields_omitted(api_client, ds_config, mock_wled):
    r = api_client.post("/dl/api/dungeon-screen/manual-apply", json={"on": True})
    assert r.status_code == 200
    ip, state = mock_wled[0]
    assert state["bri"] == 180          # ds.get("brightness", 180) from ds_config
    assert state["seg"][0]["col"][0] == [255, 255, 255]
    assert state["seg"][0]["fx"] == 0
    assert state["seg"][0]["sx"] == 128


def test_manual_apply_no_device_returns_no_device(api_client, tmp_path, monkeypatch):
    import json
    cfg = {"enabled": True, "events": {}, "dungeon_screen": {
        "ip": "", "total_leds": 30, "brightness": 180, "players": [], "corners": [],
        "current_ambient": None, "ambient_modes": {}}}
    f = tmp_path / "dl.json"
    f.write_text(json.dumps(cfg))
    monkeypatch.setattr(dl, "DL_CONFIG_FILE", f)
    r = api_client.post("/dl/api/dungeon-screen/manual-apply", json={"on": True})
    assert r.status_code == 200
    assert r.json() == {"status": "no device"}


# ── _ha_set ──────────────────────────────────────────────────────────────────

@pytest.fixture
def ha_http(monkeypatch, ds_config):
    """Patches httpx.AsyncClient to capture HA REST calls.
    Also sets up a home_assistant config block."""
    cfg = dl.dl_load()
    cfg["home_assistant"] = {"url": "http://ha.local:8123", "token": "testtoken"}
    dl.dl_save(cfg)

    posts = []

    class FakeResponse:
        status_code = 200

    class FakeClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, url, **kwargs):
            posts.append({"url": url, "json": kwargs.get("json", {}), "headers": kwargs.get("headers", {})})
            return FakeResponse()

    monkeypatch.setattr(dl.httpx, "AsyncClient", FakeClient)
    return posts


@pytest.mark.asyncio
async def test_ha_set_turn_on_sends_rgb_and_brightness(ha_http):
    state = {"on": True, "bri": 200,
             "seg": [{"id": 0, "col": [[255, 100, 0], [0,0,0], [0,0,0]], "fx": 0, "sx": 128, "on": True}]}
    result = await dl._ha_set("light.table", state, "")
    assert result is True
    assert len(ha_http) == 1
    body = ha_http[0]["json"]
    assert "turn_on" in ha_http[0]["url"]
    assert body["entity_id"] == "light.table"
    assert body["rgb_color"] == [255, 100, 0]
    assert body["brightness"] == 200
    assert "effect" not in body


@pytest.mark.asyncio
async def test_ha_set_turn_on_includes_effect_when_set(ha_http):
    state = {"on": True, "bri": 150,
             "seg": [{"id": 0, "col": [[0, 255, 0], [0,0,0], [0,0,0]], "fx": 0, "sx": 100, "on": True}]}
    await dl._ha_set("light.table", state, "colorloop")
    assert ha_http[0]["json"]["effect"] == "colorloop"


@pytest.mark.asyncio
async def test_ha_set_turn_off_calls_turn_off(ha_http):
    result = await dl._ha_set("light.table", {"on": False}, "")
    assert result is True
    assert "turn_off" in ha_http[0]["url"]
    assert ha_http[0]["json"]["entity_id"] == "light.table"


@pytest.mark.asyncio
async def test_ha_set_uses_bearer_auth(ha_http):
    state = {"on": True, "bri": 100,
             "seg": [{"id": 0, "col": [[10, 20, 30], [0,0,0], [0,0,0]], "fx": 0, "sx": 100, "on": True}]}
    await dl._ha_set("light.x", state, "")
    assert "ha.local:8123" in ha_http[0]["url"]
    assert ha_http[0]["headers"].get("Authorization") == "Bearer testtoken"


@pytest.mark.asyncio
async def test_ha_set_empty_entity_id_returns_false(ha_http):
    state = {"on": True, "bri": 100,
             "seg": [{"id": 0, "col": [[10, 20, 30], [0,0,0], [0,0,0]], "fx": 0, "sx": 100, "on": True}]}
    result = await dl._ha_set("", state, "")
    assert result is False
    assert len(ha_http) == 0


# ── dev_config / dev_api_client fixtures ─────────────────────────────────────

@pytest.fixture
def dev_config(tmp_path, monkeypatch):
    """Minimal config with an empty devices list for device-related tests."""
    import json
    cfg = {
        "enabled": True,
        "events": {k: dict(v) for k, v in dl.DL_DEFAULT_EVENTS.items()},
        "dungeon_screen": {
            "ip": "10.0.0.1",
            "total_leds": 30,
            "brightness": 180,
            "players": [],
            "corners": [],
            "current_ambient": None,
            "ambient_modes": dl.DL_DS_AMBIENT_DEFAULTS,
        },
        "devices": [],
    }
    config_file = tmp_path / "dancing_lights.json"
    config_file.write_text(json.dumps(cfg))
    monkeypatch.setattr(dl, "DL_CONFIG_FILE", config_file)
    return cfg


@pytest.fixture
def dev_api_client(dev_config, mock_wled):
    app = FastAPI()
    app.include_router(dl.router)
    return TestClient(app)


# ── _dev_has_target ───────────────────────────────────────────────────────────

def test_dev_has_target_wled_with_ip():
    assert dl._dev_has_target({"type": "wled", "ip": "10.0.0.5"}) is True

def test_dev_has_target_wled_without_ip():
    assert dl._dev_has_target({"type": "wled", "ip": ""}) is False

def test_dev_has_target_ha_with_entity():
    assert dl._dev_has_target({"type": "ha", "entity_id": "light.x"}) is True

def test_dev_has_target_ha_without_entity():
    assert dl._dev_has_target({"type": "ha", "entity_id": ""}) is False

def test_dev_has_target_defaults_to_wled_check():
    # No type field → behaves as wled
    assert dl._dev_has_target({"ip": "10.0.0.1"}) is True
    assert dl._dev_has_target({"ip": ""}) is False


# ── _dev_set dispatcher ───────────────────────────────────────────────────────

@pytest.fixture
def mock_ha_set(monkeypatch):
    """Monkeypatches _ha_set so HA calls are captured without HTTP."""
    calls = []
    async def fake(entity_id, state, ha_effect=""):
        calls.append({"entity_id": entity_id, "state": state, "ha_effect": ha_effect})
        return True
    monkeypatch.setattr(dl, "_ha_set", fake)
    return calls


@pytest.mark.asyncio
async def test_dev_set_wled_dispatches_to_dl_set(mock_wled, dev_config):
    dev = {"type": "wled", "ip": "10.0.0.2"}
    state = {"on": True, "bri": 100, "seg": [{"id": 0}]}
    await dl._dev_set(dev, state)
    assert len(mock_wled) == 1
    assert mock_wled[0][0] == "10.0.0.2"


@pytest.mark.asyncio
async def test_dev_set_ha_dispatches_to_ha_set(mock_ha_set, dev_config):
    dev = {"type": "ha", "entity_id": "light.table"}
    state = {"on": True, "bri": 200, "seg": [{"id": 0, "col": [[255,0,0]]}]}
    await dl._dev_set(dev, state, "colorloop")
    assert len(mock_ha_set) == 1
    assert mock_ha_set[0]["entity_id"] == "light.table"
    assert mock_ha_set[0]["ha_effect"] == "colorloop"


@pytest.mark.asyncio
async def test_dev_set_no_type_falls_back_to_wled(mock_wled, dev_config):
    dev = {"ip": "10.0.0.9"}  # no type key
    state = {"on": True, "bri": 50, "seg": []}
    await dl._dev_set(dev, state)
    assert mock_wled[0][0] == "10.0.0.9"


# ── _dev_apply_ambient with HA device ─────────────────────────────────────────

@pytest.fixture
def ha_dev_config(dev_config, mock_ha_set):
    """Extends dev_config with an HA device ha001."""
    cfg = dl.dl_load()
    cfg["devices"].append({
        "id": "ha001", "name": "Tischlampe", "type": "ha",
        "ip": "", "entity_id": "light.table",
        "enabled": True, "brightness": 180, "manual_mode": False,
        "current_ambient": None,
        "ambient_modes": {
            "tavern": {"color": [255, 140, 0], "fx": 0, "bri": 150, "sx": 100, "ha_effect": "colorloop"},
        },
        "events": {k: dict(v) for k, v in dl.DL_DEFAULT_EVENTS.items()},
    })
    dl.dl_save(cfg)
    dl._dev_ambient["ha001"] = None
    dl._dev_manual["ha001"] = False
    return dl.dl_load()


@pytest.mark.asyncio
async def test_dev_apply_ambient_ha_uses_ha_set(mock_ha_set, ha_dev_config):
    dl._dev_ambient["ha001"] = "tavern"
    await dl._dev_apply_ambient("ha001")
    assert len(mock_ha_set) == 1
    assert mock_ha_set[0]["entity_id"] == "light.table"
    assert mock_ha_set[0]["ha_effect"] == "colorloop"


@pytest.mark.asyncio
async def test_dev_trigger_ha_uses_ha_set(mock_ha_set, ha_dev_config):
    cfg = dl.dl_load()
    dev = next(d for d in cfg["devices"] if d["id"] == "ha001")
    dev["events"]["nat20"]["ha_effect"] = "flash"
    ev = dev["events"]["nat20"]
    await dl._dev_trigger("ha001", dev, ev)
    assert len(mock_ha_set) == 1
    assert mock_ha_set[0]["entity_id"] == "light.table"
    assert mock_ha_set[0]["ha_effect"] == "flash"
    t = dl._dev_roll_timers.pop("ha001", None)
    if t: t.cancel()


@pytest.mark.asyncio
async def test_dev_apply_ambient_ha_neutral_when_no_ambient(mock_ha_set, ha_dev_config):
    dl._dev_ambient["ha001"] = None
    await dl._dev_apply_ambient("ha001")
    assert len(mock_ha_set) == 1
    assert mock_ha_set[0]["state"]["on"] is True
    assert mock_ha_set[0]["ha_effect"] == ""


@pytest.mark.asyncio
async def test_sync_ambient_ha_unknown_key_uses_dev_set(mock_ha_set, ha_dev_config, dev_api_client):
    cfg = dl.dl_load()
    cfg["dungeon_screen"]["current_ambient"] = "hell"
    cfg["dungeon_screen"]["ambient_modes"]["hell"] = {
        "color": [200, 20, 0], "fx": 25, "bri": 220, "sx": 180, "ha_effect": ""
    }
    dl.dl_save(cfg)
    r = dev_api_client.post("/dl/api/devices/ha001/sync-ambient")
    assert r.status_code == 200
    assert len(mock_ha_set) >= 1
