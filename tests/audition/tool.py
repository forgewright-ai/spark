#!/usr/bin/env python3
"""tally -- count lines, words and characters in files, as a table."""

import sys


def tally(path):
    lines = words = chars = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            lines += 1
            chars += len(line)
            words += len(line.split())
    return lines, words, chars


def main(argv):
    if not argv:
        print("usage: tally FILE...", file=sys.stderr)
        return 2
    bad = False
    total = [0, 0, 0]
    for path in argv:
        try:
            row = tally(path)
        except OSError as e:
            print("tally: %s: %s" % (path, e.strerror), file=sys.stderr)
            bad = True
            continue
        total = [a + b for a, b in zip(total, row)]
        print("%8d %8d %8d  %s" % (row + (path,)))
    if len(argv) > 1:
        print("%8d %8d %8d  total" % tuple(total))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
