"""Local kiosk accessibility preferences; voice only reads generic guidance."""
import json
from PyQt6.QtCore import QObject,QEvent,QTimer
from PyQt6.QtWidgets import QPushButton,QLabel,QLineEdit,QCheckBox,QHBoxLayout
from shared.config import APP_DIR
from shared.account_ui import dialog,button
PATH=APP_DIR/'accessibility.json'

class Accessibility(QObject):
    def __init__(self,host):
        super().__init__(host);self.host=host;self.voice=None;self.pending=False
        try:self.options=json.loads(PATH.read_text())
        except (OSError,ValueError):self.options={}
        b=QPushButton('Accessibility');b.clicked.connect(self.settings);host.statusBar().addPermanentWidget(b)
        host.installEventFilter(self);self.apply();QTimer.singleShot(1500,self.speak)
    def eventFilter(self,obj,event):
        if event.type()==QEvent.Type.ChildAdded and not self.pending:
            self.pending=True;QTimer.singleShot(0,self.apply)
        return False
    def apply(self):
        self.pending=False
        for w in self.host.findChildren(QObject):
            if not isinstance(w,(QPushButton,QLabel,QLineEdit)):continue
            if w.property('accessBaseStyle') is None:
                w.setProperty('accessBaseStyle',w.styleSheet());w.setProperty('accessBaseMin',w.minimumHeight());w.installEventFilter(self)
            style=w.property('accessBaseStyle') or ''
            if self.options.get('large'):style+='\n'+type(w).__name__+' {font-size:20px;}'
            if self.options.get('contrast'):
                style+='\n'+type(w).__name__+' {color:#FFFFFF;background-color:#102A43;border:2px solid #FFFFFF;}'
                if isinstance(w,QPushButton):style+=' QPushButton:disabled{color:#AAB6C3;background:#31465C;} QPushButton:focus{border:3px solid #FFD54F;}'
            w.setStyleSheet(style)
            if isinstance(w,QPushButton):w.setMinimumHeight(max(w.property('accessBaseMin') or 0,54 if self.options.get('large') else 0))
    def speak(self):
        if not self.options.get('voice'):return
        try:
            from PyQt6.QtTextToSpeech import QTextToSpeech
            if self.voice is None:self.voice=QTextToSpeech(self)
            self.voice.say('Welcome to the library. Choose Attendance, Borrow, Return, or My Account, then tap your library card.')
        except (ImportError,RuntimeError):pass
    def settings(self):
        d,l=dialog(self.host,'Accessibility');choices={}
        for k,text in [('large','Larger text and buttons'),('contrast','High contrast'),('voice','Voice guidance (requires an installed system voice)')]:
            w=QCheckBox(text);w.setChecked(bool(self.options.get(k)));l.addWidget(w);choices[k]=w
        def save():
            self.options={k:w.isChecked() for k,w in choices.items()};PATH.parent.mkdir(parents=True,exist_ok=True);tmp=PATH.with_suffix('.tmp');tmp.write_text(json.dumps(self.options));tmp.replace(PATH);d.accept();self.apply();self.speak()
        button(l,'Read instructions',self.speak);button(l,'Save',save);button(l,'Close',d.reject);d.exec()
