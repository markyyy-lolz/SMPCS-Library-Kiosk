"""Suite integration test; uses an isolated CI PostgreSQL database."""
import os,uuid
from pathlib import Path
import psycopg
from psycopg.types.json import Jsonb
root=Path(__file__).resolve().parent.parent
with psycopg.connect(os.environ['TEST_DATABASE_URL'],autocommit=True) as db:
    migration=(root/'migrations/003_library_suite.sql').read_text();db.execute(migration);db.execute(migration)
    def rpc(name,*args):
        with db.transaction():
            db.execute('SET LOCAL ROLE anon')
            return db.execute('SELECT '+name+'('+','.join(['%s']*len(args))+')',tuple(Jsonb(x) if isinstance(x,dict) else x for x in args)).fetchone()[0]
    def denied(fn):
        try:fn()
        except psycopg.Error:return
        raise AssertionError('Operation should be rejected')
    admin=rpc('library_account_login','staff','admin','strong-password');token=admin['token']
    def suite(action,data=None,t=token):return rpc('library_suite',t,action,data or {})
    def account(action,data=None,t=token):return rpc('library_account_action',t,action,data or {})
    def station(action,data=None):return rpc('library_suite_station','TEST','test-token',action,data or {})
    assistant=account('staff_save',{'username':'assistant','full_name':'Assistant','role':'assistant','active':True,'password':'strong-password'})
    at=rpc('library_account_login','staff','assistant','strong-password')['token']
    denied(lambda:suite('maintenance',{'enabled':True},at));denied(lambda:account('member_save',{'member_no':'S2'},at))
    denied(lambda:rpc('library_save_book','RF','AC','Title','Author','Category','Shelf',1))
    denied(lambda:rpc('library_staff_rpc',at,'library_save_book',{}))
    reg=station('register',{'student_id':'NEW1','rfid':'NEWCARD','full_name':'New Student','grade_level':'10','section':'A'})
    denied(lambda:station('register',{'student_id':'NEW1','rfid':'NEWCARD','full_name':'New Student'}))
    suite('review',{'id':reg['id'],'decision':'approved'})
    denied(lambda:suite('review',{'id':reg['id'],'decision':'approved'}))
    mid=db.execute("select id from library_members where member_no='NEW1'").fetchone()[0]
    account('member_access',{'id':str(mid),'pin':'123456','active':True})
    mt=rpc('library_account_login','member','NEWCARD','123456')['token']
    denied(lambda:suite('notifications',t=mt));suite('continue_session',t=mt)
    suite('import',{'kind':'books','rows':[{'accession_no':'AC1','book_rfid':'BOOKCARD','title':'New Book','total_copies':1,'shelf':'A1'}]})
    bid=db.execute("select id from library_books where accession_no='AC1'").fetchone()[0]
    denied(lambda:suite('import',{'kind':'books','rows':[{'accession_no':'AC2','title':'Rollback book'},{'accession_no':'AC1','title':'Duplicate'}]}))
    assert db.execute("select count(*) from library_books where accession_no='AC2'").fetchone()[0]==0
    suite('book_details',{'id':str(bid),'shelf':'B1','cover_data':None})
    assert suite('catalog',t=mt)[0]
    loan=db.execute('insert into library_loans(member_id,book_id) values(%s,%s) returning id',(mid,bid)).fetchone()[0]
    db.execute('update library_books set available_copies=0 where id=%s',(bid,))
    reservation=suite('request',{'kind':'reservation','book_id':str(bid)},mt)
    renewal=suite('request',{'kind':'renewal','loan_id':str(loan),'days':7},mt)
    denied(lambda:suite('review',{'id':renewal['id'],'decision':'approved'}))
    suite('cancel_request',{'id':reservation['id']},mt)
    old=db.execute('select due_at from library_loans where id=%s',(loan,)).fetchone()[0]
    suite('review',{'id':renewal['id'],'decision':'approved'})
    assert db.execute('select due_at from library_loans where id=%s',(loan,)).fetchone()[0]>old
    feedback=suite('request',{'kind':'feedback','message':'Please fix the shelf label.'},mt)
    suite('review',{'id':feedback['id'],'decision':'resolved','note':'Done'})
    suite('incident',{'loan_id':str(loan),'type':'damaged','message':'Cover torn; assessed at desk'})
    assert suite('notifications',t=at)
    assert suite('requests',{'kind':'feedback','status':'All'})
    assert suite('my_requests',t=mt)
    assert rpc('library_staff_rpc',token,'library_save_book',{'p_book_rfid':'OTHERBOOK','p_accession_no':'OTHERACC','p_title':'Other','p_author':'Author','p_category':'General','p_shelf':'B2','p_total_copies':1})
    suite('announce',{'title':'Notice','message':'Library event','expires_at':'2099-01-01T00:00:00Z'})
    assert station('status')['announcements']
    suite('maintenance',{'enabled':True,'message':'Reopens 2 PM'})
    assert station('status')['maintenance']
    denied(lambda:station('register',{'student_id':'X','rfid':'X','full_name':'Paused'}))
    suite('maintenance',{'enabled':False,'message':''})
    inv=suite('inventory_start',{'name':'September'})
    suite('inventory_scan',{'session_id':inv['id'],'rfid':'BOOKCARD','shelf':'WRONG'})
    assert any(r['status']=='Misplaced' for r in suite('inventory_results',{'session_id':inv['id']}))
    suite('inventory_close',{'session_id':inv['id']})
    denied(lambda:suite('inventory_scan',{'session_id':inv['id'],'rfid':'BOOKCARD','shelf':'B1'}))
    assert suite('reports',{'kind':'borrowed','start':'2000-01-01T00:00:00Z','end':'2099-01-01T00:00:00Z'})
    suite('rfid_replace',{'member_id':str(mid),'new_rfid':'REPLACED'})
    assert rpc('library_account_login','member','NEWCARD','123456').get('error')
    denied(lambda:suite('my_requests',t=mt))
    denied(lambda:account('member_save',{'member_no':'OTHER','rfid_uid':'NEWCARD','full_name':'Other','member_type':'student'}))
    suite('promote',{'ids':[str(mid)],'school_year':'2027-2028','grade_level':'11','section':'B','archive':False})
    backup=suite('backup');assert backup['format']=='SMPCS operational backup v2'
    assert 'password_hash' not in str(backup) and 'pin_hash' not in str(backup)
    db.execute("update library_members set full_name='Changed' where id=%s",(mid,))
    denied(lambda:suite('restore',{'snapshot':backup,'confirmation':'wrong'}))
    suite('restore',{'snapshot':backup,'confirmation':'RESTORE'})
    assert db.execute('select full_name from library_members where id=%s',(mid,)).fetchone()[0]=='New Student'
    assert suite('restore_points')
    print('PASS: suite rerun, live roles, registration, duplicate rollback, renewals, reservations, feedback, maintenance, inventory, reports, RFID revocation, promotion, backup and restore.')
