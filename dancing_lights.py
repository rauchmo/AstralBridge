import asyncio
import json
import uuid
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException

from logger import DATA_DIR, log

DL_CONFIG_FILE = DATA_DIR / "dancing_lights.json"

DL_DEFAULT_EVENTS = {
    "nat20":      {"label": "Nat 20",       "enabled": True,  "color": [255, 215, 0], "effect": 38, "brightness": 255, "speed": 220, "duration": 3500},
    "nat1":       {"label": "Nat 1",        "enabled": True,  "color": [140, 0, 0],   "effect": 11, "brightness": 180, "speed": 200, "duration": 2500},
    "damage":     {"label": "Damage",       "enabled": True,  "color": [255, 50, 0],  "effect": 25, "brightness": 230, "speed": 200, "duration": 2000},
    "heal":       {"label": "Heal",         "enabled": True,  "color": [0, 220, 90],  "effect": 2,  "brightness": 200, "speed": 150, "duration": 2500},
    "initiative": {"label": "Initiative",   "enabled": True,  "color": [80, 80, 255], "effect": 58, "brightness": 200, "speed": 180, "duration": 2000},
    "save":       {"label": "Saving Throw", "enabled": False, "color": [160, 0, 255], "effect": 17, "brightness": 180, "speed": 150, "duration": 1500},
    "check":      {"label": "Ability Check","enabled": False, "color": [0, 160, 200], "effect": 77, "brightness": 160, "speed": 150, "duration": 1500},
    "attack":     {"label": "Attack Roll",  "enabled": False, "color": [220, 100, 0], "effect": 9,  "brightness": 200, "speed": 200, "duration": 1500},
}

DL_DS_AMBIENT_DEFAULTS = {
    "tavern":  {"color": [255, 120,  20], "fx":  2, "bri": 180, "sx": 100},
    "dungeon": {"color": [  0,  20,  40], "fx": 38, "bri":  80, "sx":  60},
    "forest":  {"color": [ 10,  80,  20], "fx": 58, "bri": 140, "sx":  80},
    "hell":    {"color": [200,  20,   0], "fx": 25, "bri": 220, "sx": 180},
    "ocean":   {"color": [  0,  60, 180], "fx": 13, "bri": 150, "sx":  90},
    "magic":   {"color": [120,   0, 200], "fx": 38, "bri": 160, "sx": 100},
    "ice":     {"color": [150, 200, 255], "fx":  2, "bri": 120, "sx":  70},
    "combat":  {"color": [180,   0,   0], "fx": 11, "bri": 200, "sx":  60},
}

_DL_DS_DEFAULT = {"ip": "", "total_leds": 60, "brightness": 180, "players": [], "corners": []}

# Layer state — _dl_ds_roll_timer is not None means roll is active
_dl_ds_ambient_mode: Optional[str] = None
_dl_ds_player_active: Optional[str] = None
_dl_ds_roll_timer: Optional[asyncio.Task] = None
_dl_manual_mode: bool = False

# Extra segments 2-7 (segment 0=background strip, segment 1=player signal; 2-7 unused)
_DL_DS_EXTRA_SEGS_OFF = [{"id": i, "on": False, "stop": 0} for i in range(2, 8)]
# Neutral disables ALL extra segs 1-7 (no player signal active, so seg 1 must also be off)
_DL_DS_NEUTRAL = {"on": True, "bri": 10, "seg": [{"id": 0, "col": [[5, 5, 10]], "fx": 0, "on": True}, *[{"id": i, "on": False, "stop": 0} for i in range(1, 8)]]}


# ── Config helpers ─────────────────────────────────────────────────────────

def dl_load() -> dict:
    if not DL_CONFIG_FILE.exists():
        return {
            "enabled": False,
            "events": {k: dict(v) for k, v in DL_DEFAULT_EVENTS.items()},
            "dungeon_screen": {**_DL_DS_DEFAULT, "current_ambient": None, "ambient_modes": dict(DL_DS_AMBIENT_DEFAULTS)},
        }
    try:
        cfg = json.loads(DL_CONFIG_FILE.read_text())
        cfg.setdefault("enabled", False)
        cfg.pop("devices", None)  # removed — all animations on dungeon screen
        cfg.setdefault("dungeon_screen", dict(_DL_DS_DEFAULT))
        ds = cfg["dungeon_screen"]
        ds.setdefault("current_ambient", None)
        ds.setdefault("ambient_modes", dict(DL_DS_AMBIENT_DEFAULTS))
        cfg.setdefault("events", {})
        return cfg
    except Exception:
        return {
            "enabled": False,
            "events": {k: dict(v) for k, v in DL_DEFAULT_EVENTS.items()},
            "dungeon_screen": {**_DL_DS_DEFAULT, "current_ambient": None, "ambient_modes": dict(DL_DS_AMBIENT_DEFAULTS)},
        }


def dl_save(cfg: dict):
    DL_CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


def dl_get_ds() -> dict:
    return dl_load().get("dungeon_screen", dict(_DL_DS_DEFAULT))


def dl_save_ds(ds: dict):
    cfg = dl_load()
    cfg["dungeon_screen"] = ds
    dl_save(cfg)


# ── Layer state helper ─────────────────────────────────────────────────────

async def dl_ds_apply_current_layer():
    """Apply the highest active layer to the dungeon screen WLED device.
    If a roll animation is in progress (_dl_ds_roll_timer is not None), skip — roll has priority.
    """
    if _dl_ds_roll_timer is not None:
        return  # roll playing, don't interrupt
    ds = dl_get_ds()
    ip = ds.get("ip", "")
    if not ip:
        return

    # Layer 1: player signal
    if _dl_ds_player_active:
        player = next((p for p in ds.get("players", []) if p["id"] == _dl_ds_player_active), None)
        if player:
            total = ds.get("total_leds", 60)
            state = {
                "on": True, "bri": ds.get("brightness", 180), "transition": 2,
                "seg": [
                    {"id": 0, "start": 0, "stop": total, "col": [[5, 5, 20]], "fx": 0, "on": True},
                    {"id": 1, "start": player["start"], "stop": player["end"],
                     "col": [player["color"], [0, 0, 0], [0, 0, 0]], "fx": 9, "sx": 180, "on": True},
                    *_DL_DS_EXTRA_SEGS_OFF,
                ],
            }
            await _dl_set(ip, state)
            return

    # Layer 0: ambient
    if _dl_ds_ambient_mode:
        cfg = dl_load()
        modes = cfg["dungeon_screen"].get("ambient_modes", DL_DS_AMBIENT_DEFAULTS)
        m = modes.get(_dl_ds_ambient_mode)
        if m:
            state = {
                "on": True, "bri": m["bri"], "transition": 2,
                "seg": [
                    {"id": 0, "col": [m["color"], [0, 0, 0], [0, 0, 0]], "fx": m["fx"], "sx": m["sx"], "on": True},
                    *[{"id": i, "on": False, "stop": 0} for i in range(1, 8)],
                ],
            }
            await _dl_set(ip, state)
            return

    # Nothing active — near-black neutral
    await _dl_set(ip, _DL_DS_NEUTRAL)


# ── WLED low-level helpers ─────────────────────────────────────────────────

async def _dl_get(ip: str) -> Optional[dict]:
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"http://{ip}/json/state")
            return r.json()
    except Exception:
        return None


async def _dl_set(ip: str, state: dict) -> bool:
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.post(f"http://{ip}/json/state", json=state)
            return r.status_code == 200
    except Exception:
        return False


# ── Event detection & triggering ───────────────────────────────────────────

def dl_detect_event(msg: dict) -> Optional[str]:
    """Map AstralBridge roll message (dice={faces,result}) to a DL event name.
    DnD Beyond rollType values: 'to hit', 'damage', 'roll' (initiative/saves),
    'check' (ability checks), 'heal'.
    """
    roll_type = (msg.get("rollType") or "").lower()
    action = (msg.get("action") or "").lower()
    dice = msg.get("dice", [])

    if roll_type == "to hit":
        d20 = next((d["result"] for d in dice if d.get("faces") == 20), None)
        if d20 == 20: return "nat20"
        if d20 == 1:  return "nat1"
        return "attack"

    if roll_type == "roll":
        if "initiative" in action:
            return "initiative"
        return "save"

    return {"damage": "damage", "heal": "heal", "check": "check"}.get(roll_type)


async def dl_trigger(event_name: str):
    """Layer 2: play a roll animation on the dungeon screen.
    Cancels any pending restore timer (rapid-fire safe), then restores via layer model.
    """
    if _dl_manual_mode:
        return
    global _dl_ds_roll_timer
    cfg = dl_load()
    if not cfg.get("enabled"):
        return
    ev = cfg.get("events", {}).get(event_name)
    if not ev or not ev.get("enabled"):
        return
    ds = cfg.get("dungeon_screen", {})
    ip = ds.get("ip", "")
    if not ip:
        return

    color = ev.get("color", [255, 255, 255])
    effect = ev.get("effect", 0)
    bri = ev.get("brightness", 200)
    speed = ev.get("speed", 128)
    duration_ms = ev.get("duration", 2000)

    anim = {
        "on": True, "bri": bri, "transition": 2,
        "seg": [
            {"id": 0, "col": [color, [0, 0, 0], [0, 0, 0]], "fx": effect, "sx": speed, "on": True},
            *[{"id": i, "on": False, "stop": 0} for i in range(1, 8)],
        ],
    }

    # Cancel previous restore if rapid successive rolls
    if _dl_ds_roll_timer is not None:
        _dl_ds_roll_timer.cancel()
        _dl_ds_roll_timer = None

    await _dl_set(ip, anim)

    async def _restore():
        global _dl_ds_roll_timer
        await asyncio.sleep(duration_ms / 1000)
        _dl_ds_roll_timer = None
        await dl_ds_apply_current_layer()

    _dl_ds_roll_timer = asyncio.create_task(_restore())


# ── Dungeon Screen signals ─────────────────────────────────────────────────

async def dl_ds_signal(player_id: str):
    """Set Layer 1 (player signal). Applies immediately unless roll is active."""
    global _dl_ds_player_active
    ds = dl_get_ds()
    if not ds.get("ip"):
        return
    player = next((p for p in ds.get("players", []) if p["id"] == player_id), None)
    if not player:
        return
    _dl_ds_player_active = player_id
    await dl_ds_apply_current_layer()


async def dl_ds_clear():
    """Clear Layer 1 (player signal) and apply next lower layer."""
    global _dl_ds_player_active
    _dl_ds_player_active = None
    await dl_ds_apply_current_layer()


async def dl_auto_signal(character: str):
    """Map DnD Beyond character name → player id and set Layer 1.
    If no match (or auto_signal disabled), clear the player signal.
    Called on every roll and combat turn change from bridge.py.
    """
    if _dl_manual_mode:
        return
    global _dl_ds_player_active
    if not character:
        return
    cfg = dl_load()
    if not cfg.get("enabled"):
        return
    ds = cfg.get("dungeon_screen", {})
    players = ds.get("players", [])
    matched = next(
        (p for p in players if p.get("auto_signal") and p.get("character") == character),
        None,
    )
    if matched:
        await dl_ds_signal(matched["id"])
    else:
        _dl_ds_player_active = None
        await dl_ds_apply_current_layer()


async def dl_ds_ambient_set(mode: str):
    """Activate ambient mode (Layer 0). Persists to config.
    If a roll is in progress, defers the WLED write until roll ends.
    """
    global _dl_ds_ambient_mode
    cfg = dl_load()
    modes = cfg["dungeon_screen"].get("ambient_modes", DL_DS_AMBIENT_DEFAULTS)
    if mode not in modes:
        return  # unknown key — noop
    _dl_ds_ambient_mode = mode
    cfg["dungeon_screen"]["current_ambient"] = mode
    dl_save(cfg)
    await dl_ds_apply_current_layer()


async def dl_ds_ambient_clear():
    """Deactivate ambient mode. Persists null to config."""
    global _dl_ds_ambient_mode
    _dl_ds_ambient_mode = None
    cfg = dl_load()
    cfg["dungeon_screen"]["current_ambient"] = None
    dl_save(cfg)
    await dl_ds_apply_current_layer()


# ── Manual mode init ────────────────────────────────────────────────────────

def _dl_load_manual_mode():
    global _dl_manual_mode
    _dl_manual_mode = dl_load().get("manual_mode", False)

_dl_load_manual_mode()


# ── API Router ─────────────────────────────────────────────────────────────

router = APIRouter(prefix="/dl")


@router.get("/api/config")
async def dl_api_get_config():
    cfg = dl_load()
    return {"enabled": cfg.get("enabled", False)}


@router.post("/api/config")
async def dl_api_set_config(body: dict):
    cfg = dl_load()
    if "enabled" in body:
        cfg["enabled"] = bool(body["enabled"])
    dl_save(cfg)
    return {"enabled": cfg["enabled"]}


@router.get("/api/mode")
async def dl_api_get_mode():
    return {"manual": _dl_manual_mode}


@router.post("/api/mode")
async def dl_api_set_mode(body: dict):
    global _dl_manual_mode
    manual = bool(body.get("manual", False))
    _dl_manual_mode = manual
    cfg = dl_load()
    cfg["manual_mode"] = manual
    dl_save(cfg)
    if not manual:
        await dl_ds_apply_current_layer()
    return {"manual": _dl_manual_mode}


@router.post("/api/dungeon-screen/manual-apply")
async def dl_api_manual_apply(body: dict):
    ds = dl_get_ds()
    ip = ds.get("ip", "")
    if not ip:
        return {"status": "no device"}
    on = bool(body.get("on", True))
    if not on:
        await _dl_set(ip, {"on": False})
        return {"status": "ok"}
    color = body.get("color", [255, 255, 255])
    fx = int(body.get("fx", 0))
    bri = int(body.get("bri", ds.get("brightness", 180)))
    sx = int(body.get("sx", 128))
    state = {
        "on": True,
        "bri": bri,
        "seg": [
            {"id": 0, "col": [color, [0, 0, 0], [0, 0, 0]], "fx": fx, "sx": sx, "on": True},
            *[{"id": i, "on": False, "stop": 0} for i in range(1, 8)],
        ],
    }
    await _dl_set(ip, state)
    return {"status": "ok"}


@router.get("/api/events")
async def dl_api_get_events():
    return dl_load().get("events", {})


@router.post("/api/events")
async def dl_api_save_events(events: dict):
    cfg = dl_load()
    cfg["events"] = events
    dl_save(cfg)
    return {"status": "ok"}


@router.post("/api/events/{event_name}/trigger")
async def dl_api_trigger_event(event_name: str):
    cfg = dl_load()
    if event_name not in cfg.get("events", {}):
        raise HTTPException(404, f"Unknown event: {event_name}")
    asyncio.create_task(dl_trigger(event_name))
    return {"status": "ok"}


@router.put("/api/events/{name}")
async def dl_api_upsert_event(name: str, body: dict):
    cfg = dl_load()
    cfg.setdefault("events", {})[name] = body
    dl_save(cfg)
    return cfg["events"][name]


@router.delete("/api/events/{name}")
async def dl_api_delete_event(name: str):
    cfg = dl_load()
    if name not in cfg.get("events", {}):
        raise HTTPException(404, f"Event not found: {name}")
    del cfg["events"][name]
    dl_save(cfg)
    return {"status": "ok"}


@router.get("/api/dungeon-screen")
async def dl_api_get_ds():
    ds = dl_get_ds()
    ds["active_player"] = _dl_ds_player_active
    ds["current_ambient"] = _dl_ds_ambient_mode
    ds["roll_active"] = _dl_ds_roll_timer is not None
    return ds


@router.post("/api/dungeon-screen")
async def dl_api_save_ds(body: dict):
    body.pop("active_player", None)
    dl_save_ds(body)
    return {"status": "ok"}


@router.get("/api/dungeon-screen/ping")
async def dl_api_ds_ping():
    ip = dl_get_ds().get("ip", "")
    if not ip:
        return {"online": False, "error": "No IP configured"}
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"http://{ip}/json/info")
            info = r.json()
        return {"online": True, "name": info.get("name"), "version": info.get("ver"), "leds": info.get("leds", {}).get("count")}
    except Exception as e:
        return {"online": False, "error": str(e)}


@router.post("/api/dungeon-screen/players")
async def dl_api_ds_add_player(body: dict):
    ds = dl_get_ds()
    player = {
        "id": str(uuid.uuid4())[:8],
        "name": (body.get("name") or "Player").strip(),
        "character": (body.get("character") or "").strip(),
        "start": int(body.get("start", 0)),
        "end": int(body.get("end", 5)),
        "color": body.get("color", [255, 215, 0]),
        "auto_signal": bool(body.get("auto_signal", True)),
    }
    ds.setdefault("players", []).append(player)
    dl_save_ds(ds)
    return ds["players"]


@router.patch("/api/dungeon-screen/players/{player_id}")
async def dl_api_ds_update_player(player_id: str, body: dict):
    ds = dl_get_ds()
    player = next((p for p in ds.get("players", []) if p["id"] == player_id), None)
    if not player:
        raise HTTPException(404)
    for k in ("name", "character", "start", "end", "color", "auto_signal"):
        if k in body:
            player[k] = body[k]
    dl_save_ds(ds)
    return player


@router.delete("/api/dungeon-screen/players/{player_id}")
async def dl_api_ds_delete_player(player_id: str):
    ds = dl_get_ds()
    ds["players"] = [p for p in ds.get("players", []) if p["id"] != player_id]
    dl_save_ds(ds)
    return ds["players"]


@router.post("/api/dungeon-screen/signal/{player_id}")
async def dl_api_ds_signal(player_id: str):
    asyncio.create_task(dl_ds_signal(player_id))
    return {"status": "ok", "player_id": player_id}


@router.post("/api/dungeon-screen/clear")
async def dl_api_ds_clear():
    asyncio.create_task(dl_ds_clear())
    return {"status": "ok"}


@router.get("/api/dungeon-screen/ambient")
async def dl_api_get_ambient():
    cfg = dl_load()
    modes = cfg["dungeon_screen"].get("ambient_modes", DL_DS_AMBIENT_DEFAULTS)
    return {"current": _dl_ds_ambient_mode, "modes": modes}


@router.post("/api/dungeon-screen/ambient/{mode}")
async def dl_api_set_ambient(mode: str):
    cfg = dl_load()
    modes = cfg["dungeon_screen"].get("ambient_modes", DL_DS_AMBIENT_DEFAULTS)
    if mode not in modes:
        raise HTTPException(404, f"Unknown ambient mode: {mode}")
    asyncio.create_task(dl_ds_ambient_set(mode))
    return {"status": "ok", "mode": mode}


@router.patch("/api/dungeon-screen/ambient/{mode}")
async def dl_api_update_ambient(mode: str, body: dict):
    cfg = dl_load()
    modes = cfg["dungeon_screen"].get("ambient_modes", DL_DS_AMBIENT_DEFAULTS)
    if mode not in modes:
        raise HTTPException(404, f"Unknown ambient mode: {mode}")
    for k in ("color", "fx", "bri", "sx"):
        if k in body:
            modes[mode][k] = body[k]
    cfg["dungeon_screen"]["ambient_modes"] = modes
    dl_save(cfg)
    if _dl_ds_ambient_mode == mode:
        asyncio.create_task(dl_ds_apply_current_layer())
    return modes[mode]


@router.delete("/api/dungeon-screen/ambient")
async def dl_api_clear_ambient():
    asyncio.create_task(dl_ds_ambient_clear())
    return {"status": "ok"}


@router.put("/api/dungeon-screen/ambient/{mode}")
async def dl_api_upsert_ambient_mode(mode: str, body: dict):
    cfg = dl_load()
    cfg["dungeon_screen"].setdefault("ambient_modes", {})[mode] = {
        "color": body.get("color", [255, 255, 255]),
        "fx":    int(body.get("fx", 0)),
        "bri":   int(body.get("bri", 150)),
        "sx":    int(body.get("sx", 100)),
    }
    dl_save(cfg)
    return cfg["dungeon_screen"]["ambient_modes"][mode]


@router.delete("/api/dungeon-screen/ambient/{mode}")
async def dl_api_delete_ambient_mode(mode: str):
    global _dl_ds_ambient_mode
    cfg = dl_load()
    modes = cfg["dungeon_screen"].get("ambient_modes", {})
    if mode not in modes:
        raise HTTPException(404, f"Ambient mode not found: {mode}")
    del modes[mode]
    if cfg["dungeon_screen"].get("current_ambient") == mode or _dl_ds_ambient_mode == mode:
        cfg["dungeon_screen"]["current_ambient"] = None
        _dl_ds_ambient_mode = None
    dl_save(cfg)
    return {"status": "ok"}


@router.post("/api/dungeon-screen/restore")
async def dl_api_ds_restore():
    """Re-apply current layer state. Called by dashboard after preview drag ends."""
    asyncio.create_task(dl_ds_apply_current_layer())
    return {"status": "ok"}


@router.post("/api/dungeon-screen/preview")
async def dl_api_ds_preview(body: dict):
    ds = dl_get_ds()
    ip = ds.get("ip", "")
    if not ip:
        return {"status": "no device"}
    total = ds.get("total_leds", 60)
    bri = ds.get("brightness", 180)
    state = {
        "on": True, "bri": bri, "transition": 0,
        "seg": [
            {"id": 0, "start": 0, "stop": total, "col": [[5, 5, 20]], "fx": 0, "on": True},
            {"id": 1, "start": int(body.get("start", 0)), "stop": int(body.get("end", 5)),
             "col": [body.get("color", [255, 215, 0]), [0,0,0], [0,0,0]], "fx": 0, "on": True},
            *[{"id": i, "on": False, "stop": 0} for i in range(2, 8)],
        ],
    }
    asyncio.create_task(_dl_set(ip, state))
    return {"status": "ok"}


@router.post("/api/dungeon-screen/corners-preview")
async def dl_api_ds_corners_preview(body: dict):
    ds = dl_get_ds()
    ip = ds.get("ip", "")
    if not ip:
        return {"status": "no device"}
    total = ds.get("total_leds", 60)
    corners = body.get("corners", [])
    if len(corners) < 3:
        return {"status": "need 3 corners"}
    c1, c2, c3 = int(corners[0]), int(corners[1]), int(corners[2])
    edge_colors = [[10, 10, 120], [10, 120, 10], [120, 10, 10], [100, 80, 0]]
    state = {
        "on": True, "bri": ds.get("brightness", 180), "transition": 0,
        "seg": [
            {"id": 0, "start": 0,  "stop": c1,    "col": [edge_colors[0]], "fx": 0, "on": True},
            {"id": 1, "start": c1, "stop": c2,    "col": [edge_colors[1]], "fx": 0, "on": True},
            {"id": 2, "start": c2, "stop": c3,    "col": [edge_colors[2]], "fx": 0, "on": True},
            {"id": 3, "start": c3, "stop": total, "col": [edge_colors[3]], "fx": 0, "on": True},
        ],
    }
    asyncio.create_task(_dl_set(ip, state))
    return {"status": "ok"}
