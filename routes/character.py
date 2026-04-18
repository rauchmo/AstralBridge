import os

import requests
from fastapi import APIRouter, HTTPException

from logger import log

router = APIRouter()


@router.get("/api/character/{entity_id}")
async def api_character(entity_id: str):
    cobalt_token = os.environ.get("DDB_COBALT_TOKEN", "")
    headers = {"cookie": f"CobaltSession={cobalt_token};"} if cobalt_token else {}
    try:
        r = requests.get(
            f"https://character-service.dndbeyond.com/character/v5/character/{entity_id}",
            headers=headers, timeout=10,
        )
        r.raise_for_status()
        data = r.json().get("data", {})
        stats          = {s["id"]: (s["value"] or 0) for s in data.get("stats", [])}
        bonus_stats    = {s["id"]: (s["value"] or 0) for s in data.get("bonusStats", [])}
        override_stats = {s["id"]: s["value"] for s in data.get("overrideStats", []) if s.get("value") is not None}

        con = override_stats.get(3, stats.get(3, 10) + bonus_stats.get(3, 0))
        con_mod = (con - 10) // 2

        hp_per_level = data.get("baseHitPoints") or 0
        bonus_hp     = data.get("bonusHitPoints") or 0
        override_hp  = data.get("overrideHitPoints")
        level        = sum((c.get("level") or 0) for c in data.get("classes", []))

        modifier_hp = 0
        for source_mods in data.get("modifiers", {}).values():
            for mod in source_mods:
                sub = mod.get("subType", "")
                val = (mod.get("dice") or {}).get("fixedValue") or mod.get("value") or 0
                if sub == "hit-points-per-level":
                    modifier_hp += val * level
                elif sub == "hit-points":
                    modifier_hp += val

        max_hp = override_hp if override_hp else hp_per_level + (con_mod * level) + bonus_hp + modifier_hp

        return {
            "name":   data.get("name"),
            "level":  level,
            "max_hp": max_hp,
            "ac":     data.get("overrideArmorClass") or None,
        }
    except Exception as e:
        log("warn", f"Failed to fetch character {entity_id}: {e}")
        raise HTTPException(status_code=502, detail=str(e))
