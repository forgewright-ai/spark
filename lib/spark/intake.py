# spark.intake -- the Intake context: what this machine can run, read into
# the store outside the prompt line. Sources give entries; the store keeps
# them; refresh() rebuilds what changed. Nothing here asks a model, and
# nothing here runs on the prompt line's hot path.
#
#   a source   where entries come from: programs (their manuals, or their
#              --help run only inside spark's sandbox), apps (.desktop and
#              .app bundles), spark (its own verbs, from the tree)
#   an entry   one thing a person can run, as spark read it
#   the store  STATE_DIR/knowledge/: index.json (the searchable words) and
#              entries/<name>.json (one entry each), dir 0700, files 0600
#
# Every text an entry holds went through text.scrub and text.hold_secrets:
# the store never keeps a secret shape. The import rule (a smoke test holds
# it): this module imports only spark/__init__, text and sandbox.

from collections import namedtuple

# the options a manual or a --help names, the three shapes a flag takes
OptionSet = namedtuple("OptionSet", "long short words")

# kind: program | app | spark; source: man | help | pkg | desktop | app |
# tree; origin: who installed it (dpkg:coreutils, xbps:runit, brew:jq,
# macos, local); stamp: (mtime, size) of what it was read from
Entry = namedtuple("Entry", "name kind source what synopsis options lines origin stamp")


class Store:
    """The repository of entries. LocalStore is this machine's; the
    audition's SnapshotStore reads an OS's help snapshot instead, so a
    question can be grounded in another OS's manuals."""

    def names(self):
        """Every entry's name."""
        raise NotImplementedError

    def entry(self, name):
        """The Entry named `name`, or None."""
        raise NotImplementedError

    def index(self):
        """The searchable words: {"names", "len", "avg", "post"} (see
        grounding), or None when there is no index yet."""
        raise NotImplementedError


class LocalStore(Store):
    """STATE_DIR/knowledge/ on this machine. A missing store answers empty:
    no index is no evidence, never an error."""

    def names(self):
        return []

    def entry(self, name):
        return None

    def index(self):
        return None


def status():
    """(counts by kind, built epoch or None, stale bool, skipped count) --
    what the check row and the bootstrap row say."""
    return {}, None, False, 0


def refresh(deadline=None):
    """Rebuild what changed since the last fingerprint, within `deadline`
    seconds when given; never raises. Returns status()."""
    return status()
