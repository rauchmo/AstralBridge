from pydantic import BaseModel


class WebhookAdd(BaseModel):
    url: str
