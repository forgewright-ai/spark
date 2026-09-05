# Changelog

## v1.3

The CLI experience wave. A few days of living with spark taught one
lesson: the machine works, the conversation with it was rough. This
release is one grammar for every verb, a machine that explains itself,
and long output you can actually read.

The grammar, written into `CLAUDE.md` beside the contracts: a bare verb
shows and never mutates (`spark bar` included -- bare shows now,
`on|off` sets; tmux still always gets its line); `on|off` is the only
switch vocabulary at the CLI while the stored keys stay `yes|no` --
the verb translates; `status` is an alias of bare and `list` the table
word; every verb answers `-h` first, signed; one confirm shape
(`<question>? yes/NO: `, `confirm()`), one progress vocabulary (curl's
bar for downloads, one dot-spinner -- `wait_ready()` -- for every wait
on a server coming up), and one exit-code law (0 ok or show, 1 the
world, 2 the invocation, 78 misconfiguration, 130 SIGINT). A verb that
breaks a rule is a bug now, not a style choice.

`spark quiet` replaces `spark bootconfig`, which exits 2 naming the new
verb (`spark talk` goes the same way, naming `spark chat`; the API
keeps accepting the old mode word). Bare `spark quiet` shows three
states. `login` and `boot` are the old Linux motd and kernel-line
switches, and `boot on` now means a genuinely silent boot: one
removable drop-in in `/etc/default/grub.d` hides GRUB's menu, quiets
the kernel line and asks systemd for errors only (hold Shift at boot
for the menu). The new `start` switch (`SITE_QUIET_START`, both OSes)
silences spark itself: no login banner, one-line `spark serve` and
`spark forge`, one-line bare `spark` -- `spark status` stays full.

Long output pages. The help, the check report, the model and theme
tables, the history and the stats go through `$PAGER` (`less -R -F -X`
when unset) at a terminal, colour stripped on the way in -- inside a
pager it is either rendered or garbage; piped output never sees a pager
and stays byte-identical, and an absent pager falls back to plain print
(less is not guaranteed). Text-first means the pipe contract is
untouched. `spark help` itself is rewritten, not patched: every verb
and the flags that matter, grouped so a new user reads the top and a
daily user finds the bottom; the pager carries the length.

Chat finds its way back. `/resume` lists the newest five threads and
`/resume N` (or a thread id) switches to one; `/clear` wipes the screen
while the thread goes on; `spark chat --thread N [words]` continues an
older thread straight from the command line, the one-shot form
included.

The machine explains itself, twice over. The line and chat prompts
learn spark's own command surface, so `?? how do I change the theme`
answers naming `spark theme` -- proven live on a box, the same way a
model row is proven on the line. And TAB completes: the first word
offers the verbs, the second each verb's words -- theme and model names
included, resolved offline through the `spark` symlink -- in bash and
zsh, wired by the core hook, no key bound. A `completion` check row
watches the wiring.

The first run looks right. `spark setup` asks a fourth question,
`theme [gruvbox-dark]:` (the default is only the default answer;
`site.env.example` stays `SITE_THEME=none`), and the chosen palette
lands on every surface at once: the Linux text console (a precomputed
`console-colors` palette the rc hooks apply only when `TERM=linux`),
micro (a rendered `spark` colorscheme plus a seeded `settings.json`)
and tmux -- one look from minute one, watched by a new `theme` check
row. Two palettes join, nord and tokyonight-night, and the two theme
validators (`lib/env.sh` and `config.py`) now require the same 21 keys;
the tests render every palette by glob, so a gap in a new one goes
loud. `spark shell off` hands the look back too: tmux, starship, btop
and the micro files come back from `.bak` or go, the way the rc files
always did. And `spark font` leaves the shell gate -- the console font
is the machine's face with the layer off too; the new `spark font list`
shows the real faces and sizes in `/usr/share/consolefonts` and a face
or size not there is refused before anything is written. 36 check rows
now.

Fixes from first-session use. A misspelled verb with arguments (`spark
quite start on`) became a question to the model; it is a did-you-mean
at exit 2 now. Bare `spark` under quiet start said `ember` when a
single model serves both roles; it names the truth. `spark update`
twice mixed the running process with the tree it had just pulled (an
ImportError mid-deploy); after a move it now execs the fresh
`bin/spark`, so bootstrap and the recheck always run in the new code.
And `spark shell off` could strand a console login by leaving an empty
`~/.bash_profile`: a restore never leaves a husk now, and a new
`rc-login` bootstrap row gives a regular `~/.bash_profile` that never
reaches `~/.bashrc` the same marked hook line.

The conversational modes now rule out markdown at the source: replies
are plain text for a terminal, commands on their own indented line --
no renderer, no pandoc, no wasted marks.

## v1.2

The page wears the brand. The FORGE's client page is redesigned around
the ember palette: dark is the default, light answers the browser's
preference, and everything is mono. The old neutral default is gone --
there is no plain look to fall back to; a `spark theme` palette still
overrides every colour, as it always did. Transcript rows carry marks
instead of labels (`*` the answer, `>` you, `!` an error), a caret
blinks while an answer streams, every fenced block has a copy button, a
stop button (and Esc) ends an answer and keeps what arrived, and the
keyboard grows `n` (a new thread) and `j`/`k` (the next and previous
one). On the config page the ember picker now really runs `spark ember`
on the box (`ember` joined the `/api/run` allowlist), and the headless
switch is gone: it could never work through `/api/run` -- `spark
headless` needs sudo on macOS -- so the verb at the prompt is the way.
On an iPhone, share -> add to home screen makes the page an app:
the server now answers `/manifest.webmanifest` and draws its own
`/apple-touch-icon.png` from the banner grid -- no binary in the repo.
Android grants a standalone install only to a secure context, so over
LAN http the home-screen shortcut keeps its icon but opens the page in
the browser; `INSTALL.md` explains.

The same page now also runs inside sparkapp, the desktop shell for
macOS and Windows (the app it ships is simply named spark): there the
login card asks for the FORGE's address as well
as the token, log out forgets the stored token, and `q` quits the app;
pointed at a bare llama-server instead of a FORGE it falls back to chat
only, threads and the other tabs waiting for a FORGE. In a browser
nothing changes -- the desktop parts stay hidden.

## v1.1

The `peer` check row understands a FORGE: `SITE_PEER_AI_URL` pointing at
another machine's `:8081` (the shape `spark forge --print-client` hands
out) showed `down` because a FORGE answers `/api/health`, not a
llama-server's `/health`. The row now asks the FORGE first and reports
`forge <host> ok`, or `up, its model loading|down` when the FORGE stands
but its model does not; a raw `spark serve` URL reads as before.

`spark check` over a plain ssh command (`ssh host '~/.spark/bin/spark
check'`) no longer reports spark and starship missing: a non-interactive
shell never sourced the hook that puts `~/.local/bin` on PATH, so the
check now looks there, and in Homebrew's bin, itself.

The client shape. A machine with `SITE_AI_MODEL=none` and a peer URL
runs nothing of its own and is now treated that way end to end: `spark
client URL` writes both keys, applies the prompt hook and the widgets,
and says the `scp` of the ember-token; `spark client` shows the state and
whether the peer answers; `spark client off` is `spark model auto`.
bootstrap skips the engine and the units, `install.sh` links no unit and
renders no plist, and `spark check` reads the engine, services, watchdog,
ai, serve and forge rows as `na` (a fourth `--selftest` pass proves it) -- the peer row
is where a client's health lives. `spark forge --print-client` names the
verb. Before this a client's check showed three red rows for things a
client should not have.

## v1.0

The ignition. One line -- `curl -fsSL .../get | sh` -- or a clone and
`spark setup`, and a fresh Debian 13 or macOS has a private local AI at
its prompt: `? how big is this dir` puts a command in your line with a
hint above it, `cmd 2>&1 | explain` says what went wrong, `spark chat`
is a conversation. Nothing leaves the machine but apt or brew and the
pinned, sha256-checked downloads. The line and the ember are the proof
that a machine of yours can carry its own intelligence, not the
product; the product is the FORGE it builds and keeps. spark is public
now, under the MIT license (`LICENSE`, verbatim, ASCII like every doc).

`get` clones spark to `~/.spark` (or pulls it: the same line is the
updater), refuses a directory that is not spark, wants git, a python3
of 3.9 or newer and, on a Mac, the command line tools, and never runs
sudo. It hands over to `spark setup`, which asks three things -- this
machine's name, yours, and the model from the table this machine earns
-- and never asks for a password, an account or a key; sudo happens
once, for apt on Linux, and setup says so before it does. Stdin that is
not a terminal takes every default; `--yes`, `--model`, `--name`,
`--user` and the environment pre-answer the same things. It writes
`site.env`, runs bootstrap on the terminal (progress bars and all),
waits for the brain, asks the first question for you and prints the
speed it measured. `tests/get_test.sh` proves the one-liner
hermetically: a throwaway HOME, a bare `file://` clone, a sudo that
shouts, the refusals, the pipe form, the second run pulling, the
hand-off.

Two layers. `SITE_SHELL=off` (the default) is the AI only: the engine,
the token, the tools in `~/.local/bin`, the widgets, the units -- and
one marked line appended to your `.bashrc` or `.zshrc`, sourcing
`~/.config/spark/hook.bash` or `hook.zsh`; core never links your rc
files. `spark shell on` is the workstation: tmux, starship, micro, fzf,
zoxide, eza, bat, btop, the Nerd Font, the theme, the console, and the
rc files become spark's own. Every shell-layer check row reads `na`
while the layer is off, `--selftest` runs a third pass to prove it, and
`spark help` folds the layer's verbs into one `spark shell on` line.

One model by default: `SITE_EMBER_MODEL` is `none` now, the spark model
answers everything, and an ember is a choice (`spark ember`). The
engine is the pinned llama.cpp tarball on both OSes -- six flavours,
sha256 each, a `flavour` file in the engine dir that the new `engine`
row names; Homebrew is the shell layer's only, and the AI needs nothing
from it. `spark model list` and setup's table carry a speed column:
tok/s measured where a bench baseline or a turn from a server on this
machine recorded one, an estimate from the RAM and the backend
otherwise (marked `~`), so the choice is made on a number. Found in the
first fresh-account proof: `SITE_AI_BUILD` is `auto` now -- the Vulkan
build, its two Mesa packages under the same sudo and the vulkan speed
column wherever a GPU reports its memory in sysfs, `cpu` otherwise, the
`gpu` row naming the build and bootstrap replacing an engine of the
other build. Found there too: `auto` picks the largest model that fits
the budget and stays under the build's speed cap (3 GB files on cpu, 6
GB on vulkan, 20 GB on metal: about 8 tok/s or better), the header says
what the cap held back, and a name is never second-guessed. The units
warm the model after `/health` answers (`spark serve --warm-when-up`),
so the first question after boot does not pay for the load. And
bootstrap's launchd rows skip, with the reason, where there is no gui
domain -- ssh with nobody at the console, a CI runner -- as the systemd
rows do without a user session.

The privacy word list left the tree: `~/.config/spark/privacy-terms`
(0600, one word per line, `SPARK_PRIVACY_TERMS` overrides) on each
machine, the `SPARK_PRIVACY_TERMS` repository secret in CI; the hook
and the `privacy` row read the union with the committed
`.privacy-terms`, which holds no personal word. One release control now:
there is no `VERSION` constant, `spark ver` derives it straight from git
(`lib/spark/version.py`, cached), `get` lands a fresh clone on the newest
release tag (`SPARK_REF` for a developer clone), and the new `spark
update` moves a checkout to that tag or pulls a branch, then converges.
`release.yml` turns a
`v*` tag on a green commit into the GitHub Release, the notes that
version's CHANGELOG section, and refuses a tag the CHANGELOG heading or
`spark ver` do not match. CI grew a Debian 13 container job -- a user made
for the run, sudo without a password, the one-liner in pipe form from
the tree under test, converging to `Nothing to do` -- and the macOS job
applies the real core bootstrap and then the shell layer on top of it,
where the old dispatch-only brew job used to be. `tests/bench_smoke.py`
is in the pre-commit hook and CI in fact; v0.4 said it was.

Three model lists now, plus yours. `models.env` is curated: open licenses
only, each row proven on the line before it lands, and the only file
`auto` reads -- qwen3-14b joins it (Apache-2.0, the large Metal slot),
gemma3-12b leaves. `embers.env` names a purpose and a license per row --
Qwen2.5-Coder-7B for code, Qwen3-4B-Thinking for reasoning -- and `spark
ember list` shows both under their rows. `community.env` is untested, at
your own risk: any license, named per row, a `yes` before the download;
gemma3-12b lives there now, under Google's Gemma Terms of Use, no longer
fetched anonymously. `~/.config/spark/models.env` holds your own rows.
The table marks a row `?` community, `e` ember, `u` yours; a name in two
files is refused, naming both. A row in any list is a pull request.

`spark model add URL [--sha256 HEX] --license "NAME URL"` writes your row:
a huggingface.co URL is auto-verified from its LFS headers for the size
and the sha256, any other host needs `--sha256`; the license is required
even for your own file, then the download runs through the same sha check
as every other row. `spark model verify` re-hashes every downloaded file
and never deletes one -- a mismatch is reported, the remedy is `spark
model rm NAME; spark model NAME`; the new `models` check row runs the
same check daily, cached. `spark model budget [N]` and `SITE_AI_BUDGET`
replace the 60% that used to be baked into nine places in the code and
the docs; the budget is a choice now, 10 to 95.

The ember is a second brain, said out loud for the first time: setup's
closing block gains a line naming it, the help line calls it a second
brain for conversations, and `spark ember list` shows each ember row with
its purpose.

`spark chat` wraps a reply at the terminal's width, one mark on the first
line, a blank line between turns; the up arrow recalls past lines
(readline, `~/.local/state/spark/chat-history`, 0600, off with
`SPARK_HISTORY=off`). Ctrl-C cancels a reply in progress, not the chat --
`* (stopped)`, and the partial reply is kept, marked `partial`. Slash
verbs: `/help /new /last /model /q`; an unknown `/word` is refused, never
sent to the model. llama-server stops generating when the client hangs
up -- observed on the box, GPU load drops to 0% right after a cancel.

`CREDITS.md` names every project spark downloads or installs, with its
license; spark vendors none of them, bootstrap fetches pinned upstreams
to your machine and apt/brew install the rest from their own
repositories. `spark ver` names the engine's license and points at the
file for the rest. The banner is spark's own artwork.

Measured on a fresh Debian 13 account over ssh (an AMD iGPU, vulkan,
the 4.7 GB qwen3-8b at about 8 MB/s from huggingface.co): the one-liner
to the end of setup in 10 min 3 s, the first answer at 10 min 19 s, the
download 8 of those minutes; `spark check` with no row failed, the first
question at 8.4 tok/s on the GPU. On a fresh macOS account (an M4 with
24 GB, the 6.8 GB gemma3-12b): the one-liner to the closing block in
16 min 25 s, download included, the first question at 13.0 tok/s on
Metal, every check row green; the one thing macOS adds is its own
dialog asking whether python3 may reach the local network -- that is
the FORGE binding your LAN address, and the answer is yes. The curated
pick on that Mac is qwen3-14b now (Apache-2.0), measured at 11.6 tok/s
on Metal; gemma stays, named, in the community list.

The default soul is a template, not a fixture: `spark soul edit` is meant
to replace it on day one. The FORGE's page is a client page in the
browser, one among several -- not a phone product.

## v0.4

The ember. One llama-server now serves two models. When
`SITE_EMBER_MODEL` (`auto|none|name`, default `auto`) resolves to a
second model, `spark serve` starts llama-server as a router:
`--models-dir` on `~/.local/state/spark/router/` -- two symlinks,
`spark.gguf` and `ember.gguf` -- with a `presets.ini` spark renders,
the spark role at context 4096 with `reasoning = off` (a thinking model
answers the prompt line plainly), the ember at `SPARK_CTX`, both with
the tuning keys. One process, one port, one api-token; the request's
`model` field routes. `auto` means spark is the small one: the smallest
row of `models.env`, the ember the largest that fits beside it in the
60% RAM budget; nothing fits, or `none`, and one model plays both roles
exactly as v0.3 did (`--alias spark,<stem>`, so contract 5 still prints
the file stem). `spark serve` warms both children after `/health` and
says which answered; `bootstrap.sh` picks, downloads and lists both
roles (`--list-models` marks `*` spark, `+` ember).

The rule is one sentence: the prompt line is spark, every sentence is
an ember. The session derives the role from the mode -- `line` sends
`model: spark`, everything else `model: ember` -- and the identity
(soul, memory) rides only with the ember: a spark request is machine
facts and the line grammar, cheap and byte-stable, whether it goes to
the FORGE or straight to the engine. The FORGE defaults a missing
`model` to `ember` and injects the identity only then, so any `/v1`
client gets the box's identity unless it asks for the bare line model.
`/api/health` gains `models` (each role, `loaded|unloaded`); `spark
brain` and `spark status` list both roles; `spark brain --porcelain`
still prints the spark role's stem (contract 5).

`spark ember [NAME|auto|none|list]` is the choice's verb: it sets the
key, downloads through bootstrap and restarts the router; bare, it
shows both roles and their loaded state; `list` is the one model table
with `*` for the spark pick and `+` for the ember. `spark bench`
measures the ember when one serves (`--spark` and `--ember` force a
role; baselines stay per file). Check rows: new `ember` (CAPABILITY --
none on purpose, not downloaded, not warm, or the pair over budget,
with the numbers); `ai` shows both roles; `serve` says `router, 2
models` or `single`; `gpu` sums both files against VRAM. 31 rows now.
`SITE_EMBER_MODEL` joins contract 3.

Two tokens on the FORGE, two faces on the page. A second 0600 token,
`~/.local/state/spark/ember-token`, logs a browser or a bearer in as
user: chat, threads, the soul and the memory, the palette, and a
read-only monitor. The forge-token keeps the whole box: every verb,
`do`, config, serve, bench, the log. One login field; whichever token
matches decides the role, `GET /api/me` tells the page, and the page
draws only what the role can do -- a user hitting an admin route gets a
quiet 403 "this needs the admin token", never a login loop. `spark
forge --print-client` now hands a peer the user token (the URL, the
ember-token's `scp`, and a reminder that admin stays on the box);
`spark forge --print-url [--user]` prints a role's login URL and token;
`spark forge token --new [--user]` rotates one role and kills exactly
its logins. The admin page gains the ember picker, the role marks in
the model table, the two rotate buttons and a headless switch. The
`forge` and `privacy` rows watch both tokens; contract 9 lists the
admin-only routes. `tests/bench_smoke.py` joins the hook and CI.


First-session fixes, from a stranger's first ten minutes. The
conversation verb is `spark chat` (`spark talk` still dispatches,
silently, for one version; old records keep mode `talk`, new ones write
`chat`); its prompt is `chat> `, one intro line names the exits, and a
generous quit grammar ends it silently -- `/q`, `/quit`, `/exit`, `:q`,
`:quit`, `:wq`, `quit`, `exit`, `bye`, Ctrl-D -- closing the trap where
`:q` went to the model, which role-played "Exited." while the REPL lived
on. Blank input asks nothing. Replies in a conversation print bare (a
dialog needs no mark), and the answer and warn marks everywhere else are
now the same ASCII pair on both OSes (`*`, `!`) -- one mark, both OSes;
the check report's glyphs are untouched. A conversation also sheds the
shell costume: its system message is one machine line plus the identity
and the mode, not the package-manager, tools and flags brief the prompt
line needs -- byte-stable per mode, so the prompt cache keeps hitting.
And a head-word guard: a proposed command whose first word no binary or
shell builtin here answers to is re-asked once with "X is not installed
on this machine" (`spark line`; failing that, the hint says `X: not on
this machine`), and in `spark do` such a step is never offered to run --
the same sentence goes back as feedback and the loop continues. `free
-h` on a Mac dies here now, not in your terminal.

From use, a provenance guard on `do`: a done summary is only a claim,
so its numbers are checked against what the run actually printed --
the goal, each step's output, the user's own words -- and a number
nothing produced marks the done line with the warn glyph and
`unchecked: no command produced N -- believe the outputs above`.
Mechanical and model-agnostic (digit substrings, commas dropped; exit
0 either way -- it is a label, not an error): one failure class closed
in code instead of a prompt rule. `spark do` also opens by naming the
model driving, and `/api/do/propose` carries both (`driver`,
`unchecked`) so the page shows the same.

Also from use: each turn records the model that answered it -- the
role's stem from the brain's roles map -- so throughput and stats judge
the right model instead of blaming the spark role for the ember's pace.
`/api/health` names each role's model file (`roles`),
the chat's `done` event says which model answered, and the page's
header shows every role the FORGE reports -- nothing about the pair is
baked into the page.

From a client machine (`SITE_AI_MODEL=none`, a peer's FORGE answers):
the ember's `auto` still chose and downloaded a model there, and with
a .gguf on disk the server and the FORGE came up beside it. No spark
model means nothing is served here, so there is no ember either -- in
`bootstrap.sh model_pick` and its python twin `engine.chosen_rows`
alike. CI had been red on exactly this since the router landed.

From the first day at a Mac's prompt: a question longer than the row
wrapped, and "the row above" the cursor was the prompt itself -- the
hint erased it and the command landed mid-hint. The zsh widget now
empties the line before it speaks, so the cursor is back on the
prompt's row (bash was never wrong: readline hands a `bind -x` command
the cursor at the start of that row). Both cut a hint to the width, so
it cannot wrap onto the prompt either. `widget_pty.py` proves it on a
real screen: a 40-column tmux pane, skipped where tmux is absent.

From the first headless day: on Linux the serving user joins the
`render` group (bootstrap row `render`; a logind seat ACL dies with the
console session, and new servers silently fell back to the CPU), and
the `gpu` row warns when the render node is not readable.

The machine says what it is doing. `spark model NAME` and `spark ember
NAME` announce a pending download (`ok  download  <file> (N GB)`) and,
at a terminal, hand bootstrap the terminal unfiltered: `fetch` names
the file and lets curl draw its progress bar, so gigabytes are visible
minutes instead of silence (captured output stays row-filtered as
before). A managed restart narrates both ends -- `restarting (the
model reloads, ~30 s)...`, then `ready` once `/health` answers -- for
`spark model`, `spark ember` and `spark tune apply` alike; `spark
serve` announces the warm-up before running it, and `spark bench` says
llama-bench is running and that the server is resuming. The client
lines now open with `for another machine to use this server:` -- the
old `on another machine:` heading read as a failure ("serving on
another machine") on first contact.

## v0.3

The FORGE. spark is the seed; the FORGE is the agent it builds and keeps
on the box: the model plus one soul, one memory and threads, served on
the LAN by `spark forge` (`lib/spark/forgeserve.py`, a stdlib HTTP server
in front of llama-server, bound to one LAN address, never `0.0.0.0`). A
second 0600 token, `~/.local/state/spark/forge-token`, gates it -- typed
once on the page's login (an HttpOnly, SameSite=Strict cookie derived by
HMAC) or sent as a bearer; the api-token never leaves the box. Any program
speaks to it at `/v1/chat/completions` and `/v1/models` (OpenAI-shaped,
streaming, the identity injected); `/api/*` feeds the page with the check,
stats, bar, serve, gpu, bench, config, theme, log and an event stream, and
takes chat, threads, do, soul, memory and an allowlist of verbs through
`/api/run`, so the page changes nothing except through the commands the
shell uses. `/api/health` answers without a token and is how a client
recognises a FORGE: another machine's `spark` then sends only its machine
facts and the line. The page under `lib/spark/forge/` (three ASCII files,
no inline script, CSP `default-src 'self'`) is the monitor, the chat, the
task runner and the settings, on a phone too. Verbs: `spark forge`
(status), `on|off`, `start|stop`, `--foreground`, `--print-url`,
`--print-client`, `token --new`. Keys: `SPARK_FORGE` (`auto|on|off`),
`SPARK_FORGE_HOST`, `SPARK_FORGE_PORT`, `SPARK_FORGE_TOKEN_FILE`. Units:
`spark-forge.service` and `spark.forge.plist`, twins of serve, enabled by
bootstrap where the model server is. Check rows: `forge` (CAPABILITY),
`services` and `privacy` extended. `spark brain --porcelain` grows a third
field, `forge|model` (contract 5); contract 9 documents the API.
`tests/forge_smoke.py` joins the hook and CI.

Who it is and what it remembers. `~/.config/spark/soul` is the paragraph
that tells the model who it is (`spark soul`, `spark soul edit`, `spark
soul reset`; a built-in paragraph until you write one; at most 4000
characters, 0600). `~/.config/spark/memory` is one fact per line (`spark
remember <words>`, `spark forget N|<words>`, `spark memory` lists,
`memory on|off|clear`; 40 facts of 200 characters, 2000 in all). Both are
config, not state: `spark history clear` and the history pruning never
touch them. The model never writes memory in this version; only you do.
Key `SPARK_MEMORY` (`on|off`). Check rows `soul` and `memory` (CAPABILITY,
fixture-tested). `SPARK_PERSONA_EXTRA` leaves contract 3: it is still read
as the soul's fallback in this version, the `soul` row warns while it is
set, and `spark soul edit` absorbs it.

The next lines. `? words` and `spark <words>` start a thread; `?? words`
continues the newest -- a rule, no heuristics -- and `spark talk <words>`
is one more turn on it, `spark talk` alone a conversation (`spark> `,
`/new`, `/quit`, Ctrl-D). Threads live under
`~/.local/state/spark/threads/` (0700/0600), pruned by `SPARK_HISTORY`
like the turns; a continued thread sends at most 20 kB of its past.
`spark @FILE words` sends a text file's first 4 kB and last 12 kB through
the same slot as piped input. `spark do <words>` runs a task one command
at a time: Enter runs, `e` edits, `s` skips, `q` quits, a step that can
destroy data runs only on the word `yes`; at most 8 steps, each step's
output (last 4 kB) goes back to the model, every step is recorded. The
turn log carries the thread id; `spark last`, `spark status` and `spark
history` show it.

Headless. `SITE_HEADLESS=yes` (`spark headless on|off`) makes a box the
brain: the FORGE up from boot with nobody logged in, never asleep. Linux:
linger, the sleep/suspend/hibernate targets masked, the lid ignored by a
logind drop-in. macOS: `spark.serve`, `spark.forge` and `spark.check`
become LaunchDaemons in the `system/` domain running as you (no
auto-login; FileVault's login screen untouched), `pmset` never sleeps and
wakes on LAN; `off` puts the login agents back and sets no power values of
its own. Bootstrap rows `linger`, `sleep`, `lid` (Linux) and `daemons`,
`sleep` (macOS); check row `headless` (NONFUNCTIONAL); `services` shows
`(daemon)`; restart and stop print the `sudo launchctl` line a daemon
needs. 30 check rows now.

## v0.2

Throughput you can see. Every turn records the server's timings (tokens
each way, tokens/s, cache hits); `spark last`, `spark status` and the
status line show them; `spark stats` sums them up with latency
percentiles, cache hit ratio, the running server's settings and the GPU
(Linux sysfs). `spark bench` measures with llama-bench and keeps a
baseline; `spark bench --tune` searches GPU/CPU layers, flash attention,
KV cache type and threads, `spark tune apply` writes the winner to
spark.env (`SPARK_FLASH_ATTN`, `SPARK_KV`, `SPARK_THREADS` join
`SPARK_NGL`) and restarts. New check rows: `throughput` (real turns vs
the baseline) and `gpu` (a model bigger than VRAM is named, with the BIOS
remedy). `spark model` lists the table and switches models; the served
model follows SITE_AI_MODEL, not the newest file.

## v0.1

First release. One command, `spark`: the AI at the prompt (`? words`,
`words?`, `Esc a`, `explain`), `spark serve`/`stop` with a systemd unit
and a launchd agent, `spark check` with a fixture selftest, `spark bar`,
`spark theme`. One `bootstrap.sh` and one `install.sh` for Debian-family
Linux and macOS; four palettes; five pinned models chosen by RAM; a
privacy gate on every commit. Python 3.9+ stdlib and POSIX sh only.

After the first real Debian 13 box: `libgomp1` for the engine; an ASCII
mode for the Linux console (also behind tmux); `spark theme NAME` and
`spark theme list`; `spark ver` as the login greeting; the check header
carries the version; the mark is the plain word `spark`. `spark font` and
`spark bootconfig` set the console font and a quiet login/boot (Linux;
the macOS font lives in the Terminal profile); bootstrap enables linger.
`spark bar` toggles the status line; tmux draws it with `spark bar line`.
