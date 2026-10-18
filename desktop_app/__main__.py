"""Entry point: python -m desktop_app [--smoke-test]"""
from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="CIRCUIT AI desktop")
    parser.add_argument("--smoke-test", action="store_true",
                        help="Initialize the database, build the main window offscreen, print status and exit")
    parser.add_argument("--db", default=None, help="SQLite database path override")
    args = parser.parse_args()

    if args.smoke_test:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from services.db import database_path, init_db
    from .window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("CIRCUIT AI")
    app.setOrganizationName("CIRCUIT AI")
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

    db = init_db(args.db) if args.db else init_db()
    window = MainWindow(db)
    if args.smoke_test:
        print(f"SMOKE OK · db={db} · pages={len(window.page_widgets)} · "
              f"dashboard/calculators/diagnosis built · qt={app.platformName()}")
        return 0
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
