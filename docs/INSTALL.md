# Installing spark

Start at section 1 without a machine, at section 2 with one. The rest
is the runbook, in the order you need it.

## 1. A machine from zero

About 10 minutes, with `sudo` once. One model download takes most of
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
   sudo apt-get update && sudo apt-get install -y git curl python3 openssh-client
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

Void:

1. Get the live ISO from voidlinux.org: the glibc flavour, `x86_64`.
   Write it to a USB stick and boot it. The engine is a glibc build,
   so `get` refuses the musl flavour.
2. Log in as `root`, password `voidlinux`, and run `void-installer`.
   The answers that matter:
   - A user in the `wheel` group. That is the `sudo`.
   - GRUB as the bootloader.
   - A network.
3. Reboot, log in, run `sudo xbps-install -Su` once, then:

   ```sh
   sudo xbps-install -Sy git curl python3
   ```

4. Continue at section 2.

A machine that will not join the Wi-Fi: `docs/TROUBLESHOOTING.md`.

macOS: any Mac Apple still updates. `xcode-select --install` brings
`git`, `curl` and Apple's `python3`. Version 3.9 is enough.

Windows: spark runs in WSL 2, where Ubuntu is Linux to it. In
PowerShell run `wsl --install -d Ubuntu-24.04` and reboot when asked.
Open Ubuntu, then do Debian's step 3.

## 2. Install spark

1. Check the 5 things spark needs: `sudo` once for the package
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
   - Void Linux: `sudo xbps-install -Sy git curl python3`. When xbps
     refuses, `sudo xbps-install -Su` first: xbps itself must be
     current. `ssh-keygen` is already there: Void's base system
     brings OpenSSH.
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
   spark check      # what needs you; exit 0 when no row fails
   ```

What `get` does first. It checks the ground: the command line tools on
macOS, `apt-get`, `pacman` or `xbps-install`, `git`, `python3` 3.9 or
newer, and `ssh-keygen`. When one is missing it refuses and prints the
install line. It never runs `sudo`. `SPARK_HOME` moves the clone,
`SPARK_URL` points it at another repository, and `SPARK_REF=main`
follows development. `sh get --clone-only` stops after the clone.

What `spark setup` does. It asks 3 things: this machine's name, yours,
and the model. The name defaults to the short hostname, yours to your
login. The model row this machine earns is marked `*`. One question
more, default no: should spark read aloud for you, in the clear voice
for low vision? "The voice" in section 3 says what that is. Then it:

1. Writes `~/.config/spark/site.env` at 0600.
2. On Linux, asks `sudo -v` once when a package is missing: `libgomp1`
   on Debian and `libgomp` on Void, plus the Mesa Vulkan packages with
   a GPU. Arch has the library in `base`, so it asks only with a GPU.
   macOS needs nothing.
3. Runs `bootstrap.sh`: the engine, one pinned llama.cpp tarball for
   this OS, checked by sha256. The model, with curl's progress bar. The
   token, the prompt line, one rc line, and the units: the engine, the
   page's server and a check every 5 minutes. On Void the units are
   runit services, and the first run writes one root service with
   `sudo`.
4. Brings the engine up and waits for it.
5. Asks `? how big is this dir` for you and prints the speed.
6. With a yes to reading aloud, runs `spark voice clear`: the engine's
   download, its size said first.
7. Prints 3 things to try, after `open a new shell (exec $SHELL)`.
8. Suggests the next step in one line: `next: spark awaken -- give this
   machine a personality and a look`. Nothing changes until you run it.

It paints nothing: the machine looks as it did. You can run it again at
any time. `--yes` takes every default, and is implied when stdin is not
a terminal. `--model NAME|auto|none`, `--name NAME`, `--user NAME`
and `--no-serve` pre-answer, as do `SITE_NAME`, `SITE_USER` and
`SITE_AI_MODEL` in the environment. A `SPARK_VOICE` already set, in
the environment or in `spark.env`, is not asked again.

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
the prompt line: bash 4 or newer and zsh can, macOS's bash 3.2 cannot.
Run `chsh -s /bin/zsh`, then `spark setup` again. A bare zsh needs
your own `autoload -Uz compinit && compinit` in `~/.zshrc` for
completion.

## 3. Use it

The prompt line. Type `? words` or `words?` and press `Enter`. The
command lands in your line the moment it is complete, and its hint
fills the row above it. `Enter` again runs it. Everything spark or the
model says sits in that row, and your line holds only the command. A
command that deletes comes back marked `!`, and a recursive `rm` says
how many files and bytes it clears. The `!` is there before the
command is. Before the command lands, spark checks it against the
manuals on this machine. When a flag is not in the manual, spark asks
the model once more, and the hint says so. `?? words` follows up on
the last answer. `Esc s` asks about the line you are on. `spark off`
gives `Enter` back, and `spark on` restores it. `TAB` completes the
verbs and their words, offline. While the model answers, the mark
pulses in that row. The marks are plain unless your rc exports
`SPARK_ACCENT_SGR`, `SPARK_MUTED_SGR` and `SPARK_WARN_SGR`, SGR codes
such as `1;94`. A pipe never sees an escape.

The failure line. When a command fails, the row above the next prompt
says `* failed (1) -- Esc s asks why`. The next thing spark says there
replaces it. `Esc s` on the empty line puts the command back, piped to
`explain`, and the row says `* Enter explains the error`. Nothing runs
until you press `Enter`. A second `Esc s` proposes the corrected
command. When a command is not found, exit 127, `Esc s` gets the line
that installs it. A command that deletes or destroys is never offered a
re-run. After the fix works, `Esc s` offers to keep it as a `spark
memory add` fact. `Ctrl-C` and a no-match from `grep` or `diff` stay
quiet.

`Esc r` is intent search. Type what a command did in your own words and
press `Esc r`. The line that ran lands in your prompt, and `Esc r`
again cycles through the matches. Every candidate is a line from your
shell's own history. `Ctrl-R` stays the shell's.

The row. spark writes in the row just above the line you type on. A
prompt of two lines, such as starship's default, has its status line
there, and spark's line would sit on it. Press `Esc k` at the prompt: a
test line shows where spark writes, and each press moves it up a row,
to 3 and back to 1. The choice holds for every shell. `spark height N`
sets any height from 1 to 5, and `spark height` shows it.

Every verb below has a `-h` with the rest.

A script, a cron job and `ssh HOST 'spark ...'` name
`~/.local/bin/spark` in full. A stock `~/.bashrc` returns before
spark's hook in a shell that is not interactive, so `~/.local/bin` is
not on `PATH`.

`spark chat` talks with the model at a `chat> ` prompt. It goes on
with your newest thread and opens with one line:

```
* continuing "how do I resize a partition" -- /new starts fresh, Esc ends
```

With no thread to go on with, the line is `* chat with NAME -- Esc
ends, /help lists commands`. The chat ends with nothing printed.

`Esc` on an empty line, `/q` or `Ctrl-D` ends. On a line with text,
`Esc` does nothing. On macOS the system's line editor reads that `Esc`
as Alt for the next key. `Ctrl-C` clears the line, or cancels a reply,
and the chat goes on. `spark chat --thread N`
continues an older thread from the `spark history` list. A thread
lives `SPARK_HISTORY` days. With `SPARK_HISTORY=off`, `spark chat` goes
on with the newest kept thread.

The commands:

| command | what it does |
|---|---|
| `/help` | lists the commands |
| `/new` | a fresh thread |
| `/resume [N]` | an older thread: bare lists the newest 5, N picks one |
| `/clear` | wipes the screen, and the thread goes on |
| `/keep` | keeps this thread past `SPARK_HISTORY` and `spark clear --history`. `/keep off` lets it go |
| `/last` | the last turn, with its tok/s |
| `/model` | which model answers |
| `/reveal [N\|auto\|off]` | the pace of the replies. Bare, the measured numbers |
| `/copy [N]` | the last reply, or the Nth from the end, to the clipboard |
| `/save [FILE]` | the thread as a text file |
| `/read @FILE [question]` | an answer about the file, every line quoting it |
| `/do GOAL` | a task, one confirmed step at a time, as `spark do` runs it |
| `/do --sandbox GOAL` | the same task in a copy, as `spark do --sandbox` runs it |
| `/aloud` | speaks every reply, or stops: `spark voice on` or `clear` first |
| `/again` | the last reply again, printed and spoken |
| `/q` | ends the chat |

`/copy` uses the clipboard tool it finds: `pbcopy` on macOS, `wl-copy`
on Wayland, `xclip` or `xsel` on X11. On the console or over ssh there
is none, and it says `! no clipboard here -- /save writes a file`.

`/save` writes the thread as plain text to FILE, by default
`~/spark-chat-YYYY-MM-DD.txt`. It never overwrites a file: a second
save that day gets `-2`, then `-3`. The file is 0600, and the chat says
its path and how many turns it holds. The thread stays sealed, and the
file is your own copy.

`/read @FILE question` answers the way `spark read` does. Every line
quotes the file, and a line the file does not hold is dropped. When
nothing is left, one line says the file does not answer. The question
and the answer land on the chat's thread. `@FILE` in an ordinary
message stays a free answer about the file.

`/do GOAL` hands the goal to `spark do`. Each step is confirmed as
below, and `--sandbox` ends with the diff to review. Then you are back
at `chat> `. The chat itself runs nothing.

With the voice on or clear, `Esc v` at `chat> ` listens. A pause ends
it, and the words land on the line: `Enter` sends them. `Esc x` stops
the speaking. In clear mode every reply is read aloud from the start.
In mode on, `/aloud` reads the replies. `/again` prints the last reply
again, and speaks it while the voice is on. "The voice" below has the
rest.

Awake, the face shows while a reply is on its way, and goes when the
reply comes. A reply is plain text, with no face. A reply read aloud
is the one exception: the face leads it and talks while the voice
plays.

`spark <words>` streams one answer. `spark @FILE words` sends a text
file's first 4 kB and last 12 kB with the question.

`spark do <words>` proposes one command at a time. `Enter` runs it, `e`
edits it, `s` skips it, `q` quits. On a block, `r` reads it again. A
step that can destroy data runs only when you type `yes`. After a step,
a read-only check that it worked is offered the same way, and only its
exit code goes back. Each step's output, the last 4 kB, goes back to the
model until it says done, or after 8 steps. A goal is at most 8 kB, and
one that starts with `-` goes after `--`.

A step is one line, or a block of several lines: a here-document that
writes a file. A block is shown whole before you confirm it, the step
line first, then every line numbered beneath it:

    * 1  cat > count.py <<'EOF'   (3 lines)   write the script
         1  cat > count.py <<'EOF'
         2  print(len(open("notes.txt").read().split()))
         3  EOF

Danger is read on every line. A redirect onto a file that does not
exist yet destroys nothing, so it is not marked. One onto a file that
is there is marked, and so is any redirect in a step that runs `cd`.
`e` on a block opens it in your editor: `$VISUAL`, `$EDITOR`, else
micro, nano or vi. With none, `e` says so and the step is unchanged.
A block is 16 kB at most, a line 4096 characters, and a line feed is
the only control character a block may hold.

`spark do --sandbox <words>` does the same task in a copy of this
directory. Every step runs on its own, 2 minutes at most, with no
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
answer: at most 3, one per line, and nothing else. A line that is
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
checked against the stream. A window of up to 40 lines or 10 seconds,
8 kB at most, goes to the server you chose, never the whole stream.

`spark soul edit` writes the paragraph that tells the model who it is:
`~/.config/spark/soul`, at most 4000 characters. `spark soul reset`
goes back to the default:

```
You are spark, the AI on this machine. You run here, on hardware the user
owns. You are here to answer, to explain, to write, and to hand the user
a command when one is what they need. Speak plainly, in the user's
language. Say when you do not know. Never invent a flag, a path, or a
command.
```

After `spark awaken` the soul has two parts, spark's fixed core and a
personality paragraph: see "The living prompt" below.

`spark memory add <words>` adds a fact it keeps: 40 facts of 200
characters. `spark memory forget N` drops one, and `spark memory off`
stops sending them. Soul and facts ride on every question, so keep
the facts that change answers. The model never writes them.

`spark bar line` prints the machine's status in one line: load, memory,
disk, net, the model, the last check, runs waiting and the clock. A
status bar runs it every 15 seconds.

The living prompt. After the install spark works as it did. `spark
awaken` gives this machine a personality and a look, and until you run
it nothing changes. Step by step:

1. It asks one question, the temperament: plain, warm, playful or
   terse. `Enter` keeps plain.
2. The model picks its face. With no model answering, the shipped
   face is used.
3. It shows the personality paragraph it wrote, addressed to the model
   as "you". A paragraph in the first person is refused, and the
   shipped one stands in. A soul file of your own is kept.
4. One reply plays at a measured pace. Answer `yes`, `faster`,
   `slower` or `off`.
5. Where a player is, it offers a voice of its own, made from the
   temperament. It asks before the engine downloads, plays a line in
   that voice, and asks `keep`, `again` or `none`. "The voice" below
   has the rest.
6. The look turns to `auto` and it says `* awake -- the look is on
   auto`. Your next prompt, in every open shell, is awake. A voice you
   kept is on.

Nothing is written until the end, so `Ctrl-C` leaves the machine as it
was. An engine already downloaded stays for the next run. Run it
again to start over. The look is one switch, and 3 parts follow it.
`spark look` shows it, with the height, the reveal and the face:

- Motion: while a reply comes, a scanner with a face,
  `* (o.O) [  =     ]`. While a model loads, a bar with an estimate
  from its last load. From 2 seconds a wait shows its seconds. It draws
  on every terminal, ssh and the console too.
- Colour: a built-in palette of bold, dim, red, bold red and green,
  where you export no colour of your own. Dim is only for decoration.
- Words: the face in the wait. spark prints no greeting, no goodbye
  and no news.

Awake, a failed command that ran over 30 seconds says how long:
`* failed (1) after 4 min -- Esc s asks why`.

The reveal is the pace a reply appears at, as `spark reveal` sets it.
On an awake machine it breathes at the punctuation.

`spark look on|off|auto` sets the 3 parts at once. `auto` draws each
only where the terminal carries it: a terminal, not `TERM=dumb`, and
for colour `NO_COLOR` unset. `on` draws at any terminal, over
`NO_COLOR` too. `off` turns them all off, and `spark reveal off` stops
the reveal. A pipe never sees a frame or a colour.

What wins, strongest first: a pipe, then `spark off`, which silences
the prompt line. Then the look `off`, then `on`, then `auto`.

Your own colours win over the built-in ones. `SPARK_OK_SGR` and
`SPARK_TROUBLE_SGR` join the 3 exports above, the same SGR codes.
`spark check` paints its rows with them when awake. `SPARK_YOU_SGR` is
reserved: nothing paints with it yet.

The machine's own look is not spark's: the console's palette and font,
the terminal's profile, a quiet boot. A tool of your choice may write a
palette to `~/.config/spark/theme.env`. When it is there, `spark ver`
draws its logo in it and the status line takes its accent.

Awaken makes only what shows: the personality and the face. After
awaken, `spark soul edit` changes the personality paragraph alone, and
`spark soul edit --core` the whole soul.

The voice. `spark voice` reads aloud and hears a question, all on this
machine. It has 3 modes, the key `SPARK_VOICE`:

- `off`: silent. The default.
- `clear`: a plain clear voice, for low vision. It needs no `spark
  awaken`, and `spark setup` offers it.
- `on`: this machine's own voice, the one `spark awaken` made for it.
  It is never a plain human voice.

```
spark voice                   show the voice settings
spark voice clear [--anyway]  read aloud in a clear voice
spark voice on                use this machine's own voice
spark voice off [--remove]    turn the voice off (--remove frees 600 MB)
spark voice rate N            set the speed (50 to 300, default 100)
spark voice test              say one line
spark voice listen            ask a question by voice (Esc v)
spark voice stop              stop speaking (Esc x)
```

Clear mode reads the prompt line's command with its symbols. `du -ah
~ | sort -rh` is "du, dash a h, tilde, pipe, sort, dash r h". Then it
reads the hint. A line marked `!` is read with its warning first. In
`spark do` it reads each step. In a block it reads every command line
with its symbols, and the text of a here-document as "a here-document
writing count.py, 3 lines of text". `r` reads every line again. It
reads the choices once a
run, the last 3 lines of each output and the end. It reads the chat's
replies and the errors. Every line it speaks is printed too.

A chat reply read aloud is shown as it is spoken. Each sentence goes
to the voice as the model writes it, and its text appears as its sound
starts, at the pace of the voice. `spark voice rate` sets both. The
first sentence goes at its first comma, or after six words with none,
so the first sound never waits for a whole sentence. The voice is
loaded once, as the chat opens and while you type.

Awake, a reply read aloud starts with the face, and its lines hang
under it. While a sentence plays, the mouth opens and closes, `(o.o)`
and `(oOo)`. Between sentences, after the last one and after `Esc x`,
it rests. It rests too once you type at `chat> `, or once the reply
has scrolled its first line off the screen.

The text follows the voice only with the reveal on, at a terminal of
this machine. Over ssh the sound plays on the far machine, so the text
keeps the reveal's pace. With the reveal off the text shows at once
and the voice reads behind it. A sound late by 8 seconds lets the rest
of the reply go at the reveal's pace.

The voice starts with a quarter second of silence, so a sound card
that sleeps never loses the first word. `SPARK_VOICE_LEAD_MS`, 0 to
1000 in the environment, changes that silence.

Mode on speaks the chat's replies after `/aloud`. It never reads the
prompt line. The voice comes from the
temperament: plain is a radio, warm a soft robot choir, playful eight
bit and terse a robot. The machine's seed picks a speaker and tunes the
sound, so two machines rarely sound alike. `spark voice` names it, such
as `radio, Kokoro af_heart`. `spark voice on` on an awake machine that
kept none makes one from its temperament.

A reply in Portuguese is read in a Brazilian Portuguese voice, and one
in English in an English voice.

The keys, at the prompt and in the chat:

- `Esc v` listens. A pause ends it, and the words land in your line. On
  an empty prompt they land as a `? ` question. Nothing runs until you
  press `Enter`.
- `Esc x` stops the speaking, in this shell and in any other.
- The prompt binds both keys only when the voice is on or clear as the
  shell starts. After `spark voice on` or `clear`, open a new shell.

A spoken yes never confirms anything. A step that can destroy data
still needs `yes` typed, and `spark do` never listens.

The engine. It is downloaded only when you turn the voice on, by
`spark voice on`, `spark voice clear`, or a yes at setup or at awaken.
The size is said first. Each part is pinned in `voice.env`, and its
size and sha256 are checked before a byte is unpacked. A part that
does not match is refused, and nothing is kept.

| part | what | size | licence |
|---|---|---|---|
| the runtime | sherpa-onnx v1.13.8, with onnxruntime inside | 28 MB on Linux, 44 MB on macOS | Apache-2.0; onnxruntime MIT |
| the mouth | Kokoro-82M v1.0, full precision, with espeak-ng-data | 350 MB | Apache-2.0; espeak-ng-data GPL-3.0 |
| the ears | Whisper base, int8 | 208 MB | MIT |
| the end of a question | Silero VAD | under 1 MB | MIT |

That is about 586 MB on Linux and 602 MB on macOS, in
`~/.local/share/spark/voice`. The voice spark awaken made lives in
`~/.config/spark/voice`, 0600. `spark voice off --remove` deletes the
engine, and `spark uninstall` takes both. `CREDITS.md` names every
part. The runtime is a glibc build, so Void's musl flavour refuses it
in one line.

Where it plays and listens. macOS plays through `afplay`, and the
terminal asks once for the microphone: allow it. Linux plays through
`aplay`, else `paplay`, and listens through ALSA. A headset on the
second card needs `SPARK_VOICE_DEVICE=plughw:1,0` in `spark.env`.
`aplay -l` lists the cards. The `voice` row of `spark check` says
whether the engine is here and is its pin, and names the player and the
listener. It is `na` while the voice is off.

Screen readers. VoiceOver on macOS, and Orca or speakup on Linux, read
for you already. While one runs, clear mode stays silent. `spark voice
clear` says why, and `spark voice` shows it. `spark voice clear
--anyway` speaks beside it.

What it hears. Listening is push to talk alone: `Esc v` or `spark voice
listen`, and no wake word. The recording goes to a private directory
and is deleted before the words come back. The voice runs here, on a
client of another machine too, and nothing it hears or says leaves the
machine.

## 4. Models

Two files:

| file | what |
|---|---|
| `models.env` | every model spark can serve: 11 models, each with its license, in priority order. `line` marks a row proven on the prompt line |
| `~/.config/spark/models.env` | your own rows (`spark model add URL --license`), 0600, marked `u` |

`spark model list` shows every row: the file size, the RAM it needs
against this machine's budget, the license, the proof column,
downloaded or serving, and its speed here. The budget is
`SITE_AI_BUDGET`, 60 percent of RAM plus GPU memory by default. The
proof column says `line` when the row is tested on the prompt line, or
a `kept/run` score once the grounding audition measured how faithfully
it quotes a source. The speed `~N tok/s` is an estimate until `spark
bench` or a real turn measures it, and `too big` means the row does not
fit.

The list is in priority order. The first four rows are the prompt
line's ladder, measured on the maintainer's box:

| name | file | RAM | for |
|---|---|---|---|
| `gemma4-26b-a4b` | 15.9 GB | 19 GB | the best, a machine with 32 GB |
| `gemma4-e4b` | 5.0 GB | 8 GB | the standard, with a GPU or without |
| `qwen3-4b` | 2.3 GB | 5 GB | a budget of 5 to 7 GB |
| `qwen3-5-2b` | 1.3 GB | 3 GB | a small machine |

Five more rows are tested on the line, for you to name or for the chat
model: `qwen3-5-4b`, `qwen3-8b`, `granite-4-2-8b`, `qwen3-14b` and
`qwen3-30b-a3b`. Two are yours by name: `gemma4-e2b` and
`qwen3-coder-30b-a3b`. Every row is under Apache-2.0. A row of your own
under another licence prints its licence and asks `download it?
yes/NO:` first. The project site lists them all at
spark.forgewright.ai/models/.

How `auto` picks. It walks the list in order and takes the first tested
open-licence row that fits. A row fits when its RAM fits the budget and
its file is under this build's speed cap: 3 GB on `cpu`, 6 GB on
`vulkan`, 20 GB on `metal`. Those sizes keep about 8 tok/s. A row with
4B working parameters or fewer counts as a small file. That is a MoE's
active 4B, as in `gemma4-26b-a4b`, or a Gemma edge model's effective 4B,
as in `gemma4-e4b`. On the maintainer's box with no GPU, E4B writes 16.8
tok/s. When the cap held a row back, the
table's header says so, and `spark model NAME` takes that row anyway.
When nothing under the cap fits, it takes the smallest row that fits.

1. `spark model NAME` chooses a model. It downloads the file, checks
   its size and sha256 against the row, and restarts the engine. `spark
   model auto` goes back to the rule above. `spark model rm NAME`
   deletes a file not in use.
2. `spark model budget N`, 10 to 95, sets the percent and prints the
   table.
3. A `.gguf` of your own in `~/.local/share/spark/models` is served
   with `SPARK_MODEL=<file>` in `spark.env`.
4. `spark model --chat NAME` chooses a second model for chat, a larger
   one. The prompt line stays with the small one, at
   context 4096 with reasoning off and a thinking budget of 0, so a
   thinking model answers fast. Everything else goes to the chat
   model: `spark <words>`, `chat`, `do`, the page, and any `/v1` client
   naming no model. One engine, one port, one token: the request's
   `model` field picks. `spark model --chat auto` pairs the smallest
   tested row with the first in the list that fits beside it.
   `spark model --chat none`, the default, runs one model in both roles.
   `spark model --chat list` shows the pair.
5. `spark model add URL` adds your own row. A huggingface.co
   `.../resolve/<rev>/<file>` URL is checked from its redirect headers,
   and any other URL needs `--sha256 HEX`. `--license "NAME URL"` is
   required. The row lands in `~/.config/spark/models.env`, then it is
   downloaded and served like any row.
6. `spark model verify` checks every downloaded file again. It prints
   `intact` per file, or `damaged -- spark model rm NAME; spark model
   NAME`, and exits 1 on a damaged one. Nothing is deleted for you.
   The `models` row of `spark check` is the daily, cached version.

Speed. `spark bench` measures with llama-bench, prompt 512 and generate
128, and keeps the result as the file's baseline. The `throughput` row
warns when real turns fall below 70 percent of it. `spark bench tune`
tries GPU layers, flash attention, KV cache types and thread counts,
and `spark bench tune apply` writes the winner to `spark.env`. `spark
stats [--week]` sums up what real turns measured. The engine keeps no
prompt cache in RAM, `--cache-ram 0`, because llama-server would
otherwise keep up to 8 GB of replaced prompts in host memory.
`SPARK_EXTRA_ARGS=--cache-ram N` in `spark.env` sets a budget in MB.

The prompt line has a pace of its own. `spark bench --line [N]` asks
N everyday questions (5 by default) the way the prompt line does. It
times the wait until the command is ready and until the whole answer.
It counts the warm slots too: a warm slot reuses the prompt it has
already read. `spark stats` shows the result as the line pace, and the
`throughput` row names it. Nothing the questions propose is run.

The prompt line reads this machine first. spark keeps an index of its
programs, their manuals, its apps, its services and its own verbs in
`~/.local/state/spark/knowledge/`. `./bootstrap.sh` builds it, and the
check timer refreshes it every 5 minutes. A program with no manual is
read from its `--help`, and only inside the sandbox. The `knowledge`
row of `spark check` says what the index holds and how old it is.
`SPARK_KNOWLEDGE=off` in `spark.env` turns it off, and the prompt line
answers from the model alone.

## 5. Other machines and your phone

spark serves the same model, with its soul, memory and threads, on one
LAN address: `http://<host>:8081`. The admin token stays on this
machine.
Everyone else is a named user with a token of their own.

The servers. Two run on this machine, and one verb runs them both. The
engine, llama-server on port 8080, holds the model. The page's server
on port 8081 holds the soul, the memory and the threads. It answers
the page, the API and every client.

- `spark serve on` starts both through their services and waits until
  they answer, then says one line each. It is kept: they come back
  after a restart.
- `spark serve off` stops both and keeps them down. `--force` also
  stops an engine spark did not start.
- `spark serve` alone shows what answers, this machine or the other
  one. It names the model and the chat model, the page's URL, the
  services, boot and share.
- `--login` also prints what another machine needs to join, and
  `--foreground` is what a service runs.

Another machine of yours:

1. Here: `spark user add NAME` mints an account. Its token is shown
   once and never stored.
2. There, with spark installed: `spark client URL`, with the URL from
   `spark serve --login` here. Then `spark user login NAME` with
   that token.
3. `spark client` there says whether this machine answers.

This machine reinstalled: mint the account again here with `spark user
add NAME`, then `spark user login NAME` there with the new token. When
that machine keeps threads of its own, sealed under the old token, the
login locks them under the new one. This machine must accept the token
first.

A client runs nothing of its own: no engine, no model, no units, and no
account of its own. The login is the token minted here. `spark check`
there reads `na` on those rows, and the `peer` row says whether this
machine answers and accepts that login. `spark model` there prints
this machine's table, and choosing a model there is refused. `spark
client off` gives it a model of its own again. From then on it never
asks this machine, even while this one answers, until `spark client
URL` there again.

Another OS user on this same machine, on Linux: you run `spark serve
share on` once. That makes a `spark` group with one engine for everyone.
Add the user to the group with `sudo gpasswd -a NAME spark`, and they
log in again. Then they run the one-liner in their own home, with no
`sudo` and no download. `spark setup` sees the shared engine and joins
it: their own soul and memory, one model loaded once. `spark serve share
off` ends it.

Every program that calls spark, a script, an app or a CI job, gets its
own user with `spark user add NAME` and its own token. The admin token
is never shared. Any program with the OpenAI shape works. A request
naming no `model` gets the chat model with the identity, and
`model: spark` the bare prompt model. `"identity": false` asks for the
chat model bare, for a program that brings its own system prompt:

```sh
curl -sN http://<host>:8081/v1/chat/completions \
  -H "Authorization: Bearer $YOUR_SPARK_USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"what is this machine for?"}],"stream":true}'
```

A program keeps its own threads the same way, in its user's store.
`POST /api/threads` makes a thread that `SPARK_HISTORY` never ages,
with no model turn. It goes with its user (`spark user remove NAME`).
`POST /api/threads/ID/append` adds one message, and its answer says
whether the message was kept. A write carries `X-Spark: 1`:

```sh
curl -s http://<host>:8081/api/threads \
  -H "Authorization: Bearer $YOUR_SPARK_USER_TOKEN" \
  -H "Content-Type: application/json" -H "X-Spark: 1" \
  -d '{"id":"notes"}'
```

The users. `spark user list` shows them with their threads, the kept
ones counted, and last activity. `spark user add NAME` mints an account
and shows its token and a QR of its login link once, and `--no-qr`
skips the QR. `spark user remove NAME` deletes the account and its
sealed data, kept threads too, and asks first. `SPARK_YES=1` answers
yes, for a script. `spark user login NAME`
pastes a token so this machine acts as NAME. `spark user logout`
forgets the login, and the sealed data stays. `spark user token --new`
rotates your token, and other logins die. A name is a-z, 0-9 and `-`,
starting with a letter, at most 32 characters.

The page, in any browser on the LAN:

1. `spark serve --login` prints `http://<host>:8081/login`. At a
   terminal it also prints the admin token and a QR code. Piped, it
   prints the URL alone, and `--show-token` adds the token. Scan the
   QR with a phone's camera and the page signs in by itself. The token
   rides the link after `#`, which never reaches the server. The QR is
   the token drawn as squares: show it only to the user it is for.
2. Or type a token once. The browser keeps a cookie for 90 days, and
   logging out or a server restart asks again. A user's token opens a
   chat app: their own threads and memory, plus their account behind
   the one menu button. The admin token also opens the whole machine:
   activity, `do`, the settings and the log.
3. On a phone, add it to the home screen. On iOS, share, then add to
   home screen, and it becomes an app. Android keeps a shortcut that
   opens in a browser tab. The page needs this machine reachable when
   it opens. There is no offline copy.

`spark serve --login --new` rotates the admin token, and `spark user
token --new` rotates a user's. That user logs in again. `spark serve
--audit [N]` lists the newest admin actions, sealed in this machine's
own store. Each is a command run from the page, with its sha256 prefix
and exit code and never its text, a verb run, or a user added, removed
or rotated.

Sealed stores. Each user's threads, memory and chat history are
encrypted under a key wrapped by that user's token. The cipher is
ChaCha20-Poly1305, written from RFC 8439. The machine keeps a sha256
verifier and the wrap, never the token. Nobody, the admin included,
holds a key to another user's messages. A lost token is lost history.
There is no TLS on the LAN: the trust model is your LAN.

Up from boot. On the machine that stays on, `spark serve boot on`:

- Linux: the units run from boot without a login, by linger. The GPU is
  reachable without a seat, by the `render` group. Sleep, suspend and
  hibernate are masked, and the lid is ignored. `off` reverses all but
  linger and the group. Over a plain `ssh HOST spark model NAME` the
  units are reached the same way: spark brings the user bus itself. On
  Void the services run from boot already, and sleep and the lid are
  the machine's own. Void has no `render` group: its GPU node is open
  to every user. So `on` changes nothing there, and the row says so.
- macOS: the 3 agents move to `/Library/LaunchDaemons`, with no
  auto-login, and FileVault's login screen is untouched. `pmset` keeps
  the machine awake. Restart and stop then need `sudo launchctl`, and
  the verbs print the line. `off` puts the login agents back.
- WSL 2 stops with its last window, so `spark serve boot on` refuses
  there.
- A machine that starts before its network has no LAN address yet. The
  model and the page then wait for one, as long as it takes, and start
  when it comes. Their log says so.

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
- Units: `launchctl print gui/$UID/spark.serve`, and `.forge` and
  `.check` likewise. `launchctl kickstart -k gui/$UID/spark.serve`
  restarts one.
- `spark stats` and the `gpu` row say the counter needs root.
- `Alt-s` is Option-s. `Esc` then `s`, quickly, is the same keys.
- The voice: the terminal asks once for the microphone the first time
  `Esc v` listens. Allow it. Section 3, "The voice", has the rest.
- `spark do --sandbox` copies the project as an APFS clone and runs
  each step in it under `sandbox-exec`. A step opens no network socket
  and writes only to the copy and the run's own home and temp. It
  cannot read your home, other volumes, the temp directories, the
  keychain or spark's state and token. It cannot run `osascript`,
  `open`, `launchctl`, `sudo`, `security`, the clipboard, Shortcuts,
  Automator, `defaults`, `cron` or `at`. It still reads the rest of the
  system, such as `/Applications` and `/etc`, and sees the process
  list. The diff is the gate: read it before you type `yes`. The
  `sandbox` row says whether it works here. `sandbox-exec` is Apple's
  own tool, and its man page tells developers to move off it.

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
- The `render` group grants the GPU without a logind seat.
  `bootstrap.sh` adds you on a Vulkan build. Log out of every session
  and in again for the units to see it. Void has no such group: its
  GPU node is open to every user, and the `headless` row says so.
- The voice plays and listens on ALSA's default device. A headset on
  another card needs `SPARK_VOICE_DEVICE`, such as `plughw:1,0`.
  Section 3, "The voice", has the rest.
- The console's font, its palette and a quiet boot are yours to set:
  spark leaves them as the machine has them. The console cannot draw
  the check and arrow glyphs, so spark prints ASCII there.
  `SPARK_ASCII=1` forces it.
- `spark do --sandbox` needs bubblewrap 0.11 or newer, which Debian 13
  and Arch ship. Ubuntu 24.04's 0.9 has no overlay, and the `sandbox`
  row reads `na` there. Each step runs in fresh namespaces: no network,
  and the homes, `/run`, `/tmp`, `/var/tmp`, `/media`, `/mnt` and
  `/etc/spark` hidden. The project is an overlay that keeps every
  write. `sudo` inside cannot become root. The rest of the system stays
  readable, so the diff is the gate there as well.
- Units: `systemctl --user status spark-serve spark-forge
  spark-check.timer` and `journalctl --user -u spark-serve -n 50`. On
  Void: `sv status ~/.config/spark/sv/*`. Without a user systemd
  session, as in a container, the `services` row reads `na`, and
  `spark serve on` starts both by hand.

Arch:

- Linux to spark: the same one-liner, the same rows. The engine is the
  pinned `ubuntu-*` tarball, a glibc build, and Arch's glibc is newer.
  CI proves the one-liner in an Arch container. The units and the GPU
  there are proven by hand.
- Packages come through `pacman -S --needed`, never `-Sy` alone. When a
  name cannot be found, the `packages` row says `sudo pacman -Syu`
  first. `gcc-libs` is in `base`, so without a GPU nothing is
  installed.

Void:

- Linux to spark: the same one-liner, the same rows. The engine is the
  pinned `ubuntu-*` tarball, a glibc build. Void's glibc flavour runs
  it, and `get` refuses the musl flavour in one line. The voice's
  runtime is a glibc build too. CI proves the one-liner and the
  supervised services in a Void container, and the maintainer's box
  runs Void with the engine on its GPU.
- Packages come through `xbps-install -Sy`. When xbps refuses an
  install, the `packages` row says `sudo xbps-install -Su` first: on a
  rolling distro xbps itself must be current. `libgomp` is its own
  package, so `spark setup` asks for `sudo` once, GPU or not.
- Services are runit's. There is no systemd. `bootstrap.sh` writes
  `/etc/sv/runsvdir-USER` once, with `sudo`, and links it into
  `/var/service`. From then on the services run from boot, logged in
  or not. The 3 live in `~/.config/spark/sv/`, and `sv status
  ~/.config/spark/sv/*` shows them. Each log is
  `~/.local/state/spark/log/NAME/current`. `spark serve off` puts a
  `down` file in each service's directory, and `spark check` runs every
  5 minutes as a supervised loop. A `runsvdir-USER` of your own is
  used as it is: spark links its services into its directory. spark's
  own has a `control/t`: a stop, or the shutdown, ends each service
  cleanly first, then the supervisor.
- Void's base has no `hostname` command. With `SITE_SET_HOSTNAME=yes`
  spark writes `/etc/hostname` and sets the kernel's name.
- `spark serve boot on` works. The services run from boot either way,
  and sleep and the lid are the machine's own. A service that keeps
  crashing is held, and the `services` row warns.
- A machine whose network gives only a link-local address, 169.254,
  waits: the model and the page bind the real address when it comes.

Windows, as Ubuntu 24.04 on WSL 2:

- Linux to spark: the same one-liner, the same rows. `spark check` and
  the status line say `WSL 2`. CI has no WSL runner, so the one-liner
  end to end there is on you, for now.
- The engine is the CPU build. WSL 2 exposes the GPU as `/dev/dxg`, not
  as a DRM card, so `auto` lands on `cpu`: `gemma4-e4b` from an 8 GB
  budget, `qwen3-4b` below it. `SITE_AI_BUILD=vulkan` through Mesa is
  yours to try, untested.
- Units: if the `services` row reads `na`, put `[boot] systemd=true` in
  `/etc/wsl.conf`, run `wsl --shutdown` from PowerShell, reopen Ubuntu,
  then `./bootstrap.sh`.
- Not a server for the LAN: the distro stops with its last window, so
  `spark serve boot on` refuses. Reaching the page from the LAN needs
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
With the voice on, a voice part whose pin changed is downloaded again,
its size said first, and the old one goes.
By hand: `git -C ~/.spark pull --ff-only && ~/.spark/bootstrap.sh`.

The first update past v1.62 hands the machine's look back, once. The
console gets its stock palette and font, the boot is loud again, and
the motd and `/etc/issue` return. On macOS the spark profiles leave
Terminal.app. It says `the look is off this machine now`.

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
   Anything else prints `* nothing changed`.
2. Everything spark made goes: the units, the hook line from your rc
   file, `~/.local/bin/spark`, the engine, every model and the voice,
   `~/.config/spark` and `~/.local/state/spark`. The clone at `~/.spark`
   goes when it is the one `get` made and clean. Headless is undone
   first, with `sudo`, and so is a look an older spark set. On Void the
   `runsvdir-USER` service spark wrote goes too.
3. What stays, on purpose: your soul and its personality, your memory,
   the sealed users' stores with their keys, your `models.env` and
   `privacy-terms`. `--purge` takes those too. The packages
   spark installed are a question, and `--packages` or `--keep-packages`
   answer it up front. `--dry-run` shows the plan. `--yes`, or
   `SPARK_YES=1`, skips the question for a script.
4. Named at the end, with the line that puts it back: a hostname it
   set, macOS's `pmset` values, a console font set before v1.12. A root
   step whose `sudo` refuses becomes a `todo` row, never a failure.

The keys. Everything in `~/.config/spark/site.env` beyond the 3
things setup asks is optional and has a verb. Editing the file and
running `./bootstrap.sh` does the same.

| key | values | default |
|---|---|---|
| `SITE_NAME` | this machine's display name | short hostname |
| `SITE_USER` | your display name | your login |
| `SITE_SET_HOSTNAME` | `yes`: the OS hostname follows `SITE_NAME` (sudo) | `no` |
| `SITE_AI_MODEL` | `auto`, `none`, or a name -- `spark model NAME`. `none` beside the other machine's URL is a client | `auto` |
| `SITE_EMBER_MODEL` | `none`, `auto`, or a name: the chat model -- `spark model --chat NAME` | `none` |
| `SITE_AI_BUDGET` | 10 to 95: the percent of RAM plus GPU memory `auto` may use -- `spark model budget N` | `60` |
| `SITE_AI_BUILD` | `auto`, `cpu` or `vulkan`: the Linux engine build. macOS ignores it, and WSL 2 lands on `cpu` | `auto` |
| `SITE_PEER_AI_URL` | another machine's URL, from `spark serve --login` there -- `spark client URL` | unset |
| `SITE_PEER_SSH` | an ssh target, with key auth, that `spark check` should be able to reach | unset |
| `SITE_HEADLESS` | `yes`: up from boot, never asleep -- `spark serve boot on\|off` | `no` |
| `SITE_SHARE` | `yes`: a `spark` group shares this machine's engine with its other OS users (Linux) -- `spark serve share on\|off` | `no` |

Runtime keys live in `~/.config/spark/spark.env`, and
`spark.env.example` lists them all. The ones with a verb:

| key | values | default |
|---|---|---|
| `SPARK_MEMORY` | `on` or `off`: send the remembered facts -- `spark memory on\|off` | `on` |
| `SPARK_REVEAL` | `off`, `auto` or N: a reply's pace at a terminal in chat, explain and a question -- `spark reveal N`, `auto` or `off` sets it, `--reveal` on the verb and `/reveal` in chat for one time. `spark stats` shows the measured threshold | `off` |
| `SPARK_SERVICE` | the engine as a service: `auto` wherever a model is served -- `spark serve on\|off` sets it with `SPARK_FORGE` | `auto` |
| `SPARK_FORGE` | `auto`, `on` or `off`: serve the page and the API -- `spark serve on\|off` sets it with `SPARK_SERVICE` | `auto` |
| `SPARK_FORGE_HOST` / `SPARK_FORGE_PORT` | the page's address and port, never `0.0.0.0` | the LAN address / `8081` |
| `SPARK_HISTORY` | days a turn or a thread lives. `off` keeps none. A kept thread (`/keep` in `spark chat`) stays until you let it go | `30` |
| `SPARK_NGL` `SPARK_FLASH_ATTN` `SPARK_KV` `SPARK_THREADS` | the engine's tuning -- `spark bench tune apply` | auto |
| `SPARK_API_KEY_FILE` | a token file you already have | `~/.local/state/spark/api-token` |
| `SPARK_LOOK` | `auto`, `on` or `off`: the look, once awake -- the scanner, the waking bar and the face in the wait; the built-in palette where you export no colour -- `spark look on\|off\|auto` | `off`, `auto` after `spark awaken` |
| `SPARK_HEIGHT` | 1 to 5: the row spark writes in, counted up from the line you type on -- `spark height N`, or `Esc k` at the prompt | `1` |
| `SPARK_VOICE` | `off`, `clear` or `on`: read aloud in the clear voice for low vision, or in this machine's own voice -- `spark voice clear\|on\|off` | `off` |
| `SPARK_VOICE_RATE` | 50 to 300: the clear voice's speed, 100 as made -- `spark voice rate N` | `100` |
| `SPARK_VOICE_DEVICE` | Linux: the ALSA device the voice plays to and listens on, such as `plughw:1,0` for a headset on the second card | ALSA's default |

What needs root. `bootstrap.sh --dry-run` lists which of these it would
do, and never calls `sudo`:

- Always: the package manager for the `packages` row, and the hostname
  when `SITE_SET_HOSTNAME=yes`. On Void the `runsvdir-USER` service,
  once. On macOS the hostname only.
- `spark serve boot on`: linger, the `render` group, the sleep targets
  and the lid. On Void nothing: the services already run from boot.
  On macOS the LaunchDaemons and `pmset`.

`spark uninstall` uses `sudo` for the mirror image. Passwordless `sudo`
is yours to decide: `echo 'you ALL=(ALL) NOPASSWD:ALL' | sudo tee
/etc/sudoers.d/you` is fine for a test bench.

The check. `spark check` has 39 rows, one per promise this machine
makes, and exits 0 when no row fails. Bare, it prints only the rows
that need you, each with its remedy, then the totals. With nothing to
fix it prints the totals alone. `--all` prints every row, and `spark
check NAME...` the rows you name. `--watch N` redraws every N
seconds. `--porcelain` prints one tab-separated row per line, for a
program. `--fresh` ignores cached answers, and `--fetch` asks origin
before judging the `git` row. `--selftest` proves every fixture-tested
row can flip. `--chaos` breaks a throwaway machine one known way at a
time and proves the right row says so and its remedy heals it.
`--report` prints a block safe to paste into an issue: the version,
the OS, the backend, the model stems and every row's status. Never a
value, a path or a name.

When something stops working:

1. `spark check` names the row and the remedy. `spark check --all`
   shows every row. Long output pages through `$PAGER`, plain when
   piped.
2. `./bootstrap.sh --dry-run` says what a rebuild would change.
3. `spark` says which model answers, and `spark status` whether the
   prompt line is on.
4. A stale server after a DHCP move shows on the `serve` or the
   `forge` row as `serving on ADDRESS, but this machine is ADDRESS
   now`: `spark serve off; spark serve on`.
5. `spark serve` says whether the page is up and at which address. One
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
10. spark's line sits on your prompt: the prompt has two lines. Press
    `Esc k` at the prompt, or run `spark height 2`.
11. For an issue: `spark check --report`.

## 8. What an attacker can and cannot do

The trust boundary is your LAN. spark serves plain HTTP to the
addresses you gave it and nothing else.

- On your LAN, an attacker can read the HTTP traffic, because there is
  no TLS. A cookie or token they capture works until it is rotated or
  its session is logged out. Logging out revokes the session on the
  server, not only in the browser. They cannot log in by guessing. A
  wrong token costs a second, and 10 wrong tokens in a minute lock the
  address out for a minute. The login sleep is bounded, so a burst
  cannot pin the server's threads. The remedy is rotation: `spark user
  token --new` for your own token, which re-keys your sessions on the
  spot, and `spark serve --login --new` for the admin's.
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
  that can destroy data runs only after your `yes`, typed: a spoken yes
  never confirms it. In `spark do
  --sandbox` it runs in a copy with no network and no view of your
  home, and nothing lands here until you have seen the diff and typed
  `yes`. `spark do --accept ID` applies a waiting run without showing
  it, for a script, and an app set to approve on its own accepts
  without you. Either way, a git hook or git config it wrote is never
  applied, and a link that leads out of the project is refused. The
  sandbox does not hide the whole machine: section 6 names what a step
  can still read.
- The microphone opens only on your `Esc v` or `spark voice listen`,
  never on a wake word. The recording is deleted once it is written
  out, and the voice sends nothing anywhere.
- What spark depends on is one command. `spark ver --sbom` prints a
  software bill of materials as CycloneDX 1.5 JSON: every component
  this tree pins, with versions and sha256s. Every release carries it
  as `sbom.cdx.json`. `spark ver --credits` names who made spark and
  what it uses, and `CREDITS.md` names the rest. The `pending` row of
  `spark check` counts the security upgrades your package manager holds
  back and warns while any waits.

What leaves is counted, never read. Every request's size and
destination ride its turn record, as a number and a host. `spark stats
--sends` prints them by destination and day for the last week. The
`sends` row of `spark check` warns the day any bytes went to a host
other than the server you chose.

## How it fits together

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

spark check   39 rows: every promise the machine makes, fixture-tested
spark update  the newest signed tag, or main on a developer clone; converge

what leaves the machine: pinned downloads in, your questions to the
server you chose, nothing else -- no telemetry, no account, one LAN address.
```
