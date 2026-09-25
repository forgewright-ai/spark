# Roadmap

What comes after v1.49, in the order it is likely to happen. Nothing
here is a promise. A row in `docs/CHANGELOG.md` is. `docs/IDEAS.md` is
the field this is picked from.

The rule for this stretch: spark has one user, on one box, and what
that use measures goes first. No new contract and no new verb until
the first two items below are done. Fifteen contracts is more surface
than one user lives in, and the two numbers that describe the daily
experience have sat in the ideas file behind the test suite.

## 1. The wait for the first line is the model's own speed

Measured 2026-09-14 on the box's 12B with v1.32's instrument: a 14 kB
source, the same question three times, a chat between the second and
the third.

- Cold: 3632 prompt tokens processed at 185 tok/s, 43.7 seconds in
  all.
- Again: 1 prompt token processed, 3632 from the cache, 26.6 seconds.
- After a chat: 3632 from the cache still, 24.6 seconds.

So the prefix cache holds, the reading pass restates the same bytes, a
chat in between does not evict it, and `--cache-ram 0` costs nothing.
Item 1 as first written said the rerun costs what the first run cost.
That was wrong: the rerun saves exactly the prefill. What remains is
generation, 90 tokens at 4.9 tok/s, plus the reading pass. The 9
second first line of the original note is a 12B writing about 30
tokens at that speed. Three levers, in order.

The first lever is a faster chat model for reading. Generation speed
is the wait, and it is the model's. This is item 2 turned into a
choice. The `_GROUND` score sits beside a `tg` number per row on this
box, and the reading contracts get the smallest row whose score holds.
Nothing in the tree moves the first line more than halving the model.

The second lever is the reading pass, measured at 7.4 seconds of 34.4.
It is recorded as its own turn since v1.32, as mode `edit-read`. On
the box it does not run on a small model: the chat model is `none`,
so the 12B answers both roles. The pass is 306 prompt tokens and 28
generated at 4.9 tok/s before the answer starts, a fifth of the whole
wait for two words. The cheap form is no second request. The answer
brief asks for the reading as the answer's first line, `Read as:
language, kind.`. The gate drops that line as unquoted, and the reader
never sees it. That is 10 tokens in the stream instead of a round trip
with its own prefill. The audition judges it against the two-request
form before it lands.

The third lever is `--warm` on contract 11. The cold prefill is 20
seconds of the 43.7, and cold is the common case: a page is read once.
A reading client sends the source the moment its key is pressed, with
no question yet, and the typing hides the prefill. The cache holds, so
the real call reuses the warm call's prefix. This is the one prefill
lever.

Measured 2026-09-14 on the three rows that fit the box's 9 GB, one
model in both roles, a 6 kB source that answers, the audition once
each:

| model | tg tok/s | reading pass, seconds | first line cold / warm, seconds | audition |
|---|---|---|---|---|
| Gemma 3 12B | 5.5 | 7.6 | 20.1 / 8.0 | 5/9 |
| Qwen3 8B | 8.7 | 3.9 | 19.8 / 5.0 | 7/9 |
| Qwen3 4B | 16.2 | 2.3 | refused both | 5/9 |

The decision is the 8B. It is faster than the 12B and better grounded,
and the 4B's speed buys nothing when the gate drops every line it
writes. `spark model qwen3-8b` on the box is one command, and the first
lever is pulled. What stays open, in order: the reading pass in the
stream, 3.9 seconds of every read on the 8B, then `--warm`. The cold
first line is 20 seconds on either model and 5 seconds warm: the
prefill and the pass are the cold cost, and typing hides them.

Not levers: the cache flag, the message order, since the prefix already
hits, and a shorter brief, since a few lines is already the ask. One
note on the instrument: `first_ms` exists only on a kept answer. A
refusal has no first line. So a source cut where the answer is not, a
man page's boilerplate or a wiki's navigation, measures the whole wait
and records no first line. Measure with a source that answers.

## 2. Grounding, graded on every row `auto` may pick

Four rows carry a `_GROUND` score: Qwen3 8B 21/27, Qwen3 4B 5/9,
Gemma 3 12B 5/9 and Granite 4.2 8B 25/30, the best. The 4B and the
12B scores come from a single run, so plus or minus one. Three rows
proven on the line carry none: the 1.7B, the 14B and the 30B-A3B.
`auto` prefers a grounded row when two fit the budget, so between
those three the preference is still blind.

- Run `tests/audition.py --json` on each `_TESTED` row and write the
  score into `models.env` by hand, the way `_TESTED` carries the line
  proof. The page's model table then shows the reader's quality, not
  only the prompt's.
- The read-about case, the ninth in the audition, stays the measure of
  the gap. Three brief rewrites each traded that miss for false
  grounding elsewhere, so the brief does not move again until a
  mechanism, not a wording, closes it.

## 3. Bind where promised

Seen twice on the box on 2026-09-19. A reboot brings the Wi-Fi up
before the wire, and the `serve` and `forge` units start 5 seconds in.
`lan_ip()` reads the default route of that instant, so the engine
lands on the Wi-Fi address while `/etc/spark/url` and every client
still name the wire. A restart of the two units once both links were
up put it right each time. The `serve` and `forge` rows already say
`moved`.

- One rule when `serve` and `forge` start: an address the machine has
  promised, in `/etc/spark/url` or `serve-url`, gets 30 seconds to
  appear on an interface before the bind. Otherwise the bind takes the
  source of the default route with the lowest metric, not the first
  route that exists.
- The two rows' remedy stays `restart the unit`. A changelog line says
  what the wait is and when it gives up.
- The answer without code for a machine with one link stays true: drop
  the Wi-Fi from its network config and the race is gone.

## 4. Live in it, and let the turn records pick

`spark stats` reads the turn records: numbers only, never words. For
the length of this stretch the roadmap is read from them, not written
from the maintainer's chair.

- Once a week, which verbs ran and which did not. A verb unused for a
  month is a candidate to leave, and one that runs 40 times a day is
  where the next hour goes.
- A tag when something is stable enough to defend, not per commit.
  `spark update` on a clone follows the newest tag, so a tag is a
  promise to that clone.
- The two small history items that pass the test in `docs/IDEAS.md`
  and cost almost nothing, once the numbers say the hint row is read.
  The first is the command you keep retyping: an alias you do not
  have, offered once, counts only.
- The second is the tool you have and do not use: 10 `find` on a
  machine with `fd` earns one line, once. `persona.PREFERRED` is the
  list.

## 5. The first new user

Before an issue tracker exists: one new user, someone known, installs
spark unattended on their own machine with nothing but `README.md`,
and says what broke. CI's container proves the one-liner on a clean
image. It does not prove it on a laptop with a life on it. Issues open
after that conversation, not before. The maintainer is the worst
reporter of the product, and a public tracker with nobody behind it is
worse than a closed one.

## 6. Chaos on a real box

What a fixture cannot reach is the maintainer's to do by hand, as the
WSL pass is:

- The engine killed mid-reply. The unit must bring it back, and the
  fixture proves only the `serve` row.
- A genuinely full disk, on a real filesystem, not curl's write error
  faked.
- The GPU taken away for real: a card removed, not an empty sysfs.
- Two machines, one server: the server dies mid-answer for a client.

Then the two shapes the suite still cannot express: a scenario whose
remedy needs the network, such as a re-download after `spark model
rm`, and one that must survive a reboot.

A shared engine as a system service is parked in `docs/IDEAS.md`. It
is only worth weighing once the group model has been lived with.

## 7. A refused field is a refused option

Seen 2026-09-23 on the box: a step ran `ps -p ... -o pid,cmd,%mem,%vsz`
and procps answered `error: improper AIX field descriptor`.
`do.BAD_OPTION` knows `unrecognized|invalid|unknown option` and
`illegal option`, not procps' wording, so no man page lines came back
and the model guessed at the next flag twice.

- Widen `do.BAD_OPTION` with the wordings the tools on the box print
  for a bad option or field: procps prints `improper ... field
  descriptor` and `unknown user-defined format specifier`. Each is a
  named line with a smoke case, and the man excerpt then finds the
  field's own lines.

## 8. spark do goes on

Seen the same evening: `spark do again` ran as a new goal with nothing
to go on and spent its eight steps listing the home directory. The run
before it had its answer in `free -h` at step two and never said so.
`spark line` continues its newest thread with `??`. `spark do` has no
way to say "the last run: again" or "go on".

- `spark do ?? [words]` continues the newest do thread with its goal
  and steps as the history, the same budget and the goal kept. The
  words are the next user message, and bare `??` means "go on".
- `??` then means the newest thread everywhere, one grammar.
