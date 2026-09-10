#!/bin/sh
# spark tests/install_test.sh -- install.sh against a throwaway HOME.
# Proves contract 2: the row shapes, link/render/back-up semantics,
# idempotence, and that every theme and prompt style renders cleanly.
set -eu
REPO=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
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
printf '%s\n' "$out" | grep -q '^would .*\.gitconfig$' && bad ".gitconfig announced" || ok "no .gitconfig row (the look is spark-shell's)"
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
ok "no rc file, no .gitconfig, .tmux.conf, btop or starship"
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

# 4. a bad theme name (bootstrap's theme row) and shell syntax in
#    site.env (site_load, both scripts) are refused
printf 'SITE_THEME=nope\n' > "$HOME/.config/spark/site.env"
if sh "$REPO/bootstrap.sh" --dry-run >/dev/null 2>&1; then bad "unknown theme accepted"; else ok "unknown theme refused"; fi
printf 'SITE_THEME=none; rm -rf /\n' > "$HOME/.config/spark/site.env"
if run >/dev/null 2>&1; then bad "shell syntax in site.env accepted"; else ok "shell syntax in site.env refused"; fi
printf 'SITE_THEME=none\n' > "$HOME/.config/spark/site.env"

# 7. bootstrap --dry-run with SITE_HEADLESS=yes announces the headless rows
#    (contract 1: would/skip, a count line, never sudo -- a sudo on PATH that
#    shouts proves it); SITE_HEADLESS=no leaves sleep alone; and the shell
#    layer: SITE_SHELL unset skips every shell row, on announces them
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
printf '%s\n' "$out" | grep -qE '^skip +console +(macOS:|SITE_FONT_FACE unset)' && ok "the console row is core, its skip names its own reason" || bad "console row: $(printf '%s\n' "$out" | grep -E ' console ' | head -1)"
printf '%s\n' "$out" | grep -qE '^skip +hostname +SITE_SET_HOSTNAME=no' && ok "the hostname row is core (identity), its skip names its key" || bad "hostname row: $(printf '%s\n' "$out" | grep -E ' hostname ' | head -1)"
printf '%s\n' "$out" | grep -qE ' micro-aspell ' && bad "a micro-aspell row survives (spark ships no app)" || ok "no micro-aspell row: spark installs no editor"
printf '%s\n' "$out" | grep -qE "^would +dir +mkdir .*/projects" && bad "the workspace folder would be made" || ok "no workspace folder for a new user"
[ "$(uname -s)" = Darwin ] && { printf '%s\n' "$out" | grep -qE '^ok +packages +nothing required' && ok "macOS: packages row is ok, nothing required" || bad "macOS packages row"; }
[ -z "$(sh "$REPO/bootstrap.sh" --list-packages | grep -E '^(tmux|starship|bat|eza|fzf|btop)$')" ] && ok "--list-packages has no shell tool (spark-shell installs those)" || bad "--list-packages lists a shell tool"
[ -z "$(sh "$REPO/bootstrap.sh" --list-packages | grep -E '^(micro|aspell|aspell-en|shellcheck)$')" ] && ok "no editor, no contributor tool in --list-packages" || bad "--list-packages still lists micro/aspell/shellcheck"
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
[ "$(uname -s)" = Darwin ] || { printf '%s\n' "$out" | grep -qE '^skip +linger ' && ok "SITE_HEADLESS=no: linger is skipped" || bad "linger row with SITE_HEADLESS=no"; }
printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "dry-run called sudo" || ok "dry-run never called sudo (workstation)"
# the shell-moved migration: an rc file symlinked into this repository (an
# older shell layer's) is announced for hand-back; the rc row names it
case $(uname -s) in Darwin) rc=.zshrc ;; *) rc=.bashrc ;; esac
ln -sfn "$REPO/$([ "$rc" = .zshrc ] && echo macos || echo linux)/home/$rc" "$HOME/$rc"
out=$(PATH="$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (rc linked) failed"
printf '%s\n' "$out" | grep -qE '^would +shell-moved +the shell layer moved to github.com/forgewright-ai/spark-shell' && ok "shell-moved: the migration row announces the hand-back" || bad "shell-moved row: $(printf '%s\n' "$out" | grep -E ' shell-moved ' | head -1)"
printf '%s\n' "$out" | grep -qE "^ok +rc +~/$rc is a symlink into this repo" && ok "rc: a repo symlink is named (shell-moved hands it back)" || bad "rc: linked: $(printf '%s\n' "$out" | grep -E ' rc ')"
printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "dry-run called sudo (rc linked)" || ok "dry-run never called sudo (rc linked)"
rm -f "$HOME/$rc"

# 8. bootstrap --list-models names both roles' picks (the choosing rule;
#    lib/spark engine.chosen_rows is the twin, tests/smoke.py pins it the
#    same way). SPARK_MEM_TOTAL_GB pins the budget; a uname stub pins the
#    Linux rule on either OS (on macOS the build is metal whatever the key
#    says) and SPARK_SYSFS_DRM the GPU probe. 18 GB -> 10 GB budget: auto
#    (tested, open-license rows only) takes the largest row that fits AND stays under the
#    build's speed cap -- 3 GB files on cpu (qwen3-4b), 6 GB on vulkan
#    (qwen3-8b); qwen3-14b needs 11 GB, over this budget either way. With
#    the ember auto: the smallest row + the largest usable beside it.
#    SITE_AI_BUILD=auto (the default) = vulkan when a DRM device reports
#    VRAM, else cpu. A name is never second-guessed, and is looked up in
#    the whole list and yours, tested or not, any license.
#    6 GB -> 3 GB budget: the smallest row alone, no ember, nothing held
#    back.
mkdir -p "$T/os" "$T/drm/card0/device" "$T/nodrm"
printf '#!/bin/sh\ncase ${1:-} in -s) echo Linux ;; -m) echo x86_64 ;; *) exec /usr/bin/uname "$@" ;; esac\n' > "$T/os/uname"
chmod +x "$T/os/uname"
echo 8589934592 > "$T/drm/card0/device/mem_info_vram_total"
lm() { env PATH="$T/os:$PATH" SPARK_SYSFS_DRM="$T/nodrm" "$@" sh "$REPO/bootstrap.sh" --list-models 2>&1; }
printf 'SITE_AI_MODEL=auto\nSITE_EMBER_MODEL=auto\n' > "$HOME/.config/spark/site.env"
out=$(lm SPARK_MEM_TOTAL_GB=18 SITE_AI_BUILD=cpu) || bad "--list-models failed"
printf '%s\n' "$out" | grep -qx 'spark: qwen3-1-7b' && ok "18 GB cpu: spark is the smallest row" || bad "18 GB cpu spark line"
printf '%s\n' "$out" | grep -qx 'ember: qwen3-4b' && ok "18 GB cpu: ember is the largest under the 3 GB cap beside it" || bad "18 GB cpu ember line: $(printf '%s\n' "$out" | grep '^ember')"
printf '%s\n' "$out" | grep -qE '^\*  ?qwen3-1-7b ' && ok "spark pick marked *" || bad "* mark"
printf '%s\n' "$out" | grep -qE '^\+  ?qwen3-4b ' && ok "ember pick marked +" || bad "+ mark"
printf '%s\n' "$out" | grep -qx 'auto stops at 3 GB files on cpu (bigger fits, slower than 8 tok/s)' && ok "the header says what the cpu cap held back" || bad "no cap note: $(printf '%s\n' "$out" | head -3)"
printf '%s\n' "$out" | head -3 | awk 'length > 80 { bad = 1 } END { exit bad }' && ok "the header and the cap note fit 80 columns" || bad "a header line is wider than 80"
out=$(lm SPARK_MEM_TOTAL_GB=18 SITE_AI_BUILD=vulkan) || bad "--list-models failed"
printf '%s\n' "$out" | grep -qx 'ember: qwen3-8b' && ok "18 GB vulkan: ember is the largest under the 6 GB cap beside it" || bad "18 GB vulkan ember line"
printf 'SITE_AI_MODEL=auto\nSITE_EMBER_MODEL=none\n' > "$HOME/.config/spark/site.env"
out=$(lm SPARK_MEM_TOTAL_GB=18 SITE_AI_BUILD=cpu) || bad "--list-models failed"
printf '%s\n' "$out" | grep -qx 'spark: qwen3-4b' && ok "18 GB cpu: auto stops at the 3 GB cap (qwen3-4b, not a bigger tested row)" || bad "18 GB cpu spark line: $(printf '%s\n' "$out" | grep '^spark')"
printf '%s\n' "$out" | head -1 | grep -q ', cpu$' && ok "the header names the cpu build" || bad "header: $(printf '%s\n' "$out" | head -1)"
# a client (none + a peer): the rows, no budget, never this machine's RAM
printf 'SITE_AI_MODEL=none\nSITE_PEER_AI_URL=http://192.0.2.10:8081\n' > "$HOME/.config/spark/site.env"
out=$(lm SPARK_MEM_TOTAL_GB=24 SITE_AI_BUILD=cpu) || bad "--list-models failed on a client"
printf '%s\n' "$out" | head -1 | grep -q '^this machine is a client of http://192.0.2.10:8081' && ok "a client's --list-models names the peer" || bad "client header: $(printf '%s\n' "$out" | head -1)"
printf '%s\n' "$out" | grep -q '24 GB\|budget\| fits$\|^spark:\|^ember:' && bad "a client's --list-models printed a local budget or a pick" || ok "a client's --list-models has no budget, verdict or pick"
printf '%s\n' "$out" | grep -qE '^   qwen3-1-7b ' && ok "a client's --list-models still lists the rows" || bad "client rows: $(printf '%s\n' "$out" | sed -n 3p)"
printf 'SITE_AI_MODEL=auto\nSITE_EMBER_MODEL=none\n' > "$HOME/.config/spark/site.env"
# 19 GB -> 11 GB budget: qwen3-14b (11 GB) fits the budget but its 8.4 GB
# file is over the 6 GB vulkan cap, so auto still stops at qwen3-8b and
# the header says what the cap held back.
out=$(lm SPARK_MEM_TOTAL_GB=19 SITE_AI_BUILD=vulkan) || bad "--list-models failed"
printf '%s\n' "$out" | grep -qx 'spark: qwen3-8b' && ok "19 GB vulkan: auto stops at the 6 GB cap (qwen3-8b)" || bad "19 GB vulkan spark line"
printf '%s\n' "$out" | grep -qx 'auto stops at 6 GB files on vulkan (bigger fits, slower than 8 tok/s)' && ok "the header says what the vulkan cap held back" || bad "no vulkan cap note"
out=$(lm SPARK_MEM_TOTAL_GB=18 SPARK_SYSFS_DRM="$T/drm") || bad "--list-models failed"
printf '%s\n' "$out" | head -1 | grep -q ', vulkan$' && ok "SITE_AI_BUILD=auto: vulkan when a DRM device reports VRAM" || bad "auto with a GPU: $(printf '%s\n' "$out" | head -1)"
printf '%s\n' "$out" | grep -qx 'spark: qwen3-8b' && ok "auto with a GPU picks as vulkan" || bad "auto with a GPU spark line"
# SITE_AI_BUDGET=30 drops the budget to 5 GB (18 * 30 / 100): qwen3-4b
# (5 GB) still fits, qwen3-8b (7 GB) no longer does -- it would at the
# default 60 % (the case just above); the header names the percent too.
out=$(lm SPARK_MEM_TOTAL_GB=18 SITE_AI_BUILD=vulkan SITE_AI_BUDGET=30) || bad "--list-models failed"
printf '%s\n' "$out" | grep -qx 'spark: qwen3-4b' && ok "SITE_AI_BUDGET=30: the budget drops to 5 GB, qwen3-8b no longer fits" || bad "SITE_AI_BUDGET=30 spark line: $(printf '%s\n' "$out" | grep '^spark')"
printf '%s\n' "$out" | head -1 | grep -q 'budget 5 GB (30%)' && ok "the header names the SITE_AI_BUDGET percent" || bad "header: $(printf '%s\n' "$out" | head -1)"
out=$(lm SPARK_MEM_TOTAL_GB=18) || bad "--list-models failed"
printf '%s\n' "$out" | head -1 | grep -q ', cpu$' && ok "SITE_AI_BUILD=auto: cpu with no GPU in sysfs" || bad "auto without a GPU: $(printf '%s\n' "$out" | head -1)"
printf '%s\n' "$out" | grep -qx 'spark: qwen3-4b' && ok "auto without a GPU picks as cpu" || bad "auto without a GPU spark line"
out=$(lm SPARK_MEM_TOTAL_GB=18 SITE_AI_BUILD=cpu SITE_AI_MODEL=qwen3-14b) || bad "--list-models failed"
printf '%s\n' "$out" | grep -qx 'spark: qwen3-14b' && ok "a named model is never second-guessed" || bad "named model line"
printf '%s\n' "$out" | grep -q '^auto stops' && bad "a name printed the cap note" || ok "a name: no cap note"
# a name is looked up in the whole list, tested or not: an untested row
# and a non-open-license row, picked by name for the spark role
out=$(lm SPARK_MEM_TOTAL_GB=18 SITE_AI_BUILD=cpu SITE_AI_MODEL=qwen2-5-coder-7b) || bad "--list-models failed"
printf '%s\n' "$out" | grep -qx 'spark: qwen2-5-coder-7b' && ok "a named untested row is picked for spark too" || bad "named untested row: $(printf '%s\n' "$out" | grep '^spark')"
out=$(lm SPARK_MEM_TOTAL_GB=18 SITE_AI_BUILD=cpu SITE_AI_MODEL=gemma3-12b) || bad "--list-models failed"
printf '%s\n' "$out" | grep -qx 'spark: gemma3-12b' && ok "a named non-open row is picked for spark too" || bad "named non-open row: $(printf '%s\n' "$out" | grep '^spark')"
out=$(lm SPARK_MEM_TOTAL_GB=6 SITE_AI_BUILD=cpu) || bad "--list-models failed"
printf '%s\n' "$out" | grep -qx 'spark: qwen3-1-7b' && ok "6 GB: the smallest row alone" || bad "6 GB spark line"
printf '%s\n' "$out" | grep -qx 'ember: none' && ok "6 GB: no ember" || bad "6 GB ember line"
printf '%s\n' "$out" | grep -q '^auto stops' && bad "6 GB: a cap note with nothing held back" || ok "6 GB: nothing held back, no cap note"
# the package family is read from os-release, pinned like the kernel line:
# on a macOS dev box the uname stub says Linux and the family must be said too
printf 'ID=ubuntu\nID_LIKE=debian\nPRETTY_NAME="Ubuntu fixture"\n' > "$T/os-release-debian"
env PATH="$T/os:$PATH" SPARK_SYSFS_DRM="$T/drm" SPARK_OS_RELEASE="$T/os-release-debian" sh "$REPO/bootstrap.sh" --list-packages | grep -qx libvulkan1 && ok "auto with a GPU: --list-packages adds the vulkan libraries" || bad "vulkan packages missing with a GPU"
env PATH="$T/os:$PATH" SPARK_SYSFS_DRM="$T/nodrm" SPARK_OS_RELEASE="$T/os-release-debian" sh "$REPO/bootstrap.sh" --list-packages | grep -qx libvulkan1 && bad "no GPU: --list-packages still adds the vulkan libraries" || ok "auto without a GPU: no vulkan libraries"
# this OS as it is: macOS is metal whatever the key says, Linux cpu or
# vulkan. 24 GB -> 14 GB budget: qwen3-14b (11 GB) fits on metal (no cap
# there); on cpu the 3 GB cap still stops it at qwen3-4b.
out=$(SPARK_MEM_TOTAL_GB=24 SITE_AI_BUILD=cpu sh "$REPO/bootstrap.sh" --list-models 2>&1) || bad "--list-models failed"
case $(uname -s) in
    Darwin) printf '%s\n' "$out" | head -1 | grep -q ', metal$' && printf '%s\n' "$out" | grep -qx 'spark: qwen3-14b' && ok "macOS: metal, the key ignored, the largest that fits" || bad "macOS header/pick: $(printf '%s\n' "$out" | head -1)" ;;
    *) printf '%s\n' "$out" | head -1 | grep -qE ', (cpu|vulkan)$' && ok "Linux: the header names cpu or vulkan" || bad "Linux header: $(printf '%s\n' "$out" | head -1)" ;;
esac

# 9. WSL 2 (Linux only: the rows are Linux's): a kernel line naming
#    microsoft makes the console and quiet-boot rows honest skips and a
#    hand-set SITE_HEADLESS=yes a todo -- never a systemctl mask, no sudo
if [ "$(uname -s)" != Darwin ]; then
    printf 'Linux version 6.6.87.2-microsoft-standard-WSL2 (root@w) #1 SMP\n' > "$T/version-wsl"
    printf 'SITE_FONT_FACE=Terminus\nSITE_FONT_SIZE=16x32\nSITE_QUIET_BOOT=yes\nSITE_HEADLESS=yes\nSITE_AI_MODEL=none\n' > "$HOME/.config/spark/site.env"
    out=$(SPARK_PROC_VERSION="$T/version-wsl" PATH="$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (WSL 2) failed: $out"
    printf '%s\n' "$out" | grep -qE '^skip +console +WSL 2' && ok "WSL 2: the console row skips (the font is Windows Terminal's)" || bad "WSL 2 console row: $(printf '%s\n' "$out" | grep -E ' console ' | head -1)"
    printf '%s\n' "$out" | grep -qE '^skip +quiet-boot +WSL 2' && ok "WSL 2: the quiet-boot row skips (no GRUB)" || bad "WSL 2 quiet-boot row: $(printf '%s\n' "$out" | grep -E ' quiet-boot ' | head -1)"
    printf '%s\n' "$out" | grep -qE '^todo +headless +WSL 2' && ok "WSL 2: SITE_HEADLESS=yes is a todo, never a mask" || bad "WSL 2 headless: $(printf '%s\n' "$out" | grep -E ' headless | sleep ' | head -2)"
    printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "WSL 2 dry-run called sudo" || ok "WSL 2 dry-run: no sudo"
    # the console palette is root's: with a painted palette the vt-palette
    # row wants the boot unit (would, never sudo in a dry run); without one
    # it has nothing to do
    printf 'SITE_AI_MODEL=none\n' > "$HOME/.config/spark/site.env"
    printf '40,204,152,215,69,177,104,168,146,251,184,250,131,211,142,235\n40,36,151,153,133,135,157,153,131,73,187,189,165,134,192,219\n40,29,26,33,136,166,116,132,116,54,38,47,152,155,164,178\n' > "$HOME/.config/spark/console-colors.rgb"
    out=$(PATH="$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (palette) failed"
    printf '%s\n' "$out" | grep -qE '^(would|todo) +vt-palette ' && ok "a painted palette: the vt-palette row would install the boot unit (or names kbd)" || bad "vt-palette row: $(printf '%s\n' "$out" | grep -E ' vt-palette ' | head -1)"
    printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "vt-palette dry-run called sudo" || ok "vt-palette dry-run: no sudo"
    rm -f "$HOME/.config/spark/console-colors.rgb"
    out=$(PATH="$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run failed"
    printf '%s\n' "$out" | grep -qE '^skip +vt-palette +no palette painted yet' && ok "no palette: the vt-palette row skips" || bad "vt-palette skip: $(printf '%s\n' "$out" | grep -E ' vt-palette ' | head -1)"
fi

# 10. Arch (the second family): ID=arch in os-release, pinned by
#     SPARK_OS_RELEASE, and a pacman on PATH that answers -- the packages
#     row asks it, the console and quiet-boot rows are honest skips, never
#     sudo. The names come from distro/arch.env (both OSes, the uname stub);
#     the dry-run is Linux's (the rows are).
printf 'ID=arch\nPRETTY_NAME="Arch Linux"\n' > "$T/os-release-arch"
printf 'ID=manjaro\nID_LIKE=arch\nPRETTY_NAME="Manjaro Linux"\n' > "$T/os-release-manjaro"
lp() { env PATH="$T/os:$PATH" SPARK_SYSFS_DRM="$T/nodrm" SPARK_OS_RELEASE="$1" sh "$REPO/bootstrap.sh" --list-packages 2>&1; }
printf 'SITE_AI_MODEL=none\n' > "$HOME/.config/spark/site.env"
out=$(lp "$T/os-release-arch")
printf '%s\n' "$out" | grep -qx gcc-libs && printf '%s\n' "$out" | grep -qx kbd && ! printf '%s\n' "$out" | grep -qxE 'fd-find|libgomp1|tmux' \
    && ok "Arch: --list-packages speaks pacman's names (gcc-libs, kbd)" || bad "Arch --list-packages: $(printf '%s' "$out" | tr '\n' ' ')"
[ "$(lp "$T/os-release-manjaro")" = "$out" ] && ok "Manjaro (ID_LIKE=arch): the same list" || bad "Manjaro list differs"
lp "$T/os-release-debian" | grep -qx libgomp1 && ok "Ubuntu (ID_LIKE=debian): libgomp1 still" || bad "Ubuntu list lost libgomp1"
if [ "$(uname -s)" != Darwin ]; then
    mkdir -p "$T/arch"
    printf '#!/bin/sh\ncase $1 in -Qq) shift; printf "%%s\\n" "$@" ;; -Sp) exit 0 ;; *) exit 1 ;; esac\n' > "$T/arch/pacman"; chmod +x "$T/arch/pacman"
    printf 'SITE_FONT_FACE=Terminus\nSITE_FONT_SIZE=16x32\nSITE_QUIET_BOOT=yes\nSITE_AI_MODEL=none\n' > "$HOME/.config/spark/site.env"
    out=$(SPARK_OS_RELEASE="$T/os-release-arch" PATH="$T/arch:$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (Arch) failed: $out"
    printf '%s\n' "$out" | grep -qE '^ok +packages ' && ok "Arch: the packages row answers through pacman (everything installed)" || bad "Arch packages row: $(printf '%s\n' "$out" | grep -E ' packages ' | head -1)"
    printf '%s\n' "$out" | grep -qE '^skip +console +Arch' && ok "Arch: the console row skips (no console-setup)" || bad "Arch console row: $(printf '%s\n' "$out" | grep -E ' console ' | head -1)"
    printf '%s\n' "$out" | grep -qE '^skip +quiet-boot +Arch' && ok "Arch: the quiet-boot row skips (no update-grub)" || bad "Arch quiet-boot row: $(printf '%s\n' "$out" | grep -E ' quiet-boot ' | head -1)"
    printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "Arch dry-run called sudo" || ok "Arch dry-run: no sudo"
    # a pacman that knows nothing installed: the row would install, as root
    printf '#!/bin/sh\ncase $1 in -Sp) exit 0 ;; *) exit 1 ;; esac\n' > "$T/arch/pacman"; chmod +x "$T/arch/pacman"
    out=$(SPARK_OS_RELEASE="$T/os-release-arch" PATH="$T/arch:$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (Arch, bare) failed: $out"
    printf '%s\n' "$out" | grep -qE '^would +packages +install:.*\(sudo\)$' && ok "Arch, nothing installed: the packages row would install (sudo)" || bad "Arch bare packages row: $(printf '%s\n' "$out" | grep -E ' packages ' | head -1)"
    printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "Arch bare dry-run called sudo" || ok "Arch bare dry-run: no sudo"
fi

[ "$fail" -eq 0 ] && echo "install_test: all ok" || { echo "install_test: FAILED"; exit 1; }
