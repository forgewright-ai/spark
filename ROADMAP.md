# Roadmap

What comes after v1.6, in the order it is likely to happen. Nothing here
is a promise; a row in `CHANGELOG.md` is. A better idea is an issue away.

## The editor, next

- Anchor verification: every span a `?` answer quotes is checked against
  the buffer; the unverifiable ones marked; a key jumps to the quote.
- A per-file ledger in memory: a declined suggestion retires.
- Whole-file context around a selection for `?`; threads in the pane
  (`??`); a key that applies a code block; Escape and `q` close the pane.
- The audition: fixtures (a poem, a chapter, a README, a commit message,
  Portuguese prose, Go, Python, shell) with mechanical lints, run against
  a live brain, so a brief is judged blind.

## spark token: status for the keys that remain

Bare `spark token` names which keys this machine holds (api-token, admin
token, login) and whether the brain accepts each -- status only, never a
value, with the remedy per stale key.

## OS-user accounts on one box

Real OS users, each running their own spark against one shared engine:
the port story, a shared model cache with per-user config, a system unit
serving all of them. After the account layer has been lived with.

## Chaos: rehearse the failures

`spark chaos` (or `spark check --chaos`) breaks the machine one known way
at a time and proves the right row goes red and its remedy heals it.
Hermetic first (the stub servers learn to be slow, to hang, to 503, to
cut a stream), then once on a real box. Not part of a stranger's check.

- the server killed mid-reply -- `serve`; the unit brings it back
- a truncated model file -- `models`; `spark model verify` names it
- a full disk -- the download refuses cleanly, no `.part` left
- the GPU taken away -- `gpu`; the line still answers on the CPU
- the LAN cut on a client -- `peer`; `??` and chat fail fast
- two `spark serve` or two `spark update` at once -- the lock wins
- a clone three tags behind -- `git`; `spark update` moves it
- a hostile line answer (not JSON, empty, 40 kB) -- the widget runs
  nothing, keeps the prompt

## Line-bench: a quality number per model and OS

About forty questions per OS with a checker each, through the real
`spark line` path: `spark bench --lines`, one pass rate and one median
latency per model, kept beside the speed baseline. The table then
chooses on quality and speed, not size alone.

## Per-OS exemplars in the line

The misses so far are macOS knowledge (`free` for `vm_stat`). A short
block of per-OS examples in the line's prefix is the cheapest gain.

## More distros, more machines

Debian-family only today. Fedora and Arch need a package table and a CI
job each; Linux arm64 already has an engine pin. A `.deb` and a Homebrew
tap wait until the clone-and-tag path has been lived with.

## The FORGE from anywhere

The page and the API stop at the LAN on purpose. An overlay network
(Tailscale, any WireGuard mesh) extends that boundary to your own devices
without opening a port; its https endpoints are the real PWA path (a
service worker, a true offline shell).

## The bigger second model

A machine with 32 GB earns a mixture-of-experts model (the 30B-A3B rows:
near-4B speed, near-flagship answers) as its second model. The table
already says when it fits; the proof and the tuning are the work.
