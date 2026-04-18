import json
from fastapi import WebSocket
from logger import log

foundry_clients: set = set()


async def broadcast_to_foundry(message: dict):
    if not foundry_clients:
        log("warn", "No Foundry clients connected, dropping roll.")
        return
    msg_json = json.dumps(message)
    disconnected = set()
    for ws in list(foundry_clients):
        try:
            await ws.send_text(msg_json)
        except Exception:
            disconnected.add(ws)
    foundry_clients.difference_update(disconnected)
    log("info", f"Sent to {len(foundry_clients)} Foundry client(s)")
