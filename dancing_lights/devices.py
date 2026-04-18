from typing import Optional

import httpx

from dancing_lights.config import dl_load
from logger import log

_DL_DS_EXTRA_SEGS_OFF = [{"id": i, "on": False, "stop": 0} for i in range(2, 8)]
_DL_DS_NEUTRAL = {
    "on": True, "bri": 10,
    "seg": [
        {"id": 0, "col": [[5, 5, 10]], "fx": 0, "on": True},
        *[{"id": i, "on": False, "stop": 0} for i in range(1, 8)],
    ],
}


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


async def _ha_set(entity_id: str, state: dict, ha_effect: str = "") -> bool:
    if not entity_id:
        return False
    cfg = dl_load()
    ha = cfg.get("home_assistant", {})
    url_base = (ha.get("url") or "").rstrip("/")
    token = ha.get("token", "")
    if not url_base or not token:
        return False
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            if not state.get("on", True):
                r = await c.post(
                    f"{url_base}/api/services/light/turn_off",
                    json={"entity_id": entity_id},
                    headers=headers,
                )
            else:
                seg0 = state.get("seg", [{}])[0]
                col = seg0.get("col", [[255, 255, 255]])[0]
                body: dict = {
                    "entity_id": entity_id,
                    "rgb_color": col,
                    "brightness": state.get("bri", 180),
                }
                if ha_effect:
                    body["effect"] = ha_effect
                r = await c.post(
                    f"{url_base}/api/services/light/turn_on",
                    json=body,
                    headers=headers,
                )
            return r.status_code < 300
    except Exception:
        return False


def _dev_has_target(dev: dict) -> bool:
    if dev.get("type") == "ha":
        return bool(dev.get("entity_id", ""))
    return bool(dev.get("ip", ""))


async def _dev_set(dev: dict, state: dict, ha_effect: str = "") -> bool:
    if dev.get("type") == "ha":
        return await _ha_set(dev.get("entity_id", ""), state, ha_effect)
    return await _dl_set(dev.get("ip", ""), state)
