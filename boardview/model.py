"""Board file parsing and validation (no Qt, fully unit-testable).

Native format ``circuit-ai-board/1`` (JSON). Coordinates are millimetres with
the origin at the board's top-left corner and Y growing downwards, matching a
board photo so photos and vector data share one coordinate system.

{
  "format": "circuit-ai-board/1",
  "name": "Pump controller rev B",
  "width_mm": 100, "height_mm": 80,
  "image": "board_top.png",                  // optional photo, relative to the JSON
  "parts": [
    {"ref": "U1", "part_number": "DRV8825", "package": "HTSSOP-28",
     "side": "top", "x": 50, "y": 40, "rotation": 0, "w": 9.7, "h": 4.4,
     "pins": [{"pin": "1", "name": "VCP", "net": "VCP", "x": 46, "y": 38.5}]}
  ]
}

CSV import uses two files: parts.csv (ref,part_number,package,side,x_mm,y_mm,
rotation,w_mm,h_mm) and pins.csv (part_ref,pin,net,x_mm,y_mm,side).
"""
from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path
from typing import Any

FORMAT = "circuit-ai-board/1"


class BoardFormatError(ValueError):
    pass


def _num(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise BoardFormatError(f"{label} باید عددی باشد: {value!r}") from exc
    if not math.isfinite(number):
        raise BoardFormatError(f"{label} باید عدد محدود باشد.")
    return number


def validate_board(data: dict[str, Any]) -> dict[str, Any]:
    """Validate + normalize a board dict; raises BoardFormatError on bad data."""
    if not isinstance(data, dict):
        raise BoardFormatError("داده برد باید یک شیء JSON باشد.")
    name = str(data.get("name", "")).strip()
    if not name:
        raise BoardFormatError("نام برد الزامی است.")
    width = _num(data.get("width_mm", 100), "width_mm")
    height = _num(data.get("height_mm", 80), "height_mm")
    if width <= 0 or height <= 0:
        raise BoardFormatError("ابعاد برد باید مثبت باشد.")
    parts_out, seen_refs = [], set()
    for raw in data.get("parts", []):
        ref = str(raw.get("ref", "")).strip()
        if not ref:
            raise BoardFormatError("هر قطعه باید ref داشته باشد (مثل U1).")
        if ref.upper() in seen_refs:
            raise BoardFormatError(f"ref تکراری: {ref}")
        seen_refs.add(ref.upper())
        side = str(raw.get("side", "top")).strip().lower()
        if side not in {"top", "bottom"}:
            raise BoardFormatError(f"side نامعتبر برای {ref}: {side}")
        pins_out, seen_pins = [], set()
        for pin in raw.get("pins", []):
            pin_name = str(pin.get("pin", pin.get("pin_name", ""))).strip()
            if not pin_name:
                raise BoardFormatError(f"پین بدون نام در قطعه {ref}")
            if pin_name in seen_pins:
                raise BoardFormatError(f"پین تکراری {pin_name} در {ref}")
            seen_pins.add(pin_name)
            pins_out.append({
                "pin_name": pin_name,
                "name": str(pin.get("name", "")).strip(),
                "net": str(pin.get("net", "")).strip(),
                "x": _num(pin.get("x"), f"{ref}.{pin_name}.x"),
                "y": _num(pin.get("y"), f"{ref}.{pin_name}.y"),
                "side": side,
                "diode_mv": pin.get("diode_mv"),
            })
        parts_out.append({
            "ref": ref,
            "part_number": str(raw.get("part_number", "")).strip(),
            "package": str(raw.get("package", "")).strip(),
            "side": side,
            "x": _num(raw.get("x"), f"{ref}.x"), "y": _num(raw.get("y"), f"{ref}.y"),
            "rotation": _num(raw.get("rotation", 0), f"{ref}.rotation"),
            "w": _num(raw.get("w", raw.get("w_mm", 5)), f"{ref}.w"),
            "h": _num(raw.get("h", raw.get("h_mm", 3)), f"{ref}.h"),
            "pins": pins_out,
        })
    return {"format": FORMAT, "name": name, "width_mm": width, "height_mm": height,
            "image": str(data.get("image", "")).strip(),
            "is_sample": bool(data.get("is_sample", False)), "parts": parts_out}


def load_board_json(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BoardFormatError(f"خواندن فایل برد ناموفق بود: {exc}") from exc
    board = validate_board(raw)
    if board["image"] and not Path(board["image"]).is_absolute():
        board["image_path"] = str((path.parent / board["image"]).resolve())
    else:
        board["image_path"] = board["image"]
    board["source_file"] = str(path)
    return board


def load_board_csv(parts_csv: str | Path, pins_csv: str | Path | None,
                   *, name: str, width_mm: float, height_mm: float) -> dict[str, Any]:
    parts: dict[str, dict[str, Any]] = {}
    with open(parts_csv, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            ref = (row.get("ref") or "").strip()
            if not ref:
                continue
            parts[ref] = {"ref": ref, "part_number": row.get("part_number", ""),
                          "package": row.get("package", ""), "side": row.get("side", "top"),
                          "x": row.get("x_mm"), "y": row.get("y_mm"),
                          "rotation": row.get("rotation", 0),
                          "w": row.get("w_mm", 5), "h": row.get("h_mm", 3), "pins": []}
    if pins_csv:
        with open(pins_csv, newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                ref = (row.get("part_ref") or "").strip()
                if ref not in parts:
                    raise BoardFormatError(f"پین برای قطعه ناموجود: {ref}")
                parts[ref]["pins"].append({
                    "pin": row.get("pin", ""), "net": row.get("net", ""),
                    "x": row.get("x_mm"), "y": row.get("y_mm")})
    return validate_board({"name": name, "width_mm": width_mm, "height_mm": height_mm,
                           "parts": list(parts.values())})


def parse_csv_text(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def board_stats(board: dict[str, Any]) -> dict[str, int]:
    pins = [p for part in board["parts"] for p in part["pins"]]
    return {"parts": len(board["parts"]), "pins": len(pins),
            "nets": len({p["net"] for p in pins if p["net"]}),
            "unconnected_pins": sum(1 for p in pins if not p["net"])}
