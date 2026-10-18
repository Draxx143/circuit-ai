"""CIRCUIT AI desktop main window — native Qt, no browser, fully offline.

Layout follows professional test/engineering tools (Keysight BenchVue /
NI InstrumentStudio pattern): fixed navigation rail, page header bar,
workspace, and a permanent status bar with database/engine state.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QMainWindow, QMessageBox, QPushButton, QRadioButton, QScrollArea, QSplitter,
    QStackedWidget, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from core.diagnostic_engine import diagnose
from core.electrical_calculations import (
    CalculationError, capacitor_energy, compare_to_reference, diode_power,
    ohms_current, parallel_resistance, power_vi, rc_time_constant,
    series_resistance, voltage_divider, voltage_drop_percent,
)
from services.backup_service import create_backup, restore_backup
from services.component_service import get_component, list_categories, search_components
from services.db import database_path, init_db
from services.knowledge_service import (
    list_failure_modes, list_rules, list_sources, list_topologies, quality_report,
)
from services.repair_service import (
    SYMPTOM_LABELS, add_measurement, archive_case, close_case, create_case,
    find_similar_cases, get_case, list_cases, record_test_result,
)
from services.settings_service import get_setting, set_setting

from .helpers import fill_table, make_table, page_container, section_title, stat_card
from .theme import stylesheet

NAV = [
    ("dashboard", "▦  داشبورد"),
    ("diagnosis", "⚕  عیب‌یابی جدید"),
    ("history", "▤  پرونده‌های تعمیر"),
    ("components", "⌘  بانک قطعات"),
    ("knowledge", "▣  دانش مدار و قواعد"),
    ("calculators", "ƒx  محاسبات مهندسی"),
    ("database", "⛁  مدیریت پایگاه داده"),
    ("settings", "⚙  تنظیمات"),
]
STATE_FA = {"نامشخص": "unknown", "روشن / برق‌دار": "powered", "خاموش / بی‌برق": "power_off"}
RESULT_FA = {"همسو با فرضیه": "supports", "مخالف فرضیه": "contradicts",
             "نامشخص": "inconclusive", "انجام نشده": "not_performed"}


class DashboardPage(QWidget):
    def __init__(self, win):
        super().__init__(); self.win = win
        _, lay = page_container(); self.setLayout(lay)
        title = QLabel("نمای کلی سامانه"); title.setObjectName("h1"); lay.addWidget(title)
        sub = QLabel("ابزار مهندسی عیب‌یابی بردهای الکترونیکی و کنترل صنعتی · آفلاین و محلی")
        sub.setObjectName("muted"); lay.addWidget(sub)
        self.cards = QGridLayout(); lay.addLayout(self.cards)
        btns = QHBoxLayout()
        start = QPushButton("＋  شروع عیب‌یابی جدید"); start.setObjectName("primary")
        start.clicked.connect(lambda: win.navigate("diagnosis"))
        comp = QPushButton("جست‌وجوی قطعه"); comp.clicked.connect(lambda: win.navigate("components"))
        hist = QPushButton("پرونده‌های تعمیر"); hist.clicked.connect(lambda: win.navigate("history"))
        for b in (start, comp, hist): btns.addWidget(b)
        btns.addStretch(1); lay.addLayout(btns)
        lay.addWidget(section_title("آخرین پرونده‌ها"))
        self.table = make_table(["شماره پرونده", "برد", "شرح خرابی", "وضعیت", "تاریخ"])
        lay.addWidget(self.table, 1)

    def refresh(self):
        report = quality_report(path=self.win.db_path)
        from services.db import table_counts
        counts = table_counts(self.win.db_path)
        data = [
            ("پرونده‌های تعمیر", str(counts.get("repair_cases", 0)), "ثبت‌شده در پایگاه محلی"),
            ("قطعات در بانک", str(report["components"]), f"{report['official_component_sources']} قطعه با دیتاشیت رسمی بررسی‌شده"),
            ("قوانین عیب‌یابی فعال", str(report["rules"]), f"{report['rules_needing_review']} قانون نیازمند بازبینی انسانی"),
            ("منابع فنی", str(report["sources"]), "فقط منابع ثبت‌شده با وضعیت اعتبار نمایش داده می‌شوند"),
        ]
        while self.cards.count():
            item = self.cards.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        for i, (t, v, f) in enumerate(data):
            self.cards.addWidget(stat_card(t, v, f), 0, i)
        fill_table(self.table, [[c["case_number"], c["board_name"], c["fault_description"][:48],
                                 c["status"], c["created_at"][:10]] for c in
                                __import__("services.repair_service", fromlist=["recent_cases"]).recent_cases(8, path=self.win.db_path)])


class DiagnosisPage(QWidget):
    def __init__(self, win):
        super().__init__(); self.win = win; self.case_id: int | None = None
        _, lay = page_container(); self.setLayout(lay)
        title = QLabel("عیب‌یابی مرحله‌ای"); title.setObjectName("h1"); lay.addWidget(title)
        safety = QLabel("⚠ پیش از اندازه‌گیری برق‌دار، نوع منبع، نقطه زمین و سطح خطر را از روی مدار واقعی مشخص کنید. این ابزار مسیر بررسی می‌دهد، نه تشخیص قطعی.")
        safety.setObjectName("warn"); safety.setWordWrap(True); lay.addWidget(safety)

        splitter = QSplitter(Qt.Orientation.Horizontal); lay.addWidget(splitter, 1)
        left = QWidget(); ll = QVBoxLayout(left)
        board = QGroupBox("۱ · مشخصات برد")
        form = QFormLayout(board)
        self.board_name = QLineEdit(); self.board_name.setPlaceholderText("مثلاً کنترلر پمپ")
        self.manufacturer = QLineEdit(); self.model = QLineEdit(); self.application = QLineEdit()
        self.ref_component = QLineEdit(); self.ref_component.setPlaceholderText("شماره دقیق قطعه، مثل TPS5430")
        self.fault_desc = QLineEdit()
        for label, w in [("نام برد *", self.board_name), ("سازنده", self.manufacturer),
                         ("مدل / شماره PCB", self.model), ("کاربرد", self.application),
                         ("قطعه مرجع", self.ref_component), ("شرح خرابی", self.fault_desc)]:
            form.addRow(label, w)
        ll.addWidget(board)
        sym_box = QGroupBox("۲ · علائم خرابی")
        grid = QGridLayout(sym_box); self.symptom_checks = {}
        for i, (code, label) in enumerate(SYMPTOM_LABELS.items()):
            cb = QCheckBox(label); self.symptom_checks[code] = cb
            grid.addWidget(cb, i // 2, i % 2)
        ll.addWidget(sym_box)
        create = QPushButton("ذخیره پرونده و ادامه"); create.setObjectName("primary")
        create.clicked.connect(self.create_case); ll.addWidget(create)
        self.case_label = QLabel("هنوز پرونده‌ای ساخته نشده است."); self.case_label.setObjectName("muted")
        self.case_label.setWordWrap(True); ll.addWidget(self.case_label)

        meas = QGroupBox("۳ · افزودن اندازه‌گیری")
        mf = QFormLayout(meas)
        self.m_signal = QLineEdit(); self.m_signal.setPlaceholderText("VIN, VOUT, VM, RESET ...")
        self.m_value = QDoubleSpinBox(); self.m_value.setRange(-1e9, 1e9); self.m_value.setDecimals(6)
        self.m_value.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.m_unit = QComboBox(); self.m_unit.addItems(["V", "mV", "A", "mA", "Ω", "kΩ", "°C", "Hz", "kHz", "logic", "other"])
        self.m_unit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.m_state = QComboBox(); self.m_state.addItems(list(STATE_FA))
        self.m_expected = QDoubleSpinBox(); self.m_expected.setRange(-1e9, 1e9); self.m_expected.setDecimals(6)
        self.m_expected.setSpecialValueText("— ثبت نشده —"); self.m_expected.setValue(-1e9)
        self.m_tolerance = QDoubleSpinBox(); self.m_tolerance.setRange(-1, 1000); self.m_tolerance.setValue(-1)
        self.m_tolerance.setSpecialValueText("— ثبت نشده —")
        self.m_source = QLineEdit(); self.m_source.setPlaceholderText("منبع مرجع: شماتیک/دیتاشیت + صفحه")
        self.m_conditions = QLineEdit(); self.m_conditions.setPlaceholderText("بار، زمان، ابزار...")
        for label, w in [("نقطه / سیگنال *", self.m_signal), ("مقدار *", self.m_value), ("واحد", self.m_unit),
                         ("وضعیت مدار", self.m_state), ("مقدار مرجع", self.m_expected),
                         ("تلرانس ±٪", self.m_tolerance), ("منبع مرجع", self.m_source), ("شرایط", self.m_conditions)]:
            mf.addRow(label, w)
        add_m = QPushButton("ثبت اندازه‌گیری"); add_m.clicked.connect(self.add_measurement)
        mf.addRow(add_m); ll.addWidget(meas); ll.addStretch(1)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(left)
        scroll.setMinimumWidth(430)
        splitter.addWidget(scroll)

        right = QWidget(); rl = QVBoxLayout(right)
        rl.addWidget(section_title("۴ · تحلیل و آزمایش بعدی"))
        run = QPushButton("▶  اجرای موتور عیب‌یابی"); run.setObjectName("primary")
        run.clicked.connect(self.run_diagnosis); rl.addWidget(run)
        self.result = QTextEdit(); self.result.setReadOnly(True)
        self.result.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        rl.addWidget(self.result, 1)
        test_box = QGroupBox("۵ · ثبت نتیجه آزمایش و بستن پرونده")
        tf = QFormLayout(test_box)
        self.test_combo = QComboBox(); self.test_result = QComboBox()
        self.test_result.addItems(list(RESULT_FA)); self.test_notes = QLineEdit()
        save_t = QPushButton("ذخیره نتیجه آزمایش و تحلیل دوباره"); save_t.clicked.connect(self.save_test)
        tf.addRow("آزمایش", self.test_combo); tf.addRow("نتیجه", self.test_result)
        tf.addRow("توضیحات", self.test_notes); tf.addRow(save_t)
        self.outcome = QLineEdit(); self.outcome.setPlaceholderText("نتیجه نهایی تعمیر (برای بستن پرونده)")
        self.cause = QLineEdit(); self.cause.setPlaceholderText("علت نهایی تأییدشده")
        close = QPushButton("بستن پرونده تعمیر"); close.setObjectName("danger")
        close.clicked.connect(self.close_case)
        tf.addRow("نتیجه نهایی", self.outcome); tf.addRow("علت نهایی", self.cause); tf.addRow(close)
        rl.addWidget(test_box)
        splitter.addWidget(right); splitter.setSizes([430, 700])

    def _warn(self, msg): QMessageBox.warning(self, "CIRCUIT AI", msg)

    def create_case(self):
        if not self.board_name.text().strip():
            return self._warn("نام برد الزامی است.")
        try:
            case = create_case({
                "board_name": self.board_name.text(), "board_manufacturer": self.manufacturer.text(),
                "board_model": self.model.text(), "application": self.application.text(),
                "reference_component": self.ref_component.text(), "fault_description": self.fault_desc.text(),
                "symptoms": [c for c, cb in self.symptom_checks.items() if cb.isChecked()],
            }, path=self.win.db_path)
        except Exception as exc:
            return self._warn(str(exc))
        self.case_id = case["id"]
        self.case_label.setText(f"پرونده {case['case_number']} ساخته شد. حالا اندازه‌گیری واقعی را ثبت و تحلیل را اجرا کنید.")

    def add_measurement(self):
        if not self.case_id: return self._warn("اول پرونده را بسازید.")
        if not self.m_signal.text().strip(): return self._warn("نام نقطه اندازه‌گیری الزامی است.")
        expected = None if self.m_expected.value() == -1e9 else self.m_expected.value()
        tolerance = None if self.m_tolerance.value() < 0 else self.m_tolerance.value()
        try:
            add_measurement(self.case_id, {
                "signal": self.m_signal.text(), "measured_value": self.m_value.value(),
                "unit": self.m_unit.currentText(), "measurement_state": STATE_FA[self.m_state.currentText()],
                "expected_value": expected, "tolerance_percent": tolerance,
                "expected_source": self.m_source.text(), "conditions": self.m_conditions.text(),
            }, path=self.win.db_path)
        except Exception as exc:
            return self._warn(str(exc))
        QMessageBox.information(self, "CIRCUIT AI", "اندازه‌گیری ثبت شد.")

    def run_diagnosis(self):
        if not self.case_id: return self._warn("اول پرونده را بسازید.")
        case = get_case(self.case_id, path=self.win.db_path)
        result = diagnose(case, path=self.win.db_path)
        from services.repair_service import save_diagnosis
        save_diagnosis(self.case_id, result, path=self.win.db_path)
        lines = [result["status_fa"], "", result["method"], ""]
        if result["ranked_hypotheses"]:
            lines.append("فرضیه‌های قابل بررسی (اولویت بررسی، نه احتمال):")
            for i, h in enumerate(result["ranked_hypotheses"], 1):
                lines += [f"{i}. {h['title']}", f"   اولویت: {h['priority_label']}",
                          "   شواهد موافق: " + "؛ ".join(h["evidence_for"]),
                          "   شواهد مخالف/محدودیت: " + "؛ ".join(h["evidence_against"]),
                          f"   کیفیت شواهد: {h['evidence_quality']['label']}", ""]
        else:
            lines.append("با داده فعلی علت مستندی رتبه‌بندی نشد؛ سیستم به‌جای حدس، اندازه‌گیری بعدی را می‌خواهد.")
        if result["missing_information"]:
            lines += ["", "اطلاعات لازم بعدی:"] + [f"- {x}" for x in result["missing_information"]]
        if result.get("documented_failure_modes"):
            lines += ["", "رکوردهای مستند مرتبط:"] + [f"- {f['title']}" for f in result["documented_failure_modes"]]
        self.result.setPlainText("\n".join(lines))
        self.test_combo.clear()
        for t in result["next_tests"]:
            self.test_combo.addItem(f"{t['test_code']} — {t['title']}", t)
        similar = find_similar_cases(case, limit=4, path=self.win.db_path)
        if similar:
            self.result.append("\nپرونده‌های مشابه قبلی (فقط سرنخ، نه تشخیص):")
            for s in similar:
                self.result.append(f"- {s['case_number']} · {s['board_name']} · شباهت {s['similarity_score']*100:.0f}٪")
        return result

    def save_test(self):
        if not self.case_id or self.test_combo.currentData() is None:
            return self._warn("اول تحلیل را اجرا کنید تا آزمایش‌ها ساخته شوند.")
        test = self.test_combo.currentData()
        record_test_result(self.case_id, {
            "test_code": test["test_code"], "test_title": test["title"],
            "result": RESULT_FA[self.test_result.currentText()], "notes": self.test_notes.text(),
        }, path=self.win.db_path)
        self.run_diagnosis()

    def close_case(self):
        if not self.case_id: return self._warn("پرونده‌ای فعال نیست.")
        if not self.outcome.text().strip(): return self._warn("برای بستن پرونده، نتیجه نهایی الزامی است.")
        close_case(self.case_id, final_outcome=self.outcome.text(), confirmed_cause=self.cause.text(),
                   path=self.win.db_path)
        QMessageBox.information(self, "CIRCUIT AI", "پرونده بسته و در تاریخچه ذخیره شد.")
        self.case_id = None; self.case_label.setText("پرونده بسته شد.")


class HistoryPage(QWidget):
    def __init__(self, win):
        super().__init__(); self.win = win
        _, lay = page_container(); self.setLayout(lay)
        lay.addWidget(section_title("پرونده‌های تعمیر"))
        row = QHBoxLayout(); self.query = QLineEdit(); self.query.setPlaceholderText("جست‌وجو: برد، مدل، شرح خرابی...")
        btn = QPushButton("جست‌وجو"); btn.clicked.connect(self.refresh)
        self.query.returnPressed.connect(self.refresh)
        row.addWidget(self.query); row.addWidget(btn); lay.addLayout(row)
        self.table = make_table(["شماره", "برد", "مدل", "علائم", "وضعیت", "تأیید", "تاریخ"])
        self.table.itemSelectionChanged.connect(self.show_detail)
        lay.addWidget(self.table, 1)
        self.detail = QTextEdit(); self.detail.setReadOnly(True); lay.addWidget(self.detail)
        archive = QPushButton("بایگانی پرونده انتخاب‌شده"); archive.setObjectName("danger")
        archive.clicked.connect(self.archive); lay.addWidget(archive)

    def refresh(self):
        self.cases = list_cases(self.query.text(), path=self.win.db_path)
        fill_table(self.table, [[c["case_number"], c["board_name"], c["board_model"],
                                 "، ".join(SYMPTOM_LABELS.get(s, s) for s in c["symptoms"]),
                                 c["status"], c["verification_status"], c["created_at"][:10]] for c in self.cases])

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        return self.cases[rows[0].row()] if rows and hasattr(self, "cases") else None

    def show_detail(self):
        case = self._selected()
        if not case: return
        full = get_case(case["id"], path=self.win.db_path)
        self.detail.setPlainText(json.dumps(full, ensure_ascii=False, indent=2, default=str))

    def archive(self):
        case = self._selected()
        if case and QMessageBox.question(self, "بایگانی", f"پرونده {case['case_number']} بایگانی شود؟ (حذف نمی‌شود)") == QMessageBox.StandardButton.Yes:
            archive_case(case["id"], path=self.win.db_path); self.refresh()


class ComponentsPage(QWidget):
    def __init__(self, win):
        super().__init__(); self.win = win
        _, lay = page_container(); self.setLayout(lay)
        lay.addWidget(section_title("بانک قطعات الکترونیکی"))
        row = QHBoxLayout(); self.query = QLineEdit(); self.query.setPlaceholderText("شماره قطعه، سازنده یا کاربرد...")
        self.category = QComboBox(); search = QPushButton("جست‌وجو")
        search.clicked.connect(self.refresh); self.query.returnPressed.connect(self.refresh)
        row.addWidget(self.query); row.addWidget(self.category); row.addWidget(search); lay.addLayout(row)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.table = make_table(["شماره قطعه", "سازنده", "دسته", "پکیج", "اعتبار"])
        self.table.itemSelectionChanged.connect(self.show_detail)
        self.detail = QTextEdit(); self.detail.setReadOnly(True)
        split.addWidget(self.table); split.addWidget(self.detail); split.setSizes([560, 420])
        lay.addWidget(split, 1)

    def refresh(self):
        if self.category.count() == 0:
            self.category.addItems(["همه"] + list_categories(path=self.win.db_path))
        self.items = search_components(self.query.text(), category=self.category.currentText(), path=self.win.db_path)
        fill_table(self.table, [[c["part_number"], c["manufacturer"], c["category"], c["package"] or "—",
                                 c["validation_status"]] for c in self.items])

    def show_detail(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows: return
        comp = get_component(self.items[rows[0].row()]["part_number"], path=self.win.db_path)
        lines = [comp["part_number"], comp["manufacturer"], "", comp.get("function_text", ""), "",
                 "مشخصات ثبت‌شده:", json.dumps(comp.get("specs", {}), ensure_ascii=False, indent=2),
                 "", "محدوده کاری توصیه‌شده (فقط اگر مستند باشد):",
                 json.dumps(comp.get("recommended_operating", {}), ensure_ascii=False, indent=2),
                 "", "پایه‌ها:"]
        lines += [f"- {p['pin_number']} · {p['pin_name']}: {p['function_text']}" for p in comp.get("pins", [])] or ["- ثبت نشده (حدس زده نمی‌شود)"]
        lines += ["", f"وضعیت اعتبار: {comp['validation_status']}", comp.get("notes", "")]
        lines += ["", "منابع:"] + [f"- {s['title']} · {s['url']}" for s in comp.get("sources", [])]
        self.detail.setPlainText("\n".join(lines))


class KnowledgePage(QWidget):
    def __init__(self, win):
        super().__init__(); self.win = win
        _, lay = page_container(); self.setLayout(lay)
        lay.addWidget(section_title("دانش مدارها، قواعد و منابع فنی"))
        tabs = QTabWidget(); lay.addWidget(tabs, 1)
        self.topo = make_table(["کد", "عنوان", "دسته", "اعتبار"])
        self.rules = make_table(["کد قاعده", "عنوان", "دسته", "اولویت", "اعتبار"])
        self.sources = make_table(["عنوان", "ناشر", "نوع", "وضعیت", "قطعات مرتبط"])
        self.failures = make_table(["کد", "عنوان", "اعتبار"])
        for table, label in [(self.topo, "ساختارهای مدار"), (self.rules, "قواعد عیب‌یابی"),
                             (self.failures, "حالت‌های خرابی مستند"), (self.sources, "منابع فنی")]:
            w = QWidget(); l = QVBoxLayout(w); l.addWidget(table); tabs.addTab(w, label)

    def refresh(self):
        fill_table(self.topo, [[t["topology_code"], t["title"], t["category"], t["validation_status"]]
                               for t in list_topologies(path=self.win.db_path)])
        fill_table(self.rules, [[r["rule_code"], r["title"], r["category"], r["priority"], r["validation_status"]]
                                for r in list_rules(path=self.win.db_path)])
        fill_table(self.sources, [[s["title"], s["publisher"], s["document_type"], s["status"], s["component_count"]]
                                  for s in list_sources(path=self.win.db_path)])
        fill_table(self.failures, [[f["failure_code"], f["title"], f["validation_status"]]
                                   for f in list_failure_modes(path=self.win.db_path)])


class CalculatorsPage(QWidget):
    TOOLS = {}

    def __init__(self, win):
        super().__init__(); self.win = win
        _, lay = page_container(); self.setLayout(lay)
        lay.addWidget(section_title("محاسبات مهندسی"))
        note = QLabel("محاسبات ایده‌آل‌اند و محدودیت هرکدام کنار نتیجه نوشته می‌شود؛ تلرانس یا مقدار مورد انتظار هیچ بردی حدس زده نمی‌شود.")
        note.setObjectName("muted"); note.setWordWrap(True); lay.addWidget(note)
        self.combo = QComboBox(); self.combo.addItems(list(self._defs()))
        self.combo.currentTextChanged.connect(self._build)
        lay.addWidget(self.combo)
        self.form_host = QWidget(); self.form = QFormLayout(self.form_host); lay.addWidget(self.form_host)
        calc = QPushButton("محاسبه"); calc.setObjectName("primary"); calc.clicked.connect(self._calc)
        lay.addWidget(calc); self.out = QLabel(""); self.out.setWordWrap(True); lay.addWidget(self.out); lay.addStretch(1)
        self._build(self.combo.currentText())

    @staticmethod
    def _defs():
        return {
            "قانون اهم  I = V / R": (["ولتاژ (V)", "مقاومت (Ω)"], lambda a: f"I = {ohms_current(a[0], a[1]):.8g} A — ایده‌آل؛ امپدانس منبع/سیم نادیده گرفته شده."),
            "توان  P = V × I": (["ولتاژ (V)", "جریان (A)"], lambda a: f"P = {power_vi(a[0], a[1]):.8g} W"),
            "تقسیم ولتاژ": (["Vin (V)", "R بالا (Ω)", "R پایین (Ω)"], lambda a: f"Vout = {voltage_divider(a[0], a[1], a[2]):.8g} V — تقسیم‌گرِ بدون بار فرض شده."),
            "مقاومت سری": (["مقاومت‌ها با کاما (Ω)"], lambda a: f"R = {series_resistance(*a):.8g} Ω"),
            "مقاومت موازی": (["مقاومت‌ها با کاما (Ω)"], lambda a: f"R = {parallel_resistance(*a):.8g} Ω"),
            "ثابت زمانی RC  τ = R×C": (["مقاومت (Ω)", "ظرفیت (F)"], lambda a: f"τ = {rc_time_constant(a[0], a[1]):.8g} s — مدار مرتبه‌اول ایده‌آل."),
            "انرژی خازن  E = ½CV²": (["ظرفیت (F)", "ولتاژ (V)"], lambda a: f"E = {capacitor_energy(a[0], a[1]):.8g} J — فقط بزرگی انرژی؛ دستور تخلیه نیست."),
            "توان دیود  P ≈ Vf × I": (["Vf (V)", "جریان (A)"], lambda a: f"P ≈ {diode_power(a[0], a[1]):.8g} W"),
            "انحراف از مرجع (٪)": (["اندازه‌گیری‌شده", "مرجع"], lambda a: f"انحراف = {voltage_drop_percent(a[0], a[1]):+.4f}٪ — حکم تلرانس نیست."),
            "مقایسه با تلرانس کاربر": (["اندازه‌گیری‌شده", "مرجع", "تلرانس ±٪"], lambda a: str(compare_to_reference(a[0], a[1], a[2]))),
        }

    def _build(self, _=None):
        while self.form.count():
            item = self.form.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.inputs = []
        labels, _ = self._defs()[self.combo.currentText()]
        for label in labels:
            edit = QLineEdit("0"); edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
            self.form.addRow(label, edit); self.inputs.append(edit)

    def _calc(self):
        try:
            _, fn = self._defs()[self.combo.currentText()]
            values = []
            for edit in self.inputs:
                text = edit.text().replace("،", ",")
                if "," in text:
                    values.extend(float(x) for x in text.split(",") if x.strip())
                else:
                    values.append(float(text))
            self.out.setText(fn(values))
        except (CalculationError, ValueError) as exc:
            self.out.setText(f"خطا: {exc}")


class DatabasePage(QWidget):
    def __init__(self, win):
        super().__init__(); self.win = win
        _, lay = page_container(); self.setLayout(lay)
        lay.addWidget(section_title("مدیریت پایگاه داده"))
        self.info = QTextEdit(); self.info.setReadOnly(True); lay.addWidget(self.info, 1)
        row = QHBoxLayout()
        backup = QPushButton("ساخت نسخه پشتیبان…"); backup.setObjectName("primary"); backup.clicked.connect(self.backup)
        restore = QPushButton("بازیابی از پشتیبان…"); restore.setObjectName("danger"); restore.clicked.connect(self.restore)
        refresh = QPushButton("به‌روزرسانی گزارش"); refresh.clicked.connect(self.refresh)
        for b in (backup, restore, refresh): row.addWidget(b)
        row.addStretch(1); lay.addLayout(row)

    def refresh(self):
        report = quality_report(path=self.win.db_path)
        self.info.setPlainText(f"مسیر پایگاه داده:\n{self.win.db_path}\n\nگزارش کیفیت:\n"
                               + json.dumps(report, ensure_ascii=False, indent=2))

    def backup(self):
        target, _ = QFileDialog.getSaveFileName(self, "ذخیره پشتیبان", "circuit-ai-backup.sqlite3", "SQLite (*.sqlite3)")
        if target:
            try:
                create_backup(Path(target), source=self.win.db_path)
                QMessageBox.information(self, "CIRCUIT AI", f"پشتیبان ساخته شد:\n{target}")
            except Exception as exc:
                QMessageBox.warning(self, "CIRCUIT AI", str(exc))

    def restore(self):
        source, _ = QFileDialog.getOpenFileName(self, "انتخاب فایل پشتیبان", "", "SQLite (*.sqlite3 *.db *.bak)")
        if source and QMessageBox.question(self, "بازیابی", "پایگاه فعلی جایگزین می‌شود (نسخه محافظتی نگه داشته می‌شود). ادامه؟") == QMessageBox.StandardButton.Yes:
            try:
                restore_backup(Path(source), destination=self.win.db_path)
                init_db(self.win.db_path); self.refresh()
                QMessageBox.information(self, "CIRCUIT AI", "بازیابی کامل شد.")
            except Exception as exc:
                QMessageBox.warning(self, "CIRCUIT AI", str(exc))


class SettingsPage(QWidget):
    def __init__(self, win):
        super().__init__(); self.win = win
        _, lay = page_container(); self.setLayout(lay)
        lay.addWidget(section_title("تنظیمات"))
        box = QGroupBox("تم رابط"); bl = QVBoxLayout(box)
        self.dark = QRadioButton("تیره مهندسی (پیش‌فرض)"); self.light = QRadioButton("روشن")
        (self.dark if win.theme == "dark" else self.light).setChecked(True)
        bl.addWidget(self.dark); bl.addWidget(self.light); lay.addWidget(box)
        save = QPushButton("ذخیره و اعمال تم"); save.setObjectName("primary"); save.clicked.connect(self.save)
        lay.addWidget(save)
        info = QLabel("برنامه کاملاً آفلاین و محلی است؛ هیچ داده‌ای به سرویس خارجی ارسال نمی‌شود.\n"
                      f"پایگاه داده: {win.db_path}\nموتور: قوانین صریح + محاسبات مهندسی (بدون درصد اطمینان ساختگی)")
        info.setObjectName("muted"); info.setWordWrap(True); lay.addWidget(info); lay.addStretch(1)

    def save(self):
        theme = "dark" if self.dark.isChecked() else "light"
        set_setting("desktop_theme", theme, path=self.win.db_path)
        self.win.apply_theme(theme)


class MainWindow(QMainWindow):
    PAGES = {"dashboard": DashboardPage, "diagnosis": DiagnosisPage, "history": HistoryPage,
             "components": ComponentsPage, "knowledge": KnowledgePage, "calculators": CalculatorsPage,
             "database": DatabasePage, "settings": SettingsPage}

    def __init__(self, db_path=None):
        super().__init__()
        self.db_path = Path(init_db(db_path) if db_path else init_db())
        self.theme = get_setting("desktop_theme", "dark", path=self.db_path)
        self.setWindowTitle("CIRCUIT AI — Intelligent Electronics Diagnostics")
        self.resize(1240, 780); self.setMinimumSize(980, 620)

        central = QWidget(); root = QHBoxLayout(central); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        sidebar = QFrame(); sidebar.setObjectName("sidebar"); sidebar.setFixedWidth(218)
        sl = QVBoxLayout(sidebar)
        brand = QLabel("⚡ CIRCUIT AI"); brand.setObjectName("h2"); sl.addWidget(brand)
        tag = QLabel("Intelligent Electronics\nDiagnostics"); tag.setObjectName("muted"); sl.addWidget(tag)
        self.nav = QListWidget(); self.nav.setObjectName("nav")
        self.nav.addItems([label for _, label in NAV]); sl.addWidget(self.nav, 1)
        mode = QLabel("● حالت آفلاین محلی"); mode.setObjectName("ok"); sl.addWidget(mode)
        root.addWidget(sidebar)

        main = QWidget(); ml = QVBoxLayout(main); ml.setContentsMargins(0, 0, 0, 0); ml.setSpacing(0)
        topbar = QFrame(); topbar.setObjectName("topbar"); tl = QHBoxLayout(topbar)
        self.page_title = QLabel("داشبورد"); self.page_title.setObjectName("h2"); tl.addWidget(self.page_title)
        tl.addStretch(1)
        db_label = QLabel("پایگاه داده: متصل (SQLite محلی)"); db_label.setObjectName("muted"); tl.addWidget(db_label)
        engine = QLabel("موتور عیب‌یابی: فعال"); engine.setObjectName("ok"); tl.addWidget(engine)
        ml.addWidget(topbar)
        self.stack = QStackedWidget(); ml.addWidget(self.stack, 1)
        root.addWidget(main, 1)
        self.setCentralWidget(central)

        self.page_widgets = {}
        for key, cls in self.PAGES.items():
            widget = cls(self); self.page_widgets[key] = widget; self.stack.addWidget(widget)
        self.nav.currentRowChanged.connect(self._on_nav)
        self.nav.setCurrentRow(0)

        bar = self.statusBar()
        bar.showMessage(f"آماده · پایگاه داده: {self.db_path} · آفلاین (بدون ارسال داده به خارج)")
        self.apply_theme(self.theme)
        self._build_menu()

    def _build_menu(self):
        menu = self.menuBar()
        file_menu = menu.addMenu("پرونده")
        new_case = QAction("عیب‌یابی جدید", self); new_case.triggered.connect(lambda: self.navigate("diagnosis"))
        quit_action = QAction("خروج", self); quit_action.triggered.connect(self.close)
        file_menu.addAction(new_case); file_menu.addSeparator(); file_menu.addAction(quit_action)
        help_menu = menu.addMenu("راهنما")
        about = QAction("درباره CIRCUIT AI", self)
        about.triggered.connect(lambda: QMessageBox.about(
            self, "CIRCUIT AI",
            "CIRCUIT AI — دستیار محلی عیب‌یابی بردهای الکترونیکی\n"
            "موتور قانون‌محور و محاسبات مهندسی؛ بدون تشخیص قطعی یا درصد اطمینان ساختگی.\n"
            "خروجی، مسیر بررسی است و جایگزین شماتیک/دیتاشیت برد واقعی نیست."))
        help_menu.addAction(about)

    def apply_theme(self, theme: str):
        self.theme = theme
        from PySide6.QtWidgets import QApplication
        QApplication.instance().setStyleSheet(stylesheet(dark=(theme == "dark")))

    def navigate(self, key: str):
        index = [k for k, _ in NAV].index(key)
        self.nav.setCurrentRow(index)

    def _on_nav(self, row: int):
        if row < 0: return
        key, label = NAV[row]
        self.stack.setCurrentWidget(self.page_widgets[key])
        self.page_title.setText(label.split("  ", 1)[-1])
        refresh = getattr(self.page_widgets[key], "refresh", None)
        if refresh: refresh()
        self.statusBar().showMessage(f"{label.split('  ', 1)[-1]} · پایگاه داده: {self.db_path} · آفلاین")
