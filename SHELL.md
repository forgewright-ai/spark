# The shell layer

spark's own shell for a machine that is an AI box -- tmux, starship,
fzf, zoxide, eza, bat, btop, the JetBrainsMono Nerd Font, one palette
on every surface -- lives in its own repository now:

    https://github.com/forgewright-ai/spark-shell

This document is not tied to a spark release. It is kept true as
things change, but it is outside the landing rule: nothing here has to
appear in `spark help`, `CHEATSHEET.txt` or a `CHANGELOG.md` entry,
and no release waits on it.

Install:

    git clone https://github.com/forgewright-ai/spark-shell ~/.spark-shell
    ~/.spark-shell/spark-shell on

How it meets spark, the whole of it:

- `~/.config/spark/theme.env` -- `spark theme NAME` writes the palette
  (21 `THEME_*` keys, contract 3); `spark-shell apply` re-renders the
  look from it. Two steps, two tools, one palette.
- `spark bar line` -- the machine's one-line status (core). The
  rendered `.tmux.conf` runs it every 15 s in the status line; any
  other status bar can call the same line.
- Nothing else. spark never calls spark-shell; spark-shell never
  writes spark's files.

A machine that ran the old built-in layer (spark v1.19 or earlier) is
migrated on `spark update`: bootstrap's `shell-moved` row hands the rc
files back from their `.bak`, and the first `spark-shell on` reads
your old choices out of site.env once and adopts the rendered files in
place. `spark shell` and `spark bar on|off` answer with a pointer to
the repository for one release.
