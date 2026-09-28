"""One application entry point, with kiosk and staff choices."""
from pathlib import Path
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from shared.updates import VERSION

class AppChooser(QDialog):
    def __init__(self):
        super().__init__()
        self.role = None
        self.setWindowTitle('SMPCS Library')
        self.setMinimumSize(720, 460)
        self.setStyleSheet('''QDialog {background:#F3ECE7;}
            QLabel {color:#192B45; background:transparent; font-family:"Segoe UI";}
            QPushButton {background:#9B2335; color:white; border:none; border-radius:16px;
            padding:24px; font-size:20px; font-weight:700;}
            QPushButton:hover {background:#B82C43;} QPushButton:focus {border:3px solid #D99B48;}
            QPushButton#admin {background:#192B45;} QPushButton#admin:hover {background:#304E72;}''')
        layout=QVBoxLayout(self); layout.setContentsMargins(40,30,40,32); layout.setSpacing(18)
        logo=QLabel(); logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image=QPixmap(str(Path(__file__).resolve().parent.parent/'assets/school_logo.png'))
        logo.setPixmap(image.scaled(90,90,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(logo)
        title=QLabel('Welcome to SMPCS Library'); title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet('font-size:29px;font-weight:800;'); layout.addWidget(title)
        subtitle=QLabel('Choose how you want to use the library.'); subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet('font-size:15px;color:#6F727B;'); layout.addWidget(subtitle)
        row=QHBoxLayout(); row.setSpacing(18)
        kiosk=QPushButton('Go to Kiosk'); admin=QPushButton('Go to Admin'); admin.setObjectName('admin')
        kiosk.clicked.connect(lambda:self.choose('kiosk')); admin.clicked.connect(lambda:self.choose('admin'))
        row.addWidget(kiosk); row.addWidget(admin); layout.addLayout(row)
        note=QLabel('Kiosk: attendance, borrowing and returns\nAdmin: staff sign-in and library management')
        note.setAlignment(Qt.AlignmentFlag.AlignCenter); note.setStyleSheet('font-size:13px;color:#6F727B;'); layout.addWidget(note)
        footer=QLabel(f'Version {VERSION}'); footer.setAlignment(Qt.AlignmentFlag.AlignCenter); layout.addWidget(footer)

    def choose(self, role):
        self.role=role; self.accept()
