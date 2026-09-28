from __future__ import annotations
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QFormLayout, QDialogButtonBox
from .api import SupabaseAPI, ApiError
from .config import save_config, load_config
from .ui import msg, card

class BackendSetup(QDialog):
    def __init__(self, parent=None, role="admin"):
        super().__init__(parent)
        self.role = role
        self.setWindowTitle("SMPCS Library — First Time Setup")
        self.setMinimumWidth(620)
        self.result_config = None
        lay = QVBoxLayout(self)
        title = QLabel("First Time Setup")
        title.setObjectName("title")
        lay.addWidget(title)
        subtitle = QLabel(
            "Connect this PC to the shared SMPCS Supabase database. "
            "Do not use a different database on the other PC."
        )
        subtitle.setWordWrap(True); subtitle.setObjectName("muted")
        lay.addWidget(subtitle)
        form = QFormLayout()
        self.url = QLineEdit(load_config().get("SUPABASE_URL", ""))
        self.key = QLineEdit(load_config().get("SUPABASE_ANON_KEY", ""))
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Supabase URL", self.url)
        form.addRow("Anon / Publishable Key", self.key)
        lay.addLayout(form)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        self.buttons.accepted.connect(self.test)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)

    def test(self):
        url, key = self.url.text().strip(), self.key.text().strip()
        if not url or not key:
            msg(self, "Missing", "Enter both Supabase URL and API key.")
            return
        try:
            api = SupabaseAPI(url, key)
            api.health()
        except ApiError as e:
            msg(self, "Connection failed", str(e))
            return
        self.result_config = {"SUPABASE_URL": url, "SUPABASE_ANON_KEY": key}
        save_config(self.result_config | load_config())
        self.accept()
