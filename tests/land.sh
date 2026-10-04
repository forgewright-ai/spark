#!/bin/sh
# spark tests/land.sh -- land HEAD on main through CI. main only ever
# receives a commit ci.yml already passed.
#
#   sh tests/land.sh              push HEAD to try/<short sha>, wait for
#                                 ci.yml, then fast-forward main to the same
#                                 commit and delete the try branch
#   sh tests/land.sh --dry-run    print the steps, touch nothing
#   sh tests/land.sh --passed SHA [OWNER/REPO | URL]
#                                 the one check "ci.yml passed for this
#                                 commit": the pre-push hook, this script
#                                 and release.yml all ask it here
#
# --passed exits 0 passed, 1 not passed, 2 could not ask (no gh, no
# network, a bad sha), 3 the remote is not on github.com. A red run leaves
# main untouched and the try branch in place. SPARK_GH names the gh
# program (a test seam: tests/land_test.sh puts a stub there).
set -eu
GH=${SPARK_GH:-gh}
usage() { echo "usage: sh tests/land.sh [--dry-run] | --passed SHA [OWNER/REPO | URL]" >&2; exit 2; }
say() { printf 'land: %s\n' "$*"; }
no() { printf '! land: %s\n' "$*"; }

# repo_of WHERE: OWNER/REPO from a github.com remote URL (https, ssh, the
# scp-like form) or from OWNER/REPO itself; fails for anything else
repo_of() {
    r=$1
    case $r in
        https://github.com/*) r=${r#https://github.com/} ;;
        ssh://*@github.com/*) r=${r#ssh://*@github.com/} ;;
        *@github.com:*)       r=${r#*@github.com:} ;;
        *:*|/*|.*)            return 1 ;;
    esac
    r=${r%/}; r=${r%.git}
    case $r in
        */*/*|*[!A-Za-z0-9._/-]*|/*|*/|'') return 1 ;;
        */*) printf '%s\n' "$r" ;;
        *)   return 1 ;;
    esac
}

# passed SHA REPO: a successful ci.yml run exists for that exact commit. A
# pull request's run does not count: it tests the merge, not the commit.
passed() {
    case $1 in *[!0-9a-f]*|'') return 2 ;; esac
    [ "${#1}" -eq 40 ] || return 2
    command -v "$GH" >/dev/null 2>&1 || return 2
    n=$("$GH" api "repos/$2/actions/workflows/ci.yml/runs?head_sha=$1&status=success" \
        --jq '[.workflow_runs[] | select(.event != "pull_request")] | length' 2>/dev/null) || return 2
    case $n in ''|*[!0-9]*) return 2 ;; 0) return 1 ;; esac
    return 0
}

if [ "${1:-}" = --passed ]; then
    [ $# -ge 2 ] && [ $# -le 3 ] || usage
    sha=$2
    where=${3:-${GITHUB_REPOSITORY:-$(git config --get remote.origin.url || true)}}
    repo=$(repo_of "$where") || { no "not a github.com repository: nothing to ask"; exit 3; }
    rc=0; passed "$sha" "$repo" || rc=$?
    short=$(printf '%s' "$sha" | cut -c1-7)
    case $rc in
        0) say "ci.yml passed for $short" ;;
        1) no "ci.yml has not passed for $short -- sh tests/land.sh" ;;
        *) no "could not ask GitHub whether ci.yml passed for $short -- gh auth status" ;;
    esac
    exit "$rc"
fi

dry=0
case ${1:-} in
    '') ;;
    --dry-run) dry=1 ;;
    *) usage ;;
esac
[ $# -le 1 ] || usage
cd "$(git rev-parse --show-toplevel)"
command -v "$GH" >/dev/null 2>&1 || { no "gh is not on PATH: it watches the run"; exit 1; }
repo=$(repo_of "$(git config --get remote.origin.url || true)") || { no "origin is not on github.com"; exit 1; }
[ -z "$(git status --porcelain)" ] || { no "the tree is dirty -- commit first"; exit 1; }
sha=$(git rev-parse HEAD)
short=$(git rev-parse --short HEAD)
try=try/$short

if [ "$dry" -eq 1 ]; then
    say "would land $short on main of $repo:"
    say "  git fetch origin main                     # main must be an ancestor of HEAD"
    say "  git push --force origin $short:refs/heads/$try"
    say "  gh run watch RUN --exit-status            # the ci.yml run for $short"
    say "  green: git push origin $short:refs/heads/main   # a fast-forward, never forced"
    say "         git push origin --delete $try"
    say "  red:   the failed jobs' log; main untouched; $try stays"
    exit 0
fi

git fetch -q origin main
main=$(git rev-parse FETCH_HEAD)
if [ "$main" = "$sha" ]; then say "main is already at $short"; exit 0; fi
git merge-base --is-ancestor "$main" "$sha" \
    || { no "origin's main is not an ancestor of HEAD -- rebase on it first"; exit 1; }

rc=0; passed "$sha" "$repo" || rc=$?
if [ "$rc" -eq 0 ]; then
    say "ci.yml already passed for $short"
else
    say "$short -> $try"
    git push -q --force origin "$sha:refs/heads/$try"
    # the run appears a few seconds after the push
    id=
    n=0
    while [ -z "$id" ] && [ "$n" -lt 30 ]; do
        id=$("$GH" run list -R "$repo" --workflow ci.yml --commit "$sha" --branch "$try" --limit 1 \
             --json databaseId --jq '.[0].databaseId // empty' 2>/dev/null) || id=
        [ -n "$id" ] || { n=$((n + 1)); sleep "${SPARK_LAND_POLL:-4}"; }
    done
    [ -n "$id" ] || { no "no ci.yml run for $short on $try -- gh run list -R $repo"; exit 1; }
    say "watching run $id"
    green=0
    "$GH" run watch "$id" -R "$repo" --exit-status --compact --interval 20 || green=$?
    # the shared check decides, not the watch's exit code alone
    if [ "$green" -eq 0 ]; then passed "$sha" "$repo" || green=$?; fi
    if [ "$green" -ne 0 ]; then
        "$GH" run view "$id" -R "$repo" --log-failed 2>/dev/null | tail -40 || true
        no "ci.yml did not pass for $short: main is untouched, $try stays"
        no "fix it, amend, run sh tests/land.sh again; then: git push origin --delete $try"
        exit 1
    fi
fi
# a fast-forward only: no --force, and the hook asks the same check again
git push origin "$sha:refs/heads/main"
if git ls-remote --exit-code origin "refs/heads/$try" >/dev/null 2>&1; then
    git push -q origin --delete "$try"
fi
say "main is at $short"
