# spark

<img src="assets/banner.svg" alt="spark" width="400">

Your own AI, on a machine you own: no account, no cloud, nothing leaves.
One line installs it. Then ask at the prompt line:

```
~ > files bigger than 1G modified this week?          <- type it, press Enter
* Finds files >1G modified in last 7 days               <- the hint, above the prompt
~ > find . -type f -size +1G -mtime -7                  <- the command, in your line
```

Nothing runs until you press `Enter` again. A command that deletes comes
back marked `!`. A recursive `rm` says how many files and bytes it would
clear, and how many of them git tracks. spark works that out from the
command itself and runs nothing.

## Install

1. Once, on a bare machine:

   ```sh
   # Debian 13 / Ubuntu 24.04 or newer
   sudo apt-get update && sudo apt-get install -y git curl python3 openssh-client
   # Arch Linux
   sudo pacman -S --needed git curl python openssh
   # Void Linux
   sudo xbps-install -Sy git curl python3 openssh
   # macOS
   xcode-select --install
   ```

   Windows: `wsl --install -d Ubuntu-24.04` in PowerShell, then the
   Debian line inside Ubuntu.

2. One line, any OS:

   ```sh
   curl -fsSL https://github.com/forgewright-ai/spark/releases/latest/download/get | sh
   ```

   It asks 3 things: this machine's name, yours and the model. Then
   it asks the first question for you. About 10 minutes, most of it
   one model download. To read the script first:

   ```sh
   curl -fsSLO https://github.com/forgewright-ai/spark/releases/latest/download/get
   sh get
   ```

3. Open a new shell:

   ```sh
   exec $SHELL
   spark check
   ```

One line goes into your rc file, nothing else. Your shell, your colours
and your editor stay yours. `docs/INSTALL.md` has every step and every
key.

## Use it

The first 3 things to type:

```
? how big is this dir           a command in your line, a hint above it
cmd 2>&1 | explain              what went wrong, and the fix
spark chat                      a conversation; /help lists its verbs
```

Then the rest, one line each in `docs/CHEATSHEET.txt`, and a first
hour in `docs/TOUR.md`:

- `spark do <words>`: a task, one confirmed command at a time. With
  `--sandbox` it runs in a copy, and you apply the diff with `yes`.
- `spark ask`, `spark read`, `spark drill`, `spark watch`: questions a
  text does not answer, what a source says, practice from a source,
  and a live stream watched for one thing. Every line quotes the
  source.
- `spark model list`: 26 models, each with its license. `spark ember
  NAME` adds the chat model, a bigger second one.
- `spark forge --print-url`: the same model, soul and memory in a
  browser on the LAN, and on a phone that scans the QR. `spark client
  URL` lets another machine of yours use this one's model.
- `spark check`: every promise this machine makes, one row each. It
  exits 0 when no row fails. `spark uninstall` takes it all off.

## Documents

Four files sit at the root: this one, `CREDITS.md`, `CLAUDE.md` and
`AGENTS.md`. The rest live in `docs/`. Five move with each release:

- `docs/INSTALL.md`: every step and every key.
- `docs/CHEATSHEET.txt`: one page (`lp ~/.spark/docs/CHEATSHEET.txt`).
- `docs/CHANGELOG.md`: what each release changed.
- `docs/ROADMAP.md`: what comes next.
- `docs/CONTRIBUTING.md`: how to send a change, and the voice.

Four are kept true as things change, outside a release:

- `docs/TOUR.md`: a first hour, 12 small things to try.
- `docs/APPS.md`: editors and tools that speak to spark.
- `docs/IDEAS.md`: the field the roadmap is picked from.
- `docs/TROUBLESHOOTING.md`: a machine that will not join the Wi-Fi.

The project site, spark.forgewright.ai, shows the docs and the model
list at the newest release.

## What leaves this machine

Your words go to one place: the server on this machine, or the one on
another machine of yours (`spark client URL`). What each verb sends:

- `line` (the prompt line): the line you typed, with the shell and OS
  name, and the directory's path. Never the directory's contents.
- `chat`: your soul, your remembered facts and the thread's earlier
  turns. A conversation sends no path.
- `do`: each step's output, the last 4 kB, and the directory's path.
  After a step refused for an option, the lines of that command's man
  page about it, 1.5 kB at most. spark reads the page itself, and the
  command never runs for it.
- `explain`: the piped text, the last 6 kB, and the directory's path.
- `@FILE`: the file's first 4 kB and last 12 kB, under the name you
  typed.
- `edit` (from an editor): the file's name and its text: 6 kB around
  the cursor for a completion, 12 kB for a rewrite, 16 kB for a
  question. Never its path. `--watch` sends each saved stanza the same
  way.
- `ask`: the text, 12 kB, with the `--name` and `--about` hints you
  gave.
- `read`: the source, 16 kB a part. `--name` stays here, in the ledger.
- `drill`: the source, 16 kB. Your answers are graded here, against the
  source, and never sent.
- `watch`: each window of the stream, up to 40 lines or 10 seconds,
  8 kB at most. Never the whole stream at once.
- `recall` (`Esc r`): the last 400 lines of this shell's own history,
  with what you said the command did.
- `paste`: a multi-line paste into an empty prompt, 8 kB at most. A
  bigger paste is not sent. A paste shaped like a secret is not sent.

Before a source, a step's output or an editor's question about a source
leaves, spark holds back every span that looks like a secret. It holds
back a private key, an AWS access key, a GitHub token, a Slack token
and an API key. It also holds back a credential line, a long base64
run, a one-time code and a link token. The model sees `[held]` in its
place. spark's own tokens are held back the same way.

No telemetry, no analytics, no crash reports, no account. Downloads:
`get` and the clone from github.com, one pinned llama.cpp release from
github.com with its sha256, and the model you chose from huggingface.co.
Its size and sha256 are in `models.env`. Nothing else.

On this machine: the server binds one LAN address, never `0.0.0.0`,
behind tokens kept at 0600. A token is shown once, when you ask
(`spark forge --print-url`, `spark user add`). Turns and threads live
30 days under `~/.local/state/spark/` (`SPARK_HISTORY=off` keeps none).
A turn record holds numbers, never words. Each named user
(`spark user add NAME`) has a sealed store. Its cipher is
ChaCha20-Poly1305, written from RFC 8439, under a key only that user's
token opens. The admin cannot read it. A stolen disk is ciphertext. A
lost token is lost history. There is no reset.

## License

MIT, in `LICENSE`. Everything spark downloads is pinned and named in
`CREDITS.md` with its license. Built with Claude.
