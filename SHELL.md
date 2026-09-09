# spark shell

spark's own shell for a machine that is only an AI box, behind
`SITE_SHELL` and off by default. The AI does not need it.

This document is not tied to a spark release. It is kept true as things
change, but it is outside the landing rule: nothing here has to appear in
`spark help`, `CHEATSHEET.txt` or a `CHANGELOG.md` entry, and no release
waits on it. It stays until the shell layer's future is decided.

`spark shell on` (`SITE_SHELL=on`) puts spark's own shell on a machine
that is only an AI box: tmux, starship, fzf, zoxide, eza, bat, btop and
the Nerd Font, with one palette on every surface once a theme is chosen
(the text console, tmux, starship, and a micro you have). The rc files
become spark's (`~/.bashrc` and `~/.bash_profile` on Linux, `~/.zshrc`
and `~/.zprofile` on macOS; yours move to `<file>.bak`). It runs
bootstrap (sudo once for the packages on Linux; Homebrew on macOS, the
`Brewfile`), then says `open a new shell`. No editor comes with it.

`spark shell off` hands everything back: each rc file and each rendered
config (`.tmux.conf`, `.config/starship.toml`, btop's conf, micro's
colorscheme) is restored from its `.bak` or removed when there was none;
the console palette goes back to VGA; `~/.gitconfig` stays; the packages
stay installed. With the layer off, `spark bar` and the set forms of
`spark quiet login|boot` refuse, `spark help` folds the shell block into
one line, and the check rows that stand on it read `na`. `spark theme`,
`spark font` and `spark quiet start|audio` work either way.

Its keys:

| key | values | default |
|---|---|---|
| `SITE_SHELL` | `off` / `on` -- `spark shell on\|off` | `off` |
| `SITE_GIT_NAME` / `SITE_GIT_EMAIL` | the git identity `~/.gitconfig` is rendered with; unset, spark guesses and the `identity` row says so | guessed |
| `SITE_PROMPT` / `SITE_PROMPT_STYLE` | `starship`/`plain`; `minimal`/`full` | `starship`, `minimal` |
| `SITE_WORKSPACE` | the folder the `backup` row watches | `~/projects` |
| `SITE_QUIET_LOGIN` / `SITE_QUIET_BOOT` | Linux: `yes` bares the login (motd, `/etc/issue`; originals kept) / makes the boot silent (one GRUB drop-in) -- `spark quiet login\|boot on`. `boot` is refused on WSL 2 and Arch | `no` |

Two fonts on Linux: `spark font` sets the console face (core); the Nerd
Font comes with the layer as a `.ttf` in `~/.local/share/fonts` for your
terminal emulator, set in its own settings. On macOS the layer adds a
Terminal.app profile with the palette, the font and the keys an editor
needs (Option as Meta, so `Alt-s` is Option-s).

Most linked files are symlinks into the repo. Some apps rewrite their
own config on exit; those are rendered once as regular files:

| file | why it is not a symlink |
|---|---|
| `~/.config/btop/btop.conf` | btop rewrites it on every exit |
| `~/.config/micro/settings.json` | micro rewrites it; seeded once with `"colorscheme": "spark"` when micro is on PATH, then it is micro's. `spark theme NAME` sets that one key back; `spark shell off` drops it |
| `~/.gitconfig`, `~/.tmux.conf`, `~/.config/starship.toml`, `~/.config/micro/colorschemes/spark.micro` | carry your name / palette / choices |
| `~/.config/spark/launchd/*.plist` | launchd needs absolute paths |

`install.sh` never overwrites a regular file: it moves it to `<file>.bak`.
