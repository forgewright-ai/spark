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
/usr/bin/python3 tests/widget_pty.py zsh home/.config/spark/widget.zsh
/usr/bin/python3 bin/spark check --selftest
sh tests/install_test.sh
sh tests/get_test.sh
sh tests/update_test.sh
```

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
  metadata, and, for the curated list, the line proof (`spark line`
  answers valid JSON for it).
- Call `git` on `spark line`'s path: the widgets depend on nothing but
  the line contract, and it must never block.
- Write non-ASCII into a doc: the pre-commit hook refuses it, because
  these docs are read on the Linux console too.

## Voice

Lowercase messages, one mark (`*` answer, `!` warn, both OSes), `--`
before the remedy when there is one.
