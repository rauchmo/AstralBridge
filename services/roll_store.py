import json
from collections import deque
from logger import DATA_DIR, log

ROLLS_FILE = DATA_DIR / "rolls.json"

roll_history: deque = deque(maxlen=100)
roll_index: dict = {}


def load_persisted_rolls():
    if not ROLLS_FILE.exists():
        return
    try:
        data = json.loads(ROLLS_FILE.read_text(encoding="utf-8"))
        for entry in reversed(data.get("history", [])):
            roll_history.appendleft(entry)
        roll_index.update(data.get("index", {}))
    except Exception:
        pass


def save_rolls():
    try:
        payload = {"history": list(roll_history), "index": roll_index}
        ROLLS_FILE.write_text(json.dumps(payload), encoding="utf-8")
    except Exception as e:
        print(f"[persist] Failed to save rolls: {e}", flush=True)


load_persisted_rolls()
