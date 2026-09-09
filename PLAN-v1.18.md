# Plan: v1.18, "the prompt"

Execution plan for the next release, written for a Claude Code session in
this checkout. Delete this file before the release is tagged; it is a
working note, not a doc under the landing rule.

## Context

The tree is clean at the v1.17 tag, no open issues. ROADMAP.md lists nine
items in likely order. v1.18 ships the four that all live at the prompt:
blast radius, the failure moment's two escalations, localize a pasted
command, and intent search. They share `cmd_line` (lib/spark/cli.py),
`persona.prefix` (lib/spark/persona.py) and the two widgets
(home/.config/spark/widget.bash, widget.zsh): one release, one CHANGELOG
section. Order of work, by cost and shared code: blast radius (no model,
no key) -> failure escalations -> localize (shares the exit-127 path) ->
intent search (a verb and a key, last because it is the largest). One
commit per item, each landing in all four obligations (CLAUDE.md).

What the changelog settles before starting:

- v1.15 added the `failure` check row (`row_failure`, check.py): it watches
  that both widgets carry `_spark_failed` and that live shells report the
  hook through contract 6's fourth field. The new offer kinds ride the
  same hook: no new row. Esc r is a widget binding, not a promise: no row
  either. `spark check` stays at 40 rows (docs_test ties the count).
- v1.16 named modes "for what spark does" and left `ask` free on purpose:
  the new mode key is `recall`, never a reused word.
- v1.16 moved `spark remember` to `spark memory add`; new docs use it.
- v1.16 marked the read/drill cases in tests/smoke.py as skipped:
  shipping those contracts later means un-skipping them.
- `spark history` is taken (threads). The intent verb is `spark recall`;
  free in `cli.COMMANDS` and in `bin/spark`'s `VERBS`.
- Read AGENTS.md first: the gate it lists runs before every commit.

## Item 1: blast radius

A `danger` line earns facts beside the `!`: for `rm -r|-f PATH...` (the
first `_DANGER` pattern in persona.py) the count of files, bytes and
git-tracked files under the paths. Computed from the command spark already
has; nothing the model proposes is run.

- `persona.blast(command, cwd)` -> `"1,204 files, 3.1 GB, 2 tracked by git"`
  or `""`. `shlex` the args after the flags; skip globs and options;
  `os.walk` each path with a cap (entries and about 200 ms) -> `1,204+
  files` when the cap hits; tracked = `git ls-files -- PATH` line count
  when cwd is in a repo (quiet on failure). Paths resolve against `--cwd`.
- cli.py `cmd_line`, after `flagged`: `hint = _one_line("<- " + facts +
  " -- " + hint)` when facts exist: the facts first, so the 80-char cut
  (contract 4) eats the model's words, not the numbers. The turn record
  stays numbers only (session.TEXT_FIELDS strips the hint).
- lib/spark/do.py `cmd_do`: the same facts line above the `yes` prompt of
  a danger step (`do.shown` unchanged: the thread keeps the step as is).
- tests/smoke.py: the stub already answers `rm -rf build` unflagged for
  `rm-plain?`; run it with `--cwd` on a temp tree holding `build/` with N
  files and assert the counts in line 2; a capped tree prints `+`; a
  missing path prints no facts; a danger without `rm` prints the hint as
  before.
- Docs: CHEATSHEET.txt's `Enter again` line, README's `!` sentence,
  INSTALL.md section 3 item 1, CLAUDE.md contract 4 (line 2 of a `danger`
  may open with the facts), CHANGELOG.

## Item 2: the failure moment, further

Built from the pane variables the widgets keep (`_spark_fail`,
`_spark_fail_rc`, `_spark_explained`, `_spark_fix`). The same change in
both widgets; tests/smoke.py compares their word lists (`_SPARK_DANGER`,
`_SPARK_QUIET_ONE`, `_SPARK_QUIET_RC`, `_SPARK_LOOKING`), so a new list
joins that loop.

2a. A second `Esc s` after an explain: the corrected command in the buffer.

- `_spark_ask_line` / `spark-ask`: empty buffer, `_spark_explained` set,
  no `_spark_fix` yet -> run `spark line` with `SPARK_EXPLAIN_CMD` and
  `SPARK_EXPLAIN_RC` exported (the two variables `cmd_explain` reads) and
  the buffer `? fix it`; the answer lands through the existing
  `cmd|danger` path. Nothing runs until Enter. Contract 4 unchanged.
- cli.py `cmd_line`: when those env vars are set, ride `Command: ...
  Exit: ...` (the shape `cmd_explain` builds) into the turn as context.
- tests/widget_pty.py: fail, `Esc s` (explain), `Esc s` again -> a `cmd`
  in the buffer, against the stub brain, both shells.

2b. `command not found` offers the install line.

- `_spark_kind_of`: rc 127 -> `_spark_kind=install`; `_spark_failed` notes
  `failed (127) -- HEAD: not installed; Esc s offers the install line`;
  `Esc s` runs `spark line` with the env vars as in 2a.
- cli.py: with `SPARK_EXPLAIN_RC=127`, look the head word up in
  lib/spark/packages.py first (`packages.table()`, `install_line`):
  spark's own tools (fd/fdfind, rg, eza, bat...) get the family's line
  with no model call; otherwise the model names the package and
  `packages.install_line([pkg])` renders it. The docs say which half is
  offline: only the five package groups are known without the model.
- smoke.py: `_spark_offer_kind "foo" 127` prints `install` in both
  shells; `spark line` with rc 127 and `rg` prints the family's line.

## Item 3: localize a pasted command

- persona.py `prefix()`: per-OS exemplar pairs (`free -h` / `vm_stat`,
  `apt install` / `brew install`, `systemctl` / `launchctl`,
  `xdg-open` / `open`, `ls --color` / `ls -G`), this OS's side only, and
  the rule: a command written for the other OS is rewritten for this one
  and the hint says so. The prefix stays byte-stable per machine (the
  prompt cache depends on it).
- Trigger: the 127 path from 2b (a Linux-only tool on macOS) and `Esc s`
  on a pasted line. No new key.
- tests/audition: one brief case per exemplar (not in the gate);
  smoke.py: the prefix names this OS's exemplars and not the other's.

## Item 4: intent search, Esc r + spark recall

Design: the SHELL hands its history to spark on stdin; spark never reads
a history file. `fc -ln -400` in bash and zsh prints the last lines
without numbers or timestamps (zsh extended history included), covers the
current session, and honours whatever HISTFILE the user has, layer on or
off.

- `spark recall <words>` (cli.py, `cli.COMMANDS`; mode `recall` in
  `persona.MODES`): history lines on stdin, the intent in the words, the
  spark role, a JSON schema `{candidates: [str]}`, at most 5. Each
  candidate is checked with `text.anchor` (lib/spark/text.py) against
  stdin: one not in the history is dropped, so the answer is always a
  line that ran. One per line out; none -> one line on stderr, exit 1.
  Nothing is written: no thread; the turn record is numbers (`kind`,
  `chars`, `ms`, `candidates`). No new contract (the roadmap's own word);
  the grounding law is borrowed, not numbered.
- Widgets: `bind -x '"\er": _spark_recall'` and `bindkey '\er'
  spark-recall` beside `\es` (keyseq-timeout is already 1000). First
  press: the buffer is the intent; `fc -ln -400 | spark recall "$buf"`
  fills a pane array, candidate 1 goes in the buffer, the hint row says
  `* 1/3 -- Esc r: next`. Next press with the buffer unchanged: candidate
  2, wrapping. Empty buffer: a hint to type the intent. The `spark off`
  flag is honoured. `Ctrl-R` untouched.
- Docs note: bash binds `M-r` to revert-line by default and spark takes
  it; both bindings live in the widget block of INSTALL.md.
- Lands in: `cli.COMMANDS`, help (bin/spark USAGE, beside `Esc s`),
  CHEATSHEET.txt, README, both completion files (`recall` in the word
  list), widget_pty.py (type, Esc r, the buffer holds a history line; Esc
  r again cycles), smoke.py (the stub answers one real and one invented
  line: only the real one prints), CHANGELOG.

## Landing, every item

`spark help` (bin/spark), CHEATSHEET.txt, README/INSTALL where named,
CLAUDE.md and AGENTS.md (contract 4, the widget section, `spark recall`),
CHANGELOG `## v1.18` (grows per item, in the changelog's voice), ROADMAP:
drop the four shipped sections; its first line becomes "after v1.18" in
the same commit as the `## v1.18` heading (docs_test ties them). Docs are
ASCII, 80 columns, nothing from `.privacy-terms`. Push after each item;
CI runs on every push.

## Release

1. The full gate from AGENTS.md, then `sh tests/install_test.sh`,
   `sh tests/get_test.sh`, `sh tests/update_test.sh`.
2. Delete this file. Commit, push, CI green.
3. `git tag -a v1.18 -m 'spark v1.18' && git push origin v1.18`:
   release.yml checks the heading and `spark ver`, publishes the release.
4. `spark update` on every box; `./bootstrap.sh --dry-run` says
   `Nothing to do`, `spark check` exits 0.

## After v1.18 (sequence, not this plan's work)

- v1.19: contract 11 `spark read`: ask.py as the template; keep() drops
  UNQUOTED and UNGROUNDED; the coverage line composed locally on empty;
  the `--part` line printed by spark; ledger kind `read`; NOT BUILT
  header removed, a VERBS line, CLAUDE.md 11 rewritten, the roadmap
  section deleted, smoke.py's two skipped cases un-skipped.
- v1.20: contract 13 `spark drill` (answers from the tty with a test hook
  like `SPARK_DO_STDIN`; `ledger` gains an update op for misses, streak
  and due; its two skipped cases un-skipped) and `lib/spark/watch.py`
  reserved NOT BUILT so docs_test's reserved count stays above zero.
- v1.21: contract 14 `spark watch`, the contract text first.
- Standing: chaos on a real box (a checklist under "Verifying a claim");
  per-OS users (a design note, after the account layer is lived with).

## Verification

```sh
python3 tests/smoke.py                 # blast, 127, prefix, recall cases
python3 tests/widget_pty.py bash home/.config/spark/widget.bash
python3 tests/widget_pty.py zsh home/.config/spark/widget.zsh
python3 tests/docs_test.py             # counts, roadmap line, credits
python3 tests/site_test.py
sh tests/install_test.sh
./bootstrap.sh --dry-run               # Nothing to do
spark check --selftest                 # 40 rows, the failure row flips
git status -sb                         # clean, pushed to the branch
```

By hand on the live machine: `? clean out the build dir` shows the facts;
a typo'd command, `Esc s`, `Esc s` again lands the fix; `rg` uninstalled
shows the install line; `that docker network thing` + `Esc r` lands the
line that ran.
