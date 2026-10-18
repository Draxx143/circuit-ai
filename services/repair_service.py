"""Repair case lifecycle, measurements, test outcomes and lexical case retrieval."""
from __future__ import annotations

import json
import math
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from services.db import db_session, escape_like

SYMPTOM_LABELS = {
    "no_power": "روشن نمی‌شود",
    "resets": "ریست/خاموش‌روشن‌شدن مداوم",
    "no_output": "خروجی ندارد",
    "wrong_voltage": "ولتاژ نادرست/افت/نوسان",
    "short_reported": "اتصال کوتاه گزارش شده",
    "no_communication": "ارتباط برقرار نمی‌شود",
    "digital_io": "ورودی/خروجی دیجیتال مشکل دارد",
    "motor_driver_fault": "مشکل در درایور موتور",
    "other": "سایر",
}
VALID_SYMPTOMS = set(SYMPTOM_LABELS)
VALID_MEASUREMENT_STATES = {"power_off", "powered", "unknown"}
VALID_TEST_RESULTS = {"supports", "contradicts", "inconclusive", "not_performed"}


class CaseNotFoundError(LookupError):
    pass


def _case_number() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"CA-{stamp}-{uuid.uuid4().hex[:8].upper()}"


def _finite(value: Any, label: str, *, optional: bool = False) -> float | None:
    if optional and (value is None or value == ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} باید عددی باشد.") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} باید عدد محدود باشد (NaN/بی‌نهایت پذیرفته نیست).")
    return number


def _decode_case(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["symptoms"] = json.loads(item.pop("symptoms_json") or "[]")
    item["diagnosis"] = json.loads(item.pop("diagnosis_json") or "{}")
    return item


def create_case(payload: dict[str, Any], *, path=None) -> dict[str, Any]:
    board_name = str(payload.get("board_name", "")).strip()
    if not board_name:
        raise ValueError("نام برد الزامی است.")
    symptoms = payload.get("symptoms", [])
    if not isinstance(symptoms, list) or any(code not in VALID_SYMPTOMS for code in symptoms):
        raise ValueError("کد علامت خرابی معتبر نیست.")
    expected = _finite(payload.get("expected_input_voltage"), "ولتاژ ورودی مورد انتظار", optional=True)
    with db_session(path) as conn:
        cursor = conn.execute(
            """INSERT INTO repair_cases
               (case_number,board_name,board_manufacturer,board_model,application,
                expected_input_voltage,expected_input_unit,expected_input_source,reference_component,fault_description,
                symptoms_json,submitted_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (_case_number(), board_name, str(payload.get("board_manufacturer", "")).strip(),
             str(payload.get("board_model", "")).strip(), str(payload.get("application", "")).strip(),
             expected, str(payload.get("expected_input_unit", "V")),
             str(payload.get("expected_input_source", "")).strip(),
             str(payload.get("reference_component", "")).strip(),
             str(payload.get("fault_description", "")).strip(),
             json.dumps(symptoms, ensure_ascii=False), str(payload.get("submitted_by", "")).strip()),
        )
        case_id = int(cursor.lastrowid)
    result = get_case(case_id, path=path)
    assert result is not None
    return result


_CASE_UPDATE_FIELDS = {
    "board_name", "board_manufacturer", "board_model", "application",
    "expected_input_voltage", "expected_input_unit", "expected_input_source", "reference_component",
    "fault_description", "submitted_by",
}


def update_case(case_id: int, changes: dict[str, Any], *, path=None) -> dict[str, Any]:
    updates = {k: v for k, v in changes.items() if k in _CASE_UPDATE_FIELDS}
    if "symptoms" in changes:
        symptoms = changes["symptoms"]
        if not isinstance(symptoms, list) or any(code not in VALID_SYMPTOMS for code in symptoms):
            raise ValueError("کد علامت خرابی معتبر نیست.")
        updates["symptoms_json"] = json.dumps(symptoms, ensure_ascii=False)
    if "expected_input_voltage" in updates:
        updates["expected_input_voltage"] = _finite(
            updates["expected_input_voltage"], "ولتاژ ورودی مورد انتظار", optional=True
        )
    if "board_name" in updates:
        updates["board_name"] = str(updates["board_name"]).strip()
        if not updates["board_name"]:
            raise ValueError("نام برد نمی‌تواند خالی باشد.")
    if not updates:
        return get_case(case_id, path=path) or _raise_not_found(case_id)
    assignments = ",".join(f"{column}=?" for column in updates)
    values = list(updates.values()) + [case_id]
    with db_session(path) as conn:
        cursor = conn.execute(
            f"UPDATE repair_cases SET {assignments}, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? AND is_archived=0",
            values,
        )
        if cursor.rowcount == 0:
            raise CaseNotFoundError(f"پرونده {case_id} پیدا نشد یا بایگانی شده است.")
    result = get_case(case_id, path=path)
    assert result is not None
    return result


def _raise_not_found(case_id: int):
    raise CaseNotFoundError(f"پرونده {case_id} پیدا نشد.")


def get_case(case_id: int, *, path=None) -> dict[str, Any] | None:
    with db_session(path) as conn:
        row = conn.execute("SELECT * FROM repair_cases WHERE id=?", (int(case_id),)).fetchone()
        if row is None:
            return None
        item = _decode_case(row)
        item["measurements"] = [dict(r) for r in conn.execute(
            "SELECT * FROM measurements WHERE case_id=? ORDER BY created_at,id", (int(case_id),)
        ).fetchall()]
        item["tests"] = [dict(r) for r in conn.execute(
            "SELECT * FROM repair_tests WHERE case_id=? ORDER BY tested_at,id", (int(case_id),)
        ).fetchall()]
        return item


def list_cases(query: str = "", *, include_archived: bool = False, path=None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM repair_cases WHERE 1=1"
    params: list[Any] = []
    if not include_archived:
        sql += " AND is_archived=0"
    if query.strip():
        like = f"%{escape_like(query.strip())}%"
        sql += " AND (case_number LIKE ? COLLATE NOCASE ESCAPE '\\' OR board_name LIKE ? COLLATE NOCASE ESCAPE '\\' " \
               "OR board_manufacturer LIKE ? COLLATE NOCASE ESCAPE '\\' OR board_model LIKE ? COLLATE NOCASE ESCAPE '\\' " \
               "OR application LIKE ? COLLATE NOCASE ESCAPE '\\' OR fault_description LIKE ? COLLATE NOCASE ESCAPE '\\' " \
               "OR confirmed_cause LIKE ? COLLATE NOCASE ESCAPE '\\')"
        params.extend([like] * 7)
    sql += " ORDER BY created_at DESC,id DESC"
    with db_session(path) as conn:
        return [_decode_case(row) for row in conn.execute(sql, params).fetchall()]


def recent_cases(limit: int = 8, *, path=None) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 100))
    with db_session(path) as conn:
        return [_decode_case(row) for row in conn.execute(
            "SELECT * FROM repair_cases WHERE is_archived=0 ORDER BY created_at DESC,id DESC LIMIT ?",
            (limit,),
        ).fetchall()]


def add_measurement(case_id: int, payload: dict[str, Any], *, path=None) -> int:
    signal = str(payload.get("signal", "")).strip()
    unit = str(payload.get("unit", "")).strip()
    if not signal or not unit:
        raise ValueError("نام سیگنال و واحد الزامی است.")
    measured = _finite(payload.get("measured_value"), "مقدار اندازه‌گیری‌شده")
    expected = _finite(payload.get("expected_value"), "مقدار مورد انتظار", optional=True)
    tolerance = _finite(payload.get("tolerance_percent"), "تلرانس درصدی", optional=True)
    if tolerance is not None and tolerance < 0:
        raise ValueError("تلرانس نمی‌تواند منفی باشد.")
    state = str(payload.get("measurement_state", "unknown"))
    if state not in VALID_MEASUREMENT_STATES:
        raise ValueError("وضعیت اندازه‌گیری معتبر نیست.")
    with db_session(path) as conn:
        exists = conn.execute("SELECT 1 FROM repair_cases WHERE id=? AND is_archived=0", (case_id,)).fetchone()
        if not exists:
            raise CaseNotFoundError(f"پرونده {case_id} پیدا نشد یا بایگانی شده است.")
        cursor = conn.execute(
            """INSERT INTO measurements
               (case_id,signal,measured_value,unit,conditions,expected_value,tolerance_percent,
                expected_source,measurement_state)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (case_id, signal, measured, unit, str(payload.get("conditions", "")).strip(), expected,
             tolerance, str(payload.get("expected_source", "")).strip(), state),
        )
        conn.execute(
            "UPDATE repair_cases SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
            (case_id,),
        )
        return int(cursor.lastrowid)


def delete_measurement(measurement_id: int, *, path=None) -> None:
    """Delete one measurement only; UI must explicitly confirm before calling."""
    with db_session(path) as conn:
        conn.execute("DELETE FROM measurements WHERE id=?", (measurement_id,))


def record_test_result(case_id: int, payload: dict[str, Any], *, path=None) -> int:
    code = str(payload.get("test_code", "")).strip()
    title = str(payload.get("test_title", "")).strip()
    result = str(payload.get("result", "")).strip()
    if not code or not title or result not in VALID_TEST_RESULTS:
        raise ValueError("آزمایش، عنوان و نتیجه معتبر الزامی است.")
    with db_session(path) as conn:
        if not conn.execute("SELECT 1 FROM repair_cases WHERE id=? AND is_archived=0", (case_id,)).fetchone():
            raise CaseNotFoundError(f"پرونده {case_id} پیدا نشد یا بایگانی شده است.")
        cursor = conn.execute(
            """INSERT INTO repair_tests(case_id,test_code,test_title,result,notes,test_details_json,source_id)
               VALUES (?,?,?,?,?,?,?)""",
            (case_id, code, title, result, str(payload.get("notes", "")).strip(),
             json.dumps(payload.get("details", {}), ensure_ascii=False), payload.get("source_id")),
        )
        conn.execute("UPDATE repair_cases SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (case_id,))
        return int(cursor.lastrowid)


def save_diagnosis(case_id: int, diagnosis: dict[str, Any], *, path=None) -> None:
    with db_session(path) as conn:
        cursor = conn.execute(
            """UPDATE repair_cases SET diagnosis_json=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
               WHERE id=? AND is_archived=0""",
            (json.dumps(diagnosis, ensure_ascii=False), case_id),
        )
        if cursor.rowcount == 0:
            raise CaseNotFoundError(f"پرونده {case_id} پیدا نشد یا بایگانی شده است.")


def close_case(case_id: int, *, confirmed_cause: str = "", repaired_component: str = "",
               final_outcome: str, verified: bool = False, reviewer: str = "",
               evidence: str = "", path=None) -> None:
    outcome = str(final_outcome).strip()
    if not outcome:
        raise ValueError("برای بستن پرونده، نتیجه نهایی تعمیر الزامی است.")
    if verified and (not reviewer.strip() or not evidence.strip()):
        raise ValueError("پرونده تأییدشده باید بازبین و شواهد تأیید ثبت‌شده داشته باشد.")
    verified_status = "verified" if verified else "unverified"
    with db_session(path) as conn:
        cursor = conn.execute(
            """UPDATE repair_cases SET status='completed',verification_status=?,confirmed_cause=?,
               repaired_component=?,final_outcome=?,closed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),
               updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? AND is_archived=0""",
            (verified_status, str(confirmed_cause).strip(), str(repaired_component).strip(), outcome, case_id),
        )
        if cursor.rowcount == 0:
            raise CaseNotFoundError(f"پرونده {case_id} پیدا نشد یا بایگانی شده است.")
        if verified:
            conn.execute(
                """INSERT INTO validation_records(entity_type,entity_id,status,evidence,reviewer)
                   VALUES ('repair_case',?,'verified',?,?)""",
                (case_id, evidence.strip(), reviewer.strip()),
            )


def reopen_case(case_id: int, *, path=None) -> None:
    with db_session(path) as conn:
        cursor = conn.execute(
            """UPDATE repair_cases SET status='open',closed_at=NULL,
               updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? AND is_archived=0""",
            (case_id,),
        )
        if cursor.rowcount == 0:
            raise CaseNotFoundError(f"پرونده {case_id} پیدا نشد یا بایگانی شده است.")


def archive_case(case_id: int, *, path=None) -> None:
    with db_session(path) as conn:
        cursor = conn.execute(
            "UPDATE repair_cases SET is_archived=1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? AND is_archived=0",
            (case_id,),
        )
        if cursor.rowcount == 0:
            raise CaseNotFoundError(f"پرونده {case_id} پیدا نشد یا قبلاً بایگانی شده است.")


def find_similar_cases(case: dict[str, Any], *, limit: int = 5, path=None) -> list[dict[str, Any]]:
    """Lexical/symptom similarity only; returned scores are not fault probabilities."""
    candidates = list_cases(path=path)
    query_terms = _terms(" ".join([
        str(case.get("board_name", "")), str(case.get("board_model", "")),
        str(case.get("application", "")), str(case.get("fault_description", "")),
    ]))
    query_symptoms = set(case.get("symptoms", []))
    query_model = str(case.get("board_model", "")).strip().casefold()
    scored: list[dict[str, Any]] = []
    for candidate in candidates:
        if int(candidate.get("id", -1)) == int(case.get("id", -2)):
            continue
        terms = _terms(" ".join([
            str(candidate.get("board_name", "")), str(candidate.get("board_model", "")),
            str(candidate.get("application", "")), str(candidate.get("fault_description", "")),
        ]))
        symptoms = set(candidate.get("symptoms", []))
        shared_symptoms = query_symptoms & symptoms
        union = query_symptoms | symptoms
        symptom_similarity = len(shared_symptoms) / len(union) if union else 0.0
        shared_terms = query_terms & terms
        union_terms = query_terms | terms
        text_similarity = len(shared_terms) / len(union_terms) if union_terms else 0.0
        same_model = bool(query_model and query_model == str(candidate.get("board_model", "")).strip().casefold())
        # Transparent retrieval heuristic; not a diagnostic score or probability.
        score = 0.65 * symptom_similarity + 0.25 * text_similarity + (0.10 if same_model else 0.0)
        if score <= 0 and not shared_symptoms and not shared_terms:
            continue
        differences = []
        if not same_model:
            differences.append("مدل برد متفاوت یا ثبت‌نشده است")
        if query_symptoms != symptoms:
            differences.append("مجموعه علائم متفاوت است")
        if not shared_terms:
            differences.append("واژه مشترک در شرح خرابی پیدا نشد")
        scored.append({
            **candidate,
            "similarity_score": round(score, 4),
            "shared_symptoms": sorted(shared_symptoms),
            "shared_terms": sorted(shared_terms),
            "similarities": (["علائم مشترک: " + ", ".join(SYMPTOM_LABELS.get(x, x) for x in sorted(shared_symptoms))]
                             if shared_symptoms else []) + (["مدل برد یکسان"] if same_model else []),
            "differences": differences,
            "knowledge_warning": "شباهت پرونده، دلیل خرابی یا تشخیص را اثبات نمی‌کند.",
        })
    return sorted(scored, key=lambda x: (x["similarity_score"], x["created_at"]), reverse=True)[:max(1, limit)]


def _terms(text: str) -> set[str]:
    words = re.findall(r"[A-Za-z0-9_]+|[\u0600-\u06FF]+", text.casefold())
    stop = {"و", "در", "از", "با", "برای", "روی", "به", "the", "and", "or", "board", "برد"}
    return {word for word in words if len(word) > 1 and word not in stop}
