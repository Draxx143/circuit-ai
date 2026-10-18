"""Reusable small UI helpers. All user-supplied text is escaped before HTML rendering."""
from __future__ import annotations

import html

STATUS_LABELS = {
    "official_datasheet_reviewed": "بررسی‌شده با دیتاشیت رسمی",
    "official_product_page_reviewed": "صفحه رسمی بررسی‌شده",
    "verified_multiple_sources": "تطبیق با چند منبع",
    "needs_review": "نیازمند بررسی انسانی",
    "conflicting": "منابع متناقض",
    "experimental": "تجربی",
    "lab_tested": "تأیید آزمایش عملی",
    "unverified": "تأییدنشده",
    "verified": "تأییدشده",
    "rejected": "ردشده",
    "open": "باز",
    "completed": "تکمیل‌شده",
}


def badge(text: str, kind: str = "info") -> str:
    safe = html.escape(str(text))
    css_class = {"ok": "badge ok", "warn": "badge warn", "danger": "badge danger", "info": "badge info"}.get(kind, "badge info")
    return f'<span class="{css_class}">{safe}</span>'


def esc(value) -> str:
    return html.escape("—" if value is None or value == "" else str(value))


def validation_label(status: str) -> str:
    return STATUS_LABELS.get(status, status or "نامشخص")
