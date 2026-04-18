from fastapi import APIRouter, HTTPException

from models.webhook import WebhookAdd
from services.webhook_service import load_webhooks, save_webhooks

router = APIRouter()


@router.get("/api/webhooks")
async def api_get_webhooks():
    return load_webhooks()


@router.post("/api/webhooks")
async def api_add_webhook(body: WebhookAdd):
    url = body.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="url required")
    urls = load_webhooks()
    if url not in urls:
        urls.append(url)
        save_webhooks(urls)
    return urls


@router.delete("/api/webhooks/{index}")
async def api_delete_webhook(index: int):
    urls = load_webhooks()
    if index < 0 or index >= len(urls):
        raise HTTPException(status_code=404, detail="Index out of range")
    urls.pop(index)
    save_webhooks(urls)
    return urls
