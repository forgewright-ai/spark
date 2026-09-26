# spark.grounding -- the Grounding context: which entries go with one
# question. The index ranks entries by the machine's own words (BM25 over
# each entry's name, one-line description, synopsis and option lines); no
# synonym, genre, OS or app table. Evidence is a short labelled block that
# rides the USER message, never the prefix, so the warm slot keeps its
# cache. shell_map() is spark's own verbs, generated from the tree for the
# prefix: byte-stable for a release, complete by construction.

from collections import namedtuple

from . import intake

Hit = namedtuple("Hit", "name score")
Evidence = namedtuple("Evidence", "text names chars")

BUDGET = 600          # characters of evidence per question (the audition sweeps it)


def search(words, k=3, store=None):
    """The entries that best match `words`, best first: [Hit]."""
    return []


def evidence(question, heads=(), store=None, budget=BUDGET):
    """The Reference block for one question (and the heads last tried, on
    ?? or a re-ask), or an empty Evidence when nothing clears the floor."""
    return Evidence("", (), 0)


def shell_map(store=None):
    """spark's own commands for the prefix, from the tree."""
    return ""
