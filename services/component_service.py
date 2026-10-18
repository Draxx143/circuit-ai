"""Read/search component records while preserving unknown fields as unknown."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from services.db import db_session, escape_like


def _decode(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    for field in ("specs_json", "recommended_operating_json", "absolute_max_json"):
        item[field.removesuffix("_json")] = json.loads(item.pop(field) or "{}")
    return item


def search_components(query: str = "", *, category: str = "همه", path=None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM components WHERE 1=1"
    params: list[Any] = []
    term = query.strip()
    if term:
        sql += " AND (part_number LIKE ? COLLATE NOCASE ESCAPE '\\' OR manufacturer LIKE ? COLLATE NOCASE ESCAPE '\\' " \
               "OR function_text LIKE ? COLLATE NOCASE ESCAPE '\\' OR common_applications LIKE ? COLLATE NOCASE ESCAPE '\\')"
        params.extend([f"%{escape_like(term)}%"] * 4)
    if category and category != "همه":
        sql += " AND category = ?"
        params.append(category)
    sql += " ORDER BY manufacturer, part_number"
    with db_session(path) as conn:
        return [_decode(row) for row in conn.execute(sql, params).fetchall()]


def get_component(part_number: str, *, path=None) -> dict[str, Any] | None:
    with db_session(path) as conn:
        row = conn.execute(
            "SELECT * FROM components WHERE part_number = ? COLLATE NOCASE", (part_number.strip(),)
        ).fetchone()
        if row is None:
            return None
        result = _decode(row)
        result["pins"] = [dict(pin) for pin in conn.execute(
            """SELECT cp.pin_name,cp.pin_number,cp.function_text,cp.electrical_role,cp.conditions,
                      s.title AS source_title,s.url AS source_url
               FROM component_pins cp LEFT JOIN sources s ON s.id=cp.source_id
               WHERE cp.component_id=? ORDER BY cp.pin_number""", (row["id"],)
        ).fetchall()]
        result["sources"] = [dict(src) for src in conn.execute(
            """SELECT s.* FROM component_datasheets cd JOIN sources s ON s.id=cd.source_id
               WHERE cd.component_id=? ORDER BY s.accessed_on DESC""", (row["id"],)
        ).fetchall()]
        # Include the primary datasheet and other provenance links stored in validation_records.
        linked_sources = conn.execute(
            """SELECT DISTINCT s.* FROM validation_records v JOIN sources s ON s.id=v.source_id
               WHERE v.entity_type='component' AND v.entity_id=? ORDER BY s.accessed_on DESC""",
            (row["id"],),
        ).fetchall()
        for source in linked_sources:
            if all(existing["id"] != source["id"] for existing in result["sources"]):
                result["sources"].append(dict(source))
        primary = conn.execute("SELECT * FROM sources WHERE id=?", (row["source_id"],)).fetchone()
        if primary and all(existing["id"] != primary["id"] for existing in result["sources"]):
            result["sources"].insert(0, dict(primary))
        return result


def get_diagnostic_profile(part_number: str, *, path=None) -> dict[str, Any] | None:
    """Return the data-driven operating-range check profile for an exact catalog part."""
    with db_session(path) as conn:
        row = conn.execute(
            """SELECT p.*,c.part_number,s.title AS source_title,s.publisher,s.url AS source_url,
                      s.document_version,s.status AS source_status
               FROM component_diagnostic_profiles p
               JOIN components c ON c.id=p.component_id
               LEFT JOIN sources s ON s.id=p.source_id
               WHERE c.part_number=? COLLATE NOCASE""", (part_number.strip(),)
        ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["signal_aliases"] = json.loads(item.pop("signal_aliases_json") or "[]")
        return item


def list_categories(*, path=None) -> list[str]:
    with db_session(path) as conn:
        return [r[0] for r in conn.execute(
            "SELECT DISTINCT category FROM components ORDER BY category"
        ).fetchall()]


def create_component(payload: dict[str, Any], *, path=None) -> int:
    """Add a user-supplied part record. It is never silently marked as verified."""
    part = str(payload.get("part_number", "")).strip()
    manufacturer = str(payload.get("manufacturer", "")).strip()
    category = str(payload.get("category", "")).strip()
    if not part or not manufacturer or not category:
        raise ValueError("شماره قطعه، سازنده و دسته‌بندی الزامی است.")
    status = payload.get("validation_status", "needs_review")
    if status not in {"needs_review", "experimental", "lab_tested", "conflicting"}:
        raise ValueError("ثبت قطعه توسط کاربر نمی‌تواند به‌تنهایی وضعیت تأیید رسمی بگیرد.")
    with db_session(path) as conn:
        cur = conn.execute(
            """INSERT INTO components
               (part_number,manufacturer,category,component_type,function_text,common_applications,
                specs_json,recommended_operating_json,absolute_max_json,package,pin_count,
                operating_temperature,datasheet_url,datasheet_section,accessed_on,
                validation_status,last_reviewed,notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (part, manufacturer, category, payload.get("component_type", ""),
             payload.get("function_text", ""), payload.get("common_applications", ""),
             json.dumps(payload.get("specs", {}), ensure_ascii=False),
             json.dumps(payload.get("recommended_operating", {}), ensure_ascii=False),
             json.dumps(payload.get("absolute_max", {}), ensure_ascii=False),
             payload.get("package"), payload.get("pin_count"), payload.get("operating_temperature"),
             payload.get("datasheet_url"), payload.get("datasheet_section"), payload.get("accessed_on"),
             status, payload.get("last_reviewed"), payload.get("notes", "")),
        )
        return int(cur.lastrowid)
