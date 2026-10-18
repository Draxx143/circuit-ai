import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_main_window_builds_all_pages(qapp, tmp_path):
    from desktop_app.window import NAV, MainWindow

    win = MainWindow(tmp_path / "desktop.sqlite3")
    assert len(win.page_widgets) == len(NAV) == 8
    for row in range(len(NAV)):
        win.nav.setCurrentRow(row)  # every page must build + refresh without error
    win.close()


def test_diagnosis_flow_creates_hypothesis(qapp, tmp_path):
    from desktop_app.window import MainWindow

    win = MainWindow(tmp_path / "flow.sqlite3")
    page = win.page_widgets["diagnosis"]
    page.board_name.setText("برد تست")
    page.symptom_checks["no_output"].setChecked(True)
    page.create_case()
    assert page.case_id
    # The page slot pops a modal confirmation, so drive the same service calls it makes.
    from services.repair_service import add_measurement
    add_measurement(page.case_id, {"signal": "VIN", "measured_value": 24, "unit": "V",
                                   "measurement_state": "powered"}, path=win.db_path)
    add_measurement(page.case_id, {"signal": "VOUT", "measured_value": 0, "unit": "V",
                                   "measurement_state": "powered"}, path=win.db_path)
    result = page.run_diagnosis()
    assert "conversion_stage_not_delivering" in [h["code"] for h in result["ranked_hypotheses"]]
    assert page.test_combo.count() >= 1
    win.close()
