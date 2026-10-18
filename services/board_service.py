"""Persistence for BoardView: boards, parts, pins, nets, pin measurements."""
from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

from boardview.model import BoardFormatError, validate_board
from services.db import db_session

MEASUREMENT_KINDS = {"diode_mv", "voltage_v", "resistance_ohm", "continuity"}


def import_board(data: dict[str, Any], *, source_file: str = "", db_path=None) -> int:
    board = validate_board(data)
    with db_session(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO boards(name,source_file,format,width_mm,height_mm,image_path,is_sample)
               VALUES (?,?,?,?,?,?,?)""",
            (board["name"], source_file or board.get("source_file", ""), board["format"],
             board["width_mm"], board["height_mm"], board.get("image_path", ""),
             1 if board.get("is_sample") else 0))
        board_id = int(cur.lastrowid)
        for part in board["parts"]:
            pcur = conn.execute(
                """INSERT INTO board_parts(board_id,ref,part_number,package,side,x_mm,y_mm,rotation_deg,w_mm,h_mm)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (board_id, part["ref"], part["part_number"], part["package"], part["side"],
                 part["x"], part["y"], part["rotation"], part["w"], part["h"]))
            part_id = int(pcur.lastrowid)
            for pin in part["pins"]:
                pin_cur = conn.execute(
                    """INSERT INTO board_pins(part_id,pin_name,net,x_mm,y_mm,side) VALUES (?,?,?,?,?,?)""",
                    (part_id, pin["pin_name"], pin["net"], pin["x"], pin["y"], pin["side"]))
                if pin.get("diode_mv") is not None:
                    conn.execute(
                        """INSERT INTO board_pin_measurements(pin_id,kind,value,unit,note)
                           VALUES (?,'diode_mv',?,'mV','مقدار همراه فایل برد')""",
                        (int(pin_cur.lastrowid), float(pin["diode_mv"])))
    return board_id


def image_size_px(path: str | Path) -> tuple[int, int] | None:
    """PNG/JPEG pixel size with stdlib only (for image-only boards)."""
    data = Path(path).read_bytes()[:64 * 1024]
    if data.startswith(b"\x89PNG") and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data.startswith(b"\xff\xd8"):
        blob = Path(path).read_bytes()
        i = 2
        while i < len(blob) - 9:
            if blob[i] != 0xFF:
                i += 1; continue
            marker = blob[i + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack(">HH", blob[i + 5:i + 9])
                return w, h
            length = struct.unpack(">H", blob[i + 2:i + 4])[0]
            i += 2 + length
    return None


def import_image_board(path: str | Path, *, name: str = "", mm_per_10px: float = 1.0,
                       db_path=None) -> int:
    path = Path(path)
    size = image_size_px(path)
    if size is None:
        raise BoardFormatError("ابعاد تصویر خوانده نشد؛ فرمت باید PNG یا JPEG باشد.")
    width_mm, height_mm = size[0] * mm_per_10px / 10.0, size[1] * mm_per_10px / 10.0
    return import_board({"name": name or path.stem, "width_mm": width_mm,
                         "height_mm": height_mm, "image": str(path), "parts": []},
                        source_file=str(path), db_path=db_path)


def list_boards(*, db_path=None) -> list[dict[str, Any]]:
    with db_session(db_path) as conn:
        rows = conn.execute(
            """SELECT b.*, (SELECT COUNT(*) FROM board_parts p WHERE p.board_id=b.id) AS part_count,
                      (SELECT COUNT(*) FROM board_pins pn JOIN board_parts p ON p.id=pn.part_id
                        WHERE p.board_id=b.id) AS pin_count
               FROM boards b ORDER BY b.created_at DESC, b.id DESC""").fetchall()
        return [dict(r) for r in rows]


def get_board(board_id: int, *, db_path=None) -> dict[str, Any] | None:
    with db_session(db_path) as conn:
        row = conn.execute("SELECT * FROM boards WHERE id=?", (board_id,)).fetchone()
        if row is None:
            return None
        board = dict(row)
        meas: dict[int, list[dict[str, Any]]] = {}
        for m in conn.execute(
                """SELECT bm.* FROM board_pin_measurements bm
                   JOIN board_pins pn ON pn.id=bm.pin_id
                   JOIN board_parts p ON p.id=pn.part_id
                   WHERE p.board_id=? ORDER BY bm.created_at, bm.id""", (board_id,)):
            meas.setdefault(int(m["pin_id"]), []).append(dict(m))
        board["parts"] = []
        for prow in conn.execute("SELECT * FROM board_parts WHERE board_id=? ORDER BY ref", (board_id,)):
            part = dict(prow)
            part["pins"] = []
            for pin in conn.execute("SELECT * FROM board_pins WHERE part_id=? ORDER BY pin_name", (part["id"],)):
                item = dict(pin)
                item["measurements"] = meas.get(int(pin["id"]), [])
                item["diode_mv"] = next((m["value"] for m in item["measurements"]
                                          if m["kind"] == "diode_mv"), None)
                part["pins"].append(item)
            board["parts"].append(part)
        return board


def delete_board(board_id: int, *, db_path=None) -> None:
    with db_session(db_path) as conn:
        conn.execute("DELETE FROM boards WHERE id=?", (board_id,))


def add_part(board_id: int, part: dict[str, Any], *, db_path=None) -> int:
    ref = str(part.get("ref", "")).strip()
    if not ref:
        raise ValueError("نام قطعه (ref) الزامی است؛ مثل U7")
    with db_session(db_path) as conn:
        if not conn.execute("SELECT 1 FROM boards WHERE id=?", (board_id,)).fetchone():
            raise LookupError("برد پیدا نشد.")
        cur = conn.execute(
            """INSERT INTO board_parts(board_id,ref,part_number,package,side,x_mm,y_mm,rotation_deg,w_mm,h_mm)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (board_id, ref, part.get("part_number", ""), part.get("package", ""),
             part.get("side", "top"), float(part["x"]), float(part["y"]),
             float(part.get("rotation", 0)), float(part.get("w", 5)), float(part.get("h", 3))))
        return int(cur.lastrowid)


def add_pin(part_id: int, pin: dict[str, Any], *, db_path=None) -> int:
    with db_session(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO board_pins(part_id,pin_name,net,x_mm,y_mm,side) VALUES (?,?,?,?,?,?)",
            (part_id, str(pin["pin_name"]), str(pin.get("net", "")), float(pin["x"]),
             float(pin["y"]), pin.get("side", "top")))
        return int(cur.lastrowid)


def list_nets(board_id: int, *, db_path=None) -> list[dict[str, Any]]:
    with db_session(db_path) as conn:
        rows = conn.execute(
            """SELECT pn.net AS net, COUNT(*) AS pin_count,
                      GROUP_CONCAT(DISTINCT p.ref) AS part_refs
               FROM board_pins pn JOIN board_parts p ON p.id=pn.part_id
               WHERE p.board_id=? AND pn.net<>''
               GROUP BY pn.net ORDER BY pn.net""", (board_id,)).fetchall()
        return [dict(r) for r in rows]


def pins_on_net(board_id: int, net: str, *, db_path=None) -> list[dict[str, Any]]:
    with db_session(db_path) as conn:
        return [dict(r) for r in conn.execute(
            """SELECT pn.*, p.ref AS part_ref FROM board_pins pn
               JOIN board_parts p ON p.id=pn.part_id
               WHERE p.board_id=? AND pn.net=? COLLATE NOCASE ORDER BY p.ref, pn.pin_name""",
            (board_id, net))]


def save_pin_measurement(pin_id: int, *, kind: str, value: float | None, unit: str = "",
                         note: str = "", case_id: int | None = None, db_path=None) -> int:
    if kind not in MEASUREMENT_KINDS:
        raise ValueError(f"نوع اندازه‌گیری نامعتبر: {kind}")
    with db_session(db_path) as conn:
        if not conn.execute("SELECT 1 FROM board_pins WHERE id=?", (pin_id,)).fetchone():
            raise LookupError("پین پیدا نشد.")
        cur = conn.execute(
            """INSERT INTO board_pin_measurements(pin_id,case_id,kind,value,unit,note)
               VALUES (?,?,?,?,?,?)""", (pin_id, case_id, kind, value, unit, note))
        return int(cur.lastrowid)


def pin_measurements(pin_id: int, *, db_path=None) -> list[dict[str, Any]]:
    with db_session(db_path) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM board_pin_measurements WHERE pin_id=? ORDER BY created_at, id", (pin_id,))]


def seed_bundled_boards(*, db_path=None) -> int:
    """Import bundled sample/real boards once, when the user has no boards yet."""
    from services.db import PROJECT_ROOT
    with db_session(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM boards").fetchone()[0]
    if count:
        return 0
    imported = 0
    for folder in ("real_boards", "sample_boards"):
        directory = PROJECT_ROOT / "data" / folder
        if not directory.exists():
            continue
        for file in sorted(directory.glob("*.board.json")):
            from boardview.model import load_board_json
            import_board(load_board_json(file), source_file=str(file), db_path=db_path)
            imported += 1
    return imported
