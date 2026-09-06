# spark -- credits and licenses

spark vendors none of the projects below. `bootstrap.sh` downloads each
one, pinned by version and sha256, from its own upstream to your machine
at install time; apt and Homebrew install the rest from their own
repositories. spark's own code is MIT (`LICENSE`). The banner in
`home/.config/spark/banner` is spark's own artwork.

## The engine

llama.cpp -- https://github.com/ggml-org/llama.cpp -- MIT
(c) The ggml authors

Release b10689 (`LLAMA_VERSION` in `bootstrap.sh`), six flavours (macOS
arm64, macOS x64, Linux x64, Linux x64 Vulkan, Linux arm64, Linux arm64
Vulkan), each pinned by sha256.

## The prompt

starship -- https://github.com/starship/starship -- ISC
(c) Starship Contributors

Version 1.26.0 (`STARSHIP_VERSION` in `bootstrap.sh`), pinned by sha256
on Linux; Homebrew installs the same tool on macOS with no version pin.

micro's aspell plugin, installed by `micro -plugin install aspell` from
micro's own plugin channel -- not pinned by spark; the shell layer only
(`spark shell on`).

## Fonts

JetBrains Mono -- https://github.com/JetBrains/JetBrainsMono -- SIL Open
Font License 1.1, Reserved Font Name "JetBrains Mono"

Nerd Fonts -- https://github.com/ryanoasis/nerd-fonts -- MIT (the
patcher)

Nerd Fonts patches JetBrains Mono and renames the result "JetBrainsMono
Nerd Font" -- version 3.5.1 (`NERDFONT_VERSION` in `bootstrap.sh`),
pinned by sha256 on Linux; Homebrew's font-jetbrains-mono-nerd-font cask
installs the same family on macOS with no version pin.

## Palettes

Colour values only, no code copied; MIT, each:

- Catppuccin -- https://github.com/catppuccin/catppuccin
- Gruvbox -- https://github.com/morhetz/gruvbox
- Selenized -- https://github.com/jan-warchol/selenized
- Solarized -- https://ethanschoonover.com/solarized

## Shell tools (apt / Homebrew, `spark shell on`)

None of these is shipped by spark; apt and Homebrew install them from
their own repositories, unpinned.

- bash -- GPL-3.0-or-later
- tmux -- ISC
- git -- GPL-2.0-only
- curl -- the curl license
- unzip -- Info-ZIP
- python3 -- PSF-2.0
- fontconfig -- MIT-style
- ncurses -- MIT-style
- bat -- MIT/Apache-2.0
- eza -- MIT
- fzf -- MIT
- zoxide -- MIT
- ripgrep -- MIT/Unlicense
- fd -- MIT/Apache-2.0
- jq -- MIT
- btop -- Apache-2.0
- micro -- MIT
- aspell -- LGPL-2.1-or-later
- aspell-en -- SCOWL
- shellcheck -- GPL-3.0-only (development only)
- libgomp1 -- GPL-3.0-or-later, with the GCC runtime exception
- libvulkan1 -- Apache-2.0
- mesa-vulkan-drivers -- MIT and others

## Models

Downloaded by `bootstrap.sh`, never vendored. Each row's size and sha256
come from Hugging Face's file metadata; every row in `models.env` names
its license. GGUF quantizations by bartowski and unsloth.

- Qwen3 (1.7B, 4B, 4B-Thinking, 8B, 14B, 30B-A3B, Coder-30B-A3B) and
  Qwen2.5 (7B, 14B, Coder-7B), by Alibaba's Qwen team -- Apache-2.0
- Mistral 7B Instruct v0.3 and Mistral Nemo 12B, by Mistral AI --
  Apache-2.0
- Phi-4 and Phi-4 mini, by Microsoft -- MIT
- DeepSeek-R1-Distill-Qwen 7B and 14B, by DeepSeek -- MIT
- SmolLM2 1.7B, by Hugging Face -- Apache-2.0
- gpt-oss-20b, by OpenAI -- Apache-2.0
- Granite 3.3 8B, by IBM -- Apache-2.0
- Llama 3.2 1B / 3B and Llama 3.1 8B, by Meta -- the Llama Community
  License (not an open-source license; spark asks before downloading)
- Gemma 3 1B / 4B / 12B / 27B, by Google -- the Gemma Terms of Use
  (https://ai.google.dev/gemma/terms; not an open-source license; spark
  asks before downloading)

## Built with Claude

The v1.0 refactor and simplification -- the layer split, the guided first
run, the model catalog, the chooser, the chat, the fresh-account proofs,
and these docs -- were designed and implemented with Claude (Anthropic)
in Claude Code, directed and reviewed by the maintainer.

Every such commit carries a `Co-Authored-By: Claude` trailer, so `git
log` tells the same story as this paragraph. The mistakes are the
maintainer's.

## Corrections

A correction or a missing name is a pull request away.
