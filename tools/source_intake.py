#!/usr/bin/env python3
"""Explicit, allowlisted source intake. No web crawling or automatic fact approval.

Input manifest example:
{"components":[{"part_number":"TPS5430","manufacturer":"Texas Instruments",
"category":"DC-DC","datasheet_url":"https://www.ti.com/lit/ds/symlink/tps5430.pdf"}]}
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_HOSTS = {
    "ti.com", "www.ti.com", "st.com", "www.st.com", "infineon.com", "www.infineon.com",
    "nexperia.com", "www.nexperia.com", "assets.nexperia.com", "onsemi.com", "www.onsemi.com",
    "microchip.com", "www.microchip.com", "analog.com", "www.analog.com", "mps.com", "www.monolithicpower.com",
    "toshiba.semicon-storage.com", "www.toshiba.semicon-storage.com",
}
MAX_BYTES = 25 * 1024 * 1024


def normalized_part(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", str(value).upper())


def official_url(value: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(value)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (host in ALLOWED_HOSTS or any(host.endswith("." + x) for x in ALLOWED_HOSTS))


def audit_manifest(data: dict[str, Any]) -> dict[str, Any]:
    records = data.get("components", [])
    issues: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    queue = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            issues.append({"index": index, "issue": "رکورد باید شیء JSON باشد"})
            continue
        part = str(record.get("part_number", "")).strip()
        key = normalized_part(part)
        if not part:
            issues.append({"index": index, "issue": "شماره قطعه خالی است"})
        elif key in seen:
            issues.append({"index": index, "issue": f"شماره قطعه تکراری با رکورد {seen[key] + 1}: {part}"})
        else:
            seen[key] = index
        missing = [field for field in ("manufacturer", "category", "datasheet_url") if not str(record.get(field, "")).strip()]
        if missing:
            issues.append({"index": index, "part_number": part, "issue": "فیلدهای لازم ناقص: " + ", ".join(missing)})
        url = str(record.get("datasheet_url", ""))
        if url and not official_url(url):
            issues.append({"index": index, "part_number": part, "issue": "URL خارج از HTTPS/فهرست ناشرهای مجاز؛ دانلود/ورود مجاز نیست"})
        queued = dict(record)
        queued["validation_status"] = "needs_review"
        queued["imported_automatically"] = False
        queued["review_required"] = True
        queue.append(queued)
    return {
        "generated_on": date.today().isoformat(),
        "total_records": len(records),
        "unique_part_numbers": len(seen),
        "issues": issues,
        "review_queue": queue,
        "policy": "اسکریپت جست‌وجوی وب انجام نمی‌دهد، صفحات را crawl نمی‌کند و هیچ مشخصه‌ای را تأیید نمی‌کند. فقط URLهای HTTPS رسمی که کاربر صریحاً در manifest داده است بررسی می‌شوند.",
    }


def import_approved_records(data: dict[str, Any], *, db_path: Path) -> dict[str, Any]:
    """Import only explicitly human-approved official datasheet records; never auto-approve extraction."""
    from services.db import db_session, init_db

    init_db(db_path)
    imported: list[str] = []
    skipped: list[dict[str, str]] = []
    with db_session(db_path) as conn:
        for record in data.get("components", []):
            part = str(record.get("part_number", "")).strip()
            reviewer = str(record.get("reviewer", "")).strip()
            note = str(record.get("manual_verification_note", "")).strip()
            sections = str(record.get("reviewed_sections", "")).strip()
            url = str(record.get("datasheet_url", "")).strip()
            if not record.get("human_approved"):
                skipped.append({"part_number": part, "reason": "human_approved=true ثبت نشده"})
                continue
            if not (part and reviewer and note and sections):
                skipped.append({"part_number": part, "reason": "شماره قطعه/بازبین/یادداشت بررسی/بخش‌های بررسی‌شده ناقص است"})
                continue
            if not official_url(url) or not urllib.parse.urlparse(url).path.lower().endswith(".pdf"):
                skipped.append({"part_number": part, "reason": "برای واردکردن دیتاشیت، URL رسمی HTTPS با مسیر PDF لازم است"})
                continue
            if str(record.get("validation_status", "")) != "official_datasheet_reviewed":
                skipped.append({"part_number": part, "reason": "فقط وضعیت official_datasheet_reviewed با تأیید صریح قابل واردکردن است"})
                continue
            if not str(record.get("manufacturer", "")).strip() or not str(record.get("category", "")).strip():
                skipped.append({"part_number": part, "reason": "سازنده یا دسته‌بندی خالی است"})
                continue
            exists = conn.execute("SELECT 1 FROM components WHERE part_number=? COLLATE NOCASE", (part,)).fetchone()
            if exists:
                skipped.append({"part_number": part, "reason": "قطعه از قبل وجود دارد؛ ابزار intake رکورد موجود را بازنویسی نمی‌کند"})
                continue
            host = urllib.parse.urlparse(url).hostname or ""
            source_key = "intake_" + normalized_part(part).lower()
            title = str(record.get("source_title") or f"Official datasheet: {part}")
            publisher = str(record.get("publisher") or record.get("manufacturer"))
            accessed = date.today().isoformat()
            conn.execute(
                """INSERT INTO sources(source_key,title,publisher,document_type,url,document_version,
                   accessed_on,status,notes) VALUES (?,?,?,?,?,?,?,?,?)""",
                (source_key, title, publisher, "Official datasheet", url,
                 str(record.get("document_version") or "unspecified; human review required"), accessed,
                 "official_datasheet_reviewed", f"Host: {host}. Human reviewer: {reviewer}. {note}"),
            )
            source_id = conn.execute("SELECT id FROM sources WHERE source_key=?", (source_key,)).fetchone()[0]
            conn.execute(
                """INSERT INTO components(part_number,manufacturer,category,component_type,function_text,
                   common_applications,specs_json,recommended_operating_json,absolute_max_json,package,
                   pin_count,operating_temperature,datasheet_url,datasheet_section,source_id,accessed_on,
                   validation_status,last_reviewed,notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (part, str(record["manufacturer"]).strip(), str(record["category"]).strip(),
                 str(record.get("component_type", "")), str(record.get("function_text", "")),
                 str(record.get("common_applications", "")), json.dumps(record.get("specs", {}), ensure_ascii=False),
                 json.dumps(record.get("recommended_operating", {}), ensure_ascii=False),
                 json.dumps(record.get("absolute_max", {}), ensure_ascii=False), record.get("package"),
                 record.get("pin_count"), record.get("operating_temperature"), url, sections, source_id,
                 accessed, "official_datasheet_reviewed", accessed,
                 f"بازبینی انسانی توسط {reviewer}: {note}"),
            )
            component_id = conn.execute("SELECT id FROM components WHERE part_number=? COLLATE NOCASE", (part,)).fetchone()[0]
            conn.execute(
                """INSERT INTO component_datasheets(component_id,source_id,page_or_section,revision,notes)
                   VALUES (?,?,?,?,?)""",
                (component_id, source_id, sections, record.get("document_version"), note),
            )
            conn.execute(
                """INSERT INTO validation_records(entity_type,entity_id,status,evidence,reviewer,source_id)
                   VALUES ('component',?,'official_datasheet_reviewed',?,?,?)""",
                (component_id, f"{note}; sections reviewed: {sections}", reviewer, source_id),
            )
            imported.append(part)
    return {"imported": imported, "skipped": skipped}


def download_pdf(url: str, output_dir: Path, *, timeout: int = 25) -> dict[str, Any]:
    if not official_url(url):
        raise ValueError("برای دانلود فقط HTTPS از ناشر مجاز پذیرفته می‌شود.")
    parsed = urllib.parse.urlparse(url)
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(parsed.path).name or "datasheet.pdf")
    if not safe_name.lower().endswith(".pdf"):
        safe_name += ".pdf"
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / safe_name
    request = urllib.request.Request(url, headers={"User-Agent": "CIRCUIT-AI-source-intake/0.1 (manual user request)"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        final_url = response.geturl()
        if not official_url(final_url):
            raise ValueError("تغییرمسیر به دامنه غیرمجاز؛ دانلود متوقف شد.")
        content_type = response.headers.get("Content-Type", "").lower()
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("حجم سند از حد 25 MiB بیشتر است؛ دانلود متوقف شد.")
    if not body.startswith(b"%PDF-") and "pdf" not in content_type:
        raise ValueError(f"پاسخ به‌عنوان PDF شناخته نشد (Content-Type={content_type or 'نامشخص'}).")
    if destination.exists():
        raise FileExistsError(f"فایل از قبل وجود دارد؛ بدون اجازه بازنویسی نشد: {destination}")
    destination.write_bytes(body)
    return {"path": str(destination), "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(), "final_url": final_url}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="JSON manifest explicitly supplied by operator")
    parser.add_argument("--download", action="store_true", help="Download listed official PDFs (network access; opt-in)")
    parser.add_argument("--extract-text", action="store_true", help="Extract text if optional pypdf is installed; no automatic fact approval")
    parser.add_argument("--import-approved", action="store_true", help="Import only records explicitly marked human_approved with reviewer/evidence/sections")
    parser.add_argument("--db", type=Path, default=None, help="SQLite database path used with --import-approved")
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "reports" / "source_intake_report.json")
    parser.add_argument("--pdf-dir", type=Path, default=ROOT / "data" / "datasheets")
    args = parser.parse_args()
    if not args.manifest.is_file():
        parser.error(f"Manifest پیدا نشد: {args.manifest}")
    try:
        data = json.loads(args.manifest.read_text(encoding="utf-8"))
        report = audit_manifest(data)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"خطای خواندن manifest: {exc}", file=sys.stderr)
        return 2
    if args.import_approved:
        try:
            from services.db import database_path
            target_db = args.db.expanduser().resolve() if args.db else database_path()
            report["database_import"] = import_approved_records(data, db_path=target_db)
        except Exception as exc:
            print(f"ورود داده تأییدشده انجام نشد: {exc}", file=sys.stderr)
            return 2
    if args.download:
        for record in data.get("components", []):
            url = str(record.get("datasheet_url", ""))
            if not official_url(url):
                continue
            try:
                result = download_pdf(url, args.pdf_dir)
                report.setdefault("downloads", []).append({"part_number": record.get("part_number"), **result})
                if args.extract_text:
                    try:
                        from pypdf import PdfReader  # optional dependency
                        reader = PdfReader(result["path"])
                        text = "\n".join(page.extract_text() or "" for page in reader.pages)
                        text_path = Path(result["path"]).with_suffix(".txt")
                        text_path.write_text(text, encoding="utf-8")
                        report["downloads"][-1]["extracted_text_path"] = str(text_path)
                        report["downloads"][-1]["extracted_pages"] = len(reader.pages)
                    except ImportError:
                        report["downloads"][-1]["extraction_note"] = "pypdf نصب نیست؛ برای متن PDF، اختیاری: pip install pypdf"
                time.sleep(1.0)  # polite spacing between explicitly requested downloads
            except (urllib.error.URLError, TimeoutError, OSError, ValueError, FileExistsError) as exc:
                report.setdefault("download_errors", []).append({"part_number": record.get("part_number"), "url": url, "error": str(exc)})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"گزارش ممیزی ذخیره شد: {args.out}")
    print(f"رکوردها: {report['total_records']} | قطعات یکتا: {report['unique_part_numbers']} | موارد نیازمند بررسی: {len(report['issues'])}")
    print("وضعیت تأیید به‌طور خودکار ارتقا داده نمی‌شود.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
