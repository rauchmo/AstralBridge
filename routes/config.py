import asyncio
import os
import threading

from dotenv import load_dotenv, set_key
from fastapi import APIRouter

import services.ddb_client as ddb
from logger import log
from models.config import ConfigUpdate
from services.foundry import foundry_clients
from settings import ENV_PATH

router = APIRouter()


@router.get("/api/status")
async def api_status():
    return {"ddb_connected": ddb.ddb_connected, "foundry_clients": len(foundry_clients)}


@router.get("/api/config")
async def api_get_config():
    return {
        "DDB_COBALT_TOKEN": os.getenv("DDB_COBALT_TOKEN", ""),
        "DDB_GAME_ID":      os.getenv("DDB_GAME_ID", ""),
        "DDB_USER_ID":      os.getenv("DDB_USER_ID", ""),
    }


@router.post("/api/config")
async def api_update_config(cfg: ConfigUpdate):
    for key, val in cfg.model_dump().items():
        if val:
            set_key(str(ENV_PATH), key, val)
            os.environ[key] = val
    load_dotenv(dotenv_path=ENV_PATH, override=True)
    log("info", "Configuration updated.")
    return {"status": "ok"}


@router.post("/api/restart")
async def api_restart():
    log("info", "Manual restart triggered.")
    ddb._reconnect_enabled = False
    if ddb.ddb_ws_instance:
        try:
            ddb.ddb_ws_instance.close()
        except Exception:
            pass
    await asyncio.sleep(1.0)
    ddb._reconnect_enabled = True
    ddb.ddb_connected = False
    threading.Thread(target=ddb.start_ddb_client, daemon=True).start()
    return {"status": "restarting"}
