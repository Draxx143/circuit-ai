from tools.source_intake import audit_manifest, import_approved_records, normalized_part, official_url
from services.component_service import get_component
from services.db import db_session


def test_manifest_audit_deduplicates_and_never_auto_approves():
    result = audit_manifest({"components": [
        {"part_number": "TPS-5430", "manufacturer": "TI", "category": "Power", "datasheet_url": "https://www.ti.com/doc.pdf", "human_approved": True},
        {"part_number": "TPS5430", "manufacturer": "TI", "category": "Power", "datasheet_url": "https://www.ti.com/doc.pdf"},
        {"part_number": "bad", "manufacturer": "x", "category": "y", "datasheet_url": "http://example.org/a.pdf"},
    ]})
    assert result["total_records"] == 3
    assert result["unique_part_numbers"] == 2
    assert all(item["validation_status"] == "needs_review" for item in result["review_queue"])
    assert all(item["imported_automatically"] is False for item in result["review_queue"])
    assert any("تکراری" in issue["issue"] for issue in result["issues"])
    assert any("خارج از HTTPS" in issue["issue"] for issue in result["issues"])


def test_official_url_allowlist_and_normalization():
    assert official_url("https://www.ti.com/lit/ds/foo.pdf")
    assert official_url("http://www.ti.com/foo.pdf") is False
    assert official_url("https://example.org/foo.pdf") is False
    assert normalized_part("tps-5430") == "TPS5430"


def test_import_requires_explicit_human_approval(db_path):
    unapproved = {"components": [{
        "part_number": "CANDIDATE-1", "manufacturer": "TI", "category": "Power",
        "datasheet_url": "https://www.ti.com/ds.pdf", "validation_status": "official_datasheet_reviewed",
    }]}
    result = import_approved_records(unapproved, db_path=db_path)
    assert result["imported"] == []
    assert "human_approved" in result["skipped"][0]["reason"]


def test_import_records_human_review_provenance(db_path):
    approved = {"components": [{
        "part_number": "EXAMPLE123", "manufacturer": "Texas Instruments", "category": "Power",
        "component_type": "test record", "function_text": "verified description",
        "datasheet_url": "https://www.ti.com/lit/ds/example.pdf", "source_title": "Example official datasheet",
        "document_version": "Rev A", "reviewed_sections": "Sections 1 and 4",
        "manual_verification_note": "Values cross-checked against the official table.", "reviewer": "reviewer-1",
        "human_approved": True, "validation_status": "official_datasheet_reviewed",
        "recommended_operating": {"vin_v": {"min": 1, "max": 5}}, "absolute_max": {}, "specs": {},
    }]}
    result = import_approved_records(approved, db_path=db_path)
    assert result["imported"] == ["EXAMPLE123"]
    part = get_component("EXAMPLE123", path=db_path)
    assert part["validation_status"] == "official_datasheet_reviewed"
    assert part["sources"][0]["publisher"] == "Texas Instruments"
    with db_session(db_path) as conn:
        row = conn.execute("SELECT reviewer,evidence FROM validation_records WHERE entity_type='component' AND entity_id=?", (part["id"],)).fetchone()
        assert row["reviewer"] == "reviewer-1"
        assert "Sections 1 and 4" in row["evidence"]
