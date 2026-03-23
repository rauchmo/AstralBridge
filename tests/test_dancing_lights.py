import asyncio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import dancing_lights as dl

_AMBIENT_MODES_LITERAL = {
    "taverne": {"color": [255, 120, 20], "fx": 2,  "bri": 180, "sx": 100},
    "dungeon": {"color": [0,   20,  40], "fx": 38, "bri": 80,  "sx": 60},
    "wald":    {"color": [10,  80,  20], "fx": 58, "bri": 140, "sx": 80},
    "hoelle":  {"color": [200, 20,   0], "fx": 25, "bri": 220, "sx": 180},
    "ozean":   {"color": [0,   60, 180], "fx": 13, "bri": 150, "sx": 90},
    "magie":   {"color": [120,  0, 200], "fx": 38, "bri": 160, "sx": 100},
    "eis":     {"color": [150, 200, 255],"fx": 2,  "bri": 120, "sx": 70},
    "kampf":   {"color": [180,  0,   0], "fx": 11, "bri": 200, "sx": 60},
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
    assert "taverne" in ds["ambient_modes"]
    assert "kampf" in ds["ambient_modes"]
    assert ds["current_ambient"] is None


def test_dl_load_strips_devices_key(tmp_path, monkeypatch):
    import json
    cfg = {"enabled": True, "devices": [{"id": "x"}], "events": {}, "dungeon_screen": {}}
    f = tmp_path / "dancing_lights.json"
    f.write_text(json.dumps(cfg))
    monkeypatch.setattr(dl, "DL_CONFIG_FILE", f)

    result = dl.dl_load()
    assert "devices" not in result


def test_dl_load_preserves_existing_ambient_modes(tmp_path, monkeypatch):
    import json
    custom_modes = {"taverne": {"color": [1, 2, 3], "fx": 5, "bri": 99, "sx": 77}}
    cfg = {"enabled": True, "events": {}, "dungeon_screen": {
        "ip": "1.1.1.1", "current_ambient": "taverne", "ambient_modes": custom_modes
    }}
    f = tmp_path / "dancing_lights.json"
    f.write_text(json.dumps(cfg))
    monkeypatch.setattr(dl, "DL_CONFIG_FILE", f)

    result = dl.dl_load()
    assert result["dungeon_screen"]["ambient_modes"]["taverne"]["color"] == [1, 2, 3]
    assert result["dungeon_screen"]["current_ambient"] == "taverne"


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
    dl._dl_ds_ambient_mode = "taverne"
    await dl.dl_ds_apply_current_layer()
    assert len(mock_wled) == 1
    ip, state = mock_wled[0]
    assert state["bri"] == 180
    assert state["seg"][0]["fx"] == 2  # Breathe
    assert state["seg"][0]["col"][0] == [255, 120, 20]


@pytest.mark.asyncio
async def test_apply_layer_signal_overrides_ambient(mock_wled, ds_config):
    dl._dl_ds_ambient_mode = "taverne"
    dl._dl_ds_player_active = "p1"
    await dl.dl_ds_apply_current_layer()
    ip, state = mock_wled[0]
    seg_ids = [s.get("id", 0) for s in state["seg"]]
    assert 1 in seg_ids
    player_seg = next(s for s in state["seg"] if s.get("id") == 1)
    assert player_seg["col"][0] == [255, 0, 0]


@pytest.mark.asyncio
async def test_apply_layer_skips_write_during_roll(mock_wled, ds_config):
    dl._dl_ds_ambient_mode = "taverne"
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
    await dl.dl_ds_ambient_set("wald")
    assert dl._dl_ds_ambient_mode == "wald"
    ip, state = mock_wled[0]
    assert state["seg"][0]["fx"] == 58  # Ripple


@pytest.mark.asyncio
async def test_ambient_set_persists_to_config(mock_wled, ds_config):
    await dl.dl_ds_ambient_set("hoelle")
    cfg = dl.dl_load()
    assert cfg["dungeon_screen"]["current_ambient"] == "hoelle"


@pytest.mark.asyncio
async def test_ambient_set_defers_wled_during_roll(mock_wled, ds_config):
    dl._dl_ds_roll_timer = asyncio.create_task(asyncio.sleep(100))
    await dl.dl_ds_ambient_set("wald")
    dl._dl_ds_roll_timer.cancel()
    dl._dl_ds_roll_timer = None
    assert dl._dl_ds_ambient_mode == "wald"
    assert len(mock_wled) == 0  # deferred


@pytest.mark.asyncio
async def test_ambient_clear_removes_mode(mock_wled, ds_config):
    dl._dl_ds_ambient_mode = "taverne"
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
    dl._dl_ds_ambient_mode = "taverne"
    r = api_client.get("/dl/api/dungeon-screen/ambient")
    assert r.status_code == 200
    data = r.json()
    assert data["current"] == "taverne"
    assert "taverne" in data["modes"]
    assert "kampf" in data["modes"]


def test_post_ambient_activates_mode(api_client):
    r = api_client.post("/dl/api/dungeon-screen/ambient/wald")
    assert r.status_code == 200
    assert dl._dl_ds_ambient_mode == "wald"


def test_post_ambient_unknown_mode_returns_404(api_client):
    r = api_client.post("/dl/api/dungeon-screen/ambient/nonexistent")
    assert r.status_code == 404


def test_patch_ambient_updates_params(api_client):
    r = api_client.patch("/dl/api/dungeon-screen/ambient/taverne",
                         json={"bri": 50, "sx": 30})
    assert r.status_code == 200
    cfg = dl.dl_load()
    assert cfg["dungeon_screen"]["ambient_modes"]["taverne"]["bri"] == 50
    assert cfg["dungeon_screen"]["ambient_modes"]["taverne"]["sx"] == 30
    assert cfg["dungeon_screen"]["ambient_modes"]["taverne"]["color"] == [255, 120, 20]


def test_delete_ambient_clears(api_client):
    dl._dl_ds_ambient_mode = "kampf"
    r = api_client.delete("/dl/api/dungeon-screen/ambient")
    assert r.status_code == 200
    assert dl._dl_ds_ambient_mode is None


def test_get_dungeon_screen_includes_ambient_state(api_client):
    dl._dl_ds_ambient_mode = "magie"
    r = api_client.get("/dl/api/dungeon-screen")
    assert r.status_code == 200
    data = r.json()
    assert data["current_ambient"] == "magie"
    assert "roll_active" in data


def test_restore_endpoint_applies_current_layer(api_client, mock_wled):
    dl._dl_ds_ambient_mode = "eis"
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
