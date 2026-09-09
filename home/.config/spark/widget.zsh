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
#   spark off / spark on        silence / restore (a flag file, checked at
#              every Enter and on the failing path, so one `spark off`
#              reaches every pane at once)
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
# contract 6: <shell> <pid> <epoch> [hook] -- the fourth field says this
# shell's exit-code hook is armed; readers ignore fields they do not know.
# EPOCHSECONDS is empty until zsh/datetime is loaded (a bare zsh -f showed
# a two-field marker); load it, and keep 0 as the honest fallback.
zmodload zsh/datetime 2>/dev/null
mkdir -p "$SPARK_DIR/widgets" 2>/dev/null && chmod 700 "$SPARK_DIR" 2>/dev/null
print -r -- "zsh $$ ${EPOCHSECONDS:-0} hook" > "$SPARK_DIR/widgets/$$" 2>/dev/null
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

# --- the failure moment ------------------------------------------------------
# The verbatim command is captured at Enter from $BUFFER -- never from
# history -- and lives in shell variables: per pane, nothing on disk,
# never exported, gone with the shell. A capture still unconsumed at the
# next Enter means no prompt was drawn between them (a PS2 continuation):
# the lines accumulate and the newline refuses the offer.
typeset -g _spark_cmd='' _spark_fail='' _spark_fail_rc=0
typeset -g _spark_explained='' _spark_explained_rc='' _spark_fix='' _spark_offer_fix=''
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

# what a failed command deserves: sets _spark_kind to ask (the offer),
# danger (seen, never re-run) or none. The head word is the first word
# past leading VAR=val assignments and sudo/env/command/time/nohup,
# basename'd, mkfs.* folded to mkfs; a shell keyword (a continuation
# fragment), a history bang and a line already piping to explain are none.
_spark_kind_of() {
    local cmd=$1 rc=$2 head i
    local -a w
    _spark_kind=none _spark_head=''
    case " $_SPARK_QUIET_RC " in *" $rc "*) return 0 ;; esac
    [[ $cmd == *$'\n'* ]] && return 0
    case $cmd in *"| explain"*|*"|explain"*) return 0 ;; esac
    w=( ${=cmd} )
    i=1
    while (( i <= ${#w} )); do
        case ${w[i]} in
            [A-Za-z_]*=*|sudo|env|command|time|nohup) (( i++ )) ;;
            *) break ;;
        esac
    done
    head=${w[i]:-}
    head=${head##*/}
    [[ $head == mkfs.* ]] && head=mkfs
    _spark_head=$head
    case $head in ''|\!*|spark|explain|done|fi|esac|then|else|do) return 0 ;; esac
    if (( rc == 1 )); then
        case " $_SPARK_QUIET_ONE " in *" $head "*) return 0 ;; esac
    fi
    case " $_SPARK_DANGER " in *" $head "*) _spark_kind=danger; return 0 ;; esac
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
    print -r -- "$t"
}

# a capture still here means no prompt came between: a PS2 continuation
_spark_capture() {
    if [[ -n $_spark_cmd ]]; then _spark_cmd=$_spark_cmd$'\n'$1
    else _spark_cmd=$1; fi
}

# $? is read first and handed back last, so a later precmd (a git
# prompt, starship) still sees the command's own status.
_spark_failed() {
    local rc=$? cmd=$_spark_cmd
    _spark_cmd=''
    unset SPARK_EXPLAIN_CMD SPARK_EXPLAIN_RC
    _spark_offer_fix=''
    # no capture: an empty Enter, Ctrl-C at the prompt, or a key spark
    # does not own. Nothing prints twice; a standing offer survives.
    [[ -n $cmd ]] || return $rc
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
        _spark_fail=''
        return 0
    fi
    if [[ $cmd == *"| explain"* || $cmd == *"|explain"* ]]; then
        return $rc                        # explain itself failed: the offer stays
    fi
    _spark_kind_of "$cmd" $rc
    [[ $_spark_kind == none ]] && return $rc
    if [[ -e $SPARK_DIR/off ]]; then      # only ever stat'd on a failing path
        _spark_fail=''
        return $rc
    fi
    if [[ $_spark_kind == danger ]]; then
        _spark_fail=''
        _spark_note "$_spark_h failed ($rc) -- $_spark_head: not re-run; ? words asks about it"
    else
        _spark_fail=$cmd _spark_fail_rc=$rc _spark_explained='' _spark_explained_rc='' _spark_fix=''
        if (( rc == 127 )); then
            _spark_note "$_spark_h failed (127) -- $_spark_head not found; Esc s offers the install line"
        else
            _spark_note "$_spark_h failed ($rc) -- press Esc s to ask why"
        fi
    fi
    return $rc
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
        _spark_capture "$BUFFER"          # verbatim, before anything expands
        zle "$_spark_orig_accept"
        return
    fi
    _spark_ask "$BUFFER"                  # a question: nothing runs, nothing
}                                         # is captured, no prompt is drawn
zle -N spark-accept-line
bindkey '^M' spark-accept-line
bindkey '^J' spark-accept-line

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
        _spark_say "$_spark_h Enter runs it: the failure, explained"
    elif [[ -n $_spark_offer_fix ]]; then
        # the second Esc s, right after the explain: the corrected command
        export SPARK_EXPLAIN_CMD=$_spark_explained SPARK_EXPLAIN_RC=${_spark_explained_rc:-1}
        _spark_offer_fix=''
        _spark_ask "? fix it"
    elif [[ -n $_spark_fix ]]; then
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
spark-recall() {
    [[ -e $SPARK_DIR/off ]] && return
    if [[ -n $BUFFER && $BUFFER == $_spark_recall_for && ${#_spark_recall_cands[@]} -gt 0 ]]; then
        _spark_recall_i=$(( _spark_recall_i % ${#_spark_recall_cands[@]} + 1 ))
        BUFFER=${_spark_recall_cands[_spark_recall_i]}
        CURSOR=$#BUFFER
        _spark_say "$_spark_h $_spark_recall_i/${#_spark_recall_cands[@]} -- Esc r: next"
        _spark_recall_for=$BUFFER
        zle -R
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
    BUFFER=${_spark_recall_cands[1]}
    CURSOR=$#BUFFER
    _spark_recall_for=$BUFFER
    _spark_say "$_spark_h 1/${#_spark_recall_cands[@]} -- Esc r: next"
    zle -R
}
zle -N spark-recall
bindkey '\er' spark-recall
# Esc and s are two keystrokes: give them a full second to be one chord
KEYTIMEOUT=100
