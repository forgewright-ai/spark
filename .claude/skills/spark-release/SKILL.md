---
name: spark-release
description: Tag a spark release, a major vX.Y, the way docs/REFERENCE.md "Releasing" says. A person runs it, with the version as the argument; the model never invokes it on its own.
disable-model-invocation: true
argument-hint: vX.Y
---
# Release spark $0

Read docs/REFERENCE.md, "Releasing", first. The tag is the release, and
a person signs it. A patch, vX.Y.Z, is `tests/tag.sh`'s and never this
skill's.

Every line below must hold before the tag. One that does not: stop and
say which.

1. `git status -sb` is clean and on main, and after `git fetch origin`
   HEAD is `origin/main`.
2. `sh tests/land.sh --passed $(git rev-parse HEAD)` exits 0: ci.yml
   passed for this very commit.
3. `docs/CHANGELOG.md` opens with `## $0` and its bullets are written.
4. `python3 tests/docs_test.py` ends `all ok`.
5. `git tag -l $0` prints nothing, `git config gpg.format` says `ssh`
   and `git config user.signingkey` names a key.

Then:

6. `git tag -s $0 -m 'spark $0' && git push origin $0`.
7. Watch release.yml: `gh run list --workflow release.yml --limit 1`,
   then `gh run watch <id>`. It refuses a tag whose commit CI did not
   pass, verifies the signature against `allowed-signers`, checks the
   CHANGELOG heading and `spark ver`, and makes the GitHub Release with
   the CHANGELOG section as its notes and two assets, `get` and
   `sbom.cdx.json`.
8. Report the tag and the release's URL, then what comes after and by
   whom: the site renders at the newest tag through its own workflow in
   the repository that renders it, and `spark update` moves every
   machine.
