"""Conservative deterministic diagnostic triage with provenance and no fake certainty."""
from __future__ import annotations

import math
from typing import Any

from core.confidence import evidence_quality
from core.electrical_calculations import compare_to_reference
from core.rules_engine import match_rules
from services.component_service import get_component, get_diagnostic_profile
from services.knowledge_service import list_failure_modes
from services.repair_service import SYMPTOM_LABELS


class DiagnosticInputError(ValueError):
    pass


SAFETY_NOTES = [
    "این خروجی مسیر بررسی است، نه تشخیص قطعی و نه جایگزین شماتیک/دیتاشیت برد واقعی.",
    "اندازه‌گیری روشن را از تست بی‌برق جدا کنید. برای تست مقاومت، منبع‌ها باید جدا و بی‌برقی/تخلیه خازن طبق روش ایمن همان مدار تأیید شده باشد؛ خازن را با اتصال کوتاه مستقیم تخلیه نکنید.",
    "بردهای متصل به برق شهر، باس DC، اینورتر و جریان بالا فقط برای فرد واجد صلاحیت با ابزار و حفاظت مناسب هستند. مقدار ولتاژ، جریان و نقطه تست را حدس نزنید.",
    "در این نسخه هیچ تزریق جریان یا اتصال کوتاه آزمایشی پیشنهاد نمی‌شود؛ مقدار نامشخص/بدون منبع به‌عنوان نامعلوم باقی می‌ماند.",
]


def _key(value: Any) -> str:
    text = str(value).strip().casefold().replace("−", "-")
    return "".join(ch for ch in text if ch.isalnum())


def _to_volts(value: float, unit: str) -> float | None:
    number = float(value)
    normalized = unit.strip().casefold()
    if normalized in {"v", "volt", "volts"}:
        return number
    if normalized in {"mv", "millivolt", "millivolts"}:
        return number / 1000.0
    return None


def _measurement_matches(measurement: dict[str, Any], aliases: set[str]) -> bool:
    name = _key(measurement.get("signal", ""))
    canonical_aliases = {_key(alias) for alias in aliases}
    return name in canonical_aliases


def _compare_user_measurements(measurements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    observations = []
    for item in measurements:
        if item.get("expected_value") is None:
            continue
        tolerance = item.get("tolerance_percent")
        comparison = compare_to_reference(
            item["measured_value"], item["expected_value"], tolerance
        )
        within = comparison.get("within_tolerance")
        if within is True:
            observation = "داخل تلرانس اعلام‌شده توسط کاربر"
        elif within is False:
            observation = "خارج از تلرانس اعلام‌شده توسط کاربر"
        else:
            observation = "اختلاف عددی ثبت شد؛ بدون تلرانس/شرایط مرجع نمی‌توان انطباق را تعیین کرد"
        observations.append({
            "kind": "user_reference_comparison",
            "title": f"مقایسه {item.get('signal', 'اندازه‌گیری')} با مرجع واردشده",
            "measured_value": comparison["measured"],
            "expected_value": comparison["expected"],
            "unit": item.get("unit", ""),
            "difference": comparison["difference"],
            "tolerance_percent": comparison.get("tolerance_percent"),
            "within_tolerance": within,
            "interpretation": observation,
            "reference_source": item.get("expected_source") or "منبع مرجع در پرونده مشخص نشده است",
            "not_a_cause": True,
        })
    return observations


def _case_measurements(case: dict[str, Any]) -> list[dict[str, Any]]:
    measurements = case.get("measurements", [])
    if not isinstance(measurements, list):
        raise DiagnosticInputError("اندازه‌گیری‌ها باید فهرست باشند.")
    normalized = []
    for item in measurements:
        try:
            value = float(item["measured_value"])
        except (KeyError, TypeError, ValueError) as exc:
            raise DiagnosticInputError("اندازه‌گیری دارای مقدار نامعتبر است.") from exc
        if not math.isfinite(value):
            raise DiagnosticInputError("اندازه‌گیری باید عدد محدود باشد.")
        normalized.append({**item, "measured_value": value})
    return normalized


def _specific_component_checks(case: dict[str, Any], measurements: list[dict[str, Any]], *, path=None):
    component_name = str(case.get("reference_component", "")).strip()
    if not component_name:
        return [], [], []
    component = get_component(component_name, path=path)
    if not component:
        return [], [f"قطعهٔ مرجع «{component_name}» در بانک محلی پیدا نشد؛ بررسی اختصاصی دیتاشیت اجرا نشد."], []
    if component["validation_status"] not in {"official_datasheet_reviewed", "verified_multiple_sources"}:
        return [], [f"اطلاعات {component_name} در وضعیت «نیازمند بررسی» است؛ از آن برای مقایسه عددی خودکار استفاده نشد."], []
    profile = get_diagnostic_profile(component["part_number"], path=path)
    if not profile:
        return [], [f"برای {component_name} پروفایل مستند اندازه‌گیری ثبت نشده است؛ هیچ حدی حدس زده نشد."], []
    if profile["validation_status"] not in {"official_datasheet_reviewed", "verified_multiple_sources"} or profile.get("source_status") != "official_datasheet_reviewed":
        return [], [f"پروفایل اندازه‌گیری {component_name} هنوز با دیتاشیت رسمی قابل استفاده تأیید نشده است."], []
    range_key = profile["operating_range_key"]
    aliases = set(profile["signal_aliases"])
    spec = component.get("recommended_operating", {}).get(range_key)
    if not spec:
        return [], [f"محدوده کاری توصیه‌شده {range_key} برای {component_name} در بانک ثبت نشده است."], []
    try:
        lower, upper = float(spec["min"]), float(spec["max"])
    except (KeyError, TypeError, ValueError):
        return [], [f"حداقل/حداکثر عددی بازه {range_key} برای {component_name} کامل نیست؛ هیچ نتیجه مقایسه‌ای صادر نشد."], []
    if not math.isfinite(lower) or not math.isfinite(upper) or lower > upper:
        return [], [f"محدوده عددی {range_key} برای {component_name} معتبر نیست؛ هیچ نتیجه مقایسه‌ای صادر نشد."], []
    if profile.get("measurement_unit") != "V":
        return [], [f"واحد مبنا «{profile.get('measurement_unit')}» در پروفایل {component_name} پشتیبانی نمی‌شود؛ مقایسه خودکار اجرا نشد."], []
    source = {
        "title": profile.get("source_title"), "publisher": profile.get("publisher"),
        "url": profile.get("source_url"), "document_version": profile.get("document_version"),
        "status": profile.get("source_status"), "datasheet_section": component.get("datasheet_section"),
    }
    profile_limitations = "؛ ".join(
        part for part in (profile.get("description"), spec.get("conditions"), profile.get("notes")) if part
    ) or "شرایط و محدودیت‌های دیتاشیت را بررسی کنید."
    matched = next((m for m in measurements if _measurement_matches(m, aliases)), None)
    if matched is None:
        test = {
            "test_code": "T_VERIFY_COMPONENT_SUPPLY",
            "title": f"تطبیق تغذیه {component['part_number']} با دیتاشیت",
            "purpose": "پس از شناسایی دقیق قطعه، اندازه‌گیری واقعی را در نقطه/پایه تغذیه و مرجع زمین همان شماتیک ثبت کنید.",
            "steps": [
                f"مارکینگ کامل قطعه را بررسی کنید. نقطه/پایه مستند: {profile['pin_description']}",
                "محدوده مورد استفاده در این بررسی از Recommended Operating Conditions است؛ نه Absolute Maximum Ratings.",
                "ولتاژ را در نقطه واقعی و با مرجع زمین صحیح و در شرایط بار ثبت کنید.",
                "در صورت خطر برق شهر/باس DC/خازن، آزمون فقط توسط فرد واجد صلاحیت و با تجهیزات مناسب انجام شود.",
            ],
            "measurement_state": "board_dependent",
            "risk_level": "board_dependent",
            "prerequisites": ["شماره قطعه دقیق", "نقشه و مرجع زمین", "سطح خطر/صلاحیت و ابزار مناسب"],
            "limitations": "فقط یک بررسی شرط کاری است؛ اندازه‌گیری داخل بازه یا خارج آن، به‌تنهایی سلامت/خرابی قطعه را اثبات نمی‌کند.",
            "source_title": source["title"], "source_url": source["url"],
            "source_section": source["datasheet_section"], "validation_status": profile["validation_status"],
        }
        return [], [], [test]

    volts = _to_volts(matched["measured_value"], matched.get("unit", ""))
    if volts is None:
        return [], [f"واحد اندازه‌گیری «{matched.get('unit')}» برای مقایسه بازه ولتاژ پشتیبانی نمی‌شود؛ فقط V یا mV پذیرفته شد."], []
    if matched.get("measurement_state") != "powered":
        return [], ["برای مقایسه با محدوده کاری، اندازه‌گیری باید با وضعیت «برق‌دار» و در نقطه/مرجع مشخص ثبت شود؛ مقدار با وضعیت نامشخص/خاموش تفسیر نشد."], []
    outside = volts < lower or volts > upper
    label = "خارج از محدوده کاری توصیه‌شده ثبت‌شده" if outside else "داخل بازه عددی کاری توصیه‌شده ثبت‌شده"
    candidate = {
        "code": f"operating_range_{component['part_number'].upper()}",
        "title": f"شرط کاری {component['part_number']} · {range_key}: {label}",
        "type": "documented_operating_condition",
        "priority_label": "بررسی مقدم به‌عنوان شرط کاری" if outside else "با این بررسی فعلاً اولویت پایین‌تر",
        "rank_reason": "رتبه فقط برای ترتیب بررسی شرط کاری است؛ احتمال خرابی/درصد اطمینان محاسبه نشده است.",
        "evidence_for": [
            f"اندازه‌گیری ثبت‌شده: {matched['signal']} = {matched['measured_value']} {matched['unit']} در وضعیت {matched.get('measurement_state','unknown')}.",
            f"نقطه مستند: {profile['pin_description']}",
            f"دیتاشیت {component['part_number']} محدوده کاری توصیه‌شده {lower} تا {upper} V را برای {range_key} مشخص می‌کند."
        ] if outside else [
            f"اندازه‌گیری ثبت‌شده: {matched['signal']} = {matched['measured_value']} {matched['unit']}.",
            f"این مقدار با بازه توصیه‌شده {lower} تا {upper} V مقایسه شد."
        ],
        "evidence_against": [
            "این شرط به‌تنهایی خرابی قطعه را ثابت نمی‌کند.",
            "شماره کامل/نسخه قطعه، مرجع زمین، دقت ابزار و نقطه اندازه‌گیری ممکن است با فرض سیستم متفاوت باشد.",
            "Absolute Maximum Ratings با محدوده کار توصیه‌شده یکسان نیست."
        ],
        "source": source,
        "validation_status": profile["validation_status"],
        "diagnostic_limit": profile_limitations,
    }
    if outside:
        return [candidate], [], []
    return [], [candidate["title"] + "; این مشاهده عملکرد کامل یا سالم بودن قطعه را اثبات نمی‌کند."], []


def diagnose(case: dict[str, Any], *, path=None) -> dict[str, Any]:
    """Run deterministic, traceable triage. No statistical confidence is generated."""
    symptoms = case.get("symptoms", [])
    if not isinstance(symptoms, list) or any(code not in SYMPTOM_LABELS for code in symptoms):
        raise DiagnosticInputError("علائم باید فهرستی از کدهای معتبر باشند.")
    measurements = _case_measurements(case)
    rules = match_rules(symptoms, measurements=measurements, tests=case.get("tests", []), path=path)
    observations = _compare_user_measurements(measurements)
    hypotheses, component_warnings, component_tests = _specific_component_checks(case, measurements, path=path)
    # Conditional rules: fire only when their recorded facts all hold.
    for item in rules.get("conditional_hypotheses", []):
        hypotheses.append({
            "code": item["code"],
            "title": item["title"],
            "type": "conditional_rule_hypothesis",
            "priority_label": item.get("priority_label", "قابل بررسی"),
            "rank_reason": f"قاعده شرطی {item['rule_code']} با داده‌های ثبت‌شده برقرار شد؛ ترتیب، اولویت بررسی است نه احتمال خرابی.",
            "evidence_for": list(item.get("evidence_for", [])),
            "evidence_against": list(item.get("against", [])) or ["این فرضیه به‌تنهایی خرابی قطعه مشخصی را ثابت نمی‌کند."],
            "source": None,
            "diagnostic_limit": "فرضیه مسیر بررسی است؛ با آزمایش بعدی و شماتیک/دیتاشیت همان برد باید تأیید یا رد شود.",
            "_rule_priority": item.get("rule_priority", 100),
        })
    hypotheses.sort(key=lambda h: h.get("_rule_priority", 5 if h.get("type") == "documented_operating_condition" else 100))
    for h in hypotheses:
        h.pop("_rule_priority", None)

    # A recorded qualitative experiment can reorder a related condition, but cannot confirm a failed IC.
    test_findings = []
    for test in case.get("tests", []):
        if test.get("test_code") == "T_VERIFY_COMPONENT_SUPPLY":
            result = test.get("result")
            if result not in {"supports", "contradicts", "inconclusive", "not_performed"}:
                continue
            test_findings.append({
                "title": test.get("test_title", "آزمایش تغذیه قطعه"),
                "result": result,
                "interpretation": {
                    "supports": "کاربر این آزمایش را موافق فرضیه شرط تغذیه علامت‌گذاری کرده است؛ صحت مقدار/روش به ثبت و بازبینی وابسته است.",
                    "contradicts": "کاربر این آزمایش را مخالف فرضیه شرط تغذیه علامت‌گذاری کرده است؛ داده متناقض/بازبینی لازم است.",
                    "inconclusive": "آزمایش قطعی نبود.",
                    "not_performed": "آزمایش هنوز انجام نشده است.",
                }[result],
                "notes": test.get("notes", ""),
                "does_not_prove_component_failure": True,
            })
            for hypothesis in hypotheses:
                if result == "supports":
                    hypothesis["priority_label"] = "بررسی مقدم؛ با نتیجه ثبت‌شده همسو است"
                    hypothesis["evidence_for"].append("نتیجه آزمایش مرتبط توسط کاربر به‌عنوان موافق ثبت شد؛ تفسیر نهایی نیازمند بررسی است.")
                elif result == "contradicts":
                    hypothesis["priority_label"] = "اولویت کاهش‌یافته؛ نتیجه ثبت‌شده با آن ناسازگار است"
                    hypothesis["evidence_against"].append("نتیجه آزمایش مرتبط توسط کاربر به‌عنوان مخالف ثبت شد؛ مقدارها/شرایط باید بازبینی شوند.")
                else:
                    hypothesis["priority_label"] = "بررسی نامشخص؛ آزمایش نتیجه قطعی نداد"
        elif test.get("result") in {"supports", "contradicts", "inconclusive", "not_performed"}:
            test_findings.append({
                "title": test.get("test_title", test.get("test_code", "آزمایش ثبت‌شده")),
                "result": test.get("result"),
                "interpretation": "نتیجه کیفی کاربر ثبت شد؛ چون این قاعده عمومی علت مشخصی را مدل نمی‌کند، از آن احتمال خرابی ساخته نمی‌شود.",
                "notes": test.get("notes", ""),
                "does_not_prove_component_failure": True,
            })

    # Extract only recorded observations; never invent thresholds or infer a cause from a zero alone.
    for measurement in measurements:
        name = _key(measurement.get("signal", ""))
        if name in {_key(x) for x in ("input_voltage", "board_input", "board_input_voltage", "vin", "v_in")}:
            observations.append({
                "kind": "measurement_record",
                "title": "اندازه‌گیری ورودی ثبت‌شده",
                "measured_value": measurement["measured_value"],
                "unit": measurement.get("unit", ""),
                "conditions": measurement.get("conditions", ""),
                "interpretation": "این مقدار فقط مربوط به نقطه/شرایط ثبت‌شده است؛ بدون مشخصات برد و مرجع، نتیجه علّی گرفته نمی‌شود.",
                "not_a_cause": True,
            })

    missing = []
    if not measurements:
        missing.append("حداقل یک اندازه‌گیری واقعی با نام نقطه، واحد، وضعیت روشن/خاموش و شرایط لازم است.")
    if "no_power" in symptoms and not any(_key(m.get("signal", "")) in {_key(x) for x in ("input_voltage", "board_input", "board_input_voltage", "vin", "v_in")} for m in measurements):
        missing.append("ولتاژ ورودی را فقط پس از تعیین مقدار نامی از روی برچسب/شماتیک و نقطه مرجع واقعی ثبت کنید؛ سیستم مقدار ورودی برد را حدس نمی‌زند.")
    if "wrong_voltage" in symptoms or "no_output" in symptoms:
        if not any(m.get("expected_value") is not None for m in measurements):
            missing.append("مقدار خروجی مورد انتظار و منبع آن (شماتیک/دیتاشیت همان برد) ثبت نشده است.")
        elif not any(m.get("tolerance_percent") is not None for m in measurements if m.get("expected_value") is not None):
            missing.append("برای حکم انطباق، تلرانس/شرایط آزمون منبع مرجع نیز لازم است؛ مقایسه فعلاً صرفاً عددی است.")
    if "no_communication" in symptoms:
        missing.append("نوع رابط، شماره قطعه رابط، پایه‌ها و سطح ولتاژ I/O از نقشه/دیتاشیت همان برد لازم است.")
    if "resets" in symptoms:
        missing.append("برای تفکیک افت تغذیه/Reset/Clock، مدل دقیق میکروکنترلر و داده موج/شرایط زمانی لازم است.")
    if "short_reported" in symptoms:
        missing.append("محل ریل و روش بی‌برق/تخلیه ایمن را مشخص کنید؛ مقدار مقاومت بدون مدل/مرجع مدار به‌تنهایی معیار عمومی نیست.")

    next_tests = rules["tests"] + component_tests
    # Preserve order and avoid duplicate test cards.
    seen = set()
    unique_tests = []
    for test in next_tests:
        code = test.get("test_code")
        if code not in seen:
            seen.add(code)
            unique_tests.append(test)

    for hypothesis in hypotheses:
        hypothesis["evidence_quality"] = evidence_quality(
            direct_measurement=True,
            official_source=bool(hypothesis.get("source") and hypothesis["source"].get("status") == "official_datasheet_reviewed"),
            exact_component_match=True,
            conflicting_evidence=any(x.get("test_code") == "T_VERIFY_COMPONENT_SUPPLY" and x.get("result") == "contradicts" for x in case.get("tests", [])),
        )

    if hypotheses:
        status = "analysis_available_not_a_diagnosis"
    elif observations or unique_tests:
        status = "triage_only_insufficient_for_cause"
    else:
        status = "insufficient_data"

    return {
        "status": status,
        "status_fa": {
            "analysis_available_not_a_diagnosis": "یک شرط/فرضیه قابل بررسی پیدا شد؛ تشخیص خرابی نیست",
            "triage_only_insufficient_for_cause": "مسیر عیب‌یابی آماده است؛ علت قابل تعیین نیست",
            "insufficient_data": "اطلاعات کافی برای تحلیل وجود ندارد",
        }[status],
        "symptoms": [{"code": code, "label": SYMPTOM_LABELS[code]} for code in symptoms],
        "observations": observations,
        "ranked_hypotheses": hypotheses,
        "next_tests": unique_tests,
        "matched_rules": [
            {"code": rule["rule_code"], "title": rule["title"], "validation_status": rule["validation_status"],
             "explanation": rule["explanation"]}
            for rule in rules["rules"]
        ],
        "test_findings": test_findings,
        "documented_failure_modes": list_failure_modes(symptoms, path=path),
        "missing_information": list(dict.fromkeys(missing)),
        "warnings": SAFETY_NOTES + component_warnings,
        "method": "قواعد صریح علائم + مقایسه عددی فقط با مرجع/تلرانس واردشده + محدوده کاری مستند فقط برای شماره قطعه شناخته‌شده. هیچ مدل آماری یا درصد اطمینانی استفاده نشده است.",
        "generated_from": {
            "rule_codes": [rule["rule_code"] for rule in rules["rules"]],
            "component_reference": case.get("reference_component", ""),
            "measurement_count": len(measurements),
            "test_result_count": len(case.get("tests", [])),
        },
    }
