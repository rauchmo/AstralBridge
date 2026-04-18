import json
from typing import Optional

from logger import DATA_DIR, log

DL_CONFIG_FILE = DATA_DIR / "dancing_lights.json"

DL_DEFAULT_EVENTS = {
    "nat20":      {"label": "Nat 20",        "enabled": True,  "color": [255, 215, 0], "effect": 38, "brightness": 255, "speed": 220, "duration": 3500},
    "nat1":       {"label": "Nat 1",         "enabled": True,  "color": [140, 0, 0],   "effect": 11, "brightness": 180, "speed": 200, "duration": 2500},
    "damage":     {"label": "Damage",        "enabled": True,  "color": [255, 50, 0],  "effect": 25, "brightness": 230, "speed": 200, "duration": 2000},
    "heal":       {"label": "Heal",          "enabled": True,  "color": [0, 220, 90],  "effect": 2,  "brightness": 200, "speed": 150, "duration": 2500},
    "initiative": {"label": "Initiative",    "enabled": True,  "color": [80, 80, 255], "effect": 58, "brightness": 200, "speed": 180, "duration": 2000},
    "save":       {"label": "Saving Throw",  "enabled": False, "color": [160, 0, 255], "effect": 17, "brightness": 180, "speed": 150, "duration": 1500},
    "check":      {"label": "Ability Check", "enabled": False, "color": [0, 160, 200], "effect": 77, "brightness": 160, "speed": 150, "duration": 1500},
    "attack":     {"label": "Attack Roll",   "enabled": False, "color": [220, 100, 0], "effect": 9,  "brightness": 200, "speed": 200, "duration": 1500},
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

_DL_DS_DEFAULT = {
    "ip": "", "total_leds": 60, "brightness": 180, "players": [],
    "corners": [], "ambient_during_turn": True, "turn_buffer_leds": 2,
}


def dl_load() -> dict:
    if not DL_CONFIG_FILE.exists():
        return {
            "enabled": False,
            "events": {k: dict(v) for k, v in DL_DEFAULT_EVENTS.items()},
            "dungeon_screen": {**_DL_DS_DEFAULT, "current_ambient": None, "ambient_modes": dict(DL_DS_AMBIENT_DEFAULTS)},
            "devices": [],
        }
    try:
        cfg = json.loads(DL_CONFIG_FILE.read_text())
        cfg.setdefault("enabled", False)
        cfg.setdefault("devices", [])
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
            "devices": [],
        }


def dl_save(cfg: dict):
    DL_CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


def dl_get_ds() -> dict:
    return dl_load().get("dungeon_screen", dict(_DL_DS_DEFAULT))


def dl_save_ds(ds: dict):
    cfg = dl_load()
    cfg["dungeon_screen"] = ds
    dl_save(cfg)
