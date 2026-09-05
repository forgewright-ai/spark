# spark widget.bash -- the AI at the prompt, for bash 4+. Sourced by .bashrc
# after fzf. Symlinked from the spark repository.
#
#   ? words    or    words?     Enter sends the line to `spark line`; the
#              command it returns lands IN your line with a hint in the row
#              above the prompt. Nothing runs until you press Enter again.
#   Esc s      asks about whatever line you are on, question mark or not.
#   spark off / spark on        silence / restore (a flag file, checked at
#              every Enter, so one `spark off` reaches every pane at once)
#   SPARK_OFF=1                 in the environment: bind nothing at all
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
mkdir -p "$SPARK_DIR/widgets" 2>/dev/null && chmod 700 "$SPARK_DIR" 2>/dev/null
printf 'bash %d %d\n' "$$" "$(date +%s)" > "$SPARK_DIR/widgets/$$" 2>/dev/null
_spark_gone() { rm -f "$SPARK_DIR/widgets/$$"; }
trap '_spark_gone' EXIT

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
_spark_say() {   # _spark_say TEXT  -- write into the row above, cursor untouched
    local t=$1 w=${COLUMNS:-80}
    (( ${#t} > w - 2 )) && t=${t:0:w-3}$_spark_d
    printf '\0337\033[1A\r\033[2K%s\0338' "$t"
}

_spark_ask() {   # _spark_ask LINE  -- ask, then edit READLINE_LINE
    local line=$1 out kind cmd hint
    _spark_say "$_spark_h $_spark_d"
    out=$("$SPARK_BIN" line --cwd "$PWD" --shell bash <<< "$line" 2>/dev/null)
    kind=${out%%$'\n'*}
    hint=${out#*$'\n'}
    hint=${hint%%$'\n'*}
    case $kind in
        cmd$'\t'*)
            cmd=${kind#cmd$'\t'}
            _spark_say "$_spark_h $hint"
            READLINE_LINE=$cmd; READLINE_POINT=${#cmd} ;;
        danger$'\t'*)
            cmd=${kind#danger$'\t'}
            _spark_say "$_spark_w $hint -- read it before Enter"
            READLINE_LINE=$cmd; READLINE_POINT=${#cmd} ;;
        answer)
            _spark_say "$_spark_h $hint"
            READLINE_LINE=''; READLINE_POINT=0 ;;
        *)
            _spark_say "$_spark_h ${hint:-no brain awake}" ;;
    esac
}

# --- Enter ------------------------------------------------------------------
_spark_enter() {
    if [[ -e $SPARK_DIR/off ]] || ! _spark_is_question "$READLINE_LINE"; then
        bind '"\C-x\C-a": accept-line'
        return
    fi
    bind '"\C-x\C-a": redraw-current-line'
    _spark_ask "$READLINE_LINE"
}
bind -x '"\C-x\C-s": _spark_enter'
bind '"\C-x\C-a": accept-line'
bind '"\C-m": "\C-x\C-s\C-x\C-a"'
bind '"\C-j": "\C-x\C-s\C-x\C-a"'

# --- Esc s: ask about this line, no question mark needed -------------------
_spark_ask_line() {
    if [[ -n $READLINE_LINE ]]; then _spark_ask "$READLINE_LINE"
    else _spark_say "$_spark_h type something first, then Esc s  (or end the line with ?)"; fi
}
bind -x '"\es": _spark_ask_line'
# Esc and s are two keystrokes: give them a full second to be one chord
bind 'set keyseq-timeout 1000'
