"""KiCad .kicad_pcb importer + bundled real-board seeding tests (no Qt)."""
import json

from boardview.kicad import load_kicad_pcb, parse_sexpr
from boardview.model import validate_board
from services import board_service
from services.db import init_db


MINIMAL_PCB = """(kicad_pcb (version 20230121) (generator pcbnew)
  (general (thickness 1.6))
  (paper "A4")
  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))
  (net 0 "") (net 1 "GND") (net 2 "+3V3")
  (gr_line (start 0 0) (end 20 0) (stroke (width 0.1) (type default)) (layer "Edge.Cuts"))
  (gr_line (start 20 0) (end 20 10) (stroke (width 0.1) (type default)) (layer "Edge.Cuts"))
  (gr_line (start 20 10) (end 0 10) (stroke (width 0.1) (type default)) (layer "Edge.Cuts"))
  (gr_line (start 0 10) (end 0 0) (stroke (width 0.1) (type default)) (layer "Edge.Cuts"))
  (footprint "Package_TO_SOT_SMD:SOT-23" (layer "F.Cu") (at 5 5)
    (property "Reference" "Q1" (at 0 -2 0) (layer "F.SilkS"))
    (property "Value" "2N7002" (at 0 2 0) (layer "F.Fab"))
    (pad "1" smd rect (at -0.95 0) (size 0.6 1.4) (layers "F.Cu" "F.Paste" "F.Mask") (net 1 "GND"))
    (pad "2" smd rect (at 0.95 0) (size 0.6 1.4) (layers "F.Cu" "F.Paste" "F.Mask") (net 2 "+3V3"))
    (pad "3" smd rect (at 0 0.95) (size 0.6 1.4) (layers "F.Cu" "F.Paste" "F.Mask"))
  )
  (footprint "Resistor_SMD:R_0603" (layer "B.Cu") (at 12 5 90)
    (property "Reference" "R1" (at 0 0 0) (layer "B.SilkS"))
    (property "Value" "10k" (at 0 0 0) (layer "B.Fab"))
    (pad "1" smd rect (at -0.8 0) (size 0.9 0.9) (layers "B.Cu") (net 1 "GND"))
    (pad "2" smd rect (at 0.8 0) (size 0.9 0.9) (layers "B.Cu") (net 2 "+3V3"))
  )
)
"""


def test_parse_sexpr_basic():
    tree = parse_sexpr('(a (b 1) "x y")')
    assert tree[0] == "a" and tree[1] == ["b", "1"] and tree[2] == "x y"


def test_kicad_import_geometry_nets_and_sides(tmp_path):
    path = tmp_path / "mini.kicad_pcb"
    path.write_text(MINIMAL_PCB, encoding="utf-8")
    board = load_kicad_pcb(path)
    validate_board(board)  # must satisfy the native board format
    assert board["name"] == "mini"
    assert board["width_mm"] == 20 and board["height_mm"] == 10
    parts = {p["ref"]: p for p in board["parts"]}
    assert parts["Q1"]["side"] == "top" and parts["R1"]["side"] == "bottom"
    assert parts["Q1"]["part_number"] == "2N7002"
    q1 = {p["pin_name"]: p for p in parts["Q1"]["pins"]}
    assert q1["1"]["net"] == "GND" and q1["2"]["net"] == "+3V3" and q1["3"]["net"] == ""
    # R1 is rotated 90 degrees: pad offsets rotate with the footprint.
    r1 = {p["pin_name"]: p for p in parts["R1"]["pins"]}
    assert abs(r1["1"]["x"] - 12) < 1e-6 and abs(r1["1"]["y"] - 5.8) < 1e-6


def test_bundled_real_board_seeds_without_measurements(tmp_path):
    db = str(tmp_path / "t.sqlite3")
    init_db(db)
    assert board_service.seed_bundled_boards(db_path=db) >= 2
    assert board_service.seed_bundled_boards(db_path=db) == 0  # idempotent
    boards = board_service.list_boards(db_path=db)
    real = [b for b in boards if not b["is_sample"]]
    assert real, "a real (non-sample) board must be bundled"
    board = board_service.get_board(real[0]["id"], db_path=db)
    assert real[0]["part_count"] > 100 and real[0]["pin_count"] > 500
    # No diode measurement may be fabricated for a real board.
    assert all(p.get("diode_mv") is None for part in board["parts"] for p in part["pins"])
    nets = board_service.list_nets(real[0]["id"], db_path=db)
    assert len(nets) > 100
