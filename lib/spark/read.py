# spark.read -- contract 11: what a source says, and only what it says.
#
# NOT BUILT. This module is the contract's text and the constants it
# fixes; nothing dispatches to it (bin/spark's VERBS has no `read`), and
# `spark read` is an unknown word until one line lands there. It is here
# so the shape is written down where the code that will fill it lives.
# ROADMAP.md carries the same text for a reader who is not in the source.
#
# Contract 11. `spark read` is the reader's protocol: the source on
# stdin, a question in the words, the answer raw text out; never a path.
# Mode from the argument shape, no mode flags.
#
#   what grounds it   every claim quotes the source. A line whose quotes
#                     are not in the source is dropped (text.Gate), and
#                     so is a line that quotes nothing (text.UNQUOTED):
#                     an unquoted sentence about a source is the model's
#                     own knowledge wearing the source's clothes.
#   when it fails     when the source does not answer, the whole reply is
#                     ONE line naming what the source does cover. Never
#                     "the text does not say, but generally ...": the
#                     line is composed here, from the source's own words,
#                     not asked of the model.
#   caps              READ_MAX in; past that `--part N` reads part N and
#                     the answer names which part it read, in the first
#                     line, always -- an answer from part 2 that does not
#                     say so is indistinguishable from an answer from a
#                     source that has one part.
#   ledger            kind `read`: the questions asked of this source, so
#                     a second reader sees what has been asked. Nothing
#                     invalidates them -- a source does not change (that
#                     is what makes it a source); age and `--ledger
#                     clear` are the only ways out. No suppression: a
#                     question asked twice of a source is a fair question
#                     twice, unlike a note declined in a draft.
#   what leaves       the source's text and the question, to the model
#                     this machine answers from. No name, no path, no cwd.

READ_MAX = 16000        # the source one part reads
PART_OVERLAP = 400      # a part carries this much of the one before it
MODE = "read-source"    # persona.MODES key, when the brief lands


def cmd_read(_args):
    raise NotImplementedError("contract 11: see ROADMAP.md")
