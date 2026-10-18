import pytest

from services.repair_service import (
    add_measurement, close_case, create_case, find_similar_cases,
    get_case, list_cases, record_test_result, update_case,
)


def test_case_and_measurement_persist_across_connections(db_path):
    case = create_case({
        "board_name": "کنترلر آزمایشی کاربر", "board_model": "PCB-01",
        "fault_description": "خروجی ثبت‌شده کمتر از مرجع است", "symptoms": ["wrong_voltage"],
        "expected_input_voltage": 24, "expected_input_source": "برچسب دستگاه",
    }, path=db_path)
    measurement_id = add_measurement(case["id"], {
        "signal": "VOUT", "measured_value": 4.7, "unit": "V", "expected_value": 5.0,
        "tolerance_percent": 2, "expected_source": "شماتیک صفحه 2", "measurement_state": "powered",
        "conditions": "تست با بار مشخص‌شده در پرونده",
    }, path=db_path)
    loaded = get_case(case["id"], path=db_path)
    assert loaded["case_number"] == case["case_number"]
    assert loaded["expected_input_source"] == "برچسب دستگاه"
    assert loaded["measurements"][0]["id"] == measurement_id
    assert loaded["measurements"][0]["measured_value"] == pytest.approx(4.7)
    assert loaded["symptoms"] == ["wrong_voltage"]


def test_case_update_close_and_verification_guards(db_path):
    case = create_case({"board_name": "برد موتور"}, path=db_path)
    updated = update_case(case["id"], {"symptoms": ["motor_driver_fault"], "board_model": "M-2"}, path=db_path)
    assert updated["symptoms"] == ["motor_driver_fault"]
    with pytest.raises(ValueError):
        close_case(case["id"], final_outcome="ok", verified=True, reviewer="", evidence="")
    close_case(case["id"], final_outcome="تعمیر موفق طبق تست نهایی", confirmed_cause="اتصال لحیم معیوب", path=db_path)
    loaded = get_case(case["id"], path=db_path)
    assert loaded["status"] == "completed"
    assert loaded["verification_status"] == "unverified"
    assert loaded["confirmed_cause"] == "اتصال لحیم معیوب"


def test_bad_measurements_are_rejected(db_path):
    case = create_case({"board_name": "برد"}, path=db_path)
    with pytest.raises(ValueError):
        add_measurement(case["id"], {"signal": "VIN", "measured_value": float("nan"), "unit": "V"}, path=db_path)
    with pytest.raises(ValueError):
        add_measurement(case["id"], {"signal": "VIN", "measured_value": 1, "unit": "V", "tolerance_percent": -1}, path=db_path)


def test_similar_cases_explain_match_and_preserve_verification(db_path):
    older = create_case({
        "board_name": "کنترلر پمپ A", "board_model": "P-100", "application": "کنترل موتور",
        "fault_description": "ریست هنگام راه‌اندازی", "symptoms": ["resets", "no_power"],
    }, path=db_path)
    current = create_case({
        "board_name": "کنترلر پمپ B", "board_model": "P-100", "application": "کنترل موتور",
        "fault_description": "ریست زمان راه اندازی", "symptoms": ["resets", "no_power"],
    }, path=db_path)
    matches = find_similar_cases(current, path=db_path)
    assert len(matches) == 1
    assert matches[0]["id"] == older["id"]
    assert matches[0]["similarity_score"] > 0
    assert "شباهت" in matches[0]["knowledge_warning"]
    assert matches[0]["verification_status"] == "unverified"


def test_test_result_is_saved(db_path):
    case = create_case({"board_name": "برد"}, path=db_path)
    record_test_result(case["id"], {
        "test_code": "T_CHECK", "test_title": "آزمایش نمونه", "result": "inconclusive", "notes": "شرایط نامشخص"
    }, path=db_path)
    assert get_case(case["id"], path=db_path)["tests"][0]["result"] == "inconclusive"
    assert len(list_cases(path=db_path)) == 1
