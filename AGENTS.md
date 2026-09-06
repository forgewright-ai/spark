# spark -- for agents and contributors

spark is a local AI at your shell prompt, bare bones, for Linux and
macOS; nothing leaves the machine except pinned downloads and your own
talk to a model you run.

## The landing rule

A change is done only when it is in all of: `spark help` (a line in
`bin/spark`'s `USAGE`), a `spark <verb>` that sets and applies it (never
just a `site.env` key by hand), a `spark check` row when it is a promise
the machine makes, and every doc (`README.md` / `INSTALL.md` /
`CHEATSHEET.txt` / `CHANGELOG.md`). Apply it, reproduce it in
`bootstrap.sh` / `install.sh`, detect it in a check row, explain it in
every doc -- or it is not done.

## The grammar

Bare verb = show, never mutate (`spark bar` piped still prints the bar
line -- tmux depends on it); `on|off` is the only switch vocabulary at
the CLI (storage stays `yes|no`); `status` = bare, `list` = the table;
`-h` answers first, signed `spark <sub> -- <one line>`; confirms are
`<question>? yes/NO: ` (`confirm()`); waits are one dot-spinner
(`wait_ready()`), downloads curl's bar; exit codes: 0 ok/show, 1 the
world (stderr), 2 the invocation (stdout, signed), 78 config, 130
SIGINT. `CLAUDE.md`'s "The grammar" is the full text.

## The gate, before every commit

```sh
/usr/bin/python3 -m py_compile lib/spark/*.py bin/spark
sh -n bootstrap.sh install.sh lib/env.sh
shellcheck -S warning bootstrap.sh install.sh lib/env.sh
/usr/bin/python3 tests/smoke.py
/usr/bin/python3 tests/serve_smoke.py
/usr/bin/python3 tests/forge_smoke.py
/usr/bin/python3 tests/bench_smoke.py
/usr/bin/python3 tests/docs_test.py
/usr/bin/python3 tests/vault_test.py
/usr/bin/python3 tests/site_test.py
/usr/bin/python3 tests/widget_pty.py zsh home/.config/spark/widget.zsh
/usr/bin/python3 tests/widget_pty.py pager
/usr/bin/python3 tests/widget_pty.py completion zsh home/.config/spark/completion.zsh
/usr/bin/python3 tests/micro_pty.py
/usr/bin/python3 bin/spark check --selftest
sh tests/install_test.sh
sh tests/get_test.sh
sh tests/update_test.sh
```

(`tests/check_selftest.py` is the hook's entry to `spark check --selftest`.)

## The audition: the editor's briefs, judged blind

Not in the gate -- it needs a live brain -- and the one test that judges
words. `tests/audition.py` runs eight fixtures (`tests/audition/`: a poem,
a chapter, a README, a commit message, Portuguese prose, Go, Python,
shell) through the real `spark edit` -- complete, rewrite, `?` -- against
the brain this machine answers from, and scores every answer with
mechanical lints only (no fence, no preamble, a poem keeps its lines,
code still compiles, the language holds, at most five notes, every quote
anchors, no `"X" -> "X"`, no praise opener). It prints a table and never
an answer unless `-v`.

The rule: a change to any `edit-*` brief in `persona.py` carries the
audition's before and after totals in the PR (`--times 3`: a small model
is not deterministic). `--json` appends the model, the briefs' hashes
and the totals to `STATE_DIR/audition.jsonl`, so two briefs are compared
by number, never by taste.

## Contracts

The interfaces between parts -- `spark line`, `spark check`, config file
shape, the FORGE's HTTP API and the rest -- live in `CLAUDE.md`. Read
them there; do not duplicate them here or let this file drift from it.

## Privacy

No person, machine, or project name belongs in this tree. The personal
word list lives outside the repo, at `~/.config/spark/privacy-terms`
(one word per line, 0600), never committed. The pre-commit hook prints a
NOTICE when that list is absent -- expected on a fresh clone or a fork --
and still enforces e-mail addresses, private IPv4 ranges, and absolute
home paths naming a user, with no skip path for those.

## Never

- Apply `bootstrap.sh` or `install.sh` against a real `HOME` in a test --
  use a throwaway `HOME` and the matching `XDG_*` dirs.
- Change the banner (`home/.config/spark/banner`): it is spark's own
  artwork.
- Add a model row without its size and sha256 from Hugging Face's file
  metadata and its license, or mark one `_TESTED="line"` without the
  line proof (`spark line` answers valid JSON for it).
- Call `git` on `spark line`'s path: the widgets depend on nothing but
  the line contract, and it must never block.
- Write non-ASCII into a doc: the pre-commit hook refuses it, because
  these docs are read on the Linux console too.

## Voice

Lowercase messages, one mark (`*` answer, `!` warn, both OSes), `--`
before the remedy when there is one.
