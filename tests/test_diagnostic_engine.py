from core.diagnostic_engine import diagnose
from services.db import db_session
from services.repair_service import add_measurement, create_case, record_test_result, get_case


def test_no_power_without_measurements_returns_no_cause(db_path):
    case = create_case({"board_name": "برد ناشناس", "symptoms": ["no_power"]}, path=db_path)
    result = diagnose(case, path=db_path)
    assert result["status"] == "triage_only_insufficient_for_cause"
    assert result["ranked_hypotheses"] == []
    assert result["next_tests"]
    assert any("حدس نمی‌زند" in item for item in result["missing_information"])
    assert result["warnings"]


def test_generic_component_measurement_does_not_use_unknown_fixed_limit(db_path):
    case = create_case({"board_name": "برد ناشناس", "symptoms": ["no_power"]}, path=db_path)
    add_measurement(case["id"], {"signal": "VIN", "measured_value": 5, "unit": "V", "measurement_state": "powered"}, path=db_path)
    case = get_case(case["id"], path=db_path)
    result = diagnose(case, path=db_path)
    assert result["ranked_hypotheses"] == []
    assert not any("5 V" in h["title"] for h in result["ranked_hypotheses"])


def test_specific_component_range_check_has_official_source_and_no_probability(db_path):
    case = create_case({"board_name": "برد تغذیه", "reference_component": "TPS5430", "symptoms": ["no_output"]}, path=db_path)
    add_measurement(case["id"], {
        "signal": "VIN", "measured_value": 4.9, "unit": "V", "measurement_state": "powered",
        "conditions": "اندازه‌گیری در پایه VIN نسبت به GND؛ ثبت نمونه آزمایشی",
    }, path=db_path)
    result = diagnose(get_case(case["id"], path=db_path), path=db_path)
    assert result["ranked_hypotheses"]
    candidate = result["ranked_hypotheses"][0]
    assert "TPS5430" in candidate["title"]
    assert candidate["source"]["status"] == "official_datasheet_reviewed"
    assert candidate["evidence_quality"]["confidence_percent"] is None
    assert "خرابی قطعه را ثابت نمی‌کند" in " ".join(candidate["evidence_against"])
    assert "Absolute Maximum" in " ".join(candidate["evidence_against"])


def test_component_operating_check_uses_seeded_profile_data_not_part_number_mapping(db_path):
    with db_session(db_path) as conn:
        conn.execute(
            "UPDATE components SET recommended_operating_json=? WHERE part_number='LM2596'",
            ('{"test_supply_range":{"min":10,"max":20}}',),
        )
        conn.execute(
            """UPDATE component_diagnostic_profiles
               SET operating_range_key='test_supply_range',signal_aliases_json='[\"CUSTOM_RAIL\"]'
               WHERE profile_code='PROFILE_LM2596_VIN_RANGE'"""
        )
    case = create_case({"board_name": "برد آزمایشی", "reference_component": "LM2596", "symptoms": ["no_output"]}, path=db_path)
    add_measurement(case["id"], {
        "signal": "custom rail", "measured_value": 21, "unit": "V", "measurement_state": "powered",
    }, path=db_path)
    result = diagnose(get_case(case["id"], path=db_path), path=db_path)
    candidate = next(h for h in result["ranked_hypotheses"] if h["type"] == "documented_operating_condition")
    assert "test_supply_range" in candidate["title"]
    assert candidate["source"]["status"] == "official_datasheet_reviewed"


def test_incomplete_profile_range_is_left_unknown_not_treated_as_in_range(db_path):
    with db_session(db_path) as conn:
        conn.execute(
            "UPDATE components SET recommended_operating_json=? WHERE part_number='TPS5430'",
            ('{"input_voltage_v":{"min":5.5}}',),
        )
    case = create_case({"board_name": "برد آزمایشی", "reference_component": "TPS5430", "symptoms": ["no_output"]}, path=db_path)
    add_measurement(case["id"], {"signal": "VIN", "measured_value": 4.9, "unit": "V", "measurement_state": "powered"}, path=db_path)
    result = diagnose(get_case(case["id"], path=db_path), path=db_path)
    assert result["ranked_hypotheses"] == []
    assert any("کامل نیست" in warning for warning in result["warnings"])


def test_measurement_must_be_recorded_as_powered_for_operating_check(db_path):
    case = create_case({"board_name": "برد", "reference_component": "TPS5430", "symptoms": ["no_output"]}, path=db_path)
    add_measurement(case["id"], {"signal": "VIN", "measured_value": 4.9, "unit": "V", "measurement_state": "unknown"}, path=db_path)
    result = diagnose(get_case(case["id"], path=db_path), path=db_path)
    assert result["ranked_hypotheses"] == []
    assert any("برق‌دار" in warning for warning in result["warnings"])


def test_user_reference_is_compared_only_if_tolerance_is_supplied(db_path):
    case = create_case({"board_name": "برد", "symptoms": ["wrong_voltage"]}, path=db_path)
    add_measurement(case["id"], {
        "signal": "VOUT", "measured_value": 4.8, "unit": "V", "expected_value": 5.0,
        "expected_source": "شماتیک صفحه 3", "measurement_state": "powered",
    }, path=db_path)
    result = diagnose(get_case(case["id"], path=db_path), path=db_path)
    assert result["observations"][0]["within_tolerance"] is None
    assert result["observations"][0]["not_a_cause"] is True
    assert result["ranked_hypotheses"] == []


def test_test_result_updates_relevant_priority_without_confirming_failure(db_path):
    case = create_case({"board_name": "برد", "reference_component": "TPS5430", "symptoms": ["no_output"]}, path=db_path)
    add_measurement(case["id"], {"signal": "VIN", "measured_value": 4.9, "unit": "V", "measurement_state": "powered"}, path=db_path)
    record_test_result(case["id"], {
        "test_code": "T_VERIFY_COMPONENT_SUPPLY", "test_title": "تطبیق تغذیه",
        "result": "contradicts", "notes": "بازاندازه‌گیری در شرایط دیگر",
    }, path=db_path)
    result = diagnose(get_case(case["id"], path=db_path), path=db_path)
    assert "کاهش‌یافته" in result["ranked_hypotheses"][0]["priority_label"]
    assert result["test_findings"]
    assert result["ranked_hypotheses"][0]["evidence_quality"]["confidence_percent"] is None


def test_conditional_rule_input_zero_creates_hypothesis(db_path):
    case = create_case({"board_name": "برد", "symptoms": ["no_power"]}, path=db_path)
    add_measurement(case["id"], {"signal": "VIN", "measured_value": 0, "unit": "V", "measurement_state": "powered"}, path=db_path)
    result = diagnose(get_case(case["id"], path=db_path), path=db_path)
    codes = [h["code"] for h in result["ranked_hypotheses"]]
    assert "input_path_open_or_source_absent" in codes
    hyp = next(h for h in result["ranked_hypotheses"] if h["code"] == "input_path_open_or_source_absent")
    assert hyp["evidence_quality"]["confidence_percent"] is None
    assert hyp["evidence_against"]
    assert result["documented_failure_modes"]


def test_conditional_rule_input_present_output_zero(db_path):
    case = create_case({"board_name": "برد", "symptoms": ["no_output"]}, path=db_path)
    add_measurement(case["id"], {"signal": "VIN", "measured_value": 24, "unit": "V", "measurement_state": "powered"}, path=db_path)
    add_measurement(case["id"], {"signal": "VOUT", "measured_value": 0, "unit": "V", "measurement_state": "powered"}, path=db_path)
    result = diagnose(get_case(case["id"], path=db_path), path=db_path)
    assert "conversion_stage_not_delivering" in [h["code"] for h in result["ranked_hypotheses"]]
    codes = [t["test_code"] for t in result["next_tests"]]
    assert "T_REGULATOR_STAGE_CHECK" in codes


def test_conditional_rule_needs_tolerance_for_expected_outside(db_path):
    case = create_case({"board_name": "برد", "symptoms": ["wrong_voltage"]}, path=db_path)
    add_measurement(case["id"], {"signal": "VOUT", "measured_value": 3.0, "unit": "V",
                                  "expected_value": 5.0, "tolerance_percent": 5,
                                  "expected_source": "شماتیک", "measurement_state": "powered"}, path=db_path)
    result = diagnose(get_case(case["id"], path=db_path), path=db_path)
    assert "rail_outside_documented_reference" in [h["code"] for h in result["ranked_hypotheses"]]
