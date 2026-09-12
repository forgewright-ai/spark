# Changelog

## v1.26

- `spark setup` no longer picks a look: it writes `SITE_THEME=none`, so a
  fresh machine keeps its terminal's own colours until `spark theme NAME`
  says otherwise. It recorded gruvbox-dark before -- a choice the user
  never made, which the theme row's remedy then offered to paint.

## v1.25

- A shared-engine box converges again. The `share` row compared the token
  copy by contents, which the owner (not in the `spark` group) cannot read,
  so every `bootstrap`/`spark update`/`spark check` showed a perpetual "1 to
  do" and re-copied the token. Freshness is now by mtime -- the copy is
  current when it is no older than the source -- readable by the owner, so
  the row (and `spark share`) settle to `ok`. A rotated token still
  re-syncs.

## v1.24

- `spark share` no longer cries STALE at the owner. The shared token is
  `0640 root:spark`, so the owner (not in the `spark` group) cannot read the
  copy to compare it -- and unreadable was being reported as stale. Now a
  content check runs only when the file is readable here; otherwise the
  perms are the health signal. A group member still gets the real check.
- INSTALL's join one-liner named the wrong host (a 404); it now points at
  `raw.githubusercontent.com/forgewright-ai/spark/main/get`, the same URL
  the page and README use.

## v1.23

- Joining a shared engine is now userspace -- no sudo, no download. When a
  machine already runs a shared engine (`spark share on`), `spark setup`
  detects it and offers to join instead of the full first-run: it writes the
  client shape (no model, `SITE_THEME=none`), keeps the joining user's own
  soul and memory in their `$HOME`, and touches nothing that needs root. A
  second OS user sets up with the ordinary one-liner and answers from the
  one engine in seconds. Fixes v1.22, where a second user hit the model
  table, a second download, and a sudo wall they could not pass.
- `spark share on` now also publishes the engine's address to
  `/etc/spark/url` (0644, beside the token), so a joining user finds it
  without reading the owner's home; `spark share` reports it.
- `bootstrap.sh` makes a client of a shared engine truly root-free: it skips
  the `share` section for a client (no longer trying to remove the owner's
  token) and no longer asks for sudo up front when nothing needs it.

## v1.22

- `spark share on|off`: one engine for every OS user on a machine. Instead
  of each user loading the model again, the owner runs the engine (headless)
  and a `spark` OS group reads a `0640` copy of the api-token; a group
  member's spark answers from that shared engine as a client -- `spark
  client http://<host>:8080` -- keeping their own soul, memory and threads
  in their own `$HOME`. One model loaded once; every user sovereign. The
  owner's own token stays `0600`; the shared copy is re-synced by `spark
  share on` and the new `share` check row warns if it drifts. Explicit, not
  automatic: which engine answers is always the user's own `spark client`
  choice. Linux (a shared workstation); macOS and WSL keep one user per box
  in this version. `spark check` gains the `share` row (36 rows).

## v1.21

- `spark drill` (contract 13): a source on stdin becomes practice
  questions it answers. The model proposes a verbatim span of the source
  as each answer and a question that span answers; an item whose answer is
  not in the source is dropped before it is ever asked, and a source too
  thin to drill is one line, never padded from the model's own knowledge.
  Self-graded -- you see the source's own words and say whether you had it;
  the answers are graded on this machine and never sent. `--name` keeps a
  schedule: a missed item comes back on a widening interval (1, 3, 7, 21,
  60 days) until it is right twice in a row, the one ledger kind that
  schedules rather than suppresses. `--ledger [clear]` lists or drops it.
- `spark watch` (contract 14): a live stream on stdin -- a log tail, a
  build, a migration -- watched for the one thing you named. Silent until
  a line matches, then one line quoting it; the quote is checked against
  the stream, so it cannot report what is not there, and silence is the
  healthy state. A window is a few lines or a few seconds, cheap enough to
  leave running, and a brain that comes and goes underneath it is ridden
  out rather than fatal. The stream never leaves the machine.
- `spark edit --watch FILE`: the live form of the editor's `?`. It watches
  a draft on disk and comments on each stanza as you save it, reviewing the
  whole draft when you pause. Grounded like every `?`; the writer answers
  back through the Alt-s ask key, not a built-in chat.

## v1.20

- `spark read` (contract 11): the source on stdin -- a page, a message,
  a document -- a question in the words, and an answer that says only
  what the source says. Every line quotes the source and the quote is
  checked; a line whose quotes are not in it, or that quotes nothing,
  is dropped before the reader sees it. When the source does not
  answer, the reply is one line showing the source's own opening words,
  composed in code, never a model's guess. A source past 16 kB is parts
  (`--part N`), and the answer's first line names the part it read.
  `--name` records the question in the ledger (kind `read`, never
  suppressing -- a source does not change); `--ledger [clear]` lists or
  drops. The second verb through the gate `spark ask` landed.

## v1.19

- The shell layer lives in its own repository:
  github.com/forgewright-ai/spark-shell. The tools, the starship and
  Nerd Font pins, the rc files, the terminfo entry and the rendered
  look (tmux, starship, btop, micro's colorscheme) install from there
  (`spark-shell on`), read `~/.config/spark/theme.env` -- the palette
  `spark theme NAME` writes -- and re-render on `spark-shell apply`.
  spark keeps no shell code, no shell package, no gate: 35 check rows
  now, and a first install touches nothing but the AI.
- What was appliance behaviour stayed, ungated: `spark quiet
  login|boot` (the silent login and boot) and the bar line -- bare
  `spark bar` or `spark bar line` prints the machine's one-line status
  for any status bar to run.
- Moving off the old built-in layer is automatic: bootstrap's
  `shell-moved` row hands the rc files back from their `.bak` on the
  first `spark update`, rendered files keep working where they are and
  spark-shell adopts them; `spark shell` and `spark bar on|off` answer
  with a pointer for this one release.

- The code now speaks the four value areas. `spark edit` (contract 10)
  has its own module beside `spark ask`'s; `spark model` / `spark ember`
  moved out of site.py into model.py; the shell layer's switch and
  hand-back live in shell.py; site.py keeps the site.env custody, the
  rc hook and the machine-shape verbs. One dispatch table in bin/spark
  lists every verb. No verb, flag or message changed.
- One home for every decision. bootstrap.sh no longer computes its own
  answers in sh twins: lib/spark/facts.py prints the machine's facts
  (distro, build, WSL, memory, the engine's home and flavour, the model
  picks) from the same code the verbs use, and bootstrap eval's them.
  The llama.cpp pin moved to engine.env (version + one sha per
  flavour), read by both sides.
- Bring your own engine, on Linux too. On an architecture spark has no
  pin for, a `llama-server` already on this machine (`$PATH`,
  `/usr/local/bin`, `/usr/bin`) is found and served with -- the engine
  check row reads `(your build)`. macOS keeps its Homebrew probe; a
  pinned build still wins where one exists.

## v1.18

- Intent search: describe a command you ran, and the line that ran comes
  back. `Esc r` sends your shell's own history (`fc -ln -400`, bash and
  zsh) to `spark recall <words>` on stdin; the model matches meaning, and
  every candidate is checked against the history (`text.anchor`) so what
  lands in your prompt is always a line you actually ran, never invented.
  `Esc r` again cycles the matches. `Ctrl-R` is left to the shell and to
  fzf -- an instant key stays instant, and a dead brain costs nothing.
  No new contract: the grounding law is borrowed. Nothing is written; the
  turn record is numbers.
- A command pasted from a page is rewritten for this machine. The prompt
  line's prefix now names this OS's side of the pairs a paste crosses
  most -- `free`/`vm_stat`, the package managers, `systemctl`/`launchctl`,
  `xdg-open`/`open`, `ls --color`/`ls -G` -- and tells the model to
  rewrite the other side and say so in the hint. This OS's half only, so
  the prefix stays byte-stable per machine and the prompt cache keeps
  hitting.
- The failure moment goes further, twice. After the explain, a second
  `Esc s` proposes the corrected command in your line -- the command and
  its exit code ride to `spark line`, which answers with a fix through the
  cmd path, and nothing runs until Enter. And a `command not found` (exit
  127) offers the line that installs it: a tool spark itself installs is
  named here with no model call (`packages.package_for` -- fd is fd-find
  on Debian, fd on Arch and macOS), the rest through the model. Both ride
  the same hook the widgets already keep, in both shells; no new check row.
- Blast radius: a recursive `rm` at the prompt earns its numbers beside
  the `!`. `? clean the build dir` that comes back `rm -rf build` now
  reads `<- 1,204 files, 3.1 GB, 2 tracked by git -- ...`: the count of
  files, bytes and git-tracked files under the paths, worked out from the
  command spark already has -- nothing the model proposed is run. Only a
  recursive `rm` (a glob or a plain delete says nothing), the walk is
  capped so a huge tree cannot hang the prompt (the count ends `+` then),
  and `spark do` shows the same line above its `yes`. The facts lead the
  hint so contract 4's cut eats the model's words, not the numbers.
- `spark ask` survives a model that wraps its questions. The brief said to
  point at the text "by quoting it between double quotes", and small
  models read that as wrapping the whole question -- every line then ended
  in a quote mark and the law (`it ends in ? or it is not output`) dropped
  all of them: on the box, two different models produced zero questions.
  The brief now says the quotes go inside the question, never around it,
  and a line that still arrives as one wrapped question is unwrapped
  before the gate reads it -- its inner quotes are then exactly the spans
  the grounding law judges.
- Signed lines name verbs that exist. `spark serve off` still answered
  `spark stop -- stopped`, and the tune report signed itself `spark tune`;
  both verbs were removed in v1.17 and nothing looked at the strings that
  named them. `tests/docs_test.py` now reads the verb table out of
  `bin/spark` and refuses any `%s <verb> --` line whose verb is not in it.

## v1.17

- `spark uninstall` no longer deletes the script it just told you to run.
  The undo pass is the one root step that runs `bootstrap.sh` rather than
  a command of its own -- bootstrap is what knows how to unmask sleep,
  drop the lid file and put the motd and GRUB back -- so when it cannot
  get sudo, its remedy is "run ./bootstrap.sh". The clone was then
  removed a few steps later, leaving an instruction nobody could follow
  and a machine still half spark's. The clone stays while that is
  outstanding, and says so.

- The core documents are the core. `spark help`, `CHEATSHEET.txt`,
  `README.md` and `INSTALL.md` no longer carry the shell layer or the
  apps: `spark shell` and `spark bar` moved to `SHELL.md`, and the apps
  to `APPS.md`, each with one pointer line left behind. INSTALL loses two
  sections and renumbers; the app table the README carried is APPS.md's
  now, and `tests/docs_test.py` reads the app names from there.
- The landing rule binds core documentation, and core documentation moves
  with a release. `APPS.md` and `SHELL.md` sit outside it: kept true as
  things change, no release waiting on them, nothing in them owed to
  help, the cheatsheet or a changelog entry. Both say so in their first
  lines and docs_test checks that they do, so neither drifts back under
  the rule unnoticed.
- `spark help` reads the same whatever the shell layer is doing. It had
  two versions of its interface block and picked one by reading
  `site.env`; with the gated verbs gone there is one block, and help no
  longer reads config at all. `spark theme` and `spark font` stay in it:
  they are core, and a machine has a face with the layer off.

- An install says what it changed, not what it checked. A converged
  machine printed 54 rows of `ok` and `skip` from `./bootstrap.sh` and 18
  more from `install.sh`; both now print what they changed, what needs
  you, and the summary -- so `Nothing to do` is usually the whole of it.
  `--verbose` brings every row back, and `--dry-run` is untouched,
  because that one is the report `spark check` and the tests read.
- The sudo password is asked for once, at the start, before anything is
  touched. It used to be asked at whichever row first needed root, half
  way through a run that had already changed things. If sudo is not on
  the machine at all, that is one line and exit 1 up front rather than a
  failure later. Only at a terminal: over ssh or a pipe there is nobody
  to answer, and a run that needs no root -- `spark update` on a
  converged machine -- is never made to ask.
- `spark theme list` is in `spark help` now, and `spark ember list` in
  both help and the cheatsheet: the grammar names four verbs that take
  `list` and the docs described two of them. The cheatsheet also names
  `auto` and `none` for `spark model` (it showed them for `ember` and
  hid them for `model`, whose default is `auto`), spells the mute the way
  help does (`spark off | on`), and writes `<words>` where it had `WORDS`.

## v1.16

- `spark ask` (contract 12): a plan, a draft or a decision on stdin, and
  at most three questions about it back -- one per line, nothing else.
  The shape is the law, not a request in a brief: a line that does not
  end in a question mark never reaches you, and neither does one whose
  every quoted span is missing from the text, one that could be asked of
  any plan, a repeat, or a question you have already answered
  (`spark ask --answered --name NAME`, `--ledger [clear]`). Three is a
  cap, never a target: when nothing survives, stdout stays empty and one
  line on stderr says so, exit 1. At most 12 kB in; `--thread ID` keeps
  a round going, and a follow-up obeys the same law -- the moment a
  reply may assert, that is `spark chat`.
- One switch vocabulary for both servers. `spark serve` used to start a
  server when a bare verb is supposed to show, and stopping it was a
  top-level `spark stop`, while the FORGE had `on|off` for the setting
  and `start|stop` for the same thing by hand -- four words for two
  states, and two grammars for one kind of thing. Now both are
  `spark <verb> on|off`, bare shows (`spark serve` reports the url,
  whether anything answers, and the model), and `--force` and
  `--noreload` are flags of `off`. `spark stop` and `spark forge
  start|stop` are gone rather than kept as aliases: there is nobody to
  keep them for yet. The check rows that named the old verb name the
  new one, which `spark check --chaos` proves by running each remedy.
- Memory lives under its own noun, like the soul. `spark remember
  <words>` and `spark forget N` were top-level verbs while the other
  half of the same identity was `spark soul edit|reset`: two shapes for
  two halves of one thing. It is `spark memory add <words>` and `spark
  memory forget N` now, beside the `on|off` and `clear` that were
  already there. The widget composes the new line too -- the fact `Esc
  s` offers to keep after a fix lands in your buffer as `spark memory
  add '...'`.
- Three smaller harmonies. `tune` was a flag and a verb at once
  (`spark bench --tune`, `spark tune show`); it is a sub-noun of the
  thing it belongs to now -- `spark bench tune [show|apply]`. The
  `spark ledger` tombstone from v1.7 is gone: it existed to tell people
  where the ledger went, and there is nobody to tell yet. And the signed
  first line uses one separator, `spark <verb> -- <one line>` as
  contract 8 says; the glyph separator is for fields inside a line, not
  for the signature, so `spark theme` and `spark model` no longer sign
  differently from `spark shell` and `spark forge`.
- A mode is named for what spark does. `ask` meant spark answering your
  question, which read backwards next to `spark ask`, where spark is the
  one asking: the mode is `answer` now, and contract 10's `edit-ask` is
  `edit-answer`. `ask` is left free rather than reused for contract 12 --
  a string that changed meaning would make the turn records already on
  disk lie about themselves. The old names are read for one version, the
  way `talk` is read for `chat`, and `/api/chat` takes either.
- The grounding law is one place now, `lib/spark/text.py`: `anchor()`
  checks a span, `Ground.verdict()` a whole note or question, and `Gate`
  is the stream that marks what it keeps and drops what it refuses.
  `Anchors` (contract 10's marker) is that gate with nothing refused, so
  `spark edit ?` behaves exactly as before -- its own tests are the
  proof. `session.reading()` and `forge.text_sha()` / `same_text()` come
  out of the editor's path for the same reason: the next contract needs
  them, not a copy of them.
- The ledger holds more than the editor's declined notes: one sealed
  file, one record shape, and a kind per contract -- and the rule that
  retires a record belongs to the contract that wrote it
  (`ledger.RULES`), because a rule that generalised would fit none of
  them. A note declined in a draft retires when its quote leaves the
  text; a question you answered stays answered.
- A `ledger` check row: sealed, 0600, what is in it and how much room is
  left before the oldest records go. The `users` row watches the ledger
  file too, so a plaintext one cannot sit unseen in a sealed store.
  `spark check` has 40 rows.
- Contracts 11 (`spark read`) and 13 (`spark drill`) are written down and
  not built: their text is in ROADMAP.md and in `lib/spark/read.py` and
  `lib/spark/drill.py`, nothing dispatches to them, and their cases in
  `tests/smoke.py` are marked skipped with the reason.
- `spark check --chaos` rehearses the failures: it breaks a throwaway
  machine one known way at a time and proves the right row says so and
  the remedy that row prints heals it. `--selftest` proves a row can
  flip; `--chaos` proves the sentence under it is true. Nine scenarios,
  each on ports of its own, so a machine that is serving is left alone.
- A reply cut off mid-stream is an error, not half an answer. A severed
  connection is not an end of stream: the read simply stops, so a killed
  server handed back a truncated answer looking whole, and exited 0. The
  turn still lands -- the question and the words that did arrive go on
  the thread, the way they do when you press Ctrl-C.
- A download that dies leaves nothing behind. `bootstrap.sh` removed its
  partial file only on a sha256 mismatch; a curl that failed left a
  `.part` on the disk that was already full. `--fetch U D S` runs the
  download primitive alone, so that failure can be rehearsed.
- Two `spark update` at once: the second refuses rather than race the
  first through a checkout. Both locks refuse alike now -- `spark serve`
  said it on stderr and exited 1; a lock another process holds is a gate
  refusal, so it is signed and exits 2.

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
