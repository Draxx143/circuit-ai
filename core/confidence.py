"""Transparent evidence-quality labels. This module deliberately emits no probabilities."""
from __future__ import annotations


def evidence_quality(*, direct_measurement: bool, official_source: bool,
                     exact_component_match: bool, conflicting_evidence: bool = False) -> dict[str, str | None]:
    """Return an explainable evidence label, not a numerical confidence estimate."""
    if conflicting_evidence:
        label = "شواهد متناقض؛ نیازمند بازبینی"
    elif direct_measurement and official_source and exact_component_match:
        label = "اندازه‌گیری ثبت‌شده + تطبیق با دیتاشیت رسمی همان قطعه"
    elif direct_measurement:
        label = "اندازه‌گیری ثبت‌شده؛ مرجع فنی/مدل قطعه کامل نیست"
    elif official_source and exact_component_match:
        label = "شرط دیتاشیت در دسترس است؛ اندازه‌گیری واقعی موجود نیست"
    else:
        label = "اطلاعات کافی برای ارزیابی شواهد وجود ندارد"
    return {
        "label": label,
        "method": "برچسب کیفی بر پایه وجود اندازه‌گیری، تطبیق شماره قطعه و وضعیت منبع؛ نه احتمال آماری.",
        "confidence_percent": None,
    }
