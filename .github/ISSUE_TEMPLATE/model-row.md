---
name: Model row
about: Propose a row for models.env
title: "model: NAME"
labels: model
---

The file URL on huggingface.co (a `.../resolve/main/<file>.gguf`, Q4_K_M):

The size in bytes and the sha256. They are `x-linked-size` and
`x-linked-etag` on the redirect `curl -sI '<url>?download=true'`
answers with:

The license name and URL. Required; `auto` may pick Apache-2.0 and MIT
only:

A note, optional, one line: what this model is for, or a warning:

The line proof, optional. The row is marked tested only with it: the
output of piping a question through `spark line` with this model
loaded, showing valid JSON on line 1:

One row per issue or pull request, please.
