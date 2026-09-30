import tempfile,unittest
from pathlib import Path
from datetime import datetime
from shared.update_schedule import in_window,validate_time
from shared.operations import labels_pdf

class OperationsTests(unittest.TestCase):
    def test_maintenance_windows(self):
        self.assertTrue(in_window(datetime(2026,1,1,18), '17:00','19:00'))
        self.assertFalse(in_window(datetime(2026,1,1,19), '17:00','19:00'))
        self.assertTrue(in_window(datetime(2026,1,1,23), '22:00','02:00'))
        self.assertTrue(in_window(datetime(2026,1,1,1), '22:00','02:00'))
        self.assertFalse(in_window(datetime(2026,1,1,12), '22:00','02:00'))
        self.assertFalse(in_window(datetime(2026,1,1,12), '12:00','12:00'))
        for invalid in ('24:00','12:60','hello'):
            with self.assertRaises(ValueError):validate_time(invalid)
    def test_labels_pdf_contains_each_accession(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'labels.pdf'
            rows=[{'title':'Science & Technology','accession':f'COPY-00000000-0000-0000-0000-000000000000-{i}','shelf':'SCI-10','condition':'good'} for i in range(13)]
            labels_pdf(p,rows)
            self.assertTrue(p.read_bytes().startswith(b'%PDF'))
            self.assertGreater(p.stat().st_size,2000)
    def test_staff_circulation_routing(self):
        from shared.suite import StaffAPI
        class API:
            def rpc(self,n,p):return n,p
        name,data=StaffAPI(API(),{'token':'staff'}).rpc('library_verify_loan',{'p_loan_id':'loan'})
        self.assertEqual(name,'library_operations');self.assertEqual(data['p_data'],{'id':'loan'})
        self.assertEqual(data['p_action'],'verify_loan')

    def test_scheduled_install_waits_for_idle_and_safe_screen(self):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QApplication,QMainWindow,QDialog
        from PyQt6.QtCore import QObject,QCoreApplication,QEvent
        from shared.update_schedule import attach
        app=QApplication.instance() or QApplication([]);window=QMainWindow()
        class Controller(QObject):
            def __init__(self):super().__init__(window);self.ready={'tag':'v9.0.0'};self.busy=False;self.installed=0
            def install(self):self.installed+=1
        controller=Controller();scheduler=attach(controller,window);cfg={'enabled':True,'start':'17:00','end':'19:00'}
        with patch('shared.update_schedule.read',return_value=cfg),patch('shared.update_schedule.write'),patch('shared.update_schedule.in_window',return_value=True),patch('shared.update_schedule.time.monotonic',return_value=1000):
            scheduler.last_activity=900;scheduler.tick();self.assertEqual(controller.installed,0)
            scheduler.last_activity=0;window.member={'id':'member'};scheduler.tick();self.assertEqual(controller.installed,0)
            window.member=None;window.current_page='books';scheduler.tick();self.assertEqual(controller.installed,0)
            window.current_page='dashboard';window.busy=True;scheduler.tick();self.assertEqual(controller.installed,0)
            window.busy=False;d=QDialog(window);d.show();scheduler.tick();self.assertEqual(controller.installed,0);d.hide()
            scheduler.tick();self.assertEqual(controller.installed,1)
            scheduler.tick();self.assertEqual(controller.installed,1)
        scheduler.timer.stop();window.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
