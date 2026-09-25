# Ideas

What an AI at the shell prompt can do that nothing else can. This file
is upstream of `docs/ROADMAP.md`: the roadmap is what comes next, in
order, and this is the wider field it is picked from. Nothing here is
a promise. A row in `docs/CHANGELOG.md` is. An idea that earns a place
moves to the roadmap and leaves here.

This document is not tied to a spark release. It is kept true as
things change, but it is outside the landing rule. Nothing here has to
appear in `spark help`, `docs/CHEATSHEET.txt` or a `docs/CHANGELOG.md`
entry, and no release waits on it.

Each entry says what it is, what it looks like at the prompt line and
what it costs: which contract it extends, or whether it needs a new
one.

## Why the prompt line, and why local

Two things are already built, and almost nothing else has both:

- The line is spark's: the `Esc s` binding reads the line you typed,
  calls `spark line` (contract 4) and puts the answer back in the line
  before the shell runs it. A pane that prints an answer beside your
  shell is a different, smaller thing.
- The failure moment: a nonzero exit prints one line above the next
  prompt, and the command and its status live in that pane's variables
  since v1.15. The shell's most useful instant is caught with no model
  call and no fork.

One thing is structural: the model is on this machine, and every
prompt on it talks to one server, the page's (contract 9), with the
threads sealed per user. The most valuable text at a shell is your
history, your logs, a script you were about to paste, a diff. That is
exactly the text nobody sends to a vendor. Every idea below that reads
such text is possible here and not there. Those are marked local-only.

The test for an idea in this file: could a chat window in another pane
do it as well? If yes, it is not a prompt feature.

## An answer from the machine's own numbers

`spark check` answers 40 questions with yes or no, and `spark stats`
has the numbers. Let a model read `check.json` and `bench.jsonl` and
answer the question the rows cannot:

```
~ > ? why is it slow today
* KV cache off since the last tune; 4.1 tok/s against a 12.3 baseline
```

The forecast is the same trick pointed forward: "the disk fills in
about 3 days at this rate". It stays honest, because it is made of
numbers spark already keeps and words that never leave.

## Where to start

| idea | cost | surface |
|---|---|---|
| An answer from the numbers | medium, it reads what exists | the machine |

## Parked

A shared engine as a system service. `spark share`, since v1.22,
covers the need through a `spark` group. The system-unit form, with a
service account and models outside any home directory, costs root, a
service user and new paths. Nothing asks for them yet, so it waits
until the group model has been lived with.

## Not prompt features

These came off the roadmap or off a reboot, not out of the field. None
passes the test at the top of this file: they are the machine's own
tools, not things an AI at the prompt line does. They sit apart here.

- Line-bench: about 40 questions per OS with a checker each, through
  the real `spark line` path. `spark bench --lines` gives one pass
  rate and one median latency per model, kept beside the speed
  baseline, and the table then chooses on quality and speed, not size
  alone.
- `spark token`: bare `spark token` names which keys this machine
  holds, the api-token, the admin token and the login, and whether the
  server accepts each. Status only, never a value, with the remedy per
  stale key.
