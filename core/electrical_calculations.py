"""Small, explicit engineering calculations with validation and stated limits."""
from __future__ import annotations

import math
from typing import Iterable


class CalculationError(ValueError):
    """Invalid or physically undefined input for a calculation."""


def _number(value: float, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise CalculationError(f"{name} باید عددی باشد.") from exc
    if not math.isfinite(number):
        raise CalculationError(f"{name} باید عدد محدود باشد.")
    return number


def ohms_current(voltage_v: float, resistance_ohm: float) -> float:
    """Return I=V/R. This ideal DC calculation ignores source/lead impedance."""
    v, r = _number(voltage_v, "ولتاژ"), _number(resistance_ohm, "مقاومت")
    if r == 0:
        raise CalculationError("تقسیم بر مقاومت صفر تعریف نشده است.")
    return v / r


def power_vi(voltage_v: float, current_a: float) -> float:
    """Return electrical power P=V*I using signed values as entered."""
    return _number(voltage_v, "ولتاژ") * _number(current_a, "جریان")


def voltage_divider(vin_v: float, r_top_ohm: float, r_bottom_ohm: float) -> float:
    """Ideal unloaded two-resistor divider; does not model source/load effects."""
    vin = _number(vin_v, "ولتاژ ورودی")
    r1, r2 = _number(r_top_ohm, "مقاومت بالا"), _number(r_bottom_ohm, "مقاومت پایین")
    if r1 < 0 or r2 < 0 or r1 + r2 == 0:
        raise CalculationError("مقاومت‌ها باید نامنفی باشند و مجموع آن‌ها صفر نباشد.")
    return vin * r2 / (r1 + r2)


def series_resistance(*resistances_ohm: float) -> float:
    values = [_number(x, "مقاومت") for x in resistances_ohm]
    if not values:
        raise CalculationError("حداقل یک مقاومت لازم است.")
    if any(x < 0 for x in values):
        raise CalculationError("مقاومت منفی پذیرفته نیست.")
    return sum(values)


def parallel_resistance(*resistances_ohm: float) -> float:
    """Parallel equivalent. A zero-ohm branch gives zero equivalent resistance."""
    values = [_number(x, "مقاومت") for x in resistances_ohm]
    if not values:
        raise CalculationError("حداقل یک مقاومت لازم است.")
    if any(x < 0 for x in values):
        raise CalculationError("مقاومت منفی پذیرفته نیست.")
    if any(x == 0 for x in values):
        return 0.0
    return 1.0 / sum(1.0 / x for x in values)


def rc_time_constant(resistance_ohm: float, capacitance_f: float) -> float:
    """Return tau=R*C; does not predict a loaded/non-first-order circuit."""
    r, c = _number(resistance_ohm, "مقاومت"), _number(capacitance_f, "ظرفیت")
    if r < 0 or c < 0:
        raise CalculationError("مقاومت و ظرفیت باید نامنفی باشند.")
    return r * c


def capacitor_energy(capacitance_f: float, voltage_v: float) -> float:
    """Return stored energy E=1/2*C*V^2 in joules (not a discharge instruction)."""
    c, v = _number(capacitance_f, "ظرفیت"), _number(voltage_v, "ولتاژ")
    if c < 0:
        raise CalculationError("ظرفیت باید نامنفی باشد.")
    return 0.5 * c * v * v


def diode_power(forward_voltage_v: float, current_a: float) -> float:
    """Approximate instantaneous DC dissipation P=Vf*I under entered conditions."""
    vf, current = _number(forward_voltage_v, "افت دیود"), _number(current_a, "جریان")
    if vf < 0 or current < 0:
        raise CalculationError("افت و جریان در این محاسبه باید نامنفی باشند.")
    return vf * current


def voltage_drop_percent(measured_v: float, reference_v: float) -> float:
    """Percentage deviation from a non-zero user-supplied reference; not a tolerance verdict."""
    measured = _number(measured_v, "ولتاژ اندازه‌گیری‌شده")
    reference = _number(reference_v, "ولتاژ مرجع")
    if reference == 0:
        raise CalculationError("درصد افت نسبت به مرجع صفر تعریف نشده است.")
    return 100.0 * (measured - reference) / abs(reference)


def compare_to_reference(measured: float, expected: float, tolerance_percent: float | None = None) -> dict:
    """Compare two user-supplied values; never supplies a default tolerance."""
    actual = _number(measured, "مقدار اندازه‌گیری‌شده")
    target = _number(expected, "مقدار مرجع")
    delta = actual - target
    result = {"measured": actual, "expected": target, "difference": delta, "within_tolerance": None}
    if tolerance_percent is None:
        result["interpretation"] = "تلرانس ارائه نشده؛ فقط اختلاف عددی محاسبه شده است."
        return result
    tolerance = _number(tolerance_percent, "تلرانس درصدی")
    if tolerance < 0:
        raise CalculationError("تلرانس نمی‌تواند منفی باشد.")
    allowed = abs(target) * tolerance / 100.0
    if target == 0 and tolerance > 0:
        raise CalculationError("برای مقدار مرجع صفر از تلرانس مطلق استفاده کنید؛ تلرانس درصدی قابل تفسیر نیست.")
    result.update({
        "tolerance_percent": tolerance,
        "allowed_absolute_difference": allowed,
        "within_tolerance": abs(delta) <= allowed,
        "interpretation": "مقایسه عددی بر اساس تلرانس ورودی کاربر؛ علت خرابی را تعیین نمی‌کند.",
    })
    return result
