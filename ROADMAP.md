# Roadmap

What comes after v1.15, in the order it is likely to happen. Nothing here
is a promise; a row in `CHANGELOG.md` is. A better idea is an issue away.

## Chaos on a real box

The hermetic half shipped: `spark check --chaos` rehearses nine failures
against a throwaway machine. What a fixture cannot reach is left, and it
is the maintainer's, by hand, as the WSL pass is:

- the server killed mid-reply -- the unit must bring it back (the stub
  service manager here says `absent`, so only the `serve` row is proven)
- a genuinely full disk -- the rehearsal fakes curl's write error; a
  real ENOSPC on a real filesystem is the one that counts
- the GPU taken away for real -- a card removed, not an empty sysfs
- two machines, one FORGE: a peer that dies mid-answer for a client

Then the two shapes the suite still cannot express: a scenario whose
remedy needs the network (a re-download after `spark model rm`), and
one that must survive a reboot.

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
