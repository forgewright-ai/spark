# Roadmap

What comes after v1.4, in the order it is likely to happen. Nothing here
is a promise; a row in `CHANGELOG.md` is. A better idea is an issue away.

## spark token: status for the keys that remain

v1.4 made user tokens personal (`spark user`: mint, login, rotate --
shown once, never stored server-side), which absorbed the rotation half
of the old `spark token` idea. What remains is status: bare `spark
token` naming which keys this machine holds (the api-token, the admin
token, the login) and whether the brain accepts each -- status only,
never a value -- with the right remedy per stale key. The landing rule
applies: the help line, the verb, a check row, the docs.

## OS-user accounts on one box

v1.4's users are FORGE accounts: one OS login, many named people, each
with a sealed store. The second layer is real OS users on the box, each
running their own spark against one shared engine: a package of the
port story (two servers cannot bind one :8080), a shared model cache
with per-user config, and a system unit serving all of them. Deferred
on purpose until the account layer has been lived with.

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
