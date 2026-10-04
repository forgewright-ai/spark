#!/bin/sh
# spark tests/land_test.sh -- the pre-push guard and tests/land.sh, against
# a stub gh and a bare repository standing in for GitHub. Hermetic: no
# network, no real gh. Proves: --passed says passed, not passed, could not
# ask and not github.com by exit code; the guard refuses main and a v* tag
# (asked by the commit an annotated tag points at) when ci.yml has not
# passed, lets them through when it has, lets every other ref and a
# deletion through unasked, and only notes a remote that is not on
# github.com or a machine without gh; land.sh refuses a dirty tree and a
# main that is not behind HEAD, --dry-run touches nothing, a green run
# fast-forwards main and deletes the try branch, a red run leaves main
# untouched and the try branch in place.
set -eu
REPO=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
export HOME="$T/home"
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
export GIT_CONFIG_NOSYSTEM=1 SPARK_LAND_POLL=0
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GITHUB_REPOSITORY
mkdir -p "$HOME" "$T/bin"
fail=0
ok() { printf '  ok   %s\n' "$1"; }
bad() { printf '  FAIL %s\n' "$1"; fail=1; }
echo "land_test: $T"

# the stub gh: `api` logs the URL and prints the count in $T/count (or
# fails when the file holds "down"); `run list` prints a run id; `run
# watch` exits as $T/watch says, and a green watch is a passed run from
# then on; `run view` prints one line of a failed log
cat > "$T/bin/gh" <<'EOF'
#!/bin/sh
case "$1 ${2:-}" in
    api\ *)     printf '%s\n' "$2" >> "$STUB/asked"
                [ "$(cat "$STUB/count")" != down ] || exit 1
                cat "$STUB/count" ;;
    run\ list)  echo 4242 ;;
    run\ watch) rc=$(cat "$STUB/watch"); [ "$rc" -ne 0 ] || echo 1 > "$STUB/count"; exit "$rc" ;;
    run\ view)  echo "the failed step's log" ;;
    *)          exit 2 ;;
esac
EOF
chmod +x "$T/bin/gh"
export STUB="$T" SPARK_GH="$T/bin/gh"
echo 0 > "$T/count"; echo 0 > "$T/watch"; : > "$T/asked"
HUB=https://github.com/example/scratch

# the work tree: the hooks and land.sh from the tree under test, an origin
# whose URL is on github.com and whose bytes are a bare repository here
git init -q --bare -b main "$T/origin.git"
# a bare repository refuses to delete the branch its HEAD names
git -C "$T/origin.git" symbolic-ref HEAD refs/heads/unborn
git init -q -b main "$T/w"
W="$T/w"
mkdir -p "$W/.githooks" "$W/tests"
cp "$REPO/.githooks/pre-push" "$W/.githooks/pre-push"
cp "$REPO/tests/land.sh" "$W/tests/land.sh"
chmod +x "$W/.githooks/pre-push"
git -C "$W" config core.hooksPath .githooks
git -C "$W" config "url.$T/origin.git.insteadOf" "$HUB"
git -C "$W" remote add origin "$HUB"
git -C "$W" add -A
git -C "$W" commit -q -m one
c1=$(git -C "$W" rev-parse HEAD)
at() { git -C "$T/origin.git" rev-parse -q --verify "$1" 2>/dev/null || echo none; }
land() { (cd "$W" && sh tests/land.sh "$@" 2>&1); }

# --- --passed: one check, four answers -------------------------------------
rc=0; out=$(land --passed "$c1" example/scratch) || rc=$?
[ "$rc" -eq 1 ] && printf '%s\n' "$out" | grep -q '^! land: ci.yml has not passed for .* -- sh tests/land.sh$' \
    && ok "--passed: no successful run is exit 1, one line naming land.sh" || bad "--passed not passed: rc $rc: $out"
grep -q "repos/example/scratch/actions/workflows/ci.yml/runs?head_sha=$c1&status=success" "$T/asked" \
    && ok "--passed asks ci.yml's successful runs for that sha" || bad "--passed asked: $(cat "$T/asked")"
echo 1 > "$T/count"
rc=0; out=$(land --passed "$c1" "$HUB.git") || rc=$?
[ "$rc" -eq 0 ] && [ "$out" = "land: ci.yml passed for $(printf '%s' "$c1" | cut -c1-7)" ] \
    && ok "--passed: a successful run is exit 0 (the repository read from an https URL)" || bad "--passed passed: rc $rc: $out"
rc=0; out=$(land --passed "$c1") || rc=$?
[ "$rc" -eq 0 ] && ok "--passed: no repository named, origin's is asked" || bad "--passed origin: rc $rc: $out"
echo down > "$T/count"
rc=0; out=$(land --passed "$c1" example/scratch) || rc=$?
[ "$rc" -eq 2 ] && printf '%s\n' "$out" | grep -q '^! land: could not ask GitHub' \
    && ok "--passed: a gh that fails is exit 2, could not ask" || bad "--passed down: rc $rc: $out"
echo 1 > "$T/count"
rc=0; out=$(land --passed "$c1; id" example/scratch) || rc=$?
[ "$rc" -eq 2 ] && ok "--passed: a sha that is not 40 hex digits is never sent" || bad "--passed bad sha: rc $rc: $out"
rc=0; out=$(SPARK_GH="$T/bin/absent" sh "$W/tests/land.sh" --passed "$c1" example/scratch 2>&1) || rc=$?
[ "$rc" -eq 2 ] && ok "--passed: no gh is exit 2" || bad "--passed no gh: rc $rc: $out"
rc=0; out=$(land --passed "$c1" "$T/origin.git") || rc=$?
[ "$rc" -eq 3 ] && ok "--passed: a remote that is not on github.com is exit 3" || bad "--passed not github: rc $rc: $out"

# --- the guard ---------------------------------------------------------------
echo 0 > "$T/count"; : > "$T/asked"
rc=0; out=$(git -C "$W" push -q origin main 2>&1) || rc=$?
[ "$rc" -ne 0 ] && [ "$(at refs/heads/main)" = none ] \
    && [ "$(printf '%s\n' "$out" | grep -c '^! pre-push: ')" -eq 1 ] \
    && printf '%s\n' "$out" | grep -q '^! pre-push: ci.yml has not passed for .* (main) -- sh tests/land.sh$' \
    && ok "guard: main refused in one line naming land.sh, nothing pushed" || bad "guard main refused: rc $rc: $out"
: > "$T/asked"
rc=0; out=$(git -C "$W" push -q origin main:refs/heads/try/x main:refs/heads/topic 2>&1) || rc=$?
[ "$rc" -eq 0 ] && [ -z "$out" ] && [ "$(at refs/heads/try/x)" = "$c1" ] && [ ! -s "$T/asked" ] \
    && ok "guard: a try branch and a topic branch pass, silent and unasked" || bad "guard other refs: rc $rc: $out"
git -C "$W" tag -a -m v9.9 v9.9
rc=0; out=$(git -C "$W" push -q origin v9.9 2>&1) || rc=$?
[ "$rc" -ne 0 ] && [ "$(at refs/tags/v9.9)" = none ] && printf '%s\n' "$out" | grep -q '^! pre-push: .*(v9.9) -- sh tests/land.sh$' \
    && ok "guard: a v* tag refused" || bad "guard tag refused: rc $rc: $out"
grep -q "head_sha=$c1&" "$T/asked" && ! grep -q "head_sha=$(git -C "$W" rev-parse v9.9)&" "$T/asked" \
    && ok "guard: an annotated tag is asked by the commit it points at" || bad "guard tag sha: $(cat "$T/asked")"
git -C "$W" tag note
rc=0; out=$(git -C "$W" push -q origin note 2>&1) || rc=$?
[ "$rc" -eq 0 ] && [ "$(at refs/tags/note)" = "$c1" ] && ok "guard: a tag that is not v* passes" || bad "guard other tag: rc $rc: $out"
echo down > "$T/count"
rc=0; out=$(git -C "$W" push -q origin main 2>&1) || rc=$?
[ "$rc" -ne 0 ] && [ "$(at refs/heads/main)" = none ] && printf '%s\n' "$out" | grep -q '^! pre-push: could not ask GitHub' \
    && ok "guard: a gh that fails refuses main, could not ask" || bad "guard down: rc $rc: $out"
rc=0; out=$(SPARK_GH="$T/bin/absent" git -C "$W" push -q origin main:refs/heads/main 2>&1) || rc=$?
[ "$rc" -eq 0 ] && [ "$(at refs/heads/main)" = "$c1" ] && printf '%s\n' "$out" | grep -q '^NOTICE: pre-push: gh not found' \
    && ok "guard: no gh is a NOTICE, the push goes on" || bad "guard no gh: rc $rc: $out"
echo 0 > "$T/count"; : > "$T/asked"
rc=0; out=$(git -C "$W" push -q origin :refs/heads/main 2>&1) || rc=$?
[ "$rc" -eq 0 ] && [ "$(at refs/heads/main)" = none ] && [ ! -s "$T/asked" ] \
    && ok "guard: a deletion passes unasked" || bad "guard deletion: rc $rc: $out"
git init -q --bare -b main "$T/plain.git"
rc=0; out=$(git -C "$W" push -q "$T/plain.git" main v9.9 2>&1) || rc=$?
[ "$rc" -eq 0 ] && [ "$(git -C "$T/plain.git" rev-parse main)" = "$c1" ] && [ ! -s "$T/asked" ] \
    && [ "$(printf '%s\n' "$out" | grep -c '^NOTICE: pre-push: not a github.com remote')" -eq 2 ] \
    && ok "guard: a remote that is not on github.com is a NOTICE, unasked" || bad "guard plain remote: rc $rc: $out"
echo 1 > "$T/count"
rc=0; out=$(git -C "$W" push -q origin main v9.9 2>&1) || rc=$?
[ "$rc" -eq 0 ] && [ -z "$out" ] && [ "$(at refs/heads/main)" = "$c1" ] && [ "$(at 'refs/tags/v9.9^{commit}')" = "$c1" ] \
    && ok "guard: main and the tag pass once ci.yml passed, silent" || bad "guard passed: rc $rc: $out"

# --- land.sh -----------------------------------------------------------------
echo two > "$W/two"
rc=0; out=$(land) || rc=$?
[ "$rc" -eq 1 ] && [ "$out" = "! land: the tree is dirty -- commit first" ] \
    && ok "land: a dirty tree refused in one line" || bad "land dirty: rc $rc: $out"
git -C "$W" add -A; git -C "$W" commit -q -m two
c2=$(git -C "$W" rev-parse HEAD); s2=$(git -C "$W" rev-parse --short HEAD)
before=$(git -C "$T/origin.git" for-each-ref | sort)
rc=0; out=$(land --dry-run) || rc=$?
[ "$rc" -eq 0 ] && printf '%s\n' "$out" | grep -q "git push origin $s2:refs/heads/main" \
    && [ "$(git -C "$T/origin.git" for-each-ref | sort)" = "$before" ] \
    && ok "land --dry-run: the steps, nothing pushed" || bad "land --dry-run: rc $rc: $out"
echo 0 > "$T/count"; echo 1 > "$T/watch"
rc=0; out=$(land) || rc=$?
[ "$rc" -eq 1 ] && [ "$(at refs/heads/main)" = "$c1" ] && [ "$(at "refs/heads/try/$s2")" = "$c2" ] \
    && printf '%s\n' "$out" | grep -q "the failed step's log" \
    && printf '%s\n' "$out" | grep -q "^! land: ci.yml did not pass for $s2: main is untouched, try/$s2 stays$" \
    && ok "land: a red run prints the failed log, main untouched, the try branch stays" || bad "land red: rc $rc: $out"
echo 0 > "$T/watch"
rc=0; out=$(land) || rc=$?
[ "$rc" -eq 0 ] && [ "$(at refs/heads/main)" = "$c2" ] && [ "$(at "refs/heads/try/$s2")" = none ] \
    && printf '%s\n' "$out" | grep -q "^land: main is at $s2$" \
    && ok "land: a green run fast-forwards main to the same commit, the try branch gone" || bad "land green: rc $rc: $out"
rc=0; out=$(land) || rc=$?
[ "$rc" -eq 0 ] && [ "$out" = "land: main is already at $s2" ] && ok "land: nothing to land says so" || bad "land again: rc $rc: $out"
# main moved elsewhere: HEAD no longer holds it
git -C "$W" commit -q --amend -m "two, again"
rc=0; out=$(land) || rc=$?
[ "$rc" -eq 1 ] && [ "$(at refs/heads/main)" = "$c2" ] && printf '%s\n' "$out" | grep -q "^! land: origin's main is not an ancestor of HEAD" \
    && ok "land: a main that is not behind HEAD refused, never forced" || bad "land diverged: rc $rc: $out"
rc=0; out=$(cd "$W" && SPARK_GH="$T/bin/absent" sh tests/land.sh 2>&1) || rc=$?
[ "$rc" -eq 1 ] && [ "$out" = "! land: gh is not on PATH: it watches the run" ] && ok "land: no gh refused" || bad "land no gh: rc $rc: $out"

[ "$fail" -eq 0 ] && echo "land_test: all ok" || { echo "land_test: FAILED"; exit 1; }
