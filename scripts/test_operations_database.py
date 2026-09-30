"""Integration checks on isolated CI database, after the earlier migration suites."""
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import psycopg
from psycopg.types.json import Jsonb
root=Path(__file__).resolve().parent.parent
url=os.environ['TEST_DATABASE_URL']
with psycopg.connect(url,autocommit=True) as db:
    sql=(root/'migrations/20260930115934_library_operations.sql').read_text()
    db.execute(sql);db.execute(sql)
    def rpc(name,*args):
        with db.transaction():
            db.execute('set local role anon')
            return db.execute('select '+name+'('+','.join(['%s']*len(args))+')',tuple(Jsonb(x) if isinstance(x,dict) else x for x in args)).fetchone()[0]
    def denied(fn):
        try:fn()
        except psycopg.Error:return
        raise AssertionError('Expected permission or validation rejection')
    token=rpc('library_account_login','staff','admin','strong-password')['token']
    at=rpc('library_account_login','staff','assistant','strong-password')['token']
    def op(a,d=None,t=token):return rpc('library_operations',t,a,d or {})
    def suite(a,d=None,t=token):return rpc('library_suite',t,a,d or {})
    def account(a,d=None):return rpc('library_account_action',token,a,d or {})
    denied(lambda:op('calendar_save',{'open_days':[1]},at))
    denied(lambda:op('copies',t='invalid'))
    for t in ('library_copies','library_ops_requests','library_handover'):
        denied(lambda t=t:rpc('query_not_a_real_function',t))
        with db.transaction():
            db.execute('set local role anon')
            try:db.execute('select * from '+t)
            except psycopg.errors.InsufficientPrivilege:pass
            else:raise AssertionError('Private table readable')
    mid=str(db.execute("insert into library_members(member_no,rfid_uid,full_name) values('OPS1','OPSCARD','Operations Member') returning id").fetchone()[0])
    account('member_access',{'id':mid,'pin':'123456','active':True})
    mt=rpc('library_account_login','member','OPSCARD','123456')['token']
    denied(lambda:op('search',t=mt))
    bid=str(db.execute("insert into library_books(title,total_copies,available_copies,accession_no) values('Operations Book',2,2,'OPSBOOK') returning id").fetchone()[0])
    copies=op('copies',{'book_id':bid});assert len(copies)==2 and all(c['needs_verification'] for c in copies)
    for i,c in enumerate(copies):op('copy_save',{**c,'rfid':f'OPSCOPY{i}','verified':True})
    assert db.execute('select available_copies from library_books where id=%s',(bid,)).fetchone()[0]==2
    def station(a,d=None):return rpc('library_operations_station','TEST','test-token',a,{'member_rfid':'OPSCARD','scan':'OPSCOPY0',**(d or {})})
    info=station('find');due=info['default_due']
    loan=station('borrow',{'due_date':due})['id'];denied(lambda:station('borrow',{'due_date':due}))
    op('verify_loan',{'id':loan});denied(lambda:op('reject_loan',{'id':loan}))
    assert op('clearance',t=mt)['loans']
    station('return');request=next(r for r in account('return_list') if r['member_no']=='OPS1')
    account('return_review',{'id':request['id'],'approve':True})
    assert not op('clearance',t=mt)['loans']
    assert db.execute('select available_copies from library_books where id=%s',(bid,)).fetchone()[0]==2
    c=copies[0];op('copy_save',{**c,'rfid':'OPSCOPY0','verified':True,'condition':'quarantine'})
    denied(lambda:station('borrow',{'due_date':due}));op('copy_save',{**c,'rfid':'OPSCOPY0','verified':True})
    calendar=op('calendar');op('calendar_save',{'open_days':[1,2,3,4,5],'closed':[{'day':due,'reason':'School holiday'}]})
    denied(lambda:station('borrow',{'due_date':due}));assert station('find')['default_due']!=due
    db.execute(sql);assert op('calendar')['closed'][0]['day']==due
    op('calendar_save',calendar)
    req=op('submit',{'kind':'profile','reason':'Correct spelling','full_name':'Corrected Name','grade_level':'10','section':'A'},mt)
    op('review',{'id':req['id'],'status':'approved'});assert db.execute('select full_name from library_members where id=%s',(mid,)).fetchone()[0]=='Corrected Name'
    denied(lambda:op('review',{'id':req['id'],'status':'approved'}))
    req=op('submit',{'kind':'acquisition','reason':'For our project','title':'A new book','author':'A writer'},mt)
    op('review',{'id':req['id'],'status':'under_review'});op('review',{'id':req['id'],'status':'ordered'});op('review',{'id':req['id'],'status':'added','book_id':bid})
    eid=str(db.execute("insert into library_attendance(member_id,action,scanned_at) values(%s,'IN',now()-interval '2 days') returning id",(mid,)).fetchone()[0])
    assert any(x['stale'] for x in op('occupancy')['people'] if x['member_id']==mid)
    req=op('submit',{'kind':'attendance','attendance_id':eid,'action':'OUT','scanned_at':(datetime.now(timezone.utc)-timedelta(days=2)).isoformat(),'reason':'Missed time out'},mt)
    op('review',{'id':req['id'],'status':'approved'})
    assert not any(x['member_id']==mid for x in op('occupancy')['people'])
    assert db.execute("select count(*) from library_audit_log where action='review' and details->'before' is not null").fetchone()[0]
    reading=op('reading_save',{'name':'Science 10','subject':'Science','grade':'10','book_ids':[bid]})
    assert any(x['books'][0]['id']==bid for x in op('reading',t=mt))
    start=datetime.fromisoformat(due).replace(hour=9,tzinfo=timezone(timedelta(hours=8)))
    booking={'section':'10-A','teacher':'Teacher One','starts_at':start.isoformat(),'ends_at':(start+timedelta(hours=1)).isoformat(),'seats':20}
    visit=op('visit_save',booking);denied(lambda:op('visit_save',booking));op('visit_cancel',{'id':visit['id']})
    hand=op('handover_add',{'message':'Check repaired books'});op('handover_resolve',{'id':hand['id']})
    op('filter_save',{'name':'Our books','search':'Operations','kind':'Book'});assert op('filters');assert not op('filters',t=at)
    assert op('search',{'search':'Operations'});op('closing_save',{})
    # Two concurrent borrowers must never acquire the same physical copy.
    due=station('find')['default_due']
    def borrow_once():
        with psycopg.connect(url,autocommit=True) as cdb:
            try:
                cdb.execute('set role anon')
                return cdb.execute("select library_operations_station('TEST','test-token','borrow',%s)",(Jsonb({'member_rfid':'OPSCARD','scan':'OPSCOPY0','due_date':due}),)).fetchone()[0]
            except psycopg.Error:return None
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:borrow_once(),range(2)))
    assert sum(x is not None for x in results)==1
    # Merges require current preview; preserve source identity for audit.
    dup=str(db.execute("insert into library_members(member_no,full_name) values('OPS2','Corrected Name') returning id").fetchone()[0])
    preview=op('merge_preview',{'kind':'Member','source':dup,'target':mid});assert op('duplicates')
    denied(lambda:op('merge',{'kind':'Member','source':dup,'target':mid,'confirmation':'MERGE','fingerprint':'stale'}))
    op('merge',{'kind':'Member','source':dup,'target':mid,'confirmation':'MERGE','fingerprint':preview['fingerprint']})
    assert not db.execute('select active from library_members where id=%s',(dup,)).fetchone()[0]
    snap=suite('backup');assert snap['format']=='SMPCS operational backup v3';assert 'pin_hash' not in str(snap)
    suite('restore',{'snapshot':snap,'confirmation':'RESTORE'})
    assert len(op('copies',{'book_id':bid}))==2
    denied(lambda:op('my_operations',t=mt)) # Restore revoked member sessions.
    print('PASS operations: migration rerun, roles, copies, stock, quarantine, calendar, approvals, attendance, bookings, reading, clearance, handover, filters, concurrent borrowing, merge preview and restore.')
