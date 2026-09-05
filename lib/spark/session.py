# spark.session -- the turns on disk, and the Session that asks a brain
# and retries once with a fresh resolution when the cached one is gone.

import json
import os
import time

from . import TURNS_DIR, log_exc, state_dir
from . import forge, persona, wire


def _turns_dir():
    state_dir()
    os.makedirs(TURNS_DIR, exist_ok=True)
    try:
        os.chmod(TURNS_DIR, 0o700)
    except OSError:
        pass
    return TURNS_DIR


# Turns are telemetry: numbers, enums, ids -- never what was said. The
# words live only in the sealed threads; this is the one choke point that
# keeps free text out of the turn log, whatever a caller passes.
TEXT_FIELDS = ("line", "command", "hint", "answer", "cwd", "context")


def record(cfg, **fields):
    """Append one turn to today's JSONL (0600). SPARK_HISTORY=off keeps none."""
    if cfg.history <= 0:
        return
    try:
        for k in TEXT_FIELDS:
            fields.pop(k, None)
        fields["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
        path = os.path.join(_turns_dir(), time.strftime("%Y-%m-%d") + ".jsonl")
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(json.dumps(fields, ensure_ascii=False) + "\n")
    except OSError:
        log_exc("record turn")


def prune(cfg):
    """Delete turn files older than SPARK_HISTORY days."""
    try:
        cutoff = time.time() - cfg.history * 86400
        for name in os.listdir(TURNS_DIR):
            p = os.path.join(TURNS_DIR, name)
            if name.endswith(".jsonl") and os.path.getmtime(p) < cutoff:
                os.remove(p)
    except OSError:
        pass


def clear():
    n = 0
    try:
        for name in os.listdir(TURNS_DIR):
            if name.endswith(".jsonl"):
                os.remove(os.path.join(TURNS_DIR, name))
                n += 1
    except OSError:
        pass
    return n


def last_turn():
    try:
        names = sorted(n for n in os.listdir(TURNS_DIR) if n.endswith(".jsonl"))
        for name in reversed(names):
            with open(os.path.join(TURNS_DIR, name), encoding="utf-8") as f:
                lines = [l for l in f.read().splitlines() if l.strip()]
            if lines:
                return json.loads(lines[-1])
    except (OSError, ValueError):
        pass
    return None


def _resolve(cfg, fresh):
    """The default brain: whatever wire finds, its cache dropped on a retry."""
    if fresh:
        wire.drop_cache()
    return wire.resolve_brain(cfg, fresh=fresh)


class Session:
    def __init__(self, cfg, mode, shell, cwd="", history=None, brain=None, mem=None):
        """`brain` is a callable(fresh) -> wire.Brain, else wire.resolve_brain:
        the FORGE passes its own upstream so an in-process reply never
        resolves to the FORGE itself. `mem` names whose remembered facts
        ride the identity (memory.store_of); None is this machine's own."""
        self.cfg, self.mode, self.shell, self.cwd = cfg, mode, shell, cwd
        self.mem = mem
        # The rule: the prompt line is spark; every sentence is an ember.
        # Every request names its role in the `model` field.
        self.role = "spark" if mode == "line" else "ember"
        self.history = list(history or [])      # earlier turns of a continued thread
        self.timings = {}
        self._brain = brain or (lambda fresh: _resolve(cfg, fresh))
        self.url, self.model, self.forge = self._brain(False)

    def _system(self):
        """The identity (soul, memory) rides only with the ember. The
        spark role gets machine facts + the mode, nowhere the identity
        (a FORGE passes a spark request through untouched). An ember
        against a FORGE gets prefix + mode (the FORGE adds the identity);
        an ember against a raw server gets the whole thing."""
        if self.role == "spark" or self.forge:
            return persona.mode_prefix(self.cfg, self.mode, self.shell) + "\n\n" + persona.MODES[self.mode]
        return forge.system(self.cfg, self.mode, self.shell, self.mem)

    def _messages(self, text, context=""):
        # the [cwd] line is for the modes that propose commands relative
        # to it; in a conversation it is noise a chatty model narrates
        # back ("your current working directory is ...")
        cwd = self.cwd if self.mode in ("line", "do", "explain") else ""
        return ([{"role": "system", "content": self._system()}]
                + self.history
                + [{"role": "user", "content": persona.user_message(text, cwd, context)}])

    def _retry_fresh(self, fn):
        """A cached brain may have gone away: on `down`, resolve once more
        and try again; any other error is the answer."""
        try:
            return fn()
        except wire.BrainError as e:
            if e.kind != "down":
                raise
            self.url, self.model, self.forge = self._brain(True)
            return fn()

    def ask_json(self, text, schema=None):
        """One JSON reply shaped by `schema` (the line's by default)."""
        t0 = time.time()
        schema = schema or persona.LINE_SCHEMA
        reply, self.timings = self._retry_fresh(lambda: wire.chat_json(self.cfg, self.url, self._messages(text), schema, forge=self.forge, model=self.role))
        return reply, int((time.time() - t0) * 1000)

    def ask_stream(self, text, context, on_delta):
        t0 = time.time()
        out, self.timings = self._retry_fresh(lambda: wire.chat_stream(self.cfg, self.url, self._messages(text, context), on_delta, forge=self.forge, model=self.role))
        return out, int((time.time() - t0) * 1000)

    def answered_model(self):
        """The stem of the model this session's role got: the roles map
        from the brain cache, or /v1/models once; the brain's default
        (the spark role's stem, contract 5) only as the last resort."""
        if getattr(self, "_role_model", None):
            return self._role_model
        m = self.model
        try:
            rs = wire.brain_roles(self.cfg)
            if self.role not in rs:
                rs = dict((a, st) for a, st, _l in wire.models(self.cfg, self.url, forge=self.forge))
            m = rs.get(self.role) or self.model
        except Exception:
            pass
        self._role_model = m
        return m

    def record(self, **fields):
        """One turn, with the throughput the server reported for it."""
        record(self.cfg, backend=self.url, model=self.answered_model(), mode=self.mode, **dict(getattr(self, "timings", {}) or {}, **fields))
