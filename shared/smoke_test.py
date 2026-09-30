"""Offline startup check used by the Windows release build."""
import json
from pathlib import Path
from PyQt6.QtCore import QTimer, QAbstractAnimation, QCoreApplication, QEvent
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
    import tempfile
    from shared.suite import export_rows
    with tempfile.TemporaryDirectory() as folder:
        for ext in ('pdf','xlsx'):
            path=Path(folder)/('smoke.'+ext);export_rows(str(path),['Field','Value'],[['Book','Build test']]);assert path.stat().st_size>0
        from shared.operations import labels_pdf
        labels_pdf(Path(folder)/'labels.pdf',[{'title':'Build test','accession':'TEST-001','shelf':'A1'}])
    if __import__('os').name=='nt':
        assert SILENT_IMAGE_PRINT_AVAILABLE, 'Windows image-print dependencies missing'
    chooser=AppChooser(); chooser.show()
    admin=AdminLogin(None); kiosk=KioskSetup()
    # Construct both routes without making database requests.
    chooser.choose('admin'); assert chooser.role=='admin'
    chooser.show(); chooser.choose('kiosk'); assert chooser.role=='kiosk'
    chooser.show(); app.processEvents()
    import admin.main as admin_module
    import kiosk.main as kiosk_module
    from shared.updates import attach_updates
    admin_module.MOTION_ENABLED=False; kiosk_module.MOTION_ENABLED=False
    class OfflineAPI:
        def select(self,*args,**kwargs): return []
        def rpc(self,*args,**kwargs): return {}
    original_load=admin_module.AdminWindow.load
    original_poll=admin_module.AdminWindow.poll_pending
    original_verify=kiosk_module.Kiosk.verify_station
    admin_module.AdminWindow.load=lambda *args:None
    admin_module.AdminWindow.poll_pending=lambda *args:None
    kiosk_module.Kiosk.verify_station=lambda *args:None
    staff=admin_module.AdminWindow(OfflineAPI(),{'full_name':'Build test','role':'admin'})
    staff.show(); staff.show_page('attendance')
    staff._attendance_rows=[{'name':'Test Member','student_id':'DEMO','grade':'10','action':'IN','time':'Test time','station':'TEST'}]
    staff.apply_attendance_filters(); assert staff.att_table.rowCount()==1
    staff.att_action.setCurrentText('OUT'); assert staff.att_table.rowCount()==0
    station=kiosk_module.Kiosk(OfflineAPI(),{'STATION_CODE':'TEST','STATION_NAME':'Test','STATION_TOKEN':'test-only'})
    station.showNormal(); station.resize(1366,768)
    updates=attach_updates(station,kiosk=True); updates.show_settings()
    assert '#F4F7FB' in updates.dialog.styleSheet()
    app.processEvents()
    QTimer.singleShot(500,app.quit)
    app.exec()
    # Dispose timers/animations while QApplication is alive.
    for window in (staff,station,chooser,admin,kiosk):
        for timer in window.findChildren(QTimer): timer.stop()
        for animation in window.findChildren(QAbstractAnimation): animation.stop()
        window.close(); window.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    admin_module.AdminWindow.load=original_load
    admin_module.AdminWindow.poll_pending=original_poll
    kiosk_module.Kiosk.verify_station=original_verify
    Path(result_path).write_text(json.dumps({'ok':True,'version':VERSION,'checks':['chooser','admin-login','kiosk-setup','logo','updates','bcrypt','printing-imports','attendance-filter','kiosk-home','light-updates-dialog']}))
    return 0
