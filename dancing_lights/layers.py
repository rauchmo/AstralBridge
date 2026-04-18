import asyncio
from typing import Optional

from dancing_lights.config import (
    DL_DS_AMBIENT_DEFAULTS,
    dl_get_ds,
    dl_load,
    dl_save,
)
from dancing_lights.devices import (
    _DL_DS_NEUTRAL,
    _dev_has_target,
    _dev_set,
    _dl_set,
)
from logger import log

# Layer state — simple reassignable variables (do NOT import these from outside; use module ref)
_dl_ds_ambient_mode: Optional[str] = None
_dl_ds_player_active: Optional[str] = None
_dl_ds_roll_timer: Optional[asyncio.Task] = None
_dl_ds_roll_event: Optional[str] = None
_dl_manual_mode: bool = False

# Per-device state (keyed by device id) — dicts, safe to import directly
_dev_roll_timers: dict = {}
_dev_ambient: dict = {}
_dev_manual: dict = {}


async def dl_ds_apply_current_layer():
    global _dl_ds_roll_timer
    if _dl_ds_roll_timer is not None:
        return
    ds = dl_get_ds()
    ip = ds.get("ip", "")
    if not ip:
        return

    if _dl_ds_player_active:
        player = next((p for p in ds.get("players", []) if p["id"] == _dl_ds_player_active), None)
        if player:
            total      = ds.get("total_leds", 60)
            ambient_on = ds.get("ambient_during_turn", True)
            buffer     = int(ds.get("turn_buffer_leds", 2))
            buf_start  = max(0, player["start"] - buffer)
            buf_end    = min(total, player["end"] + buffer)

            m = None
            if ambient_on and _dl_ds_ambient_mode:
                cfg2 = dl_load()
                m = cfg2["dungeon_screen"].get("ambient_modes", DL_DS_AMBIENT_DEFAULTS).get(_dl_ds_ambient_mode)
            if m:
                bg  = {"id": 0, "start": 0, "stop": total, "col": [m["color"], [0, 0, 0], [0, 0, 0]], "fx": m["fx"], "sx": m["sx"], "on": True}
                bri = m["bri"]
            else:
                bg  = {"id": 0, "start": 0, "stop": total, "col": [[5, 5, 20]], "fx": 0, "on": True}
                bri = ds.get("brightness", 180)

            segs = [
                bg,
                {"id": 1, "start": player["start"], "stop": player["end"],
                 "col": [player["color"], [0, 0, 0], [0, 0, 0]], "fx": 9, "sx": 180, "on": True},
            ]
            seg_id = 2
            if buf_start < player["start"]:
                segs.append({"id": seg_id, "start": buf_start, "stop": player["start"], "col": [[0, 0, 0]], "fx": 0, "on": True})
                seg_id += 1
            if player["end"] < buf_end:
                segs.append({"id": seg_id, "start": player["end"], "stop": buf_end, "col": [[0, 0, 0]], "fx": 0, "on": True})
                seg_id += 1
            for i in range(seg_id, 8):
                segs.append({"id": i, "on": False, "stop": 0})

            await _dl_set(ip, {"on": True, "bri": bri, "transition": 2, "seg": segs})
            return

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

    await _dl_set(ip, _DL_DS_NEUTRAL)


async def _dev_apply_ambient(dev_id: str):
    if dev_id in _dev_roll_timers:
        return
    cfg = dl_load()
    dev = next((d for d in cfg.get("devices", []) if d["id"] == dev_id), None)
    if not dev or not _dev_has_target(dev):
        return
    mode_key = _dev_ambient.get(dev_id)
    if mode_key:
        m = dev.get("ambient_modes", {}).get(mode_key)
        if m:
            state = {
                "on": True, "bri": m["bri"],
                "seg": [{"id": 0, "col": [m["color"], [0, 0, 0], [0, 0, 0]], "fx": m["fx"], "sx": m["sx"], "on": True}],
            }
            await _dev_set(dev, state, m.get("ha_effect", ""))
            return
    await _dev_set(dev, {"on": True, "bri": 10, "seg": [{"id": 0, "col": [[5, 5, 10]], "fx": 0, "on": True}]})


async def _dev_trigger(dev_id: str, dev: dict, ev: dict):
    existing = _dev_roll_timers.pop(dev_id, None)
    if existing:
        existing.cancel()
    if not _dev_has_target(dev):
        return
    color       = ev.get("color", [255, 255, 255])
    effect      = ev.get("effect", 0)
    bri         = ev.get("brightness", 200)
    speed       = ev.get("speed", 128)
    duration_ms = ev.get("duration", 2000)
    anim = {
        "on": True, "bri": bri,
        "seg": [{"id": 0, "col": [color, [0, 0, 0], [0, 0, 0]], "fx": effect, "sx": speed, "on": True}],
    }

    async def _restore():
        await asyncio.sleep(duration_ms / 1000)
        _dev_roll_timers.pop(dev_id, None)
        await _dev_apply_ambient(dev_id)

    _dev_roll_timers[dev_id] = asyncio.create_task(_restore())
    await _dev_set(dev, anim, ev.get("ha_effect", ""))


def dl_detect_event(msg: dict) -> Optional[str]:
    roll_type = (msg.get("rollType") or "").lower()
    action    = (msg.get("action") or "").lower()
    dice      = msg.get("dice", [])

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
    global _dl_ds_roll_timer, _dl_ds_roll_event
    if _dl_manual_mode:
        return
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

    color       = ev.get("color", [255, 255, 255])
    effect      = ev.get("effect", 0)
    bri         = ev.get("brightness", 200)
    speed       = ev.get("speed", 128)
    duration_ms = ev.get("duration", 2000)

    anim = {
        "on": True, "bri": bri, "transition": 2,
        "seg": [
            {"id": 0, "col": [color, [0, 0, 0], [0, 0, 0]], "fx": effect, "sx": speed, "on": True},
            *[{"id": i, "on": False, "stop": 0} for i in range(1, 8)],
        ],
    }

    if _dl_ds_roll_timer is not None:
        _dl_ds_roll_timer.cancel()
        _dl_ds_roll_timer = None

    async def _restore():
        global _dl_ds_roll_timer, _dl_ds_roll_event
        await asyncio.sleep(duration_ms / 1000)
        _dl_ds_roll_timer = None
        _dl_ds_roll_event = None
        await dl_ds_apply_current_layer()

    _dl_ds_roll_event = ev.get("label", event_name)
    _dl_ds_roll_timer = asyncio.create_task(_restore())
    await _dl_set(ip, anim)

    for dev in cfg.get("devices", []):
        if not dev.get("enabled"):
            continue
        if _dev_manual.get(dev["id"]):
            continue
        dev_ev = dev.get("events", {}).get(event_name, {})
        if dev_ev.get("enabled"):
            asyncio.create_task(_dev_trigger(dev["id"], dev, dev_ev))


async def dl_ds_signal(player_id: str):
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
    global _dl_ds_player_active
    _dl_ds_player_active = None
    await dl_ds_apply_current_layer()


async def dl_auto_signal(character: str):
    global _dl_ds_player_active
    if _dl_manual_mode:
        return
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
    global _dl_ds_ambient_mode
    cfg = dl_load()
    modes = cfg["dungeon_screen"].get("ambient_modes", DL_DS_AMBIENT_DEFAULTS)
    if mode not in modes:
        return
    _dl_ds_ambient_mode = mode
    cfg["dungeon_screen"]["current_ambient"] = mode
    dl_save(cfg)
    await dl_ds_apply_current_layer()


async def dl_ds_ambient_clear():
    global _dl_ds_ambient_mode
    _dl_ds_ambient_mode = None
    cfg = dl_load()
    cfg["dungeon_screen"]["current_ambient"] = None
    dl_save(cfg)
    await dl_ds_apply_current_layer()


def _dl_load_manual_mode():
    global _dl_manual_mode
    _dl_manual_mode = dl_load().get("manual_mode", False)


def _dl_init_devices():
    cfg = dl_load()
    for dev in cfg.get("devices", []):
        dev_id = dev.get("id")
        if not dev_id:
            continue
        _dev_ambient[dev_id] = dev.get("current_ambient")
        _dev_manual[dev_id] = dev.get("manual_mode", False)


_dl_load_manual_mode()
_dl_init_devices()
