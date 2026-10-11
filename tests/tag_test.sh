#!/bin/sh
# spark tests/tag_test.sh -- tests/tag.sh against a bare repository standing
# in for GitHub, a stub gh and a scratch release key. Hermetic: no network,
# no real key, config only in the scratch clone. Proves: a two-part heading
# is a major and nothing is done; a section of S3 and S4 waits off the
# weekly day and is tagged on it, or with --now; an S1 is tagged at once;
# ci.yml not passed refuses; --dry-run touches nothing; the pushed tag is
# annotated, signed by the key, named as the ref and points at main; a
# second run finds it and stops; a section without a severity bullet
# refuses. NOTICE and exit 0 where ssh-keygen is missing (a container).
set -eu
REPO=$(cd "$(dirname "$0")/.." && pwd)
command -v ssh-keygen >/dev/null 2>&1 || { echo "tag_test: NOTICE: ssh-keygen not found; skipped"; exit 0; }
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
export HOME="$T/home"
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
export GIT_CONFIG_NOSYSTEM=1
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GITHUB_REPOSITORY SPARK_TAG_WEEKDAY
mkdir -p "$HOME" "$T/bin"
fail=0
ok() { printf '  ok   %s\n' "$1"; }
bad() { printf '  FAIL %s\n' "$1"; fail=1; }
echo "tag_test: $T"

# the stub gh: `api` prints the count in $T/count, or fails on "down"
cat > "$T/bin/gh" <<'STUB'
#!/bin/sh
case "$1" in
    api) [ "$(cat "$STUB/count")" != down ] || exit 1; cat "$STUB/count" ;;
    *)   exit 2 ;;
esac
STUB
chmod +x "$T/bin/gh"
export STUB="$T" SPARK_GH="$T/bin/gh" SPARK_CURL="$T/bin/absent"
echo 1 > "$T/count"
HUB=https://github.com/example/scratch

# the scratch key and the signers file it is trusted by
ssh-keygen -q -t ed25519 -N '' -C t -f "$T/key"
printf 'spark-release namespaces="git" %s\n' "$(cut -d' ' -f1,2 "$T/key.pub")" > "$T/signers"

# the clone: tag.sh and land.sh from the tree under test, an origin whose
# URL is on github.com and whose bytes are a bare repository here
git init -q --bare -b main "$T/origin.git"
git init -q -b main "$T/w"
W="$T/w"
mkdir -p "$W/tests" "$W/docs"
cp "$REPO/tests/land.sh" "$REPO/tests/tag.sh" "$W/tests/"
git -C "$W" config "url.$T/origin.git.insteadOf" "$HUB"
git -C "$W" remote add origin "$HUB"
git -C "$W" config gpg.format ssh
git -C "$W" config user.signingkey "$T/key"
git -C "$W" config gpg.ssh.allowedSignersFile "$T/signers"
at() { git -C "$T/origin.git" rev-parse -q --verify "$1" 2>/dev/null || echo none; }
tagsh() { (cd "$W" && sh tests/tag.sh "$@" 2>&1); }
# log HEADING BULLET: the CHANGELOG with that patch section on top of v9.9
log() {
    if [ "$1" = v9.9 ]; then printf '# Changelog\n\n## v9.9\n\n- the release.\n' > "$W/docs/CHANGELOG.md"
    else printf '# Changelog\n\n## %s\n\n%s\n\n## v9.9\n\n- the release.\n' "$1" "$2" > "$W/docs/CHANGELOG.md"; fi
    git -C "$W" add -A; git -C "$W" commit -q -m "$1"; git -C "$W" push -q origin main
}
today=$(date +%u)
other=$((today % 7 + 1))

# --- a major: a person tags it ---------------------------------------------
log v9.9
rc=0; out=$(tagsh) || rc=$?
[ "$rc" -eq 0 ] && printf '%s\n' "$out" | grep -q 'a major (## v9.9): a person tags it$' && [ "$(at refs/tags/v9.9)" = none ] \
    && ok "a two-part heading is a major: said, nothing tagged" || bad "major: rc $rc: $out"
git -C "$W" tag -a -m v9.9 v9.9 && git -C "$W" push -q origin v9.9

# --- S3 alone: waits for the weekly day ----------------------------------
log v9.9.1 '- S3: a wording fixed (#7)'
m=$(git -C "$W" rev-parse HEAD)
rc=0; out=$(tagsh --weekday "$other") || rc=$?
[ "$rc" -eq 0 ] && printf '%s\n' "$out" | grep -q "^tag: v9.9.1 waits for weekday $other, today is $today: S3 -- " \
    && [ "$(at refs/tags/v9.9.1)" = none ] \
    && ok "S3 alone waits off the weekly day, says until when" || bad "S3 waits: rc $rc: $out"
echo 0 > "$T/count"
rc=0; out=$(tagsh --now) || rc=$?
[ "$rc" -eq 1 ] && [ "$out" = "! tag: ci.yml has not passed for main at $(printf '%s' "$m" | cut -c1-7) -- nothing tagged" ] \
    && [ "$(at refs/tags/v9.9.1)" = none ] && ok "ci.yml not passed: refused in one line, nothing tagged" || bad "not passed: rc $rc: $out"
echo down > "$T/count"
rc=0; out=$(tagsh --now) || rc=$?
[ "$rc" -eq 1 ] && printf '%s\n' "$out" | grep -q '^! tag: could not ask GitHub' && [ "$(at refs/tags/v9.9.1)" = none ] \
    && ok "a gh that fails: refused, could not ask" || bad "down: rc $rc: $out"
echo 1 > "$T/count"
before=$(git -C "$T/origin.git" for-each-ref | sort)
rc=0; out=$(tagsh --dry-run --now) || rc=$?
[ "$rc" -eq 0 ] && printf '%s\n' "$out" | grep -q "^tag: would tag v9.9.1 at .* (--now):$" \
    && printf '%s\n' "$out" | grep -q "git tag -s v9.9.1 -m 'spark v9.9.1'" \
    && [ "$(git -C "$T/origin.git" for-each-ref | sort)" = "$before" ] && [ -z "$(git -C "$W" tag -l v9.9.1)" ] \
    && ok "--dry-run: the steps, nothing tagged or pushed" || bad "dry-run: rc $rc: $out"
# a push the remote refuses (a deploy key not yet registered, a ruleset): the
# local tag is undone, so the next run is not fooled by it
mkdir -p "$T/origin.git/hooks"
printf '#!/bin/sh\nexit 1\n' > "$T/origin.git/hooks/pre-receive"
chmod +x "$T/origin.git/hooks/pre-receive"
rc=0; out=$(tagsh --now) || rc=$?
[ "$rc" -eq 1 ] && [ "$out" = "! tag: the push of v9.9.1 was refused; the tag is undone, nothing changed" ] \
    && [ -z "$(git -C "$W" tag -l v9.9.1)" ] && [ "$(at refs/tags/v9.9.1)" = none ] \
    && ok "a refused push: said, the local tag undone" || bad "refused push: rc $rc: $out: local $(git -C "$W" tag -l v9.9.1)"
rm -f "$T/origin.git/hooks/pre-receive"
rc=0; out=$(tagsh --weekday "$today") || rc=$?
[ "$rc" -eq 0 ] && [ "$out" = "tag: v9.9.1 at $(printf '%s' "$m" | cut -c1-7) (the weekly day)" ] \
    && ok "S3 alone on the weekly day: tagged" || bad "weekly: rc $rc: $out"
[ "$(at 'refs/tags/v9.9.1^{commit}')" = "$m" ] && [ "$(git -C "$T/origin.git" cat-file -t refs/tags/v9.9.1)" = tag ] \
    && ok "the pushed tag is annotated and points at main" || bad "tag shape: $(at 'refs/tags/v9.9.1^{commit}') vs $m"
git -C "$W" verify-tag v9.9.1 >/dev/null 2>&1 && ok "the tag is signed by the key the signers file trusts" || bad "verify-tag v9.9.1"
[ "$(git -C "$W" cat-file tag v9.9.1 | sed -n '/^$/q; s/^tag //p')" = v9.9.1 ] \
    && [ "$(git -C "$W" cat-file tag v9.9.1 | sed -n '/^$/,$p' | sed -n 2p)" = "spark v9.9.1" ] \
    && ok "the tag object is named v9.9.1 and says 'spark v9.9.1'" || bad "tag object: $(git -C "$W" cat-file tag v9.9.1 | head -8)"
rc=0; out=$(tagsh --now) || rc=$?
[ "$rc" -eq 0 ] && [ "$out" = "tag: v9.9.1 exists; nothing to do" ] && ok "a second run finds the tag and stops" || bad "again: rc $rc: $out"

# --- an S1: at once, whatever the day --------------------------------------
log v9.9.2 '- S1: the install died on a missing tar (#8)'
m2=$(git -C "$W" rev-parse HEAD)
rc=0; out=$(tagsh --weekday "$other") || rc=$?
[ "$rc" -eq 0 ] && [ "$out" = "tag: v9.9.2 at $(printf '%s' "$m2" | cut -c1-7) (an S1 or S2 fix ships at once)" ] \
    && [ "$(at 'refs/tags/v9.9.2^{commit}')" = "$m2" ] && ok "an S1 is tagged at once, off the weekly day" || bad "S1: rc $rc: $out"

# --- a section without a severity bullet -----------------------------------
log v9.9.3 '- a bullet without a severity (#9)'
rc=0; out=$(tagsh --now) || rc=$?
[ "$rc" -eq 1 ] && printf '%s\n' "$out" | grep -q "^! tag: the ## v9.9.3 section has no '- S<n>: ... (#N)' bullet" \
    && [ "$(at refs/tags/v9.9.3)" = none ] && ok "no severity bullet: refused, nothing tagged" || bad "no severity: rc $rc: $out"
rc=0; out=$(tagsh --weekday 9) || rc=$?
[ "$rc" -eq 2 ] && ok "--weekday outside 1..7 is usage" || bad "usage: rc $rc: $out"

[ "$fail" -eq 0 ] && echo "tag_test: all ok" || { echo "tag_test: FAILED"; exit 1; }
