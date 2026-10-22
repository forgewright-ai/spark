# Installing spark

Start with the signed installer on a computer you already use. It does
not reinstall the OS or erase a disk. Section 2 has the steps. Section
1 is optional OS provisioning for a bare machine; its disk choices can
erase existing data. The rest is for later.

## Before you start

- Supported: Debian/Ubuntu, Arch, Void (glibc, not musl), Fedora and
  openSUSE Tumbleweed Linux, macOS, or Windows with WSL 2 and Ubuntu.
  Atomic Linux variants such as Fedora Silverblue and openSUSE Aeon
  are not supported. Use x86-64 or ARM64 for the supplied engine.
- Use zsh or bash 4 or newer for the prompt line. macOS's system bash
  is 3.2, so use zsh there. Have `sudo`, `git`, `curl`, Python 3.9 or
  newer and `ssh-keygen`. Section 2 checks these before installation.
- A CPU can run a model without a GPU. Listed model files range from
  1.3 to 17.4 GB and need a 3 to 21 GB model memory budget. The
  budget defaults to 60 percent of RAM plus GPU memory; it is not a
  whole-computer RAM minimum. For example, the 1.3 GB file needs a
  3 GB model budget. Section 4 lists the choices.
- Leave more free disk space than the model file for the engine and
  setup. spark downloads its code and engine from GitHub and model
  weights from Hugging Face. Setup time depends on your connection,
  disk and CPU; it is not a fixed ten minutes.

spark runs a model here by default, with no telemetry. If you
configure a model server elsewhere, it receives the text you send;
README.md says what each command sends, under What leaves this
machine. Setup starts the model engine, a page server on one LAN
address, and a health check. The page needs a token but uses plain
HTTP until you configure https (section 5, HTTPS for the page).
Anyone on that network can read plain HTTP. Conversations are kept
locally for 30 days by default; `SPARK_HISTORY=off` keeps none.
Section 5 covers sharing. Section 8, the threat model, covers access
and storage.

## Install on an existing computer

Use the signed-release installer in a terminal on the supported
computer you already use:

```sh
curl -fsSL https://github.com/forgewright-ai/spark/releases/latest/download/get | sh
```

It checks the prerequisites and asks before setup changes anything.
Section 2 has prerequisite fixes, a way to read the script first, and
the first check.

## 1. A machine from zero

Optional: only follow this section if you intend to install an OS on a
bare machine. Writing an installer USB stick or choosing a target disk
can erase data. On a computer you already use, skip to section 2.

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

Fedora:

1. Get the Fedora Everything network installer from fedoraproject.org,
   `x86_64`. It is the only image with a minimal system. Write it to a
   USB stick and boot it.
2. On a machine with Wi-Fi only, use the graphical installer. The text
   installer cannot join a WPA network.
3. Leave Installation Source on the closest mirror: the image holds no
   packages. `Failed to download metadata` means the network is not up
   yet.
4. In Software Selection choose `Fedora Custom Operating System`. The
   text installer calls it `Minimal Install`.
5. In Installation Destination pick the disk, then Automatic and Done.
   Then choose Reclaim space, Delete all and Reclaim.
6. Make your user an administrator, for `sudo`.
7. Reboot, log in and run:

   ```sh
   sudo dnf install -y git openssh-clients python3 curl
   ```

Warning: a minimal Fedora installed over Wi-Fi boots with no Wi-Fi. It
lacks the drivers, in `kernel-modules`, and `NetworkManager-wifi` and
`wpa_supplicant`. Add them in Software Selection if you can. Otherwise
plug in a cable for the first boot, then run:

```sh
sudo dnf install -y NetworkManager-wifi wpa_supplicant kernel-modules
sudo reboot
```

A wired machine needs none of this.

openSUSE:

1. Get the openSUSE Tumbleweed network installer from
   get.opensuse.org. Write it to a USB stick and boot it.
2. Choose a minimal or server system role, and a user who can use
   `sudo`.
3. Reboot, log in and run:

   ```sh
   sudo zypper install -y git openssh-clients python3 curl
   ```

These openSUSE steps were not run on a real machine.

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
   - Fedora: `sudo dnf install -y git openssh-clients python3 curl`.
   - openSUSE Tumbleweed:
     `sudo zypper install -y git openssh-clients python3 curl`.
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

   Developer-only alternative: the following clone follows `main`,
   without signed-release verification. Use the signed installer above
   for a normal installation.

   ```sh
   git clone https://github.com/forgewright-ai/spark.git ~/.spark
   ~/.spark/bin/spark setup
   ```

3. When it finishes:

   ```sh
   exec $SHELL
   spark check
   ```

   `spark check` lists what needs you. A healthy check prints the
   totals line alone. It exits 0 when nothing fails.

`get` checks the tools above, clones spark to `~/.spark`, moves to the
newest signed release and runs `spark setup`. It never runs `sudo`.

`get` prints a short notice first: the license, no warranty, and that
a model can be wrong, so what you run or accept is at your own risk.
At a terminal `spark setup` then asks `go on? yes/NO:` before it
changes anything. Run by itself, `spark setup` shows the notice once,
then asks. `spark ver --credits` shows the notice again.

`spark setup`:

1. Asks this machine's name, your name and the model. The model marked
   `*` is the one `auto` picks here.
2. Asks whether spark should read aloud in a clear voice, for low
   vision. The default is no.
3. On Linux, may ask for `sudo` once for a package: `libgomp1` on
   Debian and openSUSE, `libgomp` on Void and Fedora, and the Vulkan
   drivers with a GPU.
4. Downloads the engine and the model, and checks both by sha256.
5. Writes a token, adds one line to your rc file and starts the
   services: the engine, the page's server and a check every 5 minutes.
   On Void it writes one root service with `sudo`, once.
6. Asks one test question and prints the speed.

You can run `spark setup` again at any time. `spark setup -h` lists its
options.

If a download is interrupted or fails its sha256 check, run the signed
installer command again. It retries the download and checks the full
file before keeping it; it does not resume a partial file. Check free
disk space if it fails again. You do not need to wipe the installation.

The rc line goes at the end of `~/.bashrc` or `~/.zshrc`. It loads the
prompt line and `TAB` completion. If setup prints a `todo rc` row, run
`chsh -s /bin/zsh`, then `spark setup` again. A bare zsh needs `autoload
-Uz compinit && compinit` in `~/.zshrc` for completion.

The rc line is always added. Setup asks only about the keys. It lists
the keys spark can add to your shell and what each one replaces there.
Answer `n` and spark binds none of them. `? words`, `TAB` completion
and the row above your prompt work the same.

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
- `spark off` turns the prompt line off. `spark on` turns it back on.
- `cmd 2>&1 | explain` says what went wrong, and the fix.
- `spark <words>` answers in the terminal. `spark @FILE words` asks
  about a file.

The keys spark adds to your shell, each with a name:

| name | key | what it does |
|---|---|---|
| `ask` | `Esc s` | asks about the current line; after a failure, press it on an empty line for the reason, then again for the fix |
| `recall` | `Esc r` | finds a past command from your words; press it again for the next match |
| `height` | `Esc k` | moves spark's row for a two-line prompt; `spark height N` sets it from 1 to 5 |
| `listen` | `Esc v` | listens, with the voice on |
| `stop` | `Esc x` | stops the speaking, with the voice on |

After `Esc`, your shell waits up to 1 second for the next key. `Enter`,
`Ctrl-U`, `Ctrl-L` and paste stay as they are.

- `spark keys` lists each key and what it replaced in your shell.
- `spark keys ask Esc a` moves a key. `Alt-a` is the same key, and
  `Ctrl-g` works too.
- `spark keys ask none` leaves that key to your shell.
- `spark keys reset` brings back the keys in the table.
- `spark keys off` binds none of the 5 keys. Your shell keeps its own
  keys there, and its own wait after `Esc`.
- With the keys off, the rest works as before: `? words`, `TAB`
  completion and the row above your prompt. The rc line stays.
- `spark keys on` binds them again.
- With the keys off, a key you move is kept for when they are on.
- `SPARK_OFF=1` in the environment starts one shell without the prompt
  line.

A change shows in the next shell you open. Your choice of keys is kept
in `~/.config/spark/keys.env`, and `KEYS=off` there turns them off.

`spark chat` talks with the model. It goes on with your newest thread.
`Esc` on an empty line, `/q` or `Ctrl-D` ends it. `Ctrl-C` cancels a
reply. If a reply times out after words arrive, history keeps those
words as an incomplete answer. The next message continues that thread.
The commands:

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

If applying fails, the copy stays. A failure while preparing the files
applies nothing. A later failure can leave some changes applied.
Fix the cause, then use `spark do --review ID` to review what remains.
Files changed here still cause a conflict, even on a retry. A partly
deleted directory may need manual recovery. Keep the copy until that
work is safe; `spark do --discard ID` removes it.

These work on a text on stdin:

- `spark ask < plan.md`: up to 3 questions the text does not answer.
- `spark read <words> < page.txt`: an answer where every line quotes
  the text.
- `spark drill < notes.md`: practice questions from the text.
- `tail -f app.log | spark watch "a 500 appears"`: one line when a line
  matches.
- `spark edit`: for editors. `README.md` lists the apps that use it.

MCP servers. An MCP server is a program that offers tools to an AI,
such as the sound or the windows of a desktop. spark starts only the
servers on its list, one line each in `~/.config/spark/mcp.env`:

```sh
spark mcp add notes /opt/notes/bin/notes-mcp
spark mcp                           # the servers and their tools
spark mcp call notes add_note text=milk
```

- `spark mcp NAME` shows one server's tools and their arguments.
- `spark mcp call NAME TOOL KEY=VALUE` runs one tool. A value is typed
  as the tool takes it: a number, `yes` or `no`, or text. A password is
  asked for, never typed on the line.
- A tool that changes something asks you to type `yes`, unless its
  server is trusted and the tool says it destroys nothing. spark's own
  programs are trusted, and `spark mcp` says which server is. `spark
  mcp trust NAME on` trusts another, `off` takes it back.
- The prompt line, `spark do` and `/do` in a chat know the tools
  `spark mcp` listed last. A tool step is a `spark mcp call` line: you
  read it before `Enter`, as any other step. Inside `--sandbox` a tool
  step does not run, because a tool acts outside the copy.
- `spark mcp read NAME` lists a server's resources, and `spark mcp read
  NAME URI --watch` shows one again each time it changes.
- `spark mcp rm NAME` takes a server off the list.
- `spark steps <words> < tools.json` turns your words into tool calls,
  from an MCP tools list on stdin. It prints them as JSON and runs
  nothing. A desktop's dialog is its first user.

A server runs with no shell, in your home, with a short list of
environment variables. It talks to spark over its stdin and stdout
alone, never the network. A tool's description never goes to the model:
only its name, its arguments and its title. Each call is a record in
the audit trail, its names and a digest of its arguments: `spark serve
--audit`.

`spark soul edit` changes who spark is, in 4000 characters at most.
`spark soul reset` goes back to the default. `spark memory add <words>`
remembers a fact, up to 40. The soul and the facts go with every
question.

`spark history` lists past threads. `spark clear --history` forgets
them, except the ones you kept. It also forgets what `spark check
--history` shows. `spark user claim` moves chats from an
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
prompt's lines: press `Esc k`, or run `spark height N`. In bash,
`Ctrl-C` at a prompt can leave one face in the scrollback. In zsh the
next prompt erases it.

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

When the model gives no answer at the prompt, spark asks once more by
itself. `spark stats` counts the questions that still got none. The
`answers` row of `spark check` warns when 2 or more questions got none
in 7 days, and they are 2 % of your questions or more. A larger model
answers more often: `spark model list` shows them.

## 5. Other machines and your phone

This machine can serve its model to other machines and to a browser,
at `http://<host>:8081`. The traffic is plain HTTP unless you give the
page a certificate (below). Anyone on your network can read plain
HTTP.

- `spark serve on` starts the engine and the page's server. They come
  back after a restart. `spark serve off` stops them.
- `spark serve` shows what runs and where.
- `spark serve boot on` makes this an always-on, headless box: both
  stay up from boot, with nobody logged in.

Fedora and openSUSE turn a firewall on, firewalld, and spark does not
change it. Other machines reach this one only after you open the port:

```sh
sudo firewall-cmd --permanent --add-port=8081/tcp
sudo firewall-cmd --reload
```

With a cable and Wi-Fi both connected, spark serves at one address: the
one your default route uses. `spark serve` prints it.

Another machine of yours:

1. Here: `spark user add NAME`. The token is shown once.
2. There: `spark client URL`, with the URL from `spark serve --login`
   here. Then `spark user login NAME` with that token.
3. `spark client` there says whether this machine answers.

A client runs no model of its own. `spark client off` gives it one
again.

Your own llama-server:

1. `spark client http://127.0.0.1:8080` uses a `llama-server` you
   already run, at that address. On a new install, `spark setup --engine
   URL` does the same.
2. When the server asks for a key, put the key in a file. Then run
   `spark client URL --key-file FILE`.
3. `spark client` says whether the server answers.

spark uses the one model the server has loaded. A server that loads
more than one model is not supported. spark downloads no model for it,
and never starts or stops it. Your threads and memory stay on this
machine, encrypted. `spark client off` goes back to a model spark runs
here. Stop your server first when it holds port 8080, or set
`SPARK_PORT`. Ollama is not supported yet.

`spark setup --engine URL` needs the server to answer. It refuses the
address of a spark machine: `spark client URL` is the command for that
one. spark cannot tell a bare `llama-server` on another spark machine
from your own, so it treats both the same way.

A browser or a phone:

Use a trusted network for plain HTTP, or set up HTTPS for the page,
below, before sharing. An ordinary
user's token opens only that user's chat and store. The admin token
can run commands here; with passwordless `sudo`, it can run as root.
The login QR holds that admin token. Keep it private and never put a
token or login QR screenshot in a public issue.

1. `spark serve --login` prints the page's address, the admin token and
   a QR code. Scan the QR with a phone and the page signs in.
2. Or type a token. A user's token opens their own chat. The admin
   token opens the whole machine.
3. On iOS, add the page to the home screen.

For someone else, create an ordinary user with `spark user add NAME`
and give that person only their own token. On the page, the admin adds
a user under settings: the token shows once, with a QR for that
person's phone.

### HTTPS for the page

The page is plain HTTP until you give it a certificate. Then it serves
https on the same port, and the login link, the QR and `spark client
URL` follow.

1. A pair you were given, from your office, certbot, step or `tailscale
   cert`: `spark serve https CERT KEY`. When the certificate carries a
   name, add `--name HOST`, and the links say it. A browser that trusts
   the issuer needs nothing. A renewed pair is read within a minute,
   with no restart.
2. A pair of this machine's own, for home: `spark serve https own`.
   spark mints a root for this machine's names and a certificate under
   it, and renews the certificate itself. Each phone installs the root
   once: `spark serve --login` shows its QR first, then the login's.
   On iOS, after the profile, turn the root on under General, About,
   Certificate Trust Settings. Android says the network may be
   monitored: that is the root. The root signs for this machine's
   names and no other.
3. `spark serve https` only shows certificate status and who must trust
   it; it does not turn on HTTPS. Follow step 1 or 2 to configure it.
   `spark serve https off` is plain HTTP again.

Over plain HTTP an admin action (a verb run, the do console, the soul,
the check) answers this machine and its own networks alone. A request
routed in from farther is refused and told to serve https. A reverse
proxy in front of the page is the peer: spark reads no forwarded
header, so put the proxy on this network or serve https.

Another spark that does not trust the issuer pins the certificate:
`spark client https://HOST:8081 --pin FINGERPRINT`, with the
fingerprint `spark serve --login` prints there. `--ca FILE` trusts the
issuer instead. On macOS, Python reads no root from the keychain, so an
office root needs `--ca FILE` even when Safari trusts it. On Fedora and
openSUSE, open 8082 too in own mode: the root is served there.

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

Fedora:

- Packages come through `dnf install -y`. `sudo dnf upgrade` upgrades
  the system.
- CI proves the install line in a Fedora container. On one real
  machine, a minimal Fedora 44 with SELinux enforcing ran the install
  line, the engine on its GPU and the services.
- Fedora Silverblue, Kinoite and the other atomic systems are not
  supported in this version.
- Rocky Linux and AlmaLinux are treated as Fedora. They are not
  proven, and their older system library may not run the engine.
- The firewall is on: see section 5.

openSUSE:

- Tumbleweed and Leap are one family. Packages come through `zypper
  install -y`. On Tumbleweed, `sudo zypper dup` upgrades the system.
- CI proves the install line in a Tumbleweed container. On one real
  machine, a minimal Tumbleweed ran the install line, the engine on its
  GPU and the services.
- MicroOS, Aeon and the other atomic systems are not supported in this
  version.
- The firewall is on: see section 5.

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
`~/.config/spark/spark.env` holds the runtime settings. Non-empty
environment values win over `spark.env`, then `site.env`, then defaults.
Within each file, the first non-empty value of a key wins.
Empty values, including `""`, leave the next source in use.

These files are data, never shell code. Write `KEY=value`, with no
space before `=`. Keys start with an uppercase letter or underscore;
digits may follow. Blank lines and whole-line `#` comments are skipped.
One pair of surrounding double quotes is removed. Other quotes,
backslashes, spaces and inline `#` stay literal. A leading `~` or `~/`
then expands to your home. Unix and Windows line endings both work.
A bad line refuses the file, even when another value would win.

Older Python readers kept the last non-empty duplicate; now both
readers keep the first. Keep one line per key to avoid ambiguity.
Keys starting with a digit are now refused by both readers.

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

`~/.config/spark/spark.env` holds the rest. `spark.env.example` lists
every key. The common ones:

| key | what | default |
|---|---|---|
| `SPARK_HISTORY` | days threads and check changes are kept, or `off` | `30` |
| `SPARK_MEMORY` | send the facts: `spark memory on\|off` | `on` |
| `SPARK_REVEAL` | how fast replies appear: `spark reveal N\|auto\|off` | `off` |
| `SPARK_LOOK` | the look: `spark look on\|off\|auto` | `off`, `auto` after awaken |
| `SPARK_HEIGHT` | the row spark writes in: `spark height N` | `1` |
| `SPARK_VOICE` | `off`, `clear` or `on`: `spark voice` | `off` |
| `SPARK_VOICE_RATE` | the voice's speed, 50 to 300: `spark voice rate N` | `100` |
| `SPARK_VOICE_DEVICE` | the sound card on Linux, such as `plughw:1,0` | ALSA's default |
| `SPARK_KNOWLEDGE` | `off`: the prompt line skips the manuals | `on` |

`~/.config/spark/mcp.env` is the list of MCP servers, written by `spark
mcp add`, `rm` and `trust`:

| key | what | default |
|---|---|---|
| `MCP_SERVER_<NAME>` | a server: its program's absolute path, then its words | none |
| `MCP_SERVER_<NAME>_TRUST` | `yes` or `no`: believe what its tools say of themselves | `yes` for spark's own programs |

Root. spark uses `sudo` for the package manager, the hostname, the
`render` group, Void's one service, `spark serve boot on` and `spark
serve share on`.
`~/.spark/bootstrap.sh --dry-run` lists what it would do, without
`sudo`.

Keep passwordless `sudo` off a machine that serves your network. The
admin token can run any command here. With passwordless `sudo`, that
means root.

The check. `spark check` has 42 rows and exits 0 when no row fails.
Bare, it shows only the rows that need you, each with its fix. `spark
check --all` shows every row. `spark check --report` prints a block for
a bug report, with no names or paths.

When a row turns worse, your next prompt says so on the line spark
writes, with the fix: `! serve: nothing answers at 127.0.0.1:8080 --
spark serve on`. When it heals, the prompt says that too: `* serve: ok
again, after 21 min`. Each is said once in each shell, and `spark off`
keeps both quiet. The engine and the page are red for a moment after an
update or a restart, while the model loads. The prompt says so only when
they are still red 3 minutes later. `spark check --history` lists the
changes, newest first, and `spark check --history NAME` those of one
row. They are kept `SPARK_HISTORY` days.

When something stops working:

GitHub bug reports are public. Use `spark check --report`, then review
what you share. Use made-up names and paths in your steps, and do not
post private prompts, tokens or login QR screenshots. README.md says
the same under Bugs.

1. `spark check` names the row and the fix.
2. `spark` says which model answers now. `spark status` is the full
   report, with what the last check found.
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

spark serves plain HTTP on one address of your network, or https with
a certificate you configured above. Without one, your
network is the trust boundary.

- Over plain HTTP, anyone on your network can read the traffic, tokens
  included. A captured token works until it is rotated. Rotate with
  `spark user token --new`, or `spark serve --login --new` for the
  admin.
- Over plain HTTP a captured admin token acts from this network alone:
  a verb run or a command through the do console answers no peer
  routed in from outside it. Over https it acts from anywhere a valid
  session reaches.
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
names who made spark and what it uses, with the notice. `spark stats
--sends` shows what spark sent over the network, by destination and
day.

## How it fits together

- The engine, llama-server on port 8080, runs the model.
- The page's server, on port 8081, keeps the soul, the memory and the
  threads. It serves the page, the API and other machines.
- `spark` at your prompt talks to both.
- `spark check` runs every 5 minutes.
