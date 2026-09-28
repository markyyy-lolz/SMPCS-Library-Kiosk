"""Light blue account and library service dialogs."""
from PyQt6.QtCore import Qt,QTimer
from PyQt6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QLabel,QPushButton,QComboBox,QCheckBox,QTableWidget,QTableWidgetItem,QHeaderView,QMessageBox,QFileDialog,QApplication)
from shared.services import login,account,save_backup,Outbox
from shared.config import APP_DIR

STYLE='QDialog{background:#F4F8FF;} QLabel,QCheckBox{color:#193657;font-size:14px;} QLineEdit,QComboBox,QTableWidget{background:white;color:#193657;padding:8px;} QPushButton{background:#2463C7;color:white;border-radius:8px;padding:11px;} QPushButton:disabled{background:#9AAEC9;}'

def dialog(host,title):
    d=QDialog(host);d.setWindowTitle(title);d.resize(820,620);d.setStyleSheet(STYLE);lay=QVBoxLayout(d);return d,lay

def button(lay,text,fn):
    b=QPushButton(text);b.clicked.connect(fn);lay.addWidget(b);return b

def table(lay,headers):
    t=QTableWidget(0,len(headers));t.setHorizontalHeaderLabels(headers);t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows);t.setSelectionMode(QTableWidget.SelectionMode.SingleSelection);t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);lay.addWidget(t);return t

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
        d.setEnabled(True)
        if d.isVisible():ok(value)
    def fail(exc):
        d.setEnabled(True)
        if d.isVisible():QMessageBox.warning(d,'Could not complete',str(exc))
    if hasattr(host,'load'):host.load(fn,success,fail)
    else:host.run_async(fn,success,fail)

def edit_staff(host,refresh,row=None):
    row=row or {};d,lay=dialog(host,'Staff account');form=QFormLayout();lay.addLayout(form);fields={}
    for key,label in [('username','Username'),('full_name','Full name'),('password','New password (blank keeps current)')]:
        w=QLineEdit(str(row.get(key,'')));form.addRow(label,w);fields[key]=w
    fields['password'].setEchoMode(QLineEdit.EchoMode.Password)
    role=QComboBox();role.addItems(['librarian','admin']);role.setCurrentText(row.get('role','librarian'));form.addRow('Role',role)
    active=QCheckBox('Active');active.setChecked(row.get('active',True));form.addRow(active)
    lay.addWidget(QLabel('Passwords: 10+ characters, maximum 72 UTF-8 bytes.'))
    def save():
        data={k:w.text() for k,w in fields.items()};data.update(id=row.get('id'),role=role.currentText(),active=active.isChecked())
        task(host,d,lambda:account(host.api,host.user,'staff_save',data),lambda _:(d.accept(),refresh()))
    button(lay,'Save account',save);button(lay,'Cancel',d.reject);d.exec()

def staff_accounts(host):
    d,lay=dialog(host,'Staff account management');lay.addWidget(QLabel('Administrators manage staff accounts and access.'))
    t=table(lay,['Username','Full name','Role','Active'])
    def refresh():task(host,d,lambda:account(host.api,host.user,'staff_list'),lambda rows:fill(t,rows,['username','full_name','role','active']))
    button(lay,'New staff account',lambda:edit_staff(host,refresh))
    button(lay,'Edit selected / reset password',lambda:edit_staff(host,refresh,selected(t)) if selected(t) else None)
    button(lay,'Refresh',refresh);button(lay,'Close',d.reject);QTimer.singleShot(0,refresh);d.exec()

def member_access(host):
    from admin.main import selected_row
    row=selected_row(host.mtable)
    if not row:QMessageBox.information(host,'Member access','Select a member first.');return
    d,lay=dialog(host,'Member account access');lay.addWidget(QLabel(str(row.get('full_name',''))))
    active=QCheckBox('Account active');active.setChecked(row.get('active',True));lay.addWidget(active)
    pin=QLineEdit();pin.setEchoMode(QLineEdit.EchoMode.Password);pin.setPlaceholderText('New 6–12 digit PIN; blank keeps current');lay.addWidget(pin)
    confirm=QLineEdit();confirm.setEchoMode(QLineEdit.EchoMode.Password);confirm.setPlaceholderText('Repeat new PIN');lay.addWidget(confirm)
    lay.addWidget(QLabel('RFID + PIN opens My Account. Disabling blocks new kiosk access.'))
    def save():
        if pin.text()!=confirm.text():QMessageBox.warning(d,'PIN','PINs do not match.');return
        data={'id':row['id'],'active':active.isChecked(),'pin':pin.text()}
        task(host,d,lambda:account(host.api,host.user,'member_access',data),lambda _:(d.accept(),host.refresh_members()))
    button(lay,'Save access',save);button(lay,'Cancel',d.reject);d.exec()

def return_requests(host):
    d,lay=dialog(host,'Book return confirmation');lay.addWidget(QLabel('Confirm only after receiving the physical book.'))
    t=table(lay,['Member','Book','Requested','Station'])
    def refresh():task(host,d,lambda:account(host.api,host.user,'return_list'),lambda rows:fill(t,rows,['full_name','title','created_at','station_code']))
    def review(approve):
        row=selected(t)
        if not row:return
        if QMessageBox.question(d,'Confirm return','Book received — approve return?' if approve else 'Reject this return request?')!=QMessageBox.StandardButton.Yes:return
        task(host,d,lambda:account(host.api,host.user,'return_review',{'id':row['id'],'approve':approve}),lambda _:refresh())
    button(lay,'Book received — approve',lambda:review(True));button(lay,'Reject request',lambda:review(False));button(lay,'Refresh',refresh);button(lay,'Close',d.reject);QTimer.singleShot(0,refresh);d.exec()

def backup_dialog(host):
    d,lay=dialog(host,'Operational backups');label=QLabel('Daily backup runs while an administrator is signed in. Keeps the latest 7 snapshots.\nIncludes members, books, loans, attendance and return requests.\nPasswords, PINs, station secrets and database schema are excluded.\nRecovery requires a database administrator; this is not a full database backup.');label.setWordWrap(True);lay.addWidget(label)
    lay.addWidget(QLabel('Automatic backup folder: '+str(APP_DIR/'backups')))
    def save():
        folder=QFileDialog.getExistingDirectory(d,'Choose backup folder')
        if folder:task(host,d,lambda:save_backup(host.api,host.user,folder),lambda path:QMessageBox.information(d,'Backup saved',path))
    button(lay,'Create backup in folder…',save);button(lay,'Close',d.reject);d.exec()

def kiosk_account(host):
    if not host.member or host.busy:return
    host.busy=True;host.mode='account';host.rfid.buffer='';host.rfid.timer.stop();QApplication.instance().removeEventFilter(host.rfid)
    rfid=host.member.get('rfid_uid','');user={};d,lay=dialog(host,'My library account');d.resize(880,640)
    name=QLabel('Enter your PIN. Ask the librarian to set one if you do not have one.');name.setWordWrap(True);lay.addWidget(name)
    pin=QLineEdit();pin.setEchoMode(QLineEdit.EchoMode.Password);pin.setPlaceholderText('Library PIN');lay.addWidget(pin)
    pad=QHBoxLayout();lay.addLayout(pad)
    focus=[pin]
    def type_digit(n):focus[0].insert(n)
    for digit in '1234567890':
        b=button(pad,digit,lambda _=False,n=digit:type_digit(n));b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    b=button(pad,'⌫',lambda:focus[0].backspace());b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    t=table(lay,['Book','Status','Due date','Overdue'])
    current=QLineEdit();current.setEchoMode(QLineEdit.EchoMode.Password);current.setPlaceholderText('Current PIN');lay.addWidget(current);current.hide()
    new=QLineEdit();new.setEchoMode(QLineEdit.EchoMode.Password);new.setPlaceholderText('New PIN: 6–12 digits');lay.addWidget(new);new.hide()
    repeat=QLineEdit();repeat.setEchoMode(QLineEdit.EchoMode.Password);repeat.setPlaceholderText('Repeat new PIN');lay.addWidget(repeat);repeat.hide()
    def track_focus(old,now):
        if now in (pin,current,new,repeat):focus[0]=now
    QApplication.instance().focusChanged.connect(track_focus)
    def show_profile(data):
        member=data['member'];loans=data['loans'];overdue=sum(bool(r.get('overdue')) for r in loans)
        name.setText(f"{member.get('full_name','')} • {member.get('member_no','')}\nGrade / section: {member.get('grade_level','')} {member.get('section','')}\n{overdue} overdue book(s). Please proceed to the librarian for profile or RFID corrections.")
        fill(t,loans,['title','status','due_at','overdue'])
    def signed(result):
        user.update(result);pin.clear();pin.hide();signin.hide()
        focus[0]=current
        current.show();new.show();repeat.show();change.show()
        task(host,d,lambda:account(host.api,user,'profile'),show_profile)
    signin=button(lay,'Sign in',lambda:task(host,d,lambda:login(host.api,'member',rfid,pin.text()),signed))
    def change_pin():
        if new.text()!=repeat.text():QMessageBox.warning(d,'PIN','PINs do not match.');return
        data={'current_pin':current.text(),'pin':new.text()}
        task(host,d,lambda:account(host.api,user,'change_pin',data),lambda _:(current.clear(),new.clear(),repeat.clear(),QMessageBox.information(d,'PIN changed','Your new PIN is ready.')))
    change=button(lay,'Change PIN',change_pin);change.hide();button(lay,'Sign out / close',d.reject)
    timer=QTimer(d);timer.setSingleShot(True);timer.timeout.connect(d.reject);timer.start(120000)
    lay.addWidget(QLabel('This account screen closes automatically after 2 minutes.'))
    try:d.exec()
    finally:
        QApplication.instance().focusChanged.disconnect(track_focus)
        if user:host.run_async(lambda:account(host.api,user,'logout'),lambda _:None,lambda _:None)
        host.rfid.buffer='';QApplication.instance().installEventFilter(host.rfid);host.busy=False;host.reset()

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
    button(lay,'Retry sync',lambda:task(host,d,lambda:host.outbox.sync(host.api,host.cfg),lambda _:refresh()))
    button(lay,'Export for librarian review',export);button(lay,'Close',d.reject);refresh();d.exec()
