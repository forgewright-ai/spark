# Roadmap

What comes after v1.0, in the order it is likely to happen. Nothing here
is a promise; a row in `CHANGELOG.md` is. A better idea is an issue away.

## v1.3: the CLI experience wave

A month of living with spark taught one lesson: the machine works, the
conversation with it is rough. v1.3 is four passes over the same
surface, the command line, in this order.

### One grammar for every verb

A code review of every verb, parameter and mechanic, then a
harmonization: bare verb = show, `on|off` toggles read the same way
everywhere, the same words mean the same things. The first casualty is
the quiet family: `SITE_QUIET_LOGIN`, `SITE_QUIET_BOOT` (today the
confusing `spark bootconfig quiet|loud`) and the missing quiet start
become one verb -- `spark quiet` bare shows the three states, `spark
quiet boot|login|start [on|off]` sets one. Quiet start silences what
spark prints when it comes up: the login banner, the serve/forge
startup chatter, and a one-line answer from bare `spark`. The same pass
sets the interaction language: confirms are `yes/NO` and read the same
in every verb, downloads draw one progress bar, refusals and hints
share one shape and one voice.

### spark knows itself

Two gaps, one theme. First, the brain: asking `?? how do I change the
theme` should answer `spark theme`, but the model has never heard of
spark -- the line and chat prompts learn spark's own command surface,
so the machine can explain itself. Second, the shell: `spark th<TAB>`
completes nothing -- bash and zsh completion for the verbs and their
arguments (theme names, model names, the words each verb takes),
shipped with the rc hooks.

### Reading long output

`spark help` outgrew one screen and there is no way to scroll it; the
same is true of `check`, `history` and the model table. Long output
goes through a pager when stdout is a terminal (`$PAGER`, else `less
-R`), and never when piped or `--porcelain` -- text-first means the
pipe contract is untouched. Chat gets the same care within the same
principle: scrolling that works everywhere the terminal's own
scrollback does (tmux on the box included), `/clear` to wipe the screen
and continue, and a way back into an earlier thread (`/resume`, and
`spark chat --thread N`), without turning the REPL into a curses app.

### The first run looks right

The shell layer is nice; setting it up is not. `spark setup` on a
fresh machine lands gruvbox-dark as the default answer -- terminal,
micro and tmux all reading the same palette, consistent from minute
one -- while the theme question keeps the user choosing. More palettes
in `themes/`, and `spark font` grows easier: name a face and size once
and every surface that draws text follows.

## spark token: one verb for the keys

Three clients hold the same secret three ways: the CLI reads files under
`~/.local/state/spark/`, the desktop app keeps the OS keychain, the
browser a cookie. When the box rotates a token, only the file copies go
quietly stale, and the hint points at the wrong door. `spark token` makes
the keys first-class: bare, it names which tokens this machine holds and
whether the brain accepts each (status only, never a value); `spark token
sync` refreshes a client's copies from its peer over SSH; `spark token
rotate` rotates on the box and says what must change where. The landing
rule applies: the help line, the verb, a check row (a held token the
brain rejects is a warn with the sync remedy), the docs.

## Chaos: rehearse the failures

Every failure spark met on the way to v1.0 was met by accident -- a model
that did not fit, a server on the CPU because a group landed after the
unit, two processes racing for one port, a download cut half way, a unit
that never warmed, a client with no route to the brain, a thinking model
answering with no JSON. The next wave turns that list into a rehearsal:
`spark chaos` (or `spark check --chaos`) breaks the machine one known
way at a time and proves that the right check row goes red and that the
remedy it names heals it. Hermetic first (the stub servers in `tests/`
learn to be slow, to hang, to answer 503 forever, to cut a stream), then
once, live, on a real box. Not part of a stranger's `spark check`.

The faults, each with the row that must catch it: the server killed
mid-reply (`serve`; the unit brings it back, the line answers again
within 30 s); a truncated model file (`models`; `spark model verify`
names it); a full disk (the download refuses cleanly, no `.part` left);
the GPU taken away (`gpu`; the line still answers on the CPU); the LAN
cut on a client (`peer`; `??` and chat fail fast with the hint, never a
20 s hang); two `spark serve` or two `spark update` at once (the lock
wins, the other says so); a clone three tags behind (`git`; `spark
update` moves it, `spark check` green after); a hostile line answer --
not JSON, empty, 40 kB (the widget runs nothing, keeps the prompt).

## Line-bench: a quality number per model and OS

A fixed set of about forty questions per OS with a checker each (the
kind, a head word, a pattern the command must match or must not), run
through the real `spark line` path: `spark bench --lines`, one pass rate
and one median latency per model, kept beside the speed baseline. The
curated table then chooses on quality and speed, not size alone.

## Per-OS exemplars in the line

The misses so far are macOS knowledge: `free` where `vm_stat` was meant,
a `top` field that does not exist. A short block of per-OS examples in
the line's prefix is the cheapest gain and the first rung of teaching a
small model with its own machine's answers.

## More distros, more machines

Debian-family only today (`apt`). Fedora and Arch need a package table
and a CI job each; Linux arm64 already has an engine pin. A `.deb` and a
Homebrew tap wait until the clone-and-tag path has been lived with.

## The FORGE from anywhere

The page and the API stop at the LAN today, on purpose: LAN http is the
trust model. An overlay network -- Tailscale, or any WireGuard mesh --
extends that boundary to your own devices wherever they are, without
opening a port to the world. Its https endpoints are also the real PWA
path: a secure context at last, so a service worker and a true offline
shell become possible without spark minting certificates.

## The bigger ember

A machine with 32 GB earns a mixture-of-experts model (the 30B-A3B row:
near-4B speed, near-flagship answers) as its ember. The table already
says when it fits; the proof and the tuning are the work.
