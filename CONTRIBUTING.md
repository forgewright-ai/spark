# Contributing to spark

Thanks for looking. spark is a local AI at the shell prompt, for Linux
and macOS; this file is the short path to a change that lands.

## Clone and run the gate

No special hardware is needed: the tests are hermetic (a stub
llama-server, throwaway `HOME` and `XDG_*` dirs), and CI runs the same
gate on Ubuntu, Debian 13, and macOS.

```sh
git clone https://github.com/forgewright-ai/spark.git
cd spark
/usr/bin/python3 -m py_compile lib/spark/*.py bin/spark
sh -n bootstrap.sh install.sh lib/env.sh
shellcheck -S warning bootstrap.sh install.sh lib/env.sh
/usr/bin/python3 tests/smoke.py
/usr/bin/python3 tests/serve_smoke.py
/usr/bin/python3 tests/forge_smoke.py
/usr/bin/python3 tests/bench_smoke.py
/usr/bin/python3 tests/widget_pty.py zsh home/.config/spark/widget.zsh
/usr/bin/python3 tests/widget_pty.py pager
/usr/bin/python3 tests/widget_pty.py completion zsh home/.config/spark/completion.zsh
/usr/bin/python3 bin/spark check --selftest
sh tests/install_test.sh
sh tests/get_test.sh
sh tests/update_test.sh
```

The full list, and why each step matters, is in `AGENTS.md`.

## Branch model

`main` is development; a git tag is a release. Users' clones follow the
newest tag; a developer's clone follows `main`. `spark update` moves
either one forward and converges the machine.

## Three ways to contribute without writing code

1. **A model row.** One row per pull request, in `models.env`: the
   five fields (size and sha256 from Hugging Face's file metadata), its
   `_LICENSE`, an optional `_NOTE`; `_TESTED="line"` only with the line
   proof (`spark line` answers it with valid JSON). A proof for a row
   that is already there is a pull request too.
2. **A CREDITS correction.** A wrong version, a missing license, a name
   that changed -- `CREDITS.md` is a pull request away from being right.
3. **A doc fix.** A stale count, a broken cross-reference, a sentence
   that no longer matches the code.

## Code changes

Follow the landing rule in `AGENTS.md`: a feature is not done until it
is in `spark help`, a `spark <verb>`, a `spark check` row (when it is a
promise), and every doc. Run the gate above before you open a pull
request.

Commit messages: a lowercase title line, and a body that says why, not
just what. No trailers are required from you.

## Privacy gate

The pre-commit hook checks staged changes for e-mail addresses, private
IPv4 ranges, and absolute home paths naming a user; it also reads a
personal word list that does not exist in your fork, so you will see a
NOTICE that it is missing. That is expected -- your fork has no personal
list to enforce. Never add a real person's, machine's, or project's name
to the tree regardless.

## Where to ask

Open an issue. `.github/ISSUE_TEMPLATE/` has a form for a model row and
one for a bug; anything else is a blank issue.

## Roadmap

`ROADMAP.md` lists what comes next, the editor first; an idea that is
not there is an issue away.
