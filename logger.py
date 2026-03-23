import json
import threading
from collections import deque
from datetime import datetime
from pathlib import Path

DATA_DIR = (Path(__file__).parent / "data").resolve()
DATA_DIR.mkdir(exist_ok=True)
LOG_FILE = DATA_DIR / "logs.jsonl"

log_buffer: deque = deque(maxlen=500)
log_subscribers: list = []
main_event_loop = None
_log_file_lock = threading.Lock()


def _load_persisted_logs():
    if not LOG_FILE.exists():
        return
    try:
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
        for line in lines[-log_buffer.maxlen:]:
            try:
                log_buffer.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    except Exception:
        pass


def _append_log_file(entry: dict):
    with _log_file_lock:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    try:
        if LOG_FILE.stat().st_size > 5 * 1024 * 1024:
            LOG_FILE.replace(LOG_FILE.with_suffix(".jsonl.bak"))
    except Exception:
        pass


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


_load_persisted_logs()
