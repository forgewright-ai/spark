# spark.mcp -- contract 16's client half: spark as an MCP host, stdio only.
#
# A server is a named line in ~/.config/spark/mcp.env, read by the
# contract-3 reader: MCP_SERVER_<NAME>="<absolute path> [words]". A server
# not on that list is never started. spark starts one with no shell, cwd
# HOME, the environment ENV_KEEP names and nothing else, stdin and stdout
# its wire (JSON-RPC 2.0, one message a line, PROTOCOL pinned), stderr
# thrown away. It speaks initialize, tools/list, tools/call, resources
# (list, read, subscribe), ping and elicitation; it declares no sampling
# and no roots, ever, and there is no HTTP transport.
#
# The gate (call): the tool is in the server's tools/list now; its
# arguments validate against its inputSchema, an argument it does not
# name refused; where the server's rows resource names that tool with its
# arguments, the call names one of them exactly; and a person saw the
# step. A tool's annotations are believed only from a trusted server
# (TRUSTED_CHAIN, or MCP_SERVER_<NAME>_TRUST=yes): there a destructive
# tool takes the typed yes; from any other server every tool does. No
# terminal to type it at: refused. Every tools/call sent is one sealed
# audit record, `mcp/call`: names and a digest, never an argument or a
# result. Every string a server hands on passes scrub() before a
# terminal, a brief or a record.
#
# `spark line` never comes here: the prompt line reads TOOLS_FILE, which
# `spark mcp` writes, line by line (brief_tools), and never starts a
# server or talks to one.

import getpass
import hashlib
import json
import os
import queue
import re
import secrets
import select
import signal
import stat
import subprocess
import sys
import threading
import time

from . import CONFIG_DIR, HOME, MARK, STATE_DIR, config, log_exc, page, say
from . import text as textmod

PROTOCOL = "2025-06-18"           # the spec spark speaks, pinned: a server that answers another is closed
MCP_ENV = os.environ.get("SPARK_MCP_ENV") or os.path.join(CONFIG_DIR, "mcp.env")
TOOLS_FILE = os.path.join(STATE_DIR, "mcp-tools")   # what `spark mcp` last listed: the prompt line's and do's tools

KEY = re.compile(r"^MCP_SERVER_([A-Z][A-Z0-9_]{0,31})$")
NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")              # a server's name, as typed: its key's part, lower case
TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")         # a tool's name, or it is not offered
TITLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ,.'/_-]{0,79}$")   # a title a brief may carry, or it is not offered
ARG_WORD = re.compile(r"^[a-z][a-z0-9_]{0,31}$")          # an argument's name a step may carry
ENUM_WORD = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$")   # a choice a brief may name; any other enum reads TEXT
TRUST_SUFFIX = "_TRUST"

# The programs trusted by default: the trusted chain. A server whose
# program, its link resolved, carries one of these names, and whose file
# and directory only its owner or root may write, is trusted unless its
# _TRUST key says no. A named line each, so it can be argued with.
TRUSTED_CHAIN = (
    "spark",          # spark itself
    "spark-shell",    # the seat: the desktop's providers, one server a part
    "spark-acp",      # the task verb's client
)

# The environment a server gets, a named line each; nothing else is passed.
ENV_KEEP = (
    "HOME",                       # where its config and state live
    "PATH",                       # the tools it runs
    "USER",                       # who it runs as
    "LOGNAME",                    # the same, by another name
    "LANG",                       # the language of its words
    "LC_ALL",                     # the same
    "LC_CTYPE",                   # the same
    "TMPDIR",                     # where its scratch files go
    "XDG_CONFIG_HOME",            # its config
    "XDG_STATE_HOME",             # its state
    "XDG_DATA_HOME",              # its data
    "XDG_CACHE_HOME",             # its cache
    "XDG_RUNTIME_DIR",            # the session's sockets
    "WAYLAND_DISPLAY",            # the desktop
    "SWAYSOCK",                   # sway's own socket, for the windows
    "DBUS_SESSION_BUS_ADDRESS",   # the session bus
)

# The words that make an argument a credential: a field so named, or one
# whose schema says format password, is never a word on the line, never
# shown, never kept and never in a digest. A word is a part of the name
# split at _ and -, so `mapping` and `encode` are no credential; the long
# words also count at either end of a part (`apitoken`, `passwordhash`).
CREDENTIAL_WORDS = ("password", "passphrase", "psk", "token", "secret", "pin", "code")
CREDENTIAL_ENDS = ("password", "passphrase", "token", "secret")

# What a server hands on that can redraw or reorder a screen goes, beyond
# text.printable (escapes, C0, DEL, C1, the bidi controls): a named line
# each, so it can be argued with.
ZERO_WIDTH = re.compile(
    "[\u200b-\u200d"       # zero-width space, non-joiner, joiner
    "\u2060-\u2064"        # word joiner and the invisible operators
    "\ufeff"               # zero-width no-break space (a BOM)
    "\u00ad"               # the soft hyphen
    "\u180e"               # the Mongolian vowel separator
    "\ufe00-\ufe0f"        # the variation selectors
    "\U000e0000-\U000e007f"  # the tag characters: text a model reads and a person never sees
    "\u2028\u2029]")       # the line and paragraph separators

LINE_MAX = 65536            # a message from a server, at most: a longer line closes it
RESOURCE_MAX = 262144       # a resource read, at most
RESULT_MAX = 65536          # a result's text spark prints, at most
INIT_TIMEOUT = 5            # seconds for initialize, and again for tools/list
LIST_TIMEOUT = 5
READ_TIMEOUT = 10           # a resource read
CALL_TIMEOUT = 120          # a tools/call's ceiling, whatever its progress says: do.STEP_TIMEOUT
STOP_WAIT = 2               # seconds a server has to end once its stdin closed, then once more after SIGTERM
WRITE_TIMEOUT = 5           # seconds a message to a server may take to write: one that stops reading is closed
SERVER_ASKS_MAX = 64        # requests of its own a server may send while spark waits on one: past them it is closed
QUEUE_MAX = 256             # messages read ahead of spark: past them the reader waits, and so does the server
TOOLS_MAX = 128             # tools kept from one server; the rest are not offered
PAGES_MAX = 8               # tools/list pages read, at most
ELICIT_PER_CALL = 3         # questions a server may ask in one call
ELICIT_PER_MINUTE = 6       # and in a minute, over every call
ELICIT_MESSAGE_MAX = 300    # characters of its question shown
STRING_MAX = 4096           # a string argument with no maxLength of its own
ARRAY_MAX = 32              # an array argument's items, with no maxItems of its own
BRIEF_MAX = 1500            # characters of tool lines a brief carries
SHOW_MAX = 300              # characters of a server's error or refusal shown

USAGE = """spark mcp -- the MCP servers spark may start, and their tools

  spark mcp                    every server on the list, and its tools
  spark mcp NAME               one server: its tools, their arguments
  spark mcp add NAME PATH [WORDS]
                               put a server on the list: its program,
                               an absolute path, and the words after it
  spark mcp rm NAME            take a server off the list
  spark mcp trust NAME [on|off]
                               believe what its tools say of themselves
  spark mcp call NAME TOOL [KEY=VALUE ...]
                               run one tool; a value is typed as the tool
                               takes it, and a password is asked for
  spark mcp read NAME [URI] [--watch]
                               a server's resources, or one of them;
                               --watch shows it again as it changes

  The list is ~/.config/spark/mcp.env, one line a server:
  MCP_SERVER_NAME="/absolute/path words". A server not on it is never
  started. spark's own programs, the trusted chain, are trusted; any
  other only with spark mcp trust NAME on (spark mcp says which). A
  tool that changes things asks you to type yes, unless a trusted
  server says it destroys nothing.
"""


class Refused(Exception):
    """One line saying why a server, a tool or a call is refused."""

    def __init__(self, hint):
        super().__init__(hint)
        self.hint = hint


def scrub(s, keep=""):
    """A server's string fit for a terminal, a brief or a record:
    text.printable (escapes and control characters, `keep` excepted),
    then ZERO_WIDTH; strict UTF-8."""
    return ZERO_WIDTH.sub("", textmod.printable(textmod.utf8(str(s)), keep))


def short(s, n=SHOW_MAX):
    """scrub() on one line, cut at n characters."""
    s = " ".join(scrub(s, "\t\n").split())
    return s if len(s) <= n else s[:n - 3] + "..."


def home_short(path):
    return "~" + path[len(HOME):] if path.startswith(HOME + "/") else path


# ---------------------------------------------------------------- the list
class Spec:
    """One server on the list: its name, its argv, whether it is trusted
    and why, and what keeps it from starting ('' when nothing does)."""
    __slots__ = ("name", "argv", "trusted", "why", "problem")

    def __init__(self, name, argv, trusted, why, problem):
        self.name, self.argv, self.trusted, self.why, self.problem = name, argv, trusted, why, problem


def private_group(gid, uid):
    """True when group `gid` is the owner's alone: no member but the
    owner, and no other user's primary group (a user private group, as
    a umask of 0002 expects)."""
    import grp
    import pwd
    try:
        owner = pwd.getpwuid(uid).pw_name
        members = set(grp.getgrgid(gid).gr_mem)
        others = any(p.pw_gid == gid and p.pw_uid != uid for p in pwd.getpwall())
    except (KeyError, OSError):
        return False
    return members <= {owner} and not others


def _owned_safe(path):
    """'' when `path` is owned by this user or root and nobody else may
    write it -- its group may, when that group is the owner's alone
    (private_group) -- else why not."""
    try:
        st = os.stat(path)
    except OSError:
        return "%s is not there" % home_short(path)
    if st.st_uid not in (os.getuid(), 0):
        return "%s is someone else's" % home_short(path)
    if st.st_mode & 0o002 or (st.st_mode & 0o020 and not private_group(st.st_gid, st.st_uid)):
        return "others may write %s" % home_short(path)
    return ""


def _ancestors_safe(path):
    """'' when every directory above `path` up to / is owned by this user
    or root and nobody else may write it (a root-owned sticky directory,
    /tmp, is safe: nobody else can rename what is in it), else why not
    -- ssh's StrictModes, for the program spark starts."""
    d = os.path.dirname(path)
    while True:
        try:
            st = os.stat(d)
        except OSError:
            return "%s is not there" % home_short(d)
        if not (st.st_uid == 0 and st.st_mode & stat.S_ISVTX):
            why = _owned_safe(d)
            if why:
                return why
        up = os.path.dirname(d)
        if up == d:
            return ""
        d = up


def program_problem(prog):
    """'' when a server's program may be started: an absolute path to an
    executable regular file, it and every directory above it written by
    its owner alone (the link resolved), else why not."""
    if not os.path.isabs(prog):
        return "%s is not an absolute path" % prog
    real = os.path.realpath(prog)
    try:
        st = os.stat(real)
    except OSError:
        return "%s is not there" % home_short(prog)
    if not stat.S_ISREG(st.st_mode) or not os.access(real, os.X_OK):
        return "%s is not a program" % home_short(prog)
    return _owned_safe(real) or _ancestors_safe(real)


CHAIN_ORIGIN = re.compile(r"^\s*url\s*=\s*(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
                          r"forgewright-ai/([a-z-]+?)(?:\.git)?/?\s*$", re.M)


def _origin(path):
    """The forgewright-ai repository name the git clone holding `path`
    was cloned from (its config's remote url), or ''."""
    d = os.path.dirname(path)
    while True:
        dot = os.path.join(d, ".git")
        cfg = ""
        if os.path.isdir(dot):
            cfg = os.path.join(dot, "config")
        elif os.path.isfile(dot):
            try:
                with open(dot, encoding="utf-8") as f:
                    gitdir = f.read(4096).strip().split("gitdir:", 1)[-1].strip()
                gitdir = os.path.join(d, gitdir)
                common = gitdir
                if os.path.isfile(os.path.join(gitdir, "commondir")):
                    with open(os.path.join(gitdir, "commondir"), encoding="utf-8") as f:
                        common = os.path.join(gitdir, f.read(4096).strip())
                cfg = os.path.join(common, "config")
            except OSError:
                return ""
        if cfg:
            try:
                with open(cfg, encoding="utf-8") as f:
                    m = CHAIN_ORIGIN.search(f.read(65536))
            except OSError:
                return ""
            return m.group(1) if m else ""
        up = os.path.dirname(d)
        if up == d:
            return ""
        d = up


def chain_member(prog):
    """The trusted chain's name `prog` carries, its link resolved, when
    it lives in a clone of that very forgewright-ai repository (another
    project's program of the same name, or a file of that name anywhere
    else, is not the chain), or ''."""
    if not os.path.isabs(prog):
        return ""
    real = os.path.realpath(prog)
    base = os.path.basename(real)
    return base if base in TRUSTED_CHAIN and _origin(real) == base else ""


def read_list(path=None):
    """{KEY: value} of the list, the file's order; {} when there is none.
    A line of another shape refuses the file (contract 3)."""
    path = path or MCP_ENV
    if not os.path.isfile(path):
        return {}
    why = _owned_safe(path) or _owned_safe(os.path.dirname(path))
    if why:
        raise Refused("%s -- chmod 600 %s" % (why, home_short(path)))
    return config.parse_env(path)


def specs(path=None):
    """[Spec] for every MCP_SERVER_<NAME> line, in the file's order."""
    kv = read_list(path)
    out = []
    for key, val in kv.items():
        m = KEY.match(key)
        if not m or key.endswith(TRUST_SUFFIX):
            continue
        name = m.group(1).lower()
        argv = val.split()
        problem = program_problem(argv[0]) if argv else "no program"
        trust = kv.get(key + TRUST_SUFFIX, "")
        member = chain_member(argv[0]) if argv else ""
        if trust == "yes":
            trusted, why = True, "trusted (spark mcp trust)"
        elif trust == "no":
            trusted, why = False, "not trusted (spark mcp trust)"
        elif member and not problem:
            trusted, why = True, "trusted (the trusted chain: %s)" % member
        else:
            trusted, why = False, "not trusted"
        out.append(Spec(name, argv, trusted, why, problem))
    return out


def spec(name, path=None):
    for s in specs(path):
        if s.name == name:
            return s
    raise Refused("no server named %s on the list -- spark mcp lists them" % name)


def env():
    """The environment a server starts with: ENV_KEEP, nothing else."""
    out = {k: os.environ[k] for k in ENV_KEEP if os.environ.get(k)}
    out["HOME"] = HOME
    return out


# --------------------------------------------------------------- the wire
class Tool:
    """A tool as a server listed it, its strings scrubbed: the name, the
    title, the input schema, and what its annotations mean here (`hints`,
    as said; `read_only` and `destructive`, the spec's defaults where it
    says nothing)."""
    __slots__ = ("server", "name", "title", "schema", "read_only", "destructive", "trusted")

    def __init__(self, server, name, title, schema, read_only, destructive, trusted):
        self.server, self.name, self.title, self.schema = server, name, title, schema
        self.read_only, self.destructive, self.trusted = read_only, destructive, trusted

    def needs_yes(self):
        """The typed yes: every tool of a server not trusted; a trusted
        server's tool when it may destroy (destructiveHint, true unless it
        says false or says it only reads)."""
        return not self.trusted or self.destructive

    def args(self):
        """[(name, kind, required)] of its input schema's properties, a
        credential's left out."""
        props = self.schema.get("properties") or {}
        req = set(required(self.schema))
        out = []
        for k, p in props.items():
            if secret(k, p):
                continue
            out.append((k, kind(p), k in req))
        return out


def kind(prop):
    """A property's kind as a step writes it: N, TEXT, yes|no, a|b|c."""
    if not isinstance(prop, dict):
        return "TEXT"
    if isinstance(prop.get("enum"), list) and prop["enum"]:
        words = [v for v in prop["enum"][:12] if isinstance(v, str) and ENUM_WORD.match(v)]
        return "|".join(words) if len(words) == len(prop["enum"][:12]) else "TEXT"
    t = prop.get("type")
    if t in ("integer", "number"):
        return "N"
    if t == "boolean":
        return "yes|no"
    if t == "array":
        return "A,B"
    return "TEXT"


def secret(name, prop=None):
    if isinstance(prop, dict) and prop.get("format") == "password":
        return True
    parts = [w for w in re.split(r"[_\-]+", str(name).lower()) if w]
    return any(w in CREDENTIAL_WORDS or w.startswith(CREDENTIAL_ENDS) or w.endswith(CREDENTIAL_ENDS) for w in parts)


def tool_of(server, d, trusted):
    """A Tool from one tools/list entry, or None when it is not offered:
    a name not TOOL_NAME, a title not TITLE, a schema that is no object."""
    if not isinstance(d, dict):
        return None
    name = d.get("name")
    if not isinstance(name, str) or not TOOL_NAME.match(name):
        return None
    ann = d.get("annotations") if isinstance(d.get("annotations"), dict) else {}
    title = d.get("title") or ann.get("title") or ""
    if title and (not isinstance(title, str) or not TITLE.match(title)):
        return None                     # the title shape, as sent: never one a scrub made fit
    schema = d.get("inputSchema")
    if not isinstance(schema, dict) or schema.get("type", "object") != "object":
        return None
    props = schema.get("properties") or {}
    if not isinstance(props, dict) or not all(isinstance(k, str) and ARG_WORD.match(k) for k in props):
        return None
    read_only = ann.get("readOnlyHint") is True                 # the spec's default: false
    destructive = not read_only and ann.get("destructiveHint") is not False   # the spec's default: true
    return Tool(server, name, title, schema, read_only, destructive, trusted)


class Server:
    """One server, started from its Spec, spoken to over its stdin and
    stdout. A reader thread hands each line on (one past RESOURCE_MAX,
    or that is not a JSON-RPC 2.0 object, closes it; one past LINE_MAX
    closes it unless it answers a resources/read). request() sends one
    request and waits for its answer, answering what the server asks
    meanwhile -- ping, and elicitation/create while a tools/call is in
    flight -- SERVER_ASKS_MAX times at most, and handing its
    notifications to `on_note`. A write waits WRITE_TIMEOUT at most.
    close() ends it: stdin closed, then SIGTERM and SIGKILL to its whole
    process group, whatever its leader did."""

    def __init__(self, sp, ask=None):
        if sp.problem:
            raise Refused("%s: %s" % (sp.name, sp.problem))
        self.spec, self.name, self.trusted = sp, sp.name, sp.trusted
        self.ask = ask                       # elicitation's answerer: a callable(server, params) -> result, or None
        self.asked = 0                       # questions this call
        self.calling = False                 # a tools/call in flight: the one time a question is answered
        self.next_id = 0
        self.q = queue.Queue(maxsize=QUEUE_MAX)
        self.gone = ""
        self.caps = {}
        argv = [os.path.realpath(sp.argv[0])] + sp.argv[1:]     # the program the checks read, never a link swapped since
        try:
            self.p = subprocess.Popen(argv, cwd=HOME, env=env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
        except OSError as e:
            raise Refused("%s did not start: %s" % (sp.name, e.strerror or e))
        os.set_blocking(self.p.stdin.fileno(), False)
        t = threading.Thread(target=self._read, daemon=True)
        t.start()

    def _read(self):
        try:
            while True:
                raw = self.p.stdout.readline(RESOURCE_MAX + 1)
                if not raw:
                    self.q.put(("gone", "it ended", 0))
                    return
                if len(raw) > RESOURCE_MAX:
                    self.q.put(("gone", "a message over %d kB" % (RESOURCE_MAX // 1024), 0))
                    return
                if not raw.strip():
                    continue
                try:
                    msg = json.loads(raw.decode("utf-8", "replace"))
                except (ValueError, RecursionError):
                    self.q.put(("gone", "a line that is not JSON", 0))
                    return
                if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
                    self.q.put(("gone", "a message that is not JSON-RPC 2.0", 0))
                    return
                self.q.put(("msg", msg, len(raw)))
        except (OSError, ValueError):
            self.q.put(("gone", "its output broke", 0))

    def send(self, obj):
        """One message, written within WRITE_TIMEOUT: a server that stops
        reading cannot hold spark past it."""
        data = (json.dumps(textmod.clean(obj), separators=(",", ":")) + "\n").encode("utf-8")
        fd, end = self.p.stdin.fileno(), time.monotonic() + WRITE_TIMEOUT
        try:
            while data:
                try:
                    n = os.write(fd, data)
                    data = data[n:]
                except BlockingIOError:
                    left = end - time.monotonic()
                    if left <= 0 or not select.select([], [fd], [], left)[1]:
                        self.gone = "it stopped reading"
                        raise Refused("%s: it stopped reading" % self.name)
        except (OSError, ValueError):
            self.gone = "it stopped listening"
            raise Refused("%s: it stopped listening" % self.name)

    def note(self, method, params=None):
        self.send({"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {})})

    def take(self, timeout):
        """The next message (msg, size), or None after `timeout`; Refused
        when the server is gone."""
        try:
            what, msg, size = self.q.get(timeout=timeout)
        except queue.Empty:
            return None
        if what == "gone":
            self.gone = msg
            raise Refused("%s: %s" % (self.name, msg))
        return msg, size

    def request(self, method, params, timeout, on_note=None):
        """The result of one request, or Refused: its error, the server
        gone, or `timeout` seconds without the answer -- a ceiling no
        progress extends; a cancellation goes to the server first."""
        if self.gone:
            raise Refused("%s: %s" % (self.name, self.gone))
        self.next_id += 1
        rid = self.next_id
        self.send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        end = time.monotonic() + timeout
        asks = 0
        while True:
            left = end - time.monotonic()
            if left <= 0:
                try:
                    self.note("notifications/cancelled", {"requestId": rid, "reason": "spark stopped waiting"})
                except Refused:
                    pass
                raise Refused("%s: %s took longer than %d s -- cancelled" % (self.name, method, timeout))
            got = self.take(min(left, 0.5))
            if got is None:
                continue
            msg, size = got
            mine = "method" not in msg and msg.get("id") == rid
            if size > LINE_MAX and not (mine and method == "resources/read"):
                self.gone = "a message over %d kB" % (LINE_MAX // 1024)
                raise Refused("%s: %s" % (self.name, self.gone))
            if "method" not in msg:
                if not mine:
                    continue                        # an answer to nothing spark asked
                if "error" in msg:
                    err = msg.get("error") if isinstance(msg.get("error"), dict) else {}
                    raise Refused("%s: %s" % (self.name, short(err.get("message") or "an error")))
                res = msg.get("result")
                if not isinstance(res, dict):
                    raise Refused("%s: %s answered no result" % (self.name, method))
                return res
            if "id" in msg:
                asks += 1
                if asks > SERVER_ASKS_MAX:
                    self.gone = "more than %d requests of its own in one call" % SERVER_ASKS_MAX
                    raise Refused("%s: %s" % (self.name, self.gone))
                self._answer(msg)
            elif on_note is not None:
                on_note(msg)

    def _answer(self, msg):
        """A request from the server: ping and elicitation/create are
        answered; anything else (sampling, roots) is not a method here."""
        method, rid = msg.get("method"), msg.get("id")
        if not isinstance(rid, (str, int)) or isinstance(rid, bool):
            return
        if method == "ping":
            self.send({"jsonrpc": "2.0", "id": rid, "result": {}})
        elif method == "elicitation/create":
            self.send({"jsonrpc": "2.0", "id": rid, "result": self._elicit(msg.get("params"))})
        else:
            self.send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "not a method spark answers"}})

    def _elicit(self, params):
        """A question from the server: declined outside a tools/call (the
        person has not seen a step yet), past ELICIT_PER_CALL or
        ELICIT_PER_MINUTE, with nobody to ask, or when a server that is
        not trusted asks for a credential."""
        self.asked += 1
        params = params if isinstance(params, dict) else {}
        schema = params.get("requestedSchema") if isinstance(params.get("requestedSchema"), dict) else {}
        props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        if (self.ask is None or not self.calling or self.asked > ELICIT_PER_CALL
                or (not self.trusted and any(secret(k, p) for k, p in props.items()))
                or not _ask_room()):
            return {"action": "decline"}
        try:
            return self.ask(self.name, params)
        except (EOFError, KeyboardInterrupt):
            return {"action": "cancel"}

    def initialize(self):
        """The handshake: PROTOCOL asked, PROTOCOL answered, or closed --
        a server that fails it is never left running."""
        try:
            res = self.request("initialize", {
                "protocolVersion": PROTOCOL,
                "capabilities": {"elicitation": {}},
                "clientInfo": {"name": "spark", "version": _version()}}, INIT_TIMEOUT)
            got = res.get("protocolVersion")
            if got != PROTOCOL:
                raise Refused("%s speaks MCP %s; spark speaks %s -- closed" % (self.name, short(got, 20), PROTOCOL))
            self.caps = res.get("capabilities") if isinstance(res.get("capabilities"), dict) else {}
            self.note("notifications/initialized")
        except BaseException:
            self.close()
            raise
        return self

    def tools(self):
        """[Tool] the server lists now, TOOLS_MAX at most, every page
        within one LIST_TIMEOUT; (tools, dropped)."""
        out, dropped, cursor = [], 0, None
        end = time.monotonic() + LIST_TIMEOUT
        for _ in range(PAGES_MAX):
            left = end - time.monotonic()
            if left <= 0:
                raise Refused("%s: tools/list took longer than %d s" % (self.name, LIST_TIMEOUT))
            res = self.request("tools/list", {"cursor": cursor} if cursor else {}, left)
            page_ = res.get("tools") if isinstance(res.get("tools"), list) else []
            for d in page_:
                t = tool_of(self.name, d, self.trusted)
                if t is None or len(out) >= TOOLS_MAX or any(o.name == t.name for o in out):
                    dropped += 1
                else:
                    out.append(t)
            cursor = res.get("nextCursor")
            if not isinstance(cursor, str) or not cursor:
                break
        return out, dropped

    def resources(self):
        """[(uri, name, title)] the server lists, its strings scrubbed."""
        if "resources" not in self.caps:
            return []
        res = self.request("resources/list", {}, LIST_TIMEOUT)
        out = []
        rows = res.get("resources") if isinstance(res.get("resources"), list) else []
        for d in rows[:TOOLS_MAX]:
            if isinstance(d, dict) and isinstance(d.get("uri"), str):
                out.append((short(d["uri"], 200), short(d.get("name") or "", 60), short(d.get("title") or "", 80)))
        return out

    def read(self, uri):
        """A resource's text, RESOURCE_MAX at most, scrubbed (tab and
        line feed kept)."""
        res = self.request("resources/read", {"uri": uri}, READ_TIMEOUT)
        parts, size = [], 0
        contents = res.get("contents") if isinstance(res.get("contents"), list) else []
        for c in contents:
            if not isinstance(c, dict):
                continue
            t = c.get("text") if isinstance(c.get("text"), str) else ""
            if not t and isinstance(c.get("blob"), str):
                t = "[%d bytes of %s]" % (len(c["blob"]) * 3 // 4, short(c.get("mimeType") or "data", 40))
            size += len(t.encode("utf-8", "replace"))
            if size > RESOURCE_MAX:
                raise Refused("%s: the resource is over %d kB" % (self.name, RESOURCE_MAX // 1024))
            parts.append(scrub(t, "\t\n"))
        return "\n".join(parts)

    def close(self):
        """stdin closed and STOP_WAIT for the leader, then SIGTERM to the
        whole group, STOP_WAIT more, then SIGKILL: what the server left
        running (a node under npx) goes too."""
        p = getattr(self, "p", None)
        if p is None:
            return
        try:
            p.stdin.close()
        except OSError:
            pass
        try:
            p.wait(STOP_WAIT)
        except subprocess.TimeoutExpired:
            pass
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(p.pid, sig)
            except OSError:
                break                               # the group is gone
            end = time.monotonic() + STOP_WAIT
            while time.monotonic() < end:
                try:
                    p.wait(0.1)
                except subprocess.TimeoutExpired:
                    pass
                try:
                    os.killpg(p.pid, 0)
                except OSError:
                    return
        try:
            p.wait(STOP_WAIT)
        except subprocess.TimeoutExpired:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


ASKED_FILE = os.path.join(STATE_DIR, "mcp-asked")   # when the last questions were asked: ELICIT_PER_MINUTE across processes
_ASKED = []     # the same, in this process, when the file cannot be kept


def _ask_room():
    """True, and the question counted, while fewer than ELICIT_PER_MINUTE
    were asked in the last minute -- by any spark process (ASKED_FILE,
    epochs a line, 0600), else this one's."""
    now = time.time()
    try:
        from . import state_dir
        state_dir()
        try:
            with open(ASKED_FILE, encoding="utf-8") as f:
                seen = [float(l) for l in f.read(4096).split() if re.match(r"^\d+(\.\d+)?$", l)]
        except FileNotFoundError:
            seen = []
        seen = [t for t in seen if 0 <= now - t < 60]
        ok = len(seen) < ELICIT_PER_MINUTE
        if ok:
            seen.append(now)
        fd = os.open(ASKED_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("".join("%.3f\n" % t for t in seen))
        return ok
    except (OSError, ValueError):
        _ASKED[:] = [t for t in _ASKED if now - t < 60]
        if len(_ASKED) >= ELICIT_PER_MINUTE:
            return False
        _ASKED.append(now)
        return True


def _version():
    try:
        from . import version
        return version.version()
    except Exception:       # noqa: BLE001 -- a version is no reason to fail a handshake
        return "unknown"


def start(name, ask=None, path=None):
    """A Server for the list's `name`, initialized."""
    return Server(spec(name, path), ask=ask).initialize()


# ---------------------------------------------------------------- the gate
def required(schema):
    """The schema's required names, a list of strings, or [] for a shape
    that is none."""
    req = schema.get("required") if isinstance(schema, dict) else None
    return [r for r in req if isinstance(r, str)] if isinstance(req, list) else []


def asked_later(tool, args):
    """The required credentials `args` lacks: spark asks for them through
    getpass before the call, and they are never a word on the line."""
    props = tool.schema.get("properties") or {}
    return tuple(r for r in required(tool.schema) if r not in args and secret(r, props.get(r)))


def validate(schema, args, later=()):
    """'' when `args` fit `schema`, else why not: an object; no argument
    the schema does not name; every required one there (but `later`, the
    credentials asked for before the call); each its type, its enum, its
    range and its length; no control or zero-width character in a
    string. A shape spark does not check is refused."""
    if not isinstance(args, dict):
        return "the arguments are no object"
    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    for k in args:
        if k not in props:
            return "no argument %s" % short(k, 40)
    for r in required(schema):
        if r not in args and r not in later:
            return "missing %s" % short(r, 40)
    for k, v in args.items():
        why = _value_ok(props[k], v)
        if why:
            return "%s %s" % (k, why)
    return ""


_PLAIN_BAD = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff"
                        "\u2028\u2029\u00ad\u180e\ufe00-\ufe0f\U000e0000-\U000e007f]")


def _int(v, default):
    """A schema's count as an int, `default` for anything else."""
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else default


def _value_ok(p, v, depth=0):
    if not isinstance(p, dict):
        return "is not a shape spark checks"
    if isinstance(p.get("enum"), list) and v not in p["enum"]:
        return "is not one of %s" % ", ".join(short(e, 30) for e in p["enum"][:12])
    t = p.get("type")
    if t == "string":
        if not isinstance(v, str):
            return "is text"
        if _PLAIN_BAD.search(v):
            return "holds a control character"
        lo, hi = _int(p.get("minLength"), 0), _int(p.get("maxLength"), STRING_MAX)
        if not lo <= len(v) <= hi:
            return "is %d to %d characters" % (lo, hi)
        return ""
    if t in ("integer", "number"):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or (t == "integer" and v != int(v)):
            return "is a whole number" if t == "integer" else "is a number"
        lo, hi = p.get("minimum"), p.get("maximum")
        if (isinstance(lo, (int, float)) and v < lo) or (isinstance(hi, (int, float)) and v > hi):
            return "is %s to %s" % (lo if lo is not None else "any", hi if hi is not None else "any")
        return ""
    if t == "boolean":
        return "" if isinstance(v, bool) else "is yes or no"
    if t == "array" and depth == 0:
        cap = _int(p.get("maxItems"), ARRAY_MAX)
        if not isinstance(v, list) or len(v) > cap:
            return "is a list of %d at most" % cap
        for x in v:
            why = _value_ok(p.get("items") if isinstance(p.get("items"), dict) else {}, x, 1)
            if why:
                return "holds an item that " + why
        return ""
    return "is not a shape spark checks"


def plain(schema, args):
    """The arguments with every credential gone: what a row is matched
    against, what a record digests, what a screen may show."""
    props = schema.get("properties") or {}
    return {k: v for k, v in args.items() if not secret(k, props.get(k))}


def digest(schema, args):
    """A record's digest of the arguments: sha256 over plain()'s JSON,
    sorted, its first 16 hex digits."""
    blob = json.dumps(plain(schema, args), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def rows_of(srv):
    """The calls a server's rows resource names ([(name, arguments, ask)]),
    or None when it lists no rows resource (the desktop providers' rows
    schema: {"rows": [{"tool": {"name", "arguments", "ask"}, "more":
    [...]}]}). A rows resource listed that does not read, or is not that
    shape, is Refused: the rule is never skipped in silence."""
    res = [r for r in srv.resources() if r[1] == "rows"]
    if not res:
        return None
    try:
        d = json.loads(srv.read(res[0][0]))
    except (ValueError, RecursionError):
        d = None
    if not isinstance(d, dict) or not isinstance(d.get("rows"), list):
        raise Refused("%s: its rows do not read, so no step of it is checked -- not run" % srv.name)
    out = []
    for row in d["rows"]:
        if not isinstance(row, dict):
            continue
        more = row.get("more") if isinstance(row.get("more"), list) else []
        for c in [row.get("tool")] + more:
            if isinstance(c, dict) and isinstance(c.get("name"), str) and isinstance(c.get("arguments"), dict):
                ask = [a for a in c.get("ask") if isinstance(a, str)] if isinstance(c.get("ask"), list) else []
                out.append((c["name"], c["arguments"], ask))
    return out


def rows_gate(tool, args, rows):
    """'' and the row's ask list when the call may go: where the rows
    name this tool with its required arguments, the call names one of
    them exactly (credentials aside); where none does, it is free."""
    if rows is None:
        return "", []
    req = required(tool.schema)
    naming = [(a, ask) for n, a, ask in rows if n == tool.name and all(k in a for k in req)]
    if not naming:
        return "", []
    mine = plain(tool.schema, args)
    for a, ask in naming:
        if plain(tool.schema, a) == mine:
            return "", ask
    return "%s names nothing %s lists now" % (tool.name, tool.server), []


def words_args(tool, words):
    """KEY=VALUE words as the tool's arguments, each value typed by its
    schema: a number, yes|no, a comma list, else text. ValueError says
    which word does not fit. A credential is never a word on the line."""
    props = tool.schema.get("properties") or {}
    out = {}
    for w in words:
        k, eq, v = w.partition("=")
        if not eq or not ARG_WORD.match(k):
            raise ValueError("%s is not KEY=VALUE" % short(w, 40))
        if k not in props:
            raise ValueError("%s takes no %s" % (tool.name, k))
        if secret(k, props[k]):
            raise ValueError("%s is a credential: never a word on the line -- spark asks for it" % k)
        out[k] = _typed(props[k], v)
    return out


def _typed(p, v):
    t = p.get("type") if isinstance(p, dict) else None
    if t == "integer":
        try:
            return int(v)
        except ValueError:
            return v
    if t == "number":
        try:
            return float(v) if any(c in v for c in ".eE") else int(v)
        except ValueError:
            return v
    if t == "boolean":
        return {"yes": True, "true": True, "on": True, "no": False, "false": False, "off": False}.get(v.lower(), v)
    if t == "array":
        return [_typed(p.get("items") or {}, x) for x in v.split(",") if x != ""]
    return v


# --------------------------------------------------------------- the call
class Result:
    __slots__ = ("text", "error")

    def __init__(self, text, error):
        self.text, self.error = text, error


def result_text(res):
    """A tools/call result as text, scrubbed: the text items, the
    structured content as JSON, a line naming any other item."""
    parts = []
    for c in res.get("content") or []:
        if not isinstance(c, dict):
            continue
        if c.get("type") == "text" and isinstance(c.get("text"), str):
            parts.append(c["text"])
        else:
            parts.append("[%s]" % short(c.get("type") or "an item", 20))
    sc = res.get("structuredContent")
    if isinstance(sc, dict) and not parts:
        parts.append(json.dumps(sc, sort_keys=True))
    out = scrub("\n".join(parts), "\t\n")
    return out if len(out) <= RESULT_MAX else out[:RESULT_MAX] + "\n[... cut at %d kB]" % (RESULT_MAX // 1024)


def record(server, tool, schema, args, error):
    """The sealed audit record of one tools/call: names and a digest."""
    from . import audit, users
    try:
        why = audit.record("mcp/call", who=users.account()[0] or "-", server=server, tool=tool,
                           args=digest(schema, args), error=bool(error))
    except Exception:           # noqa: BLE001 -- the record never stops the call or replaces its result
        log_exc("mcp record")
        return
    if why and sys.stderr.isatty():
        sys.stderr.write("! %s -- the call stands\n" % why)
    elif why:
        log_exc("mcp record: " + why)


def prepare(srv, tool_name, args=None, words=None):
    """(tool, args, ask): the gate before a call, all but the person --
    the tool in the list now, the arguments (`words` typed by its schema
    when no `args`) by its schema, the rows. Refused, or ValueError for a
    word that is not KEY=VALUE of this tool."""
    tools, _dropped = srv.tools()
    tool = next((t for t in tools if t.name == tool_name), None)
    if tool is None:
        raise Refused("%s is not a tool of %s now -- spark mcp %s lists them" % (short(tool_name, 64), srv.name, srv.name))
    if args is None:
        args = words_args(tool, words or [])
    why = validate(tool.schema, args, later=asked_later(tool, args))
    if why:
        raise Refused("%s %s: %s" % (srv.name, tool.name, why))
    why, ask = rows_gate(tool, args, rows_of(srv))
    if why:
        raise Refused(why)
    return tool, args, ask


def invoke(srv, tool, args, progress=None):
    """One tools/call, its record, its Result. `progress(message)` hears
    the server's progress for this call alone, while it increases."""
    token = "spark-" + secrets.token_hex(8)
    last = [None]

    def on_note(msg):
        if msg.get("method") != "notifications/progress" or progress is None:
            return
        pr = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        n = pr.get("progress")
        if pr.get("progressToken") != token or isinstance(n, bool) or not isinstance(n, (int, float)):
            return
        if last[0] is not None and n <= last[0]:
            return
        last[0] = n
        progress(short(pr.get("message") or "", 60))
    error = True
    srv.calling, srv.asked = True, 0
    try:
        res = srv.request("tools/call", {"name": tool.name, "arguments": args, "_meta": {"progressToken": token}},
                          CALL_TIMEOUT, on_note=on_note)
        error = res.get("isError") is True
        return Result(result_text(res), error)
    finally:
        srv.calling = False
        record(srv.name, tool.name, tool.schema, args, error)


def call_line(server, tool, args=None, words=None, sure=False, tty=None, out=None):
    """`spark mcp call` and do's tool step: start, gate, ask, call. (rc,
    text): 0 the tool's result, 1 the tool's own error or a refusal (the
    text says which), 2 a word that is not KEY=VALUE of the tool. `sure`
    is a person's yes already given (do's typed yes on this very step).
    `tty` False means nobody is at a terminal to ask."""
    tty = (sys.stdin.isatty() and sys.stderr.isatty()) if tty is None else tty
    out = out or sys.stderr
    busy = textmod.Busy(out if tty else None, kind="march")

    def asking(name, params):
        busy.stop()                     # the march never draws over a question
        return _ask_at_prompt(name, params)
    try:
        with start(server, ask=asking if tty else None) as srv:
            try:
                t, args, ask = prepare(srv, tool, args, words)
            except ValueError as e:
                return 2, str(e)
            if t.needs_yes() and not sure:
                if not tty:
                    raise Refused("%s %s asks a typed yes -- run it at a terminal" % (server, tool))
                out.write("  %s\n" % shown(t, args))
                why = "%s does not vouch for it" % server if not t.trusted else "%s says it can destroy" % server
                if ask_line("  %s -- type yes to run it: " % why).strip() != "yes":
                    return 1, "%s %s: not run" % (server, tool)
            for a in list(ask) + [x for x in asked_later(t, args) if x not in ask]:
                prop = (t.schema.get("properties") or {}).get(a)
                if a in args or not secret(a, prop):
                    continue
                if not tty:
                    raise Refused("%s %s asks for its %s -- run it at a terminal" % (server, tool, a))
                v = getpass.getpass("  %s %s: " % (server, a))
                if v:
                    args = dict(args, **{a: v})
            why = validate(t.schema, args)      # the whole call now, a credential typed included
            if why:
                raise Refused("%s %s: %s" % (server, tool, why))
            with busy:
                r = invoke(srv, t, args)
            return (1 if r.error else 0), r.text
    except Refused as e:
        return 1, e.hint


def shown(tool, args):
    """The call as a person reads it: server, tool, its words, credentials
    held."""
    words = " ".join("%s=%s" % (k, _word(v)) for k, v in plain(tool.schema, args).items())
    return ("%s %s %s" % (tool.server, tool.name, words)).rstrip()


def _word(v):
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, list):
        return ",".join(_word(x) for x in v)
    return short(v, 80)


def ask_line(prompt):
    """One line from the person: the prompt on stderr, so a piped stdout
    carries the result alone. EOF raises EOFError."""
    sys.stderr.write(prompt)
    sys.stderr.flush()
    line = sys.stdin.readline()
    if not line:
        raise EOFError
    return line.rstrip("\n")


def _ask_at_prompt(server, params):
    """elicitation/create answered as a question at the prompt: the
    server's name and its message, then each field; a credential through
    getpass, never echoed. Enter on a required field cancels."""
    schema = params.get("requestedSchema") if isinstance(params.get("requestedSchema"), dict) else {}
    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    req = set(required(schema))
    sys.stderr.write("  %s asks: %s\n" % (server, short(params.get("message") or "", ELICIT_MESSAGE_MAX)))
    sys.stderr.flush()
    content = {}
    for k, p in list(props.items())[:8]:
        if not ARG_WORD.match(str(k)) or not isinstance(p, dict):
            return {"action": "decline"}
        label = short(p.get("title") or k, 40)
        if isinstance(p.get("enum"), list):
            label += " (%s)" % "|".join(short(e, 20) for e in p["enum"][:8])
        elif p.get("type") == "boolean":
            label += " (yes|no)"
        raw = getpass.getpass("  %s: " % label) if secret(k, p) else ask_line("  %s: " % label)
        if raw == "":
            if k in req:
                return {"action": "cancel"}
            continue
        v = _typed(p, raw.strip() if not secret(k, p) else raw)
        if _value_ok(p, v):
            return {"action": "cancel"}
        content[k] = v
    return {"action": "accept", "content": content}


# ------------------------------------------------------ the tools, on disk
def tool_line(t):
    """One line of TOOLS_FILE: server, tool, flags (r reads only, y asks
    the typed yes), the required arguments as KEY=KIND, the title."""
    flags = ("t" if t.trusted else "") + ("r" if t.read_only and t.trusted else "") + ("y" if t.needs_yes() else "")
    req = " ".join("%s=%s" % (k, kd) for k, kd, r in t.args() if r)
    return "\t".join((t.server, t.name, flags or "-", req or "-", t.title or "-"))


_ARG = re.compile(r"^[a-z][a-z0-9_]{0,31}=(?:N|TEXT|yes\|no|A,B|[A-Za-z0-9_.|-]{1,120})$")
_LINE = re.compile(r"^([a-z][a-z0-9_]{0,31})\t([a-z][a-z0-9_]{0,63})\t(t?r?y?|-)\t([^\t]{1,200})\t([^\t]{1,80})$")


def tool_lines(path=None):
    """[(server, tool, flags, args, title)] from TOOLS_FILE, read line by
    line, never sourced: a line of another shape is dropped, and so is a
    server no longer on the list."""
    try:
        with open(path or TOOLS_FILE, encoding="utf-8", errors="replace") as f:
            raw = f.read(64 * 1024).splitlines()
    except OSError:
        return []
    try:
        on = {s.name for s in specs() if not s.problem}
    except (SystemExit, Refused):
        return []
    out = []
    for line in raw:
        m = _LINE.match(line)
        if not m or m.group(1) not in on:
            continue
        server, tool, flags, args, title = m.groups()
        if title != "-" and not TITLE.match(title):
            continue
        if args != "-" and not all(_ARG.match(a) for a in args.split(" ")):
            continue
        out.append((server, tool, "" if flags == "-" else flags, "" if args == "-" else args, "" if title == "-" else title))
    return out


def write_tools(lines):
    """TOOLS_FILE written whole, 0600, through a temp file renamed."""
    from . import state_dir
    state_dir()
    tmp = TOOLS_FILE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")
    os.replace(tmp, TOOLS_FILE)


def brief_tools():
    """The tool lines a shell brief carries (persona.prefix): '' when no
    tool is listed, or under SPARK_LINE_BENCH (a measured run grounds in
    its own snapshot). Names, the required arguments and the titles --
    never a description -- BRIEF_MAX characters at most, whole lines."""
    if os.environ.get("SPARK_LINE_BENCH") == "1":
        return ""
    lines = tool_lines()
    if not lines:
        return ""
    parts, used = [], 0
    for server, tool, flags, args, title in lines:
        title = title if "t" in flags else ""   # a server not trusted: its titles never ride
        p = "spark mcp call %s %s%s%s" % (server, tool, " " + args if args else "",
                                          " -- " + title if title else "")
        if used + len(p) + 2 > BRIEF_MAX:
            break
        parts.append(p)
        used += len(p) + 2
    return ("MCP tools on this machine: a step that one of them does is that spark mcp call line, "
            "KEY=VALUE for each argument: " + "; ".join(parts) + ".")


CALL_WORDS = re.compile(r"(?:^|[;&|(`{\n]\s*|\b(?:then|do|else|env|exec|nohup|time)\s+)(?:\S*/)?spark\s+mcp\s+call\s+([a-z][a-z0-9_]{0,31})\s+([a-z][a-z0-9_]{0,63})\b")


def line_danger(command):
    """True when a line runs a tool that asks the typed yes, by the tools
    `spark mcp` last listed -- or a tool it has not listed at all."""
    hits = CALL_WORDS.findall(command or "")
    if not hits:
        return False
    flags = {(s, t): f for s, t, f, _a, _ti in tool_lines()}
    return any("y" in flags.get(h, "y") for h in hits)


def call_words(command):
    """(server, tool, [KEY=VALUE]) when the whole of `command` is one
    `spark mcp call` line of plain words, else None: what do runs as a
    tool step itself."""
    import shlex
    if not command or "\n" in command or re.search(r"[;&|<>`$(){}\\]", command):
        return None
    try:
        w = shlex.split(command)
    except ValueError:
        return None
    if len(w) < 5 or os.path.basename(w[0]) != "spark" or w[1:3] != ["mcp", "call"]:
        return None
    if not NAME.match(w[3]) or not TOOL_NAME.match(w[4]):
        return None
    return w[3], w[4], w[5:]


# ----------------------------------------------------------------- the verb
def _refuse(why, rc=2):
    say("%s mcp -- %s" % (MARK, why))
    return rc


def _list_one(sp, verbose):
    """The lines for one server, and its tool lines for TOOLS_FILE."""
    head = "%-10s %-12s %s" % (sp.name, "trusted" if sp.trusted else "not trusted", home_short(" ".join(sp.argv)))
    if verbose:
        head += "\n  %s" % sp.why
    if sp.problem:
        return [head, "  ! %s" % sp.problem], []
    try:
        with Server(sp).initialize() as srv:
            tools, dropped = srv.tools()
            res = srv.resources() if verbose else []
    except Refused as e:
        return [head, "  ! %s" % e.hint], []
    lines = [head]
    for t in tools:
        req = " ".join("%s=%s" % (k, kd) for k, kd, r in t.args() if r)
        opt = " ".join("[%s=%s]" % (k, kd) for k, kd, r in t.args() if not r)
        mark = "reads" if t.read_only and t.trusted else ("asks yes" if t.needs_yes() else "")
        call = ("%s %s %s" % (t.name, req, opt) if verbose else "%s %s" % (t.name, req)).rstrip()
        lines.append(("  %-30s %-28s %s" % (call, t.title, mark)).rstrip())
    if dropped:
        lines.append("  ! %d tool%s not offered: a name, title or schema spark does not take"
                     % (dropped, "" if dropped == 1 else "s"))
    for uri, name, title in res:
        lines.append(("  resource %-21s %s" % (uri, title or name)).rstrip())
    return lines, [tool_line(t) for t in tools]


def cmd_list(name=None):
    all_specs = specs()
    if name is not None:
        try:
            sp = spec(name)
        except Refused as e:
            return _refuse(e.hint)
        lines, tl = _list_one(sp, True)
        _merge_tools(sp.name, tl)
        page("\n".join(lines))
        return 0
    if not all_specs:
        say("mcp      no server on the list -- spark mcp add NAME PATH [WORDS]")
        write_tools([])
        return 0
    out, tl = [], []
    for sp in all_specs:
        lines, t = _list_one(sp, False)
        out.extend(lines)
        tl.extend(t)
    write_tools(tl)
    page("\n".join(out))
    return 0


def _merge_tools(server, lines):
    """TOOLS_FILE with `server`'s lines replaced by `lines`."""
    others = []
    try:
        with open(TOOLS_FILE, encoding="utf-8", errors="replace") as f:
            others = [l.rstrip("\n") for l in f if not l.startswith(server + "\t")]
    except OSError:
        pass
    try:
        write_tools(others + list(lines))
    except OSError:
        log_exc("mcp tools file")


def _key(name):
    return "MCP_SERVER_" + name.upper()


def _write(**kv):
    """The list's keys set (a value None drops its line), 0600."""
    from . import site
    lines = []
    try:
        with open(MCP_ENV, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        pass
    drop = {k for k, v in kv.items() if v is None}
    lines = [l for l in lines if l.split("=", 1)[0] not in drop]
    put = {k: v for k, v in kv.items() if v is not None}
    if put:
        site.set_keys(_file=MCP_ENV, _quiet=True, **put)
        return
    os.makedirs(os.path.dirname(MCP_ENV), exist_ok=True)
    fd = os.open(MCP_ENV, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + ("\n" if lines else ""))
    os.chmod(MCP_ENV, 0o600)


def cmd_add(words):
    if len(words) < 2:
        return _refuse("add takes a name and a program: spark mcp add NAME /absolute/path [WORDS]")
    name, argv = words[0], words[1:]
    if not NAME.match(name) or name.endswith(TRUST_SUFFIX.lower()):
        return _refuse("a name is a letter, then letters, digits or _ (32 at most), not ending in _trust")
    bad = [w for w in argv if not re.match(r"^[^\s;`$()|&<>\"']+$", w)]
    if bad:
        return _refuse("%s cannot ride in the list: no quotes, spaces or ;`$()|&<>" % short(bad[0], 40))
    why = program_problem(argv[0])
    if why:
        return _refuse(why)
    if any(s.name == name for s in specs()):
        return _refuse("%s is on the list already -- spark mcp rm %s first" % (name, name))
    _write(**{_key(name): '"%s"' % " ".join(argv)})
    sp = spec(name)
    lines, tl = _list_one(sp, False)
    _merge_tools(name, tl)
    say("* %s is on the list, %s" % (name, sp.why))
    page("\n".join(lines))
    return 0


def cmd_rm(words):
    if len(words) != 1:
        return _refuse("rm takes a name: spark mcp rm NAME")
    try:
        spec(words[0])
    except Refused as e:
        return _refuse(e.hint)
    _write(**{_key(words[0]): None, _key(words[0]) + TRUST_SUFFIX: None})
    _merge_tools(words[0], [])
    say("* %s is off the list" % words[0])
    return 0


def cmd_trust(words):
    if len(words) not in (1, 2) or (len(words) == 2 and words[1] not in ("on", "off")):
        return _refuse("trust takes a name, then on or off: spark mcp trust NAME [on|off]")
    try:
        sp = spec(words[0])
    except Refused as e:
        return _refuse(e.hint)
    if len(words) == 1:
        say("%-10s %s" % (sp.name, sp.why))
        return 0
    _write(**{_key(sp.name) + TRUST_SUFFIX: "yes" if words[1] == "on" else "no"})
    sp = spec(words[0])
    lines, tl = _list_one(sp, False)
    _merge_tools(sp.name, tl)
    say("* %s is %s" % (sp.name, sp.why))
    return 0


def cmd_call(words):
    if len(words) < 2:
        return _refuse("call takes a server and a tool: spark mcp call NAME TOOL [KEY=VALUE ...]")
    server, tool, rest = words[0], words[1], words[2:]
    if not NAME.match(server) or not TOOL_NAME.match(tool):
        return _refuse("call takes a server and a tool: spark mcp call NAME TOOL [KEY=VALUE ...]")
    rc, text = call_line(server, tool, words=rest)
    if rc == 2:
        return _refuse(text)
    if text:
        (sys.stdout if rc == 0 else sys.stderr).write(text.rstrip("\n") + "\n")
    return rc


def cmd_read(words):
    watch = "--watch" in words
    words = [w for w in words if w != "--watch"]
    if not words or len(words) > 2:
        return _refuse("read takes a server, then a resource: spark mcp read NAME [URI] [--watch]")
    try:
        with start(words[0]) as srv:
            if len(words) == 1:
                rows = srv.resources()
                if not rows:
                    say("%-10s no resources" % srv.name)
                for uri, name, title in rows:
                    say(("%-36s %s" % (uri, title or name)).rstrip())
                return 0
            uri = words[1]
            say(srv.read(uri).rstrip("\n"))
            if not watch:
                return 0
            if not (srv.caps.get("resources") or {}).get("subscribe"):
                say("! %s does not say when it changes" % srv.name)
                return 1
            changed = threading.Event()

            def on_note(msg):
                pr = msg.get("params") if isinstance(msg.get("params"), dict) else {}
                if msg.get("method") == "notifications/resources/updated" and pr.get("uri") == uri:
                    changed.set()
            srv.request("resources/subscribe", {"uri": uri}, LIST_TIMEOUT)
            while True:
                _pump(srv, on_note, 1.0)
                if changed.is_set():
                    changed.clear()
                    say("")
                    say(srv.read(uri).rstrip("\n"))
    except Refused as e:
        say("! " + e.hint)
        return 1
    except KeyboardInterrupt:
        return 0


def _pump(srv, on_note, seconds):
    """The server's notifications for `seconds`, answering its requests."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            what, msg = srv.q.get(timeout=max(0.05, end - time.monotonic()))
        except queue.Empty:
            return
        if what == "gone":
            srv.gone = msg
            raise Refused("%s: %s" % (srv.name, msg))
        if "method" in msg:
            if "id" in msg:
                srv._answer(msg)
            else:
                on_note(msg)


def main(args):
    if args[:1] and args[0] in ("-h", "--help", "help"):
        say(USAGE.rstrip())
        return 0
    try:
        return _main(args)
    except Refused as e:
        sys.stderr.write("! %s\n" % e.hint)
        return 1


def _main(args):
    sub, rest = (args[0], args[1:]) if args else ("", [])
    if sub in ("", "status", "list"):
        return cmd_list() if not rest else _refuse("spark mcp lists every server; spark mcp NAME shows one")
    if sub == "add":
        return cmd_add(rest)
    if sub == "rm":
        return cmd_rm(rest)
    if sub == "trust":
        return cmd_trust(rest)
    if sub == "call":
        return cmd_call(rest)
    if sub == "read":
        return cmd_read(rest)
    if NAME.match(sub) and not rest:
        return cmd_list(sub)
    return _refuse("no %s here: spark mcp -h" % short(sub, 40))
