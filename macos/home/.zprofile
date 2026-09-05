# spark ~/.zprofile -- login shells on macOS: Homebrew, then ~/.local/bin first
if [ -x /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
elif [ -x /usr/local/bin/brew ]; then
    eval "$(/usr/local/bin/brew shellenv)"
fi
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) PATH="$HOME/.local/bin:$PATH" ;; esac
export PATH

# the greeting: once per interactive login on a terminal (every Terminal.app
# window is one), never for scripts; SITE_QUIET_START=yes in site.env
# silences it (spark quiet start on -- the file is read directly: no python
# on the login path, so the environment's SITE_QUIET_START is not honored here)
if [[ -o interactive ]] && [ -t 1 ] && [ -r ~/.config/spark/banner ]; then
    if command -v spark >/dev/null 2>&1; then                       # blank row, logo, version, credits
        grep -qx 'SITE_QUIET_START=yes' ~/.config/spark/site.env 2>/dev/null || spark ver
    else printf '\n%b\n' "$(cat ~/.config/spark/banner)"; fi        # before bootstrap has linked spark
fi
