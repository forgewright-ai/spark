#!/bin/sh
# setup.sh -- put tally on PATH for this user: ~/.local/bin, and a line in
# the shell's rc file when the directory is not on PATH yet.
set -eu

BIN="$HOME/.local/bin"
SRC="$(dirname "$0")/tally"

if [ ! -x "$SRC" ]; then
    echo "setup: $SRC is missing or not executable" >&2
    exit 1
fi

mkdir -p "$BIN"
cp "$SRC" "$BIN/tally"
chmod 755 "$BIN/tally"
echo "ok     tally        $BIN/tally"

case ":$PATH:" in
    *":$BIN:"*) ;;
    *)
        rc="$HOME/.profile"
        [ -n "${ZSH_VERSION:-}" ] && rc="$HOME/.zshrc"
        printf '\nexport PATH="%s:$PATH"\n' "$BIN" >> "$rc"
        echo "ok     path         added $BIN to PATH in $rc (open a new shell)"
        ;;
esac
