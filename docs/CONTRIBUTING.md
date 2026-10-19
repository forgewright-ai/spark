# Contributing to spark

spark is a local AI at the shell prompt, for Linux and macOS. This file
is the short path to a change that lands.

## Clone and run the gate

The tests use a stub llama-server, a throwaway `HOME` and `XDG_*`
dirs. No model is needed. "A test baseline" below records the host
prerequisites.

```sh
git clone https://github.com/forgewright-ai/spark.git
cd spark
git config core.hooksPath .githooks
```

A commit runs the fast half of the gate, in seconds: privacy, secrets,
syntax, shellcheck and the docs. The full gate runs in CI, once for
each commit, on Ubuntu and macOS. CI also runs the one-liner in Debian
13, Arch, Void, Fedora and openSUSE Tumbleweed containers. `sh
tests/gate.sh full` runs the full gate on your own machine, in about
10 minutes. `AGENTS.md`, "The gate", lists every step.

A pull request runs CI for you. With push rights, `sh tests/land.sh`
sends your commit to a `try/` branch and waits for CI. On green it
moves `main` to the same commit. On red `main` is untouched: fix the
commit, amend it and run it again. A push to `main` that CI has not
passed is refused.

shellcheck is a contributor's tool, not a user's package: `apt-get
install shellcheck`, `pacman -S shellcheck`, `xbps-install shellcheck`,
`dnf install ShellCheck`, `zypper install ShellCheck` or `brew install
shellcheck`. The gate skips it with a notice when absent. `gh`,
GitHub's command line, is what `tests/land.sh` asks CI with.

### A test baseline

To record a run, use the Python you want to test:

```sh
python3 tests/baseline.py
python3 tests/baseline.py smoke
python3 tests/baseline.py --probe-readline
```

The runner prints the Python version, line editor, terminal, init
override and ownership prerequisites. It calls the same gate and
keeps its exit status. Each group is passed, failed, blocked or unrun;
skipped checks remain in the output. No assertion is disabled.
On Linux it reaps orphaned children, which a container's first
process may leave behind. Live model and hardware checks stay unrun.

The runner pins launchd or systemd; runit cases set their own seam.
Smoke also pins its defaults when called without the runner.
Voice pins its terminal and checks that `TERM=dumb` stays plain.
On Linux, a libedit Python may lose a full line when the kernel
refuses terminal input injection. The isolated readline probe records
that failure without a model. Compare it with a GNU readline Python
before assigning the failure to the model or the test fixture.

MCP requires its executable and every ancestor to be owned by root
or the current user, with safe write permissions. A container with
foreign-owned paths cannot pass those checks or their selftest.
Do not relax the checks to make the gate pass.

A sandbox may put empty `.git` directories above temporary files.
The uninstall guard treats them as checkouts and retains linked rc
files. That detection edge is separate from an unsafe removal.
Record missing tools as skipped and unresolved checks as failed.

A change to one of the editor's briefs (`persona.MODE_EDIT_*`) needs
more. Run `tests/audition.py` against a live model and put its before
and after totals in the pull request. The briefs are judged by lints,
not taste.

A change to the prompt line's brief (`persona.MODE_LINE` or its schema)
needs the same. Run `tests/line_audition.py run` for each OS and put the
`report` table, before and after, in the pull request. A change to what
the line knows (the store, the search, the verdict) adds `recall` per
OS and the 3 arms of `run --arm`. `AGENTS.md`, "The audition", holds
the bar.

The audition's held-out questions never change. Never tune a help
row, a brief or the knowledge on them. A change to the line reports
the held-out score beside the other.

## Branch model

`main` is development. A git tag signed by a release key, a line in
`allowed-signers`, is a release. A user's clone follows the newest
release tag, and a developer clone follows `main`. `spark update` moves
either one forward and converges the machine. A tag no release key
signed moves nothing.

Two kinds of release come off `main`. A major, `v1.88`, is a planned
piece of work, tagged by a person. A patch, `v1.88.1`, is one or more
reported bugs fixed, tagged by a machine with a release key:
`tests/tag.sh` is the rule it follows. An S1 or S2 fix is tagged once
it has rested 6 hours on `main`, an S3 or S4 fix on Sunday. The tagger
checks for itself that no protected path changed and that each fix's
issue exists, is approved and carries its severity. A patch opens only
when `main` holds
nothing unreleased. It never adds a command, an option, a key, a check
row or a help row, and `tests/patch_test.py` refuses one that does.
`AGENTS.md`, "The patch lane", has the whole of it.

## Three ways to contribute without writing code

1. A model row. One row per pull request, in `models.env`: the 5
   fields, with the size and sha256 from Hugging Face's file metadata,
   its `_LICENSE` and an optional `_NOTE`. `_TESTED="line"` needs the
   line proof: `spark line` answers it with valid JSON. A proof for a
   row that is already there is a pull request too.
2. A credits correction. A wrong version, a missing license, a name
   that changed: `CREDITS.md` is a pull request away from being right.
3. A doc fix. A stale count, a broken cross-reference, a sentence that
   no longer matches the code. What a new user reads stays minimal and
   step by step, with two nouns, spark and spark apps, and
   `tests/docs_test.py` says which words are out. The project site,
   spark.forgewright.ai, is these docs rendered at the newest release
   tag, so a fix here reaches it with the next one. A fix in `docs/`
   needs no changelog entry.

## Code changes

Follow the landing rule in `AGENTS.md`. A feature is not done until it
is in `spark help`, a `spark <verb>`, a `spark check` row when it is a
promise, and every doc. CI runs the full gate on your pull request.

Commit messages: a lowercase title line, and a body that says why, not
only what. Trailers are optional.

A spark app is an editor or another tool that becomes smart as a
client of one spark verb: `spark edit`, `spark line` or the page's API.
It lives in a repository of its own, and spark-micro is the shape.
spark itself ships no app, no app package and no app check row. A pull
request adding one is turned into a pointer to the app's own
repository.

## Privacy gate

The pre-commit hook checks staged changes for e-mail addresses, private
IPv4 ranges and absolute home paths naming a user. It also reads a
personal word list that does not exist in your fork, so you will see a
notice that it is missing. That is expected. Never add a real name, a
machine name or a project name to the tree regardless.

## Report a bug

Open an issue: https://github.com/forgewright-ai/spark/issues/new/choose.
The form asks for `spark ver`, your OS, the steps to reproduce, what
you saw and what you expected. Steps are required. `spark check
--report` is welcome too. It is statuses only, with no value, no path
and no name, and it runs your privacy word list over itself before
printing.

An agent reads each new report within the hour. It follows your steps
in a fresh install, sets one severity label and answers on the issue.
A new report carries `triage` until it does.

- `S1`: spark is unusable for every user of a family. The install or
  the update fails, the prompt line or the chat is dead, data is lost,
  or something private leaks.
- `S2`: a documented behaviour does not work on a family or OS, with
  no workaround.
- `S3`: wrong, with a workaround. An edge case, or a check row that is
  wrong.
- `S4`: a doc, a help text or a wording is wrong.

Its verdict is one more label:

- `approved`: a patch fixes it. An S1 or S2 is fixed and released
  within 24 hours. An S3 or S4 ships in the weekly patch, on Sunday.
- `needs-steps`: the steps could not be followed, and the comment says
  what is missing.
- `arc`: the fix needs a new command, option, key, check row or help
  row, so it goes to the roadmap for a planned release.
- `not-a-bug`: the comment says what spark promises instead.

A fixed issue closes when the fix lands on `main`, and a comment names
the release that carries it.

Questions and ideas go to Discussions:
https://github.com/forgewright-ai/spark/discussions. A model row has
its own form.

## Roadmap

`docs/ROADMAP.md` lists what comes next. An idea that is not there is
an issue away.

## Voice

Every document, help text and message follows five rules:

- Write short, plain English, the way you would say it.
- Say what happens and what to type. Leave out how it works.
- Name a model by its name in the list, not its file name.
- Print nothing when nothing changed.
- Keep a line under 80 characters.

`tests/docs_test.py` checks what a program can: ASCII, the widths, no
contractions, sentences of 30 words at most. The CHANGELOG is history
and stays as written.

