# spark

<img src="assets/banner.svg" alt="spark" width="400">

AI on the edge, at no cost. spark turns a Linux or macOS machine you own
into a private AI: no account, no cloud, nothing leaves. `spark chat` is
the front door. The prompt line is the surprise: ask, press Enter, and the
command is in your line.

Try it at the prompt:

```
~ > files bigger than 1G modified this week?          <- type it, press Enter
* Finds files >1G modified in last 7 days               <- the hint, above the prompt
~ > find . -type f -size +1G -mtime -7                  <- the command, in your line
```

Nothing runs until you press Enter again. A command that deletes comes back
marked `!` -- one mark, every OS, every terminal.

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

`spark setup` asks four things -- this machine's name, yours, the model,
the theme -- does the rest, and asks the first question for you. A Debian
box with 16 GB between RAM and GPU:

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
model [qwen3-8b]:
theme [gruvbox-dark]:

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
spark shell on adds spark's own shell: tmux, starship, micro, fzf ...
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
  command lands in your line with a hint above it. `Esc a` asks about the
  line you are on. `cmd 2>&1 | explain` says what went wrong. `spark off`
  gives Enter back.
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
  `spark ember NAME` adds a second brain -- a bigger, conversational
  model; spark stays small at the prompt. `spark ember list` shows the
  ones with a purpose. Every model is verified on download and by `spark
  model verify`; add your own with `spark model add URL`.
- **`spark check`.** Every promise this machine makes, one row each; exit 0
  when all are kept. `./bootstrap.sh --dry-run` says what a rebuild would
  change and never asks for sudo.
- **`spark shell on`.** Off by default. On: tmux, starship, micro, fzf, eza,
  bat, btop, the Nerd Font, and the rc files become spark's (yours move to
  `.bak`). With a theme chosen, one palette lands on every surface at once:
  the text console, tmux and micro share the same look, and `spark theme
  NAME` switches all of them. `off` hands everything back -- rc files and
  the rendered look alike, each from its `.bak` or removed. Off, your
  shell stays yours.
- **`spark quiet`.** What stays silent, three switches: `spark quiet start
  on` silences spark itself -- no login banner, `spark serve` and bare
  `spark` answer with one line (`spark status` stays full); on Linux,
  `spark quiet login|boot on` empties the motd and makes the boot itself
  silent: GRUB's menu hidden, the kernel line quiet, systemd showing
  errors only (one removable drop-in; hold Shift at boot for the menu).

## What leaves this machine

Exactly this, and only to the FORGE or llama-server you configured: the
line you typed; the directory's path, not its contents; the shell and OS
name; with a conversation, your soul, your remembered facts and the
thread's earlier turns; for `explain`, the piped text (last 6 kB); for
`@FILE`, its first 4 kB and last 12 kB, under the name you typed; for
`spark do`, each step's output (last 4 kB). No telemetry, no analytics, no
crash reports, no account. The one-liner fetches two things: `get` from
raw.githubusercontent.com and the clone from github.com; bootstrap fetches
the engine (one pinned llama.cpp release, sha256) from github.com and the
model you chose from huggingface.co (size and sha256 in `models.env`).
Nothing else. The server and the FORGE bind one LAN address, never
`0.0.0.0`, behind 0600 tokens that are never printed; turns and threads
live 30 days under `~/.local/state/spark/` (0600), `SPARK_HISTORY=off`
keeps none.

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
| models | `models.env` (curated), `embers.env`, `community.env` | file size + sha256; `spark model list` / `spark ember list` |

## License

MIT. See `LICENSE`. Everything spark downloads or installs is named in
`CREDITS.md` with its license.

Built with Claude -- see `CREDITS.md`.
