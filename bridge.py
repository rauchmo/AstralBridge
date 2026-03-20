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
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

ENV_PATH = Path(os.environ.get("ENV_PATH", str((Path(__file__).parent / "../.env").resolve())))
load_dotenv(dotenv_path=ENV_PATH)

# ---------- Persistence ----------

DATA_DIR  = (Path(__file__).parent / "data").resolve()
DATA_DIR.mkdir(exist_ok=True)
LOG_FILE   = DATA_DIR / "logs.jsonl"
ROLLS_FILE = DATA_DIR / "rolls.json"

_log_file_lock = threading.Lock()


def _load_persisted_logs(buf: deque):
    if not LOG_FILE.exists():
        return
    try:
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
        for line in lines[-buf.maxlen:]:
            try:
                buf.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    except Exception:
        pass


def _append_log_file(entry: dict):
    with _log_file_lock:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    # Rotate if file exceeds 5 MB
    try:
        if LOG_FILE.stat().st_size > 5 * 1024 * 1024:
            LOG_FILE.replace(LOG_FILE.with_suffix(".jsonl.bak"))
    except Exception:
        pass


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


# ---------- Logging ----------

log_buffer: deque = deque(maxlen=500)
log_subscribers: list = []
main_event_loop = None
_load_persisted_logs(log_buffer)


def log(level: str, msg: str, extra: dict = None):
    entry = {"ts": datetime.now().strftime("%H:%M:%S"), "level": level, "msg": msg}
    if extra:
        entry.update(extra)
    log_buffer.append(entry)
    _append_log_file(entry)
    print(f"[{entry['ts']}] [{level.upper()}] {msg}", flush=True)
    if main_event_loop and main_event_loop.is_running():
        for q in list(log_subscribers):
            main_event_loop.call_soon_threadsafe(q.put_nowait, entry)


# ---------- State ----------

foundry_clients: set = set()
ddb_ws_instance = None
ddb_connected = False
_reconnect_enabled = True

# Roll history: compact summary list + full data index keyed by roll ID
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

            # Compact summary stored in the history list
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

            # Full entry includes raw DDB payload
            roll_index[roll_id] = {**summary, "raw": data}
            roll_history.appendleft(summary)

            # Trim index to match history size
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
            if main_event_loop and main_event_loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    broadcast_to_foundry(msg), main_event_loop
                )
                future.add_done_callback(
                    lambda f: log("error", f"Broadcast error: {f.exception()}") if f.exception() else None
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
    global main_event_loop
    main_event_loop = asyncio.get_event_loop()
    log("info", "Bridge server started — Web UI at http://0.0.0.0:8765")
    start_ddb_client()
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


@app.websocket("/ws")
async def foundry_ws(ws: WebSocket):
    await ws.accept()
    foundry_clients.add(ws)
    log("info", f"Foundry client connected: {ws.client}")
    try:
        while True:
            await ws.receive_text()
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
        from fastapi import HTTPException
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

        # Parse HP modifiers from race/class/feat/background
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
        from fastapi import HTTPException
        raise HTTPException(status_code=502, detail=str(e))


@app.delete("/api/logs")
async def api_clear_logs():
    log_buffer.clear()
    with _log_file_lock:
        LOG_FILE.write_text("", encoding="utf-8")
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
    from fastapi import HTTPException
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


def _watch_quit():
    print("Press Q + Enter to stop.", flush=True)
    for line in sys.stdin:
        if line.strip().lower() == "q":
            print("Stopping...", flush=True)
            os._exit(0)


if __name__ == "__main__":
    threading.Thread(target=_watch_quit, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="warning")
