"""Opt-in maintenance windows. Times follow this computer's local timezone."""
import json
import time
from datetime import datetime
from shared.config import APP_DIR
PATH=APP_DIR/'update_schedule.json'

def validate_time(value):
    try:
        h,m=map(int,value.split(':'))
        if not (0<=h<24 and 0<=m<60):raise ValueError
    except (ValueError,AttributeError):raise ValueError('Use a 24-hour time, e.g. 17:00.')
    return h*60+m

def in_window(now,start,end):
    a,b=validate_time(start),validate_time(end);n=now.hour*60+now.minute
    return a<=n<b if a<b else n>=a or n<b if a>b else False

def read():
    try:
        data=json.loads(PATH.read_text());validate_time(data['start']);validate_time(data['end']);return data
    except (OSError,ValueError,KeyError,TypeError):return {'enabled':False,'start':'17:00','end':'19:00'}

def write(data):
    validate_time(data['start']);validate_time(data['end'])
    if data['start']==data['end']:raise ValueError('Choose different start and end times.')
    PATH.parent.mkdir(parents=True,exist_ok=True);tmp=PATH.with_suffix('.tmp');tmp.write_text(json.dumps(data));tmp.replace(PATH)

def attach(controller,window,public=False):
    from PyQt6.QtCore import QObject,QTimer,QEvent,QThread
    from PyQt6.QtWidgets import QApplication,QDialog,QCheckBox,QLineEdit,QLabel,QMessageBox
    from shared.account_ui import dialog,button
    class Scheduler(QObject):
        def __init__(self):
            super().__init__(controller);self.last_activity=time.monotonic();QApplication.instance().installEventFilter(self)
            self.timer=QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(30000)
        def eventFilter(self,obj,event):
            if event.type() in (QEvent.Type.KeyPress,QEvent.Type.MouseButtonPress,QEvent.Type.TouchBegin,QEvent.Type.Wheel):self.last_activity=time.monotonic()
            return False
        def tick(self):
            cfg=read();now=datetime.now()
            if public or not cfg.get('enabled') or not controller.ready or controller.busy or not in_window(now,cfg['start'],cfg['end']):return
            if time.monotonic()-self.last_activity<300 or getattr(window,'member',None) is not None or getattr(window,'busy',False):return
            if getattr(window,'current_page','dashboard') not in ('dashboard','services'):return
            if getattr(window,'pending_action',None) is not None:return
            if QApplication.activeModalWidget() or any(isinstance(w,QDialog) and w.isVisible() for w in QApplication.topLevelWidgets()):return
            if any(t.isRunning() for t in window.findChildren(QThread)):return
            attempt=now.date().isoformat()+':'+str(controller.ready.get('tag'))
            if cfg.get('attempt')==attempt:return
            cfg['attempt']=attempt
            try:write(cfg)
            except OSError:return
            controller.install()
        def settings(self):
            d,l=dialog(window,'Scheduled updates');cfg=read();enabled=QCheckBox('Install downloaded updates automatically while idle');enabled.setChecked(cfg.get('enabled',False));l.addWidget(enabled)
            l.addWidget(QLabel('Maintenance window — this computer’s local time (24-hour HH:MM)'));start=QLineEdit(cfg['start']);end=QLineEdit(cfg['end']);l.addWidget(QLabel('Start'));l.addWidget(start);l.addWidget(QLabel('End'));l.addWidget(end)
            note=QLabel('The app must be open and idle for 5 minutes. Leave Admin on Dashboard / Library Services or Kiosk on Home. Active members, dialogs and database work postpone installation. The app restarts after the verified update is prepared. Enable automatic downloading in Update settings.');note.setWordWrap(True);l.addWidget(note)
            def save():
                try:write({'enabled':enabled.isChecked(),'start':start.text().strip(),'end':end.text().strip()})
                except (OSError,ValueError) as exc:QMessageBox.warning(d,'Schedule not saved',str(exc));return
                d.accept()
            button(l,'Save schedule',save);button(l,'Close',d.reject);d.exec()
    return Scheduler()
