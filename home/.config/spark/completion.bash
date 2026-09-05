# spark completion.bash -- TAB completes spark's verbs and their names.
# Self-contained (bash 4+; the bash-completion package is not needed) and
# sourced by hook.bash. Offline always, no python: the dynamic names come
# from the repository `command -v spark` links into (readlink), themes by
# glob, models by sed over the four model lists; when any of that fails,
# the static words still complete, silently. Binds no key of its own --
# readline's TAB does the work.
# Not completed on purpose (plumbing, gone, or aliases of ver):
#   line talk version --version

_spark_repo() {
    # ~/.local/bin/spark is a symlink to <repo>/bin/spark; print <repo>
    local bin link
    bin=$(command -v spark 2>/dev/null) || return 1
    link=$(readlink "$bin" 2>/dev/null) || return 1
    case $link in /*) ;; *) link=${bin%/*}/$link ;; esac
    link=${link%/spark}
    printf '%s\n' "${link%/bin}"
}

_spark_theme_names() {
    local repo f
    repo=$(_spark_repo) || return 0
    for f in "$repo"/themes/*.env; do
        [ -f "$f" ] || continue
        f=${f##*/}
        printf '%s\n' "${f%.env}"
    done
}

_spark_model_names() {
    # MODEL_QWEN3_1_7B= -> qwen3-1-7b, the same mapping bootstrap.sh makes
    # (tr 'A-Z_' 'a-z-'); the _LICENSE and _NOTE keys are not models
    local repo
    repo=$(_spark_repo) || return 0
    sed -n 's/^MODEL_\([A-Z0-9_]*\)=.*/\1/p' \
        "$repo/models.env" "$repo/embers.env" "$repo/community.env" \
        "$HOME/.config/spark/models.env" 2>/dev/null \
        | sed -e '/_LICENSE$/d' -e '/_NOTE$/d' | tr 'A-Z_' 'a-z-'
}

_spark_complete() {
    local cur words
    cur=${COMP_WORDS[COMP_CWORD]}
    COMPREPLY=()
    if [ "$COMP_CWORD" -eq 1 ]; then
        words="chat do serve stop check update shell headless client setup
               ver last status brain history stats bench tune model ember
               forge soul remember forget memory quiet theme font bar off
               on user explain help"
        COMPREPLY=($(compgen -W "$words" -- "$cur"))
        return 0
    fi
    [ "$COMP_CWORD" -eq 2 ] || return 0
    case ${COMP_WORDS[1]} in
        quiet)   words="start login boot on off status" ;;
        theme)   words="list show none status $(_spark_theme_names)" ;;
        model)   words="list verify budget rm add auto none status $(_spark_model_names)" ;;
        ember)   words="list auto none status $(_spark_model_names)" ;;
        shell | bar | headless | forge | memory) words="on off status" ;;
        check)   words="--watch --porcelain --selftest --fresh --fetch" ;;
        serve)   words="--foreground --host --print-client" ;;
        chat)    words="--thread" ;;
        soul)    words="show edit reset" ;;
        history) words="clear" ;;
        tune)    words="show apply" ;;
        font)    words="list none status" ;;
        client)  words="off status" ;;
        user)    words="list add remove login logout token claim status" ;;
        *)       return 0 ;;
    esac
    COMPREPLY=($(compgen -W "$words" -- "$cur"))
    return 0
}

complete -F _spark_complete spark
