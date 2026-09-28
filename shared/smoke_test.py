"""Offline startup check used by the Windows release build."""
import json
from pathlib import Path
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QDialog

def run(app, result_path):
    import bcrypt
    from admin.main import AdminLogin
    from kiosk.main import KioskSetup, SILENT_IMAGE_PRINT_AVAILABLE
    from shared.launcher import AppChooser
    from shared.updates import ROOT, VERSION, read_settings
    assert not QPixmap(str(ROOT/'assets/school_logo.png')).isNull(), 'Missing school logo'
    assert read_settings()['repository']=='markyyy-lolz/SMPCS-Library-Kiosk', 'Missing update defaults'
    assert bcrypt.checkpw(b'test',bcrypt.hashpw(b'test',bcrypt.gensalt(rounds=4)))
    if __import__('os').name=='nt':
        assert SILENT_IMAGE_PRINT_AVAILABLE, 'Windows image-print dependencies missing'
    chooser=AppChooser(); chooser.show()
    admin=AdminLogin(None); kiosk=KioskSetup()
    # Construct both routes without making database requests.
    chooser.choose('admin'); assert chooser.role=='admin'
    chooser.show(); chooser.choose('kiosk'); assert chooser.role=='kiosk'
    chooser.show(); app.processEvents()
    QTimer.singleShot(500,app.quit)
    app.exec()
    Path(result_path).write_text(json.dumps({'ok':True,'version':VERSION,'checks':['chooser','admin-login','kiosk-setup','logo','updates','bcrypt','printing-imports']}))
    return 0
