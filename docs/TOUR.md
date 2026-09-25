# The tour

spark is installed, `spark check` says every row is ok, and the prompt
line answers. This is the fun part: 12 small things to try, in 4 acts.
Each one is a habit worth keeping.

This document is not tied to a spark release. It is kept true as
things change, and no release waits on it.

Most of the tour needs only spark. A few stops use a spark app or a
tool, such as micro with spark-micro, tmux or btop, and say so. Skip
what you have not installed yet. `Alt-s` is Option-s on a Mac.

## Act 1, the prompt line

Ask the shell itself. Type:

    ? what is eating my disk

The command lands in your line, with a hint above it. `Enter` runs it.
A `!` in the hint means read it first. A recursive `rm` says how many
files and bytes it clears, before you commit to it, not after.

Break something on purpose. Run a command with a typo, `sl` or `git
pushh`, then press `Esc s` on the empty line. The failed command is
explained. `Esc s` again offers the fix.

Ask a follow-up:

    ?? how do I change the model

spark knows itself: it names its own verbs.

## Act 2, the editor

This act uses micro with spark-micro. Make it write. Open an empty
file with `micro poem.md`, press `Alt-s` and give it words:

    spark> a short poem about this machine

An empty text with words is written from nothing. Now ask about what
it wrote: `Alt-s`, then `?` alone. The review lands in a pane on the
right. Every quote in it is checked against your text. A claim the
text does not back is marked `[not in the text]` where it stands.

The rewrite. Select one stanza, press `Alt-s`, and say what you want:

    spark> make it rhyme

The new text comes back selected: a proposal, never applied on its
own. micro's undo, `Ctrl-Z`, puts it back.

Write with a companion, in tmux. In one pane:

    spark edit --watch poem.md

micro sits in the other. Save a stanza, and a comment appears. Go
quiet for 90 seconds, and it reads the whole draft. Answer it back
with `Alt-s`.

## Act 3, the machine reads

Man pages read themselves:

    man zoxide | spark read how do I jump to a folder

Every line of the answer quotes the page. A line that cannot quote it
never reaches you. When the page does not say, the reply is one line
with the page's opening words, and exit 1. A long page is read in
parts, and `--part N` picks one.

Let spark teach you spark:

    spark drill --name spark < ~/.spark/docs/CHEATSHEET.txt

The cheatsheet becomes questions it answers. You say whether you had
each one. `--name` keeps the schedule: a miss comes back tomorrow, then
in 3 days, then 7. The tour revises itself.

Set a watch, in a pane you can forget:

    journalctl -f | spark watch anything that fails

Silence is the healthy state. The one line that ever appears quotes
the log, so "a failure appeared" cannot fire when none did.

## Act 4, yours on the LAN

Give it a voice of its own:

    spark soul edit

Two sentences are plenty. Then teach it one fact:

    spark memory add "short answers, and call me by name"

Chat once with `spark chat` and feel the difference. The soul and the
facts ride on every answer. The soul is a file under
`~/.config/spark/`. The facts live sealed in your store. Both go to the
one server you chose: this machine's, or the one machine of yours a
client points at.

The pocket test:

    spark forge --print-url

Open that address in your phone's browser, log in, and go on with the
thread you started at the terminal. Same voice, same facts, another
door. Share, then add to home screen, makes it an app.

Watch it think, with tmux and btop. btop in one pane, `spark chat` in
the other: memory fills as the model loads, and the cores light up as
it answers. It is just a good show.

## When you want more

`spark <TAB>` completes every verb. `spark check` says what this
machine promises. `lp ~/.spark/docs/CHEATSHEET.txt` prints the one-page
reference. And

    ? what should I try next with spark

is a fair question.
