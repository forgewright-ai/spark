# Installing spark

Section 1 sets up a bare machine. Section 2 installs spark. The rest is
for later.

## 1. A machine from zero

About 10 minutes, with `sudo` once. Most of it is one model download,
2.3 to 17 GB.

Debian:

1. Get the Debian 13 network installer from debian.org: `amd64` for a
   PC, `arm64` for an ARM board. Write it to a USB stick and boot it.
2. Leave the root password empty. That puts your user in the `sudo`
   group. Keep the SSH server and the standard system utilities.
3. Log in and run:

   ```sh
   sudo apt-get update && sudo apt-get install -y git curl python3 openssh-client
   ```

Arch:

1. Get the ISO from archlinux.org, write it to a USB stick and boot it.
2. Run `archinstall` and choose:
   - the minimal profile
   - a user marked superuser, for `sudo`
   - `systemd-boot` or GRUB
   - `git curl python openssh` as additional packages
   - copy the ISO's network configuration, to keep the Wi-Fi you
     joined with `iwctl`
   - one HTTPS mirror as a custom server, such as
     `https://geo.mirror.pkgbuild.com/$repo/os/$arch`
3. Reboot, log in and run `sudo pacman -Syu` once.

A plain HTTP mirror can fail with `invalid or corrupted database (PGP
signature)` when the router inspects traffic. Use HTTPS.

Void:

1. Get the live ISO from voidlinux.org: glibc, `x86_64`. spark does not
   run on the musl flavour. Write it to a USB stick and boot it.
2. Log in as `root`, password `voidlinux`, and run `void-installer`.
   Choose a user in the `wheel` group, GRUB and a network.
3. Reboot, log in and run:

   ```sh
   sudo xbps-install -Su
   sudo xbps-install -Sy git curl python3
   ```

macOS: run `xcode-select --install`. It brings `git`, `curl` and
`python3`.

Windows: in PowerShell, run `wsl --install -d Ubuntu-24.04` and reboot
when asked. Open Ubuntu and run Debian's step 3.

## 2. Install spark

1. Check what spark needs: `sudo`, `git`, `curl`, `python3` 3.9 or
   newer, and `ssh-keygen`.

   ```sh
   for c in sudo git curl python3 ssh-keygen; do
       command -v "$c" >/dev/null || echo "missing: $c"
   done
   python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' \
       || echo "python3 is older than 3.9"
   ```

   No output means you are ready. Otherwise install what is missing:

   - Debian 13 / Ubuntu 24.04 or newer: `sudo apt-get install -y git
     curl python3 openssh-client`. With no `sudo` at all, run `su -c
     'apt-get install -y sudo && usermod -aG sudo YOURNAME'`, then log
     in again.
   - Arch Linux: `sudo pacman -S --needed git curl python openssh`. If
     a package is not found, run `sudo pacman -Syu` first.
   - Void Linux: `sudo xbps-install -Sy git curl python3`. If xbps
     refuses, run `sudo xbps-install -Su` first.
   - macOS: `xcode-select --install`.

   Your login shell must be zsh, or bash 4 or newer. macOS's bash is
   3.2, so use zsh there.

2. Run:

   ```sh
   curl -fsSL https://github.com/forgewright-ai/spark/releases/latest/download/get | sh
   ```

   To read the script first:

   ```sh
   curl -fsSLO https://github.com/forgewright-ai/spark/releases/latest/download/get
   sh get
   ```

   Or by hand:

   ```sh
   git clone https://github.com/forgewright-ai/spark.git ~/.spark
   ~/.spark/bin/spark setup
   ```

3. When it finishes:

   ```sh
   exec $SHELL
   spark check
   ```

   `spark check` lists what needs you. It exits 0 when nothing fails.

`get` checks the tools above, clones spark to `~/.spark`, moves to the
newest signed release and runs `spark setup`. It never runs `sudo`.

`spark setup`:

1. Asks this machine's name, your name and the model. The model marked
   `*` is the one `auto` picks here.
2. Asks whether spark should read aloud in a clear voice, for low
   vision. The default is no.
3. On Linux, may ask for `sudo` once for a package: `libgomp1` on
   Debian, `libgomp` on Void, and the Vulkan drivers with a GPU.
4. Downloads the engine and the model, and checks both by sha256.
5. Writes a token, adds one line to your rc file and starts the
   services: the engine, the page's server and a check every 5 minutes.
   On Void it writes one root service with `sudo`, once.
6. Asks one test question and prints the speed.

You can run `spark setup` again at any time. `spark setup -h` lists its
options.

The rc line goes at the end of `~/.bashrc` or `~/.zshrc`. It loads the
prompt line and `TAB` completion. If setup prints a `todo rc` row, run
`chsh -s /bin/zsh`, then `spark setup` again. A bare zsh needs `autoload
-Uz compinit && compinit` in `~/.zshrc` for completion.

Setup asks before it adds the rc line. It lists the keys the line
adds to your shell and what each one replaces there. Answer `n` and
spark adds no line and no key. `spark keys on` adds them later.

A shell that is not interactive does not load the rc line. In a script,
a cron job or `ssh HOST 'spark ...'`, call `~/.local/bin/spark` in full.

## 3. Use it

Every command has `-h`. `docs/CHEATSHEET.txt` lists every command on
one page. `README.md` has things to try in your first hour.

The prompt line:

- Type `? words` or `words?` and press `Enter`. A command lands in your
  line, with a hint above it. Press `Enter` again to run it.
- A command that deletes is marked `!`.
- `?? words` follows up on the last answer.
- `Esc s` asks about the line you are on.
- After a command fails, `Esc s` on the empty line explains it. Press
  it again for the fix.
- `Esc r` finds a past command from your own words. Press it again for
  the next match.
- `Esc k` moves the row spark writes in, for a prompt of two lines.
  `spark height N` sets it, 1 to 5.
- `spark off` turns the prompt line off. `spark on` turns it back on.
- `spark keys` lists the keys spark added, and moves them.
- `cmd 2>&1 | explain` says what went wrong, and the fix.
- `spark <words>` answers in the terminal. `spark @FILE words` asks
  about a file.

The keys spark adds to your shell, each with a name:

| name | key | what it does |
|---|---|---|
| `ask` | `Esc s` | asks about the line you are on |
| `recall` | `Esc r` | finds a past command |
| `height` | `Esc k` | moves the row spark writes in |
| `listen` | `Esc v` | listens, with the voice on |
| `stop` | `Esc x` | stops the speaking, with the voice on |

A lone `Esc` waits up to 1 second for the next key. `Enter`, `Ctrl-U`,
`Ctrl-L` and a paste keep what they did, and they do not move.

- `spark keys` lists each key and what it replaced in your shell.
- `spark keys ask Esc a` moves a key. `Alt-a` is the same key, and
  `Ctrl-g` works too.
- `spark keys ask none` leaves that key to your shell.
- `spark keys reset` brings back the keys in the table.
- `spark keys off` takes the line out of your rc file. `spark update`
  then leaves the file alone. The prompt line and `TAB` completion go
  with it.
- `spark keys on` adds the line again.
- `SPARK_OFF=1` in the environment starts one shell without the keys.

A change shows in the next shell you open. Your choice of keys is kept
in `~/.config/spark/keys.env`.

`spark chat` talks with the model. It goes on with your newest thread.
`Esc` on an empty line, `/q` or `Ctrl-D` ends it. `Ctrl-C` cancels a
reply. The commands:

| command | what it does |
|---|---|
| `/help` | lists the commands |
| `/new` | starts a fresh thread |
| `/resume [N]` | an older thread: bare lists the newest 5 |
| `/clear` | clears the screen |
| `/keep` | keeps this thread past `SPARK_HISTORY`. `/keep off` undoes it |
| `/last` | the last turn and its speed |
| `/model` | which model answers |
| `/reveal [N\|auto\|off]` | how fast replies appear |
| `/copy [N]` | a reply to the clipboard |
| `/save [FILE]` | the thread as a text file |
| `/read @FILE [question]` | an answer that quotes the file |
| `/do [--sandbox] GOAL` | a task, as `spark do` runs it |
| `/aloud` | reads the replies aloud, or stops |
| `/again` | the last reply again |
| `/q` | ends the chat |

`spark do <words>` does a task, one command at a time. At each step,
`Enter` runs it, `e` edits it, `s` skips it, `q` quits and `r` shows a
long step again. A step that
can destroy data runs only when you type `yes`. A run is 8 steps at
most.

`spark do --sandbox <words>` runs the steps in a copy of this
directory, with no network. At the end it shows the changes, and you
type `yes` to apply them. `spark do --review` lists the runs that wait.
Section 6 says what a step can still read.

These work on a text on stdin:

- `spark ask < plan.md`: up to 3 questions the text does not answer.
- `spark read <words> < page.txt`: an answer where every line quotes
  the text.
- `spark drill < notes.md`: practice questions from the text.
- `tail -f app.log | spark watch "a 500 appears"`: one line when a line
  matches.
- `spark edit`: for editors. `README.md` lists the apps that use it.

`spark soul edit` changes who spark is, in 4000 characters at most.
`spark soul reset` goes back to the default. `spark memory add <words>`
keeps a fact, up to 40. The soul and the facts go with every question.

`spark history` lists past threads. `spark clear --history` forgets
them, except the ones you kept. `spark user claim` moves chats from an
older spark into your account.

`spark awaken` gives this machine a personality and a look. Nothing
changes until you run it. It asks for a temperament: plain, warm,
playful or terse. The model writes a personality and picks a face.
Where a player is, it offers a voice: keep it, hear another or have
none. `Ctrl-C` leaves the machine as it was.

After awaken, spark has a face and uses a few colours. The face waits
while a reply is on its way, and what moves beside it says what spark
is doing. It opens each reply and ends pleased, puzzled or alarmed. At
your prompt it shows on the line spark writes, and it rests above an
empty prompt. `Enter` erases the resting face.

In zsh the resting face blinks, falls asleep after 5 minutes without a
key and wakes on the next key. In bash it stays still. It shows only
where your prompt starts with a blank line and the height matches the
prompt's lines: press `Esc k`, or run `spark height N`. `Ctrl-C` at a
prompt can leave one face in the scrollback.

`spark look on|off|auto` turns the face and the colours on or off.
`auto` draws only at a terminal, and colour only without `NO_COLOR`.
A pipe never sees it. Your own colours win: export `SPARK_ACCENT_SGR`,
`SPARK_MUTED_SGR`, `SPARK_WARN_SGR`, `SPARK_OK_SGR` or
`SPARK_TROUBLE_SGR`, as SGR codes such as `1;94`.

The voice. `spark voice` reads aloud and listens, on this machine.
`SPARK_VOICE` has 3 modes:

- `off`: silent. The default.
- `clear`: a plain voice for low vision. It reads commands with their
  symbols, the hints, the steps of `spark do` and the chat's replies.
- `on`: the voice `spark awaken` picked for this machine, plain, with
  no effect. It reads the chat's replies.

`Esc v` listens. A pause ends it, and your words land in the line.
Nothing runs until you press `Enter`. `Esc x` stops the speaking. After
`spark voice on` or `clear`, open a new shell for the keys. A spoken
yes never confirms a step.

While a screen reader runs, clear mode stays silent. `spark voice
clear --anyway` speaks beside it.

The voice engine downloads only when you turn the voice on, and its
size is said first:

| part | what | size |
|---|---|---|
| the runtime | sherpa-onnx v1.13.8 | 28 MB on Linux, 44 MB on macOS |
| the mouth | Kokoro-82M v1.0 | 350 MB |
| the ears | Whisper base | 208 MB |
| the end of a question | Silero VAD | under 1 MB |

That is 586 MB on Linux and 602 MB on macOS, in
`~/.local/share/spark/voice`. `spark voice off --remove` deletes it.
`CREDITS.md` names each licence.

macOS asks once for the microphone: allow it. On Linux, a headset on
the second card needs `SPARK_VOICE_DEVICE=plughw:1,0` in `spark.env`.
`aplay -l` lists the cards. A recording is deleted once it is read.

## 4. Models

`models.env` lists 11 models, each with its license. `spark model`
shows them with their size, the memory they need, and whether they fit
here.

The first four are the prompt line's ladder:

| name | file | RAM | for |
|---|---|---|---|
| `gemma4-26b-a4b` | 15.9 GB | 19 GB | a machine with 32 GB |
| `gemma4-e4b` | 5.0 GB | 8 GB | the standard, with a GPU or without |
| `qwen3-4b` | 2.3 GB | 5 GB | a budget of 5 to 7 GB |
| `qwen3-5-2b` | 1.3 GB | 3 GB | a small machine |

The others are `qwen3-5-4b`, `qwen3-8b`, `granite-4-2-8b`,
`qwen3-14b`, `qwen3-30b-a3b`, `gemma4-e2b` and `qwen3-coder-30b-a3b`.
All are under Apache-2.0.

`auto` takes the first tested model that fits the budget, 60 percent of
RAM plus GPU memory. It skips a file over the speed cap: 3 GB on `cpu`,
6 GB on `vulkan`, 20 GB on `metal`. A model with 4B or fewer working
parameters, such as `gemma4-26b-a4b`, is not held to the cap.

- `spark model NAME` downloads a model, checks it and serves it.
- `spark model auto` goes back to the rule above.
- `spark model budget N` sets the budget, 10 to 95 percent.
- `spark model --chat NAME` adds a second, larger model for chat. The
  prompt line keeps the small one.
- `spark model add URL --license "NAME URL"` adds your own. A file not
  on huggingface.co also needs `--sha256 HEX`.
- `spark model verify` checks every downloaded file again.
- `spark model rm NAME` deletes a file not in use.

A model under a licence that is not open asks before it downloads.

`spark bench` measures the speed. `spark bench tune` tries settings,
and `spark bench tune apply` keeps the fastest. `spark stats` shows
what real turns measured.

The prompt line checks each command against the manuals on this
machine. `SPARK_KNOWLEDGE=off` in `spark.env` turns that off.

## 5. Other machines and your phone

This machine can serve its model to other machines and to a browser,
at `http://<host>:8081`. The traffic is plain HTTP. Anyone on your
network can read it.

- `spark serve on` starts the engine and the page's server. They come
  back after a restart. `spark serve off` stops them.
- `spark serve` shows what runs and where.
- `spark serve boot on` keeps them up from boot, with nobody logged in.

Another machine of yours:

1. Here: `spark user add NAME`. The token is shown once.
2. There: `spark client URL`, with the URL from `spark serve --login`
   here. Then `spark user login NAME` with that token.
3. `spark client` there says whether this machine answers.

A client runs no model of its own. `spark client off` gives it one
again.

A browser or a phone:

1. `spark serve --login` prints the page's address, the admin token and
   a QR code. Scan the QR with a phone and the page signs in.
2. Or type a token. A user's token opens their own chat. The admin
   token opens the whole machine.
3. On iOS, add the page to the home screen.

The QR holds the token. Show it only to the person it is for.

Another OS user on this Linux machine: run `spark serve share on` and
`sudo gpasswd -a NAME spark`. That user logs in again and runs the
install line. They share one engine and keep their own soul and memory.

A program, a script or a CI job gets its own user and token. The API
has the OpenAI shape:

```sh
curl -sN http://<host>:8081/v1/chat/completions \
  -H "Authorization: Bearer $YOUR_SPARK_USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"hello"}],"stream":true}'
```

Users:

- `spark user list` lists them.
- `spark user remove NAME` deletes a user and their data.
- `spark user token --new` gives you a new token. Other logins end.
- `spark serve --login --new` gives the admin a new token.
- `spark serve --audit` lists what the admin did.

Each user's threads and memory are encrypted. Only their token opens
them, and a lost token cannot be recovered. This machine's own login
keeps its key next to its store. Encrypt the disk to protect it.

## 6. Per-OS notes

macOS:

- macOS asks once whether `python3` may find devices on the local
  network. Allow it, or the page answers only this machine.
- Services: `launchctl print gui/$UID/spark.serve`, and `.forge` and
  `.check` likewise. `launchctl kickstart -k gui/$UID/spark.serve`
  restarts one.
- `spark serve boot on` moves the services to `/Library/LaunchDaemons`
  and keeps the machine awake with `pmset`. Restart and stop then need
  `sudo launchctl`, and spark prints the line.
- `spark do --sandbox` uses Apple's `sandbox-exec`. A step has no
  network, cannot write outside the copy and cannot read your home. It
  can still read the rest of the system, such as `/Applications` and
  `/etc`. Read the changes before you type `yes`.

Linux:

- With a GPU, the engine is the Vulkan build. `SITE_AI_BUILD=cpu` or
  `vulkan` chooses one.
- With no engine pinned for your CPU, spark uses a `llama-server` on
  your `PATH`. Or set `SPARK_ENGINE_DIR` to your own build.
- An integrated GPU gets its memory from the BIOS. If the `gpu` row
  says the model does not fit, raise it there: 8 GB for a 4B to 8B
  model.
- On a Vulkan build you join the `render` group. Log out of every
  session and in again.
- `spark do --sandbox` needs bubblewrap 0.11 or newer, as in Debian 13
  and Arch. Ubuntu 24.04 has 0.9, so the sandbox does not work there. A
  step has no network, and the homes and `/tmp` are hidden. The rest of
  the system stays readable.
- Services: `systemctl --user status spark-serve spark-forge
  spark-check.timer` and `journalctl --user -u spark-serve -n 50`.
- `spark serve boot on` runs the services without a login, turns off
  sleep and ignores the lid. `off` gives back sleep and the lid.

Arch:

- Packages come through `pacman -S --needed`. If a package is not
  found, run `sudo pacman -Syu` first. Never run `pacman -Sy` alone.

Void:

- Only the glibc flavour runs spark.
- Services are runit's. spark writes `/etc/sv/runsvdir-USER` once, with
  `sudo`, so they run from boot. `sv status ~/.config/spark/sv/*` shows
  them. Logs are in `~/.local/state/spark/log/NAME/current`.
- `spark serve boot on` changes nothing on Void: the services already
  run from boot.
- Void has no `hostname` command. With `SITE_SET_HOSTNAME=yes`, spark
  writes `/etc/hostname`.

Windows, as Ubuntu 24.04 on WSL 2:

- The engine is the CPU build.
- If the `services` row reads `na`, put `[boot] systemd=true` in
  `/etc/wsl.conf`. Run `wsl --shutdown` in PowerShell, reopen Ubuntu,
  then run `spark update`.
- WSL 2 stops with its last window, so it cannot serve your network.
  `spark serve boot on` refuses.

## 7. Keep it

Update:

```sh
spark update
```

It moves to the newest signed release, sets it up and runs `spark
check`. `spark update --dry-run` says what it would do.

A release is signed. `spark update` moves only forward, to a release
signed by a key this install already trusts. It skips a tag that fails,
and says why. A first install checks against the key inside `get`. A
clone on `main`, or one made with `SPARK_REF`, is not checked.

Uninstall:

```sh
spark uninstall
```

It shows the plan and asks you to type `yes`. Everything spark made
goes. Your soul, your memory and the users' stores stay, and `--purge`
takes them too. `--dry-run` shows the plan only. At a terminal it asks
whether to remove the packages it installed. spark prints how to undo
what it cannot remove, such as a hostname it set.

The settings. `~/.config/spark/site.env` holds the machine's choices.
Each has a command:

| key | what | default |
|---|---|---|
| `SITE_NAME` | this machine's name | short hostname |
| `SITE_USER` | your name | your login |
| `SITE_SET_HOSTNAME` | `yes`: the hostname follows `SITE_NAME` | `no` |
| `SITE_AI_MODEL` | `auto`, `none` or a name: `spark model NAME` | `auto` |
| `SITE_EMBER_MODEL` | the chat model: `spark model --chat NAME` | `none` |
| `SITE_AI_BUDGET` | percent of memory for models: `spark model budget N` | `60` |
| `SITE_AI_BUILD` | `auto`, `cpu` or `vulkan` (Linux) | `auto` |
| `SITE_PEER_AI_URL` | another machine's URL: `spark client URL` | unset |
| `SITE_PEER_SSH` | an ssh target `spark check` should reach | unset |
| `SITE_HEADLESS` | `yes`: up from boot: `spark serve boot on` | `no` |
| `SITE_SHARE` | `yes`: one engine for every user: `spark serve share on` | `no` |
| `SITE_KEYS` | `off`: no rc line and no keys: `spark keys off` | `on` |

`~/.config/spark/spark.env` holds the rest. `spark.env.example` lists
every key. The common ones:

| key | what | default |
|---|---|---|
| `SPARK_HISTORY` | days a thread is kept. `off` keeps none | `30` |
| `SPARK_MEMORY` | send the facts: `spark memory on\|off` | `on` |
| `SPARK_REVEAL` | how fast replies appear: `spark reveal N\|auto\|off` | `off` |
| `SPARK_LOOK` | the look: `spark look on\|off\|auto` | `off`, `auto` after awaken |
| `SPARK_HEIGHT` | the row spark writes in: `spark height N` | `1` |
| `SPARK_VOICE` | `off`, `clear` or `on`: `spark voice` | `off` |
| `SPARK_VOICE_RATE` | the voice's speed, 50 to 300: `spark voice rate N` | `100` |
| `SPARK_VOICE_DEVICE` | the sound card on Linux, such as `plughw:1,0` | ALSA's default |
| `SPARK_KNOWLEDGE` | `off`: the prompt line skips the manuals | `on` |

Root. spark uses `sudo` for the package manager, the hostname, the
`render` group, Void's one service, `spark serve boot on` and `spark
serve share on`.
`~/.spark/bootstrap.sh --dry-run` lists what it would do, without
`sudo`.

Keep passwordless `sudo` off a machine that serves your network. The
admin token can run any command here. With passwordless `sudo`, that
means root.

The check. `spark check` has 39 rows and exits 0 when no row fails.
Bare, it shows only the rows that need you, each with its fix. `spark
check --all` shows every row. `spark check --report` prints a block for
an issue, with no names or paths.

When something stops working:

1. `spark check` names the row and the fix.
2. `spark` says which model answers. `spark status` says more.
3. After the address changes: `spark serve off; spark serve on`.
4. `SPARK_DEBUG=1 spark ...` writes `~/.local/state/spark/debug.log`.
5. The page's server logs each request in
   `~/.local/state/spark/forge.log`. A command run from the page is
   logged by its sha256 and its length, never its text.
6. `the ledger does not open`: log in with your own token, `spark user
   login NAME`.
7. spark's line sits on your prompt: press `Esc k`, or run `spark
   height 2`. The resting face waits until the height matches your
   prompt's lines. A prompt with no blank line above it shows none.
8. `1 record in thread ID could not be read -- skipped`: part of that
   thread is damaged on disk. The rest of it reads, and new turns land.

## 8. What an attacker can and cannot do

spark serves plain HTTP on one address of your network. Your network
is the trust boundary.

- On your network, anyone can read the traffic, tokens included. A
  captured token works until it is rotated. Rotate with `spark user
  token --new`, or `spark serve --login --new` for the admin.
- Guessing a token is slow: 10 wrong tokens in a minute lock that
  address out for a minute.
- The admin token can run any command on this machine. With
  passwordless `sudo`, that is root.
- With the disk, an attacker reads this machine's own store, because
  its key sits beside it. Each named user's store stays encrypted.
  Encrypt the disk.
- With a stolen phone that was logged in, they hold that user's chat.
  `spark user token --new` ends it.
- At the prompt and in `spark do`, a command runs only after your
  `Enter`. A command that can destroy data needs `yes` typed.
- An app that drives `spark do --porcelain` can approve steps for you.
  So can `spark do --accept`.
- Outside the sandbox, such an app cannot run a step that sends data
  off this machine, such as `scp FILE host:`.
- `spark do --sandbox` runs steps in a copy with no network. A step can
  still read most of the system: see section 6.
- `spark read`, `spark do`, `recall` (`Esc r`) and `spark edit ?
  --source` replace secrets with `[held]`. `explain`, `@FILE` and
  `spark chat` send text as it is.
- No log keeps the text of a command run from the page.
- A reply's terminal escapes, such as a clipboard write, never reach
  your screen.
- A first install checks against the key inside `get`. Updates check
  against the key already installed. A clone on `main` is not checked.
- The microphone opens only on `Esc v` or `spark voice listen`.

`spark ver --sbom` lists what spark depends on. `spark ver --credits`
names who made spark and what it uses. `spark stats --sends` shows
what left this machine, by destination and day.

## How it fits together

- The engine, llama-server on port 8080, runs the model.
- The page's server, on port 8081, keeps the soul, the memory and the
  threads. It serves the page, the API and other machines.
- `spark` at your prompt talks to both.
- `spark check` runs every 5 minutes.
