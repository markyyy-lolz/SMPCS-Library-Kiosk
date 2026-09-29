"""Installed release summary shown after a successful admin session starts."""
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton
from shared.changelog import CURRENT_CHANGES
from shared.theme import LIGHT_QSS
from shared.updates import VERSION


class WhatsNewDialog(QDialog):
    def __init__(self, parent, open_updates):
        super().__init__(parent)
        self.setWindowTitle("SMPCS Library — What's new")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(660, 570)
        self.setStyleSheet(LIGHT_QSS)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        header = QLabel(f"What's new\nInstalled version {VERSION}")
        header.setStyleSheet('background:#2563ad;color:white;border-radius:14px;padding:22px;font-size:22px;font-weight:700;')
        layout.addWidget(header)
        intro = QLabel('Welcome back! Here is what changed in your installed app.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.notes = QPlainTextEdit(CURRENT_CHANGES)
        self.notes.setReadOnly(True)
        self.notes.setStyleSheet('background:white;color:#254160;border:1px solid #dce6f3;border-radius:10px;padding:14px;font-size:14px;')
        layout.addWidget(self.notes, 1)
        footer = QLabel('You can read this again from Updates → What’s new.')
        footer.setWordWrap(True)
        layout.addWidget(footer)
        buttons = QHBoxLayout()
        updates = QPushButton('Open updates')
        def open_settings():
            self.accept()
            open_updates()
        updates.clicked.connect(open_settings)
        buttons.addWidget(updates)
        buttons.addStretch()
        self.continue_button = QPushButton('Continue to dashboard')
        self.continue_button.setStyleSheet('background:#2563ad;color:white;border-radius:10px;padding:12px 18px;font-weight:700;')
        self.continue_button.setDefault(True)
        self.continue_button.clicked.connect(self.accept)
        buttons.addWidget(self.continue_button)
        layout.addLayout(buttons)


def attach_admin_whats_new(window, controller):
    """Call only after admin login; kiosk staff authorization stays separate."""
    dialog = WhatsNewDialog(window, controller.show_settings)
    window.whats_new_dialog = dialog
    def show():
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
    menu = next((a.menu() for a in window.menuBar().actions()
                 if a.text() == 'Updates' and a.menu()), None)
    if menu is not None:
        menu.addAction("What's new", show)
    timer = QTimer(window)
    timer.setSingleShot(True)
    timer.timeout.connect(show)
    timer.start(0)
    return dialog
