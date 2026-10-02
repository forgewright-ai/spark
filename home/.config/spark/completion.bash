# spark completion.bash -- TAB completes spark's verbs and their names.
# Self-contained (bash 4+; the bash-completion package is not needed) and
# sourced by hook.bash. Offline always, no python: the dynamic names come
# from the repository `command -v spark` links into (readlink), models by
# sed over the four model lists; when any of that fails,
# the static words still complete, silently. Binds no key of its own --
# readline's TAB does the work.
# Not completed on purpose (plumbing, or aliases of ver):
#   line version --version
# Older spellings, still dispatched and named nowhere (serve boot|share,
# serve --login|--audit, model --chat and status took their places):
#   forge ember headless share brain

_spark_repo() {
    # ~/.local/bin/spark is a symlink to <repo>/bin/spark; print <repo>
    local bin link
    bin=$(command -v spark 2>/dev/null) || return 1
    link=$(readlink "$bin" 2>/dev/null) || return 1
    case $link in /*) ;; *) link=${bin%/*}/$link ;; esac
    link=${link%/spark}
    printf '%s\n' "${link%/bin}"
}

_spark_model_names() {
    # MODEL_QWEN3_1_7B= -> qwen3-1-7b, the same mapping bootstrap.sh makes
    # (tr 'A-Z_' 'a-z-'); the _LICENSE, _NOTE and _TESTED keys are not models
    local repo
    repo=$(_spark_repo) || return 0
    sed -n 's/^MODEL_\([A-Z0-9_]*\)=.*/\1/p' \
        "$repo/models.env" "$HOME/.config/spark/models.env" 2>/dev/null \
        | sed -e '/_LICENSE$/d' -e '/_NOTE$/d' -e '/_TESTED$/d' | tr 'A-Z_' 'a-z-'
}

# lua: excluded on purpose -- not a verb anyone is told about
_spark_complete() {
    local cur words
    cur=${COMP_WORDS[COMP_CWORD]}
    COMPREPLY=()
    if [ "$COMP_CWORD" -eq 1 ]; then
        words="chat do recall serve check update client setup
               ver last status history stats clear bench model
               soul memory bar look height off
               on user explain edit ask read drill watch reveal help uninstall
               awaken words voice"
        COMPREPLY=($(compgen -W "$words" -- "$cur"))
        return 0
    fi
    [ "$COMP_CWORD" -eq 2 ] || return 0
    case ${COMP_WORDS[1]} in
        model)   words="list verify budget rm add auto none status --chat $(_spark_model_names)" ;;
        bar)     words="line" ;;
        memory)  words="add forget clear on off" ;;
        reveal)  words="auto off" ;;
        look)    words="on off auto status" ;;
        voice)   words="clear on off rate test status" ;;
        height)  words="1 2 3 4 5" ;;
        check)   words="--watch --porcelain --report --fresh --fetch --selftest --chaos" ;;
        uninstall) words="--dry-run --yes --purge --packages --keep-packages" ;;
        serve)   words="on off boot share status --login --audit" ;;
        chat)    words="--thread" ;;
        do)      words="--sandbox --detach --porcelain --review --accept --discard" ;;
        soul)    words="show edit reset" ;;
        words)   words="edit" ;;
        bench)   words="--line" ;;
        clear)   words="--history" ;;
        client)  words="off status" ;;
        user)    words="list add remove login logout token claim status" ;;
        *)       return 0 ;;
    esac
    COMPREPLY=($(compgen -W "$words" -- "$cur"))
    return 0
}

complete -F _spark_complete spark
