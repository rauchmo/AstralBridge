import asyncio
import uuid

import httpx
from fastapi import APIRouter, HTTPException

from dancing_lights.config import (
    DL_DEFAULT_EVENTS,
    DL_DS_AMBIENT_DEFAULTS,
    dl_get_ds,
    dl_load,
    dl_save,
    dl_save_ds,
)
from dancing_lights.devices import _dev_has_target, _dev_set, _dl_set
from dancing_lights.layers import (
    _dev_ambient,
    _dev_manual,
    _dev_roll_timers,
    _dev_apply_ambient,
    dl_ds_ambient_clear,
    dl_ds_ambient_set,
    dl_ds_apply_current_layer,
    dl_ds_clear,
    dl_ds_signal,
    dl_trigger,
)
import dancing_lights.layers as _layers

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
    return {"manual": _layers._dl_manual_mode}


@router.post("/api/mode")
async def dl_api_set_mode(body: dict):
    pass  # state in layers module
    manual = bool(body.get("manual", False))
    _layers._dl_manual_mode = manual
    cfg = dl_load()
    cfg["manual_mode"] = manual
    dl_save(cfg)
    if not manual:
        await dl_ds_apply_current_layer()
    return {"manual": _layers._dl_manual_mode}


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
    ds["active_player"] = _layers._dl_ds_player_active
    ds["current_ambient"] = _layers._dl_ds_ambient_mode
    ds["roll_active"] = _layers._dl_ds_roll_timer is not None
    ds["roll_event"] = _layers._dl_ds_roll_event
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
    return {"current": _layers._dl_ds_ambient_mode, "modes": modes}


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
    if _layers._dl_ds_ambient_mode == mode:
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
    pass  # state in layers module
    cfg = dl_load()
    modes = cfg["dungeon_screen"].get("ambient_modes", {})
    if mode not in modes:
        raise HTTPException(404, f"Ambient mode not found: {mode}")
    del modes[mode]
    if cfg["dungeon_screen"].get("current_ambient") == mode or _layers._dl_ds_ambient_mode == mode:
        cfg["dungeon_screen"]["current_ambient"] = None
        _layers._dl_ds_ambient_mode = None
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


# ── Simple Device endpoints ────────────────────────────────────────────────

def _dev_find(cfg: dict, dev_id: str) -> dict:
    dev = next((d for d in cfg.get("devices", []) if d["id"] == dev_id), None)
    if not dev:
        raise HTTPException(404, f"Device not found: {dev_id}")
    return dev


@router.get("/api/devices")
async def dl_api_list_devices():
    return dl_load().get("devices", [])


@router.post("/api/devices")
async def dl_api_create_device(body: dict):
    name = (body.get("name") or "Device").strip()
    ip   = (body.get("ip") or "").strip()
    dev = {
        "id":             str(uuid.uuid4())[:8],
        "name":           name,
        "ip":             ip,
        "type":           "wled",
        "entity_id":      "",
        "enabled":        True,
        "brightness":     180,
        "manual_mode":    False,
        "current_ambient": None,
        "ambient_modes":  {k: dict(v) for k, v in DL_DS_AMBIENT_DEFAULTS.items()},
        "events":         {k: dict(v) for k, v in DL_DEFAULT_EVENTS.items()},
    }
    cfg = dl_load()
    cfg.setdefault("devices", []).append(dev)
    dl_save(cfg)
    _dev_ambient[dev["id"]] = None
    _dev_manual[dev["id"]]  = False
    return dev


@router.put("/api/devices/{dev_id}")
async def dl_api_update_device(dev_id: str, body: dict):
    cfg = dl_load()
    dev = _dev_find(cfg, dev_id)
    for k in ("name", "ip", "type", "entity_id", "enabled", "brightness"):
        if k in body:
            dev[k] = body[k]
    dl_save(cfg)
    return dev


@router.delete("/api/devices/{dev_id}")
async def dl_api_delete_device(dev_id: str):
    cfg = dl_load()
    _dev_find(cfg, dev_id)  # raises 404 if missing
    t = _dev_roll_timers.pop(dev_id, None)
    if t:
        t.cancel()
    _dev_ambient.pop(dev_id, None)
    _dev_manual.pop(dev_id, None)
    cfg["devices"] = [d for d in cfg["devices"] if d["id"] != dev_id]
    dl_save(cfg)
    return {"status": "ok"}


@router.get("/api/devices/{dev_id}/events")
async def dl_api_get_device_events(dev_id: str):
    cfg = dl_load()
    dev = _dev_find(cfg, dev_id)
    return dev.get("events", {})


@router.put("/api/devices/{dev_id}/events/{event_key}")
async def dl_api_put_device_event(dev_id: str, event_key: str, body: dict):
    cfg = dl_load()
    dev = _dev_find(cfg, dev_id)
    dev.setdefault("events", {})[event_key] = body
    dl_save(cfg)
    return dev["events"][event_key]


@router.get("/api/devices/{dev_id}/ambient")
async def dl_api_get_device_ambient(dev_id: str):
    cfg = dl_load()
    dev = _dev_find(cfg, dev_id)
    return {"current": _dev_ambient.get(dev_id), "modes": dev.get("ambient_modes", {})}


@router.post("/api/devices/{dev_id}/ambient/{mode_key}")
async def dl_api_activate_device_ambient(dev_id: str, mode_key: str):
    cfg = dl_load()
    dev = _dev_find(cfg, dev_id)
    if mode_key not in dev.get("ambient_modes", {}):
        raise HTTPException(404, f"Unknown ambient mode: {mode_key}")
    _dev_ambient[dev_id] = mode_key
    dev["current_ambient"] = mode_key
    dl_save(cfg)
    asyncio.create_task(_dev_apply_ambient(dev_id))
    return {"status": "ok", "mode": mode_key}


@router.put("/api/devices/{dev_id}/ambient/{mode_key}")
async def dl_api_upsert_device_ambient(dev_id: str, mode_key: str, body: dict):
    cfg = dl_load()
    dev = _dev_find(cfg, dev_id)
    dev.setdefault("ambient_modes", {})[mode_key] = {
        "color":     body.get("color", [255, 255, 255]),
        "fx":        int(body.get("fx", 0)),
        "bri":       int(body.get("bri", 150)),
        "sx":        int(body.get("sx", 100)),
        "ha_effect": body.get("ha_effect", ""),
    }
    dl_save(cfg)
    return dev["ambient_modes"][mode_key]


@router.delete("/api/devices/{dev_id}/ambient/{mode_key}")
async def dl_api_delete_device_ambient(dev_id: str, mode_key: str):
    cfg = dl_load()
    dev = _dev_find(cfg, dev_id)
    modes = dev.get("ambient_modes", {})
    if mode_key not in modes:
        raise HTTPException(404, f"Ambient mode not found: {mode_key}")
    del modes[mode_key]
    if dev.get("current_ambient") == mode_key or _dev_ambient.get(dev_id) == mode_key:
        dev["current_ambient"] = None
        _dev_ambient[dev_id] = None
    dl_save(cfg)
    return {"status": "ok"}


@router.get("/api/devices/{dev_id}/mode")
async def dl_api_get_device_mode(dev_id: str):
    cfg = dl_load()
    _dev_find(cfg, dev_id)
    return {"manual": _dev_manual.get(dev_id, False)}


@router.post("/api/devices/{dev_id}/mode")
async def dl_api_set_device_mode(dev_id: str, body: dict):
    cfg = dl_load()
    dev = _dev_find(cfg, dev_id)
    manual = bool(body.get("manual", False))
    _dev_manual[dev_id] = manual
    dev["manual_mode"] = manual
    dl_save(cfg)
    if not manual:
        asyncio.create_task(_dev_apply_ambient(dev_id))
    return {"manual": manual}


@router.post("/api/devices/{dev_id}/manual-apply")
async def dl_api_device_manual_apply(dev_id: str, body: dict):
    cfg = dl_load()
    dev = _dev_find(cfg, dev_id)
    if not _dev_has_target(dev):
        return {"status": "no device"}
    ha_effect = body.get("ha_effect", "")
    on = bool(body.get("on", True))
    if not on:
        await _dev_set(dev, {"on": False}, ha_effect)
        return {"status": "ok"}
    color = body.get("color", [255, 255, 255])
    fx  = int(body.get("fx", 0))
    bri = int(body.get("bri", dev.get("brightness", 180)))
    sx  = int(body.get("sx", 128))
    state = {
        "on": True, "bri": bri,
        "seg": [{"id": 0, "col": [color, [0, 0, 0], [0, 0, 0]], "fx": fx, "sx": sx, "on": True}],
    }
    await _dev_set(dev, state, ha_effect)
    return {"status": "ok"}


@router.post("/api/devices/{dev_id}/sync-ambient")
async def dl_api_device_sync_ambient(dev_id: str):
    cfg = dl_load()
    dev = _dev_find(cfg, dev_id)
    ds_key = cfg.get("dungeon_screen", {}).get("current_ambient")
    if not ds_key:
        return {"synced_mode": None}
    if ds_key in dev.get("ambient_modes", {}):
        _dev_ambient[dev_id] = ds_key
        dev["current_ambient"] = ds_key
        dl_save(cfg)
        asyncio.create_task(_dev_apply_ambient(dev_id))
        return {"synced_mode": ds_key}
    else:
        m = cfg.get("dungeon_screen", {}).get("ambient_modes", {}).get(ds_key)
        if not m:
            return {"synced_mode": None}
        state = {
            "on": True, "bri": m["bri"],
            "seg": [{"id": 0, "col": [m["color"], [0, 0, 0], [0, 0, 0]], "fx": m["fx"], "sx": m["sx"], "on": True}],
        }
        await _dev_set(dev, state, m.get("ha_effect", ""))
        return {"synced_mode": None}


# ── HA config endpoints ────────────────────────────────────────────────────────

@router.get("/api/ha-config")
async def dl_api_get_ha_config():
    ha = dl_load().get("home_assistant", {})
    return {"url": ha.get("url", ""), "token_set": bool(ha.get("token", ""))}


@router.post("/api/ha-config")
async def dl_api_set_ha_config(body: dict):
    cfg = dl_load()
    ha = cfg.setdefault("home_assistant", {})
    ha["url"] = (body.get("url") or "").strip()
    new_token = (body.get("token") or "").strip()
    if new_token:
        ha["token"] = new_token
    dl_save(cfg)
    return {"url": ha["url"], "token_set": bool(ha.get("token", ""))}
