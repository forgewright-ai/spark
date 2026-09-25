# shellcheck shell=sh
# shellcheck disable=SC2034   # the variables set here are read by the sourcing script
# spark lib/env.sh -- the KEY=value reader shared by bootstrap.sh and
# install.sh. POSIX sh. lib/spark/config.py is the same reader in python;
# the two must agree on what a valid line is (contract 3 in CLAUDE.md).
#
# load_env FILE      set every KEY the environment does not already set
# site_load          load ~/.config/spark/site.env, then apply defaults

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
    # hostname is not in every base (Arch's lacks inetutils): uname -n is POSIX
    [ -n "$_host" ] || _host=$(hostname -s 2>/dev/null || uname -n | cut -d. -f1)
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
    # spark.env first: with load_env's only-if-unset semantics the FIRST
    # file wins, and config.py lets spark.env override site.env (its
    # later dict update) -- the twins must agree on who wins
    load_env "$SPARK_CONFIG_DIR/spark.env" || return 1    # SPARK_SERVICE, SPARK_PORT, dirs
    load_env "$SPARK_CONFIG_DIR/site.env" || return 1
    : "${SITE_NAME:=$(short_host)}"
    : "${SITE_USER:=$(id -un)}"
    : "${SITE_SET_HOSTNAME:=no}"
    : "${SITE_THEME:=none}"
    : "${SITE_AI_MODEL:=auto}"
    : "${SITE_EMBER_MODEL:=none}"
    : "${SITE_AI_BUDGET:=60}"
    : "${SITE_AI_BUILD:=auto}"
    : "${SITE_FONT_FACE:=}"
    : "${SITE_FONT_SIZE:=}"
    : "${SITE_QUIET_LOGIN:=no}"
    : "${SITE_QUIET_BOOT:=no}"
    : "${SITE_QUIET_AUDIO:=no}"
    : "${SITE_QUIET_START:=no}"
    : "${SITE_HEADLESS:=no}"
    : "${SITE_SHARE:=no}"
    : "${SITE_PEER_AI_URL:=}"
    : "${SITE_PEER_SSH:=}"
    export SITE_NAME SITE_USER SITE_SET_HOSTNAME SITE_THEME \
           SITE_AI_MODEL SITE_EMBER_MODEL SITE_AI_BUDGET SITE_AI_BUILD \
           SITE_FONT_FACE SITE_FONT_SIZE SITE_QUIET_LOGIN SITE_QUIET_BOOT SITE_QUIET_START SITE_QUIET_AUDIO SITE_HEADLESS SITE_SHARE SITE_PEER_AI_URL SITE_PEER_SSH
}
