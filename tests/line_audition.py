#!/usr/bin/env python3
# line_audition.py -- the prompt line, judged by outcomes. Plain words a
# person types after `? ` go through the real `spark line` (contract 4)
# for four OSes (debian, arch, void, macos) and for spark itself, and a
# mechanical grader decides each answer: line 1 is contract 4's shape,
# the head command exists on that OS, every option it passes appears in
# that OS's own help, the case's must-nots hold, and danger is right.
# Nothing here trusts the generation: the OS facts are help snapshots
# gathered ON that OS (collect), and spark's verbs come from the tree's
# own TAB completion, so a retired verb fails with no list to keep.
#
#   python3 tests/line_audition.py run --os void --model NAME [--url URL]
#                                      [--out FILE] [--subject tools|spark]
#                                      [--case ID] [-v]
#   python3 tests/line_audition.py collect [--os OS] --out help-OS.json
#   python3 tests/line_audition.py report FILE...
#   python3 tests/line_audition.py serve-candidate --model-file PATH [--port 8090]
#   python3 tests/line_audition.py packages --os OS
#   python3 tests/line_audition.py selftest
#
# Not part of the gate: `run` needs a live model. `selftest` needs none
# and is fast. The help snapshots are data: nothing in them is run.
# The OS a run speaks as comes from spark's own seams (SPARK_OS_RELEASE,
# SPARK_ETC_RUNIT, SPARK_PROC_VERSION) plus stub commands on PATH, so the
# box can speak as debian or arch. macOS speaks only on a Mac: the prompt
# reads platform.system() there, which has no seam.

import json
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

OSES = ("debian", "arch", "void", "macos")
SUBJECTS = ("tools", "spark")
HELP_MAX = 4096          # the human-readable part of a snapshot entry
MAN_MAX = 200000         # a man page read for options (git's is ~150 kB)

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
EXTRA_BUILTINS = ("command", "time", "builtin", "pwd", "history", "ulimit", "hash", "[[")
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


def cases_for(data, os_name, subject=None, only=None):
    """[(subject, case)] for one OS: its own tools, then spark core."""
    out = []
    for subj, key in (("tools", os_name), ("spark", "spark")):
        if subject and subject != subj:
            continue
        for c in data["cases"].get(key, ()):
            if only and c["id"] not in only:
                continue
            out.append((subj, c))
    return out


def this_os():
    """The OS this machine is, in the audition's four names, or ""."""
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
    man synopsis) for a person to read, and the options its --help and
    man page name, for the grader. --help is run only for tools outside
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
    return entry


def tools_for(data, os_name):
    """Every command a snapshot for os_name must describe: the heads its
    cases accept, its `also` list, COMMON, the wrappers, and persona's
    PREFERRED (the prompt names them when installed)."""
    names = set(COMMON) | set(WRAPPERS)
    for c in data["cases"].get(os_name, ()):
        names.update(h for h in c.get("head_any", ()) if h != "spark")
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
    dynamic slots (themes/, the model tables). persona.KNOW_SHELL and
    KNOW_CHAT add the slots completion cannot list: an upper-case slot
    (FACE, URL, WORDS) takes any word, unless completion fills that slot
    from the tree (a model, a palette), which keeps it closed."""
    cdir = os.path.join(repo, "home", ".config", "spark")
    bash = open(os.path.join(cdir, "completion.bash"), encoding="utf-8").read()
    zsh = open(os.path.join(cdir, "completion.zsh"), encoding="utf-8").read()
    themes = sorted(n[:-4] for n in os.listdir(os.path.join(repo, "themes")) if n.endswith(".env"))
    try:
        from spark import config
        models = sorted(r[0] for r in config.model_tables(repo))
    except Exception:          # a tree whose models.env will not parse still has verbs
        models = []

    def fill(words):
        dynamic = "_spark_theme_names" in words or "_spark_model_names" in words
        words = re.sub(r"\$\{\(f\)\"\$\(_spark_theme_names\)\"\}|\$\(_spark_theme_names\)", " ".join(themes), words)
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
    free, third = set(), {}
    try:
        from spark import persona
        know = persona.KNOW_SHELL + "\n" + persona.KNOW_CHAT
    except ImportError:
        know = ""
    for m in re.finditer(r"\bspark ([a-z][\w|]*)((?: [\[\]\w|.-]+)*)", know):
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
    verbs.add("help")
    return {"verbs": verbs, "words": words, "free": free, "third": third, "themes": themes, "models": models}


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
def split_stages(command):
    """The command's stages as [[word, ...], ...], split on | || && ; &
    and parentheses; a redirection and its target are dropped. Raises
    ValueError on a bad quote (shlex's own)."""
    lex = shlex.shlex(command, posix=True, punctuation_chars=True)
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
            cur.append(tok)
    if cur:
        stages.append(cur)
    return stages


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
    if head.startswith(("./", "~/", "../")) or head in builtins or base in builtins:
        return True, True, ""
    entry = snap.get("tools", {}).get(base)
    if not entry or not entry.get("exists"):
        return False, True, "%s: not on %s" % (base, snap.get("os", "?"))
    bad, prev = [], ""
    for tok in args:
        if tok == "--" or tok in FIND_EXEC:
            break                              # the rest is another command's words
        if tok.startswith("-") and tok != "-" and not option_ok(tok, prev, base, entry):
            bad.append(tok)
        prev = tok
    if bad:
        return True, False, "%s: %s not in its help" % (base, " ".join(bad))
    return True, True, ""


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


def grade(case, stdout, snap, tree, builtins):
    """[(rule, ok, detail)] for one answer. Every rule is mechanical."""
    kind, command, text, _proof = parse_reply(stdout)
    rules = []
    shape = kind in ("cmd", "danger") and bool(command.strip()) or kind == "answer" and bool(text.strip())
    rules.append(("contract", shape, "" if shape else "line 1 %r: %s" % (stdout.split("\n")[0][:40], text[:60])))
    if not shape:
        return rules
    want = case.get("kind")
    got = "answer" if kind == "answer" else "cmd"
    rules.append(("kind", want in (None, got), "" if want in (None, got) else "wanted %s, got %s" % (want, got)))
    judged = command if got == "cmd" else text
    hits = [p for p in case.get("must_not", ()) if re.search(p, judged)]
    rules.append(("must_not", not hits, "matches %s" % " ".join(hits) if hits else ""))
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
    try:
        stages = split_stages(command)
    except ValueError as e:
        rules.append(("parse", False, str(e)))
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


# ------------------------------------------------------------ run
def persona_env(os_name, snap, data, scratch, url):
    """The environment one `spark line` runs in to speak as os_name: the
    seams spark already reads, and a stub on PATH for every tool the
    snapshot says that OS has and this machine lacks (so the prompt's
    package manager is that OS's, and the head-word guard does not
    re-ask for a tool the OS would have). The stubs are never run."""
    env = dict(os.environ)
    env["SPARK_LINE_BENCH"] = "1"          # the turn's numbers, marked bench; no thread
    for k in ("SPARK_EXPLAIN_CMD", "SPARK_EXPLAIN_RC", "SPARK_HINT_ROW", "SPARK_DEBUG"):
        env.pop(k, None)
    stubs = os.path.join(scratch, "bin")
    os.makedirs(stubs, exist_ok=True)
    have = [t for t, e in (snap or {}).get("tools", {}).items() if e.get("exists")]
    if not have:
        have = [h for c in data["cases"].get(os_name, ()) for h in c.get("head_any", ())]
    have.append(data["oses"][os_name].get("pm", ""))
    for tool in sorted(set(t for t in have if t and "/" not in t)):
        if shutil.which(tool):
            continue
        p = os.path.join(stubs, tool)
        with open(p, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\necho 'line_audition: a stub, never run' >&2\nexit 127\n")
        os.chmod(p, 0o755)
    env["PATH"] = stubs + os.pathsep + env.get("PATH", "")
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


def check_prefix(os_name, data, env):
    """The prompt spark will send, checked before any case: it must name
    this OS's package manager and init. Returns (ok, prefix, why)."""
    p = subprocess.run([sys.executable, "-c", PREFIX_PROBE, LIB], env=env, capture_output=True, text=True)
    prefix = p.stdout
    o = data["oses"][os_name]
    want = []
    if o.get("pm") and shutil.which(o["pm"], path=env["PATH"]):
        want.append("Package manager: %s." % o["pm"])
    want.append("System tools: " + {"runit": "sv,", "systemd": "systemctl", "launchd": "launchctl"}[o["init"]])
    miss = [w for w in want if w not in prefix]
    return not miss, prefix, ("the prompt lacks %r" % miss[0]) if miss else ""


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


def cmd_run(args):
    os_name, model, url, out, subject, only, verbose, snap_path = "", "", "", "", None, set(), False, None
    it = iter(args)
    for a in it:
        if a == "--os":
            os_name = next(it, "")
        elif a == "--model":
            model = next(it, "")
        elif a == "--url":
            url = next(it, "").rstrip("/")
        elif a == "--out":
            out = next(it, "")
        elif a == "--subject":
            subject = next(it, "")
        elif a == "--case":
            only.add(next(it, ""))
        elif a == "--snapshot":
            snap_path = next(it, "")
        elif a == "-v":
            verbose = True
        else:
            die("run takes --os OS --model NAME [--url URL] [--out FILE] [--subject tools|spark] [--case ID] [-v]")
    if os_name not in OSES or not model:
        die("run: say --os (one of %s) and --model NAME (the label the report groups by)" % ", ".join(OSES))
    if subject and subject not in SUBJECTS:
        die("run: --subject is tools or spark")
    here_mac = sys.platform == "darwin"
    if (os_name == "macos") != here_mac:
        # persona.prefix reads platform.system() for macOS, with no seam
        die("run: %s cases run on %s" % (os_name, "a Mac" if os_name == "macos" else "Linux (any family)"))
    data = load_cases()
    snap = load_snapshot(os_name, snap_path)
    if snap is None:
        print("line_audition: no help-%s.json yet -- answers are kept, graded by `report` once it exists" % os_name)
    tree, builtins = spark_tree(), builtins_set()
    scratch = tempfile.mkdtemp(prefix="line-audition-")
    try:
        env = persona_env(os_name, snap, data, scratch, url)
        ok, prefix, why = check_prefix(os_name, data, env)
        if not ok:
            die("run: cannot speak as %s here: %s" % (os_name, why))
        cwd = os.path.join(scratch, "cwd")
        os.makedirs(cwd)
        results = []
        todo = cases_for(data, os_name, subject, only)
        for n, (subj, case) in enumerate(todo, 1):
            before = turn_sizes()
            t0 = time.time()
            try:
                p = subprocess.run([sys.executable, SPARK, "line", "--cwd", cwd, "--shell", "bash"],
                                   input="? " + case["words"] + "\n", capture_output=True, text=True,
                                   env=env, timeout=300, cwd=cwd)
                rc, stdout, stderr = p.returncode, p.stdout, p.stderr
            except subprocess.TimeoutExpired:
                rc, stdout, stderr = -1, "error\ntimed out after 300 s\n", ""
            total = int((time.time() - t0) * 1000)
            rec = newest_turn(before)
            prompt_ms, first_ms, tok = timing(rec)
            rules = grade(case, stdout, snap, tree, builtins) if snap else []
            passed = bool(rules) and all(r[1] for r in rules)
            results.append({"id": case["id"], "subject": subj, "words": case["words"], "rc": rc,
                            "raw": stdout.split("\n")[:3], "stderr": stderr[-400:],
                            "rules": rules, "pass": passed if snap else None, "total_ms": total,
                            "prompt_ms": prompt_ms, "first_token_ms": first_ms, "tokens_out": tok,
                            "cache_n": rec.get("cache_n"), "turn_model": rec.get("model")})
            mark = "?" if not snap else ("ok" if passed else "FAIL")
            fails = ", ".join("%s (%s)" % (r[0], r[2]) if r[2] else r[0] for r in rules if not r[1])
            print("%3d/%d %-4s %-14s %6d ms  %s" % (n, len(todo), mark, case["id"], total, fails[:60]))
            if verbose:
                print("        " + " | ".join(stdout.split("\n")[:3]))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    import hashlib
    doc = {"tool": "line_audition", "version": 1, "os": os_name, "model": model, "url": url,
           "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "brief": brief_sha(),
           "prefix_sha": hashlib.sha256(prefix.encode()).hexdigest()[:12],
           "prefix_facts": [l for l in prefix.splitlines() if l.startswith(("Package manager", "System tools"))],
           "snapshot": (snap or {}).get("collected"), "cases": results}
    if not out:
        from spark import STATE_DIR
        d = os.path.join(STATE_DIR, "line_audition")
        os.makedirs(d, exist_ok=True)
        out = os.path.join(d, "%s-%s-%s.json" % (time.strftime("%Y%m%d-%H%M%S"), os_name, re.sub(r"[^\w.-]", "_", model)))
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print("written to %s -- python3 tests/line_audition.py report %s" % (out, out))
    return 0


# ------------------------------------------------------------ report
def _median(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return int(statistics.median(xs)) if xs else None


def cmd_report(args):
    """One table per model: pass rate per OS x subject, the median total
    ms and tokens out; then every failed case on one line. Each answer is
    re-graded against today's snapshot and tree when the snapshot is
    here, so a refreshed snapshot re-judges an old run."""
    if not args:
        die("report takes one or more results files")
    tree, builtins, data = spark_tree(), builtins_set(), load_cases()
    by_id = dict((c["id"], c) for k in data["cases"] for c in data["cases"][k])
    runs = {}
    for path in args:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        snap = load_snapshot(doc["os"])
        for r in doc["cases"]:
            case = by_id.get(r["id"])
            if snap and case:
                r["rules"] = grade(case, "\n".join(r["raw"]), snap, tree, builtins)
                r["pass"] = all(x[1] for x in r["rules"])
            runs.setdefault(doc["model"], []).append((doc["os"], r))
    for model in sorted(runs):
        rows = runs[model]
        print("model %s" % model)
        print("  %-8s %-16s %-16s %10s %9s" % ("os", "tools", "spark core", "median ms", "tok out"))
        for os_name in OSES + ("all",):
            sel = [r for o, r in rows if os_name in ("all", o)]
            if not sel:
                continue
            cells = []
            for subj in SUBJECTS:
                s = [r for r in sel if r["subject"] == subj and r["pass"] is not None]
                p = sum(1 for r in s if r["pass"])
                cells.append("%d/%d %3d %%" % (p, len(s), 100 * p // len(s)) if s else "-")
            ms = _median(r["total_ms"] for r in sel)
            tok = _median(r.get("tokens_out") for r in sel)
            print("  %-8s %-16s %-16s %10s %9s" % (os_name, cells[0], cells[1],
                                                 "-" if ms is None else ms, "-" if tok is None else tok))
        failed = [(o, r) for o, r in rows if r["pass"] is False]
        if failed:
            print("  failed:")
        for o, r in failed:
            rule = next((x for x in r["rules"] if not x[1]), ["?", False, ""])
            what = r["raw"][0].replace("\t", " ") if r["raw"] else ""
            line = "  %-14s %-10s %s" % (r["id"], rule[0], what)
            print(line[:100])
        print("")
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
    print("serving %s at %s (Ctrl-C stops it)" % (os.path.basename(path), url))
    print("then: python3 tests/line_audition.py run --os OS --model %s --url %s"
          % (engine.model_stem(path), url))
    p = subprocess.Popen(argv, env=engine.server_env(cfg), stdin=subprocess.DEVNULL)
    try:
        return p.wait()
    except KeyboardInterrupt:
        p.terminate()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
        return 0


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
        "apt": {"exists": False},
    },
}


def cmd_selftest(_args):
    """Canned answers against SELF_SNAP and the real tree: a right answer
    passes, and each way to be wrong fails on the rule that names it."""
    tree, builtins = spark_tree(), builtins_set()
    fails = []

    def expect(what, case, stdout, want_pass, rule=None):
        rules = grade(case, stdout, SELF_SNAP, tree, builtins)
        passed = all(r[1] for r in rules)
        bad = [r[0] for r in rules if not r[1]]
        ok = passed == want_pass and (rule is None or rule in bad)
        print(("ok   " if ok else "FAIL ") + what + ("" if ok else "  -- rules: %r" % rules))
        if not ok:
            fails.append(what)

    ls = {"id": "t", "words": "list with sizes", "kind": "cmd", "head_any": ["ls"], "danger": False,
          "must_not": [r"\bsudo\b"]}
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
    sp = {"id": "t", "words": "quiet boot", "kind": None, "head_any": ["spark"], "spark_verb": ["quiet"], "danger": None}
    expect("a real spark verb and word pass", sp, "cmd\tspark quiet boot on\nquiets\n", True)
    expect("a retired spark verb fails (spark shell on)", sp, "cmd\tspark shell on\nshell\n", False, "spark tree")
    expect("a word the verb does not take fails", sp, "cmd\tspark quiet loud on\nquiets\n", False, "spark tree")
    expect("a third word outside on|off fails", sp, "cmd\tspark quiet boot enable\nquiets\n", False, "spark tree")
    expect("an answer naming the verb in words passes", sp, "answer\nRun `spark quiet boot on` and reboot.\n", True)
    expect("an answer naming a retired verb fails", sp, "answer\nRun spark shell on, then reboot.\n", False, "spark tree")
    th = {"id": "t", "words": "dracula", "kind": "cmd", "head_any": ["spark"], "spark_verb": ["theme"], "danger": None}
    expect("a palette from themes/ passes", th, "cmd\tspark theme dracula\npalette\n", True)
    expect("a palette not in themes/ fails", th, "cmd\tspark theme hotdogstand\npalette\n", False, "spark tree")
    fo = {"id": "t", "words": "font", "kind": "cmd", "head_any": ["spark"], "spark_verb": ["font"], "danger": None}
    expect("a free slot (FACE) takes any word", fo, "cmd\tspark font Terminus 16\nfont\n", True)
    # the tree itself, read from completion: the facts the grader leans on
    ok = "quiet" in tree["verbs"] and "shell" not in tree["verbs"] and "boot" in tree["words"].get("quiet", ())
    print(("ok   " if ok else "FAIL ") + "the tree reads completion: quiet is a verb, shell is not")
    if not ok:
        fails.append("tree")
    ok = bool(tree["models"]) and all(m in tree["words"].get("model", ()) for m in tree["models"])
    print(("ok   " if ok else "FAIL ") + "the tree fills model names from the model tables")
    if not ok:
        fails.append("models")
    # every case in cases.json is well formed: a new case cannot break a run
    data = load_cases()
    keys = {"id", "words", "kind", "head_any", "must_not", "danger", "spark_verb", "answer_any", "topic"}
    ids = [c["id"] for k in data["cases"] for c in data["cases"][k]]
    bad = [c.get("id", "?") for k in data["cases"] for c in data["cases"][k]
           if set(c) - keys or not c.get("words") or c.get("kind") not in ("cmd", "answer", None)
           or not (c.get("head_any") or c.get("answer_any") or c.get("spark_verb"))]
    bad += [i for i in set(ids) if ids.count(i) > 1]
    for k in data["cases"]:
        for c in data["cases"][k]:
            for p in list(c.get("must_not", [])) + list(c.get("answer_any", [])):
                try:
                    re.compile(p)
                except re.error:
                    bad.append(c["id"])
            if k == "spark":
                bad += [c["id"] for v in c.get("spark_verb", ()) if v not in tree["verbs"]]
    ok = not bad and set(data["cases"]) == set(OSES) | {"spark"}
    print(("ok   " if ok else "FAIL ") + "cases.json: %d cases, each well formed%s"
          % (len(ids), "" if ok else " (%s)" % ", ".join(sorted(set(bad)))))
    if not ok:
        fails.append("cases")
    print("%s: %d failed" % ("line_audition selftest", len(fails)) if fails else "line_audition selftest: all ok")
    return 1 if fails else 0


COMMANDS = {"run": cmd_run, "collect": cmd_collect, "report": cmd_report, "packages": cmd_packages,
            "serve-candidate": cmd_serve_candidate, "selftest": cmd_selftest}


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
