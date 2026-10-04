# Roadmap

What comes after v1.81, in rough order. Nothing here is a promise.
`docs/CHANGELOG.md` says what shipped.

No new verb until items 1 and 2 are done.

1. A faster first line from `spark read`. Put the reading pass in the
   answer's stream. Send the text early, while the reader types.
2. Grounding scores for every model `auto` may pick. Score the
   30B-A3B on a machine it fits. Find a fix for answers that keep
   lines the source does not hold.
3. After a reboot, wait up to 30 seconds for the promised address
   before the server starts. Today it can bind to the Wi-Fi instead.
4. Let use decide. Read `spark stats` each week, and drop verbs
   nobody runs. Then two small hints: an alias you keep typing, and a
   tool you have but do not use.
5. A first new user installs spark from `README.md` alone and says
   what broke. Issues open after that.
6. Failure tests on a real machine: the engine killed mid-reply, a
   full disk, no GPU, the server lost mid-answer.
7. `spark do` knows more "bad option" messages, such as procps's
   `improper ... field descriptor`. The man page lines then come back.
8. `spark do ??` goes on with the last task, as `??` does at the
   prompt.
9. The voice answers in the language it heard. `spark stats` shows
   the wait before the first sound.
