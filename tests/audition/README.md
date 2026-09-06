# tally

A small command that counts words, lines and characters in a file, like
`wc`, but prints a table and knows about UTF-8.

## Install

    curl -fsSL https://example.com/tally/get | sh

This puts `tally` in `~/.local/bin`. Nothing else is written.

## Use

    tally FILE...          one row per file, a total at the end
    tally --json FILE      the same as JSON, one object per file
    tally -h               this help

Exit codes: 0 when every file was read, 1 when one could not be, 2 for a
bad invocation.

## Configuration

`TALLY_COLUMNS` in the environment picks the columns, comma separated:
`lines,words,chars,bytes`. The default is `lines,words,chars`.

## License

MIT. See `LICENSE`.
