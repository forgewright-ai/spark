# Installing spark

spark is AI on the edge, at no cost: `spark chat` is the front door, the
prompt line is the surprise. This is the runbook: what the first run does,
every key, the models, the shell layer, the FORGE from other machines,
headless, updating, and what to do when something stops working. The
README is the short form.

## Before you start

- Linux: a Debian-family system with `apt` (Debian 13 or Ubuntu 24.04 or
  newer -- older ones lack `eza` for the shell layer), `git`, `python3`
  >= 3.9, `curl`, and sudo once for `apt`. x86_64 or arm64.
- macOS: the command line tools (`xcode-select --install`); Apple's own
  `python3` (3.9) is enough. No Homebrew for the AI -- the engine is a
  pinned tarball here too; Homebrew only for `spark shell on`.
- Either: a terminal, and bash 4+ or zsh as your login shell (the prompt
  widget lives in one of them; macOS ships zsh, its bash is 3.2).

## The first run

The one-liner clones spark to `~/.spark` and runs `spark setup`:

```sh
curl -fsSL https://raw.githubusercontent.com/forgewright-ai/spark/main/get | sh
```

`get` checks the ground first -- the command line tools on macOS (before
`git` can pop the dialog), `apt-get` on Linux, `git`, `python3` >= 3.9 --
and refuses with the install line when one is missing. It never runs sudo,
and its whole body is one function called on its last line, so a download
cut short runs nothing. `SPARK_HOME` moves the clone, `SPARK_URL` points it
elsewhere, `SPARK_REF` checks out a ref right after a fresh clone
(developers: `SPARK_REF=main`; with none, it lands on the newest release
tag, or stays on the default branch when there is none). A `~/.spark` that
is spark already: fetches tags, then pulls `--ff-only` on a branch or
moves to the newest tag when detached; any other non-empty directory is
refused. `sh get --clone-only` stops after the clone. By hand, the same
two steps:

```sh
git clone https://github.com/forgewright-ai/spark.git ~/.spark
~/.spark/bin/spark setup
```

`spark setup` asks four things and never more: this machine's name (the
short hostname by default), yours (your login), the model, from the
table with the row this machine earns marked `*` -- the largest that fits
in the SITE_AI_BUDGET percent (default 60) of RAM plus GPU memory and
stays usable on this engine build (the speed cap under Models) -- and the
theme (`theme [gruvbox-dark]:`, any name from `themes/` or `none`; the
default is only the default answer, `site.env.example` stays
`SITE_THEME=none`). It never asks about the hostname, the shell
layer or headless: those have verbs of their own. Then, in order:

1. writes `~/.config/spark/site.env` (created from `site.env.example`,
   0600, with `SITE_SHELL=off`: the AI only, your shell stays yours);
2. on Linux, `sudo -v` once when `apt` has something to install
   (`libgomp1`; with a GPU, the Mesa Vulkan packages too: one sudo, both
   at once); nothing on macOS;
3. runs `bootstrap.sh` on the terminal: the engine (one pinned llama.cpp
   tarball for this OS and architecture, sha256-verified), the model with
   curl's progress bar, the api-token, the widgets, the one rc line, the
   units (`spark-serve` / `spark.serve` and the FORGE's, plus a 5-minute
   check timer);
4. writes the chosen palette's runtime files (`theme.env`,
   `console-colors`) unless the answer was `none` -- the theme is core,
   shell layer or not; on macOS the Terminal.app profile is imported too;
5. brings the server up (the unit, or `spark serve`) and waits for it;
6. asks `? how big is this dir` for you, shows the answer as the widget
   shows it, and prints the tok/s that question measured;
7. prints the three things to try. `spark shell on` is mentioned, never
   offered.

Flags: `--yes` takes every default without asking (implied when stdin is
not a terminal); `--model NAME|auto|none`, `--name`, `--user`, `--theme`
and `--no-serve` pre-answer; `SITE_NAME`, `SITE_USER`, `SITE_AI_MODEL`,
`SITE_THEME` in the environment do the same, and a key `site.env` already
holds is not asked again. It is re-runnable: every bootstrap row is
idempotent.

The rc line: bootstrap's `rc` row appends exactly one line to the end of
your login shell's rc file -- `~/.bashrc` for bash, `~/.zshrc` for zsh --
and only when the file does not already contain `config/spark/hook.`:

```sh
[ -r ~/.config/spark/hook.bash ] && . ~/.config/spark/hook.bash   # spark: the AI at the prompt
[[ -r ~/.config/spark/hook.zsh ]] && source ~/.config/spark/hook.zsh   # spark: the AI at the prompt
```

The hook puts `~/.local/bin` first on PATH, sources the widget and keeps
a blank row above a plain prompt (the hint lives there). It goes last,
after fzf, because the widget wraps Enter. If the row says `todo rc`, the
login shell cannot host the widget (another shell, or macOS's bash 3.2):
`chsh -s /bin/zsh`, then `spark setup` again -- or paste the line into
the rc file of a bash 4+ or zsh you do use. Open a new shell (`exec
$SHELL`) and the prompt is live.

The hook also sources TAB completion
(`~/.config/spark/completion.bash` / `.zsh`, linked by `install.sh`):
the first word completes the verbs, the second each verb's words --
theme and model names included, resolved offline from the repository
the `spark` symlink points into. It binds no key of its own. One zsh
note: registration needs `compinit`; with the shell layer off nothing
runs it for you, so a bare zsh without your own
`autoload -Uz compinit && compinit` in `~/.zshrc` gets no completion --
silently, by design.

## The keys

Everything else in `site.env` is optional and has a verb of its own;
editing the file by hand and running `./bootstrap.sh` does the same thing.
The two you may want are `SITE_GIT_NAME` and `SITE_GIT_EMAIL` (the shell
layer's git identity).

| key | values | default |
|---|---|---|
| `SITE_NAME` | this machine's display name | short hostname |
| `SITE_USER` | your display name | your login |
| `SITE_AI_MODEL` | `auto`, `none`, or a name from `spark model` -- later, `spark model NAME`; `none` beside a peer URL is a client (`spark client URL`) | `auto` |
| `SITE_EMBER_MODEL` | `none`, `auto`, or a name: a second model for conversations; `none` = one model does both -- later, `spark ember NAME` | `none` |
| `SITE_AI_BUDGET` | 10..95: percent of RAM+GPU memory `auto` may use -- later, `spark model budget N` | `60` |
| `SITE_AI_BUILD` | `auto`, `cpu` or `vulkan`: the Linux engine build; `auto` = `vulkan` when a GPU reports its memory in `/sys/class/drm`, else `cpu` (macOS ignores it, its tarball has Metal) | `auto` |
| `SITE_SHELL` | `off`: the AI only; `on`: tmux, starship, micro (with the spark plugin: Alt-s), fzf, zoxide, eza, bat, btop, the Nerd Font, and the rc files become spark's -- later, `spark shell on|off` | `off` |
| `SITE_PEER_AI_URL` | another machine's FORGE URL (`spark forge --print-client` there), or its raw `spark serve` URL | unset |
| `SITE_HEADLESS` | `yes`: the FORGE up from boot with nobody logged in, never asleep -- later, `spark headless on|off` | `no` |
| `SITE_THEME` | `none`, or a palette from `themes/` (`spark theme` lists them) -- later, `spark theme NAME` | `none` |
| `SITE_PROMPT` / `SITE_PROMPT_STYLE` | `starship`/`plain`; `minimal`/`full` (the shell layer) | `starship`, `minimal` |
| `SITE_FONT_FACE` / `SITE_FONT_SIZE` | Linux console: a face and size `spark font list` shows (e.g. `Terminus` `16x32`); macOS profile: a font's PostScript name and points -- later, `spark font FACE SIZE`; core, shell layer or not | unset / `13` |
| `SITE_QUIET_LOGIN` / `SITE_QUIET_BOOT` | Linux: `yes` bares the login (motd, kernel line and `/etc/issue` emptied, originals kept as `*.orig`) / makes the boot silent -- BIOS splash to login prompt (GRUB menu hidden, quiet kernel line, systemd silent; one drop-in at `/etc/default/grub.d/zz-spark-quiet.cfg`) -- later, `spark quiet login|boot on` | `no` |
| `SITE_QUIET_START` | both OSes: `yes` silences spark's own start -- no login banner, one-line `spark serve` and `spark forge`, one-line bare `spark` (`spark status` stays full) -- later, `spark quiet start on`. The login path greps `site.env` directly (no python there), so the usual environment-over-file precedence does not apply to the banner | `no` |
| `SITE_SET_HOSTNAME` | `yes`: the OS hostname follows `SITE_NAME` (sudo; the shell layer) | `no` |

Runtime knobs live in `~/.config/spark/spark.env` (`spark.env.example`
lists them all); the ones with a verb of their own:

| key | values | default |
|---|---|---|
| `SPARK_MEMORY` | `on`/`off`: recall the remembered facts on every answer -- later, `spark memory on|off` | `on` |
| `SPARK_FORGE` | `auto`/`on`/`off`: serve the FORGE; `auto` = wherever the model server is enabled -- later, `spark forge on|off` | `auto` |
| `SPARK_FORGE_HOST` / `SPARK_FORGE_PORT` | the address and port the FORGE binds (never `0.0.0.0`) | the LAN address / `8081` |
| `SPARK_FORGE_TOKEN_FILE` | its admin token file (0600); never the api-token | `~/.local/state/spark/forge-token` |
| `SPARK_HISTORY` | days of turns and threads kept under `~/.local/state/spark/`; `off` keeps none, so `??` behaves like `?` | `30` |
| `SPARK_NGL` `SPARK_FLASH_ATTN` `SPARK_KV` `SPARK_THREADS` | the engine's tuning; `spark tune apply` writes them | auto |
| `SPARK_API_KEY_FILE` | a token file you already have | `~/.local/state/spark/api-token` |

`SPARK_PERSONA_EXTRA`, the old one-line persona, is still read as the
soul's fallback in this version; `spark soul edit` absorbs it and the
`soul` row warns while it is set.

## Models

### Three lists, and yours

Every model lives in one of three files at the repo root, plus a fourth
that is never in the repo:

| list | file | rule | shown by |
|---|---|---|---|
| curated | `models.env` | open license, proven on the line -- the only one `auto` reads | `spark model list`, unmarked |
| embers | `embers.env` | open license, plus a one-line purpose | `spark ember list`, marked `e` |
| community | `community.env` | any license, named; untested, at your own risk | `spark model list`, marked `?` |
| yours | `~/.config/spark/models.env` | your own rows, written by hand, 0600, never in the repo | either table, marked `u` |

`spark model list` shows the curated, community and your own rows (no
purpose to show), then a line pointing at `spark ember list` when there
is one. `spark ember list` shows all four, with each ember row's purpose
printed on the line below it, indented. A name in two lists is refused,
naming both files. Picking a community or your-own row by name (`spark
model NAME` / `spark ember NAME`) prints its license line and, at a
terminal, asks `download it? [y/N]` first (`SPARK_YES=1` in the
environment, or stdin not a terminal, counts as yes without asking);
`spark setup` never offers one, though naming one with `--model` is still
allowed. A row in any list is a pull request.

`spark model` lists the curated table: each model's file size, the RAM it
needs against this machine's SITE_AI_BUDGET percent (default 60) of RAM
plus GPU memory, whether it is downloaded, which one serves, and its
speed here -- `~N tok/s` is an estimate for this backend (metal, vulkan
or cpu) until `spark bench` or a real turn measures the model, when the
`~` goes.

| name | file | RAM |
|---|---|---|
| `qwen3-1-7b` | 1.0 GB | 3 GB |
| `qwen3-4b` | 2.3 GB | 5 GB |
| `qwen3-8b` | 4.7 GB | 7 GB |
| `qwen3-14b` | 8.4 GB | 11 GB |
| `qwen3-30b-a3b` | 17.4 GB | 21 GB |

How `auto` picks: every curated row whose RAM fits the SITE_AI_BUDGET
percent (default 60) of RAM plus GPU memory, then the largest of those
whose file is under this build's speed cap -- 3 GB on `cpu`, 6 GB on
`vulkan`, 20 GB on `metal`: the size classes the
estimate keeps at about 8 tok/s or better (a `-a3b` MoE counts as its 3B
active class, as in the speed column). A row can fit the budget but run
too slowly on a weaker backend, so `auto` stops earlier there than on a
faster one; when the cap held a bigger row back the table's header says
so (`auto stops at 6 GB files on vulkan ...`), and `spark model NAME`
takes that row anyway, from any of the four lists: a name is never
second-guessed. Nothing under the cap fits: the smallest row that fits,
never nothing while something fits. `bootstrap.sh --list-models` and
`spark model` make the same choice (they are twins, and the tests pin
both); `bootstrap.sh --list-models` shows all four lists too, curated
first, with the same marks.

`spark model qwen3-8b` chooses it (`SITE_AI_MODEL`), downloads and
verifies it if needed (size and sha256 from the list it is in, from
huggingface.co), and restarts the server; `spark model auto` goes back to
the rule above (curated only); `spark model rm NAME` deletes a file that
is not in use. A `.gguf` you drop into `~/.local/share/spark/models`
yourself is served with `SPARK_MODEL=<file>` in `spark.env`. `spark model
budget` prints the percent, the GB it buys and the table; `spark model
budget N` (10-95) sets `SITE_AI_BUDGET`, re-applies the pick and prints
the table again.

One model answers everything by default. A second brain is a larger model
devoted to conversation while spark stays small and fast at the prompt
line, chosen by name from any list.

One model by default. `spark ember NAME` is the opt-in second model: the
prompt line stays with the small spark model (context 4096, reasoning off,
so a thinking model answers plainly and fast) and every conversation --
`spark <words>`, `chat`, `do`, the page, any `/v1` client that names no
model -- goes to the ember, the identity riding only with it. `spark serve`
then runs llama-server as a router: one process, one port, one api-token;
the request's `model` field picks the child. `spark ember auto` makes spark
the smallest row and the ember the largest that fits beside it in the
budget, under the same speed cap; `spark ember none` (the default) runs
one model in both roles.

Speed: `spark bench` measures with llama-bench (pp512 / tg128; the ember
when one serves, `--spark` / `--ember` force a role) and keeps the result
as the file's baseline; `spark check`'s `throughput` row warns when real
turns fall below 70 % of it. `spark bench --tune` tries GPU vs CPU layers,
flash attention, KV cache types and thread counts; `spark tune apply`
writes the winner to `spark.env` and restarts. `spark stats [--week]` sums
up what real turns measured. The server is paused while llama-bench runs.

### Adding your own model

`spark model add URL` writes a fifth, yours-only row and picks it. A
huggingface.co `.../resolve/<rev>/<file>` URL is auto-verified from its
LFS headers (size and sha256); any other URL needs `--sha256 HEX`. The
name is the file stem, lowercased, dots and underscores turned to dashes,
a trailing quantization token (`-q4-k-m`, `-f16`, ...) stripped; a name
already in any of the four lists is refused, naming the file it is in.
`--license "NAME URL"` is required -- your own row states its license
like every non-curated row. The row lands in `~/.config/spark/models.env`
(0600, created if absent), then `spark model add` downloads it and
restarts the server, same as `spark model NAME`.

### Verifying

Every download is sha256-verified once, by `fetch` in `bootstrap.sh`.
`spark model verify` re-hashes every downloaded file right now (1 MiB
chunks), prints `ok` or `bad -- spark model rm NAME; spark model NAME`
per file, and exits 1 on a mismatch; nothing is ever deleted for you.
`spark check`'s `models` row is the cached, daily version of the same
check: a file's hash is re-verified when its size or modification time
changes, or once a day, whichever comes first.

## The shell layer

`spark shell on` (`SITE_SHELL=on`) puts spark's own shell on top of the AI:
tmux, starship, micro, fzf, zoxide, eza, bat, btop, the Nerd Font, and on
Linux the quiet login and boot when their keys say so (the console font is
core: `spark font` sets it with the layer off too). With a theme chosen,
one palette lands on every surface in the same
move: tmux and starship are rendered from it, micro gets a `spark`
colorscheme (plus a seeded `settings.json` choosing it, and
`MICRO_TRUECOLOR=1` from the hook), and the text console wears it through
`console-colors` -- TTY, tmux and micro, the same look. micro also gets
spark itself: the plugin under `~/.config/micro/plug/spark/` (linked,
like the bindings) puts `spark> ` on `Alt-s` -- Enter alone completes at
the cursor, words rewrite the selection, `? words` asks in a pane on the
right, `?` alone reviews; nothing selected means the whole file; `> help
spark` inside micro says the rest. The
plugin is one client of `spark edit` (the text on stdin, raw text out;
`spark edit -h`), which works from a pipe too. spark reads what the text
is and answers as that kind deserves; when it should not guess, `setlocal
spark.about "a novel chapter"` says so for a buffer, or a path glob in
`settings.json` for a folder. `set spark false` switches the plugin off;
the `editor` check row reports all of it. The rc files
become spark's -- `~/.bashrc` and `~/.bash_profile` on Linux, `~/.zshrc`
and `~/.zprofile` on macOS turn into symlinks into the repo, yours moved
to `<file>.bak`, never overwritten. It runs bootstrap (sudo once for
`apt` on Linux; Homebrew on macOS), then says `open a new shell`.
`spark shell off` hands everything back the same way, look included:
each rc file and each rendered config -- `.tmux.conf`,
`.config/starship.toml`, btop's conf, micro's colorscheme and
`settings.json` -- is restored from its `.bak`, or removed when there was
none (that was the pre-spark state; never an empty husk). `~/.gitconfig`
(your identity, not the look) and the core palette files under
`~/.config/spark/` stay; the `configs` and `rc` rows re-run so the one
hook line lands in a restored rc file; the packages stay installed
(`apt` or `brew` removes them). `spark shell` prints the state.

With the layer off, `spark bar` and the set forms of
`spark quiet login|boot` refuse (`the shell layer is off`), `spark help`
folds the shell block into one line, and the check rows that stand on it
(`pinned terminfo quiet bar git backup swap editor encryption pending
battery disk`) read `na`; the `shell` row says what `on` adds. `spark
theme` and `spark font` work either way -- the palette and the console
font are the machine's face, shell layer or not (the Nerd Font download
alone stays with the layer; `spark font list` shows the console faces
this box has) -- and `spark quiet start` works either way: it is spark's
own noise, not the shell's.

Most linked files are symlinks into the repo, so an edit anywhere is a
`git status` line. Some apps rewrite their own config on exit; those are
rendered once as regular files and left to the app:

| file | why it is not a symlink |
|---|---|
| `~/.config/btop/btop.conf` | btop rewrites it on every exit |
| `~/.config/micro/bindings.json` | micro rewrites it (through the link) when a plugin adds keys -- spark's own plugin never binds from inside for that reason; `Alt-s` is a tracked line here |
| `~/.config/micro/plug/spark/` | linked file by file; micro loads it from there, `set spark false` switches it off |
| `~/.config/micro/settings.json` | micro rewrites it on every option change; seeded once (`"colorscheme": "spark"`), then it is micro's -- never re-rendered, never backed up |
| `~/.gitconfig`, `~/.tmux.conf`, `~/.config/starship.toml`, `~/.config/micro/colorschemes/spark.micro` | carry your name / palette / choices |
| `~/.config/spark/launchd/*.plist` | launchd needs absolute paths |

`install.sh` never overwrites a regular file: it moves it to `<file>.bak`.

## The identity

`~/.config/spark/soul` is the paragraph that tells the model who it is.
spark ships with a default soul; `spark soul edit` replaces it with your
own, in `$EDITOR` (`spark soul` shows which is in use, `spark soul reset`
goes back to the default; at most 4000 characters, 0600). The default:

```
You are spark, the AI on this machine. You run here, on hardware the user
owns; nothing you are told leaves it. You are here to answer, to explain,
to write, and to hand the user a command when one is what they need.
Speak plainly, in the user's language. Say when you do not know. Never
invent a flag, a path, or a command.
```

`~/.config/spark/memory` is one fact per line: `spark remember <words>`
adds one, `spark forget N` (or `spark forget <words>`) drops one, `spark
memory` lists them, `spark memory off` stops sending them; 40 facts of
200 characters, 2000 in all. Both go into the system message on every
conversational request, so a fact costs tokens every time -- keep the
ones that change answers. The model never
writes them: a small model's judgement about what is worth keeping is
poor, and a silent write to a file you own breaks "the user chooses". They
are config, not state: `spark history clear` empties the turns and threads
and never touches a fact.

`? words` and `spark <words>` start a thread; `?? words` continues the
newest one -- a rule, not a guess -- and `spark chat <words>` is one more
turn on it. `spark chat --thread N [words]` continues an older thread
instead: N counts down the `spark history` (or `/resume`) list, 1 the
newest, and a literal thread id works too. `spark chat` alone is a
conversation at a `chat> ` prompt: `/help` lists its verbs (`/new` a
fresh thread, `/resume` an older one -- bare lists the newest five,
`/resume N` switches to one -- `/clear` wipes the screen while the
thread goes on, `/last` the last turn with its tok/s, `/model` which one
is answering); `/q` (or `quit`, `exit`, Ctrl-D) ends it, silently, and
Ctrl-C cancels a reply in progress without ending the chat. At a terminal it keeps a readline history,
sealed in your account's store (`users/<name>/chat-history`; off with
every other conversation trace when `SPARK_HISTORY=off`); two
`spark chat` sessions open at once share that history and the newest
thread the same way two shells share one file -- last writer wins. `spark @FILE words`
sends a text file's first 4 kB and last 12 kB along with the question (a
directory or a binary is refused). Quote words the shell would glob (a
trailing `?`, parentheses) -- zsh eats them first. `spark do <words>`
proposes one command at a time: Enter runs it, `e` edits it first, `s`
skips, `q` quits, and a step that can destroy data runs only when you type
`yes`; each step's output (last 4 kB) goes back to the model until it says
done, or after 8 steps. A done summary whose numbers no command produced
is marked unchecked -- claims need provenance the way actions need
confirmation.

## The FORGE from other machines and programs

The FORGE is the agent this machine serves: the model plus its soul,
memory and threads behind one HTTP API on `http://<host>:8081`, started
beside the model server (`SPARK_FORGE=auto`). The api-token is the
model server's and never leaves the machine; the forge-token is the
admin's and stays here too. Everyone else is a named user: `spark user
add NAME` mints an account whose token is shown once and never stored
-- it is the only key to that user's sealed threads and memory, and
there is no reset. `spark forge --print-client` says the flow: mint the
user here, `spark client URL` and `spark user login NAME` on the other
machine. A peer only talks to the ember; a machine with a model of its
own prefers the peer while it answers and falls back to its own server
silently; `spark brain` says which answers. The raw-model path still
exists: `spark serve --print-client` prints the `:8080` URL and the
api-token's `scp`.

`spark client URL` on the other machine is the short form: it writes the
peer URL and `SITE_AI_MODEL=none`, applies the prompt hook and the
widgets, and names the login step. A client runs nothing --
no engine, no model, no units -- and `spark check` there says so: the
engine, services, watchdog, ai, serve and forge rows read `na`, the
peer row says whether the FORGE answers. `spark client` shows that state; `spark client
off` is `spark model auto`: a model of its own again, the peer still
first while it answers.

Any program talks to the same FORGE with the OpenAI shape; a request that
names no `model` gets the ember with the identity injected (`model: spark`
reaches the bare line model, no identity):

```sh
curl -sN http://<host>:8081/v1/chat/completions \
  -H "Authorization: Bearer $YOUR_SPARK_USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"what is this machine for?"}],"stream":true}'
```

The page: a plain client page in the browser. `spark forge --print-url`
prints `http://<host>:8081/login` and, on a terminal, the admin token;
type a token once and the browser keeps a cookie (90 days; a server
restart asks again -- a user's key lives in memory only). Any
machine's browser works -- a phone is just one client among many. The
forge-token logs in as admin -- the whole machine: every verb, `do`, the
config, serve, bench, the log, and the box account's own threads; a
personal token logs in as that user: their own sealed chat, threads and
memory, the palette, a read-only monitor. Give each of the household
their own `spark user add NAME`; the admin token stays here, and nobody
-- the admin included -- holds a key to another user's messages.
`spark forge token --new` rotates the admin; `spark user token --new`
(or the page's account card) rotates a user; exactly that principal's
clients and browsers log in again. `spark forge` alone is the status
(URL, health, model, unit, tokens, users, log tail); `spark forge
on|off` writes `SPARK_FORGE` and enables or disables the unit.

Each user's threads, memory and chat history are sealed --
ChaCha20-Poly1305, written from RFC 8439, under a per-user data key
wrapped by that user's token. The box stores a sha256 verifier and the
wrap, never the token: no token, no key, no plaintext, and there is no
reset -- a lost token is lost history. Coming from v1.3, `spark user
claim` seals the old plaintext threads, memory and chat history into
your store and removes them (`spark setup` and the first `spark user
add` offer it at a terminal); the `users` check row nags until every
plaintext file and the old shared ember-token are gone. There is no TLS on the LAN: the standard library
cannot mint a certificate without a new dependency, a self-signed one
trains people to click through warnings, and the trust model is your LAN.
The API is contract 9 in `CLAUDE.md`.

On a phone, open the page once and add it to the home screen (iOS:
share -> add to home screen; Android: menu -> add to home screen). On
iOS the page becomes an app: its own icon, full screen, no browser
chrome. Android grants that standalone install only to a secure
context -- the same rule that bars the service worker below -- so over
LAN http the shortcut keeps its icon but opens in an ordinary browser
tab. Either way the page still needs the FORGE reachable when it
opens: there is no service worker and no offline copy, and that
follows from the no-TLS decision above -- browsers grant service
workers only to a secure context (https, or localhost), and the page
lives on LAN http. Pretending otherwise with a cache that cannot exist
would be a lie; the page is small and loads from the FORGE in one
round trip.

## Headless

Install spark on the machine that stays on, then `spark headless on`
(`SITE_HEADLESS=yes`). Linux: linger (the units run from boot without a
login), the `render` group (the GPU without a logind seat), the sleep,
suspend and hibernate targets masked, the lid ignored through
`/etc/systemd/logind.conf.d/spark.conf`; bootstrap rows `linger`,
`render`, `sleep`, `lid`, each with sudo; `off` reverses all but linger
and the group. macOS: `spark.serve`, `spark.forge` and `spark.check` move
from `gui/$UID` to `/Library/LaunchDaemons` as LaunchDaemons running as
you (no auto-login; FileVault's login screen is untouched), and `pmset -a
sleep 0 disksleep 0 womp 1 autorestart 1` (only the keys this hardware
lists); rows `daemons`, `sleep`. Restart and stop then need root: `spark
stop` and `spark model` print the `sudo launchctl` line. `off` puts the
login agents back and leaves `pmset` as it is. Then `spark forge
--print-client`, and point every laptop's `site.env` and every phone's
browser at it: one FORGE, one identity, the same answers everywhere. The
`headless` row names any piece that is missing.

## Updating

```sh
spark update
```

Fetches tags, then either pulls `--ff-only` (a developer clone, on a
branch) or moves to the newest release tag (the common case: what `get`
lands on by default); either way it converges -- bootstrap.sh runs, `spark
check` re-reads -- and `--dry-run` says what it would do without changing
anything. By hand, the same two steps:

```sh
git -C ~/.spark pull --ff-only && ~/.spark/bootstrap.sh
```

`./bootstrap.sh --dry-run` must then end with `Nothing to do`, and `spark
check` exit 0.

## Per-OS notes

- macOS asks once, in a dialog, whether `python3` may find and connect
  to devices on the local network: that is the FORGE (`spark forge`)
  binding your LAN address so other machines and your phone can reach
  it. Allow it; deny it and the FORGE answers only this machine.

macOS:

- No Homebrew for the AI. The engine is the pinned llama.cpp tarball for
  arm64 or x64 (Metal inside; `SITE_AI_BUILD` is ignored), extracted into
  `~/.local/share/spark/engine/`. Bootstrap clears any quarantine flag on
  it, so Gatekeeper never objects; if it still does, `xattr -dr
  com.apple.quarantine ~/.local/share/spark/engine`.
- The shell layer is Homebrew's (`Brewfile`, no pinning worth trusting)
  plus a Terminal.app profile: `spark theme profile` writes and imports
  one with the palette and the font (`spark font FACE SIZE` sets them).
  the profile makes Option the Meta key, so `Alt-s` is Option-s (Cmd-s is
  Terminal's own Export sheet); `Esc` then `s`, quickly, is the same keys.
- Apple's `tmux-256color` terminfo predates modified arrow keys, so micro
  types junk on Shift+Right; bootstrap compiles a complete entry from
  Homebrew's ncurses into `~/.terminfo` (the `terminfo` row).
- Units: `launchctl print gui/$UID/spark.serve` (`.forge`, `.check`
  likewise); `launchctl kickstart -k gui/$UID/spark.serve` restarts one.
  There is no root-free GPU counter, so `stats` and the `gpu` row say so.

Linux:

- The engine is the pinned tarball for x86_64 or arm64, the Vulkan build
  when a GPU reports its memory in `/sys/class/drm` (`SITE_AI_BUILD=auto`,
  the default; `vulkan` and `cpu` choose outright, `cpu` works anywhere).
  The Vulkan build brings `libvulkan1 mesa-vulkan-drivers` through apt --
  the same sudo as `libgomp1`, no second prompt. The `gpu` row names the
  build this machine gets; when the extracted engine is the other build
  (a box that had `cpu` before a GPU was seen) the `engine` row says so
  and `./bootstrap.sh` replaces it. An architecture without a pin gets
  `skip engine no pin for llama.cpp ...` -- point `SPARK_ENGINE_DIR` at a
  build of your own; bootstrap and the `engine` row honour it over the
  tarball.
- Integrated GPUs: the BIOS decides how much RAM the iGPU owns as VRAM
  ("UMA frame buffer size"). If the `gpu` row says the model is larger
  than VRAM, the weights spill into GTT across the bus and generation
  slows; raise it in the BIOS (e.g. 8 GB for a 4B-8B model), then `spark
  bench` again: the two rows in `~/.local/state/spark/bench.jsonl` are
  your before and after.
- The `render` group grants the GPU without a logind seat (an ssh login
  has none): bootstrap adds you to it on a vulkan build and under `spark
  headless on`; log out of every session and in again for the units to
  see it.
- The theme reaches the text console: `spark theme NAME` (and `spark
  setup`'s theme answer) writes `~/.config/spark/console-colors`, the
  precomputed VT palette escapes, and the rc hook applies it only when
  `TERM=linux` -- an xterm-family terminal never sees the escapes. GUI
  terminal emulators stay yours: apply the colours in `theme.env` in their
  settings by hand. The `theme` check row watches that `theme.env` and
  `console-colors` still match the chosen palette.
- The console font is core, not the shell layer: `spark font Terminus
  16x32` gives the text console a readable font on a 1080p screen (`VGA`
  for the installer's look). `spark font list` reads
  `/usr/share/consolefonts` -- the real faces and sizes this box has --
  and a face or size not there is refused before anything is written (a
  WxH size such as `16x32` matches its HxW file name). The quiet rows stay
  with the shell layer: `spark quiet login on` empties the motd and
  `spark quiet boot on` makes the boot silent (the GRUB drop-in). The
  console font cannot draw the check and arrow glyphs; spark notices
  (`TERM=linux`, also inside a tmux whose client is the console) and
  prints ASCII. `SPARK_ASCII=1` forces that.
- Units: `systemctl --user status spark-serve spark-forge
  spark-check.timer`; `journalctl --user -u spark-serve -n 50`. Without a
  user systemd session (a container) the `services` row reads `na`; run
  `spark serve` and `spark forge` by hand.
- `fd` and `bat` are `fdfind` and `batcat` on Debian; the shell layer's rc
  file aliases them.

## What bootstrap does as root

`bootstrap.sh` uses sudo per layer, and `--dry-run` never calls it -- it
lists exactly which of these it would do:

- the AI (always): Linux `apt` for `libgomp1` (and the Vulkan libraries
  when the build is vulkan: a GPU in sysfs, or `SITE_AI_BUILD=vulkan`);
  macOS nothing.
- the shell (`SITE_SHELL=on`): Linux `apt` for tmux and the tools, the
  hostname (`SITE_SET_HOSTNAME=yes`), the console font, the quiet login
  (motd) and the quiet boot (the GRUB drop-in), each only when its key says so; macOS
  the hostname only.
- headless (`SITE_HEADLESS=yes`): Linux `loginctl enable-linger` and the
  `render` group (also on any vulkan build), the sleep targets masked, the
  lid ignored (a logind drop-in); macOS the LaunchDaemons in `system/` and
  `pmset`.

One thing stays manual on purpose, being a trust decision rather than
configuration: passwordless sudo for your user (`echo 'you ALL=(ALL)
NOPASSWD:ALL' | sudo tee /etc/sudoers.d/you`, fine for a test bench).

## When something stops working

1. `spark check` -- it names the row and the remedy. The report -- like
   every long output: the help, the model table -- pages through `$PAGER`
   (`less` when unset) at a terminal, and stays plain when piped.
2. `./bootstrap.sh --dry-run` -- what a rebuild would change.
3. `spark` -- which brain answers, which shells have the widget.
4. A stale server after a DHCP move shows as `moved` on the `serve` row
   and on the status line: `spark stop; spark serve` (or restart the
   unit). The `forge` row says the same for the FORGE: `spark forge stop;
   spark forge start`.
5. `spark forge` -- is the FORGE up, at which address, is its upstream ok;
   `~/.local/state/spark/forge.log` has one line per request, never a body.
6. The `ember` row: the pair over budget (`spark ember list` shows one
   that fits), the file not downloaded (`./bootstrap.sh`), or not warm
   (`spark serve` warms it).
7. A GPU that new servers cannot see (the `gpu` row warns, generation is
   slow): on Linux the serving user must be in the `render` group;
   `./bootstrap.sh` adds it on a vulkan build; log out of every session
   and in again so the user units pick it up.
8. `SPARK_DEBUG=1 spark ...` and `~/.local/state/spark/debug.log`.

## Appendix: how it fits together

```
your shell                    this machine                        the LAN
----------                    ------------                        -------
? words ---- widget -------> spark line ---+
micro Alt-s - plugin ------> spark edit ---+
spark chat | do | explain -> spark <verb> -+-> the FORGE :8081 ---> another
(readline, wrapped)                        |   identity: soul,         machine's
                                           |   memory, threads; /v1     spark, a
                                           |   and /api; the page       browser,
                                           +-> llama-server :8080 <---- program
                                               one model (spark), or
                                               two (spark + ember):
                                               the pinned engine and a
                                               GGUF from models.env,
                                               embers.env, community.env
                                               or your own models.env

get -> spark setup -> bootstrap.sh (apply) -> install.sh (links, renders)
                      the engine tarball, the model, the token, the units,
                      one rc line; SITE_SHELL=on adds the workstation

spark check   38 rows: every promise the machine makes, fixture-tested
spark update  the newest tag (a stranger), or main (a developer); converge

what leaves the machine: pinned downloads in, your questions to the brain
you chose, nothing else -- no telemetry, no account, one LAN address.
```
