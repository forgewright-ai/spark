# spark -- for agents and contributors

spark is a local AI at the shell prompt, for Linux (the Debian and Arch
families), macOS and Windows through WSL 2. Nothing leaves the machine
except pinned downloads and your own words to a model you run. One
line installs it, and spark is live. A tool becomes a spark app as a
client of `spark edit`, in its own `spark-<app>` repository, and no
shell code lives in this tree. `CLAUDE.md` is the full reference: the
principles, the layout, the fifteen contracts, the grammar and the
release steps. This file is the short brief.

## The landing rule

A change is done only when it is in all of these. `CLAUDE.md`, "Adding
things", has the reasons.

- `spark help`: a line in `bin/spark`'s usage text.
- A `spark <verb>` that sets and applies it, never a `site.env` key by
  hand.
- A `spark check` row, when it is a promise the machine makes.
- Every doc: `README.md`, `docs/INSTALL.md`, `docs/CHEATSHEET.txt` and
  `docs/CHANGELOG.md`.

Apply it, reproduce it in `bootstrap.sh` or `install.sh`, detect it in a
row, explain it in every doc. Otherwise it is not done.

## The grammar

`CLAUDE.md`, "The grammar", is the full text.

- A bare verb shows and never mutates. `spark bar` piped still prints
  the bar line: a status bar runs `spark bar` piped.
- `on|off` is the only switch vocabulary at the CLI. Storage stays
  `yes|no`.
- `status` is bare; `list` is the table.
- `-h` answers first, signed `spark <sub> -- <one line>`.
- A confirm is `<question>? yes/NO: ` (`confirm()`).
- A wait is one dot-spinner (`wait_ready()`) for a server coming up,
  one pulse (`text.Busy`, a tty only) for a reply, and curl's bar for a
  download.
- Exit codes: 0 ok or show, 1 the world (stderr), 2 the invocation
  (stdout, signed), 78 config, 130 `SIGINT`.

## The gate

The pre-commit hook runs the fast half and the pre-push hook the slow
half. Together they are the gate. `git config core.hooksPath
.githooks` turns them on.

pre-commit:

```sh
# the privacy gate: the staged diff, the staged names and the branch
# syntax, one file per call: sh -n, bash -n, zsh -n, py_compile -W error
python3 tests/smoke.py
python3 tests/serve_smoke.py
python3 tests/forge_smoke.py
python3 tests/bench_smoke.py
python3 tests/vault_test.py
python3 tests/sandbox_test.py
python3 tests/qr_test.py
python3 tests/docs_test.py
python3 tests/policy_test.py
python3 tests/widget_pty.py zsh home/.config/spark/widget.zsh          # bash on Linux
python3 tests/widget_pty.py completion zsh home/.config/spark/completion.zsh
python3 tests/widget_pty.py pager
python3 bin/spark check --selftest
# docs/CHEATSHEET.txt within 80 columns; the docs and the page ASCII; shellcheck
```

pre-push:

```sh
sh tests/install_test.sh
sh tests/get_test.sh
sh tests/update_test.sh
sh tests/uninstall_test.sh
python3 bin/spark check --selftest
python3 bin/spark check --chaos
```

The hooks call `bin/spark` directly; `tests/check_selftest.py` is a
standalone entry to `spark check --selftest`. The privacy gate also
reads the staged diff for secret shapes: `SOURCE_SHAPES` in
`lib/spark/text.py`, minus the two tuned for a paste and the two tuned
for a source. It names the shape, never the line, and skips a line
marked `spark:allow-secret`. shellcheck is the contributor's tool, not
a user's package, and the hook skips it with a notice when absent.

CI is the second net, `.github/workflows/`. In `ci.yml` the `linux` and
`macos` jobs run the hermetic tests, then a real bootstrap on the
runner. The `debian` and `arch` jobs run the one-liner as a new user in
a container. The `workflows` job runs zizmor over the workflows, medium
and above failing. `codeql.yml` is GitHub's static analysis over the
python and the javascript. `advisories.yml` opens one issue when
llama.cpp publishes a security advisory after the engine pin's date.
`dependabot.yml` keeps every action's sha pin current.
`tests/forge_probe.py URL` is not in the gate: it asks a live `FORGE`'s
gates from the wire, one line per gate, exit 1 when any does not hold.

`--selftest` proves every fixture-testable row can flip. `--chaos`
proves the sentence a row prints under a real failure is true, and that
the remedy it names heals it: ten scenarios in `lib/spark/chaos.py`.

## The audition

The audition is not in the gate: it needs a live model, and it is the
one test that judges words. `tests/audition.py` runs eight fixtures in
`tests/audition/` (a poem, a chapter, a README, a commit message,
Portuguese prose, Go, Python, shell) through the real `spark edit`
(complete, rewrite, `?`). It scores every answer with mechanical lints
only. `tests/audition/ground/` holds 10 cases for the grounded
contracts, scored the same way; `--ground` runs only those. It prints a
table and never an answer unless `-v`. A change to any `edit-*` brief
in `persona.py` carries the audition's before and after totals in the
pull request (`--times 3`: a small model is not deterministic).
`--json` appends the model, the briefs' hashes and the totals to
`STATE_DIR/audition.jsonl`, so two briefs are compared by number, never
by taste.

## Contracts

The interfaces between parts live in `CLAUDE.md`, "Contracts": `spark
line`, `spark check`, the config file shape, the `FORGE` HTTP API and
the rest. Read them there. Do not duplicate them here.

## Privacy

No person, machine or project name belongs in this tree. The personal
word list lives outside the repository at
`~/.config/spark/privacy-terms`, one word per line, 0600, never
committed. The pre-commit hook prints a notice when that list is
absent, which is expected on a fresh clone or a fork. It still enforces
e-mail addresses, private IPv4 ranges and absolute home paths naming a
user, with no skip path. `CLAUDE.md`, "Privacy by design", has the
whole of it.

## Never

- Apply `bootstrap.sh` or `install.sh` against a real `HOME` in a test.
  Use a throwaway `HOME` and the matching `XDG_*` dirs.
- Change the banner (`home/.config/spark/banner`): it is spark's own
  artwork.
- Put an app inside this repository: no plugin, no app package, no app
  check row. An app is a client of one spark verb, in a repository of
  its own. spark-micro is the shape.
- Add a model row without its size and sha256 from Hugging Face's file
  metadata and its license. Mark one `_TESTED="line"` only with the line
  proof: `spark line` answers valid JSON for it.
- Call `git` on `spark line`'s path. The widgets depend on nothing but
  the line contract, and it must never block.
- Fork, call a model or write a file in the widgets' prompt hook, the
  failure line. It runs before every prompt: a `$?` test, a few variable
  writes and at most one `printf`. The one read it may do is
  `state/fails`, the plain hash-to-fix index the ledger writes, opened
  with shell builtins. Its other state is per pane and in memory: never
  exported, never on disk.
- Write non-ASCII into a doc. The pre-commit hook refuses it, because
  the docs are read on the Linux console too.
- Name a private repository or tool in any doc. What is not public is
  not documented, and `tests/docs_test.py` refuses the word for that
  tooling.
- Bring the contracts' names into what a new user reads. `README.md`,
  `docs/INSTALL.md`, `docs/CHEATSHEET.txt` and the page front speak two
  nouns, spark and spark apps. `docs_test.py` holds the word list;
  `CLAUDE.md` keeps the names.

## Voice

Every document, help text and usage text speaks with one voice.
`docs/CONTRIBUTING.md`, "Voice", is the style sheet. Messages are
lowercase, with one mark (`*` answer, `!` warn, both OSes) and `--`
before the remedy when there is one.
