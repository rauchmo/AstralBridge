import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

import logger
from logger import log, log_buffer, log_subscribers

router = APIRouter()


@router.get("/api/logs/stream")
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


@router.delete("/api/logs")
async def api_clear_logs():
    log_buffer.clear()
    with logger._log_file_lock:
        logger.LOG_FILE.write_text("", encoding="utf-8")
    log("info", "Logs cleared.")
    return {"status": "ok"}
