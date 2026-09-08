# Roadmap

What comes after v1.15, in the order it is likely to happen. Nothing here
is a promise; a row in `CHANGELOG.md` is. A better idea is an issue away.

## Contract 11: `spark read`

The reader's protocol -- the source on stdin, a question in the words,
raw text out, never a path. `lib/spark/read.py` holds this text and the
constants beside the code that will fill it.

- Every claim quotes the source. A line whose quotes are not in it is
  dropped, and so is a line that quotes nothing: an unquoted sentence
  about a source is the model's own knowledge wearing the source's
  clothes.
- When the source does not answer, the whole reply is one line naming
  what the source does cover -- composed here, from the source's own
  words. Never "the text does not say, but generally ...".
- 16 kB a part, `--part N` beyond that, and the answer names which part
  it read in its first line, always: an answer from part 2 that does not
  say so cannot be told from an answer about the whole.
- Ledger kind `read`: the questions asked of this source, so a second
  reader sees what has been asked. Nothing invalidates them -- a source
  does not change; that is what makes it a source -- and none of them
  suppresses a question, unlike a note declined in a draft.

## Contract 13: `spark drill`

Practice against a source: the source on stdin, one question at a time
out, your answer in. `lib/spark/drill.py` holds this text.

- Both the question and the correct answer come from the source. The
  model composes neither: it proposes a span of the source as the answer
  and a question that span answers, and a question whose answer does not
  anchor in the source is dropped before it is ever asked. A drill built
  on an invented answer teaches the invention.
- Material too thin for questions is said in one line, never padded from
  the model's own knowledge -- the learner cannot tell padding from the
  source.
- Self-graded against the sourced answer to begin with: you see the span
  and say whether you had it. A second model grading a first model's
  question is two opinions and no source.
- Ledger kind `drill` schedules rather than suppresses, the inversion of
  every other kind: a missed item comes back at 1, 3, 7, 21 and 60 days
  until it has been answered right twice in a row. Its records carry
  state the other kinds do not, and alone among them they never age out
  -- a schedule that expires is not a schedule.

## Chaos: rehearse the failures

`spark chaos` (or `spark check --chaos`) breaks the machine one known way
at a time and proves the right row goes red and its remedy heals it.
Hermetic first (the stub servers learn to be slow, to hang, to 503, to
cut a stream), then once on a real box. Not part of a new user's check.

- the server killed mid-reply -- `serve`; the unit brings it back
- a truncated model file -- `models`; `spark model verify` names it
- a full disk -- the download refuses cleanly, no `.part` left
- the GPU taken away -- `gpu`; the line still answers on the CPU
- the LAN cut on a client -- `peer`; `??` and chat fail fast
- two `spark serve` or two `spark update` at once -- the lock wins
- a clone three tags behind -- `git`; `spark update` moves it
- a hostile line answer (not JSON, empty, 40 kB) -- the widget runs
  nothing, keeps the prompt

## Line-bench: a quality number per model and OS

About forty questions per OS with a checker each, through the real
`spark line` path: `spark bench --lines`, one pass rate and one median
latency per model, kept beside the speed baseline. The table then
chooses on quality and speed, not size alone.

## Per-OS exemplars in the line

The misses so far are macOS knowledge (`free` for `vm_stat`). A short
block of per-OS examples in the line's prefix is the cheapest gain.

## Per-OS user accounts

Real OS users, each running their own spark against one shared engine:
the port story, a shared model cache with per-user config, a system unit
serving all of them. After the account layer has been lived with.

## spark token: status for the keys that remain

Bare `spark token` names which keys this machine holds (api-token, admin
token, login) and whether the brain accepts each -- status only, never a
value, with the remedy per stale key.
