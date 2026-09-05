# spark completion.zsh -- TAB completes spark's verbs and their names.
# Self-contained and sourced by hook.zsh. Registered only when compinit is
# live -- with the shell layer off nothing here runs compinit, and this
# file degrades silently (functions defined, nothing bound). Offline
# always, no python: the dynamic names come from the repository
# `command -v spark` links into (readlink), themes by glob, models by sed
# over the four model lists; when any of that fails, the static words
# still complete, silently. Binds no key of its own.
# Not completed on purpose (plumbing, gone, or aliases of ver):
#   line talk version --version

_spark_repo() {
    # ~/.local/bin/spark is a symlink to <repo>/bin/spark; print <repo>
    local bin link
    bin=$(command -v spark 2>/dev/null) || return 1
    link=$(readlink "$bin" 2>/dev/null) || return 1
    case $link in /*) ;; *) link=${bin%/*}/$link ;; esac
    link=${link%/spark}
    print -r -- "${link%/bin}"
}

_spark_theme_names() {
    local repo f
    local -a files
    repo=$(_spark_repo) || return 0
    files=("$repo"/themes/*.env(N))
    for f in "${files[@]}"; do
        print -r -- "${${f:t}%.env}"
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

_spark() {
    local -a comp
    if (( CURRENT == 2 )); then
        comp=(chat do serve stop check update shell headless client setup
              ver last status brain history stats bench tune model ember
              forge soul remember forget memory quiet theme font bar off
              on user explain edit help)
    elif (( CURRENT == 3 )); then
        case ${words[2]} in
            quiet)   comp=(start login boot on off status) ;;
            theme)   comp=(list show none status ${(f)"$(_spark_theme_names)"}) ;;
            model)   comp=(list verify budget rm add auto none status ${(f)"$(_spark_model_names)"}) ;;
            ember)   comp=(list auto none status ${(f)"$(_spark_model_names)"}) ;;
            shell | bar | headless | forge | memory) comp=(on off status) ;;
            check)   comp=(--watch --porcelain --selftest --fresh --fetch) ;;
            serve)   comp=(--foreground --host --print-client) ;;
            chat)    comp=(--thread) ;;
            soul)    comp=(show edit reset) ;;
            history) comp=(clear) ;;
            tune)    comp=(show apply) ;;
            font)    comp=(list none status) ;;
            client)  comp=(off status) ;;
            user)    comp=(list add remove login logout token claim status) ;;
        esac
    fi
    (( ${#comp} )) && compadd -- "${comp[@]}"
    return 0
}

if (( $+functions[compdef] )); then
    compdef _spark spark
fi
