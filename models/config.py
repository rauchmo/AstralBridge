from pydantic import BaseModel


class ConfigUpdate(BaseModel):
    DDB_COBALT_TOKEN: str = ""
    DDB_GAME_ID: str = ""
    DDB_USER_ID: str = ""
