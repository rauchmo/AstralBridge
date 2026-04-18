import json
import threading

import requests

from logger import DATA_DIR, log

WEBHOOKS_FILE = DATA_DIR / "webhooks.json"


def load_webhooks() -> list[str]:
    if not WEBHOOKS_FILE.exists():
        return []
    try:
        return json.loads(WEBHOOKS_FILE.read_text())
    except Exception:
        return []


def save_webhooks(urls: list[str]):
    WEBHOOKS_FILE.write_text(json.dumps(urls, indent=2))


def dispatch_webhooks(payload: dict):
    urls = load_webhooks()
    if not urls:
        return

    def _send():
        for url in urls:
            try:
                requests.post(url, json=payload, timeout=5)
            except Exception as e:
                log("warn", f"Webhook to {url} failed: {e}")

    threading.Thread(target=_send, daemon=True).start()
