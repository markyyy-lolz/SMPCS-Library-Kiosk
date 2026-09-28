from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QLineEdit, QVBoxLayout,
    QHBoxLayout, QFormLayout, QMessageBox, QFrame, QScrollArea, QGridLayout,
    QDialog, QDialogButtonBox, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QStackedWidget
)

from shared.theme import LIGHT_QSS as APP_QSS, force_light_palette

def apply_theme(app):
    app.setStyle("Fusion")
    force_light_palette(app)
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
