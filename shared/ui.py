from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QLineEdit, QVBoxLayout,
    QHBoxLayout, QFormLayout, QMessageBox, QFrame, QScrollArea, QGridLayout,
    QDialog, QDialogButtonBox, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QStackedWidget
)

APP_QSS = """
* { font-family: "Segoe UI"; }
QWidget { background: #071426; color: #edf4ff; }
QFrame#card { background: #0e2039; border: 1px solid #1f3b5e; border-radius: 18px; }
QLabel#title { font-size: 30px; font-weight: 700; }
QLabel#muted { color: #8fa7c4; }
QLineEdit, QComboBox {
  background: #0a192c; border: 1px solid #2a486c; border-radius: 10px;
  padding: 12px; color: white; min-height: 20px;
}
QPushButton {
  background: #1479ff; border: none; border-radius: 11px; padding: 12px 18px;
  font-weight: 600; color: white;
}
QPushButton:hover { background: #3290ff; }
QPushButton:disabled { background: #253b56; color: #72849b; }
QPushButton#secondary { background: #17304d; }
QPushButton#danger { background: #a8324d; }
QTableWidget {
  background: #0a192c; alternate-background-color: #0d2036;
  gridline-color: #1f3854; border: 1px solid #203d5d;
}
QHeaderView::section { background: #112b48; color: #dcecff; padding: 9px; border: none; }
QMessageBox { background: #0e2039; }
"""

def apply_theme(app):
    app.setStyleSheet(APP_QSS)

def msg(parent, title, text, icon=QMessageBox.Icon.Information):
    box = QMessageBox(parent)
    box.setIcon(icon); box.setWindowTitle(title); box.setText(text)
    box.exec()

def card():
    f = QFrame(); f.setObjectName("card")
    return f

def button(text, slot=None, object_name=""):
    b = QPushButton(text)
    if object_name: b.setObjectName(object_name)
    if slot: b.clicked.connect(slot)
    return b

def table(columns):
    t = QTableWidget(0, len(columns))
    t.setHorizontalHeaderLabels(columns)
    t.setAlternatingRowColors(True)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    t.verticalHeader().setVisible(False)
    t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    return t

def fill_table(t, rows, keys):
    t.setRowCount(0)
    for row in rows or []:
        r = t.rowCount(); t.insertRow(r)
        for c, k in enumerate(keys):
            value = row.get(k, "")
            if isinstance(value, bool): value = "Yes" if value else "No"
            t.setItem(r, c, QTableWidgetItem(str(value if value is not None else "")))
