# spark

<img src="assets/banner.svg" alt="spark" width="400">

AI on the edge, at no cost. spark turns a Linux, macOS or Windows (WSL 2)
machine you own into a private AI: no account, no cloud, nothing leaves.
OS + spark = a smart OS: `spark chat` is the front door, and the prompt
line is the surprise -- ask, press Enter, and the command is in your line.
Two things sit beside it, each optional: `spark shell on`, spark's own
shell for the machine that is an AI box; and the smart apps, tools that
are clients of spark -- micro first.

Try it at the prompt:

```
~ > files bigger than 1G modified this week?          <- type it, press Enter
* Finds files >1G modified in last 7 days               <- the hint, above the prompt
~ > find . -type f -size +1G -mtime -7                  <- the command, in your line
```

Nothing runs until you press Enter again. A command that deletes comes back
marked `!` -- one mark, every OS, every terminal.

The page: https://spark.forgewright.ai -- the docs, the model list.

## Quickstart

Debian 13 / Ubuntu 24.04 or newer (Ubuntu on WSL 2 too), or macOS with the
command line tools. Step 0 on a bare Linux, once:

```sh
sudo apt-get update && sudo apt-get install -y git curl python3
```

Then one line, either OS. No sudo, except once for `apt` on Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/forgewright-ai/spark/main/get | sh
```

By hand, the same two steps:

```sh
git clone https://github.com/forgewright-ai/spark.git ~/.spark && ~/.spark/bin/spark setup
```

Read it first: `curl -fsSLO https://raw.githubusercontent.com/forgewright-ai/spark/main/get; sh get`
(`wget -qO- URL | sh` works too). About ten minutes, most of it one 4.7 GB
download.

`spark setup` asks three things -- this machine's name, yours, the model
-- does the rest, and asks the first question for you. A Debian box with
16 GB between RAM and GPU:

```
this machine's name [mini]:
your name [ana]:

16 GB for models (RAM + GPU), budget 9 GB (60%), vulkan
     qwen3-4b      2.3 GB file 5 GB RAM fits ~16 tok/s
  *  qwen3-8b      4.7 GB file 7 GB RAM fits ~9 tok/s
     qwen3-14b     8.4 GB file 11 GB RAM too big
     21 more: spark model list (unproven, or a license that asks)
model [qwen3-8b]:
...
? how big is this dir
* Show disk usage of current directory
  du -sh .

8.5 tok/s on your first question (spark bench for the full number)
```

`INSTALL.md` is the runbook. A first run adds one line to your rc file and
nothing else: your shell, your colours and your editor stay yours.

## Three ways in

| you want | one command | what lands |
|---|---|---|
| a local AI, nothing else touched | the one-liner above | the engine, a model, `spark chat`, the `?` prompt line, the FORGE on the LAN |
| an AI box to run and keep: a Linux box, a mac mini, an old laptop | `spark shell on` | tmux, starship, fzf, eza, bat, btop, zoxide, the Nerd Font, one palette on every surface, the status bar, a quiet login and boot |
| a workstation, spark inside the tools you use | the app's own install | micro first: `git clone https://github.com/forgewright-ai/spark-micro ~/.config/micro/plug/spark`, one Alt-s line; the shell layer is optional |

## What you get

### spark

- **The AI.** `spark chat` is a conversation (`/help` lists its verbs;
  `/resume` picks up an older thread), `spark <words>` streams a one-off
  answer, `spark do <words>` runs a task one confirmed command at a time,
  `spark @FILE words` reads a file, `?? words` follows up. Ask it how to
  change spark and it answers with spark's own verbs.
- **The prompt line.** `? words` or `words?`, Enter, and the command lands
  in your line with a hint above it. `Esc s` asks about the line you are
  on. `cmd 2>&1 | explain` says what went wrong. `spark off` gives Enter
  back. TAB completes the verbs and their names, offline.
- **The FORGE.** `spark forge` serves the same agent on the LAN: an
  OpenAI-shaped API for any program, and a client page in the browser (on
  a phone, add it to the home screen). `spark headless on` keeps it up from
  boot on the machine that stays on; `spark client URL` makes another
  machine of yours a client of it, no model of its own.
- **Yours.** A default soul; `spark soul edit` writes your own. `spark
  remember` adds a fact it keeps. `spark ember NAME` adds a second, bigger
  model for conversations. `spark model list` is the one table: 26 models,
  each with its license, the tested ones marked; every download is
  verified; `spark model add URL` adds your own.
- **`spark check`.** Every promise this machine makes, one row each; exit 0
  when all are kept. `./bootstrap.sh --dry-run` says what a rebuild would
  change and never asks for sudo.

### spark shell

- **`spark shell on`.** Off by default. On: tmux, starship, fzf, eza, bat,
  btop, zoxide, the Nerd Font, and the rc files become spark's (yours move
  to `.bak`). With a theme chosen, one palette lands on every surface at
  once -- the text console, tmux, starship, and a micro you have -- and
  `spark theme NAME` switches all of them; a palette of your own is one
  file in `~/.config/spark/themes/`. `off` hands everything back, each
  file from its `.bak` or removed. No editor is installed either way.
- **`spark quiet`.** What stays silent: `start` (spark's own banner and
  narration), and on Linux `login` (the motd) and `boot` (BIOS splash to
  login prompt, one removable GRUB drop-in). `audio` mutes spark's sounds.

### smart apps

- **spark in micro.** A tool becomes smart by being a client of one verb,
  `spark edit`: text on stdin, raw text out, never a path. micro is first:
  [spark-micro](https://github.com/forgewright-ai/spark-micro) puts
  `spark> ` under `Alt-s` (Option-s on a Mac) -- Enter completes at the
  cursor, words rewrite the selection or the file, `?` asks in a pane where
  every quote is checked against your text; `a` applies a code block, `d`
  declines a note for good. It installs the editor's own way (a clone and
  one binding line); spark ships no app. The same verb works from a pipe:
  `spark edit fix grammar < draft.md`. Another editor joins the same way.

## What leaves this machine

Exactly this, and only to the FORGE or llama-server you configured: the
line you typed; the shell and OS name; the directory's path -- never its
contents, and only where a command is proposed (the prompt line, `do`,
`explain`): a conversation sends no path at all; with a conversation,
your soul, your remembered facts and the thread's earlier turns; for
`explain`, the piped text (last 6 kB); for `@FILE`, its first 4 kB and
last 12 kB, under the name you typed; for `spark do`, each step's output
(last 4 kB); from an editor (`spark edit`), the file's name and its text
-- 6 kB around the cursor for a completion, 12 kB for a rewrite, 16 kB
for a question -- never its path, and no thread is kept unless the editor
asks for one, which is then sealed like a chat thread. No telemetry, no
analytics, no crash reports, no account. The one-liner fetches `get` from
raw.githubusercontent.com and the clone from github.com; bootstrap fetches
the engine (one pinned llama.cpp release, sha256) from github.com and the
model you chose from huggingface.co (size and sha256 in `models.env`).
Nothing else. The server and the FORGE bind one LAN address, never
`0.0.0.0`, behind 0600 tokens that are never printed; turns and threads
live 30 days under `~/.local/state/spark/` (`SPARK_HISTORY=off` keeps
none); turns are numbers, never words. Named users (`spark user add NAME`)
each get their own sealed store, encrypted (ChaCha20-Poly1305, written
from RFC 8439) under a key only that user's token opens: the admin cannot
read your messages, a stolen disk is ciphertext, and a lost token is lost
history, by design. There is no reset.

## How fast

`spark bench` measures this machine with llama-bench and keeps the
baseline; `spark stats` sums up what real turns measured; the model table
shows `~N tok/s` until a model is measured here, then the `~` goes.

## Pinned

Every version below, and its license, is in `CREDITS.md`.

| what | layer | where | pinned by |
|---|---|---|---|
| llama.cpp | spark | `bootstrap.sh` (both OSes) | version + sha256 |
| models | spark | `models.env` | file size + sha256; `spark model list` |
| starship, JetBrainsMono Nerd Font | spark shell | `bootstrap.sh` (Linux) | version + sha256 |
| the same | spark shell | `Brewfile` (macOS) | Homebrew -- no pinning worth trusting |

## License

MIT. See `LICENSE`. Everything spark downloads or installs is named in
`CREDITS.md` with its license.

Built with Claude -- see `CREDITS.md`.
