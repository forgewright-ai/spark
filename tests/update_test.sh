#!/bin/sh
# spark tests/update_test.sh -- `spark update` against a throwaway HOME and a
# file:// bare clone of this tree (the get_test shape). Hermetic:
# SPARK_NO_APPLY=1 so bootstrap.sh never runs. Proves: up to date on a
# branch, one new commit pulled and named, a dirty tree refused with
# nothing changed, a detached clone moved to a newer tag, and --dry-run
# changing nothing in every case.
set -eu
REPO=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
export HOME="$T/home" XDG_CONFIG_HOME="$T/home/.config" XDG_STATE_HOME="$T/home/.local/state" XDG_DATA_HOME="$T/home/.local/share"
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
export SPARK_NO_APPLY=1
mkdir -p "$HOME"
fail=0
ok() { printf '  ok   %s\n' "$1"; }
bad() { printf '  FAIL %s\n' "$1"; fail=1; }

echo "update_test: $T"
# the origin: a bare clone of this repository; when the working tree has
# changes, one commit on top of HEAD carries them, so the test proves the
# tree at hand (the pre-commit case), not only what was last committed
# a bare clone of this repository's common git dir, not of $REPO: from a
# linked worktree a clone of the worktree path aliases the real repository
# (a run from one wrote a branch and a commit into it, 2026-09-05). The
# tested tree is $REPO's HEAD, published as the fixture's main, so a
# detached source (a CI checkout at a tag) and a worktree land the same.
common=$(cd "$REPO" && cd "$(git rev-parse --git-common-dir)" && pwd)
git clone -q --bare "$common" "$T/origin.git"
git -C "$T/origin.git" update-ref refs/heads/main "$(git -C "$REPO" rev-parse HEAD)"
git -C "$T/origin.git" symbolic-ref HEAD refs/heads/main
# the real repository carries release tags; the fixture makes its own, so
# drop the inherited ones first (a name collision would fail `git tag`)
for t in $(git -C "$T/origin.git" tag -l); do git -C "$T/origin.git" tag -d "$t" >/dev/null; done
if [ -n "$(git -C "$REPO" status --porcelain)" ]; then
    tree=$(GIT_INDEX_FILE="$T/index" sh -c 'cd "$1" && git add -A >/dev/null && git write-tree' sh "$REPO")
    commit=$(git -C "$REPO" commit-tree "$tree" -p HEAD -m "update_test: the working tree")
    git -C "$REPO" push -q --no-verify "$T/origin.git" "$commit:refs/heads/update-test"
    git -C "$T/origin.git" symbolic-ref HEAD refs/heads/update-test
fi

# 1. a clone attached to a branch, tracking origin
git clone -q "$T/origin.git" "$T/work"
branch=$(git -C "$T/work" symbolic-ref --short HEAD)
SPARK="$T/work/bin/spark"

out=$("$SPARK" update 2>&1) && ok "up to date exits 0" || bad "up to date: rc $? $out"
printf '%s\n' "$out" | grep -q 'up to date' && ok "up to date says so" || bad "up to date: $out"
before=$(git -C "$T/work" rev-parse HEAD)

# 2. --dry-run with a new commit on origin: says so, changes nothing
tip=$(git -C "$T/origin.git" rev-parse "refs/heads/$branch")
otree=$(git -C "$T/origin.git" rev-parse "$tip^{tree}")
newc=$(git -C "$T/origin.git" commit-tree "$otree" -p "$tip" -m "update_test: one more commit")
git -C "$T/origin.git" update-ref "refs/heads/$branch" "$newc"

out=$("$SPARK" update --dry-run 2>&1) && ok "--dry-run (pull) exits 0" || bad "--dry-run pull: rc $? $out"
printf '%s\n' "$out" | grep -q 'would pull' && ok "--dry-run says it would pull" || bad "--dry-run pull: $out"
[ "$(git -C "$T/work" rev-parse HEAD)" = "$before" ] && ok "--dry-run (pull) changed nothing" || bad "--dry-run pull moved HEAD"

# 3. the real run pulls it and names the count
out=$("$SPARK" update 2>&1) && ok "pull exits 0" || bad "pull: rc $? $out"
printf '%s\n' "$out" | grep -q ": 1 new commit" && ok "pull names the count" || bad "pull: $out"
[ "$(git -C "$T/work" rev-parse HEAD)" = "$newc" ] && ok "pull moved HEAD to the new commit" || bad "pull: HEAD is $(git -C "$T/work" rev-parse HEAD)"

out=$("$SPARK" update 2>&1) && ok "second pull run: up to date" || bad "second pull run: rc $? $out"
printf '%s\n' "$out" | grep -q 'up to date' || bad "second pull run did not settle: $out"

# 4. a dirty tree is refused, --dry-run or not, nothing changes
echo dirty >> "$T/work/CHANGELOG.md"
before=$(git -C "$T/work" rev-parse HEAD)
if out=$("$SPARK" update 2>&1); then bad "dirty tree: not refused"; else ok "dirty tree: refused"; fi
printf '%s\n' "$out" | grep -q 'dirty' && ok "dirty tree: the refusal names it" || bad "dirty tree: $out"
if out=$("$SPARK" update --dry-run 2>&1); then bad "dirty tree --dry-run: not refused"; else ok "dirty tree --dry-run: refused"; fi
[ "$(git -C "$T/work" rev-parse HEAD)" = "$before" ] && ok "dirty tree: HEAD unchanged" || bad "dirty tree: HEAD moved"
git -C "$T/work" checkout -q -- CHANGELOG.md

# 5. a detached clone: two tags on origin, checked out at the older one
base=$(git -C "$T/origin.git" rev-parse "refs/heads/$branch")
git -C "$T/origin.git" tag v1.0 "$base"
rtree=$(git -C "$T/origin.git" rev-parse "$base^{tree}")
c2=$(git -C "$T/origin.git" commit-tree "$rtree" -p "$base" -m "update_test: v1.1")
git -C "$T/origin.git" tag v1.1 "$c2"
git clone -q "$T/origin.git" "$T/rel"
git -C "$T/rel" checkout -q --detach v1.0
RELSPARK="$T/rel/bin/spark"

out=$("$RELSPARK" update --dry-run 2>&1) && ok "detached --dry-run exits 0" || bad "detached --dry-run: rc $? $out"
printf '%s\n' "$out" | grep -q 'would move to v1.1 (was v1.0)' && ok "detached --dry-run says it would move" || bad "detached --dry-run: $out"
[ "$(git -C "$T/rel" describe --tags --exact-match)" = v1.0 ] && ok "detached --dry-run stayed at v1.0" || bad "detached --dry-run moved"

out=$("$RELSPARK" update 2>&1) && ok "detached move exits 0" || bad "detached move: rc $? $out"
printf '%s\n' "$out" | grep -q 'v1.1 (was v1.0)' && ok "detached move names old and new" || bad "detached move: $out"
[ "$(git -C "$T/rel" describe --tags --exact-match)" = v1.1 ] && ok "detached move landed on v1.1" || bad "detached move: $(git -C "$T/rel" describe --tags --exact-match 2>&1)"

out=$("$RELSPARK" update 2>&1) && ok "at the newest tag: exits 0" || bad "at newest: rc $? $out"
printf '%s\n' "$out" | grep -q 'already at v1.1' && ok "at the newest tag: says so" || bad "at newest: $out"

[ "$fail" -eq 0 ] && echo "update_test: all ok" || { echo "update_test: FAILED"; exit 1; }
