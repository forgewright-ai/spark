import csv
import sys
from collections import defaultdict

from .dates import month_key, parse_date


def read_rows(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["day"] = parse_date(row["date"])
            row["amount"] = int(row["amount"])
            rows.append(row)
    return rows


def by_month(rows):
    totals = defaultdict(int)
    for row in rows:
        totals[month_key(row["day"])] += row["amount"]
    return dict(sorted(totals.items()))


def by_store(rows):
    totals = defaultdict(int)
    for row in rows:
        totals[row["store"]] += row["amount"]
    return dict(sorted(totals.items(), key=lambda kv: -kv[1]))


def average(rows):
    return sum(row["amount"] for row in rows) / len(rows)


def best_day(rows):
    best = max(rows, key=lambda row: row["amount"])
    return best["day"], best["amount"]


def render(rows):
    lines = ["Sales report", ""]
    for month, total in by_month(rows).items():
        lines.append("%s  %8d" % (month, total))
    lines.append("")
    for store, total in by_store(rows).items():
        lines.append("%-10s %8d" % (store, total))
    lines.append("")
    lines.append("average sale  %.2f" % average(rows))
    day, amount = best_day(rows)
    lines.append("best day      %s (%d)" % (day.isoformat(), amount))
    return "\n".join(lines) + "\n"


def main(argv):
    if len(argv) != 2:
        print("usage: report FILE.csv", file=sys.stderr)
        return 2
    sys.stdout.write(render(read_rows(argv[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
