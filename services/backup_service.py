"""Safe SQLite backup and validated restore using SQLite's online backup API."""
from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from services.db import CURRENT_SCHEMA_VERSION, database_path


class BackupError(RuntimeError):
    pass


def create_backup(destination: str | Path, *, source: str | Path | None = None) -> Path:
    src = Path(source).expanduser().resolve() if source else database_path()
    dst = Path(destination).expanduser().resolve()
    if not src.exists():
        raise BackupError(f"پایگاه داده پیدا نشد: {src}")
    if src == dst:
        raise BackupError("مسیر نسخه پشتیبان نباید با فایل پایگاه داده یکی باشد.")
    dst.parent.mkdir(parents=True, exist_ok=True)
    # Do not overwrite an existing backup without an explicit new filename.
    if dst.exists():
        raise BackupError(f"این فایل از قبل وجود دارد؛ نام دیگری انتخاب کنید: {dst}")
    try:
        source_conn = sqlite3.connect(str(src), timeout=15)
        target_conn = sqlite3.connect(str(dst), timeout=15)
        source_conn.backup(target_conn)
        target_conn.commit()
        check = target_conn.execute("PRAGMA integrity_check").fetchone()[0]
        target_conn.close()
        source_conn.close()
        if check != "ok":
            dst.unlink(missing_ok=True)
            raise BackupError(f"نسخه پشتیبان از آزمون integrity رد شد: {check}")
        if os.name == "posix":
            dst.chmod(0o600)
        return dst
    except (sqlite3.Error, OSError) as exc:
        dst.unlink(missing_ok=True)
        raise BackupError(f"ایجاد نسخه پشتیبان ناموفق بود: {exc}") from exc


def restore_backup(backup: str | Path, *, destination: str | Path | None = None) -> Path:
    """Validate a backup first, then atomically replace the target DB. Existing DB is backed up."""
    src = Path(backup).expanduser().resolve()
    target = Path(destination).expanduser().resolve() if destination else database_path()
    if not src.is_file():
        raise BackupError(f"فایل پشتیبان پیدا نشد: {src}")
    if src == target:
        raise BackupError("فایل پشتیبان و پایگاه داده مقصد یکسان هستند.")
    try:
        check_conn = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)
        integrity = check_conn.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {r[0] for r in check_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {"schema_meta", "repair_cases", "components", "sources"}
        version_row = check_conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
        check_conn.close()
        try:
            backup_version = int(version_row[0]) if version_row else 0
        except (TypeError, ValueError):
            backup_version = 0
        if backup_version < 1 or backup_version > CURRENT_SCHEMA_VERSION:
            raise BackupError(
                f"نسخه اسکیما پشتیبان ({backup_version or 'نامشخص'}) با این نسخه برنامه "
                f"(حداکثر {CURRENT_SCHEMA_VERSION}) سازگار نیست.")
        if integrity != "ok" or not required.issubset(tables):
            raise BackupError("فایل انتخاب‌شده پایگاه داده CIRCUIT AI معتبر نیست یا integrity check را نگذرانده است.")
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safety_copy = None
        if target.exists():
            safety_copy = target.with_name(f"{target.name}.before-restore-{timestamp}.bak")
            if safety_copy.exists():
                raise BackupError("نام نسخه محافظتی موجود است؛ بازیابی لغو شد.")
            old_conn = sqlite3.connect(str(target))
            safe_conn = sqlite3.connect(str(safety_copy))
            old_conn.backup(safe_conn)
            safe_conn.close()
            old_conn.close()
        fd, temp_name = tempfile.mkstemp(prefix=".circuit-ai-restore-", suffix=".sqlite3", dir=target.parent)
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            src_conn = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)
            temp_conn = sqlite3.connect(str(temp_path))
            src_conn.backup(temp_conn)
            temp_conn.commit()
            post = temp_conn.execute("PRAGMA integrity_check").fetchone()[0]
            temp_conn.close()
            src_conn.close()
            if post != "ok":
                raise BackupError(f"نسخه کپی‌شده از آزمون سلامت رد شد: {post}")
            if os.name == "posix":
                temp_path.chmod(0o600)
            os.replace(temp_path, target)
        finally:
            temp_path.unlink(missing_ok=True)
        return target
    except BackupError:
        raise
    except (sqlite3.Error, OSError) as exc:
        raise BackupError(f"بازیابی ناموفق بود: {exc}") from exc
