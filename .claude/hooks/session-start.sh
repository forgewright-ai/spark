#!/bin/sh
# spark's session start, in a Claude Code cloud session only: the
# repository's hooks on, so a commit runs tests/gate.sh fast, and the
# tools the gate needs, installed when apt-get can. A local clone is left
# as it is. Every start says one line: what is on, or what is missing.
set -eu
[ "${CLAUDE_CODE_REMOTE:-}" = true ] || exit 0
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"
git config core.hooksPath .githooks

# a tool the gate runs, and the Debian package that has it
TOOLS='shellcheck shellcheck
zsh zsh
bwrap bubblewrap
ssh-keygen openssh-client'

missing() {    # missing tools|packages: what is not on PATH
    printf '%s\n' "$TOOLS" | while read -r tool pkg; do
        command -v "$tool" >/dev/null 2>&1 && continue
        if [ "$1" = tools ]; then printf '%s ' "$tool"; else printf '%s ' "$pkg"; fi
    done
}

pkgs=$(missing packages)
if [ -n "$pkgs" ] && [ "$(id -u)" = 0 ] && command -v apt-get >/dev/null 2>&1; then
    # a failed install is said below and tried again at the next start
    # shellcheck disable=SC2086 # one word a package
    { apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $pkgs; } >/dev/null 2>&1 || :
fi
tools=$(missing tools)
if [ -n "$tools" ]; then
    echo "! the gate is missing ${tools}-- tests/gate.sh skips what needs them with a NOTICE"
else
    echo "* hooks on (.githooks); the gate's tools are here: shellcheck, zsh, bwrap, ssh-keygen"
fi
