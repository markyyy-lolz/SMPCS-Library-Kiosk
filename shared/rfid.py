from PyQt6.QtCore import QObject, pyqtSignal, QTimer
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QEvent

class RFIDCapture(QObject):
    tag = pyqtSignal(str)
    def __init__(self, parent=None, timeout_ms=120):
        super().__init__(parent)
        self.buffer = ""
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(timeout_ms)
        self.timer.timeout.connect(self.flush)
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            text = event.text()
            if key in (16777220, 16777221):  # Enter / Return
                self.flush()
                return True
            if text and text.isprintable() and len(text) == 1:
                self.buffer += text
                self.timer.start()
                return True
        return False

    def flush(self):
        value = "".join(ch for ch in self.buffer if ch.isalnum()).strip()
        self.buffer = ""
        self.timer.stop()
        if 3 <= len(value) <= 64:
            self.tag.emit(value)
