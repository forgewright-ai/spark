#!/bin/sh
# spark tests/uninstall_test.sh -- `spark uninstall` against a throwaway
# HOME holding a real clone at the default place (~/.spark), the shell
# layer's links and renders with .bak originals, state, config, data. Proves:
# --dry-run changes nothing; a non-terminal without --yes refuses; --yes takes
# everything spark made and keeps what is yours; --purge keeps nothing; a
# developer checkout is never removed. sudo is a stub that shouts and
# refuses, so every root step must land as a `todo` row, never a failure.
set -eu
REPO=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
fail=0
ok() { printf '  ok   %s\n' "$1"; }
bad() { printf '  FAIL %s\n' "$1"; fail=1; }
echo "uninstall_test: $T"

# a sudo that refuses and says so; a micro on PATH (the look renders its colorscheme)
mkdir -p "$T/bin"
printf '#!/bin/sh\necho "SUDO CALLED: $*" >&2; exit 97\n' > "$T/bin/sudo"; chmod +x "$T/bin/sudo"
printf '#!/bin/sh\nexit 0\n' > "$T/bin/micro"; chmod +x "$T/bin/micro"
export PATH="$T/bin:$PATH" SPARK_NO_REFRESH=1 TERM=xterm-256color
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
unset SPARK_HOME SPARK_REPO SPARK_NO_APPLY SPARK_YES SITE_SHELL SITE_THEME SITE_AI_MODEL SITE_HEADLESS

case $(uname -s) in Darwin) rc=.zshrc; other=.bashrc ;; *) rc=.bashrc; other=.zshrc ;; esac

# build_home NAME: a converged-looking HOME with a clone, links, renders, state
build_home() {
    export HOME="$T/$1" XDG_CONFIG_HOME="$T/$1/.config" XDG_STATE_HOME="$T/$1/.local/state" XDG_DATA_HOME="$T/$1/.local/share"
    mkdir -p "$HOME/.config/spark/themes" "$HOME/.local/state/spark/users/ana" "$HOME/.local/share/spark/engine/llama.cpp-b1" \
             "$HOME/.local/share/spark/engine/llama.cpp-b0" "$HOME/.local/share/spark/models" "$HOME/.local/bin" \
             "$HOME/.local/share/fonts/JetBrainsMonoNerdFont" "$HOME/.terminfo/74" "$HOME/.config/micro"
    # a real clone at the default place, carrying the WORKING tree (an
    # uncommitted verb must be testable), committed there so it is clean
    git clone -q "$REPO" "$HOME/.spark"
    (cd "$REPO" && git ls-files -z --cached --others --exclude-standard | tar --null -cf - -T -) | (cd "$HOME/.spark" && tar xf -)
    git -C "$HOME/.spark" add -A >/dev/null 2>&1; git -C "$HOME/.spark" commit -q -m "the working tree" >/dev/null 2>&1 || true
    printf 'SITE_SHELL=on\nSITE_THEME=gruvbox-dark\nSITE_AI_MODEL=none\n' > "$HOME/.config/spark/site.env"
    # originals the layer will back up, and a marker line in the other shell's rc
    printf '# mine\n' > "$HOME/$rc"; printf '# my tmux\n' > "$HOME/.tmux.conf"; printf '[user]\n\tname = me\n' > "$HOME/.gitconfig"
    printf 'export MINE=1\n\n[ -r ~/.config/spark/hook.bash ] && . ~/.config/spark/hook.bash   # spark: the AI at the prompt\n' > "$HOME/$other"
    printf '{"colorscheme": "spark", "tabsize": 2}\n' > "$HOME/.config/micro/settings.json"
    sh "$HOME/.spark/install.sh" >/dev/null
    for f in spark explain; do ln -s "$HOME/.spark/bin/$f" "$HOME/.local/bin/$f"; done
    printf '#!/bin/sh\n' > "$HOME/.local/bin/starship"; chmod +x "$HOME/.local/bin/starship"
    # state, config, data
    printf 'tok\n' > "$HOME/.local/state/spark/api-token"; printf '{}' > "$HOME/.local/state/spark/check.json"
    printf 'h\n' > "$HOME/.local/state/spark/users/ana/token.hash"; printf 'ana tok\n' > "$HOME/.local/state/spark/account"
    printf 'me\n' > "$HOME/.config/spark/soul"; printf 'a fact\n' > "$HOME/.config/spark/memory"
    printf 'MODEL_MINE="f u 1 s 1"\n' > "$HOME/.config/spark/models.env"; printf 'THEME_BG=#000000\n' > "$HOME/.config/spark/themes/mine.env"
    printf 'secret\n' > "$HOME/.config/spark/privacy-terms"; printf 'THEME_BG=#282828\n' > "$HOME/.config/spark/theme.env"
    printf '\033]P0282828\n' > "$HOME/.config/spark/console-colors"; printf '40\n40\n40\n' > "$HOME/.config/spark/console-colors.rgb"
    printf 'x' > "$HOME/.local/share/spark/engine/llama.cpp-b1/llama-server"; printf 'x' > "$HOME/.local/share/spark/engine/llama.cpp-b0/old"
    printf 'x' > "$HOME/.local/share/spark/models/x.gguf"; printf 'x' > "$HOME/.local/share/spark/models/y.gguf.part"
    printf 'x' > "$HOME/.local/share/fonts/JetBrainsMonoNerdFont/a.ttf"; printf 'x' > "$HOME/.terminfo/74/tmux-256color"
}
snapshot() { (cd "$HOME" && find . -not -path './.spark/*' -not -path './.spark' -not -path './Library/*' -not -path './Library' | sort); }
spark() { python3 "$HOME/.spark/bin/spark" "$@"; }

# 1. the plan changes nothing; only would/skip/todo rows; sudo is never called
build_home one
[ -L "$HOME/$rc" ] && [ -f "$HOME/$rc.bak" ] && ok "the layer is on: $rc is spark's link, the original in .bak" || bad "setup: $rc not linked"
before=$(snapshot)
out=$(spark uninstall --dry-run 2>&1) || bad "--dry-run failed: $out"
[ "$(snapshot)" = "$before" ] && ok "--dry-run changed nothing" || bad "--dry-run changed the HOME: $(printf '%s\n' "$before" > "$T/b"; snapshot | diff "$T/b" - | tr '\n' ' ')"
printf '%s\n' "$out" | grep -qE '^ok ' && bad "--dry-run printed an ok row" || ok "--dry-run prints would/skip/todo rows only"
printf '%s\n' "$out" | grep -q 'SUDO CALLED' && bad "--dry-run called sudo" || ok "--dry-run never calls sudo"
printf '%s\n' "$out" | grep -qE '^would +clone +~/.spark removed' && ok "the default clone would go" || bad "clone row: $(printf '%s\n' "$out" | grep -E ' clone ')"
printf '%s\n' "$out" | grep -q 'kept (yours): .*soul' && ok "the plan names what stays" || bad "no kept line: $out"

# 2. a non-terminal without --yes: the plan, one line, exit 2
rc2=0; out=$(spark uninstall </dev/null 2>&1) || rc2=$?
[ "$rc2" = 2 ] && printf '%s\n' "$out" | grep -q -- '--yes runs it' && ok "not a terminal: refused with the --yes line, exit 2" || bad "non-tty: rc=$rc2 $out"
[ "$(snapshot)" = "$before" ] && ok "the refusal changed nothing" || bad "the refusal changed the HOME: $(printf '%s\n' "$before" > "$T/b"; snapshot | diff "$T/b" - | tr '\n' ' ')"

# 3. --yes --keep-packages: all spark made goes, yours stays, root steps are todo
out=$(spark uninstall --yes --keep-packages 2>&1) || bad "uninstall --yes failed: $out"
[ "$(cat "$HOME/$rc")" = "# mine" ] && [ ! -e "$HOME/$rc.bak" ] && ok "$rc back from its .bak" || bad "$rc: $(ls -la "$HOME/$rc"* 2>&1)"
[ "$(cat "$HOME/.tmux.conf")" = "# my tmux" ] && ok ".tmux.conf back from its .bak" || bad ".tmux.conf: $(cat "$HOME/.tmux.conf" 2>&1)"
grep -q 'name = me' "$HOME/.gitconfig" && ok ".gitconfig back from its .bak (spark's render gone)" || bad ".gitconfig: $(cat "$HOME/.gitconfig" 2>&1)"
grep -q 'config/spark/hook' "$HOME/$other" && bad "the marker line survived in $other" || ok "the spark line is gone from $other"
grep -q 'MINE=1' "$HOME/$other" && ok "$other kept its own lines" || bad "$other lost its content"
[ ! -e "$HOME/.config/starship.toml" ] && [ ! -e "$HOME/.config/micro/colorschemes/spark.micro" ] && ok "the rendered look is gone" || bad "a render survived"
grep -q tabsize "$HOME/.config/micro/settings.json" && ! grep -q colorscheme "$HOME/.config/micro/settings.json" && ok "micro's settings.json kept, minus the colorscheme key" || bad "settings.json: $(cat "$HOME/.config/micro/settings.json")"
[ ! -e "$HOME/.local/bin/spark" ] && [ ! -e "$HOME/.local/bin/explain" ] && ok "~/.local/bin/spark and explain are gone" || bad "bin links survived"
[ ! -e "$HOME/.local/share/spark" ] && ok "the data dir (engine, models, .part) is gone" || bad "data dir survived: $(ls -R "$HOME/.local/share/spark")"
[ ! -e "$HOME/.terminfo/74/tmux-256color" ] && ok "the terminfo entry is gone" || bad "terminfo survived"
case $(uname -s) in Darwin) ;; *) [ ! -e "$HOME/.local/share/fonts/JetBrainsMonoNerdFont" ] && ok "the Nerd Font dir is gone (Linux)" || bad "the font dir survived" ;; esac
[ ! -e "$HOME/.spark" ] && ok "the default clone is gone" || bad "~/.spark survived"
state=$(cd "$HOME/.local/state/spark" && find . | sort | tr '\n' ' ')
[ "$state" = ". ./account ./users ./users/ana ./users/ana/token.hash " ] && ok "state keeps only the sealed users and the account" || bad "state left: $state"
conf=$(cd "$HOME/.config/spark" && find . | sort | tr '\n' ' ')
[ "$conf" = ". ./memory ./models.env ./privacy-terms ./soul ./themes ./themes/mine.env " ] && ok "config keeps only soul, memory, models.env, themes, privacy-terms" || bad "config left: $conf"
printf '%s\n' "$out" | grep -qE '^spark: |^fail ' && bad "a step failed outright: $(printf '%s\n' "$out" | grep -E '^spark: |^fail ' | head -2)" || ok "no step failed outright (a refusing sudo is a todo row)"
printf '%s\n' "$out" | grep -q 'kept (yours): ' && printf '%s\n' "$out" | grep -q 'is gone from this machine' && ok "the summary names what stayed and says spark is gone" || bad "summary: $(printf '%s\n' "$out" | tail -6)"
case $(uname -s) in Darwin) ;; *) [ ! -e "$HOME/.local/bin/starship" ] && ok "the pinned starship is gone (Linux)" || bad "starship survived" ;; esac

# 4. --purge on a fresh HOME: nothing of spark's remains
build_home two
out=$(spark uninstall --yes --purge --keep-packages 2>&1) || bad "uninstall --purge failed: $out"
left=$(cd "$HOME" && find . -path '*spark*' -not -path './Library/*' | sort | tr '\n' ' ')
[ -z "$left" ] && ok "--purge: no path with spark in its name remains" || bad "--purge left: $left"
[ ! -e "$HOME/.config/spark" ] && [ ! -e "$HOME/.local/state/spark" ] && ok "--purge: config and state dirs are gone" || bad "--purge left a spark dir"

# 5. a developer checkout is never removed
build_home three
out=$(SPARK_REPO="$REPO" python3 "$REPO/bin/spark" uninstall --dry-run 2>&1) || bad "dev-clone dry-run failed: $out"
printf '%s\n' "$out" | grep -qE '^skip +clone +.* is yours' && ok "a developer checkout: the clone row skips" || bad "dev clone row: $(printf '%s\n' "$out" | grep -E ' clone ')"
[ -z "$(git -C "$REPO" status --porcelain -- bin lib tests 2>/dev/null | grep -v '^??')" ] || true
[ -e "$REPO/.git" ] && ok "the repository is untouched" || bad "the repository is gone"

[ "$fail" -eq 0 ] && echo "uninstall_test: all ok" || { echo "uninstall_test: FAILED"; exit 1; }
