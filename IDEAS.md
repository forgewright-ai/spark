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

v1.15 catches the instant and offers prose. Two of its escalations are on
the roadmap; this is the third, and the most expensive.

### Failure memory (local-only)

The third time you hit a failure is not the same event as the first.
Hash the shape locally -- the command's head word, the exit code, the
first line of stderr -- and the prompt can say what worked last time:

```
* failed (1) -- you hit this in April; the fix was: git config --global ...
```

`lib/spark/ledger.py` is the precedent to copy, down to the retirement
rule: a note whose anchor is gone is dropped where it stands.

## 3. History as a corpus (local-only)

### The command you keep retyping

A command reconstructed from scratch three times is an alias you do not
have. Counts only, kept here, no words anywhere. The offer rides the
flow v1.15 already built for keeping a fix as a fact.

### The tool you have and do not use

Ten `find . -name` in a machine with `fd` on it earns one line in the
hint row, once, and then never again. `persona.PREFERRED` is the list.

## 4. One FORGE, many prompts

Threads are sealed and per-user, and every client talks to one FORGE
(contract 9) -- but the prompt does not use that yet.

- **`??` across machines.** Start a thread at the box's prompt, go on
  with `??` from the laptop. Same identity, same thread, nothing in a
  cloud. The thread routing is the work; the identity is done.
- **Two people, one box.** Named users have sealed stores already: two
  prompts on one machine, one soul, and the admin genuinely cannot read
  the other's history. No hosted assistant can make that promise.

## 5. The machine's own doctor

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

## 6. spark drill: practice against a source

Not the line and not a smart tool -- a use for a model on the box that a
hosted one cannot schedule for you. The source on stdin, one question at
a time out, your answer in.

- both the question AND the correct answer come from the source: the
  model proposes a span of the source as the answer and a question that
  span answers, and a question whose answer does not anchor is dropped
  before it is ever asked. A drill built on an invented answer teaches
  the invention
- material too thin for questions is said in one line, never padded from
  the model's own knowledge -- the learner cannot tell padding from the
  source
- self-graded against the sourced answer: you see the span and say
  whether you had it. A second model grading a first model's question is
  two opinions and no source
- its ledger kind schedules rather than suppresses -- a missed item comes
  back at 1, 3, 7, 21 and 60 days -- which is the inversion of every
  other kind, and the reason it waits here: records that carry state and
  never age out are a cost the roadmap has not agreed to pay

Contract 13, if it is ever built. `lib/spark/drill.py` on the
`claude/spark-three-new-contracts-qds99n` branch holds the full text.

## Where to start

| idea | cost | surface |
|---|---|---|
| The command you keep retyping | low -- counts, and v1.15's offer flow | history |
| The tool you have and do not use | low -- `persona.PREFERRED` is the list | history |
| Paste inspection | medium -- widget work | the line |
| The command and the proof | medium -- the line plus `do` | the line |
| Failure memory | medium -- a ledger of its own | the failure |
| The doctor | medium -- reads what exists | the machine |
| `spark drill` | medium -- contract 13, a ledger that schedules | new |
| `??` across machines | high -- thread routing at the prompt | new |

Two to build first, if it were two:

- **The command and the proof**, because it turns a hopeful line into a
  verified one, and `spark do` already runs the confirmed half.
- **Failure memory**, because the ledger it needs exists, and the third
  time you hit a failure is not the same event as the first.

## Not prompt features

These two came off the roadmap rather than out of the field. Neither
passes the test at the top of this file -- they are maintainer tools,
not things an AI at the prompt does -- so they sit apart here rather
than pretending otherwise.

- **Line-bench.** About forty questions per OS with a checker each,
  through the real `spark line` path: `spark bench --lines`, one pass
  rate and one median latency per model, kept beside the speed baseline.
  The table would then choose on quality and speed, not size alone.
- **`spark token`.** Bare `spark token` names which keys this machine
  holds (api-token, admin token, login) and whether the brain accepts
  each -- status only, never a value, with the remedy per stale key.
