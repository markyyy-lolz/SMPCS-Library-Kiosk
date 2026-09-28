"""Account RPCs, durable attendance outbox and operational backups."""
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from shared.config import APP_DIR
from shared.api import ApiError, NetworkError

MIGRATION_HELP='Apply migrations/002_accounts_services.sql in Supabase SQL Editor, then sign in again.'

def login(api,kind,identity,secret):
    result=api.rpc('library_account_login',{'p_kind':kind,'p_identity':identity,'p_secret':secret})
    if not isinstance(result,dict) or result.get('error'):raise ApiError((result or {}).get('error','Sign-in failed.'))
    return result

def account(api,user,action,data=None):
    if not user.get('token'):raise ApiError(MIGRATION_HELP)
    return api.rpc('library_account_action',{'p_token':user['token'],'p_action':action,'p_data':data or {}})

def station(api,cfg,action,data):
    return api.rpc('library_station_service',{'p_station':cfg['STATION_CODE'],'p_token':cfg['STATION_TOKEN'],'p_action':action,'p_data':data})

class Outbox:
    def __init__(self,path=None):
        self.path=Path(path or APP_DIR/'attendance_outbox.sqlite3'); self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:db.execute('CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, station TEXT NOT NULL, rfid TEXT NOT NULL, scanned_at TEXT NOT NULL, error TEXT)')
    def connect(self):return sqlite3.connect(self.path,timeout=20)
    def add(self,code,rfid,now=None):
        stamp=(now or datetime.now(timezone.utc)).isoformat(); event={'id':str(uuid.uuid4()),'rfid':rfid,'scanned_at':stamp}
        with self.connect() as db:
            last=db.execute('SELECT scanned_at FROM events WHERE station=? AND rfid=? ORDER BY scanned_at DESC LIMIT 1',(code,rfid)).fetchone()
            if last and (datetime.fromisoformat(stamp)-datetime.fromisoformat(last[0])).total_seconds()<10:raise ApiError('Card already queued. Wait a few seconds before tapping again.')
            db.execute('INSERT INTO events VALUES(?,?,?,?,NULL)',(event['id'],code,rfid,stamp))
        return event
    def rows(self,code):
        with self.connect() as db:
            db.row_factory=sqlite3.Row
            return [dict(r) for r in db.execute('SELECT * FROM events WHERE station=? ORDER BY scanned_at,id',(code,))]
    def sync(self,api,cfg):
        count=0
        for row in self.rows(cfg['STATION_CODE']):
            try:station(api,cfg,'attendance_event',{k:row[k] for k in ('id','rfid','scanned_at')})
            except NetworkError:break
            except Exception as exc:
                with self.connect() as db:db.execute('UPDATE events SET error=? WHERE id=?',(str(exc)[:500],row['id']))
                break  # Keep order; never silently drop rejected scans.
            else:
                with self.connect() as db:db.execute('DELETE FROM events WHERE id=?',(row['id'],))
                count+=1
        return {'synced':count,'pending':len(self.rows(cfg['STATION_CODE']))}


def save_backup(api,user,directory=None):
    folder=Path(directory or APP_DIR/'backups');folder.mkdir(parents=True,exist_ok=True)
    data=account(api,user,'backup')
    if not isinstance(data,dict) or data.get('format')!='SMPCS operational backup v1':raise ApiError('Invalid backup response')
    name='library-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')+'.json'
    path=folder/name;tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)
    for old in sorted(folder.glob('library-*.json'))[:-7]:old.unlink()
    return str(path)
