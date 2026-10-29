---
name: spark-add-check-row
description: Add a row to spark check the way docs/REFERENCE.md says, with its fixture, its selftest proof and the doc counts. Use when asked to add, change or prove a check row.
argument-hint: NAME
---
# Add the check row $0

Read docs/REFERENCE.md, "The four obligations", and under "Adding
things" the bullet "A check row". A row is a promise the machine makes,
and a check that has only ever returned one answer has never been
tested.

1. The row: `row_$0(ctx)` in `lib/spark/check.py`, decorated
   `@row(CATEGORY, fixture=True)` or `@row(CATEGORY, fixture=False,
   reason="...")`. A CAPABILITY row answers ok, warn or na, never fail.
   The remedy is the command that fixes it, when one does.
2. The fixture: extend `make_fixture` so the row is ok in the good
   fixture and not ok in the bad one. `spark check --selftest` refuses a
   fixture row that does not flip, and a row with `fixture=False` must
   say why in `reason`.
3. The proof: `spark check --selftest`. Then break the thing on purpose
   on this machine, watch `spark check $0` go red, and put it back.
4. The counts: docs/REFERENCE.md says how many rows `spark check` has
   today and how many in each category, and docs/INSTALL.md states the
   count too. `python3 tests/docs_test.py` holds both to `check.py`.
5. The docs: one line under the top section of docs/CHANGELOG.md, and
   docs/INSTALL.md where the row's promise is explained.
6. The gate: `sh tests/gate.sh fast`, then `python3
   tests/check_selftest.py`.

Report the row's category, its remedy, and the selftest line that
proves it flips.
