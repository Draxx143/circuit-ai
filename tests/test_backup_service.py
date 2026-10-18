from pathlib import Path

import pytest

from services.backup_service import BackupError, create_backup, restore_backup
from services.db import init_db
from services.repair_service import create_case, list_cases


def test_backup_and_restore_preserve_data_and_create_safety_copy(db_path, tmp_path):
    create_case({"board_name": "پرونده اول"}, path=db_path)
    backup = create_backup(tmp_path / "before.sqlite3", source=db_path)
    create_case({"board_name": "پرونده دوم"}, path=db_path)
    restored = restore_backup(backup, destination=db_path)
    assert restored == db_path
    assert [c["board_name"] for c in list_cases(path=db_path)] == ["پرونده اول"]
    assert list(tmp_path.glob("test_circuit_ai.sqlite3.before-restore-*.bak"))


def test_backup_refuses_overwrite(db_path, tmp_path):
    destination = tmp_path / "existing.sqlite3"
    destination.write_bytes(b"do not replace")
    with pytest.raises(BackupError):
        create_backup(destination, source=db_path)
    assert destination.read_bytes() == b"do not replace"


def test_restore_rejects_non_database(db_path, tmp_path):
    bad = tmp_path / "not-a-db.sqlite3"
    bad.write_text("not sqlite", encoding="utf-8")
    with pytest.raises(BackupError):
        restore_backup(bad, destination=db_path)
