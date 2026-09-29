# spark widget.zsh -- the AI at the prompt, for zsh. Sourced by .zshrc
# after fzf. Symlinked from the spark repository.
#
#   ? words    or    words?     Enter sends the line to `spark line`; the
#              command it returns lands IN your line with a hint in the row
#              above the prompt. Nothing runs until you press Enter again.
#   Esc s      asks about whatever line you are on, question mark or not.
#              On an empty line after a failure it puts the failed command
#              back, piped to explain; after the fix works, it offers to
#              keep what happened (spark memory add). You press Enter.
#   * failed   a nonzero exit prints that one line above the next prompt.
#              No model call, no fork, nothing written: the command you
#              typed on one line and its exit code live in this pane's
#              variables and die with it.
#   Esc k      moves spark's row: 1, 2 or 3 rows above the line you type
#              on (`spark height N` keeps it). A two-line prompt needs 2.
#   spark off / spark on        silence / restore (a flag file, checked at
#              every Enter and on the failing path, so one `spark off`
#              reaches every pane at once)
#   SPARK_OFF=1                 in the environment: bind nothing at all
#
# The look file ($STATE_DIR/look, written by `spark awaken`, `spark look`
# and `spark height`) is read line by line when it changes -- never
# sourced. Until the machine is awake it only moves the row; awake, it
# adds the built-in colours, the news once, a greeting after an absence
# and how long a failed command ran.

[[ -o interactive ]] || return 0
[[ -n ${_SPARK_WIDGET_LOADED:-} ]] && return 0
_SPARK_WIDGET_LOADED=1
[[ -n ${SPARK_OFF:-} ]] && return 0

: "${SPARK_BIN:=spark}"
# one mark, both OSes: the answer and warn marks are ASCII everywhere
_spark_h='*' _spark_w='!'
# the console font cannot draw …; ASCII there (TERM=linux) or on request
if [[ $TERM == linux || -n ${SPARK_ASCII:-} ]] || { [[ -n ${TMUX:-} ]] && [[ $(tmux display -p '#{client_termname}' 2>/dev/null) == linux ]]; }; then _spark_d='...'
else _spark_d='…'; fi
SPARK_DIR=${XDG_STATE_HOME:-$HOME/.local/state}/spark

# --- liveness marker ---------------------------------------------------------
# contract 6: <shell> <pid> <epoch> [hook] -- the fourth field says this
# shell's exit-code hook is armed; readers ignore fields they do not know.
# EPOCHSECONDS is empty until zsh/datetime is loaded (a bare zsh -f showed
# a two-field marker); load it, and keep 0 as the honest fallback.
zmodload zsh/datetime 2>/dev/null
typeset -g _spark_born=${EPOCHSECONDS:-0}
mkdir -p "$SPARK_DIR/widgets" 2>/dev/null && chmod 700 "$SPARK_DIR" 2>/dev/null
print -r -- "zsh $$ $_spark_born hook" > "$SPARK_DIR/widgets/$$" 2>/dev/null
_spark_gone() { rm -f "$SPARK_DIR/widgets/$$"; }
autoload -Uz add-zsh-hook
add-zsh-hook zshexit _spark_gone

# --- the look: read line by line, never sourced -----------------------------
# KEY=value lines; a value holding a control character (an escape) is
# dropped. The marker above doubles as the stamp: the file is read again
# only when it is newer than the marker, then the marker is written anew.
# SPARK_HEIGHT in the environment wins over the file's HEIGHT.
typeset -g _spark_height=1 _spark_lk_had='' _spark_lk_awake='' _spark_lk_colour=''
typeset -g _spark_lk_words='' _spark_lk_acc='' _spark_lk_warn='' _spark_lk_face=''
_spark_look_read() {
    local f=$SPARK_DIR/look line k v n=0
    _spark_height=1 _spark_lk_had='' _spark_lk_awake='' _spark_lk_colour=''
    _spark_lk_words='' _spark_lk_acc='' _spark_lk_warn='' _spark_lk_face=''
    if [[ -r $f ]]; then
        _spark_lk_had=1
        while (( n++ < 64 )) && { IFS= read -r line || [[ -n $line ]]; }; do
            [[ $line == [A-Z]*=* ]] || continue
            k=${line%%=*} v=${line#*=}
            [[ $v == *[[:cntrl:]]* ]] && continue
            case $k in
                AWAKE) _spark_lk_awake=$v ;;
                COLOUR) _spark_lk_colour=$v ;;
                WORDS) _spark_lk_words=$v ;;
                HEIGHT) [[ $v == [1-5] ]] && _spark_height=$v ;;
                SGR_ACCENT) _spark_lk_acc=$v ;;
                SGR_WARN) _spark_lk_warn=$v ;;
                FACE_IDLE) _spark_lk_face=$v ;;
            esac
        done < "$f"
    fi
    [[ ${SPARK_HEIGHT:-} == [1-5] ]] && _spark_height=$SPARK_HEIGHT
}
_spark_look_check() {
    local f=$SPARK_DIR/look m=$SPARK_DIR/widgets/$$
    if [[ -e $f ]]; then
        [[ -z $_spark_lk_had || $f -nt $m ]] || return 0
    else
        [[ -n $_spark_lk_had ]] || return 0
    fi
    _spark_look_read
    print -r -- "zsh $$ $_spark_born hook" > "$m" 2>/dev/null
}
_spark_look_read

# --- is this line a question? -----------------------------------------------
_spark_is_question() {
    local line=$1 w
    local -a m
    [[ $line == \?* ]] && return 0
    [[ $line == *\? ]] || return 1
    w=${line##*[[:space:]]}
    w=${w%\?}
    if [[ -n $w ]]; then
        m=( ${w}?(N) )          # ${w} is literal (no GLOB_SUBST); the ? is the glob
        (( ${#m} )) && return 1
    fi
    return 0
}

# --- colour: three optional exports, plain without them ---------------------
# SPARK_ACCENT_SGR / SPARK_WARN_SGR are SGR parameter strings (`1;94`);
# any rc may export them from a palette. Unset, or not
# digits and semicolons, the line stays plain. The text is cut to the
# width first, then painted: the escapes never count as columns. A
# `* ...` line gets the mark alone in the accent; a `! ...` line is
# whole in warn. Sets _spark_out. On an awake machine whose colour part
# is auto (a terminal that is not dumb, NO_COLOR unset) or on, the look
# file's built-in values stand in for an export that is not there.
_spark_paint() {
    local t=$1 a=${SPARK_ACCENT_SGR:-} w=${SPARK_WARN_SGR:-}
    _spark_out=$t
    if [[ $_spark_lk_awake == yes ]] && [[ $_spark_lk_colour == on || ( $_spark_lk_colour == auto \
            && $TERM != dumb && -z ${NO_COLOR:-} ) ]]; then
        [[ -n $a ]] || a=$_spark_lk_acc
        [[ -n $w ]] || w=$_spark_lk_warn
    fi
    case $t in
        "$_spark_h "*) [[ -n $a && -z ${a//[0-9;]/} ]] \
            && _spark_out=$'\e['"$a"'m'"$_spark_h"$'\e[0m'"${t#"$_spark_h"}" ;;
        "$_spark_w "*) [[ -n $w && -z ${w//[0-9;]/} ]] \
            && _spark_out=$'\e['"$w"'m'"$t"$'\e[0m' ;;
    esac
}

# --- the hint row: the blank line above the prompt --------------------------
# _spark_height rows up from the cursor (1 unless the look file or
# SPARK_HEIGHT says more: a two-line prompt takes 2), so the edit line must
# be a single row when this runs (a wrapped question would make "the row
# above" the prompt itself), and the text must fit the width (a wrapped
# hint would push the prompt down).
typeset -g _spark_hinted=''   # spark drew in the row above since this prompt came
_spark_say() {
    local t=$1
    [[ -n $t ]] && _spark_hinted=1
    (( ${#t} > COLUMNS - 2 )) && t=${t[1,COLUMNS-3]}$_spark_d
    _spark_paint "$t"
    print -n -- $'\e7\e['"$_spark_height"$'A\r\e[2K'"$_spark_out"$'\e8'
}

# The line streams (contract 4): line 1 -- the command, its danger known --
# arrives first and lands at once; the hint and the proof follow. The
# layout: everything spark says lives in the row above (the mark, the
# pulse, the facts, the hint, an answer); the prompt line holds only the
# command to run, empty for an answer. The mark is painted BEFORE the
# command lands, so a danger line is never in the buffer without its !.
# While spark thinks, the question stays in the line as typed, and line 1
# replaces it. Until the hint comes the cursor waits at the line's start
# (one row below the hint row, however far the line wraps), and keys
# typed meanwhile queue for when the widget returns.
_spark_ask() {
    local line=$1 fd kind cmd hint line3 mark=$_spark_h tail=''
    # the cursor to the line's start: back on the prompt's row, so the
    # hint lands in the blank row above it however far a question wraps
    CURSOR=0; zle -R
    _spark_say "$_spark_h $_spark_d"
    _spark_proof='' _spark_proof_for=''
    # SPARK_HINT_ROW=N: spark line may pulse in that row, N up (text.Busy),
    # while the model answers -- then in the reply's own mark until the hint
    exec {fd}< <(print -r -- "$line" | SPARK_HINT_ROW=$_spark_height "$SPARK_BIN" line --cwd "$PWD" --shell zsh 2>/dev/null)
    IFS= read -r -u $fd kind
    case $kind in
        cmd$'\t'*|danger$'\t'*)
            cmd=${kind#*$'\t'}
            [[ $kind == danger$'\t'* ]] && mark=$_spark_w tail=' -- read it before Enter'
            _spark_say "$mark $_spark_d$tail"
            BUFFER=$cmd; CURSOR=0; zle -R
            IFS= read -r -u $fd hint
            _spark_say "$mark ${hint:-no hint came}$tail"
            IFS= read -r -u $fd line3
            case $line3 in proof$'\t'*) _spark_proof=${line3#proof$'\t'} _spark_proof_for=$cmd ;; esac
            CURSOR=$#BUFFER ;;
        answer)
            BUFFER=''; CURSOR=0; zle -R           # an answer leaves the line empty
            IFS= read -r -u $fd hint
            _spark_say "$_spark_h ${hint:-no answer came}" ;;
        *)
            IFS= read -r -u $fd hint
            [[ -n $kind && $kind != error ]] && hint=$kind    # not contract 4: say what came
            _spark_say "$_spark_h ${hint:-no engine is awake}"
            BUFFER=$line; CURSOR=$#BUFFER ;;      # the question stays yours
    esac
    exec {fd}<&-
    zle -R
}

# --- the failure moment ------------------------------------------------------
# The verbatim command is captured at Enter from $BUFFER -- never from
# history -- and lives in shell variables: per pane, nothing on disk,
# never exported, gone with the shell. A capture still unconsumed at the
# next Enter means no prompt was drawn between them (a PS2 continuation):
# the lines accumulate and the newline refuses the offer.
typeset -g _spark_cmd='' _spark_fail='' _spark_fail_rc=0
typeset -g _spark_explained='' _spark_explained_rc='' _spark_fix='' _spark_offer_fix=''
typeset -g _spark_proof='' _spark_proof_for='' _spark_offer_proof=''
# One list per judgment, the same lists in widget.bash (tests/smoke.py
# compares them). DANGER: head words never offered a re-run. QUIET_ONE:
# exit 1 means "no match" or "differs" for these, not a failure.
# QUIET_RC: 128+INT/QUIT/CONT/TSTP -- Ctrl-C, Ctrl-\, Ctrl-Z and its
# resume are the user's own act (spark itself exits 130 on Ctrl-C too).
_SPARK_DANGER='rm dd mkfs shred chown chmod kill killall pkill shutdown reboot halt poweroff crontab truncate diskutil fdisk parted'
_SPARK_QUIET_ONE='grep egrep fgrep rg ag ack diff cmp test [ pgrep pkill false'
_SPARK_QUIET_RC='130 131 146 148'
# the first success after an explain is the fix -- unless it is only the
# user looking around
_SPARK_LOOKING='ls cd pwd clear cat echo bat eza exit spark explain'

# the head word of one command: the first word past leading VAR=val
# assignments and sudo/env/command/time/nohup, basename'd, mkfs.* folded
# to mkfs. Sets _spark_seg_head.
_spark_head_of() {
    local i=1
    local -a w
    w=( ${=1} )
    while (( i <= ${#w} )); do
        case ${w[i]} in
            [A-Za-z_]*=*|sudo|env|command|time|nohup) (( i++ )) ;;
            *) break ;;
        esac
    done
    _spark_seg_head=${w[i]:-}
    _spark_seg_head=${_spark_seg_head##*/}
    [[ $_spark_seg_head == mkfs.* ]] && _spark_seg_head=mkfs
}

# what a failed command deserves: sets _spark_kind to ask (the offer),
# danger (seen, never re-run) or none. A shell keyword (a continuation
# fragment), a history bang and a line already piping to explain are
# none. EVERY segment of a compound line (&&, ;, |) is classified: one
# dangerous segment makes the whole line danger, so `cp x y && rm -rf x`
# is never re-offered whole through explain.
_spark_kind_of() {
    local cmd=$1 rc=$2 head segs seg
    _spark_kind=none _spark_head=''
    case " $_SPARK_QUIET_RC " in *" $rc "*) return 0 ;; esac
    [[ $cmd == *$'\n'* ]] && return 0
    case $cmd in *"| explain"*|*"|explain"*) return 0 ;; esac
    _spark_head_of "$cmd"
    head=$_spark_seg_head
    _spark_head=$head
    case $head in ''|\!*|spark|explain|done|fi|esac|then|else|do) return 0 ;; esac
    if (( rc == 1 )); then
        case " $_SPARK_QUIET_ONE " in *" $head "*) return 0 ;; esac
    fi
    segs=${cmd//&&/$'\n'}
    segs=${segs//;/$'\n'}
    segs=${segs//|/$'\n'}
    for seg in ${(f)segs}; do
        [[ -n ${seg//[[:space:]]/} ]] || continue
        _spark_head_of "$seg"
        case " $_SPARK_DANGER " in
            *" $_spark_seg_head "*) _spark_kind=danger; _spark_head=$_spark_seg_head; return 0 ;;
        esac
    done
    _spark_kind=ask
    return 0
}

# the test surface: _spark_offer_kind CMD RC prints ask | danger | none
_spark_offer_kind() { _spark_kind_of "$1" "$2"; print -r -- "$_spark_kind"; }

# the failure line: ordinary output above the coming prompt, never the
# hint row -- at precmd time the prompt (and its blank row) is not drawn
# yet, so _spark_say would eat the last row of the command's own output
_spark_note() {
    local t=$1
    (( ${#t} > COLUMNS - 1 )) && t=${t[1,COLUMNS-5]}$_spark_d
    _spark_paint "$t"
    print -r -- "$_spark_out"
}

# a capture still here means no prompt came between: a PS2 continuation
_spark_capture() {
    if [[ -n $_spark_cmd ]]; then _spark_cmd=$_spark_cmd$'\n'$1
    else _spark_cmd=$1; fi
}

# --- the living layer: the news once, a greeting after an absence ----------
# Only on an awake machine whose words part is on (or auto, TERM not
# dumb), with spark not off and SITE_QUIET_START not yes. A prompt costs
# one stat of the news file; the last-seen stamp (the epoch of a prompt in
# any shell) is read and written at most every _SPARK_SEEN_EVERY seconds.
# Absent, or older than _SPARK_ABSENT, the next prompt runs `spark words
# greet` once and prints what it says, control characters stripped. The
# news file is one line, ID<TAB>line: shown once per id, in any shell.
typeset -g _SPARK_LONG=30 _SPARK_ABSENT=14400 _SPARK_SEEN_EVERY=300
typeset -g _spark_seen_at=0 _spark_t0=''
_spark_quiet() {   # SITE_QUIET_START=yes, the environment first, then site.env
    local f=${XDG_CONFIG_HOME:-$HOME/.config}/spark/site.env line q=${SITE_QUIET_START-}
    if [[ -z ${SITE_QUIET_START+x} && -r $f ]]; then
        while IFS= read -r line || [[ -n $line ]]; do
            [[ $line == SITE_QUIET_START=* ]] && q=${line#*=}
        done < "$f"
    fi
    q=${q//[\"\']/}
    [[ $q == yes ]]
}
_spark_living() {
    local now t line id seen out greet='' nf=$SPARK_DIR/news ns=$SPARK_DIR/news-seen ls=$SPARK_DIR/last-seen
    [[ $_spark_lk_awake == yes ]] || return 0
    [[ $_spark_lk_words == on || ( $_spark_lk_words == auto && $TERM != dumb ) ]] || return 0
    [[ -e $SPARK_DIR/off ]] && return 0
    now=${EPOCHSECONDS:-0}
    if (( now - _spark_seen_at >= _SPARK_SEEN_EVERY )); then
        t=''
        [[ -r $ls ]] && IFS= read -r t < "$ls"
        [[ $t == [0-9]* && -z ${t//[0-9]/} ]] && (( now - t <= _SPARK_ABSENT )) || greet=1
        print -r -- "$now" > "$ls" 2>/dev/null
        _spark_seen_at=$now
    fi
    if [[ -n $greet ]] && ! _spark_quiet; then
        out=$("$SPARK_BIN" words greet </dev/null 2>/dev/null) || out=''
        for line in "${(@f)out}"; do
            line=${line//[[:cntrl:]]/}
            [[ -n $line ]] && print -r -- "$line"
        done
    fi
    [[ -r $nf ]] && [[ ! -e $ns || $nf -nt $ns ]] || return 0
    line='' seen=''
    IFS= read -r line < "$nf"
    [[ -r $ns ]] && IFS= read -r seen < "$ns"
    id=${line%%$'\t'*}
    [[ $line == *$'\t'* ]] || id=''
    print -r -- "$id" > "$ns" 2>/dev/null
    # quiet: the news counts as seen, so it never plays later, and the
    # next prompt costs a stat again
    _spark_quiet && return 0
    [[ -n $id && $id != "$seen" ]] || return 0
    line=${line#*$'\t'}
    [[ -n $line && $line != *[[:cntrl:]]* ]] || return 0
    _spark_note "$_spark_h ${_spark_lk_face:+$_spark_lk_face }$line"
}

# $? is read first and handed back last, so a later precmd (a git
# prompt, starship) still sees the command's own status. The look file is
# checked first (one stat while it has not changed); then the failure
# moment; then, on an awake machine, what the living layer has to say.
_spark_failed() {
    local rc=$? took='' d
    _spark_look_check
    if [[ -n $_spark_t0 && $_spark_lk_awake == yes ]]; then
        d=$(( ${EPOCHSECONDS:-${SECONDS%.*}} - _spark_t0 ))
        if (( d > _SPARK_LONG )); then
            if (( d < 90 )); then took=" after $d s"; else took=" after $(( d / 60 )) min"; fi
        fi
    fi
    _spark_t0=''
    _spark_failure $rc "$took"
    _spark_living
    return $rc
}

# the failure moment: RC and, for a long command, " after N s|min"
_spark_failure() {
    local rc=$1 took=$2 cmd=$_spark_cmd
    _spark_cmd='' _spark_hinted=''       # a new prompt: the row above is not spark's
    unset SPARK_EXPLAIN_CMD SPARK_EXPLAIN_RC
    _spark_offer_fix=''
    # no capture: an empty Enter, Ctrl-C at the prompt, or a key spark
    # does not own. Nothing prints twice; a standing offer survives.
    [[ -n $cmd ]] || return 0
    if (( rc == 0 )); then
        if [[ $cmd == *"| explain"* || $cmd == *"|explain"* ]]; then
            _spark_explained=${_spark_fail:-$_spark_explained}   # the offer was taken
            _spark_explained_rc=${_spark_fail_rc:-$_spark_explained_rc}
            _spark_offer_fix=1                                    # a second Esc s now proposes the fix
            _spark_fix=''
        elif [[ $cmd == "spark memory add"* ]]; then
            _spark_explained='' _spark_fix=''                    # the fact was kept
        elif [[ -n $_spark_explained && -z $_spark_fix ]]; then
            case " $_SPARK_LOOKING " in
                *" ${${=cmd}[1]:-} "*) ;;
                *) _spark_fix=$cmd ;;     # the first success after an explain
            esac
        fi
        if [[ -n $_spark_proof && $cmd == "$_spark_proof_for" ]]; then
            # contract 4's proof line: the proposed command just ran --
            # the read-only check is one Esc s away
            _spark_offer_proof=$_spark_proof
            _spark_note "$_spark_h done -- Esc s checks it: $_spark_proof"
            _spark_proof='' _spark_proof_for=''
        fi
        _spark_fail=''
        return 0
    fi
    if [[ $cmd == *"| explain"* || $cmd == *"|explain"* ]]; then
        return 0                          # explain itself failed: the offer stays
    fi
    _spark_kind_of "$cmd" $rc
    [[ $_spark_kind == none ]] && return 0
    if [[ -e $SPARK_DIR/off ]]; then      # only ever stat'd on a failing path
        _spark_fail=''
        return 0
    fi
    if [[ $_spark_kind == danger ]]; then
        _spark_fail=''
        _spark_note "$_spark_h failed ($rc)$took -- $_spark_head: not re-run; ? words asks about it"
    else
        _spark_fail=$cmd _spark_fail_rc=$rc _spark_explained='' _spark_explained_rc='' _spark_fix=''
        # failure memory: the ONE file this hook may read -- the
        # hash->fix index the ledger writes. Builtins only: no fork.
        local _fk='' _fh _fhd _frc _ffx
        if [[ -r $SPARK_DIR/fails ]]; then
            while read -r _fh _fhd _frc _ffx; do
                if [[ $_fhd == "$_spark_head" && $_frc == "$rc" ]]; then _fk=$_ffx; break; fi
            done < "$SPARK_DIR/fails"
        fi
        if [[ -n $_fk ]]; then
            _spark_note "$_spark_h failed ($rc)$took -- last time the fix was: $_fk"
        elif (( rc == 127 )); then
            _spark_note "$_spark_h failed (127)$took -- $_spark_head not found; Esc s offers the install line"
        else
            _spark_note "$_spark_h failed ($rc)$took -- press Esc s to ask why"
        fi
    fi
    return 0
}
add-zsh-hook precmd _spark_failed         # add-zsh-hook refuses a duplicate

# --- Enter: wrap whatever accept-line already is ----------------------------
_spark_orig_accept=${widgets[accept-line]#user:}
[[ $_spark_orig_accept == builtin ]] && _spark_orig_accept=.accept-line
spark-accept-line() {
    if [[ -e $SPARK_DIR/off ]]; then
        _spark_cmd=''                     # off: nothing arms, nothing prints
        zle "$_spark_orig_accept"
        return
    fi
    if ! _spark_is_question "$BUFFER"; then
        [[ -n $_spark_cmd ]] || _spark_t0=${EPOCHSECONDS:-${SECONDS%.*}}   # how long it runs
        _spark_capture "$BUFFER"          # verbatim, before anything expands
        zle "$_spark_orig_accept"
        return
    fi
    _spark_ask "$BUFFER"                  # a question: nothing runs, nothing
}                                         # is captured, no prompt is drawn
zle -N spark-accept-line
bindkey '^M' spark-accept-line
bindkey '^J' spark-accept-line

# --- Ctrl-U: an emptied line takes its hint with it ------------------------
# The hint labels the line; once the user empties the line, it labels
# nothing. Ctrl-U keeps whatever it already was (kill-whole-line unless
# the rc chose another), then clears the row above -- only when the line
# is now empty and spark drew in that row since the prompt came: a row
# spark never wrote is never touched.
_spark_orig_kill=${${(z)"$(bindkey '^U' 2>/dev/null)"}[2]}
[[ -z $_spark_orig_kill || $_spark_orig_kill == (undefined-key|spark-kill-line|\"*) ]] && _spark_orig_kill=kill-whole-line
spark-kill-line() {
    zle "$_spark_orig_kill"
    [[ -z $BUFFER && -n $_spark_hinted ]] || return 0
    _spark_say ''
    _spark_hinted=''
}
zle -N spark-kill-line
bindkey '^U' spark-kill-line

# --- Esc s: ask about this line, no question mark needed --------------------
# On an empty line it serves the failure moment first: a pending failure
# becomes `cmd 2>&1 | explain` in your line (the command and its exit
# code ride along for that one run); a fix that just worked becomes a
# `spark memory add` line. Either way you press Enter.
spark-ask() {
    local fact
    if [[ -n $BUFFER ]]; then _spark_ask "$BUFFER"; return; fi
    if [[ -n $_spark_fail && $_spark_fail_rc == 127 ]]; then
        # command not found: Esc s asks for the install line (known tools
        # answer offline in `spark line`, the rest through the model)
        export SPARK_EXPLAIN_CMD=$_spark_fail SPARK_EXPLAIN_RC=127
        _spark_fail=''
        _spark_ask "install it"
    elif [[ -n $_spark_fail ]]; then
        # braces catch a compound's every branch; a trailing ; would
        # double up inside them, so it is trimmed
        fact=$_spark_fail
        while [[ $fact == *[\;\ ] ]]; do fact=${fact%?}; done
        export SPARK_EXPLAIN_CMD=$fact SPARK_EXPLAIN_RC=$_spark_fail_rc
        BUFFER="{ $fact; } 2>&1 | explain"
        CURSOR=$#BUFFER
        _spark_say "$_spark_h Enter re-runs it: the failure, explained"
    elif [[ -n $_spark_offer_proof ]]; then
        # the proof the line proposed: lands ready to run, read-only
        BUFFER=$_spark_offer_proof
        CURSOR=$#BUFFER
        _spark_offer_proof=''
        _spark_say "$_spark_h Enter runs the proof"
        zle -R
    elif [[ -n $_spark_offer_fix ]]; then
        # the second Esc s, right after the explain: the corrected command
        export SPARK_EXPLAIN_CMD=$_spark_explained SPARK_EXPLAIN_RC=${_spark_explained_rc:-1}
        _spark_offer_fix=''
        _spark_ask "? fix it"
    elif [[ -n $_spark_fix ]]; then
        # the accepted fix also lands in the failure memory (a fork is
        # fine HERE: Esc s is the user's own key, not the prompt hook)
        "$SPARK_BIN" history --fix-worked "$_spark_fix" >/dev/null 2>&1 </dev/null
        fact="$_spark_explained failed until: $_spark_fix"
        BUFFER="spark memory add ${(qq)fact}"
        CURSOR=$#BUFFER
        _spark_say "$_spark_h the fix, as a fact -- edit it, then Enter"
    else
        _spark_say "$_spark_h type something first, then Esc s  (or end the line with ?)"
    fi
    zle -R
}
zle -N spark-ask
bindkey '\es' spark-ask

# --- Esc r: intent search over the shell's own history ---------------------
typeset -g _spark_recall_for=''
typeset -ga _spark_recall_cands
typeset -g _spark_recall_i=0
# land candidate _spark_recall_i in the line; a `!<TAB>` prefix from
# `spark recall` means the line can destroy -- stripped, and the warn
# mark shows instead of the answer mark
_spark_recall_show() {
    local cand=${_spark_recall_cands[$_spark_recall_i]} mark=$_spark_h note=''
    if [[ $cand == $'!\t'* ]]; then
        cand=${cand#$'!\t'}
        mark=$_spark_w note=' -- careful'
    fi
    BUFFER=$cand
    CURSOR=$#BUFFER
    _spark_recall_for=$cand
    _spark_say "$mark $_spark_recall_i/${#_spark_recall_cands[@]}$note -- Esc r: next"
    zle -R
}
spark-recall() {
    [[ -e $SPARK_DIR/off ]] && return
    if [[ -n $BUFFER && $BUFFER == $_spark_recall_for && ${#_spark_recall_cands[@]} -gt 0 ]]; then
        _spark_recall_i=$(( _spark_recall_i % ${#_spark_recall_cands[@]} + 1 ))
        _spark_recall_show
        return
    fi
    local intent=$BUFFER
    if [[ -z $intent ]]; then
        _spark_say "$_spark_h type what the command did, then Esc r"
        zle -R
        return
    fi
    _spark_say "$_spark_h $_spark_d"
    local out
    out=$(fc -ln -400 2>/dev/null | "$SPARK_BIN" recall "$intent" 2>/dev/null)
    if [[ -z $out ]]; then
        _spark_say "$_spark_h nothing in your history matches that"
        zle -R
        return
    fi
    _spark_recall_cands=("${(@f)out}")
    _spark_recall_i=1
    _spark_recall_show
}
zle -N spark-recall
bindkey '\er' spark-recall

# --- Esc k: move spark's row -------------------------------------------------
# 1, 2, 3, then 1 again: the row spark writes in, counted up from the line
# you type on. A two-line prompt (starship's default) needs 2. `spark
# height N` keeps the choice for every shell (quietly; without it the
# choice lasts this shell); a test line shows where the row is now. A row
# spark drew in at the old height is cleared first, and only that one.
spark-height() {
    local n=1
    [[ -e $SPARK_DIR/off ]] && return
    (( _spark_height < 3 )) && n=$(( _spark_height + 1 ))
    [[ -n $_spark_hinted ]] && _spark_say ''
    _spark_height=$n
    [[ -n ${SPARK_HEIGHT:-} ]] && SPARK_HEIGHT=$n
    "$SPARK_BIN" height $n </dev/null >/dev/null 2>&1
    _spark_say "$_spark_h spark writes here. Esc k moves this line."
    zle -R
}
zle -N spark-height
bindkey '\ek' spark-height

# --- paste inspection: a multi-line paste into an EMPTY prompt --------------
# The builtin widget inserts the paste (newlines literal -- nothing
# runs); for two or more lines into an empty prompt, one answer/danger
# line from `spark line --paste` lands in the hint row. spark off (and
# SPARK_OFF at load) disable the inspection; the paste always lands.
spark-bracketed-paste() {
    local before=$BUFFER
    zle .bracketed-paste
    [[ -e $SPARK_DIR/off ]] && return
    if [[ -z $before && $BUFFER == *$'\n'?* ]]; then
        local out kind text
        out=$(print -rn -- "$BUFFER" | SPARK_HINT_ROW=$_spark_height "$SPARK_BIN" line --paste 2>/dev/null)
        kind=${out%%$'\n'*}
        text=${out#*$'\n'}
        text=${text%%$'\n'*}
        case $kind in
            danger) _spark_say "$_spark_w $text -- pasted, not run" ;;
            answer) _spark_say "$_spark_h $text -- pasted, not run" ;;
        esac
        zle -R
    fi
}
zle -N bracketed-paste spark-bracketed-paste
# Esc and s are two keystrokes: give them a full second to be one chord
KEYTIMEOUT=100
