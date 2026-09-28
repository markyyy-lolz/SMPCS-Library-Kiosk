import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone,timedelta
from shared.services import Outbox,save_backup
from shared.api import ApiError,NetworkError
class ServiceTests(unittest.TestCase):
    def test_outbox_survives_lost_response_with_same_id(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'outbox.db';q=Outbox(path);event=q.add('TEST','CARD1');seen=[]
            class API:
                def rpc(self,name,p):
                    seen.append(p['p_data']['id'])
                    if len(seen)==1:raise NetworkError('response lost')
                    return {'action':'IN'}
            api=API();cfg={'STATION_CODE':'TEST','STATION_TOKEN':'token'}
            self.assertEqual(q.sync(api,cfg)['pending'],1)
            self.assertEqual(Outbox(path).sync(api,cfg)['pending'],0)
            self.assertEqual(seen,[event['id'],event['id']])
    def test_rejected_scan_retained_and_other_station_isolated(self):
        with tempfile.TemporaryDirectory() as root:
            q=Outbox(Path(root)/'db');q.add('A','CARD');q.add('B','CARD')
            class API:
                def rpc(self,*a):raise ApiError('inactive card')
            self.assertEqual(q.sync(API(),{'STATION_CODE':'A','STATION_TOKEN':'x'})['pending'],1)
            self.assertEqual(q.rows('A')[0]['error'],'inactive card');self.assertIsNone(q.rows('B')[0]['error'])
    def test_duplicate_tap_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            q=Outbox(Path(root)/'db');now=datetime.now(timezone.utc);q.add('A','CARD',now)
            with self.assertRaises(ApiError):q.add('A','CARD',now+timedelta(seconds=2))
            q.add('A','CARD',now+timedelta(seconds=12));self.assertEqual(len(q.rows('A')),2)
    def test_backup_retention_and_invalid_response(self):
        with tempfile.TemporaryDirectory() as root:
            class API:
                def rpc(self,*a):return {'format':'SMPCS operational backup v1','members':[]}
            for _ in range(9):save_backup(API(),{'token':'test'},root)
            self.assertEqual(len(list(Path(root).glob('*.json'))),7)
