# spark hook.zsh -- the one line ~/.zshrc sources (bootstrap's rc row adds
# it at the end, after fzf). Symlinked from the spark repository.
#   ~/.local/bin first on PATH; the widget; and the blank row above a plain
#   prompt -- the widget draws its hint there (starship's add_newline draws
#   it when starship is active, so the prompt is left alone then).
[[ -o interactive ]] || return 0
[[ -n ${_SPARK_HOOK_LOADED:-} ]] && return 0
_SPARK_HOOK_LOADED=1
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) PATH="$HOME/.local/bin:$PATH" ;; esac
export PATH
[[ -r ~/.config/spark/widget.zsh ]] && source ~/.config/spark/widget.zsh
if [[ -z ${STARSHIP_SHELL:-} && $PROMPT != $'\n'* ]]; then PROMPT=$'\n'$PROMPT; fi
# the Linux VT palette (`spark theme` writes it) -- strictly TERM=linux, so
# an xterm-family terminal's scrollback is never garbled by the escapes
[ "$TERM" = linux ] && [ -r ~/.config/spark/console-colors ] && cat ~/.config/spark/console-colors
# quiet boot turns the VT cursor off globally; a human session turns it back on
[ "$TERM" = linux ] && printf '\033[?25h'
[[ -r "$HOME/.config/spark/completion.zsh" ]] && source "$HOME/.config/spark/completion.zsh"
