#!/usr/bin/env python3
"""Local database initialization, quality report, export, backup and restore."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.backup_service import BackupError, create_backup, restore_backup  # noqa: E402
from services.db import database_path, db_session, init_db  # noqa: E402
from services.knowledge_service import quality_report  # noqa: E402


def export_json(destination: Path, *, db_path: Path | None = None) -> Path:
    with db_session(db_path) as conn:
        tables = [
            "sources", "components", "component_datasheets", "component_pins", "component_diagnostic_profiles",
            "circuit_topologies", "failure_modes", "diagnostic_tests", "diagnostic_rules", "repair_cases", "measurements",
            "repair_tests", "case_components", "component_relationships", "validation_records",
        ]
        payload = {}
        for table in tables:
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            payload[table] = [dict(row) for row in rows]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=None, help="Override SQLite database path")
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("init", help="Create schema and seed official-source catalogue; does not reset repair cases")
    subs.add_parser("report", help="Print a data-quality summary")
    backup = subs.add_parser("backup", help="Create a new SQLite backup; existing targets are not overwritten")
    backup.add_argument("destination", type=Path)
    restore = subs.add_parser("restore", help="Validated restore; current DB is preserved as a before-restore backup")
    restore.add_argument("backup", type=Path)
    export = subs.add_parser("export", help="Export local records to JSON; may contain sensitive repair data")
    export.add_argument("destination", type=Path)
    args = parser.parse_args()
    db_path = args.db
    try:
        if args.command == "init":
            path = init_db(db_path)
            print(f"پایگاه داده آماده شد: {path}")
            print("داده‌های تعمیر قبلی پاک یا بازنشانی نشدند.")
        elif args.command == "report":
            init_db(db_path)
            print(json.dumps(quality_report(path=db_path), ensure_ascii=False, indent=2))
            print(f"مسیر پایگاه داده: {db_path or database_path()}")
        elif args.command == "backup":
            init_db(db_path)
            print(f"نسخه پشتیبان: {create_backup(args.destination, source=db_path)}")
        elif args.command == "restore":
            target = restore_backup(args.backup, destination=db_path)
            print(f"پایگاه داده بازیابی شد: {target}")
            print("اگر قبلاً فایل پایگاه داده وجود داشت، نسخه قبل از بازیابی کنار آن با پسوند .bak نگه داشته شد.")
        elif args.command == "export":
            init_db(db_path)
            print(f"خروجی JSON: {export_json(args.destination, db_path=db_path)}")
            print("این فایل ممکن است حاوی اطلاعات تعمیر محرمانه باشد؛ آن را امن نگه دارید.")
        return 0
    except (BackupError, RuntimeError, sqlite3.Error, OSError, ValueError) as exc:
        print(f"خطا: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
