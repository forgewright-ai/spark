# spark widget.zsh -- the AI at the prompt, for zsh. Sourced by .zshrc
# after fzf. Symlinked from the spark repository.
#
#   ? words    or    words?     Enter sends the line to `spark line`; the
#              command it returns lands IN your line with a hint in the row
#              above the prompt. Nothing runs until you press Enter again.
#   Esc a      asks about whatever line you are on, question mark or not.
#   spark off / spark on        silence / restore (a flag file, checked at
#              every Enter, so one `spark off` reaches every pane at once)
#   SPARK_OFF=1                 in the environment: bind nothing at all

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
mkdir -p "$SPARK_DIR/widgets" 2>/dev/null && chmod 700 "$SPARK_DIR" 2>/dev/null
print -r -- "zsh $$ $EPOCHSECONDS" > "$SPARK_DIR/widgets/$$" 2>/dev/null
_spark_gone() { rm -f "$SPARK_DIR/widgets/$$"; }
autoload -Uz add-zsh-hook
add-zsh-hook zshexit _spark_gone

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

# --- the hint row: the blank line above the prompt --------------------------
# One row up from the cursor, so the edit line must be a single row when this
# runs (a wrapped question would make "the row above" the prompt itself), and
# the text must fit the width (a wrapped hint would push the prompt down).
_spark_say() {
    local t=$1
    (( ${#t} > COLUMNS - 2 )) && t=${t[1,COLUMNS-3]}$_spark_d
    print -n -- $'\e7\e[1A\r\e[2K'"$t"$'\e8'
}

_spark_ask() {
    local line=$1 out kind cmd hint
    # a long question wraps: empty the line first, so the cursor is back on
    # the prompt's row and the hint lands in the blank row above it
    BUFFER=''; CURSOR=0; zle -R
    _spark_say "$_spark_h $_spark_d"
    out=$(print -r -- "$line" | "$SPARK_BIN" line --cwd "$PWD" --shell zsh 2>/dev/null)
    kind=${out%%$'\n'*}
    hint=${out#*$'\n'}
    hint=${hint%%$'\n'*}
    case $kind in
        cmd$'\t'*)
            cmd=${kind#cmd$'\t'}
            _spark_say "$_spark_h $hint"
            BUFFER=$cmd; CURSOR=$#BUFFER ;;
        danger$'\t'*)
            cmd=${kind#danger$'\t'}
            _spark_say "$_spark_w $hint -- read it before Enter"
            BUFFER=$cmd; CURSOR=$#BUFFER ;;
        answer)
            _spark_say "$_spark_h $hint"
            BUFFER=''; CURSOR=0 ;;
        *)
            _spark_say "$_spark_h ${hint:-no brain awake}"
            BUFFER=$line; CURSOR=$#BUFFER ;;      # the question stays yours
    esac
    zle -R
}

# --- Enter: wrap whatever accept-line already is ----------------------------
_spark_orig_accept=${widgets[accept-line]#user:}
[[ $_spark_orig_accept == builtin ]] && _spark_orig_accept=.accept-line
spark-accept-line() {
    if [[ -e $SPARK_DIR/off ]] || ! _spark_is_question "$BUFFER"; then
        zle "$_spark_orig_accept"
        return
    fi
    _spark_ask "$BUFFER"
}
zle -N spark-accept-line
bindkey '^M' spark-accept-line
bindkey '^J' spark-accept-line

# --- Esc a: ask about this line, no question mark needed --------------------
spark-ask() {
    if [[ -n $BUFFER ]]; then _spark_ask "$BUFFER"
    else _spark_say "$_spark_h type something first, then Esc a  (or end the line with ?)"; zle -R; fi
}
zle -N spark-ask
bindkey '\ea' spark-ask
# Esc and a are two keystrokes: give them a full second to be one chord
KEYTIMEOUT=100
