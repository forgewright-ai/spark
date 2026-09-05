# spark ~/.bashrc -- bash 5 on Linux. Symlinked from the spark repository:
# edit it there, and `git status` shows the change.
[[ $- == *i* ]] || return

# --- PATH first: everything below may depend on ~/.local/bin ---------------
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) PATH="$HOME/.local/bin:$PATH" ;; esac
export PATH
export EDITOR=micro VISUAL=micro

# --- history ---------------------------------------------------------------
HISTSIZE=20000 HISTFILESIZE=50000 HISTCONTROL=ignoreboth:erasedups
shopt -s histappend checkwinsize globstar autocd
bind 'set completion-ignore-case on' 2>/dev/null

# --- the daily tools, by their Debian names where those differ -------------
command -v fdfind >/dev/null && alias fd=fdfind
command -v batcat >/dev/null && alias bat=batcat
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

# --- fzf, zoxide -----------------------------------------------------------
for f in /usr/share/doc/fzf/examples/key-bindings.bash /usr/share/fzf/key-bindings.bash; do
    [ -r "$f" ] && { . "$f"; break; }
done

# --- prompt: starship when SITE_PROMPT=starship rendered a config ----------
if [ -r ~/.config/starship.toml ] && command -v starship >/dev/null; then
    eval "$(starship init bash)"
else
    PS1='\n\u@\h:\w\$ '   # the blank row is where spark prints its hint
fi

# --- spark at the prompt: `? words` or `words?` + Enter; Esc a on any line -
# After fzf, so its Enter macro is the one that wins.
[ -r ~/.config/spark/widget.bash ] && . ~/.config/spark/widget.bash
[ -r ~/.config/spark/completion.bash ] && . ~/.config/spark/completion.bash

# zoxide last: its prompt hook has to be the final one, or it complains
command -v zoxide >/dev/null && eval "$(zoxide init bash)"
