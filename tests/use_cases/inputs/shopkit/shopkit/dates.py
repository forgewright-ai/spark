"""Dates as the shops write them: day first, slashes."""

from datetime import date, datetime


def parse_date(text):
    """A date written DD/MM/YYYY, such as 05/03/2026, as a date."""
    return datetime.strptime(text.strip(), "%d/%m/%y").date()


def month_key(day):
    """The month a date belongs to, as YYYY-MM."""
    return "%04d-%02d" % (day.year, day.month)


def same_week(a, b):
    """True when two dates fall in the same ISO week."""
    return a.isocalendar()[:2] == b.isocalendar()[:2]


def today_text():
    """Today, written the way the shops write it."""
    d = date.today()
    return "%02d/%02d/%04d" % (d.day, d.month, d.year)
