# spark.drill -- contract 13: questions the source itself answers.
#
# NOT BUILT. This module is the contract's text and the constants it
# fixes; nothing dispatches to it (bin/spark's VERBS has no `drill`), and
# `spark drill` is an unknown word until one line lands there. ROADMAP.md
# carries the same text.
#
# Contract 13. `spark drill` is the practice protocol: the source on
# stdin, one question at a time on stdout, your answer on stdin; never a
# path. Mode from the argument shape, no mode flags.
#
#   what grounds it   both the question AND the correct answer come from
#                     the source. The model composes neither: it proposes
#                     a span of the source as the answer and a question
#                     whose answer is that span, and a question whose
#                     answer does not anchor in the source (text.Ground)
#                     is dropped before it is ever asked. A drill built
#                     on an invented answer teaches the invention.
#   when it fails     material too thin for questions is said in ONE
#                     line -- never padded from the model's own
#                     knowledge, which is the one thing a drill must not
#                     contain: the learner cannot tell the padding from
#                     the source.
#   caps              DRILL_MAX in, ITEMS_MAX items a session.
#   grading           self-graded against the sourced answer to begin
#                     with: you see the span the source holds and say
#                     whether you had it. Model-grading is a second
#                     model's opinion of a first model's question, and
#                     neither is the source.
#   ledger            kind `drill`, and it schedules rather than
#                     suppresses -- the inversion of every other kind. A
#                     missed item comes BACK, at INTERVALS[n] days, until
#                     it has been answered right RIGHT_TWICE times in a
#                     row. So its records carry state the other kinds do
#                     not (misses, streak, due) and, alone among the
#                     kinds, they never age out: ledger.RULES has
#                     drill age=False, because a schedule that expires is
#                     not a schedule.
#   what leaves       the source's text, to the model this machine
#                     answers from. Your answers are graded here, against
#                     the source; they are never sent.

DRILL_MAX = 16000       # the source one session reads
ITEMS_MAX = 10          # items proposed for one session
INTERVALS = (1, 3, 7, 21, 60)   # days: a missed item comes back, widening
RIGHT_TWICE = 2         # answered right this many times in a row: it rests
MODE = "drill-items"    # persona.MODES key, when the brief lands


def cmd_drill(_args):
    raise NotImplementedError("contract 13: see ROADMAP.md")
