"""Queries for the local, provenance-aware knowledge catalogue."""
from __future__ import annotations

import json
from typing import Any

from services.db import db_session, escape_like


def list_sources(query: str = "", *, path=None) -> list[dict[str, Any]]:
    sql = """SELECT s.*,
             (SELECT COUNT(DISTINCT c.id) FROM components c
              WHERE c.source_id=s.id OR EXISTS (
                SELECT 1 FROM validation_records v WHERE v.entity_type='component'
                  AND v.entity_id=c.id AND v.source_id=s.id
              )) AS component_count
             FROM sources s WHERE 1=1"""
    params: list[Any] = []
    if query.strip():
        like = f"%{escape_like(query.strip())}%"
        sql += " AND (s.title LIKE ? COLLATE NOCASE ESCAPE '\\' OR s.publisher LIKE ? COLLATE NOCASE ESCAPE '\\' OR s.url LIKE ? COLLATE NOCASE ESCAPE '\\')"
        params.extend([like, like, like])
    sql += " GROUP BY s.id ORDER BY s.accessed_on DESC, s.publisher, s.title"
    with db_session(path) as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def list_topologies(query: str = "", *, path=None) -> list[dict[str, Any]]:
    sql = """SELECT t.*, s.title AS source_title, s.url AS source_url, s.publisher
             FROM circuit_topologies t LEFT JOIN sources s ON s.id=t.source_id WHERE 1=1"""
    params: list[Any] = []
    if query.strip():
        like = f"%{escape_like(query.strip())}%"
        sql += " AND (t.title LIKE ? COLLATE NOCASE ESCAPE '\\' OR t.category LIKE ? COLLATE NOCASE ESCAPE '\\' OR t.description LIKE ? COLLATE NOCASE ESCAPE '\\')"
        params.extend([like] * 3)
    sql += " ORDER BY t.category,t.title"
    with db_session(path) as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    for row in rows:
        for key in ("failure_modes_json", "measurement_points_json"):
            row[key.removesuffix("_json")] = json.loads(row.pop(key) or "[]")
    return rows


def list_rules(*, path=None) -> list[dict[str, Any]]:
    with db_session(path) as conn:
        rows = [dict(r) for r in conn.execute(
            """SELECT r.*,s.title AS source_title,s.url AS source_url
               FROM diagnostic_rules r LEFT JOIN sources s ON s.id=r.source_id
               ORDER BY r.priority,r.rule_code"""
        ).fetchall()]
    for row in rows:
        for key in ("trigger_symptoms_json", "conditions_json", "action_json"):
            row[key.removesuffix("_json")] = json.loads(row.pop(key) or "{}")
    return rows


def get_test_catalog(*, path=None) -> dict[str, dict[str, Any]]:
    with db_session(path) as conn:
        rows = conn.execute(
            """SELECT t.*,s.title AS source_title,s.url AS source_url
               FROM diagnostic_tests t LEFT JOIN sources s ON s.id=t.source_id"""
        ).fetchall()
    output = {}
    for row in rows:
        item = dict(row)
        for key in ("steps_json", "prerequisites_json", "possible_outcomes_json"):
            item[key.removesuffix("_json")] = json.loads(item.pop(key) or "[]")
        output[item["test_code"]] = item
    return output


def quality_report(*, path=None) -> dict[str, Any]:
    with db_session(path) as conn:
        counts = {
            "components": conn.execute("SELECT COUNT(*) FROM components").fetchone()[0],
            "component_diagnostic_profiles": conn.execute(
                "SELECT COUNT(*) FROM component_diagnostic_profiles"
            ).fetchone()[0],
            "diagnostic_profiles_needing_review": conn.execute(
                "SELECT COUNT(*) FROM component_diagnostic_profiles WHERE validation_status IN ('needs_review','conflicting')"
            ).fetchone()[0],
            "official_component_sources": conn.execute(
                "SELECT COUNT(*) FROM components WHERE validation_status='official_datasheet_reviewed' AND source_id IS NOT NULL"
            ).fetchone()[0],
            "component_records_needing_review": conn.execute(
                "SELECT COUNT(*) FROM components WHERE validation_status IN ('needs_review','conflicting')"
            ).fetchone()[0],
            "components_without_pin_records": conn.execute(
                """SELECT COUNT(*) FROM components c WHERE NOT EXISTS
                   (SELECT 1 FROM component_pins p WHERE p.component_id=c.id)"""
            ).fetchone()[0],
            "components_without_recommended_operating_data": conn.execute(
                "SELECT COUNT(*) FROM components WHERE recommended_operating_json='{}'"
            ).fetchone()[0],
            "component_records_with_intentional_unknowns": conn.execute(
                """SELECT COUNT(*) FROM components c WHERE c.recommended_operating_json='{}' OR NOT EXISTS
                   (SELECT 1 FROM component_pins p WHERE p.component_id=c.id)"""
            ).fetchone()[0],
            "sources": conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
            "official_datasheets_reviewed": conn.execute(
                "SELECT COUNT(*) FROM sources WHERE status='official_datasheet_reviewed'"
            ).fetchone()[0],
            "topologies": conn.execute("SELECT COUNT(*) FROM circuit_topologies").fetchone()[0],
            "failure_modes": conn.execute("SELECT COUNT(*) FROM failure_modes").fetchone()[0],
            "rules": conn.execute("SELECT COUNT(*) FROM diagnostic_rules").fetchone()[0],
            "rules_needing_review": conn.execute(
                "SELECT COUNT(*) FROM diagnostic_rules WHERE validation_status='needs_review'"
            ).fetchone()[0],
            "unverified_cases": conn.execute(
                "SELECT COUNT(*) FROM repair_cases WHERE verification_status='unverified' AND is_archived=0"
            ).fetchone()[0],
            "lab_tested_components": conn.execute(
                "SELECT COUNT(*) FROM components WHERE validation_status='lab_tested'"
            ).fetchone()[0],
        }
        counts["component_official_source_percent"] = (
            round(100.0 * counts["official_component_sources"] / counts["components"], 1)
            if counts["components"] else 0.0
        )
        return counts


def list_failure_modes(symptom_codes=None, *, path=None) -> list[dict[str, Any]]:
    """Documented failure/condition records relevant to the given symptoms."""
    wanted = set(symptom_codes or [])
    with db_session(path) as conn:
        rows = [dict(r) for r in conn.execute(
            """SELECT f.*, s.title AS source_title, s.url AS source_url
               FROM failure_modes f LEFT JOIN sources s ON s.id=f.source_id
               ORDER BY f.failure_code"""
        ).fetchall()]
    output = []
    for row in rows:
        codes = json.loads(row.pop("symptom_codes_json") or "[]")
        row["symptom_codes"] = codes
        row["causes"] = json.loads(row.pop("causes_json") or "[]")
        row["evidence"] = json.loads(row.pop("evidence_json") or "{}")
        if wanted and not (wanted & set(codes)):
            continue
        output.append(row)
    return output
