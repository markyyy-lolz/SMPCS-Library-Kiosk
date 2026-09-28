"""Windowless entry point used by the Windows VBS launchers."""
import ctypes
import os
from pathlib import Path
import sys
import traceback

root = Path(__file__).resolve().parent
os.chdir(root)
sys.path.insert(0, str(root))
role = sys.argv[1] if len(sys.argv) > 1 else 'chooser'
try:
    from shared.runtime import configure
    configure(role if role in ('admin', 'kiosk', 'updates') else 'launcher')
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    if role == 'chooser':
        from shared.launcher import AppChooser
        chooser = AppChooser()
        if chooser.exec() != chooser.DialogCode.Accepted:
            sys.exit(0)
        role = chooser.role
    if role == 'updates':
        from PyQt6.QtWidgets import QApplication, QMainWindow
        from shared.updates import attach_updates
        owner = QMainWindow()
        controller = attach_updates(owner)
        controller.show_settings()
        controller.dialog.finished.connect(app.quit)
        code = app.exec()
    elif role in ('admin', 'kiosk'):
        from importlib import import_module
        code = import_module(role + '.main').main(app=app)
    else:
        raise ValueError('Unknown application: ' + role)
except Exception:
    traceback.print_exc()
    if os.name == 'nt':
        ctypes.windll.user32.MessageBoxW(None,
            'The app could not start. Run install.bat first.\nDetails: %APPDATA%\\SMPCS_Library\\logs',
            'SMPCS Library — Startup error', 16)
    code = 1
sys.exit(code or 0)
