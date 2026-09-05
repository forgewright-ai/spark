# spark -- maintainer's reference

AGENTS.md is the short form for agents and contributors; this file is
the full reference.

spark is a local AI at the shell prompt that never leaves your LAN, plus the
minimal workstation setup that keeps it reproducible and observable on a fresh
Debian-family Linux or macOS. spark is the seed; the FORGE is the agent it
builds and keeps on the box -- the model plus one soul, one memory and
threads, served on the LAN by `spark forge` -- one identity per box, the same
one for the prompt, the page and any program. This file is the reference for
anyone (human or agent) changing it. It describes how things are, not how
they came to be.

## Principles

- **Simple.** One command (`spark`), one bootstrap, one install script, one
  config format (`KEY=value`), python3 stdlib >= 3.9 or POSIX sh, nothing else.
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
  mechanism (apt/brew, systemd/launchd, bash/zsh). Nothing OS-only ships.
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
Brewfile        macOS packages (the Linux list is in bootstrap.sh)
site.env.example, models.env, embers.env,        KEY=value data
  community.env, themes/*.env
bin/spark, bin/explain -> spark                  the one command
lib/spark/      __init__ config wire engine serve session persona cli check
                verify (sha256, cached: spark model verify, check's models row) bar theme site
                setup (spark setup: the guided first run)
                stats (turns -> numbers) bench (llama-bench, --tune, tune apply)
                soul memory (the identity files) forge (identity, threads, reply, the chat REPL, @FILE)
                forgeserve (the FORGE server: spark forge, the API, the page) do (spark do)
                version (the version, from git, cached: spark ver, check's header, forgeserve)
                update (spark update: the newest tag, or main; converges)
                chacha (ChaCha20-Poly1305 written from RFC 8439, pinned to its
                vectors in tests/vault_test.py: the sealed stores' cipher)
lib/spark/forge/  index.html spark.css spark.js manifest.webmanifest favicon.svg
                  -- the page, ASCII, no inline script
home/           shared $HOME mirror (linked): micro bindings, the two widgets, the two rc hooks
                (.config/spark/hook.bash hook.zsh: PATH, the widget, the blank row, completion,
                the VT palette -- TERM=linux only -- and MICRO_TRUECOLOR),
                the two completion files (.config/spark/completion.bash completion.zsh:
                TAB completes the verbs and their names, offline), the banner, spark.env.example
linux/home/     .bashrc .bash_profile, the systemd user units (spark-serve spark-forge spark-check)
macos/home/     .zshrc .zprofile
templates/      rendered, not linked: .gitconfig .tmux.conf .config/btop/btop.conf
                .config/micro/colorschemes/spark.micro .config/micro/settings.json (seeded once)
                .config/starship.toml.{minimal,full} .config/spark/launchd/spark.{serve,forge,check}.plist
tests/          install_test.sh get_test.sh update_test.sh smoke.py serve_smoke.py
                forge_smoke.py bench_smoke.py widget_pty.py check_selftest.py
                vault_test.py (RFC 8439 vectors, round-trips, refusals)
.githooks/      pre-commit (privacy gate, syntax, tests, 80-col), pre-push (install test, selftest)
.github/        ci.yml: the same on ubuntu (plus a real bootstrap) and macOS (python 3.9)
                release.yml: the GitHub Release from the CHANGELOG section, on a v* tag
LICENSE         MIT, verbatim, ASCII (the hook checks it with the docs)
assets/         banner.svg -- the banner as rectangles, for the README and the site
CREDITS.md      every third-party project spark downloads or installs,
                with its license; spark's own code is LICENSE
ROADMAP.md      what comes after the current release, in order
```

Runtime paths: config `~/.config/spark/{site.env,spark.env,theme.env,
console-colors,soul,memory}` (`console-colors` is the precomputed Linux VT
palette -- `\033]P<n><rrggbb>` per ansi colour, `\033]R` after `none` --
written by `spark theme`/`spark setup` only, applied by the rc hooks only
when `TERM=linux`; `soul` and `memory` are prose, 0600, yours: never
linked from `home/`);
state `~/.local/state/spark/` (0700: `api-token` 0600, `serve-url`,
`serve.pid`, `serve.log`, `serve.lock`, `forge-token` 0600, `ember-token`
0600, `forge-url`, `forge.pid`, `forge.log`, `forge.lock`,
`router/` (`spark.gguf`, `ember.gguf`, `presets.ini` -- the router's
models dir, written by `spark serve`), `off`, `widgets/`, `turns/`,
`threads/` (0600 files), `chat-history` 0600, `brain`, `check.json`, `bar`,
`bench.jsonl`, `tune.json`); data `~/.local/share/spark/{engine,models}`;
tools linked into `~/.local/bin`.

## Contracts

These are the only interfaces between parts. Everything else is private and
may change freely.

1. `bootstrap.sh --list-packages` prints one package per line, after OS and
   site branching. `--list-tools` prints `repo-relative-path<TAB>name` per
   line. `--list-models` prints the model table with a RAM verdict per row
   and marks the chosen one; its header names the engine build this
   machine gets (`ai_build`: metal, vulkan or cpu) and, on a line of its
   own, what the speed cap held back, when it did. `--dry-run` prints rows `ok|would|skip|todo
   <what>  <why>` (`todo` = needs the user, e.g. a placeholder in site.env)
   and ends with `Nothing to do` or `N to do`; it never calls sudo. The
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
   up  <path>` and the same final line. Link = symlink into the repo; render
   = a regular file written from `templates/`. An existing regular file, or
   a symlink that points outside the repo, is moved to `<path>.bak`, never
   overwritten (a stale symlink into the repo is replaced). The rc files,
   micro's bindings and the shell templates (`.gitconfig`, `.tmux.conf`,
   btop, starship, micro's colorscheme and `settings.json`) are installed
   only with `SITE_SHELL=on`; micro's `settings.json` is seeded once and
   never re-rendered (micro rewrites it). `spark shell off` hands the
   rendered look back the way it hands the rc files back
   (`site.restore_rendered`): each of `.tmux.conf`,
   `.config/starship.toml`, btop's conf and the two micro files is
   restored from its `.bak` or removed -- never an empty husk;
   `.gitconfig` (identity, not look) and the core palette files under
   `~/.config/spark/` stay.
3. Config files are `KEY=value` lines; any other non-blank, non-comment line
   is refused by every reader (`^[A-Z_0-9]+=[^;`$()|&<>]*$`). Keys:
   `site.env` -- `SITE_NAME SITE_USER SITE_SET_HOSTNAME SITE_GIT_NAME
   SITE_GIT_EMAIL SITE_WORKSPACE SITE_PEER_AI_URL SITE_PEER_SSH SITE_THEME
   SITE_PROMPT SITE_PROMPT_STYLE SITE_AI_MODEL SITE_EMBER_MODEL SITE_AI_BUDGET
   SITE_AI_BUILD SITE_FONT_FACE
   SITE_FONT_SIZE SITE_QUIET_LOGIN SITE_QUIET_BOOT SITE_QUIET_START
   SITE_HEADLESS SITE_SHELL`;
   `spark.env` -- `SPARK_PORT SPARK_BASE_URL SPARK_PREFER_URL SPARK_SERVE_HOST
   SPARK_ENGINE_DIR SPARK_MODELS_DIR SPARK_MODEL SPARK_NGL SPARK_CTX
   SPARK_FLASH_ATTN SPARK_KV SPARK_THREADS SPARK_EXTRA_ARGS SPARK_MEM_NEEDED_GB
   SPARK_API_KEY_FILE SPARK_TIMEOUT SPARK_HISTORY SPARK_MEMORY SPARK_SERVICE
   SPARK_FORGE SPARK_FORGE_HOST SPARK_FORGE_PORT SPARK_FORGE_TOKEN_FILE`
   (`SPARK_PERSONA_EXTRA` is still read, as the soul's fallback, in this
   version only; the `soul` row warns while it is set);
   `models.env` (curated), `embers.env`, `community.env` and
   `~/.config/spark/models.env` (yours) -- `MODEL_<NAME>="<file> <url>
   <bytes> <sha256> <ram_gb>"`, plus `EMBER_<NAME>_PURPOSE` (required in
   embers.env) and `MODEL_<NAME>_LICENSE`/`MODEL_<NAME>_NOTE` (LICENSE
   required in community.env and yours; NOTE optional). A name in two
   files is refused, naming both;
   `themes/<name>.env` -- `THEME_BG THEME_FG THEME_ACCENT THEME_MUTED
   THEME_BTOP THEME_ANSI_0..15` (the same 21 keys in `lib/env.sh`
   `THEME_KEYS` and `config.theme_palette`: the two validators agree).
   Precedence: environment > file > default.
4. `spark line --cwd D --shell S` reads the prompt buffer on stdin and prints
   line 1 = `cmd<TAB>command` | `danger<TAB>command` | `answer` | `error`,
   line 2 = hint / answer / reason (<= 80 columns). Exit 0 for the first
   three, 1 for error. A buffer starting with `??` continues the newest
   thread; any other starts a new one (no heuristics). The shell widgets
   depend on nothing else.
5. `spark brain --porcelain` prints `<url><TAB><model><TAB>forge|model`
   (`<model>` is the spark role's model -- the file stem; `forge` when
   `/api/health` there says `forge: true`) and exits 0, or exits 1. This
   is the check's only AI probe.
6. A live widget writes `~/.local/state/spark/widgets/<pid>` containing
   `<shell> <pid> <epoch>` and removes it on shell exit.
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
9. The FORGE's HTTP API (`lib/spark/forgeserve.py`, on
   `SPARK_FORGE_HOST:SPARK_FORGE_PORT`, one LAN address, never `0.0.0.0`).
   `GET /api/health` answers without a token: `{status, forge: true, name,
   version, model, upstream, models, roles}` (`models` = `{role: loaded|
   unloaded}`, `roles` = `{role: model file stem}` per served role) -- the client's FORGE detector and the
   `forge` row's probe. `GET /`, `/login`, `/static/<f>`,
   `/manifest.webmanifest` and `/apple-touch-icon.png` (a 180x180 PNG the
   server draws) are the page, no token. Auth is two tokens, two roles: the forge-token is admin (the
   whole box), the ember-token is user. `POST /api/login` takes `{token}`,
   matches it against both, sets the cookie derived from the matching
   token and answers `{ok, name, role}` (1 s and 401 when wrong; 429
   after 10 wrong per minute from one address). Every other `/api/*` and
   `/v1/*` route needs the cookie or either token as a bearer, else 401;
   whichever token matched decides the role, per request. Admin-only:
   `GET` `/api/serve`, `/api/gpu`, `/api/bench`, `/api/config`,
   `/api/log` and `POST` `/api/run`, `/api/do/propose`, `/api/do/run`,
   `/api/check/refresh` -- a user there gets 403 `{error: {kind: role}}`;
   every other authed route is user-or-admin, and `GET /api/me` answers
   `{role, name, version}`, which is how the page decides which console
   to draw. Every `POST` and `DELETE` under `/api/` except `/api/login`
   also needs `X-Spark: 1`, a JSON object body, a `Host` this machine
   answers to and, when sent, an `Origin` matching it (400/403); `POST
   /v1/chat/completions` needs only the bearer or cookie. `GET
   /api/check` returns `check.json` as written plus `age` (seconds).
   `POST /api/do/propose` answers `{thread, reply, ms, driver,
   unchecked}` -- `driver` the ember role's model stem, `unchecked` the
   done hint's numbers no user message of the thread backs (`[]`
   otherwise).
   Streams are SSE: `/api/chat` (mode `chat|talk|ask`; `talk` is the old
   name for `chat` and records write `chat`) emits `queued` (when the model is busy),
   `delta {t}`, `done {thread, ms, model}`, `error {kind, hint}`; a
   client that hangs up mid-stream (the stop button) still lands the
   turn -- the user line and any partial answer (`partial: true`) go on
   the thread, and the log line says 499; `/api/run` emits
   `line {s}` then `done {rc}`; `/api/events` emits `check`, `bar`, `serve`
   on change (`log` too, for an admin) and a `:keepalive` comment every
   15 s. `/v1/chat/completions` and `/v1/models` are OpenAI-shaped and
   proxied to the llama-server with the api-token; the request's `model`
   field routes -- a missing `model` means `ember` -- and the identity
   (soul, memory) is injected into the system message only for an ember
   request, a `spark` request passing through untouched; JSON or SSE
   bytes come back as they are. Every `/api/*` answer is `Cache-Control:
   no-store`; the page is served with `Content-Security-Policy:
   default-src 'self'` and depends on nothing else. Errors are
   `{error: {kind, hint}}`.

## The grammar

One grammar for every verb; a verb that breaks a rule is a bug.

1. A bare verb shows; it never mutates. The one carve-out: `spark bar`
   with stdout not a tty still prints the bar line itself -- tmux's
   status-right runs `spark bar` and must always get the line, never a
   state change.
2. `on|off` is the only switch vocabulary at the CLI (shell, bar,
   headless, forge, quiet, memory). Stored values are storage, not
   interface: `SITE_HEADLESS` and the `SITE_QUIET_*` keys stay `yes|no`
   in `site.env`; the verb translates. Choices keep their value grammars
   (`theme NAME|none`, `model NAME|auto|none`, `client URL|off`).
3. `status` is an alias of bare for every stateful verb; `list` is the
   table word (theme, model, ember, font).
4. Every verb answers `-h|--help|help` first -- before any gate or
   config read -- signed per contract 8.
5. One confirm shape: `<question>? yes/NO: ` -- only `y` or `yes`
   proceeds; Enter or EOF is no (`confirm()` in `lib/spark/__init__.py`,
   beside `say()`). The one deliberate second shape: `spark do`'s danger
   step requires the typed word `yes`.
6. One progress vocabulary: curl's bar for downloads, and one
   dot-spinner -- `wait_ready(label, probe, timeout, interval)` in
   `lib/spark/__init__.py` -- for every wait on a server coming up.
7. Exit codes: 0 ok or show; 1 the world failed (stderr, via `die()`);
   2 the invocation -- usage, an unknown name, a gate refusal (stdout,
   signed); 78 misconfiguration (`EX_CONFIG`); 130 SIGINT.

## Adding things

- **A package.** Linux: the right `PKG_*` group in `bootstrap.sh` with a
  comment saying why (`PKG_CORE`/`PKG_ENGINE`/`PKG_AI` are the AI, always
  installed; the rest is the shell layer, `SITE_SHELL=on`). macOS:
  `Brewfile`, same comment -- the whole Brewfile is the shell layer; the AI
  needs nothing from Homebrew. The `packages` row reads both; nothing else
  to update.
- **A config file.** First ask whether the app *rewrites* its own config.
  If it only reads: put it in `home/` (shared) or `<os>/home/`; `install.sh`
  links it. If it rewrites: it cannot be linked -- seed it once from
  `templates/` as a rendered regular file, and note it in INSTALL.md's trap
  table (under "The shell layer"). Test by changing a setting in the app and running `ls -l` on the
  path: still a symlink, or now a regular file?
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
- **A check row.** A function `row_<name>(ctx)` in `lib/spark/check.py`
  decorated `@row(CATEGORY, fixture=True)` or `@row(CATEGORY, fixture=False,
  reason="...")`. If it is fixture-testable, extend `make_fixture` so the row
  is ok in the good fixture and not ok in the bad one; `--selftest` refuses
  otherwise. CAPABILITY rows use `warn`/`na`, never `fail`, so `spark
  check`'s exit code keeps meaning "something reproducible is broken".
- **A prose data file.** The soul and the memory are the pattern:
  user-owned text under `~/.config/spark/`, never linked from `home/`,
  written 0600 by a `spark` verb (and by the page through the same code),
  capped (`SOUL_MAX`, `FACT_MAX`/`FACTS_MAX`/`TOTAL_MAX`), sent to the brain
  on every request, and reported by its own check row (mode, size, cap).
  It is config, not state: pruning and `history clear` never touch it.
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
  that. `spark shell on|off` (`site.cmd_shell`, `site.SHELL_ROWS`) is the
  only switch; `spark shell off` hands back what the layer rendered
  (`restore_rc`, `restore_rendered`: `.bak` or gone, never a husk).
  `spark theme` and `spark font` stay outside the gate (the FORGE page
  reads `theme.env`, the VT console palette and font are the machine's
  face with the layer off too); their `theme` and `font` check rows are
  core for the same reason -- only the Nerd Font piece of `font` waits
  for the layer.
- **The client shape.** `SITE_AI_MODEL=none` beside `SITE_PEER_AI_URL`
  (`config.client`; `spark client URL|off`, `site.cmd_client`) means
  nothing runs here: bootstrap skips the `engine` and `services` rows
  (`$client`), `install.sh` links no unit and renders no plist, and the
  rows in `check.CLIENT_ROWS` (engine, services, watchdog, ai, serve,
  forge) read `na`;
  `--selftest`'s fourth pass asserts that with the peer row ok. The peer
  row is where a client's health lives.
- **A model.** Three lists, by what it is:
  - Curated (`models.env`, the only source `auto` reads): an open
    license, proven on the line -- size and sha256 from the file's LFS
    metadata, then watch it answer `spark line` with valid JSON.
  - An ember (`embers.env`, `spark ember list`): an open license, plus
    `EMBER_<NAME>_PURPOSE` (one line) and `MODEL_<NAME>_LICENSE`.
  - Community (`community.env`, untested, at your own risk): any license,
    named in `MODEL_<NAME>_LICENSE`; `MODEL_<NAME>_NOTE` is optional.
  A name already in another list (including
  `~/.config/spark/models.env`, yours) is refused, naming both files
  (`config.model_tables`, `bootstrap.sh model_rows_all`). `spark model add
  URL` writes your row for you: huggingface.co is auto-verified from its
  LFS headers, any other host needs `--sha256`; `--license "NAME URL"` is
  always required there. `spark model verify` (and the `models` check
  row, cached) re-hashes every downloaded file (`lib/spark/verify.py`).
- **A palette.** Two files, nothing else hand-listed: `themes/<name>.env`
  with the full 21-key `THEME_*` set (contract 3; the header comment names
  the upstream project and its license; `THEME_BTOP` names a theme btop
  ships, else `Default`), and its flat 20-value row in `spark.js`'s
  `theme.builtin` map (the page has no build step). `tests/install_test.sh`
  renders every palette by glob, and `tests/smoke.py` asserts the
  `theme.builtin` map matches `themes/*.env` value for value -- a gap in
  either goes loud.

## Verifying a claim

```sh
./bootstrap.sh --dry-run        # must end with: Nothing to do
spark check                     # must exit 0
spark check --selftest          # every fixture-testable row flips
spark forge                     # the FORGE: up, at one LAN address, upstream ok
python3 tests/forge_smoke.py    # the API and the page, against a stub model
python3 tests/widget_pty.py pager        # $PAGER at a tty; plain when absent
python3 tests/widget_pty.py completion zsh home/.config/spark/completion.zsh
                                # TAB completes verbs and names (bash likewise)
git status -sb                  # clean, not ahead of origin
spark check --porcelain | grep privacy   # the tree contains no banned word
sh tests/get_test.sh            # the one-liner: clone, pull, refusals, the hand-off to setup
sh tests/update_test.sh         # spark update: pull, move to a tag, dirty refused, --dry-run
```

`spark check` has 36 rows today: 12 SOFTWARE, 16 CAPABILITY, 8
NONFUNCTIONAL (`grep -c '^@row' lib/spark/check.py`). With `SITE_SHELL=off`
the 11 rows in `check.SHELL_ROWS` and the `shell` row answer `na`;
`--selftest` runs a third pass to prove it, and a fourth for the client
shape (the 6 rows in `check.CLIENT_ROWS`).

## Releasing

The git tag is the release: one control, not two. There is no `VERSION`
constant -- `spark ver` derives it from git (`lib/spark/version.py`, cached:
`1.0` exactly at a tag, `1.0+3` three commits past it). Update `CREDITS.md`
when a pin or a model row changes.

1. Write the `## vX.Y` section at the top of `CHANGELOG.md` (prose, newest
   first). The full gate, then `sh tests/install_test.sh`, `sh
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
gate, which reads the tree, not the log: use the GitHub noreply address.

Re-derive every count in the docs before trusting it; counts go stale.
Follow every cross-reference; sections get deleted. Be most suspicious of a
sentence that explains *why* something works -- a wrong reason reads exactly
like a right one.
