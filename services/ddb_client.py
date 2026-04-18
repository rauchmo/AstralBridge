import asyncio
import json
import os
import threading
import types
from datetime import datetime

import requests
import websocket

import logger
from logger import log
from services.foundry import broadcast_to_foundry
from services.roll_store import roll_history, roll_index, save_rolls
from services.webhook_service import dispatch_webhooks

ddb_ws_instance = None
ddb_connected = False
_reconnect_enabled = True


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
    if data.get("eventType") != "dice/roll/fulfilled":
        return
    try:
        roll = parse_roll(data)
        context = data["data"]["context"]
        roll_id = data.get("id", datetime.now().isoformat())

        summary = {
            "id":          roll_id,
            "ts":          datetime.now().strftime("%H:%M:%S"),
            "character":   roll.character,
            "entity_id":   roll.entity_id,
            "entity_type": context.get("entityType", ""),
            "game_id":     data.get("gameId", ""),
            "action":      roll.action,
            "rollType":    roll.roll_type,
            "total":       roll.total,
            "text":        roll.text,
            "dice":        roll.dice,
            "constant":    roll.constant,
        }

        roll_index[roll_id] = {**summary, "raw": data}
        roll_history.appendleft(summary)

        if len(roll_index) > 110:
            oldest = next(iter(roll_index))
            del roll_index[oldest]

        save_rolls()
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
            from dancing_lights import dl_detect_event, dl_trigger, dl_auto_signal
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
