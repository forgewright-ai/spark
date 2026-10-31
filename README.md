# spark

<img src="assets/banner.svg" alt="spark" width="400">

A local AI for your shell. It runs a model on your own machine by
default, with no account or telemetry. If you configure another model
server, it receives the text you send. [What leaves this
machine](#what-leaves-this-machine) has details.

```
~ > files bigger than 1G modified this week?          <- type it, press Enter
* Finds files >1G modified in last 7 days.              <- the hint
~ > find . -type f -size +1G -mtime -7                  <- the command, in your line
```

Nothing runs until you press `Enter` again. A command that deletes is
marked `!`.

## Install

Use a computer you already use; installing spark does not reinstall its
OS or erase a disk. It supports Debian/Ubuntu, Arch, Void (glibc),
Fedora and openSUSE Tumbleweed Linux, macOS, and Windows through WSL 2
with Ubuntu. Use zsh or bash 4 or newer (zsh on macOS), on an x86-64
or ARM64 machine with a supported engine. You need `git`, `curl`,
Python 3.9 or newer and `ssh-keygen`, and `sudo` unless the machine is
a client of another machine's model.

Before starting, allow room for a model download: the listed files
range from 1.3 to 17.4 GB and need a separate 3 to 21 GB model memory
budget. That budget is not the whole machine's RAM. Leave more
free disk space than the model file for the engine and setup. A CPU
works without a GPU; download and setup time depend on your connection
and machine. [Model sizes and choices](docs/INSTALL.md#4-models) has
details.

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

   This is the signed-release installer. It asks setup questions and
   downloads a model. Time varies with the download and your machine.
   To read the script first:

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

Config files use `KEY=value`. Non-empty environment values win over
`spark.env`, then `site.env`, then defaults. Within each file, the first
non-empty value wins. See `docs/INSTALL.md` for quoting and comments.

## Use it

```
? how many files are here       a command for your line
cmd 2>&1 | explain              what went wrong, and the fix
spark chat                      talk with the model
```

- `spark do WORDS`: a task, one confirmed command at a time.
- `spark ask`, `spark read`, `spark drill`, `spark watch`: work with a
  text.
- `spark model list`: the models and their licenses.
- `spark mcp`: the tools of the MCP servers you put on its list, such
  as the parts of a desktop. A tool that can destroy asks you first.
- `spark serve on`: use this machine's model from a browser or another
  machine. [Read about network access](#on-this-machine) before sharing.
- `spark voice on`: spark reads aloud.
- `spark awaken`: give spark a personality and a look.
- `spark check`: is spark ok, and what to fix. Your prompt says when
  something breaks. `spark status` is the full report.
- `spark uninstall` removes spark from this machine.

Every command is in `docs/CHEATSHEET.txt`.

## A first hour

No editor app, other service account or second device is needed:

1. `spark check` shows rows that need attention. A healthy check
   prints its totals line alone and exits 0.
2. `spark chat` and ask a harmless question, such as `What is 2 + 2?`.
   Type `/q`, `Esc` or `Ctrl-D` to leave chat; `Ctrl-C` stops a reply.
3. At the shell prompt, type `? how many files are here` and press
   `Enter`. Read the proposed command in your line. Press `Ctrl-C` to
   discard it, or press `Enter` again only if you want to run it.

More to try later (some need an app from the next section; `Alt-s` is
Option-s on a Mac):

1. Run a command with a typo, such as `git pushh`. Press `Esc s` on the
   empty line for the reason, and again for the fix.
2. `?? how do I change the model`: follow up on the last answer.
3. In micro with spark-micro, open an empty file, press `Alt-s` and
   type `a short poem about this machine`.
4. Press `Alt-s`, then `?` alone: a review opens beside your text.
5. Select a stanza, press `Alt-s` and type `make it rhyme`. `Ctrl-Z`
   undoes it.
6. `spark edit --watch poem.md` in a second terminal comments on each
   save.
7. `man ls | spark read how do I sort by size`: an answer that quotes
   the page.
8. `spark drill --name spark < ~/.spark/docs/CHEATSHEET.txt`: practise
   the commands.
9. `journalctl -f | spark watch anything that fails`, on Linux: one
    line when a line matches.
10. `spark awaken`: a personality, and a face that waits, answers and
    rests above your prompt. `spark look off` turns them off.
11. `spark memory add "short answers"`, then `spark chat`. In the chat,
    `/read @notes.txt what is due` answers from the file.
12. See [Phone use](docs/INSTALL.md#5-other-machines-and-your-phone)
    before using `spark serve --login` on a phone. The QR holds an admin
    token. The page uses plain HTTP until you configure HTTPS there;
    `spark serve https` only reports certificate status.

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

- [Install guide](docs/INSTALL.md): requirements, models and updates.
- [Cheatsheet](docs/CHEATSHEET.txt): commands at a glance.
- [Changelog](docs/CHANGELOG.md): changes in each release.
- [Roadmap](docs/ROADMAP.md): planned work.
- [Contributing](docs/CONTRIBUTING.md): how to send a change.
- [Reference](docs/REFERENCE.md): the maintainer's reference.

## Bugs

Something does not match what spark promises? Open an issue with the
steps to reproduce: https://github.com/forgewright-ai/spark/issues.
GitHub issues are public. Share your version, OS and steps with made-up
names and paths. Prefer `spark check --report` for status. Review any
other output and remove private prompts, names, paths, addresses and
tokens. Never share a login QR screenshot.
An agent reads it within the hour and answers there. Questions and
ideas go to https://github.com/forgewright-ai/spark/discussions.

## What leaves this machine

Your words go to the model's server. It runs on this machine, or on
another machine of yours (`spark client URL`). The same command uses
a `llama-server` you already run, and `spark setup --engine URL` does
it on a new install. What each command sends:

- `line`: the line you typed, your shell, your OS and the folder's
  path. With a question, the matching lines of your manuals, 600
  characters at most. A picture of this machine: how the prompt runs,
  in a terminal on a desktop, a console or an ssh login. It names the
  apps and how each was installed, and which common programs are not
  installed. It names your home folders, the services that
  start at boot and the network interfaces. With MCP servers on the
  list, every tool and its arguments. From a trusted server, the first
  words of each tool's description and the values its arguments take.
  Never a file's text or a password.
- `mcp call` and a tool step of `do`: the arguments you typed or
  confirmed go to that server. It is a program on this machine, and
  may be a network client of its own: `spark stats --sends` does not
  count what it sends on. A credential it asks for goes to it alone,
  never to the model.
- `chat`: your soul, your remembered facts and the conversation, with
  the part of a file that answered each `/read` in it.
- `do`: each step's output (the last 4 kB) and the folder's path, and
  the names of the files the step changed: in `--sandbox`, every file
  that changed in the copy. After a refused option, a few lines of that
  command's man page. A tool's result, the last 4 kB. With MCP servers
  on the list, the names and titles of their tools, 1.5 kB at most.
- `explain`: the piped text, the last 6 kB.
- `steps`: your words and the tools you pipe in, their names,
  arguments and titles, up to 32 kB. Never a tool's description or a
  password.
- `@FILE`: the file's first 4 kB and last 12 kB.
- `edit`: the file's name and up to 16 kB of its text.
- `ask`: the text, up to 12 kB.
- `read` and `drill`: the source, 16 kB at a time.
- `watch`: the stream, 8 kB at a time.
- `recall` (`Esc r`): the newest commands of your shell history, each
  once and 400 at most, with secrets replaced by `[held]`.
- `paste`: a paste of several lines, up to 8 kB. A paste that looks
  like a secret is not sent.
- `awaken`: the temperament you chose, once.

`spark stats --sends` counts what left this machine, by destination
and day. The page shows the same under activity, and under a user's
settings.

`read`, `do`, `recall` and `edit ? --source` replace secrets with
`[held]`. They
catch a private key, an AWS access key, a GitHub token, a Slack token
and an API key. They also catch a credential line (in a config, an env
file or JSON), a long base64 run, a one-time code and a link token. The
other commands send the text as it is.

Setup starts the model engine, the page server and a health check. The
page listens on one LAN address with a token. Between machines, traffic
is plain HTTP until you [configure
HTTPS](docs/INSTALL.md#https-for-the-page). Anyone on your
network can read plain HTTP, including tokens. `spark serve https`
only reports certificate status.

spark downloads itself, the llama.cpp engine and the voice from
github.com, and your model from huggingface.co. The engine, the voice
and the model are checked by sha256. Your package manager installs the
basics and checks for updates. There is no telemetry.

A release is signed. A first install checks it against the key inside
`get`. Each update checks against the key already installed, and only
moves forward. A clone on `main` is not checked.

## On this machine

- The server listens on one LAN address and needs a token.
- An ordinary user's token opens that user's chat and store. The admin
  token can run commands on this machine. With passwordless sudo, that
  means root. Keep tokens and login QR codes private.
- Conversations are kept for 30 days in `~/.local/state/spark/`.
  `SPARK_HISTORY=off` keeps none, and none of the check's changes.
- Each user (`spark user add NAME`) has an encrypted store that only
  their token opens. A lost token cannot be recovered.
- Your own login keeps its key next to its store. Encrypt the disk to
  protect it.

## License

spark's code is free and open source under the [MIT license](LICENSE).
What spark downloads, and each license, is in [Credits](CREDITS.md).
It also names the one file here under another license. spark comes
with no warranty. A model can be wrong, so check what you run or
accept. Built with Claude.
