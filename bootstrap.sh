#!/bin/sh
# spark bootstrap.sh -- a fresh Debian-family, Arch or Void Linux, or macOS,
# to a spark workstation, idempotently. Run it again after any change to
# site.env. An apply run prints what it CHANGED and what needs you, and
# nothing else: a converged machine says only "Nothing to do".
#
#   ./bootstrap.sh                 apply (sudo only for the packages, runit's root service and the headless rows)
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
# one layer: the AI. The rc files stay yours (the rc row adds one line);
# an editor is an app's plugin (spark-micro). spark ships no tool of its
# own beyond the engine.
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
        echo "nothing is served here; what fits is the other machine's (spark model there)"
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
        echo "* = spark (the prompt line), + = the chat model (conversations)"
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
todo=0          # a dry run: what would change; an apply run: what it changed
needs=0         # the todo rows, what needs the user: an apply run counts them apart
acting=0        # the row about to print is a change, not a state already true
row() { [ "$1" != todo ] || needs=$((needs + 1)); printf '%-6s %-12s %s\n' "$1" "$2" "${3:-}"; }
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
made() {   # made STEP -- record a root-side change THIS bootstrap made, so
    # spark uninstall undoes only what spark did (state/made, one word a line)
    [ "$MODE" = dry ] && return 0
    mkdir -p "$SPARK_STATE_DIR" 2>/dev/null || true
    grep -qx "$1" "$SPARK_STATE_DIR/made" 2>/dev/null || echo "$1" >> "$SPARK_STATE_DIR/made"
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
        echo "bootstrap: no sudo here, and the packages and the units need root." >&2
        echo "bootstrap: run it as root, or install sudo first. Nothing was changed." >&2
        exit 1
    fi
    sudo -n true 2>/dev/null && return 0        # passwordless, or already cached
    [ -t 0 ] || return 0                        # nobody to ask: let the root step speak
    printf 'spark needs sudo once, now: the packages and the units.\n'
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
    # https only, redirects included: a pinned download never drops to http.
    PARTIAL=$2
    if [ -t 2 ]; then
        printf '       downloading %s\n' "${1##*/}"
        curl -fL --proto '=https' --proto-redir '=https' --retry 3 --progress-bar -o "$2" "$1" || fetch_died "$1"
    else
        curl -fsSL --proto '=https' --proto-redir '=https' --retry 3 -o "$2" "$1" || fetch_died "$1"
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
if [ -z "$pick" ] && [ "$SITE_EMBER_MODEL" != none ]; then ok ember "no spark model here: nothing is served, no chat model"
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
    # read and set by what is present, never by family: hostname is not in
    # every base (uname -n is POSIX), hostnamectl is systemd's -- without it
    # the name is /etc/hostname's at boot and the kernel's now
    if [ "$(hostname -s 2>/dev/null || hostname 2>/dev/null || uname -n)" = "$SITE_NAME" ]; then
        ok hostname "$SITE_NAME"
    elif need hostname "set to $SITE_NAME (sudo)"; then
        if [ "$OS" = Darwin ]; then
            for k in LocalHostName ComputerName HostName; do as_root scutil --set $k "$SITE_NAME"; done
        elif command -v hostnamectl >/dev/null 2>&1; then
            as_root hostnamectl set-hostname "$SITE_NAME"
        else
            printf '%s\n' "$SITE_NAME" | as_root tee /etc/hostname >/dev/null
            as_root sysctl -qw kernel.hostname="$SITE_NAME" 2>/dev/null || true
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
        xbps) xbps-query -p pkgver "$1" >/dev/null 2>&1 ;;
        *) return 1 ;;
    esac
}
pkg_available() {
    case $PM in
        apt) apt-cache policy "$1" 2>/dev/null | grep -q 'Candidate: [^(]' ;;
        pacman) pacman -Sp "$1" >/dev/null 2>&1 ;;
        xbps) xbps-query -R -p pkgver "$1" >/dev/null 2>&1 ;;
        *) return 1 ;;
    esac
}
pkg_install() {   # pkg_install NAME... -- as root, the manager's own way
    case $PM in
        apt) as_root apt-get update -qq && as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$@" ;;
        pacman) as_root pacman -S --needed --noconfirm "$@" ;;      # never -Sy alone: a rolling distro forbids the partial upgrade
        xbps) as_root xbps-install -Sy "$@" ;;                     # -S syncs the index; a stale xbps refuses (the todo below)
        *) return 1 ;;
    esac
}
section packages
if [ "$client" = 1 ]; then
    skip packages "a client: nothing to install here (python3 and curl already run this)"
elif [ "$OS" = Darwin ]; then
    ok packages "nothing required"
elif [ -z "$PM" ]; then
    row todo packages "no package list for this Linux ($(sed -n 's/^PRETTY_NAME=//p' "${SPARK_OS_RELEASE:-/etc/os-release}" 2>/dev/null | tr -d '"')): distro/*.env know debian, arch and void -- install git curl python3 and libgomp by hand"
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
        elif [ "$PM" = xbps ]; then
            # xbps itself is behind, most often (a rolling distro refuses
            # every install until it is current): the full upgrade is the fix
            row todo packages "xbps could not install:$missing -- sudo xbps-install -Su (a rolling distro: xbps itself must be current), then run again"
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
    # named in memory either way; the note lands on disk only in an apply
    # run -- a dry run changes nothing, one-line note or not
    [ "$MODE" = dry ] || echo "$have" > "$ENGINE_DIR/flavour"
fi
if [ "$client" = 1 ]; then
    skip engine "$CLIENT_OF"
elif [ "$SITE_AI_MODEL" = none ]; then
    # no model chosen, no peer either: nothing to run the engine for --
    # spark model NAME brings it (a client never gets one, see above)
    skip engine "no model chosen -- spark model NAME brings the engine with it"
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
# older pins beside the current one: each is ~1 GB nobody runs any more
case $ENGINE_DIR in
    */llama.cpp-b*)
        old_pins=''
        for d in "$(dirname "$ENGINE_DIR")"/llama.cpp-b*; do
            [ -d "$d" ] && [ "$d" != "$ENGINE_DIR" ] && old_pins="$old_pins $d"
        done
        if [ -n "$old_pins" ]; then
            if need engine-old "remove older engine pins:$old_pins"; then
                # shellcheck disable=SC2086
                rm -rf $old_pins
                ok engine-old "older pins removed:$old_pins"
            fi
        fi ;;
esac
# the models, one per role (both OSes): each pick's six fields become $1..$6
for role in spark ember; do
    if [ "$role" = spark ]; then rname=model; choice=$SITE_AI_MODEL; else rname=ember; choice=$SITE_EMBER_MODEL; fi
    # shellcheck disable=SC2046
    set -- $(model_pick "$role")
    if [ "$choice" = none ]; then
        [ "$role" = spark ] && skip model "SITE_AI_MODEL=none" || skip ember "SITE_EMBER_MODEL=none"
    elif [ "$role" = ember ] && [ -z "$(model_pick spark)" ]; then
        skip ember "no spark model here: nothing is served, no chat model"
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
# the bin and the state dirs are spark's own (no projects folder)
for d in "$MODELS_DIR" "$HOME/.local/bin" "$SPARK_STATE_DIR"; do
    if [ -d "$d" ]; then ok dir "$d"
    elif need dir "mkdir $d"; then mkdir -p "$d"; ok dir "$d"; fi
done
[ ! -d "$SPARK_STATE_DIR" ] || chmod 0700 "$SPARK_STATE_DIR"

# ============================================================= 7. configs
section configs
if [ "$MODE" = dry ]; then out=$(sh "$REPO/install.sh" --dry-run); else out=$(sh "$REPO/install.sh"); fi
printf '%s\n' "$out" | grep -v '^ok ' | grep -vE '^(Nothing to do|[0-9]+ to do)$' | sed 's/^/       /' || true
if [ "$MODE" = dry ]; then n=$(printf '%s\n' "$out" | grep -c '^would' || true)
else n=$(printf '%s\n' "$out" | grep -cE '^(link|render|back up) ' || true); fi
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
# the rc hook: one marked line at the end of the login shell's rc file
# (after fzf: the widget wraps Enter, so it loads last). The marker is
# `config/spark/hook.`, so the line lands once -- in a file or through a
# symlink of yours alike.
rc_bin=$(login_shell); rc_shell=${rc_bin##*/}; rc_major=
case $rc_shell in
    bash) rc="$HOME/.bashrc"; rc_line='[ -r ~/.config/spark/hook.bash ] && . ~/.config/spark/hook.bash   # spark: the AI at the prompt'
          rc_major=$("$(command -v "$rc_bin" || echo bash)" -c 'echo "${BASH_VERSINFO[0]}"' 2>/dev/null || true) ;;
    zsh)  rc="$HOME/.zshrc";  rc_line='[[ -r ~/.config/spark/hook.zsh ]] && source ~/.config/spark/hook.zsh   # spark: the AI at the prompt' ;;
    *)    rc=; rc_line= ;;
esac
if [ -z "$rc" ]; then
    row todo rc "shell $rc_shell: no prompt line for it -- bash 4+ or zsh hosts one (chsh -s /bin/zsh)"
elif [ "$rc_shell" = bash ] && [ "${rc_major:-0}" -lt 4 ]; then
    row todo rc "bash ${rc_major:-3} cannot host the prompt line -- zsh can (chsh -s /bin/zsh)"
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
# and the box never sleeps (SITE_HEADLESS=yes; `spark serve boot on`)
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
    # the render group is core on a vulkan build too, and on either init: an
    # ssh login has no seat, so no ACL, and llama-server would fall back to
    # the CPU; headless, the group is durable where a logind seat ACL
    # vanishes with the console session. A workstation on a cpu build sets
    # nothing here.
    if [ -e /dev/dri/renderD128 ] && getent group render >/dev/null 2>&1 && { [ "$headless" = 1 ] || [ "$AI_BUILD" = vulkan ]; }; then
        # runit: the services take their groups from runsvdir-USER when it
        # starts, never from a login (until then the servers use sg render)
        if [ "$INIT" = runit ]; then again="sudo sv restart runsvdir-$(id -un)"; seen="once runsvdir-$(id -un) restarts ($again, or a reboot); until then the servers use sg render"
        else again="log in again"; seen="once you log out of every session and in again"; fi
        if id -nG | tr " " "\n" | grep -qx render; then ok render "in the render group"
        elif need render "usermod -aG render $(id -un) (sudo; then $again)"; then
            as_root usermod -aG render "$(id -un)"; made render; ok render "added -- the units see the GPU $seen"; fi
    fi
    if [ "$INIT" = runit ]; then
        # runit (Void): no user manager and no timer, so the user's services
        # are one root service, /etc/sv/runsvdir-USER, whose run script drops
        # to the user (chpst) and runs runsvdir over ~/.config/spark/sv -- the
        # three dirs install.sh rendered (spark-check loops in place of a
        # timer). Linked into /var/service it runs from boot, login or not;
        # a `down` file in a service dir is the disable. A runsvdir-USER of
        # your own (no spark marker in its run) is kept: spark links its dirs
        # into the directory that one supervises. Seamed for the tests
        # (SPARK_ETC_SV here; RUNIT_LIVE and VAR_SERVICE come from facts).
        me=$(id -un); svdir="$SPARK_CONFIG_DIR/sv"; logs="$SPARK_STATE_DIR/log"
        etc_sv=${SPARK_ETC_SV:-/etc/sv}; root_sv="$etc_sv/runsvdir-$me"; root_run="$root_sv/run"
        sv_link="$VAR_SERVICE/runsvdir-$me"; sv_mark='rendered by spark bootstrap.sh'
        sv_units="spark-check spark-serve spark-forge"
        sv_show() { printf '~%s' "${1#"$HOME"}"; }
        sv_first() { sv status "$1" 2>/dev/null | awk '{ print $1; exit }'; }
        skip linger "runit: the supervisor runs from boot, login or not"
        if [ "$RUNIT_LIVE" != 1 ]; then
            skip runit "runit is not running here (a container): the services wait for a machine that boots"
        else
            # the svlogd dirs first: a log service starts with its runsv,
            # `down` file or not, and dies without its directory
            if [ "$MODE" != dry ]; then for s in $sv_units; do mkdir -p "$logs/$s"; chmod 0700 "$logs/$s"; done; fi
            if [ -f "$root_run" ] && ! grep -qsF "$sv_mark" "$root_run"; then
                # yours: the directory its runsvdir line names -- the last
                # word, quotes off, $HOME spelled out; a space or a quote
                # left in it is not a path spark will guess at
                your_svdir=$(grep runsvdir "$root_run" 2>/dev/null | tail -1 | awk '{ print $NF }' | tr -d "\"'" | sed "s|\$HOME|$HOME|g")
                linked=1
                for s in $sv_units; do [ "$(readlink "$your_svdir/$s" 2>/dev/null)" = "$svdir/$s" ] || linked=0; done
                case $your_svdir in
                    ''|*[" \"'"]*) row todo supervisor "your runsvdir-$me's directory could not be read: link ~/.config/spark/sv/spark-* into it by hand" ;;
                    *)  if [ "$linked" = 1 ]; then ok supervisor "your runsvdir-$me supervises $your_svdir; spark's services are linked there"
                        elif [ ! -d "$your_svdir" ]; then row todo supervisor "your runsvdir-$me's directory could not be read: link ~/.config/spark/sv/spark-* into it by hand"
                        elif need supervisor "link spark-check, spark-serve, spark-forge into $your_svdir (your runsvdir-$me)"; then
                            for s in $sv_units; do ln -sfn "$svdir/$s" "$your_svdir/$s"; done
                            # runsvdir scans every 5 s: give runsv time to take spark-check
                            i=0; while [ "$i" -lt 10 ] && [ ! -e "$svdir/spark-check/supervise/ok" ]; do sleep 1; i=$((i + 1)); done
                            ok supervisor "your runsvdir-$me supervises $your_svdir; spark's services are linked there"
                        fi ;;
                esac
            else
                # spark's root service, one fixed shape (lib/spark/uninstall.py
                # knows it by the marker); the two values baked in are validated
                # first, since they land in a root-owned script: a plain user
                # name, and a HOME contract 3 takes with no space or quote in it
                root_want=$(cat <<EOF
#!/bin/sh
# rendered by spark bootstrap.sh -- $me's services from boot (spark uninstall removes it)
export USER="$me"
export HOME="$HOME"
groups="\$(id -Gn "\$USER" | tr ' ' ':')"
exec chpst -u "\$USER:\$groups" runsvdir "\$HOME/.config/spark/sv"
EOF
)
                # control/t: runsv's TERM makes runsvdir exit at once and leave
                # the services running, so Void's shutdown signalled each one
                # twice (runsv and pkill) and llama-server skipped its clean
                # exit. Stop them first, one TERM each (KILL after 15 s), then
                # HUP ends runsvdir; exit 0 = runsv sends no TERM of its own.
                # sv runs as the user (chpst), on the three names run's own
                # directory holds: the supervise files there are the user's,
                # and root never writes through them
                root_t="$root_sv/control/t"
                t_want=$(cat <<EOF
#!/bin/sh
# rendered by spark bootstrap.sh -- stop $me's services cleanly, then runsvdir
d="$HOME/.config/spark/sv"
chpst -u "$me" sv -w 15 force-stop "\$d/spark-check" "\$d/spark-serve" "\$d/spark-forge" >/dev/null 2>&1
kill -HUP "\$(cat supervise/pid)" 2>/dev/null
exit 0
EOF
)
                sv_inputs_ok() {
                    printf '%s' "$me" | grep -qE '^[a-z_][a-z0-9_-]*$' || return 1
                    case $HOME in *[';`$()|&<>"'"'"' ']*) return 1 ;; esac
                }
                if [ "$(cat "$root_run" 2>/dev/null)" = "$root_want" ] && [ "$(cat "$root_t" 2>/dev/null)" = "$t_want" ] \
                    && [ "$(readlink "$sv_link" 2>/dev/null)" = "$root_sv" ]; then
                    ok supervisor "runsvdir-$me supervises ~/.config/spark/sv from boot"
                elif ! sv_inputs_ok; then
                    row todo supervisor "$root_run: the user name $me or the home $HOME cannot ride in a root script -- write it by hand: exec chpst -u $me runsvdir ~/.config/spark/sv"
                elif need supervisor "write $root_sv, link it into $VAR_SERVICE (sudo)"; then
                    as_root mkdir -p "$root_sv"
                    printf '%s\n' "$root_want" | as_root tee "$root_run" >/dev/null
                    as_root chmod 0755 "$root_run"
                    as_root mkdir -p "${root_t%/*}"
                    printf '%s\n' "$t_want" | as_root tee "$root_t" >/dev/null
                    as_root chmod 0755 "$root_t"
                    as_root ln -sfn "$root_sv" "$sv_link"
                    made runsvdir
                    # runsvdir scans every 5 s: give runsv time to take spark-check
                    i=0; while [ "$i" -lt 10 ] && [ ! -e "$svdir/spark-check/supervise/ok" ]; do sleep 1; i=$((i + 1)); done
                    ok supervisor "runsvdir-$me supervises ~/.config/spark/sv from boot"
                fi
            fi
            # sv_row NAME WANTED WHY IDLE: ok when supervised and running;
            # else up (the `down` file goes), or disable (it comes back);
            # IDLE is the skip word when it is down on purpose
            sv_row() {
                d="$svdir/$1"
                if [ "$2" = 1 ]; then
                    first=$(sv_first "$d")
                    if [ ! -f "$d/down" ] && [ "$first" = run: ]; then ok "$1" "supervised (run)"
                    elif [ ! -f "$d/down" ] && [ "$first" = finish: ]; then
                        row todo "$1" "enabled, not running: its run exited and runsv restarts it -- tail $(sv_show "$logs/$1/current")"
                    elif need "$1" "sv up $(sv_show "$d")"; then
                        rm -f "$d/down"; sv up "$d" >/dev/null 2>&1 || true
                        i=0; while [ "$i" -lt 5 ] && [ "$(sv_first "$d")" != run: ]; do sleep 1; i=$((i + 1)); done
                        case $(sv_first "$d") in
                            run:) ok "$1" "supervised (run)" ;;
                            # finish: its run exited and runsv brings it back --
                            # enabled, not running; the svlogd tail says why
                            finish:) row todo "$1" "enabled, not running: its run exited and runsv restarts it -- tail $(sv_show "$logs/$1/current")" ;;
                            *) row todo "$1" "sv up $(sv_show "$d"): no runsv answers for it yet (runsvdir scans every 5 s) -- run again in a minute" ;;
                        esac
                    fi
                elif [ ! -f "$d/down" ]; then
                    if need "$1" "disable ($3)"; then touch "$d/down"; sv down "$d" >/dev/null 2>&1 || true; ok "$1" "disabled"; fi
                else skip "$1" "$4 ($3)"; fi
            }
            sv_row spark-check 1 "" ""
            sv_row spark-serve "$serve_ready" "$serve_why" "on demand"
            sv_row spark-forge "$forge_ready" "$forge_why" off
        fi
    else
        # the user bus, as lib/spark/engine.py user_bus_env gives it to every
        # systemctl --user: a plain ssh brings neither, and the manager runs on
        XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"; export XDG_RUNTIME_DIR
        DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"
        export DBUS_SESSION_BUS_ADDRESS
        if ! systemctl --user show-environment >/dev/null 2>&1; then
            skip systemd "no user systemd session (headless or container)"
        else
            [ "$MODE" = dry ] || systemctl --user daemon-reload
            # first, before a unit starts a server: linger. headless: nobody
            # logs in, so the login session's gift is replaced by linger (the
            # user's units run from boot, not from login). A workstation keeps
            # linger from its login session; SITE_HEADLESS=no sets nothing there.
            if [ "$headless" = 0 ]; then
                skip linger "a workstation (SITE_HEADLESS=no): units run from login"
            elif [ "$(loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null)" = yes ]; then ok linger "units run from boot"
            elif need linger "loginctl enable-linger $(id -un) (sudo)"; then
                as_root loginctl enable-linger "$(id -un)"; made linger; ok linger "units run from boot"; fi
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
    fi
    if [ "$INIT" = runit ]; then
        # no sleep targets and no logind on runit: a Void box that is a brain
        # needs no mask, and its lid is elogind's or acpid's; a hand-set
        # SITE_HEADLESS=yes stands (the services run from boot by construction)
        skip sleep "runit: no sleep targets here; nothing puts this machine to sleep on its own"
        skip lid "runit: the lid is elogind's or acpid's here; left alone"
    else
        # sleep: a brain never sleeps (the four sleep targets masked) and a laptop
        # as the box keeps running with its lid shut (a logind drop-in, HUP to
        # logind). `spark serve boot off` undoes both (SPARK_HEADLESS_UNDO=1): a
        # plain run with SITE_HEADLESS=no never touches another user's brain.
        targets="sleep.target suspend.target hibernate.target hybrid-sleep.target"
        nmasked=0
        for t in $targets; do [ "$(systemctl is-enabled "$t" 2>/dev/null || true)" = masked ] && nmasked=$((nmasked + 1)); done
        dropin=/etc/systemd/logind.conf.d/spark.conf
        lid=$(printf '[Login]\nHandleLidSwitch=ignore\nHandleLidSwitchExternalPower=ignore\n')
        # WSL 2 stops with its last window: a hand-set SITE_HEADLESS=yes there is a
        # todo, never a systemctl mask (spark serve boot on refuses it first)
        if [ "$headless" = 1 ] && is_wsl; then row todo headless "WSL 2 stops with its last window: not a brain (a Linux machine is)"; headless=0; fi
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
            skip sleep "masked by a brain on this machine (spark serve boot off undoes it)"
        else
            if [ "$nmasked" != 0 ] && need sleep "systemctl unmask $targets (SITE_HEADLESS=no) (sudo)"; then
                # shellcheck disable=SC2086
                as_root systemctl unmask $targets >/dev/null 2>&1; ok sleep "unmasked: this machine may sleep again"; fi
            if [ -f "$dropin" ] && need lid "remove $dropin; HUP systemd-logind (SITE_HEADLESS=no) (sudo)"; then
                as_root rm -f "$dropin"; as_root systemctl kill -s HUP systemd-logind.service 2>/dev/null || true
                ok lid "the lid closes the laptop again"; fi
        fi
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
    if [ "$SITE_SHARE" = yes ]; then row todo share "one user per machine here (macOS/WSL): a shared engine is for a Linux machine"
    else skip share "not shared (one user per machine on macOS/WSL)"; fi
elif [ "$SITE_SHARE" != yes ]; then
    if { [ -f "$share_tok" ] || [ -f "$share_url" ]; } && need share "remove $share_tok, $share_url (SITE_SHARE=no) (sudo)"; then
        as_root rm -f "$share_tok" "$share_url"; ok share "not shared"
    else skip share "not shared (SITE_SHARE=no; spark serve share on)"; fi
elif [ ! -s "$tok" ]; then
    row todo share "no api-token yet: spark serve on first, then spark serve share on"
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
    if [ -z "$surl" ]; then row todo share "engine URL unknown yet ($share_url): spark serve on, then spark serve share on"
    elif [ -f "$share_url" ] && [ "$(cat "$share_url" 2>/dev/null)" = "$surl" ]; then ok share "$share_url ($surl)"
    elif need share "publish the engine URL to $share_url (sudo)"; then
        as_root mkdir -p "$(dirname "$share_url")"
        printf '%s\n' "$surl" | as_root tee "$share_url" >/dev/null
        as_root chmod 0644 "$share_url"
        ok share "$share_url ($surl)"
    fi
fi

# ============================================================ 12. handback
# v1.62 took the look out of spark. What an older spark painted here goes
# back as it was, once: the console palette and font, the quiet login and
# boot, Terminal.app's spark profiles. lib/spark/handback.py is the one
# undo (spark uninstall runs it too). It finds spark's own files and
# marks, so a machine that never had them has nothing to do, and it asks
# root only for what is there. A later release drops this row.
section handback
handback() { SPARK_OS=$OS PYTHONPATH="$REPO/lib" python3 -m spark.handback "$@"; }
hb=$(handback --dry-run 2>/dev/null) || hb=
if [ -z "$hb" ]; then
    skip handback "nothing of an older spark's look is left here"
elif [ "$MODE" = dry ]; then
    printf '%s\n' "$hb"
    todo=$((todo + $(printf '%s\n' "$hb" | grep -c '^would' || true)))
else
    hb=$(handback) || true
    printf '%s\n' "$hb"
    todo=$((todo + $(printf '%s\n' "$hb" | grep -c '^ok' || true)))
    needs=$((needs + $(printf '%s\n' "$hb" | grep -c '^todo' || true)))
fi

# =========================================================== 13. knowledge
# What this machine can run -- its programs' manuals, its apps, spark's own
# verbs -- read into the store the prompt line's knowledge comes from
# (lib/spark/intake.py, STATE/knowledge/). Last, so every package above is
# in it. Rebuilt only when the machine's fingerprint moved (a package, a
# PATH or man dir, spark's tree); the check timer keeps it fresh after.
section knowledge
knowledge() { PYTHONPATH="$REPO/lib" python3 -m spark.intake "$@"; }
if knowledge fresh 2>/dev/null; then
    skip knowledge "fresh"
elif need knowledge "read the programs, manuals and apps on this machine"; then
    ok knowledge "$(knowledge build 2>/dev/null || true)"
fi

# =============================================================== report
printf '\n'
# --dry-run ends as contract 1 says. An apply run says what it changed,
# and what needs you apart from that: a count read as "to do" after a
# good run looked unfinished.
if [ "$MODE" = dry ]; then
    if [ "$todo" -eq 0 ]; then echo "Nothing to do"; else echo "$todo to do"; fi
else
    if [ "$needs" -eq 1 ]; then you="1 needs you"; else you="$needs need you"; fi
    if [ "$todo" -eq 0 ] && [ "$needs" -eq 0 ]; then echo "Nothing to do"
    elif [ "$needs" -eq 0 ]; then echo "$todo changed"
    elif [ "$todo" -eq 0 ]; then echo "$you"
    else echo "$todo changed -- $you"; fi
fi
