from __future__ import annotations

import sys
import csv
import json
import math
import secrets
import threading
import time
import traceback
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

# Make the project root importable when launched directly from a .bat file.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import bcrypt
from PyQt6 import sip
from PyQt6.QtCore import (
    Qt, QTimer, QPoint, QPointF, QRectF, QEasingCurve, QPropertyAnimation, QVariantAnimation,
    QSequentialAnimationGroup, QThread, pyqtSignal
)
from PyQt6.QtGui import (
    QColor, QPainter, QPen, QBrush, QLinearGradient, QPainterPath, QPixmap, QFont, QFontMetrics, QPalette
)
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QCompleter, QDialog, QFileDialog, QFrame,
    QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QStackedWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QVBoxLayout, QWidget
)

from shared.admin_features import AdminFeatures
from shared.theme import LIGHT_QSS
from shared.config import load_config
from shared.api import SupabaseAPI, ApiError
from shared.setup import BackendSetup

# ============================================================
# THEME  (same palette as the kiosk)
# ============================================================
WHITE = "#FFFFFF"
BACKGROUND = "#F4F7FB"
TEXT = "#172B46"
MUTED = "#52647B"
MUTED_LIGHT = "#65768B"
BORDER = "#DCE5EF"
BANNER_1 = "#3177C6"
BANNER_2 = "#245DAD"
ACCENT = "#245DAD"
ACCENT_DARK = "#194A90"
ACCENT_LIGHT = "#EAF2FF"
SECONDARY = "#3E82E8"
SUCCESS = "#1BAA67"
SUCCESS_BG = "#EAF9F1"
DANGER = "#E5484D"
DANGER_BG = "#FDEEEE"
GOLD = "#F2B84B"
NAVY = "#172237"
PALETTE = [BANNER_2, SECONDARY, SUCCESS, GOLD, "#7C5CFF", BANNER_1, "#14B8A6", "#94A3B8"]

MOTION_ENABLED = True       # set False to disable fades / chart intro animations
BANNER_HEIGHT = 96
LOGO_SIZE = 68

APP_QSS = f"""
QMainWindow, QDialog {{ background:{BACKGROUND}; }}
QWidget {{ font-family:'Segoe UI'; color:{TEXT}; font-size:13px; }}
QLabel {{ background:transparent; }}
QLineEdit, QComboBox {{
    background:#FFFFFF; color:{TEXT}; border:none; border-bottom:3px solid #CDD9E7;
    border-radius:10px; padding:0 12px; min-height:44px; font-weight:700;
}}
QLineEdit:focus, QComboBox:focus {{ background:white; border-bottom:3px solid {BANNER_2}; }}
QLineEdit:read-only {{ background:#EEF3FA; color:{BANNER_2}; }}
QComboBox::drop-down {{ border:none; width:30px; }}
QComboBox QAbstractItemView {{
    background:white; color:{TEXT}; border:1px solid {BORDER};
    selection-background-color:{ACCENT_LIGHT}; selection-color:{ACCENT_DARK}; outline:0;
}}
QTableWidget {{
    background:white; alternate-background-color:#F3F6FB; border:none; gridline-color:transparent;
    selection-background-color:{ACCENT_LIGHT}; selection-color:{TEXT}; font-size:12px; outline:0;
}}
QTableWidget::item {{ padding:4px 10px; border-bottom:1px solid #E3EAF3; }}
QHeaderView::section {{
    background:#EAF0F8; color:{MUTED}; border:none; padding:10px; font-size:10px;
    font-weight:900; letter-spacing:1px;
}}
QTableCornerButton::section {{ background:#EAF0F8; border:none; }}
QScrollArea {{ border:none; background:transparent; }}
QScrollBar:vertical {{ background:transparent; width:12px; margin:2px; }}
QScrollBar::handle:vertical {{ background:#CED9E7; border-radius:5px; min-height:36px; }}
QScrollBar::handle:vertical:hover {{ background:#C9B9B0; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
QScrollBar:horizontal {{ background:transparent; height:12px; margin:2px; }}
QScrollBar::handle:horizontal {{ background:#CED9E7; border-radius:5px; min-width:36px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width:0; }}
QToolTip {{ background:{NAVY}; color:white; border:none; padding:6px 9px; }}
QWidget#anInner, QWidget#anViewport {{ background:{BACKGROUND}; }}
"""


# ============================================================
# SMALL HELPERS
# ============================================================

def clock() -> float:
    return time.monotonic()


def clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def mix(a, b, t: float) -> QColor:
    ca, cb = QColor(a), QColor(b)
    t = clamp01(t)
    return QColor(int(lerp(ca.red(), cb.red(), t)), int(lerp(ca.green(), cb.green(), t)),
                  int(lerp(ca.blue(), cb.blue(), t)), int(lerp(ca.alpha(), cb.alpha(), t)))


def with_alpha(color, alpha: float) -> QColor:
    c = QColor(color)
    c.setAlpha(int(max(0, min(255, alpha))))
    return c


def round_pen(color, width: float) -> QPen:
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def px_font(px: int, bold: bool = False) -> QFont:
    f = QFont("Segoe UI")
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def _drop_effect(widget, effect):
    try:
        if sip.isdeleted(widget) or sip.isdeleted(effect):
            return
        if widget.graphicsEffect() is effect:
            widget.setGraphicsEffect(None)
    except Exception:
        pass


def fade_in(widget, duration=320, delay=0):
    if not MOTION_ENABLED:
        return None
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity")
    anim.setDuration(int(duration))
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    group = QSequentialAnimationGroup(widget)
    if delay > 0:
        group.addPause(int(delay))
    group.addAnimation(anim)
    group.finished.connect(lambda: QTimer.singleShot(0, lambda: _drop_effect(widget, effect)))
    widget._fade_animation = group
    group.start()
    return group


def stagger_fade(widgets, start=0, step=70, duration=360):
    for i, w in enumerate(widgets):
        if w is not None:
            fade_in(w, duration, delay=start + i * step)


def count_up(label: QLabel, target: float, fmt: Optional[Callable[[float], str]] = None, duration=850):
    fmt = fmt or (lambda v: str(int(round(v))))
    prev = getattr(label, "_count_anim", None)
    if prev is not None:
        prev.stop()
    if not MOTION_ENABLED or not target:
        label.setText(fmt(float(target or 0)))
        return
    anim = QVariantAnimation(label)
    anim.setStartValue(0.0)
    anim.setEndValue(float(target))
    anim.setDuration(duration)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.valueChanged.connect(lambda v: label.setText(fmt(float(v))))
    anim.finished.connect(lambda: label.setText(fmt(float(target))))
    label._count_anim = anim
    anim.start()


def find_asset(*parts):
    rel = Path(*parts)
    bases = [Path(__file__).resolve().parent, PROJECT_ROOT, Path.cwd()]
    if getattr(sys, "frozen", False):
        bases.insert(0, Path(sys.executable).resolve().parent)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bases.insert(0, Path(meipass))
    for base in bases:
        candidate = base / rel
        if candidate.is_file():
            return candidate
    return None


class LogoBadge(QWidget):
    """Round white badge showing assets/school_logo.png (falls back to 'SMPCS' text)."""
    def __init__(self, size=56, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        path = find_asset("assets", "school_logo.png")
        pix = QPixmap(str(path)) if path else QPixmap()
        self._pix = None if pix.isNull() else pix

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        s = float(self.width())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("white"))
        p.drawEllipse(QRectF(0, 0, s, s))
        if self._pix is not None:
            clip = QPainterPath()
            clip.addEllipse(QRectF(1, 1, s - 2, s - 2))
            p.setClipPath(clip)
            pad = max(3, int(s * 0.05))
            side = int(s - 2 * pad)
            scaled = self._pix.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(int((s - scaled.width()) / 2), int((s - scaled.height()) / 2), scaled)
        else:
            p.setFont(px_font(max(12, int(s * 0.22)), True))
            p.setPen(QColor("#8D1E2D"))
            p.drawText(QRectF(0, 0, s, s), Qt.AlignmentFlag.AlignCenter, "SMPCS")
        p.end()


class BannerFrame(QFrame):
    """Coral gradient banner with a soft light streak (same as the kiosk)."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("bannerFrame")
        self.setStyleSheet("QFrame#bannerFrame{background:transparent;border:none;} "
                           "QFrame#bannerFrame QLabel{background:transparent;border:none;}")
        self._t0 = clock()
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self.update)
        self._timer.start()

    def paintEvent(self, _event):
        p = QPainter(self)
        w = float(self.width())
        g = QLinearGradient(0, 0, w, 0)
        g.setColorAt(0.0, QColor(BANNER_2))
        g.setColorAt(0.6, QColor("#2D73BC"))
        g.setColorAt(1.0, QColor("#3493B8"))
        p.fillRect(self.rect(), QBrush(g))
        cycle = ((clock() - self._t0) % 8.0) / 8.0
        if cycle < 0.55 and MOTION_ENABLED:
            x = lerp(-160.0, w + 160.0, cycle / 0.55)
            sh = QLinearGradient(x - 120, 0, x + 120, 0)
            sh.setColorAt(0.0, QColor(255, 255, 255, 0))
            sh.setColorAt(0.5, QColor(255, 255, 255, 46))
            sh.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.fillRect(self.rect(), QBrush(sh))
        p.end()


class ApiTask(QThread):
    """Runs a blocking API call off the UI thread."""
    done = pyqtSignal(object)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn
        self.result = None
        self.error = None
        self.on_ok = None
        self.on_err = None

    def run(self):
        try:
            self.result = self._fn()
        except Exception as exc:  # noqa: BLE001
            self.error = exc
        self.done.emit(self)


# ============================================================
# STYLED BUILDING BLOCKS
# ============================================================

def make_button(text, callback=None, kind="primary", height=46):
    b = QPushButton(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setMinimumHeight(height)
    grad = f"qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {BANNER_2},stop:1 {BANNER_1})"
    grad_h = f"qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #D92F4C,stop:1 #EE5A3B)"
    base = "border:none;border-radius:13px;padding:0 22px;font-size:12px;font-weight:900;"
    styles = {
        "primary": f"QPushButton{{background:{grad};color:white;{base}}} QPushButton:hover{{background:{grad_h};}} QPushButton:pressed{{background:#C82E48;}} QPushButton:disabled{{background:#E6DAD4;color:white;}}",
        "success": f"QPushButton{{background:{SUCCESS};color:white;{base}}} QPushButton:hover{{background:#159657;}} QPushButton:disabled{{background:#E6DAD4;}}",
        "secondary": f"QPushButton{{background:{WHITE};color:{TEXT};border:1px solid {BORDER};border-radius:13px;padding:0 20px;font-size:12px;font-weight:900;}} QPushButton:hover{{background:{ACCENT_LIGHT};color:{ACCENT_DARK};}} QPushButton:disabled{{color:{MUTED_LIGHT};}}",
        "danger": f"QPushButton{{background:{DANGER_BG};color:{DANGER};{base}}} QPushButton:hover{{background:{DANGER};color:white;}}",
        "ghost": f"QPushButton{{background:transparent;color:{MUTED};{base}}} QPushButton:hover{{background:{ACCENT_LIGHT};color:{ACCENT_DARK};}}",
    }
    b.setStyleSheet(styles.get(kind, styles["primary"]))
    if callback is not None:
        b.clicked.connect(lambda _=False: callback())
    return b


def field_label(text):
    lab = QLabel(text)
    lab.setStyleSheet(f"color:{TEXT};font-size:10px;font-weight:950;letter-spacing:1px;background:transparent;")
    return lab


class Card(QFrame):
    """White rounded card with an optional title / subtitle header."""
    def __init__(self, title="", subtitle="", padding=22, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setStyleSheet(f"QFrame#card{{background:{WHITE};border:none;border-radius:20px;}}")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(padding, padding - 4, padding, padding)
        self.lay.setSpacing(12)
        self.header = QHBoxLayout()
        self.header.setContentsMargins(0, 0, 0, 0)
        self.header.setSpacing(10)
        if title:
            col = QVBoxLayout()
            col.setSpacing(2)
            t = QLabel(title.upper())
            t.setStyleSheet(f"color:{BANNER_2};font-size:11px;font-weight:950;letter-spacing:1.4px;background:transparent;")
            col.addWidget(t)
            if subtitle:
                s = QLabel(subtitle)
                s.setWordWrap(True)
                s.setStyleSheet(f"color:{MUTED};font-size:11px;font-weight:650;background:transparent;")
                col.addWidget(s)
            self.header.addLayout(col)
            self.header.addStretch()
            hw = QWidget()
            hw.setLayout(self.header)
            hw.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            self.lay.addWidget(hw)

    def add_action(self, widget):
        self.header.addWidget(widget)


class KpiCard(QFrame):
    def __init__(self, title, color=BANNER_2, icon="●", parent=None):
        super().__init__(parent)
        self.setObjectName("kpi")
        self.setStyleSheet(f"QFrame#kpi{{background:{WHITE};border:none;border-radius:20px;}}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(4)
        top = QHBoxLayout()
        badge = QLabel(icon)
        badge.setFixedSize(34, 34)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tint = with_alpha(color, 32)
        badge.setStyleSheet(f"background:rgba({tint.red()},{tint.green()},{tint.blue()},{tint.alpha()});color:{color};border-radius:17px;font-size:15px;font-weight:900;")
        cap = QLabel(title.upper())
        cap.setStyleSheet(f"color:{MUTED};font-size:10px;font-weight:950;letter-spacing:1.2px;background:transparent;")
        top.addWidget(badge)
        top.addWidget(cap, 1)
        lay.addLayout(top)
        self.value = QLabel("0")
        self.value.setStyleSheet(f"color:{TEXT};font-size:34px;font-weight:950;background:transparent;")
        self.sub = QLabel("")
        self.sub.setStyleSheet(f"color:{MUTED};font-size:11px;font-weight:700;background:transparent;")
        self.sub.setWordWrap(True)
        lay.addWidget(self.value)
        lay.addWidget(self.sub)
        line = QFrame()
        line.setFixedHeight(4)
        line.setStyleSheet(f"background:{color};border:none;border-radius:2px;")
        lay.addWidget(line)

    def set_value(self, value, fmt=None, sub=None):
        if value is None:
            prev = getattr(self.value, "_count_anim", None)
            if prev is not None:
                prev.stop()
            self.value.setText("—")
        else:
            count_up(self.value, value, fmt)
        if sub is not None:
            self.sub.setText(sub)


class Segmented(QFrame):
    """Pill-shaped segmented control (used for the analytics period)."""
    changed = pyqtSignal(object)

    def __init__(self, options, current=0, parent=None):
        super().__init__(parent)
        self.setObjectName("seg")
        self.setStyleSheet(f"QFrame#seg{{background:{WHITE};border-radius:15px;}}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)
        self._buttons, self._values = [], []
        style = (f"QPushButton{{background:transparent;color:{MUTED};border:none;border-radius:11px;font-size:11px;font-weight:950;padding:0 14px;}}"
                 f"QPushButton:hover{{background:{ACCENT_LIGHT};color:{ACCENT_DARK};}}"
                 f"QPushButton:checked{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {BANNER_2},stop:1 {BANNER_1});color:white;}}")
        for i, (label, value) in enumerate(options):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFixedHeight(34)
            b.setMinimumWidth(58)
            b.setStyleSheet(style)
            b.clicked.connect(lambda _=False, i=i: self.select(i))
            lay.addWidget(b)
            self._buttons.append(b)
            self._values.append(value)
        self.select(current, emit=False)

    def select(self, i, emit=True):
        for j, b in enumerate(self._buttons):
            b.setChecked(j == i)
        if emit:
            self.changed.emit(self._values[i])


class Toast(QFrame):
    """Small slide-up notification that replaces 'Saved' message boxes."""
    def __init__(self, host):
        super().__init__(host)
        self.setObjectName("toast")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(22, 12, 22, 12)
        self.label = QLabel("")
        lay.addWidget(self.label)
        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._pos_anim = QPropertyAnimation(self, b"pos", self)
        self._pos_anim.setDuration(320)
        self._pos_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._op_anim = QPropertyAnimation(self._fx, b"opacity", self)
        self._op_anim.setDuration(260)
        self._op_anim.finished.connect(self._after_fade)
        self._dismissing = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._dismiss)
        self.hide()

    def show_message(self, text, kind="success"):
        color = {"success": SUCCESS, "error": DANGER}.get(kind, NAVY)
        self.setStyleSheet(f"QFrame#toast{{background:{color};border-radius:16px;}}")
        self.label.setStyleSheet("color:white;font-size:13px;font-weight:900;background:transparent;")
        self.label.setText(text)
        self.adjustSize()
        host = self.parentWidget()
        x = int((host.width() - self.width()) / 2)
        y = int(host.height() - self.height() - 30)
        self._dismissing = False
        self._op_anim.stop()
        self._pos_anim.stop()
        self.move(x, y + 26)
        self.show()
        self.raise_()
        self._pos_anim.setStartValue(self.pos())
        self._pos_anim.setEndValue(QPoint(x, y))
        self._pos_anim.start()
        self._op_anim.setStartValue(0.0)
        self._op_anim.setEndValue(1.0)
        self._op_anim.start()
        self._timer.start(2800 if kind != "error" else 4200)

    def _dismiss(self):
        self._dismissing = True
        self._op_anim.setStartValue(1.0)
        self._op_anim.setEndValue(0.0)
        self._op_anim.start()

    def _after_fade(self):
        if self._dismissing:
            self.hide()


def _box_style():
    return f"""
    QMessageBox {{ background:{WHITE}; }}
    QMessageBox QLabel {{ color:{TEXT}; background:transparent; font-size:14px; font-weight:650; }}
    QMessageBox QPushButton {{
        min-width:96px; min-height:42px; padding:6px 20px; border:none; border-radius:11px;
        background:{SECONDARY}; color:white; font-size:12px; font-weight:900;
    }}
    QMessageBox QPushButton:hover {{ background:#2F70C7; }}
    """


def msg(parent, title, text, kind="info"):
    box = QMessageBox(parent)
    box.setWindowTitle(str(title))
    box.setText(str(text))
    box.setIcon({"info": QMessageBox.Icon.Information, "warning": QMessageBox.Icon.Warning,
                 "error": QMessageBox.Icon.Critical}.get(kind, QMessageBox.Icon.Information))
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.setMinimumWidth(460)
    box.setStyleSheet(_box_style())
    return box.exec()


def confirm(parent, title, text, yes="Confirm") -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(str(title))
    box.setText(str(text))
    box.setIcon(QMessageBox.Icon.Question)
    y = box.addButton(yes, QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    box.setMinimumWidth(460)
    box.setStyleSheet(_box_style())
    box.exec()
    return box.clickedButton() is y


# ============================================================
# TABLE HELPERS
# ============================================================

def plain(v):
    if v is None or v == "":
        return "—"
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, (dict, list)):
        try:
            s = json.dumps(v, ensure_ascii=False)
        except Exception:
            s = str(v)
        return s if len(s) <= 140 else s[:137] + "…"
    return str(v)


def make_table(headers, min_height=220):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels([h.upper() for h in headers])
    t.verticalHeader().setVisible(False)
    t.verticalHeader().setDefaultSectionSize(44)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    t.setAlternatingRowColors(True)
    t.setShowGrid(False)
    t.setWordWrap(False)
    t.setMinimumHeight(min_height)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    t.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return t


def fill(table, rows, cols, color_fn=None):
    """cols = [(key, formatter(value,row)->str or None), ...]; the row dict is kept on column 0."""
    table.setUpdatesEnabled(False)
    table.setRowCount(0)
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, (key, fmt) in enumerate(cols):
            v = row.get(key) if isinstance(row, dict) else None
            item = QTableWidgetItem(fmt(v, row) if fmt else plain(v))
            if c == 0:
                item.setData(Qt.ItemDataRole.UserRole, row)
            if color_fn is not None:
                col = color_fn(row, c)
                if col is not None:
                    item.setForeground(QColor(col))
            table.setItem(r, c, item)
    table.setUpdatesEnabled(True)


def selected_row(table):
    r = table.currentRow()
    if r < 0:
        return None
    it = table.item(r, 0)
    return it.data(Qt.ItemDataRole.UserRole) if it else None


def filter_table(table, text):
    needle = (text or "").strip().lower()
    for r in range(table.rowCount()):
        if not needle:
            table.setRowHidden(r, False)
            continue
        hit = any(needle in (table.item(r, c).text().lower() if table.item(r, c) else "")
                  for c in range(table.columnCount()))
        table.setRowHidden(r, not hit)


def search_box(placeholder):
    e = QLineEdit()
    e.setPlaceholderText(placeholder)
    e.setClearButtonEnabled(True)
    e.setMinimumWidth(320)
    return e


# ---- ANALYTICS-CORE-BEGIN ------------------------------------------------
# (pure Python - no Qt - so it can be unit-tested on its own)

def parse_dt(v):
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        try:
            d = datetime.strptime(str(v)[:19], "%Y-%m-%dT%H:%M:%S")
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone()


def fmt_dt(v, with_time=True):
    d = parse_dt(v)
    if d is None:
        return "—" if not v else str(v)
    return d.strftime("%b %d, %Y  %I:%M %p" if with_time else "%b %d, %Y")


def to_int(v, default=0):
    try:
        return int(float(v))
    except Exception:
        return default


def compute_analytics(books, loans, members, days=30, now=None):
    now = now or datetime.now().astimezone()
    today = now.date()
    if days <= 31:
        mode, n = "day", max(1, days)
    elif days <= 120:
        mode, n = "week", int(math.ceil(days / 7.0))
    else:
        mode, n = "month", 12

    def bucket(d):
        dd = d.date()
        if mode == "day":
            delta = (today - dd).days
            return n - 1 - delta if 0 <= delta < n else None
        if mode == "week":
            delta = (today - dd).days
            return n - 1 - delta // 7 if 0 <= delta < n * 7 else None
        diff = (today.year - dd.year) * 12 + (today.month - dd.month)
        return n - 1 - diff if 0 <= diff < n else None

    labels = []
    for i in range(n):
        if mode == "day":
            labels.append((today - timedelta(days=n - 1 - i)).strftime("%b %d"))
        elif mode == "week":
            labels.append((today - timedelta(days=(n - 1 - i) * 7 + 6)).strftime("%b %d"))
        else:
            m, y = today.month - (n - 1 - i), today.year
            while m <= 0:
                m += 12
                y -= 1
            labels.append(date(y, m, 1).strftime("%b %y"))

    book_by_id = {b.get("id"): b for b in books if b.get("id") is not None}
    member_by_id = {m.get("id"): m for m in members if m.get("id") is not None}
    has_returns = any(l.get("returned_at") for l in loans)

    borrowed_series = [0] * n
    returned_series = [0] * n
    period_loans = []
    durations, ontime, ret_count = [], 0, 0
    for l in loans:
        bd = parse_dt(l.get("borrowed_at"))
        rd = parse_dt(l.get("returned_at"))
        if bd:
            i = bucket(bd)
            if i is not None:
                borrowed_series[i] += 1
                period_loans.append(l)
        if rd:
            j = bucket(rd)
            if j is not None:
                returned_series[j] += 1
                if bd:
                    durations.append(max(0.0, (rd - bd).total_seconds() / 86400.0))
                    ret_count += 1
                    dd = parse_dt(l.get("due_at"))
                    if dd is not None and rd.date() <= dd.date():
                        ontime += 1

    def book_title(bid):
        return (book_by_id.get(bid) or {}).get("title") or "Unknown book"

    def member_name(mid):
        return (member_by_id.get(mid) or {}).get("full_name") or "Unknown member"

    def member_grade(mid):
        m = member_by_id.get(mid) or {}
        gs = " • ".join(x for x in (str(m.get("grade_level") or "").strip(), str(m.get("section") or "").strip()) if x)
        return gs or "—"

    by_book = Counter(l.get("book_id") for l in period_loans)
    top_books = [(book_title(b), c, (book_by_id.get(b) or {}).get("author") or "") for b, c in by_book.most_common(8)]

    cat_counter = Counter(((book_by_id.get(l.get("book_id")) or {}).get("category") or "Uncategorized") for l in period_loans)
    cats = cat_counter.most_common()
    cat_segments = [(name, cnt) for name, cnt in cats[:5]]
    rest = sum(cnt for _, cnt in cats[5:])
    if rest:
        cat_segments.append(("Others", rest))

    by_member = Counter(l.get("member_id") for l in period_loans)
    top_borrowers = [(member_name(m), c, member_grade(m)) for m, c in by_member.most_common(8)]

    grade_counter = Counter((str((member_by_id.get(l.get("member_id")) or {}).get("grade_level") or "").strip() or "Unspecified")
                            for l in period_loans)
    by_grade = [(g, c, "") for g, c in grade_counter.most_common(8)]

    wd_counter = Counter()
    for l in period_loans:
        bd = parse_dt(l.get("borrowed_at"))
        if bd:
            wd_counter[bd.weekday()] += 1
    by_weekday = [(name, wd_counter.get(i, 0), "") for i, name in enumerate(("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"))]

    active = [l for l in loans if str(l.get("status", "")).lower() == "borrowed"]
    active_by_book = Counter(l.get("book_id") for l in active)
    overdue = []
    for l in active:
        dd = parse_dt(l.get("due_at"))
        if dd is not None and dd < now:
            overdue.append({
                "book": book_title(l.get("book_id")), "borrower": member_name(l.get("member_id")),
                "grade": member_grade(l.get("member_id")), "due_at": l.get("due_at"),
                "days": max(0, (today - dd.date()).days),
            })
    overdue.sort(key=lambda r: r["days"], reverse=True)

    total_copies = avail = unavailable = 0
    for b in books:
        av = to_int(b.get("available_copies"), 0)
        tc = b.get("total_copies")
        tc = to_int(tc, av) if tc is not None else av + active_by_book.get(b.get("id"), 0)
        total_copies += tc
        avail += av
        if av <= 0 and tc > 0:
            unavailable += 1

    idle = [{"title": b.get("title") or "—", "category": b.get("category") or "—", "shelf": b.get("shelf") or "—",
             "copies": b.get("available_copies") if b.get("available_copies") is not None else "—"}
            for b in books if by_book.get(b.get("id"), 0) == 0]
    idle.sort(key=lambda r: str(r["title"]).lower())

    on_loan_copies = max(0, total_copies - avail)
    return {
        "labels": labels, "borrowed_series": borrowed_series, "returned_series": returned_series if has_returns else None,
        "top_books": top_books, "cat_segments": cat_segments, "top_borrowers": top_borrowers,
        "by_grade": by_grade, "by_weekday": by_weekday, "overdue": overdue, "idle": idle,
        "kpi": {
            "titles": len(books), "categories": len({(b.get("category") or "") for b in books if b.get("category")}),
            "copies_total": total_copies, "copies_available": avail, "copies_on_loan": on_loan_copies,
            "utilization": (on_loan_copies / total_copies * 100.0) if total_copies else 0.0,
            "active_loans": len(active), "overdue": len(overdue), "loans_period": len(period_loans),
            "avg_days": (sum(durations) / len(durations)) if durations else None,
            "ontime_rate": (ontime / ret_count * 100.0) if ret_count else None,
            "idle_titles": len(idle), "unavailable_titles": unavailable,
        },
    }

# ---- ANALYTICS-CORE-END --------------------------------------------------


def select_all(api, table, select, extra="", page=1000, max_pages=40):
    """PostgREST returns at most ~1000 rows per request - page through everything."""
    rows = []
    for i in range(max_pages):
        chunk = api.select(table, f"?select={select}{extra}&limit={page}&offset={i * page}") or []
        rows.extend(chunk)
        if len(chunk) < page:
            break
    return rows


def select_first_ok(api, table, select_options, extra=""):
    """Try column lists from richest to poorest so a missing optional column never breaks the page."""
    last = None
    for cols in select_options:
        try:
            return select_all(api, table, cols, extra)
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise last if last else ApiError("Could not load data.")


# ============================================================
# CHARTS (custom painted, animated intro)
# ============================================================

def nice_max(v):
    if v <= 4:
        return 4
    raw = v / 4.0
    mag = 10 ** int(math.floor(math.log10(raw)))
    for m in (1, 2, 5, 10):
        if raw <= m * mag:
            return int(max(1, m * mag) * 4)
    return int(math.ceil(v))


def smooth_path(pts):
    path = QPainterPath(pts[0])
    for i in range(1, len(pts)):
        a, b = pts[i - 1], pts[i]
        cx = (a.x() + b.x()) / 2.0
        path.cubicTo(QPointF(cx, a.y()), QPointF(cx, b.y()), b)
    return path


class ChartBase(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._p = 1.0
        self._anim = None

    def play(self, duration=850):
        if self._anim is not None:
            self._anim.stop()
        if not MOTION_ENABLED:
            self._p = 1.0
            self.update()
            return
        a = QVariantAnimation(self)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.setDuration(duration)
        a.setEasingCurve(QEasingCurve.Type.OutCubic)
        a.valueChanged.connect(self._set_p)
        self._anim = a
        a.start()

    def _set_p(self, v):
        self._p = float(v)
        self.update()

    def draw_empty(self, p, text="No data for this period"):
        p.setPen(QColor(MUTED_LIGHT))
        p.setFont(px_font(13, True))
        p.drawText(QRectF(0, 0, self.width(), self.height()), Qt.AlignmentFlag.AlignCenter, text)


class TrendChart(ChartBase):
    LEFT, TOP, RIGHT, BOTTOM = 46, 38, 16, 32

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(290)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.labels, self.series, self._hover = [], [], -1

    def set_data(self, labels, series):
        self.labels, self.series, self._hover = labels, series, -1
        self.play()

    def _plot(self):
        return QRectF(self.LEFT, self.TOP, self.width() - self.LEFT - self.RIGHT, self.height() - self.TOP - self.BOTTOM)

    def mouseMoveEvent(self, e):
        n = len(self.labels)
        if n == 0:
            return
        plot = self._plot()
        idx = -1
        if plot.left() - 10 <= e.position().x() <= plot.right() + 10:
            rel = (e.position().x() - plot.left()) / max(1.0, plot.width())
            idx = int(round(clamp01(rel) * (n - 1))) if n > 1 else 0
        if idx != self._hover:
            self._hover = idx
            self.update()

    def leaveEvent(self, _e):
        self._hover = -1
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        plot = self._plot()
        n = len(self.labels)
        vmax = max([max(s["values"]) for s in self.series if s["values"]] + [0])
        # legend
        lx = float(self.LEFT)
        p.setFont(px_font(11, True))
        fm = QFontMetrics(p.font())
        for s in self.series:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(s["color"]))
            p.drawEllipse(QPointF(lx + 5, 16), 5, 5)
            p.setPen(QColor(TEXT))
            p.drawText(QPointF(lx + 16, 20), s["name"])
            lx += 16 + fm.horizontalAdvance(s["name"]) + 22
        if n == 0 or vmax <= 0:
            self.draw_empty(p)
            p.end()
            return
        top_v = nice_max(vmax)
        p.setFont(px_font(11))
        for i in range(5):
            y = plot.bottom() - plot.height() * i / 4.0
            p.setPen(QPen(QColor("#EFE5DF"), 1))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(0, y - 9, self.LEFT - 8, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(int(top_v * i / 4)))

        def xpos(i):
            return plot.left() + (plot.width() * i / (n - 1) if n > 1 else plot.width() / 2)

        ep = self._p
        for s in self.series:
            pts = [QPointF(xpos(i), plot.bottom() - (v / top_v) * plot.height() * ep) for i, v in enumerate(s["values"])]
            col = QColor(s["color"])
            if len(pts) > 1:
                line = smooth_path(pts)
                area = QPainterPath(line)
                area.lineTo(pts[-1].x(), plot.bottom())
                area.lineTo(pts[0].x(), plot.bottom())
                area.closeSubpath()
                g = QLinearGradient(0, plot.top(), 0, plot.bottom())
                g.setColorAt(0.0, with_alpha(col, 70))
                g.setColorAt(1.0, with_alpha(col, 0))
                p.fillPath(area, QBrush(g))
                p.setPen(round_pen(col, 3))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(line)
            if n <= 31:
                p.setPen(QPen(col, 2))
                p.setBrush(QColor("white"))
                for pt in pts:
                    p.drawEllipse(pt, 3.4, 3.4)
        # x labels
        p.setPen(QColor(MUTED))
        p.setFont(px_font(11))
        k = max(1, int(math.ceil(n / 9.0)))
        for i in range(0, n, k):
            p.drawText(QRectF(xpos(i) - 34, plot.bottom() + 8, 68, 16), Qt.AlignmentFlag.AlignCenter, self.labels[i])
        # hover
        if 0 <= self._hover < n and ep > 0.95:
            x = xpos(self._hover)
            p.setPen(QPen(QColor(with_alpha(NAVY, 90)), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            lines = [self.labels[self._hover]] + [f"{s['name']}: {s['values'][self._hover]}" for s in self.series]
            p.setFont(px_font(11, True))
            fm2 = QFontMetrics(p.font())
            bw = max(fm2.horizontalAdvance(t) for t in lines) + 24
            bh = 14 + 18 * len(lines)
            bx = min(max(6.0, x - bw / 2), self.width() - bw - 6)
            by = plot.top() + 4
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(NAVY))
            p.drawRoundedRect(QRectF(bx, by, bw, bh), 10, 10)
            p.setPen(QColor("white"))
            for i, t in enumerate(lines):
                p.drawText(QRectF(bx + 12, by + 8 + i * 18, bw - 16, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, t)
        p.end()


class HBarChart(ChartBase):
    ROW_H = 42

    def __init__(self, color=BANNER_2, rainbow=False, parent=None):
        super().__init__(parent)
        self.color = color
        self.rainbow = rainbow
        self.items = []
        self.setMinimumHeight(120)

    def set_data(self, items):
        self.items = list(items)
        self.setMinimumHeight(max(120, len(self.items) * self.ROW_H + 8))
        self.play()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self.items:
            self.draw_empty(p)
            p.end()
            return
        w = float(self.width())
        vmax = max(v for _, v, _ in self.items) or 1
        label_w = min(240.0, max(120.0, w * 0.38))
        val_w = 44.0
        track_x = label_w + 10
        track_w = max(20.0, w - track_x - val_w)
        for i, (label, value, sub) in enumerate(self.items):
            y = i * self.ROW_H + 4
            row_h = self.ROW_H - 8
            p.setFont(px_font(12, True))
            fm = QFontMetrics(p.font())
            p.setPen(QColor(TEXT))
            name = fm.elidedText(str(label), Qt.TextElideMode.ElideRight, int(label_w))
            if sub:
                p.drawText(QRectF(0, y, label_w, row_h / 2 + 2), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, name)
                p.setFont(px_font(10))
                p.setPen(QColor(MUTED))
                sub_t = QFontMetrics(p.font()).elidedText(str(sub), Qt.TextElideMode.ElideRight, int(label_w))
                p.drawText(QRectF(0, y + row_h / 2 + 3, label_w, row_h / 2 - 3), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, sub_t)
            else:
                p.drawText(QRectF(0, y, label_w, row_h), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)
            bar_h = 14.0
            by = y + (row_h - bar_h) / 2
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#F4F7FB"))
            p.drawRoundedRect(QRectF(track_x, by, track_w, bar_h), 7, 7)
            ep = clamp01(self._p * 1.35 - i * 0.07)
            bw = track_w * (value / vmax) * ep
            if value > 0 and bw > 0:
                bw = max(bar_h, bw)
                base = QColor(PALETTE[i % len(PALETTE)] if self.rainbow else self.color)
                g = QLinearGradient(track_x, 0, track_x + bw, 0)
                g.setColorAt(0.0, base)
                g.setColorAt(1.0, mix(base, "#FFC45D", 0.35))
                p.setBrush(QBrush(g))
                p.drawRoundedRect(QRectF(track_x, by, bw, bar_h), 7, 7)
            p.setPen(QColor(TEXT))
            p.setFont(px_font(12, True))
            p.drawText(QRectF(track_x + track_w + 8, y, val_w - 8, row_h), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(int(round(value * (1 if self._p > 0.6 else self._p / 0.6)))))
        p.end()


class DonutChart(ChartBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(230)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.segments = []          # (label, value, color)
        self.center_text = ""
        self.center_sub = ""

    def set_data(self, segments, center_text="", center_sub=""):
        self.segments = [(n, v, PALETTE[i % len(PALETTE)] if c is None else c) for i, (n, v, c) in enumerate(segments)]
        self.center_text, self.center_sub = center_text, center_sub
        self.play()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        size = min(h - 12, w * 0.46)
        cx, cy = 6 + size / 2, h / 2
        thick = size * 0.15
        ring = QRectF(cx - size / 2 + thick / 2, cy - size / 2 + thick / 2, size - thick, size - thick)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("#F4F7FB"), thick))
        p.drawEllipse(ring)
        total = sum(v for _, v, _ in self.segments)
        if total > 0:
            angle = 90.0
            gap = 2.5 if len(self.segments) > 1 else 0.0
            for _, v, col in self.segments:
                sweep = v / total * 360.0 * self._p
                pen = QPen(QColor(col), thick)
                pen.setCapStyle(Qt.PenCapStyle.FlatCap)
                p.setPen(pen)
                if sweep > gap:
                    p.drawArc(ring, int(angle * 16), int(-(sweep - gap) * 16))
                angle -= sweep
        p.setPen(QColor(TEXT))
        p.setFont(px_font(int(size * 0.17), True))
        p.drawText(QRectF(cx - size / 2, cy - size * 0.2, size, size * 0.24), Qt.AlignmentFlag.AlignCenter, self.center_text)
        p.setPen(QColor(MUTED))
        p.setFont(px_font(11, True))
        p.drawText(QRectF(cx - size / 2, cy + size * 0.05, size, 20), Qt.AlignmentFlag.AlignCenter, self.center_sub)
        # legend
        if total <= 0:
            p.setPen(QColor(MUTED_LIGHT))
            p.setFont(px_font(12, True))
            p.drawText(QRectF(size + 24, 0, w - size - 30, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "No data yet")
            p.end()
            return
        lx = size + 34
        row_h = 30.0
        y0 = cy - (len(self.segments) * row_h) / 2
        p.setFont(px_font(12, True))
        fm = QFontMetrics(p.font())
        for i, (name, v, col) in enumerate(self.segments):
            y = y0 + i * row_h
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(col))
            p.drawRoundedRect(QRectF(lx, y + 9, 12, 12), 4, 4)
            p.setPen(QColor(TEXT))
            label = fm.elidedText(str(name), Qt.TextElideMode.ElideRight, int(max(40, w - lx - 100)))
            p.drawText(QRectF(lx + 20, y, w - lx - 20, row_h), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(lx, y, w - lx - 6, row_h), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{v}  •  {v / total * 100:.0f}%")
        p.end()


# ============================================================
# DIALOGS
# ============================================================

def gradient_header(title, subtitle):
    head = QFrame()
    head.setObjectName("dlgHead")
    head.setStyleSheet(f"QFrame#dlgHead{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {BANNER_2},stop:.6 #2D73BC,stop:1 #3493B8);"
                       f"border-top-left-radius:22px;border-top-right-radius:22px;}}")
    lay = QHBoxLayout(head)
    lay.setContentsMargins(26, 20, 26, 20)
    lay.setSpacing(16)
    lay.addWidget(LogoBadge(64))
    col = QVBoxLayout()
    col.setSpacing(2)
    t = QLabel(title)
    t.setStyleSheet("color:white;font-size:22px;font-weight:950;background:transparent;")
    s = QLabel(subtitle)
    s.setStyleSheet("color:rgba(255,255,255,225);font-size:11px;font-weight:800;letter-spacing:1px;background:transparent;")
    col.addWidget(t)
    col.addWidget(s)
    lay.addLayout(col, 1)
    return head


class AdminLogin(QDialog):
    def __init__(self, api, parent=None):
        super().__init__(parent)
        self.api = api
        self.user = None
        self.setWindowTitle("SMPCS Library — Librarian Login")
        self.setFixedWidth(500)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(gradient_header("Librarian Login", "SMPCS LIBRARY  •  ADMINISTRATION"))
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(30, 26, 30, 28)
        lay.setSpacing(8)
        self.u = QLineEdit()
        self.u.setPlaceholderText("Enter your username")
        self.p = QLineEdit()
        self.p.setPlaceholderText("Enter your password")
        self.p.setEchoMode(QLineEdit.EchoMode.Password)
        self.err = QLabel("")
        self.err.setWordWrap(True)
        self.err.setStyleSheet(f"color:{DANGER};font-size:11px;font-weight:800;background:transparent;")
        self.btn = make_button("SIGN IN", self.login, height=52)
        lay.addWidget(field_label("USERNAME"))
        lay.addWidget(self.u)
        lay.addSpacing(4)
        lay.addWidget(field_label("PASSWORD"))
        lay.addWidget(self.p)
        lay.addWidget(self.err)
        lay.addSpacing(4)
        lay.addWidget(self.btn)
        self.update_btn=make_button("UPDATES / REPAIR — NO SIGN-IN NEEDED",self.open_login_updates,"secondary",42)
        lay.addWidget(self.update_btn)
        outer.addWidget(body)
        self.u.returnPressed.connect(self.p.setFocus)
        self.p.returnPressed.connect(self.login)

    def open_login_updates(self):
        from shared.updates import attach_updates
        controller=getattr(self,'update_controller',None)
        if controller is None:controller=attach_updates(self,public=True)
        controller.show_settings()

    def _shake(self):
        base = self.pos()
        a = QVariantAnimation(self)
        a.setDuration(420)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.valueChanged.connect(lambda v: self.move(base.x() + int(14 * math.sin(float(v) * 22) * (1 - float(v))), base.y()))
        a.finished.connect(lambda: self.move(base))
        self._shake_anim = a
        a.start()

    def login(self):
        self.err.setText("")
        self.btn.setEnabled(False)
        self.btn.setText("SIGNING IN…")
        QApplication.processEvents()
        try:
            from shared.services import login
            try:
                self.user = login(self.api,'staff',self.u.text().strip(),self.p.text())
            except ApiError as exc:
                if 'PGRST202' not in str(exc) and 'Could not find the function' not in str(exc):raise
                rows=self.api.rpc('library_login',{'p_username':self.u.text().strip()})
                user=rows if isinstance(rows,dict) else rows[0]
                if not bcrypt.checkpw(self.p.text().encode(),user['password_hash'].encode()):raise ApiError('Invalid username or password.')
                user.pop('password_hash',None);self.user=user
            self.p.clear()
            self.accept()
        except Exception as e:  # noqa: BLE001
            detail=str(e)
            if 'permission denied for function library_login' in detail:
                detail='This database requires a newer app. Click UPDATES / REPAIR below; no sign-in is needed.'
            self.err.setText(detail)
            self.p.selectAll()
            self.p.setFocus()
            self._shake()
        finally:
            self.btn.setEnabled(True)
            self.btn.setText("SIGN IN")


class FirstAdminDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.values = None
        self.setWindowTitle("Create First Administrator")
        self.setFixedWidth(520)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(gradient_header("Create Administrator", "FIRST-TIME SETUP"))
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(30, 24, 30, 28)
        lay.setSpacing(6)
        self.u, self.n, self.p, self.q = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.u.setPlaceholderText("Username")
        self.n.setPlaceholderText("Full name")
        self.p.setPlaceholderText("Password (at least 8 characters)")
        self.q.setPlaceholderText("Confirm password")
        for e in (self.p, self.q):
            e.setEchoMode(QLineEdit.EchoMode.Password)
        for lab, w in (("USERNAME", self.u), ("FULL NAME", self.n), ("PASSWORD", self.p), ("CONFIRM PASSWORD", self.q)):
            lay.addWidget(field_label(lab))
            lay.addWidget(w)
        self.err = QLabel("")
        self.err.setWordWrap(True)
        self.err.setStyleSheet(f"color:{DANGER};font-size:11px;font-weight:800;background:transparent;")
        lay.addWidget(self.err)
        lay.addWidget(make_button("CREATE ADMINISTRATOR", self.submit, height=52))
        outer.addWidget(body)

    def submit(self):
        if not self.u.text().strip() or not self.n.text().strip():
            self.err.setText("Username and full name are required.")
            return
        if self.p.text() != self.q.text() or len(self.p.text()) < 8:
            self.err.setText("Passwords must match and be at least 8 characters.")
            return
        self.values = (self.u.text().strip(), self.n.text().strip(), self.p.text())
        self.accept()


class TokenDialog(QDialog):
    def __init__(self, code, token, note, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Station Token")
        self.setFixedWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(8)
        t = QLabel(f"Station {code}")
        t.setStyleSheet(f"color:{TEXT};font-size:22px;font-weight:950;")
        n = QLabel(note)
        n.setWordWrap(True)
        n.setStyleSheet(f"color:{MUTED};font-size:12px;font-weight:650;")
        lay.addWidget(t)
        lay.addWidget(n)
        lay.addWidget(field_label("TOKEN"))
        self.field = QLineEdit(token)
        self.field.setReadOnly(True)
        lay.addWidget(self.field)
        row = QHBoxLayout()
        self.copy_btn = make_button("Copy token", self._copy, "secondary")
        row.addWidget(self.copy_btn)
        row.addStretch()
        row.addWidget(make_button("Close", self.accept))
        lay.addLayout(row)

    def _copy(self):
        QApplication.clipboard().setText(self.field.text())
        self.copy_btn.setText("Copied ✓")


# ============================================================
# MAIN WINDOW
# ============================================================

NAV_ITEMS = [
    ("dashboard", "Dashboard", "🏠"),
    ("approvals", "Borrow Approvals", "✅"),
    ("members", "Members", "👥"),
    ("accounts", "Accounts & Services", "⚙"),
    ("books", "Books", "📚"),
    ("analytics", "Book Analytics", "📊"),
    ("loans", "Loans", "🔄"),
    ("stations", "Kiosk Stations", "🖥"),
    ("printlogs", "Print Logs", "🖨"),
    ("attendance", "Attendance", "◷"),
    ("logs", "Audit / Logs", "🧾"),
]
PAGE_META = {
    "accounts": ("Accounts & Services", "Manage access, confirm returns and back up library records."),
    "attendance": ("Attendance history", "Search RFID visits, filter dates and export attendance records."),
    "dashboard": ("Library Dashboard", "A quick look at your library right now."),
    "approvals": ("Borrow Approvals", "Students who borrowed at the kiosk need your OK before they leave with the book."),
    "members": ("Members", "Register students and staff, and manage their RFID cards."),
    "books": ("Books", "Manage the catalog and the RFID tag on every book."),
    "analytics": ("Book Analytics", "What is being borrowed, by whom, and what needs attention."),
    "loans": ("Active Loans", "Every book that is currently out, with due dates."),
    "stations": ("Kiosk Stations", "Register kiosks and monitor whether they are online."),
    "printlogs": ("Print Logs", "Files printed from the kiosk's USB print station, and who printed them."),
    "logs": ("Audit / Logs", "The latest actions taken in the system."),
}


class AdminWindow(QMainWindow, AdminFeatures):
    def __init__(self, api, user):
        super().__init__()
        self.api = api
        self.user = user
        self._api_lock = threading.Lock()
        self._members_cache, self._books_cache, self._stations_cache = [], [], []
        self._pending_count, self._approval_ready = None, True
        self._an_raw, self._an_result, self._an_days, self._an_loaded_at = None, None, 30, 0.0
        self.setWindowTitle("SMPCS Library — Librarian / Admin")
        self.resize(1440, 900)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_banner())
        body = QHBoxLayout()
        body.setContentsMargins(20, 18, 20, 18)
        body.setSpacing(18)
        side_scroll=QScrollArea(); side_scroll.setWidgetResizable(True); side_scroll.setFixedWidth(264)
        side_scroll.setFrameShape(QFrame.Shape.NoFrame); side_scroll.setWidget(self._build_sidebar())
        body.addWidget(side_scroll)
        content = QVBoxLayout()
        content.setSpacing(14)
        self.page_title = QLabel("")
        self.page_title.setStyleSheet(f"color:{TEXT};font-size:30px;font-weight:950;")
        self.page_sub = QLabel("")
        self.page_sub.setStyleSheet(f"color:{MUTED};font-size:13px;font-weight:650;")
        head = QVBoxLayout()
        head.setSpacing(0)
        head.addWidget(self.page_title)
        head.addWidget(self.page_sub)
        content.addLayout(head)
        content.addLayout(self.build_quick_tools())
        self.stack = QStackedWidget()
        content.addWidget(self.stack, 1)
        body.addLayout(content, 1)
        outer.addLayout(body, 1)
        self.toast = Toast(root)

        self.pages = {}
        self._refreshers = {}
        self.build_dashboard(); self.build_members(); self.build_books(); self.build_analytics()
        self.build_loans(); self.build_approvals(); self.build_stations(); self.build_print_logs(); self.build_logs(); self.build_attendance(); self.build_accounts()
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start(1000)
        self._tick_clock()
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self.poll_pending)
        self._poll_timer.start(25000)
        QTimer.singleShot(1500, self.poll_pending)
        self.show_page("dashboard")

    # ---------------------------------------------------------------- shell
    def _build_banner(self):
        banner = BannerFrame()
        banner.setFixedHeight(BANNER_HEIGHT)
        lay = QHBoxLayout(banner)
        lay.setContentsMargins(28, 10, 28, 10)
        lay.setSpacing(18)
        lay.addWidget(LogoBadge(LOGO_SIZE), alignment=Qt.AlignmentFlag.AlignVCenter)
        brand = QVBoxLayout()
        brand.setSpacing(2)
        brand.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        s = QLabel("ST. MARTIN DE PORRES CATHOLIC SCHOOL, INC.")
        s.setStyleSheet("color:white;font-size:25px;font-weight:950;background:transparent;border:none;")
        l = QLabel("LIBRARY ADMINISTRATION   •   LIBRARIAN PORTAL")
        l.setStyleSheet("color:rgba(255,255,255,235);font-size:12px;font-weight:800;letter-spacing:1.8px;background:transparent;border:none;")
        brand.addWidget(s)
        brand.addWidget(l)
        lay.addLayout(brand, 1)
        clock_col = QVBoxLayout()
        clock_col.setSpacing(0)
        clock_col.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.clock_lbl = QLabel()
        self.clock_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.clock_lbl.setStyleSheet("color:white;font-size:32px;font-weight:950;background:transparent;border:none;")
        self.date_lbl = QLabel()
        self.date_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.date_lbl.setStyleSheet("color:rgba(255,255,255,235);font-size:12px;font-weight:700;background:transparent;border:none;")
        clock_col.addWidget(self.clock_lbl)
        clock_col.addWidget(self.date_lbl)
        lay.addLayout(clock_col)
        return banner

    def _tick_clock(self):
        now = datetime.now()
        self.clock_lbl.setText(now.strftime("%I:%M:%S %p"))
        self.date_lbl.setText(now.strftime("%A, %B %d, %Y"))

    def _build_sidebar(self):
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(250)
        side.setStyleSheet(f"QFrame#sidebar{{background:white;border:1px solid #DCE5EF;border-radius:20px;}}")
        lay = QVBoxLayout(side)
        lay.setContentsMargins(16, 20, 16, 16)
        lay.setSpacing(6)
        cap = QLabel("MENU")
        cap.setStyleSheet("color:#52647B;font-size:10px;font-weight:950;letter-spacing:2px;padding-left:10px;background:transparent;")
        lay.addWidget(cap)
        self.nav_buttons = {}
        style = ("QPushButton{color:#334C6C;background:transparent;border:none;border-left:5px solid transparent;"
                 "border-radius:14px;text-align:left;padding:0 16px;font-size:13px;font-weight:800;}"
                 "QPushButton:hover{background:#F0F5FC;color:#172B46;}"
                 f"QPushButton:checked{{background:#DBEAFE;color:#172B46;border-left:5px solid {BANNER_1};}}")
        for key, label, icon in NAV_ITEMS:
            b = QPushButton(f"{icon}    {label}")
            b.setCheckable(True)
            b.setMinimumHeight(42)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(style)
            b.clicked.connect(lambda _=False, k=key: self.show_page(k))
            lay.addWidget(b)
            self.nav_buttons[key] = b
        lay.addStretch()
        name = str(self.user.get("full_name") or self.user.get("username") or "Librarian")
        role = str(self.user.get("role") or "LIBRARIAN").upper()
        chip = QFrame()
        chip.setObjectName("userchip")
        chip.setStyleSheet("QFrame#userchip{background:#F0F5FC;border-radius:16px;}")
        cl = QHBoxLayout(chip)
        cl.setContentsMargins(12, 10, 12, 10)
        cl.setSpacing(10)
        av = QLabel(name[:1].upper())
        av.setFixedSize(40, 40)
        av.setAlignment(Qt.AlignmentFlag.AlignCenter)
        av.setStyleSheet(f"background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {BANNER_2},stop:1 {BANNER_1});color:#172B46;border-radius:20px;font-size:16px;font-weight:950;")
        col = QVBoxLayout()
        col.setSpacing(0)
        n = QLabel(name)
        n.setStyleSheet("color:#172B46;font-size:13px;font-weight:900;background:transparent;")
        r = QLabel(role)
        r.setStyleSheet("color:#52647B;font-size:9px;font-weight:900;letter-spacing:1.2px;background:transparent;")
        col.addWidget(n)
        col.addWidget(r)
        cl.addWidget(av)
        cl.addLayout(col, 1)
        lay.addWidget(chip)
        out = QPushButton("⏻    Sign out")
        out.setMinimumHeight(48)
        out.setCursor(Qt.CursorShape.PointingHandCursor)
        out.setStyleSheet("QPushButton{background:rgba(229,72,77,46);color:#A02535;border:none;border-radius:14px;font-size:13px;font-weight:900;}"
                          "QPushButton:hover{background:#E5484D;color:#172B46;}")
        out.clicked.connect(self.sign_out)
        lay.addWidget(out)
        return side

    def sign_out(self):
        from shared.services import account
        if not self.user.get('token'):self.close();return
        self.load(lambda:account(self.api,self.user,'logout'),lambda _:self.close(),lambda _:self.close())

    def add_page(self, name, widget, refresh):
        scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(widget)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.pages[name] = scroll
        self._refreshers[name] = refresh
        self.stack.addWidget(scroll)

    def show_page(self, name):
        page = self.pages.get(name)
        if page is None:
            msg(self, "Page error", f"The page '{name}' has not been initialized.", "error")
            return
        for k, b in self.nav_buttons.items():
            b.setChecked(k == name)
        self.page_title.setText(PAGE_META[name][0])
        self.page_sub.setText(PAGE_META[name][1])
        self.current_page = name
        self.stack.setCurrentWidget(page)
        fade_in(page, 260)
        self._refreshers[name]()

    # ---------------------------------------------------------------- async
    def load(self, fn, on_ok, on_err=None):
        def locked():
            with self._api_lock:
                return fn()
        task = ApiTask(locked, self)
        task.on_ok = on_ok
        task.on_err = on_err
        task.done.connect(self._task_done)
        task.finished.connect(task.deleteLater)
        task.start()

    def _task_done(self, task):
        try:
            if task.error is not None:
                if task.on_err:
                    task.on_err(task.error)
                else:
                    self.toast.show_message(str(task.error), "error")
            else:
                task.on_ok(task.result)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self.toast.show_message(str(exc), "error")

    # ---------------------------------------------------------------- dashboard
    def build_dashboard(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)
        row = QHBoxLayout()
        row.setSpacing(16)
        self.kd_members = KpiCard("Members", SECONDARY, "👥")
        self.kd_books = KpiCard("Book titles", BANNER_2, "📚")
        self.kd_borrowed = KpiCard("Borrowed now", SUCCESS, "🔄")
        self.kd_overdue = KpiCard("Overdue", DANGER, "⏰")
        for k in (self.kd_members, self.kd_books, self.kd_borrowed, self.kd_overdue):
            row.addWidget(k)
        lay.addLayout(row)
        bottom = QHBoxLayout()
        bottom.setSpacing(16)
        act = Card("Recent activity", "The latest actions in the system")
        self.dash_table = make_table(["Who", "Action", "Item", "When"], 300)
        act.lay.addWidget(self.dash_table)
        quick = Card("Quick actions", "Jump straight to a task")
        quick.setFixedWidth(340)
        for text, page, kind in (("✅  Review borrow approvals", "approvals", "success"), ("➕  Add a member", "members", "primary"), ("📖  Add a book", "books", "secondary"),
                                 ("📊  Open book analytics", "analytics", "secondary"), ("🖥  Manage kiosk stations", "stations", "secondary")):
            quick.lay.addWidget(make_button(text, lambda p=page: self.show_page(p), kind, 52))
        quick.lay.addStretch()
        bottom.addWidget(act, 1)
        bottom.addWidget(quick)
        lay.addLayout(bottom, 1)
        self._dash_cards = [self.kd_members, self.kd_books, self.kd_borrowed, self.kd_overdue]
        self.add_page("dashboard", w, self.refresh_dashboard)

    def refresh_dashboard(self):
        def job():
            d = self.api.rpc("library_dashboard") or {}
            if isinstance(d, list):
                d = d[0] if d else {}
            logs = self.api.select("library_audit_log", "?select=actor_username,action,entity_type,created_at&order=created_at.desc&limit=8") or []
            return d, logs

        def ok(res):
            d, logs = res
            self.kd_members.set_value(to_int(d.get("members")), sub="registered library members")
            self.kd_books.set_value(to_int(d.get("books")), sub="titles in the catalog")
            self.kd_borrowed.set_value(to_int(d.get("borrowed")), sub="books currently on loan")
            self.kd_overdue.set_value(to_int(d.get("overdue")), sub="past their due date")
            fill(self.dash_table, logs, [("actor_username", None), ("action", None), ("entity_type", None), ("created_at", lambda v, r: fmt_dt(v))])
        self.load(job, ok, lambda e: msg(self, "Dashboard", str(e), "error"))

    # ---------------------------------------------------------------- members
    def build_members(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)
        form = Card("Member details", "Fill in the fields, or click a member in the list to edit them.")
        self.mno, self.mrfid, self.mname = QLineEdit(), QLineEdit(), QLineEdit()
        self.mgrade, self.msection = QLineEdit(), QLineEdit()
        self.mtype = QComboBox()
        self.mtype.addItems(["student", "employee", "guest", "teacher", "staff", "other"])
        self.mno.setPlaceholderText("e.g. 2024-0001")
        self.mrfid.setPlaceholderText("Tap the card or type the UID")
        self.mname.setPlaceholderText("Complete name")
        self.mgrade.setPlaceholderText("e.g. Grade 10")
        self.msection.setPlaceholderText("e.g. St. Martin")
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)
        for i, (lab, wd) in enumerate([("MEMBER NO", self.mno), ("RFID UID", self.mrfid), ("FULL NAME", self.mname),
                                       ("TYPE", self.mtype), ("GRADE / LEVEL", self.mgrade), ("SECTION", self.msection)]):
            r, c = (i // 3) * 2, i % 3
            grid.addWidget(field_label(lab), r, c)
            grid.addWidget(wd, r + 1, c)
        form.lay.addLayout(grid)
        btns = QHBoxLayout()
        btns.addWidget(make_button("💾  Save member", self.save_member))
        from shared.account_ui import member_access
        btns.addWidget(make_button("Account access / PIN",lambda:member_access(self),"secondary"))
        btns.addWidget(make_button("Clear form", self.clear_member_form, "secondary"))
        btns.addStretch()
        form.lay.addLayout(btns)
        lst = Card("All members")
        self.msearch = search_box("Search name, member no, RFID, grade…")
        lst.add_action(self.msearch)
        lst.add_action(make_button("↻ Refresh", self.refresh_members, "secondary", 44))
        self.mtable = make_table(["Member No", "RFID", "Name", "Type", "Grade", "Section", "Status"], 300)
        self.mtable.itemSelectionChanged.connect(self.member_selected)
        self.msearch.textChanged.connect(lambda t: filter_table(self.mtable, t))
        lst.lay.addWidget(self.mtable)
        lay.addWidget(form)
        lay.addWidget(lst, 1)
        self.add_page("members", w, self.refresh_members)

    def refresh_members(self):
        def ok(rows):
            self._members_cache = rows
            fill(self.mtable, rows, [("member_no", None), ("rfid_uid", None), ("full_name", None), ("member_type", None),
                                     ("grade_level", None), ("section", None),
                                     ("active", lambda v, r: "● Active" if v else "○ Inactive")],
                 lambda row, c: (SUCCESS if row.get("active") else MUTED_LIGHT) if c == 6 else None)
            filter_table(self.mtable, self.msearch.text())
        self.load(lambda: select_all(self.api, "library_members", "id,member_no,rfid_uid,full_name,member_type,grade_level,section,active", "&order=full_name"),
                  ok, lambda e: msg(self, "Members", str(e), "error"))

    def member_selected(self):
        row = selected_row(self.mtable)
        if not row:
            return
        self.mno.setText(str(row.get("member_no") or ""))
        self.mrfid.setText(str(row.get("rfid_uid") or ""))
        self.mname.setText(str(row.get("full_name") or ""))
        self.mgrade.setText(str(row.get("grade_level") or ""))
        self.msection.setText(str(row.get("section") or ""))
        t = str(row.get("member_type") or "student")
        if self.mtype.findText(t) < 0:
            self.mtype.addItem(t)
        self.mtype.setCurrentText(t)

    def clear_member_form(self):
        for e in (self.mno, self.mrfid, self.mname, self.mgrade, self.msection):
            e.clear()
        self.mtype.setCurrentIndex(0)
        self.mtable.clearSelection()

    def save_member(self):
        if not self.mno.text().strip() or not self.mname.text().strip():
            msg(self, "Save member", "Member No and Full Name are required.", "warning")
            return
        rfid = self.mrfid.text().strip()
        if rfid:
            other = next((m for m in self._members_cache if str(m.get("rfid_uid") or "") == rfid
                          and str(m.get("member_no") or "") != self.mno.text().strip()), None)
            if other and not confirm(self, "RFID already assigned",
                                     f"This RFID card is already assigned to {other.get('full_name')} ({other.get('member_no')}).\n\n"
                                     "Saving will move the card to this member. Continue?", "Move card"):
                return
        payload = {"p_member_no": self.mno.text(), "p_rfid_uid": self.mrfid.text(), "p_full_name": self.mname.text(),
                   "p_member_type": self.mtype.currentText() or "student", "p_grade_level": self.mgrade.text(), "p_section": self.msection.text()}

        def ok(_):
            self.toast.show_message("Member saved ✓")
            self.refresh_members()
        from shared.services import account
        data={k.removeprefix("p_"):v for k,v in payload.items()}
        self.load(lambda: account(self.api,self.user,"member_save",data), ok, lambda e: msg(self, "Save failed", str(e), "error"))

    # ---------------------------------------------------------------- books
    def build_accounts(self):
        from shared.account_ui import staff_accounts,return_requests,backup_dialog,member_access
        page=QWidget();lay=QVBoxLayout(page);lay.setContentsMargins(0,0,0,0);lay.setSpacing(16)
        grid=QGridLayout();grid.setSpacing(16)
        items=[('Staff accounts','Create staff logins, assign roles and reset passwords.',lambda:staff_accounts(self),True),
               ('Member access / PIN','Select a member to manage access and library PIN.',lambda:self.show_page('members'),False),
               ('Pending book returns','Confirm returned books after receiving them at the desk.',lambda:return_requests(self),False),
               ('Backups','Save and locate your operational records backups.',lambda:backup_dialog(self),True)]
        for i,(title,description,fn,admin_only) in enumerate(items):
            card=Card(title,description)
            b=make_button('Open '+title.lower(),fn,height=44);b.setEnabled(not admin_only or self.user.get('role')=='admin');card.lay.addWidget(b)
            grid.addWidget(card,i//2,i%2)
        grid.setColumnStretch(0,1);grid.setColumnStretch(1,1);lay.addLayout(grid)
        self.backup_status=QLabel('');self.backup_status.setWordWrap(True);lay.addWidget(self.backup_status);lay.addStretch()
        if not self.user.get('token'):self.backup_status.setText('New services need the v1.5 database migration: migrations/002_accounts_services.sql. Existing pages remain available.')
        self.add_page('accounts',page,lambda:None)
        self.backup_timer=QTimer(self);self.backup_timer.timeout.connect(self.auto_backup);self.backup_timer.start(3600000)
        QTimer.singleShot(5000,self.auto_backup)

    def auto_backup(self):
        if self.user.get('role')!='admin' or not self.user.get('token') or getattr(self,'_backup_busy',False):return
        from shared.services import save_backup
        from shared.config import APP_DIR
        from datetime import datetime,timezone
        folder=APP_DIR/'backups';today=datetime.now(timezone.utc).strftime('%Y%m%d')
        if folder.exists() and any(folder.glob('library-'+today+'-*.json')):return
        self._backup_busy=True
        def done(text):self._backup_busy=False;self.backup_status.setText(text)
        self.load(lambda:save_backup(self.api,self.user),lambda path:done('Automatic backup saved: '+path),lambda exc:done('Automatic backup failed: '+str(exc)))

    def build_books(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)
        form = Card("Book details", "Fill in the fields, or click a book in the list to edit it.")
        self.brfid, self.bacc, self.btitle, self.bauthor = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.bcat, self.bshelf, self.bcopies = QLineEdit(), QLineEdit(), QLineEdit("1")
        self.brfid.setPlaceholderText("Tap the book tag or type the UID")
        self.bacc.setPlaceholderText("Accession number")
        self.btitle.setPlaceholderText("Book title")
        self.bauthor.setPlaceholderText("Author")
        self.bcat.setPlaceholderText("e.g. Science")
        self.bshelf.setPlaceholderText("e.g. A-3")
        self.bcopies.setPlaceholderText("Number of copies")
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)
        for i, (lab, wd) in enumerate([("BOOK RFID", self.brfid), ("ACCESSION NO", self.bacc), ("TITLE", self.btitle),
                                       ("AUTHOR", self.bauthor), ("CATEGORY", self.bcat), ("SHELF", self.bshelf), ("COPIES", self.bcopies)]):
            r, c = (i // 3) * 2, i % 3
            grid.addWidget(field_label(lab), r, c)
            grid.addWidget(wd, r + 1, c)
        form.lay.addLayout(grid)
        btns = QHBoxLayout()
        btns.addWidget(make_button("💾  Save book", self.save_book))
        btns.addWidget(make_button("Clear form", self.clear_book_form, "secondary"))
        btns.addStretch()
        form.lay.addLayout(btns)
        lst = Card("All books")
        self.bsearch = search_box("Search title, author, category, shelf…")
        lst.add_action(self.bsearch)
        lst.add_action(make_button("↻ Refresh", self.refresh_books, "secondary", 44))
        self.btable = make_table(["RFID", "Accession", "Title", "Author", "Category", "Shelf", "Available"], 300)
        self.btable.itemSelectionChanged.connect(self.book_selected)
        self.bsearch.textChanged.connect(lambda t: filter_table(self.btable, t))
        lst.lay.addWidget(self.btable)
        lay.addWidget(form)
        lay.addWidget(lst, 1)
        self.add_page("books", w, self.refresh_books)

    def refresh_books(self):
        def ok(rows):
            self._books_cache = rows
            cats = sorted({str(r.get("category")) for r in rows if r.get("category")})
            comp = QCompleter(cats, self.bcat)
            comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            self.bcat.setCompleter(comp)

            def avail(v, r):
                total = r.get("total_copies")
                return f"{plain(v)} / {total}" if total is not None else plain(v)
            fill(self.btable, rows, [("book_rfid", None), ("accession_no", None), ("title", None), ("author", None),
                                     ("category", None), ("shelf", None), ("available_copies", avail)],
                 lambda row, c: (DANGER if to_int(row.get("available_copies"), 1) <= 0 else None) if c == 6 else None)
            filter_table(self.btable, self.bsearch.text())
        self.load(lambda: select_first_ok(self.api, "library_books",
                                          ["book_rfid,accession_no,title,author,category,shelf,available_copies,total_copies",
                                           "book_rfid,accession_no,title,author,category,shelf,available_copies"], "&order=title"),
                  ok, lambda e: msg(self, "Books", str(e), "error"))

    def book_selected(self):
        row = selected_row(self.btable)
        if not row:
            return
        self.brfid.setText(str(row.get("book_rfid") or ""))
        self.bacc.setText(str(row.get("accession_no") or ""))
        self.btitle.setText(str(row.get("title") or ""))
        self.bauthor.setText(str(row.get("author") or ""))
        self.bcat.setText(str(row.get("category") or ""))
        self.bshelf.setText(str(row.get("shelf") or ""))
        self.bcopies.setText(str(row.get("total_copies") if row.get("total_copies") is not None else "1"))

    def clear_book_form(self):
        for e in (self.brfid, self.bacc, self.btitle, self.bauthor, self.bcat, self.bshelf):
            e.clear()
        self.bcopies.setText("1")
        self.btable.clearSelection()

    def save_book(self):
        if not self.btitle.text().strip() or not self.brfid.text().strip():
            msg(self, "Save book", "Book RFID and Title are required.", "warning")
            return
        try:
            copies = int(self.bcopies.text() or "1")
            if copies < 1:
                raise ValueError
        except ValueError:
            msg(self, "Save book", "Copies must be a whole number of at least 1.", "warning")
            return
        payload = {"p_book_rfid": self.brfid.text(), "p_accession_no": self.bacc.text(), "p_title": self.btitle.text(),
                   "p_author": self.bauthor.text(), "p_category": self.bcat.text(), "p_shelf": self.bshelf.text(), "p_total_copies": copies}

        def ok(_):
            self.toast.show_message("Book saved ✓")
            self.refresh_books()
        self.load(lambda: self.api.rpc("library_save_book", payload), ok, lambda e: msg(self, "Save failed", str(e), "error"))

    # ---------------------------------------------------------------- analytics
    def build_analytics(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        inner.setObjectName("anInner")
        scroll.viewport().setObjectName("anViewport")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(16)
        bar = QHBoxLayout()
        bar.setSpacing(12)
        bar.addWidget(QLabel("Period"))
        self.seg = Segmented([("7 days", 7), ("30 days", 30), ("90 days", 90), ("12 months", 365)], 1)
        self.seg.changed.connect(self.analytics_period)
        bar.addWidget(self.seg)
        self.an_status = QLabel("")
        self.an_status.setStyleSheet(f"color:{MUTED};font-size:12px;font-weight:700;")
        bar.addWidget(self.an_status)
        bar.addStretch()
        bar.addWidget(make_button("↻  Refresh", self.load_analytics, "secondary", 44))
        bar.addWidget(make_button("⬇  Export CSV", self.export_analytics, "secondary", 44))
        lay.addLayout(bar)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        self.k_loans = KpiCard("Borrowed in period", BANNER_2, "📖")
        self.k_active = KpiCard("On loan now", SECONDARY, "🔄")
        self.k_overdue = KpiCard("Overdue", DANGER, "⏰")
        self.k_avail = KpiCard("Copies available", SUCCESS, "✅")
        self.k_titles = KpiCard("Book titles", "#7C5CFF", "📚")
        self.k_avg = KpiCard("Avg. loan length", GOLD, "⏱")
        self.k_ontime = KpiCard("On-time returns", "#14B8A6", "🎯")
        self.k_idle = KpiCard("Not borrowed", "#94A3B8", "💤")
        self._an_cards = [self.k_loans, self.k_active, self.k_overdue, self.k_avail, self.k_titles, self.k_avg, self.k_ontime, self.k_idle]
        for i, k in enumerate(self._an_cards):
            grid.addWidget(k, i // 4, i % 4)
        lay.addLayout(grid)

        r1 = QHBoxLayout()
        r1.setSpacing(16)
        c_trend = Card("Borrowing trend", "Books borrowed and returned over time  •  hover for details")
        self.trend = TrendChart()
        c_trend.lay.addWidget(self.trend)
        c_util = Card("Copies on loan", "How much of the collection is out")
        c_util.setFixedWidth(430)
        self.util = DonutChart()
        c_util.lay.addWidget(self.util)
        r1.addWidget(c_trend, 1)
        r1.addWidget(c_util)
        lay.addLayout(r1)

        r2 = QHBoxLayout()
        r2.setSpacing(16)
        c_top = Card("Most borrowed books", "Top titles in the selected period")
        self.top_books = HBarChart(BANNER_2)
        c_top.lay.addWidget(self.top_books)
        c_top.lay.addStretch(1)
        c_cat = Card("Popular categories", "Share of loans by category")
        c_cat.setFixedWidth(430)
        self.cats = DonutChart()
        c_cat.lay.addWidget(self.cats)
        r2.addWidget(c_top, 1)
        r2.addWidget(c_cat)
        lay.addLayout(r2)

        r3 = QHBoxLayout()
        r3.setSpacing(16)
        c_b = Card("Top borrowers", "Members who borrowed the most")
        self.borrowers = HBarChart(SECONDARY)
        c_b.lay.addWidget(self.borrowers)
        c_b.lay.addStretch(1)
        c_g = Card("Borrowing by grade level")
        self.grades = HBarChart(SUCCESS)
        c_g.lay.addWidget(self.grades)
        c_g.lay.addStretch(1)
        c_w = Card("Busiest days of the week")
        self.weekdays = HBarChart(GOLD)
        c_w.lay.addWidget(self.weekdays)
        c_w.lay.addStretch(1)
        for c in (c_b, c_g, c_w):
            r3.addWidget(c, 1)
        lay.addLayout(r3)

        r4 = QHBoxLayout()
        r4.setSpacing(16)
        c_o = Card("Overdue books", "Needs follow-up with the borrower")
        self.overdue_table = make_table(["Book", "Borrower", "Grade / Section", "Due", "Days overdue"], 320)
        c_o.lay.addWidget(self.overdue_table)
        c_i = Card("Not borrowed in this period", "Candidates for display, promotion, or weeding")
        self.idle_table = make_table(["Title", "Category", "Shelf", "Available"], 320)
        c_i.lay.addWidget(self.idle_table)
        r4.addWidget(c_o, 3)
        r4.addWidget(c_i, 2)
        lay.addLayout(r4)
        lay.addStretch()
        scroll.setWidget(inner)
        self.add_page("analytics", scroll, self.maybe_load_analytics)

    def analytics_period(self, days):
        self._an_days = int(days)
        self.render_analytics()

    def maybe_load_analytics(self):
        if self._an_raw and (clock() - self._an_loaded_at) < 90:
            self.render_analytics()
        else:
            self.load_analytics()

    def load_analytics(self):
        self.an_status.setText("Loading…")

        def job():
            books = select_first_ok(self.api, "library_books",
                                    ["id,title,author,category,shelf,total_copies,available_copies", "id,title,author,category,shelf,available_copies",
                                     "id,title,category,available_copies"], "&order=title")
            loans = select_first_ok(self.api, "library_loans",
                                    ["id,member_id,book_id,borrowed_at,due_at,returned_at,status", "id,member_id,book_id,borrowed_at,due_at,status"],
                                    "&order=borrowed_at.desc")
            members = select_first_ok(self.api, "library_members", ["id,full_name,grade_level,section,member_type", "id,full_name"])
            return books, loans, members

        def ok(res):
            self._an_raw = res
            self._an_loaded_at = clock()
            self.an_status.setText(f"Updated {datetime.now().strftime('%I:%M %p')}  •  {len(res[1])} loans analysed")
            self.render_analytics()

        def err(e):
            self.an_status.setText("Could not load analytics")
            msg(self, "Book analytics", str(e), "error")
        self.load(job, ok, err)

    def render_analytics(self):
        if not self._an_raw:
            return
        books, loans, members = self._an_raw
        r = compute_analytics(books, loans, members, self._an_days)
        self._an_result = r
        k = r["kpi"]
        self.k_loans.set_value(k["loans_period"], sub="loans in the selected period")
        self.k_active.set_value(k["active_loans"], sub=f"{k['utilization']:.0f}% of all copies")
        self.k_overdue.set_value(k["overdue"], sub="books past their due date")
        self.k_avail.set_value(k["copies_available"], sub=f"of {k['copies_total']} total copies")
        self.k_titles.set_value(k["titles"], sub=f"{k['categories']} categor{'y' if k['categories'] == 1 else 'ies'}  •  {k['unavailable_titles']} fully checked out")
        self.k_avg.set_value(k["avg_days"], fmt=lambda v: f"{v:.1f} d", sub="from borrow to return" if k["avg_days"] is not None else "needs return dates in the data")
        self.k_ontime.set_value(k["ontime_rate"], fmt=lambda v: f"{v:.0f}%", sub="returned on or before the due date" if k["ontime_rate"] is not None else "no returns in this period")
        self.k_idle.set_value(k["idle_titles"], sub="titles with zero loans")
        stagger_fade(self._an_cards, 0, 45, 320)

        series = [{"name": "Borrowed", "color": BANNER_2, "values": r["borrowed_series"]}]
        if r["returned_series"] is not None:
            series.append({"name": "Returned", "color": SUCCESS, "values": r["returned_series"]})
        self.trend.set_data(r["labels"], series)
        self.util.set_data([("On loan", k["copies_on_loan"], BANNER_2), ("Available", k["copies_available"], SUCCESS)],
                           f"{k['utilization']:.0f}%", "of copies on loan")
        self.top_books.set_data(r["top_books"])
        self.cats.set_data([(n, v, None) for n, v in r["cat_segments"]], str(sum(v for _, v in r["cat_segments"])), "loans")
        self.borrowers.set_data(r["top_borrowers"])
        self.grades.set_data(r["by_grade"])
        self.weekdays.set_data(r["by_weekday"])
        fill(self.overdue_table, r["overdue"][:25], [("book", None), ("borrower", None), ("grade", None),
                                                    ("due_at", lambda v, row: fmt_dt(v, False)),
                                                    ("days", lambda v, row: "Today" if v == 0 else f"{v} day{'s' if v != 1 else ''}")],
             lambda row, c: DANGER if c == 4 else None)
        fill(self.idle_table, r["idle"][:60], [("title", None), ("category", None), ("shelf", None), ("copies", None)])

    def export_analytics(self):
        r = self._an_result
        if not r:
            msg(self, "Export", "Nothing to export yet - wait for the analytics to load.", "warning")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export analytics", f"book_analytics_{datetime.now().strftime('%Y%m%d')}.csv", "CSV files (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["SMPCS Library - Book analytics", f"Last {self._an_days} days", datetime.now().strftime("%Y-%m-%d %H:%M")])
                w.writerow([])
                w.writerow(["SUMMARY"])
                for key, val in r["kpi"].items():
                    w.writerow([key.replace("_", " "), "" if val is None else (round(val, 2) if isinstance(val, float) else val)])
                for title, rows, head in (("MOST BORROWED BOOKS", r["top_books"], ["Title", "Loans", "Author"]),
                                          ("TOP BORROWERS", r["top_borrowers"], ["Member", "Loans", "Grade / Section"]),
                                          ("BY GRADE LEVEL", r["by_grade"], ["Grade", "Loans", ""]),
                                          ("BY WEEKDAY", r["by_weekday"], ["Day", "Loans", ""])):
                    w.writerow([])
                    w.writerow([title])
                    w.writerow(head)
                    for row in rows:
                        w.writerow(list(row))
                w.writerow([])
                w.writerow(["OVERDUE BOOKS"])
                w.writerow(["Book", "Borrower", "Grade / Section", "Due", "Days overdue"])
                for o in r["overdue"]:
                    w.writerow([o["book"], o["borrower"], o["grade"], fmt_dt(o["due_at"], False), o["days"]])
                w.writerow([])
                w.writerow(["NOT BORROWED IN PERIOD"])
                w.writerow(["Title", "Category", "Shelf", "Available"])
                for i in r["idle"]:
                    w.writerow([i["title"], i["category"], i["shelf"], i["copies"]])
            self.toast.show_message("Report exported ✓")
        except Exception as e:  # noqa: BLE001
            msg(self, "Export failed", str(e), "error")

    # ---------------------------------------------------------------- loans
    def build_loans(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        card = Card("Books currently on loan")
        self.lsearch = search_box("Search book, borrower, grade…")
        self.lfilter = QComboBox()
        self.lfilter.addItems(["All loans", "Overdue only", "Due within 3 days", "Awaiting approval"])
        self.lfilter.setMinimumWidth(200)
        card.add_action(self.lsearch)
        card.add_action(self.lfilter)
        card.add_action(make_button("↻ Refresh", self.refresh_loans, "secondary", 44))
        self.ltable = make_table(["Book", "Accession", "Borrower", "Grade / Section", "Borrowed", "Due", "Status"], 400)
        card.lay.addWidget(self.ltable)
        self.lcount = QLabel("")
        self.lcount.setStyleSheet(f"color:{MUTED};font-size:11px;font-weight:700;")
        card.lay.addWidget(self.lcount)
        self.lsearch.textChanged.connect(lambda t: self._apply_loan_filters())
        self.lfilter.currentIndexChanged.connect(lambda i: self._apply_loan_filters())
        lay.addWidget(card, 1)
        self._loan_rows = []
        self.add_page("loans", w, self.refresh_loans)

    def refresh_loans(self):
        def job():
            loans = select_first_ok(self.api, "library_loans", ["id,member_id,book_id,borrowed_at,due_at,verified_at", "id,member_id,book_id,borrowed_at,due_at"],
                                    "&status=eq.borrowed&order=due_at")
            members = select_first_ok(self.api, "library_members", ["id,full_name,grade_level,section", "id,full_name"])
            books = select_first_ok(self.api, "library_books", ["id,title,accession_no", "id,title"])
            return loans, members, books

        def ok(res):
            loans, members, books = res
            mem = {m.get("id"): m for m in members}
            bk = {b.get("id"): b for b in books}
            now = datetime.now().astimezone()
            rows = []
            for l in loans:
                m, b = mem.get(l.get("member_id")) or {}, bk.get(l.get("book_id")) or {}
                dd = parse_dt(l.get("due_at"))
                days = (dd.date() - now.date()).days if dd else None
                if "verified_at" in l and l.get("verified_at") is None:
                    status, state = "Awaiting approval", "pending"
                elif dd and dd < now and days is not None and days < 0:
                    status, state = f"OVERDUE  {abs(days)}d", "overdue"
                elif days == 0:
                    status, state = "Due today", "soon"
                elif days is not None and days <= 3:
                    status, state = f"Due in {days}d", "soon"
                else:
                    status, state = "On loan", "ok"
                rows.append({"book": b.get("title") or "Unknown book", "accession": b.get("accession_no") or "—",
                             "borrower": m.get("full_name") or "Unknown member",
                             "grade": " • ".join(x for x in (str(m.get("grade_level") or ""), str(m.get("section") or "")) if x) or "—",
                             "borrowed_at": l.get("borrowed_at"), "due_at": l.get("due_at"), "status": status, "state": state})
            self._loan_rows = rows
            self._apply_loan_filters()

        self.load(job, ok, lambda e: msg(self, "Loans", str(e), "error"))

    def _apply_loan_filters(self):
        mode = self.lfilter.currentIndex()
        rows = self._loan_rows
        if mode == 1:
            rows = [r for r in rows if r["state"] == "overdue"]
        elif mode == 2:
            rows = [r for r in rows if r["state"] in ("soon", "overdue")]
        elif mode == 3:
            rows = [r for r in rows if r["state"] == "pending"]
        fill(self.ltable, rows, [("book", None), ("accession", None), ("borrower", None), ("grade", None),
                                 ("borrowed_at", lambda v, r: fmt_dt(v, False)), ("due_at", lambda v, r: fmt_dt(v, False)), ("status", None)],
             lambda row, c: ({"overdue": DANGER, "soon": "#B56A13", "pending": "#B56A13", "ok": SUCCESS}[row["state"]] if c == 6 else None))
        filter_table(self.ltable, self.lsearch.text())
        self.lcount.setText(f"{len(rows)} loan{'s' if len(rows) != 1 else ''} shown  •  {sum(1 for r in self._loan_rows if r['state'] == 'overdue')} overdue in total")

    # ---------------------------------------------------------------- borrow approvals
    APPROVAL_HELP = ("One-time setup needed: run <b>approval_migration.sql</b> in the Supabase SQL editor "
                     "(it adds the approval columns and the approve / reject functions), then click Refresh.")

    def _set_nav_badge(self, n):
        b = self.nav_buttons.get("approvals")
        if b is not None:
            b.setText(f"✅    Borrow Approvals" + (f"   •   {n}" if n else ""))

    def poll_pending(self):
        if not self._approval_ready:
            return

        def ok(rows):
            n, prev = len(rows), self._pending_count
            self._pending_count = n
            self._set_nav_badge(n)
            if prev is not None and n > prev:
                d = n - prev
                self.toast.show_message(f"🔔  {d} new borrow request{'s' if d > 1 else ''} waiting for approval")

        def err(e):
            if "verified_at" in str(e):
                self._approval_ready = False
        self.load(lambda: self.api.select("library_loans", "?select=id&status=eq.borrowed&verified_at=is.null&limit=500") or [], ok, err)

    def build_approvals(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)
        self.appr_banner = QLabel(self.APPROVAL_HELP)
        self.appr_banner.setWordWrap(True)
        self.appr_banner.setTextFormat(Qt.TextFormat.RichText)
        self.appr_banner.setStyleSheet("background:#FFF5DD;color:#8A5A0F;border-radius:14px;padding:14px 18px;font-size:12px;font-weight:700;")
        self.appr_banner.hide()
        card = Card("Waiting for your approval", "Check the student and the book in front of you, then approve or reject.")
        card.add_action(make_button("↻ Refresh", self.refresh_approvals, "secondary", 44))
        self.atable = make_table(["Book", "Accession", "Borrower", "Grade / Section", "Requested", "Return by", "Waiting"], 360)
        card.lay.addWidget(self.atable)
        btns = QHBoxLayout()
        btns.setSpacing(12)
        btns.addWidget(make_button("✓   Approve selected", self.approve_selected, "success", 54))
        btns.addWidget(make_button("✕   Reject selected", self.reject_selected, "danger", 54))
        btns.addStretch()
        self.appr_count = QLabel("")
        self.appr_count.setStyleSheet(f"color:{MUTED};font-size:12px;font-weight:700;")
        btns.addWidget(self.appr_count)
        card.lay.addLayout(btns)
        lay.addWidget(self.appr_banner)
        lay.addWidget(card, 1)
        self.add_page("approvals", w, self.refresh_approvals)

    @staticmethod
    def _ago(v):
        d = parse_dt(v)
        if d is None:
            return "—"
        mins = int((datetime.now().astimezone() - d).total_seconds() // 60)
        if mins < 1:
            return "just now"
        if mins < 60:
            return f"{mins} min"
        if mins < 1440:
            return f"{mins // 60} h {mins % 60} min"
        return f"{mins // 1440} d"

    def refresh_approvals(self):
        def job():
            loans = select_all(self.api, "library_loans", "id,member_id,book_id,borrowed_at,due_at",
                               "&status=eq.borrowed&verified_at=is.null&order=borrowed_at")
            mem, bk = {}, {}
            if loans:
                mids = ",".join(sorted({str(l["member_id"]) for l in loans if l.get("member_id") is not None}))
                bids = ",".join(sorted({str(l["book_id"]) for l in loans if l.get("book_id") is not None}))
                if mids:
                    for m in select_first_ok(self.api, "library_members", ["id,full_name,grade_level,section", "id,full_name"], f"&id=in.({mids})"):
                        mem[m.get("id")] = m
                if bids:
                    for b in select_first_ok(self.api, "library_books", ["id,title,accession_no", "id,title"], f"&id=in.({bids})"):
                        bk[b.get("id")] = b
            return loans, mem, bk

        def ok(res):
            loans, mem, bk = res
            rows = []
            for l in loans:
                m, b = mem.get(l.get("member_id")) or {}, bk.get(l.get("book_id")) or {}
                rows.append({"id": l.get("id"), "book": b.get("title") or "Unknown book", "accession": b.get("accession_no") or "—",
                             "borrower": m.get("full_name") or "Unknown member",
                             "grade": " • ".join(x for x in (str(m.get("grade_level") or ""), str(m.get("section") or "")) if x) or "—",
                             "borrowed_at": l.get("borrowed_at"), "due_at": l.get("due_at")})
            self.appr_banner.hide()
            self._approval_ready = True
            self._pending_count = len(rows)
            self._set_nav_badge(len(rows))
            fill(self.atable, rows, [("book", None), ("accession", None), ("borrower", None), ("grade", None),
                                     ("borrowed_at", lambda v, r: fmt_dt(v)), ("due_at", lambda v, r: fmt_dt(v, False)),
                                     ("borrowed_at", lambda v, r: self._ago(v))],
                 lambda row, c: "#B56A13" if c == 6 else None)
            self.appr_count.setText(f"{len(rows)} request{'s' if len(rows) != 1 else ''} waiting" if rows else "All caught up ✓")

        def err(e):
            if "verified_at" in str(e):
                self._approval_ready = False
                self.appr_banner.show()
                fill(self.atable, [], [("book", None)] * 7)
                self.appr_count.setText("")
            else:
                msg(self, "Borrow approvals", str(e), "error")
        self.load(job, ok, err)

    def _pick_request(self, verb):
        row = selected_row(self.atable)
        if not row:
            msg(self, verb, "Select a request in the list first.", "warning")
        return row

    def approve_selected(self):
        row = self._pick_request("Approve")
        if not row:
            return
        actor = self.user.get("username")

        def ok(_):
            self.toast.show_message(f"Approved: {row['book']} → {row['borrower']} ✓")
            self.refresh_approvals()
        self.load(lambda: self.api.rpc("library_verify_loan", {"p_loan_id": str(row["id"]), "p_actor": actor}), ok,
                  lambda e: msg(self, "Approve failed", str(e), "error"))

    def reject_selected(self):
        row = self._pick_request("Reject")
        if not row:
            return
        if not confirm(self, "Reject borrow request",
                       f"Reject \"{row['book']}\" for {row['borrower']}?\n\nThe copy goes back to the shelf count and the student must not take the book.", "Reject request"):
            return
        actor = self.user.get("username")

        def ok(_):
            self.toast.show_message("Request rejected — copy returned to the shelf")
            self.refresh_approvals()
        self.load(lambda: self.api.rpc("library_reject_loan", {"p_loan_id": str(row["id"]), "p_actor": actor}), ok,
                  lambda e: msg(self, "Reject failed", str(e), "error"))

    # ---------------------------------------------------------------- stations
    def build_stations(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)
        form = Card("Register a kiosk", "Registering an existing code resets its token - the kiosk must be set up again with the new one.")
        self.scode, self.sname = QLineEdit(), QLineEdit()
        self.scode.setPlaceholderText("e.g. LIB-KIOSK-1")
        self.sname.setPlaceholderText("e.g. Library Entrance")
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)
        grid.addWidget(field_label("STATION CODE"), 0, 0)
        grid.addWidget(self.scode, 1, 0)
        grid.addWidget(field_label("STATION NAME"), 0, 1)
        grid.addWidget(self.sname, 1, 1)
        form.lay.addLayout(grid)
        form.lay.addWidget(make_button("🔑  Register / reset station token", self.register_station), alignment=Qt.AlignmentFlag.AlignLeft)
        lst = Card("All stations", "Online means the kiosk sent a heartbeat in the last 2 minutes  •  tokens stay hidden until you unlock them")
        lst.add_action(make_button("👁  Show token…", self.show_token, "secondary", 44))
        lst.add_action(make_button("↻ Refresh", self.refresh_stations, "secondary", 44))
        self.stable = make_table(["Code", "Name", "Status", "Token", "Enabled", "Last seen"], 260)
        lst.lay.addWidget(self.stable)
        lay.addWidget(form)
        lay.addWidget(lst, 1)
        self.add_page("stations", w, self.refresh_stations)

    def refresh_stations(self):
        def ok(rows):
            self._stations_cache = rows
            now = datetime.now().astimezone()
            for r in rows:
                seen = parse_dt(r.get("last_seen_at"))
                r["_online"] = bool(seen and (now - seen).total_seconds() <= 120)
            fill(self.stable, rows, [("station_code", None), ("station_name", None),
                                     ("_online", lambda v, r: "● Online" if v else "○ Offline"),
                                     ("station_token", lambda v, r: "••••••••••••" if v else "—"),
                                     ("active", lambda v, r: "Yes" if v else "No"),
                                     ("last_seen_at", lambda v, r: fmt_dt(v))],
                 lambda row, c: (SUCCESS if row.get("_online") else MUTED_LIGHT) if c == 2 else None)
        self.load(lambda: select_all(self.api, "library_kiosk_stations", "station_code,station_name,station_token,active,last_seen_at", "&order=station_code"),
                  ok, lambda e: msg(self, "Stations", str(e), "error"))

    def register_station(self):
        code, name = self.scode.text().strip(), self.sname.text().strip()
        if not code:
            msg(self, "Register station", "Enter a station code first.", "warning")
            return
        if any(str(s.get("station_code")) == code for s in self._stations_cache) and \
                not confirm(self, "Reset token", f"Station {code} already exists.\n\nResetting its token will disconnect that kiosk until it is set up again. Continue?", "Reset token"):
            return
        token = secrets.token_hex(24)

        def ok(d):
            if isinstance(d, list):
                d = d[0]
            TokenDialog(d["station_code"], d["station_token"],
                        "Copy this token into the kiosk setup now. For safety it is hidden in the list from here on.", self).exec()
            self.refresh_stations()
        self.load(lambda: self.api.rpc("library_register_station", {"p_station_code": code, "p_station_name": name, "p_station_token": token}),
                  ok, lambda e: msg(self, "Station failed", str(e), "error"))

    def show_token(self):
        row = selected_row(self.stable)
        if not row:
            msg(self, "Show token", "Select a station in the list first.", "warning")
            return
        pw, ok = QInputDialog.getText(self, "Confirm it's you", "Enter your password to reveal this token:", QLineEdit.EchoMode.Password)
        if not ok:
            return
        try:
            good = bcrypt.checkpw(pw.encode(), str(self.user["password_hash"]).encode())
        except Exception:
            good = False
        if not good:
            self.toast.show_message("Wrong password", "error")
            return
        TokenDialog(row.get("station_code"), str(row.get("station_token") or ""), "Keep this token private - anyone with it can act as this kiosk.", self).exec()

    # ---------------------------------------------------------------- logs
    # ---------------------------------------------------------------- print logs
    PRINTLOG_HELP = ("One-time setup needed: run <b>print_log_migration.sql</b> in the Supabase SQL editor "
                     "(it adds the print log table and the logging function), then click Refresh.")

    def build_print_logs(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)
        self.pl_banner = QLabel(self.PRINTLOG_HELP)
        self.pl_banner.setWordWrap(True)
        self.pl_banner.setTextFormat(Qt.TextFormat.RichText)
        self.pl_banner.setStyleSheet("background:#FFF5DD;color:#8A5A0F;border-radius:14px;padding:14px 18px;font-size:12px;font-weight:700;")
        self.pl_banner.hide()
        row = QHBoxLayout()
        row.setSpacing(16)
        self.kp_today = KpiCard("Printed today", GOLD, "🖨")
        self.kp_week = KpiCard("Printed this week", SECONDARY, "📅")
        self.kp_total = KpiCard("Total on record", BANNER_2, "🗂")
        for k in (self.kp_today, self.kp_week, self.kp_total):
            row.addWidget(k)
        lay.addLayout(row)
        card = Card("Print activity", "Every file printed at the kiosk's USB print station")
        self.plsearch = search_box("Search member, file name, type…")
        card.add_action(self.plsearch)
        card.add_action(make_button("↻ Refresh", self.refresh_print_logs, "secondary", 44))
        self.pltable = make_table(["Member", "Grade / Section", "File", "Type", "Size", "Station", "Printed At"], 400)
        self.plsearch.textChanged.connect(lambda t: filter_table(self.pltable, t))
        card.lay.addWidget(self.pltable)
        lay.addWidget(card, 1)
        self.add_page("printlogs", w, self.refresh_print_logs)

    def refresh_print_logs(self):
        def job():
            rows = select_all(self.api, "library_print_log", "id,member_id,file_name,file_type,file_size,station_code,printed_at", "&order=printed_at.desc&limit=500")
            mids = ",".join(sorted({str(r["member_id"]) for r in rows if r.get("member_id") is not None}))
            mem = {}
            if mids:
                for m in select_first_ok(self.api, "library_members", ["id,full_name,grade_level,section", "id,full_name"], f"&id=in.({mids})"):
                    mem[m.get("id")] = m
            return rows, mem

        def ok(res):
            rows, mem = res
            self.pl_banner.hide()
            now = datetime.now().astimezone()
            today = now.date()
            week_start = today - timedelta(days=today.weekday())
            today_n = week_n = 0
            out = []
            for r in rows:
                m = mem.get(r.get("member_id")) or {}
                pd = parse_dt(r.get("printed_at"))
                if pd is not None:
                    if pd.date() == today:
                        today_n += 1
                    if pd.date() >= week_start:
                        week_n += 1
                out.append({
                    "member": m.get("full_name") or "Unknown member",
                    "grade": " • ".join(x for x in (str(m.get("grade_level") or ""), str(m.get("section") or "")) if x) or "—",
                    "file_name": r.get("file_name"), "file_type": r.get("file_type") or "—",
                    "file_size": human_size(r.get("file_size")) if r.get("file_size") is not None else "—",
                    "station_code": r.get("station_code") or "—", "printed_at": r.get("printed_at"),
                })
            self.kp_today.set_value(today_n, sub="files printed today")
            self.kp_week.set_value(week_n, sub="files printed since Monday")
            self.kp_total.set_value(len(rows), sub="most recent 500 shown below")
            fill(self.pltable, out, [("member", None), ("grade", None), ("file_name", None), ("file_type", None),
                                     ("file_size", None), ("station_code", None), ("printed_at", lambda v, r: fmt_dt(v))])
            filter_table(self.pltable, self.plsearch.text())

        def err(e):
            if "library_print_log" in str(e) or "PGRST" in str(e).upper():
                self.pl_banner.show()
                fill(self.pltable, [], [("member", None)] * 7)
                for k in (self.kp_today, self.kp_week, self.kp_total):
                    k.set_value(None)
            else:
                msg(self, "Print logs", str(e), "error")
        self.load(job, ok, err)

    def build_logs(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        card = Card("Latest 200 actions")
        self.gsearch = search_box("Search actor, action, item…")
        card.add_action(self.gsearch)
        card.add_action(make_button("↻ Refresh", self.refresh_logs, "secondary", 44))
        self.gtable = make_table(["Actor", "Action", "Entity", "Time", "Details"], 400)
        self.gsearch.textChanged.connect(lambda t: filter_table(self.gtable, t))
        card.lay.addWidget(self.gtable)
        lay.addWidget(card, 1)
        self.add_page("logs", w, self.refresh_logs)

    def refresh_logs(self):
        def ok(rows):
            fill(self.gtable, rows, [("actor_username", None), ("action", None), ("entity_type", None),
                                     ("created_at", lambda v, r: fmt_dt(v)), ("details", None)])
            filter_table(self.gtable, self.gsearch.text())
        self.load(lambda: self.api.select("library_audit_log", "?select=actor_username,action,entity_type,created_at,details&order=created_at.desc&limit=200") or [],
                  ok, lambda e: msg(self, "Logs", str(e), "error"))


# ============================================================
# ENTRY POINT
# ============================================================

def apply_light_palette(app):
    """Force the light theme even when Windows is in dark mode (otherwise unstyled areas turn black)."""
    pal = QPalette()
    for role, color in ((QPalette.ColorRole.Window, BACKGROUND), (QPalette.ColorRole.WindowText, TEXT),
                        (QPalette.ColorRole.Base, "#FFFFFF"), (QPalette.ColorRole.AlternateBase, "#F3F6FB"),
                        (QPalette.ColorRole.Text, TEXT), (QPalette.ColorRole.Button, WHITE),
                        (QPalette.ColorRole.ButtonText, TEXT), (QPalette.ColorRole.ToolTipBase, NAVY),
                        (QPalette.ColorRole.ToolTipText, "#FFFFFF"), (QPalette.ColorRole.Highlight, BANNER_2),
                        (QPalette.ColorRole.HighlightedText, "#FFFFFF"), (QPalette.ColorRole.PlaceholderText, MUTED_LIGHT)):
        pal.setColor(role, QColor(color))
    app.setPalette(pal)


def main(app=None):
    from shared.runtime import configure
    configure("admin")
    sys.excepthook = lambda et, ev, tb: traceback.print_exception(et, ev, tb)
    app = app or QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    apply_light_palette(app)
    app.setStyleSheet(LIGHT_QSS + APP_QSS)
    cfg = load_config()
    if not cfg.get("SUPABASE_URL") or not cfg.get("SUPABASE_ANON_KEY"):
        d = BackendSetup(role="admin")
        if d.exec() != QDialog.DialogCode.Accepted:
            return 0
        cfg = load_config()
    try:
        api = SupabaseAPI(cfg["SUPABASE_URL"], cfg["SUPABASE_ANON_KEY"])
    except Exception as e:  # noqa: BLE001
        msg(None, "Setup", str(e), "error")
        return 1
    try:
        status = api.rpc("library_setup_status")
        if isinstance(status, list):
            status = status[0]
        if not status.get("complete", False):
            d = FirstAdminDialog()
            if d.exec() != QDialog.DialogCode.Accepted:
                return 0
            username, full_name, password = d.values
            h = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            api.rpc("library_setup_admin", {"p_username": username, "p_full_name": full_name, "p_password_hash": h})
    except Exception as e:  # noqa: BLE001
        msg(None, "Database setup", str(e), "error")
        return 1
    login = AdminLogin(api)
    if login.exec() != QDialog.DialogCode.Accepted:
        return 0
    win = AdminWindow(api, login.user)
    from shared.updates import attach_updates
    attach_updates(win)
    win.showMaximized()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())