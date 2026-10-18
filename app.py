from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from core.diagnostic_engine import diagnose
from services.backup_service import BackupError, create_backup, restore_backup
from services.component_service import create_component, get_component, get_diagnostic_profile, list_categories, search_components
from services.db import db_session, database_path, init_db
from services.knowledge_service import get_test_catalog, list_rules, list_sources, list_topologies, quality_report
from services.repair_service import (
    SYMPTOM_LABELS, add_measurement, archive_case, close_case, create_case,
    delete_measurement, find_similar_cases, get_case, list_cases, recent_cases,
    record_test_result, reopen_case, save_diagnosis, update_case,
)
from services.settings_service import get_setting, set_setting
from ui.calculator_page import render_calculators
from ui.common import badge, esc, validation_label


PAGES = [
    "داشبورد",
    "عیب‌یابی جدید",
    "پرونده‌های تعمیر",
    "بانک قطعات",
    "دانش مدارها",
    "قواعد عیب‌یابی",
    "منابع فنی",
    "مدیریت پایگاه داده",
    "محاسبات مهندسی",
    "تنظیمات",
]
PAGE_TITLES = {
    "داشبورد": "نمای کلی سامانه",
    "عیب‌یابی جدید": "پرونده و فرایند عیب‌یابی",
    "پرونده‌های تعمیر": "جست‌وجوی پرونده‌های تعمیر",
    "بانک قطعات": "کتابخانه قطعات الکترونیکی",
    "دانش مدارها": "ساختارها و دانش تعمیراتی",
    "قواعد عیب‌یابی": "موتور قواعد شفاف",
    "منابع فنی": "منابع و اسناد فنی",
    "مدیریت پایگاه داده": "داده‌ها، پشتیبان‌گیری و بازیابی",
    "محاسبات مهندسی": "ابزارهای محاسبه الکتریکی",
    "تنظیمات": "تنظیمات محلی",
}

APP_CONFIG = json.loads((Path(__file__).resolve().parent / "config" / "settings.json").read_text(encoding="utf-8"))
APP_NAME = str(APP_CONFIG.get("app", {}).get("name", "CIRCUIT AI"))
APP_TAGLINE = str(APP_CONFIG.get("app", {}).get("tagline", "Intelligent Electronics Diagnostics"))

st.set_page_config(page_title=f"{APP_NAME} | عیب‌یابی الکترونیک", page_icon="⚡", layout="wide", initial_sidebar_state="expanded")

if "_pending_page" in st.session_state:
    st.session_state["page_nav"] = st.session_state.pop("_pending_page")
if "_pending_diag_step" in st.session_state:
    st.session_state["diag_step"] = st.session_state.pop("_pending_diag_step")
APP_SCHEMA_VERSION = 3
if "_db_path" not in st.session_state:
    st.session_state["_db_path"] = str(database_path())
DB_PATH = Path(st.session_state["_db_path"])
if st.session_state.get("_initialized_schema_version") != APP_SCHEMA_VERSION:
    try:
        init_db(DB_PATH)
        st.session_state["_initialized_schema_version"] = APP_SCHEMA_VERSION
    except Exception as exc:
        st.error(f"پایگاه داده محلی آماده نشد: {exc}")
        st.stop()
if "_theme" not in st.session_state:
    st.session_state["_theme"] = get_setting("theme", APP_CONFIG.get("app", {}).get("default_theme", "dark"), path=DB_PATH)

DARK = {
    "background": "#0B0F14", "panel": "#121923", "card": "#18222E", "border": "#283544",
    "accent": "#00D1B2", "blue": "#4DA3FF", "text": "#F1F5F9", "muted": "#94A3B8",
    "success": "#22C55E", "warning": "#F59E0B", "danger": "#EF4444",
}
LIGHT = {
    "background": "#F4F7FA", "panel": "#FFFFFF", "card": "#EDF3F7", "border": "#D7E0E8",
    "accent": "#008F7A", "blue": "#216FC0", "text": "#15202B", "muted": "#5B6B7B",
    "success": "#16803C", "warning": "#A96800", "danger": "#C92A2A",
}
C = DARK if st.session_state["_theme"] == "dark" else LIGHT

st.markdown(f"""
<style>
:root {{ color-scheme: {'dark' if st.session_state['_theme'] == 'dark' else 'light'}; }}
html, body, [class*="css"], .stApp {{ font-family: "Noto Sans Arabic", "Noto Naskh Arabic", "DejaVu Sans", sans-serif; }}
.stApp {{ background: {C['background']}; color: {C['text']}; direction: rtl; }}
[data-testid="stAppViewContainer"] > .main {{ direction: rtl; }}
.block-container {{ max-width: 1500px; padding-top: 1.2rem; padding-bottom: 3rem; }}
[data-testid="stSidebar"] {{ background: {C['panel']}; border-left: 1px solid {C['border']}; border-right: 0; }}
[data-testid="stSidebar"] * {{ direction: rtl; text-align: right; }}
[data-testid="stHeader"] {{ background: transparent; }}
h1, h2, h3, h4, p, label {{ color: {C['text']}; }}
.stCaption, [data-testid="stCaptionContainer"] {{ color: {C['muted']} !important; }}
.stButton > button, .stFormSubmitButton > button {{ border: 1px solid {C['border']}; border-radius: 10px; background: {C['card']}; color: {C['text']}; min-height: 2.65rem; font-weight: 650; transition: border .15s ease, background .15s ease; }}
.stButton > button:hover, .stFormSubmitButton > button:hover {{ border-color: {C['accent']}; color: {C['accent']}; }}
[data-testid="stMetric"] {{ background: {C['card']}; border: 1px solid {C['border']}; padding: 1rem; border-radius: 12px; direction: rtl; text-align: right; }}
[data-testid="stMetricLabel"] {{ color: {C['muted']}; }}
[data-testid="stMetricValue"] {{ color: {C['accent']}; }}
[data-testid="stVerticalBlockBorderWrapper"] {{ border-color: {C['border']} !important; }}
[data-testid="stExpander"] {{ background: {C['panel']}; border: 1px solid {C['border']}; border-radius: 10px; }}
[data-testid="stDataFrame"] {{ direction: rtl; }}
[data-testid="stTextInput"] input, [data-testid="stNumberInput"] input, [data-testid="stTextArea"] textarea {{ background: {C['panel']}; color: {C['text']}; border-color: {C['border']}; }}
[data-testid="stSelectbox"] div, [data-testid="stMultiSelect"] div {{ border-color: {C['border']}; }}
hr {{ border-color: {C['border']}; }}
.brand {{ display:flex; align-items:center; gap:.65rem; margin: .2rem 0 1.2rem; }}
.brand-mark {{ width:2.4rem; height:2.4rem; border-radius:9px; background:{C['card']}; border:1px solid {C['border']}; display:grid; place-items:center; color:{C['accent']}; font-size:1.2rem; }}
.brand-name {{ font-weight:850; letter-spacing:.08em; color:{C['text']}; font-size:1rem; }}
.brand-sub {{ color:{C['muted']}; font-size:.68rem; margin-top:.1rem; }}
.topbar {{ border-bottom:1px solid {C['border']}; padding:.2rem 0 .8rem; margin-bottom:1.1rem; display:flex; align-items:center; justify-content:space-between; gap:1rem; }}
.topbar-title {{ font-size:1.3rem; font-weight:750; }}
.status-pill {{ border:1px solid {C['border']}; background:{C['card']}; border-radius:999px; padding:.3rem .65rem; font-size:.78rem; color:{C['muted']}; white-space:nowrap; }}
.card {{ background:{C['card']}; border:1px solid {C['border']}; border-radius:13px; padding:1rem 1.1rem; margin:.25rem 0 .75rem; }}
.card-title {{ color:{C['muted']}; font-size:.82rem; margin-bottom:.35rem; }}
.card-value {{ font-size:1.38rem; color:{C['text']}; font-weight:800; }}
.card-foot {{ color:{C['muted']}; font-size:.75rem; margin-top:.35rem; }}
.badge {{ display:inline-block; padding:.2rem .55rem; border:1px solid {C['border']}; border-radius:999px; font-size:.72rem; white-space:nowrap; margin:.1rem; }}
.badge.info {{ color:{C['blue']}; }} .badge.ok {{ color:{C['success']}; }} .badge.warn {{ color:{C['warning']}; }} .badge.danger {{ color:{C['danger']}; }}
.callout {{ background:{C['panel']}; border:1px solid {C['border']}; border-right:4px solid {C['warning']}; border-radius:9px; padding:.85rem 1rem; margin:.5rem 0 1rem; }}
.callout.danger {{ border-right-color:{C['danger']}; }} .callout.ok {{ border-right-color:{C['success']}; }}
.muted {{ color:{C['muted']}; }} .tech {{ direction:ltr; unicode-bidi:isolate; font-family:monospace; }}
.step-strip {{ display:flex; flex-wrap:wrap; gap:.45rem; margin:.3rem 0 1rem; }}
.step-item {{ border:1px solid {C['border']}; border-radius:8px; padding:.4rem .7rem; background:{C['panel']}; color:{C['muted']}; font-size:.8rem; }}
.step-item.active {{ border-color:{C['accent']}; color:{C['accent']}; }}
.small {{ font-size:.8rem; }}
a {{ color:{C['blue']}; }}
@media (max-width: 800px) {{ .block-container {{ padding: .6rem .8rem 2rem; }} .topbar {{ flex-wrap:wrap; }} }}
</style>
""", unsafe_allow_html=True)


def go_to(page: str) -> None:
    # Streamlit invokes this callback before its automatic rerun.
    st.session_state["_pending_page"] = page


def card(title: str, value: str, foot: str = "") -> None:
    st.markdown(
        f'<div class="card"><div class="card-title">{esc(title)}</div><div class="card-value">{esc(value)}</div>'
        f'<div class="card-foot">{esc(foot)}</div></div>', unsafe_allow_html=True
    )


def safety_callout(text: str = "پیش از هر اندازه‌گیری روشن، نوع منبع، ولتاژ واقعی، نقطه زمین و سطح خطر را از روی مدار مشخص کنید.", danger: bool = False) -> None:
    kind = " danger" if danger else ""
    st.markdown(f'<div class="callout{kind}"><b>ایمنی:</b> {esc(text)}</div>', unsafe_allow_html=True)


def render_topbar(page: str) -> None:
    st.markdown(
        f'<div class="topbar"><div class="topbar-title">{esc(PAGE_TITLES.get(page, page))}</div>'
        f'<div style="display:flex;gap:.45rem;flex-wrap:wrap;justify-content:flex-start">'
        f'<span class="status-pill">● SQLite محلی</span><span class="status-pill">◌ آفلاین‌محور</span>'
        f'<span class="status-pill">قواعد: توضیح‌پذیر</span></div></div>',
        unsafe_allow_html=True,
    )


def show_validation(status: str) -> None:
    kind = "ok" if status in {"official_datasheet_reviewed", "verified_multiple_sources", "lab_tested"} else "warn"
    st.markdown(badge(validation_label(status), kind), unsafe_allow_html=True)


def render_data_table(rows: list[dict], columns: dict[str, str]) -> None:
    if not rows:
        st.info("رکوردی برای نمایش وجود ندارد.")
        return
    frame = pd.DataFrame(rows)
    visible = [col for col in columns if col in frame.columns]
    frame = frame[visible].rename(columns=columns)
    st.dataframe(frame, width="stretch", hide_index=True)


def render_dashboard() -> None:
    st.markdown("### ابزار مهندسی برای عیب‌یابی مرحله‌ای")
    st.caption(f"{APP_TAGLINE} · نسخه محلی و آفلاین‌محور؛ موتور قانون‌محور، محاسبات مهندسی و دانش همراه با منبع.")
    report = quality_report(path=DB_PATH)
    metrics = [
        ("پرونده‌های تعمیر", report.get("cases", 0), "ثبت‌شده در پایگاه داده"),
        ("قطعات مستند", report["components"], f"{report['component_official_source_percent']}٪ با منبع رسمی"),
        ("قواعد فعال", sum(1 for rule in list_rules(path=DB_PATH) if rule["enabled"]), "قاعده، نه مدل آماری"),
        ("نیازمند بررسی", report["unverified_cases"] + report["component_records_needing_review"], "پرونده تأییدنشده + رکورد قطعه ناقص"),
        ("منابع فنی", report["sources"], "ثبت‌شده در بانک محلی"),
    ]
    # Keep all displayed counters tied to database queries.
    with db_session(DB_PATH) as conn:
        case_count = conn.execute("SELECT COUNT(*) FROM repair_cases WHERE is_archived=0").fetchone()[0]
    metrics[0] = ("پرونده‌های تعمیر", case_count, "ثبت‌شده در پایگاه داده")
    cols = st.columns(5)
    for col, (title, value, foot) in zip(cols, metrics):
        with col:
            st.metric(title, value, help=foot)
    st.markdown("#### شروع سریع")
    quick = st.columns(4)
    with quick[0]:
        st.button("＋ شروع عیب‌یابی جدید", type="primary", width="stretch", on_click=go_to, args=("عیب‌یابی جدید",))
    with quick[1]:
        st.button("⌕ جست‌وجوی قطعه", width="stretch", on_click=go_to, args=("بانک قطعات",))
    with quick[2]:
        st.button("▤ پرونده‌های مشابه", width="stretch", on_click=go_to, args=("پرونده‌های تعمیر",))
    with quick[3]:
        st.button("⛁ مدیریت داده‌ها", width="stretch", on_click=go_to, args=("مدیریت پایگاه داده",))
    left, right = st.columns([1.45, 1])
    with left:
        st.markdown("#### آخرین فعالیت‌ها")
        cases = recent_cases(6, path=DB_PATH)
        if not cases:
            st.markdown('<div class="card"><b>هنوز پرونده‌ای ثبت نشده است.</b><div class="card-foot">برای شروع، یک پرونده واقعی ایجاد کنید؛ داده نمونه تعمیراتی ساخته نشده است.</div></div>', unsafe_allow_html=True)
            st.button("ایجاد اولین پرونده", on_click=go_to, args=("عیب‌یابی جدید",))
        else:
            for item in cases:
                symptom_text = "، ".join(SYMPTOM_LABELS.get(code, code) for code in item["symptoms"]) or "علامتی ثبت نشده"
                st.markdown(
                    f'<div class="card"><b>{esc(item["board_name"])}</b> <span class="muted">· {esc(item["case_number"])}</span>'
                    f'<div class="card-foot">{esc(item.get("fault_description") or symptom_text)} · {esc(item["created_at"][:10])}</div>'
                    f'<div class="card-foot">وضعیت: {esc(validation_label(item["status"]))} · نتیجه: {esc(item.get("final_outcome") or "ثبت نشده")}</div></div>',
                    unsafe_allow_html=True,
                )
    with right:
        st.markdown("#### وضعیت بانک دانش")
        st.markdown(f'<div class="card"><div class="card-title">اعتبار فنی</div><div class="card-value">{report["official_datasheets_reviewed"]} دیتاشیت رسمی بررسی‌شده</div><div class="card-foot">این تعداد به معنی تأیید آزمایشگاهی نیست.</div></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="card"><div class="card-title">ساختارهای مدار</div><div class="card-value">{report["topologies"]}</div><div class="card-foot">نمونه‌های مستندشده از مدار مرجع سازنده</div></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="card"><div class="card-title">قواعد نیازمند بازبینی انسانی</div><div class="card-value">{report["rules_needing_review"]}</div><div class="card-foot">تا زمان اعتبارسنجی، فقط مسیر triage هستند.</div></div>', unsafe_allow_html=True)
    safety_callout("CIRCUIT AI ولتاژ/پایه عمومی برای برد ناشناس فرض نمی‌کند. بردهای برق شهر، باس DC و خازن‌های پرانرژی فقط برای متخصص واجد صلاحیت هستند.", danger=True)


def _case_form_new() -> None:
    st.markdown("### مرحله ۱ از ۴ · مشخصات برد")
    st.caption("با ثبت این فرم یک پروندهٔ محلی ساخته می‌شود؛ اندازه‌گیری‌ها در مرحله بعد جداگانه ذخیره می‌شوند.")
    with st.form("create_new_case", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            board_name = st.text_input("نام برد *", placeholder="مثلاً کنترلر پمپ / نام درج‌شده روی PCB")
            manufacturer = st.text_input("سازنده برد", placeholder="در صورت نامشخص، خالی بگذارید")
            model = st.text_input("مدل / شماره PCB", placeholder="شماره کامل یا مارکینگ")
        with col2:
            application = st.text_input("کاربرد", placeholder="کنترل موتور، منبع تغذیه، کنترل صنعتی...")
            reference_component = st.text_input("قطعه مرجع (اختیاری)", placeholder="شماره دقیق روی بدنه؛ مثلاً TPS5430")
            expected_enabled = st.checkbox("ولتاژ ورودی مورد انتظار را از منبع معتبر دارم")
            expected_value = st.number_input("ولتاژ ورودی مورد انتظار (V)", value=0.0, step=0.1, format="%.4f", disabled=not expected_enabled)
            expected_source = st.text_input("منبع مقدار مورد انتظار", placeholder="شماتیک/لیبل/بخش دیتاشیت + شماره صفحه") if expected_enabled else ""
        description = st.text_area("شرح اولیه خرابی", placeholder="آنچه دیده‌اید، چه زمانی رخ می‌دهد، چه چیزی قبلاً تغییر کرده است؟")
        submitted = st.form_submit_button("ذخیره پرونده و ادامه به ثبت علائم", type="primary", width="stretch")
    if submitted:
        if not board_name.strip():
            st.error("نام برد لازم است.")
            return
        try:
            case = create_case({
                "board_name": board_name, "board_manufacturer": manufacturer, "board_model": model,
                "application": application, "reference_component": reference_component,
                "expected_input_voltage": expected_value if expected_enabled else None,
                "expected_input_unit": "V", "expected_input_source": expected_source,
                "fault_description": description,
            }, path=DB_PATH)
            st.session_state["diagnosis_case_id"] = case["id"]
            st.session_state["_pending_diag_step"] = "۲ · علائم"
            st.success(f"پرونده {case['case_number']} ذخیره شد.")
            st.rerun()
        except Exception as exc:
            st.error(f"ذخیره پرونده ناموفق بود: {exc}")


def _render_case_measurements(case: dict) -> None:
    measurements = case.get("measurements", [])
    if not measurements:
        st.info("هنوز اندازه‌گیری‌ای برای این پرونده ثبت نشده است.")
        return
    rows = [{
        "شناسه": m["id"], "سیگنال / نقطه": m["signal"], "مقدار": m["measured_value"], "واحد": m["unit"],
        "حالت": {"powered": "روشن", "power_off": "خاموش", "unknown": "نامشخص"}.get(m["measurement_state"], m["measurement_state"]),
        "مرجع مورد انتظار": "—" if m["expected_value"] is None else f"{m['expected_value']} {m['unit']}",
        "تلرانس ٪": "—" if m["tolerance_percent"] is None else m["tolerance_percent"],
        "شرایط": m["conditions"], "منبع مرجع": m["expected_source"],
    } for m in measurements]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def _render_diagnostic_result(case: dict, result: dict) -> None:
    status_kind = "warn" if result["status"] != "analysis_available_not_a_diagnosis" else "info"
    st.markdown(f'<div class="card"><b>{esc(result["status_fa"])}</b><div class="card-foot">{esc(result["method"])}</div></div>', unsafe_allow_html=True)
    if result.get("ranked_hypotheses"):
        st.markdown("#### فرضیه‌های/شرایط قابل بررسی")
        st.caption("ترتیب، اولویت بررسی است؛ احتمال آماری یا تشخیص قطعی نیست.")
        for index, item in enumerate(result["ranked_hypotheses"], start=1):
            with st.container(border=True):
                st.markdown(f"**{index}. {item['title']}**  {badge(item['priority_label'], 'warn' if 'خارج' in item['title'] else 'info')}", unsafe_allow_html=True)
                st.caption(item["rank_reason"])
                cols = st.columns(2)
                with cols[0]:
                    st.markdown("**شواهد موافق / داده ثبت‌شده**")
                    for evidence in item["evidence_for"]:
                        st.markdown(f"- {evidence}")
                with cols[1]:
                    st.markdown("**شواهد مخالف و محدودیت‌ها**")
                    for evidence in item["evidence_against"]:
                        st.markdown(f"- {evidence}")
                st.markdown(f"**کیفیت شواهد:** {item['evidence_quality']['label']}")
                if item.get("source"):
                    source = item["source"]
                    st.markdown(f"**منبع:** [{source.get('title')}]({source.get('url')}) · {esc(item.get('diagnostic_limit',''))}")
                else:
                    st.caption(item.get("diagnostic_limit", ""))
    else:
        st.info("با داده فعلی هیچ علت خرابی مستندی رتبه‌بندی نشد. سیستم به‌جای حدس، اندازه‌گیری/مرجع بعدی را درخواست می‌کند.")

    if result.get("observations"):
        with st.expander("مشاهدات و مقایسه‌های عددی ثبت‌شده", expanded=True):
            for obs in result["observations"]:
                value = obs.get("measured_value")
                unit = obs.get("unit", "")
                st.markdown(f"**{obs['title']}**")
                if value is not None:
                    st.markdown(f"`{value} {unit}` · {esc(obs.get('interpretation',''))}")
                else:
                    st.markdown(esc(obs.get("interpretation", "")))
                if obs.get("reference_source"):
                    st.caption(f"منبع مقدار مرجع: {obs['reference_source']}")

    if result.get("missing_information"):
        st.markdown("#### اطلاعاتی که هنوز لازم است")
        for item in result["missing_information"]:
            st.markdown(f"- {item}")

    if result.get("next_tests"):
        st.markdown("#### آزمایش/بررسی بعدی")
        for index, test in enumerate(result["next_tests"], start=1):
            with st.expander(f"{index}. {test['title']} · خطر: {test['risk_level']}", expanded=(index == 1)):
                st.write(test.get("purpose", ""))
                for line in test.get("steps", []):
                    st.markdown(f"- {line}")
                if test.get("prerequisites"):
                    st.markdown("**پیش‌نیاز:** " + "؛ ".join(test["prerequisites"]))
                if test.get("limitations"):
                    st.warning(test["limitations"])
                if test.get("source_url"):
                    st.markdown(f"منبع: [{test.get('source_title') or 'دیتاشیت رسمی'}]({test['source_url']}) · {test.get('source_section') or ''}")
                if test.get("validation_status") == "needs_review":
                    st.caption("این راهنمای عمومی به بازبینی عملی/انسانی نیاز دارد.")
                with st.form(f"test_result_{case['id']}_{index}_{test['test_code']}"):
                    result_label = st.selectbox("نتیجه/برداشت ثبت‌شده", ["همسو با مسیر/فرضیه", "مخالف مسیر/فرضیه", "نامشخص", "انجام نشده"], key=f"test_result_select_{case['id']}_{index}")
                    notes = st.text_area("مقدار واقعی، شرایط و توضیحات نتیجه", key=f"test_notes_{case['id']}_{index}")
                    submitted = st.form_submit_button("ذخیره نتیجه آزمایش")
                if submitted:
                    mapping = {"همسو با مسیر/فرضیه": "supports", "مخالف مسیر/فرضیه": "contradicts", "نامشخص": "inconclusive", "انجام نشده": "not_performed"}
                    try:
                        record_test_result(case["id"], {
                            "test_code": test["test_code"], "test_title": test["title"],
                            "result": mapping[result_label], "notes": notes,
                        }, path=DB_PATH)
                        current = get_case(case["id"], path=DB_PATH)
                        updated = diagnose(current, path=DB_PATH)
                        save_diagnosis(case["id"], updated, path=DB_PATH)
                        st.success("نتیجه ذخیره شد و تحلیلِ مبتنی بر اطلاعات تازه دوباره اجرا شد.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"ثبت نتیجه ناموفق بود: {exc}")

    if result.get("matched_rules"):
        with st.expander("قواعدی که واقعاً اجرا شدند"):
            for rule in result["matched_rules"]:
                st.markdown(f"- **{rule['title']}** · {validation_label(rule['validation_status'])}")
                st.caption(rule["explanation"])
    if result.get("test_findings"):
        with st.expander("نتایج آزمایش‌های پیشین"):
            for finding in result["test_findings"]:
                st.markdown(f"- **{finding['title']}**: {finding['interpretation']}")
                if finding.get("notes"):
                    st.caption(finding["notes"])
    with st.expander("هشدارهای ایمنی و حدود تفسیر"):
        for warning in result["warnings"]:
            st.markdown(f"- {warning}")

    similar = find_similar_cases(case, limit=4, path=DB_PATH)
    with st.expander("پرونده‌های مشابه قبلی", expanded=False):
        st.caption("جست‌وجوی واژه‌ای/علائم برای یافتن سرنخ است؛ شباهت، علت یا تشخیص را ثابت نمی‌کند. وضعیت تأیید هر پرونده جداگانه نمایش داده می‌شود.")
        if not similar:
            st.info("پرونده مشابه قبلی پیدا نشد.")
        else:
            for item in similar:
                st.markdown(f"**{item['case_number']} · {item['board_name']}** · شباهت تقریبی {item['similarity_score']*100:.0f}٪ · {validation_label(item['verification_status'])}")
                st.caption("؛ ".join(item["similarities"] + item["differences"]) or "تطبیق محدود")
                st.caption(item["knowledge_warning"])


def render_diagnosis_page() -> None:
    st.markdown("### عیب‌یابی مرحله‌ای")
    st.caption("پرونده از ابتدا ذخیره می‌شود؛ هر اندازه‌گیری و نتیجه آزمایش جداگانه به همان پرونده افزوده می‌شود.")
    active_id = st.session_state.get("diagnosis_case_id")
    case = get_case(active_id, path=DB_PATH) if active_id else None
    if case is None or case.get("is_archived"):
        st.session_state.pop("diagnosis_case_id", None)
        safety_callout("برای بردهای صنعتی ابتدا سطح ولتاژ/انرژی را مشخص کنید. اگر منبع یا مرجع زمین ناشناخته است، آزمون روشن انجام ندهید.", danger=True)
        _case_form_new()
        return
    st.markdown(f"**پرونده فعال:** `{case['case_number']}` · {esc(case['board_name'])} · وضعیت {validation_label(case['status'])}")
    if case["status"] == "completed":
        st.info("این پرونده بسته شده است. آن را از تاریخچه باز کنید یا پرونده تازه بسازید.")
        cols = st.columns(2)
        with cols[0]:
            if st.button("بازکردن دوباره پرونده", key=f"reopen_{case['id']}"):
                reopen_case(case["id"], path=DB_PATH)
                st.rerun()
        with cols[1]:
            if st.button("پرونده تازه", key="new_case_from_closed"):
                st.session_state.pop("diagnosis_case_id", None)
                st.session_state["_pending_diag_step"] = "۱ · مشخصات"
                st.rerun()
        return

    step_labels = ["۱ · مشخصات", "۲ · علائم", "۳ · اندازه‌گیری‌ها", "۴ · تحلیل و نتیجه"]
    if "diag_step" not in st.session_state:
        st.session_state["diag_step"] = step_labels[1]
    current_step = st.radio("مراحل پرونده", step_labels, horizontal=True, key="diag_step", label_visibility="collapsed")
    safety_callout("تست روشن فقط پس از تأیید ولتاژ/نقطه/ابزار/صلاحیت. تست مقاومت فقط بی‌برق و پس از روش تخلیه ایمن طبق مدار.", danger=True)

    if current_step == step_labels[0]:
        st.markdown("#### مشخصات برد")
        with st.form(f"edit_case_{case['id']}"):
            a, b = st.columns(2)
            with a:
                board_name = st.text_input("نام برد *", value=case["board_name"])
                manufacturer = st.text_input("سازنده", value=case["board_manufacturer"])
                model = st.text_input("مدل/شماره PCB", value=case["board_model"])
                application = st.text_input("کاربرد", value=case["application"])
            with b:
                reference_component = st.text_input("شماره دقیق قطعه مرجع (اختیاری)", value=case["reference_component"], help="مقایسه محدودۀ کاری فقط برای قطعه و پایه‌های مشخص انجام می‌شود.")
                enabled = st.checkbox("ولتاژ ورودی مورد انتظار مشخص است", value=case["expected_input_voltage"] is not None)
                expected_value = st.number_input("ولتاژ ورودی مورد انتظار (V)", value=float(case["expected_input_voltage"] or 0.0), step=0.1, format="%.4f", disabled=not enabled)
                expected_source = st.text_input("منبع مقدار", value=case["expected_input_source"])
            description = st.text_area("شرح خرابی", value=case["fault_description"])
            submit = st.form_submit_button("ذخیره مشخصات", type="primary")
        if submit:
            try:
                update_case(case["id"], {
                    "board_name": board_name, "board_manufacturer": manufacturer, "board_model": model,
                    "application": application, "reference_component": reference_component,
                    "expected_input_voltage": expected_value if enabled else None,
                    "expected_input_unit": "V", "expected_input_source": expected_source,
                    "fault_description": description,
                }, path=DB_PATH)
                st.success("مشخصات ذخیره شد.")
                st.rerun()
            except Exception as exc:
                st.error(f"ذخیره ناموفق بود: {exc}")

    elif current_step == step_labels[1]:
        st.markdown("#### علائم مشاهده‌شده")
        with st.form(f"symptoms_{case['id']}"):
            selected = st.multiselect(
                "یک یا چند علامت را انتخاب کنید",
                options=list(SYMPTOM_LABELS),
                default=case["symptoms"],
                format_func=lambda key: SYMPTOM_LABELS.get(key, key),
            )
            description = st.text_area("توضیح آزاد / زمان رخداد / شرایط بار", value=case["fault_description"])
            submit = st.form_submit_button("ذخیره علائم", type="primary")
        if submit:
            try:
                update_case(case["id"], {"symptoms": selected, "fault_description": description}, path=DB_PATH)
                st.success("علائم ذخیره شدند.")
                st.rerun()
            except Exception as exc:
                st.error(f"ذخیره ناموفق بود: {exc}")

    elif current_step == step_labels[2]:
        st.markdown("#### ثبت اندازه‌گیری واقعی")
        st.caption("مقادیر مرجع/تلرانس را فقط با ذکر منبع همان برد یا قطعه وارد کنید. هر رکورد با وضعیت روشن/خاموش جدا می‌شود.")
        with st.form(f"measurement_form_{case['id']}", clear_on_submit=True):
            a, b, c = st.columns([1.2, 1, .8])
            with a:
                signal = st.text_input("نام سیگنال/نقطه *", placeholder="مثل VIN, VM, VDD یا نام روی شماتیک")
                conditions = st.text_input("شرایط اندازه‌گیری", placeholder="بار، زمان پس از روشن‌شدن، روش/ابزار")
            with b:
                measured = st.number_input("مقدار اندازه‌گیری‌شده *", value=0.0, step=0.01, format="%.6f")
                unit = st.selectbox("واحد", ["V", "mV", "A", "mA", "Ω", "kΩ", "°C", "Hz", "kHz", "logic", "other"])
            with c:
                state_label = st.selectbox("وضعیت مدار", ["نامشخص", "روشن/برق‌دار", "خاموش/بی‌برق"])
                expected_enabled = st.checkbox("مقدار مرجع دارم")
                expected_value = st.number_input("مقدار مرجع", value=0.0, step=0.01, format="%.6f", disabled=not expected_enabled)
                tolerance_enabled = st.checkbox("تلرانس مستند دارم", disabled=not expected_enabled)
                tolerance = st.number_input("تلرانس (%)", min_value=0.0, value=0.0, step=0.1, disabled=not tolerance_enabled)
            expected_source = st.text_input("منبع مقدار مرجع", placeholder="نام سند، شماره صفحه/بخش") if expected_enabled else ""
            submit = st.form_submit_button("ذخیره اندازه‌گیری", type="primary")
        if submit:
            if not signal.strip():
                st.error("نام نقطه اندازه‌گیری لازم است.")
            else:
                state = {"نامشخص": "unknown", "روشن/برق‌دار": "powered", "خاموش/بی‌برق": "power_off"}[state_label]
                try:
                    add_measurement(case["id"], {
                        "signal": signal, "measured_value": measured, "unit": unit,
                        "conditions": conditions, "measurement_state": state,
                        "expected_value": expected_value if expected_enabled else None,
                        "tolerance_percent": tolerance if expected_enabled and tolerance_enabled else None,
                        "expected_source": expected_source,
                    }, path=DB_PATH)
                    st.success("اندازه‌گیری ذخیره شد و به سابقه پرونده اضافه شد.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"ذخیره اندازه‌گیری ناموفق بود: {exc}")
        case = get_case(case["id"], path=DB_PATH)
        _render_case_measurements(case)
        if case["measurements"]:
            st.markdown("##### حذف کنترل‌شده یک رکورد اشتباه")
            st.caption("حذف اندازه‌گیری تاریخچه را تغییر می‌دهد؛ در صورت نیاز ابتدا از بانک پشتیبان بگیرید.")
            with st.form(f"delete_measurement_{case['id']}"):
                choice = st.selectbox("رکورد", case["measurements"], format_func=lambda m: f"#{m['id']} · {m['signal']} = {m['measured_value']} {m['unit']}")
                confirm = st.checkbox("حذف همین اندازه‌گیری را تأیید می‌کنم")
                delete = st.form_submit_button("حذف رکورد انتخاب‌شده")
            if delete:
                if not confirm:
                    st.error("برای حذف، تأیید صریح لازم است.")
                else:
                    delete_measurement(choice["id"], path=DB_PATH)
                    st.success("رکورد حذف شد.")
                    st.rerun()

    else:
        st.markdown("#### تحلیل بر اساس داده‌های ذخیره‌شده")
        case = get_case(case["id"], path=DB_PATH)
        analyze = st.button("اجرای مجدد موتور عیب‌یابی", type="primary", key=f"analyze_{case['id']}")
        if analyze:
            try:
                result = diagnose(case, path=DB_PATH)
                save_diagnosis(case["id"], result, path=DB_PATH)
                case = get_case(case["id"], path=DB_PATH)
                st.success("تحلیل اجرا شد و نسخه نتیجه در پرونده ذخیره شد.")
            except Exception as exc:
                st.error(f"تحلیل ناموفق بود: {exc}")
                result = None
        else:
            result = case.get("diagnosis") or None
        if result:
            generated = result.get("generated_from", {})
            stale = generated.get("measurement_count") != len(case["measurements"]) or generated.get("test_result_count") != len(case["tests"])
            if stale:
                st.warning("پس از تحلیل قبلی اندازه‌گیری/نتیجه تازه‌ای ثبت شده است؛ دکمه «اجرای مجدد» را بزنید تا رتبه‌بندی/مشاهدات به‌روز شوند.")
            _render_diagnostic_result(case, result)
        else:
            st.info("برای نمایش تحلیل، دکمه اجرای موتور را بزنید. نبود داده کافی صریحاً اعلام می‌شود.")
        st.markdown("---")
        st.markdown("#### ثبت نتیجه تعمیر")
        with st.form(f"close_case_{case['id']}"):
            confirmed_cause = st.text_input("علت نهایی (اگر با آزمایش تأیید شده)")
            repaired_component = st.text_input("قطعه تعمیر/تعویض‌شده")
            final_outcome = st.text_area("نتیجه نهایی تعمیر *", placeholder="تعمیر موفق/ناموفق، تست نهایی، مدت کارکرد...")
            mark_verified = st.checkbox("پرونده را با شواهد مستند تأییدشده علامت بزن")
            reviewer = st.text_input("نام/شناسه بازبین", disabled=not mark_verified)
            evidence = st.text_area("شواهد آزمایش/منبع تأیید", disabled=not mark_verified)
            close = st.form_submit_button("بستن و ذخیره پرونده")
        if close:
            try:
                close_case(case["id"], confirmed_cause=confirmed_cause, repaired_component=repaired_component,
                           final_outcome=final_outcome, verified=mark_verified, reviewer=reviewer,
                           evidence=evidence, path=DB_PATH)
                st.success("پرونده ذخیره و بسته شد. وضعیت اعتبار جداگانه ثبت شده است.")
                st.rerun()
            except Exception as exc:
                st.error(f"بستن پرونده ناموفق بود: {exc}")

    st.markdown("---")
    if st.button("شروع پرونده جدید (پرونده فعلی ذخیره می‌ماند)", key=f"new_case_{case['id']}"):
        st.session_state.pop("diagnosis_case_id", None)
        st.session_state["_pending_diag_step"] = "۱ · مشخصات"
        st.rerun()


def render_history() -> None:
    st.markdown("### جست‌وجو و بازیابی پرونده‌ها")
    query = st.text_input("جست‌وجو بر اساس شناسه، برد، مدل، کاربرد یا شرح خرابی", key="history_query")
    cases = list_cases(query, path=DB_PATH)
    if not cases:
        st.info("پرونده‌ای مطابق جست‌وجو وجود ندارد؛ این صفحه داده نمایشی تولید نمی‌کند.")
        st.button("ایجاد پرونده جدید", on_click=go_to, args=("عیب‌یابی جدید",))
        return
    rows = [{
        "case_number": c["case_number"], "board_name": c["board_name"], "board_model": c["board_model"],
        "fault_description": c["fault_description"], "symptoms": "، ".join(SYMPTOM_LABELS.get(x, x) for x in c["symptoms"]),
        "status": validation_label(c["status"]), "verification_status": validation_label(c["verification_status"]),
        "created_at": c["created_at"][:10], "final_outcome": c["final_outcome"], "id": c["id"],
    } for c in cases]
    render_data_table(rows, {
        "case_number": "شناسه", "board_name": "برد", "board_model": "مدل", "fault_description": "شرح خرابی",
        "symptoms": "علائم", "status": "وضعیت", "verification_status": "اعتبار", "created_at": "تاریخ", "final_outcome": "نتیجه",
    })
    choices = {f"{c['case_number']} · {c['board_name']}": c["id"] for c in cases}
    selected_label = st.selectbox("نمایش پرونده", list(choices))
    case = get_case(choices[selected_label], path=DB_PATH)
    if case:
        with st.container(border=True):
            st.markdown(f"### {case['board_name']} · `{case['case_number']}`")
            st.caption(f"ثبت: {case['created_at']} · وضعیت: {validation_label(case['status'])} · اعتبار: {validation_label(case['verification_status'])}")
            st.write(case.get("fault_description") or "شرح خرابی ثبت نشده است.")
            st.write("علائم: " + ("، ".join(SYMPTOM_LABELS.get(code, code) for code in case["symptoms"]) or "ثبت نشده"))
            if case.get("confirmed_cause"):
                st.markdown(f"**علت نهایی ثبت‌شده:** {case['confirmed_cause']}")
            if case.get("repaired_component"):
                st.markdown(f"**قطعه تعمیرشده:** {case['repaired_component']}")
            if case.get("final_outcome"):
                st.markdown(f"**نتیجه نهایی:** {case['final_outcome']}")
            if case.get("diagnosis"):
                with st.expander("تحلیل ذخیره‌شده"):
                    st.json(case["diagnosis"])
            st.markdown("#### اندازه‌گیری‌ها")
            _render_case_measurements(case)
            if case["tests"]:
                st.markdown("#### آزمایش‌های ثبت‌شده")
                render_data_table(case["tests"], {"test_title": "آزمایش", "result": "نتیجه", "notes": "یادداشت", "tested_at": "زمان"})
        with st.expander("پرونده‌های مشابه"):
            st.caption("امتیاز شباهت از اشتراک علائم، متن و مدل برد ساخته می‌شود؛ نه احتمال علت.")
            similar = find_similar_cases(case, path=DB_PATH)
            if not similar:
                st.info("پرونده مشابهی پیدا نشد.")
            for item in similar:
                st.markdown(f"- `{item['case_number']}` · {item['board_name']} · شباهت {item['similarity_score']*100:.0f}٪ · {validation_label(item['verification_status'])}")
                st.caption("؛ ".join(item["similarities"] + item["differences"]) or item["knowledge_warning"])
        with st.expander("عملیات کنترل‌شده"):
            confirm_archive = st.checkbox(f"بایگانی پرونده {case['case_number']} را تأیید می‌کنم", key=f"archive_confirm_{case['id']}")
            if st.button("بایگانی نرم پرونده", key=f"archive_{case['id']}"):
                if not confirm_archive:
                    st.error("برای بایگانی، تیک تأیید لازم است.")
                else:
                    archive_case(case["id"], path=DB_PATH)
                    st.success("پرونده بایگانی شد؛ رکورد از پایگاه داده حذف نشده است.")
                    st.rerun()


def render_components() -> None:
    st.markdown("### جست‌وجوی قطعه و مشاهده مشخصات")
    categories = ["همه"] + list_categories(path=DB_PATH)
    a, b = st.columns([2, 1])
    with a:
        query = st.text_input("شماره قطعه، سازنده یا کاربرد", key="component_query")
    with b:
        category = st.selectbox("دسته‌بندی", categories)
    parts = search_components(query, category=category, path=DB_PATH)
    render_data_table(parts, {
        "part_number": "شماره قطعه", "manufacturer": "سازنده", "category": "دسته", "component_type": "نوع",
        "package": "پکیج", "validation_status": "وضعیت اعتبار",
    })
    if parts:
        choices = {f"{item['part_number']} · {item['manufacturer']}": item["part_number"] for item in parts}
        selected = st.selectbox("نمایش پرونده قطعه", list(choices))
        item = get_component(choices[selected], path=DB_PATH)
        if item:
            st.markdown(f"## `{item['part_number']}`")
            st.caption(f"{item['manufacturer']} · {item['category']} · {item.get('component_type','')}")
            show_validation(item["validation_status"])
            st.write(item["function_text"] or "توضیح عملکرد در بانک موجود نیست.")
            st.write("**کاربردهای متداول:** " + (item["common_applications"] or "ثبت نشده"))
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("#### محدوده کاری توصیه‌شده")
                st.json(item["recommended_operating"] or {"وضعیت": "در دیتابیس ثبت نشده؛ مقدار حدس زده نمی‌شود."})
            with c2:
                st.markdown("#### حداکثر مقادیر مطلق")
                st.json(item["absolute_max"] or {"وضعیت": "در دیتابیس ثبت نشده."})
            st.caption("Absolute Maximum Ratings شرایط عادی کار نیستند. شرایط آزمون هر عدد را همراه خود بخوانید.")
            if item["specs"]:
                with st.expander("مشخصات الکتریکی/کاربردی", expanded=True):
                    st.json(item["specs"])
            if item["pins"]:
                st.markdown("#### پایه‌ها")
                render_data_table(item["pins"], {"pin_number": "شماره", "pin_name": "نام", "function_text": "عملکرد", "electrical_role": "نقش", "conditions": "شرایط"})
            else:
                st.info("اطلاعات پایه‌ها در نسخه فعلی ثبت نشده است؛ از روی پکیج/مدل مشابه حدس نزنید.")
            st.markdown("#### منبع و بازبینی")
            for source in item["sources"]:
                show_validation(source["status"])
                st.markdown(f"**{source['title']}** · {source['publisher']} · {source.get('document_version') or ''}")
                st.caption(f"دسترسی/بازبینی: {source['accessed_on']} · بخش: {item['datasheet_section'] or 'نامشخص'}")
                st.link_button("بازکردن منبع رسمی (در صورت اتصال اینترنت)", source["url"])
            profile = get_diagnostic_profile(item["part_number"], path=DB_PATH)
            if profile:
                st.markdown("#### پروفایل شرط کاریِ منبع‌دار")
                show_validation(profile["validation_status"])
                st.write(profile["description"])
                st.write(f"**سیگنال‌های تطبیق‌پذیر:** {', '.join(profile['signal_aliases'])}")
                st.write(f"**نقطه/مرجع مستند:** {profile['pin_description']}")
                st.caption(
                    f"کلید بازه: {profile['operating_range_key']} · واحد مبنا: {profile['measurement_unit']} · "
                    f"منبع: {profile['source_title']} · {profile.get('document_version') or 'نسخه ثبت‌نشده'}"
                )
                st.caption("این پروفایل فقط شرط کاری را مقایسه می‌کند؛ به‌تنهایی خرابی یا سلامت قطعه را ثابت نمی‌کند.")
                if profile.get("source_url"):
                    st.link_button("بازکردن منبع پروفایل", profile["source_url"])
            st.caption(item["notes"])
    st.markdown("---")
    with st.expander("افزودن قطعه به‌عنوان نیازمند بررسی انسانی"):
        st.warning("ثبت این فرم قطعه را تأییدشده نمی‌کند. مقادیر الکتریکی را بدون ارجاع بررسی‌شده وارد نکنید.")
        with st.form("new_component_form"):
            part = st.text_input("شماره قطعه *")
            manufacturer = st.text_input("سازنده *")
            category = st.text_input("دسته‌بندی *")
            component_type = st.text_input("نوع")
            function_text = st.text_area("عملکرد (در صورت داشتن منبع)")
            package = st.text_input("پکیج")
            datasheet_url = st.text_input("پیوند منبع رسمی (اختیاری)")
            notes = st.text_area("منبع/اطلاعات تکمیلی و موارد نامعلوم")
            submit = st.form_submit_button("ثبت به‌صورت نیازمند بررسی")
        if submit:
            try:
                create_component({"part_number": part, "manufacturer": manufacturer, "category": category,
                                  "component_type": component_type, "function_text": function_text,
                                  "package": package, "datasheet_url": datasheet_url, "notes": notes,
                                  "validation_status": "needs_review"}, path=DB_PATH)
                st.success("قطعه ثبت شد؛ وضعیت آن «نیازمند بررسی انسانی» است.")
                st.rerun()
            except Exception as exc:
                st.error(f"ثبت قطعه انجام نشد: {exc}")


def render_circuit_knowledge() -> None:
    st.markdown("### مدارهای مرجع مستند")
    st.caption("این موارد نمونه‌های مستند از شماتیک/ساختار دیتاشیت قطعات مشخص‌اند، نه مقادیر عمومی برای هر برد.")
    topologies = list_topologies(path=DB_PATH)
    for item in topologies:
        with st.expander(f"{item['title']} · {item['category']}", expanded=False):
            show_validation(item["validation_status"])
            st.write(item["description"])
            st.markdown("**رفتار مورد انتظار:** " + item["expected_behavior"])
            st.markdown("**نقاط قابل بررسی فقط بر اساس نقشه واقعی:** " + "؛ ".join(item["measurement_points"]))
            st.warning(item["diagnostic_limits"])
            if item.get("source_url"):
                st.markdown(f"منبع: [{item.get('source_title')}]({item['source_url']})")
    st.markdown("#### شرایط/خرابی‌های مستند در سطح قطعه")
    with db_session(DB_PATH) as conn:
        failures = conn.execute(
            """SELECT f.*,s.title AS source_title,s.url AS source_url FROM failure_modes f
               LEFT JOIN sources s ON s.id=f.source_id ORDER BY f.failure_code"""
        ).fetchall()
    if not failures:
        st.info("هنوز خرابی مستندشده‌ای در بانک نیست.")
    for failure in failures:
        item = dict(failure)
        with st.container(border=True):
            st.markdown(f"**{item['title']}**")
            show_validation(item["validation_status"])
            st.write(item["summary"])
            st.caption("علل احتمالی/موارد برای بررسی: " + "؛ ".join(json.loads(item["causes_json"])))
            st.warning(item["limitations"])
            if item.get("source_url"):
                st.markdown(f"منبع: [{item['source_title']}]({item['source_url']})")


def render_rules() -> None:
    st.markdown("### موتور قانون‌محور")
    st.markdown('<div class="callout"><b>روش رتبه‌بندی:</b> در نسخه اول فقط قواعد صریح و مقایسه‌های شرطی اجرا می‌شوند. درصد احتمال تولید نمی‌شود. قوانین عمومی، مسیر آزمایش هستند و تا بازبینی تعمیرکار «نیازمند بررسی» می‌مانند.</div>', unsafe_allow_html=True)
    rules = list_rules(path=DB_PATH)
    st.metric("قواعد فعال در DB", sum(1 for r in rules if r["enabled"]))
    for rule in rules:
        with st.expander(f"{rule['title']} · {rule['category']}"):
            show_validation(rule["validation_status"])
            st.markdown(rule["explanation"])
            st.markdown("**علائم راه‌انداز:** " + "، ".join(SYMPTOM_LABELS.get(code, code) for code in rule["trigger_symptoms"]))
            test_catalog = get_test_catalog(path=DB_PATH)
            tests = rule["action"].get("tests", [])
            st.markdown("**آزمایش‌های پیشنهادی:** " + ("؛ ".join(test_catalog[code]["title"] for code in tests if code in test_catalog) or "ثبت نشده"))
    with st.expander("تعریف/ویرایش قانون برای توسعه‌دهنده"):
        st.code("data/diagnostic_rules/rules.json", language="text")
        st.caption("برای افزودن قانون: JSON را تغییر دهید، شروط/محدودیت/منبع را ثبت کنید، پایگاه را با `python tools/manage_data.py init` به‌روزرسانی و تست‌ها را اجرا کنید. بازبینی انسانی همچنان لازم است.")


def render_sources() -> None:
    st.markdown("### منابع فنی ثبت‌شده")
    query = st.text_input("جست‌وجو در عنوان، ناشر یا URL", key="source_query")
    sources = list_sources(query, path=DB_PATH)
    if not sources:
        st.info("منبعی پیدا نشد.")
        return
    render_data_table(sources, {"title": "عنوان", "publisher": "ناشر", "document_type": "نوع", "document_version": "نسخه", "accessed_on": "تاریخ دسترسی", "status": "اعتبار", "component_count": "قطعات مرتبط"})
    for source in sources:
        with st.expander(f"{source['publisher']} · {source['title']}"):
            show_validation(source["status"])
            st.markdown(f"**نسخه:** {source.get('document_version') or 'ثبت نشده'} · **تاریخ دسترسی:** {source['accessed_on']}")
            st.markdown(f"**نوع سند:** {source['document_type']}")
            st.write(source["notes"])
            st.code(source["url"], language="text")
            st.link_button("بازکردن سند رسمی (نیازمند اینترنت)", source["url"])


def export_database_bytes() -> bytes:
    tables = [
        "sources", "components", "component_datasheets", "component_pins", "circuit_topologies",
        "failure_modes", "diagnostic_tests", "diagnostic_rules", "repair_cases", "measurements",
        "repair_tests", "case_components", "component_relationships", "validation_records", "app_settings",
    ]
    payload = {"exported_at": datetime.now().astimezone().isoformat(), "format": "CIRCUIT AI JSON export v1", "tables": {}}
    with db_session(DB_PATH) as conn:
        for table in tables:
            payload["tables"][table] = [dict(row) for row in conn.execute(f"SELECT * FROM {table}").fetchall()]
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def render_database_manager() -> None:
    st.markdown("### وضعیت پایگاه داده محلی")
    st.code(str(DB_PATH), language="text")
    report = quality_report(path=DB_PATH)
    cols = st.columns(5)
    for col, (title, key) in zip(cols, [("پرونده‌ها", "cases"), ("قطعات", "components"), ("منابع", "sources"), ("مدارها", "topologies"), ("قواعد", "rules")]):
        with col:
            if key == "cases":
                with db_session(DB_PATH) as conn:
                    count = conn.execute("SELECT COUNT(*) FROM repair_cases WHERE is_archived=0").fetchone()[0]
            else:
                count = report[key]
            st.metric(title, count)
    st.markdown("#### کنترل کیفیت")
    st.json(report)
    with db_session(DB_PATH) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
    if integrity == "ok" and not foreign_key_errors:
        st.success("SQLite integrity_check: ok · کلیدهای خارجی: بدون خطا")
    else:
        st.error(f"سلامت پایگاه داده نیازمند بررسی است: {integrity}; FK errors={len(foreign_key_errors)}")
    st.markdown("#### پشتیبان‌گیری")
    default_dir = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "circuit-ai" / "backups"
    backup_dir_text = st.text_input("پوشه پشتیبان", value=str(default_dir))
    st.caption("فایل‌های پشتیبان قبلی بازنویسی نمی‌شوند. نسخه‌ها ممکن است حاوی اطلاعات تعمیر محرمانه باشند.")
    if st.button("ساخت نسخه پشتیبان SQLite", type="primary"):
        try:
            folder = Path(backup_dir_text).expanduser()
            folder.mkdir(parents=True, exist_ok=True)
            name = f"circuit-ai-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite3"
            target = create_backup(folder / name, source=DB_PATH)
            st.success(f"نسخه پشتیبان ساخته شد: {target}")
        except Exception as exc:
            st.error(f"ساخت پشتیبان ناموفق بود: {exc}")
    st.download_button("خروجی JSON از داده‌ها", data=export_database_bytes(), file_name=f"circuit-ai-export-{datetime.now().strftime('%Y%m%d')}.json", mime="application/json")
    st.markdown("#### بازیابی از فایل SQLite")
    st.warning("بازیابی، پایگاه فعلی را جایگزین می‌کند. پیش از آن، برنامه یک نسخه محافظتی کنار فایل فعلی می‌سازد. مسیر بازگردانی را پس از بازیابی کنترل کنید.")
    upload = st.file_uploader("فایل نسخه پشتیبان `.sqlite3`", type=["sqlite3", "db", "bak"], key="restore_file")
    confirmation = st.text_input("برای فعال‌کردن بازیابی، واژه RESTORE را دقیق وارد کنید", key="restore_confirm")
    if st.button("اعتبارسنجی و بازیابی فایل", disabled=(upload is None or confirmation != "RESTORE")):
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(prefix="circuit-ai-upload-", suffix=".sqlite3", delete=False) as handle:
                handle.write(upload.getvalue())
                temporary_path = Path(handle.name)
            restored = restore_backup(temporary_path, destination=DB_PATH)
            init_db(restored)
            st.session_state.pop("diagnosis_case_id", None)
            st.success(f"بازیابی کامل شد: {restored}. پایگاه قبلی (در صورت وجود) به‌عنوان نسخه before-restore حفظ شده است.")
            st.rerun()
        except Exception as exc:
            st.error(f"بازیابی انجام نشد: {exc}")
        finally:
            if temporary_path:
                temporary_path.unlink(missing_ok=True)
    st.markdown("#### سیاست حذف")
    st.info("پرونده تعمیر از رابط به‌صورت حذف نرم/بایگانی مدیریت می‌شود. پاک‌سازی دسته‌جمعی وجود ندارد تا اطلاعات ناخواسته حذف نشود.")


def render_settings() -> None:
    st.markdown("### ترجیحات و حریم خصوصی")
    st.caption("CIRCUIT AI در این نسخه هیچ API، مدل زبانی یا سرویس ابری را فراخوانی نمی‌کند.")
    with st.form("settings_form"):
        theme = st.radio("تم رابط", ["dark", "light"], index=0 if st.session_state["_theme"] == "dark" else 1,
                         format_func=lambda x: "تیره مهندسی" if x == "dark" else "روشن", horizontal=True)
        submit = st.form_submit_button("ذخیره تنظیمات")
    if submit:
        set_setting("theme", theme, path=DB_PATH)
        st.session_state["_theme"] = theme
        st.success("تنظیمات ذخیره شد.")
        st.rerun()
    st.markdown("#### مسیرها و رفتار آفلاین")
    st.markdown(f"- پایگاه داده: `{DB_PATH}`")
    st.markdown("- مسیر پیش‌فرض لینوکس: `~/.local/share/circuit-ai/circuit_ai.sqlite3` (یا `$XDG_DATA_HOME/circuit-ai/`).")
    st.markdown("- دسترسی وب فقط با بازکردن پیوند منبع یا اجرای ابزار جمع‌آوری با گزینه صریح دانلود انجام می‌شود؛ برنامه تعمیرات را به خارج ارسال نمی‌کند.")
    st.markdown("- اجرای محلی به‌طور پیش‌فرض روی `127.0.0.1` انجام می‌شود.")
    st.markdown("#### درباره موتور")
    st.write("قواعد و محاسبات در Python/SQLite اجرا می‌شوند. مدل یادگیری ماشین و RAG عمداً به نسخه نخست افزوده نشده‌اند؛ مجموعه تعمیرات تأییدشده هنوز برای آموزش مدل کافی نیست.")
    st.write("رکوردهای قطعه در بانک اولیه از دیتاشیت رسمی بررسی شده‌اند؛ این وضعیت آزمایش فیزیکی قطعه یا تعمیر برد را معنی نمی‌دهد.")


# Navigation is intentionally a single local Streamlit application; no external API is required.
with st.sidebar:
    st.markdown(f'''<div class="brand"><div class="brand-mark">ϟ</div><div><div class="brand-name">{esc(APP_NAME)}</div><div class="brand-sub">{esc(APP_TAGLINE)}</div></div></div>''', unsafe_allow_html=True)
    st.markdown("<div class='muted small'>محیط مهندسی · نسخه محلی</div>", unsafe_allow_html=True)
    page = st.radio("بخش‌ها", PAGES, key="page_nav", label_visibility="collapsed")
    st.markdown("---")
    st.markdown("<span class='status-pill'>● پایگاه داده محلی</span>", unsafe_allow_html=True)
    st.caption("بدون API پولی · آماده کار آفلاین")

render_topbar(page)
if page == "داشبورد":
    render_dashboard()
elif page == "عیب‌یابی جدید":
    render_diagnosis_page()
elif page == "پرونده‌های تعمیر":
    render_history()
elif page == "بانک قطعات":
    render_components()
elif page == "دانش مدارها":
    render_circuit_knowledge()
elif page == "قواعد عیب‌یابی":
    render_rules()
elif page == "منابع فنی":
    render_sources()
elif page == "مدیریت پایگاه داده":
    render_database_manager()
elif page == "محاسبات مهندسی":
    render_calculators()
elif page == "تنظیمات":
    render_settings()
