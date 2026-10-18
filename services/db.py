"""SQLite path, connection, schema setup and idempotent catalogue seeding."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "database" / "schema.sql"
CURRENT_SCHEMA_VERSION = 5
SEED_PATH = PROJECT_ROOT / "data" / "seed_catalog.json"


class DatabaseError(RuntimeError):
    """Raised when the local database cannot be safely initialized or used."""


def database_path() -> Path:
    """Return an XDG-compliant per-user location, unless explicitly overridden."""
    override = os.environ.get("CIRCUIT_AI_DB_PATH")
    if override:
        return Path(override).expanduser().resolve()
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return (data_home / "circuit-ai" / "circuit_ai.sqlite3").expanduser().resolve()


def connect_db(path: str | Path | None = None) -> sqlite3.Connection:
    db_path = Path(path).expanduser().resolve() if path else database_path()
    if str(db_path) != ":memory:":
        db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    conn = sqlite3.connect(str(db_path), timeout=15, isolation_level="DEFERRED")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    # Streamlit reruns / multiple browser tabs open several connections to the
    # same file; WAL avoids most "database is locked" failures.
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    except sqlite3.Error:
        pass  # :memory: and read-only files keep their default journal mode
    return conn


def escape_like(term: str) -> str:
    """Escape a user search term for use in ``LIKE ... ESCAPE '\\'`` patterns."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@contextmanager
def db_session(path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect_db(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _seed_catalog(conn: sqlite3.Connection, seed_path: Path = SEED_PATH) -> None:
    if not seed_path.exists():
        raise DatabaseError(f"Seed data file not found: {seed_path}")
    data = json.loads(seed_path.read_text(encoding="utf-8"))

    for source in data.get("sources", []):
        conn.execute(
            """INSERT INTO sources
               (source_key,title,publisher,document_type,url,document_version,accessed_on,status,notes)
               VALUES (:source_key,:title,:publisher,:document_type,:url,:document_version,:accessed_on,:status,:notes)
               ON CONFLICT(source_key) DO UPDATE SET
                 title=excluded.title, publisher=excluded.publisher,
                 document_type=excluded.document_type, url=excluded.url,
                 document_version=excluded.document_version, accessed_on=excluded.accessed_on,
                 status=excluded.status, notes=excluded.notes""",
            source,
        )

    source_ids = {
        row["source_key"]: row["id"]
        for row in conn.execute("SELECT id, source_key FROM sources").fetchall()
    }
    component_ids: dict[str, int] = {}
    component_fields = (
        "part_number manufacturer category component_type function_text common_applications "
        "specs_json recommended_operating_json absolute_max_json package pin_count "
        "operating_temperature datasheet_url datasheet_section source_id accessed_on "
        "validation_status last_reviewed notes"
    ).split()
    placeholders = ",".join(f":{name}" for name in component_fields)
    updates = ",".join(f"{name}=excluded.{name}" for name in component_fields if name != "part_number")
    for component in data.get("components", []):
        values = {
            **component,
            "specs_json": _json(component.get("specs", {})),
            "recommended_operating_json": _json(component.get("recommended_operating", {})),
            "absolute_max_json": _json(component.get("absolute_max", {})),
            "source_id": source_ids.get(component.get("source_key")),
            "accessed_on": component.get("last_reviewed", data.get("accessed_on")),
        }
        values = {key: values.get(key) for key in component_fields}
        conn.execute(
            f"""INSERT INTO components ({','.join(component_fields)}) VALUES ({placeholders})
                ON CONFLICT(part_number) DO UPDATE SET {updates},
                updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')""",
            values,
        )
        row = conn.execute(
            "SELECT id FROM components WHERE part_number = ? COLLATE NOCASE",
            (component["part_number"],),
        ).fetchone()
        component_id = int(row["id"])
        component_ids[component["part_number"].upper()] = component_id
        source_id = source_ids.get(component.get("source_key"))
        if source_id is not None:
            source = conn.execute("SELECT document_version FROM sources WHERE id=?", (source_id,)).fetchone()
            conn.execute(
                """INSERT INTO component_datasheets(component_id,source_id,page_or_section,revision,notes)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(component_id,source_id) DO UPDATE SET
                     page_or_section=excluded.page_or_section,revision=excluded.revision,notes=excluded.notes""",
                (component_id, source_id, component.get("datasheet_section", ""),
                 source["document_version"] if source else None,
                 "بازبینی مستندات رسمی؛ آزمایش عملی انجام نشده است."),
            )
            evidence = "رکورد قطعه با مشخصات درج‌شده از منبع رسمی متصل شده؛ این تأیید مستندی است، نه آزمایشگاهی."
            exists = conn.execute(
                """SELECT 1 FROM validation_records WHERE entity_type='component' AND entity_id=?
                   AND status=? AND source_id=? AND evidence=? LIMIT 1""",
                (component_id, component.get("validation_status", "needs_review"), source_id, evidence),
            ).fetchone()
            if not exists:
                conn.execute(
                    """INSERT INTO validation_records(entity_type,entity_id,status,evidence,reviewer,source_id)
                       VALUES ('component',?,?,?,?,?)""",
                    (component_id, component.get("validation_status", "needs_review"), evidence,
                     "initial datasheet review", source_id),
                )

    link_path = PROJECT_ROOT / "data" / "sources" / "component_source_links.json"
    if link_path.exists():
        link_data = json.loads(link_path.read_text(encoding="utf-8"))
        for link in link_data.get("links", []):
            component_id = component_ids.get(link["part_number"].upper())
            source_id = source_ids.get(link.get("source_key"))
            if component_id is None or source_id is None:
                raise DatabaseError(f"Component source link is unresolved: {link}")
            exists = conn.execute(
                """SELECT 1 FROM validation_records WHERE entity_type='component' AND entity_id=?
                   AND status=? AND source_id=? AND evidence=? LIMIT 1""",
                (component_id, link["status"], source_id, link["evidence"]),
            ).fetchone()
            if not exists:
                conn.execute(
                    """INSERT INTO validation_records(entity_type,entity_id,status,evidence,reviewer,source_id)
                       VALUES ('component',?,?,?,?,?)""",
                    (component_id, link["status"], link["evidence"], "initial official product page review", source_id),
                )

    for pin in data.get("pins", []):
        component_id = component_ids.get(pin["part_number"].upper())
        if component_id is None:
            raise DatabaseError(f"Pin references unknown part: {pin['part_number']}")
        source_id = source_ids.get(pin.get("source_key"))
        conn.execute(
            """INSERT INTO component_pins
               (component_id,pin_name,pin_number,function_text,electrical_role,conditions,source_id)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(component_id,pin_number,pin_name) DO UPDATE SET
                 function_text=excluded.function_text, electrical_role=excluded.electrical_role,
                 conditions=excluded.conditions, source_id=excluded.source_id""",
            (component_id, pin["pin_name"], pin["pin_number"], pin["function_text"],
             pin.get("electrical_role"), pin.get("conditions", ""), source_id),
        )

    profiles_path = PROJECT_ROOT / "data" / "diagnostic_rules" / "component_ranges.json"
    if profiles_path.exists():
        profile_data = json.loads(profiles_path.read_text(encoding="utf-8"))
        for profile in profile_data.get("profiles", []):
            component_id = component_ids.get(profile["part_number"].upper())
            source_id = source_ids.get(profile.get("source_key"))
            if component_id is None or source_id is None:
                raise DatabaseError(f"Component diagnostic profile is unresolved: {profile}")
            conn.execute(
                """INSERT INTO component_diagnostic_profiles
                   (profile_code,component_id,operating_range_key,signal_aliases_json,pin_description,
                    measurement_unit,description,source_id,validation_status,notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(profile_code) DO UPDATE SET
                     component_id=excluded.component_id,operating_range_key=excluded.operating_range_key,
                     signal_aliases_json=excluded.signal_aliases_json,pin_description=excluded.pin_description,
                     measurement_unit=excluded.measurement_unit,description=excluded.description,
                     source_id=excluded.source_id,validation_status=excluded.validation_status,notes=excluded.notes""",
                (profile["profile_code"], component_id, profile["operating_range_key"],
                 _json(profile.get("signal_aliases", [])), profile.get("pin_description", ""),
                 profile.get("measurement_unit", "V"), profile.get("description", ""), source_id,
                 profile["validation_status"], profile.get("notes", "")),
            )

    for topology in data.get("topologies", []):
        conn.execute(
            """INSERT INTO circuit_topologies
               (topology_code,title,category,description,expected_behavior,failure_modes_json,
                measurement_points_json,diagnostic_limits,source_id,validation_status,last_reviewed)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(topology_code) DO UPDATE SET
                 title=excluded.title, category=excluded.category, description=excluded.description,
                 expected_behavior=excluded.expected_behavior, failure_modes_json=excluded.failure_modes_json,
                 measurement_points_json=excluded.measurement_points_json,
                 diagnostic_limits=excluded.diagnostic_limits, source_id=excluded.source_id,
                 validation_status=excluded.validation_status, last_reviewed=excluded.last_reviewed""",
            (topology["topology_code"], topology["title"], topology["category"],
             topology["description"], topology.get("expected_behavior", ""),
             _json(topology.get("failure_modes", [])), _json(topology.get("measurement_points", [])),
             topology.get("diagnostic_limits", ""), source_ids.get(topology.get("source_key")),
             topology["validation_status"], data.get("accessed_on")),
        )

    for failure in data.get("failure_modes", []):
        conn.execute(
            """INSERT INTO failure_modes
               (failure_code,title,failure_type,summary,symptom_codes_json,causes_json,evidence_json,
                limitations,source_id,validation_status)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(failure_code) DO UPDATE SET
                 title=excluded.title, failure_type=excluded.failure_type, summary=excluded.summary,
                 symptom_codes_json=excluded.symptom_codes_json, causes_json=excluded.causes_json,
                 evidence_json=excluded.evidence_json, limitations=excluded.limitations,
                 source_id=excluded.source_id, validation_status=excluded.validation_status""",
            (failure["failure_code"], failure["title"], failure.get("failure_type", "hypothesis"),
             failure["summary"], _json(failure.get("symptom_codes", [])),
             _json(failure.get("causes", [])), _json(failure.get("evidence", {})),
             failure.get("limitations", ""), source_ids.get(failure.get("source_key")),
             failure["validation_status"]),
        )

    for test in data.get("tests", []):
        conn.execute(
            """INSERT INTO diagnostic_tests
               (test_code,title,purpose,steps_json,measurement_state,risk_level,prerequisites_json,
                possible_outcomes_json,limitations,source_id,validation_status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(test_code) DO UPDATE SET
                 title=excluded.title,purpose=excluded.purpose,steps_json=excluded.steps_json,
                 measurement_state=excluded.measurement_state,risk_level=excluded.risk_level,
                 prerequisites_json=excluded.prerequisites_json,
                 possible_outcomes_json=excluded.possible_outcomes_json,
                 limitations=excluded.limitations,source_id=excluded.source_id,
                 validation_status=excluded.validation_status""",
            (test["test_code"], test["title"], test["purpose"], _json(test.get("steps", [])),
             test["measurement_state"], test["risk_level"], _json(test.get("prerequisites", [])),
             _json(test.get("possible_outcomes", [])), test.get("limitations", ""),
             source_ids.get(test.get("source_key")), test["validation_status"]),
        )

    rules_path = PROJECT_ROOT / "data" / "diagnostic_rules" / "rules.json"
    rule_data = json.loads(rules_path.read_text(encoding="utf-8")) if rules_path.exists() else data
    for rule in rule_data.get("rules", []):
        conn.execute(
            """INSERT INTO diagnostic_rules
               (rule_code,title,category,enabled,priority,trigger_symptoms_json,conditions_json,
                action_json,explanation,source_id,validation_status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(rule_code) DO UPDATE SET
                 title=excluded.title,category=excluded.category,enabled=excluded.enabled,
                 priority=excluded.priority,trigger_symptoms_json=excluded.trigger_symptoms_json,
                 conditions_json=excluded.conditions_json,action_json=excluded.action_json,
                 explanation=excluded.explanation,source_id=excluded.source_id,
                 validation_status=excluded.validation_status,
                 updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')""",
            (rule["rule_code"], rule["title"], rule["category"], int(rule["enabled"]),
             rule["priority"], _json(rule.get("trigger_symptoms", [])),
             _json(rule.get("conditions", {})), _json(rule.get("action", {})),
             rule.get("explanation", ""), source_ids.get(rule.get("source_key")),
             rule["validation_status"]),
        )

    conn.execute(
        "INSERT INTO app_settings(setting_key,setting_value) VALUES('catalog_seed_version','1') "
        "ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value, "
        "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')"
    )


# Columns introduced after the first schema; added additively, never dropped.
_ADDED_COLUMNS = {
    "repair_cases": {
        "expected_input_source": "TEXT NOT NULL DEFAULT ''",
        "expected_input_voltage": "REAL",
        "expected_input_unit": "TEXT NOT NULL DEFAULT 'V'",
        "diagnosis_json": "TEXT NOT NULL DEFAULT '{}'",
        "is_archived": "INTEGER NOT NULL DEFAULT 0",
    },
}


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Apply additive, non-destructive migrations to databases from earlier builds."""
    for table, columns in _ADDED_COLUMNS.items():
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if not existing:
            continue  # fresh DB: schema.sql already created the table completely
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
    conn.execute("DROP INDEX IF EXISTS idx_component_profiles_component")
    conn.execute(
        "INSERT INTO schema_meta(key,value) VALUES('schema_version',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(CURRENT_SCHEMA_VERSION),),
    )


def init_db(path: str | Path | None = None, *, seed: bool = True) -> Path:
    """Create schema and seed catalogue data, without deleting or resetting repair records."""
    target = Path(path).expanduser().resolve() if path else database_path()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        conn = sqlite3.connect(str(target), timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        _migrate_schema(conn)
        if seed:
            _seed_catalog(conn)
        conn.commit()
        check = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            raise DatabaseError(f"SQLite integrity check failed: {check}")
        conn.close()
        if os.name == "posix":
            target.chmod(0o600)
        return target
    except (sqlite3.Error, OSError, json.JSONDecodeError) as exc:
        try:
            conn.close()  # type: ignore[possibly-undefined]
        except Exception:
            pass
        raise DatabaseError(f"Database initialization failed: {exc}") from exc


def table_counts(path: str | Path | None = None) -> dict[str, int]:
    tables = [
        "repair_cases", "components", "diagnostic_rules", "sources", "circuit_topologies",
        "failure_modes", "diagnostic_tests", "component_pins", "component_diagnostic_profiles",
        "validation_records",
    ]
    with db_session(path) as conn:
        return {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in tables
        }
