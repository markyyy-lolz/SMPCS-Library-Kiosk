"""Blue, task-oriented operations dialogs; all mutations are authorized on server."""
import json
from datetime import datetime,timedelta
from PyQt6.QtCore import QTimer,Qt,QDate,QDateTime
from PyQt6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QPushButton,QLineEdit,QComboBox,QCheckBox,QFormLayout,QInputDialog,QMessageBox,QFileDialog,QDateEdit,QDateTimeEdit,QPlainTextEdit,QSpinBox,QAbstractItemView,QScrollArea)
from shared.account_ui import dialog,table,fill,selected,task,button
from shared.operations import operations,labels_pdf
from shared.suite_ui import confirm,export_table,error

def call(host,d,action,data,ok,user=None):task(host,d,lambda:operations(host.api,user or host.user,action,data),ok)

def pretty(data):
    if isinstance(data,dict):return '\n'.join(k.replace('_',' ').title()+': '+pretty(v) for k,v in data.items() if v is not None and k not in ('id','member_id','created_by','reviewed_by','fingerprint','book_id','loan_id','copy_id','request_id','attendance_id'))
    if isinstance(data,list):return '\n'+'\n'.join(pretty(v) for v in data)
    return str(data)

def details(parent,title,data):
    d,l=dialog(parent,title);text=QPlainTextEdit(pretty(data));text.setReadOnly(True);l.addWidget(text);button(l,'Close',d.reject);d.exec()

def form(parent,title,fields,save):
    """Fields: key,label,initial,type (text,number,bool,date,datetime,notes,or choices)."""
    d,lay=dialog(parent,title);d.resize(660,570);scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();f=QFormLayout(body);widgets={}
    for key,label,value,kind in fields:
        if isinstance(kind,list):w=QComboBox();w.addItems(kind);w.setCurrentText(str(value or kind[0]))
        elif kind=='bool':w=QCheckBox();w.setChecked(bool(value))
        elif kind=='number':w=QSpinBox();w.setRange(1,10000);w.setValue(int(value or 1))
        elif kind=='date':w=QDateEdit();w.setCalendarPopup(True);w.setDisplayFormat('yyyy-MM-dd');w.setDate(QDate.fromString(str(value),'yyyy-MM-dd') if value else QDate.currentDate())
        elif kind=='datetime':
            w=QDateTimeEdit();w.setCalendarPopup(True);w.setDisplayFormat('yyyy-MM-dd HH:mm');dt=QDateTime.fromString(str(value),Qt.DateFormat.ISODate) if value else QDateTime.currentDateTime();w.setDateTime(dt.toLocalTime())
        elif kind=='notes':w=QPlainTextEdit(str(value or ''));w.setMaximumHeight(110)
        else:w=QLineEdit(str(value or ''))
        f.addRow(label,w);widgets[key]=(w,kind)
    scroll.setWidget(body);lay.addWidget(scroll)
    def values():
        out={}
        for k,(w,t) in widgets.items():
            out[k]=w.currentText() if isinstance(t,list) else w.isChecked() if t=='bool' else w.value() if t=='number' else w.date().toString('yyyy-MM-dd') if t=='date' else w.dateTime().toUTC().toString(Qt.DateFormat.ISODate) if t=='datetime' else w.toPlainText().strip() if t=='notes' else w.text().strip()
        return out
    row=QHBoxLayout();lay.addLayout(row);button(row,'Save',lambda:save(values(),d));button(row,'Cancel',d.reject);d.exec()

def listing(host,title,headers,keys,action,actions=(),data=None,user=None):
    d,l=dialog(host,title);d.resize(1100,730);t=table(l,headers);info=QPlainTextEdit();info.setReadOnly(True);info.setMaximumHeight(130);l.addWidget(info)
    def refresh():call(host,d,action,data or {},lambda rows:fill(t,rows,keys),user)
    t.itemSelectionChanged.connect(lambda:info.setPlainText(pretty(selected(t) or {})))
    row=QHBoxLayout();l.addLayout(row)
    for label,fn,write in actions:
        b=button(row,label,lambda _=False,f=fn:f(d,t,refresh));b.setEnabled(not write or getattr(host,'user',{}).get('role')!='assistant')
    button(row,'Refresh',refresh);button(row,'Export',lambda:export_table(d,t,title));button(row,'Close',d.reject);QTimer.singleShot(0,refresh);d.exec()

def picker(host,parent,kind,callback,multiple=False):
    d,l=dialog(parent,'Choose '+kind.lower());q=QLineEdit();q.setPlaceholderText('Search name, title or reference…');l.addWidget(q);t=table(l,['Name / title','Reference','Details']);rows=[]
    if multiple:t.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    def search():call(host,d,'search',{'search':q.text(),'kind':kind},lambda x:fill(t,x,['label','reference','detail']))
    def accept():
        picked=[t.item(i.row(),0).data(Qt.ItemDataRole.UserRole) for i in t.selectionModel().selectedRows()]
        if picked:d.accept();callback(picked if multiple else picked[0])
    button(l,'Search',search);button(l,'Choose selected',accept);q.returnPressed.connect(search);t.doubleClicked.connect(accept);QTimer.singleShot(0,search);d.exec()

def global_search(host):
    d,l=dialog(host,'Search library');d.resize(1100,730);row=QHBoxLayout();q=QLineEdit();q.setPlaceholderText('Member, book, copy or loan…');kind=QComboBox();kind.addItems(['All','Member','Book','Copy','Loan']);row.addWidget(q,1);row.addWidget(kind);l.addLayout(row);t=table(l,['Type','Name / title','Reference','Details'])
    def search():call(host,d,'search',{'search':q.text(),'kind':kind.currentText()},lambda x:fill(t,x,['kind','label','reference','detail']))
    def save():
        name,ok=QInputDialog.getText(d,'Save filter','Filter name:')
        if ok:call(host,d,'filter_save',{'name':name,'search':q.text(),'kind':kind.currentText()},lambda _:QMessageBox.information(d,'Saved','Filter saved to your staff account.'))
    def load():
        def show(rows):
            if not rows:return
            names=[r['name'] for r in rows];name,ok=QInputDialog.getItem(d,'Saved filters','Choose filter:',names,0,False)
            if ok:r=rows[names.index(name)]['data'];q.setText(r['search']);kind.setCurrentText(r.get('kind') or 'All');search()
        call(host,d,'filters',{},show)
    def open_selected():
        r=selected(t)
        if not r:return
        if r['kind']=='Member':clearance(host,r['id'])
        elif r['kind']=='Book':copies(host,r['id'])
        elif r['kind']=='Copy':listing(host,'Copy history',['Member','Borrowed','Due','Returned','Status'],['full_name','borrowed_at','due_at','returned_at','status'],'copy_history',data={'id':r['id']})
        else:details(d,'Loan',r)
    actions=QHBoxLayout();l.addLayout(actions)
    for name,fn in [('Search',search),('Open selected',open_selected),('Save filter',save),('Load filter',load),('Export',lambda:export_table(d,t,'Library search')),('Close',d.reject)]:button(actions,name,fn)
    q.returnPressed.connect(search);t.doubleClicked.connect(open_selected);QTimer.singleShot(0,search);d.exec()

def copies(host,book_id=None):
    def edit(d,t,refresh,new=False):
        r={} if new else selected(t)
        if r is None:return
        def selected_book(b):
            fields=[('accession','Accession number',r.get('accession'),'text'),('rfid','Physical copy RFID',r.get('rfid'),'text'),('shelf','Shelf / spine code',r.get('shelf'),'text'),('condition','Condition',r.get('condition','good'),['good','quarantine','lost','retired']),('notes','Condition / repair notes',r.get('notes'),'notes'),('verified','I checked this physical copy and its loan assignment',not r.get('needs_verification',True),'bool')]
            form(d,'Add copy' if new else 'Edit / verify physical copy',fields,lambda v,f:call(host,f,'copy_save',{**v,'book_id':b,'id':r.get('id')},lambda _:(f.accept(),refresh())))
        if r:selected_book(r['book_id'])
        elif book_id:selected_book(book_id)
        else:picker(host,d,'Book',lambda b:selected_book(b['id']))
    def history(d,t,refresh):
        r=selected(t)
        if r:listing(host,'Copy history',['Member','Borrowed','Due','Returned','Status'],['full_name','borrowed_at','due_at','returned_at','status'],'copy_history',data={'id':r['id']})
    def labels(d,t,refresh):
        rows=[t.item(i.row(),0).data(Qt.ItemDataRole.UserRole) for i in t.selectionModel().selectedRows()]
        if not rows:return
        path,_=QFileDialog.getSaveFileName(d,'Save printable copy labels','Copy_labels.pdf','PDF (*.pdf)')
        if path:
            try:labels_pdf(path,rows)
            except Exception as exc:error(d,exc)
            else:QMessageBox.information(d,'Labels saved','Print at Actual size / 100%.\n'+path)
    # Dedicated list includes local filtering and extended selection for labels.
    d,l=dialog(host,'Physical copies & repairs');d.resize(1160,760);q=QLineEdit();q.setPlaceholderText('Search title, accession, RFID or shelf…');l.addWidget(q)
    tip=QLabel('Verify migrated copies before borrowing. Quarantine copies while being repaired. Select multiple rows with Ctrl/Shift to print labels.');tip.setWordWrap(True);l.addWidget(tip)
    t=table(l,['Title','Accession','RFID','Shelf','Availability','Notes']);t.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    def refresh():call(host,d,'copies',{'search':q.text(),**({'book_id':book_id} if book_id else {})},lambda rows:fill(t,rows,['title','accession','rfid','shelf','availability','notes']))
    row=QHBoxLayout();l.addLayout(row)
    for label,fn,write in [('Search',lambda:refresh(),False),('Add copy',lambda:edit(d,t,refresh,True),True),('Edit / verify',lambda:edit(d,t,refresh),True),('History',lambda:history(d,t,refresh),False),('Print labels',lambda:labels(d,t,refresh),False),('Export',lambda:export_table(d,t,'Physical copies'),False)]:button(row,label,fn).setEnabled(not write or host.user.get('role')!='assistant')
    button(row,'Close',d.reject);q.returnPressed.connect(refresh);QTimer.singleShot(0,refresh);d.exec()

def calendar(host):
    d,l=dialog(host,'School calendar');d.resize(800,670);l.addWidget(QLabel('Due dates move forward to an open library day. Dates use Philippine time.'))
    row=QHBoxLayout();days=[]
    for name in ['Sun','Mon','Tue','Wed','Thu','Fri','Sat']:w=QCheckBox(name);row.addWidget(w);days.append(w)
    l.addLayout(row);t=table(l,['Closed date','Reason']);closed=[]
    def draw():fill(t,closed,['day','reason'])
    def loaded(data):
        for i,w in enumerate(days):w.setChecked(i in data['open_days'])
        closed[:]=data['closed'];draw()
    def add():
        def save(v,f):
            closed[:]=[r for r in closed if r['day']!=v['day']]+[v];closed.sort(key=lambda r:r['day']);draw();f.accept()
        form(d,'Closed school date',[('day','Date',None,'date'),('reason','Holiday / closure reason','','text')],save)
    def remove():
        r=selected(t)
        if r:closed.remove(r);draw()
    row=QHBoxLayout();l.addLayout(row)
    button(row,'Add holiday',add);button(row,'Remove selected',remove)
    button(row,'Save calendar',lambda:call(host,d,'calendar_save',{'open_days':[i for i,w in enumerate(days) if w.isChecked()],'closed':closed},lambda _:d.accept())).setEnabled(host.user.get('role')=='admin')
    button(row,'Close',d.reject);QTimer.singleShot(0,lambda:call(host,d,'calendar',{},loaded));d.exec()

def rules(host):
    def edit(d,t,refresh):
        r=selected(t)
        if r:form(d,'Borrowing rule',[('max_books','Maximum active loans',r['max_books'],'number'),('loan_days','Borrowing days',r['loan_days'],'number'),('block_overdue','Block new loans when overdue',r['block_overdue'],'bool')],lambda v,f:call(host,f,'rule_save',{**v,'member_type':r['member_type']},lambda _:(f.accept(),refresh())))
    listing(host,'Borrowing rules',['Member type','Max books','Days','Block overdue'],['member_type','max_books','loan_days','block_overdue'],'rules',[('Edit rule',edit,True)])

def clearance(host,member_id=None,user=None):
    def show(mid):
        d,l=dialog(host,'Library clearance');text=QPlainTextEdit();text.setReadOnly(True);l.addWidget(text);state={}
        def loaded(data):
            state.update(data);clear=not data['loans'] and not data['incidents'];text.setPlainText(('CLEARED' if clear else 'NOT CLEARED — outstanding items')+'\n\n'+pretty(data))
        def export():
            from shared.suite import export_rows
            path,_=QFileDialog.getSaveFileName(d,'Export clearance','Library_clearance.pdf','PDF (*.pdf)')
            if path and state:
                try:export_rows(path,['Field','Value'],[[k,pretty(v)] for k,v in state.items()],'Library clearance — '+('Cleared' if not state['loans'] and not state['incidents'] else 'Not cleared'))
                except Exception as exc:error(d,exc)
        button(l,'Export PDF',export);button(l,'Close',d.reject);QTimer.singleShot(0,lambda:call(host,d,'clearance',{'member_id':mid} if mid else {},loaded,user));d.exec()
    if user or member_id:show(member_id)
    else:picker(host,host,'Member',lambda r:show(r['id']))

def review_requests(host):
    def review(d,t,refresh):
        r=selected(t)
        if not r:return
        choices=['under_review','ordered','added','rejected'] if r['kind']=='acquisition' else ['approved','rejected']
        def save(v,f):
            def go(book=None):call(host,f,'review',{'id':r['id'],**v,**({'book_id':book['id']} if book else {})},lambda _:(f.accept(),refresh()))
            if v['status']=='added':picker(host,f,'Book',go)
            elif confirm(f,'Apply this decision? Approved corrections update the member or attendance record.'):go()
        form(d,'Review '+r['kind'],[('status','Decision',choices[0],choices),('note','Librarian response','','notes')],save)
    listing(host,'Acquisitions & corrections',['Type','Member','Status','Requested','Response'],['kind','full_name','status','created_at','note'],'requests',[('Review selected',review,True)])

def reading(host,user=None):
    def edit(d,t,refresh,new=False):
        r={} if new else selected(t)
        if r is None:return
        def save(v,f):
            picker(host,f,'Book',lambda rows:call(host,f,'reading_save',{**v,'id':r.get('id'),'book_ids':[b['id'] for b in rows]},lambda _:(f.accept(),refresh())),True)
        form(d,'Reading list — choose books after Save',[('name','List name',r.get('name'),'text'),('subject','Subject',r.get('subject'),'text'),('grade','Grade level',r.get('grade'),'text')],save)
    actions=[] if user else [('New list',lambda d,t,r:edit(d,t,r,True),True),('Edit list',edit,True),('Delete list',lambda d,t,r:call(host,d,'reading_delete',{'id':selected(t)['id']},lambda _:r()) if selected(t) and confirm(d,'Delete this reading list?') else None,True)]
    listing(host,'Reading lists',['Name','Subject','Grade'],['name','subject','grade'],'reading',actions,user=user)

def occupancy(host):
    d,l=dialog(host,'Library occupancy');d.resize(1050,700);summary=QLabel();summary.setWordWrap(True);l.addWidget(summary);t=table(l,['Member','Number','Last time-in','Needs review'])
    def loaded(data):
        people=data['people'];current=sum(not p['stale'] for p in people);stale=len(people)-current;summary.setText(f"Today's unmatched time-ins: {current} / capacity {data['capacity']}   •   Older entries needing review: {stale}\nAttendance is an estimate; verify stale entries before using the count.");fill(t,people,['full_name','member_no','scanned_at','stale'])
    def refresh():call(host,d,'occupancy',{},loaded)
    def correct():
        r=selected(t)
        if r:form(d,'Correct attendance entry',[('action','Correct action',r['action'],['IN','OUT']),('scanned_at','Correct time (this computer timezone)',r['scanned_at'],'datetime'),('reason','Reason for correction','','notes')],lambda v,f:call(host,f,'attendance_correct',{'id':r['id'],**v},lambda _:(f.accept(),refresh())))
    def capacity():
        value,ok=QInputDialog.getInt(d,'Library capacity','Maximum occupants:',50,1,10000)
        if ok:call(host,d,'capacity',{'capacity':value},lambda _:refresh())
    row=QHBoxLayout();l.addLayout(row);button(row,'Refresh',refresh);button(row,'Correct selected',correct).setEnabled(host.user.get('role')!='assistant');button(row,'Set capacity',capacity).setEnabled(host.user.get('role')=='admin');button(row,'Close',d.reject);QTimer.singleShot(0,refresh);d.exec()

def visits(host):
    def add(d,t,refresh):
        start=(datetime.now()+timedelta(days=1)).replace(hour=9,minute=0,second=0,microsecond=0)
        form(d,'Book a class visit',[('section','Section','','text'),('teacher','Teacher','','text'),('starts_at','Start (this computer timezone)',start.isoformat(),'datetime'),('ends_at','End (this computer timezone)',(start+timedelta(hours=1)).isoformat(),'datetime'),('seats','Number of students',30,'number')],lambda v,f:call(host,f,'visit_save',v,lambda _:(f.accept(),refresh())))
    def cancel(d,t,refresh):
        r=selected(t)
        if r and confirm(d,'Cancel this class visit?'):call(host,d,'visit_cancel',{'id':r['id']},lambda _:refresh())
    listing(host,'Class visits',['Section','Teacher','Starts','Ends','Seats','Status'],['section','teacher','starts_at','ends_at','seats','status'],'visits',[('Book visit',add,True),('Cancel selected',cancel,True)])

def handover(host):
    def add(d,t,refresh):form(d,'Staff handover',[('message','Tasks / concerns for the next shift','','notes')],lambda v,f:call(host,f,'handover_add',v,lambda _:(f.accept(),refresh())))
    def resolve(d,t,refresh):
        r=selected(t)
        if r and confirm(d,'Mark this handover task completed?'):call(host,d,'handover_resolve',{'id':r['id']},lambda _:refresh())
    listing(host,'Staff handover',['Note','Staff','Created','Completed'],['message','full_name','created_at','resolved_at'],'handover',[('Add note',add,True),('Mark completed',resolve,True)])

def closing(host):
    d,l=dialog(host,'Daily closing report');date=QDateEdit(QDate.currentDate());date.setCalendarPopup(True);l.addWidget(date);text=QPlainTextEdit();text.setReadOnly(True);l.addWidget(text);state={}
    def load():call(host,d,'closing',{'day':date.date().toString('yyyy-MM-dd')},lambda r:(state.update(r),text.setPlainText(pretty(r))))
    def save():call(host,d,'closing_save',{'day':date.date().toString('yyyy-MM-dd')},lambda r:QMessageBox.information(d,'Saved','Closing snapshot recorded with your staff account.'))
    def export():
        from shared.suite import export_rows
        path,_=QFileDialog.getSaveFileName(d,'Export daily closing','Daily_closing.xlsx','Excel (*.xlsx);;PDF (*.pdf)')
        if path:
            try:export_rows(path,['Measure','Value'],[[k,pretty(v)] for k,v in state.items()],'Daily closing report')
            except Exception as exc:error(d,exc)
    row=QHBoxLayout();l.addLayout(row);button(row,'Refresh',load);button(row,'Record closing',save).setEnabled(host.user.get('role')!='assistant');button(row,'Saved snapshots',lambda:listing(host,'Saved closing reports',['Day','Recorded'],['day','created_at'],'closing_history'));button(row,'Export',export);button(row,'Close',d.reject);date.dateChanged.connect(load);QTimer.singleShot(0,load);d.exec()

def pickups(host):
    def collect(d,t,refresh):
        r=selected(t)
        if r and confirm(d,f"Hand copy {r['accession']} to {r['full_name']} and create the loan?"):call(host,d,'collect',{'id':r['request_id']},lambda _:refresh())
    listing(host,'Ready for pickup',['Member','Number','Title','Copy','Pickup deadline'],['full_name','member_no','title','accession','deadline'],'pickups',[('Confirm handover',collect,True)])

def duplicates(host):
    def merge(d,t,refresh):
        r=selected(t)
        if not r:return
        def source(s):
            def target(tgt):
                payload={'kind':r['kind'],'source':s['id'],'target':tgt['id']}
                def preview(p):
                    details(d,'Merge preview — source will be archived',p)
                    value,ok=QInputDialog.getText(d,'Confirm merge',f"Keep {tgt['label']} ({tgt['reference']}); archive {s['reference']}.\nType MERGE to apply:")
                    if ok and value=='MERGE':call(host,d,'merge',{**payload,'confirmation':value,'fingerprint':p['fingerprint']},lambda _:refresh())
                call(host,d,'merge_preview',payload,preview)
            picker(host,d,r['kind'],target)
        QMessageBox.information(d,'Merge records','Choose the SOURCE to archive, then the TARGET to keep. Pending requests must be resolved first.');picker(host,d,r['kind'],source)
    listing(host,'Possible duplicates',['Type','Matching name / title','Records'],['kind','match','records'],'duplicates',[('Preview merge',merge,True)])

def add_operations(host,items):
    items.extend([
      ('Search library','Search members, books, copies and loans; save your filters.',global_search,False),
      ('Physical copies & repairs','Verify accessions and RFID, quarantine damaged books, print labels.',copies,False),
      ('School calendar','Open weekdays and school holidays for borrowing due dates.',calendar,False),
      ('Borrowing rules','Loan limits and duration by member type.',rules,False),
      ('Library clearance','Outstanding loans and unresolved incidents per member.',clearance,False),
      ('Ready for pickup','Reservation deadlines and confirmed copy handover.',pickups,False),
      ('Acquisitions & corrections','Requested books, profile changes and attendance corrections.',review_requests,False),
      ('Reading lists','Recommended books grouped by subject and grade.',reading,False),
      ('Library occupancy','Current attendance estimate, stale time-ins and capacity.',occupancy,False),
      ('Class visits','Book class schedules and detect time conflicts.',visits,False),
      ('Possible duplicates','Review matches and preview record merges.',duplicates,True),
      ('Staff handover','Tasks and notes for the next shift.',handover,False),
      ('Daily closing','Review activity and save an end-of-day snapshot.',closing,False)])

def attach_member(account_dialog):
    """Account-only panel; never accepts a caller-supplied member identity."""
    from shared.operations import operations
    host=account_dialog;host.api=account_dialog.host.api;host.run_async=account_dialog.host.run_async
    def close_children(*_):
        from PyQt6.QtWidgets import QDialog
        for child in host.findChildren(QDialog):child.reject();child.deleteLater()
    account_dialog.finished.connect(close_children)
    page=QWidget();lay=QVBoxLayout(page);title=QLabel('My library services');title.setStyleSheet('font-size:22px;font-weight:700;color:#174476;');lay.addWidget(title)
    note=QLabel('Request corrections and new books here. The librarian reviews your changes before applying them.');note.setWordWrap(True);lay.addWidget(note)
    def requests():
        listing(host,'My book requests & corrections',['Type','Status','Requested','Librarian response'],['kind','status','created_at','note'],'my_operations',user=account_dialog.user)
    def submit(kind,fields,extra=None):
        def save(v,d):call(host,d,'submit',{'kind':kind,**v,**(extra or {})},lambda _:(d.accept(),QMessageBox.information(account_dialog,'Request sent','You can check the status in My requests & corrections.')),account_dialog.user)
        form(account_dialog,'Request '+kind,fields+[('reason','Reason','','notes')],save)
    def profile():
        from shared.services import account
        def loaded(data):
            m=data['member'];submit('profile',[(k,label,m.get(k),'text') for k,label in [('full_name','Correct full name'),('grade_level','Grade level'),('section','Section')]])
        task(host,account_dialog,lambda:account(host.api,account_dialog.user,'profile'),loaded)
    def attendance():
        def request(d,t,refresh):
            r=selected(t)
            if r:submit('attendance',[('action','Correct action',r['action'],['IN','OUT']),('scanned_at','Correct time (this computer timezone)',r['scanned_at'],'datetime')],{'attendance_id':r['id']})
        listing(host,'My attendance',['Action','Time','Station'],['action','scanned_at','station_code'],'my_attendance',[('Request correction',request,False)],user=account_dialog.user)
    for label,fn in [
      ('Request a new book',lambda:submit('acquisition',[('title','Book title','','text'),('author','Author','','text')])),
      ('Request profile correction',profile),('My attendance / correction',attendance),
      ('My requests & corrections',requests),('Reading lists',lambda:reading(host,account_dialog.user)),
      ('Check library clearance',lambda:clearance(host,user=account_dialog.user))]:
        b=QPushButton(label);b.setMinimumHeight(44);b.clicked.connect(fn);lay.addWidget(b)
    lay.addStretch();account_dialog.tabs.addTab(page,'Library services')
