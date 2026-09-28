"""Shared explicit light palette, including dialogs under Windows dark mode."""
from PyQt6.QtGui import QColor, QPalette
LIGHT_QSS = '''
QWidget {font-family:"Segoe UI";color:#172B46;font-size:13px;}
QMainWindow,QDialog,QMessageBox {background:#F4F7FB;}
QLabel {background:transparent;color:#172B46;}
QLineEdit,QComboBox,QDateEdit,QSpinBox,QTextEdit {background:#FFFFFF;color:#172B46;border:1px solid #C6D2E0;border-radius:9px;padding:10px;min-height:24px;selection-background-color:#DBEAFE;selection-color:#172B46;}
QLineEdit:focus,QDateEdit:focus,QComboBox:focus {border:2px solid #2563EB;}
QComboBox QAbstractItemView,QCalendarWidget QAbstractItemView {background:white;color:#172B46;selection-background-color:#DBEAFE;selection-color:#172B46;}
QPushButton {background:#245DAD;color:white;border:1px solid transparent;border-radius:10px;padding:11px 17px;font-weight:700;}
QPushButton:hover {background:#194A90;} QPushButton:pressed {background:#153D76;}
QPushButton:disabled {background:#E2E8F0;color:#52647B;}
QCheckBox {background:transparent;color:#172B46;spacing:9px;min-height:26px;}
QCheckBox::indicator {width:19px;height:19px;}
QTableWidget {background:white;color:#172B46;alternate-background-color:#F3F6FB;gridline-color:#E3EAF3;border:1px solid #DEE6F0;selection-background-color:#DBEAFE;selection-color:#172B46;}
QHeaderView::section {background:#EAF0F8;color:#334C6C;padding:10px;border:none;font-weight:700;}
QMenuBar,QMenu {background:white;color:#172B46;} QMenu::item:selected,QMenuBar::item:selected {background:#DBEAFE;color:#172B46;}
QScrollArea {border:none;background:transparent;}
QToolTip {background:#172B46;color:white;border:none;padding:7px;}
'''

def force_light_palette(app):
    p=QPalette()
    values={'Window':'#F4F7FB','WindowText':'#172B46','Base':'#FFFFFF','AlternateBase':'#F3F6FB',
            'Text':'#172B46','Button':'#FFFFFF','ButtonText':'#172B46','Highlight':'#DBEAFE',
            'HighlightedText':'#172B46','ToolTipBase':'#172B46','ToolTipText':'#FFFFFF','PlaceholderText':'#64748B'}
    for role,color in values.items(): p.setColor(getattr(QPalette.ColorRole,role),QColor(color))
    p.setColor(QPalette.ColorGroup.Disabled,QPalette.ColorRole.Text,QColor('#64748B'))
    p.setColor(QPalette.ColorGroup.Disabled,QPalette.ColorRole.ButtonText,QColor('#64748B'))
    app.setPalette(p)
