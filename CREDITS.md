# spark -- credits and licenses

spark vendors none of the projects below. `bootstrap.sh` downloads each
one, pinned by version and sha256, from its own upstream to your
machine at install time. apt and pacman install the rest from their own
repositories. spark's own code is MIT (`LICENSE`). The banner in
`home/.config/spark/banner` is spark's own artwork.

## The engine

llama.cpp -- https://github.com/ggml-org/llama.cpp -- MIT
(c) The ggml authors

Release b10689 (`LLAMA_VERSION` in `engine.env`), six flavours, each
pinned by sha256: macOS arm64, macOS x64, Linux x64, Linux x64 Vulkan,
Linux arm64, Linux arm64 Vulkan.

## The tale

The text in `home/.config/spark/tale` is the maintainer's own, CC
BY-NC-ND 4.0.

## Palettes

Colour values only, no code copied. The license is the upstream's:

- Catppuccin -- https://github.com/catppuccin/catppuccin -- MIT.
- Dracula -- https://github.com/dracula/dracula-theme -- MIT.
- Everforest -- https://github.com/sainnhe/everforest -- MIT.
- Gruvbox -- https://github.com/morhetz/gruvbox -- MIT.
- Nord -- https://www.nordtheme.com -- MIT.
- Rose Pine -- https://github.com/rose-pine/rose-pine-theme -- MIT.
- Selenized -- https://github.com/jan-warchol/selenized -- MIT.
- Solarized -- https://ethanschoonover.com/solarized -- MIT.
- Tokyo Night -- https://github.com/folke/tokyonight.nvim -- Apache-2.0.

## The AI's packages

apt or pacman installs these from the distro's own repositories,
unpinned; macOS needs none. The names are the distro's own, as
`distro/debian.env` and `distro/arch.env` list them, and
`tests/docs_test.py` checks that every name there is credited here.
Where the two families name one project differently, both names are
here.

- git -- GPL-2.0-only.
- curl -- the curl license.
- ca-certificates -- MPL-2.0, Mozilla's bundle as the distro ships it.
- python3 -- PSF-2.0.
- python -- PSF-2.0, Arch's name for python3.
- libgomp1 -- GPL-3.0-or-later, with the GCC runtime exception.
- gcc-libs -- GPL-3.0-or-later, with the GCC runtime exception. Arch's
  libgomp, in `base` there.
- libvulkan1 -- Apache-2.0, the vulkan build only.
- vulkan-icd-loader -- Apache-2.0, Arch's libvulkan1, the vulkan build
  only.
- mesa-vulkan-drivers -- MIT and others, the vulkan build only.
- vulkan-radeon -- MIT and others, Mesa's AMD driver on Arch, the vulkan
  build only.
- vulkan-intel -- MIT and others, Mesa's Intel driver on Arch, the
  vulkan build only.
- kbd -- https://kbd-project.org/ -- GPL-2.0-or-later. `setvtrgb` for
  the console palette unit, and the console fonts on Arch.

## The apps

An app's plugin is its own repository with its own credits, at
github.com/forgewright-ai/<name>: spark-micro, spark-neovim, spark-vim,
spark-helix, spark-nano, spark-w3m, spark-newsboat, spark-aerc and
spark-acp.

## Models

`bootstrap.sh` downloads them, never vendored. Each row's size and
sha256 come from Hugging Face's file metadata, and every row in
`models.env` names its license. The GGUF quantizations are by bartowski
and unsloth, and IBM's own for Granite.

- Qwen3 (1.7B, 4B, 4B-Thinking, 8B, 14B, 30B-A3B, Coder-30B-A3B) and
  Qwen2.5 (7B, 14B, Coder-7B) -- https://huggingface.co/Qwen -- Apache-2.0.
- Mistral 7B Instruct v0.3 and Mistral Nemo 12B --
  https://huggingface.co/mistralai -- Apache-2.0.
- Phi-4 and Phi-4 mini -- https://huggingface.co/microsoft -- MIT.
- DeepSeek-R1-Distill-Qwen 7B and 14B -- https://huggingface.co/deepseek-ai
  -- MIT.
- SmolLM2 1.7B -- https://huggingface.co/HuggingFaceTB -- Apache-2.0.
- gpt-oss-20b -- https://huggingface.co/openai -- Apache-2.0.
- Granite 4.2 8B -- https://huggingface.co/ibm-granite -- Apache-2.0.
- Llama 3.2 1B / 3B and Llama 3.1 8B -- https://huggingface.co/meta-llama
  -- the Llama Community License. Not an open-source license: spark asks
  before downloading.
- Gemma 3 1B / 4B / 12B / 27B -- https://ai.google.dev/gemma/terms -- the
  Gemma Terms of Use. Not an open-source license: spark asks before
  downloading.

## Built with Claude

The v1.0 refactor and simplification were designed and implemented with
Claude (Anthropic) in Claude Code, directed and reviewed by the
maintainer. That work was the layer split, the guided first run, the
model catalog, the chooser, the chat, the fresh-account proofs, and
these docs. Every
such commit carries a `Co-Authored-By: Claude` trailer, so `git log`
tells the same story as this paragraph. The mistakes are the
maintainer's.

## The page's glyphs

Simple Icons -- https://simpleicons.org -- CC0 1.0. The Debian, Arch,
Apple and GitHub glyphs inline on the front of spark.forgewright.ai,
which is rendered outside this tree. The Windows panes are drawn by
hand.

## Corrections

A correction or a missing name is a pull request away.
