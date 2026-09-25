# spark apps

An app becomes a spark app by being a client of one spark verb:
`spark edit` for text you write, `spark read` for text you read and
`spark do` for a task. Each app's plugin lives in its own
`spark-<app>` repository and installs the app's way. spark ships no
app.

This document is not tied to a spark release. It is kept true as
things change, but it is outside the landing rule. Nothing here has to
appear in `spark help`, `docs/CHEATSHEET.txt` or a `docs/CHANGELOG.md`
entry, and no release waits on it.

| | |
|---|---|
| [spark-micro](https://github.com/forgewright-ai/spark-micro) | micro: `Alt-s` opens `spark> ` |
| [spark-neovim](https://github.com/forgewright-ai/spark-neovim) | neovim: your key opens `spark> ` |
| [spark-vim](https://github.com/forgewright-ai/spark-vim) | vim: your key opens `spark> ` |
| [spark-helix](https://github.com/forgewright-ai/spark-helix) | helix: `A-s` pre-fills helix's prompt |
| [spark-nano](https://github.com/forgewright-ai/spark-nano) | nano: `M-S` pre-fills nano's prompt |
| [spark-w3m](https://github.com/forgewright-ai/spark-w3m) | w3m: `M-s` opens the w3m page: chat, overview, questions |
| [spark-newsboat](https://github.com/forgewright-ai/spark-newsboat) | newsboat: `,s` asks about the article you are on |
| [spark-aerc](https://github.com/forgewright-ai/spark-aerc) | aerc: `A-s` opens `spark> ` on the mail you are on |
| [spark-acp](https://github.com/forgewright-ai/spark-acp) | Toad, Zed, any ACP client: `spark do` there, each command a Run or a Skip |

## One key, one grammar

One key in every editor and reader summons spark on what is in front
of you. The key is `Alt-s` (Option-s on a Mac). Each tool spells it
its own way: `M-s` in w3m, `A-s` in helix and aerc, `M-S` in nano. In
newsboat the key is `,s`. spark-acp has no key: its client's Run and
Skip are the whole of it.

One grammar answers the key. At `spark> `, `Enter` does the surface's
default: it completes at the cursor where you write and gives the
overview where you read. Words do the natural act: they rewrite where
you write and ask where you read. `? words` asks anywhere. helix and
nano have no cursor hook, so their key puts `spark edit ` on the
editor's own prompt instead. Add words and press `Enter`.

## The editors: micro, neovim, vim, helix and nano

`spark edit` is the editors' verb. The text goes in on stdin and the
text comes out, never a path. micro is the first app. Clone the
plugin:

```sh
git clone https://github.com/forgewright-ai/spark-micro ~/.config/micro/plug/spark
```

Add one line to `~/.config/micro/bindings.json`:
`"Alt-s": "lua:spark.prompt"`. Then `Alt-s` opens `spark> `. `Enter`
alone completes at the cursor. Words rewrite the selection or the
file. `? words` asks in a pane, `?` alone reviews and `??` goes on. In
the pane, `Enter` jumps to a quote, `a` applies a code block, `d`
declines a note for good and `q` closes. `help spark` inside micro
says everything. `setlocal spark.about "a novel chapter"` tells spark
what a buffer is. `git -C ~/.config/micro/plug/spark pull` updates the
plugin.

neovim and vim carry micro's whole prompt: `spark> `, the pane and its
keys, the ledger and the splice safety. Each is one clone and one
mapping, and `:help spark` inside the editor says the rest.

neovim 0.9 or newer:

```sh
git clone https://github.com/forgewright-ai/spark-neovim ~/.config/nvim/pack/spark/start/spark
```

Then one line in `init.lua`:

```lua
vim.keymap.set({ "n", "x" }, "<M-s>", function() require("spark").prompt() end)
```

vim 8.2 or newer, the usual huge build:

```sh
git clone https://github.com/forgewright-ai/spark-vim ~/.vim/pack/spark/start/spark
```

Then three lines in `~/.vimrc`. The first teaches terminal vim the
key:

```vim
execute "set <M-s>=\es"
nnoremap <M-s> :call spark#prompt(0)<CR>
xnoremap <M-s> :<C-u>call spark#prompt(1)<CR>
```

helix and nano are one clone each, and the snippet's comment block is
the help. helix 25.01 or newer:

```sh
git clone https://github.com/forgewright-ai/spark-helix ~/.config/helix/spark
```

Then paste the two key blocks of `spark.toml` into `config.toml`
(`:config-open`, paste, `:config-reload`). `A-s r` rewrites the file,
`A-s s` the selection and `A-s a` asks (`u` removes the answer).
`A-s f` fixes spelling in one keystroke.

nano 5.4 or newer:

```sh
git clone https://github.com/forgewright-ai/spark-nano ~/.config/nano/spark
cat ~/.config/nano/spark/spark.nanorc >> ~/.nanorc
```

`M-S words` rewrites the file or the marked region (`M-U` undoes).
`M-F` fixes spelling in one keystroke.

An editor with a filter needs no plugin. The selection goes through
`spark edit`, or the whole file when nothing is selected:

| editor | rewrite the selection | ask about it |
|---|---|---|
| vim | `:'<,'>!spark edit fix the spelling` | `:'<,'>w !spark edit \? is this clear` |
| helix | `\|spark edit fix the spelling` | `\|spark edit ? is this clear` |
| nano | mark, `^T`, `\|spark edit fix the spelling` | `^T`, `\|spark edit ? is this clear` |

In vim the `\?` keeps zsh from reading a bare `?` as a pattern. In
helix and nano the answer replaces the selection, and `u` or `M-U`
takes it back. A filter cannot complete at the cursor: that needs a
plugin.

Coming from spark v1.9, where the plugin came with spark: `spark
update` hands the old links back, and its `micro` row says so. Then
clone as above. Another editor joins the same way: one client of
`spark edit`, in a repository of its own.

## The readers: w3m, newsboat and aerc

`spark read` is the readers' verb, since spark 1.20. The source goes
in on stdin, and the answer says only what the source says: every line
quotes it, and the quote is checked. w3m is the first reader:

```sh
git clone https://github.com/forgewright-ai/spark-w3m ~/.w3m/spark
ln -s ~/.w3m/spark/spark-w3m ~/.local/bin/spark-w3m
cat ~/.w3m/spark/keymap.spark >> ~/.w3m/keymap
printf 'cgi_bin %s/.w3m/spark\n' "$HOME" >> ~/.w3m/config
```

`M-s` stashes the web page you are reading and opens the w3m page, a
small place of w3m's own. The `chat>` field is a conversation:
follow-ups ride the thread, and the w3m page re-renders as the log.
`overview` and the part links are `spark read`, framed. `questions` is
`spark ask`: what the web page does not answer, each question a link
that asks itself. A quit word never reaches the model, and `B` is two
presses from any depth. The verb works from any shell without a
plugin:

```sh
w3m -dump https://example.com | spark read "what is this page for"
```

newsboat, the RSS reader, is the second. It reads the article you are
on, open or selected in the list:

```sh
git clone https://github.com/forgewright-ai/spark-newsboat ~/.newsboat/spark
ln -s ~/.newsboat/spark/spark-newsboat ~/.local/bin/spark-newsboat
cat ~/.newsboat/spark/config.spark >> ~/.newsboat/config
```

`,s` is newsboat's macro prefix and then `s`. It opens the article's
room on the terminal newsboat hands over: the header, then `chat> `.
`Enter` alone is the overview, every line quoting the article, or an
honest refusal. Words are a conversation about it: follow-ups ride the
thread, and an unheld quote is marked where it stands. `q` walks back
to newsboat at any time. On newsboat 2.38 or newer a commented bind
line in the snippet offers `Alt-s`.

aerc, the mail client, is the third. It reads the mail you are on,
open or selected in the list. A mail is someone else's text, so spark
1.46 or newer holds back what looks like a secret in it before it
leaves. That is a one-time code, a reset link's token or a key. The
model sees `[held]`, and spark says how many it held.

```sh
git clone https://github.com/forgewright-ai/spark-aerc ~/.local/share/spark-aerc
ln -s ~/.local/share/spark-aerc/spark-aerc ~/.local/bin/spark-aerc
```

Then append `binds.spark` to aerc's `binds.conf`, under
`~/.config/aerc` on Linux and `~/Library/Preferences/aerc` on macOS.
Start from aerc's own file when you have none. The repository's
`README.md` has each line. `A-s` opens the mail's header on a new tab,
then `spark> `: `Enter` is the overview, words ask and `q` goes back
to aerc. On the review screen, before you send, `A-s` asks about your
own draft, and the lines you quote stay here. Writing a mail is your
editor's job. With micro, neovim or vim and its spark app, `Alt-s` is
already there.

## The task client: spark-acp

`spark do --porcelain` is the task verb for a program, since spark
1.47. spark-acp speaks it to any Agent Client Protocol client, Toad in
a terminal or Zed in the editor:

```sh
git clone https://github.com/forgewright-ai/spark-acp ~/.local/share/spark-acp
ln -s ~/.local/share/spark-acp/spark-acp ~/.local/bin/spark-acp
toad acp "spark-acp"
```

Each command the model proposes is a Run or a Skip in the client.
Outside the sandbox, spark refuses two kinds of command through a
client and says so. One can destroy data. The other's effect cannot be
read from the line: a command substitution, `eval`, code handed to an
interpreter or an upload. Those run at a terminal with `spark do`.
Anything else runs on your Run, as you. In the sandbox mode every
command runs in a copy of the directory, those two kinds included, and
the diff comes back once, to Accept or Discard. The diff is the gate:
Accept applies exactly what the diff showed. A client set to approve
on its own answers Run and Accept without you. In the sandbox mode its
commands still run in the copy, with no network. The repository's
`README.md` has Zed's lines.

## The protocol

Every app is a client of one verb, and `spark <verb> -h` says the
rest. When an app needs more than text, another contract is defined,
and apps connect to it the same way.

`spark edit` (contract 10): the text on stdin, raw text out, never a
path. `--at N` completes at a byte offset. Words rewrite the text,
12000 characters at most. `? [words]` asks or reviews. An empty text
with words is written from nothing. `--type`, `--name` and `--about`
are hints. There is no thread unless the app asks with `--thread ID`,
and that thread is sealed like a chat thread.

`spark read` (contract 11): the source on stdin, the answer out, every
line quoting the source. `--part N` reads one part of a long source.
`spark edit ? --source` is the same reading for a question an app asks
about a source, and it holds a secret back the same way.

`spark do --porcelain` (contract 15): one command at a time as JSON
lines, and one word back when something waits: run, skip, quit, edit,
accept or discard. `--sandbox` runs every step in a copy of the
directory.
