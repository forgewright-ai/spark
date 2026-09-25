# Contributing to spark

spark is a local AI at the shell prompt, for Linux and macOS. This file
is the short path to a change that lands.

## Clone and run the gate

The tests are hermetic: a stub llama-server, a throwaway `HOME` and
`XDG_*` dirs. The tests run on any machine.

```sh
git clone https://github.com/forgewright-ai/spark.git
cd spark
git config core.hooksPath .githooks
```

The pre-commit and pre-push hooks together run the gate. `AGENTS.md`,
"The gate", lists every step. CI runs the gate on Ubuntu and macOS, and
the one-liner in Debian 13 and Arch containers. shellcheck is a
contributor's tool, not a user's package: `apt-get install shellcheck`,
`pacman -S shellcheck` or `brew install shellcheck`. The hook skips it
with a notice when absent.

A change to one of the editor's briefs (`persona.MODE_EDIT_*`) needs
more. Run `tests/audition.py` against a live model and put its before
and after totals in the pull request. The briefs are judged by lints,
not taste.

## Branch model

`main` is development. A git tag signed by a release key, a line in
`allowed-signers`, is a release. A user's clone follows the newest
release tag, and a developer clone follows `main`. `spark update` moves
either one forward and converges the machine. A tag no release key
signed moves nothing.

## Three ways to contribute without writing code

1. A model row. One row per pull request, in `models.env`: the 5
   fields, with the size and sha256 from Hugging Face's file metadata,
   its `_LICENSE` and an optional `_NOTE`. `_TESTED="line"` needs the
   line proof: `spark line` answers it with valid JSON. A proof for a
   row that is already there is a pull request too.
2. A credits correction. A wrong version, a missing license, a name
   that changed: `CREDITS.md` is a pull request away from being right.
3. A doc fix. A stale count, a broken cross-reference, a sentence that
   no longer matches the code. What a new user reads stays minimal and
   step by step, with two nouns, spark and spark apps, and
   `tests/docs_test.py` says which words are out. The project site,
   spark.forgewright.ai, is these docs rendered at the newest release
   tag, so a fix here reaches it with the next one. A fix in `docs/`
   needs no changelog entry.

## Code changes

Follow the landing rule in `AGENTS.md`. A feature is not done until it
is in `spark help`, a `spark <verb>`, a `spark check` row when it is a
promise, and every doc. Run the gate before you open a pull request.

Commit messages: a lowercase title line, and a body that says why, not
only what. Trailers are optional.

A spark app is an editor or another tool that becomes smart as a
client of one spark verb: `spark edit`, `spark line` or the page's API.
It lives in a repository of its own, and spark-micro is the shape.
spark itself ships no app, no app package and no app check row. A pull
request adding one is turned into a pointer to the app's own
repository.

## Privacy gate

The pre-commit hook checks staged changes for e-mail addresses, private
IPv4 ranges and absolute home paths naming a user. It also reads a
personal word list that does not exist in your fork, so you will see a
notice that it is missing. That is expected. Never add a real name, a
machine name or a project name to the tree regardless.

## Where to ask

Open an issue. `.github/ISSUE_TEMPLATE/` has a form for a model row and
one for a bug, and anything else is a blank issue. For a bug, paste
`spark check --report`. It is statuses only, with no value, no path and
no name, and it runs your privacy word list over itself before
printing.

## Roadmap

`docs/ROADMAP.md` lists what comes next. An idea that is not there is
an issue away.

## Voice

Every document, help text and usage text speaks with one voice: simple
and direct English. The rules below are the whole of it. A pull request
that follows them lands faster.

One word per thing:

- The machine: "this machine" for the reader's own, "another machine"
  for any other. "the box" names the maintainer's test machine and
  appears only in `CLAUDE.md` and `docs/ROADMAP.md`.
- The AI: "the model" is the file that answers, and "the engine" is
  the program that runs it (llama.cpp).
- The server: "the page's server" is the HTTP server the page and the
  API answer from. After the first mention, "the server".
- The chat model is "the chat model". The verb stays `spark ember`.
- The web UI is "the page", and the project site is spark.forgewright.ai
  by name. The verb stays `spark forge`, and the server's code name
  appears only in `CLAUDE.md` and `AGENTS.md`, in backticks.
- The place you type a question is "the prompt line".
- People: "you" in the customer docs. "The admin" is the machine's own
  account, and "a user" is a named account.
- "A new user" is a person meeting spark for the first time.
- The check: `spark check`, "a row", "every row ok".
- Another machine using this one's model is "a client". An editor or
  tool that talks to spark is "an app" or "a spark app".
- The colours are "the palette", and `spark theme` is the verb. "The
  console" is the Linux text console and "the terminal" an emulator.
- Installing is "install". The command is "the one-liner", and `spark
  setup` is a verb.

Form:

- British spelling, as the code prints: colour, behaviour, flavour.
  "Wi-Fi", "e-mail", "macOS", "GB", "kB", "characters".
- Numerals for every count and time: 30 seconds, 5 minutes, 12 things.
  A word only when a number starts a sentence.
- Keys in backticks: `Esc s` at the shell, `Alt-s` in an app (say
  "Option-s on a Mac" once per document), `Enter`, `Ctrl-C`.
- ASCII only, and " -- " is the only dash. No semicolon joining two
  clauses.
- Parentheses hold a short aside: a command, a key or one clarifying
  phrase.
- Capitals only for acronyms. No contractions and no "we".
- A number the tests derive (the row count, the model count, the palette
  keys) is stated once, in the file that owns it.

Sentences:

- Short sentences, present tense, active voice, the subject first. Under
  18 words on average in the customer docs, under 22 in the contributor
  docs, never over 30.
- A bullet is one or two sentences. A heading is a noun phrase.
- Say what it does. A sentence about what it does not do stays only when
  a reader needs the promise, such as what leaves the machine.
- One home per topic. The full explanation lives in one file, and every
  other mention is one sentence and a pointer to that file and section.
- A command sits in a fenced `sh` block or in backticks. A row or a
  message is quoted exactly as the code prints it.
- Prose wraps at 72 columns. Tables and fences are exempt, and the
  cheatsheet stays under 80.

Structure:

- Headings in sentence case, `spark` in lowercase, and the first heading
  is the file's noun.
- Numbered sections only in `docs/INSTALL.md` and `docs/ROADMAP.md`.
- Bullets start with "-" and end with a period. One level of nesting.
- A cross-reference is a `docs/` path in backticks. The only bare links
  are spark.forgewright.ai and the upstream URLs in `CREDITS.md`.
- A table of repositories may link them.

`tests/docs_test.py` holds the mechanical half of these rules: the words
that are out, the capitals, the contractions, the widths, the counts.
