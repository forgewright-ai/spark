# spark apps

This document is not tied to a spark release. It is kept up to date
as the apps change.

A spark app is an editor or a tool that calls spark. Each one lives in
its own repository and installs the app's way. spark ships no app.
Each repository's `README.md` has the details.

In most apps `Alt-s` (Option-s on a Mac) opens a `spark> ` prompt.
`Enter` alone completes or gives an overview. Words rewrite or ask.
`? words` asks.

## Editors

spark-micro, for micro:

```sh
git clone https://github.com/forgewright-ai/spark-micro ~/.config/micro/plug/spark
```

Add `"Alt-s": "lua:spark.prompt"` to `~/.config/micro/bindings.json`.
`help spark` in micro lists the keys.

spark-neovim, for neovim 0.9 or newer:

```sh
git clone https://github.com/forgewright-ai/spark-neovim ~/.config/nvim/pack/spark/start/spark
```

Add to `init.lua`:

```lua
vim.keymap.set({ "n", "x" }, "<M-s>", function() require("spark").prompt() end)
```

spark-vim, for vim 8.2 or newer:

```sh
git clone https://github.com/forgewright-ai/spark-vim ~/.vim/pack/spark/start/spark
```

Add to `~/.vimrc`:

```vim
execute "set <M-s>=\es"
nnoremap <M-s> :call spark#prompt(0)<CR>
xnoremap <M-s> :<C-u>call spark#prompt(1)<CR>
```

spark-helix, for helix 25.01 or newer:

```sh
git clone https://github.com/forgewright-ai/spark-helix ~/.config/helix/spark
```

Paste the two key blocks of `spark.toml` into `config.toml`. `A-s r`
rewrites the file, `A-s s` the selection, and `A-s a` asks.

spark-nano, for nano 5.4 or newer:

```sh
git clone https://github.com/forgewright-ai/spark-nano ~/.config/nano/spark
cat ~/.config/nano/spark/spark.nanorc >> ~/.nanorc
```

`M-S words` rewrites the file or the marked text. `M-U` undoes.

Any editor that can filter text works without a plugin. In vim:
`:'<,'>!spark edit fix the spelling`.

## Readers

spark-w3m, for w3m:

```sh
git clone https://github.com/forgewright-ai/spark-w3m ~/.w3m/spark
ln -s ~/.w3m/spark/spark-w3m ~/.local/bin/spark-w3m
cat ~/.w3m/spark/keymap.spark >> ~/.w3m/keymap
printf 'cgi_bin %s/.w3m/spark\n' "$HOME" >> ~/.w3m/config
```

`M-s` opens a page to chat about the web page you are reading.

spark-newsboat, for newsboat:

```sh
git clone https://github.com/forgewright-ai/spark-newsboat ~/.newsboat/spark
ln -s ~/.newsboat/spark/spark-newsboat ~/.local/bin/spark-newsboat
cat ~/.newsboat/spark/config.spark >> ~/.newsboat/config
```

`,s` asks about the article you are on.

spark-aerc, for aerc:

```sh
git clone https://github.com/forgewright-ai/spark-aerc ~/.local/share/spark-aerc
ln -s ~/.local/share/spark-aerc/spark-aerc ~/.local/bin/spark-aerc
```

Append `binds.spark` to aerc's `binds.conf`. `A-s` asks about the
mail you are on. spark holds back what looks like a secret in the mail
before the model sees it.

## Tasks

spark-acp, for Toad, Zed or another Agent Client Protocol client:

```sh
git clone https://github.com/forgewright-ai/spark-acp ~/.local/share/spark-acp
ln -s ~/.local/share/spark-acp/spark-acp ~/.local/bin/spark-acp
toad acp "spark-acp"
```

Each command spark proposes is a Run or a Skip in the client. A client
set to approve on its own runs commands, and accepts their changes,
with no person checking. In the sandbox mode the commands still run
in a copy, offline.
