# Roadmap

What comes after v1.40, in the order it is likely to happen. Nothing here
is a promise; a row in `docs/CHANGELOG.md` is. `docs/IDEAS.md` is the field this
is picked from.

The rule for this stretch: spark has one user, on one box, and what
that use measures goes first. No new contract and no new verb until the
first two items below are done -- fourteen contracts is more surface
than one person lives in, and the two numbers that describe the daily
experience have been sitting in the ideas file behind the test suite.

## 1. The wait for the first line is the model's own speed

Measured 2026-09-14 on the box's 12B with v1.32's instrument, a 14 kB
source, the same question three times, a chat in between the second
and the third:

- cold: 3632 prompt tokens processed at 185 tok/s, 43.7 s in all
- again: 1 prompt token processed, 3632 from the cache, 26.6 s
- after a chat: 3632 from the cache still, 24.6 s

So the prefix cache holds, the reading pass restates the same bytes, a
chat in between does not evict it, and `--cache-ram 0` costs nothing.
Item 1 as first written (the rerun costs what the first run cost) was
wrong: the rerun saves exactly the prefill, and what remains is
generation -- 90 tokens at 4.9 tok/s -- plus the reading pass. The 9 s
first line of the original note is a 12B writing thirty-odd tokens at
that speed. Three levers, in order:

- **A faster ember for reading.** Generation speed is the wait, and it
  is the model's. This is item 2 turned into a choice: the `_GROUND`
  score beside a `tg` number per row on THIS box, and the reading
  contracts get the smallest row whose score holds. Nothing in the
  tree moves the first line more than halving the model.
- **The reading pass, measured: 7.4 s of 34.4 s.** Recorded as its own
  turn since v1.32 (mode `edit-read`). On the box it is not on a small
  model: the ember is `none`, so the 12B answers both roles, and the
  pass is 306 prompt tokens and 28 generated at 4.9 tok/s before the
  answer starts -- a fifth of the whole wait for two words. The cheap
  form: no second request; the answer brief asks for the reading as
  the answer's first line (`Read as: LANGUAGE, KIND.`), which the gate
  drops as unquoted and the reader never sees, ten tokens in-stream
  instead of a round trip with its own prefill. The audition judges
  it against the two-request form before it lands.
- **`--warm` on contract 11.** The cold prefill is 20 s of the 43.7 s,
  and cold is the common case: a page is read once. A reading client
  sends the source the moment its key is pressed, no question yet,
  and the typing hides the prefill. The cache holds, so the warm call's
  prefix is reused by the real one; this is the one prefill lever.

Measured 2026-09-14, the three rows that fit the box's 9 GB, one model
in both roles, a 6 kB source that answers, the audition once each:

| model | tg tok/s | reading pass | first line cold / warm | audition |
|---|---|---|---|---|
| Gemma 3 12B | 5.5 | 7.6 s | 20.1 s / 8.0 s | 5/9 |
| Qwen3 8B | 8.7 | 3.9 s | 19.8 s / 5.0 s | 7/9 |
| Qwen3 4B | 16.2 | 2.3 s | refused both | 5/9 |

The decision is the 8B: faster than the 12B and better grounded, and
the 4B's speed buys nothing when the gate drops every line it writes.
`spark model qwen3-8b` on the box, one command, and the first lever is
pulled. What stays open, in order: the reading pass in-stream (3.9 s of
every read on the 8B), then `--warm` (the cold first line is 20 s on
either model and 5 s warm: the prefill and the pass are the cold cost,
and typing hides them).

Not levers: the cache flag, the message order (the prefix already
hits), a shorter brief (a few lines is already the ask). One note on
the instrument: `first_ms` exists only on a kept answer -- a refusal
has no first line, so a source cut where the answer is not (a man
page's boilerplate, a wiki's navigation) measures the whole wait and
records no first line; measure with a source that answers.

## 2. Grounding, graded on every row `auto` may pick

Three rows carry a `_GROUND` score (Qwen3 8B 21/27, Qwen3 4B 5/9,
Gemma 3 12B 5/9 -- the two new ones from a single run, so plus or minus
one). Three rows proven on the line carry none (1.7B, 14B, 30B-A3B),
and `auto` prefers a grounded row when two fit the budget -- so the
preference is still blind between those.

- run `tests/audition.py --json` on each `_TESTED` row and write the
  score into `models.env` by hand, the way `_TESTED` carries the line
  proof; the page's model table then shows the reader's quality, not
  only the prompt's
- the read-about case (the ninth in the audition) stays the measure of
  the gap: three brief rewrites each traded that miss for false
  grounding elsewhere, so the brief does not move again until a
  mechanism, not a wording, closes it

## 3. Bind where promised

Seen twice on the box on 2026-09-19: a reboot brings the WiFi up before
the wire, the serve and forge units start five seconds in, `lan_ip()`
reads the default route of that instant, and the engine lands on the
WiFi address while `/etc/spark/url` and every client still name the
wire. A restart of the two units once both links were up put it right
each time; the `serve` and `forge` rows already say `moved`.

- one rule at serve and forge start: when the machine has already
  promised an address (the published `/etc/spark/url`, or the last
  `serve-url`), wait up to 30 s for it to appear on an interface before
  binding; otherwise bind the lowest-metric default route's source, not
  the first route that exists
- the two rows' remedy stays `restart the unit`; a changelog line says
  what the wait is and when it gives up
- the no-code answer for a box with one link stays true: drop the WiFi
  from its network config and the race is gone

## 4. Live in it, and let the turn records pick

`spark stats` reads the turn records -- numbers only, never words. For
the length of this stretch the roadmap is read from them, not written
from the founder's chair:

- once a week, which verbs ran and which did not; a verb unused for a
  month is a candidate to leave, and one that runs forty times a day is
  where the next hour goes
- a tag when something is stable enough to defend, not per commit:
  `spark update` on a clone follows the newest tag, so a tag is a
  promise to that clone
- the two small history items that pass `docs/IDEAS.md`'s test and cost
  almost nothing, once the numbers say the hint row is read: the
  command you keep retyping (an alias you do not have, offered once,
  counts only), and the tool you have and do not use (ten `find` on a
  box with `fd` earns one line, once; `persona.PREFERRED` is the list)

## 5. The first other person

Before an issue tracker exists: one person, known, installs spark
unattended on their own machine with nothing but the README, and says
what broke. CI's container proves the one-liner on a clean image; it
does not prove it on a laptop with a life on it. Issues open after that
conversation, not before -- a founder is the worst reporter of their
own product, and a public tracker with nobody behind it is worse than a
closed one.

## 6. Chaos on a real box

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

(A shared engine as a system service is parked in `docs/IDEAS.md`: only
worth weighing once the group model has been lived with.)
