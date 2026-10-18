#!/usr/bin/env python3
"""Convert a real KiCad .kicad_pcb file to circuit-ai-board/1 JSON.

Usage: python tools/convert_kicad.py board.kicad_pcb -o board.board.json --name "My Board"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from boardview.kicad import load_kicad_pcb  # noqa: E402
from boardview.model import board_stats  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--name", default="")
    args = ap.parse_args()
    board = load_kicad_pcb(args.input, name=args.name)
    args.output.write_text(json.dumps(board, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{args.output}: {board_stats(board)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
