#!/bin/sh
# spark tests/get_test.sh -- the one-liner against a throwaway HOME and a
# file:// bare clone of this tree. Hermetic: no network, and a sudo that
# shouts. Proves: a fresh clone with no SPARK_REF lands detached on the
# newest tag on origin, SPARK_REF=main lands attached to main, the second
# run on an attached clone pulls, a detached clone moves to a newer SIGNED
# tag on origin and stays put at an unsigned one (a fresh clone of which is
# refused and removed), the refusals (a foreign directory, no git, an old
# python3), the pipe form, and the hand-off to `spark setup` in its non-interactive mode
# (SPARK_NO_APPLY=1: site.env is written, nothing is applied).
set -eu
REPO=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
export HOME="$T/home" XDG_CONFIG_HOME="$T/home/.config" XDG_STATE_HOME="$T/home/.local/state" XDG_DATA_HOME="$T/home/.local/share"
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
mkdir -p "$HOME" "$T/bin"
printf '#!/bin/sh\necho "SUDO CALLED: $*" >&2; exit 97\n' > "$T/bin/sudo"; chmod +x "$T/bin/sudo"
export PATH="$T/bin:$PATH"
unset SPARK_HOME SPARK_NO_APPLY SITE_AI_MODEL SPARK_REF
fail=0
ok() { printf '  ok   %s\n' "$1"; }
bad() { printf '  FAIL %s\n' "$1"; fail=1; }
all=''
note() { all="$all
$1"; }

echo "get_test: $T"
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
if [ -n "$(git -C "$REPO" status --porcelain)" ]; then
    tree=$(GIT_INDEX_FILE="$T/index" sh -c 'cd "$1" && git add -A >/dev/null && git write-tree' sh "$REPO")
    commit=$(git -C "$REPO" commit-tree "$tree" -p HEAD -m "get_test: the working tree")
    git -C "$REPO" push -q --no-verify "$T/origin.git" "$commit:refs/heads/get-test"   # no pre-push hook: it runs this test
    git -C "$T/origin.git" symbolic-ref HEAD refs/heads/get-test
fi
# the real repository's release tags are signed by a key this fixture does
# not hold: drop them, give the tested tip one commit whose allowed-signers
# is a throwaway key's public half, and tag with that key -- get moves a
# clone to a tag that key signed and to no other
for t in $(git -C "$T/origin.git" tag -l); do git -C "$T/origin.git" tag -d "$t" >/dev/null; done
ssh-keygen -q -t ed25519 -N '' -f "$T/key"
printf 'spark-release namespaces="git" %s\n' "$(cut -d' ' -f1,2 "$T/key.pub")" > "$T/allowed-signers"
head=$(git -C "$T/origin.git" symbolic-ref HEAD)
tip=$(git -C "$T/origin.git" rev-parse "$head")
blob=$(git -C "$T/origin.git" hash-object -w "$T/allowed-signers")
stree=$(GIT_INDEX_FILE="$T/signers-index" sh -c 'git -C "$1" read-tree "$2" && git -C "$1" update-index --add --cacheinfo "100644,$3,allowed-signers" && git -C "$1" write-tree' sh "$T/origin.git" "$tip" "$blob")
tip=$(git -C "$T/origin.git" commit-tree "$stree" -p "$tip" -m "get_test: the release key")
git -C "$T/origin.git" update-ref "$head" "$tip"
# sign TAG COMMIT: an annotated tag signed with the release key
sign() { git -C "$T/origin.git" -c gpg.format=ssh -c user.signingkey="$T/key" tag -s -m "$1" "$1" "$2"; }
sign v1.0 "$tip"
export SPARK_URL="file://$T/origin.git"
newest_tag=$(git -C "$T/origin.git" tag -l 'v[0-9]*' --sort=-v:refname | head -1)

# 1. --clone-only, no ref: a full clone at ~/.spark, detached at the newest tag
out=$(sh "$REPO/get" --clone-only 2>&1) || bad "get --clone-only failed: $out"; note "$out"
printf '%s\n' "$out" | head -1 | grep -q '^spark get -- clone .* to ~/.spark, then spark setup (no sudo)$' \
    && ok "the first line says what it does" || bad "first line: $(printf '%s\n' "$out" | head -1)"
[ -x "$HOME/.spark/bin/spark" ] && ok "cloned to ~/.spark, bin/spark present" || bad "no bin/spark in the clone"
# a full clone: get passes no --depth; a CI checkout is itself shallow, so the
# clone can only be as deep as its source
! grep -q -- '--depth' "$REPO/get" && ok "get clones with no --depth" || bad "get clones shallow"
if [ "$(git -C "$REPO" rev-parse --is-shallow-repository)" = false ]; then
    [ "$(git -C "$HOME/.spark" rev-parse --is-shallow-repository)" = false ] && ok "a full clone, not shallow" || bad "shallow clone"
fi
[ "$(git -C "$HOME/.spark" remote get-url origin)" = "$SPARK_URL" ] && ok "remote origin is SPARK_URL" || bad "origin: $(git -C "$HOME/.spark" remote get-url origin)"
if [ -n "$newest_tag" ]; then
    ! git -C "$HOME/.spark" symbolic-ref -q HEAD >/dev/null 2>&1 && ok "no SPARK_REF: lands detached" || bad "no SPARK_REF: attached to a branch"
    [ "$(git -C "$HOME/.spark" describe --tags --exact-match 2>/dev/null)" = "$newest_tag" ] \
        && ok "no SPARK_REF: at the newest tag $newest_tag" || bad "no SPARK_REF: not at $newest_tag"
else
    bad "origin has no v* tag to test the default landing against"
fi

# 2. SPARK_REF=main: a fresh clone attaches to main, not the newest tag
out=$(SPARK_HOME="$T/main-clone" SPARK_REF=main sh "$REPO/get" --clone-only 2>&1) && ok "SPARK_REF=main clone exits 0" || bad "SPARK_REF=main: $out"; note "$out"
[ "$(git -C "$T/main-clone" symbolic-ref -q --short HEAD 2>/dev/null)" = main ] \
    && ok "SPARK_REF=main lands attached to main" || bad "SPARK_REF=main: $(git -C "$T/main-clone" symbolic-ref -q --short HEAD 2>/dev/null)"

# 3. the second run, on that attached clone, pulls --ff-only and exits 0
tip=$(git -C "$T/origin.git" rev-parse refs/heads/main)
otree=$(git -C "$T/origin.git" rev-parse "$tip^{tree}")
newc=$(git -C "$T/origin.git" commit-tree "$otree" -p "$tip" -m "get_test: one more commit on main")
git -C "$T/origin.git" update-ref refs/heads/main "$newc"
out=$(SPARK_HOME="$T/main-clone" sh "$REPO/get" --clone-only 2>&1) && ok "second run exits 0" || bad "second run: $out"; note "$out"
printf '%s\n' "$out" | grep -q 'is spark already: pulled' && ok "second run pulls" || bad "second run did not pull: $out"
[ "$(git -C "$T/main-clone" rev-parse HEAD)" = "$newc" ] && ok "second run landed on the new commit" || bad "second run: HEAD is $(git -C "$T/main-clone" rev-parse HEAD)"

# 4. a detached clone (from step 1) moves to a newer tag pushed to origin
if [ -n "$newest_tag" ]; then
    base=$(git -C "$T/origin.git" rev-parse "$newest_tag^{commit}")
    rtree=$(git -C "$T/origin.git" rev-parse "$base^{tree}")
    newer=$(git -C "$T/origin.git" commit-tree "$rtree" -p "$base" -m "get_test: a newer release")
    newer_tag="${newest_tag%.*}.$((${newest_tag##*.} + 1))"
    sign "$newer_tag" "$newer"
    out=$(sh "$REPO/get" --clone-only 2>&1) && ok "moved run exits 0" || bad "moved run: $out"; note "$out"
    printf '%s\n' "$out" | grep -q "moved to $newer_tag" && ok "detached clone moves to the newer signed tag" || bad "moved run: $out"
    [ "$(git -C "$HOME/.spark" describe --tags --exact-match 2>/dev/null)" = "$newer_tag" ] && ok "landed on $newer_tag" || bad "not on $newer_tag"

    # 4b. an unsigned tag on origin is no release: the detached clone stays
    #     put, and a fresh clone is refused and removed -- exit 1, before
    #     spark setup
    unsigned="${newer_tag%.*}.$((${newer_tag##*.} + 1))"
    c3=$(git -C "$T/origin.git" commit-tree "$rtree" -p "$newer" -m "get_test: $unsigned, unsigned")
    git -C "$T/origin.git" tag "$unsigned" "$c3"
    rc=0; out=$(sh "$REPO/get" --clone-only 2>&1) || rc=$?; note "$out"
    [ "$rc" -eq 1 ] && ok "unsigned tag: the re-run refuses, exit 1" || bad "unsigned tag re-run: rc $rc: $out"
    printf '%s\n' "$out" | grep -q "spark get: $unsigned is not signed by a known key: refused" && ok "unsigned tag: the refusal names it" || bad "unsigned tag: $out"
    [ "$(git -C "$HOME/.spark" describe --tags --exact-match 2>/dev/null)" = "$newer_tag" ] && ok "unsigned tag: still at $newer_tag" || bad "unsigned tag: moved"
    rc=0; out=$(SPARK_HOME="$T/refused" sh "$REPO/get" 2>&1 < /dev/null) || rc=$?; note "$out"
    [ "$rc" -eq 1 ] && printf '%s\n' "$out" | grep -q "$unsigned is not signed by a known key: refused" && ok "unsigned tag: a fresh clone is refused before setup" || bad "unsigned tag fresh clone: rc $rc: $out"
    [ ! -e "$T/refused" ] && ok "unsigned tag: the refused clone is gone" || bad "unsigned tag: the refused clone stayed"
    git -C "$T/origin.git" tag -d "$unsigned" >/dev/null   # the runs below land on $newer_tag again
fi

# 5. a non-empty directory that is not spark is refused, untouched
mkdir -p "$T/other"; echo keep > "$T/other/file"
if out=$(SPARK_HOME="$T/other" sh "$REPO/get" --clone-only 2>&1); then bad "a foreign directory was not refused"; else ok "a foreign directory is refused"; fi
note "$out"
printf '%s\n' "$out" | grep -q 'exists and is not spark -- move it or set SPARK_HOME' && ok "the refusal names the remedy" || bad "refusal text: $out"
[ "$(cat "$T/other/file")" = keep ] && [ ! -e "$T/other/.git" ] && ok "the directory is untouched" || bad "the directory was touched"

# 6. the pipe form: the script on stdin, arguments after -s --
out=$(SPARK_HOME="$T/piped" sh -s -- --clone-only < "$REPO/get" 2>&1) && ok "pipe form exits 0" || bad "pipe form: $out"; note "$out"
[ -x "$T/piped/bin/spark" ] && ok "pipe form cloned to SPARK_HOME" || bad "pipe form: no clone"

# 7. no git on PATH: a PATH of only the other tools get needs
mkdir "$T/nogit"
for t in sh uname ls python3 apt-get pacman xbps-install xcode-select; do
    p=$(command -v "$t" 2>/dev/null || true); [ -z "$p" ] || ln -s "$p" "$T/nogit/$t"
done
if out=$(PATH="$T/nogit" SPARK_HOME="$T/nogit-home" /bin/sh "$REPO/get" --clone-only 2>&1); then bad "no git: not refused"; else ok "no git: refused"; fi
note "$out"
printf '%s\n' "$out" | grep -q 'missing: git' && ok "no git: the refusal names git" || bad "no git: $out"
[ ! -e "$T/nogit-home" ] && ok "no git: nothing cloned" || bad "no git: a clone appeared"

# 7b. the family probe (get's Linux arm; a uname stub says Linux, so both
#     OSes prove it): a PATH with none of apt-get, pacman or xbps-install is
#     refused naming the three, before any clone; an xbps-install alone
#     passes it (Void) and the clone lands; a musl loader where SPARK_LD_MUSL
#     points refuses in one line (the pinned engine is a glibc build)
tools() {   # tools DIR -- what get runs after the probe, and a uname that says Linux x86_64
    mkdir -p "$1"
    for t in sh ls python3 git ssh-keygen head rm find cut; do p=$(command -v "$t" 2>/dev/null || true); [ -z "$p" ] || ln -s "$p" "$1/$t"; done
    printf '#!/bin/sh\ncase ${1:-} in -s) echo Linux ;; -m) echo x86_64 ;; *) exec /usr/bin/uname "$@" ;; esac\n' > "$1/uname"; chmod +x "$1/uname"
}
tools "$T/nopm"
rc=0; out=$(PATH="$T/nopm" SPARK_HOME="$T/nopm-home" /bin/sh "$REPO/get" --clone-only 2>&1) || rc=$?; note "$out"
[ "$rc" -eq 1 ] && ok "no apt-get, pacman or xbps-install: refused, exit 1" || bad "no package manager: rc $rc: $out"
printf '%s\n' "$out" | grep -qF 'spark get: no apt-get, pacman or xbps-install -- a Debian-family, Arch or Void Linux in this version' \
    && ok "the refusal names the three managers and the three families" || bad "no package manager: $out"
[ ! -e "$T/nopm-home" ] && ok "no package manager: nothing cloned" || bad "no package manager: a clone appeared"
tools "$T/xbps"; printf '#!/bin/sh\nexit 0\n' > "$T/xbps/xbps-install"; chmod +x "$T/xbps/xbps-install"
out=$(PATH="$T/xbps" SPARK_LD_MUSL="$T/no-ld-musl-*.so.1" SPARK_HOME="$T/xbps-home" /bin/sh "$REPO/get" --clone-only 2>&1) \
    && ok "xbps-install alone: the probe passes (Void), get runs on" || bad "xbps-install alone: $out"; note "$out"
[ -x "$T/xbps-home/bin/spark" ] && ok "xbps-install alone: the clone landed" || bad "xbps-install alone: no clone"
: > "$T/ld-musl-x86_64.so.1"
rc=0; out=$(PATH="$T/xbps" SPARK_LD_MUSL="$T/ld-musl-x86_64.so.1" SPARK_HOME="$T/musl-home" /bin/sh "$REPO/get" --clone-only 2>&1) || rc=$?; note "$out"
[ "$rc" -eq 1 ] && printf '%s\n' "$out" | grep -qF "spark get: musl libc: the pinned engine is a glibc build -- Void's glibc flavour runs spark" \
    && ok "a musl loader: refused in one line, exit 1" || bad "musl: rc $rc: $out"
[ ! -e "$T/musl-home" ] && ok "a musl loader: nothing cloned" || bad "musl: a clone appeared"

# 8. an old python3: the version check fails
mkdir "$T/oldpy"; printf '#!/bin/sh\nexit 1\n' > "$T/oldpy/python3"; chmod +x "$T/oldpy/python3"
if out=$(PATH="$T/oldpy:$PATH" SPARK_HOME="$T/oldpy-home" sh "$REPO/get" --clone-only 2>&1); then bad "old python3: not refused"; else ok "old python3: refused"; fi
note "$out"
printf '%s\n' "$out" | grep -q 'python3>=3.9' && ok "old python3: the refusal names 3.9" || bad "old python3: $out"

# 9. the hand-off: get without --clone-only execs spark setup; stdin is not
#    a tty, so setup takes every default; SITE_AI_MODEL=none and
#    SPARK_NO_APPLY=1 keep it from downloading or applying anything.
#    SPARK_REF=main: today's code under test, not whatever the newest
#    release tag happens to be
out=$(SPARK_HOME="$T/handoff" SPARK_REF=main SPARK_NO_APPLY=1 SITE_AI_MODEL=none sh "$REPO/get" < /dev/null 2>&1) && ok "get -> spark setup (non-interactive) exits 0" || bad "get -> setup: rc $? $(printf '%s\n' "$out" | tail -5)"
note "$out"
site="$HOME/.config/spark/site.env"
[ -f "$site" ] && grep -q '^SITE_AI_MODEL=none$' "$site" && ok "setup wrote SITE_AI_MODEL=none" || bad "site.env: $(cat "$site" 2>/dev/null | grep SITE_AI_MODEL)"
grep -q 'SITE_SHELL' "$site" 2>/dev/null && bad "setup wrote a shell key (there is none)" || ok "setup writes no shell key"
printf '%s\n' "$out" | grep -q 'GB for models' && ok "setup printed the table header" || bad "no table header"
printf '%s\n' "$out" | grep -q 'open a new shell' && ok "setup printed the closing block" || bad "no closing block"
printf '%s\n' "$out" | grep -q 'no model chosen' && ok "setup said no model was chosen" || bad "no 'no model chosen' line"

# 10. sudo was never called, anywhere above
printf '%s\n' "$all" | grep -q 'SUDO CALLED' && bad "sudo was called" || ok "sudo never called"

[ "$fail" -eq 0 ] && echo "get_test: all ok" || { echo "get_test: FAILED"; exit 1; }
