# spark -- for agents and contributors

spark is a local AI at the shell prompt, for Linux (the Debian, Arch,
Void, Fedora and openSUSE families), macOS and Windows through WSL 2.
Nothing leaves the machine except pinned downloads and your own words
to a model you run. One line installs it, and spark is live. A tool
becomes a spark app as a client of `spark edit`, in its own
`spark-<app>` repository, and no shell code lives in this tree.
`CLAUDE.md` is the full reference: the principles, the layout, the 15
contracts, the grammar and the release steps. This file is the short
brief.

## The landing rule

A change is done only when it is in `spark help`, a `spark` verb, a
`spark check` row and every core doc: `CLAUDE.md`, "Adding things",
"The landing rule", is the full text.

## The grammar

Every verb follows one grammar, and nothing living happens before
`spark awaken`: `CLAUDE.md`, "The grammar" and the principle "Awake by
choice", is the full text.

## The gate

`tests/gate.sh` holds the one test list. The hooks and CI call it and
name no test themselves. `git config core.hooksPath .githooks` turns
the hooks on.

A commit runs the fast half, in seconds:

```sh
sh tests/gate.sh fast
# the privacy gate: the staged diff, the staged names and the branch
# syntax, one file per call: sh -n, bash -n, zsh -n, py_compile -W error
# docs/CHEATSHEET.txt within 80 columns; the docs and the page ASCII; shellcheck
python3 tests/docs_test.py
```

CI runs the full gate once per commit, in 3 groups side by side:

```sh
sh tests/gate.sh full smoke
python3 tests/smoke.py

sh tests/gate.sh full serve
python3 tests/serve_smoke.py

sh tests/gate.sh full rest
# every fast check, and the privacy gate over the whole tree
sh tests/install_test.sh
sh tests/get_test.sh
sh tests/update_test.sh
sh tests/uninstall_test.sh
sh tests/finish_test.sh
sh tests/land_test.sh
python3 tests/forge_smoke.py
python3 tests/bench_smoke.py
python3 tests/vault_test.py
python3 tests/sandbox_test.py
python3 tests/knowledge_test.py
python3 tests/qr_test.py
python3 tests/voice_test.py
python3 tests/docs_test.py
python3 tests/policy_test.py
python3 tests/widget_pty.py zsh home/.config/spark/widget.zsh          # bash on Linux
python3 tests/widget_pty.py completion zsh home/.config/spark/completion.zsh
python3 tests/widget_pty.py pager
python3 bin/spark check --selftest
python3 bin/spark check --chaos
```

`sh tests/gate.sh full` runs the 3 groups in order on your own machine.
It takes about 10 minutes, and nothing asks for it. `SPARK_GATE_PYTHON`
names the python, and CI on macOS sets it to Apple's.

`sh tests/land.sh` lands a commit. It pushes the commit to a `try/`
branch and waits for CI. On green it moves `main` forward to the same
commit and deletes the branch. On red it prints the failed step and
leaves `main` alone. Fix the commit, amend it and run it again.
`--dry-run` prints the steps.

The pre-push hook runs no test. It refuses a push to `main`, or of a
`v*` tag, unless `ci.yml` passed for that exact commit. Without `gh`,
or on a remote that is not GitHub, it prints a notice and lets the push
go. `sh tests/land.sh --passed SHA` is that one check, and
`release.yml` asks it again on the server. `tests/land_test.sh` proves
the hook and `tests/land.sh` against a stub `gh`.

`tests/docs_test.py` holds the list whole. Every file in `tests/` is
run by `tests/gate.sh` or named in `NOT_IN_GATE` with its reason. The
hooks and the workflows name no test file.

The gate calls `bin/spark` directly. `tests/check_selftest.py` is a
standalone entry to `spark check --selftest`. The privacy gate also
reads the staged diff for secret shapes: `SOURCE_SHAPES` in
`lib/spark/text.py`, minus the two tuned for a paste and the two tuned
for a source. It names the shape, never the line, and skips a line
marked `spark:allow-secret`. shellcheck is the contributor's tool, not
a user's package, and the gate skips it with a notice when absent.

CI is where the full gate runs, `.github/workflows/`. `ci.yml` runs on
a push to `main` or to a `try/` branch, on a pull request and by hand.
A tag push runs `release.yml` alone. A newer push cancels an older run
on a `try/` branch or a pull request, never on `main`. The `linux` and
`macos` jobs run `tests/gate.sh full`, one job per group. The `rest`
job then runs a real bootstrap on the runner. The `debian`, `arch`,
`void`, `fedora` and `opensuse` jobs run the one-liner as a new user
in a container. The `void` job starts a runsvdir first, so it
proves `spark-check` running supervised. The `workflows` job runs
zizmor over the workflows, medium and above failing. `codeql.yml` is
GitHub's static analysis over the python and the javascript.
`advisories.yml` opens one issue when llama.cpp publishes a security
advisory after the engine pin's date, and one when sherpa-onnx does
after the voice pin's. `dependabot.yml` keeps every action's sha pin
current. The Debian image is pinned by its digest, moved by hand.
`tests/forge_probe.py URL` is not in the
gate: it asks a live `FORGE`'s gates from the wire, one line per gate,
exit 1 when any does not hold.

`--selftest` proves every fixture-testable row can flip. `--chaos`
proves the sentence a row prints under a real failure is true, and that
the remedy it names heals it: eleven scenarios in `lib/spark/chaos.py`.

## The audition

The audition is not in the gate: it needs a live model, and it is the
one test that judges words. `tests/audition.py` runs 8 fixtures in
`tests/audition/` (a poem, a chapter, a README, a commit message,
Portuguese prose, Go, Python, shell) through the real `spark edit`
(complete, rewrite, `?`). It scores every answer with mechanical lints
only. `tests/audition/ground/` holds 10 cases for the grounded
contracts, scored the same way, and `--ground` runs only those. It
prints a table and never an answer unless `-v`. A change to any
`edit-*` brief in `persona.py` carries the audition's before and after
totals in the pull request (`--times 3`: a small model is not
deterministic). `--json` appends the model, the briefs' hashes and the
totals to `STATE_DIR/audition.jsonl`, so two briefs are compared by
number, never by taste.

`tests/line_audition.py` is the prompt line's audition, not in the
gate either. `tests/line_audition/cases.json` holds about 58 questions
per OS (debian, arch, void, fedora, opensuse, macos) and 39 about spark
itself. A case names what makes an answer right: the head commands, the
must-nots, the danger flag. A case with `then` is a `??` pair: the
follow-up must keep the tool. `run --os OS --model NAME` sends each
case through the real `spark line`. The OS comes from spark's own
seams, so one Linux speaks as another family too. macOS runs on a Mac.
The grader trusts outcomes and shares no code with the line's own
judge. The head command must
exist in that OS's help snapshot, `help-<os>.json`, and every option
must appear in its help. A spark verb must appear in the TAB completion
files or the cheatsheet's command column. `collect` writes a snapshot
on the OS it describes, and `line-audition-help.yml` runs it in the CI
images. A snapshot also keeps what a store indexes: each tool's one
line, its synopsis and its option lines. `serve-candidate` starts a
second engine for a model on trial. `selftest` needs no model:
`python3 tests/line_audition.py selftest`.

`recall --os OS|all [--k 3]` needs no model either. It builds that OS's
snapshot into a store (`SnapshotStore`, spark's own verbs included). It
asks `grounding.search` for each case's words and counts a case whose
head is in the top 3. It prints the share per topic and the search's
p50 and p95. A stub search exits 2.

The A/B runs each OS three times, once per arm: `run --arm off`, `run
--arm judge` and `run --arm full`. The arm is `SPARK_LINE_KNOW` for
`spark line`: no knowledge, the verdict with one re-ask, or evidence up
front too. `report FILE...` prints one block per model and arm. Its
second table holds danger recall, danger over-fire, flag honesty, the
re-ask share, the evidence characters, and total and command-ready ms
at p50 and p90. Its last line says whether the bar is met.

The production bar, before a release tag that changes the line:

- tools at 90 % or more on each OS, and spark core at 90 % or more
- danger recall 100 %: one dangerous case without its mark blocks the
  tag
- danger over-fire reported, 10 % or less the target
- flag honesty 100 %: every painted option is in its manual, or the
  hint names it

A run sets 3 seams, honoured only with `SPARK_LINE_BENCH=1` and never
on a person's line. `SPARK_LINE_KNOW` is the arm.
`SPARK_KNOWLEDGE_SNAPSHOT=FILE` is the store the line grounds and judges
in: that OS's snapshot, so a Void machine grounds a debian question in
debian's manuals. When it is set, `spark line` prints one line on
stderr naming it, so it never passes silently. `run` warns when no turn
did. `SPARK_LINE_BENCH_HISTORY=FILE` is a `??` pair's first turn, as the
history a bench turn otherwise lacks. All 3 are for measuring only.

## Contracts

The interfaces between parts live in `CLAUDE.md`, "Contracts": `spark
line`, `spark check`, the config file shape, the `FORGE` HTTP API and
the rest. Read them there. Do not duplicate them here.

## Privacy

No real name, machine name or project name belongs in this tree. The
personal word list lives outside the repository at
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
- Put an app inside this repository: `CLAUDE.md`, "A spark app", says
  where one lives.
- Set the machine's look from core: the console's palette and font, a
  quiet boot, a terminal profile. `CLAUDE.md`, "A shell thing", says
  what spark's side is.
- Add a model row without its size and sha256 from Hugging Face's file
  metadata and its license. Mark one `_TESTED="line"` only with the line
  proof: `spark line` answers valid JSON for it.
- Call `git` on `spark line`'s path. The widgets depend on nothing but
  the line contract, and it must never block.
- Call a model in the widgets' prompt hook, or fork there. It runs
  before every prompt: a `$?` test, a few variable writes and at most a
  few `printf`s. One of them may print the resting face. In zsh one
  may erase a resting face a `Ctrl-C` left. Its reads,
  with shell builtins: `state/fails`, the
  plain hash-to-fix index the ledger writes, and on a failure only. The
  look file, again only when it is newer than the shell's marker, line
  by line and never sourced. `state/alert`, the check's changes: one
  `-nt` test a prompt, then line by line, a bad line dropped, never
  sourced and never written. One stat of `state/off`, where the face
  is on. Its other state is per pane and in
  memory: never exported.
- Start a process for the resting face. The zsh idle timer is `sched`
  and `zselect`, builtins only, and it draws only at an empty line. In
  bash the face is still.
- Print a canned line: a greeting, a goodbye, a news line. Awaken
  writes no lines, an older shell's `spark words greet` prints nothing,
  and nothing reads `state/news`, `news-seen` or `last-seen`. A check
  row's change is not one: `state/alert` carries the row's own words,
  said once. The face
  says nothing. It shows in a wait, leads a reply, follows the mark
  in spark's row, rests above an idle prompt, and is in `spark look`.
- Store a frame of the face. `look.Anim` derives every frame from the
  stored idle face: the faces file and the look file keep one still a
  mood.
- Write non-ASCII into a doc: the pre-commit hook refuses it.
- Name a private repository or tool in any doc: `tests/docs_test.py`
  refuses it.
- Bring the contracts' names into what a new user reads: `docs_test.py`
  holds the word list.

## Voice

Every document, help text and usage text speaks with one voice.
`docs/CONTRIBUTING.md`, "Voice", is the style sheet. Messages are
lowercase, with one mark (`*` spark speaking, `!` a warning or a
failure, both OSes) and `--` before the remedy when there is one.
