# The tour -- a first hour with spark

spark is installed, `spark check` says every promise is kept, and the
prompt answers. This is the fun part: twelve small things to try, in
four acts. Each one is a habit worth keeping.

This document is not tied to a spark release. It is kept true as
things change, but it is outside the landing rule: nothing here has to
appear in `spark help`, `CHEATSHEET.txt` or a `CHANGELOG.md` entry,
and no release waits on it.

Most of the tour needs only spark. A few stops use a spark app or the
shell (micro with spark-micro, tmux and btop from spark-shell) and say
so; skip what you have not installed yet.

## Act 1 -- the prompt is alive

Ask the shell itself. Type:

    ? what is eating my disk

The command lands in your line, a hint above it; Enter runs it. A `!`
in the hint means read it first -- and a recursive rm says how many
files and bytes it clears, before you commit to it, not after.

Break something on purpose. Run a command with a typo -- `sl`, or
`git pushh` -- then press Esc s on the empty line: the failed command
is explained. Esc s again offers the fix.

Ask a follow-up:

    ?? how do I change the model

spark knows itself: it names its own verbs.

## Act 2 -- the editor has an opinion  (micro + spark-micro)

Make it write. Open an empty file (`micro poem.md`), press Alt-s and
give it words:

    spark> a short poem about this machine

An empty text with words is written from nothing. Now interrogate what
it wrote: Alt-s, then `?` alone. The review lands in a pane on the
right, and every quote in it is checked against your text -- a claim
the text does not back is marked `[not in the text]` where it stands.
The reviewer is policed.

The rewrite dance. Select one stanza, Alt-s, say what you want:

    spark> make it rhyme

The new text comes back selected -- a proposal, never applied
silently. micro's undo (Ctrl-z) puts it back.

Write with a companion (tmux). In one pane:

    spark edit --watch poem.md

micro in the other. Save a stanza; a comment appears. Go quiet for a
minute; it reads the whole draft. Answer it back with Alt-s.

## Act 3 -- the machine reads for you

Never read a man page again:

    man zoxide | spark read how do I jump to a folder

Every line of the answer quotes the page, and a line that cannot quote
it never reaches you. Silence and exit 1 mean the page does not say --
no answer is a real answer here. (A long page is read in parts;
`--part N` picks one.)

Let spark teach you spark:

    spark drill --name spark < ~/.spark/CHEATSHEET.txt

The cheatsheet becomes questions it answers; you say whether you had
each one. `--name` keeps the schedule: a miss comes back tomorrow,
then in three days, then seven. The tour revises itself.

Set a watchman, in a pane you can forget:

    journalctl -f | spark watch anything that fails

Silence is the healthy state. The one line that ever appears quotes
the log, so "a failure appeared" cannot fire when none did.

## Act 4 -- yours, everywhere on the LAN

Give it a voice of its own:

    spark soul edit

Two sentences are plenty. Then teach it one fact:

    spark memory add "short answers, and call me by name"

Chat once (`spark chat`) and feel the difference. The soul and the
facts ride on every answer, and they are yours: files under your own
`~/.config/spark/`, never leaving the machine.

The pocket test:

    spark forge --print-url

Open that address in your phone's browser, log in, and go on with the
thread you started at the terminal. Same voice, same facts, another
door. Share -> add to home screen makes it an app.

Watch it think (tmux + btop). btop in one pane, `spark chat` in the
other: memory fills as the model loads, the cores light up as it
answers. No lesson in this one. It is just a good show.

## When you want more

`spark <TAB>` completes every verb, `spark check` says what this
machine promises, `lp CHEATSHEET.txt` prints the one-page reference --
and

    ? what should I try next with spark

is a fair question.
