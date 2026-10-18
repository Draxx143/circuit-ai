from pathlib import Path

import pytest

from services.db import init_db


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "test_circuit_ai.sqlite3"
    init_db(path)
    return path
