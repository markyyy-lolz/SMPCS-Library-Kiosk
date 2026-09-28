"""Attendance reporting and table actions; uses the existing database schema."""
import csv
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QDateEdit,QFileDialog,QTableWidget,QHeaderView

def csv_cell(value):
    value=str(value)
    return "'"+value if value.lstrip().startswith(('=','+','-','@')) else value

def attendance_query(start,end):
    if start>end: raise ValueError('The start date must be on or before the end date.')
    tz=timezone(timedelta(hours=8))
    lo=datetime.combine(start,datetime.min.time(),tz).isoformat()
    hi=datetime.combine(end+timedelta(days=1),datetime.min.time(),tz).isoformat()
    return ('?select=id,action,scanned_at,station_code,library_members(full_name,student_id,grade_level,section)'
            +'&scanned_at=gte.'+quote(lo,safe='')+'&scanned_at=lt.'+quote(hi,safe='')+'&order=scanned_at.desc,id.desc')

class AdminFeatures:
    def build_quick_tools(self):
        from admin.main import make_button
        row=QHBoxLayout()
        row.addWidget(make_button('Refresh page',lambda:self._refreshers[self.current_page](),'secondary',38))
        row.addWidget(make_button('Export visible table',self.export_visible_table,'secondary',38))
        row.addStretch()
        row.addWidget(make_button('Attendance',lambda:self.show_page('attendance'),'secondary',38))
        row.addWidget(make_button('Overdue books',self.show_overdue,'secondary',38))
        return row

    def show_overdue(self):
        self.show_page('loans'); self.lfilter.setCurrentIndex(1)

    def export_visible_table(self):
        from admin.main import msg
        page=self.stack.currentWidget()
        tables=[t for t in page.findChildren(QTableWidget) if t.isVisibleTo(page)]
        if not tables:
            msg(self,'Export','Open a page with a table first.','info'); return
        table=tables[0]
        rows=[[table.item(r,c).text() if table.item(r,c) else '' for c in range(table.columnCount())]
              for r in range(table.rowCount()) if not table.isRowHidden(r)]
        if not rows:
            msg(self,'Export','There are no visible rows to export.','info'); return
        path,_=QFileDialog.getSaveFileName(self,'Export visible rows',self.current_page+'.csv','CSV (*.csv)')
        if not path:return
        try:
            with open(path,'w',encoding='utf-8-sig',newline='') as stream:
                writer=csv.writer(stream)
                writer.writerow([table.horizontalHeaderItem(c).text() if table.horizontalHeaderItem(c) else str(c+1) for c in range(table.columnCount())])
                writer.writerows([[csv_cell(v) for v in row] for row in rows])
            self.toast.show_message(f'Exported {len(rows)} visible rows')
        except OSError as exc: msg(self,'Export failed',str(exc),'error')

    def build_attendance(self):
        from admin.main import Card,make_table,search_box,make_button
        page=QWidget(); layout=QVBoxLayout(page); layout.setContentsMargins(0,0,0,0)
        card=Card('RFID attendance records','Dates use Philippine time. Export contains only the rows currently shown.')
        row=QHBoxLayout()
        self.att_from=QDateEdit(QDate.currentDate().addDays(-6)); self.att_to=QDateEdit(QDate.currentDate())
        for label,field in [('From',self.att_from),('To',self.att_to)]:
            field.setCalendarPopup(True); field.setDisplayFormat('MMM dd, yyyy'); row.addWidget(QLabel(label)); row.addWidget(field)
        self.att_action=QComboBox(); self.att_action.addItems(['All actions','IN','OUT']); row.addWidget(self.att_action)
        row.addWidget(make_button('Load records',self.refresh_attendance,'secondary',42)); card.lay.addLayout(row)
        self.att_search=search_box('Search member, student ID, section or station…'); card.lay.addWidget(self.att_search)
        self.att_table=make_table(['Member','Student ID','Grade / Section','Action','Time (PH)','Station'],280); self.att_table.horizontalHeader().setSectionResizeMode(4,QHeaderView.ResizeMode.ResizeToContents); card.lay.addWidget(self.att_table)
        self.att_summary=QLabel('Select dates and load records.'); card.lay.addWidget(self.att_summary)
        layout.addWidget(card); self._attendance_rows=[]; self._attendance_generation=0; self._attendance_capped=False
        self.att_search.textChanged.connect(self.apply_attendance_filters); self.att_action.currentIndexChanged.connect(self.apply_attendance_filters)
        self.add_page('attendance',page,self.refresh_attendance)

    def refresh_attendance(self):
        from admin.main import msg
        try: query=attendance_query(self.att_from.date().toPyDate(),self.att_to.date().toPyDate())
        except ValueError as exc: msg(self,'Date range',str(exc),'warning'); return
        self._attendance_generation+=1; generation=self._attendance_generation
        self.att_summary.setText('Loading attendance…')
        def job():
            rows=[]
            while len(rows)<10000:
                batch=self.api.select('library_attendance',query+f'&limit=500&offset={len(rows)}') or []
                rows.extend(batch)
                if len(batch)<500: break
            return rows
        def ok(rows):
            if generation!=self._attendance_generation:return
            self._attendance_capped=len(rows)>=10000; self._attendance_rows=[]
            for r in rows:
                member=r.get('library_members') or {}
                if isinstance(member,list):member=member[0] if member else {}
                try: timestamp=datetime.fromisoformat(r['scanned_at'].replace('Z','+00:00')).astimezone(timezone(timedelta(hours=8))).strftime('%b %d, %Y  %I:%M %p')
                except (ValueError,KeyError,TypeError):timestamp=str(r.get('scanned_at') or '')
                self._attendance_rows.append({'name':member.get('full_name') or 'Unknown member','student_id':member.get('student_id') or '',
                    'grade':' / '.join(str(member.get(k) or '') for k in ('grade_level','section')),'action':r.get('action') or '',
                    'time':timestamp,'station':r.get('station_code') or ''})
            self.apply_attendance_filters()
        def error(exc):
            if generation==self._attendance_generation:self.att_summary.setText('Could not load attendance. '+str(exc))
        self.load(job,ok,error)

    def apply_attendance_filters(self,*_):
        from admin.main import fill,filter_table
        action=self.att_action.currentText()
        rows=[r for r in self._attendance_rows if action=='All actions' or r['action']==action]
        fill(self.att_table,rows,[(key,None) for key in ('name','student_id','grade','action','time','station')])
        filter_table(self.att_table,self.att_search.text())
        visible=[r for r in range(self.att_table.rowCount()) if not self.att_table.isRowHidden(r)]
        ins=sum(self.att_table.item(r,3).text()=='IN' for r in visible)
        suffix=' • Limited to latest 10,000 records; narrow the dates.' if self._attendance_capped else ''
        self.att_summary.setText(f'{len(visible)} records shown • {ins} IN • {len(visible)-ins} OUT'+suffix)
