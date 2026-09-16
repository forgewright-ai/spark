# The grounding rule

What a model says about a text is checked against that text before you
read it. A line that does not check out is never shown. When nothing
checks out, the tool says so in its own words, not the model's.

That is the whole rule. spark applies it to five commands, and this
document states it so that any tool can, with or without spark.

This document is not tied to a spark release. It is kept true as the
rule's code changes, but it is outside the landing rule: nothing here
has to appear in `spark help`, `CHEATSHEET.txt` or a `CHANGELOG.md`
entry, and no release waits on it.

## Why

A language model writes fluently about a text it has not understood,
and it writes the same way about one it has. A reader cannot tell the
two apart by reading. Asking the model to be careful does not help: the
brief is a request, and the answer is still the model's word.

The rule moves the check out of the model and into code that runs after
it. The model is asked to point at the text -- to quote it, a few words
at a time -- and every quote is looked up. The model can still be
wrong, but it cannot be wrong and unchecked: a line that points nowhere
is dropped before anyone sees it.

Measured on 2026-09-14 on a 4B model: asked what a README says about
installing, it wrote twenty-one confident lines; not one quoted the
README, and the gate dropped them all. The reader saw one line saying
the source does not answer, and an exit code. Any tool without the rule
would have shown the twenty-one.

## The rule in five parts

1. **A claim carries a quote.** The brief asks for it: every line that
   says something about the text weaves a short piece of the text --
   character for character, at most twelve words, never across a line
   -- between quote marks. Double quotes, curly quotes and backticks all
   count; a span is 3 to 200 characters; a span made only of stop words
   ("the", "of") proves nothing and does not count.

2. **A quote is looked up.** First verbatim. Then with both sides folded
   -- whitespace collapsed, quote marks unified, case dropped. Then with
   the punctuation a model tucks inside a closing quote stripped. A span
   that survives none of these is not in the text. For a stream of
   short lines (a log), the lookup is at word boundaries, so "500" does
   not anchor in "1500ms".

3. **A line gets one verdict.** *Grounded*: it quotes, and at least one
   quote is in the text. *Ungrounded*: it quotes, and not one quote is
   -- fluent invention, the failure the rule exists to make impossible.
   *Unquoted*: it quotes nothing. A line with one good quote and one
   bad is grounded, and the bad one is marked where it stands:
   `[not in the text]`. A span right after an arrow (`->`) is the
   model's own proposal, not a quotation: it is not checked and is
   marked `[proposed]`.

4. **A gate sits between the model and the reader.** The stream is cut
   into lines; each line gets its verdict; the command decides what to
   keep; a kept line is written with its marks; a refused line is
   written nowhere. Kept and dropped are counted, and the counts are
   the only record: the words are not kept anywhere.

5. **A refusal is composed by code.** When the model wrote and nothing
   was kept, the reader gets one line that the tool wrote, not the
   model -- for a source, its own opening words -- on stderr, with exit
   code 1. Standard output stays empty. A program tells "no answer"
   from "an answer" by the exit code, never by reading prose.

What each command keeps, because one rule fits none of them exactly:

| command | keeps | drops |
|---|---|---|
| `spark read` | grounded lines | ungrounded, and unquoted: an unquoted sentence about a source is the model's own knowledge wearing the source's clothes |
| `spark ask` | questions, grounded or unquoted (a question need not quote) | ungrounded, statements, repeats, the generic |
| `spark watch` | one grounded line per window, word-boundary lookup | everything else: silence is the healthy state |
| `spark drill` | an answer span that is in the source, checked before the question is ever asked | an item built on an invented answer |
| `spark edit ?` | every line, marked | nothing: an editor's review shows its work and says which quotes to distrust |

## What it costs

- A model that writes well and quotes badly is refused. Small models
  fail more on quoting than on understanding; the rule makes that
  failure visible instead of fluent.
- Answers are short. A quote in every line is a discipline that
  produces a few lines, not a page.
- The brief has to ask for quotes, in words the model follows, and the
  ask is worth measuring: `tests/audition.py` scores a model on a set
  of grounded cases (kept over run), and `models.env` carries the
  score beside each model's name so the choice of model is made on it.
- Nothing is free of the lookup's limits. A paraphrase is not a quote,
  so a correct paraphrase is dropped; that is the trade, made on
  purpose: the reader is shown less and none of it is invented.

## Use it from any tool

The commands read text on standard input and write text on standard
output; nothing else is needed, no plugin, no protocol:

    w3m -dump URL | spark read "what is this page for"
    spark ask < plan.md
    tail -f app.log | spark watch "a 500 appears"

Exit 0: an answer, every line of it checked, on stdout. Exit 1: no
answer -- stdout empty, one line on stderr. Exit 2: the usage. An
editor, a mail reader, a feed reader or a script can be a client by
running the command and reading the exit code; the ones that already
do are listed in `APPS.md`.

## Take it into your own code

The rule is one file, `lib/spark/text.py`: Python's standard library,
no dependency, MIT like the rest of spark. Copy the file. Three names
matter:

- `anchor(span, text)` -- is this span in this text, by the lookup in
  part 2. `whole=True` for word-boundary matching.
- `Ground(text).verdict(line)` -- the verdict of part 3 and the spans
  the text lacks; `Ground(text).mark(line)` writes the marks.
- `Gate(stream, text, keep)` -- the gate of part 4: `write()` the
  model's chunks into it, `close()` at the end; `keep(line, verdict,
  misses)` is your command's rule; `kept`, `dropped`, `quoted`,
  `missed` and `spoke` are the counts.

Part 5 is yours to write: when `spoke` is true and `kept` is zero,
say so in one line of your own and exit 1. Part 1 is your brief's:
ask for the quotes, and measure whether your model gives them.

The tests that pin the rule are `tests/smoke.py` (the verdicts, the
marks, the refusals, the exit codes, against a stub model) and
`tests/audition.py` (the briefs against a live model, scored). Take
those too.
