# Changelog

## v1.7

The server keeps no prompt cache in RAM.

- `spark serve` passes `--cache-ram 0` (single server and both router
  presets). llama-server's default keeps every replaced prompt's KV state
  in host memory up to 8 GiB, more than a small box has: a 12B model on a
  16 GB APU climbed from 32 % to 90 % RAM in a day and started swapping.
  The four slots still hold the recent prompts on the GPU; a prompt that
  comes back after four others costs its prefill again (about 8 s per
  1000 tokens on that box). `SPARK_EXTRA_ARGS=--cache-ram N` in
  `spark.env` sets a budget in MiB for those who want one.
- The `serve` check row reads the running server's arguments: `no host
  cache`, or the budget you set, or a warning when an older start still
  caches (restart the unit).
- The micro plugin (1.0.1) survives its own mistakes: every job callback
  runs protected, so a Lua error becomes an infobar line instead of a dead
  editor with a stack trace. A rewrite checks that the text it was given
  is still where it was; when the buffer was edited meanwhile the answer
  opens in a read-only pane instead of being spliced over a stale range.
  Two pty cases prove both.
- The docs keep themselves true: `tests/docs_test.py` (pre-commit, CI)
  checks every palette's and every model's upstream is in `CREDITS.md`,
  the check-row and model counts the docs state are the tree's, every
  page has its source file, and no retired list word survives.
- `CREDITS.md` names all six palettes with their own license (Tokyo Night
  is Apache-2.0) and every model family's upstream.
- The page's models table drops the note column; `models.env` ships no
  notes (the key stays, optional, for your own rows).
- The page renders a CHANGELOG section above the newest tag as
  `vX.Y (unreleased)`; `tests/docs_test.py` refuses a heading more than
  one release ahead of the tag. The sign line and the changelog agree.
- Every quote in a `?` answer is checked against the text. The answer
  streams line by line; a quoted span the text does not hold -- verbatim,
  with whitespace folded, or with the punctuation tucked inside the quote
  stripped -- is followed by `[not in the text]` where it stands, so a
  misquote (an earlier tool of ours turned "plum" into "plume") never
  reads as the author's words. The brief asks for double quotes, never
  across a line; the turn record counts `quotes` and `unanchored`.
- A `?` about a selection sees the file around it: `spark edit ? --sel A
  B` takes the whole file on stdin and sends one 16 kB window -- the
  selection between two mark lines the brief knows, the file before and
  after it -- so a question about a paragraph is answered in the light
  of the chapter.
- A `?` can go on: `spark edit ? words --thread ID` keeps the exchange
  under an id of the client's choosing, sealed in your account's store
  like a chat thread and pruned with it; the same id again continues it,
  sending the words alone while the text is unchanged and the text again
  when it is not. Without the flag nothing is kept, as before.
- A declined note retires. `spark edit --decline --name NAME` keeps the
  note on stdin in a ledger, sealed in your account's store by file name;
  the next `?` about that file is told not to raise it again. A note
  leaves by itself once the words it quoted have left the file, or after
  `SPARK_HISTORY` days. `spark ledger [NAME]` lists them, `spark ledger
  clear [NAME]` drops them.
- A client stays a client. `spark model` on a client showed its own RAM
  and a budget for a machine that serves nothing, and `spark model NAME`
  there quietly made it a server (the same steps as `spark client off`).
  Now `spark model`, `ember list` and `model budget` on a client print
  the peer's table -- the FORGE's new `GET /api/models` (any logged-in
  user): its RAM, budget, picks and speeds -- or the rows alone, without
  a verdict, when the peer is a bare server, down, or older; `bootstrap.sh
  --list-models` does the same. `spark model NAME|auto|none`, `model
  budget N`, `model rm` and `spark ember NAME` are refused on a client
  with one line; `spark client off` remains the one way to serve again.

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
