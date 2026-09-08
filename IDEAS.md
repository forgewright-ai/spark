# Ideas

What an AI at the shell prompt could do that nothing else can. This file
is upstream of `ROADMAP.md`: the roadmap is what comes next in order,
this is the wider field it is picked from. Nothing here is a promise; a
row in `CHANGELOG.md` is. An idea that earns a place moves to the
roadmap and leaves here.

Each entry says what it is, what it looks like at the prompt, and what
it would cost -- which contract it extends, or whether it needs a new
one.

## Why the prompt, and why local

Two things are already built, and almost nothing else in the world has
both:

- **The line is ours.** The widget reads the buffer, calls `spark line`
  (contract 4) and puts the answer back *in the line* before readline
  runs it. A pane that prints an answer beside your shell is a
  different, smaller thing.
- **The failure moment.** A nonzero exit prints one line above the next
  prompt, and the command and its status live in that pane's variables
  (v1.15). The shell's most useful instant is caught, with no model call
  and no fork.

And one thing is structural: the model is on the box. The most valuable
text at a shell -- your history, your logs, a script you were about to
paste, a diff -- is exactly the text nobody sends to a vendor. Every
idea below that reads such text is possible here and not possible there.
Those are marked **local-only**.

The test for an idea in this file: could a chat window in another pane
do it just as well? If yes, it is not a prompt feature.

## 1. The line, before it runs

### Blast radius

`danger=true` earns a `!` today. Have the line answer with a read-only
twin as well; spark runs the twin and puts the number in the hint row.

```
~ > ? clean out the build dir
! rm -rf ./build            <- 1,204 files, 3.1 GB, 2 tracked by git
```

A confirmation everywhere else is a yes/no. This one is a yes/no with
the facts, and it costs one more field in contract 4 (`probe`, a command
that only reads) plus the rule that a probe which is not read-only is
dropped. The highest safety per line of code in this file.

### Localize a pasted command

A command from a page on the internet is written for someone else's
machine. Before Enter, rewrite it for this one: the OS, the package
manager from `distro/<id>.env`, the tools `persona.PREFERRED` says are
here.

```
~ > free -h                            (on macOS)
* vm_stat: the same numbers here       <- the hint
~ > vm_stat
```

The roadmap already names per-OS knowledge as the line's weakest spot.
This turns the weakness into the feature, and the exemplars it needs are
the ones the roadmap wanted anyway.

### Paste inspection (local-only)

Bracketed paste is visible to readline. A multi-line paste into a prompt
is the most dangerous thing a shell accepts and the least likely thing
anyone would upload to be checked. Read it here, say one line, run
nothing:

```
~ > [paste]
! 40 lines: downloads a tarball, pipes it to sh, writes /etc/profile.d
```

The refusal shape and the `!` mark exist; the work is in the widget.

### The command and the proof

Ask the line for the assertion as well as the command: `? delete the
build dir` gives `rm -rf ./build` and `test ! -d build`. The prompt
stops being a hopeful step and becomes a verified one. Pairs with
`spark do`, which already runs one confirmed command at a time.

## 2. The failure moment, further

v1.15 catches the instant and offers prose. Three escalations, in
increasing cost:

### The fix as a patch

`Esc s` explains. A second `Esc s` should put the *corrected command* in
the buffer -- one keystroke from failure to a line you can read and
press Enter on. The state it needs (the command, the exit code) is
already in the pane.

### Failure memory (local-only)

The third time you hit a failure is not the same event as the first.
Hash the shape locally -- the command's head word, the exit code, the
first line of stderr -- and the prompt can say what worked last time:

```
* failed (1) -- you hit this in April; the fix was: git config --global ...
```

`lib/spark/ledger.py` is the precedent to copy, down to the retirement
rule: a note whose anchor is gone is dropped where it stands.

### `command not found` is a package name

spark knows every family's names already (`distro/<id>.env`,
`lib/spark/packages.py`). That failure should offer the install line,
not an explanation of what a PATH is.

## 3. History as a corpus (local-only)

### Intent search

`Ctrl-R` matches text. A model on the box matches intent:

```
(Ctrl-R) that thing where I fixed the docker network
> docker network rm $(docker network ls -q --filter dangling=true)
```

Your shell history is the highest-value and most private corpus you own.
Nobody uploads it -- which is exactly why a local AI wins here and a
hosted one structurally cannot. fzf is already in the shell layer; this
is `Ctrl-R` with a brain behind it. If one idea in this file explains
why spark exists, it is this one.

### The command you keep retyping

A command reconstructed from scratch three times is an alias you do not
have. Counts only, kept here, no words anywhere. The offer rides the
flow v1.15 already built for keeping a fix as a fact.

### The tool you have and do not use

Ten `find . -name` in a machine with `fd` on it earns one line in the
hint row, once, and then never again. `persona.PREFERRED` is the list.

## 4. Streams: the gap beside contract 10

`spark edit` takes a body of text. There is no verb for a live one:

```
tail -f app.log | spark watch "tell me when a 500 appears"
journalctl -f  | spark watch "anything about the disk"
```

Silent until something matters, then one line. This is a new contract
(11) and a real surface -- and local-only in the strongest sense: nobody
streams a production log to a vendor by the megabyte. The same shape
covers a long build, a test watcher, a slow migration.

The hard parts are honest ones: what a window is, how it says nothing
for an hour without looking dead, and how it stays cheap enough to leave
running.

## 5. One FORGE, many prompts

Threads are sealed and per-user, and every client talks to one FORGE
(contract 9) -- but the prompt does not use that yet.

- **`??` across machines.** Start a thread at the box's prompt, go on
  with `??` from the laptop. Same identity, same thread, nothing in a
  cloud. The thread routing is the work; the identity is done.
- **Two people, one box.** Named users have sealed stores already: two
  prompts on one machine, one soul, and the admin genuinely cannot read
  the other's history. No hosted assistant can make that promise.

## 6. The machine's own doctor

`spark check` answers 39 yes/no questions and `stats.py` keeps the
numbers. Let a model read `check.json` and `bench.jsonl` and answer the
question the rows cannot:

```
~ > ? why is it slow today
* KV cache off since the last tune; 4.1 tok/s against a 12.3 baseline
```

The forecast is the same trick pointed forward -- "the disk fills in
about three days at this rate" -- and it stays honest, because it is
made of numbers spark already keeps and words that never leave.

## Where to start

| idea | cost | surface |
|---|---|---|
| Blast radius | low -- one field in contract 4 | the line |
| The fix as a patch | low -- the state is in the pane | the failure |
| Localize a pasted command | low -- the brief plus `distro/` | the line |
| `command not found` | low -- `packages.py` knows the name | the failure |
| Intent search | medium -- a verb, no new contract | history |
| Paste inspection | medium -- widget work | the line |
| The command and the proof | medium -- the line plus `do` | the line |
| Failure memory | medium -- a ledger of its own | the failure |
| The doctor | medium -- reads what exists | the machine |
| `spark watch` | high -- contract 11 | new |
| `??` across machines | high -- thread routing at the prompt | new |

Two to build first, if it were two:

- **Blast radius**, because it makes `danger` mean a number instead of a
  mark, and because it is nearly free.
- **Intent search**, because it is the clearest thing a local model does
  that a hosted one cannot, and it is the demo that needs no
  explanation.
