"""Dark Engineering theme (default) + light alternative, as Qt stylesheets."""
COLORS = {
    "background": "#0B0F14", "panel": "#121923", "card": "#18222E", "border": "#283544",
    "accent": "#00D1B2", "secondary": "#4DA3FF", "text": "#F1F5F9", "muted": "#94A3B8",
    "ok": "#22C55E", "warn": "#F59E0B", "danger": "#EF4444",
}

def stylesheet(dark: bool = True) -> str:
    if not dark:
        return """
        QMainWindow, QWidget { background:#F1F5F9; color:#0F172A; font-size:13px; }
        QFrame#card, QGroupBox { background:#FFFFFF; border:1px solid #CBD5E1; border-radius:8px; }
        QListWidget#nav { background:#E2E8F0; border:none; }
        QListWidget#nav::item { padding:10px 14px; border-radius:6px; margin:2px 6px; }
        QListWidget#nav::item:selected { background:#00A88F; color:white; }
        QPushButton { background:#FFFFFF; border:1px solid #94A3B8; border-radius:6px; padding:7px 14px; }
        QPushButton#primary { background:#00A88F; color:white; border:none; font-weight:bold; }
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {
            background:white; border:1px solid #94A3B8; border-radius:6px; padding:5px 8px; }
        QTableWidget { background:white; gridline-color:#CBD5E1; }
        QHeaderView::section { background:#E2E8F0; padding:6px; border:none; }
        QStatusBar { background:#E2E8F0; }
        """
    c = COLORS
    return f"""
    QMainWindow, QWidget {{ background:{c['background']}; color:{c['text']}; font-size:13px; }}
    QFrame#sidebar {{ background:{c['panel']}; border-left:1px solid {c['border']}; }}
    QFrame#topbar {{ background:{c['panel']}; border-bottom:1px solid {c['border']}; }}
    QFrame#card, QGroupBox {{ background:{c['card']}; border:1px solid {c['border']}; border-radius:8px; }}
    QGroupBox {{ margin-top:10px; padding-top:12px; font-weight:bold; }}
    QLabel#h1 {{ font-size:20px; font-weight:800; }}
    QLabel#h2 {{ font-size:15px; font-weight:700; }}
    QLabel#muted {{ color:{c['muted']}; }}
    QLabel#statValue {{ font-size:22px; font-weight:800; color:{c['accent']}; }}
    QLabel#ok {{ color:{c['ok']}; }} QLabel#warn {{ color:{c['warn']}; }} QLabel#danger {{ color:{c['danger']}; }}
    QListWidget#nav {{ background:transparent; border:none; outline:none; }}
    QListWidget#nav::item {{ padding:10px 14px; border-radius:6px; margin:2px 8px; color:{c['muted']}; }}
    QListWidget#nav::item:selected {{ background:{c['card']}; color:{c['accent']}; border:1px solid {c['border']}; }}
    QListWidget#nav::item:hover {{ color:{c['text']}; }}
    QPushButton {{ background:{c['card']}; border:1px solid {c['border']}; border-radius:6px; padding:7px 14px; }}
    QPushButton:hover {{ border-color:{c['accent']}; }}
    QPushButton#primary {{ background:{c['accent']}; color:#04241E; border:none; font-weight:bold; }}
    QPushButton#danger {{ border-color:{c['danger']}; color:{c['danger']}; }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit, QListWidget {{
        background:{c['panel']}; border:1px solid {c['border']}; border-radius:6px; padding:5px 8px; }}
    QTableWidget {{ background:{c['panel']}; gridline-color:{c['border']}; border:1px solid {c['border']}; border-radius:6px; }}
    QHeaderView::section {{ background:{c['card']}; color:{c['muted']}; padding:6px; border:none; font-weight:bold; }}
    QTableWidget::item:selected {{ background:{c['secondary']}; color:white; }}
    QTabWidget::pane {{ border:1px solid {c['border']}; border-radius:6px; }}
    QTabBar::tab {{ background:{c['card']}; padding:7px 14px; border-top-left-radius:6px; border-top-right-radius:6px; }}
    QTabBar::tab:selected {{ color:{c['accent']}; }}
    QCheckBox {{ spacing:6px; }}
    QStatusBar {{ background:{c['panel']}; color:{c['muted']}; border-top:1px solid {c['border']}; }}
    QSplitter::handle {{ background:{c['border']}; }}
    QScrollBar:vertical {{ background:{c['panel']}; width:10px; }}
    QScrollBar::handle:vertical {{ background:{c['border']}; border-radius:5px; }}
    """
