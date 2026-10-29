#!/bin/sh
# spark's session start, in a Claude Code cloud session only: the
# repository's hooks on, so a commit runs tests/gate.sh fast, and the
# tools the gate needs, installed when apt-get can. The session is root,
# and spark refuses some work as root (the knowledge index never builds),
# so a user of its own, gate, runs the full gate. A local clone is left
# as it is. Every start says one line: what is on, or what is missing.
set -eu
[ "${CLAUDE_CODE_REMOTE:-}" = true ] || exit 0
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"
git config core.hooksPath .githooks

# a tool the gate runs, and the Debian package that has it
TOOLS='shellcheck shellcheck
zsh zsh
bwrap bubblewrap
ssh-keygen openssh-client
mandoc mandoc'

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
# the user the full gate runs as, and this clone trusted for it: git
# refuses a repository another user owns, and the suites isolate HOME, so
# the trust is the system's. The command gives gate the system's own
# PATH: root's names folders gate cannot read, and /usr/local/bin holds
# links into /root
if [ "$(id -u)" = 0 ]; then
    id gate >/dev/null 2>&1 || useradd -m -s /bin/sh gate >/dev/null 2>&1 || :
    for d in "$PWD" "$PWD/.git"; do    # a clone of the path is checked at its .git
        git config --system --get-all safe.directory 2>/dev/null | grep -qxF "$d" \
            || git config --system --add safe.directory "$d"
    done
fi
full="sh tests/gate.sh full"
if [ "$(id -u)" = 0 ] && id gate >/dev/null 2>&1; then
    full="runuser -u gate -- env PATH=/usr/sbin:/usr/bin:/sbin:/bin sh -c 'PYTHONPYCACHEPREFIX=\$HOME/.cache/pycache exec sh tests/gate.sh full'"
fi
tools=$(missing tools)
if [ -n "$tools" ]; then
    echo "! the gate is missing ${tools}-- tests/gate.sh skips what needs them with a NOTICE; the full gate: $full"
else
    echo "* hooks on (.githooks); the gate's tools are here; the full gate: $full"
fi
