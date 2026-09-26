#!/bin/sh
# spark tests/install_test.sh -- install.sh against a throwaway HOME.
# Proves contract 2: the row shapes, link/render/back-up semantics,
# idempotence, and that a bad theme name is refused.
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

# 4. a bad theme name (bootstrap's theme row) and shell syntax in
#    site.env (site_load, both scripts) are refused
printf 'SITE_THEME=nope\n' > "$HOME/.config/spark/site.env"
if sh "$REPO/bootstrap.sh" --dry-run >/dev/null 2>&1; then bad "unknown theme accepted"; else ok "unknown theme refused"; fi
printf 'SITE_THEME=none; rm -rf /\n' > "$HOME/.config/spark/site.env"
if run >/dev/null 2>&1; then bad "shell syntax in site.env accepted"; else ok "shell syntax in site.env refused"; fi
printf 'SITE_THEME=none\n' > "$HOME/.config/spark/site.env"

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
printf '%s\n' "$out" | grep -qE '^skip +console +(macOS:|SITE_FONT_FACE unset)' && ok "the console row is core, its skip names its own reason" || bad "console row: $(printf '%s\n' "$out" | grep -E ' console ' | head -1)"
printf '%s\n' "$out" | grep -qE '^skip +hostname +SITE_SET_HOSTNAME=no' && ok "the hostname row is core (identity), its skip names its key" || bad "hostname row: $(printf '%s\n' "$out" | grep -E ' hostname ' | head -1)"
printf '%s\n' "$out" | grep -qE ' micro-aspell ' && bad "a micro-aspell row survives (spark ships no app)" || ok "no micro-aspell row: spark installs no editor"
printf '%s\n' "$out" | grep -qE "^would +dir +mkdir .*/projects" && bad "the workspace folder would be made" || ok "no workspace folder for a new user"
[ "$(uname -s)" = Darwin ] && { printf '%s\n' "$out" | grep -qE '^ok +packages +nothing required' && ok "macOS: packages row is ok, nothing required" || bad "macOS packages row"; }
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

# 9c. quiet-login restores only spark's own trace (Linux: the row is
#     Linux's). A stock Ubuntu -- no /etc/motd, the distro's file at
#     /usr/share/base-files/motd -- with SITE_QUIET_LOGIN=no was never
#     quieted by spark: the row is a skip (loud already), never a
#     `would ... (sudo)` that writes /etc/motd as root. With spark's
#     own motd.orig beside it, the restore is offered.
if [ "$(uname -s)" != Darwin ]; then
    mkdir -p "$T/etc"
    printf 'SITE_AI_MODEL=none\nSITE_QUIET_LOGIN=no\n' > "$HOME/.config/spark/site.env"
    ql() { SPARK_ETC_MOTD="$T/etc/motd" SPARK_ETC_ISSUE="$T/etc/issue" SPARK_ETC_UNAME_MOTD="$T/etc/10-uname" \
           PATH="$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1; }
    out=$(ql) || bad "bootstrap --dry-run (stock, no .orig) failed: $out"
    printf '%s\n' "$out" | grep -qE '^skip +quiet-login +loud' && ok "quiet-login: a stock box with no .orig is loud already (skip, not would)" || bad "quiet-login stock: $(printf '%s\n' "$out" | grep -E ' quiet-login ' | head -1)"
    printf 'the distro notice\n' > "$T/etc/motd.orig"
    out=$(ql) || bad "bootstrap --dry-run (with .orig) failed: $out"
    printf '%s\n' "$out" | grep -qE '^would +quiet-login +restore' && ok "quiet-login: spark's own motd.orig makes the restore a would row" || bad "quiet-login .orig: $(printf '%s\n' "$out" | grep -E ' quiet-login ' | head -1)"
    rm -f "$T/etc/motd.orig"
    printf 'SITE_AI_MODEL=none\n' > "$HOME/.config/spark/site.env"
fi

# 10. Arch (the second family): ID=arch in os-release, pinned by
#     SPARK_OS_RELEASE, and a pacman on PATH that answers -- the packages
#     row asks it, the console row writes vconsole.conf's FONT= and, without
#     a UKI, the quiet-boot row is an honest skip; never sudo. The names come from distro/arch.env (both OSes, the uname stub);
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
    printf 'KEYMAP=us\nFONT=default8x16\n' > "$T/vconsole.conf"
    out=$(SPARK_OS_RELEASE="$T/os-release-arch" SPARK_ETC_MKINITCPIO_D="$T/no-mkinitcpio.d" SPARK_ETC_CONSOLE_SETUP="$T/no-console-setup" SPARK_ETC_VCONSOLE="$T/vconsole.conf" PATH="$T/arch:$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (Arch) failed: $out"
    printf '%s\n' "$out" | grep -qE '^ok +packages ' && ok "Arch: the packages row answers through pacman (everything installed)" || bad "Arch packages row: $(printf '%s\n' "$out" | grep -E ' packages ' | head -1)"
    printf '%s\n' "$out" | grep -qE '^would +console +FONT=Terminus in .*vconsole.conf; systemd-vconsole-setup' && ok "Arch: the console row would write FONT= into vconsole.conf (the vconsole shape, by mechanism)" || bad "Arch console row: $(printf '%s\n' "$out" | grep -E ' console ' | head -1)"
    printf '%s\n' "$out" | grep -qE '^skip +quiet-boot +Arch without a UKI' && ok "Arch: the quiet-boot row skips (no UKI: the kernel line is the boot loader's)" || bad "Arch quiet-boot row: $(printf '%s\n' "$out" | grep -E ' quiet-boot ' | head -1)"
    printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "Arch dry-run called sudo" || ok "Arch dry-run: no sudo"
    printf 'KEYMAP=us\nFONT=Terminus\n' > "$T/vconsole.conf"
    out=$(SPARK_OS_RELEASE="$T/os-release-arch" SPARK_ETC_MKINITCPIO_D="$T/no-mkinitcpio.d" SPARK_ETC_CONSOLE_SETUP="$T/no-console-setup" SPARK_ETC_VCONSOLE="$T/vconsole.conf" PATH="$T/arch:$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (Arch, font set) failed: $out"
    printf '%s\n' "$out" | grep -qE '^ok +console +Terminus 16x32 \(.*vconsole.conf\)' && ok "Arch: vconsole.conf already naming the face is ok" || bad "Arch console ok row: $(printf '%s\n' "$out" | grep -E ' console ' | head -1)"
    out=$(SPARK_OS_RELEASE="$T/os-release-arch" SPARK_ETC_MKINITCPIO_D="$T/no-mkinitcpio.d" SPARK_ETC_CONSOLE_SETUP="$T/no-console-setup" SPARK_ETC_VCONSOLE="$T/no-vconsole" PATH="$T/arch:$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (no console file) failed: $out"
    printf '%s\n' "$out" | grep -qE '^skip +console +no console-setup, vconsole.conf or rc.conf' && ok "no console file: the console row skips, naming both" || bad "bare console row: $(printf '%s\n' "$out" | grep -E ' console ' | head -1)"
    # 10a. Arch with a Unified Kernel Image (a preset's `default_uki=`, the
    #     splash on its `default_options`): the quiet-boot row is REAL --
    #     a would row naming the cmdline.d drop-in, never sudo in a dry
    #     run; with the drop-in holding the words and the splash marked
    #     off, ok; with the key off and the drop-in still there, a would
    #     row puts the loud back. Both files are seamed (SPARK_ETC_*).
    mkdir -p "$T/mkinitcpio.d"
    printf 'ALL_kver="/boot/vmlinuz-linux"\nPRESETS=(%s)\ndefault_uki="/boot/EFI/Linux/arch-linux.efi"\ndefault_options="--splash /usr/share/systemd/bootctl/splash-arch.bmp"\n' "'default'" > "$T/mkinitcpio.d/linux.preset"
    ukienv() { env SPARK_OS_RELEASE="$T/os-release-arch" SPARK_ETC_MKINITCPIO_D="$T/mkinitcpio.d" SPARK_ETC_CMDLINE_DROPIN="$T/zz-spark-quiet.conf" PATH="$T/arch:$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1; }
    out=$(ukienv) || bad "bootstrap --dry-run (Arch UKI) failed: $out"
    printf '%s\n' "$out" | grep -qE '^would +quiet-boot +cmdline.d drop-in .*zz-spark-quiet.conf' && ok "Arch UKI: the quiet-boot row would write the cmdline.d drop-in, mark the splash, rebuild" || bad "Arch UKI quiet-boot row: $(printf '%s\n' "$out" | grep -E ' quiet-boot ' | head -1)"
    printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "Arch UKI dry-run called sudo" || ok "Arch UKI dry-run: no sudo"
    printf '%s\n' 'quiet splash loglevel=3 systemd.show_status=false udev.log_level=3 vt.global_cursor_default=0 fbcon=nodefer' > "$T/zz-spark-quiet.conf"
    printf 'ALL_kver="/boot/vmlinuz-linux"\nPRESETS=(%s)\ndefault_uki="/boot/EFI/Linux/arch-linux.efi"\n#spark-quiet# default_options="--splash /usr/share/systemd/bootctl/splash-arch.bmp"\n' "'default'" > "$T/mkinitcpio.d/linux.preset"
    out=$(ukienv) || bad "bootstrap --dry-run (Arch UKI, quiet) failed: $out"
    printf '%s\n' "$out" | grep -qE '^ok +quiet-boot +silent' && ok "Arch UKI: the drop-in with the words and the splash marked off is ok" || bad "Arch UKI quiet row: $(printf '%s\n' "$out" | grep -E ' quiet-boot ' | head -1)"
    printf 'SITE_FONT_FACE=Terminus\nSITE_FONT_SIZE=16x32\nSITE_QUIET_BOOT=no\nSITE_AI_MODEL=none\n' > "$HOME/.config/spark/site.env"
    out=$(ukienv) || bad "bootstrap --dry-run (Arch UKI, off) failed: $out"
    printf '%s\n' "$out" | grep -qE '^would +quiet-boot +show the boot menu again' && ok "Arch UKI, key off with the drop-in there: a would row puts the loud back (never sudo in a dry run)" || bad "Arch UKI off row: $(printf '%s\n' "$out" | grep -E ' quiet-boot ' | head -1)"
    printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "Arch UKI off dry-run called sudo" || ok "Arch UKI off dry-run: no sudo"
    rm -f "$T/zz-spark-quiet.conf"
    printf 'SITE_FONT_FACE=Terminus\nSITE_FONT_SIZE=16x32\nSITE_QUIET_BOOT=yes\nSITE_AI_MODEL=none\n' > "$HOME/.config/spark/site.env"
    # a pacman that knows nothing installed: the row would install, as root
    printf '#!/bin/sh\ncase $1 in -Sp) exit 0 ;; *) exit 1 ;; esac\n' > "$T/arch/pacman"; chmod +x "$T/arch/pacman"
    out=$(SPARK_OS_RELEASE="$T/os-release-arch" PATH="$T/arch:$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (Arch, bare) failed: $out"
    printf '%s\n' "$out" | grep -qE '^would +packages +install:.*\(sudo\)$' && ok "Arch, nothing installed: the packages row would install (sudo)" || bad "Arch bare packages row: $(printf '%s\n' "$out" | grep -E ' packages ' | head -1)"
    printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "Arch bare dry-run called sudo" || ok "Arch bare dry-run: no sudo"
    # 10b. a CLIENT on the same bare box: no root row at all -- the dry
    # run holds no `sudo` word, and an APPLY makes no as_root call (the
    # sudo stub would shout SUDO CALLED); python3 and curl are all it runs
    printf 'SITE_AI_MODEL=none\nSITE_PEER_AI_URL=http://192.0.2.10:8081\nSITE_SET_HOSTNAME=yes\nSITE_FONT_FACE=Terminus\nSITE_FONT_SIZE=16x32\nSITE_QUIET_BOOT=yes\nSITE_QUIET_LOGIN=yes\n' > "$HOME/.config/spark/site.env"
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
#     whether it is booted) and rc.conf beside it is the console's file. The
#     names come from distro/void.env (both OSes, the uname stub); the dry
#     runs and the apply are Linux's (the rows are). The sudo stub shouts: a
#     dry run never reaches it, and the links into a runsvdir of your own
#     need no root.
printf 'ID="void"\nPRETTY_NAME="Void Linux"\n' > "$T/os-release-void"
out=$(lp "$T/os-release-void")
printf '%s\n' "$out" | grep -qx libgomp && printf '%s\n' "$out" | grep -qx kbd && printf '%s\n' "$out" | grep -qx python3 \
    && ! printf '%s\n' "$out" | grep -qxE 'gcc-libs|libgomp1|python|fd-find|tmux' \
    && ok "Void: --list-packages speaks xbps's names (libgomp, kbd, python3)" || bad "Void --list-packages: $(printf '%s' "$out" | tr '\n' ' ')"
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
            SPARK_ETC_SV="$V/sv-etc" SPARK_ETC_CONSOLE_SETUP="$V/no-console-setup" SPARK_ETC_VCONSOLE="$V/no-vconsole" SPARK_ETC_RCCONF="$V/rc.conf" \
            SPARK_ETC_MKINITCPIO_D="$T/no-mkinitcpio.d" SPARK_ETC_CMDLINE_DROPIN="$T/no-cmdline.conf" \
            SPARK_ETC_MOTD="$T/etc/motd" SPARK_ETC_ISSUE="$T/etc/issue" SPARK_ETC_UNAME_MOTD="$T/etc/10-uname" \
            SPARK_SHARE_TOKEN="$V/no-share-token" SPARK_SHARE_URL="$V/no-share-url" \
            SV_LOG="$V/sv.log" PATH="$V/bin:$T/bin:$PATH" "$@"
    }
    # 11a. a container (no /var/service): the packages row answers through
    #      xbps, the services wait, quiet boot is Void's own, linger, sleep
    #      and the lid are runit's skips, and the console row writes rc.conf's
    #      FONT= (a commented #FONT= line is the one it takes over) with
    #      setfont to redraw; never sudo
    printf 'SITE_FONT_FACE=Terminus\nSITE_FONT_SIZE=16x32\nSITE_QUIET_BOOT=yes\nSITE_AI_MODEL=none\n' > "$HOME/.config/spark/site.env"
    printf '# /etc/rc.conf - system configuration for void\n#KEYMAP="us"\n#FONT="lat9w-16"\n' > "$V/rc.conf"
    out=$(vrun sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (Void) failed: $out"
    printf '%s\n' "$out" | grep -qE '^skip +runit +runit is not running here' && ok "Void, a container: the runit row skips (the services wait for a machine that boots)" || bad "Void runit row: $(printf '%s\n' "$out" | grep -E ' runit ' | head -1)"
    printf '%s\n' "$out" | grep -qE '^ok +packages ' && ok "Void: the packages row answers through xbps (everything installed)" || bad "Void packages row: $(printf '%s\n' "$out" | grep -E ' packages ' | head -1)"
    printf '%s\n' "$out" | grep -qE '^skip +quiet-boot +Void' && ok "Void: the quiet-boot row skips (GRUB reads no drop-in)" || bad "Void quiet-boot row: $(printf '%s\n' "$out" | grep -E ' quiet-boot ' | head -1)"
    printf '%s\n' "$out" | grep -qE '^skip +linger +runit' && ok "Void: linger skips (the supervisor runs from boot, login or not)" || bad "Void linger row: $(printf '%s\n' "$out" | grep -E ' linger ' | head -1)"
    printf '%s\n' "$out" | grep -qE '^skip +sleep +runit' && printf '%s\n' "$out" | grep -qE '^skip +lid +runit' && ok "Void: sleep and lid skip (no sleep targets, no logind)" || bad "Void sleep/lid rows: $(printf '%s\n' "$out" | grep -E ' (sleep|lid) ' | head -2 | tr '\n' ' ')"
    printf '%s\n' "$out" | grep -qE '^would +console +FONT=Terminus in .*rc.conf; setfont' && ok "Void: the console row would write FONT= into rc.conf and setfont (the rcconf shape, by mechanism)" || bad "Void console row: $(printf '%s\n' "$out" | grep -E ' console ' | head -1)"
    printf '%s\n' "$out" | grep -qE '^(ok|would|skip|todo) +spark-(check|serve|forge) ' && bad "a container: a service row spoke: $(printf '%s\n' "$out" | grep -E '^(ok|would|skip|todo) +spark-' | head -1)" || ok "a container: no service row (they wait with runit)"
    printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "Void dry-run called sudo" || ok "Void dry-run: no sudo"
    printf '# /etc/rc.conf\n#KEYMAP="us"\nFONT="Terminus"\n' > "$V/rc.conf"
    out=$(vrun sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (Void, font set) failed: $out"
    printf '%s\n' "$out" | grep -qE '^ok +console +Terminus 16x32 \(.*rc.conf\)' && ok "Void: rc.conf already naming the face (quoted, as Void writes it) is ok" || bad "Void console ok row: $(printf '%s\n' "$out" | grep -E ' console ' | head -1)"
    out=$(vrun SPARK_ETC_RCCONF="$V/no-rc.conf" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (Void, no console file) failed: $out"
    printf '%s\n' "$out" | grep -qE '^skip +console +no console-setup, vconsole.conf or rc.conf' && ok "Void without rc.conf: the console row skips, naming the three files" || bad "Void bare console row: $(printf '%s\n' "$out" | grep -E ' console ' | head -1)"
    # 11b. runit LIVE (/var/service is a dir), no runsvdir-USER yet: the
    #      supervisor row would write the root service and link it (sudo),
    #      spark-check would come up; a dry run says so and changes nothing
    #      through sv
    out=$(vrun SPARK_VAR_SERVICE="$V/service" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (Void, runit live) failed: $out"
    printf '%s\n' "$out" | grep -qE '^would +supervisor +write .*runsvdir-.*, link it into .*/service \(sudo\)$' && ok "runit live, no root service: the supervisor row would write runsvdir-USER and link it (sudo)" || bad "supervisor row: $(printf '%s\n' "$out" | grep -E ' supervisor ' | head -1)"
    printf '%s\n' "$out" | grep -qE '^would +spark-check +sv up ~/\.config/spark/sv/spark-check$' && ok "runit live: spark-check would come up (sv up, the dir spelled with ~)" || bad "spark-check row: $(printf '%s\n' "$out" | grep -E ' spark-check ' | head -1)"
    printf '%s\n' "$out" | grep -qE '^(ok|would|skip|todo) +runit ' && bad "runit live: the runit skip row survives" || ok "runit live: no runit skip row"
    printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "runit live dry-run called sudo" || ok "runit live dry-run: no sudo"
    grep -qE '^sv (up|down|restart|exit) ' "$V/sv.log" 2>/dev/null && bad "a dry run changed a service: $(grep -E '^sv (up|down|restart|exit) ' "$V/sv.log" | head -1)" || ok "a dry run asks sv status and nothing more"
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
    printf 'SITE_QUIET_BOOT=yes\nSITE_AI_MODEL=none\n' > "$HOME/.config/spark/site.env"
    rm -f "$V/sv.log"
    out=$(vrun SPARK_VAR_SERVICE="$V/service" sh "$REPO/bootstrap.sh" </dev/null 2>&1) || bad "bootstrap apply (Void, your runsvdir) failed: $(printf '%s\n' "$out" | tail -5 | tr '\n' ' ')"
    printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "the apply called as_root: $(printf '%s\n' "$out" | grep 'SUDO CALLED' | head -1)" || ok "your runsvdir apply: no as_root call (the links are yours)"
    printf '%s\n' "$out" | grep -qE "^ok +supervisor +your runsvdir-$me supervises .*/service; spark's services are linked there$" && ok "your runsvdir apply: the supervisor row says yours, linked" || bad "supervisor row: $(printf '%s\n' "$out" | grep -E ' supervisor ' | head -1)"
    linked=1
    for s in spark-check spark-serve spark-forge; do [ "$(readlink "$HOME/service/$s" 2>/dev/null)" = "$svd/$s" ] || linked=0; done
    [ "$linked" = 1 ] && ok "your runsvdir apply: the three symlinks point into ~/.config/spark/sv/" || bad "links: $(ls -l "$HOME/service" 2>&1 | tr '\n' ' ')"
    printf '%s\n' "$out" | grep -qE '^ok +spark-check +supervised \(run\)$' && ok "your runsvdir apply: spark-check is supervised (run)" || bad "spark-check row: $(printf '%s\n' "$out" | grep -E ' spark-check ' | head -1)"
    [ ! -e "$svd/spark-check/down" ] && [ -f "$svd/spark-serve/down" ] && [ -f "$svd/spark-forge/down" ] && ok "your runsvdir apply: spark-check's down file went; serve and forge keep theirs (no model here)" || bad "down files: $(ls "$svd"/*/down 2>&1 | tr '\n' ' ')"
    grep -qxF "sv up $svd/spark-check" "$V/sv.log" && ! grep -qE '^sv (up|down|restart|exit) .*spark-(serve|forge)$' "$V/sv.log" && ok "your runsvdir apply: sv up spark-check, nothing else moved through sv" || bad "sv log: $(grep -vE '^sv status' "$V/sv.log" 2>/dev/null | tr '\n' ' ')"
    out=$(vrun SPARK_VAR_SERVICE="$V/service" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (Void, converged) failed: $out"
    printf '%s\n' "$out" | grep -qE "^ok +supervisor +your runsvdir-$me " && printf '%s\n' "$out" | grep -qE '^ok +spark-check +supervised \(run\)$' \
        && printf '%s\n' "$out" | grep -qE '^skip +spark-serve +on demand \(' && printf '%s\n' "$out" | grep -qE '^skip +spark-forge +off \(' \
        && ok "converged: supervisor and spark-check ok, serve on demand, forge off" || bad "converged rows: $(printf '%s\n' "$out" | grep -E ' (supervisor|spark-check|spark-serve|spark-forge) ' | tr '\n' ' ')"
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

[ "$fail" -eq 0 ] && echo "install_test: all ok" || { echo "install_test: FAILED"; exit 1; }
