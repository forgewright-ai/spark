#!/bin/sh
# spark bootstrap.sh -- a fresh Debian-family Linux or macOS to a spark
# workstation, idempotently. Run it again after any change to site.env; a
# converged machine ends with "Nothing to do".
#
#   ./bootstrap.sh                 apply (sudo only for apt, and the shell/headless rows)
#   ./bootstrap.sh --dry-run       print what would change; never sudo
#   ./bootstrap.sh --list-packages one package per line, as this site wants them
#   ./bootstrap.sh --list-tools    repo-path<TAB>name of every tool linked on PATH
#   ./bootstrap.sh --list-models   the model table with a RAM verdict per row
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
usage() { sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }
case ${1:-} in
    --dry-run) MODE=dry ;;
    --list-tools) printf 'bin/spark\tspark\nbin/explain\texplain\n'; exit 0 ;;
    --list-packages|--list-models) MODE=${1#--list-} ;;
    -h|--help) usage ;;
    '') ;;
    *) usage 2 ;;
esac

# ---------------------------------------------------------------- packages
# Linux, by group, each with its reason. macOS reads Brewfile instead (the
# shell layer only: the AI needs nothing from Homebrew).
# core -- the AI: SITE_SHELL=off installs only these (+ PKG_AI for vulkan)
PKG_CORE="git curl ca-certificates python3"
PKG_ENGINE="libgomp1"                                        # llama.cpp's Ubuntu build needs OpenMP; Debian's base lacks it
PKG_AI="libvulkan1 mesa-vulkan-drivers"                      # the vulkan build only (ai_build: a GPU in sysfs, or SITE_AI_BUILD=vulkan)
# the shell layer -- SITE_SHELL=on (spark shell on)
PKG_SHELL="bash tmux unzip fontconfig ncurses-bin"           # tmux, the font's unzip + fc-cache, a tmux-256color terminfo
PKG_CLI="bat eza fzf zoxide ripgrep fd-find jq btop"        # the shell's daily tools
PKG_EDITOR="micro aspell aspell-en"                          # micro + its spell checker
PKG_QA="shellcheck"                                          # the pre-commit hook wants it

# ------------------------------------------------------------ pinned bits
# Everything not packaged is pinned by version and sha256. An empty sha
# means "not pinned yet": the block skips with a notice, never guesses.
STARSHIP_VERSION=1.26.0
STARSHIP_SHA_X86_64=321f0dd7af8340a5f2e6a8fec6538a04f617486f9ec70d878f91c09cd8deef22
STARSHIP_SHA_AARCH64=dc30189378d2f2e287384e8a692d3f95ad1df64cf0e8c36aa9201516028aed6b
NERDFONT_VERSION=3.5.1
NERDFONT_SHA=fab782a66f7d3019da64f6572db9fc5d3a4bcb19f9fa13e2d8a62e3693d6396e
# llama.cpp: one release, one tarball per OS/arch (the macOS ones carry
# Metal; on Linux ai_build picks the Vulkan build when a GPU is there)
LLAMA_VERSION=b10689
LLAMA_SHA_MACOS_ARM64=00540770ac0ef4748996f0332d3b93e73c3252d4f1d16ba613ea62cf93e7cccd
LLAMA_SHA_MACOS_X64=75f463c3ac353f54c3a8daa1b7b117ebbebc7e573bf8e49fb60a464a1665f262
LLAMA_SHA_LINUX_X64=5524e59a98b037c054760fde61fb871c5473f782336b69efeb485e845041fda7
LLAMA_SHA_LINUX_VULKAN_X64=ffa749a6c0f969fc13ec1de3d8e931374f8735965247b585c0aa141b80124c23
LLAMA_SHA_LINUX_ARM64=b70d5f153e089fbdf6ef79531a5fd462831f09b29745f11a5a86607af11c29d2
LLAMA_SHA_LINUX_VULKAN_ARM64=c34ac1facc627f39807d727c0700280b8bae3304fd27bbbd66c645cfa50f5af8
ENGINE_DIR="$SPARK_DATA_DIR/engine/llama.cpp-$LLAMA_VERSION"
# drm_vram_file: the first DRM device that reports VRAM in sysfs (Linux;
# nothing when none). SPARK_SYSFS_DRM overrides the root (tests), as it
# does for lib/spark engine.gpu_info(), the python twin of this probe.
drm_vram_file() {
    for f in "${SPARK_SYSFS_DRM:-/sys/class/drm}"/card*/device/mem_info_vram_total; do
        [ -r "$f" ] && { echo "$f"; return; }
    done
    return 0
}
# ai_build: the engine build this machine gets -- metal on macOS (the key
# is ignored there); on Linux SITE_AI_BUILD cpu|vulkan as chosen, auto
# (the default) = vulkan when a DRM device reports VRAM, else cpu. It
# drives PKG_AI, the engine flavour and the model pick's speed cap; lib/
# spark engine.backend() is the python twin and must answer the same.
ai_build() {
    [ "$OS" = Darwin ] && { echo metal; return; }
    case $SITE_AI_BUILD in
        cpu|vulkan) echo "$SITE_AI_BUILD" ;;
        *) [ -n "$(drm_vram_file)" ] && echo vulkan || echo cpu ;;
    esac
}
# engine_flavour: the release asset for this OS/arch/build, and its pin
# (empty when there is none) -- macos-arm64 | macos-x64 | ubuntu-x64 |
# ubuntu-vulkan-x64 | ubuntu-arm64 | ubuntu-vulkan-arm64
engine_flavour() {
    case $OS/$ARCH/$AI_BUILD in
        Darwin/arm64/*)         flavour=macos-arm64;         sha=$LLAMA_SHA_MACOS_ARM64 ;;
        Darwin/x86_64/*)        flavour=macos-x64;           sha=$LLAMA_SHA_MACOS_X64 ;;
        Linux/x86_64/vulkan)    flavour=ubuntu-vulkan-x64;   sha=$LLAMA_SHA_LINUX_VULKAN_X64 ;;
        Linux/x86_64/*)         flavour=ubuntu-x64;          sha=$LLAMA_SHA_LINUX_X64 ;;
        Linux/aarch64/vulkan)   flavour=ubuntu-vulkan-arm64; sha=$LLAMA_SHA_LINUX_VULKAN_ARM64 ;;
        Linux/aarch64/*)        flavour=ubuntu-arm64;        sha=$LLAMA_SHA_LINUX_ARM64 ;;
        *)                      flavour=;                    sha= ;;
    esac
}
# engine_home: where llama-server is looked for (lib/spark config.py
# default_engine_dir is the python twin): SPARK_ENGINE_DIR, else the
# newest ~/.local/share/spark/engine/<name> holding one, else Homebrew's
# bin on macOS, else the pinned directory bootstrap fills
engine_home() {
    [ -z "${SPARK_ENGINE_DIR:-}" ] || { echo "$SPARK_ENGINE_DIR"; return; }
    found=
    for d in "$SPARK_DATA_DIR"/engine/*/; do
        [ -x "$d/llama-server" ] && found=${d%/}
    done
    if [ -n "$found" ]; then echo "$found"; return; fi
    if [ "$OS" = Darwin ]; then
        for d in /opt/homebrew/bin /usr/local/bin; do
            [ -x "$d/llama-server" ] && { echo "$d"; return; }
        done
    fi
    echo "$ENGINE_DIR"
}

site_load
MODELS_DIR=${SPARK_MODELS_DIR:-$SPARK_DATA_DIR/models}
AI_BUILD=$(ai_build)
# the two layers: the AI is always on; the shell (tmux, starship, micro, the
# daily tools, the font, the rc files, the console) only with SITE_SHELL=on
shell=0; [ "$SITE_SHELL" = on ] && shell=1
SHELL_OFF="SITE_SHELL=off (spark shell on)"
# a client: no model of its own and a peer answering (SITE_AI_MODEL=none +
# SITE_PEER_AI_URL; spark client URL). No engine and no units here -- the
# widget, the hook and the tokens are all a client needs
client=0; [ "$SITE_AI_MODEL" = none ] && [ -n "$SITE_PEER_AI_URL" ] && client=1
CLIENT_OF="a client of $SITE_PEER_AI_URL (spark client off serves here again)"

# ------------------------------------------------------------- the lists
list_packages() {
    if [ "$OS" = Darwin ]; then
        [ "$shell" = 1 ] || return 0
        sed -nE 's/^(brew|cask) "([^"]+)".*/\2/p' "$REPO/Brewfile"
    else
        set -- $PKG_CORE $PKG_ENGINE
        [ "$AI_BUILD" = vulkan ] && set -- "$@" $PKG_AI
        [ "$shell" = 1 ] && set -- "$@" $PKG_SHELL $PKG_CLI $PKG_EDITOR $PKG_QA
        printf '%s\n' "$@"
    fi
}

# memory a model can live in: RAM, plus the GPU's own memory on Linux (an
# iGPU's VRAM is RAM the BIOS carved out of MemTotal; a discrete card's VRAM
# holds the weights too). The same rule as lib/spark mem_total_gb().
mem_gb() {
    # SPARK_MEM_TOTAL_GB overrides it (tests; whole GB), like SPARK_MEM_NEEDED_GB
    if [ -n "${SPARK_MEM_TOTAL_GB:-}" ]; then echo "$SPARK_MEM_TOTAL_GB"; return; fi
    if [ "$OS" = Darwin ]; then
        echo $(( $(sysctl -n hw.memsize) / 1073741824 ))
    else
        ram=$(awk '/^MemTotal:/ { printf "%d", $2 / 1048576 }' /proc/meminfo)
        vram=0; f=$(drm_vram_file)
        [ -z "$f" ] || vram=$(( $(cat "$f") / 1073741824 ))
        echo $(( ram + vram ))
    fi
}

# open_license KEY FILE: true when MODEL_<KEY>_LICENSE in FILE starts with
# a license auto may take -- Apache-2.0 or MIT (lib/spark
# config.OPEN_LICENSES is the twin).
open_license() {
    grep -E "^MODEL_${1}_LICENSE=\"?(Apache-2\.0|MIT)( |\"|$)" "$2" >/dev/null 2>&1
}
# model_rows: name file url bytes sha256 ram_gb, one per line, file order --
# the rows auto may pick: models.env rows with MODEL_<NAME>_TESTED=line
# (proven on the line) under an open license. The only source auto reads
# (lib/spark config.models_table / auto_rows is the twin).
model_rows() {
    [ -f "$REPO/models.env" ] || return 0
    grep -E '^MODEL_[A-Z0-9_]+=' "$REPO/models.env" | grep -vE '_(LICENSE|NOTE|TESTED)=' | while IFS='=' read -r k v; do
        v=${v#\"}; v=${v%\"}
        grep -qE "^${k}_TESTED=\"?line\"?$" "$REPO/models.env" || continue
        open_license "${k#MODEL_}" "$REPO/models.env" || continue
        name=$(printf '%s' "${k#MODEL_}" | tr 'A-Z_' 'a-z-')
        printf '%s %s\n' "$name" "$v"
    done
}
# model_rows_all: the list then yours, each row's name file url bytes
# sha256 ram_gb followed by a source mark: - models.env, u yours
# (~/.config/spark/models.env). An absent file is skipped; a
# LICENSE/NOTE/TESTED side-key is not a row (lib/spark config.model_tables
# is the twin, and where a name in both files is refused).
model_rows_all() {
    for pair in "$REPO/models.env -" "$SPARK_CONFIG_DIR/models.env u"; do
        # shellcheck disable=SC2086
        set -- $pair
        f=$1; mark=$2
        [ -f "$f" ] || continue
        grep -E '^MODEL_[A-Z0-9_]+=' "$f" | grep -vE '_(LICENSE|NOTE|TESTED)=' | while IFS='=' read -r k v; do
            v=${v#\"}; v=${v%\"}
            # shellcheck disable=SC2086
            set -- $v
            [ $# -eq 5 ] || continue
            name=$(printf '%s' "${k#MODEL_}" | tr 'A-Z_' 'a-z-')
            printf '%s %s %s\n' "$name" "$v" "$mark"
        done
    done
}

# model_pick spark|ember [nocap]: that role's row (lib/spark
# engine.chosen_rows is the python twin; the two must agree). spark:
# SITE_AI_MODEL none|NAME|auto -- auto is the smallest auto row (tested
# on the line, open license: model_rows) when an ember resolves beside
# it, else the largest usable auto row that fits the SITE_AI_BUDGET
# percent (default 60) alone (the default: the ember is none); a NAME is
# looked up in the list and yours, never second-guessed.
# ember: SITE_EMBER_MODEL
# none|NAME|auto -- none (default) is one model doing both; auto is the
# largest usable auto row fitting the budget beside the spark pick, a
# NAME again any row; the spark row again would be one model doing
# both, so it prints nothing. No spark model (SITE_AI_MODEL=none, or a
# name that is not there) means nothing is served here: no ember either.
# Usable = the file is at or under the speed cap (speed_cap); nothing
# usable fits -> the smallest auto row that fits, so auto never picks
# nothing while something fits (an untested row is by name only).
# `nocap` lifts the cap (list_models says what it held back).
model_sorted() { model_rows | sort -n -k6 ; }
model_sorted_all() { model_rows_all | sort -n -k6 ; }
# speed_cap: the largest file (bytes) auto takes on this build -- cpu 3 GB,
# vulkan 6 GB, metal 20 GB: the size classes the speed column keeps at
# about 8 tok/s or better (engine.SPEED_CAP_GB is the python twin). A
# `-a3b` MoE counts as its 3B active class, as in the speed column.
speed_cap() {
    case $AI_BUILD in vulkan) echo 6442450944 ;; metal) echo 21474836480 ;; *) echo 3221225472 ;; esac
}
model_fit() {   # model_fit BESIDE_GB CAP_BYTES -> the largest row with BESIDE+ram_gb <= budget and the file under CAP (0 = no cap), else the smallest that fits
    budget=$(( $(mem_gb) * ${SITE_AI_BUDGET:-60} / 100 ))
    model_sorted | awk -v b="$budget" -v s="$1" -v c="$2" \
        '$6 + s <= b { if (!first) first = $0; if (c == 0 || $4 <= c || $1 ~ /-a3b/) row = $0 } END { if (row) print row; else if (first) print first }'
}
model_pick() {
    if [ "${2:-}" = nocap ]; then cap=0; else cap=$(speed_cap); fi
    if [ "${1:-spark}" = ember ]; then
        spark_row=$(model_pick spark "${2:-}")
        [ -n "$spark_row" ] || return 0
        spark_ram=$(printf '%s' "$spark_row" | awk '{ print $6 }')
        case $SITE_EMBER_MODEL in
            none) return 0 ;;
            auto) erow=$(model_fit "$spark_ram" "$cap") ;;
            *) erow=$(model_sorted_all | awk -v n="$SITE_EMBER_MODEL" '$1 == n') ;;
        esac
        [ -n "$erow" ] && [ "${erow%% *}" != "${spark_row%% *}" ] && printf '%s\n' "$erow"
        return 0
    fi
    case $SITE_AI_MODEL in
        none) return 0 ;;
        auto)
            small=$(model_sorted | head -n 1)
            if [ "$SITE_EMBER_MODEL" != none ] && [ -n "$small" ]; then
                case $SITE_EMBER_MODEL in
                    auto) e=$(model_fit "$(printf '%s' "$small" | awk '{ print $6 }')" "$cap") ;;
                    *) e=$(model_sorted_all | awk -v n="$SITE_EMBER_MODEL" '$1 == n') ;;
                esac
                if [ -n "$e" ]; then printf '%s\n' "$small"; return 0; fi
            fi
            model_fit 0 "$cap"
            ;;
        *) model_sorted_all | awk -v n="$SITE_AI_MODEL" '$1 == n' ;;
    esac
}
# cap_note: one line when the speed cap held a bigger auto pick back
# (lib/spark engine.cap_note is the python twin), else nothing
cap_note() {
    [ "$(model_pick spark)$(model_pick ember)" != "$(model_pick spark nocap)$(model_pick ember nocap)" ] || return 0
    printf 'auto stops at %s GB files on %s (bigger fits, slower than 8 tok/s)\n' "$(( $(speed_cap) / 1073741824 ))" "$AI_BUILD"
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
    total=$(mem_gb); budget=$(( total * ${SITE_AI_BUDGET:-60} / 100 ))
    spick=$(model_pick spark | awk '{ print $1 }')
    epick=$(model_pick ember | awk '{ print $1 }')
    printf 'this machine: %s GB for models (RAM + GPU), budget %s GB (%s%%), %s\n' "$total" "$budget" "${SITE_AI_BUDGET:-60}" "$AI_BUILD"
    printf 'SITE_AI_MODEL=%s, SITE_EMBER_MODEL=%s\n' "$SITE_AI_MODEL" "$SITE_EMBER_MODEL"
    cap_note
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
row() { printf '%-6s %-12s %s\n' "$1" "$2" "${3:-}"; }
ok() { row ok "$1" "${2:-}"; }
skip() { row skip "$1" "${2:-}"; }
need() {   # need WHAT WHY -- something must change; in apply mode the caller does it
    todo=$((todo + 1))
    if [ "$MODE" = dry ]; then row would "$1" "${2:-}"; return 1; fi
    return 0
}
as_root() {
    if [ "$(id -u)" -eq 0 ]; then "$@"; else sudo "$@"; fi
}
section() { printf '\n== %s\n' "$1"; }
sha_ok() {   # sha_ok FILE SHA
    if [ "$OS" = Darwin ]; then shasum -a 256 "$1" | awk '{print $1}' | grep -qx "$2"
    else sha256sum "$1" | awk '{print $1}' | grep -qx "$2"; fi
}
fetch() {   # fetch URL DEST SHA  -- download, verify, or die
    # at a terminal: name the file and let curl draw its progress bar
    # (a model is gigabytes -- minutes, not seconds); captured output
    # (spark model/ember filtering, CI) stays quiet as before
    if [ -t 2 ]; then
        printf '       downloading %s\n' "${1##*/}"
        curl -fL --retry 3 --progress-bar -o "$2" "$1"
    else
        curl -fsSL --retry 3 -o "$2" "$1"
    fi
    sha_ok "$2" "$3" || { rm -f "$2"; echo "bootstrap: sha256 mismatch for $1" >&2; exit 1; }
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
trap 'rm -rf "$TMP"' EXIT
printf 'spark bootstrap | %s %s | %s\n' "$OS" "$ARCH" "$MODE"

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
# the shell layer: the git identity goes into ~/.gitconfig, the theme into tmux and starship
if [ "$shell" = 1 ]; then
    [ -z "$SPARK_GIT_GUESSED" ] || row todo identity \
        "guessed, and it signs every commit -- set in site.env: $SPARK_GIT_GUESSED"
    ok theme "$SITE_THEME | prompt $SITE_PROMPT/$SITE_PROMPT_STYLE"
else
    skip identity "$SHELL_OFF"
    skip theme "$SHELL_OFF"
fi
pick=$(model_pick spark | awk '{ print $1 " (" $6 " GB)" }')
case $SITE_AI_MODEL in
    none) ok model "none: no download; bring your own .gguf or set SITE_AI_MODEL" ;;
    *) [ -n "$pick" ] && ok model "$SITE_AI_MODEL -> $pick" || row todo model "SITE_AI_MODEL=$SITE_AI_MODEL: nothing fits $(mem_gb) GB / not in models.env or yours" ;;
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
if [ "$shell" = 0 ]; then
    skip hostname "$SHELL_OFF"
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
section packages
if [ "$OS" = Darwin ]; then
    if [ "$shell" = 0 ]; then
        ok brew "nothing required (SITE_SHELL=off)"
    elif ! command -v brew >/dev/null 2>&1; then
        row todo brew "Homebrew is not installed: https://brew.sh (then run again)"
    elif brew bundle check --file "$REPO/Brewfile" --no-upgrade >/dev/null 2>&1; then
        ok brew "Brewfile satisfied ($(list_packages | wc -l | tr -d ' ') entries)"
    elif need brew "brew bundle --file Brewfile"; then
        brew bundle --file "$REPO/Brewfile" --no-upgrade
        ok brew "Brewfile satisfied"
    fi
else
    missing=''; absent=''
    for p in $(list_packages); do
        if dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q 'install ok installed'; then continue; fi
        if apt-cache policy "$p" 2>/dev/null | grep -q 'Candidate: [^(]'; then missing="$missing $p"; else absent="$absent $p"; fi
    done
    [ -z "$absent" ] || skip apt "not in this apt:$absent (spark targets Debian 13 / Ubuntu 24.04+)"
    if [ -z "$missing" ]; then
        ok apt "$(list_packages | wc -l | tr -d ' ') packages installed"
    elif need apt "install:$missing (sudo)"; then
        as_root apt-get update -qq
        # shellcheck disable=SC2086
        as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $missing > "$TMP/apt.log" 2>&1 \
            || { tail -20 "$TMP/apt.log"; echo "bootstrap: apt-get install failed" >&2; exit 1; }
        ok apt "installed:$missing"
    fi
fi

# ============================================================== 4. pinned
section pinned
if [ "$OS" = Darwin ]; then
    [ "$shell" = 1 ] && skip pinned "Homebrew provides starship and the Nerd Font here" || skip pinned "$SHELL_OFF"
else
    # starship
    # look in ~/.local/bin explicitly: a non-login ssh shell has no such PATH
    if [ "$shell" = 0 ]; then
        skip starship "$SHELL_OFF"
    elif [ -x "$HOME/.local/bin/starship" ] || command -v starship >/dev/null 2>&1; then
        ok starship "$(PATH=$HOME/.local/bin:$PATH starship --version 2>/dev/null | head -1)"
    else
        case $ARCH in x86_64) sha=$STARSHIP_SHA_X86_64; tri=x86_64-unknown-linux-gnu ;;
                      aarch64) sha=$STARSHIP_SHA_AARCH64; tri=aarch64-unknown-linux-musl ;;
                      *) sha=; tri= ;; esac
        if [ -z "$sha" ]; then
            skip starship "no pin for $ARCH yet (NOTICE)"
        elif need starship "install $STARSHIP_VERSION into ~/.local/bin"; then
            fetch "https://github.com/starship/starship/releases/download/v$STARSHIP_VERSION/starship-$tri.tar.gz" "$TMP/starship.tgz" "$sha"
            mkdir -p "$HOME/.local/bin"
            tar -xzf "$TMP/starship.tgz" -C "$HOME/.local/bin" starship
            ok starship "$STARSHIP_VERSION"
        fi
    fi
    # Nerd Font
    fontdir="$HOME/.local/share/fonts/JetBrainsMonoNerdFont"
    if [ "$shell" = 0 ]; then
        skip font "$SHELL_OFF"
    elif ls "$fontdir"/*.ttf >/dev/null 2>&1; then
        ok font "JetBrainsMono Nerd Font in $fontdir"
    elif [ -z "$NERDFONT_SHA" ]; then
        skip font "no pin yet (NOTICE)"
    elif need font "install JetBrainsMono Nerd Font $NERDFONT_VERSION"; then
        fetch "https://github.com/ryanoasis/nerd-fonts/releases/download/v$NERDFONT_VERSION/JetBrainsMono.zip" "$TMP/font.zip" "$NERDFONT_SHA"
        mkdir -p "$fontdir"
        unzip -q -o "$TMP/font.zip" -d "$fontdir" 'JetBrainsMonoNerdFont-*.ttf'
        fc-cache -f "$fontdir" >/dev/null 2>&1 || true
        ok font "JetBrainsMono Nerd Font $NERDFONT_VERSION (set it in your terminal)"
    fi
fi
# llama.cpp engine: the pinned release tarball on both OSes (the AI layer,
# always). A build of your own in SPARK_ENGINE_DIR wins; the tarball is
# never fetched over it. The extracted dir carries a one-line `flavour`
# file so `spark check`'s engine row can name it.
engine_flavour
have=$(cat "$ENGINE_DIR/flavour" 2>/dev/null || true)
if [ -z "$have" ] && [ -x "$ENGINE_DIR/llama-server" ] && [ -n "$flavour" ]; then
    # a dir from before the flavour file existed: name it now by what is in
    # it -- the Linux vulkan build ships libggml-vulkan.so (dry-run too: a
    # one-line note beside a binary that is already there is not a change)
    have=$flavour
    if [ "$OS" = Linux ]; then
        if ls "$ENGINE_DIR"/libggml-vulkan.so* >/dev/null 2>&1; then have="ubuntu-vulkan-${flavour##*-}"; else have="ubuntu-${flavour##*-}"; fi
    fi
    echo "$have" > "$ENGINE_DIR/flavour"
fi
if [ "$client" = 1 ]; then
    skip engine "$CLIENT_OF"
elif [ -n "${SPARK_ENGINE_DIR:-}" ] && [ -x "$SPARK_ENGINE_DIR/llama-server" ]; then
    ok engine "your build in $SPARK_ENGINE_DIR (SPARK_ENGINE_DIR)"
elif [ -x "$ENGINE_DIR/llama-server" ] && { [ -z "$sha" ] || [ "$have" = "$flavour" ]; }; then
    ok engine "llama.cpp $LLAMA_VERSION $have"
elif [ -z "$sha" ]; then
    skip engine "no pin for llama.cpp $LLAMA_VERSION $OS/$ARCH ($AI_BUILD) -- set SPARK_ENGINE_DIR to a build of your own"
elif need engine "install llama.cpp $LLAMA_VERSION $flavour$([ -z "$have" ] || echo " (replaces $have: the build here is $AI_BUILD now)")"; then
    fetch "https://github.com/ggml-org/llama.cpp/releases/download/$LLAMA_VERSION/llama-$LLAMA_VERSION-bin-$flavour.tar.gz" "$TMP/llama.tgz" "$sha"
    rm -rf "$ENGINE_DIR"
    mkdir -p "$ENGINE_DIR"
    tar -xzf "$TMP/llama.tgz" -C "$ENGINE_DIR" --strip-components=1
    echo "$flavour" > "$ENGINE_DIR/flavour"
    # macOS Gatekeeper: a curl download carries no quarantine flag, but if
    # one is there the unsigned binaries would be refused; clear it, no sudo
    if [ "$OS" = Darwin ]; then xattr -dr com.apple.quarantine "$ENGINE_DIR" 2>/dev/null || true; fi
    ok engine "llama.cpp $LLAMA_VERSION $flavour"
fi
# micro's spell checker plugin (both OSes; the shell layer)
if [ "$shell" = 0 ]; then
    skip micro-aspell "$SHELL_OFF"
elif [ -d "$HOME/.config/micro/plug/aspell" ]; then
    ok micro-aspell "installed"
elif ! command -v micro >/dev/null 2>&1; then
    skip micro-aspell "micro not installed yet"
elif need micro-aspell "micro -plugin install aspell"; then
    micro -plugin install aspell >/dev/null 2>&1 || true
    [ -d "$HOME/.config/micro/plug/aspell" ] && ok micro-aspell "installed" || skip micro-aspell "plugin install failed (network?)"
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
# the workspace is the shell layer's (the backup row watches it, a template
# names it): a stranger's machine gets no folder it did not ask for
if [ "$shell" = 1 ]; then dirs="$SITE_WORKSPACE $MODELS_DIR"; else dirs="$MODELS_DIR"; skip dir "$SHELL_OFF, $SITE_WORKSPACE"; fi
for d in $dirs "$HOME/.local/bin" "$SPARK_STATE_DIR"; do
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
    ok rc "~${rc#"$HOME"} is spark's own (SITE_SHELL=on)"
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
engine_bin=$(engine_home)
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

# ============================================================ 11. terminal
section terminal
if [ "$shell" = 0 ]; then
    # the palette render, the terminfo and the login/boot noise are the
    # shell layer -- one skip row per block. The console-font row is core
    # (spark font works with the layer off) and runs below either way.
    for r in theme terminfo quiet-login quiet-boot; do skip "$r" "$SHELL_OFF"; done
elif [ "$SITE_THEME" = none ]; then
    skip theme "SITE_THEME=none: your terminal keeps its colours"
else
    theme_load "$REPO"
    want=$(for k in $THEME_KEYS; do eval "printf '%s=%s\n' $k \"\$$k\""; done
           [ -z "${THEME_LOGO:-}" ] || printf 'THEME_LOGO=%s\n' "$THEME_LOGO")
    # console-colors (the Linux VT palette) has one writer: spark theme /
    # spark setup (lib/spark/theme.py write_runtime); this row only notes it
    cc=""; [ -f "$SPARK_CONFIG_DIR/console-colors" ] && cc=" + console-colors"
    if [ -f "$SPARK_CONFIG_DIR/theme.env" ] && [ "$(cat "$SPARK_CONFIG_DIR/theme.env")" = "$want" ]; then
        ok theme "$SITE_THEME -> $SPARK_CONFIG_DIR/theme.env$cc"
    elif need theme "write $SPARK_CONFIG_DIR/theme.env ($SITE_THEME)"; then
        mkdir -p "$SPARK_CONFIG_DIR"; printf '%s\n' "$want" > "$SPARK_CONFIG_DIR/theme.env"; ok theme "$SITE_THEME$cc"
    fi
    if [ "$OS" = Darwin ] && [ -x "$HOME/.local/bin/spark" ]; then
        if [ "$MODE" = dry ]; then "$HOME/.local/bin/spark" theme profile --dry-run | sed 's/^/       /' || true
        else "$HOME/.local/bin/spark" theme profile | sed 's/^/       /' || true; fi
    fi
fi
if [ "$shell" = 0 ]; then
    :   # skipped above
elif infocmp -1x tmux-256color 2>/dev/null | grep -q 'kUP='; then
    ok terminfo "tmux-256color knows modified arrow keys"
elif [ "$OS" = Darwin ]; then
    nc=$(brew --prefix ncurses 2>/dev/null || true)
    if [ ! -x "$nc/bin/infocmp" ]; then skip terminfo "Homebrew ncurses not installed yet"
    elif need terminfo "compile tmux-256color from Homebrew ncurses into ~/.terminfo"; then
        "$nc/bin/infocmp" -x tmux-256color > "$TMP/tmux.ti"
        tic -x -o "$HOME/.terminfo" "$TMP/tmux.ti"
        ok terminfo "compiled into ~/.terminfo"
    fi
else
    skip terminfo "tmux-256color lacks kUP here; install a newer ncurses-term (Debian 13's is fine)"
fi
# the text console's font (console-setup), when chosen: core, not the
# shell layer -- spark font sets SITE_FONT_FACE with the layer off too
if [ "$OS" = Darwin ]; then
    skip console "macOS: the font is in the Terminal.app profile (spark theme profile)"
elif [ -z "$SITE_FONT_FACE" ]; then
    skip console "SITE_FONT_FACE unset: the console keeps its font"
else
    size=${SITE_FONT_SIZE:-16x32}
    cur=$(sed -n 's/^FONTFACE="\{0,1\}\([^"]*\)"\{0,1\}$/\1/p; s/^FONTSIZE="\{0,1\}\([^"]*\)"\{0,1\}$/\1/p' /etc/default/console-setup 2>/dev/null | paste -sd' ' -)
    if [ "$cur" = "$SITE_FONT_FACE $size" ]; then ok console "$SITE_FONT_FACE $size"
    elif need console "set $SITE_FONT_FACE $size in /etc/default/console-setup (sudo)"; then
        as_root sed -i "s/^FONTFACE=.*/FONTFACE=\"$SITE_FONT_FACE\"/; s/^FONTSIZE=.*/FONTSIZE=\"$size\"/" /etc/default/console-setup
        as_root setupcon --force 2>/dev/null || true
        ok console "$SITE_FONT_FACE $size"
    fi
fi
if [ "$shell" = 0 ]; then
    :   # quiet-login and quiet-boot skipped above
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
        as_root truncate -s 0 /etc/motd
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
