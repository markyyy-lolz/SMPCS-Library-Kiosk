"""Runs against an isolated PostgreSQL CI database, never the school database."""
import os
from pathlib import Path
from datetime import datetime,timezone,timedelta
import uuid
import psycopg
from psycopg.types.json import Jsonb
ROOT=Path(__file__).resolve().parent.parent
with psycopg.connect(os.environ['TEST_DATABASE_URL'],autocommit=True) as db:
    db.execute('CREATE ROLE anon; CREATE ROLE authenticated;')
    db.execute((ROOT/'SMPCS_LIBRARY_FULL_DATABASE.sql').read_text())
    migration=(ROOT/'migrations/002_accounts_services.sql').read_text()
    db.execute(migration);db.execute(migration)
    admin_id=db.execute("INSERT INTO library_users(username,full_name,password_hash,role) VALUES('admin','Admin',crypt('strong-password',gen_salt('bf',4)),'admin') RETURNING id").fetchone()[0]
    mid=db.execute("INSERT INTO library_members(member_no,rfid_uid,full_name) VALUES('S1','CARD1','Student One') RETURNING id").fetchone()[0]
    bid=db.execute("INSERT INTO library_books(title,total_copies,available_copies) VALUES('Book',1,0) RETURNING id").fetchone()[0]
    loan=db.execute("INSERT INTO library_loans(member_id,book_id,due_at) VALUES(%s,%s,now()-interval '1 day') RETURNING id",(mid,bid)).fetchone()[0]
    db.execute("INSERT INTO library_kiosk_stations(station_code,station_name,station_token) VALUES('TEST','Test','test-token')")
    def rpc(name,*args):
        with db.transaction():
            db.execute('SET LOCAL ROLE anon')
            return db.execute('SELECT '+name+'('+','.join(['%s']*len(args))+')',tuple(Jsonb(x) if isinstance(x,dict) else x for x in args)).fetchone()[0]
    def denied(fn):
        try:fn()
        except psycopg.Error:return
        raise AssertionError('Unauthorized operation succeeded')
    user=rpc('library_account_login','staff','admin','strong-password');assert user['token'] and 'password_hash' not in user
    token=user['token']
    def act(action,data=None,t=token):return rpc('library_account_action',t,action,data or {})
    denied(lambda:rpc('library_login','admin'))
    denied(lambda:rpc('library_return',loan,'attacker'))
    denied(lambda:rpc('library_save_member','S1','OTHER','Changed','student','','',''))
    denied(lambda:act('staff_list',t='fake'))
    act('member_access',{'id':str(mid),'pin':'123456','active':True})
    member=rpc('library_account_login','member','CARD1','123456');mt=member['token']
    profile=act('profile',t=mt);assert profile['member']['id']==str(mid) and profile['loans'][0]['overdue']
    denied(lambda:act('staff_list',t=mt));denied(lambda:act('backup',t=mt));denied(lambda:act('member_access',{'id':str(mid),'active':False},t=mt))
    act('change_pin',{'current_pin':'123456','pin':'654321'},t=mt)
    assert rpc('library_account_login','member','CARD1','123456').get('error')
    assert rpc('library_account_login','member','CARD1','654321').get('token')
    staff=act('staff_save',{'username':'helper','full_name':'Librarian','role':'librarian','active':True,'password':'another-password'})
    librarian=rpc('library_account_login','staff','helper','another-password')
    denied(lambda:act('staff_list',t=librarian['token']))
    denied(lambda:act('staff_save',{'id':str(admin_id),'username':'admin','full_name':'Admin','role':'admin','active':False}))
    def service(action,data):return rpc('library_station_service','TEST','test-token',action,data)
    service('return_request',{'loan_id':str(loan),'rfid':'CARD1'});service('return_request',{'loan_id':str(loan),'rfid':'CARD1'})
    requests=act('return_list');assert len(requests)==1
    assert db.execute('SELECT available_copies FROM library_books WHERE id=%s',(bid,)).fetchone()[0]==0
    act('return_review',{'id':requests[0]['id'],'approve':True},t=librarian['token'])
    denied(lambda:act('return_review',{'id':requests[0]['id'],'approve':True}))
    assert db.execute('SELECT available_copies FROM library_books WHERE id=%s',(bid,)).fetchone()[0]==1
    ts=datetime.now(timezone.utc)-timedelta(seconds=30)
    event={'id':str(uuid.uuid4()),'rfid':'CARD1','scanned_at':ts.isoformat()}
    assert service('attendance_event',event)['action']=='IN'
    assert service('attendance_event',event)['action']=='IN'
    duplicate=dict(event,id=str(uuid.uuid4()),scanned_at=(ts+timedelta(seconds=2)).isoformat());assert service('attendance_event',duplicate)['duplicate']
    next_event=dict(event,id=str(uuid.uuid4()),scanned_at=(ts+timedelta(seconds=20)).isoformat());assert service('attendance_event',next_event)['action']=='OUT'
    denied(lambda:service('attendance_event',dict(event,id=str(uuid.uuid4()))))
    assert db.execute('SELECT count(*) FROM library_attendance').fetchone()[0]==2
    snapshot=act('backup');assert len(snapshot['attendance'])==2 and 'pin_hash' not in str(snapshot) and 'password_hash' not in str(snapshot)
    act('member_access',{'id':str(mid),'active':False});denied(lambda:act('profile',t=mt));assert rpc('library_account_login','member','CARD1','654321').get('error')
    for _ in range(5):assert rpc('library_account_login','staff','helper','wrong').get('error')
    assert 'Too many' in rpc('library_account_login','staff','helper','another-password')['error']
    act('logout');denied(lambda:act('backup'))
    print('PASS: migration twice, server roles, login lockout, PIN changes, session invalidation, return approval, attendance idempotency, backups, last-admin protection.')
