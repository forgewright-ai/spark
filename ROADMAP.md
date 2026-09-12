# Roadmap

What comes after v1.28, in the order it is likely to happen. Nothing here
is a promise; a row in `CHANGELOG.md` is. A better idea is an issue away.

## Chaos on a real box

What a fixture cannot reach is the maintainer's, by hand, as the WSL
pass is:

- the server killed mid-reply -- the unit must bring it back (the
  fixture proves only the `serve` row)
- a genuinely full disk -- a real ENOSPC on a real filesystem, not
  curl's write error faked
- the GPU taken away for real -- a card removed, not an empty sysfs
- two machines, one FORGE: a peer that dies mid-answer for a client

Then the two shapes the suite still cannot express: a scenario whose
remedy needs the network (a re-download after `spark model rm`), and
one that must survive a reboot.

## A shared engine as a system service

`spark share` (v1.22) shares the owner's headless engine with the box's
other OS users through a `spark` group. The heavier step, if it is ever
wanted: the engine as a real system unit under its own service account,
models in a shared path, so it needs no owner logged in at all. Bigger --
root, a service user, paths outside any `$HOME` -- and only worth it once
the group model has been lived with.
