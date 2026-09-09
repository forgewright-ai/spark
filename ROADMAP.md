# Roadmap

What comes after v1.18, in the order it is likely to happen. Nothing here
is a promise; a row in `CHANGELOG.md` is. A better idea is an issue away.

## Contract 11: spark read

`spark edit` works on text you are writing. There is no verb for text you
are reading: the source on stdin, a question in the words, raw text out,
never a path.

- every claim quotes the source. A line whose quotes are not in it is
  dropped, and so is a line that quotes nothing -- an unquoted sentence
  about a source is the model's own knowledge wearing the source's
  clothes
- when the source does not answer, the whole reply is one line naming
  what the source does cover, composed from the source's own words --
  never "the text does not say, but generally ..."
- 16 kB a part, `--part N` beyond that, and the answer names the part it
  read in its first line: an answer from part 2 that does not say so
  cannot be told from an answer about the whole
- ledger kind `read`: the questions asked of this source, so a second
  reader sees what has been asked. Nothing invalidates them -- a source
  does not change, and that is what makes it a source -- and none of
  them suppresses a question, unlike a note declined in a draft

The gate `spark ask` landed -- `text.Gate`, `text.Ground` -- is the
machinery. This is the second verb through it, and `lib/spark/read.py`
holds this text beside the code that will fill it.

## Contract 13: spark drill

Practice against a source: the source on stdin, one question at a time
out, your answer in. `lib/spark/drill.py` holds this text.

- both the question and the correct answer come from the source. The
  model composes neither: it proposes a span of the source as the answer
  and a question that span answers, and a question whose answer does not
  anchor in the source is dropped before it is ever asked -- a drill
  built on an invented answer teaches the invention
- material too thin for questions is said in one line, never padded from
  the model's own knowledge: the learner cannot tell padding from the
  source
- self-graded against the sourced answer to begin with -- you see the
  span and say whether you had it. A second model grading a first
  model's question is two opinions and no source
- ledger kind `drill` schedules rather than suppresses, the inversion of
  every other kind: a missed item comes back at 1, 3, 7, 21 and 60 days
  until it has been answered right twice in a row. Its records carry
  state the other kinds do not, and alone among them they never age out
  -- a schedule that expires is not a schedule

## Contract 14: spark watch

`spark edit` takes a body of text. There is no verb for a live one.

```
tail -f app.log | spark watch "tell me when a 500 appears"
journalctl -f  | spark watch "anything about the disk"
```

Silent until something matters, then one line. Nobody streams a
production log to a vendor by the megabyte, so this is local-only in the
strongest sense, and the same shape covers a long build, a test watcher
and a slow migration. The hard parts are honest ones: what a window is,
how it says nothing for an hour without looking dead, and how it stays
cheap enough to leave running.

## Chaos on a real box

What a fixture cannot reach is the maintainer's, by hand, as the WSL
pass is:

- the server killed mid-reply -- the unit must bring it back (the
  fixture proves only the `serve` row)
- a genuinely full disk -- a real ENOSPC on a real filesystem, not
  curl's write error faked
- the GPU taken away for real -- a card removed, not an empty sysfs
- two machines, one FORGE: a peer that dies mid-answer for a client

Then the two shapes the suite still cannot express: a scenario whose
remedy needs the network (a re-download after `spark model rm`), and
one that must survive a reboot.

## Per-OS user accounts

Real OS users, each running their own spark against one shared engine:
the port story, a shared model cache with per-user config, a system unit
serving all of them. After the account layer has been lived with.
