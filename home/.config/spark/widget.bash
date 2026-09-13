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
#   * failed   a nonzero exit prints that one line above the next prompt.
#              No model call, no fork, nothing written: the command you
#              typed on one line and its exit code live in this pane's
#              variables and die with it.
#   spark off / spark on        silence / restore (a flag file, checked at
#              every Enter and on the failing path, so one `spark off`
#              reaches every pane at once)
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
# contract 6: <shell> <pid> <epoch> [hook] -- the fourth field says this
# shell's exit-code hook is armed; readers ignore fields they do not know
mkdir -p "$SPARK_DIR/widgets" 2>/dev/null && chmod 700 "$SPARK_DIR" 2>/dev/null
printf 'bash %d %d hook\n' "$$" "$(date +%s)" > "$SPARK_DIR/widgets/$$" 2>/dev/null
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

# --- the failure moment ------------------------------------------------------
# The verbatim command is captured at Enter from $READLINE_LINE -- never
# from history -- and lives in shell variables: per pane, nothing on disk,
# never exported, gone with the shell. A capture still unconsumed at the
# next Enter means no prompt was drawn between them (a PS2 continuation):
# the lines accumulate and the newline refuses the offer.
_spark_cmd='' _spark_fail='' _spark_fail_rc=0
_spark_explained='' _spark_explained_rc='' _spark_fix='' _spark_offer_fix=''
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
    read -ra w <<< "$cmd"
    i=0
    while (( i < ${#w[@]} )); do
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
_spark_offer_kind() { _spark_kind_of "$1" "$2"; printf '%s\n' "$_spark_kind"; }

# the failure line: ordinary output above the coming prompt, never the
# hint row -- at PROMPT_COMMAND time the prompt (and its blank row) is not
# drawn yet, so _spark_say would eat the command's own last output row
_spark_note() {
    local t=$1 w=${COLUMNS:-80}
    (( ${#t} > w - 1 )) && t=${t:0:w-4}$_spark_d
    printf '%s\n' "$t"
}

# a capture still here means no prompt came between: a PS2 continuation
_spark_capture() {
    if [[ -n $_spark_cmd ]]; then _spark_cmd=$_spark_cmd$'\n'$1
    else _spark_cmd=$1; fi
}

# In bash, unlike zsh, $? is NOT restored between the parts of
# PROMPT_COMMAND (nor between the elements of the 5.1+ array form): only
# the FIRST part sees the command's status. spark goes first, and hands
# the status back with `return`, so starship -- or anything else behind
# it -- still sees the truth.
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
                *" ${cmd%% *} "*) ;;
                *) _spark_fix=$cmd ;;     # the first success after an explain
            esac
        fi
        _spark_fail=''
        return 0
    fi
    if [[ $cmd == *"| explain"* || $cmd == *"|explain"* ]]; then
        return $rc                        # explain itself failed: the offer stays
    fi
    _spark_kind_of "$cmd" "$rc"
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
    if [[ -e $SPARK_DIR/off ]]; then
        bind '"\C-x\C-a": accept-line'
        _spark_cmd=''                     # off: nothing arms, nothing prints
        return
    fi
    if ! _spark_is_question "$READLINE_LINE"; then
        bind '"\C-x\C-a": accept-line'
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

# --- Esc s: ask about this line, no question mark needed --------------------
# On an empty line it serves the failure moment first: a pending failure
# becomes `cmd 2>&1 | explain` in your line (the command and its exit
# code ride along for that one run); a fix that just worked becomes a
# `spark memory add` line. Either way you press Enter.
_spark_ask_line() {
    local fact
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
        _spark_say "$_spark_h Enter runs it: the failure, explained"
    elif [[ -n $_spark_offer_fix ]]; then
        # the second Esc s, right after the explain: the corrected command
        export SPARK_EXPLAIN_CMD=$_spark_explained SPARK_EXPLAIN_RC=${_spark_explained_rc:-1}
        _spark_offer_fix=''
        _spark_ask "? fix it"
    elif [[ -n $_spark_fix ]]; then
        fact="$_spark_explained failed until: $_spark_fix"
        READLINE_LINE="spark memory add '${fact//\'/\'\\\'\'}'"
        READLINE_POINT=${#READLINE_LINE}
        _spark_say "$_spark_h the fix, as a fact -- edit it, then Enter"
    else
        _spark_say "$_spark_h type something first, then Esc s  (or end the line with ?)"
    fi
}
bind -x '"\es": _spark_ask_line'

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
        mark=$_spark_w note=' -- careful'
    fi
    READLINE_LINE=$cand
    READLINE_POINT=${#cand}
    _spark_recall_for=$cand
    _spark_say "$mark $(( _spark_recall_i + 1 ))/${#_spark_recall_cands[@]}$note -- Esc r: next"
}
_spark_recall() {
    [[ -e $SPARK_DIR/off ]] && return
    if [[ -n $READLINE_LINE && $READLINE_LINE == "$_spark_recall_for" && ${#_spark_recall_cands[@]} -gt 0 ]]; then
        # a repeat with the landed candidate still in the line: cycle
        _spark_recall_i=$(( (_spark_recall_i + 1) % ${#_spark_recall_cands[@]} ))
        _spark_recall_show
        return
    fi
    local intent=$READLINE_LINE
    if [[ -z $intent ]]; then
        _spark_say "$_spark_h type what the command did, then Esc r"
        return
    fi
    _spark_say "$_spark_h $_spark_d"
    local out
    out=$(fc -ln -400 2>/dev/null | "$SPARK_BIN" recall "$intent" 2>/dev/null)
    if [[ -z $out ]]; then
        _spark_say "$_spark_h nothing in your history matches that"
        return
    fi
    mapfile -t _spark_recall_cands <<< "$out"
    _spark_recall_i=0
    _spark_recall_show
}
bind -x '"\er": _spark_recall'
# Esc and s are two keystrokes: give them a full second to be one chord
bind 'set keyseq-timeout 1000'
