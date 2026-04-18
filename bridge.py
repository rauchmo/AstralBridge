import asyncio
import os
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

import logger
from dancing_lights import router as dl_router, dl_load, dl_ds_ambient_set
from logger import log
from routes.character import router as character_router
from routes.config import router as config_router
from routes.logs import router as logs_router
from routes.rolls import router as rolls_router
from routes.webhooks import router as webhooks_router
from routes.ws import router as ws_router
from services.ddb_client import start_ddb_client
from settings import ENV_PATH

load_dotenv(dotenv_path=ENV_PATH)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.main_event_loop = asyncio.get_event_loop()
    log("info", "Bridge server started — Web UI at http://0.0.0.0:8765")
    start_ddb_client()
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

app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(dl_router)
app.include_router(rolls_router)
app.include_router(config_router)
app.include_router(webhooks_router)
app.include_router(character_router)
app.include_router(logs_router)
app.include_router(ws_router)


@app.get("/", response_class=HTMLResponse)
async def ui():
    return (Path(__file__).parent / "templates/index.html").read_text()


def _watch_quit():
    print("Press Q + Enter to stop.", flush=True)
    for line in sys.stdin:
        if line.strip().lower() == "q":
            print("Stopping...", flush=True)
            os._exit(0)


if __name__ == "__main__":
    threading.Thread(target=_watch_quit, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="warning")
