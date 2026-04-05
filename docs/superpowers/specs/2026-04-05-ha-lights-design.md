# Home Assistant Lights — Design Spec

**Date:** 2026-04-05
**Feature:** Add Home Assistant light entities as an alternative device type alongside WLED for simple devices.

---

## Overview

Simple devices (non-dungeon-screen) currently only support WLED via HTTP JSON API. This feature adds Home Assistant (HA) as a second device type. A single global HA connection (URL + Long-Lived Access Token) is configured once; individual devices then select their type (WLED or HA) and provide either an IP address or an `entity_id`.

---

## Data Model

### Global HA connection — new top-level key in `dancing_lights.json`

```json
"home_assistant": {
  "url": "http://homeassistant.local:8123",
  "token": "ey..."
}
```

- Absent if never configured — treated as no connection.
- Token stored as-is in the JSON file (same security boundary as the rest of the config).

### Per-device additions

Two new fields on every simple device, plus `ha_effect` on events and ambient modes:

```json
{
  "id": "dev001",
  "name": "Tischlampe",
  "type": "ha",
  "ip": "",
  "entity_id": "light.tischlampe",
  "enabled": true,
  "brightness": 180,
  "manual_mode": false,
  "current_ambient": null,
  "events": {
    "nat20": {
      "label": "NAT 20", "enabled": true,
      "color": [255, 215, 0], "effect": 9, "ha_effect": "colorloop",
      "brightness": 200, "speed": 128, "duration": 2000
    }
  },
  "ambient_modes": {
    "tavern": { "color": [255, 140, 0], "fx": 0, "bri": 150, "sx": 100, "ha_effect": "" }
  }
}
```

**Backward compatibility:**
- `type` absent → implicitly `"wled"` — all existing devices continue to work unchanged.
- `ha_effect` absent → empty string → no effect sent to HA.
- `ip` stays in schema for HA devices (unused).
- WLED `effect` (int) and `ha_effect` (string) coexist; only the one matching the device type is used.

---

## Backend

### New helpers

**`_ha_set(entity_id: str, state: dict, ha_effect: str = "") -> bool`**

Translates the WLED-style state dict to a HA REST API call:

| Condition | HA call |
|-----------|---------|
| `state["on"] is False` | `POST /api/services/light/turn_off` `{entity_id}` |
| `state["on"] is True` | `POST /api/services/light/turn_on` `{entity_id, rgb_color, brightness, [effect]}` |

- `rgb_color` from `state["seg"][0]["col"][0]` — `[r, g, b]`
- `brightness` from `state["bri"]` — 0–255 (same scale as WLED, no conversion)
- `effect` only included when `ha_effect` is a non-empty string
- `speed` (`sx`) has no HA equivalent — silently ignored
- HA URL + Token read from `dl_load()` on every call (no caching)
- Auth header: `Authorization: Bearer <token>`
- Returns `True` on 2xx, `False` otherwise

**`_dev_set(dev: dict, state: dict, ha_effect: str = "") -> bool`**

Single dispatcher replacing direct `_dl_set` calls for simple devices:

```python
async def _dev_set(dev, state, ha_effect=""):
    if dev.get("type") == "ha":
        return await _ha_set(dev.get("entity_id", ""), state, ha_effect)
    return await _dl_set(dev.get("ip", ""), state)
```

### Modified functions (minimal changes)

| Function | Change |
|----------|--------|
| `_dev_apply_ambient` | `await _dl_set(ip, state)` → `await _dev_set(dev, state, mode.get("ha_effect", ""))` |
| `_dev_trigger` | `await _dl_set(ip, anim)` → `await _dev_set(dev, anim, ev.get("ha_effect", ""))` |
| `dl_api_device_manual_apply` | Accept optional `ha_effect: str` from request body; pass to `_dev_set` |

The `_restore()` closure inside `_dev_trigger` calls `_dev_apply_ambient` — no change needed there.

### New endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/dl/api/ha-config` | Returns `{url, token_set: bool}` — token never returned in plaintext |
| `POST` | `/dl/api/ha-config` | Saves `{url, token}` to config |

### Updated endpoints

- `PUT /dl/api/devices/{id}` — must accept `type` and `entity_id` fields in addition to existing fields
- `POST /dl/api/devices` (create) — scaffolds device with `type: "wled"`, `entity_id: ""`
- `PUT /dl/api/devices/{id}/events/{key}` — must accept `ha_effect` field
- `PUT /dl/api/devices/{id}/ambient/{key}` — must accept `ha_effect` field

---

## Frontend

### Config tab — new "Home Assistant" section

- URL input + Token input (`type="password"`) + Save button
- On load: URL pre-filled, Token field shows placeholder `••••••••` if token is set
- Calls `GET /dl/api/ha-config` on load, `POST /dl/api/ha-config` on save

### Device settings card — type dropdown

- New `<select id="dev-type">` with options `WLED` / `Home Assistant` above the connection fields
- `WLED` selected: IP input visible, entity_id input hidden
- `HA` selected: entity_id input visible (`light.tischlampe`), IP input hidden
- `devSaveHeader()` extended to send `type` + `entity_id`
- `devSelectDevice()` extended to populate type dropdown and toggle field visibility

### Events sub-tab — conditional effect field

- `devRenderEvents()` checks `_devType` (new state variable, set on device select)
- `WLED`: existing Effect dropdown with WLED effect IDs
- `HA`: Effect dropdown replaced with `<input type="text" placeholder="colorloop">` for `ha_effect`
- `devCollectEvents()` reads the correct field per type

### Ambient sub-tab — conditional effect field

- Same conditional logic in inline editor and add-mode form
- `WLED`: `fx` dropdown
- `HA`: `ha_effect` text input
- `devAmbientPatch()` and `devAddAmbientMode()` include `ha_effect` in payload

### Dashboard custom section

- `WLED`: existing Effect select
- `HA`: text input for `ha_effect`
- `devManualApply()` includes `ha_effect` in body when type is HA

---

## HA API Translation Reference

```
HA endpoint:  POST {url}/api/services/light/turn_on
Headers:      Authorization: Bearer {token}
              Content-Type: application/json
Body (on):    { "entity_id": "light.x", "rgb_color": [r,g,b], "brightness": 0-255, "effect": "..." }
Body (off):   endpoint = turn_off, body = { "entity_id": "light.x" }
```

---

## Out of Scope

- Multiple HA instances per installation
- HA light state readback / status polling
- HA scene support
- Dungeon Screen via HA (Dungeon Screen stays WLED-only)
