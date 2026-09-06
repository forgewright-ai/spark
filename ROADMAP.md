# Roadmap

What comes after v1.8, in the order it is likely to happen. Nothing here
is a promise; a row in `CHANGELOG.md` is. A better idea is an issue away.

## Onboarding: a stranger's path from a bare OS

The docs begin where spark can already run. A vanilla Debian 13 with ssh
and the standard utilities has neither `git` nor `curl`, so the one-liner
dies as `curl: command not found` before spark says a word, and "Before
you start" is a prose list rather than the first step. Someone meeting us
for the first time should be walked from a fresh OS to a first answer in
numbered steps, each saying what it looks like when it worked.

- step 0 is the `apt` line, in README and INSTALL both, ahead of the
  one-liner rather than beside it
- `sudo` is absent when Debian's installer was given a root password --
  say so, and say the fix
- `get` cannot check for `curl`: it needed `curl` to arrive at all. A
  `wget` form of the one-liner, or the by-hand clone, is the answer we owe
- what it will cost, up front: about ten minutes, 4.7 GB down, one sudo
- the same walk for macOS, where the command line tools are the gate

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

## Per-OS user accounts

Real OS users, each running their own spark against one shared engine:
the port story, a shared model cache with per-user config, a system unit
serving all of them. After the account layer has been lived with.

## spark token: status for the keys that remain

Bare `spark token` names which keys this machine holds (api-token, admin
token, login) and whether the brain accepts each -- status only, never a
value, with the remedy per stale key.
