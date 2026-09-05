#!/bin/sh
# spark install.sh -- put the tracked configuration into $HOME.
#
#   home/<path>        -> symlink at ~/<path>          (shared by both OSes)
#   <os>/home/<path>   -> symlink at ~/<path>          (linux/ or macos/)
#   templates/<path>   -> regular file at ~/<path>, rendered with @KEY@
#
# A symlink means: edit the file in the repo, the machine sees it at once,
# and `git status` shows every change. A rendered file exists only where a
# value must be baked in (your name, a palette, an absolute path). An
# existing regular file, or a symlink that points outside the repo, is
# never overwritten: it is moved to <path>.bak.
#
# Two layers (site.env SITE_SHELL): the AI is always installed -- the
# widgets, the banner, spark.env.example, the service units. The shell
# layer -- the rc files, micro, .gitconfig, .tmux.conf, btop, starship --
# only with SITE_SHELL=on (spark shell on).
#
#   install.sh --dry-run    print what would change, touch nothing
#
# Output rows (contract 2): ok | would link | would render | would back up
# in dry-run; ok | link | render | back up when applied.
set -eu
REPO=$(cd "$(dirname "$0")" && pwd)
. "$REPO/lib/env.sh"

DRY=0
case ${1:-} in
    --dry-run) DRY=1 ;;
    '') ;;
    *) echo "usage: install.sh [--dry-run]" >&2; exit 2 ;;
esac
OS=$(uname -s)
case $OS in Darwin) OSDIR=macos ;; *) OSDIR=linux ;; esac

site_load
theme_load "$REPO"
# a client (SITE_AI_MODEL=none + SITE_PEER_AI_URL, spark client URL) runs no
# units: the systemd units and the launchd plists stay out
client=0; [ "$SITE_AI_MODEL" = none ] && [ -n "$SITE_PEER_AI_URL" ] && client=1

changes=0
row() { printf '%-14s %s\n' "$1" "$2"; }

# --- helpers --------------------------------------------------------------
backup() {
    changes=$((changes + 1))
    if [ "$DRY" -eq 1 ]; then row "would back up" "$1"; return; fi
    mv "$1" "$1.bak"
    row "back up" "$1 -> $1.bak"
}

link_one() {   # link_one SRC DST
    if [ -L "$2" ] && [ "$(readlink "$2")" = "$1" ]; then row ok "$2"; return; fi
    # a regular file, or someone else's symlink (one into this repo is an
    # older layout of ours: replaced), is backed up first
    if [ -e "$2" ] && [ ! -L "$2" ]; then backup "$2"
    elif [ -L "$2" ]; then case $(readlink "$2") in "$REPO"/*) ;; *) backup "$2" ;; esac; fi
    changes=$((changes + 1))
    if [ "$DRY" -eq 1 ]; then row "would link" "$2"; return; fi
    mkdir -p "$(dirname "$2")"
    ln -sfn "$1" "$2"
    row link "$2"
}

# sed-escape a replacement value: \ & and our | delimiter
esc() { printf '%s' "$1" | sed -e 's/[\\&|]/\\&/g'; }

render_expr() {
    e="s|@HOME@|$(esc "$HOME")|g;s|@USER@|$(esc "$(id -un)")|g;s|@REPO@|$(esc "$REPO")|g"
    e="$e;s|@WORKSPACE@|$(esc "$SITE_WORKSPACE")|g;s|@NAME@|$(esc "$SITE_NAME")|g"
    e="$e;s|@GIT_NAME@|$(esc "$SITE_GIT_NAME")|g;s|@GIT_EMAIL@|$(esc "$SITE_GIT_EMAIL")|g"
    e="$e;s|@BREW_PREFIX@|$(esc "${HOMEBREW_PREFIX:-$(command -v brew >/dev/null 2>&1 && brew --prefix || echo /usr/local)}")|g"
    for k in $THEME_KEYS; do
        eval "v=\$$k"
        # shellcheck disable=SC2154   # v is set by the eval above
        e="$e;s|@$k@|$(esc "$v")|g"
    done
    printf '%s' "$e"
}

TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT
EXPR=$(render_expr)

render_one() {   # render_one SRC DST
    sed -e "$EXPR" "$1" > "$TMP"
    if grep -q '@[A-Z_0-9]*@' "$TMP"; then
        printf 'install.sh: %s: unrendered placeholder: %s\n' "$1" "$(grep -o '@[A-Z_0-9]*@' "$TMP" | head -1)" >&2
        exit 1
    fi
    if [ -f "$2" ] && [ ! -L "$2" ] && cmp -s "$TMP" "$2"; then row ok "$2"; return; fi
    # a file we rendered before is ours to re-render; anything else is backed up
    if [ -f "$2" ] && [ ! -L "$2" ] && ! grep -q 'rendered by spark' "$2"; then backup "$2"; fi
    changes=$((changes + 1))
    if [ "$DRY" -eq 1 ]; then row "would render" "$2"; return; fi
    mkdir -p "$(dirname "$2")"
    rm -f "$2"                      # a stale symlink from an older layout
    cp "$TMP" "$2"
    chmod 0644 "$2"
    row render "$2"
}

# --- 1. links: shared tree, then the OS tree (the OS tree wins) -----------
for tree in "$REPO/home" "$REPO/$OSDIR/home"; do
    [ -d "$tree" ] || continue
    for src in $(find "$tree" -type f | sort); do
        rel=${src#"$tree"/}
        case $rel in
            .bashrc|.bash_profile|.zshrc|.zprofile|.config/micro/*)
                [ "$SITE_SHELL" = on ] || continue ;;
            .config/systemd/user/*)
                [ "$client" = 0 ] || continue ;;
        esac
        link_one "$src" "$HOME/$rel"
    done
done

# --- 2. templates ---------------------------------------------------------
for src in $(find "$REPO/templates" -type f | sort); do
    rel=${src#"$REPO"/templates/}
    seed=0
    case $rel in
        .config/spark/launchd/*)
            [ "$OS" = Darwin ] || continue
            [ "$client" = 0 ] || continue ;;
        .config/micro/settings.json)
            # seeded once, then micro's own: micro rewrites it on every
            # option change, so a file that exists is never re-rendered
            [ "$SITE_SHELL" = on ] || continue
            seed=1 ;;
        .gitconfig|.tmux.conf|.config/btop/*|.config/micro/*)
            [ "$SITE_SHELL" = on ] || continue ;;
        .config/starship.toml.*)
            [ "$SITE_SHELL" = on ] || continue
            [ "$SITE_PROMPT" = starship ] || continue
            [ "${rel##*.}" = "$SITE_PROMPT_STYLE" ] || continue
            rel=.config/starship.toml ;;
    esac
    if [ "$seed" = 1 ] && { [ -e "$HOME/$rel" ] || [ -L "$HOME/$rel" ]; }; then
        row ok "$HOME/$rel"
        continue
    fi
    render_one "$src" "$HOME/$rel"
done

if [ "$changes" -eq 0 ]; then echo "Nothing to do"; else echo "$changes to do"; fi
