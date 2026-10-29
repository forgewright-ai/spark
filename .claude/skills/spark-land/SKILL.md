---
name: spark-land
description: Land HEAD on main through CI with sh tests/land.sh. Use when asked to land, merge or push a change of spark to main. main is never pushed any other way.
context: fork
allowed-tools: Bash(sh tests/land.sh:*), Bash(git status:*), Bash(git log:*), Bash(git fetch:*), Bash(git rev-parse:*), Bash(gh run:*)
---
# Land HEAD on main

main only receives a commit ci.yml already passed. `tests/land.sh` is
the one way: it pushes HEAD to `try/<sha>`, waits for ci.yml, moves
main forward to the same commit and deletes the try branch. Never
amend, never force-push, never push main by hand before step 4 says so.

1. `git status -sb`: the tree is clean and HEAD is on a branch that is
   not main. A dirty tree, or main itself: stop and say so.
2. `git log --oneline -1`: the commit being landed.
3. `sh tests/land.sh`. Wait for it. CI takes about 6 minutes.
4. Read what it said.
   - main moved forward: landed. Report the sha.
   - `ci.yml did not pass`: main is untouched and `try/<sha>` stays.
     Report the failing job and the last lines of its log, from
     `gh run view <run id> --log-failed`. Re-run a failed job at most
     once, and only to tell a flake from a fault: a flake is a test
     that passed before on the same tree.
   - `could not ask GitHub`: the watch timed out or the API refused.
     Run `sh tests/land.sh --passed <sha>` once more. When it exits 0,
     `git push origin <sha>:main` finishes the landing, and the
     pre-push hook asks the same question again.
5. Report in five lines or fewer: the commit, the try branch, the run's
   URL, the result, and what is left by hand (a try branch to delete
   when the run was red).
