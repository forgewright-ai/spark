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
#   * failed   a nonzero exit says so in the row above the next prompt;
#              the next thing spark says there replaces it. No model
#              call, no fork, nothing written: the command you typed on
#              one line and its exit code live in this pane's variables
#              and die with it.
#   Esc k      moves spark's row: 1, 2 or 3 rows above the line you type
#              on (`spark height N` keeps it). A two-line prompt needs 2.
#   Esc v      listens (spark voice on or clear): a pause ends it, and the
#              words land in your line -- as a `? ` question on an empty
#              one. Nothing runs until you press Enter.
#   Esc x      stops spark speaking. Both are bound only where the voice
#              is on or clear when the shell starts; off, the keys stay
#              the shell's own.
#   spark off / spark on        silence / restore (a flag file, checked at
#              every Enter and on the failing path, so one `spark off`
#              reaches every pane at once)
#   SPARK_OFF=1                 in the environment: bind nothing at all
#
# The look file ($STATE_DIR/look, written by `spark awaken`, `spark look`
# and `spark height`) is read line by line when it changes -- never
# sourced. Until the machine is awake it only moves the row; awake, it
# adds the built-in colours and how long a failed command ran.
#
# The face (awake, the look's motion and words active, no `spark off`):
# every line spark says in its row carries the mood's face after the
# mark -- `* (^.^) Forty-two`, `! (O.O) <- deletes 3 files`. At an idle
# prompt the resting face sits alone in that row and is erased at Enter,
# so scrollback keeps no face. It is drawn only where the blank row is
# known: the prompt opens with a newline and has as many lines as the
# row's height, or starship draws it. At an empty line it blinks, sleeps
# after five minutes without a key and wakes on the next one -- a `sched`
# timer, builtins only, nothing in the background. The face says nothing.
# With the face off every byte is what it was.

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
# A FACE_<MOOD> value is kept only as printable ASCII, 8 characters at
# most. BLINK (frames of 0.12 s between two blinks, 0 = never) becomes
# _spark_period, whole seconds: 14 -> 5, 28 -> 10, 50 -> 18, never under 4.
typeset -g _spark_height=1 _spark_lk_had='' _spark_lk_awake='' _spark_lk_colour=''
typeset -g _spark_lk_acc='' _spark_lk_warn='' _spark_lk_motion='' _spark_lk_words=''
typeset -g _spark_fc_idle='' _spark_fc_thinking='' _spark_fc_pleased='' _spark_fc_puzzled=''
typeset -g _spark_fc_alarmed='' _spark_fc_listening='' _spark_fc_asleep='' _spark_fc_waking=''
typeset -g _spark_fc_blink='' _spark_fc_glance=''
typeset -gi _spark_period=0
_spark_look_read() {
    local f=$SPARK_DIR/look line k v n=0
    _spark_height=1 _spark_lk_had='' _spark_lk_awake='' _spark_lk_colour=''
    _spark_lk_acc='' _spark_lk_warn='' _spark_lk_motion='' _spark_lk_words=''
    _spark_fc_idle='' _spark_fc_thinking='' _spark_fc_pleased='' _spark_fc_puzzled=''
    _spark_fc_alarmed='' _spark_fc_listening='' _spark_fc_asleep='' _spark_fc_waking=''
    _spark_fc_blink='' _spark_fc_glance='' _spark_period=0
    if [[ -r $f ]]; then
        _spark_lk_had=1
        while (( n++ < 64 )) && { IFS= read -r line || [[ -n $line ]]; }; do
            [[ $line == [A-Z]*=* ]] || continue
            k=${line%%=*} v=${line#*=}
            [[ $v == *[[:cntrl:]]* ]] && continue
            case $k in
                AWAKE) _spark_lk_awake=$v ;;
                MOTION) _spark_lk_motion=$v ;;
                COLOUR) _spark_lk_colour=$v ;;
                WORDS) _spark_lk_words=$v ;;
                HEIGHT) [[ $v == [1-5] ]] && _spark_height=$v ;;
                SGR_ACCENT) _spark_lk_acc=$v ;;
                SGR_WARN) _spark_lk_warn=$v ;;
                BLINK)
                    if [[ ( $v == [1-9]* || $v == 0 ) && -z ${v//[0-9]/} && ${#v} -le 3 ]]; then
                        _spark_period=$(( (v * 36 + 50) / 100 ))
                        (( v > 0 && _spark_period < 4 )) && _spark_period=4
                    fi ;;
                FACE_?*)
                    [[ -n $v && ${#v} -le 8 && $v != *[![:ascii:]]* ]] || continue
                    case $k in
                        FACE_IDLE) _spark_fc_idle=$v ;;
                        FACE_THINKING) _spark_fc_thinking=$v ;;
                        FACE_PLEASED) _spark_fc_pleased=$v ;;
                        FACE_PUZZLED) _spark_fc_puzzled=$v ;;
                        FACE_ALARMED) _spark_fc_alarmed=$v ;;
                        FACE_LISTENING) _spark_fc_listening=$v ;;
                        FACE_ASLEEP) _spark_fc_asleep=$v ;;
                        FACE_WAKING) _spark_fc_waking=$v ;;
                        FACE_BLINK) _spark_fc_blink=$v ;;
                        FACE_GLANCE) _spark_fc_glance=$v ;;
                    esac ;;
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
# _spark_paint TEXT [N]: N is how many leading characters the accent
# takes -- the mark and its face, or a face alone; without it, the mark.
_spark_paint() {
    local t=$1 n=${2:-} a=${SPARK_ACCENT_SGR:-} w=${SPARK_WARN_SGR:-}
    _spark_out=$t
    if [[ $_spark_lk_awake == yes ]] && [[ $_spark_lk_colour == on || ( $_spark_lk_colour == auto \
            && $TERM != dumb && -z ${NO_COLOR:-} ) ]]; then
        [[ -n $a ]] || a=$_spark_lk_acc
        [[ -n $w ]] || w=$_spark_lk_warn
    fi
    case $t in
        "$_spark_w "*) [[ -n $w && -z ${w//[0-9;]/} ]] \
            && _spark_out=$'\e['"$w"'m'"$t"$'\e[0m' ;;
        *)  [[ -z $n && $t == "$_spark_h "* ]] && n=1
            (( ${n:-0} > 0 )) && [[ -n $a && -z ${a//[0-9;]/} ]] \
                && _spark_out=$'\e['"$a"'m'"${t[1,n]}"$'\e[0m'"${t[n+1,-1]}" ;;
    esac
}

# --- the face: beside the mark, and alone at an idle prompt ------------------
# On when the machine is awake, the look's words and motion are each on
# (or auto at a terminal that is not dumb) and `spark off` is not set.
# Off, nothing here writes a byte.
typeset -g _spark_mood='' _spark_ft='' _spark_fn='' _spark_faced=''
typeset -gi _spark_gen=0
_spark_face_on() {
    [[ $_spark_lk_awake == yes ]] || return 1
    [[ $_spark_lk_words == on || ( $_spark_lk_words == auto && $TERM != dumb ) ]] || return 1
    [[ $_spark_lk_motion == on || ( $_spark_lk_motion == auto && $TERM != dumb ) ]] || return 1
    [[ ! -e $SPARK_DIR/off ]]
}
# _spark_face TEXT: sets _spark_ft, TEXT with the face of _spark_mood
# (idle unless the caller set one) after its mark, and _spark_fn, the
# characters the accent then takes. The mood is spent: the next line is
# idle again. A mood the look file lacks shows the idle face.
_spark_face() {
    local f=''
    _spark_ft=$1 _spark_fn=''
    if [[ $1 == ("$_spark_h"|"$_spark_w")" "* ]] && _spark_face_on; then
        case $_spark_mood in
            thinking) f=$_spark_fc_thinking ;;
            pleased) f=$_spark_fc_pleased ;;
            puzzled) f=$_spark_fc_puzzled ;;
            alarmed) f=$_spark_fc_alarmed ;;
            listening) f=$_spark_fc_listening ;;
        esac
        [[ -n $f ]] || f=$_spark_fc_idle
        if [[ -n $f ]]; then
            _spark_ft="${1[1]} $f ${1[3,-1]}"
            _spark_fn=$(( ${#f} + 2 ))
        fi
    fi
    _spark_mood=''
}
# the resting face, alone in spark's row: the same frame _spark_say draws
_spark_idle_draw() {
    _spark_paint "$1" ${#1}
    print -n -- $'\e7\e['"$_spark_height"$'A\r\e[2K'"$_spark_out"$'\e8'
    _spark_faced=1
}
# and gone again: only a row the resting face stands in is cleared
_spark_unface() {
    [[ -n $_spark_faced ]] || return 0
    _spark_faced=''
    print -n -- $'\e7\e['"$_spark_height"$'A\r\e[2K\e8'
}

# --- the hint row: the blank line above the prompt --------------------------
# _spark_height rows up from the cursor (1 unless the look file or
# SPARK_HEIGHT says more: a two-line prompt takes 2), so the edit line must
# be a single row when this runs (a wrapped question would make "the row
# above" the prompt itself), and the text must fit the width (a wrapped
# hint would push the prompt down). The face counts toward that width.
# What it writes replaces the resting face: _spark_faced is spent.
typeset -g _spark_hinted=''   # spark drew in the row above since this prompt came
_spark_say() {
    local t=$1
    [[ -n $t ]] && _spark_hinted=1
    _spark_face "$t"
    t=$_spark_ft
    (( ${#t} > COLUMNS - 2 )) && t=${t[1,COLUMNS-3]}$_spark_d
    _spark_paint "$t" $_spark_fn
    _spark_faced=''
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
    local line=$1 fd kind cmd hint line3 mark=$_spark_h tail='' mood=''
    # the cursor to the line's start: back on the prompt's row, so the
    # hint lands in the blank row above it however far a question wraps
    CURSOR=0; zle -R
    _spark_mood=thinking
    _spark_say "$_spark_h $_spark_d"
    _spark_proof='' _spark_proof_for=''
    # SPARK_HINT_ROW=N: spark line may pulse in that row, N up (text.Busy),
    # while the model answers -- then in the reply's own mark until the hint
    exec {fd}< <(print -r -- "$line" | SPARK_HINT_ROW=$_spark_height "$SPARK_BIN" line --cwd "$PWD" --shell zsh 2>/dev/null)
    IFS= read -r -u $fd kind
    case $kind in
        cmd$'\t'*|danger$'\t'*)
            cmd=${kind#*$'\t'}
            [[ $kind == danger$'\t'* ]] && mark=$_spark_w tail=' -- read it before Enter' mood=alarmed
            _spark_mood=${mood:-thinking}
            _spark_say "$mark $_spark_d$tail"
            BUFFER=$cmd; CURSOR=0; zle -R
            IFS= read -r -u $fd hint
            [[ -n $hint ]] || mood=${mood:-puzzled}
            _spark_mood=$mood
            _spark_say "$mark ${hint:-no hint came}$tail"
            IFS= read -r -u $fd line3
            case $line3 in proof$'\t'*) _spark_proof=${line3#proof$'\t'} _spark_proof_for=$cmd ;; esac
            CURSOR=$#BUFFER ;;
        answer)
            BUFFER=''; CURSOR=0; zle -R           # an answer leaves the line empty
            IFS= read -r -u $fd hint
            _spark_mood=pleased
            [[ -n $hint ]] || _spark_mood=puzzled
            _spark_say "$_spark_h ${hint:-no answer came}" ;;
        *)
            IFS= read -r -u $fd hint
            [[ -n $kind && $kind != error ]] && hint=$kind    # not contract 4: say what came
            _spark_mood=alarmed
            _spark_say "$_spark_h ${hint:-no model answers}"
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

# the failure line goes in the hint row, like every line spark says at
# the prompt, so the next one there replaces it. At precmd time the
# prompt (and its blank row) is not drawn yet: the line waits here, and
# the line editor's start draws it (zle-line-init, after the prompt),
# with its mood (_spark_note TEXT [MOOD]). With no line waiting, the
# resting face is drawn there instead (_spark_idle) -- at a fresh prompt
# only, never at a continuation line, whose row above is the command.
typeset -g _spark_pending='' _spark_pending_mood='' _spark_fresh=''
_spark_note() { _spark_pending=$1 _spark_pending_mood=${2:-}; }
_spark_line_init() {
    local fresh=$_spark_fresh
    _spark_fresh=''
    (( ++_spark_gen ))                    # a tick from an earlier line is stale
    if [[ -n $_spark_pending ]]; then
        _spark_mood=$_spark_pending_mood
        _spark_say "$_spark_pending"
        _spark_pending='' _spark_pending_mood=''
    fi
    [[ -n $fresh && $CONTEXT == start ]] || return 0
    _spark_idle
}
zle -N _spark_line_init
autoload -Uz add-zle-hook-widget && add-zle-hook-widget line-init _spark_line_init

# --- the resting face at an idle prompt --------------------------------------
# Drawn only where the blank row is known to be there: the prompt opens
# with a newline and has as many lines as the row is high, or starship
# draws the blank row (its add_newline). Anywhere else the row above
# holds the last command's output, and nothing is drawn. A note already
# in the row keeps it: it carries its own face.
#
# Motion (zsh only): _spark_tick is a `sched` event, so zle runs it
# while it waits for a key -- builtins alone, no process, nothing in the
# background. A tick draws only at a fresh prompt whose line is empty
# and whose row holds no note, with the face still on and the terminal
# the size it was. A blink is the blink face for one 0.12 s beat
# (zselect, cut short by a key it does not read), every _spark_period
# seconds; each third is a glance. After _spark_sleep_after seconds
# with no key the face sleeps, two frames in turn every 2 s; the next
# key (zle-line-pre-redraw) draws the waking face, and the tick after it
# the resting one. Text in the line: the face stands still. A resize or
# Ctrl-L: the tick stops until the next prompt. A generation counter
# makes a tick from an earlier prompt a no-op. Without zsh/sched or
# zsh/zselect the face is still. SPARK_IDLE_SLEEP is the tests' seam for
# the 300 seconds, nothing a person sets.
typeset -gi _spark_keyed=0 _spark_blinks=0 _spark_sleep_after=300
typeset -g _spark_can_tick='' _spark_asleep='' _spark_waking='' _spark_zz='' _spark_cols='' _spark_rows=''
[[ ${SPARK_IDLE_SLEEP:-} == [1-9]* && -z ${SPARK_IDLE_SLEEP//[0-9]/} && ${#SPARK_IDLE_SLEEP} -le 5 ]] \
    && _spark_sleep_after=$SPARK_IDLE_SLEEP
zmodload zsh/sched 2>/dev/null && zmodload zsh/zselect 2>/dev/null && _spark_can_tick=1
_spark_idle() {
    local nl
    [[ -n $_spark_fc_idle ]] && (( ${COLUMNS:-80} > 12 )) && _spark_face_on || return 0
    if [[ -z ${STARSHIP_SHELL:-} ]]; then
        [[ $PROMPT == $'\n'* ]] || return 0
        nl=${PROMPT//[^$'\n']/}
        (( ${#nl} == _spark_height )) || return 0
    fi
    [[ -n $_spark_hinted ]] || _spark_idle_draw "$_spark_fc_idle"
    [[ -n $_spark_can_tick ]] || return 0
    _spark_cols=$COLUMNS _spark_rows=$LINES _spark_keyed=${EPOCHSECONDS:-${SECONDS%.*}}
    _spark_asleep='' _spark_waking='' _spark_zz=''
    _spark_arm
}
# one tick from now, and only one: an earlier one of spark's is dropped
_spark_arm() {
    local -i i n=${1:-0} left
    if (( n == 0 )); then
        n=$_spark_period
        left=$(( _spark_sleep_after - ( ${EPOCHSECONDS:-${SECONDS%.*}} - _spark_keyed ) ))
        (( n == 0 || left < n )) && n=$left
        (( n < 1 )) && n=1
    fi
    for (( i = ${#zsh_scheduled_events}; i > 0; i-- )); do
        [[ ${zsh_scheduled_events[i]} == *:_spark_tick\ * ]] && sched -$i
    done
    sched +$n _spark_tick $_spark_gen
}
_spark_tick() {
    (( ${1:-0} == _spark_gen )) || return 0
    zle && zle spark-tick                 # a widget: it reads the line
    return 0
}
spark-tick() {
    local f
    local -a ready
    [[ $COLUMNS == $_spark_cols && $LINES == $_spark_rows && $CONTEXT == start ]] || return 0
    if ! _spark_face_on; then             # spark off, from any pane: the face goes
        (( BUFFERLINES == 1 )) && _spark_unface
        return 0
    fi
    if [[ -n $_spark_waking ]]; then
        _spark_waking=''
        [[ -n $_spark_faced && -z $_spark_hinted ]] && (( BUFFERLINES == 1 )) \
            && _spark_idle_draw "$_spark_fc_idle"
    elif [[ -n $BUFFER || -n $_spark_hinted ]]; then
        :                                 # text in the line, or a note in the row: still
    elif (( ${EPOCHSECONDS:-${SECONDS%.*}} - _spark_keyed >= _spark_sleep_after )); then
        _spark_asleep=1
        if [[ -z $_spark_zz ]]; then _spark_zz=1 f=$_spark_fc_asleep
        else _spark_zz='' f=$_spark_fc_blink; fi
        [[ -n $f ]] && _spark_idle_draw "$f"
        _spark_arm 2
        return 0
    elif (( _spark_period > 0 )); then
        (( ++_spark_blinks ))
        f=$_spark_fc_blink
        (( _spark_blinks % 3 == 0 )) && f=${_spark_fc_glance:-$f}
        if [[ -n $f ]]; then
            _spark_idle_draw "$f"
            zselect -a ready -t 12 -r 0   # one beat; a key ends it, and is not read
            _spark_idle_draw "$_spark_fc_idle"
        fi
    fi
    _spark_arm
}
zle -N spark-tick
# a key came: the one variable this tests is _spark_asleep
_spark_keyed_hook() {
    _spark_keyed=${EPOCHSECONDS:-${SECONDS%.*}}
    [[ -n $_spark_asleep ]] || return 0
    _spark_asleep='' _spark_zz=''
    [[ -n $_spark_faced && -z $_spark_hinted && -n $_spark_fc_waking ]] || return 0
    _spark_idle_draw "$_spark_fc_waking"
    _spark_waking=1
    _spark_arm 1
}
zle -N _spark_keyed_hook
[[ -n $_spark_can_tick ]] && add-zle-hook-widget line-pre-redraw _spark_keyed_hook
# Ctrl-L keeps whatever it was, and the tick stops: the screen is new
_spark_orig_clear=${${(z)"$(bindkey '^L' 2>/dev/null)"}[2]}
[[ -z $_spark_orig_clear || $_spark_orig_clear == (undefined-key|spark-clear-screen|\"*) ]] && _spark_orig_clear=clear-screen
spark-clear-screen() {
    (( ++_spark_gen ))
    _spark_faced='' _spark_asleep='' _spark_waking=''
    zle "$_spark_orig_clear"
}
zle -N spark-clear-screen
bindkey '^L' spark-clear-screen

# a capture still here means no prompt came between: a PS2 continuation
_spark_capture() {
    if [[ -n $_spark_cmd ]]; then _spark_cmd=$_spark_cmd$'\n'$1
    else _spark_cmd=$1; fi
}

# how long a command ran, for a failure on an awake machine
typeset -g _SPARK_LONG=30 _spark_t0=''

# $? is read first and handed back last, so a later precmd (a git
# prompt, starship) still sees the command's own status. The look file is
# checked first (one stat while it has not changed); then the failure
# moment.
_spark_failed() {
    local rc=$? took='' d
    _spark_fresh=1                        # a prompt is coming: the resting face may go above it
    _spark_look_check
    if [[ -n $_spark_t0 && $_spark_lk_awake == yes ]]; then
        d=$(( ${EPOCHSECONDS:-${SECONDS%.*}} - _spark_t0 ))
        if (( d > _SPARK_LONG )); then
            if (( d < 90 )); then took=" after $d s"; else took=" after $(( d / 60 )) min"; fi
        fi
    fi
    _spark_t0=''
    _spark_failure $rc "$took"
    return $rc
}

# the failure moment: RC and, for a long command, " after N s|min"
_spark_failure() {
    local rc=$1 took=$2 cmd=$_spark_cmd
    _spark_cmd='' _spark_hinted='' _spark_pending=''   # a new prompt: the row above is not spark's
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
            _spark_note "$_spark_h done -- Esc s checks it: $_spark_proof" pleased
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
    # stat'd on a failing path -- and, where the face is on, once a prompt
    # (_spark_face_on)
    if [[ -e $SPARK_DIR/off ]]; then
        _spark_fail=''
        return 0
    fi
    if [[ $_spark_kind == danger ]]; then
        _spark_fail=''
        _spark_note "$_spark_h failed ($rc)$took -- $_spark_head is not re-run; ? words asks about it" alarmed
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
            _spark_note "$_spark_h failed ($rc)$took -- last time this fixed it: $_fk" alarmed
        elif (( rc == 127 )); then
            _spark_note "$_spark_h failed (127)$took -- $_spark_head not found; Esc s gets the install line" alarmed
        else
            _spark_note "$_spark_h failed ($rc)$took -- Esc s asks why" alarmed
        fi
    fi
    return 0
}
add-zsh-hook precmd _spark_failed         # add-zsh-hook refuses a duplicate

# --- Enter: wrap whatever accept-line already is ----------------------------
_spark_orig_accept=${widgets[accept-line]#user:}
[[ $_spark_orig_accept == builtin ]] && _spark_orig_accept=.accept-line
spark-accept-line() {
    (( ++_spark_gen ))                    # no tick while the command runs
    if [[ -n $_spark_faced ]]; then
        # the resting face goes before the line does: scrollback keeps
        # none. From the prompt's own row, however far the line wraps.
        local c=$CURSOR
        (( BUFFERLINES > 1 )) && { CURSOR=0; zle -R; }
        _spark_unface
        CURSOR=$c
    fi
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
        _spark_say "$_spark_h Enter explains the error"
    elif [[ -n $_spark_offer_proof ]]; then
        # the proof the line proposed: lands ready to run, read-only
        BUFFER=$_spark_offer_proof
        CURSOR=$#BUFFER
        _spark_offer_proof=''
        _spark_say "$_spark_h Enter runs the check"
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
        _spark_say "$_spark_h Enter remembers the fix"
    else
        _spark_mood=puzzled
        _spark_say "$_spark_h type a question, then Esc s"
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
        mark=$_spark_w note=' -- careful' _spark_mood=alarmed
    fi
    BUFFER=$cand
    CURSOR=$#BUFFER
    _spark_recall_for=$cand
    _spark_say "$mark $_spark_recall_i/${#_spark_recall_cands[@]}$note -- Esc r for the next"
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
        _spark_mood=puzzled
        _spark_say "$_spark_h type what the command did, then Esc r"
        zle -R
        return
    fi
    _spark_mood=thinking
    _spark_say "$_spark_h $_spark_d"
    local out
    # SPARK_HINT_ROW=N: spark recall may pulse in that row while it asks
    out=$(fc -ln -400 2>/dev/null | SPARK_HINT_ROW=$_spark_height "$SPARK_BIN" recall "$intent" 2>/dev/null)
    if [[ -z $out ]]; then
        _spark_mood=puzzled
        _spark_say "$_spark_h nothing in your history matches"
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
    _spark_unface                         # the resting face leaves the old row too
    _spark_height=$n
    [[ -n ${SPARK_HEIGHT:-} ]] && SPARK_HEIGHT=$n
    "$SPARK_BIN" height $n </dev/null >/dev/null 2>&1
    _spark_say "$_spark_h spark writes here -- Esc k moves it"
    zle -R
}
zle -N spark-height
bindkey '\ek' spark-height

# --- Esc v: listen; Esc x: stop speaking -------------------------------------
# Esc v hands the hearing to `spark voice listen --buffer` (the words on
# stdout and nothing else; a pause ends them) and lands the words at the
# cursor -- on an empty line as a `? ` question, so Enter asks spark and
# never runs what was heard. While it listens the row says so. Esc x is
# `spark voice stop`.
spark-listen() {
    local words rc
    [[ -e $SPARK_DIR/off ]] && return
    _spark_mood=listening
    _spark_say "$_spark_h listening -- a pause ends it"
    zle -R
    words=$("$SPARK_BIN" voice listen --buffer </dev/null 2>/dev/null)
    rc=$?
    words=${words//[[:cntrl:]]/ }
    if (( rc == 0 )) && [[ -n ${words//[[:space:]]/} ]]; then
        if [[ -z $BUFFER ]]; then
            BUFFER="? $words"; CURSOR=$#BUFFER
            _spark_say "$_spark_h heard -- Enter asks it"
        else
            [[ -n $LBUFFER && $LBUFFER != *[[:space:]] ]] && words=" $words"
            LBUFFER+=$words
            _spark_say "$_spark_h heard -- in your line"
        fi
    elif (( rc == 1 || rc == 130 )); then
        _spark_mood=puzzled
        _spark_say "$_spark_h nothing heard"
    else
        _spark_say "$_spark_h Esc v needs the voice -- spark voice on"
    fi
    zle -R
}
zle -N spark-listen
spark-hush() { "$SPARK_BIN" voice stop </dev/null >/dev/null 2>&1; }
zle -N spark-hush
# bound only where the voice is on or clear as the shell starts --
# SPARK_VOICE from the environment, else spark.env's line, read line by
# line and never sourced; off, Esc x stays zsh's execute-named-cmd
typeset -g _spark_voice=${SPARK_VOICE-}
if [[ -z $_spark_voice && -r ${XDG_CONFIG_HOME:-$HOME/.config}/spark/spark.env ]]; then
    () {
        local line n=0
        while (( n++ < 256 )) && { IFS= read -r line || [[ -n $line ]]; }; do
            [[ $line == SPARK_VOICE=* ]] && _spark_voice=${line#SPARK_VOICE=}
        done < "${XDG_CONFIG_HOME:-$HOME/.config}/spark/spark.env"
    }
fi
_spark_voice=${${_spark_voice#\"}%\"}
if [[ ${(L)_spark_voice} == (on|clear) ]]; then
    bindkey '\ev' spark-listen
    bindkey '\ex' spark-hush
fi

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
            danger) _spark_mood=alarmed; _spark_say "$_spark_w $text -- pasted, not run" ;;
            answer) _spark_say "$_spark_h $text -- pasted, not run" ;;
        esac
        zle -R
    fi
}
zle -N bracketed-paste spark-bracketed-paste
# Esc and s are two keystrokes: give them a full second to be one chord
KEYTIMEOUT=100
