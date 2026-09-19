#!/bin/sh
# spark tests/update_test.sh -- `spark update` against a throwaway HOME and a
# file:// bare clone of this tree (the get_test shape). Hermetic:
# SPARK_NO_APPLY=1 so bootstrap.sh never runs. Proves: up to date on a
# branch, one new commit pulled and named, a dirty tree refused with
# nothing changed, a detached clone moved to a newer SIGNED tag, an
# unsigned tag and a tag signed by an unknown key refused with HEAD
# unmoved, the signed row flipping with the tag, and --dry-run changing
# nothing in every case.
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
# a throwaway release key: the tested tip gains one commit whose
# allowed-signers is its public half, so a tag it signs is one `spark
# update` may move to, and a tag nobody known signed is not
ssh-keygen -q -t ed25519 -N '' -f "$T/key"
printf 'spark-release namespaces="git" %s\n' "$(cut -d' ' -f1,2 "$T/key.pub")" > "$T/allowed-signers"
head=$(git -C "$T/origin.git" symbolic-ref HEAD)
tip=$(git -C "$T/origin.git" rev-parse "$head")
blob=$(git -C "$T/origin.git" hash-object -w "$T/allowed-signers")
stree=$(GIT_INDEX_FILE="$T/signers-index" sh -c 'git -C "$1" read-tree "$2" && git -C "$1" update-index --add --cacheinfo "100644,$3,allowed-signers" && git -C "$1" write-tree' sh "$T/origin.git" "$tip" "$blob")
git -C "$T/origin.git" update-ref "$head" "$(git -C "$T/origin.git" commit-tree "$stree" -p "$tip" -m "update_test: the release key")"
# sign TAG COMMIT [KEY]: an annotated tag signed with the release key, or another
sign() { git -C "$T/origin.git" -c gpg.format=ssh -c user.signingkey="${3:-$T/key}" tag -s -m "$1" "$1" "$2"; }
# row SPARK: the signed row of spark check, as "status: value"
row() { "$1" check --porcelain --fresh signed 2>/dev/null | awk -F'\t' '$3 == "signed" { print $2 ": " $4 }'; }

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

# a systemctl stub (Linux): is-enabled answers enabled, so a converge
# that moved the tree must RESTART both units and say so -- without it
# the API keeps serving the old code with every row green
if [ "$(uname -s)" != Darwin ]; then
    mkdir -p "$T/bin"
    cat > "$T/bin/systemctl" <<'SH'
#!/bin/sh
echo "systemctl $*" >> "$SYSCTL_LOG"
case "$*" in *is-enabled*) echo enabled ;; esac
exit 0
SH
    chmod +x "$T/bin/systemctl"
    SYSCTL_LOG="$T/systemctl.log"; export SYSCTL_LOG
    PATH="$T/bin:$PATH"; export PATH
fi

# 3. the real run pulls it and names the count
out=$("$SPARK" update 2>&1) && ok "pull exits 0" || bad "pull: rc $? $out"
printf '%s\n' "$out" | grep -q ": 1 new commit" && ok "pull names the count" || bad "pull: $out"
[ "$(git -C "$T/work" rev-parse HEAD)" = "$newc" ] && ok "pull moved HEAD to the new commit" || bad "pull: HEAD is $(git -C "$T/work" rev-parse HEAD)"
if [ "$(uname -s)" != Darwin ]; then
    grep -q -- "--user restart spark-serve.service" "$SYSCTL_LOG" 2>/dev/null \
        && grep -q -- "--user restart spark-forge.service" "$SYSCTL_LOG" 2>/dev/null \
        && ok "a pull that moved the tree restarts the loaded units" \
        || bad "no restart logged: $(cat "$SYSCTL_LOG" 2>/dev/null | tr '\n' ' ')"
    printf '%s\n' "$out" | grep -q "restarted on the new tree" && ok "the restart says so" || bad "restart not said: $out"
fi

out=$("$SPARK" update 2>&1) && ok "second pull run: up to date" || bad "second pull run: rc $? $out"
printf '%s\n' "$out" | grep -q 'up to date' || bad "second pull run did not settle: $out"

# 4. a dirty tree is refused, --dry-run or not, nothing changes
echo dirty >> "$T/work/docs/CHANGELOG.md"
before=$(git -C "$T/work" rev-parse HEAD)
if out=$("$SPARK" update 2>&1); then bad "dirty tree: not refused"; else ok "dirty tree: refused"; fi
printf '%s\n' "$out" | grep -q 'dirty' && ok "dirty tree: the refusal names it" || bad "dirty tree: $out"
if out=$("$SPARK" update --dry-run 2>&1); then bad "dirty tree --dry-run: not refused"; else ok "dirty tree --dry-run: refused"; fi
[ "$(git -C "$T/work" rev-parse HEAD)" = "$before" ] && ok "dirty tree: HEAD unchanged" || bad "dirty tree: HEAD moved"
git -C "$T/work" checkout -q -- docs/CHANGELOG.md

# 5. a detached clone: two tags on origin -- v1.0 unsigned (where the
#    clone was put by hand), v1.1 signed -- checked out at the older one
base=$(git -C "$T/origin.git" rev-parse "refs/heads/$branch")
git -C "$T/origin.git" tag v1.0 "$base"
rtree=$(git -C "$T/origin.git" rev-parse "$base^{tree}")
c2=$(git -C "$T/origin.git" commit-tree "$rtree" -p "$base" -m "update_test: v1.1")
sign v1.1 "$c2"
git clone -q "$T/origin.git" "$T/rel"
git -C "$T/rel" checkout -q --detach v1.0
RELSPARK="$T/rel/bin/spark"
r=$(row "$RELSPARK")
[ "$r" = "warn: v1.0 is not signed: spark update refuses unsigned tags" ] && ok "signed row: warns at an unsigned tag" || bad "signed row at v1.0: $r"

out=$("$RELSPARK" update --dry-run 2>&1) && ok "detached --dry-run exits 0" || bad "detached --dry-run: rc $? $out"
printf '%s\n' "$out" | grep -q 'would move to v1.1 (signed by spark-release; was v1.0)' && ok "detached --dry-run says it would move, signed" || bad "detached --dry-run: $out"
[ "$(git -C "$T/rel" describe --tags --exact-match)" = v1.0 ] && ok "detached --dry-run stayed at v1.0" || bad "detached --dry-run moved"

out=$("$RELSPARK" update 2>&1) && ok "detached move exits 0" || bad "detached move: rc $? $out"
printf '%s\n' "$out" | grep -q 'v1.1 (signed by spark-release; was v1.0)' && ok "detached move names old, new and the signer" || bad "detached move: $out"
[ "$(git -C "$T/rel" describe --tags --exact-match)" = v1.1 ] && ok "detached move landed on v1.1" || bad "detached move: $(git -C "$T/rel" describe --tags --exact-match 2>&1)"
r=$(row "$RELSPARK")
[ "$r" = "ok: v1.1 signed by spark-release" ] && ok "signed row: ok at a signed tag, naming the signer" || bad "signed row at v1.1: $r"

out=$("$RELSPARK" update 2>&1) && ok "at the newest tag: exits 0" || bad "at newest: rc $? $out"
printf '%s\n' "$out" | grep -q 'already at v1.1' && ok "at the newest tag: says so" || bad "at newest: $out"

# 6. an unsigned tag on origin is no release: refused in one line, exit 1,
#    HEAD unmoved -- and --dry-run says the same
c3=$(git -C "$T/origin.git" commit-tree "$rtree" -p "$c2" -m "update_test: v1.2, unsigned")
git -C "$T/origin.git" tag v1.2 "$c3"
rc=0; out=$("$RELSPARK" update 2>&1) || rc=$?
[ "$rc" -eq 1 ] && ok "unsigned tag: refused, exit 1" || bad "unsigned tag: rc $rc: $out"
printf '%s\n' "$out" | grep -q 'update -- v1.2 is not signed by a known key: refused' && ok "unsigned tag: the refusal names it" || bad "unsigned tag: $out"
[ "$(git -C "$T/rel" describe --tags --exact-match)" = v1.1 ] && ok "unsigned tag: HEAD unmoved" || bad "unsigned tag: HEAD moved to $(git -C "$T/rel" describe --tags --exact-match 2>&1)"
rc=0; out=$("$RELSPARK" update --dry-run 2>&1) || rc=$?
[ "$rc" -eq 1 ] && printf '%s\n' "$out" | grep -q 'v1.2 is not signed by a known key: refused' && ok "unsigned tag: --dry-run refuses the same way" || bad "unsigned tag --dry-run: rc $rc: $out"

# 7. a tag signed by a key the tree does not know is no release either
ssh-keygen -q -t ed25519 -N '' -f "$T/other"
c4=$(git -C "$T/origin.git" commit-tree "$rtree" -p "$c3" -m "update_test: v1.3, another key")
sign v1.3 "$c4" "$T/other"
rc=0; out=$("$RELSPARK" update 2>&1) || rc=$?
[ "$rc" -eq 1 ] && printf '%s\n' "$out" | grep -q 'v1.3 is not signed by a known key: refused' && ok "unknown key: refused" || bad "unknown key: rc $rc: $out"
[ "$(git -C "$T/rel" describe --tags --exact-match)" = v1.1 ] && ok "unknown key: HEAD unmoved" || bad "unknown key: HEAD moved"

# 8. the next signed tag moves it again
c5=$(git -C "$T/origin.git" commit-tree "$rtree" -p "$c4" -m "update_test: v1.4")
sign v1.4 "$c5"
out=$("$RELSPARK" update 2>&1) && ok "a signed tag after the refusals: exits 0" || bad "v1.4: rc $? $out"
[ "$(git -C "$T/rel" describe --tags --exact-match)" = v1.4 ] && ok "landed on v1.4" || bad "not on v1.4: $out"

[ "$fail" -eq 0 ] && echo "update_test: all ok" || { echo "update_test: FAILED"; exit 1; }
