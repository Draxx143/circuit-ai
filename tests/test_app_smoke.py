import os
from pathlib import Path


def test_streamlit_app_loads_dashboard(tmp_path, monkeypatch):
    monkeypatch.setenv("CIRCUIT_AI_DB_PATH", str(tmp_path / "ui.sqlite3"))
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=60)
    app.run()
    assert not app.exception, app.exception
    assert any("داشبورد" in (r.value or "") for r in app.radio)
