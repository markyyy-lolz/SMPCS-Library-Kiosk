import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from PyQt6.QtWidgets import QApplication,QWidget
from PyQt6.QtCore import QCoreApplication,QEvent
from shared.account_ui import AccountDialog

class AccountLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_history_and_security_are_separate_and_filterable(self):
        host=QWidget();host.api=object();host.member={'rfid_uid':'test'};host.run_async=lambda *a:None
        dlg=AccountDialog(host);dlg.show();dlg.pages.setCurrentIndex(1)
        dlg.show_profile({'member':{'full_name':'Test Member','member_no':'S1','grade_level':'10','section':'Test'},'loans':[
            {'title':'Science','status':'borrowed','due_at':'2026-09-20','overdue':True},
            {'title':'History','status':'returned','due_at':'2026-09-25','overdue':False}]})
        self.app.processEvents()
        self.assertFalse(dlg.current.isVisible());self.assertTrue(dlg.history.isVisible())
        dlg.filter.setCurrentText('Overdue');self.assertEqual(dlg.history.rowCount(),1)
        dlg.search.setText('History');self.assertEqual(dlg.history.rowCount(),0)
        dlg.tabs.setCurrentIndex(1);self.app.processEvents()
        self.assertTrue(dlg.current.isVisible());self.assertFalse(dlg.history.isVisible())
        dlg.current.setText('123456');dlg.tabs.setCurrentIndex(0);self.assertEqual(dlg.current.text(),'')
        for width,height in [(940,680),(760,540)]:
            dlg.resize(width,height);self.app.processEvents()
            self.assertLessEqual(dlg.close_button.geometry().bottom(),dlg.height())
            self.assertLessEqual(dlg.width(),width)
        dlg.reject();dlg.deleteLater();host.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
