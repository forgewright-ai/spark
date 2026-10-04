#!/bin/sh
# spark tests/gate.sh -- the one test list. The hooks and ci.yml call this
# file and name no test themselves (tests/docs_test.py holds them to it).
#
#   sh tests/gate.sh fast           what a commit runs: seconds
#   sh tests/gate.sh full           every group below, in order
#   sh tests/gate.sh full GROUP     smoke | serve | rest (one CI job each)
#
# fast: the privacy gate over the staged change, syntax, the cheatsheet's
# 80 columns, ASCII docs, shellcheck, docs_test.
# full: fast's checks over the tree, the whole-tree privacy gate, and every
# suite for this OS. A tool that is missing on this machine prints a NOTICE
# and is skipped; it never silently passes. The privacy gate has no skip
# path. SPARK_GATE_PYTHON names the python (ci.yml: Apple's on macOS).
set -eu
cd "$(git rev-parse --show-toplevel)"
mode=${1:-}
group=${2:-}
PY=${SPARK_GATE_PYTHON:-python3}
os=$(uname -s)
fail=0
failed=
notice() { printf 'NOTICE: %s\n' "$*"; }
bad() { printf 'gate: %s\n' "$*"; fail=1; failed="$failed
  $(printf '%s\n' "$*" | head -1)"; }

# run LABEL COMMAND...: one suite. fast keeps it quiet, full shows it under
# a `== LABEL` line. Every tests/ file the gate runs is on a `run` line.
run() {
    label=$1; shift
    if [ "$mode" = fast ]; then
        "$@" >/dev/null || bad "$label"
    else
        printf '== %s\n' "$label"
        "$@" || bad "$label"
    fi
}

# --- the privacy gate: staged content, the staged names, the branch ------
# Banned words (whole word, any case) from the union of .privacy-terms and
# the local list -- $SPARK_PRIVACY_TERMS, else ~/.config/spark/privacy-terms
# -- plus e-mail addresses, private IPv4 ranges and home-directory paths
# that name a user. The three patterns always run; a missing word list is a
# NOTICE, never silence, and an empty list never becomes grep -E "".
staged() {
    staged_files=$(git diff --cached --name-only --diff-filter=ACMR)
    [ -n "$staged_files" ] || return 0
    local_terms=${SPARK_PRIVACY_TERMS:-${XDG_CONFIG_HOME:-$HOME/.config}/spark/privacy-terms}
    # each word escaped for grep -E: a dot or a bracket in a word stays literal
    terms=$(cat .privacy-terms "$local_terms" 2>/dev/null \
            | sed 's/#.*//; s/^[[:space:]]*//; s/[[:space:]]*$//' | grep -v '^$' | sort -u \
            | sed 's,[][\.*^$+?(){}|/],\\&,g' | paste -sd'|' -)
    [ -n "$terms" ] || notice "no privacy word list ($(printf '%s' "$local_terms" | sed "s|^$HOME|~|")) -- generic patterns only"
    # the names are public too: every staged path, and the branch itself
    if [ -n "$terms" ]; then
        hit=$(printf '%s\n%s\n' "$staged_files" "$(git rev-parse --abbrev-ref HEAD)" | grep -iE "\\b($terms)\\b" || true)
        [ -z "$hit" ] || bad "banned word in a staged file name or the branch name:
$hit"
    fi
    # .privacy-terms is the one tracked file allowed to contain the words.
    added=$(git diff --cached --diff-filter=ACMR -U0 -- . ':(exclude).privacy-terms' \
            | grep '^+' | grep -v '^+++' || true)
    [ -n "$added" ] || return 0
    if [ -n "$terms" ]; then
        hit=$(printf '%s\n' "$added" | grep -iEn "\\b($terms)\\b" || true)
        [ -z "$hit" ] || bad "banned word in staged change:
$hit"
    fi
    hit=$(printf '%s\n' "$added" | grep -En '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' \
          | grep -v 'you@example.com' || true)
    [ -z "$hit" ] || bad "e-mail address in staged change:
$hit"
    hit=$(printf '%s\n' "$added" \
          | grep -En '\b(10\.[0-9]+\.[0-9]+\.[0-9]+|192\.168\.[0-9]+\.[0-9]+|172\.(1[6-9]|2[0-9]|3[01])\.[0-9]+\.[0-9]+)\b' || true)
    [ -z "$hit" ] || bad "private IPv4 address in staged change:
$hit"
    # absolute paths only: a repo-relative `linux/home/...` is fine
    hit=$(printf '%s\n' "$added" | grep -En '(^.|[^[:alnum:]/._-])/(home|Users)/[A-Za-z0-9_-]+' || true)
    [ -z "$hit" ] || bad "home path naming a user in staged change:
$hit"
    # secret shapes: the product's own list (SOURCE_SHAPES in
    # lib/spark/text.py -- SECRET_SHAPES, what `spark line --paste`
    # holds, plus the two only a source needs) minus the lines tuned
    # for a paste or a source and not a tree -- "a credential line"
    # reads `token = users.add(name)` as one, "a long base64 run" reads
    # every sha256 pin and the key in allowed-signers as one, "a
    # one-time code" reads any "code ... 1234", "a link token" any
    # test URL with a key. A hit names the shape, never the line; a
    # line marked `spark:allow-secret` (a test fixture) is skipped. A
    # text.py that does not import refuses too.
    if [ -f lib/spark/text.py ]; then
        hit=$(printf '%s\n' "$added" | grep -v 'spark:allow-secret' | PYTHONPATH=lib "$PY" -c '
import re, sys
from spark.text import SOURCE_SHAPES
paste_only = ("a credential line", "a long base64 run")
source_only = ("a one-time code", "a link token")
text = sys.stdin.buffer.read().decode("utf-8", "replace")
print(", ".join(w for w, p in SOURCE_SHAPES if w not in paste_only + source_only and re.search(p, text)))
') || bad "secret shapes: lib/spark/text.py does not import"
        [ -z "$hit" ] || bad "a secret shape in the staged diff: $hit"
    else
        bad "lib/spark/text.py is missing: the secret shapes have no list"
    fi
}

# --- the privacy gate over the whole tree (full) --------------------------
# In CI the personal word list is a repository secret, one word per line,
# handed over as SPARK_PRIVACY_TERMS_SECRET; on a workstation it is the
# local list. Each word is escaped for grep -E, and -l: a hit names the
# file, never the line -- the CI log is public. Without a list: a NOTICE
# and the generic patterns only. Each check is an if: a negated pipeline
# is exempt from errexit, and would fail in silence.
tree_privacy() {
    list=${SPARK_PRIVACY_TERMS:-${XDG_CONFIG_HOME:-$HOME/.config}/spark/privacy-terms}
    if [ -n "${SPARK_PRIVACY_TERMS_SECRET:-}" ]; then
        list=$(mktemp)
        printf '%s\n' "$SPARK_PRIVACY_TERMS_SECRET" > "$list"
    fi
    terms=$(cat .privacy-terms "$list" 2>/dev/null | grep -v '^#' | grep -v '^[[:space:]]*$' | sort -u \
            | sed 's,[][\.*^$+?(){}|/],\\&,g' | paste -sd'|' -)
    [ -z "${SPARK_PRIVACY_TERMS_SECRET:-}" ] || rm -f "$list"
    if [ -z "$terms" ]; then
        notice "no privacy word list -- generic patterns only"
    elif git grep -l -i -w -E "$terms" -- . ':(exclude).privacy-terms'; then
        bad "privacy: a listed word is in the tree"
    fi
    hits=$(git grep -n -E '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' -- . | grep -v 'you@example.com' || true)
    if [ -n "$hits" ]; then
        printf '%s\n' "$hits"
        bad "privacy: an e-mail address is in the tree"
    fi
    if git grep -n -E '\b(10\.[0-9]+\.[0-9]+\.[0-9]+|192\.168\.[0-9]+\.[0-9]+|172\.(1[6-9]|2[0-9]|3[01])\.[0-9]+\.[0-9]+)\b' -- .; then
        bad "privacy: a private IPv4 is in the tree"
    fi
}

# --- syntax -----------------------------------------------------------------
# one file per call: `sh -n A B` parses A and hands B to it as $1
syntax() {
    for f in bootstrap.sh install.sh lib/env.sh get \
             .githooks/pre-commit .githooks/pre-push .githooks/commit-msg tests/*.sh; do
        [ -f "$f" ] || { bad "$f is missing (sh -n names it)"; continue; }
        sh -n "$f" || bad "sh -n $f"
    done
    for f in home/.config/spark/completion.bash home/.config/spark/hook.bash home/.config/spark/widget.bash; do
        [ -f "$f" ] || { bad "$f is missing (bash -n names it)"; continue; }
        bash -n "$f" || bad "bash -n $f"
    done
    if command -v zsh >/dev/null 2>&1; then
        for f in home/.config/spark/completion.zsh home/.config/spark/hook.zsh home/.config/spark/widget.zsh; do
            [ -f "$f" ] || { bad "$f is missing (zsh -n names it)"; continue; }
            zsh -n "$f" || bad "zsh -n $f"
        done
    else
        notice "zsh not found; zsh syntax not checked"
    fi
    # -W error: a SyntaxWarning (an invalid escape, `is` on a literal) refuses
    "$PY" -W error -m py_compile bin/spark lib/spark/*.py tests/*.py || bad "py_compile (-W error)"
}

# --- the printed cheatsheet must fit 80 columns ---------------------------
columns() {
    if [ -f docs/CHEATSHEET.txt ]; then
        long=$(awk 'length > 80 { printf "  line %d (%d cols)\n", NR, length }' docs/CHEATSHEET.txt)
        [ -z "$long" ] || bad "docs/CHEATSHEET.txt wider than 80 columns:
$long"
    else
        bad "docs/CHEATSHEET.txt is missing: the 80-column gate has nothing to read"
    fi
}

# --- docs stay ASCII: they are read on the console too; so does the
#     FORGE page (served bytes, curl-able from that console) ----------------
# The pattern is an explicit byte range, not [:print:][:space:]: macOS grep
# decodes UTF-8 for the named classes even under LC_ALL=C, so multibyte
# characters slipped through. Bytes outside tab + printable ASCII fail.
ascii() {
    tab=$(printf '\t')
    # The ten in docs/ are named (the glob would miss the .txt), and a named
    # file that is missing refuses: only the glob may come back empty.
    for f in README.md CLAUDE.md CREDITS.md AGENTS.md LICENSE get \
             docs/INSTALL.md docs/CHEATSHEET.txt docs/CHANGELOG.md docs/ROADMAP.md docs/CONTRIBUTING.md \
             docs/*.md \
             lib/spark/forge/index.html lib/spark/forge/spark.css lib/spark/forge/spark.js \
             lib/spark/forge/manifest.webmanifest lib/spark/forge/favicon.svg; do
        case $f in 'docs/*.md') continue ;; esac
        [ -f "$f" ] || { bad "$f is missing (the ASCII gate names it)"; continue; }
        hit=$(LC_ALL=C grep -n "[^ -~${tab}]" "$f" | head -3 || true)
        [ -z "$hit" ] || bad "non-ASCII in $f (docs are read on the console):
$hit"
    done
}

# --- shellcheck -------------------------------------------------------------
# The contributor's tool, not a user's package: a NOTICE when absent, but
# never in CI on Linux, where ci.yml installs it.
lint() {
    if command -v shellcheck >/dev/null 2>&1; then
        shellcheck -S warning bootstrap.sh install.sh lib/env.sh get \
            .githooks/pre-commit .githooks/pre-push .githooks/commit-msg tests/gate.sh tests/land.sh \
            || bad "shellcheck"
    elif [ -n "${CI:-}" ] && [ "$os" = Linux ]; then
        bad "shellcheck not found (ci.yml installs it)"
    else
        notice "shellcheck not found; skipped"
    fi
}

static() { staged; syntax; columns; ascii; lint; }

group_smoke() {
    run smoke.py "$PY" tests/smoke.py
}

group_serve() {
    run serve_smoke.py "$PY" tests/serve_smoke.py
}

group_rest() {
    printf '== static\n'
    static
    tree_privacy
    run install_test.sh sh tests/install_test.sh
    run get_test.sh sh tests/get_test.sh
    run update_test.sh sh tests/update_test.sh
    run uninstall_test.sh sh tests/uninstall_test.sh
    # the runit finish scripts, run as runsv runs them (sv and sleep stubbed)
    run finish_test.sh sh tests/finish_test.sh
    # the pre-push guard and land.sh, against a stub gh and a bare repository
    run land_test.sh sh tests/land_test.sh
    run forge_smoke.py "$PY" tests/forge_smoke.py
    run bench_smoke.py "$PY" tests/bench_smoke.py
    run vault_test.py "$PY" tests/vault_test.py
    run sandbox_test.py "$PY" tests/sandbox_test.py
    run knowledge_test.py "$PY" tests/knowledge_test.py
    run qr_test.py "$PY" tests/qr_test.py
    run voice_test.py "$PY" tests/voice_test.py
    run docs_test.py "$PY" tests/docs_test.py
    run policy_test.py "$PY" tests/policy_test.py
    # the widgets at a pty: zsh on a Mac, bash on Linux; the pager on both
    case $os in
        Darwin) run "widget_pty shell" "$PY" tests/widget_pty.py zsh home/.config/spark/widget.zsh
                run "widget_pty completion" "$PY" tests/widget_pty.py completion zsh home/.config/spark/completion.zsh ;;
        *)      run "widget_pty shell" "$PY" tests/widget_pty.py bash home/.config/spark/widget.bash
                run "widget_pty completion" "$PY" tests/widget_pty.py completion bash home/.config/spark/completion.bash ;;
    esac
    run "widget_pty pager" "$PY" tests/widget_pty.py pager
    run selftest "$PY" bin/spark check --selftest
    run chaos "$PY" bin/spark check --chaos
}

case $mode in
    fast)
        [ -z "$group" ] || { echo "usage: sh tests/gate.sh fast | full [smoke|serve|rest]" >&2; exit 2; }
        static
        run docs_test.py "$PY" tests/docs_test.py
        ;;
    full)
        # git hands a hook GIT_DIR; the clone-based tests must see the tree
        # as a user does (from a linked worktree GIT_DIR names the worktree
        # git dir, and every git -C in them would answer for that instead)
        unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE
        "$PY" --version
        case $group in
            '')    group_smoke; group_serve; group_rest ;;
            smoke) group_smoke ;;
            serve) group_serve ;;
            rest)  group_rest ;;
            *)     echo "usage: sh tests/gate.sh fast | full [smoke|serve|rest]" >&2; exit 2 ;;
        esac
        printf '== end\n'
        ;;
    *)
        echo "usage: sh tests/gate.sh fast | full [smoke|serve|rest]" >&2; exit 2 ;;
esac

if [ "$fail" -ne 0 ]; then
    printf 'gate: refused%s\n' "$failed"
    exit 1
fi
[ "$mode" = fast ] || printf 'gate: %s %s ok\n' "$mode" "${group:-all}"
