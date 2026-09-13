#!/bin/sh
# spark bootstrap.sh -- a fresh Debian-family Linux or macOS to a spark
# workstation, idempotently. Run it again after any change to site.env. An
# apply run prints what it CHANGED and what needs you, and nothing else:
# a converged machine says only "Nothing to do".
#
#   ./bootstrap.sh                 apply (sudo only for apt/pacman and the headless rows)
#   ./bootstrap.sh --dry-run       print what would change; never sudo
#   ./bootstrap.sh --verbose       every row, not only what changed
#   ./bootstrap.sh --list-packages one package per line, as this site wants them
#   ./bootstrap.sh --list-tools    repo-path<TAB>name of every tool linked on PATH
#   ./bootstrap.sh --list-models   the model table with a RAM verdict per row
#   ./bootstrap.sh --fetch U D S   download U to D, verify sha256 S, or die
#                                  cleanly (the download primitive, alone)
#
# Rows (contract 1):  ok | would | skip | todo   <what>   <why>
#   ok     already true, or just applied        would   dry-run: would apply
#   skip   not applicable here, with the reason todo    needs you (edit site.env)
set -eu
REPO=$(cd "$(dirname "$0")" && pwd)
. "$REPO/lib/env.sh"
OS=$(uname -s)
ARCH=$(uname -m)
MODE=apply
VERBOSE=0
usage() { sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }
case ${1:-} in
    --dry-run) MODE=dry ;;
    --verbose|-v) VERBOSE=1 ;;
    --list-tools) printf 'bin/spark\tspark\nbin/explain\texplain\n'; exit 0 ;;
    --list-packages|--list-models) MODE=${1#--list-} ;;
    # the download primitive on its own, so a failed download can be
    # rehearsed (spark check --chaos) without a machine to bootstrap
    --fetch) [ $# -eq 4 ] || usage 2; MODE=fetch; FETCH_ARGS_URL=$2; FETCH_ARGS_DEST=$3; FETCH_ARGS_SHA=$4 ;;
    -h|--help) usage ;;
    '') ;;
    *) usage 2 ;;
esac

# ---------------------------------------------------------------- packages
# Linux: the names live in distro/<id>.env (PKG_CORE PKG_ENGINE PKG_AI,
# plus PM PM_INSTALL PM_TARGET), one file per package family, loaded
# after site_load once distro() has said which. macOS needs nothing
# installed. The verbs that ask a package manager are pkg_installed,
# pkg_available and pkg_install below -- the one place that switches on PM.

# ------------------------------------------------------------ pinned bits
# Everything not packaged is pinned by version and sha256. An empty sha
# means "not pinned yet": the block skips with a notice, never guesses.
site_load
# Every decision is python's: lib/spark/facts.py answers from the same
# code the verbs use (distro, the build, WSL, memory, the engine home
# and flavour off engine.env, the model picks), printed as KEY=value
# and eval'd here -- one home, no sh twin. This file orchestrates: rows,
# package installs, downloads, file placement. python3 >= 3.9 is a
# prerequisite of the public path (get refuses without it; spark setup
# is python itself), so asking python is not a new requirement.
facts=$(SPARK_OS=$OS SPARK_ARCH=$ARCH python3 "$REPO/lib/spark/facts.py") || {
    echo "bootstrap: lib/spark/facts.py failed -- python3 >= 3.9 is required" >&2; exit 1; }
eval "$facts"
ENGINE_DIR="$SPARK_DATA_DIR/engine/$ENGINE_PIN_NAME"
# thin adapters over the facts: the names the rows below already speak
is_wsl() { [ "$IS_WSL" = 1 ]; }
# model_pick spark|ember: that role's row (name file url bytes sha256
# ram_gb), or nothing -- engine.chosen_rows decided it
model_pick() {
    if [ "${1:-spark}" = ember ]; then _row=$EMBER_PICK; else _row=$SPARK_PICK; fi
    [ -z "$_row" ] || printf '%s\n' "$_row"
}
# every model row (the list, then yours), trailing mark: - the list, u yours
model_rows_all() { [ -z "$MODEL_ROWS" ] || printf '%s\n' "$MODEL_ROWS"; }
# the package family and its names: brew on macOS; on Linux the distro's
# file (load_env sets only what the environment lacks, so a test may pin
# a group); an unknown Linux keeps PM empty and the packages row says so
PM=
[ -z "$DISTRO" ] || load_env "$REPO/distro/$DISTRO.env" || exit 1
: "${PM_INSTALL:=}" "${PM_TARGET:=}" "${PKG_CORE:=}" "${PKG_ENGINE:=}" "${PKG_AI:=}"
MODELS_DIR=${SPARK_MODELS_DIR:-$SPARK_DATA_DIR/models}
# one layer: the AI. The shell -- tmux, starship, the daily tools, the
# font, the rc files -- is spark-shell's, its own repository; an editor
# is an app's plugin (spark-micro). spark ships neither.
# a client: no model of its own and a peer answering (SITE_AI_MODEL=none +
# SITE_PEER_AI_URL; spark client URL). No engine and no units here -- the
# widget, the hook and the tokens are all a client needs
client=0; [ "$SITE_AI_MODEL" = none ] && [ -n "$SITE_PEER_AI_URL" ] && client=1
CLIENT_OF="a client of $SITE_PEER_AI_URL (spark client off serves here again)"

# ------------------------------------------------------------- the lists
list_packages() {
    [ "$OS" != Darwin ] || return 0     # the mac core needs nothing installed
    [ -n "$DISTRO" ] || return 0        # an unknown family: no list (the packages row says so)
    set -- $PKG_CORE $PKG_ENGINE
    [ "$AI_BUILD" = vulkan ] && set -- "$@" $PKG_AI
    printf '%s\n' "$@"
}

list_models() {
    if [ "$client" = 1 ]; then
        # a client: never this machine's RAM as a budget; the rows alone
        # (spark model asks the peer's FORGE for its table)
        printf 'this machine is %s\n' "$CLIENT_OF"
        echo "nothing is served here; what fits is the peer's business (spark model there)"
        model_rows_all | while read -r name file _url _bytes _sha ram src; do
            [ "$src" = - ] && src=' '
            printf ' %s %-20s %6s GB  %s\n' "$src" "$name" "$ram" "$file"
        done
        echo "u = yours"
        return
    fi
    total=$MEM_GB; budget=$(( total * ${SITE_AI_BUDGET:-60} / 100 ))
    spick=$(model_pick spark | awk '{ print $1 }')
    epick=$(model_pick ember | awk '{ print $1 }')
    printf 'this machine: %s GB for models (RAM + GPU), budget %s GB (%s%%), %s\n' "$total" "$budget" "${SITE_AI_BUDGET:-60}" "$AI_BUILD"
    printf 'SITE_AI_MODEL=%s, SITE_EMBER_MODEL=%s\n' "$SITE_AI_MODEL" "$SITE_EMBER_MODEL"
    [ -z "$CAP_NOTE" ] || printf '%s\n' "$CAP_NOTE"
    model_rows_all | while read -r name file _url _bytes _sha ram src; do
        if [ "$ram" -le "$budget" ]; then v=fits; else v="needs $ram GB"; fi
        mark=' '; [ "$name" = "$spick" ] && mark='*'; [ "$name" = "$epick" ] && mark='+'
        [ "$src" = - ] && src=' '
        printf '%s%s %-20s %6s GB  %s  %s\n' "$mark" "$src" "$name" "$ram" "$v" "$file"
    done
    printf 'spark: %s\n' "${spick:-none}"
    printf 'ember: %s\n' "${epick:-none}"
    if [ -n "$spick" ]; then
        echo "* = spark (the prompt line), + = ember (conversations)"
    else
        echo "no model chosen (none, or nothing fits)"
    fi
    echo "u = yours; auto picks among the rows tested on the line (Apache-2.0, MIT)"
}

case $MODE in
    packages) list_packages; exit 0 ;;
    models) list_models; exit 0 ;;
esac

# ------------------------------------------------------------------ rows
todo=0
acting=0        # the row about to print is a change, not a state already true
row() { printf '%-6s %-12s %s\n' "$1" "$2" "${3:-}"; }
# An apply run says what it CHANGED. A machine already converged has
# nothing to say, so it says nothing; --verbose (and --dry-run, which is
# the report `spark check` and install_test.sh read) print every row.
loud() { [ "$MODE" = dry ] || [ "$VERBOSE" = 1 ]; }
ok() {
    if loud || [ "$acting" = 1 ]; then row ok "$1" "${2:-}"; fi
    acting=0
}
skip() { if loud; then row skip "$1" "${2:-}"; fi; acting=0; }
need() {   # need WHAT WHY -- something must change; in apply mode the caller does it
    todo=$((todo + 1))
    if [ "$MODE" = dry ]; then row would "$1" "${2:-}"; return 1; fi
    acting=1
    return 0
}
as_root() {
    if [ "$(id -u)" -eq 0 ]; then "$@"; else sudo "$@"; fi
}
sudo_upfront() {
    # Ask once, here, before anything is touched. A run that stops at the
    # first root step has already changed things and springs a password
    # prompt on someone who thought the install was under way.
    #
    # Only where a prompt can be answered: at a terminal. Piped or over
    # ssh there is nobody to type, and demanding sudo there would break
    # every run that needed no root at all -- `spark update` on a
    # converged machine is exactly that.
    [ "$MODE" = apply ] || return 0
    [ "$(id -u)" -ne 0 ] || return 0
    [ "$client" = 1 ] && return 0               # a client of a shared engine needs no root
    if ! command -v sudo >/dev/null 2>&1; then
        echo "bootstrap: no sudo here, and packages, the console and the units need root." >&2
        echo "bootstrap: run it as root, or install sudo first. Nothing was changed." >&2
        exit 1
    fi
    sudo -n true 2>/dev/null && return 0        # passwordless, or already cached
    [ -t 0 ] || return 0                        # nobody to ask: let the root step speak
    printf 'spark needs sudo once, now: packages, the console, the units.\n'
    if ! sudo -v; then
        echo "bootstrap: sudo refused. Nothing was changed." >&2
        exit 1
    fi
}
section() { if loud; then printf '\n== %s\n' "$1"; fi; }
sha_ok() {   # sha_ok FILE SHA
    if [ "$OS" = Darwin ]; then shasum -a 256 "$1" | awk '{print $1}' | grep -qx "$2"
    else sha256sum "$1" | awk '{print $1}' | grep -qx "$2"; fi
}
fetch() {   # fetch URL DEST SHA  -- download, verify, or die
    # at a terminal: name the file and let curl draw its progress bar
    # (a model is gigabytes -- minutes, not seconds); captured output
    # (spark model/ember filtering, CI) stays quiet as before.
    # PARTIAL is what the EXIT trap removes: a download that dies -- a
    # full disk, a cut LAN, a Ctrl-C, a bad sha -- leaves nothing behind,
    # least of all on the disk that was already full.
    PARTIAL=$2
    if [ -t 2 ]; then
        printf '       downloading %s\n' "${1##*/}"
        curl -fL --retry 3 --progress-bar -o "$2" "$1" || fetch_died "$1"
    else
        curl -fsSL --retry 3 -o "$2" "$1" || fetch_died "$1"
    fi
    sha_ok "$2" "$3" || { echo "bootstrap: sha256 mismatch for $1" >&2; exit 1; }
    PARTIAL=
}
fetch_died() {
    echo "bootstrap: could not download $1 (nothing left behind)" >&2
    exit 1
}
login_shell() {   # the login shell, as a path: $SHELL, else the passwd entry
    s=${SHELL:-}
    if [ -z "$s" ]; then
        if [ "$OS" = Darwin ]; then s=$(dscl . -read "/Users/$(id -un)" UserShell 2>/dev/null | awk '{ print $2 }')
        else s=$(getent passwd "$(id -un)" 2>/dev/null | cut -d: -f7); fi
    fi
    printf '%s\n' "${s:-sh}"
}

TMP=$(mktemp -d)
PARTIAL=
trap 'rm -rf "$TMP"; [ -z "$PARTIAL" ] || rm -f "$PARTIAL"' EXIT
if [ "$MODE" = fetch ]; then
    fetch "$FETCH_ARGS_URL" "$FETCH_ARGS_DEST" "$FETCH_ARGS_SHA"
    exit 0
fi
sudo_upfront
if loud; then printf 'spark bootstrap | %s %s | %s\n' "$OS" "$ARCH" "$MODE"; fi

# =============================================================== 1. site
section site
if [ ! -f "$SPARK_CONFIG_DIR/site.env" ]; then
    if need site "create $SPARK_CONFIG_DIR/site.env from site.env.example"; then
        mkdir -p "$SPARK_CONFIG_DIR"
        cp "$REPO/site.env.example" "$SPARK_CONFIG_DIR/site.env"
        chmod 0600 "$SPARK_CONFIG_DIR/site.env"
        ok site "created; edit it and run again"
    fi
else
    # yours to edit, but never world-readable: it names you and your peers
    [ "$MODE" = dry ] || chmod 0600 "$SPARK_CONFIG_DIR/site.env" "$SPARK_CONFIG_DIR/spark.env" 2>/dev/null || true
    ok site "$SPARK_CONFIG_DIR/site.env"
fi
# spark.env: optional, every key a default -- but a documented file beats an empty one
if [ ! -f "$SPARK_CONFIG_DIR/spark.env" ]; then
    if need spark.env "create $SPARK_CONFIG_DIR/spark.env from spark.env.example (all defaults)"; then
        cp "$REPO/home/.config/spark/spark.env.example" "$SPARK_CONFIG_DIR/spark.env"
        chmod 0600 "$SPARK_CONFIG_DIR/spark.env"
        ok spark.env "created"
    fi
fi
ok name "$SITE_NAME  (user $SITE_USER)"
pick=$(model_pick spark | awk '{ print $1 " (" $6 " GB)" }')
case $SITE_AI_MODEL in
    none) ok model "none: no download; bring your own .gguf or set SITE_AI_MODEL" ;;
    *) [ -n "$pick" ] && ok model "$SITE_AI_MODEL -> $pick" || row todo model "SITE_AI_MODEL=$SITE_AI_MODEL: nothing fits $MEM_GB GB / not in models.env or yours" ;;
esac
epick=$(model_pick ember | awk '{ print $1 " (" $6 " GB)" }')
if [ -z "$pick" ] && [ "$SITE_EMBER_MODEL" != none ]; then ok ember "no spark model here: nothing is served, no ember"
else case $SITE_EMBER_MODEL in
    none) ok ember "none: the spark model answers everything" ;;
    auto) [ -n "$epick" ] && ok ember "auto -> $epick" || ok ember "auto: nothing fits beside the spark model" ;;
    *) [ -n "$epick" ] && ok ember "$SITE_EMBER_MODEL -> $epick" || row todo ember "SITE_EMBER_MODEL=$SITE_EMBER_MODEL: not in models.env, or it is the spark model (--list-models)" ;;
esac; fi

# ============================================================ 2. identity
section identity
if [ "$client" = 1 ] && [ "$SITE_SET_HOSTNAME" = yes ]; then
    skip hostname "a client: the name is left as it is (the machine that serves owns its own)"
elif [ "$SITE_SET_HOSTNAME" = yes ]; then
    if [ "$(hostname -s 2>/dev/null || hostname)" = "$SITE_NAME" ]; then
        ok hostname "$SITE_NAME"
    elif need hostname "set to $SITE_NAME (sudo)"; then
        if [ "$OS" = Darwin ]; then
            for k in LocalHostName ComputerName HostName; do as_root scutil --set $k "$SITE_NAME"; done
        else
            as_root hostnamectl set-hostname "$SITE_NAME"
        fi
        ok hostname "$SITE_NAME"
    fi
else
    skip hostname "SITE_SET_HOSTNAME=no (display name only: $SITE_NAME)"
fi

# ============================================================ 3. packages
# the three questions a package manager is asked, switched once on PM
# (lib/spark packages.py is the python twin: the packages check row and
# spark uninstall ask the same way). A new family is one arm in each.
pkg_installed() {
    case $PM in
        apt) dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q 'install ok installed' ;;
        pacman) pacman -Qq "$1" >/dev/null 2>&1 ;;
        *) return 1 ;;
    esac
}
pkg_available() {
    case $PM in
        apt) apt-cache policy "$1" 2>/dev/null | grep -q 'Candidate: [^(]' ;;
        pacman) pacman -Sp "$1" >/dev/null 2>&1 ;;
        *) return 1 ;;
    esac
}
pkg_install() {   # pkg_install NAME... -- as root, the manager's own way
    case $PM in
        apt) as_root apt-get update -qq && as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$@" ;;
        pacman) as_root pacman -S --needed --noconfirm "$@" ;;      # never -Sy alone: a rolling distro forbids the partial upgrade
        *) return 1 ;;
    esac
}
section packages
if [ "$client" = 1 ]; then
    skip packages "a client: nothing to install here (python3 and curl already run this)"
elif [ "$OS" = Darwin ]; then
    ok packages "nothing required"
elif [ -z "$PM" ]; then
    row todo packages "no package list for this Linux ($(sed -n 's/^PRETTY_NAME=//p' "${SPARK_OS_RELEASE:-/etc/os-release}" 2>/dev/null | tr -d '"')): distro/*.env know debian and arch -- install git curl python3 and libgomp by hand"
else
    missing=''; absent=''
    for p in $(list_packages); do
        if pkg_installed "$p"; then continue; fi
        if pkg_available "$p"; then missing="$missing $p"; else absent="$absent $p"; fi
    done
    [ -z "$absent" ] || skip packages "not in this $PM:$absent (spark targets $PM_TARGET)"
    if [ -z "$missing" ]; then
        ok packages "$(list_packages | wc -l | tr -d ' ') packages installed"
    elif need packages "install:$missing (sudo)"; then
        # shellcheck disable=SC2086
        if pkg_install $missing > "$TMP/pkg.log" 2>&1; then
            ok packages "installed:$missing"
        elif [ "$PM" = pacman ]; then
            # the sync database is stale, most often: the fix is the full
            # upgrade, the user's to run (spark never -Sy's alone)
            row todo packages "pacman could not install:$missing -- sudo pacman -Syu (a rolling distro: spark never refreshes the database without upgrading), then run again"
        else
            tail -20 "$TMP/pkg.log"; echo "bootstrap: $PM install failed" >&2; exit 1
        fi
    fi
fi

# ============================================================== 4. pinned
section pinned
# llama.cpp engine: the pinned release tarball on both OSes (the AI layer,
# always). A build of your own in SPARK_ENGINE_DIR wins; the tarball is
# never fetched over it. The extracted dir carries a one-line `flavour`
# file so `spark check`'s engine row can name it.
have=$(cat "$ENGINE_DIR/flavour" 2>/dev/null || true)
if [ -z "$have" ] && [ -x "$ENGINE_DIR/llama-server" ] && [ -n "$ENGINE_FLAVOUR" ]; then
    # a dir from before the flavour file existed: name it now by what is in
    # it -- the Linux vulkan build ships libggml-vulkan.so (dry-run too: a
    # one-line note beside a binary that is already there is not a change)
    have=$ENGINE_FLAVOUR
    if [ "$OS" = Linux ]; then
        if ls "$ENGINE_DIR"/libggml-vulkan.so* >/dev/null 2>&1; then have="ubuntu-vulkan-${ENGINE_FLAVOUR##*-}"; else have="ubuntu-${ENGINE_FLAVOUR##*-}"; fi
    fi
    echo "$have" > "$ENGINE_DIR/flavour"
fi
if [ "$client" = 1 ]; then
    skip engine "$CLIENT_OF"
elif [ -n "${SPARK_ENGINE_DIR:-}" ] && [ -x "$SPARK_ENGINE_DIR/llama-server" ]; then
    ok engine "your build in $SPARK_ENGINE_DIR (SPARK_ENGINE_DIR)"
elif [ -x "$ENGINE_DIR/llama-server" ] && { [ -z "$ENGINE_SHA" ] || [ "$have" = "$ENGINE_FLAVOUR" ]; }; then
    ok engine "llama.cpp $LLAMA_VERSION $have"
elif [ -z "$ENGINE_SHA" ]; then
    # no pin for this OS/arch/build: a llama-server this machine already
    # has (facts: ENGINE_HOME probed PATH and the system dirs) is used
    # rather than refused; where a pin exists it is still installed and
    # still wins, so an existing build is never a silent unpin
    if [ -x "$ENGINE_HOME/llama-server" ]; then
        ok engine "your llama-server ($ENGINE_HOME)"
    else
        skip engine "no pin for llama.cpp $LLAMA_VERSION $OS/$ARCH ($AI_BUILD) -- set SPARK_ENGINE_DIR to a build of your own"
    fi
elif need engine "install llama.cpp $LLAMA_VERSION $ENGINE_FLAVOUR$([ -z "$have" ] || echo " (replaces $have: the build here is $AI_BUILD now)")"; then
    fetch "https://github.com/ggml-org/llama.cpp/releases/download/$LLAMA_VERSION/llama-$LLAMA_VERSION-bin-$ENGINE_FLAVOUR.tar.gz" "$TMP/llama.tgz" "$ENGINE_SHA"
    rm -rf "$ENGINE_DIR"
    mkdir -p "$ENGINE_DIR"
    tar -xzf "$TMP/llama.tgz" -C "$ENGINE_DIR" --strip-components=1
    echo "$ENGINE_FLAVOUR" > "$ENGINE_DIR/flavour"
    # macOS Gatekeeper: a curl download carries no quarantine flag, but if
    # one is there the unsigned binaries would be refused; clear it, no sudo
    if [ "$OS" = Darwin ]; then xattr -dr com.apple.quarantine "$ENGINE_DIR" 2>/dev/null || true; fi
    ok engine "llama.cpp $LLAMA_VERSION $ENGINE_FLAVOUR"
fi
# the models, one per role (both OSes): each pick's six fields become $1..$6
for role in spark ember; do
    if [ "$role" = spark ]; then rname=model; choice=$SITE_AI_MODEL; else rname=ember; choice=$SITE_EMBER_MODEL; fi
    # shellcheck disable=SC2046
    set -- $(model_pick "$role")
    if [ "$choice" = none ]; then
        [ "$role" = spark ] && skip model "SITE_AI_MODEL=none" || skip ember "SITE_EMBER_MODEL=none"
    elif [ "$role" = ember ] && [ -z "$(model_pick spark)" ]; then
        skip ember "no spark model here: nothing is served, no ember"
    elif [ $# -lt 6 ]; then
        skip "$rname" "nothing chosen"
    elif [ -f "$MODELS_DIR/$2" ]; then
        ok "$rname" "$1: $2"
    elif need "$rname" "download $1 ($6 GB RAM, $(( $4 / 1048576 )) MB): $2"; then
        mkdir -p "$MODELS_DIR"
        fetch "$3" "$MODELS_DIR/$2.part" "$5"
        mv "$MODELS_DIR/$2.part" "$MODELS_DIR/$2"
        ok "$rname" "$1: $2"
    fi
done

# =============================================================== 5. token
section token
tok=${SPARK_API_KEY_FILE:-$SPARK_STATE_DIR/api-token}
if [ -s "$tok" ]; then
    ok token "$tok"
elif need token "create $tok (0600; the value is never printed)"; then
    mkdir -p "$(dirname "$tok")"; chmod 0700 "$SPARK_STATE_DIR" 2>/dev/null || true
    umask 077
    python3 -c 'import secrets; print(secrets.token_urlsafe(32))' > "$tok"
    umask 022
    ok token "created"
fi

# ================================================================ 6. dirs
section dirs
# a new user's machine gets no folder it did not ask for: the models,
# the bin and the state dirs are spark's own (a projects folder is
# spark-shell's business)
for d in "$MODELS_DIR" "$HOME/.local/bin" "$SPARK_STATE_DIR"; do
    if [ -d "$d" ]; then ok dir "$d"
    elif need dir "mkdir $d"; then mkdir -p "$d"; ok dir "$d"; fi
done
[ ! -d "$SPARK_STATE_DIR" ] || chmod 0700 "$SPARK_STATE_DIR"

# ============================================================= 7. configs
section configs
if [ "$MODE" = dry ]; then out=$(sh "$REPO/install.sh" --dry-run); else out=$(sh "$REPO/install.sh"); fi
printf '%s\n' "$out" | grep -v '^ok ' | grep -vE '^(Nothing to do|[0-9]+ to do)$' | sed 's/^/       /' || true
n=$(printf '%s\n' "$out" | grep -c '^would' || true)
todo=$((todo + n))
ok configs "$(printf '%s\n' "$out" | tail -1)"
# micro's plugin left this repository in v1.10 (github.com/forgewright-ai/
# spark-micro): the links an older install.sh made under ~/.config/micro
# now dangle into this tree. Hand them back once (bindings.json from its
# .bak, or gone); a machine without them has nothing to do here.
mplug="$HOME/.config/micro/plug/spark"
old_plug=0
if [ -L "$mplug/spark.lua" ]; then case $(readlink "$mplug/spark.lua") in "$REPO"/*) old_plug=1 ;; esac; fi
if [ "$old_plug" = 1 ] && need micro "the plugin moved to github.com/forgewright-ai/spark-micro: remove spark's links"; then
    for f in "$mplug/spark.lua" "$mplug/repo.json" "$mplug/help/spark.md"; do
        [ ! -L "$f" ] || rm -f "$f"
    done
    rmdir "$mplug/help" "$mplug" 2>/dev/null || true
    mb="$HOME/.config/micro/bindings.json"
    if [ -L "$mb" ]; then rm -f "$mb"; [ ! -f "$mb.bak" ] || mv "$mb.bak" "$mb"; fi
    ok micro "spark's links removed -- git clone https://github.com/forgewright-ai/spark-micro $mplug"
fi
# the shell layer left this repository (github.com/forgewright-ai/
# spark-shell): rc files an older install.sh symlinked into this tree
# now dangle. Hand them back once (.bak back, or gone); spark-shell
# adopts the rendered look (tmux, starship, btop) in place.
moved=0
for f in .bashrc .bash_profile .zshrc .zprofile; do
    [ -L "$HOME/$f" ] || continue
    case $(readlink "$HOME/$f") in "$REPO"/*) moved=1 ;; esac
done
if [ "$moved" = 1 ] && need shell-moved "the shell layer moved to github.com/forgewright-ai/spark-shell: hand the rc files back"; then
    for f in .bashrc .bash_profile .zshrc .zprofile; do
        [ -L "$HOME/$f" ] || continue
        case $(readlink "$HOME/$f") in
            "$REPO"/*) rm -f "$HOME/$f"; [ ! -e "$HOME/$f.bak" ] || mv "$HOME/$f.bak" "$HOME/$f" ;;
        esac
    done
    ok shell-moved "rc files handed back -- git clone https://github.com/forgewright-ai/spark-shell ~/.spark-shell"
fi
# the core rc hook: one marked line at the end of the login shell's rc file
# (after fzf: the widget wraps Enter, so it loads last). The marker is
# `config/spark/hook.`, so the line lands once. An rc file that is spark's
# own symlink (SITE_SHELL=on) already sources the widget.
rc_bin=$(login_shell); rc_shell=${rc_bin##*/}; rc_major=
case $rc_shell in
    bash) rc="$HOME/.bashrc"; rc_line='[ -r ~/.config/spark/hook.bash ] && . ~/.config/spark/hook.bash   # spark: the AI at the prompt'
          rc_major=$("$(command -v "$rc_bin" || echo bash)" -c 'echo "${BASH_VERSINFO[0]}"' 2>/dev/null || true) ;;
    zsh)  rc="$HOME/.zshrc";  rc_line='[[ -r ~/.config/spark/hook.zsh ]] && source ~/.config/spark/hook.zsh   # spark: the AI at the prompt' ;;
    *)    rc=; rc_line= ;;
esac
rc_link=0; [ -n "$rc" ] && [ -L "$rc" ] && case $(readlink "$rc") in "$REPO"/*) rc_link=1 ;; esac
if [ -z "$rc" ]; then
    row todo rc "shell $rc_shell: no widget for it -- bash 4+ or zsh hosts one (chsh -s /bin/zsh)"
elif [ "$rc_shell" = bash ] && [ "${rc_major:-0}" -lt 4 ]; then
    row todo rc "bash ${rc_major:-3} cannot host the widget -- zsh can (chsh -s /bin/zsh)"
elif [ "$rc_link" = 1 ]; then
    ok rc "~${rc#"$HOME"} is a symlink into this repo (shell-moved hands it back)"
elif grep -qF 'config/spark/hook.' "$rc" 2>/dev/null; then
    ok rc "~${rc#"$HOME"} sources the hook"
elif need rc "add one line to ~${rc#"$HOME"}"; then
    printf '\n%s\n' "$rc_line" >> "$rc"      # appended, never truncated; created if absent
    ok rc "~${rc#"$HOME"} sources the hook"
fi

# a ~/.bash_profile that never reaches ~/.bashrc shadows the hook on a
# console login (bash reads only it, and stops); give it the same marked
# line so spark survives every login shape. zsh has no shadow: a login
# zsh reads .zprofile and .zshrc both.
rc_prof="$HOME/.bash_profile"
if [ "$rc_shell" = bash ] && [ "${rc_major:-0}" -ge 4 ] && [ -f "$rc_prof" ] && [ ! -L "$rc_prof" ] \
   && ! grep -qF 'config/spark/hook.' "$rc_prof" 2>/dev/null \
   && ! grep -qE '\.bashrc|\.profile' "$rc_prof" 2>/dev/null; then
    if need rc-login "add one line to ~${rc_prof#"$HOME"} (it shadows ~/.profile)"; then
        printf '\n%s\n' "$rc_line" >> "$rc_prof"
        ok rc-login "~${rc_prof#"$HOME"} sources the hook (it shadowed ~/.profile)"
    fi
fi

# =============================================================== 8. tools
section tools
"$0" --list-tools | while IFS='	' read -r rel name; do
    link="$HOME/.local/bin/$name"
    if [ -L "$link" ] && [ "$(readlink "$link")" = "$REPO/$rel" ]; then ok "$name" "$link"
    elif need "$name" "link $link -> $REPO/$rel"; then ln -sfn "$REPO/$rel" "$link"; ok "$name" "$link"; fi
done
found=$(command -v spark 2>/dev/null || true)
[ -z "$found" ] || [ "$found" = "$HOME/.local/bin/spark" ] || skip PATH "another spark shadows ~/.local/bin/spark: $found (put ~/.local/bin first)"

# =============================================================== 9. hooks
section hooks
if [ "$(git -C "$REPO" config core.hooksPath 2>/dev/null)" = .githooks ]; then
    ok hooks ".githooks"
elif need hooks "git config core.hooksPath .githooks"; then
    git -C "$REPO" config core.hooksPath .githooks; ok hooks ".githooks"
fi

# ============================================================ 10. services
section services
have_model=0; ls "$MODELS_DIR"/*.gguf >/dev/null 2>&1 && have_model=1
engine_bin=$ENGINE_HOME
serve_ready=0
[ -x "$engine_bin/llama-server" ] && [ "$have_model" = 1 ] && [ -s "$tok" ] && [ "${SPARK_SERVICE:-auto}" = auto ] && serve_ready=1
serve_why="engine $([ -x "$engine_bin/llama-server" ] && echo yes || echo no), model $([ "$have_model" = 1 ] && echo yes || echo no), token $([ -s "$tok" ] && echo yes || echo no), SPARK_SERVICE=${SPARK_SERVICE:-auto}"
# the FORGE (the served agent): on, or auto = wherever the model server is
forge_ready=0
case ${SPARK_FORGE:-auto} in on) forge_ready=1 ;; auto) forge_ready=$serve_ready ;; esac
forge_why="SPARK_FORGE=${SPARK_FORGE:-auto}, server $([ "$serve_ready" = 1 ] && echo yes || echo no)"
# a box that is the brain: the units run from boot with nobody logged in
# and the box never sleeps (SITE_HEADLESS=yes; `spark headless on`)
headless=0; [ "$SITE_HEADLESS" = yes ] && headless=1
if [ "$client" = 1 ]; then
    skip services "$CLIENT_OF"
elif [ "$OS" = Darwin ]; then
    dom="gui/$(id -u)"; agents="$HOME/Library/LaunchAgents"; src="$SPARK_CONFIG_DIR/launchd"
    daemons=/Library/LaunchDaemons; me=$(id -un)
    agent() {   # agent LABEL WANTED(0|1) [WHY]
        plist="$agents/$1.plist"; why=${3:-$serve_why}
        loaded=0; launchctl print "$dom/$1" >/dev/null 2>&1 && loaded=1
        if [ "$2" = 1 ]; then
            if [ -f "$src/$1.plist" ] && cmp -s "$src/$1.plist" "$plist" && [ "$loaded" = 1 ]; then ok "$1" "loaded"
            elif [ ! -f "$src/$1.plist" ]; then skip "$1" "not rendered yet (install.sh runs first)"
            elif need "$1" "install and load"; then
                mkdir -p "$agents"
                [ "$loaded" = 0 ] || launchctl bootout "$dom/$1" 2>/dev/null || true
                cp "$src/$1.plist" "$plist"
                launchctl bootstrap "$dom" "$plist" 2>/dev/null || launchctl kickstart -k "$dom/$1" 2>/dev/null || true
                ok "$1" "loaded"
            fi
        else
            if [ "$loaded" = 0 ] && [ ! -f "$plist" ]; then skip "$1" "not installed ($why)"
            elif need "$1" "unload and remove ($why)"; then
                launchctl bootout "$dom/$1" 2>/dev/null || true; rm -f "$plist"; ok "$1" "removed"
            fi
        fi
    }
    # a LaunchDaemon: the same rendered plist plus a UserName key, in root's
    # system/ domain, so it runs as $me from boot with nobody logged in and
    # leaves FileVault's login screen alone. Never beside a login agent.
    daemon() {   # daemon LABEL WANTED(0|1) [WHY]
        dplist="$daemons/$1.plist"; why=${3:-$serve_why}
        dloaded=0; launchctl print "system/$1" >/dev/null 2>&1 && dloaded=1
        gone=1; { launchctl print "$dom/$1" >/dev/null 2>&1 || [ -f "$agents/$1.plist" ]; } && gone=0
        if [ "$2" = 1 ]; then
            if [ ! -f "$src/$1.plist" ]; then skip daemons "$1 not rendered yet (install.sh runs first)"; return 0; fi
            cp "$src/$1.plist" "$TMP/$1.plist"
            plutil -insert UserName -string "$me" "$TMP/$1.plist"
            if [ "$dloaded" = 1 ] && [ "$gone" = 1 ] && cmp -s "$TMP/$1.plist" "$dplist"; then ok daemons "$1 loaded in system/ (runs as $me from boot)"
            elif need daemons "install $1 as a LaunchDaemon in system/, boot out its login agent (sudo)"; then
                launchctl bootout "$dom/$1" 2>/dev/null || true; rm -f "$agents/$1.plist"
                [ "$dloaded" = 0 ] || as_root launchctl bootout "system/$1" 2>/dev/null || true
                as_root install -o root -g wheel -m 0644 "$TMP/$1.plist" "$dplist"
                as_root launchctl bootstrap system "$dplist"
                ok daemons "$1 loaded in system/ (runs as $me from boot)"
            fi
        elif [ "$dloaded" = 0 ] && [ ! -f "$dplist" ] && [ "$gone" = 1 ]; then skip daemons "$1 not installed ($why)"
        elif need daemons "boot out and remove $1 ($why) (sudo)"; then
            launchctl bootout "$dom/$1" 2>/dev/null || true; rm -f "$agents/$1.plist"
            [ "$dloaded" = 0 ] || as_root launchctl bootout "system/$1" 2>/dev/null || true
            as_root rm -f "$dplist"; ok daemons "$1 removed"
        fi
    }
    unit() {   # unit LABEL WANTED [WHY] -- a daemon when headless, else a login agent; never both
        if [ "$headless" = 1 ]; then daemon "$@"; return 0; fi
        if launchctl print "system/$1" >/dev/null 2>&1 || [ -f "$daemons/$1.plist" ]; then
            if need daemons "boot out and remove the $1 daemon: a login agent again (SITE_HEADLESS=no) (sudo)"; then
                as_root launchctl bootout "system/$1" 2>/dev/null || true; as_root rm -f "$daemons/$1.plist"; ok daemons "$1 removed"
            fi
        fi
        agent "$@"
    }
    # a login agent lives in the gui domain of a logged-in session; over
    # ssh with nobody at the console, or on a CI runner, there is none and
    # the rows skip -- the systemd block's guard, in launchd's terms (a
    # daemon of SITE_HEADLESS=yes is in system/ and needs no session)
    if [ "$headless" = 0 ] && ! launchctl print "$dom" >/dev/null 2>&1; then
        skip launchd "no gui launchd domain (ssh or CI): the login agents need a logged-in session"
    else
        unit spark.check 1
        if [ "$serve_ready" = 1 ] && ! launchctl print "$dom/spark.serve" >/dev/null 2>&1 && ! launchctl print system/spark.serve >/dev/null 2>&1 \
           && curl -fs -m 2 "http://127.0.0.1:${SPARK_PORT:-8080}/health" >/dev/null 2>&1; then
            skip spark.serve "port ${SPARK_PORT:-8080} already answers /health (another server); not installing"
        else
            unit spark.serve "$serve_ready"
        fi
        unit spark.forge "$forge_ready" "$forge_why"
    fi
    # sleep: a brain never sleeps, wakes on LAN, comes back after a power cut.
    # Only the keys this hardware lists are set (a laptop has no autorestart);
    # SITE_HEADLESS=no sets nothing -- a workstation's defaults are its own.
    pm=$(pmset -g 2>/dev/null || true); pm_set=''; pm_now=''
    for kv in sleep=0 disksleep=0 womp=1 autorestart=1; do
        k=${kv%=*}; v=${kv#*=}
        cur=$(printf '%s\n' "$pm" | awk -v k="$k" '$1 == k { print $2; exit }')
        [ -z "$cur" ] || [ "$cur" = "$v" ] || { pm_set="$pm_set $k $v"; pm_now="$pm_now $k=$cur"; }
    done
    if [ "$headless" = 0 ]; then skip sleep "left as is (pmset -g); SITE_HEADLESS=no sets nothing"
    elif [ -z "$pm_set" ]; then ok sleep "never sleeps, wake on LAN (pmset)"
    elif need sleep "pmset -a$pm_set (now:$pm_now) (sudo)"; then
        # shellcheck disable=SC2086
        as_root pmset -a $pm_set; ok sleep "never sleeps, wake on LAN (pmset)"
    fi
else
    if ! systemctl --user show-environment >/dev/null 2>&1; then
        skip systemd "no user systemd session (headless or container)"
    else
        [ "$MODE" = dry ] || systemctl --user daemon-reload
        # first, before a unit starts a server: linger and the render group.
        # headless: nobody logs in, so the login session's two gifts are
        # replaced -- linger (the user's units run from boot, not from
        # login) and the render group (llama-server reads /dev/dri/render*
        # for the GPU; the group is durable where a logind seat ACL
        # vanishes with the console session). A workstation keeps linger
        # from its login session; SITE_HEADLESS=no sets nothing there.
        if [ "$headless" = 0 ]; then
            skip linger "a workstation (SITE_HEADLESS=no): units run from login"
        elif [ "$(loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null)" = yes ]; then ok linger "units run from boot"
        elif need linger "loginctl enable-linger $(id -un) (sudo)"; then
            as_root loginctl enable-linger "$(id -un)"; ok linger "units run from boot"; fi
        # the render group is core on a vulkan build too: an ssh login has
        # no seat, so no ACL, and llama-server would fall back to the CPU
        if [ -e /dev/dri/renderD128 ] && getent group render >/dev/null 2>&1 && { [ "$headless" = 1 ] || [ "$AI_BUILD" = vulkan ]; }; then
            if id -nG | tr " " "\n" | grep -qx render; then ok render "in the render group"
            elif need render "usermod -aG render $(id -un) (sudo; then log in again)"; then
                as_root usermod -aG render "$(id -un)"; ok render "added -- the units see the GPU once you log out of every session and in again"; fi
        fi
        if [ "$(systemctl --user is-enabled spark-check.timer 2>/dev/null)" = enabled ]; then ok spark-check "timer enabled"
        elif need spark-check "systemctl --user enable --now spark-check.timer"; then
            systemctl --user enable --now spark-check.timer; ok spark-check "timer enabled"; fi
        en=$(systemctl --user is-enabled spark-serve.service 2>/dev/null || true)
        if [ "$serve_ready" = 1 ]; then
            if [ "$en" = enabled ]; then ok spark-serve "enabled ($(systemctl --user is-active spark-serve.service 2>/dev/null))"
            elif need spark-serve "systemctl --user enable --now spark-serve.service"; then
                systemctl --user enable --now spark-serve.service; ok spark-serve "enabled"; fi
        else
            if [ "$en" = enabled ] && need spark-serve "disable ($serve_why)"; then
                systemctl --user disable --now spark-serve.service; ok spark-serve "disabled"
            elif [ "$en" != enabled ]; then skip spark-serve "on demand ($serve_why)"; fi
        fi
        en=$(systemctl --user is-enabled spark-forge.service 2>/dev/null || true)
        if [ "$forge_ready" = 1 ]; then
            if [ "$en" = enabled ]; then ok spark-forge "enabled ($(systemctl --user is-active spark-forge.service 2>/dev/null))"
            elif need spark-forge "systemctl --user enable --now spark-forge.service"; then
                systemctl --user enable --now spark-forge.service; ok spark-forge "enabled"; fi
        else
            if [ "$en" = enabled ] && need spark-forge "disable ($forge_why)"; then
                systemctl --user disable --now spark-forge.service; ok spark-forge "disabled"
            elif [ "$en" != enabled ]; then skip spark-forge "off ($forge_why)"; fi
        fi
    fi
    # sleep: a brain never sleeps (the four sleep targets masked) and a laptop
    # as the box keeps running with its lid shut (a logind drop-in, HUP to
    # logind). `spark headless off` undoes both (SPARK_HEADLESS_UNDO=1): a
    # plain run with SITE_HEADLESS=no never touches another user's brain.
    targets="sleep.target suspend.target hibernate.target hybrid-sleep.target"
    nmasked=0
    for t in $targets; do [ "$(systemctl is-enabled "$t" 2>/dev/null || true)" = masked ] && nmasked=$((nmasked + 1)); done
    dropin=/etc/systemd/logind.conf.d/spark.conf
    lid=$(printf '[Login]\nHandleLidSwitch=ignore\nHandleLidSwitchExternalPower=ignore\n')
    # WSL 2 stops with its last window: a hand-set SITE_HEADLESS=yes there is a
    # todo, never a systemctl mask (spark headless on refuses it first)
    if [ "$headless" = 1 ] && is_wsl; then row todo headless "WSL 2 stops with its last window: not a brain (a Linux box is)"; headless=0; fi
    if [ "$headless" = 1 ]; then
        if [ "$nmasked" = 4 ]; then ok sleep "sleep, suspend, hibernate masked"
        elif need sleep "systemctl mask $targets (sudo)"; then
            # shellcheck disable=SC2086
            as_root systemctl mask $targets >/dev/null 2>&1; ok sleep "sleep, suspend, hibernate masked"; fi
        if [ "$(cat "$dropin" 2>/dev/null)" = "$lid" ]; then ok lid "ignored ($dropin)"
        elif need lid "write $dropin: HandleLidSwitch=ignore; HUP systemd-logind (sudo)"; then
            as_root mkdir -p "$(dirname "$dropin")"
            printf '%s\n' "$lid" | as_root tee "$dropin" >/dev/null
            as_root systemctl kill -s HUP systemd-logind.service 2>/dev/null || true
            ok lid "ignored ($dropin)"; fi
    elif [ "$nmasked" = 0 ] && [ ! -f "$dropin" ]; then
        skip sleep "a workstation (SITE_HEADLESS=no)"
    elif [ "${SPARK_HEADLESS_UNDO:-}" != 1 ]; then
        skip sleep "masked by a brain on this machine (spark headless off undoes it)"
    else
        if [ "$nmasked" != 0 ] && need sleep "systemctl unmask $targets (SITE_HEADLESS=no) (sudo)"; then
            # shellcheck disable=SC2086
            as_root systemctl unmask $targets >/dev/null 2>&1; ok sleep "unmasked: the box may sleep again"; fi
        if [ -f "$dropin" ] && need lid "remove $dropin; HUP systemd-logind (SITE_HEADLESS=no) (sudo)"; then
            as_root rm -f "$dropin"; as_root systemctl kill -s HUP systemd-logind.service 2>/dev/null || true
            ok lid "the lid closes the laptop again"; fi
    fi
fi

# =============================================================== 11. share
# One engine for every OS user on this machine: a `spark` group may read a
# 0640 copy of the api-token, so a group member's spark (spark client) uses
# this box's llama-server without a token of its own -- its own soul and
# memory, one model loaded once. The owner's api-token stays 0600 in $HOME;
# the shared copy is re-synced here, so a rotated token is picked up. macOS
# and WSL 2 keep one user per box in this version.
section share
share_tok=${SPARK_SHARE_TOKEN:-/etc/spark/token}
share_url=${SPARK_SHARE_URL:-/etc/spark/url}
if [ "$client" = 1 ]; then
    # a client joins a shared engine, it does not run one: never touch the
    # owner's token or the group, and never a root step (a joining user has
    # no sudo). This is what lets a second OS user set up in userspace.
    skip share "$CLIENT_OF"
elif [ "$OS" = Darwin ] || is_wsl; then
    if [ "$SITE_SHARE" = yes ]; then row todo share "one user per box here (macOS/WSL): a shared engine is a Linux box story"
    else skip share "not shared (one user per box on macOS/WSL)"; fi
elif [ "$SITE_SHARE" != yes ]; then
    if { [ -f "$share_tok" ] || [ -f "$share_url" ]; } && need share "remove $share_tok, $share_url (SITE_SHARE=no) (sudo)"; then
        as_root rm -f "$share_tok" "$share_url"; ok share "not shared"
    else skip share "not shared (SITE_SHARE=no; spark share on)"; fi
elif [ ! -s "$tok" ]; then
    row todo share "no api-token yet: spark serve first, then spark share on"
else
    if getent group spark >/dev/null 2>&1; then ok share "group spark exists"
    elif need share "groupadd spark (sudo)"; then as_root groupadd spark; ok share "group spark created"; fi
    # freshness by mtime, not contents: the owner is not in the spark group
    # and cannot read the 0640 copy, so a content compare would never
    # converge -- the copy is current when it is no older than the source
    if [ -f "$share_tok" ] \
       && [ "$(stat -c %Y "$share_tok" 2>/dev/null || echo 0)" -ge "$(stat -c %Y "$tok" 2>/dev/null || echo 0)" ] \
       && [ "$(stat -c '%a %G' "$share_tok" 2>/dev/null)" = "640 spark" ]; then
        ok share "$share_tok (0640 root:spark)"
    elif need share "copy the api-token to $share_tok (0640 root:spark) (sudo)"; then
        as_root mkdir -p "$(dirname "$share_tok")"
        as_root cp "$tok" "$share_tok"
        as_root chgrp spark "$share_tok"
        as_root chmod 0640 "$share_tok"
        ok share "$share_tok (0640 root:spark)"
    fi
    # the engine's address, so a joining user finds it without reading the
    # owner's $HOME. Not a secret (the token gates use): 0644.
    surl=$(cat "$SPARK_STATE_DIR/serve-url" 2>/dev/null || true)
    if [ -z "$surl" ]; then row todo share "engine URL unknown yet ($share_url): spark serve, then spark share on"
    elif [ -f "$share_url" ] && [ "$(cat "$share_url" 2>/dev/null)" = "$surl" ]; then ok share "$share_url ($surl)"
    elif need share "publish the engine URL to $share_url (sudo)"; then
        as_root mkdir -p "$(dirname "$share_url")"
        printf '%s\n' "$surl" | as_root tee "$share_url" >/dev/null
        as_root chmod 0644 "$share_url"
        ok share "$share_url ($surl)"
    fi
fi

# ============================================================ 12. terminal
section terminal
if [ "$SITE_THEME" = none ]; then
    skip theme "SITE_THEME=none: your terminal keeps its colours"
else
    # the palette must exist (yours first, then the repository's), but
    # writing theme.env, the console files and the mac profile is
    # `spark theme NAME`'s alone: a bootstrap run paints nothing
    tf="$SPARK_CONFIG_DIR/themes/$SITE_THEME.env"
    [ -f "$tf" ] || tf="$REPO/themes/$SITE_THEME.env"
    if [ ! -f "$tf" ]; then
        printf 'spark: SITE_THEME=%s: no such palette (themes/*.env, ~/.config/spark/themes/*.env)\n' "$SITE_THEME" >&2
        exit 1
    fi
    if [ -f "$SPARK_CONFIG_DIR/theme.env" ]; then
        ok theme "$SITE_THEME (painted: theme.env; spark theme NAME repaints)"
    else
        skip theme "$SITE_THEME chosen, not painted (spark theme $SITE_THEME)"
    fi
fi
# the text console's font (console-setup), when chosen: core -- spark
# font sets SITE_FONT_FACE either way
if [ "$client" = 1 ]; then
    skip console "a client: the console keeps its font"
elif [ "$OS" = Darwin ]; then
    skip console "macOS: the font is in the Terminal.app profile (spark theme profile)"
elif is_wsl; then
    skip console "WSL 2: no console -- the font is Windows Terminal's"
elif [ "$DISTRO" = arch ]; then
    skip console "Arch: no console-setup -- the font is /etc/vconsole.conf's, left alone in this version"
elif [ -z "$SITE_FONT_FACE" ]; then
    skip console "SITE_FONT_FACE unset: the console keeps its font"
else
    size=${SITE_FONT_SIZE:-16x32}
    cur=$(sed -n 's/^FONTFACE="\{0,1\}\([^"]*\)"\{0,1\}$/\1/p; s/^FONTSIZE="\{0,1\}\([^"]*\)"\{0,1\}$/\1/p' /etc/default/console-setup 2>/dev/null | paste -sd' ' -)
    if [ "$cur" = "$SITE_FONT_FACE $size" ]; then ok console "$SITE_FONT_FACE $size"
    elif need console "set $SITE_FONT_FACE $size in /etc/default/console-setup (sudo)"; then
        # the original, once: spark uninstall puts it back
        as_root cp -n /etc/default/console-setup /etc/default/console-setup.spark-orig 2>/dev/null || true
        as_root sed -i "s/^FONTFACE=.*/FONTFACE=\"$SITE_FONT_FACE\"/; s/^FONTSIZE=.*/FONTSIZE=\"$size\"/" /etc/default/console-setup
        as_root setupcon --force 2>/dev/null || true
        ok console "$SITE_FONT_FACE $size"
    fi
fi
# the console palette at boot: a user's escapes reach their own VT (the rc
# hook, spark theme), but the login screen is drawn before any shell runs
# and other VTs keep the kernel's defaults. This one-shot unit (root,
# setvtrgb: the same sudo as the font) sets the defaults at every boot from
# the .rgb twin of console-colors. No palette painted yet: nothing to do.
vt_unit=/etc/systemd/system/spark-console.service
vt_file="$SPARK_CONFIG_DIR/console-colors.rgb"
if [ "$client" = 1 ]; then
    skip vt-palette "a client: no boot unit installed here"
elif [ "$OS" = Darwin ]; then
    skip vt-palette "macOS: the palette is the Terminal.app profile's"
elif is_wsl; then
    skip vt-palette "WSL 2: no console"
elif [ ! -f "$vt_file" ]; then
    skip vt-palette "no palette painted yet (spark theme NAME)"
elif ! command -v setvtrgb >/dev/null 2>&1; then
    row todo vt-palette "setvtrgb is missing: $PM_INSTALL kbd"
elif [ ! -d /run/systemd/system ]; then
    skip vt-palette "no booted systemd here (a container): the unit waits for a machine that boots"
else
    vt_want=$(printf '[Unit]\nDescription=spark: the console palette (setvtrgb)\nAfter=console-setup.service systemd-vconsole-setup.service\nConditionPathExists=%s\n\n[Service]\nType=oneshot\nExecStart=/usr/bin/setvtrgb %s\n\n[Install]\nWantedBy=multi-user.target\n' "$vt_file" "$vt_file")
    # the kernel's live defaults (sysfs, the red line) must be the file's:
    # spark theme and spark shell off rewrite the file under a unit that
    # already exists, and the defaults follow only when someone sets them
    vt_live=$(cat "${SPARK_SYSFS_VT:-/sys/module/vt/parameters}/default_red" 2>/dev/null || true)
    vt_mine=$(sed -n 1p "$vt_file")
    vt_unit_ok=0
    [ "$(cat "$vt_unit" 2>/dev/null)" = "$vt_want" ] && systemctl is-enabled spark-console.service >/dev/null 2>&1 && vt_unit_ok=1
    if [ "$vt_unit_ok" = 1 ] && [ "$vt_live" = "$vt_mine" ]; then
        ok vt-palette "spark-console.service: setvtrgb $vt_file at boot; the defaults are the file's"
    elif [ "$vt_unit_ok" = 1 ]; then
        if need vt-palette "setvtrgb $vt_file: the defaults changed under the unit (sudo)"; then
            as_root setvtrgb "$vt_file" 2>/dev/null || true
            ok vt-palette "spark-console.service: setvtrgb $vt_file at boot; the defaults set now"
        fi
    elif need vt-palette "write $vt_unit; enable it; setvtrgb now (sudo)"; then
        printf '%s\n' "$vt_want" | as_root tee "$vt_unit" >/dev/null
        as_root systemctl daemon-reload
        as_root systemctl enable spark-console.service >/dev/null 2>&1 || true
        as_root setvtrgb "$vt_file" 2>/dev/null || true      # the defaults now, for the other VTs
        ok vt-palette "spark-console.service: setvtrgb $vt_file at boot; the defaults set now"
    fi
fi
if [ "$client" = 1 ]; then
    skip quiet-login "a client: the login screen is left as it is"
    skip quiet-boot "a client: the boot is left as it is"
elif [ "$OS" = Darwin ]; then
    skip quiet-login "macOS: no motd"
    skip quiet-boot "macOS: no GRUB"
else
    # a quiet login: no distro notice, no kernel line before the greeting,
    # and a bare `login:` -- /etc/issue (the pre-login OS banner) empties
    # with the motd, so the console shows the prompt and nothing else.
    # The one thing issue keeps is invisible: the cursor-on escape
    # (ESC [?25h), because quiet boot's vt.global_cursor_default=0 is
    # global and would leave the login prompt cursorless without it
    cursor_on=$(printf '\033[?25h')
    if [ "$SITE_QUIET_LOGIN" != yes ]; then
        if [ ! -s /etc/motd ] && [ -f /usr/share/base-files/motd ] || [ -f /etc/update-motd.d/10-uname ] && [ ! -x /etc/update-motd.d/10-uname ]; then
            if need quiet-login "restore the distro notice, kernel line and login banner (sudo)"; then
                if [ -f /etc/motd.orig ]; then as_root cp /etc/motd.orig /etc/motd
                elif [ -f /usr/share/base-files/motd ]; then as_root cp /usr/share/base-files/motd /etc/motd; fi
                [ -f /etc/update-motd.d/10-uname ] && as_root chmod +x /etc/update-motd.d/10-uname
                [ -f /etc/issue.orig ] && as_root cp /etc/issue.orig /etc/issue
                ok quiet-login "loud: distro notice, kernel line and login banner back"
            fi
        else skip quiet-login "loud (SITE_QUIET_LOGIN=no)"; fi
    elif [ ! -s /etc/motd ] && [ ! -x /etc/update-motd.d/10-uname ] && [ "$(cat /etc/issue 2>/dev/null)" = "$cursor_on" ]; then
        ok quiet-login "motd empty, no kernel line, bare login prompt (cursor kept)"
    elif need quiet-login "empty /etc/motd and /etc/issue (cursor escape only), disable update-motd.d/10-uname (sudo)"; then
        [ -s /etc/motd ] && as_root cp -n /etc/motd /etc/motd.orig 2>/dev/null
        [ -f /etc/motd ] && as_root truncate -s 0 /etc/motd      # Arch ships none: an absent motd is quiet already
        [ -x /etc/update-motd.d/10-uname ] && as_root chmod -x /etc/update-motd.d/10-uname
        [ -s /etc/issue ] && ! grep -q '25h' /etc/issue && as_root cp -n /etc/issue /etc/issue.orig 2>/dev/null
        printf '\033[?25h' | as_root tee /etc/issue >/dev/null
        ok quiet-login "motd empty, no kernel line, bare login prompt (cursor kept; originals: *.orig)"
    fi
    # a quiet boot: straight past GRUB's menu, a silent kernel line, and
    # only errors from systemd. One drop-in spark owns -- the user's
    # GRUB_CMDLINE_LINUX_DEFAULT is never sed'd; grub-mkconfig sources
    # /etc/default/grub.d/*.cfg after the main file, zz- sorts it last so
    # it wins. quiet+loglevel=3 silence the kernel, splash hands plymouth
    # the boot when it is installed (inert otherwise),
    # systemd.show_status=false keeps mount/fsck status lines off the
    # console entirely (failures still land in the journal; loglevel=3
    # keeps a broken kernel able to say so), udev.log_level=3 quiets the
    # initramfs, vt.global_cursor_default=0 stops the early blinking
    # cursor, fbcon=nodefer stops the framebuffer's mid-boot flicker.
    # update-grub is the Debian-family guard: no update-grub, no touch.
    grub_dropin=/etc/default/grub.d/zz-spark-quiet.cfg
    # the $GRUB_CMDLINE reference below is grub's to expand, not ours
    # shellcheck disable=SC2016
    grub_want='GRUB_TIMEOUT=0
GRUB_TIMEOUT_STYLE=hidden
GRUB_CMDLINE_LINUX_DEFAULT="$GRUB_CMDLINE_LINUX_DEFAULT quiet splash loglevel=3 systemd.show_status=false udev.log_level=3 vt.global_cursor_default=0 fbcon=nodefer"'
    # /usr/sbin is not in a user's PATH on Debian: look for update-grub
    # there too (sudo's secure_path finds it at run time either way) --
    # `command -v` alone once mis-skipped a real Debian as "not GRUB"
    have_update_grub() { command -v update-grub >/dev/null 2>&1 || [ -x /usr/sbin/update-grub ]; }
    # the row is only ok when the ARTIFACT agrees: the generated
    # /boot/grub/grub.cfg carries our kernel line (update-grub failures
    # were once swallowed and the row lied ok). Reading it needs root on
    # newer Debians (0600): the action path verifies as root right after
    # update-grub; the steady state and --dry-run verify only when the
    # file is readable without sudo (dry-run never calls sudo).
    grub_live_quiet() { as_root grep -q 'loglevel=3' /boot/grub/grub.cfg 2>/dev/null; }
    grub_user_ok() { [ ! -r /boot/grub/grub.cfg ] || grep -q 'loglevel=3' /boot/grub/grub.cfg 2>/dev/null; }
    if [ "$SITE_QUIET_BOOT" != yes ]; then
        if [ -f "$grub_dropin" ] || grep -q '^GRUB_TIMEOUT=0$' /etc/default/grub 2>/dev/null; then
            if need quiet-boot "show GRUB's menu again, 5 s; kernel messages back (sudo)"; then
                as_root rm -f "$grub_dropin"
                as_root sed -i 's/^GRUB_TIMEOUT=.*/GRUB_TIMEOUT=5/; s/^GRUB_TIMEOUT_STYLE=.*/GRUB_TIMEOUT_STYLE=menu/' /etc/default/grub
                if as_root update-grub >/dev/null 2>&1; then
                    ok quiet-boot "loud: GRUB menu shown for 5 s, kernel messages back"
                else
                    row todo quiet-boot "update-grub failed -- run: sudo update-grub"
                fi
            fi
        else skip quiet-boot "loud (SITE_QUIET_BOOT=no)"; fi
    elif is_wsl; then
        skip quiet-boot "WSL 2: no GRUB (Windows boots it)"
    elif [ "$DISTRO" = arch ]; then
        skip quiet-boot "Arch: no update-grub -- GRUB left alone in this version"
    elif [ ! -f /etc/default/grub ]; then
        skip quiet-boot "no /etc/default/grub here"
    elif ! have_update_grub; then
        skip quiet-boot "no update-grub: not a Debian-family GRUB -- left alone"
    elif [ -f "$grub_dropin" ] && [ "$(cat "$grub_dropin" 2>/dev/null)" = "$grub_want" ] && grub_user_ok; then
        ok quiet-boot "silent: menu hidden, kernel line quiet ($grub_dropin)"
    elif need quiet-boot "GRUB drop-in $grub_dropin; update-grub (sudo)"; then
        as_root mkdir -p /etc/default/grub.d
        printf '%s\n' "$grub_want" | as_root tee "$grub_dropin" >/dev/null
        if as_root update-grub >/dev/null 2>&1 && grub_live_quiet; then
            ok quiet-boot "silent: menu hidden, kernel line quiet (hold Shift at boot for the menu)"
        else
            row todo quiet-boot "grub.cfg does not carry the quiet line -- run: sudo update-grub, then spark check"
        fi
    fi
fi

# =============================================================== report
printf '\n'
if [ "$todo" -eq 0 ]; then echo "Nothing to do"; else echo "$todo to do"; fi
