# spark -- your own AI, in this editor

Alt-s opens the `spark> ` prompt (Esc s is the same keys). What you
type there decides what happens:

    (nothing) Enter      complete at the cursor: the rest of the sentence,
                         statement or block, left selected -- Backspace
                         discards it, Ctrl-z undoes it. End your text with
                         a space (or a new line) first: the continuation
                         begins exactly where the cursor is
    words                rewrite the selection as the words ask ("shorter",
                         "fix grammar", "add a docstring", "translate to
                         Portuguese"); with nothing selected, the words are
                         written at the cursor. The new text is left
                         selected: it is a proposal, never applied silently
    ? words              ask about the selection (or the whole file) in a
                         pane on the right; Ctrl-q closes it
    ?                    review the selection or the file: a few sentences,
                         then a handful of quoted notes

The same thing from command mode (Ctrl-e): `spark shorter`, `spark ? why`.

spark reads what the text is -- code or prose, a poem or a chapter or a
README -- and answers as that kind of text deserves, in its own language.
When it should not guess, tell it, for this buffer or for a folder:

    setlocal spark.about "a novel chapter"
    "*/Manuscripts/*.md": {"spark.about": "a novel chapter"}   (settings.json)

Options: `spark.about` (what the author says the text is; default empty),
`spark.bin` (the spark binary; default: SPARK_BIN, then ~/.local/bin/spark,
then PATH). `set spark false` switches the plugin off.

What leaves this machine: the file's name and its text -- at most 6 kB
around the cursor for a completion, 12 kB for a rewrite (more is refused:
select less), 16 kB for a question -- never its path, and only to the
FORGE or llama-server spark is configured for. No thread is kept.

Every run is one call to `spark edit` (the text on stdin); `spark edit -h`
says the rest, and `spark edit fix grammar < draft.md` works from a pipe.
