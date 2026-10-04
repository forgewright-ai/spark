# spark -- credits and licenses

spark vendors none of the projects below. `bootstrap.sh` downloads each
one, pinned by version and sha256, from its own upstream to your
machine at install time. `spark voice` downloads the voice the same
way, only when you turn it on. apt, pacman, xbps, dnf and zypper
install the rest from their own repositories. spark's own code is MIT
(`LICENSE`). The banner in `home/.config/spark/banner` is spark's own
artwork.

## The engine

llama.cpp -- https://github.com/ggml-org/llama.cpp -- MIT
(c) The ggml authors

Release b10689 (`LLAMA_VERSION` in `engine.env`), 6 flavours, each
pinned by sha256: macOS arm64, macOS x64, Linux x64, Linux x64 Vulkan,
Linux arm64, Linux arm64 Vulkan.

## The voice

sherpa-onnx -- https://github.com/k2-fsa/sherpa-onnx -- Apache-2.0
(c) Xiaomi Corporation

Release v1.13.8 (`VOICE_RUNTIME_VERSION` in `voice.env`), 3 flavours,
each pinned by size and sha256: Linux x64, Linux arm64 and macOS. Each
carries onnxruntime -- https://github.com/microsoft/onnxruntime -- MIT.

`spark voice on` or `clear` downloads the models it runs into
`~/.local/share/spark/voice`, each pinned by size and sha256 in
`voice.env`:

- Kokoro-82M v1.0 -- https://huggingface.co/hexgrad/Kokoro-82M --
  Apache-2.0, the voice, in sherpa-onnx's full-precision export. Its
  tarball carries espeak-ng-data --
  https://github.com/espeak-ng/espeak-ng -- GPL-3.0, downloaded with it
  and never vendored.
- Whisper base -- https://github.com/openai/whisper -- MIT, the ears,
  in sherpa-onnx's int8 export.
- Silero VAD -- https://github.com/snakers4/silero-vad -- MIT: where a
  spoken question ends.

## The tale

The text in `home/.config/spark/tale` is the maintainer's own, CC
BY-NC-ND 4.0.

## The packages

apt, pacman, xbps, dnf or zypper installs these from the distro's own
repositories, unpinned. macOS needs none. The names are the distro's
own, as `distro/debian.env`, `distro/arch.env`, `distro/void.env`,
`distro/fedora.env` and `distro/opensuse.env` list them.
`tests/docs_test.py` checks that every name there is credited here.
Where the families name one project differently, every name is here.

- git -- GPL-2.0-only.
- curl -- the curl license.
- ca-certificates -- MPL-2.0, Mozilla's bundle as the distro ships it.
- python3 -- PSF-2.0, on Debian, Void, Fedora and openSUSE.
- python -- PSF-2.0, Arch's name for python3.
- tar -- GPL-3.0-or-later, GNU tar, on Fedora and openSUSE. It unpacks
  the engine, and a minimal install there has none.
- libgomp1 -- GPL-3.0-or-later, with the GCC runtime exception. The
  name on Debian and openSUSE.
- gcc-libs -- GPL-3.0-or-later, with the GCC runtime exception. Arch's
  libgomp, in `base` there.
- libgomp -- GPL-3.0-or-later, with the GCC runtime exception. The
  libgomp1 of Void and Fedora, its own package there.
- libvulkan1 -- Apache-2.0, the vulkan build only. The name on Debian
  and openSUSE.
- vulkan-icd-loader -- Apache-2.0, Arch's libvulkan1, the vulkan build
  only.
- vulkan-loader -- Apache-2.0, the libvulkan1 of Void and Fedora, the
  vulkan build only.
- mesa-vulkan-drivers -- MIT and others, the vulkan build only. The
  name on Debian and Fedora.
- vulkan-radeon -- MIT and others, Mesa's AMD driver on Arch, the vulkan
  build only.
- vulkan-intel -- MIT and others, Mesa's Intel driver on Arch, the
  vulkan build only.
- mesa-vulkan-radeon -- MIT and others, Mesa's AMD driver on Void, the
  vulkan build only.
- mesa-vulkan-intel -- MIT and others, Mesa's Intel driver on Void, the
  vulkan build only.
- libvulkan_radeon -- MIT and others, Mesa's AMD driver on openSUSE,
  the vulkan build only.
- libvulkan_intel -- MIT and others, Mesa's Intel driver on openSUSE,
  the vulkan build only.

## The apps

An app's plugin is its own repository with its own credits, at
github.com/forgewright-ai/<name>. The apps are spark-micro,
spark-neovim, spark-vim, spark-helix, spark-nano, spark-w3m,
spark-newsboat, spark-aerc and spark-acp.

## Models

`bootstrap.sh` downloads them, never vendored. Each row's size and
sha256 come from Hugging Face's file metadata, and every row in
`models.env` names its license. The GGUF quantizations are by bartowski
and unsloth, and IBM's own for Granite.

- Gemma 4 (E2B, E4B, 26B-A4B) -- https://huggingface.co/google --
  Apache-2.0.
- Qwen3 (4B, 8B, 14B, 30B-A3B, Coder-30B-A3B) and Qwen3.5 (2B, 4B) --
  https://huggingface.co/Qwen -- Apache-2.0.
- Granite 4.2 8B -- https://huggingface.co/ibm-granite -- Apache-2.0.

## Built with Claude

The v1.0 refactor and simplification were designed and implemented with
Claude (Anthropic) in Claude Code, directed and reviewed by the
maintainer. That work was the layer split, the guided first run, the
model catalogue, the chooser, the chat, the fresh-account proofs, and
these docs. Every
such commit carries a `Co-Authored-By: Claude` trailer, so `git log`
tells the same story as this paragraph. The mistakes are the
maintainer's.

## The site's glyphs

Simple Icons -- https://simpleicons.org -- CC0 1.0. The Debian, Arch,
Void, Apple and GitHub glyphs inline on the front of
spark.forgewright.ai, which is rendered outside this tree. The Windows
panes are drawn by hand.

## Corrections

A correction or a missing name is a pull request away.
