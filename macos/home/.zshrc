# spark ~/.zshrc -- zsh on macOS. Symlinked from the spark repository:
# edit it there, and `git status` shows the change.
[[ -o interactive ]] || return

# --- PATH first (Terminal.app opens login shells, so .zprofile ran; a plain
#     `zsh` did not) -------------------------------------------------------
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) PATH="$HOME/.local/bin:$PATH" ;; esac
export PATH
export EDITOR=micro VISUAL=micro

# --- history and completion ---------------------------------------------
HISTFILE=~/.zsh_history HISTSIZE=20000 SAVEHIST=50000
setopt hist_ignore_all_dups hist_ignore_space share_history
setopt auto_cd extended_glob
autoload -Uz compinit && compinit -d ~/.cache/zcompdump
zstyle ':completion:*' matcher-list 'm:{a-z}={A-Za-z}'
bindkey -e

# --- the daily tools ------------------------------------------------------
if command -v eza >/dev/null; then
    alias ls='eza --group-directories-first'
    alias ll='eza -la --group-directories-first --git'
    alias lt='eza --tree -L 2'
else
    alias ll='ls -la'
fi
alias g=git
alias ..='cd ..'
alias check='spark check'

# --- fzf, zoxide ----------------------------------------------------------
command -v fzf >/dev/null && source <(fzf --zsh)

# --- prompt: starship when SITE_PROMPT=starship rendered a config ---------
if [[ -r ~/.config/starship.toml ]] && command -v starship >/dev/null; then
    eval "$(starship init zsh)"
else
    PROMPT=$'\n%n@%m:%~%# '   # the blank row is where spark prints its hint
fi

# --- spark at the prompt: `? words` or `words?` + Enter; Esc a on any line
# After fzf, so its accept-line wrapper is the one spark wraps.
[[ -r ~/.config/spark/widget.zsh ]] && source ~/.config/spark/widget.zsh
[[ -r ~/.config/spark/completion.zsh ]] && source ~/.config/spark/completion.zsh

# zoxide last: its prompt hook has to be the final one, or it complains
command -v zoxide >/dev/null && eval "$(zoxide init zsh)"
