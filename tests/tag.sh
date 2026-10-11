#!/bin/sh
# spark tests/tag.sh -- tag a patch release. main holds a patch when
# docs/CHANGELOG.md's top heading has three parts, `## vX.Y.Z`: the fixes
# of the patch lane (AGENTS.md, "The patch lane"), one bullet each,
# `- S<n>: ... (#N)`. This script is the policy. A machine that holds a
# release key runs it every hour (CLAUDE.md, "Releasing").
#
#   sh tests/tag.sh                 tag origin/main when its turn has come
#   sh tests/tag.sh --dry-run       say what it would do, touch nothing
#   sh tests/tag.sh --now           an S3 or S4 patch today, not on the day
#   sh tests/tag.sh --weekday N     the weekly day, 1 Monday to 7 Sunday
#                                   (default 7; SPARK_TAG_WEEKDAY too)
#
# The turn: a section with an S1 or S2 bullet is tagged at once; a section
# of S3 and S4 alone waits for the weekly day. A two-part heading is a
# major, which a person tags: nothing is done. The tag is made only when
# ci.yml passed for that exact commit (tests/land.sh --passed), signed by
# the key this clone's git config names (gpg.format ssh, user.signingkey)
# and pushed as refs/tags/vX.Y.Z. Exit 0 tagged or nothing to do, 1
# refused, 2 usage.
set -eu
weekday=${SPARK_TAG_WEEKDAY:-7}
dry=0
now=0
usage() { echo "usage: sh tests/tag.sh [--dry-run] [--now] [--weekday N]" >&2; exit 2; }
say() { printf 'tag: %s\n' "$*"; }
no() { printf '! tag: %s\n' "$*"; }
while [ $# -gt 0 ]; do
    case $1 in
        --dry-run) dry=1 ;;
        --now) now=1 ;;
        --weekday) [ $# -ge 2 ] || usage; weekday=$2; shift ;;
        *) usage ;;
    esac
    shift
done
case $weekday in [1-7]) ;; *) usage ;; esac
here=$(cd "$(dirname "$0")" && pwd)
cd "$(git rev-parse --show-toplevel)"

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

# the section's severities, one per bullet: S1 and S2 ship at once
sev=$(git show "$sha:docs/CHANGELOG.md" \
      | awk -v h="$top" '$0 == h { on = 1; next } on && /^## / { exit } on && /^- S[1-4]: / { print substr($0, 3, 2) }' \
      | tr '\n' ' ')
[ -n "$sev" ] || { no "the $top section has no '- S<n>: ... (#N)' bullet (AGENTS.md, The patch lane)"; exit 1; }
today=$(date +%u)
case " $sev" in
    *" S1 "*|*" S2 "*) why="an S1 or S2 fix ships at once" ;;
    *) if [ "$now" -eq 1 ]; then why="--now"
       elif [ "$today" = "$weekday" ]; then why="the weekly day"
       else say "$tag waits for weekday $weekday, today is $today: ${sev}-- S3 and S4 ship weekly, --now ships today"; exit 0
       fi ;;
esac

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
