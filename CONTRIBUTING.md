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
git config core.hooksPath .githooks
```

Then the gate: the list in `AGENTS.md`, run in that order, is what the
pre-commit hook runs -- one copy, there. shellcheck is a contributor's
tool, not a user's package: `apt-get install shellcheck` or `brew install
shellcheck` (the hook skips it with a notice when absent). Changing
one of the editor's briefs (`persona.MODE_EDIT_*`)? Run
`tests/audition.py` against a live brain and put its before and after
totals in the pull request -- the briefs are judged by lints, not taste.

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

An editor or another app becomes smart by being a client of one spark
verb (`spark edit`, `spark line`, the FORGE's API), in a repository of
its own -- spark-micro is the shape. spark itself ships no app, no app
package and no app check row; a pull request adding one is turned into a
pointer to the app's own repository.

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

`ROADMAP.md` lists what comes next; an idea that is not there is an
issue away.
