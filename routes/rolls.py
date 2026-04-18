from fastapi import APIRouter, HTTPException

from logger import log
from services.foundry import broadcast_to_foundry
from services.roll_store import roll_history, roll_index, save_rolls

router = APIRouter()


@router.get("/api/rolls")
async def api_rolls():
    return list(roll_history)


@router.get("/api/rolls/{roll_id}")
async def api_roll_detail(roll_id: str):
    entry = roll_index.get(roll_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Roll not found")
    return entry


@router.delete("/api/rolls")
async def api_clear_rolls():
    roll_history.clear()
    roll_index.clear()
    save_rolls()
    log("info", "Roll history cleared.")
    return {"status": "ok"}


@router.post("/api/rolls/{roll_id}/resend")
async def api_resend_roll(roll_id: str):
    entry = roll_index.get(roll_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Roll not found")
    msg = {
        "type":      "ddb-roll",
        "character": entry["character"],
        "action":    entry["action"],
        "rollType":  entry["rollType"],
        "total":     entry["total"],
        "text":      entry["text"],
        "constant":  entry["constant"],
        "dice":      entry["dice"],
    }
    await broadcast_to_foundry(msg)
    log("info", f"Resent roll {roll_id} ({entry['character']}: {entry['action']})")
    return {"status": "ok"}
