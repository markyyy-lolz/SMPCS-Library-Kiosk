import unittest
from datetime import date
from urllib.parse import unquote
from shared.admin_features import attendance_query,csv_cell

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
