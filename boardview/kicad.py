"""KiCad .kicad_pcb importer (KiCad 6/7/8 S-expression format).

Extracts real board data — footprint references/values, positions, sides,
pad positions and net names, and the Edge.Cuts outline — and converts it to
the circuit-ai-board/1 model. Graphics, tracks and zones are not converted;
this is a placement/netlist map for diagnosis, not a PCB editor.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from .model import BoardFormatError, validate_board


def _tokenize(text: str) -> list:
    tokens, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
        elif ch in "()":
            tokens.append(ch); i += 1
        elif ch == '"':
            j, buf = i + 1, []
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j + 1]); j += 2
                else:
                    buf.append(text[j]); j += 1
            tokens.append(("str", "".join(buf))); i = j + 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in "()":
                j += 1
            tokens.append(text[i:j]); i = j
    return tokens


def _parse(tokens: list) -> Any:
    pos = 0

    def rec():
        nonlocal pos
        tok = tokens[pos]; pos += 1
        if tok == "(":
            out = []
            while pos < len(tokens) and tokens[pos] != ")":
                out.append(rec())
            pos += 1  # consume ')'
            return out
        if isinstance(tok, tuple):
            return tok[1]
        return tok

    return rec()


def parse_sexpr(text: str):
    """Parse one KiCad S-expression document into nested lists/strings."""
    return _parse(_tokenize(text))


def _children(node: list, head: str) -> list[list]:
    return [c for c in node if isinstance(c, list) and c and c[0] == head]


def _child(node: list, head: str) -> list | None:
    found = _children(node, head)
    return found[0] if found else None


def _at(node: list) -> tuple[float, float, float]:
    at = _child(node, "at")
    if not at or len(at) < 3:
        return 0.0, 0.0, 0.0
    rot = float(at[3]) if len(at) > 3 else 0.0
    return float(at[1]), float(at[2]), rot


def _rotate(px: float, py: float, deg: float) -> tuple[float, float]:
    rad = math.radians(deg)
    return (px * math.cos(rad) + py * math.sin(rad),
            -px * math.sin(rad) + py * math.cos(rad))


def load_kicad_pcb(path: str | Path, *, name: str = "") -> dict[str, Any]:
    path = Path(path)
    try:
        root = _parse(_tokenize(path.read_text(encoding="utf-8", errors="replace")))
    except (OSError, IndexError, ValueError) as exc:
        raise BoardFormatError(f"خواندن فایل KiCad ناموفق بود: {exc}") from exc
    if not (isinstance(root, list) and root and root[0] == "kicad_pcb"):
        raise BoardFormatError("این فایل .kicad_pcb معتبر نیست.")

    # Board outline from Edge.Cuts graphics, else footprint bounding box.
    outline_pts: list[tuple[float, float]] = []
    for head in ("gr_line", "gr_rect", "gr_arc", "gr_circle"):
        for node in _children(root, head):
            layer = _child(node, "layer")
            if not layer or "Edge.Cuts" not in [str(x) for x in layer[1:]]:
                continue
            for key in ("start", "end", "mid", "center"):
                pt = _child(node, key)
                if pt and len(pt) >= 3:
                    outline_pts.append((float(pt[1]), float(pt[2])))

    raw_parts = []
    seen_refs: dict[str, int] = {}
    for fp in _children(root, "footprint"):
        lib = str(fp[1]) if len(fp) > 1 else ""
        fx, fy, frot = _at(fp)
        layer_node = _child(fp, "layer")
        side = "bottom" if layer_node and any("B.Cu" == str(x) for x in layer_node[1:]) else "top"
        ref, value = "", ""
        for text in _children(fp, "fp_text"):
            if len(text) >= 3 and text[1] == "reference":
                ref = str(text[2])
            elif len(text) >= 3 and text[1] == "value":
                value = str(text[2])
        for prop in _children(fp, "property"):
            if len(prop) >= 3 and prop[1] == "Reference":
                ref = str(prop[2])
            elif len(prop) >= 3 and prop[1] == "Value":
                value = str(prop[2])
        if not ref:
            continue
        seen_refs[ref] = seen_refs.get(ref, 0) + 1
        if seen_refs[ref] > 1:  # silkscreen logos etc. repeat a "reference" on real boards
            ref = f"{ref}#{seen_refs[ref]}"
        pads = []
        seen_pins: dict[str, int] = {}
        for pad in _children(fp, "pad"):
            if len(pad) < 2 or str(pad[1]) == "":
                continue  # mechanical / unnamed pads are not diagnostic pins
            px, py, _ = _at(pad)
            rx, ry = _rotate(px, py, frot)
            net = ""
            net_node = _child(pad, "net")
            if net_node and len(net_node) >= 3:
                net = str(net_node[2])
            pin_name = str(pad[1])
            seen_pins[pin_name] = seen_pins.get(pin_name, 0) + 1
            if seen_pins[pin_name] > 1:  # real boards repeat a pin number (e.g. power balls)
                pin_name = f"{pin_name}#{seen_pins[pin_name]}"
            pads.append({"pin": pin_name, "net": net,
                         "x": fx + rx, "y": fy + ry, "_local": (px, py)})
        xs = [p["x"] for p in pads] or [fx]; ys = [p["y"] for p in pads] or [fy]
        w = max(max(xs) - min(xs), 1.2); h = max(max(ys) - min(ys), 1.2)
        raw_parts.append({"ref": ref, "part_number": value,
                          "package": lib.split(":")[-1], "side": side,
                          "x": fx, "y": fy, "rotation": frot, "w": w, "h": h,
                          "pins": pads})

    if not raw_parts:
        raise BoardFormatError("هیچ فوت‌پرینت دارای Reference در فایل پیدا نشد.")
    all_x = [p["x"] for p in raw_parts] + [pt[0] for pt in outline_pts]
    all_y = [p["y"] for p in raw_parts] + [pt[1] for pt in outline_pts]
    min_x, min_y = min(all_x), min(all_y)
    width = max(max(all_x) - min_x, 10.0); height = max(max(all_y) - min_y, 10.0)
    for part in raw_parts:
        part["x"] -= min_x; part["y"] -= min_y
        for pin in part["pins"]:
            pin["x"] -= min_x; pin["y"] -= min_y
            pin.pop("_local", None)
    board_name = name or _title(root) or path.stem
    return validate_board({"name": board_name, "width_mm": round(width, 2),
                           "height_mm": round(height, 2), "parts": raw_parts})


def _title(root: list) -> str:
    block = _child(root, "title_block")
    if block:
        title = _child(block, "title")
        if title and len(title) >= 2:
            return str(title[1])
        rev = _child(block, "rev")
        if rev and len(rev) >= 2:
            return f"KiCad board rev {rev[1]}"
    return ""
