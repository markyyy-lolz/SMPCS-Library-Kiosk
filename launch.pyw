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
    if role == '--apply-update':
        from shared.installer import apply_request
        sys.exit(apply_request(sys.argv[2]))
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    from shared.ui import apply_theme
    apply_theme(app)
    if role == 'chooser':
        from shared.launcher import AppChooser
        chooser = AppChooser()
        if chooser.exec() != chooser.DialogCode.Accepted:
            sys.exit(0)
        role = chooser.role
    if role == '--smoke-test':
        from shared.smoke_test import run
        code = run(app, sys.argv[2])
    elif role == 'updates':
        from PyQt6.QtWidgets import QApplication, QMainWindow
        from shared.updates import attach_updates
        owner = QMainWindow()
        controller = attach_updates(owner)
        controller.show_settings()
        controller.dialog.finished.connect(app.quit)
        code = app.exec()
    elif role in ('admin', 'kiosk'):
        if role == 'admin':
            from admin.main import main
        else:
            from kiosk.main import main
        code = main(app=app)
    else:
        raise ValueError('Unknown application: ' + role)
except Exception:
    traceback.print_exc()
    if os.name == 'nt' and role != '--smoke-test':
        ctypes.windll.user32.MessageBoxW(None,
            'The app could not start. See the log for details.\nDetails: %APPDATA%\\SMPCS_Library\\logs',
            'SMPCS Library — Startup error', 16)
    code = 1
sys.exit(code or 0)
