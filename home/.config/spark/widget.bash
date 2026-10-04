# spark widget.bash -- the AI at the prompt, for bash 4+. Sourced by .bashrc
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
#   spark keys                  lists the keys; `spark keys NAME KEY` moves
#              one (ask, recall, height, listen, stop), `none` leaves it to
#              the shell. ~/.config/spark/keys.env holds the choice, read
#              here as the shell starts; the hints name the key you chose.
#              Enter, Ctrl-U and paste stay as they are.
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
# row's height, or starship draws it. In bash the face is still:
# readline has no idle timer, and nothing runs in the background for
# it (zsh blinks). The face says nothing. With the face off every byte
# is what it was.
#
# How Enter works: it is a two-key macro. The first key runs _spark_enter,
# which looks at the line and rebinds the second key -- to accept-line for a
# plain command, or to a redraw for a question -- before readline reads it.
# The second key then does whatever the first decided. This is the only way
# a bind -x handler can both edit the line and stop it from running.

[[ $- == *i* ]] || return 0
[[ -n ${_SPARK_WIDGET_LOADED:-} ]] && return 0
_SPARK_WIDGET_LOADED=1
[[ -n ${SPARK_OFF:-} ]] && return 0
(( BASH_VERSINFO[0] >= 4 )) || return 0

: "${SPARK_BIN:=spark}"
# one mark, both OSes: the answer and warn marks are ASCII everywhere
_spark_h='*' _spark_w='!'
# the console font cannot draw …; ASCII there (TERM=linux) or on request
if [[ $TERM == linux || -n ${SPARK_ASCII:-} ]] || { [[ -n ${TMUX:-} ]] && [[ $(tmux display -p '#{client_termname}' 2>/dev/null) == linux ]]; }; then _spark_d='...'
else _spark_d='…'; fi
SPARK_DIR=${XDG_STATE_HOME:-$HOME/.local/state}/spark

# --- liveness marker: `spark check` and `spark status` see this shell -------
# contract 6: <shell> <pid> <epoch> [hook] -- the fourth field says this
# shell's exit-code hook is armed; readers ignore fields they do not know
_spark_born=${EPOCHSECONDS:-$(date +%s)}
mkdir -p "$SPARK_DIR/widgets" 2>/dev/null && chmod 700 "$SPARK_DIR" 2>/dev/null
printf 'bash %d %d hook\n' "$$" "$_spark_born" > "$SPARK_DIR/widgets/$$" 2>/dev/null
# a reader still drawing an answer's hint stops with the shell, before its
# proof file goes: it must not write after the shell is gone
_spark_gone() { _spark_reap; rm -f "$SPARK_DIR/widgets/$$" "$SPARK_DIR/proof.$$"; }
# an EXIT trap the rc set before this one still runs, after spark's, and
# sees the exit status as it was: `trap -p` quotes it as trap -- '...'
# EXIT, with each ' written '\''
_spark_exit=$(trap -p EXIT)
_spark_exit=${_spark_exit#trap -- \'}
_spark_exit=${_spark_exit%\' EXIT}
_spark_exit=${_spark_exit//\'\\\'\'/\'}
trap -- "_spark_rc=\$?; _spark_gone${_spark_exit:+; (exit \$_spark_rc); $_spark_exit}" EXIT
unset _spark_exit

# --- the keys: today's defaults, moved by ~/.config/spark/keys.env -----------
# `spark keys` writes that file: KEYS_<NAME>=Esc a | Ctrl-g | none (Alt-a
# reads as Esc a). Read line by line, never sourced; a value of any other
# shape keeps the default (the letters are spelled out: a range such as
# a-z follows the locale's collation in bash 4). _spark_key NAME FUNCTION binds it: nothing for
# none, else the sequence -- and notes what the key did before, a line of
# _spark_rec. _spark_binds is readline's own list, asked once for every
# key spark takes (one fork, builtins only).
_spark_k_ask='Esc s' _spark_k_recall='Esc r' _spark_k_height='Esc k'
_spark_k_listen='Esc v' _spark_k_stop='Esc x' _spark_rec='' _spark_esc='' _spark_sq=''
_spark_kf=${XDG_CONFIG_HOME:-$HOME/.config}/spark/keys.env
if [[ -r $_spark_kf ]]; then
    _spark_kn=0
    while (( _spark_kn++ < 32 )) && { IFS= read -r _spark_kl || [[ -n $_spark_kl ]]; }; do
        [[ $_spark_kl == KEYS_[A-Z]*=* ]] || continue
        _spark_kv=${_spark_kl#*=}; _spark_kv=${_spark_kv#\"}; _spark_kv=${_spark_kv%\"}
        [[ $_spark_kv == Alt-? ]] && _spark_kv="Esc ${_spark_kv#Alt-}"
        [[ $_spark_kv == none || $_spark_kv == 'Esc '[abcdefghijklmnopqrstuvwxyz0123456789] || $_spark_kv == Ctrl-[abefgknoprtvwy] ]] || continue
        case ${_spark_kl%%=*} in
            KEYS_ASK) _spark_k_ask=$_spark_kv ;;
            KEYS_RECALL) _spark_k_recall=$_spark_kv ;;
            KEYS_HEIGHT) _spark_k_height=$_spark_kv ;;
            KEYS_LISTEN) _spark_k_listen=$_spark_kv ;;
            KEYS_STOP) _spark_k_stop=$_spark_kv ;;
        esac
    done < "$_spark_kf"
fi
unset _spark_kf _spark_kn _spark_kl _spark_kv
# the sequence bind takes for a key's name: sets _spark_sq ('' for none)
_spark_seq() {
    case $1 in
        'Esc '?) _spark_sq="\\e${1#Esc }" ;;
        Ctrl-?) _spark_sq="\\C-${1#Ctrl-}" ;;
        *) _spark_sq='' ;;
    esac
}
_spark_binds=$(bind -p 2>/dev/null; bind -s 2>/dev/null; bind -X 2>/dev/null)
_spark_key() {
    local v=_spark_k_$1 key was=- line
    key=${!v}
    _spark_seq "$key"
    [[ -n $_spark_sq ]] || return 0
    while IFS= read -r line; do
        if [[ $line == "\"$_spark_sq\": "* ]]; then was=${line#*\": }; break; fi
    done <<< "$_spark_binds"
    [[ -z $was || $was == self-insert || $was == *_spark_* || $was == *[[:cntrl:]]* ]] && was=-
    _spark_rec+="$1"$'\t'"$key"$'\t'"${was:0:40}"$'\n'
    [[ $key == Esc* ]] && _spark_esc=1
    bind -x "\"$_spark_sq\": $2"
}

# --- the look: read line by line, never sourced -----------------------------
# KEY=value lines; a value holding a control character (an escape) is
# dropped. The marker above doubles as the stamp: the file is read again
# only when it is newer than the marker, then the marker is written anew.
# SPARK_HEIGHT in the environment wins over the file's HEIGHT.
# A FACE_<MOOD> value is kept only as printable ASCII, 8 characters at
# most. BLINK and the faces of motion (blink, glance, asleep, waking)
# are zsh's: this face is still.
_spark_height=1 _spark_lk_had='' _spark_lk_awake='' _spark_lk_colour=''
_spark_lk_acc='' _spark_lk_warn='' _spark_lk_motion='' _spark_lk_words=''
_spark_fc_idle='' _spark_fc_thinking='' _spark_fc_pleased='' _spark_fc_puzzled=''
_spark_fc_alarmed='' _spark_fc_listening=''
_spark_look_read() {
    local f=$SPARK_DIR/look line k v n=0
    _spark_height=1 _spark_lk_had='' _spark_lk_awake='' _spark_lk_colour=''
    _spark_lk_acc='' _spark_lk_warn='' _spark_lk_motion='' _spark_lk_words=''
    _spark_fc_idle='' _spark_fc_thinking='' _spark_fc_pleased='' _spark_fc_puzzled=''
    _spark_fc_alarmed='' _spark_fc_listening=''
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
                FACE_?*)
                    [[ -n $v && ${#v} -le 8 && $v != *[![:ascii:]]* ]] || continue
                    case $k in
                        FACE_IDLE) _spark_fc_idle=$v ;;
                        FACE_THINKING) _spark_fc_thinking=$v ;;
                        FACE_PLEASED) _spark_fc_pleased=$v ;;
                        FACE_PUZZLED) _spark_fc_puzzled=$v ;;
                        FACE_ALARMED) _spark_fc_alarmed=$v ;;
                        FACE_LISTENING) _spark_fc_listening=$v ;;
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
    printf 'bash %d %d hook\n' "$$" "$_spark_born" > "$m" 2>/dev/null
}
_spark_look_read

# --- is this line a question? ----------------------------------------------
# `? ...` always is. `...?` is, unless the last word is a glob that matches
# something (`ls a.tx?`): the shell gets those.
_spark_is_question() {
    local line=$1 w
    [[ $line == \?* ]] && return 0
    [[ $line == *\? ]] || return 1
    w=${line##*[[:space:]]}
    w=${w%\?}
    [[ -n $w ]] && compgen -G "$(printf '%q' "$w")?" >/dev/null 2>&1 && return 1
    return 0
}

# --- the hint row: the blank line above the prompt -------------------------
# readline runs a bind -x command with the cursor at the start of the
# prompt's first row -- wrapped line or not, wherever the point is -- so one
# row up is that blank row. The text must fit the width, or its wrap would
# push the prompt down.
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
                && _spark_out=$'\e['"$a"'m'"${t:0:n}"$'\e[0m'"${t:n}" ;;
    esac
}

# --- the face: beside the mark, and alone at an idle prompt ------------------
# On when the machine is awake, the look's words and motion are each on
# (or auto at a terminal that is not dumb) and `spark off` is not set.
# Off, nothing here writes a byte.
_spark_mood='' _spark_ft='' _spark_fn='' _spark_faced=''
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
    if [[ $1 == "$_spark_h "* || $1 == "$_spark_w "* ]] && _spark_face_on; then
        case $_spark_mood in
            thinking) f=$_spark_fc_thinking ;;
            pleased) f=$_spark_fc_pleased ;;
            puzzled) f=$_spark_fc_puzzled ;;
            alarmed) f=$_spark_fc_alarmed ;;
            listening) f=$_spark_fc_listening ;;
        esac
        [[ -n $f ]] || f=$_spark_fc_idle
        if [[ -n $f ]]; then
            _spark_ft="${1:0:1} $f ${1:2}"
            _spark_fn=$(( ${#f} + 2 ))
        fi
    fi
    _spark_mood=''
}
# the resting face, alone in spark's row. bash has no hook after the
# prompt is drawn, so, like the failure line, the face is printed before
# it WITHOUT a newline, and the prompt's own opening newline ends it: it
# IS the blank row. Only where that row is known: the prompt opens with
# a newline and has as many lines as the row is high, or starship draws
# it. A row of spaces goes first: at the left edge it fills the row and
# the cursor comes back; after output that ended without a newline it
# wraps, and the face starts a row of its own -- so clearing the face's
# row at Enter never takes a line of output with it.
_spark_idle() {
    local p nl lf=$'\n' w=${COLUMNS:-80}
    [[ -n $_spark_fc_idle ]] && (( w > 12 )) && _spark_face_on || return 0
    if [[ -z ${STARSHIP_SHELL:-} ]]; then
        [[ $PS1 == \\n* || $PS1 == "$lf"* ]] || return 0
        p=${PS1//\\n/$lf}
        nl=${p//[!$lf]/}
        (( ${#nl} == _spark_height )) || return 0
    fi
    _spark_paint "$_spark_fc_idle" "${#_spark_fc_idle}"
    printf '%*s\r%s' "$w" '' "$_spark_out"
    _spark_faced=1
}
# and gone again: only a row the resting face stands in is cleared
_spark_unface() {
    [[ -n $_spark_faced ]] || return 0
    _spark_faced=''
    printf '\0337\033[%dA\r\033[2K\0338' "$_spark_height"
}

# The row is _spark_height rows up (1 unless the look file or SPARK_HEIGHT
# says more: a two-line prompt takes 2). The face counts toward the
# width. What it writes replaces the resting face: _spark_faced is spent.
_spark_hinted=''          # spark drew in the row above since this prompt came
_spark_say() {   # _spark_say TEXT  -- write into the row above, cursor untouched
    local t=$1 w=${COLUMNS:-80}
    [[ -n $t ]] && _spark_hinted=1
    _spark_face "$t"
    t=$_spark_ft
    (( ${#t} > w - 2 )) && t=${t:0:w-3}$_spark_d
    # shellcheck disable=SC2086  # empty means no count: the mark alone
    _spark_paint "$t" $_spark_fn
    _spark_faced=''
    printf '\0337\033[%dA\r\033[2K%s\0338' "$_spark_height" "$_spark_out"
}

# The line streams (contract 4): line 1 -- the command, its danger known --
# arrives first. The layout: everything spark says lives in the row above
# (the mark, the pulse, the facts, the hint, an answer); the prompt line
# holds only the command to run, empty for an answer. The mark is painted
# BEFORE the command lands, so a danger line is never in the line without
# its !. A bind -x handler hands the line to readline only when it
# returns, so the handler lands line 1 and returns; a reader in the
# background (disowned, its output nowhere) draws line 2 into the row
# above through /dev/tty -- save the cursor, up one, clear, draw, restore:
# text.Busy's frame, never a byte on the prompt line -- and keeps line 3's
# proof in _spark_pf, where the next prompt picks it up. The file is
# 0600; the prompt empties it with no fork, and the next question and the
# shell's exit remove it. The next Enter,
# Esc s, Esc r or prompt stops a reader still waiting, and its spark line.
# One row up is the row above only while the prompt and the command fit
# one row with room to type; past that (or before bash 4.4) the handler
# waits for the whole reply, as it always did.
_spark_rd='' _spark_lp='' _spark_pw='' _spark_pf=$SPARK_DIR/proof.$$
_SPARK_ROOM=16            # columns left free to type in before the row would wrap

_spark_reap() {   # the reader of an earlier answer, and its spark line, stop
    [[ -n $_spark_rd ]] || return 0
    kill "$_spark_rd" "$_spark_lp" 2>/dev/null
    _spark_rd='' _spark_lp=''
}

_spark_keep() {   # _spark_keep CMD LINE3  -- the reader's proof, for the next prompt
    # a fresh file, 0600 whatever the shell's umask: umask 077 in a subshell
    case $2 in
        proof$'\t'*) ( umask 077; rm -f -- "$_spark_pf"; printf '%s\n%s\n' "$1" "${2#proof$'\t'}" > "$_spark_pf" ) ;;
    esac
}

_spark_rest() {   # _spark_rest FD MARK TAIL CMD NONE MOOD  -- lines 2 and 3, in the background
    local fd=$1 mark=$2 tail=$3 cmd=$4 none=$5 mood=$6 hint='' l3=''
    IFS= read -r hint <&"$fd"
    [[ -n $hint || $mood == alarmed ]] || mood=puzzled
    # a proof already here is kept before the hint shows: an Enter on the
    # hint then finds it
    if read -t 0 -u "$fd"; then IFS= read -r l3 <&"$fd"; _spark_keep "$cmd" "$l3"; fi
    _spark_mood=$mood
    _spark_say "$mark ${hint:-$none}$tail" > /dev/tty
    trap '' TERM          # drawn: nothing left that could land on a later screen
    [[ -z $l3 ]] && IFS= read -r l3 <&"$fd" && _spark_keep "$cmd" "$l3"
}

_spark_prow() {   # the prompt's last row: _spark_pp as drawn, _spark_pn its columns
    local p v
    _spark_pp='' _spark_pn=-1
    (( BASH_VERSINFO[0] > 4 || BASH_VERSINFO[1] >= 4 )) || return 1
    p=${PS1@P}
    p=${p##*$'\n'}
    v=$p
    while [[ $v == *$'\001'*$'\002'* ]]; do v=${v%%$'\001'*}${v#*$'\002'}; done
    p=${p//$'\001'/} p=${p//$'\002'/}
    _spark_pp=$p _spark_pn=${#v}
}

_spark_fits() {   # _spark_fits CMD  -- true when prompt + CMD leave room on one row
    (( _spark_pn >= 0 && _spark_pn + ${#1} + _SPARK_ROOM <= ${COLUMNS:-80} ))
}

# The words stay on screen while spark thinks. readline clears the
# prompt's row before it runs a bind -x handler, and draws it again only
# when the handler returns: through a think of seconds the row would
# stand empty. _spark_hold writes the prompt's last row and the words
# back as they were, then leaves the cursor where the words begin -- on
# the prompt's own row, however far they wrap, so the row above is still
# the hint row. _spark_drop clears them just before the handler returns:
# readline then draws the new line (line 1, painted once) on a blank
# row, for its redraw does not clear what a longer question left.
_spark_held=''
_spark_hold() {   # _spark_hold WORDS
    local t=${1//[[:cntrl:]]/ } w=${COLUMNS:-80} up
    _spark_prow || return 0
    (( w > 0 )) || return 0
    # ${#t} counts characters, not columns: a wide character would put
    # the cursor a row off, so a question or prompt beyond ASCII is not held
    [[ $t$_spark_pp == *[![:ascii:]]* ]] && return 0
    up=$(( (_spark_pn + ${#t} - 1) / w ))
    t=$'\r'$_spark_pp$t
    (( up > 0 )) && t+=$'\033['$up'A'
    t+=$'\r'
    (( _spark_pn > 0 )) && t+=$'\033['$_spark_pn'C'
    _spark_held=1
    printf '%s' "$t"          # one write: a pulse frame never lands inside it
}
_spark_drop() {
    [[ -n $_spark_held ]] || return 0
    _spark_held=''
    printf '\r\033[J'
}

_spark_ask() {   # _spark_ask LINE  -- ask, then edit READLINE_LINE
    _spark_asked "$1"
    _spark_drop
}

_spark_asked() {
    local line=$1 fd kind cmd='' hint line3 mark=$_spark_h tail='' none='no hint came' mood=''
    _spark_reap
    _spark_mood=thinking
    _spark_say "$_spark_h $_spark_d"
    _spark_proof='' _spark_proof_for='' _spark_pw=''
    rm -f -- "$_spark_pf"
    # the buffer as typed, before spark line starts: its pulse never
    # draws while these words are on their way
    _spark_hold "$READLINE_LINE"
    # SPARK_HINT_ROW=N: spark line may pulse in that row, N up (text.Busy),
    # while the model answers -- then in the reply's own mark until the hint
    exec {fd}< <(SPARK_HINT_ROW=$_spark_height exec "$SPARK_BIN" line --cwd "$PWD" --shell bash <<< "$line" 2>/dev/null)
    _spark_lp=$!
    IFS= read -r kind <&"$fd"
    case $kind in
        cmd$'\t'*|danger$'\t'*)
            cmd=${kind#*$'\t'}
            [[ $kind == danger$'\t'* ]] && mark=$_spark_w tail=' -- read it before Enter' mood=alarmed
            _spark_mood=${mood:-thinking}
            _spark_say "$mark $_spark_d$tail"
            READLINE_LINE=$cmd; READLINE_POINT=${#cmd} ;;
        answer)
            none='no answer came' mood=pleased
            READLINE_LINE=''; READLINE_POINT=0 ;;
        *)
            IFS= read -r hint <&"$fd"
            exec {fd}<&-
            [[ -n $kind && $kind != error ]] && hint=$kind    # not contract 4: say what came
            _spark_mood=alarmed
            _spark_say "$_spark_h ${hint:-no model answers}"
            return ;;
    esac
    if _spark_fits "$cmd"; then
        # the shell's own `[1] pid` notice goes to the group's stderr: nowhere
        { _spark_rest "$fd" "$mark" "$tail" "$cmd" "$none" "$mood" < /dev/null > /dev/null 2>&1 & } 2>/dev/null
        _spark_rd=$! _spark_pw=1
        disown "$_spark_rd" 2>/dev/null
        exec {fd}<&-
        return
    fi
    IFS= read -r hint <&"$fd"
    IFS= read -r line3 <&"$fd"
    exec {fd}<&-
    case $line3 in proof$'\t'*) _spark_proof=${line3#proof$'\t'} _spark_proof_for=$cmd ;; esac
    [[ -n $hint || $mood == alarmed ]] || mood=puzzled
    _spark_mood=$mood
    _spark_say "$mark ${hint:-$none}$tail"
}

# --- the failure moment ------------------------------------------------------
# The verbatim command is captured at Enter from $READLINE_LINE -- never
# from history -- and lives in shell variables: per pane, nothing on disk,
# never exported, gone with the shell. A capture still unconsumed at the
# next Enter means no prompt was drawn between them (a PS2 continuation):
# the lines accumulate and the newline refuses the offer.
_spark_cmd='' _spark_fail='' _spark_fail_rc=0
_spark_explained='' _spark_explained_rc='' _spark_fix='' _spark_offer_fix=''
_spark_proof='' _spark_proof_for='' _spark_offer_proof=''
# One list per judgment, the same lists in widget.zsh (tests/smoke.py
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
    local i=0
    local -a w
    read -ra w <<< "$1"
    while (( i < ${#w[@]} )); do
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
    while IFS= read -r seg; do
        [[ -n ${seg//[[:space:]]/} ]] || continue
        _spark_head_of "$seg"
        case " $_SPARK_DANGER " in
            *" $_spark_seg_head "*) _spark_kind=danger; _spark_head=$_spark_seg_head; return 0 ;;
        esac
    done <<< "$segs"
    _spark_kind=ask
    return 0
}

# the test surface: _spark_offer_kind CMD RC prints ask | danger | none
_spark_offer_kind() { _spark_kind_of "$1" "$2"; printf '%s\n' "$_spark_kind"; }

# the failure line goes in the hint row, like every line spark says at
# the prompt, so the next one there replaces it. At PROMPT_COMMAND time
# the prompt is not drawn yet, and bash has no hook after it: the line is
# printed WITHOUT its newline, and the prompt's own opening newline (the
# hook's blank row, starship's add_newline) ends it -- so it IS the blank
# row. A prompt that opens otherwise gets the newline here. The line
# carries its mood's face (_spark_note TEXT [MOOD]).
_spark_note() {
    local t=$1 w=${COLUMNS:-80}
    _spark_mood=${2:-}
    _spark_face "$t"
    t=$_spark_ft
    (( ${#t} > w - 2 )) && t=${t:0:w-3}$_spark_d
    # shellcheck disable=SC2086  # empty means no count: the mark alone
    _spark_paint "$t" $_spark_fn
    _spark_hinted=1
    if [[ -n ${STARSHIP_SHELL:-} || $PS1 == \\n* || $PS1 == $'\n'* ]]; then printf '%s' "$_spark_out"
    else printf '%s\n' "$_spark_out"; fi
}

# a capture still here means no prompt came between: a PS2 continuation
_spark_capture() {
    if [[ -n $_spark_cmd ]]; then _spark_cmd=$_spark_cmd$'\n'$1
    else _spark_cmd=$1; fi
}

# how long a command ran, for a failure on an awake machine
_SPARK_LONG=30 _spark_t0=''

# In bash, unlike zsh, $? is NOT restored between the parts of
# PROMPT_COMMAND (nor between the elements of the 5.1+ array form): only
# the FIRST part sees the command's status. spark goes first, and hands
# the status back with `return`, so starship -- or anything else behind
# it -- still sees the truth. The look file is checked first (one stat
# while it has not changed); then the failure moment; then, in a row
# no line took, the resting face.
_spark_failed() {
    local rc=$? took='' d
    _spark_look_check
    if [[ -n $_spark_t0 && $_spark_lk_awake == yes ]]; then
        d=$(( SECONDS - _spark_t0 ))
        if (( d > _SPARK_LONG )); then
            if (( d < 90 )); then took=" after $d s"; else took=" after $(( d / 60 )) min"; fi
        fi
    fi
    _spark_t0=''
    _spark_faced=''                       # a new prompt: the row above holds no face yet
    _spark_failure "$rc" "$took"
    [[ -n $_spark_hinted ]] || _spark_idle
    return $rc
}

# the failure moment: RC and, for a long command, " after N s|min"
_spark_failure() {
    local rc=$1 took=$2 cmd=$_spark_cmd
    _spark_cmd='' _spark_hinted=''       # a new prompt: the row above is not spark's
    unset SPARK_EXPLAIN_CMD SPARK_EXPLAIN_RC
    _spark_offer_fix=''
    _spark_reap
    if [[ -n $_spark_pw ]]; then          # the background reader's proof, if one came
        _spark_pw=''
        if [[ -s $_spark_pf ]]; then
            { IFS= read -r _spark_proof_for; IFS= read -r _spark_proof; } < "$_spark_pf"
            : > "$_spark_pf"
        fi
    fi
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
                *" ${cmd%% *} "*) ;;
                *) _spark_fix=$cmd ;;     # the first success after an explain
            esac
        fi
        if [[ -n $_spark_proof && $cmd == "$_spark_proof_for" ]]; then
            # contract 4's proof line: the proposed command just ran --
            # the read-only check is one Esc s away
            _spark_offer_proof=$_spark_proof
            if [[ $_spark_k_ask == none ]]; then _spark_note "$_spark_h done -- check it: $_spark_proof" pleased
            else _spark_note "$_spark_h done -- $_spark_k_ask checks it: $_spark_proof" pleased; fi
            _spark_proof='' _spark_proof_for=''
        fi
        _spark_fail=''
        return 0
    fi
    if [[ $cmd == *"| explain"* || $cmd == *"|explain"* ]]; then
        return 0                          # explain itself failed: the offer stays
    fi
    _spark_kind_of "$cmd" "$rc"
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
        elif [[ $_spark_k_ask == none ]]; then
            _spark_note "$_spark_h failed ($rc)$took -- ? words asks about it" alarmed
        elif (( rc == 127 )); then
            _spark_note "$_spark_h failed (127)$took -- $_spark_head not found; $_spark_k_ask gets the install line" alarmed
        else
            _spark_note "$_spark_h failed ($rc)$took -- $_spark_k_ask asks why" alarmed
        fi
    fi
    return 0
}

# first in PROMPT_COMMAND, once, whatever shape it is in -- appended, it
# would read the status of whatever ran before it (starship's, always 0)
_spark_pc_array=0
(( BASH_VERSINFO[0] > 5 || (BASH_VERSINFO[0] == 5 && BASH_VERSINFO[1] >= 1) )) \
    && [[ ${PROMPT_COMMAND@a} == *a* ]] && _spark_pc_array=1
case " ${PROMPT_COMMAND[*]-} " in
    *_spark_failed*) ;;                   # a re-source, a nested rc, a tmux pane
    *)  if (( _spark_pc_array )); then
            PROMPT_COMMAND=(_spark_failed "${PROMPT_COMMAND[@]}")
        elif [[ -z ${PROMPT_COMMAND:-} ]]; then
            PROMPT_COMMAND=_spark_failed
        else
            PROMPT_COMMAND="_spark_failed; $PROMPT_COMMAND"
        fi ;;
esac
unset _spark_pc_array

# --- Enter ------------------------------------------------------------------
_spark_enter() {
    _spark_reap                           # a hint still on its way would land on the output
    _spark_unface                         # the resting face goes before the line does
    if [[ -e $SPARK_DIR/off ]]; then
        bind '"\C-x\C-a": accept-line'
        _spark_cmd=''                     # off: nothing arms, nothing prints
        return
    fi
    if ! _spark_is_question "$READLINE_LINE"; then
        bind '"\C-x\C-a": accept-line'
        [[ -n $_spark_cmd ]] || _spark_t0=$SECONDS   # how long it runs
        _spark_capture "$READLINE_LINE"   # verbatim, before anything expands
        return
    fi
    bind '"\C-x\C-a": redraw-current-line'
    _spark_ask "$READLINE_LINE"           # a question: nothing runs, nothing
}                                         # is captured, no prompt is drawn
bind -x '"\C-x\C-s": _spark_enter'
bind '"\C-x\C-a": accept-line'
bind '"\C-m": "\C-x\C-s\C-x\C-a"'
bind '"\C-j": "\C-x\C-s\C-x\C-a"'

# --- Ctrl-U: an emptied line takes its hint with it ------------------------
# The hint labels the line; once the user empties the line, it labels
# nothing. bash says nothing when the line changes, so Ctrl-U becomes a
# two-key macro like Enter: unix-line-discard first (the kill ring keeps
# the words for Ctrl-Y), then _spark_unhint. It clears the row above
# only when the line is now empty and spark drew in that row since the
# prompt came: a row spark never wrote is never touched. A hint still on
# its way stops first, or it would land on the empty prompt.
_spark_unhint() {
    [[ -z $READLINE_LINE && -n $_spark_hinted ]] || return 0
    _spark_reap
    _spark_say ''
    _spark_hinted=''
}
bind -x '"\C-x\C-o": _spark_unhint'
# Ctrl-U keeps the function it had (an inputrc's kill-whole-line too);
# a Ctrl-U that is a macro or a bind -x of the user's is left alone
_spark_ctrlu='' _spark_re='^"\\C-u": ([a-z-]*)$'
while IFS= read -r _spark_bl; do
    if [[ $_spark_bl =~ $_spark_re ]]; then _spark_ctrlu=${BASH_REMATCH[1]}; break; fi
done <<< "$_spark_binds"
unset _spark_re _spark_bl
if [[ -n $_spark_ctrlu && $_spark_ctrlu != self-insert ]]; then
    bind "\"\\C-x\\C-k\": $_spark_ctrlu"
    bind '"\C-u": "\C-x\C-k\C-x\C-o"'
fi

# --- Esc s: ask about this line, no question mark needed --------------------
# On an empty line it serves the failure moment first: a pending failure
# becomes `cmd 2>&1 | explain` in your line (the command and its exit
# code ride along for that one run); a fix that just worked becomes a
# `spark memory add` line. Either way you press Enter.
_spark_ask_line() {
    local fact
    _spark_reap
    if [[ -n $READLINE_LINE ]]; then _spark_ask "$READLINE_LINE"; return; fi
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
        READLINE_LINE="{ $fact; } 2>&1 | explain"
        READLINE_POINT=${#READLINE_LINE}
        _spark_say "$_spark_h Enter explains the error"
    elif [[ -n $_spark_offer_proof ]]; then
        # the proof the line proposed: lands ready to run, read-only
        READLINE_LINE=$_spark_offer_proof
        READLINE_POINT=${#READLINE_LINE}
        _spark_offer_proof=''
        _spark_say "$_spark_h Enter runs the check"
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
        READLINE_LINE="spark memory add '${fact//\'/\'\\\'\'}'"
        READLINE_POINT=${#READLINE_LINE}
        _spark_say "$_spark_h Enter remembers the fix"
    else
        _spark_mood=puzzled
        _spark_say "$_spark_h type a question, then $_spark_k_ask"
    fi
}
_spark_key ask _spark_ask_line

# --- Esc r: intent search over the shell's own history ---------------------
# First press: the buffer is what you are looking for; the shell's history
# goes to `spark recall` on stdin, and candidate 1 lands in the line. Press
# again, buffer unchanged, to cycle. Ctrl-R is left to the shell.
_spark_recall_cands=() _spark_recall_i=0 _spark_recall_for=''
# land candidate _spark_recall_i in the line; a `!<TAB>` prefix from
# `spark recall` means the line can destroy -- stripped, and the warn
# mark shows instead of the answer mark
_spark_recall_show() {
    local cand=${_spark_recall_cands[_spark_recall_i]} mark=$_spark_h note=''
    if [[ $cand == $'!\t'* ]]; then
        cand=${cand#$'!\t'}
        mark=$_spark_w note=' -- careful' _spark_mood=alarmed
    fi
    READLINE_LINE=$cand
    READLINE_POINT=${#cand}
    _spark_recall_for=$cand
    _spark_say "$mark $(( _spark_recall_i + 1 ))/${#_spark_recall_cands[@]}$note -- $_spark_k_recall for the next"
}
_spark_recall() {
    _spark_reap
    [[ -e $SPARK_DIR/off ]] && return
    if [[ -n $READLINE_LINE && $READLINE_LINE == "$_spark_recall_for" && ${#_spark_recall_cands[@]} -gt 0 ]]; then
        # a repeat with the landed candidate still in the line: cycle
        _spark_recall_i=$(( (_spark_recall_i + 1) % ${#_spark_recall_cands[@]} ))
        _spark_recall_show
        return
    fi
    local intent=$READLINE_LINE
    if [[ -z $intent ]]; then
        _spark_mood=puzzled
        _spark_say "$_spark_h type what the command did, then $_spark_k_recall"
        return
    fi
    _spark_mood=thinking
    _spark_say "$_spark_h $_spark_d"
    local out
    _spark_hold "$READLINE_LINE"          # the words stay while the search runs
    # SPARK_HINT_ROW=N: spark recall may pulse in that row while it asks
    out=$(fc -ln -400 2>/dev/null | SPARK_HINT_ROW=$_spark_height "$SPARK_BIN" recall "$intent" 2>/dev/null)
    _spark_drop
    if [[ -z $out ]]; then
        _spark_mood=puzzled
        _spark_say "$_spark_h nothing in your history matches"
        return
    fi
    mapfile -t _spark_recall_cands <<< "$out"
    _spark_recall_i=0
    _spark_recall_show
}
_spark_key recall _spark_recall

# --- Esc k: move spark's row -------------------------------------------------
# 1, 2, 3, then 1 again: the row spark writes in, counted up from the line
# you type on. A two-line prompt (starship's default) needs 2. `spark
# height N` keeps the choice for every shell (quietly; without it the
# choice lasts this shell); a test line shows where the row is now. A row
# spark drew in at the old height is cleared first, and only that one.
_spark_height_key() {
    local n=1
    _spark_reap
    [[ -e $SPARK_DIR/off ]] && return
    (( _spark_height < 3 )) && n=$(( _spark_height + 1 ))
    [[ -n $_spark_hinted ]] && _spark_say ''
    _spark_unface                         # the resting face leaves the old row too
    _spark_height=$n
    [[ -n ${SPARK_HEIGHT:-} ]] && SPARK_HEIGHT=$n
    "$SPARK_BIN" height "$n" </dev/null >/dev/null 2>&1
    _spark_say "$_spark_h spark writes here -- $_spark_k_height moves it"
}
_spark_key height _spark_height_key

# --- Esc v: listen; Esc x: stop speaking -------------------------------------
# Esc v hands the hearing to `spark voice listen --buffer` (the words on
# stdout and nothing else; a pause ends them) and lands the words at the
# cursor -- on an empty line as a `? ` question, so Enter asks spark and
# never runs what was heard. While it listens the row says so. Esc x is
# `spark voice stop`.
_spark_listen() {
    local words rc
    _spark_reap
    [[ -e $SPARK_DIR/off ]] && return
    _spark_mood=listening
    _spark_say "$_spark_h listening -- a pause ends it"
    _spark_hold "$READLINE_LINE"          # the line stays while it listens
    words=$("$SPARK_BIN" voice listen --buffer </dev/null 2>/dev/null)
    rc=$?
    _spark_drop
    words=${words//[[:cntrl:]]/ }
    if (( rc == 0 )) && [[ -n ${words//[[:space:]]/} ]]; then
        if [[ -z $READLINE_LINE ]]; then
            READLINE_LINE="? $words"; READLINE_POINT=${#READLINE_LINE}
            _spark_say "$_spark_h heard -- Enter asks it"
        else
            (( READLINE_POINT > 0 )) && [[ ${READLINE_LINE:READLINE_POINT-1:1} != [[:space:]] ]] && words=" $words"
            READLINE_LINE=${READLINE_LINE:0:READLINE_POINT}$words${READLINE_LINE:READLINE_POINT}
            READLINE_POINT=$(( READLINE_POINT + ${#words} ))
            _spark_say "$_spark_h heard -- in your line"
        fi
    elif (( rc == 1 || rc == 130 )); then
        _spark_mood=puzzled
        _spark_say "$_spark_h nothing heard"
    else
        _spark_say "$_spark_h $_spark_k_listen needs the voice -- spark voice on"
    fi
}
_spark_hush() { "$SPARK_BIN" voice stop </dev/null >/dev/null 2>&1; }
# bound only where the voice is on or clear as the shell starts --
# SPARK_VOICE from the environment, else spark.env's line, read line by
# line and never sourced; off, Esc v and Esc x stay readline's own
_spark_voice=${SPARK_VOICE-}
_spark_vf=${XDG_CONFIG_HOME:-$HOME/.config}/spark/spark.env
if [[ -z $_spark_voice && -r $_spark_vf ]]; then
    _spark_vn=0
    while (( _spark_vn++ < 256 )) && { IFS= read -r _spark_vl || [[ -n $_spark_vl ]]; }; do
        [[ $_spark_vl == SPARK_VOICE=* ]] && _spark_voice=${_spark_vl#SPARK_VOICE=}
    done < "$_spark_vf"
fi
_spark_voice=${_spark_voice#\"}; _spark_voice=${_spark_voice%\"}
case ${_spark_voice,,} in
    on|clear) _spark_key listen _spark_listen; _spark_key stop _spark_hush ;;
esac
unset _spark_vf _spark_vl _spark_vn
# what each key did before spark took it, for `spark keys`: written only
# when it is not what the file already says
_spark_ro=''
{
    [[ -r $SPARK_DIR/replaced.bash ]] && IFS= read -r -d '' _spark_ro < "$SPARK_DIR/replaced.bash"
    [[ $_spark_ro == "$_spark_rec" ]] || printf '%s' "$_spark_rec" >| "$SPARK_DIR/replaced.bash"
} 2>/dev/null
unset _spark_ro _spark_rec _spark_binds

# --- paste inspection: a multi-line paste into an EMPTY prompt --------------
# Rebinding the paste-begin sequence takes the paste from readline: the
# handler reads the terminal's own bytes up to the end marker, puts them
# in the line UNTOUCHED (newlines stay literal -- nothing runs), and,
# for two or more lines into an empty prompt, asks `spark line --paste`
# for one answer/danger line. spark off (and SPARK_OFF at load) disable
# the inspection; the paste itself always lands.
_spark_paste() {
    local before=$READLINE_LINE buf='' ch
    _spark_reap
    while IFS= read -r -s -N1 -t 2 ch; do
        buf+=$ch
        [[ $buf == *$'\e[201~' ]] && { buf=${buf%$'\e[201~'}; break; }
    done
    READLINE_LINE=${READLINE_LINE:0:READLINE_POINT}$buf${READLINE_LINE:READLINE_POINT}
    READLINE_POINT=$(( READLINE_POINT + ${#buf} ))
    [[ -e $SPARK_DIR/off ]] && return
    if [[ -z $before && $buf == *$'\n'?* ]]; then
        local out kind text
        out=$(SPARK_HINT_ROW=$_spark_height "$SPARK_BIN" line --paste <<< "$buf" 2>/dev/null)
        kind=${out%%$'\n'*}
        text=${out#*$'\n'}
        text=${text%%$'\n'*}
        case $kind in
            danger) _spark_mood=alarmed; _spark_say "$_spark_w $text -- pasted, not run" ;;
            answer) _spark_say "$_spark_h $text -- pasted, not run" ;;
        esac
    fi
}
bind -x '"\e[200~": _spark_paste'

# Esc and s are two keystrokes: give them a full second to be one chord
# (only where a key of spark's starts with Esc)
if [[ -n $_spark_esc ]]; then bind 'set keyseq-timeout 1000'; fi
unset _spark_esc
