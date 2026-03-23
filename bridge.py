import asyncio
import json
import os
import sys
import threading
import types
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import requests
import uvicorn
import websocket
from dotenv import load_dotenv, set_key
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

import logger
from logger import DATA_DIR, log, log_buffer, log_subscribers
from dancing_lights import (
    router as dl_router,
    dl_detect_event,
    dl_trigger,
    dl_auto_signal,
)

ENV_PATH = Path(os.environ.get("ENV_PATH", str((Path(__file__).parent / "../.env").resolve())))
load_dotenv(dotenv_path=ENV_PATH)

ROLLS_FILE    = DATA_DIR / "rolls.json"
WEBHOOKS_FILE = DATA_DIR / "webhooks.json"


# ---------- Webhooks ----------

def _load_webhooks() -> list[str]:
    if not WEBHOOKS_FILE.exists():
        return []
    try:
        return json.loads(WEBHOOKS_FILE.read_text())
    except Exception:
        return []


def _save_webhooks(urls: list[str]):
    WEBHOOKS_FILE.write_text(json.dumps(urls, indent=2))


def dispatch_webhooks(payload: dict):
    urls = _load_webhooks()
    if not urls:
        return
    def _send():
        for url in urls:
            try:
                requests.post(url, json=payload, timeout=5)
            except Exception as e:
                log("warn", f"Webhook to {url} failed: {e}")
    threading.Thread(target=_send, daemon=True).start()


# ---------- Persistence: Rolls ----------

def _load_persisted_rolls(history: deque, index: dict):
    if not ROLLS_FILE.exists():
        return
    try:
        data = json.loads(ROLLS_FILE.read_text(encoding="utf-8"))
        for entry in reversed(data.get("history", [])):
            history.appendleft(entry)
        index.update(data.get("index", {}))
    except Exception:
        pass


def _save_rolls(history: deque, index: dict):
    try:
        payload = {"history": list(history), "index": index}
        ROLLS_FILE.write_text(json.dumps(payload), encoding="utf-8")
    except Exception as e:
        print(f"[persist] Failed to save rolls: {e}", flush=True)


# ---------- State ----------

foundry_clients: set = set()
ddb_ws_instance = None
ddb_connected = False
_reconnect_enabled = True

roll_history: deque = deque(maxlen=100)
roll_index: dict = {}
_load_persisted_rolls(roll_history, roll_index)


# ---------- Foundry Broadcast ----------

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


# ---------- DDB Client ----------

def get_session_token(cobalt_token, game_id, user_id):
    headers = {"cookie": f"CobaltSession={cobalt_token}; User.ID={user_id};"}
    r = requests.post("https://auth-service.dndbeyond.com/v1/cobalt-token", headers=headers)
    r.raise_for_status()
    return json.loads(r.content)["token"]


def parse_roll(data):
    roll_data = data["data"]["rolls"][0]
    context = data["data"]["context"]
    notation = roll_data.get("diceNotation", {})

    result = types.SimpleNamespace()
    result.total = roll_data["result"]["total"]
    result.text = roll_data["result"]["text"]
    result.roll_type = roll_data["rollType"]
    result.action = data["data"]["action"]
    result.character = context.get("name", "Unknown")
    result.entity_id = context.get("entityId")
    result.constant = notation.get("constant", 0)

    result.dice = []
    for die_set in notation.get("set", []):
        for die in die_set.get("dice", []):
            die_type = die.get("dieType", "d20")
            faces = int(die_type.replace("d", "")) if isinstance(die_type, str) else die_type
            result.dice.append({"faces": faces, "result": die.get("dieValue", 0)})

    return result


def on_message(ws, message):
    data = json.loads(message)
    if data.get("eventType") == "dice/roll/fulfilled":
        try:
            roll = parse_roll(data)
            context = data["data"]["context"]

            roll_id = data.get("id", datetime.now().isoformat())

            summary = {
                "id":         roll_id,
                "ts":         datetime.now().strftime("%H:%M:%S"),
                "character":  roll.character,
                "entity_id":  roll.entity_id,
                "entity_type": context.get("entityType", ""),
                "game_id":    data.get("gameId", ""),
                "action":     roll.action,
                "rollType":   roll.roll_type,
                "total":      roll.total,
                "text":       roll.text,
                "dice":       roll.dice,
                "constant":   roll.constant,
            }

            roll_index[roll_id] = {**summary, "raw": data}
            roll_history.appendleft(summary)

            if len(roll_index) > 110:
                oldest = next(iter(roll_index))
                del roll_index[oldest]

            _save_rolls(roll_history, roll_index)
            log("ddb", f"{roll.character}: {roll.action} | {roll.roll_type} | Total: {roll.total}",
                extra={"roll_id": roll_id, "roll_summary": summary})

            msg = {
                "type":      "ddb-roll",
                "character": roll.character,
                "entity_id": roll.entity_id,
                "action":    roll.action,
                "rollType":  roll.roll_type,
                "total":     roll.total,
                "text":      roll.text,
                "constant":  roll.constant,
                "dice":      roll.dice,
            }
            dispatch_webhooks(msg)
            if logger.main_event_loop and logger.main_event_loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    broadcast_to_foundry(msg), logger.main_event_loop
                )
                future.add_done_callback(
                    lambda f: log("error", f"Broadcast error: {f.exception()}") if f.exception() else None
                )
                dl_ev = dl_detect_event(msg)
                if dl_ev:
                    asyncio.run_coroutine_threadsafe(dl_trigger(dl_ev), logger.main_event_loop)
                asyncio.run_coroutine_threadsafe(
                    dl_auto_signal(msg.get("character", "")), logger.main_event_loop
                )
        except Exception as e:
            log("error", f"Error parsing roll: {e}")


def on_error(ws, error):
    log("error", f"DDB WS error: {error}")


def on_close(ws, code, msg):
    global ddb_connected
    ddb_connected = False
    if _reconnect_enabled:
        log("warn", "DDB connection closed, reconnecting in 5s...")
        threading.Timer(5.0, start_ddb_client).start()
    else:
        log("info", "DDB connection closed (manual).")


def on_open(ws):
    global ddb_connected
    ddb_connected = True
    log("info", "Connected to D&D Beyond game log.")


def start_ddb_client():
    global ddb_ws_instance
    cobalt_token = os.getenv("DDB_COBALT_TOKEN")
    game_id = os.getenv("DDB_GAME_ID")
    user_id = os.getenv("DDB_USER_ID")

    if not all([cobalt_token, game_id, user_id]):
        log("error", "Missing env vars: DDB_COBALT_TOKEN, DDB_GAME_ID, DDB_USER_ID")
        return

    try:
        token = get_session_token(cobalt_token, game_id, user_id)
    except Exception as e:
        log("error", f"Failed to get session token: {e}")
        threading.Timer(10.0, start_ddb_client).start()
        return

    url = f"wss://game-log-api-live.dndbeyond.com/v1?gameId={game_id}&userId={user_id}&stt={token}"
    ws = websocket.WebSocketApp(
        url, on_open=on_open, on_message=on_message,
        on_error=on_error, on_close=on_close,
    )
    ddb_ws_instance = ws
    threading.Thread(target=ws.run_forever, daemon=True).start()
    log("info", "DDB client starting...")


# ---------- FastAPI ----------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.main_event_loop = asyncio.get_event_loop()
    log("info", "Bridge server started — Web UI at http://0.0.0.0:8765")
    start_ddb_client()
    # Restore ambient mode from last session
    from dancing_lights import dl_load, dl_ds_ambient_set
    cfg = dl_load()
    mode = cfg.get("dungeon_screen", {}).get("current_ambient")
    if mode:
        await dl_ds_ambient_set(mode)
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(dl_router)


@app.websocket("/ws")
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


@app.get("/", response_class=HTMLResponse)
async def ui():
    return (Path(__file__).parent / "templates/index.html").read_text()


@app.get("/api/status")
async def api_status():
    return {"ddb_connected": ddb_connected, "foundry_clients": len(foundry_clients)}


@app.get("/api/rolls")
async def api_rolls():
    return list(roll_history)


@app.get("/api/rolls/{roll_id}")
async def api_roll_detail(roll_id: str):
    entry = roll_index.get(roll_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Roll not found")
    return entry


@app.get("/api/logs/stream")
async def api_logs_stream():
    async def generate():
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        log_subscribers.append(queue)
        try:
            for entry in list(log_buffer):
                yield f"data: {json.dumps(entry)}\n\n"
            while True:
                entry = await queue.get()
                yield f"data: {json.dumps(entry)}\n\n"
        finally:
            if queue in log_subscribers:
                log_subscribers.remove(queue)

    return StreamingResponse(
        generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/config")
async def api_get_config():
    return {
        "DDB_COBALT_TOKEN": os.getenv("DDB_COBALT_TOKEN", ""),
        "DDB_GAME_ID": os.getenv("DDB_GAME_ID", ""),
        "DDB_USER_ID": os.getenv("DDB_USER_ID", ""),
    }


class ConfigUpdate(BaseModel):
    DDB_COBALT_TOKEN: str = ""
    DDB_GAME_ID: str = ""
    DDB_USER_ID: str = ""


@app.post("/api/config")
async def api_update_config(cfg: ConfigUpdate):
    for key, val in cfg.model_dump().items():
        if val:
            set_key(str(ENV_PATH), key, val)
            os.environ[key] = val
    load_dotenv(dotenv_path=ENV_PATH, override=True)
    log("info", "Configuration updated.")
    return {"status": "ok"}


@app.get("/api/character/{entity_id}")
async def api_character(entity_id: str):
    cobalt_token = os.environ.get("DDB_COBALT_TOKEN", "")
    headers = {"cookie": f"CobaltSession={cobalt_token};"} if cobalt_token else {}
    try:
        r = requests.get(
            f"https://character-service.dndbeyond.com/character/v5/character/{entity_id}",
            headers=headers, timeout=10
        )
        r.raise_for_status()
        data = r.json().get("data", {})
        stats         = {s["id"]: (s["value"] or 0) for s in data.get("stats", [])}
        bonus_stats   = {s["id"]: (s["value"] or 0) for s in data.get("bonusStats", [])}
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
            "name":      data.get("name"),
            "level":     level,
            "max_hp":    max_hp,
            "ac":        data.get("overrideArmorClass") or None,
        }
    except Exception as e:
        log("warn", f"Failed to fetch character {entity_id}: {e}")
        raise HTTPException(status_code=502, detail=str(e))


@app.delete("/api/logs")
async def api_clear_logs():
    log_buffer.clear()
    with logger._log_file_lock:
        logger.LOG_FILE.write_text("", encoding="utf-8")
    log("info", "Logs cleared.")
    return {"status": "ok"}


@app.delete("/api/rolls")
async def api_clear_rolls():
    roll_history.clear()
    roll_index.clear()
    _save_rolls(roll_history, roll_index)
    log("info", "Roll history cleared.")
    return {"status": "ok"}


@app.post("/api/rolls/{roll_id}/resend")
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


@app.get("/api/webhooks")
async def api_get_webhooks():
    return _load_webhooks()


@app.post("/api/webhooks")
async def api_add_webhook(body: dict):
    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url required")
    urls = _load_webhooks()
    if url not in urls:
        urls.append(url)
        _save_webhooks(urls)
    return urls


@app.delete("/api/webhooks/{index}")
async def api_delete_webhook(index: int):
    urls = _load_webhooks()
    if index < 0 or index >= len(urls):
        raise HTTPException(status_code=404, detail="Index out of range")
    urls.pop(index)
    _save_webhooks(urls)
    return urls


@app.post("/api/restart")
async def api_restart():
    global ddb_ws_instance, ddb_connected, _reconnect_enabled
    log("info", "Manual restart triggered.")
    _reconnect_enabled = False
    if ddb_ws_instance:
        try:
            ddb_ws_instance.close()
        except Exception:
            pass
    await asyncio.sleep(1.0)
    _reconnect_enabled = True
    ddb_connected = False
    threading.Thread(target=start_ddb_client, daemon=True).start()
    return {"status": "restarting"}


# ---------- Main ----------

def _watch_quit():
    print("Press Q + Enter to stop.", flush=True)
    for line in sys.stdin:
        if line.strip().lower() == "q":
            print("Stopping...", flush=True)
            os._exit(0)


if __name__ == "__main__":
    threading.Thread(target=_watch_quit, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="warning")
