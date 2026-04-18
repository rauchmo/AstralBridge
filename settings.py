import os
from pathlib import Path

ENV_PATH = Path(os.environ.get("ENV_PATH", str((Path(__file__).parent / "../.env").resolve())))
