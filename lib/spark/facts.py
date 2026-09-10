# spark.facts -- the machine's decisions, printed for bootstrap.sh.
# What bootstrap once computed in sh twins (distro, ai build, WSL,
# memory, the engine's home and flavour, the model picks) is answered
# by the same code every spark verb already uses, and printed as
# KEY=value lines bootstrap.sh eval's at its start. sh keeps the
# orchestration -- rows, package installs, downloads, file placement --
# and asks no question of its own.
#
#   python3 lib/spark/facts.py        the facts, sh-quoted, one per line
#
# The test overrides bootstrap honoured (SPARK_OS_RELEASE,
# SPARK_PROC_VERSION, SPARK_SYSFS_DRM, SPARK_MEM_TOTAL_GB, SITE_* in the
# environment) are honoured here too: config and engine read the same
# variables.

import os
import shlex
import sys

if __name__ == "__main__":
    _LIB = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    if _LIB not in sys.path:
        sys.path.insert(0, _LIB)

from spark import config, distro, is_wsl, mem_total_gb
from spark import engine


def row_line(r):
    """A model row as bootstrap's six fields: name file url bytes sha ram."""
    return "%s %s %s %d %s %d" % (r[0], r[1], r[2], r[3], r[4], r[5])


def facts():
    """[(KEY, value)] -- every decision bootstrap.sh needs, in one pass."""
    cfg = config.load()
    # bootstrap passes its own uname view (SPARK_OS, SPARK_ARCH), so a
    # test's uname stub steers these facts too
    sysname = os.environ.get("SPARK_OS") or os.uname().sysname
    machine = os.environ.get("SPARK_ARCH") or os.uname().machine
    build = engine.backend(cfg)
    flavour, sha = engine.flavour(sysname, machine, build)
    pair = engine.chosen_rows(cfg)
    # each row plus a source mark; `-` for the list (sh field-splitting
    # cannot carry model.SOURCE_MARKS' blank), `u` yours
    rows = "\n".join(row_line(r) + (" u" if r[6] == "user" else " -")
                     for r in config.model_tables())
    return [
        ("DISTRO", distro()),
        ("AI_BUILD", build),
        ("IS_WSL", "1" if is_wsl() else "0"),
        ("MEM_GB", int(mem_total_gb())),
        ("LLAMA_VERSION", config.engine_pins().get("LLAMA_VERSION", "")),
        ("ENGINE_PIN_NAME", config.pinned_engine_name()),
        ("ENGINE_FLAVOUR", flavour),
        ("ENGINE_SHA", sha),
        ("ENGINE_HOME", engine.engine_dir(cfg)),
        ("SPARK_PICK", row_line(pair["spark"]) if pair.get("spark") else ""),
        ("EMBER_PICK", row_line(pair["ember"]) if pair.get("ember") else ""),
        ("CAP_NOTE", engine.cap_note(cfg)),
        ("MODEL_ROWS", rows),
    ]


def main():
    for key, val in facts():
        sys.stdout.write("%s=%s\n" % (key, shlex.quote(str(val))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
