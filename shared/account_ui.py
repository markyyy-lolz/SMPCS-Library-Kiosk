"""Light blue account and library service dialogs."""
from PyQt6.QtCore import Qt,QTimer,QRegularExpression
from PyQt6.QtGui import QRegularExpressionValidator,QColor
from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QLabel,QPushButton,QComboBox,QCheckBox,QTableWidget,QTableWidgetItem,QHeaderView,QMessageBox,QFileDialog,QApplication,QWidget,QStackedWidget,QTabWidget,QScrollArea,QFrame,QGridLayout)
from shared.services import login,account,save_backup,Outbox
from shared.config import APP_DIR

STYLE='QDialog{background:#F4F8FF;} QLabel,QCheckBox{color:#193657;font-size:14px;} QLineEdit,QComboBox,QTableWidget{background:white;color:#193657;padding:8px;} QPushButton{background:#2463C7;color:white;border-radius:8px;padding:11px;} QPushButton:disabled{background:#9AAEC9;} QTabWidget::pane{background:white;border:1px solid #DCE6F3;border-radius:8px;} QTabBar::tab{background:#E7EFFB;color:#23456C;padding:12px 20px;} QTabBar::tab:selected{background:#2463C7;color:white;} QHeaderView::section{background:#E8EFF8;color:#264B73;padding:10px;border:0;} QTableWidget{alternate-background-color:#F2F6FC;gridline-color:#E2EAF5;} QPushButton[secondary=true]{background:#E3ECF9;color:#23456C;}'

def dialog(host,title):
    d=QDialog(host);d.setWindowTitle(title);d.resize(820,580);d.setStyleSheet(STYLE);lay=QVBoxLayout(d);lay.setContentsMargins(22,20,22,20);lay.setSpacing(12);return d,lay

def button(lay,text,fn):
    b=QPushButton(text);b.clicked.connect(fn);lay.addWidget(b);return b

def table(lay,headers):
    t=QTableWidget(0,len(headers));t.setHorizontalHeaderLabels(headers);t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows);t.setSelectionMode(QTableWidget.SelectionMode.SingleSelection);t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);t.verticalHeader().hide();lay.addWidget(t,1);return t

def fill(t,rows,keys):
    t.setRowCount(len(rows))
    for i,r in enumerate(rows):
        for j,k in enumerate(keys):
            item=QTableWidgetItem(str(r.get(k) if r.get(k) is not None else ''));item.setData(Qt.ItemDataRole.UserRole,r);t.setItem(i,j,item)

def selected(t):
    i=t.currentRow();return t.item(i,0).data(Qt.ItemDataRole.UserRole) if i>=0 and t.item(i,0) else None

def task(host,d,fn,ok):
    d.setEnabled(False)
    def success(value):
        from PyQt6 import sip
        if sip.isdeleted(d):return
        d.setEnabled(True)
        if d.isVisible():ok(value)
    def fail(exc):
        from PyQt6 import sip
        if sip.isdeleted(d):return
        d.setEnabled(True)
        if d.isVisible():
            box=QMessageBox(QMessageBox.Icon.Warning,'Could not complete',str(exc),QMessageBox.StandardButton.Ok,d)
            from shared.suite import add_copy_error
            add_copy_error(box,str(exc));box.exec()
    if hasattr(host,'load'):host.load(fn,success,fail)
    else:host.run_async(fn,success,fail)

def edit_staff(host,refresh,row=None):
    row=row or {};d,lay=dialog(host,'Staff account');d.resize(620,430);form=QFormLayout();lay.addLayout(form);fields={}
    for key,label in [('username','Username'),('full_name','Full name'),('password','New password (blank keeps current)')]:
        w=QLineEdit(str(row.get(key,'')));form.addRow(label,w);fields[key]=w
    fields['password'].setEchoMode(QLineEdit.EchoMode.Password)
    role=QComboBox();role.addItems(['assistant','librarian','admin']);role.setCurrentText(row.get('role','librarian'));form.addRow('Role',role)
    active=QCheckBox('Active');active.setChecked(row.get('active',True));form.addRow(active)
    lay.addWidget(QLabel('Passwords: 10+ characters, maximum 72 UTF-8 bytes.'))
    def save():
        if not active.isChecked() and QMessageBox.question(d,'Disable staff account','Disable access for this staff account?')!=QMessageBox.StandardButton.Yes:return
        data={k:w.text() for k,w in fields.items()};data.update(id=row.get('id'),role=role.currentText(),active=active.isChecked())
        task(host,d,lambda:account(host.api,host.user,'staff_save',data),lambda _:(d.accept(),refresh()))
    lay.addStretch();actions=QHBoxLayout();actions.addStretch();lay.addLayout(actions);button(actions,'Cancel',d.reject);button(actions,'Save account',save);d.exec()

def staff_accounts(host):
    d,lay=dialog(host,'Staff account management');lay.addWidget(QLabel('Administrators manage staff accounts and access.'))
    search=QLineEdit();search.setPlaceholderText('Search username, name or role…');lay.addWidget(search)
    t=table(lay,['Username','Full name','Role','Active']);cache=[]
    def filtered():fill(t,[r for r in cache if search.text().casefold() in ' '.join(str(v) for v in r.values()).casefold()],['username','full_name','role','active'])
    def loaded(rows):cache[:]=rows;filtered()
    def refresh():task(host,d,lambda:account(host.api,host.user,'staff_list'),loaded)
    search.textChanged.connect(filtered)
    actions=QHBoxLayout();lay.addLayout(actions)
    button(actions,'New staff account',lambda:edit_staff(host,refresh))
    button(actions,'Edit / reset password',lambda:edit_staff(host,refresh,selected(t)) if selected(t) else None)
    button(actions,'Refresh',refresh);button(actions,'Close',d.reject);QTimer.singleShot(0,refresh);d.exec()

def member_access(host):
    from admin.main import selected_row
    row=selected_row(host.mtable)
    if not row:QMessageBox.information(host,'Member access','Select a member first.');return
    d,lay=dialog(host,'Member account access');d.resize(620,400);lay.addWidget(QLabel(str(row.get('full_name',''))))
    active=QCheckBox('Account active');active.setChecked(row.get('active',True));lay.addWidget(active)
    pin=QLineEdit();pin.setEchoMode(QLineEdit.EchoMode.Password);pin.setPlaceholderText('New 6–12 digit PIN; blank keeps current');lay.addWidget(pin)
    confirm=QLineEdit();confirm.setEchoMode(QLineEdit.EchoMode.Password);confirm.setPlaceholderText('Repeat new PIN');lay.addWidget(confirm)
    lay.addWidget(QLabel('RFID + PIN opens My Account. Disabling blocks new kiosk access.'))
    def save():
        if pin.text()!=confirm.text():QMessageBox.warning(d,'PIN','PINs do not match.');return
        if not active.isChecked() and QMessageBox.question(d,'Deactivate account','Block this member from new kiosk access?')!=QMessageBox.StandardButton.Yes:return
        data={'id':row['id'],'active':active.isChecked(),'pin':pin.text()}
        task(host,d,lambda:account(host.api,host.user,'member_access',data),lambda _:(d.accept(),host.refresh_members()))
    lay.addStretch();actions=QHBoxLayout();actions.addStretch();lay.addLayout(actions);button(actions,'Cancel',d.reject);button(actions,'Save access',save);d.exec()

def return_requests(host):
    d,lay=dialog(host,'Book return confirmation');lay.addWidget(QLabel('Confirm only after receiving the physical book.'))
    t=table(lay,['Member','Book','Requested','Station'])
    def refresh():task(host,d,lambda:account(host.api,host.user,'return_list'),lambda rows:fill(t,rows,['full_name','title','created_at','station_code']))
    def review(approve):
        row=selected(t)
        if not row:return
        if QMessageBox.question(d,'Confirm return','Book received — approve return?' if approve else 'Reject this return request?')!=QMessageBox.StandardButton.Yes:return
        task(host,d,lambda:account(host.api,host.user,'return_review',{'id':row['id'],'approve':approve}),lambda _:refresh())
    actions=QHBoxLayout();lay.addLayout(actions)
    button(actions,'Book received — approve',lambda:review(True));button(actions,'Reject',lambda:review(False));button(actions,'Refresh',refresh);button(actions,'Close',d.reject);QTimer.singleShot(0,refresh);d.exec()

def backup_dialog(host):
    from shared.suite_ui import backups
    return backups(host)

ACCOUNT_STYLE = STYLE + """
QDialog{background:#F1F5FA;}
QFrame#profileBanner{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #103F86,stop:1 #2677CD);border-radius:16px;}
QTabWidget::pane{background:white;border:none;border-radius:14px;}
QTabBar::tab{background:transparent;color:#60758D;padding:13px 22px;border-bottom:3px solid transparent;}
QTabBar::tab:selected{background:transparent;color:#195BB2;border-bottom:3px solid #2677CD;font-weight:700;}
QTableWidget{background:white;border:none;padding:0;selection-background-color:#EDF4FF;selection-color:#173D68;}
QHeaderView::section{background:#F4F7FB;color:#71849B;padding:10px 14px;border:none;font-size:11px;font-weight:600;}
QTableWidget::item{padding:0 12px;border-bottom:1px solid #EDF1F6;color:#254160;}
QPushButton{background:#2467C5;border-radius:10px;padding:11px 17px;}
QLineEdit,QComboBox{border:1px solid #DEE6F0;border-radius:10px;padding:10px;background:#FAFCFF;}
QComboBox::drop-down{border:none;width:26px;}
QScrollBar:vertical{background:#F4F7FB;width:8px;margin:0;border-radius:4px;}
QScrollBar::handle:vertical{background:#C6D5E7;min-height:28px;border-radius:4px;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}
"""

class AccountDialog(QDialog):
    """Touch-friendly account pages with a separate security form."""
    def __init__(self,host):
        super().__init__(host)
        self.host=host;self.user={};self.loans=[];self.rfid=host.member.get('rfid_uid','')
        self.setWindowTitle('My library account');self.setStyleSheet(ACCOUNT_STYLE)
        size=QApplication.primaryScreen().availableGeometry()
        self.resize(min(940,size.width()-40),min(700,size.height()-60))
        root=QVBoxLayout(self);root.setContentsMargins(22,18,22,18);root.setSpacing(12)
        banner=QFrame();banner.setObjectName('profileBanner');header=QHBoxLayout(banner);header.setContentsMargins(22,18,22,18);header.setSpacing(16)
        self.avatar=QLabel('ID');self.avatar.setFixedSize(58,58);self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter);self.avatar.setStyleSheet('background:#4785CE;color:white;border-radius:18px;font-size:23px;font-weight:700;');header.addWidget(self.avatar)
        details=QVBoxLayout();details.setSpacing(5)
        caption=QLabel('MY LIBRARY');caption.setStyleSheet('color:#BDD9FA;font-size:10px;font-weight:700;letter-spacing:2px;');details.addWidget(caption)
        self.heading=QLabel('My library account');self.heading.setTextFormat(Qt.TextFormat.PlainText);self.heading.setWordWrap(True);self.heading.setStyleSheet('font-size:23px;font-weight:700;color:white;');details.addWidget(self.heading)
        self.identity=QLabel('Verify your school card with your library PIN.');self.identity.setWordWrap(True);self.identity.setTextFormat(Qt.TextFormat.PlainText);self.identity.setStyleSheet('color:#D2E6FF;font-size:12px;');details.addWidget(self.identity);header.addLayout(details,1);root.addWidget(banner)
        self.pages=QStackedWidget();root.addWidget(self.pages,1)
        signin_page=QWidget();signin_lay=QVBoxLayout(signin_page);signin_lay.setContentsMargins(0,8,0,8);signin_lay.setSpacing(12)
        signin_lay.addStretch()
        entry=QWidget();entry.setMaximumWidth(370);entry_lay=QVBoxLayout(entry);entry_lay.setContentsMargins(0,0,0,0);entry_lay.setSpacing(10)
        entry_lay.addWidget(QLabel('LIBRARY PIN'))
        self.pin=self.pin_field('Enter 6–12 digit PIN');entry_lay.addWidget(self.pin)
        self.login_focus=[self.pin];entry_lay.addWidget(self.keypad(self.login_focus))
        button(entry_lay,'Sign in',self.sign_in)
        helper=QLabel('No PIN yet? Ask the librarian to set one.');helper.setWordWrap(True);entry_lay.addWidget(helper)
        signin_lay.addWidget(entry,0,Qt.AlignmentFlag.AlignHCenter);signin_lay.addStretch();self.pages.addWidget(signin_page)
        self.tabs=QTabWidget();self.pages.addWidget(self.tabs)
        history=QWidget();hist=QVBoxLayout(history);hist.setContentsMargins(14,14,14,14);hist.setSpacing(10)
        cards=QHBoxLayout();cards.setSpacing(12);self.stat_values=[]
        for title,color in [('ON LOAN','#2467C5'),('OVERDUE','#C96628'),('RECENT RECORDS','#526C89')]:
            card=QFrame();card.setStyleSheet('QFrame{background:#F5F8FD;border-radius:12px;}');col=QVBoxLayout(card);col.setContentsMargins(16,12,16,12);col.setSpacing(3)
            value=QLabel('—');value.setStyleSheet(f'color:{color};font-size:27px;font-weight:700;');label=QLabel(title);label.setStyleSheet('color:#788AA0;font-size:10px;font-weight:700;letter-spacing:.8px;');col.addWidget(value);col.addWidget(label);cards.addWidget(card,1);self.stat_values.append(value)
        hist.addLayout(cards)
        self.summary=QLabel('Loading borrowing history…');self.summary.setStyleSheet('font-size:12px;color:#647C97;');hist.addWidget(self.summary)
        filters=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText('Search book title…');filters.addWidget(self.search,1)
        self.filter=QComboBox();self.filter.addItems(['All loans','Currently borrowed','Overdue','Returned','Cancelled']);filters.addWidget(self.filter)
        button(filters,'Refresh',self.refresh_profile);hist.addLayout(filters)
        self.history=table(hist,['Book','Status','Due date','Overdue']);hist.setStretchFactor(self.history,1)
        self.history.setShowGrid(False);self.history.setAlternatingRowColors(False)
        self.history.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter)
        self.history.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.history.verticalHeader().setDefaultSectionSize(56)
        self.history.setWordWrap(False)
        self.result_count=QLabel('');hist.addWidget(self.result_count)
        self.tabs.addTab(history,'Borrowing history')
        security=QWidget();sec=QVBoxLayout(security);sec.setContentsMargins(18,18,18,18);sec.setSpacing(12)
        description=QLabel('Change your library PIN. Use 6–12 digits and keep it private.');description.setWordWrap(True);sec.addWidget(description)
        row=QHBoxLayout();row.setSpacing(24);fields=QVBoxLayout();fields.setSpacing(8)
        self.current=self.pin_field('Current PIN');self.new=self.pin_field('New PIN');self.repeat=self.pin_field('Repeat new PIN')
        for label,w in [('Current PIN',self.current),('New PIN',self.new),('Confirm new PIN',self.repeat)]:fields.addWidget(QLabel(label));fields.addWidget(w)
        fields.addStretch();row.addLayout(fields,1)
        self.security_focus=[self.current];row.addWidget(self.keypad(self.security_focus),0,Qt.AlignmentFlag.AlignTop);sec.addLayout(row)
        actions=QHBoxLayout();actions.addStretch();button(actions,'Save new PIN',self.change_pin);sec.addLayout(actions)
        sec.addStretch();note=QLabel('For name, grade, section or RFID corrections, please contact the librarian.');note.setWordWrap(True);sec.addWidget(note)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.Shape.NoFrame);scroll.setWidget(security);self.tabs.addTab(scroll,'Change PIN')
        self.search.textChanged.connect(self.filter_history);self.filter.currentIndexChanged.connect(self.filter_history)
        self.tabs.currentChanged.connect(self.tab_changed)
        footer=QHBoxLayout();timeout=QLabel('Automatically signs out after 2 minutes.');timeout.setWordWrap(True);timeout.setStyleSheet('color:#61738A;font-size:12px;');footer.addWidget(timeout,1)
        self.close_button=button(footer,'Cancel',self.reject);self.close_button.setProperty('secondary',True);root.addLayout(footer)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.reject);self.timer.start(120000)
        QApplication.instance().focusChanged.connect(self.track_focus)
        self.finished.connect(self.cleanup)
        from shared.kiosk_suite import attach_account, AccountTimeout
        attach_account(self)
        continue_button=button(footer,'Continue session',lambda:None)
        self.privacy_timeout=AccountTimeout(self,timeout,continue_button)

    def pin_field(self,placeholder):
        w=QLineEdit();w.setPlaceholderText(placeholder);w.setEchoMode(QLineEdit.EchoMode.Password);w.setMaxLength(12);w.setMinimumHeight(40)
        w.setValidator(QRegularExpressionValidator(QRegularExpression('[0-9]{0,12}'),w));return w

    def keypad(self,focus):
        box=QWidget();grid=QGridLayout(box);grid.setContentsMargins(0,0,0,0);grid.setSpacing(7)
        for index,key in enumerate(['1','2','3','4','5','6','7','8','9','Clear','0','⌫']):
            b=QPushButton(key);b.setMinimumSize(66,44);b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            def press(_=False,value=key):
                field=focus[0]
                if value=='Clear':field.clear()
                elif value=='⌫':field.backspace()
                else:field.insert(value)
            b.clicked.connect(press);grid.addWidget(b,index//3,index%3)
        return box

    def track_focus(self,old,now):
        if now in (self.current,self.new,self.repeat):self.security_focus[0]=now

    def tab_changed(self,index):
        for field in (self.current,self.new,self.repeat):field.clear()
        if index==1:self.current.setFocus()

    def sign_in(self):
        secret=self.pin.text()
        task(self.host,self,lambda:login(self.host.api,'member',self.rfid,secret),self.signed)

    def signed(self,result):
        self.user.update(result);self.pin.clear();self.pages.setCurrentIndex(1);self.close_button.setText('Sign out');self.refresh_profile()

    def refresh_profile(self):
        if self.user:task(self.host,self,lambda:account(self.host.api,self.user,'profile'),self.show_profile)

    def show_profile(self,data):
        from datetime import datetime,timezone,timedelta
        m=data['member'];self.loans=[dict(r) for r in data['loans']]
        self.heading.setText(str(m.get('full_name') or 'My library account'))
        self.avatar.setText(''.join(p[:1] for p in str(m.get('full_name') or 'Library Member').split()[:2]).upper())
        self.identity.setText('Member '+str(m.get('member_no') or m.get('student_id') or '—')+'  •  '+' / '.join(str(m.get(k) or '—') for k in ('grade_level','section')))
        for row in self.loans:
            row['status_label']=str(row.get('status') or '').replace('_',' ').title()
            from shared.suite import due_hint
            row['overdue_label']=due_hint(row.get('due_at'),row.get('status'))
            try:row['due_label']=datetime.fromisoformat(row['due_at'].replace('Z','+00:00')).astimezone(timezone(timedelta(hours=8))).strftime('%b %d, %Y')
            except (ValueError,TypeError,KeyError):row['due_label']=str(row.get('due_at') or '—')
        borrowed=sum(r.get('status')=='borrowed' for r in self.loans);overdue=sum(bool(r.get('overdue')) for r in self.loans)
        for label,value in zip(self.stat_values,(borrowed,overdue,len(self.loans))):label.setText(str(value))
        self.summary.setText('Please return overdue books to the librarian.' if overdue else 'Your recent borrowing activity')
        self.filter_history()

    def filter_history(self,*_):
        query=self.search.text().strip().casefold();choice=self.filter.currentText()
        rows=[r for r in self.loans if query in str(r.get('title','')).casefold() and (choice=='All loans' or choice=='Overdue' and r.get('overdue') or r.get('status')=={'Currently borrowed':'borrowed','Returned':'returned','Cancelled':'cancelled'}.get(choice,'__none__'))]
        fill(self.history,rows,['title','status_label','due_label','overdue_label'])
        palette={'borrowed':('#E9F1FF','#2467C5'),'returned':('#E7F5EF','#287D59'),'cancelled':('#F0F2F5','#768599'),'lost':('#FDECEC','#B64848')}
        for i,row in enumerate(rows):
            bg,fg=palette.get(row.get('status'),('#F0F2F5','#60768E'))
            self.history.item(i,1).setText('')
            badge=QLabel(row['status_label']);badge.setFixedHeight(28);badge.setToolTip(row['status_label']);badge.setAlignment(Qt.AlignmentFlag.AlignCenter);badge.setStyleSheet(f'background:{bg};color:{fg};border-radius:9px;padding:5px 9px;font-size:11px;font-weight:600;')
            cell=QWidget();line=QHBoxLayout(cell);line.setContentsMargins(8,0,8,0);line.addWidget(badge);line.addStretch();self.history.setCellWidget(i,1,cell)
            if row.get('overdue'):self.history.item(i,3).setForeground(QColor('#BA5C28'))
            for c in range(4):self.history.item(i,c).setToolTip(self.history.item(i,c).text())
            self.history.setRowHeight(i,56)
        self.balance_columns()
        self.result_count.setText(f'{len(rows)} records shown • Most recent 200 loans maximum' if rows else 'No borrowing records match this view.')

    def balance_columns(self):
        width=max(self.history.viewport().width(),480)
        proportions=(.43,.20,.22,.15)
        for column,fraction in enumerate(proportions):self.history.setColumnWidth(column,int(width*fraction))

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'history'):QTimer.singleShot(0,self.balance_columns)

    def change_pin(self):
        if len(self.new.text())<6:QMessageBox.warning(self,'PIN','Use 6–12 digits for your new PIN.');return
        if self.new.text()!=self.repeat.text():QMessageBox.warning(self,'PIN','PINs do not match.');return
        data={'current_pin':self.current.text(),'pin':self.new.text()}
        def saved(_):
            for field in (self.current,self.new,self.repeat):field.clear()
            QMessageBox.information(self,'PIN changed','Your new PIN is ready.')
        task(self.host,self,lambda:account(self.host.api,self.user,'change_pin',data),saved)

    def cleanup(self,*_):
        self.timer.stop();QApplication.instance().focusChanged.disconnect(self.track_focus)
        for field in (self.pin,self.current,self.new,self.repeat):field.clear()
        if self.user:
            user=dict(self.user);self.user.clear()
            self.host.run_async(lambda:account(self.host.api,user,'logout'),lambda _:None,lambda _:None)


def kiosk_account(host):
    if not host.member or host.busy:return
    host.busy=True;host.mode='account';host.rfid.buffer='';host.rfid.timer.stop();QApplication.instance().removeEventFilter(host.rfid)
    d=AccountDialog(host)
    try:d.exec()
    finally:
        host.rfid.buffer='';QApplication.instance().installEventFilter(host.rfid);host.busy=False;host.reset();d.deleteLater()

def outbox_dialog(host):
    import json
    from pathlib import Path
    d,lay=dialog(host,'Attendance sync queue');label=QLabel('Scans stay here until acknowledged by the server. Errors require librarian review.\nAn exported copy is for review only; it does not mark records as synced.');label.setWordWrap(True);lay.addWidget(label)
    t=table(lay,['Card','Scanned at (UTC)','Error'])
    def refresh():fill(t,host.outbox.rows(host.cfg['STATION_CODE']),['rfid','scanned_at','error'])
    def export():
        path,_=QFileDialog.getSaveFileName(d,'Export pending scans','pending-attendance.json','JSON (*.json)')
        if path:
            try:Path(path).write_text(json.dumps(host.outbox.rows(host.cfg['STATION_CODE']),indent=2),encoding='utf-8')
            except OSError as exc:QMessageBox.warning(d,'Export failed',str(exc))
    actions=QHBoxLayout();lay.addLayout(actions)
    button(actions,'Retry sync',lambda:task(host,d,lambda:host.outbox.sync(host.api,host.cfg),lambda _:refresh()))
    button(actions,'Export for review',export);button(actions,'Close',d.reject);refresh();d.exec()
