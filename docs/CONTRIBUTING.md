# Contributing to spark

spark is a local AI at the shell prompt, for Linux and macOS. This file
is the short path to a change that lands.

## Clone and run the gate

Fixture tests use a stub llama-server, a throwaway `HOME` and
`XDG_*` dirs. Real isolation tests also need host capabilities.
Fixture success proves neither real isolation nor live-model quality.

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

## Validation boundaries

Keep fixture, real isolation, model compatibility and quality results
separate. A green ordinary gate can contain capability skips. It does
not certify an untested host, engine, model or prompt.

The sandbox suite ends with `sandbox-summary: ` followed by JSON.
It counts executed assertions, failed checks and named skips separately
for fixtures, the probe and real isolation. A skipped section counts
once; it does not guess how many assertions would have run.
The record names the OS, kernel, architecture, Python and sandbox tool.
It omits the hostname.

An ordinary contributor run keeps explicit capability skips:

```sh
python3 tests/sandbox_test.py
```

A job that promises real isolation must use:

```sh
python3 tests/sandbox_test.py --real-only --require-real
```

That command requires a fresh successful sandbox probe, real assertions
and curl. On macOS, missing command line tools also fails the run.
Missing capability fails, even when fixture tests pass.
It tests writes in the copy, review and apply, and the existing
containment assertions. Optional checks still name their skips, such
as an absent session bus. Read those skips beside the assertion count.
These checks are scoped evidence, not a general security guarantee.

Use a non-root Linux host with bubblewrap 0.11 or later, working user
namespaces and overlay support. On macOS, use APFS, sandbox-exec and
the command line tools. Do not relax host security settings to make
the probe pass. Record a failed probe as a blocked host.

The bounded compatibility command needs two local files: the native
Linux CPU archive pinned in `engine.env`, and the qwen3-5-2b weights
pinned in `models.env`. It verifies both hashes before starting the
engine. It never downloads files, uses a remote model or reads user
prompts. Run it as a non-root user on glibc Linux, x86_64 or aarch64,
with space for the extracted engine and enough RAM for the model.

```sh
umask 077
python3 tests/model_validation.py \
  --engine-archive /path/to/engine.tar.gz \
  --model-file /path/to/model.gguf > compatibility.json
```

It runs two synthetic requests three times each, with two CPU threads,
2048 context tokens and at most 64 output tokens per request. Startup
has a 120-second limit; each request has a 60-second socket timeout.
The server binds only to loopback, uses a temporary key and is stopped
after the run. No existing server or user configuration is used.

The JSON record names the time, OS, kernel, CPU, RAM, backend, engine
revision and archive hash, model content hash, prompt hashes and
settings. It counts requested, executed, passed and unfinished samples.
The model hash is its content revision; a mutable download URL is not
revision evidence. The record includes source hashes and the tested
binary hash. Keep it with the checkout commit and CI run address.
It contains no answers, local paths, credentials or server logs.

Compatibility means the pinned engine loads those weights and returns
nonempty text and a JSON object when requested. It does not judge the
words, exercise all spark commands or establish the release quality bar.
GPU backends, other models and other platforms remain untested by this
command. A missing artifact, refused host or failed request exits
nonzero. Its selftest uses fixtures and proves only the harness.

Held-out quality remains the separate `line_audition.py` run and report
described above. Keep its sample counts, prompt hashes, platform and
verified artifact identities beside its scores. Never mark it passed
from a compatibility run. This harness records quality as `not_run`.
Use only repository fixtures or explicitly approved synthetic data.

CI activation is pending. The current patch policy protects workflows
and `tests/gate.sh`; this patch does not add a job or schedule.
In a planned release, wire the strict isolation command through the
gate into dedicated Linux and macOS jobs on verified capable hosts.
Wire compatibility through the gate into a scheduled or release job
with the pinned artifacts already available. Set a job deadline and
retain the JSON result on failure too. Do not run untrusted pull
requests on a persistent model host.
Until those jobs exist and run, neither capability is a required CI
check. A host that cannot run the probe, or lacks the artifacts, is
an outstanding validation requirement.

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

