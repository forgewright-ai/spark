# Ideas

What an AI at the shell prompt could do that nothing else can. This file
is upstream of `docs/ROADMAP.md`: the roadmap is what comes next in order,
this is the wider field it is picked from. Nothing here is a promise; a
row in `docs/CHANGELOG.md` is. An idea that earns a place moves to the
roadmap and leaves here.

This document is not tied to a spark release. It is kept true as
things change, but it is outside the landing rule: nothing here has to
appear in `spark help`, `docs/CHEATSHEET.txt` or a `docs/CHANGELOG.md` entry,
and no release waits on it.

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

## 1. One FORGE, many prompts

Threads are sealed and per-user, and every client talks to one FORGE
(contract 9). `??` across machines shipped in v1.30; what remains:

- **Two people, one box.** Named users have sealed stores already: two
  prompts on one machine, one soul, and the admin genuinely cannot read
  the other's history. No hosted assistant can make that promise.

## 2. The machine's own doctor

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
| The doctor | medium -- reads what exists | the machine |

## Parked

- **A shared engine as a system service.** `spark share` (v1.22) covers
  the need through a `spark` group; the system-unit form (a service
  account, models outside any `$HOME`) waits until the group model has
  been lived with -- it costs root, a service user and new paths, and
  nothing yet asks for them.

## Not prompt features

These came off the roadmap, or off a reboot, rather than out of the
field. None passes the test at the top of this file -- they are the
machine's own tools, not things an AI at the prompt does -- so they sit
apart here rather than pretending otherwise.

- **Line-bench.** About forty questions per OS with a checker each,
  through the real `spark line` path: `spark bench --lines`, one pass
  rate and one median latency per model, kept beside the speed baseline.
  The table would then choose on quality and speed, not size alone.
- **`spark token`.** Bare `spark token` names which keys this machine
  holds (api-token, admin token, login) and whether the brain accepts
  each -- status only, never a value, with the remedy per stale key.
