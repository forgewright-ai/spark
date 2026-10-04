#!/bin/sh
# spark tests/install_test.sh -- install.sh against a throwaway HOME.
# Proves contract 2: the row shapes, link/render/back-up semantics,
# idempotence, and that shell syntax in site.env is refused. bootstrap's
# rows on every shape, and the hand-back of what an older spark painted.
set -eu
REPO=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
# the hand-back's files, pinned: the machine underneath is never read (a
# runner's own /etc, a developer's Terminal.app preferences). 9c pins its
# own fixture over these.
for k in CONSOLE_UNIT RC_LOCAL CONSOLE_SETUP VCONSOLE RCCONF MOTD ISSUE UNAME_MOTD GRUB_DROPIN DEFAULT_GRUB GETTY_CONF MKINITCPIO_D CMDLINE_DROPIN; do
    export "SPARK_ETC_$k=$T/no-etc/$k"
done
export SPARK_TERMINAL_DOMAIN="$T/no-terminal.plist"
export HOME="$T/home" XDG_CONFIG_HOME="$T/home/.config"
mkdir -p "$HOME/.config/spark"
# a site.env with nothing chosen: every default applies
: > "$HOME/.config/spark/site.env"
fail=0
ok() { printf '  ok   %s\n' "$1"; }
bad() { printf '  FAIL %s\n' "$1"; fail=1; }
run() { sh "$REPO/install.sh" "$@" 2>&1; }

echo "install_test: $T"

# 1. dry-run on an empty HOME: only
#    `would` rows, nothing created
out=$(run --dry-run)
if printf '%s\n' "$out" | grep -qE '^(ok|link|render|back up) '; then bad "dry-run printed a non-would row"; else ok "dry-run prints only would rows"; fi
printf '%s\n' "$out" | grep -q '^would link .*\.config/spark/spark.env.example$' && ok "would link a home/ file" || bad "would link"
printf '%s\n' "$out" | grep -q '^would .*\.gitconfig$' && bad ".gitconfig announced" || ok "no .gitconfig row (spark renders none)"
[ ! -e "$HOME/.config/spark/spark.env.example" ] && ok "dry-run created nothing" || bad "dry-run wrote a file"
printf '%s\n' "$out" | tail -1 | grep -qE '^[0-9]+ to do$' && ok "dry-run summary line" || bad "summary line"

# 2a. apply the AI layer: the widgets, the banner, spark.env.example and
#     the units are linked or rendered; the rc files and the shell's
#     templates are not touched; the second run is Nothing to do
run >/dev/null
for f in .config/spark/spark.env.example .config/spark/widget.bash .config/spark/widget.zsh .config/spark/hook.bash .config/spark/hook.zsh .config/spark/banner; do
    [ -L "$HOME/$f" ] && ok "AI layer: $f is a symlink" || bad "AI layer: $f not linked"
done
for f in .bashrc .bash_profile .zshrc .zprofile .config/micro .gitconfig .tmux.conf .config/btop .config/starship.toml; do
    [ ! -e "$HOME/$f" ] && [ ! -L "$HOME/$f" ] || bad "$f was installed"
done
ok "no rc file, no dotfile of another tool"
case $(uname -s) in
    Darwin) [ -f "$HOME/.config/spark/launchd/spark.serve.plist" ] && ok "plists rendered on macOS" || bad "plist"
            [ -f "$HOME/.config/spark/launchd/spark.forge.plist" ] && ok "spark.forge.plist rendered too" || bad "forge plist"
            grep -q 'forge.log' "$HOME/.config/spark/launchd/spark.forge.plist" && ok "the forge logs to forge.log" || bad "forge plist log path" ;;
    *)      [ ! -e "$HOME/.config/spark/launchd" ] && ok "no plists on Linux" || bad "plist on Linux"
            [ -L "$HOME/.config/systemd/user/spark-serve.service" ] && ok "spark-serve.service linked" || bad "serve unit"
            [ -L "$HOME/.config/systemd/user/spark-forge.service" ] && ok "spark-forge.service linked too" || bad "forge unit" ;;
esac
out=$(run)
[ "$(printf '%s\n' "$out" | tail -1)" = "Nothing to do" ] && ok "AI layer, second run: Nothing to do" || bad "not idempotent: $(printf '%s\n' "$out" | grep -v '^ok' | head -3)"

# 2c. a client (SITE_AI_MODEL=none + SITE_PEER_AI_URL): the widgets and the
#     hooks as before, no unit and no plist, on either OS
C=$T/client; mkdir -p "$C/.config/spark"
printf 'SITE_AI_MODEL=none\nSITE_PEER_AI_URL=http://192.0.2.10:8081\n' > "$C/.config/spark/site.env"
out=$(HOME=$C XDG_CONFIG_HOME=$C/.config sh "$REPO/install.sh" --dry-run 2>&1)
printf '%s\n' "$out" | grep -q '^would link .*\.config/spark/widget\.zsh$' && ok "client: would link the widget" || bad "client: widget"
if printf '%s\n' "$out" | grep -qE 'spark[-.](serve|forge|check)'; then bad "client: a unit or plist announced: $(printf '%s\n' "$out" | grep -E 'spark[-.](serve|forge|check)' | head -1)"; else ok "client: no unit, no plist"; fi

# 3. a regular file in the way is backed up, never overwritten; so is a
#    symlink that points outside the repo (the link itself moves to .bak);
#    a stale symlink into the repo (an older layout of ours) is replaced
rm "$HOME/.config/spark/spark.env.example"
echo mine > "$HOME/.config/spark/spark.env.example"
out=$(run --dry-run)
printf '%s\n' "$out" | grep -q '^would back up' && ok "dry-run announces the back-up" || bad "no back-up row"
run >/dev/null
[ "$(cat "$HOME/.config/spark/spark.env.example.bak")" = mine ] && ok "content preserved in .bak" || bad "back-up lost content"
[ -L "$HOME/.config/spark/spark.env.example" ] && ok "then linked" || bad "not linked after back-up"
# a second file in the way while the first .bak stands: stamped, the first survives
rm "$HOME/.config/spark/spark.env.example"; echo again > "$HOME/.config/spark/spark.env.example"
out=$(run)
printf '%s\n' "$out" | grep -q '^back up .*spark\.env\.example -> .*\.bak\.[0-9][0-9]*$' \
    && ok "a second back-up is stamped .bak.<epoch>" || bad "second back-up row: $(printf '%s\n' "$out" | grep '^back up' || echo none)"
[ "$(cat "$HOME/.config/spark/spark.env.example.bak")" = mine ] && ok "the first .bak survives" || bad "the first .bak was overwritten"
rm -f "$HOME"/.config/spark/spark.env.example.bak.[0-9]*
rm "$HOME/.config/spark/spark.env.example" "$HOME/.config/spark/spark.env.example.bak"
mkdir -p "$T/elsewhere"; echo theirs > "$T/elsewhere/file"
ln -s "$T/elsewhere/file" "$HOME/.config/spark/spark.env.example"
out=$(run --dry-run)
printf '%s\n' "$out" | grep -q '^would back up .*spark.env.example$' && ok "dry-run: a foreign symlink would be backed up" || bad "foreign symlink: no would back up row"
[ "$(readlink "$HOME/.config/spark/spark.env.example")" = "$T/elsewhere/file" ] && ok "dry-run left the foreign symlink" || bad "dry-run touched the foreign symlink"
run >/dev/null
[ -L "$HOME/.config/spark/spark.env.example.bak" ] && [ "$(readlink "$HOME/.config/spark/spark.env.example.bak")" = "$T/elsewhere/file" ] \
    && ok "the foreign symlink itself moved to .bak" || bad "foreign symlink not backed up"
[ "$(readlink "$HOME/.config/spark/spark.env.example")" = "$REPO/home/.config/spark/spark.env.example" ] && ok "then linked into the repo" || bad "not linked after the foreign symlink"
rm "$HOME/.config/spark/spark.env.example" "$HOME/.config/spark/spark.env.example.bak"
ln -s "$REPO/home/.config/spark/no-such-file" "$HOME/.config/spark/spark.env.example"
run >/dev/null
[ ! -e "$HOME/.config/spark/spark.env.example.bak" ] && [ ! -L "$HOME/.config/spark/spark.env.example.bak" ] \
    && [ "$(readlink "$HOME/.config/spark/spark.env.example")" = "$REPO/home/.config/spark/spark.env.example" ] \
    && ok "a stale symlink into the repo is replaced, no .bak" || bad "stale repo symlink"

# 4. shell syntax in site.env (site_load, both scripts) is refused
printf 'SITE_NAME=x; rm -rf /\n' > "$HOME/.config/spark/site.env"
if run >/dev/null 2>&1; then bad "shell syntax in site.env accepted"; else ok "shell syntax in site.env refused"; fi
: > "$HOME/.config/spark/site.env"

# 4b. the keys v1.69 removed (SITE_QUIET_START, SITE_QUIET_AUDIO and the
#     three SPARK_LOOK_* parts), left in an older file: both scripts and
#     spark itself load it, and nothing reads them (both OSes)
printf 'SITE_QUIET_START=yes\nSITE_QUIET_AUDIO=yes\n' > "$HOME/.config/spark/site.env"
printf 'SPARK_LOOK_MOTION=on\nSPARK_LOOK_COLOUR=on\nSPARK_LOOK_WORDS=off\n' > "$HOME/.config/spark/spark.env"
if run --dry-run >/dev/null 2>&1; then ok "install.sh loads an old site.env and spark.env holding the removed keys"; else bad "install.sh refused an old file with the removed keys"; fi
out=$(python3 "$REPO/bin/spark" look 2>&1) && printf '%s\n' "$out" | grep -qE '^look +off( |$)' \
    && ok "spark look loads them too, and reads SPARK_LOOK alone (off)" || bad "spark look with the removed keys: $out"
: > "$HOME/.config/spark/site.env"
rm -f "$HOME/.config/spark/spark.env"

# 7. bootstrap --dry-run with SITE_HEADLESS=yes announces the headless rows
#    (contract 1: would/skip, a count line, never sudo -- a sudo on PATH that
#    shouts proves it); SITE_HEADLESS=no leaves sleep alone
mkdir -p "$T/bin"; printf '#!/bin/sh\necho "SUDO CALLED: $*" >&2; exit 97\n' > "$T/bin/sudo"; chmod +x "$T/bin/sudo"
printf 'SITE_HEADLESS=yes\nSITE_AI_MODEL=none\n' > "$HOME/.config/spark/site.env"
out=$(PATH="$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (headless) failed: $(printf '%s\n' "$out" | tail -3)"
case $(uname -s) in Darwin) rows="daemons sleep" ;; *) rows="sleep lid" ;; esac
for r in $rows; do
    printf '%s\n' "$out" | grep -qE "^(ok|would|skip) +$r " && ok "headless dry-run names $r" || bad "no $r row in the headless dry-run"
done
printf '%s\n' "$out" | grep -qE '^(would|skip) +(daemons|lid) ' && ok "headless dry-run only announces (would/skip)" || bad "headless dry-run applied something: $(printf '%s\n' "$out" | grep -E '^ok +(daemons|lid)')"
printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "dry-run called sudo" || ok "dry-run never called sudo"
printf '%s\n' "$out" | tail -1 | grep -qE '^([0-9]+ to do|Nothing to do)$' && ok "headless dry-run ends with a count line" || bad "no count line"
printf '%s\n' "$out" | grep -qE '^skip +engine +no model chosen -- spark model NAME' && ok "no model chosen: the engine row skips (nothing to run it for)" || bad "engine row with SITE_AI_MODEL=none: $(printf '%s\n' "$out" | grep -E ' engine ' | head -1)"
# the rc row (the core hook): a throwaway rc file without the line is a
# `would`; with the line appended it is ok; an unknown login shell is a todo
case $(uname -s) in Darwin) SHELL=/bin/zsh; rc=.zshrc ;; *) SHELL=/bin/bash; rc=.bashrc ;; esac
export SHELL
rm -f "$HOME/$rc"; : > "$HOME/$rc"
out=$(PATH="$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (rc) failed"
printf '%s\n' "$out" | grep -qE "^would +rc +add one line to ~/$rc\$" && ok "rc: an rc file without the line: would rc" || bad "rc: no would row: $(printf '%s\n' "$out" | grep -E ' rc ')"
[ ! -s "$HOME/$rc" ] && ok "rc: dry-run left the rc file empty" || bad "rc: dry-run wrote the rc file"
case $rc in .zshrc) line='[[ -r ~/.config/spark/hook.zsh ]] && source ~/.config/spark/hook.zsh   # spark: the AI at the prompt' ;;
            *) line='[ -r ~/.config/spark/hook.bash ] && . ~/.config/spark/hook.bash   # spark: the AI at the prompt' ;; esac
printf '\n%s\n' "$line" >> "$HOME/$rc"
out=$(PATH="$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (rc hooked) failed"
printf '%s\n' "$out" | grep -qE "^ok +rc +~/$rc sources the hook\$" && ok "rc: with the line: ok rc sources the hook" || bad "rc: no ok row: $(printf '%s\n' "$out" | grep -E ' rc ')"
out=$(SHELL=/usr/local/bin/fish PATH="$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (fish) failed"
printf '%s\n' "$out" | grep -qE '^todo +rc +shell fish' && ok "rc: an unknown login shell is a todo naming it" || bad "rc: fish: $(printf '%s\n' "$out" | grep -E ' rc ')"
printf '%s\n' "$out" | grep -qE '^[a-z]+ +(theme|console|vt-palette|quiet-login|quiet-boot) ' && bad "a row of the look survives: $(printf '%s\n' "$out" | grep -E ' (theme|console|vt-palette|quiet-login|quiet-boot) ' | head -1)" || ok "no theme, console, vt-palette or quiet row: the look left core"
printf '%s\n' "$out" | grep -qE "^skip +handback +nothing of an older spark's look is left here" && ok "the handback row: nothing left here, a skip" || bad "handback row: $(printf '%s\n' "$out" | grep -E ' handback ' | head -1)"
printf '%s\n' "$out" | grep -qE '^skip +hostname +SITE_SET_HOSTNAME=no' && ok "the hostname row is core (identity), its skip names its key" || bad "hostname row: $(printf '%s\n' "$out" | grep -E ' hostname ' | head -1)"
printf '%s\n' "$out" | grep -qE ' micro-aspell ' && bad "a micro-aspell row survives (spark ships no app)" || ok "no micro-aspell row: spark installs no editor"
printf '%s\n' "$out" | grep -qE "^would +dir +mkdir .*/projects" && bad "the workspace folder would be made" || ok "no workspace folder for a new user"
[ "$(uname -s)" = Darwin ] && { printf '%s\n' "$out" | grep -qE '^ok +packages +nothing to install' && ok "macOS: packages row is ok, nothing to install" || bad "macOS packages row"; }
[ -z "$(sh "$REPO/bootstrap.sh" --list-packages | grep -E '^(tmux|starship|bat|eza|fzf|btop)$')" ] && ok "--list-packages has no shell tool (spark installs none)" || bad "--list-packages lists a shell tool"
[ -z "$(sh "$REPO/bootstrap.sh" --list-packages | grep -E '^(micro|aspell|aspell-en|shellcheck)$')" ] && ok "no editor, no contributor tool in --list-packages" || bad "--list-packages still lists micro/aspell/shellcheck"
# the sh twin's precedence matches python: a key in BOTH files -- the
# later file of config.py's update order (spark.env) wins in lib/env.sh too
mkdir -p "$T/prec/spark"
printf 'SPARK_THREADS=1\n' > "$T/prec/spark/site.env"
printf 'SPARK_THREADS=7\n' > "$T/prec/spark/spark.env"
got=$(env -i PATH="$PATH" HOME="$HOME" XDG_CONFIG_HOME="$T/prec" sh -c '. "$0/lib/env.sh"; site_load; printf %s "$SPARK_THREADS"' "$REPO")
[ "$got" = 7 ] && ok "env.sh: a key in both files -- spark.env wins, as config.py has it" || bad "env.sh precedence: got '$got'"

# an older engine pin beside the current one is offered for removal, named
mkdir -p "$HOME/.local/share/spark/engine/llama.cpp-b1"
out=$(PATH="$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (old pin) failed"
printf '%s\n' "$out" | grep -qE '^would +engine-old +remove older engine pins:.*llama\.cpp-b1' && ok "an older engine pin: would engine-old, naming it" || bad "engine-old row: $(printf '%s\n' "$out" | grep -E ' engine-old ' | head -1)"
rm -rf "$HOME/.local/share/spark/engine"
# the v1.10 migration row: links an older install.sh made into this repo's
# home/.config/micro are handed back once (dry-run says would; apply is
# proven by hand -- it needs a real bootstrap)
mkdir -p "$HOME/.config/micro/plug/spark/help"
ln -s "$REPO/home/.config/micro/plug/spark/spark.lua" "$HOME/.config/micro/plug/spark/spark.lua"
ln -s "$REPO/home/.config/micro/bindings.json" "$HOME/.config/micro/bindings.json"
out=$(PATH="$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (old plugin links) failed"
printf '%s\n' "$out" | grep -qE '^would +micro +the plugin moved to github.com/forgewright-ai/spark-micro' && ok "old plugin links: the micro row would hand them back" || bad "no micro row for old plugin links: $(printf '%s\n' "$out" | grep -E ' micro ' | head -1)"
rm -rf "$HOME/.config/micro/plug" "$HOME/.config/micro/bindings.json"
out=$(PATH="$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run failed"
printf '%s\n' "$out" | grep -qE ' micro ' && bad "a micro row with nothing to hand back" || ok "no old plugin links: no micro row"
printf 'SITE_HEADLESS=no\nSITE_AI_MODEL=none\n' > "$HOME/.config/spark/site.env"
out=$(PATH="$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run failed"
printf '%s\n' "$out" | grep -qE '^(skip|would) +sleep ' && ok "SITE_HEADLESS=no: sleep row is skip (or would undo)" || bad "no sleep row for SITE_HEADLESS=no"
[ "$(uname -s)" = Darwin ] || { printf '%s\n' "$out" | grep -qE '^skip +(linger|systemd) ' && ok "SITE_HEADLESS=no: linger is skipped (or no user systemd session)" || bad "linger row with SITE_HEADLESS=no"; }
printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "dry-run called sudo" || ok "dry-run never called sudo (workstation)"
# an rc file that is a symlink of yours (a dotfiles folder) is a file like
# any other: the rc row would append the hook line through the link when
# the target lacks it, and finds it there when it has it -- no migration
# row, no hand-back
case $(uname -s) in Darwin) rc=.zshrc; hook='[[ -r ~/.config/spark/hook.zsh ]] && source ~/.config/spark/hook.zsh   # spark: the AI at the prompt' ;;
                     *) rc=.bashrc; hook='[ -r ~/.config/spark/hook.bash ] && . ~/.config/spark/hook.bash   # spark: the AI at the prompt' ;;
esac
mkdir -p "$T/dotfiles"
printf '# my rc, kept in a dotfiles folder\n' > "$T/dotfiles/$rc"
ln -sfn "$T/dotfiles/$rc" "$HOME/$rc"
out=$(PATH="$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (rc symlink) failed"
printf '%s\n' "$out" | grep -qE ' shell-moved ' && bad "a shell-moved row survives" || ok "no migration row: a symlinked rc is yours"
printf '%s\n' "$out" | grep -qE "^would +rc +add one line to ~/$rc" && ok "rc: a symlinked rc without the line would get it appended" || bad "rc: symlink: $(printf '%s\n' "$out" | grep -E ' rc ')"
printf '\n%s\n' "$hook" >> "$T/dotfiles/$rc"
out=$(PATH="$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (rc symlink, hooked) failed"
printf '%s\n' "$out" | grep -qE "^ok +rc +~/$rc sources the hook" && ok "rc: a symlinked rc that has the line is found through the link" || bad "rc: symlink hooked: $(printf '%s\n' "$out" | grep -E ' rc ')"
printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "dry-run called sudo (rc symlink)" || ok "dry-run never called sudo (rc symlink)"
rm -f "$HOME/$rc"

# 8. bootstrap --list-models names both roles' picks (the choosing rule;
#    lib/spark engine.chosen_rows is the twin, tests/smoke.py pins it the
#    same way). SPARK_MEM_TOTAL_GB pins the budget; a uname stub pins the
#    Linux rule on either OS (on macOS the build is metal whatever the key
#    says) and SPARK_SYSFS_DRM the GPU probe. 18 GB -> 10 GB budget: auto
#    (tested, open-license rows only) takes the first row in the list
#    that fits AND stays under the build's speed cap -- 3 GB files on cpu,
#    6 GB on vulkan, a row of 4B working parameters counting as small:
#    gemma4-e4b on both. With the ember auto: the smallest row + the
#    first usable in the list that fits beside it.
#    SITE_AI_BUILD=auto (the default) = vulkan when a DRM device reports
#    VRAM, else cpu. A name is never second-guessed, and is looked up in
#    the whole list and yours, tested or not, any license.
#    6 GB -> 3 GB budget: the smallest row alone, no ember, nothing held
#    back. The list holds no non-open row: one of yours stands in.
mkdir -p "$T/os" "$T/drm/card0/device" "$T/nodrm"
printf '#!/bin/sh\ncase ${1:-} in -s) echo Linux ;; -m) echo x86_64 ;; *) exec /usr/bin/uname "$@" ;; esac\n' > "$T/os/uname"
chmod +x "$T/os/uname"
echo 8589934592 > "$T/drm/card0/device/mem_info_vram_total"
lm() { env PATH="$T/os:$PATH" SPARK_SYSFS_DRM="$T/nodrm" "$@" sh "$REPO/bootstrap.sh" --list-models 2>&1; }
printf 'SITE_AI_MODEL=auto\nSITE_EMBER_MODEL=auto\n' > "$HOME/.config/spark/site.env"
out=$(lm SPARK_MEM_TOTAL_GB=18 SITE_AI_BUILD=cpu) || bad "--list-models failed"
printf '%s\n' "$out" | grep -qx 'spark: qwen3-5-2b' && ok "18 GB cpu: spark is the smallest row" || bad "18 GB cpu spark line"
printf '%s\n' "$out" | grep -qx 'ember: qwen3-4b' && ok "18 GB cpu: ember is the first in the list under the 3 GB cap beside it" || bad "18 GB cpu ember line: $(printf '%s\n' "$out" | grep '^ember')"
printf '%s\n' "$out" | grep -qE '^\*  ?qwen3-5-2b ' && ok "spark pick marked *" || bad "* mark"
printf '%s\n' "$out" | grep -qE '^\+  ?qwen3-4b ' && ok "ember pick marked +" || bad "+ mark"
out=$(lm SPARK_MEM_TOTAL_GB=18 SITE_AI_BUILD=vulkan) || bad "--list-models failed"
printf '%s\n' "$out" | grep -qx 'ember: qwen3-4b' && ok "18 GB vulkan: ember is the first in the list that fits beside it" || bad "18 GB vulkan ember line"
printf 'SITE_AI_MODEL=auto\nSITE_EMBER_MODEL=none\n' > "$HOME/.config/spark/site.env"
out=$(lm SPARK_MEM_TOTAL_GB=18 SITE_AI_BUILD=cpu) || bad "--list-models failed"
printf '%s\n' "$out" | grep -qx 'spark: gemma4-e4b' && ok "18 GB cpu: gemma4-e4b, its 4B working parameters pass the 3 GB cap" || bad "18 GB cpu spark line: $(printf '%s\n' "$out" | grep '^spark')"
printf '%s\n' "$out" | grep -q '^auto picks files under' && bad "18 GB cpu: a cap note with nothing held back" || ok "18 GB cpu: nothing held back, no cap note"
printf '%s\n' "$out" | head -2 | awk 'length > 80 { bad = 1 } END { exit bad }' && ok "the header fits 80 columns" || bad "a header line is wider than 80"
printf '%s\n' "$out" | head -1 | grep -q ', cpu$' && ok "the header names the cpu build" || bad "header: $(printf '%s\n' "$out" | head -1)"
# a client (none + a peer): the rows, no budget, never this machine's RAM
printf 'SITE_AI_MODEL=none\nSITE_PEER_AI_URL=http://192.0.2.10:8081\n' > "$HOME/.config/spark/site.env"
out=$(lm SPARK_MEM_TOTAL_GB=24 SITE_AI_BUILD=cpu) || bad "--list-models failed on a client"
printf '%s\n' "$out" | head -1 | grep -q '^this machine is a client of http://192.0.2.10:8081' && ok "a client's --list-models names the peer" || bad "client header: $(printf '%s\n' "$out" | head -1)"
printf '%s\n' "$out" | grep -q '24 GB\|budget\| fits$\|^spark:\|^ember:' && bad "a client's --list-models printed a local budget or a pick" || ok "a client's --list-models has no budget, verdict or pick"
printf '%s\n' "$out" | grep -qE '^   gemma4-e4b ' && ok "a client's --list-models still lists the rows" || bad "client rows: $(printf '%s\n' "$out" | sed -n 3p)"
printf 'SITE_AI_MODEL=auto\nSITE_EMBER_MODEL=none\n' > "$HOME/.config/spark/site.env"
# 19 GB -> 11 GB budget: qwen3-14b (11 GB) fits the budget, but the
# list's order is the priority: gemma4-e4b comes first, it is under the
# 6 GB vulkan cap, and nothing was held back, so no note.
out=$(lm SPARK_MEM_TOTAL_GB=19 SITE_AI_BUILD=vulkan) || bad "--list-models failed"
printf '%s\n' "$out" | grep -qx 'spark: gemma4-e4b' && ok "19 GB vulkan: the first in the list that fits (gemma4-e4b)" || bad "19 GB vulkan spark line"
printf '%s\n' "$out" | grep -q '^auto picks files under' && bad "19 GB vulkan: a cap note with nothing held back" || ok "19 GB vulkan: nothing held back, no cap note"
out=$(lm SPARK_MEM_TOTAL_GB=18 SPARK_SYSFS_DRM="$T/drm") || bad "--list-models failed"
printf '%s\n' "$out" | head -1 | grep -q ', vulkan$' && ok "SITE_AI_BUILD=auto: vulkan when a DRM device reports VRAM" || bad "auto with a GPU: $(printf '%s\n' "$out" | head -1)"
printf '%s\n' "$out" | grep -qx 'spark: gemma4-e4b' && ok "auto with a GPU picks as vulkan" || bad "auto with a GPU spark line"
# SITE_AI_BUDGET=30 drops the budget to 5 GB (18 * 30 / 100): qwen3-4b
# (5 GB) still fits, gemma4-e4b (8 GB) no longer does -- it would at the
# default 60 % (the case just above); the header names the percent too.
out=$(lm SPARK_MEM_TOTAL_GB=18 SITE_AI_BUILD=vulkan SITE_AI_BUDGET=30) || bad "--list-models failed"
printf '%s\n' "$out" | grep -qx 'spark: qwen3-4b' && ok "SITE_AI_BUDGET=30: the budget drops to 5 GB, gemma4-e4b no longer fits" || bad "SITE_AI_BUDGET=30 spark line: $(printf '%s\n' "$out" | grep '^spark')"
printf '%s\n' "$out" | head -1 | grep -q 'budget 5 GB (30%)' && ok "the header names the SITE_AI_BUDGET percent" || bad "header: $(printf '%s\n' "$out" | head -1)"
out=$(lm SPARK_MEM_TOTAL_GB=18) || bad "--list-models failed"
printf '%s\n' "$out" | head -1 | grep -q ', cpu$' && ok "SITE_AI_BUILD=auto: cpu with no GPU in sysfs" || bad "auto without a GPU: $(printf '%s\n' "$out" | head -1)"
printf '%s\n' "$out" | grep -qx 'spark: gemma4-e4b' && ok "auto without a GPU picks as cpu" || bad "auto without a GPU spark line"
out=$(lm SPARK_MEM_TOTAL_GB=18 SITE_AI_BUILD=cpu SITE_AI_MODEL=qwen3-14b) || bad "--list-models failed"
printf '%s\n' "$out" | grep -qx 'spark: qwen3-14b' && ok "a named model is never second-guessed" || bad "named model line"
printf '%s\n' "$out" | grep -q '^auto picks files under' && bad "a name printed the cap note" || ok "a name: no cap note"
# a name is looked up in the whole list, tested or not: an untested row
# and a non-open-license row, picked by name for the spark role
out=$(lm SPARK_MEM_TOTAL_GB=18 SITE_AI_BUILD=cpu SITE_AI_MODEL=gemma4-e2b) || bad "--list-models failed"
printf '%s\n' "$out" | grep -qx 'spark: gemma4-e2b' && ok "a named untested row is picked for spark too" || bad "named untested row: $(printf '%s\n' "$out" | grep '^spark')"
( umask 077; printf '%s\n' 'MODEL_GEMMA3_12B="google_gemma-3-12b-it-Q4_K_M.gguf https://huggingface.co/bartowski/google_gemma-3-12b-it-GGUF/resolve/main/google_gemma-3-12b-it-Q4_K_M.gguf 7300575264 fc57f67efa46d711c346e587cbef7d049e95f3df8db2eb2271153343ef0acc7b 9"' 'MODEL_GEMMA3_12B_LICENSE="Gemma-Terms-of-Use https://ai.google.dev/gemma/terms"' > "$HOME/.config/spark/models.env" )
out=$(lm SPARK_MEM_TOTAL_GB=18 SITE_AI_BUILD=cpu SITE_AI_MODEL=gemma3-12b) || bad "--list-models failed"
printf '%s\n' "$out" | grep -qx 'spark: gemma3-12b' && ok "a named non-open row is picked for spark too" || bad "named non-open row: $(printf '%s\n' "$out" | grep '^spark')"
rm -f "$HOME/.config/spark/models.env"
out=$(lm SPARK_MEM_TOTAL_GB=6 SITE_AI_BUILD=cpu) || bad "--list-models failed"
printf '%s\n' "$out" | grep -qx 'spark: qwen3-5-2b' && ok "6 GB: the smallest row alone" || bad "6 GB spark line"
printf '%s\n' "$out" | grep -qx 'ember: none' && ok "6 GB: no ember" || bad "6 GB ember line"
printf '%s\n' "$out" | grep -q '^auto picks files under' && bad "6 GB: a cap note with nothing held back" || ok "6 GB: nothing held back, no cap note"
# the package family is read from os-release, pinned like the kernel line:
# on a macOS dev box the uname stub says Linux and the family must be said too
printf 'ID=ubuntu\nID_LIKE=debian\nPRETTY_NAME="Ubuntu fixture"\n' > "$T/os-release-debian"
env PATH="$T/os:$PATH" SPARK_SYSFS_DRM="$T/drm" SPARK_OS_RELEASE="$T/os-release-debian" sh "$REPO/bootstrap.sh" --list-packages | grep -qx libvulkan1 && ok "auto with a GPU: --list-packages adds the vulkan libraries" || bad "vulkan packages missing with a GPU"
env PATH="$T/os:$PATH" SPARK_SYSFS_DRM="$T/nodrm" SPARK_OS_RELEASE="$T/os-release-debian" sh "$REPO/bootstrap.sh" --list-packages | grep -qx libvulkan1 && bad "no GPU: --list-packages still adds the vulkan libraries" || ok "auto without a GPU: no vulkan libraries"
# this OS as it is: macOS is metal whatever the key says, Linux cpu or
# vulkan. 24 GB -> 14 GB budget: gemma4-e4b, the first in the list that
# fits, on metal (no cap there) and on cpu (4B working parameters pass).
out=$(SPARK_MEM_TOTAL_GB=24 SITE_AI_BUILD=cpu sh "$REPO/bootstrap.sh" --list-models 2>&1) || bad "--list-models failed"
case $(uname -s) in
    Darwin) printf '%s\n' "$out" | head -1 | grep -q ', metal$' && printf '%s\n' "$out" | grep -qx 'spark: gemma4-e4b' && ok "macOS: metal, the key ignored, the first that fits" || bad "macOS header/pick: $(printf '%s\n' "$out" | head -1)" ;;
    *) printf '%s\n' "$out" | head -1 | grep -qE ', (cpu|vulkan)$' && ok "Linux: the header names cpu or vulkan" || bad "Linux header: $(printf '%s\n' "$out" | head -1)" ;;
esac

# 9. WSL 2 (Linux only: the rows are Linux's): a kernel line naming
#    microsoft makes a hand-set SITE_HEADLESS=yes a todo -- never a
#    systemctl mask, no sudo
if [ "$(uname -s)" != Darwin ]; then
    printf 'Linux version 6.6.87.2-microsoft-standard-WSL2 (root@w) #1 SMP\n' > "$T/version-wsl"
    printf 'SITE_HEADLESS=yes\nSITE_AI_MODEL=none\n' > "$HOME/.config/spark/site.env"
    out=$(SPARK_PROC_VERSION="$T/version-wsl" PATH="$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (WSL 2) failed: $out"
    printf '%s\n' "$out" | grep -qE '^todo +headless +WSL 2' && ok "WSL 2: SITE_HEADLESS=yes is a todo, never a mask" || bad "WSL 2 headless: $(printf '%s\n' "$out" | grep -E ' headless | sleep ' | head -2)"
    printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "WSL 2 dry-run called sudo" || ok "WSL 2 dry-run: no sudo"
fi

# 9b. spark client URL on a machine that served (Linux): the enabled
#     unit is disabled, its link removed, and the run says the engine
#     that ran here is stopped -- spark serve off would refuse while
#     the unit is loaded, so the promotion to client must do it itself
if [ "$(uname -s)" != Darwin ]; then
    mkdir -p "$HOME/.config/systemd/user" "$T/sysd"
    ln -sf "$REPO/linux/home/.config/systemd/user/spark-serve.service" "$HOME/.config/systemd/user/spark-serve.service"
    cat > "$T/sysd/systemctl" <<'SH'
#!/bin/sh
echo "systemctl $*" >> "$SYSD_LOG"
case "$*" in *is-enabled*spark-serve*) echo enabled ;; *is-enabled*) echo disabled ;; esac
exit 0
SH
    chmod +x "$T/sysd/systemctl"
    out=$(SYSD_LOG="$T/sysd.log" SPARK_NO_APPLY=1 PATH="$T/sysd:$T/bin:$PATH" python3 "$REPO/bin/spark" client http://192.0.2.9:8081 2>&1) \
        || bad "spark client URL failed: $out"
    grep -q -- "--user disable --now spark-serve.service" "$T/sysd.log" 2>/dev/null \
        && ok "client URL: the serve unit is stopped and disabled" || bad "client URL: no disable logged: $(cat "$T/sysd.log" 2>/dev/null | tr '\n' ' ')"
    [ ! -e "$HOME/.config/systemd/user/spark-serve.service" ] && ok "client URL: the unit link is removed" || bad "client URL: the link stayed"
    printf '%s\n' "$out" | grep -q "the engine that ran here is stopped" && ok "client URL: the stop is said" || bad "client URL says nothing: $out"
    printf 'SITE_AI_MODEL=none\n' > "$HOME/.config/spark/site.env"
fi

# 9c. the hand-back (v1.62): what an older spark painted goes back once,
#     through lib/spark/handback.py (bootstrap's handback row, and spark
#     uninstall). A fixture holds every file and mark spark made, on every
#     shape: the palette files, the boot unit and a line of yours in
#     rc.local; the console font's .spark-orig beside console-setup,
#     vconsole.conf and rc.conf; motd and issue with their .orig; the
#     Debian GRUB drop-in; the Arch UKI drop-in and the splash mark; Void's
#     marked lines in GRUB's file, rc.conf and the getty's conf. A dry run
#     names each and never calls sudo. The apply puts each back through a
#     sudo that runs what it is given, and your own lines stay, byte for
#     byte. A stale .orig never overwrites a login file you changed; a
#     failed boot rebuild runs again next time; a failed palette step keeps
#     spark's palette files. A second run, and a machine that never had any
#     of it, say nothing and never call sudo. Both OSes: python, the Linux
#     shape by SPARK_OS.
H=$T/hb; mkdir -p "$H/bin"
printf '#!/bin/sh\n[ "$1" = -n ] && shift\necho "sudo $*" >> "$HBLOG"\nexec "$@"\n' > "$H/bin/sudo"
for c in setvtrgb systemctl update-grub mkinitcpio setupcon setfont; do
    printf '#!/bin/sh\necho "%s${*:+ $*}" >> "$HBLOG"\nexit 0\n' "$c" > "$H/bin/$c"
done
chmod +x "$H"/bin/*
printf 'Linux version 6.12.0-fixture (fixture) #1 SMP\n' > "$H/version"
# hb COMMAND...: the fixture's seams; HBPATH first on PATH ($H/bin by
# default: the sudo that runs; "$T/bin:$H/bin" puts the one that shouts first)
hb() {
    env HOME="$H/home" XDG_CONFIG_HOME="$H/home/.config" XDG_STATE_HOME="$H/home/.local/state" SPARK_OS=Linux SPARK_PROC_VERSION="$H/version" TERM=xterm \
        SPARK_ETC_CONSOLE_UNIT="$H/etc/spark-console.service" SPARK_ETC_RC_LOCAL="$H/etc/rc.local" \
        SPARK_ETC_CONSOLE_SETUP="$H/etc/console-setup" SPARK_ETC_VCONSOLE="$H/etc/vconsole.conf" SPARK_ETC_RCCONF="$H/etc/rc.conf" \
        SPARK_ETC_MOTD="$H/etc/motd" SPARK_ETC_ISSUE="$H/etc/issue" SPARK_ETC_UNAME_MOTD="$H/etc/10-uname" \
        SPARK_ETC_GRUB_DROPIN="$H/etc/zz-spark-quiet.cfg" SPARK_ETC_DEFAULT_GRUB="$H/etc/default-grub" SPARK_ETC_GETTY_CONF="$H/etc/getty-conf" \
        SPARK_ETC_MKINITCPIO_D="$H/etc/mkinitcpio.d" SPARK_ETC_CMDLINE_DROPIN="$H/etc/zz-spark-quiet.conf" \
        PYTHONPATH="$REPO/lib" HBLOG="$H/log" PATH="${HBPATH:-$H/bin}:$PATH" "$@"
}
hb_clean() {
    rm -rf "${H:?}/etc" "${H:?}/home" "${H:?}/log"; mkdir -p "$H/etc/mkinitcpio.d" "$H/home/.config/spark"
    printf 'SITE_AI_MODEL=none\n' > "$H/home/.config/spark/site.env"
    printf 'CHARMAP="UTF-8"\nFONTFACE="Fixed"\nFONTSIZE="8x16"\n' > "$H/etc/console-setup"
    printf 'GRUB_TIMEOUT=5\n' > "$H/etc/default-grub"
    printf 'the distro notice\n' > "$H/etc/motd"; printf 'Debian \\n \\l\n' > "$H/etc/issue"
    printf '#!/bin/sh\n' > "$H/etc/10-uname"; chmod 0755 "$H/etc/10-uname"
}
hb_painted() {
    hb_clean
    printf '\033]P0282828\n' > "$H/home/.config/spark/console-colors"; printf '40\n40\n40\n' > "$H/home/.config/spark/console-colors.rgb"
    printf '[Unit]\n' > "$H/etc/spark-console.service"
    printf '#!/bin/sh\nsetvtrgb %s/.config/spark/console-colors.rgb\n' "$H/home" > "$H/etc/rc.local"
    cp "$H/etc/console-setup" "$H/etc/console-setup.spark-orig"
    printf 'CHARMAP="UTF-8"\nFONTFACE="Terminus"\nFONTSIZE="16x32"\n# mine, after spark\n' > "$H/etc/console-setup"
    printf 'KEYMAP=us\n' > "$H/etc/vconsole.conf.spark-orig"; printf 'KEYMAP=us\nFONT=Terminus\n' > "$H/etc/vconsole.conf"
    printf '#KEYMAP="us"\n#FONT="lat9w-16"\n' > "$H/etc/rc.conf.spark-orig"
    printf '#KEYMAP="us"\nFONT="Terminus"\nTIMEZONE="UTC"\nmsg() { :; } #spark-quiet#\n' > "$H/etc/rc.conf"
    mv "$H/etc/motd" "$H/etc/motd.orig"; : > "$H/etc/motd"; chmod 0644 "$H/etc/10-uname"
    mv "$H/etc/issue" "$H/etc/issue.orig"; printf '\033[?25h' > "$H/etc/issue"
    printf 'GRUB_TIMEOUT=0\n' > "$H/etc/zz-spark-quiet.cfg"
    printf 'GRUB_TIMEOUT=0 #spark-quiet#\n' >> "$H/etc/default-grub"
    printf 'GETTY_ARGS="--noclear" # caf\351\nGETTY_ARGS= #spark-quiet#\n' > "$H/etc/getty-conf"
    printf 'quiet loglevel=3\n' > "$H/etc/zz-spark-quiet.conf"
    printf 'default_uki="/boot/x.efi"\n#spark-quiet# default_options="--splash /x.bmp"\n' > "$H/etc/mkinitcpio.d/linux.preset"
}
hb_painted
out=$(HBPATH="$T/bin:$H/bin" hb python3 -m spark.handback --dry-run 2>&1) || bad "handback --dry-run failed: $out"
[ "$(printf '%s\n' "$out" | grep -cE '^would +handback ')" -ge 10 ] && ok "hand-back dry run: a would row for each thing spark left (palette, unit, files, 3 fonts, login, 3 boots)" || bad "hand-back dry run: $out"
printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "hand-back dry run called sudo" || ok "hand-back dry run: no sudo"
[ -f "$H/etc/motd.orig" ] && [ -f "$H/home/.config/spark/console-colors" ] && [ -f "$H/etc/zz-spark-quiet.cfg" ] && ok "hand-back dry run: nothing changed" || bad "hand-back dry run changed a file"
out=$(hb python3 -m spark.handback 2>&1) || bad "handback apply failed: $out"
printf '%s\n' "$out" | grep -q "the look is off this machine now" && bad "hand-back said the look is off with a todo left" || ok "hand-back with a todo left: no closing line"
[ "$(printf '%s\n' "$out" | grep -c '^todo')" = 2 ] && printf '%s\n' "$out" | grep -qE '^todo +handback +.*rc.local still paints' \
    && printf '%s\n' "$out" | grep -qE "^todo +handback +the boot menu's wait stays 0" \
    && ok "hand-back: your rc.local line and the loader's wait are said, never guessed (2 todo rows)" || bad "hand-back todo rows: $(printf '%s\n' "$out" | grep '^todo' | tr '\n' ' ')"
[ ! -e "$H/home/.config/spark/console-colors" ] && [ ! -e "$H/home/.config/spark/console-colors.rgb" ] && [ ! -e "$H/etc/spark-console.service" ] \
    && grep -q '^setvtrgb vga$' "$H/log" && grep -q '^systemctl disable spark-console.service$' "$H/log" \
    && ok "hand-back: the palette is VGA, the boot unit and spark's palette files are gone" || bad "hand-back palette: $(tr '\n' ' ' < "$H/log")"
grep -q 'setvtrgb' "$H/etc/rc.local" && ok "hand-back: rc.local is yours, left as it is" || bad "hand-back edited rc.local"
[ "$(cat "$H/etc/console-setup")" = "$(printf 'CHARMAP="UTF-8"\nFONTFACE="Fixed"\nFONTSIZE="8x16"\n# mine, after spark')" ] \
    && [ "$(cat "$H/etc/vconsole.conf")" = "KEYMAP=us" ] \
    && [ "$(cat "$H/etc/rc.conf")" = "$(printf '#KEYMAP="us"\n#FONT="lat9w-16"\nTIMEZONE="UTC"')" ] \
    && [ -z "$(ls "$H"/etc/*.spark-orig 2>/dev/null)" ] \
    && ok "hand-back: each console font line is back from its .spark-orig, your later lines kept, the copies gone" \
    || bad "hand-back font: $(cat "$H/etc/console-setup" "$H/etc/vconsole.conf" "$H/etc/rc.conf" | tr '\n' ' ')"
grep -q '^setupcon --force$' "$H/log" && grep -q '^systemctl restart systemd-vconsole-setup$' "$H/log" && ! grep -q '^setfont' "$H/log" \
    && printf '%s\n' "$out" | grep -q 'the console font returns at the next boot' \
    && ok "hand-back: each console redraws its own way (setupcon, systemd-vconsole-setup; Void's at the next boot)" || bad "hand-back redraw: $(tr '\n' ' ' < "$H/log")"
[ "$(cat "$H/etc/motd")" = "the distro notice" ] && [ "$(cat "$H/etc/issue")" = 'Debian \n \l' ] && [ -x "$H/etc/10-uname" ] \
    && [ ! -e "$H/etc/motd.orig" ] && [ ! -e "$H/etc/issue.orig" ] \
    && ok "hand-back: motd and issue from their .orig, 10-uname runnable, the .orig gone" || bad "hand-back login: $(ls -l "$H/etc" | tr '\n' ' ')"
[ ! -e "$H/etc/zz-spark-quiet.cfg" ] && [ ! -e "$H/etc/zz-spark-quiet.conf" ] \
    && [ "$(cat "$H/etc/mkinitcpio.d/linux.preset")" = "$(printf 'default_uki="/boot/x.efi"\ndefault_options="--splash /x.bmp"')" ] \
    && grep -q '^mkinitcpio -P$' "$H/log" && [ "$(grep -c '^update-grub$' "$H/log")" = 1 ] && [ ! -e "$H/home/.local/state/spark/handback-rebuild" ] \
    && ok "hand-back: the GRUB and UKI drop-ins gone, the splash unmarked, update-grub and mkinitcpio -P run" || bad "hand-back boot: $(tr '\n' ' ' < "$H/log")"
printf 'GETTY_ARGS="--noclear" # caf\351\n' > "$H/expect"
[ "$(cat "$H/etc/default-grub")" = "GRUB_TIMEOUT=5" ] && cmp -s "$H/etc/getty-conf" "$H/expect" \
    && ok "hand-back: Void's marked lines gone, your own GRUB and getty lines as they were (a Latin-1 byte kept)" || bad "hand-back marks: $(cat "$H/etc/default-grub" "$H/etc/getty-conf" | od -c | tr '\n' ' ')"
out=$(HBPATH="$T/bin:$H/bin" hb python3 -m spark.handback 2>&1) || bad "handback again failed: $out"
[ -z "$out" ] && ok "hand-back, a second run: nothing left, silent, no sudo" || bad "hand-back second run: $out"
# a stale .orig (an older `quiet login off` copied it back, never removed
# it) under a login screen you changed since: the .orig goes, yours stays
hb_clean
printf 'the old notice\n' > "$H/etc/motd.orig"; printf 'old issue\n' > "$H/etc/issue.orig"
printf 'my issue\n' > "$H/etc/issue"; chmod 0644 "$H/etc/10-uname"
out=$(hb python3 -m spark.handback 2>&1) || bad "handback (stale .orig) failed: $out"
[ "$(cat "$H/etc/issue")" = "my issue" ] && [ "$(cat "$H/etc/motd")" = "the distro notice" ] && [ ! -x "$H/etc/10-uname" ] \
    && [ ! -e "$H/etc/motd.orig" ] && [ ! -e "$H/etc/issue.orig" ] && [ "$(printf '%s\n' "$out" | tail -1)" = "the look is off this machine now" ] \
    && ok "hand-back: a stale .orig goes, your changed motd and issue and your 10-uname stay" || bad "hand-back stale .orig: $out / $(cat "$H/etc/motd" "$H/etc/issue")"
# spark-shell's look (v1.63): its quiet login (motd empty, 10-uname off,
# issue the cursor escape alone, its copies *.spark-shell-orig and no
# .orig of spark's), its palette unit and rc.local line, its marked boot
# lines and drop-ins, its font copy. None of it is spark's: the hand-back
# does nothing, says nothing and never calls sudo, every byte stays
hb_clean
mv "$H/etc/motd" "$H/etc/motd.spark-shell-orig"; : > "$H/etc/motd"; chmod 0644 "$H/etc/10-uname"
mv "$H/etc/issue" "$H/etc/issue.spark-shell-orig"; printf '\033[?25h' > "$H/etc/issue"
printf '[Unit]\n' > "$H/etc/spark-shell-console.service"
printf "#!/bin/sh\n[ -r '%s' ] && setvtrgb '%s' #spark-shell-palette#\n" "$H/home/.config/spark-shell/console-colors.rgb" "$H/home/.config/spark-shell/console-colors.rgb" > "$H/etc/rc.local"
printf 'GRUB_TIMEOUT=0\n' > "$H/etc/zz-spark-shell-quiet.cfg"; printf 'quiet\n' > "$H/etc/zz-spark-shell-quiet.conf"
printf 'GRUB_TIMEOUT=0 #spark-shell-quiet#\n' >> "$H/etc/default-grub"
printf 'GETTY_ARGS= #spark-shell-quiet#\n' > "$H/etc/getty-conf"
printf 'default_uki="/boot/x.efi"\n#spark-shell-quiet# default_options="--splash /x.bmp"\n' > "$H/etc/mkinitcpio.d/linux.preset"
cp "$H/etc/console-setup" "$H/etc/console-setup.spark-shell-orig"
printf 'FONT="Terminus" #spark-shell-quiet#\n' > "$H/etc/rc.conf"
before=$(cd "$H" && find etc home -type f | sort | xargs cksum; ls -l "$H/etc/10-uname")
out=$(HBPATH="$T/bin:$H/bin" hb python3 -m spark.handback --dry-run 2>&1; HBPATH="$T/bin:$H/bin" hb python3 -m spark.handback 2>&1)
after=$(cd "$H" && find etc home -type f | sort | xargs cksum; ls -l "$H/etc/10-uname")
[ -z "$out" ] && [ ! -e "$H/log" ] && [ "$before" = "$after" ] \
    && ok "hand-back: spark-shell's quiet login, palette, boot lines and drop-ins are not spark's, left byte for byte, no sudo" \
    || bad "hand-back touched spark-shell's look: $out / $(printf '%s\n' "$after" | tr '\n' ' ')"
# spark's own palette files beside spark-shell's rc.local line: spark's
# go, and the line is spark-shell's, never called yours to delete
printf '\033]P0282828\n' > "$H/home/.config/spark/console-colors"
out=$(hb python3 -m spark.handback 2>&1) || bad "handback (spark-shell's rc.local) failed: $out"
[ ! -e "$H/home/.config/spark/console-colors" ] && ! printf '%s\n' "$out" | grep -q 'rc.local still paints' \
    && [ "$(cat "$H/etc/issue")" = "$(printf '\033[?25h')" ] && [ -e "$H/etc/issue.spark-shell-orig" ] \
    && ok "hand-back: spark's palette files go; spark-shell's rc.local line and login are not called spark's" || bad "hand-back (spark-shell's rc.local): $out"
# a boot rebuild that fails is marked and runs again next time; a root
# step that fails keeps spark's palette files for the next run
hb_clean
printf 'GRUB_TIMEOUT=0\n' > "$H/etc/zz-spark-quiet.cfg"
printf '\033]P0282828\n' > "$H/home/.config/spark/console-colors"
mkdir -p "$H/fail"; printf '#!/bin/sh\necho "$(basename "$0") failed" >> "$HBLOG"\nexit 1\n' > "$H/fail/update-grub"
cp "$H/fail/update-grub" "$H/fail/setvtrgb"; chmod +x "$H"/fail/*
out=$(HBPATH="$H/fail:$H/bin" hb python3 -m spark.handback 2>&1) || bad "handback (failing rebuild) failed: $out"
[ ! -e "$H/etc/zz-spark-quiet.cfg" ] && grep -qx grub "$H/home/.local/state/spark/handback-rebuild" \
    && printf '%s\n' "$out" | grep -qE '^todo +handback +sudo update-grub$' && [ -f "$H/home/.config/spark/console-colors" ] \
    && ok "hand-back: a failed update-grub is a todo and stays marked; a failed setvtrgb keeps the palette files" || bad "hand-back failing rebuild: $out"
out=$(hb python3 -m spark.handback --dry-run 2>&1)
printf '%s\n' "$out" | grep -qE '^would +handback +update-grub ran' && ok "hand-back dry run: the marked rebuild would run again" || bad "hand-back dry run (marked): $out"
: > "$H/log"
out=$(hb python3 -m spark.handback 2>&1) || bad "handback (retry) failed: $out"
[ "$(grep -c '^update-grub$' "$H/log")" = 1 ] && [ ! -e "$H/home/.local/state/spark/handback-rebuild" ] && [ ! -e "$H/home/.config/spark/console-colors" ] \
    && [ "$(printf '%s\n' "$out" | tail -1)" = "the look is off this machine now" ] \
    && ok "hand-back, the next run: update-grub again, the mark gone, the palette files gone, then its one line" || bad "hand-back retry: $out"
hb_clean
out=$(HBPATH="$T/bin:$H/bin" hb python3 -m spark.handback --dry-run 2>&1; HBPATH="$T/bin:$H/bin" hb python3 -m spark.handback 2>&1)
[ -z "$out" ] && [ ! -e "$H/log" ] && ok "hand-back on a machine spark never painted: nothing to do, no sudo" || bad "hand-back clean: $out"
if [ "$(uname -s)" = Darwin ]; then
    # macOS: the profiles spark made leave Terminal.app's preferences (a
    # fixture plist, never the real ones) and a default naming one is
    # Basic; spark-shell's profile is spark-shell's and stays (v1.63)
    python3 -c 'import plistlib, sys; plistlib.dump({"Window Settings": {"spark-gruvbox-dark": {"a": 1}, "spark-shell": {"c": 3}, "Basic": {"b": 2}}, "Default Window Settings": "spark-gruvbox-dark", "Startup Window Settings": "spark-shell"}, open(sys.argv[1], "wb"))' "$H/terminal.plist"
    : > "$H/home/.config/spark/spark-gruvbox-dark.terminal"
    out=$(hb env SPARK_OS=Darwin SPARK_TERMINAL_DOMAIN="$H/terminal.plist" python3 -m spark.handback --dry-run 2>&1)
    printf '%s\n' "$out" | grep -qE '^would +handback +the spark profiles left Terminal.app' && ok "macOS hand-back dry run: the profiles would go" || bad "macOS hand-back dry run: $out"
    out=$(hb env SPARK_OS=Darwin SPARK_TERMINAL_DOMAIN="$H/terminal.plist" python3 -m spark.handback 2>&1)
    left=$(python3 -c 'import plistlib, sys; p = plistlib.load(open(sys.argv[1], "rb")); print(" ".join(sorted(p["Window Settings"])), p["Default Window Settings"], p["Startup Window Settings"])' "$H/terminal.plist")
    [ "$left" = "Basic spark-shell Basic spark-shell" ] && [ ! -e "$H/home/.config/spark/spark-gruvbox-dark.terminal" ] && [ "$(printf '%s\n' "$out" | tail -1)" = "the look is off this machine now" ] \
        && ok "macOS hand-back: the spark profiles and their .terminal file gone, the default Basic, spark-shell's profile kept" || bad "macOS hand-back: $left / $out"
fi
if [ "$(uname -s)" != Darwin ]; then
    # bootstrap's row: the dry run prints the would rows and counts them; a
    # machine with nothing left is one skip; never sudo
    hb_painted
    out=$(HBPATH="$T/bin:$H/bin" hb sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (hand-back) failed: $out"
    printf '%s\n' "$out" | grep -qE '^would +handback +spark-console.service is disabled and removed \(sudo\)$' && ok "bootstrap's handback row: the would rows" || bad "handback row: $(printf '%s\n' "$out" | grep -E ' handback ' | head -3 | tr '\n' ' ')"
    printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "handback row dry run called sudo" || ok "handback row dry run: no sudo"
    printf '%s\n' "$out" | tail -1 | grep -qE '^[0-9]+ to do$' && ok "handback row: the would rows count in the last line" || bad "handback last line: $(printf '%s\n' "$out" | tail -1)"
    hb_clean
    out=$(HBPATH="$T/bin:$H/bin" hb sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (hand-back, clean) failed: $out"
    printf '%s\n' "$out" | grep -qE "^skip +handback +nothing of an older spark's look is left here" && ok "handback row, nothing left: one skip" || bad "handback clean row: $(printf '%s\n' "$out" | grep -E ' handback ' | head -2 | tr '\n' ' ')"
fi

# 10. Arch (the second family): ID=arch in os-release, pinned by
#     SPARK_OS_RELEASE, and a pacman on PATH that answers -- the packages
#     row asks it; never sudo. The names come from distro/arch.env (both
#     OSes, the uname stub); the dry-run is Linux's (the rows are).
printf 'ID=arch\nPRETTY_NAME="Arch Linux"\n' > "$T/os-release-arch"
printf 'ID=manjaro\nID_LIKE=arch\nPRETTY_NAME="Manjaro Linux"\n' > "$T/os-release-manjaro"
lp() { env PATH="$T/os:$PATH" SPARK_SYSFS_DRM="$T/nodrm" SPARK_OS_RELEASE="$1" sh "$REPO/bootstrap.sh" --list-packages 2>&1; }
printf 'SITE_AI_MODEL=none\n' > "$HOME/.config/spark/site.env"
out=$(lp "$T/os-release-arch")
printf '%s\n' "$out" | grep -qx gcc-libs && ! printf '%s\n' "$out" | grep -qxE 'kbd|fd-find|libgomp1|tmux' \
    && ok "Arch: --list-packages speaks pacman's names (gcc-libs; no kbd, the look left core)" || bad "Arch --list-packages: $(printf '%s' "$out" | tr '\n' ' ')"
[ "$(lp "$T/os-release-manjaro")" = "$out" ] && ok "Manjaro (ID_LIKE=arch): the same list" || bad "Manjaro list differs"
lp "$T/os-release-debian" | grep -qx libgomp1 && ok "Ubuntu (ID_LIKE=debian): libgomp1 still" || bad "Ubuntu list lost libgomp1"
if [ "$(uname -s)" != Darwin ]; then
    mkdir -p "$T/arch"
    printf '#!/bin/sh\ncase $1 in -Qq) shift; printf "%%s\\n" "$@" ;; -Sp) exit 0 ;; *) exit 1 ;; esac\n' > "$T/arch/pacman"; chmod +x "$T/arch/pacman"
    printf 'SITE_AI_MODEL=none\n' > "$HOME/.config/spark/site.env"
    out=$(SPARK_OS_RELEASE="$T/os-release-arch" PATH="$T/arch:$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (Arch) failed: $out"
    printf '%s\n' "$out" | grep -qE '^ok +packages ' && ok "Arch: the packages row answers through pacman (everything installed)" || bad "Arch packages row: $(printf '%s\n' "$out" | grep -E ' packages ' | head -1)"
    printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "Arch dry-run called sudo" || ok "Arch dry-run: no sudo"
    # a pacman that knows nothing installed: the row would install, as root
    printf '#!/bin/sh\ncase $1 in -Sp) exit 0 ;; *) exit 1 ;; esac\n' > "$T/arch/pacman"; chmod +x "$T/arch/pacman"
    out=$(SPARK_OS_RELEASE="$T/os-release-arch" PATH="$T/arch:$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (Arch, bare) failed: $out"
    printf '%s\n' "$out" | grep -qE '^would +packages +install:.*\(sudo\)$' && ok "Arch, nothing installed: the packages row would install (sudo)" || bad "Arch bare packages row: $(printf '%s\n' "$out" | grep -E ' packages ' | head -1)"
    printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "Arch bare dry-run called sudo" || ok "Arch bare dry-run: no sudo"
    # 10b. a CLIENT on the same bare box: no root row at all -- the dry
    # run holds no `sudo` word, and an APPLY makes no as_root call (the
    # sudo stub would shout SUDO CALLED); python3 and curl are all it runs
    # the keys of the look an older site.env still holds (v1.62's and
    # v1.69's) load as any key nothing reads: no row, no refusal
    printf 'SITE_AI_MODEL=none\nSITE_PEER_AI_URL=http://192.0.2.10:8081\nSITE_SET_HOSTNAME=yes\nSITE_THEME=gruvbox-dark\nSITE_FONT_FACE=Terminus\nSITE_FONT_SIZE=16x32\nSITE_QUIET_BOOT=yes\nSITE_QUIET_LOGIN=yes\nSITE_QUIET_START=yes\nSITE_QUIET_AUDIO=yes\n' > "$HOME/.config/spark/site.env"
    out=$(SPARK_OS_RELEASE="$T/os-release-arch" PATH="$T/arch:$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (client, bare PM) failed: $out"
    printf '%s\n' "$out" | grep -qE '^skip +packages +a client' && ok "client: the packages row skips even with a package missing" || bad "client packages row: $(printf '%s\n' "$out" | grep -E ' packages ' | head -1)"
    printf '%s\n' "$out" | grep -qi 'sudo' && bad "client dry-run holds a sudo word: $(printf '%s\n' "$out" | grep -i sudo | head -2 | tr '\n' ' ')" || ok "client dry-run: no sudo word anywhere"
    out=$(SPARK_OS_RELEASE="$T/os-release-arch" PATH="$T/arch:$T/bin:$PATH" sh "$REPO/bootstrap.sh" 2>&1) || bad "bootstrap apply (client) failed: $out"
    printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "client apply called as_root: $out" || ok "client apply: no as_root call"
    printf 'SITE_AI_MODEL=none\n' > "$HOME/.config/spark/site.env"
fi

# 11. Void (the third family): ID="void" in os-release -- quoted, as Void
#     ships it -- pinned by SPARK_OS_RELEASE. xbps answers for the packages
#     (a stub in the fixture's shape: -l lists every name distro/void.env
#     holds as installed, -p pkgver and -R say installed and in a repo),
#     runit is the init (SPARK_ETC_RUNIT names a dir; SPARK_VAR_SERVICE says
#     whether it is booted). The names come from distro/void.env (both
#     OSes, the uname stub); the dry runs and the apply are Linux's (the
#     rows are). The sudo stub shouts: a dry run never reaches it, and the
#     links into a runsvdir of your own need no root.
printf 'ID="void"\nPRETTY_NAME="Void Linux"\n' > "$T/os-release-void"
out=$(lp "$T/os-release-void")
printf '%s\n' "$out" | grep -qx libgomp && printf '%s\n' "$out" | grep -qx python3 \
    && ! printf '%s\n' "$out" | grep -qxE 'kbd|gcc-libs|libgomp1|python|fd-find|tmux' \
    && ok "Void: --list-packages speaks xbps's names (libgomp, python3; no kbd)" || bad "Void --list-packages: $(printf '%s' "$out" | tr '\n' ' ')"
if [ "$(uname -s)" != Darwin ]; then
    V=$T/void; mkdir -p "$V/bin" "$V/runit" "$V/service" "$V/sv-etc" "$T/etc"
    names=$(sed -n 's/^PKG_[A-Z]*=//p' "$REPO/distro/void.env" | tr '\n' ' ')
    printf '#!/bin/sh\ncase $1 in -l) for p in %s; do echo "ii $p-1.0_1 x"; done ;; -p|-R) exit 0 ;; *) exit 1 ;; esac\n' "$names" > "$V/bin/xbps-query"
    printf '#!/bin/sh\ncase $1 in -un) exit 0 ;; *) exit 1 ;; esac\n' > "$V/bin/xbps-install"
    # sv logs its argv (SV_LOG); status reads the dir the way runsv would
    # leave it: run: with a supervise/ dir and no down file, down: with one,
    # fail: when nobody supervises it (engine.parse_sv_status's three words);
    # up, down and the rest just succeed
    cat > "$V/bin/sv" <<'SH'
#!/bin/sh
echo "sv $*" >> "${SV_LOG:-/dev/null}"
case $1 in
    status) if [ ! -d "$2/supervise" ]; then echo "fail: $2: runsv not running"; exit 1
            elif [ -f "$2/finishing" ]; then echo "finish: $2: (pid 2) 1s, normally up"
            elif [ -f "$2/down" ]; then echo "down: $2: 1s, normally up"
            else echo "run: $2: (pid 1) 1s"; fi ;;
esac
exit 0
SH
    chmod +x "$V/bin/xbps-query" "$V/bin/xbps-install" "$V/bin/sv"
    # vrun [VAR=VALUE...] COMMAND...: the Void fixture's seams (a later
    # VAR=VALUE overrides), the stubs first on PATH, the sudo that shouts;
    # every file a row reads is pinned, so the machine underneath says nothing
    vrun() {
        env SPARK_OS_RELEASE="$T/os-release-void" SPARK_SYSFS_DRM="$T/nodrm" SPARK_ETC_RUNIT="$V/runit" SPARK_VAR_SERVICE="$V/no-service" \
            SPARK_ETC_SV="$V/sv-etc" \
            SPARK_SHARE_TOKEN="$V/no-share-token" SPARK_SHARE_URL="$V/no-share-url" \
            SV_LOG="$V/sv.log" PATH="$V/bin:$T/bin:$PATH" "$@"
    }
    # 11a. a container (no /var/service): the packages row answers through
    #      xbps, the services wait, linger, sleep and the lid are runit's
    #      skips; never sudo
    printf 'SITE_AI_MODEL=none\n' > "$HOME/.config/spark/site.env"
    out=$(vrun sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (Void) failed: $out"
    printf '%s\n' "$out" | grep -qE '^skip +runit +runit is not running here' && ok "Void, a container: the runit row skips (the services wait for a machine that boots)" || bad "Void runit row: $(printf '%s\n' "$out" | grep -E ' runit ' | head -1)"
    printf '%s\n' "$out" | grep -qE '^ok +packages ' && ok "Void: the packages row answers through xbps (everything installed)" || bad "Void packages row: $(printf '%s\n' "$out" | grep -E ' packages ' | head -1)"
    printf '%s\n' "$out" | grep -qE '^skip +linger +runit' && ok "Void: linger skips (the supervisor runs from boot, login or not)" || bad "Void linger row: $(printf '%s\n' "$out" | grep -E ' linger ' | head -1)"
    printf '%s\n' "$out" | grep -qE '^skip +sleep +runit' && printf '%s\n' "$out" | grep -qE '^skip +lid +runit' && ok "Void: sleep and lid skip (no sleep targets, no logind)" || bad "Void sleep/lid rows: $(printf '%s\n' "$out" | grep -E ' (sleep|lid) ' | head -2 | tr '\n' ' ')"
    printf '%s\n' "$out" | grep -qE '^(ok|would|skip|todo) +spark-(check|serve|forge) ' && bad "a container: a service row spoke: $(printf '%s\n' "$out" | grep -E '^(ok|would|skip|todo) +spark-' | head -1)" || ok "a container: no service row (they wait with runit)"
    printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "Void dry-run called sudo" || ok "Void dry-run: no sudo"
    # 11b. runit LIVE (/var/service is a dir), no runsvdir-USER yet: the
    #      supervisor row would write the root service and link it (sudo),
    #      spark-check would come up; a dry run says so and changes nothing
    #      through sv
    out=$(vrun SPARK_VAR_SERVICE="$V/service" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (Void, runit live) failed: $out"
    printf '%s\n' "$out" | grep -qE '^would +supervisor +write .*runsvdir-.*, link it into .*/service \(sudo\)$' && ok "runit live, no root service: the supervisor row would write runsvdir-USER and link it (sudo)" || bad "supervisor row: $(printf '%s\n' "$out" | grep -E ' supervisor ' | head -1)"
    printf '%s\n' "$out" | grep -qE '^would +spark-check +sv up ~/\.config/spark/sv/spark-check$' && ok "runit live: spark-check would come up (sv up, the dir spelled with ~)" || bad "spark-check row: $(printf '%s\n' "$out" | grep -E ' spark-check ' | head -1)"
    printf '%s\n' "$out" | grep -qE '^(ok|would|skip|todo) +runit ' && bad "runit live: the runit skip row survives" || ok "runit live: no runit skip row"
    printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "runit live dry-run called sudo" || ok "runit live dry-run: no sudo"
    grep -qE '^sv (-w [0-9]+ )?(up|down|restart|exit) ' "$V/sv.log" 2>/dev/null && bad "a dry run changed a service: $(grep -E '^sv (-w [0-9]+ )?(up|down|restart|exit) ' "$V/sv.log" | head -1)" || ok "a dry run asks sv status and nothing more"
    # 11c. a runsvdir-USER of your own (no spark marker in its run): spark
    #      reads the directory its runsvdir line names -- the last word,
    #      quotes off, $HOME spelled out -- and would link its three service
    #      dirs there
    me=$(id -un); mkdir -p "$V/sv-etc/runsvdir-$me" "$HOME/service"
    printf '#!/bin/sh\n# my services, the handbook way\nexport USER=%s HOME=%s\nexec chpst -u %s runsvdir "$HOME/service"\n' "$me" "$HOME" "$me" > "$V/sv-etc/runsvdir-$me/run"
    out=$(vrun SPARK_VAR_SERVICE="$V/service" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (Void, your runsvdir) failed: $out"
    printf '%s\n' "$out" | grep -qE "^would +supervisor +link spark-check, spark-serve, spark-forge into .*/service \(your runsvdir-$me\)$" && ok "your runsvdir-USER: the supervisor row would link spark's dirs into its directory (\$HOME read from its run)" || bad "your runsvdir row: $(printf '%s\n' "$out" | grep -E ' supervisor ' | head -1)"
    printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "your runsvdir dry-run called sudo" || ok "your runsvdir dry-run: no sudo"
    # 11d. install.sh renders the service dirs only where /etc/runit is a
    #      dir (the seam): run scripts executable, @USER@ and @HOME@ filled,
    #      a `down` file beside a run that is new here (nothing starts before
    #      bootstrap decides); the second run has nothing to do and leaves
    #      the down file where it is
    out=$(SPARK_ETC_RUNIT="$V/runit" sh "$REPO/install.sh" 2>&1) || bad "install.sh (runit) failed: $out"
    svd="$HOME/.config/spark/sv"
    [ -x "$svd/spark-serve/run" ] && [ -x "$svd/spark-forge/run" ] && [ -x "$svd/spark-check/run" ] && ok "runit: install.sh renders the three run scripts, executable" || bad "runit: run scripts: $(ls -l "$svd"/*/run 2>&1 | head -3 | tr '\n' ' ')"
    [ -x "$svd/spark-serve/finish" ] && [ -x "$svd/spark-forge/finish" ] && [ -x "$svd/spark-check/log/run" ] && ok "runit: finish and log/run beside them, executable" || bad "runit: finish/log: $(ls -lR "$svd/spark-serve" 2>&1 | tr '\n' ' ')"
    [ -f "$svd/spark-serve/down" ] && [ -f "$svd/spark-forge/down" ] && [ -f "$svd/spark-check/down" ] && ok "runit: a run that is new here comes with a down file" || bad "runit: down files: $(ls "$svd"/*/down 2>&1 | tr '\n' ' ')"
    grep -qF "USER=$me " "$svd/spark-serve/run" && grep -qF "HOME=$HOME " "$svd/spark-serve/run" && ! grep -q '@[A-Z_]*@' "$svd/spark-serve/run" && ok "runit: @HOME@ and @USER@ rendered, no placeholder left" || bad "runit: spark-serve/run: $(grep -n 'export' "$svd/spark-serve/run")"
    grep -q 'rendered by spark install.sh' "$svd/spark-check/log/run" && grep -q 'rendered by spark install.sh' "$svd/spark-forge/finish" && ok "runit: every rendered file carries the mark" || bad "runit: a rendered file lacks the mark"
    out=$(SPARK_ETC_RUNIT="$V/runit" sh "$REPO/install.sh" 2>&1)
    [ "$(printf '%s\n' "$out" | tail -1)" = "Nothing to do" ] && [ -f "$svd/spark-serve/down" ] && ok "runit: the second run is Nothing to do, the down file stays" || bad "runit: second run: $(printf '%s\n' "$out" | grep -v '^ok' | head -3 | tr '\n' ' ')"
    # 11e. the APPLY with your runsvdir-USER: the links land (yours, no
    #      root), spark-check comes up (its down file goes, sv up), the
    #      serve and forge dirs keep theirs (on demand: no model here), and
    #      the sudo stub never speaks. runsv is played by the stub: a
    #      supervise/ dir in each service dir is what a runsvdir leaves
    for s in spark-check spark-serve spark-forge; do mkdir -p "$svd/$s/supervise"; : > "$svd/$s/supervise/ok"; done
    printf 'SITE_AI_MODEL=none\n' > "$HOME/.config/spark/site.env"
    rm -f "$V/sv.log"
    out=$(vrun SPARK_VAR_SERVICE="$V/service" sh "$REPO/bootstrap.sh" </dev/null 2>&1) || bad "bootstrap apply (Void, your runsvdir) failed: $(printf '%s\n' "$out" | tail -5 | tr '\n' ' ')"
    printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "the apply called as_root: $(printf '%s\n' "$out" | grep 'SUDO CALLED' | head -1)" || ok "your runsvdir apply: no as_root call (the links are yours)"
    printf '%s\n' "$out" | grep -qE "^ok +supervisor +your runsvdir-$me supervises .*/service; spark's services are linked there$" && ok "your runsvdir apply: the supervisor row says yours, linked" || bad "supervisor row: $(printf '%s\n' "$out" | grep -E ' supervisor ' | head -1)"
    linked=1
    for s in spark-check spark-serve spark-forge; do [ "$(readlink "$HOME/service/$s" 2>/dev/null)" = "$svd/$s" ] || linked=0; done
    [ "$linked" = 1 ] && ok "your runsvdir apply: the three symlinks point into ~/.config/spark/sv/" || bad "links: $(ls -l "$HOME/service" 2>&1 | tr '\n' ' ')"
    printf '%s\n' "$out" | grep -qE '^ok +spark-check +supervised \(run\)$' && ok "your runsvdir apply: spark-check is supervised (run)" || bad "spark-check row: $(printf '%s\n' "$out" | grep -E ' spark-check ' | head -1)"
    [ ! -e "$svd/spark-check/down" ] && [ -f "$svd/spark-serve/down" ] && [ -f "$svd/spark-forge/down" ] && ok "your runsvdir apply: spark-check's down file went; serve and forge keep theirs (no model here)" || bad "down files: $(ls "$svd"/*/down 2>&1 | tr '\n' ' ')"
    grep -qxF "sv up $svd/spark-check" "$V/sv.log" && ! grep -qE '^sv (-w [0-9]+ )?(up|down|restart|exit) .*spark-(serve|forge)$' "$V/sv.log" && ok "your runsvdir apply: sv up spark-check, nothing else moved through sv" || bad "sv log: $(grep -vE '^sv status' "$V/sv.log" 2>/dev/null | tr '\n' ' ')"
    out=$(vrun SPARK_VAR_SERVICE="$V/service" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (Void, converged) failed: $out"
    printf '%s\n' "$out" | grep -qE "^ok +supervisor +your runsvdir-$me " && printf '%s\n' "$out" | grep -qE '^ok +spark-check +supervised \(run\)$' \
        && printf '%s\n' "$out" | grep -qE '^skip +spark-serve +on demand \(' && printf '%s\n' "$out" | grep -qE '^skip +spark-forge +off \(' \
        && ok "converged: supervisor and spark-check ok, serve on demand, forge off" || bad "converged rows: $(printf '%s\n' "$out" | grep -E ' (supervisor|spark-check|spark-serve|spark-forge) ' | tr '\n' ' ')"
    # 11e2. finish: (the run exited, runsv brings it back) is its own
    #       state: enabled, not running -- the row says so and names the
    #       log's tail, never "no runsv answers"
    : > "$svd/spark-check/finishing"
    out=$(vrun SPARK_VAR_SERVICE="$V/service" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || true
    printf '%s\n' "$out" | grep -qE '^todo +spark-check +enabled, not running: its run exited and runsv restarts it -- tail .*/log/spark-check/current$' \
        && ok "runit finish: the spark-check row says enabled, not running, and where its log is" \
        || bad "finish row: $(printf '%s\n' "$out" | grep -E ' spark-check ' | head -1)"
    rm -f "$svd/spark-check/finishing"
    # 11f. an xbps that knows nothing installed: the row would install, as
    #      root, in xbps's names
    printf '#!/bin/sh\ncase $1 in -R) exit 0 ;; *) exit 1 ;; esac\n' > "$V/bin/xbps-query"
    out=$(vrun sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (Void, bare) failed: $out"
    printf '%s\n' "$out" | grep -qE '^would +packages +install:.*\(sudo\)$' && ok "Void, nothing installed: the packages row would install (sudo)" || bad "Void bare packages row: $(printf '%s\n' "$out" | grep -E ' packages ' | head -1)"
    printf '%s\n' "$out" | grep -qE '^would +packages +install:.* libgomp \(sudo\)$' && ! printf '%s\n' "$out" | grep -qE '^would +packages +.*(gcc-libs|libgomp1)' && ok "the install line speaks xbps's names (libgomp)" || bad "Void bare install line: $(printf '%s\n' "$out" | grep -E ' packages ' | head -1)"
    printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "Void bare dry-run called sudo" || ok "Void bare dry-run: no sudo"
    # 11g. no /etc/runit (the seam names a dir that is not there): install.sh
    #      renders no service dir -- 2a's list is the whole of a systemd
    #      Linux's $HOME; a client under runit gets none either
    P=$T/plain; mkdir -p "$P/.config/spark"; : > "$P/.config/spark/site.env"
    HOME=$P XDG_CONFIG_HOME=$P/.config SPARK_ETC_RUNIT="$V/no-runit" sh "$REPO/install.sh" >/dev/null
    [ ! -e "$P/.config/spark/sv" ] && [ -L "$P/.config/systemd/user/spark-serve.service" ] && ok "no /etc/runit: install.sh renders no service dir; the systemd unit is linked as before" || bad "no runit: $(find "$P/.config" -maxdepth 3 | tr '\n' ' ')"
    out=$(HOME=$C XDG_CONFIG_HOME=$C/.config SPARK_ETC_RUNIT="$V/runit" sh "$REPO/install.sh" --dry-run 2>&1)
    printf '%s\n' "$out" | grep -q 'sv/spark-' && bad "a client under runit: a service dir announced: $(printf '%s\n' "$out" | grep 'sv/spark-' | head -1)" || ok "a client under runit: no service dir (a client runs no unit)"
    printf 'SITE_AI_MODEL=none\n' > "$HOME/.config/spark/site.env"
fi

# 12. runit: a service dir new here gets its `down` file BEFORE any file
#     of it lands (runsvdir scans every 5 s and starts a dir it finds with
#     a run and no down file): a cp that logs whether down was there when
#     each file of the dir was copied, on both OSes (the seam names a dir)
D=$T/downfirst; mkdir -p "$D/home/.config/spark" "$D/runit" "$D/bin"
: > "$D/home/.config/spark/site.env"
cat > "$D/bin/cp" <<'SH'
#!/bin/sh
for last; do :; done
case $last in
    */.config/spark/sv/*) svc=${last#*/.config/spark/sv/}; svc=${last%%/.config/spark/sv/*}/.config/spark/sv/${svc%%/*}
                          [ -f "$svc/down" ] && echo "down-first $last" >> "$CP_LOG" || echo "down-late $last" >> "$CP_LOG" ;;
esac
exec /bin/cp "$@"
SH
chmod +x "$D/bin/cp"
HOME="$D/home" XDG_CONFIG_HOME="$D/home/.config" SPARK_ETC_RUNIT="$D/runit" CP_LOG="$D/cp.log" PATH="$D/bin:$PATH" \
    sh "$REPO/install.sh" >/dev/null 2>&1 || bad "install.sh (runit, down first) failed"
n=$(grep -c '^down-first ' "$D/cp.log" 2>/dev/null || true)
[ "${n:-0}" -ge 8 ] && ! grep -q '^down-late ' "$D/cp.log" \
    && ok "runit: every file of a new service dir lands after its down file ($n files)" \
    || bad "runit down-first: $(tr '\n' ' ' < "$D/cp.log" 2>/dev/null)"

# 13. Fedora (the fourth family): ID=fedora in os-release, pinned by
#     SPARK_OS_RELEASE; Rocky says ID_LIKE="rhel centos fedora" and lands
#     in the same family. rpm answers "is it installed" by provider (a
#     stub: --whatprovides exits 0), dnf "is it in a repository" (repoquery
#     prints a line). The names come from distro/fedora.env (both OSes, the
#     uname stub); the dry runs are Linux's (the rows are); never sudo.
printf 'ID=fedora\nPRETTY_NAME="Fedora Linux 44 (Workstation Edition)"\n' > "$T/os-release-fedora"
printf 'ID="rocky"\nID_LIKE="rhel centos fedora"\nPRETTY_NAME="Rocky Linux 9.5 (Blue Onyx)"\n' > "$T/os-release-rocky"
out=$(lp "$T/os-release-fedora")
printf '%s\n' "$out" | grep -qx libgomp && printf '%s\n' "$out" | grep -qx python3 \
    && ! printf '%s\n' "$out" | grep -qxE 'gcc-libs|libgomp1|python|vulkan-loader' \
    && ok "Fedora: --list-packages speaks dnf's names (libgomp, python3; no vulkan without a GPU)" || bad "Fedora --list-packages: $(printf '%s' "$out" | tr '\n' ' ')"
[ "$(lp "$T/os-release-rocky")" = "$out" ] && ok "Rocky (ID_LIKE names fedora): the same list" || bad "Rocky list differs"
out=$(env PATH="$T/os:$PATH" SPARK_SYSFS_DRM="$T/drm" SPARK_OS_RELEASE="$T/os-release-fedora" sh "$REPO/bootstrap.sh" --list-packages 2>&1)
printf '%s\n' "$out" | grep -qx vulkan-loader && printf '%s\n' "$out" | grep -qx mesa-vulkan-drivers \
    && ok "Fedora with a GPU: the loader and Mesa's drivers, in Fedora's names" || bad "Fedora vulkan names: $(printf '%s' "$out" | tr '\n' ' ')"
if [ "$(uname -s)" != Darwin ]; then
    mkdir -p "$T/fedora"
    printf '#!/bin/sh\n[ "$1 $2" = "-q --whatprovides" ] && exit 0\nexit 1\n' > "$T/fedora/rpm"
    printf '#!/bin/sh\ncase "$*" in "-q repoquery --whatprovides "*) echo "$4-0:1.0-1.fc44.x86_64" ;; *) exit 1 ;; esac\n' > "$T/fedora/dnf"
    chmod +x "$T/fedora/rpm" "$T/fedora/dnf"
    out=$(SPARK_OS_RELEASE="$T/os-release-fedora" PATH="$T/fedora:$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (Fedora) failed: $out"
    printf '%s\n' "$out" | grep -qE '^ok +packages ' && ok "Fedora: the packages row answers through rpm's providers (everything installed)" || bad "Fedora packages row: $(printf '%s\n' "$out" | grep -E ' packages ' | head -1)"
    printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "Fedora dry-run called sudo" || ok "Fedora dry-run: no sudo"
    # an rpm that knows no provider: the row would install, as root, in dnf's names
    printf '#!/bin/sh\nexit 1\n' > "$T/fedora/rpm"
    out=$(SPARK_OS_RELEASE="$T/os-release-rocky" PATH="$T/fedora:$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (Rocky, bare) failed: $out"
    printf '%s\n' "$out" | grep -qE '^would +packages +install:.* libgomp \(sudo\)$' && ! printf '%s\n' "$out" | grep -qE '^would +packages +.*(gcc-libs|libgomp1)' \
        && ok "Rocky, nothing installed: the packages row would install (sudo), in dnf's names (libgomp)" || bad "Rocky bare packages row: $(printf '%s\n' "$out" | grep -E ' packages ' | head -1)"
    printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "Rocky bare dry-run called sudo" || ok "Rocky bare dry-run: no sudo"
    # a dnf whose repositories hold none of the names: the row skips, naming the target
    printf '#!/bin/sh\nexit 0\n' > "$T/fedora/dnf"
    out=$(SPARK_OS_RELEASE="$T/os-release-fedora" PATH="$T/fedora:$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (Fedora, no repository) failed: $out"
    printf '%s\n' "$out" | grep -qE '^skip +packages +not in this dnf:.* libgomp \(spark targets Fedora\)$' && ok "Fedora, a name no repository holds: the row skips and names its target" || bad "Fedora absent row: $(printf '%s\n' "$out" | grep -E ' packages ' | head -2 | tr '\n' ' ')"
fi

# 14. openSUSE (the fifth family): Tumbleweed's os-release says
#     ID="opensuse-tumbleweed" and ID_LIKE="opensuse suse", Leap's
#     ID="opensuse-leap" and ID_LIKE="suse opensuse" -- the family is the
#     ID_LIKE word, in either order. rpm answers "is it installed" by
#     provider (python3 is python313's capability there), zypper "is it in
#     a repository" (search --provides exits 0, 104 when nothing matches).
printf 'ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\nPRETTY_NAME="openSUSE Tumbleweed"\n' > "$T/os-release-tumbleweed"
printf 'ID="opensuse-leap"\nID_LIKE="suse opensuse"\nPRETTY_NAME="openSUSE Leap 16.0"\n' > "$T/os-release-leap"
out=$(lp "$T/os-release-tumbleweed")
printf '%s\n' "$out" | grep -qx libgomp1 && printf '%s\n' "$out" | grep -qx python3 \
    && ! printf '%s\n' "$out" | grep -qxE 'gcc-libs|libgomp|python|libvulkan1' \
    && ok "openSUSE: --list-packages speaks zypper's names (libgomp1, python3; no vulkan without a GPU)" || bad "openSUSE --list-packages: $(printf '%s' "$out" | tr '\n' ' ')"
[ "$(lp "$T/os-release-leap")" = "$out" ] && ok "Leap (ID_LIKE names opensuse second): the same list" || bad "Leap list differs"
out=$(env PATH="$T/os:$PATH" SPARK_SYSFS_DRM="$T/drm" SPARK_OS_RELEASE="$T/os-release-tumbleweed" sh "$REPO/bootstrap.sh" --list-packages 2>&1)
printf '%s\n' "$out" | grep -qx libvulkan_radeon && printf '%s\n' "$out" | grep -qx libvulkan_intel && ! printf '%s\n' "$out" | grep -qx mesa-vulkan-drivers \
    && ok "openSUSE with a GPU: the loader and Mesa's two drivers, in openSUSE's names" || bad "openSUSE vulkan names: $(printf '%s' "$out" | tr '\n' ' ')"
if [ "$(uname -s)" != Darwin ]; then
    mkdir -p "$T/opensuse"
    printf '#!/bin/sh\n[ "$1 $2" = "-q --whatprovides" ] && exit 0\nexit 1\n' > "$T/opensuse/rpm"
    printf '#!/bin/sh\ncase "$*" in "--non-interactive --no-refresh search --match-exact --provides "*) exit 0 ;; *) exit 1 ;; esac\n' > "$T/opensuse/zypper"
    chmod +x "$T/opensuse/rpm" "$T/opensuse/zypper"
    out=$(SPARK_OS_RELEASE="$T/os-release-tumbleweed" PATH="$T/opensuse:$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (openSUSE) failed: $out"
    printf '%s\n' "$out" | grep -qE '^ok +packages ' && ok "openSUSE: the packages row answers through rpm's providers (everything installed)" || bad "openSUSE packages row: $(printf '%s\n' "$out" | grep -E ' packages ' | head -1)"
    printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "openSUSE dry-run called sudo" || ok "openSUSE dry-run: no sudo"
    # an rpm that knows no provider: the row would install, as root, in zypper's names
    printf '#!/bin/sh\nexit 1\n' > "$T/opensuse/rpm"
    out=$(SPARK_OS_RELEASE="$T/os-release-leap" PATH="$T/opensuse:$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (Leap, bare) failed: $out"
    printf '%s\n' "$out" | grep -qE '^would +packages +install:.* libgomp1 \(sudo\)$' && ! printf '%s\n' "$out" | grep -qE '^would +packages +.*(gcc-libs|libgomp )' \
        && ok "Leap, nothing installed: the packages row would install (sudo), in zypper's names (libgomp1)" || bad "Leap bare packages row: $(printf '%s\n' "$out" | grep -E ' packages ' | head -1)"
    printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "Leap bare dry-run called sudo" || ok "Leap bare dry-run: no sudo"
    # a zypper that finds no provider (104): the row skips, naming the target
    printf '#!/bin/sh\nexit 104\n' > "$T/opensuse/zypper"
    out=$(SPARK_OS_RELEASE="$T/os-release-tumbleweed" PATH="$T/opensuse:$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (openSUSE, no repository) failed: $out"
    printf '%s\n' "$out" | grep -qE '^skip +packages +not in this zypper:.* libgomp1 \(spark targets openSUSE Tumbleweed\)$' && ok "openSUSE, a name no repository holds: the row skips and names its target" || bad "openSUSE absent row: $(printf '%s\n' "$out" | grep -E ' packages ' | head -2 | tr '\n' ' ')"
fi

[ "$fail" -eq 0 ] && echo "install_test: all ok" || { echo "install_test: FAILED"; exit 1; }
