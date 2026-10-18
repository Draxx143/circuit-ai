"""Professional BoardView page: interactive board layout, net highlighting,
part/pin cross-reference, per-pin measurements and a schematic pane.

Patterns taken from dedicated board-analysis tools (BoardViewer / ZXW class):
search -> focus+highlight a part, click a pin -> the whole net lights up,
pin table beside the layout, schematic next to the board.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QSplitter, QTableWidget, QTabWidget, QVBoxLayout,
    QWidget, QGraphicsEllipseItem, QGraphicsItem, QGraphicsRectItem,
    QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView,
)

try:
    from PySide6.QtPdf import QPdfDocument
except Exception:  # QtPdf is optional
    QPdfDocument = None

from boardview.model import load_board_csv, load_board_json
from services.board_service import (
    add_part, delete_board, get_board, import_board, import_image_board,
    list_boards, list_nets, pins_on_net, save_pin_measurement,
)
from services.repair_service import list_cases

from .helpers import fill_table, make_table, page_container, section_title

KIND_FA = {"دیود مد (mV)": ("diode_mv", "mV"), "ولتاژ (V)": ("voltage_v", "V"),
           "مقاومت (Ω)": ("resistance_ohm", "Ω"), "پیوستگی": ("continuity", "")}
SAMPLE_PATH = Path(__file__).resolve().parents[1] / "data" / "sample_boards" / "motor_control_demo.board.json"


def diode_color(value) -> QColor:
    """Display colour for a recorded diode-mode reading (display heuristic only)."""
    if value is None:
        return QColor("#8a93a3")
    if value < 50:
        return QColor("#EF4444")      # near-zero reading
    if value < 350:
        return QColor("#F59E0B")
    if value <= 900:
        return QColor("#22C55E")
    return QColor("#4DA3FF")          # very high / OL-like reading


class BoardGraphicsView(QGraphicsView):
    scene_clicked = Signal(QPointF)

    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.add_mode = False

    def wheelEvent(self, event):
        factor = 1.18 if event.angleDelta().y() > 0 else 1 / 1.18
        self.scale(factor, factor)

    def mousePressEvent(self, event):
        if self.add_mode and event.button() == Qt.MouseButton.LeftButton:
            self.scene_clicked.emit(self.mapToScene(event.pos()))
            return
        super().mousePressEvent(event)


class PinItem(QGraphicsEllipseItem):
    def __init__(self, pin, part_ref):
        r = 0.85
        super().__init__(-r, -r, 2 * r, 2 * r)
        self.pin = pin; self.part_ref = part_ref
        self.setPos(pin["x_mm"], pin["y_mm"])
        self.setBrush(QBrush(diode_color(pin.get("diode_mv"))))
        self.setPen(QPen(QColor("#0B0F14"), 0.12))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setToolTip(f"{part_ref}.{pin['pin_name']} · net: {pin.get('net') or '—'}"
                        + (f" · diode: {pin['diode_mv']} mV" if pin.get("diode_mv") is not None else ""))
        self.setData(0, {"type": "pin", "pin_id": pin["id"], "part_ref": part_ref, "net": pin.get("net", "")})


class PartItem(QGraphicsRectItem):
    def __init__(self, part):
        w, h = max(part["w_mm"], 1.6), max(part["h_mm"], 1.2)
        super().__init__(-w / 2, -h / 2, w, h)
        self.part = part
        self.setPos(part["x_mm"], part["y_mm"])
        self.setRotation(part.get("rotation_deg") or 0)
        self.setBrush(QBrush(QColor("#1B2A38")))
        self.setPen(QPen(QColor("#5B7186"), 0.15))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setToolTip(f"{part['ref']} · {part.get('part_number') or ''} · {part.get('package') or ''}")
        self.setData(0, {"type": "part", "ref": part["ref"], "part_id": part["id"]})
        from PySide6.QtGui import QFont
        label = QGraphicsSimpleTextItem(part["ref"], self)
        font = QFont(); font.setPointSizeF(max(1.3, min(2.8, h * 0.55))); font.setBold(True)
        label.setFont(font)
        label.setBrush(QBrush(QColor("#E8F4F1")))
        b = label.boundingRect()
        label.setPos(-b.width() / 2, -b.height() / 2)


class BoardViewPage(QWidget):
    def __init__(self, win):
        super().__init__(); self.win = win
        self.db = win.db_path
        self.board = None
        self.part_items: dict[str, PartItem] = {}
        self.pin_items: dict[int, PinItem] = {}
        self.selected_net = ""
        self.selected_pin = None

        _, lay = page_container(); self.setLayout(lay)
        lay.addWidget(section_title("BoardView — نقشه تعاملی برد، نت‌ها و نقاط اندازه‌گیری"))
        hint = QLabel("فایل برد JSON/CSV یا عکس برد را باز کنید. روی قطعه کلیک کنید تا انتخاب شود؛ روی پین کلیک کنید تا کل نت روی برد روشن شود. مقادیر دیودمد/ولتاژ هر پین ذخیره و رنگی می‌شود و می‌تواند به پرونده تعمیر وصل شود.")
        hint.setObjectName("muted"); hint.setWordWrap(True); lay.addWidget(hint)

        # ---- toolbar
        bar = QHBoxLayout()
        self.btn_json = QPushButton("بازکردن فایل برد (JSON)"); self.btn_json.clicked.connect(self.open_json)
        self.btn_csv = QPushButton("واردکردن CSV قطعات/پین‌ها"); self.btn_csv.clicked.connect(self.open_csv)
        self.btn_img = QPushButton("بازکردن عکس برد"); self.btn_img.clicked.connect(self.open_image)
        self.btn_sample = QPushButton("برد نمونه آموزشی"); self.btn_sample.setObjectName("primary")
        self.btn_sample.clicked.connect(self.load_sample)
        self.btn_fit = QPushButton("⤢ جا دادن در صفحه"); self.btn_fit.clicked.connect(self.fit)
        self.btn_rot = QPushButton("⟳ چرخش ۹۰°"); self.btn_rot.clicked.connect(lambda: self.view.rotate(90))
        self.side_combo = QComboBox(); self.side_combo.addItems(["نمایش: روی برد (Top)", "نمایش: پشت برد (Bottom)", "نمایش: هر دو سمت"])
        self.side_combo.currentIndexChanged.connect(self.apply_side)
        self.mirror = QCheckBox("آینه‌ای (دید از پشت)"); self.mirror.toggled.connect(self.apply_side)
        for w in (self.btn_json, self.btn_csv, self.btn_img, self.btn_sample, self.btn_fit, self.btn_rot, self.side_combo, self.mirror):
            bar.addWidget(w)
        bar.addStretch(1); lay.addLayout(bar)
        bar2 = QHBoxLayout()
        self.chk_labels = QCheckBox("برچسب قطعات"); self.chk_labels.setChecked(True)
        self.chk_pins = QCheckBox("پین‌ها"); self.chk_pins.setChecked(True)
        self.chk_traces = QCheckBox("مسیر نت‌ها"); self.chk_traces.setChecked(True)
        self.chk_values = QCheckBox("رنگ دیودمد"); self.chk_values.setChecked(True)
        for chk in (self.chk_labels, self.chk_pins, self.chk_traces, self.chk_values):
            chk.toggled.connect(self.redraw); bar2.addWidget(chk)
        self.add_mode_btn = QPushButton("＋ افزودن قطعه با کلیک روی برد"); self.add_mode_btn.setCheckable(True)
        self.add_mode_btn.toggled.connect(self._set_add_mode); bar2.addWidget(self.add_mode_btn)
        bar2.addStretch(1)
        legend = QLabel("رنگ پین‌ها (فقط نمایش مقدار ثبت‌شده): خاکستری=ثبت نشده · قرمز=نزدیک صفر · زرد=کم · سبز=بازه رایج دیود · آبی=خیلی زیاد/OL")
        legend.setObjectName("muted"); bar2.addWidget(legend)
        lay.addLayout(bar2)

        # ---- main split: library | board | inspector ; schematic below board
        main_split = QSplitter(Qt.Orientation.Horizontal); lay.addWidget(main_split, 1)

        left = QWidget(); ll = QVBoxLayout(left)
        ll.addWidget(section_title("بردهای ذخیره‌شده"))
        self.boards_list = QListWidget(); self.boards_list.itemSelectionChanged.connect(self._board_selected)
        ll.addWidget(self.boards_list, 1)
        del_btn = QPushButton("حذف برد انتخاب‌شده"); del_btn.setObjectName("danger"); del_btn.clicked.connect(self.delete_current)
        ll.addWidget(del_btn)
        ll.addWidget(section_title("جست‌وجوی قطعه"))
        self.part_search = QLineEdit(); self.part_search.setPlaceholderText("مثل U4 یا TPS...")
        self.part_search.returnPressed.connect(self.search_part)
        ll.addWidget(self.part_search)
        self.parts_list = QListWidget(); self.parts_list.itemSelectionChanged.connect(self._part_from_list)
        ll.addWidget(self.parts_list, 2)
        ll.addWidget(section_title("نت‌ها (Net)"))
        self.net_search = QLineEdit(); self.net_search.setPlaceholderText("مثل GND یا VCC_5V...")
        self.net_search.textChanged.connect(self._filter_nets)
        ll.addWidget(self.net_search)
        self.nets_list = QListWidget(); self.nets_list.itemSelectionChanged.connect(self._net_from_list)
        ll.addWidget(self.nets_list, 2)
        main_split.addWidget(left)

        center = QWidget(); cl = QVBoxLayout(center)
        self.scene = QGraphicsScene(self)
        self.view = BoardGraphicsView(self.scene)
        self.view.scene_clicked.connect(self._scene_clicked)
        self.scene.selectionChanged.connect(self._selection_changed)
        cl.addWidget(self.view, 3)
        self.board_info = QLabel("هنوز بردی باز نشده است. برای شروع «برد نمونه آموزشی» را بزنید یا فایل/عکس برد باز کنید.")
        self.board_info.setObjectName("muted"); self.board_info.setWordWrap(True); cl.addWidget(self.board_info)
        schem_box = QGroupBox("شماتیک کنار برد (Cross-Probe دستی: قطعه را در هر دو نما پیدا کنید)")
        sl = QVBoxLayout(schem_box)
        srow = QHBoxLayout()
        open_schem = QPushButton("بازکردن شماتیک (عکس یا PDF)"); open_schem.clicked.connect(self.open_schematic)
        self.schem_search = QLineEdit(); self.schem_search.setPlaceholderText("نام قطعه برای یادداشت جست‌وجو در شماتیک...")
        srow.addWidget(open_schem); srow.addWidget(self.schem_search); sl.addLayout(srow)
        self.schem_label = QLabel("شماتیکی باز نشده است. PDF صفحه اول رندر می‌شود؛ برای شماتیک چندصفحه‌ای فعلاً عکس صفحه مربوط را باز کنید.")
        self.schem_label.setObjectName("muted"); self.schem_label.setWordWrap(True)
        self.schem_label.setMinimumHeight(120)
        sl.addWidget(self.schem_label)
        cl.addWidget(schem_box, 1)
        main_split.addWidget(center)

        right = QWidget(); rl = QVBoxLayout(right)
        rl.addWidget(section_title("قطعه / پین انتخاب‌شده"))
        self.selection_label = QLabel("قطعه یا پینی انتخاب نشده است."); self.selection_label.setWordWrap(True)
        rl.addWidget(self.selection_label)
        self.pins_table = make_table(["پین", "نام", "نت", "دیود (mV)", "آخرین اندازه‌گیری"])
        self.pins_table.itemSelectionChanged.connect(self._pin_from_table)
        rl.addWidget(self.pins_table, 1)
        meas = QGroupBox("ثبت اندازه‌گیری روی پین انتخاب‌شده")
        mf = QFormLayout(meas)
        self.meas_kind = QComboBox(); self.meas_kind.addItems(list(KIND_FA))
        self.meas_value = QDoubleSpinBox(); self.meas_value.setRange(-1e6, 1e6); self.meas_value.setDecimals(3)
        self.meas_value.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.meas_case = QComboBox(); self.meas_case.addItem("بدون اتصال به پرونده", None)
        self.meas_note = QLineEdit(); self.meas_note.setPlaceholderText("شرایط: بی‌برق، پراب قرمز روی زمین...")
        save_m = QPushButton("ذخیره اندازه‌گیری پین"); save_m.setObjectName("primary"); save_m.clicked.connect(self.save_measurement)
        mf.addRow("نوع", self.meas_kind); mf.addRow("مقدار", self.meas_value)
        mf.addRow("پرونده تعمیر", self.meas_case); mf.addRow("توضیحات", self.meas_note); mf.addRow(save_m)
        rl.addWidget(meas)
        rl.addWidget(section_title("پین‌های نت انتخاب‌شده"))
        self.net_pins = make_table(["قطعه", "پین", "سمت"])
        rl.addWidget(self.net_pins, 1)
        main_split.addWidget(right)
        main_split.setSizes([300, 760, 380])

    # ---------------- data loading
    def refresh(self):
        self.boards_list.clear()
        for b in list_boards(db_path=self.db):
            label = f"{b['name']} · {b['part_count']} قطعه · {b['pin_count']} پین" + (" · نمونه" if b["is_sample"] else "")
            item = QListWidgetItem(label); item.setData(Qt.ItemDataRole.UserRole, b["id"])
            self.boards_list.addItem(item)
        cases = list_cases(path=self.db)
        self.meas_case.clear(); self.meas_case.addItem("بدون اتصال به پرونده", None)
        for c in cases:
            if c["status"] == "open":
                self.meas_case.addItem(f"{c['case_number']} · {c['board_name']}", c["id"])

    def _load_board_id(self, board_id: int):
        self.board = get_board(board_id, db_path=self.db)
        self.selected_net = ""; self.selected_pin = None
        if not self.board:
            return
        n_nets = len(list_nets(board_id, db_path=self.db))
        self.board_info.setText(
            f"{self.board['name']} · ابعاد {self.board['width_mm']:.0f}×{self.board['height_mm']:.0f} mm · "
            f"{len(self.board['parts'])} قطعه · {sum(len(p['pins']) for p in self.board['parts'])} پین · {n_nets} نت"
            + (" · ⚠ داده نمونه آموزشی است، برد واقعی نیست." if self.board["is_sample"] else ""))
        self.parts_list.clear()
        for part in self.board["parts"]:
            item = QListWidgetItem(f"{part['ref']} · {part['part_number'] or '—'} · {part['side']}")
            item.setData(Qt.ItemDataRole.UserRole, part["ref"]); self.parts_list.addItem(item)
        self._filter_nets()
        self.redraw(); self.fit()

    def _board_selected(self):
        items = self.boards_list.selectedItems()
        if items:
            self._load_board_id(int(items[0].data(Qt.ItemDataRole.UserRole)))

    def delete_current(self):
        items = self.boards_list.selectedItems()
        if not items: return
        if QMessageBox.question(self, "حذف برد", "این برد و همه قطعات/اندازه‌گیری‌های نقشه‌اش حذف شود؟") == QMessageBox.StandardButton.Yes:
            delete_board(int(items[0].data(Qt.ItemDataRole.UserRole)), db_path=self.db)
            self.board = None; self.scene.clear(); self.refresh()

    def open_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "فایل برد JSON", "", "Board JSON (*.json)")
        if not path: return
        try:
            board_id = import_board(load_board_json(path), source_file=path, db_path=self.db)
        except Exception as exc:
            return QMessageBox.warning(self, "خطای فایل برد", str(exc))
        self.refresh(); self._load_board_id(board_id)

    def open_csv(self):
        parts, _ = QFileDialog.getOpenFileName(self, "parts.csv", "", "CSV (*.csv)")
        if not parts: return
        pins, _ = QFileDialog.getOpenFileName(self, "pins.csv (اختیاری — لغو = بدون پین)", "", "CSV (*.csv)")
        name, ok = QInputDialog.getText(self, "نام برد", "نام برد:", text=Path(parts).stem)
        if not ok or not name.strip(): return
        try:
            data = load_board_csv(parts, pins or None, name=name, width_mm=100, height_mm=80)
            board_id = import_board(data, source_file=parts, db_path=self.db)
        except Exception as exc:
            return QMessageBox.warning(self, "خطای CSV", str(exc))
        self.refresh(); self._load_board_id(board_id)

    def open_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "عکس برد", "", "Images (*.png *.jpg *.jpeg)")
        if not path: return
        name, ok = QInputDialog.getText(self, "نام برد", "نام برد:", text=Path(path).stem)
        if not ok: return
        try:
            board_id = import_image_board(path, name=name, db_path=self.db)
        except Exception as exc:
            return QMessageBox.warning(self, "خطای عکس", str(exc))
        self.refresh(); self._load_board_id(board_id)
        QMessageBox.information(self, "عکس برد",
                                "عکس بارگذاری شد. حالا با «افزودن قطعه با کلیک روی برد» روی عکس کلیک کنید تا قطعات و نقاط تست روی آن ثبت شوند.")

    def load_sample(self):
        try:
            board_id = import_board(load_board_json(SAMPLE_PATH), source_file=str(SAMPLE_PATH), db_path=self.db)
        except Exception as exc:
            return QMessageBox.warning(self, "خطای نمونه", str(exc))
        self.refresh(); self._load_board_id(board_id)

    # ---------------- rendering
    def redraw(self):
        self.scene.clear(); self.part_items = {}; self.pin_items = {}
        if not self.board:
            return
        w, h = self.board["width_mm"], self.board["height_mm"]
        self.scene.setSceneRect(-4, -4, w + 8, h + 8)
        image_path = self.board.get("image_path") or ""
        pix = QPixmap(image_path) if image_path and Path(image_path).exists() else QPixmap()
        if not pix.isNull():
            from PySide6.QtWidgets import QGraphicsPixmapItem
            item = QGraphicsPixmapItem(pix.scaled(int(w * 4), int(h * 4),
                                                  Qt.AspectRatioMode.IgnoreAspectRatio,
                                                  Qt.TransformationMode.SmoothTransformation))
            item.setScale(0.25); item.setZValue(-10); self.scene.addItem(item)
        else:
            bg = QGraphicsRectItem(0, 0, w, h)
            bg.setBrush(QBrush(QColor("#123A2A"))); bg.setPen(QPen(QColor("#2E7D5B"), 0.2))
            bg.setZValue(-10); self.scene.addItem(bg)
            if self.chk_traces.isChecked():
                self._draw_traces()
        side_mode = self.side_combo.currentIndex()  # 0 top, 1 bottom, 2 both
        for part in self.board["parts"]:
            visible = side_mode == 2 or (side_mode == 0 and part["side"] == "top") or (side_mode == 1 and part["side"] == "bottom")
            item = PartItem(part); item.setVisible(visible)
            if not self.chk_labels.isChecked():
                for child in item.childItems(): child.setVisible(False)
            self.scene.addItem(item); self.part_items[part["ref"]] = item
            for pin in part["pins"]:
                pitem = PinItem(pin, part["ref"])
                pitem.setVisible(visible and self.chk_pins.isChecked())
                if not self.chk_values.isChecked():
                    pitem.setBrush(QBrush(QColor("#D9C25A")))
                self.scene.addItem(pitem); self.pin_items[pin["id"]] = pitem
        self._highlight_net(self.selected_net, keep=True)

    def _draw_traces(self):
        by_net: dict[str, list[tuple[float, float]]] = {}
        for part in self.board["parts"]:
            for pin in part["pins"]:
                if pin.get("net"):
                    by_net.setdefault(pin["net"], []).append((pin["x_mm"], pin["y_mm"]))
        pen = QPen(QColor(80, 200, 160, 55), 0.35)
        from PySide6.QtWidgets import QGraphicsLineItem
        for pts in by_net.values():
            for a, b in zip(pts, pts[1:]):
                line = QGraphicsLineItem(a[0], a[1], b[0], b[1]); line.setPen(pen); line.setZValue(-5)
                self.scene.addItem(line)

    def fit(self):
        if self.board:
            self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def apply_side(self):
        self.view.resetTransform()
        if self.mirror.isChecked():
            self.view.scale(-1, 1)
        self.redraw()

    def _set_add_mode(self, on):
        self.view.add_mode = on
        self.view.setDragMode(QGraphicsView.DragMode.NoDrag if on else QGraphicsView.DragMode.ScrollHandDrag)

    def _scene_clicked(self, pos: QPointF):
        if not self.board: return
        ref, ok = QInputDialog.getText(self, "قطعه جدید", "نام قطعه (Ref) مثل U7:")
        if not ok or not ref.strip(): return
        part_number, _ = QInputDialog.getText(self, "قطعه جدید", "شماره قطعه (اختیاری):")
        side = "bottom" if self.side_combo.currentIndex() == 1 else "top"
        try:
            add_part(self.board["id"], {"ref": ref.strip(), "part_number": part_number,
                                        "x": pos.x(), "y": pos.y(), "side": side}, db_path=self.db)
        except Exception as exc:
            return QMessageBox.warning(self, "خطا", str(exc))
        keep = self.board["id"]; self._load_board_id(keep); self.select_part(ref.strip())

    # ---------------- selection / cross-reference
    def _selection_changed(self):
        for item in self.scene.selectedItems():
            data = item.data(0)
            if not data: continue
            if data.get("type") == "part":
                self.select_part(data["ref"])
            elif data.get("type") == "pin":
                self.select_part(data["part_ref"], pin_id=data["pin_id"])
                if data.get("net"):
                    self.highlight_net(data["net"])

    def select_part(self, ref: str, pin_id: int | None = None):
        if not self.board: return
        part = next((p for p in self.board["parts"] if p["ref"] == ref), None)
        if not part: return
        self.selection_label.setText(f"{part['ref']} · {part['part_number'] or 'شماره قطعه ثبت نشده'} · "
                                     f"{part['package'] or ''} · سمت {part['side']} · {len(part['pins'])} پین")
        rows = []
        for pin in part["pins"]:
            last = pin["measurements"][-1] if pin.get("measurements") else None
            rows.append([pin["pin_name"], pin.get("name", ""), pin.get("net") or "—",
                         pin.get("diode_mv") if pin.get("diode_mv") is not None else "—",
                         f"{last['kind']}={last['value']}" if last else "—"])
            if pin_id and pin["id"] == pin_id:
                self.selected_pin = pin
        if pin_id is None and part["pins"]:
            self.selected_pin = part["pins"][0]
        fill_table(self.pins_table, rows)
        item = self.part_items.get(ref)
        if item:
            self.view.centerOn(item)
            item.setPen(QPen(QColor("#00D1B2"), 0.35))

    def _part_from_list(self):
        items = self.parts_list.selectedItems()
        if items: self.select_part(items[0].data(Qt.ItemDataRole.UserRole))

    def search_part(self):
        term = self.part_search.text().strip().lower()
        if not self.board or not term: return
        for part in self.board["parts"]:
            if term in part["ref"].lower() or term in (part["part_number"] or "").lower():
                self.select_part(part["ref"]); return
        QMessageBox.information(self, "جست‌وجو", "قطعه‌ای با این عبارت روی این برد پیدا نشد.")

    def _filter_nets(self):
        if not self.board: return
        term = self.net_search.text().strip().lower() if hasattr(self, "net_search") else ""
        self.nets_list.clear()
        for net in list_nets(self.board["id"], db_path=self.db):
            if term and term not in net["net"].lower(): continue
            item = QListWidgetItem(f"{net['net']} · {net['pin_count']} پین · {net['part_refs']}")
            item.setData(Qt.ItemDataRole.UserRole, net["net"]); self.nets_list.addItem(item)

    def _net_from_list(self):
        items = self.nets_list.selectedItems()
        if items: self.highlight_net(items[0].data(Qt.ItemDataRole.UserRole))

    def highlight_net(self, net: str):
        self.selected_net = net
        self._highlight_net(net)
        if self.board:
            rows = [[p["part_ref"], p["pin_name"], p["side"]] for p in pins_on_net(self.board["id"], net, db_path=self.db)]
            fill_table(self.net_pins, rows)

    def _highlight_net(self, net: str, keep=False):
        for pin_id, item in self.pin_items.items():
            is_net = bool(net) and item.pin.get("net", "").lower() == net.lower()
            item.setBrush(QBrush(QColor("#00D1B2") if is_net else diode_color(item.pin.get("diode_mv"))))
            item.setScale(1.5 if is_net else 1.0)
            item.setZValue(5 if is_net else 1)

    def _pin_from_table(self):
        rows = self.pins_table.selectionModel().selectedRows()
        if not rows or not self.board: return
        part_ref = self.selection_label.text().split(" · ")[0]
        part = next((p for p in self.board["parts"] if p["ref"] == part_ref), None)
        if not part: return
        pin = part["pins"][rows[0].row()]
        self.selected_pin = pin
        if pin.get("net"): self.highlight_net(pin["net"])

    # ---------------- measurements & schematic
    def save_measurement(self):
        if not self.selected_pin:
            return QMessageBox.warning(self, "اندازه‌گیری", "اول یک پین را انتخاب کنید.")
        kind, unit = KIND_FA[self.meas_kind.currentText()]
        try:
            save_pin_measurement(self.selected_pin["id"], kind=kind,
                                 value=self.meas_value.value(), unit=unit,
                                 note=self.meas_note.text(),
                                 case_id=self.meas_case.currentData(), db_path=self.db)
        except Exception as exc:
            return QMessageBox.warning(self, "خطا", str(exc))
        board_id = self.board["id"]; ref = self.selection_label.text().split(" · ")[0]
        self._load_board_id(board_id); self.select_part(ref, pin_id=self.selected_pin["id"])

    def open_schematic(self):
        path, _ = QFileDialog.getOpenFileName(self, "شماتیک", "", "Schematic (*.png *.jpg *.jpeg *.pdf)")
        if not path: return
        if path.lower().endswith(".pdf"):
            if QPdfDocument is None:
                return QMessageBox.warning(self, "شماتیک", "ماژول PDF در این نصب Qt موجود نیست؛ عکس صفحه را باز کنید.")
            doc = QPdfDocument(self)
            if doc.load(path) != QPdfDocument.Error.None_:
                return QMessageBox.warning(self, "شماتیک", "خواندن PDF ناموفق بود.")
            size = doc.pagePointSize(0)
            from PySide6.QtCore import QSize
            image = doc.render(0, QSize(int(size.width() * 2), int(size.height() * 2)))
            pix = QPixmap.fromImage(image)
        else:
            pix = QPixmap(path)
        if pix.isNull():
            return QMessageBox.warning(self, "شماتیک", "تصویر شماتیک خوانده نشد.")
        self.schem_label.setPixmap(pix.scaled(720, 380, Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation))
        self.schem_label.setText("")
