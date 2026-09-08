# Changelog

## v1.15

- The failure moment: a command that exits nonzero prints one line above
  the next prompt -- `* failed (1) -- press Esc s to ask why` -- and
  `Esc s` on the empty line puts it back, already piped to `explain`;
  nothing runs until Enter. The command and its exit code ride along, so
  the answer can correct the command itself, and a command that failed
  in silence still gets an answer. A destructive head word (`rm`, `dd`,
  `mkfs`...) is seen but never offered a re-run; Ctrl-C, a no-match from
  `grep` or `diff`, spark's own refusals and a multi-line command stay
  quiet. After the fix works, `Esc s` offers to keep what happened as a
  `spark remember` fact you edit before Enter. All of it is per pane, in
  shell variables, with no model call and no fork at the prompt; `spark
  off` silences the line with everything else, and the new `failure`
  check row (39 rows now) watches the hook through the liveness
  marker's fourth field (contract 6).
- The hint above the prompt stopped cutting answers at 80 characters
  mid-word: an answer now carries up to 300 characters, cut at a word,
  and the widget trims it to the terminal's own width -- so a wide
  terminal shows the whole sentence. The ellipsis comes from the glyph
  table (`...` on the Linux console, which cannot draw the Unicode one).
- Five spark apps: spark-neovim and spark-vim join spark-micro with the
  whole prompt (one clone, one mapping: complete at the cursor, rewrite,
  ask in a pane, the ledger); spark-helix and spark-nano put `spark
  edit ` on the editor's own prompt instead -- helix and nano have no
  cursor hook, so words rewrite or ask, and nothing completes. Each in
  its own repository, proven by its own pty test; any editor's filter
  is still a client with no plugin at all (INSTALL section 6).
- The page front redesigned for onboarding: three stages (choose your
  OS with a picker, spark is live, spark apps), a light theme with a
  toggle, and a table of contents on the long pages. Every command on
  the front is a line of INSTALL.md or the README, and the page's
  palette stays in lockstep with the LAN page's -- both are tests now.

## v1.14

The docs rewritten around three lines: choose your OS, one line, spark
is live; spark apps, a tool that becomes smart as a client of `spark
edit`; another contract when apps ask for it. The shell layer keeps
working, off by default, and the docs stop presenting it as a third of
spark.

- README: install in three steps, the verbs in one table, spark apps,
  what leaves the machine. The page front is spark and spark apps.
  `tests/docs_test.py` checks the voice: two nouns in what a new user
  reads, every spark app the README names in INSTALL, the cheatsheet,
  the credits and the page.
- CLAUDE.md, AGENTS.md and CONTRIBUTING.md are framed by the same
  three lines; the shell layer is one principle, behind its gate.
- A new user is a new user: the word that held them at arm's length is
  gone from every doc, code comment and CI account name, and
  `tests/docs_test.py` refuses it.
- INSTALL.md in the new user's order, numbered and step by step (the
  machine, the one line, the verbs, the models, other machines, spark
  apps, the per-OS notes, keeping it, spark shell last). CHEATSHEET.txt
  in the same words, the shell block folded to its verbs.

## v1.13

A second Linux family: Arch. One spark, one oracle, the package names as
data.

- `distro()` beside `is_wsl()` in both twins (`lib/spark/__init__.py`,
  `bootstrap.sh`) reads `ID` then `ID_LIKE` from os-release and answers
  `debian`, `arch` or nothing; `SPARK_OS_RELEASE` pins it in tests, the
  way `SPARK_PROC_VERSION` pins WSL 2. `os_pretty` reads the same file.
- The package names live in `distro/<id>.env`, one file per family, the
  same eight keys (contract 3): the manager, its install line, the name
  the docs use, the five groups. `lib/spark/packages.py` is the one place
  python asks a package manager; bootstrap's `pkg_installed`,
  `pkg_available` and `pkg_install` are the one place sh does.
  `spark uninstall` reads the same file instead of bootstrap's source.
- The `apt` and `brew` rows are one row, `packages`, in bootstrap and in
  `spark check`.
- Arch: `get` accepts pacman and names its install line; packages come
  through `pacman -S --needed`, never `-Sy` alone (a name the database
  cannot find is a todo naming `sudo pacman -Syu`); the `pending` row
  counts `checkupdates`; `gcc-libs` is in `base`, so the AI layer asks
  for sudo only with a GPU.
- What Arch lacks refuses in one signed line: `spark font` (no
  console-setup: `/etc/vconsole.conf` is yours) and `spark quiet boot` (no
  `update-grub`); the `font` and `quiet` rows say so, never fail
  (`check.ARCH_ROWS`, a sixth selftest pass). `spark quiet login` works
  there.
- Two rows are generic now: the console palette's boot unit orders after
  `systemd-vconsole-setup.service` as well as `console-setup.service`,
  and the quiet login never creates a motd that was absent.
- CI runs the new user's one-liner in an `archlinux` container too, with
  the shell layer on top; an Arch block in INSTALL sections 1 and 7;
  the Arch package names in CREDITS.md.

## v1.12

A way out: `spark uninstall` takes spark off a machine and keeps what is yours.

- `spark uninstall` prints the plan, one row per thing, then asks for the
  word `yes`. Everything spark made goes -- units and timers, the shell
  layer's look (rc files and renders back from `.bak`), the spark line in
  your rc file, the console palette (VGA again, the boot unit removed),
  the Nerd Font and the terminfo entry, `~/.local/bin/{spark,explain,
  starship}`, the engine and every model, `~/.config/spark`,
  `~/.local/state/spark`, and the clone `get` made. Your soul, memory,
  sealed users and account keys, `models.env`, themes and `privacy-terms`
  stay unless `--purge`; the shell layer's packages are a question
  (`--packages` / `--keep-packages` answer it up front); `--dry-run` shows;
  `--yes` is a script's form. Headless and the quiet login and boot are
  undone first through their own bootstrap rows; a root step whose sudo
  refuses is a `todo` row with its command. What spark could not record
  before changing it -- a hostname, pmset, a console font set before this
  release -- is named with the line that puts it back; the console font's
  original is kept from now on (`console-setup.spark-orig`).
- Terminal.app: `theme.remove_profiles` takes the spark profiles out of
  the preferences (a default or startup setting that named one falls back
  to Basic).
- `tests/uninstall_test.sh` proves it against a real clone in a throwaway
  HOME: the plan changes nothing, a non-terminal refuses, `--yes` keeps
  exactly yours, `--purge` keeps nothing, a developer checkout is left.

## v1.11

The help in the maintainer's own order; an empty buffer is a page to
write on; the console palette paints the whole screen, and the login one.

- `spark help` reads top to bottom as spark (status, off|on, soul, memory,
  ver, chat, ask, do, edit, then a `try:` list of the prompt gestures),
  the FORGE: server/client, the machine (setup, check, update), the
  interface (shell, bar, theme, quiet, font) and "less often used"; the
  tail is the version alone (README carries what leaves the machine).
  46 lines with the shell off, 48 on. CHEATSHEET follows the same order.
- `spark edit` on an empty text: words write it from nothing (a new file
  in micro no longer answers "edit reads stdin"), the reply ending with a
  newline; `?` and Enter alone say what is missing in one infobar line.
- The console palette paints the whole screen: a framebuffer console
  colours only what is drawn after a palette change, so `spark theme`
  and `spark shell on|off` redraw after sending it. The login screen is
  drawn before any shell, so bootstrap's new `vt-palette` row installs a
  one-shot `spark-console.service` (root, `setvtrgb`, the same sudo as
  the font) that sets the kernel's defaults at boot from
  `console-colors.rgb`, for every VT; `none` writes the VGA sixteen
  instead of a reset, and the `theme` row watches the boot palette.

## v1.10

Three domains share the one command: spark, spark shell, and the smart
apps in their own repositories; Windows through WSL 2, honestly.

- spark ships no app. The micro plugin moved to its own home,
  github.com/forgewright-ai/spark-micro, and installs micro's own way: a
  clone into `~/.config/micro/plug/spark` and one `Alt-s` line. An editor
  becomes smart by being a client of `spark edit`; spark keeps the verb
  and its judge (the audition), never the plugin, the packages or the row.
  `spark update` hands back the links an older install made (the `micro`
  bootstrap row), then clone as the plugin's README says.
- `spark shell on` installs no editor: tmux, starship, fzf, zoxide, eza,
  bat, btop and the Nerd Font, and nothing else. A micro you have still
  wears the palette (its colorscheme and the seeded `settings.json`,
  rendered only when micro is on PATH); `spark shell off` keeps
  `settings.json` -- it is micro's after the seed -- and drops only the
  colorscheme key it seeded. The rc files set `EDITOR=micro` only when
  micro is there; the core hooks export nothing of micro's.
- Windows users have a way in: Ubuntu on WSL 2 is Linux to spark, minus
  what the VT console and GRUB own. `spark font` and `spark quiet boot`
  say so in one line and refuse to set; `spark headless on` refuses (the
  distro stops with its last window); the gpu, services and encryption
  rows say WSL 2; the status and the check header name it. Pinned by
  fixture (a fifth selftest pass, Linux only) -- CI has no WSL runner.
- `spark help` is sectioned by domain -- spark, at the prompt, the FORGE,
  the server, the machine, spark shell -- and half as long: 51 lines with
  the shell on, no line wider than 80. The forms still live on each verb's
  `-h`. README opens with the three ways in; INSTALL is sectioned the same
  way, with a Windows walk and per-OS notes for three tribes; CHEATSHEET
  and CREDITS follow the layers.
- The hostname row leaves the shell gate: `SITE_SET_HOSTNAME` is identity,
  not look. git and shellcheck leave the user's packages (core has git;
  shellcheck is a contributor's tool). The v1.3 stubs `bootconfig` and
  `talk` are gone; the page's two boot buttons run `spark quiet boot
  on|off`. One verb table drives dispatch and the near-miss hint. tmux's
  status line asks `spark bar` every 15 s, not 5.
- The docs' counts are tests: the category split, the roadmap's version
  and the page sources join the derived facts `tests/docs_test.py` reads.
  38 check rows.

## v1.9

A new user's first run: three questions, and a machine that looks untouched
until it is asked to change.

- `spark setup` asks three things, not four. The palette is no longer a
  question: spark ships wearing `gruvbox-dark`, and `spark theme NAME` or
  `spark theme none` changes it whenever you like. Asking a first-timer to
  pick colours for tmux and starship -- the shell layer, which setup leaves
  off -- spent a question on nothing. `--theme` and `SITE_THEME`
  pre-answer it.
- A first run now leaves the machine looking exactly as it did. setup wrote
  the palette's runtime files whatever `SITE_SHELL` said, and the rc hook
  is core: it cats `console-colors` on a `TERM=linux` console, so a fresh
  install with the shell layer off repainted the VT at the next login.
  `SITE_THEME` is still recorded; the files, and the macOS Terminal
  profile, land with `spark shell on` or an explicit `spark theme NAME`.
- A palette reaches the console it is typed on. `spark theme` wrote
  `console-colors` and left it for the next login, so a theme arrived late
  and turning one off looked stuck until a logout and a `clear`. One helper
  sends that file to a running Linux VT, and `spark theme`, `spark shell
  on` and `spark shell off` all use it. An emulator is never repainted.
- `spark theme` no longer asks for a shell restart it never needed:
  starship re-reads its config on every prompt, the widget draws no colour
  of its own, and the hook reads `console-colors` alone. Only a running
  micro must be reopened.
- `spark shell off` hands the terminal back: the palette goes with the
  layer that brought it, a running console is reset at once, and it prints
  the `open a new shell (exec $SHELL)` line that `spark shell on` always
  printed. `SITE_THEME` stays, so `spark shell on` paints it again. The
  `theme` check row reads `na`, not `fail`, for a palette nothing has
  painted yet.
- `spark font list` on Linux names the Nerd Font. The console takes `.psf`
  faces from `/usr/share/consolefonts`; the JetBrainsMono Nerd Font that
  `spark shell on` unzips into `~/.local/share/fonts` is a `.ttf` for a
  terminal emulator and can never appear in that list, so it is named
  under it with where to set it.
- The setup table says it is not the whole list. Only rows proven on the
  line and under an open license are offered -- today the five qwen3 rows
  -- so the first run read as though spark served nothing else. One line
  counts the other 21 and points at `spark model list`.
- INSTALL.md opens with two numbered walkthroughs instead of prose: a
  machine from zero (the Debian image, the empty root password that earns
  you `sudo`, the packages) and spark on a machine you have (one check for
  `sudo`, `git`, `curl` and `python3`, then the one-liner). The runbook
  follows.
- The page really does rebuild on a release. `release.yml` creates the
  Release with the job's own `GITHUB_TOKEN`, and GitHub raises no event for
  what that token does, so v1.8's `release: published` trigger never fired
  and the page went on naming v1.7. `pages.yml` waits for the release
  workflow to finish instead, and publishes only when it succeeded.

## v1.8

A rendered file stops moving with the network; the page stands on its own.

- `SITE_NAME` and a guessed `SITE_GIT_EMAIL` take `scutil --get
  LocalHostName` on macOS instead of `hostname`: with `HostName` unset the
  kernel name follows whatever the network last said, so `~/.gitconfig` and
  `~/.tmux.conf` drifted from their templates on their own, the `configs`
  row failed, and `install.sh` would have rewritten the author line of
  every later commit. Linux is unchanged.
- `./bootstrap.sh` names a guessed git identity in its `identity` row
  whether the key is absent or still the example's placeholder: a guess
  signs every commit, so it is said out loud.
- A client's `ember` row reads `na` beside its other AI rows -- a client
  keeps no second model of its own, and `spark ember NAME` there is
  refused. `spark ember list` shows what the peer offers.
- The page rebuilds when a release is published, and its sign line links
  that release: the page and the GitHub release never disagree.
- The page loads no font from Google -- the local stack draws it, and a
  browser no longer waits on fonts.googleapis.com to render it.

## v1.7

The editor grows up; the shell learns your palettes; a client stays a client.

- `spark serve` passes `--cache-ram 0`: llama-server no longer keeps
  replaced prompts in host RAM (a 12B model on a 16 GB box had climbed
  from 32 % to 90 % in a day). `SPARK_EXTRA_ARGS=--cache-ram N` sets a
  budget in MiB; the `serve` row reports it.
- `spark edit ?` checks every quote against the text: a span the text
  does not hold is followed by `[not in the text]`. `--sel A B` answers
  about a selection in the light of the file around it; `--thread ID`
  keeps an exchange going, sealed like a chat thread; `--decline --name
  NAME` retires a note so the next `?` does not raise it, until the words
  it quoted leave the file.
- The micro plugin (1.3.0): a Lua error is an infobar line, never a dead
  editor; an answer over text that moved opens in a pane instead of being
  spliced. The pane has keys -- `q` closes, Enter jumps to the quote, `a`
  applies a code block, `d` declines a note -- and `?? words` goes on in
  it. `ledger` and `ledger clear` at the `spark>` prompt list or drop the
  file's declined notes; the shell verb `spark ledger` is gone.
- A client stays a client: `spark model`, `ember list` and `model budget`
  on a client print the peer's table (`GET /api/models`), and the verbs
  that would make it a server are refused with one line; `spark client
  off` remains the way back.
- Your own palettes: a `~/.config/spark/themes/<name>.env` with the 21
  `THEME_*` keys is listed, chosen, completed and checked like the six in
  the repository, and wins on a name clash. `THEME_LOGO`, optional, paints
  the banner's six rows in a palette's colours.
- `spark theme NAME` reaches everything at once: the open Terminal.app
  windows on macOS (profile, font and cursor), micro's `colorscheme` when
  micro had changed it, and tmux when it runs.
- `spark font` on macOS refuses a face the Mac does not have and lists
  the monospace faces installed; the default is the Nerd Font at 13, one
  face and size for every profile. On Linux the list spells sizes the way
  the command takes them, width by height.
- `spark quiet audio on|off` silences every sound spark makes; the
  `audio` row names the player it would use. 39 check rows.
- `tests/docs_test.py` keeps the docs true (credits, counts, pages); the
  page shows a section above the newest tag as `vX.Y (unreleased)`;
  `tests/audition.py` scores the editor's briefs against a live brain,
  outside the gate.

## v1.6

One model list. The three lists (curated, embers, community) are one
`models.env`, 26 rows, tested or not, any license named.

- `models.env`: every row carries `MODEL_<NAME>_LICENSE`; `_TESTED=line`
  marks a row proven on the line; `_NOTE` is one optional line.
  `embers.env` and `community.env` are gone; `~/.config/spark/models.env`
  is still yours.
- `auto` picks only among tested rows under Apache-2.0 or MIT; any row is
  yours by name; a row under another license prints it and asks first.
- New rows: Qwen3-Coder-30B-A3B, Qwen2.5 7B/14B, Mistral 7B v0.3, Mistral
  Nemo 12B, Phi-4 mini and 14B, DeepSeek-R1 distills 7B/14B, SmolLM2
  1.7B, gpt-oss-20b, Granite 3.3 8B, Llama 3.2 1B/3B, Llama 3.1 8B,
  Gemma 3 1B/4B/27B. Untested until someone posts the line proof.
- `spark model list` and `spark ember list` print the same table: license,
  `line`, a note under its row, `u` for yours. No more `? e` marks.
- `spark model add URL` works on huggingface.co again: the size and
  sha256 live on the redirect, not on the CDN it points at.
- The page's models page is one table. `CHANGELOG.md` and `ROADMAP.md`
  are lists now, not essays; every doc drops the list words.

## v1.5

The editor wave: micro is the first smart tool.

- Two arcs: OS -> spark -> smart shell and chat; tools -> spark -> smart
  tools.
- `spark edit` (contract 10): text on stdin, raw text out; `--at N`
  completes, `<words>` rewrites (12 kB cap), `? [words]` asks or reviews;
  hints `--type --name --about --part`. Works from a pipe.
- Before a `?`, a 20-token reading (language, kind) is restated to the
  model, so a Portuguese draft is answered in Portuguese.
- micro plugin `home/.config/micro/plug/spark/`: `Alt-s` opens `spark> `;
  the new text is left selected -- Backspace discards, Ctrl-z undoes.
  `setlocal spark.about "..."` says what the text is; `set spark false`
  switches it off. No key is bound from inside (micro would detach the
  link).
- `Esc a` became `Esc s` at the prompt: one gesture, shell and editor.
- Check row `editor` (CAPABILITY, shell layer); 38 rows.
- `tests/micro_pty.py` drives a real micro against a stub spark.
- `Session(role=)`, `ask_stream/ask_json(max_tokens=, timeout=)`,
  `forge.clip`, `text.Fence`.

## v1.4

The multi-user wave. Break: the shared ember-token is gone.

- `spark user add|login|logout|remove|token --new|claim`: named users,
  each with a personal token shown once and never stored.
- Threads, memory and chat history sealed per user (ChaCha20-Poly1305
  from RFC 8439, pinned to its vectors) under a key only that token
  opens; the box keeps a hash and a wrapped key. No reset.
- The FORGE is multi-user: forge-token = admin (the box account's store);
  every other caller is a user; `GET /api/users` shows names and counts,
  never a word. Browser logins live in memory (a restart asks again).
- `[cwd]` rides only the modes that propose a command (line, do,
  explain); a conversation sends no path.
- Turns are numbers: one choke point strips every free-text field.
- Check row `users`: 0700 dirs, 0600 keys, sealed magic; nags until the
  old ember-token and plaintext files are gone.
- `.githooks/commit-msg`: the privacy patterns over the message too.

## v1.3

The CLI experience wave: one grammar, a machine that explains itself.

- The grammar (CLAUDE.md): bare = show; `on|off` the only switch words;
  `status` = bare, `list` = the table; `-h` first, signed; one confirm
  shape, one spinner, one exit-code law (0, 1, 2, 78, 130).
- `spark quiet start|login|boot on|off` replaces `spark bootconfig`;
  `boot on` is a genuinely silent boot (one GRUB drop-in).
- Long output pages through `$PAGER`, plain when piped. `spark help`
  rewritten.
- Chat: `/resume [N]`, `/clear`, `spark chat --thread N [words]`.
- The line and chat prompts know spark's own verbs (`?? how do I change
  the theme` names `spark theme`).
- TAB completion for verbs and their names, bash and zsh, offline; check
  row `completion`.
- `spark setup` asks the theme; the palette lands on console, micro and
  tmux at once; check row `theme`; nord and tokyonight-night join.
- `spark shell off` restores the rendered look from `.bak`; `spark font`
  leaves the shell gate; `spark font list`.
- Fixes: did-you-mean at exit 2; `spark update` execs the fresh
  `bin/spark`; a restore never leaves an empty `~/.bash_profile`
  (`rc-login` row); plain-text replies, no markdown. 36 rows.

## v1.2

The page wears the brand.

- The FORGE page: the ember palette by default, dark and light, all
  mono; marks `* > !` on transcript rows; a blinking caret; copy buttons;
  a stop button; keys `n j k`.
- The config page's ember picker runs `spark ember` on the box; the
  headless switch is gone (it needs sudo).
- `/manifest.webmanifest` and a drawn `/apple-touch-icon.png`: an app on
  an iPhone's home screen (Android opens a tab over LAN http).
- The same page runs inside sparkapp (macOS and Windows): the login card
  asks the address too; `q` quits.

## v1.1

- The `peer` row understands a FORGE (`/api/health`), reporting
  `forge <host> ok` or `up, its model loading|down`.
- `spark check` over plain ssh finds `~/.local/bin` and Homebrew's bin.
- The client shape: `spark client URL|off`; bootstrap skips the engine
  and the units, `install.sh` links no unit, the rows in `CLIENT_ROWS`
  read `na`; a fourth `--selftest` pass proves it.

## v1.0

The ignition: one line, and a fresh Debian 13 or macOS has a private
local AI at its prompt. spark is public, MIT.

- `get`: clone or pull `~/.spark`, refuse what is not spark, never sudo,
  hand over to `spark setup` (name, user, model; `--yes`, `--model`,
  `--name`, `--user`; stdin not a tty takes every default).
- Two layers: `SITE_SHELL=off` (the AI only, one rc line appended) and
  `spark shell on` (tmux, starship, micro, fzf, ...); shell rows `na`
  when off, a third `--selftest` pass proves it.
- One model by default: `SITE_EMBER_MODEL=none`; the engine is the
  pinned llama.cpp tarball on both OSes (six flavours, check row
  `engine`); the table gains a speed column.
- `SITE_AI_BUILD=auto`: vulkan when a GPU reports its memory, else cpu;
  `auto` picks the largest model under the budget AND the build's speed
  cap (3 GB files on cpu, 6 on vulkan, 20 on metal); units warm the
  model after `/health`; launchd rows skip without a gui domain.
- Privacy words leave the tree (`~/.config/spark/privacy-terms`,
  `SPARK_PRIVACY_TERMS`); the tag is the release (`spark ver` from git,
  `spark update`, `release.yml`); CI grows a Debian 13 container job.
- Three model lists plus yours (folded back into one in v1.6);
  `spark model add URL [--sha256] --license`, `spark model verify`
  (check row `models`), `spark model budget N` (`SITE_AI_BUDGET`).
- `spark chat` v2: wrapped replies, readline history, Ctrl-C stops a
  reply, `/help /new /last /model /q`.
- `CREDITS.md` names every project spark downloads or installs.
- Measured: a fresh Debian account over ssh reached its first answer in
  10 min 19 s (a 4.7 GB download, 8.4 tok/s on vulkan); a fresh M4 Mac
  in 16 min 25 s (13.0 tok/s on Metal).

## v0.4

The ember: one llama-server serves two models.

- `SITE_EMBER_MODEL auto|none|name`; `spark serve` runs llama-server as a
  router (`--models-dir`, a rendered `presets.ini`); the spark role at
  context 4096 with reasoning off; the request's `model` field routes.
- The rule: the prompt line is spark, every sentence is an ember; the
  identity rides only with the ember.
- `spark ember [NAME|auto|none|list]`; check row `ember`; `/api/health`
  gains `models` and `roles`; 31 rows.
- Two tokens on the FORGE (admin and user), two faces on the page;
  `spark forge token --new [--user]`.
- `spark chat` is the conversation verb (`spark talk` dispatches for one
  version); a generous quit grammar; one mark pair `* !` on both OSes.
- A head-word guard: a command whose first word is not installed here is
  re-asked once; `spark do` never offers it.
- `spark do`: a done summary whose numbers no output backs is marked
  unchecked; each turn records the model that answered.
- Linux: the serving user joins the `render` group (GPU without a seat);
  the zsh widget empties the line before it speaks; downloads and
  restarts narrate both ends.

## v0.3

The FORGE: spark is the seed, the FORGE is the agent it builds and keeps.

- `spark forge` (`lib/spark/forgeserve.py`): a stdlib HTTP server in
  front of llama-server, one LAN address, a 0600 forge-token, cookie or
  bearer; `/v1/chat/completions`, `/v1/models`, `/api/*`, the page.
- `~/.config/spark/soul` (`spark soul [edit|reset]`) and `memory`
  (`spark remember|forget|memory`); check rows `soul`, `memory`.
- Threads: `? words` starts one, `?? words` continues the newest; `spark
  talk`, `spark @FILE words`, `spark do <words>` (one confirmed command
  at a time, `yes` for a destructive step).
- `spark headless on|off`: linger, sleep masked, lid ignored (Linux);
  LaunchDaemons and `pmset` (macOS); check row `headless`. 30 rows.

## v0.2

- Every turn records the server's timings; `spark last`, `spark status`,
  `spark stats` (percentiles, cache hits, GPU).
- `spark bench [--tune]`, `spark tune apply` (`SPARK_FLASH_ATTN`,
  `SPARK_KV`, `SPARK_THREADS`, `SPARK_NGL`).
- Check rows `throughput` and `gpu`; `spark model` lists and switches.

## v0.1

- One command, `spark`: `? words`, `words?`, `Esc a`, `explain`; `spark
  serve|stop` with a systemd unit and a launchd agent; `spark check` with
  a fixture selftest; `spark bar`; `spark theme`.
- One `bootstrap.sh`, one `install.sh`, Debian-family Linux and macOS;
  four palettes; five pinned models chosen by RAM; a privacy gate on
  every commit. Python 3.9+ stdlib and POSIX sh only.
- After the first Debian 13 box: `libgomp1`; ASCII on the console; `spark
  theme NAME|list`; `spark ver`; `spark font`; `spark bootconfig`.
