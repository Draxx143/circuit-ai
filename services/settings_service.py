"""Small persistent application settings in SQLite."""
from services.db import db_session


def get_setting(key: str, default: str, *, path=None) -> str:
    with db_session(path) as conn:
        row = conn.execute("SELECT setting_value FROM app_settings WHERE setting_key=?", (key,)).fetchone()
        return str(row[0]) if row else default


def set_setting(key: str, value: str, *, path=None) -> None:
    with db_session(path) as conn:
        conn.execute(
            """INSERT INTO app_settings(setting_key,setting_value) VALUES(?,?)
               ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value,
               updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')""",
            (key, value),
        )
