"""Engineering calculators page — thin UI over core.electrical_calculations.

Every result states its idealised limits; nothing here supplies a default
tolerance or a board-specific expected value.
"""
from __future__ import annotations

import streamlit as st

from core.electrical_calculations import (
    CalculationError, capacitor_energy, compare_to_reference, diode_power,
    ohms_current, parallel_resistance, power_vi, rc_time_constant,
    series_resistance, voltage_divider, voltage_drop_percent,
)


def _num(label, value=0.0, key=""):
    return st.number_input(label, value=float(value), format="%.8g", key=key)


def render_calculators() -> None:
    st.markdown("### محاسبات مهندسی")
    st.caption("محاسبات ایده‌آل و صریح‌اند و محدودیت هرکدام کنار نتیجه نوشته می‌شود؛ مقدار مورد انتظار هیچ بردی از اینجا حدس زده نمی‌شود.")
    tool = st.selectbox("ابزار محاسبه", [
        "قانون اهم (I = V/R)", "توان (P = V×I)", "تقسیم ولتاژ", "مقاومت سری",
        "مقاومت موازی", "ثابت زمانی RC", "انرژی ذخیره‌شده خازن",
        "توان تلفاتی دیود (Vf×I)", "درصد انحراف از مرجع", "مقایسه با مرجع و تلرانس کاربر",
    ])
    try:
        if tool.startswith("قانون اهم"):
            v, r = _num("ولتاژ (V)", 12, "ohm_v"), _num("مقاومت (Ω)", 100, "ohm_r")
            if st.button("محاسبه", key="b_ohm"):
                st.success(f"I = {ohms_current(v, r):.8g} A")
                st.caption("ایده‌آل: امپدانس منبع و سیم‌ها نادیده گرفته شده است.")
        elif tool.startswith("توان"):
            v, i = _num("ولتاژ (V)", 12, "p_v"), _num("جریان (A)", 1, "p_i")
            if st.button("محاسبه", key="b_p"):
                st.success(f"P = {power_vi(v, i):.8g} W")
        elif tool.startswith("تقسیم"):
            vin = _num("ولتاژ ورودی (V)", 12, "d_vin"); r1 = _num("مقاومت بالا R1 (Ω)", 10000, "d_r1"); r2 = _num("مقاومت پایین R2 (Ω)", 10000, "d_r2")
            if st.button("محاسبه", key="b_d"):
                st.success(f"Vout = {voltage_divider(vin, r1, r2):.8g} V")
                st.caption("تقسیم‌گر بدون بار فرض شده؛ بار خروجی نتیجه را تغییر می‌دهد.")
        elif tool.startswith("مقاومت سری") or tool.startswith("مقاومت موازی"):
            raw = st.text_input("مقاومت‌ها (Ω) با کاما جدا شوند", value="100, 220, 470", key="r_raw")
            values = [float(x) for x in raw.replace("،", ",").split(",") if x.strip()]
            if st.button("محاسبه", key="b_r"):
                result = series_resistance(*values) if tool.startswith("مقاومت سری") else parallel_resistance(*values)
                st.success(f"R معادل = {result:.8g} Ω")
        elif tool.startswith("ثابت زمانی"):
            r, c = _num("مقاومت (Ω)", 10000, "rc_r"), _num("ظرفیت (F)", 0.00001, "rc_c")
            if st.button("محاسبه", key="b_rc"):
                st.success(f"τ = {rc_time_constant(r, c):.8g} s")
                st.caption("مدار مرتبه‌اول ایده‌آل فرض شده است.")
        elif tool.startswith("انرژی"):
            c, v = _num("ظرفیت (F)", 0.001, "e_c"), _num("ولتاژ (V)", 24, "e_v")
            if st.button("محاسبه", key="b_e"):
                st.success(f"E = {capacitor_energy(c, v):.8g} J")
                st.warning("این عدد فقط بزرگی انرژی ذخیره‌شده را نشان می‌دهد و دستور تخلیه نیست؛ تخلیه باید با روش ایمن همان مدار انجام شود.")
        elif tool.startswith("توان تلفاتی"):
            vf, i = _num("افت مستقیم دیود (V)", 0.7, "di_vf"), _num("جریان (A)", 1, "di_i")
            if st.button("محاسبه", key="b_di"):
                st.success(f"P ≈ {diode_power(vf, i):.8g} W")
                st.caption("تقریب DC لحظه‌ای در همان شرایط واردشده است.")
        elif tool.startswith("درصد انحراف"):
            m, ref = _num("مقدار اندازه‌گیری‌شده (V)", 4.8, "pc_m"), _num("مرجع (V)", 5.0, "pc_r")
            if st.button("محاسبه", key="b_pc"):
                st.success(f"انحراف = {voltage_drop_percent(m, ref):+.4f}٪ نسبت به مرجع")
                st.caption("انحراف عددی، حکم «خارج از تلرانس» نیست؛ تلرانس باید از منبع همان برد بیاید.")
        else:
            m = _num("مقدار اندازه‌گیری‌شده", 4.8, "cmp_m"); e = _num("مقدار مرجع", 5.0, "cmp_e")
            tol = st.number_input("تلرانس ±٪ (از شماتیک/دیتاشیت همان برد)", value=5.0, format="%.4g", key="cmp_t")
            if st.button("مقایسه", key="b_cmp"):
                result = compare_to_reference(m, e, tol)
                st.success(f"اختلاف = {result['difference']:+.8g} · داخل تلرانس: {result['within_tolerance']}")
                st.caption(result["interpretation"])
    except (CalculationError, ValueError) as exc:
        st.error(str(exc))
