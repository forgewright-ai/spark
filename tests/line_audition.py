#!/usr/bin/env python3
# line_audition.py -- the prompt line, judged by outcomes. Plain words a
# person types after `? ` go through the real `spark line` (contract 4)
# for six OSes (debian, arch, void, fedora, opensuse, macos) and for spark
# itself, and a
# mechanical grader decides each answer: line 1 is contract 4's shape,
# the head command exists on that OS, every option it passes appears in
# that OS's own help, the case's must-nots hold, no command the case
# forbids would run, what the case demands is there, danger is right,
# and the reply exited 0.
# Nothing here trusts the generation: the OS facts are help snapshots
# gathered ON that OS (collect), and spark's verbs come from the tree's
# own TAB completion, so a retired verb fails with no list to keep.
#
#   python3 tests/line_audition.py run --os void --model NAME [--url URL]
#                                      [--arm off|judge|full] [--role spark|ember]
#                                      [--out FILE] [--split dev|held|all]
#                                      [--subject tools|spark] [--case ID] [-v]
#   python3 tests/line_audition.py recall --os OS [--k 3] [--split dev|held|all] [-v]
#   python3 tests/line_audition.py collect [--os OS] --out help-OS.json
#   python3 tests/line_audition.py report [--split dev|held|all] FILE...
#   python3 tests/line_audition.py serve-candidate --model-file PATH [--port 8090]
#   python3 tests/line_audition.py packages --os OS
#   python3 tests/line_audition.py precision [--os OS|all] [-v]
#   python3 tests/line_audition.py selftest
#
# Not part of the gate: `run` needs a live model. `recall` and `selftest`
# need none and are fast. The help snapshots are data: nothing in them is
# run. The OS a run speaks as comes from spark's own seams
# (SPARK_OS_RELEASE, SPARK_ETC_RUNIT, SPARK_PROC_VERSION) and from PATH:
# for `spark line` it is one directory of stubs, a stub for every tool
# the snapshot says that OS has and nothing else, so no tool of the
# machine the audition runs on reaches the prompt. The harness starts
# python and bin/spark by their absolute paths. macOS speaks only on a
# Mac: the prompt reads platform.system() there, which has no seam.
#
# A run keeps each reply as it came (its first 3 lines, its exit code,
# its timings), and `report` grades those again with today's grader,
# cases and snapshots: an old run is judged by the new rules offline.
# A new rule goes after the older ones, so the first failing rule of an
# old answer stays the one it was.
#
# The held-out questions (cases.json, split "held") are frozen: tune the
# prompt and the knowledge on the others (`run --split dev`; `recall`
# leaves the held ones out unless told), and read the held ones' score
# on its own line of the report.
#
# The measuring-only seams a run sets for `spark line`, honoured only with
# SPARK_LINE_BENCH=1 (a person's line never reads them):
#   SPARK_LINE_KNOW=off|judge|full   the A/B arm (--arm): no knowledge,
#                                    the verdict and one re-ask only, or
#                                    evidence up front too
#   SPARK_KNOWLEDGE_SNAPSHOT=FILE    the store the line grounds and judges
#                                    in: that OS's snapshot as a store
#                                    (SnapshotStore.save), so the box can
#                                    ground a debian question in debian's
#                                    manuals. The file is plain JSON:
#                                    {"entries": {name: Entry's fields},
#                                    "index": index.json's shape,
#                                    "closed": true, "absent": [names]}.
#                                    Closed: the snapshot is that OS's
#                                    whole PATH, so the line's judge finds
#                                    a program it lacks not installed, as
#                                    it does on a real machine
#   SPARK_LINE_BENCH_HISTORY=FILE    a `??` case's first turn as chat
#                                    history [{"role","content"}]: a bench
#                                    turn keeps no thread, so the pair
#                                    rides this file instead
#   SPARK_LINE_ROLE=spark|ember      which role the line's request names
#                                    (--role): the chat model measured on
#                                    the line with the line's own prompt,
#                                    the person's config unchanged

import json
import math
import os
import re
import shlex
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SPARK = os.path.join(REPO, "bin", "spark")
DATA = os.path.join(HERE, "line_audition")
CASES = os.path.join(DATA, "cases.json")
LIB = os.path.join(REPO, "lib")
sys.path.insert(0, LIB)

OSES = ("debian", "arch", "void", "fedora", "opensuse", "macos")
SUBJECTS = ("tools", "spark")
ARMS = ("off", "judge", "full")
ROLES = ("spark", "ember")         # --role: which model answers the line (SPARK_LINE_ROLE)
HELP_MAX = 4096          # the human-readable part of a snapshot entry
MAN_MAX = 200000         # a man page read for options (git's is ~150 kB)
LINES_MAX = 60           # option lines an entry keeps, each its first sentence
SENTENCE_MAX = 100       # characters of one what, synopsis or option sentence
SYNOPSIS_MAX = 3         # synopsis lines an entry keeps
CASE_KEYS = {"id", "words", "kind", "head_any", "must_not", "not_head", "must", "danger", "spark_verb",
             "answer_any", "topic", "then", "why_review", "split"}
SPLITS = ("dev", "held", "all")    # --split: the cases to tune on, the frozen ones, or both
# the held-out questions' ids and words, hashed (held_sha): they are
# frozen, and the selftest fails when one is reworded, added or dropped
HELD_N, HELD_SHA = 24, "cc5a0ed2e52347ca"
# the line's own words for a reply the model left empty (wire.THOUGHT_OUT
# starts with them; the selftest holds the two equal)
NO_ANSWER = "the model gave no answer"
# the prompt's line that names the preferred tools found on PATH
PREFERRED_LINE = "Preferred when installed"

# Tools a pipeline stage reaches for whatever the question: each OS's
# snapshot holds them, so `du -sh * | sort -h` is judged stage by stage.
COMMON = ("ls", "cat", "grep", "awk", "sed", "sort", "uniq", "head", "tail", "wc", "cut",
          "tr", "xargs", "find", "du", "df", "ps", "pkill", "killall", "pgrep", "less",
          "tee", "date", "stat", "file", "which", "whoami", "id", "groups", "who", "uptime",
          "free", "top", "uname", "hostname", "ln", "cp", "mv", "rm", "mkdir", "chmod",
          "chown", "tar", "gzip", "zip", "unzip", "curl", "wget", "ping", "ssh", "scp",
          "rsync", "git", "sudo", "env", "nohup", "nice", "timeout", "watch", "diff",
          "column", "basename", "dirname", "realpath", "readlink", "touch", "tree", "dmesg",
          "lsof", "sh", "bash", "last", "w")

# A wrapper runs the command after it: the wrapper is a stage of its own
# (it must exist, its options must be real) and so is what it runs. The
# options named here take a value, which is not an option to check.
WRAPPERS = {
    "sudo": ("-u", "-g", "-C", "-D", "-h", "-p", "-U", "-r", "-t", "-T"),
    "doas": ("-u", "-C"),
    "env": ("-u", "-C", "-S"),
    "nice": ("-n",),
    "nohup": (),
    "timeout": ("-s", "-k"),
    "watch": ("-n", "--interval"),
    "xargs": ("-I", "-n", "-P", "-L", "-s", "-d", "-E", "-a"),
}
# the shell's own words beyond persona.SH_BUILTINS: never looked up on PATH
EXTRA_BUILTINS = ("command", "time", "builtin", "pwd", "history", "ulimit", "hash", "[[", "disown")
# kill -9, pkill -HUP: a signal spelled as an option is no option to look up
SIGNAL_HEADS = ("kill", "pkill", "killall")
# never run these to read their help, even with --help: a snapshot is
# gathered as root in a container and on a person's Mac -- man only
NEVER_RUN = ("shutdown", "reboot", "halt", "poweroff", "init", "telinit", "rm", "dd",
             "mkfs", "wipefs", "shred", "kill", "pkill", "killall", "sudo", "doas", "su",
             "login", "passwd", "sh", "bash", "zsh", "top", "htop", "btop", "watch",
             "less", "more", "vi", "vim", "nano", "micro", "ssh", "scp", "sftp",
             "caffeinate", "yes", "cat", "tee", "nohup", "timeout", "xargs", "env",
             # these read --help as a name: pbcopy empties the clipboard,
             # pbpaste prints it, svlogtail follows a log forever, xlocate
             # fetches its index, dig and nslookup ask the network, unlink
             # removes a file named --help, dscl and mdfind search
             "pbcopy", "pbpaste", "svlogtail", "xlocate", "dig", "nslookup", "host",
             "unlink", "dscl", "mdfind", "memory_pressure", "system_profiler", "tmux")
# find -exec rm -f {} ; -- what follows is rm's, not find's, and shlex
# reads the escaped \\; as a plain ; so no stage boundary is left to see
FIND_EXEC = ("-exec", "-execdir", "-ok", "-okdir")
# English words that follow "spark" in a sentence and are no verb: an
# answer's prose ("spark is ...") is not a command to judge
PROSE_AFTER_SPARK = ("is", "can", "cannot", "has", "will", "does", "did", "was", "and",
                     "or", "to", "itself", "the", "on", "in", "uses", "runs", "keeps",
                     "reads", "has", "starts", "needs", "may", "should", "would", "could")

OVERSTRIKE = re.compile(r".\x08")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PRIVATE_V4 = re.compile(r"\b(10\.[0-9]+\.[0-9]+\.[0-9]+|192\.168\.[0-9]+\.[0-9]+|"
                        r"172\.(1[6-9]|2[0-9]|3[01])\.[0-9]+\.[0-9]+)\b")


def die(msg, code=2):
    print("line_audition: " + msg, file=sys.stderr)
    sys.exit(code)


def load_cases(path=CASES):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def split_of(case):
    """A case's split: `held` (frozen, never tuned on), `more` (a second
    phrasing of a spark question, added to tune on beside the first
    report's cases) or `dev` (the first report's cases)."""
    s = (case or {}).get("split")
    return s if s in ("held", "more") else "dev"


def is_held(case):
    """A held-out case: frozen, never tuned on (split "held")."""
    return (case or {}).get("split") == "held"


def held_sha(data):
    """(count, hash) of the held-out cases' ids and words, in file order."""
    import hashlib
    held = [c for k in data["cases"] for c in data["cases"][k] if is_held(c)]
    text = "\n".join("%s\t%s" % (c["id"], c["words"]) for c in held)
    return len(held), hashlib.sha256(text.encode()).hexdigest()[:16]


def cases_for(data, os_name, subject=None, only=None, split="all"):
    """[(subject, case)] for one OS: its own tools, then spark core.
    `split` dev leaves the held-out cases out, held keeps them alone."""
    out = []
    for subj, key in (("tools", os_name), ("spark", "spark")):
        if subject and subject != subj:
            continue
        for c in data["cases"].get(key, ()):
            if only and c["id"] not in only:
                continue
            if split != "all" and is_held(c) != (split == "held"):
                continue
            out.append((subj, c))
    return out


def this_os():
    """The OS this machine is, in the audition's six names, or ""."""
    if sys.platform == "darwin":
        return "macos"
    from spark import distro
    return distro()


# ------------------------------------------------------------ help text
def clean(text):
    """A help or man text as data: no overstrike, no colour, and nothing
    the privacy gate refuses (an e-mail, a private IPv4, a home path)."""
    text = OVERSTRIKE.sub("", ANSI.sub("", text))
    text = EMAIL.sub("<e-mail>", text)
    text = PRIVATE_V4.sub("192.0.2.1", text)
    home = os.path.expanduser("~")
    if home and home != "/":
        text = text.replace(home, "~")
    return text


def options_of(text):
    """The options a help text names, three ways: `long` (--all), `short`
    (every single letter an option can be: -a, and each letter of a BSD
    usage cluster [-ABC]), `words` (a single-dash word: find's -name,
    ip's -br, with ip's -br[ief] spelled out to -brief)."""
    longs, words, short = set(), set(), set()
    for m in re.finditer(r"(?<![\w-])--([A-Za-z0-9][A-Za-z0-9_-]*)", text):
        longs.add("--" + m.group(1).rstrip("-"))
    for m in re.finditer(r"--\[no-?\]([A-Za-z0-9][\w-]*)", text):       # --[no-]pager
        longs.update(("--" + m.group(1), "--no-" + m.group(1)))
    for m in re.finditer(r"(?<![\w-])-([A-Za-z0-9?@%])(?![A-Za-z0-9_-])", text):
        short.add(m.group(1))
    for m in re.finditer(r"\[-([A-Za-z0-9@%?,]{2,})[\] ]", text):         # [-@ABC1%,]
        short.update(c for c in m.group(1) if c != ",")
    for m in re.finditer(r"(?<![\w-])(-[A-Za-z][A-Za-z0-9_-]*)(?:\[([a-z-]+)\])?", text):
        base, rest = m.group(1).rstrip("-"), m.group(2) or ""
        words.add(base)
        for i in range(1, len(rest) + 1):                                    # -br[ief]
            words.add(base + rest[:i])
    return {"long": sorted(longs), "short": "".join(sorted(short)), "words": sorted(words)}


# a manual's sections a person reads for what a tool does and takes; the
# rest (examples, see also, history) is never kept
SKIP_SECTIONS = ("EXAMPLE", "SEE ALSO", "AUTHOR", "BUGS", "HISTORY", "COPYRIGHT", "REPORTING",
                 "STANDARDS", "EXIT STATUS", "ENVIRONMENT", "FILES", "CAVEATS", "COLOPHON")
SECTION = re.compile(r"^[A-Z][A-Z0-9 ,/()-]*[A-Z)]$")


def sections(man):
    """A rendered man page -> [(HEADER, [line, ...])], in order."""
    out, cur = [], None
    for line in man.split("\n"):
        if SECTION.match(line.rstrip()):
            cur = (line.strip(), [])
            out.append(cur)
        elif cur is not None:
            cur[1].append(line.rstrip())
    return out


def _short(text, n=SENTENCE_MAX):
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 3].rstrip() + "..."


def first_sentence(text):
    text = " ".join(text.split())
    m = re.search(r"(?<=\.)\s", text)
    return _short(text[:m.start()] if m else text)


def _indent(line):
    return len(line) - len(line.lstrip(" "))


def option_lines(lines, commands=False):
    """[[tag, first sentence]] from a manual section or a --help text: a
    line that starts with an option (-a, --all, -B, --block-size=SIZE,
    -p PROP) is a tag, its words the rest of that line or the more-indented
    lines under it. With `commands` (a COMMANDS section) a word at the
    section's own indent is a tag too: launchctl's list, sv's status."""
    base = min((_indent(l) for l in lines if l.strip()), default=0)
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        i += 1
        ind = _indent(line)
        if not line.strip() or ind > 14:
            continue
        m = re.match(r"^(\S.*?)(?:\s{2,}|\t|$)(.*)$", line.strip())
        tag, rest = m.group(1), m.group(2)
        under = next((l for l in lines[i:] if l.strip()), "")
        is_opt = re.match(r"^-{1,2}[A-Za-z0-9?@#]", tag) is not None
        if is_opt and len(tag.split()) > 4:
            # -g live displays the settings: one space parts tag and words
            tag, rest = " ".join(tag.split()[:2]), " ".join(tag.split()[2:] + [rest])
        # a subcommand: a word at the section's indent, its words beside it
        # (a short tag) or under it -- never a wrapped line of prose
        is_cmd = (commands and ind == base and re.match(r"^[a-z][\w/-]*(\s|$)", tag) is not None
                  and not tag.endswith((".", ",", ":"))
                  and (_indent(under) > ind or rest and len(tag.split()) <= 3))
        if is_cmd and len(tag) > 48:
            tag = tag[:48].rsplit(" ", 1)[0]       # bootstrap | bootout domain-target [...]
        if not (is_opt or is_cmd) or len(tag) > 48 or ". " in tag:
            continue
        words = [rest] if rest else []
        while i < len(lines) and (not lines[i].strip() and not words or lines[i].strip() and _indent(lines[i]) > ind):
            if lines[i].strip() and re.match(r"^-{1,2}[A-Za-z0-9]", lines[i].strip()) and words:
                break                              # the next option, nested deeper
            if lines[i].strip():
                words.append(lines[i].strip())
            elif words:
                break
            i += 1
        out.append([_short(tag, 48), first_sentence(" ".join(words))])
    return out


def entry_text(helptext, mans):
    """(what, synopsis, lines) of one tool, from its man pages (the first
    one names it) and its --help: what is the man NAME one-liner, the
    synopsis at most 3 lines, the lines each option with its first
    sentence, at most 60 -- the words a store indexes."""
    what, synopsis, lines, seen = "", [], [], set()

    def keep(pairs):
        for tag, words in pairs:
            if tag not in seen and len(lines) < LINES_MAX:
                seen.add(tag)
                lines.append([tag, words])
    for n, man in enumerate(mans):
        for head, body in sections(man):
            if n == 0 and head == "NAME" and not what:
                m = re.search(r"\s[-–—]{1,2}\s(.*)$", " ".join(" ".join(body).split()))
                what = _short(m.group(1)) if m else ""
            elif n == 0 and head == "SYNOPSIS" and not synopsis:
                synopsis = [_short(l) for l in body if l.strip()][:SYNOPSIS_MAX]
            elif not any(s in head for s in SKIP_SECTIONS):
                keep(option_lines(body, commands="COMMAND" in head or "VERB" in head))
    hl = [l.rstrip() for l in helptext.split("\n")]
    if not synopsis:
        synopsis = [_short(re.sub(r"(?i)^\s*(usage|or)\s*:\s*", "", l)) for l in hl
                    if re.match(r"(?i)^\s*(usage|or)\s*:", l)][:SYNOPSIS_MAX]
    if not what:
        for l in hl:
            s = l.strip()
            if (s and not l[:1].isspace() and not s.startswith("-") and len(s.split()) >= 3
                    and not re.match(r"(?i)^(usage|or)\b|.*: (unrecognized|illegal|invalid)", s)):
                what = _short(s)
                break
    keep(option_lines(hl))
    return what, synopsis, lines


def _run_text(argv, env, timeout=15):
    # an empty scratch directory as the cwd: a tool that takes --help for
    # a file name finds nothing of anyone's there
    d = tempfile.mkdtemp(prefix="line-audition-help-")
    try:
        p = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, env=env,
                           timeout=timeout, cwd=d, start_new_session=True)
        return (p.stdout + p.stderr).decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return ""
    finally:
        shutil.rmtree(d, ignore_errors=True)


def collect_tool(tool, path_env, man_extra=()):
    """One snapshot entry: whether the tool exists here, its --help (or
    man synopsis) for a person to read, the options its --help and man
    page name, for the grader, and what a store indexes (what, synopsis,
    lines: see entry_text). --help is run only for tools outside
    NEVER_RUN, with no stdin, a pager of cat and a 15 s cap."""
    env = dict(os.environ, PATH=path_env, LC_ALL="C", LANG="C", PAGER="cat", MANPAGER="cat",
               GIT_PAGER="cat", MANWIDTH="100", TERM="dumb", NO_COLOR="1")
    where = shutil.which(tool, path=path_env)
    entry = {"exists": bool(where), "path": clean(where or "")}
    if not where:
        return entry
    helptext = "" if tool in NEVER_RUN else clean(_run_text([where, "--help"], env))
    mans = []
    for page in (tool,) + tuple(man_extra):
        t = clean(_run_text(["man", page], env))
        # a missing page answers "No manual entry" in a line or two
        if len(t) > 200 and "No manual entry" not in t[:200]:
            mans.append(t[:MAN_MAX])
    entry["man"] = bool(mans)
    shown = helptext if len(helptext.strip()) > 40 else ""
    if not shown and mans:
        m = re.search(r"(?ms)^SYNOPSIS\s*$(.*?)(?=^[A-Z][A-Z ]+\s*$)", mans[0])
        shown = m.group(1) if m else mans[0]
    entry["help"] = shown.strip()[:HELP_MAX]
    entry.update(options_of(helptext + "\n" + "\n".join(mans)))
    entry["what"], entry["synopsis"], entry["lines"] = entry_text(helptext, mans)
    cmds = commands_text(tool, mans)
    if cmds:
        entry["commands"] = cmds
    return entry


def commands_text(tool, mans, render=True):
    """{words, prefix, seen, v}: the commands the tool's manual lists (sv
    status, apt-get install), read by intake's own command_set -- the
    same words a machine's store keeps -- or None. The page is rendered
    once more the way a store renders it (intake's own environment and
    width), so a snapshot holds the list a machine holds; `mans[0]`, the
    page as collect read it, is the fallback (and, with render False, the
    only text read: the selftest's fixture page)."""
    if not mans or not (_IN and hasattr(_IN, "command_set")):
        return None
    page = ""
    man = shutil.which("man", path=_IN.abs_path())
    if man and render:
        rc, out = _IN.bounded([man, tool], "/", _IN._man_env(), _IN.MAN_TIMEOUT, _IN.MAN_TEXT_MAX)
        page = _IN._scrub(out) if rc == 0 and len(out) > 200 else ""
    cs = _IN.command_set(page or mans[0], tool)
    if not cs:
        return None
    return {"words": list(cs.words), "prefix": bool(cs.prefix), "seen": list(cs.seen), "v": _IN.COMMANDS_V}


def tools_for(data, os_name):
    """Every command a snapshot for os_name must describe: the heads its
    cases accept, its `also` list, COMMON, the wrappers, persona's
    PREFERRED (the prompt names them when installed), and the shell's own
    words. Some of those are programs too -- pwd everywhere; command,
    time, ulimit and hash on macOS -- and a run's PATH and its closed
    store hold only what a snapshot found: the snapshot must say which."""
    names = set(COMMON) | set(WRAPPERS) | set(EXTRA_BUILTINS)
    for c in data["cases"].get(os_name, ()):
        # a script the case names (./build.sh) is the person's, not the OS's
        names.update(h for h in c.get("head_any", ()) if h != "spark" and not h.endswith(".sh"))
    names.update(data["oses"][os_name].get("also", ()))
    try:
        from spark import persona
        names.update(persona.PREFERRED)
    except ImportError:
        pass
    return sorted(names)


def cmd_collect(args):
    os_name, out = this_os(), ""
    it = iter(args)
    for a in it:
        if a == "--os":
            os_name = next(it, "")
        elif a == "--out":
            out = next(it, "")
        else:
            die("collect takes --os OS --out FILE")
    if os_name not in OSES:
        die("collect: say --os (one of %s)" % ", ".join(OSES))
    if os_name != this_os():
        # a snapshot is what THIS machine's tools say: debian's help is
        # only true when gathered on debian
        die("collect: this machine is %s, not %s -- run it on %s" % (this_os() or "unknown", os_name, os_name))
    data = load_cases()
    if os_name == "macos":
        # the system's own tools first, so BSD sed's help is what a GNU sed
        # from Homebrew would otherwise hide; Homebrew's after, for brew
        path_env = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin"
        import platform
        pretty = "macOS " + platform.mac_ver()[0]
    else:
        path_env = os.environ.get("PATH", "") + ":/usr/local/sbin:/usr/sbin:/sbin"
        from spark import os_pretty
        pretty = os_pretty()
    man_extra = data["oses"][os_name].get("man", {})
    tools = {}
    for tool in tools_for(data, os_name):
        tools[tool] = collect_tool(tool, path_env, man_extra.get(tool, ()))
    snap = {"os": os_name, "pretty": pretty, "collected": time.strftime("%Y-%m-%d"), "tools": tools}
    out = out or os.path.join(DATA, "help-%s.json" % os_name)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(snap, f, indent=1, sort_keys=True, ensure_ascii=True)
        f.write("\n")
    have = sum(1 for t in tools.values() if t["exists"])
    print("%s: %d tools, %d here, written to %s" % (os_name, len(tools), have, out))
    return 0


def cmd_packages(args):
    """The packages a snapshot job installs first, one line: the tools
    the cases name, as a normal install of that OS has them."""
    if len(args) != 2 or args[0] != "--os" or args[1] not in OSES:
        die("packages takes --os OS")
    print(" ".join(load_cases()["oses"][args[1]].get("install", ())))
    return 0


# ------------------------------------------------------------ the tree
def spark_tree(repo=REPO):
    """spark's verbs and the words each takes, read from what TAB
    completion completes (completion.bash and .zsh: the files smoke's
    drift guard holds to bin/spark's VERBS) and the names that fill its
    dynamic slots (the model tables). persona.KNOW_SHELL and KNOW_CHAT
    add the slots completion cannot list: an upper-case slot (URL, WORDS)
    takes any word, unless completion fills that slot from the tree (a
    model), which keeps it closed."""
    cdir = os.path.join(repo, "home", ".config", "spark")
    bash = open(os.path.join(cdir, "completion.bash"), encoding="utf-8").read()
    zsh = open(os.path.join(cdir, "completion.zsh"), encoding="utf-8").read()
    try:
        from spark import config
        models = sorted(r[0] for r in config.model_tables(repo))
    except Exception:          # a tree whose models.env will not parse still has verbs
        models = []

    def fill(words):
        dynamic = "_spark_model_names" in words
        words = re.sub(r"\$\{\(f\)\"\$\(_spark_model_names\)\"\}|\$\(_spark_model_names\)", " ".join(models), words)
        return set(words.split()), dynamic

    verbs = set()
    m = re.search(r'COMP_CWORD" -eq 1 \]; then\s+words="([^"]*)"', bash)
    verbs.update(m.group(1).split() if m else ())
    m = re.search(r"comp=\(([^)]*)\)", zsh)
    verbs.update(m.group(1).split() if m else ())
    # plumbing completion leaves out on purpose is still a verb that works
    m = re.search(r"Not completed on purpose[^\n]*\n#\s+([^\n]*)", bash)
    verbs.update(m.group(1).split() if m else ())
    words, closed = {}, set()
    for src, pat in ((bash, r'^\s*([a-z| -]+)\)\s+words="([^"]*)"'),
                     (zsh, r'^\s*([a-z| -]+)\)\s+comp=\(((?:[^()]|\([^)]*\))*)\)')):
        for m in re.finditer(pat, src, re.M):
            ws, dynamic = fill(m.group(2))
            for verb in (v.strip() for v in m.group(1).split("|")):
                words.setdefault(verb, set()).update(ws)
                if dynamic:
                    closed.add(verb)
    # the words a verb takes that completion leaves to the cheatsheet's
    # command column: spark forge --print-url, spark bench tune
    try:
        sheet = open(os.path.join(repo, "docs", "CHEATSHEET.txt"), encoding="utf-8").read()
    except OSError:
        sheet = ""
    for cmd, _w in _columns(sheet):
        m = re.search(r"\bspark ([a-z][\w-]*) (\S+)", cmd)
        if m and m.group(1) in words:
            words[m.group(1)].update(a for a in m.group(2).strip("[]").split("|")
                                     if re.match(r"^(--?)?[a-z][\w-]*$", a))
    free, third = set(), {}
    try:
        from spark import persona
        shell, chat = getattr(persona, "KNOW_SHELL", ""), getattr(persona, "KNOW_CHAT", "")
    except ImportError:
        shell, chat = "", ""
    # the shell map: its forms alone, never a description's words. The
    # chat map is prose, read as it always was: every `spark ...` in it
    learn_slots([m for m in (KNOW_FORM.match(f) for f in know_forms(shell)) if m], words, free, third, closed)
    learn_slots(KNOW_FORM.finditer(chat), words, free, third, closed)
    verbs.add("help")
    return {"verbs": verbs, "words": words, "free": free, "third": third, "models": models}


# one `spark VERB [slot]...` form: the verb (alternatives joined by |),
# then the slots, each a run of the characters a slot is written in
KNOW_FORM = re.compile(r"\bspark ([a-z][\w|]*)((?: [\[\]\w|.-]+)*)")


def know_forms(know):
    """The `spark ...` forms persona.KNOW_SHELL names, from either of its
    two formats. One command a line: a head line with no ` -- ` in it,
    then `FORM[, FORM]... -- description` a line, then a tail line
    (`Settings live in ...`) -- the forms are what stands before a
    line's first ` -- `, split on `, `. Or the whole map on one line: a
    head that itself holds ` -- ` and ends in a colon, then the forms
    joined by `; `, up to the tail. A description is never read: its
    words are not commands."""
    lines = [l.strip() for l in know.split("\n") if l.strip()]
    forms = []
    if len(lines) == 1:
        body = lines[0].split(" -- ", 1)[-1].split(": ", 1)[-1].split(" Settings live in", 1)[0]
        forms = [p.strip().rstrip(".") for p in body.split("; ")]
    else:
        for line in lines:
            if " -- " in line and not line.startswith("Settings live in"):
                forms.extend(p.strip() for p in line.split(" -- ", 1)[0].split(", "))
    return [f for f in forms if f.startswith("spark ")]


def learn_slots(matches, words, free, third, closed):
    """What each KNOW_FORM match teaches the tree: the words a verb's
    first slot takes, a verb whose first slot is free (an upper-case
    slot: URL, WORDS), and the third words after a second one (spark
    serve boot on|off)."""
    for m in matches:
        slots = []
        for s in m.group(2).split():
            if s == "--":
                break                          # "spark ember NAME -- the chat model": prose after
            slots.append(s.strip("[].,"))
        for verb in m.group(1).split("|"):
            if not slots:
                continue
            alts = slots[0].split("|")
            if any(a[:1].isupper() for a in alts) and verb not in closed:
                free.add(verb)
            words.setdefault(verb, set()).update(a for a in alts if not a[:1].isupper())
            if len(slots) > 1:
                alts3 = slots[1].split("|")
                if all(a.islower() for a in alts3):
                    for w in alts:
                        third.setdefault((verb, w), set()).update(alts3)


def grade_spark(argv, tree):
    """(ok, detail) for one `spark ...` argv against the tree."""
    if len(argv) < 2:
        return True, ""                        # bare `spark`: the status, a real command
    verb = argv[1]
    if verb not in tree["verbs"]:
        return False, "spark %s: no such verb in the tree" % verb
    if len(argv) < 3 or verb in tree["free"]:
        return True, ""
    w = argv[2]
    known = tree["words"].get(verb)
    if known is not None and w not in known:
        return False, "spark %s %s: not a word %s takes" % (verb, w, verb)
    third = tree["third"].get((verb, w))
    if third and len(argv) > 3 and argv[3] not in third:
        return False, "spark %s %s %s: takes %s" % (verb, w, argv[3], "|".join(sorted(third)))
    return True, ""


# ------------------------------------------------------------ parsing
def _closing(s, i):
    """The index just past the `)` that closes the `(` at s[i], quotes and
    nested parentheses read as the shell reads them. ValueError when it
    never closes."""
    depth, quote, n = 0, "", len(s)
    while i < n:
        ch = s[i]
        if quote:
            if ch == "\\" and quote == '"' and i + 1 < n:
                i += 1
            elif ch == quote:
                quote = ""
        elif ch == "\\" and i + 1 < n:
            i += 1
        elif ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError("No closing parenthesis")


SUB_MARK = re.compile("\x01(\\d+)\x02")


def _lift(command):
    """(text, parts): `command` with each substitution -- $(...), `...`,
    <(...), >(...) and the arithmetic $((...)) -- replaced by a mark that
    stays inside its word, and parts[i] = (the text it stood for, the
    command inside it, "" for arithmetic). Nothing inside single quotes
    is a substitution: awk's '{print $(NF)}' is awk's own."""
    out, parts, quote, i, n = [], [], "", 0, len(command)

    def mark(text, inner):
        parts.append((text, inner))
        out.append("\x01%d\x02" % (len(parts) - 1))
    while i < n:
        ch = command[i]
        if quote == "'":
            out.append(ch)
            quote = "" if ch == "'" else quote
            i += 1
        elif ch == "\\" and i + 1 < n:
            out.append(command[i:i + 2])
            i += 2
        elif ch == "$" and command[i + 1:i + 2] == "(":
            j = _closing(command, i + 1)
            text = command[i:j]
            mark(text, "" if text.startswith("$((") and text.endswith("))") else text[2:-1])
            i = j
        elif ch == "`":
            j = command.find("`", i + 1)
            if j < 0:
                raise ValueError("No closing backtick")
            mark(command[i:j + 1], command[i + 1:j])
            i = j + 1
        elif not quote and ch in "<>" and command[i + 1:i + 2] == "(":
            j = _closing(command, i + 1)
            mark(command[i:j], command[i + 2:j - 1])
            i = j
        else:
            if ch == '"':
                quote = "" if quote else ch
            elif ch == "'" and not quote:
                quote = ch
            out.append(ch)
            i += 1
    return "".join(out), parts


def split_stages(command):
    """The command's stages as [[word, ...], ...], split on | || && ; &
    and parentheses; a redirection and its target are dropped. A
    substitution -- $(...), backticks, <(...) -- stays inside its word,
    and the command inside it follows as stages of its own, so
    `launchctl kickstart -k gui/$(id -u)/NAME` is launchctl's stage and
    id's. Raises ValueError on a bad quote (shlex's own) or a
    substitution that never closes."""
    text, parts = _lift(command)
    lex = shlex.shlex(text, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    stages, cur, skip = [], [], False
    for tok in lex:
        if skip:
            skip = False
            continue
        if tok in ("|", "||", "&&", ";", "&", "|&", "(", ")", ";;"):
            if cur:
                stages.append(cur)
            cur = []
        elif tok in (">", ">>", "<", "<<", "<<<", ">&", "&>", ">|", "<>", "&>>"):
            skip = True
            if cur and cur[-1].isdigit():
                cur.pop()                      # 2> : the 2 is the stream, not a word
        elif re.match(r"^[()]+$", tok):
            continue
        else:
            cur.append(SUB_MARK.sub(lambda m: parts[int(m.group(1))][0], tok))
    if cur:
        stages.append(cur)
    for _text, inner in parts:
        if inner.strip():
            stages.extend(split_stages(inner))
    return stages


def substituted(word):
    """Is a word made by a substitution: nothing to look up by name."""
    return "$(" in word or "`" in word


SHELLS = ("sh", "bash", "zsh", "dash", "ksh")
# the shell's own words that run the command after them: time sudo ls
RUNS_NEXT = ("time", "command", "exec", "builtin", "setsid")


def heads_run(stages, depth=0):
    """Every head word the stages would run, as base names: each stage's
    head and its wrappers' (unwrap), the command after time or exec, the
    command a find -exec runs, and the commands inside `sh -c '...'`.
    What a case's not_head is held against."""
    out = []
    for st in stages:
        for head, args in unwrap(st):
            base = head.rsplit("/", 1)[-1]
            out.append(base)
            if base in RUNS_NEXT and depth < 3:
                rest = list(args)
                while rest and rest[0].startswith("-"):
                    rest.pop(0)
                out.extend(heads_run([rest], depth + 1))
            if base == "find":
                for i, a in enumerate(args):
                    if a in FIND_EXEC and args[i + 1:]:
                        out.extend(h.rsplit("/", 1)[-1] for h, _a in unwrap(args[i + 1:]))
            if base in SHELLS and depth < 3:
                for i, a in enumerate(args[:-1]):
                    if re.match(r"^-[A-Za-z]*c$", a):
                        try:
                            out.extend(heads_run(split_stages(args[i + 1]), depth + 1))
                        except ValueError:
                            pass
                        break
    return out


def not_run(names, stages, text):
    """The not_head entries a reply breaks. Each entry is a regex held
    whole against every head the command would run (heads_run). With no
    stages -- an answer in words, a command shlex cannot read -- an entry
    is looked for as a word of the text, never inside a path or a longer
    name (/var/service, sshd.service)."""
    if stages is None:
        return [n for n in names if re.search(r"(?<![\w/.-])(?:%s)(?![\w/-])" % n, text)]
    heads = heads_run(stages)
    return [n for n in names if any(re.fullmatch(n, h) for h in heads)]


def unwrap(stage):
    """One stage -> [(head, args)], a wrapper and the command it runs as
    separate entries; env assignments before the head are dropped."""
    out = []
    words = list(stage)
    while words:
        while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            words.pop(0)
        if not words:
            break
        head, rest = words[0], words[1:]
        if head not in WRAPPERS:
            out.append((head, rest))
            break
        valued = WRAPPERS[head]
        own = []
        while rest and rest[0].startswith("-") and rest[0] != "-":
            opt = rest.pop(0)
            own.append(opt)
            if opt == "--":
                break
            if opt in valued and rest:
                rest.pop(0)                    # sudo -u NAME: NAME is a value
        if head == "env":
            while rest and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", rest[0]):
                rest.pop(0)
        if head == "timeout" and rest:
            rest.pop(0)                        # the duration
        out.append((head, own))
        if head == "watch" and len(rest) == 1 and " " in rest[0]:
            try:
                rest = shlex.split(rest[0])    # watch 'df -h': the quoted command
            except ValueError:
                rest = []
        words = rest
    return out


def option_ok(tok, prev, head, entry):
    """Whether one option token of a stage is in that tool's help."""
    longs, short, words = set(entry.get("long", ())), set(entry.get("short", "")), set(entry.get("words", ()))
    if tok.startswith("--"):
        return tok.split("=", 1)[0] in longs
    if re.match(r"^-\d+[A-Za-z]?$", tok):
        # -7 after find's -mtime is its value; tail -20 is the old count
        if tok in words or all(c in short for c in tok[1:] if c.isdigit()):
            return True
        if prev and prev.startswith("-"):
            return True
        return head in ("head", "tail") or head in SIGNAL_HEADS
    if head in SIGNAL_HEADS and re.match(r"^-[A-Z][A-Z0-9]*$", tok):
        return True                            # kill -HUP
    if tok in words:
        return True
    m = re.match(r"^-([A-Za-z?@]+)(.*)$", tok)
    if not m:
        return True                            # -, -:, an odd value: nothing to look up
    return all(c in short for c in m.group(1))


def stage_rules(head, args, snap, builtins):
    """(exists_ok, flags_ok, detail) for one non-spark stage."""
    base = head.rsplit("/", 1)[-1]
    if head.startswith(("./", "~/", "../")) or head in builtins or base in builtins or substituted(head):
        return True, True, ""
    entry = snap.get("tools", {}).get(base)
    if not entry or not entry.get("exists"):
        return False, True, "%s: not on %s" % (base, snap.get("os", "?"))
    bad = bad_options(base, args, entry)
    if bad:
        return True, False, "%s: %s not in its help" % (base, " ".join(bad))
    return True, True, ""


def bad_options(base, args, entry):
    """The option tokens of one stage its tool's help does not name."""
    bad, prev = [], ""
    for tok in args:
        if tok == "--" or tok in FIND_EXEC:
            break                              # the rest is another command's words
        if tok.startswith("-") and tok != "-" and not option_ok(tok, prev, base, entry):
            bad.append(tok)
        prev = tok
    return bad


def unknown_flags(command, snap, builtins):
    """[(tool, option)] a command passes that its tool's help (on the
    snapshot's OS) does not name; a tool not there is `exists`'s finding."""
    try:
        stages = split_stages(command)
    except ValueError:
        return []
    out = []
    for head, args in (pair for st in stages for pair in unwrap(st)):
        base = head.rsplit("/", 1)[-1]
        if (base in ("spark", "explain") or head.startswith(("./", "~/", "../")) or base in builtins
                or substituted(head)):
            continue
        entry = snap.get("tools", {}).get(base)
        if entry and entry.get("exists"):
            out.extend((base, tok) for tok in bad_options(base, args, entry))
    return out


def spark_mentions(text):
    """The `spark ...` commands an answer in words names: a code span that
    starts with spark, else each `spark WORD ...` whose WORD is not prose."""
    spans = [s for s in re.findall(r"`([^`]+)`", text) if s.strip().startswith("spark")]
    if spans:
        out = []
        for s in spans:
            try:
                out.append(shlex.split(s))
            except ValueError:
                out.append(s.split())
        return out
    out = []
    for m in re.finditer(r"\bspark((?: [a-z0-9][\w.:/-]*)+)", text):
        words = m.group(1).split()
        if words and words[0] not in PROSE_AFTER_SPARK:
            out.append(["spark"] + words[:3])
    return out


# ------------------------------------------------------------ grading
def parse_reply(stdout):
    """contract 4's lines -> (kind, command, text, proof); kind "" when
    line 1 is not one of the four shapes."""
    lines = stdout.split("\n")
    first = lines[0] if lines else ""
    second = lines[1] if len(lines) > 1 else ""
    third = lines[2] if len(lines) > 2 else ""
    proof = third[6:] if third.startswith("proof\t") else ""
    if first.startswith(("cmd\t", "danger\t")):
        kind, command = first.split("\t", 1)
        return kind, command, second, proof
    if first in ("answer", "error"):
        return first, "", second, ""
    return "", "", second, ""


def grade(case, stdout, snap, tree, builtins, rc=None):
    """[(rule, ok, detail)] for one answer. Every rule is mechanical.
    `rc` is the reply's exit code, None when a record kept none. The
    rules come in a fixed order, a newer rule after the older ones
    (`must`, then `answered`, last), so the first failing rule of an old
    answer is the one it always was."""
    kind, command, text, _proof = parse_reply(stdout)
    rules = []
    shape = kind in ("cmd", "danger") and bool(command.strip()) or kind == "answer" and bool(text.strip())
    rules.append(("contract", shape, "" if shape else "line 1 %r: %s" % (stdout.split("\n")[0][:40], text[:60])))
    if shape:
        rules.extend(_graded(case, kind, command, text, snap, tree, builtins))
        judged = text if kind == "answer" else command
        lacks = [p for p in case.get("must", ()) if not re.search(p, judged)]
        if case.get("must"):
            rules.append(("must", not lacks, "lacks %s" % " ".join(lacks) if lacks else ""))
    if rc is not None:
        # a reply cut after line 1 keeps its command and exits 1, its
        # line 2 the reason: line 1 alone is no answer
        rules.append(("answered", rc == 0, "" if rc == 0 else "exit %d: %s" % (rc, text[:60])))
    return rules


def _graded(case, kind, command, text, snap, tree, builtins):
    """grade's rules for a reply of contract 4's shape, `must` and
    `answered` aside."""
    rules = []
    want = case.get("kind")
    got = "answer" if kind == "answer" else "cmd"
    rules.append(("kind", want in (None, got), "" if want in (None, got) else "wanted %s, got %s" % (want, got)))
    judged = command if got == "cmd" else text
    stages, unread = None, ""
    if got == "cmd":
        try:
            stages = split_stages(command)
        except ValueError as e:
            unread = str(e)
    # must_not is a pattern of the text; not_head a command that must not
    # run, read from the stages. Both report as must_not
    why = [p for p in case.get("must_not", ()) if re.search(p, judged)]
    why = ["matches " + " ".join(why)] if why else []
    ran = not_run(case.get("not_head", ()), stages, judged)
    if ran:
        why.append("runs " + " ".join(ran))
    rules.append(("must_not", not why, "; ".join(why)))
    if got == "answer":
        spark_case = case.get("spark_verb") is not None
        if spark_case:
            said = spark_mentions(text)
            bad = [d for ok, d in (grade_spark(a, tree) for a in said) if not ok]
            rules.append(("spark tree", not bad, "; ".join(bad)))
            hit = any(len(a) > 1 and a[1] in case["spark_verb"] for a in said)
            rules.append(("head", hit, "" if hit else "names no spark %s" % "|".join(case["spark_verb"])))
        if case.get("answer_any"):
            ok = any(re.search(p, text) for p in case["answer_any"])
            rules.append(("answer", ok, "" if ok else "says none of %s" % " ".join(case["answer_any"])))
        return rules
    danger = case.get("danger")
    if danger is not None:
        ok = (kind == "danger") == bool(danger)
        rules.append(("danger", ok, "" if ok else "wanted %s, got %s" % ("danger" if danger else "cmd", kind)))
    if stages is None:
        rules.append(("parse", False, unread))
        return rules
    runs = [pair for st in stages for pair in unwrap(st)]
    heads = [h.rsplit("/", 1)[-1] for h, _a in runs]
    head_any = case.get("head_any") or []
    if case.get("spark_verb") is not None:
        verbs = [a[0] for h, a in runs if h == "spark" and a]
        ok = any(v in case["spark_verb"] for v in verbs)
        rules.append(("head", ok, "" if ok else "spark %s, wanted %s" % (" ".join(verbs) or "-", "|".join(case["spark_verb"]))))
    elif head_any:
        ok = any(h in head_any for h in heads)
        rules.append(("head", ok, "" if ok else "%s, wanted %s" % (" ".join(heads), "|".join(head_any))))
    missing, flags, tree_bad = [], [], []
    for head, args in runs:
        if head.rsplit("/", 1)[-1] in ("spark", "explain"):
            if head.endswith("spark"):
                ok, why = grade_spark(["spark"] + args, tree)
                if not ok:
                    tree_bad.append(why)
            continue
        ex, fl, why = stage_rules(head, args, snap, builtins)
        if not ex:
            missing.append(why)
        elif not fl:
            flags.append(why)
    rules.append(("exists", not missing, "; ".join(missing)))
    rules.append(("flags", not flags, "; ".join(flags)))
    if tree_bad or case.get("spark_verb") is not None:
        rules.append(("spark tree", not tree_bad, "; ".join(tree_bad)))
    return rules


def builtins_set():
    try:
        from spark import persona
        return set(persona.SH_BUILTINS) | set(EXTRA_BUILTINS)
    except ImportError:
        return set(EXTRA_BUILTINS)


def load_snapshot(os_name, path=None):
    path = path or os.path.join(DATA, "help-%s.json" % os_name)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------ the store
# A snapshot as intake.Store: the audition grounds and judges a question in
# the OS it speaks as, whatever machine runs it. The tokenizer is intake's
# own (intake.words) when the tree has it, else the local copy below of the
# same rule (lowercase, stopwords, crude suffixes) -- the index must be cut
# the way grounding cuts the question.
STOPWORDS = frozenset("a an the and or of to in on for with by is are was be been it its this that "
                      "these those my me i you your we our at as from into how do does did what "
                      "which who whom when where why can could would should will there here".split())


def _local_words(text):
    out = []
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if len(w) < 2 or w in STOPWORDS:
            continue
        for suf, rep, n in (("ies", "y", 4), ("sses", "ss", 5), ("xes", "x", 4), ("ches", "ch", 5),
                            ("shes", "sh", 5), ("ing", "", 6), ("ed", "", 5), ("s", "", 4)):
            if w.endswith(suf) and len(w) >= n and not (suf == "s" and w.endswith(("ss", "us", "is"))):
                w = w[:len(w) - len(suf)] + rep
                break
        out.append(w)
    return out


def tokenizer():
    """(words function, "intake" | "local")."""
    try:
        from spark import intake
        if callable(getattr(intake, "words", None)):
            return intake.words, "intake"
    except ImportError:
        pass
    return _local_words, "local"


def _intake():
    try:
        from spark import intake
        return intake
    except ImportError:
        return None


_IN = _intake()
_Base = _IN.Store if _IN else object


def make_entry(d):
    """A JSON entry dict -> intake.Entry (a dict when intake is absent)."""
    o = d.get("options") or {}
    opts = (o.get("long", ()), o.get("short", ""), o.get("words", ()))
    fields = dict(d, options=_IN.OptionSet(*opts) if _IN else opts,
                  synopsis=tuple(d.get("synopsis", ())), lines=tuple(tuple(x) for x in d.get("lines", ())))
    if not _IN:
        return fields
    return _IN.Entry(*(fields.get(k) for k in _IN.Entry._fields))


def tool_entry(name, t, os_name):
    """One snapshot tool -> an entry dict. A snapshot from before the
    store fields reads them from its `help` text instead."""
    what, synopsis, lines = t.get("what"), t.get("synopsis"), t.get("lines")
    if what is None or synopsis is None or lines is None:
        w2, s2, l2 = entry_text(t.get("help", ""), [])
        what, synopsis, lines = what or w2, synopsis or s2, lines or l2
    d = {"name": name, "kind": "program", "source": "man" if t.get("man") else "help",
         "what": what or "", "synopsis": list(synopsis or ()), "lines": [list(x) for x in lines or ()],
         "options": {"long": list(t.get("long", ())), "short": t.get("short", ""),
                     "words": list(t.get("words", ()))},
         "origin": "snapshot:" + os_name, "stamp": None}
    # a snapshot collected before commands were kept has none: its 3
    # synopsis lines and 60 option lines are a list cut short, never a
    # list (the workflow collects them again)
    # one from before v1.87 has a list with no `v`: intake.commands_of
    # reads it as none, since the older reader could cut a list short
    c = t.get("commands")
    if isinstance(c, dict) and c.get("words"):
        d["commands"] = {"words": list(c["words"]), "prefix": bool(c.get("prefix"))}
        if "v" in c:
            d["commands"].update(seen=list(c.get("seen", ())), v=c["v"])
    return d


def _columns(text):
    """[[command column, words]] of a help-shaped text (spark help, the
    cheatsheet): the words column is where the continuation lines start."""
    lines = text.split("\n")
    conts = [_indent(l) for l in lines if l.strip() and _indent(l) >= 16]
    col = max(set(conts), key=conts.count) if conts else 30
    out = []
    for l in lines:
        if not l.strip():
            continue
        if _indent(l) >= col - 1 and out:
            out[-1][1] = (out[-1][1] + " " + l.strip()).strip()
        elif _indent(l) < 4:
            out.append([l[:col].strip(), l[col:].strip()])
    return out


_SPARK = {}


def spark_entries():
    """spark's own verbs as a machine's store holds them: every verb
    completion lists (but help), each read from its own `spark VERB -h`
    run the way intake runs it (intake.spark_help: an empty home, 5
    seconds) and parsed by the same intake.spark_entry -- so recall
    measures the entries that ship. Once per process; {} without intake."""
    if _SPARK or not _IN or not hasattr(_IN, "spark_entry"):
        return dict(_SPARK)
    from concurrent.futures import ThreadPoolExecutor
    subs, verbs = _IN.spark_words()
    slots = _IN.spark_slots()
    todo = [None] + [v for v in verbs if _IN.NAME_SHAPE.match(v) and v != "help"]
    scratch = tempfile.mkdtemp(prefix="line-audition-spark-")
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            texts = list(pool.map(lambda v: _IN.spark_help(v, scratch), todo))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    for verb, text in zip(todo, texts):
        if not text:
            continue
        name, what, synopsis, opts, lines = _IN.spark_entry(verb, clean(text), subs, slots)
        _SPARK[name] = {"name": name, "kind": "spark", "source": "tree", "what": what,
                        "synopsis": [l for l in synopsis.split("\n") if l],
                        "lines": list(lines),
                        "options": {"long": list(opts.long), "short": "".join(x.lstrip("-") for x in opts.short),
                                    "words": list(opts.words)},
                        "origin": "spark", "stamp": None}
    return dict(_SPARK)


class SnapshotStore(_Base):
    """intake.Store over one OS's help snapshot (help-<os>.json): every tool
    that exists there is an entry, spark's verbs too (spark=True), and the
    index is built in memory. A file SnapshotStore.save wrote loads as it
    is, with no build: what SPARK_KNOWLEDGE_SNAPSHOT names for a run.
    The store is closed: the snapshot is that OS's whole PATH, so a
    program it does not hold is not there (has_program), and the tools
    the snapshot looked for and did not find are kept by name (absent)."""

    def __init__(self, path=None, spark=True, snap=None):
        doc = snap
        if doc is None:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        self.os = doc.get("os", "?")
        if "line_audition_store" in doc:
            self._entries, self._index, self.tokenizer = doc["entries"], doc["index"], doc.get("tokenizer", "?")
            self.absent = sorted(doc.get("absent") or ())
            return
        _words, self.tokenizer = tokenizer()
        self.absent = sorted(n for n, t in doc.get("tools", {}).items() if not t.get("exists"))
        self._entries = dict((n, tool_entry(n, t, self.os)) for n, t in doc.get("tools", {}).items()
                             if t.get("exists"))
        if spark:
            self._entries.update(spark_entries())
        # the store's own index, built by the same code a machine's is
        self._index = _IN.index_of((n, _IN.entry_terms(e)) for n, e in self._entries.items()) if _IN else None

    def names(self):
        return sorted(self._entries)

    def entry(self, name):
        d = self._entries.get(name)
        return make_entry(d) if d else None

    def index(self):
        return self._index

    def has_program(self, name):
        """Is `name` a program of that OS: the snapshot is its whole PATH."""
        return name in self._entries and name not in self.absent

    def save(self, path):
        # closed: grounding's reader answers "not there" for a program
        # this file lacks or names absent, so the judge's `missing`
        # finding fires in a run as it does on a real machine
        doc = {"line_audition_store": 1, "os": self.os, "tokenizer": self.tokenizer,
               "closed": True, "absent": self.absent,
               "entries": self._entries, "index": self._index}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
        return path


# ------------------------------------------------------------ run
def persona_env(os_name, snap, data, scratch, url):
    """The environment one `spark line` runs in to speak as os_name: the
    seams spark already reads, and a PATH that is one directory of stubs
    ALONE -- a stub for every tool the snapshot says that OS has, and its
    package manager. So what the prompt says is installed (the package
    manager, the preferred tools) and what the head-word guard finds are
    that OS's, never this machine's: fd, rg or micro on the machine the
    audition runs on reach no prompt. The harness needs nothing from
    PATH: it starts python (sys.executable) and bin/spark by their
    absolute paths. A stub does nothing and exits 127.

    Two facts of this machine that spark reads through PATH are pinned
    first, with the real PATH: its name (on a Mac config asks scutil for
    it) and the console's glyphs (a tmux probe). They stay what the line
    says here on any other day."""
    from spark import ASCII, config
    env = dict(os.environ)
    env["SPARK_LINE_BENCH"] = "1"          # the turn's numbers, marked bench; no thread
    for k in ("SPARK_EXPLAIN_CMD", "SPARK_EXPLAIN_RC", "SPARK_HINT_ROW", "SPARK_DEBUG",
              "SPARK_LINE_KNOW", "SPARK_KNOWLEDGE_SNAPSHOT", "SPARK_LINE_BENCH_HISTORY", "SPARK_LINE_ROLE"):
        env.pop(k, None)
    env["SITE_NAME"] = config.load().name
    if ASCII:
        env["SPARK_ASCII"] = "1"
    stubs = os.path.join(scratch, "bin")
    os.makedirs(stubs, exist_ok=True)
    have = [t for t, e in (snap or {}).get("tools", {}).items() if e.get("exists")]
    if not have:
        have = [h for c in data["cases"].get(os_name, ()) for h in c.get("head_any", ())]
    have.append(data["oses"][os_name].get("pm", ""))
    for tool in sorted(set(t for t in have if t and "/" not in t)):
        p = os.path.join(stubs, tool)
        with open(p, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n# line_audition: a stub, so this OS's tool is on PATH; it does nothing\nexit 127\n")
        os.chmod(p, 0o755)
    env["PATH"] = stubs
    if os_name != "macos":
        o = data["oses"][os_name]
        rel = os.path.join(scratch, "os-release")
        with open(rel, "w", encoding="utf-8") as f:
            f.write('PRETTY_NAME="%s"\nID=%s\n' % (o["pretty"], o["id"]))
        proc = os.path.join(scratch, "proc-version")
        with open(proc, "w", encoding="utf-8") as f:
            f.write("Linux version 6.0 (line audition)\n")     # never WSL
        runit = os.path.join(scratch, "etc-runit")
        if o.get("init") == "runit":
            os.makedirs(runit, exist_ok=True)
        env.update(SPARK_OS_RELEASE=rel, SPARK_PROC_VERSION=proc, SPARK_ETC_RUNIT=runit)
    if url:
        env["SPARK_BASE_URL"] = url
    return env


PREFIX_PROBE = ("import sys; sys.path.insert(0, sys.argv[1])\n"
                "from spark import config, persona\n"
                "print(persona.prefix(config.load(), 'bash'))\n")


def preferred_named(prefix):
    """The tools the prompt's Preferred line names, in its order."""
    for line in prefix.splitlines():
        if line.startswith(PREFERRED_LINE) and ": " in line:
            return [t.strip() for t in line.split(": ", 1)[1].rstrip(".").split(",") if t.strip()]
    return []


def check_prefix(os_name, data, env, snap=None):
    """The prompt spark will send, checked before any case: python starts
    with the run's PATH, the prompt names this OS's package manager and
    init, and its Preferred line names the preferred tools the snapshot
    says this OS has -- those and no other: a tool of the machine the
    audition runs on must not be in it. Returns (ok, prefix, why)."""
    p = subprocess.run([sys.executable, "-c", PREFIX_PROBE, LIB], env=env, capture_output=True, text=True)
    prefix = p.stdout
    if p.returncode != 0 or not prefix.strip():
        said = (p.stderr.strip().splitlines() or ["no output"])[-1][:120]
        return False, prefix, "python (%s) did not start with the run's PATH alone: %s" % (sys.executable, said)
    o = data["oses"][os_name]
    want = []
    if o.get("pm") and shutil.which(o["pm"], path=env["PATH"]):
        want.append("Package manager: %s." % o["pm"])
    want.append("System tools: " + {"runit": "sv,", "systemd": "systemctl", "launchd": "launchctl"}[o["init"]])
    miss = [w for w in want if w not in prefix]
    if miss:
        return False, prefix, "the prompt lacks %r" % miss[0]
    if snap:
        from spark import persona
        here = set(t for t, e in snap.get("tools", {}).items() if e.get("exists"))
        named = preferred_named(prefix)
        extra = [t for t in named if t not in here]
        if extra:
            return False, prefix, ("the prompt prefers %s, which %s's snapshot lacks: a tool of this machine "
                                   "is on the run's PATH" % (", ".join(extra), os_name))
        lost = [t for t in persona.PREFERRED if t in here and t not in named]
        if lost:
            return False, prefix, "the prompt does not prefer %s, which %s's snapshot has" % (", ".join(lost), os_name)
    return True, prefix, ""


def newest_turn(sizes_before):
    """The turn record `spark line` just appended (the newest `line` one
    past each file's size before the case), or {}. It carries no words:
    session.record drops them."""
    from spark import TURNS_DIR
    rec = {}
    try:
        names = sorted(n for n in os.listdir(TURNS_DIR) if n.endswith(".jsonl"))
    except OSError:
        return rec
    for n in names:
        p = os.path.join(TURNS_DIR, n)
        with open(p, "rb") as f:
            f.seek(sizes_before.get(p, 0))
            for line in f.read().decode("utf-8", "replace").splitlines():
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("mode") == "line":
                    rec = d
    return rec


def turn_sizes():
    from spark import TURNS_DIR
    out = {}
    try:
        for n in os.listdir(TURNS_DIR):
            p = os.path.join(TURNS_DIR, n)
            out[p] = os.path.getsize(p)
    except OSError:
        pass
    return out


def timing(rec):
    """prompt ms, first-token ms, tokens out, from the turn record: the
    fields WP2 may add by name, else derived from llama-server's own
    (pp_n / pp_tps is the prompt's reading time)."""
    prompt = rec.get("prompt_ms")
    if prompt is None and rec.get("pp_n") and rec.get("pp_tps"):
        prompt = int(1000.0 * rec["pp_n"] / rec["pp_tps"])
    first = rec.get("first_token_ms", rec.get("first_ms", rec.get("ttft_ms")))
    return prompt, first, rec.get("tg_n")


def brief_sha():
    import hashlib
    try:
        from spark import persona
        return hashlib.sha256((persona.MODES["line"] + repr(persona.LINE_SCHEMA)).encode()).hexdigest()[:12]
    except (ImportError, KeyError, AttributeError):
        return "?"


def ask_line(words, env, cwd):
    """One `spark line` turn: (rc, stdout, stderr, total ms, turn record)."""
    before = turn_sizes()
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, SPARK, "line", "--cwd", cwd, "--shell", "bash"],
                           input=words + "\n", capture_output=True, text=True,
                           env=env, timeout=300, cwd=cwd)
        rc, stdout, stderr = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        rc, stdout, stderr = -1, "error\ntimed out after 300 s\n", ""
    return rc, stdout, stderr, int((time.time() - t0) * 1000), newest_turn(before)


def shown_of(stdout):
    """What a thread keeps of one line answer, as cli.cmd_line appends it:
    "`command` -- hint" for a command, the words for an answer."""
    kind, command, text, _proof = parse_reply(stdout)
    return "`%s` -- %s" % (command, text) if kind in ("cmd", "danger") else text


def cmd_run(args):
    os_name, model, url, out, subject, only, verbose, snap_path = "", "", "", "", None, set(), False, None
    arm, store, role, split = "", "snapshot", "", "all"
    it = iter(args)
    for a in it:
        if a == "--os":
            os_name = next(it, "")
        elif a == "--model":
            model = next(it, "")
        elif a == "--url":
            url = next(it, "").rstrip("/")
        elif a == "--arm":
            arm = next(it, "")
        elif a == "--role":
            role = next(it, "")
        elif a == "--out":
            out = next(it, "")
        elif a == "--subject":
            subject = next(it, "")
        elif a == "--split":
            split = next(it, "")
        elif a == "--case":
            only.add(next(it, ""))
        elif a == "--snapshot":
            snap_path = next(it, "")
        elif a == "--store":
            store = next(it, "")
        elif a == "-v":
            verbose = True
        else:
            die("run takes --os OS --model NAME [--url URL] [--arm off|judge|full] [--role spark|ember] "
                "[--out FILE] [--split dev|held|all] [--subject tools|spark] [--case ID] "
                "[--store snapshot|local] [-v]")
    if os_name not in OSES or not model:
        die("run: say --os (one of %s) and --model NAME (the label the report groups by)" % ", ".join(OSES))
    if subject and subject not in SUBJECTS:
        die("run: --subject is tools or spark")
    if split not in SPLITS:
        die("run: --split is dev (the held-out cases left out), held (those alone) or all")
    if arm and arm not in ARMS:
        die("run: --arm is off, judge or full")
    if role and role not in ROLES:
        die("run: --role is spark or ember")
    if store not in ("snapshot", "local"):
        die("run: --store is snapshot (the OS's snapshot, the default) or local (this machine's own index, "
            "for the OS it runs on)")
    here_mac = sys.platform == "darwin"
    if (os_name == "macos") != here_mac:
        # persona.prefix reads platform.system() for macOS, with no seam
        die("run: %s cases run on %s" % (os_name, "a Mac" if os_name == "macos" else "Linux (any family)"))
    data = load_cases()
    snap = load_snapshot(os_name, snap_path)
    if snap is None:
        print("line_audition: no help-%s.json yet -- answers are kept, graded by `report` once it exists" % os_name)
    # a snapshot gathered before a tool was asked about says nothing of
    # it, and a run takes what the snapshot does not hold for not there
    unasked = [t for t in tools_for(data, os_name) if t not in (snap or {}).get("tools", {})] if snap else []
    if unasked:
        print("line_audition: help-%s.json has no word on %s -- collect it again; until then this run takes "
              "them for not installed" % (os_name, ", ".join(unasked)))
    tree, builtins = spark_tree(), builtins_set()
    scratch = tempfile.mkdtemp(prefix="line-audition-")
    started = time.strftime("%Y-%m-%d %H:%M:%S")       # before the first case, not when the file is written
    try:
        env = persona_env(os_name, snap, data, scratch, url)
        if arm:
            env["SPARK_LINE_KNOW"] = arm
        if role:
            env["SPARK_LINE_ROLE"] = role
        if snap and store == "snapshot":
            # the store the line grounds and judges in: this OS's, built
            # once here so no turn pays for the build (--store local: the
            # machine's own index instead, the OS it runs on; the grade
            # still reads the snapshot, the independent referee)
            env["SPARK_KNOWLEDGE_SNAPSHOT"] = SnapshotStore(snap=snap).save(
                os.path.join(scratch, "store-%s.json" % os_name))
        ok, prefix, why = check_prefix(os_name, data, env, snap)
        if not ok:
            die("run: cannot speak as %s here: %s" % (os_name, why))
        cwd = os.path.join(scratch, "cwd")
        os.makedirs(cwd)
        results = []
        todo = cases_for(data, os_name, subject, only, split)
        for n, (subj, case) in enumerate(todo, 1):
            first = None
            if case.get("then"):
                # a `??` pair: the first turn, then the follow-up with the
                # first as its history (a bench turn keeps no thread)
                first = ask_line("? " + case["words"], env, cwd)
                hist = os.path.join(scratch, "history.json")
                with open(hist, "w", encoding="utf-8") as f:
                    json.dump([{"role": "user", "content": case["words"]},
                               {"role": "assistant", "content": shown_of(first[1])}], f)
                rc, stdout, stderr, total, rec = ask_line("?? " + case["then"],
                                                          dict(env, SPARK_LINE_BENCH_HISTORY=hist), cwd)
            else:
                rc, stdout, stderr, total, rec = ask_line("? " + case["words"], env, cwd)
            prompt_ms, first_ms, tok = timing(rec)
            rules = grade(case, stdout, snap, tree, builtins, rc) if snap else []
            passed = bool(rules) and all(r[1] for r in rules)
            results.append({"id": case["id"], "subject": subj, "split": split_of(case),
                            "words": case["words"], "rc": rc,
                            "then": case.get("then"), "raw_first": first[1].split("\n")[:3] if first else None,
                            "raw": stdout.split("\n")[:3], "stderr": stderr[-400:],
                            "rules": rules, "pass": passed if snap else None, "total_ms": total,
                            "cmd_ms": rec.get("cmd_ms"), "reasked": rec.get("reasked"),
                            "evidence_chars": rec.get("evidence_chars"),
                            # the seam's stderr banner: the line read this OS's store
                            "store_seen": "SPARK_KNOWLEDGE_SNAPSHOT" in stderr,
                            "prompt_ms": prompt_ms, "first_token_ms": first_ms, "tokens_out": tok,
                            "cache_n": rec.get("cache_n"), "turn_model": rec.get("model")})
            mark = "?" if not snap else ("ok" if passed else "FAIL")
            fails = ", ".join("%s (%s)" % (r[0], r[2]) if r[2] else r[0] for r in rules if not r[1])
            print("%3d/%d %-4s %-14s %6d ms  %s" % (n, len(todo), mark, case["id"], total, fails[:60]))
            if verbose:
                print("        " + " | ".join(stdout.split("\n")[:3]))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if snap and results and not any(r["store_seen"] for r in results):
        print("line_audition: no turn named SPARK_KNOWLEDGE_SNAPSHOT on stderr -- this spark line "
              "grounds in this machine's own store, not %s's" % os_name)
    import hashlib
    # started is when the first case was asked, ended when the last came
    # back; ts is the start too (it was the time of writing until v1.87)
    doc = {"tool": "line_audition", "version": 1, "os": os_name, "model": model, "url": url,
           "arm": arm or "default", "role": role or "spark", "split": split,
           "ts": started, "started": started, "ended": time.strftime("%Y-%m-%d %H:%M:%S"), "brief": brief_sha(),
           "prefix_sha": hashlib.sha256(prefix.encode()).hexdigest()[:12],
           "prefix_facts": [l for l in prefix.splitlines()
                            if l.startswith(("Package manager", "System tools", PREFERRED_LINE))],
           "snapshot": (snap or {}).get("collected"), "snapshot_lacks": unasked, "cases": results}
    if not out:
        from spark import STATE_DIR
        d = os.path.join(STATE_DIR, "line_audition")
        os.makedirs(d, exist_ok=True)
        out = os.path.join(d, "%s-%s-%s%s.json" % (time.strftime("%Y%m%d-%H%M%S"), os_name,
                                                   re.sub(r"[^\w.-]", "_", model), "-" + arm if arm else ""))
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print("written to %s -- python3 tests/line_audition.py report %s" % (out, out))
    return 0


# ------------------------------------------------------------ report
def _median(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return int(statistics.median(xs)) if xs else None


def _p90(xs):
    xs = sorted(x for x in xs if isinstance(x, (int, float)))
    return int(xs[-(-9 * len(xs) // 10) - 1]) if xs else None


def _frac(n, d):
    return "%d/%d %3d %%" % (n, d, 100 * n // d) if d else "-"


def _ms(xs):
    xs = list(xs)
    m, p = _median(xs), _p90(xs)
    return "-" if m is None else "%d/%d" % (m, p)


# the production bar (AGENTS.md, "The audition"): the report says which
# part of it a group of runs meets
BAR_PASS = 90            # tools per OS and spark core, in %
BAR_CMD_MS = 2300        # command ready, median, on the 4B on the box


def no_answer(kind, line2, rc):
    """Did a reply hold no answer: line 1 `error` with the model's
    no-answer reason, or line 1 out and then a non-zero exit (the reply
    was cut: line 2 is the reason, not a hint)."""
    if kind == "error":
        return NO_ANSWER in line2
    return kind in ("cmd", "danger", "answer") and rc not in (0, None)


def command_heads(command):
    """The head words a command would run, [] when it cannot be read."""
    try:
        return heads_run(split_stages(command))
    except ValueError:
        return []


def measures(sel, by_id, snaps, builtins):
    """The report's second table for one group of results: (danger recall,
    over-fire, flag honesty) as (n, of) pairs, the re-ask share, the
    median evidence characters, and the total and command-ready ms.
    - danger recall: the cases marked danger that came back danger
    - over-fire: the cases not marked danger (false or either) that came
      back danger, over every such case
    - flag honesty: the painted commands whose every option is in its
      tool's help on that OS, or whose hint names the option
    - empty: the replies with no answer in them -- line 1 `error` with
      the model's no-answer reason, or a reply cut after line 1 (a
      non-zero exit) -- over every reply
    - leak: the tools cases answered with a `spark` command, over every
      tools case: spark's own verbs reaching a question about the OS"""
    rec, over, honest, empty, leak = [0, 0], [0, 0], [0, 0], [0, 0], [0, 0]
    for o, r in sel:
        case = by_id.get(r["id"], {})
        kind, command, hint, _p = parse_reply("\n".join(r.get("raw") or ()))
        if case.get("danger") is True:
            rec[1] += 1
            rec[0] += kind == "danger"
        else:
            over[1] += 1
            over[0] += kind == "danger"
        if kind in ("cmd", "danger") and command.strip() and snaps.get(o):
            honest[1] += 1
            bad = unknown_flags(command, snaps[o], builtins)
            honest[0] += all(tok.split("=", 1)[0] in hint for _t, tok in bad)
        empty[1] += 1
        empty[0] += no_answer(kind, hint, r.get("rc"))
        if r.get("subject", "spark" if case.get("spark_verb") is not None else "tools") == "tools":
            leak[1] += 1
            leak[0] += kind in ("cmd", "danger") and "spark" in command_heads(command)
    asked = [r["reasked"] for _o, r in sel if r.get("reasked") is not None]
    return {"danger": tuple(rec), "over": tuple(over), "honest": tuple(honest),
            "empty": tuple(empty), "leak": tuple(leak),
            "reask": (sum(1 for a in asked if a), len(asked)),
            "evidence": _median(r.get("evidence_chars") for _o, r in sel),
            "total": [r.get("total_ms") for _o, r in sel], "cmd": [r.get("cmd_ms") for _o, r in sel]}


def report_lines(docs, tree, builtins, data, snaps, split="all"):
    """The report as lines: one block per (model, arm). Each answer is
    re-graded against today's snapshot, tree and cases when the snapshot
    is there -- from its kept lines and exit code alone -- so a new
    grader or a refreshed snapshot re-judges an old run. `split` dev
    leaves the held-out cases out, held keeps them alone; the held-out
    cases' score is a line of its own either way."""
    by_id = dict((c["id"], c) for k in data["cases"] for c in data["cases"][k])

    def held(r):
        return is_held(by_id.get(r["id"]) or r)
    runs = {}
    for doc in docs:
        snap = snaps.get(doc["os"])
        for r in doc["cases"]:
            case = by_id.get(r["id"])
            if split != "all" and held(r) != (split == "held"):
                continue
            if snap and case:
                r["rules"] = grade(case, "\n".join(r["raw"]), snap, tree, builtins, r.get("rc"))
                r["pass"] = all(x[1] for x in r["rules"])
            runs.setdefault((doc["model"], doc.get("arm") or "default"), []).append((doc["os"], r))
    out = []
    for model, arm in sorted(runs):
        rows = runs[(model, arm)]
        out.append("model %s, arm %s" % (model, arm))
        out.append("  %-8s %-16s %-16s %10s %9s" % ("os", "tools", "spark core", "median ms", "tok out"))
        second, misses = [], []
        for os_name in OSES + ("all",):
            sel = [(o, r) for o, r in rows if os_name in ("all", o)]
            if not sel:
                continue
            cells = []
            for subj in SUBJECTS:
                s = [r for _o, r in sel if r["subject"] == subj and r["pass"] is not None]
                p = sum(1 for r in s if r["pass"])
                cells.append(_frac(p, len(s)))
                if os_name != "all" and subj == "tools" and s and 100 * p < BAR_PASS * len(s):
                    misses.append("%s tools %d %%" % (os_name, 100 * p // len(s)))
            ms = _median(r.get("total_ms") for _o, r in sel)
            tok = _median(r.get("tokens_out") for _o, r in sel)
            out.append("  %-8s %-16s %-16s %10s %9s" % (os_name, cells[0], cells[1],
                                                      "-" if ms is None else ms, "-" if tok is None else tok))
            m = measures(sel, by_id, snaps, builtins)
            second.append("  %-8s %-14s %-14s %-14s %-12s %5s %12s %11s  %-12s %s" % (
                os_name, _frac(*m["danger"]), _frac(*m["over"]), _frac(*m["honest"]), _frac(*m["reask"]),
                "-" if m["evidence"] is None else m["evidence"], _ms(m["total"]), _ms(m["cmd"]),
                _frac(*m["empty"]), _frac(*m["leak"])))
            if os_name == "all":
                core = [r for _o, r in sel if r["subject"] == "spark" and r["pass"] is not None
                        and split_of(by_id.get(r["id"]) or r) == "dev"]
                p = sum(1 for r in core if r["pass"])
                if core and 100 * p < BAR_PASS * len(core):
                    misses.append("spark core %d %%" % (100 * p // len(core)))
                if m["danger"][0] < m["danger"][1]:
                    misses.append("danger recall %d/%d" % m["danger"])
                if m["honest"][0] < m["honest"][1]:
                    misses.append("flag honesty %d/%d" % m["honest"])
                cmd = _median(m["cmd"])
                if cmd is not None and cmd > BAR_CMD_MS:
                    misses.append("command ready %d ms" % cmd)
        # the held-out questions: never tuned on, so their score says
        # whether a gain on the others is a gain at all
        def of(name):
            return [r for _o, r in rows if r["subject"] == "spark" and r["pass"] is not None
                    and split_of(by_id.get(r["id"]) or r) == name]
        kept, more, first = of("held"), of("more"), of("dev")
        if kept or more:
            for name, got, why in (("first", first, "the first report's spark questions: the bar reads these"),
                                   ("more", more, "second phrasings, tuned on"),
                                   ("held", kept, "held-out, frozen, never tuned on")):
                if got:
                    out.append("  %-8s %-16s %-14s (%s)" % (name, "", _frac(sum(1 for r in got if r["pass"]), len(got)), why))
        out.append("  %-8s %-14s %-14s %-14s %-12s %5s %12s %11s  %-12s %s" % (
            "os", "danger recall", "over-fire", "flag honesty", "re-asks", "evid.", "total p50/90", "cmd p50/90",
            "empty", "leak"))
        out.extend(second)
        out.append("  bar: " + ("met" if not misses else "not met -- " + ", ".join(misses)))
        failed = [(o, r) for o, r in rows if r["pass"] is False]
        if failed:
            out.append("  failed:")
        for o, r in failed:
            rule = next((x for x in r["rules"] if not x[1]), ["?", False, ""])
            what = r["raw"][0].replace("\t", " ") if r["raw"] else ""
            out.append(("  %-14s %-10s %s" % (r["id"], rule[0], what))[:100])
        out.append("")
    return out


def cmd_report(args):
    """One block per model and arm: pass rate per OS x subject, the median
    total ms and tokens out; the held-out cases' score on a line of its
    own; the danger, flag, speed, empty and leak measures; the bar; then
    every failed case on one line."""
    split, paths = "all", []
    it = iter(args)
    for a in it:
        if a == "--split":
            split = next(it, "")
        else:
            paths.append(a)
    if not paths or split not in SPLITS:
        die("report takes [--split dev|held|all] and one or more results files")
    docs = []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            docs.append(json.load(f))
    snaps = dict((d["os"], load_snapshot(d["os"])) for d in docs)
    print("\n".join(report_lines(docs, spark_tree(), builtins_set(), load_cases(), snaps, split)))
    return 0


# ------------------------------------------------------------ recall
def recall_targets(case):
    """The entries a case's evidence should hold: its heads, or spark's
    own verb entries ("spark look") for a spark core case."""
    if case.get("spark_verb") is not None:
        return ["spark " + v for v in case["spark_verb"]]
    return [h for h in case.get("head_any", ()) if h != "spark"]


def recall_run(todo, store, search, k):
    """[(subject, case, ok, got names, ms)]: is any target among the top k
    that search returns for the case's words (a pair's first words)."""
    out = []
    for subj, c in todo:
        t0 = time.time()
        hits = search(c["words"], k=k, store=store) or []
        ms = (time.time() - t0) * 1000
        got = [getattr(h, "name", None) or h[0] for h in hits][:k]
        out.append((subj, c, any(w in got for w in recall_targets(c)), got, ms))
    return out


def recall_lines(os_name, rows, k, verbose=False):
    topics = {}
    for subj, c, ok, _got, _ms in rows:
        t = topics.setdefault(c.get("topic") or subj, [0, 0])
        t[0] += ok
        t[1] += 1
    ms = [r[4] for r in rows]
    ms_s = sorted(ms)
    p95 = ms_s[-(-95 * len(ms_s) // 100) - 1] if ms_s else 0
    out = ["recall %s, top %d: %s  (search p50 %.1f ms, p95 %.1f ms)"
           % (os_name, k, _frac(sum(1 for r in rows if r[2]), len(rows)),
              statistics.median(ms) if ms else 0, p95)]
    for t in sorted(topics):
        out.append("  %-12s %s" % (t, _frac(*topics[t])))
    for subj, c, ok, got, _ms in rows:
        if not ok:
            out.append(("  miss %-14s wanted %s%s" % (c["id"], "|".join(recall_targets(c)),
                                                       ", got " + " ".join(got) if verbose else ""))[:120])
    return out


# the margins `recall --margins` sweeps for grounding.CONFIDENT: 0 is
# evidence up front whatever the margin (the top hit need not clear the
# floor itself), 1.0 the floor on the top hit alone
MARGINS = (0, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.75, 2.0, 2.5, 3.0)


def margin_run(todo, store, grounding):
    """{margin: {subject: [rides, right]}}: at each margin, how many cases'
    first request would carry evidence up front (grounding.evidence with
    confident=True), and how many of those carry one of the case's
    targets as the top entry -- recall@1 of what rides."""
    out = {}
    saved = grounding.CONFIDENT
    try:
        for m in MARGINS:
            grounding.CONFIDENT = m
            row = out.setdefault(m, {})
            for subj, c in todo:
                ev = grounding.evidence(c["words"], (), store, confident=bool(m))
                cell = row.setdefault(subj, [0, 0, 0])
                cell[2] += 1
                if ev.names:
                    cell[0] += 1
                    cell[1] += ev.names[0] in recall_targets(c)
    finally:
        grounding.CONFIDENT = saved
    return out


def margin_lines(title, runs):
    """The tradeoff table: per margin and subject, the cases evidence
    rides up front, how many of those lead with a right entry, and the
    wrong ones (misleading evidence)."""
    out = ["%s: evidence up front by margin (rides/cases, right first, wrong first)" % title,
           "  margin   " + "".join("%-29s" % ("spark core" if x == "spark" else x) for x in SUBJECTS).rstrip()]
    for m in MARGINS:
        cells = []
        for subj in SUBJECTS:
            rides, right, n = [sum(r[m].get(subj, [0, 0, 0])[i] for r in runs) for i in range(3)]
            cells.append("%3d/%-3d right %3d  wrong %3d" % (rides, n, right, rides - right))
        out.append("  %-6s   %s   %s" % ("off" if m == 0 else "%.2f" % m, cells[0], cells[1]))
    return out


def cmd_recall(args):
    """Offline, no model: for each case of each OS asked, is any of its
    heads among the top k entries grounding.search finds in that OS's
    snapshot store (SnapshotStore, spark's verbs included). --margins:
    the tradeoff table grounding.CONFIDENT is chosen from. Recall is
    what the search is tuned on, so the held-out cases are left out
    unless --split says held or all."""
    oses, k, verbose, margins, split = [], 3, False, False, "dev"
    it = iter(args)
    for a in it:
        if a == "--os":
            v = next(it, "")
            oses.extend(OSES if v == "all" else [v])
        elif a == "--k":
            v = next(it, "")
            k = int(v) if v.isdigit() and int(v) > 0 else die("recall: --k is a whole number")
        elif a == "--split":
            split = next(it, "")
        elif a == "-v":
            verbose = True
        elif a == "--margins":
            margins = True
        else:
            die("recall takes --os OS|all [--k 3] [--split dev|held|all] [-v] [--margins]")
    if not oses or any(o not in OSES for o in oses):
        die("recall: say --os (one of %s, or all)" % ", ".join(OSES))
    if split not in SPLITS:
        die("recall: --split is dev (the default: the held-out cases left out), held or all")
    try:
        from spark import grounding
    except ImportError:
        die("recall: no spark.grounding in this tree")
    data = load_cases()
    runs = []
    for os_name in oses:
        snap = load_snapshot(os_name)
        if snap is None:
            die("recall: no help-%s.json" % os_name)
        store = SnapshotStore(snap=snap)
        probe = next((n for n in ("ls", "grep", "cat") if n in store.names()), store.names()[0])
        if not grounding.search(probe, k=1, store=store):
            print("recall: grounding.search is still a stub (no hit for %r, a name the store holds)" % probe)
            return 2
        if margins:
            runs.append(margin_run(cases_for(data, os_name, split=split), store, grounding))
            print("\n".join(margin_lines(os_name, runs[-1:])))
            continue
        rows = recall_run(cases_for(data, os_name, split=split), store, grounding.search, k)
        print("\n".join(recall_lines(os_name, rows, k, verbose)))
        print("  (%d entries, the %s tokenizer)" % (len(store.names()), store.tokenizer))
    if margins and len(runs) > 1:
        print("\n".join(margin_lines("all", runs)))
        print("  (grounding.CONFIDENT is %s)" % grounding.CONFIDENT)
    return 0


# ------------------------------------------------------------ candidate
def cmd_serve_candidate(args):
    """A llama-server for one candidate model on its own port, started the
    way spark serves a single line model (engine.server_cmd's single
    branch), so `run --url` measures the model and not a different set of
    flags. It stops on Ctrl-C."""
    model_file, port, host = "", "8090", "127.0.0.1"
    it = iter(args)
    for a in it:
        if a == "--model-file":
            model_file = next(it, "")
        elif a == "--port":
            port = next(it, "")
        elif a == "--host":
            host = next(it, "")
        else:
            die("serve-candidate takes --model-file PATH [--port 8090] [--host 127.0.0.1]")
    if not os.path.isfile(model_file) or not port.isdigit():
        die("serve-candidate: --model-file must be a .gguf file and --port a number")
    os.environ["SPARK_PORT"] = port            # config reads the environment first
    from spark import config, engine
    cfg = config.load()
    if not engine.engine_bin(cfg):
        die("serve-candidate: no llama-server in %s" % engine.engine_dir(cfg))
    # server_cmd serves the roles it finds and rewrites the router's
    # directory: the candidate is one model alone, and the running
    # engine's router files stay untouched
    path = os.path.abspath(model_file)
    engine.roles = lambda _cfg: {"spark": path, "ember": ""}
    engine.write_router = lambda _cfg: None
    argv = engine.render_wrap(engine.server_cmd(cfg, host))
    url = "http://%s:%s" % (host, port)
    # a server already on the port would answer for this candidate: a run
    # would then measure the wrong model (a 1.7B left on :8090 answered a
    # whole 4B run once)
    from spark import wire
    if wire.health(url) != "down":
        die("serve-candidate: %s already answers -- stop that server first" % url)
    print("serving %s at %s (Ctrl-C stops it)" % (os.path.basename(path), url))
    print("then: python3 tests/line_audition.py run --os OS --model %s --url %s"
          % (engine.model_stem(path), url))
    sys.stdout.flush()
    # become the server: its pid is this one, so a kill or Ctrl-C stops the
    # server itself and leaves nothing holding the port
    os.execvpe(argv[0], argv, engine.server_env(cfg))


# ------------------------------------------------------------ selftest
SELF_SNAP = {
    "os": "fake",
    "tools": {
        "ls": {"exists": True, **options_of("usage: ls [-@ABCFGHILOPRSTUWXabcdefghiklmnopqrstuvwxy1%,] [--color=when]")},
        "du": {"exists": True, **options_of("  -s, --summarize\n  -h, --human-readable\n  -d, --max-depth=N")},
        "sort": {"exists": True, **options_of("  -h, --human-numeric-sort\n  -r, --reverse")},
        "sed": {"exists": True, **options_of("usage: sed [-Ealnru] command [file ...]\n       sed [-Ealnu] [-i extension] [file ...]")},
        "find": {"exists": True, **options_of("find [-H | -L | -P] path ... -name pattern -mtime n -size n[ckMG] -type t -delete")},
        "rm": {"exists": True, **options_of("usage: rm [-f | -i] [-dIPRrvWx] file ...")},
        "ip": {"exists": True, **options_of("OPTIONS := { -V[ersion] | -s[tatistics] | -br[ief] | -4 | -6 }")},
        "xbps-install": {"exists": True, **options_of(" -S, --sync\n -u, --update\n -y, --yes")},
        "sudo": {"exists": True, **options_of("usage: sudo [-u user] [-i] command")},
        "ln": {"exists": True, **options_of("usage: ln [-s [-F] | -L | -P] [-f | -i] [-hnv] source_file [target_file]")},
        "grep": {"exists": True, **options_of("usage: grep [-abcdDEFGHhIiJLlMmnOopqRSsUVvwXxZz] [-e pattern] [file ...]")},
        "awk": {"exists": True, **options_of("usage: awk [-F fs] [-v var=value] [prog | -f progfile] [file ...]")},
        "systemctl": {"exists": True, **options_of("  -a --all\n     --user\n     --no-pager")},
        "launchctl": {"exists": True, **options_of("Usage: launchctl kickstart [-k] [-p] service-target")},
        "id": {"exists": True, **options_of("usage: id [-G | -g | -u] [-nr] [user]")},
        "vm_stat": {"exists": True},
        "groups": {"exists": True},
        "apt": {"exists": False},
        "free": {"exists": False},
    },
}
# persona.KNOW_SHELL in its two formats, a sample of each: one line of
# `; `-joined forms after a head that holds ` -- ` (until v1.86), and one
# command a line, `FORM[, FORM]... -- description` (from v1.87)
KNOW_ONE_LINE = ("spark's own commands -- when the user asks how to change or run spark itself, answer with "
                 "these: spark soul edit|reset; spark memory add <words>; cmd 2>&1 | explain; spark serve on|off; "
                 "spark serve boot on|off; spark client URL|off; spark clear --history; spark off|on|ver. "
                 "Settings live in ~/.config/spark/spark.env (SPARK_REVEAL) and site.env.")
KNOW_BY_LINE = ("spark's own commands, one a line: the forms, then what each does.\n"
                "spark soul edit, spark soul reset -- who spark is: change it, or the first one again\n"
                "spark memory add WORDS -- keep a fact\n"
                "cmd 2>&1 | explain -- what went wrong\n"
                "spark serve, spark serve on, spark serve off -- start or stop the engine and the page\n"
                "spark serve boot on, spark serve boot off -- up from boot -- or not; spark keeps it\n"
                "spark client URL, spark client off -- another machine's model, or this one's again\n"
                "spark clear --history -- forget the conversations\n"
                "spark check -- is spark ok: every check, what to fix; spark frobnicate is no command\n"
                "Settings live in ~/.config/spark/spark.env (SPARK_REVEAL) and site.env.")


def cmd_selftest(_args):
    """Canned answers against SELF_SNAP and the real tree: a right answer
    passes, and each way to be wrong fails on the rule that names it."""
    tree, builtins = spark_tree(), builtins_set()
    fails = []

    def expect(what, case, stdout, want_pass, rule=None, rc=None):
        rules = grade(case, stdout, SELF_SNAP, tree, builtins, rc)
        passed = all(r[1] for r in rules)
        bad = [r[0] for r in rules if not r[1]]
        ok = passed == want_pass and (rule is None or rule in bad)
        print(("ok   " if ok else "FAIL ") + what + ("" if ok else "  -- rules: %r" % rules))
        if not ok:
            fails.append(what)

    def check(ok, what, detail=""):
        print(("ok   " if ok else "FAIL ") + what + ("" if ok or not detail else "  -- %s" % (detail,)))
        if not ok:
            fails.append(what)

    def first_failed(case, stdout, rc=None):
        return next((r[0] for r in grade(case, stdout, SELF_SNAP, tree, builtins, rc) if not r[1]), "")

    ls = {"id": "t", "words": "list with sizes", "kind": "cmd", "head_any": ["ls"], "danger": False,
          "not_head": ["sudo"]}
    expect("a right answer passes (a BSD cluster -laS)", ls, "cmd\tls -laS\nlists\n", True)
    expect("a made-up flag fails", ls, "cmd\tls --frobnicate\nlists\n", False, "flags")
    expect("a made-up letter in a cluster fails", ls, "cmd\tls -lZ\nlists\n", False, "flags")
    expect("sudo on a read fails", ls, "danger\tsudo ls -la\nlists\n", False, "must_not")
    du = {"id": "t", "words": "biggest folders", "kind": "cmd", "head_any": ["du"], "danger": False}
    expect("a pipeline passes stage by stage", du, "cmd\tdu -sh -- * | sort -hr\nsizes\n", True)
    expect("a bad flag in the second stage fails", du, "cmd\tdu -sh * | sort --humanize\nsizes\n", False, "flags")
    expect("a head that is not on the OS fails", du, "cmd\tapt install ncdu\ninstall\n", False, "exists")
    expect("the wrong head fails", du, "cmd\tls -la\nlists\n", False, "head")
    find = {"id": "t", "words": "old logs", "kind": "cmd", "head_any": ["find"], "danger": None}
    expect("find's single-dash words and a -7 value pass", find, "cmd\tfind . -name '*.log' -mtime -7\nold\n", True)
    ip = {"id": "t", "words": "my ip", "kind": "cmd", "head_any": ["ip"], "danger": False}
    expect("ip -brief (from -br[ief]) and -4 pass", ip, "cmd\tip -4 -brief addr\naddresses\n", True)
    rm = {"id": "t", "words": "delete tmp", "kind": "cmd", "head_any": ["rm", "find"], "danger": True}
    expect("a delete marked danger passes", rm, "danger\trm -f -- *.tmp\ndeletes\n", True)
    expect("a delete without danger fails", rm, "cmd\trm -f -- *.tmp\ndeletes\n", False, "danger")
    expect("a read marked danger fails", ls, "danger\tls -la\nlists\n", False, "danger")
    sed = {"id": "t", "words": "replace foo", "kind": "cmd", "head_any": ["sed"], "danger": None,
           "must_not": [r"\bsed\s+(-\w+\s+)*-i(?!\s*''|\s*\"\"|\.\w)", r"--in-place"]}
    expect("BSD sed -i '' passes on macos", sed, "danger\tsed -i '' 's/foo/bar/' notes.txt\nreplaces\n", True)
    expect("GNU sed -i fails on macos", sed, "danger\tsed -i 's/foo/bar/' notes.txt\nreplaces\n", False, "must_not")
    xi = {"id": "t", "words": "install htop", "kind": "cmd", "head_any": ["xbps-install"], "danger": None}
    expect("a wrapper and its command both pass", xi, "danger\tsudo xbps-install -Sy htop\ninstalls\n", True)
    expect("contract: an error is no answer", xi, "error\nno model answers\n", False, "contract")
    sp = {"id": "t", "words": "up from boot", "kind": None, "head_any": ["spark"], "spark_verb": ["serve"], "danger": None}
    expect("a real spark verb and word pass", sp, "cmd\tspark serve boot on\nboots\n", True)
    expect("a retired spark verb fails (spark shell on)", sp, "cmd\tspark shell on\nshell\n", False, "spark tree")
    expect("a removed spark verb fails (spark quiet, v1.69)", sp, "cmd\tspark quiet start on\nquiets\n", False,
           "spark tree")
    expect("a word the verb does not take fails", sp, "cmd\tspark serve loud on\nboots\n", False, "spark tree")
    expect("a third word outside on|off fails", sp, "cmd\tspark serve boot enable\nboots\n", False, "spark tree")
    expect("an answer naming the verb in words passes", sp, "answer\nRun `spark serve boot on` and log in again.\n", True)
    expect("an answer naming a retired verb fails", sp, "answer\nRun spark shell on, then reboot.\n", False, "spark tree")
    lk = {"id": "t", "words": "the look", "kind": None, "head_any": ["spark"], "spark_verb": ["look"], "danger": None}
    expect("the look's one switch passes", lk, "cmd\tspark look off\nlook\n", True)
    expect("a part of the look fails (v1.69: one switch)", lk, "cmd\tspark look motion on\nlook\n", False, "spark tree")
    mo = {"id": "t", "words": "a model", "kind": "cmd", "head_any": ["spark"], "spark_verb": ["model"], "danger": None}
    if tree["models"]:
        expect("a model from the tables passes", mo, "cmd\tspark model %s\nmodel\n" % tree["models"][0], True)
    expect("a model not in the tables fails", mo, "cmd\tspark model hotdogstand\nmodel\n", False, "spark tree")
    cl = {"id": "t", "words": "client", "kind": "cmd", "head_any": ["spark"], "spark_verb": ["client"], "danger": None}
    expect("a free slot (URL) takes any word", cl, "cmd\tspark client http://box:8080\nclient\n", True)

    # not_head: a command that must not RUN, read from the stages. The
    # right answers below are the ones a pattern of the text failed
    svc = {"id": "t", "words": "start sshd at every boot", "kind": "cmd", "head_any": ["ln", "ls"], "danger": None,
           "not_head": ["systemctl", "journalctl", "service"]}
    expect("not_head: a path that holds the word is no hit (ln -s /etc/sv/sshd /var/service/)", svc,
           "danger\tln -s /etc/sv/sshd /var/service/\nlinks the service\n", True)
    expect("not_head: ls /var/service passes", svc, "cmd\tls /var/service\nlists\n", True)
    expect("not_head: the command itself fails, under must_not", svc, "cmd\tsystemctl --all\nlists\n", False,
           "must_not")
    expect("not_head: behind a wrapper too (sudo systemctl)", svc, "danger\tsudo systemctl --all\nlists\n", False,
           "must_not")
    unit = {"id": "t", "words": "is sshd running", "kind": "cmd", "head_any": ["systemctl"], "danger": None,
            "not_head": ["service", "sv"]}
    expect("not_head: a unit's name is no hit (systemctl status sshd.service)", unit,
           "cmd\tsystemctl --no-pager status sshd.service\nstatus\n", True)
    mem = {"id": "t", "words": "how much memory is free", "kind": "cmd", "head_any": ["vm_stat"], "danger": False,
           "not_head": ["free"]}
    expect("not_head: a word inside a quoted pattern is no hit (grep 'Pages free')", mem,
           "cmd\tvm_stat | grep 'Pages free'\nfree pages\n", True)
    expect("not_head: free itself fails, under must_not", mem, "cmd\tfree -h\nmemory\n", False, "must_not")
    expect("not_head: sudo as a word of the command is no hit (grep sudo)", ls, "cmd\tls -la | grep sudo\nlists\n", True)
    expect("not_head: the command a find -exec runs counts", dict(find, not_head=["sudo"]),
           "danger\tfind . -name '*.log' -exec sudo rm -f {} \\;\ndeletes\n", False, "must_not")
    expect("not_head: the command inside sh -c counts", ls, "cmd\tsh -c 'sudo ls -la'\nlists\n", False, "must_not")
    expect("not_head: the command after time counts", ls, "cmd\ttime sudo ls -la\nlists\n", False, "must_not")
    expect("not_head: a pipe into sudo counts (ls | sudo tee)", ls, "cmd\tls -la | sudo tee list.txt\nlists\n", False,
           "must_not")
    expect("not_head: a regex entry is held whole against a head (xbps-\\w+)", dict(ls, not_head=[r"xbps-\w+"]),
           "cmd\txbps-install -S | ls\nlists\n", False, "must_not")
    init = {"id": "t", "words": "which init", "kind": None, "head_any": ["ls"], "danger": False,
            "answer_any": ["(?i)runit"], "not_head": ["service", "sudo"]}
    expect("not_head: an answer in words may name a path that holds the word", init,
           "answer\nrunit: its services are the links in /var/service.\n", True)
    expect("not_head: an answer in words that names the command fails", init,
           "answer\nrunit; ask it with sudo sv status.\n", False, "must_not")
    check(first_failed(ls, "danger\tsudo ls -la\nlists\n") == "must_not",
          "not_head: the first failing rule is must_not, as it was when sudo was a pattern")

    # a substitution stays inside its word, and the command inside it is
    # a stage of its own
    kick = {"id": "t", "words": "restart the agent", "kind": "cmd", "head_any": ["launchctl"], "danger": None}
    expect("a substitution stays in its word (launchctl kickstart -k gui/$(id -u)/com.example.agent)", kick,
           "danger\tlaunchctl kickstart -k gui/$(id -u)/com.example.agent\nrestarts\n", True)
    expect("the command inside a substitution is graded: a made-up flag fails", kick,
           "danger\tlaunchctl kickstart -k gui/$(id --frobnicate)/com.example.agent\nrestarts\n", False, "flags")
    expect("the command inside a substitution is graded: a tool not on the OS fails", ls,
           "cmd\tls -la $(apt list)\nlists\n", False, "exists")
    expect("backticks are a substitution too", ls, "cmd\tls -la `apt list`\nlists\n", False, "exists")
    expect("a process substitution's command is graded, and may hold the head", du,
           "cmd\tsort -r <(du -s -- *)\nsizes\n", True)
    expect("a process substitution's made-up flag fails", du, "cmd\tsort -r <(du --frobnicate)\nsizes\n", False, "flags")
    expect("awk's own $(NF) in single quotes is no command", ls, "cmd\tls -la | awk '{print $(NF)}'\nnames\n", True)
    expect("a substitution that never closes is a parse failure", ls, "cmd\tls -la $(id -u\nlists\n", False, "parse")
    check(split_stages("launchctl kickstart -k gui/$(id -u)/com.example.agent")
          == [["launchctl", "kickstart", "-k", "gui/$(id -u)/com.example.agent"], ["id", "-u"]]
          and split_stages("diff <(ls a) <(ls b)") == [["diff", "<(ls a)", "<(ls b)"], ["ls", "a"], ["ls", "b"]]
          and split_stages("echo \"now $(date +%s)\" `whoami`")
          == [["echo", "now $(date +%s)", "`whoami`"], ["date", "+%s"], ["whoami"]]
          and split_stages("a $(b $(c)) | d") == [["a", "$(b $(c))"], ["d"], ["b", "$(c)"], ["c"]]
          and split_stages("echo $((1+2)) '$(x)'") == [["echo", "$((1+2))", "$(x)"]],
          "split_stages: $(...), backticks and <(...) stay words, their commands follow; arithmetic and "
          "single quotes hold none")

    # must: what a right answer cannot leave out
    chat = {"id": "t", "words": "a bigger model for chat", "kind": None, "head_any": ["spark"],
            "spark_verb": ["model"], "danger": None, "must": ["--chat"]}
    expect("must: the command holds it", chat, "cmd\tspark model --chat list\nthe chat models\n", True)
    expect("must: the verb alone fails", chat, "cmd\tspark model list\nthe models\n", False, "must")
    expect("must: an answer in words holds it", chat, "answer\nRun `spark model --chat list` and pick one.\n", True)
    expect("must: an answer in words without it fails", chat, "answer\nRun `spark model list`.\n", False, "must")
    check(first_failed(chat, "cmd\tspark serve on\nserves\n") == "head",
          "must: a newer rule comes after the older ones -- the first failing rule is still head")
    miss = {"id": "t", "words": "watch processes with htop", "kind": None, "head_any": ["xbps-install"],
            "danger": None, "answer_any": [r"(?i)\bhtop\b"], "must": [r"(?i)\bhtop\b", r"\bxbps-install\b"]}
    expect("must: every pattern -- an answer that only names the missing tool fails", miss,
           "answer\nhtop is not installed on this machine.\n", False, "must")
    expect("must: an answer that names the tool and its install command passes", miss,
           "answer\nhtop is not installed: sudo xbps-install -S htop adds it.\n", True)
    expect("must: the install command itself passes", miss, "danger\tsudo xbps-install -Sy htop\ninstalls\n", True)

    # answered: a reply that exits non-zero is no answer, whatever line 1 holds
    gr = {"id": "t", "words": "which groups am I in", "kind": "cmd", "head_any": ["groups", "id"], "danger": False}
    cut = "cmd\tgroups\n%s -- ask again\n" % NO_ANSWER
    expect("answered: a reply cut after line 1 (exit 1) fails", gr, cut, False, "answered", rc=1)
    expect("answered: the same lines with exit 0 pass", gr, cut, True, rc=0)
    expect("answered: a record that kept no exit code is judged as before", gr, cut, True)
    got = grade(gr, cut, SELF_SNAP, tree, builtins, 1)
    check(got[-1][0] == "answered" and [r[0] for r in got if not r[1]] == ["answered"]
          and "answered" not in [r[0] for r in grade(gr, cut, SELF_SNAP, tree, builtins)],
          "answered: the last rule, and absent when no exit code was kept")
    check(first_failed(gr, "error\nno model answers\n", 1) == "contract",
          "answered: an error's first failing rule is still contract")
    try:
        from spark import wire
        check(wire.THOUGHT_OUT.startswith(NO_ANSWER), "empty: the no-answer reason is the line's own (wire.THOUGHT_OUT)")
    except ImportError:
        pass

    # persona.KNOW_SHELL's two formats teach the tree the same words
    def learned(know):
        w, f, t = {}, set(), {}
        learn_slots([m for m in (KNOW_FORM.match(x) for x in know_forms(know)) if m], w, f, t, set())
        return w, f, t
    one_line, by_line = learned(KNOW_ONE_LINE), learned(KNOW_BY_LINE)
    check(know_forms(KNOW_ONE_LINE) == ["spark soul edit|reset", "spark memory add <words>", "spark serve on|off",
                                        "spark serve boot on|off", "spark client URL|off", "spark clear --history",
                                        "spark off|on|ver"],
          "the shell map on one line: the forms after the head's colon, `; `-joined, up to the tail",
          know_forms(KNOW_ONE_LINE))
    check(know_forms(KNOW_BY_LINE) == ["spark soul edit", "spark soul reset", "spark memory add WORDS", "spark serve",
                                       "spark serve on", "spark serve off", "spark serve boot on",
                                       "spark serve boot off", "spark client URL", "spark client off",
                                       "spark clear --history", "spark check"],
          "the shell map one command a line: the forms before the first ` -- `, split on `, `",
          know_forms(KNOW_BY_LINE))
    for name, (w, f, t) in (("one line", one_line), ("one command a line", by_line)):
        check(w.get("soul") == {"edit", "reset"} and w.get("serve") == {"on", "off", "boot"}
              and t.get(("serve", "boot")) == {"on", "off"} and f == {"client"} and w.get("client") == {"off"}
              and w.get("clear") == {"--history"} and "frobnicate" not in w and "ok" not in w,
              "the shell map, %s: first words, a free slot, third words; a description is never read" % name,
              (w, f, t))
    check(tree["third"].get(("serve", "boot")) == {"on", "off"} and "client" in tree["free"]
          and {"add", "forget", "clear"} <= tree["words"].get("memory", set()),
          "the tree reads this tree's own shell map, whichever format it is in")

    # the tree itself, read from completion: the facts the grader leans on
    ok = ("look" in tree["verbs"] and "quiet" not in tree["verbs"] and "shell" not in tree["verbs"]
          and "auto" in tree["words"].get("look", ()) and "motion" not in tree["words"].get("look", ()))
    print(("ok   " if ok else "FAIL ") + "the tree reads completion: look is a verb of on|off|auto, quiet and shell are not")
    if not ok:
        fails.append("tree")
    ok = bool(tree["models"]) and all(m in tree["words"].get("model", ()) for m in tree["models"])
    print(("ok   " if ok else "FAIL ") + "the tree fills model names from the model tables")
    if not ok:
        fails.append("models")

    # what a store indexes, read from a manual in both shapes (GNU and BSD)
    gnu = ("NAME\n       du - estimate file space usage\n\nSYNOPSIS\n       du [OPTION]... [FILE]...\n\n"
           "DESCRIPTION\n       Summarize device usage.\n\n       -s, --summarize\n"
           "              display only a total for each argument. More words.\n\n"
           "       -h, --human-readable\n              print sizes like 1K 234M 2G\n\n"
           "EXAMPLES\n       -x     never kept\n")
    bsd = ("NAME\n     ls - list directory contents\n\nSYNOPSIS\n     ls [-al] [file ...]\n\nDESCRIPTION\n"
           "     -a      Include directory entries whose names begin with a dot.\n"
           "     -l      List in long format.  More.\n\nCOMMANDS\n     list [-x] [label]\n"
           "              Lists the jobs.\n     A line of prose.  Not a command.\n")
    w, s, l = entry_text("", [gnu])
    check(w == "estimate file space usage" and s == ["du [OPTION]... [FILE]..."]
          and l == [["-s, --summarize", "display only a total for each argument."],
                    ["-h, --human-readable", "print sizes like 1K 234M 2G"]],
          "a GNU manual gives what, synopsis and option lines; EXAMPLES is never kept")
    w, s, l = entry_text("", [bsd])
    check(w == "list directory contents" and [x[0] for x in l] == ["-a", "-l", "list [-x] [label]"]
          and l[1][1] == "List in long format.", "a BSD manual gives its options and a COMMANDS word, not prose")
    w, s, l = entry_text("Usage: sv [-v] command service\n  -v   verbose\n", [])
    check(s == ["sv [-v] command service"] and l == [["-v", "verbose"]], "a --help text alone gives synopsis and lines")

    # SnapshotStore: a snapshot as intake.Store, saved and loaded back the same
    fake = {"os": "fake", "tools": {
        "du": dict(SELF_SNAP["tools"]["du"], man=True, what="estimate file space usage",
                   synopsis=["du [OPTION]... [FILE]..."], lines=[["-s, --summarize", "display only a total"]]),
        "xbps-query": dict(SELF_SNAP["tools"]["xbps-install"], help="Usage: xbps-query [OPTIONS] MODE\n"
                           " -f, --files PKG   Show package files for PKG\n"),
        "apt": {"exists": False}}}
    st = SnapshotStore(snap=fake, spark=False)
    e = st.entry("du")
    ix = st.index()
    check(st.names() == ["du", "xbps-query"] and st.entry("apt") is None, "SnapshotStore: an entry per tool that exists")
    check(e is not None and e.what == "estimate file space usage" and "--summarize" in e.options.long
          and e.lines[0][0] == "-s, --summarize" if _IN else e is not None,
          "SnapshotStore: an entry carries what, options and lines")
    check(st.entry("xbps-query").lines[0][0] == "-f, --files PKG" if _IN else True,
          "SnapshotStore: an older snapshot's entry reads its help text")
    check(set(ix) == {"v", "names", "post"} and ix["v"] == _IN.INDEX_V and ix["names"] == st.names()
          and all(re.match(r"^\d+:\d+(\.\d+)?( \d+:\d+(\.\d+)?)*$", p) for p in ix["post"].values()),
          "SnapshotStore: intake.index_of's shape, names sorted, postings i:tf")
    words, _how = tokenizer()
    du_terms = dict(x.split(":") for x in ix["post"].get(words("summarize")[0], "").split())
    check("0" in du_terms and "1" not in du_terms, "SnapshotStore: an option line's word is du's alone")
    name_tf = dict(x.split(":") for x in ix["post"].get(words("du")[0], "").split())
    check(float(name_tf.get("0", 0)) > float(du_terms.get("0", 0)) > 0,
          "SnapshotStore: a name weighs more than an option line's word")
    # commands: collect keeps what the manual lists (intake's own reader),
    # the store's entry carries them; an older snapshot's entry has none
    sv_man = ("NAME\n       sv - control services\n\nSYNOPSIS\n       sv [-v] [-w sec] command services\n\n"
              "COMMANDS\n       status Report the status.\n\n       up     Start it.\n\n       down   Stop it.\n")
    got = commands_text("sv", [sv_man], render=False)
    check((got["words"] == ["status", "up", "down"] and got["prefix"] is False and got["v"] == _IN.COMMANDS_V
           and isinstance(got["seen"], list)) if _IN else got is None,
          "collect: a manual's command list is kept, read by intake's own command_set, in the store's own shape")
    cs = SnapshotStore(snap={"os": "fake", "tools": {
        "sv": {"exists": True, "man": True, "what": "x", "synopsis": ["sv command"], "lines": [], "commands": got},
        "du": dict(fake["tools"]["du"])}}, spark=False)
    old = SnapshotStore(snap={"os": "fake", "tools": {
        "sv": {"exists": True, "man": True, "what": "x", "synopsis": ["sv command"], "lines": [],
               "commands": {"words": ["status", "up", "down"], "prefix": False}}}}, spark=False)
    check(_IN is None or (cs.entry("sv").commands == got and _IN.commands_of(cs.entry("sv").commands).words
                          == ("status", "up", "down") and not cs.entry("du").commands
                          and _IN.commands_of(old.entry("sv").commands) == ()),
          "SnapshotStore: an entry carries the commands its snapshot kept, none when it kept none, "
          "and a list from before v1.87 closes nothing")
    tmp = tempfile.mkdtemp(prefix="line-audition-self-")
    try:
        saved = st.save(os.path.join(tmp, "store.json"))
        back = SnapshotStore(saved)
        check(back.names() == st.names() and back.index() == ix and back.entry("du") == st.entry("du")
              and back.absent == st.absent == ["apt"],
              "SnapshotStore: save and load give the same store")
        # the saved store is closed: the line's own reader (grounding)
        # answers "not there" for a tool it lacks or names absent, so the
        # judge finds it not installed, as on a real machine
        with open(saved, encoding="utf-8") as f:
            doc = json.load(f)
        check(doc.get("closed") is True and doc.get("absent") == ["apt"] and st.has_program("du")
              and not st.has_program("apt") and not st.has_program("pandoc"),
              "SnapshotStore: the saved store says it is closed and names the absent tools")
        try:
            from spark import grounding, judge
        except ImportError:
            grounding = judge = None
        if grounding and hasattr(grounding, "_SnapshotFile"):
            gs = grounding._SnapshotFile(saved)
            check(gs.has_program("du") is True and gs.has_program("apt") is False
                  and gs.has_program("pandoc") is False,
                  "a closed store: a tool it holds is there, one it marks absent or lacks is not",
                  (gs.has_program("du"), gs.has_program("apt"), gs.has_program("pandoc")))
            found = [tuple(x) for x in judge.verdict("pandoc notes.md -o notes.pdf", gs).findings]
            check(found == [("missing", "pandoc", "pandoc")] and judge.verdict("du -s notes.md", gs).ok,
                  "a closed store: the line's judge finds pandoc not installed, and du there", found)
            del doc["closed"]
            flagless = os.path.join(tmp, "flagless.json")
            with open(flagless, "w", encoding="utf-8") as f:
                json.dump(doc, f)
            go = grounding._SnapshotFile(flagless)
            check(go.has_program("du") is True and go.has_program("pandoc") is None,
                  "a store without the flag: a tool it does not hold is unknown, as before")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # the run's PATH: one directory of stubs -- the snapshot's tools, no
    # tool of this machine -- and python still starts with it. Offline:
    # the prompt is built, no model is asked
    data = load_cases()
    here = "macos" if sys.platform == "darwin" else "void"
    pm = data["oses"][here]["pm"]
    psnap = {"os": here, "tools": {"rg": {"exists": True}, "git": {"exists": True}, "ls": {"exists": True},
                                   pm: {"exists": True}, "fd": {"exists": False}, "micro": {"exists": False}}}
    tmp = tempfile.mkdtemp(prefix="line-audition-self-")
    try:
        env = persona_env(here, psnap, data, tmp, "")
        stubs = env["PATH"]
        check(os.path.isabs(stubs) and os.pathsep not in stubs
              and sorted(os.listdir(stubs)) == sorted(["rg", "git", "ls", pm]),
              "run: PATH is one directory, a stub for every tool the snapshot has (one this machine has too) "
              "and none it lacks", stubs)
        ok, prefix, why = check_prefix(here, data, env, psnap)
        check(ok and preferred_named(prefix) == ["rg", "git"] and "Package manager: %s." % pm in prefix,
              "run: python starts with that PATH, and the prompt prefers the snapshot's tools alone",
              why or preferred_named(prefix))
        leaked = os.path.join(tmp, "leaked")
        os.makedirs(leaked)
        shutil.copy(os.path.join(stubs, "rg"), os.path.join(leaked, "fzf"))
        ok, _prefix, why = check_prefix(here, data, dict(env, PATH=stubs + os.pathsep + leaked), psnap)
        check(not ok and "fzf" in why, "run: a tool of this machine on the run's PATH is refused before any case", why)
        ok, _prefix, why = check_prefix(here, data, env, dict(psnap, tools=dict(psnap["tools"], fd={"exists": True})))
        check(not ok and "fd" in why, "run: a preferred tool the snapshot has and the prompt lacks is refused too", why)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # recall on a tiny fixture, with a reference BM25 (grounding's is the
    # real one; this proves recall's own counting)
    def bm25(q, k=3, store=None):
        ix, scores = store.index(), {}
        n = len(ix["names"])
        for t in set(words(q)):
            posts = ix["post"].get(t, "").split()
            idf = math.log(1 + (n - len(posts) + 0.5) / (len(posts) + 0.5))
            for p in posts:
                i, tf = int(p.split(":")[0]), float(p.split(":")[1])
                scores[i] = scores.get(i, 0) + idf * tf * 3.0 / (tf + 2.0)
        return [(ix["names"][i], s) for i, s in sorted(scores.items(), key=lambda x: -x[1])[:k]]
    todo = [("tools", {"id": "a", "words": "show package files", "head_any": ["xbps-query"], "topic": "packages"}),
            ("tools", {"id": "b", "words": "total space of a folder", "head_any": ["du"], "topic": "disks"}),
            ("tools", {"id": "c", "words": "restart nginx", "head_any": ["sv"], "topic": "services"})]
    rows = recall_run(todo, st, bm25, 1)
    check([r[2] for r in rows] == [True, True, False], "recall: a head among the top k is a hit, else a miss")
    text = "\n".join(recall_lines("fake", rows, 1))
    check("2/3" in text and "services" in text and "miss c" in text, "recall: per topic, and each miss named")
    check(recall_targets({"spark_verb": ["look"], "head_any": ["spark"]}) == ["spark look"],
          "recall: a spark core case wants spark's own verb entry")

    # the report's measures on canned results
    snaps = {"fake": SELF_SNAP}
    by = {"d1": {"danger": True}, "d2": {"danger": True}, "n1": {"danger": False}, "n2": {"danger": None},
          "f1": {"danger": False}, "f2": {"danger": False}}
    sel = [("fake", {"id": "d1", "raw": ["danger\trm -f -- x.tmp", "deletes"], "reasked": 0, "cmd_ms": 1000,
                     "total_ms": 1500, "evidence_chars": 300}),
           ("fake", {"id": "d2", "raw": ["cmd\trm -f -- y.tmp", "deletes"], "reasked": 1, "cmd_ms": 3000,
                     "total_ms": 4000, "evidence_chars": 500}),
           ("fake", {"id": "n1", "raw": ["danger\tls -la", "lists"], "cmd_ms": 2000, "total_ms": 2500}),
           ("fake", {"id": "n2", "raw": ["cmd\tls -la", "lists"], "total_ms": 900}),
           ("fake", {"id": "f1", "raw": ["cmd\tls --frobnicate", "the ls manual has no --frobnicate"]}),
           ("fake", {"id": "f2", "raw": ["cmd\tdu -sh * | sort --humanize", "sizes"]})]
    m = measures(sel, by, snaps, builtins)
    check(m["danger"] == (1, 2) and m["over"] == (1, 4), "report: danger recall 1/2, over-fire 1 of 4 non-danger")
    check(m["honest"] == (5, 6), "report: flag honesty -- a flag the hint names is honest, one it hides is not")
    check(m["reask"] == (1, 2) and m["evidence"] == 400, "report: re-ask share and evidence characters when the turn has them")
    check(_median(m["cmd"]) == 2000 and _p90(m["cmd"]) == 3000 and _ms(m["total"]) == "2000/4000",
          "report: median and p90 of total and command-ready ms")
    docs = [{"os": "fake", "model": "m", "arm": "judge", "cases": [dict(r, subject="tools", rules=[], **{"pass": None})
                                                                  for _o, r in sel]}]
    cdata = {"cases": {"fake": [dict(v, id=k, words="w") for k, v in by.items()]}}
    text = "\n".join(report_lines(docs, tree, builtins, cdata, snaps))
    check("model m, arm judge" in text and "danger recall" in text and "bar: not met" in text
          and "danger recall 1/2" in text and "flag honesty 5/6" in text,
          "report: a block per model and arm, the measures, and the bar it misses")
    # empty and leak, from the kept lines and exit codes alone
    by2 = dict(by, s1={"danger": None, "spark_verb": ["check"]})
    sel2 = [("fake", {"id": "n1", "raw": ["cmd\tgroups", NO_ANSWER + " -- ask again"], "rc": 1}),
            ("fake", {"id": "n1", "raw": ["error", NO_ANSWER + " -- ask again"], "rc": 1}),
            ("fake", {"id": "n1", "raw": ["error", "no answer from SPARK_BASE_URL http://127.0.0.1:9"], "rc": 1}),
            ("fake", {"id": "n2", "raw": ["cmd\tspark check", "checks"], "rc": 0}),
            ("fake", {"id": "n2", "raw": ["cmd\tls -la | grep spark", "lists"], "rc": 0}),
            ("fake", {"id": "s1", "raw": ["cmd\tspark check", "checks"], "rc": 0})]
    m2 = measures(sel2, by2, snaps, builtins)
    check(m2["empty"] == (2, 6), "report: empty -- an error with the no-answer reason, and a reply cut after line 1",
          m2["empty"])
    check(m2["leak"] == (1, 5), "report: leak -- a tools case answered with a spark command; a spark case is none",
          m2["leak"])
    # the held-out cases: a line of their own, and --split
    hcase = {"words": "w", "kind": None, "head_any": ["spark"], "spark_verb": ["check"], "danger": None}
    hdata = {"cases": {"spark": [dict(hcase, id="h1", split="held"), dict(hcase, id="h2", split="held"),
                                 dict(hcase, id="d1")],
                       "fake": [dict(by["n2"], id="n2", words="w", head_any=["ls"])]}}

    def hdocs():
        rows = [("h1", "spark", "spark check"), ("h2", "spark", "spark serve"), ("d1", "spark", "spark check"),
                ("n2", "tools", "ls -la")]
        return [{"os": "fake", "model": "m", "arm": "judge",
                 "cases": [{"id": i, "subject": s, "raw": ["cmd\t" + c, "hint"], "rc": 0, "rules": [], "pass": None}
                           for i, s, c in rows]}]
    text = "\n".join(report_lines(hdocs(), tree, builtins, hdata, snaps))
    held_line = [l for l in text.split("\n") if l.startswith("  held ")]
    first_line = [l for l in text.split("\n") if l.startswith("  first ")]
    check(len(held_line) == 1 and "1/2" in held_line[0] and len(first_line) == 1 and "1/1" in first_line[0]
          and "empty" in text and "leak" in text,
          "report: the held-out cases' score on a line of its own, the first report's cases on another", text)
    mdata = dict(hdata, cases=dict(hdata["cases"], spark=hdata["cases"]["spark"] + [dict(hcase, id="m1", split="more")]))
    mdoc = hdocs()
    mdoc[0]["cases"].append({"id": "m1", "subject": "spark", "raw": ["cmd\tspark serve", "hint"], "rc": 0,
                             "rules": [], "pass": None})
    mtext = "\n".join(report_lines(mdoc, tree, builtins, mdata, snaps))
    more_line = [l for l in mtext.split("\n") if l.startswith("  more ")]
    check(len(more_line) == 1 and "0/1" in more_line[0] and "bar: met" in mtext
          and split_of({"split": "more"}) == "more" and split_of({}) == "dev" and split_of({"split": "x"}) == "dev",
          "report: a second phrasing (split more) is a line of its own, and the bar reads the first report's cases",
          mtext)
    dev_text = "\n".join(report_lines(hdocs(), tree, builtins, hdata, snaps, "dev"))
    held_text = "\n".join(report_lines(hdocs(), tree, builtins, hdata, snaps, "held"))
    check("\n  held " not in dev_text and "h2 " not in dev_text and "1/1 100 %" in dev_text
          and "h2 " in held_text and "d1 " not in held_text,
          "report --split: dev leaves the held-out cases out, held keeps them alone", dev_text)
    todo = [c["id"] for _s, c in cases_for(hdata, "fake")]
    check(todo == ["n2", "h1", "h2", "d1"] and [c["id"] for _s, c in cases_for(hdata, "fake", split="dev")] == ["n2", "d1"]
          and [c["id"] for _s, c in cases_for(hdata, "fake", split="held")] == ["h1", "h2"],
          "run --split: all runs every case, dev leaves the held-out ones out, held runs them alone")
    check(shown_of("cmd\tls -la\nlists\n") == "`ls -la` -- lists" and shown_of("answer\nruns it\n") == "runs it",
          "a pair's first turn rides as the thread keeps it")

    # every case in cases.json is well formed: a new case cannot break a run
    data = load_cases()
    ids = [c["id"] for k in data["cases"] for c in data["cases"][k]]
    bad = [c.get("id", "?") for k in data["cases"] for c in data["cases"][k]
           if set(c) - CASE_KEYS or not c.get("words") or c.get("kind") not in ("cmd", "answer", None)
           or not (c.get("head_any") or c.get("answer_any") or c.get("spark_verb"))
           or "then" in c and not (isinstance(c["then"], str) and c["then"].strip())
           or c.get("split") not in (None, "held", "more")
           or not all(isinstance(c.get(key, []), list) and all(isinstance(p, str) and p for p in c.get(key, []))
                      for key in ("must_not", "not_head", "must", "answer_any"))]
    bad += [i for i in set(ids) if ids.count(i) > 1]
    for k in data["cases"]:
        for c in data["cases"][k]:
            for key in ("must_not", "not_head", "must", "answer_any"):
                for p in c.get(key, []):
                    try:
                        re.compile(p)
                    except (re.error, TypeError):
                        bad.append(c["id"])
            # a case never forbids a head it accepts
            bad += [c["id"] for n in c.get("not_head", []) for h in c.get("head_any", [])
                    if isinstance(n, str) and re.fullmatch(n, h)]
            if k == "spark":
                bad += [c["id"] for v in c.get("spark_verb", ()) if v not in tree["verbs"]]
    ok = not bad and set(data["cases"]) == set(OSES) | {"spark"}
    print(("ok   " if ok else "FAIL ") + "cases.json: %d cases, each well formed%s"
          % (len(ids), "" if ok else " (%s)" % ", ".join(sorted(set(bad)))))
    if not ok:
        fails.append("cases")
    # the held-out questions are frozen: their ids and words, by hash
    held = [c for k in data["cases"] for c in data["cases"][k] if is_held(c)]
    check(held_sha(data) == (HELD_N, HELD_SHA) and held == [c for c in data["cases"]["spark"] if is_held(c)]
          and [c["id"] for c in held] == ["held-%02d" % n for n in range(1, HELD_N + 1)],
          "cases.json: the %d held-out questions are the frozen ones, word for word" % HELD_N, held_sha(data))
    # a case about a tool that is not installed: the answer must hold the
    # install command, and the OS's snapshot must not have the tool
    miss = [(k, c) for k in data["cases"] for c in data["cases"][k] if c.get("topic") == "missing"]
    wrong = []
    for k, c in miss:
        tool = c["words"].split()[-1]
        snap = load_snapshot(k) or {}
        if (len(c.get("must", [])) < 2 or not re.search(c["must"][0], tool)
                or snap.get("tools", {}).get(tool, {}).get("exists")):
            wrong.append(c["id"])
    check(len(miss) == len(OSES) and not wrong,
          "cases.json: a missing tool's case demands its install command, and no snapshot has the tool",
          wrong)
    # what the next snapshot asks about: a run's PATH and its closed store
    # hold only what a snapshot found
    asks = dict((o, set(tools_for(data, o))) for o in OSES)
    check(all({"nc", "pandoc", "asciinema", "nmap", "pwd", "time", "command"} <= asks[o] for o in OSES)
          and all("nc" in data["oses"][o]["also"] for o in OSES),
          "collect: every OS's next snapshot asks about nc, the three missing tools and the shell's own words "
          "that are programs too (pwd)")
    # the judge's precision, on every OS's snapshot: no command the grader
    # accepted is asked again about, and the wrong ones are still caught
    if _IN and os.path.exists(ACCEPTED):
        wrong = []
        for o in OSES:
            refused, missed, _n = precision(o)
            wrong += ["%s: refused %s %s" % (o, c, f) for c, f in refused]
            wrong += ["%s: missed %s (%s)" % (o, c, k) for c, k, _got in missed]
        check(not wrong, "precision: the judge refuses no accepted command on any OS, and still catches the wrong ones",
              "; ".join(wrong)[:600])
    print("%s: %d failed" % ("line_audition selftest", len(fails)) if fails else "line_audition selftest: all ok")
    return 1 if fails else 0


ACCEPTED = os.path.join(DATA, "accepted.json")


def precision(os_name, snap=None):
    """The judge's precision on one OS: (refused, missed, n).

    `refused` lists (command, findings) for every command of
    accepted.json -- that OS's and spark's own -- the line's judge would
    ask again about, over that OS's closed snapshot store; a finding of
    kind `slot` never asks again, so it is no refusal. `missed` lists the
    must_find commands that got no finding of the kind named. Both empty
    is the pass. No model: the judge and the snapshot alone."""
    from spark import grounding, judge
    with open(ACCEPTED, encoding="utf-8") as f:
        doc = json.load(f)
    st = SnapshotStore(snap=snap or load_snapshot(os_name))
    tmp = tempfile.mkdtemp(prefix="line-audition-precision-")
    try:
        gs = grounding._SnapshotFile(st.save(os.path.join(tmp, "store.json")))
        refused, missed, n = [], [], 0
        for key in (os_name, "spark"):
            for cmd in doc["accepted"].get(key, ()):
                n += 1
                found = [tuple(x) for x in judge.verdict(cmd, gs).findings if x.kind != "slot"]
                if found:
                    refused.append((cmd, found))
            for cmd, kind in doc["must_find"].get(key, ()):
                n += 1
                kinds = [x.kind for x in judge.verdict(cmd, gs).findings]
                if kind not in kinds:
                    missed.append((cmd, kind, kinds))
        return refused, missed, n
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cmd_precision(args):
    """precision [--os OS|all] [-v]: the judge against the commands the
    grader accepted, and against the wrong ones it must still catch."""
    rest = [a for a in args if a != "-v"]
    opts = dict(zip(rest[::2], rest[1::2]))
    which = opts.get("--os", "all")
    names = OSES if which == "all" else (which,)
    if len(rest) % 2 or any(o not in OSES for o in names):
        die("precision takes [--os OS|all] [-v]")
    bad = 0
    for o in names:
        refused, missed, n = precision(o)
        bad += len(refused) + len(missed)
        print("%-9s %3d commands  refused %d  missed %d" % (o, n, len(refused), len(missed)))
        for cmd, found in refused:
            print("  refused  %s   %s" % (cmd, found))
        for cmd, kind, kinds in missed:
            print("  missed   %s   wanted %s, got %s" % (cmd, kind, kinds or "nothing"))
    print("line_audition precision: %s" % ("all ok" if not bad else "%d wrong" % bad))
    return 1 if bad else 0


COMMANDS = {"run": cmd_run, "collect": cmd_collect, "report": cmd_report, "packages": cmd_packages,
            "recall": cmd_recall, "serve-candidate": cmd_serve_candidate, "selftest": cmd_selftest,
            "precision": cmd_precision}


def main(argv):
    if not argv or argv[0] not in COMMANDS:
        # the usage is the header comment, so the two never drift
        head = []
        for line in open(__file__, encoding="utf-8").read().split("\n")[1:]:
            if not line.startswith("#"):
                break
            head.append(line[2:] if line.startswith("# ") else line[1:])
        print("\n".join(head))
        return 2
    return COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
