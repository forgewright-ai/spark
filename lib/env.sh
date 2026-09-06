# shellcheck shell=sh
# shellcheck disable=SC2034   # the variables set here are read by the sourcing script
# spark lib/env.sh -- the KEY=value reader shared by bootstrap.sh and
# install.sh. POSIX sh. lib/spark/config.py is the same reader in python;
# the two must agree on what a valid line is (contract 3 in CLAUDE.md).
#
# load_env FILE      set every KEY the environment does not already set
# site_load          load ~/.config/spark/site.env, then apply defaults
# theme_load REPO    export THEME_* for $SITE_THEME (a palette, or neutral)

SPARK_CONFIG_DIR=${XDG_CONFIG_HOME:-$HOME/.config}/spark
SPARK_STATE_DIR=${XDG_STATE_HOME:-$HOME/.local/state}/spark
SPARK_DATA_DIR=${XDG_DATA_HOME:-$HOME/.local/share}/spark

# This machine's own short name, the one safe to bake into a rendered file.
# On macOS `hostname` is whatever the network last told configd while
# `scutil --get HostName` is unset, so it moves from network to network;
# LocalHostName is the name the owner set and does not move. ComputerName is
# not it: that one carries spaces and punctuation. lib/spark/config.py
# _short_host() is the twin.
short_host() {
    _host=
    [ "$(uname -s)" != Darwin ] || _host=$(scutil --get LocalHostName 2>/dev/null || true)
    [ -n "$_host" ] || _host=$(hostname -s 2>/dev/null || hostname)
    printf '%s' "$_host"
}

# A valid line: blank, a comment, or KEY=value with no shell syntax in the
# value. Anything else refuses the whole file -- config is data, never code.
load_env() {
    [ -f "$1" ] || return 0
    bad=$(grep -nEv '^[[:space:]]*(#|$)|^[A-Z_0-9]+=[^;`$()|&<>]*$' "$1" || true)
    if [ -n "$bad" ]; then
        printf 'spark: %s: refused, these lines are not KEY=value:\n%s\n' "$1" "$bad" >&2
        return 1
    fi
    while IFS= read -r line || [ -n "$line" ]; do
        case $line in ''|'#'*|' '*|'	'*) continue ;; esac
        key=${line%%=*}
        val=${line#*=}
        # optional surrounding double quotes, and a leading ~
        case $val in \"*\") val=${val#\"}; val=${val%\"} ;; esac
        tilde='~'
        case $val in "$tilde"|"$tilde/"*) val=$HOME${val#"$tilde"} ;; esac
        [ -n "$val" ] || continue
        eval "cur=\${$key:-}"
        [ -n "$cur" ] || export "$key=$val"
    done < "$1"
}

site_load() {
    load_env "$SPARK_CONFIG_DIR/site.env" || return 1
    load_env "$SPARK_CONFIG_DIR/spark.env" || return 1    # SPARK_SERVICE, SPARK_PORT, dirs
    : "${SITE_NAME:=$(short_host)}"
    : "${SITE_USER:=$(id -un)}"
    : "${SITE_SET_HOSTNAME:=no}"
    : "${SITE_WORKSPACE:=$HOME/projects}"
    : "${SITE_THEME:=none}"
    : "${SITE_PROMPT:=starship}"
    : "${SITE_PROMPT_STYLE:=minimal}"
    : "${SITE_AI_MODEL:=auto}"
    : "${SITE_EMBER_MODEL:=none}"
    : "${SITE_AI_BUDGET:=60}"
    : "${SITE_AI_BUILD:=auto}"
    : "${SITE_FONT_FACE:=}"
    : "${SITE_FONT_SIZE:=}"
    : "${SITE_QUIET_LOGIN:=no}"
    : "${SITE_QUIET_BOOT:=no}"
    : "${SITE_QUIET_AUDIO:=no}"
    : "${SITE_HEADLESS:=no}"
    : "${SITE_SHELL:=off}"
    : "${SITE_PEER_AI_URL:=}"
    # placeholders from site.env.example count as unset
    [ "${SITE_GIT_NAME:-}" != "Your Name" ] || SITE_GIT_NAME=
    [ "${SITE_GIT_EMAIL:-}" != "you@example.com" ] || SITE_GIT_EMAIL=
    # unchosen is unchosen, whether the key is absent or still the example's
    # placeholder: spark guesses so git works, and bootstrap's identity row
    # names what it guessed -- the author line of every commit is at stake
    SPARK_GIT_GUESSED=
    [ -n "${SITE_GIT_NAME:-}" ] || SPARK_GIT_GUESSED=SITE_GIT_NAME
    [ -n "${SITE_GIT_EMAIL:-}" ] || SPARK_GIT_GUESSED="${SPARK_GIT_GUESSED:+$SPARK_GIT_GUESSED }SITE_GIT_EMAIL"
    : "${SITE_GIT_NAME:=$SITE_USER}"
    : "${SITE_GIT_EMAIL:=$(id -un)@$(short_host)}"
    export SPARK_GIT_GUESSED
    export SITE_NAME SITE_USER SITE_SET_HOSTNAME SITE_WORKSPACE SITE_THEME \
           SITE_PROMPT SITE_PROMPT_STYLE SITE_AI_MODEL SITE_EMBER_MODEL SITE_AI_BUDGET SITE_AI_BUILD \
           SITE_GIT_NAME SITE_GIT_EMAIL SITE_FONT_FACE SITE_FONT_SIZE SITE_QUIET_LOGIN SITE_QUIET_BOOT SITE_QUIET_AUDIO SITE_HEADLESS SITE_SHELL SITE_PEER_AI_URL
}

THEME_KEYS="THEME_BG THEME_FG THEME_ACCENT THEME_MUTED THEME_BTOP THEME_ANSI_0 THEME_ANSI_1 THEME_ANSI_2 THEME_ANSI_3 THEME_ANSI_4 THEME_ANSI_5 THEME_ANSI_6 THEME_ANSI_7 THEME_ANSI_8 THEME_ANSI_9 THEME_ANSI_10 THEME_ANSI_11 THEME_ANSI_12 THEME_ANSI_13 THEME_ANSI_14 THEME_ANSI_15"

theme_load() {
    if [ "$SITE_THEME" = none ]; then
        # names both tmux and starship understand: the terminal's own colours
        THEME_BG=default THEME_FG=default THEME_ACCENT=blue THEME_MUTED=white THEME_BTOP=Default
        THEME_ANSI_0=black THEME_ANSI_1=red THEME_ANSI_2=green THEME_ANSI_3=yellow
        THEME_ANSI_4=blue THEME_ANSI_5=magenta THEME_ANSI_6=cyan THEME_ANSI_7=white
        THEME_ANSI_8=black THEME_ANSI_9=red THEME_ANSI_10=green THEME_ANSI_11=yellow
        THEME_ANSI_12=blue THEME_ANSI_13=magenta THEME_ANSI_14=cyan THEME_ANSI_15=white
    else
        # yours first (~/.config/spark/themes), then the repository's:
        # config.theme_path is the python twin
        f="$SPARK_CONFIG_DIR/themes/$SITE_THEME.env"
        [ -f "$f" ] || f="$1/themes/$SITE_THEME.env"
        if [ ! -f "$f" ]; then
            printf 'spark: SITE_THEME=%s: no such palette (themes/*.env, ~/.config/spark/themes/*.env)\n' "$SITE_THEME" >&2
            return 1
        fi
        load_env "$f" || return 1
    fi
    for k in $THEME_KEYS; do
        eval "v=\${$k:-}"
        if [ -z "$v" ]; then printf 'spark: theme %s lacks %s\n' "$SITE_THEME" "$k" >&2; return 1; fi
        export "${k?}"
    done
    # THEME_LOGO is optional: the banner's row colours (spark ver), else its own
    [ -z "${THEME_LOGO:-}" ] || export THEME_LOGO
}
