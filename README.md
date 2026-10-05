# spark

<img src="assets/banner.svg" alt="spark" width="400">

A local AI for your shell. It runs on your own machine, with no account
and no cloud.

```
~ > files bigger than 1G modified this week?          <- type it, press Enter
* Finds files >1G modified in last 7 days.              <- the hint
~ > find . -type f -size +1G -mtime -7                  <- the command, in your line
```

Nothing runs until you press `Enter` again. A command that deletes is
marked `!`.

## Install

1. Install the basics:

   ```sh
   # Debian 13 / Ubuntu 24.04 or newer
   sudo apt-get update && sudo apt-get install -y git curl python3 openssh-client
   # Arch Linux
   sudo pacman -S --needed git curl python openssh
   # Void Linux
   sudo xbps-install -Sy git curl python3
   # Fedora
   sudo dnf install -y git openssh-clients python3 curl
   # openSUSE Tumbleweed
   sudo zypper install -y git openssh-clients python3 curl
   # macOS
   xcode-select --install
   ```

   Windows: run `wsl --install -d Ubuntu-24.04` in PowerShell, then the
   Debian line inside Ubuntu.

2. Install spark:

   ```sh
   curl -fsSL https://github.com/forgewright-ai/spark/releases/latest/download/get | sh
   ```

   It asks three questions, then downloads a model. This takes about
   10 minutes. To read the script first:

   ```sh
   curl -fsSLO https://github.com/forgewright-ai/spark/releases/latest/download/get
   sh get
   ```

3. Open a new shell and check:

   ```sh
   exec $SHELL
   spark check
   ```

spark adds one line to your rc file. Setup asks before it adds its
keys. `spark keys` lists them, moves one, or turns them all off. With
the keys off, `? words` still works. `docs/INSTALL.md` has the
details.

## Use it

```
? how big is this dir           a command for your line
cmd 2>&1 | explain              what went wrong, and the fix
spark chat                      talk with the model
```

- `spark do WORDS`: a task, one confirmed command at a time.
- `spark ask`, `spark read`, `spark drill`, `spark watch`: work with a
  text.
- `spark model list`: the models and their licenses.
- `spark serve on`: use this machine's model from a browser or another
  machine.
- `spark voice on`: spark reads aloud.
- `spark awaken`: give spark a personality and a look.
- `spark check`: is spark ok, and what to fix. Your prompt says when
  something breaks. `spark status` is the full report.
- `spark uninstall` removes spark from this machine.

Every command is in `docs/CHEATSHEET.txt`.

## A first hour

Some of these need an app from the next section. `Alt-s` is Option-s
on a Mac.

1. `? what is eating my disk`: a command lands in your line. `Enter`
   runs it.
2. Run a command with a typo, such as `git pushh`. Press `Esc s` on the
   empty line for the reason, and again for the fix.
3. `?? how do I change the model`: follow up on the last answer.
4. In micro with spark-micro, open an empty file, press `Alt-s` and
   type `a short poem about this machine`.
5. Press `Alt-s`, then `?` alone: a review opens beside your text.
6. Select a stanza, press `Alt-s` and type `make it rhyme`. `Ctrl-Z`
   undoes it.
7. `spark edit --watch poem.md` in a second terminal comments on each
   save.
8. `man ls | spark read how do I sort by size`: an answer that quotes
   the page.
9. `spark drill --name spark < ~/.spark/docs/CHEATSHEET.txt`: practise
   the commands.
10. `journalctl -f | spark watch anything that fails`, on Linux: one
    line when a line matches.
11. `spark awaken`: a personality, and a face that waits, answers and
    rests above your prompt. `spark look off` turns them off.
12. `spark memory add "short answers"`, then `spark chat`. In the chat,
    `/read @notes.txt what is due` answers from the file.
13. `spark serve --login`: open the address on your phone. The traffic
    is plain HTTP, so use a network you trust.

## Apps

An app is an editor or a tool that calls spark. Each one has its own
repository, and its `README.md` says how to install it. In most apps,
`Alt-s` opens a `spark>` prompt.

Editors:

- [spark-micro](https://github.com/forgewright-ai/spark-micro): micro.
- [spark-neovim](https://github.com/forgewright-ai/spark-neovim): neovim.
- [spark-vim](https://github.com/forgewright-ai/spark-vim): vim.
- [spark-helix](https://github.com/forgewright-ai/spark-helix): helix.
- [spark-nano](https://github.com/forgewright-ai/spark-nano): nano.

Any editor that can filter text works without one. In vim:
`:'<,'>!spark edit fix the spelling`.

Readers:

- [spark-w3m](https://github.com/forgewright-ai/spark-w3m): w3m.
- [spark-newsboat](https://github.com/forgewright-ai/spark-newsboat):
  newsboat.
- [spark-aerc](https://github.com/forgewright-ai/spark-aerc): aerc.

Tasks:

- [spark-acp](https://github.com/forgewright-ai/spark-acp): Toad, Zed
  or another Agent Client Protocol client. Each command is a Run or a
  Skip. A client set to approve on its own runs commands with no
  person checking.

## Documents

- `docs/INSTALL.md`: install, models, other machines, updates.
- `docs/CHEATSHEET.txt`: every command on one page.
- `docs/CHANGELOG.md`: what each release changed.
- `docs/ROADMAP.md`: what comes next.
- `docs/CONTRIBUTING.md`: how to send a change.

## What leaves this machine

Your words go to the model's server. It runs on this machine, or on
another machine of yours (`spark client URL`). The same command uses
a `llama-server` you already run, and `spark setup --engine URL` does
it on a new install. What each command sends:

- `line`: the line you typed, your shell, your OS and the folder's
  path. With a question, the matching lines of your manuals, 600
  characters at most.
- `chat`: your soul, your remembered facts and the conversation.
- `do`: each step's output (the last 4 kB) and the folder's path. After
  a refused option, a few lines of that command's man page.
- `explain`: the piped text, the last 6 kB.
- `@FILE`: the file's first 4 kB and last 12 kB.
- `edit`: the file's name and up to 16 kB of its text.
- `ask`: the text, up to 12 kB.
- `read` and `drill`: the source, 16 kB at a time.
- `watch`: the stream, 8 kB at a time.
- `recall` (`Esc r`): the last 400 lines of your shell history, with
  secrets replaced by `[held]`.
- `paste`: a paste of several lines, up to 8 kB. A paste that looks
  like a secret is not sent.
- `awaken`: the temperament you chose, once.

`read`, `do`, `recall` and `edit ? --source` replace secrets with
`[held]`. They
catch a private key, an AWS access key, a GitHub token, a Slack token
and an API key. They also catch a credential line, a long base64 run, a
one-time code and a link token. The other commands send the text as it
is.

Between machines, the traffic is plain HTTP. Anyone on your network can
read it.

spark downloads itself, the llama.cpp engine and the voice from
github.com, and your model from huggingface.co. The engine, the voice
and the model are checked by sha256. Your package manager installs the
basics and checks for updates. There is no telemetry.

A release is signed. A first install checks it against the key inside
`get`. Each update checks against the key already installed, and only
moves forward. A clone on `main` is not checked.

## On this machine

- The server listens on one LAN address and needs a token.
- The admin token can run commands on this machine. With passwordless
  sudo, that means root.
- Conversations are kept for 30 days in `~/.local/state/spark/`.
  `SPARK_HISTORY=off` keeps none, and none of the check's changes.
- Each user (`spark user add NAME`) has an encrypted store that only
  their token opens. A lost token cannot be recovered.
- Your own login keeps its key next to its store. Encrypt the disk to
  protect it.

## License

MIT, in `LICENSE`. spark comes with no warranty. A model can be wrong,
so what you run or accept is at your own risk. What spark downloads, and
each license, is in `CREDITS.md`. It also names the one file here
under another license. Built with Claude.
