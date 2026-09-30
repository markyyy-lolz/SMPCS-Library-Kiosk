"""Member requests, catalog and kiosk session/status controls."""
import base64
import time
from PyQt6.QtCore import QObject,QTimer,Qt,QEvent
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLineEdit,QLabel,QPushButton,QInputDialog,QMessageBox,QPlainTextEdit
from shared.account_ui import table,fill,selected,task,button
from shared.suite import suite,station_suite


def attach_account(dialog):
    host=dialog.host
    page=QWidget();layout=QVBoxLayout(page);search=QLineEdit();search.setPlaceholderText('Search title or author…');layout.addWidget(search)
    row=QHBoxLayout();cover=QLabel('Select a book');cover.setFixedSize(110,145);cover.setAlignment(Qt.AlignmentFlag.AlignCenter);row.addWidget(cover)
    details=QLabel('Shelf and availability appear here.');details.setWordWrap(True);row.addWidget(details,1);layout.addLayout(row)
    books=table(layout,['Title','Author','Shelf','Available']);books.setMinimumHeight(90)
    def api(action,data,ok):task(host,dialog,lambda:suite(host.api,dialog.user,action,data),ok)
    def catalog():
        if dialog.user:api('catalog',{'search':search.text()},lambda rows:fill(books,rows,['title','author','shelf','available_copies']))
    def chosen():
        r=selected(books)
        if not r:return
        cover.clear();cover.setText('No cover')
        if r.get('cover_data'):
            pix=QPixmap();pix.loadFromData(base64.b64decode(r['cover_data']))
            if not pix.isNull():cover.setPixmap(pix.scaled(110,145,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        details.setText(f"{r['title']}\nShelf: {r.get('shelf') or 'Ask librarian'}\nAvailable: {r['available_copies']} of {r['total_copies']}")
    def reserve():
        r=selected(books)
        if not r:return
        if QMessageBox.question(dialog,'Reserve book','Join the waiting list for this book?')==QMessageBox.StandardButton.Yes:
            api('request',{'kind':'reservation','book_id':r['id']},lambda _:(QMessageBox.information(dialog,'Reservation sent','The librarian can see your queue position.'),load_requests()))
    actions=QHBoxLayout();layout.addLayout(actions);button(actions,'Search',catalog);button(actions,'Reserve selected',reserve);books.itemSelectionChanged.connect(chosen);dialog.tabs.addTab(page,'Find books')
    requests=QWidget();req_lay=QVBoxLayout(requests);req_table=table(req_lay,['Type','Book','Status','Queue']);note=QPlainTextEdit();note.setReadOnly(True);note.setMaximumHeight(90);req_lay.addWidget(note)
    def load_requests():
        if dialog.user:api('my_requests',{},lambda rows:fill(req_table,rows,['kind','title','status','queue_position']))
    def details_req():
        r=selected(req_table);note.setPlainText('\n'.join(k.replace('_',' ').title()+': '+str(v) for k,v in (r or {}).get('data',{}).items() if k not in ('book_id','loan_id')))
    req_table.itemSelectionChanged.connect(details_req)
    def cancel():
        r=selected(req_table)
        if r and QMessageBox.question(dialog,'Cancel request','Cancel this pending request?')==QMessageBox.StandardButton.Yes:api('cancel_request',{'id':r['id']},lambda _:load_requests())
    def renew():
        r=selected(dialog.history)
        if not r or r.get('status')!='borrowed':QMessageBox.information(dialog,'Renew borrowing','Select a currently borrowed book in Borrowing history first.');return
        days,ok=QInputDialog.getInt(dialog,'Renew borrowing','Additional days requested:',7,1,30)
        if ok:api('request',{'kind':'renewal','loan_id':r['id'],'days':days},lambda _:(QMessageBox.information(dialog,'Renewal requested','Your due date changes only after librarian approval.'),load_requests()))
    def feedback():
        text,ok=QInputDialog.getMultiLineText(dialog,'Feedback / problem','Describe your concern (3–2000 characters):')
        if ok:api('request',{'kind':'feedback','message':text},lambda _:(QMessageBox.information(dialog,'Sent','Your concern was sent to the librarian.'),load_requests()))
    actions=QHBoxLayout();req_lay.addLayout(actions);button(actions,'Refresh',load_requests);button(actions,'Cancel request',cancel);button(actions,'Feedback',feedback);dialog.tabs.addTab(requests,'My requests')
    dialog.tabs.widget(0).layout().addWidget(QPushButton('Request renewal',clicked=renew))
    def changed(index):
        if index==2:catalog()
        elif index==3:load_requests()
    dialog.tabs.currentChanged.connect(changed)


class AccountTimeout(QObject):
    def __init__(self,dialog,label,continue_button):
        super().__init__(dialog);self.dialog=dialog;self.label=label;self.button=continue_button;self.deadline=time.monotonic()+120
        dialog.timer.stop();self.timer=QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(1000);self.button.clicked.connect(self.extend);dialog.finished.connect(self.timer.stop);self.tick()
    def tick(self):
        left=max(0,int(self.deadline-time.monotonic()));self.label.setText(f'Privacy sign-out in {left}s');self.button.setVisible(left<=30)
        if left<=0:self.dialog.reject()
    def extend(self):
        if not self.dialog.user:self.deadline=time.monotonic()+120;self.tick();return
        task(self.dialog.host,self.dialog,lambda:suite(self.dialog.host.api,self.dialog.user,'continue_session'),self.extended)
    def extended(self,_):self.deadline=time.monotonic()+120;self.tick()


class KioskStatus(QObject):
    def __init__(self,host):
        super().__init__(host);self.host=host;self.busy=False;self.maintenance=False;self.member_since=None
        self.banner=QLabel();self.banner.setWordWrap(True);self.banner.setTextFormat(Qt.TextFormat.PlainText);self.banner.setStyleSheet('background:#DBEAFE;color:#174476;padding:10px 18px;font-size:13px;');self.banner.hide();host.main_layout.insertWidget(1,self.banner)
        self.timer=QTimer(self);self.timer.timeout.connect(self.refresh);self.timer.start(30000);QTimer.singleShot(1000,self.refresh)
        self.privacy=QTimer(self);self.privacy.timeout.connect(self.tick);self.privacy.start(1000)
        self.continue_button=QPushButton('Continue session');host.statusBar().addPermanentWidget(self.continue_button);self.continue_button.hide();self.continue_button.clicked.connect(lambda:setattr(self,'member_since',time.monotonic()))
    def refresh(self):
        if self.busy:return
        self.busy=True
        def ok(data):
            self.busy=False;self.maintenance=bool(data.get('maintenance'));self.message=data.get('message') or 'Please return later.'
            lines=([self.message] if self.maintenance else [])+[str(r['title'])+': '+str(r['message']) for r in data.get('announcements',[])]
            self.banner.setText('\n'.join(lines));self.banner.setVisible(bool(lines))
        def fail(exc):self.busy=False
        self.host.run_async(lambda:station_suite(self.host,'status'),ok,fail)
    def tick(self):
        host=self.host
        # Account dialog provides its own countdown. Do not interrupt an in-flight transaction.
        if not host.member or host.mode=='account':self.member_since=None;self.continue_button.hide();return
        if self.member_since is None:self.member_since=time.monotonic()
        left=120-int(time.monotonic()-self.member_since)
        self.continue_button.setVisible(left<=30)
        if left<=30:self.continue_button.setText(f'Continue session ({max(0,left)}s)')
        if left<=0 and not host.busy:host.reset();self.member_since=None


def maintenance_block(host):
    status=getattr(host,'suite_status',None)
    if status and status.maintenance:
        QMessageBox.information(host,'Library maintenance',status.message);return True
    return False
