# spark.facts -- the machine's decisions, in their one home. What
# bootstrap.sh once computed in sh twins (distro, ai build, WSL, memory,
# the engine's home and flavour, the model picks) is answered here by
# the same code every spark verb already uses, and printed as KEY=value
# lines bootstrap.sh eval's at its start. sh keeps the orchestration --
# rows, package installs, downloads, file placement -- and asks no
# question of its own.
#
#   python3 lib/spark/facts.py        the facts, sh-quoted, one per line
#
# The test overrides bootstrap honoured (SPARK_OS_RELEASE,
# SPARK_PROC_VERSION, SPARK_SYSFS_DRM, SPARK_MEM_TOTAL_GB, SITE_* in the
# environment) are honoured here too: config and engine read the same
# variables.

import os
import sys

if __name__ == "__main__":
    _LIB = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    if _LIB not in sys.path:
        sys.path.insert(0, _LIB)

from spark import IS_MAC, REPO, config, distro, is_wsl, mem_total_gb
from spark import engine

# The release asset per OS/arch/build (the engine step's tarball name and
# its sha key in engine.env); '' when there is no pin for this machine.
FLAVOURS = {
    ("Darwin", "arm64", "metal"): ("macos-arm64", "LLAMA_SHA_MACOS_ARM64"),
    ("Darwin", "x86_64", "metal"): ("macos-x64", "LLAMA_SHA_MACOS_X64"),
    ("Linux", "x86_64", "vulkan"): ("ubuntu-vulkan-x64", "LLAMA_SHA_LINUX_VULKAN_X64"),
    ("Linux", "x86_64", "cpu"): ("ubuntu-x64", "LLAMA_SHA_LINUX_X64"),
    ("Linux", "aarch64", "vulkan"): ("ubuntu-vulkan-arm64", "LLAMA_SHA_LINUX_VULKAN_ARM64"),
    ("Linux", "aarch64", "cpu"): ("ubuntu-arm64", "LLAMA_SHA_LINUX_ARM64"),
}

SOURCE_MARKS = {"repo": "-", "user": "u"}


def quote(v):
    """One sh-safe single-quoted value."""
    return "'" + str(v).replace("'", "'\\''") + "'"


def pick_line(row):
    """A role's pick as bootstrap's six fields: name file url bytes sha ram."""
    return "%s %s %s %d %s %d" % (row[0], row[1], row[2], row[3], row[4], row[5]) if row else ""


def facts():
    """[(KEY, value)] -- every decision bootstrap.sh needs, in one pass."""
    cfg = config.load()
    # bootstrap passes its own uname view (SPARK_OS, SPARK_ARCH), so a
    # test's uname stub steers these facts too
    sysname = "Darwin" if IS_MAC else "Linux"
    machine = os.environ.get("SPARK_ARCH") or os.uname().machine
    build = engine.backend(cfg)
    flavour, sha_key = FLAVOURS.get((sysname, machine, build), ("", ""))
    pins = config.parse_env(os.path.join(REPO, "engine.env"))
    pair = engine.chosen_rows(cfg)
    rows = "\n".join("%s %s %s %d %s %d %s" % (r[0], r[1], r[2], r[3], r[4], r[5], SOURCE_MARKS.get(r[6], "-"))
                     for r in config.model_tables())
    return [
        ("DISTRO", distro()),
        ("AI_BUILD", build),
        ("IS_WSL", "1" if is_wsl() else "0"),
        ("MEM_GB", int(mem_total_gb())),
        ("LLAMA_VERSION", pins.get("LLAMA_VERSION", "")),
        ("ENGINE_FLAVOUR", flavour),
        ("ENGINE_SHA", pins.get(sha_key, "") if sha_key else ""),
        ("ENGINE_HOME", engine.engine_dir(cfg)),
        ("SPARK_PICK", pick_line(pair.get("spark"))),
        ("EMBER_PICK", pick_line(pair.get("ember"))),
        ("CAP_NOTE", engine.cap_note(cfg)),
        ("MODEL_ROWS", rows),
    ]


def main():
    for key, val in facts():
        sys.stdout.write("%s=%s\n" % (key, quote(val)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
