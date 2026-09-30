#!/bin/sh
# spark tests/finish_test.sh -- the runit finish scripts
# (templates/.config/spark/sv/spark-{serve,forge}/finish), run the way
# runsv runs them: in the service dir, with the run script's exit code
# and signal as $1 and $2. sv and sleep are stubs that log, so nothing
# waits and no real service is touched. Proves: 78 (EX_CONFIG) stands
# the service down (sv down on its own dir), a clean exit and a TERM
# (sv down, sv restart, the shutdown) restart at once with no wait, and
# a crash waits 15 s like the systemd unit's RestartSec.
set -eu
REPO=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
fail=0
ok() { printf '  ok   %s\n' "$1"; }
bad() { printf '  FAIL %s\n' "$1"; fail=1; }
echo "finish_test: $T"

mkdir -p "$T/bin"
printf '#!/bin/sh\necho "sv $*" >> "$STUB_LOG"\n' > "$T/bin/sv"
printf '#!/bin/sh\necho "sleep $*" >> "$STUB_LOG"\n' > "$T/bin/sleep"
chmod +x "$T/bin/sv" "$T/bin/sleep"

# fin UNIT CODE SIGNAL: run UNIT's finish in its own dir, as runsv does;
# prints the exit code, then what the stubs were asked
fin() {
    d="$T/sv/spark-$1"; mkdir -p "$d"; : > "$T/log"
    rc=0
    (cd "$d" && STUB_LOG="$T/log" PATH="$T/bin:$PATH" sh "$REPO/templates/.config/spark/sv/spark-$1/finish" "$2" "$3") || rc=$?
    printf 'rc %s|%s\n' "$rc" "$(tr '\n' ';' < "$T/log")"
}

for u in serve forge; do
    d="$T/sv/spark-$u"
    [ -x "$REPO/templates/.config/spark/sv/spark-$u/finish" ] && ok "$u: finish is tracked executable" || bad "$u: finish not executable"
    got=$(fin "$u" 78 0)
    [ "$got" = "rc 0|sv down $d;" ] && ok "$u: 78 stands it down (sv down on its own dir, no wait)" || bad "$u 78: $got"
    got=$(fin "$u" 0 0)
    [ "$got" = "rc 0|" ] && ok "$u: a clean exit restarts at once (no wait, no sv)" || bad "$u clean exit: $got"
    got=$(fin "$u" -1 15)
    [ "$got" = "rc 0|" ] && ok "$u: a TERM (sv down, restart, shutdown) is no crash: no wait" || bad "$u TERM: $got"
    got=$(fin "$u" 1 0)
    [ "$got" = "rc 0|sleep 15;" ] && ok "$u: a crash waits 15 s before runsv runs it again" || bad "$u crash: $got"
    got=$(fin "$u" -1 9)
    [ "$got" = "rc 0|sleep 15;" ] && ok "$u: a KILL is a crash: it waits 15 s" || bad "$u KILL: $got"
done

[ "$fail" -eq 0 ] && echo "finish_test: all ok" || { echo "finish_test: FAILED"; exit 1; }
