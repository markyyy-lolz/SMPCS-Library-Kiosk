import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile,unittest,json
from pathlib import Path
from datetime import date
from unittest.mock import Mock
from shared.suite import read_import,export_rows,due_hint,error_report,StaffAPI
from shared.update_history import record,history

class SuiteTests(unittest.TestCase):
    def test_import_preserves_ids_and_rejects_duplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'members.csv';path.write_text('member_no,rfid_uid,full_name\n0001,0000123,Student\n')
            _,rows=read_import(path,'members');self.assertEqual(rows[0]['rfid_uid'],'0000123')
            path.write_text('member_no,full_name\n1,A\n1,B\n')
            with self.assertRaises(ValueError):read_import(path,'members')
    def test_export_excel_formula_is_text_and_pdf_exists(self):
        from openpyxl import load_workbook
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'report.xlsx';export_rows(path,['Name'],[['=1+1']]);book=load_workbook(path);self.assertEqual(book.active['A2'].data_type,'s');book.close()
            path=Path(folder)/'report.pdf';export_rows(path,['Name','Value'],[['A&B','<Title>']]);self.assertTrue(path.read_bytes().startswith(b'%PDF'))
    def test_due_dates_in_philippine_time(self):
        self.assertEqual(due_hint('2026-09-29T16:00:00Z','borrowed',date(2026,9,29)),'Due tomorrow')
        self.assertEqual(due_hint('2026-09-26T00:00:00Z','borrowed',date(2026,9,29)),'3 days overdue')
    def test_diagnostics_never_copies_supplied_secrets(self):
        text=error_report('HTTP 401 password=secret TOKEN super-secret account John Smith')
        self.assertNotIn('super-secret',text);self.assertNotIn('John Smith',text);self.assertIn('HTTP 401',text)
    def test_history_records_once_per_version(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'history.json';record('1.5.5','Old',path);record('1.5.5','Old',path);record('1.6.0','New',path)
            self.assertEqual(len(history(path)),2)
    def test_staff_writes_pass_session_to_server(self):
        api=Mock();wrapped=StaffAPI(api,{'token':'session'})
        wrapped.rpc('library_save_book',{'p_title':'Book'})
        api.rpc.assert_called_once_with('library_staff_rpc',{'p_token':'session','p_name':'library_save_book','p_args':{'p_title':'Book'}})
