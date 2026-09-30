"""Admin service center: shared list/form controls with server-authorized actions."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from PyQt6.QtCore import QTimer, QDate, Qt
from PyQt6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QPushButton,QLineEdit,QComboBox,QCheckBox,QFormLayout,QInputDialog,QMessageBox,QFileDialog,QDateEdit,QPlainTextEdit,QScrollArea,QApplication,QAbstractItemView)
from shared.account_ui import dialog,table,fill,selected,task,button
from shared.suite import suite,read_import,export_rows,cover_image,diagnostics
from shared.config import APP_DIR


def confirm(parent,text):
    return QMessageBox.question(parent,'Confirm',text)==QMessageBox.StandardButton.Yes


def error(parent,exc):QMessageBox.warning(parent,'Could not complete',str(exc))


def ask(parent,title,fields,callback):
    d,lay=dialog(parent,title);d.resize(620,420);form=QFormLayout();lay.addLayout(form);widgets={}
    for key,label,initial in fields:
        w=QLineEdit(str(initial));form.addRow(label,w);widgets[key]=w
    note=QLabel('Changes are checked by the server before saving.');note.setWordWrap(True);lay.addWidget(note);lay.addStretch()
    def save():
        callback({k:w.text().strip() for k,w in widgets.items()},d)
    button(lay,'Save',save);button(lay,'Cancel',d.reject);d.exec()


def call(host,d,action,data,ok):task(host,d,lambda:suite(host.api,host.user,action,data),ok)


def export_table(parent,t,title):
    path,_=QFileDialog.getSaveFileName(parent,'Export report',title+'.xlsx','Excel (*.xlsx);;PDF (*.pdf);;CSV (*.csv)')
    if not path:return
    headers=[t.horizontalHeaderItem(c).text() for c in range(t.columnCount())]
    rows=[[t.item(r,c).text() if t.item(r,c) else '' for c in range(t.columnCount())] for r in range(t.rowCount()) if not t.isRowHidden(r)]
    try:export_rows(path,headers,rows,title)
    except Exception as exc:error(parent,exc)
    else:QMessageBox.information(parent,'Export saved',path)


def requests_dialog(host,initial='All'):
    d,lay=dialog(host,'Requests & notifications');d.resize(1060,720)
    filters=QHBoxLayout();kind=QComboBox();kind.addItems(['All','registration','reservation','renewal','feedback','incident']);kind.setCurrentText(initial)
    status=QComboBox();status.addItems(['pending','All','approved','rejected','resolved','cancelled']);filters.addWidget(kind);filters.addWidget(status);lay.addLayout(filters)
    t=table(lay,['Type','Member','Book','Status','Requested']);details=QPlainTextEdit();details.setReadOnly(True);details.setMaximumHeight(150);lay.addWidget(details)
    def show_details():
        r=selected(t);details.setPlainText(json.dumps(r.get('data',{}),indent=2,ensure_ascii=False) if r else '')
    t.itemSelectionChanged.connect(show_details)
    def refresh():call(host,d,'requests',{'kind':kind.currentText(),'status':status.currentText()},lambda rows:fill(t,rows,['kind','full_name','title','status','created_at']))
    def review(decision):
        r=selected(t)
        if not r:return
        if r['kind'] in ('feedback','incident') and decision=='approved':decision='resolved'
        text='Confirm this request?'
        if r['kind']=='reservation' and decision=='approved':text='Confirm the book has been handed to this member? This creates a 7-day loan.'
        if not confirm(d,text):return
        note,ok=QInputDialog.getText(d,'Review note','Remarks / assessment (optional):')
        if ok:call(host,d,'review',{'id':r['id'],'decision':decision,'note':note},lambda _:refresh())
    actions=QHBoxLayout();lay.addLayout(actions)
    for text,decision in [('Approve / Resolve','approved'),('Reject','rejected')]:
        b=button(actions,text,lambda _=False,v=decision:review(v));b.setEnabled(host.user.get('role')!='assistant')
    button(actions,'Refresh',refresh);button(actions,'Export',lambda:export_table(d,t,'Library requests'));button(actions,'Close',d.reject)
    kind.currentTextChanged.connect(refresh);status.currentTextChanged.connect(refresh);QTimer.singleShot(0,refresh);d.exec()


def notifications(host):
    d,lay=dialog(host,'Notifications');t=table(lay,['Needs attention','Count'])
    def refresh():call(host,d,'notifications',{},lambda rows:fill(t,[r for r in rows if r['count']],['kind','count']))
    def open_item():
        r=selected(t)
        if not r:return
        d.accept();kind=r['kind']
        if kind=='overdue':host.show_overdue()
        elif kind=='borrowing':host.show_page('approvals')
        elif kind=='returns':
            from shared.account_ui import return_requests
            return_requests(host)
        else:requests_dialog(host,kind)
    t.doubleClicked.connect(open_item);button(lay,'Open selected',open_item);button(lay,'Refresh',refresh);button(lay,'Close',d.reject);QTimer.singleShot(0,refresh);d.exec()


def member_tools(host):
    d,lay=dialog(host,'Member management');d.resize(1040,720)
    row=QHBoxLayout();search=QLineEdit();search.setPlaceholderText('Search name, member number, grade, section…');row.addWidget(search)
    status=QComboBox();status.addItems(['All','Active','Inactive']);row.addWidget(status);lay.addLayout(row)
    t=table(lay,['Member number','Name','Grade','Section','Active','School year']);t.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection);data=[]
    def filtered():
        q=search.text().casefold();fill(t,[r for r in data if q in ' '.join(str(v) for v in r.values()).casefold() and (status.currentText()=='All' or r.get('active')==(status.currentText()=='Active'))],['member_no','full_name','grade_level','section','active','school_year'])
    def loaded(rows):data[:]=rows;filtered()
    def load_all():
        rows=[]
        while True:
            batch=host.api.select('library_members',f'?select=*&order=full_name,id&limit=500&offset={len(rows)}') or [];rows+=batch
            if len(batch)<500:return rows
    def refresh():task(host,d,load_all,loaded)
    def access():
        r=selected(t)
        if not r:return
        def save(v,form):
            if v['active'].lower() not in ('yes','no'):error(form,'Use yes or no for Active.');return
            if not confirm(form,'Save account access changes?'):return
            from shared.services import account
            task(host,form,lambda:account(host.api,host.user,'member_access',{'id':r['id'],'active':v['active'].lower()=='yes','pin':v['pin']}),lambda _:(form.accept(),refresh()))
        ask(d,'Account access / reset PIN',[('active','Active: yes / no','yes' if r['active'] else 'no'),('pin','New PIN (blank keeps current)','')],save)
    def replace_card():
        r=selected(t)
        if not r:return
        def save(v,form):
            if confirm(form,'Retire the old RFID card and replace it?'):
                call(host,form,'rfid_replace',{'member_id':r['id'],**v},lambda _:(form.accept(),refresh()))
        ask(d,'Replace RFID',[('new_rfid','New card UID','')],save)
    def promote():
        ids=[t.item(i.row(),0).data(Qt.ItemDataRole.UserRole)['id'] for i in t.selectionModel().selectedRows()]
        if not ids:return
        def save(v,form):
            if v['archive'].lower() not in ('yes','no'):error(form,'Archive must be yes or no.');return
            if confirm(form,f'Apply to {len(ids)} selected members? History will be retained.'):
                call(host,form,'promote',{**v,'ids':ids,'archive':v['archive'].lower()=='yes'},lambda _:(form.accept(),refresh()))
        ask(d,'Promote / archive selected members',[('school_year','School year','2026–2027'),('grade_level','New grade',''),('section','New section',''),('archive','Archive graduates? yes / no','no')],save)
    actions=QHBoxLayout();lay.addLayout(actions)
    for text,fn,admin in [('Access / PIN',access,False),('Replace RFID',replace_card,True),('Promote / archive',promote,True)]:
        b=button(actions,text,fn);b.setEnabled(host.user.get('role')=='admin' if admin else host.user.get('role')!='assistant')
    button(actions,'Refresh',refresh);button(actions,'Close',d.reject);search.textChanged.connect(filtered);status.currentTextChanged.connect(filtered);QTimer.singleShot(0,refresh);d.exec()


def import_dialog(host):
    d,lay=dialog(host,'Import members / books');kind=QComboBox();kind.addItems(['members','books']);lay.addWidget(kind)
    note=QLabel('Import creates new records only. Duplicates reject the whole batch; existing records are never overwritten. Maximum 1000 rows. Store RFID and member numbers as text in Excel to keep leading zeros.');note.setWordWrap(True);lay.addWidget(note)
    t=table(lay,['Preview']);state={}
    def template():
        fields= {'members':['member_no','rfid_uid','full_name','member_type','grade_level','section'],'books':['accession_no','book_rfid','title','author','category','shelf','total_copies']}[kind.currentText()]
        path,_=QFileDialog.getSaveFileName(d,'Save template',kind.currentText()+'.csv','CSV (*.csv)')
        if path:export_rows(path,fields,[])
    def choose():
        path,_=QFileDialog.getOpenFileName(d,'Import file','','CSV / Excel (*.csv *.xlsx)')
        if not path:return
        try:headers,rows=read_import(path,kind.currentText())
        except Exception as exc:error(d,exc);return
        state.update(kind=kind.currentText(),rows=rows);t.setColumnCount(len(headers));t.setHorizontalHeaderLabels(headers);fill(t,rows,headers)
        note.setText(f'{len(rows)} rows validated locally. Confirm to import; the database also checks existing duplicates.')
    def save():
        if state and confirm(d,f"Import {len(state['rows'])} {state['kind']}? This is one atomic batch."):
            call(host,d,'import',state,lambda r:(QMessageBox.information(d,'Imported',str(r['imported'])+' records added.'),d.accept()))
    actions=QHBoxLayout();lay.addLayout(actions);button(actions,'Template',template);button(actions,'Choose file',choose);button(actions,'Confirm import',save);button(actions,'Close',d.reject);d.exec()


def book_details(host):
    d,lay=dialog(host,'Book covers & shelf locations');search=QLineEdit();search.setPlaceholderText('Search title / author');lay.addWidget(search);t=table(lay,['Title','Author','Shelf','Available']);state={}
    def refresh():call(host,d,'catalog',{'search':search.text()},lambda rows:fill(t,rows,['title','author','shelf','available_copies']))
    def edit():
        r=selected(t)
        if not r:return
        state['cover']=r.get('cover_data')
        form,box=dialog(d,'Book details');form.resize(600,360);shelf=QLineEdit(r.get('shelf') or '');box.addWidget(QLabel(r['title']));box.addWidget(QLabel('Shelf location'));box.addWidget(shelf);label=QLabel('Cover attached' if state['cover'] else 'No cover');box.addWidget(label)
        def choose():
            path,_=QFileDialog.getOpenFileName(form,'Choose cover','','Images (*.png *.jpg *.jpeg *.webp)')
            if path:
                try:state['cover']=cover_image(path);label.setText('New cover ready')
                except Exception as exc:error(form,exc)
        button(box,'Choose cover',choose);button(box,'Remove cover',lambda:(state.update(cover=None),label.setText('No cover')))
        button(box,'Save',lambda:call(host,form,'book_details',{'id':r['id'],'shelf':shelf.text(),'cover_data':state['cover']},lambda _:(form.accept(),refresh())));button(box,'Cancel',form.reject);form.exec()
    actions=QHBoxLayout();lay.addLayout(actions);button(actions,'Search',refresh);b=button(actions,'Edit selected',edit);b.setEnabled(host.user.get('role')!='assistant');button(actions,'Close',d.reject);QTimer.singleShot(0,refresh);d.exec()


def announcements(host):
    d,lay=dialog(host,'Announcements & maintenance');t=table(lay,['Title','Message','Expires'])
    def refresh():call(host,d,'announcements',{},lambda rows:fill(t,rows,['title','message','expires_at']))
    def add():
        def save(v,form):
            try:v['expires_at']=(datetime.now(timezone.utc)+timedelta(days=int(v.pop('days')))).isoformat()
            except ValueError:error(form,'Enter expiry in whole days.');return
            call(host,form,'announce',v,lambda _:(form.accept(),refresh()))
        ask(d,'New announcement',[('title','Title',''),('message','Message',''),('days','Expires in days','7')],save)
    def remove():
        r=selected(t)
        if r and confirm(d,'Remove this announcement?'):call(host,d,'announcement_remove',{'id':r['id']},lambda _:refresh())
    def maintenance():
        def save(v,form):
            if v['enabled'].lower() not in ('yes','no'):error(form,'Use yes or no.');return
            if confirm(form,'Apply kiosk maintenance setting?'):call(host,form,'maintenance',{'enabled':v['enabled'].lower()=='yes','message':v['message']},lambda _:(form.accept(),QMessageBox.information(d,'Saved','Kiosks refresh within 30 seconds.')))
        ask(d,'Maintenance mode',[('enabled','Pause kiosk? yes / no','no'),('message','Message / expected reopening','Please return after maintenance.')],save)
    actions=QHBoxLayout();lay.addLayout(actions)
    for text,fn,admin in [('New announcement',add,False),('Remove',remove,False),('Maintenance',maintenance,True)]:
        b=button(actions,text,fn);b.setEnabled(host.user.get('role')=='admin' if admin else host.user.get('role')!='assistant')
    button(actions,'Close',d.reject);QTimer.singleShot(0,refresh);d.exec()


def reports(host):
    d,lay=dialog(host,'Reports & borrowing receipts');d.resize(1120,720);row=QHBoxLayout();kind=QComboBox();kind.addItems(['borrowed','returned','overdue','attendance']);row.addWidget(kind)
    start=QDateEdit(QDate.currentDate().addDays(-30));end=QDateEdit(QDate.currentDate())
    for label,w in [('From',start),('Through',end)]:w.setCalendarPopup(True);row.addWidget(QLabel(label));row.addWidget(w)
    lay.addLayout(row);note=QLabel('Dates use Philippine time. Overdue reports filter by due date; returned reports by return date.');note.setWordWrap(True);lay.addWidget(note);t=table(lay,['Records'])
    def loaded(rows):
        if len(rows)>10000:error(d,'More than 10,000 rows. Narrow the dates for a complete report.');t.setRowCount(0);return
        headers=list(rows[0]) if rows else ['No records'];t.setColumnCount(len(headers));t.setHorizontalHeaderLabels(headers);fill(t,rows,headers);note.setText(str(len(rows))+' records loaded (Philippine date range).')
    def refresh():
        tz=timezone(timedelta(hours=8));lo=datetime.combine(start.date().toPyDate(),datetime.min.time(),tz);hi=datetime.combine(end.date().addDays(1).toPyDate(),datetime.min.time(),tz)
        call(host,d,'reports',{'kind':kind.currentText(),'start':lo.isoformat(),'end':hi.isoformat()},loaded)
    def receipt():
        r=selected(t)
        if not r or 'title' not in r:error(d,'Select a borrowing record first.');return
        path,_=QFileDialog.getSaveFileName(d,'Save printable receipt','Borrowing_receipt.pdf','PDF (*.pdf)')
        if path:
            try:export_rows(path,['Field','Details'],[[k,str(r.get(k) or '')] for k in ['id','full_name','member_no','title','status','borrowed_at','due_at']],'SMPCS Library — Borrowing receipt')
            except Exception as exc:error(d,exc)
            else:QMessageBox.information(d,'Receipt saved','Open this PDF to print:\n'+path)
    def incident():
        r=selected(t)
        if not r or 'title' not in r:return
        def save(v,form):call(host,form,'incident',{'loan_id':r['id'],**v},lambda _:(form.accept(),refresh()))
        ask(d,'Record lost / damaged book',[('type','Type: lost / damaged','damaged'),('message','Remarks / assessment','')],save)
    actions=QHBoxLayout();lay.addLayout(actions);button(actions,'Load',refresh);button(actions,'Export PDF / Excel',lambda:export_table(d,t,'Library report'));button(actions,'Receipt PDF',receipt);b=button(actions,'Lost / damaged',incident);b.setEnabled(host.user.get('role')!='assistant');button(actions,'Close',d.reject);QTimer.singleShot(0,refresh);d.exec()


def inventory(host):
    d,lay=dialog(host,'Library inventory');d.resize(1080,700);sessions=QComboBox();lay.addWidget(sessions);note=QLabel('One scan identifies a catalog record. For multi-copy titles, verify copy counts physically; unscanned records are not automatically declared lost.');note.setWordWrap(True);lay.addWidget(note)
    row=QHBoxLayout();rfid=QLineEdit();rfid.setPlaceholderText('Scan RFID / accession number');shelf=QLineEdit();shelf.setPlaceholderText('Observed shelf');row.addWidget(rfid);row.addWidget(shelf);lay.addLayout(row);t=table(lay,['Title','Accession','Expected shelf','Observed shelf','Available copies','Status'])
    def refresh():
        if sessions.currentData():call(host,d,'inventory_results',{'session_id':sessions.currentData()},lambda rows:fill(t,rows,['title','accession_no','shelf','observed_shelf','available_copies','status']))
    def loaded(rows):
        sessions.blockSignals(True);sessions.clear()
        for r in rows:sessions.addItem(r['name']+(' — completed' if r['completed_at'] else ' — open'),r['id'])
        sessions.blockSignals(False);refresh()
    def load_sessions():call(host,d,'inventory_list',{},loaded)
    def new():
        name,ok=QInputDialog.getText(d,'New inventory','Session name:')
        if ok and name:call(host,d,'inventory_start',{'name':name},lambda _:load_sessions())
    def scan():
        if sessions.currentData():call(host,d,'inventory_scan',{'session_id':sessions.currentData(),'rfid':rfid.text().strip(),'shelf':shelf.text().strip()},lambda _:(rfid.clear(),rfid.setFocus(),refresh()))
    def close_session():
        if sessions.currentData() and confirm(d,'Finish this inventory session?'):call(host,d,'inventory_close',{'session_id':sessions.currentData()},lambda _:load_sessions())
    actions=QHBoxLayout();lay.addLayout(actions)
    for text,fn in [('New session',new),('Record scan',scan),('Finish session',close_session)]:b=button(actions,text,fn);b.setEnabled(host.user.get('role')!='assistant')
    button(actions,'Export',lambda:export_table(d,t,'Inventory'));button(actions,'Close',d.reject);rfid.returnPressed.connect(scan);sessions.currentIndexChanged.connect(refresh);QTimer.singleShot(0,load_sessions);d.exec()


def backups(host):
    d,lay=dialog(host,'Backup & restore center');d.resize(900,650)
    note=QLabel('Operational snapshots include records and suite requests, not passwords, PINs, station secrets or database schema. Restore merges by record ID and retains newer records. Stock is recalculated. A server recovery point is saved before every restore.');note.setWordWrap(True);lay.addWidget(note)
    t=table(lay,['Snapshot','Created / modified']);state={}
    def refresh():
        rows=[{'name':p.name,'time':datetime.fromtimestamp(p.stat().st_mtime).isoformat(),'path':str(p)} for p in sorted((APP_DIR/'backups').glob('library-*.json'),reverse=True)]
        fill(t,rows,['name','time']);note.setText('Last local backup: '+(rows[0]['time'] if rows else 'None yet')+'\nRestore merges operational records; passwords and station credentials are excluded. A server recovery point is created first.')
    def save():
        from shared.services import save_backup
        task(host,d,lambda:save_backup(host.api,host.user),lambda _:(refresh(),QMessageBox.information(d,'Backup','Backup saved.')))
    def restore_payload(payload):
        value,ok=QInputDialog.getText(d,'Restore operational records','This changes existing records. Type RESTORE to confirm:')
        if ok and value=='RESTORE':call(host,d,'restore',{**payload,'confirmation':value},lambda _:(refresh(),QMessageBox.information(d,'Restore complete','Records restored. Member sessions were signed out.')))
    def restore_file():
        path,_=QFileDialog.getOpenFileName(d,'Choose operational backup',str(APP_DIR/'backups'),'JSON (*.json)')
        if not path:return
        try:
            if Path(path).stat().st_size>50_000_000:raise ValueError('Backup exceeds 50 MB.')
            snap=json.loads(Path(path).read_text(encoding='utf-8'))
            if snap.get('format') not in ('SMPCS operational backup v1','SMPCS operational backup v2'):raise ValueError('Unsupported backup format.')
            counts='\n'.join(f'{k}: {len(v)}' for k,v in snap.items() if isinstance(v,list))
        except Exception as exc:error(d,exc);return
        if confirm(d,'Review snapshot '+str(snap.get('created_at',''))+'\n'+counts+'\nContinue to restore confirmation?'):restore_payload({'snapshot':snap})
    def points():
        def show(rows):
            if not rows:QMessageBox.information(d,'Recovery points','No server recovery points yet.');return
            labels=[r['created_at']+' • '+r['id'] for r in rows];chosen,ok=QInputDialog.getItem(d,'Server recovery points','Snapshot before a previous restore:',labels,0,False)
            if ok:restore_payload({'restore_id':rows[labels.index(chosen)]['id']})
        call(host,d,'restore_points',{},show)
    actions=QHBoxLayout();lay.addLayout(actions);button(actions,'Create backup',save);button(actions,'Restore file',restore_file);button(actions,'Server recovery points',points);button(actions,'Close',d.reject);refresh();d.exec()


def diagnostic_dialog(host):
    d,lay=dialog(host,'Diagnostics');box=QPlainTextEdit(diagnostics());box.setReadOnly(True);lay.addWidget(box);button(lay,'Copy diagnostic report',lambda:QApplication.clipboard().setText(box.toPlainText()));button(lay,'Close',d.reject);d.exec()


def build_center(host):
    from admin.main import Card,make_button
    page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(0,0,0,0)
    scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();grid=QGridLayout(body);grid.setSpacing(16)
    items=[('Notifications','Overdue books and pending requests.',notifications,False),('Requests','Registrations, reservations, renewals and feedback.',requests_dialog,False),('Member management','Search, access, PINs, RFID replacement and school-year promotion.',member_tools,False),('Import records','Preview CSV / Excel and add members or books.',import_dialog,True),('Catalog details','Book covers and shelf locations.',book_details,False),('Announcements','Publish notices and control maintenance mode.',announcements,False),('Reports & receipts','Date filters, PDF / Excel, lost and damaged books.',reports,False),('Inventory','Record shelf scans and review missing or misplaced books.',inventory,False),('Backup & restore','Local snapshots and server recovery points.',backups,True),('Diagnostics','Copy an app report without credentials or member data.',diagnostic_dialog,False)]
    for i,(title,description,fn,admin) in enumerate(items):
        card=Card(title,description);b=make_button('Open',lambda _=False,f=fn:f(host),height=40);b.setEnabled(not admin or host.user.get('role')=='admin');card.lay.addWidget(b);grid.addWidget(card,i//2,i%2)
    grid.setColumnStretch(0,1);grid.setColumnStretch(1,1);scroll.setWidget(body);layout.addWidget(scroll);host.add_page('services',page,lambda:None)
    host.notification_button=QPushButton('Notifications');host.notification_button.clicked.connect(lambda:notifications(host));host.statusBar().addPermanentWidget(host.notification_button)
    timer=QTimer(host);timer.setInterval(60000);busy=[False]
    def poll():
        if busy[0]:return
        busy[0]=True
        def ok(rows):busy[0]=False;host.notification_button.setText(f"Notifications ({sum(r['count'] for r in rows)})")
        def fail(exc):busy[0]=False;host.notification_button.setToolTip(str(exc))
        host.load(lambda:suite(host.api,host.user,'notifications'),ok,fail)
    timer.timeout.connect(poll);timer.start();QTimer.singleShot(3000,poll)
