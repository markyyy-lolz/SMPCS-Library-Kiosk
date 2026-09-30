from __future__ import annotations

import sys
import os
import ctypes
import math
import random
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6 import sip
from PyQt6.QtCore import (
    Qt, QDate, QEvent, QTimer, QPoint, QPointF, QRectF, QSize,
    QEasingCurve, QPropertyAnimation, QVariantAnimation,
    QSequentialAnimationGroup, QThread, pyqtSignal
)
from PyQt6.QtGui import (
    QColor, QPainter, QPen, QBrush, QLinearGradient, QPainterPath, QPixmap
)
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFormLayout, QGridLayout, QFrame, QGraphicsDropShadowEffect,
    QMessageBox,
    QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget
)

from shared.config import load_config, save_config
from shared.api import SupabaseAPI, ApiError
from shared.ui import apply_theme, msg
from shared.rfid import RFIDCapture

# ============================================================
# THEME
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

# ============================================================
# MOTION SETTINGS
# ============================================================
# Master switch. Set to False on very slow kiosk PCs to turn off the
# fade / stagger / confetti entrance effects (spinners still animate).
MOTION_ENABLED = True

# The book-scan screen shows a sweeping scan line. The home-screen RFID
# reader itself stays completely static (no pulse / ripple), as before.
ENABLE_BOOK_SCAN_SWEEP = True

# Top banner size (increase these if your kiosk screen is large)
BANNER_HEIGHT = 124
LOGO_SIZE = 100


# ============================================================
# SMALL MATH / COLOR HELPERS
# ============================================================

def clock() -> float:
    return time.monotonic()


def clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def ease_out_cubic(t: float) -> float:
    t = clamp01(t)
    return 1.0 - (1.0 - t) ** 3


def ease_in_out(t: float) -> float:
    t = clamp01(t)
    return t * t * (3.0 - 2.0 * t)


def mix(a, b, t: float) -> QColor:
    ca, cb = QColor(a), QColor(b)
    t = clamp01(t)
    return QColor(
        int(lerp(ca.red(), cb.red(), t)),
        int(lerp(ca.green(), cb.green(), t)),
        int(lerp(ca.blue(), cb.blue(), t)),
        int(lerp(ca.alpha(), cb.alpha(), t)),
    )


def with_alpha(color, alpha: float) -> QColor:
    c = QColor(color)
    c.setAlpha(int(max(0, min(255, alpha))))
    return c


def round_pen(color, width: float) -> QPen:
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def draw_partial_polyline(p: QPainter, pts, t: float):
    """Draw only the first `t` (0..1) fraction of a polyline - used to 'write' check marks."""
    t = clamp01(t)
    if t <= 0.0 or len(pts) < 2:
        return
    lens = [math.hypot(pts[i + 1].x() - pts[i].x(), pts[i + 1].y() - pts[i].y()) for i in range(len(pts) - 1)]
    target = sum(lens) * t
    path = QPainterPath(pts[0])
    acc = 0.0
    for i, seg in enumerate(lens):
        if acc + seg <= target + 1e-6:
            path.lineTo(pts[i + 1])
            acc += seg
        else:
            f = (target - acc) / seg if seg else 0.0
            path.lineTo(QPointF(lerp(pts[i].x(), pts[i + 1].x(), f), lerp(pts[i].y(), pts[i + 1].y(), f)))
            break
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)


# ============================================================
# KIOSK MESSAGE BOX — always readable in light kiosk theme
# ============================================================

def kiosk_msg(parent, title, text, kind="info"):
    box = QMessageBox(parent)
    box.setWindowTitle(str(title))
    box.setText(str(text))
    box.setIcon({
        "info": QMessageBox.Icon.Information,
        "warning": QMessageBox.Icon.Warning,
        "error": QMessageBox.Icon.Critical,
        "question": QMessageBox.Icon.Question,
    }.get(kind, QMessageBox.Icon.Information))
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    if kind=='error':
        from shared.suite import add_copy_error
        add_copy_error(box,text)
    box.setMinimumWidth(560)
    box.setStyleSheet(
        f"""
        QMessageBox {{
            background: {WHITE};
            color: {TEXT};
            border: none;
        }}
        QMessageBox QLabel {{
            color: {TEXT};
            background: transparent;
            font-family: \"Segoe UI\";
            font-size: 15px;
            font-weight: 650;
        }}
        QMessageBox QPushButton {{
            min-width: 92px;
            min-height: 44px;
            padding: 7px 20px;
            border: none;
            border-radius: 11px;
            background: {SECONDARY};
            color: white;
            font-size: 12px;
            font-weight: 900;
        }}
        QMessageBox QPushButton:hover {{ background: #2F70C7; }}
        QMessageBox QPushButton:pressed {{ background: #275FA9; }}
        """
    )
    return box.exec()


# ============================================================
# SAFE ANIMATION HELPERS
# No RFID pulse/ripple animation on the home reader.
# ============================================================

def add_shadow(widget, blur=24, y=7, opacity=22):
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, y)
    effect.setColor(QColor(15, 23, 42, opacity))
    widget.setGraphicsEffect(effect)
    return effect


def _drop_effect(widget, effect):
    """Remove a finished fade effect so the widget goes back to cheap direct painting."""
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


def stagger_fade(widgets, start=0, step=80, duration=380):
    """Fade widgets in one after another (cascade entrance)."""
    for i, w in enumerate(widgets):
        if w is not None:
            fade_in(w, duration, delay=start + i * step)


def count_up(label: QLabel, target: int, duration=800):
    if not MOTION_ENABLED or target <= 0:
        label.setText(str(target))
        return
    anim = QVariantAnimation(label)
    anim.setStartValue(0.0)
    anim.setEndValue(float(target))
    anim.setDuration(duration)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.valueChanged.connect(lambda v: label.setText(str(int(round(float(v))))))
    label._count_anim = anim
    label.setText("0")
    anim.start()


class ApiTask(QThread):
    """Runs a blocking API call off the UI thread so animations never freeze."""
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
# USB PRINTING  (removable drives only — never the system disk)
# ============================================================
PRINT_EXTENSIONS = {
    ".pdf": ("PDF document", "📄"),
    ".doc": ("Word document", "📝"), ".docx": ("Word document", "📝"),
    ".rtf": ("Rich text document", "📝"), ".txt": ("Text file", "📝"),
    ".xls": ("Excel sheet", "📊"), ".xlsx": ("Excel sheet", "📊"), ".csv": ("Spreadsheet", "📊"),
    ".ppt": ("PowerPoint", "📽"), ".pptx": ("PowerPoint", "📽"),
    ".jpg": ("Image", "🖼"), ".jpeg": ("Image", "🖼"), ".png": ("Image", "🖼"),
    ".bmp": ("Image", "🖼"), ".gif": ("Image", "🖼"),
}
FOLDER_ICON = "📁"
GENERIC_FILE_ICON = "📦"
MAX_PRINT_BYTES = 200 * 1024 * 1024  # refuse to spool absurdly large files
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif"}

# Silent GDI printing for images only (jpg/png/bmp/gif) — bypasses the Windows
# Photos app "Print Pictures" dialog entirely, using pywin32 + Pillow directly.
# Documents (PDF/DOCX/XLSX/PPTX) still go through ShellExecute below and may
# still show their own app's print dialog — there is no universal silent-print
# API for arbitrary document types without a licensed conversion engine.
try:
    import win32con, win32print, win32ui, win32gui
    from PIL import Image, ImageWin
    SILENT_IMAGE_PRINT_AVAILABLE = True
except Exception:
    SILENT_IMAGE_PRINT_AVAILABLE = False

# "Short" bond paper (8.5 x 11 in / Letter) — the requested default.
# For "Long" (8.5 x 13 in / Legal-ish), pass DMPAPER_LEGAL instead.
PAPER_SHORT = getattr(win32con, "DMPAPER_LETTER", 1) if SILENT_IMAGE_PRINT_AVAILABLE else 1
PAGE_RATIO = 8.5 / 11.0  # Short/Letter portrait, width:height — used by the preview panel too

# Optional: first-page PDF thumbnails in the preview panel. Needs the
# separate `PyQt6-QtPdf` wheel; everything works fine without it, the
# preview just falls back to an icon placeholder for PDFs.
try:
    from PyQt6.QtPdf import QPdfDocument
    QTPDF_AVAILABLE = True
except Exception:
    QTPDF_AVAILABLE = False


def _printer_devmode(printer_name, paper_id):
    handle = win32print.OpenPrinter(printer_name)
    try:
        info = win32print.GetPrinter(handle, 2)
        devmode = info["pDevMode"]
        devmode.PaperSize = paper_id
        devmode.Fields |= win32con.DM_PAPERSIZE
        return devmode
    finally:
        win32print.ClosePrinter(handle)


def print_image_silent(path, printer_name=None, paper_id=None):
    """Prints an image with no dialog: renders it straight to the printer's
    device context via GDI, centred and scaled to fit the page, on Short
    (Letter) paper by default. Requires `pip install pywin32 pillow`."""
    if not SILENT_IMAGE_PRINT_AVAILABLE:
        raise ApiError("Silent photo printing needs the pywin32 and Pillow packages installed on this kiosk.")
    printer_name = printer_name or win32print.GetDefaultPrinter()
    if not printer_name:
        raise ApiError("No default printer is set on this kiosk.")
    devmode = _printer_devmode(printer_name, paper_id or PAPER_SHORT)
    hdc_handle = win32gui.CreateDC("WINSPOOL", printer_name, devmode)
    hDC = win32ui.CreateDCFromHandle(hdc_handle)
    try:
        img = Image.open(path)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img_w, img_h = img.size

        HORZRES, VERTRES, PHYSICALWIDTH, PHYSICALHEIGHT = 8, 10, 110, 111
        printable_w = hDC.GetDeviceCaps(HORZRES) or img_w
        printable_h = hDC.GetDeviceCaps(VERTRES) or img_h
        page_w = hDC.GetDeviceCaps(PHYSICALWIDTH) or printable_w
        page_h = hDC.GetDeviceCaps(PHYSICALHEIGHT) or printable_h

        scale = min(printable_w / img_w, printable_h / img_h)
        w, h = max(1, int(img_w * scale)), max(1, int(img_h * scale))
        x1 = int((page_w - w) / 2)
        y1 = int((page_h - h) / 2)

        hDC.StartDoc(Path(path).name)
        hDC.StartPage()
        dib = ImageWin.Dib(img)
        dib.draw(hDC.GetHandleOutput(), (x1, y1, x1 + w, y1 + h))
        hDC.EndPage()
        hDC.EndDoc()
    finally:
        hDC.DeleteDC()
    return True



def _is_windows():
    return os.name == "nt"


def _drive_type(path):
    try:
        return ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(path))
    except Exception:
        return 0


def _volume_label(path):
    try:
        buf = ctypes.create_unicode_buffer(261)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(ctypes.c_wchar_p(path), buf, 260, None, None, None, None, 0)
        return buf.value.strip() if ok else ""
    except Exception:
        return ""


def _disk_usage(path):
    try:
        free_b = ctypes.c_ulonglong(0)
        total_b = ctypes.c_ulonglong(0)
        ctypes.windll.kernel32.GetDiskFreeSpaceExW(ctypes.c_wchar_p(path), ctypes.byref(free_b), ctypes.byref(total_b), None)
        return int(free_b.value), int(total_b.value)
    except Exception:
        return 0, 0


def list_removable_drives():
    """USB / removable drives only. Windows only — the kiosk has nothing to
    show on other platforms, and print_file() will refuse to run there too."""
    drives = []
    if not _is_windows():
        return drives
    DRIVE_REMOVABLE = 2
    try:
        mask = ctypes.windll.kernel32.GetLogicalDrives()
    except Exception:
        return drives
    for i in range(26):
        if not (mask & (1 << i)):
            continue
        root = f"{chr(65 + i)}:\\"
        if _drive_type(root) != DRIVE_REMOVABLE:
            continue
        label = _volume_label(root) or "USB DRIVE"
        free, total = _disk_usage(root)
        drives.append({"path": root, "letter": root[:2], "label": label, "free": free, "total": total})
    return drives


def human_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024.0 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TB"


def _within_root(root, path):
    """True only if `path` is the USB root itself or physically inside it —
    this is what keeps the file explorer sandboxed to the USB drive."""
    try:
        root_r = Path(root).resolve()
        path_r = Path(path).resolve()
        return path_r == root_r or root_r in path_r.parents
    except Exception:
        return False


def list_dir_entries(root, path):
    """Folders first, then files, alphabetically. Entries that resolve
    outside `root` (odd symlinks/junctions) are silently skipped."""
    entries = []
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.name.startswith("$") or e.name.lower() in (
                        "system volume information", ".trashes", ".spotlight-v100", ".fseventsd"
                    ):
                        continue
                    is_dir = e.is_dir(follow_symlinks=False)
                    full = e.path
                    if not _within_root(root, full):
                        continue
                    st = e.stat(follow_symlinks=False)
                    entries.append({
                        "name": e.name, "path": full, "is_dir": is_dir,
                        "size": 0 if is_dir else st.st_size, "mtime": st.st_mtime,
                        "ext": "" if is_dir else Path(e.name).suffix.lower(),
                    })
                except OSError:
                    continue
    except OSError as exc:
        raise ApiError(f"Could not open this folder: {exc.strerror or exc}")
    entries.sort(key=lambda r: (not r["is_dir"], r["name"].lower()))
    return entries


def print_file(path):
    """Best-effort print via the file's default Windows application (the
    'print' shell verb). Whether this prints silently or opens the app's own
    print dialog depends entirely on that application — a limitation of
    Windows' ShellExecute, not something this kiosk can control for every
    file type. Test each file type you expect students to print."""
    if not _is_windows():
        raise ApiError("Printing is only supported when the kiosk runs on Windows.")
    p = Path(path)
    if not p.is_file():
        raise ApiError("This file is no longer on the USB drive.")
    if p.stat().st_size > MAX_PRINT_BYTES:
        raise ApiError("This file is too large to print here (over 200 MB).")
    try:
        res = ctypes.windll.shell32.ShellExecuteW(None, "print", str(p), None, str(p.parent), 0)
    except Exception as exc:
        raise ApiError(f"Could not start printing: {exc}")
    code = int(res)
    if code <= 32:
        raise ApiError(f"Windows could not print this file (error {code}). "
                       "Check that a default printer is set and that a program for this file type is installed.")
    return True


class DriveChip(QFrame):
    selected = pyqtSignal()

    def __init__(self, drive, parent=None):
        super().__init__(parent)
        self.drive = drive
        self.setObjectName("driveChip")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(74)
        self._active = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 8, 16, 8)
        lay.setSpacing(12)
        icon = QLabel("💾")
        icon.setStyleSheet("font-size:26px;background:transparent;")
        col = QVBoxLayout()
        col.setSpacing(3)
        name = QLabel(drive["label"])
        name.setStyleSheet(f"color:{TEXT};font-size:13px;font-weight:900;background:transparent;")
        total = drive["total"] or 1
        used_pct = clamp01(max(0, total - drive["free"]) / total)
        sub = QLabel(f"{drive['letter']}   •   {human_size(drive['free'])} free of {human_size(total)}")
        sub.setStyleSheet(f"color:{MUTED};font-size:10px;font-weight:700;background:transparent;")
        bar = QFrame()
        bar.setFixedHeight(5)
        stop = max(0.02, min(0.98, used_pct))
        bar.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {SECONDARY}, stop:{stop:.3f} {SECONDARY}, "
            f"stop:{min(0.999, stop + 0.01):.3f} #EFE5DF, stop:1 #EFE5DF); border-radius:2px;"
        )
        col.addWidget(name)
        col.addWidget(sub)
        col.addWidget(bar)
        lay.addWidget(icon)
        lay.addLayout(col, 1)
        self._apply()

    def _apply(self):
        if self._active:
            self.setStyleSheet(f"QFrame#driveChip{{background:{ACCENT_LIGHT};border:2px solid {ACCENT};border-radius:16px;}}")
        else:
            self.setStyleSheet(f"QFrame#driveChip{{background:{WHITE};border:2px solid transparent;border-radius:16px;}} "
                               f"QFrame#driveChip:hover{{background:#EAF2FF;}}")

    def set_active(self, on):
        self._active = on
        self._apply()

    def mousePressEvent(self, e):
        self.selected.emit()
        super().mousePressEvent(e)


class PrintTile(QFrame):
    activated = pyqtSignal()

    def __init__(self, entry, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.setObjectName("printTile")
        self.setFixedSize(176, 152)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._selected = False
        is_dir = entry["is_dir"]
        self._is_dir = is_dir
        self._supported = is_dir or entry["ext"] in PRINT_EXTENSIONS
        icon_char = FOLDER_ICON if is_dir else PRINT_EXTENSIONS.get(entry["ext"], (None, GENERIC_FILE_ICON))[1]
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 14, 10, 10)
        lay.setSpacing(5)
        ic = QLabel(icon_char)
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic.setStyleSheet(f"font-size:42px;background:transparent;{'' if self._supported else 'opacity:0.5;'}")
        name = QLabel(entry["name"])
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setWordWrap(True)
        name.setMaximumHeight(36)
        name.setStyleSheet(f"color:{TEXT if self._supported else MUTED_LIGHT};font-size:11px;font-weight:800;background:transparent;")
        if is_dir:
            meta_text = "Folder"
        elif self._supported:
            meta_text = f"{PRINT_EXTENSIONS[entry['ext']][0]}  •  {human_size(entry['size'])}"
        else:
            meta_text = "Can't print this type"
        meta = QLabel(meta_text)
        meta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        meta.setWordWrap(True)
        meta.setStyleSheet(f"color:{MUTED if self._supported else MUTED_LIGHT};font-size:9px;font-weight:700;background:transparent;")
        lay.addWidget(ic)
        lay.addWidget(name)
        lay.addWidget(meta)
        self._apply_style()

    def _apply_style(self):
        if self._selected:
            self.setStyleSheet(f"QFrame#printTile{{background:{ACCENT_LIGHT};border:2px solid {ACCENT};border-radius:16px;}}")
        else:
            self.setStyleSheet(f"QFrame#printTile{{background:{WHITE};border:2px solid transparent;border-radius:16px;}} "
                               f"QFrame#printTile:hover{{background:#EAF2FF;}}")

    def set_selected(self, on):
        self._selected = on
        self._apply_style()

    def mousePressEvent(self, event):
        if self._is_dir or self._supported:
            self.activated.emit()
        super().mousePressEvent(event)


class PagePreview(QWidget):
    """Paints a small Short/Letter 'sheet of paper' showing what will
    actually print: a scaled, centred image (mirroring print_image_silent's
    own fit logic), a rendered PDF first page when available, a placeholder
    icon for other file types, or an empty dashed outline when nothing is
    selected."""
    def __init__(self, parent=None):
        super().__init__(parent)
        w = 232
        self.setFixedSize(w, int(w / PAGE_RATIO))
        self._pixmap = None
        self._mode = "empty"   # empty | image | placeholder
        self._icon = GENERIC_FILE_ICON
        add_shadow(self, blur=26, y=10, opacity=26)

    def set_empty(self):
        self._mode, self._pixmap = "empty", None
        self.update()

    def set_image(self, path):
        pm = QPixmap(path)
        if pm.isNull():
            self.set_empty()
            return False
        self._pixmap, self._mode = pm, "image"
        self.update()
        return True

    def set_pdf(self, path):
        if not QTPDF_AVAILABLE:
            return False
        try:
            doc = QPdfDocument()
            load_result = doc.load(path)
            ok = (load_result is None) or (str(load_result).endswith("None_")) or (int(load_result) == 0)
        except Exception:
            return False
        if not ok:
            return False
        try:
            if doc.pageCount() < 1:
                return False
            target = QSize(max(1, self.width() * 3), max(1, self.height() * 3))
            img = doc.render(0, target)
            if img is None or img.isNull():
                return False
            self._pixmap = QPixmap.fromImage(img)
            self._mode = "image"
            self.update()
            return True
        except Exception:
            return False

    def set_placeholder(self, entry):
        self._mode, self._pixmap = "placeholder", None
        self._icon = PRINT_EXTENSIONS.get(entry["ext"], (None, GENERIC_FILE_ICON))[1]
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(0, 0, self.width(), self.height())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("white"))
        p.drawRoundedRect(rect, 6, 6)
        if self._mode == "image" and self._pixmap is not None:
            margin = rect.width() * 0.07
            inner = rect.adjusted(margin, margin, -margin, -margin)
            scaled = self._pixmap.scaled(max(1, int(inner.width())), max(1, int(inner.height())),
                                         Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            x = inner.left() + (inner.width() - scaled.width()) / 2
            y = inner.top() + (inner.height() - scaled.height()) / 2
            p.drawPixmap(int(x), int(y), scaled)
        elif self._mode == "placeholder":
            p.setPen(QColor(MUTED_LIGHT))
            f = p.font(); f.setPointSize(30); p.setFont(f)
            p.drawText(rect.adjusted(0, 0, 0, -rect.height() * 0.32), Qt.AlignmentFlag.AlignCenter, self._icon)
        else:
            p.setPen(QPen(QColor(BORDER), 2, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect.adjusted(7, 7, -7, -7), 8, 8)
            p.setPen(QColor(MUTED_LIGHT))
            f = p.font(); f.setPointSize(26); p.setFont(f)
            p.drawText(rect.adjusted(0, 0, 0, -rect.height() * 0.30), Qt.AlignmentFlag.AlignCenter, "🖹")
        p.end()


class FilePreviewPanel(QFrame):
    """Read-only print preview + the actual print confirmation. Images show
    exactly how they'll be scaled and centred on Short (Letter) paper; PDFs
    show their first page when PyQt6-QtPdf is installed; every other
    supported type shows a plain icon, since Windows has no universal way
    to rasterize arbitrary document formats outside their own program."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("previewPanel")
        self.setFixedWidth(330)
        self.setStyleSheet(f"QFrame#previewPanel{{background:{WHITE};border:none;border-radius:20px;}}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(10)
        cap = QLabel("PRINT PREVIEW")
        cap.setStyleSheet(f"color:{BANNER_2};font-size:10px;font-weight:950;letter-spacing:1.4px;background:transparent;")
        lay.addWidget(cap)

        stage = QWidget()
        stage_lay = QVBoxLayout(stage)
        stage_lay.setContentsMargins(0, 6, 0, 6)
        self.page = PagePreview()
        stage_lay.addWidget(self.page, alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(stage, 1)

        self.note = QLabel("Select a file on the left to preview it here.")
        self.note.setWordWrap(True)
        self.note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.note.setStyleSheet(f"color:{MUTED_LIGHT};font-size:10px;font-weight:700;background:transparent;")
        lay.addWidget(self.note)

        self.name_label = QLabel("")
        self.name_label.setWordWrap(True)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setStyleSheet(f"color:{TEXT};font-size:12px;font-weight:900;background:transparent;")
        self.meta_label = QLabel("")
        self.meta_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.meta_label.setStyleSheet(f"color:{MUTED};font-size:10px;font-weight:700;background:transparent;")
        lay.addWidget(self.name_label)
        lay.addWidget(self.meta_label)

        self.print_btn = QPushButton("🖨   PRINT THIS FILE")
        self.print_btn.setMinimumHeight(54)
        self.print_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.print_btn.setEnabled(False)
        self.print_btn.setStyleSheet(
            f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {BANNER_2},stop:1 {BANNER_1});color:white;"
            f"border:none;border-radius:14px;padding:0 16px;font-size:12px;font-weight:950;}} "
            f"QPushButton:disabled{{background:#E6DAD4;color:white;}} QPushButton:pressed{{background:#C82E48;}}"
        )
        lay.addWidget(self.print_btn)
        self.clear()

    def clear(self):
        self.page.set_empty()
        self.note.show()
        self.note.setText("Select a file on the left to preview it here.")
        self.name_label.setText("")
        self.meta_label.setText("")
        self.print_btn.setEnabled(False)

    def show_entry(self, entry):
        ext = entry["ext"]
        self.name_label.setText(entry["name"])
        kind = PRINT_EXTENSIONS.get(ext, ("File",))[0]
        note_suffix = "  •  prints on Short paper" if ext in IMAGE_EXTENSIONS else ""
        self.meta_label.setText(f"{kind}  •  {human_size(entry['size'])}{note_suffix}")
        self.print_btn.setEnabled(ext in PRINT_EXTENSIONS)

        if ext in IMAGE_EXTENSIONS:
            ok = self.page.set_image(entry["path"])
            self.note.setText("" if ok else "Couldn't open this image for preview.")
            self.note.setVisible(not ok)
        elif ext == ".pdf" and QTPDF_AVAILABLE and self.page.set_pdf(entry["path"]):
            self.note.hide()
        else:
            self.page.set_placeholder(entry)
            self.note.show()
            self.note.setText("No visual preview for this file type — it will print through its own "
                              "program, which may look slightly different." if ext in PRINT_EXTENSIONS
                              else "This file type can't be printed here.")



class PrintScreen(QFrame):
    """Self-contained USB file browser + print screen. Sandboxed to
    removable drives only — it can never navigate above a USB drive's root,
    so it never exposes the kiosk's own disk (similar in spirit to a
    website's file-upload picker, but read-only and print-only)."""
    back = pyqtSignal()

    def __init__(self, member=None, log_fn=None, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"QFrame{{background:{BACKGROUND};border:none;}}")
        self.member = member
        self._log_fn = log_fn
        self._drives, self._drive, self._root, self._path = [], None, None, None
        self._entries, self._tiles, self._selected_entry, self._printing = [], [], None, False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        header = QFrame()
        header.setStyleSheet(f"QFrame{{background:{WHITE};border:none;border-radius:20px;}}")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(22, 16, 22, 16)
        hl.setSpacing(16)
        back_btn = QPushButton("←  BACK")
        back_btn.setMinimumHeight(46)
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.setStyleSheet(f"QPushButton{{background:#E3EBF6;color:{TEXT};border:none;border-radius:12px;padding:0 18px;font-weight:900;}} "
                               f"QPushButton:pressed{{background:#E2D8D2;}}")
        back_btn.clicked.connect(self.back.emit)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        t = QLabel("PRINT A FILE")
        t.setStyleSheet(f"color:{TEXT};font-size:27px;font-weight:950;background:transparent;")
        member_name = str((member or {}).get("full_name") or "").strip()
        sub_text = f"Printing for {member_name}  •  choose a file from the USB drive." if member_name else "Insert a USB drive, then choose a file to print."
        sub = QLabel(sub_text)
        sub.setStyleSheet(f"color:{MUTED};font-size:12px;font-weight:700;background:transparent;")
        title_col.addWidget(t)
        title_col.addWidget(sub)
        hl.addWidget(back_btn)
        hl.addLayout(title_col, 1)
        self.status_badge = StatusBadge(SECONDARY, "doc", 46, working=False)
        self.status_badge.hide()
        self.status_label = QLabel("")
        self.status_label.setWordWrap(False)
        self.status_label.hide()
        hl.addWidget(self.status_badge)
        hl.addWidget(self.status_label)
        root.addWidget(header)

        self.drive_card = QFrame()
        self.drive_card.setStyleSheet(f"QFrame{{background:{WHITE};border:none;border-radius:18px;}}")
        dl = QVBoxLayout(self.drive_card)
        dl.setContentsMargins(18, 14, 18, 14)
        dl.setSpacing(8)
        cap = QLabel("USB DRIVES")
        cap.setStyleSheet(f"color:{BANNER_2};font-size:10px;font-weight:950;letter-spacing:1.4px;background:transparent;")
        dl.addWidget(cap)
        self.drive_row = QHBoxLayout()
        self.drive_row.setSpacing(10)
        dl.addLayout(self.drive_row)
        root.addWidget(self.drive_card)

        self.empty_card = QFrame()
        self.empty_card.setStyleSheet(f"QFrame{{background:{WHITE};border:2px dashed {BORDER};border-radius:22px;}}")
        el = QVBoxLayout(self.empty_card)
        el.setAlignment(Qt.AlignmentFlag.AlignCenter)
        el.setSpacing(8)
        plug = QLabel("🔌")
        plug.setAlignment(Qt.AlignmentFlag.AlignCenter)
        plug.setStyleSheet("font-size:52px;background:transparent;")
        self._waiting_label = QLabel("WAITING FOR A USB DRIVE…")
        self._waiting_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._waiting_label.setStyleSheet(f"color:{MUTED};font-size:13px;font-weight:950;letter-spacing:1px;background:transparent;")
        hint = QLabel("Plug a USB flash drive into the kiosk. It will appear here automatically.")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{MUTED_LIGHT};font-size:11px;font-weight:700;background:transparent;")
        el.addWidget(plug)
        el.addWidget(self._waiting_label)
        el.addWidget(hint)
        root.addWidget(self.empty_card, 1)
        self._breathe(self._waiting_label)

        self.browser = QFrame()
        bl = QVBoxLayout(self.browser)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(10)
        toolbar = QFrame()
        toolbar.setStyleSheet(f"QFrame{{background:{WHITE};border:none;border-radius:16px;}}")
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(14, 8, 14, 8)
        tl.setSpacing(10)
        self.up_btn = QPushButton("⬆  UP")
        self.up_btn.setMinimumHeight(40)
        self.up_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.up_btn.setStyleSheet(f"QPushButton{{background:#F4F7FB;color:{TEXT};border:none;border-radius:10px;padding:0 14px;font-weight:900;}} "
                                  f"QPushButton:disabled{{color:{MUTED_LIGHT};}}")
        self.up_btn.clicked.connect(self.go_up)
        self.breadcrumb = QLabel("")
        self.breadcrumb.setStyleSheet(f"color:{MUTED};font-size:12px;font-weight:800;background:transparent;")
        refresh_btn = QPushButton("↻  REFRESH")
        refresh_btn.setMinimumHeight(40)
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.setStyleSheet(f"QPushButton{{background:#F4F7FB;color:{TEXT};border:none;border-radius:10px;padding:0 14px;font-weight:900;}}")
        refresh_btn.clicked.connect(lambda: self.open_path(self._path) if self._path else None)
        tl.addWidget(self.up_btn)
        tl.addWidget(self.breadcrumb, 1)
        tl.addWidget(refresh_btn)
        bl.addWidget(toolbar)

        content_row = QHBoxLayout()
        content_row.setSpacing(14)

        left_col = QVBoxLayout()
        left_col.setSpacing(8)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("QScrollArea{background:transparent;border:none;} QWidget#printGridHost{background:transparent;}")
        grid_host = QWidget()
        grid_host.setObjectName("printGridHost")
        self.grid = QGridLayout(grid_host)
        self.grid.setContentsMargins(4, 4, 4, 4)
        self.grid.setSpacing(12)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.scroll.setWidget(grid_host)
        left_col.addWidget(self.scroll, 1)

        self.empty_folder_label = QLabel("This folder is empty.")
        self.empty_folder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_folder_label.setStyleSheet(f"color:{MUTED_LIGHT};font-size:13px;font-weight:800;background:transparent;")
        self.empty_folder_label.hide()
        left_col.addWidget(self.empty_folder_label)
        content_row.addLayout(left_col, 1)

        self.preview = FilePreviewPanel()
        self.preview.print_btn.clicked.connect(self.print_selected)
        content_row.addWidget(self.preview)

        bl.addLayout(content_row, 1)

        root.addWidget(self.browser, 1)
        self.browser.hide()

        self._poll = QTimer(self)
        self._poll.setInterval(2000)
        self._poll.timeout.connect(self._poll_drives)
        self._poll.start()
        self._poll_drives(initial=True)

    # ---- lifecycle ------------------------------------------------------
    def stop(self):
        self._poll.stop()

    def _breathe(self, label):
        fx = QGraphicsOpacityEffect(label)
        label.setGraphicsEffect(fx)
        a = QPropertyAnimation(fx, b"opacity", label)
        a.setDuration(1400)
        a.setStartValue(1.0)
        a.setKeyValueAt(0.5, 0.35)
        a.setEndValue(1.0)
        a.setLoopCount(-1)
        a.setEasingCurve(QEasingCurve.Type.InOutSine)
        label._breathe_anim = a
        a.start()

    # ---- drive handling ---------------------------------------------------
    def _poll_drives(self, initial=False):
        if self._printing or sip.isdeleted(self):
            return
        drives = list_removable_drives()
        changed = [d["path"] for d in drives] != [d["path"] for d in self._drives]
        self._drives = drives
        if not drives:
            if self._drive is not None:
                self._waiting_label.setText("USB DRIVE REMOVED")
                QTimer.singleShot(2400, lambda: self._waiting_label.setText("WAITING FOR A USB DRIVE…") if not sip.isdeleted(self) else None)
            self._drive = None
            self.browser.hide()
            self.drive_card.hide()
            self.empty_card.show()
            return
        self.drive_card.show()
        if changed or initial:
            self._rebuild_drive_chips()
        still_here = self._drive and any(d["path"] == self._drive["path"] for d in drives)
        if not still_here:
            self.select_drive(drives[0])
        elif changed:
            self._drive = next(d for d in drives if d["path"] == self._drive["path"])

    def _rebuild_drive_chips(self):
        while self.drive_row.count():
            it = self.drive_row.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for d in self._drives:
            chip = DriveChip(d)
            chip.set_active(self._drive is not None and d["path"] == self._drive["path"])
            chip.selected.connect(lambda _=False, d=d: self.select_drive(d))
            self.drive_row.addWidget(chip, 1)

    def select_drive(self, drive):
        self._drive = drive
        self._root = drive["path"]
        self.empty_card.hide()
        self.browser.show()
        for i in range(self.drive_row.count()):
            w = self.drive_row.itemAt(i).widget()
            if isinstance(w, DriveChip):
                w.set_active(w.drive["path"] == drive["path"])
        self.open_path(drive["path"])

    # ---- folder browsing ----------------------------------------------------
    def open_path(self, path):
        self._selected_entry = None
        self.preview.clear()
        try:
            entries = list_dir_entries(self._root, path)
        except ApiError as exc:
            self._clear_grid()
            self.empty_folder_label.setText(str(exc))
            self.empty_folder_label.show()
            return
        self._path = path
        self._entries = entries
        rel = os.path.relpath(path, self._root)
        crumb = self._drive["label"] if rel in (".", "") else f"{self._drive['label']}  ›  " + rel.replace(os.sep, "  ›  ")
        self.breadcrumb.setText(crumb)
        self.up_btn.setEnabled(rel not in (".", ""))
        self._render_grid()

    def go_up(self):
        if not self._path:
            return
        parent = os.path.dirname(self._path.rstrip("\\/")) or self._root
        if _within_root(self._root, parent):
            self.open_path(parent)

    def _clear_grid(self):
        for tile in self._tiles:
            tile.setParent(None)
            tile.deleteLater()
        self._tiles = []

    def _render_grid(self):
        self._clear_grid()
        if not self._entries:
            self.empty_folder_label.setText("This folder is empty.")
            self.empty_folder_label.show()
            return
        self.empty_folder_label.hide()
        cols = max(1, (self.scroll.viewport().width() or 900) // 190)
        for i, entry in enumerate(self._entries):
            tile = PrintTile(entry)
            tile.activated.connect(lambda _=False, e=entry, t=tile: self._activate(e, t))
            self.grid.addWidget(tile, i // cols, i % cols)
            self._tiles.append(tile)
        stagger_fade(self._tiles[:24], start=0, step=16, duration=220)

    def _activate(self, entry, tile):
        if entry["is_dir"]:
            self.open_path(entry["path"])
            return
        for t in self._tiles:
            t.set_selected(t is tile)
        self._selected_entry = entry
        self.preview.show_entry(entry)

    # ---- printing ------------------------------------------------------------
    def print_selected(self):
        entry = self._selected_entry
        if not entry or self._printing:
            return
        self._printing = True
        self.preview.print_btn.setEnabled(False)
        self.status_badge.working = True
        self.status_badge._res = 0.0
        self.status_badge._timer.start()
        self.status_badge.show()
        is_image = entry["ext"] in IMAGE_EXTENSIONS
        label = "PHOTO" if is_image else "FILE"
        self.status_label.setStyleSheet(f"color:{SECONDARY};font-size:11px;font-weight:900;background:transparent;")
        self.status_label.setText(f"PRINTING {label} “{entry['name']}” ON SHORT PAPER…" if is_image else f"SENDING “{entry['name']}” TO THE PRINTER…")
        self.status_label.show()
        path = entry["path"]

        def job():
            # Photos print silently, straight to Short (Letter) paper, with no
            # popup dialog. Other file types still open their default app's
            # own print handling, which may show that app's own dialog.
            if is_image and SILENT_IMAGE_PRINT_AVAILABLE:
                print_image_silent(path)
            elif is_image:
                print_file(path)  # pywin32/Pillow missing — falls back to the Photos dialog
            else:
                print_file(path)

        def finish(ok, text):
            if sip.isdeleted(self):
                return
            self._printing = False
            self.preview.print_btn.setEnabled(self._selected_entry is not None)
            self.status_badge.working = False
            self.status_badge.show_result("ok" if ok else "error")
            self.status_label.setStyleSheet(f"color:{SUCCESS if ok else DANGER};font-size:11px;font-weight:900;background:transparent;")
            self.status_label.setText(text)
            QTimer.singleShot(4500, lambda: (self.status_badge.hide(), self.status_label.hide()) if not sip.isdeleted(self) else None)
            if self._log_fn:
                try: self._log_fn(entry, ok, None if ok else text)
                except Exception: pass

        def done(t):
            if t.error is not None:
                finish(False, str(t.error).upper())
            else:
                finish(True, "PRINTED ✓" if is_image else "SENT TO THE PRINTER ✓")

        task = ApiTask(job, self)
        task.done.connect(done)
        task.finished.connect(task.deleteLater)
        task.start()


class TapFrame(QFrame):
    tapped = pyqtSignal()

    def mousePressEvent(self, event):
        self.tapped.emit()
        super().mousePressEvent(event)


def find_asset(*parts):
    """Look for assets/<file> next to this script, in the project root, the working folder,
    or beside the packaged .exe (PyInstaller)."""
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
    """Round white badge showing assets/school_logo.png (falls back to 'SMPCS' text if missing)."""
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
            f = p.font()
            f.setBold(True)
            f.setPixelSize(max(12, int(s * 0.22)))
            p.setFont(f)
            p.setPen(QColor("#8D1E2D"))
            p.drawText(QRectF(0, 0, s, s), Qt.AlignmentFlag.AlignCenter, "SMPCS")
        p.end()


class BannerFrame(QFrame):
    """Top banner with a soft light streak that sweeps across every few seconds."""
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
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = float(self.width())
        g = QLinearGradient(0, 0, w, 0)
        g.setColorAt(0.0, QColor(BANNER_2))
        g.setColorAt(0.6, QColor("#2D73BC"))
        g.setColorAt(1.0, QColor("#3493B8"))
        p.fillRect(self.rect(), QBrush(g))
        # streak passes once every ~7 seconds
        cycle = ((clock() - self._t0) % 7.0) / 7.0
        if cycle < 0.55 and MOTION_ENABLED:
            x = lerp(-160.0, w + 160.0, cycle / 0.55)
            sh = QLinearGradient(x - 120, 0, x + 120, 0)
            sh.setColorAt(0.0, QColor(255, 255, 255, 0))
            sh.setColorAt(0.5, QColor(255, 255, 255, 46))
            sh.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.fillRect(self.rect(), QBrush(sh))
        p.end()


class ShimmerButton(QPushButton):
    """Subtle moving highlight; intentionally unrelated to RFID."""
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._shine = QLabel(self)
        self._shine.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._shine.setFixedSize(34, 7)
        self._shine.setStyleSheet("background: rgba(255,255,255,105); border-radius: 3px;")
        self._shine_x = -50
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._move_shine)
        self._timer.start()

    def _move_shine(self):
        if not self.isVisible() or self.width() <= 0:
            return
        self._shine_x += 5
        if self._shine_x > self.width() + 20:
            self._shine_x = -50
        self._shine.move(self._shine_x, max(8, self.height() // 2))
        self._shine.raise_()


class FloatingDot(QLabel):
    def __init__(self, parent, color, size, start, end, duration):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setStyleSheet(f"background:{color}; border-radius:{size//2}px;")
        self.move(*start)
        self._anim = QPropertyAnimation(self, b"pos", self)
        self._anim.setStartValue(QPoint(*start))
        self._anim.setEndValue(QPoint(*end))
        self._anim.setDuration(duration)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._anim.finished.connect(self._reverse)
        self._anim.start()

    def _reverse(self):
        self._anim.setDirection(
            QPropertyAnimation.Direction.Backward
            if self._anim.direction() == QPropertyAnimation.Direction.Forward
            else QPropertyAnimation.Direction.Forward
        )
        self._anim.start()


# ============================================================
# STATUS BADGE  (spinner  ->  animated check / alert / cross)
# ============================================================

class StatusBadge(QWidget):
    """
    Large animated badge.
      working=True  : rotating arcs + orbiting dots around a bobbing icon (book / card / doc)
      show_result() : the ring closes, the icon dissolves, and a check / "!" / cross is drawn
                      stroke-by-stroke with a little pop (cross also shakes).
    """
    def __init__(self, accent=BANNER_2, icon="book", size=176, working=True, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.accent = QColor(accent)
        self.icon = icon
        self.working = working
        self._res = 0.0
        self._kind = "ok"
        self._anim = None
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self.update)
        self._timer.start()

    def show_result(self, kind="ok", duration=780, delay=0):
        self._kind = kind
        anim = QVariantAnimation()
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(duration)
        anim.setEasingCurve(QEasingCurve.Type.Linear)
        anim.valueChanged.connect(self._set_res)
        group = QSequentialAnimationGroup(self)
        if delay > 0:
            group.addPause(int(delay))
        group.addAnimation(anim)
        group.finished.connect(self._finished)
        self._anim = group
        group.start()

    def _set_res(self, v):
        self._res = float(v)
        self.update()

    def _finished(self):
        self._res = 1.0
        self.update()
        self._timer.stop()

    def _draw_icon(self, p: QPainter):
        c = self.accent
        p.setPen(Qt.PenStyle.NoPen)
        if self.icon == "card":
            p.setBrush(c)
            p.drawRoundedRect(QRectF(-27, -18, 54, 36), 7, 7)
            p.setBrush(QColor(255, 255, 255, 235))
            p.drawEllipse(QPointF(-13, -3), 6, 6)
            p.drawRoundedRect(QRectF(-20, 6, 14, 5), 2, 2)
            p.setPen(round_pen(QColor(255, 255, 255, 220), 3))
            p.drawLine(QPointF(3, -6), QPointF(20, -6))
            p.drawLine(QPointF(3, 3), QPointF(16, 3))
            return
        if self.icon == "doc":
            p.setBrush(c)
            p.drawRoundedRect(QRectF(-19, -25, 38, 50), 6, 6)
            p.setPen(round_pen(QColor(255, 255, 255, 230), 3.5))
            for i, wd in enumerate((22, 22, 14)):
                y = -11 + i * 11
                p.drawLine(QPointF(-11, y), QPointF(-11 + wd, y))
            return
        # open book
        left = QPainterPath()
        left.moveTo(-2, -12); left.lineTo(-27, -17); left.lineTo(-27, 15); left.lineTo(-2, 20); left.closeSubpath()
        right = QPainterPath()
        right.moveTo(2, -12); right.lineTo(27, -17); right.lineTo(27, 15); right.lineTo(2, 20); right.closeSubpath()
        p.setBrush(c)
        p.drawPath(left)
        p.setBrush(mix(c, "#000000", 0.12))
        p.drawPath(right)
        p.setPen(round_pen(QColor(255, 255, 255, 220), 2.6))
        for i in range(3):
            y = -6 + i * 7
            p.drawLine(QPointF(-21, y - 1), QPointF(-9, y + 1))
            p.drawLine(QPointF(9, y + 1), QPointF(21, y - 1))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        s = float(self.width())
        cx = cy = s / 2.0
        k = s / 176.0
        t = clock()
        res = self._res
        kind = self._kind
        end_col = {"ok": QColor(SUCCESS), "error": QColor(DANGER)}.get(kind, self.accent)
        col = mix(self.accent, end_col, ease_in_out(res * 2.0))

        # pop / shake
        p.translate(cx, cy)
        if res > 0.0:
            if kind == "error":
                p.translate(9.0 * math.sin(res * 26.0) * (1.0 - res), 0)
            x = clamp01((res - 0.5) / 0.5)
            sc = 1.0 + 0.10 * math.sin(math.pi * x)
            p.scale(sc, sc)
        p.translate(-cx, -cy)

        # soft disc
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(with_alpha(col, 26 + 22 * res))
        p.drawEllipse(QPointF(cx, cy), s / 2 - 6, s / 2 - 6)

        # ring track + main arc
        R = s / 2 - 14
        rect = QRectF(cx - R, cy - R, 2 * R, 2 * R)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(round_pen(with_alpha(col, 46), 8 * k))
        p.drawEllipse(rect)
        if self.working or res > 0.0:
            span0 = 100.0 if self.working else 0.0
            span = lerp(span0, 360.0, ease_out_cubic(res / 0.55))
            start = (90.0 - t * 230.0) % 360.0 if self.working else 90.0
            p.setPen(round_pen(col, 8 * k))
            p.drawArc(rect, int(start * 16), int(-span * 16))

        # inner counter-rotating arc + orbiting dots (only while working)
        if self.working:
            fade = clamp01(1.0 - res / 0.45)
            if fade > 0.0:
                R2 = R - 16 * k
                rect2 = QRectF(cx - R2, cy - R2, 2 * R2, 2 * R2)
                p.setPen(round_pen(with_alpha(mix(self.accent, "#FFFFFF", 0.35), 200 * fade), 5 * k))
                p.drawArc(rect2, int(((t * 330.0) % 360.0) * 16), int(70 * 16))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(with_alpha(self.accent, 170 * fade))
                r3 = R2 - 15 * k
                for i in range(3):
                    a = math.radians(t * 150.0 + i * 120.0)
                    p.drawEllipse(QPointF(cx + r3 * math.cos(a), cy + r3 * math.sin(a)), 3.2 * k, 3.2 * k)

        # centre icon (dissolves as result appears)
        icon_alpha = clamp01(1.0 - res * 2.2)
        if icon_alpha > 0.0:
            p.save()
            p.translate(cx, cy + 3.0 * math.sin(t * 3.0))
            p.scale(k, k)
            p.setOpacity(icon_alpha)
            self._draw_icon(p)
            p.restore()

        # result glyph
        g = ease_out_cubic(clamp01((res - 0.42) / 0.58))
        if g > 0.0:
            p.setPen(round_pen(end_col, 10 * k))
            p.setBrush(Qt.BrushStyle.NoBrush)
            if kind == "ok":
                pts = [QPointF(cx - 24 * k, cy + 2 * k), QPointF(cx - 8 * k, cy + 18 * k), QPointF(cx + 25 * k, cy - 17 * k)]
                draw_partial_polyline(p, pts, g)
            elif kind == "error":
                a = [QPointF(cx - 17 * k, cy - 17 * k), QPointF(cx + 17 * k, cy + 17 * k)]
                b = [QPointF(cx + 17 * k, cy - 17 * k), QPointF(cx - 17 * k, cy + 17 * k)]
                draw_partial_polyline(p, a, clamp01(g * 2.0))
                draw_partial_polyline(p, b, clamp01(g * 2.0 - 1.0))
            else:
                draw_partial_polyline(p, [QPointF(cx, cy - 26 * k), QPointF(cx, cy + 6 * k)], g)
                if g > 0.7:
                    r = 6.0 * k * clamp01((g - 0.7) / 0.3)
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(end_col)
                    p.drawEllipse(QPointF(cx, cy + 24 * k), r, r)
        p.end()


# ============================================================
# PROCESSING SCREEN  ("Verifying your book borrow request ...")
# ============================================================

class ProgressTrack(QWidget):
    def __init__(self, accent=BANNER_2, parent=None):
        super().__init__(parent)
        self.setFixedHeight(12)
        self.value = 0.0
        self.accent = QColor(accent)
        self.failed = False

    def set_value(self, v):
        self.value = clamp01(v)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = float(self.width())
        h = float(self.height())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#EFE5DF"))
        p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
        if self.value <= 0.0:
            p.end()
            return
        fw = max(h, w * self.value)
        base = QColor(DANGER) if self.failed else self.accent
        g = QLinearGradient(0, 0, fw, 0)
        g.setColorAt(0.0, base)
        g.setColorAt(1.0, base if self.failed else mix(base, "#FFC45D", 0.55))
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, fw, h), h / 2, h / 2)
        p.fillPath(path, QBrush(g))
        if not self.failed:
            p.save()
            p.setClipPath(path)
            x = (clock() * 220.0) % (fw + 120.0) - 60.0
            sh = QLinearGradient(x - 40, 0, x + 40, 0)
            sh.setColorAt(0.0, QColor(255, 255, 255, 0))
            sh.setColorAt(0.5, QColor(255, 255, 255, 120))
            sh.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.fillRect(QRectF(0, 0, fw, h), QBrush(sh))
            p.restore()
        p.end()


class StepIcon(QWidget):
    """pending: hollow ring | active: spinning arc | done: green disc + drawn check | error: red disc + X"""
    def __init__(self, accent=BANNER_2, parent=None):
        super().__init__(parent)
        self.setFixedSize(28, 28)
        self.accent = QColor(accent)
        self.state = "pending"
        self._pop = 1.0
        self._anim = None

    def set_state(self, state):
        self.state = state
        if self._anim is not None:
            self._anim.stop()
            self._anim.deleteLater()
        self._pop = 0.0
        a = QVariantAnimation(self)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.setDuration(340)
        a.setEasingCurve(QEasingCurve.Type.OutCubic)
        a.valueChanged.connect(self._set_pop)
        self._anim = a
        a.start()
        self.update()

    def _set_pop(self, v):
        self._pop = float(v)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        c = QPointF(14, 14)
        pop = self._pop
        if self.state == "pending":
            p.setPen(round_pen("#D8CBC4", 2.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, 9, 9)
        elif self.state == "active":
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(round_pen(with_alpha(self.accent, 55), 3))
            p.drawEllipse(c, 9, 9)
            p.setPen(round_pen(self.accent, 3))
            p.drawArc(QRectF(5, 5, 18, 18), int(((90.0 - clock() * 360.0) % 360.0) * 16), int(-100 * 16))
        elif self.state == "done":
            sc = 0.55 + 0.45 * clamp01(pop * 1.6)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(SUCCESS))
            p.drawEllipse(c, 11 * sc, 11 * sc)
            p.setPen(round_pen("white", 2.8))
            pts = [QPointF(8.5, 14.5), QPointF(12.5, 18.5), QPointF(19.5, 10.0)]
            draw_partial_polyline(p, pts, clamp01((pop - 0.25) / 0.75))
        else:
            sc = 0.55 + 0.45 * clamp01(pop * 1.6)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(DANGER))
            p.drawEllipse(c, 11 * sc, 11 * sc)
            p.setPen(round_pen("white", 2.8))
            g = clamp01((pop - 0.2) / 0.8)
            draw_partial_polyline(p, [QPointF(9.5, 9.5), QPointF(18.5, 18.5)], clamp01(g * 2.0))
            draw_partial_polyline(p, [QPointF(18.5, 9.5), QPointF(9.5, 18.5)], clamp01(g * 2.0 - 1.0))
        p.end()


class StepRow(QFrame):
    def __init__(self, text, accent=BANNER_2, parent=None):
        super().__init__(parent)
        self.setObjectName("stepRow")
        self.text = text
        self.accent = accent
        self.state = "pending"
        self.icon = StepIcon(accent)
        self.label = QLabel(text)
        self.tag = QLabel("")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 14, 6)
        lay.setSpacing(12)
        lay.addWidget(self.icon)
        lay.addWidget(self.label, 1)
        lay.addWidget(self.tag)
        self.setMinimumHeight(42)
        self._apply()

    def set_state(self, state):
        if state == self.state:
            return
        self.state = state
        self.icon.set_state(state)
        self._apply()

    def _apply(self):
        bg, color, weight, tag, tag_color = "transparent", MUTED_LIGHT, 700, "", MUTED
        if self.state == "active":
            bg, color, weight, tag, tag_color = ACCENT_LIGHT, TEXT, 900, "WORKING", self.accent
        elif self.state == "done":
            color, weight, tag, tag_color = TEXT, 800, "DONE", SUCCESS
        elif self.state == "error":
            bg, color, weight, tag, tag_color = DANGER_BG, DANGER, 900, "FAILED", DANGER
        self.setStyleSheet(f"QFrame#stepRow{{background:{bg};border:none;border-radius:12px;}}")
        self.label.setStyleSheet(f"color:{color};font-size:13px;font-weight:{weight};background:transparent;")
        self.tag.setText(tag)
        self.tag.setStyleSheet(f"color:{tag_color};font-size:8px;font-weight:950;letter-spacing:1px;background:transparent;")


class ProcessingScreen(QFrame):
    """
    Full-page 'please wait' screen.
    - spinner badge that morphs into a check / cross
    - step checklist that ticks off one by one (each check is drawn stroke-by-stroke)
    - shimmering progress bar and animated dots
    The real API call runs in a worker thread; call finish(ok, callback) when it returns.
    """
    def __init__(self, title, subtitle, steps, accent=BANNER_2, icon="book", chip=None,
                 min_ms=1700, step_ms=760, parent=None):
        super().__init__(parent)
        self.setObjectName("procPage")
        self.setStyleSheet(f"QFrame#procPage{{background:{BACKGROUND};border:none;}}")
        self._min_ms = min_ms
        self._step_ms = step_ms
        self._t0 = clock()
        self._last_step = self._t0
        self._active = 0
        self._state = "running"
        self._finish = None
        self._ok = True
        self._cb = None
        self._final_text = ""
        self._settle_until = 0.0
        self._p = 0.0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card = QFrame()
        card.setObjectName("procCard")
        card.setFixedWidth(840)
        card.setStyleSheet(f"QFrame#procCard{{background:{WHITE};border:none;border-radius:30px;}}")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(44, 28, 44, 26)
        cl.setSpacing(10)

        eyebrow = QLabel("PLEASE WAIT")
        eyebrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        eyebrow.setStyleSheet(f"color:{accent};font-size:10px;font-weight:950;letter-spacing:2px;background:transparent;")
        self.title = QLabel(title.upper())
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setWordWrap(True)
        self.title.setStyleSheet(f"color:{TEXT};font-size:25px;font-weight:950;background:transparent;")
        self.status = QLabel(subtitle)
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setStyleSheet(f"color:{MUTED};font-size:13px;font-weight:750;background:transparent;")
        cl.addWidget(eyebrow)
        cl.addWidget(self.title)
        cl.addWidget(self.status)

        self.chip = None
        if chip:
            self.chip = QLabel(chip)
            self.chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.chip.setStyleSheet(f"background:{ACCENT_LIGHT};color:{ACCENT_DARK};border-radius:13px;padding:6px 16px;font-size:11px;font-weight:900;")
            cl.addWidget(self.chip, alignment=Qt.AlignmentFlag.AlignHCenter)

        body = QHBoxLayout()
        body.setSpacing(34)
        self.badge = StatusBadge(accent, icon, 176, working=True)
        body.addWidget(self.badge, alignment=Qt.AlignmentFlag.AlignVCenter)
        col = QVBoxLayout()
        col.setSpacing(4)
        self.rows = []
        for s in steps:
            row = StepRow(s, accent)
            col.addWidget(row)
            self.rows.append(row)
        body.addLayout(col, 1)
        cl.addLayout(body)

        self.track = ProgressTrack(accent)
        cl.addSpacing(4)
        cl.addWidget(self.track)
        foot = QLabel("This only takes a moment  •  please do not tap another card")
        foot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        foot.setStyleSheet(f"color:{MUTED};font-size:10px;font-weight:700;background:transparent;")
        cl.addWidget(foot)
        root.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)

        self.rows[0].set_state("active")
        stagger_fade(self.rows, start=120, step=90, duration=340)

        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ---- public -------------------------------------------------------
    def finish(self, ok: bool, callback: Callable, message: Optional[str] = None):
        self._finish = True
        self._ok = ok
        self._cb = callback
        self._final_text = message or ("ALL DONE" if ok else "SOMETHING WENT WRONG")

    # ---- internals ----------------------------------------------------
    def _advance(self) -> bool:
        self.rows[self._active].set_state("done")
        if self._active < len(self.rows) - 1:
            self._active += 1
            self.rows[self._active].set_state("active")
            return True
        return False

    def _succeed(self, now):
        self._state = "settling"
        self._settle_until = now + 1.05
        self.badge.show_result("ok")
        self.status.setText(self._final_text)
        self.status.setStyleSheet(f"color:{SUCCESS};font-size:13px;font-weight:950;letter-spacing:1px;background:transparent;")

    def _fail(self, now):
        self._state = "settling"
        self._settle_until = now + 1.3
        self.rows[self._active].set_state("error")
        self.track.failed = True
        self.badge.show_result("error")
        self.status.setText(self._final_text)
        self.status.setStyleSheet(f"color:{DANGER};font-size:13px;font-weight:950;letter-spacing:1px;background:transparent;")

    def _tick(self):
        now = clock()
        n = len(self.rows)
        elapsed_ms = (now - self._t0) * 1000.0
        target = self._p

        if self._state == "running":
            if self._active < n - 1 and (now - self._last_step) * 1000.0 >= self._step_ms:
                self._last_step = now
                self._advance()
            target = min(0.92, (self._active + 0.55) / n)
            if self._finish and elapsed_ms >= self._min_ms:
                if self._ok:
                    self._state = "finishing"
                    self._last_step = now - 1.0
                else:
                    self._fail(now)
        elif self._state == "finishing":
            target = min(1.0, (self._active + 0.9) / n)
            if (now - self._last_step) * 1000.0 >= 170.0:
                self._last_step = now
                if not self._advance():
                    self._succeed(now)
        elif self._state == "settling":
            target = 1.0 if self._ok else self._p
            if now >= self._settle_until:
                self._state = "done"
                self._timer.stop()
                cb, self._cb = self._cb, None
                if cb:
                    cb()

        self._p += (target - self._p) * 0.14
        if self._state == "settling" and self._ok:
            self._p = max(self._p, 0.995)
        self.track.set_value(self._p)

        if self._state in ("running", "finishing"):
            k = int(now * 3.0) % 4
            self.status.setText(f"{self.rows[self._active].text}{'.' * k}{chr(0x00A0) * (3 - k)}")
        for row in self.rows:
            if row.state == "active":
                row.icon.update()


# ============================================================
# RESULT-SCREEN EXTRAS
# ============================================================

class CountdownBar(QWidget):
    """Thin bar that drains while the result screen waits to return to start."""
    def __init__(self, ms, color, parent=None):
        super().__init__(parent)
        self.setFixedHeight(8)
        self._v = 1.0
        self.color = QColor(color)
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.setDuration(int(ms))
        self._anim.setEasingCurve(QEasingCurve.Type.Linear)
        self._anim.valueChanged.connect(self._set)
        self._anim.start()

    def _set(self, v):
        self._v = float(v)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#EFE5DF"))
        p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
        if self._v > 0.0:
            p.setBrush(with_alpha(self.color, 200))
            p.drawRoundedRect(QRectF(0, 0, max(h, w * self._v), h), h / 2, h / 2)
        p.end()


class ConfettiLayer(QWidget):
    """One-shot confetti burst from the success badge."""
    COLORS = (BANNER_2, BANNER_1, SECONDARY, SUCCESS, GOLD, "#7C5CFF")

    def __init__(self, host, origin_widget, delay_ms=650, count=72):
        super().__init__(host)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._origin = origin_widget
        self._count = count
        self._parts = []
        self._last = 0.0
        self._t_start = 0.0
        self.hide()
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._step)
        self._delay = QTimer(self)
        self._delay.setSingleShot(True)
        self._delay.timeout.connect(self.burst)
        self._delay.start(int(delay_ms))

    def burst(self):
        host = self.parentWidget()
        if host is None or sip.isdeleted(self._origin):
            return
        self.setGeometry(host.rect())
        self.raise_()
        self.show()
        o = self._origin.mapTo(host, self._origin.rect().center())
        for _ in range(self._count):
            ang = math.radians(random.uniform(-160.0, -20.0))
            sp = random.uniform(320.0, 720.0)
            self._parts.append({
                "x": float(o.x()), "y": float(o.y()),
                "vx": math.cos(ang) * sp, "vy": math.sin(ang) * sp,
                "rot": random.uniform(0, 360), "vr": random.uniform(-420, 420),
                "size": random.uniform(6, 11), "color": QColor(random.choice(self.COLORS)),
                "life": random.uniform(1.9, 2.7),
            })
        self._last = self._t_start = clock()
        self._timer.start()

    def _step(self):
        now = clock()
        dt = min(0.05, now - self._last)
        self._last = now
        alive = False
        for q in self._parts:
            q["vy"] += 980.0 * dt
            q["vx"] *= max(0.0, 1.0 - 1.3 * dt)
            q["x"] += q["vx"] * dt
            q["y"] += q["vy"] * dt
            q["rot"] += q["vr"] * dt
            if (now - self._t_start) < q["life"] and q["y"] < self.height() + 30:
                alive = True
        self.update()
        if not alive:
            self._timer.stop()
            self.hide()

    def paintEvent(self, _event):
        if not self._parts:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        age = clock() - self._t_start
        p.setPen(Qt.PenStyle.NoPen)
        for q in self._parts:
            a = clamp01((q["life"] - age) / 0.6)
            if a <= 0.0:
                continue
            p.save()
            p.translate(q["x"], q["y"])
            p.rotate(q["rot"])
            p.setBrush(with_alpha(q["color"], 255 * a))
            s = q["size"]
            p.drawRoundedRect(QRectF(-s / 2, -s / 3, s, s * 0.62), 1.5, 1.5)
            p.restore()
        p.end()


class BookScanVisual(QWidget):
    """Viewfinder brackets + floating book + sweeping scan line for the borrow / return screens."""
    def __init__(self, accent=BANNER_2, parent=None):
        super().__init__(parent)
        self.setMinimumSize(300, 190)
        self.accent = QColor(accent)
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self.update)
        self._timer.start()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        cx, cy = w / 2, h / 2
        t = clock()
        bw, bh = 176.0, 124.0
        rect = QRectF(cx - bw / 2, cy - bh / 2, bw, bh)

        # corner brackets
        p.setPen(round_pen(with_alpha(self.accent, 190), 5))
        L = 26.0
        for x, y, dx, dy in ((rect.left(), rect.top(), 1, 1), (rect.right(), rect.top(), -1, 1),
                             (rect.left(), rect.bottom(), 1, -1), (rect.right(), rect.bottom(), -1, -1)):
            p.drawLine(QPointF(x, y), QPointF(x + dx * L, y))
            p.drawLine(QPointF(x, y), QPointF(x, y + dy * L))

        # floating book with RFID tag
        bob = 6.0 * math.sin(t * 2.2)
        p.save()
        p.translate(cx, cy + bob)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.accent)
        p.drawRoundedRect(QRectF(-31, -42, 62, 84), 7, 7)
        p.setBrush(mix(self.accent, "#000000", 0.18))
        p.drawRoundedRect(QRectF(-31, -42, 9, 84), 4, 4)
        p.setBrush(QColor(255, 255, 255, 235))
        p.drawRoundedRect(QRectF(-10, -28, 32, 8), 3, 3)
        p.drawRoundedRect(QRectF(-10, -14, 22, 6), 3, 3)
        p.setBrush(QColor(255, 255, 255, 60))
        p.drawRoundedRect(QRectF(-8, 16, 28, 18), 4, 4)
        p.setPen(round_pen(QColor(255, 255, 255, 230), 2.4))
        p.drawArc(QRectF(-2, 20, 12, 12), int(-40 * 16), int(80 * 16))
        p.drawArc(QRectF(2, 17, 18, 18), int(-40 * 16), int(80 * 16))
        p.restore()

        # sweeping scan line
        if ENABLE_BOOK_SCAN_SWEEP and MOTION_ENABLED:
            k = (t * 0.55) % 1.0
            ping = ease_in_out(1.0 - abs(2.0 * k - 1.0))
            y = rect.top() + ping * bh
            g = QLinearGradient(0, y - 24, 0, y + 24)
            g.setColorAt(0.0, with_alpha(self.accent, 0))
            g.setColorAt(0.5, with_alpha(self.accent, 105))
            g.setColorAt(1.0, with_alpha(self.accent, 0))
            p.fillRect(QRectF(rect.left() + 6, y - 24, bw - 12, 48), QBrush(g))
            p.setPen(round_pen(with_alpha(self.accent, 235), 3))
            p.drawLine(QPointF(rect.left() + 6, y), QPointF(rect.right() - 6, y))
        p.end()


class ServicePromo(QFrame):
    """Small animated service illustration beside the home advertisement."""
    MODES = (
        ("ATTENDANCE", "TIME IN / TIME OUT", "#1BAA67"),
        ("BORROW", "TAKE A BOOK", "#245DAD"),
        ("RETURN", "SURRENDER A BOOK", "#3E82E8"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(220, 184)
        self.setStyleSheet("QFrame{background:transparent;border:none;}")
        self._index = 0
        self._swap_t0 = clock() - 5.0
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(33)
        self._tick_timer.timeout.connect(self.update)
        self._tick_timer.start()
        self._switch_timer = QTimer(self)
        self._switch_timer.setInterval(3300)
        self._switch_timer.timeout.connect(self._next)
        self._switch_timer.start()

    def _next(self):
        self._index = (self._index + 1) % len(self.MODES)
        self._swap_t0 = clock()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        mode, subtitle, accent = self.MODES[self._index]
        c = QColor(accent)
        dy = int(5 * math.sin(clock() * 0.79))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFF0E9"))
        p.drawRoundedRect(self.rect(), 22, 22)
        p.setBrush(QColor(255, 255, 255, 110))
        p.drawEllipse(20, 22, 90, 70)
        p.drawEllipse(128, 38, 65, 58)
        p.setBrush(QColor(c.red(), c.green(), c.blue(), 150))
        p.drawEllipse(182, 20 + dy, 10, 10)

        # the illustration slides up + fades in every time the mode changes
        k = ease_out_cubic((clock() - self._swap_t0) / 0.55)
        p.save()
        p.setOpacity(k)
        p.translate(0, (1.0 - k) * 18.0)

        if mode == "ATTENDANCE":
            p.setBrush(QColor("#FFFFFF"))
            p.setPen(QPen(QColor("#DCE5EF"), 1.2))
            p.drawRoundedRect(34, 42 + dy, 68, 86, 10, 10)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(34, 42 + dy, 68, 17, 10, 10)
            p.setBrush(QColor("#F8D9D2"))
            p.drawEllipse(52, 65 + dy, 32, 28)
            p.setBrush(QColor("#1F2A44"))
            p.drawRoundedRect(55, 96 + dy, 26, 4, 2, 2)
            p.drawRoundedRect(50, 104 + dy, 36, 4, 2, 2)
            p.drawRoundedRect(112, 58 - dy, 72, 58, 15, 15)
            p.setPen(QPen(Qt.GlobalColor.white, 4))
            p.drawLine(148, 76 - dy, 148, 90 - dy)
            p.drawLine(148, 90 - dy, 160, 90 - dy)
        elif mode == "BORROW":
            for i, col in enumerate((QColor("#3E82E8"), QColor("#1BAA67"), c)):
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(col)
                p.drawRoundedRect(38, 105 - i * 22, 92, 18, 7, 7)
            p.setBrush(QColor("#FFC39E"))
            p.drawRoundedRect(118, 58 + dy, 58, 18, 9, 9)
            p.drawEllipse(160, 44 + dy, 28, 28)
        else:
            p.setBrush(QColor("#C98955"))
            p.drawRoundedRect(34, 54 - dy, 135, 82, 10, 10)
            p.setPen(QPen(QColor("#8A5A37"), 4))
            p.drawLine(44, 74 - dy, 159, 74 - dy)
            p.drawLine(44, 112 - dy, 159, 112 - dy)
            p.setPen(Qt.PenStyle.NoPen)
            for x, col in ((50, "#245DAD"), (73, "#3E82E8"), (96, "#1BAA67"), (116, accent)):
                p.setBrush(QColor(col))
                p.drawRoundedRect(x, 79 - dy if x != 116 else 71 - dy, 18 if x != 116 else 33, 30 if x != 116 else 39, 4, 4)

        p.setPen(QColor("#8C2735"))
        f = p.font(); f.setBold(True); f.setPointSize(12); p.setFont(f)
        p.drawText(18, 153, 184, 20, Qt.AlignmentFlag.AlignCenter, mode)
        f.setPointSize(8); p.setFont(f); p.setPen(QColor("#9A756B"))
        p.drawText(18, 171, 184, 12, Qt.AlignmentFlag.AlignCenter, subtitle)
        p.restore()

        # mode indicator dots (active one stretches into a pill)
        p.setPen(Qt.PenStyle.NoPen)
        widths = [16 if i == self._index else 6 for i in range(len(self.MODES))]
        gap = 6
        x = (self.width() - (sum(widths) + gap * (len(widths) - 1))) / 2.0
        for i, wd in enumerate(widths):
            p.setBrush(QColor(accent) if i == self._index else QColor(200, 180, 172, 150))
            p.drawRoundedRect(QRectF(x, 9, wd, 6), 3, 3)
            x += wd + gap
        p.end()


class SimpleScanPanel(QFrame):
    """Static RFID reader area. No pulse/ripple animation - only smooth text/colour transitions."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("QFrame{background:#FFFFFF;border:none;border-radius:24px;}")
        self.setMinimumHeight(220)
        root = QHBoxLayout(self); root.setContentsMargins(26,22,26,22); root.setSpacing(24)
        self.reader = QLabel("RFID")
        self.reader.setFixedSize(112,112); self.reader.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.reader, alignment=Qt.AlignmentFlag.AlignVCenter)
        col = QVBoxLayout(); col.setSpacing(7)
        self.eyebrow = QLabel("STEP 1  •  IDENTIFY")
        self.title = QLabel("TAP YOUR SCHOOL ID"); self.title.setStyleSheet(f"color:{TEXT};font-size:28px;font-weight:950;")
        self.subtitle = QLabel("Place your RFID card on the reader to begin."); self.subtitle.setWordWrap(True); self.subtitle.setStyleSheet(f"color:{MUTED};font-size:13px;font-weight:700;")
        self.hint = QLabel("Your account will be identified automatically."); self.hint.setStyleSheet(f"color:{TEXT};font-size:11px;font-weight:750;")
        steps = QHBoxLayout(); steps.setSpacing(10)
        for n, label, color in (("01","TAP ID",BANNER_2),("02","SELECT",SECONDARY),("03","SCAN BOOK",SUCCESS)):
            chip = QFrame(); chip.setStyleSheet("QFrame{background:#EDF3FB;border:none;border-radius:10px;}")
            cl=QHBoxLayout(chip); cl.setContentsMargins(10,7,10,7)
            a=QLabel(n); a.setStyleSheet(f"color:{color};font-size:8px;font-weight:950;")
            b=QLabel(label); b.setStyleSheet(f"color:{TEXT};font-size:8px;font-weight:900;")
            cl.addWidget(a); cl.addWidget(b); steps.addWidget(chip,1)
        col.addWidget(self.eyebrow); col.addWidget(self.title); col.addWidget(self.subtitle); col.addWidget(self.hint); col.addSpacing(5); col.addLayout(steps)
        root.addLayout(col,1)
        self.set_accent(BANNER_2)

    def set_accent(self, color):
        light = mix(color, "#FFFFFF", 0.22).name()
        self.reader.setStyleSheet(f"QLabel{{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {color},stop:1 {light});color:white;border-radius:56px;font-size:16px;font-weight:950;}}")
        self.eyebrow.setStyleSheet(f"color:{color};font-size:10px;font-weight:950;letter-spacing:1.7px;")

    def set_message(self, title, subtitle, hint=None, eyebrow=None, accent=None):
        self.title.setText(title); self.subtitle.setText(subtitle)
        if hint is not None: self.hint.setText(hint)
        if eyebrow is not None: self.eyebrow.setText(eyebrow)
        if accent is not None: self.set_accent(accent)
        fade_in(self.title, 260)
        fade_in(self.subtitle, 320)


class VirtualKeyboard(QFrame):
    """
    Large touch keyboard (12 key-widths wide, 5 rows):
        1 2 3 4 5 6 7 8 9 0   [ DELETE ]
        Q W E R T Y U I O P   -  '
        A S D F G H J K L     .  [ DONE ]
        [SHIFT] Z X C V B N M ,  [ CLEAR ]
        [            SPACE            ]
    Letters follow the shift state and auto-capitalise at the start of every word.
    """
    COLS = 24          # every normal key spans 2 columns so half-key offsets are possible
    KEY_H = 62
    visibilityChanged = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.target: Optional[QLineEdit] = None
        self.shift = False
        self._letters = {}
        self._shift_btn = None
        self.setStyleSheet("QFrame{background:#1D2533;border:none;border-radius:24px;}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 20)
        outer.setSpacing(10)
        head = QHBoxLayout()
        lbl = QLabel("ON-SCREEN KEYBOARD")
        lbl.setStyleSheet("color:rgba(255,255,255,205);font-size:12px;font-weight:950;letter-spacing:1.2px;background:transparent;")
        hide_btn = QPushButton("HIDE  ▾")
        hide_btn.setFixedSize(120, 42)
        hide_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        hide_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        hide_btn.setStyleSheet("QPushButton{background:#2C3647;color:white;border:none;border-radius:12px;font-size:12px;font-weight:950;} QPushButton:pressed{background:#4B5870;}")
        hide_btn.clicked.connect(self.hide)
        head.addWidget(lbl)
        head.addStretch()
        head.addWidget(hide_btn)
        outer.addLayout(head)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(8)
        for c in range(self.COLS):
            self.grid.setColumnStretch(c, 1)
        outer.addLayout(self.grid)
        self._build()

    # ---- layout --------------------------------------------------------
    def _build(self):
        col = 0
        for k in "1234567890":
            self._add(k, 0, col, 2)
            col += 2
        self._add("BACKSPACE", 0, 20, 4)

        col = 0
        for k in "QWERTYUIOP":
            self._add(k, 1, col, 2)
            col += 2
        self._add("-", 1, 20, 2)
        self._add("'", 1, 22, 2)

        col = 0
        for k in "ASDFGHJKL":
            self._add(k, 2, col, 2)
            col += 2
        self._add(".", 2, 18, 2)
        self._add("DONE", 2, 20, 4)

        self._add("SHIFT", 3, 0, 4)
        col = 4
        for k in "ZXCVBNM":
            self._add(k, 3, col, 2)
            col += 2
        self._add(",", 3, 18, 2)
        self._add("CLEAR", 3, 20, 4)

        self._add("SPACE", 4, 0, self.COLS)

    @staticmethod
    def _style(bg, fg, size, pressed="#4B5870"):
        return (f"QPushButton{{background:{bg};color:{fg};border:none;border-radius:14px;"
                f"font-size:{size}px;font-weight:900;}} QPushButton:pressed{{background:{pressed};}}")

    def _add(self, key, row, col, span):
        labels = {"BACKSPACE": "⌫  DELETE", "SPACE": "SPACE", "SHIFT": "⇧  SHIFT", "CLEAR": "CLEAR", "DONE": "DONE  ✓"}
        b = QPushButton(labels.get(key, key))
        b.setFixedHeight(self.KEY_H)
        b.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)   # equal key widths
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)                                # never steal focus from the field
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        if key == "DONE":
            b.setStyleSheet(self._style("#245DAD", "white", 16, "#C82E48"))
        elif key == "SHIFT":
            self._shift_btn = b
            b.setStyleSheet(self._style("#485467", "white", 15))
        elif key in ("BACKSPACE", "CLEAR"):
            b.setStyleSheet(self._style("#4A3038", "#FFD7D7", 15, "#6B404C"))
        elif key == "SPACE":
            b.setStyleSheet(self._style("#36425A", "#DCE3F0", 15))
        elif key.isdigit():
            b.setStyleSheet(self._style("#263148", "white", 24))
        elif key.isalpha():
            self._letters[key] = b
            b.setStyleSheet(self._style("#2C3647", "white", 24))
        else:
            b.setStyleSheet(self._style("#36425A", "white", 24))
        b.clicked.connect(lambda _=False, k=key: self._key(k))
        self.grid.addWidget(b, row, col, 1, span)

    # ---- behaviour -----------------------------------------------------
    def set_target(self, target):
        self.target = target
        self._refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh()
        self.visibilityChanged.emit(True)

    def hideEvent(self, event):
        super().hideEvent(event)
        self.visibilityChanged.emit(False)

    def _auto_cap(self) -> bool:
        if self.target is None:
            return False
        before = self.target.text()[:self.target.cursorPosition()]
        return (not before) or before[-1] in " -'"

    def _upper(self) -> bool:
        return self.shift or self._auto_cap()

    def _refresh(self):
        up = self._upper()
        for k, b in self._letters.items():
            b.setText(k.upper() if up else k.lower())
        if self._shift_btn is not None:
            if self.shift:
                self._shift_btn.setStyleSheet(self._style("#245DAD", "white", 15, "#C82E48"))
            else:
                self._shift_btn.setStyleSheet(self._style("#485467", "white", 15))

    def _key(self, key):
        if self.target is None:
            return
        self.target.setFocus()
        if key == "DONE":
            self.hide()
            return
        if key == "SHIFT":
            self.shift = not self.shift
        elif key == "BACKSPACE":
            self.target.backspace()
        elif key == "CLEAR":
            self.target.clear()
        elif key == "SPACE":
            self.target.insert(" ")
        else:
            ch = key
            if key.isalpha():
                ch = key.upper() if self._upper() else key.lower()
            self.target.insert(ch)
            self.shift = False
        self._refresh()


class KioskSetup(QDialog):
    def __init__(self):
        super().__init__(); self.setWindowTitle("SMPCS Library Kiosk - First Time Setup"); self.setMinimumSize(650,560)
        self.setStyleSheet(f"QDialog{{background:{BACKGROUND};}} QLabel{{color:{TEXT};}} QLineEdit{{background:{WHITE};color:{TEXT};border:1px solid {BORDER};border-radius:12px;padding:13px;font-size:15px;}}")
        layout=QVBoxLayout(self); layout.setContentsMargins(35,35,35,35); layout.setSpacing(15)
        title=QLabel("Library Kiosk Setup"); title.setStyleSheet(f"font-size:28px;font-weight:950;color:{TEXT};")
        sub=QLabel("Connect this computer to the SMPCS Library system."); sub.setStyleSheet(f"color:{MUTED};font-size:14px;")
        layout.addWidget(title); layout.addWidget(sub)
        self.url=QLineEdit(); self.key=QLineEdit(); self.code=QLineEdit(); self.name=QLineEdit(); self.token=QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password); self.token.setEchoMode(QLineEdit.EchoMode.Password)
        cfg=load_config(); self.url.setText(cfg.get("SUPABASE_URL","")); self.key.setText(cfg.get("SUPABASE_ANON_KEY","")); self.code.setText(cfg.get("STATION_CODE","")); self.name.setText(cfg.get("STATION_NAME","Library Kiosk")); self.token.setText(cfg.get("STATION_TOKEN",""))
        form=QFormLayout(); form.setVerticalSpacing(14)
        for label, widget in (("Supabase URL",self.url),("Anon / Publishable Key",self.key),("Station Code",self.code),("Station Name",self.name),("Station Token",self.token)): form.addRow(label,widget)
        layout.addLayout(form); layout.addStretch()
        btn=QPushButton("SAVE & VERIFY CONNECTION"); btn.setMinimumHeight(55); btn.setStyleSheet(f"QPushButton{{background:{ACCENT};color:white;border:none;border-radius:14px;font-size:15px;font-weight:800;}} QPushButton:hover{{background:{ACCENT_DARK};}}")
        btn.clicked.connect(self.verify); layout.addWidget(btn)

    def verify(self):
        try:
            url=self.url.text().strip(); key=self.key.text().strip(); code=self.code.text().strip().upper(); name=self.name.text().strip() or "Library Kiosk"; token=self.token.text().strip()
            if not url or not key or not code or not token: raise ApiError("Supabase URL, key, station code, and station token are required.")
            api=SupabaseAPI(url,key); result=api.rpc("library_kiosk_auth",{"p_station_code":code,"p_token":token})
            if isinstance(result,list) and not result: raise ApiError("Station verification returned no result.")
            cfg=load_config(); cfg.update({"SUPABASE_URL":url,"SUPABASE_ANON_KEY":key,"STATION_CODE":code,"STATION_NAME":name,"STATION_TOKEN":token}); save_config(cfg); self.accept()
        except Exception as exc: kiosk_msg(self,"Kiosk Setup Failed",str(exc),"error")


# ============================================================
# MAIN KIOSK WINDOW
# ============================================================

class Kiosk(QMainWindow):
    def __init__(self,api,cfg):
        super().__init__(); self.api=api; self.cfg=cfg; self.member=None; self.mode="member"; self.online=False; self.manual=None; self.pending_action=None
        self.scan_panel=None; self.busy=False; self._syncing=False; self._verifying_station=False; self._api_lock=threading.Lock(); self._result_shown_at=0.0
        self._reset_timer=QTimer(self); self._reset_timer.setSingleShot(True); self._reset_timer.timeout.connect(self.reset)
        self.setWindowTitle("SMPCS Library Kiosk"); self.showFullScreen()
        self.setStyleSheet(f"QMainWindow{{background:{BACKGROUND};}} QWidget{{font-family:'Segoe UI';color:{TEXT};}} QLabel{{background:transparent;}}")
        self.root=QWidget(); self.root.setObjectName("kioskRoot"); self.root.setStyleSheet(f"background:{BACKGROUND};border:none;"); self.root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True); self.root.setAutoFillBackground(True); self.setCentralWidget(self.root)
        self.main_layout=QVBoxLayout(self.root); self.main_layout.setContentsMargins(0,0,0,0); self.main_layout.setSpacing(0)
        self.build_banner()
        body=QWidget(); body.setObjectName("kioskBody"); body.setStyleSheet(f"background:{BACKGROUND};border:none;"); body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True)
        self.body_layout=QVBoxLayout(body); self.body_layout.setContentsMargins(24,16,24,16); self.body_layout.setSpacing(12); self.main_layout.addWidget(body,1)
        self.content_container=QWidget(); self.content_container.setObjectName("kioskContent"); self.content_container.setStyleSheet(f"background:{BACKGROUND};border:none;"); self.content_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True)
        self.content_layout=QVBoxLayout(self.content_container); self.content_layout.setContentsMargins(0,0,0,0); self.body_layout.addWidget(self.content_container,1)
        self.build_status_bar()
        from shared.services import Outbox
        self.outbox=Outbox()
        self.clock_timer=QTimer(self); self.clock_timer.timeout.connect(self.update_clock); self.clock_timer.start(1000); self.update_clock()
        self.heartbeat=QTimer(self); self.heartbeat.timeout.connect(self.heartbeat_fn); self.heartbeat.start(30000)
        self.rfid=RFIDCapture(self); self.rfid.tag.connect(self.handle_rfid)
        self.show_home(); QTimer.singleShot(300,self.verify_station)
        from shared.kiosk_suite import KioskStatus
        self.suite_status=KioskStatus(self)

    # ========================================================
    # BACKGROUND API CALLS (keeps every animation smooth)
    # ========================================================
    def run_async(self, fn, on_ok, on_err):
        def locked():
            with self._api_lock:
                return fn()
        task=ApiTask(locked,self); task.on_ok=on_ok; task.on_err=on_err
        task.done.connect(self._task_done); task.finished.connect(task.deleteLater); task.start()

    def _task_done(self, task):
        try:
            if task.error is not None: task.on_err(task.error)
            else: task.on_ok(task.result)
        except Exception as exc:
            try: self.busy=False; self.show_error("ERROR",str(exc))
            except Exception: pass

    def show_processing(self,title,subtitle,steps,accent=BANNER_2,icon="book",chip=None,min_ms=1700,step_ms=760):
        self.clear_content()
        screen=ProcessingScreen(title,subtitle,steps,accent=accent,icon=icon,chip=chip,min_ms=min_ms,step_ms=step_ms)
        self.content_layout.addWidget(screen,1); fade_in(screen,240)
        self.status.setText("PROCESSING • Please wait…")
        return screen

    def run_with_processing(self,title,subtitle,steps,fn,on_ok,on_err,accent=BANNER_2,icon="book",chip=None,min_ms=1700,step_ms=760):
        self.busy=True
        screen=self.show_processing(title,subtitle,steps,accent,icon,chip,min_ms,step_ms)
        def ok(result):
            if sip.isdeleted(screen): self.busy=False; return
            screen.finish(True,lambda:self._processing_done(on_ok,result))
        def err(exc):
            if sip.isdeleted(screen): self.busy=False; return
            screen.finish(False,lambda:self._processing_done(on_err,exc),"COULD NOT COMPLETE")
        self.run_async(fn,ok,err)

    def _processing_done(self,callback,arg):
        self.busy=False; callback(arg)

    # ========================================================
    # LAYOUT PIECES
    # ========================================================
    def build_banner(self):
        banner=BannerFrame(); banner.setFixedHeight(BANNER_HEIGHT)
        lay=QHBoxLayout(banner); lay.setContentsMargins(30,12,30,12); lay.setSpacing(22)
        clear="background:transparent;border:none;"
        lay.addWidget(LogoBadge(LOGO_SIZE),alignment=Qt.AlignmentFlag.AlignVCenter)
        brand=QVBoxLayout(); brand.setSpacing(4); brand.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        school=QLabel("ST. MARTIN DE PORRES CATHOLIC SCHOOL, INC."); school.setStyleSheet(f"{clear}color:white;font-size:24px;font-weight:800;")
        lib=QLabel("LIBRARY KIOSK   •   SELF SERVICE"); lib.setStyleSheet(f"{clear}color:rgba(255,255,255,235);font-size:15px;font-weight:800;letter-spacing:2px;")
        brand.addWidget(school); brand.addWidget(lib); lay.addLayout(brand,1)
        clock_col=QVBoxLayout(); clock_col.setSpacing(2); clock_col.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
        self.clock=QLabel(); self.clock.setAlignment(Qt.AlignmentFlag.AlignRight); self.clock.setStyleSheet(f"{clear}color:white;font-size:34px;font-weight:800;")
        self.date_label=QLabel(); self.date_label.setAlignment(Qt.AlignmentFlag.AlignRight); self.date_label.setStyleSheet(f"{clear}color:rgba(255,255,255,235);font-size:15px;font-weight:700;")
        clock_col.addWidget(self.clock); clock_col.addWidget(self.date_label); lay.addLayout(clock_col)
        self.main_layout.addWidget(banner)

    def build_status_bar(self):
        bar=QFrame(); bar.setObjectName("statusBar"); bar.setFixedHeight(42); bar.setStyleSheet("QFrame#statusBar{background:#E8EFF7;border-top:1px solid #CED9E7;} QFrame#statusBar QLabel{background:transparent;border:none;}"); lay=QHBoxLayout(bar); lay.setContentsMargins(20,5,20,5)
        self.status_dot=QLabel("●"); self.status=QLabel("CONNECTING..."); self.station=QLabel(f"Station: {self.cfg.get('STATION_NAME','Library Kiosk')}"); ready=QLabel("RFID  •  TOUCHSCREEN READY")
        self.status_dot.setStyleSheet(f"color:{MUTED};font-size:12px;"); self.status.setStyleSheet(f"color:{TEXT};font-size:11px;font-weight:800;"); self.station.setStyleSheet(f"color:{MUTED};font-size:10px;font-weight:700;"); ready.setStyleSheet(f"color:{MUTED};font-size:10px;font-weight:800;")
        # the status dot gently "breathes" while the station is online
        self._dot_fx=QGraphicsOpacityEffect(self.status_dot); self.status_dot.setGraphicsEffect(self._dot_fx)
        self._dot_anim=QPropertyAnimation(self._dot_fx,b"opacity",self); self._dot_anim.setDuration(1800); self._dot_anim.setStartValue(1.0); self._dot_anim.setKeyValueAt(0.5,0.3); self._dot_anim.setEndValue(1.0); self._dot_anim.setLoopCount(-1); self._dot_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        lay.addWidget(self.status_dot); lay.addWidget(self.status); lay.addSpacing(10); lay.addWidget(self.station); lay.addStretch(); lay.addWidget(ready); self.main_layout.addWidget(bar)
        self.settings_button=QPushButton("Settings")
        self.settings_button.setStyleSheet("QPushButton{background:#192B45;color:white;border-radius:8px;padding:5px 16px;font-weight:700;}")
        self.settings_button.clicked.connect(self.open_settings); lay.addWidget(self.settings_button)

    def open_settings(self):
        # Do not reset an in-progress circulation transaction.
        if self.busy or self.member is not None or self.mode != "member" or self._verifying_station:
            kiosk_msg(self,"Settings","Finish the current transaction or wait for verification, then open Settings.","info")
            return
        from admin.main import AdminLogin
        from shared.updates import VERSION
        self.busy=True; self._settings_open=True
        self.rfid.timer.stop(); self.rfid.buffer=""
        QApplication.instance().removeEventFilter(self.rfid)
        try:
            login=AdminLogin(self.api,self)
            if login.exec()!=QDialog.DialogCode.Accepted: return
            dialog=QDialog(self); dialog.setWindowTitle("Kiosk Settings")
            dialog.setMinimumWidth(500)
            dialog.setStyleSheet("QDialog{background:#F4F7FB;} QLabel,QCheckBox{color:#192B45;font-size:14px;} QPushButton{background:#192B45;color:white;border-radius:10px;padding:13px;font-weight:700;}")
            layout=QVBoxLayout(dialog); layout.setContentsMargins(26,26,26,26); layout.setSpacing(15)
            layout.addWidget(QLabel(f"SMPCS Library • Version {VERSION}"))
            layout.addWidget(QLabel("Station: "+self.cfg.get("STATION_NAME","Library Kiosk")))
            from shared.account_ui import outbox_dialog
            queue_button=QPushButton("Attendance sync queue"); queue_button.clicked.connect(lambda:outbox_dialog(self)); layout.addWidget(queue_button)
            fullscreen=QCheckBox("Full-screen kiosk"); fullscreen.setChecked(self.isFullScreen()); layout.addWidget(fullscreen)
            motion=QCheckBox("Enable animations"); motion.setChecked(MOTION_ENABLED); layout.addWidget(motion)
            def updates():
                self.update_controller.show_settings()
                self.update_controller.dialog.exec()
            update_btn=QPushButton("GitHub updates / Check now"); update_btn.clicked.connect(updates); layout.addWidget(update_btn)
            def connection():
                setup=KioskSetup(); setup.setParent(dialog,Qt.WindowType.Dialog)
                if setup.exec()==QDialog.DialogCode.Accepted:
                    self.cfg=load_config(); self.api=SupabaseAPI(self.cfg["SUPABASE_URL"],self.cfg["SUPABASE_ANON_KEY"])
                    self.station.setText("Station: "+self.cfg.get("STATION_NAME","Library Kiosk"))
                    dialog.accept()
            connection_btn=QPushButton("Connection and station setup"); connection_btn.clicked.connect(connection); layout.addWidget(connection_btn)
            def save_display():
                global MOTION_ENABLED
                cfg=load_config(); cfg.update(KIOSK_FULLSCREEN=fullscreen.isChecked(),KIOSK_ANIMATIONS=motion.isChecked()); save_config(cfg)
                self.cfg=cfg; MOTION_ENABLED=motion.isChecked()
                self.showFullScreen() if fullscreen.isChecked() else self.showMaximized()
                self.set_online(self.online,self.status.text())
                dialog.accept()
            save=QPushButton("Save display settings"); save.clicked.connect(save_display); layout.addWidget(save)
            close=QPushButton("Back to kiosk"); close.clicked.connect(dialog.reject); layout.addWidget(close)
            dialog.exec()
        finally:
            self.rfid.buffer=""; self.rfid.timer.stop()
            QApplication.instance().installEventFilter(self.rfid)
            self.busy=False; self._settings_open=False
            if not getattr(self,"_update_requested",False): self.reset(); self.verify_station()

    def update_clock(self):
        now=datetime.now(); self.clock.setText(now.strftime("%I:%M:%S %p")); self.date_label.setText(now.strftime("%A, %B %d, %Y"))

    def clear_content(self):
        self._reset_timer.stop(); self.scan_panel=None; self.manual=None
        while self.content_layout.count():
            item=self.content_layout.takeAt(0); w=item.widget()
            if w is not None: w.setParent(None); w.deleteLater(); continue
            child=item.layout()
            if child:
                while child.count():
                    c=child.takeAt(0)
                    if c.widget(): c.widget().setParent(None); c.widget().deleteLater()

    # ========================================================
    # HOME
    # ========================================================
    def show_home(self):
        self.member=None; self.mode="member"; self.manual=None; self.pending_action=None; self.clear_content()
        page=QFrame(); page.setStyleSheet(f"QFrame{{background:{BACKGROUND};border:none;}}")
        outer=QVBoxLayout(page); outer.setContentsMargins(0,0,0,0); outer.setSpacing(12)
        nav=QFrame(); nav.setFixedHeight(48); nav.setStyleSheet(f"QFrame{{background:{WHITE};border:none;border-radius:16px;}}"); nl=QHBoxLayout(nav); nl.setContentsMargins(14,7,14,7); nl.setSpacing(9)
        chip=QLabel("LIBRARY"); chip.setAlignment(Qt.AlignmentFlag.AlignCenter); chip.setFixedSize(82,32); chip.setStyleSheet(f"QLabel{{background:{BANNER_2};color:white;border-radius:9px;font-size:8px;font-weight:950;letter-spacing:1px;}}")
        title=QLabel("LIBRARY SELF-SERVICE"); title.setStyleSheet(f"color:{TEXT};font-size:15px;font-weight:950;"); sub=QLabel("Borrow  •  Return  •  Attendance"); sub.setStyleSheet(f"color:{MUTED};font-size:9px;font-weight:700;")
        ready=QLabel("● READY"); ready.setAlignment(Qt.AlignmentFlag.AlignCenter); ready.setFixedSize(84,30); ready.setStyleSheet(f"QLabel{{background:{SUCCESS_BG};color:{SUCCESS};border:none;border-radius:10px;font-size:8px;font-weight:950;}}")
        nl.addWidget(chip); nl.addWidget(title); nl.addWidget(sub); nl.addStretch(); nl.addWidget(ready); outer.addWidget(nav)
        cols=QHBoxLayout(); cols.setSpacing(12); left=QVBoxLayout(); left.setSpacing(12)
        hero=QFrame(); hero.setMinimumHeight(228); hero.setStyleSheet(f"QFrame{{background:{WHITE};border:none;border-radius:22px;}}"); hl=QHBoxLayout(hero); hl.setContentsMargins(24,22,22,20); hl.setSpacing(16)
        copy=QVBoxLayout(); copy.setSpacing(7); ey=QLabel("WELCOME TO THE LIBRARY"); ey.setStyleSheet(f"color:{BANNER_2};font-size:10px;font-weight:950;letter-spacing:1.5px;"); ht=QLabel("READ. DISCOVER.\nGROW."); ht.setStyleSheet(f"color:{TEXT};font-size:37px;font-weight:950;"); desc=QLabel("A simple, fast self-service station for your school library."); desc.setWordWrap(True); desc.setStyleSheet(f"color:{MUTED};font-size:13px;font-weight:650;")
        copy.addWidget(ey); copy.addWidget(ht); copy.addWidget(desc); copy.addStretch(); pills=QHBoxLayout(); pills.setSpacing(8)
        for t,bg,fc in (("RFID","#EAF2FF",BANNER_2),("FAST","#EEF4FF",SECONDARY),("EASY","#ECF9F2",SUCCESS)):
            x=QLabel(t); x.setAlignment(Qt.AlignmentFlag.AlignCenter); x.setFixedSize(58,28); x.setStyleSheet(f"QLabel{{background:{bg};color:{fc};border:none;border-radius:9px;font-size:8px;font-weight:950;}}"); pills.addWidget(x)
        pills.addStretch(); copy.addLayout(pills); hl.addLayout(copy,1); hl.addWidget(ServicePromo()); left.addWidget(hero)
        self.scan_panel=SimpleScanPanel(); left.addWidget(self.scan_panel)
        steps=QHBoxLayout(); steps.setSpacing(14)
        for n,t,b,c in (("01","TAP ID","Identify your account",BANNER_2),("02","SELECT","Choose a service",SECONDARY),("03","SCAN BOOK","Finish your transaction",SUCCESS)):
            col=QVBoxLayout(); num=QLabel(n); num.setStyleSheet(f"color:{c};font-size:9px;font-weight:950;"); ttl=QLabel(t); ttl.setStyleSheet(f"color:{TEXT};font-size:10px;font-weight:950;"); sb=QLabel(b); sb.setStyleSheet(f"color:{MUTED};font-size:9px;font-weight:650;"); col.addWidget(num); col.addWidget(ttl); col.addWidget(sb); steps.addLayout(col,1)
        left.addLayout(steps); cols.addLayout(left,7)
        right=QVBoxLayout(); right.setSpacing(11)
        status=QFrame(); status.setFixedHeight(110); status.setStyleSheet(f"QFrame{{background:{WHITE};border:none;border-radius:18px;}}"); sl=QVBoxLayout(status); sl.setContentsMargins(16,13,16,12)
        a=QLabel("LIBRARY STATUS"); a.setStyleSheet(f"color:{MUTED};font-size:9px;font-weight:950;letter-spacing:1.1px;"); b=QLabel("READY"); b.setStyleSheet(f"color:{BANNER_2};font-size:26px;font-weight:950;"); c=QLabel("Kiosk service is available"); c.setStyleSheet(f"color:{TEXT};font-size:10px;font-weight:750;"); line=QFrame(); line.setFixedHeight(4); line.setStyleSheet(f"background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {BANNER_2},stop:.6 {BANNER_1},stop:1 #7FB9F1);border:none;border-radius:2px;"); sl.addWidget(a); sl.addWidget(b); sl.addWidget(c); sl.addSpacing(5); sl.addWidget(line); right.addWidget(status)
        account_btn=QPushButton("MY ACCOUNT  •  RFID + PIN"); account_btn.setMinimumHeight(42); account_btn.clicked.connect(lambda:self.find_member_from_home("account")); left.addWidget(account_btn)
        btn_borrow=self.home_action_button("BORROW A BOOK","Scan your ID  •  scan the book",BANNER_2,self.borrow_from_home,"📖")
        btn_return=self.home_action_button("RETURN A BOOK","Scan your ID  •  scan the book",SECONDARY,self.return_from_home,"↩")
        btn_attend=self.home_action_button("ATTENDANCE","Time in  •  time out",SUCCESS,self.attendance_from_home,"✓")
        btn_print=self.home_action_button("PRINT A FILE","Scan your ID  •  choose a file",GOLD,self.print_from_home,"🖨")
        right.addWidget(btn_borrow); right.addWidget(btn_return); right.addWidget(btn_attend); right.addWidget(btn_print)
        reminder=QFrame(); reminder.setStyleSheet("QFrame{background:#FFF5DD;border:none;border-radius:15px;}"); rl=QVBoxLayout(reminder); rl.setContentsMargins(14,11,14,11); r1=QLabel("QUICK REMINDER"); r1.setStyleSheet("color:#B56A13;font-size:8px;font-weight:950;letter-spacing:1px;"); r2=QLabel("Return books on or before the date you select."); r2.setWordWrap(True); r2.setStyleSheet(f"color:{TEXT};font-size:10px;font-weight:750;"); rl.addWidget(r1); rl.addWidget(r2); right.addWidget(reminder)
        reg=QPushButton("REGISTER HERE\nNew student / no library account"); reg.setMinimumHeight(78); reg.setCursor(Qt.CursorShape.PointingHandCursor); reg.setStyleSheet(f"QPushButton{{background:#DBEAFE;color:{TEXT};border:none;border-radius:16px;text-align:left;padding:13px 16px;font-size:12px;font-weight:950;}} QPushButton:hover{{background:#C5DEFF;}}"); reg.clicked.connect(self.show_registration); right.addWidget(reg); right.addStretch(); cols.addLayout(right,3)
        outer.addLayout(cols,1); foot=QLabel("Touch a service, or simply tap your school ID on the RFID reader."); foot.setAlignment(Qt.AlignmentFlag.AlignCenter); foot.setStyleSheet(f"color:{MUTED};font-size:10px;font-weight:700;"); outer.addWidget(foot); self.content_layout.addWidget(page,1)
        # cascade entrance: everything glides in, one card after another
        stagger_fade([nav,hero,self.scan_panel,status,btn_borrow,btn_return,btn_attend,btn_print,reminder,reg,foot],start=30,step=75,duration=380)
        QTimer.singleShot(80,lambda:self._add_home_motion(page))

    def _add_home_motion(self,page):
        if sip.isdeleted(page) or not page.isVisible(): return
        w=max(page.width(),900); h=max(page.height(),620); page._dots=[]
        for spec in (("#FFD0C6",12,(w-250,105),(w-250,145),1900),("#BFD8FF",9,(w-315,250),(w-315,210),2300),("#BFE8D2",8,(w-190,max(220,h-250)),(w-230,max(180,h-290)),2100),
                     ("#FFE2A8",10,(w-120,140),(w-160,110),2600),("#FFD0C6",7,(w-360,max(200,h-200)),(w-330,max(160,h-240)),2000),("#BFD8FF",11,(w-90,max(240,h-180)),(w-120,max(200,h-220)),2400)):
            d=FloatingDot(page,*spec); page._dots.append(d); d.lower()

    def home_action_button(self,title,subtitle,color,callback,icon="•"):
        btn=ShimmerButton(); btn.setCursor(Qt.CursorShape.PointingHandCursor); btn.setMinimumHeight(82); btn.setMaximumHeight(92); btn.setText(f"{icon}   {title}\n      {subtitle}"); btn.setStyleSheet(f"QPushButton{{background:{WHITE};color:{TEXT};border:none;border-left:7px solid {color};border-radius:16px;text-align:left;padding:10px 15px;font-size:12px;font-weight:900;}} QPushButton:hover{{background:#EAF2FF;}} QPushButton:pressed{{background:#DCEAFF;}}"); btn.clicked.connect(callback); return btn

    # ========================================================
    # REGISTRATION
    # ========================================================
    def show_registration(self):
        from shared.kiosk_suite import maintenance_block
        if maintenance_block(self):return
        self.member=None; self.mode="register"; self.pending_action=None; self.clear_content()
        page=QFrame(); page.setStyleSheet(f"QFrame{{background:{BACKGROUND};border:none;}}"); root=QVBoxLayout(page); root.setContentsMargins(0,0,0,0); root.setSpacing(12)
        hero=QFrame(); hero.setStyleSheet(f"QFrame{{background:{WHITE};border:none;border-radius:24px;}}"); hl=QHBoxLayout(hero); hl.setContentsMargins(24,20,24,20); hl.setSpacing(20)
        copy=QVBoxLayout(); ey=QLabel("LIBRARY MEMBERSHIP"); ey.setStyleSheet(f"color:{BANNER_2};font-size:10px;font-weight:950;letter-spacing:1.5px;"); title=QLabel("REGISTER HERE"); title.setStyleSheet(f"color:{TEXT};font-size:34px;font-weight:950;"); sub=QLabel("Fill in your details, tap your school RFID, then proceed to the librarian for verification."); sub.setWordWrap(True); sub.setStyleSheet(f"color:{MUTED};font-size:12px;font-weight:650;"); steps=QLabel("01 PERSONAL INFO    02 RFID    03 LIBRARIAN VERIFICATION"); steps.setStyleSheet(f"color:{BANNER_2};font-size:9px;font-weight:950;letter-spacing:.8px;"); copy.addWidget(ey); copy.addWidget(title); copy.addWidget(sub); copy.addSpacing(4); copy.addWidget(steps); hl.addLayout(copy,1); hl.addWidget(ServicePromo()); root.addWidget(hero)
        row=QHBoxLayout(); row.setSpacing(12); left=QFrame(); left.setStyleSheet(f"QFrame{{background:{WHITE};border:none;border-radius:20px;}}"); ll=QVBoxLayout(left); ll.setContentsMargins(20,18,20,18); ll.setSpacing(9); right=QFrame(); right.setStyleSheet(f"QFrame{{background:{WHITE};border:none;border-radius:20px;}}"); rr=QVBoxLayout(right); rr.setContentsMargins(20,18,20,18); rr.setSpacing(9)
        def field(parent,label,ph,read_only=False):
            lab=QLabel(label); lab.setStyleSheet(f"color:{TEXT};font-size:9px;font-weight:950;letter-spacing:.8px;"); box=QLineEdit(); box.setPlaceholderText(ph); box.setReadOnly(read_only); box.setMinimumHeight(52); box.setStyleSheet(f"QLineEdit{{background:#FFFFFF;color:{TEXT};border:none;border-bottom:3px solid #CDD9E7;border-radius:10px;padding:0 13px;font-size:13px;font-weight:750;}} QLineEdit:focus{{background:white;border-bottom:3px solid {BANNER_2};}} QLineEdit:read-only{{background:#EEF3FA;color:{BANNER_2};}}"); parent.addWidget(lab); parent.addWidget(box); return box
        lab1=QLabel("STUDENT INFORMATION"); lab1.setStyleSheet(f"color:{BANNER_2};font-size:10px;font-weight:950;letter-spacing:1.1px;"); ll.addWidget(lab1); self.reg_name=field(ll,"FULL NAME","Enter your complete name"); self.reg_student_id=field(ll,"STUDENT ID","Enter your student ID"); self.reg_grade=field(ll,"GRADE / LEVEL","e.g. Grade 10"); self.reg_section=field(ll,"SECTION","Enter your section")
        lab2=QLabel("REGISTRATION"); lab2.setStyleSheet(f"color:{BANNER_2};font-size:10px;font-weight:950;letter-spacing:1.1px;"); rr.addWidget(lab2); self.reg_rfid=field(rr,"SCHOOL RFID","Tap the button below to capture RFID",True); self.reg_note=field(rr,"NOTE FOR LIBRARIAN","Optional note"); self.reg_status=QLabel("WAITING FOR RFID"); self.reg_status.setAlignment(Qt.AlignmentFlag.AlignCenter); self.reg_status.setFixedHeight(34); self.reg_status.setStyleSheet(f"QLabel{{background:#EAF0F8;color:{MUTED};border-radius:10px;font-size:9px;font-weight:950;}}"); rr.addWidget(self.reg_status)
        row.addWidget(left,1); row.addWidget(right,1); root.addLayout(row)
        scan=QPushButton("TAP SCHOOL RFID TO REGISTER"); scan.setMinimumHeight(58); scan.setStyleSheet(f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {BANNER_2},stop:1 {BANNER_1});color:white;border:none;border-radius:14px;font-size:13px;font-weight:950;}}"); scan.clicked.connect(self._prepare_registration_rfid); root.addWidget(scan)
        note=QLabel("After completing this form, proceed to the librarian for verification and account activation."); note.setWordWrap(True); note.setStyleSheet("color:#A66D16;background:#FFF5DD;border-radius:12px;padding:10px;font-size:10px;font-weight:750;"); root.addWidget(note)
        actions=QHBoxLayout(); cancel=QPushButton("CANCEL / BACK TO START"); cancel.setMinimumHeight(52); cancel.setStyleSheet("QPushButton{background:#E3EBF6;color:#334C6C;border:none;border-radius:13px;font-weight:900;}"); cancel.clicked.connect(self.reset); cont=QPushButton("CONTINUE TO LIBRARIAN  →"); cont.setMinimumHeight(52); cont.setStyleSheet(f"QPushButton{{background:{SUCCESS};color:white;border:none;border-radius:13px;font-weight:900;}}"); cont.clicked.connect(self.submit_registration_request); actions.addWidget(cancel,1); actions.addWidget(cont,1); root.addLayout(actions)
        self.keyboard=VirtualKeyboard(page); self.keyboard.hide(); self.keyboard.visibilityChanged.connect(lambda visible,h=hero,n=note:self._kb_visibility(visible,h,n))
        for field_widget in (self.reg_name,self.reg_student_id,self.reg_grade,self.reg_section,self.reg_note):
            field_widget.focusInEvent=self._make_keyboard_focus(field_widget)
        self.content_layout.addWidget(page,1)
        stagger_fade([hero,left,right,scan,note,cancel,cont],start=0,step=80,duration=360)

    def _make_keyboard_focus(self,field_widget):
        original=field_widget.focusInEvent
        def handler(event):
            original(event); self.keyboard.set_target(field_widget); self._show_keyboard()
        return handler

    @staticmethod
    def _kb_visibility(visible,*widgets):
        # while the keyboard is up, hide the big header + note so the form stays visible above it
        for w in widgets:
            try: w.setVisible(not visible)
            except RuntimeError: pass

    def _place_keyboard(self):
        kb=getattr(self,"keyboard",None)
        if kb is None or sip.isdeleted(kb): return
        page=kb.parentWidget()
        if page is None: return
        kh=kb.sizeHint().height()
        kb.setGeometry(0,max(0,page.height()-kh),page.width(),kh); kb.raise_()

    def _show_keyboard(self):
        kb=getattr(self,"keyboard",None)
        if kb is None or sip.isdeleted(kb) or kb.isVisible(): return
        self._place_keyboard(); kb.show(); kb.raise_(); fade_in(kb,200)
        QTimer.singleShot(0,self._place_keyboard)   # re-place once the form has re-flowed

    def _prepare_registration_rfid(self):
        self.mode="register_rfid"; self.reg_status.setText("TAP YOUR SCHOOL RFID NOW"); self.reg_status.setStyleSheet(f"QLabel{{background:#EAF2FF;color:{BANNER_2};border-radius:10px;font-size:9px;font-weight:950;}}"); self.status.setText("REGISTERING • Tap your school RFID…"); fade_in(self.reg_status,260)

    def _handle_registration_rfid(self,uid):
        if not hasattr(self,'reg_rfid'): return
        self.reg_rfid.setText(str(uid).strip()); self.reg_status.setText("RFID CAPTURED  ✓"); self.reg_status.setStyleSheet(f"QLabel{{background:{SUCCESS_BG};color:{SUCCESS};border-radius:10px;font-size:9px;font-weight:950;}}"); self.mode="register"; self.status.setText("ONLINE • RFID captured for registration")
        fade_in(self.reg_status,300); fade_in(self.reg_rfid,300)

    def submit_registration_request(self):
        values={"full_name":self.reg_name.text().strip(),"student_id":self.reg_student_id.text().strip(),"grade_level":self.reg_grade.text().strip(),"section":self.reg_section.text().strip(),"rfid":self.reg_rfid.text().strip(),"note":self.reg_note.text().strip()}
        missing=[k for k,v in (("Full name",values['full_name']),("Student ID",values['student_id']),("Grade / Level",values['grade_level']),("Section",values['section']),("School RFID",values['rfid'])) if not v]
        if missing: kiosk_msg(self,"Registration Incomplete","Please complete: "+", ".join(missing)+".","warning"); return
        if self.busy: return
        self.run_with_processing(
            "PREPARING YOUR REGISTRATION","Getting your details ready",
            ["Checking your details","Matching your school RFID","Preparing your slip for the librarian"],
            fn=lambda: __import__("shared.suite",fromlist=["station_suite"]).station_suite(self,"register",values),
            on_ok=lambda v: self.show_result("REGISTRATION SUBMITTED",f"{values['full_name']}\nRequest: {v['id']}","AWAITING APPROVAL","The librarian received your request. Ask them to approve your account and assign a PIN.",BANNER_2,"!",20000),
            on_err=lambda exc: self.show_error("REGISTRATION FAILED",str(exc)),
            accent=BANNER_2,icon="doc",min_ms=1900,step_ms=650)

    def borrow_from_home(self): self.find_member_from_home("borrow")
    def return_from_home(self): self.find_member_from_home("return")
    def attendance_from_home(self): self.find_member_from_home("attendance")

    def print_from_home(self): self.find_member_from_home("print")

    def print_start(self):
        if self.busy or not self.member: return
        self.mode="print"; self.clear_content()
        member=self.member
        screen=PrintScreen(member=member, log_fn=self._log_print)
        screen.back.connect(lambda:(screen.stop(),self.show_member()))
        self.content_layout.addWidget(screen,1); fade_in(screen,240)
        self.status.setText(f"PRINT • {member.get('full_name','Member')}")

    def _log_print(self,entry,ok,error_text):
        # best-effort audit trail for the admin's Print Logs page — a failed
        # or missing library_log_print function must never interrupt printing
        if not ok or not self.member: return
        member=self.member
        payload={"p_member_id":member.get("id"),"p_file_name":entry.get("name"),
                 "p_file_type":PRINT_EXTENSIONS.get(entry.get("ext"),("File",))[0],
                 "p_file_size":entry.get("size"),"p_station":self.cfg.get("STATION_CODE")}
        self.run_async(lambda:self.api.rpc("library_log_print",payload), lambda _r:None, lambda _e:None)

    def find_member_from_home(self,action):
        from shared.kiosk_suite import maintenance_block
        if maintenance_block(self):return
        self.mode="member"; self.pending_action=action
        if self.scan_panel is not None:
            info={"borrow":("BORROW A BOOK",BANNER_2),"return":("RETURN A BOOK",SECONDARY),"attendance":("ATTENDANCE",SUCCESS),"print":("PRINT A FILE",GOLD),"account":("MY ACCOUNT",BANNER_2)}
            name,color=info[action]
            self.scan_panel.set_message("TAP YOUR SCHOOL ID",f"{name} selected. Tap your school ID on the reader to continue.","Your account will be identified automatically.",eyebrow=f"STEP 1  •  IDENTIFY  •  {name}",accent=color)

    # ========================================================
    # CONNECTION (runs in the background so animations never stall)
    # ========================================================
    def verify_station(self):
        if self._verifying_station or self.busy: return
        self._verifying_station=True
        code=self.cfg["STATION_CODE"]; token=self.cfg["STATION_TOKEN"]
        self.run_async(lambda:self.api.rpc("library_kiosk_auth",{"p_station_code":code,"p_token":token}),self._station_ok,self._station_fail)

    def _station_ok(self,_r):
        self._verifying_station=False; self.online=True
        if not self.busy and self.mode=="member" and self.scan_panel is not None: self.set_online(True,"ONLINE • Ready for RFID scan")
        else: self.set_online(True,self.status.text())

    def _station_fail(self,_e):
        self._verifying_station=False; self.online=False; self.set_online(False,"OFFLINE • Station not verified")

    def heartbeat_fn(self):
        self.verify_station()
        if self.online and not self.busy and not self._syncing:
            self._syncing=True
            def done(result):
                self._syncing=False
                self.status.setText(f"ONLINE • {result['pending']} attendance scan(s) pending sync / review" if result['pending'] else 'ONLINE • All attendance synced')
            def fail(exc):
                self._syncing=False
                self.status.setText(f"OFFLINE • {len(self.outbox.rows(self.cfg['STATION_CODE']))} scan(s) waiting to sync")
            self.run_async(lambda:self.outbox.sync(self.api,self.cfg),done,fail)

    def set_online(self,online,text):
        self.status.setText(text); self.status_dot.setStyleSheet(f"color:{SUCCESS if online else DANGER};font-size:13px;background:transparent;")
        if online and MOTION_ENABLED:
            if self._dot_anim.state()!=QPropertyAnimation.State.Running: self._dot_anim.start()
        else:
            self._dot_anim.stop(); self._dot_fx.setOpacity(1.0)

    # ========================================================
    # RFID
    # ========================================================
    def handle_rfid(self,uid):
        uid=str(uid).strip()
        if not uid or self.busy: return
        if self.mode=="member": self.start_rfid_verification(uid)
        elif self.mode=="register_rfid": self._handle_registration_rfid(uid)
        elif self.mode=="book_borrow": self.find_book_borrow(uid)
        elif self.mode=="book_return": self.find_book_return(uid)

    def start_rfid_verification(self,uid):
        from shared.kiosk_suite import maintenance_block
        if maintenance_block(self):return
        action=self.pending_action
        if action=='attendance':
            self.record_attendance_uid(uid);return
        accent={"borrow":BANNER_2,"return":SECONDARY,"attendance":SUCCESS,"print":GOLD}.get(action,BANNER_2)
        self.run_with_processing(
            "VERIFYING YOUR SCHOOL ID","Reading your card",
            ["Reading your RFID card","Finding your library account","Checking your account status","Getting your options ready"],
            fn=lambda:self._lookup_member(uid),on_ok=self._member_found,on_err=self._member_failed,
            accent=accent,icon="card",min_ms=1800,step_ms=650)

    # ========================================================
    # MEMBER / STUDENT INFO
    # ========================================================
    def _lookup_member(self,uid):
        rows=self.api.rpc("library_find_member",{"p_rfid":uid})
        if not rows: raise ApiError("RFID is not registered.")
        member=rows[0] if isinstance(rows,list) else rows
        if isinstance(member,dict):
            cnt=member.get("borrowed_count")
            if cnt is None: cnt=member.get("current_loans")
            if cnt is None:
                try: member["_loan_count"]=len(self.api.select("library_loans",f"?select=id&member_id=eq.{member['id']}&status=eq.borrowed") or [])
                except Exception: member["_loan_count"]=None
        member['rfid_uid']=uid
        return member

    def _member_found(self,member):
        self.member=member
        action=self.pending_action; self.pending_action=None
        if action=="borrow": self.borrow_start()
        elif action=="return": self.return_start()
        elif action=="attendance": self.attendance()
        elif action=="print": self.print_start()
        elif action=="account":
            from shared.account_ui import kiosk_account
            kiosk_account(self)
        else: self.show_member()

    def _member_failed(self,exc):
        self.pending_action=None; self.show_error("RFID NOT FOUND",str(exc))

    def show_member(self):
        m=self.member or {}; name=str(m.get("full_name") or "Library Member")
        student_id=str(m.get("student_id") or m.get("student_number") or m.get("id") or "Not available")
        grade=str(m.get("grade_level") or m.get("grade") or "Not available")
        section=str(m.get("section") or m.get("section_name") or "Not available")
        course=str(m.get("course") or m.get("program") or "Not specified")
        gender=str(m.get("gender") or "Not specified")
        member_type=str(m.get("member_type") or m.get("person_type") or m.get("role") or "STUDENT").upper()
        status=str(m.get("status") or "ACTIVE").upper()
        library_status="ACTIVE" if status in {"ACTIVE","ENABLED"} else status
        loan_count=m.get("borrowed_count")
        if loan_count is None: loan_count=m.get("current_loans")
        if isinstance(loan_count,(list,tuple)): loan_count=len(loan_count)
        if loan_count is None: loan_count=m.get("_loan_count")
        if loan_count is None: loan_count="—"
        self.mode="member_action"; self.clear_content()
        page=QFrame(); page.setStyleSheet(f"QFrame{{background:{BACKGROUND};border:none;}}"); row=QHBoxLayout(page); row.setContentsMargins(0,0,0,0); row.setSpacing(12)
        left=QFrame(); left.setStyleSheet(f"QFrame{{background:{WHITE};border:none;border-radius:22px;}}"); ll=QVBoxLayout(left); ll.setContentsMargins(24,22,24,20); ll.setSpacing(11)
        w=QLabel("WELCOME BACK"); w.setStyleSheet(f"color:{BANNER_2};font-size:10px;font-weight:950;letter-spacing:1.6px;"); h=QLabel("What would you like to do?"); h.setStyleSheet(f"color:{TEXT};font-size:31px;font-weight:950;"); s=QLabel(name.upper()); s.setWordWrap(True); s.setStyleSheet(f"color:{MUTED};font-size:14px;font-weight:800;"); helper=QLabel("Choose a service below."); helper.setStyleSheet(f"color:{MUTED};font-size:11px;font-weight:650;"); ll.addWidget(w); ll.addWidget(h); ll.addWidget(s); ll.addWidget(helper); ll.addSpacing(6)
        action_buttons=[]
        for title,desc,color,cb,icon in (("ATTENDANCE","Time in / time out",SUCCESS,self.attendance,"✓"),("BORROW BOOK","Take a book",BANNER_2,self.borrow_start,"📖"),("RETURN BOOK","Surrender a book",SECONDARY,self.return_start,"↩"),("PRINT A FILE","Print from a USB drive",GOLD,self.print_start,"🖨")):
            b=ShimmerButton(); b.setMinimumHeight(88); b.setText(f"{icon}   {title}\n      {desc}"); b.setStyleSheet(f"QPushButton{{background:#FFF8F5;color:{TEXT};border:none;border-left:8px solid {color};border-radius:16px;text-align:left;padding:11px 16px;font-size:12px;font-weight:950;}} QPushButton:hover{{background:#EAF2FF;}} QPushButton:pressed{{background:#F7E7E0;}}"); b.clicked.connect(cb); ll.addWidget(b); action_buttons.append(b)
        note=QFrame(); note.setStyleSheet("QFrame{background:#FFF5DD;border:none;border-radius:14px;}"); nl=QHBoxLayout(note); nl.setContentsMargins(14,10,14,10); inf=QLabel("i"); inf.setFixedSize(28,28); inf.setAlignment(Qt.AlignmentFlag.AlignCenter); inf.setStyleSheet("background:#F2B84B;color:white;border-radius:14px;font-size:14px;font-weight:950;"); nt=QLabel("Borrowing a book will ask you to choose the date you want to surrender it."); nt.setWordWrap(True); nt.setStyleSheet(f"color:{TEXT};font-size:10px;font-weight:750;"); nl.addWidget(inf); nl.addWidget(nt,1); ll.addWidget(note); ll.addStretch(); back=QPushButton("←  CANCEL / BACK TO START"); back.setMinimumHeight(48); back.setStyleSheet(f"QPushButton{{background:#F2ECE8;color:{MUTED};border:none;border-radius:12px;font-size:10px;font-weight:950;}} QPushButton:hover{{background:#EAE1DC;color:{TEXT};}}"); back.clicked.connect(self.reset); ll.addWidget(back)
        info=QFrame(); info.setFixedWidth(365); info.setStyleSheet("QFrame{background:#172237;border:none;border-radius:22px;}"); il=QVBoxLayout(info); il.setContentsMargins(22,22,22,22); il.setSpacing(10)
        head=QLabel("STUDENT INFORMATION"); head.setStyleSheet("color:rgba(255,255,255,185);font-size:9px;font-weight:950;letter-spacing:1.5px;")
        initial=(name[:1].upper() if name else "ID"); avatar=QLabel(initial); avatar.setFixedSize(94,94); avatar.setAlignment(Qt.AlignmentFlag.AlignCenter); avatar.setStyleSheet(f"QLabel{{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {BANNER_2},stop:1 {BANNER_1});color:white;border-radius:47px;font-size:30px;font-weight:950;}}")
        nm=QLabel(name.upper()); nm.setWordWrap(True); nm.setStyleSheet("color:white;font-size:25px;font-weight:950;")
        ver=QLabel("RFID VERIFIED  ✓"); ver.setAlignment(Qt.AlignmentFlag.AlignCenter); ver.setFixedHeight(30); ver.setStyleSheet("QLabel{background:rgba(40,190,120,.18);color:#67E3A7;border-radius:10px;font-size:8px;font-weight:950;letter-spacing:.8px;}")
        il.addWidget(head); il.addWidget(avatar,alignment=Qt.AlignmentFlag.AlignHCenter); il.addWidget(nm); il.addWidget(ver)
        fields=(("Student ID",student_id),("Grade / Level",grade),("Section",section),("Course",course),("Gender",gender),("Member Type",member_type),("Books on Loan",str(loan_count)),("Account Status",status),("Library Access",library_status))
        info_rows=[]; loan_label=None
        for label,value in fields:
            rw=QWidget(); rw.setStyleSheet("background:transparent;"); r=QHBoxLayout(rw); r.setContentsMargins(0,4,0,4); a=QLabel(label); a.setStyleSheet("color:rgba(255,255,255,160);font-size:9px;font-weight:750;"); b=QLabel(str(value)); b.setWordWrap(True); b.setAlignment(Qt.AlignmentFlag.AlignRight); b.setStyleSheet("color:white;font-size:10px;font-weight:900;"); r.addWidget(a); r.addStretch(); r.addWidget(b); il.addWidget(rw); info_rows.append(rw)
            if label=="Books on Loan": loan_label=b
        il.addStretch(); row.addWidget(left,1); row.addWidget(info); self.content_layout.addWidget(page,1)
        # entrance: welcome text, then the service buttons cascade in; the student card fills in row by row
        stagger_fade([w,h,s,helper]+action_buttons+[note,back],start=0,step=70,duration=340)
        stagger_fade([head,avatar,nm,ver]+info_rows,start=120,step=55,duration=320)
        if loan_label is not None and isinstance(loan_count,int): count_up(loan_label,loan_count)

    # ========================================================
    # ATTENDANCE
    # ========================================================
    def record_attendance_uid(self,uid):
        from shared.services import station
        from shared.api import NetworkError
        import uuid
        from datetime import timezone
        event={'id':str(uuid.uuid4()),'rfid':uid,'scanned_at':datetime.now(timezone.utc).isoformat()}
        def job():
            # Persist first: a lost response must retry the identical id, not create a second scan.
            event=self.outbox.add(self.cfg['STATION_CODE'],uid)
            result=self.outbox.sync(self.api,self.cfg)
            rows=self.outbox.rows(self.cfg['STATION_CODE'])
            own=next((r for r in rows if r['id']==event['id']),None)
            if own and own.get('error'):raise ApiError(own['error'])
            return {'pending':own is not None,'count':result['pending']}
        self.run_with_processing('RECORDING ATTENDANCE','Saving your card scan',
            ['Saving scan on this computer','Syncing with the library'],fn=job,
            on_ok=lambda result:self.show_result('SAVED OFFLINE' if result['pending'] else 'ATTENDANCE RECORDED','Card scan saved',
            'PENDING SYNC' if result['pending'] else 'SYNCED',
            'Awaiting server verification. Do not tap again. Keep this PC available to sync.' if result['pending'] else 'Your time in / out was recorded. Duplicate taps within 10 seconds are ignored.',SUCCESS,'✓',4500),
            on_err=lambda exc:self.show_error('ATTENDANCE NEEDS REVIEW',str(exc)),accent=SUCCESS,icon='card',min_ms=1600,step_ms=600)

    def attendance(self):
        if self.member and not self.busy:self.record_attendance_uid(self.member.get('rfid_uid',''))

    # ========================================================
    # BOOK WORKFLOW
    # ========================================================
    def borrow_start(self): self.mode="book_borrow"; self.show_book_screen("BORROW BOOK","Scan the book RFID or enter it manually.")
    def return_start(self): self.mode="book_return"; self.show_book_screen("RETURN BOOK","Scan the book RFID or enter it manually.")

    def show_book_screen(self,title,subtitle):
        accent=SECONDARY if self.mode=="book_return" else BANNER_2
        self.clear_content(); page=QFrame(); page.setStyleSheet(f"QFrame{{background:{BACKGROUND};border:none;}}"); lay=QVBoxLayout(page); lay.setContentsMargins(0,0,0,0); lay.setSpacing(12)
        card=QFrame(); card.setStyleSheet(f"QFrame{{background:{WHITE};border:none;border-radius:20px;}}"); cl=QVBoxLayout(card); cl.setContentsMargins(22,18,22,18); h=QLabel(title); h.setStyleSheet(f"color:{TEXT};font-size:28px;font-weight:950;"); s=QLabel(subtitle); s.setStyleSheet(f"color:{MUTED};font-size:12px;font-weight:650;"); cl.addWidget(h); cl.addWidget(s); lay.addWidget(card)
        body=QHBoxLayout(); body.setSpacing(12); scan=QFrame(); scan.setStyleSheet(f"QFrame{{background:#FFF9F7;border:2px dashed #F0AD9C;border-radius:22px;}}"); sl=QVBoxLayout(scan); sl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        visual=BookScanVisual(accent); sl.addWidget(visual,alignment=Qt.AlignmentFlag.AlignHCenter)
        big=QLabel("SCAN\nBOOK RFID"); big.setAlignment(Qt.AlignmentFlag.AlignCenter); big.setStyleSheet(f"color:{accent};font-size:34px;font-weight:950;border:none;"); sm=QLabel("Hold the book RFID tag near the reader."); sm.setAlignment(Qt.AlignmentFlag.AlignCenter); sm.setWordWrap(True); sm.setStyleSheet(f"color:{MUTED};font-size:13px;font-weight:700;border:none;"); sl.addWidget(big); sl.addWidget(sm); body.addWidget(scan,5)
        keys=QFrame(); keys.setStyleSheet(f"QFrame{{background:{WHITE};border:none;border-radius:22px;}}"); kl=QVBoxLayout(keys); self.manual=QLineEdit(); self.manual.setPlaceholderText("Enter Book RFID"); self.manual.setMinimumHeight(52); self.manual.setAlignment(Qt.AlignmentFlag.AlignCenter); self.manual.setStyleSheet(f"QLineEdit{{background:#FAF7F5;color:{TEXT};border:none;border-bottom:3px solid #E6DAD4;border-radius:12px;padding:8px;font-size:18px;font-weight:900;}} QLineEdit:focus{{border-bottom:3px solid {accent};background:white;}}"); kl.addWidget(self.manual)
        grid=QGridLayout(); grid.setSpacing(8); labels=[("1","1"),("2","2"),("3","3"),("4","4"),("5","5"),("6","6"),("7","7"),("8","8"),("9","9"),("CLR","CLEAR"),("0","0"),("OK","SUBMIT")]
        for i,(txt,key) in enumerate(labels):
            b=QPushButton(txt); b.setMinimumHeight(52); b.setStyleSheet(f"QPushButton{{background:{accent if key=='SUBMIT' else '#FAF8F7'};color:{'white' if key=='SUBMIT' else TEXT};border:none;border-radius:12px;font-size:16px;font-weight:900;}} QPushButton:pressed{{background:#EDE2DD;}}"); b.clicked.connect(lambda _,k=key:self.keypad(k)); grid.addWidget(b,i//3,i%3)
        kl.addLayout(grid); body.addWidget(keys,4); lay.addLayout(body,1); back=QPushButton("←  BACK"); back.setMinimumHeight(50); back.clicked.connect(self.show_member); back.setStyleSheet(f"QPushButton{{background:#E3EBF6;color:{TEXT};border:none;border-radius:12px;font-weight:900;}}"); lay.addWidget(back); self.content_layout.addWidget(page,1); self.manual.setFocus()
        stagger_fade([card,scan,keys,back],start=0,step=90,duration=360)

    def keypad(self,value):
        if self.manual is None: return
        if value=="CLEAR": self.manual.clear(); return
        if value=="SUBMIT":
            uid=self.manual.text().strip()
            if not uid: kiosk_msg(self,"Book RFID","Enter a book RFID first.","warning"); return
            self.find_book_borrow(uid) if self.mode=="book_borrow" else self.find_book_return(uid); return
        self.manual.setText(self.manual.text()+value)

    # ---- borrow --------------------------------------------------------
    def find_book_borrow(self,uid):
        if self.busy: return
        self.run_with_processing(
            "READING YOUR BOOK","Looking up the book tag",
            ["Reading the book tag","Finding the book in the catalog"],
            fn=lambda:self.api.rpc("library_find_book",{"p_rfid":uid}),
            on_ok=self._borrow_book_found,
            on_err=lambda exc:self.show_error("BORROW FAILED",str(exc)),
            accent=BANNER_2,icon="book",min_ms=1000,step_ms=520)

    def _borrow_book_found(self,rows):
        if not rows: self.show_error("BORROW FAILED","Book RFID is not registered."); return
        book=rows[0] if isinstance(rows,list) else rows; title=book.get("title","Book")
        self.busy=True
        try: due=self.ask_return_date(title)
        finally: self.busy=False
        if due is None: self.borrow_start(); return
        days=QDate.currentDate().daysTo(due)
        if days<1: kiosk_msg(self,"Invalid Return Date","Please choose a return date starting tomorrow.","warning"); self.borrow_start(); return
        member=self.member; due_text=due.toString('MMMM d, yyyy')
        self.run_with_processing(
            "VERIFYING YOUR BOOK BORROW REQUEST","Checking your request",
            ["Reading the book tag","Checking that the book is available","Checking your library account","Sending your request to the librarian"],
            fn=lambda:self.api.rpc("library_borrow",{"p_member_id":member["id"],"p_book_id":book["id"],"p_actor":self.cfg["STATION_CODE"],"p_due_days":days}),
            on_ok=lambda _r:self.show_result("BORROW REQUEST",f"{title}\nReturn by {due_text}","PROCEED TO THE LIBRARIAN FOR VERIFICATION","Please bring the book and your school ID to the librarian before leaving.",BANNER_2,"!",8000),
            on_err=lambda exc:self.show_error("BORROW FAILED",str(exc)),
            accent=BANNER_2,icon="book",chip=f"“{title}”   •   Return by {due.toString('MMM d, yyyy')}",min_ms=2800,step_ms=800)

    def ask_return_date(self,book_title):
        dlg=QDialog(self); dlg.setWindowTitle("Choose Return Date"); dlg.setModal(True); dlg.setMinimumSize(900,700); dlg.setStyleSheet(f"QDialog{{background:{BACKGROUND};}} QLabel{{color:{TEXT};background:transparent;}} QPushButton{{border-radius:14px;font-weight:800;}}")
        lay=QVBoxLayout(dlg); lay.setContentsMargins(28,24,28,26); lay.setSpacing(14); head=QFrame(); head.setStyleSheet(f"QFrame{{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {BANNER_2},stop:1 {BANNER_1});border-radius:18px;}}"); hl=QVBoxLayout(head); h=QLabel("WHAT DAY DO YOU WANT TO SURRENDER THE BOOK?"); h.setAlignment(Qt.AlignmentFlag.AlignCenter); h.setStyleSheet("color:white;font-size:22px;font-weight:900;"); t=QLabel(f'"{book_title}"'); t.setAlignment(Qt.AlignmentFlag.AlignCenter); t.setStyleSheet("color:rgba(255,255,255,220);font-size:14px;font-weight:600;"); hl.addWidget(h); hl.addWidget(t); lay.addWidget(head)
        selected=QDate.currentDate().addDays(7); chosen={"date":selected}; min_date=QDate.currentDate().addDays(1); visible={"date":QDate(selected.year(),selected.month(),1)}; sel=QLabel(); sel.setAlignment(Qt.AlignmentFlag.AlignCenter); sel.setStyleSheet(f"color:{ACCENT};font-size:18px;font-weight:900;"); lay.addWidget(sel)
        cal=QFrame(); cal.setStyleSheet(f"QFrame{{background:{WHITE};border:none;border-radius:20px;}}"); cl=QVBoxLayout(cal); nav=QHBoxLayout(); prev=QPushButton("‹"); nxt=QPushButton("›"); ml=QLabel(); ml.setAlignment(Qt.AlignmentFlag.AlignCenter); ml.setStyleSheet(f"color:{TEXT};font-size:22px;font-weight:900;"); prev.setFixedSize(58,52); nxt.setFixedSize(58,52); nav.addWidget(prev); nav.addWidget(ml,1); nav.addWidget(nxt); cl.addLayout(nav); wk=QGridLayout();
        for i,d in enumerate(("SUN","MON","TUE","WED","THU","FRI","SAT")):
            q=QLabel(d); q.setAlignment(Qt.AlignmentFlag.AlignCenter); q.setStyleSheet(f"color:{MUTED};font-size:12px;font-weight:900;"); wk.addWidget(q,0,i)
        cl.addLayout(wk); dg=QGridLayout(); dg.setSpacing(6); cl.addLayout(dg,1)
        def render():
            while dg.count():
                it=dg.takeAt(0); w=it.widget()
                if w: w.deleteLater()
            month=visible["date"]; ml.setText(month.toString("MMMM yyyy").upper()); start=QDate(month.year(),month.month(),1).dayOfWeek()%7
            for day in range(1,month.daysInMonth()+1):
                d=QDate(month.year(),month.month(),day); r=(start+day-1)//7; c=(start+day-1)%7; b=QPushButton(str(day)); b.setMinimumHeight(58); b.setEnabled(d>=min_date)
                if d<min_date: b.setStyleSheet("QPushButton{background:#F1F2F4;color:#B8BDC6;border:none;}")
                elif d==chosen["date"]: b.setStyleSheet(f"QPushButton{{background:{ACCENT};color:white;border:none;font-size:17px;}}")
                else: b.setStyleSheet(f"QPushButton{{background:#FAFAFB;color:{TEXT};border:none;font-size:17px;}} QPushButton:hover{{background:{ACCENT_LIGHT};color:{ACCENT};}}")
                b.clicked.connect(lambda _,date=d:(chosen.__setitem__("date",date),sel.setText(f"RETURN DATE: {date.toString('dddd, MMMM d, yyyy').upper()}"),render())); dg.addWidget(b,r,c)
        def prev_month():
            nm=visible["date"].addMonths(-1); minm=QDate(min_date.year(),min_date.month(),1)
            if nm>=minm: visible["date"]=nm; render()
        def next_month(): visible["date"]=visible["date"].addMonths(1); render()
        prev.clicked.connect(prev_month); nxt.clicked.connect(next_month); sel.setText(f"RETURN DATE: {selected.toString('dddd, MMMM d, yyyy').upper()}"); render(); lay.addWidget(cal,1)
        btns=QHBoxLayout(); cancel=QPushButton("CANCEL"); confirm=QPushButton("CONFIRM RETURN DATE"); cancel.setMinimumHeight(58); confirm.setMinimumHeight(58); cancel.clicked.connect(dlg.reject); confirm.clicked.connect(dlg.accept); cancel.setStyleSheet(f"QPushButton{{background:{WHITE};color:{MUTED};border:none;}}"); confirm.setStyleSheet(f"QPushButton{{background:{ACCENT};color:white;border:none;}}"); btns.addWidget(cancel); btns.addWidget(confirm,1); lay.addLayout(btns)
        fade_in(cal,300)
        return chosen["date"] if dlg.exec()==QDialog.DialogCode.Accepted else None

    # ---- return --------------------------------------------------------
    def _return_job(self,member,uid):
        loans=self.api.select("library_loans","?select=id,book_id"+f"&member_id=eq.{member['id']}&status=eq.borrowed") or []; books=self.api.rpc("library_find_book",{"p_rfid":uid})
        if not books: raise ApiError("Book RFID is not registered.")
        book=books[0] if isinstance(books,list) else books; loan=next((x for x in loans if x.get("book_id")==book.get("id")),None)
        if not loan: raise ApiError("This book is not currently borrowed by this member.")
        from shared.services import station
        station(self.api,self.cfg,"return_request",{"loan_id":loan["id"],"rfid":member.get("rfid_uid","")})
        return book

    def find_book_return(self,uid):
        if self.busy: return
        member=self.member
        self.run_with_processing(
            "VERIFYING YOUR BOOK RETURN","Checking your return",
            ["Reading the book tag","Finding your borrowed book","Sending return request","Waiting for librarian confirmation"],
            fn=lambda:self._return_job(member,uid),
            on_ok=lambda book:self.show_result("RETURN REQUESTED",book.get("title","Book"),"LIBRARIAN CONFIRMATION REQUIRED","Please hand the book to the librarian. It remains on loan until approved.",SUCCESS,"✓",4500),
            on_err=lambda exc:self.show_error("RETURN FAILED",str(exc)),
            accent=SECONDARY,icon="book",min_ms=2400,step_ms=700)

    # ========================================================
    # RESULTS / ERRORS
    # ========================================================
    def show_result(self,heading,detail,status,note,accent,icon,reset_ms):
        self.clear_content()
        kind="error" if accent==DANGER else ("ok" if icon=="✓" else "alert")
        page=TapFrame(); page.setObjectName("resultPage"); page.setStyleSheet(f"QFrame#resultPage{{background:{BACKGROUND};border:none;}}"); page.tapped.connect(self._result_tap)
        root=QVBoxLayout(page); root.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card=QFrame(); card.setObjectName("resultCard"); card.setFixedWidth(720); card.setStyleSheet(f"QFrame#resultCard{{background:{WHITE};border:none;border-radius:30px;}}")
        cl=QVBoxLayout(card); cl.setContentsMargins(40,28,40,22); cl.setSpacing(8)
        badge=StatusBadge(accent,"book",150,working=False); badge.show_result(kind,delay=180)
        title=QLabel(heading.upper()); title.setAlignment(Qt.AlignmentFlag.AlignCenter); title.setWordWrap(True); title.setStyleSheet(f"color:{TEXT};font-size:33px;font-weight:950;background:transparent;")
        detail_lbl=QLabel(detail); detail_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter); detail_lbl.setWordWrap(True); detail_lbl.setStyleSheet(f"color:{MUTED};font-size:16px;font-weight:700;background:transparent;")
        st=QLabel(status.upper()); st.setAlignment(Qt.AlignmentFlag.AlignCenter); st.setWordWrap(True); st.setStyleSheet(f"color:{accent};font-size:12px;font-weight:950;letter-spacing:1px;background:transparent;")
        note_lbl=QLabel(note); note_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter); note_lbl.setWordWrap(True); note_lbl.setStyleSheet(f"color:{MUTED};font-size:11px;font-weight:650;background:transparent;")
        bar=CountdownBar(reset_ms,accent); tap=QLabel("TAP ANYWHERE TO CONTINUE"); tap.setAlignment(Qt.AlignmentFlag.AlignCenter); tap.setStyleSheet(f"color:{MUTED_LIGHT};font-size:8px;font-weight:950;letter-spacing:1.4px;background:transparent;")
        cl.addWidget(badge,alignment=Qt.AlignmentFlag.AlignHCenter)
        for wdg in (title,detail_lbl,st,note_lbl): cl.addWidget(wdg)
        cl.addSpacing(8); cl.addWidget(bar); cl.addWidget(tap)
        root.addWidget(card); self.content_layout.addWidget(page,1)
        stagger_fade([title,detail_lbl,st,note_lbl],start=380,step=120,duration=380)
        if kind=="ok" and MOTION_ENABLED: ConfettiLayer(page,badge,delay_ms=650)
        self._result_shown_at=clock(); self._reset_timer.start(int(reset_ms))

    def _result_tap(self):
        if clock()-self._result_shown_at>0.9: self.reset()

    def show_error(self,title,detail): self.show_result(title,detail,"PLEASE TRY AGAIN","If the problem continues, please contact the librarian.",DANGER,"!",4500)

    def create_secondary_button(self,text,callback):
        b=QPushButton(text); b.setMinimumHeight(50); b.setStyleSheet(f"QPushButton{{background:{WHITE};color:{MUTED};border:none;border-radius:13px;font-weight:700;}} QPushButton:hover{{background:{ACCENT_LIGHT};color:{ACCENT};}} "); b.clicked.connect(callback); return b

    def reset(self):
        self._reset_timer.stop(); self.busy=False; self.member=None; self.mode="member"; self.manual=None; self.pending_action=None; self.show_home(); self.status.setText("ONLINE • Ready for RFID scan" if self.online else "OFFLINE • Check connection")

    def closeEvent(self,event): event.accept()


def main(app=None):
    from shared.runtime import configure
    configure("kiosk")
    # a stray exception in a Qt slot must never close the kiosk - log it and keep running
    sys.excepthook=lambda et,ev,tb: traceback.print_exception(et,ev,tb)
    app=app or QApplication.instance() or QApplication(sys.argv); app.setApplicationName("SMPCS Library Kiosk"); app.setOrganizationName("St. Martin de Porres Catholic School, Inc.")
    try: apply_theme(app)
    except Exception: pass
    cfg=load_config(); required=("SUPABASE_URL","SUPABASE_ANON_KEY","STATION_CODE","STATION_TOKEN")
    if not all(cfg.get(k) for k in required):
        setup=KioskSetup()
        if setup.exec()!=QDialog.DialogCode.Accepted: return 0
        cfg=load_config()
    try: api=SupabaseAPI(cfg["SUPABASE_URL"],cfg["SUPABASE_ANON_KEY"])
    except Exception as exc: kiosk_msg(None,"Setup Error",str(exc),"error"); return 1
    global MOTION_ENABLED
    MOTION_ENABLED=cfg.get("KIOSK_ANIMATIONS",True)
    window=Kiosk(api,cfg)
    if not cfg.get("KIOSK_FULLSCREEN",True): window.showMaximized()
    from shared.updates import attach_updates
    attach_updates(window, kiosk=True)
    return app.exec()


if __name__=="__main__":
    sys.exit(main())