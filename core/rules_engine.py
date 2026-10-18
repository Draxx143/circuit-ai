"""Data-driven symptom routing + *conditional* rules evaluated on real measurements.

Rules live in SQLite/JSON, not the UI. A conditional rule only fires when every
fact in its ``condition.all`` list is satisfied by recorded data (symptoms,
measurements, test results). Facts never invent thresholds: ``zero`` means the
recorded value is exactly 0 in its converted unit, and ``expected_outside``
only fires when the user supplied both a reference value and a tolerance.
"""
from __future__ import annotations

from typing import Any

from services.knowledge_service import get_test_catalog, list_rules

# Signal-name aliases used only to *classify* a user-recorded measurement point.
# They say nothing about what value that point should have.
SIGNAL_GROUPS: dict[str, set[str]] = {
    "input": {"vin", "v_in", "input_voltage", "board_input", "board_input_voltage", "input"},
    "output": {"vout", "v_out", "output_voltage", "output", "rail_output"},
    "mcu_supply": {"vdd", "vcc", "mcu_vdd", "vdd_mcu", "supply_rail", "rail"},
    "reset": {"reset", "nreset", "nrst", "rst"},
    "clock": {"clock", "clk", "xtal", "oscillator", "osc"},
    "motor_supply": {"vm", "vma", "vmb", "motor_supply", "motor_supply_voltage"},
    "rail_resistance": {"rail_resistance", "resistance_to_gnd", "rail_to_gnd", "rail_resistance_to_ground"},
}


def _key(value: Any) -> str:
    text = str(value).strip().casefold().replace("−", "-")
    return "".join(ch for ch in text if ch.isalnum())


def _to_base(value: float, unit: str) -> float | None:
    """Convert V/mV and Ω/kΩ/MΩ to their base unit; None for anything else."""
    u = str(unit).strip().casefold()
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if u in {"v", "volt", "volts", "ω", "ohm", "ohms", "Ω".casefold()}:
        return n
    if u in {"mv", "millivolt", "millivolts"}:
        return n / 1000.0
    if u in {"kω", "kohm", "kohms", "kΩ".casefold()}:
        return n * 1000.0
    if u in {"mω", "mohm", "mΩ".casefold()}:
        return n * 1_000_000.0
    return None


def group_of(measurement: dict[str, Any]) -> str | None:
    name = _key(measurement.get("signal", ""))
    for group, aliases in SIGNAL_GROUPS.items():
        if name in {_key(a) for a in aliases}:
            return group
    return None


def build_context(symptoms, measurements, tests) -> dict[str, Any]:
    by_group: dict[str, list[dict[str, Any]]] = {}
    for item in measurements or []:
        group = group_of(item)
        if group:
            by_group.setdefault(group, []).append(item)
    return {
        "symptoms": set(symptoms or []),
        "measurements": measurements or [],
        "by_group": by_group,
        "tests": {t.get("test_code"): t.get("result") for t in (tests or [])},
    }


def _fact_evidence(fact: dict[str, Any], ctx: dict[str, Any]) -> str | None:
    """Return an evidence sentence if the fact holds, else None."""
    kind = fact.get("fact")
    if kind == "symptom":
        code = fact.get("code")
        return f"علامت ثبت‌شده: {code}" if code in ctx["symptoms"] else None
    if kind == "test_result":
        got = ctx["tests"].get(fact.get("test_code"))
        return f"نتیجه آزمایش {fact.get('test_code')}: {got}" if got == fact.get("result") else None

    group = fact.get("group")
    items = ctx["by_group"].get(group, [])
    if kind == "measurement_present":
        if items:
            m = items[0]
            return f"اندازه‌گیری {m.get('signal')} = {m.get('measured_value')} {m.get('unit', '')} ثبت شده است."
        return None
    if kind == "measurement_absent":
        return f"برای گروه «{group}» هنوز اندازه‌گیری ثبت نشده است." if not items else None
    if not items:
        return None
    m = items[0]
    base = _to_base(m.get("measured_value"), m.get("unit", ""))
    if kind == "measurement_zero":
        if base == 0 and m.get("measurement_state") == fact.get("state", "powered"):
            return f"{m.get('signal')} در وضعیت برق‌دار دقیقاً ۰ ثبت شده است ({m.get('measured_value')} {m.get('unit', '')})."
        return None
    if kind == "measurement_nonzero":
        if base not in (None, 0) and m.get("measurement_state") == fact.get("state", "powered"):
            return f"{m.get('signal')} در وضعیت برق‌دار غیرصفر ثبت شده است: {m.get('measured_value')} {m.get('unit', '')}."
        return None
    if kind == "measurement_state":
        if m.get("measurement_state") == fact.get("state"):
            return f"وضعیت اندازه‌گیری {m.get('signal')}: {fact.get('state')}."
        return None
    if kind == "expected_outside":
        for item in items:
            if item.get("expected_value") is None or item.get("tolerance_percent") is None:
                continue
            expected, tol = float(item["expected_value"]), float(item["tolerance_percent"])
            if expected == 0:
                continue
            if abs(float(item["measured_value"]) - expected) > abs(expected) * tol / 100.0:
                return (f"{item.get('signal')} = {item.get('measured_value')} {item.get('unit', '')} "
                        f"خارج از تلرانس ±{tol}٪ مرجع کاربر ({expected}) است؛ منبع مرجع: "
                        f"{item.get('expected_source') or 'ثبت نشده'}.")
        return None
    return None


def evaluate_condition(condition: dict[str, Any], ctx: dict[str, Any]) -> list[str] | None:
    """Return the evidence list when all facts hold, otherwise None."""
    facts = (condition or {}).get("all")
    if not facts:
        return []  # unconditional triage rule
    evidence = []
    for fact in facts:
        sentence = _fact_evidence(fact, ctx)
        if sentence is None:
            return None
        evidence.append(sentence)
    return evidence


def match_rules(symptoms: list[str], *, measurements=None, tests=None, path=None) -> dict[str, Any]:
    ctx = build_context(symptoms, measurements or [], tests or [])
    selected = set(symptoms)
    matches, conditional, test_codes = [], [], []
    for rule in list_rules(path=path):
        if not rule["enabled"]:
            continue
        if not (set(rule.get("trigger_symptoms", [])) & selected):
            continue
        evidence = evaluate_condition(rule.get("conditions", {}), ctx)
        if evidence is None:
            continue
        matches.append(rule)
        action = rule.get("action", {})
        hypothesis = action.get("hypothesis")
        if hypothesis:
            conditional.append({**hypothesis, "rule_code": rule["rule_code"],
                                "rule_priority": rule.get("priority", 100),
                                "evidence_for": evidence,
                                "validation_status": rule.get("validation_status")})
        for code in action.get("tests", []):
            if code not in test_codes:
                test_codes.append(code)
    conditional.sort(key=lambda h: h["rule_priority"])
    catalog = get_test_catalog(path=path)
    return {
        "rules": matches,
        "conditional_hypotheses": conditional,
        "tests": [catalog[code] for code in test_codes if code in catalog],
        "unresolved_test_codes": [code for code in test_codes if code not in catalog],
    }
