# spark apps

A tool becomes smart by being a client of a spark verb: `spark edit`
for text you are writing, `spark read` for text you are reading. spark
ships no app: each plugin lives in its own repository and installs the
app's way.

This document is not tied to a spark release. It is kept true as things
change, but it is outside the landing rule: nothing here has to appear in
`spark help`, `CHEATSHEET.txt` or a `CHANGELOG.md` entry, and no release
waits on it. It stays until the integration story is settled.

A tool becomes smart as a client of one command, `spark edit`: text in
on stdin, text out, never a path. Each app's plugin is its own
`spark-<app>` repository, installed the app's way; spark ships no app.

| | |
|---|---|
| [spark-micro](https://github.com/forgewright-ai/spark-micro) | micro: `Alt-s` opens `spark> ` |
| [spark-neovim](https://github.com/forgewright-ai/spark-neovim) | neovim: your key opens `spark> ` |
| [spark-vim](https://github.com/forgewright-ai/spark-vim) | vim: your key opens `spark> ` |
| [spark-helix](https://github.com/forgewright-ai/spark-helix) | helix: `A-s` pre-fills helix's prompt |
| [spark-nano](https://github.com/forgewright-ai/spark-nano) | nano: `M-S` pre-fills nano's prompt |
| [spark-w3m](https://github.com/forgewright-ai/spark-w3m) | w3m: `M-s` opens `spark> ` over the page |

One key in every app -- Alt-s (`M-s`, `A-s`: the same key by each
tool's name) -- summons spark on what is in front of you, and one
grammar answers it. At `spark> `: Enter does the surface's default
(complete at the cursor where you write, the overview where you read),
words do its natural act (rewrite where you write, ask where you read),
and `? words` asks anywhere. helix and nano have no cursor hook: their
key pre-fills `spark edit ` on the editor's own prompt instead -- add
words, press Enter. The rest of this file has each app's lines; an
editor with a filter needs no plugin at all.

When apps need more than text, another contract is defined -- e-mail,
for example -- and apps connect to it the same way.

## The command they all use

A tool becomes smart as a client of one command, `spark edit`: the text
on stdin, raw text out; `--at N` completes at a byte offset, `<words>`
rewrites (12 kB at most), `? [words]` asks or reviews; an empty text with
words is written from nothing; hints `--type`, `--name`, `--about`; never
a path, and no thread unless the app asks (`--thread ID`, sealed like a
chat thread). `spark edit -h` says the rest. It works from a pipe too:

```sh
spark edit fix grammar < draft.md
```

spark ships no app. Each app's plugin lives in its own repository and
installs the app's way. micro is first:

1. Clone the plugin:

   ```sh
   git clone https://github.com/forgewright-ai/spark-micro ~/.config/micro/plug/spark
   ```

2. Add one line to `~/.config/micro/bindings.json`:
   `"Alt-s": "lua:spark.prompt"`.
3. `Alt-s` (Option-s on a Mac) opens `spark> `: Enter alone completes at
   the cursor; words rewrite the selection or the file; `? words` asks in
   a pane; `?` alone reviews; `??` goes on. In the pane, Enter jumps to a
   quote, `a` applies a code block, `d` declines a note for good, `q`
   closes. `help spark` inside micro says everything; `setlocal
   spark.about "a novel chapter"` tells spark what a buffer is; `git -C
   ~/.config/micro/plug/spark pull` updates it.

neovim and vim carry micro's whole prompt -- `spark> `, the pane and its
keys, the ledger, the splice safety -- one clone and one mapping each
(each README says the rest, `:help spark` inside the editor too):

- neovim (0.9 or newer):

  ```sh
  git clone https://github.com/forgewright-ai/spark-neovim ~/.config/nvim/pack/spark/start/spark
  ```

  and one line in `init.lua`:
  `vim.keymap.set({ "n", "x" }, "<M-s>", function() require("spark").prompt() end)`.

- vim (8.2 or newer, the usual huge build):

  ```sh
  git clone https://github.com/forgewright-ai/spark-vim ~/.vim/pack/spark/start/spark
  ```

  and three lines in `~/.vimrc` (the first teaches terminal vim the key):
  `execute "set <M-s>=\es"`, `nnoremap <M-s> :call spark#prompt(0)<CR>`,
  `xnoremap <M-s> :<C-u>call spark#prompt(1)<CR>`.

helix and nano have no cursor hook: their plugins put `spark edit ` on
the editor's own prompt -- add words, press Enter; no completion there.
One clone each, and the snippet's comment block is the help:

- helix (25.01 or newer):

  ```sh
  git clone https://github.com/forgewright-ai/spark-helix ~/.config/helix/spark
  ```

  then paste `spark.toml`'s two key blocks into `config.toml`
  (`:config-open`, paste, `:config-reload`). `A-s r` rewrites the file,
  `A-s s` the selection, `A-s a` asks (`u` removes the answer), `A-s f`
  fixes spelling in one keystroke.

- nano (GNU nano 5.4 or newer):

  ```sh
  git clone https://github.com/forgewright-ai/spark-nano ~/.config/nano/spark
  cat ~/.config/nano/spark/spark.nanorc >> ~/.nanorc
  ```

  `M-S words` rewrites the file or the marked region (`M-U` undoes),
  `M-F` fixes spelling in one keystroke.

## Reading, not writing: w3m

`spark read` (spark 1.20 or newer) is the reader's verb: the source on
stdin, an answer that says only what the source says -- every line
quotes it, and the quote is checked. w3m is its first client, and the
first app outside the editors:

```sh
git clone https://github.com/forgewright-ai/spark-w3m ~/.w3m/spark
ln -s ~/.w3m/spark/spark-w3m ~/.local/bin/spark-w3m
cat ~/.w3m/spark/keymap.spark >> ~/.w3m/keymap
```

`M-s` opens `spark> ` over the page you are reading: Enter or `?`
alone is the overview (what does this page cover?), your words are
your question, and a page past 16 kB answers with its part count
(`--part 2 words` reads part 2; the answer's first line names its
part). Ctrl-C is never mind. No plugin at all still works from any
shell:

```sh
w3m -dump https://example.com | spark read "what is this page for"
```

No plugin at all still works: an editor with a filter is a client
already. The selection goes through `spark edit`, the whole file when
nothing is selected:

| editor | rewrite the selection | ask about it |
|---|---|---|
| vim | `:'<,'>!spark edit fix the spelling` | `:'<,'>w !spark edit \? is this clear` (`\?`: vim hands the line to your shell, and zsh reads a bare `?` as a pattern) |
| helix | `\|spark edit fix the spelling` | `\|spark edit ? is this clear`; the answer replaces the selection, `u` takes it back |
| nano | mark, `^T`, `\|spark edit fix the spelling` | `^T`, `\|spark edit ? is this clear`; the answer replaces the mark, `M-U` takes it back |

A filter cannot complete at the cursor: that needs a plugin -- micro's,
neovim's and vim's complete; helix's and nano's pre-fill the prompt.

Coming from spark v1.9, where the plugin came with spark: `spark update`
hands the old links back (the `micro` row says so), then clone as above.
Another editor joins the same way: one client of `spark edit`, in a
repository of its own.
