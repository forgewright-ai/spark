# spark completion.zsh -- TAB completes spark's verbs and their names.
# Self-contained and sourced by hook.zsh. Registered only when compinit is
# live -- nothing here runs compinit, so without it this file degrades
# silently (functions defined, nothing bound). Offline
# always, no python: the dynamic names come from the repository
# `command -v spark` links into (readlink), themes by glob, models by sed
# over the four model lists; when any of that fails, the static words
# still complete, silently. Binds no key of its own.
# Not completed on purpose (plumbing, or aliases of ver):
#   line version --version

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
    # the repository's palettes and yours (~/.config/spark/themes)
    local repo f
    local -a files
    repo=$(_spark_repo) || return 0
    files=("$repo"/themes/*.env(N) "${XDG_CONFIG_HOME:-$HOME/.config}"/spark/themes/*.env(N))
    for f in "${files[@]}"; do
        print -r -- "${${f:t}%.env}"
    done | sort -u
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
_spark() {
    local -a comp
    if (( CURRENT == 2 )); then
        comp=(chat do recall serve check update headless share client setup
              ver last status brain history stats bench model ember
              forge soul memory quiet theme font bar off
              on user explain edit ask read drill watch reveal help uninstall)
    elif (( CURRENT == 3 )); then
        case ${words[2]} in
            quiet)   comp=(start login boot audio on off status) ;;
            theme)   comp=(list show none status ${(f)"$(_spark_theme_names)"}) ;;
            model)   comp=(list verify budget rm add auto none status ${(f)"$(_spark_model_names)"}) ;;
            ember)   comp=(list auto none status ${(f)"$(_spark_model_names)"}) ;;
            headless | share) comp=(on off status) ;;
            memory)  comp=(add forget clear on off) ;;
            forge) comp=(on off status audit token) ;;
            bar)     comp=(line) ;;
            check)   comp=(--watch --porcelain --report --fresh --fetch --selftest --chaos) ;;
            uninstall) comp=(--dry-run --yes --purge --packages --keep-packages) ;;
            serve)   comp=(on off status --foreground --host --print-client) ;;
            chat)    comp=(--thread) ;;
            do)      comp=(--sandbox --detach --porcelain --review --accept --discard) ;;
            soul)    comp=(show edit reset) ;;
            bench)   comp=(--line) ;;
            history) comp=(clear) ;;
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
