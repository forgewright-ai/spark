# Installing spark

Start at section 1 without a machine, at section 2 with one. The rest
is the runbook, in the order you need it.

## 1. A machine from zero

About ten minutes, with `sudo` once. One model download takes most of
it, usually 2.3 to 17 GB. Section 4 says which model.

Debian:

1. Get Debian 13, the small network installer image, from debian.org.
   Take `amd64` for a PC and `arm64` for an ARM board. Write it to a
   USB stick and boot it.
2. In the installer, leave the root password empty. That puts your user
   in the `sudo` group. Under software selection keep the SSH server and
   the standard system utilities. A desktop is optional.
3. Log in and install what spark needs:

   ```sh
   sudo apt-get update && sudo apt-get install -y git curl python3
   ```

4. Continue at section 2.

Arch:

1. Get the ISO from archlinux.org, write it to a USB stick and boot it.
2. Run `archinstall`. The answers that matter:
   - The minimal profile.
   - A user account marked superuser. That is the `sudo`.
   - `systemd-boot` as the bootloader. GRUB works too.
   - `git curl python openssh` under additional packages.
   - Copy the ISO's network configuration. That keeps the Wi-Fi you
     joined with `iwctl`.
   - One HTTPS mirror as a custom server, such as
     `https://geo.mirror.pkgbuild.com/$repo/os/$arch`. A router that
     inspects HTTP turns a plain mirror into `invalid or corrupted
     database (PGP signature)`.
3. Reboot, log in, run `sudo pacman -Syu` once, then section 2.

A machine that will not join the Wi-Fi: `docs/TROUBLESHOOTING.md`.

macOS: any Mac Apple still updates. `xcode-select --install` brings
`git`, `curl` and Apple's `python3`. Version 3.9 is enough.

Windows: spark runs in WSL 2, where Ubuntu is Linux to it. In
PowerShell run `wsl --install -d Ubuntu-24.04` and reboot when asked.
Open Ubuntu, then do Debian's step 3.

## 2. Install spark

1. Check the five things spark needs: `sudo` once for the package
   manager, `git`, `curl`, `python3` 3.9 or newer, and `ssh-keygen`.
   The last one checks the release's signature.

   ```sh
   for c in sudo git curl python3 ssh-keygen; do
       command -v "$c" >/dev/null || echo "missing: $c"
   done
   python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' \
       || echo "python3 is older than 3.9"
   ```

   Silence means you are ready. Otherwise:

   - Debian 13 / Ubuntu 24.04 or newer: `sudo apt-get install -y git
     curl python3 openssh-client`. With no `sudo` at all, run `su -c
     'apt-get install -y sudo && usermod -aG sudo YOURNAME'`, then log
     out and in.
   - Arch Linux, or what says `ID_LIKE=arch`: `sudo pacman -S --needed
     git curl python openssh`. Run `sudo pacman -Syu` first when a
     package cannot be found. `pacman -Sy` alone breaks a rolling
     distro.
   - macOS: `xcode-select --install`.
   - Your login shell must be bash 4 or newer, or zsh. The prompt line
     lives in one of them. macOS ships zsh, and its bash is 3.2.

2. One line:

   ```sh
   curl -fsSL https://github.com/forgewright-ai/spark/releases/latest/download/get | sh
   ```

   It clones spark to `~/.spark`, lands on the newest release and runs
   `spark setup`. To read the script first:

   ```sh
   curl -fsSLO https://github.com/forgewright-ai/spark/releases/latest/download/get
   sh get
   ```

   With `wget`: `wget -qO- URL | sh`. By hand, the same two steps:

   ```sh
   git clone https://github.com/forgewright-ai/spark.git ~/.spark
   ~/.spark/bin/spark setup
   ```

3. When it finishes:

   ```sh
   exec $SHELL      # the prompt line goes live
   spark check      # every row ok
   ```

What `get` does first. It checks the ground: the command line tools on
macOS, `apt-get` or `pacman`, `git`, `python3` 3.9 or newer, and
`ssh-keygen`. When one is missing it refuses and prints the install
line. It never runs `sudo`. `SPARK_HOME` moves the clone, `SPARK_URL`
points it at another repository, and `SPARK_REF=main` follows
development. `sh get --clone-only` stops after the clone.

What `spark setup` does. It asks three things and never more: this
machine's name, yours, and the model. The name defaults to the short
hostname, yours to your login. The model row this machine earns is
marked `*`. Then it:

1. Writes `~/.config/spark/site.env` at 0600.
2. On Linux, asks `sudo -v` once when a package is missing: `libgomp1`
   on Debian, plus the Mesa Vulkan packages with a GPU. Arch has the
   library in `base`, so it asks only with a GPU. macOS needs nothing.
3. Runs `bootstrap.sh`: the engine, one pinned llama.cpp tarball for
   this OS, checked by sha256. The model, with curl's progress bar. The
   token, the prompt line, one rc line, and the units: the engine's
   server, the page's server and a check timer every five minutes.
4. Brings the server up and waits for it.
5. Asks `? how big is this dir` for you and prints the tok/s it
   measured.
6. Prints the three things to try.

It paints nothing: the machine looks as it did. You can run it again at
any time. `--yes` takes every default, and is implied when stdin is not
a terminal. `--model NAME|auto|none`, `--name NAME`, `--user NAME`,
`--theme NAME` and `--no-serve` pre-answer, as do `SITE_NAME`,
`SITE_USER`, `SITE_AI_MODEL` and `SITE_THEME` in the environment.

The rc line. `bootstrap.sh` appends one line to your login shell's rc
file, `~/.bashrc` for bash or `~/.zshrc` for zsh, and only when it is
not there yet:

```sh
[ -r ~/.config/spark/hook.bash ] && . ~/.config/spark/hook.bash   # spark: the AI at the prompt
[[ -r ~/.config/spark/hook.zsh ]] && source ~/.config/spark/hook.zsh   # spark: the AI at the prompt
```

The hook puts `~/.local/bin` first on `PATH`, loads the prompt line,
keeps a blank row above the prompt for the hint, and loads `TAB`
completion. Completion is offline: the verbs, then each verb's words.
The line goes last, after fzf, because the prompt line wraps `Enter`.
If `spark setup` prints a `todo rc` row, the login shell cannot host
the prompt line: another shell, or macOS's bash 3.2. Run `chsh -s
/bin/zsh`, then `spark setup` again. A bare zsh needs your own
`autoload -Uz compinit && compinit` in `~/.zshrc` for completion.

## 3. Use it

The prompt line. Type `? words` or `words?` and press `Enter`. The
command lands in your line with a hint above it, and `Enter` again
runs it. A command that deletes comes back marked `!`, and a recursive
`rm` says how many files and bytes it clears. `?? words` follows up on
the last answer. `Esc s` asks about the line you are on. `spark off`
gives `Enter` back, and `spark on` restores it. `TAB` completes the
verbs and their words, offline. While the model answers, the mark
pulses in that row. The marks are plain unless your rc exports
`SPARK_ACCENT_SGR`, `SPARK_MUTED_SGR` and `SPARK_WARN_SGR`, SGR codes
such as `1;94`. A pipe never sees an escape.

The failure line. When a command fails, one line appears above the next
prompt: `* failed (1) -- press Esc s to ask why`. `Esc s` on the empty
line puts the command back, piped to `explain`, and nothing runs until
you press `Enter`. A second `Esc s` proposes the corrected command.
When a command is not found, exit 127, `Esc s` offers the line that
installs it. A command that deletes or destroys is never offered a
re-run. After the fix works, `Esc s` offers to keep it as a `spark
memory add` fact. `Ctrl-C` and a no-match from `grep` or `diff` stay
quiet.

`Esc r` is intent search. Type what a command did in your own words and
press `Esc r`. The line that ran lands in your prompt, and `Esc r`
again cycles through the matches. Every candidate is a line from your
shell's own history. `Ctrl-R` stays the shell's.

Every verb below has a `-h` with the rest.

`spark chat` is a conversation at a `chat> ` prompt. `/help` lists its
verbs. `/q` or `Ctrl-D` ends, and `Ctrl-C` cancels a reply. `spark chat
--thread N` continues an older thread from the `spark history` list.

`spark <words>` streams one answer. `spark @FILE words` sends a text
file's first 4 kB and last 12 kB with the question.

`spark do <words>` proposes one command at a time. `Enter` runs it, `e`
edits it, `s` skips it, `q` quits. A step that can destroy data runs
only when you type `yes`. After a step, its proof, one read-only
check, is offered the same way, and only its exit code goes back. Each
step's output, the last 4 kB, goes back to the model until it says
done, or after 8 steps. A goal is at most 8 kB, and one that starts
with `-` goes after `--`.

`spark do --sandbox <words>` does the same task in a copy of this
directory. Every step runs on its own, two minutes at most, with no
network, nothing outside the copy writable, and your home out of
sight. A run writes 1 GB at most. At the end you see the diff and type
`yes` to apply it here. `yes` applies exactly what you saw, and a copy
or a file that changed since leaves the run waiting. Inside a git
directory only git's own records apply. Its config and hooks are held
back and listed. `spark do --review` lists the runs waiting, `--review
ID` shows one and asks again, `--accept ID` applies one unseen, for a
script, and `--discard ID` drops it. `spark` says `1 run waiting`
while one does.

`spark do --sandbox --detach <words>` does the same with nobody there.
It prints the run's id and leaves the changes waiting, one detached
run at a time. A systemd user timer or a launchd agent can run it
daily, and `spark watch` can start it when a line matches.

`spark ask < plan.md` answers with the questions the text does not
answer: at most three, one per line, and nothing else. A line that is
not a question, one quoting words the text lacks, and one that fits
any plan are dropped. Nothing left is one line and exit 1. The text is
at most 12 kB. `--answered --name NAME` keeps a question from coming
back, and `--ledger --name NAME` lists what you answered.

`spark read <words> < page.txt` says what a source says, and only that.
Every line quotes the source, and the quote is checked. When the
source does not answer, the reply is one line with its opening words
and exit 1. A source past 16 kB is read one `--part N` at a time. What
looks like a secret is held back before it leaves, and the model sees
`[held]`. `--name NAME` records the question here, never elsewhere.

`spark drill < notes.md` turns the source into questions it answers.
You try each, then see the source's own words and say whether you had
it. An answer the model invents is dropped before it is asked. `--name
NAME` keeps a schedule: a miss comes back after 1, 3, 7, 21 and 60 days
until you have it right twice in a row.

`tail -f app.log | spark watch "a 500 appears"` reads a live stream,
silent until a line matches, then one line quoting it. The quote is
checked against the stream. A window of up to 40 lines or ten seconds,
8 kB at most, goes to the server you chose, never the whole stream.

`spark soul edit` writes the paragraph that tells the model who it is:
`~/.config/spark/soul`, at most 4000 characters. `spark soul reset`
goes back to the default:

```
You are spark, the AI on this machine. You run here, on hardware the user
owns; nothing you are told leaves it. You are here to answer, to explain,
to write, and to hand the user a command when one is what they need.
Speak plainly, in the user's language. Say when you do not know. Never
invent a flag, a path, or a command.
```

`spark memory add <words>` adds a fact it keeps: 40 facts of 200
characters. `spark memory forget N` drops one, and `spark memory off`
stops sending them. Soul and facts ride on every conversation, so keep
the facts that change answers. The model never writes them.

`spark bar line` prints the machine's status in one line: load, memory,
disk, net, the model, the last check, runs waiting and the clock. A
status bar runs it every 15 seconds.

## 4. Models

Two files:

| file | what |
|---|---|
| `models.env` | every model spark can serve: 26 models, each with its license. `line` marks a row proven on the prompt line |
| `~/.config/spark/models.env` | your own rows (`spark model add URL --license`), 0600, marked `u` |

`spark model list` shows every row: the file size, the RAM it needs
against this machine's budget, the license, the proof column,
downloaded or serving, and its speed here. The budget is
`SITE_AI_BUDGET`, 60 percent of RAM plus GPU memory by default. The
proof column says `line` when the row is tested on the prompt line, or
a `kept/run` score once the grounding audition measured how faithfully
it quotes a source. A scored row wins an `auto` tie. The speed `~N
tok/s` is an estimate until `spark bench` or a real turn measures it,
and `too big` means the row does not fit. The tested rows:

| name | file | RAM |
|---|---|---|
| `qwen3-1-7b` | 1.0 GB | 3 GB |
| `qwen3-4b` | 2.3 GB | 5 GB |
| `qwen3-8b` | 4.7 GB | 7 GB |
| `qwen3-14b` | 8.4 GB | 11 GB |
| `qwen3-30b-a3b` | 17.4 GB | 21 GB |
| `granite-4-2-8b` | 5.0 GB | 7 GB |

The other 20 rows are yours by name: more Qwen, Mistral, Phi-4,
DeepSeek-R1, SmolLM2, gpt-oss, Llama and Gemma. A row under a license
that is not Apache-2.0 or MIT prints its license and asks `download
it? yes/NO:` first. The project site lists them all at
spark.forgewright.ai/models/.

How `auto` picks. It takes every tested open-license row whose RAM fits
the budget. Of those, it takes the largest whose file is under this
build's speed cap: 3 GB on `cpu`, 6 GB on `vulkan`, 20 GB on `metal`.
Those sizes keep about 8 tok/s. When the cap held a bigger row back,
the table's header says so, and `spark model NAME` takes that row
anyway. When nothing under the cap fits, it takes the smallest row
that fits.

1. `spark model NAME` chooses a model. It downloads the file, checks
   its size and sha256 against the row, and restarts the server. `spark
   model auto` goes back to the rule above. `spark model rm NAME`
   deletes a file not in use.
2. `spark model budget N`, 10 to 95, sets the percent and prints the
   table.
3. A `.gguf` of your own in `~/.local/share/spark/models` is served
   with `SPARK_MODEL=<file>` in `spark.env`.
4. `spark ember NAME` adds a second, bigger model for conversations.
   The prompt line stays with the small one, at context 4096 with
   reasoning off, so a thinking model answers fast. Every conversation
   goes to the second: `spark <words>`, `chat`, `do`, the page, and any
   `/v1` client naming no model. One server, one port, one token: the
   request's `model` field picks. `spark ember auto` pairs the smallest
   tested row with the largest that fits beside it. `spark ember none`,
   the default, runs one model in both roles.
5. `spark model add URL` adds your own row. A huggingface.co
   `.../resolve/<rev>/<file>` URL is checked from its redirect headers,
   and any other URL needs `--sha256 HEX`. `--license "NAME URL"` is
   required. The row lands in `~/.config/spark/models.env`, then it is
   downloaded and served like any row.
6. `spark model verify` hashes every downloaded file again. It prints
   `ok` per file, or `sha256 MISMATCH -- spark model rm NAME; spark
   model NAME`, and exits 1 on a mismatch. Nothing is deleted for you.
   The `models` row of `spark check` is the daily, cached version.

Speed. `spark bench` measures with llama-bench, prompt 512 and generate
128, and keeps the result as the file's baseline. The `throughput` row
warns when real turns fall below 70 percent of it. `spark bench tune`
tries GPU layers, flash attention, KV cache types and thread counts,
and `spark bench tune apply` writes the winner to `spark.env`. `spark
stats [--week]` sums up what real turns measured. The engine keeps no
prompt cache in RAM, `--cache-ram 0`, because llama-server would
otherwise keep up to 8 GiB of replaced prompts in host memory.
`SPARK_EXTRA_ARGS=--cache-ram N` in `spark.env` sets a budget in MiB.

## 5. Other machines and your phone

spark serves the same AI, with its soul, memory and threads, on one LAN
address: `http://<host>:8081`. The admin token stays on this machine.
Everyone else is a named user with a token of their own.

The servers. Two run on this machine. The engine's server, llama-server
on port 8080, holds the model. The page's server on port 8081 holds the
soul, the memory and the threads, and answers the page, the API and
every client. `spark serve on` starts the engine's server and waits
until it answers. `spark serve off` stops it, and `--force` also stops
the unit's, or one spark did not start. `--host ADDR` binds another
address, `--print-client` prints the two lines another machine needs,
and `--foreground` is what the unit runs.

Another machine of yours:

1. Here: `spark user add NAME` mints an account. Its token is shown
   once and never stored.
2. There, with spark installed: `spark client URL`, with the URL from
   `spark forge --print-client` here. Then `spark user login NAME` with
   that token.
3. `spark client` there says whether this machine answers.

A client runs nothing of its own: no engine, no model, no units, and no
account of its own. The login is the token minted here. `spark check`
there reads `na` on those rows, and the `peer` row says whether this
machine answers and accepts that login. `spark model` there prints
this machine's table, and choosing a model there is refused. `spark
client off` gives it a model of its own again.

Another OS user on this same machine, on Linux: you run `spark share
on` once. That makes a `spark` group with one engine for everyone. Add
the user to the group with `sudo gpasswd -a NAME spark`, and they log
in again. Then they run the one-liner in their own home, with no `sudo`
and no download. `spark setup` sees the shared engine and joins it:
their own soul and memory, one model loaded once. `spark share off`
ends it.

Every program that calls spark, a script, an app or a CI job, gets its
own user with `spark user add NAME` and its own token. The admin token
is never shared. Any program with the OpenAI shape works. A request
naming no `model` gets the conversation model with the identity, and
`model: spark` the bare prompt model:

```sh
curl -sN http://<host>:8081/v1/chat/completions \
  -H "Authorization: Bearer $YOUR_SPARK_USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"what is this machine for?"}],"stream":true}'
```

The users. `spark user list` shows them with their threads and last
activity. `spark user add NAME` mints an account and shows its token
and a QR of its login link once, and `--no-qr` skips the QR. `spark
user remove NAME` deletes the account and its sealed data, and asks
first. `SPARK_YES=1` answers yes, for a script. `spark user login NAME`
pastes a token so this machine acts as NAME. `spark user logout`
forgets the login, and the sealed data stays. `spark user token --new`
rotates your token, and other logins die. A name is a-z, 0-9 and `-`,
starting with a letter, at most 32 characters.

The page, in any browser on the LAN:

1. `spark forge --print-url` prints `http://<host>:8081/login`. At a
   terminal it also prints the admin token and a QR code. Piped, it
   prints the URL alone, and `--show-token` adds the token. Scan the
   QR with a phone's camera and the page signs in by itself. The token
   rides the link after `#`, which never reaches the server. The QR is
   the token drawn as squares: show it only to the person it is for.
2. Or type a token once. The browser keeps a cookie for 90 days, and
   logging out or a server restart asks again. A user's token opens a
   chat app: their own threads and memory, plus their account behind
   the one menu button. The admin token also opens the whole machine:
   activity, `do`, the settings and the log.
3. On a phone, add it to the home screen. On iOS, share, then add to
   home screen, and it becomes an app. Android keeps a shortcut that
   opens in a browser tab. The page needs this machine reachable when
   it opens. There is no offline copy.

`spark forge` alone is the status: URL, health, model, unit, token and
the log tail. `spark forge on|off` enables or disables it. `spark forge
token --new` rotates the admin token, and `spark user token --new`
rotates a user's. That person logs in again. `spark forge audit` lists
the newest admin actions, sealed in this machine's own store. Each is a
command run from the page, with its sha256 prefix and exit code and
never its text, a verb run, or a user added, removed or rotated.

Sealed stores. Each user's threads, memory and chat history are
encrypted under a key wrapped by that user's token. The cipher is
ChaCha20-Poly1305, written from RFC 8439. The machine keeps a sha256
verifier and the wrap, never the token. Nobody, the admin included,
holds a key to another user's messages. A lost token is lost history.
There is no TLS on the LAN: the trust model is your LAN.

Headless. On the machine that stays on, `spark headless on`:

- Linux: the units run from boot without a login, by linger. The GPU is
  reachable without a seat, by the `render` group. Sleep, suspend and
  hibernate are masked, and the lid is ignored. `off` reverses all but
  linger and the group. Over a plain `ssh HOST spark model NAME` the
  units are reached the same way: spark brings the user bus itself.
- macOS: the three agents move to `/Library/LaunchDaemons`, with no
  auto-login, and FileVault's login screen is untouched. `pmset` keeps
  the machine awake. Restart and stop then need `sudo launchctl`, and
  the verbs print the line. `off` puts the login agents back.
- WSL 2 stops with its last window, so `spark headless on` refuses
  there.

Then point every laptop at it with `spark client URL`, and every phone
at the page: one address, one identity, the same answers everywhere.
The `headless` row names any piece that is missing.

## 6. Per-OS notes

macOS:

- macOS asks once whether `python3` may find devices on the local
  network. That is spark binding your LAN address. Allow it. Denied,
  the page answers only this machine.
- The engine is the pinned llama.cpp tarball for arm64 or x64, with
  Metal inside, under `~/.local/share/spark/engine/`. `bootstrap.sh`
  clears its quarantine flag. If Gatekeeper still objects: `xattr -dr
  com.apple.quarantine ~/.local/share/spark/engine`. Nothing comes from
  Homebrew.
- `spark theme NAME` makes a `spark-NAME` profile in Terminal.app.
  `spark theme profile` writes it again, imports it and makes it the
  default. `spark font FACE SIZE` sets the profile's font, by
  PostScript name and points, from `spark font list`.
- Units: `launchctl print gui/$UID/spark.serve`, and `.forge` and
  `.check` likewise. `launchctl kickstart -k gui/$UID/spark.serve`
  restarts one.
- There is no root-free GPU counter, so `spark stats` and the `gpu`
  row say so.
- `Alt-s` is Option-s. `Esc` then `s`, quickly, is the same keys.
- `spark do --sandbox` copies the project as an APFS clone and runs
  each step in it under `sandbox-exec`. A step opens no network socket
  and writes only to the copy and the run's own home and temp. It
  cannot read your home, other volumes, the temp directories, the
  keychain or spark's state and token. It cannot run `osascript`, `open`,
  `launchctl`, `sudo`, `security`, the clipboard, Shortcuts, Automator,
  `defaults`, `cron` or `at`. It still reads the rest of the system,
  such as `/Applications` and `/etc`, and sees the process list. The
  diff is the gate: read it before you type `yes`. The `sandbox` row
  says whether it works here. `sandbox-exec` is Apple's own tool, and
  its man page tells developers to move off it.

Linux:

- The engine is the pinned tarball for x86_64 or arm64. With
  `SITE_AI_BUILD=auto` it is the Vulkan build when a GPU reports its
  memory in `/sys/class/drm`, and `vulkan` or `cpu` choose outright.
  The `gpu` row names the build this machine gets. When the extracted
  engine is the other build, the `engine` row says so and
  `./bootstrap.sh` replaces it.
- An architecture without a pin: a `llama-server` already on `PATH`, or
  in `/usr/local/bin` or `/usr/bin`, is used, and the `engine` row
  reads `your build`. Or point `SPARK_ENGINE_DIR` at a build of your
  own. Where a pin exists, your build never replaces it.
- Integrated GPUs: the BIOS decides how much RAM the iGPU owns, under
  a name such as "UMA frame buffer size". If the `gpu` row says the
  model is larger than VRAM, raise it there, 8 GB for a 4B to 8B
  model, then `spark bench` again.
- The `render` group grants the GPU without a logind seat. `bootstrap.sh`
  adds you on a Vulkan build. Log out of every session and in again for
  the units to see it.
- `spark font FACE SIZE` gives the text console a readable font, and
  `spark font list` shows what this machine has. The font lands in the
  file the console reads: `/etc/default/console-setup` on Debian, as in
  `spark font Terminus 16x32`, and `/etc/vconsole.conf` on Arch, as in
  `spark font Lat2-Terminus16 8x16`. The original is kept beside it,
  and `spark uninstall` puts it back. `spark font none` leaves the
  console its own font. The console cannot draw the check and arrow
  glyphs, so spark prints ASCII there. `SPARK_ASCII=1` forces it.
- `spark theme NAME` reaches the text console: the palette is sent to
  the console you type on and set at boot for every VT, by the
  `spark-console` unit and `setvtrgb`. GUI terminals stay yours. Apply
  `theme.env` in their settings by hand.
- `spark do --sandbox` needs bubblewrap 0.11 or newer, which Debian 13
  and Arch ship. Ubuntu 24.04's 0.9 has no overlay, and the `sandbox`
  row reads `na` there. Each step runs in fresh namespaces: no network,
  and the homes, `/run`, `/tmp`, `/var/tmp`, `/media`, `/mnt` and
  `/etc/spark` hidden. The project is an overlay that keeps every
  write. `sudo` inside cannot become root. The rest of the system stays
  readable, so the diff is the gate there as well.
- Units: `systemctl --user status spark-serve spark-forge
  spark-check.timer` and `journalctl --user -u spark-serve -n 50`.
  Without a user systemd session, as in a container, the `services`
  row reads `na`. Run `spark serve` and `spark forge` by hand.

Arch:

- Linux to spark: the same one-liner, the same rows. The engine is the
  pinned `ubuntu-*` tarball, a glibc build, and Arch's glibc is newer.
  CI proves the one-liner in an Arch container. The console, the units
  and the GPU there are proven by hand.
- Packages come through `pacman -S --needed`, never `-Sy` alone. When a
  name cannot be found, the `packages` row says `sudo pacman -Syu`
  first. `gcc-libs` is in `base`, so without a GPU nothing is
  installed.
- The console font is the `FONT=` line of `/etc/vconsole.conf`, and
  `spark font` writes it there. `spark font list` reads the kbd fonts,
  and `terminus-font` adds the `ter-*` faces. A change restarts
  `systemd-vconsole-setup`, so every VT redraws.
- `spark quiet login on` works. `spark quiet boot on` works on an Arch
  that boots a Unified Kernel Image, the shape `archinstall` makes with
  `systemd-boot`. spark writes one drop-in,
  `/etc/cmdline.d/zz-spark-quiet.conf`, marks the preset's `--splash`
  line off, sets `timeout 0` in `/boot/loader/loader.conf` and runs
  `mkinitcpio -P`. The running kernel keeps its old line until you
  reboot, and the `quiet` row says `boot quiet after a reboot` until
  then. `spark quiet boot off` reverses each step. Hold Space at boot
  for the menu.
- Without a UKI the kernel line is your boot loader's, and `spark quiet
  boot` refuses. Put `quiet splash loglevel=3 systemd.show_status=false
  udev.log_level=3 vt.global_cursor_default=0 fbcon=nodefer` on the
  entry's `options` line under `/boot/loader/entries/`. With GRUB, put
  them in `GRUB_CMDLINE_LINUX_DEFAULT` with `GRUB_TIMEOUT=0` and
  `GRUB_TIMEOUT_STYLE=hidden`, then `sudo grub-mkconfig -o
  /boot/grub/grub.cfg`.

Windows, as Ubuntu 24.04 on WSL 2:

- Linux to spark: the same one-liner, the same rows. `spark check` and
  the status line say `WSL 2`. CI has no WSL runner, so the one-liner
  end to end there is on you, for now.
- The engine is the CPU build. WSL 2 exposes the GPU as `/dev/dxg`, not
  as a DRM card, so `auto` lands on `cpu` and picks under the 3 GB cap,
  `qwen3-4b` on most machines. `SITE_AI_BUILD=vulkan` through Mesa is
  yours to try, untested.
- No console: the font is Windows Terminal's. `spark font` refuses, and
  the `font` row reads `na`. No GRUB: `spark quiet boot` refuses, and
  `spark quiet login` works.
- Units: if the `services` row reads `na`, put `[boot] systemd=true` in
  `/etc/wsl.conf`, run `wsl --shutdown` from PowerShell, reopen Ubuntu,
  then `./bootstrap.sh`.
- Not a server for the LAN: the distro stops with its last window, so
  `spark headless on` refuses. Reaching the page from the LAN needs
  `networkingMode=mirrored` in `.wslconfig` on Windows 11, untested
  here.

## 7. Keep it

Update:

```sh
spark update
```

A clone `get` made moves to the newest release tag. A developer clone
on a branch pulls `--ff-only`. Either way it converges: `bootstrap.sh`
runs and `spark check` reads again. `--dry-run` says what it would do.
By hand: `git -C ~/.spark pull --ff-only && ~/.spark/bootstrap.sh`.

A release tag is signed. `spark update` moves only to a tag signed by a
key in the tree's `allowed-signers`. Any other tag is refused in one
line, `spark update -- v1.36 is not signed by a known key: refused`,
and nothing moves. `get` keeps the same rule. The `signed` row of
`spark check` names the key that signed the tag you are on.

Uninstall:

```sh
spark uninstall
```

1. It prints the plan, one row per thing, then asks for the word `yes`.
2. Everything spark made goes: the units, the hook line from your rc
   file, the console palette and font, `~/.local/bin/spark`, the engine
   and every model, `~/.config/spark` and `~/.local/state/spark`. The
   clone at `~/.spark` goes when it is the one `get` made and clean.
   Headless and the quiet login and boot are undone first, with `sudo`.
3. What stays, on purpose: your soul, your memory, the sealed users'
   stores with their keys, your `models.env`, your themes and
   `privacy-terms`. `--purge` takes those too. The packages spark
   installed are a question, and `--packages` or `--keep-packages`
   answer it up front. `--dry-run` shows the plan. `--yes`, or
   `SPARK_YES=1`, skips the question for a script.
4. Named at the end, with the line that puts it back: a hostname it
   set, macOS's `pmset` values, a console font set before v1.12. A root
   step whose `sudo` refuses becomes a `todo` row, never a failure.

The keys. Everything in `~/.config/spark/site.env` beyond the three
things setup asks is optional and has a verb. Editing the file and
running `./bootstrap.sh` does the same.

| key | values | default |
|---|---|---|
| `SITE_NAME` | this machine's display name | short hostname |
| `SITE_USER` | your display name | your login |
| `SITE_SET_HOSTNAME` | `yes`: the OS hostname follows `SITE_NAME` (sudo) | `no` |
| `SITE_AI_MODEL` | `auto`, `none`, or a name -- `spark model NAME`. `none` beside a peer URL is a client | `auto` |
| `SITE_EMBER_MODEL` | `none`, `auto`, or a name: the second model for conversations -- `spark ember NAME` | `none` |
| `SITE_AI_BUDGET` | 10 to 95: the percent of RAM plus GPU memory `auto` may use -- `spark model budget N` | `60` |
| `SITE_AI_BUILD` | `auto`, `cpu` or `vulkan`: the Linux engine build. macOS ignores it, and WSL 2 lands on `cpu` | `auto` |
| `SITE_PEER_AI_URL` | another machine's URL, from `spark forge --print-client` there -- `spark client URL` | unset |
| `SITE_PEER_SSH` | an ssh target, with key auth, that `spark check` should be able to reach | unset |
| `SITE_HEADLESS` | `yes`: up from boot, never asleep -- `spark headless on\|off` | `no` |
| `SITE_SHARE` | `yes`: a `spark` group shares this machine's engine with its other OS users (Linux) -- `spark share on\|off` | `no` |
| `SITE_THEME` | `none`, or a palette from `themes/` or `~/.config/spark/themes/` -- `spark theme NAME` | `none` |
| `SITE_FONT_FACE` / `SITE_FONT_SIZE` | Linux console: a face and size from `spark font list`, such as `Terminus` `16x32`. macOS: Terminal.app's font and points -- `spark font FACE SIZE`. Refused on WSL 2 | unset / `16x32` on Linux, `Menlo-Regular` / `13` on macOS |
| `SITE_QUIET_LOGIN` | Linux: `yes` bares the login: the motd and `/etc/issue`, originals kept -- `spark quiet login on` | `no` |
| `SITE_QUIET_BOOT` | Linux: `yes` makes the boot silent with one drop-in, GRUB's on Debian or `/etc/cmdline.d` on an Arch kernel image -- `spark quiet boot on`. Refused on WSL 2 and on an Arch without a UKI | `no` |
| `SITE_QUIET_START` | `yes`: no banner, and one-line `serve`, `forge` and bare `spark` -- `spark quiet start on` | `no` |
| `SITE_QUIET_AUDIO` | `yes`: no sound from spark -- `spark quiet audio on` | `no` |

Runtime keys live in `~/.config/spark/spark.env`, and `spark.env.example`
lists them all. The ones with a verb:

| key | values | default |
|---|---|---|
| `SPARK_MEMORY` | `on` or `off`: send the remembered facts -- `spark memory on\|off` | `on` |
| `SPARK_REVEAL` | `off`, `auto` or N: a reply's pace at a terminal in chat, explain and a question -- `--reveal` on the verb, `/reveal` in chat. `spark stats` shows the measured threshold | `off` |
| `SPARK_FORGE` | `auto`, `on` or `off`: serve the page and the API -- `spark forge on\|off` | `auto` |
| `SPARK_FORGE_HOST` / `SPARK_FORGE_PORT` | the page's address and port, never `0.0.0.0` | the LAN address / `8081` |
| `SPARK_HISTORY` | days of turns and threads kept. `off` keeps none | `30` |
| `SPARK_NGL` `SPARK_FLASH_ATTN` `SPARK_KV` `SPARK_THREADS` | the engine's tuning -- `spark bench tune apply` | auto |
| `SPARK_API_KEY_FILE` | a token file you already have | `~/.local/state/spark/api-token` |

What needs root. `bootstrap.sh --dry-run` lists which of these it would
do, and never calls `sudo`:

- Always: the package manager for the `packages` row, and the hostname
  when `SITE_SET_HOSTNAME=yes`. On macOS the hostname only.
- `spark font`, `spark theme` and `spark quiet`: the console font and
  palette, the quiet login and boot, each only when its key says so.
- `spark headless on`: linger, the `render` group, the sleep targets
  and the lid. On macOS the LaunchDaemons and `pmset`.

`spark uninstall` uses `sudo` for the mirror image. Passwordless `sudo`
is yours to decide: `echo 'you ALL=(ALL) NOPASSWD:ALL' | sudo tee
/etc/sudoers.d/you` is fine for a test bench.

The check. `spark check` has 40 rows, one per promise this machine
makes, and exits 0 when every row is ok. `--watch N` redraws every N
seconds. `--porcelain` prints one tab-separated row per line, for a
program. `--fresh` ignores cached answers, and `--fetch` asks origin
before judging the `git` row. `--selftest` proves every fixture-tested
row can flip. `--chaos` breaks a throwaway machine one known way at a
time and proves the right row says so and its remedy heals it.
`--report` prints a block safe to paste into an issue: the version,
the OS, the backend, the model stems and every row's status. Never a
value, a path or a name.

When something stops working:

1. `spark check` names the row and the remedy. Long output pages
   through `$PAGER`, plain when piped.
2. `./bootstrap.sh --dry-run` says what a rebuild would change.
3. `spark` says which server answers and which shells have the prompt
   line.
4. A stale server after a DHCP move shows as `moved` on the `serve`
   row: `spark serve off; spark serve on`. The `forge` row likewise:
   `spark forge off; spark forge on`.
5. `spark forge` says whether the page is up and at which address. One
   line per request lands in `~/.local/state/spark/forge.log`, never a
   body.
6. The `ember` row names the pair over budget, a file not downloaded,
   which `./bootstrap.sh` fetches, or a model not warm, which `spark
   serve` warms.
7. A GPU new servers cannot see makes the `gpu` row warn. On Linux the
   serving user must be in the `render` group. Log out of every
   session and in again.
8. `SPARK_DEBUG=1 spark ...` writes `~/.local/state/spark/debug.log`.
9. `the ledger does not open -- spark user login again`, or the same
   for the memory: the key this machine holds is not the one that
   sealed the file. A login by another token does that, or a byte that
   changed on disk. Nothing is written over it. `spark user login NAME`
   with your token puts the right key back.
10. For an issue: `spark check --report`.

## 8. What an attacker can and cannot do

The trust boundary is your LAN. spark serves plain HTTP to the
addresses you gave it and nothing else.

- On your LAN, an attacker can read the HTTP traffic, because there is
  no TLS. A cookie or token they capture works until it is rotated or
  its session is logged out. Logging out revokes the session on the
  server, not only in the browser. They cannot log in by guessing. A
  wrong token costs a second, and ten wrong tokens in a minute lock the
  address out for a minute. The login sleep is bounded, so a burst
  cannot pin the server's threads. The remedy is rotation: `spark user
  token --new` for your own token, which re-keys your sessions on the
  spot, and `spark forge token --new` for the admin's.
- With the disk, an attacker reads the admin's own store, because its
  key sits beside it so the machine can work, plus the soul, which is
  plain config. Every named user's store is ciphertext. The key is
  wrapped by that user's token, the admin holds no copy, and a lost
  token is lost history. There is no reset.
- With a stolen phone that was logged in, they hold that one user's
  chat and settings. Never another user's store, never the machine
  beyond it. `spark user token --new` from any logged-in session, or
  the page's log out, ends it.
- A command the model proposes runs only after your `Enter`. A command
  that can destroy data runs only after your `yes`. In `spark do
  --sandbox` it runs in a copy with no network and no view of your
  home, and nothing lands here until you have seen the diff and typed
  `yes`. `spark do --accept ID` applies a waiting run without showing
  it, for a script, and an app set to approve on its own accepts
  without you. Either way, a git hook or git config it wrote is never
  applied, and a link that leads out of the project is refused. The
  sandbox does not hide the whole machine: section 6 names what a step
  can still read.
- What spark depends on is one command. `spark ver --sbom` prints a
  software bill of materials as CycloneDX 1.5 JSON: every component
  this tree pins, with versions and sha256s. Every release carries it
  as `sbom.cdx.json`. The `pending` row of `spark check` counts the
  security upgrades your package manager holds back and warns while
  any waits.

What leaves is counted, never read. Every request's size and
destination ride its turn record, as a number and a host. `spark stats
--sends` prints them by destination and day for the last week. The
`sends` row of `spark check` warns the day any bytes went to a host
other than the server you chose.

## Appendix: how it fits together

```
your shell                    this machine                        the LAN
----------                    ------------                        -------
? words ---- prompt line ---> spark line --+
an app's key - spark-<app> -> spark edit --+
spark chat | do | explain -> spark <verb> -+-> the page's server :8081 --> another
                                           |   soul, memory, threads;    machine's
                                           |   /v1 and /api; the page    spark, a
                                           |                             browser,
                                           +-> llama-server :8080 <---- a program
                                               one model, or two:
                                               the pinned engine and a
                                               GGUF from models.env

get -> spark setup -> bootstrap.sh (apply) -> install.sh (links, renders)
                      the engine, the model, the token, the units, one rc
                      line; a spark app is its own repository (spark-<app>)

spark check   40 rows: every promise the machine makes, fixture-tested
spark update  the newest signed tag, or main on a developer clone; converge

what leaves the machine: pinned downloads in, your questions to the
server you chose, nothing else -- no telemetry, no account, one LAN address.
```
