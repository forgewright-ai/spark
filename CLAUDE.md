# spark -- maintainer's reference

AGENTS.md is the short form for agents and contributors; this file is
the full reference.

spark is a local AI at the shell prompt that never leaves your LAN, on a
fresh Debian-family or Arch Linux, macOS, or Ubuntu on WSL 2. Three lines
are its spine: choose your OS, one line, spark is live; spark apps -- a
tool becomes smart as a client of `spark edit` (contract 10), each in its
own `spark-<app>` repository; and, as apps ask for it, another contract
is defined and apps connect to it the same way. Inside, the FORGE is the
agent spark builds and keeps on the box -- the model plus one soul, one
memory and threads, served on the LAN by `spark forge` -- one identity
per box, the same one for the prompt, the page and any program. This
file is the reference for anyone (human or agent) changing it. It
describes how things are, not how they came to be.

## Principles

- **Simple.** One command (`spark`), one bootstrap, one install script, one
  config format (`KEY=value`), python3 stdlib >= 3.9 or POSIX sh, nothing else.
- **The spine, one command.** spark: the engine, the model, chat, the
  `?` prompt line, the FORGE, users -- always installed, one rc line and
  nothing else touched. spark apps: a tool becomes smart by being a
  client of one spark surface -- text on stdin (`spark edit`, contract
  10; `spark line`, contract 4), the shell (`? words`, `spark do`,
  `explain`, `$EDITOR`), or the FORGE's API (contract 9) -- and its
  plugin lives in its own repository, named `spark-<app>` (micro first:
  forgewright-ai/spark-micro), installed the app's way. spark ships no
  app, no app package, no app check row, and no per-app verb. The shell
  layer (`SITE_SHELL`, `spark shell on|off`, default off): spark's own
  shell for a machine that is only an AI box -- tmux, starship, fzf,
  eza, bat, btop, zoxide, the Nerd Font, palettes, the bar, quiet login
  and boot. It stays green behind its gate; the docs a new user reads
  give it one paragraph, never a third of the story, and no word that
  writes it off (docs_test). A domain is a switch (`spark shell`); an
  app is not.
- **The seed and the FORGE.** spark is the seed; the FORGE is the agent it
  builds and keeps. One identity per box (`soul`, `memory`); every client --
  the prompt here, a laptop's `spark`, a script, a phone -- talks to the same
  FORGE, and the prompt is only the first line of interaction. spark is the
  small model at the prompt; an ember is the conversational model; the forge
  serves both with one identity. The FORGE is found (`/api/health` says
  `forge: true`), never assumed.
- **Privacy by design.** Nothing leaves the machine except package managers,
  pinned sha256-verified downloads, and `spark` talking to a FORGE or a
  llama-server you run. Identity lives in `~/.config/spark/site.env`, never
  in the repo; the soul and the memory are yours, under `~/.config/spark/`.
  Secrets are 0600 files, never config values. The words in `.privacy-terms`
  never appear anywhere in this repository; the pre-commit hook enforces it.
  The personal words are not published either: they live in
  `~/.config/spark/privacy-terms` (or `SPARK_PRIVACY_TERMS`), 0600, one per
  line, and the hook and the `privacy` row read the union of both lists.
- **Text-first.** Plain-text output that pipes; `--porcelain` for machines;
  no curses; keyboard-only. Long output pages at a terminal (`$PAGER`, else
  `less`; `page()`/`paged()` in `lib/spark/__init__.py`) and is always
  plain when piped. Every character spark prints is drawable on the
  Linux console: the mark is the word `spark`, the answer and warn marks are
  `*` and `!` on every OS and terminal (one mark, both OSes), and on the
  console (also inside a tmux running on it, or with `SPARK_ASCII=1`) the
  report/bar glyphs fall back to `+ x - | v ^ ->`. The docs are ASCII too (the hook refuses
  anything else): they are read on that console as well.
- **Symmetric.** Every feature exists on both OSes, using each OS's native
  mechanism (apt or pacman/brew, systemd/launchd, bash/zsh). Nothing
  OS-only ships. A Linux package family is one oracle beside `is_wsl()`
  (`distro()`, `ID` then `ID_LIKE` from os-release, `SPARK_OS_RELEASE`
  pins it), one data file `distro/<id>.env` (the names), and the verbs
  that ask a package manager switched once on `PM` (bootstrap's
  `pkg_*`, `lib/spark/packages.py`); what a family lacks refuses in one
  signed line, its rows say so (`check.ARCH_ROWS`, a sixth selftest
  pass), never fail. Windows is reached through WSL 2: Ubuntu there is Linux to spark, minus
  what the VT console and GRUB own (`is_wsl()` beside `os_pretty`; the
  verbs that own those refuse in one signed line, their rows say so, never
  fail). CI has no WSL runner: `check.WSL_ROWS` and a fifth selftest pass
  pin the branch by fixture; a real run there is the maintainer's, by hand.
- **The user chooses.** Theme, prompt, model, workstation name, user -- all
  `site.env` keys with defaults. Nothing aesthetic or sized-to-hardware is
  baked in.

## The four obligations

Every change lands in four places, or it is not done:

| # | obligation | where |
|---|---|---|
| 1 | apply | the live machine |
| 2 | reproduce | `bootstrap.sh` / `install.sh` / `Brewfile` / `templates/` / `home/` |
| 3 | detect | a row in `spark check` (`lib/spark/check.py`), fixture-tested by `--selftest` |
| 4 | explain | `README.md` / `INSTALL.md` / this file / `CHEATSHEET.txt` |

Then commit and push. `spark check` has a `git` row that warns while the
working tree is dirty or ahead of origin.

Skipping #3 is the expensive one: a capability nobody checks is one you
discover is broken by needing it. **A check that has only ever returned one
answer has never been tested** -- break the thing on purpose, watch the row
go red, put it back. `--selftest` automates this for every row that can be
fixture-tested; the rest are listed as untestable with the reason.

## Layout

```
get             POSIX sh, both OSes: the one-liner. Clone (or pull) ~/.spark, exec spark setup
bootstrap.sh    POSIX sh, both OSes. --dry-run --list-packages --list-tools --list-models
install.sh      POSIX sh, both OSes. Links home/ + <os>/home/ into $HOME; renders templates/
lib/env.sh      the KEY=value reader for the two scripts (config.py is the python twin)
Brewfile        macOS packages (the Linux lists are distro/<id>.env)
distro/         one KEY=value file per Linux package family (debian.env): the
                manager, its install line, the doc's name, the five package groups
site.env.example, models.env, themes/*.env       KEY=value data
bin/spark, bin/explain -> spark                  the one command
lib/spark/      __init__ config wire engine serve session persona cli check
                verify (sha256, cached: spark model verify, check's models row) bar theme site
                packages (the family's names from distro/<id>.env, the manager's
                questions -- installed, pending, install/remove lines -- switched once)
                chaos (spark check --chaos: the rehearsed failures --
                break a throwaway machine, prove the row says so and its
                own remedy heals it; a llama-server with a mood, as a
                real process, so it can be killed mid-reply)
                setup (spark setup: the guided first run)
                stats (turns -> numbers) bench (llama-bench, bench tune [show|apply])
                soul memory (the identity files)
                text (the streams: wrap, fence, and the grounding law -- anchor,
                Ground, Gate, shared by every contract that shows a text to a model)
                ledger (what you have already weighed: one sealed file, a kind per
                contract, and the rule that retires a record is the contract's own)
                ask (spark ask: contract 12) read drill (contracts 11 and 13: the
                contract text and its constants, no code, nothing dispatched yet)
                forge (identity, threads, reply, the chat REPL, @FILE)
                forgeserve (the FORGE server: spark forge, the API, the page) do (spark do)
                version (the version, from git, cached: spark ver, check's header, forgeserve)
                update (spark update: the newest tag, or main; converges)
                uninstall (spark uninstall: the plan, the word yes, then everything
                spark made goes; yours stays unless --purge; the clone last)
                chacha (ChaCha20-Poly1305 written from RFC 8439, pinned to its
                vectors in tests/vault_test.py: the sealed stores' cipher)
                vault (the sealed-file format and the key custody: a per-user
                data key wrapped by the token; sha256 verifier; pbkdf2)
                users (the named users, their store under state/users/, and
                this machine's login: spark user)
lib/spark/forge/  index.html spark.css spark.js manifest.webmanifest favicon.svg
                  -- the page, ASCII, no inline script
home/           shared $HOME mirror (linked): the two widgets, the two rc hooks
                (.config/spark/hook.bash hook.zsh: PATH, the widget, the blank row, completion,
                the VT palette -- TERM=linux only), the two completion files (.config/spark/completion.bash completion.zsh:
                TAB completes the verbs and their names, offline), the banner, spark.env.example
linux/home/     .bashrc .bash_profile, the systemd user units (spark-serve spark-forge spark-check)
macos/home/     .zshrc .zprofile
templates/      rendered, not linked: .gitconfig .tmux.conf .config/btop/btop.conf
                .config/micro/colorschemes/spark.micro .config/micro/settings.json (seeded once;
                both only with the layer on AND micro on PATH -- the look for a micro you have)
                .config/starship.toml.{minimal,full} .config/spark/launchd/spark.{serve,forge,check}.plist
tests/          install_test.sh get_test.sh update_test.sh uninstall_test.sh smoke.py serve_smoke.py
                docs_test.py (the docs say what the tree holds: credits, counts, pages,
                the voice of what a new user reads)
                audition.py + audition/ (the editor's briefs against a live brain, lints as the
                judge; not in the gate) vault_test.py site_test.py check_selftest.py
                forge_smoke.py bench_smoke.py widget_pty.py check_selftest.py
                vault_test.py (RFC 8439 vectors, round-trips, refusals)
.githooks/      pre-commit (privacy gate, syntax, tests, 80-col), commit-msg (the
                same privacy patterns over the message -- history is public too),
                pre-push (install test, selftest, chaos)
.github/        ci.yml: the same on ubuntu (plus a real bootstrap) and macOS (python 3.9);
                the new user's one-liner in a debian:13 and an archlinux container
                release.yml: the GitHub Release from the CHANGELOG section, on a v* tag
                pages.yml: www/ rendered and published to GitHub Pages on a doc change
                and on a published release (the sign line links the release)
LICENSE         MIT, verbatim, ASCII (the hook checks it with the docs)
assets/         banner.svg -- the banner as rectangles, for the README and the page
                (banner-light.svg is the page's light-theme variant);
                banner-svg.py makes both from home/.config/spark/banner; icon-svg.py
                makes the favicon, the app icons and the social card the same way
www/            the page, spark.forgewright.ai: build.py (stdlib) renders the docs
                (INSTALL, CHEATSHEET, the model list, CHANGELOG, ROADMAP,
                CONTRIBUTING, CREDITS) into www/dist/ with template.html; index.html
                is the front: onboarding in three stages (the OS picker, the
                one line, spark apps), every command on it a doc's own line
CREDITS.md      every third-party project spark downloads or installs,
                with its license; spark's own code is LICENSE
ROADMAP.md      what comes after the current release, in order
APPS.md         the editors and tools that speak to spark, and how each one
                connects; outside the landing rule, kept true continuously
SHELL.md        spark shell and spark bar: the layer behind SITE_SHELL,
                off by default; outside the landing rule, like APPS.md
```

Runtime paths: config `~/.config/spark/{site.env,spark.env,theme.env,
console-colors,console-colors.rgb,soul,memory}` (`console-colors` is the
precomputed Linux VT palette -- `\033]P<n><rrggbb>` per ansi colour, the
sixteen VGA values after `none`, never `\033]R`: the kernel's defaults may
be a theme -- written by `spark theme`/`spark setup` only, sent to a
running VT by `theme.apply_console` followed by a redraw (a framebuffer
paints a palette only into cells drawn after it) and by the rc hooks at
login, `TERM=linux` only. `console-colors.rgb` is the same palette in
`setvtrgb`'s three-line form for root at boot: bootstrap's `vt-palette`
row installs the one-shot `spark-console.service`, which sets the kernel's
defaults so the login screen and every VT wear it before any shell runs;
the `theme` row compares that file with `/sys/module/vt/parameters` --
`SPARK_SYSFS_VT` pins it in the fixture; `soul` and `memory` are prose,
0600, yours: never linked from `home/`);
state `~/.local/state/spark/` (0700: `api-token` 0600, `serve-url`,
`serve.pid`, `serve.log`, `serve.lock`, `forge-token` 0600, `ember-token`
0600, `forge-url`, `forge.pid`, `forge.log`, `forge.lock`,
`router/` (`spark.gguf`, `ember.gguf`, `presets.ini` -- the router's
models dir, written by `spark serve`), `off`, `widgets/`, `turns/`,
`threads/` (pre-v1.4 plaintext threads only; `spark user claim` seals them
away), `chat-history` 0600, `brain`, `check.json`, `bar`,
`bench.jsonl`, `tune.json`,
`users/<name>/` (0700 per user: `token.hash` and `key` 0600 -- the sha256
token verifier and the wrapped data key -- plus that user's sealed
`threads/`, `memory`, `chat-history`, `ledger`), `account` 0600 (this machine's
login: name and token), `account-key` 0600 (the unwrapped data key, so
the hot paths never pay the KDF)); data `~/.local/share/spark/{engine,models}`;
tools linked into `~/.local/bin`. `spark uninstall` (`lib/spark/uninstall.py`)
removes all of it but the sealed stores, the account keys and your prose
(`--purge` takes those); it runs bootstrap ONCE first -- headless and quiet
undone through their rows with the shell layer still on -- and never
`site.apply` or `check.refresh` after (each would put things back); root
steps become `todo` rows when sudo refuses; the clone goes last, only when
it is `${SPARK_HOME:-~/.spark}` and clean.

## Contracts

These are the only interfaces between parts. Everything else is private and
may change freely.

1. `bootstrap.sh --list-packages` prints one package per line, after OS and
   site branching. `--list-tools` prints `repo-relative-path<TAB>name` per
   line. `--list-models` prints the model table with a RAM verdict per row
   and marks the chosen one; its header names the engine build this
   machine gets (`ai_build`: metal, vulkan or cpu) and, on a line of its
   own, what the speed cap held back, when it did. `--fetch URL DEST SHA` runs the download primitive
   alone -- download, verify sha256, or die having removed its own
   partial file (`spark check --chaos` rehearses that; nothing else
   calls it). `--dry-run` prints rows `ok|would|skip|todo
   <what>  <why>` (`todo` = needs the user, e.g. a placeholder in site.env)
   and ends with `Nothing to do` or `N to do`; it never calls sudo. An
   APPLY run prints only what it changed and what needs the user: `ok`
   and `skip` are silent there (and so are the section headers) unless
   `--verbose`, because a converged machine has nothing to report and
   said it in 54 lines. `--dry-run` stays the full report -- `spark
   check`'s configs row and tests/install_test.sh read those rows. An
   apply run that will need root asks for sudo ONCE, before it touches
   anything (`sudo_upfront`), and only at a terminal: over ssh or a
   pipe there is nobody to answer, and a run needing no root at all
   (`spark update` on a converged machine) must not be made to ask.
   No sudo on the machine at all is one line and exit 1, up front. The
   `rc` row appends one marked line (marker `config/spark/hook.`) to the
   end of the login shell's rc file -- `~/.bashrc` or `~/.zshrc`, by
   `$SHELL` else the passwd entry -- creating it if absent and never
   truncating it; a rc file that is spark's own symlink is `ok` as it is;
   another shell, or bash < 4, is a `todo` naming the fix. On bash, a
   regular `~/.bash_profile` that neither sources `~/.bashrc` nor holds
   the marker shadows the hook on a console login -- the `rc-login` row
   appends the same marked line there. `spark shell off` restores an rc
   file from its `.bak`, or removes it when there was no file before --
   never an empty husk.
2. `install.sh --dry-run` prints rows `ok|would link|would render|would back
   up  <path>` and the same final line. Apply is quiet the same way: an
   `ok` row (already in place) prints only with `--verbose`. Link = symlink into the repo; render
   = a regular file written from `templates/`. An existing regular file, or
   a symlink that points outside the repo, is moved to `<path>.bak`, never
   overwritten (a stale symlink into the repo is replaced). The rc files
   and the shell templates (`.gitconfig`, `.tmux.conf`, btop, starship)
   are installed only with `SITE_SHELL=on`; micro's colorscheme and its
   `settings.json` seed only with the layer on AND micro on PATH
   (`look_micro`: the look for a micro the user has -- spark installs no
   editor). `settings.json` is seeded once and never re-rendered (micro
   rewrites it) -- except its `colorscheme` key, which `spark theme NAME`
   sets back to `spark` when micro changed it (`theme.micro_colorscheme`;
   the `theme` row warns meanwhile). `spark shell off` hands the rendered
   look back the way it hands the rc files back (`site.restore_rendered`):
   each of `.tmux.conf`, `.config/starship.toml`, btop's conf and micro's
   colorscheme is restored from its `.bak` or removed -- never an empty
   husk; `settings.json` stays (it is micro's) and only its seeded
   `colorscheme` key is dropped (`site.micro_settings_reset`);
   `.gitconfig` (identity, not look) and the core palette files under
   `~/.config/spark/` stay. A `micro` bootstrap row hands back, once, the
   plugin links and `bindings.json` a pre-v1.10 install made under
   `~/.config/micro` (the plugin lives at forgewright-ai/spark-micro now).
3. Config files are `KEY=value` lines; any other non-blank, non-comment line
   is refused by every reader (`^[A-Z_0-9]+=[^;`$()|&<>]*$`). Keys:
   `site.env` -- `SITE_NAME SITE_USER SITE_SET_HOSTNAME SITE_GIT_NAME
   SITE_GIT_EMAIL SITE_WORKSPACE SITE_PEER_AI_URL SITE_PEER_SSH SITE_THEME
   SITE_PROMPT SITE_PROMPT_STYLE SITE_AI_MODEL SITE_EMBER_MODEL SITE_AI_BUDGET
   SITE_AI_BUILD SITE_FONT_FACE
   SITE_FONT_SIZE SITE_QUIET_LOGIN SITE_QUIET_BOOT SITE_QUIET_START SITE_QUIET_AUDIO
   SITE_HEADLESS SITE_SHELL`;
   `spark.env` -- `SPARK_PORT SPARK_BASE_URL SPARK_PREFER_URL SPARK_SERVE_HOST
   SPARK_ENGINE_DIR SPARK_MODELS_DIR SPARK_MODEL SPARK_NGL SPARK_CTX
   SPARK_FLASH_ATTN SPARK_KV SPARK_THREADS SPARK_EXTRA_ARGS SPARK_MEM_NEEDED_GB
   SPARK_API_KEY_FILE SPARK_TIMEOUT SPARK_HISTORY SPARK_MEMORY SPARK_SERVICE
   SPARK_FORGE SPARK_FORGE_HOST SPARK_FORGE_PORT SPARK_FORGE_TOKEN_FILE`
   (`SPARK_PERSONA_EXTRA` is still read, as the soul's fallback, in this
   version only; the `soul` row warns while it is set);
   `models.env` and `~/.config/spark/models.env` (yours) --
   `MODEL_<NAME>="<file> <url> <bytes> <sha256> <ram_gb>"`, plus
   `MODEL_<NAME>_LICENSE="<name> <url>"` (required, every row),
   `MODEL_<NAME>_TESTED="line"` (present only on a row proven on the
   line: with an open license -- `config.OPEN_LICENSES`, Apache-2.0 or
   MIT -- it is a row `auto` may pick) and `MODEL_<NAME>_NOTE` (one line,
   optional). A name in both files is refused, naming both;
   `distro/<id>.env` (one per Linux package family the oracle `distro()`
   knows -- `lib/spark/__init__.py` beside `is_wsl()`, the sh twin in
   `bootstrap.sh`, `SPARK_OS_RELEASE` pins it) -- `PM PM_INSTALL
   PM_TARGET PKG_CORE PKG_ENGINE PKG_AI PKG_SHELL PKG_CLI`, the same eight
   keys in every file (`packages.KEYS`; tests/docs_test.py asserts it);
   `themes/<name>.env` -- `THEME_BG THEME_FG THEME_ACCENT THEME_MUTED
   THEME_BTOP THEME_ANSI_0..15` (the same 21 keys in `lib/env.sh`
   `THEME_KEYS` and `config.theme_palette`: the two validators agree);
   `~/.config/spark/themes/<name>.env` is yours, the same keys, and wins
   on a name clash (`config.theme_path`, `lib/env.sh theme_load`).
   `THEME_LOGO` is optional in either: six colour names, one per banner
   row (`bright-` allowed), and `spark ver` draws the logo in them
   (`cli.recolour`); unset, the logo keeps its own. It rides in
   `theme.env` with the rest when present (both twins).
   Precedence: environment > file > default.
4. `spark line --cwd D --shell S` reads the prompt buffer on stdin and prints
   line 1 = `cmd<TAB>command` | `danger<TAB>command` | `answer` | `error`,
   line 2 = hint / answer / reason -- one line, cut at a word to a
   character budget (a hint or reason <= 80, an answer <= `cli.ANSWER_MAX`;
   the widget trims to the terminal's own width). Exit 0 for the first
   three, 1 for error. A buffer starting with `??` continues the newest
   thread; any other starts a new one (no heuristics). The shell widgets
   depend on nothing else.
5. `spark brain --porcelain` prints `<url><TAB><model><TAB>forge|model`
   (`<model>` is the spark role's model -- the file stem; `forge` when
   `/api/health` there says `forge: true`) and exits 0, or exits 1. This
   is the check's only AI probe.
6. A live widget writes `~/.local/state/spark/widgets/<pid>` containing
   `<shell> <pid> <epoch> [hook]` and removes it on shell exit. The
   fourth field, the literal word `hook`, says that shell's exit-code
   hook is armed (the failure moment); readers ignore fields they do
   not know, so old markers and old readers both survive.
7. `spark check` exits 0 iff no row is `fail`; CAPABILITY rows never
   `fail`. `--porcelain` prints `category<TAB>status<TAB>name<TAB>value<TAB>
   remedy`. Every run writes `~/.local/state/spark/check.json` for the bar.
8. Signing: the first line of `spark --help` and of every subcommand's help
   is `spark <sub> -- <one line>` -- plain ASCII, so every terminal can draw it.
   `spark shell --` is that line for the shell layer's switch; `spark
   setup --` is the offer bare `spark` prints, after the banner, on a
   clone with no `site.env` at a terminal; and a refusal signs the same
   way: with `SITE_SHELL=off`, `spark bar` prints
   `spark bar -- the shell layer is off (spark shell on)` and exits 2,
   and the set forms `spark quiet login|boot on|off` refuse with the
   same line (showing still answers, saying the layer is off); `spark
   help` then folds the shell block into one `spark shell on` line.
   `spark theme` and `spark font` are core: they answer either way.
   `spark uninstall -- not a terminal: spark uninstall --yes runs it` is
   the refusal of a non-terminal without `--yes` (the plan printed, 2). On
   WSL 2 the same shape: `spark font -- no console on WSL 2: the font
   lives in Windows Terminal's settings` (show 0, set 2), `spark quiet
   boot -- no GRUB on WSL 2: Windows boots it`, `spark headless -- WSL 2
   stops with its last window: not a brain (a Linux box is)` (exit 2). On
   Arch likewise: `spark font -- no console-setup on Arch: the console
   font is /etc/vconsole.conf's (FONT=), left alone in this version`
   (show 0, set 2) and `spark quiet boot -- no update-grub on Arch: GRUB
   is left alone in this version` (exit 2).
9. The FORGE's HTTP API (`lib/spark/forgeserve.py`, on
   `SPARK_FORGE_HOST:SPARK_FORGE_PORT`, one LAN address, never `0.0.0.0`).
   `GET /api/health` answers without a token: `{status, forge: true, name,
   version, model, upstream, models, roles}` (`models` = `{role: loaded|
   unloaded}`, `roles` = `{role: model file stem}` per served role) -- the client's FORGE detector and the
   `forge` row's probe. `GET /`, `/login`, `/static/<f>`,
   `/manifest.webmanifest` and `/apple-touch-icon.png` (a 180x180 PNG the
   server draws) are the page, no token. Auth: the forge-token is admin
   (the whole box, and the box account's own store); every other caller
   is a named user (`spark user add NAME`) presenting their personal
   token -- verified against its stored sha256, and unwrapping their
   data key in memory only. `POST /api/login` takes `{token}`, sets the
   cookie derived from it and answers `{ok, name, role, user}` (1 s and
   401 when wrong; 429 after 10 wrong per minute from one address); a
   user cookie lives in an in-memory session, so a server restart sends
   browsers back to the login (the key cannot come back from a cookie),
   while a bearer is stateless. A wrong bearer costs 1 s and is
   counted; an unknown cookie is only a 401 (after a restart every
   browser holds one). The v1.3 shared ember-token is not accepted.
   Every other `/api/*` and `/v1/*` route needs the cookie or a token
   as a bearer, else 401. Admin-only: `GET` `/api/serve`, `/api/gpu`,
   `/api/bench`, `/api/config`, `/api/log`, `/api/users` and `POST`
   `/api/run`, `/api/do/propose`, `/api/do/run`, `/api/check/refresh`,
   `/api/soul` (the soul is the box's one identity) -- a user there
   gets 403 `{error: {kind: role}}`; every other authed route is
   user-or-admin, and `GET /api/me` answers `{role, user, name,
   version}`, which is how the page decides which console to draw and
   whom to greet. `GET /api/models` (user-or-admin) answers this box's
   model table `{name, total_gb, budget_gb, budget_pct, backend,
   cap_note, models: site.model_rows}` -- what `spark model` on a client
   prints instead of its own numbers. The chat, thread and memory routes are scoped to the
   requester's own sealed store -- a user's to their
   `users/<name>/`, the admin's to the box account's; nobody holds a
   key to anyone else's. `GET /api/users` (admin) answers `{users:
   [{name, threads, last}]}` -- counts and stamps, never a title, a
   body or a token: the whole of admin visibility. `POST
   /api/user/token` (user) rotates the requester's own token, returned
   once, never stored; `DELETE /api/threads` clears the requester's own
   store and answers `{cleared}`. Every `POST` and `DELETE` under `/api/` except `/api/login`
   also needs `X-Spark: 1`, a JSON object body, a `Host` this machine
   answers to and, when sent, an `Origin` matching it (400/403); `POST
   /v1/chat/completions` needs only the bearer or cookie. `GET
   /api/check` returns `check.json` as written plus `age` (seconds).
   `POST /api/do/propose` answers `{thread, reply, ms, driver,
   unchecked}` -- `driver` the ember role's model stem, `unchecked` the
   done hint's numbers no user message of the thread backs (`[]`
   otherwise).
   Streams are SSE: `/api/chat` (mode `chat|answer`; `talk` and `ask` are
   the old names for `chat` and `answer`, accepted for one version, and
   records write the new ones) emits `queued` (when the model is busy),
   `delta {t}`, `done {thread, ms, model}`, `error {kind, hint}`; a
   client that hangs up mid-stream (the stop button) still lands the
   turn -- the user line and any partial answer (`partial: true`) go on
   the thread, and the log line says 499; `/api/run` emits
   `line {s}` then `done {rc}`; `/api/events` emits `check`, `bar`, `serve`
   on change (`log` too, for an admin) and a `:keepalive` comment every
   15 s. `/v1/chat/completions` and `/v1/models` are OpenAI-shaped and
   proxied to the llama-server with the api-token; the request's `model`
   field routes -- a missing `model` means `ember` -- and the identity
   (the soul, plus the requester's own remembered facts: a user's
   sealed memory, the box account's for the admin) is injected into the
   system message only for an ember request, a `spark` request passing
   through untouched; JSON or SSE bytes come back as they are. Every `/api/*` answer is `Cache-Control:
   no-store`; the page is served with `Content-Security-Policy:
   default-src 'self'` and depends on nothing else. Errors are
   `{error: {kind, hint}}`.
10. `spark edit` is the editor's protocol: the text on stdin; `--at N`
    prints what goes at byte offset N (a completion: 4 kB before the
    cursor and 2 kB after it are sent), `<words>` prints the whole text
    rewritten (at most 12 kB, else refused: the output replaces the
    input, so head+tail makes no sense), `? [words]` answers about it
    (head 4 kB + tail 12 kB, a visible cut mark; `?` alone reviews);
    `--type FT`, `--name NAME`, `--about TEXT` and `--part` (the text is a
    selection from a larger file: the rewrite replaces exactly it) are
    hints that ride in the user message (the name is a basename, never a
    path; no `[cwd]` line, ever). Output is raw streamed text: no mark, no wrap, a code
    fence around the answer removed, a rewrite ending the way the input
    ended; an empty text with words is written from nothing (a new file
    in the editor), the reply ending with a newline. Exit 0; 1 when `?` or
    `--at` find no text, or no brain answers; 2 for the usage. No thread is kept; the turn record is numbers (`kind`,
    `chars`, `ms`). A `?` is two requests: the reading (`edit-read`, a
    JSON `{language, kind}` from the first 800 chars, restated as `You
    read this as: ...`; any failure is silence) and the answer. A `?`
    answer streams line by line through `text.Anchors`: every quoted
    span (double quotes, curly quotes, backticks; 3..200 chars) is
    checked against the text on stdin -- verbatim, then folded
    (whitespace, quote marks, case), then trailing punctuation stripped
    -- and one that does not
    anchor is followed by ` [not in the text]` where it stands (a span
    right after `->`, a Unicode arrow or `=>` is the model's proposal: not checked,
    not counted); the turn
    records `quotes` and `unanchored`. `--sel A B` (a `?`; stdin is the
    whole file) sends one window of at most 16 kB (`cli._edit_window`):
    the selection whole (head + cut + tail past 12 kB) between the lines
    `[selection starts]` / `[selection ends]` the brief knows, the file
    around it split evenly, cut marks where it goes on; the reading
    runs on the 800 chars from 200 before the selection. `--thread ID`
    (a `?`; the CLIENT names the id, `forge.valid_id`) keeps the
    exchange in the account's sealed store like a chat thread
    (`forge.open_thread`; `SPARK_HISTORY` prunes it; `spark history`
    lists it): the same id again rides the earlier pairs and sends the
    words alone when the text on stdin is the one the first turn carried
    (`text_sha` on that message), else `File NAME, as it is now:` and the
    text; the reading runs on the first turn only; anchors always check
    the text on stdin now. Without `--thread`, or with history off, no
    thread is kept. `--decline --name NAME` (the pane's `d`) keeps the
    note on stdin in the ledger (`lib/spark/ledger.py`: the account's
    sealed `users/<name>/ledger`, by file NAME, 300 chars a note, 30 a
    name, 200 in all); a later `?` about NAME carries `Declined before --
    do not raise these again:` and the notes, newest first, 1200 chars at
    most; a note whose first quoted span is no longer in the text has
    retired (dropped there and then), and every note leaves after
    `SPARK_HISTORY` days. `--ledger [clear] --name NAME` lists or drops them
    (the pane's `ledger` and `ledger clear` at the `spark>` prompt); no
    shell verb. The micro plugin depends on nothing else.
11. `spark read` -- reserved, not built. The contract's text is in
    `ROADMAP.md` and in `lib/spark/read.py`; nothing dispatches to it, and
    `spark read` is an unknown word until one line lands in `bin/spark`'s
    `VERBS`.
12. `spark ask` is the questioner's protocol: the text on stdin -- a plan,
    a draft, a decision -- and questions about it out, raw, one per line;
    never a path, never a `[cwd]` line. Mode from the argument shape, no
    mode flags: bare asks what the text does not answer, `<words>` says
    what the author is deciding. `--name NAME` (a basename) and `--about
    TEXT` are hints that ride in the user message; a reading pass runs
    first (`session.reading`, contract 10's); `--thread ID` (the CLIENT
    names the id, `forge.valid_id`) keeps the exchange in the account's
    sealed store, the same id again riding the earlier pairs and sending
    the words alone when the text is the one the first turn carried
    (`forge.same_text`) -- and a follow-up obeys the same law, so the
    moment a reply may assert, this is `spark chat`.
    The law is enforced after the model, never by the brief alone: every
    line of the output ends in a question mark or it never reaches stdout
    (`text.Gate`, line by line). Five filters, in this order -- a line
    that is not a question; one whose every quoted span is missing from
    the text (`text.UNGROUNDED`); anything past the cap of three (a cap,
    never a target); a repeat, or a question the ledger holds as
    answered; a question that could be asked of any plan (`ask._GENERIC`,
    a named list, forgiven when the question shares a word of its own
    with the text). When nothing survives, stdout stays empty and the
    refusal is one line on stderr, exit 1: a client tells "no question"
    from "a question" by the exit code, never by reading prose. At most
    12 kB in, else one line and exit 1; exit 2 for the usage, and stdin
    with no text prints it plus where a question for spark itself goes
    (`spark <words>`). `--answered --name NAME` keeps the question on
    stdin in the ledger (kind `ask`, `ledger.RULES`: nothing invalidates
    it but age and `clear` -- a plan moves, an answer stays an answer);
    `--ledger [clear] --name NAME` lists or drops them. A round where
    nothing survived is not written to the thread: a refusal is not a
    turn to follow up on. The turn record is numbers (`kind`, `chars`,
    `ms`, `asked`, `dropped`, `quotes`, `unanchored`).
13. `spark drill` -- reserved, not built. The contract's text is in
    `ROADMAP.md` and in `lib/spark/drill.py`; nothing dispatches to it.
    Its ledger rule inverts every other one -- a missed item comes back
    rather than being suppressed -- which is why `ledger.RULES` exists.

## The grammar

One grammar for every verb; a verb that breaks a rule is a bug.

1. A bare verb shows; it never mutates. The one carve-out: `spark bar`
   with stdout not a tty still prints the bar line itself -- tmux's
   status-right runs `spark bar` and must always get the line, never a
   state change.
2. `on|off` is the only switch vocabulary at the CLI (shell, bar,
   headless, serve, forge, quiet, memory) -- including the two servers,
   which hold the same kind of state and so answer the same way; there
   is no `start`/`stop` pair beside it, and `--force`/`--noreload` are
   flags of `off`. Stored values are storage, not
   interface: `SITE_HEADLESS` and the `SITE_QUIET_*` keys stay `yes|no`
   in `site.env`; the verb translates. Choices keep their value grammars
   (`theme NAME|none`, `model NAME|auto|none`, `client URL|off`). The
   one carve-out is bare `spark off` / `spark on`, which silences and
   restores the whole prompt: it is the global mute, and reads better
   without a noun in front of it.
3. `status` is an alias of bare for every stateful verb; `list` is the
   table word (theme, model, ember, font). A noun keeps its own verbs as
   sub-words rather than taking top-level ones: `spark soul edit|reset`,
   `spark memory add|forget|clear`.
4. Every verb answers `-h|--help|help` first -- before any gate or
   config read -- signed per contract 8.
5. One confirm shape: `<question>? yes/NO: ` -- only `y` or `yes`
   proceeds; Enter or EOF is no (`confirm()` in `lib/spark/__init__.py`,
   beside `say()`). The one deliberate second shape, two users: `spark
   do`'s danger step and `spark uninstall` require the typed word `yes`.
6. One progress vocabulary: curl's bar for downloads, and one
   dot-spinner -- `wait_ready(label, probe, timeout, interval)` in
   `lib/spark/__init__.py` -- for every wait on a server coming up.
7. Exit codes: 0 ok or show; 1 the world failed (stderr, via `die()`);
   2 the invocation -- usage, an unknown name, a gate refusal (stdout,
   signed); 78 misconfiguration (`EX_CONFIG`); 130 SIGINT.

## Adding things

- **A doc.** The page (`www/`, spark.forgewright.ai) is the docs rendered:
  a change in INSTALL.md, CHEATSHEET.txt, models.env, CHANGELOG.md,
  ROADMAP.md, CONTRIBUTING.md or CREDITS.md ships on the next push to main,
  nothing to do. The look lives in `www/template.html` (dark and light, in
  lockstep with `lib/spark/forge/spark.css` -- docs_test checks); the front in
  `www/index.html` (onboarding in three stages; every command on it is a
  line of INSTALL.md or the README, and site_test checks); the
  markdown subset in `www/build.py` (tests/site_test.py holds its
  invariants -- a new construct in a doc needs both). The docs are kept
  true by `tests/docs_test.py` (pre-commit, CI): every palette and every
  model upstream is in CREDITS.md, the check-row and model counts the
  docs state are the tree's, every page has its source, no retired word
  survives. A new fact a doc states that the tree can derive goes there
  as one more check -- the test is the consistency, not a reviewer. What
  a new user reads (README, INSTALL, CHEATSHEET, the page front) is
  minimal and step by step and speaks two nouns, spark and spark apps:
  no FORGE, ember or brain as a noun there, no "smart app", nothing
  private named anywhere in the tree's docs (docs_test holds the word
  list; this file and AGENTS.md keep the contracts' names).
- **A package.** Linux: the right `PKG_*` group in every `distro/<id>.env`
  with a comment saying why (`PKG_CORE`/`PKG_ENGINE`/`PKG_AI` are the AI,
  always installed; `PKG_SHELL`/`PKG_CLI` the shell layer, `SITE_SHELL=on`),
  under the name that family's manager knows, and its credit in
  `CREDITS.md` (docs_test looks every name up). macOS: `Brewfile`, same
  comment -- the whole Brewfile is the shell layer; the AI needs nothing
  from Homebrew. No editor, no app and no contributor tool in either
  (shellcheck is the contributor's own). The `packages` row and `spark
  uninstall` read the same files through `lib/spark/packages.py`;
  bootstrap's `pkg_installed`/`pkg_available`/`pkg_install` are the sh
  twin, the one place that switches on the manager. Nothing else to
  update.
- **A config file.** First ask whether the app *rewrites* its own config.
  If it only reads: put it in `home/` (shared) or `<os>/home/`; `install.sh`
  links it. If it rewrites: it cannot be linked -- seed it once from
  `templates/` as a rendered regular file, and note it in INSTALL.md's trap
  table (SHELL.md). Test by changing a setting in the app
  and running `ls -l` on the path: still a symlink, or now a regular file?
- **A choice.** A `SITE_*` key with a default in `site.env.example`, applied
  by `bootstrap.sh` or rendered by `install.sh`, **and** a `spark <verb>`
  that sets and applies it (`spark theme`, `spark font`, `spark quiet`;
  `lib/spark/site.py` has `set_keys` and `apply`). Editing `site.env` by hand
  is the fallback, never the interface.
- **The landing rule.** Nothing is done until it is in all of: `spark help`
  (bin/spark), a `spark` command, a `spark check` row when it is a promise
  the machine makes, contract 3 above if it is a key, and README / INSTALL /
  CHEATSHEET / CHANGELOG. A key without a command, or a command without a
  row and a doc line, is half a feature.
  The rule binds the CORE documentation, and core documentation moves with
  a release: README, INSTALL.md, CHEATSHEET.txt, `spark help`, this file
  and CHANGELOG.md are updated as a version ships, together. `APPS.md` and
  `SHELL.md` are outside it -- they are kept true continuously, no release
  waits on them, and nothing in them has to appear in help, the cheatsheet
  or a changelog entry. Both say so in their own first lines, and
  `tests/docs_test.py` checks that they do, so neither drifts back under
  the rule by accident.
- **A check row.** A function `row_<name>(ctx)` in `lib/spark/check.py`
  decorated `@row(CATEGORY, fixture=True)` or `@row(CATEGORY, fixture=False,
  reason="...")`. If it is fixture-testable, extend `make_fixture` so the row
  is ok in the good fixture and not ok in the bad one; `--selftest` refuses
  otherwise. CAPABILITY rows use `warn`/`na`, never `fail`, so `spark
  check`'s exit code keeps meaning "something reproducible is broken".
- **A chaos scenario.** A function `chaos_<name>(m)` in
  `lib/spark/chaos.py` decorated `@scenario(row=..., expect=..., ...)`. It
  breaks the throwaway machine `m` one way and returns `""` or why the
  break did not take; the runner then asks the row, runs the heal and
  asks again. The heal is the row's OWN remedy string wherever the
  remedy is a command (`heal="remedy"`; a parenthetical aside after two
  spaces is for the reader, not the shell) -- that is the point of the
  suite, and it is how a remedy naming a renamed verb gets caught. Where
  nothing here can run it, `heal=None` and `unhealed` must say why, so
  an unrehearsed half is visible instead of silent; `healed=NA` where
  the remedy's promise is to forget a thing, not bring it back. A
  scenario with no row (`row=None`) must say what it proves instead.
  `mood` picks the brain: `ok`, `slow`, `hang`, `loading`, `cut`,
  `garbage`, `blackhole`. A scenario is NOT a check row: chaos is a
  prover, like `--selftest`, not a promise the machine makes -- neither
  has a row, and obligation 3 is met by the row the scenario judges.
  Before trusting a new one, take the fix away and watch it go red.
- **A prose data file.** The soul is the pattern: user-owned text under
  `~/.config/spark/`, never linked from `home/`, written 0600 by a
  `spark` verb (and by the page through the same code), capped
  (`SOUL_MAX`), sent to the brain on every request, and reported by its
  own check row (mode, size, cap). It is config, not state: pruning and
  `history clear` never touch it. The memory follows the same rules but
  lives sealed in the account's store since v1.4
  (`users/<name>/memory`, `FACT_MAX`/`FACTS_MAX`/`TOTAL_MAX`); the
  pre-v1.4 plaintext file is read as a fallback until the first write
  or `spark user claim` seals it away. Turns are the opposite pattern:
  telemetry, numbers only -- `session.record` strips every free-text
  field (`session.TEXT_FIELDS`), and the words live only in the sealed
  threads.
- **A route.** In `forgeserve.py`: pick its auth class (none; U = user
  or admin; A = admin-only, added to `ADMIN_GET`/`ADMIN_POST`; plus the
  POST rules) and put it in the matching branch of `_route`;
  answer through `_json`/`_sse` so it is `no-store` and logged; a case in
  `tests/forge_smoke.py`; a line in contract 9. The page calls verbs
  through `/api/run`'s allowlist (`RUN_VERBS`) rather than writing config.
- **A shell-layer thing.** Anything that is not the AI -- a tool, a
  dotfile, a console setting, a tmux piece -- lands behind `SITE_SHELL`:
  its bootstrap row starts `[ "$shell" = 1 ] || skip <row> "$SHELL_OFF"`,
  `install.sh` links or renders it only with `SITE_SHELL=on`, its verb
  refuses through `site.shell_off()`, its help line sits in `USAGE_SHELL`
  (bin/spark), and its check row's name goes into `check.SHELL_ROWS` so
  it reads `na` when the layer is off; `--selftest`'s third pass asserts
  that. `spark shell on|off` (`site.cmd_shell`, `site.SHELL_APPLY_ROWS` --
  bootstrap row names, not check's) is the only switch; `spark shell off` hands back what the layer rendered
  (`restore_rc`, `restore_rendered`: `.bak` or gone, never a husk).
  `spark theme` and `spark font` stay outside the gate (the FORGE page
  reads `theme.env`, the VT console palette and font are the machine's
  face with the layer off too); their `theme` and `font` check rows are
  core for the same reason -- only the Nerd Font piece of `font` waits
  for the layer. The layer installs no editor: the hostname row is core
  too (identity), and micro's colorscheme is rendered only for a micro
  the user already has.
- **A grounded contract.** One law, four contracts (10, 11, 12, 13): what
  a model says about a text is checked against that text before the reader
  sees it. The judge is `lib/spark/text.py` -- `anchor()` at the span
  level, `Ground.verdict()` at the unit level, `Gate` the stream that
  marks what it keeps and drops what it refuses, so a contract can refuse
  instead of invent. A new one states, in `CLAUDE.md` and in its module's
  own head: what grounds its output; what happens when grounding fails
  (one line, and what exit code says so); its caps; its ledger kind and
  the rule that retires a record there (`ledger.RULES` -- each contract's
  own, because a rule that generalised would fit none of them); and what
  leaves the machine. Text on stdin, raw text out, never a path: that is
  what lets an editor with no plugin at all be a client.
- **A spark app.** Nothing in this repository. A tool becomes smart by
  being a client of one spark surface -- text on stdin (`spark edit`,
  contract 10; `spark line`, contract 4), the shell (`? words`, `spark
  do`, `explain`, `$EDITOR`), or the FORGE's API (contract 9) -- and its
  plugin lives in its own repository, `spark-<app>`, installed the app's
  way with its own keys, tests and channel. spark keeps the verb and its
  judge: the editor briefs live in `persona.MODES` (`edit-complete`,
  `edit-rewrite`, `edit-answer`, `edit-read`): no table routes by filetype
  or genre -- the model reads what the text is, and for a `?` its own
  reading is restated to it (small models drift otherwise); the audition
  (`tests/audition.py`) scores those briefs against a live brain. micro
  is the first client, forgewright-ai/spark-micro: it spawns `spark edit`
  with the text on stdin and streams the answer back, never speaks HTTP,
  never sees a token, never sends a path; its pty test, its `Alt-s` line
  and its README are its own. Five clients today, two shapes: a full
  plugin (micro, neovim, vim) carries the whole prompt and completes at
  the cursor; a prompt plugin (helix, nano -- editors with no cursor
  hook) pre-fills the editor's own prompt with `spark edit `, proven the
  same way, by a pty test whose config is the shipped snippet itself.
  The known clients are listed in APPS.md, and every one of them is in
  CREDITS.md and on the page front -- docs_test reads the app names out
  of APPS.md and looks them up in those two; a new one is one line in
  each. The core docs no longer name them at all. A pull
  request that adds an app, an app package or an app check row here is
  turned into a pointer to the app's repository.
- **The client shape.** `SITE_AI_MODEL=none` beside `SITE_PEER_AI_URL`
  (`config.client`; `spark client URL|off`, `site.cmd_client`) means
  nothing runs here: bootstrap skips the `engine` and `services` rows
  (`$client`), `install.sh` links no unit and renders no plist, and the
  rows in `check.CLIENT_ROWS` (engine, services, watchdog, ai, serve,
  forge, ember) read `na`;
  `--selftest`'s fourth pass asserts that with the peer row ok. The peer
  row is where a client's health lives. A client stays a client until
  `spark client off`: `spark model` / `ember list` / `model budget` there
  print the PEER's table (`site.peer_models`, `GET /api/models` with the
  login token; the rows alone, no verdict, when the peer is down, a bare
  server or an older FORGE; `bootstrap.sh --list-models` likewise) and
  never this machine's RAM as a budget; `spark model NAME|auto|none`,
  `model budget N`, `model rm`, `spark ember NAME` are refused with one
  line (`site._client_no`) -- each would have made a server of the
  client in silence. `spark client off` is the one deliberate promotion
  (it ends the shape, then runs `spark model auto`).
- **A model.** One list, `models.env`: a row (`MODEL_<NAME>`, the
  five fields), its `_LICENSE` (always), a `_NOTE` when one line helps,
  and `_TESTED="line"` only once the row has answered `spark line` with
  valid JSON -- `auto` reads only tested rows under an open license
  (`config.auto_rows`, `bootstrap.sh model_rows`); a row under another
  license is by name and asks before the download (`site._license_ok`,
  `config.is_open`). Size and sha256 come from the file's Hugging Face
  metadata: `x-linked-size` and `x-linked-etag` on the redirect
  `.../resolve/main/<file>?download=true` answers with (the CDN it
  points at knows neither). A name already in the other file
  (`~/.config/spark/models.env`, yours) is refused, naming both
  (`config.model_tables`, `bootstrap.sh model_rows_all`). `spark model add
  URL` writes your row for you: huggingface.co is auto-verified from
  that redirect, any other host needs `--sha256`; `--license "NAME URL"`
  is always required there. `spark model verify` (and the `models` check
  row, cached) re-hashes every downloaded file (`lib/spark/verify.py`).
- **A palette.** Two files, nothing else hand-listed: `themes/<name>.env`
  with the full 21-key `THEME_*` set (contract 3; the header comment names
  the upstream project and its license; `THEME_BTOP` names a theme btop
  ships, else `Default`), and its flat 20-value row in `spark.js`'s
  `theme.builtin` map (the page has no build step). `tests/install_test.sh`
  renders every palette by glob, and `tests/smoke.py` asserts the
  `theme.builtin` map matches `themes/*.env` value for value -- a gap in
  either goes loud. A palette of the user's own is one file,
  `~/.config/spark/themes/<name>.env`, the same 21 keys, and lives nowhere
  else: not on the page, not in `CREDITS.md`, not in that map. On macOS
  `spark theme NAME` also switches every open Terminal.app window to the
  profile (`theme._switch_windows`): the running app reads its
  preferences only at launch, so a profile it does not know yet is
  imported live by opening the `.terminal` file (one window opens with
  it), then made the default and set on every tab by osascript.

## Verifying a claim

```sh
./bootstrap.sh --dry-run        # must end with: Nothing to do
spark check                     # must exit 0
spark check --selftest          # every fixture-testable row flips
spark check --chaos             # every rehearsed failure: break, red, remedy, green
spark forge                     # the FORGE: up, at one LAN address, upstream ok
python3 tests/forge_smoke.py    # the API and the page, against a stub model
python3 tests/docs_test.py      # the docs say what the tree holds (credits, counts)
python3 tests/widget_pty.py pager        # $PAGER at a tty; plain when absent
python3 tests/widget_pty.py completion zsh home/.config/spark/completion.zsh
                                # TAB completes verbs and names (bash likewise)
git status -sb                  # clean, not ahead of origin
spark check --porcelain | grep privacy   # the tree contains no banned word
sh tests/get_test.sh            # the one-liner: clone, pull, refusals, the hand-off to setup
sh tests/update_test.sh         # spark update: pull, move to a tag, dirty refused, --dry-run
```

`spark check` has 40 rows today: 12 SOFTWARE, 19 CAPABILITY, 9
NONFUNCTIONAL (`grep -c '^@row' lib/spark/check.py`). With `SITE_SHELL=off`
the 11 rows in `check.SHELL_ROWS` and the `shell` row answer `na`;
`--selftest` runs a third pass to prove it, a fourth for the client
shape (the 7 rows in `check.CLIENT_ROWS`), and on Linux a fifth under a
WSL 2 kernel line (the 3 rows in `check.WSL_ROWS` say so, never fail)
and a sixth under `ID=arch` (the 2 rows in `check.ARCH_ROWS` say so; the
packages row answers through a pacman stub).

## Releasing

The git tag is the release: one control, not two. There is no `VERSION`
constant -- `spark ver` derives it from git (`lib/spark/version.py`, cached:
`1.0` exactly at a tag, `1.0+3` three commits past it). Update `CREDITS.md`
when a pin or a model row changes.

1. Write the `## vX.Y` section at the top of `CHANGELOG.md` (bullets, newest
   first; until the tag exists the page renders that heading as
   `vX.Y (unreleased)`, and `tests/docs_test.py` refuses a heading more
   than one release ahead of the newest tag). The full gate, then `sh tests/install_test.sh`, `sh
   tests/get_test.sh` and `sh tests/update_test.sh`. Commit, push, `gh
   run watch` until green.
2. `git tag -a vX.Y -m 'spark vX.Y' && git push origin vX.Y`. The tag
   push runs `release.yml`, which checks the CHANGELOG heading and that
   `spark ver` says `spark X.Y` at the tag, then creates the GitHub
   Release with that CHANGELOG section as its notes; nothing is rerun.
3. Deploy = `spark update` everywhere: a main checkout pulls, a checkout
   on a tag moves to the new one; either way it converges (bootstrap.sh,
   then `spark check`, must both come back clean). `spark ver` there
   prints exactly `spark X.Y` at the tag, `spark X.Y+N` N commits past it
   on a developer clone (`main`, via `SPARK_REF=main`).

Author metadata (the name and e-mail on commits) is outside the privacy
gate: use the GitHub noreply address. The gate itself reads both the
tree (pre-commit) and the message (commit-msg) -- the history is as
public as the tree.

Re-derive every count in the docs before trusting it; counts go stale.
Follow every cross-reference; sections get deleted. Be most suspicious of a
sentence that explains *why* something works -- a wrong reason reads exactly
like a right one.
