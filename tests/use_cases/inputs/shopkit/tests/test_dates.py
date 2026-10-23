import unittest
from datetime import date

from shopkit.dates import month_key, parse_date, same_week


class DatesTest(unittest.TestCase):
    def test_parse_date(self):
        self.assertEqual(parse_date("05/03/2026"), date(2026, 3, 5))

    def test_parse_date_spaces(self):
        self.assertEqual(parse_date(" 31/12/2025 "), date(2025, 12, 31))

    def test_month_key(self):
        self.assertEqual(month_key(date(2026, 3, 5)), "2026-03")

    def test_same_week(self):
        self.assertTrue(same_week(date(2026, 10, 19), date(2026, 10, 25)))
        self.assertFalse(same_week(date(2026, 10, 25), date(2026, 10, 26)))


if __name__ == "__main__":
    unittest.main()
