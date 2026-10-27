import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as appmod


@pytest.fixture
def client(tmp_path):
    appmod.DB_PATH = str(tmp_path / "report.db")
    appmod.PLATFORM_API_TOKEN = ""
    appmod.init_db()
    return appmod.app.test_client()