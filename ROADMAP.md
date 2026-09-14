# Roadmap

What comes after v1.32, in the order it is likely to happen. Nothing here
is a promise; a row in `CHANGELOG.md` is. `IDEAS.md` is the field this
is picked from.

The rule for this stretch: spark has one user, on one box, and what
that use measures goes first. No new contract and no new verb until the
first two items below are done -- fourteen contracts is more surface
than one person lives in, and the two numbers that describe the daily
experience have been sitting in the ideas file behind the test suite.

## 1. The rerun costs what the first run cost

Measured 2026-09-13, on the box's 12B: 12.8 s to the first line of a
`spark read` answer cold, and 9.0 s asking the SAME source the SAME
question again. A server reusing the processed prefix would land the
rerun in 2-3 s; it barely does. Nothing else on this list moves what
the prompt feels like as much.

What the tree says (read for v1.32): every request asks for the cache
(`cache_prompt: true`); the system message is byte-stable per machine,
mode and soul; the request's user message is the question, then the
reading pass's words, then the source. Two things can throw the cached
prefix away before the 16 kB source: the reading pass sampling a
different word on the same source (v1.32 makes it greedy), and another
request replacing the slot in between -- a chat, a `?` at the prompt --
which `--cache-ram 0` (the v1.7 leak fix) makes unrecoverable. The
server may also have hit every time, and the 9 s be the reading pass
plus the first line's own generation; the numbers say which.

- read them: `spark stats` now shows the read mode's cache hit rate and
  its median wait to the first line -- a rerun that hits shows a cache
  rate near the prompt's length; one that does not shows 0 %
- if the rate is low with v1.32: put the source ABOVE the question and
  the reading line in the user message, so the big stable block is the
  prefix whatever is asked of it (the audition judges the briefs after)
- if a slot lost in between is the cause: `SPARK_EXTRA_ARGS=--cache-ram
  1024` is the experiment, no code change, the `serve` row reports it
  and the RAM is watched at the same time; a bounded default follows
  only if the leak stays fixed
- keep it: the first-line wait in `spark stats` is the number; a rerun
  case beside the speed baseline in `spark bench` once it is known

Done when the same question again lands its first line in 2-3 s and
the leak stays fixed. Only then is `--warm` on contract 11 worth
building: a reading client sends the source the moment its key is
pressed, no question yet, and the first line lands almost at Enter.

## 2. Grounding, graded on every row `auto` may pick

One model carries a `_GROUND` score today (Qwen3 8B, 21/27). The other
four rows proven on the line carry none, and `auto` prefers a grounded
row when two fit the budget -- so today the preference is blind.

- run `tests/audition.py --json` on each `_TESTED` row and write the
  score into `models.env` by hand, the way `_TESTED` carries the line
  proof; the page's model table then shows the reader's quality, not
  only the prompt's
- the read-about case (the ninth in the audition) stays the measure of
  the gap: three brief rewrites each traded that miss for false
  grounding elsewhere, so the brief does not move again until a
  mechanism, not a wording, closes it

## 3. Live in it, and let the turn records pick

`spark stats` reads the turn records -- numbers only, never words. For
the length of this stretch the roadmap is read from them, not written
from the founder's chair:

- once a week, which verbs ran and which did not; a verb unused for a
  month is a candidate to leave, and one that runs forty times a day is
  where the next hour goes
- a tag when something is stable enough to defend, not per commit:
  `spark update` on a clone follows the newest tag, so a tag is a
  promise to that clone
- the two small history items that pass `IDEAS.md`'s test and cost
  almost nothing, once the numbers say the hint row is read: the
  command you keep retyping (an alias you do not have, offered once,
  counts only), and the tool you have and do not use (ten `find` on a
  box with `fd` earns one line, once; `persona.PREFERRED` is the list)

## 4. The first other person

Before an issue tracker exists: one person, known, installs spark
unattended on their own machine with nothing but the README, and says
what broke. CI's container proves the one-liner on a clean image; it
does not prove it on a laptop with a life on it. Issues open after that
conversation, not before -- a founder is the worst reporter of their
own product, and a public tracker with nobody behind it is worse than a
closed one.

## 5. Chaos on a real box

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

(A shared engine as a system service is parked in `IDEAS.md`: only
worth weighing once the group model has been lived with.)
