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

## The tale

The text in `home/.config/spark/tale` is the maintainer's own, CC BY-NC-ND 4.0.

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

Colour values only, no code copied; the license is the upstream's:

- Catppuccin -- https://github.com/catppuccin/catppuccin -- MIT
- Gruvbox -- https://github.com/morhetz/gruvbox -- MIT
- Nord -- https://www.nordtheme.com -- MIT
- Selenized -- https://github.com/jan-warchol/selenized -- MIT
- Solarized -- https://ethanschoonover.com/solarized -- MIT
- Tokyo Night -- https://github.com/folke/tokyonight.nvim -- Apache-2.0

## The AI's packages (apt, Linux; macOS needs none)

None of these is shipped by spark; apt installs them from Debian's or
Ubuntu's own repositories, unpinned.

- git -- GPL-2.0-only
- curl -- the curl license
- python3 -- PSF-2.0
- libgomp1 -- GPL-3.0-or-later, with the GCC runtime exception
- libvulkan1 -- Apache-2.0 (the vulkan build only)
- mesa-vulkan-drivers -- MIT and others (the vulkan build only)

## Shell tools (apt / Homebrew, `spark shell on`)

The shell layer's, installed from apt's or Homebrew's own repositories,
unpinned. No editor is among them: an app's plugin is its own repository
(micro: github.com/forgewright-ai/spark-micro, with its own credits).

- bash -- GPL-3.0-or-later
- tmux -- ISC
- unzip -- Info-ZIP (the Nerd Font's archive)
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

## Models

Downloaded by `bootstrap.sh`, never vendored. Each row's size and sha256
come from Hugging Face's file metadata; every row in `models.env` names
its license. GGUF quantizations by bartowski and unsloth.

- Qwen3 (1.7B, 4B, 4B-Thinking, 8B, 14B, 30B-A3B, Coder-30B-A3B) and
  Qwen2.5 (7B, 14B, Coder-7B) -- https://huggingface.co/Qwen -- Apache-2.0
- Mistral 7B Instruct v0.3 and Mistral Nemo 12B --
  https://huggingface.co/mistralai -- Apache-2.0
- Phi-4 and Phi-4 mini -- https://huggingface.co/microsoft -- MIT
- DeepSeek-R1-Distill-Qwen 7B and 14B -- https://huggingface.co/deepseek-ai
  -- MIT
- SmolLM2 1.7B -- https://huggingface.co/HuggingFaceTB -- Apache-2.0
- gpt-oss-20b -- https://huggingface.co/openai -- Apache-2.0
- Granite 3.3 8B -- https://huggingface.co/ibm-granite -- Apache-2.0
- Llama 3.2 1B / 3B and Llama 3.1 8B -- https://huggingface.co/meta-llama
  -- the Llama Community License: not an open-source license, spark asks
  before downloading
- Gemma 3 1B / 4B / 12B / 27B -- https://ai.google.dev/gemma/terms -- the
  Gemma Terms of Use: not an open-source license, spark asks before
  downloading

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
