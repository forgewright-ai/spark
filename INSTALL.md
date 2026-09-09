# Installing spark

Start at section 1 without a machine, at section 2 with one. The rest
is the runbook, in the order you will need it.

## 1. A machine from zero

About ten minutes, most of it one 4.7 GB download; sudo once.

Debian:

1. Get Debian 13 (trixie), the small installer image, from
   https://www.debian.org/CD/netinst/ (`amd64` for a PC, `arm64` for an
   ARM board). Write it to a USB stick and boot it.
2. In the installer, leave the root password empty: that puts your user
   in the `sudo` group. At *Software selection* keep SSH server and
   standard system utilities; a desktop is optional.
3. Log in and install what spark needs:

   ```sh
   sudo apt-get update && sudo apt-get install -y git curl python3
   ```

4. Continue at section 2.

Arch:

1. Get the ISO from https://archlinux.org/download/, write it to a USB
   stick and boot it.
2. Run `archinstall`. The answers that matter: the *Minimal* profile; a
   user account marked superuser (that is the `sudo`); *systemd-boot* as
   the bootloader (GRUB works too); `git curl python openssh` under
   additional packages; "copy the ISO's" network configuration to keep
   the Wi-Fi you joined with `iwctl`; one HTTPS mirror as a custom server
   (`https://geo.mirror.pkgbuild.com/$repo/os/$arch`), because a router
   that inspects HTTP turns a mirror into `invalid or corrupted database
   (PGP signature)`.
3. Reboot, log in, `sudo pacman -Syu` once, then section 2.

macOS: any Mac Apple still updates. `xcode-select --install` brings
`git`, `curl` and Apple's `python3` (3.9 is enough). Continue at
section 2.

Windows: spark runs in WSL 2, where Ubuntu is Linux to it. In
PowerShell, `wsl --install -d Ubuntu-24.04`, reboot when asked, open
Ubuntu, then Debian's step 3 and section 2.

## 2. Install spark

1. Check the four things spark needs: `sudo` once for the package
   manager, `git`, `curl`, `python3` 3.9 or newer.

   ```sh
   for c in sudo git curl python3; do
       command -v "$c" >/dev/null || echo "missing: $c"
   done
   python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' \
       || echo "python3 is older than 3.9"
   ```

   Silence means you are ready. Otherwise:

   - Debian 13 / Ubuntu 24.04 or newer: `sudo apt-get install -y git
     curl python3`. No `sudo` at all: `su -c 'apt-get install -y sudo &&
     usermod -aG sudo YOURNAME'`, then log out and in.
   - Arch Linux, or what says `ID_LIKE=arch`: `sudo pacman -S --needed
     git curl python`. Never `pacman -Sy` alone: `sudo pacman -Syu` first
     when a package cannot be found.
   - macOS: `xcode-select --install`.
   - Your login shell must be bash 4+ or zsh: the prompt widget lives in
     one of them (macOS ships zsh; its bash is 3.2).

2. One line:

   ```sh
   curl -fsSL https://raw.githubusercontent.com/forgewright-ai/spark/main/get | sh
   ```

   It clones spark to `~/.spark`, lands on the newest release and runs
   `spark setup`. To read it first:
   `curl -fsSLO https://raw.githubusercontent.com/forgewright-ai/spark/main/get; sh get`.
   With `wget`: `wget -qO- URL | sh`. By hand, the same two steps:

   ```sh
   git clone https://github.com/forgewright-ai/spark.git ~/.spark
   ~/.spark/bin/spark setup
   ```

3. When it finishes:

   ```sh
   exec $SHELL      # the prompt widget goes live
   spark check      # every row green
   ```

What setup does. It asks three things and never more: this machine's
name (the short hostname by default), yours (your login), and the model
(the row this machine earns is marked `*`; section 4 says how). Then:

1. writes `~/.config/spark/site.env` (0600);
2. on Linux, `sudo -v` once when a package is missing (`libgomp1` on
   Debian, plus the Mesa Vulkan packages with a GPU; Arch has the library
   in `base`, so a bare Arch asks only with a GPU); nothing on macOS;
3. runs `bootstrap.sh`: the engine (one pinned llama.cpp tarball for this
   OS, sha256-verified), the model with curl's progress bar, the token,
   the prompt widget, one rc line, the units (the server, the page, a
   5-minute check timer);
4. brings the server up and waits for it;
5. asks `? how big is this dir` for you and prints the tok/s it measured;
6. prints the three things to try.

It paints nothing: the machine looks as it did. It is re-runnable.
Flags: `--yes` takes every default (implied when stdin is not a
terminal); `--model NAME|auto|none`, `--name`, `--user`, `--theme`,
`--no-serve` pre-answer, as do `SITE_NAME`, `SITE_USER`, `SITE_AI_MODEL`
and `SITE_THEME` in the environment. `get` itself checks the ground
first (the command line tools on macOS, `apt-get` or `pacman`, `git`,
`python3` >= 3.9) and refuses with the install line when one is
missing; it never runs sudo. `SPARK_HOME` moves the clone, `SPARK_URL`
points it elsewhere, `SPARK_REF=main` follows development; `sh get
--clone-only` stops after the clone.

The rc line. bootstrap appends exactly one line to your login shell's rc
file (`~/.bashrc` for bash, `~/.zshrc` for zsh), only when it is not
there yet:

```sh
[ -r ~/.config/spark/hook.bash ] && . ~/.config/spark/hook.bash   # spark: the AI at the prompt
[[ -r ~/.config/spark/hook.zsh ]] && source ~/.config/spark/hook.zsh   # spark: the AI at the prompt
```

The hook puts `~/.local/bin` first on PATH, sources the widget, keeps a
blank row above the prompt for the hint, and sources TAB completion (the
verbs, then each verb's words, offline). It goes last, after fzf,
because the widget wraps Enter. If the `rc` row says `todo`, the login
shell cannot host the widget (another shell, or macOS's bash 3.2):
`chsh -s /bin/zsh`, then `spark setup` again. A bare zsh needs your own
`autoload -Uz compinit && compinit` in `~/.zshrc` for completion.

## 3. Use it

1. At the prompt: `? words` or `words?`, Enter, and the command lands in
   your line with a hint above it; Enter again runs it. A command that
   deletes comes back marked `!`. `?? words` follows up on the last
   answer; `Esc s` asks about the line you are on; `cmd 2>&1 | explain`
   says what went wrong. `spark off` gives Enter back and quiets the
   failure line; `spark on` restores both. TAB completes the verbs and
   their names, offline.
2. When a command fails, one line appears above the next prompt:
   `* failed (1) -- press Esc s to ask why`. `Esc s` on the empty line
   puts the command back, already piped to `explain`, and nothing runs
   until you press Enter. A command that deletes or destroys (`rm`,
   `dd`, `mkfs`...) is never offered a re-run -- the line says so, and
   `? words` still answers about it. After the fix works, `Esc s` offers
   to keep what happened as a `spark memory add` fact -- edit the line,
   then Enter. Only a command typed on one line is offered; Ctrl-C and
   a no-match from `grep` or `diff` stay quiet. The offer lives in the
   one pane it happened in and is gone with it.
3. `spark chat` is a conversation at a `chat> ` prompt. `/help` lists
   its verbs: `/new` a fresh thread, `/resume [N]` an older one, `/clear`
   the screen, `/last` the last turn with its tok/s, `/model` which one
   answers, `/q` (or Ctrl-D) ends. Ctrl-C cancels a reply and keeps the
   chat. `spark chat --thread N [words]` continues an older thread from
   the `spark history` list (1 = newest).
4. `spark <words>` streams one answer; `spark @FILE words` sends a text
   file's first 4 kB and last 12 kB with the question. Quote words the
   shell would glob (a trailing `?`, parentheses).
5. `spark do <words>` proposes one command at a time: Enter runs it, `e`
   edits it first, `s` skips, `q` quits; a step that can destroy data
   runs only when you type `yes`. Each step's output (last 4 kB) goes
   back to the model until it says done, or after 8 steps.
6. `spark ask` reads a plan, a draft or a decision on stdin and answers
   with questions about it -- at most three, one per line, and nothing
   else. Every line of the output is a question: a line that is not one,
   a question quoting words the text does not contain, and a question
   that could be asked of any plan are dropped before you see them, so
   the reply cannot state a fact the text does not hold. When nothing
   survives, you get one line saying so and nothing more -- a reader
   with nothing to ask says nothing.

   ```sh
   spark ask < plan.md
   spark ask what am I deciding here < plan.md
   ```

   Answer one of them and it stops coming back:
   `spark ask --answered --name plan.md` with the question on stdin;
   `spark ask --ledger --name plan.md` lists what you have answered,
   `--ledger clear` drops it. `spark ask -h` says the rest.
7. `spark soul edit` writes the paragraph that tells the model who it is
   (`~/.config/spark/soul`, at most 4000 characters; `spark soul` shows
   which is in use, `spark soul reset` goes back to the default). The
   default:

   ```
   You are spark, the AI on this machine. You run here, on hardware the user
   owns; nothing you are told leaves it. You are here to answer, to explain,
   to write, and to hand the user a command when one is what they need.
   Speak plainly, in the user's language. Say when you do not know. Never
   invent a flag, a path, or a command.
   ```

8. `spark memory add <words>` adds a fact it keeps (`spark memory forget N` drops
   one, `spark memory` lists them, `spark memory off` stops sending
   them; 40 facts of 200 characters). Soul and facts ride on every
   conversation, so a fact costs tokens every time: keep the ones that
   change answers. The model never writes them. `spark history clear`
   empties the turns and threads and never touches a fact.

## 4. Models

Two files:

| file | what |
|---|---|
| `models.env` | every model spark can serve: 26 models, each with its license; `line` marks a row proven on the prompt line |
| `~/.config/spark/models.env` | your own rows (`spark model add URL --license`), 0600; marked `u` |

`spark model list` shows every row: file size, the RAM it needs against
this machine's budget (`SITE_AI_BUDGET`, default 60 percent of RAM plus
GPU memory), the license, `line` when tested, downloaded or serving,
and its speed here (`~N tok/s` is an estimate until `spark bench` or a
real turn measures it; `too big` when it does not fit). The tested rows:

| name | file | RAM |
|---|---|---|
| `qwen3-1-7b` | 1.0 GB | 3 GB |
| `qwen3-4b` | 2.3 GB | 5 GB |
| `qwen3-8b` | 4.7 GB | 7 GB |
| `qwen3-14b` | 8.4 GB | 11 GB |
| `qwen3-30b-a3b` | 17.4 GB | 21 GB |

The untested rows (Qwen3 4B-Thinking and Coder-30B-A3B, Qwen2.5 7B /
14B / Coder-7B, Mistral 7B and Nemo 12B, Phi-4 mini and 14B,
DeepSeek-R1 distills 7B / 14B, SmolLM2 1.7B, gpt-oss-20b, Granite 3.3
8B, all Apache-2.0 or MIT; Llama 3.2 1B / 3B, Llama 3.1 8B and Gemma 3
1B / 4B / 12B / 27B under their own terms) are yours by name. A row
under a license that is not Apache-2.0 or MIT prints its license and
asks `download it? yes/NO:` first. The page lists them all:
https://spark.forgewright.ai/models/

How `auto` picks: every tested open-license row whose RAM fits the
budget, then the largest of those whose file is under this build's
speed cap (3 GB on `cpu`, 6 GB on `vulkan`, 20 GB on `metal`: the sizes
that keep about 8 tok/s). When the cap held a bigger row back the
table's header says so, and `spark model NAME` takes that row anyway.
Nothing under the cap fits: the smallest row that fits.

1. `spark model NAME` chooses a model: downloads and verifies it (size
   and sha256 from its row) and restarts the server. `spark model auto`
   goes back to the rule above; `spark model rm NAME` deletes a file not
   in use.
2. `spark model budget N` (10-95) sets the percent and prints the table.
3. A `.gguf` of your own in `~/.local/share/spark/models` is served with
   `SPARK_MODEL=<file>` in `spark.env`.
4. `spark ember NAME` adds a second, bigger model for conversations: the
   prompt line stays with the small one (context 4096, reasoning off, so
   a thinking model answers fast) and every conversation (`spark
   <words>`, `chat`, `do`, the page, any `/v1` client naming no model)
   goes to the second. One server, one port, one token; the request's
   `model` field picks. `spark ember auto` pairs the smallest tested row
   with the largest that fits beside it; `spark ember none` (the
   default) runs one model in both roles.
5. `spark model add URL` adds your own row: a huggingface.co
   `.../resolve/<rev>/<file>` URL is verified from its redirect headers,
   any other URL needs `--sha256 HEX`; `--license "NAME URL"` is
   required. The row lands in `~/.config/spark/models.env`, then it is
   downloaded and served like any row.
6. `spark model verify` re-hashes every downloaded file, prints `ok` or
   `bad -- spark model rm NAME; spark model NAME` per file, and exits 1
   on a mismatch; nothing is deleted for you. `spark check`'s `models`
   row is the daily, cached version of the same check.

Speed: `spark bench` measures with llama-bench (pp512 / tg128) and keeps
the result as the file's baseline; the `throughput` check row warns when
real turns fall below 70 percent of it. `spark bench tune` tries GPU
layers, flash attention, KV cache types and thread counts; `spark bench tune
apply` writes the winner to `spark.env` and restarts. `spark stats
[--week]` sums up what real turns measured. The server keeps no prompt
cache in RAM (`--cache-ram 0`: llama-server would otherwise keep up to
8 GiB of replaced prompts in host memory); `SPARK_EXTRA_ARGS=--cache-ram
N` in `spark.env` sets a budget in MiB.

## 5. Other machines and your phone

spark serves the same AI, with its soul, memory and threads, on one LAN
address (`http://<host>:8081`). The admin token stays on this machine;
everyone else is a named user with a token of their own.

Another machine of yours:

1. Here: `spark user add NAME` mints an account; its token is shown once
   and never stored.
2. There, with spark installed: `spark client URL` (the URL from `spark
   forge --print-client` here), then `spark user login NAME` with that
   token.
3. `spark brain` there says which server answers.

A client runs nothing of its own: no engine, no model, no units. `spark
check` there reads `na` on those rows and the `peer` row says whether
this machine answers. `spark model` there prints this machine's table;
choosing a model there is refused. `spark client off` gives it a model
of its own again.

Any program, with the OpenAI shape (a request naming no `model` gets the
conversation model with the identity; `model: spark` the bare prompt
model):

```sh
curl -sN http://<host>:8081/v1/chat/completions \
  -H "Authorization: Bearer $YOUR_SPARK_USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"what is this machine for?"}],"stream":true}'
```

The page, in any browser on the LAN:

1. `spark forge --print-url` prints `http://<host>:8081/login` and, on a
   terminal, the admin token.
2. Type a token once; the browser keeps a cookie (90 days; a server
   restart asks again). The admin token opens the whole machine (every
   verb, `do`, the config, the log, this account's threads); a user's
   token opens that user's own chat, threads, memory and a read-only
   monitor. Give each of the household their own `spark user add NAME`.
3. On a phone, add it to the home screen (iOS: share > add to home
   screen, and it becomes an app; Android keeps a shortcut that opens in
   a browser tab). The page needs this machine reachable when it opens:
   there is no offline copy.

`spark forge` alone is the status (URL, health, model, unit, users);
`spark forge on|off` enables or disables it. `spark forge token --new`
rotates the admin token; `spark user token --new` rotates a user's;
that principal logs in again.

Sealed stores: each user's threads, memory and chat history are
encrypted (ChaCha20-Poly1305, written from RFC 8439) under a key wrapped
by that user's token. The machine keeps a sha256 verifier and the wrap,
never the token: nobody, the admin included, holds a key to another
user's messages, and a lost token is lost history. There is no TLS on
the LAN: the trust model is your LAN.

Headless. On the machine that stays on, `spark headless on`:

- Linux: the units run from boot without a login (linger), the GPU is
  reachable without a seat (the `render` group), sleep, suspend and
  hibernate are masked, the lid is ignored. `off` reverses all but
  linger and the group.
- macOS: the three agents move to `/Library/LaunchDaemons` (no
  auto-login; FileVault's login screen is untouched) and `pmset` keeps
  the machine awake. Restart and stop then need `sudo launchctl` (the
  verbs print the line). `off` puts the login agents back.
- WSL 2 stops with its last window: `spark headless on` refuses there.

Then point every laptop (`spark client URL`) and every phone at it: one
address, one identity, the same answers everywhere. The `headless` check
row names any piece that is missing.

## 6. Per-OS notes

macOS:

- macOS asks once whether `python3` may find devices on the local
  network: that is spark binding your LAN address. Allow it; deny it and
  the page answers only this machine.
- The engine is the pinned llama.cpp tarball for arm64 or x64 (Metal
  inside), under `~/.local/share/spark/engine/`; bootstrap clears its
  quarantine flag. If Gatekeeper still objects: `xattr -dr
  com.apple.quarantine ~/.local/share/spark/engine`.
- Nothing from Homebrew. `spark font FACE SIZE` sets Terminal.app's
  font (`spark font list` shows the monospace faces installed).
- Units: `launchctl print gui/$UID/spark.serve` (`.forge`, `.check`
  likewise); `launchctl kickstart -k gui/$UID/spark.serve` restarts one.
  There is no root-free GPU counter, so `stats` and the `gpu` row say so.
- `Alt-s` is Option-s; `Esc` then `s`, quickly, is the same keys.

Linux:

- The engine is the pinned tarball for x86_64 or arm64: the Vulkan build
  when a GPU reports its memory in `/sys/class/drm` (`SITE_AI_BUILD=auto`;
  `vulkan` and `cpu` choose outright). The Vulkan build brings the Mesa
  Vulkan packages with the same sudo. The `gpu` row names the build this
  machine gets; when the extracted engine is the other build, the
  `engine` row says so and `./bootstrap.sh` replaces it. An architecture
  without a pin: point `SPARK_ENGINE_DIR` at a build of your own.
- Integrated GPUs: the BIOS decides how much RAM the iGPU owns ("UMA
  frame buffer size"). If the `gpu` row says the model is larger than
  VRAM, raise it there (8 GB for a 4B-8B model), then `spark bench`
  again.
- The `render` group grants the GPU without a logind seat: bootstrap
  adds you on a vulkan build; log out of every session and in again for
  the units to see it.
- `spark font Terminus 16x32` gives the text console a readable font
  (`spark font list` shows the faces and sizes this box has, width by
  height). The console cannot draw the check and arrow glyphs; spark
  notices (`TERM=linux`) and prints ASCII; `SPARK_ASCII=1` forces it.
- `spark theme NAME` reaches the text console: the palette is sent to
  the console you type on and set at boot for every VT (the
  `spark-console` unit, `setvtrgb`). GUI terminals stay yours: apply
  `theme.env` in their settings by hand. Nothing is painted until you
  ask.
- Units: `systemctl --user status spark-serve spark-forge
  spark-check.timer`; `journalctl --user -u spark-serve -n 50`. Without a
  user systemd session (a container) the `services` row reads `na`; run
  `spark serve` and `spark forge` by hand.

Arch:

- Linux to spark: the same one-liner, the same rows. The engine is the
  pinned `ubuntu-*` tarball (a glibc build; Arch's glibc is newer). CI
  proves the one-liner in an Arch container; the console, the units and
  the GPU there are proven by hand.
- Packages come through `pacman -S --needed`, never `-Sy` alone; when a
  name cannot be found the `packages` row says `sudo pacman -Syu` first.
  `gcc-libs` is in `base`: without a GPU nothing is installed.
- No console-setup: `spark font` refuses to set and the `font` row says
  so; the console font is `/etc/vconsole.conf`'s (`FONT=ter-132n` with
  `terminus-font`; `sudo systemctl restart systemd-vconsole-setup`).
- `spark quiet login on` works; `spark quiet boot` refuses (no
  `update-grub`). By hand with systemd-boot: `timeout 0` in
  `/boot/loader/loader.conf` and `quiet loglevel=3
  systemd.show_status=false udev.log_level=3 vt.global_cursor_default=0
  fbcon=nodefer` on the entry's `options` line under
  `/boot/loader/entries/`. With GRUB: the same words in
  `GRUB_CMDLINE_LINUX_DEFAULT`, `GRUB_TIMEOUT=0`,
  `GRUB_TIMEOUT_STYLE=hidden`, then `sudo grub-mkconfig -o
  /boot/grub/grub.cfg`.

Windows (Ubuntu 24.04 on WSL 2):

- Linux to spark: the same one-liner, the same rows; `spark check` and
  the status line say `WSL 2`. Not proven by CI (no WSL runner): the
  one-liner end to end there is on you, for now.
- The engine is the CPU build: WSL 2 exposes the GPU as `/dev/dxg`, not
  as a DRM card, so `auto` lands on `cpu` and picks under the 3 GB cap
  (qwen3-4b on most machines). `SITE_AI_BUILD=vulkan` through Mesa is
  yours to try, untested.
- No console: the font is Windows Terminal's (`spark font` refuses; the
  `font` row reads `na`). No GRUB: `spark quiet boot` refuses; `spark
  quiet login` works.
- Units: if the `services` row reads `na`, put `[boot] systemd=true` in
  `/etc/wsl.conf`, `wsl --shutdown` from PowerShell, reopen,
  `./bootstrap.sh`.
- Not a server for the LAN: the distro stops with its last window, so
  `spark headless on` refuses. Reaching the page from the LAN needs
  `networkingMode=mirrored` in `.wslconfig` (Windows 11), untested here.

## 7. Keep it

Update:

```sh
spark update
```

A clone `get` made moves to the newest release tag; a developer clone on
a branch pulls `--ff-only`. Either way it converges (bootstrap.sh runs,
`spark check` re-reads); `--dry-run` says what it would do. By hand:
`git -C ~/.spark pull --ff-only && ~/.spark/bootstrap.sh`.

Uninstall:

```sh
spark uninstall
```

1. It prints the plan, one row per thing, then asks for the word `yes`.
2. Everything spark made goes: the units, the rc line, the console
   palette and font (VGA again), the shell layer's files back from their
   `.bak` (SHELL.md), `~/.local/bin/spark`, the engine and every model,
   `~/.config/spark`, `~/.local/state/spark`, and the clone at `~/.spark`
   when it is the one `get` made and clean. Headless and the quiet login
   and boot are undone first (sudo).
3. What stays, on purpose: your soul, your memory, the sealed users'
   stores with their keys, your `models.env`, your themes and
   `privacy-terms`; `--purge` takes those too. The shell layer's packages
   are a question (`--packages` / `--keep-packages` answer up front).
   `--dry-run` shows the plan; `--yes` skips the question for a script.
4. Named at the end with the line that puts it back: a hostname it set,
   macOS's `pmset` values, a console font set before v1.12. A root step
   whose sudo refuses becomes a `todo` row, never a failure.

The keys. Everything in `~/.config/spark/site.env` beyond the three
setup asks is optional and has a verb; editing the file and running
`./bootstrap.sh` does the same.

| key | values | default |
|---|---|---|
| `SITE_NAME` | this machine's display name | short hostname |
| `SITE_USER` | your display name | your login |
| `SITE_SET_HOSTNAME` | `yes`: the OS hostname follows `SITE_NAME` (sudo) | `no` |
| `SITE_AI_MODEL` | `auto`, `none`, or a name -- `spark model NAME`; `none` beside a peer URL is a client | `auto` |
| `SITE_EMBER_MODEL` | `none`, `auto`, or a name: the second model for conversations -- `spark ember NAME` | `none` |
| `SITE_AI_BUDGET` | 10..95: percent of RAM+GPU memory `auto` may use -- `spark model budget N` | `60` |
| `SITE_AI_BUILD` | `auto`, `cpu` or `vulkan`: the Linux engine build (macOS ignores it; WSL 2 lands on `cpu`) | `auto` |
| `SITE_PEER_AI_URL` | another machine's URL (`spark forge --print-client` there) -- `spark client URL` | unset |
| `SITE_HEADLESS` | `yes`: up from boot, never asleep -- `spark headless on\|off` | `no` |
| `SITE_THEME` | `none`, or a palette from `themes/` or `~/.config/spark/themes/` -- `spark theme NAME`; painted only when you ask | `none` |
| `SITE_FONT_FACE` / `SITE_FONT_SIZE` | Linux console: a face and size from `spark font list` (`Terminus` `16x32`); macOS: Terminal.app's font and points -- `spark font FACE SIZE`. Refused on WSL 2 and Arch (no console-setup) | unset / `16x32` (Linux), the Nerd Font / `13` (macOS) |
| `SITE_QUIET_START` | `yes`: no banner, one-line `serve`, `forge` and bare `spark` -- `spark quiet start on` | `no` |
| `SITE_QUIET_AUDIO` | `yes`: no sound from spark -- `spark quiet audio on` | `no` |

Runtime knobs live in `~/.config/spark/spark.env` (`spark.env.example`
lists them all); the ones with a verb:

| key | values | default |
|---|---|---|
| `SPARK_MEMORY` | `on`/`off`: send the remembered facts -- `spark memory on\|off` | `on` |
| `SPARK_FORGE` | `auto`/`on`/`off`: serve the page and the API -- `spark forge on\|off` | `auto` |
| `SPARK_FORGE_HOST` / `SPARK_FORGE_PORT` | the address and port (never `0.0.0.0`) | the LAN address / `8081` |
| `SPARK_HISTORY` | days of turns and threads kept; `off` keeps none | `30` |
| `SPARK_NGL` `SPARK_FLASH_ATTN` `SPARK_KV` `SPARK_THREADS` | the engine's tuning -- `spark bench tune apply` | auto |
| `SPARK_API_KEY_FILE` | a token file you already have | `~/.local/state/spark/api-token` |

What needs root. `bootstrap.sh --dry-run` lists exactly which of these
it would do and never calls sudo:

- always: the package manager for the `packages` row (`libgomp1` on
  Debian, the Vulkan libraries with a GPU) and the hostname when
  `SITE_SET_HOSTNAME=yes`; macOS the hostname only;
- `spark shell on`: the shell tools, the console font and palette, the
  quiet login and boot, each only when its key says so;
- `spark headless on`: linger, the `render` group, the sleep targets,
  the lid; macOS the LaunchDaemons and `pmset`.

`spark uninstall` uses sudo for the mirror image. Passwordless sudo is
yours to decide (`echo 'you ALL=(ALL) NOPASSWD:ALL' | sudo tee
/etc/sudoers.d/you`, fine for a test bench).

When something stops working:

1. `spark check` names the row and the remedy (long output pages
   through `$PAGER`, plain when piped).
2. `./bootstrap.sh --dry-run`: what a rebuild would change.
3. `spark`: which server answers, which shells have the widget.
4. A stale server after a DHCP move shows as `moved` on the `serve` row:
   `spark serve off; spark serve on`. The `forge` row likewise:
   `spark forge off; spark forge on`.
5. `spark forge`: is the page up, at which address; one line per request
   in `~/.local/state/spark/forge.log`, never a body.
6. The `ember` row: the pair over budget, the file not downloaded
   (`./bootstrap.sh`), or not warm (`spark serve` warms it).
7. A GPU new servers cannot see (the `gpu` row warns): on Linux the
   serving user must be in the `render` group; log out of every session
   and in again.
8. `SPARK_DEBUG=1 spark ...` and `~/.local/state/spark/debug.log`.

## Appendix: how it fits together

```
your shell                    this machine                        the LAN
----------                    ------------                        -------
? words ---- widget -------> spark line ---+
an app's key - spark-<app> -> spark edit --+
spark chat | do | explain -> spark <verb> -+-> spark's server :8081 --> another
                                           |   soul, memory, threads;    machine's
                                           |   /v1 and /api; the page    spark, a
                                           |                             browser,
                                           +-> llama-server :8080 <---- a program
                                               one model, or two:
                                               the pinned engine and a
                                               GGUF from models.env

get -> spark setup -> bootstrap.sh (apply) -> install.sh (links, renders)
                      the engine, the model, the token, the units, one rc
                      line; spark shell on adds spark's shell; a spark app
                      is its own repository (spark-<app>)

spark check   40 rows: every promise the machine makes, fixture-tested
spark update  the newest tag, or main on a developer clone; converge

what leaves the machine: pinned downloads in, your questions to the
server you chose, nothing else -- no telemetry, no account, one LAN address.
```
