"""The recovery updater must work without database authentication."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from unittest.mock import patch
from PyQt6.QtCore import QTimer,QAbstractAnimation,QCoreApplication,QEvent
from PyQt6.QtWidgets import QApplication,QPushButton

class UpdateAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):self.windows=[]
    def tearDown(self):
        for window in self.windows:
            for timer in window.findChildren(QTimer):timer.stop()
            for animation in window.findChildren(QAbstractAnimation):animation.stop()
            window.close();window.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def test_chooser_routes_to_standalone_updates(self):
        from shared.launcher import AppChooser
        chooser=AppChooser();self.windows.append(chooser)
        next(b for b in chooser.findChildren(QPushButton) if b.text()=='Updates / Repair').click()
        self.assertEqual(chooser.role,'updates')
    def test_login_updater_needs_no_api_and_handles_download_event(self):
        from admin.main import AdminLogin
        login=AdminLogin(None);self.windows.append(login);login.show()
        cfg={'repository':'markyyy-lolz/SMPCS-Library-Kiosk','enabled':False,'auto_download':False}
        with patch('shared.updates.read_settings',return_value=cfg):
            login.update_btn.click();controller=login.update_controller
            self.assertTrue(controller.dialog.isVisible())
            self.assertIsNone(login.user)
            self.assertIn('MY ACCOUNT',controller.notes.toPlainText())
            controller.release={'tag':'v9.0.0','notes':'• New display layout'}
            controller.refresh()
            self.assertEqual(controller.notes.toPlainText(),'• New display layout')
            self.assertIn('v9.0.0',controller.notes_title.text())
            self.assertTrue(controller.repo.isReadOnly())
            self.assertFalse(controller.enabled.isEnabled())
            controller.repo.setText('untrusted/other-app')
            self.assertEqual(controller.settings()['repository'],'markyyy-lolz/SMPCS-Library-Kiosk')
            # Regression: dialog parents have no menuBar/statusBar methods.
            ready={'tag':'v9.0.0','repository':cfg['repository'],'archive':'unused','sha256':'unused'}
            controller.events.put(('download',cfg['repository'],False,ready,None));controller.finish()
            self.assertTrue(controller.install_btn.isEnabled())
            self.assertIn('checksum verified',controller.label.text())
    def test_legacy_login_error_points_to_repair(self):
        from admin.main import AdminLogin
        from shared.api import ApiError
        class API:
            def rpc(self,*args):raise ApiError('Supabase error 401: permission denied for function library_login')
        login=AdminLogin(API());self.windows.append(login)
        login.login()
        self.assertIn('UPDATES / REPAIR',login.err.text())
        self.assertIsNone(login.user)
