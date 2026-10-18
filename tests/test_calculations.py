import math

import pytest

from core.electrical_calculations import (
    CalculationError, capacitor_energy, compare_to_reference, diode_power,
    ohms_current, parallel_resistance, power_vi, rc_time_constant,
    series_resistance, voltage_divider, voltage_drop_percent,
)


def test_ohms_law_and_power():
    assert ohms_current(12, 6) == pytest.approx(2)
    assert power_vi(12, 2) == pytest.approx(24)


def test_voltage_divider_ideal_unloaded():
    assert voltage_divider(12, 10_000, 10_000) == pytest.approx(6)


def test_series_and_parallel_resistance():
    assert series_resistance(10, 20, 30) == pytest.approx(60)
    assert parallel_resistance(100, 100) == pytest.approx(50)
    assert parallel_resistance(0, 100) == 0


def test_rc_energy_and_diode_power():
    assert rc_time_constant(10_000, 100e-6) == pytest.approx(1)
    assert capacitor_energy(100e-6, 10) == pytest.approx(0.005)
    assert diode_power(0.7, 0.01) == pytest.approx(0.007)


def test_compare_requires_explicit_tolerance():
    result = compare_to_reference(4.9, 5.0)
    assert result["within_tolerance"] is None
    assert result["difference"] == pytest.approx(-0.1)
    assert compare_to_reference(4.9, 5.0, 2)["within_tolerance"] is True
    assert compare_to_reference(4.7, 5.0, 2)["within_tolerance"] is False


def test_percent_deviation_is_signed():
    assert voltage_drop_percent(4.5, 5.0) == pytest.approx(-10)


@pytest.mark.parametrize("fn,args", [
    (ohms_current, (5, 0)),
    (voltage_divider, (5, -1, 2)),
    (series_resistance, (-1, 2)),
    (parallel_resistance, ()),
    (rc_time_constant, (-1, 1e-6)),
    (voltage_drop_percent, (1, 0)),
    (compare_to_reference, (1, 0, 5)),
])
def test_invalid_inputs_raise(fn, args):
    with pytest.raises(CalculationError):
        fn(*args)


def test_non_finite_inputs_raise():
    with pytest.raises(CalculationError):
        power_vi(math.nan, 1)
