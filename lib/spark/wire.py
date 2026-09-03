# spark.wire -- HTTP to a llama-server: the token, /health, which server
# answers (the brain), and the two chat shapes: JSON-constrained for the
# prompt, streamed for the CLI. Nothing here spawns anything.

import collections
import json
import os
import time
import urllib.error
import urllib.request

from . import BRAIN_CACHE, EMBER_TOKEN_FILE, IS_MAC, SERVE_URL_FILE, debug, forge_url, run, state_dir

HEALTH_TIMEOUT = 2.0
CACHE_TTL = 60

# What answers: a raw llama-server (forge False, bearer = api-token) or a
# FORGE in front of one (forge True, bearer = forge-token, identity added
# there). Unpacks as (url, model, forge).
Brain = collections.namedtuple("Brain", "url model forge")


class BrainError(Exception):
    """kind: down | loading | auth | bad | timeout ; hint: one line for a human"""

    def __init__(self, kind, hint):
        super().__init__(hint)
        self.kind, self.hint = kind, hint


# ------------------------------------------------------------------ token
def api_key(cfg):
    """SPARK_API_KEY from the environment (tests, one-offs), else the 0600
    token file. Empty when there is none."""
    key = os.environ.get("SPARK_API_KEY", "")
    if key:
        return key
    try:
        with open(cfg.token_file, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def forge_token(cfg):
    """The token a FORGE client sends: SPARK_FORGE_TOKEN from the
    environment, else the 0600 forge-token file (admin), else the 0600
    ember-token file (user) -- a machine that only received the user token
    still talks /v1 and chat. Empty when there is none."""
    key = os.environ.get("SPARK_FORGE_TOKEN", "")
    if key:
        return key
    for path in (cfg.forge_token_file, EMBER_TOKEN_FILE):
        try:
            with open(path, encoding="utf-8") as f:
                tok = f.read().strip()
            if tok:
                return tok
        except OSError:
            pass
    return ""


def ensure_token(cfg):
    """Create the api-token file if missing (O_EXCL, 0600); repair its mode
    if loose. Returns the token. Never prints it."""
    return ensure_token_file(cfg.token_file)


def ensure_token_file(path):
    """The same for any token file (the FORGE has its own)."""
    try:
        with open(path, encoding="utf-8") as f:
            tok = f.read().strip()
        if tok:
            st = os.stat(path)
            if st.st_mode & 0o077:
                os.chmod(path, 0o600)
            return tok
    except OSError:
        pass
    import secrets
    state_dir()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tok = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(tok + "\n")
    return tok


def _headers(cfg, extra=None, forge=False):
    """The request headers: the api-token for a llama-server, the
    forge-token for a FORGE."""
    h = {"Content-Type": "application/json"}
    key = forge_token(cfg) if forge else api_key(cfg)
    if key:
        h["Authorization"] = "Bearer " + key
    if extra:
        h.update(extra)
    return h


def _auth_hint(cfg, url, forge):
    if forge:
        return ("token rejected by %s -- copy that machine's ember-token here (spark forge --print-client there), or set SPARK_FORGE_TOKEN"
                % url)
    return "token rejected by %s -- copy the serving machine's %s here, or set SPARK_API_KEY" % (url, cfg.token_file)


# ----------------------------------------------------------------- health
def health(url, timeout=HEALTH_TIMEOUT):
    """'ok' | 'loading' | 'down' for a llama-server base URL"""
    try:
        with urllib.request.urlopen(urllib.request.Request(url + "/health"), timeout=timeout) as r:
            return "ok" if r.status == 200 else "down"
    except urllib.error.HTTPError as e:
        return "loading" if e.code == 503 else "down"
    except (urllib.error.URLError, OSError, ValueError):
        return "down"


def forge_health(url, timeout=HEALTH_TIMEOUT):
    """GET /api/health: the FORGE's answer (a dict with "forge": true), or
    "down" when nothing listens there, or None for anything that is not a
    FORGE (a llama-server says 404, or 503 while loading)."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url + "/api/health"), timeout=timeout) as r:
            d = json.load(r)
        return d if isinstance(d, dict) and d.get("forge") is True else None
    except urllib.error.HTTPError:
        return None
    except (urllib.error.URLError, OSError, ValueError):
        return "down"


def request_headers(cfg):
    """The headers a plain llama-server request takes (the api-token)."""
    return _headers(cfg)


def _stem(s):
    return os.path.basename(str(s)).replace(".gguf", "")


def models(cfg, url, timeout=HEALTH_TIMEOUT, forge=False):
    """[(alias, file stem, loaded)] from /v1/models. The router lists one
    entry per role (id = the alias, status.value loaded|unloaded, the
    file in status.args after --model); a single server lists its one
    model (id = the file stem, `spark` among its aliases, loaded); a
    FORGE (forge=True: the forge-token goes on) proxies its upstream's.
    BrainError(auth) when the token is refused; [] when nothing answers."""
    try:
        req = urllib.request.Request(url + "/v1/models", headers=_headers(cfg, forge=forge))
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
        out = []
        for e in d["data"]:
            st = e.get("status") if isinstance(e.get("status"), dict) else {}
            args = st.get("args") if isinstance(st.get("args"), list) else []
            stem = _stem(args[args.index("--model") + 1]) if "--model" in args[:-1] else ""
            names = [e["id"]] + [a for a in (e.get("aliases") or []) if isinstance(a, str)]
            alias = "spark" if "spark" in names else ("ember" if "ember" in names else e["id"])
            if not stem:
                stem = _stem(next((n for n in names if n not in ("spark", "ember")), e["id"]))
            loaded = st.get("value", "loaded") == "loaded" if st else True
            out.append((alias, stem, loaded))
        return out
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise BrainError("auth", _auth_hint(cfg, url, forge))
        return []
    except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, TypeError):
        return []


def model_name(cfg, url, timeout=HEALTH_TIMEOUT):
    """The spark role's model, by file stem (contract 5): the entry aliased
    spark, else the first one. "?" when the server does not say."""
    rows = models(cfg, url, timeout)
    for alias, stem, _loaded in rows:
        if alias == "spark":
            return stem
    return rows[0][1] if rows else "?"


# ------------------------------------------------------------------ brain
def serve_url():
    try:
        with open(SERVE_URL_FILE, encoding="utf-8") as f:
            return f.read().strip().rstrip("/")
    except OSError:
        return ""


def candidates(cfg):
    """Where to look, in order: a hard client URL alone; else the preferred
    peer, then the FORGE `spark forge` bound here, then whatever `spark
    serve` bound here, then loopback."""
    if cfg.base_url:
        return [cfg.base_url]
    out = []
    for u in (cfg.prefer_url, forge_url(), serve_url(), cfg.loopback_url()):
        if u and u not in out:
            out.append(u)
    return out


def _read_cache(key):
    try:
        with open(BRAIN_CACHE, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("key") == key and time.time() - d["t"] < CACHE_TTL:
            return Brain(d["url"], d["model"], bool(d.get("forge")))
    except (OSError, ValueError, KeyError):
        pass
    return None


def _write_cache(key, url, model, forge, roles=None):
    try:
        state_dir()
        with open(BRAIN_CACHE, "w", encoding="utf-8") as f:
            json.dump({"t": time.time(), "key": key, "url": url, "model": model,
                       "forge": forge, "roles": roles or {}}, f)
    except OSError:
        pass


def brain_roles(cfg):
    """{role: model file stem} of the cached brain, {} when unknown. The
    turn log records the model that answered, not the brain's default."""
    try:
        with open(BRAIN_CACHE, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("key") == "|".join(candidates(cfg)) and time.time() - d["t"] < CACHE_TTL:
            return d.get("roles") or {}
    except (OSError, ValueError, KeyError):
        pass
    return {}


def drop_cache():
    try:
        os.remove(BRAIN_CACHE)
    except OSError:
        pass


def no_brain_hint(cfg):
    """One honest line: how to get a brain on this machine."""
    if cfg.base_url:
        return "no answer from SPARK_BASE_URL %s" % cfg.base_url
    if cfg.prefer_url:
        return "no answer from the peer %s -- is it up? (spark serve starts a local brain)" % cfg.prefer_url
    from . import engine
    st = engine.service_state(cfg)
    if st == "loaded":
        if IS_MAC:
            dom = engine.service_domain(cfg)
            return "no brain awake -- %slaunchctl kickstart -k %s" % ("sudo " if dom == "system" else "", engine.service_target(cfg))
        return "no brain awake -- systemctl --user restart spark-serve"
    if st == "disabled":
        return "no brain awake -- the service is disabled on purpose; `spark serve` starts one by hand"
    m = engine.model_file(cfg)
    if not m:
        return "no brain awake -- no model in %s (./bootstrap.sh downloads one)" % cfg.models_dir
    gb = os.path.getsize(m) / 2**30
    return "no brain awake -- `spark serve` loads %s (%.1f GB)" % (os.path.basename(m), gb)


def resolve_brain(cfg, fresh=False):
    """Brain(url, model, forge) of the first candidate that answers: a
    FORGE whose /api/health says its upstream is ok, or a llama-server
    whose /health is 200. Cached for 60 s, keyed on the candidate list so
    a different SPARK_BASE_URL in this shell is never answered from
    another shell's cache."""
    cands = candidates(cfg)
    key = "|".join(cands)
    if not fresh:
        hit = _read_cache(key)
        if hit:
            return hit
    loading = None
    for url in cands:
        fh = forge_health(url)
        if fh == "down":
            debug("health %s -> down" % url)
            continue
        if fh:
            up = fh.get("upstream", "ok")
            debug("forge %s -> upstream %s" % (url, up))
            if up == "ok":
                b = Brain(url, str(fh.get("model") or "?"), True)
                _write_cache(key, b.url, b.model, True, fh.get("roles"))
                return b
            if up == "loading" and not loading:
                loading = url
            continue
        st = health(url)
        debug("health %s -> %s" % (url, st))
        if st == "ok":
            model = model_name(cfg, url)
            try:
                rs = dict((a, st) for a, st, _l in models(cfg, url))
            except (BrainError, Exception):
                rs = {}
            _write_cache(key, url, model, False, rs)
            return Brain(url, model, False)
        if st == "loading" and not loading:
            loading = url
    if loading:
        raise BrainError("loading", "loading the model (about 30 s) -- ask again in a moment")
    raise BrainError("down", no_brain_hint(cfg))


# ------------------------------------------------------------------- chat
def _post(cfg, url, body, timeout, stream=False, forge=False):
    data = json.dumps(body).encode()
    req = urllib.request.Request(url + "/v1/chat/completions", data=data, headers=_headers(cfg, forge=forge))
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise BrainError("auth", _auth_hint(cfg, url, forge))
        if e.code == 503:
            raise BrainError("loading", "%s is still loading its model" % url)
        detail = ""
        try:
            detail = e.read().decode(errors="replace")[:200]
        except OSError:
            pass
        raise BrainError("bad", "%s answered HTTP %d %s" % (url, e.code, detail))
    except urllib.error.URLError as e:
        reason = str(getattr(e, "reason", e))
        if "timed out" in reason:
            raise BrainError("timeout", "%s took longer than %ss" % (url, timeout))
        raise BrainError("down", "%s: %s" % (url, reason))
    except OSError as e:
        if "timed out" in str(e):
            raise BrainError("timeout", "%s took longer than %ss" % (url, timeout))
        raise BrainError("down", "%s: %s" % (url, e))


def chat_json(cfg, url, messages, schema, max_tokens=200, temperature=0.2, forge=False, model=None):
    """One JSON object shaped by `schema`, parsed. `model` names the role
    the request is for (spark | ember); the caller decides, the wire
    only carries it. None sends no model field at all."""
    body = {"messages": messages, "max_tokens": max_tokens, "temperature": temperature,
            "stream": False, "cache_prompt": True,
            "response_format": {"type": "json_schema", "json_schema": {"name": "spark_line", "schema": schema}}}
    if model is not None:
        body["model"] = model
    with _post(cfg, url, body, cfg.timeout, forge=forge) as r:
        try:
            d = json.load(r)
            text = d["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError):
            raise BrainError("bad", "%s returned something that is not a chat completion" % url)
    try:
        return json.loads(text), timings_of(d)
    except ValueError:
        raise BrainError("bad", "the model did not return JSON: %s" % text[:80].replace("\n", " "))


def timings_of(d):
    """llama-server's per-request throughput, as spark records it: tokens
    in, tokens out, tokens per second each way, prompt-cache hits."""
    t = d.get("timings") if isinstance(d, dict) else None
    if not isinstance(t, dict):
        return {}
    out = {}
    for src, dst in (("prompt_n", "pp_n"), ("prompt_per_second", "pp_tps"), ("predicted_n", "tg_n"),
                     ("predicted_per_second", "tg_tps"), ("cache_n", "cache_n")):
        v = t.get(src)
        if isinstance(v, (int, float)):
            out[dst] = round(v, 1) if isinstance(v, float) else v
    return out


def chat_stream(cfg, url, messages, on_delta, max_tokens=600, temperature=0.3, forge=False, model=None):
    """Stream the answer through on_delta(text); returns (text, timings).
    `model` as in chat_json: the role, or None for no model field."""
    body = {"messages": messages, "max_tokens": max_tokens, "temperature": temperature,
            "stream": True, "cache_prompt": True}
    if model is not None:
        body["model"] = model
    out, timings = [], {}
    with _post(cfg, url, body, cfg.timeout, stream=True, forge=forge) as r:
        for raw in r:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
            except ValueError:
                continue
            if "timings" in chunk:
                timings = timings_of(chunk)
            try:
                delta = chunk["choices"][0]["delta"].get("content") or ""
            except (KeyError, IndexError, TypeError):
                continue
            if delta:
                out.append(delta)
                on_delta(delta)
    return "".join(out), timings
