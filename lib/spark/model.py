# spark.model -- the AI-infrastructure verbs: `spark model` (which model
# this machine serves: the table, a choice, budget, rm, add, verify) and
# `spark ember` (the conversational model, the second role from the same
# table). Each writes the site.env key, then applies it (site.set_keys,
# site.apply) and restarts the server that must follow.

import json
import math
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from . import CONFIG_DIR, HOME, IS_MAC, MARK, REPO, config, confirm, glyph, mem_total_gb, paged, say, wait_ready
from .site import apply, set_keys


def _downloads_pending(cfg):
    """The chosen roles' model files not on disk yet: models.env rows."""
    from . import engine
    pair = engine.chosen_rows(cfg)
    out = []
    for role in engine.ROLES:
        r = pair.get(role)
        if r and not os.path.isfile(os.path.join(cfg.models_dir, r[1])):
            out.append(r)
    return out


def _announce_downloads(pend):
    """One row per pending download, before bootstrap runs: what, how big."""
    for r in pend:
        say("ok     download     %s (%.1f GB)%s" % (
            r[1], r[3] / 2**30,
            " -- curl's progress bar follows" if sys.stdout.isatty() else ""))


# ------------------------------------------------------------------ model
MODEL_USAGE = """%s model -- which model this machine serves

  spark model                   the table: size, RAM, license, tested,
                                downloaded, serving, tok/s; the spark pick
                                marked *, the ember +, your own rows u
  spark model NAME              choose it: site.env, download, server restart
                                (a row not under Apache-2.0 or MIT prints
                                its license and asks first)
  spark model auto | none       auto: the largest tested open-license row
                                that fits (smallest beside an ember);
                                none: no model here
  spark model budget [N]        percent of RAM+GPU auto may use (10-95)
  spark model rm NAME           delete a downloaded file that is not in use
  spark model add URL           add your own: --sha256 HEX (non-HF URLs need
                                it), --license "NAME URL" (required); writes
                                ~/.config/spark/models.env, downloads it
  spark model verify            sha256 every downloaded file now; exit 1 on
                                a mismatch (spark check's models row is the
                                cached, daily version of this)

  On a client (spark client URL) the table is the peer's and every choice
  is refused: choose there, or spark client off to serve here again.
""" % MARK


def _client_no(cfg, what):
    """The one line a client answers to a model choice: nothing is served
    here, so a budget, a model or an ember chosen here would silently
    make this machine a server (that is spark client off, by name)."""
    say("%s %s -- a client of %s serves nothing; choose on the peer, or spark client off to serve here again"
        % (MARK, what, cfg.peer_ai_url))
    return 2


def peer_models(cfg):
    """The peer's own model table: GET /api/models on the FORGE, with the
    login token (any role). None when the peer is down, a bare
    llama-server, or a FORGE older than this route."""
    from . import wire
    try:
        req = Request(cfg.peer_ai_url.rstrip("/") + "/api/models", headers=wire._headers(cfg, forge=True))
        with urlopen(req, timeout=wire.HEALTH_TIMEOUT) as r:
            d = json.load(r)
        return d if isinstance(d, dict) and isinstance(d.get("models"), list) else None
    except (HTTPError, URLError, OSError, ValueError):
        return None


def _restart_server(cfg):
    from . import engine, wire
    st = engine.service_state(cfg)
    if st == "loaded":
        if IS_MAC and engine.service_domain(cfg) == "system":
            say(engine.daemon_note(cfg))
            return
        say("ok     server       restarting -- the model loads again (about 30 s) ...")
        engine.service_stop(noreload=False)
        engine.wait_gone(engine.server_pids(cfg.port), 30)
        engine.kickstart(cfg)
        url = wire.serve_url() or cfg.loopback_url()
        if wait_ready("", lambda: wire.health(url) == "ok", 180, 2):
            say("ok     server       ready")
        else:
            say("todo   server       not ready yet -- spark check --watch 5 follows it")
        from . import check
        check.refresh()
    elif engine.pidfile_pid():
        from . import serve
        serve.cmd_stop([])
        serve.cmd_serve([])
    else:
        say("ok     server       not running -- the next spark serve uses it")


SOURCE_MARKS = {"repo": " ", "user": "u"}


def model_rows(cfg, serving=None):
    """The model table as data: [{name, gb, ram_gb, fits, downloaded,
    chosen, role, serving, speed, speed_kind, source, mark, tested,
    license, open, note}] in model_tables() order (the list, then yours).
    `role` is "spark", "ember" or "" from engine.chosen_rows. `source` is
    "repo" or "user"; `mark` is the second column's glyph (SOURCE_MARKS:
    blank, `u` yours); `tested` says the row was proven on the line and
    `open` that its license is one auto may take (config.is_open).
    `serving` is the model name a brain answers with; None
    asks the brain (the FORGE passes its own). `speed` is tok/s and
    `speed_kind` "measured" or "estimate" (engine.speed_of)."""
    from . import engine, wire
    # a client serves nothing: its own RAM is no budget, so `fits` is None
    budget = None if cfg.client else mem_total_gb() * cfg.ai_budget / 100.0
    pair = engine.chosen_rows(cfg)
    chosen = pair["spark"][1] if pair.get("spark") else ""
    role_of = {}
    for role in engine.ROLES:
        r = pair.get(role)
        if r and r[1] not in role_of:
            role_of[r[1]] = role
    if serving is None:
        serving = ""
        try:
            serving = wire.resolve_brain(cfg).model
        except wire.BrainError:
            pass
    out = []
    for row in config.model_tables():
        name, fname, _url, nbytes, _sha, ram, source, tested, license_, note = row
        speed, kind = engine.speed_of(cfg, row)
        out.append({"name": name, "gb": round(nbytes / 2**30, 1), "ram_gb": ram, "fits": (ram <= budget) if budget is not None else None,
                    "downloaded": os.path.isfile(os.path.join(cfg.models_dir, fname)),
                    "chosen": fname == chosen, "role": role_of.get(fname, ""),
                    "serving": bool(serving) and fname.replace(".gguf", "") == serving,
                    "speed": speed, "speed_kind": kind, "source": source,
                    "mark": SOURCE_MARKS.get(source, " "), "tested": tested,
                    "license": license_, "open": config.is_open(license_), "note": note})
    return out


def model_line(r, marks=None, width=13):
    """One table row: the pick mark (spark *, ember +), the source mark
    (blank the list, `u` yours), the name, the file size, the RAM verdict,
    the license's first word (`open` marks one auto may take), `line` when
    the row was proven on the line, downloaded / serving, and the speed --
    `~N tok/s` an estimate, `N tok/s` measured; nothing for a row that
    does not fit. `width` pads the name column (the caller widens it past
    13 for a longer name). Every row stays within 80 columns."""
    marks = marks or {"spark": "*", "ember": "+"}
    state = "serving" if r["serving"] else ("downloaded" if r["downloaded"] else "")
    if r["fits"] is None:
        speed = ""                       # a client: the peer's business
    else:
        speed = ("%s%d tok/s" % ("~" if r["speed_kind"] == "estimate" else "", r["speed"])) if r["fits"] else "too big"
    lic = ((r["license"] or "").split() or [""])[0][:10]
    # padded columns, right-aligned numbers: the eye reads a table, not a
    # sentence; 57 + width columns, so a 23-char name still fits 80
    return ("  %s%s %-*s %5.1f GB %2.0f GB %-10s %-4s %-10s %9s"
            % (marks.get(r["role"], " "), r["mark"], width, r["name"], r["gb"], r["ram_gb"],
               lic, "line" if r["tested"] else "", state, speed)).rstrip()


def print_model_table(cfg):
    """The one table `spark model list` and `spark ember list` share:
    every row of models.env and yours with its RAM verdict, the spark pick
    marked * and the ember pick + (the marks bootstrap.sh --list-models
    draws), a second mark `u` for your own rows, the license's first word,
    `line` on a row proven on the line (auto reads only those, under an
    open license), and a last column with the generation speed: `~N
    tok/s` an estimate for this backend, `N tok/s` measured here (spark
    bench, or a real turn); nothing for a row that does not fit. A row's
    note follows it, indented. Every row stays within 80 columns."""
    from . import engine
    if cfg.client:
        # a client: never this machine's RAM. The peer's table when its
        # FORGE answers /api/models (the box's RAM, budget, picks,
        # speeds); else the rows alone, no verdict
        peer = peer_models(cfg)
        if peer:
            say("%s model -- a client of %s: the peer's table: %.0f GB for models, budget %.0f GB (%d%%), %s" % (
                MARK, cfg.peer_ai_url, peer.get("total_gb", 0), peer.get("budget_gb", 0),
                peer.get("budget_pct", 0), peer.get("backend", "?")))
            if peer.get("cap_note"):
                say("  " + peer["cap_note"])
            rows = peer["models"]
        else:
            say("%s model -- a client of %s: nothing is served here; what fits is the peer's business (spark model there)" % (
                MARK, cfg.peer_ai_url))
            rows = model_rows(cfg)
    else:
        budget = mem_total_gb() * cfg.ai_budget / 100.0
        say("%s model -- SITE_AI_MODEL=%s SITE_EMBER_MODEL=%s%s%.0f GB for models (RAM + GPU), budget %.0f GB (%d%%), %s" % (
            MARK, cfg.model_choice, cfg.ember_model, glyph("sep"), mem_total_gb(), budget, cfg.ai_budget, engine.backend(cfg)))
        note = engine.cap_note(cfg)
        if note:
            say("  " + note)
        rows = model_rows(cfg)
    width = max([13] + [len(r["name"]) for r in rows])
    say("     %-*s %8s %5s %-10s %-4s %-10s %9s" % (width, "model", "file", "RAM", "license", "line", "", "fits"))
    for r in rows:
        say(model_line(r, width=width))
        if r["note"]:
            say("      " + r["note"])
    known = {row[1] for row in config.model_tables()}
    others = [f for f in os.listdir(cfg.models_dir) if f.endswith(".gguf") and f not in known] if os.path.isdir(cfg.models_dir) else []
    for f in others:
        say("    %-13s %5.1f GB file   (not in models.env; SPARK_MODEL=%s serves it)" % (
            "-", os.path.getsize(os.path.join(cfg.models_dir, f)) / 2**30, f))
    say("  * = spark (the prompt line), + = ember (conversations), u = yours")
    say("  auto picks among the rows tested on the line (line) under %s" % " or ".join(config.OPEN_LICENSES))
    return 0


def _license_ok(row, verb):
    """A row under a license auto would not take (config.is_open: not
    Apache-2.0 or MIT) prints its license line -- and its note, when
    there is one -- and gets a yes before the download: SPARK_YES=1 in
    the environment, or stdin not a tty (a script, a pipe), counts as yes
    without asking. An open-license row downloads without a question."""
    name, license_, note = row[0], row[8], row[9]
    if config.is_open(license_):
        return True
    say("%s license: %s" % (name, license_ or "none on file"))
    if note:
        say("  " + note)
    if os.environ.get("SPARK_YES") == "1" or not sys.stdin.isatty():
        return True
    if not confirm("download it"):
        say("spark %s: cancelled" % verb)
        return False
    return True


# ------------------------------------------------------------------ add
QUANT_RE = re.compile(r"-(q4-k-m|q5-k-m|q8-0|f16|bf16|iq[0-9][a-z0-9-]*)$")
USER_MODELS_FILE = os.path.join(CONFIG_DIR, "models.env")


def _short(path):
    return "~" + path[len(HOME):] if path.startswith(HOME + "/") else path


def _source_file(source):
    return USER_MODELS_FILE if source == "user" else os.path.join(REPO, "models.env")


def _model_name(fname):
    """The file stem, lowercased, dots and underscores to dashes, a
    trailing quantization token stripped: Qwen_Qwen3-4B-Q4_K_M.gguf ->
    qwen-qwen3-4b."""
    stem = os.path.splitext(fname)[0].lower().replace(".", "-").replace("_", "-")
    return QUANT_RE.sub("", stem)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _head(url, extra_headers=None, follow=True):
    """(headers, error) -- a HEAD request through urllib; redirects
    followed and the final response's headers returned, or, with
    follow=False, the FIRST response's headers even when it is a 3xx
    (huggingface.co puts the file's size and sha256 on its redirect, and
    the CDN it points at knows neither). error is a one-line reason, or
    None."""
    req = Request(url, method="HEAD", headers=dict(extra_headers or {}, **{"User-Agent": "spark"}))
    opener = urlopen if follow else build_opener(_NoRedirect()).open
    try:
        with opener(req, timeout=20) as resp:
            return resp.headers, None
    except HTTPError as e:
        if not follow and 300 <= e.code < 400:
            return e.headers, None
        return None, "could not reach %s -- %s" % (url, e)
    except (URLError, OSError) as e:
        return None, "could not reach %s -- %s" % (url, e)


def _probe_model_url(url, sha):
    """(bytes, sha256, error) for `spark model add URL`: huggingface.co is
    auto-verified from its LFS headers (x-linked-size, x-linked-etag, on
    the redirect it answers with); any other host needs --sha256 and its
    size from a plain HEAD."""
    host = urlsplit(url).hostname or ""
    if host == "huggingface.co":
        hurl = url + ("&download=true" if "?" in url else "?download=true")
        headers, err = _head(hurl, follow=False)
        if err:
            return None, None, err
        size = headers.get("x-linked-size")
        etag = (headers.get("x-linked-etag") or "").strip('"').lower()
        if not size or not re.match(r"^[0-9a-f]{64}$", etag):
            return None, None, "not an LFS file -- add --sha256 HEX"
        return int(size), etag, None
    if not sha:
        return None, None, "%s is not huggingface.co -- add --sha256 HEX" % host
    if not re.match(r"^[0-9a-fA-F]{64}$", sha):
        return None, None, "--sha256 needs 64 hex characters"
    headers, err = _head(url)
    if err:
        return None, None, err
    size = headers.get("Content-Length")
    if not size:
        return None, None, "%s answered no Content-Length" % url
    return int(size), sha.lower(), None


def _model_add(args):
    url = sha = license_ = None
    it = iter(args)
    for a in it:
        if a == "--sha256":
            sha = next(it, None)
        elif a == "--license":
            license_ = next(it, None)
        elif url is None:
            url = a
        else:
            say(MODEL_USAGE.rstrip())
            return 2
    if not url:
        say(MODEL_USAGE.rstrip())
        return 2
    if not license_:
        say('spark model add: --license "NAME URL" is required -- your own row states its license too')
        return 2
    bad = re.search(r"[;`$()|&<>]", license_)
    if bad:
        # contract 3 refuses the whole file over one such character, and
        # then every verb dies with exit 2 -- refuse it before it lands
        say("spark model add -- the license cannot hold %s (contract 3); use -- or , instead" % bad.group(0))
        return 2
    nbytes, sha256, err = _probe_model_url(url, sha)
    if err:
        say("spark model add: %s" % err)
        return 2
    fname = os.path.basename(urlsplit(url).path)
    if not fname:
        say("spark model add: %s has no file name" % url)
        return 2
    name = _model_name(fname)
    if not name:
        say("spark model add: %s has no name once the quantization is stripped" % fname)
        return 2
    existing = {r[0]: r[6] for r in config.model_tables()}
    if name in existing:
        say("spark model add: %s is already in %s" % (name, _short(_source_file(existing[name]))))
        return 2
    ram_gb = math.ceil(nbytes / 2**30 * 1.1 + 1.5)
    stem = name.upper().replace("-", "_")
    set_keys(_file=USER_MODELS_FILE, _quiet=True, **{
        "MODEL_" + stem: '"%s %s %d %s %d"' % (fname, url, nbytes, sha256, ram_gb),
        "MODEL_" + stem + "_LICENSE": '"%s"' % license_})
    say("ok     model        added %s (%.1f GB, ram %d GB) -- %s" % (
        name, nbytes / 2**30, ram_gb, _short(USER_MODELS_FILE)))
    return cmd_model([name])


def cmd_model(args):
    from . import engine
    cfg = config.load()
    if args and args[0] in ("-h", "--help", "help"):
        say(MODEL_USAGE.rstrip())
        return 0
    if args[0:1] == ["add"]:
        return _model_add(args[1:])
    if args[0:1] == ["verify"]:
        from . import verify
        rows = verify.verify_all(cfg, force=True)
        if not rows:
            say("spark model verify: no downloaded model")
            return 0
        bad = False
        width = max(12, max(len(r["name"]) for r in rows))
        for r in rows:
            if r["status"] == "ok":
                say("%-7s%-*s sha256 ok (%.1f GB)" % ("ok", width, r["name"], r["bytes"] / 2**30))
            else:
                bad = True
                say("%-7s%-*s sha256 MISMATCH -- spark model rm %s; spark model %s" % (
                    "bad", width, r["name"], r["name"], r["name"]))
        return 1 if bad else 0
    rows = config.model_tables()
    if not args or args[0] in ("list", "status"):
        return paged(lambda: print_model_table(cfg))
    if args[0] == "budget":
        if len(args) == 1:
            if cfg.client:
                return print_model_table(cfg)
            gb = mem_total_gb() * cfg.ai_budget / 100.0
            say("%s model budget -- %d%% of %.0f GB = %.0f GB" % (MARK, cfg.ai_budget, mem_total_gb(), gb))
            return print_model_table(cfg)
        if len(args) != 2 or not args[1].isdigit() or not 10 <= int(args[1]) <= 95:
            say(MODEL_USAGE.rstrip())
            return 2
        if cfg.client:
            return _client_no(cfg, "model budget")
        set_keys(SITE_AI_BUDGET=args[1])
        pend = [] if os.environ.get("SPARK_NO_APPLY") else _downloads_pending(config.load())
        _announce_downloads(pend)
        rc = apply(["model", "ember"], stream=bool(pend))
        if rc != 0:
            return rc
        if not os.environ.get("SPARK_NO_APPLY"):
            cfg = config.load()
            if engine.model_file(cfg):
                _restart_server(cfg)
            else:
                say("ok     server       nothing to serve -- left as it is")
        return print_model_table(config.load())
    if args[0] == "rm":
        if len(args) != 2:
            say(MODEL_USAGE.rstrip())
            return 2
        if cfg.client:
            return _client_no(cfg, "model rm")
        match = [r for r in rows if r[0] == args[1]]
        fname = match[0][1] if match else args[1]
        path = os.path.join(cfg.models_dir, fname)
        if not os.path.isfile(path):
            say("spark model: %s is not downloaded -- nothing to remove" % fname)
            return 2
        if fname == engine.chosen_model_name(cfg) or path == engine.model_file(cfg):
            say("spark model: %s is in use -- choose another first" % fname)
            return 1
        os.remove(path)
        say("ok     removed      %s" % path)
        return 0
    name = args[0]
    match = [r for r in rows if r[0] == name]
    if name not in ("auto", "none") and not match:
        say("spark model: no model named %s -- one of: auto none %s" % (name, " ".join(r[0] for r in rows)))
        return 2
    if cfg.client:
        return _client_no(cfg, "model")
    if match and not _license_ok(match[0], "model"):
        return 1
    set_keys(SITE_AI_MODEL=name)
    pend = [] if os.environ.get("SPARK_NO_APPLY") else _downloads_pending(config.load())
    _announce_downloads(pend)
    rc = apply(["model"], stream=bool(pend))
    if rc != 0:
        return rc
    if os.environ.get("SPARK_NO_APPLY"):
        return 0
    cfg = config.load()
    if name == "none" or not engine.model_file(cfg):
        say("ok     server       nothing to serve -- left as it is")
        return 0
    _restart_server(cfg)
    return 0


# ------------------------------------------------------------------ ember
EMBER_USAGE = """%s ember -- the conversational model

  spark ember                   the two roles: model, file, loaded or not
  spark ember NAME              choose it: site.env, download, server restart
  spark ember auto              the largest that fits beside the spark model
  spark ember none              no second model -- spark answers everything
  spark ember list              the model table, the spark pick marked *,
                                the ember + (the same table as spark model)
""" % MARK


def cmd_ember(args):
    from . import engine, wire
    cfg = config.load()
    if args and args[0] in ("-h", "--help", "help"):
        say(EMBER_USAGE.rstrip())
        return 0
    if args and args[0] == "list":
        return paged(lambda: print_model_table(cfg))
    if not args or args[0] == "status":
        pair = engine.chosen_rows(cfg)
        files = engine.roles(cfg)
        url = wire.serve_url()
        status = engine.models_status(cfg, url) if url and wire.health(url) == "ok" else {}
        say("%s ember -- SITE_EMBER_MODEL=%s" % (MARK, cfg.ember_model))
        for role in engine.ROLES:
            f, r = files[role], pair.get(role)
            if not f and not r:
                say("  %-5s  none -- %s" % (role, "spark answers everything (spark ember NAME adds one)"
                                            if role == "ember" else "no model (./bootstrap.sh downloads one)"))
            elif f:
                say(("  %-5s  %-14s %5.1f GB  %s" % (role, engine.model_stem(f),
                                                     os.path.getsize(f) / 2**30, status.get(role, ""))).rstrip())
            else:
                say("  %-5s  %-14s not downloaded (./bootstrap.sh)" % (role, r[1].replace(".gguf", "")))
        return 0
    name = args[0]
    rows = config.model_tables()
    match = [r for r in rows if r[0] == name]
    if name not in ("auto", "none") and not match:
        say("spark ember: no model named %s -- one of: auto none %s   (spark ember list)" % (name, " ".join(r[0] for r in rows)))
        return 2
    if cfg.client:
        return _client_no(cfg, "ember")
    if match and not _license_ok(match[0], "ember"):
        return 1
    set_keys(SITE_EMBER_MODEL=name)
    pend = [] if os.environ.get("SPARK_NO_APPLY") else _downloads_pending(config.load())
    _announce_downloads(pend)
    rc = apply(["model", "ember"], stream=bool(pend))
    if rc != 0:
        return rc
    if os.environ.get("SPARK_NO_APPLY"):
        return 0
    cfg = config.load()
    if not engine.model_file(cfg):
        say("ok     server       nothing to serve -- left as it is")
        return 0
    _restart_server(cfg)
    return 0
