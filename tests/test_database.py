import sqlite3

from pathlib import Path

from services.db import init_db, table_counts, db_session, PROJECT_ROOT
from services.knowledge_service import quality_report
from services.component_service import get_component, get_diagnostic_profile


def test_schema_catalog_seed_and_idempotence(db_path):
    first = table_counts(db_path)
    assert first["components"] == 20
    assert first["sources"] == 21
    assert first["circuit_topologies"] == 3
    assert first["diagnostic_rules"] == 14
    assert first["component_diagnostic_profiles"] == 3
    init_db(db_path)
    second = table_counts(db_path)
    assert second == first
    with db_session(db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {
            "components", "component_datasheets", "component_pins", "circuit_topologies",
            "failure_modes", "diagnostic_rules", "diagnostic_tests", "repair_cases",
            "sources", "validation_records", "component_relationships", "component_diagnostic_profiles",
            "measurements", "repair_tests",
        }
        assert required.issubset(tables)
        profile_indexes = {row[1] for row in conn.execute("PRAGMA index_list(component_diagnostic_profiles)")}
        assert "idx_component_diag_profile_component" in profile_indexes
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_component_reference_links_to_source_and_pin_records(db_path):
    with db_session(db_path) as conn:
        component = conn.execute("SELECT id,source_id,validation_status FROM components WHERE part_number='TPS5430'").fetchone()
        assert component["source_id"] is not None
        assert component["validation_status"] == "official_datasheet_reviewed"
        assert conn.execute("SELECT COUNT(*) FROM component_pins WHERE component_id=?", (component["id"],)).fetchone()[0] >= 5
        assert conn.execute("SELECT COUNT(*) FROM component_datasheets WHERE component_id=?", (component["id"],)).fetchone()[0] == 1


def test_component_diagnostic_profile_is_seeded_with_source_provenance(db_path):
    profile = get_diagnostic_profile("TPS5430", path=db_path)
    assert profile["operating_range_key"] == "input_voltage_v"
    assert "vin" in {alias.casefold() for alias in profile["signal_aliases"]}
    assert profile["pin_description"]
    assert profile["source_status"] == "official_datasheet_reviewed"
    assert profile["validation_status"] == "official_datasheet_reviewed"


def test_quality_report_does_not_claim_lab_testing(db_path):
    report = quality_report(path=db_path)
    # Catalogue v2: 5 datasheet-reviewed parts + 15 needs_review reference records.
    assert report["components"] == 20
    assert report["component_diagnostic_profiles"] == 3
    assert report["diagnostic_profiles_needing_review"] == 0
    assert report["official_component_sources"] == 5
    assert report["component_official_source_percent"] == 25.0
    assert report["lab_tested_components"] == 0
    assert report["component_records_needing_review"] == 15
    assert report["rules"] == 14
    assert report["rules_needing_review"] == 14


def test_nexperia_product_page_is_a_separate_linked_source(db_path):
    component = get_component("1N4148", path=db_path)
    titles = {source["title"] for source in component["sources"]}
    assert "1N4148 (High-speed diodes) product page" in titles
    with db_session(db_path) as conn:
        row = conn.execute("SELECT status FROM sources WHERE source_key='nexperia_1n4148_product_page'").fetchone()
        assert row["status"] == "official_product_page_reviewed"


def test_additive_schema_migration_v1_to_current_adds_input_source_and_profiles(tmp_path):
    old_path = tmp_path / "old.sqlite3"
    old_schema = (PROJECT_ROOT / "database" / "schema.sql").read_text(encoding="utf-8")
    old_schema = old_schema.replace("    expected_input_source TEXT NOT NULL DEFAULT '',\n", "")
    profile_start = old_schema.index("CREATE TABLE IF NOT EXISTS component_diagnostic_profiles (")
    profile_end = old_schema.index("CREATE TABLE IF NOT EXISTS circuit_topologies (", profile_start)
    old_schema = old_schema[:profile_start] + old_schema[profile_end:]
    old_schema = old_schema.replace(
        "CREATE INDEX IF NOT EXISTS idx_component_diag_profile_component ON component_diagnostic_profiles(component_id);\n", ""
    )
    old_schema = old_schema.replace("VALUES ('schema_version', '5');", "VALUES ('schema_version', '1');")
    conn = sqlite3.connect(old_path)
    conn.executescript(old_schema)
    conn.close()
    init_db(old_path, seed=False)
    with db_session(old_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(repair_cases)")}
        assert "expected_input_source" in columns
        version = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0]
        assert version == "5"
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='component_diagnostic_profiles'"
        ).fetchone()
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(component_diagnostic_profiles)")}
        assert "idx_component_diag_profile_component" in indexes


def test_search_terms_treat_like_wildcards_literally(tmp_path):
    """A user typing % or _ must search for those characters, not match everything."""
    from services.component_service import search_components
    from services.repair_service import create_case, list_cases

    db = tmp_path / "wild.sqlite3"
    init_db(db)
    assert search_components("%", path=db) == []
    assert search_components("_", path=db) == []
    create_case({"board_name": "برد 100% تست"}, path=db)
    assert len(list_cases("100%", path=db)) == 1
    assert list_cases("100_", path=db) == []
