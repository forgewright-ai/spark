# spark -- maintainer's reference

`AGENTS.md` is the short brief for agents and contributors. This file is
the full reference. It describes how things are, not how they came to
be.

spark is a local AI at the shell prompt that never leaves your LAN. It
runs on a fresh Debian-family, Arch or Void Linux, on macOS, and on
Ubuntu under WSL 2. Its spine is 3 lines. Choose your OS, run one line,
spark is live. A tool becomes a spark app as a client of `spark edit`
(contract 10), in its own `spark-<app>` repository. When apps ask for
it, another contract is defined and apps connect the same way. Inside,
the `FORGE` is the identity spark builds and keeps on this machine: the
model, one soul, one memory and the threads, served on the LAN by
`spark forge`. It is one identity per machine, the same one for the
prompt line, the page and any program.

## Principles

- **Simple.** One command (`spark`), one bootstrap, one install script,
  one config format (`KEY=value`). The code is python3 stdlib, 3.9 or
  newer, and `sh`. Nothing else.
- **The spine, one command.** spark is the engine, the model, chat, the
  `?` prompt line, the `FORGE` and users. It is always installed: one rc
  line, and nothing else touched. A spark app is a client of one spark
  surface. The surfaces are text on stdin (`spark edit`, contract 10,
  and `spark line`, contract 4), the shell (`? words`, `spark do`,
  `explain`, `$EDITOR`) and the `FORGE` API (contract 9). Its plugin
  lives in its own repository, named `spark-<app>`, installed the app's
  way. micro came first: forgewright-ai/spark-micro. spark ships no app,
  no app package, no app check row and no per-app verb. The look and the
  daily tools of a machine are not spark's business. spark's side is
  generic: `~/.config/spark/theme.env` is a palette any renderer may
  read, and no shell code lives in this tree. The bar line and `spark
  quiet` are core, beside `spark headless`: the behaviour of an AI
  appliance.
- **The `FORGE`.** spark is the small model at the prompt line. The chat
  model is the larger one for conversations. The `FORGE` serves both
  with one identity per machine, `soul` and `memory`. Every client talks
  to the same `FORGE`: the prompt line here, a laptop's `spark`, a
  script, a phone. The prompt line is only the first line of
  interaction. The `FORGE` is found, never assumed: `/api/health` says
  `forge: true`.
- **Privacy by design.** Nothing leaves the machine except the package
  managers, pinned sha256-verified downloads, and `spark` talking to a
  `FORGE` or a llama-server you run. Identity lives in
  `~/.config/spark/site.env`, never in the repository. The soul is
  yours, under `~/.config/spark/`. The memory is yours, sealed in your
  store. Secrets are 0600 files, never config values. The words in
  `.privacy-terms` appear nowhere in this repository, and the pre-commit
  hook enforces it. The personal words are not published either. They
  live in `~/.config/spark/privacy-terms` (or `SPARK_PRIVACY_TERMS`),
  0600, one per line. The hook and the `privacy` row read the union of
  both lists.
- **Two paces.** A conversation can be paced for the reader. The prompt
  line is speed alone. Where you read a reply as it comes (chat,
  explain, a bare question), spark measures what the model writes. The
  measure is the newest turns' tokens a second and characters a token
  (`reveal.measured`). It offers the threshold a reveal stays under, so
  the hand never waits and never bursts: `reveal.auto_cps`, 85% of the
  measured pace, a reader's 40 a second at most. `spark stats` and a
  bare `/reveal` show the numbers. The choice is the reader's, never
  imposed: `--reveal N|auto|off`, `/reveal`, `SPARK_REVEAL`. Off is the
  default, the chunks as they come. Where you type commands (the
  widget's line, `spark do`'s steps) nothing is paced. Piped, nothing is
  paced anywhere.
- **Text-first.** Plain text that pipes, `--porcelain` for programs, no
  curses, keyboard only. Long output pages at a terminal (`$PAGER`, else
  `less`) and is plain when piped: `page()` and `paged()` in
  `lib/spark/__init__.py`. Every character spark prints draws on the
  Linux console. The mark is the word `spark`. The answer and warn marks
  are `*` and `!` on every OS and terminal. On the console, inside a
  tmux running on it, or with `SPARK_ASCII=1`, the report and bar glyphs
  fall back to `+ x - | v ^ ->`. The docs are ASCII too, and the hook
  refuses anything else: they are read on that console as well. Colour
  is never spark's own. It comes at a terminal only, from 3 optional
  environment variables an rc may export: `SPARK_ACCENT_SGR`,
  `SPARK_MUTED_SGR` and `SPARK_WARN_SGR`, SGR parameter strings. `sgr()`
  and `paint()` in `lib/spark/__init__.py` keep to 30-37 and 90-97 plus
  bold and dim. A `38;5` or 24-bit value is dropped whole. A pipe never
  sees an escape. Unset, every output is byte for byte what it was. An
  input() prompt (`chat> `) is painted only under GNU readline,
  bracketed in `\001` and `\002`. libedit counts the escape bytes as
  columns, so there it stays plain. Every animation frame is ASCII:
  `text.Busy`, the pulse while a reply is on its way. A reply's Markdown
  is drawn at a terminal, never stripped blind. `text.Wrap` renders
  `**bold**` as bold and a `# heading` line as bold. It drops the `*`
  marks of an emphasis only when they flank a word: a letter after an
  opening mark and none before it, the reverse to close. So `*.txt`,
  `**/`, `2*3*4` and `_names_` pass through. A ``` fence opens a block
  that passes through whole until the closing fence. Piped, the bytes
  are the model's. Text in is strict UTF-8 as well. stdin is decoded
  with the replacement mark (`text.stdin_text`). Every string bound for
  the wire or a store goes through `text.clean` first: a thread, the
  ledger, a turn record. A lone surrogate is an HTTP 500 from the
  engine's JSON parser and a crash at a store's strict encode.
  surrogateescape keeps one for a byte that was not UTF-8 in argv or the
  environment under the C locale. A w3m page title on the box was one.
- **Symmetric.** Every feature exists on both OSes, through each OS's
  native mechanism: apt, pacman or xbps for the packages, systemd,
  launchd or runit for the services, bash or zsh for the shell.
  Nothing OS-only ships. A Linux package family is one oracle beside
  `is_wsl()`: `distro()` reads `ID`, then `ID_LIKE`, from os-release,
  and `SPARK_OS_RELEASE` pins it. Its names are one data file,
  `distro/<id>.env`. The verbs that ask a package manager switch once on
  `PM`: bootstrap's `pkg_*` and `lib/spark/packages.py`. The init is
  one oracle too, `init_shape()` beside `distro()`: launchd on macOS,
  runit when `/etc/runit` is a directory, else systemd. On runit the 3
  services are directories under `~/.config/spark/sv/`, rendered by
  `install.sh`. A root `runsvdir-USER` service, written once by
  bootstrap and linked into `/var/service`, supervises them from boot.
  The engine pin is a glibc build, so Void's musl flavour refuses at
  `get`: `musl libc: the pinned engine is a glibc build -- Void's glibc
  flavour runs spark`. What a family lacks refuses in one signed line,
  and its rows say so, never fail (`check.ARCH_ROWS` and
  `check.VOID_ROWS`, the fifth and sixth selftest passes). Windows is
  reached through WSL 2. Ubuntu there is Linux to spark, minus what the
  VT console and the boot loader own. `is_wsl()` sits beside
  `os_pretty`, the verbs that own those refuse in one signed line, and
  their rows say so, never fail. CI has no WSL runner: `check.WSL_ROWS`
  and the fourth selftest pass pin the branch by fixture. A real run
  there is the maintainer's, by hand.
- **The OS is the harness.** An agent's harness is its tools, its
  permissions, its context, its triggers and its memory. spark brings
  only the last. The tools are the programs on PATH and their man pages:
  a step refused for an option brings back its own page's lines. The
  permissions are the kernel's sandbox (bubblewrap's namespaces and
  no_new_privs, `sandbox-exec` on macOS) and the user's Enter or `yes`.
  The context is the shell: the directory, the exit code, the output.
  The triggers are the OS's own timers starting `spark do --sandbox
  --detach`: a systemd user timer, launchd, cron, a `spark watch` line.
  The memory and the audit are the `FORGE`'s sealed threads. No tool
  schema rides a request: a small model's context holds the task, not
  the harness.
- **The user chooses.** Theme, prompt, model, machine name, user: all
  `site.env` keys with defaults. Nothing aesthetic or sized to hardware
  is baked in.

## The four obligations

Every change lands in 4 places, or it is not done:

| # | obligation | where |
|---|---|---|
| 1 | apply | the live machine |
| 2 | reproduce | `bootstrap.sh` / `install.sh` / `templates/` / `home/` |
| 3 | detect | a row in `spark check` (`lib/spark/check.py`), fixture-tested by `--selftest` |
| 4 | explain | `README.md` / `docs/INSTALL.md` / `docs/CHEATSHEET.txt` / `docs/CHANGELOG.md` / this file |

Then commit and push. `spark check` has a `git` row that warns while the
working tree is dirty or ahead of origin.

Skipping the third is the expensive one. A capability nobody checks is
one you discover broken by needing it. A check that has only ever
returned one answer has never been tested. Break the thing on purpose,
watch the row go red, put it back. `--selftest` automates this for
every row that can be fixture-tested. The rest are listed as untestable
with the reason.

## Layout

```
get             POSIX sh, both OSes: the one-liner. Clone (or pull) ~/.spark, exec spark setup
allowed-signers the release keys, ssh allowed-signers form -- one line per key,
                `spark-release namespaces="git" <keytype> <base64>`, never a
                real name: get, spark update and release.yml move to a
                tag only when a key here signed it
bootstrap.sh    POSIX sh, both OSes. --dry-run --list-packages --list-tools --list-models
install.sh      POSIX sh, both OSes. Links home/ + <os>/home/ into $HOME; renders templates/
lib/env.sh      the KEY=value reader for the two scripts (config.py is the python twin)
distro/         one KEY=value file per Linux package family (debian.env, arch.env,
                void.env): the manager, its install line, the doc's name, the 3
                package groups
site.env.example, models.env, engine.env, themes/*.env       KEY=value data
                (engine.env is the llama.cpp pin: version + one sha per flavour)
bin/spark, bin/explain -> spark                  the one command
lib/spark/      __init__ config wire engine serve session persona cli check
                verify (sha256, cached: spark model verify, check's models row)
                bar (the status line) theme
                site (site.env custodian: set_keys/apply, rc custody, font quiet
                headless client share)
                model (spark model / spark ember: the table, add, verify, budget)
                edit (spark edit: contract 10)
                facts (the machine's decisions as KEY=value for bootstrap's eval:
                distro, build, WSL, memory, engine home + flavour, model picks)
                packages (the family's names from distro/<id>.env, the manager's
                questions, switched once)
                sbom (spark ver --sbom: what the tree depends on, as CycloneDX
                1.5 JSON; the release's sbom.cdx.json)
                chaos (spark check --chaos: the rehearsed failures on a throwaway
                machine; a llama-server with a mood, as a real process)
                setup (spark setup: the guided first run)
                stats (turns -> numbers; --sends: bytes out by destination and day)
                bench (llama-bench, bench tune [show|apply])
                soul memory (the identity files; memory's writers refuse a
                sealed file that does not open, never write over it)
                text (the streams: wrap, fence, Busy; the grounding law: anchor,
                Ground, Gate, shared by every contract that shows a text to a
                model; what a source holds back: SECRET_SHAPES, SOURCE_SHAPES,
                hold_secrets)
                ledger (what you have already weighed: one sealed file, a kind
                per contract, the retiring rule the contract's own; a writer
                refuses a file that does not open; the plain state/fails index
                it writes carries `NAME=...` where NAME smells of a secret)
                ask (spark ask: contract 12) read (spark read: contract 11)
                drill (spark drill: contract 13) watch (spark watch: contract 14)
                reveal (spark reveal: stdin at a reader's pace at a terminal, an exact
                copy piped; the same pace inside the streaming verbs: `--reveal
                [CPS]` on chat, explain and bare words, `/reveal` in chat --
                `text.Wrap(cps=)`, `cli.reveal_flag`)
                forge (identity, threads, reply, the chat loop, @FILE; the
                chat-history save skips a sealed file that does not open)
                forgeserve (the page's server: spark forge, the API, the page;
                ROUTES is the one table of every route and its role)
                do (spark do: the one loop, a face per driver -- the terminal,
                --porcelain (contract 15) -- the budget, the hold, the man excerpt)
                sandbox (spark do --sandbox: the probe, the copy the kernel keeps
                the steps inside, the review, the apply bound to it, a run's
                life and its lock; every list that decides is a named line)
                audit (the sealed audit trail: one record per admin action in
                the box account's store, numbers and names only; spark forge
                audit [N] reads it)
                version (the version, from git, cached: spark ver, check's
                header, forgeserve)
                update (spark update: the newest release tag signed by a key in
                allowed-signers, or main; converges; `verified` is the one
                signature check, check's signed row reuses it)
                uninstall (spark uninstall: the plan, the word yes, then
                everything spark made goes; yours stays unless --purge; the
                clone last)
                chacha (ChaCha20-Poly1305 written from RFC 8439, pinned to its
                vectors in tests/vault_test.py: the sealed stores' cipher)
                qr (a QR encoder from ISO/IEC 18004, versions 1-5, pinned to the
                spec in tests/qr_test.py: the login link, scannable at a terminal)
                vault (the sealed-file format and the key custody: a per-user
                data key wrapped by the token; an append holds an existing file
                to the caller's header first, so a foreign file takes no record)
                users (the named users, their store under state/users/, and
                this machine's login: spark user)
lib/spark/forge/  index.html spark.css spark.js manifest.webmanifest favicon.svg
                  mark.svg -- the page, ASCII, no inline script
home/           the shared $HOME mirror, linked. .config/spark/ holds the two
                widgets (widget.bash widget.zsh), the two rc hooks (hook.bash
                hook.zsh: PATH, the widget, the blank row, completion, the VT
                palette -- TERM=linux only), the two completion files
                (completion.bash completion.zsh: TAB completes the verbs and
                their names, offline), the banner, spark.env.example and tale
                (a text of the maintainer's own, credited in CREDITS.md)
linux/home/     the systemd user units (.config/systemd/user: spark-serve spark-forge
                spark-check.service + spark-check.timer)
templates/      rendered, not linked: .config/spark/launchd/spark.{serve,forge,check}.plist
                (the 3 launchd agents); .config/spark/sv/spark-{serve,forge,check}/
                (the 3 runit service directories: run, finish, log/run; rendered
                only where /etc/runit is a directory)
tests/          smoke.py serve_smoke.py forge_smoke.py bench_smoke.py
                policy_test.py (every row of forgeserve.ROUTES with 3
                callers: nobody, a user, the admin)
                vault_test.py (RFC 8439 vectors, round-trips, refusals)
                sandbox_test.py (the review, every named apply refusal, a run's
                life and its lock, and the real escapes where the probe says
                this machine has a sandbox)
                qr_test.py (ISO 18004 format table, the RS vector, a decode-back)
                docs_test.py (the docs say what the tree holds: credits, counts,
                the voice)
                widget_pty.py (the widgets, the pager and completion at a pty)
                check_selftest.py (a standalone entry to spark check --selftest)
                install_test.sh get_test.sh update_test.sh uninstall_test.sh
                audition.py + audition/ (the editor's briefs against a live
                model, lints as the judge; audition/ground/ holds the grounded
                contracts' set of 10 cases, scored the same blind way, the
                score written by hand as MODEL_<NAME>_GROUND; not in the gate)
                forge_probe.py URL (the page's server's gates asked from the wire --
                wire.probe_gates, the hardening row's probes -- one line per
                gate, exit 1 when any does not hold; against a real server)
.githooks/      pre-commit (the privacy gate, syntax one file per call, the
                hermetic suites, the widget pty tests, the selftest, the
                cheatsheet's 80 columns, ASCII, shellcheck), commit-msg (the
                privacy patterns over the message -- history is public too),
                pre-push (the install, get, update and uninstall tests, the
                selftest, chaos)
.github/        workflows/ci.yml: linux and macos run the hermetic tests, then
                a real bootstrap; debian, arch and void containers run the
                one-liner as a new user (void under a runsvdir started for the
                job: the supervised spark-check is proven there); workflows
                runs zizmor over the workflows
                workflows/release.yml: the GitHub Release from the CHANGELOG
                section, on a signed v* tag
                workflows/codeql.yml: GitHub's static analysis over the python
                and the javascript, on a push to main, a pull request and weekly
                workflows/advisories.yml: weekly, one issue when llama.cpp
                published a security advisory after the engine pin's date
                dependabot.yml: the workflows' action sha pins, kept current weekly
                PULL_REQUEST_TEMPLATE.md, ISSUE_TEMPLATE/bug.md and model-row.md
LICENSE         MIT, verbatim, ASCII (the hook checks it with the docs)
assets/         banner.svg -- the banner as rectangles, for the README and the project site
                (banner-light.svg is the site's light-theme variant; the site reads
                both from this tree at the newest release tag);
                banner-svg.py makes both from home/.config/spark/banner; icon-svg.py
                makes the favicon, the app icons and the social card the same way
CREDITS.md      every third-party project spark downloads or installs,
                with its license; spark's own code is LICENSE
docs/           every document but the 4 at the root. With a release (the
                landing rule): INSTALL.md (every step and every key),
                CHEATSHEET.txt (one page, 80 columns, what `lp` prints),
                CHANGELOG.md (release.yml reads its top section as the notes),
                ROADMAP.md (what comes after the current release, in order),
                CONTRIBUTING.md (how a change lands, and the voice). Beside the
                core -- outside the landing rule, kept true continuously, not
                tied to a release, each saying so in its first lines: TOUR.md
                (a first hour: 12 small things to try), APPS.md (the apps
                and how each one connects), IDEAS.md (the field ROADMAP.md is
                picked from), TROUBLESHOOTING.md (a machine that will not join
                the Wi-Fi: one Wi-Fi daemon per card, then the logs)
```

Runtime paths. Config is `~/.config/spark/`: `site.env`, `spark.env`,
`theme.env`, `models.env` (yours), `themes/<name>.env` (yours),
`privacy-terms`, `console-colors`, `console-colors.rgb`, `soul` and
`memory` (the pre-v1.4 facts file, read until the first write).
`console-colors` is the precomputed Linux VT palette: one
`\033]P<n><rrggbb>` per ansi colour, the 16 VGA values after
`none`, never `\033]R`, because the kernel's defaults may be a theme.
`spark theme` and `spark setup` alone write it. `theme.apply_console`
sends it to a running VT and then redraws, because a framebuffer paints
a palette only into cells drawn after it. The rc hooks send it at
login, `TERM=linux` only. `console-colors.rgb` is the same palette in
`setvtrgb`'s three-line form, for root at boot. Bootstrap's
`vt-palette` row installs the one-shot `spark-console.service`, which
sets the kernel's defaults so the login screen and every VT wear it
before any shell runs. The `theme` row compares that file with
`/sys/module/vt/parameters`. `SPARK_SYSFS_VT` pins it in the fixture.
`soul` is prose, 0600, yours, never linked from `home/`. `memory`
there is the pre-v1.4 fallback: the facts live sealed in your store
since v1.4, and the file is read until the first write.

State is `~/.local/state/spark/`, 0700:

- `api-token` 0600, `serve-url`, `serve.pid`, `serve.log`, `serve.lock`.
- `forge-token` 0600, `ember-token` 0600, `forge-url`, `forge.pid`,
  `forge.log`, `forge.lock`.
- `router/` (`spark.gguf`, `ember.gguf`, `presets.ini`): the router's
  models dir, written by `spark serve`.
- `off`, `widgets/`, `turns/`, `chat-history` 0600, `brain`,
  `check.json`, `bar`, `bench.jsonl`, `tune.json`.
- `threads/`: pre-v1.4 plaintext threads only. `spark user claim` seals
  them away.
- `runs/<id>/` 0700: a sandboxed run. `meta.json` 0600 holds numbers and
  names only. `lock` is the flock its driver or a `--review`, `--accept`
  or `--discard` holds. `up/` and `wk/` are the overlay's on Linux.
  `clone/`, `manifest.json`, `home/`, `tmp/` and `profile.sb` are
  macOS's. The dir is removed whole once the run is applied or
  discarded. `runs/.lock` serialises a new run's count and mkdir.
  `runs/detach.lock` is the one detached run's flock.
- `sandbox/probe.json`: the probe's answer, keyed by the bwrap version,
  the kernel and the AppArmor userns switch.
- `users/<name>/` 0700 per user: `token.hash` and `key` 0600 (the sha256
  token verifier and the wrapped data key), plus that user's sealed
  `threads/`, `memory`, `chat-history` and `ledger`. The box account's
  store holds `audit` too, the admin actions.
- `account` 0600, this machine's login (name and token), and
  `account-key` 0600, the unwrapped data key, so the hot paths never pay
  the KDF.

Data is `~/.local/share/spark/{engine,models}`. Tools are linked into
`~/.local/bin`. `spark uninstall` (`lib/spark/uninstall.py`) removes
all of it but the sealed stores, the account keys and your prose.
`--purge` takes those too. It runs bootstrap once first, with headless
and quiet undone through their rows, and never `site.apply` or
`check.refresh` after: each would put things back. Root steps become
`todo` rows when sudo refuses. The clone goes last, only when it is
`${SPARK_HOME:-~/.spark}` and clean.

## Contracts

These are the only interfaces between parts. Everything else is private
and may change freely.

1. `bootstrap.sh --list-packages` prints one package per line, after OS
   and site branching. `--list-tools` prints
   `repo-relative-path<TAB>name` per line. `--list-models` prints the
   model table with a RAM fit per row and marks the chosen one. Its
   header names the engine build this machine gets: `engine.backend`,
   metal, vulkan or cpu. Bootstrap evals every such decision from
   `lib/spark/facts.py`. A line of its own says what the speed cap held
   back, when it did. `--fetch URL DEST SHA` runs the download primitive
   alone: download, verify sha256, or die having removed its own partial
   file. `spark check --chaos` rehearses that. Nothing else calls it.
   `--dry-run` prints rows `ok|would|skip|todo <what>  <why>` and ends
   with `Nothing to do` or `N to do`. A `todo` needs the user, such as a
   placeholder in site.env. `--dry-run` never calls sudo. An apply run
   prints only what it changed and what needs the user. Its `ok` and
   `skip` rows and its section headers are silent unless `--verbose`,
   because a converged machine has nothing to report. `--dry-run` stays
   the full report: `spark check`'s configs row and
   `tests/install_test.sh` read those rows. An apply run that will need
   root asks for sudo once, before it touches anything (`sudo_upfront`),
   and only at a terminal. Over ssh or a pipe there is nobody to answer,
   and a run needing no root, such as `spark update` on a converged
   machine, must not be made to ask. No sudo on the machine at all is
   one line and exit 1, up front. The `rc` row appends one marked line
   (marker `config/spark/hook.`) to the end of the login shell's rc
   file: `~/.bashrc` or `~/.zshrc`, by `$SHELL`, else the passwd entry.
   It creates the file if absent and never truncates it. A symlinked rc
   file is treated like any other file: the marker looked for, the line
   appended. Another shell, or a bash older than 4, is a `todo` naming
   the fix. On bash, a regular `~/.bash_profile` that neither sources
   `~/.bashrc` nor holds the marker shadows the hook on a console login.
   The `rc-login` row appends the same marked line there. One hand-back
   row covers what older sparks made. The `micro` row removes the plugin
   links a pre-v1.10 install left under `~/.config/micro` and names the
   app's own repository.
2. `install.sh --dry-run` prints rows `ok|would link|would render|would
   back up  <path>` and the same final line. Apply is quiet the same
   way: an `ok` row, already in place, prints only with `--verbose`.
   Link is a symlink into the repository. Render is a regular file
   written from `templates/`, the launchd plists. An existing regular
   file, or a symlink that points outside the repository, moves to
   `<path>.bak`, never overwritten. A stale symlink into the repository
   is replaced. The rc file is contract 1's.
3. Config files are `KEY=value` lines. Every reader refuses any other
   non-blank, non-comment line (``^[A-Z_0-9]+=[^;`$()|&<>]*$``). The
   keys:
   - `site.env`: `SITE_NAME SITE_USER SITE_SET_HOSTNAME SITE_PEER_AI_URL
     SITE_PEER_SSH SITE_THEME SITE_AI_MODEL SITE_EMBER_MODEL
     SITE_AI_BUDGET SITE_AI_BUILD SITE_FONT_FACE SITE_FONT_SIZE
     SITE_QUIET_LOGIN SITE_QUIET_BOOT SITE_QUIET_START SITE_QUIET_AUDIO
     SITE_HEADLESS SITE_SHARE`.
   - `spark.env`: `SPARK_PORT SPARK_BASE_URL SPARK_PREFER_URL
     SPARK_SERVE_HOST SPARK_ENGINE_DIR SPARK_MODELS_DIR SPARK_MODEL
     SPARK_NGL SPARK_CTX SPARK_FLASH_ATTN SPARK_KV SPARK_THREADS
     SPARK_EXTRA_ARGS SPARK_MEM_NEEDED_GB SPARK_API_KEY_FILE
     SPARK_TIMEOUT SPARK_MAX_TOKENS SPARK_REVEAL SPARK_HISTORY
     SPARK_MEMORY SPARK_SERVICE SPARK_FORGE SPARK_FORGE_HOST
     SPARK_FORGE_PORT SPARK_FORGE_TOKEN_FILE`. `SPARK_REVEAL_CPS` is
     optional: the reveal pace in characters a second (`spark reveal`).
     `SPARK_PERSONA_EXTRA` is still read as the soul's fallback, and the
     `soul` row warns while it is set.
   - `models.env`, and `~/.config/spark/models.env` for your own rows:
     `MODEL_<NAME>="<file> <url> <bytes> <sha256> <ram_gb>"`, with
     `MODEL_<NAME>_LICENSE="<name> <url>"` on every row.
     `MODEL_<NAME>_TESTED="line"` marks a row proven on `spark line`.
     With an open license (`config.OPEN_LICENSES`: Apache-2.0 or MIT) it
     is a row `auto` may pick. `MODEL_<NAME>_NOTE` is one optional line.
     `MODEL_<NAME>_GROUND="<kept>/<run> <YYYY-MM-DD>"` is the grounding
     audition's score, written by hand from a `tests/audition.py --json`
     run, the way `_TESTED` carries the line proof. `spark model list`
     shows it in the proof column and spark.forgewright.ai/models/
     renders it. `auto` prefers a grounded row when two rows fit the
     budget at the same RAM, and among equals the earlier row of the
     list. A name in both files is refused, naming both.
   - `distro/<id>.env`, one per Linux package family the oracle
     `distro()` knows (`debian`, `arch`, `void`): `PM PM_INSTALL
     PM_TARGET PKG_CORE PKG_ENGINE PKG_AI`, the same 6 keys in every
     file (`packages.KEYS`, and `tests/docs_test.py` asserts it).
     `distro()` lives in `lib/spark/__init__.py` beside `is_wsl()`,
     bootstrap.sh evals it from `lib/spark/facts.py`, and
     `SPARK_OS_RELEASE` pins it. `init_shape()` sits beside it, and
     `SPARK_ETC_RUNIT` and `SPARK_VAR_SERVICE` pin the runit answer.
   - `themes/<name>.env`: `THEME_BG THEME_FG THEME_ACCENT THEME_MUTED
     THEME_ANSI_0..15`, the same 20 keys in `config.theme_palette` and
     the `theme` row's `check.THEME_KEYS`.
     `~/.config/spark/themes/<name>.env` is yours, the same keys, and
     wins on a name clash (`config.theme_path`). `THEME_LOGO` is
     optional in either: 6 colour names, one per banner row, `bright-`
     allowed. `spark ver` draws the logo in them (`cli.recolour`).
     Unset, the logo keeps its own. It rides in `theme.env` with the
     rest when present.
   Precedence: environment, then file, then default.
4. `spark line --cwd D --shell S` reads the prompt buffer on stdin and
   prints two lines. Line 1 is `cmd<TAB>command`, `danger<TAB>command`,
   `answer` or `error`. Line 2 is the hint, the answer or the reason:
   one line, cut at a word to a character budget. A hint or a reason is
   80 at most, an answer `cli.ANSWER_MAX`. Line 1 is written the moment
   the command is complete, and lines 2 and 3 follow; after line 1, a
   failure makes line 2 its reason and exits 1. A `danger` line's hint may
   open with `<- <facts> -- `: `persona.blast`'s count for a recursive
   `rm`, the files, bytes and git-tracked, read from the command with
   nothing run. The facts lead, so the cut eats the model's words first.
   The widget trims to the terminal's own width. An optional line 3,
   `proof<TAB>command` on a cmd or danger reply, is one read-only check
   that the command did what was asked: `test ! -d build` after `rm -rf
   build`. The brief asks for it. `persona.proof_ok` refuses a proof
   that is not read-only, so a refused proof is never printed. It reads
   argv (`shlex.split`, a bad quote refuses) against a named allowlist
   of head words: test, ls, stat, grep, git status, systemctl is-active
   and the like. No compound, no redirect, no control character, and
   none of `persona.PROOF_DENIED` anywhere in argv. That list holds the
   options that make a read-only head write or run something:
   `--output`, `-o`, `--ext-diff`, `--textconv`, `tail -f`, `git -c`,
   `-exec`, `-delete` and more. A one-letter option is caught inside a
   cluster too. The widgets show the proof in the hint row after the
   command runs and offer it on `Esc s`. `spark do` offers it after each
   confirmed step like a step of its own: Enter runs it,
   `do.PROOF_TIMEOUT` seconds at most. `e` edits it, and the edit runs
   when `proof_ok` still takes it, else it is skipped. `spark do` shows
   the result and sends the model the exit code alone: a proof's output
   never rides a request. `spark do` lands each step's feedback on the
   thread the moment the step ran (`do.land`). The feedback is the
   command that ran, `edited from` the proposal when the user changed
   it, its exit code, the proof that ran and its exit code. So the last
   step of a run is recorded like every other. A control character in
   the model's command or proof refuses the reply whole, a `done` with
   `do.REFUSED_CONTROL`. `do.CONTROL` is C0, DEL, C1 and the bidi
   controls U+200E/F, U+202A-E and U+2066-9. An edit carrying one is
   skipped. A `sudo` step is a danger step: the typed `yes`. A goal is
   at most `do.DO_GOAL_MAX` (8 kB), else one signed line, exit 2,
   nothing sent. The budget keeps the goal whole, so it must fit. `spark
   do` is bounded, measured and held. A proposal's messages fit the
   served context (`do.budget`): `SPARK_CTX`, 8192 when unknown, at
   `reveal.CHARS_PER_TOKEN`, a `CTX_SHARE` of 0.8, less the system
   message and the reply's `DO_MAX_TOKENS`. `do.fit` keeps the goal and
   the newest step, shortens the oldest outputs to `(output trimmed,
   exit N)` first, then drops the oldest exchanges. `forge.history`
   (mode `do`) cuts the same way and rebuilds each user message with its
   `[cwd]` line, so a replayed prefix is the one that was served. Every
   proposal is a turn record through `Session.record`: the server's
   timings, the stem that answered, and a kind. The kinds are `cmd`,
   `danger`, `done`, `skipped`, `reasked`, `missing`, `stopped` and
   `quit`, with `held` and `man` as numbers on a step. What a step
   printed passes `do.hold` before a program sees it or it rides a
   request: `text.SOURCE_SHAPES`, plus spark's own secrets held by their
   contents wherever they appear (`do.own_secrets`). Those are the
   api-token, the file `SPARK_API_KEY_FILE` names, the forge-token, the
   ember-token, the shared engine's token, the account key and the
   login's token, `OWN_SECRET_MIN` 16 characters at least. One stderr
   line says `held=N`. The one named exemption is `do.CHECKSUM_LINE`.
   When the step's argv[0] is one of `do.CHECKSUM_TOOLS` (md5sum through
   b2sum, and shasum), a line of the checksum shape whose digest length
   is in `DIGEST_LENGTHS` keeps its digest. The same line from any other
   command is held. A step that exits non-zero with an option refused
   (`do.BAD_OPTION`) brings back `do.man_excerpt`. That runs `man -P cat
   HEAD` as argv, with `HEAD` a plain name. Both it and `man` must be
   found on `$PATH` with its empty and relative entries dropped
   (`do._abs_path`): a `man` planted in the step's directory is not the
   machine's. man runs from `/` with the pager variables dropped and
   `MANWIDTH=80`, on `MAN_TIMEOUT` 5 seconds with the process group
   killed. Overstrikes are stripped, and at most `MAN_MAX` 1500 bytes
   around the refused flag go back. The tool itself never runs for it,
   and `persona.SENDS` names it. A step nobody watches runs on
   `do.STEP_TIMEOUT` (120 seconds): rc 124, the process group killed,
   its pipe read `LEASH_GRACE` 0.5 seconds more and no longer. So a
   grandchild that left the group with `setsid` and holds the pipe
   cannot keep the step alive. That covers the page's steps, a sandboxed
   run's and a program's. `spark do --sandbox` (`lib/spark/sandbox.py`)
   moves the user's Enter and never removes it: containment replaces
   the per-step Enter, and the Enter moves to the apply.
   `sandbox.probe()` answers first (the `sandbox` row). A no is one
   signed line with the reason and the install line, exit 2.
   `sandbox.new_run` refuses a run dir inside the cwd (`spark do -- the
   sandbox needs a project directory, not ~ or /`) and a sixth run
   running or waiting (`SANDBOX_MAX_WAITING` 5, the count and the mkdir
   hold `runs/.lock`). Linux is one bwrap a step: `--ro-bind / /`, the
   git config files read-only one by one, the project an overlay whose
   upper dir keeps every write, `--clearenv` and `sandbox.STEP_ENV`. An
   empty tmpfs covers each of `sandbox.HIDDEN`: the homes, /root, /run,
   /tmp, /var/tmp, /media, /mnt and /etc/spark. `sandbox.BWRAP_FLAGS`
   gives fresh user, ipc, pid, net, uts and cgroup namespaces,
   `--disable-userns`, `--die-with-parent` and `--new-session`. bwrap
   sets no_new_privs, so sudo and setuid do not elevate. The rest of the
   system stays readable (/usr, /etc, /opt, /var): the review, a diff,
   is the gate there too. macOS is an `APFS` clone under `sandbox-exec`
   with `sandbox.PROFILE`: `cp -c` on the same volume,
   `SANDBOX_MAX_ENTRIES` listed within `SANDBOX_LIST_SECONDS`, a
   manifest at clone time. The
   profile is a named line each, every path a `-D` parameter, and
   `[cwd]` names the clone. It allows by default, because a deny-default
   profile breaks dyld. It denies every network socket, TCP and unix, so
   the ssh and gpg agents are out of reach. It denies reads of /Users,
   /Volumes, the home, spark's state and config, /private/etc/spark and
   the temp dirs (/private/var/folders, /private/tmp, /private/var/tmp).
   It denies reads of the system keychain, root's home and the package
   manager's service config (/opt/homebrew/etc, /usr/local/etc), but not
   the public files git, openssl, node and clang read. It denies every
   write but the clone, the run's own home and temp and the null
   devices, and it denies the terminal. It denies the mach services, so
   a program the step builds cannot reach them either: Apple events,
   Launch Services, the clipboard, the keychain daemons, Shortcuts and
   the workflow runner, login items and launchd jobs, the preferences
   daemons, recent items, plugins, mounts, file providers and consent.
   It denies the exec of osascript, osacompile, open, launchctl, sudo,
   security, pbcopy, pbpaste, shortcuts, automator, defaults and
   sfltool. It also denies screencapture, lsregister, lsappinfo,
   pluginkit, qlmanage, tccutil, hdiutil, diskutil, tmutil, crontab, at,
   fileproviderctl and brctl. setuid programs do not run. It does not
   make the machine private: a step reads everything else, sees the
   process list, and can talk to any system service the profile does not
   name. The review is the gate. sandbox-exec is Apple's, and its own
   man page tells developers to move off it. Steps and proofs run
   without asking, `proof_ok` still applying, `STEP_TIMEOUT` each, under
   `RLIMIT_FSIZE` (`sandbox.preexec`). The copy's total is weighed every
   `do.WATCH_SECONDS` (2 seconds) during a step: past
   `SANDBOX_MAX_BYTES` (1 GB) the step's group is killed (rc 124).
   Between steps the same cap stops the run (`cap`). A run is 8 steps. A
   danger step runs, contained, and is named. A step's own group is
   killed when it ends, so a background writer cannot outlive it. Its
   echo passes `sandbox.visible`: output nobody confirmed cannot redraw
   the screen the review is read on. The goal carries `do.SANDBOX_NOTE`.
   The system message stays byte-identical to plain do's. The review is
   `sandbox.changes`: entries sorted by path, each with a status from
   `sandbox.STATUSES` and its sha256. The statuses are added, changed,
   deleted, mode, link, binary, and the two that never apply, held and
   refused. `diff_text` (through `page()`) is a heading an entry and a
   unified diff under a changed text. Every control character is shown
   as an escape (`VISIBLE`: C0 but TAB, DEL, C1, the bidi controls, a
   lone surrogate). An entry whose name, link target or text holds one
   says `(control characters)`: a review cannot be redrawn by the text
   it reviews. A text over `DIFF_MAX` (256 kB) is a heading. Past
   `REVIEW_MAX` (2 MB of texts) every later entry is a heading, `too
   large to show`. Then `apply N changes to DIR? type yes:`. Git
   directories go by shape, not name (`GITDIR`). One is a directory
   named `.git`, case folded with the characters HFS+ ignores taken out,
   or one holding a `HEAD` file and an `objects/` directory. It counts
   in the project or the copy, and the project itself counts when it
   sits inside one. Every item inside is its own entry, under one count
   line per git directory. Only `sandbox.GIT_KEEP` applies: objects (but
   not `objects/info/alternates` and `http-alternates`), refs, logs,
   index, `HEAD`, `ORIG_HEAD`, `FETCH_HEAD`, `MERGE_HEAD`, packed-refs,
   `MERGE_MSG`, `COMMIT_EDITMSG`, description and `info/exclude`.
   Everything else is held with its reason (`GIT_WHY`): config and
   config.worktree, hooks, commondir and gitdir, worktrees and modules,
   anything else. A `.git` that is not a directory is held (`GITFILE`).
   `sandbox.apply(run, reviewed)` applies only what the review showed.
   The entries' fingerprint (path, status, kind, modes, sha256) must
   match the copy's now, and every file's bytes are hashed against it as
   they are staged, before the project is touched. A copy changed after
   the review is `the copy changed after the review -- nothing applied`,
   and the run waits. `--accept` passes nothing, since nothing was
   shown, and applies what the copy holds. The apply masks setuid and
   setgid. It refuses a device, a fifo, a socket, an overlay metacopy or
   redirect, and a link that leaves the project. It marks an added `+x`.
   It writes fd-relative with `O_NOFOLLOW` at every component, staged
   temps renamed into place. It refuses whole on a git lock file in the
   change set. It refuses whole on a conflict too: a touched project
   path whose mtime or ctime is newer than the run's start. No step can
   set ctime back. The run then waits. Anything but `yes` leaves the run
   waiting. A run that changed nothing is said and removed. Ctrl-C or
   `SIGTERM` leaves it waiting too. A run's life is `sandbox.STATES`:
   `running` while a process drives it and holds the run's flock,
   `runs/<id>/lock`, then `waiting`. Applied or discarded, its dir is
   removed whole. A run recorded running whose lock is free lost its
   driver and reads waiting. `runs/<id>/meta.json` holds numbers and
   names (id, thread, cwd, start, os, state). The goal's words live in
   the sealed thread. `--detach` needs no tty. It holds
   `runs/detach.lock` (`sandbox.detach_lock`, an flock: one detached run
   at a time, refused in one signed line), prints the id and leaves the
   changes waiting. `--review` lists the runs: id, age, changes or
   `running`, and the goal's first words from the thread. `--review ID`
   is the diff and the typed `yes`, at a terminal only. Otherwise one
   line points at `--accept`. `--accept ID` applies without showing,
   every named refusal still holding. `--discard ID` drops it. Each
   claims the run first (`sandbox.claim`: its lock taken here) and
   refuses one still running (`run ID is still running`). Bare `spark`
   and the bar line say `N runs waiting` (`bar.waiting`), a running run
   not counted. `--` ends the options: a goal that starts with `-` or is
   `help` is words. Without it, a first word that starts with `-` and is
   not an option is refused (`no option -x`, exit 2). `spark line
   --paste` is the paste inspection: a multi-line paste on stdin, no
   command back. It answers one `answer` or `danger` line naming what
   the paste does, and a locally dangerous line forces `danger` whatever
   the model says. Over 8 kB it is one line and nothing is sent. A paste
   that looks like a secret is one `answer` line naming the shape, and
   nothing is sent either. `text.SECRET_SHAPES` holds a private key
   block, an AWS, GitHub, Slack or `sk-` token, a `password=` or
   `token:` line, and a 64+ run of base64. The widgets hook the
   bracketed paste: bash rebinds the paste-begin sequence, zsh wraps
   `bracketed-paste`. Two or more lines into an empty prompt get the
   answer in the hint row. The paste itself always lands in the buffer
   untouched, and nothing runs until the user's own Enter. `spark off`
   and `SPARK_OFF` disable it. Exit 0 for the first 3 kinds, 1 for
   error. A buffer starting with `??` continues the newest thread. Any
   other starts a new one, no heuristics. On a logged-in client of a
   `FORGE`, `??` continues the newest thread on the `FORGE`
   (`forge.peer_newest`, the requester's own store over contract 9) and
   the turn lands there. Any trouble falls back to the local store.
   `SPARK_HINT_ROW=1` in the environment (the widgets set it on their
   two calls) lets `spark line` draw the pulse (`text.Busy.hint_row`) in
   the row above the cursor on `/dev/tty` while the model answers. Each
   frame saves the cursor, goes up one row, clears it, draws the mark
   and the dots, and restores. A hand-run `spark line` never touches
   that row, and stdout stays the two lines either way. The shell
   widgets depend on nothing else.
5. `spark brain --porcelain` prints `<url><TAB><model><TAB>forge|model`
   and exits 0, or exits 1. `<model>` is the spark role's model, the
   file stem. `forge` means `/api/health` there says `forge: true`. This
   is the check's only AI probe.
6. A live widget writes `~/.local/state/spark/widgets/<pid>` containing
   `<shell> <pid> <epoch> [hook]` and removes it on shell exit. The
   fourth field, the literal word `hook`, says that shell's exit-code
   hook is armed: the failure moment. Readers ignore fields they do not
   know, so old markers and old readers both survive.
7. `spark check` exits 0 when no row is `fail`, else 1. A `CAPABILITY`
   row never fails. `--porcelain` prints
   `category<TAB>status<TAB>name<TAB>value<TAB>remedy`. Every run writes
   `~/.local/state/spark/check.json` for the bar.
8. Signing. The first line of `spark --help` and of every subcommand's
   help is `spark <sub> -- <one line>`, plain ASCII, so every terminal
   can draw it. A refusal signs the same way. `spark setup --` is the
   offer bare `spark` prints after the banner, on a clone with no
   `site.env` at a terminal. `spark theme`, `spark font`, `spark quiet`
   and `spark bar` are core: they answer everywhere. `spark uninstall --
   not a terminal: spark uninstall --yes runs it` is the refusal of a
   non-terminal without `--yes`: the plan printed, exit 2. On WSL 2 the
   same shape: `spark font -- no console on WSL 2: the font lives in
   Windows Terminal's settings` (show 0, set 2), `spark quiet boot -- no
   GRUB on WSL 2: Windows boots it` and `spark headless -- WSL 2 stops
   with its last window: it cannot stay on and answer (a Linux machine
   can)` (exit 2). On Arch
   the verb is real only when a mkinitcpio preset builds a Unified
   Kernel Image (`site.boot_shape()` is `uki`), through the
   `/etc/cmdline.d` drop-in. Otherwise it answers `spark quiet boot --
   no UKI on this Arch: the kernel line is the boot loader's (a loader
   entry's options line, or GRUB_CMDLINE_LINUX_DEFAULT then
   grub-mkconfig)`, exit 2. On Void the verb is real where
   `/etc/default/grub` and `update-grub` are: Void's grub-mkconfig reads
   no drop-in, so `site.GRUB_WANT` lands as 3 lines at the file's end,
   each ending ` #spark-quiet#` (`site.GRUB_MARK`, bootstrap's twin);
   off deletes them. A Void without GRUB answers `spark quiet boot --
   no GRUB on this Void: its boot loader is left alone`, exit 2
   (`site.VOID_NO_BOOT`). The console font goes by mechanism,
   never by family (`site.console_shape()`: console-setup's file, else
   vconsole.conf, else rc.conf beside `/etc/runit`, else none). A Linux
   with none answers `spark font -- no console-setup, vconsole.conf or
   rc.conf here: the console font is not spark's to set` (show 0, set
   2).
9. The `FORGE` HTTP API. `lib/spark/forgeserve.py` serves it on
   `SPARK_FORGE_HOST:SPARK_FORGE_PORT`: one LAN address, never the
   unspecified address in any spelling. `bind_check` in
   `lib/spark/__init__.py` reads IPv4 the way the socket layer does, so
   `0`, `0.0` and `00.0.0.0` are `0.0.0.0` and refused like `::`. An
   address neither private nor loopback is bound with a warning, said
   and logged. `spark serve` shares the check. `GET /api/health` answers
   without a token: `{status, forge: true, name, version, model,
   upstream, models, roles}`, where `models` is `{role:
   loaded|unloaded}` and `roles` is `{role: model file stem}` per served
   role. It is the client's `FORGE` detector and the `forge` row's
   probe. `GET /`, `/login`, `/static/<f>`, `/manifest.webmanifest` and
   `/apple-touch-icon.png` (a 180x180 PNG the server draws) are the
   page, no token. The page is chat-first, and both roles land in the
   chat view. The hash routes are chat, monitor, do, config and help,
   chat the default, and navigation is one header menu button. For a
   user only chat, config and help exist. Monitor and do redirect to
   chat. The login link `/login#t=<token>` signs in by itself: `spark
   forge --print-url` and `spark user add` draw it as a QR at a
   terminal. The page reads the fragment before routing, strips it with
   history.replaceState, and posts it to `/api/login` once. A stale link
   is one 401, never a retry loop. A browser never sends a fragment, so
   it cannot reach the server or its log, which drops query strings
   besides (`_dispatch` logs `urlsplit().path`). Auth. The forge-token
   is admin: the whole machine and the box account's own store. The box
   account is the code's name for this machine's own login. Every other
   caller is a named user (`spark user add NAME`) presenting a personal
   token, verified against its stored sha256, its data key unwrapped in
   memory only. Every non-human caller is a named user of its own with
   its own token: a script, an app, a CI job. The admin's forge-token is
   the machine's, never shared. The `FORGE` is the account authority,
   and a client never mints: `spark setup --model none` skips the
   account row, and `forge.local_store` keeps nothing on a client with
   no login. A client logs in with a token minted here, and the `peer`
   row there says whether this `FORGE` accepts it. `POST /api/login`
   takes `{token}`, goes through the write gate like every other POST,
   and answers `{ok, name, role, user}`, setting the cookie. So a page
   on another origin cannot log a browser in. The session id is minted
   at random for that login, the admin's included, never derived from
   the token: two logins hold two cookies, and a captured token yields
   none. Sessions live in memory only. One expires with its cookie (90
   days). It dies on logout (`POST /api/logout` drops the session, not
   only the cookie) and with its token's rotation or removal, and it is
   gone on a restart. A restart sends every browser, the admin's too,
   back to the login. A wrong login costs 1 second and is counted: 401,
   then 429 after 10 wrong per minute from one address. While locked
   out, that address gets 429 on a bearer as well, before it is
   compared. A wrong bearer costs 1 second and is counted likewise. An
   unknown cookie is only a 401, because after a restart every browser
   holds one. The v1.3 shared ember-token is not accepted. Every route
   the server answers is one row of `forgeserve.ROUTES`: `(method,
   pattern): none|user|admin`, a `*` one path segment. `_route` consults
   nothing else, so a request off the table is 404. `none` is open. The
   two with a gate of their own keep it (`/api/login` the write gate,
   `/v1/chat/completions` the bearer). `user` needs the cookie or a
   token as a bearer, else 401. `admin` is the forge-token. A user there
   is 403 `{error: {kind: role}}`, because the soul is the machine's one
   identity. `tests/docs_test.py` holds this table equal to the code,
   entry for entry, and `tests/policy_test.py` proves every row with
   3 callers:

   ```
   GET     /                          none
   GET     /login                     none
   GET     /static/*                  none
   GET     /manifest.webmanifest      none
   GET     /apple-touch-icon.png      none
   GET     /api/health                none
   POST    /api/login                 none
   GET     /api/me                    user
   GET     /api/check                 user
   GET     /api/stats                 user
   GET     /api/bar                   user
   GET     /api/theme                 user
   GET     /api/events                user
   GET     /api/soul                  user
   GET     /api/memory                user
   GET     /api/models                user
   GET     /api/threads               user
   GET     /api/threads/*             user
   GET     /v1/models                 user
   POST    /v1/chat/completions       user
   POST    /api/logout                user
   POST    /api/chat                  user
   POST    /api/memory                user
   POST    /api/threads/*/append      user
   POST    /api/user/token            user
   DELETE  /api/threads               user
   DELETE  /api/memory/*              user
   GET     /api/serve                 admin
   GET     /api/gpu                   admin
   GET     /api/bench                 admin
   GET     /api/config                admin
   GET     /api/log                   admin
   GET     /api/users                 admin
   POST    /api/run                   admin
   POST    /api/do/propose            admin
   POST    /api/do/run                admin
   POST    /api/check/refresh         admin
   POST    /api/soul                  admin
   ```

   `GET /api/me` answers `{role, user, name, version}`: how the page
   decides which console to draw and whom to greet. `GET /api/models`
   answers this machine's model table `{name, total_gb, budget_gb,
   budget_pct, backend, cap_note, models: model.model_rows}`, what
   `spark model` on a client prints instead of its own numbers. The
   server answers every route from site.env and spark.env as they are
   now: `ForgeServer.cfg` re-reads them when either changes, the
   forge-token's rule. `spark model NAME` on the machine restarts
   spark-serve, not the `FORGE`. The chat, thread and memory routes are
   scoped to the requester's own sealed store: a user's to their
   `users/<name>/`, the admin's to the box account's. Nobody holds a key
   to anyone else's. `GET /api/users` (admin) answers `{users: [{name,
   threads, last}]}`: counts and stamps, never a title, a body or a
   token. That is the whole of admin visibility. `POST /api/user/token`
   (user) rotates the requester's own token, returned once, never
   stored. `DELETE /api/threads` clears the requester's own store and
   answers `{cleared}`. Every `POST` and `DELETE` under `/api/`,
   `/api/login` included, also needs `X-Spark: 1`, a `Host` this machine
   answers to and, when sent, an `Origin` matching it (400 or 403). A
   `POST` there needs a JSON object body sent as `Content-Type:
   application/json` besides (415 otherwise). A `DELETE` carries no
   body. `POST /v1/chat/completions` takes the bearer only. A cookie
   does not open it (401), so a browser's login cannot be ridden into
   the model from another origin. The forwarded body asks for at most
   `forgeserve.V1_MAX_TOKENS` (8192) completion tokens: `max_tokens` is
   set when absent, not a positive integer or larger, and `n_predict`
   and `max_completion_tokens` are capped the same when present. `POST
   /api/threads/<id>/append` puts one message onto the requester's own
   thread: `{role: user|assistant, text}`, with `mode` and `kind` as
   short optional fields. That is how a client's `??` lands its turn
   here, so the machine's prompt line, a client's prompt line and the
   page share one thread. `GET /api/check` returns `check.json` as
   written plus `age` in seconds. `POST /api/do/propose` answers
   `{thread, reply, ms, driver, unchecked}`: `driver` is the `ember`
   role's model stem, `unchecked` the done hint's numbers no user
   message of the thread backs (`[]` otherwise). A new thread's text is
   the goal, `do.DO_GOAL_MAX` (8 kB) at most, 400 otherwise. On a
   continued thread the text is held before the model sees it
   (`do.hold`). The command is read from its `Output of` first line for
   the checksum exemption. The proposal is a turn record. `POST
   /api/do/run` (admin) takes `{command, cwd?, confirmed?}`, runs the
   command as typed through the login shell on `do.STEP_TIMEOUT` (120
   seconds: rc 124, the process group killed) and answers `{rc, tail}`.
   When the step was refused for an option, `man` carries
   `do.man_excerpt`'s lines, and the page appends it to the feedback it
   proposes on, as the prompt line does. A control character in the
   command (`do.CONTROL`) is refused: 400, one line of printable text.
   Both do routes take `cwd` as sent (`HOME` when empty) and refuse one
   with a control character or that is not the absolute path of a
   directory (400). A command `persona.is_dangerous` flags runs only
   with `confirmed: true`, else 400 `{error: {kind: confirm}}`,
   which the page sends after its second click. The log line carries a
   sha256 prefix of the command beside its truncated text, and a second
   line the rc. Every admin action is one sealed record in the box
   account's `audit` (`lib/spark/audit.py`, kind `audit`,
   `vault.append_sealed`): `do/run` `{ts, ip, action, digest, rc}`,
   `/api/run` `{ts, ip, action, verb, rc}`, a user minted, removed or
   rotated `{ts, ip|cli, action, name}` (`spark user add|remove|token
   --new`, `POST /api/user/token`), and `spark forge token --new` `{ts,
   cli, action}`. Numbers and names, never a command's text or its
   arguments. `spark forge audit [N] [--porcelain]` prints the newest N
   (50 by default), one line each. A trail that does not open is one
   signed line, exit 2, never written over. `GET /api/config` returns no
   key matching `KEY|TOKEN|SECRET`, whatever spark.env holds. Streams
   are SSE. `/api/chat` (mode `chat|answer`) emits `queued` when the
   model is busy, `delta {t}`, `done {thread, ms, model}` and `error
   {kind, hint, thread?}`. `talk` and `ask` are still accepted as
   aliases of `chat` and `answer`, and records write the new names.
   `thread` rides a `cut`, whose partial already landed, so the page
   continues that thread instead of opening a new one. A client that
   hangs up mid-stream (the stop button) still lands the turn. The user
   line and any partial answer (`partial: true`) go on the thread, and
   the log line says 499. A client that leaves while queued pays no
   prefill and lands nothing, 499 likewise. `/api/run` emits `line {s}`
   then `done {rc}`. `/api/events` emits `check`, `bar` and `serve` on
   change, `log` too for an admin, and a `:keepalive` comment every 15
   seconds. `/v1/chat/completions` and `/v1/models` are OpenAI-shaped
   and proxied to the llama-server with the api-token. The request's
   `model` field routes, and a missing `model` means `ember`. The
   identity is injected into the system message only for an `ember`
   request. It is the soul, plus the requester's own remembered facts: a
   user's sealed memory, or the box account's for the admin. A `spark`
   request passes through untouched. JSON or SSE bytes come back as they
   are. Every `/api/*` answer is `Cache-Control: no-store`. The page and
   its files are served with `Content-Security-Policy: default-src
   'self'`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` and
   `X-Content-Type-Options: nosniff`, and depend on nothing else. Errors
   are `{error: {kind, hint}}`.
10. `spark edit` is the editor's protocol: the text on stdin. `--at N`
    prints what goes at byte offset N, a completion: 4 kB before the
    cursor and 2 kB after it are sent. `<words>` prints the whole text
    rewritten, at most 12 kB, else refused: the output replaces the
    input, so head plus tail makes no sense. `? [words]` answers about
    it: head 4 kB plus tail 12 kB with a visible cut mark, and `?` alone
    reviews. `--type FT`, `--name NAME`, `--about TEXT` and `--part` are
    hints that ride in the user message. `--part` says the text is a
    selection from a larger file, so the rewrite replaces exactly it.
    The name is a basename, never a path, and no `[cwd]` line rides,
    ever. Output is raw streamed text: no mark, no wrap, a code fence
    around the answer removed, a rewrite ending the way the input ended.
    An empty text with words is written from nothing (a new file in the
    editor), the reply ending with a newline. Exit 0, 1 when `?` or
    `--at` find no text, or no model answers, 2 for the usage. No thread
    is kept. The turn record is numbers (`kind`, the character count,
    `ms`). A `?` is two requests: the reading and the answer. The
    reading (`edit-read`) is a JSON `{language, kind}` from the first
    800 characters, restated as `You read this as: ...`. Any failure is
    silence. Its cost is a turn of its own, mode `edit-read`, kind
    `reading`, so `spark stats` shows what every grounded answer pays
    before it starts. When stderr is a terminal it says so there:
    `reading ...` while it runs, then the language and kind it named,
    one line. So the seconds before the first answer line are something
    to read. When stderr is a pipe, nothing: an editor's job,
    spark-w3m's capture and the tests keep stdout and stderr as the
    contract states them. A `?` answer streams line by line through
    `text.Anchors`. Every quoted span (double quotes, curly quotes,
    backticks, 3 to 200 characters) is checked against the text on
    stdin: verbatim, then folded (whitespace, quote marks, case), then
    trailing punctuation stripped. One that does not anchor is followed
    by ` [not in the text]` where it stands. A span right after `->`, a
    Unicode arrow or `=>` is the model's proposal. It is not checked,
    not counted, and followed by ` [proposed]`, so a reader can tell a
    quote from a proposal. The turn records `quotes` and `unanchored`.
    `--sel A B` is a `?` with stdin the whole file. It sends one window
    of at most 16 kB (`edit._edit_window`). The selection goes whole,
    with head, cut and tail past 12 kB, between the lines `[selection
    starts]` and `[selection ends]` the brief knows. The file around it
    is split evenly, with cut marks where it goes on. The reading runs
    on the 800 characters from 200 before the selection. `--thread ID`
    (a `?`, the client names the id, `forge.valid_id`) keeps the
    exchange in the account's sealed store like a chat thread
    (`forge.open_thread`, `SPARK_HISTORY` prunes it, `spark history`
    lists it). The same id again rides the earlier pairs. It sends the
    words alone when the text on stdin is the one the first turn carried
    (`text_sha` on that message), else `File NAME, as it is now:` and
    the text. The reading runs on the first turn only. Anchors always
    check the text on stdin now. Without `--thread`, or with history
    off, no thread is kept. `--source` (a `?`) picks the
    reading-discussion brief (`persona.MODE_EDIT_DISCUSS`, mode
    `edit-discuss`, the turn stays `kind` answer) over the editor's
    review brief. The text is a published source the reader discusses,
    not their draft, so the model answers the question and never
    suggests edits. The reading apps (spark-w3m, spark-newsboat) pass
    it. The editors never do. The flag is the caller declaring which
    posture, no auto-detection. A source is text that is not yours, so
    a `? --source` holds back every span that looks like a secret right
    after stdin is read. `text.SOURCE_SHAPES` is the paste's shapes plus
    two.
    A one-time code is its digits, whole or split once or twice by a
    space or a hyphen, within 30 characters after or before code, otp,
    pin, passcode or verification. A link token is every token-like
    parameter of an http(s) URL. It is found as a pair, the URL first
    and then its parameters, so no one regex backtracks over a crafted
    megabyte. A named `s` group is the part held. Each becomes `[held]`.
    The reading, the context, `--sel`'s offsets, the anchors and the
    thread's `text_sha` all see the held text: what the model saw.
    `--name`, `--about` and `--type` ride in the same message and are
    held the same way. The ledger keeps the name as given. One stderr
    line says how many and which shapes. The turn records `held`, a
    number. A rewrite, `--at` and a `?` without `--source` send the
    author's own text as it is. `--` ends the options: every argument
    after it is a word, so a question that says `--name` cannot eat the
    flag after it. `--decline --name NAME` (the pane's `d`) keeps the
    note on stdin in the ledger: `lib/spark/ledger.py`, the account's
    sealed `users/<name>/ledger`, by file NAME, 300 characters a note,
    30 a name, 200 in all. A later `?` about NAME carries `Declined
    before -- do not raise these again:` and the notes, newest first,
    1200 characters at most. A note whose first quoted span is no longer
    in the text has retired, dropped there and then, and every note
    leaves after `SPARK_HISTORY` days. `--ledger [clear] --name NAME`
    lists or drops them (the pane's `ledger` and `ledger clear` at the
    `spark>` prompt). There is no shell verb. The micro plugin depends
    on nothing else. `spark edit --watch FILE` is the live form. It
    watches a draft on disk: poll by mtime, re-open by path so an atomic
    save is caught, and a read that fails mid-swap waits a tick. It runs
    the `?` review path over each fresh stanza as it is saved
    (`edit.stanzas`, `_review_context`, `text.Anchors`), and a
    whole-draft review after `EDIT_WATCH_IDLE` seconds idle. A non-empty
    draft owes itself a review rather than baselining its work into
    `seen`. A transient model gap skips a comment in silence
    (`session.once`). The writer answers back through the `Alt-s` ask
    key, not a built-in chat: the loop keeps to one concern.
11. `spark read` is the reader's protocol: the source on stdin (a page,
    a message, a document), a question in the words, the answer raw
    streamed text out. Never a path, never a `[cwd]` line. Bare asks
    what the source covers. The law is contract 12's turned from
    questions to claims, enforced after the model (`text.Gate`, line by
    line). A line whose quotes are not in the source is dropped
    (`text.UNGROUNDED`). So is a line that quotes nothing
    (`text.UNQUOTED`): an unquoted sentence about a source is the
    model's own knowledge wearing the source's clothes. Kept lines
    stream marked. A reading pass runs first (`session.reading`,
    contract 10's). When nothing survives, stdout stays untouched and
    the reply is one line on stderr, exit 1. That line shows the
    source's own opening words (`read.opening`), composed in code and
    never asked of the model. A client tells "no answer" from "an
    answer" by the exit code. At most `READ_MAX` (16000) characters a
    part. A longer source is parts, each opening with the last
    `PART_OVERLAP` (400) characters of the one before. Without `--part
    N` it is refused in one line naming the count (exit 1, nothing
    sent). With it, the answer's first line is `[part N of M]`, written
    by the code before the first kept line. An answer from part 2 that
    does not say so cannot be told from an answer about the whole.
    `--name NAME` (a basename) never leaves the machine. It names the
    ledger record (kind `read`, `ledger.RULES`) written after a kept
    answer: the questions asked of this source, so a second reader sees
    what has been asked. Nothing invalidates them but age and `--ledger
    clear`, and they never suppress: a question asked twice of a source
    is a fair question twice, unlike a note declined in a draft.
    `--ledger [clear] [--name NAME]` lists or drops them. Exit 2 for the
    usage, a bad `--part`, or empty stdin (the usage plus where a
    question for spark itself goes). The turn record is numbers: `kind`,
    the character count, `ms`, `part`, `parts`, `kept`, `dropped`,
    `quotes`, `unanchored`, and `first_ms`, the wait to the first kept
    line. That is the number the prompt cache moves, and `spark stats`
    shows it beside each mode's cache hit rate. The reading pass is
    greedy (temperature 0). Its words are restated above the source in
    the request that follows, so a word sampled differently on the same
    source would break the served prompt's cached prefix. The source is
    always held back first (`text.hold_secrets`, contract 10's
    `--source` rule). Every span that looks like a secret becomes
    `[held]` before the parts are cut, one stderr line names the count
    and the shapes, and the turn records `held`.
12. `spark ask` is the questioner's protocol: the text on stdin (a plan,
    a draft, a decision) and questions about it out, raw, one per line.
    Never a path, never a `[cwd]` line. Mode comes from the argument
    shape, no mode flags: bare asks what the text does not answer,
    `<words>` says what the author is deciding. `--name NAME` (a
    basename) and `--about TEXT` are hints that ride in the user
    message. A reading pass runs first (`session.reading`, contract
    10's). `--thread ID` (the client names the id, `forge.valid_id`)
    keeps the exchange in the account's sealed store. The same id again
    rides the earlier pairs and sends the words alone when the text is
    the one the first turn carried (`forge.same_text`). A follow-up
    obeys the same law: the moment a reply may assert, this is `spark
    chat`. The law is enforced after the model, never by the brief
    alone. Every line of the output ends in a question mark or it never
    reaches stdout (`text.Gate`, line by line). Five filters run, in
    this order. The first drops a line that is not a question. The
    second drops one whose every quoted span is missing from the text
    (`text.UNGROUNDED`). The third drops anything past the cap of 3,
    a cap and never a target. The fourth drops a repeat, or a question
    the ledger holds as answered. The fifth drops a question that could
    be asked of any plan: `ask._GENERIC`, a named list, forgiven when
    the question shares a word of its own with the text. When nothing
    survives, stdout stays empty and the refusal is one line on stderr,
    exit 1. A client tells "no question" from "a question" by the exit
    code, never by reading prose. At most 12 kB in, else one line and
    exit 1. Exit 2 for the usage. stdin with no text prints it plus
    where a question for spark itself goes (`spark <words>`).
    `--answered --name NAME` keeps the question on stdin in the ledger
    (kind `ask`, `ledger.RULES`). Nothing invalidates it but age and
    `clear`: a plan moves, an answer stays an answer. `--ledger [clear]
    --name NAME` lists or drops them. A round where nothing survived is
    not written to the thread: a refusal is not a turn to follow up on.
    The turn record is numbers (`kind`, the character count, `ms`,
    `asked`, `dropped`, `quotes`, `unanchored`).
13. `spark drill` is the practice protocol: the source on stdin, one
    question at a time out, the answer at the terminal. Never a path.
    Both halves come from the source. The model proposes a verbatim span
    as the answer and a question that span answers
    (`persona.DRILL_SCHEMA`, a JSON reply). `drill._ground` drops any
    item whose answer does not `text.anchor` in the source before it is
    ever asked: a drill built on an invented answer teaches the
    invention. `DRILL_MAX` in, `ITEMS_MAX` a session. Too little to
    drill is one line (the source's opening, `read.opening`) and exit 1,
    never padded from the model's own knowledge. It is self-graded: the
    learner sees the source's span and says whether they had it. Model
    grading is a second opinion, not the source. The answers are graded
    on this machine and never sent. The source comes on stdin, so the
    answers come from `/dev/tty`. The `SPARK_DRILL_TTY` seam points them
    at a file in tests. No tty is a signed refusal, exit 2. The ledger
    kind is `drill`, and it schedules rather than suppresses, the
    inversion `ledger.RULES` exists for. `--name` keeps a schedule
    (`ledger.drill_grade`, `drill_due`, records carrying `misses`,
    `streak`, `due`). A missed item comes back at `INTERVALS` days (1,
    3, 7, 21, 60), widening each miss, until `RIGHT_TWICE` in a row
    rests it. `drill.schedule` is the policy. Alone among the kinds
    these never age out (`age: False`): a schedule that expires is not
    one. `--ledger [clear] --name NAME` lists or drops. Without
    `--name`, a session is practice kept nowhere. The turn record is
    numbers (`kind`, the character count, `items`, `right`, `wrong`).
14. `spark watch` is the monitor's protocol. A live stream comes on
    stdin (log lines, build output, a running process), an instruction
    in the words, and one line goes out when a line matches it. Never a
    path. Bare, with no words, is refused. The law is the grounded one,
    enforced after the model (`text.Gate`, `keep=GROUNDED`). The line
    out quotes the stream, so a line whose quote is not in the window it
    was shown is dropped, and "a 500 appeared" cannot fire when none
    did. Silence is the answer when nothing matches, and the healthy
    state. A window closes at `WINDOW_LINES` lines or `WINDOW_SECS` old,
    whichever comes first, at most `WATCH_MAX` characters to the model.
    No more than one call runs per `MIN_INTERVAL`, 10 seconds since
    v1.45. A chatty journal is one look every 10 seconds, not a pinned
    GPU, so the watch is cheap enough to leave running. Backlog accrued
    during a call coalesces into the next window. The watcher never
    watches itself. spark's own units log into the journal, and
    spark-serve carries llama-server's every slot and task line. A
    `journalctl -f | spark watch` once fed the model's own inference
    back to it, each look writing the lines that triggered the next. So
    a journal line under spark's identifier and a bare llama-server log
    line are dropped before the window (`watch.own_line`, `OWN_LINE`). A
    window of only those is no call at all. A transient model gap (down,
    loading, timeout, cut) skips the window and the watch goes on
    (`session.once`, the shared recovery `spark edit --watch` uses too).
    stdin closing ends it (exit 0), `SIGINT` 130. No ledger: a live
    stream has nothing stable to name. It is local in the strongest
    sense: the stream never leaves the machine, and the same model the
    prompt line uses answers. The turn record is numbers.
15. `spark do --porcelain [--sandbox] [--] <words>` is the task verb for
    a program: contract 4's `spark do`, driven over a pipe. No tty is
    needed. One stderr line (`do.PORCELAIN_BANNER`) says a program
    drives the run. stdout carries JSON Lines and nothing else, one
    object a line:
    - `{"ev":"start","thread","sandbox","run"}`, with `run` null outside
      the sandbox.
    - `{"ev":"step","n","command","hint","danger","proof"}`.
    - `{"ev":"output","n","text"}`: the step's last 4 kB after
      `do.hold`, what the model reads.
    - `{"ev":"rc","n","rc"}`.
    - `{"ev":"note","text"}`: the driver line, a refusal, a skip, the
      man excerpt's count, an apply's result.
    - `{"ev":"review","run","files"}`, each file
      `{"path","status","old","new","exec","reason","control"}`. `path`
      is relative to the cwd and `status` one of `sandbox.STATUSES`.
      `old` and `new` are the whole texts, a
      link's targets, a mode's octal, or null where there is none or it
      is too large to show. `exec` is true when the file became
      executable. `reason` says why it is held or refused, else a note
      (the setuid bit dropped, a binary's size, too large to show), ''
      when none. `control` is true when its name, link target or text
      holds a control character. Every item inside a git directory is
      its own entry.
    - `{"ev":"end","reason":"done|cap|quit|refused|stopped|error","hint","rc"}`.
    `stopped` is spark stopping the run: a skipped step proposed again,
    verbatim, after it was re-asked once. A sandboxed run's `end` is its
    review's, however the steps stopped, and a note says that: `done`
    (applied, discarded, nothing changed), `quit` (the run waits) or
    `error`. Only an `error` before the review skips it, the copy then
    waiting when it holds a change. `end` is always the last line:
    Ctrl-C is `quit` rc 130, `SIGTERM` `quit` rc 143, an exception
    `error` rc 1, and the event goes out before the exception does. `n`
    counts step events, a proof's included. stdin is read only when
    something waits, one word a line. Outside the sandbox a step waits
    for `run`, `skip`, `quit` or `edit <command>`. Its proof is a step
    of its own (hint `proof of step N`, danger false, proof null) that
    waits for `run`, `skip` or `quit`. Inside the sandbox nothing waits
    per step: steps and proofs run, and the review waits for `accept` or
    `discard`. On `quit` or EOF there, the run waits for `spark do
    --review`. `accept` applies only what the review event showed
    (`sandbox.apply`'s `reviewed`). A copy that changed after it applies
    nothing: a note, `end` reason `error` rc 1, and the run waits. There
    is no `yes` word. Outside the sandbox the line is all that is
    checked before a step runs. A step that can destroy data
    (`persona.is_dangerous`, or the model's danger flag) is refused
    without waiting. So is one whose effect cannot be read from the line
    (`persona.OPAQUE`). The refusal is a note, and the model hears it
    was skipped. `persona.OPAQUE` is a command substitution, a backtick,
    eval, a backslash inside a word, an interpreter handed inline code
    or a script on stdin, and a curl or wget upload. An edit is held to
    the same two. Anything else runs on the program's `run` with the
    user's own rights. A program that cannot vouch for every step drives
    the run with `--sandbox`. EOF while a step waits is quit. Every
    refusal before the run is one `end` event, reason `refused`, rc 2,
    and nothing else on stdout. The refusals are an option spark do does
    not take, no goal, a goal over 8 kB, `--detach`, the probe, the cwd
    and the waiting cap. `--review`, `--accept` and `--discard` are
    refused there too, because they are not runs. No model to drive the
    run is one `end`, reason `error`, rc 1. Outside the sandbox the
    steps run on `do.STEP_TIMEOUT`. `SIGTERM` ends the run and its step.
    The exit code is the `end` event's rc. Its first app is spark-acp
    (`docs/APPS.md`), an Agent Client Protocol agent: a step is a Run or
    a Skip, a review one Accept or Discard.

## The grammar

One grammar for every verb. A verb that breaks a rule is a bug.

1. A bare verb shows. It never mutates. The one carve-out: `spark bar`
   with stdout not a tty still prints the bar line itself. A status bar
   runs `spark bar` piped and must always get the line, never a state
   change.
2. `on|off` is the only switch vocabulary at the CLI: headless, serve,
   forge, quiet, memory. The two servers hold the same kind of state and
   answer the same way. There is no `start`/`stop` pair beside it, and
   `--force`/`--noreload` are flags of `off`. Stored values are storage,
   not interface: `SITE_HEADLESS` and the `SITE_QUIET_*` keys stay
   `yes|no` in `site.env`, and the verb translates. Choices keep their
   value grammars (`theme NAME|none`, `model NAME|auto|none`, `client
   URL|off`). The one carve-out is bare `spark off` / `spark on`, which
   silences and restores the whole prompt: it is the global mute, and
   reads better without a noun in front of it.
3. `status` is an alias of bare for every stateful verb. `list` is the
   table word (theme, model, ember, font). A noun keeps its own verbs as
   sub-words rather than taking top-level ones: `spark soul edit|reset`,
   `spark memory add|forget|clear`.
4. Every verb answers `-h|--help|help` first, before any gate or config
   read, signed per contract 8.
5. One confirm shape: `<question>? yes/NO: `. Only `y` or `yes`
   proceeds. Enter or EOF is no (`confirm()` in `lib/spark/__init__.py`,
   beside `say()`). The one deliberate second shape is the typed word
   `yes`: `spark do`'s danger step, the sandbox's apply (`apply N
   changes to DIR? type yes:`) and `spark uninstall`.
6. One progress vocabulary. curl's bar for downloads. One dot-spinner
   for every wait on a server coming up: `wait_ready(label, probe,
   timeout, interval)` in `lib/spark/__init__.py`, plain dots that
   survive in a log. One pulse for every wait on a reply: `text.Busy`,
   the mark and `.` `..` `...` redrawn in place, a tty only (the hint
   row, chat, explain, an answer, `spark do`).
7. Exit codes: 0 ok or show, 1 the world failed (stderr, via `die()`), 2
   the invocation (usage, an unknown name, a gate refusal: stdout,
   signed), 78 misconfiguration (`EX_CONFIG`), 130 `SIGINT`.

## Adding things

- **A doc.** The project site (spark.forgewright.ai) is the docs
  rendered outside this tree, at the newest signed release tag, never
  main:
  `docs/INSTALL.md`, `docs/CHEATSHEET.txt`, `models.env`,
  `docs/CHANGELOG.md`, `docs/ROADMAP.md`, `docs/CONTRIBUTING.md`,
  `CREDITS.md` and `docs/TOUR.md`. A change here reaches it with the
  next release, nothing to do, and nothing in this tree builds or
  publishes it (Releasing, step 3). Its look mirrors the colour tokens
  of `lib/spark/forge/spark.css`. That lockstep is checked where the
  site is rendered, against this tree. `tests/docs_test.py` keeps the
  docs true (pre-commit, CI). Every palette and every model upstream is
  in `CREDITS.md`, the check-row and model counts the docs state are the
  tree's, and no retired word survives. A new fact a doc states that the
  tree can derive goes there as one more check: the test is the
  consistency, not a reviewer. What a new user reads (`README.md`,
  `docs/INSTALL.md`, `docs/CHEATSHEET.txt`, the site's front) is minimal
  and step by step and speaks two nouns, spark and spark apps. No
  `FORGE`, `ember` or `brain` as a noun there, no "smart app", and
  nothing private named anywhere in the tree's docs. docs_test holds the
  word list. This file and `AGENTS.md` keep the contracts' names. Every
  document but `README.md`, `CREDITS.md`, this file and `AGENTS.md`
  lives in `docs/`. One beside the core says it is not tied to a
  release, and a core one does not. Each is in the Layout and is pointed
  to, because a doc nobody is sent to is dead. `docs/CONTRIBUTING.md`,
  "Voice", is the style sheet every document, help and usage text
  follows.
- **A package.** Linux: the right `PKG_*` group in every
  `distro/<id>.env`, with a comment saying why, under the name that
  family's manager knows, and its credit in `CREDITS.md` (docs_test
  looks every name up). `PKG_CORE`, `PKG_ENGINE` and `PKG_AI` are the
  AI, always installed. spark installs no shell tool. The mac core
  needs nothing from Homebrew. No editor, no app and no contributor tool
  (shellcheck is the contributor's own). The `packages` row and `spark
  uninstall` read the same files through `lib/spark/packages.py`.
  Bootstrap's `pkg_installed`, `pkg_available` and `pkg_install` are the
  sh twin, the one place that switches on the manager. Nothing else to
  update.
- **A config file.** First ask whether the app rewrites its own config.
  If it only reads, put it in `home/` (shared) or `<os>/home/`, and
  `install.sh` links it. If it rewrites, it cannot be linked: write it
  once from `templates/` as a rendered regular file, and note it in
  `docs/INSTALL.md`. Test by changing a setting in the app and running
  `ls -l` on the path: still a symlink, or now a regular file?
- **A choice.** A `SITE_*` key with a default in `site.env.example`,
  applied by `bootstrap.sh` or rendered by `install.sh`. And a `spark
  <verb>` that sets and applies it: `spark theme`, `spark font`, `spark
  quiet`. `lib/spark/site.py` has `set_keys` and `apply`. Editing
  `site.env` by hand is the fallback, never the interface.
- **The landing rule.** Nothing is done until it is in all of: `spark
  help` (`bin/spark`), a `spark` command, a `spark check` row when it is
  a promise the machine makes, contract 3 above if it is a key, and
  `README.md`, `docs/INSTALL.md`, `docs/CHEATSHEET.txt` and
  `docs/CHANGELOG.md`. A key without a command, or a command without a
  row and a doc line, is half a feature. The rule binds the core
  documentation, and core documentation moves with a release:
  `README.md`, `docs/INSTALL.md`, `docs/CHEATSHEET.txt`, `spark help`,
  this file and `docs/CHANGELOG.md` are updated as a version ships,
  together. The four beside them in `docs/` (TOUR, APPS, IDEAS,
  TROUBLESHOOTING) are outside it. They are kept true continuously, and
  no release waits on them. Nothing in them has to appear in help, the
  cheatsheet or a changelog entry. Each of those says so in its own
  first lines. `tests/docs_test.py` checks that it does and that the
  Layout above names it. It also checks that `README.md`,
  `docs/INSTALL.md`, `docs/CHEATSHEET.txt` or `docs/ROADMAP.md` points
  to it. So none drifts back under the rule by accident, and none goes
  unread.
- **A check row.** A function `row_<name>(ctx)` in `lib/spark/check.py`
  decorated `@row(CATEGORY, fixture=True)` or `@row(CATEGORY,
  fixture=False, reason="...")`. If it is fixture-testable, extend
  `make_fixture` so the row is ok in the good fixture and not ok in the
  bad one. `--selftest` refuses otherwise. `CAPABILITY` rows use `warn`
  or `na`, never `fail`, so `spark check`'s exit code keeps meaning
  "something reproducible is broken".
- **A chaos scenario.** A function `chaos_<name>(m)` in
  `lib/spark/chaos.py` decorated `@scenario(row=..., expect=..., ...)`.
  It breaks the throwaway machine `m` one way and returns `""` or why
  the break did not take. The runner then asks the row, runs the heal
  and asks again. The heal is the row's own remedy string wherever the
  remedy is a command (`heal="remedy"`, a parenthetical aside after two
  spaces is for the reader, not the shell). That is the point of the
  suite, and it is how a remedy naming a renamed verb gets caught.
  Where nothing here can run it, `heal=None` and `unhealed` must say
  why, so an unrehearsed half is visible instead of silent. `healed=NA`
  is for a remedy whose promise is to forget a thing, not bring it
  back. A scenario with no row (`row=None`) must say what it proves
  instead. `mood` picks the model's behaviour: `ok`, `slow`, `hang`,
  `loading`, `cut`, `garbage`, `blackhole`. A scenario is not a check
  row. Chaos is a prover, like `--selftest`, not a promise the machine
  makes: neither has a row, and obligation 3 is met by the row the
  scenario judges. Before trusting a new one, take the fix away and
  watch it go red.
- **A prose data file.** The soul is the pattern. It is user-owned text
  under `~/.config/spark/`, never linked from `home/`. A `spark` verb
  writes it 0600, and the page writes it through the same code. It is
  capped (`SOUL_MAX`), sent to the model on every request, and reported
  by its own check row (mode, size, cap). It is config, not state:
  pruning and `history clear` never touch it. The memory follows the
  same rules but lives sealed in the account's store since v1.4
  (`users/<name>/memory`, `FACT_MAX`, `FACTS_MAX`, `TOTAL_MAX`). The
  pre-v1.4 plaintext file is read as a fallback until the first write or
  `spark user claim` seals it away. Turns are the opposite pattern:
  telemetry, numbers only. `session.record` strips every free-text field
  (`session.TEXT_FIELDS`), and the words live only in the sealed
  threads. What a request weighed and where it went do ride the record:
  `out_bytes` and `dest` (`host:port`, or `local` for loopback),
  `wire._sent`'s pair on every chat shape's timings. So the `sends` row
  and `spark stats --sends` count what left by destination and day
  without a word of it. The `hardening` row asks contract 9's gates of
  the served `FORGE` (the other machine's, on a client) from the wire:
  `wire.probe_gates`, the probes `tests/forge_probe.py` runs against a
  real server.
- **A route.** In `forgeserve.py`: one row in `ROUTES` (`(method,
  pattern): none|user|admin`, plus the POST rules) and its handler in
  the matching branch of `_route`. Answer through `_json` or `_sse` so
  it is `no-store` and logged. Add the same row in contract 9's table
  (`docs_test` holds the two equal, `policy_test` proves the row) and a
  case in `tests/forge_smoke.py`. An admin action writes its audit
  record (`Handler._audit`). The page calls verbs through `/api/run`'s
  allowlist (`RUN_VERBS`) rather than writing config. The page is a
  door to the same identity, not a product of its own: a page change
  lands only when it is the client side of a contract change. No new
  page features in this release or the next.
- **A shell thing.** The look and the tools of a machine are not spark's
  business. spark's side of any renderer is 3 things. `theme.env` is
  the palette `spark theme` writes, a `KEY=value` file any renderer or
  terminal may read. The three `SPARK_*_SGR` variables are what an rc
  may export: colour at the prompt's marks, plain when unset. The bar
  line (`spark bar line`) is for any status bar to run. `spark theme`,
  `spark font`, `spark quiet` and the bar line are core: the page reads
  `theme.env`, the console palette and font are the machine's own, the
  status line is the machine's own report. Nothing in this tree names a
  renderer as a dependency. A coexistence check for a prompt program
  (the hooks' `STARSHIP_SHELL` test) is not a coupling.
- **A grounded contract.** One law, 5 contracts (10, 11, 12, 13, 14):
  what a model says about a text is checked against that text before the
  reader sees it. The judge is `lib/spark/text.py`. `anchor()` works at
  the span level and `Ground` at the unit level. `Gate` is the stream
  that marks what it keeps and drops what it refuses, so a contract can
  refuse instead of invent. drill checks a single answer span with
  `anchor()` directly. watch and read run the `Gate`. A new one states
  5 things, in this file and in its module's own head. It names what
  grounds its output. It says what happens when grounding fails: one
  line, and the exit code that says so. It states its caps. It names its
  ledger kind and the rule that retires a record there, because
  `ledger.RULES` holds each contract's own rule, and a rule that
  generalised would fit none of them. It says what leaves the machine.
  Text on stdin, raw text out, never a path: that is what lets an editor
  with no plugin at all be a client.
- **A spark app.** Nothing in this repository. A tool becomes smart as a
  client of one spark surface (Principles, "The spine"). Its plugin
  lives in its own repository, `spark-<app>`, installed the app's way
  with its own keys, tests and channel. spark keeps the verb and its
  judge. The editor briefs live in
  `persona.MODES` (`edit-complete`, `edit-rewrite`, `edit-answer`,
  `edit-read`): no table routes by filetype or genre. The model reads
  what the text is, and for a `?` its own reading is restated to it,
  because small models drift otherwise. The audition
  (`tests/audition.py`) scores those briefs against a live model. micro
  is the first app, forgewright-ai/spark-micro: it spawns `spark
  edit` with the text on stdin and streams the answer back, never speaks
  HTTP, never sees a token, never sends a path. Its pty test, its
  `Alt-s` line and its README are its own. Nine apps today: micro,
  neovim, vim, helix, nano, w3m, newsboat, aerc and acp. The editors
  take two shapes. A full plugin (micro, neovim, vim) carries the whole
  prompt and completes at the cursor. A prompt plugin (helix, nano,
  editors with no cursor hook) pre-fills the editor's own prompt with
  `spark edit `. It is proven the same way, by a pty test whose config
  is the shipped snippet itself. The readers (w3m, newsboat, aerc) are
  clients of contract 11, `spark read`: a keymap snippet and a
  stderr-folding wrapper, the same laws, their own repositories.
  spark-acp is the task verb's client (contract 15, `spark do
  --porcelain`). It is an Agent Client Protocol agent for Toad or Zed.
  It starts nothing but spark, never speaks HTTP, and has no `yes` to
  give. `docs/APPS.md` lists the known apps, and every one of them is
  in `CREDITS.md` and on the site's front. docs_test reads the app
  names out of `docs/APPS.md` and looks them up in `CREDITS.md`. The
  site's front is checked the same way where it is rendered. A new one
  is one line in each. The core docs do not name them. A pull request
  that adds an app, an app package or an app check row here is turned
  into a pointer to the app's repository.
- **The client shape.** `SITE_AI_MODEL=none` beside `SITE_PEER_AI_URL`
  (`config.client`, `spark client URL|off`, `site.cmd_client`) means
  nothing runs here. Bootstrap skips the `engine` and `services` rows
  (`$client`), `install.sh` links no unit and renders no plist, and the
  rows in `check.CLIENT_ROWS` (engine, services, watchdog, ai, serve,
  forge, ember) read `na`. `--selftest`'s third pass asserts that with
  the `peer` row ok. The `peer` row is where a client's health lives. A
  client stays a client until `spark client off`. `spark model`, `ember
  list` and `model budget` there print the other machine's table, never
  this machine's RAM as a budget (`model.peer_models`, `GET /api/models`
  with the login token). When the other machine is down, a bare server
  or an older `FORGE`, they print the rows alone, without a fit.
  `bootstrap.sh --list-models` does likewise. `spark model
  NAME|auto|none`, `model budget N`, `model rm` and `spark ember NAME`
  are refused with one line (`model._client_no`): each would have made
  a server of the client in silence. `spark client off` is the one
  deliberate promotion. It ends the shape, then runs `spark model
  auto`. The other machine may be this same machine's raw engine
  (`spark share on` there). The client injects its
  own soul and memory (forge=False), so it stays sovereign. `cmd_client`
  records `SPARK_API_KEY_FILE=$SHARE_TOKEN` when that group-readable
  token is present, rather than minting one the engine would reject.
  `config.token_file` also falls back to it for a user with none of
  their own.
- **A shared engine.** `spark share on` (`SITE_SHARE=yes`,
  `site.cmd_share`) lets a machine's other OS users answer from its one
  engine instead of each loading the model. Bootstrap's `share` row
  ensures a `spark` OS group and a `0640 root:spark` copy of the
  api-token at `$SHARE_TOKEN` (`/etc/spark/token`, `SPARK_SHARE_TOKEN`
  overrides), re-synced each apply. It publishes the engine's address to
  `$SHARE_URL` (`/etc/spark/url`, `0644`) so a joiner finds it without
  reading the owner's `$HOME`. The owner's own token stays `0600`. The
  `share` check row (`CAPABILITY`, `fixture=False`, because the group
  needs root) reports the group, the token and the url, and warns if the
  copy drifts. A group member joins as a client with no root.
  Bootstrap's `share` row and `sudo_upfront` both short-circuit for a
  client (`$client`), so a joining user never trips a root step or
  removes the owner's token. `spark setup` on such a machine detects
  `$SHARE_TOKEN` and offers the join. It writes the client shape for
  them: `SITE_AI_MODEL=none`, `SITE_PEER_AI_URL` from `$SHARE_URL`,
  `SPARK_API_KEY_FILE=$SHARE_TOKEN` and `SITE_THEME=none`. No model is
  downloaded, and their own soul and memory stay in `$HOME`. Identity
  stays per `$HOME`. Compute is shared and chosen explicitly. spark
  never routes to an engine the user did not name. Linux only in this
  version: macOS and WSL are one user per machine (`site.no_share`), a
  signed refusal from `spark share on` and a skip row.
- **A model.** One list, `models.env`. A row is `MODEL_<NAME>` with the
  5 fields, and its `_LICENSE` always. A `_NOTE` goes on when one
  line helps. A `_GROUND="<kept>/<run> <date>"` goes on once the
  grounding audition scored it here (`tests/audition.py --json`).
  `_TESTED="line"` goes on only once the row has answered `spark line`
  with valid JSON. `auto` reads only tested rows under an open license
  (`config.auto_rows`, `bootstrap.sh model_rows`). A row under another
  license is by name and asks before the download (`model._license_ok`,
  `config.is_open`). Size and sha256 come from the file's Hugging Face
  metadata: `x-linked-size` and `x-linked-etag` on the redirect
  `.../resolve/main/<file>?download=true` answers with. The CDN it
  points at knows neither. A name already in the other file
  (`~/.config/spark/models.env`, yours) is refused, naming both
  (`config.model_tables`, `bootstrap.sh model_rows_all`). `spark model
  add URL` writes your row for you: huggingface.co is auto-verified from
  that redirect, any other host needs `--sha256`, and `--license "NAME
  URL"` is always required there. `spark model verify` (and the `models`
  check row, cached) re-hashes every downloaded file
  (`lib/spark/verify.py`).
- **A palette.** Two files, nothing else hand-listed.
  `themes/<name>.env` carries the full 20-key `THEME_*` set (contract
  3), and its header comment names the upstream project and its license.
  `spark.js`'s `theme.builtin` map carries its flat 20-value row,
  because the page has no build step. `tests/install_test.sh` renders
  every palette by glob, and `tests/smoke.py` asserts the
  `theme.builtin` map matches `themes/*.env` value for value: a gap in
  either goes loud. A palette of the user's own is one file,
  `~/.config/spark/themes/<name>.env`, the same 20 keys, and lives
  nowhere else: not on the page, not in `CREDITS.md`, not in that map.
  On macOS `spark theme NAME` also switches every open Terminal.app
  window to the profile (`theme._switch_windows`). The running app reads
  its preferences only at launch. So a profile it does not know yet is
  imported live by opening the `.terminal` file, and one window opens
  with it. osascript then makes it the default and sets it on every tab.

## Verifying a claim

```sh
./bootstrap.sh --dry-run        # must end with: Nothing to do
spark check                     # must exit 0
spark check --selftest          # every fixture-testable row flips
spark check --chaos             # every rehearsed failure: break, red, remedy, green
spark forge                     # the page's server: up, at one LAN address
python3 tests/forge_smoke.py    # the API and the page, against a stub model
python3 tests/docs_test.py      # the docs say what the tree holds (credits, counts)
python3 tests/widget_pty.py pager        # $PAGER at a tty; plain when absent
python3 tests/widget_pty.py completion zsh home/.config/spark/completion.zsh
                                # TAB completes verbs and names (bash likewise)
git status -sb                  # clean, not ahead of origin
spark check --porcelain | grep privacy   # the tree contains no banned word
sh tests/get_test.sh            # the one-liner: clone, pull, refusals, the hand-off to setup
sh tests/update_test.sh         # spark update: pull, move to a signed tag, unsigned and dirty refused, --dry-run
```

`spark check` has 40 rows today, by category `11 SOFTWARE, 20
CAPABILITY, 9 NONFUNCTIONAL` (`grep -c '^@row' lib/spark/check.py`
counts them). `--selftest` runs 6 passes. The first two prove every
fixture-testable row flips between a good and a bad fixture. The third
is the client shape: the 7 rows in `check.CLIENT_ROWS` answer `na`. On
Linux the fourth runs under a WSL 2 kernel line, where the 3 rows in
`check.WSL_ROWS` say so and never fail. The fifth runs under `ID=arch`,
where the 1 row in `check.ARCH_ROWS` says so, the font row is ok
through vconsole.conf and the packages row answers through a pacman
stub. The sixth runs under `ID=void`, where the 1 row in
`check.VOID_ROWS` says so, the font row is ok through rc.conf, the
packages row answers through an xbps stub and the services row through
an sv stub.

## Releasing

The git tag is the release: one control, not two. There is no `VERSION`
constant. `spark ver` derives it from git (`lib/spark/version.py`,
cached): `1.0` exactly at a tag, `1.0+3` 3 commits past it. A
release tag is signed. `get`, `spark update` and `release.yml` verify
its ssh signature against the tree's `allowed-signers` and move to no
other tag. That file is one line per key, the principal the literal
`spark-release`, never a real name. So a pushed tag alone runs
nothing on anyone's install. A key in that file does. The `signed` row
of `spark check` names the key's principal on a release clone. Update
`CREDITS.md` when a pin or a model row changes.

Signing, once per machine: `git config gpg.format ssh` and `git config
user.signingkey ~/.ssh/id_ed25519.pub`, with the private half beside it
or in the agent. Key rotation is a commit that adds the new key's line
to `allowed-signers`, released under a tag signed by the old key. Every
clone verifies with the file it has and moves to the tree that knows
the new key. The old line comes out in a later release, signed by the
new one. `verify-tag` with an ssh signature needs git 2.34 or newer and
ssh-keygen (openssh). `get` asks for both before it clones.

1. Write the `## vX.Y` section at the top of `docs/CHANGELOG.md`,
   bullets, newest first. The project site shows the section only once
   the tag exists, because it renders the newest release tag.
   `tests/docs_test.py` refuses a heading more than one release ahead
   of that tag.
   Run the full gate: the pre-commit and pre-push hooks. Commit, push,
   `gh run watch` until green.
2. `git tag -s vX.Y -m 'spark vX.Y' && git push origin vX.Y`. The tag
   push runs `release.yml`. It verifies the signature against
   `allowed-signers`. It checks the CHANGELOG heading, and that `spark
   ver` says `spark X.Y` at the tag. Then it creates the GitHub Release
   with that CHANGELOG section as its notes and two assets. The assets
   are `get` (`releases/latest/download/get`, the one-liner) and
   `sbom.cdx.json` (`spark ver --sbom` at the tag: what the tree depends
   on, CycloneDX 1.5, `lib/spark/sbom.py`). Nothing is rerun.
3. The project site (spark.forgewright.ai) is rendered outside this
   tree, at the newest signed tag. Run its render by hand now (`gh
   workflow run` in the repository that renders it), or let its
   six-hourly run pick the tag up. Nothing in this tree publishes it.
4. Deploy is `spark update` everywhere. A main checkout pulls, and a
   checkout on a tag moves to the new one. Either way it converges:
   bootstrap.sh, then `spark check`, must both come back clean. `spark
   ver` there prints exactly `spark X.Y` at the tag, and `spark X.Y+N` N
   commits past it on a developer clone (`main`, via `SPARK_REF=main`).

Author metadata (the name and e-mail on commits) is outside the privacy
gate: use the GitHub noreply address. The gate itself reads both the
tree (pre-commit) and the message (commit-msg). The history is as
public as the tree.

Re-derive every count in the docs before trusting it. Counts go stale.
Follow every cross-reference. Sections get deleted. Be most suspicious
of a sentence that explains why something works: a wrong reason reads
exactly like a right one.
