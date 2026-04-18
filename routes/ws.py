import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from logger import log
from services.foundry import foundry_clients
from dancing_lights import dl_auto_signal

router = APIRouter()


@router.websocket("/ws")
async def foundry_ws(ws: WebSocket):
    await ws.accept()
    foundry_clients.add(ws)
    log("info", f"Foundry client connected: {ws.client}")
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if msg.get("type") == "combat-turn":
                asyncio.create_task(dl_auto_signal(msg.get("character", "")))
    except WebSocketDisconnect:
        pass
    finally:
        foundry_clients.discard(ws)
        log("info", "Foundry client disconnected.")
