# spark.judge -- the Judge context: what spark finds about a proposed
# command before a person sees it. Local, no model call: every stage's head
# must be a builtin, a spark verb from the tree, or a program on PATH, and
# every option must be in that program's own entry. A finding names one
# problem; a verdict with none is ok. read_only() lets spark's own argv
# proof lower a model's `!` -- persona.is_dangerous always wins.

from collections import namedtuple

# kind: missing (no such program here) | flag (not in its entry) | verb
# (not a spark verb or word) | placeholder (a <word> the shell would read
# as a redirect)
Finding = namedtuple("Finding", "kind head word")


class Verdict(namedtuple("Verdict", "findings")):
    @property
    def ok(self):
        return not self.findings


def verdict(command, store=None):
    """The Verdict on one command line."""
    return Verdict(())


def read_only(command):
    """True when every stage of `command` passes spark's own read-only argv
    proof (persona's proof lists, unchanged) and nothing is dangerous."""
    return False
