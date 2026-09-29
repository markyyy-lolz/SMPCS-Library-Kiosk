import unittest
from datetime import date
from urllib.parse import unquote
from shared.admin_features import attendance_query,csv_cell,load_attendance

class ReportsTests(unittest.TestCase):
    def test_inclusive_philippine_dates(self):
        query=unquote(attendance_query(date(2026,9,28),date(2026,9,28)))
        self.assertIn('scanned_at=gte.2026-09-28T00:00:00+08:00',query)
        self.assertIn('scanned_at=lt.2026-09-29T00:00:00+08:00',query)
    def test_invalid_date_range(self):
        with self.assertRaises(ValueError):attendance_query(date(2026,9,29),date(2026,9,28))
    def test_csv_formula_safety(self):
        for value in ('=1+1',' +SUM(A1:A3)','@x','-1+2'):
            self.assertTrue(csv_cell(value).startswith("'"))
        self.assertEqual(csv_cell('Student 123'),'Student 123')

    def test_member_number_is_canonical(self):
        q=attendance_query(date(2026,9,29),date(2026,9,29))
        self.assertIn('member_no',q);self.assertNotIn('student_id',q)
    def test_legacy_identifier_fallback_only_for_missing_column(self):
        from shared.api import ApiError
        class API:
            def __init__(self):self.calls=[]
            def select(self,table,q):
                self.calls.append(q)
                if 'member_no' in q:raise ApiError('column library_members_1.member_no does not exist')
                return [{'library_members':{'student_id':'123'}}]
        api=API();rows=load_attendance(api,date(2026,9,29),date(2026,9,29))
        self.assertEqual(len(api.calls),2);self.assertEqual(rows[0]['library_members']['student_id'],'123')
        class Denied:
            def select(self,*_):raise ApiError('permission denied')
        with self.assertRaisesRegex(ApiError,'permission denied'):load_attendance(Denied(),date(2026,9,29),date(2026,9,29))
