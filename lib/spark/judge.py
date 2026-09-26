# spark.judge -- the Judge context: what spark finds about a proposed
# command before a person sees it. Local, no model call: every stage's head
# must be a builtin, a spark verb from the tree, or a program on PATH, and
# every option must be in that program's own entry. A finding names one
# problem; a verdict with none is ok. read_only() lets spark's own argv
# proof lower a model's `!` -- persona.is_dangerous always wins.
#
# Unknown is not wrong: a program with no entry, or an entry whose manual
# named no options, earns no flag finding; a line this parser cannot read
# earns none at all. The parser is this module's own -- the audition's
# grader (tests/line_audition.py) is independent code on purpose, the
# referee never sharing the player's parser.
#
# The import rule (a smoke test holds it): this module imports the
# package itself, grounding, intake and persona, never cli, session or
# wire; only cli and bench import it.

import os
import re
import shutil
import signal
from collections import namedtuple

from . import CONFIG_DIR, REPO, grounding, persona

# kind: missing (no such program here) | flag (not in its entry) | verb
# (not a spark verb or word) | placeholder (a <word> the shell would read
# as a redirect)
Finding = namedtuple("Finding", "kind head word")


class Verdict(namedtuple("Verdict", "findings")):
    @property
    def ok(self):
        return not self.findings


# ------------------------------------------------------------ the parser
# the shell's operators, longest first: the ones that end a stage, and
# the redirections (whose target word goes with them)
_OPS = ("&>>", "<<<", "&&", "||", ";;", "|&", "&>", ">>", ">|", ">&", "<<", "<>", "<&",
        "|", "&", ";", "(", ")", "<", ">")
_ENDS = frozenset(("&&", "||", ";;", "|&", "|", "&", ";", "(", ")"))


def _tokens(line):
    """[(kind, text)]: 'w' a word as the shell reads its quotes, 'op' an
    operator outside them. A digit word glued to a redirection (2>) is
    the stream, not a word. Raises ValueError on an unclosed quote."""
    toks, cur, has, i, n = [], [], False, 0, len(line)

    def flush():
        if has:
            toks.append(("w", "".join(cur)))

    while i < n:
        ch = line[i]
        if ch in " \t\n":
            flush()
            cur, has, i = [], False, i + 1
        elif ch == "#" and not has:
            break                                  # a comment runs to the end
        elif ch == "\\":
            cur.append(line[i + 1:i + 2])
            has, i = True, i + 2
        elif ch == "'":
            j = line.find("'", i + 1)
            if j < 0:
                raise ValueError("unclosed quote")
            cur.append(line[i + 1:j])
            has, i = True, j + 1
        elif ch == '"':
            j, buf = i + 1, []
            while j < n and line[j] != '"':
                if line[j] == "\\" and j + 1 < n and line[j + 1] in '"\\$`':
                    buf.append(line[j + 1])
                    j += 2
                else:
                    buf.append(line[j])
                    j += 1
            if j >= n:
                raise ValueError("unclosed quote")
            cur.append("".join(buf))
            has, i = True, j + 1
        elif line.startswith("$(", i):
            depth, j = 1, i + 2                    # a substitution stays inside its word, whole
            while j < n and depth:
                depth += {"(": 1, ")": -1}.get(line[j], 0)
                j += 1
            if depth:
                raise ValueError("unclosed substitution")
            cur.append(line[i:j])
            has, i = True, j
        elif ch == "`":
            j = line.find("`", i + 1)
            if j < 0:
                raise ValueError("unclosed backtick")
            cur.append(line[i:j + 1])
            has, i = True, j + 1
        elif ch in "|&;()<>":
            op = next(o for o in _OPS if line.startswith(o, i))
            if op[0] in "<>" and op not in _ENDS and has and "".join(cur).isdigit():
                cur, has = [], False               # 2> : the 2 is the stream
            else:
                flush()
                cur, has = [], False
            toks.append(("op", op))
            i += len(op)
        else:
            cur.append(ch)
            has, i = True, i + 1
    flush()
    return toks


def _stages(line):
    """The command's stages as [[word, ...]], split on | || && ; & and
    parentheses; a redirection and its target are dropped."""
    stages, cur, skip = [], [], False
    for kind, t in _tokens(line):
        if kind == "op":
            if t in _ENDS:
                if cur:
                    stages.append(cur)
                cur = []
            else:
                skip = True
            continue
        if skip:
            skip = False
            continue
        cur.append(t)
    if cur:
        stages.append(cur)
    return stages


# a wrapper runs the command after its own options: the options that
# take a value (the next word, unless glued on), and how many plain
# words it takes before the command (timeout's duration)
WRAPPERS = {
    "sudo": (("-u", "-g", "-h", "-p", "-C", "-D", "-r", "-t", "-U", "-T", "-R", "--user",
              "--group", "--host", "--prompt", "--close-from", "--chdir", "--role", "--type",
              "--other-user", "--command-timeout", "--chroot"), 0),
    "doas": (("-u", "-C"), 0),
    "env": (("-u", "-C", "-S", "--unset", "--chdir", "--split-string"), 0),
    "nice": (("-n", "--adjustment"), 0),
    "nohup": ((), 0),
    "timeout": (("-s", "-k", "--signal", "--kill-after"), 1),
    "xargs": (("-I", "-L", "-n", "-P", "-s", "-d", "-E", "-a", "--arg-file", "--delimiter",
               "--eof", "--max-lines", "--max-args", "--max-procs", "--max-chars", "--replace",
               "--process-slot-var"), 0),
    "watch": (("-n", "--interval", "-q", "--equexit"), 0),
    "stdbuf": (("-i", "-o", "-e", "--input", "--output", "--error"), 0),
    "ionice": (("-c", "-n", "-p", "-P", "-u", "--class", "--classdata"), 0),
}
# the shell's own words that run the command after them
KEYWORDS = frozenset(("!", "time", "if", "then", "elif", "else", "while", "until", "do", "{"))
# words the shell answers itself, beyond persona's list: a stage whose
# head is one needs no program on PATH
BUILTINS = persona.SH_BUILTINS | frozenset((
    "command", "builtin", "true", "false", ":", "exit", "return", "local", "declare",
    "typeset", "readonly", "let", "pushd", "popd", "dirs", "hash", "ulimit", "history",
    "disown", "suspend", "shopt", "bind", "complete", "compgen", "caller", "enable",
    "help", "logout", "times", "getopts", "noglob", "autoload", "setopt", "unsetopt",
    "whence", "where", "rehash", "zmodload", "bindkey", "print", "for", "case", "esac",
    "fi", "done", "function", "select", "}", "[[", "]]", "coproc", "wait"))


def _unwrap(stage):
    """One stage -> [(head, args, own)]: each wrapper as its own entry
    (own=True: its options are its own, not checked), then the command
    it runs. Assignments before a head are dropped."""
    out, words = [], list(stage)
    while words:
        while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            words.pop(0)
        if not words:
            break
        head, rest = words[0], words[1:]
        if head in KEYWORDS:
            words = rest
            continue
        if head not in WRAPPERS:
            out.append((head, rest, False))
            break
        valued, plain = WRAPPERS[head]
        out.append((head, [], True))
        while rest and rest[0].startswith("-") and rest[0] != "-":
            opt = rest.pop(0)
            if opt == "--":
                break
            if opt in valued and rest:
                rest.pop(0)
        for _ in range(plain):
            if rest:
                rest.pop(0)
        if head == "watch" and len(rest) == 1 and " " in rest[0]:
            try:
                inner = _stages(rest[0])        # watch 'ps aux': one string, a command inside
            except ValueError:
                inner = []
            rest = inner[0] if inner else []
        words = rest
    return out


# ------------------------------------------------------------ this machine
_WHICH, _ENTRIES = {}, {}


def _on_path(head):
    """Is `head` a program on PATH -- the absolute entries only, so a
    program planted in the working directory is not the machine's."""
    got = _WHICH.get(head)
    if got is None:
        dirs = [d for d in os.environ.get("PATH", "").split(os.pathsep) if os.path.isabs(d)]
        got = bool(dirs) and shutil.which(head, path=os.pathsep.join(dirs)) is not None
        _WHICH[head] = got
    return got


def _present(store, head):
    """Is `head` a program here: a store that speaks for another machine
    (the audition's snapshot) answers for it -- True, or None for not
    known, which is never a finding -- else this machine's PATH does."""
    ask = getattr(store, "has_program", None)
    if callable(ask):
        got = ask(head)
        return True if got is None else bool(got)
    return _on_path(head)


def _entry(store, name):
    key = (id(store), name)
    if key not in _ENTRIES:
        try:
            _ENTRIES[key] = store.entry(name)
        except (OSError, ValueError, TypeError, AttributeError):
            _ENTRIES[key] = None
    return _ENTRIES[key]


def _options(entry):
    """(long, short, words) as sets from an entry's OptionSet, whichever
    shape its three fields take (a string of letters, or a list of -x)."""
    o = getattr(entry, "options", None)
    long, short, wordset = set(), set(), set()
    if not o:
        return long, short, wordset
    get = o.get if isinstance(o, dict) else (lambda k: getattr(o, k, None))
    for x in get("long") or ():
        x = str(x)
        long.add(x if x.startswith("--") else "--" + x.lstrip("-"))
    sh = get("short") or ""
    for x in (sh if not isinstance(sh, str) else list(sh)):
        x = str(x).lstrip("-")
        if len(x) == 1:
            short.add(x)
        elif x:
            wordset.add("-" + x)
    for x in get("words") or ():
        x = str(x)
        if x.startswith("--"):
            long.add(x.split("=", 1)[0])
        elif re.match(r"^-[A-Za-z0-9]$", x):
            short.add(x[1])
        elif x.startswith("-"):
            wordset.add(x)
    return long, short, wordset


# an option line that shows its option takes a value: `-o fmt  ...`,
# `--sort=KEY`, `-n, --lines=NUM`
_VALUED = re.compile(r"(?:^|,\s*|\s)(--?[A-Za-z0-9][\w-]*)(?:=|\s|\[=?)\[?(?!-)[<A-Za-z_][\w.,<>|:-]*\]?"
                     r"(?=\s{2,}|\s*$|,|\s+--\s)")


def _valued(entry):
    got = set()
    for line in getattr(entry, "lines", None) or ():
        got.update(m.group(1) for m in _VALUED.finditer(grounding.line_text(line)))
    return got


# ------------------------------------------------------------ findings
_SIGNALS = frozenset(
    ("HUP INT QUIT ILL TRAP ABRT IOT BUS EMT FPE KILL USR1 SEGV USR2 PIPE ALRM TERM STKFLT "
     "CHLD CLD CONT STOP TSTP TTIN TTOU URG XCPU XFSZ VTALRM PROF WINCH IO POLL PWR SYS "
     "INFO LOST UNUSED EXIT ERR DEBUG RETURN").split()) | frozenset(
    s.name[3:] for s in signal.Signals if s.name.startswith("SIG") and not s.name.startswith("SIG_"))


def _signal_ok(name):
    n = name.upper()
    n = n[3:] if n.startswith("SIG") else n
    return n.isdigit() or n in _SIGNALS or re.match(r"^RTM(IN|AX)([+-]\d+)?$", n) is not None


def _kill(args):
    """kill is the shell's: its options are signals, checked by name."""
    out, it = [], iter(args)
    for a in it:
        if a == "--":
            break
        if a in ("-s", "-n", "--signal"):
            name = next(it, "")
            if name and not _signal_ok(name):
                out.append(Finding("flag", "kill", name))
        elif a.startswith("-") and len(a) > 1 and a not in ("-l", "-L", "-p", "-a", "-q", "--list", "--table"):
            if not _signal_ok(a[1:]):
                out.append(Finding("flag", "kill", a))
    return out


def _mentions(entry, token):
    """Does the entry's own text (synopsis, option lines) spell `token`
    anywhere: an option the parse of its manual missed is still not a
    wrong one."""
    blob = " ".join([str(getattr(entry, "synopsis", "") or "")]
                    + [grounding.line_text(x) for x in getattr(entry, "lines", None) or ()])
    return re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(token), blob) is not None


def _flags(head, args, entry):
    """The options in `args` the entry does not name. `find -exec ... ;`
    is the command's own, and `--` ends the options."""
    long, short, wordset = _options(entry)
    if not (long or short or wordset):
        return []
    valued = _valued(entry)
    found, skip, in_exec = [], False, False
    for a in args:
        if skip:
            skip = False
            continue
        if in_exec:
            in_exec = a not in (";", "+")
            continue
        if a == "--":
            break
        if head == "find" and a in ("-exec", "-execdir", "-ok", "-okdir"):
            in_exec = True                          # the command after it is its own
            continue
        if not a.startswith("-") or a == "-" or " " in a or re.match(r"^-\d+$", a):
            continue                                # a word, stdin, a phrase, a count (head -10)
        if a.startswith("--"):
            name = a.split("=", 1)[0]
            if name not in long and name not in wordset:
                found.append((name, a))
            skip = "=" not in a and name in valued
            continue
        if a in wordset:
            skip = a in valued
            continue
        if wordset and len(a) > 2 and a[1:].isalpha() and not set(a[1:]) <= short:
            found.append((a, a))                    # -name, -mtime: a program with word options
            continue
        for j, ch in enumerate(a[1:]):
            if not ch.isalpha():
                break                               # -k2,2 -t, : the rest is a value
            if ch not in short:
                found.append(("-" + ch, a))
                break
            if "-" + ch in valued:
                skip = j == len(a) - 2              # its value is the next word
                break
    return [Finding("flag", head, w) for w, tok in dict.fromkeys(found)
            if not (_mentions(entry, w) or _mentions(entry, tok.split("=", 1)[0]))]


def _dynamic(verb):
    """The names the tree fills a slot with: a palette, a model."""
    names = set()
    if verb == "theme":
        for d in (os.path.join(REPO, "themes"), os.path.join(CONFIG_DIR, "themes")):
            try:
                names.update(n[:-4] for n in os.listdir(d) if n.endswith(".env"))
            except OSError:
                pass
    else:
        for f in (os.path.join(REPO, "models.env"), os.path.join(CONFIG_DIR, "models.env")):
            try:
                with open(f, encoding="utf-8") as fh:
                    src = fh.read()
            except OSError:
                continue
            for m in re.finditer(r"^MODEL_([A-Z0-9_]+)=", src, re.M):
                key = m.group(1)
                if not key.endswith(("_LICENSE", "_NOTE", "_TESTED", "_GROUND")):
                    names.add(key.lower().replace("_", "-"))
    return names


def _spark(args):
    """spark's own verbs and words, against the tree. A question (a ?,
    an @FILE) is words, never a verb."""
    if not args or args[0].startswith("-"):
        return []
    verb = args[0]
    if verb.startswith("@") or any("?" in a for a in args):
        return []
    tree = grounding.spark_tree()
    if verb not in tree.verbs:
        return [Finding("verb", "spark", verb)]
    rest = args[1:]
    known = tree.words.get(verb)
    if not rest or rest[0].startswith("-") or known is None:
        return []
    w = rest[0]
    if w not in known and not (verb in tree.dynamic and w in _dynamic(verb)):
        return [Finding("verb", "spark " + verb, w)]
    nxt = tree.third.get((verb, w))
    if nxt and len(rest) > 1 and not rest[1].startswith("-") and rest[1] not in nxt:
        return [Finding("verb", "spark %s %s" % (verb, w), rest[1])]
    return []


_ANGLE = re.compile(r"(?<![<\w])<([A-Za-z][\w.-]*(?: [\w.-]+)*)>(?!>)")
_SQUARE = re.compile(r"(?:^|(?<=[\s;&|(]))\[([A-Za-z][\w.-]*)\](?=$|[\s;&|)])")


def _unquoted(line):
    """`line` with every quoted span blanked: a <div> inside quotes is a
    pattern, not a placeholder."""
    out, quote = [], ""
    for ch in line:
        if quote:
            out.append(" ")
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def _placeholders(line):
    bare = _unquoted(line)
    out = []
    for m in list(_ANGLE.finditer(bare)) + list(_SQUARE.finditer(bare)):
        try:
            before = _stages(bare[:m.start()])
        except ValueError:
            before = []
        heads = _unwrap(before[-1]) if before else []
        out.append(Finding("placeholder", heads[-1][0] if heads else "", m.group(0).strip()))
    return out


# a synopsis that runs something after the program's own words
_TAKES = re.compile(r"(?i)\b(?:sub)?command\b|\butility\b|\bscript\b|\bprogramfile\b")


def _stage(words, store):
    out = []
    for head, args, own in _unwrap(words):
        if not head or re.search(r"[$`*?\[]", head) or head.startswith("-"):
            continue                                # opaque, a glob: nothing to read
        if head == "kill":
            out.extend(_kill(args))
            continue
        if head in BUILTINS:
            continue
        if head in ("spark", "explain"):
            out.extend(_spark(args) if head == "spark" else [])
            continue
        if "/" in head:
            if not os.path.isabs(head):
                continue                            # ./script: this directory's, not the machine's
            if not os.path.exists(head):
                out.append(Finding("missing", head, head))
                continue
            head = os.path.basename(head)
        elif not _present(store, head):
            out.append(Finding("missing", head, head))
            continue
        if own:
            continue
        entry = _entry(store, head)
        if entry is None:
            continue
        # a program with an entry per subcommand (git log, xbps-query):
        # the options before the subcommand are the program's, after it
        # the subcommand's own -- and after one with no entry, nobody's.
        # A program whose synopsis runs a command, a utility or a script
        # after its words (ssh HOST ls -la, python3 x.py --port) has its
        # own options checked up to that word and no further.
        valued = _valued(entry)
        i = 0
        while i < len(args) and args[i] != "--" and args[i].startswith("-"):
            i += 2 if (args[i] in valued and "=" not in args[i]) else 1
        word = args[i] if i < len(args) and args[i] != "--" else ""
        if word and head in grounding.parents(store) and re.match(r"^[a-z][\w-]*$", word):
            out.extend(_flags(head, args[:i], entry))
            sub = _entry(store, "%s %s" % (head, word))
            if sub is not None:
                out.extend(_flags("%s %s" % (head, word), args[i + 1:], sub))
        elif word and _TAKES.search(str(getattr(entry, "synopsis", "") or "")):
            out.extend(_flags(head, args[:i], entry))
        else:
            out.extend(_flags(head, args, entry))
    return out


def verdict(command, store=None):
    """The Verdict on one command line: what is missing, which flag no
    manual here names, which spark verb or word the tree lacks, which
    placeholder is left in. Never raises; a line it cannot read is ok."""
    line = command or ""
    try:
        stages = _stages(line)
        store = grounding.default_store(store)
        found = list(_placeholders(line))
        for words in stages:
            found.extend(_stage(words, store))
    except Exception:                               # the line never breaks on the judge: unknown, not wrong
        return Verdict(())
    return Verdict(tuple(dict.fromkeys(found)))


# ------------------------------------------------------------ read only
def _raw_stages(line):
    """`line` cut at every unquoted | || && ; & -- the words and the
    redirections left exactly as written, for proof_ok to read. None on
    an unclosed quote."""
    out, cur, quote, i = [], [], "", 0
    while i < len(line):
        ch = line[i]
        if quote:
            cur.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < len(line):
                cur.append(line[i + 1])
                i += 1
            elif ch == quote:
                quote = ""
        elif ch == "\\" and i + 1 < len(line):
            cur.append(line[i:i + 2])
            i += 1
        elif ch in "'\"":
            quote = ch
            cur.append(ch)
        elif ch in "|&;":
            out.append("".join(cur))
            cur = []
            if line[i:i + 2] in ("||", "&&"):
                i += 1
        else:
            cur.append(ch)
        i += 1
    if quote:
        return None
    out.append("".join(cur))
    return out


def read_only(command):
    """True when every stage of `command` passes spark's own read-only argv
    proof (persona's proof lists, unchanged) and nothing is dangerous.
    Each stage is handed to persona.proof_ok as it is written -- no
    wrapper unwrapped, no assignment or redirection removed -- so an
    `env GIT_EXTERNAL_DIFF=... git diff` stays refused."""
    c = command or ""
    if not c.strip() or grounding.CONTROL.search(c) or persona.opaque(c) or persona.is_dangerous(c):
        return False
    stages = _raw_stages(c)
    return bool(stages) and all(s.strip() and persona.proof_ok(s) for s in stages)
