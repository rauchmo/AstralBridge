from pydantic import BaseModel


class RollSummary(BaseModel):
    id: str
    ts: str
    character: str
    entity_id: str | None
    entity_type: str
    game_id: str
    action: str
    rollType: str
    total: int
    text: str
    dice: list[dict]
    constant: int
