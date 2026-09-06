# spark

<img src="assets/banner.svg" alt="spark" width="400">

AI on the edge, at no cost. spark turns a Linux or macOS machine you own
into a private AI: no account, no cloud, nothing leaves. `spark chat` is
the front door. The prompt line is the surprise: ask, press Enter, and the
command is in your line. Two arcs, the same local AI in the middle of
each: OS -> spark -> a smart shell and chat (the foundation); tools ->
spark -> smart tools (the productivity), starting with micro.

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

One line, either OS (Debian 13 / Ubuntu 24.04 or newer; macOS with the
command line tools). No sudo, except once for `apt` on Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/forgewright-ai/spark/main/get | sh
```

By hand, the same two steps:

```sh
git clone https://github.com/forgewright-ai/spark.git ~/.spark && ~/.spark/bin/spark setup
```

Read it first: `curl -fsSLO https://raw.githubusercontent.com/forgewright-ai/spark/main/get; sh get`.

`spark setup` asks three things -- this machine's name, yours, the model
-- does the rest, and asks the first question for you. The palette is not
one of them: spark ships wearing gruvbox-dark, and `spark theme NAME` or
`spark theme none` changes it whenever you like. A Debian box with 16 GB
between RAM and GPU:

```
spark 1.3
by forgewright-ai . github.com/forgewright-ai/spark

this machine's name [mini]:
your name [ana]:

16 GB for models (RAM + GPU), budget 9 GB (60%), vulkan
     qwen3-1-7b    1.0 GB file 3 GB RAM fits ~35 tok/s
     qwen3-4b      2.3 GB file 5 GB RAM fits ~16 tok/s
  *  qwen3-8b      4.7 GB file 7 GB RAM fits ~9 tok/s
     qwen3-14b     8.4 GB file 11 GB RAM too big
     qwen3-30b-a3b 17.4 GB file 21 GB RAM too big
     21 more: spark model list (unproven, or a license that asks)
model [qwen3-8b]:

ok     site         SITE_NAME=mini SITE_USER=ana SITE_AI_MODEL=qwen3-8b SITE_THEME=gruvbox-dark
ok     engine       llama.cpp b10689 ubuntu-vulkan-x64
ok     download     Qwen_Qwen3-8B-Q4_K_M.gguf (4.7 GB) -- curl's progress bar follows
ok     model        qwen3-8b: Qwen_Qwen3-8B-Q4_K_M.gguf
...                 (token, dirs, configs, tools, hooks, units)
ok     rc           ~/.bashrc sources the hook
ok     theme        gruvbox-dark -> ~/.config/spark/theme.env (+ console-colors)
ok     server       loading the model ... ready

? how big is this dir
* Show disk usage of current directory
  du -sh .

8.5 tok/s on your first question (spark bench for the full number)

open a new shell (exec $SHELL), then:
  spark chat                      a conversation
  ? how big is this dir           a command in your line, a hint above it
  cmd 2>&1 | explain              what went wrong, and the fix
spark shell on adds spark's own shell: tmux, starship, micro (Alt-s: spark
                                inside the editor), fzf ...
```

`INSTALL.md` is the runbook; the percent is `SITE_AI_BUDGET` (`spark model
budget N`). Long output -- the help, the check report, the tables -- pages
through `$PAGER` (`less` when unset) at a terminal, and stays plain when
piped. TAB completes the verbs and their names -- themes and models
included -- in bash and zsh, offline.

Contributing: `CONTRIBUTING.md`; the short brief for agents: `AGENTS.md`.
What comes next: `ROADMAP.md`.

## What you get

- **The AI.** `spark chat` is a conversation (`/help` lists its verbs:
  `/resume` picks up an older thread, `/clear` wipes the screen), and
  `spark chat --thread N [words]` continues an older thread straight from
  the command line. `spark <words>` streams a one-off answer, `spark do
  <words>` runs a task one confirmed command at a time, `spark @FILE
  words` reads a file, `?? words` follows up on the last answer. The
  machine can explain itself: ask it how to change or run spark and it
  answers with spark's own commands (`?? how do I change the theme`
  names `spark theme`).
- **The prompt line, the surprise.** `? words` or `words?`, Enter, and the
  command lands in your line with a hint above it. `Esc s` asks about the
  line you are on. `cmd 2>&1 | explain` says what went wrong. `spark off`
  gives Enter back.
- **In the editor.** With the shell layer on, micro has spark under one
  key: `Alt-s` (Option-s on a Mac) opens `spark> `. Enter alone completes at the cursor;
  words rewrite the selection, or the whole file when nothing is
  selected (`shorter`, `fix grammar`, `add a docstring`); `? words` asks
  in a pane; `?` alone reviews; `??` goes on. In the pane, Enter jumps to
  a quote (every quote is checked against your text), `a` applies a code
  block, `d` declines a note for good, `q` closes. spark reads
  what the text is -- code or prose, a poem or a chapter or a README --
  and answers as that kind of text deserves, in its own language; the
  new text is left selected, a proposal you keep or discard. The same
  verb works from a pipe: `spark edit fix grammar < draft.md`.
- **The FORGE.** `spark forge` serves the same agent on the LAN: an
  OpenAI-shaped API for any program, and a client page in the browser
  that wears spark's own ember look by default (`spark theme` recolours
  it). On an iPhone, share -> add to home screen makes the page an app:
  its own icon, full screen (Android keeps the icon but opens a browser
  tab -- `INSTALL.md` says why). `spark headless on` keeps it up from boot
  on the machine that stays on. `spark client URL` makes another machine
  of yours a client of it: the same prompt, chat and explain there, no
  model of its own.
- **Yours.** spark ships with a default soul; `spark soul edit` writes your
  own. `spark remember` adds a fact it keeps. Both live under
  `~/.config/spark/`, 0600, read by the model and never written by it.
  `spark ember NAME` adds a second, bigger model for conversations;
  spark stays small at the prompt. `spark model list` is the one table:
  26 models, each with its license, the tested ones marked. Every model
  is verified on download and by `spark model verify`; add your own with
  `spark model add URL`.
- **`spark check`.** Every promise this machine makes, one row each; exit 0
  when all are kept. `./bootstrap.sh --dry-run` says what a rebuild would
  change and never asks for sudo.
- **`spark shell on`.** Off by default. On: tmux, starship, micro (with
  spark inside it), fzf, eza, bat, btop, the Nerd Font, and the rc files
  become spark's (yours move to `.bak`). With a theme chosen, one palette lands on every surface at once:
  the text console, tmux and micro share the same look, and `spark theme
  NAME` switches all of them. A palette of your own is one file in
  `~/.config/spark/themes/`, listed and chosen like the built-in six.
  `off` hands everything back -- rc files and
  the rendered look alike, each from its `.bak` or removed. Off, your
  shell stays yours.
- **`spark quiet`.** What stays silent, three switches: `spark quiet start
  on` silences spark itself -- no login banner, `spark serve` and bare
  `spark` answer with one line (`spark status` stays full); on Linux,
  `spark quiet login on` bares the login (no distro notice, no kernel
  line, an empty pre-login banner) and `spark quiet boot on` makes the
  boot itself silent -- BIOS splash, then the login prompt, nothing
  between (one removable GRUB drop-in; hold Shift at boot for the menu).

## What leaves this machine

Exactly this, and only to the FORGE or llama-server you configured: the
line you typed; the shell and OS name; the directory's path -- never its
contents, and only where a command is proposed (the prompt line, `do`,
`explain`): a conversation sends no path at all; with a conversation,
your soul, your remembered facts and the
thread's earlier turns; for `explain`, the piped text (last 6 kB); for
`@FILE`, its first 4 kB and last 12 kB, under the name you typed; for
`spark do`, each step's output (last 4 kB); from the editor (`spark
edit`), the file's name and its text -- 6 kB around the cursor for a
completion, 12 kB for a rewrite, 16 kB for a question -- never its path,
and no thread is kept unless the editor asks for one (`--thread`), which
is then sealed like a chat thread; a note you decline is kept, sealed, by
the file's name (`ledger` at micro's `spark>` prompt). No telemetry, no analytics, no
crash reports, no account. The one-liner fetches two things: `get` from
raw.githubusercontent.com and the clone from github.com; bootstrap fetches
the engine (one pinned llama.cpp release, sha256) from github.com and the
model you chose from huggingface.co (size and sha256 in `models.env`).
Nothing else. The server and the FORGE bind one LAN address, never
`0.0.0.0`, behind 0600 tokens that are never printed; turns and threads
live 30 days under `~/.local/state/spark/` and `SPARK_HISTORY=off`
keeps none; turns are telemetry -- numbers, never words, the said things
live only in the sealed threads. Named users (`spark user add NAME`) each get their own sealed
store: threads, memory and chat history encrypted (ChaCha20-Poly1305,
written from RFC 8439) under a key only that user's token opens. The box
keeps a hash and a wrapped key, never the token -- the admin cannot read
your messages, a stolen disk is ciphertext, and a lost token is lost
history, by design. There is no reset.

## How fast

`spark bench` measures this machine with llama-bench and keeps the
baseline; `spark stats` sums up what real turns measured; the model table
shows `~N tok/s` until a model is measured here, then the `~` goes.

## Pinned

Every version below, and its license, is in `CREDITS.md`.

| what | where | pinned by |
|---|---|---|
| llama.cpp | `bootstrap.sh` (both OSes) | version + sha256 |
| starship, JetBrainsMono Nerd Font | `bootstrap.sh` (Linux) | version + sha256 |
| the same | `Brewfile` (macOS) | Homebrew -- no pinning worth trusting |
| models | `models.env` | file size + sha256; `spark model list` |

## License

MIT. See `LICENSE`. Everything spark downloads or installs is named in
`CREDITS.md` with its license.

Built with Claude -- see `CREDITS.md`.
