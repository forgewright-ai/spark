#!/bin/sh
# spark tests/tag.sh -- tag a patch release. main holds a patch when
# docs/CHANGELOG.md's top heading has three parts, `## vX.Y.Z`: the fixes
# of the patch lane (AGENTS.md, "The patch lane"), one bullet each,
# `- S<n>: ... (#N)`. This script is the policy. A machine that holds a
# release key runs it every hour (docs/REFERENCE.md, "Releasing").
#
#   sh tests/tag.sh                 tag origin/main when its turn has come
#   sh tests/tag.sh --dry-run       say what it would do, touch nothing
#   sh tests/tag.sh --now           a person's word: today, with no wait
#   sh tests/tag.sh --weekday N     the weekly day, 1 Monday to 7 Sunday
#                                   (default 7; SPARK_TAG_WEEKDAY too)
#   sh tests/tag.sh --cool H        the hours a fix rests on main before
#                                   its tag (default 6; SPARK_TAG_COOL too)
#
# The turn: a section with an S1 or S2 bullet is tagged once the fix has
# rested the cooling hours, so a person has time to see the issue and
# the commit; a section of S3 and S4 alone waits for the weekly day as
# well. --now skips both. A two-part heading is a major, which a person
# tags: nothing is done.
#
# Its own gates, whatever CI said: the tag it patches is itself a
# release, signed by a key the installed spark trusts (its allowed-signers
# at $HOME/.spark, or SPARK_TAG_SIGNERS; this clone's own file only when
# no spark is installed) and named as its object says -- a tag anyone with
# a write token could push is no base for a patch; no protected path
# differs from the tag it patches (tests/patch_test.py --protected is the
# one list);
# every bullet's issue exists on GitHub, is labelled `approved` and
# carries the bullet's severity (the public API through curl, no
# token); ci.yml passed for the exact commit (tests/land.sh --passed);
# the cooling hours are counted from when the commit reached main by
# GitHub's clock (tests/land.sh --landed-at), never from a date the
# committer wrote.
# Then the tag is signed by the key this clone's git config names
# (gpg.format ssh, user.signingkey) and pushed as refs/tags/vX.Y.Z; a
# refused push undoes it. Exit 0 tagged or nothing to do, 1 refused, 2
# usage. SPARK_CURL names the curl (a test seam).
set -eu
weekday=${SPARK_TAG_WEEKDAY:-7}
cool=${SPARK_TAG_COOL:-6}
CURL=${SPARK_CURL:-curl}
dry=0
now=0
usage() { echo "usage: sh tests/tag.sh [--dry-run] [--now] [--weekday N] [--cool H]" >&2; exit 2; }
say() { printf 'tag: %s\n' "$*"; }
no() { printf '! tag: %s\n' "$*"; }
while [ $# -gt 0 ]; do
    case $1 in
        --dry-run) dry=1 ;;
        --now) now=1 ;;
        --weekday) [ $# -ge 2 ] || usage; weekday=$2; shift ;;
        --cool) [ $# -ge 2 ] || usage; cool=$2; shift ;;
        *) usage ;;
    esac
    shift
done
case $weekday in [1-7]) ;; *) usage ;; esac
case $cool in ''|*[!0-9]*) usage ;; esac
here=$(cd "$(dirname "$0")" && pwd)
cd "$(git rev-parse --show-toplevel)"

# repo_of URL: OWNER/REPO from a github.com remote (https, ssh, scp-like)
repo_of() {
    r=$1
    case $r in
        https://github.com/*) r=${r#https://github.com/} ;;
        ssh://*@github.com/*) r=${r#ssh://*@github.com/} ;;
        *@github.com:*)       r=${r#*@github.com:} ;;
        *)                    return 1 ;;
    esac
    r=${r%/}; r=${r%.git}
    case $r in
        */*/*|*[!A-Za-z0-9._/-]*|/*|*/|'') return 1 ;;
        */*) printf '%s\n' "$r" ;;
        *)   return 1 ;;
    esac
}
repo=$(repo_of "$(git config --get remote.origin.url || true)") || { no "origin is not on github.com"; exit 1; }

git fetch -q origin '+refs/heads/main:refs/remotes/origin/main' 'refs/tags/*:refs/tags/*'
sha=$(git rev-parse refs/remotes/origin/main)
short=$(printf '%s' "$sha" | cut -c1-7)
top=$(git show "$sha:docs/CHANGELOG.md" | grep -m1 '^## v' || true)
ver=${top#"## v"}
case $ver in
    '') no "docs/CHANGELOG.md on main has no '## vX.Y' heading"; exit 1 ;;
    *.*.*) ;;
    *) say "main is at $short, a major ($top): a person tags it"; exit 0 ;;
esac
tag=v$ver
if git rev-parse -q --verify "refs/tags/$tag" >/dev/null 2>&1; then
    say "$tag exists; nothing to do"
    exit 0
fi

# the tag it patches: the release for Z = 1, else the patch before
patch=${ver##*.}
mm=${ver%.*}
case $patch in ''|*[!0-9]*) no "$top is not a vX.Y.Z heading"; exit 1 ;; esac
if [ "$patch" -eq 1 ]; then base=v$mm; else base=v$mm.$((patch - 1)); fi
git rev-parse -q --verify "refs/tags/$base" >/dev/null 2>&1 \
    || { no "$tag patches $base, and no such tag exists -- nothing tagged"; exit 1; }
# ... and that tag is a release: signed by a key the installed spark
# trusts, named as its object says. The fence below compares against it,
# so a tag that is not a release would make any commit a patch
signers=${SPARK_TAG_SIGNERS:-$HOME/.spark/allowed-signers}
[ -f "$signers" ] || signers=$PWD/allowed-signers
git -c gpg.format=ssh -c gpg.ssh.allowedSignersFile="$signers" verify-tag "$base" >/dev/null 2>&1 \
    || { no "$base is not signed by a key the installed allowed-signers trust -- not a release, nothing tagged"; exit 1; }
named=$(git cat-file tag "$base" 2>/dev/null | sed -n '/^$/q; s/^tag //p')
[ "$named" = "$base" ] || { no "the tag object $base points to is named '$named' -- nothing tagged"; exit 1; }

# the section's bullets, each joined into one line: `- S<n>: ... (#N)`
bullets=$(git show "$sha:docs/CHANGELOG.md" | awk -v h="$top" '
    $0 == h { on = 1; next }
    on && /^## / { exit }
    !on { next }
    /^- / { if (b != "") print b; b = $0; next }
    /^  / && b != "" { sub(/^ +/, " "); b = b $0; next }
    { if (b != "") print b; b = "" }
    END { if (b != "") print b }')
[ -n "$bullets" ] || { no "the $top section has no bullet (AGENTS.md, The patch lane)"; exit 1; }

# the fence, again, here: whatever CI said, a protected path that differs
# from the tag it patches is not a patch
prot=$(python3 "$here/patch_test.py" --protected) || { no "tests/patch_test.py --protected failed"; exit 1; }
# shellcheck disable=SC2086 # the list is paths without spaces, one a word
changed=$(git diff --name-only "$base" "$sha" -- $prot)
[ -z "$changed" ] \
    || { no "$tag changes a protected path since $base: $(printf '%s ' "$changed" | tr '\n' ' ')-- not a patch, nothing tagged"; exit 1; }

# every bullet names a severity and an issue; the issue exists, is
# approved and carries that severity (the public API, no token)
sevs=""
set -f
oldifs=$IFS
IFS='
'
for b in $bullets; do
    IFS=$oldifs
    head=$(printf '%s' "$b" | cut -c1-60)
    case $b in
        "- S"[1-4]": "*) ;;
        *) no "the $top section has a bullet that is not '- S<n>: ... (#N)': $head"; exit 1 ;;
    esac
    sev=${b#- }; sev=${sev%%:*}
    n=${b##*(#}; n=${n%)}
    case $n in ''|*[!0-9]*) no "the bullet for $sev names no issue: $head"; exit 1 ;; esac
    json=$("$CURL" -fsS -m 30 -H 'Accept: application/vnd.github+json' "https://api.github.com/repos/$repo/issues/$n" 2>/dev/null) \
        || { no "could not read issue #$n from GitHub -- nothing tagged"; exit 1; }
    labels=$(printf '%s' "$json" | python3 -c 'import json, sys
print(" ".join(l.get("name", "") for l in json.load(sys.stdin).get("labels", [])))' 2>/dev/null) \
        || { no "issue #$n: GitHub's answer could not be read -- nothing tagged"; exit 1; }
    case " $labels " in *" approved "*) ;; *) no "issue #$n is not labelled approved -- nothing tagged"; exit 1 ;; esac
    case " $labels " in *" $sev "*) ;; *) no "issue #$n is not labelled $sev, as its bullet says -- nothing tagged"; exit 1 ;; esac
    sevs="$sevs$sev "
    IFS='
'
done
IFS=$oldifs
set +f

# the turn
today=$(date +%u)
why=""
case " $sevs" in *" S1 "*|*" S2 "*) why="an S1 or S2 fix" ;; esac
if [ "$now" -eq 1 ]; then why="--now"
elif [ -n "$why" ]; then :
elif [ "$today" = "$weekday" ]; then why="the weekly day"
else say "$tag waits for weekday $weekday, today is $today: ${sevs}-- S3 and S4 ship weekly, --now ships today"; exit 0
fi
# the cooling hours: a fix rests on main before its tag, counted from when
# it reached main by GitHub's clock (its first ci.yml run there) -- a
# commit header is the committer's to write
if [ "$now" -eq 0 ]; then
    landed=$(sh "$here/land.sh" --landed-at "$sha" 2>/dev/null) \
        || { no "could not ask GitHub when $short reached main -- nothing tagged"; exit 1; }
    age=$(( $(date +%s) - landed ))
    if [ "$age" -lt $((cool * 3600)) ]; then
        say "$tag waits: main at $short is $((age / 60)) min old, a fix rests $cool hours before its tag (--now skips the wait)"
        exit 0
    fi
fi

rc=0; sh "$here/land.sh" --passed "$sha" >/dev/null 2>&1 || rc=$?
case $rc in
    0) ;;
    1) no "ci.yml has not passed for main at $short -- nothing tagged"; exit 1 ;;
    *) no "could not ask GitHub whether ci.yml passed for $short -- nothing tagged"; exit 1 ;;
esac
if [ "$dry" -eq 1 ]; then
    say "would tag $tag at $short ($why):"
    say "  git tag -s $tag -m 'spark $tag' $short"
    say "  git push origin refs/tags/$tag"
    exit 0
fi
git tag -s "$tag" -m "spark $tag" "$sha"
# a refused push undoes the local tag: the next run may try again
if ! git push -q origin "refs/tags/$tag" 2>/dev/null; then
    git tag -d "$tag" >/dev/null 2>&1 || true
    no "the push of $tag was refused; the tag is undone, nothing changed"
    exit 1
fi
say "$tag at $short ($why)"
