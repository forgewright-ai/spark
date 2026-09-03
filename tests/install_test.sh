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

# 1. dry-run on an empty HOME (SITE_SHELL unset: the AI layer only): only
#    `would` rows, nothing created
out=$(run --dry-run)
if printf '%s\n' "$out" | grep -qE '^(ok|link|render|back up) '; then bad "dry-run printed a non-would row"; else ok "dry-run prints only would rows"; fi
printf '%s\n' "$out" | grep -q '^would link .*\.config/spark/spark.env.example$' && ok "would link a home/ file" || bad "would link"
printf '%s\n' "$out" | grep -q '^would .*\.gitconfig$' && bad "SITE_SHELL unset: .gitconfig announced" || ok "SITE_SHELL unset: no .gitconfig row"
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
    [ ! -e "$HOME/$f" ] && [ ! -L "$HOME/$f" ] || bad "SITE_SHELL unset: $f was installed"
done
ok "SITE_SHELL unset: no rc file, no .gitconfig, .tmux.conf, btop or starship"
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

# 2b. SITE_SHELL=on adds the shell layer on top: the rc files linked, the
#     templates rendered; then Nothing to do again
printf 'SITE_SHELL=on\n' > "$HOME/.config/spark/site.env"
out=$(run --dry-run)
printf '%s\n' "$out" | grep -q '^would render .*\.gitconfig$' && ok "SITE_SHELL=on: would render .gitconfig" || bad "would render"
case $(uname -s) in Darwin) rc=.zshrc ;; *) rc=.bashrc ;; esac
printf '%s\n' "$out" | grep -q "^would link .*/$rc\$" && ok "SITE_SHELL=on: would link $rc" || bad "would link $rc"
run >/dev/null
[ -L "$HOME/$rc" ] && ok "$rc is a symlink" || bad "$rc not linked"
[ -L "$HOME/.config/micro/bindings.json" ] && ok "micro bindings linked" || bad "micro bindings"
[ -f "$HOME/.gitconfig" ] && [ ! -L "$HOME/.gitconfig" ] && ok ".gitconfig is a regular file" || bad ".gitconfig"
grep -q "name = $(id -un)" "$HOME/.gitconfig" && ok "git name defaulted to the login" || bad "git name default"
[ -f "$HOME/.config/starship.toml" ] && grep -q 'bold blue' "$HOME/.config/starship.toml" && ok "starship minimal with neutral colours" || bad "starship render"
grep -q 'bg=default,fg=default' "$HOME/.tmux.conf" && ok "tmux neutral colours" || bad "tmux neutral"
grep -q '@' "$HOME/.tmux.conf" && bad "unrendered placeholder in .tmux.conf" || ok "no placeholders left"
[ -f "$HOME/.config/btop/btop.conf" ] && ok "btop.conf rendered" || bad "btop.conf"
out=$(run)
[ "$(printf '%s\n' "$out" | tail -1)" = "Nothing to do" ] && ok "shell layer, second run: Nothing to do" || bad "not idempotent: $(printf '%s\n' "$out" | grep -v '^ok' | head -3)"

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

# 4. a file spark rendered is re-rendered in place (its header says whose it
#    is); a file someone else wrote in that spot is backed up first; and a
#    stale symlink is replaced
echo edited >> "$HOME/.gitconfig"
run >/dev/null
[ ! -f "$HOME/.gitconfig.bak" ] && ! grep -q edited "$HOME/.gitconfig" && ok "edited render re-rendered, no .bak" || bad "render re-render"
printf '[user]\n\tname = theirs\n' > "$HOME/.gitconfig"
run >/dev/null
[ -f "$HOME/.gitconfig.bak" ] && grep -q theirs "$HOME/.gitconfig.bak" && ok "a foreign file in a render's place is backed up" || bad "foreign file back-up"
rm "$HOME/.tmux.conf"; ln -s /nonexistent "$HOME/.tmux.conf"
run >/dev/null
[ -f "$HOME/.tmux.conf" ] && [ ! -L "$HOME/.tmux.conf" ] && ok "stale symlink replaced by a render" || bad "stale link"

# 5. every palette and both prompt styles render without a leftover
#    placeholder (the shell layer on: that is where the palette lands)
for theme in none catppuccin-mocha selenized-dark gruvbox-dark solarized-light; do
    for style in minimal full; do
        printf 'SITE_SHELL=on\nSITE_THEME=%s\nSITE_PROMPT_STYLE=%s\n' "$theme" "$style" > "$HOME/.config/spark/site.env"
        if out=$(run); then
            grep -q '@[A-Z_0-9]*@' "$HOME/.config/starship.toml" "$HOME/.tmux.conf" && bad "$theme/$style placeholder" || ok "$theme / $style"
        else
            bad "$theme/$style: $out"
        fi
    done
done
grep -q '#fdf6e3' "$HOME/.tmux.conf" && ok "last palette (solarized-light) reached tmux" || bad "palette not rendered"

# 6. plain prompt renders no starship.toml; a bad theme name is refused
rm -f "$HOME/.config/starship.toml"
printf 'SITE_SHELL=on\nSITE_PROMPT=plain\n' > "$HOME/.config/spark/site.env"
run >/dev/null
[ ! -e "$HOME/.config/starship.toml" ] && ok "plain prompt: no starship.toml" || bad "starship rendered for plain"
printf 'SITE_THEME=nope\n' > "$HOME/.config/spark/site.env"
if run >/dev/null 2>&1; then bad "unknown theme accepted"; else ok "unknown theme refused"; fi
printf 'SITE_THEME=none; rm -rf /\n' > "$HOME/.config/spark/site.env"
if run >/dev/null 2>&1; then bad "shell syntax in site.env accepted"; else ok "shell syntax in site.env refused"; fi

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
case $(uname -s) in Darwin) SHELL=/bin/zsh ;; *) SHELL=/bin/bash ;; esac
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
# the shell layer off (SITE_SHELL unset): every shell row is a skip naming the key
case $(uname -s) in Darwin) srows="dir hostname theme pinned micro-aspell terminfo console quiet" ;; *) srows="dir hostname theme starship font micro-aspell terminfo console quiet-login quiet-boot" ;; esac
for r in $srows; do
    printf '%s\n' "$out" | grep -qE "^skip +$r +SITE_SHELL=off" && ok "SITE_SHELL unset: skip $r" || bad "SITE_SHELL unset: no skip row for $r: $(printf '%s\n' "$out" | grep -E " $r " | head -1)"
done
printf '%s\n' "$out" | grep -qE "^would +dir +mkdir .*/projects" && bad "SITE_SHELL unset: the workspace folder would be made" || ok "SITE_SHELL unset: no workspace folder for a stranger"
[ "$(uname -s)" = Darwin ] && { printf '%s\n' "$out" | grep -qE '^ok +brew +nothing required' && ok "SITE_SHELL unset: brew row is ok, nothing required" || bad "brew row with the shell off"; }
[ -z "$(sh "$REPO/bootstrap.sh" --list-packages | grep -E '^(tmux|starship|micro|bat|eza|fzf|btop|shellcheck)$')" ] && ok "SITE_SHELL unset: --list-packages has no shell package" || bad "--list-packages lists shell packages with the shell off"
printf 'SITE_HEADLESS=no\nSITE_AI_MODEL=none\n' > "$HOME/.config/spark/site.env"
out=$(PATH="$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run failed"
printf '%s\n' "$out" | grep -qE '^(skip|would) +sleep ' && ok "SITE_HEADLESS=no: sleep row is skip (or would undo)" || bad "no sleep row for SITE_HEADLESS=no"
[ "$(uname -s)" = Darwin ] || { printf '%s\n' "$out" | grep -qE '^skip +linger ' && ok "SITE_HEADLESS=no: linger is skipped" || bad "linger row with SITE_HEADLESS=no"; }
printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "dry-run called sudo" || ok "dry-run never called sudo (workstation)"
# the shell layer on: the shell rows are announced (would or ok), still no sudo
printf 'SITE_SHELL=on\nSITE_HEADLESS=no\nSITE_AI_MODEL=none\n' > "$HOME/.config/spark/site.env"
out=$(PATH="$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (shell on) failed: $(printf '%s\n' "$out" | tail -3)"
case $(uname -s) in
    Darwin) printf '%s\n' "$out" | grep -qE '^skip +pinned +Homebrew' && ok "SITE_SHELL=on: pinned names Homebrew" || bad "SITE_SHELL=on: pinned row"
            printf '%s\n' "$out" | grep -qE '^(ok|would|todo) +brew ' && ok "SITE_SHELL=on: the brew row reads the Brewfile" || bad "SITE_SHELL=on: brew row" ;;
    *)      for r in starship font; do
                printf '%s\n' "$out" | grep -qE "^(ok|would) +$r " && ok "SITE_SHELL=on: $r announced" || bad "SITE_SHELL=on: no $r row"
            done ;;
esac
printf '%s\n' "$out" | grep -qE '^skip +[a-z-]+ +SITE_SHELL=off' && bad "SITE_SHELL=on still skips a shell row" || ok "SITE_SHELL=on: no shell row skipped"
ln -sfn "$REPO/$([ "$rc" = .zshrc ] && echo macos || echo linux)/home/$rc" "$HOME/$rc"
out=$(PATH="$T/bin:$PATH" sh "$REPO/bootstrap.sh" --dry-run 2>&1) || bad "bootstrap --dry-run (rc linked) failed"
printf '%s\n' "$out" | grep -qE "^ok +rc +~/$rc is spark's own" && ok "rc: spark's own rc file: ok rc is spark's own" || bad "rc: linked: $(printf '%s\n' "$out" | grep -E ' rc ')"
printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "dry-run called sudo (shell on)" || ok "dry-run never called sudo (shell on)"
printf '%s\n' "$out" | tail -1 | grep -qE '^([0-9]+ to do|Nothing to do)$' && ok "shell-on dry-run ends with a count line" || bad "no count line (shell on)"
sh "$REPO/bootstrap.sh" --list-packages | grep -qx tmux && ok "SITE_SHELL=on: --list-packages has tmux" || bad "--list-packages lacks tmux with the shell on"

# 8. bootstrap --list-models names both roles' picks (the choosing rule;
#    lib/spark engine.chosen_rows is the twin, tests/smoke.py pins it the
#    same way). SPARK_MEM_TOTAL_GB pins the budget; a uname stub pins the
#    Linux rule on either OS (on macOS the build is metal whatever the key
#    says) and SPARK_SYSFS_DRM the GPU probe. 18 GB -> 10 GB budget: auto
#    (curated only) takes the largest row that fits AND stays under the
#    build's speed cap -- 3 GB files on cpu (qwen3-4b), 6 GB on vulkan
#    (qwen3-8b); qwen3-14b needs 11 GB, over this budget either way. With
#    the ember auto: the smallest row + the largest usable beside it.
#    SITE_AI_BUILD=auto (the default) = vulkan when a DRM device reports
#    VRAM, else cpu. A name is never second-guessed, and is looked up in
#    all four lists (curated, embers, community, yours), not curated only.
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
printf '%s\n' "$out" | grep -qx 'spark: qwen3-4b' && ok "18 GB cpu: auto stops at the 3 GB cap (qwen3-4b, not a bigger curated row)" || bad "18 GB cpu spark line: $(printf '%s\n' "$out" | grep '^spark')"
printf '%s\n' "$out" | head -1 | grep -q ', cpu$' && ok "the header names the cpu build" || bad "header: $(printf '%s\n' "$out" | head -1)"
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
# a name is looked up in all four lists, not curated only: an ember row
# and a community row, picked by name for the spark role
out=$(lm SPARK_MEM_TOTAL_GB=18 SITE_AI_BUILD=cpu SITE_AI_MODEL=qwen2-5-coder-7b) || bad "--list-models failed"
printf '%s\n' "$out" | grep -qx 'spark: qwen2-5-coder-7b' && ok "a named ember row is picked for spark too" || bad "named ember row: $(printf '%s\n' "$out" | grep '^spark')"
out=$(lm SPARK_MEM_TOTAL_GB=18 SITE_AI_BUILD=cpu SITE_AI_MODEL=gemma3-12b) || bad "--list-models failed"
printf '%s\n' "$out" | grep -qx 'spark: gemma3-12b' && ok "a named community row is picked for spark too" || bad "named community row: $(printf '%s\n' "$out" | grep '^spark')"
out=$(lm SPARK_MEM_TOTAL_GB=6 SITE_AI_BUILD=cpu) || bad "--list-models failed"
printf '%s\n' "$out" | grep -qx 'spark: qwen3-1-7b' && ok "6 GB: the smallest row alone" || bad "6 GB spark line"
printf '%s\n' "$out" | grep -qx 'ember: none' && ok "6 GB: no ember" || bad "6 GB ember line"
printf '%s\n' "$out" | grep -q '^auto stops' && bad "6 GB: a cap note with nothing held back" || ok "6 GB: nothing held back, no cap note"
env PATH="$T/os:$PATH" SPARK_SYSFS_DRM="$T/drm" sh "$REPO/bootstrap.sh" --list-packages | grep -qx libvulkan1 && ok "auto with a GPU: --list-packages adds the vulkan libraries" || bad "vulkan packages missing with a GPU"
env PATH="$T/os:$PATH" SPARK_SYSFS_DRM="$T/nodrm" sh "$REPO/bootstrap.sh" --list-packages | grep -qx libvulkan1 && bad "no GPU: --list-packages still adds the vulkan libraries" || ok "auto without a GPU: no vulkan libraries"
# this OS as it is: macOS is metal whatever the key says, Linux cpu or
# vulkan. 24 GB -> 14 GB budget: qwen3-14b (11 GB) fits on metal (no cap
# there); on cpu the 3 GB cap still stops it at qwen3-4b.
out=$(SPARK_MEM_TOTAL_GB=24 SITE_AI_BUILD=cpu sh "$REPO/bootstrap.sh" --list-models 2>&1) || bad "--list-models failed"
case $(uname -s) in
    Darwin) printf '%s\n' "$out" | head -1 | grep -q ', metal$' && printf '%s\n' "$out" | grep -qx 'spark: qwen3-14b' && ok "macOS: metal, the key ignored, the largest that fits" || bad "macOS header/pick: $(printf '%s\n' "$out" | head -1)" ;;
    *) printf '%s\n' "$out" | head -1 | grep -qE ', (cpu|vulkan)$' && ok "Linux: the header names cpu or vulkan" || bad "Linux header: $(printf '%s\n' "$out" | head -1)" ;;
esac

[ "$fail" -eq 0 ] && echo "install_test: all ok" || { echo "install_test: FAILED"; exit 1; }
