import asyncio
import pytest
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def bridge_app():
    with patch("services.ddb_client.start_ddb_client"), \
         patch("dancing_lights.layers.dl_ds_ambient_set", new_callable=AsyncMock):
        from bridge import app
        return app


@pytest.fixture(scope="session")
def client(bridge_app):
    with TestClient(bridge_app) as c:
        yield c


@pytest.fixture(autouse=True)
def clear_roll_state():
    from services import roll_store
    roll_store.roll_history.clear()
    roll_store.roll_index.clear()
    yield
    roll_store.roll_history.clear()
    roll_store.roll_index.clear()
