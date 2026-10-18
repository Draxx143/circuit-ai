import json

import pytest

from boardview.model import BoardFormatError, board_stats, load_board_json, validate_board
from services.board_service import (
    add_part, get_board, import_board, list_nets, pins_on_net, save_pin_measurement,
)
from services.db import init_db

SAMPLE = {
    "name": "برد تست", "width_mm": 50, "height_mm": 40,
    "parts": [
        {"ref": "U1", "part_number": "TESTREG", "x": 20, "y": 20, "w": 6, "h": 4,
         "pins": [{"pin": "1", "net": "VIN", "x": 18, "y": 19},
                  {"pin": "2", "net": "GND", "x": 18, "y": 21, "diode_mv": 4},
                  {"pin": "3", "net": "VOUT", "x": 22, "y": 20, "diode_mv": 501}]},
        {"ref": "C1", "x": 30, "y": 20, "pins": [{"pin": "1", "net": "VOUT", "x": 29, "y": 20},
                                                 {"pin": "2", "net": "GND", "x": 31, "y": 20}]},
    ],
}


@pytest.fixture
def bdb(tmp_path):
    path = tmp_path / "board.sqlite3"
    init_db(path)
    return path


def test_validate_rejects_duplicate_ref_and_bad_numbers():
    bad = json.loads(json.dumps(SAMPLE)); bad["parts"].append(bad["parts"][0])
    with pytest.raises(BoardFormatError):
        validate_board(bad)
    bad2 = json.loads(json.dumps(SAMPLE)); bad2["parts"][0]["x"] = "abc"
    with pytest.raises(BoardFormatError):
        validate_board(bad2)
    assert board_stats(validate_board(SAMPLE)) == {"parts": 2, "pins": 5, "nets": 3, "unconnected_pins": 0}


def test_import_nets_and_measurements_roundtrip(bdb):
    board_id = import_board(SAMPLE, db_path=bdb)
    board = get_board(board_id, db_path=bdb)
    assert [p["ref"] for p in board["parts"]] == ["C1", "U1"] or len(board["parts"]) == 2
    nets = {n["net"]: n["pin_count"] for n in list_nets(board_id, db_path=bdb)}
    assert nets == {"VIN": 1, "GND": 2, "VOUT": 2}
    assert len(pins_on_net(board_id, "gnd", db_path=bdb)) == 2  # case-insensitive net lookup
    u1 = next(p for p in board["parts"] if p["ref"] == "U1")
    pin3 = next(p for p in u1["pins"] if p["pin_name"] == "3")
    assert pin3["diode_mv"] == 501  # sample-file diode value imported as measurement
    save_pin_measurement(pin3["id"], kind="voltage_v", value=4.98, unit="V", db_path=bdb)
    reloaded = get_board(board_id, db_path=bdb)
    pin3b = next(p for p in next(x for x in reloaded["parts"] if x["ref"] == "U1")["pins"] if p["pin_name"] == "3")
    assert pin3b["measurements"][-1]["value"] == 4.98
    with pytest.raises(ValueError):
        save_pin_measurement(pin3["id"], kind="guess", value=1, db_path=bdb)


def test_add_part_on_image_board(bdb):
    board_id = import_board({"name": "عکس برد", "width_mm": 80, "height_mm": 60, "parts": []}, db_path=bdb)
    part_id = add_part(board_id, {"ref": "U9", "x": 10, "y": 12}, db_path=bdb)
    assert part_id > 0
    with pytest.raises(Exception):
        add_part(board_id, {"ref": "U9", "x": 1, "y": 1}, db_path=bdb)  # duplicate ref


def test_sample_board_file_loads():
    from pathlib import Path
    sample = Path(__file__).resolve().parents[1] / "data" / "sample_boards" / "motor_control_demo.board.json"
    board = load_board_json(sample)
    assert board["is_sample"] is True
    stats = board_stats(board)
    assert stats["parts"] >= 20 and stats["pins"] >= 80 and stats["nets"] >= 15


@pytest.fixture(scope="module")
def qapp():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_boardview_page_flow(qapp, tmp_path):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from desktop_app.window import MainWindow

    win = MainWindow(tmp_path / "bv-ui.sqlite3")
    page = win.page_widgets["boardview"]
    win.navigate("boardview")
    page.load_sample()
    assert page.board is not None and len(page.board["parts"]) >= 20
    assert page.parts_list.count() >= 20 and page.nets_list.count() >= 10
    page.select_part("U4")
    assert page.pins_table.rowCount() >= 10
    page.highlight_net("GND")
    rows = page.net_pins.rowCount()
    assert rows >= 5  # GND appears across the whole demo board
    pin_item = next(iter(page.pin_items.values()))
    assert pin_item.pin["id"]
    win.close()
