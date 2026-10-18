"""Small shared Qt helpers."""
from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget


def stat_card(title: str, value: str, foot: str = "") -> QFrame:
    frame = QFrame(); frame.setObjectName("card")
    lay = QVBoxLayout(frame)
    t = QLabel(title); t.setObjectName("muted")
    v = QLabel(value); v.setObjectName("statValue")
    lay.addWidget(t); lay.addWidget(v)
    if foot:
        f = QLabel(foot); f.setObjectName("muted"); f.setWordWrap(True); lay.addWidget(f)
    return frame


def make_table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.horizontalHeader().setStretchLastSection(True)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    return table


def fill_table(table: QTableWidget, rows: list[list]) -> None:
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            table.setItem(r, c, QTableWidgetItem("" if value is None else str(value)))
    table.resizeColumnsToContents()


def section_title(text: str) -> QLabel:
    label = QLabel(text); label.setObjectName("h2"); return label


def page_container() -> tuple[QWidget, QVBoxLayout]:
    widget = QWidget(); lay = QVBoxLayout(widget)
    lay.setContentsMargins(18, 14, 18, 14); lay.setSpacing(12)
    return widget, lay
