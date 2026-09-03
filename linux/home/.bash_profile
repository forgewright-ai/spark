# spark ~/.bash_profile -- login shells read this; everything lives in .bashrc
[ -r ~/.bashrc ] && . ~/.bashrc

# the greeting: once per interactive login on a terminal, never for scripts
if [[ $- == *i* ]] && [ -t 1 ] && [ -r ~/.config/spark/banner ]; then
    if command -v spark >/dev/null 2>&1; then spark ver                # blank row, logo, version, credits
    else printf '\n%b\n' "$(cat ~/.config/spark/banner)"; fi        # before bootstrap has linked spark
fi
