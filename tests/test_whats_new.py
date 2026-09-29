import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from unittest.mock import Mock
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication, QMainWindow, QPushButton, QLabel
from shared.whats_new import attach_admin_whats_new
from shared.changelog import CURRENT_CHANGES
from shared.updates import VERSION


class WhatsNewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_login_summary_and_reopen(self):
        window = QMainWindow()
        menu = window.menuBar().addMenu('Updates')
        controller = Mock()
        dialog = attach_admin_whats_new(window, controller)
        window.show()
        self.app.processEvents()
        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog.notes.toPlainText(), CURRENT_CHANGES)
        self.assertIn(VERSION, dialog.findChildren(QLabel)[0].text())
        controller.show_settings.assert_not_called()
        dialog.continue_button.click()
        self.assertFalse(dialog.isVisible())
        menu.actions()[-1].trigger()
        self.assertTrue(dialog.isVisible())
        next(b for b in dialog.findChildren(QPushButton) if b.text() == 'Open updates').click()
        controller.show_settings.assert_called_once()
        self.assertFalse(dialog.isVisible())
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
