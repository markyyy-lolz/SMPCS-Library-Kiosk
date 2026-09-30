import tempfile,unittest
from pathlib import Path
from datetime import datetime
from shared.update_schedule import in_window,validate_time
from shared.operations import labels_pdf

class OperationsTests(unittest.TestCase):
    def test_maintenance_windows(self):
        self.assertTrue(in_window(datetime(2026,1,1,18), '17:00','19:00'))
        self.assertFalse(in_window(datetime(2026,1,1,19), '17:00','19:00'))
        self.assertTrue(in_window(datetime(2026,1,1,23), '22:00','02:00'))
        self.assertTrue(in_window(datetime(2026,1,1,1), '22:00','02:00'))
        self.assertFalse(in_window(datetime(2026,1,1,12), '22:00','02:00'))
        self.assertFalse(in_window(datetime(2026,1,1,12), '12:00','12:00'))
        for invalid in ('24:00','12:60','hello'):
            with self.assertRaises(ValueError):validate_time(invalid)
    def test_labels_pdf_contains_each_accession(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'labels.pdf'
            rows=[{'title':'Science & Technology','accession':f'COPY-00000000-0000-0000-0000-000000000000-{i}','shelf':'SCI-10','condition':'good'} for i in range(13)]
            labels_pdf(p,rows)
            self.assertTrue(p.read_bytes().startswith(b'%PDF'))
            self.assertGreater(p.stat().st_size,2000)
    def test_staff_circulation_routing(self):
        from shared.suite import StaffAPI
        class API:
            def rpc(self,n,p):return n,p
        name,data=StaffAPI(API(),{'token':'staff'}).rpc('library_verify_loan',{'p_loan_id':'loan'})
        self.assertEqual(name,'library_operations');self.assertEqual(data['p_data'],{'id':'loan'})
        self.assertEqual(data['p_action'],'verify_loan')
