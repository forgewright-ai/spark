# spark

<img src="assets/banner.svg" alt="spark" width="400">

Your own AI, on a machine you own: no account, no cloud, nothing leaves.
One line installs it. Then ask at the prompt:

```
~ > files bigger than 1G modified this week?          <- type it, press Enter
* Finds files >1G modified in last 7 days               <- the hint, above the prompt
~ > find . -type f -size +1G -mtime -7                  <- the command, in your line
```

Nothing runs until you press Enter again. A command that deletes comes
back marked `!`.

## Install

1. Once, on a bare machine:

   ```sh
   # Debian 13 / Ubuntu 24.04 or newer
   sudo apt-get update && sudo apt-get install -y git curl python3
   # Arch Linux
   sudo pacman -S --needed git curl python
   # macOS
   xcode-select --install
   ```

   Windows: `wsl --install -d Ubuntu-24.04` in PowerShell, then the
   Debian line inside Ubuntu.

2. One line, any OS:

   ```sh
   curl -fsSL https://raw.githubusercontent.com/forgewright-ai/spark/main/get | sh
   ```

   It asks three things -- this machine's name, yours, the model -- and
   asks the first question for you. About ten minutes, most of it one
   download. To read it first:
   `curl -fsSLO https://raw.githubusercontent.com/forgewright-ai/spark/main/get; sh get`

3. Open a new shell:

   ```sh
   exec $SHELL
   spark check
   ```

One line goes into your rc file, nothing else: your shell, your colours
and your editor stay yours. `INSTALL.md` has every step and every key.

## Use it

| | |
|---|---|
| `? words` at the prompt | the command lands in your line; `??` follows up; `Esc s` asks about the line you are on |
| `cmd 2>&1 \| explain` | what went wrong, and the fix |
| `spark chat` | a conversation; `/help` lists its verbs |
| `spark <words>` | one answer, streamed; `spark @FILE words` reads a file |
| `spark do <words>` | a task, one confirmed command at a time |
| `spark soul edit` | who it is; `spark remember <words>` adds a fact it keeps |
| `spark model list` | 26 models, each with its license; `spark model NAME` serves one |
| `spark ember NAME` | a second, bigger model for conversations |
| `spark forge --print-url` | the same AI in a browser, on the LAN; on a phone, add it to the home screen |
| `spark client URL` | another machine of yours uses this one's AI, no model of its own |
| `spark headless on` | keeps it up from boot, on the machine that stays on |
| `spark check` | every promise this machine makes, one row each; exit 0 when all are kept |
| `spark off` | Enter is a plain Enter again; `spark on` brings it back |
| `spark uninstall` | takes it all off; keeps your prose and your threads |

## spark apps

A tool becomes smart as a client of one command, `spark edit`: text in
on stdin, text out, never a path. Five editors have a plugin today, each
in its own `spark-<app>` repository, installed the app's way; spark
ships no app. micro is first:

```sh
git clone https://github.com/forgewright-ai/spark-micro ~/.config/micro/plug/spark
```

plus one line in `~/.config/micro/bindings.json`: `"Alt-s": "lua:spark.prompt"`.
Then `Alt-s` (Option-s on a Mac): Enter completes at the cursor, words
rewrite, `?` asks in a pane. neovim and vim carry the same prompt under
one key of your own -- https://github.com/forgewright-ai/spark-neovim
and https://github.com/forgewright-ai/spark-vim. helix and nano cannot
hook the cursor, so their plugins put `spark edit ` on the editor's own
prompt instead -- https://github.com/forgewright-ai/spark-helix and
https://github.com/forgewright-ai/spark-nano: add words, press Enter,
and the text is rewritten or asked about. INSTALL section 6 has each
app's lines; an editor with a filter is a client with no plugin at all.

When apps need more than text, another contract is defined -- e-mail,
for example -- and apps connect to it the same way.

## Also

`spark shell on` gives a machine that is only an AI box spark's own
shell: tmux, starship, fzf, eza, bat, btop, zoxide, the Nerd Font, one
palette on every surface. Off by default; `spark shell off` hands
everything back. `INSTALL.md` section 9.

The page: https://spark.forgewright.ai -- the docs and the model list.

## What leaves this machine

Only to the server you configured (this machine's, or another of yours):

- the line you typed, with the shell and OS name;
- the directory's path where a command is proposed (the prompt line,
  `do`, `explain`) -- never its contents; a conversation sends no path;
- in a conversation, your soul, your remembered facts and the thread's
  earlier turns;
- for `explain` the piped text (last 6 kB); for `@FILE` its first 4 kB
  and last 12 kB under the name you typed; for `spark do` each step's
  output (last 4 kB);
- from an editor (`spark edit`), the file's name and its text: 6 kB
  around the cursor for a completion, 12 kB for a rewrite, 16 kB for a
  question -- never its path; a thread only when the editor asks for
  one, sealed like a chat thread.

No telemetry, no analytics, no crash reports, no account. Downloads:
`get` from raw.githubusercontent.com and the clone from github.com, one
pinned llama.cpp release (sha256) from github.com, the model you chose
from huggingface.co (size and sha256 in `models.env`). Nothing else.

On this machine: the server binds one LAN address, never `0.0.0.0`,
behind 0600 tokens that are never printed. Turns and threads live 30
days under `~/.local/state/spark/` (`SPARK_HISTORY=off` keeps none);
turns are numbers, never words. Each named user (`spark user add NAME`)
has a sealed store -- ChaCha20-Poly1305, written from RFC 8439 -- under
a key only that user's token opens: the admin cannot read it, a stolen
disk is ciphertext, a lost token is lost history. There is no reset.

## License

MIT (`LICENSE`). Everything spark downloads is pinned and named in
`CREDITS.md` with its license. Built with Claude.
