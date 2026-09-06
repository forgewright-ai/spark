---
name: Model row
about: Propose a row for models.env
title: "model: NAME"
labels: model
---

File URL on huggingface.co (a `.../resolve/main/<file>.gguf`, Q4_K_M):

Size (bytes) and sha256 -- `x-linked-size` and `x-linked-etag` on the
redirect `curl -sI '<url>?download=true'` answers with:

License name and URL (required; Apache-2.0 and MIT are the ones `auto`
may pick):

Note (optional, one line -- what this model is for, or a warning):

Line proof (optional; the row is marked tested only with it -- the
output of piping a question through `spark line` with this model
loaded, showing valid JSON on line 1):

One row per issue / pull request, please.
